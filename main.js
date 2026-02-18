const { app, BrowserWindow, ipcMain, shell } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');
const fs = require('fs');

// Detect packaged vs development mode
const IS_PACKAGED = app.isPackaged;

// In packaged mode, python/ is an extraResource inside the .app bundle
// In dev mode, python/ is a sibling directory
const PYTHON_DIR = IS_PACKAGED
  ? path.join(process.resourcesPath, 'python')
  : path.join(__dirname, 'python');

const VENV_PYTHON = path.join(PYTHON_DIR, 'venv', 'bin', 'python');
const MAIN_PY = path.join(PYTHON_DIR, 'main.py');
const DATA_DIR = path.join(app.getPath('userData'), 'attune-data');

const API_HOST = '127.0.0.1';
const API_PORT = 8765;
const API_BASE = `http://${API_HOST}:${API_PORT}`;

let splashWindow = null;
let onboardingWindow = null;
let mainWindow = null;
let pythonProcess = null;

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

function spawnPython() {
  return new Promise((resolve, reject) => {
    ensureDataDir();

    const env = {
      ...process.env,
      ATTUNE_DATA_DIR: DATA_DIR,
    };

    console.log(`[Main] Python dir: ${PYTHON_DIR}`);
    console.log(`[Main] Python bin: ${VENV_PYTHON}`);
    console.log(`[Main] Data dir: ${DATA_DIR}`);

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
            resolve(data);
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
    },
  });

  mainWindow.loadURL(`${API_BASE}/static/index.html`);

  mainWindow.once('ready-to-show', () => {
    if (splashWindow) {
      splashWindow.close();
      splashWindow = null;
    }
    if (onboardingWindow) {
      onboardingWindow.close();
      onboardingWindow = null;
    }
    mainWindow.show();
  });

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

// ============ App Lifecycle ============

app.whenReady().then(async () => {
  showSplash();

  try {
    await spawnPython();
    console.log('[Main] Python process spawned, waiting for server...');

    await pollForServer();
    console.log('[Main] Server is up!');

    const status = await checkOnboardingStatus();
    console.log('[Main] Onboarding status:', status);

    if (status.completed) {
      showMainApp();
    } else {
      showOnboarding();
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

app.on('before-quit', () => {
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
