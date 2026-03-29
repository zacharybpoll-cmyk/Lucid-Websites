/**
 * Settings panel — notification prefs, quiet hours, adaptive timing,
 * export buttons, linguistic analysis toggle.
 */
(function () {
    'use strict';

    function setupSettings() {
        const settingsBtn = document.getElementById('settings-btn');
        const settingsPanel = document.getElementById('settings-panel');
        const closeBtn = document.getElementById('settings-close-btn');
        if (!settingsBtn || !settingsPanel || !closeBtn) return;

        settingsBtn.addEventListener('click', () => {
            settingsPanel.style.display = 'block';
            loadNotificationSettings();
            loadAdaptiveTiming();
            loadSpeakerStatus();
            // Load version into About section
            fetch(`${API_BASE}/version`).then(r => r.json()).then(d => {
                const el = document.getElementById('settings-version');
                if (el) el.textContent = 'v' + d.version;
            }).catch(() => {});
        });

        closeBtn.addEventListener('click', () => {
            settingsPanel.style.display = 'none';
        });

        // Wire speaker buttons eagerly (don't wait for async API call)
        const speakerSetupBtn = document.getElementById('speaker-setup-btn');
        const speakerDeleteBtn = document.getElementById('speaker-delete-btn');
        if (speakerSetupBtn) {
            speakerSetupBtn.addEventListener('click', () => startEnrollment());
        }
        const speakerEnhanceBtn = document.getElementById('speaker-enhance-btn');
        if (speakerEnhanceBtn) {
            speakerEnhanceBtn.addEventListener('click', () => openEnhanceOverlay());
        }
        if (speakerDeleteBtn) {
            speakerDeleteBtn.addEventListener('click', async () => {
                if (confirm('Delete your voice profile? Lucid will analyze all detected speech until you re-enroll.')) {
                    await API.deleteSpeakerProfile();
                    loadSpeakerStatus();
                }
            });
        }

        const exportReadingsBtn = document.getElementById('export-readings-btn');
        const exportSummariesBtn = document.getElementById('export-summaries-btn');
        const exportJsonBtn = document.getElementById('export-json-btn');

        if (exportReadingsBtn) {
            exportReadingsBtn.addEventListener('click', () => {
                const origText = exportReadingsBtn.textContent;
                exportReadingsBtn.textContent = 'Exporting...';
                exportReadingsBtn.disabled = true;
                window.location.href = `${API_BASE}/export/readings`;
                setTimeout(() => { exportReadingsBtn.textContent = origText; exportReadingsBtn.disabled = false; }, 3000);
            });
        }

        if (exportSummariesBtn) {
            exportSummariesBtn.addEventListener('click', () => {
                const origText = exportSummariesBtn.textContent;
                exportSummariesBtn.textContent = 'Exporting...';
                exportSummariesBtn.disabled = true;
                window.location.href = `${API_BASE}/export/summaries?days=30`;
                setTimeout(() => { exportSummariesBtn.textContent = origText; exportSummariesBtn.disabled = false; }, 3000);
            });
        }

        if (exportJsonBtn) {
            exportJsonBtn.addEventListener('click', async () => {
                const origText = exportJsonBtn.textContent;
                exportJsonBtn.textContent = 'Exporting...';
                exportJsonBtn.disabled = true;
                try {
                    const data = await API.exportJson(30);
                    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'lucid-export.json';
                    a.click();
                    URL.revokeObjectURL(url);
                } catch (e) {
                    console.error('JSON export failed:', e);
                } finally {
                    exportJsonBtn.textContent = origText;
                    exportJsonBtn.disabled = false;
                }
            });
        }

        const exportTherapistBtn = document.getElementById('export-therapist-btn');
        if (exportTherapistBtn) {
            exportTherapistBtn.addEventListener('click', async () => {
                const origText = exportTherapistBtn.textContent;
                exportTherapistBtn.textContent = 'Generating...';
                exportTherapistBtn.disabled = true;
                try {
                    const data = await API.getTherapistSummary(30);
                    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'lucid-therapist-summary.json';
                    a.click();
                    URL.revokeObjectURL(url);
                } catch (e) {
                    console.error('Therapist export failed:', e);
                } finally {
                    exportTherapistBtn.textContent = origText;
                    exportTherapistBtn.disabled = false;
                }
            });
        }

        // Enhanced linguistic analysis toggle
        loadLinguisticAnalysisSetting();
        const lingToggle = document.getElementById('linguistic-enhanced-toggle');
        if (lingToggle) {
            lingToggle.addEventListener('change', async () => {
                try {
                    await API.setLinguisticAnalysisSetting(lingToggle.checked);
                } catch (e) {
                    console.error('Failed to save linguistic setting:', e);
                }
            });
        }
    }

    async function loadLinguisticAnalysisSetting() {
        try {
            const data = await API.getLinguisticAnalysisSetting();
            const toggle = document.getElementById('linguistic-enhanced-toggle');
            if (toggle) toggle.checked = data.enabled !== false;
        } catch (e) {
            const toggle = document.getElementById('linguistic-enhanced-toggle');
            if (toggle) toggle.checked = true; // default ON
        }
    }

    async function loadNotificationSettings() {
        const container = document.getElementById('notification-settings');
        if (!container) return;

        try {
            const prefs = await API.getNotifPrefs();

            const types = [
                { key: 'notifications_enabled', label: 'Enable Notifications' },
                { key: 'notif_voice_weather', label: 'Voice Weather (Morning)' },
                { key: 'notif_curtain_call', label: 'Curtain Call (End of Day)' },
                { key: 'notif_transition', label: 'Zone Transitions' },
                { key: 'notif_threshold', label: 'Stress Alerts' },
                { key: 'notif_milestone', label: 'Milestones' },
                { key: 'notif_echo', label: 'Pattern Discoveries' },
                { key: 'notif_weekly_wrapped', label: 'Weekly Wrapped' },
            ];

            let html = '';
            for (const t of types) {
                const checked = (prefs[t.key] || 'true') === 'true' ? 'checked' : '';
                const isMaster = t.key === 'notifications_enabled';
                html += `<label class="notif-toggle ${isMaster ? 'notif-master' : ''}">
                    <input type="checkbox" ${checked} data-pref="${t.key}" onchange="toggleNotifPref(this)">
                    <span>${t.label}</span>
                </label>`;
            }

            const qStart = parseInt(prefs.quiet_start || 20);
            const qEnd = parseInt(prefs.quiet_end || 6);
            html += `<div class="notif-quiet-hours">
                <label>Quiet Hours:</label>
                <div class="quiet-hours-row">
                    <select id="quiet-start" onchange="saveQuietHours()">
                        ${buildHourOptions(qStart)}
                    </select>
                    <span>to</span>
                    <select id="quiet-end" onchange="saveQuietHours()">
                        ${buildHourOptions(qEnd)}
                    </select>
                </div>
            </div>`;

            container.innerHTML = html;
        } catch (e) {
            console.error('Failed to load notification settings:', e);
        }
    }

    async function toggleNotifPref(checkbox) {
        const key = checkbox.dataset.pref;
        const value = checkbox.checked ? 'true' : 'false';
        try {
            await API.setNotifPref(key, value);
        } catch (e) {
            console.error('Failed to save pref:', e);
        }
    }

    function buildHourOptions(selectedHour) {
        let html = '';
        for (let h = 0; h < 24; h++) {
            const ampm = h < 12 ? 'AM' : 'PM';
            const display = h === 0 ? 12 : h > 12 ? h - 12 : h;
            const label = `${display} ${ampm}`;
            const selected = h === selectedHour ? 'selected' : '';
            html += `<option value="${h}" ${selected}>${label}</option>`;
        }
        return html;
    }

    async function saveQuietHours() {
        const start = document.getElementById('quiet-start');
        const end = document.getElementById('quiet-end');
        if (start && end) {
            try {
                await Promise.all([
                    API.setNotifPref('quiet_start', start.value),
                    API.setNotifPref('quiet_end', end.value),
                ]);
            } catch (e) {
                console.error('Failed to save quiet hours:', e);
            }
        }
    }

    async function loadAdaptiveTiming() {
        try {
            const data = await API.getNotificationTiming();
            const toggle = document.getElementById('adaptive-timing-toggle');
            const heatmapContainer = document.getElementById('adaptive-heatmap');

            if (toggle) {
                toggle.checked = data.adaptive_enabled || false;
                toggle.onchange = async () => {
                    await API.setAdaptiveTiming(toggle.checked);
                    loadAdaptiveTiming();
                };
            }

            if (data.has_data && data.histogram && heatmapContainer) {
                heatmapContainer.style.display = 'block';
                renderAdaptiveHeatmap(data.histogram, data.peak_start, data.peak_end);

                const peakLabel = document.getElementById('adaptive-peak-label');
                if (peakLabel) {
                    peakLabel.textContent = `Peak window: ${data.peak_start}:00\u2013${data.peak_end}:00`;
                }
            }
        } catch (e) {
            console.error('Failed to load adaptive timing:', e);
        }
    }

    function renderAdaptiveHeatmap(histogram, peakStart, peakEnd) {
        const grid = document.getElementById('adaptive-heatmap-grid');
        if (!grid) return;

        const maxVal = Math.max(...histogram, 1);
        const hours = [];
        for (let h = 6; h <= 20; h++) {
            const val = histogram[h] || 0;
            const intensity = val / maxVal;
            const isPeak = h >= peakStart && h < peakEnd;
            hours.push(`<div class="heatmap-cell ${isPeak ? 'heatmap-peak' : ''}"
                style="opacity: ${0.15 + intensity * 0.85}"
                title="${h}:00 \u2014 ${val} opens">
                <span class="heatmap-hour">${h}</span>
            </div>`);
        }
        grid.innerHTML = hours.join('');
    }

    // Expose public API
    window.setupSettings = setupSettings;
    window.toggleNotifPref = toggleNotifPref;
    window.saveQuietHours = saveQuietHours;
    window.loadNotificationSettings = loadNotificationSettings;
    window.loadAdaptiveTiming = loadAdaptiveTiming;
})();
