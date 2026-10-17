/**
 * 1.194 的壳层检查：窗口矮到时间线让不动了，界面必须说出来，而且不许抄第二条公式。
 *
 * 1.191 交出那条 clamp 时在 README 里明留了一句没做：「时间线被夹到 180 下限以后，拖拽条在那个
 * 方向上就不再起作用（诚实的做法是把『已被窗口挤到下限』告诉用户，这句还没做）」。这一轮补的就是
 * 那一句。这里钉的是三件事——
 * ① 那两个数必须是**量**出来的：要的那一个读同一个 CSS 变量（`--timeline-height`，自定义属性会
 *    继承），得到的是这个盒子的真实高度；TS 里再写一遍 180/300 或第二条 `calc(100dvh …)`，
 *    就成了「一条公式两个主人」，改 CSS 那一处不会有人来提醒改这里（1.191 那一档壳检钉的就是
 *    公式只有一处，这一档钉的是消费者也只能有一处读数）；
 * ② 这一行只在**真的夹住了**时出现（`wanted - got > 1` 那一个判断），大窗口里一个字都不许多；
 * ③ 句子里那两条出路必须真走得通：把窗口拉高、退出「素材预览」那一屏（`.editor.source-open`
 *    那条规则把保留数从 430 抬到 510，退出就是还给时间线 80 px）——指一条走不通的路等于没说。
 */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync);
  assert.ok(found, `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};

const timeline = read("desktop/src/views/Timeline.tsx", "../../desktop/src/views/Timeline.tsx");
const css = read("desktop/src/styles.css", "../../desktop/src/styles.css");
const editor = read("desktop/src/views/Editor.tsx", "../../desktop/src/views/Editor.tsx");

const count = (text: string, needle: string) => text.split(needle).length - 1;

// ① 读数：那一个「要的数」只能来自同一个 CSS 变量，那一个「得到的数」只能来自真的盒子。
assert.equal(count(timeline, 'getPropertyValue("--timeline-height")'), 1, "读 `--timeline-height` 的地方不是恰好一处");
assert.match(timeline, /const measure = \(\) => \{[\s\S]{0,240}getBoundingClientRect\(\)\.height/, "量到的不是这一屏真实的那一段高");
const block = timeline.slice(timeline.indexOf("const rootRef"), timeline.indexOf("const clamped"));
assert.ok(block.length > 200, "找不到那一段测量（rootRef 到 clamped）");
for (const forbidden of ["180", "300", "calc(", "100dvh", "--preview-reserve"]) {
  assert.ok(!block.includes(forbidden), `那段测量里出现了「${forbidden}」——公式的第二份常数或第二条公式`);
}

// ② 只在夹住时出现，且判据是「要的」减「得到的」。
assert.match(timeline, /const clamped = room && room\.wanted - room\.got > 1 \? room : null;/, "夹住的那一个判断被改写了");
assert.equal(count(timeline, 'className="timeline-clamped"'), 1, "那一行出现了两遍");
assert.match(timeline, /\{clamped \? <p className="timeline-clamped" role="status">/, "那一行没有条件、或不是一条 status");

// ③ 句子里两条出路都得在，且说的都是这一屏真做得动的事。
const line = timeline.slice(timeline.indexOf('className="timeline-clamped"'), timeline.indexOf("</p>"));
assert.ok(line.includes("把窗口拉高"), "没给出路①：把窗口拉高");
assert.ok(line.includes("素材预览"), "没给出路②：退出「素材预览」那一屏");
assert.match(line, /Math\.round\(clamped\.wanted\)[^]*?Math\.round\(clamped\.got\)/, "那两个数没照量到的写");

// ④ 样式与公式：那一行有自己的规则，而那条 clamp 仍只有一处。
assert.match(css, /\.editor \.timeline \.timeline-clamped \{/, "样式里没有这一行");
assert.equal(
  count(css, ".editor .timeline { height: clamp(180px, var(--timeline-height, 300px), calc(100dvh - var(--preview-reserve))); }"),
  1,
  "让步那条公式不再恰好一处"
);
assert.ok(count(editor, '"--timeline-height"') === 1, "写 `--timeline-height` 的地方不是恰好一处");

console.log(
  "desktop_clamphint_check: 夹住了就说——两个数都来自量（同一个 CSS 变量 + 真的盒子），" +
  "TS 里没有 180/300/第二条 calc，那一行只在 wanted-got>1 时出现，两条出路都点名真走得通的"
);
