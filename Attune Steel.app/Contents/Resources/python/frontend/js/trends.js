/**
 * Trends view with 14-day charts and resilience score
 */

class TrendsView {
    constructor() {
        this.container = document.getElementById('trends-view');
        this.data = null;
    }

    async load(days = 14) {
        try {
            const data = await API.getTrends(days);
            this.data = data;
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

        // Clear container
        this.container.textContent = '';

        // Create structure
        const header = document.createElement('div');
        header.className = 'trends-header';

        const trend = this.data.trend_direction || 'stable';
        const trendArrow = trend === 'improving' ? '\u2191' : trend === 'declining' ? '\u2193' : '\u2192';
        const trendColor = trend === 'improving' ? '#5a9a6e' : trend === 'declining' ? '#C44E52' : '#5a6270';

        header.innerHTML = `<h2>14-Day Trends <span class="trend-arrow" style="color: ${trendColor}; font-size: 18px;">${trendArrow} ${trend}</span></h2>`;
        this.container.appendChild(header);

        // Line charts
        this.renderLineCharts();

        // Zone breakdown
        this.renderZoneBreakdown();
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
            { key: 'avg_emotional_stability', label: 'Stability', color: '#7B68EE' }
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
        title.setAttribute('fill', 'rgba(168,192,208,0.75)');
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

        // Y-axis labels (0, 50, 100)
        [0, 50, 100].forEach(val => {
            const y = yScale(val);
            const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            label.setAttribute('x', margin.left - 5);
            label.setAttribute('y', y + 4);
            label.setAttribute('text-anchor', 'end');
            label.setAttribute('font-size', '10');
            label.setAttribute('fill', 'rgba(168,192,208,0.45)');
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
