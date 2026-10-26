/**
 * AgentCut 桌面外壳：无边框窗口 + 内嵌窗口控制 + 本地剪辑引擎生命周期。
 *
 * 界面只是这个进程的一个视图；所有剪辑语义都走 127.0.0.1 的 HTTP 引擎，
 * 和外部 Agent 完全同一条路径。后端崩了会重启，界面永不直接读写数据库。
 */

import { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import { app, BrowserWindow, clipboard, dialog, ipcMain, Menu, shell } from "electron";
import {
  appendFileSync,
  createReadStream,
  createWriteStream,
  existsSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { basename, join } from "node:path";

import type { BackendInfo, WindowState } from "./shared";

const APP_ID = "com.agentcut.desktop";
const MIN_SIZE = { width: 1040, height: 660 };

let window: BrowserWindow | null = null;
let backend: ChildProcessWithoutNullStreams | null = null;
let backendInfo: BackendInfo | null = null;
let quitting = false;
let restarting = false;

const stateFile = () => join(app.getPath("userData"), "window-state.json");
const settingsFile = () => join(app.getPath("userData"), "settings.json");
const tokenFile = () => join(app.getPath("userData"), "agentcut.token");
const logFile = () => join(app.getPath("userData"), "logs", "engine.log");

type Settings = { mediaFolders: string[]; lastProject: string; outputFolder: string };

function readSettings(): Settings {
  const library = join(app.getPath("userData"), "media");
  mkdirSync(library, { recursive: true });
  const fallbackOutput = join(app.getPath("downloads") || library, "AgentCut 输出");
  try {
    const parsed = JSON.parse(readFileSync(settingsFile(), "utf-8")) as Partial<Settings>;
    const folders = [library, ...(parsed.mediaFolders ?? [])].filter((item) => existsSync(item));
    const output = parsed.outputFolder && existsSync(parsed.outputFolder) ? parsed.outputFolder : fallbackOutput;
    return { mediaFolders: Array.from(new Set(folders)), lastProject: parsed.lastProject ?? "", outputFolder: output };
  } catch {
    return { mediaFolders: [library], lastProject: "", outputFolder: fallbackOutput };
  }
}

function writeSettings(settings: Settings) {
  writeFileSync(settingsFile(), JSON.stringify(settings, null, 2), "utf-8");
}

function readWindowState(): WindowState {
  try {
    const parsed = JSON.parse(readFileSync(stateFile(), "utf-8")) as WindowState;
    if (parsed.width >= MIN_SIZE.width && parsed.height >= MIN_SIZE.height) return parsed;
  } catch {
    /* 首次运行没有状态文件 */
  }
  return { width: 1480, height: 900, x: undefined, y: undefined, maximized: false };
}

function backendCommand(): { command: string; args: string[] } {
  const resources = process.resourcesPath;
  // PyInstaller onedir 落在 bin/agentcut/，onefile 落在 bin/；哪个存在用哪个。
  const packaged = [
    join(resources, "bin", "agentcut.exe"),
    join(resources, "bin", "agentcut", "agentcut.exe"),
  ].find((item) => existsSync(item));
  if (packaged) {
    return {
      command: packaged,
      args: ["desktop", "--port", "0"],
    };
  }
  // 开发态：用仓库里的 venv 直接跑源码，改动立刻生效。
  const repo = join(__dirname, "..", "..");
  const python =
    process.platform === "win32"
      ? join(repo, ".venv", "Scripts", "python.exe")
      : join(repo, ".venv", "bin", "python");
  return { command: python, args: ["-m", "agentcut", "desktop", "--port", "0"] };
}

function ffmpegPaths(): string[] {
  const root = join(__dirname, "..");
  const candidates = [
    process.env.AGENTCUT_FFMPEG,
    join(process.resourcesPath, "bin", "ffmpeg.exe"),
    join(root, "node_modules", "ffmpeg-static", "ffmpeg.exe"),
    join(process.resourcesPath, "bin", "ffprobe.exe"),
    join(root, "node_modules", "ffprobe-static", "bin", "win32", "x64", "ffprobe.exe"),
  ].filter(Boolean) as string[];
  const found: string[] = [];
  for (const item of candidates) if (existsSync(item) && !found.includes(item)) found.push(item);
  return found;
}

let startPromise: Promise<BackendInfo> | null = null;

function startBackend(): Promise<BackendInfo> {
  // 渲染端 boot 与主进程 whenReady 可能同时调这里；引擎要起好几秒，
  // 期间两个调用都看不到 backendInfo —— 缓存进行中的 Promise 才不会拉起两个引擎。
  if (startPromise) return startPromise;
  startPromise = doStartBackend().finally(() => {
    startPromise = null;
  });
  return startPromise;
}

function doStartBackend(): Promise<BackendInfo> {
  if (backendInfo) return Promise.resolve(backendInfo);
  const settings = readSettings();
  const { command, args } = backendCommand();
  const dataDir = join(app.getPath("userData"), "engine");
  mkdirSync(dataDir, { recursive: true });
  const argv = [
    ...args,
    "--data-dir",
    dataDir,
    "--token-file",
    tokenFile(),
    "--output-dir",
    settings.outputFolder,
  ];
  for (const folder of settings.mediaFolders) argv.push("--media-root", folder);
  const bins = ffmpegPaths();
  if (bins.length) {
    argv.push("--ffmpeg", bins[0]);
    const probe = bins.find((item) => /ffprobe/.test(item));
    if (probe) argv.push("--ffprobe", probe);
  }
  const child = spawn(command, argv, {
    cwd: dataDir,
    windowsHide: true,
    env: { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" },
  }) as ChildProcessWithoutNullStreams;
  backend = child;
  // 引擎的 stderr 落盘，出问题时用户能把一个文件发给支持人员，而不是"重启试试"。
  const log = logFile();
  const writeLog = (stream: string) => {
    try {
      if (existsSync(log) && statSync(log).size > 2_000_000) renameSync(log, `${log}.1`);
      appendFileSync(log, `[${new Date().toISOString()}] ${stream}`, "utf-8");
    } catch {
      /* 日志写不进去不能影响剪辑 */
    }
  };
  child.stderr.on("data", (chunk: Buffer) => {
    const text = chunk.toString("utf-8");
    writeLog(`[stderr] ${text}`);
    if (process.env.AGENTCUT_DEBUG) console.error("[engine]", text);
  });
  child.stdout.on("data", (chunk: Buffer) => writeLog(`[stdout] ${chunk.toString("utf-8")}`));
  return new Promise<BackendInfo>((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      // 超时不杀进程就会留下一个"看不见的引擎"，重试时还会再起一个。
      child.kill("SIGKILL");
      reject(new Error("剪辑引擎启动超时（15 秒）"));
    }, 15000);
    const onExit = (code: number | null) => {
      backend = null;
      backendInfo = null;
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        if (quitting || restarting) return;
        reject(new Error(`剪辑引擎意外退出（code ${code}）。正在自动重启…`));
      }
      if (quitting || restarting) return;
      // 已成功启动后的退出是崩溃：外壳自动拉起，界面会收到 engine:ready。
      superviseRestart();
    };
    child.on("exit", onExit);
    // 逐行扫描全部输出：ready 之前可能有其它 JSON 事件行，只看第一行会永远错过。
    let buffered = "";
    child.stdout.on("data", (chunk: Buffer) => {
      if (settled) return;
      buffered += chunk.toString("utf-8");
      const lines = buffered.split("\n");
      buffered = lines.pop() ?? "";
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("{")) continue;
        try {
          const parsed = JSON.parse(trimmed) as BackendInfo & { event: string };
          if (parsed.event !== "ready") continue;
          settled = true;
          clearTimeout(timer);
          const token = existsSync(tokenFile()) ? readFileSync(tokenFile(), "utf-8").trim() : "";
          backendInfo = { ...parsed, token };
          resolve(backendInfo);
          return;
        } catch {
          /* 半行 JSON，忽略 */
        }
      }
    });
  });
}

/** 引擎意外退出后自动拉起：连续失败 5 次才放弃并把原因交给界面。 */
let restarts = 0;
// 用户还没真用过就没有一台引擎该被拉起：崩溃监督也不能替他做这件事。
let engineWanted = false;
function superviseRestart() {
  if (quitting || !engineWanted || restarts >= 5) {
    send("engine:error", "剪辑引擎连续启动失败。请查看引擎日志，或重新安装 AgentCut。");
    return;
  }
  restarts += 1;
  const wait = Math.min(600 * restarts, 3000);
  setTimeout(() => {
    startBackend()
      .then((info) => {
        restarts = 0;
        send("engine:ready", info);
      })
      .catch((error: Error) => send("engine:error", error.message));
  }, wait);
}

async function stopBackend() {
  const child = backend;
  backend = null;
  backendInfo = null;
  if (!child) return;
  await new Promise<void>((resolve) => {
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      resolve();
    }, 3000);
    child.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
    child.kill("SIGTERM");
  });
}

function createWindow() {
  const state = readWindowState();
  const created = new BrowserWindow({
    ...state,
    minWidth: MIN_SIZE.width,
    minHeight: MIN_SIZE.height,
    frame: false,
    show: false,
    backgroundColor: "#f6f6f8",
    title: "AgentCut 剪辑台",
    icon: join(__dirname, "..", "build", "icon.ico"),
    webPreferences: {
      preload: join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      spellcheck: false,
      sandbox: false,
    },
  });
  window = created;
  if (state.maximized) created.maximize();
  created.once("ready-to-show", () => created.show());
  created.webContents.on("context-menu", (_event, params) => {
    // 只在可编辑处给出系统剪贴板菜单，其余保持应用内交互。
    if (!params.isEditable) return;
    Menu.buildFromTemplate([
      { role: "cut" },
      { role: "copy" },
      { role: "paste" },
    ]).popup({ window: created });
  });
  const persist = () => {
    if (!created.isMinimized() && !created.isMaximized()) {
      const bounds = created.getBounds();
      writeFileSync(
        stateFile(),
        JSON.stringify({ ...bounds, maximized: false } satisfies WindowState),
        "utf-8"
      );
    }
  };
  created.on("moved", persist);
  created.on("resized", persist);
  created.on("close", () => {
    const maximized = created.isMaximized();
    // 最大化时 getBounds 返回铺满屏幕的边界；持久化"正常"边界，取消最大化才不会四边出屏。
    const bounds = created.getNormalBounds();
    writeFileSync(
      stateFile(),
      JSON.stringify({ ...bounds, maximized } satisfies WindowState),
      "utf-8"
    );
  });
  created.on("closed", () => {
    window = null;
  });
  const target = process.argv.find((item) => item.startsWith("http://127.0.0.1:"));
  if (target && process.env.AGENTCUT_DEBUG) {
    // 仅调试模式允许把任意本地页面装进带完整 bridge 的主窗口。
    void created.loadURL(target);
  } else {
    void created.loadFile(join(__dirname, "..", "dist", "renderer", "index.html"));
  }
  if (process.env.AGENTCUT_DEBUG) created.webContents.openDevTools({ mode: "detach" });
}

function send(channel: string, payload: unknown) {
  window?.webContents.send(channel, payload);
}

/**
 * 分块复制进素材库：大文件不会冻结界面，进度实时回报；
 * 同名文件自动加序号，绝不静默覆盖用户已经导入过的素材。
 */
async function copyIntoLibrary(source: string, folder: string): Promise<string> {
  const real = realpathSync(source);
  const base = basename(real);
  const dot = base.lastIndexOf(".");
  const stem = dot > 0 ? base.slice(0, dot) : base;
  const ext = dot > 0 ? base.slice(dot) : "";
  let target = join(folder, base);
  let index = 1;
  while (existsSync(target)) {
    index += 1;
    target = join(folder, `${stem}-${n2(index)}${ext}`);
  }
  if (target === real) return real;
  const total = statSync(real).size;
  await new Promise<void>((resolve, reject) => {
    const input = createReadStream(real);
    const output = createWriteStream(target);
    let done = 0;
    input.on("data", (chunk) => {
      done += chunk.length;
      if (done % (4 << 20) < (1 << 20)) send("media:progress", { file: base, done, total });
    });
    input.on("error", (error) => {
      output.destroy();
      try {
        rmSync(target);
      } catch {
        /* 半成品可能已被清理 */
      }
      reject(error);
    });
    output.on("error", reject);
    output.on("finish", () => resolve());
    input.pipe(output);
  });
  return target;
}

const n2 = (value: number) => String(value).padStart(2, "0");

function registerIpc() {
  ipcMain.handle("engine:start", async () => {
    engineWanted = true; // 这是「用户真的用了」那一下：在此之前一台引擎都不该起
    try {
      return { ok: true, info: await startBackend() };
    } catch (error) {
      return { ok: false, error: String(error instanceof Error ? error.message : error) };
    }
  });
  ipcMain.handle("engine:status", () => ({ running: Boolean(backendInfo), info: backendInfo ?? undefined }));
  ipcMain.handle("window:control", (_event, action: string) => {
    const win = window;
    if (!win) return null;
    if (action === "minimize") win.minimize();
    else if (action === "maximize") win.isMaximized() ? win.unmaximize() : win.maximize();
    else if (action === "restore") win.unmaximize();
    else if (action === "close") win.close();
    else if (action === "fullscreen") win.setFullScreen(!win.isFullScreen());
    return { maximized: win.isMaximized(), fullscreen: win.isFullScreen() };
  });
  ipcMain.handle("window:state", () => {
    const win = window;
    if (!win) return { maximized: false, fullscreen: false };
    return { maximized: win.isMaximized(), fullscreen: win.isFullScreen() };
  });
  ipcMain.handle("window:resize", (_event, edge: string, dx: number, dy: number) => {
    const win = window;
    if (!win || win.isMaximized()) return null;
    const bounds = win.getBounds();
    const minW = MIN_SIZE.width;
    const minH = MIN_SIZE.height;
    if (edge.includes("left")) {
      // 先算出"新宽度"，再用它回推 x —— 与 top 缘公式对称，最小宽度处不会吸入右缘。
      const next = Math.max(minW, bounds.width - dx);
      bounds.x = bounds.x + (bounds.width - next);
      bounds.width = next;
    }
    if (edge.includes("right")) bounds.width = Math.max(minW, bounds.width + dx);
    if (edge.includes("top")) {
      const next = Math.max(minH, bounds.height - dy);
      bounds.y = bounds.y + bounds.height - next;
      bounds.height = next;
    }
    if (edge.includes("bottom")) bounds.height = Math.max(minH, bounds.height + dy);
    win.setBounds(bounds);
    return bounds;
  });
  ipcMain.handle("dialog:openMedia", async () => {
    const win = window;
    if (!win) return { cancelled: true };
    const result = await dialog.showOpenDialog(win, {
      title: "选择要导入的素材（视频 / 音频 / 图片）",
      buttonLabel: "导入到素材库",
      properties: ["openFile", "multiSelections"],
      filters: [
        { name: "常见素材", extensions: ["mp4", "mov", "m4v", "mkv", "webm", "avi", "mp3", "wav", "m4a", "aac", "flac", "png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"] },
        { name: "所有文件", extensions: ["*"] },
      ],
    });
    if (result.canceled || !result.filePaths.length) return { cancelled: true };
    const settings = readSettings();
    const library = settings.mediaFolders[0];
    mkdirSync(library, { recursive: true });
    const copied: { from: string; to: string }[] = [];
    let copyError = "";
    for (const source of result.filePaths) {
      try {
        const target = await copyIntoLibrary(source, library);
        copied.push({ from: source, to: target });
      } catch (error) {
        // 单个文件失败不否定整批：已复制成功的照常返回去探测。
        copyError = `复制到素材库失败：${String(error)}`;
      }
    }
    if (!copied.length) return { cancelled: true, error: copyError };
    send("media:progress", { file: "", done: 0, total: 0 });
    return { cancelled: false, copied, library, error: copyError || undefined };
  });
  ipcMain.handle("dialog:pickOutputFolder", async () => {
    const win = window;
    if (!win) return { cancelled: true };
    const result = await dialog.showOpenDialog(win, {
      title: "选择成品输出文件夹",
      buttonLabel: "用这个文件夹",
      properties: ["openDirectory", "createDirectory"],
    });
    if (result.canceled || !result.filePaths.length) return { cancelled: true };
    return { cancelled: false, folder: result.filePaths[0] };
  });
  ipcMain.handle("dialog:pickMediaRoot", async () => {
    const win = window;
    if (!win) return { cancelled: true };
    const result = await dialog.showOpenDialog(win, {
      title: "添加一个素材文件夹（Agent 也可直接从里面导入）",
      buttonLabel: "添加",
      properties: ["openDirectory"],
    });
    if (result.canceled || !result.filePaths.length) return { cancelled: true };
    const settings = readSettings();
    if (!settings.mediaFolders.includes(result.filePaths[0])) {
      settings.mediaFolders.push(result.filePaths[0]);
      writeSettings(settings);
    }
    await restartBackend();
    return { cancelled: false, folders: settings.mediaFolders, info: backendInfo };
  });
  ipcMain.handle("shell:showItem", (_event, path: string) => {
    shell.showItemInFolder(path);
    return true;
  });
  ipcMain.handle("shell:openExternal", (_event, url: string) => {
    if (/^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?(\/|$)/.test(url)) void shell.openExternal(url);
    return true;
  });
  ipcMain.handle("clipboard:writeText", (_event, text: string) => {
    clipboard.writeText(text);
    return true;
  });
  ipcMain.handle("settings:outputFolder", (_event, folder: string) => {
    const settings = readSettings();
    if (!folder) return { ok: false, folder: settings.outputFolder };
    try {
      mkdirSync(folder, { recursive: true });
    } catch {
      return { ok: false, folder: settings.outputFolder };
    }
    writeSettings({ ...settings, outputFolder: folder });
    return { ok: true, folder };
  });
  ipcMain.handle("settings:read", () => {
    const settings = readSettings();
    return { outputFolder: settings.outputFolder, mediaFolders: settings.mediaFolders };
  });
  ipcMain.handle("app:token", () => {
    return existsSync(tokenFile()) ? readFileSync(tokenFile(), "utf-8").trim() : "";
  });
  ipcMain.handle("app:restartEngine", async () => {
    await restartBackend();
    return { ok: true, info: backendInfo };
  });
  ipcMain.handle("app:info", () => ({
    version: app.getVersion(),
    electron: process.versions.electron,
    userData: app.getPath("userData"),
    library: readSettings().mediaFolders,
    // MCP 配置模板要用真实的引擎路径：便携版/自定义安装目录下硬编码路径是错的。
    enginePath: engineExecutable(),
  }));
}

function engineExecutable(): string {
  const resources = process.resourcesPath;
  return (
    [
      join(resources, "bin", "agentcut.exe"),
      join(resources, "bin", "agentcut", "agentcut.exe"),
    ].find((item) => existsSync(item)) ?? ""
  );
}

async function restartBackend() {
  restarting = true;
  await stopBackend();
  restarting = false;
  try {
    const info = await startBackend();
    send("engine:ready", info);
  } catch (error) {
    send("engine:error", String(error));
  }
}

app.whenReady().then(() => {
  app.setAppUserModelId(APP_ID);
  Menu.setApplicationMenu(null);
  registerIpc();
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

/**
 * 单实例：两个 AgentCut 同时写同一个项目库只会互相踩。
 * 第二次启动时把已有窗口叫到前面，而不是再开一个引擎。
 */
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    const existing = BrowserWindow.getAllWindows()[0];
    if (!existing) {
      createWindow();
      return;
    }
    if (existing.isMinimized()) existing.restore();
    existing.show();
    existing.focus();
  });
}

app.on("window-all-closed", () => {
  quitting = true;
  void stopBackend().finally(() => app.quit());
});

process.on("exit", () => {
  if (backend && !backend.killed) backend.kill("SIGTERM");
});
