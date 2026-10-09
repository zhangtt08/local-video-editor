/** 预览里那条擦除的边，必须与成片那条斜坡共用同一个中点。
 *
 * 导出在 alpha 上算一条宽 `feather` 的斜坡（`transitions.wipe_expression`），浏览器只能给一条硬边。
 * 硬边取斜坡的中点：`progress*(1+feather) - feather/2`。进度、轴、方向、羽化宽四个数全部由引擎
 * 下发——界面不许自备第二张「名字→方向」的表，也不许自己写 0.02（1.87 那个 300 就是这么藏住的）。
 *
 * 最硬的一条不是逐个数值，而是一个不变量：同一个进度下，进来的那层露出的比例与出去的那层露出的
 * 比例必须**恰好加起来等于整幅画面**。这正是导出用互补 alpha 保证的事；哪一天界面把方向或中点
 * 算错，这个和就会不等于 1，两边立刻对不上。
 */

import assert from "node:assert/strict";

import { wipeClipPath } from "../desktop/src/effects";
import type { WipeChannel } from "../desktop/src/engine";

const FEATHER = 0.02;

const wipe = (kind: string): WipeChannel => ({
  kind,
  invert: false,
  axis: kind.includes("_left") || kind.includes("_right") ? "x" : "y",
  flipped: kind.includes("_right") || kind.includes("_bottom"),
  feather: FEATHER,
  curve: [],
});

const inset = (path: string): number[] =>
  path.match(/inset\(([^)]+)\)/)![1].split(/\s+/).map((part) => Number.parseFloat(part) / 100);

const visible = (path: string): number => {
  const [top, right, bottom, left] = inset(path);
  return 1 - (top + bottom || left + right);
};

// 中点：进度一半时，边就在画面正中——不是 51%，也不是 49%。
assert.equal(wipeClipPath(wipe("wipe_from_left"), 0.5), "inset(0 50% 0 0%)", wipeClipPath(wipe("wipe_from_left"), 0.5));
// 窗口两端：一边什么都没有，另一边是整幅画面（越界的那半个百分点要被夹回来）。
assert.equal(wipeClipPath(wipe("wipe_from_left"), 0), "inset(0 100% 0 0%)");
assert.equal(wipeClipPath(wipe("wipe_from_left"), 1), "inset(0 0% 0 0%)");

// 方向：从右擦除露出的是右半边，从上露出上边，从下露出下边。
assert.equal(wipeClipPath(wipe("wipe_from_right"), 0.5), "inset(0 0% 0 50%)");
assert.equal(wipeClipPath(wipe("wipe_from_top"), 0.5), "inset(0% 0 50% 0)");
assert.equal(wipeClipPath(wipe("wipe_from_bottom"), 0.5), "inset(50% 0 0% 0)");

// 四分之一处：中点跟着进度走，且带的是引擎那个羽化宽的一半偏移（0.25*1.02 − 0.01 = 0.245）。
assert.equal(wipeClipPath(wipe("wipe_from_left"), 0.25), "inset(0 75.5% 0 0%)");

// 最硬的一条：同一个进度下，两层露出的比例恰好铺满整幅画面，既不留缝也不重叠。
for (const kind of ["wipe_from_left", "wipe_from_right", "wipe_from_top", "wipe_from_bottom"]) {
  for (const progress of [0, 0.1, 0.25, 0.5, 0.75, 0.9, 1]) {
    const base = wipe(kind);
    const incoming = wipeClipPath(base, progress);
    const outgoing = wipeClipPath({ ...base, invert: true }, progress);
    const sum = visible(incoming) + visible(outgoing);
    assert.ok(Math.abs(sum - 1) < 1e-9, `${kind} @${progress}: 两层露出 ${visible(incoming)} + ${visible(outgoing)} = ${sum}，不是整幅画面`);
    const hidden = (path: string) => inset(path).reduce((total, value) => total + value, 0);
    assert.ok(Math.abs(hidden(incoming) + hidden(outgoing) - 1) < 1e-9, `${kind} @${progress}: 被遮的两半也该凑成整幅`);
  }
}

// 引擎哪天改了羽化宽，界面必须跟着动：feather=0 时边就落在 progress 上；
// 宽羽化 0.2 时中点是 0.25×1.2 − 0.1 = 0.2，也就是露出到 20%。
assert.equal(wipeClipPath({ ...wipe("wipe_from_left"), feather: 0 }, 0.25), "inset(0 75% 0 0%)");
assert.equal(wipeClipPath({ ...wipe("wipe_from_left"), feather: 0.2 }, 0.25), "inset(0 80% 0 0%)");

console.log(
  "PASS: 预览那条硬边走的是引擎斜坡的中点（0.5 → 画面正中），四个方向各就各位，" +
    "同一进度下两层露出的比例恰好铺满整幅画面，羽化宽换了数也跟着动"
);
