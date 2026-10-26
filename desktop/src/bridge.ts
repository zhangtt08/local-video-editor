import type { BackendInfo, Bridge } from "../electron/shared";

/**
 * 渲染端只通过这一个入口拿桌面能力。浏览器里跑（vite dev / 自检）时 window.desktop 不存在，
 * 于是退化成一个纯 HTTP 的假外壳：引擎信息由 ?engine=…&token=… 或 sessionStorage 提供。
 */

const real = (globalThis as { desktop?: Bridge }).desktop;

/** 桌面外壳在场与否要当场读，不能在 import 那一刻记死：自检里外壳是后装上的那一个。 */
export function isNative(): boolean {
  return Boolean((globalThis as { desktop?: Bridge }).desktop);
}

export function urlParam(name: string): string {
  try {
    return new URLSearchParams(location.search).get(name) ?? "";
  } catch {
    return "";
  }
}

function queryParam(name: string): string {
  return urlParam(name);
}

const stored = (name: string): string => {
  try {
    return sessionStorage.getItem(name) ?? "";
  } catch {
    return "";
  }
};

const browserEngine = queryParam("engine") || stored("agentcut.engine") || "http://127.0.0.1:8765";
export function originPort(origin: string): number {
  try { const url = new URL(origin); return Number(url.port || (url.protocol === "https:" ? 443 : 80)); }
  catch { return 0; }
}
export const stubInfo: BackendInfo = {
  port: originPort(browserEngine),
  base_url: browserEngine,
  token_file: "",
  media_ready: true,
  media_roots: [],
  render_ready: false,
  output_roots: [],
  data_dir: "",
  output_dir: "",
  ffmpeg: "",
  token: queryParam("token") || stored("agentcut.token"),
};

const stubBridge: Bridge = {
  engineStatus: async () => ({ running: false }),
  startEngine: async () => {
    const info = { ...stubInfo };
    try {
      const response = await fetch(`${info.base_url}/health`);
      if (!response.ok) throw new Error(`health ${response.status}`);
      const health = (await response.json()) as { media_ready?: boolean; render_ready?: boolean };
      info.media_ready = Boolean(health.media_ready);
      info.render_ready = Boolean(health.render_ready);
      if (info.media_ready && info.token) {
        // 让浏览器模式也能看到真实的 FFmpeg 路径与素材目录（原生模式由 ready 行给出）。
        const config = (await (
          await fetch(`${info.base_url}/v1/media/config`, { headers: { Authorization: `Bearer ${info.token}` } })
        ).json()) as { media_roots?: string[]; ffmpeg?: string };
        info.media_roots = config.media_roots ?? [];
        info.ffmpeg = config.ffmpeg ?? "";
      }
    } catch {
      /* 引擎没起来时交给界面给出引导，不在这里抛 */
    }
    return { ok: true, info };
  },
  control: async (action) => {
    if (action === "info") return { maximized: false, fullscreen: false };
    return { maximized: false, fullscreen: false };
  },
  windowState: async () => ({ maximized: false, fullscreen: false }),
  resize: async () => null,
  openMedia: async () => ({
    cancelled: true,
    error: "浏览器预览没有原生文件对话框：请把文件放进素材文件夹，然后在“素材库”里点“刷新”。",
  }),
  pickOutputFolder: async () => ({ cancelled: true }),
  setOutputFolder: async (folder) => ({ ok: false, folder }),
  readSettings: async () => ({ outputFolder: "", mediaFolders: [] }),
  pickMediaRoot: async () => ({ cancelled: true }),
  showItem: async () => false,
  openExternal: async () => false,
  copyText: async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      return false;
    }
  },
  token: async () => stubInfo.token ?? "",
  restartEngine: async () => ({ ok: false, info: undefined }),
  appInfo: async () => ({
    version: "dev",
    electron: "browser",
    userData: "",
    library: [],
    enginePath: "",
  }),
  onEngineReady: () => () => {},
  onEngineError: () => () => {},
  onMediaProgress: () => () => {},
};

export const bridge: Bridge = real ?? stubBridge;
