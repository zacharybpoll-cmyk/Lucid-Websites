/**
 * Voice Scan (Active Assessment) — frontend logic
 * State machine: idle → recording → analyzing → results
 */
const ActiveAssessment = (() => {
    // Guided prompts
    const PROMPTS = [
        "Talk about how your day has been going so far...",
        "How have you been sleeping lately?",
        "Describe something that's been on your mind recently...",
        "What's been your biggest challenge this week?",
        "Talk about something you're looking forward to...",
        "How have you been feeling about your work recently?",
        "Describe your energy levels over the past few days...",
        "What's one thing that made you smile recently?",
        "Talk about how you've been spending your free time...",
        "How would you describe your stress levels right now?",
    ];

    let state = 'idle'; // idle | recording | analyzing | results
    let pollInterval = null;
    let currentPrompt = '';
    let currentResult = null;

    function init() {
        _shufflePrompt();
        _bindEvents();
        loadHistory();
    }

    function _shufflePrompt() {
        const idx = Math.floor(Math.random() * PROMPTS.length);
        currentPrompt = PROMPTS[idx];
        const el = document.getElementById('vs-prompt-text');
        if (el) el.textContent = currentPrompt;
    }

    function _bindEvents() {
        const shuffleBtn = document.getElementById('vs-shuffle-btn');
        if (shuffleBtn) shuffleBtn.addEventListener('click', _shufflePrompt);

        const startBtn = document.getElementById('vs-start-btn');
        if (startBtn) startBtn.addEventListener('click', startRecording);

        const stopBtn = document.getElementById('vs-stop-btn');
        if (stopBtn) stopBtn.addEventListener('click', stopRecording);

        const cancelBtn = document.getElementById('vs-cancel-btn');
        if (cancelBtn) cancelBtn.addEventListener('click', cancelRecording);

        const newScanBtn = document.getElementById('vs-new-scan-btn');
        if (newScanBtn) newScanBtn.addEventListener('click', resetToIdle);
    }

    function _setState(newState) {
        state = newState;
        document.querySelectorAll('#voicescan-view .vs-state').forEach(el => {
            el.classList.toggle('active', el.dataset.state === newState);
        });
    }

    // ========== Recording ==========

    async function startRecording() {
        try {
            const resp = await fetch('/api/active/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt_text: currentPrompt }),
            });
            if (!resp.ok) {
                const err = await resp.json();
                alert(err.detail || 'Failed to start recording');
                return;
            }
            _setState('recording');
            // Reset UI
            document.getElementById('vs-stop-btn').disabled = true;
            _startPolling();
        } catch (e) {
            console.error('Start recording error:', e);
        }
    }

    async function stopRecording() {
        _stopPolling();
        _setState('analyzing');

        try {
            const resp = await fetch('/api/active/stop', { method: 'POST' });
            const data = await resp.json();

            if (!resp.ok || data.error) {
                // Don't alert — just return to idle gracefully
                console.warn('Voice scan stop:', data.detail || data.error);
                _setState('idle');
                _shufflePrompt();
                return;
            }

            currentResult = data;
            _renderResults(data);
            _setState('results');
            loadHistory();
        } catch (e) {
            console.error('Stop recording error:', e);
            _setState('idle');
            _shufflePrompt();
        }
    }

    async function cancelRecording() {
        _stopPolling();
        try {
            await fetch('/api/active/cancel', { method: 'POST' });
        } catch (e) { /* ignore */ }
        _setState('idle');
    }

    function resetToIdle() {
        currentResult = null;
        _shufflePrompt();
        _setState('idle');
    }

    // ========== Polling ==========

    function _startPolling() {
        _stopPolling();
        pollInterval = setInterval(_pollStatus, 200);
    }

    function _stopPolling() {
        if (pollInterval) {
            clearInterval(pollInterval);
            pollInterval = null;
        }
    }

    async function _pollStatus() {
        try {
            const resp = await fetch('/api/active/status');
            const data = await resp.json();
            if (!data.active && state === 'recording') {
                // Session ended externally (max time hit) — just return to idle quietly
                _stopPolling();
                _setState('idle');
                _shufflePrompt();
                return;
            }
            _updateRecordingUI(data);
        } catch (e) { /* ignore poll errors */ }
    }

    function _updateRecordingUI(data) {
        // Timers
        const totalEl = document.getElementById('vs-total-time');
        const speechEl = document.getElementById('vs-speech-time');
        if (totalEl) totalEl.textContent = _formatTime(data.total_recording_sec || 0);
        if (speechEl) speechEl.textContent = _formatTime(data.speech_duration_sec || 0);

        // Speech progress
        const minSpeech = data.min_speech_sec || 30;
        const speechSec = data.speech_duration_sec || 0;
        const pct = Math.min(100, (speechSec / minSpeech) * 100);
        const fillEl = document.getElementById('vs-progress-fill');
        const labelEl = document.getElementById('vs-progress-label');
        if (fillEl) fillEl.style.width = pct + '%';
        if (labelEl) labelEl.textContent = `${speechSec.toFixed(0)}s / ${minSpeech}s speech`;

        // Stop button
        const stopBtn = document.getElementById('vs-stop-btn');
        if (stopBtn) stopBtn.disabled = !data.ready_for_analysis;

        // Level meter
        _renderLevelMeter(data.rms_levels || []);
    }

    function _renderLevelMeter(levels) {
        const container = document.getElementById('vs-level-meter');
        if (!container) return;

        const barCount = 30;
        // Ensure we have enough bars
        while (container.children.length < barCount) {
            const bar = document.createElement('div');
            bar.className = 'vs-level-bar';
            container.appendChild(bar);
        }

        // Map levels to bar heights (take last N levels)
        const recent = levels.slice(-barCount);
        const maxRms = 0.15; // normalization cap
        for (let i = 0; i < barCount; i++) {
            const bar = container.children[i];
            const val = i < recent.length ? recent[recent.length - 1 - (barCount - 1 - i)] : 0;
            const normalized = Math.min(1, (val || 0) / maxRms);
            const height = 4 + normalized * 76; // min 4px, max 80px
            bar.style.height = height + 'px';
        }
    }

    function _formatTime(sec) {
        const m = Math.floor(sec / 60);
        const s = Math.floor(sec % 60);
        return `${m}:${s.toString().padStart(2, '0')}`;
    }

    // ========== Population Percentile ==========

    const PERCENTILE_TABLES = {
        phq9: [[0,32],[1,45],[2,55],[3,63],[4,75],[5,80],[7,87],[10,93],[15,99],[20,99.5],[27,100]],
        gad7: [[0,35],[1,48],[2,58],[3,68],[4,84],[5,85],[7,90],[10,95],[15,99],[21,100]],
    };

    function _getPercentile(score, type) {
        const table = PERCENTILE_TABLES[type];
        if (!table) return null;
        if (score <= table[0][0]) return table[0][1];
        if (score >= table[table.length - 1][0]) return table[table.length - 1][1];
        for (let i = 1; i < table.length; i++) {
            if (score <= table[i][0]) {
                const [x0, y0] = table[i - 1];
                const [x1, y1] = table[i];
                return y0 + (y1 - y0) * (score - x0) / (x1 - x0);
            }
        }
        return table[table.length - 1][1];
    }

    function _buildPopulationCurveHtml(canvasId, title, score, maxScore, percentile) {
        const axisPoints = maxScore === 27 ? [0, 5, 10, 15, 20, 27] : [0, 5, 10, 15, 21];
        const axisHtml = axisPoints.map(v => `<span>${v}</span>`).join('');
        const pctRound = Math.round(percentile);
        return `<div class="vs-population-card">
            <div class="vs-population-title">${title}</div>
            <div class="vs-population-chart" id="${canvasId}-container">
                <canvas id="${canvasId}"></canvas>
                <div class="vs-population-score-label" id="${canvasId}-label">
                    <div class="vs-population-score-value">${score.toFixed(1)}</div>
                    <div class="vs-population-percentile">${pctRound}th percentile</div>
                </div>
            </div>
            <div class="vs-population-axis">${axisHtml}</div>
            <div class="vs-population-footnote">Higher than ${pctRound}% of the general U.S. adult population</div>
        </div>`;
    }

    function _drawPopulationCurve(canvasId, score, maxScore) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const dpr = window.devicePixelRatio || 1;
        const container = document.getElementById(canvasId + '-container');
        const W = container.clientWidth;
        const H = 140;
        canvas.width = W * dpr;
        canvas.height = H * dpr;
        canvas.style.width = W + 'px';
        canvas.style.height = H + 'px';
        ctx.scale(dpr, dpr);

        const padT = 8, padB = 4;
        const chartH = H - padT - padB;

        // Right-skewed gamma-like PDF
        function pdf(x) {
            if (x <= 0) return 0;
            const k = 1.8, theta = 1.8;
            return Math.pow(x, k - 1) * Math.exp(-x / theta);
        }

        const points = [];
        let maxY = 0;
        for (let i = 0; i <= 200; i++) {
            const x = (i / 200) * maxScore;
            const y = pdf(x);
            if (y > maxY) maxY = y;
            points.push({ x, y });
        }

        function xToC(x) { return (x / maxScore) * W; }
        function yToC(y) { return padT + chartH - (y / maxY) * chartH * 0.9; }

        const scoreX = xToC(score);
        const scoreYVal = pdf(score);

        // Filled area left of score
        ctx.beginPath();
        ctx.moveTo(0, yToC(0));
        for (const p of points) {
            if (xToC(p.x) > scoreX) break;
            ctx.lineTo(xToC(p.x), yToC(p.y));
        }
        ctx.lineTo(scoreX, yToC(scoreYVal));
        ctx.lineTo(scoreX, yToC(0));
        ctx.closePath();
        const gradFill = ctx.createLinearGradient(0, 0, W, 0);
        gradFill.addColorStop(0, 'rgba(91,141,184,0.35)');
        gradFill.addColorStop(0.5, 'rgba(91,141,184,0.2)');
        gradFill.addColorStop(1, 'rgba(75,85,99,0.15)');
        ctx.fillStyle = gradFill;
        ctx.fill();

        // Right side light fill
        ctx.beginPath();
        let started = false;
        for (const p of points) {
            if (xToC(p.x) < scoreX) continue;
            if (!started) { ctx.moveTo(scoreX, yToC(scoreYVal)); started = true; }
            ctx.lineTo(xToC(p.x), yToC(p.y));
        }
        ctx.lineTo(W, yToC(0));
        ctx.lineTo(scoreX, yToC(0));
        ctx.closePath();
        ctx.fillStyle = 'rgba(75,85,99,0.06)';
        ctx.fill();

        // Curve outline with gradient
        ctx.beginPath();
        ctx.moveTo(0, yToC(0));
        for (const p of points) ctx.lineTo(xToC(p.x), yToC(p.y));
        ctx.lineTo(W, yToC(0));
        const gradLine = ctx.createLinearGradient(0, 0, W, 0);
        gradLine.addColorStop(0, '#5B8DB8');
        gradLine.addColorStop(0.6, '#6B7A8D');
        gradLine.addColorStop(1, '#4B5563');
        ctx.strokeStyle = gradLine;
        ctx.lineWidth = 2;
        ctx.stroke();

        // Dashed vertical marker line
        ctx.beginPath();
        ctx.moveTo(scoreX, yToC(scoreYVal) - 4);
        ctx.lineTo(scoreX, yToC(0));
        ctx.strokeStyle = 'var(--text-primary, #1a1d21)';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 3]);
        ctx.stroke();
        ctx.setLineDash([]);

        // Glowing dot
        ctx.beginPath();
        ctx.arc(scoreX, yToC(scoreYVal), 10, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(91,141,184,0.15)';
        ctx.fill();
        ctx.beginPath();
        ctx.arc(scoreX, yToC(scoreYVal), 6, 0, Math.PI * 2);
        ctx.fillStyle = '#5B8DB8';
        ctx.fill();
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 2.5;
        ctx.stroke();

        // Position floating label
        const label = document.getElementById(canvasId + '-label');
        if (label) {
            label.style.left = scoreX + 'px';
            label.style.bottom = (H - yToC(scoreYVal) + 14) + 'px';
        }
    }

    // ========== Results ==========

    function _renderResults(data) {
        const container = document.getElementById('vs-results-content');
        if (!container) return;

        const depMapped = data.depression_mapped != null ? data.depression_mapped : 0;
        const anxMapped = data.anxiety_mapped != null ? data.anxiety_mapped : 0;

        // Meta
        document.getElementById('vs-results-meta').textContent =
            `${data.speech_duration_sec}s speech analyzed`;

        // PHQ-9 severity bar
        const phq9Html = _buildSeverityBar('PHQ-9 (Depression)', depMapped, 27, [
            { label: 'None', max: 4, cls: 'seg-none' },
            { label: 'Mild', max: 9, cls: 'seg-mild' },
            { label: 'Moderate', max: 14, cls: 'seg-moderate' },
            { label: 'Mod. Severe', max: 19, cls: 'seg-modsev' },
            { label: 'Severe', max: 27, cls: 'seg-severe' },
        ], data.depression_ci_lower, data.depression_ci_upper, 'phq9');

        // GAD-7 severity bar
        const gad7Html = _buildSeverityBar('GAD-7 (Anxiety)', anxMapped, 21, [
            { label: 'Minimal', max: 4, cls: 'seg-minimal' },
            { label: 'Mild', max: 9, cls: 'seg-mild' },
            { label: 'Moderate', max: 14, cls: 'seg-moderate' },
            { label: 'Severe', max: 21, cls: 'seg-severe' },
        ], data.anxiety_ci_lower, data.anxiety_ci_upper, 'gad7');

        // Extra scores
        const extraScores = [
            { key: 'wellbeing_score', label: 'Wellbeing' },
            { key: 'calm_score', label: 'Calm' },
            { key: 'stress_score', label: 'Stress' },
            { key: 'activation_score', label: 'Activation' },
            { key: 'energy_score', label: 'Energy' },
            { key: 'emotional_stability_score', label: 'Stability' },
        ];
        const extrasHtml = extraScores.map(s => {
            const val = data[s.key] != null ? Math.round(data[s.key]) : '—';
            return `<div class="vs-extra-score">
                <div class="vs-extra-score-value">${val}</div>
                <div class="vs-extra-score-label">${s.label}</div>
            </div>`;
        }).join('');

        // Notes field
        const notesHtml = `<div class="vs-notes-card">
            <textarea class="vs-notes-textarea" id="vs-notes-input"
                placeholder="Add a note about how you're feeling..."></textarea>
            <button class="vs-notes-save" id="vs-notes-save-btn">Save Note</button>
        </div>`;

        // Population percentile curves
        const phq9Pct = _getPercentile(depMapped, 'phq9');
        const gad7Pct = _getPercentile(anxMapped, 'gad7');
        const phq9CurveHtml = _buildPopulationCurveHtml(
            'vs-pop-phq9', 'Population Comparison — PHQ-9', depMapped, 27, phq9Pct);
        const gad7CurveHtml = _buildPopulationCurveHtml(
            'vs-pop-gad7', 'Population Comparison — GAD-7', anxMapped, 21, gad7Pct);

        container.innerHTML = phq9Html + phq9CurveHtml + gad7Html + gad7CurveHtml +
            `<div id="vs-comparison-container"></div>` +
            `<div class="vs-extra-scores">${extrasHtml}</div>` +
            notesHtml;

        // Draw canvases after DOM insertion
        requestAnimationFrame(() => {
            _drawPopulationCurve('vs-pop-phq9', depMapped, 27);
            _drawPopulationCurve('vs-pop-gad7', anxMapped, 21);
        });

        // Bind notes save
        const saveBtn = document.getElementById('vs-notes-save-btn');
        if (saveBtn && data.id) {
            saveBtn.addEventListener('click', async () => {
                const notes = document.getElementById('vs-notes-input').value;
                try {
                    await fetch('/api/active/notes', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ id: data.id, notes }),
                    });
                    saveBtn.textContent = 'Saved';
                    setTimeout(() => saveBtn.textContent = 'Save Note', 2000);
                } catch (e) { console.error(e); }
            });
        }

        // Load comparison
        _loadComparison();
    }

    function _buildSeverityBar(title, score, maxScore, segments, ciLo, ciHi, barClass) {
        const scorePct = Math.min(100, (score / maxScore) * 100);

        // Find severity label
        let severityLabel = segments[0].label;
        let prevMax = -1;
        for (const seg of segments) {
            if (score > prevMax && score <= seg.max) {
                severityLabel = seg.label;
                break;
            }
            prevMax = seg.max;
        }
        if (score > segments[segments.length - 1].max) {
            severityLabel = segments[segments.length - 1].label;
        }

        // Segment widths
        let prevEnd = 0;
        const segsHtml = segments.map(seg => {
            const width = ((seg.max - prevEnd) / maxScore) * 100;
            prevEnd = seg.max;
            return `<div class="vs-severity-segment ${seg.cls}" style="width:${width}%"></div>`;
        }).join('');

        // CI text
        const ciText = (ciLo != null && ciHi != null)
            ? `CI: ${ciLo.toFixed(1)} – ${ciHi.toFixed(1)}`
            : '';

        // Interpretation
        const interpMap = {
            'None': 'Minimal or no symptoms detected',
            'Minimal': 'Minimal or no symptoms detected',
            'Mild': 'Mild symptoms — may benefit from monitoring',
            'Moderate': 'Moderate symptoms — consider follow-up',
            'Mod. Severe': 'Moderately severe — clinical attention recommended',
            'Severe': 'Severe symptoms — professional support recommended',
        };
        const interp = interpMap[severityLabel] || '';

        return `<div class="vs-scale-card">
            <div class="vs-scale-title">${title}</div>
            <div class="vs-severity-bar ${barClass}" style="position:relative">
                ${segsHtml}
                <div class="vs-score-indicator" style="left:${scorePct}%"></div>
            </div>
            <div class="vs-scale-details">
                <div>
                    <span class="vs-score-value">${score.toFixed(1)}</span>
                    <span class="vs-score-ci">${ciText}</span>
                </div>
                <div class="vs-severity-label">${severityLabel}</div>
            </div>
            <div class="vs-scale-interpretation">${interp}</div>
        </div>`;
    }

    async function _loadComparison() {
        try {
            const resp = await fetch('/api/active/compare');
            const data = await resp.json();
            const container = document.getElementById('vs-comparison-container');
            if (!container || !data.scan || !data.passive_avg) return;

            const metrics = [
                { key: 'depression_mapped', label: 'PHQ-9' },
                { key: 'anxiety_mapped', label: 'GAD-7' },
                { key: 'stress_score', label: 'Stress' },
                { key: 'mood_score', label: 'Mood' },
            ];

            const rows = metrics.map(m => {
                const scanVal = data.scan[m.key] != null ? data.scan[m.key].toFixed(1) : '—';
                const passiveVal = data.passive_avg[m.key] != null ? data.passive_avg[m.key].toFixed(1) : '—';
                return `<div class="vs-comparison-row">
                    <span class="vs-comparison-metric">${m.label}</span>
                    <div class="vs-comparison-values">
                        <span class="vs-comparison-scan">${scanVal}</span>
                        <span class="vs-comparison-passive">${passiveVal}</span>
                    </div>
                </div>`;
            }).join('');

            container.innerHTML = `<div class="vs-comparison">
                <div class="vs-comparison-title">How This Compares</div>
                <div class="vs-comparison-row" style="margin-bottom:6px">
                    <span></span>
                    <div class="vs-comparison-values">
                        <span class="vs-comparison-scan" style="font-size:11px">Scan</span>
                        <span class="vs-comparison-passive" style="font-size:11px">Passive Avg</span>
                    </div>
                </div>
                ${rows}
                <div class="vs-comparison-note">
                    Voice scans may differ from passive readings due to focused self-reflection and intentional speech patterns.
                </div>
            </div>`;
        } catch (e) { /* ignore */ }
    }

    // ========== History ==========

    async function loadHistory() {
        try {
            const resp = await fetch('/api/active/history?limit=10');
            const history = await resp.json();

            const html = (!history || history.length === 0)
                ? '<div class="vs-history-empty">No voice scans yet</div>'
                : history.map(item => {
                    const d = new Date(item.timestamp);
                    const dateStr = d.toLocaleDateString('en-US', {
                        month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'
                    });
                    const phq = item.depression_mapped != null ? item.depression_mapped.toFixed(1) : '—';
                    const gad = item.anxiety_mapped != null ? item.anxiety_mapped.toFixed(1) : '—';
                    return `<div class="vs-history-item" data-id="${item.id}">
                        <span class="vs-history-date">${dateStr}</span>
                        <div class="vs-history-scores">
                            PHQ-9: <span>${phq}</span> &nbsp; GAD-7: <span>${gad}</span>
                        </div>
                    </div>`;
                }).join('');

            // Populate both history containers
            ['vs-history-list', 'vs-idle-history-list'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.innerHTML = html;
            });
        } catch (e) {
            ['vs-history-list', 'vs-idle-history-list'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.innerHTML = '<div class="vs-history-empty">Failed to load history</div>';
            });
        }
    }

    // ========== Public API ==========

    function onNavigateAway() {
        if (state === 'recording') {
            cancelRecording();
        }
    }

    return { init, loadHistory, onNavigateAway, resetToIdle };
})();
