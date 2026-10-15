/** 1.164/1.165「遮罩可旋转 + 角度能打曲线」界面这一侧：角度只在引擎里换算，界面只许画参考线、
 *  平移那张图，并按引擎下发的那份窗表换图。
 *
 这一档要挡的四种错和 1.115、1.163 撞过的是同三种，加上 1.165 新引的那一种：
 ① 界面自己再算一份旋转（两条腿各算各的，量出来的是话不是画面）；
 ② 把一条导出会拒的曲线摆到人面前（转过的盒子能给宽高打关键帧，红的是画面上那条斜坡；路径遮罩
    根本没有盒可转）；
 ③ 界面自带一个角度上限（引擎改了数字界面还在说 360，那是抄的）；
 ④ 1.165：一端连续、一端台阶。角度曲线在导出是**按帧对齐的阶梯**，预览就必须吃同一份窗表——
    界面在两窗之间插出一个角，画面上看着对，导出的那一步却从来不存在。
 所以这里既量那张参考线的数学（它在屏幕像素意义上必须真的转了）、量落格（表头表尾各夹一次），
 也读源码数那几处接线。
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { maskAnimFields } from "../desktop/src/effects";
import type { Capabilities, ShapeMask } from "../desktop/src/engine";
import { rotatedCorners, rotationWindowAt } from "../desktop/src/maskGeometry";

declare const REPO_ROOT: string;

const read = (rel: string) => readFileSync(`${REPO_ROOT}/${rel}`, "utf-8");
const box = (extra: Partial<ShapeMask>): ShapeMask => ({
  shape: "ellipse", center_x: 0.5, center_y: 0.5, width: 0.4, height: 0.4,
  feather: 0, inverted: false, vertices: null, ...extra,
});
const points = (mask: ShapeMask, k: number) => rotatedCorners(mask, k).split(", ").flatMap((pair) => pair.split(" ").map(Number));
const caps = (features: Record<string, boolean>) => ({ features, limits: { mask_rotation_limit: 360 } }) as unknown as Capabilities;

// ① 曲线名单：转过的盒子只剩两条中心曲线，没转的还是四条（两个方向都要成立）。
//    1.165 多钉两端：这一版引擎报了 `mask_rotation_curves` 时名单里必须有角度那一行，
//    没报（老引擎）时必须没有——摆一颗按下去必被拒的针与藏掉一条已经能用的曲线，是同一种错。
const rows = (mask: ShapeMask | null, c?: Capabilities) => maskAnimFields(mask, c).map((row) => row.property);
const angleCaps = caps({ mask_rotation: true, mask_rotation_curves: true });
const plainCaps = caps({ mask_rotation: true });
assert.deepEqual(rows(box({}), plainCaps), ["mask_x", "mask_y", "mask_width", "mask_height"],
  "这一版引擎不收角度曲线，名单里却摆了它");
assert.deepEqual(rows(box({})), ["mask_x", "mask_y", "mask_width", "mask_height"],
  "没下发 capabilities 时名单里也不该有角度那一行（没转的盒子仍是四条）");
assert.deepEqual(rows(box({}), angleCaps),
  ["mask_x", "mask_y", "mask_width", "mask_height", "mask_rotation"], "引擎报了角度曲线，名单里却没有这一行");
assert.deepEqual(rows(box({ rotation: 30 })), ["mask_x", "mask_y"], "转过角度的盒子还给了宽/高曲线");
assert.deepEqual(rows(box({ rotation: 30 }), angleCaps), ["mask_x", "mask_y", "mask_rotation"],
  "转过角度的盒子把自己那条角度曲线也丢了");
assert.deepEqual(rows(box({ rotation: -1 })), ["mask_x", "mask_y"], "转过角度的盒子还给了宽/高曲线（负角那一档）");
assert.deepEqual(rows(box({ shape: "path", vertices: [] })), ["mask_x", "mask_y"], "路径遮罩的曲线名单不对");
assert.deepEqual(rows(box({ shape: "path", vertices: [] }), angleCaps), ["mask_x", "mask_y"],
  "路径遮罩摆了角度曲线：轮廓自己带形状，引擎的 validator 不收那一格");
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
// 1.165：有窗表时画的是「此刻那一窗」的角，不是遮罩自己那一格——调用方传的角度必须赢
const own = box({ width: 0.8, height: 0.2, rotation: 0 });
assert.equal(rotatedCorners(own, 0.5625, 90), rotatedCorners(box({ width: 0.8, height: 0.2, rotation: 90 }), 0.5625),
  "窗表给的角度没盖过遮罩自己那一格");
assert.notEqual(rotatedCorners(box({ rotation: 30 }), 0.5625), rotatedCorners(box({ rotation: 30 }), 0.5625, 0),
  "给了角度参数却还被忽略");

// ②b 阶梯落格：播放头落在哪一窗就画哪一窗，界面前后各夹一次，绝不插值出一个导出没有的角
const steps = [
  { from_ticks: 0, to_ticks: 30, angle: 0 },
  { from_ticks: 30, to_ticks: 60, angle: 30 },
  { from_ticks: 60, to_ticks: 90, angle: 60 },
];
assert.equal(rotationWindowAt(steps, 0)?.angle, 0, "第一窗的开头不该落到别处");
assert.equal(rotationWindowAt(steps, 29)?.angle, 0, "换窗前的那一格跳早了");
assert.equal(rotationWindowAt(steps, 30)?.angle, 30, "换窗的那一格还停在上一窗");
assert.equal(rotationWindowAt(steps, 89)?.angle, 60, "最后一窗在表尾前一格就撒手了");
assert.equal(rotationWindowAt(steps, 90)?.angle, 60, "超出表尾该停在最后一窗，不是回头猜");
assert.equal(rotationWindowAt(steps, -1)?.angle, 0, "表头之前该停在第一窗——回到最后一窗就是把阶梯倒着读");
assert.equal(rotationWindowAt([], 5), null, "没有窗表时不许猜一个角度");

// ③ 接线：走的是引擎那张等比图，界面自己不再算角度
const picture = read("desktop/src/views/MaskPicture.tsx");
assert.ok(picture.includes('import { rotatedCorners, rotationWindowAt } from "../maskGeometry"'), "向导没读那份几何");
assert.ok(picture.includes('const spun = draft ? null : rotation ? rotationWindowAt(rotation, local) : null'),
  "向导没按播放头去引擎那份窗表里取此刻那一窗");
assert.ok(picture.includes("Boolean(mask?.rotation) || Boolean(spun)"), "有没有转过角度只看了一头");
assert.ok(!picture.includes("Math.cos"), "向导里出现了第二份三角换算");
assert.ok(picture.includes('rotated ? " rotated-mask" : " animated-mask"'), "旋转的格子没换类名");
assert.ok(picture.includes("{rotated ? null : CORNERS.map"), "转过的盒子还留着四角把手");
assert.ok(picture.includes("画面上这框就是转过角度的遮罩盒"), "收掉把手没说为什么");
assert.ok(picture.includes("这一格的角度是"), "阶梯在画面上没说这一刻吃的是哪一窗");
assert.ok(picture.includes('type MaskBoxProperty = Exclude<MaskProperty, "mask_rotation">'),
  "盒子那四个 CSS 变量的名单没把角度排除掉");
assert.equal(picture.split('"--mask-w": mask?.width').length - 1, 1, "旋转那一路也该拿盒子的宽去缩放");
assert.ok(picture.includes('? { maskImage: spun.image,'), "阶梯那一路没换成此刻那一张图");
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
// 那颗 ◇ 的两个方向：这一版引擎不收曲线时不许出现，路径遮罩整个没有角度这一格。
assert.ok(inspector.includes("{rotationCurves && animatable ? <button"), "角度那颗 ◇ 没受 capabilities 管");
assert.ok(inspector.includes('mask.shape === "path" ? null : rotationLimit === undefined'),
  "路径遮罩摆了角度那一格（引擎两头都拒）");
assert.ok(inspector.includes('property: "mask_rotation", at_ticks: at'), "◇ 写的不是引擎认的那条属性名");
assert.ok(inspector.includes("删除遮罩角度关键帧") && inspector.includes("添加遮罩角度关键帧"),
  "那颗 ◇ 没说它按下去会做什么");
assert.ok(inspector.includes('removeKeyframe(clip.id, "mask_rotation"'), "再按一次删不掉自己打的那一格");

// ④ 角度是关键帧了，但它不走 CSS 变量那一路：`mask-image` 不吃图层 transform（1.164 量的），
//    界面每窗换的是引擎烘好的那张等比图。把它做成第五个变量就是画一条导出不会走的路。
const engine = read("desktop/src/engine.ts");
assert.ok(engine.includes('export type MaskProperty = "mask_x" | "mask_y" | "mask_width" | "mask_height" | "mask_rotation";'),
  "盒的第五条属性没接进界面类型（导出这一腿 1.165 已经接上了）");
assert.ok(engine.includes("export type MaskRotationWindow = {"), "预览清单里那扇窗在界面这边没有类型");
assert.ok(engine.includes("mask_rotation_windows?: MaskRotationWindow[] | null"), "界面没接引擎下发的那份阶梯");
assert.ok(engine.includes("mask_rotation: number"), "采样值里没有这一格，曲线编辑器就成了瞎子");
assert.ok(!/MASK_VARIABLE[^=]*=\s*\{[^}]*rotation/.test(picture), "角度被做成了一个 CSS 变量");
const store = read("desktop/src/store.ts");
assert.ok(!store.includes("mask_rotation"), "角度进了逐帧补间那一路——它该换图，不该动变量");
assert.ok(engine.includes("rotation?: number"), "ShapeMask 没带上角度");
const preview = read("desktop/src/views/Preview.tsx");
assert.ok(preview.includes('rotation={plan?.mask_rotation_windows}'), "预览没把那份阶梯交给向导");
const curves = read("desktop/src/views/CurveEditor.tsx");
assert.ok(curves.includes("maskAnimFields(clip.mask, app.caps)"), "曲线编辑器没把 capabilities 交给那份名单");

const contracts = read("src/agentcut/contracts.py");
assert.ok(contracts.includes('"mask_rotation": True'), "引擎没把这一档报出去");
assert.ok(contracts.includes('"mask_rotation_curves": True'), "引擎没报角度能不能打曲线");
assert.ok(contracts.includes("or set 遮罩角度 back to 0"), "那句拒绝没说要转回 0°");
assert.ok(contracts.includes('key.property == "mask_rotation" for key in self.keyframes'),
  "路径遮罩的角度曲线没被拒——摆出来就是一条导出不执行的针");

console.log(`PASS: 遮罩角度的参考线在屏幕像素意义上转了（${flat.length} 个角钉住），阶梯按窗落格 ${steps.length} 段两头同一张表，`
  + "界面只平移引擎那张等比图，上下限与能不能打曲线都从 capabilities 读");
