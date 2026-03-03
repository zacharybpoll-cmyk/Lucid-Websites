const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('lucid', {
  completeOnboarding: () => ipcRenderer.invoke('onboarding-complete'),
  getApiBase: () => ipcRenderer.invoke('get-api-base'),
  openSystemSettings: () => ipcRenderer.invoke('open-system-settings'),
});
