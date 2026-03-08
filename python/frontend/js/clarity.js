/**
 * clarity.js — Clarity Journey
 * 12-week structured coaching with track selection, progress arc, daily actions.
 */
const clarityView = (() => {
    let journeyData = null;

    async function load() {
        const container = document.getElementById('journey-view');
        if (!container) return;
        container.innerHTML = '<div style="text-align:center;padding:60px;color:#5a6270;">Loading journey...</div>';

        try {
            const data = await API.getClarityJourney();
            if (data && data.active !== false && data.id) {
                journeyData = data;
                renderOverview(container);
            } else {
                renderTrackSelection(container);
            }
        } catch (e) {
            console.error('Clarity load error:', e);
            renderTrackSelection(container);
        }
    }

    function unload() {
        journeyData = null;
    }

    // ── Track Selection ──

    async function renderTrackSelection(container) {
        let tracks = [];
        try {
            tracks = await API.getClarityTracks();
        } catch (e) {
            console.error('Failed to load tracks:', e);
        }

        container.innerHTML = `
            <div class="clarity-track-selection">
                <div class="clarity-header">
                    <h2>Clarity Journey</h2>
                    <p class="clarity-subtitle">Choose your 12-week coaching track</p>
                </div>
                <div class="clarity-tracks-grid">
                    ${tracks.map(t => `
                        <div class="clarity-track-card" data-track="${t.key}">
                            <div class="clarity-track-icon">${_trackIcon(t.key)}</div>
                            <h3>${t.name}</h3>
                            <p class="clarity-track-desc">${t.desc}</p>
                            <div class="clarity-track-score">
                                <span class="clarity-score-label">Current</span>
                                <span class="clarity-score-value">${t.current_score != null ? Math.round(t.current_score) : '--'}</span>
                            </div>
                            <div class="clarity-target-row">
                                <label>Target</label>
                                <input type="range" class="clarity-target-slider" min="30" max="95" value="${t.suggested_target}" data-track="${t.key}">
                                <span class="clarity-target-display">${t.suggested_target}</span>
                            </div>
                            <button class="clarity-begin-btn" data-track="${t.key}">Begin Journey</button>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;

        // Wire up sliders
        container.querySelectorAll('.clarity-target-slider').forEach(slider => {
            slider.addEventListener('input', (e) => {
                const display = e.target.closest('.clarity-track-card').querySelector('.clarity-target-display');
                display.textContent = e.target.value;
            });
        });

        // Wire up begin buttons
        container.querySelectorAll('.clarity-begin-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const track = e.target.dataset.track;
                const slider = container.querySelector(`.clarity-target-slider[data-track="${track}"]`);
                const target = parseInt(slider.value);
                btn.disabled = true;
                btn.textContent = 'Starting...';
                try {
                    journeyData = await API.startClarityJourney(track, target);
                    renderOverview(container);
                } catch (err) {
                    console.error('Start journey failed:', err);
                    btn.disabled = false;
                    btn.textContent = 'Begin Journey';
                }
            });
        });
    }

    // ── Overview (active journey) ──

    function renderOverview(container) {
        const d = journeyData;
        if (!d) return;

        const phaseName = d.phase ? d.phase.charAt(0).toUpperCase() + d.phase.slice(1) : '';
        const completionPct = d.completion ? Math.round((d.completion.overall_rate || 0) * 100) : 0;

        container.innerHTML = `
            <div class="clarity-overview">
                <div class="clarity-header">
                    <h2>${d.track_name} Journey</h2>
                    <p class="clarity-subtitle">${d.track_desc}</p>
                </div>

                <!-- Week strip -->
                <div class="clarity-week-strip">
                    ${_renderWeekStrip(d.current_week)}
                </div>

                <!-- Stats row -->
                <div class="clarity-stats-row">
                    <div class="clarity-stat">
                        <span class="clarity-stat-value">${d.current_week}</span>
                        <span class="clarity-stat-label">Week</span>
                    </div>
                    <div class="clarity-stat">
                        <span class="clarity-stat-value">${phaseName}</span>
                        <span class="clarity-stat-label">Phase</span>
                    </div>
                    <div class="clarity-stat">
                        <span class="clarity-stat-value">${d.current_score != null ? Math.round(d.current_score) : '--'}</span>
                        <span class="clarity-stat-label">Current</span>
                    </div>
                    <div class="clarity-stat">
                        <span class="clarity-stat-value">${Math.round(d.target_score)}</span>
                        <span class="clarity-stat-label">Target</span>
                    </div>
                    <div class="clarity-stat">
                        <span class="clarity-stat-value">${completionPct}%</span>
                        <span class="clarity-stat-label">Actions Done</span>
                    </div>
                </div>

                <!-- Today's action -->
                ${_renderActionCard(d.today_action)}

                <!-- Progress arc chart -->
                <div class="clarity-section">
                    <h3>Progress Arc</h3>
                    <div id="clarity-progress-chart" style="width:100%;height:300px;"></div>
                </div>

                <!-- Weekly check-in -->
                <div class="clarity-section">
                    <button class="clarity-checkin-btn" id="clarity-checkin-btn">Get Weekly Coach Check-in</button>
                    <div id="clarity-checkin-text" class="clarity-checkin-text"></div>
                </div>

                <!-- Abandon -->
                <div class="clarity-section clarity-abandon-section">
                    <button class="clarity-abandon-btn" id="clarity-abandon-btn">Abandon Journey</button>
                </div>
            </div>
        `;

        // Load progress arc chart
        _loadProgressArc();

        // Wire check-in button
        const checkinBtn = document.getElementById('clarity-checkin-btn');
        if (checkinBtn) {
            checkinBtn.addEventListener('click', async () => {
                checkinBtn.disabled = true;
                checkinBtn.textContent = 'Generating...';
                try {
                    const result = await API.triggerClarityWeeklyCheckin();
                    document.getElementById('clarity-checkin-text').textContent = result.checkin_text || '';
                } catch (e) {
                    document.getElementById('clarity-checkin-text').textContent = 'Check-in unavailable.';
                }
                checkinBtn.disabled = false;
                checkinBtn.textContent = 'Get Weekly Coach Check-in';
            });
        }

        // Wire action complete button
        const completeBtn = document.getElementById('clarity-action-complete');
        if (completeBtn) {
            completeBtn.addEventListener('click', async () => {
                const actionId = completeBtn.dataset.actionId;
                completeBtn.disabled = true;
                completeBtn.textContent = 'Done!';
                try {
                    await API.completeClarityAction(parseInt(actionId));
                    // Refresh
                    const updated = await API.getClarityJourney();
                    if (updated && updated.id) {
                        journeyData = updated;
                        renderOverview(container);
                    }
                } catch (e) {
                    console.error('Complete action failed:', e);
                }
            });
        }

        // Wire abandon button
        const abandonBtn = document.getElementById('clarity-abandon-btn');
        if (abandonBtn) {
            abandonBtn.addEventListener('click', async () => {
                if (!confirm('Are you sure you want to abandon your journey? This cannot be undone.')) return;
                try {
                    await API.abandonClarityJourney();
                    journeyData = null;
                    renderTrackSelection(container);
                } catch (e) {
                    console.error('Abandon failed:', e);
                }
            });
        }
    }

    // ── Helpers ──

    function _renderWeekStrip(currentWeek) {
        let html = '';
        for (let w = 1; w <= 12; w++) {
            const cls = w < currentWeek ? 'completed' : w === currentWeek ? 'current' : 'upcoming';
            html += `<div class="clarity-week-dot ${cls}" title="Week ${w}">${w}</div>`;
        }
        return html;
    }

    function _renderActionCard(action) {
        if (!action) {
            return `<div class="clarity-action-card clarity-action-empty">
                <p>No action scheduled for today</p>
            </div>`;
        }
        const completed = action.completed;
        return `
            <div class="clarity-action-card ${completed ? 'clarity-action-done' : ''}">
                <div class="clarity-action-type">${action.action_type}</div>
                <h3 class="clarity-action-title">${action.action_title}</h3>
                <p class="clarity-action-desc">${action.action_description || ''}</p>
                <div class="clarity-action-footer">
                    <span class="clarity-action-duration">${action.duration_min} min</span>
                    ${completed
                        ? '<span class="clarity-action-status">Completed</span>'
                        : `<button class="clarity-action-complete-btn" id="clarity-action-complete" data-action-id="${action.id}">Mark Complete</button>`
                    }
                </div>
            </div>
        `;
    }

    async function _loadProgressArc() {
        try {
            const data = await API.getClarityProgressArc();
            if (!data || !data.weeks || data.weeks.length === 0) return;

            const weeks = data.weeks.map(w => `W${w.week}`);
            const projected = data.weeks.map(w => w.projected);
            const actual = data.weeks.map(w => w.actual);

            const traces = [
                {
                    x: weeks,
                    y: projected,
                    type: 'scatter',
                    mode: 'lines',
                    name: 'Projected',
                    line: { color: '#e4e8ec', width: 2, dash: 'dash' },
                },
                {
                    x: weeks,
                    y: actual,
                    type: 'scatter',
                    mode: 'lines+markers',
                    name: 'Actual',
                    line: { color: '#8C96A0', width: 3 },
                    marker: { size: 8, color: '#8C96A0' },
                    connectgaps: false,
                },
            ];

            // Add milestone annotations
            const annotations = data.weeks
                .filter(w => w.milestone)
                .map(w => ({
                    x: `W${w.week}`,
                    y: w.projected,
                    text: w.milestone,
                    showarrow: true,
                    arrowhead: 0,
                    ax: 0,
                    ay: -30,
                    font: { size: 10, color: '#5a6270' },
                }));

            const layout = {
                paper_bgcolor: 'transparent',
                plot_bgcolor: 'transparent',
                margin: { t: 20, r: 20, b: 40, l: 50 },
                xaxis: { gridcolor: '#e4e8ec', tickfont: { color: '#5a6270', size: 11 } },
                yaxis: { gridcolor: '#e4e8ec', tickfont: { color: '#5a6270', size: 11 }, title: { text: 'Score', font: { color: '#5a6270', size: 12 } } },
                legend: { x: 0, y: 1.1, orientation: 'h', font: { color: '#5a6270', size: 11 } },
                annotations: annotations,
                font: { family: 'Inter, sans-serif' },
            };

            Plotly.newPlot('clarity-progress-chart', traces, layout, { displayModeBar: false, responsive: true });
        } catch (e) {
            console.error('Progress arc chart error:', e);
        }
    }

    function _trackIcon(track) {
        return '';
    }

    return { load, unload };
})();
