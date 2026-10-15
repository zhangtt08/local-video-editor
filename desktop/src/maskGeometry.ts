/**
 * 遮罩向导要画的那些几何：只把引擎已经定好的数换算成屏幕上的一处落笔，不做任何判断。
 *
 * 为什么单独一处：转过角度的遮罩盒，它的四个角不能直接在那张 0..100 的画框里转——画框是按画面
 * 非均匀拉伸的，直接把角度加上去，量出来的角度就不是人设定的那一个（这一点在这台机器上是量过的：
 * 同一张图非均匀拉过去，主轴角会挪）。所以先把盒角折成屏幕像素里的偏移，按屏幕角转，再各自除回
 * 比例。`k` 就是画面高/宽，与 `alpha_expression` 里那个比值说的同一件事；这里出的是一条参考线，
 * 导出与预览各自吃什么角度，仍然只在引擎那一处定。
 */

import type { ShapeMask } from "./engine";

/** 遮罩盒转过 `rotation` 之后，四个角在 0..100 画框里的位置（左上、右上、右下、左下）。 */
export const rotatedCorners = (mask: ShapeMask, k: number) => {
  const rad = (mask.rotation ?? 0) * Math.PI / 180;
  const cos = Math.cos(rad), sin = Math.sin(rad);
  return [[-1, -1], [1, -1], [1, 1], [-1, 1]]
    .map(([sx, sy]) => {
      const fx = sx * mask.width / 2, fy = sy * mask.height / 2;
      return `${((mask.center_x + fx * cos - fy * k * sin) * 100).toFixed(3)} ${((mask.center_y + fx * sin / k + fy * cos) * 100).toFixed(3)}`;
    })
    .join(", ");
};
