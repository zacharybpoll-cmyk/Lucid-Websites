const { app, BrowserWindow, ipcMain, shell, dialog, powerMonitor, session } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');
const fs = require('fs');

// ============ Auto-Update ============
let autoUpdater;
try {
  autoUpdater = require('electron-updater').autoUpdater;
  autoUpdater.autoDownload = false; // Don't auto-download, just notify
  autoUpdater.autoInstallOnAppQuit = true;
} catch (e) {
  console.log('[Main] electron-updater not available (dev mode)');
}

// Detect packaged vs development mode
const IS_PACKAGED = app.isPackaged;

// In packaged mode, python/ is an extraResource inside the .app bundle
// In dev mode, python/ is a sibling directory
const PYTHON_DIR = IS_PACKAGED
  ? path.join(process.resourcesPath, 'python')
  : path.join(__dirname, 'python');

const VENV_PYTHON = path.join(PYTHON_DIR, 'venv', 'bin', 'python');
const MAIN_PY = path.join(PYTHON_DIR, 'main.py');
const DATA_DIR = path.join(app.getPath('userData'), 'lucid-data');

// ============ Crash Reporting ============

const CRASH_LOG = path.join(DATA_DIR, 'crash_log.txt');

function sanitizeCrashLog(text) {
  // NOTE: Identical sanitization rules exist in python/main.py:_sanitize_crash_log()
  // If you change these patterns, update both locations.
  // Redact embedding vectors (arrays of 10+ floats)
  text = text.replace(/\[(-?\d+\.\d+,\s*){9,}-?\d+\.\d+\]/g, '[<embedding redacted>]');
  // Replace home directory paths with ~
  const home = require('os').homedir();
  text = text.split(home).join('~');
  // Redact long base64 strings (40+ chars)
  text = text.replace(/[A-Za-z0-9+/]{40,}={0,2}/g, '<base64 redacted>');
  return text;
}

function logCrash(source, error) {
  const timestamp = new Date().toISOString();
  let raw = `${error.stack || error.message || error}`;
  raw = sanitizeCrashLog(raw);
  const entry = `[${timestamp}] [${source}] ${raw}\n`;
  try {
    fs.appendFileSync(CRASH_LOG, entry);
  } catch {} // Don't crash while logging crashes
}

process.on('uncaughtException', (error) => {
  console.error('[Main] Uncaught exception:', error);
  logCrash('electron-uncaught', error);
});

process.on('unhandledRejection', (reason) => {
  console.error('[Main] Unhandled rejection:', reason);
  logCrash('electron-unhandled-rejection', reason);
});

const API_HOST = '127.0.0.1';
// Derive unique port per app variant to allow simultaneous operation
const PKG_NAME = require('./package.json').name;
const PORT_MAP = { 'lucid-development': 8765, 'lucid-health': 8766, 'lucid': 8767 };
const API_PORT = PORT_MAP[PKG_NAME] || 8765;
const API_BASE = `http://${API_HOST}:${API_PORT}`;

let splashWindow = null;
let onboardingWindow = null;
let mainWindow = null;
let pythonProcess = null;
let pythonRestartCount = 0;
let isQuitting = false;
let appLaunchTime = Date.now();

// Ensure data directory exists
function ensureDataDir() {
  if (!fs.existsSync(DATA_DIR)) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
  }
}

// Resolve the path for loading local HTML files
// In packaged mode, __dirname is inside the .app asar; use app.getAppPath()
function getAppRoot() {
  return IS_PACKAGED ? app.getAppPath() : __dirname;
}

// ============ Version-Based Cache Clearing ============

const VERSION_FILE = path.join(DATA_DIR, '.app-version');
const CURRENT_VERSION = require('./package.json').version;

function checkVersionAndClearCache() {
  let lastVersion = '';
  try { lastVersion = fs.readFileSync(VERSION_FILE, 'utf8').trim(); } catch {}
  if (lastVersion !== CURRENT_VERSION) {
    console.log(`[Main] Version changed (${lastVersion} → ${CURRENT_VERSION}), clearing cache...`);
    session.defaultSession.clearCache().then(() => {
      console.log('[Main] Cache cleared');
    });
    fs.writeFileSync(VERSION_FILE, CURRENT_VERSION);
  }
}

// ============ Splash Screen ============

function showSplash() {
  splashWindow = new BrowserWindow({
    width: 400,
    height: 300,
    frame: false,
    transparent: true,
    resizable: false,
    center: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  splashWindow.loadFile(path.join(getAppRoot(), 'src', 'splash', 'splash.html'));
  splashWindow.on('closed', () => { splashWindow = null; });
}

// ============ Python Subprocess ============

function killStaleBackend() {
  try {
    const result = require('child_process').execSync(
      `lsof -ti TCP:${API_PORT} 2>/dev/null`, { encoding: 'utf8', timeout: 5000 }
    ).trim();
    if (result) {
      const pids = result.split('\n');
      for (const pid of pids) {
        const p = parseInt(pid);
        if (p && p !== process.pid) {
          console.log(`[Main] Killing stale process on port ${API_PORT}: PID ${p}`);
          try { process.kill(p, 'SIGKILL'); } catch {}
        }
      }
    }
  } catch {} // No stale process — expected case
}

function spawnPython() {
  return new Promise((resolve, reject) => {
    ensureDataDir();
    killStaleBackend();

    const env = {
      ...process.env,
      LUCID_DATA_DIR: DATA_DIR,
      LUCID_API_PORT: String(API_PORT),
      PYTHONUNBUFFERED: '1',
      // In packaged mode, point Python to bundled models inside the .app
      ...(IS_PACKAGED ? {
        LUCID_BUNDLED_MODELS_DIR: path.join(process.resourcesPath, 'python', 'bundled_models'),
      } : {}),
    };

    console.log(`[Main] Python dir: ${PYTHON_DIR}`);
    console.log(`[Main] Python bin: ${VENV_PYTHON}`);
    console.log(`[Main] Data dir: ${DATA_DIR}`);
    console.log(`[Main] API port: ${API_PORT}`);

    pythonProcess = spawn(VENV_PYTHON, [MAIN_PY, '--electron'], {
      cwd: PYTHON_DIR,
      env,
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    pythonProcess.stdout.on('data', (data) => {
      console.log(`[Python] ${data.toString().trim()}`);
    });

    pythonProcess.stderr.on('data', (data) => {
      console.error(`[Python] ${data.toString().trim()}`);
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
        const delay = Math.pow(2, pythonRestartCount) * 1000; // 1s, 2s, 4s
        pythonRestartCount++;
        console.log(`[Python] Unexpected exit. Restarting in ${delay}ms (attempt ${pythonRestartCount}/3)...`);
        setTimeout(async () => {
          try {
            await spawnPython();
            console.log('[Python] Restarted, waiting for server...');
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
        dialog.showErrorBox(
          'Lucid — Backend Error',
          'The Lucid backend crashed and could not be restarted after 3 attempts.\nPlease restart the application.'
        );
      }
    });

    // Don't wait for exit — resolve immediately and let polling handle readiness
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
              resolve(data);
            } else {
              console.log(`[Main] Server not ready yet (attempt ${attempts}): ${data.status || 'loading...'}`);
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
  return new Promise((resolve, reject) => {
    const req = http.get(`${API_BASE}/api/onboarding-status`, (res) => {
      let body = '';
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => {
        try {
          resolve(JSON.parse(body));
        } catch {
          resolve({ completed: false });
        }
      });
    });
    req.on('error', () => resolve({ completed: false }));
    req.setTimeout(3000, () => { req.destroy(); resolve({ completed: false }); });
  });
}

// ============ Onboarding Window ============

function showOnboarding() {
  onboardingWindow = new BrowserWindow({
    width: 540,
    height: 680,
    titleBarStyle: 'hiddenInset',
    resizable: false,
    center: true,
    backgroundColor: '#faf6ee',
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(getAppRoot(), 'preload.js'),
    },
  });

  onboardingWindow.loadFile(path.join(getAppRoot(), 'src', 'onboarding', 'onboarding.html'));

  onboardingWindow.once('ready-to-show', () => {
    if (splashWindow) {
      splashWindow.close();
      splashWindow = null;
    }
    onboardingWindow.show();
  });

  onboardingWindow.on('closed', () => { onboardingWindow = null; });
}

// ============ Main App Window ============

function showMainApp() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    titleBarStyle: 'hiddenInset',
    center: true,
    backgroundColor: '#EBE4DA',
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(getAppRoot(), 'preload.js'),
    },
  });

  mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDescription, validatedURL) => {
    console.error(`[Main] Page load failed: ${errorCode} ${errorDescription} (${validatedURL})`);
  });

  mainWindow.loadURL(`${API_BASE}/static/index.html`).catch(err => {
    console.error('[Main] loadURL failed:', err);
  });

  let shown = false;
  const doShow = () => {
    if (shown) return;
    shown = true;
    if (splashWindow) {
      splashWindow.close();
      splashWindow = null;
    }
    if (onboardingWindow) {
      onboardingWindow.close();
      onboardingWindow = null;
    }
    mainWindow.show();
  };

  mainWindow.once('ready-to-show', () => {
    doShow();
  });

  // Fallback: force show after 10s if ready-to-show hasn't fired
  // (external CDN resources like Google Fonts can delay ready-to-show)
  setTimeout(() => {
    if (!shown) {
      console.warn('[Main] ready-to-show timeout — forcing show');
      doShow();
    }
  }, 10000);

  mainWindow.on('closed', () => { mainWindow = null; });
}

// ============ IPC Handlers ============

ipcMain.handle('onboarding-complete', async () => {
  // Mark onboarding complete on the server
  return new Promise((resolve) => {
    const postData = JSON.stringify({ completed: true });
    const req = http.request({
      hostname: API_HOST,
      port: API_PORT,
      path: '/api/onboarding-status',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(postData),
      },
    }, (res) => {
      let body = '';
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => {
        resolve({ success: true });
        showMainApp();
      });
    });
    req.on('error', () => resolve({ success: false }));
    req.write(postData);
    req.end();
  });
});

ipcMain.handle('get-api-base', () => {
  return API_BASE;
});

ipcMain.handle('open-system-settings', () => {
  shell.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone');
});

// ============ Analytics Helper ============

function trackAnalyticsEvent(eventType, payload = {}) {
  const postData = JSON.stringify({ event_type: eventType, payload });
  const req = http.request({
    hostname: API_HOST, port: API_PORT, path: '/api/track', method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(postData) },
  }, () => {}); // fire-and-forget
  req.on('error', () => {}); // silently ignore
  req.write(postData);
  req.end();
}

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

  // ============ User Data Migration (Attune → Lucid) ============
  function migrateUserData() {
    const newUserData = app.getPath('userData');
    const PKG_NAME = require('./package.json').name;
    const oldNameMap = { 'lucid': 'attune-steel', 'lucid-health': 'attune-health', 'lucid-development': 'attune-dev' };
    const oldName = oldNameMap[PKG_NAME];
    if (!oldName) return;
    const oldUserData = path.join(path.dirname(newUserData), oldName);
    const oldDataDir = path.join(oldUserData, 'attune-data');
    const newDataDir = path.join(newUserData, 'lucid-data');
    if (fs.existsSync(oldDataDir) && !fs.existsSync(newDataDir)) {
      fs.mkdirSync(newUserData, { recursive: true });
      require('child_process').execSync(`cp -R "${oldDataDir}" "${newDataDir}"`);
      fs.writeFileSync(path.join(newUserData, '.migrated-from-attune'),
        JSON.stringify({ date: new Date().toISOString(), source: oldDataDir }));
    }
  }

  app.whenReady().then(async () => {
    migrateUserData();
    showSplash();
    ensureDataDir();
    checkVersionAndClearCache();

    try {
      await spawnPython();
      console.log('[Main] Python process spawned, waiting for server...');

      await pollForServer();
      console.log('[Main] Server is up!');

      // Track app launch
      const os = require('os');
      trackAnalyticsEvent('app_launch', {
        app_version: CURRENT_VERSION,
        os_version: `macOS ${os.release()}`,
        first_launch: false // will be true on very first launch (no onboarding complete)
      });

      const status = await checkOnboardingStatus();
      console.log('[Main] Onboarding status:', status);

      if (status.completed) {
        showMainApp();
      } else {
        showOnboarding();
      }

      // ============ Check for Updates ============
      if (autoUpdater) {
        setTimeout(() => {
          autoUpdater.checkForUpdates().catch(err => {
            console.log('[Main] Update check failed:', err.message);
          });
        }, 5000); // Wait 5 seconds after launch

        autoUpdater.on('update-available', (info) => {
          console.log('[Main] Update available:', info.version);
          if (mainWindow) {
            dialog.showMessageBox(mainWindow, {
              type: 'info',
              title: 'Update Available',
              message: `A new version of Lucid (v${info.version}) is available.`,
              detail: 'The update will be downloaded in the background and installed when you restart.',
              buttons: ['Download', 'Later'],
              defaultId: 0,
            }).then(({ response }) => {
              if (response === 0) {
                autoUpdater.downloadUpdate();
              }
            });
          }
        });

        autoUpdater.on('update-downloaded', () => {
          console.log('[Main] Update downloaded, will install on quit');
          if (mainWindow) {
            dialog.showMessageBox(mainWindow, {
              type: 'info',
              title: 'Update Ready',
              message: 'Update has been downloaded. It will be installed when you restart Lucid.',
              buttons: ['Restart Now', 'Later'],
              defaultId: 0,
            }).then(({ response }) => {
              if (response === 0) {
                autoUpdater.quitAndInstall();
              }
            });
          }
        });

        autoUpdater.on('error', (err) => {
          console.log('[Main] Auto-update error:', err.message);
        });
      }
    } catch (err) {
      console.error('[Main] Startup failed:', err);
      if (splashWindow) splashWindow.close();
      app.quit();
    }
  });

  app.on('window-all-closed', () => {
    app.quit();
  });

  app.on('activate', () => {
    if (mainWindow) {
      mainWindow.show();
    } else if (onboardingWindow) {
      onboardingWindow.show();
    }
  });

  app.on('before-quit', () => {
    isQuitting = true;

    // Track app quit with session duration
    const sessionDurationSec = Math.round((Date.now() - appLaunchTime) / 1000);
    trackAnalyticsEvent('app_quit', { session_duration_sec: sessionDurationSec });

    if (pythonProcess) {
      console.log('[Main] Sending SIGTERM to Python...');
      pythonProcess.kill('SIGTERM');

      // Force kill after 3 seconds if still alive
      setTimeout(() => {
        if (pythonProcess) {
          console.log('[Main] Force killing Python (SIGKILL)...');
          pythonProcess.kill('SIGKILL');
        }
      }, 3000);
    }
  });

  // ============ Power Monitor (Sleep/Wake) ============

  // ERR-001: Retry helper for IPC API requests
  function sendApiRequest(apiPath, retries = 3) {
    let attempt = 0;
    const tryRequest = () => {
      attempt++;
      const req = http.request({
        hostname: API_HOST, port: API_PORT, path: apiPath, method: 'POST',
      }, (res) => {
        console.log(`[Main] ${apiPath} responded ${res.statusCode}`);
      });
      req.on('error', (e) => {
        console.warn(`[Main] ${apiPath} failed (attempt ${attempt}/${retries}): ${e.message}`);
        if (attempt < retries) setTimeout(tryRequest, 1000);
      });
      req.end();
    };
    tryRequest();
  }

  app.whenReady().then(() => {
    powerMonitor.on('suspend', () => {
      console.log('[Main] System suspending, pausing analysis...');
      sendApiRequest('/api/pause');
    });

    powerMonitor.on('resume', () => {
      console.log('[Main] System resumed, resuming analysis...');
      sendApiRequest('/api/resume');
    });

    // MEM-003: Periodic cache management — clear when cache exceeds 500MB
    setInterval(async () => {
      try {
        const cacheSize = await session.defaultSession.getCacheSize();
        const cacheMB = cacheSize / (1024 * 1024);
        if (cacheMB > 500) {
          console.log(`[Main] Cache size ${cacheMB.toFixed(0)}MB > 500MB threshold, clearing...`);
          await session.defaultSession.clearCache();
          console.log('[Main] Periodic cache clear complete');
        }
      } catch (e) {
        console.error('[Main] Cache check failed:', e.message);
      }
    }, 30 * 60 * 1000); // every 30 minutes
  });
}
