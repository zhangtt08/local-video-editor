/** 「搬成边窗口」这颗按钮什么时候该亮——界面只判必要条件，判断仍然只有一处。
 *
 * 1.96 让 1.90 之前写在关键帧里的淡可以一条 `clip.fade_adopt` 搬到片段边上。界面要先决定「有没有
 * 可能」：按钮亮着而引擎必定拒绝，是 1.82 立下的规矩所禁止的；把引擎那条规则在界面里重写一遍，
 * 违反的是「一个行为只有一处权威实现」。于是 `fadeAdoptHint` 只断言一件必然成立的事——这条属性上
 * 至少有两个关键帧，且其中某个 `0.0` 正好落在片段自己的一条边上（搬回来的窗口就是从边上量起的，
 * 边上没有 0 就根本没有淡可搬）。
 */

import assert from "node:assert/strict";

import { fadeAdoptHint } from "../desktop/src/effects";
import type { Clip } from "../desktop/src/engine";

const T = 70_560_000;
const key = (property: string, at_ticks: number, value: number) => ({
  property,
  at_ticks,
  value,
  interpolation: "ease",
});
const clip = (keyframes: unknown[], offset = 0): Clip =>
  ({
    id: "c",
    asset_id: "a",
    track_id: "v",
    position_ticks: 0,
    source_in_ticks: 0,
    duration_ticks: 6 * T,
    animation_offset_ticks: offset,
    keyframes,
    fade: null,
  }) as unknown as Clip;

// 什么都没有：没有淡可搬。
assert.equal(fadeAdoptHint(clip([]), "opacity"), false, "空曲线不是淡");
// 只有一个点：那是一条平线，不是从 0 走到静止值的斜坡。
assert.equal(fadeAdoptHint(clip([key("opacity", 0, 0)]), "opacity"), false, "一个点不成斜坡");

// 老淡的样子：边上一个 0、斜坡尽头一个静止值。两头都算。
assert.equal(fadeAdoptHint(clip([key("opacity", 0, 0), key("opacity", T, 1)]), "opacity"), true);
assert.equal(
  fadeAdoptHint(clip([key("opacity", 5 * T, 1), key("opacity", 6 * T, 0)]), "opacity"),
  true,
  "淡出写在结尾那条边上"
);

// 0 在中间而两头都不是 0：那不是淡，是被人手拖到一半的东西，搬回来会得到一条引擎不认的窗口。
assert.equal(
  fadeAdoptHint(clip([key("opacity", 2 * T, 0), key("opacity", 3 * T, 1)]), "opacity"),
  false,
  "0 不在边上就不是边上的淡"
);
// 边上那个点不是 0（哪怕很接近 0）：引擎要求从 0 起步，界面不许替它放宽。
assert.equal(
  fadeAdoptHint(clip([key("opacity", 0, 0.001), key("opacity", T, 1)]), "opacity"),
  false,
  "0.001 不是 0"
);

// 两个属性各判各的：音量上的淡不该让画面那一行的按钮亮起来。
const gainOnly = [key("gain", 0, 0), key("gain", T, 1)];
assert.equal(fadeAdoptHint(clip(gainOnly), "opacity"), false, "音量的点不是画面的淡");
assert.equal(fadeAdoptHint(clip(gainOnly), "gain"), true);

// 裁过的片段：可见区间是 [offset, offset+duration]，边要按这个区间找。
const cropped = [key("opacity", 2 * T, 0), key("opacity", 3 * T, 1)];
assert.equal(fadeAdoptHint(clip(cropped, 2 * T), "opacity"), true, "裁过的片段边在 offset 上");
assert.equal(fadeAdoptHint(clip(cropped, 0), "opacity"), false, "没裁过就没有那条边");
assert.equal(
  fadeAdoptHint(clip([key("opacity", 8 * T, 0), key("opacity", 7 * T, 1)], 2 * T), "opacity"),
  true,
  "尾边是 offset + duration"
);

// 必要条件不是充分条件：这条属性上还夹着别的点，界面仍然亮着按钮——判断留给引擎，
// 引擎会用 FADE_ADOPT_SHAPE 点名说为什么搬不动。这里把它钉住，防止有人把规则搬进界面。
assert.equal(
  fadeAdoptHint(
    clip([key("opacity", 0, 0), key("opacity", T, 1), key("opacity", 2 * T, 0.4), key("opacity", 3 * T, 1)]),
    "opacity"
  ),
  true,
  "界面不许自己判「夹了别的点」"
);

console.log(
  "PASS: 按钮只在「这条属性至少两个点、且 0 落在片段自己的边上」时亮，两个属性互不混、裁过的边按 offset 找，充分性交给引擎"
);
