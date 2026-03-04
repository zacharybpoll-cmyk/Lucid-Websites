/**
 * sculptor.js — Voice Sculptor
 * Lucid Voice Wellness Monitor
 *
 * Animated blob visualizer driven by real-time voice biomarkers.
 * Connects to the same Studio WebSocket as a read-only listener.
 *
 * Blob behaviour:
 *   Calm (coherence high)   → smooth, slow, steel-blue (#5B8DB8)
 *   Stressed (tension high) → spiky, fast, purple-tinted (#8b6abf)
 *
 * Public API: sculptorView.load() / sculptorView.unload()
 */

/* global studioView */

const sculptorView = (() => {

    // ── Constants ──────────────────────────────────────────────────

    const WS_URL         = 'ws://localhost:8767/api/studio/ws';
    const SIM_INTERVAL   = 80;  // ms between animation frames when simulating
    const NOISE_SPEED    = 0.6; // base noise drift speed (radians/sec)
    const NUM_POINTS     = 128; // polygon resolution

    // ── State ──────────────────────────────────────────────────────

    const state = {
        ws          : null,
        animFrame   : null,
        canvas      : null,
        ctx         : null,
        loaded      : false,

        // Biomarker values (0–1)
        coherence   : 0.5,   // from vocal_steadiness
        tension     : 0.3,   // from raw_jitter  (or jitter proxy)
        presence    : 0.4,   // from rms_energy

        // Smoothed display values (EMA)
        dCoherence  : 0.5,
        dTension    : 0.3,
        dPresence   : 0.4,

        // Noise offsets
        noiseOffset : 0,
        lastTs      : null,
    };

    // ── Entry ──────────────────────────────────────────────────────

    function load() {
        _render();
        _connectWS();
        state.loaded    = true;
        state.lastTs    = null;
        state.animFrame = requestAnimationFrame(_animate);
    }

    function unload() {
        state.loaded = false;

        if (state.animFrame) {
            cancelAnimationFrame(state.animFrame);
            state.animFrame = null;
        }

        if (state.ws) {
            state.ws.onclose = null;
            state.ws.close();
            state.ws = null;
        }
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
                        <span class="sculptor-bar-pct" id="sculptor-pct-presence">40%</span>
                    </div>
                    <div class="sculptor-bar-bg">
                        <div class="sculptor-bar-fill" id="sculptor-fill-presence" style="width:40%"></div>
                    </div>
                </div>
            </div>

            <div class="sculptor-status" id="sculptor-status">Connecting to audio…</div>
        `;

        // Set up canvas
        const canvas = document.getElementById('sculptor-blob');
        if (!canvas) return;

        const dpr = window.devicePixelRatio || 1;
        const css = 300;
        canvas.style.width  = css + 'px';
        canvas.style.height = css + 'px';
        canvas.width  = css * dpr;
        canvas.height = css * dpr;

        state.canvas = canvas;
        state.ctx    = canvas.getContext('2d');
        state.ctx.scale(dpr, dpr);
    }

    // ── WebSocket (read-only listener) ─────────────────────────────

    function _connectWS() {
        try {
            state.ws = new WebSocket(WS_URL);

            state.ws.onopen = () => {
                console.log('[Sculptor] WS connected');
                _setStatus('Listening to your voice…');
            };

            state.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    _onFrame(data);
                } catch (_) {}
            };

            state.ws.onclose = () => {
                if (state.loaded) {
                    _setStatus('Simulating — microphone not active');
                }
            };

            state.ws.onerror = () => {
                _setStatus('Simulating — voice studio not running');
            };
        } catch (e) {
            console.warn('[Sculptor] WS failed', e);
            _setStatus('Simulating…');
        }
    }

    function _onFrame(data) {
        // Map server keys → sculptor biomarkers
        if (data.vocal_steadiness !== undefined)
            state.coherence = Math.min(1, Math.max(0, data.vocal_steadiness));
        // raw_jitter not always present; use 1 - vocal_steadiness as proxy
        if (data.raw_jitter !== undefined)
            state.tension = Math.min(1, Math.max(0, data.raw_jitter));
        else if (data.vocal_steadiness !== undefined)
            state.tension = Math.min(1, Math.max(0, 1 - data.vocal_steadiness));
        if (data.rms_energy !== undefined)
            state.presence = Math.min(1, Math.max(0, data.rms_energy));
        else if (data.voice_clarity !== undefined)
            state.presence = Math.min(1, Math.max(0, data.voice_clarity));
    }

    // ── Animation loop ─────────────────────────────────────────────

    function _animate(ts) {
        if (!state.loaded) return;

        const dt = state.lastTs !== null ? (ts - state.lastTs) / 1000 : 0;
        state.lastTs = ts;

        // EMA smoothing (τ ≈ 1.5s)
        const alpha = Math.min(1, dt / 1.5);
        state.dCoherence = state.dCoherence + alpha * (state.coherence - state.dCoherence);
        state.dTension   = state.dTension   + alpha * (state.tension   - state.dTension);
        state.dPresence  = state.dPresence  + alpha * (state.presence  - state.dPresence);

        // Noise offset drifts faster when tense
        const speed = NOISE_SPEED + state.dTension * 2.5;
        state.noiseOffset += dt * speed;

        _drawBlob(dt);
        _updateUI();

        state.animFrame = requestAnimationFrame(_animate);
    }

    // ── Blob drawing ───────────────────────────────────────────────

    /**
     * Smooth noise function using sum-of-sines (Perlin substitute).
     * Returns a value in [-1, 1].
     */
    function _noise(t, seed) {
        return (
            Math.sin(t * 1.7 + seed) * 0.5 +
            Math.sin(t * 3.1 + seed * 1.3) * 0.25 +
            Math.sin(t * 5.3 + seed * 2.1) * 0.125 +
            Math.sin(t * 8.7 + seed * 0.9) * 0.0625
        );
    }

    function _drawBlob() {
        const canvas = state.canvas;
        const ctx    = state.ctx;
        if (!canvas || !ctx) return;

        const dpr = window.devicePixelRatio || 1;
        const css = 300;
        ctx.clearRect(0, 0, css, css);

        // Reset transform (DPR scale was applied once in _render; we work in CSS coords)
        const cx = css / 2;
        const cy = css / 2;

        // Base radius: scales with presence
        const baseR = 80 + state.dPresence * 30;

        // Spikiness: driven by tension
        const spikiness = 8 + state.dTension * 40;

        // Build blob polygon
        const points = [];
        for (let i = 0; i < NUM_POINTS; i++) {
            const angle = (i / NUM_POINTS) * Math.PI * 2;
            const noiseVal = _noise(angle * 1.5 + state.noiseOffset, i * 0.4);
            const r = baseR + noiseVal * spikiness;
            points.push({
                x: cx + Math.cos(angle) * r,
                y: cy + Math.sin(angle) * r,
            });
        }

        // Interpolate color: calm steel-blue → stressed purple
        const t = state.dTension;
        const r = Math.round(91  + t * (139 - 91));
        const g = Math.round(141 + t * (106 - 141));
        const b = Math.round(184 + t * (191 - 184));
        const fillColor   = `rgba(${r},${g},${b},0.18)`;
        const strokeColor = `rgb(${r},${g},${b})`;

        // Outer glow
        const grd = ctx.createRadialGradient(cx, cy, baseR * 0.5, cx, cy, baseR + spikiness + 20);
        grd.addColorStop(0, `rgba(${r},${g},${b},0.08)`);
        grd.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.beginPath();
        ctx.arc(cx, cy, baseR + spikiness + 20, 0, Math.PI * 2);
        ctx.fillStyle = grd;
        ctx.fill();

        // Blob fill
        ctx.beginPath();
        points.forEach((p, i) => {
            i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y);
        });
        ctx.closePath();
        ctx.fillStyle   = fillColor;
        ctx.fill();
        ctx.strokeStyle = strokeColor;
        ctx.lineWidth   = 1.5;
        ctx.stroke();
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

        // Color the coherence number when stressed
        const cohEl = document.getElementById('sculptor-coherence');
        if (cohEl) {
            cohEl.classList.toggle('stressed', state.dTension > 0.6);
        }
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

    // ── Public API ─────────────────────────────────────────────────

    return { load, unload };

})();
