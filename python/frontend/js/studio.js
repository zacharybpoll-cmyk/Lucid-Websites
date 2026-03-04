/**
 * studio.js — Live Voice Studio
 * Lucid Voice Wellness Monitor
 *
 * Real-time biofeedback via voice.
 * WebSocket client for biomarker streaming + breathing pacer + waveform visualization.
 *
 * Real-time biomarkers (fast DSP estimates, NOT full pipeline scores):
 *   - Vocal Steadiness   : jitter inverse    (pitch period consistency)
 *   - Voice Clarity      : HNR estimate      (harmonic-to-noise ratio)
 *   - Tone Stability     : F0 variance inv.  (pitch steadiness over time)
 *
 * Architecture:
 *   - studioView is exposed as a global IIFE so index.html can call studioView.load()
 *   - All DOM mutations are guarded; the module is safe to load early
 *   - Falls back to simulated gauge data when WebSocket is unavailable (dev mode)
 */

/* global switchView */

const studioView = (() => {

    // ── Constants ─────────────────────────────────────────────────────────────

    const WS_URL           = 'ws://localhost:8767/api/studio/ws';
    const API_START        = '/api/studio/start';
    const API_END          = '/api/studio/end';
    const BREATH_CYCLE_MS  = 5500;   // 5.5 s per inhale / exhale phase
    const SESSION_DURATION = 180;    // seconds (3 min default)
    const GAUGE_ALPHA      = 0.5;    // EMA smoothing (≈ 1 s at 500 ms updates)
    const COACHING_HOLDOFF = 15000;  // ms between coaching prompts
    const COACHING_SUSTAIN = 10;     // seconds of ≥0.6 average to trigger coaching
    const GAUGE_HIGH_MARK  = 0.65;   // above this: bar turns light-blue variant
    const SIM_INTERVAL_MS  = 500;    // simulated-data tick rate

    const COACHING_PROMPTS = [
        'jaw loose',
        'breath slower',
        'voice softer',
        'shoulders drop',
        'steady tone',
        'let it go',
        'long exhale',
    ];

    // ── State ─────────────────────────────────────────────────────────────────

    const state = {
        sessionId        : null,
        running          : false,
        ws               : null,
        wsRetryCount     : 0,
        wsSimulating     : false,

        breathPhase      : 'inhale',
        breathTimer      : null,

        sessionTimer     : null,
        sessionDuration  : SESSION_DURATION,
        sessionRemaining : SESSION_DURATION,

        coachingTimer    : null,
        lastCoachingMs   : 0,

        gaugeValues      : { vocal_steadiness: 0.40, voice_clarity: 0.45, tone_stability: 0.38 },
        baselineValues   : null,
        sustainedAbove   : 0,   // accumulated seconds of avg > GAUGE_HIGH_MARK

        waveformData     : [],
        waveformCanvas   : null,
        waveformCtx      : null,
        animFrame        : null,
    };

    // ── Entry point ───────────────────────────────────────────────────────────

    /**
     * Called by the router when the Studio tab becomes active.
     * Renders the view into #studio-view and initialises the waveform canvas.
     */
    function load() {
        _render();
        _setupWaveform();
    }

    // ── Rendering ─────────────────────────────────────────────────────────────

    function _render() {
        const container = document.getElementById('studio-view');
        if (!container) return;

        container.innerHTML = `
            <div class="studio-header">
                <div class="studio-title">Live Voice Studio</div>
                <div class="studio-subtitle">
                    Guide your voice to a calmer state — watch the biomarkers change in real time.
                </div>
            </div>

            <!-- Post-session summary (hidden until session ends) -->
            <div class="studio-summary" id="studio-summary"></div>

            <!-- Active session UI -->
            <div id="studio-session-ui">
                <div class="studio-layout">

                    <!-- ── Left: main stage ── -->
                    <div class="studio-stage">

                        <div class="studio-phase-label" id="studio-phase-label">
                            Ready to begin
                        </div>

                        <!-- Breathing circle -->
                        <div class="studio-breath-wrap">
                            <div class="studio-breath-circle" id="studio-breath-circle">
                                <div class="studio-breath-text" id="studio-breath-text">
                                    Begin Session
                                </div>
                            </div>
                        </div>

                        <!-- F0 waveform -->
                        <div class="studio-waveform-wrap">
                            <div class="studio-waveform-label">Voice Pitch (F0)</div>
                            <canvas
                                class="studio-waveform-canvas"
                                id="studio-waveform"
                                height="64"
                                aria-label="Real-time voice pitch waveform"
                            ></canvas>
                        </div>

                        <!-- Coaching nudge -->
                        <div class="studio-coaching-prompt" id="studio-coaching-prompt"
                             aria-live="polite"></div>

                        <!-- Timer + CTA -->
                        <div class="studio-controls">
                            <div class="studio-timer" id="studio-timer"
                                 aria-label="Session time remaining">3:00</div>
                            <button
                                class="studio-btn-primary"
                                id="studio-start-btn"
                                onclick="studioView.startSession()"
                            >Begin Session</button>
                        </div>

                        <div class="studio-disclaimer">
                            Real-time estimates only. Full acoustic analysis runs in background.&nbsp;
                            <a onclick="typeof switchView === 'function' && switchView('lab')">
                                Learn more
                            </a>
                        </div>

                    </div>
                    <!-- /studio-stage -->

                    <!-- ── Right: live gauge sidebar ── -->
                    <div class="studio-sidebar">

                        <div class="studio-sidebar-title">Live Biomarkers</div>

                        <div class="studio-gauge-card" id="card-steadiness">
                            <div class="studio-gauge-name">Vocal Steadiness</div>
                            <div class="studio-gauge-desc">Jitter — pitch period variation</div>
                            <div class="studio-gauge-bar-bg">
                                <div class="studio-gauge-bar-fill"
                                     id="gauge-steadiness"
                                     style="width:40%"></div>
                            </div>
                            <div class="studio-gauge-value-row">
                                <span class="studio-gauge-pct" id="pct-steadiness">40%</span>
                                <span class="studio-gauge-delta" id="delta-steadiness">—</span>
                            </div>
                        </div>

                        <div class="studio-gauge-card" id="card-clarity">
                            <div class="studio-gauge-name">Voice Clarity</div>
                            <div class="studio-gauge-desc">HNR — harmonic richness</div>
                            <div class="studio-gauge-bar-bg">
                                <div class="studio-gauge-bar-fill"
                                     id="gauge-clarity"
                                     style="width:45%"></div>
                            </div>
                            <div class="studio-gauge-value-row">
                                <span class="studio-gauge-pct" id="pct-clarity">45%</span>
                                <span class="studio-gauge-delta" id="delta-clarity">—</span>
                            </div>
                        </div>

                        <div class="studio-gauge-card" id="card-stability">
                            <div class="studio-gauge-name">Tone Stability</div>
                            <div class="studio-gauge-desc">F0 variance — pitch steadiness</div>
                            <div class="studio-gauge-bar-bg">
                                <div class="studio-gauge-bar-fill"
                                     id="gauge-stability"
                                     style="width:38%"></div>
                            </div>
                            <div class="studio-gauge-value-row">
                                <span class="studio-gauge-pct" id="pct-stability">38%</span>
                                <span class="studio-gauge-delta" id="delta-stability">—</span>
                            </div>
                        </div>

                        <div class="studio-sidebar-note">
                            Gauges update every 500&nbsp;ms using a 1&nbsp;s moving average.
                            Deltas are relative to your session baseline.
                        </div>

                    </div>
                    <!-- /studio-sidebar -->

                </div>
                <!-- /studio-layout -->
            </div>
            <!-- /studio-session-ui -->
        `;
    }

    // ── Waveform canvas ────────────────────────────────────────────────────────

    function _setupWaveform() {
        const canvas = document.getElementById('studio-waveform');
        if (!canvas) return;

        // Scale for device pixel ratio so lines are crisp on Retina
        const dpr = window.devicePixelRatio || 1;
        const cssW = canvas.offsetWidth || 420;
        canvas.width  = Math.floor(cssW * dpr);
        canvas.height = 64 * dpr;

        state.waveformCanvas = canvas;
        state.waveformCtx    = canvas.getContext('2d');

        // Seed with a flat midline
        const slots = Math.floor(canvas.width / (3 * dpr));
        state.waveformData = Array(Math.max(slots, 60)).fill(35);

        _drawWaveform();
    }

    function _drawWaveform() {
        const canvas = state.waveformCanvas;
        const ctx    = state.waveformCtx;
        if (!canvas || !ctx) return;

        const dpr = window.devicePixelRatio || 1;
        const w   = canvas.width;
        const h   = canvas.height;

        ctx.clearRect(0, 0, w, h);

        // Background
        ctx.fillStyle = '#f8f9fa';
        ctx.fillRect(0, 0, w, h);

        // Centre grid line
        ctx.save();
        ctx.strokeStyle  = '#e4e8ec';
        ctx.lineWidth    = 1 * dpr;
        ctx.setLineDash([4 * dpr, 5 * dpr]);
        ctx.beginPath();
        ctx.moveTo(0,   h / 2);
        ctx.lineTo(w,   h / 2);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.restore();

        // Waveform path
        const data = state.waveformData;
        if (data.length < 2) return;

        const step = w / (data.length - 1);
        const mid  = h / 2;
        // Map raw F0-derived value (centred at 35) to canvas pixels.
        // Range roughly ±25 units → ±(h*0.38) pixels.
        const yScale = (h * 0.38) / 25;

        ctx.save();
        ctx.beginPath();
        ctx.strokeStyle = '#5B8DB8';
        ctx.lineWidth   = 1.5 * dpr;
        ctx.lineJoin    = 'round';
        ctx.lineCap     = 'round';

        data.forEach((val, i) => {
            const x = i * step;
            const y = mid - (val - 35) * yScale;
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.stroke();
        ctx.restore();

        // Fill below the line for readability
        ctx.save();
        ctx.beginPath();
        data.forEach((val, i) => {
            const x = i * step;
            const y = mid - (val - 35) * yScale;
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.lineTo((data.length - 1) * step, h);
        ctx.lineTo(0, h);
        ctx.closePath();
        ctx.fillStyle = 'rgba(91,141,184,0.06)';
        ctx.fill();
        ctx.restore();

        if (state.running) {
            state.animFrame = requestAnimationFrame(_drawWaveform);
        }
    }

    function _pushWaveformSample(f0) {
        if (!state.waveformCanvas || !state.running) return;

        const dpr   = window.devicePixelRatio || 1;
        const slots = Math.floor(state.waveformCanvas.width / (3 * dpr));
        const maxLen = Math.max(slots, 60);

        // Normalise Hz (approx range 80–320) to a centred value around 35
        const norm = f0 ? Math.min(60, Math.max(10, ((f0 - 80) / 240) * 50)) : 35;
        state.waveformData.push(norm);

        if (state.waveformData.length > maxLen) {
            state.waveformData.shift();
        }
    }

    // ── Session lifecycle ──────────────────────────────────────────────────────

    async function startSession() {
        if (state.running) return;

        // Fetch session token + baseline from backend; graceful fallback
        try {
            const res = await fetch(API_START, { method: 'POST' });
            if (res.ok) {
                const data = await res.json();
                state.sessionId    = data.session_id;
                state.baselineValues = data.baseline || null;
            } else {
                throw new Error('non-ok response');
            }
        } catch (_) {
            state.sessionId    = `local_${Date.now()}`;
            state.baselineValues = { ...state.gaugeValues };
        }

        // If baseline not returned by server, snapshot current gauge values
        if (!state.baselineValues) {
            state.baselineValues = { ...state.gaugeValues };
        }

        state.running          = true;
        state.sessionRemaining = state.sessionDuration;
        state.sustainedAbove   = 0;
        state.lastCoachingMs   = Date.now();
        state.wsRetryCount     = 0;
        state.wsSimulating     = false;

        _setStartBtnMode('end');

        // Mark mic-active with a recording dot in the phase label
        _setPhaseLabel('<span class="studio-recording-dot"></span>Connecting…');

        // Connect WebSocket (or fall back to simulation)
        _connectWebSocket();

        // Start breath pacer
        _startBreathingPacer();

        // 1-second countdown ticker
        state.sessionTimer = setInterval(() => {
            state.sessionRemaining = Math.max(0, state.sessionRemaining - 1);
            _updateTimerDisplay();
            if (state.sessionRemaining <= 0) endSession();
        }, 1000);

        // Coaching check — every second
        state.coachingTimer = setInterval(_checkCoachingPrompt, 1000);

        // Start draw loop
        state.animFrame = requestAnimationFrame(_drawWaveform);
    }

    async function endSession() {
        if (!state.running) return;
        state.running = false;

        // Tear down timers
        clearInterval(state.sessionTimer);
        clearInterval(state.coachingTimer);
        state.sessionTimer  = null;
        state.coachingTimer = null;

        _stopBreathingPacer();

        // Close WebSocket
        if (state.ws) {
            state.ws.onclose = null; // prevent auto-reconnect
            state.ws.close();
            state.ws = null;
        }

        // Stop draw loop
        if (state.animFrame) {
            cancelAnimationFrame(state.animFrame);
            state.animFrame = null;
        }

        // Compute how long the session actually ran
        const durationSec = state.sessionDuration - state.sessionRemaining;

        // Fetch summary from backend; compute locally if unavailable
        let summary = null;
        try {
            const res = await fetch(API_END, {
                method  : 'POST',
                headers : { 'Content-Type': 'application/json' },
                body    : JSON.stringify({ session_id: state.sessionId }),
            });
            if (res.ok) {
                const data = await res.json();
                summary = data.summary;
            }
        } catch (_) {}

        if (!summary) {
            const cur = state.gaugeValues;
            const bas = state.baselineValues || cur;
            const relaxDelta = (
                (cur.vocal_steadiness - bas.vocal_steadiness) +
                (cur.voice_clarity    - bas.voice_clarity)    +
                (cur.tone_stability   - bas.tone_stability)
            ) / 3;
            summary = {
                relaxation_pct : Math.max(0, relaxDelta * 100).toFixed(1),
                baseline       : bas,
                end_state      : { ...cur },
                duration_sec   : durationSec,
            };
        }

        _showSummary(summary);
    }

    function _showSummary(summary) {
        const summaryEl  = document.getElementById('studio-summary');
        const sessionUi  = document.getElementById('studio-session-ui');
        if (!summaryEl) return;

        const relaxPct = Math.max(0, parseFloat(summary?.relaxation_pct || 0)).toFixed(0);
        const durSec   = summary?.duration_sec || 0;
        const m        = Math.floor(durSec / 60);
        const s        = Math.round(durSec % 60);
        const endState = summary?.end_state || state.gaugeValues;
        const baseline = summary?.baseline  || state.baselineValues || endState;

        // Delta chips per biomarker
        const metrics = [
            { label: 'Steadiness', key: 'vocal_steadiness' },
            { label: 'Clarity',    key: 'voice_clarity'    },
            { label: 'Stability',  key: 'tone_stability'   },
        ];

        const deltaChips = metrics.map(m => {
            const d     = ((endState[m.key] || 0) - (baseline[m.key] || 0)) * 100;
            const sign  = d >= 0 ? '+' : '';
            const cls   = d >= 1 ? 'improved' : d < -1 ? 'declined' : '';
            return `<span class="studio-delta-chip ${cls}">${m.label}: ${sign}${d.toFixed(0)}%</span>`;
        }).join('');

        summaryEl.innerHTML = `
            <div class="studio-summary-title">Session Complete</div>
            <div class="studio-summary-subtitle">
                Your voice relaxed by <strong>${relaxPct}%</strong> from baseline.
            </div>

            <div class="studio-summary-delta-row">${deltaChips}</div>

            <div class="studio-summary-stats">
                <div class="studio-summary-stat">
                    <div class="studio-summary-stat-value">${relaxPct}%</div>
                    <div class="studio-summary-stat-label">Relaxation</div>
                </div>
                <div class="studio-summary-stat">
                    <div class="studio-summary-stat-value">${m}:${String(s).padStart(2, '0')}</div>
                    <div class="studio-summary-stat-label">Duration</div>
                </div>
                <div class="studio-summary-stat">
                    <div class="studio-summary-stat-value">
                        ${Math.round((endState.vocal_steadiness || 0) * 100)}
                    </div>
                    <div class="studio-summary-stat-label">Final Steadiness</div>
                </div>
            </div>

            <div class="studio-summary-divider"></div>

            <div class="studio-summary-actions">
                <button class="studio-btn-primary"
                        onclick="studioView.resetSession()">New Session</button>
                <button class="studio-btn-secondary"
                        onclick="typeof switchView === 'function' && switchView('history')">
                    View History
                </button>
            </div>
        `;

        summaryEl.classList.add('visible');
        if (sessionUi) sessionUi.style.display = 'none';
    }

    function resetSession() {
        // Reset all state
        state.sessionId      = null;
        state.running        = false;
        state.baselineValues = null;
        state.wsRetryCount   = 0;
        state.wsSimulating   = false;
        state.sustainedAbove = 0;
        state.gaugeValues    = { vocal_steadiness: 0.40, voice_clarity: 0.45, tone_stability: 0.38 };

        // Re-render fresh UI
        _render();
        _setupWaveform();
    }

    // ── WebSocket ──────────────────────────────────────────────────────────────

    function _connectWebSocket() {
        try {
            state.ws = new WebSocket(WS_URL);

            state.ws.onopen = () => {
                console.log('[Studio] WebSocket connected');
                state.wsRetryCount = 0;
                state.wsSimulating = false;
                _setPhaseLabel('<span class="studio-recording-dot"></span>Listening…');
            };

            state.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    _handleIncomingFrame(data);
                } catch (_) {
                    // Ignore malformed frames
                }
            };

            state.ws.onclose = () => {
                console.log('[Studio] WebSocket closed');
                if (state.running) {
                    state.wsRetryCount++;
                    if (state.wsRetryCount <= 3) {
                        setTimeout(_connectWebSocket, 1200);
                    } else {
                        // Fall back to simulation after 3 failed attempts
                        _startSimulatedUpdates();
                    }
                }
            };

            state.ws.onerror = (e) => {
                console.warn('[Studio] WebSocket error — will fall back to simulation', e);
                // onclose fires after onerror; let it handle retry/fallback
            };

        } catch (e) {
            console.warn('[Studio] WebSocket constructor failed — using simulation', e);
            _startSimulatedUpdates();
        }
    }

    // Simulated data: gentle sinusoidal drift, good for dev / offline
    function _startSimulatedUpdates() {
        if (state.wsSimulating || !state.running) return;
        state.wsSimulating = true;
        console.info('[Studio] Using simulated biomarker data');

        const tick = () => {
            if (!state.running || !state.wsSimulating) return;
            const t = Date.now() / 1000;
            _handleIncomingFrame({
                vocal_steadiness : 0.50 + Math.sin(t * 0.31) * 0.11,
                voice_clarity    : 0.53 + Math.sin(t * 0.42) * 0.09,
                tone_stability   : 0.47 + Math.sin(t * 0.27) * 0.13,
                f0_mean          : 135  + Math.sin(t * 0.55) * 22,
            });
            setTimeout(tick, SIM_INTERVAL_MS);
        };
        tick();
    }

    function _handleIncomingFrame(data) {
        _updateGauges(data);
        _pushWaveformSample(data.f0_mean);
    }

    // ── Gauge updates ──────────────────────────────────────────────────────────

    function _updateGauges(data) {
        const g = state.gaugeValues;
        const a = GAUGE_ALPHA;

        // Exponential moving average
        if (data.vocal_steadiness !== undefined)
            g.vocal_steadiness = g.vocal_steadiness * (1 - a) + data.vocal_steadiness * a;
        if (data.voice_clarity !== undefined)
            g.voice_clarity    = g.voice_clarity    * (1 - a) + data.voice_clarity    * a;
        if (data.tone_stability !== undefined)
            g.tone_stability   = g.tone_stability   * (1 - a) + data.tone_stability   * a;

        const avg = (g.vocal_steadiness + g.voice_clarity + g.tone_stability) / 3;

        // Track sustained high state for coaching threshold
        if (avg >= GAUGE_HIGH_MARK) {
            state.sustainedAbove += SIM_INTERVAL_MS / 1000;
        } else {
            state.sustainedAbove = Math.max(0, state.sustainedAbove - 0.25);
        }

        // Update DOM
        _setGauge('gauge-steadiness', 'pct-steadiness', 'delta-steadiness',
                  g.vocal_steadiness, state.baselineValues?.vocal_steadiness);
        _setGauge('gauge-clarity',    'pct-clarity',    'delta-clarity',
                  g.voice_clarity,    state.baselineValues?.voice_clarity);
        _setGauge('gauge-stability',  'pct-stability',  'delta-stability',
                  g.tone_stability,   state.baselineValues?.tone_stability);
    }

    /**
     * Update a single gauge bar, percentage label, and delta label.
     * @param {string} barId     - element id for the fill bar
     * @param {string} pctId     - element id for the percentage label
     * @param {string} deltaId   - element id for the delta label
     * @param {number} val       - current value [0–1]
     * @param {number} [base]    - baseline value for delta calculation
     */
    function _setGauge(barId, pctId, deltaId, val, base) {
        const clamped = Math.min(1, Math.max(0, val));
        const pct     = Math.round(clamped * 100);

        const bar = document.getElementById(barId);
        if (bar) {
            bar.style.width = pct + '%';
            if (clamped >= GAUGE_HIGH_MARK) {
                bar.classList.add('high');
            } else {
                bar.classList.remove('high');
            }
        }

        const pctEl = document.getElementById(pctId);
        if (pctEl) pctEl.textContent = pct + '%';

        const deltaEl = document.getElementById(deltaId);
        if (deltaEl && base !== undefined && base !== null) {
            const d    = Math.round((clamped - base) * 100);
            const sign = d >= 0 ? '+' : '';
            deltaEl.textContent = `${sign}${d}%`;
            deltaEl.className   = 'studio-gauge-delta' + (d > 0 ? ' positive' : d < 0 ? ' negative' : '');
        }
    }

    // ── Breathing pacer ────────────────────────────────────────────────────────

    function _startBreathingPacer() {
        _setBreathPhase('inhale');
        state.breathTimer = setInterval(() => {
            _setBreathPhase(state.breathPhase === 'inhale' ? 'exhale' : 'inhale');
        }, BREATH_CYCLE_MS);
    }

    function _stopBreathingPacer() {
        clearInterval(state.breathTimer);
        state.breathTimer  = null;
        state.breathPhase  = 'inhale';

        const circle = document.getElementById('studio-breath-circle');
        const text   = document.getElementById('studio-breath-text');
        if (circle) { circle.className = 'studio-breath-circle'; }
        if (text)   { text.textContent = 'Session ended'; }
        _setPhaseLabel('Session complete');
    }

    function _setBreathPhase(phase) {
        state.breathPhase = phase;

        const circle = document.getElementById('studio-breath-circle');
        const text   = document.getElementById('studio-breath-text');

        if (circle) circle.className = `studio-breath-circle ${phase}`;
        if (text)   text.textContent = phase === 'inhale' ? 'Breathe in…' : 'Breathe out… hum';

        _setPhaseLabel(
            phase === 'inhale'
                ? 'Inhale — 5.5 seconds'
                : 'Exhale — 5.5 seconds'
        );
    }

    // ── Coaching prompts ───────────────────────────────────────────────────────

    function _checkCoachingPrompt() {
        if (!state.running) return;

        const el  = document.getElementById('studio-coaching-prompt');
        if (!el) return;

        const now = Date.now();
        const sinceLastMs = now - state.lastCoachingMs;

        if (
            state.sustainedAbove >= COACHING_SUSTAIN &&
            sinceLastMs >= COACHING_HOLDOFF
        ) {
            const prompt = COACHING_PROMPTS[
                Math.floor(Math.random() * COACHING_PROMPTS.length)
            ];
            el.textContent = prompt;
            el.classList.add('visible');
            state.lastCoachingMs = now;

            // Auto-hide after 5 s
            setTimeout(() => el.classList.remove('visible'), 5000);
        }
    }

    // ── UI helpers ─────────────────────────────────────────────────────────────

    function _updateTimerDisplay() {
        const el = document.getElementById('studio-timer');
        if (!el) return;
        const r = state.sessionRemaining;
        const m = Math.floor(r / 60);
        const s = r % 60;
        el.textContent = `${m}:${String(s).padStart(2, '0')}`;
    }

    /**
     * Set the phase label text. Accepts HTML (for recording dot).
     * @param {string} html
     */
    function _setPhaseLabel(html) {
        const el = document.getElementById('studio-phase-label');
        if (el) el.innerHTML = html;
    }

    /**
     * Toggle the start button between "begin" and "end" mode.
     * @param {'start'|'end'} mode
     */
    function _setStartBtnMode(mode) {
        const btn = document.getElementById('studio-start-btn');
        if (!btn) return;
        if (mode === 'end') {
            btn.textContent = 'End Session';
            btn.onclick     = () => endSession();
        } else {
            btn.textContent = 'Begin Session';
            btn.onclick     = () => startSession();
        }
    }

    // ── Public API ─────────────────────────────────────────────────────────────

    return {
        load,
        startSession,
        endSession,
        resetSession,
    };

})();
