/**
 * Reports — clinical preview + PDF export
 */
class ReportsView {
    constructor() {
        this.container = document.getElementById('reports-view');
        this.data = null;
        this.selectedDays = 90;
    }

    async load() {
        if (!this.container) return;
        this.container.innerHTML = '<div style="padding:40px;color:#5a6270;">Loading reports...</div>';

        try {
            this.data = await API.getClinicalPreview(this.selectedDays);
            this.render();
        } catch (e) {
            console.error('Failed to load reports:', e);
            this.renderEmpty();
        }
    }

    render() {
        if (!this.data || !this.data.has_data) {
            this.renderEmpty();
            return;
        }

        const d = this.data;

        this.container.innerHTML = `
            <div class="reports-title">Reports</div>
            <div class="reports-subtitle">Clinical overview and export tools</div>
            <div class="reports-stats">
                <div class="reports-stat">
                    <div class="reports-stat-value">${d.days_tracked || 0}</div>
                    <div class="reports-stat-label">Days tracked</div>
                </div>
                <div class="reports-stat">
                    <div class="reports-stat-value">${d.total_readings || 0}</div>
                    <div class="reports-stat-label">Total readings</div>
                </div>
                <div class="reports-stat">
                    <div class="reports-stat-value">${d.flagged_events ? d.flagged_events.length : 0}</div>
                    <div class="reports-stat-label">Flagged events</div>
                </div>
            </div>
            <div class="reports-layout">
                <div class="reports-main">
                    ${this._renderStressChart()}
                    ${this._renderZoneSummary()}
                    ${this._renderGroveDots()}
                    ${this._renderFlaggedEvents()}
                </div>
                <div class="reports-sidebar">
                    ${this._renderExportCard()}
                </div>
            </div>
        `;

        this._drawStressPlotly();
        this._wireEvents();
    }

    _renderStressChart() {
        return `
            <div class="reports-stress-section">
                <h3 class="section-label">STRESS TREND (${this.selectedDays} DAYS)</h3>
                <div id="reports-stress-chart" style="border-radius:10px;overflow:hidden;"></div>
            </div>
        `;
    }

    _renderZoneSummary() {
        const z = this.data.zone_summary || {};
        return `
            <div style="margin-bottom:20px;">
                <h3 class="section-label">ZONE DISTRIBUTION</h3>
                <div class="reports-zone-bar">
                    <div class="reports-zone-seg" style="width:${z.calm_pct||0}%;background:#5B8DB8;" title="Calm ${z.calm_pct||0}%"></div>
                    <div class="reports-zone-seg" style="width:${z.steady_pct||0}%;background:#5a6270;" title="Steady ${z.steady_pct||0}%"></div>
                    <div class="reports-zone-seg" style="width:${z.tense_pct||0}%;background:#DD8452;" title="Tense ${z.tense_pct||0}%"></div>
                    <div class="reports-zone-seg" style="width:${z.stressed_pct||0}%;background:#C44E52;" title="Stressed ${z.stressed_pct||0}%"></div>
                </div>
                <div class="reports-zone-labels">
                    <span>Calm ${z.calm_pct||0}%</span>
                    <span>Steady ${z.steady_pct||0}%</span>
                    <span>Tense ${z.tense_pct||0}%</span>
                    <span>Stressed ${z.stressed_pct||0}%</span>
                </div>
            </div>
        `;
    }

    _renderGroveDots() {
        const cal = this.data.grove_calendar || [];
        if (cal.length === 0) return '';
        const dots = cal.map(entry => {
            const cls = entry.active ? 'active' : (entry.partial ? 'partial' : '');
            return `<div class="reports-grove-dot ${cls}" title="${entry.date || ''}"></div>`;
        }).join('');
        return `
            <div class="reports-grove-section">
                <h3 class="section-label">GROVE PARTICIPATION</h3>
                <div class="reports-grove-dots">${dots}</div>
            </div>
        `;
    }

    _renderFlaggedEvents() {
        const events = this.data.flagged_events || [];
        if (events.length === 0) {
            return `
                <div class="reports-events-section">
                    <h3 class="section-label">FLAGGED HEALTH EVENTS</h3>
                    <div style="color:#8C96A0;font-size:13px;padding:12px 0;">No flagged events in this period.</div>
                </div>
            `;
        }
        const rows = events.map(e => `
            <tr>
                <td>${this._sanitize(e.date || '')}</td>
                <td><span class="reports-event-severity ${e.severity || ''}">${this._sanitize(e.severity || 'info')}</span></td>
                <td>${this._sanitize(e.message || '')}</td>
            </tr>
        `).join('');
        return `
            <div class="reports-events-section">
                <h3 class="section-label">FLAGGED HEALTH EVENTS</h3>
                <table class="reports-events-table">
                    <thead><tr><th>Date</th><th>Severity</th><th>Details</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
    }

    _renderExportCard() {
        return `
            <div class="reports-export-card">
                <div class="reports-export-title">Export Clinical Report</div>
                <div class="reports-range-btns">
                    <button class="reports-range-btn ${this.selectedDays === 30 ? 'active' : ''}" data-days="30">30d</button>
                    <button class="reports-range-btn ${this.selectedDays === 90 ? 'active' : ''}" data-days="90">90d</button>
                </div>
                <button class="reports-generate-btn" id="reports-generate-pdf">Generate PDF Report</button>
                <button class="reports-share-btn" id="reports-share-btn">Share with Therapist</button>
            </div>
        `;
    }

    _drawStressPlotly() {
        const trend = this.data.stress_trend || [];
        if (trend.length === 0 || typeof Plotly === 'undefined') return;

        const trace = {
            x: trend.map(t => t.date),
            y: trend.map(t => t.stress),
            type: 'scatter',
            mode: 'lines',
            fill: 'tozeroy',
            line: { color: '#5B8DB8', width: 2 },
            fillcolor: 'rgba(91,141,184,0.1)',
        };

        const layout = {
            yaxis: { range: [0, 100], gridcolor: '#e4e8ec', title: { text: 'Stress', font: { size: 11 } } },
            xaxis: { title: { text: 'Date', font: { size: 11 } } },
            paper_bgcolor: 'transparent',
            plot_bgcolor: 'transparent',
            font: { family: 'Inter, sans-serif', color: '#5a6270', size: 11 },
            margin: { t: 10, r: 20, b: 40, l: 45 },
            height: 240,
            hovermode: 'x unified',
        };

        Plotly.newPlot('reports-stress-chart', [trace], layout, { displaylogo: false, responsive: true });
    }

    _wireEvents() {
        // Range buttons
        this.container.querySelectorAll('.reports-range-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this.selectedDays = parseInt(btn.dataset.days);
                this.load();
            });
        });

        // Generate PDF
        const genBtn = document.getElementById('reports-generate-pdf');
        if (genBtn) {
            genBtn.addEventListener('click', async () => {
                genBtn.disabled = true;
                genBtn.textContent = 'Generating...';
                try {
                    await API.generateClinicalPDF(this.selectedDays);
                } catch (e) {
                    console.error('PDF generation failed:', e);
                } finally {
                    genBtn.disabled = false;
                    genBtn.textContent = 'Generate PDF Report';
                }
            });
        }

        // Share button (opens therapist summary in new tab for now)
        const shareBtn = document.getElementById('reports-share-btn');
        if (shareBtn) {
            shareBtn.addEventListener('click', async () => {
                try {
                    const summary = await API.getTherapistSummary(this.selectedDays);
                    const blob = new Blob([JSON.stringify(summary, null, 2)], { type: 'application/json' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `lucid_therapist_summary_${this.selectedDays}d.json`;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    URL.revokeObjectURL(url);
                } catch (e) {
                    console.error('Share failed:', e);
                }
            });
        }
    }

    renderEmpty() {
        if (!this.container) return;
        this.container.innerHTML = `
            <div class="reports-title">Reports</div>
            <div class="reports-subtitle">Clinical overview and export tools</div>
            <div class="reports-empty">
                <h3>No report data yet</h3>
                <p>Use Lucid for a few days to generate clinical reports.</p>
            </div>
        `;
    }

    _sanitize(str) {
        return typeof sanitizeHTML === 'function' ? sanitizeHTML(str) : str;
    }
}

let reportsView;
function initReportsView() {
    reportsView = new ReportsView();
}
