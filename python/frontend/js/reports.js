/**
 * Reports — clinical preview + PDF export
 * Enriched with acoustic/linguistic/depression data for therapist use
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
            <div class="reports-title">Clinical Voice Wellness Report</div>
            <div class="reports-subtitle">Comprehensive voice-derived wellness overview for clinical review</div>
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
                    ${this._renderClinicalSummary()}
                    ${this._renderDepressionAnxiety()}
                    ${this._renderStressChart()}
                    ${this._renderWeekOverWeek()}
                    ${this._renderAcousticProfile()}
                    ${this._renderLinguisticMarkers()}
                    ${this._renderZoneSummary()}
                    ${this._renderTherapistFlags()}
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

    // ===== Clinical Summary =====

    _renderClinicalSummary() {
        const d = this.data;
        const acoustic = d.acoustic_summary || {};
        const linguistic = d.linguistic_summary || {};
        const depression = d.depression_anxiety || {};
        const wow = d.week_over_week || {};

        let narrative = `Over the past ${d.days_tracked || 0} days, ${d.total_readings || 0} voice readings were analyzed. `;

        // Stress assessment
        const stressTrend = d.stress_trend || [];
        if (stressTrend.length > 0) {
            const avgStress = stressTrend.reduce((s, t) => s + (t.stress || 50), 0) / stressTrend.length;
            const stressLevel = avgStress >= 65 ? 'elevated' : avgStress >= 40 ? 'moderate' : 'low';
            narrative += `Average stress levels were ${stressLevel} (${avgStress.toFixed(0)}/100). `;
        }

        // Depression
        if (depression.avg_phq9_mapped != null) {
            const sev = this._phq9Severity(depression.avg_phq9_mapped);
            narrative += `Depression indicators mapped to ${sev.toLowerCase()} range (PHQ-9 equivalent: ${depression.avg_phq9_mapped.toFixed(1)}). `;
        }

        // Anxiety
        if (depression.avg_gad7_mapped != null) {
            const sev = this._gad7Severity(depression.avg_gad7_mapped);
            narrative += `Anxiety markers suggest ${sev.toLowerCase()} levels (GAD-7 equivalent: ${depression.avg_gad7_mapped.toFixed(1)}). `;
        }

        // Week-over-week
        const stressDelta = this._wowDelta(wow, 'avg_stress');
        if (stressDelta != null && Math.abs(stressDelta) > 5) {
            const dir = stressDelta > 0 ? 'increased' : 'decreased';
            narrative += `Stress ${dir} by ${Math.abs(stressDelta).toFixed(0)} points week-over-week. `;
        }

        return `
            <div class="reports-clinical-summary">
                <h3 class="section-label">CLINICAL SUMMARY</h3>
                <p class="reports-narrative">${narrative}</p>
            </div>
        `;
    }

    // ===== Depression & Anxiety =====

    _renderDepressionAnxiety() {
        const dep = this.data.depression_anxiety || {};
        if (dep.avg_phq9_mapped == null && dep.avg_gad7_mapped == null) return '';

        const phq9 = dep.avg_phq9_mapped != null ? dep.avg_phq9_mapped.toFixed(1) : '—';
        const gad7 = dep.avg_gad7_mapped != null ? dep.avg_gad7_mapped.toFixed(1) : '—';
        const phq9Sev = dep.avg_phq9_mapped != null ? this._phq9Severity(dep.avg_phq9_mapped) : '—';
        const gad7Sev = dep.avg_gad7_mapped != null ? this._gad7Severity(dep.avg_gad7_mapped) : '—';
        const phq9Class = dep.avg_phq9_mapped != null ? this._severityClass(dep.avg_phq9_mapped, 'phq9') : '';
        const gad7Class = dep.avg_gad7_mapped != null ? this._severityClass(dep.avg_gad7_mapped, 'gad7') : '';

        return `
            <div class="reports-depression-section">
                <h3 class="section-label">DEPRESSION & ANXIETY INDICATORS</h3>
                <div class="reports-dep-cards">
                    <div class="reports-dep-card">
                        <div class="reports-dep-label">PHQ-9 Mapped</div>
                        <div class="reports-dep-score">${phq9}</div>
                        <span class="reports-severity-badge ${phq9Class}">${phq9Sev}</span>
                        <div class="reports-dep-range">Range: 0–27</div>
                    </div>
                    <div class="reports-dep-card">
                        <div class="reports-dep-label">GAD-7 Mapped</div>
                        <div class="reports-dep-score">${gad7}</div>
                        <span class="reports-severity-badge ${gad7Class}">${gad7Sev}</span>
                        <div class="reports-dep-range">Range: 0–21</div>
                    </div>
                </div>
            </div>
        `;
    }

    // ===== Week-over-Week =====

    _renderWeekOverWeek() {
        const wow = this.data.week_over_week;
        if (!wow) return '';

        const metrics = [
            { key: 'avg_stress', label: 'Stress', invert: true },
            { key: 'avg_wellbeing', label: 'Wellbeing', invert: false },
            { key: 'avg_depression', label: 'Depression', invert: true },
        ];

        const cards = metrics.map(m => {
            const delta = this._wowDelta(wow, m.key);
            if (delta == null) return '';
            const arrow = delta > 0 ? '\u2191' : delta < 0 ? '\u2193' : '\u2192';
            const isGood = m.invert ? delta < 0 : delta > 0;
            const colorClass = Math.abs(delta) < 3 ? 'neutral' : (isGood ? 'positive' : 'negative');
            return `
                <div class="reports-wow-card ${colorClass}">
                    <div class="reports-wow-label">${m.label}</div>
                    <div class="reports-wow-delta">${arrow} ${delta > 0 ? '+' : ''}${delta.toFixed(1)}</div>
                    <div class="reports-wow-sublabel">vs prior week</div>
                </div>
            `;
        }).join('');

        if (!cards.trim()) return '';
        return `
            <div class="reports-wow-section">
                <h3 class="section-label">WEEK-OVER-WEEK CHANGES</h3>
                <div class="reports-wow-cards">${cards}</div>
            </div>
        `;
    }

    // ===== Acoustic Profile =====

    _renderAcousticProfile() {
        const a = this.data.acoustic_summary || {};
        if (!a.avg_f0 && !a.avg_hnr && !a.avg_speech_rate && !a.avg_alpha_ratio) return '';

        const rows = [
            { label: 'Fundamental Frequency (F0)', value: a.avg_f0, unit: 'Hz', normal: '100–250 Hz' },
            { label: 'Harmonics-to-Noise (HNR)', value: a.avg_hnr, unit: 'dB', normal: '15–25 dB' },
            { label: 'Speech Rate', value: a.avg_speech_rate, unit: 'wpm', normal: '120–180 wpm' },
            { label: 'Alpha Ratio', value: a.avg_alpha_ratio, unit: 'dB', normal: '-15 to -5 dB' },
        ].filter(r => r.value != null).map(r => `
            <tr>
                <td>${r.label}</td>
                <td><strong>${r.value.toFixed(1)} ${r.unit}</strong></td>
                <td>${r.normal}</td>
            </tr>
        `).join('');

        if (!rows) return '';
        return `
            <div class="reports-acoustic-section">
                <h3 class="section-label">ACOUSTIC PROFILE</h3>
                <table class="reports-data-table">
                    <thead><tr><th>Biomarker</th><th>Your Average</th><th>Normal Range</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
    }

    // ===== Linguistic Markers =====

    _renderLinguisticMarkers() {
        const l = this.data.linguistic_summary || {};
        if (!l.avg_filler_rate && !l.avg_hedging_rate && !l.avg_negative_sentiment) return '';

        const rows = [
            { label: 'Filler Rate', value: l.avg_filler_rate, fmt: v => (v * 100).toFixed(1) + '%', interp: 'Higher values may indicate cognitive load or uncertainty' },
            { label: 'Hedging Language', value: l.avg_hedging_rate, fmt: v => (v * 100).toFixed(1) + '%', interp: 'Elevated hedging correlates with reduced confidence' },
            { label: 'Negative Sentiment', value: l.avg_negative_sentiment, fmt: v => (v * 100).toFixed(1) + '%', interp: 'Proportion of negatively-valenced language' },
            { label: 'Lexical Diversity', value: l.avg_lexical_diversity, fmt: v => v.toFixed(2), interp: 'Lower values may suggest vocabulary contraction' },
            { label: 'Self-Focus (I-ratio)', value: l.avg_pronoun_i_ratio, fmt: v => (v * 100).toFixed(1) + '%', interp: 'Elevated self-referential language linked to rumination' },
        ].filter(r => r.value != null).map(r => `
            <tr>
                <td>${r.label}</td>
                <td><strong>${r.fmt(r.value)}</strong></td>
                <td class="reports-interp">${r.interp}</td>
            </tr>
        `).join('');

        if (!rows) return '';
        return `
            <div class="reports-linguistic-section">
                <h3 class="section-label">LINGUISTIC MARKERS</h3>
                <table class="reports-data-table">
                    <thead><tr><th>Marker</th><th>Your Average</th><th>Clinical Interpretation</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        `;
    }

    // ===== Therapist Flags =====

    _renderTherapistFlags() {
        const flags = this.data.therapist_flags || [];
        if (flags.length === 0) return '';

        const flagCards = flags.map(f => `
            <div class="reports-flag-card warning">
                <div class="reports-flag-icon">\u26A0</div>
                <div class="reports-flag-content">
                    <div class="reports-flag-title">${this._sanitize(f.flag || '').replace(/_/g, ' ')}</div>
                    <div class="reports-flag-desc">${this._sanitize(f.detail || '')}</div>
                </div>
            </div>
        `).join('');

        return `
            <div class="reports-flags-section">
                <h3 class="section-label">THERAPIST FLAGS</h3>
                ${flagCards}
            </div>
        `;
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
        this.container.querySelectorAll('.reports-range-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this.selectedDays = parseInt(btn.dataset.days);
                this.load();
            });
        });

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
            <div class="reports-title">Clinical Voice Wellness Report</div>
            <div class="reports-subtitle">Comprehensive voice-derived wellness overview for clinical review</div>
            <div class="reports-empty">
                <h3>No report data yet</h3>
                <p>Use Lucid for a few days to generate clinical reports.</p>
            </div>
        `;
    }

    // ===== Helpers =====

    _wowDelta(wow, key) {
        if (!wow || !wow.last_7d || !wow.prior_7d) return null;
        const last = wow.last_7d[key];
        const prior = wow.prior_7d[key];
        if (last == null || prior == null) return null;
        return last - prior;
    }

    _phq9Severity(score) {
        if (score < 5) return 'Minimal';
        if (score < 10) return 'Mild';
        if (score < 15) return 'Moderate';
        if (score < 20) return 'Moderately Severe';
        return 'Severe';
    }

    _gad7Severity(score) {
        if (score < 5) return 'Minimal';
        if (score < 10) return 'Mild';
        if (score < 15) return 'Moderate';
        return 'Severe';
    }

    _severityClass(score, type) {
        if (type === 'phq9') {
            if (score < 5) return 'minimal';
            if (score < 10) return 'mild';
            if (score < 15) return 'moderate';
            return 'severe';
        }
        if (score < 5) return 'minimal';
        if (score < 10) return 'mild';
        if (score < 15) return 'moderate';
        return 'severe';
    }

    _sanitize(str) {
        return typeof sanitizeHTML === 'function' ? sanitizeHTML(str) : str;
    }
}

let reportsView;
function initReportsView() {
    reportsView = new ReportsView();
}
