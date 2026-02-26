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
    calm: '#5a9a6e',
    steady: '#b5a84a',
    tense: '#d4943a',
    stressed: '#c4584c',
    idle: '#888888',
};

// Constants (not part of mutable state)
const SPEECH_THRESHOLD_SEC = 30;
const SANCTUARY_COOLDOWN = 300000; // 5 min
const FIRST_LIGHT_TASKS = ['canopy', 'rings', 'grove', 'faq', 'trends'];
const HERO_RING_CIRCUMFERENCE = 2 * Math.PI * 54; // ~339.3

// ========== AppState — single namespace for all mutable state ==========
window.AppState = {
    // Current view
    currentView: 'today',
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

    // Previous zone for transition detection
    previousZone: null,

    // Canopy score reveal state
    canopyRevealed: false,
    prevCanopyScore: 0,

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

    // Evening summary state
    eveningSummaryShown: false,

    // Analysis error toast state (avoid spamming same error)
    lastShownAnalysisError: null,

    // Enrollment auto-prompt guard
    enrollmentAutoPrompted: false,

    // Hero ring analyzing state
    heroAnalyzingActive: false,
    heroAnalyzeRAF: null,
    heroAnalyzeStart: 0,

    // Canopy progress circle state
    canopyIsAnalyzing: false,
    canopyProgressRAF: null,
    canopyProgressStart: 0,
    canopyProgressSafetyTimer: null,
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

    // 3. Setup UI event handlers and static content
    setupNavigation();
    setupSettings();
    setupBriefingCards();
    setupInfoButtons();
    updateCurrentDate();
    updateDailyGreeting();

    // 4. Wait for backend readiness, then load data and start polling
    await waitForBackend();
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
                        initFirstLight(),
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
            // First Light quest tracking
            if (view === 'faq') completeFirstLightTask('faq');
            if (view === 'trends') completeFirstLightTask('trends');
        });
    });
}

function switchView(view) {
    // Stop polling intervals when leaving the today view
    if (AppState.currentView === 'today' && view !== 'today') {
        stopPolling();
    }

    document.querySelectorAll('.sidebar-icon[data-view]').forEach(icon => {
        icon.classList.toggle('active', icon.dataset.view === view);
    });

    document.querySelectorAll('.view').forEach(viewEl => {
        viewEl.classList.toggle('active', viewEl.id === `${view}-view`);
    });

    AppState.currentView = view;

    // Restart polling when returning to the today view
    if (view === 'today') {
        startPolling();
        loadTodayData();
    }

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
    if (!dateEl) return;
    const now = new Date();
    const options = { weekday: 'short', month: 'short', day: 'numeric' };
    dateEl.textContent = now.toLocaleDateString('en-US', options);
}

// ========== Polling ==========

function stopPolling() {
    if (AppState.pollInterval) {
        clearTimeout(AppState.pollInterval);
        AppState.pollInterval = null;
    }
    if (AppState.statusPollInterval) {
        clearTimeout(AppState.statusPollInterval);
        AppState.statusPollInterval = null;
    }
}

// Exponential backoff state for status polling
let _statusPollDelay = 2000;
let _statusPollFailures = 0;
const _STATUS_POLL_MIN = 2000;
const _STATUS_POLL_MAX = 30000;

function _scheduleStatusPoll() {
    AppState.statusPollInterval = setTimeout(async () => {
        await pollStatus();
        _scheduleStatusPoll();
    }, _statusPollDelay);
}

function _scheduleDataPoll() {
    AppState.pollInterval = setTimeout(() => {
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
        if (status.is_analyzing && !AppState.canopyIsAnalyzing) {
            startCanopyProgress();
        }
        // Finish progress circle when backend stops analyzing
        if (!status.is_analyzing && AppState.canopyIsAnalyzing) {
            finishCanopyProgress();
        }
        // Gauge ring animations
        if (status.is_analyzing && !gaugesAreAnalyzing) startGaugeProgress();
        if (!status.is_analyzing && gaugesAreAnalyzing) {
            finishGaugeProgress();
            // Small delay to let backend persist reading before fetching
            setTimeout(() => loadTodayData(), 500);
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

        // --- Speak Hero / Daily Greeting Logic ---
        const totalReadings = data.total_readings || 0;
        const todayReadings = data.readings ? data.readings.length : 0;

        if (totalReadings === 0 && todayReadings === 0) {
            // First-time-ever: show hero card
            if (!AppState.speakHeroVisible) showSpeakHero();
        } else if (AppState.speakHeroVisible && todayReadings >= 1) {
            // First reading just arrived — celebrate and dismiss hero
            hideSpeakHero(true);
        }

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
            if (AppState.previousZone === 'stressed' && (currentZone === 'calm' || currentZone === 'steady')) {
                triggerSanctuary('calm_shift', 'You found your calm');
            } else if (AppState.previousZone === 'tense' && currentZone === 'calm') {
                triggerSanctuary('calm_shift', 'Tension released. Well done.');
            }
            AppState.previousZone = currentZone;

            // First reading of the day
            if (data.readings.length === 1 && !AppState.canopyRevealed) {
                triggerSanctuary('first_reading', 'Your voice has been heard');
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
    // Load features in parallel
    Promise.allSettled([
        loadRhythmRings(),
        loadRecoveryPulse(),
        loadEchoes(),
        loadCompass(),
        loadCapsules(),
        updateGrove(),
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
            AppState.canopyRevealed = false; // Reset so animation fires on score unlock
        } else {
            // Show score (but not while progress circle is active)
            if (progressState) progressState.style.display = 'none';
            if (!AppState.canopyIsAnalyzing && scoreEl) scoreEl.style.display = '';

            if (!AppState.canopyRevealed) {
                AppState.canopyRevealed = true;
                animateCountUp(scoreEl, data.score, 3000);
            } else if (data.score !== AppState.prevCanopyScore) {
                scoreEl.textContent = '0';
                animateCountUp(scoreEl, data.score, 1500);
            }
            AppState.prevCanopyScore = data.score;
            if (profileEl) profileEl.textContent = data.profile || '';
        }
    } catch (e) {
        console.error('Failed to load canopy score:', e);
    }
}

function animateCountUp(el, target, duration, fromValue = 0) {
    const start = fromValue;
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

// ========== Canopy Progress Circle ==========

// canopyIsAnalyzing, canopyProgressRAF, canopyProgressStart, canopyProgressSafetyTimer are in AppState

function startCanopyProgress() {
    const circle = document.getElementById('canopy-progress-circle');
    const arc = document.getElementById('canopy-progress-arc');
    const scoreEl = document.getElementById('canopy-score');
    if (!circle || !arc) return;

    AppState.canopyIsAnalyzing = true;
    circle.style.display = 'flex';
    if (scoreEl) scoreEl.style.display = 'none';

    arc.style.transition = 'none';
    arc.style.strokeDashoffset = '326.7';

    AppState.canopyProgressStart = performance.now();
    if (AppState.canopyProgressRAF) cancelAnimationFrame(AppState.canopyProgressRAF);

    // Safety timeout: auto-dismiss after 25s no matter what
    if (AppState.canopyProgressSafetyTimer) clearTimeout(AppState.canopyProgressSafetyTimer);
    AppState.canopyProgressSafetyTimer = setTimeout(() => {
        if (AppState.canopyIsAnalyzing) finishCanopyProgress();
    }, 25000);

    function tick(now) {
        const elapsed = now - AppState.canopyProgressStart;
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

        if (AppState.canopyIsAnalyzing) {
            AppState.canopyProgressRAF = requestAnimationFrame(tick);
        }
    }

    AppState.canopyProgressRAF = requestAnimationFrame(tick);
}

function finishCanopyProgress() {
    const circle = document.getElementById('canopy-progress-circle');
    const arc = document.getElementById('canopy-progress-arc');
    const scoreEl = document.getElementById('canopy-score');
    if (!arc) return;

    // Keep canopyIsAnalyzing true during the 500ms close transition
    // so loadCanopyScore() won't prematurely show the score element
    if (AppState.canopyProgressRAF) {
        cancelAnimationFrame(AppState.canopyProgressRAF);
        AppState.canopyProgressRAF = null;
    }
    if (AppState.canopyProgressSafetyTimer) {
        clearTimeout(AppState.canopyProgressSafetyTimer);
        AppState.canopyProgressSafetyTimer = null;
    }

    // Snap to 100%
    arc.style.transition = 'stroke-dashoffset 0.4s ease-out';
    arc.style.strokeDashoffset = '0';

    // After transition: hide circle, show score, refresh canopy data
    setTimeout(() => {
        AppState.canopyIsAnalyzing = false;
        if (circle) circle.style.display = 'none';
        if (scoreEl) scoreEl.style.display = '';
        // Force a fresh canopy score fetch so count-up fires immediately
        loadCanopyScore();
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
            container.innerHTML = '<div class="echoes-empty">Echoes surface recurring patterns in your voice data \u2014 like stress spikes on certain days or calm streaks. They appear after 7+ days of readings.</div>';
            return;
        }

        let html = '';

        for (const echo of data.echoes.slice(0, 5)) {
            const dateStr = new Date(echo.discovered_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
            html += `
                <div class="echo-item ${echo.seen ? '' : 'echo-new'}">
                    <span class="echo-icon">\u{2728}</span>
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
                    <span class="capsule-message">${sanitizeHTML(capsule.message)}</span>
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
                html += `<div class="${cls}" title="${sanitizeHTML(wp.description)}">
                    <div class="waypoint-dot">${wp.achieved ? '\u2713' : '\u25CB'}</div>
                    <span class="waypoint-name">${sanitizeHTML(wp.name)}</span>
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

            // First Light quest tracking
            const infoKey = btn.dataset.info;
            if (infoKey && FIRST_LIGHT_TASKS.includes(infoKey)) {
                completeFirstLightTask(infoKey);
            }
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
    if (!settingsBtn || !settingsPanel || !closeBtn) return;

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
    const speakerEnhanceBtn = document.getElementById('speaker-enhance-btn');
    if (speakerEnhanceBtn) {
        speakerEnhanceBtn.addEventListener('click', () => openEnhanceOverlay());
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
                a.download = 'attune-export.json';
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
}

// [Q-055] loadFirstSpark removed — first-spark-card HTML element no longer exists

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
            <div class="wrapped-summary-line">${sanitizeHTML(data.summary_line)}</div>
            <div class="wrapped-canopy">
                <span class="wrapped-canopy-score">${data.canopy.avg}</span>
                <span class="wrapped-canopy-label">Avg Canopy</span>
                <span class="wrapped-canopy-trend" style="color: ${trendColor}">${trendIcon} ${data.canopy.trend > 0 ? '+' : ''}${data.canopy.trend}</span>
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
            { key: 'avg_mood', label: 'Wellbeing', color: '#b8975c' },
            { key: 'avg_energy', label: 'Activation', color: '#b5a84a' },
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

// ========== Evening Summary Overlay ==========

function shouldShowEveningSummary() {
    const hour = new Date().getHours();
    if (hour < 20) return false; // Only 8 PM or later

    const todayKey = `attune_evening_seen_${new Date().toISOString().slice(0, 10)}`;
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

    // Canopy ring + score
    const canopy = data.canopy;
    const scoreEl = document.getElementById('evening-canopy-score');
    const verdictEl = document.getElementById('evening-canopy-verdict');
    const arcEl = document.getElementById('evening-ring-arc');
    const deltaEl = document.getElementById('evening-canopy-delta');

    if (canopy && canopy.has_data) {
        const score = Math.round(canopy.score);
        animateEveningScore(scoreEl, score, 2000);
        // Animate arc (circumference = 2π × 110 ≈ 691.2)
        const offset = 691.2 * (1 - score / 100);
        setTimeout(() => { arcEl.style.strokeDashoffset = offset; }, 200);
        // Verdict
        let verdict = 'Needs Attention';
        if (score >= 80) verdict = 'Excellent';
        else if (score >= 65) verdict = 'Good';
        else if (score >= 50) verdict = 'Fair';
        verdictEl.textContent = verdict;
        // Delta vs yesterday
        if (data.canopy_delta != null) {
            deltaEl.style.display = 'block';
            const sign = data.canopy_delta >= 0 ? '+' : '';
            deltaEl.textContent = `${sign}${data.canopy_delta} pts vs yesterday`;
            deltaEl.className = 'evening-canopy-delta ' +
                (data.canopy_delta > 0 ? 'positive' : data.canopy_delta < 0 ? 'negative' : 'neutral');
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
        stressDeltaEl.textContent = '—';
    }

    // Stats row 2
    const speechMin = data.total_speech_min || 0;
    const speechH = Math.floor(speechMin / 60);
    const speechM = speechMin % 60;
    document.getElementById('evening-voice-time').textContent =
        speechH > 0 ? `${speechH}h ${speechM}m` : `${speechM}m`;

    document.getElementById('evening-peak-hour').textContent = data.peak_stress_hour || '—';
    document.getElementById('evening-reading-count').textContent = data.reading_count || '—';

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
    const todayKey = `attune_evening_seen_${new Date().toISOString().slice(0, 10)}`;
    localStorage.setItem(todayKey, '1');

    // Clean up old keys (>7 days)
    for (let i = 8; i <= 30; i++) {
        const old = new Date();
        old.setDate(old.getDate() - i);
        localStorage.removeItem(`attune_evening_seen_${old.toISOString().slice(0, 10)}`);
    }
}

function animateEveningScore(el, target, duration) {
    const start = Date.now();
    const tick = () => {
        const progress = Math.min((Date.now() - start) / duration, 1);
        const ease = 1 - Math.pow(1 - progress, 3);
        el.textContent = Math.round(ease * target);
        if (progress < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
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
            await Promise.all([
                API.setNotifPref('quiet_start', start.value),
                API.setNotifPref('quiet_end', end.value),
            ]);
        } catch (e) {
            console.error('Failed to save quiet hours:', e);
        }
    }
}


// ========== Speaker Verification — Voice Profile ==========

async function loadSpeakerStatus() {
    const badge = document.getElementById('speaker-status-badge');
    const setupBtn = document.getElementById('speaker-setup-btn');
    const enhanceBtn = document.getElementById('speaker-enhance-btn');
    const deleteBtn = document.getElementById('speaker-delete-btn');
    if (!badge) return;

    try {
        const status = await API.getSpeakerStatus();
        if (status.enrolled) {
            badge.textContent = 'Active';
            badge.className = 'speaker-badge speaker-badge-active';
            setupBtn.textContent = 'Re-enroll Voice Profile';
            if (enhanceBtn) enhanceBtn.style.display = 'block';
            deleteBtn.style.display = 'block';
        } else {
            badge.textContent = 'Not Set Up';
            badge.className = 'speaker-badge speaker-badge-inactive';
            setupBtn.textContent = 'Set Up Voice Profile';
            if (enhanceBtn) enhanceBtn.style.display = 'none';
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
    isListening: false,
    speechStartTime: null,
    smoothedRms: 0,
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
    const countdown = document.getElementById('enrollment-countdown');
    const statusLabel = document.getElementById('enrollment-status-label');
    countdown.className = 'enrollment-countdown';
    countdown.textContent = '10';
    if (statusLabel) statusLabel.textContent = 'Preparing microphone...';

    // Reset level bars
    document.querySelectorAll('#enrollment-level-bars .level-bar').forEach(bar => {
        bar.classList.remove('active');
        bar.style.height = '4px';
    });

    // Show recorder, hide processing/done
    document.getElementById('enrollment-recorder').style.display = 'block';
    document.getElementById('enrollment-processing').style.display = 'none';
    document.getElementById('enrollment-done').style.display = 'none';
    document.getElementById('enrollment-steps').querySelector('.step-indicators').style.display = 'flex';

    // Auto-start listening for this step
    startListening();
}

async function startListening() {
    if (enrollmentState.isListening || enrollmentState.isRecording) return;

    const statusLabel = document.getElementById('enrollment-status-label');

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

        // Set up audio context
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        enrollmentState.audioContext = audioCtx;
        const source = audioCtx.createMediaStreamSource(stream);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
        enrollmentState.analyserNode = analyser;

        // Use ScriptProcessorNode to capture raw PCM at 16kHz
        const bufferSize = 4096;
        const scriptNode = audioCtx.createScriptProcessor(bufferSize, 1, 1);
        enrollmentState.chunks = [];

        scriptNode.onaudioprocess = (e) => {
            if (!enrollmentState.isRecording) return; // Only capture during recording phase
            const channelData = e.inputBuffer.getChannelData(0);
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

        enrollmentState.isListening = true;
        enrollmentState.speechStartTime = null;
        enrollmentState.smoothedRms = 0;

        if (statusLabel) statusLabel.textContent = 'Start speaking when ready...';

        // Start level bar animation (runs during both listening and recording)
        drawEnrollmentLevelBars();

    } catch (e) {
        console.error('Microphone access denied:', e);
        if (statusLabel) statusLabel.textContent = 'Microphone access required';
    }
}

function beginRecording() {
    if (enrollmentState.isRecording) return;

    const countdown = document.getElementById('enrollment-countdown');
    const statusLabel = document.getElementById('enrollment-status-label');

    enrollmentState.isRecording = true;
    enrollmentState.isListening = false;
    enrollmentState.chunks = [];

    if (statusLabel) statusLabel.textContent = 'Recording...';
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
    const statusLabel = document.getElementById('enrollment-status-label');

    if (statusLabel) statusLabel.textContent = 'Uploading...';

    try {
        // Send raw PCM bytes to server
        const result = await Promise.race([
            API.enrollSpeakerSample(combined.buffer, moodLabel),
            new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 30000))
        ]);

        if (step < enrollmentState.totalSteps) {
            // Move to next step
            enrollmentState.currentStep = step + 1;
            updateEnrollmentUI();
        } else {
            // All samples collected — compute centroid
            showEnrollmentProcessing();
            const enrollResult = await Promise.race([
                API.completeSpeakerEnrollment(),
                new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 30000))
            ]);
            showEnrollmentDone();
            // Hide enrollment-required banner
            const banner = document.getElementById('enrollment-required-banner');
            if (banner) banner.style.display = 'none';
        }
    } catch (e) {
        console.error('Enrollment step failed:', e);
        const isLoading = e.status === 503 || (e.message && e.message.includes('loading'));
        if (isLoading) {
            if (statusLabel) {
                statusLabel.textContent = 'Models still loading — please wait...';
                statusLabel.removeAttribute('data-retry');
            }
            setTimeout(() => startListening(), 3000);
            return;
        }
        const msg = e.message === 'timeout'
            ? 'Request timed out — tap to retry'
            : 'Failed — tap to retry';
        if (statusLabel) {
            statusLabel.textContent = msg;
            statusLabel.setAttribute('data-retry', 'true');
            statusLabel.onclick = () => {
                statusLabel.onclick = null;
                statusLabel.removeAttribute('data-retry');
                startListening();
            };
        }
    }
}

function stopRecordingCleanup() {
    enrollmentState.isRecording = false;
    enrollmentState.isListening = false;
    enrollmentState.speechStartTime = null;
    enrollmentState.smoothedRms = 0;

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

// ========== Enhance Voice Profile ==========

const enhancePrompts = [
    "Speak as if you're on a video call — slightly louder and clearer than normal.",
    "Talk softly, as if someone is sleeping nearby.",
    "Describe what you had for lunch today, with natural energy.",
    "Read this aloud in a tired, end-of-day voice: 'I'm wrapping up for today and heading out soon.'",
    "Say something with enthusiasm, like telling a friend exciting news.",
];

let enhanceState = {
    isRecording: false,
    chunks: [],
    audioStream: null,
    audioContext: null,
    analyserNode: null,
    scriptNode: null,
    sourceNode: null,
    animFrameId: null,
    countdownInterval: null,
    sampleCount: 0,
};

function openEnhanceOverlay() {
    const overlay = document.getElementById('enhance-overlay');
    overlay.style.display = 'flex';
    enhanceState.sampleCount = 0;
    prepareEnhanceSample();

    document.getElementById('enhance-close-btn').onclick = closeEnhanceOverlay;
    document.getElementById('enhance-record-btn').onclick = startEnhanceRecording;
    document.getElementById('enhance-another-btn').onclick = () => {
        enhanceState.sampleCount++;
        prepareEnhanceSample();
    };
    document.getElementById('enhance-finish-btn').onclick = closeEnhanceOverlay;
}

function prepareEnhanceSample() {
    const prompt = enhancePrompts[enhanceState.sampleCount % enhancePrompts.length];
    document.getElementById('enhance-prompt').textContent = prompt;
    document.getElementById('enhance-recorder').style.display = 'block';
    document.getElementById('enhance-processing').style.display = 'none';
    document.getElementById('enhance-done').style.display = 'none';
    const btn = document.getElementById('enhance-record-btn');
    btn.textContent = 'Start Recording';
    btn.disabled = false;
    btn.classList.remove('recording');
    document.getElementById('enhance-countdown').textContent = '10';
    document.getElementById('enhance-countdown').className = 'enrollment-countdown';
}

async function startEnhanceRecording() {
    if (enhanceState.isRecording) return;
    const btn = document.getElementById('enhance-record-btn');
    const countdown = document.getElementById('enhance-countdown');

    try {
        const stream = await navigator.mediaDevices.getUserMedia({
            audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true }
        });
        enhanceState.audioStream = stream;

        const audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        enhanceState.audioContext = audioCtx;
        const source = audioCtx.createMediaStreamSource(stream);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
        enhanceState.analyserNode = analyser;

        // Waveform animation
        drawEnhanceWaveform();

        const bufferSize = 4096;
        const scriptNode = audioCtx.createScriptProcessor(bufferSize, 1, 1);
        enhanceState.chunks = [];
        scriptNode.onaudioprocess = (e) => {
            if (!enhanceState.isRecording) return;
            const channelData = e.inputBuffer.getChannelData(0);
            const int16 = new Int16Array(channelData.length);
            for (let i = 0; i < channelData.length; i++) {
                const s = Math.max(-1, Math.min(1, channelData[i]));
                int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
            }
            enhanceState.chunks.push(int16);
        };
        source.connect(scriptNode);
        scriptNode.connect(audioCtx.destination);
        enhanceState.scriptNode = scriptNode;
        enhanceState.sourceNode = source;

        enhanceState.isRecording = true;
        btn.textContent = 'Recording...';
        btn.classList.add('recording');
        btn.disabled = true;
        countdown.className = 'enrollment-countdown active';

        let remaining = 10;
        countdown.textContent = remaining;
        enhanceState.countdownInterval = setInterval(() => {
            remaining--;
            countdown.textContent = remaining;
            if (remaining <= 0) {
                clearInterval(enhanceState.countdownInterval);
                finishEnhanceRecording();
            }
        }, 1000);
    } catch (e) {
        console.error('Microphone access denied:', e);
        btn.textContent = 'Microphone Access Required';
        btn.disabled = true;
    }
}

async function finishEnhanceRecording() {
    enhanceState.isRecording = false;
    if (enhanceState.animFrameId) {
        cancelAnimationFrame(enhanceState.animFrameId);
        enhanceState.animFrameId = null;
    }

    const totalLength = enhanceState.chunks.reduce((acc, c) => acc + c.length, 0);
    const combined = new Int16Array(totalLength);
    let offset = 0;
    for (const chunk of enhanceState.chunks) {
        combined.set(chunk, offset);
        offset += chunk.length;
    }

    cleanupEnhanceAudio();

    document.getElementById('enhance-recorder').style.display = 'none';
    document.getElementById('enhance-processing').style.display = 'block';

    try {
        const moodLabel = `enhance_${enhanceState.sampleCount}`;
        await API.enrollSpeakerSample(combined.buffer, moodLabel);
        await API.completeSpeakerEnrollment();
        document.getElementById('enhance-processing').style.display = 'none';
        document.getElementById('enhance-done').style.display = 'block';
    } catch (e) {
        console.error('Enhance sample failed:', e);
        document.getElementById('enhance-processing').style.display = 'none';
        document.getElementById('enhance-recorder').style.display = 'block';
        const btn = document.getElementById('enhance-record-btn');
        btn.textContent = 'Failed — Try Again';
        btn.disabled = false;
        btn.classList.remove('recording');
    }
}

function cleanupEnhanceAudio() {
    if (enhanceState.countdownInterval) { clearInterval(enhanceState.countdownInterval); enhanceState.countdownInterval = null; }
    if (enhanceState.animFrameId) { cancelAnimationFrame(enhanceState.animFrameId); enhanceState.animFrameId = null; }
    if (enhanceState.scriptNode) { try { enhanceState.scriptNode.disconnect(); } catch(e){} enhanceState.scriptNode = null; }
    if (enhanceState.sourceNode) { try { enhanceState.sourceNode.disconnect(); } catch(e){} enhanceState.sourceNode = null; }
    if (enhanceState.audioContext) { try { enhanceState.audioContext.close(); } catch(e){} enhanceState.audioContext = null; }
    if (enhanceState.audioStream) { enhanceState.audioStream.getTracks().forEach(t => t.stop()); enhanceState.audioStream = null; }
}

function closeEnhanceOverlay() {
    cleanupEnhanceAudio();
    document.getElementById('enhance-overlay').style.display = 'none';
    loadSpeakerStatus();
}

function drawEnhanceWaveform() {
    const canvas = document.getElementById('enhance-canvas');
    if (!canvas || !enhanceState.analyserNode) return;
    const ctx = canvas.getContext('2d');
    const analyser = enhanceState.analyserNode;
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    function draw() {
        if (!enhanceState.isRecording) return;
        enhanceState.animFrameId = requestAnimationFrame(draw);
        analyser.getByteTimeDomainData(dataArray);
        ctx.fillStyle = 'rgba(248, 249, 250, 0.3)';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.lineWidth = 2;
        ctx.strokeStyle = '#5a6270';
        ctx.beginPath();
        const sliceWidth = canvas.width / bufferLength;
        let x = 0;
        for (let i = 0; i < bufferLength; i++) {
            const v = dataArray[i] / 128.0;
            const y = v * canvas.height / 2;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
            x += sliceWidth;
        }
        ctx.lineTo(canvas.width, canvas.height / 2);
        ctx.stroke();
    }
    draw();
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

function drawEnrollmentLevelBars() {
    const barsContainer = document.getElementById('enrollment-level-bars');
    if (!barsContainer || !enrollmentState.analyserNode) return;

    const bars = barsContainer.querySelectorAll('.level-bar');
    const analyser = enrollmentState.analyserNode;
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    function draw() {
        if (!enrollmentState.isListening && !enrollmentState.isRecording) return;
        enrollmentState.animFrameId = requestAnimationFrame(draw);

        analyser.getByteTimeDomainData(dataArray);

        // Compute RMS
        let sumSq = 0;
        for (let i = 0; i < bufferLength; i++) {
            const v = (dataArray[i] - 128) / 128.0;
            sumSq += v * v;
        }
        const rms = Math.sqrt(sumSq / bufferLength);

        // Smooth RMS with EMA
        enrollmentState.smoothedRms = 0.3 * rms + 0.7 * enrollmentState.smoothedRms;
        const smoothed = enrollmentState.smoothedRms;

        // Log-scale mapping
        const normalizedLevel = Math.min(1, Math.max(0, (Math.log10(smoothed + 0.001) + 2) / 2));

        // Map to active bar count (0 to 20)
        const activeBars = Math.round(normalizedLevel * bars.length);

        bars.forEach((bar, i) => {
            if (i < activeBars) {
                bar.classList.add('active');
                // Gradient height: 8px to 44px across bars
                const t = i / (bars.length - 1);
                const height = 8 + t * 36;
                bar.style.height = height + 'px';
            } else {
                bar.classList.remove('active');
                bar.style.height = '4px';
            }
        });

        // Speech detection — only during listening phase
        if (enrollmentState.isListening && !enrollmentState.isRecording) {
            if (rms > 0.02) {
                if (!enrollmentState.speechStartTime) {
                    enrollmentState.speechStartTime = performance.now();
                } else if (performance.now() - enrollmentState.speechStartTime >= 200) {
                    beginRecording();
                }
            } else {
                enrollmentState.speechStartTime = null;
            }
        }
    }

    draw();
}

// ========== First Light — Interactive Discovery Quest ==========

async function initFirstLight() {
    try {
        const data = await API.getFirstLightQuest();
        if (!data.show) return;

        AppState.firstLightState = data;
        const panel = document.getElementById('first-light-panel');
        if (!panel) return;

        panel.style.display = 'block';

        // Restore collapsed state from localStorage
        const isCollapsed = localStorage.getItem('attune_first_light_collapsed') === 'true';
        if (isCollapsed || data.completed) {
            panel.classList.add('collapsed');
        }

        // Wire collapse toggle
        const header = document.getElementById('first-light-header');
        if (header) {
            header.addEventListener('click', () => {
                panel.classList.toggle('collapsed');
                localStorage.setItem('attune_first_light_collapsed',
                    panel.classList.contains('collapsed') ? 'true' : 'false');
            });
        }

        renderFirstLightPanel(data);
    } catch (e) {
        console.error('Failed to init First Light:', e);
    }
}

function renderFirstLightPanel(data) {
    const tasks = data.tasks;
    const completedCount = Object.values(tasks).filter(Boolean).length;
    const total = FIRST_LIGHT_TASKS.length;

    // Update progress bar
    const bar = document.getElementById('first-light-progress-bar');
    if (bar) bar.style.width = ((completedCount / total) * 100) + '%';

    // Update progress label
    const label = document.getElementById('first-light-progress-label');
    if (label) label.textContent = `${completedCount} / ${total}`;

    // Update task checkmarks
    document.querySelectorAll('.first-light-task').forEach(li => {
        const taskKey = li.dataset.questTask;
        if (tasks[taskKey]) {
            li.classList.add('completed');
            li.querySelector('.first-light-check').textContent = '\u25CF';
        } else {
            li.classList.remove('completed');
            li.querySelector('.first-light-check').textContent = '\u25CB';
        }
    });

    // Update reward text
    const reward = document.getElementById('first-light-reward');
    if (reward && data.completed) {
        reward.querySelector('.first-light-reward-text').textContent = 'Bonus tree planted!';
    }
}

async function completeFirstLightTask(taskKey) {
    if (!AppState.firstLightState || !AppState.firstLightState.show) return;
    if (AppState.firstLightState.completed) return;
    if (AppState.firstLightState.tasks[taskKey]) return; // Already done

    try {
        const result = await API.completeFirstLightTask(taskKey);
        if (!result.success) return;

        // Update local state
        AppState.firstLightState.tasks[taskKey] = true;

        if (result.just_completed) {
            AppState.firstLightState.completed = true;
            renderFirstLightPanel(AppState.firstLightState);
            onFirstLightComplete();
        } else {
            renderFirstLightPanel(AppState.firstLightState);
        }
    } catch (e) {
        console.error('Failed to complete First Light task:', e);
    }
}

function onFirstLightComplete() {
    // Bypass sanctuary cooldown for the celebration
    const savedCooldown = AppState.lastSanctuaryTime;
    AppState.lastSanctuaryTime = 0;
    triggerSanctuary('first_light', 'First Light complete! A tree grows in your honor.');
    // Restore cooldown (sanctuary sets it internally)

    // After sanctuary dismisses (~3.5s), refresh grove and highlight it
    setTimeout(() => {
        updateGrove();

        // Scroll to grove card and add highlight
        const groveCard = document.querySelector('[data-card-id="grove"]');
        if (groveCard) {
            groveCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
            groveCard.classList.add('grove-highlight');
            setTimeout(() => groveCard.classList.remove('grove-highlight'), 4500);
        }

        // Auto-collapse panel after 5s
        setTimeout(() => {
            const panel = document.getElementById('first-light-panel');
            if (panel) {
                panel.classList.add('collapsed');
                localStorage.setItem('attune_first_light_collapsed', 'true');
            }
        }, 5000);
    }, 3500);
}
