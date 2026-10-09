/** 时间线上拖淡角柄：指针离开那条边多远，这一头就淡多久，而且永远拖不出一条引擎必定拒绝的淡。
 *
 * 1.90 把淡搬到了片段的边上，却还只能在检查器里填秒数。这一版给它在时间线上加了可拖的角，
 * 于是多了一条只有界面才有的路径：拖动量是连续像素，落成整数 tick 时要对齐时间线的网格，
 * 并且要被「片段长度 − 对面那头」夹住。这个数是 `fadeRoom`，与检查器那两行同源——
 * 门禁要钉的就是「同源」这两个字：把对面那头改一改、把片段剪一剪，夹点必须跟着动。
 *
 * 最硬的一条是最后一个循环：任意一个原始拖动量，夹完之后再交给 `fadeBlocker`，必须次次放行。
 * 它成立，界面上就再也拖不出一个按下去必定被引擎回 `INVALID_FADE` 的数字（1.82 的规矩）。
 * 这条断言对写死的上限天然不满——把 30 秒片段上的夹点硬写成 2 秒，前几个循环就红。
 */

import assert from "node:assert/strict";

import { fadeBlocker, fadeDragTicks, fadeProperties, fadeRoom, fadeWindows } from "../desktop/src/effects";
import type { Asset, Clip } from "../desktop/src/engine";

const T = 70_560_000;
const FRAME = T / 25; // 25 fps 的一帧，时间线的网格
const clip = (duration: number, fade?: Clip["fade"]): Clip =>
  ({
    id: "c",
    asset_id: "a",
    track_id: "v",
    position_ticks: 0,
    source_in_ticks: 0,
    duration_ticks: duration,
    fade: fade ?? null,
  }) as Clip;

// 没有淡的六秒片段：额度就是整条片段。
assert.equal(fadeRoom(clip(6 * T), "opacity", "in"), 6 * T, "两头都空着，淡入能要满整段");

// 拖多少给多少（按网格对齐）：1 秒、2.34 秒，都不是界面自己发明的数。
assert.equal(fadeDragTicks(clip(6 * T), "opacity", "in", 1 * T, FRAME), 1 * T);
assert.equal(fadeDragTicks(clip(6 * T), "opacity", "in", 2.34 * T, FRAME), Math.round(2.34 * T / FRAME) * FRAME);

// 拖回边上、拖过头（负数）都是 0，也就是取消这一头，绝不倒着淡。
assert.equal(fadeDragTicks(clip(6 * T), "opacity", "in", 0, FRAME), 0);
assert.equal(fadeDragTicks(clip(6 * T), "opacity", "out", -3 * T, FRAME), 0, "越出片段外头不算长度");

// 夹点听片段的长度：同一次 7 秒的拖动，在 6 秒片段上给 6 秒、在 9 秒片段上给 7 秒。
assert.equal(fadeDragTicks(clip(6 * T), "opacity", "in", 7 * T, FRAME), 6 * T);
assert.equal(fadeDragTicks(clip(9 * T), "opacity", "in", 7 * T, FRAME), 7 * T);

// 夹点也听对面那头：那头占掉 2 秒，这一头最多还剩 4 秒——它是算出来的，不是写死的。
const opposite = clip(6 * T, { opacity_in_ticks: 0, opacity_out_ticks: 2 * T, gain_in_ticks: 0, gain_out_ticks: 0 });
assert.equal(fadeRoom(opposite, "opacity", "in"), 4 * T);
assert.equal(fadeDragTicks(opposite, "opacity", "in", 5 * T, FRAME), 4 * T, "对面占掉的 2 秒不能被再淡一次");
const oppositeShrunk = clip(6 * T, { opacity_in_ticks: 0, opacity_out_ticks: T, gain_in_ticks: 0, gain_out_ticks: 0 });
assert.equal(fadeDragTicks(oppositeShrunk, "opacity", "in", 5 * T, FRAME), 5 * T, "对面缩 1 秒，这边就多出 1 秒");

// 两个属性各算各的账（Shift 拖同时淡画面与音量时不许互相顶）：音量淡入占了 3 秒，画面那一头照旧能要满 6 秒。
const both = clip(6 * T, { opacity_in_ticks: 0, opacity_out_ticks: 0, gain_in_ticks: 3 * T, gain_out_ticks: 0 });
assert.equal(fadeDragTicks(both, "gain", "out", 4 * T, FRAME), 3 * T, "音量的两头自己挤");
assert.equal(fadeDragTicks(both, "opacity", "in", 4 * T, FRAME), 4 * T, "画面完全不理会音量那 3 秒");

// 网格不许被拖动绕过：一个比半帧还小的量落回 0，一个差一点到整帧的量进位。
assert.equal(fadeDragTicks(clip(6 * T), "opacity", "in", FRAME / 3, FRAME), 0);
assert.equal(fadeDragTicks(clip(6 * T), "opacity", "in", FRAME * 1.6, FRAME), 2 * FRAME);
// 界面自己算的网格（缩放极小时量子可能为 0）不许把长度变成 NaN，也不许落下半个 tick。
const degenerate = fadeDragTicks(clip(6 * T), "opacity", "in", 1.4 * FRAME, 0);
assert.ok(Number.isInteger(degenerate), `量子为 0 时也要落整数 tick：${degenerate}`);
assert.equal(degenerate, Math.round(1.4 * FRAME));

// 最硬的一条：任意原始拖动量，夹完再问检查器那句「放不下」，必须次次放行。
// 只扫引擎存得下来的状态——对面那头本身就超过片段长度的工程是假的（那样一次写入会被
// `INVALID_FADE` 拒绝或被夹到片段长度），拿它来断言等于让门禁去判一个界面永远不会遇到的东西。
const durations = [1 * T, 2.5 * T, 6 * T, 17 * T];
const outs = [0, T, 2 * T];
let probes = 0;
for (const duration of durations) {
  for (const out of outs) {
    if (out > duration) continue;
    const subject = clip(duration, { opacity_in_ticks: 0, opacity_out_ticks: out, gain_in_ticks: 0, gain_out_ticks: 0 });
    for (const raw of [0, FRAME, 0.9 * duration, duration, duration * 1.7, 240 * T]) {
      for (const side of ["in", "out"] as const) {
        const value = fadeDragTicks(subject, "opacity", side, raw, FRAME);
        assert.ok(value >= 0 && value <= duration, `夹不出片段外：${value} 对 ${duration}`);
        assert.equal(
          fadeBlocker(subject, "opacity", side, value),
          null,
          `拖出来的 ${value} 秒会被引擎拒绝（片段 ${duration}，对面 ${out}，原始 ${raw}）：${fadeBlocker(subject, "opacity", side, value)}`
        );
        probes += 1;
      }
    }
  }
}

// 读数仍是工程状态：拖完的那一头，`fadeWindows` 认得到（界面靠它画斜坡，不另记一份）。
const recorded = clip(6 * T, { opacity_in_ticks: 2 * T, opacity_out_ticks: 0, gain_in_ticks: 0, gain_out_ticks: 0 });
assert.equal(fadeWindows(recorded).opacity.in, 2 * T);
assert.equal(fadeWindows(recorded).gain.in, 0, "音量那一头没被画面拖动带起来");

// 能淡哪几头现在只有一处判断（`fadeProperties`），检查器那两行与时间线的角柄读同一个。
// 钉的是「界面不许递出一个引擎必定拒绝的手柄」：音频素材没有不透明度，`clip.fade` 会按
// `INVALID_FADE` 点名 `asset_kind` 拒；带声音的画面素材两头都给；关了内嵌声音就只剩画面。
const asset = (kind: string, hasAudio?: boolean): Asset =>
  ({ id: "a", kind, label: "x", reference: "r", verified: hasAudio === undefined ? null : { has_audio: hasAudio } }) as Asset;
const on = (duration: number, patch: Partial<Clip> = {}, from?: Asset): Clip =>
  ({ ...clip(duration), ...patch, asset_id: from?.id ?? "a" }) as Clip;

assert.deepEqual(fadeProperties(on(6 * T), asset("video")), ["opacity"], "没有声音的画面素材只淡画面");
assert.deepEqual(fadeProperties(on(6 * T), asset("video", true)), ["opacity", "gain"], "带声音的画面素材两头都能淡");
assert.deepEqual(
  fadeProperties(on(6 * T, { embedded_audio: false }), asset("video", true)),
  ["opacity"],
  "关了内嵌声音就不该给音量手柄"
);
assert.deepEqual(fadeProperties(on(6 * T), asset("audio")), ["gain"], "音频素材没有不透明度可淡");
assert.deepEqual(fadeProperties(on(6 * T), asset("image")), ["opacity"]);
assert.ok(!fadeProperties(on(6 * T), asset("audio")).includes("opacity"), "任何情况下都不许在音频素材上递出画面手柄");
// 素材记录读不到（未导入的ghost）时界面不许自己发明一套：仍按「不是 audio 就有画面」走。
assert.deepEqual(fadeProperties(on(6 * T), null), ["opacity"]);

console.log(
  `PASS: 淡角柄的拖动量按网格对齐、被「片段长度 − 对面那头」夹住，夹点跟着片段与对面那头一起动；` +
    `${probes} 次拖动夹完再问检查器，一次都没有「按下去必定被引擎拒绝」`
);
