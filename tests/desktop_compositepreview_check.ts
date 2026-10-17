/**
 * 1.193 的壳层检查：「叠一层原图」这条边在界面这一头只有一个主人、一次判断。
 *
 * 为什么单独一档：`tests/composite_check.py` 量的是导出落到像素，`tests/compositepreview_check.py`
 * 量的是清单那一行；屏幕这一头的风险是三件事——
 * ① 视图自己再算一次相合（画面上是一回事、文件里是另一回事，就是 1.98 那一族的老账）；
 * ② 界面自己问「这段素材是什么」来决定画不画（引擎已经在清单里说了 `paintable`，问第二次
 *    迟早不一致，1.166 那次「函数对、门禁对、画面里没有那两行」就是这个形状）；
 * ③ 容器不隔离，`mix-blend-mode` 穿到别的轨道底下去（1.189 为图层量过同一条）。
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync);
  assert.ok(found, `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const preview = read("desktop/src/views/Preview.tsx", "../../desktop/src/views/Preview.tsx");
const effects = read("desktop/src/effects.ts", "../../desktop/src/effects.ts");
const engine = read("desktop/src/engine.ts", "../../desktop/src/engine.ts");
const css = read("desktop/src/styles.css", "../../desktop/src/styles.css");
const animation = read("src/agentcut/animation.py", "../../src/agentcut/animation.py");
const contracts = read("src/agentcut/contracts.py", "../../src/agentcut/contracts.py");
const fields = read("desktop/src/views/GradeFields.tsx", "../../desktop/src/views/GradeFields.tsx");

const count = (text: string, needle: string) => text.split(needle).length - 1;

// 1) 那一摞 DOM 只有一处构造：底层原图 + opacity=mix 的容器 + 容器里两层按引擎的方式相合。
const stack = preview.slice(preview.indexOf("const picture ="));
assert.ok(stack.length > 40, "找不到监视器那一路的构造（picture 那一段）");
assert.ok(preview.includes('className="composite-stack"'), "监视器没有那摞容器");
assert.ok(preview.includes('className="composite-top"'), "容器里没有那个 opacity=mix 的那一层");
assert.ok(preview.includes("style={{ opacity: edge.mix }}"), "权重不是照清单里那一个数");
assert.ok(preview.includes("{rawAt()}"), "底层少了那幅原图（相合就没有底）");
assert.equal(count(preview, "const rawAt ="), 1, "「原图那一份」被构造了两遍");
// 那幅「原图」只准用这一段自己已经在用的那个 URL。切片取 `rawAt` 那一句本身——
// 再宽就会把图层那几行的 `streams[...]` 也圈进来（那是另一件事，1.189 已经钉过）。
const rawAt = preview.indexOf("const rawAt =");
const rawLine = preview.slice(rawAt, preview.indexOf("const edge =", rawAt));
assert.ok(rawLine.length > 40 && rawLine.includes("src={url}"), "那幅原图不是这一段自己用的那一个 URL");
assert.ok(!/streams\[/.test(rawLine), "这一路自己拼了素材地址");

// 2) 「normal 要交换两层」这一条判断只在 effects.ts 一处，视图只问一次。
assert.match(effects, /export const compositeSwap = /, "那条交换的判断不在 effects.ts 一处");
assert.ok(effects.includes('mode === "normal"'), "判断本身被改写了（FFmpeg 的 normal 交回第一个输入）");
assert.ok(preview.includes("compositeSwap(edge.mode)"), "监视器没在问那唯一的判断");
assert.ok(!/mode === "normal"/.test(preview), "视图自己又问了一遍是哪一档方式（第二处判断）");

// 3) 画不画得了只听引擎：界面不许自己问素材是什么。
//    「不问第二遍」要说清到式子那一级：突变把条件改成 `edge?.paintable && isImage` 时，
//    源码里既没有 `kind === "image"` 也没有第二次 `asset` 查询，只有多出来的那一个 `&&`——
//    所以钉的是那一句三元只问一个字段，别的答案一概不许进条件。
const pictureLine = preview.match(/^ {2}const picture = .*$/m);
assert.ok(pictureLine, "找不到监视器那一路的判据（picture 那一句）");
// 条件里只许有两个问句：引擎那一行的 `paintable`，以及这一段有没有地址（引擎问不到文件
// 这一会儿在不在原地）。除此之外多问 anything——素材是什么、是不是图像——就是第二个判断。
assert.match(pictureLine[0], /^ {2}const picture = edge\?\.paintable && url && compositeLive\(edge\.motion, playing\) \? /, "画不画得了那一格不止问了引擎给的那三个答案");
// 「什么时候画得成」也只许有一个主人：视图问 `compositeLive`，不许自己比 `motion` 是哪一档。
assert.equal(count(effects, "export const compositeLive = "), 1, "「什么时候画得成」的判断不止一处");
assert.ok(!/motion === "paused"/.test(preview), "视图自己又问了一遍 motion 是哪一档（第二处判断）");
assert.ok(preview.includes("compositeLive(edge.motion, playing)"), "监视器没在问那唯一的时机判断");
assert.doesNotMatch(pictureLine[0], /\b(isImage|kind|asset)\b/, "条件里又问了这一段素材是什么");
assert.ok(!/kind === "image"/.test(stack), "视图自己问了一遍素材是什么（那是第二个判断）");
assert.match(engine, /composite\?: CompositeEdge \| null/, "清单那一行的类型里没有这条边");
assert.match(engine, /export type CompositeEdge = \{ mode: BlendMode; mix: number; paintable: boolean; motion\?: "always" \| "paused" \| null \}/, "那一行的形状被改了");

// 4) 容器必须隔离，否则 `mix-blend-mode` 会穿到别的轨道底下去（1.189 那一课）。
assert.match(css, /\.composite-top \{[^}]*isolation: isolate/, "容器没隔离：这一级会与别的轨道相合");
assert.match(css, /\.composite-stack, \.composite-top \{ position: absolute; inset: 0/, "那一摞没按画面框铺满");

// 5) 引擎这一头：这一行只在 `composite_row` 一处算，判断是「素材是图像」，开关随 capabilities 下发。
assert.equal(count(animation, "def composite_row("), 1, "这一行的算法出现了两遍");
assert.ok(animation.includes('asset is not None and asset.kind == "image"'), "画不画得了的判断被改写了");
assert.ok(animation.includes("and asset.verified is not None"), "没有那次探测也当真——界面拿到的是空地址");
assert.ok(animation.includes('"composite": composite_row(clip, project)'), "清单没在交这一行（调用点）");
assert.ok(contracts.includes('"composite_preview": True'), "capabilities 里少了这一档的开关");

// 6) 卡片那一段必须说清两件具体的事（图像这一段会画、视频那一段还不画），不许留一刀切。
const card = fields.slice(fields.indexOf('if (node.kind === "composite")'));
assert.match(card, /监视器现在会画/, "卡片没说这一级现在会画");
assert.match(card, /视频素材那一段暂停与逐帧时会画/, "卡片没说视频那一档什么时候画得成");
assert.match(card, /播放中这一级不画/, "卡片没说播放中不画这一档（那是量出来的代价）");
assert.match(card, /paintable/, "卡片没说这一格由引擎逐段决定");
assert.doesNotMatch(card, /预览不生效、导出生效/, "卡片还留着那条一刀切的旧说法");

console.log(
  "desktop_compositepreview_check: 这条边在界面只有一个主人、一次判断——那一摞只构造一处、" +
  "normal 的交换只在 effects.ts、画不画只听清单里的 paintable、容器隔离，卡片把两段实话都说清"
);
