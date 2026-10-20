// 1.221：一条片段再叠几块遮罩——界面写的是整串，浏览器叠的是引擎那几张图。
//
// 这一档钉的是「两端各算一遍」那一类：多出来的那几块由 `clip.extra_masks` 说一次，
// 导出把它乘进同一条 alpha，预览把引擎给的图一层层叠起来取交集。界面不许自己造图、
// 不许把两件事写成两次 `clip.mask`，也不许在浏览器里再乘一次 alpha。
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

declare const REPO_ROOT: string;

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync) ?? resolve(REPO_ROOT, parts[0]);
  assert.ok(existsSync(found!), `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const store = read("desktop/src/store.ts", "../../desktop/src/store.ts");
const inspector = read("desktop/src/views/Inspector.tsx", "../../desktop/src/views/Inspector.tsx");
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
assert.match(inspector, /只切不动/, "关键帧只跟主遮罩走这件事必须写在格子里，不是藏在帮助里");
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
assert.match(inspector, /value=\{item\.rotation \?\? 0\}/, "叠加的块改不了角度");
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
  /maskSize: \[mainSize, \.\.\.extraPlates\.map\(\(\) => "100% 100%"\)\]\.join\(", "\)/,
  "再叠的层的尺寸不是各自的 100%×100%",
);
assert.match(picture, /const followPosition =/, "「跟着主遮罩平移」没有一条自己的落位算式");
assert.match(picture, /const extraPosition = follow \? followPosition : "0px 0px";/, "跟不跟这一格没有决定再叠层的落位");
assert.match(
  picture,
  /maskPosition: \[mainPosition, \.\.\.extraPlates\.map\(\(row\) => \(row\.own \? "0px 0px" : extraPosition\)\)\]\.join\(", "\)/,
  "再叠的层的落位不是各自的 0,0 / 跟随时的主遮罩平移",
);
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
assert.match(picture, /row\.own \? "0px 0px"/, "自己带框点的那一层没有按整画面图落位");
// 1.239：每一枚框点在卡片里有名字——时刻可跳、插值可改（贝塞尔不在这一档）、删除只走那一处 patch。
assert.match(inspector, /className="mask-stack-keylist"/, "框点没有一张看得见的表");
assert.match(inspector, /timecode\(key\.at_ticks, app\.project\?\.settings\.frame_rate/, "框点的时刻不是时间码");
assert.match(inspector, /playhead\.set\(clip\.position_ticks \+ key\.at_ticks\)/, "点时刻没有把播放头挪过去");
assert.match(inspector, /value !== "bezier"/, "框点里出现了这一档不支持的贝塞尔插值");
assert.match(inspector, /row\.at_ticks !== key\.at_ticks/, "删除一枚框点没有走同一处 patch");

console.log("PASS: 叠加遮罩只有一处写入口、额度听引擎的、每一块的五个数与羽化/反转都在格子里改、每一块可以打自己的框点、浏览器叠的是引擎那几张图并取交集、每一层各用各的 mask-size/position、样式仍走刻度");
