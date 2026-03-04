/**
 * sculptor.js — Voice Sculptor
 * Lucid Voice Wellness Monitor
 *
 * Animated blob visualizer driven by REAL mic input via Web Audio API.
 * No server required — all analysis is browser-side using AnalyserNode.
 *
 * Feature extraction:
 *   Coherence  → pitch stability (variance in dominant frequency bin)
 *   Tension    → high-freq energy ratio (HNR proxy: low/high band ratio)
 *   Presence   → RMS energy (overall loudness)
 *
 * Blob behaviour:
 *   Calm (coherence high)   → smooth, slow, steel-blue (#5B8DB8)
 *   Stressed (tension high) → spiky, fast, purple-tinted (#8b6abf)
 *
 * Public API: sculptorView.load() / sculptorView.unload()
 */

const sculptorView = (() => {

    // ── Constants ──────────────────────────────────────────────────

    const NUM_POINTS   = 128;  // blob polygon resolution
    const FFT_SIZE     = 2048; // AnalyserNode FFT size
    const SMOOTH_TAU   = 0.35; // EMA time constant (seconds) — 4x faster response
    const NOISE_BASE   = 1.4;  // base noise speed (radians/sec)

    // ── Arc ring constants ────────────────────────────────────────
    const ARC_RADIUS    = 165;  // px from center
    const ARC_STROKE    = 2;    // px
    const ARC_GAP_DEG   = 4;    // degrees between segments
    const ARC_DOT_R     = 3;    // endpoint dot radius

    const BENEFIT_SEGMENTS = [
        { name: 'HRV Sync',     startDeg: -86, spanDeg: 116, threshLo: 0.85, threshHi: 1.0  },
        { name: 'Vagal Tone',   startDeg:  34, spanDeg: 116, threshLo: 0.65, threshHi: 0.85 },
        { name: 'Vasodilation', startDeg: 154, spanDeg: 116, threshLo: 0.40, threshHi: 0.65 },
    ];

    // ── State ──────────────────────────────────────────────────────

    const state = {
        loaded      : false,
        animFrame   : null,
        canvas      : null,
        ctx         : null,

        // Web Audio
        audioCtx    : null,
        analyser    : null,
        micStream   : null,
        freqData    : null,
        timeData    : null,

        // Mic permission / status
        micGranted  : false,
        micAsked    : false,

        // Raw biomarker values (0–1)
        coherence   : 0.5,
        tension     : 0.3,
        presence    : 0.1,

        // Smoothed values (EMA)
        dCoherence  : 0.5,
        dTension    : 0.3,
        dPresence   : 0.1,

        // Animation
        noiseOffset : 0,
        lastTs      : null,
    };

    // ── Entry ──────────────────────────────────────────────────────

    function load() {
        _render();
        state.loaded    = true;
        state.lastTs    = null;
        state.animFrame = requestAnimationFrame(_animate);
        _requestMic();
    }

    function unload() {
        state.loaded = false;

        if (state.animFrame) {
            cancelAnimationFrame(state.animFrame);
            state.animFrame = null;
        }

        _teardownMic();
    }

    // ── Mic setup ──────────────────────────────────────────────────

    async function _requestMic() {
        if (state.micAsked) return;
        state.micAsked = true;

        _setStatus('Requesting microphone…');

        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: false,
                    noiseSuppression: false,
                    autoGainControl:  false,
                    sampleRate: 16000,
                },
            });

            state.audioCtx = new AudioContext({ sampleRate: 16000 });
            state.analyser = state.audioCtx.createAnalyser();
            state.analyser.fftSize = FFT_SIZE;
            state.analyser.smoothingTimeConstant = 0.75;

            const src = state.audioCtx.createMediaStreamSource(stream);
            src.connect(state.analyser);

            state.freqData  = new Float32Array(state.analyser.frequencyBinCount);
            state.timeData  = new Float32Array(state.analyser.fftSize);
            state.micStream = stream;
            state.micGranted = true;

            _setStatus('Listening — hum or speak to sculpt the form');
            console.log('[Sculptor] Mic started');
        } catch (err) {
            console.warn('[Sculptor] Mic denied or unavailable:', err);
            _setStatus('Mic unavailable — blob simulated');
            _startSimulation();
        }
    }

    function _teardownMic() {
        if (state.micStream) {
            state.micStream.getTracks().forEach(t => t.stop());
            state.micStream = null;
        }
        if (state.audioCtx) {
            state.audioCtx.close();
            state.audioCtx = null;
        }
        state.analyser   = null;
        state.freqData   = null;
        state.timeData   = null;
        state.micGranted = false;
        state.micAsked   = false;
    }

    // ── Simulation fallback (if mic denied) ────────────────────────

    function _startSimulation() {
        // Drive biomarkers with gentle sin waves so blob still looks alive
        const simTick = () => {
            if (!state.loaded || state.micGranted) return;
            const t = Date.now() / 1000;
            state.coherence = 0.5 + Math.sin(t * 0.3) * 0.15;
            state.tension   = 0.3 + Math.sin(t * 0.7) * 0.10;
            state.presence  = 0.3 + Math.sin(t * 0.5) * 0.12;
            setTimeout(simTick, 100);
        };
        simTick();
    }

    // ── Audio feature extraction ────────────────────────────────────

    function _extractFeatures() {
        if (!state.analyser || !state.freqData || !state.timeData) return;

        state.analyser.getFloatFrequencyData(state.freqData); // dBFS values
        state.analyser.getFloatTimeDomainData(state.timeData); // [-1, 1]

        const sampleRate = state.audioCtx.sampleRate;
        const binCount   = state.analyser.frequencyBinCount;
        const binHz      = sampleRate / (2 * binCount);

        // ── Presence: RMS energy ────────────────────────────────────
        let sumSq = 0;
        for (let i = 0; i < state.timeData.length; i++) {
            sumSq += state.timeData[i] * state.timeData[i];
        }
        const rms = Math.sqrt(sumSq / state.timeData.length);
        // Map: silence ≈ 0.0001, loud ≈ 0.3; normalize to [0,1] with soft clip
        state.presence = Math.min(1, rms / 0.12);

        // ── Convert dBFS freq data to linear magnitude ──────────────
        const mag = new Float32Array(binCount);
        for (let i = 0; i < binCount; i++) {
            // freqData is in dBFS, range roughly -Infinity to 0
            mag[i] = Math.pow(10, state.freqData[i] / 20);
        }

        // ── Coherence: dominant pitch bin consistency ──────────────
        // Find peak bin in vocal range (80–600 Hz)
        const voiceLo = Math.floor(80  / binHz);
        const voiceHi = Math.floor(600 / binHz);
        let peakMag = 0, peakBin = 0;
        for (let i = voiceLo; i < voiceHi && i < binCount; i++) {
            if (mag[i] > peakMag) { peakMag = mag[i]; peakBin = i; }
        }
        // Ratio of peak to surrounding energy: sharp peak = high coherence
        let surroundSum = 0;
        const window = 8;
        for (let i = Math.max(0, peakBin - window); i < Math.min(binCount, peakBin + window); i++) {
            surroundSum += mag[i];
        }
        const coherenceRaw = surroundSum > 0 ? Math.min(1, (peakMag / surroundSum) * 3) : 0;
        state.coherence = state.presence > 0.05 ? coherenceRaw : 0.5; // Neutral when silent

        // ── Tension: high-freq / low-freq energy ratio ─────────────
        const midCutHz  = 1500;
        const midCutBin = Math.floor(midCutHz / binHz);
        let loEnergy = 0, hiEnergy = 0;
        for (let i = 1; i < midCutBin && i < binCount; i++) loEnergy += mag[i] * mag[i];
        for (let i = midCutBin; i < binCount; i++) hiEnergy += mag[i] * mag[i];

        const totalEnergy = loEnergy + hiEnergy + 1e-12;
        const hiRatio = hiEnergy / totalEnergy;
        // Calm voice: hiRatio ≈ 0.1; tense/breathy: hiRatio ≈ 0.3–0.5
        state.tension = state.presence > 0.03 ? Math.min(1, hiRatio * 2.5) : 0.2;
    }

    // ── Animation loop ─────────────────────────────────────────────

    function _animate(ts) {
        if (!state.loaded) return;

        const dt = state.lastTs !== null ? Math.min((ts - state.lastTs) / 1000, 0.1) : 0.016;
        state.lastTs = ts;

        // Extract real audio features if mic is running
        if (state.micGranted && state.analyser) {
            _extractFeatures();
        }

        // EMA smoothing
        const alpha = Math.min(1, dt / SMOOTH_TAU);
        state.dCoherence = state.dCoherence + alpha * (state.coherence - state.dCoherence);
        state.dTension   = state.dTension   + alpha * (state.tension   - state.dTension);
        state.dPresence  = state.dPresence  + alpha * (state.presence  - state.dPresence);

        // Noise offset drifts faster when tense OR incoherent
        state.noiseOffset += dt * (NOISE_BASE + state.dTension * 3.5 + (1 - state.dCoherence) * 2.5);

        _drawBlob();
        _drawArcRing();
        _updateUI();

        state.animFrame = requestAnimationFrame(_animate);
    }

    // ── Noise function ─────────────────────────────────────────────

    function _noise(t, seed) {
        return (
            Math.sin(t * 1.7  + seed)        * 0.500 +
            Math.sin(t * 3.1  + seed * 1.3)  * 0.250 +
            Math.sin(t * 5.3  + seed * 2.1)  * 0.125 +
            Math.sin(t * 8.7  + seed * 0.9)  * 0.063
        );
    }

    // ── Blob drawing ───────────────────────────────────────────────

    function _drawBlob() {
        const canvas = state.canvas;
        const ctx    = state.ctx;
        if (!canvas || !ctx) return;

        const css = 400;
        ctx.clearRect(0, 0, css, css);

        const cx = css / 2;
        const cy = css / 2;

        // Base radius: collapses to tiny dot in silence, blooms with voice
        const baseR = state.dPresence > 0.05
            ? 55 + state.dPresence * 90    // range 55–145px when speaking
            : 15 + state.dPresence * 800;  // collapses to ~15–56px dot in silence
        const spikiness = 8 + state.dTension * 88;  // range 8–96

        // Coherence → smoothness: high coherence = few, regular bumps; low = chaotic
        // chaos ranges 0.1 (very coherent) → 1.5 (incoherent)
        const chaos = 0.1 + (1 - state.dCoherence) * 1.4;

        // Noise drift: faster when tense OR when incoherent
        // (this is already applied to state.noiseOffset in _animate, but we
        //  use chaos here to add a second independent high-freq layer offset)
        const hiOffset = state.noiseOffset * 1.7 + state.dTension * 2;

        // Build blob polygon
        const points = [];
        for (let i = 0; i < NUM_POINTS; i++) {
            const angle = (i / NUM_POINTS) * Math.PI * 2;

            // Low-freq base shape (smooth, few bumps) — always present
            const smoothN = _noise(angle * 1.5 + state.noiseOffset, i * 0.4);

            // High-freq chaotic layer — scales with incoherence
            const chaoticN = _noise(angle * 6.0 + hiOffset, i * 1.3);

            // Blend: smooth dominates when coherent; chaos dominates when incoherent
            const n = smoothN * Math.max(0, 1 - chaos * 0.7) + chaoticN * chaos * 0.9;
            const r = baseR + n * spikiness;
            points.push({
                x: cx + Math.cos(angle) * r,
                y: cy + Math.sin(angle) * r,
            });
        }

        // Color: calm steel-blue (#5B8DB8) → tense purple (#8b6abf)
        const t  = state.dTension;
        const r  = Math.round(91  + t * (139 - 91));
        const g  = Math.round(141 + t * (106 - 141));
        const b  = Math.round(184 + t * (191 - 184));

        // Outer glow
        const glowR = baseR + spikiness + 24;
        const grd   = ctx.createRadialGradient(cx, cy, baseR * 0.4, cx, cy, glowR);
        grd.addColorStop(0, `rgba(${r},${g},${b},0.10)`);
        grd.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.beginPath();
        ctx.arc(cx, cy, glowR, 0, Math.PI * 2);
        ctx.fillStyle = grd;
        ctx.fill();

        // Blob fill + stroke
        ctx.beginPath();
        points.forEach((p, i) => i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y));
        ctx.closePath();
        ctx.fillStyle   = `rgba(${r},${g},${b},0.16)`;
        ctx.fill();
        ctx.strokeStyle = `rgb(${r},${g},${b})`;
        ctx.lineWidth   = 1.5;
        ctx.stroke();
    }

    // ── Arc ring drawing ──────────────────────────────────────────

    function _drawArcRing() {
        const ctx = state.ctx;
        if (!ctx) return;

        const css = 400;
        const cx  = css / 2;
        const cy  = css / 2;
        const coh = state.dCoherence;
        const deg2rad = Math.PI / 180;

        for (let s = 0; s < BENEFIT_SEGMENTS.length; s++) {
            const seg = BENEFIT_SEGMENTS[s];
            const startRad = seg.startDeg * deg2rad;
            const endRad   = (seg.startDeg + seg.spanDeg) * deg2rad;

            // 1. Draw background track
            ctx.beginPath();
            ctx.arc(cx, cy, ARC_RADIUS, startRad, endRad);
            ctx.strokeStyle = 'rgba(91, 141, 184, 0.15)';
            ctx.lineWidth   = ARC_STROKE;
            ctx.lineCap     = 'round';
            ctx.stroke();

            // 2. Calculate fill based on coherence thresholds
            let fill = 0;
            if (coh >= seg.threshHi) {
                fill = 1;
            } else if (coh > seg.threshLo) {
                fill = (coh - seg.threshLo) / (seg.threshHi - seg.threshLo);
            }

            // 3. Draw filled arc
            if (fill > 0) {
                const fillEndRad = startRad + (endRad - startRad) * fill;
                ctx.beginPath();
                ctx.arc(cx, cy, ARC_RADIUS, startRad, fillEndRad);
                ctx.strokeStyle = 'rgba(91, 141, 184, 0.8)';
                ctx.lineWidth   = ARC_STROKE;
                ctx.lineCap     = 'round';
                ctx.stroke();
            }

            // 4. Draw endpoint dots
            const dotAlpha = fill > 0 ? 0.8 : 0.2;
            const dotColor = `rgba(91, 141, 184, ${dotAlpha})`;

            // Start dot
            ctx.beginPath();
            ctx.arc(
                cx + Math.cos(startRad) * ARC_RADIUS,
                cy + Math.sin(startRad) * ARC_RADIUS,
                ARC_DOT_R, 0, Math.PI * 2
            );
            ctx.fillStyle = dotColor;
            ctx.fill();

            // End dot
            ctx.beginPath();
            ctx.arc(
                cx + Math.cos(endRad) * ARC_RADIUS,
                cy + Math.sin(endRad) * ARC_RADIUS,
                ARC_DOT_R, 0, Math.PI * 2
            );
            ctx.fillStyle = `rgba(91, 141, 184, ${fill > 0.99 ? 0.8 : 0.2})`;
            ctx.fill();

            // 5. Labels — positioned at segment midpoint, offset outward
            const midRad    = (startRad + endRad) / 2;
            const labelR    = ARC_RADIUS + 22;
            const labelX    = cx + Math.cos(midRad) * labelR;
            const labelY    = cy + Math.sin(midRad) * labelR;
            const pct       = Math.round(fill * 100);
            const litAlpha  = fill > 0 ? 0.9 : 0.4;

            // Segment number
            const numR = ARC_RADIUS - 14;
            const numX = cx + Math.cos(midRad) * numR;
            const numY = cy + Math.sin(midRad) * numR;
            ctx.font      = '11px Inter, sans-serif';
            ctx.fillStyle = `rgba(91, 141, 184, ${litAlpha})`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(String(s + 1), numX, numY);

            // Percentage
            ctx.font      = '10px Inter, sans-serif';
            ctx.fillStyle = `rgba(91, 141, 184, ${litAlpha})`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(pct + '%', labelX, labelY - 6);

            // Benefit name
            ctx.fillText(seg.name, labelX, labelY + 6);
        }
    }

    // ── UI updates ─────────────────────────────────────────────────

    function _updateUI() {
        const cohPct  = Math.round(state.dCoherence * 100);
        const tenPct  = Math.round(state.dTension   * 100);
        const presPct = Math.round(state.dPresence  * 100);

        _setText('sculptor-coherence', cohPct);
        _setText('sculptor-pct-coherence', cohPct + '%');
        _setText('sculptor-pct-tension',   tenPct + '%');
        _setText('sculptor-pct-presence',  presPct + '%');

        _setWidth('sculptor-fill-coherence', cohPct + '%');
        _setWidth('sculptor-fill-tension',   tenPct + '%');
        _setWidth('sculptor-fill-presence',  presPct + '%');

        // Tint coherence score when tense
        const el = document.getElementById('sculptor-coherence');
        if (el) el.classList.toggle('stressed', state.dTension > 0.55);
    }

    function _setText(id, val) {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    }

    function _setWidth(id, val) {
        const el = document.getElementById(id);
        if (el) el.style.width = val;
    }

    function _setStatus(msg) {
        const el = document.getElementById('sculptor-status');
        if (el) el.textContent = msg;
    }

    // ── Render HTML ────────────────────────────────────────────────

    function _render() {
        const container = document.getElementById('sculptor-view');
        if (!container) return;

        container.innerHTML = `
            <div class="sculptor-header">
                <div class="sculptor-title">Voice Sculptor</div>
                <div class="sculptor-subtitle">
                    Your voice shapes the form in real time. Breathe and hum steadily.
                </div>
            </div>

            <div class="sculptor-coherence-wrap">
                <div class="sculptor-coherence-label">Coherence</div>
                <div class="sculptor-coherence-value" id="sculptor-coherence">50</div>
            </div>

            <div class="sculptor-stage">
                <canvas class="sculptor-blob-canvas" id="sculptor-blob"></canvas>
            </div>

            <div class="sculptor-bars">
                <div class="sculptor-bar-row">
                    <div class="sculptor-bar-label-row">
                        <span class="sculptor-bar-name">Voice Coherence</span>
                        <span class="sculptor-bar-pct" id="sculptor-pct-coherence">50%</span>
                    </div>
                    <div class="sculptor-bar-bg">
                        <div class="sculptor-bar-fill" id="sculptor-fill-coherence" style="width:50%"></div>
                    </div>
                </div>
                <div class="sculptor-bar-row">
                    <div class="sculptor-bar-label-row">
                        <span class="sculptor-bar-name">Tension Index</span>
                        <span class="sculptor-bar-pct" id="sculptor-pct-tension">30%</span>
                    </div>
                    <div class="sculptor-bar-bg">
                        <div class="sculptor-bar-fill tension" id="sculptor-fill-tension" style="width:30%"></div>
                    </div>
                </div>
                <div class="sculptor-bar-row">
                    <div class="sculptor-bar-label-row">
                        <span class="sculptor-bar-name">Presence</span>
                        <span class="sculptor-bar-pct" id="sculptor-pct-presence">10%</span>
                    </div>
                    <div class="sculptor-bar-bg">
                        <div class="sculptor-bar-fill" id="sculptor-fill-presence" style="width:10%"></div>
                    </div>
                </div>
            </div>

            <div class="sculptor-status" id="sculptor-status">Initializing…</div>
        `;

        // Set up Retina canvas
        const canvas = document.getElementById('sculptor-blob');
        if (!canvas) return;

        const dpr = window.devicePixelRatio || 1;
        const css = 400;
        canvas.style.width  = css + 'px';
        canvas.style.height = css + 'px';
        canvas.width  = css * dpr;
        canvas.height = css * dpr;

        state.canvas = canvas;
        state.ctx    = canvas.getContext('2d');
        state.ctx.scale(dpr, dpr);
    }

    // ── Public API ─────────────────────────────────────────────────

    return { load, unload };

})();
