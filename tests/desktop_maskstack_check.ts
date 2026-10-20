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
assert.match(inspector, /再叠的这几块只切不动/, "关键帧只跟主遮罩走这件事必须写在格子里，不是藏在帮助里");
assert.match(inspector, /与主遮罩取交集/, "那一格没说清叠出来的是什么关系");
assert.equal((inspector.match(/setClipMaskStack\(clip\.id/g) ?? []).length, 1, "叠加那一串有两个写入口，早晚一份对不上");

// ③ 浏览器：叠的是引擎给的图，取交集用标准那一格，不自己再算 alpha
assert.match(picture, /const layers = \[primaryImage, \.\.\.\(extra \?\? \[\]\)\]\.filter\(Boolean\)/,
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

console.log("PASS: 叠加遮罩只有一处写入口、额度听引擎的、做不到的那件事写在格子里、浏览器叠的是引擎那几张图并取交集、样式仍走刻度");
