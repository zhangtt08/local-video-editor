// 1.221：一条片段再叠几块遮罩——界面写的是整串，浏览器叠的是引擎那几张图。
//
// 这一档钉的是「两端各算一遍」那一类：多出来的那几块由 `clip.extra_masks` 说一次，
// 导出把它乘进同一条 alpha，预览把引擎给的图一层层叠起来取交集。界面不许自己造图、
// 不许把两件事写成两次 `clip.mask`，也不许在浏览器里再乘一次 alpha。
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { boxKeyAt, boxKeyForPlayhead } from "../desktop/src/effects";
import type { ShapeMask } from "../desktop/src/engine";
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
assert.match(inspector, /MASK_ROWS\.map\(\(\[field, label, min, max\]\)/,
  "叠加那几块的中心/大小行不是从同一张 MASK_ROWS 折出来的（第二张标签表迟早对不上）");
assert.match(inspector, /id=\{`stack-\$\{index\}-\$\{field\}`\}/, "每一块的输入框没有按块编号");
assert.match(inspector, /id=\{`stack-\$\{index\}-rotation`\}/, "叠加的块改不了角度");
assert.match(inspector, /value=\{item\.feather \* 100\}/, "叠加的块改不了羽化");
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
// 1.239：每一枚框点在卡片里有名字——时刻可跳、插值可改（贝塞尔不在这一档）、删除只走那一处 patch。
assert.match(inspector, /className="mask-stack-keylist"/, "框点没有一张看得见的表");
assert.match(inspector, /timecode\(key\.at_ticks, rate\)/, "框点的时刻不是时间码");
assert.match(inspector, /playhead\.set\(clip\.position_ticks \+ key\.at_ticks\)/, "点时刻没有把播放头挪过去");
assert.match(inspector, /value !== "bezier"/, "框点里出现了这一档不支持的贝塞尔插值");
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
assert.match(inspector, /打了框点的块走自己的窗，勾这里不会删掉那些框点/, "悬停里没写清框点与跟随谁说了算");
assert.match(inspector, /className="mask-stack-state dim"/, "每一块没有写它此刻怎么动");
assert.match(inspector, /\? `自己走 · \$\{item\.keys\.length\} 枚框点`/, "带框点的那一块没有写明它自己走");
assert.match(inspector, /: clip\.extra_masks_follow \? "跟随主遮罩" : "静止"/, "没打框点的那一块没有写它跟不跟");
assert.match(timeline, /const boxKeyRows = \(clip\.extra_masks \?\? \[\]\)/, "条上没有从再叠的遮罩取框点");
assert.match(timeline, /className="clip-boxkeys" role="img"/, "条顶上那一排点没有画");
assert.match(timeline, /\(at \/ clip\.duration_ticks\) \* 100/, "点的位置不是按片段本地刻度折的");
assert.match(timeline, /再叠的遮罩框点：\$\{boxKeyWords\}/, "整段的悬停里没有列出框点的时间");
assert.match(timeline, /打点、改插值与删除在检查器「再叠的遮罩」那一格/, "悬停里没有指一条真走得通的编辑路");
assert.match(css, /\.clip-boxkeys\s*\{[^}]*pointer-events: none/, "那一排点接了指针——片段顶上会多出一块拖不动的死区");
assert.match(css, /\.clip-boxkey\s*\{[^}]*background: var\(--accent\)/, "点不用主题色");
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
assert.match(inspector, /上面五个数改的是这一枚/, "没有说清上面五个数此刻改的是哪一枚");
assert.match(inspector, /上面五个数是模板值/, "停在两枚之间时没有说清那五个数此刻只是模板");
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
assert.match(picture, /boxKeyForPlayhead\(selectedExtra, localAt, Math\.round\(localAt \/ frame\) \* frame\)/, "画面没有用那一处键的选择");
assert.match(picture, /const extraDrawable = Boolean\(visible && selectedExtra && extraBox && !follow && !disabled/, "可拖的条件不对");
assert.match(picture, /window\.addEventListener\("pointermove", move\);/, "拓取期间没有在 window 上听");
assert.match(picture, /const box = draft\?\.index === gesture\.index \? draft\.box : null;/, "松手没有读最后一次草稿");
assert.match(picture, /if \(gesture\.keyTick !== null\) return \{ \.\.\.row,/, "停在框点上时没有写回那一枚");
assert.match(picture, /setClipMaskStack\(clip\.id, masks, follow, gesture\.projectId, gesture\.revision\)/, "松手没有走那一条写入");
assert.match(picture, /y=\{cy - ry - hs\.y \/ 2\}/, "柄不在盒子的上边中点");
assert.match(css, /\.mask-extra-handle\s*\{[^}]*cursor: move/, "柄没有自己的命中与指针");
console.log("PASS: 叠加遮罩只有一处写入口、额度听引擎的、每一块的五个数与羽化/反转都在格子里改、每一块可以打自己的框点、跟随时大小按同一比例缩放、框点的时间在条顶上看得见且不接指针、每一块都写明自己怎么动、停在框点上时五个数改的就是那一枚、浏览器叠的是引擎那几张图并取交集、每一层各用各的 mask-size/position、样式仍走刻度");
