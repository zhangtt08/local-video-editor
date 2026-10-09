/** 1.98：预览那一层 `filter` 的动画帧，必须由引擎下发的窗表原样换算，不许自己插值。
 *
 * 柔焦以前不能打关键帧，理由是「导出成阶梯、预览平滑插值」。这一版的答案是让阶梯成为唯一的权威：
 * 引擎把曲线切成一格一步的窗（`spatial_schedule`），导出串成 `gblur … :enable='between(t,…)'`，
 * 浏览器动画同一份窗。这条门禁管的是浏览器那半步：数与段边界照抄，单位换成 cqh，没有窗就没有动画。
 */

import assert from "node:assert/strict";

import { blurFrames } from "../desktop/src/effects";

// 没有曲线：一段都不编，界面不替静态那条路造第二套规则。
assert.deepEqual(blurFrames(null), [], "没有窗就不该有动画帧");
assert.deepEqual(blurFrames(undefined), []);
assert.deepEqual(blurFrames([]), []);

// 有窗：逐段一帧，值按「占画面高的比例」写成 cqh，偏移与 easing 原样带过去。
const issued = [
  { offset: 0, value: 0.02, easing: "steps(1, end)" },
  { offset: 0.5, value: 0.06, easing: "steps(1, end)" },
  { offset: 0.75, value: 0.1, easing: "steps(1, end)" },
];
assert.deepEqual(blurFrames(issued), [
  { filter: "blur(2cqh)", offset: 0, easing: "steps(1, end)" },
  { filter: "blur(6cqh)", offset: 0.5, easing: "steps(1, end)" },
  { filter: "blur(10cqh)", offset: 0.75, easing: "steps(1, end)" },
]);

// 段数与偏移不许变：多加一段、少一段、把 easing 换成 linear，都会让预览出现导出没有的中间态。
const frames = blurFrames(issued);
assert.equal(frames.length, issued.length);
assert.deepEqual(frames.map((frame) => frame.offset), issued.map((window) => window.offset));
assert.deepEqual(frames.map((frame) => frame.easing), issued.map((window) => window.easing));
// 0 也要照写：那一段是「不糊」，不是「没有这一段」。
assert.equal(blurFrames([{ offset: 0, value: 0, easing: "steps(1, end)" }])[0].filter, "blur(0cqh)");

console.log("PASS: 预览的柔焦动画帧逐段照抄引擎的窗表（值换成 cqh、偏移与 steps easing 不动），没有窗就没有动画");
