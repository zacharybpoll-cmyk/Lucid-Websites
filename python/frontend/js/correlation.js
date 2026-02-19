/**
 * History Explorer - simplified Plotly charts
 */

class CorrelationExplorer {
    constructor() {
        this.container = document.getElementById('history-view');
        this.data = null;
        this.currentChart = 'trends';
    }

    async load(days = 30) {
        try {
            const data = await API.getHistory(days);
            this.data = data;
            this.render();
        } catch (e) {
            console.error('Failed to load history:', e);
            this.renderEmpty();
        }
    }

    render() {
        if (!this.data || !this.data.readings || this.data.readings.length === 0) {
            this.renderEmpty();
            return;
        }

        // Create UI structure
        this.container.innerHTML = `
            <div class="correlation-header">
                <h2>History</h2>
                <div class="chart-type-buttons">
                    <button class="chart-btn active" data-chart="trends">Score Trends</button>
                    <button class="chart-btn" data-chart="patterns">Daily Patterns</button>
                </div>
            </div>
            <div class="correlation-controls" id="correlation-controls"></div>
            <div class="correlation-chart-container">
                <div id="plotly-chart"></div>
            </div>
            <div class="history-heatmap-section">
                <h3 class="section-label">30-DAY WELLNESS HEATMAP</h3>
                <div class="heatmap-card glass-card">
                    <div id="history-heatmap-day-headers" class="heatmap-day-headers"></div>
                    <div id="history-heatmap-calendar" class="heatmap-grid"></div>
                    <div class="heatmap-legend">
                        <span class="heatmap-legend-item"><span class="heatmap-dot good"></span>Good</span>
                        <span class="heatmap-legend-item"><span class="heatmap-dot moderate"></span>Moderate</span>
                        <span class="heatmap-legend-item"><span class="heatmap-dot poor"></span>Poor</span>
                    </div>
                </div>
            </div>
        `;

        // Wire up chart type buttons
        this.container.querySelectorAll('.chart-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this.container.querySelectorAll('.chart-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.currentChart = btn.dataset.chart;
                this.renderChart();
            });
        });

        this.renderChart();
    }

    renderChart() {
        switch (this.currentChart) {
            case 'trends':
                this.renderScoreTrends();
                break;
            case 'patterns':
                this.renderDailyPatterns();
                break;
        }
    }

    renderScoreTrends() {
        // Group readings by day and compute daily averages
        const dayMap = {};

        this.data.readings.forEach(r => {
            const day = r.timestamp.split('T')[0];
            if (!dayMap[day]) {
                dayMap[day] = {
                    stress: [],
                    mood: [],
                    energy: [],
                    calm: [],
                    depression: []
                };
            }
            dayMap[day].stress.push(r.stress_score || 0);
            dayMap[day].mood.push(r.mood_score || 0);
            dayMap[day].energy.push(r.energy_score || 0);
            dayMap[day].calm.push(r.calm_score || 0);
            // Normalize depression to 0-100
            const depScore = Math.min(100, Math.max(0, (r.depression_raw || 0) / 27 * 100));
            dayMap[day].depression.push(depScore);
        });

        const days = Object.keys(dayMap).sort();

        const avg = arr => arr.reduce((a, b) => a + b, 0) / arr.length;

        const traces = [
            {
                x: days,
                y: days.map(d => avg(dayMap[d].stress)),
                name: 'Stress',
                type: 'scatter',
                mode: 'lines+markers',
                line: { color: '#C44E52', width: 2 },
                marker: { size: 6 }
            },
            {
                x: days,
                y: days.map(d => avg(dayMap[d].mood)),
                name: 'Mood',
                type: 'scatter',
                mode: 'lines+markers',
                line: { color: '#5B8DB8', width: 2 },
                marker: { size: 6 }
            },
            {
                x: days,
                y: days.map(d => avg(dayMap[d].energy)),
                name: 'Energy',
                type: 'scatter',
                mode: 'lines+markers',
                line: { color: '#DD8452', width: 2 },
                marker: { size: 6 }
            },
            {
                x: days,
                y: days.map(d => avg(dayMap[d].calm)),
                name: 'Calm',
                type: 'scatter',
                mode: 'lines+markers',
                line: { color: '#5B5854', width: 2 },
                marker: { size: 6 }
            },
            {
                x: days,
                y: days.map(d => avg(dayMap[d].depression)),
                name: 'Depression',
                type: 'scatter',
                mode: 'lines+markers',
                line: { color: '#7B68EE', width: 2 },
                marker: { size: 6 }
            }
        ];

        const layout = {
            title: { text: 'Score Trends (Last 30 Days)', font: { size: 16 } },
            xaxis: { title: { text: 'Date', font: { size: 14 } } },
            yaxis: {
                title: { text: 'Score (0-100)', font: { size: 14 } },
                range: [0, 100],
                gridcolor: '#d4cdc3'
            },
            paper_bgcolor: '#EBE4DA',
            plot_bgcolor: '#EBE4DA',
            font: { family: 'Times New Roman', color: '#000' },
            showlegend: true,
            legend: { x: 0, y: 1 },
            hovermode: 'x unified'
        };

        Plotly.newPlot('plotly-chart', traces, layout, { displaylogo: false, responsive: true });

        document.getElementById('correlation-controls').innerHTML = '';
    }

    renderDailyPatterns() {
        // Preserve current selection if dropdown exists
        const existingSelect = document.getElementById('pattern-metric');
        const savedMetric = existingSelect ? existingSelect.value : 'stress_score';

        // Controls: Metric dropdown
        const controlsHTML = `
            <label>Metric: <select id="pattern-metric" class="chart-select">
                <option value="stress_score">Stress</option>
                <option value="mood_score">Mood</option>
                <option value="energy_score">Energy</option>
                <option value="calm_score">Calm</option>
            </select></label>
        `;
        document.getElementById('correlation-controls').innerHTML = controlsHTML;

        // Restore selection
        const selectEl = document.getElementById('pattern-metric');
        selectEl.value = savedMetric;

        const metric = selectEl.value;

        // Group by hour of day (6am-10pm only)
        const hourMap = {};
        for (let h = 6; h <= 22; h++) {
            hourMap[h] = [];
        }

        this.data.readings.forEach(r => {
            const timestamp = new Date(r.timestamp);
            const hour = timestamp.getHours();
            if (hour >= 6 && hour <= 22 && hourMap[hour]) {
                hourMap[hour].push(r[metric] || 0);
            }
        });

        const hours = Object.keys(hourMap).map(Number).sort((a, b) => a - b);
        const avg = arr => arr.length > 0 ? arr.reduce((a, b) => a + b, 0) / arr.length : null;

        const trace = {
            x: hours.map(h => h === 12 ? '12pm' : h > 12 ? `${h - 12}pm` : `${h}am`),
            y: hours.map(h => avg(hourMap[h])),
            type: 'scatter',
            mode: 'lines+markers',
            connectgaps: false,
            line: { color: '#5B5854', width: 3 },
            marker: { size: 8 }
        };

        const metricLabel = metric.replace(/_score/g, '').replace(/_/g, ' ').toUpperCase();

        const layout = {
            title: { text: `Average ${metricLabel} by Hour of Day`, font: { size: 16 } },
            xaxis: { title: { text: 'Hour', font: { size: 14 } } },
            yaxis: {
                title: { text: 'Score (0-100)', font: { size: 14 } },
                range: [0, 100],
                gridcolor: '#d4cdc3'
            },
            paper_bgcolor: '#EBE4DA',
            plot_bgcolor: '#EBE4DA',
            font: { family: 'Times New Roman', color: '#000' }
        };

        Plotly.newPlot('plotly-chart', [trace], layout, { displaylogo: false, responsive: true });

        selectEl.addEventListener('change', () => this.renderDailyPatterns());
    }

    renderEmpty() {
        this.container.innerHTML = `
            <div class="correlation-empty">
                <h2>Not enough data yet</h2>
                <p>Use the app for a few days to see trends and patterns.</p>
            </div>
        `;
    }
}

let correlationExplorer;

function initCorrelationExplorer() {
    correlationExplorer = new CorrelationExplorer();
}
