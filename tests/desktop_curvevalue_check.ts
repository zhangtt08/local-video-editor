/** 曲线编辑器「拖一下」的算术：先量化到这条属性的步长，再整组按量程与片段两头夹，最后逐枚落值。

 这一层判断此前只写在 `CurveEditor.tsx` 里，没有纯函数可以单测——也就是**只有实测、没有门禁**。
 1.116 之后装机量过两次（一条片段上不透明度 0.5 与 0.9 两枚一起拖，两个方向都拖）：落库的都是
 `0.6 / 1.0`。抓 0.5 那枚想拖到 1.4 并没有被单独写出去，整组按「离上限最近的那一枚只剩 0.1」一起
 只走 0.1；反过来抓 0.9 那枚也是同一式子。这里就把那两次的读数当夹具，把抽出来的纯模块逐条钉住，
 并断界面真的读的是这个模块、没留下第二份算术。行为一字未改，改的是它有没有红灯可看。
 */

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { applyShift, bandEdges, groupShift, quantizeToBand } from "../desktop/src/curveDrag";

const TIMEBASE = 70_560_000;
// 检查器里那条「不透明度」那一行下发的带：0–100 %，步长 1，存的是 0..1。
const OPACITY = { min: 0, max: 100, step: 1, factor: 100 };
const ROTATION = { min: -360, max: 360, step: 1, factor: 1 };
const BLUR = { min: 0, max: 25, step: 0.5, factor: 100 };   // 1.99 起柔焦按画面高的百分比

// 带换算只有一处：界面说「百分数」，工程存归一化值。
assert.deepEqual(bandEdges(OPACITY), { hardMin: 0, hardMax: 1 }, "the band edges are the field's own numbers divided");
assert.deepEqual(bandEdges(ROTATION), { hardMin: -360, hardMax: 360 }, "a factor of 1 leaves the band as written");

// 量化：落到这条属性的步长格子上，并且永远被量程夹住。
assert.equal(quantizeToBand(0.33333, OPACITY), 0.33, "0.33333 % 的东西按 1 % 步长落到 33 %");
assert.equal(quantizeToBand(0.9, OPACITY), 0.9, "already on the grid stays put");
assert.equal(quantizeToBand(1.4, OPACITY), 1, "past the ceiling is clamped, not wrapped");
assert.equal(quantizeToBand(-0.2, OPACITY), 0, "below the floor the same");
assert.equal(quantizeToBand(12.6, ROTATION), 13, "rotation is in whole degrees");
assert.equal(quantizeToBand(-500, ROTATION), -360, "and inside its own band");
assert.equal(quantizeToBand(0.123, BLUR), 0.125, "a half-percent step rounds to the half, not to the whole");

const DURATION = 8 * TIMEBASE;
const pair = [{ at_ticks: 2 * TIMEBASE, value: 0.5 }, { at_ticks: 5 * TIMEBASE, value: 0.9 }];

// 装机实测的第一次：抓 0.5 那枚往上拖一大截（指针想去 1.4），整组只走 0.1。
const up = groupShift(pair, OPACITY, DURATION, 0, 0.9);
assert.equal(up.dt, 0, "a pure vertical drag asks for no time shift");
assert.ok(Math.abs(up.dv - 0.1) < 1e-12, `the whole group is limited by the needle closest to the ceiling: ${up.dv}`);
assert.deepEqual(applyShift(pair, up, OPACITY), [
  { at_ticks: 2 * TIMEBASE, value: 0.6 },
  { at_ticks: 5 * TIMEBASE, value: 1 },
], "and that is exactly the pair the shipped app wrote: 0.6 and 1.0");
// 上面那对数字同时钉住一件事：整组的余量由 `1 - 0.9` 减出来，二进制里是 0.09999999999999998，
// 不在格子上。草稿必须再过一次格子——否则「界面写出的数」与「引擎存的数」是两份东西。
assert.deepEqual(applyShift(pair, { dt: 0, dv: 1 - 0.9 }, OPACITY).map((point) => point.value), [0.6, 1],
  "a drifting group shift still lands the needles on the property's own grid");

// 第二次（反过来抓 0.9 那枚）读数同一条式子——这一对数字就是「整组夹」而不是「逐枚夹」的证据。
const otherShift = groupShift(pair, OPACITY, DURATION, 0, quantizeToBand(1.8, OPACITY) - 0.9);
assert.ok(Math.abs(otherShift.dv - 0.1) < 1e-12, "grabbing the upper needle gives the same group room");
assert.deepEqual(applyShift(pair, otherShift, OPACITY).map((point) => point.value), [0.6, 1], "and the same pair lands");

// 向下也一样：整组能走多远由**离下界最近**的那一枚决定（这里 0.5 只剩半格的下限余量）。
const down = applyShift(pair, groupShift(pair, OPACITY, DURATION, 0, -0.7), OPACITY);
assert.equal(groupShift(pair, OPACITY, DURATION, 0, -0.7).dv, -0.5, "the lower needle's room to the floor caps the whole group");
assert.deepEqual(down.map((point) => point.value), [0, 0.4], "so 0.7 down becomes 0.5 down, both still inside the band");

// 时间通道同一层道理：整组不许越出片段两头。
const late = groupShift(pair, OPACITY, DURATION, 4 * TIMEBASE, 0);
assert.equal(late.dt, 3 * TIMEBASE, "the last needle's room decides how far the group may slide");
const early = groupShift(pair, OPACITY, DURATION, -6 * TIMEBASE, 0);
assert.equal(early.dt, -2 * TIMEBASE, "and the first one's room decides the other way");
const slid = applyShift(pair, late, OPACITY);
assert.deepEqual(slid.map((point) => point.at_ticks), [5 * TIMEBASE, 8 * TIMEBASE], "both land inside the clip, spacing intact");

// 一整轮扫描：无论指针要多少，交出去的时间与数值都必须在可写的带里——这就是「界面允许、导出会拒」的反面。
// 同时每一条结果都必须**还在这条属性的格子上**（`value === quantizeToBand(value)`）：整组的余量是减法
// 减出来的，不在格子上的草稿就等于让引擎替我们收拾——1.117 把格子放回这一处，草稿即落库的那份。
for (const raw of [-9, -1.4, -0.31, 0, 0.07, 0.5, 1.4, 7]) {
  for (const dt of [-11 * TIMEBASE, -TIMEBASE, 0, TIMEBASE, 11 * TIMEBASE]) {
    const shift = groupShift(pair, OPACITY, DURATION, dt, raw);
    for (const point of applyShift(pair, shift, OPACITY)) {
      assert.ok(point.at_ticks >= 0 && point.at_ticks <= DURATION, `${dt}/${raw} put a needle at ${point.at_ticks}`);
      assert.ok(point.value >= 0 && point.value <= 1, `${dt}/${raw} put a value at ${point.value}`);
      assert.ok(Number.isFinite(point.value), "and never a NaN the reducer would reject");
      assert.equal(point.value, quantizeToBand(point.value, OPACITY), `${dt}/${raw} drafted ${point.value}, off the 1 % grid`);
    }
  }
}

// 步长不是整数百分比的那条属性（柔焦按 0.5 % 一格）：减法漂移会写出 0.17499999999999999 这种不在格子上的数。
const BLUR_PAIR = [{ at_ticks: TIMEBASE, value: 0.125 }, { at_ticks: 3 * TIMEBASE, value: 0.2 }];
const blurShift = groupShift(BLUR_PAIR, BLUR, DURATION, 0, quantizeToBand(0.5, BLUR) - 0.125);
const landed = applyShift(BLUR_PAIR, blurShift, BLUR);
for (const point of landed) {
  assert.equal(point.value, quantizeToBand(point.value, BLUR), `a half-percent band must land on the half: ${point.value}`);
  assert.ok(point.value <= 0.25, "and inside the band the engine gave us");
}

// 空选区不许炸（Math.min(...[]) 是 +Infinity，那条式子会把 NaN 交出去）。
assert.deepEqual(groupShift([], OPACITY, DURATION, TIMEBASE, 0.5), { dt: 0, dv: 0 }, "an empty selection shifts nothing");

// 接上线：组件读这个模块，且不许留下第二份算术。
const path = ["desktop/src/views/CurveEditor.tsx", "src/views/CurveEditor.tsx"].map((part) => resolve(process.cwd(), part)).find(existsSync);
assert.ok(path, "the curve editor must be readable from the check's working directory");
const source = readFileSync(path!, "utf8");
assert.match(source, /import \{ applyShift, bandEdges, groupShift, quantizeToBand \} from "\.\.\/curveDrag";/, "the editor reads the one module");
assert.match(source, /const translate = \(points: Keyframe\[\], dt: number, dv: number\) => applyShift\(points, groupShift\(points, band, clip\.duration_ticks, dt, dv\), band\);/, "the drag goes through group-then-apply, in that order");
assert.match(source, /const quantizeValue = \(value: number\) => quantizeToBand\(value, band\);/, "and the value grid is the module's");
assert.ok(!/Math\.max\(hardMin-Math\.min\(/.test(source), "no second copy of the band clamp may live in the editor");
assert.ok(!/Math\.round\(value \* field\.factor/.test(source), "no second copy of the quantization either");
// 拖动仍然只有那一条式子：时间走 alignTime（1.109 的格子），数值走这个模块的量化——两处各一处。
assert.match(source, /translate\(gesture\.points, alignTime\(gesture\.point\.at_ticks \+ dx \/ WIDTH \* span\)-gesture\.point\.at_ticks, quantizeValue\(gesture\.point\.value - dy \/ HEIGHT \* valueSpan\)-gesture\.point\.value\)/, "the pointer is read through the shared time grid and this value grid");

console.log(
  "PASS: 曲线的拖拽算术只有一处——先按这条属性的步长量化、再整组按量程与片段两头夹、最后逐枚落值；"
    + "夹具就是装机量到的那两个方向（0.5/0.9 一起拖成 0.6/1.0），空选区与极端指针都交不出越界的数",
);
