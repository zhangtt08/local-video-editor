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
// 1.166：这一版引擎每窗重烘一张图，转过的盒也该拿到宽/高那两行（两头都钉：没报这个开关时不许给）
const sizeCaps = caps({ mask_rotation: true, mask_rotation_curves: true, mask_rotation_size_curves: true });
assert.deepEqual(rows(box({ rotation: 30 }), sizeCaps),
  ["mask_x", "mask_y", "mask_width", "mask_height", "mask_rotation"],
  "引擎每窗重烘一张图了，转过的盒还在被摘掉宽/高那两行");
assert.deepEqual(rows(box({ rotation: 30, width: 0.8, height: 0.3 }), sizeCaps).length, 5,
  "窗表的宽高与画面上那框该是同一个盒");
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
assert.ok(picture.includes('import { rotateAngleFromPointer, rotatedCorners, rotatedEdgeMids, rotationWindowAt } from "../maskGeometry"'),
  "向导没读那份几何（角度落位只许有一处实现：参考线、窗表、那颗旋转手柄同出一源）");
assert.ok(picture.includes('const spun = draft ? null : rotation ? rotationWindowAt(rotation, local) : null'),
  "向导没按播放头去引擎那份窗表里取此刻那一窗");
assert.ok(picture.includes("Boolean(mask?.rotation) || Boolean(spun)"), "有没有转过角度只看了一头");
assert.ok(picture.includes("spun ? { ...mask, width: spun.width, height: spun.height } : mask"), "参考线还在按静态那一格画盒，窗表给的宽高没进来");
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
assert.ok(inspector.includes("maskAnimFields(mask, caps)"), "检查器自己另判了一份能打的盒属性");
assert.ok(inspector.includes('if (mask.shape === "path") return [];'), "路径遮罩该整个没有数字盒这一行");
assert.ok(inspector.includes("import { blurMaxPercent, canAnimateMask") && inspector.includes("maskAnimFields,"),
  "检查器没从 effects.ts 读那份名单");
assert.ok(inspector.includes("max={rotationLimit}") && inspector.includes("min={-rotationLimit}"),
  "角度的上下限不是引擎下发的数");
assert.ok(inspector.includes("features.mask_rotation") && inspector.includes("mask_rotation_limit"),
  "没读 capabilities 就摆了颗旋钮");
assert.ok(inspector.includes("这一版引擎没有遮罩角度这一格"), "老引擎那一档没说");
// 1.209 把那一长段收成一行；「转过的盒子也能动大小」这一句还在，只是不再顺带讲烘图的机制（那部分在帮助里）。
assert.ok(inspector.includes("大小与角度都能按◇打点"), "能动尺寸这件事没写在界面上");
assert.ok(!inspector.includes("要先把角度转回 0°"), "界面还在说一条引擎已经不拒的拒绝");
// 1.166 装机量到的那一幕：判断在 `maskAnimFields` 那一处是对的，可检查器算行名单时没把 caps 递过去，
// 于是角度一非零，「宽度 / 高度」那两行就凭空消失。这里钉的是**调用点**，不是函数返回值。
assert.ok(/maskAnimFields\(mask, caps\)/.test(inspector), "maskRows 折名单时没把 capabilities 递给 maskAnimFields");
assert.ok(inspector.includes("maskRows(mask, app.caps)"), "检查器那一处调用没带 caps，转过的盒那两行会被摘掉");
assert.ok(!/maskAnimFields\(mask\)/.test(inspector), "还有一处 maskAnimFields 调用没带 caps");
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
// 这条以前写得粗（store.ts 里连 `mask_rotation` 这个名字都不许出现），它真正守的是两件事：
// 角度不能被做成逐帧补间的 CSS 变量，界面这边也不能自己算角度。1.177 让「拖手柄」和别的盒属性
// 一样走同一条拖动规则（已打针就写播放头那一帧），于是那个名字必须出现在表里——所以按本意收窄，
// 而不是把规则废掉：逐帧补间与自算角度各自钉一条（上面那条 MASK_VARIABLE 的钉法原样留着）。
assert.ok(!store.includes("--mask-rotation"), "角度进了逐帧补间那一路——它该换图，不该动变量");
assert.ok(!/Math\.(atan2?|cos|sin)\(/.test(store), "store 自己开始算角度了（角度的数只从引擎那张表来）");
assert.ok(engine.includes("rotation?: number"), "ShapeMask 没带上角度");
const preview = read("desktop/src/views/Preview.tsx");
assert.ok(preview.includes('rotation={plan?.mask_rotation_windows}'), "预览没把那份阶梯交给向导");
const curves = read("desktop/src/views/CurveEditor.tsx");
assert.ok(curves.includes("maskAnimFields(clip.mask, app.caps)"), "曲线编辑器没把 capabilities 交给那份名单");

const contracts = read("src/agentcut/contracts.py");
assert.ok(contracts.includes('"mask_rotation": True'), "引擎没把这一档报出去");
assert.ok(contracts.includes('"mask_rotation_curves": True'), "引擎没报角度能不能打曲线");
assert.ok(!contracts.includes("set 遮罩角度 back to 0"), "那句拒绝还在：转过的盒今天能动尺寸");
assert.ok(contracts.includes('"mask_rotation_size_curves": True'), "引擎没报「转过的盒能动尺寸」这一档");
// 1.170：深链 `?clip=` 点名一条片段——这既是「发个链接就能看到那一条」，也是让**渲染出来的**
// 行名单可以被机器量到（浏览器里不用先点一下）的前提。三件事各自钉：读参数、选中并切页签、坏 id 不动。
const storeSrc = read("desktop/src/store.ts");
assert.ok(storeSrc.includes('urlParam("clip")'), "深链不再点名片段");
assert.ok(storeSrc.includes('urlParam("tick")'), "深链不再读 ?tick=");
assert.ok(/export function focusLinkedClip\(clipId: string, tick = "", panel = ""\): boolean \{/.test(storeSrc),
  "focusLinkedClip 的形状变了（深链选中那条，并接住 ?tick= 与 ?panel=）");
assert.ok(/export function landLinkedTick\(tick: string\): boolean \{/.test(storeSrc),
  "landLinkedTick 不在了（?tick= 没有落点）");
assert.ok(storeSrc.includes("if (!project || !/^\\d+$/.test(tick)) return false;"),
  "认不出的 ?tick= 会往下走——播放头该一动不动");
// 1.172 那枚钉的是「夹到时间线末尾」，1.178 在同一条语句上加了整帧吸附——旧锚钉的是旧形状，
// 一起改到新形状上（两件事一起钉：吸附 + 夹边），下面那枚反向锚继续管「不许直接落回播放头」。
assert.ok(storeSrc.includes('playhead.set(Math.min(snapTo(project, "video", Number(tick)), timelineEnd(project)));'),
  "?tick= 不再吸附整帧、或不再夹到时间线末尾（半帧的播放头让此刻的窗与画面差一帧，越界的会丢进看不见处）");
// 1.178：吸附到整帧。1.177 在真页面上量到 ?tick=17640000 停在第 7.5 帧——引擎的逐片段不变量本来就按帧走。
assert.ok(!storeSrc.includes("playhead.set(Math.min(Number(tick)"),
  "深链的刻度又直接落回播放头（不再过那条唯一的吸附）");
assert.ok(storeSrc.includes("focusLinkedClip(linkedClip, linkedTick, linkedPanel);"),
  "深链选中片段时没把 ?tick= 与 ?panel= 一起递过去");
assert.ok(storeSrc.includes("if (!landLinkedPanel(panel)) setEditorPanel(\"inspect\");"),
  "focusLinkedClip 收了 panel 却没落到面板（链接点了面板还是检查器）");
assert.ok(/export function landLinkedPanel\(panel: string\): boolean \{/.test(storeSrc),
  "landLinkedPanel 不在了（?panel= 没有落点）");
assert.ok(storeSrc.includes("if (!(EDITOR_PANELS as readonly string[]).includes(panel)) return false;"),
  "认不出的 ?panel= 会往下走——面板该一动不动");
assert.ok(storeSrc.includes("export const EDITOR_PANELS = [\"inspect\", \"export\", \"scope\"] as const;"),
  "面板名单不再是唯一那一张表");
assert.ok(storeSrc.includes("editorPanel: (typeof EDITOR_PANELS)[number];"),
  "AppState 又自带第二份面板名字表");
assert.ok(!/editorPanel: \"inspect\" \| \"export\" \| \"scope\"/.test(storeSrc),
  "面板名单被抄回类型那一行了（两处各自漂移）");
assert.ok(storeSrc.includes("landLinkedPanel(linkedPanel);"),
  "只给 ?panel= 的那条链接不再落地");
// ?view= 与面板同一张表的纪律：名单只许有一处，深链在那一处上验。
assert.ok(storeSrc.includes('export const VIEWS = ["home", "editor", "history", "agent"] as const;'),
  "视图名单不再是唯一那一张表");
assert.ok(storeSrc.includes("export type View = (typeof VIEWS)[number];"),
  "View 又自带第二份视图名字表");
assert.ok(!/export type View = "home" \| "editor" \| "history" \| "agent"/.test(storeSrc),
  "视图名单被抄回类型那一行了（两处各自漂移）");
assert.ok(storeSrc.includes('const linkedView = (VIEWS as readonly string[]).includes(view) ? view as View : "";'),
  "深链 ?view= 不再在同一张表上验，认不出的名字会把界面切走");
assert.ok(storeSrc.includes("if (linkedView) set({ view: linkedView });"),
  "视图切换没落在 openProject 之后——它自己会切回编辑器，先切的那一下被盖掉（1.174 量到的缺陷）");
assert.ok(!/set\(\{ view: view as View \}\)/.test(storeSrc),
  "又回到在 openProject 之前先切视图那一版（画面上看不出，DOM 上量得到）");
// 「切面板」不许再顺手抢视图：这一处才是 1.174/1.175 两轮 DOM 量到的那次无声覆盖的真位置。
assert.ok(/export function setEditorPanel\(editorPanel: AppState\["editorPanel"\]\) \{\s*set\(\{ editorPanel \}\);/.test(storeSrc),
  "setEditorPanel 又开始顺手写 view 了（深链 ?view= 会被它盖掉）");
assert.ok(/export function setGraphOpen\(graphOpen: boolean\) \{ set\(\{ graphOpen \}\); \}/.test(storeSrc),
  "setGraphOpen 又开始顺手写 view 了");
assert.ok(/export function openEditorPanel\(editorPanel: AppState\["editorPanel"\]\) \{\s*set\(\{ editorPanel, view: "editor" \}\);/.test(storeSrc),
  "openEditorPanel 不在了——人点「导出」那一个意图没有唯一的实现");
assert.ok(/else if \(linkedView\) \{\s*set\(\{ view: linkedView \}\);/.test(storeSrc),
  "链接只点名视图（不带工程）时不再切视图");
// 1.177：画面上那颗旋转手柄。角度这一格以前只有检查器里的数字框能改，AE 与剪映的落笔都在画面上。
const pictureSrc = read("desktop/src/views/MaskPicture.tsx");
const geometrySrc = read("desktop/src/maskGeometry.ts");
const stylesSrc = read("desktop/src/styles.css");
assert.ok(pictureSrc.includes("onPointerDown={(e) => begin(e, { rotate: true })}"),
  "画面上那颗旋转手柄不在了（角度只能在数字框里改）");
assert.ok(pictureSrc.includes("旋转遮罩（此刻") && pictureSrc.includes(".toFixed(1)}°）"),
  "旋转手柄没有说清此刻角度的无障碍名");
assert.ok(pictureSrc.includes("if (gesture.rotate) {"), "proposed 里不认 rotate 这一笔（按下拖动都不转）");
assert.ok(pictureSrc.includes("angle0: target.rotate ? angleOf(event) ?? undefined : undefined"),
  "按下时没记住起始那个屏幕角（一转就跳到指针上）");
assert.ok(pictureSrc.includes("rotateAngleFromPointer(event.clientX"),
  "读回的角与茎的落位不再互逆（1.181：直接对屏幕像素取 atan2，拖多少与看见多少就分家）");
assert.ok(!pictureSrc.includes("Math.atan2(px, -py)"),
  "旧的屏幕角式子还在：那颗框是拉伸的，屏幕角不等于画框里的角度");
assert.ok(pictureSrc.includes('if (disabled || !["ArrowLeft", "ArrowRight"].includes(e.key)) return;'),
  "那颗手柄只有鼠标这一只手（键盘该有 ±1° / Shift ±15° 的孪生）");
assert.ok(pictureSrc.includes("const rotationLimit = app.caps?.limits?.mask_rotation_limit ?? FALLBACK_ROTATION_LIMIT;"),
  "手柄自己带上角度上限（上限只由 capabilities 下发）");
assert.ok(pictureSrc.includes('canRotate = Boolean(mask && mask.shape !== "path" && app.caps?.features?.mask_rotation)'),
  "轮廓遮罩或未报开关的引擎那头还在摆这颗必被拒的手柄");
assert.ok(geometrySrc.includes("export const rotatedEdgeMids"),
  "边中点的落位没有唯一一处实现（手柄与参考线会各算各的盒）");
assert.ok(pictureSrc.includes("const body = spun ? { ...mask, width: spun.width, height: spun.height } : mask;"),
  "有窗表时手柄落在了基准盒上，而不是此刻看见的那一窗的盒");
assert.ok(storeSrc.includes('["mask_rotation", "rotation"],'),
  "拖旋转这一笔不再走「已打针就写播放头那一帧」那一条规则（为角度另写一套剪辑规则）");
assert.ok(stylesSrc.includes(".mask-handle.rotate-handle"), "那颗手柄没有自己的样式（看不见也抓不着）");
const titlebarSrc = read("desktop/src/TitleBar.tsx");
assert.ok(titlebarSrc.includes('onClick={() => openEditorPanel("export")}'),
  "标题栏那颗「导出」不再走那一个组合意图（切面板与跳视图分开写就漏一半）");
assert.ok(!/onClick=\{\(\) => setEditorPanel\("export"\)\}/.test(titlebarSrc),
  "标题栏还直接调 setEditorPanel：现在它不再负责跳视图，按钮会点着没反应");
assert.ok(!/view === "home" \|\| view === "editor"/.test(storeSrc),
  "restoreDeepLink 里还剩一条自己拼的视图名单");
assert.ok(/landLinkedTick\(tick\);\s*\n\s*return true;/.test(storeSrc),
  "focusLinkedClip 收了 tick 却没把它递到落点（选中了、帧没停）");
assert.ok(/playhead\.pause\(\);[\s\S]{0,260}?playhead\.set\(Math\.min\(snapTo\(project, "video", Number\(tick\)\), timelineEnd\(project\)\)\);/.test(storeSrc),
  "停帧之前没按下播放，或停的那一格没先吸附整帧再夹边（注释隔在两条写之间，所以这里按段找）");
assert.ok(!storeSrc.includes("focusLinkedClip(linkedClip)"),
  "调用点又回到只递片段 id 那一版（?tick= 被丢了）");
assert.ok(storeSrc.includes('setEditorPanel("inspect")'), "深链选中片段后没把右侧面板切到检查器");
assert.ok(storeSrc.includes("if (!state.project?.clips[clipId]) return false;"),
  "认不出的片段 id 会往下走，界面会停在半开状态");
assert.ok(/void openProject\(wanted\)\.then\(\(\) => \{/.test(storeSrc)
  && storeSrc.includes("landLinkedTick(linkedTick);"),
  "深链没等工程读进来就下单，选不到那条片段也停不到那一帧");
assert.ok(contracts.includes('key.property == "mask_rotation" for key in self.keyframes'),
  "路径遮罩的角度曲线没被拒——摆出来就是一条导出不执行的针");

console.log(`PASS: 遮罩角度的参考线在屏幕像素意义上转了（${flat.length} 个角钉住），阶梯按窗落格 ${steps.length} 段两头同一张表，`
  + "界面只平移引擎那张等比图，上下限与能不能打曲线都从 capabilities 读");
