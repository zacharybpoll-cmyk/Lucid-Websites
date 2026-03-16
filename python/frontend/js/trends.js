/**
 * Trends view with 14-day charts and resilience score
 */

class TrendsView {
    constructor() {
        this.container = document.getElementById('trends-dynamic-content');
        this.data = null;
    }

    async load(days = 14) {
        try {
            const [data, summaries, echoProgress] = await Promise.all([
                API.getTrends(days),
                API.getSummaries(35).catch(() => []),
                API.getEchoProgress().catch(() => null),
            ]);
            this.data = data;
            this.summaries = summaries;
            this.days = days;
            this.echoProgress = echoProgress;
            this.render();
        } catch (e) {
            console.error('Failed to load trends:', e);
            this.renderEmpty();
        }
    }

    render() {
        if (!this.data || !this.data.daily_summaries || this.data.daily_summaries.length === 0) {
            this.renderEmpty();
            return;
        }

        this.container.textContent = '';

        // Echo teaser card (prepend if echo is forming)
        if (this.echoProgress && this.echoProgress.sessions_until_next_echo > 0) {
            const ep = this.echoProgress;
            const pct = Math.round((ep.sessions_completed / ep.total_sessions_needed) * 100);
            const teaserDiv = document.createElement('div');
            teaserDiv.className = 'echo-teaser-card';
            teaserDiv.innerHTML = `
                <div class="echo-teaser-header">
                    <span class="echo-teaser-pulse"></span>
                    <span class="echo-teaser-title">Echo Forming...</span>
                </div>
                <p class="echo-teaser-main">${ep.sessions_until_next_echo} reading${ep.sessions_until_next_echo !== 1 ? 's' : ''} away from your next Echo</p>
                <div class="echo-teaser-bar-wrap">
                    <div class="echo-teaser-bar-fill" style="width: ${pct}%"></div>
                </div>
                <p class="echo-teaser-hint">Pattern in progress... ${sanitizeHTML(ep.pattern_hint)}</p>
                <p class="echo-teaser-footer"><em>Something is taking shape in your data.</em></p>
            `;
            this.container.appendChild(teaserDiv);
        }

        // Day toggle
        const toggleDiv = document.createElement('div');
        toggleDiv.className = 'trends-day-toggle';
        toggleDiv.innerHTML = `
            <button class="trends-toggle-btn ${this.days === 14 ? 'active' : ''}" data-days="14">14 Days</button>
            <button class="trends-toggle-btn ${this.days === 30 ? 'active' : ''}" data-days="30">30 Days</button>
        `;
        toggleDiv.querySelectorAll('.trends-toggle-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this.load(parseInt(btn.dataset.days));
            });
        });
        this.container.appendChild(toggleDiv);

        // Arc chart hero — after day toggle
        this.renderArcChart();

        // Score Trends (Plotly) — moved up
        this.renderScoreTrends();

        // Header
        const header = document.createElement('div');
        header.className = 'trends-header';
        const trend = this.data.trend_direction || 'stable';
        const trendArrow = trend === 'improving' ? '\u2191' : trend === 'declining' ? '\u2193' : '\u2192';
        const trendColor = trend === 'improving' ? '#5a9a6e' : trend === 'declining' ? '#C44E52' : '#5a6270';
        header.innerHTML = `<h2>${this.days}-Day Trends <span class="trend-arrow" style="color: ${trendColor}; font-size: 18px;">${trendArrow} ${trend}</span></h2>`;
        this.container.appendChild(header);

        // Line charts
        this.renderLineCharts();

        // Zone breakdown + legend
        this.renderZoneBreakdown();
        this.renderZoneLegend();

        // 30-Day Heatmap
        this.renderHeatmap();
    }

    renderArcChart() {
        const summaries = [...this.data.daily_summaries].sort((a, b) => new Date(a.date) - new Date(b.date));
        // Use wellness score if available, fall back to wellbeing, then 50
        const scores = summaries.map(s => s.avg_wellness ?? s.avg_wellbeing ?? s.avg_mood ?? 50);

        const card = document.createElement('div');
        card.className = 'arc-chart-card';

        const label = document.createElement('div');
        label.className = 'arc-chart-label';
        label.textContent = 'YOUR ARC — ' + this.days + ' DAYS';

        const svgNS = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(svgNS, 'svg');
        svg.setAttribute('class', 'trends-arc-svg');
        svg.setAttribute('viewBox', '0 0 800 160');
        svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');

        const narrative = document.createElement('p');
        narrative.className = 'arc-narrative';

        card.appendChild(label);
        card.appendChild(svg);
        card.appendChild(narrative);
        this.container.appendChild(card);

        if (scores.length < 2) {
            narrative.textContent = 'Not enough data yet to draw your arc.';
            return;
        }

        const W = 800, H = 160;
        const padL = 14, padR = 14, padT = 24, padB = 32;
        const plotW = W - padL - padR;
        const plotH = H - padT - padB;

        const minScore = Math.min(...scores);
        const maxScore = Math.max(...scores);
        const range = maxScore - minScore || 10; // avoid divide-by-zero

        const xOf = (i) => padL + (i / (scores.length - 1)) * plotW;
        const yOf = (v) => padT + plotH - ((v - minScore) / range) * plotH;

        // Build smooth catmull-rom cubic bezier path
        // Each segment P[i]→P[i+1] uses control points derived from neighbours
        function catmullRomPath(pts) {
            if (pts.length < 2) return '';
            let d = `M ${pts[0][0]},${pts[0][1]}`;
            for (let i = 0; i < pts.length - 1; i++) {
                const p0 = pts[Math.max(i - 1, 0)];
                const p1 = pts[i];
                const p2 = pts[i + 1];
                const p3 = pts[Math.min(i + 2, pts.length - 1)];
                // Catmull-Rom tension = 0.5
                const cp1x = p1[0] + (p2[0] - p0[0]) / 6;
                const cp1y = p1[1] + (p2[1] - p0[1]) / 6;
                const cp2x = p2[0] - (p3[0] - p1[0]) / 6;
                const cp2y = p2[1] - (p3[1] - p1[1]) / 6;
                d += ` C ${cp1x.toFixed(2)},${cp1y.toFixed(2)} ${cp2x.toFixed(2)},${cp2y.toFixed(2)} ${p2[0]},${p2[1]}`;
            }
            return d;
        }

        const pts = scores.map((v, i) => [xOf(i), yOf(v)]);
        const pathD = catmullRomPath(pts);

        // Axis reference lines (draw first, behind everything)
        const addAxisLine = (idx, labelText) => {
            const x = xOf(idx);
            const line = document.createElementNS(svgNS, 'line');
            line.setAttribute('x1', x); line.setAttribute('y1', padT);
            line.setAttribute('x2', x); line.setAttribute('y2', padT + plotH);
            line.setAttribute('stroke', 'rgba(90,98,112,0.12)');
            line.setAttribute('stroke-width', '1');
            svg.appendChild(line);
            const text = document.createElementNS(svgNS, 'text');
            text.setAttribute('x', x);
            text.setAttribute('y', H - 6);
            text.setAttribute('text-anchor', 'middle');
            text.setAttribute('font-family', 'Inter, sans-serif');
            text.setAttribute('font-size', '9');
            text.setAttribute('fill', 'rgba(90,98,112,0.45)');
            text.setAttribute('letter-spacing', '0.04em');
            text.textContent = labelText;
            svg.appendChild(text);
        };

        const fmtDate = (dateStr) => {
            const d = new Date(dateStr + 'T12:00:00');
            return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        };

        const midIdx = Math.floor((scores.length - 1) / 2);
        addAxisLine(0, fmtDate(summaries[0].date));
        addAxisLine(midIdx, fmtDate(summaries[midIdx].date));
        addAxisLine(scores.length - 1, 'Today');

        // Main smooth arc line
        const path = document.createElementNS(svgNS, 'path');
        path.setAttribute('d', pathD);
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke', '#5B8DB8');
        path.setAttribute('stroke-width', '1.5');
        path.setAttribute('stroke-linejoin', 'round');
        path.setAttribute('stroke-linecap', 'round');
        svg.appendChild(path);

        // Milestone detection
        const floorIdx = scores.indexOf(minScore);
        let turnIdx = -1;
        if (floorIdx < scores.length - 3) {
            for (let i = floorIdx + 1; i <= scores.length - 3; i++) {
                if (scores[i] > minScore + 5 && scores[i+1] > minScore + 5 && scores[i+2] > minScore + 5) {
                    turnIdx = i;
                    break;
                }
            }
        }
        const currentIdx = scores.length - 1;

        const addDot = (idx, strokeColor, fillColor, labelText, labelBelow) => {
            const cx = xOf(idx);
            const cy = yOf(scores[idx]);
            const circle = document.createElementNS(svgNS, 'circle');
            circle.setAttribute('cx', cx); circle.setAttribute('cy', cy);
            circle.setAttribute('r', '4.5');
            circle.setAttribute('fill', fillColor);
            circle.setAttribute('stroke', strokeColor);
            circle.setAttribute('stroke-width', '1.5');
            svg.appendChild(circle);

            const text = document.createElementNS(svgNS, 'text');
            text.setAttribute('x', cx);
            text.setAttribute('y', labelBelow ? cy + 17 : cy - 9);
            text.setAttribute('text-anchor', 'middle');
            text.setAttribute('font-family', 'Inter, sans-serif');
            text.setAttribute('font-size', '8');
            text.setAttribute('fill', strokeColor);
            text.setAttribute('font-weight', '600');
            text.setAttribute('letter-spacing', '0.08em');
            text.textContent = labelText;
            svg.appendChild(text);
        };

        addDot(floorIdx, '#B45309', '#FEF3C7', 'THE FLOOR', true);
        if (turnIdx >= 0) addDot(turnIdx, '#5B8DB8', '#DBEAFE', 'THE TURN', false);
        // Current altitude — solid dot with score number
        addDot(currentIdx, '#5B8DB8', '#5B8DB8', Math.round(scores[currentIdx]) + '', false);

        // Narrative sentence
        const climb = Math.round(scores[currentIdx] - minScore);
        const lookback = Math.min(scores.length - 1, 6);
        const recentChange = scores[currentIdx] - scores[currentIdx - lookback];
        const direction = recentChange > 3 ? 'pointing up' : recentChange < -3 ? 'pointing down' : 'holding steady';
        narrative.textContent = `You've climbed ${climb} points from your floor. The arc is ${direction}.`;
    }

    renderLineCharts() {
        const chartsContainer = document.createElement('div');
        chartsContainer.className = 'trends-charts';

        // 5 metrics to chart
        const metrics = [
            { key: 'avg_stress', label: 'Stress', color: '#C44E52' },
            { key: 'avg_wellbeing', label: 'Wellbeing', color: '#5B8DB8', fallback: 'avg_mood' },
            { key: 'avg_activation', label: 'Activation', color: '#6a90a8', fallback: 'avg_energy' },
            { key: 'avg_calm', label: 'Calm', color: '#7a9eb8' },
            { key: 'avg_emotional_stability', label: 'Stability', color: '#7B68EE' },
            { key: 'avg_depression', label: 'Low Mood', color: '#8B6E8B' },
            { key: 'avg_anxiety', label: 'Tension', color: '#C4884E' }
        ];

        metrics.forEach(metric => {
            const chartDiv = document.createElement('div');
            chartDiv.className = 'trend-chart';
            chartDiv.id = `chart-${metric.key}`;
            chartsContainer.appendChild(chartDiv);

            this.renderLineChart(chartDiv, metric);
        });

        this.container.appendChild(chartsContainer);
    }

    renderLineChart(container, metric) {
        // Sort summaries by date ascending
        const summaries = [...this.data.daily_summaries].sort((a, b) =>
            new Date(a.date) - new Date(b.date)
        );

        const width = 400;
        const height = 200;
        const margin = { top: 30, right: 55, bottom: 40, left: 40 };

        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('width', '100%');
        svg.setAttribute('height', height);
        svg.setAttribute('viewBox', `0 0 ${width} ${height}`);

        // Scales
        const plotWidth = width - margin.left - margin.right;
        const plotHeight = height - margin.top - margin.bottom;

        const xScale = (index) => margin.left + (index / (summaries.length - 1)) * plotWidth;
        const yScale = (value) => margin.top + (1 - value / 100) * plotHeight;

        // Band definitions per metric
        const bandDefs = {
            'avg_stress': [
                { min: 0, max: 25, label: 'Low', color: 'rgba(90,154,110,0.07)' },
                { min: 25, max: 50, label: 'Moderate', color: 'rgba(168,192,208,0.04)' },
                { min: 50, max: 75, label: 'High', color: 'rgba(196,130,58,0.07)' },
                { min: 75, max: 100, label: 'V. High', color: 'rgba(196,88,76,0.10)' }
            ],
            'avg_mood': [
                { min: 0, max: 25, label: 'Low', color: 'rgba(196,88,76,0.10)' },
                { min: 25, max: 50, label: 'Fair', color: 'rgba(196,130,58,0.07)' },
                { min: 50, max: 75, label: 'Good', color: 'rgba(168,192,208,0.04)' },
                { min: 75, max: 100, label: 'Great', color: 'rgba(90,154,110,0.07)' }
            ],
            'avg_energy': [
                { min: 0, max: 25, label: 'Low', color: 'rgba(196,88,76,0.10)' },
                { min: 25, max: 50, label: 'Moderate', color: 'rgba(168,192,208,0.04)' },
                { min: 50, max: 75, label: 'Good', color: 'rgba(90,154,110,0.07)' },
                { min: 75, max: 100, label: 'High', color: 'rgba(90,154,110,0.07)' }
            ],
            'avg_calm': [
                { min: 0, max: 25, label: 'Low', color: 'rgba(196,88,76,0.10)' },
                { min: 25, max: 50, label: 'Fair', color: 'rgba(196,130,58,0.07)' },
                { min: 50, max: 75, label: 'Good', color: 'rgba(168,192,208,0.04)' },
                { min: 75, max: 100, label: 'V. Calm', color: 'rgba(90,154,110,0.07)' }
            ],
            'avg_wellbeing': [
                { min: 0, max: 25, label: 'Low', color: 'rgba(196,88,76,0.10)' },
                { min: 25, max: 50, label: 'Fair', color: 'rgba(196,130,58,0.07)' },
                { min: 50, max: 75, label: 'Good', color: 'rgba(168,192,208,0.04)' },
                { min: 75, max: 100, label: 'Great', color: 'rgba(90,154,110,0.07)' }
            ],
            'avg_activation': [
                { min: 0, max: 25, label: 'Low', color: 'rgba(196,88,76,0.10)' },
                { min: 25, max: 50, label: 'Moderate', color: 'rgba(168,192,208,0.04)' },
                { min: 50, max: 75, label: 'Good', color: 'rgba(90,154,110,0.07)' },
                { min: 75, max: 100, label: 'High', color: 'rgba(90,154,110,0.07)' }
            ],
            'avg_emotional_stability': [
                { min: 0, max: 25, label: 'Volatile', color: 'rgba(196,88,76,0.10)' },
                { min: 25, max: 50, label: 'Variable', color: 'rgba(196,130,58,0.07)' },
                { min: 50, max: 75, label: 'Steady', color: 'rgba(168,192,208,0.04)' },
                { min: 75, max: 100, label: 'Stable', color: 'rgba(90,154,110,0.07)' }
            ],
            'avg_depression': [
                { min: 0, max: 25, label: 'Low', color: 'rgba(90,154,110,0.07)' },
                { min: 25, max: 50, label: 'Moderate', color: 'rgba(168,192,208,0.04)' },
                { min: 50, max: 75, label: 'High', color: 'rgba(196,130,58,0.07)' },
                { min: 75, max: 100, label: 'V. High', color: 'rgba(196,88,76,0.10)' }
            ],
            'avg_anxiety': [
                { min: 0, max: 25, label: 'Low', color: 'rgba(90,154,110,0.07)' },
                { min: 25, max: 50, label: 'Moderate', color: 'rgba(168,192,208,0.04)' },
                { min: 50, max: 75, label: 'High', color: 'rgba(196,130,58,0.07)' },
                { min: 75, max: 100, label: 'V. High', color: 'rgba(196,88,76,0.10)' }
            ]
        };

        // Draw background bands
        const bands = bandDefs[metric.key] || bandDefs['avg_stress'];
        bands.forEach(band => {
            const y1 = yScale(band.max);
            const y2 = yScale(band.min);
            const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
            rect.setAttribute('x', margin.left);
            rect.setAttribute('y', y1);
            rect.setAttribute('width', plotWidth);
            rect.setAttribute('height', y2 - y1);
            rect.setAttribute('fill', band.color);
            svg.appendChild(rect);

            // Right-side band label
            const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            label.setAttribute('x', margin.left + plotWidth + 4);
            label.setAttribute('y', (y1 + y2) / 2 + 3);
            label.setAttribute('font-size', '8');
            label.setAttribute('font-family', 'Inter, sans-serif');
            label.setAttribute('fill', 'rgba(168,192,208,0.35)');
            label.textContent = band.label;
            svg.appendChild(label);
        });

        // Title
        const title = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        title.setAttribute('x', width / 2);
        title.setAttribute('y', 15);
        title.setAttribute('text-anchor', 'middle');
        title.setAttribute('font-size', '14');
        title.setAttribute('fill', 'rgba(90,98,112,0.75)');
        title.textContent = metric.label;
        svg.appendChild(title);

        // Y-axis
        const yAxis = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        yAxis.setAttribute('x1', margin.left);
        yAxis.setAttribute('y1', margin.top);
        yAxis.setAttribute('x2', margin.left);
        yAxis.setAttribute('y2', height - margin.bottom);
        yAxis.setAttribute('stroke', 'rgba(168,192,208,0.2)');
        yAxis.setAttribute('stroke-width', '1');
        svg.appendChild(yAxis);

        // X-axis
        const xAxis = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        xAxis.setAttribute('x1', margin.left);
        xAxis.setAttribute('y1', height - margin.bottom);
        xAxis.setAttribute('x2', width - margin.right);
        xAxis.setAttribute('y2', height - margin.bottom);
        xAxis.setAttribute('stroke', 'rgba(168,192,208,0.2)');
        xAxis.setAttribute('stroke-width', '1');
        svg.appendChild(xAxis);

        // Y-axis labels + gridlines (0, 25, 50, 75, 100)
        [0, 25, 50, 75, 100].forEach(val => {
            const y = yScale(val);
            // Horizontal gridline
            const gridLine = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            gridLine.setAttribute('x1', margin.left);
            gridLine.setAttribute('y1', y);
            gridLine.setAttribute('x2', margin.left + plotWidth);
            gridLine.setAttribute('y2', y);
            gridLine.setAttribute('stroke', 'rgba(90,98,112,0.08)');
            gridLine.setAttribute('stroke-width', '1');
            gridLine.setAttribute('stroke-dasharray', val === 0 || val === 100 ? 'none' : '3,3');
            svg.appendChild(gridLine);
            // Label
            const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            label.setAttribute('x', margin.left - 5);
            label.setAttribute('y', y + 4);
            label.setAttribute('text-anchor', 'end');
            label.setAttribute('font-size', '9');
            label.setAttribute('fill', 'rgba(90,98,112,0.45)');
            label.textContent = val;
            svg.appendChild(label);
        });

        // Line path (with fallback key support for backward compat)
        const getVal = (s) => s[metric.key] || (metric.fallback ? s[metric.fallback] : null) || 50;
        const points = summaries.map((s, i) => {
            const x = xScale(i);
            const y = yScale(getVal(s));
            return `${x},${y}`;
        });

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', `M ${points.join(' L ')}`);
        path.setAttribute('stroke', metric.color);
        path.setAttribute('stroke-width', '2');
        path.setAttribute('fill', 'none');
        svg.appendChild(path);

        // Dots
        summaries.forEach((s, i) => {
            const x = xScale(i);
            const y = yScale(getVal(s));

            const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
            circle.setAttribute('cx', x);
            circle.setAttribute('cy', y);
            circle.setAttribute('r', 4);
            circle.setAttribute('fill', metric.color);
            circle.setAttribute('stroke', 'rgba(168,192,208,0.3)');
            circle.setAttribute('stroke-width', '1');
            svg.appendChild(circle);
        });

        container.appendChild(svg);
    }

    renderZoneBreakdown() {
        const breakdownContainer = document.createElement('div');
        breakdownContainer.className = 'zone-breakdown-container';
        breakdownContainer.innerHTML = '<h3>Time in Each Zone (per day)</h3>';

        const summaries = [...this.data.daily_summaries].sort((a, b) =>
            new Date(a.date) - new Date(b.date)
        );

        summaries.forEach(summary => {
            const total =
                (summary.time_in_calm_min || 0) +
                (summary.time_in_steady_min || 0) +
                (summary.time_in_tense_min || 0) +
                (summary.time_in_stressed_min || 0);

            if (total === 0) return;

            const calmPct = ((summary.time_in_calm_min || 0) / total) * 100;
            const steadyPct = ((summary.time_in_steady_min || 0) / total) * 100;
            const tensePct = ((summary.time_in_tense_min || 0) / total) * 100;
            const stressedPct = ((summary.time_in_stressed_min || 0) / total) * 100;

            const date = new Date(summary.date);
            const dateStr = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

            const bar = document.createElement('div');
            bar.className = 'zone-breakdown-bar';
            bar.innerHTML = `
                <div class="zone-breakdown-label">${dateStr}</div>
                <div class="zone-breakdown-segments">
                    <div class="zone-segment calm" style="width: ${calmPct}%" title="Calm: ${Math.round(summary.time_in_calm_min || 0)}m"></div>
                    <div class="zone-segment steady" style="width: ${steadyPct}%" title="Steady: ${Math.round(summary.time_in_steady_min || 0)}m"></div>
                    <div class="zone-segment tense" style="width: ${tensePct}%" title="Tense: ${Math.round(summary.time_in_tense_min || 0)}m"></div>
                    <div class="zone-segment stressed" style="width: ${stressedPct}%" title="Stressed: ${Math.round(summary.time_in_stressed_min || 0)}m"></div>
                </div>
            `;
            breakdownContainer.appendChild(bar);
        });

        this.container.appendChild(breakdownContainer);
    }

    renderZoneLegend() {
        const legend = document.createElement('div');
        legend.className = 'zone-legend';
        legend.innerHTML = `
            <span class="zone-legend-item"><span class="zone-legend-dot" style="background: #5B8DB8;"></span>Calm</span>
            <span class="zone-legend-item"><span class="zone-legend-dot" style="background: #5a6270;"></span>Steady</span>
            <span class="zone-legend-item"><span class="zone-legend-dot" style="background: #DD8452;"></span>Tense</span>
            <span class="zone-legend-item"><span class="zone-legend-dot" style="background: #C44E52;"></span>Stressed</span>
        `;
        this.container.appendChild(legend);
    }

    renderScoreTrends() {
        if (!this.data || !this.data.daily_summaries || this.data.daily_summaries.length < 2) return;

        const section = document.createElement('div');
        section.className = 'trends-score-trends';
        section.innerHTML = `
            <h3 class="section-label">HEALTH TRENDS</h3>
            <div id="trends-plotly-chart"></div>
        `;
        this.container.appendChild(section);

        const summaries = [...this.data.daily_summaries].sort((a, b) => new Date(a.date) - new Date(b.date));
        const days = summaries.map(s => s.date);
        const avg = (key) => summaries.map(s => s[key] || 50);

        const traces = [
            { x: days, y: avg('avg_stress'), name: 'Stress', line: { color: '#C44E52', width: 2 }, marker: { size: 5 } },
            { x: days, y: avg('avg_wellbeing'), name: 'Wellbeing', line: { color: '#5B8DB8', width: 2 }, marker: { size: 5 } },
            { x: days, y: avg('avg_activation'), name: 'Activation', line: { color: '#DD8452', width: 2 }, marker: { size: 5 } },
            { x: days, y: avg('avg_calm'), name: 'Calm', line: { color: '#5a6270', width: 2 }, marker: { size: 5 } },
            { x: days, y: avg('avg_emotional_stability'), name: 'Stability', line: { color: '#7B68EE', width: 2 }, marker: { size: 5 } },
            { x: days, y: avg('avg_depression'), name: 'Depression', line: { color: '#8B5CF6', width: 2 }, marker: { size: 5 } },
            { x: days, y: avg('avg_anxiety'), name: 'Anxiety', line: { color: '#F59E0B', width: 2 }, marker: { size: 5 } },
        ].map(t => ({ ...t, type: 'scatter', mode: 'lines+markers' }));

        const layout = {
            xaxis: { title: { text: 'Date', font: { size: 12 } } },
            yaxis: { title: { text: 'Score', font: { size: 12 } }, range: [0, 100], gridcolor: '#e4e8ec' },
            paper_bgcolor: 'transparent',
            plot_bgcolor: 'transparent',
            font: { family: 'Inter, sans-serif', color: '#5a6270', size: 11 },
            showlegend: true,
            legend: { orientation: 'h', x: 0.5, xanchor: 'center', y: 1.1, font: { size: 10 } },
            hovermode: 'x unified',
            margin: { t: 10, r: 20, b: 40, l: 45 },
            height: 280,
        };

        if (typeof Plotly !== 'undefined') {
            Plotly.newPlot('trends-plotly-chart', traces, layout, { displaylogo: false, displayModeBar: false, responsive: true });
        }
    }

    renderHeatmap() {
        if (!this.summaries || this.summaries.length === 0) return;

        const section = document.createElement('div');
        section.className = 'trends-heatmap-section';
        section.innerHTML = `
            <h3 class="section-label">WELLNESS HEATMAP</h3>
            <div class="heatmap-card glass-card">
                <div id="trends-heatmap-day-headers" class="heatmap-day-headers"></div>
                <div id="trends-heatmap-calendar" class="heatmap-grid"></div>
                <div class="heatmap-legend">
                    <span class="heatmap-legend-item"><span class="heatmap-dot good"></span>Good</span>
                    <span class="heatmap-legend-item"><span class="heatmap-dot moderate"></span>Moderate</span>
                    <span class="heatmap-legend-item"><span class="heatmap-dot poor"></span>Poor</span>
                </div>
            </div>
        `;
        this.container.appendChild(section);

        // Reuse existing heatmap function from gauges.js
        if (typeof updateHeatmapCalendar === 'function') {
            // Need to temporarily set the header container ID
            const headersEl = document.getElementById('trends-heatmap-day-headers');
            if (headersEl) {
                const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
                headersEl.innerHTML = days.map(d => `<span class="heatmap-day-header">${d}</span>`).join('');
            }
            updateHeatmapCalendar(this.summaries, 'trends-heatmap-calendar');
        }
    }

    renderEmpty() {
        this.container.innerHTML = `
            <div class="trends-empty">
                <h2>Not enough data yet</h2>
                <p>Use the app for a few days to see resilience trends and 14-day charts.</p>
            </div>
        `;
    }
}

let trendsView;

function initTrendsView() {
    trendsView = new TrendsView();
}
