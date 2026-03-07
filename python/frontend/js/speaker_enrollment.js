(function() {
    'use strict';

    // ========== Speaker Verification — Voice Profile ==========

    async function loadSpeakerStatus() {
        const badge = document.getElementById('speaker-status-badge');
        const setupBtn = document.getElementById('speaker-setup-btn');
        const enhanceBtn = document.getElementById('speaker-enhance-btn');
        const deleteBtn = document.getElementById('speaker-delete-btn');
        if (!badge) return;

        try {
            const status = await API.getSpeakerStatus();
            if (status.enrolled) {
                badge.textContent = 'Active';
                badge.className = 'speaker-badge speaker-badge-active';
                setupBtn.textContent = 'Re-enroll Voice Profile';
                if (enhanceBtn) enhanceBtn.style.display = 'block';
                deleteBtn.style.display = 'block';
            } else {
                badge.textContent = 'Not Set Up';
                badge.className = 'speaker-badge speaker-badge-inactive';
                setupBtn.textContent = 'Set Up Voice Profile';
                if (enhanceBtn) enhanceBtn.style.display = 'none';
                deleteBtn.style.display = 'none';
            }

        } catch (e) {
            console.error('Failed to load speaker status:', e);
            badge.textContent = 'Unavailable';
            badge.className = 'speaker-badge speaker-badge-inactive';
        }
    }

    // Enrollment state
    let enrollmentState = {
        currentStep: 1,
        totalSteps: 5,
        moodLabels: ['neutral', 'animated', 'calm', 'reading', 'on_a_call'],
        mediaRecorder: null,
        audioStream: null,
        audioContext: null,
        analyserNode: null,
        animFrameId: null,
        chunks: [],
        isRecording: false,
        isListening: false,
        speechStartTime: null,
        smoothedRms: 0,
    };

    async function startEnrollment() {
        const overlay = document.getElementById('enrollment-overlay');
        overlay.style.display = 'flex';

        // Reset state
        enrollmentState.currentStep = 1;
        enrollmentState.chunks = [];
        enrollmentState.isRecording = false;

        // Reset enrollment on server
        try {
            await API.resetSpeakerEnrollment();
        } catch (e) {
            console.error('Failed to reset enrollment:', e);
        }

        updateEnrollmentUI();

        // Wire up buttons
        document.getElementById('enrollment-close-btn').onclick = closeEnrollment;
        document.getElementById('enrollment-finish-btn').onclick = () => {
            closeEnrollment();
            loadSpeakerStatus();
        };
    }

    function closeEnrollment() {
        const overlay = document.getElementById('enrollment-overlay');
        overlay.style.display = 'none';
        stopRecordingCleanup();
    }

    function updateEnrollmentUI() {
        const step = enrollmentState.currentStep;
        const total = enrollmentState.totalSteps;

        // Update step dots
        document.querySelectorAll('.step-dot').forEach(dot => {
            const s = parseInt(dot.dataset.step);
            dot.className = 'step-dot';
            if (s < step) dot.classList.add('complete');
            else if (s === step) dot.classList.add('active');
        });

        // Show correct step content
        for (let i = 1; i <= total; i++) {
            const el = document.getElementById(`enrollment-step-${i}`);
            if (el) el.classList.toggle('active', i === step);
        }

        // Reset recorder UI
        const countdown = document.getElementById('enrollment-countdown');
        const statusLabel = document.getElementById('enrollment-status-label');
        countdown.className = 'enrollment-countdown';
        countdown.textContent = '10';
        if (statusLabel) statusLabel.textContent = 'Preparing microphone...';

        // Reset level bars
        document.querySelectorAll('#enrollment-level-bars .level-bar').forEach(bar => {
            bar.classList.remove('active');
            bar.style.height = '4px';
        });

        // Show recorder, hide processing/done
        document.getElementById('enrollment-recorder').style.display = 'block';
        document.getElementById('enrollment-processing').style.display = 'none';
        document.getElementById('enrollment-done').style.display = 'none';
        document.getElementById('enrollment-steps').querySelector('.step-indicators').style.display = 'flex';

        // Auto-start listening for this step
        startListening();
    }

    async function startListening() {
        if (enrollmentState.isListening || enrollmentState.isRecording) return;

        const statusLabel = document.getElementById('enrollment-status-label');

        try {
            // Request microphone access
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    sampleRate: 16000,
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                }
            });
            enrollmentState.audioStream = stream;

            // Set up audio context
            const audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
            enrollmentState.audioContext = audioCtx;
            const source = audioCtx.createMediaStreamSource(stream);
            const analyser = audioCtx.createAnalyser();
            analyser.fftSize = 256;
            source.connect(analyser);
            enrollmentState.analyserNode = analyser;

            // Use ScriptProcessorNode to capture raw PCM at 16kHz
            const bufferSize = 4096;
            const scriptNode = audioCtx.createScriptProcessor(bufferSize, 1, 1);
            enrollmentState.chunks = [];

            scriptNode.onaudioprocess = (e) => {
                if (!enrollmentState.isRecording) return; // Only capture during recording phase
                const channelData = e.inputBuffer.getChannelData(0);
                const int16 = new Int16Array(channelData.length);
                for (let i = 0; i < channelData.length; i++) {
                    const s = Math.max(-1, Math.min(1, channelData[i]));
                    int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                }
                enrollmentState.chunks.push(int16);
            };

            source.connect(scriptNode);
            scriptNode.connect(audioCtx.destination);
            enrollmentState.scriptNode = scriptNode;
            enrollmentState.sourceNode = source;

            enrollmentState.isListening = true;
            enrollmentState.speechStartTime = null;
            enrollmentState.smoothedRms = 0;

            if (statusLabel) statusLabel.textContent = 'Start speaking when ready...';

            // Start level bar animation (runs during both listening and recording)
            drawEnrollmentLevelBars();

        } catch (e) {
            console.error('Microphone access denied:', e);
            if (statusLabel) statusLabel.textContent = 'Microphone access required';
        }
    }

    function beginRecording() {
        if (enrollmentState.isRecording) return;

        const countdown = document.getElementById('enrollment-countdown');
        const statusLabel = document.getElementById('enrollment-status-label');

        enrollmentState.isRecording = true;
        enrollmentState.isListening = false;
        enrollmentState.chunks = [];

        if (statusLabel) statusLabel.textContent = 'Recording...';
        countdown.className = 'enrollment-countdown active';

        // Countdown timer
        let remaining = 10;
        countdown.textContent = remaining;

        const countdownInterval = setInterval(() => {
            remaining--;
            countdown.textContent = remaining;
            if (remaining <= 0) {
                clearInterval(countdownInterval);
                finishRecordingStep();
            }
        }, 1000);

        enrollmentState.countdownInterval = countdownInterval;
    }

    async function finishRecordingStep() {
        enrollmentState.isRecording = false;

        // Stop waveform animation
        if (enrollmentState.animFrameId) {
            cancelAnimationFrame(enrollmentState.animFrameId);
            enrollmentState.animFrameId = null;
        }

        // Combine PCM chunks into single buffer
        const totalLength = enrollmentState.chunks.reduce((acc, c) => acc + c.length, 0);
        const combined = new Int16Array(totalLength);
        let offset = 0;
        for (const chunk of enrollmentState.chunks) {
            combined.set(chunk, offset);
            offset += chunk.length;
        }

        // Stop audio stream
        stopRecordingCleanup();

        const step = enrollmentState.currentStep;
        const moodLabel = enrollmentState.moodLabels[step - 1];
        const statusLabel = document.getElementById('enrollment-status-label');

        if (statusLabel) statusLabel.textContent = 'Uploading...';

        try {
            // Send raw PCM bytes to server
            const result = await Promise.race([
                API.enrollSpeakerSample(combined.buffer, moodLabel),
                new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 30000))
            ]);

            if (step < enrollmentState.totalSteps) {
                // Move to next step
                enrollmentState.currentStep = step + 1;
                updateEnrollmentUI();
            } else {
                // All samples collected — compute centroid
                showEnrollmentProcessing();
                const enrollResult = await Promise.race([
                    API.completeSpeakerEnrollment(),
                    new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 30000))
                ]);
                showEnrollmentDone();
                // Hide enrollment-required banner
                const banner = document.getElementById('enrollment-required-banner');
                if (banner) banner.style.display = 'none';
            }
        } catch (e) {
            console.error('Enrollment step failed:', e);
            const isLoading = e.status === 503 || (e.message && e.message.includes('loading'));
            if (isLoading) {
                if (statusLabel) {
                    statusLabel.textContent = 'Models still loading — please wait...';
                    statusLabel.removeAttribute('data-retry');
                }
                setTimeout(() => startListening(), 3000);
                return;
            }
            const msg = e.message === 'timeout'
                ? 'Request timed out — tap to retry'
                : 'Failed — tap to retry';
            if (statusLabel) {
                statusLabel.textContent = msg;
                statusLabel.setAttribute('data-retry', 'true');
                statusLabel.onclick = () => {
                    statusLabel.onclick = null;
                    statusLabel.removeAttribute('data-retry');
                    startListening();
                };
            }
        }
    }

    function stopRecordingCleanup() {
        enrollmentState.isRecording = false;
        enrollmentState.isListening = false;
        enrollmentState.speechStartTime = null;
        enrollmentState.smoothedRms = 0;

        if (enrollmentState.countdownInterval) {
            clearInterval(enrollmentState.countdownInterval);
            enrollmentState.countdownInterval = null;
        }

        if (enrollmentState.animFrameId) {
            cancelAnimationFrame(enrollmentState.animFrameId);
            enrollmentState.animFrameId = null;
        }

        if (enrollmentState.scriptNode) {
            try { enrollmentState.scriptNode.disconnect(); } catch (e) {}
            enrollmentState.scriptNode = null;
        }
        if (enrollmentState.sourceNode) {
            try { enrollmentState.sourceNode.disconnect(); } catch (e) {}
            enrollmentState.sourceNode = null;
        }

        if (enrollmentState.audioContext) {
            try { enrollmentState.audioContext.close(); } catch (e) {}
            enrollmentState.audioContext = null;
        }

        if (enrollmentState.audioStream) {
            enrollmentState.audioStream.getTracks().forEach(t => t.stop());
            enrollmentState.audioStream = null;
        }
    }

    function showEnrollmentProcessing() {
        document.getElementById('enrollment-recorder').style.display = 'none';
        document.getElementById('enrollment-processing').style.display = 'block';
        // Hide step content
        for (let i = 1; i <= 3; i++) {
            const el = document.getElementById(`enrollment-step-${i}`);
            if (el) el.classList.remove('active');
        }
    }

    function showEnrollmentDone() {
        document.getElementById('enrollment-processing').style.display = 'none';
        document.getElementById('enrollment-done').style.display = 'block';
        document.getElementById('enrollment-steps').querySelector('.step-indicators').style.display = 'none';
    }

    // ========== Enhance Voice Profile ==========

    const enhancePrompts = [
        "Speak as if you're on a video call — slightly louder and clearer than normal.",
        "Talk softly, as if someone is sleeping nearby.",
        "Describe what you had for lunch today, with natural energy.",
        "Read this aloud in a tired, end-of-day voice: 'I'm wrapping up for today and heading out soon.'",
        "Say something with enthusiasm, like telling a friend exciting news.",
    ];

    let enhanceState = {
        isRecording: false,
        chunks: [],
        audioStream: null,
        audioContext: null,
        analyserNode: null,
        scriptNode: null,
        sourceNode: null,
        animFrameId: null,
        countdownInterval: null,
        sampleCount: 0,
    };

    function openEnhanceOverlay() {
        const overlay = document.getElementById('enhance-overlay');
        overlay.style.display = 'flex';
        enhanceState.sampleCount = 0;
        prepareEnhanceSample();

        document.getElementById('enhance-close-btn').onclick = closeEnhanceOverlay;
        document.getElementById('enhance-record-btn').onclick = startEnhanceRecording;
        document.getElementById('enhance-another-btn').onclick = () => {
            enhanceState.sampleCount++;
            prepareEnhanceSample();
        };
        document.getElementById('enhance-finish-btn').onclick = closeEnhanceOverlay;
    }

    function prepareEnhanceSample() {
        const prompt = enhancePrompts[enhanceState.sampleCount % enhancePrompts.length];
        document.getElementById('enhance-prompt').textContent = prompt;
        document.getElementById('enhance-recorder').style.display = 'block';
        document.getElementById('enhance-processing').style.display = 'none';
        document.getElementById('enhance-done').style.display = 'none';
        const btn = document.getElementById('enhance-record-btn');
        btn.textContent = 'Start Recording';
        btn.disabled = false;
        btn.classList.remove('recording');
        document.getElementById('enhance-countdown').textContent = '10';
        document.getElementById('enhance-countdown').className = 'enrollment-countdown';
    }

    async function startEnhanceRecording() {
        if (enhanceState.isRecording) return;
        const btn = document.getElementById('enhance-record-btn');
        const countdown = document.getElementById('enhance-countdown');

        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true }
            });
            enhanceState.audioStream = stream;

            const audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
            enhanceState.audioContext = audioCtx;
            const source = audioCtx.createMediaStreamSource(stream);
            const analyser = audioCtx.createAnalyser();
            analyser.fftSize = 256;
            source.connect(analyser);
            enhanceState.analyserNode = analyser;

            // Waveform animation
            drawEnhanceWaveform();

            const bufferSize = 4096;
            const scriptNode = audioCtx.createScriptProcessor(bufferSize, 1, 1);
            enhanceState.chunks = [];
            scriptNode.onaudioprocess = (e) => {
                if (!enhanceState.isRecording) return;
                const channelData = e.inputBuffer.getChannelData(0);
                const int16 = new Int16Array(channelData.length);
                for (let i = 0; i < channelData.length; i++) {
                    const s = Math.max(-1, Math.min(1, channelData[i]));
                    int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                }
                enhanceState.chunks.push(int16);
            };
            source.connect(scriptNode);
            scriptNode.connect(audioCtx.destination);
            enhanceState.scriptNode = scriptNode;
            enhanceState.sourceNode = source;

            enhanceState.isRecording = true;
            btn.textContent = 'Recording...';
            btn.classList.add('recording');
            btn.disabled = true;
            countdown.className = 'enrollment-countdown active';

            let remaining = 10;
            countdown.textContent = remaining;
            enhanceState.countdownInterval = setInterval(() => {
                remaining--;
                countdown.textContent = remaining;
                if (remaining <= 0) {
                    clearInterval(enhanceState.countdownInterval);
                    finishEnhanceRecording();
                }
            }, 1000);
        } catch (e) {
            console.error('Microphone access denied:', e);
            btn.textContent = 'Microphone Access Required';
            btn.disabled = true;
        }
    }

    async function finishEnhanceRecording() {
        enhanceState.isRecording = false;
        if (enhanceState.animFrameId) {
            cancelAnimationFrame(enhanceState.animFrameId);
            enhanceState.animFrameId = null;
        }

        const totalLength = enhanceState.chunks.reduce((acc, c) => acc + c.length, 0);
        const combined = new Int16Array(totalLength);
        let offset = 0;
        for (const chunk of enhanceState.chunks) {
            combined.set(chunk, offset);
            offset += chunk.length;
        }

        cleanupEnhanceAudio();

        document.getElementById('enhance-recorder').style.display = 'none';
        document.getElementById('enhance-processing').style.display = 'block';

        try {
            const moodLabel = `enhance_${enhanceState.sampleCount}`;
            await API.enrollSpeakerSample(combined.buffer, moodLabel);
            await API.completeSpeakerEnrollment();
            document.getElementById('enhance-processing').style.display = 'none';
            document.getElementById('enhance-done').style.display = 'block';
        } catch (e) {
            console.error('Enhance sample failed:', e);
            document.getElementById('enhance-processing').style.display = 'none';
            document.getElementById('enhance-recorder').style.display = 'block';
            const btn = document.getElementById('enhance-record-btn');
            btn.textContent = 'Failed — Try Again';
            btn.disabled = false;
            btn.classList.remove('recording');
        }
    }

    function cleanupEnhanceAudio() {
        if (enhanceState.countdownInterval) { clearInterval(enhanceState.countdownInterval); enhanceState.countdownInterval = null; }
        if (enhanceState.animFrameId) { cancelAnimationFrame(enhanceState.animFrameId); enhanceState.animFrameId = null; }
        if (enhanceState.scriptNode) { try { enhanceState.scriptNode.disconnect(); } catch(e){} enhanceState.scriptNode = null; }
        if (enhanceState.sourceNode) { try { enhanceState.sourceNode.disconnect(); } catch(e){} enhanceState.sourceNode = null; }
        if (enhanceState.audioContext) { try { enhanceState.audioContext.close(); } catch(e){} enhanceState.audioContext = null; }
        if (enhanceState.audioStream) { enhanceState.audioStream.getTracks().forEach(t => t.stop()); enhanceState.audioStream = null; }
    }

    function closeEnhanceOverlay() {
        cleanupEnhanceAudio();
        document.getElementById('enhance-overlay').style.display = 'none';
        loadSpeakerStatus();
    }

    function drawEnhanceWaveform() {
        const canvas = document.getElementById('enhance-canvas');
        if (!canvas || !enhanceState.analyserNode) return;
        const ctx = canvas.getContext('2d');
        const analyser = enhanceState.analyserNode;
        const bufferLength = analyser.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);

        function draw() {
            if (!enhanceState.isRecording) return;
            enhanceState.animFrameId = requestAnimationFrame(draw);
            analyser.getByteTimeDomainData(dataArray);
            ctx.fillStyle = 'rgba(248, 249, 250, 0.3)';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            ctx.lineWidth = 2;
            ctx.strokeStyle = '#5a6270';
            ctx.beginPath();
            const sliceWidth = canvas.width / bufferLength;
            let x = 0;
            for (let i = 0; i < bufferLength; i++) {
                const v = dataArray[i] / 128.0;
                const y = v * canvas.height / 2;
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
                x += sliceWidth;
            }
            ctx.lineTo(canvas.width, canvas.height / 2);
            ctx.stroke();
        }
        draw();
    }

    function drawEnrollmentLevelBars() {
        const barsContainer = document.getElementById('enrollment-level-bars');
        if (!barsContainer || !enrollmentState.analyserNode) return;

        const bars = barsContainer.querySelectorAll('.level-bar');
        const analyser = enrollmentState.analyserNode;
        const bufferLength = analyser.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);

        function draw() {
            if (!enrollmentState.isListening && !enrollmentState.isRecording) return;
            enrollmentState.animFrameId = requestAnimationFrame(draw);

            analyser.getByteTimeDomainData(dataArray);

            // Compute RMS
            let sumSq = 0;
            for (let i = 0; i < bufferLength; i++) {
                const v = (dataArray[i] - 128) / 128.0;
                sumSq += v * v;
            }
            const rms = Math.sqrt(sumSq / bufferLength);

            // Smooth RMS with EMA
            enrollmentState.smoothedRms = 0.3 * rms + 0.7 * enrollmentState.smoothedRms;
            const smoothed = enrollmentState.smoothedRms;

            // Log-scale mapping
            const normalizedLevel = Math.min(1, Math.max(0, (Math.log10(smoothed + 0.001) + 2) / 2));

            // Map to active bar count (0 to 20)
            const activeBars = Math.round(normalizedLevel * bars.length);

            bars.forEach((bar, i) => {
                if (i < activeBars) {
                    bar.classList.add('active');
                    // Gradient height: 8px to 44px across bars
                    const t = i / (bars.length - 1);
                    const height = 8 + t * 36;
                    bar.style.height = height + 'px';
                } else {
                    bar.classList.remove('active');
                    bar.style.height = '4px';
                }
            });

            // Speech detection — only during listening phase
            if (enrollmentState.isListening && !enrollmentState.isRecording) {
                if (rms > 0.02) {
                    if (!enrollmentState.speechStartTime) {
                        enrollmentState.speechStartTime = performance.now();
                    } else if (performance.now() - enrollmentState.speechStartTime >= 200) {
                        beginRecording();
                    }
                } else {
                    enrollmentState.speechStartTime = null;
                }
            }
        }

        draw();
    }

    // Expose public API
    window.startEnrollment = startEnrollment;
    window.closeEnrollment = closeEnrollment;
    window.loadSpeakerStatus = loadSpeakerStatus;
    window.openEnhanceOverlay = openEnhanceOverlay;
    window.closeEnhanceOverlay = closeEnhanceOverlay;
})();
