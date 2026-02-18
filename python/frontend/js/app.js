/**
 * Main app logic
 * Handles view routing, data fetching, UI updates, and all 10 engagement features
 */

// State
let currentView = 'today';
let todayData = null;
let pollInterval = null;
let statusPollInterval = null;
let prevBufferedSec = 0;
const SPEECH_THRESHOLD_SEC = 30;

// Throttle timestamps
let lastBriefingUpdate = 0;
let lastEngagementUpdate = 0;
let lastFeatureUpdate = 0;

// Sanctuary debounce
let lastSanctuaryTime = 0;
const SANCTUARY_COOLDOWN = 300000; // 5 min

// Previous zone for transition detection
let previousZone = null;

// Canopy score reveal state
let canopyRevealed = false;

// First Spark state
let firstSparkLoaded = false;

// Beacon state
let lastBeaconZone = 'idle';

// Morning summary state
let morningSummaryShown = false;

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    console.log('Attune initialized');

    initGauges();
    initAnxietyTimeline();
    initTrendsView();
    initEngagementView();
    initCorrelationExplorer();
    initGrove();
    initLayout();

    setupNavigation();
    setupSettings();
    setupBriefingCards();
    setupInfoButtons();
    updateCurrentDate();

    waitForBackend();
});

// Wait for backend models to load (skeleton loading screen)
function waitForBackend() {
    const overlay = document.getElementById('loading-overlay');
    const statusEl = document.getElementById('loading-status');
    const progressBar = document.getElementById('skeleton-progress-bar');
    const timelineSweep = document.getElementById('skeleton-timeline-sweep');

    const ESTIMATED_POLLS = 6;
    let pollCount = 0;
    const statusMessages = [
        'Connecting to server...',
        'Loading voice models...',
        'Calibrating baseline...',
        'Preparing dashboard...',
        'Almost ready...'
    ];

    function updateProgress() {
        const pct = Math.min(95, (pollCount / ESTIMATED_POLLS) * 100);
        if (progressBar) progressBar.style.width = pct + '%';
        if (timelineSweep) timelineSweep.style.width = pct + '%';
        const msgIndex = Math.min(pollCount, statusMessages.length - 1);
        if (statusEl) statusEl.textContent = statusMessages[msgIndex];
    }

    function checkHealth() {
        API.getHealth()
            .then(data => {
                if (data.ready) {
                    // Complete the progress bar
                    if (progressBar) progressBar.style.width = '100%';
                    if (timelineSweep) timelineSweep.style.width = '100%';
                    if (statusEl) statusEl.textContent = 'Ready!';

                    // Fade out after a brief pause
                    setTimeout(() => {
                        overlay.classList.add('fade-out');
                        setTimeout(() => {
                            overlay.style.display = 'none';
                        }, 600);
                    }, 400);

                    startPolling();
                    loadTodayData();
                    loadFeatures();
                    if (shouldShowMorningSummary()) {
                        loadMorningSummary();
                    }
                } else {
                    pollCount++;
                    updateProgress();
                    setTimeout(checkHealth, 2000);
                }
            })
            .catch(() => {
                pollCount++;
                updateProgress();
                setTimeout(checkHealth, 2000);
            });
    }

    updateProgress();
    checkHealth();
}

// ========== Navigation ==========

function setupNavigation() {
    const sidebarIcons = document.querySelectorAll('.sidebar-icon[data-view]');
    sidebarIcons.forEach(icon => {
        icon.addEventListener('click', () => {
            switchView(icon.dataset.view);
        });
    });
}

function switchView(view) {
    document.querySelectorAll('.sidebar-icon[data-view]').forEach(icon => {
        icon.classList.toggle('active', icon.dataset.view === view);
    });

    document.querySelectorAll('.view').forEach(viewEl => {
        viewEl.classList.toggle('active', viewEl.id === `${view}-view`);
    });

    currentView = view;

    if (view === 'trends' && typeof trendsView !== 'undefined' && trendsView) {
        trendsView.load(14);
    } else if (view === 'history' && typeof correlationExplorer !== 'undefined' && correlationExplorer) {
        correlationExplorer.load(30);
        loadHeatmapData();
    } else if (view === 'waypoints') {
        loadWaypoints();
    }
}

function updateCurrentDate() {
    const dateEl = document.getElementById('current-date');
    const now = new Date();
    const options = { weekday: 'short', month: 'short', day: 'numeric' };
    dateEl.textContent = now.toLocaleDateString('en-US', options);
}

// ========== Polling ==========

function startPolling() {
    pollInterval = setInterval(() => {
        if (currentView === 'today') {
            loadTodayData();
        }
    }, 5000);

    pollStatus();
    statusPollInterval = setInterval(pollStatus, 2000);
}

async function pollStatus() {
    try {
        const status = await API.getStatus();
        updateMicIndicator(status);
        updateSpeakerDebug(status);
    } catch (e) {
        updateMicIndicator(null);
    }
}

// ========== Speaker Gate Debug Overlay ==========

function updateSpeakerDebug(status) {
    const panel = document.getElementById('speaker-debug');
    if (!panel || panel.style.display === 'none') return;

    const stats = status && status.speaker_gate_stats;
    if (!stats) {
        document.getElementById('speaker-debug-stats').textContent = 'No gate stats available';
        return;
    }

    const passRate = typeof stats.pass_rate === 'number' ? stats.pass_rate.toFixed(0) : '—';
    const sandwich = stats.segments_sandwich_recovered || 0;
    const momentumTag = stats.momentum_active ? ' <span style="color:#5B8DB8;">[momentum]</span>' : '';
    const thresholdDisplay = stats.momentum_active ? '0.30' : '0.35';
    document.getElementById('speaker-debug-stats').innerHTML =
        `Pass rate: <strong style="color:#fff">${passRate}%</strong> &nbsp;|&nbsp; ` +
        `✓ ${stats.segments_verified} verified &nbsp;|&nbsp; ✗ ${stats.segments_rejected} rejected` +
        (sandwich > 0 ? ` &nbsp;|&nbsp; 🥪 ${sandwich} recovered` : '') +
        momentumTag +
        (stats.last_similarity != null ? `<br>Last similarity: ${Number(stats.last_similarity).toFixed(3)} (threshold: ${thresholdDisplay})` : '');

    const events = stats.recent_events || [];
    const logEl = document.getElementById('speaker-debug-log');
    if (events.length === 0) {
        logEl.innerHTML = '<div style="opacity:0.5;margin-top:6px;">No segments yet — speak for ~1.2s</div>';
        return;
    }
    logEl.innerHTML = [...events].reverse().map(e => {
        let label = e.verified ? '✓ pass' : '✗ reject';
        if (e.sandwich_recovered) label = '🥪 recovered';
        if (e.momentum) label += ' [M]';
        return `<div class="gate-event ${e.verified ? 'gate-pass' : 'gate-fail'}">` +
            `${e.time} &nbsp;${e.duration}s &nbsp;sim:${e.similarity} &nbsp;${label}` +
            `</div>`;
    }).join('');
}

// Toggle debug overlay with Cmd+Shift+D
document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.code === 'KeyD') {
        e.preventDefault();
        const panel = document.getElementById('speaker-debug');
        if (panel) panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    }
});

document.addEventListener('DOMContentLoaded', () => {
    const closeBtn = document.getElementById('speaker-debug-close');
    if (closeBtn) closeBtn.addEventListener('click', () => {
        document.getElementById('speaker-debug').style.display = 'none';
    });
});

// Track whether we've auto-prompted enrollment
let enrollmentAutoPrompted = false;

function updateMicIndicator(status) {
    const dot = document.getElementById('mic-dot');
    const label = document.getElementById('mic-label');
    const seconds = document.getElementById('mic-seconds');
    const bar = document.getElementById('mic-progress-bar');
    const enrollBanner = document.getElementById('enrollment-required-banner');

    if (!status) {
        dot.className = 'mic-dot idle';
        label.textContent = 'Connecting...';
        if (seconds) seconds.textContent = '';
        if (bar) bar.style.width = '0%';
        return;
    }

    // Show/hide enrollment-required banner
    if (status.enrollment_required && !status.speaker_enrolled) {
        if (enrollBanner) enrollBanner.style.display = 'block';
        dot.className = 'mic-dot idle';
        label.textContent = 'Voice profile needed';
        if (seconds) seconds.textContent = '';
        if (bar) bar.style.width = '0%';
        prevBufferedSec = 0;

        // Auto-prompt enrollment on first detection (once per session)
        if (!enrollmentAutoPrompted) {
            enrollmentAutoPrompted = true;
            setTimeout(() => startEnrollment(), 1500);
        }
        return;
    } else {
        if (enrollBanner) enrollBanner.style.display = 'none';
    }

    const buffered = status.buffered_speech_sec || 0;
    const pct = Math.min(100, (buffered / SPEECH_THRESHOLD_SEC) * 100);

    if (seconds) seconds.textContent = `${Math.round(buffered)}s / ${SPEECH_THRESHOLD_SEC}s`;
    if (bar) bar.style.width = pct + '%';

    if (status.is_paused) {
        dot.className = 'mic-dot paused';
        label.textContent = 'Paused';
    } else if (!status.is_running) {
        dot.className = 'mic-dot idle';
        label.textContent = 'Not running';
    } else if (buffered < prevBufferedSec && prevBufferedSec > 5) {
        dot.className = 'mic-dot analyzing';
        label.textContent = 'Analyzing...';
    } else if (buffered > 0 && buffered > prevBufferedSec) {
        dot.className = 'mic-dot hearing';
        label.textContent = 'Hearing speech...';
    } else if (buffered >= SPEECH_THRESHOLD_SEC) {
        dot.className = 'mic-dot analyzing';
        label.textContent = 'Analyzing...';
    } else if (buffered > 0) {
        dot.className = 'mic-dot hearing';
        label.textContent = 'Speech buffered';
    } else {
        dot.className = 'mic-dot idle';
        label.textContent = 'Listening...';
    }

    prevBufferedSec = buffered;
}

// ========== Load Today's Data ==========

async function loadTodayData() {
    try {
        const data = await API.getToday();
        todayData = data;

        updateCurrentScores(data.current_scores, data.readings);
        updateScoreCircles(data.current_scores);
        updateZoneBar(data.readings);
        updateAnxietyTimeline(data.readings);
        updateZoneSummary(data.summary);
        updateMeetings(data.readings);
        updateCalibrationBanner(data.calibration_status);
        loadCanopyScore();

        // Detect zone transitions for Sanctuary Moments
        if (data.readings && data.readings.length > 0) {
            const currentZone = data.readings[0].zone;
            if (previousZone === 'stressed' && (currentZone === 'calm' || currentZone === 'steady')) {
                triggerSanctuary('calm_shift', 'You found your calm');
            } else if (previousZone === 'tense' && currentZone === 'calm') {
                triggerSanctuary('calm_shift', 'Tension released. Well done.');
            }
            previousZone = currentZone;

            // First reading of the day
            if (data.readings.length === 1 && !canopyRevealed) {
                triggerSanctuary('first_reading', 'Your voice has been heard');
            }
        }

        // Throttle expensive updates
        const now = Date.now();
        if (now - lastBriefingUpdate > 300000) {
            lastBriefingUpdate = now;
            updateBriefings();
        }
        if (now - lastEngagementUpdate > 60000) {
            lastEngagementUpdate = now;
            updateEngagement();
        }
        if (now - lastFeatureUpdate > 30000) {
            lastFeatureUpdate = now;
            loadFeatures();
        }

    } catch (error) {
        console.error('Error loading today data:', error);
    }
}

// ========== Load All New Features ==========

async function loadFeatures() {
    // Load features in parallel
    Promise.allSettled([
        loadRhythmRings(),
        loadEchoes(),
        loadCompass(),
        loadCapsules(),
        updateGrove(),
        loadFirstSpark(),
        loadWeeklyWrapped(),
        pollBeacon(),
    ]);
}

// ========== Canopy Score (Feature #1) ==========

async function loadCanopyScore() {
    try {
        const data = await API.getCanopy();
        const scoreEl = document.getElementById('canopy-score');
        const profileEl = document.getElementById('canopy-profile');
        const progressState = document.getElementById('canopy-progress-state');
        const progressBar = document.getElementById('canopy-progress-bar');
        const readingCountEl = document.getElementById('canopy-reading-count');

        if (!data.has_data) {
            // Show progress state
            const count = data.reading_count || 0;
            if (progressState) progressState.style.display = 'flex';
            if (scoreEl) scoreEl.style.display = 'none';
            if (progressBar) progressBar.style.width = ((count / 3) * 100) + '%';
            if (readingCountEl) readingCountEl.textContent = `${count} of 3 readings`;
            if (profileEl) profileEl.textContent = '';
            canopyRevealed = false; // Reset so animation fires on score unlock
        } else {
            // Show score
            if (progressState) progressState.style.display = 'none';
            if (scoreEl) scoreEl.style.display = '';

            if (!canopyRevealed) {
                canopyRevealed = true;
                animateCountUp(scoreEl, data.score, 3000);
                if (profileEl) profileEl.textContent = data.profile || '';
            } else {
                if (scoreEl) scoreEl.textContent = data.score;
                if (profileEl) profileEl.textContent = data.profile || '';
            }
        }
    } catch (e) {
        console.error('Failed to load canopy score:', e);
    }
}

function animateCountUp(el, target, duration) {
    const start = 0;
    const startTime = performance.now();

    function tick(now) {
        const elapsed = now - startTime;
        const progress = Math.min(elapsed / duration, 1);
        // Ease out cubic
        const eased = 1 - Math.pow(1 - progress, 3);
        const current = Math.round(start + (target - start) * eased);
        el.textContent = current;

        if (progress < 1) {
            requestAnimationFrame(tick);
        } else {
            el.textContent = target;
            // Add leaf particles
            addLeafParticles(el.parentElement);
        }
    }

    requestAnimationFrame(tick);
}

function addLeafParticles(container) {
    if (!container) return;
    for (let i = 0; i < 6; i++) {
        const leaf = document.createElement('span');
        leaf.className = 'leaf-particle';
        leaf.style.left = (20 + Math.random() * 60) + '%';
        leaf.style.animationDelay = (Math.random() * 1.5) + 's';
        container.appendChild(leaf);
        setTimeout(() => leaf.remove(), 3000);
    }
}

// ========== Rhythm Rings (Feature #5) ==========

async function loadRhythmRings() {
    try {
        const data = await API.getRings();

        // Update ring SVGs
        updateRing('ring-speak', data.speak.pct, 565.5);
        updateRing('ring-calm', data.calm.pct, 452.4);
        updateRing('ring-checkin', data.checkin.pct, 339.3);

        // Update labels
        const speakLabel = document.getElementById('ring-speak-label');
        const calmLabel = document.getElementById('ring-calm-label');
        const checkinLabel = document.getElementById('ring-checkin-label');

        if (speakLabel) speakLabel.textContent = `Speak: ${data.speak.current}/${data.speak.target} min`;
        if (calmLabel) calmLabel.textContent = `Calm: ${data.calm.current}/${data.calm.target} min`;
        if (checkinLabel) checkinLabel.textContent = `Check-in: ${data.checkin.current}/${data.checkin.target}`;

        // All rings closed celebration
        if (data.all_closed) {
            triggerSanctuary('rings_closed', 'All rings closed! Outstanding.');
        }
    } catch (e) {
        console.error('Failed to load rings:', e);
    }
}

function updateRing(id, pct, circumference) {
    const ring = document.getElementById(id);
    if (!ring) return;
    const offset = circumference - (Math.min(100, pct) / 100) * circumference;
    ring.style.transition = 'stroke-dashoffset 0.8s ease';
    ring.setAttribute('stroke-dashoffset', offset);
}

// ========== Echoes (Feature #6) ==========

async function loadEchoes() {
    try {
        const data = await API.getEchoes();
        const container = document.getElementById('echoes-container');
        const dotWrap = document.getElementById('echo-dot-wrap');

        // Show notification dot if unseen echoes
        if (dotWrap) {
            dotWrap.style.display = data.unseen_count > 0 ? 'flex' : 'none';
        }

        if (!container) return;

        if (!data.echoes || data.echoes.length === 0) {
            container.innerHTML = '<div class="echoes-empty">Patterns will appear after 7+ days of data</div>';
            return;
        }

        let html = '';

        for (const echo of data.echoes.slice(0, 5)) {
            const dateStr = new Date(echo.discovered_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
            html += `
                <div class="echo-item ${echo.seen ? '' : 'echo-new'}">
                    <span class="echo-icon">\u{2728}</span>
                    <div class="echo-content">
                        <span class="echo-message">${echo.message}</span>
                        <span class="echo-date">${dateStr}</span>
                    </div>
                </div>`;
        }

        container.innerHTML = html;
    } catch (e) {
        console.error('Failed to load echoes:', e);
    }
}

// ========== Compass (Feature #7) ==========

async function loadCompass() {
    try {
        const data = await API.getCompass();
        const container = document.getElementById('compass-container');
        if (!container) return;

        if (!data.has_data) {
            container.innerHTML = '<div class="compass-empty">Weekly direction updates on Mondays</div>';
            return;
        }

        const arrows = { ascending: '\u2191', holding: '\u2192', descending: '\u2193' };
        const colors = { ascending: 'var(--calm-color)', holding: 'var(--gold)', descending: 'var(--tense-color)' };
        const labels = { ascending: 'Ascending', holding: 'Holding Steady', descending: 'Descending' };

        let html = `
            <div class="compass-direction">
                <span class="compass-arrow" style="color: ${colors[data.direction]}">${arrows[data.direction]}</span>
                <span class="compass-label" style="color: ${colors[data.direction]}">${labels[data.direction]}</span>
            </div>`;

        if (data.biggest_positive) {
            html += `<div class="compass-change compass-positive">+ ${data.biggest_positive}</div>`;
        }
        if (data.biggest_negative) {
            html += `<div class="compass-change compass-negative">- ${data.biggest_negative}</div>`;
        }

        // Intention input
        html += `<div class="compass-intention">
            <label class="compass-intention-label">This week's intention:</label>
            <div class="compass-intention-row">
                <input type="text" class="compass-intention-input" id="compass-intention-input"
                    placeholder="e.g., Take a 5-min break after meetings"
                    value="${data.intention || ''}" maxlength="120" />
                <button class="btn btn-primary compass-intention-btn" onclick="saveIntention()">Set</button>
            </div>
        </div>`;

        container.innerHTML = html;
    } catch (e) {
        console.error('Failed to load compass:', e);
    }
}

async function saveIntention() {
    const input = document.getElementById('compass-intention-input');
    if (!input || !input.value.trim()) return;
    try {
        await API.setIntention(input.value.trim());
        triggerSanctuary('intention', 'Intention set. Stay committed.');
    } catch (e) {
        console.error('Failed to save intention:', e);
    }
}

// ========== Time Capsule (Feature #9) ==========

async function loadCapsules() {
    try {
        const data = await API.getCapsules();
        const container = document.getElementById('capsules-container');
        const section = document.getElementById('capsules-section');

        if (!data.capsules || data.capsules.length === 0) {
            if (section) section.style.display = 'none';
            return;
        }

        if (section) section.style.display = 'block';
        if (!container) return;

        let html = '';
        for (const capsule of data.capsules.slice(0, 3)) {
            html += `
                <div class="capsule-item">
                    <span class="capsule-icon">\u{1F4E6}</span>
                    <span class="capsule-message">${capsule.message}</span>
                </div>`;
        }

        container.innerHTML = html;
    } catch (e) {
        console.error('Failed to load capsules:', e);
    }
}

// ========== Waypoints (Feature #4) — in History view ==========

async function loadWaypoints() {
    try {
        const data = await API.getWaypoints();
        const waypointsView = document.getElementById('waypoints-view');
        if (!waypointsView) return;

        let waypointsContainer = document.getElementById('waypoints-container');

        if (!waypointsContainer) {
            waypointsView.innerHTML = `
                <div class="waypoints-section">
                    <h3 class="section-label" style="margin-top: 24px;">WAYPOINTS</h3>
                    <div class="waypoints-progress-bar">
                        <div class="waypoints-progress-fill" id="waypoints-progress-fill" style="width: 0%"></div>
                    </div>
                    <span class="waypoints-progress-label" id="waypoints-progress-label"></span>
                    <div id="waypoints-container" class="waypoints-trail"></div>
                </div>`;
            waypointsContainer = document.getElementById('waypoints-container');
        }

        // Progress bar
        const fill = document.getElementById('waypoints-progress-fill');
        const label = document.getElementById('waypoints-progress-label');
        if (fill) fill.style.width = data.progress_pct + '%';
        if (label) label.textContent = `${data.achieved}/${data.total} waypoints (${data.progress_pct}%)`;

        // Render tiers
        const tiers = ['Seedling', 'Sapling', 'Young Tree', 'Mature Tree', 'Old Growth', 'Ancient'];
        let html = '';

        for (const tier of tiers) {
            const wps = data.by_tier[tier] || [];
            html += `<div class="waypoint-tier">
                <div class="waypoint-tier-name">${tier}</div>
                <div class="waypoint-tier-items">`;

            for (const wp of wps) {
                const cls = wp.achieved ? 'waypoint-item achieved' : 'waypoint-item locked';
                html += `<div class="${cls}" title="${wp.description}">
                    <div class="waypoint-dot">${wp.achieved ? '\u2713' : '\u25CB'}</div>
                    <span class="waypoint-name">${wp.name}</span>
                </div>`;
            }

            html += '</div></div>';
        }

        waypointsContainer.innerHTML = html;
    } catch (e) {
        console.error('Failed to load waypoints:', e);
    }
}

// ========== Sanctuary Moments (Feature #8) ==========

function triggerSanctuary(type, message) {
    const now = Date.now();
    if (now - lastSanctuaryTime < SANCTUARY_COOLDOWN) return; // 5 min debounce
    lastSanctuaryTime = now;

    const overlay = document.getElementById('sanctuary-overlay');
    const msgEl = document.getElementById('sanctuary-message');
    const particles = document.getElementById('sanctuary-particles');

    if (!overlay || !msgEl) return;

    msgEl.textContent = message;
    overlay.style.display = 'flex';
    overlay.classList.add('sanctuary-active');

    // Add leaf particles
    if (particles) {
        particles.innerHTML = '';
        for (let i = 0; i < 12; i++) {
            const leaf = document.createElement('span');
            leaf.className = 'sanctuary-leaf';
            leaf.style.left = Math.random() * 100 + '%';
            leaf.style.animationDelay = Math.random() * 2 + 's';
            leaf.style.animationDuration = (2 + Math.random() * 2) + 's';
            particles.appendChild(leaf);
        }
    }

    // Auto-dismiss after 3 seconds
    setTimeout(() => {
        overlay.classList.remove('sanctuary-active');
        overlay.style.display = 'none';
        if (particles) particles.innerHTML = '';
    }, 3000);
}

// ========== Load Heatmap Data ==========

async function loadHeatmapData() {
    try {
        const summaries = await API.getSummaries(35);
        updateHeatmapCalendar(summaries, 'history-heatmap-calendar');
    } catch (e) {
        console.error('Error loading heatmap data:', e);
    }
}

// ========== Score Updates ==========

function updateCurrentScores(scores, readings) {
    let zone = 'steady';
    if (readings && readings.length > 0) {
        zone = readings[0].zone || 'steady';
    }

    if (scores.depression === undefined || scores.depression === null) {
        let depressionRaw = 0;
        if (readings && readings.length > 0) {
            depressionRaw = readings[0].depression_raw || 0;
        }
        scores.depression = Math.min(100, Math.max(0, depressionRaw / 27 * 100));
    }

    updateGauges(scores, zone);
}

function updateZoneSummary(summary) {
    if (!summary) {
        document.getElementById('calm-time').textContent = '0 min';
        document.getElementById('steady-time').textContent = '0 min';
        document.getElementById('tense-time').textContent = '0 min';
        document.getElementById('stressed-time').textContent = '0 min';
        return;
    }

    document.getElementById('calm-time').textContent = `${Math.round(summary.time_in_calm_min || 0)} min`;
    document.getElementById('steady-time').textContent = `${Math.round(summary.time_in_steady_min || 0)} min`;
    document.getElementById('tense-time').textContent = `${Math.round(summary.time_in_tense_min || 0)} min`;
    document.getElementById('stressed-time').textContent = `${Math.round(summary.time_in_stressed_min || 0)} min`;
}

function updateMeetings(readings) {
    const meetingsSection = document.querySelector('.meetings-section');
    if (!readings || readings.length === 0) {
        if (meetingsSection) meetingsSection.style.display = 'none';
        return;
    }

    const meetingReadings = readings.filter(r => r.meeting_detected === 1);
    if (meetingReadings.length === 0) {
        if (meetingsSection) meetingsSection.style.display = 'none';
        return;
    }

    if (meetingsSection) meetingsSection.style.display = 'block';

    const meetings = [];
    let currentMeeting = null;

    meetingReadings.forEach(reading => {
        if (!currentMeeting) {
            currentMeeting = { start: reading.timestamp, end: reading.timestamp, readings: [reading] };
        } else {
            const lastTime = new Date(currentMeeting.end);
            const currentTime = new Date(reading.timestamp);
            const diffMinutes = (currentTime - lastTime) / (1000 * 60);

            if (diffMinutes < 10) {
                currentMeeting.end = reading.timestamp;
                currentMeeting.readings.push(reading);
            } else {
                meetings.push(currentMeeting);
                currentMeeting = { start: reading.timestamp, end: reading.timestamp, readings: [reading] };
            }
        }
    });

    if (currentMeeting) meetings.push(currentMeeting);

    document.getElementById('meeting-count').textContent = meetings.length;

    const listHtml = meetings.map((meeting, idx) => {
        const startTime = new Date(meeting.start).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: false });
        const endTime = new Date(meeting.end).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: false });
        return `<div class="meeting-item"><span class="meeting-time">${startTime} - ${endTime}</span><span class="meeting-label">Meeting ${idx + 1}</span></div>`;
    }).join('');

    document.getElementById('meetings-list').innerHTML = listHtml;
}

function updateCalibrationBanner(status) {
    const banner = document.getElementById('calibration-banner');
    const progress = document.getElementById('calibration-progress');

    if (!status || status.is_calibrated) {
        banner.style.display = 'none';
        return;
    }

    // If First Spark journey card is showing, hide the old calibration banner
    const journeyCard = document.getElementById('first-spark-card');
    if (journeyCard && journeyCard.style.display !== 'none') {
        banner.style.display = 'none';
        return;
    }

    banner.style.display = 'block';
    progress.textContent = `${status.total_readings || 0} readings collected (need ${status.min_readings || 10} minimum)`;
}

// ========== Briefings ==========

async function updateBriefings(force = false) {
    const now = new Date();
    const hour = now.getHours();

    if (hour >= 6) {
        try {
            const response = await API.getBriefing('morning', force);
            displayBriefing('morning', response);
        } catch (e) {
            console.error('Failed to load morning briefing:', e);
        }
    }
}

function displayBriefing(type, response) {
    const card = document.getElementById(`briefing-${type}`);
    if (!card) return;

    card.style.display = 'block';

    const legacyEl = card.querySelector('.briefing-legacy');
    const structuredEl = card.querySelector('.briefing-structured');
    const nodataEl = card.querySelector('.briefing-nodata');

    if (legacyEl) legacyEl.style.display = 'none';
    if (structuredEl) structuredEl.style.display = 'none';
    if (nodataEl) nodataEl.style.display = 'none';

    if (response.data && typeof response.data === 'object') {
        const data = response.data;
        if (data.has_data === false) {
            if (nodataEl) {
                nodataEl.style.display = 'block';
                nodataEl.textContent = data.message || 'No data available for yesterday.';
            }
        } else {
            if (structuredEl) {
                structuredEl.style.display = 'block';
                renderStructuredBriefing(card, data);
            }
        }
    } else if (response.content) {
        if (legacyEl) {
            legacyEl.style.display = 'block';
            legacyEl.textContent = response.content;
        }
    }
}

function renderStructuredBriefing(card, data) {
    const scoreNum = card.querySelector('.briefing-score-number');
    const scoreLbl = card.querySelector('.briefing-score-label');
    const scoreBadge = card.querySelector('.briefing-score-badge');
    const scoreDate = card.querySelector('.briefing-score-date');

    if (scoreNum) scoreNum.textContent = data.overall_score;
    if (scoreLbl) scoreLbl.textContent = data.score_label;
    if (scoreDate) {
        const d = new Date(data.date + 'T12:00:00');
        scoreDate.textContent = d.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });
    }

    if (scoreBadge) {
        scoreBadge.className = 'briefing-score-badge';
        const cls = data.score_label.toLowerCase().replace(/\s+/g, '-');
        scoreBadge.classList.add(`score-${cls}`);
    }

    const metricsGrid = card.querySelector('.briefing-metrics-grid');
    if (metricsGrid && data.metrics) {
        let html = '';
        const order = ['avg_stress', 'avg_mood', 'avg_energy', 'avg_calm', 'peak_stress', 'avg_depression', 'avg_anxiety'];
        for (const key of order) {
            const m = data.metrics[key];
            if (!m) continue;
            const pct = Math.min(100, (m.value / m.max) * 100);
            const barClass = key.includes('stress') || key.includes('depression') || key.includes('anxiety')
                ? 'bar-negative' : 'bar-positive';
            html += `
                <div class="briefing-metric-item">
                    <div class="metric-label-row">
                        <span class="metric-name">${m.label}</span>
                        <span class="metric-value">${m.value}/${m.max}</span>
                    </div>
                    <div class="metric-bar-track">
                        <div class="metric-bar-fill ${barClass}" style="width: ${pct}%"></div>
                    </div>
                    <span class="metric-interpretation">${m.interpretation}</span>
                </div>`;
        }
        metricsGrid.innerHTML = html;
    }

    const zoneBar = card.querySelector('.briefing-zone-bar');
    const zoneLegend = card.querySelector('.briefing-zone-legend');
    if (zoneBar && data.zones) {
        const zoneColors = { calm: '#5a9a6e', steady: '#b5a84a', tense: '#d4943a', stressed: '#c4584c' };
        const zoneLabels = { calm: 'Calm', steady: 'Steady', tense: 'Tense', stressed: 'Stressed' };
        let barHtml = '';
        let legendHtml = '';
        for (const z of ['calm', 'steady', 'tense', 'stressed']) {
            const info = data.zones[z];
            if (!info || info.pct === 0) continue;
            barHtml += `<div class="zone-segment" style="width: ${info.pct}%; background: ${zoneColors[z]};" title="${zoneLabels[z]}: ${info.minutes} min (${info.pct}%)"></div>`;
            legendHtml += `<span class="zone-legend-item"><span class="zone-dot" style="background: ${zoneColors[z]};"></span>${zoneLabels[z]} ${info.minutes}m (${info.pct}%)</span>`;
        }
        zoneBar.innerHTML = barHtml;
        zoneLegend.innerHTML = legendHtml;
    }

    const activityEl = card.querySelector('.briefing-activity');
    if (activityEl && data.activity) {
        const a = data.activity;
        activityEl.innerHTML = `
            <div class="activity-stat"><strong>${a.total_readings}</strong><span>Readings</span></div>
            <div class="activity-stat"><strong>${a.first_reading}</strong><span>First</span></div>
            <div class="activity-stat"><strong>${a.last_reading}</strong><span>Last</span></div>
            <div class="activity-stat"><strong>${a.active_hours}h</strong><span>Active</span></div>
            <div class="activity-stat"><strong>${a.total_speech_min}m</strong><span>Speech</span></div>`;
    }

    const highlightsList = card.querySelector('.briefing-highlights-list');
    if (highlightsList && data.highlights) {
        highlightsList.innerHTML = data.highlights.map(h => `<li>${h}</li>`).join('');
    }

    const coachText = card.querySelector('.briefing-coach-text');
    if (coachText && data.coach_note) {
        coachText.textContent = data.coach_note;
    }
}

function setupBriefingCards() {
    document.querySelectorAll('.briefing-card').forEach(card => {
        const toggle = card.querySelector('.briefing-toggle');
        const body = card.querySelector('.briefing-body');

        if (toggle && body) {
            toggle.addEventListener('click', (e) => {
                e.stopPropagation();
                const isExpanded = body.classList.contains('briefing-expanded');
                body.classList.toggle('briefing-expanded', !isExpanded);
                toggle.innerHTML = isExpanded ? '&#9660;' : '&#9650;';
            });
        }
    });
}

// ========== Info Buttons ==========

function setupInfoButtons() {
    // Toggle popover on info button click
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.info-btn');
        if (btn) {
            e.stopPropagation();
            const popover = btn.nextElementSibling;
            if (!popover || !popover.classList.contains('info-popover')) return;

            // Close any other open popovers first
            document.querySelectorAll('.info-popover.visible').forEach(p => {
                if (p !== popover) p.classList.remove('visible');
            });

            popover.classList.toggle('visible');
            return;
        }

        // Click outside dismisses all popovers
        if (!e.target.closest('.info-popover')) {
            document.querySelectorAll('.info-popover.visible').forEach(p => {
                p.classList.remove('visible');
            });
        }
    });
}

// ========== Settings Panel ==========

function setupSettings() {
    const settingsBtn = document.getElementById('settings-btn');
    const settingsPanel = document.getElementById('settings-panel');
    const closeBtn = document.getElementById('settings-close-btn');

    settingsBtn.addEventListener('click', () => {
        settingsPanel.style.display = 'block';
        loadNotificationSettings();
        loadSpeakerStatus();
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
    if (speakerDeleteBtn) {
        speakerDeleteBtn.addEventListener('click', async () => {
            if (confirm('Delete your voice profile? Attune will analyze all detected speech until you re-enroll.')) {
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
            window.location.href = `${API_BASE}/export/readings`;
        });
    }

    if (exportSummariesBtn) {
        exportSummariesBtn.addEventListener('click', () => {
            window.location.href = `${API_BASE}/export/summaries?days=30`;
        });
    }

    if (exportJsonBtn) {
        exportJsonBtn.addEventListener('click', async () => {
            try {
                const data = await API.exportJson(30);
                const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'attune-export.json';
                a.click();
                URL.revokeObjectURL(url);
            } catch (e) {
                console.error('JSON export failed:', e);
            }
        });
    }
}

// ========== First Spark — Instant Value from Reading #1 ==========

async function loadFirstSpark() {
    if (firstSparkLoaded) return;

    try {
        const data = await API.getFirstSpark();
        const card = document.getElementById('first-spark-card');
        if (!card) return;

        if (!data.show_journey) {
            card.style.display = 'none';
            firstSparkLoaded = true;
            return;
        }

        card.style.display = 'block';

        const content = card.querySelector('.first-spark-content');
        if (!content) return;

        let html = '';

        if (data.narrative) {
            html += `<p class="spark-narrative">${data.narrative}</p>`;
            if (data.percentile_text) {
                html += `<div class="spark-percentile">${data.percentile_text}</div>`;
            }
        }

        // Progressive unlock preview
        if (data.unlocks) {
            html += '<div class="spark-unlocks">';
            for (const u of data.unlocks) {
                const achieved = data.unlocked && data.unlocked[u.label.toLowerCase().replace(/\s+/g, '_')];
                const dayLabel = `Day ${u.day}`;
                const cls = (data.days_active >= u.day) ? 'spark-unlock achieved' : 'spark-unlock locked';
                html += `<div class="${cls}">
                    <span class="spark-day">${dayLabel}</span>
                    <span class="spark-unlock-label">${u.label}</span>
                    <span class="spark-unlock-desc">${u.desc}</span>
                </div>`;
            }
            html += '</div>';
        }

        if (!data.has_readings) {
            html = '<p class="spark-narrative">Start speaking and we\'ll capture your first voice reading. Your wellness journey begins with one sentence.</p>';
        }

        content.innerHTML = html;
    } catch (e) {
        console.error('Failed to load First Spark:', e);
    }
}

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

        const trendIcon = data.canopy.trend > 0 ? '\u2191' : data.canopy.trend < 0 ? '\u2193' : '\u2192';
        const trendColor = data.canopy.trend > 0 ? 'var(--calm-color)' : data.canopy.trend < 0 ? 'var(--stressed-color)' : 'var(--gold)';

        let html = `
            <div class="wrapped-summary-line">${data.summary_line}</div>
            <div class="wrapped-canopy">
                <span class="wrapped-canopy-score">${data.canopy.avg}</span>
                <span class="wrapped-canopy-label">Avg Canopy</span>
                <span class="wrapped-canopy-trend" style="color: ${trendColor}">${trendIcon} ${data.canopy.trend > 0 ? '+' : ''}${data.canopy.trend}</span>
            </div>
            <div class="wrapped-days">
                <div class="wrapped-day-stat wrapped-best">
                    <span class="wrapped-day-label">Calmest</span>
                    <span class="wrapped-day-name">${data.best_day.label}</span>
                    <span class="wrapped-day-val">Stress ${data.best_day.stress}</span>
                </div>
                <div class="wrapped-day-stat wrapped-worst">
                    <span class="wrapped-day-label">Toughest</span>
                    <span class="wrapped-day-name">${data.worst_day.label}</span>
                    <span class="wrapped-day-val">Stress ${data.worst_day.stress}</span>
                </div>
            </div>
            <div class="wrapped-zones">`;

        const zoneColors = { calm: '#5a9a6e', steady: '#b5a84a', tense: '#d4943a', stressed: '#c4584c' };
        for (const z of ['calm', 'steady', 'tense', 'stressed']) {
            const info = data.zones[z];
            if (info && info.pct > 0) {
                html += `<div class="wrapped-zone-bar" style="width: ${info.pct}%; background: ${zoneColors[z]};" title="${z}: ${info.min}m (${info.pct}%)"></div>`;
            }
        }

        html += `</div>
            <div class="wrapped-stats">
                <span>Rings closed: ${data.rings_closed}/7 days</span>
                <span>Compass: ${data.compass_direction}</span>
            </div>`;

        if (data.top_echo) {
            html += `<div class="wrapped-echo">Top insight: "${data.top_echo}"</div>`;
        }

        content.innerHTML = html;

        // Apply collapsed state from localStorage
        const isCollapsed = localStorage.getItem('wrapped-collapsed') === 'true';
        const toggle = card.querySelector('.wrapped-toggle');
        if (isCollapsed) {
            content.classList.remove('wrapped-expanded');
            if (toggle) toggle.innerHTML = '&#9660;';
        } else {
            content.classList.add('wrapped-expanded');
            if (toggle) toggle.innerHTML = '&#9650;';
        }

        // Set up toggle click handler (remove old listener by replacing element)
        if (toggle && !toggle.dataset.bound) {
            toggle.dataset.bound = 'true';
            toggle.addEventListener('click', (e) => {
                e.stopPropagation();
                const expanded = content.classList.contains('wrapped-expanded');
                content.classList.toggle('wrapped-expanded', !expanded);
                toggle.innerHTML = expanded ? '&#9660;' : '&#9650;';
                localStorage.setItem('wrapped-collapsed', expanded ? 'true' : 'false');
            });
        }
    } catch (e) {
        console.error('Failed to load weekly wrapped:', e);
    }
}

// ========== The Beacon — Ambient Status Polling ==========

async function pollBeacon() {
    try {
        const data = await API.getBeacon();
        updateBeaconFavicon(data.zone);
        // Update header tooltip
        const micDot = document.getElementById('mic-dot');
        if (micDot && data.tooltip) {
            micDot.title = data.tooltip;
        }
    } catch (e) {
        // Silent fail — beacon is informational
    }
}

function updateBeaconFavicon(zone) {
    if (zone === lastBeaconZone) return;
    lastBeaconZone = zone;

    const colors = {
        calm: '#5a9a6e',
        steady: '#b5a84a',
        tense: '#d4943a',
        stressed: '#c4584c',
        idle: '#888888',
    };

    const color = colors[zone] || colors.idle;

    // Update favicon to colored dot
    const canvas = document.createElement('canvas');
    canvas.width = 32;
    canvas.height = 32;
    const ctx = canvas.getContext('2d');
    ctx.beginPath();
    ctx.arc(16, 16, 12, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();

    let link = document.querySelector("link[rel~='icon']");
    if (!link) {
        link = document.createElement('link');
        link.rel = 'icon';
        document.head.appendChild(link);
    }
    link.href = canvas.toDataURL();

    // Also update the page title with zone indicator
    const zoneEmoji = { calm: '\u{1F7E2}', steady: '\u{1F7E1}', tense: '\u{1F7E0}', stressed: '\u{1F534}', idle: '\u26AA' };
    document.title = `${zoneEmoji[zone] || ''} Attune`;
}

// ========== Morning Summary Overlay ==========

function shouldShowMorningSummary() {
    const hour = new Date().getHours();
    if (hour < 5 || hour >= 13) return false; // Only 5AM-1PM

    const todayKey = `attune_morning_seen_${new Date().toISOString().slice(0, 10)}`;
    if (localStorage.getItem(todayKey)) return false;

    return true;
}

async function loadMorningSummary() {
    if (morningSummaryShown) return;
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

    morningSummaryShown = true;

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

    // Canopy Score (center of rings)
    const canopy = data.canopy;
    const scoreEl = document.getElementById('morning-ring-score');
    const verdictEl = document.getElementById('morning-ring-verdict');

    if (canopy && canopy.has_data) {
        animateMorningScore(scoreEl, canopy.score, 2500);
        let verdict = 'Needs Attention';
        if (canopy.score >= 80) verdict = 'Excellent';
        else if (canopy.score >= 65) verdict = 'Good';
        else if (canopy.score >= 50) verdict = 'Fair';
        verdictEl.textContent = verdict;
    } else {
        scoreEl.textContent = '--';
        verdictEl.textContent = '';
    }

    // Extract metric values for rings
    const metricValues = {
        stress: briefing.metrics?.avg_stress ? Math.round(briefing.metrics.avg_stress.value) : 0,
        mood: briefing.metrics?.avg_mood ? Math.round(briefing.metrics.avg_mood.value) : 0,
        energy: briefing.metrics?.avg_energy ? Math.round(briefing.metrics.avg_energy.value) : 0,
        calm: briefing.metrics?.avg_calm ? Math.round(briefing.metrics.avg_calm.value) : 0,
    };

    // Animate concentric rings
    animateMorningRings(metricValues);

    // Update ring legend values
    const legendCalm = document.getElementById('morning-legend-calm');
    const legendMood = document.getElementById('morning-legend-mood');
    const legendEnergy = document.getElementById('morning-legend-energy');
    const legendStress = document.getElementById('morning-legend-stress');
    if (legendCalm) legendCalm.textContent = metricValues.calm;
    if (legendMood) legendMood.textContent = metricValues.mood;
    if (legendEnergy) legendEnergy.textContent = metricValues.energy;
    if (legendStress) legendStress.textContent = metricValues.stress;

    // Metric bars (right column)
    const barsEl = document.getElementById('morning-bars');
    if (barsEl && briefing.metrics) {
        const barConfig = [
            { key: 'avg_stress', label: 'Stress', color: '#c4584c' },
            { key: 'avg_mood', label: 'Mood', color: '#b8975c' },
            { key: 'avg_energy', label: 'Energy', color: '#b5a84a' },
            { key: 'avg_calm', label: 'Calm', color: '#5a9a6e' },
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
        const zoneColors = { calm: '#5a9a6e', steady: '#b5a84a', tense: '#d4943a', stressed: '#c4584c' };
        let barHtml = '';
        for (const z of ['calm', 'steady', 'tense', 'stressed']) {
            const info = briefing.zones[z];
            if (!info || info.pct === 0) continue;
            barHtml += `<div style="width: ${info.pct}%; background: ${zoneColors[z]};" title="${z}: ${info.minutes}m (${info.pct}%)"></div>`;
        }
        timelineBar.innerHTML = barHtml;
    }

    // Highlights
    const highlightsList = document.getElementById('morning-highlights-list');
    if (highlightsList && briefing.highlights && briefing.highlights.length > 0) {
        highlightsList.innerHTML = briefing.highlights.map(h => `<li>${h}</li>`).join('');
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
        const zoneColors = { calm: '#5a9a6e', steady: '#b5a84a', tense: '#d4943a', stressed: '#c4584c' };
        const color = zoneColors[vw.zone] || '#888';
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
        { id: 'morning-ring-mood', value: values.mood, circumference: 816.8 },
        { id: 'morning-ring-energy', value: values.energy, circumference: 659.7 },
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
    function tick(now) {
        const elapsed = now - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        el.textContent = Math.round(target * eased);
        if (progress < 1) {
            requestAnimationFrame(tick);
        } else {
            el.textContent = target;
        }
    }
    requestAnimationFrame(tick);
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
    const todayKey = `attune_morning_seen_${new Date().toISOString().slice(0, 10)}`;
    localStorage.setItem(todayKey, '1');

    // Cleanup old keys (keep last 7 days)
    const now = new Date();
    for (let i = 8; i < 30; i++) {
        const old = new Date(now);
        old.setDate(old.getDate() - i);
        const oldKey = `attune_morning_seen_${old.toISOString().slice(0, 10)}`;
        localStorage.removeItem(oldKey);
    }
}

// ========== Notification Settings ==========

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
            await API.setNotifPref('quiet_start', start.value);
            await API.setNotifPref('quiet_end', end.value);
        } catch (e) {
            console.error('Failed to save quiet hours:', e);
        }
    }
}


// ========== Speaker Verification — Voice Profile ==========

async function loadSpeakerStatus() {
    const badge = document.getElementById('speaker-status-badge');
    const setupBtn = document.getElementById('speaker-setup-btn');
    const deleteBtn = document.getElementById('speaker-delete-btn');
    if (!badge) return;

    try {
        const status = await API.getSpeakerStatus();
        if (status.enrolled) {
            badge.textContent = 'Active';
            badge.className = 'speaker-badge speaker-badge-active';
            setupBtn.textContent = 'Re-enroll Voice Profile';
            deleteBtn.style.display = 'block';
        } else {
            badge.textContent = 'Not Set Up';
            badge.className = 'speaker-badge speaker-badge-inactive';
            setupBtn.textContent = 'Set Up Voice Profile';
            deleteBtn.style.display = 'none';
        }

    } catch (e) {
        console.error('Failed to load speaker status:', e);
        badge.textContent = 'Unavailable';
        badge.className = 'speaker-badge speaker-badge-inactive';
    }
}

// Enrollment state
let enrollmentState = {
    currentStep: 1,
    totalSteps: 5,
    moodLabels: ['neutral', 'animated', 'calm', 'reading', 'on_a_call'],
    mediaRecorder: null,
    audioStream: null,
    audioContext: null,
    analyserNode: null,
    animFrameId: null,
    chunks: [],
    isRecording: false,
};

async function startEnrollment() {
    const overlay = document.getElementById('enrollment-overlay');
    overlay.style.display = 'flex';

    // Reset state
    enrollmentState.currentStep = 1;
    enrollmentState.chunks = [];
    enrollmentState.isRecording = false;

    // Reset enrollment on server
    try {
        await API.resetSpeakerEnrollment();
    } catch (e) {
        console.error('Failed to reset enrollment:', e);
    }

    updateEnrollmentUI();

    // Wire up buttons
    document.getElementById('enrollment-close-btn').onclick = closeEnrollment;
    document.getElementById('enrollment-record-btn').onclick = toggleRecording;
    document.getElementById('enrollment-finish-btn').onclick = () => {
        closeEnrollment();
        loadSpeakerStatus();
    };
}

function closeEnrollment() {
    const overlay = document.getElementById('enrollment-overlay');
    overlay.style.display = 'none';
    stopRecordingCleanup();
}

function updateEnrollmentUI() {
    const step = enrollmentState.currentStep;
    const total = enrollmentState.totalSteps;

    // Update step dots
    document.querySelectorAll('.step-dot').forEach(dot => {
        const s = parseInt(dot.dataset.step);
        dot.className = 'step-dot';
        if (s < step) dot.classList.add('complete');
        else if (s === step) dot.classList.add('active');
    });

    // Show correct step content
    for (let i = 1; i <= total; i++) {
        const el = document.getElementById(`enrollment-step-${i}`);
        if (el) el.classList.toggle('active', i === step);
    }

    // Reset recorder UI
    const recordBtn = document.getElementById('enrollment-record-btn');
    const countdown = document.getElementById('enrollment-countdown');
    recordBtn.textContent = 'Start Recording';
    recordBtn.classList.remove('recording');
    recordBtn.disabled = false;
    countdown.className = 'enrollment-countdown';
    countdown.textContent = '10';

    // Show recorder, hide processing/done
    document.getElementById('enrollment-recorder').style.display = 'block';
    document.getElementById('enrollment-processing').style.display = 'none';
    document.getElementById('enrollment-done').style.display = 'none';
    document.getElementById('enrollment-steps').querySelector('.step-indicators').style.display = 'flex';
}

async function toggleRecording() {
    if (enrollmentState.isRecording) return;

    const recordBtn = document.getElementById('enrollment-record-btn');
    const countdown = document.getElementById('enrollment-countdown');

    try {
        // Request microphone access
        const stream = await navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: 16000,
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true,
            }
        });
        enrollmentState.audioStream = stream;

        // Set up audio context for waveform visualization
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        enrollmentState.audioContext = audioCtx;
        const source = audioCtx.createMediaStreamSource(stream);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
        enrollmentState.analyserNode = analyser;

        // Start waveform animation
        drawEnrollmentWaveform();

        // Use ScriptProcessorNode to capture raw PCM at 16kHz
        const bufferSize = 4096;
        const scriptNode = audioCtx.createScriptProcessor(bufferSize, 1, 1);
        enrollmentState.chunks = [];

        scriptNode.onaudioprocess = (e) => {
            if (!enrollmentState.isRecording) return;
            const channelData = e.inputBuffer.getChannelData(0);
            // Convert float32 to int16
            const int16 = new Int16Array(channelData.length);
            for (let i = 0; i < channelData.length; i++) {
                const s = Math.max(-1, Math.min(1, channelData[i]));
                int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
            }
            enrollmentState.chunks.push(int16);
        };

        source.connect(scriptNode);
        scriptNode.connect(audioCtx.destination);
        enrollmentState.scriptNode = scriptNode;
        enrollmentState.sourceNode = source;

        enrollmentState.isRecording = true;
        recordBtn.textContent = 'Recording...';
        recordBtn.classList.add('recording');
        recordBtn.disabled = true;
        countdown.className = 'enrollment-countdown active';

        // Countdown timer
        let remaining = 10;
        countdown.textContent = remaining;

        const countdownInterval = setInterval(() => {
            remaining--;
            countdown.textContent = remaining;
            if (remaining <= 0) {
                clearInterval(countdownInterval);
                finishRecordingStep();
            }
        }, 1000);

        enrollmentState.countdownInterval = countdownInterval;

    } catch (e) {
        console.error('Microphone access denied:', e);
        recordBtn.textContent = 'Microphone Access Required';
        recordBtn.disabled = true;
    }
}

async function finishRecordingStep() {
    enrollmentState.isRecording = false;

    // Stop waveform animation
    if (enrollmentState.animFrameId) {
        cancelAnimationFrame(enrollmentState.animFrameId);
        enrollmentState.animFrameId = null;
    }

    // Combine PCM chunks into single buffer
    const totalLength = enrollmentState.chunks.reduce((acc, c) => acc + c.length, 0);
    const combined = new Int16Array(totalLength);
    let offset = 0;
    for (const chunk of enrollmentState.chunks) {
        combined.set(chunk, offset);
        offset += chunk.length;
    }

    // Stop audio stream
    stopRecordingCleanup();

    const step = enrollmentState.currentStep;
    const moodLabel = enrollmentState.moodLabels[step - 1];
    const recordBtn = document.getElementById('enrollment-record-btn');

    recordBtn.textContent = 'Uploading...';

    try {
        // Send raw PCM bytes to server
        const result = await API.enrollSpeakerSample(combined.buffer, moodLabel);
        console.log(`[Enrollment] Step ${step} complete:`, result);

        if (step < enrollmentState.totalSteps) {
            // Move to next step
            enrollmentState.currentStep = step + 1;
            updateEnrollmentUI();
        } else {
            // All samples collected — compute centroid
            showEnrollmentProcessing();
            const enrollResult = await API.completeSpeakerEnrollment();
            console.log('[Enrollment] Profile created:', enrollResult);
            showEnrollmentDone();
            // Hide enrollment-required banner
            const banner = document.getElementById('enrollment-required-banner');
            if (banner) banner.style.display = 'none';
        }
    } catch (e) {
        console.error('Enrollment step failed:', e);
        recordBtn.textContent = 'Failed — Try Again';
        recordBtn.classList.remove('recording');
        recordBtn.disabled = false;
    }
}

function stopRecordingCleanup() {
    enrollmentState.isRecording = false;

    if (enrollmentState.countdownInterval) {
        clearInterval(enrollmentState.countdownInterval);
        enrollmentState.countdownInterval = null;
    }

    if (enrollmentState.animFrameId) {
        cancelAnimationFrame(enrollmentState.animFrameId);
        enrollmentState.animFrameId = null;
    }

    if (enrollmentState.scriptNode) {
        try { enrollmentState.scriptNode.disconnect(); } catch (e) {}
        enrollmentState.scriptNode = null;
    }
    if (enrollmentState.sourceNode) {
        try { enrollmentState.sourceNode.disconnect(); } catch (e) {}
        enrollmentState.sourceNode = null;
    }

    if (enrollmentState.audioContext) {
        try { enrollmentState.audioContext.close(); } catch (e) {}
        enrollmentState.audioContext = null;
    }

    if (enrollmentState.audioStream) {
        enrollmentState.audioStream.getTracks().forEach(t => t.stop());
        enrollmentState.audioStream = null;
    }
}

function showEnrollmentProcessing() {
    document.getElementById('enrollment-recorder').style.display = 'none';
    document.getElementById('enrollment-processing').style.display = 'block';
    // Hide step content
    for (let i = 1; i <= 3; i++) {
        const el = document.getElementById(`enrollment-step-${i}`);
        if (el) el.classList.remove('active');
    }
}

function showEnrollmentDone() {
    document.getElementById('enrollment-processing').style.display = 'none';
    document.getElementById('enrollment-done').style.display = 'block';
    document.getElementById('enrollment-steps').querySelector('.step-indicators').style.display = 'none';
}

// ========== Science Modal (Rec #2) ==========

function openScienceModal() {
    const modal = document.getElementById('science-modal');
    if (modal) modal.style.display = 'flex';
}

function closeScienceModal() {
    const modal = document.getElementById('science-modal');
    if (modal) modal.style.display = 'none';
}

// Close on Escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeScienceModal();
});

function drawEnrollmentWaveform() {
    const canvas = document.getElementById('enrollment-canvas');
    if (!canvas || !enrollmentState.analyserNode) return;

    const ctx = canvas.getContext('2d');
    const analyser = enrollmentState.analyserNode;
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    function draw() {
        if (!enrollmentState.isRecording) return;
        enrollmentState.animFrameId = requestAnimationFrame(draw);

        analyser.getByteTimeDomainData(dataArray);

        ctx.fillStyle = 'rgba(235, 228, 218, 0.3)';
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        ctx.lineWidth = 2;
        ctx.strokeStyle = '#5B5854';
        ctx.beginPath();

        const sliceWidth = canvas.width / bufferLength;
        let x = 0;

        for (let i = 0; i < bufferLength; i++) {
            const v = dataArray[i] / 128.0;
            const y = (v * canvas.height) / 2;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
            x += sliceWidth;
        }

        ctx.lineTo(canvas.width, canvas.height / 2);
        ctx.stroke();
    }

    draw();
}
