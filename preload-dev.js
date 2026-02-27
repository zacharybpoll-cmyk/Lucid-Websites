const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('attune', {
  completeOnboarding: () => ipcRenderer.invoke('onboarding-complete'),
  getApiBase: () => ipcRenderer.invoke('get-api-base'),
  openSystemSettings: () => ipcRenderer.invoke('open-system-settings'),
});

// Dev-only APIs
contextBridge.exposeInMainWorld('attuneDev', {
  openDiagnostics: () => ipcRenderer.invoke('open-diagnostics'),
  getPythonLogs: () => ipcRenderer.invoke('get-python-logs'),
  restartBackend: () => ipcRenderer.invoke('restart-backend'),
  getStartupTimings: () => ipcRenderer.invoke('get-startup-timings'),
  getMemoryUsage: () => ipcRenderer.invoke('get-memory-usage'),
});
