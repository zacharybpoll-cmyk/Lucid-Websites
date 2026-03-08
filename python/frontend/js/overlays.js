/* overlays.js — Weekly Wrapped, Morning Summary, Evening Summary overlays
   Extracted from app.js [Q-060]
   Depends on: window.AppState, window.ZONE_HEX, window.sanitizeHTML, window.svgEl, window.API */

(function () {
    'use strict';

    const AppState  = window.AppState;
    const ZONE_HEX  = window.ZONE_HEX;
    const sanitizeHTML = window.sanitizeHTML;
    const svgEl     = window.svgEl;
    const API       = window.API;

    // ========== Weekly Wrapped ==========

    async function loadWeeklyWrapped() {
        try {
            const data = await API.getWeeklyWrapped();
            const card = document.getElementById('weekly-wrapped-card');
            if (!card) return;

            if (!data.has_data) {
                card.style.display = 'none';
                return;
            }

            // Show only on Mondays or if explicitly requested
            const today = new Date();
            const isMonday = today.getDay() === 1;
            // Always show the card if data exists (user can scroll past it)
            card.style.display = 'block';

            const content = card.querySelector('.wrapped-content');
            if (!content) return;

            const trendIcon = data.wellness.trend > 0 ? '\u2191' : data.wellness.trend < 0 ? '\u2193' : '\u2192';
            const trendColor = data.wellness.trend > 0 ? 'var(--calm-color)' : data.wellness.trend < 0 ? 'var(--stressed-color)' : 'var(--gold)';

            let html = `
                <div class="wrapped-summary-line">${sanitizeHTML(data.summary_line)}</div>
                <div class="wrapped-wellness">
                    <span class="wrapped-wellness-score">${data.wellness.avg}</span>
                    <span class="wrapped-wellness-label">Avg Health Score</span>
                    <span class="wrapped-wellness-trend" style="color: ${trendColor}">${trendIcon} ${data.wellness.trend > 0 ? '+' : ''}${data.wellness.trend}</span>
                </div>
                <div class="wrapped-days">
                    <div class="wrapped-day-stat wrapped-best">
                        <span class="wrapped-day-label">Calmest</span>
                        <span class="wrapped-day-name">${sanitizeHTML(data.best_day.label)}</span>
                        <span class="wrapped-day-val">Stress ${data.best_day.stress}</span>
                    </div>
                    <div class="wrapped-day-stat wrapped-worst">
                        <span class="wrapped-day-label">Toughest</span>
                        <span class="wrapped-day-name">${sanitizeHTML(data.worst_day.label)}</span>
                        <span class="wrapped-day-val">Stress ${data.worst_day.stress}</span>
                    </div>
                </div>
                <div class="wrapped-zones">`;

            for (const z of ['calm', 'steady', 'tense', 'stressed']) {
                const info = data.zones[z];
                if (info && info.pct > 0) {
                    html += `<div class="wrapped-zone-bar" style="width: ${info.pct}%; background: ${ZONE_HEX[z]};" title="${z}: ${info.min}m (${info.pct}%)"></div>`;
                }
            }

            html += `</div>
                <div class="wrapped-stats">
                    <span>Rings closed: ${data.rings_closed}/7 days</span>
                    <span>Compass: ${sanitizeHTML(data.compass_direction)}</span>
                </div>`;

            if (data.top_echo) {
                html += `<div class="wrapped-echo">Top insight: "${sanitizeHTML(data.top_echo)}"</div>`;
            }

            content.innerHTML = html;

            // Apply collapsed state from localStorage
            const isCollapsed = localStorage.getItem('wrapped-collapsed') === 'true';
            const toggle = card.querySelector('.wrapped-toggle');
            if (isCollapsed) {
                content.classList.remove('wrapped-expanded');
                if (toggle) toggle.textContent = '\u25BC';
            } else {
                content.classList.add('wrapped-expanded');
                if (toggle) toggle.textContent = '\u25B2';
            }

            // Set up toggle click handler (remove old listener by replacing element)
            if (toggle && !toggle.dataset.bound) {
                toggle.dataset.bound = 'true';
                toggle.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const expanded = content.classList.contains('wrapped-expanded');
                    content.classList.toggle('wrapped-expanded', !expanded);
                    toggle.textContent = expanded ? '\u25BC' : '\u25B2';
                    localStorage.setItem('wrapped-collapsed', expanded ? 'true' : 'false');
                });
            }

            // Click handler for full-screen overlay
            const sectionLabel = card.querySelector('.section-label');
            if (sectionLabel && !sectionLabel.dataset.overlayBound) {
                sectionLabel.dataset.overlayBound = 'true';
                sectionLabel.style.cursor = 'pointer';
                sectionLabel.addEventListener('click', () => showWrappedOverlay(data));
            }
        } catch (e) {
            console.error('Failed to load weekly wrapped:', e);
        }
    }

    // ========== Weekly Wrapped Overlay ==========

    function showWrappedOverlay(data) {
        const overlay = document.getElementById('wrapped-overlay');
        if (!overlay) return;

        // Render day circles
        const circlesEl = document.getElementById('wrapped-day-circles');
        if (circlesEl && data.day_data) {
            circlesEl.innerHTML = data.day_data.map(d => {
                const cls = d.has_data ? 'wrapped-day-circle active' : 'wrapped-day-circle missed';
                return `<div class="${cls}"><span class="wrapped-day-name">${sanitizeHTML(d.day_name)}</span></div>`;
            }).join('');
        }

        // Render stats
        const statsEl = document.getElementById('wrapped-overlay-stats');
        if (statsEl) {
            const deltaSign = (data.stress_delta || 0) > 0 ? '+' : '';
            statsEl.innerHTML = `
                <div class="wrapped-stat-item">
                    <span class="wrapped-stat-value">${sanitizeHTML(data.best_day ? data.best_day.label : '--')}</span>
                    <span class="wrapped-stat-label">Calmest Day</span>
                </div>
                <div class="wrapped-stat-item">
                    <span class="wrapped-stat-value">${Math.round(data.metrics ? data.metrics.avg_stress : 0)}</span>
                    <span class="wrapped-stat-label">Avg Stress</span>
                </div>
                <div class="wrapped-stat-item">
                    <span class="wrapped-stat-value">${deltaSign}${Math.round(data.stress_delta || 0)}</span>
                    <span class="wrapped-stat-label">vs Last Week</span>
                </div>
            `;
        }

        overlay.style.display = 'flex';
        overlay.offsetHeight;
        overlay.classList.add('visible');
    }

    function dismissWrappedOverlay() {
        const overlay = document.getElementById('wrapped-overlay');
        if (!overlay) return;
        overlay.classList.remove('visible');
        setTimeout(() => { overlay.style.display = 'none'; }, 400);
    }

    // ========== Morning Summary Overlay ==========

    function shouldShowMorningSummary() {
        // Disabled — replaced by Mental Readiness flow via speak-hero
        return false;
    }

    async function loadMorningSummary() {
        if (AppState.morningSummaryShown) return;
        try {
            const data = await API.getMorningSummary();
            if (data.briefing && data.briefing.has_data) {
                renderMorningSummary(data);
            }
        } catch (e) {
            console.error('Failed to load morning summary:', e);
        }
    }

    function renderMorningSummary(data) {
        const overlay = document.getElementById('morning-summary-overlay');
        if (!overlay) return;

        AppState.morningSummaryShown = true;

        // Greeting
        const hour = new Date().getHours();
        let greeting = 'Good morning';
        if (hour >= 12) greeting = 'Good afternoon';
        document.getElementById('morning-greeting').textContent = greeting;

        const briefing = data.briefing;

        // Yesterday's date
        if (briefing.date) {
            const d = new Date(briefing.date + 'T12:00:00');
            document.getElementById('morning-date').textContent =
                'Yesterday \u2014 ' + d.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });
        }

        // Wellness Score (center of rings)
        const wellness = data.wellness;
        const scoreEl = document.getElementById('morning-ring-score');
        const verdictEl = document.getElementById('morning-ring-verdict');

        if (wellness && wellness.has_data) {
            animateMorningScore(scoreEl, wellness.score, 2500);
            let verdict = 'Pay Attention';
            if (wellness.score >= 85) verdict = 'Optimal';
            else if (wellness.score >= 70) verdict = 'Good';
            verdictEl.textContent = verdict;
        } else {
            scoreEl.textContent = '--';
            verdictEl.textContent = '';
        }

        // Extract metric values for rings
        const metricValues = {
            stress: briefing.metrics?.avg_stress ? Math.round(briefing.metrics.avg_stress.value) : 0,
            wellbeing: briefing.metrics?.avg_mood ? Math.round(briefing.metrics.avg_mood.value) : 0,
            activation: briefing.metrics?.avg_energy ? Math.round(briefing.metrics.avg_energy.value) : 0,
            calm: briefing.metrics?.avg_calm ? Math.round(briefing.metrics.avg_calm.value) : 0,
        };

        // Animate concentric rings
        animateMorningRings(metricValues);

        // Update ring legend values
        const legendCalm = document.getElementById('morning-legend-calm');
        const legendWellbeing = document.getElementById('morning-legend-wellbeing');
        const legendActivation = document.getElementById('morning-legend-activation');
        const legendStress = document.getElementById('morning-legend-stress');
        if (legendCalm) legendCalm.textContent = metricValues.calm;
        if (legendWellbeing) legendWellbeing.textContent = metricValues.wellbeing;
        if (legendActivation) legendActivation.textContent = metricValues.activation;
        if (legendStress) legendStress.textContent = metricValues.stress;

        // Metric bars (right column)
        const barsEl = document.getElementById('morning-bars');
        if (barsEl && briefing.metrics) {
            const barConfig = [
                { key: 'avg_stress', label: 'Stress', color: '#c4584c' },
                { key: 'avg_mood', label: 'Wellbeing', color: '#7BA7C9' },
                { key: 'avg_energy', label: 'Activation', color: '#8C96A0' },
                { key: 'avg_calm', label: 'Calm', color: '#5B8DB8' },
            ];
            let barsHtml = '';
            for (const bar of barConfig) {
                const m = briefing.metrics[bar.key];
                if (!m) continue;
                const value = Math.round(m.value);
                const max = m.max || 100;
                barsHtml += `<div class="morning-bar-item">
                    <div class="morning-bar-header">
                        <span class="morning-bar-label">${bar.label}</span>
                        <span class="morning-bar-value">${value}</span>
                    </div>
                    <div class="morning-bar-track">
                        <div class="morning-bar-fill" data-width="${(value / max) * 100}" style="background: ${bar.color};"></div>
                    </div>
                </div>`;
            }
            barsEl.innerHTML = barsHtml;

            // Animate bar fills after DOM insertion
            requestAnimationFrame(() => {
                barsEl.querySelectorAll('.morning-bar-fill').forEach(fill => {
                    fill.style.width = fill.dataset.width + '%';
                });
            });
        }

        // Zone timeline bar
        const timelineBar = document.getElementById('morning-timeline-bar');
        if (timelineBar && briefing.zones) {
            let barHtml = '';
            for (const z of ['calm', 'steady', 'tense', 'stressed']) {
                const info = briefing.zones[z];
                if (!info || info.pct === 0) continue;
                barHtml += `<div style="width: ${info.pct}%; background: ${ZONE_HEX[z]};" title="${z}: ${info.minutes}m (${info.pct}%)"></div>`;
            }
            timelineBar.innerHTML = barHtml;
        }

        // Highlights
        const highlightsList = document.getElementById('morning-highlights-list');
        if (highlightsList && briefing.highlights && briefing.highlights.length > 0) {
            highlightsList.innerHTML = briefing.highlights.map(h => `<li>${sanitizeHTML(h)}</li>`).join('');
        }

        // Coach note
        const coachText = document.getElementById('morning-coach-text');
        if (coachText && briefing.coach_note) {
            coachText.textContent = briefing.coach_note;
        }

        // Voice Weather
        const weatherSection = document.getElementById('morning-weather');
        const weatherContent = document.getElementById('morning-weather-content');
        if (weatherSection && weatherContent && data.voice_weather) {
            const vw = data.voice_weather;
            const color = ZONE_HEX[vw.zone] || ZONE_HEX.idle;
            weatherContent.innerHTML = `
                <span class="morning-weather-zone" style="background: ${color};"></span>
                <span>${vw.zone.charAt(0).toUpperCase() + vw.zone.slice(1)} \u00B7 Stress ${vw.stress}</span>`;
            weatherSection.style.display = 'block';
        }

        // Show overlay
        overlay.style.display = 'flex';
    }

    function animateMorningRings(values) {
        const rings = [
            { id: 'morning-ring-calm', value: values.calm, circumference: 973.9 },
            { id: 'morning-ring-wellbeing', value: values.wellbeing, circumference: 816.8 },
            { id: 'morning-ring-activation', value: values.activation, circumference: 659.7 },
            { id: 'morning-ring-stress', value: values.stress, circumference: 471.2 },
        ];

        rings.forEach((ring, index) => {
            const el = document.getElementById(ring.id);
            if (!el) return;
            const targetOffset = ring.circumference - (ring.value / 100) * ring.circumference;
            // Stagger: each ring animates 200ms after the previous
            setTimeout(() => {
                el.style.strokeDashoffset = targetOffset;
            }, 300 + index * 200);
        });
    }

    function animateMorningScore(el, target, duration) {
        const startTime = performance.now();
        if (el._scoreRAF) cancelAnimationFrame(el._scoreRAF);
        function tick(now) {
            const elapsed = now - startTime;
            const progress = Math.min(elapsed / duration, 1);
            const eased = 1 - Math.pow(1 - progress, 3);
            el.textContent = Math.round(target * eased);
            if (progress < 1) {
                el._scoreRAF = requestAnimationFrame(tick);
            } else {
                el._scoreRAF = null;
                el.textContent = target;
            }
        }
        el._scoreRAF = requestAnimationFrame(tick);
    }

    function dismissMorningSummary() {
        const overlay = document.getElementById('morning-summary-overlay');
        if (!overlay) return;

        overlay.classList.add('fade-out');
        setTimeout(() => {
            overlay.style.display = 'none';
            overlay.classList.remove('fade-out');
        }, 500);

        // Set localStorage flag
        const todayKey = `lucid_morning_seen_${new Date().toISOString().slice(0, 10)}`;
        localStorage.setItem(todayKey, '1');

        // Cleanup old keys (keep last 7 days)
        const now = new Date();
        for (let i = 8; i < 30; i++) {
            const old = new Date(now);
            old.setDate(old.getDate() - i);
            const oldKey = `lucid_morning_seen_${old.toISOString().slice(0, 10)}`;
            localStorage.removeItem(oldKey);
        }
    }

    // ========== Evening Summary Overlay ==========

    function shouldShowEveningSummary() {
        const hour = new Date().getHours();
        if (hour < 20) return false; // Only 8 PM or later

        const todayKey = `lucid_evening_seen_${new Date().toISOString().slice(0, 10)}`;
        if (localStorage.getItem(todayKey)) return false;

        return true;
    }

    async function loadEveningSummary() {
        if (AppState.eveningSummaryShown) return;
        try {
            const data = await API.getEveningSummary();
            if (data.has_data) {
                renderEveningSummary(data);
            }
        } catch (e) {
            console.error('Failed to load evening summary:', e);
        }
    }

    function renderEveningSummary(data) {
        const overlay = document.getElementById('evening-summary-overlay');
        if (!overlay) return;
        AppState.eveningSummaryShown = true;

        // Date header
        const now = new Date();
        document.getElementById('evening-date').textContent =
            now.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });

        // Wellness ring + score
        const wellness = data.wellness;
        const scoreEl = document.getElementById('evening-wellness-score');
        const verdictEl = document.getElementById('evening-wellness-verdict');
        const arcEl = document.getElementById('evening-ring-arc');
        const deltaEl = document.getElementById('evening-wellness-delta');

        if (wellness && wellness.has_data) {
            const score = Math.round(wellness.score);
            animateEveningScore(scoreEl, score, 2000);
            // Animate arc (circumference = 2*pi * 110 ~ 691.2)
            const offset = 691.2 * (1 - score / 100);
            setTimeout(() => { arcEl.style.strokeDashoffset = offset; }, 200);
            // Verdict
            let verdict = 'Needs Attention';
            if (score >= 80) verdict = 'Excellent';
            else if (score >= 65) verdict = 'Good';
            else if (score >= 50) verdict = 'Fair';
            verdictEl.textContent = verdict;
            // Delta vs yesterday
            if (data.wellness_delta != null) {
                deltaEl.style.display = 'block';
                const sign = data.wellness_delta >= 0 ? '+' : '';
                deltaEl.textContent = `${sign}${data.wellness_delta} pts vs yesterday`;
                deltaEl.className = 'evening-wellness-delta ' +
                    (data.wellness_delta > 0 ? 'positive' : data.wellness_delta < 0 ? 'negative' : 'neutral');
            }
        } else {
            scoreEl.textContent = '--';
            verdictEl.textContent = 'Not enough data';
        }

        // Stats row 1
        const calmMin = data.time_in_calm_min || 0;
        const calmH = Math.floor(calmMin / 60);
        const calmM = calmMin % 60;
        document.getElementById('evening-calm-time').textContent =
            calmH > 0 ? `${calmH}h ${calmM}m` : `${calmM}m`;

        const avgStressEl = document.getElementById('evening-avg-stress');
        avgStressEl.textContent = data.avg_stress != null ? data.avg_stress : '--';

        const stressDeltaEl = document.getElementById('evening-stress-delta');
        if (data.stress_delta != null) {
            const sign = data.stress_delta >= 0 ? '+' : '';
            stressDeltaEl.textContent = `${sign}${data.stress_delta}`;
            // Lower stress = better (green if negative delta)
            stressDeltaEl.className = 'evening-stat-value ' +
                (data.stress_delta < 0 ? 'positive' : data.stress_delta > 0 ? 'negative' : '');
        } else {
            stressDeltaEl.textContent = '\u2014';
        }

        // Stats row 2
        const speechMin = data.total_speech_min || 0;
        const speechH = Math.floor(speechMin / 60);
        const speechM = speechMin % 60;
        document.getElementById('evening-voice-time').textContent =
            speechH > 0 ? `${speechH}h ${speechM}m` : `${speechM}m`;

        document.getElementById('evening-peak-hour').textContent = data.peak_stress_hour || '\u2014';
        document.getElementById('evening-reading-count').textContent = data.reading_count || '\u2014';

        // Mini timeline SVG
        renderEveningTimeline(data.timeline || []);

        // Insight
        const insightEl = document.getElementById('evening-insight');
        if (data.insight) {
            insightEl.textContent = `"${data.insight}"`;
            insightEl.style.display = 'block';
        }

        overlay.style.display = 'flex';

        // Mark seen
        const todayKey = `lucid_evening_seen_${new Date().toISOString().slice(0, 10)}`;
        localStorage.setItem(todayKey, '1');

        // Clean up old keys (>7 days)
        for (let i = 8; i <= 30; i++) {
            const old = new Date();
            old.setDate(old.getDate() - i);
            localStorage.removeItem(`lucid_evening_seen_${old.toISOString().slice(0, 10)}`);
        }
    }

    function animateEveningScore(el, target, duration) {
        const start = Date.now();
        if (el._scoreRAF) cancelAnimationFrame(el._scoreRAF);
        const tick = () => {
            const progress = Math.min((Date.now() - start) / duration, 1);
            const ease = 1 - Math.pow(1 - progress, 3);
            el.textContent = Math.round(ease * target);
            if (progress < 1) {
                el._scoreRAF = requestAnimationFrame(tick);
            } else {
                el._scoreRAF = null;
            }
        };
        el._scoreRAF = requestAnimationFrame(tick);
    }

    function renderEveningTimeline(timeline) {
        const svg = document.getElementById('evening-timeline-svg');
        if (!svg) return;
        while (svg.firstChild) svg.removeChild(svg.firstChild);

        const W = 520, H = 70;
        const pad = { left: 10, right: 10, top: 12, bottom: 12 };
        const innerW = W - pad.left - pad.right;
        const innerH = H - pad.top - pad.bottom;

        // Baseline
        svg.appendChild(svgEl('line', {
            x1: pad.left, x2: W - pad.right,
            y1: H - pad.bottom, y2: H - pad.bottom,
            stroke: 'rgba(255,255,255,0.1)', 'stroke-width': '1'
        }));

        if (!timeline.length) return;

        // Connect dots with a soft polyline (behind dots)
        if (timeline.length >= 2) {
            const pts = timeline.map(pt => {
                const x = pad.left + ((pt.hour - 6) / 14) * innerW;
                const y = pad.top + innerH * (1 - pt.stress / 100);
                return `${x},${y}`;
            }).join(' ');
            svg.appendChild(svgEl('polyline', {
                points: pts, fill: 'none',
                stroke: 'rgba(255,255,255,0.15)', 'stroke-width': '1.5',
                'stroke-linecap': 'round', 'stroke-linejoin': 'round'
            }));
        }

        // Dots on top
        timeline.forEach(pt => {
            const x = pad.left + ((pt.hour - 6) / 14) * innerW;
            const y = pad.top + innerH * (1 - pt.stress / 100);
            svg.appendChild(svgEl('circle', {
                cx: x, cy: y, r: 5,
                fill: ZONE_HEX[pt.zone] || ZONE_HEX.steady,
                opacity: '0.9'
            }));
        });
    }

    function dismissEveningSummary() {
        const overlay = document.getElementById('evening-summary-overlay');
        if (!overlay) return;
        overlay.classList.add('fade-out');
        setTimeout(() => {
            overlay.style.display = 'none';
            overlay.classList.remove('fade-out');
        }, 500);
    }

    // ========== Expose on window ==========

    window.loadWeeklyWrapped = loadWeeklyWrapped;
    window.showWrappedOverlay = showWrappedOverlay;
    window.dismissWrappedOverlay = dismissWrappedOverlay;
    window.shouldShowMorningSummary = shouldShowMorningSummary;
    window.loadMorningSummary = loadMorningSummary;
    window.dismissMorningSummary = dismissMorningSummary;
    window.shouldShowEveningSummary = shouldShowEveningSummary;
    window.loadEveningSummary = loadEveningSummary;
    window.dismissEveningSummary = dismissEveningSummary;

})();
