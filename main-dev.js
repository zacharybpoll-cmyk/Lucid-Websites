/**
 * Attune Steel — Development Build
 * Standalone Electron entry point with dev diagnostics.
 * Does NOT modify or import main.js.
 */
const { app, BrowserWindow, ipcMain, shell, dialog, powerMonitor, session, globalShortcut } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');
const fs = require('fs');
const os = require('os');

// ============ Dev Mode Flag ============
const IS_DEV = true;

// ============ No Auto-Update in Dev ============
// Intentionally skipped — dev builds should never auto-update.

// ============ Paths ============
const IS_PACKAGED = app.isPackaged;
const PYTHON_DIR = IS_PACKAGED
  ? path.join(process.resourcesPath, 'python')
  : path.join(__dirname, 'python');
const VENV_PYTHON = path.join(PYTHON_DIR, 'venv', 'bin', 'python');
const MAIN_PY = path.join(PYTHON_DIR, 'main_dev.py');
const DATA_DIR = path.join(app.getPath('userData'), 'attune-data');

// ============ Crash Reporting ============
const CRASH_LOG = path.join(DATA_DIR, 'crash_log.txt');

function sanitizeCrashLog(text) {
  text = text.replace(/\[(-?\d+\.\d+,\s*){9,}-?\d+\.\d+\]/g, '[<embedding redacted>]');
  const home = os.homedir();
  text = text.split(home).join('~');
  text = text.replace(/[A-Za-z0-9+/]{40,}={0,2}/g, '<base64 redacted>');
  return text;
}

function logCrash(source, error) {
  const timestamp = new Date().toISOString();
  let raw = `${error.stack || error.message || error}`;
  raw = sanitizeCrashLog(raw);
  const entry = `[${timestamp}] [${source}] ${raw}\n`;
  try { fs.appendFileSync(CRASH_LOG, entry); } catch {}
}

process.on('uncaughtException', (error) => {
  console.error('[Dev] Uncaught exception:', error);
  logCrash('electron-uncaught', error);
});
process.on('unhandledRejection', (reason) => {
  console.error('[Dev] Unhandled rejection:', reason);
  logCrash('electron-unhandled-rejection', reason);
});

// ============ Port & Networking ============
const API_HOST = '127.0.0.1';
const API_PORT = 8768;
const API_BASE = `http://${API_HOST}:${API_PORT}`;

// ============ State ============
let splashWindow = null;
let onboardingWindow = null;
let mainWindow = null;
let diagnosticsWindow = null;
let pythonProcess = null;
let pythonRestartCount = 0;
let isQuitting = false;

// Dev state
const pythonLogs = [];       // Ring buffer of last 500 log lines
const MAX_LOG_LINES = 500;
const startupTimings = {};

function ensureDataDir() {
  if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });
}

function getAppRoot() {
  return IS_PACKAGED ? app.getAppPath() : __dirname;
}

// ============ Version-Based Cache Clearing ============
const VERSION_FILE = path.join(DATA_DIR, '.app-version');
const CURRENT_VERSION = require('./package-dev.json').version;

function checkVersionAndClearCache() {
  let lastVersion = '';
  try { lastVersion = fs.readFileSync(VERSION_FILE, 'utf8').trim(); } catch {}
  if (lastVersion !== CURRENT_VERSION) {
    console.log(`[Dev] Version changed (${lastVersion} -> ${CURRENT_VERSION}), clearing cache...`);
    session.defaultSession.clearCache().then(() => console.log('[Dev] Cache cleared'));
    fs.writeFileSync(VERSION_FILE, CURRENT_VERSION);
  }
}

// ============ Splash Screen ============
function showSplash() {
  startupTimings.splashStart = Date.now();

  splashWindow = new BrowserWindow({
    width: 400, height: 300,
    frame: false, transparent: true, resizable: false,
    center: true, alwaysOnTop: true, skipTaskbar: true,
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });

  splashWindow.loadFile(path.join(getAppRoot(), 'src', 'splash', 'splash.html'));

  // Inject DEV indicator into splash
  splashWindow.webContents.on('did-finish-load', () => {
    splashWindow.webContents.executeJavaScript(`
      const badge = document.createElement('div');
      badge.textContent = 'DEV';
      badge.style.cssText = 'position:fixed;top:12px;right:12px;background:#ef4444;color:#fff;padding:2px 8px;border-radius:8px;font-size:11px;font-weight:700;letter-spacing:1px;z-index:9999;';
      document.body.appendChild(badge);
    `);
  });

  splashWindow.on('closed', () => { splashWindow = null; });
  startupTimings.splashShown = Date.now();
}

// ============ Python Subprocess ============
function spawnPython() {
  return new Promise((resolve, reject) => {
    ensureDataDir();
    startupTimings.pythonSpawnStart = Date.now();

    const env = {
      ...process.env,
      ATTUNE_DATA_DIR: DATA_DIR,
      ATTUNE_API_PORT: String(API_PORT),
      ATTUNE_DEV_MODE: '1',
      PYTHONUNBUFFERED: '1',
    };

    console.log(`[Dev] Python dir: ${PYTHON_DIR}`);
    console.log(`[Dev] Python bin: ${VENV_PYTHON}`);
    console.log(`[Dev] Main script: ${MAIN_PY}`);
    console.log(`[Dev] Data dir: ${DATA_DIR}`);
    console.log(`[Dev] API port: ${API_PORT}`);

    pythonProcess = spawn(VENV_PYTHON, [MAIN_PY, '--electron'], {
      cwd: PYTHON_DIR,
      env,
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    pythonProcess.stdout.on('data', (data) => {
      const lines = data.toString().trim().split('\n');
      lines.forEach(line => {
        console.log(`[Python] ${line}`);
        pythonLogs.push({ ts: Date.now(), level: 'stdout', msg: line });
        if (pythonLogs.length > MAX_LOG_LINES) pythonLogs.shift();
      });
    });

    pythonProcess.stderr.on('data', (data) => {
      const lines = data.toString().trim().split('\n');
      lines.forEach(line => {
        console.error(`[Python] ${line}`);
        pythonLogs.push({ ts: Date.now(), level: 'stderr', msg: line });
        if (pythonLogs.length > MAX_LOG_LINES) pythonLogs.shift();
      });
    });

    pythonProcess.on('error', (err) => {
      console.error('[Python] Failed to start:', err);
      reject(err);
    });

    pythonProcess.on('exit', (code) => {
      console.log(`[Python] Exited with code ${code}`);
      pythonProcess = null;

      if (isQuitting || code === 0) return;

      if (pythonRestartCount < 3) {
        const delay = Math.pow(2, pythonRestartCount) * 1000;
        pythonRestartCount++;
        console.log(`[Python] Unexpected exit. Restarting in ${delay}ms (attempt ${pythonRestartCount}/3)...`);
        setTimeout(async () => {
          try {
            await spawnPython();
            await pollForServer();
            console.log('[Python] Server back up after restart.');
            if (mainWindow && mainWindow.webContents) {
              mainWindow.webContents.send('backend-restarted');
            }
            pythonRestartCount = 0;
          } catch (err) {
            console.error('[Python] Restart failed:', err);
          }
        }, delay);
      } else {
        console.error('[Python] Failed to restart after 3 attempts.');
        dialog.showErrorBox('Attune Steel Dev — Backend Error',
          'The backend crashed and could not be restarted after 3 attempts.\nPlease restart the application.');
      }
    });

    startupTimings.pythonSpawned = Date.now();
    resolve();
  });
}

// ============ Server Polling ============
function pollForServer(maxAttempts = 60) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const poll = () => {
      attempts++;
      const req = http.get(`${API_BASE}/api/health`, (res) => {
        let body = '';
        res.on('data', (chunk) => { body += chunk; });
        res.on('end', () => {
          try {
            const data = JSON.parse(body);
            if (data.ready === true) {
              startupTimings.serverReady = Date.now();
              resolve(data);
            } else {
              if (attempts < maxAttempts) setTimeout(poll, 500);
              else reject(new Error('Server did not become ready in time'));
            }
          } catch {
            if (attempts < maxAttempts) setTimeout(poll, 500);
            else reject(new Error('Server responded but with invalid JSON'));
          }
        });
      });
      req.on('error', () => {
        if (attempts < maxAttempts) setTimeout(poll, 500);
        else reject(new Error(`Server not responding after ${maxAttempts} attempts`));
      });
      req.setTimeout(2000, () => {
        req.destroy();
        if (attempts < maxAttempts) setTimeout(poll, 500);
        else reject(new Error('Server timeout'));
      });
    };
    poll();
  });
}

function checkOnboardingStatus() {
  return new Promise((resolve) => {
    const req = http.get(`${API_BASE}/api/onboarding-status`, (res) => {
      let body = '';
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => {
        try { resolve(JSON.parse(body)); } catch { resolve({ completed: false }); }
      });
    });
    req.on('error', () => resolve({ completed: false }));
    req.setTimeout(3000, () => { req.destroy(); resolve({ completed: false }); });
  });
}

// ============ Onboarding Window ============
function showOnboarding() {
  onboardingWindow = new BrowserWindow({
    width: 540, height: 680,
    titleBarStyle: 'hiddenInset',
    resizable: false, center: true,
    backgroundColor: '#faf6ee',
    show: false,
    webPreferences: {
      nodeIntegration: false, contextIsolation: true,
      preload: path.join(getAppRoot(), 'preload-dev.js'),
    },
  });

  onboardingWindow.loadFile(path.join(getAppRoot(), 'src', 'onboarding', 'onboarding.html'));

  onboardingWindow.once('ready-to-show', () => {
    if (splashWindow) { splashWindow.close(); splashWindow = null; }
    onboardingWindow.show();
  });
  onboardingWindow.on('closed', () => { onboardingWindow = null; });
}

// ============ Main App Window ============
function showMainApp() {
  startupTimings.mainWindowStart = Date.now();

  mainWindow = new BrowserWindow({
    width: 1280, height: 800,
    titleBarStyle: 'hiddenInset',
    center: true,
    backgroundColor: '#EBE4DA',
    show: false,
    webPreferences: {
      nodeIntegration: false, contextIsolation: true,
      preload: path.join(getAppRoot(), 'preload-dev.js'),
    },
  });

  mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDescription, validatedURL) => {
    console.error(`[Dev] Page load failed: ${errorCode} ${errorDescription} (${validatedURL})`);
  });

  mainWindow.loadURL(`${API_BASE}/static/index.html`).catch(err => {
    console.error('[Dev] loadURL failed:', err);
  });

  let shown = false;
  const doShow = () => {
    if (shown) return;
    shown = true;
    if (splashWindow) { splashWindow.close(); splashWindow = null; }
    if (onboardingWindow) { onboardingWindow.close(); onboardingWindow = null; }
    mainWindow.show();
    startupTimings.mainWindowShown = Date.now();

    // ---- Dev enhancements ----

    // 1. Open DevTools detached
    mainWindow.webContents.openDevTools({ mode: 'detach' });

    // 2. Inject DEV badge + floating toolbar into main window
    mainWindow.webContents.executeJavaScript(`
      // DEV badge
      const badge = document.createElement('div');
      badge.id = 'attune-dev-badge';
      badge.textContent = 'DEV';
      badge.style.cssText = 'position:fixed;top:8px;right:12px;background:#ef4444;color:#fff;padding:2px 10px;border-radius:8px;font-size:11px;font-weight:700;letter-spacing:1px;z-index:99999;pointer-events:none;font-family:-apple-system,system-ui,sans-serif;';
      document.body.appendChild(badge);

      // Floating dev toolbar
      const toolbar = document.createElement('div');
      toolbar.id = 'attune-dev-toolbar';
      toolbar.style.cssText = 'position:fixed;bottom:8px;left:8px;background:rgba(0,0,0,0.85);color:#a3e635;padding:4px 12px;border-radius:6px;font-size:11px;font-family:ui-monospace,monospace;z-index:99999;display:flex;gap:12px;pointer-events:none;';
      toolbar.innerHTML = '<span>:${API_PORT}</span><span id="dev-mem">--MB</span><span id="dev-readings">0 readings</span>';
      document.body.appendChild(toolbar);

      // Update toolbar periodically
      setInterval(async () => {
        try {
          const r = await fetch('/api/dev/status');
          if (r.ok) {
            const d = await r.json();
            document.getElementById('dev-mem').textContent = d.memory_mb + 'MB';
            document.getElementById('dev-readings').textContent = d.reading_count + ' readings';
          }
        } catch {}
      }, 5000);
    `);
  };

  mainWindow.once('ready-to-show', doShow);
  setTimeout(() => {
    if (!shown) { console.warn('[Dev] ready-to-show timeout -- forcing show'); doShow(); }
  }, 10000);
  mainWindow.on('closed', () => { mainWindow = null; });
}

// ============ Diagnostics Window ============
function showDiagnostics() {
  if (diagnosticsWindow) {
    diagnosticsWindow.focus();
    return;
  }

  diagnosticsWindow = new BrowserWindow({
    width: 900, height: 650,
    title: 'Attune Steel Dev — Diagnostics',
    backgroundColor: '#1e1e2e',
    webPreferences: {
      nodeIntegration: false, contextIsolation: true,
      preload: path.join(getAppRoot(), 'preload-dev.js'),
    },
  });

  diagnosticsWindow.loadFile(path.join(getAppRoot(), 'dev', 'diagnostics.html'));
  diagnosticsWindow.on('closed', () => { diagnosticsWindow = null; });
}

// ============ IPC Handlers ============
ipcMain.handle('onboarding-complete', async () => {
  return new Promise((resolve) => {
    const postData = JSON.stringify({ completed: true });
    const req = http.request({
      hostname: API_HOST, port: API_PORT,
      path: '/api/onboarding-status', method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(postData) },
    }, (res) => {
      let body = '';
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => { resolve({ success: true }); showMainApp(); });
    });
    req.on('error', () => resolve({ success: false }));
    req.write(postData);
    req.end();
  });
});

ipcMain.handle('get-api-base', () => API_BASE);

ipcMain.handle('open-system-settings', () => {
  shell.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone');
});

// Dev IPC handlers
ipcMain.handle('open-diagnostics', () => { showDiagnostics(); });

ipcMain.handle('get-python-logs', () => pythonLogs);

ipcMain.handle('restart-backend', async () => {
  if (pythonProcess) {
    console.log('[Dev] Manual backend restart requested');
    pythonProcess.kill('SIGTERM');
    // The exit handler will auto-restart
    return { success: true };
  }
  return { success: false, error: 'No python process running' };
});

ipcMain.handle('get-startup-timings', () => startupTimings);

ipcMain.handle('get-memory-usage', () => {
  return {
    rss: process.memoryUsage().rss,
    heapUsed: process.memoryUsage().heapUsed,
    heapTotal: process.memoryUsage().heapTotal,
  };
});

// ============ App Lifecycle ============
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(async () => {
    startupTimings.appReady = Date.now();
    showSplash();
    ensureDataDir();
    checkVersionAndClearCache();

    // Register Cmd+Shift+I for diagnostics
    globalShortcut.register('CommandOrControl+Shift+I', () => {
      showDiagnostics();
    });

    try {
      await spawnPython();
      console.log('[Dev] Python process spawned, waiting for server...');

      await pollForServer();
      console.log('[Dev] Server is up!');

      const status = await checkOnboardingStatus();
      console.log('[Dev] Onboarding status:', status);

      if (status.completed) {
        showMainApp();
      } else {
        showOnboarding();
      }
    } catch (err) {
      console.error('[Dev] Startup failed:', err);
      if (splashWindow) splashWindow.close();
      app.quit();
    }
  });

  app.on('window-all-closed', () => { app.quit(); });

  app.on('activate', () => {
    if (mainWindow) mainWindow.show();
    else if (onboardingWindow) onboardingWindow.show();
  });

  app.on('will-quit', () => {
    globalShortcut.unregisterAll();
  });

  app.on('before-quit', () => {
    isQuitting = true;
    if (pythonProcess) {
      console.log('[Dev] Sending SIGTERM to Python...');
      pythonProcess.kill('SIGTERM');
      setTimeout(() => {
        if (pythonProcess) {
          console.log('[Dev] Force killing Python (SIGKILL)...');
          pythonProcess.kill('SIGKILL');
        }
      }, 3000);
    }
  });

  // ============ Power Monitor ============
  function sendApiRequest(apiPath, retries = 3) {
    let attempt = 0;
    const tryRequest = () => {
      attempt++;
      const req = http.request({ hostname: API_HOST, port: API_PORT, path: apiPath, method: 'POST' },
        (res) => { console.log(`[Dev] ${apiPath} responded ${res.statusCode}`); });
      req.on('error', (e) => {
        console.warn(`[Dev] ${apiPath} failed (attempt ${attempt}/${retries}): ${e.message}`);
        if (attempt < retries) setTimeout(tryRequest, 1000);
      });
      req.end();
    };
    tryRequest();
  }

  app.whenReady().then(() => {
    powerMonitor.on('suspend', () => {
      console.log('[Dev] System suspending, pausing analysis...');
      sendApiRequest('/api/pause');
    });
    powerMonitor.on('resume', () => {
      console.log('[Dev] System resumed, resuming analysis...');
      sendApiRequest('/api/resume');
    });

    // Cache management (30 min interval)
    setInterval(async () => {
      try {
        const cacheSize = await session.defaultSession.getCacheSize();
        const cacheMB = cacheSize / (1024 * 1024);
        if (cacheMB > 500) {
          console.log(`[Dev] Cache ${cacheMB.toFixed(0)}MB > 500MB, clearing...`);
          await session.defaultSession.clearCache();
        }
      } catch (e) {
        console.error('[Dev] Cache check failed:', e.message);
      }
    }, 30 * 60 * 1000);
  });
}
