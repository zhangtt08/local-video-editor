/** 淡入淡出的两行数字：上限只有一个主人，就是片段自己的长度。

 1.90 之前淡写成关键帧，「淡入再点淡出」会把前者抹掉；现在淡是片段两条边上的窗口（`Clip.fade`）。
 界面这边只做两件事：把四个窗口读出来，以及在按下之前算一遍「这一头加上另一头还剩多少」。
 门禁要钉的是它真的听片段 length 与对面那头的数——换一段更长的片段、或把对面那头缩短，同一串
 输入必须从不放行变成放行；否则就等于界面又自己写死了一个上限（1.87 那个 300 就是这么藏住的）。
 */

import assert from "node:assert/strict";

import { fadeBlocker, fadeWindows } from "../desktop/src/effects";
import type { Clip } from "../desktop/src/engine";

const T = 70_560_000;
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

// 没有 fade 记录（v13 的工程，或从没淡过的片段）：四头都是 0，界面不许自己发明默认淡。
const bare = fadeWindows(clip(6 * T));
assert.deepEqual(bare, { opacity: { in: 0, out: 0 }, gain: { in: 0, out: 0 } }, bare);

const read = fadeWindows(
  clip(6 * T, { opacity_in_ticks: T, opacity_out_ticks: 2 * T, gain_in_ticks: 0, gain_out_ticks: 3 * T })
);
assert.deepEqual(read, { opacity: { in: T, out: 2 * T }, gain: { in: 0, out: 3 * T } }, read);

// 放得下就放行：一头单独超过片段长度才算放不下。
assert.equal(fadeBlocker(clip(6 * T), "opacity", "in", 5 * T), null);
assert.equal(fadeBlocker(clip(6 * T), "gain", "out", 6 * T), null, "整段淡出是合法的");

// 两头一起超了：句子必须点名还剩多少，而那个数是「片段长度 − 对面那头」。
const blocked = fadeBlocker(clip(6 * T, { gain_in_ticks: 2 * T, gain_out_ticks: 0 }), "gain", "out", 5 * T);
assert.ok(blocked, "2s 淡入之后再来 5s 淡出必须被拦下");
assert.match(blocked, /[一-鿿]/, "理由必须是中文");
assert.ok(blocked!.includes("4.00"), `还剩多少要说清（6 − 2 = 4 秒）：${blocked}`);
assert.ok(blocked!.includes("剪长"), `出路得有一条真走得通：${blocked}`);
assert.ok(blocked!.includes("对面"), `另一条出路是缩短对面那头：${blocked}`);

// 数不是写死的：同一次输入，换一段更长的片段就放行。
assert.equal(fadeBlocker(clip(8 * T, { gain_in_ticks: 2 * T }), "gain", "out", 5 * T), null);
// 对面那头缩一半，余量就涨一半——它听的是 fade 记录，不是界面自己记的一份。
assert.equal(fadeBlocker(clip(6 * T, { gain_in_ticks: T }), "gain", "out", 5 * T), null, "1 + 5 正好放得下");
const halved = fadeBlocker(clip(6 * T, { gain_in_ticks: T }), "gain", "out", 5.5 * T);
assert.ok(halved, "1 + 5.5 就放不下");
assert.ok(halved!.includes("5.00"), `只剩 1 秒淡入时这一头还能要 5 秒：${halved}`);

// 两属性各算各的：淡入的音量不占画面的额度。
assert.equal(fadeBlocker(clip(6 * T, { gain_in_ticks: 5 * T }), "opacity", "out", 5 * T), null);

console.log(
  "PASS: 淡的额度只有一个主人——片段长度减去对面那头；换长度、换对面那头，放行与那句余量都跟着变，" +
    "两个属性互不占用"
);
