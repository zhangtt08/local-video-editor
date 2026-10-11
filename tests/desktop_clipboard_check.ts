/** 剪贴板跨重启保存：认得的形状才交回，认不得的当没复制过；冷的那份要粘出去，先让这台引擎
 *  把没有落点的素材重新探一遍。
 *
 * 1.125 之前 `README` 的边界写着「剪贴板仅本次应用会话」。把它存进 `localStorage` 本身只要一行，
 *  难的是两件事：① 存储里的东西不是本进程写的（半份、被人改过、上一版的形状），界面拿它去拼命令
 *  只会换来一句对不上原因的引擎拒绝；② `asset.import` 只认**这台引擎**发过的那张探测记录，
 *  上一次运行留下的那份复制跨工程粘贴必然被拒。所以这里断的是这两条，而不只是「写得进去读得出来」。
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { CLIP_KEY, KEYS_KEY, MARKS_KEY, isClipClipboard, isCopiedKeys, isSourceMarks, readBrowser, readStored, writeStored } from "../desktop/src/clipboardStore";
import { clipboardAssetsToReprobe, copyClips, pasteCommands, reviveClipboardAssets, type ClipClipboard } from "../desktop/src/selection";
import type { Asset, Project, Track } from "../desktop/src/engine";

// —— 最小的工程夹具：字段只填到 `copyClips`／`pasteCommands` 真要读的那些 ——————————————
const verified = (sha: string, probeId: string) => ({
  probe_id: probeId, path: `/media/${sha}.mp4`, kind: "video", label: "板", size_bytes: 1024,
  content_sha256: sha, duration_ticks: 70_560_000 * 2, width: 320, height: 180, has_audio: false,
  frame_rate: { numerator: 25, denominator: 1 },
});
const asset = (id: string, sha: string, probeId: string): Asset => ({
  id, kind: "video", label: id, reference: probeId, duration_ticks: 70_560_000 * 2, verified: verified(sha, probeId),
});
const track = (id: string): Track => ({ id, kind: "video", name: "画面" } as unknown as Track);
const clip = (id: string, assetId: string, at: number) => ({
  id, asset_id: assetId, track_id: "v1", position_ticks: at, source_in_ticks: 0, duration_ticks: 70_560_000,
});
const project = (assets: Asset[], clips: ReturnType<typeof clip>[], id = "p1"): Project => ({
  id, name: id, revision: 3, settings: { width: 320, height: 180, sample_rate: 48000, frame_rate: { numerator: 25, denominator: 1 } },
  assets: Object.fromEntries(assets.map((a) => [a.id, a])), tracks: [track("v1")],
  clips: Object.fromEntries(clips.map((c) => [c.id, c])), sequences: {}, markers: [],
} as unknown as Project);

const source = project([asset("a1", "A".repeat(64), "probe-old"), asset("a2", "B".repeat(64), "probe-old")], [clip("c1", "a1", 0)]);
const copied: ClipClipboard = copyClips(source, ["c1"]);

// —— ① 形状检查：真的那份要认得，坏的那几样都要当没复制过 ——————————————————————————
assert.equal(isClipClipboard(copied), true, "copyClips 交出的那份必须过自己的门");
const roundTrip = JSON.parse(JSON.stringify(copied));
assert.equal(isClipClipboard(roundTrip), true, "JSON 往返还是同一份");
for (const junk of [
  null, undefined, 0, "p", [], {},
  { projectId: "p1", clips: "不是数组", assets: [], tracks: [] },
  { projectId: "p1", clips: [{ id: "c1" }], assets: [], tracks: [] },
  { projectId: 7, clips: [], assets: [], tracks: [] },
  { projectId: "p1", clips: [], assets: [{ id: "a1", kind: "video" }], tracks: [] },
  { projectId: "p1", sequenceId: 5, clips: [], assets: [], tracks: [] },
]) {
  assert.equal(isClipClipboard(junk), false, `不该认这份：${JSON.stringify(junk)}`);
}
assert.equal(isCopiedKeys({ projectId: "p1", property: "opacity", base: 0, keys: [{ property: "opacity", at_ticks: 10 }] }), true);
assert.equal(isCopiedKeys({ projectId: "p1", property: "opacity", base: 0, keys: [{ at_ticks: 10 }] }), false, "没有属性的针不算一份复制");
assert.equal(isCopiedKeys({ projectId: "p1", property: "opacity", base: "0", keys: [] }), false, "基准不是数就不算");

// 存储：写得进去、读得出来、坏 JSON 与半份都不炸也不交回。
const memory = new Map<string, string>();
const store = {
  getItem: (key: string) => memory.get(key) ?? null,
  setItem: (key: string, value: string) => void memory.set(key, value),
  removeItem: (key: string) => void memory.delete(key),
};
writeStored(store, CLIP_KEY, copied);
assert.deepEqual(readStored(store, CLIP_KEY, isClipClipboard), copied, "往返必须一字不差");
memory.set(CLIP_KEY, "{截断的");
assert.equal(readStored(store, CLIP_KEY, isClipClipboard), null, "坏 JSON 当没复制过");
memory.set(CLIP_KEY, JSON.stringify({ projectId: "p1", clips: [{}], assets: [], tracks: [] }));
assert.equal(readStored(store, CLIP_KEY, isClipClipboard), null, "形状不对当没复制过");
writeStored(store, CLIP_KEY, null);
assert.equal(memory.has(CLIP_KEY), false, "清空要真的删掉那一项，不然下次启动又把旧的捞回来");

const throwing = { getItem: () => { throw new Error("隐私模式"); }, setItem: () => { throw new Error("配额"); }, removeItem: () => { throw new Error("配额"); } };
assert.equal(readStored(throwing, CLIP_KEY, isClipClipboard), null, "读不出就当没复制过");
writeStored(throwing, CLIP_KEY, copied); // 不许抛

// —— ② 冷的那份：哪些素材必须由这台引擎重新探一遍 ————————————————————————————
const foreign = project([], [], "p2");
const stale = copied.assets.filter((entry) => entry.verified);
assert.equal(stale.length, 1, "复制里带探测记录的素材就一个（另一份没被这个片段用到）");
assert.deepEqual(clipboardAssetsToReprobe(foreign, copied).map((entry) => entry.asset.id), ["a1"], "目标工程里没有落点的那些才要重探");
assert.deepEqual(clipboardAssetsToReprobe(source, copied), [], "同一份内容（按哈希）已经在工程里就别再探一次");
// 探的是 `verified.path`。`reference` 在 `asset.import` 之后是引擎给的那个 probe_id，拿它去探会被回
// 一句 422——装机实测第一次点粘贴就是这么红的。
assert.deepEqual(clipboardAssetsToReprobe(foreign, copied).map((entry) => entry.path), [`/media/${"A".repeat(64)}.mp4`], "要探的路径来自探测记录，不是 reference");
assert.equal(copied.assets[0]?.reference, "probe-old", "夹具的 reference 就是那个 probe_id（与引擎存的一样）");
const sibling = project([asset("a9", "A".repeat(64), "probe-new")], [], "p3");
assert.deepEqual(clipboardAssetsToReprobe(sibling, copied), [], "换个 id 但内容同一份，也算已有");
const revived = reviveClipboardAssets(copied, { a1: verified("A".repeat(64), "probe-this-run") });
assert.equal(revived.assets.find((entry) => entry.id === "a1")?.verified?.probe_id, "probe-this-run", "换的是这次运行发的那张探测记录");
assert.equal(revived.assets.find((entry) => entry.id === "a1")?.reference, "probe-old", "reference 一个字都不动：换的只有那张探测记录");
assert.equal(copied.assets.find((entry) => entry.id === "a1")?.verified?.probe_id, "probe-old", "原那份不许被就地改");

// 粘到别的工程：重探之后发的是 `asset.import`，带的是新的 probe_id。
const commands = pasteCommands(foreign, revived, 0).commands;
const importCommand = commands.find((entry) => entry.op === "asset.import") as { probe_id?: string } | undefined;
assert.equal(importCommand?.probe_id, "probe-this-run", "冷粘贴交出去的是这台引擎刚发的那张记录");
const untouched = pasteCommands(foreign, copied, 0).commands.find((entry) => entry.op === "asset.import") as { probe_id?: string } | undefined;
assert.equal(untouched?.probe_id, "probe-old", "没重探就还是旧的那张——那正是会被拒的样子");

// —— ②b 素材上那对入／出点：同一道门，认不得就当没设过 ——————————————————————————
assert.equal(isSourceMarks({ "v:1": { in_ticks: 0, out_ticks: 10 } }), true);
assert.equal(isSourceMarks({ "v:1": {} }), true, "清过入点的那份就是这个样子");
assert.equal(isSourceMarks({ "v:1": { in_ticks: 20, out_ticks: 10 } }), false, "入点在出点之后的那份不知道要画什么");
assert.equal(isSourceMarks({ "v:1": { in_ticks: "0" } }), false, "不是数就当没有");
assert.equal(isSourceMarks({ "v:1": { in_tick: 0 } }), false, "拼错的字段不收");
assert.equal(isSourceMarks([0]), false, "数组不是那份表");
writeStored(store, MARKS_KEY, { "v:1": { in_ticks: 5 } });
assert.deepEqual(readStored(store, MARKS_KEY, isSourceMarks), { "v:1": { in_ticks: 5 } }, "入出点往返要一字不差");

// —— ③ 界面只走这一处读写 ————————————————————————————————————————————————
const storeText = readFileSync("desktop/src/store.ts", "utf-8");
assert.equal((storeText.match(/writeBrowser\(CLIP_KEY/g) ?? []).length, 1, "一份复制只有一个落点：视图别自己再写一遍");
assert.match(storeText, /function rememberClip[\s\S]{0,220}writeBrowser\(CLIP_KEY/, "写的这一处就是 rememberClip");
assert.match(storeText, /readBrowser\(CLIP_KEY, isClipClipboard\)/, "启动时按同一道门读回来");
assert.doesNotMatch(storeText, /localStorage\.setItem\("agentcut\.clipboard/, "不许绕过 clipboardStore 自己拼存储键");
assert.match(storeText, /clipboardAssetsToReprobe/, "冷那份要重探的是哪些，也走 selection 那一处");
assert.equal((storeText.match(/writeBrowser\(MARKS_KEY/g) ?? []).length, 1, "入出点也只有一个落点");
assert.match(storeText, /readBrowser\(MARKS_KEY, isSourceMarks\)/, "启动时按同一道门把入出点读回来");
const keys = readFileSync("desktop/src/keyframeClipboard.ts", "utf-8");
assert.match(keys, /readBrowser\(KEYS_KEY, isCopiedKeys\)/, "关键帧那份也一样存");
assert.doesNotMatch(keys, /let last: CopiedKeys \| null = null;/, "不该再是只活在内存里的那一份");
// node 里没有 `localStorage` 这个全局：那份复制就当没存过，而不是把壳层检查撞死。
assert.equal(readBrowser("agentcut.没有这一项", isClipClipboard), null, "取不到存储就是没复制过");

console.log("PASS: 剪贴板跨重启——认得的形状才交回、坏的一律当没复制过、冷的那份先让这台引擎重探一遍");
