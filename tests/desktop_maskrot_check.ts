/** 1.164「遮罩可旋转」界面这一侧：角度只在引擎里换算，界面只许画参考线和平移那张图。

 这一档要挡的三种错和 1.115、1.163 撞过的是同三种：
 ① 界面自己再算一份旋转（两条腿各算各的，量出来的是话不是画面）；
 ② 把一条导出会拒的曲线摆到人面前（转过的盒子能给宽高打关键帧，红的是画面上那条斜坡）；
 ③ 界面自带一个角度上限（引擎改了数字界面还在说 360，那是抄的）。
 所以这里既量那张参考线的数学（它在屏幕像素意义上必须真的转了），也读源码数那几处接线。
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { maskAnimFields } from "../desktop/src/effects";
import type { ShapeMask } from "../desktop/src/engine";
import { rotatedCorners } from "../desktop/src/maskGeometry";

declare const REPO_ROOT: string;

const read = (rel: string) => readFileSync(`${REPO_ROOT}/${rel}`, "utf-8");
const box = (extra: Partial<ShapeMask>): ShapeMask => ({
  shape: "ellipse", center_x: 0.5, center_y: 0.5, width: 0.4, height: 0.4,
  feather: 0, inverted: false, vertices: null, ...extra,
});
const points = (mask: ShapeMask, k: number) => rotatedCorners(mask, k).split(", ").flatMap((pair) => pair.split(" ").map(Number));

// ① 曲线名单：转过的盒子只剩两条中心曲线，没转的还是四条（两个方向都要成立）
assert.deepEqual(maskAnimFields(box({}))!.map((row) => row.property),
  ["mask_x", "mask_y", "mask_width", "mask_height"], "没转的盒子少了曲线");
assert.deepEqual(maskAnimFields(box({ rotation: 30 }))!.map((row) => row.property), ["mask_x", "mask_y"],
  "转过角度的盒子还给了宽/高曲线");
assert.deepEqual(maskAnimFields(box({ rotation: -1 }))!.map((row) => row.property), ["mask_x", "mask_y"],
  "转过角度的盒子还给了宽/高曲线（负角那一档）");
assert.deepEqual(maskAnimFields(box({ shape: "path", vertices: [] }))!.map((row) => row.property),
  ["mask_x", "mask_y"], "路径遮罩的曲线名单不对");
assert.deepEqual(maskAnimFields(null), [], "没有遮罩也该是空名单");

// ② 那张参考线在屏幕像素意义上真的转了
const flat = rotatedCorners(box({}), 1).split(", ");
assert.deepEqual(flat, ["30.000 30.000", "70.000 30.000", "70.000 70.000", "30.000 70.000"]);
const quarter = points(box({ rotation: 45 }), 1);
assert.equal(quarter[0], 50, "45° 之后左上角该落在正上方那条中线");
assert.equal(quarter[1], 21.716, "45° 那个角该落在正上方，量到的却是别处（符号或画幅比反了）");
// 90°：一条长边必须落在竖直方向上（横着的盒子转直立），用非 1 的画幅比量才有意义
const upright = points(box({ width: 0.8, height: 0.2, rotation: 90 }), 0.5625);
assert.equal(upright[0], upright[2], "90° 之后长边还带横移：等比换算没做");
assert.notEqual(upright[1], upright[3]);
// 折回屏幕像素：那条长边的长度就是盒宽 × 画面宽，不是被画幅比拧过的另一个数
assert.ok(Math.abs(((upright[3] - upright[1]) / 100) * 9 - 0.8 * 16) < 0.02,
  `长边在屏幕像素里成了 ${(((upright[3] - upright[1]) / 100) * 9).toFixed(3)}，该是 ${0.8 * 16}`);
// +30°：长的那头朝屏幕下方斜（y 变大）；符号反了这条就红
const wide = points(box({ width: 0.8, height: 0.2, rotation: 30 }), 0.5625);
assert.ok(wide[3] > wide[1], `+30° 右端该朝下：${wide[1]} → ${wide[3]}`);
const back = points(box({ width: 0.8, height: 0.2, rotation: -30 }), 0.5625);
assert.ok(back[3] < back[1], `−30° 右端该朝上：${back[1]} → ${back[3]}`);
// 短边也要量：30° 时那条短边在屏幕像素里就该是盒高 × 画面高（0.2×9），
// x 那一项少了画幅比的话它会胀到 2.23——上一版只钉了长边，这一格就是漏的那一条。
const short = Math.hypot(((wide[6] - wide[0]) / 100) * 16, ((wide[7] - wide[1]) / 100) * 9);
assert.ok(Math.abs(short - 0.2 * 9) < 0.02, `短边在屏幕像素里成了 ${short.toFixed(3)}，该是 ${0.2 * 9}`);
const long = Math.hypot(((wide[2] - wide[0]) / 100) * 16, ((wide[3] - wide[1]) / 100) * 9);
assert.ok(Math.abs(long - 0.8 * 16) < 0.02, `长边在屏幕像素里成了 ${long.toFixed(3)}，该是 ${0.8 * 16}`);
// 中心不动：转多少度，四角的重心还是那个中心
const spread = points(box({ width: 0.8, height: 0.2, rotation: 37 }), 0.5625);
const midX = (spread[0] + spread[2] + spread[4] + spread[6]) / 4;
const midY = (spread[1] + spread[3] + spread[5] + spread[7]) / 4;
assert.ok(Math.abs(midX - 50) < 0.01 && Math.abs(midY - 50) < 0.01, [midX, midY]);

// ③ 接线：走的是引擎那张等比图，界面自己不再算角度
const picture = read("desktop/src/views/MaskPicture.tsx");
assert.ok(picture.includes('import { rotatedCorners } from "../maskGeometry"'), "向导没读那份几何");
assert.ok(!picture.includes("Math.cos"), "向导里出现了第二份三角换算");
assert.ok(picture.includes('rotated ? " rotated-mask" : " animated-mask"'), "旋转的格子没换类名");
assert.ok(picture.includes('{rotated ? null : CORNERS.map'), "转过的盒子还留着四角把手");
assert.ok(picture.includes("画面上这框就是转过角度的遮罩盒"), "收掉把手没说为什么");
assert.equal(picture.split('"--mask-w": mask?.width').length - 1, 1, "旋转那一路也该拿盒子的宽去缩放");
assert.ok(picture.includes('? { maskImage: animated.unit, "--mask-x": mask?.center_x ?? .5, "--mask-y": mask?.center_y ?? .5 } as CSSProperties'),
  "旋转的动画格子没改成只平移那一条");
const style = read("desktop/src/styles.css");
assert.ok(style.includes(".masked-picture.rotated-mask {"), "没有旋转那一路的遮罩规则");
const rotatedRule = style.slice(style.indexOf(".masked-picture.rotated-mask {"), style.indexOf("}", style.indexOf(".masked-picture.rotated-mask {")));
assert.ok(rotatedRule.includes("mask-size: 100% 100%"), rotatedRule);
assert.ok(rotatedRule.includes("calc((var(--mask-x) - 0.5) * var(--mask-lw) * 1px)"), rotatedRule);
assert.ok(!rotatedRule.includes("--mask-w"), "旋转那张图不该按盒子的宽拉伸");

const inspector = read("desktop/src/views/Inspector.tsx");
assert.ok(inspector.includes("遮罩角度"), "检查器没有角度那一格");
// 检查器那几行数字不许自己判「哪条属性能打关键帧」：名单只从 maskAnimFields 出去，
// 否则转过角度的盒会留下一颗按下去必被引擎拒绝的 ◇。
assert.ok(inspector.includes("maskAnimFields(mask)"), "检查器自己另判了一份能打的盒属性");
assert.ok(inspector.includes('if (mask.shape === "path") return [];'), "路径遮罩该整个没有数字盒这一行");
assert.ok(inspector.includes("import { blurMaxPercent, canAnimateMask") && inspector.includes("maskAnimFields,"),
  "检查器没从 effects.ts 读那份名单");
assert.ok(inspector.includes("max={rotationLimit}") && inspector.includes("min={-rotationLimit}"),
  "角度的上下限不是引擎下发的数");
assert.ok(inspector.includes("features.mask_rotation") && inspector.includes("mask_rotation_limit"),
  "没读 capabilities 就摆了颗旋钮");
assert.ok(inspector.includes("这一版引擎没有遮罩角度这一格"), "老引擎那一档没说");
assert.ok(inspector.includes("但宽/高那两条要先把角度转回 0°"), "不能打宽高曲线这件事没写在界面上");
assert.ok(!/id="mask-rotation"[^>]*min=\{-360\}/.test(inspector), "界面把 360 抄成了自己的上限");

// ④ 角度还不是关键帧：契约里那四条盒属性一条没多，界面也不许先接上
const engine = read("desktop/src/engine.ts");
assert.ok(engine.includes('export type MaskProperty = "mask_x" | "mask_y" | "mask_width" | "mask_height";'),
  "盒属性被偷偷加了第五条，导出那一腿还没接");
const store = read("desktop/src/store.ts");
assert.ok(!store.includes("mask_rotation"), "界面开始写一条引擎不收的曲线");
assert.ok(engine.includes("rotation?: number"), "ShapeMask 没带上角度");

const contracts = read("src/agentcut/contracts.py");
assert.ok(contracts.includes('"mask_rotation": True'), "引擎没把这一档报出去");
assert.ok(contracts.includes("or set 遮罩角度 back to 0"), "那句拒绝没说要转回 0°");

console.log(`PASS: 遮罩角度的参考线在屏幕像素意义上转了（${flat.length} 个角钉住），`
  + "界面只平移引擎那张等比图，上下限与能不能打曲线都从 capabilities 读");
