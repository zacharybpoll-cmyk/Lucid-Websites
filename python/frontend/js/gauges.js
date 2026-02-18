/**
 * Score circles + hero wellness + zone bar rendering
 * Oura-style translucent circles on forest canopy background
 */

// ============ Score Circles (Oura-style) ============

function updateScoreCircles(scores) {
    updateCircle('calm', scores.calm || 50);
    updateCircle('energy', scores.energy || 50);
    updateCircle('stress', scores.stress || 50);
    updateCircle('depression', scores.depression || 0);
    updateCircle('anxiety', scores.anxiety || 0);
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
    const amber = [181, 168, 74];  // #b5a84a
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

// ============ Metric Detail Popups ============

const METRIC_DETAILS = {
    calm: {
        title: 'Calmness',
        description: 'Measures vocal indicators of relaxation and composure. Derived from pitch stability, speech rate, and spectral smoothness. Higher scores indicate a calmer, more composed vocal state.',
        polarity: 'positive',
        tiers: [
            { label: 'Very Low',  range: '0 \u2013 20',  color: '#c4584c' },
            { label: 'Low',       range: '21 \u2013 40', color: '#d4943a' },
            { label: 'Moderate',  range: '41 \u2013 60', color: '#b5a84a' },
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
    energy: {
        title: 'Energy',
        description: 'Reflects vocal vitality and engagement. Based on speech amplitude variation, articulation rate, and dynamic range. Higher scores suggest more energetic, animated speech.',
        polarity: 'positive',
        tiers: [
            { label: 'Very Low',  range: '0 \u2013 20',  color: '#c4584c' },
            { label: 'Low',       range: '21 \u2013 40', color: '#d4943a' },
            { label: 'Moderate',  range: '41 \u2013 60', color: '#b5a84a' },
            { label: 'Good',      range: '61 \u2013 80', color: '#7aad6e' },
            { label: 'Excellent', range: '81 \u2013 100', color: '#5a9a6e' },
        ],
        note: 'Typical daytime energy scores range from 45\u201365, peaking mid-morning.',
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
            { label: 'Moderate',  range: '41 \u2013 60', color: '#b5a84a' },
            { label: 'High',      range: '61 \u2013 80', color: '#d4943a' },
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
            { label: 'Mild',     range: '19 \u2013 33', color: '#b5a84a' },
            { label: 'Moderate', range: '34 \u2013 52', color: '#d4943a' },
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
            { label: 'Mild',     range: '24 \u2013 47', color: '#b5a84a' },
            { label: 'Moderate', range: '48 \u2013 71', color: '#d4943a' },
            { label: 'Severe',   range: '72 \u2013 100', color: '#c4584c' },
        ],
        note: 'This is a wellness indicator, not a clinical diagnosis. Consult a healthcare provider for concerns.',
        getTier: function(v) {
            if (v <= 23) return 0;
            if (v <= 47) return 1;
            if (v <= 71) return 2;
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
    const metrics = ['calm', 'energy', 'stress', 'depression', 'anxiety'];
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
        container.innerHTML = '<div class="zone-bar-empty">Collecting data...</div>';
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
            const mood = s.avg_mood || 50;
            const calm = s.avg_calm || 50;
            const energy = s.avg_energy || 50;
            const stress = s.avg_stress || 50;
            const wellness = (mood + calm + energy + (100 - stress)) / 4;
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
    const mood = scores.mood || 50;
    const calm = scores.calm || 50;
    const energy = scores.energy || 50;
    const stress = scores.stress || 50;
    const wellness = (mood + calm + energy + (100 - stress)) / 4;
    updateHeroWellness(wellness);
    updateScoreCircles(scores);
}
