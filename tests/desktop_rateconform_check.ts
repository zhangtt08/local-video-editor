/**
 * 1.273: pasting a cut list made at another frame rate lands on the target grid by moving cut
 * points, not by stretching the picture. The tests use a 30 fps source (7 + 8 frame shots, a
 * 1-frame dissolve, a linked sound pair and a 1-second unlinked track) pasted into a 25 fps project.
 *
 * The rule this pins: each shared cut is rounded once, so neighbours stay neighbours; a linked
 * pair shares the coarser picture grid; keys outside the new duration are dropped and reported;
 * a cut that would ask for source beyond the file refuses the whole paste with the clip's name;
 * a speed curve refuses as a whole (no single mapping preserves it).
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { copyClips, pasteCommands } from "../desktop/src/selection";
import { conformPasted } from "../desktop/src/rateConform";
import { isClipClipboard } from "../desktop/src/clipboardStore";
import type { Clip, Project } from "../desktop/src/engine";
import { TIMEBASE as T } from "../desktop/src/time";

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync);
  assert.ok(found, `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const F30 = T / 30;
const F25 = T / 25;
const S48 = T / 48000;

const settings = (numerator: number) => ({
  timebase: T, width: 1280, height: 720, frame_rate: { numerator, denominator: 1 },
  sample_rate: 48000,
});

const asset = (id: string, kind: "video" | "audio", duration: number | null) => ({
  id, kind, label: id, reference: "metadata", duration_ticks: duration, verified: null,
});

function project(id: string, numerator: number, extra: Partial<Project> = {}): Project {
  return {
    schema_version: 12, id, revision: 1, name: id, notes: "", settings: settings(numerator),
    assets: {}, tracks: [], clips: {}, ...extra,
  } as Project;
}

const source = project("src", 30, {
  assets: {
    vid: asset("vid", "video", 60 * F30),
    aud: asset("aud", "audio", 60 * F30),
    pin: asset("pin", "video", 7 * F30),
  },
  tracks: [
    { id: "v", kind: "video", name: "V", muted: false, hidden: false, volume: 1 },
    { id: "s", kind: "audio", name: "A", muted: false, hidden: false, volume: 1 },
    { id: "m", kind: "audio", name: "M", muted: false, hidden: false, volume: 1 },
  ],
  clips: {
    a: {
      id: "a", asset_id: "vid", track_id: "v", position_ticks: 0, source_in_ticks: 0,
      duration_ticks: 7 * F30,
      keyframes: [
        { property: "x", at_ticks: 6 * F30, value: 0.2, interpolation: "linear" },
        { property: "x", at_ticks: Math.round(7.4 * F30), value: 0.4, interpolation: "linear" },
      ],
    },
    b: {
      id: "b", asset_id: "vid", track_id: "v", position_ticks: 6 * F30, source_in_ticks: 0,
      duration_ticks: 8 * F30, link_id: "pair",
      transition_in: { from_clip_id: "a", kind: "dissolve", duration_ticks: F30 },
    },
    voice: {
      id: "voice", asset_id: "aud", track_id: "s", position_ticks: 6 * F30,
      source_in_ticks: 0, duration_ticks: 8 * F30, link_id: "pair",
    },
    music: {
      id: "music", asset_id: "aud", track_id: "m", position_ticks: 0,
      source_in_ticks: 0, duration_ticks: 15 * F30,
    },
  },
});

const target = project("dst", 25);

const copied = copyClips(source, ["a", "b", "voice", "music"]);
assert.equal(copied.settings?.frame_rate.numerator, 30, "剪贴板没有记下源工程帧率");
assert.equal(isClipClipboard(copied), true, "新剪贴板被形状门拒了");
assert.equal(isClipClipboard({ ...copied, settings: undefined }), true, "旧剪贴板（没有 settings）应当照旧可读");
const broken = structuredClone(copied);
broken.settings!.frame_rate.numerator = 0;
assert.equal(isClipClipboard(broken), false, "帧率 0 的剪贴板不能过门");

const plan = pasteCommands(target, copied, 0);
assert.ok(plan.note, `跨帧率粘贴没有交代做了什么：${JSON.stringify(plan)}`);
assert.equal(plan.refusal, undefined);
const pasted = plan.commands.filter((command) => command.op === "clips.add")[0].clips as Clip[];
const bySource = new Map(copied.clips.map((clip, index) => [clip.id, pasted[index]]));
const a = bySource.get("a")!;
const b = bySource.get("b")!;
const voice = bySource.get("voice")!;
const music = bySource.get("music")!;

assert.equal(a.position_ticks % F25, 0, "甲没有落在目标帧格上");
assert.equal(a.duration_ticks, 6 * F25, `甲应当按切点收成 6 帧，实际 ${a.duration_ticks}`);
assert.equal(b.duration_ticks, 7 * F25, `乙应当收成 7 帧，实际 ${b.duration_ticks}`);
assert.equal(b.position_ticks % F25, 0);
assert.equal(b.transition_in?.duration_ticks, F25, "转场没有落到目标帧格");
assert.equal(a.position_ticks + a.duration_ticks - b.position_ticks, F25,
  "转场两侧的叠合区被切点换算改掉了");
assert.ok(b.transition_in!.duration_ticks < Math.min(a.duration_ticks, b.duration_ticks));
assert.equal(voice.position_ticks, b.position_ticks, "链接的声音被切点换算拆散了");
assert.equal(voice.duration_ticks, b.duration_ticks, "链接的声音时长与画面分家");
assert.equal(music.position_ticks % S48, 0, "未链接的声音应当仍在采样格上");
assert.equal(music.duration_ticks % S48, 0);
assert.equal(music.duration_ticks, 15 * F30, "未链接的声音不该被画面的帧格改时长");
assert.equal(a.keyframes?.length, 1, `新时长之外的针没有丢掉：${JSON.stringify(a.keyframes)}`);
assert.equal(a.keyframes?.[0].value, 0.2);
assert.match(plan.note!, /30\/1 → 25\/1 fps/);
assert.match(plan.note!, /丢弃 1 枚/);
assert.match(plan.note!, /1 条转场被夹短/);

// Same rate: the conformer must hand the clips back untouched and say nothing.
const copySame = copyClips(source, ["a", "b"]);
const same = pasteCommands(source, copySame, 0);
assert.equal(same.note, undefined, "同帧率粘贴不该冒出换算提示");
const sameClips = same.commands.filter((command) => command.op === "clips.add")[0].clips as Clip[];
assert.equal(sameClips[0].duration_ticks, 7 * F30);
assert.equal(sameClips[1].position_ticks, 6 * F30);

// Pinned at the file's first frame: rounding the cut up has no source room, so the paste refuses.
const pinnedSource = project("pin-src", 30, {
  assets: { pin: asset("pin", "video", 7 * F30) },
  tracks: [{ id: "v", kind: "video", name: "V", muted: false, hidden: false, volume: 1 }],
  clips: {
    pin: {
      id: "pin", asset_id: "pin", track_id: "v", position_ticks: 0, source_in_ticks: 0,
      duration_ticks: 7 * F30,
    },
  },
});
const pinned = pasteCommands(target, copyClips(pinnedSource, ["pin"]), 0);
assert.ok(pinned.refusal, `贴着素材开头的 7 帧应当拒绝整批，实际 ${JSON.stringify(pinned)}`);
assert.match(pinned.refusal!, /pin/);
assert.equal(pinned.commands.length, 0);

// A speed curve has no single mapping across rates; refuse by name rather than approximate.
const curvedSource = project("curve-src", 30, {
  assets: { vid: asset("vid", "video", 60 * F30) },
  tracks: [{ id: "v", kind: "video", name: "V", muted: false, hidden: false, volume: 1 }],
  clips: {
    c: {
      id: "c", asset_id: "vid", track_id: "v", position_ticks: 0, source_in_ticks: 0,
      duration_ticks: 7 * F30,
      speed_curve: [
        { at_ticks: 0, speed_percent: 50 },
        { at_ticks: 7 * F30, speed_percent: 150 },
      ],
    },
  },
} as unknown as Partial<Project>);
const curved = conformPasted(
  curvedSource.clips.c ? [curvedSource.clips.c] : [],
  curvedSource.tracks, target, { frame_rate: { numerator: 30, denominator: 1 }, sample_rate: 48000 },
  [asset("vid", "video", 60 * F30)],
);
assert.ok(curved.refusal, "带变速曲线的片段应当拒绝");
assert.match(curved.refusal!, /带变速曲线/);
assert.match(curved.refusal!, /vid/);

// Wiring: one owner for the conversion, the refusal is surfaced, and the note rides the success toast.
const selection = read("desktop/src/selection.ts", "../../desktop/src/selection.ts");
const store = read("desktop/src/store.ts", "../../desktop/src/store.ts");
const clipboard = read("desktop/src/clipboardStore.ts", "../../desktop/src/clipboardStore.ts");
assert.match(selection, /conformPasted\(shifted, copied\.tracks, project, copied\.settings, copied\.assets\)/,
  "粘贴规划没有把源时钟交给唯一的换算处");
assert.match(selection, /refusal: conformed\.refusal/, "拒绝没有交回给界面");
assert.match(store, /if \(plan\.refusal\)/, "界面没有处理跨帧率拒绝");
assert.match(store, /detail: plan\.note/, "换算交代没有跟着成功提示走");
assert.match(store, /detail\?: string/, "成功提示没有承载细节的那一格");
assert.match(clipboard, /value\.settings !== undefined/, "剪贴板形状门没有检查新的一格");
const imports = selection.match(/from "\.\/rateConform"/g) ?? [];
assert.equal(imports.length, 1, "换算模块应当只有一处被引入");

console.log(
  "desktop_rateconform_check: PASS: 30→25 fps 的切点、链接、转场、越界针与两档拒绝都按同一处换算；"
  + "同帧率一字不改，剪贴板形状门认得新的一格",
);
