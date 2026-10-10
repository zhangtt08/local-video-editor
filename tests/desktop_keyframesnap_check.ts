/** 曲线的针落在哪一格：吸附认的是绝对帧格子，容差认的是屏幕像素。

 片段起点未必落在整帧上——`clips.move` 只把 `delta_ticks` 加上去，不像 `_place_clip` 会查
 TIME_NOT_ALIGNED，所以一次音画链接组的平移就能把画面片段停在帧格子之间。1.109 之前吸附按「片段
 本地 0 起算的整数倍帧」来数，针于是落在渲染时并不存在的那条线上：看着对齐，导出那一帧的值却来自
 上一帧。这一版把格子交给片段自己的位置，再谈吸附；顺手把达芬奇 / AE 的「找针」也接上——已有那一针
 靠手是点不准的。门禁要测的就是它真的按传进来的片段走：位置、长度、可见区间，一个都不许写死。
 */

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { keyframeTick, latticePhase } from "../desktop/src/keyframeSnap";

const TIMEBASE = 70_560_000;
const FRAME = Math.floor((TIMEBASE * 1001) / 30000);   // 29.97 fps：2 354 352 刻度
const SAMPLE = Math.floor(TIMEBASE / 48000);            // 48 kHz：1 470 刻度
const DURATION = FRAME * 5;                              // 11 771 760
const PLOT = 924;

assert.equal(FRAME, 2_354_352, "the engine's own 29.97 frame length: `//` in TS is a comment, not division");
assert.equal(SAMPLE, 1_470, "and its 48 kHz sample length");

/** `lattice(position, span)`：把「起点在帧格子之外的这一段」交给被测函数。 */
const lattice = (position: number, span = DURATION) => ({ clip: { position_ticks: position, duration_ticks: DURATION }, quantum: FRAME, span, plot: PLOT });
const none = { playhead: null, keys: [], attract: false };
const OFF = SAMPLE * 800;                               // 1 176 000：不在整帧上
const PHASE = FRAME - OFF;                              // 1 178 352：这一帧里第一条格线
const onFrame = (position: number, value: number) => (position + value) % FRAME === 0;

// 前提得先站得住：相位就是「把片段起点抬到整帧」差的那一段。
assert.equal(latticePhase(0, FRAME), 0, "a clip on the lattice needs no shift");
assert.equal(latticePhase(FRAME, FRAME), 0, "one whole frame in is still on the lattice");
assert.equal(latticePhase(0, 0), 0, "no quantum, no lattice");
assert.equal(latticePhase(OFF, FRAME), PHASE, "29.97 with a sample-shifted start is off by 1 178 352");
for (const at of [OFF, FRAME + SAMPLE * 7, DURATION - 1, OFF * 3]) {
  const shift = latticePhase(at, FRAME);
  assert.ok((at + shift) % FRAME === 0, `phase must land ${at} on a frame line`);
  assert.ok(shift >= 0 && shift < FRAME, "the phase is a remainder, not a whole lattice");
}
assert.equal(onFrame(OFF, 0), false, "this clip really does start between two frames");

// 落在帧格子上，而不是「从本地 0 数起的整数倍帧」上：旧写法这里给的是 0。
assert.equal(keyframeTick(1_000_000, lattice(OFF), true, none), PHASE, "a drag must land on the clip's own frame line");
assert.ok(onFrame(OFF, keyframeTick(1_000_000, lattice(OFF), true, none)), "and that tick is a real output frame");
assert.equal(keyframeTick(1_000_000, lattice(0), true, none), 0, "a clip at zero keeps the old answer");
assert.equal(keyframeTick(FRAME * 2 + 900_000, lattice(0), true, none), FRAME * 2, "under half a frame rounds back");
assert.equal(keyframeTick(FRAME * 2 + 1_200_000, lattice(0), true, none), FRAME * 3, "past half a frame rounds up");
// 换一段起点更靠后的片段，答案必须跟着换：格子是片段的位置算出来的，不是这里数出来的。
assert.notEqual(keyframeTick(1_000_000, lattice(OFF), true, none), keyframeTick(1_000_000, lattice(OFF + SAMPLE), true, none), "a one-sample slide must move the answer");

// 找针：Agent 写在格子之间的一根针，手抖那点距离不该把它推走。
const existing = 5_000_000;
const grab = { playhead: null, keys: [existing], attract: true };
assert.ok(!onFrame(OFF, existing), "the grabbed key sits off the lattice on purpose");
assert.equal(keyframeTick(existing + 30_000, lattice(OFF), true, grab), existing, "a drag stacks on the needle it lands on");
assert.equal(keyframeTick(existing + 30_000, lattice(OFF), true, none), 5_887_056, "without a needle the grid answers instead");

// 数值框与「播放头添加」要的就是那个精确位置：旁边有针也不许被拽走。
assert.equal(keyframeTick(existing + 30_000, lattice(OFF), true, { playhead: null, keys: [existing], attract: false }), 5_887_056, "the number box must not be dragged onto a neighbour");
assert.notEqual(keyframeTick(existing + 30_000, lattice(OFF), true, { playhead: null, keys: [existing], attract: false }), existing, "and that is the point of opting out");

// 播放头也是吸附对象，但落在片段之外时不该有吸引力——哪怕这一针就在手边。
assert.equal(keyframeTick(8_030_000, lattice(OFF), true, { playhead: 8_000_000, keys: [], attract: true }), 8_000_000, "the playhead grabs");
assert.equal(keyframeTick(DURATION - 2_000, lattice(OFF), true, { playhead: DURATION + 40_000, keys: [], attract: true }), 10_595_760, "a playhead past the clip must not pull, even within reach");
assert.equal(keyframeTick(40_000, lattice(OFF), true, { playhead: -6_000, keys: [], attract: true }), PHASE, "a playhead before the clip is not a target either");
// 播放头落在片段之外时也一样：针不许把点拽出可写区间。
assert.equal(keyframeTick(1_000, lattice(OFF), true, none), 0, "the nearest frame line is behind the head, so the drop parks at zero");
// 而针就在格线旁边时，落在格线上的那一下不许被针偷走：吸附是为「点不到」服务的，不是为「点得太准」捣乱。
assert.equal(keyframeTick(5_887_056, lattice(OFF), true, { playhead: null, keys: [5_927_056], attract: true }), 5_887_056, "a needle four pixels away must not steal a drop that is right on a frame line");

// 容差是屏幕像素，不是刻度数：放大八倍后同样偏 40 000 刻度就不该再吸上去。
assert.equal(keyframeTick(existing + 40_000, lattice(OFF), true, grab), existing, "at full zoom four pixels reach the needle");
assert.equal(keyframeTick(existing + 40_000, lattice(OFF, DURATION / 8), true, grab), 5_887_056, "eight times the zoom narrows the grab in ticks");
assert.equal(keyframeTick(existing + 6_000, lattice(OFF, DURATION / 8), true, grab), existing, "and four pixels at that zoom still reach it");

// 关掉吸附就一个格子都不许掺进去。
assert.equal(keyframeTick(3_000_000.4, lattice(OFF), false, grab), 3_000_000, "off means the nearest whole tick");
assert.ok(!onFrame(OFF, 3_000_000), "and that tick really is off the frame line");
assert.equal(keyframeTick(3_000_000.4, lattice(OFF), true, none), 3_532_704, "on means the lattice answers, not the raw pointer");

// 上下界在吸附之后才夹：越界的落点绝不能写出去（reducer 按 duration_ticks 拒绝）。
for (const at of [-FRAME * 3, -1, 0, DURATION - 1, DURATION, DURATION + 1, DURATION + FRAME * 4]) {
  for (const enabled of [true, false]) {
    for (const attract of [true, false]) {
      const value = keyframeTick(at, lattice(OFF), enabled, { playhead: DURATION + 9_000, keys: [existing], attract });
      assert.ok(Number.isInteger(value) && value >= 0 && value <= DURATION, `${at} → ${value} must stay writable`);
    }
  }
}
// 落在区间内的答案只有三种来源：格线、被点到的那根针、片段两头——不存在「凭空一个刻度」。
for (let at = 0; at <= DURATION; at += 37_777) {
  const value = keyframeTick(at, lattice(OFF), true, grab);
  assert.ok([0, DURATION, existing].includes(value) || onFrame(OFF, value), `${at} → ${value} came from nowhere`);
}

// 接上线才作数：格子由片段算出来，精确落点的那三个入口得自己退出吸附。
const path = ["desktop/src/views/CurveEditor.tsx", "src/views/CurveEditor.tsx"].map((part) => resolve(process.cwd(), part)).find(existsSync);
assert.ok(path, "the curve editor must be readable from the check's working directory");
const source = readFileSync(path!, "utf8");
assert.match(source, /keyframeTick\(at, \{ clip, quantum: q, span, plot: WIDTH \}/, "the grid is computed from the clip, not from a number typed here");
const drag = source.split("\n").find((row) => row.includes("gesture.point.at_ticks + dx"));
assert.ok(drag && /alignTime\(/.test(drag) && !/, false\)/.test(drag), "the drag must be the grabbing gesture");
for (const [what, pattern] of [
  ["数值框", /alignTime\(value\*TIMEBASE, false\)/],
  ["播放头添加", /add\(head, sample\.values\[field\.property\], false\)/],
  ["标尺 seek", /seek\(alignTime\([^\n]*, false\)\)/],
] as const) {
  assert.ok(pattern.test(source), `${what} must keep its exact position`);
}
// 不许有第二份吸附算术：所有落点都得从 alignTime 出去（入口数量会变，这条不变量才不会过时）。
assert.ok(!/Math\.round\(at \/ q\) \* q/.test(source), "no second snapping formula may live in the curve editor");
assert.ok(!/Math\.round\([^)\n]*\) \/ TIMEBASE/.test(source) || /alignTime\(/.test(source), "time entries go through the helper");
assert.ok((source.match(/alignTime\(/g) ?? []).length >= 4, "every entry point goes through the one helper");

console.log(
  "PASS: 曲线的针落在片段自己的帧边界上——起点不在整帧时也落在帧上、放大八倍容差按像素收窄、"
    + "Agent 写在格子之间的针接得住拖动、数值框与播放头照精确位置写、越界先吸附再夹回可写区间",
);
