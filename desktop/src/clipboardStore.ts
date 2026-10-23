/**
 * 剪贴板跨重启保存：写出去的是这一份 JSON，读回来必须先过形状检查再交给界面。
 *
 * 为什么要单独一处：`localStorage` 里躺着的东西不是本进程写的——上一次运行的版本、被人手改过的
 * 值、或者配额被清之后的半份都算。界面拿一份形状不对的「复制」去拼粘贴命令，得到的会是引擎那句
 * 对不上原因的拒绝，或者直接少几个片段。所以这里只做一件事：认得就交回，认不得就当没有复制过。
 *
 * 两份剪贴板各存各的（片段那份要连着素材与轨道走，关键帧那份按工程失效），但形状检查与读写只有一处。
 * `Storage` 由调用方给，所以界面之外也能量（隐私模式里 `localStorage` 会抛错，那份不影响使用）。
 */

import type { CopiedKeys } from "./keyframeClipboard";
import type { ClipClipboard } from "./selection";

export const CLIP_KEY = "agentcut.clipboard";
export const KEYS_KEY = "agentcut.keyclipboard";
export const MARKS_KEY = "agentcut.sourceMarks";

/** 1.163「复制属性」存的不是那份数，而是「来源是哪一段」：粘的时候向引擎现问一份规划，
 *  所以复制之后又改了来源，粘出去的就是改过的那份——界面不存第二份工程状态。 */
export type AttributeCopy = { projectId: string; clipId: string };

export const ATTRIBUTES_KEY = "agentcut.attributeCopy";

export function isAttributeCopy(value: unknown): value is AttributeCopy {
  return record(value) && text(value.projectId) && text(value.clipId);
}

/** 素材预览上那对入／出点：按素材的 key 存，取用时再按目标工程的格子夹。 */
export type SourceMark = { in_ticks?: number; out_ticks?: number };

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string";
const count = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const list = (value: unknown): value is unknown[] => Array.isArray(value);

/** 片段剪贴板：粘贴要读的字段都在这里，缺一个就当没复制过。 */
export function isClipClipboard(value: unknown): value is ClipClipboard {
  if (!record(value) || !text(value.projectId)) return false;
  if (!list(value.clips) || !list(value.assets) || !list(value.tracks)) return false;
  if (value.sequenceId !== undefined && value.sequenceId !== null && !text(value.sequenceId)) return false;
  if (value.sequences !== undefined && !list(value.sequences)) return false;
  if (value.settings !== undefined) {
    const settings = value.settings;
    if (!record(settings) || !record(settings.frame_rate)) return false;
    const rate = settings.frame_rate;
    if (!count(rate.numerator) || !count(rate.denominator) || rate.numerator <= 0 || rate.denominator <= 0) return false;
    if (!count(settings.sample_rate) || settings.sample_rate <= 0) return false;
  }
  if (!(value.clips as unknown[]).every((clip) => record(clip) && text(clip.id) && text(clip.track_id) && text(clip.asset_id) && count(clip.position_ticks) && count(clip.duration_ticks))) return false;
  return (value.assets as unknown[]).every((asset) => record(asset) && text(asset.id) && text(asset.kind) && text(asset.reference))
    && (value.tracks as unknown[]).every((track) => record(track) && text(track.id) && text(track.kind));
}

/** 关键帧剪贴板：一条属性、一个基准 tick、一串针——`pasteKeys` 还会再判工程对不对。
 *  1.212 起那串针可能住在某一层的链里：带了 `layer` 就必须是个从 0 数过去的整数层序，缺了或半份
 *  都不算（`pasteInto` 按它分流，认错了就会把层的针写进片段自己的曲线上）。 */
export function isCopiedKeys(value: unknown): value is CopiedKeys {
  if (!record(value) || !text(value.projectId) || !text(value.property) || !count(value.base) || !list(value.keys)) return false;
  if (value.layer !== undefined && !(count(value.layer) && Number.isInteger(value.layer) && (value.layer as number) >= 0)) return false;
  return (value.keys as unknown[]).every((key) => record(key) && text(key.property) && count(key.at_ticks));
}

/** 素材入出点那份表：每个 key 底下最多两个数，且入点必须在出点之前——反过来的那份不知道要画什么。 */
export function isSourceMarks(value: unknown): value is Record<string, SourceMark> {
  if (!record(value)) return false;
  return Object.entries(value).every(([key, mark]) => {
    if (!text(key) || !record(mark)) return false;
    if (!Object.keys(mark).every((field) => field === "in_ticks" || field === "out_ticks")) return false;
    const inTicks = mark.in_ticks;
    const outTicks = mark.out_ticks;
    if (inTicks !== undefined && !count(inTicks)) return false;
    if (outTicks !== undefined && !count(outTicks)) return false;
    return inTicks === undefined || outTicks === undefined || (inTicks as number) < (outTicks as number);
  });
}

export function readStored<T>(store: Pick<Storage, "getItem">, key: string, guard: (value: unknown) => value is T): T | null {
  try {
    const raw = store.getItem(key);
    if (raw === null) return null;
    const parsed: unknown = JSON.parse(raw);
    return guard(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** 写：清空也要写出去（删掉那一项），不然下一次启动又会把旧的捞回来。 */
export function writeStored(store: Pick<Storage, "setItem" | "removeItem">, key: string, value: unknown): void {
  try {
    if (value === null) store.removeItem(key);
    else store.setItem(key, JSON.stringify(value));
  } catch {
    /* 存储写不进去只影响下一次启动，不影响这一次 */
  }
}

type Store = Pick<Storage, "getItem"> & Partial<Pick<Storage, "setItem" | "removeItem">>;

/** 这台机器上有没有 `localStorage` 这个全局。壳层检查是在 node 里跑的，那边没有——那份复制就当没存过，
 *  不是错误。取不到就别调，`localStorage` 作为自由变量在 node 里会直接抛。 */
export function browserStore(): Store | null {
  return typeof localStorage === "undefined" ? null : localStorage;
}

export function readBrowser<T>(key: string, guard: (value: unknown) => value is T): T | null {
  const store = browserStore();
  return store ? readStored(store, key, guard) : null;
}

export function writeBrowser(key: string, value: unknown): void {
  const store = browserStore();
  if (store) writeStored(store as Pick<Storage, "setItem" | "removeItem">, key, value);
}
