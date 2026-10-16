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

/** 转过角度的遮罩盒，四个角在 0..100 画框里的位置（左上、右上、右下、左下）。
 *  `angle` 不给就用遮罩自己那一格；有窗表时调用方给的是此刻那一窗的角度。 */
export const rotatedCorners = (mask: ShapeMask, k: number, angle?: number) => {
  const rad = (angle ?? mask.rotation ?? 0) * Math.PI / 180;
  const cos = Math.cos(rad), sin = Math.sin(rad);
  return [[-1, -1], [1, -1], [1, 1], [-1, 1]]
    .map(([sx, sy]) => {
      const fx = sx * mask.width / 2, fy = sy * mask.height / 2;
      return `${((mask.center_x + fx * cos - fy * k * sin) * 100).toFixed(3)} ${((mask.center_y + fx * sin / k + fy * cos) * 100).toFixed(3)}`;
    })
    .join(", ");
};

/** 播放头落在哪一窗，就画哪一窗的那张图。
 *
 * 阶梯是引擎算的（`animation.mask_rotation_schedule`），这里只按 `to_ticks` 找格子——
 * 不插值、不自创中间态：界面在两窗之间画出的角度，就是导出在那一刻用的角度。
 * 落不进任何一窗时停在最后一窗（表尾之后如此；表头之前 `find` 本来就命中第一窗）。
 */
export const rotationWindowAt = <T extends { from_ticks: number; to_ticks: number }>(
  windows: T[], localTicks: number,
): T | null => {
  if (!windows.length) return null;
  return windows.find((window) => localTicks < window.to_ticks) ?? windows[windows.length - 1];
};

/**
 * 转过角度的盒，四条边的中点（上、右、下、左）在 0..100 画框里的位置，外加「上」那条向外法线。
 *
 * 换算与 `rotatedCorners` 同一套——参考线画的那一圈和手柄要落的那一点必须来自同一个盒，否则手柄
 * 抓在看见的边外面。这里只做落位，不做判断：能不能转、转到哪一格，仍然只在引擎与 store 那一头。
 */
/** 指针相对盒心的屏幕偏移 -> 该写成多少度：与 `rotatedEdgeMids` 用同一套除法。
 *
 * 茎画在哪是 `rotatedEdgeMids` 定的——它先按画幅比 k 把横向挪量变形，再乘上画框那一路的像素比例
 * a、d。所以读回来必须反着除：先除 a（或 d）落回 0..100 的框，再把那一步 k 的变形除掉。
 * 方形画幅（a=d、k=1）上这就等于 `atan2(dx, -dy)`，也就是旧行为一字不变。
 */
export const rotateAngleFromPointer = (dx: number, dy: number, a: number, d: number, k: number) =>
  Math.atan2(dx / (a * k), -(dy / d)) * 180 / Math.PI;

export const rotatedEdgeMids = (mask: ShapeMask, k: number, angle?: number) => {
  const rad = (angle ?? mask.rotation ?? 0) * Math.PI / 180;
  const cos = Math.cos(rad), sin = Math.sin(rad);
  const place = (fx: number, fy: number) => ({
    x: mask.center_x + fx * cos - fy * k * sin,
    y: mask.center_y + fx * sin / k + fy * cos,
  });
  const hw = mask.width / 2, hh = mask.height / 2;
  const top = place(0, -hh), right = place(hw, 0), bottom = place(0, hh), left = place(-hw, 0);
  const dx = top.x - mask.center_x, dy = top.y - mask.center_y, len = Math.hypot(dx, dy) || 1;
  return { top, right, bottom, left, out: { x: dx / len, y: dy / len } };
};
