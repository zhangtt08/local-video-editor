/** 时间码那一栏的尺子：帧号与丢帧码都按「这一条交付画面的帧率」判，界面念的必须是同一把。

 1.137 让界面只负责把字符串交出去；1.140 发现「哪条率说了算」这件事界面也在猜——它把
 「帧号不能超过这条时间线的帧率」写在提示里，还用**时间线**的率去判分号丢帧码可不可用。
 引擎改了规矩之后，这两处不说真话了：选了 25 交付，提示还在讲 30 的事，那颗能用丢帧码的判断
 也跟着时间线走，于是界面说「可以用分号」而引擎拒。

 断三件事：① 面板算出 `effectiveRate`（选了交付率就是那一档，没选就是时间线那一档），
 提示与丢帧码判断都从它来；② 「这条时间线的帧率」那句旧话不许再出现在面板里；
 ③ 引擎那句中文提示也说清是「这一条交付画面的帧率」。
 */

// `REPO_ROOT` is defined by tests/desktop_ts_check.py at bundle time.
declare const REPO_ROOT: string;
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SRC = REPO_ROOT;
const panel = readFileSync(SRC + "desktop/src/views/ExportPanel.tsx", "utf8");
const engine = readFileSync(SRC + "desktop/src/engine.ts", "utf8");

assert.ok(/const effectiveRate = sendFps \?\? timelineRate;/.test(panel), "panel-uses-the-delivery-rate");
assert.ok(
  /const tcIsDropRate = tcDropRates\.some\(\s*\(\[n, d\]\) => n === effectiveRate\.numer/.test(panel),
  "drop-frame-judged-by-delivery-rate",
);
assert.ok(!panel.includes("这条时间线的帧率"), "panel-stale-timeline-wording");
assert.ok(!/tcDropRates[\s\S]{0,220}project\.settings\.frame_rate/.test(panel), "hint-not-recomputed-from-timeline");
assert.ok(panel.includes("是你选的交付率"), "panel-says-which-rate");
assert.ok(/帧号不能超过这一条交付画面的帧率/.test(engine), "engine-hint-names-the-delivery-picture");

// 时间码那一栏仍然只是把字交出去：界面不许自己写正则，也不许提前拦。
// 1.142 之后多了唯一一个例外：图像序列没有容器挂时间码，所以那一栏对它不起作用，
// 发出去的就是 null——「界面念的」与「真正发出去的」仍然是同一个值。
assert.ok(!/RegExp|\.test\(timecodeText\)|timecodeText\.match/.test(panel), "panel-writes-no-regex");
assert.ok(
  /const sendTimecode = isSequence \? null : timecodeText\.trim\(\) \|\| null;/.test(panel),
  "one-effective-value",
);

console.log(
  "PASS: 时间码的尺子跟着交付率——面板算出 effectiveRate，提示与「分号可用」都从它来，" +
    "旧的「这条时间线的帧率」那句话在面板里已不存在，引擎中文提示点名这一条交付的画面",
);
