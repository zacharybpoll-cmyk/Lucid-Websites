/**
 * Main app logic
 * Handles view routing, data fetching, UI updates, and all 10 engagement features
 */

// Sanitize user-controlled strings before innerHTML interpolation
function sanitizeHTML(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// Debounce utility — delays execution until calls stop for `delay` ms
function debounce(fn, delay = 250) {
    let timer;
    return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), delay);
    };
}

// SVG helper — creates an SVG element with attributes in one call
// Reduces boilerplate across chart rendering code (trends, timeline, gauges)
function svgEl(tag, attrs) {
    const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
    if (attrs) {
        for (const [k, v] of Object.entries(attrs)) {
            el.setAttribute(k, v);
        }
    }
    return el;
}

// FE-015: Centralized date formatting helpers for consistency
function formatShortDate(dateStr) {
    // "Feb 23" format from an ISO date string or Date object
    const d = typeof dateStr === 'string' ? new Date(dateStr + (dateStr.includes('T') ? '' : 'T12:00:00')) : dateStr;
    if (isNaN(d.getTime())) return '';
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function formatLongDate(dateStr) {
    // "Saturday, Feb 23" format
    const d = typeof dateStr === 'string' ? new Date(dateStr + (dateStr.includes('T') ? '' : 'T12:00:00')) : dateStr;
    if (isNaN(d.getTime())) return '';
    return d.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });
}

// Canonical zone color palette — matches CSS variables in main.css
const ZONE_COLORS = {
    calm: 'var(--calm-color)',
    steady: 'var(--steady-color)',
    tense: 'var(--tense-color)',
    stressed: 'var(--stressed-color)',
    idle: 'var(--zone-idle, #888)',
};

// Resolved zone hex colors (for canvas/SVG contexts where CSS vars don't work)
const ZONE_HEX = {
    calm: '#7BA7C9',
    steady: '#8C96A0',
    tense: '#6B7280',
    stressed: '#4B5563',
    idle: '#888888',
};

// Constants (not part of mutable state)
const SPEECH_THRESHOLD_SEC = 30;
const SANCTUARY_COOLDOWN = 300000; // 5 min
// First Light removed — constant kept empty for any residual references
const FIRST_LIGHT_TASKS = [];
const HERO_RING_CIRCUMFERENCE = 2 * Math.PI * 54; // ~339.3

// ========== AppState — single namespace for all mutable state ==========
window.AppState = {
    // Current view
    currentView: 'today',
    previousView: null,
    todayData: null,

    // Polling intervals
    pollInterval: null,
    statusPollInterval: null,

    // Mic indicator
    prevBufferedSec: 0,

    // Throttle timestamps
    lastBriefingUpdate: 0,
    lastEngagementUpdate: 0,
    lastFeatureUpdate: 0,

    // Sanctuary debounce
    lastSanctuaryTime: 0,

    // Linguistic Echo
    lastEchoReadingId: localStorage.getItem('lastEchoReadingId') || null,
    lastEchoDate: localStorage.getItem('lastEchoDate') || null,

    // Previous zone for transition detection
    previousZone: null,

    // Wellness score reveal state
    wellnessRevealed: false,
    prevWellnessScore: 0,

    // Intraday trend baseline
    morningBaselineScore: null,
    morningBaselineTime: null,

    // First Spark state
    firstSparkLoaded: false,

    // First Light quest state
    firstLightState: null,

    // Beacon state
    lastBeaconZone: 'idle',

    // Morning summary state
    morningSummaryShown: false,

    // Speak Hero state (first-time-ever + daily greeting)
    speakHeroVisible: false,

    // Mental Readiness overlay state
    readinessShown: false,
    readinessWellnessData: null,

    // Evening summary state
    eveningSummaryShown: false,

    // Analytics: timestamp when current view was entered
    _viewEnterTime: Date.now(),

    // Analysis error toast state (avoid spamming same error)
    lastShownAnalysisError: null,

    // Enrollment auto-prompt guard
    enrollmentAutoPrompted: false,

    // Hero ring analyzing state
    heroAnalyzingActive: false,
    heroAnalyzeRAF: null,
    heroAnalyzeStart: 0,

    // Wellness progress circle state
    wellnessIsAnalyzing: false,
    wellnessProgressRAF: null,
    wellnessProgressStart: 0,
    wellnessProgressSafetyTimer: null,

    // Rings closed notification guard (once per day)
    ringsClosedNotified: false,
};

// ========== Startup Sequencing ==========

async function init() {
    // 1. Fetch config (non-blocking — used for future threshold overrides)
    const config = await API.getConfig().catch(() => null);

    // 2. Initialize all view modules
    initGauges();
    initAnxietyTimeline();
    initTrendsView();
    initEngagementView();
    initCorrelationExplorer();
    initGrove();
    initLayout();
    if (typeof ActiveAssessment !== 'undefined') ActiveAssessment.init();
    initReportsView();

    // 3. Setup UI event handlers and static content
    setupNavigation();
    setupSettings();
    setupBriefingCards();
    setupInfoButtons();
    updateCurrentDate();
    updateDailyGreeting();

    // 4. Setup analytics tracking
    setupAnalyticsTracking();

    // 4b. Initialize Echo Drop overlay handlers
    initEchoDropOverlay();

    // 5. Wait for backend readiness, then load data and start polling
    await waitForBackend();

    // 6. Re-engagement check (after backend ready, non-blocking)
    checkReengagement().catch(err => console.warn('[reengagement] prefetch failed:', err.message || err));
}

document.addEventListener('DOMContentLoaded', init);

// Wait for backend models to load (skeleton loading screen)
// Returns a promise that resolves when backend is ready
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

    return new Promise((resolve) => {
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
                        if (overlay) overlay.classList.add('fade-out');
                        setTimeout(() => {
                            if (overlay) overlay.style.display = 'none';
                        }, 600);
                    }, 400);

                    startPolling();

                    // Batch parallel initial data fetches
                    const initialFetches = [
                        loadTodayData(),
                        loadFeatures(),
                    ];
                    if (shouldShowMorningSummary()) {
                        initialFetches.push(loadMorningSummary());
                    }
                    if (shouldShowEveningSummary()) {
                        initialFetches.push(loadEveningSummary());
                    }
                    Promise.allSettled(initialFetches);
                    resolve();
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
    }); // end Promise
}

// ========== Navigation ==========

function setupNavigation() {
    const sidebarIcons = document.querySelectorAll('.sidebar-icon[data-view]');
    sidebarIcons.forEach(icon => {
        icon.addEventListener('click', () => {
            const view = icon.dataset.view;
            switchView(view);
        });
    });
}

// View lifecycle registry — each view can define load/unload hooks
const VIEW_MODULES = {
    today: {
        load() { startPolling(); loadTodayData(); },
        unload() { stopPolling(); TimerRegistry.clearScope('today'); }
    },
    trends: {
        load() {
            if (typeof trendsView !== 'undefined' && trendsView) {
                trendsView.load(14);
                loadEchoes(); loadCompass(); loadVoiceSeason();
                loadWeeklyWrapped(); loadTopicCorrelations(); loadMeetingImpact();
            }
        },
        unload() { TimerRegistry.clearScope('trends'); }
    },
    waypoints: {
        load() { loadWaypoints(); },
        unload() { TimerRegistry.clearScope('waypoints'); }
    },
    voicescan: {
        load() { if (typeof ActiveAssessment !== 'undefined') ActiveAssessment.loadHistory(); },
        unload() { if (typeof ActiveAssessment !== 'undefined') ActiveAssessment.onNavigateAway(); }
    },
    lab: {
        load() { if (typeof labView !== 'undefined') labView.load(); },
        unload() { TimerRegistry.clearScope('lab'); }
    },
    reports: {
        load() { if (typeof reportsView !== 'undefined') reportsView.load(); },
        unload() { TimerRegistry.clearScope('reports'); }
    },
    echoes: {
        load() { initEchoesView(); },
        unload() { API.markEchoesSeen().then(() => updateEchoBadge()); }
    },
    settings: {
        load() {},
        unload() { TimerRegistry.clearScope('settings'); }
    },
    engagement: {
        load() {},
        unload() { TimerRegistry.clearScope('engagement'); }
    },
    journey: {
        load() { if (typeof clarityView !== 'undefined') clarityView.load(); },
        unload() { if (typeof clarityView !== 'undefined') clarityView.unload(); }
    },
};

function switchView(view) {
    // Redirect legacy view names
    if (view === 'history') { switchView('trends'); return; }

    // Analytics: track view switch with time on previous view
    const timeOnPrev = Math.round((Date.now() - (AppState._viewEnterTime || Date.now())) / 1000);
    if (AppState.currentView !== view) {
        API.track('view_switch', {
            from_view: AppState.currentView,
            to_view: view,
            time_on_previous_sec: timeOnPrev
        });
    }
    AppState._viewEnterTime = Date.now();

    // Unload previous view
    const prevModule = VIEW_MODULES[AppState.currentView];
    if (prevModule && AppState.currentView !== view) {
        prevModule.unload();
    }

    // Update sidebar + view visibility
    document.querySelectorAll('.sidebar-icon[data-view]').forEach(icon => {
        icon.classList.toggle('active', icon.dataset.view === view);
    });
    document.querySelectorAll('.view').forEach(viewEl => {
        viewEl.classList.toggle('active', viewEl.id === `${view}-view`);
    });

    AppState.previousView = AppState.currentView;
    AppState.currentView = view;

    // Load new view
    const nextModule = VIEW_MODULES[view];
    if (nextModule) nextModule.load();
}

function updateCurrentDate() {
    const dateEl = document.getElementById('current-date');
    if (!dateEl) return;
    const now = new Date();
    const options = { weekday: 'short', month: 'short', day: 'numeric' };
    dateEl.textContent = now.toLocaleDateString('en-US', options);
}

// ========== Polling ==========

function stopPolling() {
    TimerRegistry.clearScope('polling');
    AppState.pollInterval = null;
    AppState.statusPollInterval = null;
}

// Exponential backoff state for status polling
let _statusPollDelay = 2000;
let _statusPollFailures = 0;
const _STATUS_POLL_MIN = 2000;
const _STATUS_POLL_MAX = 30000;

function _scheduleStatusPoll() {
    AppState.statusPollInterval = TimerRegistry.setTimeout('polling', async () => {
        await pollStatus();
        _scheduleStatusPoll();
    }, _statusPollDelay);
}

function _scheduleDataPoll() {
    AppState.pollInterval = TimerRegistry.setTimeout('polling', () => {
        if (AppState.currentView === 'today') {
            loadTodayData();
        }
        _scheduleDataPoll();
    }, 5000);
}

function startPolling() {
    stopPolling();  // Clear any existing timeouts first
    _statusPollDelay = _STATUS_POLL_MIN;
    _statusPollFailures = 0;

    _scheduleDataPoll();
    pollStatus();
    _scheduleStatusPoll();
}

// Pause polling when tab is hidden, resume when visible
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        stopPolling();
    } else {
        startPolling();
    }
});

function handleMicDisconnectBanner(status) {
    let banner = document.getElementById('mic-disconnect-banner');
    if (status && status.mic_disconnected) {
        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'mic-disconnect-banner';
            banner.style.cssText = 'position:fixed;top:0;left:0;right:0;padding:10px 16px;' +
                'background:rgba(196,88,76,0.95);color:#fff;text-align:center;font-size:13px;' +
                'font-weight:600;z-index:10000;backdrop-filter:blur(8px);' +
                'box-shadow:0 2px 8px rgba(0,0,0,0.3);';
            banner.textContent = 'Microphone disconnected. Please reconnect your microphone.';
            document.body.appendChild(banner);
        }
    } else if (banner) {
        banner.remove();
    }
}

async function pollStatus() {
    try {
        const status = await API.getStatus();
        // Mic disconnect banner
        handleMicDisconnectBanner(status);
        updateMicIndicator(status);
        updateSpeakerDebug(status);
        // Start progress circle when backend begins analyzing
        if (status.is_analyzing && !AppState.wellnessIsAnalyzing) {
            startWellnessProgress();
        }
        // Finish progress circle when backend stops analyzing
        if (!status.is_analyzing && AppState.wellnessIsAnalyzing) {
            finishWellnessProgress();
        }
        // Ring gauge progress indicator
        if (status.is_analyzing && !_ringAnalyzing) {
            startRingGaugeProgress();
        }
        if (!status.is_analyzing && _ringAnalyzing) {
            finishRingGaugeProgress();
            console.log('[Lucid] Analysis complete, refreshing data...');
            // Small delay to let backend persist reading before fetching
            setTimeout(async () => {
                await loadTodayData();
                console.log('[Lucid] Data refreshed after analysis');
            }, 500);
        }
        // Show analysis error if present (only once per unique error)
        if (status.last_analysis_error && !status.is_analyzing) {
            showAnalysisError(status.last_analysis_error);
        } else if (!status.last_analysis_error) {
            AppState.lastShownAnalysisError = null; // reset when error clears
        }
        // Success: reset backoff
        _statusPollDelay = _STATUS_POLL_MIN;
        _statusPollFailures = 0;
        _removeBackendBanner();
    } catch (e) {
        updateMicIndicator(null);
        // Failure: exponential backoff
        _statusPollFailures++;
        _statusPollDelay = Math.min(_statusPollDelay * 2, _STATUS_POLL_MAX);
        if (_statusPollFailures >= 5) {
            _showBackendBanner();
        }
    }
}

function _showBackendBanner() {
    if (document.getElementById('backend-unreachable-banner')) return;
    const banner = document.createElement('div');
    banner.id = 'backend-unreachable-banner';
    banner.style.cssText = 'position:fixed;top:0;left:0;right:0;padding:10px 16px;' +
        'background:rgba(180,80,60,0.95);color:#fff;text-align:center;font-size:13px;' +
        'font-weight:600;z-index:10000;backdrop-filter:blur(8px);';
    banner.textContent = 'Backend unreachable — reconnecting...';
    document.body.appendChild(banner);
}

function _removeBackendBanner() {
    const banner = document.getElementById('backend-unreachable-banner');
    if (banner) banner.remove();
}

// ========== Analysis Error Toast ==========

function showAnalysisError(msg) {
    // Only show once per unique error message
    if (msg === AppState.lastShownAnalysisError) return;
    AppState.lastShownAnalysisError = msg;

    // Remove any existing toast
    const existing = document.getElementById('analysis-error-toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.id = 'analysis-error-toast';
    toast.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);' +
        'background:rgba(196,88,76,0.92);color:#fff;padding:10px 20px;border-radius:10px;' +
        'font-size:13px;z-index:9999;max-width:400px;text-align:center;' +
        'backdrop-filter:blur(8px);box-shadow:0 4px 16px rgba(0,0,0,0.3);' +
        'animation:fadeIn 0.3s ease;';
    toast.textContent = 'Analysis issue: ' + msg;

    document.body.appendChild(toast);
    setTimeout(() => {
        if (toast.parentNode) {
            toast.style.opacity = '0';
            toast.style.transition = 'opacity 0.5s ease';
            setTimeout(() => toast.remove(), 500);
        }
    }, 8000);
}

// ========== User-Visible Error Toast (FE-013) ==========

function showUserError(msg, durationMs = 6000) {
    // Remove any existing user-error toast
    const existing = document.getElementById('user-error-toast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.id = 'user-error-toast';
    toast.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);' +
        'background:rgba(91,88,84,0.92);color:#fff;padding:10px 20px;border-radius:10px;' +
        'font-size:13px;z-index:9999;max-width:400px;text-align:center;' +
        'backdrop-filter:blur(8px);box-shadow:0 4px 16px rgba(0,0,0,0.3);' +
        'animation:fadeIn 0.3s ease;';
    toast.textContent = msg;

    document.body.appendChild(toast);
    setTimeout(() => {
        if (toast.parentNode) {
            toast.style.opacity = '0';
            toast.style.transition = 'opacity 0.5s ease';
            setTimeout(() => toast.remove(), 500);
        }
    }, durationMs);
}

// ========== Card Error Feedback [R-023] ==========

function showCardError(cardId, message = 'Unable to load') {
    const card = document.getElementById(cardId);
    if (!card) return;
    const errEl = card.querySelector('.card-error');
    if (errEl) { errEl.textContent = message; return; }
    const div = document.createElement('div');
    div.className = 'card-error';
    div.style.cssText = 'text-align:center;padding:12px;color:rgba(91,88,84,0.7);font-size:12px;cursor:pointer;';
    div.textContent = message + ' — tap to retry';
    div.onclick = () => { div.remove(); loadTodayData(); };
    card.appendChild(div);
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
    const thresholdDisplay = stats.momentum_active ? '0.24' : (stats.adaptive_threshold || '0.28');
    document.getElementById('speaker-debug-stats').innerHTML =
        `Pass rate: <strong style="color:#fff">${passRate}%</strong> &nbsp;|&nbsp; ` +
        `✓ ${stats.segments_verified} verified &nbsp;|&nbsp; ✗ ${stats.segments_rejected} rejected` +
        (sandwich > 0 ? ` &nbsp;|&nbsp; 🥪 ${sandwich} recovered` : '') +
        momentumTag +
        (stats.last_similarity != null ? `<br>Last similarity: ${Number(stats.last_similarity).toFixed(3)} (threshold: ${thresholdDisplay})` : '');

    const events = stats.recent_events || [];
    const logEl = document.getElementById('speaker-debug-log');
    if (events.length === 0) {
        logEl.innerHTML = '<div style="opacity:0.5;margin-top:6px;">No segments yet — speak for ~2s</div>';
        return;
    }
    logEl.innerHTML = [...events].reverse().map(e => {
        let label = e.verified ? '✓ pass' : '✗ reject';
        if (e.overlap_rejected) label = '🗣 overlap';
        if (e.floor_rejected) label = '⛔ floor';
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

    // Escape closes any open overlay/modal
    if (e.key === 'Escape') {
        const overlays = [
            { id: 'morning-summary-overlay', dismiss: dismissMorningSummary },
            { id: 'evening-summary-overlay', dismiss: dismissEveningSummary },
            { id: 'readiness-overlay', dismiss: dismissReadinessOverlay },
            { id: 'wrapped-overlay', dismiss: dismissWrappedOverlay },
            { id: 'settings-panel', dismiss: () => { document.getElementById('settings-panel').style.display = 'none'; } },
            { id: 'enrollment-overlay', dismiss: closeEnrollment },
            { id: 'enhance-overlay', dismiss: closeEnhanceOverlay },
        ];
        for (const o of overlays) {
            const el = document.getElementById(o.id);
            if (el && el.style.display !== 'none' && typeof o.dismiss === 'function') {
                o.dismiss();
                break;
            }
        }
    }
});

document.addEventListener('DOMContentLoaded', () => {
    const closeBtn = document.getElementById('speaker-debug-close');
    if (closeBtn) closeBtn.addEventListener('click', () => {
        document.getElementById('speaker-debug').style.display = 'none';
    });
});

// enrollmentAutoPrompted is in AppState

function updateMicIndicator(status) {
    const dot = document.getElementById('mic-dot');
    const label = document.getElementById('mic-label');
    const seconds = document.getElementById('mic-seconds');
    const bar = document.getElementById('mic-progress-bar');
    const enrollBanner = document.getElementById('enrollment-required-banner');
    if (!dot || !label) return; // FE-014: guard against missing DOM elements

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
        AppState.prevBufferedSec = 0;

        // Auto-prompt enrollment on first detection (once per session)
        if (!AppState.enrollmentAutoPrompted) {
            AppState.enrollmentAutoPrompted = true;
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

    // Update hero card progress ring if visible
    if (AppState.speakHeroVisible) {
        if (status.is_analyzing) {
            setHeroAnalyzing(true);
        } else {
            setHeroAnalyzing(false);
            updateHeroRing(buffered);
        }
    }

    if (status.is_paused) {
        dot.className = 'mic-dot paused';
        label.textContent = 'Paused';
    } else if (!status.is_running) {
        dot.className = 'mic-dot idle';
        label.textContent = 'Not running';
    } else if (buffered < AppState.prevBufferedSec && AppState.prevBufferedSec > 5) {
        dot.className = 'mic-dot hearing';
        label.textContent = 'Analyzing...';
    } else if (buffered > 0 && buffered > AppState.prevBufferedSec) {
        dot.className = 'mic-dot hearing';
        label.textContent = 'Hearing speech...';
    } else if (buffered >= SPEECH_THRESHOLD_SEC) {
        dot.className = 'mic-dot hearing';
        label.textContent = 'Analyzing...';
    } else if (buffered > 0) {
        dot.className = 'mic-dot hearing';
        label.textContent = 'Speech buffered';
    } else {
        // If hero visible or daily greeting, override the label
        if (AppState.speakHeroVisible) {
            dot.className = 'mic-dot idle';
            label.textContent = 'Listening...';
        } else {
            dot.className = 'mic-dot idle';
            label.textContent = 'Listening...';
        }
    }

    AppState.prevBufferedSec = buffered;
}

// ========== Speak Hero Card Logic ==========

// HERO_RING_CIRCUMFERENCE is declared at top with constants
// heroAnalyzingActive, heroAnalyzeRAF, heroAnalyzeStart are in AppState

function updateHeroRing(bufferedSec) {
    const ringFill = document.getElementById('hero-ring-fill');
    const secondsEl = document.getElementById('hero-seconds-value');
    const unitEl = document.querySelector('.hero-ring-unit');
    if (!ringFill || !secondsEl) return;

    const progress = Math.min(1, bufferedSec / SPEECH_THRESHOLD_SEC);
    const offset = HERO_RING_CIRCUMFERENCE * (1 - progress);
    ringFill.style.strokeDashoffset = offset;
    secondsEl.textContent = Math.round(bufferedSec);
    if (unitEl) unitEl.style.display = '';
    if (unitEl) unitEl.textContent = 'sec';
}

function setHeroAnalyzing(active) {
    const ringFill = document.getElementById('hero-ring-fill');
    const secondsEl = document.getElementById('hero-seconds-value');
    const ringWrap = document.querySelector('.speak-hero-ring-wrap');
    if (!ringFill || !secondsEl) return;

    if (active && !AppState.heroAnalyzingActive) {
        AppState.heroAnalyzingActive = true;
        ringFill.classList.add('hero-ring-analyzing');
        ringWrap && ringWrap.classList.add('analyzing');
        secondsEl.textContent = 'Analyzing';
        secondsEl.classList.add('analyzing-text');

        // Progressive fill: 0->80% over 8s, then slow crawl to 95%
        AppState.heroAnalyzeStart = performance.now();
        if (AppState.heroAnalyzeRAF) cancelAnimationFrame(AppState.heroAnalyzeRAF);

        function tick(now) {
            const elapsed = now - AppState.heroAnalyzeStart;
            let progress;
            if (elapsed < 8000) {
                progress = (elapsed / 8000) * 0.80;
            } else {
                const extra = (elapsed - 8000) / 17000;
                progress = 0.80 + Math.min(extra, 1) * 0.15;
            }
            const offset = HERO_RING_CIRCUMFERENCE * (1 - progress);
            ringFill.style.strokeDashoffset = offset;

            if (AppState.heroAnalyzingActive) {
                AppState.heroAnalyzeRAF = requestAnimationFrame(tick);
            }
        }
        AppState.heroAnalyzeRAF = requestAnimationFrame(tick);

    } else if (!active && AppState.heroAnalyzingActive) {
        AppState.heroAnalyzingActive = false;
        if (AppState.heroAnalyzeRAF) {
            cancelAnimationFrame(AppState.heroAnalyzeRAF);
            AppState.heroAnalyzeRAF = null;
        }
        // Snap to full before clearing
        ringFill.style.strokeDashoffset = '0';
        setTimeout(() => {
            ringFill.classList.remove('hero-ring-analyzing');
            ringWrap && ringWrap.classList.remove('analyzing');
            secondsEl.classList.remove('analyzing-text');
        }, 400);
    }
}

function showSpeakHero() {
    const hero = document.getElementById('speak-hero');
    if (!hero) return;
    hero.style.display = '';
    AppState.speakHeroVisible = true;
}

function hideSpeakHero(celebrate) {
    const hero = document.getElementById('speak-hero');
    if (!hero || !AppState.speakHeroVisible) return;

    if (celebrate) {
        // Gold flash celebration
        hero.classList.add('celebrating');

        // Spawn leaf burst particles
        for (let i = 0; i < 12; i++) {
            const leaf = document.createElement('div');
            leaf.className = 'hero-leaf-particle';
            leaf.style.left = (30 + Math.random() * 40) + '%';
            leaf.style.top = (30 + Math.random() * 40) + '%';
            leaf.style.animationDelay = (Math.random() * 0.3) + 's';
            hero.appendChild(leaf);
        }

        setTimeout(() => {
            hero.style.maxHeight = hero.scrollHeight + 'px';
            // Force reflow
            hero.offsetHeight;
            hero.classList.add('shrinking');
            setTimeout(() => {
                hero.style.display = 'none';
                hero.classList.remove('celebrating', 'shrinking');
                // Remove particles
                hero.querySelectorAll('.hero-leaf-particle').forEach(p => p.remove());
                AppState.speakHeroVisible = false;
            }, 500);
        }, 800);
    } else {
        hero.style.display = 'none';
        AppState.speakHeroVisible = false;
    }
}

// ========== Hero → Readiness Transition ==========

function transitionHeroToDone() {
    // New flow: skip the "done" tap state — hide hero immediately, show readiness overlay
    hideSpeakHero(true);
    showReadinessOverlayAnalyzing();
}

// Kept as stub (no longer triggered, but harmless if called)
function onHeroDoneClick() {}

// ---- Readiness overlay phase helpers ----

function _setReadinessPhase(phase) {
    document.getElementById('readiness-state-analyzing').style.display = phase === 'analyzing' ? 'flex' : 'none';
    document.getElementById('readiness-state-reveal').style.display   = phase === 'reveal'    ? 'flex' : 'none';
    document.getElementById('readiness-state-score').style.display    = phase === 'score'     ? 'flex' : 'none';
}

function _computeReadinessScore(scores) {
    if (!scores) return null;
    const s  = scores.stress             != null ? scores.stress             : 50;
    const w  = scores.wellbeing          != null ? scores.wellbeing          : 50;
    const a  = scores.activation         != null ? scores.activation         : 50;
    const c  = scores.calm               != null ? scores.calm               : 50;
    const e  = scores.emotional_stability!= null ? scores.emotional_stability: 50;
    const dr = scores.depression_risk    != null ? scores.depression_risk    : 50;
    const ar = scores.anxiety_risk       != null ? scores.anxiety_risk       : 50;
    const avg = ((100 - s) + w + a + c + e + (100 - dr) + (100 - ar)) / 7;
    return Math.round(Math.min(100, Math.max(0, avg)));
}

function _readinessScoreLabel(score) {
    if (score >= 80) return 'Excellent';
    if (score >= 65) return 'Good';
    if (score >= 50) return 'Steady';
    if (score >= 35) return 'Low';
    return 'Very Low';
}

function _readinessTopFactor(scores) {
    if (!scores) return '--';
    const components = [
        { label: 'Calm',       val: scores.calm },
        { label: 'Energy',     val: scores.activation },
        { label: 'Wellbeing',  val: scores.wellbeing },
        { label: 'Stability',  val: scores.emotional_stability },
        { label: 'Low Stress', val: scores.stress != null ? 100 - scores.stress : null },
    ].filter(c => c.val != null);
    if (!components.length) return '--';
    components.sort((a, b) => b.val - a.val);
    return components[0].label;
}

async function showReadinessOverlayAnalyzing() {
    if (AppState.readinessShown) return;
    AppState.readinessShown = true;

    const overlay = document.getElementById('readiness-overlay');
    if (!overlay) return;

    // Prefetch wellness data in the background
    API.getWellness().then(d => { AppState.readinessWellnessData = d; }).catch(err => console.warn('[readiness] wellness prefetch failed:', err.message || err));

    _setReadinessPhase('analyzing');
    overlay.style.display = 'flex';
    overlay.offsetHeight;
    overlay.classList.add('visible');

    // After 2.5s: transition to reveal prompt
    TimerRegistry.setTimeout('readiness', () => _setReadinessPhase('reveal'), 2500);
}

// Alias — handles the "reopened after reading completed" path
async function showReadinessOverlay() {
    return showReadinessOverlayAnalyzing();
}

function revealReadinessScore() {
    // Mark as seen today — only after user actually clicks "Reveal"
    localStorage.setItem(`lucid_readiness_seen_${new Date().toISOString().slice(0,10)}`, '1');
    _setReadinessPhase('score');

    const scores = AppState.todayData && AppState.todayData.current_scores;
    const wellnessData = AppState.readinessWellnessData;
    const readinessScore = (wellnessData && wellnessData.score != null)
        ? Math.round(wellnessData.score)
        : _computeReadinessScore(scores);
    const label = _readinessScoreLabel(readinessScore != null ? readinessScore : 0);
    const topFactor = _readinessTopFactor(scores);
    const target = readinessScore != null ? readinessScore : 0;

    // Stats
    const countEl      = document.getElementById('readiness-count');
    const topEl        = document.getElementById('readiness-top-factor');
    const deltaEl      = document.getElementById('readiness-delta');

    if (countEl) countEl.textContent = wellnessData && wellnessData.reading_count != null
        ? wellnessData.reading_count
        : (AppState.todayData && AppState.todayData.readings ? AppState.todayData.readings.length : '1');
    if (topEl) topEl.textContent = topFactor;
    if (deltaEl) {
        const prevScore = AppState.morningBaselineScore;
        if (readinessScore != null && prevScore != null && prevScore !== readinessScore) {
            const delta = Math.round(readinessScore - prevScore);
            deltaEl.textContent = (delta > 0 ? '+' : '') + delta;
            deltaEl.className = 'readiness-stat-value ' + (delta > 0 ? 'positive' : 'negative');
        } else {
            deltaEl.textContent = '—';
            deltaEl.className = 'readiness-stat-value neutral';
        }
    }

    // Animate multi-ring arcs (staggered)
    const ringDefs = [
        { id: 'readiness-ring-1', circumference: 816.8, key: 'avg_emotional_stability' },
        { id: 'readiness-ring-2', circumference: 722.6, key: 'avg_wellbeing' },
        { id: 'readiness-ring-3', circumference: 628.3, key: 'avg_calm' },
        { id: 'readiness-ring-4', circumference: 534.1, key: 'avg_activation' },
    ];
    ringDefs.forEach((ring, i) => {
        const el = document.getElementById(ring.id);
        if (!el) return;
        const val = scores && scores[ring.key] != null ? scores[ring.key] : target;
        const offset = ring.circumference - (ring.circumference * val / 100);
        setTimeout(() => { el.style.strokeDashoffset = offset; }, 300 + i * 200);
    });

    // Count-up (2.5s)
    const scoreEl = document.getElementById('readiness-score');
    if (scoreEl) {
        const duration = 2500;
        const start = performance.now();
        const tick = (now) => {
            const elapsed = now - start;
            const progress = Math.min(elapsed / duration, 1);
            const eased = 1 - Math.pow(1 - progress, 3);
            scoreEl.textContent = Math.round(target * eased);
            if (progress < 1) requestAnimationFrame(tick);
            else scoreEl.textContent = target;
        };
        requestAnimationFrame(tick);
    }

    // Set label
    const labelEl = document.getElementById('readiness-label-text');
    if (labelEl) labelEl.textContent = label;

    // Fade in stats after 1.5s
    setTimeout(() => {
        const stats = document.getElementById('readiness-stats');
        if (stats) stats.classList.add('visible');
    }, 1500);

    // Fade in action buttons after 2.2s
    setTimeout(() => {
        const buttons = document.getElementById('readiness-buttons');
        if (buttons) { buttons.style.opacity = '1'; buttons.style.pointerEvents = ''; }
    }, 2200);
}

function dismissReadinessOverlay() {
    const overlay = document.getElementById('readiness-overlay');
    if (!overlay) return;

    overlay.classList.remove('visible');
    overlay.classList.add('fade-out');

    setTimeout(() => {
        overlay.style.display = 'none';
        overlay.classList.remove('fade-out');

        // Reset for next use
        _setReadinessPhase('analyzing');
        const arc = document.getElementById('readiness-ring-arc');
        if (arc) arc.style.strokeDashoffset = '691.2';
        const scoreEl = document.getElementById('readiness-score');
        if (scoreEl) scoreEl.textContent = '0';
        const stats = document.getElementById('readiness-stats');
        if (stats) stats.classList.remove('visible');
        const buttons = document.getElementById('readiness-buttons');
        if (buttons) { buttons.style.opacity = '0'; buttons.style.pointerEvents = 'none'; }

        // Clean up old localStorage keys (>7 days)
        const now = new Date();
        for (let i = localStorage.length - 1; i >= 0; i--) {
            const key = localStorage.key(i);
            if (key && key.startsWith('lucid_readiness_seen_')) {
                const keyDate = new Date(key.replace('lucid_readiness_seen_', ''));
                if ((now - keyDate) > 7 * 24 * 60 * 60 * 1000) localStorage.removeItem(key);
            }
        }
    }, 500);
}

function showDeeperInsights() {
    const overlay = document.getElementById('dive-deeper-overlay');
    const barsContainer = document.getElementById('dive-deeper-bars');
    if (!overlay || !barsContainer) return;

    const scores = AppState.todayData && AppState.todayData.current_scores;

    const COMPONENTS = [
        { key: 'stress',              label: 'STRESS LEVEL',         invert: true,  desc: 'Lower is better. Measured from vocal tension and pace.' },
        { key: 'wellbeing',           label: 'MOOD & WELLBEING',      invert: false, desc: 'Overall emotional quality of your voice patterns.' },
        { key: 'activation',          label: 'ENERGY LEVEL',          invert: false, desc: 'Vocal energy and engagement detected in your voice.' },
        { key: 'calm',                label: 'CALMNESS',              invert: false, desc: 'Physiological composure reflected in your speech.' },
        { key: 'emotional_stability', label: 'EMOTIONAL STABILITY',   invert: false, desc: 'Consistency of emotional tone across your readings.' },
        { key: 'depression_risk',     label: 'EMOTIONAL RESILIENCE',  invert: true,  desc: 'Inverted depression risk — higher = more resilient.' },
        { key: 'anxiety_risk',        label: 'ANXIETY EASE',          invert: true,  desc: 'Inverted anxiety risk — higher = calmer baseline.' },
    ];

    barsContainer.innerHTML = '';
    COMPONENTS.forEach(comp => {
        const rawVal = scores && scores[comp.key] != null ? scores[comp.key] : null;
        const displayVal = rawVal != null ? (comp.invert ? Math.round(100 - rawVal) : Math.round(rawVal)) : '--';
        const pct = rawVal != null ? Math.min(100, Math.max(0, comp.invert ? 100 - rawVal : rawVal)) : 0;

        const item = document.createElement('div');
        item.className = 'dd-bar-item';
        item.innerHTML = `
            <div class="dd-bar-header">
                <span class="dd-bar-label">${sanitizeHTML(comp.label)}</span>
                <span class="dd-bar-value">${displayVal}</span>
            </div>
            <div class="dd-bar-track">
                <div class="dd-bar-fill" data-pct="${pct}"></div>
            </div>
            <p class="dd-bar-desc">${sanitizeHTML(comp.desc)}</p>
        `;
        barsContainer.appendChild(item);
    });

    overlay.style.display = 'flex';
    overlay.offsetHeight;
    overlay.classList.add('visible');

    barsContainer.querySelectorAll('.dd-bar-item').forEach((item, i) => {
        setTimeout(() => {
            item.classList.add('visible');
            const fill = item.querySelector('.dd-bar-fill');
            if (fill) requestAnimationFrame(() => { fill.style.width = fill.dataset.pct + '%'; });
        }, i * 55);
    });
}

function hideDeeperInsights() {
    const overlay = document.getElementById('dive-deeper-overlay');
    if (!overlay) return;
    overlay.classList.remove('visible');
    setTimeout(() => { overlay.style.display = 'none'; }, 400);
}

function updateDailyGreeting() {
    const greetingText = document.getElementById('daily-greeting-text');
    if (!greetingText) return;
    const hour = new Date().getHours();
    if (hour < 12) greetingText.textContent = 'Good morning';
    else if (hour < 17) greetingText.textContent = 'Good afternoon';
    else greetingText.textContent = 'Good evening';
}

// ========== Load Today's Data ==========

async function loadTodayData() {
    // Set loading state on dashboard cards that haven't loaded yet
    document.querySelectorAll('.card-content').forEach(el => {
        if (!el.dataset.loaded) {
            el.classList.add('loading');
        }
    });

    try {
        const data = await API.getToday();
        AppState.todayData = data;

        // Clear loading states
        document.querySelectorAll('.card-content.loading').forEach(el => {
            el.classList.remove('loading');
            el.dataset.loaded = 'true';
        });

        // --- Speak Hero / Daily Greeting / Readiness Logic ---
        const totalReadings = data.total_readings || 0;
        const todayReadings = data.readings ? data.readings.length : 0;
        const readinessSeenToday = localStorage.getItem(
            `lucid_readiness_seen_${new Date().toISOString().slice(0, 10)}`
        );

        if (totalReadings === 0 && todayReadings === 0) {
            // First-time-ever: show hero card
            if (!AppState.speakHeroVisible) showSpeakHero();
        } else if (todayReadings === 0 && !readinessSeenToday && !AppState.speakHeroVisible) {
            // Returning user, first open today, no readings yet
            showSpeakHero();
        } else if (AppState.speakHeroVisible && todayReadings >= 1) {
            // First reading arrived — transition to "done" state
            transitionHeroToDone();
        } else if (todayReadings >= 1 && !readinessSeenToday && !AppState.readinessShown) {
            // User closed app during analysis, reopened after reading completed
            showReadinessOverlay();
        }

        // Fetch wellness data first so ring gauge has the score
        const wellnessData = await API.getWellness().catch(() => null);
        const wellnessScore = (wellnessData && wellnessData.has_data) ? wellnessData.score : null;
        // Track reading count for reveal overlay logic
        if (wellnessData) AppState.currentReadingCount = wellnessData.reading_count || 0;

        // Intraday trend: reset baseline if day changed
        if (AppState.morningBaselineTime) {
            const baseDate = AppState.morningBaselineTime.toDateString();
            const today = new Date().toDateString();
            if (baseDate !== today) {
                AppState.morningBaselineScore = null;
                AppState.morningBaselineTime = null;
            }
        }

        // Track morning baseline (first wellness score of the day)
        if (wellnessScore !== null && AppState.morningBaselineScore === null) {
            AppState.morningBaselineScore = wellnessScore;
            AppState.morningBaselineTime = new Date();
        }

        // Compute intraday delta (only after 2+ readings so delta is meaningful)
        let wellnessDelta = null;
        if (wellnessScore !== null && AppState.morningBaselineScore !== null
            && wellnessScore !== AppState.morningBaselineScore) {
            wellnessDelta = Math.round(wellnessScore - AppState.morningBaselineScore);
        }

        updateCurrentScores(data.current_scores, data.readings);
        updateScoreCircles(data.current_scores, wellnessScore, wellnessDelta);
        updateZoneBar(data.readings);
        updateAnxietyTimeline(data.readings);
        updateZoneSummary(data.summary);
        updateMeetings(data.readings);
        updateCalibrationBanner(data.calibration_status);

        // Update wellness UI elements (progress state, score display, profile)
        _updateWellnessUI(wellnessData);

        // Detect zone transitions for Sanctuary Moments
        if (data.readings && data.readings.length > 0) {
            const currentZone = data.readings[0].zone;
            if (AppState.previousZone === 'stressed' && (currentZone === 'calm' || currentZone === 'steady')) {
                triggerSanctuary('calm_shift', 'You found your calm');
            } else if (AppState.previousZone === 'tense' && currentZone === 'calm') {
                triggerSanctuary('calm_shift', 'Tension released. Well done.');
            }
            AppState.previousZone = currentZone;

            // First reading of the day
            if (data.readings.length === 1 && !AppState.wellnessRevealed) {
                triggerSanctuary('first_reading', 'Your voice has been heard');
            }
        }

        // Linguistic Echo — surface notable feature after recording (once per day)
        if (data.current_scores?.linguistic_echo) {
            const latestId = data.readings?.[0]?.id;
            const today = new Date().toISOString().split('T')[0];
            const alreadyShownToday = AppState.lastEchoDate === today;

            if (latestId && !alreadyShownToday && String(latestId) !== String(AppState.lastEchoReadingId)) {
                AppState.lastEchoReadingId = latestId;
                AppState.lastEchoDate = today;
                localStorage.setItem('lastEchoReadingId', latestId);
                localStorage.setItem('lastEchoDate', today);
                const delay = (Date.now() - AppState.lastSanctuaryTime < 5000) ? 4000 : 500;
                setTimeout(() => showLinguisticEcho(data.current_scores.linguistic_echo), delay);
            }
        }

        // Throttle expensive updates
        const now = Date.now();
        if (now - AppState.lastBriefingUpdate > 300000) {
            AppState.lastBriefingUpdate = now;
            updateBriefings();
        }
        if (now - AppState.lastEngagementUpdate > 60000) {
            AppState.lastEngagementUpdate = now;
            updateEngagement();
        }
        if (now - AppState.lastFeatureUpdate > 30000) {
            AppState.lastFeatureUpdate = now;
            loadFeatures();
        }

        // Evening summary trigger
        if (shouldShowEveningSummary()) {
            loadEveningSummary();
        }

    } catch (error) {
        // Clear loading states on error
        document.querySelectorAll('.card-content.loading').forEach(el => {
            el.classList.remove('loading');
        });
        console.error('Error loading today data:', error);
        // FE-013: Show user-visible error if this is the initial load
        if (!AppState.todayData) {
            showUserError('Unable to load dashboard data. Retrying...');
        }
    }
}

// ========== Load All New Features ==========

async function loadFeatures() {
    // Load features in parallel (pattern cards moved to Trends view)
    Promise.allSettled([
        loadRhythmRings(),
        loadRecoveryPulse(),
        updateGrove(),
        pollBeacon(),
        loadEchoesNotificationDot(),
        applyBadgeStreakFusion(),
    ]);
}

// ========== Voice Season ==========

async function loadVoiceSeason() {
    try {
        const data = await API.getVoiceSeason();
        const card = document.getElementById('voice-season-card');
        if (!card) return;

        if (!data.has_data) {
            card.style.display = 'none';
            return;
        }

        card.style.display = 'block';

        const dayEl = document.getElementById('voice-season-day');
        const phaseEl = document.getElementById('voice-season-phase');
        const fillEl = document.getElementById('voice-season-fill');
        const numberEl = document.getElementById('voice-season-number');

        if (dayEl) dayEl.textContent = data.day;
        if (phaseEl) phaseEl.textContent = data.phase;
        if (fillEl) fillEl.style.width = data.progress_pct + '%';
        if (numberEl) numberEl.textContent = data.season_number > 1 ? `Season ${data.season_number}` : '';

        // Highlight active phase
        card.querySelectorAll('.voice-season-phase-dot').forEach(dot => {
            dot.classList.toggle('active', dot.dataset.phase === data.phase);
        });

        // Phase transition celebration
        if (data.phase_transition) {
            triggerSanctuary('phase_transition', `${data.phase_transition.new_phase} Unlocked — Day ${data.phase_transition.day}`);
        }

        // Season complete celebration
        if (data.season_complete) {
            triggerSanctuary('season_complete', `Voice Season ${data.season_number} Complete!`);
        }
    } catch (e) {
        console.error('Failed to load voice season:', e);
    }
}

// ========== Streak Insurance ==========

async function loadStreakInsurance() {
    try {
        const data = await API.getStreakInsuranceStatus();
        const card = document.getElementById('streak-insurance-card');
        if (!card) return;

        const numberEl = document.getElementById('streak-insurance-number');
        const titleEl = document.getElementById('streak-insurance-title');
        const descEl = document.getElementById('streak-insurance-desc');
        const actionsEl = document.getElementById('streak-insurance-actions');

        if (numberEl) numberEl.textContent = data.streak || 0;

        if (data.available && data.streak > 0) {
            card.style.display = 'block';
            if (titleEl) titleEl.textContent = '1 Resilience Day Available';
            if (descEl) descEl.textContent = 'Your streak survives even if you miss a day';
            if (actionsEl) actionsEl.style.display = 'flex';
        } else if (data.used_this_week) {
            card.style.display = 'block';
            if (titleEl) titleEl.textContent = 'Resilience Day Used';
            if (descEl) descEl.textContent = 'Resets next Monday';
            if (actionsEl) actionsEl.style.display = 'none';
        } else {
            card.style.display = 'none';
        }
    } catch (e) {
        console.error('Failed to load streak insurance:', e);
    }
}

async function useStreakInsurance() {
    try {
        const result = await API.useStreakInsurance();
        if (result.success) {
            triggerSanctuary('streak_saved', result.message);
            loadStreakInsurance();
        } else {
            showUserError(result.message);
        }
    } catch (e) {
        console.error('Failed to use streak insurance:', e);
    }
}

function dismissStreakInsurance() {
    const card = document.getElementById('streak-insurance-card');
    if (card) card.style.display = 'none';
}

// ========== Wellness Score (Feature #1) ==========

async function loadWellnessScore() {
    try {
        const data = await API.getWellness();
        const scoreEl = document.getElementById('wellness-score');
        const profileEl = document.getElementById('wellness-profile');
        const progressState = document.getElementById('wellness-progress-state');
        const progressBar = document.getElementById('wellness-progress-bar');
        const readingCountEl = document.getElementById('wellness-reading-count');

        AppState.currentReadingCount = data.reading_count || 0;
        if (!data.has_data) {
            // Show progress state
            const count = data.reading_count || 0;
            if (progressState) progressState.style.display = 'flex';
            if (scoreEl) scoreEl.style.display = 'none';
            if (progressBar) progressBar.style.width = ((count / 1) * 100) + '%';
            if (readingCountEl) readingCountEl.textContent = `${count} of 1 reading`;
            if (profileEl) profileEl.textContent = '';
            AppState.wellnessRevealed = false; // Reset so animation fires on score unlock
        } else {
            // Show score (but not while progress circle is active)
            if (progressState) progressState.style.display = 'none';
            if (!AppState.wellnessIsAnalyzing && scoreEl) scoreEl.style.display = '';

            // Legacy score element is hidden — just update its text
            // The ring gauge reveal card controls wellnessRevealed
            if (scoreEl) scoreEl.textContent = Math.round(data.score);
            AppState.prevWellnessScore = data.score;
            if (profileEl) profileEl.textContent = data.profile || '';
        }
    } catch (e) {
        console.error('Failed to load wellness score:', e);
    }
}

// Update wellness UI elements from pre-fetched data (avoids duplicate API call)
function _updateWellnessUI(data) {
    if (!data) return;
    const scoreEl = document.getElementById('wellness-score');
    const profileEl = document.getElementById('wellness-profile');
    const progressState = document.getElementById('wellness-progress-state');
    const progressBar = document.getElementById('wellness-progress-bar');
    const readingCountEl = document.getElementById('wellness-reading-count');

    AppState.currentReadingCount = data.reading_count || 0;
    if (!data.has_data) {
        const count = data.reading_count || 0;
        if (progressState) progressState.style.display = 'flex';
        if (scoreEl) scoreEl.style.display = 'none';
        if (progressBar) progressBar.style.width = ((count / 1) * 100) + '%';
        if (readingCountEl) readingCountEl.textContent = `${count} of 1 reading`;
        if (profileEl) profileEl.textContent = '';
        AppState.wellnessRevealed = false;
    } else {
        if (progressState) progressState.style.display = 'none';
        if (!AppState.wellnessIsAnalyzing && scoreEl) scoreEl.style.display = '';

        // Legacy score element is hidden — just update its text
        // The ring gauge reveal card controls wellnessRevealed
        if (scoreEl) scoreEl.textContent = Math.round(data.score);
        AppState.prevWellnessScore = data.score;
        if (profileEl) profileEl.textContent = data.profile || '';
    }
}

function animateCountUp(el, target, duration, fromValue = 0) {
    const start = fromValue;
    const startTime = performance.now();
    if (el._countUpRAF) cancelAnimationFrame(el._countUpRAF);

    function tick(now) {
        const elapsed = now - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        const current = Math.round(start + (target - start) * eased);
        el.textContent = current;

        if (progress < 1) {
            el._countUpRAF = requestAnimationFrame(tick);
        } else {
            el._countUpRAF = null;
            el.textContent = target;
            addLeafParticles(el.parentElement);
        }
    }

    el._countUpRAF = requestAnimationFrame(tick);
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

// ========== Wellness Progress Circle ==========

// wellnessIsAnalyzing, wellnessProgressRAF, wellnessProgressStart, wellnessProgressSafetyTimer are in AppState

function startWellnessProgress() {
    const circle = document.getElementById('wellness-progress-circle');
    const arc = document.getElementById('wellness-progress-arc');
    const scoreEl = document.getElementById('wellness-score');
    if (!circle || !arc) return;

    AppState.wellnessIsAnalyzing = true;
    circle.style.display = 'flex';
    if (scoreEl) scoreEl.style.display = 'none';

    arc.style.transition = 'none';
    arc.style.strokeDashoffset = '326.7';

    AppState.wellnessProgressStart = performance.now();
    if (AppState.wellnessProgressRAF) cancelAnimationFrame(AppState.wellnessProgressRAF);

    // Safety timeout: auto-dismiss after 25s no matter what
    TimerRegistry.clearScope('wellness-progress');
    AppState.wellnessProgressSafetyTimer = TimerRegistry.setTimeout('wellness-progress', () => {
        if (AppState.wellnessIsAnalyzing) finishWellnessProgress();
    }, 25000);

    function tick(now) {
        const elapsed = now - AppState.wellnessProgressStart;
        // Phase 1: Linear to 80% over 8s
        // Phase 2: Slow crawl from 80% to 95% over next 17s
        let progress;
        if (elapsed < 8000) {
            progress = (elapsed / 8000) * 0.80;
        } else {
            const extra = (elapsed - 8000) / 17000;
            progress = 0.80 + Math.min(extra, 1) * 0.15;
        }
        const offset = 326.7 * (1 - progress);
        arc.style.transition = 'none';
        arc.style.strokeDashoffset = offset;

        if (AppState.wellnessIsAnalyzing) {
            AppState.wellnessProgressRAF = requestAnimationFrame(tick);
        }
    }

    AppState.wellnessProgressRAF = requestAnimationFrame(tick);
}

function finishWellnessProgress() {
    const circle = document.getElementById('wellness-progress-circle');
    const arc = document.getElementById('wellness-progress-arc');
    const scoreEl = document.getElementById('wellness-score');
    if (!arc) return;

    // Keep wellnessIsAnalyzing true during the 500ms close transition
    // so loadWellnessScore() won't prematurely show the score element
    if (AppState.wellnessProgressRAF) {
        cancelAnimationFrame(AppState.wellnessProgressRAF);
        AppState.wellnessProgressRAF = null;
    }
    if (AppState.wellnessProgressSafetyTimer) {
        clearTimeout(AppState.wellnessProgressSafetyTimer);
        AppState.wellnessProgressSafetyTimer = null;
    }

    // Snap to 100%
    arc.style.transition = 'stroke-dashoffset 0.4s ease-out';
    arc.style.strokeDashoffset = '0';

    // After transition: hide circle, show score, refresh wellness data
    setTimeout(() => {
        AppState.wellnessIsAnalyzing = false;
        if (circle) circle.style.display = 'none';
        if (scoreEl) scoreEl.style.display = '';
        // Force a fresh wellness score fetch so count-up fires immediately
        loadWellnessScore();
    }, 500);
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
        if (data.all_closed && !AppState.ringsClosedNotified) {
            AppState.ringsClosedNotified = true;
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

// ========== Recovery Pulse ==========

async function loadRecoveryPulse() {
    try {
        const data = await API.getRecoveryPulse();

        if (!data.has_data || data.readings.length < 2) {
            // Empty state
            const insightEl = document.getElementById('rp-insight');
            if (insightEl) insightEl.textContent = data.insight || 'Recovery Pulse measures how quickly your stress drops between readings. It needs at least 2 readings today to calculate.';
            return;
        }

        // 1. Draw sparkline SVG
        drawRecoverySparkline(data.readings);

        // 2. Update big number
        const numEl = document.getElementById('rp-number');
        if (numEl) numEl.textContent = Math.round(data.avg_recovery_speed);

        // 3. Update trend
        const trendEl = document.getElementById('rp-trend');
        if (trendEl) {
            const arrowEl = trendEl.querySelector('.rp-trend-arrow');
            const labelEl = trendEl.querySelector('.rp-trend-label');
            if (arrowEl) {
                arrowEl.textContent = data.trend === 'improving' ? '\u2197' :
                                      data.trend === 'declining' ? '\u2198' : '\u2192';
            }
            if (labelEl) labelEl.textContent = data.trend;
            trendEl.className = 'rp-trend rp-trend-' + data.trend;
        }

        // 4. Update insight
        const insightEl = document.getElementById('rp-insight');
        if (insightEl) insightEl.textContent = data.insight;
    } catch (e) {
        console.error('Failed to load recovery pulse:', e);
    }
}

function drawRecoverySparkline(readings) {
    const svg = document.getElementById('rp-sparkline');
    if (!svg || readings.length < 2) return;

    const W = 300, H = 80;
    const stressValues = readings.map(r => r.stress);
    const minS = Math.max(0, Math.min(...stressValues) - 5);
    const maxS = Math.min(100, Math.max(...stressValues) + 5);
    const range = maxS - minS || 1;

    // Map readings to SVG coordinates (higher stress = higher y visually, so invert)
    const points = readings.map((r, i) => ({
        x: (i / (readings.length - 1)) * W,
        y: H - ((r.stress - minS) / range) * (H - 8) - 4,
    }));

    // Build smooth path
    let pathD = `M ${points[0].x} ${points[0].y}`;
    for (let i = 1; i < points.length; i++) {
        const prev = points[i - 1];
        const curr = points[i];
        const cpx = (prev.x + curr.x) / 2;
        pathD += ` C ${cpx} ${prev.y}, ${cpx} ${curr.y}, ${curr.x} ${curr.y}`;
    }

    // Build gradient fill areas for each segment
    let fills = '';
    for (let i = 0; i < points.length - 1; i++) {
        const p1 = points[i];
        const p2 = points[i + 1];
        const isRecovery = readings[i].stress > readings[i + 1].stress;
        const color = isRecovery ? 'rgba(90,154,110,0.25)' : 'rgba(184,151,92,0.2)';
        const cpx = (p1.x + p2.x) / 2;

        fills += `<path d="M ${p1.x} ${p1.y} C ${cpx} ${p1.y}, ${cpx} ${p2.y}, ${p2.x} ${p2.y} L ${p2.x} ${H} L ${p1.x} ${H} Z" fill="${color}"/>`;
    }

    // Average baseline
    const avgStress = stressValues.reduce((a, b) => a + b, 0) / stressValues.length;
    const baselineY = H - ((avgStress - minS) / range) * (H - 8) - 4;

    svg.innerHTML = `
        ${fills}
        <line x1="0" y1="${baselineY}" x2="${W}" y2="${baselineY}" stroke="rgba(0,0,0,0.12)" stroke-width="1" stroke-dasharray="4,3"/>
        <path d="${pathD}" fill="none" stroke="var(--text-secondary)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        ${points.map((p, i) => {
            const isRecovery = i > 0 && readings[i].stress < readings[i - 1].stress;
            const isSpike = i > 0 && readings[i].stress > readings[i - 1].stress;
            const dotColor = isRecovery ? 'var(--calm-color)' : isSpike ? 'var(--gold)' : 'var(--text-muted)';
            return `<circle cx="${p.x}" cy="${p.y}" r="3" fill="${dotColor}" stroke="white" stroke-width="1"/>`;
        }).join('')}
    `;
}

// ========== Echoes (Feature #6) — Echo Drop System ==========

// Update sidebar badge from /api/echoes/count (no side effects)
async function updateEchoBadge() {
    try {
        const { unread_count, has_eureka } = await API.getEchoCount();
        const wrap = document.getElementById('echo-sidebar-badge-wrap');
        const countEl = document.getElementById('echo-count-badge');
        const eurekaEl = document.getElementById('echo-eureka-pill');
        if (!wrap) return;
        countEl.textContent = unread_count;
        if (eurekaEl) eurekaEl.style.display = has_eureka ? 'inline-flex' : 'none';
        wrap.style.display = unread_count > 0 ? 'flex' : 'none';
    } catch (e) {
        // silent
    }
}

// Streak × Badge Fusion: apply urgency class based on streak gap
async function applyBadgeStreakFusion() {
    try {
        const wrap = document.getElementById('echo-sidebar-badge-wrap');
        if (!wrap) return;
        const engData = await API.getEngagement();
        const streakDays = engData.streak || 0;
        // streak_gap: 0 = active today, 1 = missed yesterday, 2+ = FOMO state
        const today = new Date();
        const lastActiveDate = engData.last_active_date;
        let streakGap = 0;
        if (lastActiveDate) {
            const last = new Date(lastActiveDate);
            streakGap = Math.round((today - last) / 86400000);
        }
        wrap.classList.remove('echo-badge-urgent');
        if (streakGap === 1) {
            wrap.classList.add('echo-badge-urgent');
        } else if (streakGap >= 2) {
            // Hide badge — re-engagement overlay handles this state
            wrap.style.display = 'none';
        }
    } catch (e) {
        // silent
    }
}

// Re-engagement check: fire overlay if user absent 2+ days with unseen echoes
async function checkReengagement() {
    try {
        const { days_since_last_open } = await API.recordAppOpen();
        if (days_since_last_open < 2) return;
        const { unread_count } = await API.getEchoCount();
        if (unread_count === 0) return;
        showReengagementOverlay(unread_count);
    } catch (e) {
        // silent
    }
}

function showReengagementOverlay(unreadCount) {
    const overlay = document.getElementById('echo-reengagement-overlay');
    if (!overlay) return;
    document.getElementById('reengagement-count').textContent = unreadCount;

    // Build locked echo placeholder cards
    const row = document.getElementById('locked-echoes-row');
    if (row) {
        const cardCount = Math.min(unreadCount, 3);
        let html = '';
        for (let i = 0; i < cardCount; i++) {
            html += `<div class="locked-echo-card"></div>`;
        }
        row.innerHTML = html;
    }

    overlay.style.display = 'flex';

    const revealBtn = document.getElementById('echo-reveal-btn');
    if (revealBtn) {
        revealBtn.onclick = () => {
            overlay.style.display = 'none';
            switchView('echoes');
        };
    }
}

// Echo Drop reveal: fires when Echoes tab is opened and unseen echoes exist
async function maybeShowEchoDrop() {
    try {
        const data = await API.getEchoes();
        const unread = (data.echoes || []).filter(e => !e.seen && e.tier !== 'voice');
        if (unread.length === 0) return;
        const echo = unread[0];
        const titleEl = document.getElementById('echo-drop-title');
        const detailEl = document.getElementById('echo-drop-detail');
        const dropOverlay = document.getElementById('echo-drop-overlay');
        if (!dropOverlay) return;
        if (titleEl) titleEl.textContent = echo.message;
        if (detailEl) detailEl.textContent = echo.detail || 'Pattern detected across multiple weeks of voice data';
        dropOverlay.style.display = 'flex';
    } catch (e) {
        // silent
    }
}

// Initialize Echo Drop overlay button handlers (called once on page load)
function initEchoDropOverlay() {
    const ctaBtn = document.getElementById('echo-drop-cta');
    const skipBtn = document.getElementById('echo-drop-skip');
    const dropOverlay = document.getElementById('echo-drop-overlay');
    if (ctaBtn) {
        ctaBtn.addEventListener('click', () => {
            if (dropOverlay) dropOverlay.style.display = 'none';
            API.markEchoesSeen().then(() => updateEchoBadge());
            loadEchoesListView();
        });
    }
    if (skipBtn) {
        skipBtn.addEventListener('click', () => {
            if (dropOverlay) dropOverlay.style.display = 'none';
        });
    }
}

// Render a single echo item with tier-aware icon
function renderEchoItem(echo, variant) {
    const dateStr = new Date(echo.discovered_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    const tierClass = echo.tier === 'eureka' ? ' echo-eureka' : (echo.tier === 'voice' ? ' echo-voice' : '');
    const newClass = echo.seen ? '' : ' echo-new';
    let icon = '\u25cf'; // standard dot
    if (echo.tier === 'eureka') icon = '\u2728';
    else if (echo.tier === 'milestone') icon = '\u25cf';

    // Pattern card variant: type label above bold message
    if (variant === 'pattern') {
        const typeLabel = echo.tier === 'eureka' ? 'Eureka' : (echo.tier === 'milestone' ? 'Milestone' : 'Pattern');
        return `
        <div class="echo-item${newClass}${tierClass}">
            <span class="echo-icon">${icon}</span>
            <div class="echo-content">
                <div class="echo-type-label">${typeLabel}</div>
                <span class="echo-message">${sanitizeHTML(echo.message)}</span>
                <span class="echo-date">${dateStr}</span>
            </div>
        </div>`;
    }

    // Voice echo variant: message + date on same line
    return `
        <div class="echo-item${newClass}${tierClass}">
            <span class="echo-icon">${icon}</span>
            <div class="echo-content">
                <span class="echo-message">${sanitizeHTML(echo.message)}</span>
                <span class="echo-date">${dateStr}</span>
            </div>
        </div>`;
}

// Load full echoes list into #echoes-list-container (60/40 two-column layout)
async function loadEchoesListView() {
    const container = document.getElementById('echoes-list-container');
    if (!container) return;
    try {
        const [data, progressData] = await Promise.all([
            API.getEchoes(),
            API.getEchoProgress().catch(() => null)
        ]);
        if (!data.echoes || data.echoes.length === 0) {
            container.innerHTML = '<div class="echoes-empty">Echoes surface recurring patterns in your voice data \u2014 like stress spikes on certain days or calm streaks. They appear after 7+ days of readings.</div>';
            return;
        }

        const voiceEchoes = data.echoes.filter(e => e.tier === 'voice');
        const patternEchoes = data.echoes.filter(e => e.tier !== 'voice');

        // Left column: Voice Echoes
        let leftHtml = '<div class="echoes-column-left">';
        leftHtml += '<div class="echoes-section-header">Voice Echoes</div>';
        if (voiceEchoes.length > 0) {
            for (const echo of voiceEchoes) {
                leftHtml += renderEchoItem(echo, 'voice');
            }
        } else {
            leftHtml += '<div class="echoes-empty" style="font-size:13px;color:#5a6270;">No voice echoes yet. Keep recording to surface insights.</div>';
        }
        leftHtml += '</div>';

        // Right column: Patterns
        let rightHtml = '<div class="echoes-column-right">';
        rightHtml += '<div class="echoes-section-header">Patterns</div>';
        if (patternEchoes.length > 0) {
            // Sort: eureka first, then milestone, then standard
            const tierOrder = { eureka: 0, milestone: 1 };
            const sorted = [...patternEchoes].sort((a, b) => (tierOrder[a.tier] ?? 2) - (tierOrder[b.tier] ?? 2));
            for (const echo of sorted) {
                rightHtml += renderEchoItem(echo, 'pattern');
            }
        } else {
            rightHtml += '<div class="echoes-empty" style="font-size:13px;color:#5a6270;">Patterns emerge after consistent recordings over time.</div>';
        }

        // Progress teaser
        if (progressData && progressData.sessions_until_next_echo > 0) {
            rightHtml += `<div class="echoes-progress-teaser"><strong>${progressData.sessions_until_next_echo}</strong> more sessions until next pattern</div>`;
        } else if (progressData && progressData.pattern_hint) {
            rightHtml += `<div class="echoes-progress-teaser">Analyzing <strong>${sanitizeHTML(progressData.pattern_hint)}</strong> for new patterns</div>`;
        }

        rightHtml += '</div>';

        container.innerHTML = leftHtml + rightHtml;
    } catch (e) {
        container.innerHTML = '<div class="echoes-empty">Unable to load echoes.</div>';
    }
}

// Echoes view init: called when user navigates to echoes tab
async function initEchoesView() {
    await maybeShowEchoDrop();
    await loadEchoesListView();
}

// Legacy: load echoes in Trends view cards (does not mark seen)
async function loadEchoes() {
    try {
        const data = await API.getEchoes();
        const container = document.getElementById('echoes-container');
        if (!container) return;
        if (!data.echoes || data.echoes.length === 0) {
            container.innerHTML = '<div class="echoes-empty">Echoes surface recurring patterns in your voice data \u2014 like stress spikes on certain days or calm streaks. They appear after 7+ days of readings.</div>';
            return;
        }
        let html = '';
        for (const echo of data.echoes.slice(0, 5)) {
            const dateStr = new Date(echo.discovered_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
            html += `
                <div class="echo-item ${echo.seen ? '' : 'echo-new'}">
                    <span class="echo-icon">\u2728</span>
                    <div class="echo-content">
                        <span class="echo-message">${sanitizeHTML(echo.message)}</span>
                        <span class="echo-date">${dateStr}</span>
                    </div>
                </div>`;
        }
        container.innerHTML = html;
    } catch (e) {
        console.error('Failed to load echoes:', e);
    }
}

// Legacy alias kept for loadFeatures()
async function loadEchoesNotificationDot() {
    await updateEchoBadge();
}

// ========== Compass (Feature #7) ==========

async function loadCompass() {
    try {
        const data = await API.getCompass();
        const container = document.getElementById('compass-container');
        if (!container) return;

        if (!data.has_data) {
            container.innerHTML = '<div class="compass-empty">The Compass tracks your week-over-week trajectory \u2014 are you trending calmer, steadier, or more stressed? Updates every Monday.</div>';
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
            html += `<div class="compass-change compass-positive">+ ${sanitizeHTML(data.biggest_positive)}</div>`;
        }
        if (data.biggest_negative) {
            html += `<div class="compass-change compass-negative">- ${sanitizeHTML(data.biggest_negative)}</div>`;
        }

        // Intention input
        html += `<div class="compass-intention">
            <label class="compass-intention-label">This week's intention:</label>
            <div class="compass-intention-row">
                <input type="text" class="compass-intention-input" id="compass-intention-input"
                    placeholder="e.g., Take a 5-min break after meetings"
                    value="${sanitizeHTML(data.intention || '')}" maxlength="120" />
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

// ========== Waypoints (Feature #4) — in History view ==========

async function loadWaypoints() {
    try {
        const data = await API.getWaypoints();
        const waypointsView = document.getElementById('waypoints-view');
        if (!waypointsView) return;

        let waypointsContainer = document.getElementById('waypoints-container');

        if (!waypointsContainer) {
            waypointsView.innerHTML = `
                <div id="streak-insurance-card" class="dashboard-card" data-card-id="streak-insurance" style="display: none;">
                    <div class="streak-insurance-section glass-card">
                        <div class="streak-insurance-header">
                            <span class="streak-insurance-shield">&#x1F6E1;</span>
                            <div class="streak-insurance-info">
                                <span class="streak-insurance-title" id="streak-insurance-title">Resilience Day Available</span>
                                <span class="streak-insurance-desc" id="streak-insurance-desc">Your streak survives even if you miss a day</span>
                            </div>
                        </div>
                        <div class="streak-insurance-streak">
                            <span class="streak-insurance-number" id="streak-insurance-number">0</span>
                            <span class="streak-insurance-label">Day Streak</span>
                        </div>
                        <div class="streak-insurance-actions" id="streak-insurance-actions">
                            <button class="btn btn-primary streak-insurance-use-btn" onclick="useStreakInsurance()">Use Resilience Day</button>
                            <button class="btn streak-insurance-dismiss-btn" onclick="dismissStreakInsurance()">Not Now</button>
                        </div>
                    </div>
                </div>
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
                html += `<div class="${cls}" title="${sanitizeHTML(wp.description)}">
                    <div class="waypoint-dot">${wp.achieved ? '\u2713' : '\u25CB'}</div>
                    <span class="waypoint-name">${sanitizeHTML(wp.name)}</span>
                </div>`;
            }

            html += '</div></div>';
        }

        waypointsContainer.innerHTML = html;

        // Load streak insurance into waypoints view
        loadStreakInsurance();
    } catch (e) {
        console.error('Failed to load waypoints:', e);
    }
}

// ========== Sanctuary Moments (Feature #8) ==========

function triggerSanctuary(type, message) {
    const now = Date.now();
    if (now - AppState.lastSanctuaryTime < SANCTUARY_COOLDOWN) return; // 5 min debounce
    AppState.lastSanctuaryTime = now;

    const overlay = document.getElementById('sanctuary-overlay');
    const msgEl = document.getElementById('sanctuary-message');
    const particles = document.getElementById('sanctuary-particles');

    if (!overlay || !msgEl) return;

    msgEl.textContent = message;
    overlay.style.display = 'flex';
    overlay.classList.add('sanctuary-active');

    // Add leaf particles
    if (particles) {
        particles.textContent = '';
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
        if (particles) particles.textContent = '';
    }, 3000);
}

// ========== Linguistic Echo (Post-Recording Insight) ==========

function showLinguisticEcho(text) {
    if (!text) return;

    // Reuse or create toast element
    let toast = document.getElementById('linguistic-echo-toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'linguistic-echo-toast';
        toast.className = 'linguistic-echo-toast';
        toast.addEventListener('click', () => {
            toast.classList.remove('echo-visible');
        });
        document.body.appendChild(toast);
    }

    toast.innerHTML = `
        <div class="echo-label">VOICE ECHO</div>
        <div class="echo-text">${text}</div>
    `;

    // Trigger slide-up
    requestAnimationFrame(() => {
        toast.classList.add('echo-visible');
    });

    // Auto-dismiss after 8 seconds
    setTimeout(() => {
        toast.classList.remove('echo-visible');
    }, 8000);
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
    const calmEl = document.getElementById('calm-time');
    const steadyEl = document.getElementById('steady-time');
    const tenseEl = document.getElementById('tense-time');
    const stressedEl = document.getElementById('stressed-time');

    if (!summary) {
        if (calmEl) calmEl.textContent = '0 min';
        if (steadyEl) steadyEl.textContent = '0 min';
        if (tenseEl) tenseEl.textContent = '0 min';
        if (stressedEl) stressedEl.textContent = '0 min';
        return;
    }

    if (calmEl) calmEl.textContent = `${Math.round(summary.time_in_calm_min || 0)} min`;
    if (steadyEl) steadyEl.textContent = `${Math.round(summary.time_in_steady_min || 0)} min`;
    if (tenseEl) tenseEl.textContent = `${Math.round(summary.time_in_tense_min || 0)} min`;
    if (stressedEl) stressedEl.textContent = `${Math.round(summary.time_in_stressed_min || 0)} min`;
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

    const meetingCountEl = document.getElementById('meeting-count');
    if (meetingCountEl) meetingCountEl.textContent = meetings.length;

    const listHtml = meetings.map((meeting, idx) => {
        const startTime = new Date(meeting.start).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: false });
        const endTime = new Date(meeting.end).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: false });
        return `<div class="meeting-item"><span class="meeting-time">${startTime} - ${endTime}</span><span class="meeting-label">Meeting ${idx + 1}</span></div>`;
    }).join('');

    const meetingsListEl = document.getElementById('meetings-list');
    if (meetingsListEl) meetingsListEl.innerHTML = listHtml;
}

function updateCalibrationBanner(status) {
    const banner = document.getElementById('calibration-banner');
    const progress = document.getElementById('calibration-progress');
    if (!banner) return;

    if (!status || status.is_calibrated || (status.total_readings || 0) >= (status.min_readings || 10)) {
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
    if (progress) progress.textContent = `${status.total_readings || 0} readings collected (need ${status.min_readings || 10} minimum)`;
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
                        <span class="metric-name">${sanitizeHTML(m.label)}</span>
                        <span class="metric-value">${m.value}/${m.max}</span>
                    </div>
                    <div class="metric-bar-track">
                        <div class="metric-bar-fill ${barClass}" style="width: ${pct}%"></div>
                    </div>
                    <span class="metric-interpretation">${sanitizeHTML(m.interpretation)}</span>
                </div>`;
        }
        metricsGrid.innerHTML = html;
    }

    const zoneBar = card.querySelector('.briefing-zone-bar');
    const zoneLegend = card.querySelector('.briefing-zone-legend');
    if (zoneBar && data.zones) {
        const zoneLabels = { calm: 'Calm', steady: 'Steady', tense: 'Tense', stressed: 'Stressed' };
        let barHtml = '';
        let legendHtml = '';
        for (const z of ['calm', 'steady', 'tense', 'stressed']) {
            const info = data.zones[z];
            if (!info || info.pct === 0) continue;
            barHtml += `<div class="zone-segment" style="width: ${info.pct}%; background: ${ZONE_HEX[z]};" title="${zoneLabels[z]}: ${info.minutes} min (${info.pct}%)"></div>`;
            legendHtml += `<span class="zone-legend-item"><span class="zone-dot" style="background: ${ZONE_HEX[z]};"></span>${zoneLabels[z]} ${info.minutes}m (${info.pct}%)</span>`;
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
        highlightsList.innerHTML = data.highlights.map(h => `<li>${sanitizeHTML(h)}</li>`).join('');
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
                toggle.textContent = isExpanded ? '\u25BC' : '\u25B2';
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

// [Q-055] loadFirstSpark removed — first-spark-card HTML element no longer exists

// Weekly Wrapped card + overlay moved to overlays.js

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
    if (zone === AppState.lastBeaconZone) return;
    AppState.lastBeaconZone = zone;

    const color = ZONE_HEX[zone] || ZONE_HEX.idle;

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
    document.title = `${zoneEmoji[zone] || ''} Lucid`;
}

// Morning/Evening summaries moved to overlays.js


// Speaker enrollment/enhance code moved to speaker_enrollment.js

// ========== Voice Wellness Report (PDF) ==========

function downloadReport() {
    // Open the PDF endpoint in a new tab to trigger download
    window.open('/api/report/pdf?days=90', '_blank');
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

// Close overlays on Escape (priority-ordered: only one closes per keypress)
document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;

    // Readiness overlay (highest priority)
    const readiness = document.getElementById('readiness-overlay');
    if (readiness && readiness.style.display !== 'none' && readiness.style.display !== '') {
        dismissReadinessOverlay();
        return;
    }

    // Settings panel
    const settings = document.getElementById('settings-panel');
    if (settings && settings.style.display !== 'none' && settings.style.display !== '') {
        settings.style.display = 'none';
        return;
    }

    // Enrollment overlay
    const enrollment = document.getElementById('enrollment-overlay');
    if (enrollment && enrollment.style.display !== 'none' && enrollment.style.display !== '') {
        closeEnrollment();
        return;
    }

    // Enhance overlay
    const enhance = document.getElementById('enhance-overlay');
    if (enhance && enhance.style.display !== 'none' && enhance.style.display !== '') {
        closeEnhanceOverlay();
        return;
    }

    // Morning summary
    const morning = document.getElementById('morning-summary-overlay');
    if (morning && morning.style.display !== 'none' && morning.style.display !== '') {
        dismissMorningSummary();
        return;
    }

    // Evening summary
    const evening = document.getElementById('evening-summary-overlay');
    if (evening && evening.style.display !== 'none' && evening.style.display !== '') {
        dismissEveningSummary();
        return;
    }

    // Science modal (lowest priority)
    closeScienceModal();
});

// ========== First Light — Removed ==========
// Stub functions kept for any residual calls
function initFirstLight() {}
function completeFirstLightTask() {}

// ========== Analytics Tracking ==========

function setupAnalyticsTracking() {
    // Track button clicks via delegated event listener
    const TRACKED_BUTTONS = {
        'settings-btn': 'settings_open',
        'settings-close-btn': 'settings_close',
        'export-readings-btn': 'export_csv',
        'export-summaries-btn': 'export_csv',
        'export-json-btn': 'export_json',
        'speaker-setup-btn': 'enrollment_start',
        'speaker-enhance-btn': 'enrollment_enhance',
        'speaker-delete-btn': 'speaker_delete',
        'speaker-reset-btn': 'enrollment_reset',
        'enhance-record-btn': 'enrollment_enhance_record',
    };

    document.addEventListener('click', (e) => {
        const btn = e.target.closest('button, [onclick]');
        if (!btn) return;

        const id = btn.id;
        if (id && TRACKED_BUTTONS[id]) {
            API.track('button_click', {
                button_id: TRACKED_BUTTONS[id],
                context_view: AppState.currentView
            });
            return;
        }

        // Track specific onclick handlers by class or data attributes
        if (btn.classList.contains('grove-revive-btn')) {
            API.track('button_click', { button_id: 'grove_revive', context_view: 'grove' });
        } else if (btn.classList.contains('compass-intention-btn')) {
            API.track('button_click', { button_id: 'compass_set_intention', context_view: AppState.currentView });
        } else if (btn.classList.contains('briefing-toggle')) {
            const expanded = btn.getAttribute('aria-expanded') === 'true';
            API.track('button_click', {
                button_id: expanded ? 'briefing_collapse' : 'briefing_expand',
                context_view: AppState.currentView
            });
        }
    });

    // Track errors from API calls
    const origApiCall = window.apiCall;
    if (origApiCall) {
        window.apiCall = async function(endpoint, options) {
            try {
                return await origApiCall(endpoint, options);
            } catch (err) {
                API.track('error', {
                    error_type: 'api_error',
                    error_message: err.message || String(err),
                    context: endpoint
                });
                throw err;
            }
        };
    }
}

// ======================================================================
// Self-Assessment Prompt (Ground Truth Collection)
// ======================================================================
// Periodically asks "How are you feeling?" and stores the response
// for zone calibration. At most every 6 hours. Non-intrusive modal.

let _selfAssessmentDismissed = false;

async function checkSelfAssessmentPrompt() {
    if (_selfAssessmentDismissed) return;
    try {
        const status = await API.getSelfAssessmentStatus();
        if (status && status.should_prompt) {
            showSelfAssessmentModal(status.nearest_reading_id);
        }
    } catch (e) {
        // Silently ignore — this is optional
    }
}

function showSelfAssessmentModal(readingId) {
    // Don't show if already visible
    if (document.getElementById('self-assessment-modal')) return;

    const modal = document.createElement('div');
    modal.id = 'self-assessment-modal';
    modal.style.cssText = `
        position: fixed; bottom: 20px; right: 20px; z-index: 10000;
        background: #1a1d21; border: 1px solid #2a2d31; border-radius: 12px;
        padding: 20px; width: 280px; box-shadow: 0 8px 32px rgba(0,0,0,0.4);
        font-family: 'Inter', -apple-system, sans-serif; color: #e4e8ec;
        animation: slideInUp 0.3s ease-out;
    `;

    modal.innerHTML = `
        <style>
            @keyframes slideInUp {
                from { transform: translateY(20px); opacity: 0; }
                to { transform: translateY(0); opacity: 1; }
            }
            .sa-btn {
                display: block; width: 100%; padding: 10px; margin: 4px 0;
                border: 1px solid #2a2d31; border-radius: 8px; background: transparent;
                color: #e4e8ec; font-size: 13px; cursor: pointer; text-align: left;
                transition: background 0.15s, border-color 0.15s;
            }
            .sa-btn:hover { background: rgba(91,141,184,0.15); border-color: #5B8DB8; }
        </style>
        <div style="font-size: 14px; font-weight: 600; margin-bottom: 12px; color: #fff;">
            How are you feeling right now?
        </div>
        <div style="font-size: 12px; color: #5a6270; margin-bottom: 12px;">
            This helps calibrate your zone accuracy.
        </div>
        <button class="sa-btn" data-zone="calm">Calm — relaxed, at ease</button>
        <button class="sa-btn" data-zone="steady">Steady — neutral, fine</button>
        <button class="sa-btn" data-zone="tense">Tense — some pressure</button>
        <button class="sa-btn" data-zone="stressed">Stressed — overwhelmed</button>
        <div style="text-align: right; margin-top: 8px;">
            <button id="sa-dismiss" style="background: none; border: none; color: #5a6270;
                font-size: 11px; cursor: pointer; padding: 4px 8px;">Not now</button>
        </div>
    `;

    document.body.appendChild(modal);

    // Handle zone selection
    modal.querySelectorAll('.sa-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const zone = btn.dataset.zone;
            try {
                await API.submitSelfAssessment(zone, readingId);
                API.track('self_assessment', { zone });
            } catch (e) {
                // Silently ignore
            }
            modal.remove();
            _selfAssessmentDismissed = true;
        });
    });

    // Dismiss button
    document.getElementById('sa-dismiss').addEventListener('click', () => {
        modal.remove();
        _selfAssessmentDismissed = true;
        // Reset after 2 hours so it can prompt again
        TimerRegistry.setTimeout('self-assessment', () => { _selfAssessmentDismissed = false; }, 2 * 60 * 60 * 1000);
    });
}

// Check for self-assessment prompt every 30 minutes
TimerRegistry.setInterval('global', checkSelfAssessmentPrompt, 30 * 60 * 1000);
// Also check 60 seconds after startup
TimerRegistry.setTimeout('global', checkSelfAssessmentPrompt, 60 * 1000);

// ========== Topic Correlations (Phase 2) ==========

async function loadTopicCorrelations() {
    const container = document.getElementById('topic-correlations-container');
    if (!container) return;

    try {
        const data = await API.getTopicStress();

        if (!data.has_data || !data.topics || Object.keys(data.topics).length === 0) {
            container.innerHTML = '<div class="echoes-empty">Topic correlations appear after 7+ days of readings. Lucid will show how stress relates to work, relationships, and health topics in your speech.</div>';
            return;
        }

        const baseline = data.baseline_stress || 50;
        const topicLabels = { work: 'Work', relationships: 'Relationships', health: 'Health' };

        let html = '<div class="topic-correlations">';
        html += `<div class="topic-baseline" style="font-size: 11px; color: var(--secondary-text); margin-bottom: 8px;">Baseline stress: ${baseline}</div>`;

        for (const [topic, info] of Object.entries(data.topics)) {
            const delta = info.delta;
            const isHigher = delta > 0;
            const color = isHigher ? 'var(--tense-color, #DD8452)' : 'var(--calm-color, #5B8DB8)';
            const sign = isHigher ? '+' : '';
            const label = topicLabels[topic] || topic;
            const barPct = Math.min(100, Math.abs(delta) / 30 * 100);

            html += `
                <div class="topic-row" style="margin-bottom: 8px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 3px;">
                        <span style="font-size: 13px; font-weight: 500;">${sanitizeHTML(label)}</span>
                        <span style="font-size: 12px; color: ${color}; font-weight: 600;">${sign}${delta} stress</span>
                    </div>
                    <div style="background: var(--detail-gray, #e4e8ec); border-radius: 4px; height: 5px;">
                        <div style="background: ${color}; width: ${barPct}%; height: 100%; border-radius: 4px; transition: width 0.5s;"></div>
                    </div>
                    <div style="font-size: 10px; color: var(--secondary-text); margin-top: 2px;">${info.reading_count} readings</div>
                </div>`;
        }
        html += '</div>';

        // Absolutist language insight (if data available)
        container.innerHTML = html;
    } catch (e) {
        console.error('Failed to load topic correlations:', e);
    }
}

// ========== Meeting Impact (Phase 1) ==========

async function loadMeetingImpact() {
    const container = document.getElementById('meeting-impact-container');
    if (!container) return;

    try {
        const data = await API.getMeetingVsNonMeeting();

        if (!data.has_data || !data.meeting || data.meeting.reading_count < 3) {
            container.innerHTML = '<div class="echoes-empty" style="font-size: 12px;">Meeting impact analysis appears once you have 3+ meeting readings. Make sure the meeting detector is active.</div>';
            return;
        }

        const delta = data.delta;
        const stressDelta = delta.stress;
        const color = stressDelta > 5 ? 'var(--stressed-color, #C44E52)' :
                      stressDelta > 2 ? 'var(--tense-color, #DD8452)' :
                      stressDelta < -2 ? 'var(--calm-color, #5B8DB8)' : 'var(--secondary-text, #5a6270)';
        const sign = stressDelta > 0 ? '+' : '';

        container.innerHTML = `
            <div class="meeting-impact">
                <div style="display: flex; justify-content: space-between; margin-bottom: 10px;">
                    <div style="text-align: center;">
                        <div style="font-size: 22px; font-weight: 700; color: var(--tense-color, #DD8452);">${data.meeting.avg_stress || '—'}</div>
                        <div style="font-size: 11px; color: var(--secondary-text);">During meetings</div>
                        <div style="font-size: 10px; color: var(--secondary-text);">${data.meeting.reading_count} readings</div>
                    </div>
                    <div style="text-align: center;">
                        <div style="font-size: 22px; font-weight: 700; color: ${color};">${sign}${stressDelta}</div>
                        <div style="font-size: 11px; color: var(--secondary-text);">vs. non-meeting</div>
                    </div>
                    <div style="text-align: center;">
                        <div style="font-size: 22px; font-weight: 700; color: var(--calm-color, #5B8DB8);">${data.non_meeting.avg_stress || '—'}</div>
                        <div style="font-size: 11px; color: var(--secondary-text);">Non-meeting</div>
                        <div style="font-size: 10px; color: var(--secondary-text);">${data.non_meeting.reading_count} readings</div>
                    </div>
                </div>
                <div style="font-size: 12px; color: var(--secondary-text); text-align: center; font-style: italic;">${sanitizeHTML(delta.interpretation || '')}</div>
            </div>`;
    } catch (e) {
        console.error('Failed to load meeting impact:', e);
    }
}


