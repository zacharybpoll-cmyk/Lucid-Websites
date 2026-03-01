/**
 * Score circles + hero wellness + zone bar rendering
 * Oura-style translucent circles on forest canopy background
 */

// ============ Gauge analyzing state ============

let gaugesAreAnalyzing = false;
let prevCircleScores = {};
const ALL_METRICS = ['wellbeing','calm','activation','stress','depression','anxiety','emotional-stability'];

function startGaugeProgress() {
    if (gaugesAreAnalyzing) return;
    gaugesAreAnalyzing = true;
    ALL_METRICS.forEach(m => document.getElementById(`circle-${m}`)?.classList.add('gauge-analyzing'));
}

function finishGaugeProgress() {
    if (!gaugesAreAnalyzing) return;
    gaugesAreAnalyzing = false;
    ALL_METRICS.forEach(m => document.getElementById(`circle-${m}`)?.classList.remove('gauge-analyzing'));
}

function animateCircle(metric, value, duration) {
    const circumference = 2 * Math.PI * 30; // 188.5
    const clamped = Math.max(0, Math.min(100, value));
    const targetOffset = circumference - (clamped / 100) * circumference;
    const targetColor = getScoreColor(metric, clamped);
    const circle = document.querySelector(`#circle-${metric} .circle-progress`);
    const valueEl = document.getElementById(`circle-${metric}-value`);
    if (circle) {
        circle.style.strokeDashoffset = circumference; // reset to empty
        circle.setAttribute('stroke', targetColor);
    }
    const startTime = performance.now();
    function tick(now) {
        const progress = Math.min((now - startTime) / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
        if (circle) circle.style.strokeDashoffset = circumference - (clamped / 100) * circumference * eased;
        if (valueEl) valueEl.textContent = Math.round(clamped * eased);
        if (progress < 1) requestAnimationFrame(tick);
        else {
            if (circle) circle.setAttribute('stroke-dashoffset', targetOffset);
            if (valueEl) valueEl.textContent = Math.round(clamped);
        }
    }
    requestAnimationFrame(tick);
}

// ============ Score Circles (Oura-style) — legacy hidden elements ============

function updateScoreCircles(scores, canopyScore, delta) {
    const targets = {
        'wellbeing':           scores.wellbeing ?? scores.mood ?? 50,
        'calm':                scores.calm ?? 50,
        'activation':          scores.activation ?? scores.energy ?? 50,
        'stress':              scores.stress ?? 50,
        'depression':          scores.depression ?? 0,
        'anxiety':             scores.anxiety ?? 0,
        'emotional-stability': scores.emotional_stability ?? 50,
    };
    const hasNewData = Object.keys(targets).some(
        m => Math.abs((targets[m] || 0) - (prevCircleScores[m] || 0)) > 1
    );
    Object.entries(targets).forEach(([metric, value]) => {
        hasNewData ? animateCircle(metric, value, 1200) : updateCircle(metric, value);
    });
    prevCircleScores = {...targets};

    // Drive ring gauge + metric bars (skip if ring gauge is in analyzing state)
    if (!_ringAnalyzing) {
        const effectiveCanopy = canopyScore !== undefined && canopyScore !== null
            ? canopyScore : _gaugeState.canopy;
        renderRingGauge(effectiveCanopy, scores, delta);
    }
    updateMetricBars(scores);
}

function updateCircle(metric, value) {
    const circumference = 2 * Math.PI * 30; // r=30
    const clamped = Math.max(0, Math.min(100, value));
    const offset = circumference - (clamped / 100) * circumference;

    const circle = document.querySelector(`#circle-${metric} .circle-progress`);
    const valueEl = document.getElementById(`circle-${metric}-value`);

    if (circle) {
        circle.setAttribute('stroke-dashoffset', offset);
        circle.setAttribute('stroke', getScoreColor(metric, clamped));
    }
    if (valueEl) {
        valueEl.textContent = Math.round(clamped);
    }
}

// ============ Dynamic Score Colors ============

const NEGATIVE_METRICS = ['stress', 'depression', 'anxiety'];

function getScoreColor(metric, value) {
    // For negative metrics, flip so 0=green, 100=red
    let normalized = NEGATIVE_METRICS.includes(metric) ? (100 - value) : value;
    normalized = Math.max(0, Math.min(100, normalized));

    // Three-stop interpolation: red(0) -> amber(50) -> green(100)
    const red   = [196, 88, 76];   // #c4584c
    const amber = [138, 158, 170]; // #8a9eaa cool steel-neutral gray
    const green = [90, 154, 110];  // #5a9a6e

    let r, g, b;
    if (normalized <= 50) {
        const t = normalized / 50;
        r = Math.round(red[0] + (amber[0] - red[0]) * t);
        g = Math.round(red[1] + (amber[1] - red[1]) * t);
        b = Math.round(red[2] + (amber[2] - red[2]) * t);
    } else {
        const t = (normalized - 50) / 50;
        r = Math.round(amber[0] + (green[0] - amber[0]) * t);
        g = Math.round(amber[1] + (green[1] - amber[1]) * t);
        b = Math.round(amber[2] + (green[2] - amber[2]) * t);
    }

    return `rgb(${r}, ${g}, ${b})`;
}

// ============ Ring Gauge Progress (Analyzing State) ============

let _ringAnalyzing = false;
let _ringProgressRAF = null;
let _ringProgressStart = 0;
let _ringSafetyTimer = null;

// ============ Score Reveal Flags ============
let _ringScoreReveal = false;  // set on analysis finish, consumed by renderRingGauge()
let _metBarReveal = false;     // set on analysis finish, consumed by updateMetricBars()

function startMetricBarPulse() {
    document.querySelectorAll('.metbar-item').forEach(el => el.classList.add('metbar-analyzing'));
}

function stopMetricBarPulse() {
    document.querySelectorAll('.metbar-item').forEach(el => el.classList.remove('metbar-analyzing'));
}

function animateMetricBar(valEl, fillEl, rawTarget, pctTarget, duration, delay) {
    setTimeout(() => {
        const startTime = performance.now();
        // Disable CSS transition during JS animation
        if (fillEl) fillEl.style.transition = 'none';
        function tick(now) {
            const progress = Math.min((now - startTime) / duration, 1);
            const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
            if (valEl) valEl.textContent = Math.round(rawTarget * eased) + '%';
            if (fillEl) fillEl.style.width = (pctTarget * eased).toFixed(1) + '%';
            if (progress < 1) {
                requestAnimationFrame(tick);
            } else {
                // Snap to final values and restore transition
                if (valEl) valEl.textContent = Math.round(rawTarget) + '%';
                if (fillEl) {
                    fillEl.style.width = pctTarget.toFixed(1) + '%';
                    fillEl.style.transition = '';
                }
            }
        }
        // Reset to 0 first
        if (valEl) valEl.textContent = '0%';
        if (fillEl) fillEl.style.width = '0%';
        requestAnimationFrame(tick);
    }, delay);
}

const RING_DEFS = [
    { key: 'emotional-stability', r: 120 },
    { key: 'wellbeing',           r: 105 },
    { key: 'calm',                r: 90  },
    { key: 'activation',          r: 75  },
    { key: 'anxiety',             r: 60  },
    { key: 'stress',              r: 45  },
];

function startRingGaugeProgress() {
    if (_ringAnalyzing) return;
    _ringAnalyzing = true;

    startMetricBarPulse();

    // Remove reveal overlay if present (analysis started before user tapped Reveal)
    const card = document.getElementById('ring-gauge-svg')?.parentElement;
    card?.querySelector('.ring-reveal-overlay')?.remove();

    const svg = document.getElementById('ring-gauge-svg');
    if (!svg) return;

    renderRingGaugeAnalyzing();

    _ringProgressStart = performance.now();

    // Safety timeout: 30s max
    _ringSafetyTimer = setTimeout(() => {
        if (_ringAnalyzing) finishRingGaugeProgress();
    }, 30000);

    function tick(now) {
        if (!_ringAnalyzing) return;
        const elapsed = now - _ringProgressStart;
        let progress;
        if (elapsed < 8000) {
            progress = (elapsed / 8000) * 0.80;
        } else {
            progress = 0.80 + Math.min((elapsed - 8000) / 22000, 1) * 0.15;
        }
        updateRingGaugeProgress(progress);
        _ringProgressRAF = requestAnimationFrame(tick);
    }

    _ringProgressRAF = requestAnimationFrame(tick);
}

function renderRingGaugeAnalyzing() {
    const svg = document.getElementById('ring-gauge-svg');
    if (!svg) return;
    svg.innerHTML = '';

    const cx = 150, cy = 150;
    const opacities = [1, 0.88, 0.76, 0.62, 0.48, 0.38];
    const accentVars = ['--ring-accent-1','--ring-accent-2','--ring-accent-3',
                        '--ring-accent-4','--ring-accent-5','--ring-accent-6'];
    const style = getComputedStyle(document.documentElement);
    const trackColor = style.getPropertyValue('--ring-track').trim() || '#1a2028';

    // SVG defs: glow filter
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    const filt = document.createElementNS('http://www.w3.org/2000/svg', 'filter');
    filt.setAttribute('id', 'rg-glow');
    filt.setAttribute('x', '-30%'); filt.setAttribute('y', '-30%');
    filt.setAttribute('width', '160%'); filt.setAttribute('height', '160%');
    const fblur = document.createElementNS('http://www.w3.org/2000/svg', 'feGaussianBlur');
    fblur.setAttribute('stdDeviation', '2'); fblur.setAttribute('result', 'blur');
    filt.appendChild(fblur);
    const fmerge = document.createElementNS('http://www.w3.org/2000/svg', 'feMerge');
    ['blur','SourceGraphic'].forEach(src => {
        const mn = document.createElementNS('http://www.w3.org/2000/svg', 'feMergeNode');
        mn.setAttribute('in', src); fmerge.appendChild(mn);
    });
    filt.appendChild(fmerge);
    defs.appendChild(filt);
    svg.appendChild(defs);

    // Track rings
    RING_DEFS.forEach(({ r }) => {
        const track = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        track.setAttribute('cx', cx); track.setAttribute('cy', cy);
        track.setAttribute('r', r); track.setAttribute('fill', 'none');
        track.setAttribute('stroke', trackColor); track.setAttribute('stroke-width', '5.5');
        svg.appendChild(track);
    });

    // Progress arcs (start at 0%)
    RING_DEFS.forEach(({ r }, i) => {
        const circumference = 2 * Math.PI * r;
        const accentColor = style.getPropertyValue(accentVars[i]).trim() || '#a8c0d0';

        const arc = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        arc.setAttribute('cx', cx); arc.setAttribute('cy', cy);
        arc.setAttribute('r', r); arc.setAttribute('fill', 'none');
        arc.setAttribute('stroke', accentColor);
        arc.setAttribute('stroke-width', '5.5');
        arc.setAttribute('stroke-linecap', 'round');
        arc.setAttribute('stroke-dasharray', circumference.toFixed(2));
        arc.setAttribute('stroke-dashoffset', circumference.toFixed(2)); // 0% filled
        arc.setAttribute('transform', `rotate(-90 ${cx} ${cy})`);
        arc.setAttribute('opacity', opacities[i]);
        arc.setAttribute('filter', 'url(#rg-glow)');
        arc.classList.add('ring-progress-arc');
        svg.appendChild(arc);
    });

    // Center: "Analyzing" text with pulse
    const line1 = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    line1.setAttribute('x', cx); line1.setAttribute('y', cy + 4);
    line1.setAttribute('text-anchor', 'middle');
    line1.setAttribute('font-family', 'Playfair Display, Georgia, serif');
    line1.setAttribute('font-size', '22');
    line1.setAttribute('font-weight', '600');
    line1.setAttribute('fill', style.getPropertyValue('--ring-accent-1').trim() || '#c4d8e8');
    line1.classList.add('analyzing-text');
    line1.textContent = 'Analyzing';
    svg.appendChild(line1);

    const line2 = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    line2.setAttribute('x', cx); line2.setAttribute('y', cy + 28);
    line2.setAttribute('text-anchor', 'middle');
    line2.setAttribute('font-family', 'Inter, sans-serif');
    line2.setAttribute('font-size', '12');
    line2.setAttribute('font-weight', '500');
    line2.setAttribute('letter-spacing', '3');
    line2.setAttribute('fill', style.getPropertyValue('--ring-accent-3').trim() || '#a8c0d0');
    line2.setAttribute('opacity', '0.7');
    line2.classList.add('analyzing-text');
    line2.textContent = 'VOICE';
    svg.appendChild(line2);
}

function updateRingGaugeProgress(progress) {
    const svg = document.getElementById('ring-gauge-svg');
    if (!svg) return;

    const arcs = svg.querySelectorAll('.ring-progress-arc');
    arcs.forEach((arc, i) => {
        const r = RING_DEFS[i].r;
        const circumference = 2 * Math.PI * r;
        const offset = circumference * (1 - progress);
        arc.setAttribute('stroke-dashoffset', offset.toFixed(2));
    });
}

function finishRingGaugeProgress() {
    if (!_ringAnalyzing) return;
    _ringAnalyzing = false;

    if (_ringProgressRAF) {
        cancelAnimationFrame(_ringProgressRAF);
        _ringProgressRAF = null;
    }
    if (_ringSafetyTimer) {
        clearTimeout(_ringSafetyTimer);
        _ringSafetyTimer = null;
    }

    // Snap all rings to 100%
    updateRingGaugeProgress(1.0);

    // Set reveal flags — consumed by renderRingGauge() and updateMetricBars()
    _ringScoreReveal = true;
    _metBarReveal = true;
    window.AppState.canopyRevealed = true;  // Skip tap-to-reveal card after analysis
    stopMetricBarPulse();

    // After brief pause, loadTodayData() will call renderRingGauge() with real data
}

// ============ Ring Gauge ============

let _gaugeState = { canopy: null, scores: {} };

function _renderRevealCard(canopyScore, scores, delta) {
    const svg = document.getElementById('ring-gauge-svg');
    if (!svg) return;
    svg.innerHTML = '';

    // Render empty track rings (no arcs, no score) as a teaser background
    const cx = 150, cy = 150;
    const style = getComputedStyle(document.documentElement);
    const trackColor = style.getPropertyValue('--ring-track').trim() || '#1a2028';

    RING_DEFS.forEach(({ r }) => {
        const track = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        track.setAttribute('cx', cx); track.setAttribute('cy', cy);
        track.setAttribute('r', r); track.setAttribute('fill', 'none');
        track.setAttribute('stroke', trackColor); track.setAttribute('stroke-width', '5.5');
        svg.appendChild(track);
    });

    // Remove any existing overlay
    const card = svg.parentElement;
    card.querySelector('.ring-reveal-overlay')?.remove();

    // Create overlay
    const overlay = document.createElement('div');
    overlay.className = 'ring-reveal-overlay';
    overlay.innerHTML = `
        <div class="ring-reveal-text">Your Health Score<br>is ready</div>
        <button class="ring-reveal-btn">Reveal</button>
    `;

    // Click handler: trigger animation
    overlay.addEventListener('click', () => {
        overlay.style.opacity = '0';
        setTimeout(() => {
            overlay.remove();
            _ringScoreReveal = true;
            _metBarReveal = true;
            window.AppState.canopyRevealed = true;
            localStorage.setItem('attune-last-revealed-count', String(window.AppState.currentReadingCount || 0));
            renderRingGauge(canopyScore, scores, delta);
            updateMetricBars(_gaugeState.scores);
        }, 300);
    });

    card.appendChild(overlay);
}

function renderRingGauge(canopyScore, scores, delta) {
    _gaugeState = { canopy: canopyScore, scores: scores || {}, delta: delta };

    const svg = document.getElementById('ring-gauge-svg');
    if (!svg) return;

    // Capture and consume reveal flag
    const isReveal = _ringScoreReveal;
    if (!canopyScore && canopyScore !== 0) _ringScoreReveal = false;
    if (isReveal) _ringScoreReveal = false;

    // Tap-to-reveal: show overlay only when new readings arrive
    const showScoreEarly = canopyScore !== null && canopyScore !== undefined;
    if (showScoreEarly && !window.AppState.canopyRevealed && !isReveal) {
        const currentCount = window.AppState.currentReadingCount || 0;
        const lastRevealed = parseInt(localStorage.getItem('attune-last-revealed-count') || '0', 10);
        if (currentCount > lastRevealed) {
            _renderRevealCard(canopyScore, scores, delta);
            return;
        } else {
            // No new readings — skip overlay, go straight to display
            window.AppState.canopyRevealed = true;
        }
    }

    svg.innerHTML = '';

    const cx = 150, cy = 150;
    const rings = [
        { key: 'emotional-stability', r: 120, invert: false },
        { key: 'wellbeing',           r: 105, invert: false },
        { key: 'calm',                r: 90,  invert: false },
        { key: 'activation',          r: 75,  invert: false },
        { key: 'anxiety',             r: 60,  invert: true  },
        { key: 'stress',              r: 45,  invert: true  },
    ];
    const opacities = [1, 0.88, 0.76, 0.62, 0.48, 0.38];
    const accentVars = ['--ring-accent-1','--ring-accent-2','--ring-accent-3',
                        '--ring-accent-4','--ring-accent-5','--ring-accent-6'];

    const style = getComputedStyle(document.documentElement);
    const trackColor = style.getPropertyValue('--ring-track').trim() || '#1a2028';

    // SVG defs: glow filter
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    const filt = document.createElementNS('http://www.w3.org/2000/svg', 'filter');
    filt.setAttribute('id', 'rg-glow');
    filt.setAttribute('x', '-30%'); filt.setAttribute('y', '-30%');
    filt.setAttribute('width', '160%'); filt.setAttribute('height', '160%');
    const fblur = document.createElementNS('http://www.w3.org/2000/svg', 'feGaussianBlur');
    fblur.setAttribute('stdDeviation', '2'); fblur.setAttribute('result', 'blur');
    filt.appendChild(fblur);
    const fmerge = document.createElementNS('http://www.w3.org/2000/svg', 'feMerge');
    ['blur','SourceGraphic'].forEach(src => {
        const mn = document.createElementNS('http://www.w3.org/2000/svg', 'feMergeNode');
        mn.setAttribute('in', src); fmerge.appendChild(mn);
    });
    filt.appendChild(fmerge);
    defs.appendChild(filt);
    svg.appendChild(defs);

    // Track rings
    rings.forEach(({ r }) => {
        const track = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        track.setAttribute('cx', cx); track.setAttribute('cy', cy);
        track.setAttribute('r', r); track.setAttribute('fill', 'none');
        track.setAttribute('stroke', trackColor); track.setAttribute('stroke-width', '5.5');
        svg.appendChild(track);
    });

    // Progress arcs
    const arcElements = [];
    rings.forEach(({ key, r, invert }, i) => {
        const raw = scores[key] ?? (key === 'emotional-stability' ? (scores.emotional_stability ?? 50) : 50);
        const val = Math.max(0, Math.min(100, raw));
        const pct = invert ? (100 - val) / 100 : val / 100;
        const circumference = 2 * Math.PI * r;
        const accentColor = style.getPropertyValue(accentVars[i]).trim() || '#a8c0d0';

        const arc = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        arc.setAttribute('cx', cx); arc.setAttribute('cy', cy);
        arc.setAttribute('r', r); arc.setAttribute('fill', 'none');
        arc.setAttribute('stroke', accentColor);
        arc.setAttribute('stroke-width', '5.5');
        arc.setAttribute('stroke-linecap', 'round');
        arc.setAttribute('stroke-dasharray', circumference.toFixed(2));
        // Start at 0% if reveal, otherwise snap to final
        arc.setAttribute('stroke-dashoffset', isReveal
            ? circumference.toFixed(2)
            : (circumference * (1 - pct)).toFixed(2));
        arc.setAttribute('transform', `rotate(-90 ${cx} ${cy})`);
        arc.setAttribute('opacity', opacities[i]);
        arc.setAttribute('filter', 'url(#rg-glow)');
        svg.appendChild(arc);
        arcElements.push({ arc, circumference, pct });
    });

    // Center: canopy score
    const showScore = canopyScore !== null && canopyScore !== undefined;
    const finalScore = showScore ? Math.round(canopyScore) : null;
    const scoreStr = showScore ? (isReveal ? '0' : finalScore.toString()) : '--';

    const scoreEl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    scoreEl.setAttribute('x', cx); scoreEl.setAttribute('y', cy + 18);
    scoreEl.setAttribute('text-anchor', 'middle');
    scoreEl.setAttribute('font-family', 'Playfair Display, Georgia, serif');
    scoreEl.setAttribute('font-size', '58');
    scoreEl.setAttribute('font-weight', '600');
    scoreEl.setAttribute('fill', style.getPropertyValue('--ring-accent-1').trim() || '#c4d8e8');
    scoreEl.textContent = scoreStr;
    svg.appendChild(scoreEl);

    // Center: tier label
    const tierEl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    tierEl.setAttribute('x', cx); tierEl.setAttribute('y', cy + 36);
    tierEl.setAttribute('text-anchor', 'middle');
    tierEl.setAttribute('font-family', 'Inter, sans-serif');
    tierEl.setAttribute('font-size', '10');
    tierEl.setAttribute('font-weight', '500');
    tierEl.setAttribute('letter-spacing', '3');
    tierEl.setAttribute('fill', style.getPropertyValue('--ring-accent-3').trim() || '#a8c0d0');
    tierEl.setAttribute('opacity', '0.6');
    if (showScore) {
        const tier = canopyScore >= 80 ? 'EXCELLENT' : canopyScore >= 65 ? 'GOOD' :
                     canopyScore >= 50 ? 'FAIR' : canopyScore >= 35 ? 'LOW' : 'VERY LOW';
        tierEl.textContent = tier;
    }
    svg.appendChild(tierEl);

    // Trend delta (only when baseline differs from current)
    if (showScore && delta !== null && delta !== undefined && delta !== 0) {
        const arrow = delta > 0 ? '\u2191' : '\u2193';
        const sign = delta > 0 ? '+' : '';
        const baselineTime = window.AppState && window.AppState.morningBaselineTime
            ? _formatBaselineTime(window.AppState.morningBaselineTime) : '';
        const deltaText = `${arrow} ${sign}${Math.round(delta)}${baselineTime ? ' from ' + baselineTime : ''}`;

        const deltaEl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        deltaEl.setAttribute('x', cx);
        deltaEl.setAttribute('y', cy + 50);
        deltaEl.setAttribute('text-anchor', 'middle');
        deltaEl.setAttribute('font-family', 'Inter, sans-serif');
        deltaEl.setAttribute('font-size', '9');
        deltaEl.setAttribute('font-weight', '400');
        deltaEl.setAttribute('fill', delta > 0 ? '#5a9a6e' : '#c4584c');
        deltaEl.setAttribute('opacity', '0.7');
        deltaEl.textContent = deltaText;
        svg.appendChild(deltaEl);
    }

    // ---- Reveal animations (RAF) ----
    if (isReveal && showScore) {
        const arcDuration = 2000;   // 2s for ring arcs
        const scoreDuration = 2500; // 2.5s for score count-up
        const startTime = performance.now();

        function revealTick(now) {
            const elapsed = now - startTime;

            // Animate ring arcs (0% → final pct, 2s, ease-out cubic)
            const arcProgress = Math.min(elapsed / arcDuration, 1);
            const arcEased = 1 - Math.pow(1 - arcProgress, 3);
            arcElements.forEach(({ arc, circumference, pct }) => {
                const currentPct = pct * arcEased;
                arc.setAttribute('stroke-dashoffset', (circumference * (1 - currentPct)).toFixed(2));
            });

            // Animate score count-up (0 → finalScore, 2.5s, ease-out cubic)
            const scoreProgress = Math.min(elapsed / scoreDuration, 1);
            const scoreEased = 1 - Math.pow(1 - scoreProgress, 3);
            scoreEl.textContent = Math.round(finalScore * scoreEased).toString();

            if (arcProgress < 1 || scoreProgress < 1) {
                requestAnimationFrame(revealTick);
            } else {
                // Snap to final values
                arcElements.forEach(({ arc, circumference, pct }) => {
                    arc.setAttribute('stroke-dashoffset', (circumference * (1 - pct)).toFixed(2));
                });
                scoreEl.textContent = finalScore.toString();
            }
        }
        requestAnimationFrame(revealTick);
    }
}

function _formatBaselineTime(date) {
    if (!date) return '';
    let h = date.getHours();
    const ampm = h >= 12 ? 'pm' : 'am';
    h = h % 12 || 12;
    return h + ampm;
}

// ============ Metric Bars ============

function updateMetricBars(scores) {
    const bars = [
        { id: 'stability',  key: 'emotional-stability', altKey: 'emotional_stability', invert: false },
        { id: 'wellbeing',  key: 'wellbeing',            altKey: null,                  invert: false },
        { id: 'calmness',   key: 'calm',                 altKey: null,                  invert: false },
        { id: 'activation', key: 'activation',           altKey: null,                  invert: false },
        { id: 'anxiety',    key: 'anxiety',              altKey: null,                  invert: true  },
        { id: 'stress',     key: 'stress',               altKey: null,                  invert: true  },
    ];

    // Check and consume reveal flag
    const isReveal = _metBarReveal;
    if (isReveal) _metBarReveal = false;

    bars.forEach(({ id, key, altKey, invert }, i) => {
        const raw = Math.max(0, Math.min(100, scores[key] ?? (altKey ? scores[altKey] : null) ?? 50));
        const pct = invert ? (100 - raw) : raw;
        const valEl  = document.getElementById(`metbar-val-${id}`);
        const fillEl = document.getElementById(`metbar-fill-${id}`);

        if (isReveal) {
            // Staggered count-up animation: 1.5s each, 100ms stagger
            animateMetricBar(valEl, fillEl, raw, pct, 1500, i * 100);
        } else {
            // Normal snap
            if (valEl)  valEl.textContent = Math.round(raw) + '%';
            if (fillEl) fillEl.style.width = pct.toFixed(1) + '%';
        }
    });
}

// ============ Theme Toggle ============

function initThemeToggle() {
    const saved = localStorage.getItem('attune-theme') || 'day';
    document.documentElement.dataset.theme = saved;
    updateThemeIcon(saved);

    const btn = document.getElementById('theme-toggle-btn');
    if (!btn) return;
    btn.addEventListener('click', () => {
        const next = document.documentElement.dataset.theme === 'night' ? 'day' : 'night';
        document.documentElement.dataset.theme = next;
        localStorage.setItem('attune-theme', next);
        updateThemeIcon(next);
        // Re-render ring gauge for new theme colors
        renderRingGauge(_gaugeState.canopy, _gaugeState.scores, _gaugeState.delta);
    });
}

function updateThemeIcon(theme) {
    const icon = document.getElementById('theme-toggle-icon');
    if (!icon) return;
    if (theme === 'day') {
        // Day mode: show moon icon (click to switch to night)
        icon.innerHTML = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>';
    } else {
        // Night mode: show sun icon (click to switch to day)
        icon.innerHTML = '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>';
    }
}

// ============ Metric Detail Popups ============

const METRIC_DETAILS = {
    wellbeing: {
        title: 'Emotional Wellbeing',
        description: 'Composite measure of emotional health combining low distress, vocal engagement, and speech vitality. Higher scores indicate more positive emotional state with animated, fluid speech.',
        polarity: 'positive',
        tiers: [
            { label: 'Very Low',  range: '0 \u2013 20',  color: '#c4584c' },
            { label: 'Low',       range: '21 \u2013 40', color: '#c47840' },
            { label: 'Moderate',  range: '41 \u2013 60', color: '#8a9eaa' },
            { label: 'Good',      range: '61 \u2013 80', color: '#7aad6e' },
            { label: 'Excellent', range: '81 \u2013 100', color: '#5a9a6e' },
        ],
        note: 'Projected validity: 72/100. Replaces Mood with improved multi-component formula.',
        getTier: function(v) {
            if (v <= 20) return 0;
            if (v <= 40) return 1;
            if (v <= 60) return 2;
            if (v <= 80) return 3;
            return 4;
        }
    },
    calm: {
        title: 'Calmness',
        description: 'Measures vocal indicators of relaxation and composure. Derived from pitch stability, speech rate, and spectral smoothness. Higher scores indicate a calmer, more composed vocal state.',
        polarity: 'positive',
        tiers: [
            { label: 'Very Low',  range: '0 \u2013 20',  color: '#c4584c' },
            { label: 'Low',       range: '21 \u2013 40', color: '#c47840' },
            { label: 'Moderate',  range: '41 \u2013 60', color: '#8a9eaa' },
            { label: 'Good',      range: '61 \u2013 80', color: '#7aad6e' },
            { label: 'Excellent', range: '81 \u2013 100', color: '#5a9a6e' },
        ],
        note: 'Average calmness during relaxed conversation is typically 55\u201370.',
        getTier: function(v) {
            if (v <= 20) return 0;
            if (v <= 40) return 1;
            if (v <= 60) return 2;
            if (v <= 80) return 3;
            return 4;
        }
    },
    activation: {
        title: 'Activation',
        description: 'Measures vocal arousal and dynamism. Based on loudness, pitch height, pitch range, speech rate, and spectral brightness. Higher scores indicate more animated, energetic speech.',
        polarity: 'positive',
        tiers: [
            { label: 'Very Low',  range: '0 \u2013 20',  color: '#c4584c' },
            { label: 'Low',       range: '21 \u2013 40', color: '#c47840' },
            { label: 'Moderate',  range: '41 \u2013 60', color: '#8a9eaa' },
            { label: 'Good',      range: '61 \u2013 80', color: '#7aad6e' },
            { label: 'Excellent', range: '81 \u2013 100', color: '#5a9a6e' },
        ],
        note: 'Replaces Energy with improved validity (70/100 vs 42/100). Typical range: 40\u201370.',
        getTier: function(v) {
            if (v <= 20) return 0;
            if (v <= 40) return 1;
            if (v <= 60) return 2;
            if (v <= 80) return 3;
            return 4;
        }
    },
    stress: {
        title: 'Stress',
        description: 'Detects vocal tension from pitch variability, jitter, shimmer, and speech irregularities. Lower scores are better \u2014 they indicate relaxed, fluid speech patterns.',
        polarity: 'negative',
        tiers: [
            { label: 'Very Low',  range: '0 \u2013 20',  color: '#5a9a6e' },
            { label: 'Low',       range: '21 \u2013 40', color: '#7aad6e' },
            { label: 'Moderate',  range: '41 \u2013 60', color: '#8a9eaa' },
            { label: 'High',      range: '61 \u2013 80', color: '#c47840' },
            { label: 'Very High', range: '81 \u2013 100', color: '#c4584c' },
        ],
        note: 'Some stress is normal. Sustained scores above 60 may indicate chronic tension.',
        getTier: function(v) {
            if (v <= 20) return 0;
            if (v <= 40) return 1;
            if (v <= 60) return 2;
            if (v <= 80) return 3;
            return 4;
        }
    },
    depression: {
        title: 'Depression',
        description: 'Mapped from Kintsugi\u2019s DAM model (PHQ-9 scale, 0\u201327, normalized to 0\u2013100). Analyzes vocal biomarkers associated with depressive symptoms: reduced pitch range, slower speech, and flatter prosody.',
        polarity: 'negative',
        tiers: [
            { label: 'Minimal',  range: '0 \u2013 18',  color: '#5a9a6e' },
            { label: 'Mild',     range: '19 \u2013 33', color: '#8a9eaa' },
            { label: 'Moderate', range: '34 \u2013 52', color: '#c47840' },
            { label: 'Severe',   range: '53 \u2013 100', color: '#c4584c' },
        ],
        note: 'This is a wellness indicator, not a clinical diagnosis. Consult a healthcare provider for concerns.',
        getTier: function(v) {
            if (v <= 18) return 0;
            if (v <= 33) return 1;
            if (v <= 52) return 2;
            return 3;
        }
    },
    anxiety: {
        title: 'Anxiety',
        description: 'Mapped from Kintsugi\u2019s DAM model (GAD-7 scale, 0\u201321, normalized to 0\u2013100). Detects vocal markers of anxiety: increased speech rate, pitch instability, and micro-hesitations.',
        polarity: 'negative',
        tiers: [
            { label: 'Minimal',  range: '0 \u2013 23',  color: '#5a9a6e' },
            { label: 'Mild',     range: '24 \u2013 47', color: '#8a9eaa' },
            { label: 'Moderate', range: '48 \u2013 71', color: '#c47840' },
            { label: 'Severe',   range: '72 \u2013 100', color: '#c4584c' },
        ],
        note: 'This is a wellness indicator, not a clinical diagnosis. Consult a healthcare provider for concerns.',
        getTier: function(v) {
            if (v <= 23) return 0;
            if (v <= 47) return 1;
            if (v <= 71) return 2;
            return 3;
        }
    },
    'emotional-stability': {
        title: 'Emotional Stability',
        description: 'Measures consistency of your emotional state over time. Computed from rolling variability of core scores and acoustic coefficient of variation. Higher scores indicate steadier emotional patterns.',
        polarity: 'positive',
        tiers: [
            { label: 'Volatile',  range: '0 \u2013 25',  color: '#c4584c' },
            { label: 'Variable',  range: '26 \u2013 50', color: '#c47840' },
            { label: 'Steady',    range: '51 \u2013 75', color: '#8a9eaa' },
            { label: 'Stable',    range: '76 \u2013 100', color: '#5a9a6e' },
        ],
        note: 'Projected validity: 62/100. Requires 3+ recent readings for full accuracy.',
        getTier: function(v) {
            if (v <= 25) return 0;
            if (v <= 50) return 1;
            if (v <= 75) return 2;
            return 3;
        }
    }
};

function openMetricDetail(metric) {
    const details = METRIC_DETAILS[metric];
    if (!details) return;

    const modal = document.getElementById('metric-detail-modal');
    const titleEl = document.getElementById('metric-detail-title');
    const descEl = document.getElementById('metric-detail-description');
    const currentEl = document.getElementById('metric-detail-current');
    const tiersEl = document.getElementById('metric-detail-tiers');
    const noteEl = document.getElementById('metric-detail-note');

    // Get current score value
    const valueEl = document.getElementById(`circle-${metric}-value`);
    const currentValue = valueEl ? parseInt(valueEl.textContent) : null;

    titleEl.textContent = details.title;
    descEl.textContent = details.description;

    // Current score display
    if (currentValue !== null && !isNaN(currentValue)) {
        const tierIdx = details.getTier(currentValue);
        const tier = details.tiers[tierIdx];
        const color = getScoreColor(metric, currentValue);
        currentEl.innerHTML = `<span class="metric-detail-current-score" style="color: ${color}">${currentValue}</span>` +
            `<span class="metric-detail-current-tier" style="color: ${tier.color}">${tier.label}</span>`;
        currentEl.style.display = 'flex';
    } else {
        currentEl.innerHTML = '<span style="color: var(--text-muted); font-size: 14px;">No data yet</span>';
        currentEl.style.display = 'flex';
    }

    // Tier rows
    const activeTierIdx = (currentValue !== null && !isNaN(currentValue)) ? details.getTier(currentValue) : -1;
    let tiersHtml = '';
    details.tiers.forEach((tier, idx) => {
        const isActive = idx === activeTierIdx;
        tiersHtml += `<div class="metric-tier-row${isActive ? ' active' : ''}">` +
            `<span class="metric-tier-dot" style="background: ${tier.color}"></span>` +
            `<span class="metric-tier-label">${tier.label}</span>` +
            `<span class="metric-tier-range">${tier.range}</span>` +
            `</div>`;
    });
    tiersEl.innerHTML = tiersHtml;

    // Note
    noteEl.textContent = details.note;

    modal.style.display = 'flex';
}

function closeMetricDetail() {
    const modal = document.getElementById('metric-detail-modal');
    if (modal) modal.style.display = 'none';
}

// Wire up click handlers on DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
    // Initialize theme toggle + ring gauge
    initThemeToggle();
    renderRingGauge(null, {});

    const metrics = ['wellbeing', 'calm', 'activation', 'stress', 'depression', 'anxiety', 'emotional-stability'];
    metrics.forEach(metric => {
        const el = document.getElementById(`circle-${metric}`);
        if (el) {
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                openMetricDetail(metric);
            });
        }
    });

    // Close modal handlers
    const modal = document.getElementById('metric-detail-modal');
    if (modal) {
        const backdrop = modal.querySelector('.metric-detail-backdrop');
        const closeBtn = modal.querySelector('.metric-detail-close');
        if (backdrop) backdrop.addEventListener('click', closeMetricDetail);
        if (closeBtn) closeBtn.addEventListener('click', closeMetricDetail);
    }

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeMetricDetail();
    });
});

// ============ Hero Wellness Score ============

function updateHeroWellness(score) {
    const el = document.getElementById('wellness-score');
    if (el) {
        el.textContent = Math.round(Math.max(0, Math.min(100, score)));
    }
}

function updateWellnessMessage(readings, scores, calibration) {
    const el = document.getElementById('wellness-message');
    if (!el) return;

    if (!calibration || !calibration.is_calibrated) {
        el.textContent = 'Building your personal baseline...';
        return;
    }

    if (!readings || readings.length === 0) {
        el.textContent = 'Listening for speech...';
        return;
    }

    const zone = readings[0].zone || 'steady';
    const mood = scores.mood || 50;

    if (zone === 'stressed') {
        el.textContent = 'Stress levels elevated. Consider a break.';
    } else if (zone === 'tense') {
        el.textContent = 'Signs of tension detected.';
    } else if (zone === 'calm' && mood > 60) {
        el.textContent = 'You\'re in a great state. Keep going!';
    } else if (zone === 'calm') {
        el.textContent = 'Calm and focused.';
    } else {
        el.textContent = mood > 60 ? 'Steady and balanced.' : 'Holding steady.';
    }
}

// ============ Zone Bar (Labeled segments with time ranges + NOW marker) ============

function updateZoneBar(readings) {
    const container = document.getElementById('zone-bar');
    if (!container) return;

    if (!readings || readings.length === 0) {
        container.innerHTML = '<div class="zone-bar-empty">The Zone Bar shows how your emotional state shifts throughout the day \u2014 calm, steady, tense, or stressed. It will fill in as readings arrive.</div>';
        return;
    }

    // Build zone segments from readings (oldest to newest)
    const sorted = [...readings].reverse();
    const segments = [];
    let currentZone = null;
    let currentCount = 0;
    let segmentStartTime = null;
    let segmentEndTime = null;

    for (const r of sorted) {
        const zone = r.zone || 'steady';
        const ts = r.timestamp;
        if (zone === currentZone) {
            currentCount++;
            segmentEndTime = ts;
        } else {
            if (currentZone) {
                segments.push({ zone: currentZone, count: currentCount, startTime: segmentStartTime, endTime: segmentEndTime });
            }
            currentZone = zone;
            currentCount = 1;
            segmentStartTime = ts;
            segmentEndTime = ts;
        }
    }
    if (currentZone) {
        segments.push({ zone: currentZone, count: currentCount, startTime: segmentStartTime, endTime: segmentEndTime });
    }

    const total = segments.reduce((sum, s) => sum + s.count, 0);

    const zoneLabels = { calm: 'Calm Zone', steady: 'Steady Zone', tense: 'Tense Zone', stressed: 'Stressed Zone' };

    let html = '';
    for (const seg of segments) {
        const pct = (seg.count / total) * 100;
        const startStr = formatTime(seg.startTime);
        const endStr = formatTime(seg.endTime);
        const timeRange = startStr && endStr ? `${startStr} - ${endStr}` : '';
        const label = zoneLabels[seg.zone] || seg.zone;

        html += `<div class="zone-segment ${seg.zone}" style="width: ${pct}%;" title="${label}: ${seg.count} readings">`;
        if (pct > 12) {
            html += `<span class="zone-segment-label">${label}</span>`;
            if (timeRange) html += `<span class="zone-segment-time">${timeRange}</span>`;
        }
        html += '</div>';
    }

    // NOW marker pill at the right edge
    const now = new Date();
    const nowStr = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
    html += `<div class="zone-now-marker" style="right: 0;">`;
    html += `<div class="zone-now-pill">`;
    html += `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`;
    html += `NOW</div>`;
    html += `<div class="zone-now-line"></div>`;
    html += `</div>`;

    container.innerHTML = html;
}

function formatTime(ts) {
    if (!ts) return '';
    const d = new Date(ts);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
}

// ============ Heatmap Calendar (with day-of-week headers) ============
// Now used in history view via correlation.js

function updateHeatmapCalendar(summaries, containerIdOverride) {
    const container = document.getElementById(containerIdOverride || 'heatmap-calendar');
    if (!container) return;

    // Build day-of-week headers
    const headersContainer = document.getElementById(
        containerIdOverride ? 'history-heatmap-day-headers' : 'heatmap-day-headers'
    );
    if (headersContainer) {
        const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
        headersContainer.innerHTML = days.map(d => `<span class="heatmap-day-header">${d}</span>`).join('');
    }

    const today = new Date();
    today.setHours(0, 0, 0, 0);

    // Build a map of date -> wellness score from summaries
    const scoreMap = {};
    if (summaries && summaries.length > 0) {
        for (const s of summaries) {
            const wellbeing = s.avg_wellbeing || s.avg_mood || 50;
            const calm = s.avg_calm || 50;
            const activation = s.avg_activation || s.avg_energy || 50;
            const stress = s.avg_stress || 50;
            const wellness = (wellbeing + calm + activation + (100 - stress)) / 4;
            scoreMap[s.date] = wellness;
        }
    }

    // Generate 28 cells (4 weeks) ending this week
    const start = new Date(today);
    const todayDay = start.getDay();
    const mondayOffset = todayDay === 0 ? -6 : 1 - todayDay;
    start.setDate(start.getDate() + mondayOffset);
    start.setDate(start.getDate() - 21);

    const cells = [];
    for (let i = 0; i < 28; i++) {
        const d = new Date(start);
        d.setDate(d.getDate() + i);
        const dateStr = d.toISOString().split('T')[0];
        const isFuture = d > today;
        const isToday = d.getTime() === today.getTime();

        let cls = '';
        if (isFuture) {
            cls = 'future';
        } else if (scoreMap[dateStr] !== undefined) {
            const score = scoreMap[dateStr];
            if (score >= 65) cls = 'good';
            else if (score >= 40) cls = 'moderate';
            else cls = 'poor';
        }

        if (isToday) cls += ' today';

        cells.push(`<div class="heatmap-cell ${cls}" title="${dateStr}"></div>`);
    }

    container.innerHTML = cells.join('');
}

// ============ Backward Compat ============

function initGauges() {
    // No-op
}

function updateGauges(scores, zone) {
    const wellbeing = scores.wellbeing ?? scores.mood ?? 50;
    const calm = scores.calm ?? 50;
    const activation = scores.activation ?? scores.energy ?? 50;
    const stress = scores.stress ?? 50;
    const wellness = (wellbeing + calm + activation + (100 - stress)) / 4;
    updateHeroWellness(wellness);
    updateScoreCircles(scores);
}
