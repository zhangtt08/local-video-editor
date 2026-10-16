/** 1.181：旋转手柄读回的角度必须与茎画出去的那一套换算同一条式子。
 *
 * 茎的位置来自 `rotatedEdgeMids(body, k, angle)`：先把横向挪量按画幅比 k 变形，再由 SVG 的 CTM 乘上
 * a、d 落到屏幕。旧 `angleOf` 读的是纯屏幕角 `atan2(dx, -dy)`，两套换算不相逆，于是「拖多少」与
 * 「看见多少」成了两件事（1.180 收尾在真实尺寸上量到：指针沿屏幕 +30°，茎只走 +3.63°）。
 *
 * 钉四件事，逐条可反证：
 * - **往返**：任给一个盒角度，先按 `rotatedEdgeMids` 算出茎在框里的偏移、再按 a/d 乘成屏幕偏移，
 *   交给 `rotateAngleFromPointer` 必须原样读回那个盒角度（±1e-6）。这条就是「指针落在茎上」。
 * - **方形画幅不变**：a=d 且 k=1 时它与旧式子 `atan2(dx,-dy)` 一字不差——没有拉伸就没有改写。
 * - **旧式子在这里量得出错**：拿实测那一台的 a=4.148 / d=8.266 / k=9/16，屏幕 30° 与茎的角度差
 *   必须 > 5°，否则这份检根本看不见被修掉的那个缺陷。
 * - **调用点**：`MaskPicture.tsx` 里 `angleOf` 真的走这个函数，旧那句屏幕 atan2 不再出现。
 */
import assert from "node:assert";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { rotateAngleFromPointer, rotatedEdgeMids, type ShapeMask } from "../desktop/src/maskGeometry";

declare const REPO_ROOT: string;

const wrap = (deg: number) => {
  let value = deg;
  while (value <= -180) value += 360;
  while (value > 180) value -= 360;
  return value;
};

const mask = { shape: "rectangle", center_x: 0.5, center_y: 0.5, width: 0.5, height: 0.3 } as ShapeMask;
const aMeasured = 4.148;
const dMeasured = 8.266;
const kMeasured = 9 / 16;

// ① 往返：茎画在哪儿，指针就该读回那个角度
for (const angle of [-170, -90, -30, -0.1, 0, 7.5, 30, 90, 150]) {
  const mid = rotatedEdgeMids(mask, kMeasured, angle);
  const dx = (mid.top.x - mask.center_x) * 100 * aMeasured;
  const dy = (mid.top.y - mask.center_y) * 100 * dMeasured;
  const read = wrap(rotateAngleFromPointer(dx, dy, aMeasured, dMeasured, kMeasured));
  const want = wrap(angle);
  assert.ok(
    Math.abs(wrap(read - want)) < 1e-6,
    `茎在 ${want}° 那里，指针读回来却是 ${read}°——手柄会跳，落笔也不是看见的那一格`,
  );
}

// ② 方形画幅（a=d、k=1）：与旧式子一字不差
for (const [sx, sy] of [[12, -200], [-77, -33], [0, -50], [200, 90]] as [number, number][]) {
  const legacy = (Math.atan2(sx, -sy) * 180) / Math.PI;
  assert.ok(
    Math.abs(rotateAngleFromPointer(sx, sy, 5, 5, 1) - legacy) < 1e-9,
    "没有拉伸时这一版改了旧行为：方形画幅上它必须等于 atan2(dx, -dy)",
  );
}

// ③ 旧式子在这台的各向异性上量得出错（否则这份检看不见被修的缺陷）
const oldScreenAngle = (dx: number, dy: number) => (Math.atan2(dx, -dy) * 180) / Math.PI;
let worst = 0;
for (const angle of [-60, -30, 30, 60, 90]) {
  const mid = rotatedEdgeMids(mask, kMeasured, angle);
  const dx = (mid.top.x - mask.center_x) * 100 * aMeasured;
  const dy = (mid.top.y - mask.center_y) * 100 * dMeasured;
  worst = Math.max(worst, Math.abs(wrap(angle - wrap(oldScreenAngle(dx, dy)))));
}
assert.ok(worst > 5, `旧式子与茎的角度只差 ${worst.toFixed(2)}°，这份检根本量不到那个缺陷`);

// ④ 调用点：angleOf 走的是同一处换算，旧那句屏幕 atan2 不许留下
const guide = readFileSync(join(REPO_ROOT, "desktop/src/views/MaskPicture.tsx"), "utf8");
assert.ok(guide.includes("rotateAngleFromPointer("), "angleOf 没调用那处换算——修在了没人走的路上");
assert.ok(
  !guide.includes("return Math.atan2(px, -py) * 180 / Math.PI;"),
  "旧的屏幕角式子还在：屏幕上拖多少与茎看见多少又会分家",
);
const geometry = readFileSync(join(REPO_ROOT, "desktop/src/maskGeometry.ts"), "utf8");
assert.ok(
  geometry.indexOf("rotateAngleFromPointer") < geometry.indexOf("export const rotatedEdgeMids") ||
    geometry.includes("export const rotateAngleFromPointer"),
  "换算不在 maskGeometry 里——落位与读回必须同出一处",
);

console.log(
  `PASS: 旋转手柄读回的角度与 ${"茎"}画出去的那一套换算互逆（九格往返 <1e-6、方形画幅一字不变、` +
    `旧式子在这台的各向异性上最大差 ${worst.toFixed(1)}°），并且调用点就是这一处`,
);
