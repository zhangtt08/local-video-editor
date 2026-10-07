import { useSyncExternalStore } from "react";

import { bridge, isNative, urlParam } from "./bridge";
import type { BackendInfo, WindowState } from "../electron/shared";
import {
  Engine,
  EngineError,
  assetImport,
  clipAdd,
  clipMove,
  clipRemove,
  clipSplit,
  clipTrim,
  newId,
  trackAdd,
  trackRemove,
  trackUpdate,
} from "./engine";
import type {
  Capabilities,
  Clip,
  Command,
  MutationResult,
  Probe,
  Project,
  RenderJob,
  Track,
  Effects,
  Keyframe,
  ClipColor,
  TextStyle,
  Asset,
  ShapeMask,
  SpeedPoint,
  Property,
  Marker,
  RenderFit,
  RenderRange,
  RenderBatchItem,
} from "./engine";
import { FIT_MODES, type TransitionKind } from "./engine";
import { align, frameTicks, sampleTicks, ticks, TIMEBASE } from "./time";
import { copyClips, pasteCommands, relatedClips, selectionQuantum, timelineTracks, type ClipClipboard } from "./selection";

export type View = "home" | "editor" | "history" | "agent";

export type Toast = {
  id: number;
  kind: "info" | "ok" | "warn" | "error";
  title: string;
  detail?: string;
};

export type LibraryItem = {
  probe: Probe;
  path: string;
  added_at: string;
};

export type HistoryRow = {
  revision: number;
  operation: string;
  request_id: string;
  created_at: string;
};

type UndoEntry = { revision: number; label: string };

export type ProjectSummary = {
  id: string;
  name: string;
  revision: number;
  clips: number;
  durationTicks: number;
  assets: number;
};

export type AppState = {
  phase: "boot" | "ready" | "failed";
  bootError: string;
  info: BackendInfo | null;
  caps: Capabilities | null;
  projects: ProjectSummary[];
  project: Project | null;
  rootProject: Project | null;
  rootCandidate: Project | null;
  sequenceId: string | null;
  sequencePath: string[];
  streams: Record<string, string>;
  originals: Record<string, string>;
  proxyWidth: number;
  proxyActive: Record<string, string>;
  proxyStatus: { label: string; done: number; total: number };
  proxyUsage: { used_bytes: number; limit_bytes: number; count: number };
  cacheUsage: { used_bytes: number; limit_bytes: number; count: number };
  library: LibraryItem[];
  view: View;
  selectedClip: string | null;
  selectedClips: string[];
  clipboardCount: number;
  selectedAsset: string | null;
  mode: "instant" | "batch";
  batch: Command[];
  batchSequenceId: string | null;
  candidate: Project | null;
  dryRunError: string;
  dryRunBusy: boolean;
  busy: string;
  toasts: Toast[];
  jobs: RenderJob[];
  history: HistoryRow[];
  undo: UndoEntry[];
  redo: UndoEntry[];
  window: WindowState;
  showHelp: boolean;
  assetFilter: "all" | "video" | "image" | "audio";
  remoteAhead: number | null;
  editorPanel: "inspect" | "export" | "scope";
  graphOpen: boolean;
  maskEditing: boolean;
  monitorMode: "timeline" | "source";
  sourceCursorTicks: number;
  sourcePlaying: boolean;
  sourceMarks: Record<string, { in_ticks?: number; out_ticks?: number }>;
  targetTrack: string | null;
  sourceRippleAll: boolean;
  bundleRetry: string;
};

const listeners = new Set<() => void>();
let state: AppState = {
  phase: "boot",
  bootError: "",
  info: null,
  caps: null,
  projects: [],
  project: null,
  rootProject: null,
  rootCandidate: null,
  sequenceId: null,
  sequencePath: [],
  streams: {},
  originals: {},
  proxyWidth: readStoredProxyWidth(),
  proxyActive: {},
  proxyStatus: { label: "", done: 0, total: 0 },
  proxyUsage: { used_bytes: 0, limit_bytes: 0, count: 0 },
  cacheUsage: { used_bytes: 0, limit_bytes: 0, count: 0 },
  library: [],
  view: "home",
  selectedClip: null,
  selectedClips: [],
  clipboardCount: 0,
  selectedAsset: null,
  mode: "instant",
  batch: [],
  batchSequenceId: null,
  candidate: null,
  dryRunError: "",
  dryRunBusy: false,
  busy: "",
  toasts: [],
  jobs: [],
  history: [],
  undo: [],
  redo: [],
  window: { width: 1480, height: 900, maximized: false },
  showHelp: false,
  assetFilter: "all",
  remoteAhead: null,
  editorPanel: "inspect",
  graphOpen: false,
  maskEditing: false,
  monitorMode: "timeline",
  sourceCursorTicks: 0,
  sourcePlaying: false,
  sourceMarks: {},
  targetTrack: null,
  sourceRippleAll: true,
  bundleRetry: "",
};

function set(patch: Partial<AppState>) {
  if (patch.batch && !patch.batch.length) patch.batchSequenceId = null;
  if (patch.project) {
    patch.rootProject = patch.project;
    const same = patch.project.id === state.project?.id;
    const sequenceId = same ? state.sequenceId : null;
    if (sequenceId && patch.project.sequences?.[sequenceId]) patch.project = sequenceView(patch.project, sequenceId);
    else { patch.sequenceId = null; patch.sequencePath = []; }
  }
  if ("candidate" in patch) {
    patch.rootCandidate = patch.candidate;
    if (patch.candidate) patch.candidate = sequenceView(patch.candidate, state.sequenceId);
  }
  if (patch.selectedClips) patch.selectedClip = patch.selectedClips.at(-1) ?? null;
  else if ("selectedClip" in patch) patch.selectedClips = patch.selectedClip ? [patch.selectedClip] : [];
  if (patch.project) {
    patch.selectedClips = (patch.selectedClips ?? state.selectedClips).filter((id) => Boolean(patch.project!.clips[id]));
    patch.selectedClip = patch.selectedClips.at(-1) ?? null;
  }
  state = { ...state, ...patch };
  listeners.forEach((fn) => fn());
}

function sequenceView(root: Project, id: string | null): Project {
  const sequence = id ? root.sequences?.[id] : null;
  return sequence ? { ...root, tracks: sequence.tracks, clips: sequence.clips } : root;
}

let engine: Engine | null = null;
let pendingBundle: { file: File; requestId: string } | null = null;
let toastSeq = 1;
let dryRunTimer: number | undefined;
let dryRunVersion = 0;

export function toast(kind: Toast["kind"], title: string, detail?: string) {
  const id = toastSeq++;
  set({ toasts: [...state.toasts, { id, kind, title, detail }] });
  window.setTimeout(() => dismissToast(id), kind === "error" ? 7000 : 3200);
}

export function dismissToast(id: number) {
  set({ toasts: state.toasts.filter((item) => item.id !== id) });
}

function describe(error: unknown): { title: string; detail: string } {
  if (error instanceof EngineError) return { title: error.code, detail: error.explain() };
  const message = error instanceof Error ? error.message : String(error);
  return { title: "操作失败", detail: message };
}

export const get = () => state;

/** Editing reads the validated candidate; stale or invalid batches cannot seed new values. */
export function editableProject(app = state, displayOnly = false): Project | null {
  const project = app.project;
  if (app.mode !== "batch" || !app.batch.length) return project;
  return (displayOnly || !app.dryRunBusy) && !app.dryRunError && app.candidate?.id === project?.id
    && app.candidate?.revision === (project?.revision ?? 0) + 1 ? app.candidate : null;
}
export function setEditorPanel(editorPanel: AppState["editorPanel"]) {
  set({ editorPanel, view: "editor" });
}

export function setGraphOpen(graphOpen: boolean) { set({ graphOpen, view: "editor" }); }
export function setMaskEditing(maskEditing: boolean) { playhead.pause(); setMonitorMode("timeline"); set({ maskEditing }); }
export function useApp(): AppState {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    get,
    get
  );
}

/* ---------------------------------------------------------------- 播放头 */

type PlayState = { ticks: number; playing: boolean };
const playListeners = new Set<() => void>();
let play: PlayState = { ticks: 0, playing: false };

function setPlay(patch: Partial<PlayState>) {
  play = { ...play, ...patch };
  playListeners.forEach((fn) => fn());
}

export function usePlay(): PlayState {
  return useSyncExternalStore(
    (fn) => {
      playListeners.add(fn);
      return () => playListeners.delete(fn);
    },
    () => play,
    () => play
  );
}

export const playhead = {
  get value() {
    return play.ticks;
  },
  set(value: number) {
    setPlay({ ticks: Math.max(0, Math.round(value)) });
  },
  get playing() {
    return play.playing;
  },
  play() {
    setPlay({ playing: true });
  },
  pause() {
    setPlay({ playing: false });
  },
};

/* ---------------------------------------------------------------- 时间量化 */

export function quantum(project: Project, kind: "video" | "audio"): number {
  return kind === "audio"
    ? sampleTicks(project.settings.sample_rate)
    : frameTicks(project.settings.frame_rate);
}

export function snapTo(project: Project, kind: "video" | "audio", value: number): number {
  return align(value, quantum(project, kind), 0);
}

/** 时间线总长度（tick）：所有片段结束点的最大值，用于标尺和导出时长。 */
export function timelineEnd(project: Project | null): number {
  if (!project) return 0;
  let end = state.sequenceId && project.id === state.project?.id ? project.sequences?.[state.sequenceId]?.duration_ticks ?? 0 : 0;
  for (const clip of Object.values(project.clips)) {
    end = Math.max(end, clip.position_ticks + clip.duration_ticks);
  }
  return end;
}

/* ---------------------------------------------------------------- 启动 */

// 引擎恢复/异常/复制进度监听只注册一次：boot 可能因重试被多次调用，
// 重复注册会让一次恢复触发 N 次重载。
let listenersBound = false;
function bindBridgeListeners() {
  if (listenersBound || !isNative) return;
  listenersBound = true;
  bridge.onEngineReady((next) => {
    void bootAfterReady(next);
  });
  bridge.onEngineError((message) => toast("error", "剪辑引擎异常", message));
  bridge.onMediaProgress((progress) => {
    if (!progress.file) return;
    const pct = progress.total ? Math.round((progress.done / progress.total) * 100) : 0;
    set({ busy: `正在复制 ${progress.file} ${pct}%` });
  });
}

export async function boot() {
  set({ phase: "boot", bootError: "" });
  bindBridgeListeners();
  const result = await bridge.startEngine();
  if (!result.ok || !result.info) {
    set({ phase: "failed", bootError: result.error ?? "剪辑引擎未能启动" });
    return;
  }
  const info = result.info;
  const token = info.token || (await bridge.token());
  engine = new Engine(info.base_url, token);
  set({ info });
  try {
    const caps = await engine.capabilities();
    set({ phase: "ready", caps });
    await refreshProjects();
    await restoreDeepLink();
  } catch (error) {
    const { title, detail } = describe(error);
    set({ phase: "failed", bootError: `${title}：${detail}` });
  }
}

async function restoreDeepLink() {
  // 深链 ?project= / ?view= 优先；否则回到上次打开的工程，软件重启不该让人重新找一遍。
  let wanted = "";
  try {
    wanted = urlParam("project") || (localStorage.getItem("agentcut.lastProject") ?? "");
  } catch {
    wanted = urlParam("project");
  }
  const view = urlParam("view");
  if (view === "home" || view === "editor" || view === "history" || view === "agent") {
    set({ view });
  }
  if (wanted && state.projects.some((item) => item.id === wanted)) void openProject(wanted);
}

/** 引擎被外壳重新拉起后，接口地址会变；重建客户端并刷新界面。 */
async function bootAfterReady(info: BackendInfo) {
  engine = new Engine(info.base_url, info.token || (await bridge.token()));
  set({ info: { ...info, token: info.token || (await bridge.token()) } });
  try {
    const caps = await engine.capabilities();
    set({ caps, phase: "ready", remoteAhead: null });
    await refreshProjects();
    const current = state.project;
    if (current) {
      // 只刷新工程数据，不重置批次与撤销栈：重启不该丢掉用户攒的操作。
      const project = await engine.project(current.id);
      set({ project, undo: [], redo: [] });
      void loadStreams(project.id);
      if (state.batch.length) void runDryRun();
    }
    toast("ok", "剪辑引擎已恢复", "已提交的版本都在本地库里；未提交批次已保留。");
  } catch {
    /* 引擎还在起，界面已有提示，不重复打扰 */
  }
}

/**
 * Agent 可能就在你剪辑时改同一条时间线。每 4 秒比对一次服务端版本，
 * 领先了就明确提示，绝不静默覆盖任何一边。
 */
let pollTimer: number | undefined;
let ignoredRemoteRevision = 0;
export function startRemoteWatch() {
  if (pollTimer) window.clearInterval(pollTimer);
  pollTimer = window.setInterval(() => void checkRemote(), 4000);
}

async function checkRemote() {
  if (!engine || !state.project || state.batch.length || state.busy || state.remoteAhead) return;
  try {
    const list = await engine.projects();
    const mine = list.projects.find((item) => item.id === state.project?.id);
    // 「稍后」忽略过的版本不再反复弹，只有更新才重新提示。
    if (mine && mine.revision > Math.max(state.project.revision, ignoredRemoteRevision)) {
      set({ remoteAhead: mine.revision });
    }
  } catch {
    /* 取不到就当没变化，不打扰用户 */
  }
}

export function dismissRemote() {
  ignoredRemoteRevision = state.remoteAhead ?? ignoredRemoteRevision;
  set({ remoteAhead: null });
}

export async function refreshProjects() {
  if (!engine) return;
  try {
    const result = await engine.projects();
    // 列表接口只给 id/名称/版本；主页要显示真实时长与片段数，所以逐条取回摘要。
    const summaries = await Promise.all(
      result.projects.slice(0, 40).map(async (item): Promise<ProjectSummary> => {
        try {
          const project = await engine!.project(item.id);
          return { ...item, clips: Object.keys(project.clips).length, durationTicks: timelineEnd(project), assets: Object.keys(project.assets).length };
        } catch {
          return { ...item, clips: 0, durationTicks: 0, assets: 0 };
        }
      })
    );
    set({ projects: summaries });
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
  }
}

/* ---------------------------------------------------------------- 项目与历史 */

function showProject(project: Project) {
  const same = state.project?.id === project.id;
  try { localStorage.setItem("agentcut.lastProject", project.id); } catch { /* 存储不可用仍可打开 */ }
  playhead.pause();
  set({ project, view: "editor", selectedClips: [], selectedAsset: null, monitorMode: "timeline",
    sourcePlaying: false, sourceCursorTicks: 0, targetTrack: null, batch: same ? state.batch : [],
    candidate: null, dryRunError: "", undo: [], redo: [], streams: {}, originals: {}, proxyActive: {},
    proxyStatus: { label: "", done: 0, total: 0 }, remoteAhead: null });
  startRemoteWatch();
  playhead.set(same ? Math.min(playhead.value, timelineEnd(project)) : 0);
  void loadStreams(project.id); void loadLibrary(); void loadJobs(project.id);
  if (state.batch.length) scheduleDryRun();
}

export async function openProject(id: string) {
  if (!engine) return;
  if (state.busy) return;
  if (state.batch.length && state.project?.id !== id) { toast("warn", "先处理当前待提交批次", "提交或放弃批次后，再打开其他工程。"); return; }
  set({ busy: "读取项目…" });
  try {
    showProject(await engine.project(id));
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
  } finally {
    set({ busy: "" });
  }
}

function readStoredProxyWidth(): number {
  try { return Number(localStorage.getItem("agentcut.proxyWidth") ?? 0) || 0; } catch { return 0; }
}

/** `streams` is what the monitor plays: original URLs, overridden by any ready proxy. */
function applyPlaybackUrls() {
  const streams = { ...state.originals };
  for (const [assetId, url] of Object.entries(state.proxyActive)) if (streams[assetId]) streams[assetId] = url;
  set({ streams });
}

async function loadStreams(id: string) {
  if (!engine) return;
  try {
    const urls = await engine.assetUrls(id);
    const originals: Record<string, string> = {};
    for (const [assetId, item] of Object.entries(urls.assets)) originals[assetId] = item.stream;
    if (state.project?.id !== id) return;
    set({ originals, proxyActive: {} });
    applyPlaybackUrls();
    void refreshProxyUsage();
    if (state.proxyWidth) void resolveProxies(state.proxyWidth);
  } catch {
    /* 素材未验证时没有流地址，界面上如实显示“无画面” */
  }
}

export const PROXY_WIDTHS = [640, 960, 1280];

export async function setProxyWidth(width: number) {
  const chosen = PROXY_WIDTHS.includes(width) ? width : 0;
  try { localStorage.setItem("agentcut.proxyWidth", String(chosen)); } catch { /* 偏好当场生效即可 */ }
  set({ proxyWidth: chosen, proxyActive: {}, proxyStatus: { label: "", done: 0, total: 0 } });
  applyPlaybackUrls();
  if (chosen) await resolveProxies(chosen);
}

/** Ask the engine for a proxy of every video asset on the timeline, building the missing ones. */
async function resolveProxies(width: number) {
  const project = state.project;
  if (!engine || !project) return;
  const used = new Set(Object.values(project.clips).map((clip) => clip.asset_id));
  const videos = Object.values(project.assets).filter((asset) => asset.kind === "video" && asset.verified && used.has(asset.id));
  const active: Record<string, string> = { ...state.proxyActive };
  let done = 0;
  set({ proxyStatus: { label: "", done: 0, total: videos.length } });
  for (const asset of videos) {
    if (state.proxyWidth !== width || state.project?.id !== project.id) return;
    set({ proxyStatus: { label: asset.label, done, total: videos.length } });
    try {
      let record = await engine.proxyState(project.id, asset.id, width);
      if (record.state === "absent") record = await engine.proxyBuild(project.id, asset.id, width);
      if (record.state === "ready" && record.stream) {
        active[asset.id] = record.stream;
        set({ proxyActive: { ...active } });
        applyPlaybackUrls();
      }
    } catch (error) {
      const { title, detail } = describe(error);
      toast("warn", title, `${detail} 已改用原片回放。`);
      set({ proxyWidth: 0, proxyActive: {}, proxyStatus: { label: "", done: 0, total: 0 } });
      applyPlaybackUrls();
      return;
    }
    done += 1;
  }
  set({ proxyStatus: { label: "", done, total: videos.length } });
  void refreshProxyUsage();
}

/** Follow the picture with the clip's box mask: the engine analyses the media, the write is a normal command. */
/** 主体跟随重构图：把已经跟好的遮罩路径交给引擎，换回一条把主体锁在画面中间的平移 + 缩放。 */
export async function reframeClip(clipId: string, maxScale = 4) {
  const project = state.project;
  if (!engine || !project) return;
  set({ busy: "计算主体跟随…" });
  try {
    const planned = await engine.reframe(project.id, clipId, {
      request_id: newId("reframe-"), expected_revision: project.revision,
      max_scale: maxScale, apply: false, dry_run: false,
    });
    const stats = planned["reframe"] as {
      followed_points?: number; keyframes_added?: number; max_scale?: number;
      worst_offset?: number; clamped_points?: number; warning?: string;
    } | undefined;
    if (!planned.commands.length || !stats) {
      toast("warn", "没有可写入的跟随曲线", "引擎认为这条片段不需要（或还不能）重构图。");
      return;
    }
    submit(planned.commands as Command[], "主体跟随重构图");
    const detail = [
      `按跟好的路径采样 ${stats.followed_points} 个关键点` +
        (stats.keyframes_added ? `（引擎补了 ${stats.keyframes_added} 个）` : ""),
      `最多放大 ${stats.max_scale?.toFixed(2) ?? "?"} 倍`,
      stats.warning ??
        `主体偏离画面中心最多 ${((stats.worst_offset ?? 0) * 100).toFixed(1)}% 画面宽`,
    ].join(" · ");
    toast("ok", "主体跟随已写入", `${detail}。撤销一步回到跟随前。`);
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
  } finally {
    set({ busy: "" });
  }
}

export async function trackMask(clipId: string, fromTicks: number, frames: number) {
  const project = state.project;
  if (!engine || !project) return;
  set({ busy: "跟踪遮罩主体…" });
  try {
    const analysed = await engine.maskTrack(project.id, clipId, {
      request_id: newId("track-"), expected_revision: project.revision,
      from_ticks: fromTicks, frames, dry_run: true,
    });
    const points = analysed.tracking.points;
    if (points.length < 2) {
      toast("warn", "找不到可跟踪的目标", "这段画面里没有稳定的主体，遮罩保持不变。可以把遮罩先盖在主体上再试。");
      return;
    }
    submit([{ op: "clip.mask_track", clip_id: clipId, points }], "跟踪遮罩主体");
    const stats = analysed.tracking;
    const detail = [
      stats.scale_estimated ? "遮罩盒随主体远近变大变小，" : "遮罩盒保持原大小，",
      stats.predicted_frames > 0 ? `${stats.predicted_frames} 帧被遮挡时按匀速补齐，` : "",
      stats.lost_at_ticks === null
        ? "导出使用同一份关键帧。"
        : `在 ${(stats.lost_at_ticks / TIMEBASE).toFixed(2)} 秒处跟丢目标，之后遮罩停在最后找到的位置。`,
    ].join("");
    toast("info", `已跟踪 ${points.length} 帧`, detail);
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
  } finally {
    set({ busy: "" });
  }
}

/** 剪掉本段的停顿：引擎扫描声音并给出剪切命令，一次提交只产生一个版本。 */
export async function cutSilence(clipId: string) {
  const project = state.project;
  if (!engine || !project) return;
  set({ busy: "扫描静音…" });
  try {
    const scanned = await engine.silenceScan(project.id, clipId, {
      request_id: newId("silence-"), expected_revision: project.revision,
    });
    const commands = scanned.silence.commands;
    if (!commands.length) {
      toast("info", "没有发现停顿", "这段声音里没有足够长的静音，或者静音正好在首尾。");
      return;
    }
    submit(commands as Command[], "去掉静音空白");
    const seconds = scanned.silence.removed_ticks / TIMEBASE;
    toast("info", `去掉 ${countCuts(commands)} 处停顿，共 ${seconds.toFixed(2)} 秒`,
      "后面的内容已左移，切点向内取整帧，不会切进说话。撤销可回到原样。");
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
  } finally {
    set({ busy: "" });
  }
}

function countCuts(commands: Record<string, unknown>[]) {
  return commands.filter((command) => command.op === "clip.ripple_remove").length;
}

/** 自动字幕：本地语音模型把这段的说话转成一条字幕轨，一次提交一个版本，撤销即删整轨。
 *  重跑时替换上一轮生成的同一条轨（按工程+片段+语言记住轨 id），不会把相同字幕摞两层。 */
export async function autoCaptions(clipId: string) {
  const project = state.project;
  if (!engine || !project) return;
  set({ busy: "识别语音…" });
  try {
    const key = `agentcut.asrTrack.${project.id}.${clipId}.zh`;
    const previous = localStorage.getItem(key) ?? "";
    const known = previous && project.tracks.some((track) => track.id === previous) ? previous : null;
    const result = await engine.speechCaptions(project.id, {
      request_id: newId("speech-"), expected_revision: project.revision,
      clip_id: clipId, language: "zh", replace_track_id: known,
    });
    const speech = result.speech;
    if (!speech.cues.length) {
      toast("info", "没有听清说话", "这段声音里没有识别出语句。");
      return;
    }
    submit(speech.commands as Command[], known ? "重新生成自动字幕" : "自动字幕");
    try { localStorage.setItem(key, String(speech.command.track_id)); } catch { /* 存储不可用则下次重跑会另起一条 */ }
    toast("info", `生成 ${speech.cues.length} 条字幕`,
      `本地模型 ${speech.model}（中文）按停顿和行长分了行；双击字幕片段即可改字，撤销一次整轨消失。`);
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
  } finally {
    set({ busy: "" });
  }
}

/** 把这段的响度统一到目标 LUFS：引擎测一次，写进去的只是一个线性增益。 */
export async function normaliseLoudness(clipId: string) {
  const project = state.project;
  const clip = project?.clips[clipId];
  if (!engine || !project || !clip) return;
  set({ busy: "测量响度…" });
  try {
    const scanned = await engine.loudnessScan(project.id, clipId, {
      request_id: newId("loudness-"), expected_revision: project.revision,
    });
    const found = scanned.loudness;
    const effects = { ...clip.effects, gain: found.gain };
    submit([{ op: "clip.effects", clip_id: clipId, effects }] as Command[], "统一响度");
    const why = found.limited_by === "ceiling" ? "已按真峰值上限收住"
      : found.limited_by === "gain_range" ? "已到增益上限（4 倍）" : "正好达到目标";
    toast("info", `响度 ${found.integrated_lufs.toFixed(1)} → ${found.predicted_lufs.toFixed(1)} LUFS`,
      `目标 ${found.target_lufs} LUFS，线性增益 ${found.gain} 倍，${why}；预期峰值 ${found.predicted_peak_dbtp} dBTP。只改音量倍数，不插入压缩器。`);
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
  } finally {
    set({ busy: "" });
  }
}

/** 整轨响度对齐：逐片段测量后一次写入各自的增益，只产生一个版本。 */
export async function alignTrackLoudness(trackId: string) {
  const project = state.project;
  if (!engine || !project) return;
  set({ busy: "对齐整轨响度…" });
  try {
    const scanned = await engine.loudnessTrack(project.id, trackId, {
      request_id: newId("loudness-"), expected_revision: project.revision,
    });
    const report = scanned.loudness;
    const skipped = report.clips.length - report.measured;
    if (!report.commands.length) {
      toast("info", "这条轨已经对齐", report.measured
        ? `${report.measured} 段已经在 ${report.target_lufs} LUFS 附近，无需改动。`
        : "这条轨上没有可测量的声音片段（无音轨、带变速曲线、音量已打关键帧或已链接）。");
      return;
    }
    submit(report.commands as Command[], "整轨统一响度");
    toast("info", `对齐 ${report.changed} 段响度到 ${report.target_lufs} LUFS`,
      (report.off_target ? `${report.off_target} 段受 4 倍增益或真峰值上限限制到不了目标。` : "")
      + (skipped ? `${skipped} 段被跳过（无音轨、变速曲线、音量已打关键帧或已链接）。` : "")
      + "每段只改音量倍数，不加压缩器；撤销一次全部还原。");
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
  } finally {
    set({ busy: "" });
  }
}

/** 整片响度：让引擎用一次极小的探测渲染量出真实混音，再写一个母带增益把它对齐到目标。 */
export async function alignMasterLoudness(targetLufs = -14, limiter = false, ceilingDbtp = -7) {
  const project = state.project;
  if (!engine || !project) return;
  set({ busy: "测量整片响度…" });
  try {
    const result = await engine.masterLoudness(project.id, {
      request_id: newId("master-"), expected_revision: project.revision,
      target_lufs: targetLufs, limiter, ceiling_dbtp: ceilingDbtp, apply: true,
    });
    const report = result.master;
    set({ project: result.project as Project });
    const after = report.after;
    toast("ok", `整片对齐到 ${report.target_lufs} LUFS`,
      `实测混音 ${report.integrated_lufs} LUFS（真峰值 ${report.true_peak_dbtp} dBTP）→ 母带音量 `
      + `${report.current_master_gain} → ${report.proposed_master_gain}`
      + (report.limiter ? `，并打开 -${Math.abs(report.ceiling_applied_dbtp ?? 1)} dBTP 限制器` : "")
      + (after ? `。写入后再量一次：${after.integrated_lufs} LUFS / 真峰值 ${after.true_peak_dbtp} dBTP`
        : `，预测 ${report.predicted_lufs} LUFS`)
      + (report.reaches_target || report.measured_reaches_target
        ? "。"
        : `；受 ${report.limited_by === "ceiling" ? "真峰值上限" : "0–4 倍增益范围"}限制到不了目标`
          + `（${report.predicted_lufs} LUFS），要更响就勾上限制器。`));
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
  } finally {
    set({ busy: "" });
  }
}

/** 在指针处打一个标记。人和 Agent 用同一个整数刻度说「这里」，所以打点走的是普通命令。 */
export function addMarker(name?: string) {
  const project = state.project;
  if (!project) return;
  const at = Math.round(playhead.value);
  const label = name?.trim() || `标记 ${(project.markers?.length ?? 0) + 1}`;
  submit([{ op: "marker.set", marker: { id: newId("m"), at_ticks: at, name: label } }], "打点");
}

/** 删除标记：指针不必停在它上面，所以列表里的 × 是唯一入口。 */
export function removeMarker(markerId: string) {
  const project = state.project;
  if (!project) return;
  submit([{ op: "marker.remove", marker_id: markerId }], "删除标记");
}

/** 移动、改名或换色一个标记：落点已由标尺磁吸过，这里只提交一次编辑。 */
export function setMarker(marker: Marker, changes: Partial<Pick<Marker, "at_ticks" | "name" | "color">> = {}) {
  const project = state.project;
  if (!project) return;
  const next: Marker = { ...marker, ...changes };
  next.name = (next.name ?? marker.name).trim() || marker.name;
  if (next.at_ticks === marker.at_ticks && next.name === marker.name && next.color === marker.color) return;
  submit([{ op: "marker.set", marker: next }], next.at_ticks === marker.at_ticks ? "改标记" : "移动标记");
}

/** 按标记分割：一次问引擎所有标记会切在哪里，把普通 clip.split 合并成一条事务。 */
export async function splitAtMarkers() {
  const project = state.project;
  if (!engine || !project) return;
  if (!(project.markers ?? []).length) {
    toast("info", "还没有标记", "先在指针处按 M 打点，或让 Agent 用 marker.set 写入标记。");
    return;
  }
  set({ busy: "按标记分割…" });
  try {
    const scanned = await engine.markerSplit(project.id, {
      request_id: newId("markers-"), expected_revision: project.revision,
    });
    const plan = scanned.markers;
    if (!plan.commands.length) {
      toast("info", "标记处不需要分割", `${plan.markers} 个标记都落在片段边缘或空隙上，没有可切的段。`);
      return;
    }
    submit(plan.commands as Command[], "按标记分割");
    toast("info", `在 ${plan.splits} 个标记处分割`,
      plan.unused.length ? `${plan.unused.length} 个标记在边缘或空隙上，未产生命令。` : "切点就是标记本身的那一帧，误差不会超过一帧。");
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
  } finally {
    set({ busy: "" });
  }
}

/** 划动源画面：片段留在原地、时长不变，只换它播素材的哪一段。 */
export function slipClip(clipId: string, frames: number) {
  const project = state.project;
  if (!project || !frames) return;
  submit(
    [{ op: "clip.slip", clip_id: clipId, source_offset_ticks: frames * frameTicks(project.settings.frame_rate) }],
    `划动源画面 ${frames > 0 ? "后" : "前"} ${Math.abs(frames)} 帧`,
  );
}

/** 左右滑移：本段平移，一侧相邻段让出同样的帧数、另一侧收回，整条轨总长不变。 */
export function slideClip(clipId: string, frames: number) {
  const project = state.project;
  if (!project || !frames) return;
  submit(
    [{ op: "clip.slide", clip_id: clipId, delta_ticks: frames * frameTicks(project.settings.frame_rate) }],
    `滑移片段 ${frames > 0 ? "右" : "左"} ${Math.abs(frames)} 帧`,
  );
}

/** 整轨去空白：一次扫描这条轨上的每个片段并合并成一条事务。只有本轨内容会移动。 */
export async function cutTrackSilence(trackId: string) {
  const project = state.project;
  if (!engine || !project) return;
  set({ busy: "扫描整轨静音…" });
  try {
    const scanned = await engine.silenceTrack(project.id, trackId, {
      request_id: newId("silence-"), expected_revision: project.revision, trim_edges: true,
    });
    const commands = scanned.silence.commands;
    const skipped = scanned.silence.clips.filter((item) => item.skipped).length;
    if (!commands.length) {
      toast("info", "这条轨没有可剪的停顿", skipped
        ? `${skipped} 个片段被跳过：没有声音、带变速曲线或已经链接到别的片段。`
        : "整条轨里没有足够长的静音。");
      return;
    }
    submit(commands as Command[], "整轨去掉静音空白");
    toast("info", `去掉 ${countCuts(commands)} 处停顿，共 ${(scanned.silence.removed_ticks / TIMEBASE).toFixed(2)} 秒`,
      skipped
        ? `只移动本轨内容，${skipped} 个不能扫的片段已跳过并保持原位。`
        : "只移动本轨内容，其它轨道保持原位。");
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
  } finally {
    set({ busy: "" });
  }
}

/** 自动闪避：这条轨在别的声音轨说话时自动让路。写的是普通音量关键帧，所以预览与导出走同一条曲线。 */
export async function duckTrack(trackId: string, depthDb = 9) {
  const project = state.project;
  if (!engine || !project) return;
  set({ busy: "扫描说话区间…" });
  try {
    const scanned = await engine.duckTrack(project.id, trackId, {
      request_id: newId("duck-"), expected_revision: project.revision, depth_db: depthDb,
    });
    const plan = scanned.duck;
    const skipped = plan.clips.filter((item) => item.skipped).length + plan.skipped.length;
    if (!plan.commands.length) {
      toast("info", "这条轨不需要闪避", plan.speech.length
        ? `${skipped} 个片段不能写音量关键帧：没有声音、带变速曲线或已链接到别的片段。`
        : "其它声音轨整程都是安静的，配乐可以一直放着。");
      return;
    }
    submit(plan.commands as Command[], "自动闪避配乐");
    const seconds = plan.clips.reduce((sum, item) => sum + (item.ducked_ticks ?? 0), 0) / TIMEBASE;
    const replaced = plan.clips.reduce((sum, item) => sum + (item.replaced_gain_keyframes ?? 0), 0);
    toast("info", `${seconds.toFixed(2)} 秒里配乐降到 ${(plan.gain * 100).toFixed(0)}%`,
      `${plan.speech.length} 段说话、${plan.commands.length} 段配乐写入音量曲线`
      + (replaced ? `，替换掉 ${replaced} 个原有的音量关键帧` : "")
      + `。深度 ${plan.depth_db} dB，说话结束后用 ${(plan.release_ticks / TIMEBASE).toFixed(1)} 秒抬回来；`
      + "撤销一次全部还原。");
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
  } finally {
    set({ busy: "" });
  }
}

export async function refreshProxyUsage() {
  if (!engine) return;
  try {
    const usage = await engine.proxyInventory();
    set({ proxyUsage: { used_bytes: usage.used_bytes, limit_bytes: usage.limit_bytes, count: usage.proxies.length } });
  } catch {
    /* 媒体服务未就绪时不显示占用，界面其余部分照常 */
  }
  try {
    const cache = await engine.cacheInventory();
    set({ cacheUsage: { used_bytes: cache.used_bytes, limit_bytes: cache.limit_bytes, count: cache.entries.length } });
  } catch {
    /* 同上：占用是附加信息，拿不到就不显示 */
  }
}

/** 清空整个派生缓存（缩略图、波形、代理）。原片与工程不动，被删的派生文件下次用到时会自动重建。 */
export async function clearDerivedCache() {
  if (!engine) return;
  set({ busy: "清理派生缓存…" });
  try {
    const result = await engine.cachePrune({ max_bytes: 0 });
    set({ proxyActive: {}, proxyWidth: 0, proxyStatus: { label: "", done: 0, total: 0 } });
    applyPlaybackUrls();
    try { localStorage.setItem("agentcut.proxyWidth", "0"); } catch { /* 偏好仍可当场生效 */ }
    toast(
      "ok",
      "派生缓存已清空",
      `释放 ${(result.freed_bytes / 1048576).toFixed(1)} MB（${result.removed.length} 项缩略图 / 波形 / 代理）。` +
        "原片与工程未改动，下次用到时会重新生成。"
    );
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
  } finally {
    set({ busy: "" });
    void refreshProxyUsage();
  }
}

export async function clearProxyCache() {
  if (!engine) return;
  set({ busy: "清理代理缓存…" });
  try {
    const result = await engine.proxyPrune(0);
    set({ proxyActive: {}, proxyWidth: 0, proxyStatus: { label: "", done: 0, total: 0 } });
    applyPlaybackUrls();
    try { localStorage.setItem("agentcut.proxyWidth", "0"); } catch { /* 偏好仍可当场生效 */ }
    toast("info", "代理缓存已清理", `释放 ${(result.freed_bytes / 1048576).toFixed(1)} MB 派生副本；原片、缩略图与工程都未改动。`);
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
  } finally {
    set({ busy: "" });
    void refreshProxyUsage();
  }
}

export async function createProject(name: string, settings: Partial<Project["settings"]>) {
  if (!engine) return null;
  if (state.busy) return null; // 双击不产生两个同名工程
  if (state.batch.length) { toast("warn", "先处理当前待提交批次", "提交或放弃批次后，再创建工程。"); return null; }
  set({ busy: "创建项目…" });
  try {
    const created = await engine.create(name, settings);
    const project = created.project;
    const videoId = "v1";
    const audioId = "a1";
    const committed = await engine.edit(project.id, project.revision, [
      trackAdd({ id: videoId, kind: "video", name: "主画面" }),
      trackAdd({ id: audioId, kind: "audio", name: "声音" }),
    ]);
    showProject(committed.project);
    await refreshProjects();
    toast("ok", `已创建《${name}》`, "两条轨道已备好：主画面放视频/图片，声音放音频。");
    return committed.project;
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
    return null;
  } finally {
    set({ busy: "" });
  }
}

/** Export a project as one portable bundle: manifest plus every referenced media file. */
export async function exportBundle(projectId: string, name: string) {
  if (!engine || state.busy) return;
  set({ busy: "打包工程…" });
  try {
    const blob = await engine.bundle(projectId);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${name}.agentcut.zip`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30_000);
    toast("ok", `已导出《${name}》`, "工程与素材都在这个 .agentcut.zip 里，发给同事即可继续剪。");
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
  } finally {
    set({ busy: "" });
  }
}

export async function importBundle(file: File) {
  if (state.busy) return;
  pendingBundle = { file, requestId: newId("bundle-") };
  await retryBundle();
}

export async function retryBundle() {
  const pending = pendingBundle;
  if (!pending) return;
  if (!engine || state.busy) return;
  set({ busy: "导入工程包…", bundleRetry: "" });
  try {
    const project = await engine.importBundle(pending.file, pending.requestId);
    await refreshProjects();
    showProject(await engine.project(project.id));
    pendingBundle = null;
    toast("ok", `已导入《${project.name}》`, "素材已复制进本机素材库并重新探测。");
  } catch (error) {
    if (error instanceof EngineError && error.status >= 400 && error.status < 500) pendingBundle = null;
    set({ bundleRetry: pendingBundle ? pending.file.name : "" });
    const { title, detail } = describe(error);
    toast("error", title, detail);
  } finally {
    set({ busy: "" });
  }
}

export async function loadHistory() {
  if (!engine || !state.project) return;
  try {
    const result = await engine.history(state.project.id);
    set({ history: result.history });
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
  }
}

export function selectionFor(ids: string[], bypass = false, linksOnly = false) {
  return state.project && edit.linkedSelection && !bypass ? relatedClips(state.project, ids, linksOnly) : ids;
}

export function selectClip(clipId: string | null, additive = false, bypass = false) {
  const ids = clipId ? selectionFor([clipId], bypass) : [];
  const selectedClips = additive && clipId ? state.selectedClips.includes(clipId) ? state.selectedClips.filter((id) => !ids.includes(id)) : [...state.selectedClips, ...ids] : ids;
  selectClips(selectedClips, true);
}

export function selectClips(ids: string[], bypass = false) {
  set({ selectedClips: [...new Set(selectionFor(ids, bypass))], monitorMode: "timeline", sourcePlaying: false });
}

export function groupSelection(clear = false) {
  if (!state.selectedClips.length) return;
  submit([{ op: "clips.group", clip_ids: state.selectedClips, group_id: clear ? null : newId("g-") }], clear ? "取消组合" : "组合片段");
}

export function nestSelection(name: string) {
  if (!state.selectedClips.length || !name.trim()) return;
  const id = newId("seq-"); const clipId = newId("c-");
  submit([{ op: "sequence.nest", clip_ids: [...state.selectedClips], sequence_id: id, asset_id: newId("a-"), clip_id: clipId, name: name.trim() }], "预合成", { selectAfter: [clipId] });
}

export function openSequence(id: string | null) {
  if (!state.rootProject || state.busy || pendingEdits.length) return;
  if (state.batch.length) { toast("warn", "先处理当前待提交批次", "提交或放弃批次后，再进入另一条时间线。"); return; }
  if (id && !state.rootProject.sequences?.[id]) return;
  const previous = state.sequencePath.indexOf(id ?? "");
  const path = id ? previous < 0 ? [...state.sequencePath, id] : state.sequencePath.slice(0, previous + 1) : [];
  playhead.pause(); playhead.set(0);
  // Switching the read projection is not a project mutation; history remains global.
  state = { ...state, sequenceId: id, sequencePath: path, project: sequenceView(state.rootProject, id), candidate: null, rootCandidate: null, selectedClip: null, selectedClips: [], selectedAsset: null, targetTrack: null, sourcePlaying: false, monitorMode: "timeline", graphOpen: false, maskEditing: false };
  listeners.forEach((fn) => fn());
}

export function updateSequence(patch: { name?: string; duration_ticks?: number }) {
  if (!state.sequenceId) return;
  submit([{ op: "sequence.update", sequence_id: state.sequenceId, ...patch }], "修改合成设置");
}

export function linkSelection(clear = false) {
  if (!state.selectedClips.length) return;
  submit([{ op: "clips.link", clip_ids: state.selectedClips, link_id: clear ? null : newId("l-") }], clear ? "解除音画链接" : "链接音画");
}

export function selectAllClips() { selectClips(Object.keys(state.project?.clips ?? {})); }

export function selectAsset(assetId: string | null) {
  const sequenceId = assetId ? state.project?.assets[assetId]?.sequence_id : null;
  if (sequenceId) { openSequence(sequenceId); return; }
  if (assetId && state.project?.assets[assetId]?.kind === "text") { selectClip(Object.values(state.project.clips).find((c) => c.asset_id === assetId)?.id ?? null); return; }
  playhead.pause();
  set({ selectedAsset: assetId, selectedClip: null, monitorMode: assetId ? "source" : "timeline", sourcePlaying: false,
    ...(assetId === state.selectedAsset ? {} : { sourceCursorTicks: 0 }) });
}

function markedRange(project: Project, kind: Asset["kind"], key: string, duration: number) {
  const q = quantum(project, kind === "audio" ? "audio" : "video");
  const end = Math.floor(duration / q) * q;
  const marks = kind === "image" || kind === "text" ? {} : state.sourceMarks[key] ?? {};
  const start = Math.floor(Math.min(marks.in_ticks ?? 0, Math.max(0, end - q)) / q) * q;
  const stop = Math.floor(Math.min(end, Math.max(start + q, marks.out_ticks ?? end)) / q) * q;
  return { q, end, start, stop };
}

export function selectedSource() {
  if (!state.project) return null;
  const asset = state.project?.assets[state.selectedAsset ?? ""];
  const item = state.library.find((row) => row.probe.id === state.selectedAsset);
  const media = asset?.verified ?? item?.probe.verified;
  if (!asset && !item) return null;
  const kind = asset?.kind ?? media!.kind;
  if (kind === "text") return null;
  const duration = kind === "image" ? ticks(5) : asset?.duration_ticks ?? media?.duration_ticks ?? 0;
  const key = media?.content_sha256 ?? asset!.id;
  const range = markedRange(state.project, kind, key, duration);
  const tracks = state.project?.tracks.filter((t) => t.kind === (kind === "audio" ? "audio" : "video")) ?? [];
  const target = tracks.find((t) => t.id === state.targetTrack) ?? tracks.find((t) => !t.locked) ?? tracks[0];
  return { asset, item, kind, key, ...range, tracks, target, label: asset?.label ?? media!.label };
}

export function setMonitorMode(monitorMode: AppState["monitorMode"]) {
  playhead.pause(); set({ monitorMode, sourcePlaying: false });
}
export function setSourceCursor(value: number) {
  const source = selectedSource(); if (!source) return;
  set({ sourceCursorTicks: Math.min(Math.max(0, source.end - source.q), Math.max(0, Math.round(value / source.q) * source.q)) });
}
export function setSourcePlaying(sourcePlaying: boolean) {
  const source = selectedSource();
  if (sourcePlaying && (!source || source.kind === "image" || !source.end)) return;
  set({ sourcePlaying, ...(sourcePlaying && source && state.sourceCursorTicks >= source.end - source.q ? { sourceCursorTicks: 0 } : {}) });
}
export function setSourceTarget(targetTrack: string) { set({ targetTrack }); }
export function setSourceRipple(sourceRippleAll: boolean) { set({ sourceRippleAll }); }
/** 时间线入出点：区间导出与四点剪辑共用的一对整数刻度。写入只走工程设置这一条命令。 */
export async function setSequenceMark(side: "in" | "out", atTicks: number) {
  const project = editableProject(state);
  if (!project) return false;
  const settings = project.settings;
  const frame = frameTicks(settings.frame_rate);
  const end = Math.max(0, ...Object.values(project.clips).map((clip) => clip.position_ticks + clip.duration_ticks));
  if (!end) { toast("warn", "时间线还是空的", "先把素材放上轨道，再设入出点。"); return false; }
  const horizon = Math.ceil(end / frame) * frame;
  const snapped = Math.max(0, Math.min(Math.floor(atTicks / frame) * frame, horizon - frame));
  const inTicks = side === "in" ? snapped : settings.in_ticks ?? 0;
  const outTicks = side === "out" ? snapped + frame : settings.out_ticks ?? Math.max(inTicks + frame, snapped + frame);
  if (inTicks >= outTicks) {
    toast("warn", side === "in" ? "入点必须早于出点" : "出点必须晚于入点",
      `这样会是 ${(inTicks / TIMEBASE).toFixed(2)} – ${(outTicks / TIMEBASE).toFixed(2)} 秒；把播放头移到区间之外再按 ${side === "in" ? "I" : "O"}。`);
    return false;
  }
  await updateProjectMeta({ settings: { ...settings, in_ticks: inTicks, out_ticks: outTicks } });
  return true;
}

/** 四点剪辑：素材入出点 + 时间线入出点，一次放置。裁尾还是改速由引擎判定并如实回传，界面不猜。 */
export async function fourPoint(mode: "insert" | "overwrite") {
  const project = state.project;
  const source = selectedSource();
  if (!engine || !project || !source?.target) { toast("warn", "请选择素材和目标轨道", "先在素材库选中一段，再在右侧选一条目标轨。"); return; }
  if (source.target.locked) { toast("warn", "目标轨道已锁定", "解锁后再放，或换一条轨道。"); return; }
  if (source.kind === "image" || source.stop <= source.start) { toast("warn", "素材区间不足一帧"); return; }
  const existing = source.asset
    ?? Object.values(project.assets).find((asset) => asset.verified?.path === source.item?.probe.verified.path);
  if (!existing) { toast("warn", "这份素材还没有登记进工程", "先点「上轨」或把它拖进时间线，引擎需要一条已验证的素材记录。"); return; }
  const marks = project.settings;
  if (marks.in_ticks == null || marks.out_ticks == null) {
    toast("warn", "时间线还没有入出点", "切到「时间线预览」，把播放头放到起点按 I、终点按 O，再回来点这一颗。");
    return;
  }
  set({ busy: "四点剪辑…" });
  try {
    const planned = await engine.fourPoint(project.id, {
      request_id: newId("fourpoint-"), expected_revision: project.revision,
      asset_id: existing.id, track_id: source.target.id,
      source_in_ticks: source.start, source_out_ticks: source.stop,
      dest_in_ticks: marks.in_ticks, dest_out_ticks: marks.out_ticks,
      fit: "auto", mode, apply: false, dry_run: false,
    });
    const notes = planned.four_point;
    const read = (Number(notes.consumed_source_ticks) / TIMEBASE).toFixed(2);
    const window = (Number(notes.destination_ticks) / TIMEBASE).toFixed(2);
    submit(planned.commands as Command[], `四点${mode === "insert" ? "插入" : "覆盖"}`);
    const how = notes.resolution === "trimmed" ? `素材更长，裁掉尾部只读前 ${read} 秒`
      : notes.resolution === "re-timed" ? `素材更短，按 ${notes.speed_percent}% 变速铺满 ${window} 秒`
      : `刚好铺满 ${window} 秒`;
    toast("info", `四点${mode === "insert" ? "插入" : "覆盖"} · ${how}`,
      `写入时间线 ${(Number(notes.destination_ticks) / TIMEBASE).toFixed(2)} 秒，读素材 ${read} 秒；四个点都落在整帧上，撤销一步回到放置前。`);
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
  } finally {
    set({ busy: "" });
  }
}

export function markSequence(point: "in" | "out" | "clear") {
  const project = editableProject(state);
  if (!project) return;
  if (point === "clear") {
    if (project.settings.in_ticks == null && project.settings.out_ticks == null) {
      toast("info", "当前没有入出点区间");
      return;
    }
    void updateProjectMeta({ settings: { ...project.settings, in_ticks: null, out_ticks: null } });
    return;
  }
  void setSequenceMark(point, playhead.value);
}

export function markSource(point: "in" | "out" | "clear") {
  const source = selectedSource(); if (!source || source.kind === "image" || source.end < source.q) return;
  if (point === "clear") { const marks = { ...state.sourceMarks }; delete marks[source.key]; set({ sourceMarks: marks }); return; }
  const cursor = Math.min(source.end - source.q, Math.max(0, Math.floor(state.sourceCursorTicks / source.q) * source.q));
  const marks = { ...(state.sourceMarks[source.key] ?? {}) };
  if (point === "in") { marks.in_ticks = cursor; if ((marks.out_ticks ?? source.end) <= cursor) delete marks.out_ticks; }
  else { marks.out_ticks = cursor + source.q; if ((marks.in_ticks ?? 0) >= marks.out_ticks) delete marks.in_ticks; }
  set({ sourceMarks: { ...state.sourceMarks, [source.key]: marks } });
}

export function editSource(mode: "insert" | "overwrite") {
  const project = state.project, source = selectedSource();
  if (!project || !source?.target || source.end < source.q) { toast("warn", "请选择可用素材和目标轨道"); return; }
  if (source.target.locked) { toast("warn", "目标轨道已锁定", "请解锁或选择其他轨道。"); return; }
  const existing = source.asset ?? Object.values(project.assets).find((a) => a.verified?.path === source.item?.probe.verified.path);
  const assetId = existing?.id ?? newId("a-");
  const commands: Command[] = existing ? [] : [assetImport(source.item!.probe, assetId, source.label)];
  const clip: Clip = { id: newId("c-"), asset_id: assetId, track_id: source.target.id,
    position_ticks: snapTo(project, source.target.kind, playhead.value), source_in_ticks: source.kind === "image" ? 0 : source.start,
    duration_ticks: source.stop - source.start };
  commands.push({ op: `clip.${mode}`, clip, ...(mode === "insert" && state.sourceRippleAll ? { ripple_track_ids: project.tracks.filter((t) => !t.locked).map((t) => t.id) } : {}) });
  submit(commands, `${mode === "insert" ? "插入" : "覆盖"}「${source.label}」`);
  setSourcePlaying(false);
}

/* ---------------------------------------------------------------- 命令通道 */

/**
 * 界面唯一的写入口：要么立刻提交（instant），要么进待提交批次（batch）。
 * 两种模式都走同一条 HTTP 批命令，和外部 Agent 完全一致。
 *
 * 即时提交在一条 promise 链上串行执行：键盘连按 / 拖拽松手不会带着过期
 * revision 并发提交，也永远不会覆盖同一时段内新加入的批次命令。
 */
let editChain: Promise<void> = Promise.resolve();

function submit(commands: Command[], label: string, opts?: { quiet?: boolean; selectAfter?: string[]; revision?: number }) {
  if (!engine || !state.project) return;
  if (opts?.revision !== undefined && opts.revision !== state.project.revision) {
    toast("warn", "工程已变化，关键帧未修改", "重新选择关键帧后再编辑。"); return;
  }
  if (state.mode === "batch") {
    if (state.batch.length && state.batchSequenceId !== state.sequenceId) { toast("warn", "原合成的批次仍待处理", "先放弃这个批次，再编辑当前时间线。"); return; }
    if (!state.batch.length) set({ batchSequenceId: state.sequenceId });
    set({ batch: [...state.batch, ...commands], dryRunError: "" });
    scheduleDryRun();
    if (!opts?.quiet) {
      toast("info", `已加入待提交批次：${label}`, "点“预演”检查冲突，点“提交”才会写入。");
    }
    return;
  }
  // 连续的同类微调（按住 Alt+方向键）只保留最后一条，避免链上堆积几十次往返。
  const last = pendingEdits[pendingEdits.length - 1];
  if (last && commands.length === 1 && last.commands.length === 1 && commands[0].op === "clips.move" && last.commands[0].op === "clips.move" && last.projectId === state.project.id && JSON.stringify(commands[0].clip_ids) === JSON.stringify(last.commands[0].clip_ids) && JSON.stringify(commands[0].track_map) === JSON.stringify(last.commands[0].track_map)) {
    last.commands[0].delta_ticks = Number(last.commands[0].delta_ticks) + Number(commands[0].delta_ticks);
    return;
  }
  if (
    last &&
    commands.length === 1 &&
    last.commands.length === 1 &&
    commands[0].op === "clip.move" &&
    last.commands[0].op === "clip.move" &&
    commands[0].clip_id === last.commands[0].clip_id
    && last.projectId === state.project.id
  ) {
    last.commands = commands;
    last.label = label;
    return;
  }
  pendingEdits.push({ commands, label, quiet: Boolean(opts?.quiet), projectId: state.project.id, sequenceId: state.sequenceId, selectAfter: opts?.selectAfter, revision: opts?.revision });
  editChain = editChain.then(runPendingEdits).catch(() => {});
}

let pendingEdits: { commands: Command[]; label: string; quiet: boolean; projectId: string; sequenceId: string | null; selectAfter?: string[]; revision?: number }[] = [];

async function runPendingEdits() {
  while (pendingEdits.length) {
    const job = pendingEdits.shift()!;
    if (job.revision !== undefined && state.project?.revision !== job.revision) {
      toast("warn", "工程已变化，关键帧未修改", "重新选择关键帧后再编辑。"); continue;
    }
    if (state.project?.id === job.projectId && state.sequenceId === job.sequenceId) await doSubmit(job.commands, job.label, job.quiet, job.selectAfter);
  }
}

async function doSubmit(commands: Command[], label: string, quiet: boolean, selectAfter?: string[]) {
  if (!engine || !state.project) return;
  const project = state.project;
  const previous = project.revision;
  set({ busy: label });
  try {
    const result = await engine.edit(project.id, previous, commands, false, state.sequenceId);
    if (state.project?.id !== project.id) return;
    pushUndo(previous, label);
    applyMutation(result, label, quiet, selectAfter);
  } catch (error) {
    if (error instanceof EngineError && error.code === "REVISION_CONFLICT") {
      await recoverConflict(error);
    } else {
      const { title, detail } = describe(error);
      toast("error", `${title} · ${label}`, detail);
    }
  } finally {
    set({ busy: "" });
  }
}

function applyMutation(result: MutationResult, label: string, quiet = false, selectAfter?: string[]) {
  set({
    project: result.project,
    selectedClips: selectAfter ?? state.selectedClips,
  });
  void loadStreams(result.project.id);
  void refreshProjects();
  if (!quiet) toast("ok", `${label} · r${result.project.revision}`, "已原子写入，历史可回滚。");
}

function pushUndo(revision: number, label: string) {
  set({ undo: [...state.undo, { revision, label }], redo: [] });
}

async function recoverConflict(error: EngineError) {
  toast("warn", error.explain(), "Agent 或别的窗口刚刚改过时间线。");
  if (!engine || !state.project) return;
  try {
    set({ project: await engine.project(state.project.id) });
  } catch {
    /* 刷新失败时保留旧视图，用户可手动重试 */
  }
}

function scheduleDryRun() {
  if (dryRunTimer) window.clearTimeout(dryRunTimer);
  dryRunVersion += 1;
  set({ dryRunBusy: Boolean(state.batch.length) });
  dryRunTimer = window.setTimeout(() => void runDryRun(), 260);
}

export async function runDryRun() {
  if (dryRunTimer) window.clearTimeout(dryRunTimer);
  const version = ++dryRunVersion;
  if (!engine || !state.project || !state.batch.length) {
    set({ candidate: null, dryRunError: "", dryRunBusy: false });
    return;
  }
  if (state.batchSequenceId !== state.sequenceId) {
    set({ candidate: null, dryRunError: "这个批次属于已离开的合成，未保存。恢复该合成后重试，或放弃批次。", dryRunBusy: false });
    return;
  }
  set({ dryRunBusy: true });
  const project = state.project; const submitted = state.batch;
  try {
    // 预演必须用新的 request_id：同一个 id 已经提交过会被拒绝。
    const result = await engine.edit(project.id, project.revision, submitted, true, state.batchSequenceId);
    if (version === dryRunVersion && state.project?.id === project.id && state.project.revision === project.revision && state.batch === submitted) set({ candidate: result.project, dryRunError: "" });
  } catch (error) {
    if (version === dryRunVersion && state.project?.id === project.id && state.project.revision === project.revision && state.batch === submitted) set({ candidate: null, dryRunError: describe(error).detail || String(error) });
  } finally {
    if (version === dryRunVersion) set({ dryRunBusy: false });
  }
}

export async function commitBatch() {
  if (!engine || !state.project || !state.batch.length) return;
  const previous = state.project.revision;
  const submitted = state.batch;
  set({ busy: `提交 ${submitted.length} 条命令…` });
  try {
    const result = await engine.edit(state.project.id, previous, submitted, false, state.batchSequenceId);
    pushUndo(previous, `批次 ${submitted.length} 条命令`);
    // 只清掉这次提交的命令：提交期间新加入批次的操作必须保留。
    set({ batch: state.batch.slice(submitted.length), dryRunError: "" });
    applyMutation(result, `已提交 ${submitted.length} 条命令`);
  } catch (error) {
    if (error instanceof EngineError && error.code === "REVISION_CONFLICT") {
      // 批次内容本身没坏：刷新工程，保留批次让人重试。
      await recoverConflict(error);
      toast("warn", "批次未提交", "时间线已更新到最新版本，点「预演」检查后可再次提交。");
    } else {
      const { title, detail } = describe(error);
      toast("error", title, detail);
    }
  } finally {
    set({ busy: "" });
    if (state.batch.length) scheduleDryRun();
  }
}

export function clearBatch() {
  dryRunVersion += 1;
  if (dryRunTimer) window.clearTimeout(dryRunTimer);
  set({ batch: [], candidate: null, dryRunError: "", dryRunBusy: false });
}

export function setMode(mode: AppState["mode"]) {
  if (mode === state.mode) return;
  if (mode === "instant" && state.batch.length) {
    toast("info", "待提交批次已保留", "切回“批次”模式可以继续预演和提交。");
  }
  set({ mode });
}

export function removeBatchItem(index: number) {
  set({ batch: state.batch.filter((_, i) => i !== index), dryRunError: "" });
  scheduleDryRun();
}

/* ---------------------------------------------------------------- 具体编辑 */

export function addTrack(kind: Track["kind"]) {
  const project = state.project;
  const count = (project?.tracks ?? []).filter((item) => item.kind === kind).length + 1;
  const name = kind === "video" ? `画面 ${count}` : `声音 ${count}`;
  const id = newId(kind === "video" ? "v-" : "a-");
  void submit([trackAdd({ id, kind, name })], `添加${kind === "video" ? "画面" : "音频"}轨道`);
}

export function updateTrack(trackId: string, patch: Partial<Omit<Track, "id" | "kind">>, label: string) {
  void submit([trackUpdate(trackId, patch)], label);
}

export function removeTrack(trackId: string) {
  void submit([trackRemove(trackId)], "删除轨道");
}

export function removeClip(clipId: string) {
  void submit([clipRemove(clipId)], "移除片段");
}

/** 涟漪删除：去掉这段，并把它后面的片段整体左移，不留空隙。 */
export function removeClipRipple(clipId: string) {
  submit([{ op: "clip.ripple_remove", clip_id: clipId }], "涟漪删除", { quiet: true });
}

export function setClipEffects(clipId: string, patch: Partial<Effects>) {
  submit([{ op: "clip.patch", clip_id: clipId, effects: patch }], "调整片段属性", { quiet: true });
}

export function setClipSpeed(clipId: string, speed: number) {
  submit([{ op: "clip.speed", clip_id: clipId, speed_percent: Math.round(speed * 100), ripple: true }], "调整速度", { quiet: true });
}

export function setClipColor(clipId: string, patch: Partial<ClipColor>) {
  submit([{ op: "clip.patch", clip_id: clipId, color: patch }], "调整画面色彩", { quiet: true });
}

export function setClipText(clipId: string, patch: Partial<TextStyle>) {
  submit([{ op: "clip.patch", clip_id: clipId, text: patch }], "编辑文字", { quiet: true });
}

export function fadeClip(clipId: string, property: "opacity" | "gain", duration: number, mode: "in" | "out" | "both") {
  submit([{ op: "clip.fade", clip_id: clipId, property, duration_ticks: ticks(duration), mode }], "设置淡入淡出", { quiet: true });
}

export function importCaptions(srt: string) {
  submit([{ op: "captions.import", track_id: newId("sub-"), asset_id: newId("text-"), srt, offset_ticks: 0 }], "导入字幕");
}

export function addTextClip() {
  const project = state.project; if (!project) return;
  const trackId = newId("v-"); const assetId = newId("text-"); const clipId = newId("c-");
  const clip: Clip = { id: clipId, track_id: trackId, asset_id: assetId, position_ticks: snapTo(project, "video", playhead.value), source_in_ticks: 0, duration_ticks: ticks(3), text: { body: "输入标题或字幕", font_size: .06, color: "#FFFFFF" }, effects: { x: 0, y: .35, scale: 1, rotation: 0, opacity: 1, gain: 1 } };
  submit([trackAdd({ id: trackId, kind: "video", name: "文字" }), { op: "asset.register", asset: { id: assetId, kind: "text", label: "文字", reference: "generated:text" } }, clipAdd(clip)], "添加文字");
  set({ selectedClip: clipId, selectedAsset: null });
}

export function setKeyframe(clipId: string, keyframe: Keyframe) {
  submit([{ op: "keyframe.set", clip_id: clipId, keyframe }], "设置关键帧", { quiet: true });
}

export function removeKeyframe(clipId: string, property: Property, at: number) {
  submit([{ op: "keyframe.remove", clip_id: clipId, property, at_ticks: at }], "删除关键帧", { quiet: true });
}

export function editAtRevision(commands: Command[], projectId: string, revision: number, label = "编辑动画曲线", sequenceId = state.sequenceId) {
  if (state.project?.id !== projectId || state.sequenceId !== sequenceId) return;
  submit(commands, label, { quiet: true, revision });
}

export function setClipMask(clipId: string, mask: ShapeMask | null, projectId = state.project?.id, revision = state.project?.revision) {
  if (projectId === undefined || revision === undefined) return;
  editAtRevision([{ op: "clip.mask", clip_id: clipId, mask }], projectId, revision, "调整遮罩");
}

/**
 * 整条路径拖到新位置：已经打了中心曲线的遮罩，把这次搬动记成**当前时刻**的关键帧（AE 里拖动控制点
 * 就是这个语义——动画留在轨迹上，只是这一帧换了位置）；没有曲线的直接搬轮廓。
 */
export function moveMaskCentre(clipId: string, atTicks: number, centre: { x: number; y: number }, projectId = state.project?.id, revision = state.project?.revision) {
  if (projectId === undefined || revision === undefined) return;
  const clamp = (value: number) => Math.min(1, Math.max(0, value));
  const commands: Command[] = (["mask_x", "mask_y"] as const).map((property, index) => ({
    op: "keyframe.set", clip_id: clipId, keyframe: {
      property, at_ticks: atTicks, value: clamp(index === 0 ? centre.x : centre.y), interpolation: "linear",
    },
  }));
  editAtRevision(commands, projectId, revision, "搬动遮罩到此刻");
}

const MASK_BOX_FIELDS: [Property, "center_x" | "center_y" | "width" | "height"][] = [
  ["mask_x", "center_x"], ["mask_y", "center_y"], ["mask_width", "width"], ["mask_height", "height"],
];

/**
 * 画面上拖遮罩的落笔处：已经打了关键帧的属性写**当前时间**的关键帧，没打关键帧的属性写遮罩本身。
 * 一笔提交，所以一次拖动只产生一个 revision；否则拖动画好的框在曲线上毫无痕迹（看着像控件坏了）。
 *
 * 拖动中向导与预览都停在基准几何上（草稿是引擎按原样栅格化的），所以本地坐标就是该写进关键帧的值。
 */
export function commitMaskEdit(clipId: string, mask: ShapeMask, atTicks: number, projectId = state.project?.id, revision = state.project?.revision) {
  const clip = projectId === undefined || revision === undefined ? undefined : state.project?.clips[clipId];
  if (!clip || projectId === undefined || revision === undefined) return;
  const before = clip.mask;
  const keyed = new Set((clip.keyframes ?? []).map((key) => key.property));
  const commands: Command[] = [];
  // 路径遮罩的 box 是从顶点算出来的派生量：拖一个顶点不该顺手把位置曲线钉在当前时刻，
  // 所以只有矩形/椭圆这种「框本身就是用户意图」的形状才把拖动写成关键帧。
  const box = Boolean(before && before.shape !== "path");
  if (before && box) {
    for (const [property, field] of MASK_BOX_FIELDS) {
      if (!keyed.has(property) || Math.abs(mask[field] - before[field]) < 1e-9) continue;
      const existing = (clip.keyframes ?? []).find((key) => key.property === property && key.at_ticks === atTicks);
      commands.push({ op: "keyframe.set", clip_id: clipId, keyframe: {
        property, at_ticks: atTicks, value: mask[field], interpolation: existing?.interpolation ?? "linear",
      } });
    }
  }
  commands.push({ op: "clip.mask", clip_id: clipId, mask });
  editAtRevision(commands, projectId, revision, commands.length > 1 ? "调整遮罩关键帧" : "调整遮罩");
}

export function setClipSpeedCurve(clipId: string, points: SpeedPoint[] | null, projectId = state.project?.id, revision = state.project?.revision) {
  if (projectId === undefined || revision === undefined) return;
  editAtRevision([{ op: "clip.speed_curve", clip_id: clipId, points }], projectId, revision, "调整曲线变速");
}

/** 复制一段到本轨末尾：做重复镜头、叠字幕时比重新拖一次快。 */
export function duplicateClip(clipId: string) {
  const project = state.project;
  const clip = project?.clips[clipId];
  if (!project || !clip) return;
  const end = Object.values(project.clips)
    .filter((item) => item.track_id === clip.track_id)
    .reduce((acc, item) => Math.max(acc, item.position_ticks + item.duration_ticks), 0);
  const copy: Clip = { ...clip, id: newId("c-"), position_ticks: end, transition_in: null, group_id: null, link_id: null, link_source_offset_ticks: 0 };
  void submit([clipAdd(copy)], "复制片段");
}

let clipClipboard: ClipClipboard | null = null;

export function copySelection() {
  if (!state.project || !state.selectedClips.length) return;
  clipClipboard = copyClips(state.project, state.selectedClips, state.sequenceId);
  set({ clipboardCount: clipClipboard.clips.length });
  toast("ok", `已复制 ${clipClipboard.clips.length} 个片段`, "移动播放头后粘贴；也可切换到其他工程。");
}

function placeCopied(copied: ClipClipboard, at: number, direction = 0) {
  const project = state.project; if (!project || !copied.clips.length) return;
  const plan = pasteCommands(project, copied, at, direction, state.sequenceId);
  if (plan.commands.length > 100) { toast("warn", "这一组的新素材与轨道过多", "先将素材导入目标工程，或分组粘贴。"); return; }
  submit(plan.commands, `粘贴 ${copied.clips.length} 个片段`, { selectAfter: plan.ids });
}

export function pasteSelection() { if (clipClipboard) placeCopied(clipClipboard, playhead.value); }

export function duplicateSelection() {
  const project = state.project; if (!project || !state.selectedClips.length) return;
  const copied = copyClips(project, state.selectedClips, state.sequenceId);
  const usedTracks = new Set(copied.clips.map((c) => c.track_id));
  const end = Math.max(0, ...Object.values(project.clips).filter((c) => usedTracks.has(c.track_id)).map((c) => c.position_ticks + c.duration_ticks));
  placeCopied(copied, end, 1);
}

export function removeSelection(ripple = false) {
  if (!state.selectedClips.length) return;
  submit([{ op: "clips.remove", clip_ids: state.selectedClips, ripple }], ripple ? "涟漪删除选中片段" : "删除选中片段");
}

export function moveSelection(ids: string[], delta: number, anchorId?: string, destination?: string) {
  const project = state.project; if (!project || !ids.length) return;
  const trackMap: Record<string, string> = {};
  if (anchorId && destination) {
    const rows = timelineTracks(project);
    const anchorTrack = project.clips[anchorId]?.track_id;
    const shift = rows.findIndex((t) => t.id === destination) - rows.findIndex((t) => t.id === anchorTrack);
    for (const id of ids) {
      const source = rows.findIndex((t) => t.id === project.clips[id]?.track_id);
      const target = rows[source + shift];
      if (!target || target.kind !== rows[source]?.kind) { toast("warn", "整组需要足够的同类轨道", "保持每段的相对轨道位置；可先增加轨道或水平移动。"); return; }
      trackMap[rows[source].id] = target.id;
    }
  }
  if (delta === 0 && Object.entries(trackMap).every(([from, to]) => from === to)) return;
  submit([{ op: "clips.move", clip_ids: ids, delta_ticks: delta, track_map: trackMap }], "移动选中片段", { quiet: true });
}

export function nudgeSelection(delta: number) {
  const project = state.project; if (!project || !state.selectedClips.length) return;
  const q = selectionQuantum(project, state.selectedClips);
  const min = Math.min(...state.selectedClips.map((id) => project.clips[id].position_ticks));
  const step = Math.max(-Math.floor(min / q) * q, Math.sign(delta) * Math.max(q, Math.round(Math.abs(delta) / q) * q));
  moveSelection(state.selectedClips, step);
}

export function splitSelection(at: number) {
  const project = state.project; if (!project) return;
  const ids = state.selectedClips.filter((id) => {
    const clip = project.clips[id]; const track = project.tracks.find((t) => t.id === clip?.track_id);
    return clip && track && at > clip.position_ticks && at < clip.position_ticks + clip.duration_ticks;
  });
  if (ids.length) submit([{ op: "clips.split", clip_ids: ids, at_ticks: Math.round(at), right_clip_ids: Object.fromEntries(ids.map((id) => [id, newId("c-")])) }], "分割选中片段");
}

export function setTransition(clipId: string, fromId: string, kind: TransitionKind, duration: number) {
  submit([{ op: "transition.set", clip_id: clipId, from_clip_id: fromId, kind, duration_ticks: ticks(duration) }], "设置镜头转场");
}

export function removeTransition(clipId: string) {
  submit([{ op: "transition.remove", clip_id: clipId }], "移除镜头转场");
}

export function splitClip(clipId: string, at: number, bypass = false) {
  const clip = state.project?.clips[clipId];
  if (!clip) return;
  const ids = selectionFor([clipId], bypass, true);
  const point = align(at, selectionQuantum(state.project!, ids), 0);
  if (point <= clip.position_ticks || point >= clip.position_ticks + clip.duration_ticks) {
    toast("warn", "切点必须在片段内部", "把播放头移到这段素材中间，再点击要分割的片段。");
    return;
  }
  void submit(ids.length > 1 ? [{ op: "clips.split", clip_ids: ids, at_ticks: point, right_clip_ids: Object.fromEntries(ids.map((id) => [id, newId("c-")])) }] : [clipSplit(clipId, point, newId("c-"))], "分割片段");
}

export function moveClip(clipId: string, trackId: string, position: number) {
  const project = state.project;
  if (!project) return;
  const track = project.tracks.find((item) => item.id === trackId);
  const clip = project.clips[clipId];
  if (!track || !clip) return;
  const snapped = snapTo(project, track.kind, position);
  if (clip.track_id === trackId && clip.position_ticks === snapped) return;
  submit([clipMove(clipId, trackId, snapped)], "移动片段", { quiet: true });
}

export function trimClip(clipId: string, sourceIn: number, duration: number, position?: number, bypass = false, ripple = false) {
  const project = state.project;
  if (!project) return;
  const clip = project.clips[clipId];
  const track = project.tracks.find((item) => item.id === clip?.track_id);
  if (!clip || !track) return;
  const q = selectionQuantum(project, selectionFor([clipId], bypass, true));
  submit([{ ...clipTrim(clipId, Math.max(0, Math.round(sourceIn)), align(duration, q, 0)),
    op: edit.linkedSelection && !bypass && clip.link_id ? "clip.trim_linked" : "clip.trim",
    ...(position === undefined ? {} : { position_ticks: align(position, q, 0) }),
    ...(ripple ? { ripple: true } : {}) }], "修剪片段", {
    quiet: true,
  });
}

export function rollClip(leftId: string, rightId: string, delta: number) {
  const project = state.project;
  if (!project || !project.clips[leftId] || !project.clips[rightId]) return;
  submit([{ op: "clip.roll", clip_id: leftId, other_clip_id: rightId, delta_ticks: Math.round(delta) }], "滚动剪辑", { quiet: true });
}

export function detachAudio(clipId: string) {
  const project = state.project;
  if (!project) return;
  const clip = project.clips[clipId];
  const audioTrack = project.tracks.find((t) => t.kind === "audio" && !t.locked);
  if (!clip || !audioTrack) { toast("warn", "需要有一个解锁的声音轨"); return; }
  void submit([{ op: "clip.detach_audio", clip_id: clipId, audio_clip_id: newId("c-"), track_id: audioTrack.id }], "拆分内嵌声音");
}

export function addClipToTrack(assetId: string, trackId: string, position: number) {
  const project = state.project;
  if (!project) return;
  const asset = project.assets[assetId];
  const track = project.tracks.find((item) => item.id === trackId);
  if (!asset || !track) return;
  const kind = track.kind;
  const range = markedRange(project, asset.kind, asset.verified?.content_sha256 ?? asset.id,
    asset.kind === "image" || asset.kind === "text" ? ticks(5) : asset.duration_ticks ?? 0);
  if (range.stop <= range.start) { toast("warn", "素材不足一帧或一个采样点"); return; }
  const snapped = snapTo(project, kind, position);
  const clip: Clip = {
    id: newId("c-"),
    asset_id: assetId,
    track_id: trackId,
    position_ticks: snapped,
    source_in_ticks: range.start,
    duration_ticks: range.stop - range.start,
    ...(asset.kind === "text" ? { text: Object.values(project.clips).find((c) => c.asset_id === assetId)?.text ?? { body: "输入文字", font_size: .06, color: "#FFFFFF" } } : {}),
  };
  void submit([clipAdd(clip)], `把「${asset.label}」放到${track.kind === "video" ? "画面" : "声音"}轨`);
}

/** 从素材库放到时间线末尾（点一下就能用，不需要精确拖拽）。 */
export function appendAsset(assetId: string) {
  const project = state.project;
  if (!project) return;
  const asset = project.assets[assetId];
  if (!asset) return;
  const wantVideo = asset.kind !== "audio";
  const track =
    project.tracks.find((item) => item.id === state.targetTrack && item.kind === (wantVideo ? "video" : "audio")) ??
    project.tracks.find((item) => !item.locked && item.kind === (wantVideo ? "video" : "audio")) ??
    project.tracks.find((item) => (wantVideo ? item.kind !== "audio" : item.kind === "audio"));
  if (!track) {
    toast("warn", "还没有可用轨道", "先点时间线工具栏的“＋ 画面轨”或“＋ 声音轨”。");
    return;
  }
  const end = Object.values(project.clips)
    .filter((clip) => clip.track_id === track.id)
    .reduce((acc, clip) => Math.max(acc, clip.position_ticks + clip.duration_ticks), 0);
  addClipToTrack(assetId, track.id, end);
}

/** 播放头跳到上一个/下一个片段边界（与走带按钮、帮助文档一致）。 */
export function jumpEditPoint(direction: number) {
  const project = state.project;
  if (!project) return;
  const edges = new Set<number>();
  for (const clip of Object.values(project.clips)) {
    edges.add(clip.position_ticks);
    edges.add(clip.position_ticks + clip.duration_ticks);
  }
  const points = [...edges].sort((a, b) => a - b);
  const current = playhead.value;
  const next =
    direction > 0
      ? points.find((item) => item > current + 1)
      : [...points].reverse().find((item) => item < current - 1);
  playhead.set(next ?? (direction > 0 ? timelineEnd(project) : 0));
}

/* ---------------------------------------------------------------- 素材库 */

export async function loadLibrary() {
  if (!engine || !(await mediaAvailable())) return;
  try {
    const listed = await engine.probes();
    const items: LibraryItem[] = [];
    const seen = new Set<string>(); // 同一文件多次导入只显示最新一张卡片
    for (const row of listed.probes.slice(0, 200)) {
      try {
        const probe = await engine.probe(row.id);
        const hash = probe.verified.content_sha256;
        if (hash && seen.has(hash)) continue;
        if (hash) seen.add(hash);
        items.push({ probe, path: row.path, added_at: row.created_at });
      } catch {
        /* 单条探测记录读取失败不影响其它素材 */
      }
    }
    set({ library: items });
  } catch {
    /* 媒体引擎未就绪时素材库保持空，界面会说明原因 */
  }
}

async function mediaAvailable() {
  const info = state.info;
  if (info?.media_ready) return true;
  if (state.caps?.features.media_probe) return true;
  return false;
}

export async function importFiles() {
  if (!engine) return;
  const picked = await bridge.openMedia();
  if (picked.cancelled) {
    if (picked.error) toast("warn", "无法导入", picked.error);
    else set({ busy: "" }); // 复制中途失败也会走 cancelled 分支，别把 busy 卡住
    return;
  }
  set({ busy: `正在探测 ${picked.copied?.length ?? 0} 个文件…` });
  let ok = 0;
  try {
    for (const item of picked.copied ?? []) {
      try {
        const probe = await engine.importMedia(item.to);
        set({ library: [{ probe, path: item.to, added_at: new Date().toISOString() }, ...state.library] });
        ok += 1;
      } catch (error) {
        const { title, detail } = describe(error);
        toast("error", `${title} · ${item.to.split(/[\\/]/).pop()}`, detail);
      }
    }
  } finally {
    set({ busy: "" });
  }
  if (ok) toast("ok", `已导入 ${ok} 个素材`, "缩略图与波形是真实解码结果，可直接拖上时间线。");
}

/** 素材登记为项目资产：verified 记录原样来自服务端探测，客户端不能伪造。 */
export async function ensureAsset(probe: Probe, label: string): Promise<string | null> {
  if (!engine || !state.project) return null;
  const existing = Object.values(state.project.assets).find((asset) => asset.verified?.path === probe.verified.path);
  if (existing) return existing.id;
  const assetId = newId("a-");
  const command = assetImport(probe, assetId, label);
  if (state.mode === "batch") {
    set({ batch: [...state.batch, command] });
    scheduleDryRun();
    toast("info", `「${label}」已进批次`, "提交后才会成为项目素材。");
    return assetId;
  }
  set({ busy: `登记素材「${label}」…` });
  try {
    const result = await engine.edit(state.project.id, state.project.revision, [command]);
    pushUndo(state.project.revision, `登记素材 ${label}`);
    set({ project: result.project });
    await refreshProjects();
    return assetId;
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
    return null;
  } finally {
    set({ busy: "" });
  }
}

export async function addLibraryItemToTimeline(item: LibraryItem, trackId?: string, position?: number) {
  const label = item.probe.verified.label;
  if (!state.project) return;
  const project = state.project;
  const wantVideo = item.probe.verified.kind !== "audio";
  const track =
    state.project.tracks.find((t) => t.id === trackId) ??
    state.project.tracks.find((t) => t.id === state.targetTrack && t.kind === (wantVideo ? "video" : "audio")) ??
    state.project.tracks.find((t) => !t.locked && t.kind === (wantVideo ? "video" : "audio")) ??
    state.project.tracks[0];
  if (!track) {
    toast("warn", "还没有轨道", "先点时间线工具栏的“＋ 画面轨”或“＋ 声音轨”。");
    return;
  }
  if ((track.kind === "video") !== wantVideo) {
    toast("warn", "音频不能放在画面轨", "把它拖到绿色的声音轨，或先新建一条声音轨。");
    return;
  }
  const end = Object.values(state.project.clips)
    .filter((clip) => clip.track_id === track.id)
    .reduce((acc, clip) => Math.max(acc, clip.position_ticks + clip.duration_ticks), 0);
  const existing = Object.values(project.assets).find((asset) => asset.verified?.path === item.probe.verified.path);
  const assetId = existing?.id ?? newId("a-");
  const duration = item.probe.verified.kind === "image" ? ticks(5) : item.probe.verified.duration_ticks;
  const range = markedRange(project, item.probe.verified.kind, item.probe.verified.content_sha256, duration);
  if (range.stop <= range.start) { toast("warn", "素材不足一帧或一个采样点"); return; }
  const clip: Clip = { id: newId("c-"), asset_id: assetId, track_id: track.id,
    position_ticks: snapTo(project, track.kind, position ?? end), source_in_ticks: range.start,
    duration_ticks: range.stop - range.start };
  submit([...(existing ? [] : [assetImport(item.probe, assetId, label)]), clipAdd(clip)], `添加「${label}」`, { quiet: true });
}

export function removeAsset(assetId: string) {
  const sequenceId = state.project?.assets[assetId]?.sequence_id;
  void submit([sequenceId ? { op: "sequence.remove", sequence_id: sequenceId } : { op: "asset.remove", asset_id: assetId }], sequenceId ? "移除合成" : "移除素材");
}

/* ---------------------------------------------------------------- 项目设置 */

/** 安全框：显示哪条参考线是工程状态（和入出点一样可撤销），数值取自引擎的 capabilities。 */
export function cycleSafeArea() {
  const project = state.project;
  if (!project) return;
  const order = ["off", "action", "title"] as const;
  const next = order[(order.indexOf(project.settings.safe_area ?? "off") + 1) % order.length];
  void updateProjectMeta({ settings: { ...project.settings, safe_area: next } });
}

export async function updateProjectMeta(patch: { name?: string; notes?: string; settings?: object }) {
  if (!engine || !state.project) return;
  set({ busy: "保存项目设置…" });
  try {
    const result = await engine.update(state.project.id, state.project.revision, patch);
    // 元数据写入产生新 revision，旧撤销栈指向的链路已失效，一并清空。
    set({ project: result.project, undo: [], redo: [] });
    await refreshProjects();
    toast("ok", "项目设置已保存", `当前 r${result.project.revision}。`);
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
  } finally {
    set({ busy: "" });
  }
}

/* ---------------------------------------------------------------- 历史与撤销 */

export async function restoreRevision(target: number) {
  if (!engine || !state.project) return;
  set({ busy: `恢复到 r${target}…` });
  try {
    const result = await engine.restore(state.project.id, state.project.revision, target);
    set({ project: result.project, candidate: null, view: "editor", undo: [], redo: [] });
    // 批次命令的语义在恢复后仍可能成立，重新预演而不是静默丢弃。
    if (state.batch.length) void runDryRun();
    await loadHistory();
    await refreshProjects();
    toast("ok", `已回到 r${target} 的内容`, `历史不倒退：新版本是 r${result.project.revision}。`);
  } catch (error) {
    if (error instanceof EngineError && error.code === "REVISION_CONFLICT") {
      await recoverConflict(error);
    } else {
      const { title, detail } = describe(error);
      toast("error", title, detail);
    }
  } finally {
    set({ busy: "" });
  }
}

export async function undo() {
  const last = state.undo[state.undo.length - 1];
  if (!last) {
    toast("info", "没有可撤销的操作", "撤销走的是历史恢复：恢复旧内容并生成新版本。");
    return;
  }
  // 恢复成功才动栈：失败时撤销能力还在，可以重试。
  if (!engine || !state.project) return;
  const cameFrom = state.project.revision; // 重做要回到的是“撤销前”的内容
  set({ busy: `撤销到 r${last.revision}…` });
  try {
    const result = await engine.restore(state.project.id, state.project.revision, last.revision);
    set({ undo: state.undo.slice(0, -1), redo: [...state.redo, { revision: cameFrom, label: "重做" }] });
    set({ project: result.project, candidate: null });
    if (state.batch.length) void runDryRun();
    void refreshProjects();
  } catch (error) {
    if (error instanceof EngineError && error.code === "REVISION_CONFLICT") {
      await recoverConflict(error);
    } else {
      const { title, detail } = describe(error);
      toast("error", title, detail);
    }
  } finally {
    set({ busy: "" });
  }
}

export async function redoStep() {
  const next = state.redo[state.redo.length - 1];
  if (!next || !engine || !state.project) return;
  const cameFrom = state.project.revision; // 再次撤销要回到“重做前”的内容
  set({ busy: "重做…" });
  try {
    const result = await engine.restore(state.project.id, state.project.revision, next.revision);
    set({ redo: state.redo.slice(0, -1), undo: [...state.undo, { revision: cameFrom, label: "撤销" }] });
    set({ project: result.project, candidate: null });
    if (state.batch.length) void runDryRun();
    void refreshProjects();
  } catch (error) {
    if (error instanceof EngineError && error.code === "REVISION_CONFLICT") {
      await recoverConflict(error);
    } else {
      const { title, detail } = describe(error);
      toast("error", title, detail);
    }
  } finally {
    set({ busy: "" });
  }
}

/* ---------------------------------------------------------------- 导出任务 */

export async function loadJobs(id?: string) {
  if (!engine) return;
  const project = id ?? state.project?.id;
  if (!project) return;
  try {
    const result = await engine.jobs(project);
    set({ jobs: result.jobs });
  } catch {
    /* 渲染未就绪时任务列表为空，界面会给出原因 */
  }
}

export async function startRender(presetId: string, filename: string, folder?: string, fit: RenderFit = "contain", range: RenderRange = "full") {
  if (!engine || !state.project) return null;
  const project = state.project;
  if (folder) {
    try {
      await engine.addOutputRoot(folder);
    } catch (error) {
      const { title, detail } = describe(error);
      toast("error", title, detail);
      return null;
    }
  }
  set({ busy: "排队渲染…" });
  try {
    const result = await engine.render(project.id, project.revision, presetId, filename, folder, state.sequenceId, fit, range);
    set({ jobs: [result.job, ...state.jobs] });
    toast("ok", range === "marks" ? "开始导出区间" : "开始导出", `锁定 r${project.revision}，进度在右下角导出面板。`);
    void watchJob(result.job.id);
    return result.job;
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
    return null;
  } finally {
    set({ busy: "" });
  }
}

const watching = new Set<string>();
let watcherRunning = false;
async function watchJob(jobId: string) {
  watching.add(jobId);
  if (watcherRunning) return;
  watcherRunning = true;
  const deadline = Date.now() + 60 * 60 * 1000;
  while (watching.size && Date.now() < deadline) {
    for (const id of [...watching]) {
      try {
        const { job } = await engine!.job(id);
        set({ jobs: state.jobs.map((item) => (item.id === job.id ? job : item)) });
        if (job.status === "succeeded") {
          watching.delete(id);
          toast("ok", "导出完成", job.output_path ?? "");
        } else if (job.status === "failed" || job.status === "cancelled") {
          watching.delete(id);
          const error = new EngineError(job.error_code ?? "RENDER_FAILED", job.message, {}, 500);
          toast("error", job.status === "failed" ? "导出失败" : "导出已取消", error.explain());
        }
      } catch {
        // 单次查询失败（引擎重启瞬间）不放弃整个监听，下轮再试
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 900));
  }
  watcherRunning = false;
}

export async function cancelJob(jobId: string) {
  if (!engine) return;
  try {
    const { job } = await engine.cancelJob(jobId);
    set({ jobs: state.jobs.map((item) => (item.id === job.id ? job : item)) });
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
  }
}

/** 一次交付多个画幅：所有条目都在服务端编译通过才入队，坏一条就整批不排队。 */
export async function startRenderBatch(
  items: { preset_id: string; filename: string; fit: RenderFit; range?: RenderRange }[],
  folder?: string
) {
  if (!engine || !state.project || !items.length) return null;
  const project = state.project;
  if (folder) {
    try {
      await engine.addOutputRoot(folder);
    } catch (error) {
      const { title, detail } = describe(error);
      toast("error", title, detail);
      return null;
    }
  }
  set({ busy: "排队批量导出…" });
  try {
    const result = await engine.renderBatch(project.id, project.revision, items, folder);
    set({ jobs: [...result.jobs, ...state.jobs] });
    toast("ok", `开始导出 ${result.jobs.length} 个画幅`, `全部锁定 r${project.revision}，进度在右下角导出面板。`);
    return result;
  } catch (error) {
    const { title, detail } = describe(error);
    toast("error", title, detail);
    return null;
  } finally {
    set({ busy: "" });
  }
}

/** 交付方案：把一组导出设置存成工程状态，下次一键出货，Agent 也能按同一个 id 复用这份列表。 */
export function saveRecipe(name: string, items: RenderBatchItem[], replaceId?: string) {
  if (!state.project) return;
  if (!items.length) {
    toast("warn", "方案里至少要有一条交付", "先选好画幅与文件名，再存方案。");
    return;
  }
  if (!name.trim()) {
    toast("warn", "方案需要一个名字", "例如「竖屏 9:16 + 横屏 16:9」。");
    return;
  }
  const recipe = { id: replaceId ?? newId("r"), name: name.trim(), items };
  submit([{ op: "recipe.set", recipe }], replaceId ? "改交付方案" : "存交付方案");
}

export function removeRecipe(recipeId: string) {
  submit([{ op: "recipe.remove", recipe_id: recipeId }], "删除交付方案");
}

export async function exportRecipe(recipeId: string, folder?: string) {
  const recipe = (state.project?.recipes ?? []).find((item) => item.id === recipeId);
  if (!recipe) {
    toast("warn", "这个交付方案已经不在了", "它可能被另一次编辑删除或撤销掉了。");
    return null;
  }
  return startRenderBatch(recipe.items, folder);
}

export function renderPlanPreview(presetId: string, fit: RenderFit = "contain", range: RenderRange = "full") {
  if (!engine || !state.project) return;
  void engine
    .renderPlan(state.project.id, presetId, state.project.revision, state.sequenceId, fit, range)
    .then((result) => {
      const argv = result.argv_preview.join(" ");
      const mode = FIT_MODES.find((item) => item.id === fit);
      const span = result.plan.range as { in_ticks?: number; out_ticks?: number } | undefined;
      const window = span?.in_ticks != null && span?.out_ticks != null
        ? `，区间 ${(span.in_ticks / TIMEBASE).toFixed(2)}–${(span.out_ticks / TIMEBASE).toFixed(2)} 秒`
        : "";
      toast("info", "已生成渲染计划", `按「${mode?.label ?? fit}」由服务端编译${window}，界面只读：${argv.slice(0, 160)}…`);
    })
    .catch((error: unknown) => {
      const { title, detail } = describe(error);
      toast("error", title, detail);
    });
}

/* ---------------------------------------------------------------- 窗口与视图 */

export function setView(view: View) {
  set({ view });
  if (view === "history") void loadHistory();
}

export async function windowControl(action: string) {
  const result = await bridge.control(action);
  if (result) set({ window: { ...state.window, ...result } });
}

export async function refreshWindowState() {
  const result = await bridge.windowState();
  set({ window: { ...state.window, ...result } });
}

export function toggleHelp(show = !state.showHelp) {
  set({ showHelp: show });
}

export async function copy(text: string, label: string) {
  const ok = await bridge.copyText(text);
  if (ok) toast("ok", `${label}已复制`);
  else toast("warn", "复制失败", "请手动选中后复制。");
}

export const appInfo = {
  get native() {
    return isNative;
  },
  token() {
    return state.info?.token ?? "";
  },
  engine: () => engine,
  baseUrl: () => state.info?.base_url ?? "",
};

/** 批次面板展示用的请求号：与真正提交时生成的 id 同构，让人看清幂等长什么样。 */
export function newBatchId(commandCount: number): string {
  return `ui-edit-${commandCount}-${newId("").slice(0, 10)}`;
}

/* ---------------------------------------------------------------- 视图偏好 */

export type Tool = "select" | "razor";
type EditPrefs = { pxPerSec: number; snap: boolean; tool: Tool; showTicks: boolean; linkedSelection: boolean };

const editListeners = new Set<() => void>();
const storedPrefs = (() => {
  try {
    return JSON.parse(localStorage.getItem("agentcut.edit") ?? "") as Partial<EditPrefs>;
  } catch {
    return {};
  }
})();
let edit: EditPrefs = { pxPerSec: 62, snap: true, tool: "select", showTicks: false, linkedSelection: true, ...storedPrefs };

function setEdit(patch: Partial<EditPrefs>) {
  edit = { ...edit, ...patch };
  try {
    localStorage.setItem("agentcut.edit", JSON.stringify(edit));
  } catch {
    /* 隐私模式下写不进 localStorage 也不影响使用 */
  }
  editListeners.forEach((fn) => fn());
}

export function useEdit(): EditPrefs {
  return useSyncExternalStore(
    (fn) => {
      editListeners.add(fn);
      return () => editListeners.delete(fn);
    },
    () => edit,
    () => edit
  );
}

export const prefs = {
  setZoom(value: number) {
    setEdit({ pxPerSec: Math.min(320, Math.max(16, Math.round(value))) });
  },
  zoomBy(factor: number) {
    this.setZoom(edit.pxPerSec * factor);
  },
  toggleSnap() {
    setEdit({ snap: !edit.snap });
  },
  toggleLinkedSelection() { setEdit({ linkedSelection: !edit.linkedSelection }); if (edit.linkedSelection) selectClips(state.selectedClips); },
  toggleTicks() {
    setEdit({ showTicks: !edit.showTicks });
  },
  /** 适应窗口：把整条时间线正好放进当前可视宽度。 */
  fitTo(durationTicks: number, viewportPx: number) {
    if (durationTicks <= 0 || viewportPx <= 0) return;
    const totalSeconds = durationTicks / TIMEBASE;
    this.setZoom(viewportPx / totalSeconds);
  },
  setTool(tool: Tool) {
    setEdit({ tool });
  },
};
