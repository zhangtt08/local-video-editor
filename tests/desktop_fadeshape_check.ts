/** 淡的形状下拉列的必须是引擎那张表，一个名字都不许多。
 *
 * 1.95 给每条属性的两头一个形状（线性 / 缓入 / 缓出 / 缓入缓出）。名字与中文标签由
 * `capabilities.fade_shapes` 下发——与转场种类同一条规矩：界面不许自己写四个字符串，
 * 否则「引擎还不认这个形状」的按钮会亮着（1.82 立下的规矩）。
 *
 * 门禁钉三件事：老引擎不回这张表时一个选项都没有（那一行根本不出现）；回了就原样列出、
 * 顺序也是引擎的；混进来的未知 id 要丢掉，而不是跟着画出一个按下去必被拒的选项。
 */

import assert from "node:assert/strict";

import { fadeShape, fadeShapeChoices } from "../desktop/src/effects";
import type { Clip } from "../desktop/src/engine";

const T = 70_560_000;
const clip = (fade?: Clip["fade"]): Clip =>
  ({
    id: "c",
    asset_id: "a",
    track_id: "v",
    position_ticks: 0,
    source_in_ticks: 0,
    duration_ticks: 6 * T,
    fade: fade ?? null,
  }) as Clip;

// 老引擎：没有这张表就没有这一行。界面不许凭记忆列出四个名字。
assert.deepEqual(fadeShapeChoices(null), [], "caps 还没回来时不许有选项");
assert.deepEqual(fadeShapeChoices({}), [], "引擎没下发 fade_shapes 就不许出现这一行");
assert.deepEqual(fadeShapeChoices({ fade_shapes: [] }), []);

// 新引擎：原样列出，顺序也是引擎的（引擎把 linear 排第一，界面不许按字母重排）。
const issued = {
  fade_shapes: [
    { id: "linear", label: "线性" },
    { id: "ease_in", label: "缓入" },
    { id: "ease_out", label: "缓出" },
    { id: "ease_in_out", label: "缓入缓出" },
  ],
};
assert.deepEqual(fadeShapeChoices(issued), issued.fade_shapes, "表要一字不动地交给界面");

// 未知 id 丢掉：画出一个引擎不认的选项，就是递给用户一个按下去必被拒的按钮。
assert.deepEqual(
  fadeShapeChoices({ fade_shapes: [...issued.fade_shapes, { id: "bounce", label: "弹性" }] }),
  issued.fade_shapes,
  "引擎没实现的名字不许出现在下拉里"
);

// 读数取自工程状态；引擎没下发形状字段时读回缓入缓出（那正是 1.95 之前唯一的形状）。
assert.equal(fadeShape(clip(), "opacity"), "ease_in_out", "没有 fade 记录就是默认形状");
assert.equal(fadeShape(clip({ opacity_in_ticks: T, opacity_out_ticks: 0, gain_in_ticks: 0, gain_out_ticks: 0 }), "gain"), "ease_in_out");
assert.equal(fadeShape(clip({ opacity_shape: "linear", opacity_in_ticks: T, opacity_out_ticks: 0, gain_in_ticks: 0, gain_out_ticks: 0 }), "opacity"), "linear");
// 两个属性各读各的：画面的形状不许被当成音量的形状。
assert.equal(
  fadeShape(
    clip({ opacity_shape: "ease_in", gain_shape: "ease_out", opacity_in_ticks: T, opacity_out_ticks: 0, gain_in_ticks: 0, gain_out_ticks: 0 }),
    "gain"
  ),
  "ease_out"
);

console.log("PASS: 形状下拉列的就是 capabilities.fade_shapes（老引擎一个选项都没有、未知 id 被丢掉），读数取自工程状态且两个属性互不混");
