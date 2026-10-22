// 1.221：一条片段再叠几块遮罩——界面写的是整串，浏览器叠的是引擎那几张图。
//
// 这一档钉的是「两端各算一遍」那一类：多出来的那几块由 `clip.extra_masks` 说一次，
// 导出把它乘进同一条 alpha，预览把引擎给的图一层层叠起来取交集。界面不许自己造图、
// 不许把两件事写成两次 `clip.mask`，也不许在浏览器里再乘一次 alpha。
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { BEZIER_AXES, boxKeyAt, boxKeyForPlayhead, bezierBand, DEFAULT_BEZIER, extraMotionWords, maskBoxInterpolations } from "../desktop/src/effects";
import type { Capabilities, ShapeMask } from "../desktop/src/engine";
import { BOX_KEY_HIT_PIXELS, planBoxKeyDrag } from "../desktop/src/boxKeyDrag";
import { boxVectorFromPointer, rotateAngleFromPointer, rotatedBoxPoints, stemAngleFromUser } from "../desktop/src/maskGeometry";
import { offsetWords } from "../desktop/src/time";

declare const REPO_ROOT: string;

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync) ?? resolve(REPO_ROOT, parts[0]);
  assert.ok(existsSync(found!), `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const store = read("desktop/src/store.ts", "../../desktop/src/store.ts");
const inspector = read("desktop/src/views/Inspector.tsx", "../../desktop/src/views/Inspector.tsx");
const timeline = read("desktop/src/views/Timeline.tsx", "../../desktop/src/views/Timeline.tsx");
const picture = read("desktop/src/views/MaskPicture.tsx", "../../desktop/src/views/MaskPicture.tsx");
const preview = read("desktop/src/views/Preview.tsx", "../../desktop/src/views/Preview.tsx");
const engine = read("desktop/src/engine.ts", "../../desktop/src/engine.ts");
const css = read("desktop/src/styles.css", "../../desktop/src/styles.css");
const effects = read("desktop/src/effects.ts", "../../desktop/src/effects.ts");
const curve = read("desktop/src/views/CurveEditor.tsx", "../../desktop/src/views/CurveEditor.tsx");

// ① 写的那一手：一次交回整串，与 `clip.mask`、`clip.grade` 同一个规矩
const writer = /export function setClipMaskStack\([\s\S]*?\n\}/.exec(store);
assert.ok(writer, "setClipMaskStack 不见了——再叠的那几块就没有写入口");
assert.match(writer[0], /op: "clip\.mask_stack", clip_id: clipId, masks/, "写出去的不是那一整串");
assert.equal((writer[0].match(/op: "clip\.mask"/g) ?? []).length, 0, "叠加那一格不许顺手改主遮罩（两次写就是一份状态两个主人）");
assert.equal((store.match(/op: "clip\.mask_stack"/g) ?? []).length, 1, "clip.mask_stack 只能有一处写入口");

// ② 检查器：列表、加一块、删一块，额度听引擎的，做不到的那件事明说
assert.match(inspector, /<MaskStack clip=\{clip\} disabled=\{disabled\} \/>/, "叠加那一格没接进遮罩区");
assert.match(inspector, /app\.caps\?\.limits\?\.extra_masks/, "「最多几块」不在引擎那一份数上");
// 1.242：这一句是 1.237/1.238 之前的实话（那时这几块确实只切不动）。框点与跟随都交付之后
// 它已经是假话，而 1.221 那条断言还在替它说话——留着一个不许删的假句子比没有句子更坏。
assert.doesNotMatch(inspector, /只切不动/, "「只切不动」早就不成立了：框点与跟随都能让这几块动起来");
// 1.237：那一格旁边多了一个「跟着主遮罩平移」的开关，勾上之后它们跟着中心曲线走。
assert.match(inspector, /跟着主遮罩平移/, "「跟着主遮罩平移」这一格不在检查器里");
assert.match(inspector, /setClipMaskStack\(clip\.id, stack, event\.target\.checked\)/, "那个勾没有把 follow 交出去");
assert.match(inspector, /与主遮罩取交集/, "那一格没说清叠出来的是什么关系");
// 1.237：改一块与勾「跟着主遮罩平移」是两条人路，但都只进 setClipMaskStack 这一个写入口。
assert.equal((inspector.match(/setClipMaskStack\(clip\.id/g) ?? []).length, 2, "叠加那一串的写入口不止那两处，早晚一份对不上");

// ③ 浏览器：叠的是引擎给的图，取交集用标准那一格，不自己再算 alpha
assert.match(picture, /const layers = \[primaryImage, \.\.\.extraPlates\.map\(\(row\) => row\.image\)\]\.filter\(Boolean\)/,
  "层的顺序变了：主遮罩必须在最下面，交集才是那两块都留着的一格");
assert.match(picture, /maskComposite: "intersect"/, "浏览器不再取交集，预览就会比成片露得多");
assert.match(picture, /layers\.length > 1/, "只有一块时不许把 mask-size 那几格一起改掉（会动到 1.117 起的定位）");
assert.match(picture, /style=\{stacked\}/, "算出来的那一串没画到画面上");
assert.doesNotMatch(picture, /maskAlpha|alpha\([^\)]*\*[^\)]*\)/, "浏览器不许自己乘 alpha——那是第二次换算");

// ④ 清单那一份就是唯一的图：界面只转发，不自己按遮罩重画
assert.match(preview, /extra=\{plan\?\.extra_mask_images\}/, "预览没把引擎那几张图交给画面层");
assert.match(engine, /extra_mask_images\?: string\[\] \| null/, "清单的类型里没有那几块图");
assert.match(engine, /extra_masks\?: ShapeMask\[\]/, "Clip 的类型里没有那几块");
assert.match(engine, /extra_masks\?: number/, "limits 里没有「最多几块」那一格");

// ⑤ 样式：一格一行、圆角与卡片同一档，字号仍走刻度
const row = /\.mask-stack-row\s*\{[^}]*\}/.exec(css);
assert.ok(row, "叠加那一行的规则不见了");
assert.match(row[0], /border-radius: var\(--r-sm\)/, "那一行不用刻度里的圆角");
assert.match(row[0], /font-size: var\(--fs-body\)/, "那一行不用刻度里的字号");
assert.match(css, /\.mask-stack-head\s*\{[^}]*font-size: var\(--fs-label\)/, "标题那一行不用刻度里的字号");

// ⑥ 1.229：每一块的五个数与羽化/反转都在这一格里改——1.221 只给了一个默认矩形，人改不动
// 1.258 起软边在框点上是可缺省的，所以那一格自己管；这一枚针跟着改到「滤掉软边的那一串」。
assert.match(inspector,
  /MASK_ROWS\.filter\(\(row\) => row\[0\] !== "feather"\)\.map\(\(\[field, label, min, max\]\)/,
  "叠加那几块的中心/大小行不是从同一张 MASK_ROWS 折出来的（第二张标签表迟早对不上）");
assert.match(inspector, /id=\{`stack-\$\{index\}-\$\{field\}`\}/, "每一块的输入框没有按块编号");
assert.match(inspector, /id=\{`stack-\$\{index\}-rotation`\}/, "叠加的块改不了角度");
assert.match(inspector, /id=\{`stack-\$\{index\}-feather`\}/, "叠加的块改不了羽化");
assert.match(inspector, /inverted: event\.target\.checked/, "叠加的块改不了反转");
assert.match(inspector, /const patch = \(index: number, part: Partial<ShapeMask>\)/,
  "改一个数要经一处 patch——四处各拼一遍整串，早晚有一处只改了主遮罩");
assert.match(inspector, /write\(stack\.map\(\(item, position\) => \(position === index \? \{ \.\.\.item, \.\.\.part \} : item\)\)\)/,
  "patch 没有走那唯一的一处写入口");
assert.match(css, /\.mask-stack-grid\s*\{[^}]*grid-template-columns: 1fr 1fr/, "两列那一格没排成两列");
assert.match(css, /\.mask-stack-invert\s*\{[^}]*grid-column: 1 \/ -1/, "反转那一行占整行，不跟别的挤一格");

// ⑦ 1.236：`mask-size` / `mask-position` 是按层给的。这一条是量出来的缺陷：主遮罩的中心
// 曲线一动，`mask-position` 就按主遮罩的盒子原点把再叠的那几块也搬走（预览里被挪了 0.215，
// 导出原地不动），两端的洞不是同一个。主遮罩一层用自己的公式，再叠的每一层都是 100% / 0,0。
assert.match(picture, /const mainSize = shapeWindow/, "主遮罩那一层的尺寸不是按自己那一支算的");
assert.match(picture, /const mainPosition = shapeWindow/, "主遮罩那一层的落位不是按自己那一支算的");
assert.match(
  picture,
  /if \(!row\.unit \|\| !extraMask \|\| !mainMask\) return "100% 100%";/,
  "不跟随/不转的那几层不是 100%×100%",
);
assert.match(picture, /const followPosition =/, "「跟着主遮罩平移」没有一条自己的落位算式");
assert.match(picture, /const extraPosition = follow \? followPosition : "0px 0px";/, "跟不跟这一格没有决定再叠层的落位");

assert.match(picture, /calc\(\(var\(--mask-x\) - 0\.5\) \* var\(--mask-lw\) \* 1px\)/, "角度那一支的落位公式变了");
assert.match(picture, /calc\(\(var\(--mask-x\) - var\(--mask-w\) \/ 2\) \* var\(--mask-lw\) \* 1px\)/, "中心/宽高那一支的落位公式变了");
assert.doesNotMatch(picture, /maskSize: "100% 100%", maskRepeat: "no-repeat", maskComposite: "intersect"/,
  "又回到「一整串只给一个 mask-size」——再叠的块会被主遮罩的落位带跑");

// ⑧ 1.238：每一块可以带自己的框点——打点只记「这一刻这五个数」，额度听引擎，清空是同一处写。
assert.match(inspector, /在播放头打框点/, "每一块的框点没有打点入口");
assert.match(inspector, /extra_mask_keys/, "框点额度不在引擎那一份数上");
assert.match(inspector, /patch\(index, \{ keys \}\)/, "框点没有走那一处 patch（第二份写入口）");
assert.match(inspector, /patch\(index, \{ keys: \[\] \}\)/, "框点没有清空入口");
assert.match(inspector, /Math\.round\(raw \/ frame\) \* frame/, "框点没有落在整帧上");
assert.match(engine, /extra_mask_windows\?: \(ExtraMaskWindow\[\] \| null\)\[\] \| null/, "清单的类型里没有每块自己的窗");
assert.match(picture, /rotationWindowAt\(windows, local\)/, "浏览器没有按播放头挑那一块自己的窗");
assert.match(picture, /row\.own && !row\.follow \? "0px 0px"/, "自己带框点的那一层没有按整画面图落位");
// 1.239：每一枚框点在卡片里有名字——时刻可跳、插值可改、删除只走那一处 patch。
assert.match(inspector, /className="mask-stack-keylist"/, "框点没有一张看得见的表");
assert.match(inspector, /timecode\(key\.at_ticks, rate\)/, "框点的时刻不是时间码");
assert.match(inspector, /playhead\.set\(clip\.position_ticks \+ key\.at_ticks\)/, "点时刻没有把播放头挪过去");
// 1.257 把贝塞尔这一档给了框点：原来那枚针钉的是「下拉里没有贝塞尔」——那是被换掉的旧形状。
// 按本意收窄成「名单只能由引擎点名，界面不许自己滤掉某一种」。
assert.doesNotMatch(inspector, /INTERPOLATIONS\)\.filter/, "框点那一格又开始自己滤某一种缓动（第二份名单）");
assert.match(inspector, /const boxInterpolations = maskBoxInterpolations\(app\.caps\);/, "缓动名单不是引擎交下来的那一份");
assert.match(inspector, /row\.at_ticks !== key\.at_ticks/, "删除一枚框点没有走同一处 patch");

// ⑨ 1.240：跟随时「不转的主遮罩 + 不转的那一块」共享中心与大小——单位图按同一对比例缩放。
assert.match(engine, /extra_mask_units\?: \(string \| null\)\[\] \| null/, "清单的类型里没有单位图");
assert.match(preview, /extraUnits=\{plan\?\.extra_mask_units\}/, "预览没把单位图交给画面层");
assert.match(picture, /const unit = Boolean\(follow && extraUnits\?\.\[index\]/, "单位图那一支的判据不在");
assert.match(picture, /calc\(var\(--mask-w\) \* \$\{ratioW\.toFixed\(6\)\} \* var\(--mask-lw\) \* 1px\)/, "单位图没有按主遮罩的宽度比例缩放");
assert.match(picture, /calc\(\(var\(--mask-x\) \$\{px\} - 0\.5 \* var\(--mask-w\)/, "单位图的落位没有减掉缩放后的一半");
assert.match(inspector, /大小也按同一比例缩放/, "悬停里没说大小也跟");
assert.match(inspector, /主遮罩转了时，角度跟着它转/, "悬停里没说角度也跟");
// 1.241：转了的主遮罩烘出来的窗带 follow——形状在图里，位置仍跟着中心平移。
assert.match(engine, /image: string; follow\?: boolean/, "窗的行里没有「跟不跟」这一格");
assert.match(picture, /follow: Boolean\(window\?\.follow\)/, "视图没有读那一格");
assert.match(picture, /if \(!row\.unit\) return row\.own && !row\.follow \? "0px 0px" : extraPosition;/, "跟随时那一窗没有按中心平移落位");

// ⑩ 1.242：框点的时间要**在条上看得见**，而每一块此刻怎么动也要写在它自己那一行。
// 这一节同时钉住「只切不动」那句假话的消失——那一条不是加了一句新说明，是删掉一句旧的。
assert.doesNotMatch(timeline, /只切不动/, "时间线上也在说「只切不动」");
assert.match(inspector, /extra_mask_follow_motion/, "悬停不看引擎那一格就开始承诺「先跟后动」");
assert.match(inspector, /打了框点的块也一起被带着走（先跟后动）/, "认得这一格的引擎没说清它会带着走");
assert.match(inspector, /className="mask-stack-state dim"/, "每一块没有写它此刻怎么动");
assert.match(inspector, /extraMotionWords\(item\.keys\?\.length \?\? 0/, "那一块怎么走又回到界面自己拼了");
assert.doesNotMatch(inspector, /"跟随主遮罩"/, "界面又把那四种说法各抄了一遍");
// 行为而不是字面量：四种情形各问一次那一个主人。
assert.equal(extraMotionWords(3, true, true), "先跟后动 · 3 枚框点", "引擎认得这一格时不说「先跟后动」");
assert.equal(extraMotionWords(3, true, false), "自己走 · 3 枚框点", "引擎不认那一格时界面不许承诺带着走");
assert.equal(extraMotionWords(3, false, true), "自己走 · 3 枚框点", "没勾跟随也不许说带着走");
assert.equal(extraMotionWords(0, true, true), "跟随主遮罩", "没框点时那一句要回原样");
assert.equal(extraMotionWords(0, false, false), "静止", "两样都没有时得说静止");
assert.match(timeline, /const boxKeyRows = \(clip\.extra_masks \?\? \[\]\)/, "条上没有从再叠的遮罩取框点");
assert.match(timeline, /className="clip-boxkeys" role="group"/, "条顶上那一排点没有画");
// 真看得见才算数：那一排的 AX 计数由扫描那一腿量（`axButtons`），判据在 tests/ui_shape_check.py。
assert.doesNotMatch(timeline, /className="clip-boxkeys" role="img"/,
  "带子又是 role=img——它的孩子现在是真的按钮，那一代会把整棵子树从辅助技术里藏掉（读屏摸不到那只手）");
// 1.261 之后那一格折成百分比之前先过一只手：拖的那一枚画在指针的落点上（live），没拖的就是它自己的时刻。
assert.match(timeline, /\(live \/ clip\.duration_ticks\) \* 100/, "点的位置不是按片段本地刻度折的");
assert.match(timeline, /再叠的遮罩框点：\$\{boxKeyWords\}/, "整段的悬停里没有列出框点的时间");
assert.match(timeline, /打点、改插值与删除在检查器「再叠的遮罩」那一格/, "悬停里没有指一条真走得通的编辑路");
assert.match(css, /\.clip-boxkeys\s*\{[^}]*pointer-events: none/, "那一排点接了指针——片段顶上会多出一块拖不动的死区");
assert.match(css, /\.clip-boxkey::after\s*\{[^}]*background: var\(--accent\)/, "点不用主题色（那颗点是 ::after 画的那一颗）");
assert.match(css, /\.clip-boxkeys\s*\{[^}]*left: 7px; right: 7px/, "那一排点没有让开两头的修剪柄");

// ⑪ 1.243：播放头停在框点那一帧时，卡片上五个数就是**那一枚**——引擎有框点就不读静止值了，
// 界面再显示静止值就不是「执行的那个数」。选择只在 `boxKeyAt` 一处，这里先把它当行为验。
const stacked: ShapeMask = {
  shape: "rectangle", center_x: 0.5, center_y: 0.5, width: 0.3, height: 0.2,
  rotation: 0, feather: 0, inverted: false,
  keys: [
    { at_ticks: 0, center_x: 0.4, center_y: 0.4, width: 0.2, height: 0.2, rotation: 0, interpolation: "linear" },
    { at_ticks: 70_560_000, center_x: 0.6, center_y: 0.6, width: 0.4, height: 0.4, rotation: 10, interpolation: "ease" },
  ],
};
assert.equal(boxKeyAt(stacked, 0)?.width, 0.2, "停在第一枚框点上，交回的不是那一枚");
assert.equal(boxKeyAt(stacked, 70_560_000)?.center_x, 0.6, "停在第二枚框点上，交回的不是那一枚");
assert.equal(boxKeyAt(stacked, 70_560_001), undefined, "两枚之间也交回了一枚——卡片会显示一个并不在这一帧上的数");
assert.equal(boxKeyAt({ ...stacked, keys: [] }, 0), undefined, "没有框点时交回了一枚不存在的针");
// 1.247：选择仍是同一处，只是现在收「播放头原刻度」与「取整到的那一帧」两把尺子。
assert.match(inspector, /const atKey = boxKeyForPlayhead\(item, exact, at\);/, "检查器没有用那一处选择（自己又 find 一遍就是第二个主人）");
assert.match(inspector, /value=\{\(atKey \?\? item\)\[field\] \* 100\}/, "五个数没有按「停在这一枚就用这一枚」显示");
assert.match(inspector, /value=\{atKey \? atKey\.rotation \?\? 0 : item\.rotation \?\? 0\}/, "角度那一格没有跟着框点走");
assert.match(inspector, /const commitBox = \(index: number, atKey: MaskBoxKey \| undefined, field: BoxField, value: number\)/,
  "改那五个数没有一处共同的分岔");
assert.match(inspector, /if \(atKey\) patchKey\(index, atKey\.at_ticks, next\);/, "停在框点上时改的仍是静止值");
assert.match(inspector, /const patchKey = \(index: number, atTick: number, part: Partial<MaskBoxKey>\)/, "没有写回框点的那一处");
assert.match(inspector, /if \(keys\.some\(\(key\) => key\.at_ticks === at\)\) return;/, "这一帧已有框点时，「打点」仍会拿静止值把它盖掉");
assert.match(inspector, /\|\| Boolean\(atKey\)\}/, "这一帧已有框点时，那颗打点按钮没有灰掉");
assert.match(inspector, /这一帧已有框点/, "按钮没有把「这一帧已经有了」写在眼前");
assert.match(inspector, /上面 \$\{keyCells\} 个数改的是这一枚/, "没有说清那几个数此刻改的是哪一枚");
assert.match(inspector, /上面 \$\{keyCells\} 个数是模板值/, "停在两枚之间时没有说清那几个数此刻只是模板");
assert.match(inspector, /className=\{key\.at_ticks === active \? "current" : undefined\}/, "当前那一枚框点在表里没有标出来");
assert.match(inspector, /aria-current=\{key\.at_ticks === active \? "true" : undefined\}/, "当前那一枚对读屏没有交代");
assert.match(css, /\.mask-stack-at\s*\{[^}]*text-overflow: ellipsis/, "那一句窄了不省略，会把那一行挤成第二行");
assert.match(css, /\.mask-stack-keylist li\.current \.btn\s*\{[^}]*border-color: var\(--accent\)/, "当前那一枚没有自己在表里亮起来");

// ⑫ 1.247：框点可以落在两帧之间（引擎只查范围与次序）。点开这样一枚时播放头精确落在它的 tick 上，
// 按取整后的帧去找会落空——那正是「点了一枚，卡片却在显示静止值」。两把尺子一起问。
const between: ShapeMask = {
  ...stacked,
  keys: [
    { at_ticks: 0, center_x: 0.4, center_y: 0.4, width: 0.2, height: 0.2, rotation: 0, interpolation: "linear" },
    { at_ticks: 100, center_x: 0.45, center_y: 0.4, width: 0.25, height: 0.2, rotation: 3, interpolation: "ease" },
    { at_ticks: 70_560_000, center_x: 0.6, center_y: 0.6, width: 0.4, height: 0.4, rotation: 10, interpolation: "ease" },
  ],
};
assert.equal(boxKeyForPlayhead(between, 100, 0)?.center_x, 0.45, "点开两帧之间那一枚时没有认出它");
assert.equal(boxKeyForPlayhead(between, 0, 0)?.center_x, 0.4, "整帧上那一枚反而认不出来了");
assert.equal(boxKeyForPlayhead(stacked, 100, 35_280_000), undefined, "两把尺子都落空时也交回了一枚键");
assert.equal(boxKeyForPlayhead(between, 100, 70_560_000)?.center_x, 0.45, "精确刻度优先于整帧刻度这一条被弄反了");
assert.match(inspector, /const atKey = boxKeyForPlayhead\(item, exact, at\);/, "检查器没有用两把尺子那一处");
assert.match(inspector, /const exact = Math\.max\(0, Math\.min\(clip\.duration_ticks, play\.ticks - clip\.position_ticks\)\);/, "没有取播放头的原刻度");
assert.match(inspector, /const active = atKey\?\.at_ticks \?\? at;/, "当前那一枚没有按真正的键刻度算");
assert.match(inspector, /className=\{key\.at_ticks === active \? "current" : undefined\}/, "表里当前那一枚的标记没跟着变");
assert.match(inspector, /aria-current=\{key\.at_ticks === active \? "true" : undefined\}/, "读屏那一格没跟着变");

// ⑬ 1.248：同一帧里的两枚框点时间码一样，表里要能看出它们不是同一刻。
assert.equal(offsetWords(1_176_000, { numerator: 30, denominator: 1 }), "16.7 毫秒", "半帧的字面数不对");
assert.match(inspector, /key\.at_ticks % frame\s*\?/, "非整帧的框点没有标出差的这一点");
assert.match(inspector, /offsetWords\(key\.at_ticks % frame, rate\)/, "差的那一点没有用已有的字面化工具");
assert.match(inspector, /className="mask-stack-sub"/, "那一点没有自己的样式");
assert.match(css, /\.mask-stack-sub\s*\{[^}]*color: var\(--ink-3\)/, "那一点没有退一档颜色");
// ⑮ 1.250：一块可以整份复制一份（框点也带走），新那块往右下挪一点。
assert.match(inspector, /aria-label=\{`复制第 \$\{index \+ 1\} 块叠加遮罩`\}/, "没有复制一块的入口");
assert.match(inspector, /disabled=\{disabled \|\| full \|\| limit === 0\}/, "复制那一颗的灰掉条件不对");
assert.match(inspector, /const nudge = \(value: number\) => Math\.min\(1, value \+ 0\.04\)/, "新一块没有挪一点");
assert.match(inspector, /write\(\[\.\.\.stack, \{ \.\.\.item,/, "复制没有走那一条整串写入");
assert.match(inspector, /center_x: nudge\(item\.center_x\), center_y: nudge\(item\.center_y\)/, "静止的中心没有挪");
assert.match(inspector, /keys: \(item\.keys \?\? \[\]\)\.map\(\(key\) => \(\{ \.\.\.key,/, "框点没有随着复制");
// ⑯ 1.252：画面里先选中一块，再拖它那一颗柄——只画选中那一块，且拓取期间在 window 上听。
assert.match(store, /maskExtraSel: \{ clipId: string; index: number \} \| null;/, "应用状态里没有画面选中的那一块");
assert.match(store, /export function selectMaskExtra\(clipId: string, index: number \| null\)/, "没有选中那一块的写口");
assert.match(inspector, /selectMaskExtra\(clip\.id, pickedExtra \? null : index\)/, "检查器没有把选中交出去");
assert.match(inspector, /if \(!pickedExtra\) setMaskEditing\(true\);/, "选中时没有把画面中编辑打开");
assert.match(picture, /const selectedIndex = app\.maskExtraSel\?\.clipId === clip\.id \? app\.maskExtraSel\.index : null;/, "画面没有认选中的那一块");
assert.match(picture, /const selectedFrameTick = Math\.min\(clip\.duration_ticks, Math\.round\(localAt \/ frame\) \* frame\);/, "画面里那一枚的落点没有折到整帧上");
assert.match(picture, /boxKeyForPlayhead\(selectedExtra, localAt, selectedFrameTick\)/, "画面没有用那一处键的选择");
assert.match(picture, /const extraDrawable = Boolean\(visible && selectedExtra && extraBox && !follow && !disabled/, "可拖的条件不对");
assert.match(picture, /window\.addEventListener\("pointermove", move\);/, "拓取期间没有在 window 上听");
assert.match(picture, /const box = draft\?\.index === gesture\.index \? draft\.box : null;/, "松手没有读最后一次草稿");
assert.match(picture, /if \(keyTick !== null\) return \{ \.\.\.row,/, "停在框点上时没有写回那一枚");
assert.match(picture, /setClipMaskStack\(clip\.id, masks, follow, projectId, revision\)/, "松手没有走那一条写入");
assert.match(picture, /follow, projectId, revision\);\s*\};/, "写入没有用按下那一刻记下的那份工程与版本");
assert.match(picture, /y=\{top\.y \* 100 - hs\.y \/ 2\}/, "柄不在盒子的上边中点");
assert.match(css, /\.mask-extra-handle\s*\{[^}]*cursor: move/, "柄没有自己的命中与指针");
// ⑰ 1.253：转过角度的那一块照**画面里**那个角度画，四个角各有一颗缩放柄——拖动按未转的盒算，
// 中心柄仍只搬中心。画框是拉伸的，所以那一圈与主遮罩共用同一份 k 换算；少了 k 这一项，
// 方画幅上看着没事，16:9 里拖角就上下跑偏。
const k = 9 / 16, angle = 37;
const plan = { center_x: .5, center_y: .45, width: .4, height: .3 };
const points = rotatedBoxPoints(plan, k, angle);
const rad = angle * Math.PI / 180;
[[-1, -1], [1, -1], [1, 1], [-1, 1]].forEach(([sx, sy], index) => {
  const bx = sx * plan.width / 2, by = sy * plan.height / 2;
  const forward = { x: plan.center_x + bx * Math.cos(rad) - by * k * Math.sin(rad),
    y: plan.center_y + bx * Math.sin(rad) / k + by * Math.cos(rad) };
  assert.ok(Math.abs(points[index].x - forward.x) < 1e-12 && Math.abs(points[index].y - forward.y) < 1e-12,
    `第 ${index + 1} 个角不是按 k 那条式子落位的`);
  const back = boxVectorFromPointer(points[index].x - plan.center_x, points[index].y - plan.center_y, angle, k);
  assert.ok(Math.abs(back.x - bx) < 1e-12 && Math.abs(back.y - by) < 1e-12,
    `第 ${index + 1} 个角折回未转的盒时没有走同一条式子的逆`);
});
const corner = points[2];
const dx = corner.x - plan.center_x, dy = corner.y - plan.center_y;
const naive = { x: dx * Math.cos(-rad) - dy * Math.sin(-rad), y: dx * Math.sin(-rad) + dy * Math.cos(-rad) };
assert.ok(Math.abs(naive.x - plan.width / 2) + Math.abs(naive.y - plan.height / 2) > .01,
  "少了 k 那一项也能折回原处——这一档就证明不了那条修正是承重的");
assert.match(picture, /const points = rotatedBoxPoints\(box, pictureRatio, angle\);/, "那一圈没有用画面比例折出来的四个角");
assert.match(picture, /const mid = rotatedEdgeMids\(box, pictureRatio, angle\);/, "搬中心那颗柄没有落在看见的那条上边中点");
assert.match(picture, /x=\{points\[index\]\.x \* 100 - hs\.x \/ 2\}/, "四颗角柄没有落在那四个角上");
assert.doesNotMatch(picture, /transform=\{`rotate\(/, "那一圈仍靠 SVG 的 rotate 画——画框是拉伸的，画出来不是那个盒");
assert.match(picture, /const beginExtra = \(event: PointerEvent<SVGElement>, corner: \[number, number\] \| null, rotate = false\) =>/, "按下那一刻没有收「抓的是哪一角」");
assert.match(picture, /onPointerDown=\{\(event\) => beginExtra\(event, \[sx, sy\]\)\}/, "四颗角柄没有把抓的是哪一角交出去");
assert.match(picture, /aria-label=\{`缩放选中的再叠遮罩（第 \$\{selectedIndex! \+ 1\} 块·\$\{label\}）`\}/, "角柄没有自己的名字");
assert.match(picture, /const at = boxVectorFromPointer\(point\.x \/ 100 - gesture\.box\.center_x,/, "缩放的指针没有折回未转的盒坐标系");
assert.match(picture, /angle: extraBox\.rotation \?\? 0, k: pictureRatio,/, "抓取那一刻没有记下这一盒的角度与画面比例");
assert.match(picture, /const ax = gesture\.box\.center_x - sx \* gesture\.box\.width \/ 2;/, "对角那一点不是按未转的盒算的");
assert.match(picture, /width: clamp\(Math\.abs\(ux - ax\), \.01, 2\),/, "两条边没有按对角现算");
assert.match(picture, /\.\.\.\(gesture\.corner \? \{ width: box\.width, height: box\.height \} : \{\}\)/, "中心柄松手也写了宽高——只搬中心那一手会顺手改大小");
assert.match(picture, /if \(keyTick !== null\) return \{ \.\.\.row,/, "缩放没有落到停着的那一枚框点上");
assert.match(css, /\.mask-extra-handle\.corner\s*\{[^}]*cursor: crosshair/, "角柄的指针没有跟「盒可能转着」的说法对上");
// ⑱ 1.254：选中那一块也有一颗角度柄——写的仍是那一处，但角度读的是**画框坐标系里**指针的方向。
// 第一版按屏幕像素除 a、d 读角（主遮罩那条式子），量到的正是：屏幕拖 +20°、引擎落 +11.8°、
// 柄停在指针后面 8°——因为这一层挂着片段自己的旋转。茎的用户坐标方向恒为 (k·sinθ, −cosθ)，
// 所以 atan2(dx/k, −dy) 才是它的精确逆；轴对齐的那一层上，这一条与 `rotateAngleFromPointer` 同一个数。
for (const angle of [0, 12.5, 37, -80]) {
  const rad = angle * Math.PI / 180;
  const ux = (9 / 16) * Math.sin(rad), uy = -Math.cos(rad);
  assert.ok(Math.abs(stemAngleFromUser(ux, uy, 9 / 16) - angle) < 1e-9,
    `盒转 ${angle}° 时那根茎的方向读回来不是它自己`);
  // 同一支针在轴对齐的那一层上：两条式子必须给同一个数（主遮罩那颗手柄的签收账不许被改坏）。
  const a = 4.19, d = 2.35;
  assert.ok(Math.abs(rotateAngleFromPointer(ux * a * 100, uy * d * 100, a, d, 9 / 16)
    - stemAngleFromUser(ux, uy, 9 / 16)) < 1e-9, "两条式子在轴对齐的层上分家了");
}
assert.match(picture, /const extraPointerAngle = \(box: ShapeMask, inverse: DOMMatrix, clientX: number, clientY: number\) =>/, "那颗柄没有先落回画框坐标");
assert.match(picture, /return stemAngleFromUser\(point\.x \/ 100 - box\.center_x, point\.y \/ 100 - box\.center_y, pictureRatio\);/, "盒角不是从茎的那条精确逆读回来的");
assert.match(picture, /angle0: rotate \? extraPointerAngle\(extraBox, inverse, event\.clientX, event\.clientY\) : null/, "按下那一刻没有用**按下时那份逆矩阵**记起始角");
assert.match(picture, /const angle = extraPointerAngle\(gesture\.box, gesture\.inverse, clientX, clientY\);/, "拖动中途换了坐标系（这一层挂着片段自己的旋转/缩放）");
assert.match(picture, /onPointerDown=\{\(event\) => beginExtra\(event, null, true\)\}/, "那颗角度柄没有把「这是旋转」交出去");
assert.match(picture, /aria-label=\{`旋转选中的再叠遮罩（第 \$\{selectedIndex! \+ 1\} 块·此刻 \$\{angle\.toFixed\(1\)\}°）`\}/, "那颗柄没把「此刻是多少度」写在名字里");
assert.match(picture, /if \(delta > 180\) delta -= 360; else if \(delta < -180\) delta \+= 360;/, "转过 180° 时那一笔会跳一整圈");
assert.match(picture, /rotation: Math\.round\(clamp\(gesture\.angle \+ delta, -rotationLimit, rotationLimit\) \* 10\) \/ 10/, "角度没有按 0.1° 落笔、也没夹在引擎下发的上限里");
assert.match(picture, /const values = gesture\.rotate \? \{ rotation: box\.rotation \?\? 0 \}/, "那颗柄松手写的不是角度那一格");
assert.match(picture, /const writeExtra = \(index: number, keyTick: number \| null, values: Partial<ShapeMask>,/, "那一块的写入没有一处共同的主人");
assert.equal((picture.match(/setClipMaskStack\(/g) ?? []).length, 1, "再叠那一格出现了第二个写入口");
assert.match(picture, /writeExtra\(selectedIndex!, selectedKey\?\.at_ticks \?\? null, \{ rotation: next \}/, "那颗柄没有键盘孪生（±1°／Shift ±15°）");
assert.match(picture, /<line className="mask-extra-stem"/, "那颗柄与它那一圈之间没有一根茎（摆在哪看不出来）");
assert.match(css, /\.mask-extra-handle\.rotate-handle\s*\{[^}]*cursor: grab/, "那颗柄的指针没有跟「可以拖着转」的说法对上");
assert.match(css, /\.mask-extra-stem\s*\{[^}]*pointer-events: none/, "那根茎接了指针——它会吞掉它底下那一片的抓取");
// ⑲ 1.255：停在两枚框点**之间**也画那一框——画的是引擎窗表在这一格执行的那五个数，
// 拖它 = 在这一帧新打一枚框点（原来那几枚一字不动）。旧的那一条「画不出精确盒的帧就不画」撤了。
assert.match(engine, /box\?: ExtraMaskBox \| null/, "清单里那一窗没带上它执行的盒");
assert.match(picture, /rotationWindowAt\(extraWindows\?\.\[selectedIndex\] \?\? \[\], localAt\)/, "没有按播放头去引擎那份窗表里取这一格");
assert.match(picture, /const executedBox = selectedWindow\?\.box \?\? null;/, "那一框没有读窗表给的数（自己插值就是画导出没有的那一格）");
assert.match(picture, /executedBox && canInsert \? \{ \.\.\.selectedExtra, \.\.\.executedBox \} : selectedExtra/, "停在两枚之间时那一框画的不是执行的那一格");
assert.match(picture, /const canInsert = Boolean\(executedBox\) && \(selectedExtra\?\.keys\?\.length \?\? 0\) < extraKeyLimit;/, "新打那一枚没有数额度——满了还能插就是自己造一次必被拒的写入");
assert.match(picture, /app\.caps\?\.limits\?\.extra_mask_keys/, "额度不是引擎下发的那一份");
assert.match(picture, /insertAt: selectedKey \|\| !canInsert \? null : selectedFrameTick/, "没有定「这一拖是插一枚新的还是改停着的那一枚」");
assert.match(picture, /insertInterp: windowOwner\?\.interpolation \?\? "linear"/, "新那一枚的插值是自己编的，不是抄这一窗起点那一枚的");
assert.match(picture, /keys: \[\.\.\.\(row\.keys \?\? \[\]\), \{ at_ticks: at,/, "新那一枚没有并进这一块的框点里");
assert.match(picture, /\.sort\(\(a, b\) => a\.at_ticks - b\.at_ticks\)/, "插进去的框点没有按时刻排（引擎认的是有序的一串）");
assert.match(picture, /\) \|\| selectedKey \|\| canInsert\)/, "可拖的条件没给「停在两枚之间」这一格让路");
assert.match(inspector, /拖它会在这一帧新打一枚框点/, "检查器那一句没说清拖画面里那一框会发生什么");
assert.equal((picture.match(/setClipMaskStack\(/g) ?? []).length, 1, "插入这一手又长出第二个写入口");
// ⑳ 1.256：按住 Alt 拖那一框 = 先复制这一块再拖副本（AE 的那一只手）。
// 块数到顶时这一只手**不摆出来**，而不是偷偷退回普通拖动；拖的过程中原来那一框留在原地。
assert.match(picture, /const extraStackLimit = app\.caps\?\.limits\?\.extra_masks \?\? 0;/, "块数上限不是引擎下发的那一份");
assert.match(picture, /const canDuplicate = Boolean\(selectedExtra\) && \(clip\.extra_masks\?\.length \?\? 0\) < extraStackLimit;/, "到顶时这一只手没有被收掉");
assert.match(picture, /duplicate: rotate \? false : event\.altKey && canDuplicate,/, "按下那一刻没有记下「这是 Alt 那一手」（中途换 Alt 会改语义）");
assert.match(picture, /const mode = gesture\.duplicate \? "append" : "replace";/, "松手没有按按下那一刻定下来的那一种写法走");
assert.match(picture, /const masks = mode === "append" \? \[\.\.\.stack, mutate\(source\)\]/, "副本没有带着改完的数排在末尾");
assert.match(picture, /if \(!source\) return;/, "副本那一手在没有这一块时也会发一笔写入");
assert.match(picture, /\{ghost \? <polygon className="mask-extra-outline ghost" points=\{ghost\} \/> : null\}/, "拖副本时原来那一框没有留在原地");
assert.match(picture, /按住 Alt 拖 = 先复制这一块，再拖那一副本。/, "那颗柄没说 Alt 这一只手");
assert.match(picture, /块上限，Alt 这一手用不了：先在检查器删掉一块。/, "到顶时没说清这一只手为什么没有");
assert.match(css, /\.mask-extra-outline\.ghost\s*\{[^}]*opacity: \.4/, "副本那一框没有自己的淡档（与真身分不清）");
assert.equal((picture.match(/setClipMaskStack\(/g) ?? []).length, 1, "Alt 这一手又长出第二个写入口");

// ㉑ 1.257：框点也能带贝塞尔——名单、那四格的带、默认柄，都只有一处主人；两端读的是同一张窗表。
assert.deepEqual(maskBoxInterpolations(null), ["linear", "hold", "ease"],
  "没回名单的旧引擎那一头，兜底必须是它当时认的那三种");
assert.deepEqual(maskBoxInterpolations({ mask_box_interpolations: ["linear", "bezier"] } as unknown as Capabilities),
  ["linear", "bezier"], "引擎点了名还被界面自己改了一份——那张名单就不是唯一的主人");
assert.deepEqual(BEZIER_AXES.map((axle) => axle.axis), ["x1", "y1", "x2", "y2"],
  "那四格的名字或次序变了：曲线编辑器与检查器是在读同一张表");
assert.deepEqual([...bezierBand("y1")], [-4, 4], "数值那两格的带不对");
assert.deepEqual([...bezierBand("x2")], [0, 1], "时间那两格的带不对");
assert.equal(DEFAULT_BEZIER.x1, 1 / 3, "默认柄与契约那一份不是同一个数");
assert.equal((effects.match(/export const DEFAULT_BEZIER/g) ?? []).length, 1, "默认柄有第二处主人");
assert.doesNotMatch(curve, /const DEFAULT_BEZIER/, "曲线编辑器又自己抄了一份默认柄");
assert.doesNotMatch(curve, /startsWith\("x"\)/, "曲线编辑器里还留着「x 就是 0..1」那份第二处判断");
assert.match(curve, /BEZIER_AXES\.map/, "曲线编辑器那四格没有读那张表");
assert.match(curve, /bezierBand\(control\[0\]\)/, "拖动落回时没有按那张表夹");
assert.match(effects, /caps\?\.mask_box_interpolations\?\.length/, "名单没有读引擎那一份");
assert.equal((effects.match(/\["linear", "hold", "ease"\]/g) ?? []).length, 1, "旧引擎的兜底名单写了第二份");
assert.match(inspector, /boxInterpolations\.map\(\(value\) => <option key=\{value\} value=\{value\}>/,
  "那一格没有按引擎点名的名单排选项");
assert.match(inspector, /bezier: next === "bezier" \? row\.bezier \?\? DEFAULT_BEZIER : null/,
  "换缓动时柄没跟着走（选了贝塞尔却没有柄、换走了还留着柄都是第二种状态）");
assert.match(inspector, /key\.interpolation === "bezier" \? <div className="mask-stack-bezier"/,
  "选了贝塞尔却没把那四格画出来——人能选档却不能调，等于只有一端会执行");
assert.match(inspector, /\[axle\.axis\]: percent \/ 100/,
  "那一格写的不是百分数换算后的那一个数（界面自己再造一套刻度）");
assert.match(picture, /insertBezier: windowOwner\?\.bezier \?\? null,/,
  "画面里新打那一枚没有带走这一窗起点那一段的柄");
assert.match(picture, /bezier: gesture\.insertInterp === "bezier" \? gesture\.insertBezier \?\? DEFAULT_BEZIER : null,/,
  "新打那一枚在贝塞尔那档写了空柄");
assert.match(css, /\.mask-stack-bezier \{[^}]*font-size: var\(--fs-label\)/,
  "那一行的小字没有走刻度");
assert.match(css, /\.mask-stack-keylist li \{[^}]*flex-wrap: wrap/,
  "那一格不换行——四格挤在同一个不换行的 flex 里会被切（1.210 同一类）");

// ㉒ 1.258：那一串框点也可以带软边——两端读的是同一张窗表里的那一格。
const contractsSrc = read("src/agentcut/contracts.py", "../../src/agentcut/contracts.py");
const animationSrc = read("src/agentcut/animation.py", "../../src/agentcut/animation.py");
const renderSrc = read("src/agentcut/render.py", "../../src/agentcut/render.py");
const masksSrc = read("src/agentcut/masks.py", "../../src/agentcut/masks.py");
const projectsSrc = read("src/agentcut/projects.py", "../../src/agentcut/projects.py");
assert.match(contractsSrc, /feather: Annotated\[float \| None, Field\(ge=0, le=1\)\] = None/,
  "框点没有软边这一格，或它不是「没写就用这一块静止的那个数」那个意思");
assert.match(contractsSrc, /def box_value\(extra, key, name: str\)/,
  "「没写的那一格归谁」没有一处主人");
assert.match(contractsSrc, /MASK_BOX_VALUES = tuple\(MASK_FIELDS\)/,
  "那一串数的名字不是从主遮罩那六个数折出来的（1.259 起它是一个主人）");
assert.match(contractsSrc, /start = box_value\(self, left, name\)/,
  "越界那一条没问 box_value，自己在判羽化写没写");
assert.match(engine, /feather\?: number \| null/, "渲染层的框点类型不认识软边这一格");
assert.match(engine, /rotation: number; feather\?: number/, "窗表那一行的类型没有软边");
assert.match(animationSrc, /MASK_EXTRA_FIELDS = \("center_x", "center_y", "width", "height", "rotation", "feather"\)/,
  "窗表那一串数不是那六个");
assert.match(animationSrc, /box_value\(extra, left, name\)/,
  "采样那一路没问 box_value");
assert.doesNotMatch(animationSrc, /extra\.feather if|key\.feather is not None/,
  "animation 里又写了一遍「没写就用静止值」——那一句只能有一个主人");
assert.match(renderSrc, /for index, name in enumerate\(MASK_BOX_VALUES\)/,
  "导出那一步还在按主遮罩那五个数取值名");
assert.match(masksSrc, /def _feather_term\(feather: str\)/, "那条斜坡的写法没有一处主人");
assert.match(masksSrc, /if _is_number\(feather\) else f"max\(\{feather\},1e-4\)"/,
  "一个数没化成字面量，或一条式子没带那个下限");
assert.match(masksSrc, /\(values or \{\}\)\.get\("mask_feather"\)/, "alpha 那一路没读窗表里的软边");
assert.match(projectsSrc, /node\.pop\("feather", None\)/,
  "没写软边的旧回执会被这一版裂成两笔");
assert.match(inspector, /const featherOnKey = Boolean\(app\.caps\?\.features\?\.extra_mask_feather\)/,
  "那一句「上面几个数」不是引擎那一格认不认得决定的");
assert.match(inspector, /const keyCells = featherOnKey \? 6 : 5/,
  "那一格数的是几个数是界面自己写死的");
assert.match(inspector, /\.\.\.\(featherOnKey \? \{ feather: item\.feather \} : \{\}\)/,
  "「在播放头打框点」没有把这一块现在的软边一起记进去");
assert.match(inspector, /atKey && featherOnKey \? atKey\.feather \?\? item\.feather : item\.feather/,
  "停在框点那一帧时，羽化那一格显示的不是这一枚");
assert.match(inspector, /patchKey\(index, atKey\.at_ticks, \{ feather: value \/ 100 \}\)/,
  "停在框点那一帧改羽化时没写回这一枚");
assert.match(picture, /featherOnKey && typeof selectedKey\.feather === "number"/,
  "画面上那一框停在框点时没有读这一枚的软边");
assert.match(picture, /feather: box\.feather \?\? row\.feather/,
  "画面里新打的那一枚没有带走这一窗的软边");
assert.equal((inspector.match(/op: "clip\.mask_stack"/g) ?? []).length, 0,
  "检查器不许绕过那一处写入口");

// ㉓ 1.259：主遮罩的软边也能打点——那条斜坡烘在引擎那张板里，所以它走的是按窗换图那一路。
// 这一节钉的是「谁说话」：名单、那条带、开关、第四格的位置，以及界面那一格只在引擎认得时出现。
assert.match(contractsSrc,
  /MaskProperty = Literal\[\s*"mask_x", "mask_y", "mask_width", "mask_height", "mask_rotation", "mask_feather"/,
  "能打点的遮罩属性名单里没有软边，或次序不是那张名字表的次序");
assert.match(contractsSrc, /"mask_feather": "feather",/, "那条属性没有唯一的字段名映射");
assert.match(contractsSrc, /"mask_feather": \(0\.0, 1\.0\),/,
  "软边曲线没有那条带，或它与那一格自己声明的不是同一条");
assert.match(contractsSrc, /"mask_feather_curves": True,/, "开关没进能力表");
assert.match(contractsSrc, /key\.property in \("mask_rotation", "mask_feather"\) for key in self\.keyframes/,
  "路径遮罩只挡角度不挡软边——它会写下一张导出与预览都画不出的窗表");
assert.match(animationSrc, /BOX_STEPS = \("mask_rotation", "mask_width", "mask_height", "mask_feather"\)/,
  "那张窗表走的数里没有软边，或次序变了");
assert.match(animationSrc, /if not rotated_box\(clip\) and not points\(clip, "mask_feather"\):/,
  "不转的盒带软边曲线时被挡在窗表之外——预览就没有那条斜坡");
assert.match(animationSrc, /for prop in BOX_STEPS\)/, "采样那一路没有按那张名单走");
assert.doesNotMatch(animationSrc, /for prop in \("mask_rotation", "mask_width", "mask_height"\)/,
  "又一处自己列那三个数——加一个数就要改两遍");
assert.equal((animationSrc.match(/"feather": window\["value"\]\[3\],/g) ?? []).length, 2,
  "窗那一行与烘图那一步不是同一个数（一处 2 次：行里一次、图里一次）");
assert.match(animationSrc, /angle, width, height = window\["value"\]\[:3\]/,
  "跟随那一路按位置读三个数时把软边也算给了这一块——它读的是自己那一个");
assert.doesNotMatch(animationSrc, /= window\["value"\]\r?\n/,
  "还有整串解包：窗表多一个数就在这里抛 ValueError，清单 500、监视器整块黑（本轮量到的那一条）");
assert.match(engine,
  /export type MaskProperty = "mask_x" \| "mask_y" \| "mask_width" \| "mask_height" \| "mask_rotation" \| "mask_feather";/,
  "渲染层的属性类型不认识软边这一条曲线");
assert.match(engine, /mask_feather: number/, "逐帧采样的那一份回执里没有软边这一格");
assert.match(effects,
  /property: "mask_feather", label: "遮罩羽化", unit: "%", min: 0, max: 100, step: 1, factor: 100, field: "feather"/,
  "那张名单里没有软边那一行，或它带的数不是引擎那条带的百分数形式");
assert.equal((effects.match(/"遮罩羽化"/g) ?? []).length, 1, "软边这个名字有第二处主人");
assert.match(effects, /const featherCurves = Boolean\(caps\?\.features\.mask_feather_curves\)/,
  "那一行出现与否不是引擎那一格决定的");
assert.match(effects, /row\.property === "mask_feather"\s*\r?\n\s*\? featherCurves && mask\.shape !== "path"/,
  "路径遮罩那一行没被挡掉——摆了就是引擎必拒的一枚 ◇");
assert.match(inspector, /\['feather', '向内羽化', 0, 100, 'mask_feather'\]\] as const/,
  "主遮罩那一格的行名单里没有软边");
assert.match(inspector, /const boxRows = mask && canAnimateMask\(mask\) \? maskRows\(mask, app\.caps\) : \[\];/,
  "那一串行没有折一次——`maskRows` 少递 caps 正是 1.166 那一族");
assert.equal((inspector.match(/maskRows\(/g) ?? []).length, 1,
  "折行那一步有了第二个调用处——1.166 那一族就是「函数对、调用点各算各的」");
assert.match(inspector, /const staticFeather = Boolean\(mask\) && !boxRows\.some\(\(row\) => row\[0\] === "feather"\);/,
  "那一格不进曲线时（路径遮罩、老引擎）没有退回「只改静止值」那一种");
assert.match(inspector, /\{staticFeather && mask \? <div className="effect-row"><label htmlFor="mask-feather">/,
  "静止那一格的出没跟着上面那条判断走");
assert.match(inspector, /MASK_ROWS\.filter\(\(row\) => row\[0\] !== "feather"\)/,
  "再叠那一块的格子又走了一遍通用行——软边在框点上是可缺省的，那一格自己管");
assert.match(picture, /type MaskBoxProperty = Exclude<MaskProperty, "mask_rotation" \| "mask_feather">;/,
  "软边被当成一个 CSS 量能表达的量");
assert.match(picture, /property !== "mask_rotation" && property !== "mask_feather"/,
  "逐帧那条动画里又给软边写了一个 CSS 变量——画面上会是一条引擎没有的斜坡");
assert.doesNotMatch(picture, /--mask-feather/, "界面上造了一个第二条斜坡的刻度");

// ⑰ 1.261：条上那一枚框点现在是一只手——横向拖只改它自己的时刻。
// 判的是行为（真调用那一个规划函数），不是字面量；接线只钉「落库走那唯一的写入口」与
// 「命中盒那一个数只有一个主人」。
const boxKey = read("desktop/src/boxKeyDrag.ts", "../../desktop/src/boxKeyDrag.ts");
const FRAME = 70_560_000 / 24;          // 24 fps 的一帧（夹具的帧率）
const SPAN = 4 * 70_560_000;            // 片段长 4 秒
const at = (seconds: number) => Math.round(seconds * 70_560_000);
const stack: ShapeMask[] = [
  {
    shape: "rectangle", center_x: 0.55, center_y: 0.5, width: 0.3, height: 0.34, feather: 0, inverted: false,
    keys: [
      { at_ticks: at(0), center_x: 0.55, center_y: 0.5, width: 0.3, height: 0.34, interpolation: "linear" },
      { at_ticks: at(2), center_x: 0.55, center_y: 0.5, width: 0.3, height: 0.34, interpolation: "ease" },
      { at_ticks: at(3.6), center_x: 0.62, center_y: 0.5, width: 0.3, height: 0.34, interpolation: "hold" },
    ],
  },
  {
    shape: "ellipse", center_x: 0.2, center_y: 0.3, width: 0.1, height: 0.1, feather: 0.1, inverted: true,
    keys: [{ at_ticks: at(1), center_x: 0.2, center_y: 0.3, width: 0.1, height: 0.1, interpolation: "linear" }],
  },
];
const gesture = (over: Record<string, unknown>) => ({
  id: "k2", duration_ticks: SPAN, position_ticks: 0, stack,
  block: 0, index: 1, px: 62, quantum: FRAME, snap: true, playhead: null, attract: true, ...over,
});
const middle = (masks: ShapeMask[], index: number) => masks[0].keys![index];

const moved = planBoxKeyDrag(gesture({ pointer_ticks: at(2) + FRAME }));
assert.equal(moved.kind, "move", "往右一帧没有交出一条移动");
if (moved.kind === "move") {
  assert.equal(moved.at, at(2) + FRAME, "落点不是那一帧");
  assert.equal(moved.masks.length, stack.length, "整串少了块");
  assert.deepEqual(middle(moved.masks, 0), stack[0].keys![0], "同一块的前一枚被顺手动了");
  assert.deepEqual(middle(moved.masks, 2), stack[0].keys![2], "同一块的后一枚被顺手动了");
  assert.deepEqual(moved.masks[1], stack[1], "另一块被顺手动了");
  assert.deepEqual(middle(moved.masks, 1), { ...stack[0].keys![1], at_ticks: at(2) + FRAME },
    "那一枚只该换时刻，那四个数得原样带走");
}
assert.equal(planBoxKeyDrag(gesture({ pointer_ticks: at(2) })).kind, "noop", "回原格也发了一条命令");
const clash = planBoxKeyDrag(gesture({ pointer_ticks: at(3.6) }));
assert.equal(clash.kind, "blocked", "拖到另一枚框点停的那一格，界面还发出去了");
if (clash.kind === "blocked") {
  assert.match(clash.reason, /另一枚框点/, "那句拒绝没说清是跟谁撞了");
  assert.match(clash.reason, /检查器/, "拒绝必须点名一条此刻真走得通的路");
}
const tail = planBoxKeyDrag(gesture({ pointer_ticks: SPAN + 40 * FRAME }));
assert.ok(tail.kind === "move" && tail.at <= SPAN && tail.at % FRAME === 0,
  "拖出段尾没有夹在引擎收得下的地方：" + JSON.stringify(tail));
assert.ok(tail.kind === "move" && tail.at !== stack[0].keys![2].at_ticks,
  "夹到的那一格正好是别人的位置——该先撞针再说");
const free = planBoxKeyDrag(gesture({ snap: false, pointer_ticks: at(2) + 123 }));
assert.ok(free.kind === "move" && free.at === at(2) + 123,
  "关掉吸附之后那条落点被界面自己改了：" + JSON.stringify(free));
const pull = planBoxKeyDrag(gesture({ pointer_ticks: at(2) + FRAME - 5_000, playhead: at(2) + FRAME - 5_000 + 1 }));
assert.ok(pull.kind === "move" && pull.at % FRAME !== 0,
  "播放头就在旁边却没吸过去（吸附的那一路没走）：" + JSON.stringify(pull));
const noPull = planBoxKeyDrag(gesture({ pointer_ticks: at(2) + FRAME - 5_000, playhead: at(2) + FRAME - 5_000 + 1, attract: false }));
assert.ok(noPull.kind === "move" && noPull.at % FRAME === 0,
  "键盘那一手不该被旁边的针与播放头拽走：" + JSON.stringify(noPull));

assert.doesNotMatch(boxKey, /op: "clip\.mask_stack"/,
  "规划那一手里构造了命令——再叠那一串就有了第二个写主人");
assert.match(timeline, /setClipMaskStack\(clip\.id, next\.masks, undefined, projectId, revision\)/,
  "拖那一枚没走那唯一的写入口，或没按按下那一刻记下的工程与版本写（那样会把别人的改动顶掉）");
assert.equal((timeline.match(/op: "clip\.mask_stack"/g) ?? []).length, 0,
  "时间线自己拼了一条 mask_stack 命令");
assert.match(timeline, /const style = \{ left: `\$\{\(live \/ clip\.duration_ticks\) \* 100\}%`, width: BOX_KEY_HIT_PIXELS\.width, height: BOX_KEY_HIT_PIXELS\.height \}/,
  "命中盒那一个数又有人自己写了一遍");
assert.match(timeline, /onPointerDown=\{\(event\) => startBoxKey\(event, row\.index, keyIndex, at\)\}/,
  "那一枚没有把手交出去");
assert.match(timeline, /event\.stopPropagation\(\);\s*\n\s*if \(razor \|\| event\.button !== 0 \|\| track\.locked \|\| !box\.current\) return;/,
  "按下没先收下这一次——片段的移动手势会把它吃掉（1.115 那一课）");
assert.match(timeline, /window\.addEventListener\("pointerup", stop\);\s*\n\s*window\.addEventListener\("pointercancel", stop\);\s*\n\s*\};\s*\n\s*\/\*\* 那一枚的键盘孪生/,
  "松手不在 window 上听——那一枚就永远不落库（1.252 那一课）");
assert.match(timeline, /className=\{`clip-boxkey\$\{held \? " held" : ""\}\$\{held && boxKeyDrag\?\.blocked \? " blocked" : ""\}`\}/,
  "拖的那一枚与撞针的那一枚在画面上没有分别");
assert.match(timeline, /if \(razor \|\| track\.locked\) return <span key=\{`\$\{row\.index\}-\$\{at\}`\} className="clip-boxkey static"/,
  "锁着的那一轨还在摆一颗点不动的按钮");

// 命中盒的数只有一个主人：样式表里不许再抄一遍宽高；带子仍不接指针，层号抬到修剪边之上。
assert.doesNotMatch(css, /\.clip-boxkey \{[^}]*(width|height):/,
  "样式表又写了一遍命中盒的宽高——那两个数就有两个主人");
assert.match(css, /\.clip-boxkey \{[^}]*pointer-events: auto[^}]*\}/, "那一枚不接指针，就还是画得见摸不着");
assert.match(css, /\.clip-boxkeys \{[^}]*pointer-events: none[^}]*\}/, "带子接了指针就是在片段顶上挖一块拖不动的死区");
assert.match(css, /\.clip-boxkeys \{[^}]*z-index: 5[^}]*\}/, "带子还在修剪边那一条下面——贴边那一枚点不到（实测过）");
assert.ok(BOX_KEY_HIT_PIXELS.height <= 5,
  "命中盒高过 5px 就压住名字那一行的墨（1.261 量的是卡片 y 2..7 那一格）");
assert.ok(css.includes(".clip-boxkey.blocked::after"), "撞针那一枚没有自己的样子");
assert.match(timeline, /if \(drawn\.get\(at\) !== row\.index\) return \[\];/,
  "同一格上两块各画一枚——低的那一枚点不到（1.213 给针立的那条规矩在这一格同样成立）");
assert.match(timeline, /没有画出来的：\$\{shadowWords\}/,
  "少画的那几枚没有名字——静悄悄少画与点不到同罪");
assert.match(timeline, /条上只画得下一枚，那几块在检查器各自那一行改/,
  "那一枚的悬停没有给少画的那几枚一条真走得通的路");


console.log("PASS: 叠加遮罩只有一处写入口、额度听引擎的、每一块的那几个数与反转都在格子里改、每一块可以打自己的框点、跟随时大小按同一比例缩放、框点的时间在条顶上看得见、那一枚横着拖就只改它自己的时刻、每一块都写明自己怎么动、停在框点上时那几个数改的就是那一枚且软边也在其中、浏览器叠的是引擎那几张图并取交集、每一层各用各的 mask-size/position、选中的那一块拖着中心走、转着的那一块按未转的盒缩放四个角、那颗角度柄与主遮罩共用同一份换算与同一个写入口、Alt 拖出来的是副本、框点那几种缓动与那四格的带只有一处主人、主遮罩的软边是那张窗表的第四个数且界面只在引擎认得时摆出那一格、样式仍走刻度");
