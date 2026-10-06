import { contextBridge, ipcRenderer } from "electron";

import type { BackendInfo, Bridge, CopyProgress } from "./shared";

const api: Bridge = {
  startEngine: () => ipcRenderer.invoke("engine:start"),
  control: (action) => ipcRenderer.invoke("window:control", action),
  windowState: () => ipcRenderer.invoke("window:state"),
  resize: (edge, dx, dy) => ipcRenderer.invoke("window:resize", edge, dx, dy),
  openMedia: () => ipcRenderer.invoke("dialog:openMedia"),
  pickOutputFolder: () => ipcRenderer.invoke("dialog:pickOutputFolder"),
  setOutputFolder: (folder) => ipcRenderer.invoke("settings:outputFolder", folder),
  readSettings: () => ipcRenderer.invoke("settings:read"),
  pickMediaRoot: () => ipcRenderer.invoke("dialog:pickMediaRoot"),
  showItem: (path) => ipcRenderer.invoke("shell:showItem", path),
  openExternal: (url) => ipcRenderer.invoke("shell:openExternal", url),
  copyText: (text) => ipcRenderer.invoke("clipboard:writeText", text),
  token: () => ipcRenderer.invoke("app:token"),
  restartEngine: () => ipcRenderer.invoke("app:restartEngine"),
  appInfo: () => ipcRenderer.invoke("app:info"),
  onEngineReady: (callback) => {
    const listener = (_event: Electron.IpcRendererEvent, info: BackendInfo) => callback(info);
    ipcRenderer.on("engine:ready", listener);
    return () => ipcRenderer.removeListener("engine:ready", listener);
  },
  onEngineError: (callback) => {
    const listener = (_event: Electron.IpcRendererEvent, message: string) => callback(message);
    ipcRenderer.on("engine:error", listener);
    return () => ipcRenderer.removeListener("engine:error", listener);
  },
  onMediaProgress: (callback) => {
    const listener = (_event: Electron.IpcRendererEvent, progress: CopyProgress) => callback(progress);
    ipcRenderer.on("media:progress", listener);
    return () => ipcRenderer.removeListener("media:progress", listener);
  },
};

contextBridge.exposeInMainWorld("desktop", api);
