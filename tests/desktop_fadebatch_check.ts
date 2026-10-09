/** 拖一次淡角柄，落库的是一组：被拖的那条 + 一起选中的 + 音画链接的伙伴，各自按自己的长度夹。
 *
 * 1.91 的角柄只淡被拖的那一条，剪映与达芬奇都是整组一起动。这一版把「一组」算清楚，
 * 而一组里最容易做错的是两件事：
 *
 * 1. 拿被拖那条的长度去夹别人——三条片段各有各的额度，各自的 `fadeRoom` 才是自己的上限；
 * 2. 把「夹到 0」当成「取消这一头」——`Clip.fade` 里这两个是同一个数字，所以放不下的那条
 *    必须整个跳过（不写），而不是替用户把那一头清掉。
 *
 * 门禁钉的就是这两条，外加锁定轨道要点名、拖回边上确实是取消。
 */

import assert from "node:assert/strict";

import { fadeDragBatch } from "../desktop/src/effects";
import type { Asset, Clip, Project, Track } from "../desktop/src/engine";

const T = 70_560_000;
const FRAME = T / 25;

const clip = (id: string, track: string, asset: string, duration: number, patch: Partial<Clip> = {}): Clip =>
  ({
    id,
    asset_id: asset,
    track_id: track,
    position_ticks: 0,
    source_in_ticks: 0,
    duration_ticks: duration,
    fade: null,
    ...patch,
  }) as Clip;

const asset = (id: string, kind: string, hasAudio?: boolean): Asset =>
  ({ id, kind, label: id, reference: "r", duration_ticks: 10 * T, verified: hasAudio === undefined ? null : { has_audio: hasAudio } }) as Asset;

const project = (clips: Clip[], tracks: Track[], assets: Asset[]): Project =>
  ({
    id: "p",
    name: "n",
    revision: 1,
    schema_version: 14,
    notes: "",
    settings: { timebase: T, frame_rate: { numerator: 25, denominator: 1 }, width: 1920, height: 1080 },
    tracks,
    clips: Object.fromEntries(clips.map((c) => [c.id, c])),
    assets: Object.fromEntries(assets.map((a) => [a.id, a])),
    markers: [],
  }) as unknown as Project;

const video: Track = { id: "v", kind: "video", name: "画面", muted: false, hidden: false, volume: 1 };
const audio: Track = { id: "a", kind: "audio", name: "声音", muted: false, hidden: false, volume: 1 };
const locked: Track = { id: "lk", kind: "video", name: "锁", muted: false, hidden: false, volume: 1, locked: true };

const picture = asset("pic", "video");
const sound = asset("snd", "audio");
const mixed = asset("mix", "video", true);

const key = (op: { clipId: string; property: string; side: string; ticks: number }) => `${op.clipId}/${op.property}/${op.side}=${op.ticks / T}`;

// 一、组 = 被拖的 + 选中的；没被选中的不许被带进去。
const three = project(
  [clip("a", "v", "pic", 6 * T), clip("b", "v", "pic", 3 * T), clip("z", "v", "pic", 6 * T)],
  [video],
  [picture]
);
const one = fadeDragBatch(three, "a", "in", 1 * T, FRAME, false, ["b"]);
assert.deepEqual(one.ops.map(key).sort(), ["a/opacity/in=1", "b/opacity/in=1"], one.ops);
assert.deepEqual(one.skipped, [], "两条都放得下，一个都不该被点名");

// 二、各自按自己的长度夹：拖 5 秒，6 秒的片段拿 5 秒，3 秒的那条只能拿 3 秒。
const clamped = fadeDragBatch(three, "a", "in", 5 * T, FRAME, false, ["b"]);
assert.deepEqual(clamped.ops.map(key).sort(), ["a/opacity/in=5", "b/opacity/in=3"], clamped.ops);

// 三、链接一起动：画面与它链接的声音是一个整体，拖画面那条的角柄，音量那头跟着淡。
const linked = project(
  [clip("l1", "v", "pic", 6 * T, { link_id: "L" }), clip("l2", "a", "snd", 6 * T, { link_id: "L" }), clip("x", "a", "snd", 6 * T)],
  [video, audio],
  [picture, sound]
);
const pair = fadeDragBatch(linked, "l1", "in", 2 * T, FRAME, false);
assert.deepEqual(pair.ops.map(key).sort(), ["l1/opacity/in=2", "l2/gain/in=2"], pair.ops);
assert.equal(pair.skipped.length, 0, "没进组的片段不该被点名");

// 四、夹不动的那条整个跳过，绝不写 0 去「取消」它那一头。
const full = project(
  [clip("f", "v", "pic", 3 * T, { fade: { opacity_in_ticks: 0, opacity_out_ticks: 3 * T, gain_in_ticks: 0, gain_out_ticks: 0 } }), clip("g", "v", "pic", 6 * T)],
  [video],
  [picture]
);
const none = fadeDragBatch(full, "g", "in", 4 * T, FRAME, false, ["f"]);
assert.deepEqual(none.ops.map(key), ["g/opacity/in=4"], `放不下的那条必须整个跳过：${none.ops}`);
assert.equal(none.skipped.length, 0, "与现值相同（这里都是「不写」）不算拒绝，也不点名");
const kept = project(
  [clip("f", "v", "pic", 3 * T, { fade: { opacity_in_ticks: T, opacity_out_ticks: 2 * T, gain_in_ticks: 0, gain_out_ticks: 0 } })],
  [video],
  [picture]
);
// 对面那头占了 2 秒，这一头的额度就只剩 1 秒——它现在的淡入正好是 1 秒，拖多长都不写。
const noRoom = fadeDragBatch(kept, "f", "in", 3 * T, FRAME, false);
assert.deepEqual(noRoom.ops, [], `额度已被对面占满时不许写出第二个数：${noRoom.ops}`);
// 而拖回边上（0）是明说的「取消这一头」，这一次要写。
const cancel = fadeDragBatch(kept, "f", "in", 0, FRAME, false);
assert.deepEqual(cancel.ops.map(key), ["f/opacity/in=0"], cancel.ops);

// 五、Shift 同时淡两头，但每条只拿自己有的那一档：纯画面素材只有 opacity。
const shift = fadeDragBatch(three, "a", "out", 1 * T, FRAME, true, ["b"]);
assert.deepEqual(shift.ops.map(key).sort(), ["a/opacity/out=1", "b/opacity/out=1"], shift.ops);
const hasSound = project([clip("m", "v", "mix", 6 * T)], [video], [mixed]);
const both = fadeDragBatch(hasSound, "m", "out", 1 * T, FRAME, true);
assert.deepEqual(both.ops.map(key).sort(), ["m/gain/out=1", "m/opacity/out=1"], both.ops);

// 六、锁定轨道要点名，且不许出现在 ops 里；组里读到不存在的片段就默默跳过（不是拒绝）。
const skipProject = project(
  [clip("k", "lk", "pic", 6 * T), clip("q", "v", "pic", 6 * T)],
  [video, audio, locked],
  [picture, sound]
);
const named = fadeDragBatch(skipProject, "q", "in", 1 * T, FRAME, false, ["k", "gone"]);
assert.deepEqual(named.ops.map(key), ["q/opacity/in=1"], named.ops);
assert.deepEqual(named.skipped.map((s) => `${s.clipId}:${s.why}`), ["k:所在轨道已锁定"], named.skipped);

// 七、音轨上的锚点淡的是音量，不是画面。用的长度必须是整数帧：25 fps 下 1.5 秒是 37.5 帧，
// 网格会把它进到 38 帧（1.52 秒）——这条正是「拖动量落不到半个帧上」的证据。
const onAudio = project([clip("s", "a", "snd", 6 * T)], [audio], [sound]);
const gainOnly = fadeDragBatch(onAudio, "s", "in", 1.6 * T, FRAME, false);
assert.deepEqual(gainOnly.ops.map(key), ["s/gain/in=1.6"], gainOnly.ops);
assert.deepEqual(fadeDragBatch(onAudio, "s", "in", 1.5 * T, FRAME, false).ops.map(key), ["s/gain/in=1.52"], "半个帧进到整帧");

// 八、一次拖动只动它点名的那一头：淡入的拖动不许碰淡出。
const sides = project([clip("a", "v", "pic", 6 * T, { fade: { opacity_in_ticks: 0, opacity_out_ticks: 2 * T, gain_in_ticks: 0, gain_out_ticks: 0 } })], [video], [picture]);
const inOnly = fadeDragBatch(sides, "a", "in", 1 * T, FRAME, false);
assert.deepEqual(inOnly.ops.map((op) => op.side), ["in"], inOnly.ops);
assert.deepEqual(inOnly.ops.map((op) => op.property), ["opacity"], "没按 Shift 就只淡画面");

console.log("PASS: 一组淡角柄各自按自己的长度夹、链接的伙伴跟着动、额度为 0 的那条整个跳过而不是清成 0，锁定轨道要点名，拖回边上才是取消");
