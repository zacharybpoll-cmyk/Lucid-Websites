/**
 * Attune Onboarding — State Machine + Recording Logic
 */

// ============ Configuration ============

let API_BASE = 'http://127.0.0.1:8765'; // default, overridden by IPC
const _apiBaseReady = (async () => {
  if (window.attune && window.attune.getApiBase) {
    try {
      API_BASE = await window.attune.getApiBase();
    } catch (e) {
      console.warn('Could not get API base from preload, using default');
    }
  }
})();

const RECORDING_PROMPTS = [
  { label: 'Sample 1 — Normal Voice',  text: 'Read this aloud: "I\'m setting up my voice profile so that Attune can recognize me and focus on my wellness readings throughout the day. This way it only tracks my voice and no one else\'s."' },
  { label: 'Sample 2 — Animated Voice', text: 'Read this with energy: "Something really exciting happened today — I discovered a brand new tool that actually understands how I feel just by listening to my voice! I can\'t wait to see what it picks up over the next few days."' },
  { label: 'Sample 3 — Calm Voice',    text: 'Read this slowly and softly: "After a long day, it\'s nice to slow down and take a breath. I\'m grateful for the quiet moments and the chance to recharge before tomorrow starts all over again."' },
  { label: 'Sample 4 — Reading Aloud', text: 'Read this aloud: "The voice carries far more information than we realize. Subtle changes in pitch, rhythm, and tone can reveal how we truly feel beneath the surface — even when we think we\'re hiding it."' },
  { label: 'Sample 5 — On a Call',     text: 'Read this like you\'re on a work call: "Hey, thanks for jumping on. I just wanted to sync up on the project timeline and see if there\'s anything blocking you on your end. Let me know what you need from me to keep things moving."' },
];

const MOOD_LABELS = ['neutral', 'animated', 'calm', 'reading', 'on_a_call'];
const RECORDING_DURATION = 10; // seconds of speech required
const TOTAL_SAMPLES = 5;
const VAD_ENERGY_THRESHOLD = 12;  // average frequency bin value to consider "voice"
const VAD_CHECK_MS = 100;         // check every 100ms
const MIN_SPEECH_SECONDS = 5;     // minimum speech per sample to pass quality check
const RING_CIRCUMFERENCE = 2 * Math.PI * 60; // r=60

// ============ State ============

let currentStep = 1;
let currentSample = 0; // 0-indexed
let isRecording = false;
let audioContext = null;
let audioStream = null;
let analyserNode = null;
let scriptNode = null;   // Fallback (deprecated ScriptProcessorNode)
let workletNode = null;  // Preferred (AudioWorklet)
let sourceNode = null;
let pcmChunks = [];
let animFrameId = null;
let countdownInterval = null;
let vadCheckInterval = null;
let speechMs = 0;
let countdownRemaining = RECORDING_DURATION;
let sampleResults = [];
let carouselInterval = null;
let carouselSlide = 0;
let carouselPaused = false;
let carouselProgressStart = 0;
let carouselProgressRAF = null;
let particleRAF = null;
let enrollmentVerified = false;
const CAROUSEL_DURATION = 6000; // ms per slide
const TOTAL_SLIDES = 10;

// ============ Retry Helper ============

/**
 * Fetch with exponential backoff retry.
 * @param {string} url
 * @param {RequestInit} opts
 * @param {number} maxRetries - maximum retry attempts (default 3)
 * @param {number} baseDelayMs - initial backoff delay in ms (default 1000)
 * @returns {Promise<Response>}
 */
async function fetchWithRetry(url, opts = {}, maxRetries = 3, baseDelayMs = 1000) {
  await _apiBaseReady;
  let lastError;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 30000);
      const res = await fetch(url, { ...opts, signal: controller.signal });
      clearTimeout(timeoutId);

      // Retry on 503 (server still initializing)
      if (res.status === 503 && attempt < maxRetries) {
        const retryAfter = parseInt(res.headers.get('Retry-After') || '5', 10);
        const delay = Math.min(retryAfter * 1000, baseDelayMs * Math.pow(2, attempt));
        console.warn(`[Onboarding] 503 from ${url}, retrying in ${delay}ms (attempt ${attempt + 1}/${maxRetries})`);
        await new Promise(r => setTimeout(r, delay));
        continue;
      }

      return res;
    } catch (e) {
      lastError = e;
      if (e.name === 'AbortError') {
        // Timeout — retry with backoff
        if (attempt < maxRetries) {
          const delay = baseDelayMs * Math.pow(2, attempt);
          console.warn(`[Onboarding] Timeout for ${url}, retrying in ${delay}ms (attempt ${attempt + 1}/${maxRetries})`);
          await new Promise(r => setTimeout(r, delay));
          continue;
        }
      }
      // Network error — retry with backoff
      if (attempt < maxRetries) {
        const delay = baseDelayMs * Math.pow(2, attempt);
        console.warn(`[Onboarding] Network error for ${url}: ${e.message}, retrying in ${delay}ms (attempt ${attempt + 1}/${maxRetries})`);
        await new Promise(r => setTimeout(r, delay));
        continue;
      }
    }
  }
  throw lastError || new Error(`Failed after ${maxRetries + 1} attempts`);
}

// ============ Init ============
// API_BASE initialization handled by _apiBaseReady promise at top of file.

// ============ Step Navigation ============

function goToStep(step) {
  // [R-007] Enrollment guard: steps beyond enrollment require verified enrollment
  if (step > 5 && !enrollmentVerified) {
    console.warn('[Onboarding] Cannot advance to step', step, 'without verified enrollment');
    const voiceStatus = document.getElementById('voiceStatus');
    if (voiceStatus) voiceStatus.textContent = 'Please complete voice enrollment before continuing.';
    return;
  }

  // Deactivate current
  const currentEl = document.getElementById(`step-${currentStep}`);
  if (currentEl) currentEl.classList.remove('active');

  // Stop carousel if leaving step 2
  if (currentStep === 2) {
    stopCarouselTimer();
  }

  // Stop particles if leaving step 6
  if (currentStep === 6) {
    stopParticles();
  }

  currentStep = step;

  // Activate new
  const newEl = document.getElementById(`step-${step}`);
  if (newEl) newEl.classList.add('active');

  // Update progress dots
  document.querySelectorAll('.progress-dots .dot').forEach(dot => {
    const s = parseInt(dot.dataset.step);
    dot.classList.remove('active', 'done');
    if (s < step) dot.classList.add('done');
    else if (s === step) dot.classList.add('active');
  });

  // Start carousel auto-advance for step 2
  if (step === 2) startCarousel();

  // Start particle animation for step 6 and verify enrollment
  if (step === 6) {
    startParticles();
    // Delay first verification poll to let server finish enrollment processing
    setTimeout(() => verifyEnrollmentForComplete(), 500);
  }
}

// ============ Step 2: Carousel ============

function startCarousel() {
  carouselSlide = 0;
  carouselPaused = false;
  updateCarouselUI();
  startCarouselTimer();

  // Make dots clickable
  document.querySelectorAll('.carousel-dot').forEach(d => {
    d.addEventListener('click', () => {
      goToSlide(parseInt(d.dataset.slide));
    });
  });

  // Press-and-hold anywhere in card to pause carousel; release to resume
  const step2Card = document.querySelector('#step-2 .card');
  step2Card.addEventListener('mousedown', (e) => {
    if (e.target.closest('.carousel-arrow, .carousel-dot, .carousel-progress, .btn-primary, .btn-skip, .btn-carousel-continue')) return;
    if (!carouselPaused) toggleCarouselPause();
  });
  document.addEventListener('mouseup', () => {
    if (carouselPaused && currentStep === 2) toggleCarouselPause();
  });
}

function startCarouselTimer() {
  carouselProgressStart = performance.now();
  if (carouselProgressRAF) cancelAnimationFrame(carouselProgressRAF);
  animateCarouselProgress();
}

function animateCarouselProgress() {
  carouselProgressRAF = requestAnimationFrame(() => {
    if (currentStep !== 2) return;  // Stop RAF loop if we left this step
    if (carouselPaused) {
      // Keep RAF alive but don't advance
      animateCarouselProgress();
      return;
    }
    const elapsed = performance.now() - carouselProgressStart;
    const progress = Math.min(elapsed / CAROUSEL_DURATION, 1);
    const fill = document.getElementById('carouselProgressFill');
    if (fill) fill.style.width = (progress * 100) + '%';

    if (progress >= 1) {
      carouselSlide = (carouselSlide + 1) % TOTAL_SLIDES;
      updateCarouselUI();
      carouselProgressStart = performance.now();
    }
    animateCarouselProgress();
  });
}

function stopCarouselTimer() {
  if (carouselProgressRAF) {
    cancelAnimationFrame(carouselProgressRAF);
    carouselProgressRAF = null;
  }
}

function updateCarouselUI() {
  document.querySelectorAll('.carousel-slide').forEach(s => {
    s.classList.toggle('active', parseInt(s.dataset.slide) === carouselSlide);
  });
  document.querySelectorAll('.carousel-dot').forEach(d => {
    d.classList.toggle('active', parseInt(d.dataset.slide) === carouselSlide);
  });

  // Show Continue on last slide, Skip on all others
  const continueBtn = document.getElementById('carouselContinue');
  const skipBtn = document.getElementById('carouselSkip');
  if (continueBtn && skipBtn) {
    if (carouselSlide === TOTAL_SLIDES - 1) {
      continueBtn.style.display = '';
      skipBtn.style.display = 'none';
    } else {
      continueBtn.style.display = 'none';
      skipBtn.style.display = '';
    }
  }
}

function goToSlide(index) {
  carouselSlide = index;
  updateCarouselUI();
  // Reset progress timer
  carouselProgressStart = performance.now();
  const fill = document.getElementById('carouselProgressFill');
  if (fill) fill.style.width = '0%';
}

function carouselPrev() {
  goToSlide((carouselSlide - 1 + TOTAL_SLIDES) % TOTAL_SLIDES);
}

function carouselNext() {
  goToSlide((carouselSlide + 1) % TOTAL_SLIDES);
}

function toggleCarouselPause() {
  carouselPaused = !carouselPaused;
  const progress = document.getElementById('carouselProgress');
  if (progress) progress.classList.toggle('paused', carouselPaused);
  if (!carouselPaused) {
    // Resume — adjust start time so progress continues from where it was
    const fill = document.getElementById('carouselProgressFill');
    const currentWidth = fill ? parseFloat(fill.style.width) || 0 : 0;
    const elapsedMs = (currentWidth / 100) * CAROUSEL_DURATION;
    carouselProgressStart = performance.now() - elapsedMs;
  }
}

// ============ Step 3: Mic Permission ============

async function requestMicPermission() {
  const btn = document.getElementById('micPermBtn');
  const error = document.getElementById('micError');

  btn.textContent = 'Requesting...';
  btn.disabled = true;

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true }
    });
    // Permission granted — stop the stream immediately
    stream.getTracks().forEach(t => t.stop());

    // Flash checkmark on button
    btn.textContent = 'Access Granted';
    btn.style.background = '#5a9a6e';

    // Auto-advance after brief delay
    setTimeout(() => goToStep(4), 800);

  } catch (e) {
    console.error('Mic permission denied:', e);
    btn.textContent = 'Try Again';
    btn.disabled = false;
    btn.style.background = '#c0392b';
    error.style.display = 'block';

    // ERR-003: Allow re-attempt directly from the button
    btn.onclick = requestMicPermission;

    // Poll for permission change every 3 seconds after denial
    let permissionPollId = setInterval(async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach(t => t.stop());
        clearInterval(permissionPollId);
        btn.textContent = 'Access Granted';
        btn.style.background = '#5a9a6e';
        btn.disabled = true;
        error.style.display = 'none';
        setTimeout(() => goToStep(4), 800);
      } catch (_) {
        // Still denied — keep polling
      }
    }, 3000);
  }
}

function openSystemSettings() {
  if (window.attune && window.attune.openSystemSettings) {
    window.attune.openSystemSettings();
  }
}

// ============ Step 4: Voice Profile Recording ============

function updateRecordingUI() {
  const prompt = RECORDING_PROMPTS[currentSample];
  document.getElementById('promptLabel').textContent = prompt.label;
  document.getElementById('promptText').textContent = prompt.text;
  document.getElementById('ringLabel').textContent = `${currentSample} / ${TOTAL_SAMPLES}`;

  // Update ring fill
  const offset = RING_CIRCUMFERENCE * (1 - currentSample / TOTAL_SAMPLES);
  document.getElementById('ringFill').style.strokeDashoffset = offset;

  // Show recording UI, hide processing
  document.getElementById('recordBtn').style.display = '';
  document.getElementById('recordBtn').disabled = false;
  document.getElementById('recordBtn').classList.remove('recording');
  document.querySelector('.record-btn-container').style.display = 'flex';
  document.getElementById('countdown').classList.remove('active');
  document.getElementById('countdown').textContent = RECORDING_DURATION;
  document.getElementById('processing').style.display = 'none';
  document.getElementById('recordingPrompt').style.display = 'block';
  document.getElementById('waveformCanvas').style.display = 'block';
  document.getElementById('recordingInstructions').style.display = 'block';

  // Reset voice status
  const voiceStatus = document.getElementById('voiceStatus');
  if (voiceStatus) {
    voiceStatus.textContent = '';
    voiceStatus.classList.remove('speaking');
  }

  // Clear waveform
  const canvas = document.getElementById('waveformCanvas');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
}

async function startRecording() {
  if (isRecording) return;

  // [R-046] Model-readiness pre-check before recording
  await _apiBaseReady;
  const voiceStatus = document.getElementById('voiceStatus');
  try {
    const healthRes = await fetch(`${API_BASE}/api/health`);
    const health = await healthRes.json();
    // ERR-002: Health returns 503 when not ready — check ready field regardless of status code
    if (health.ready === false) {
      if (voiceStatus) voiceStatus.textContent = 'Models still loading — please wait a moment and try again.';
      return;
    }
  } catch (e) {
    // Backend unreachable — let recording proceed, enrollment will fail later with a clear error
  }

  const recordBtn = document.getElementById('recordBtn');
  const countdownEl = document.getElementById('countdown');
  // voiceStatus already declared above (line 380)

  try {
    audioStream = await navigator.mediaDevices.getUserMedia({
      audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true }
    });

    audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
    sourceNode = audioContext.createMediaStreamSource(audioStream);
    analyserNode = audioContext.createAnalyser();
    analyserNode.fftSize = 256;
    sourceNode.connect(analyserNode);

    // Capture raw PCM — prefer AudioWorklet, fall back to ScriptProcessorNode
    pcmChunks = [];

    try {
      if (!audioContext.audioWorklet) throw new Error('AudioWorklet not supported');
      await audioContext.audioWorklet.addModule('audio-processor.js');
      workletNode = new AudioWorkletNode(audioContext, 'pcm-capture-processor');
      workletNode.port.onmessage = (event) => {
        if (!isRecording) return;
        pcmChunks.push(event.data.pcm);
      };
      sourceNode.connect(workletNode);
      workletNode.connect(audioContext.destination);
    } catch (workletErr) {
      console.warn('[Onboarding] AudioWorklet unavailable, falling back to ScriptProcessorNode:', workletErr.message);
      const bufferSize = 4096;
      scriptNode = audioContext.createScriptProcessor(bufferSize, 1, 1);

      scriptNode.onaudioprocess = (e) => {
        if (!isRecording) return;
        const channelData = e.inputBuffer.getChannelData(0);
        const int16 = new Int16Array(channelData.length);
        for (let i = 0; i < channelData.length; i++) {
          const s = Math.max(-1, Math.min(1, channelData[i]));
          int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        pcmChunks.push(int16);
      };

      sourceNode.connect(scriptNode);
      scriptNode.connect(audioContext.destination);
    }

    isRecording = true;
    speechMs = 0;
    countdownRemaining = RECORDING_DURATION;
    recordBtn.classList.add('recording');
    recordBtn.disabled = true;
    countdownEl.classList.add('active');
    countdownEl.textContent = countdownRemaining;

    // Show initial voice status
    if (voiceStatus) {
      voiceStatus.textContent = 'Start speaking...';
      voiceStatus.classList.remove('speaking');
    }

    // Start waveform
    drawWaveform();

    // VAD-driven countdown — only ticks when voice is detected
    vadCheckInterval = setInterval(() => {
      if (!isRecording || !analyserNode) return;

      const dataArray = new Uint8Array(analyserNode.frequencyBinCount);
      analyserNode.getByteFrequencyData(dataArray);
      const avgEnergy = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;

      const voiceDetected = avgEnergy > VAD_ENERGY_THRESHOLD;

      if (voiceDetected) {
        speechMs += VAD_CHECK_MS;
        const newRemaining = RECORDING_DURATION - Math.floor(speechMs / 1000);
        if (newRemaining !== countdownRemaining && newRemaining >= 0) {
          countdownRemaining = newRemaining;
          countdownEl.textContent = countdownRemaining;
        }
        if (speechMs >= RECORDING_DURATION * 1000) {
          clearInterval(vadCheckInterval);
          vadCheckInterval = null;
          finishRecording();
          return;
        }
      }

      // Update voice status indicator
      updateVoiceStatus(voiceDetected);
    }, VAD_CHECK_MS);

  } catch (e) {
    console.error('Recording failed:', e);
    recordBtn.disabled = false;
  }
}

function updateVoiceStatus(voiceDetected) {
  const voiceStatus = document.getElementById('voiceStatus');
  if (!voiceStatus) return;

  if (voiceDetected) {
    voiceStatus.textContent = 'Recording...';
    voiceStatus.classList.add('speaking');
  } else if (speechMs > 0) {
    voiceStatus.textContent = 'Keep going...';
    voiceStatus.classList.remove('speaking');
  } else {
    voiceStatus.textContent = 'Start speaking...';
    voiceStatus.classList.remove('speaking');
  }
}

async function finishRecording() {
  isRecording = false;

  if (animFrameId) {
    cancelAnimationFrame(animFrameId);
    animFrameId = null;
  }

  // Hide voice status
  const voiceStatus = document.getElementById('voiceStatus');
  if (voiceStatus) {
    voiceStatus.textContent = '';
    voiceStatus.classList.remove('speaking');
  }

  // Combine PCM chunks
  const totalLength = pcmChunks.reduce((a, c) => a + c.length, 0);
  const combined = new Int16Array(totalLength);
  let offset = 0;
  for (const chunk of pcmChunks) {
    combined.set(chunk, offset);
    offset += chunk.length;
  }

  // Track quality for this sample
  const passed = speechMs >= MIN_SPEECH_SECONDS * 1000;
  // Store or update sample result
  const existingIdx = sampleResults.findIndex(s => s.index === currentSample);
  if (existingIdx >= 0) {
    sampleResults[existingIdx] = { index: currentSample, speechMs, passed };
  } else {
    sampleResults.push({ index: currentSample, speechMs, passed });
  }

  // Cleanup audio
  cleanupAudio();

  const moodLabel = MOOD_LABELS[currentSample];

  // Show uploading state
  document.getElementById('recordBtn').disabled = true;
  document.getElementById('countdown').classList.remove('active');
  const instructions = document.getElementById('recordingInstructions');
  instructions.textContent = 'Uploading sample...';

  try {
    // Send PCM to server with retry
    const res = await fetchWithRetry(`${API_BASE}/api/speaker/enroll?mood_label=${moodLabel}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: combined.buffer,
    });

    if (!res.ok) throw new Error(`Server error: ${res.status}`);

    const result = await res.json();

    currentSample++;

    // Show checkmark flash
    showCheckmark();

    if (currentSample < TOTAL_SAMPLES) {
      // Next sample after brief delay
      setTimeout(() => {
        hideCheckmark();
        updateRecordingUI();
      }, 800);
    } else {
      // All samples done — check for failed samples
      const failedSamples = sampleResults.filter(s => !s.passed);
      if (failedSamples.length > 0) {
        setTimeout(() => {
          hideCheckmark();
          showRedoUI(failedSamples);
        }, 800);
      } else {
        // All passed — finalize enrollment
        setTimeout(() => {
          hideCheckmark();
          finalizeEnrollment();
        }, 800);
      }
    }

  } catch (e) {
    console.error('Failed to upload sample:', e);
    const msg = e.name === 'AbortError'
      ? 'Upload timed out after retries. Please check your connection and try again.'
      : 'Upload failed after retries. Please try again.';
    updateRecordingUI();
    document.getElementById('recordingInstructions').textContent = msg;
  }
}

function showRedoUI(failedSamples) {
  const count = failedSamples.length;
  const instructions = document.getElementById('recordingInstructions');
  instructions.style.display = 'block';
  instructions.textContent = `${count} sample${count > 1 ? 's' : ''} had too little speech. Let\u2019s redo ${count > 1 ? 'them' : 'it'}.`;

  // Jump to the first failed sample
  currentSample = failedSamples[0].index;
  updateRecordingUI();
  // Override the instructions text (updateRecordingUI resets it)
  instructions.textContent = `${count} sample${count > 1 ? 's' : ''} had too little speech. Let\u2019s redo ${count > 1 ? 'them' : 'it'}.`;
}

async function finalizeEnrollment() {
  showProcessing();

  try {
    const enrollRes = await fetchWithRetry(`${API_BASE}/api/speaker/enroll/complete`, {
      method: 'POST',
    });
    if (!enrollRes.ok) {
      const body = await enrollRes.json().catch(() => ({}));
      throw new Error(body.detail || `Enrollment failed: ${enrollRes.status}`);
    }

    const enrollResult = await enrollRes.json();

    // Mark enrollment success so step 6 knows the profile is ready
    enrollmentVerified = true;

    // Show completion checkmark briefly then advance
    hideProcessing();
    showCheckmark();
    setTimeout(() => {
      hideCheckmark();
      goToStep(5);
    }, 1000);

  } catch (e) {
    console.error('Enrollment completion failed:', e);
    hideProcessing();
    currentSample = 0;
    sampleResults = [];
    updateRecordingUI();
    document.getElementById('recordingInstructions').textContent =
      'Enrollment failed. Please try again.';
  }
}

function cleanupAudio() {
  if (countdownInterval) {
    clearInterval(countdownInterval);
    countdownInterval = null;
  }
  if (vadCheckInterval) {
    clearInterval(vadCheckInterval);
    vadCheckInterval = null;
  }
  if (animFrameId) {
    cancelAnimationFrame(animFrameId);
    animFrameId = null;
  }
  if (workletNode) {
    try { workletNode.port.close(); } catch (e) {}
    try { workletNode.disconnect(); } catch (e) {}
    workletNode = null;
  }
  if (scriptNode) {
    try { scriptNode.disconnect(); } catch (e) {}
    scriptNode = null;
  }
  if (sourceNode) {
    try { sourceNode.disconnect(); } catch (e) {}
    sourceNode = null;
  }
  if (audioContext) {
    try { audioContext.close(); } catch (e) {}
    audioContext = null;
  }
  if (audioStream) {
    audioStream.getTracks().forEach(t => t.stop());
    audioStream = null;
  }
  analyserNode = null;
}

function showCheckmark() {
  const el = document.getElementById('checkmarkFlash');
  el.style.display = 'block';
  el.classList.add('show');
}

function hideCheckmark() {
  const el = document.getElementById('checkmarkFlash');
  el.classList.remove('show');
  el.style.display = 'none';
}

function showProcessing() {
  document.querySelector('.record-btn-container').style.display = 'none';
  document.getElementById('recordingPrompt').style.display = 'none';
  document.getElementById('waveformCanvas').style.display = 'none';
  document.getElementById('recordingInstructions').style.display = 'none';
  document.getElementById('processing').style.display = 'flex';

  // Fill the ring completely
  document.getElementById('ringFill').style.strokeDashoffset = 0;
  document.getElementById('ringLabel').textContent = `${TOTAL_SAMPLES} / ${TOTAL_SAMPLES}`;
}

function hideProcessing() {
  document.getElementById('processing').style.display = 'none';
}

// ============ Waveform Drawing ============

function drawWaveform() {
  const canvas = document.getElementById('waveformCanvas');
  if (!canvas || !analyserNode) return;

  const ctx = canvas.getContext('2d');
  const bufferLength = analyserNode.frequencyBinCount;
  const dataArray = new Uint8Array(bufferLength);

  function draw() {
    if (!isRecording) return;
    animFrameId = requestAnimationFrame(draw);

    analyserNode.getByteFrequencyData(dataArray);

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const barWidth = (canvas.width / bufferLength) * 2;
    const midY = canvas.height / 2;
    let x = 0;

    for (let i = 0; i < bufferLength; i++) {
      const barHeight = (dataArray[i] / 255) * midY * 0.85;

      // Gold gradient
      const alpha = 0.4 + (dataArray[i] / 255) * 0.6;
      ctx.fillStyle = `rgba(184, 151, 92, ${alpha})`;

      // Mirror bars from center
      ctx.fillRect(x, midY - barHeight, barWidth - 1, barHeight);
      ctx.fillRect(x, midY, barWidth - 1, barHeight * 0.6);

      x += barWidth;
    }
  }

  draw();
}

// ============ Step 6: Particles ============

function startParticles() {
  const canvas = document.getElementById('particleCanvas');
  if (!canvas) return;

  // Cancel any existing particle animation before starting a new one
  stopParticles();

  // Match canvas to actual card size
  const card = canvas.parentElement;
  canvas.width = card.offsetWidth;
  canvas.height = card.offsetHeight;

  const ctx = canvas.getContext('2d');
  const particles = [];

  for (let i = 0; i < 40; i++) {
    particles.push({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      vx: (Math.random() - 0.5) * 0.5,
      vy: -Math.random() * 0.8 - 0.2,
      r: Math.random() * 3 + 1,
      alpha: Math.random() * 0.5 + 0.2,
      color: Math.random() > 0.5 ? '#b8975c' : '#5a9a6e',
    });
  }

  function animate() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    for (const p of particles) {
      p.x += p.vx;
      p.y += p.vy;

      // Wrap around
      if (p.y < -10) { p.y = canvas.height + 10; p.x = Math.random() * canvas.width; }
      if (p.x < -10) p.x = canvas.width + 10;
      if (p.x > canvas.width + 10) p.x = -10;

      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = p.color;
      ctx.globalAlpha = p.alpha;
      ctx.fill();
    }

    ctx.globalAlpha = 1;
    particleRAF = requestAnimationFrame(animate);
  }

  animate();
}

function stopParticles() {
  if (particleRAF) {
    cancelAnimationFrame(particleRAF);
    particleRAF = null;
  }
}

// ============ Enrollment Verification for Step 6 ============

/**
 * Verify speaker enrollment via the API before enabling the "Open Dashboard" button.
 * Called when entering step 6. If enrollment was already verified during finalizeEnrollment(),
 * this enables the button immediately. Otherwise, polls the API as a fallback.
 */
async function verifyEnrollmentForComplete() {
  const btn = document.querySelector('#step-6 .btn-primary');
  if (!btn) return;

  if (enrollmentVerified) {
    btn.disabled = false;
    btn.textContent = 'Open Dashboard';
    return;
  }

  // Fallback: poll the speaker status API to verify enrollment
  btn.disabled = true;
  btn.textContent = 'Verifying enrollment...';

  const maxAttempts = 10;
  for (let i = 0; i < maxAttempts; i++) {
    try {
      const res = await fetchWithRetry(`${API_BASE}/api/speaker/status`, {}, 1, 1000);
      if (res.ok) {
        const status = await res.json();
        if (status.enrolled) {
          enrollmentVerified = true;
          btn.disabled = false;
          btn.textContent = 'Open Dashboard';
          return;
        }
      }
    } catch (e) {
      console.warn('[Onboarding] Enrollment verification check failed:', e.message);
    }
    // Wait before next poll
    await new Promise(r => setTimeout(r, 2000));
  }

  // [R-007] After all attempts, show error instead of silently enabling
  console.error('[Onboarding] Could not verify enrollment after polling');
  btn.disabled = false;
  btn.textContent = 'Retry Enrollment';
  btn.onclick = () => goToStep(4); // Send back to enrollment step
}


// ============ Complete Onboarding ============

async function completeOnboarding() {
  const btn = document.querySelector('#step-6 .btn-primary');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Starting...';
  }

  if (window.attune && window.attune.completeOnboarding) {
    await window.attune.completeOnboarding();
  }
}
