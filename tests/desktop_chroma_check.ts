// 1.276：色度键在浏览器里的那一路——一份数、一处判断、一条顺序。
//
// 判据只有一处（`chromaNeedsCanvas`）；那两个数（`low`/`width`）只由引擎折一次，
// 画布不许自己减；键判的是**调色前**的那一帧，与导出那趟 `geq` 挂在 `color_filter`
// 之前同一条顺序——这一条顺序是这一档唯一能让「预览所见」与「成片所得」相等的写法，
// 所以它钉在源码形状上，而不是钉在一次目测上。
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { chromaNeedsCanvas } from "../desktop/src/gradeCanvas";

declare const REPO_ROOT: string;

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync) ?? resolve(REPO_ROOT, parts[0]);
  assert.ok(existsSync(found!), `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};
const count = (text: string, needle: RegExp) => (text.match(needle) ?? []).length;

const row = { color: [0, 255, 0], low: 17.85, high: 30.6, width: 12.75, soft: true, inverted: false };

// ① 判据：挂了键才开画布，没挂就不许多一块画布
assert.equal(chromaNeedsCanvas(null), false, "没挂键也开画布");
assert.equal(chromaNeedsCanvas(undefined), false, "清单里没有这一格也开画布");
assert.equal(chromaNeedsCanvas(row), true, "挂了键却没开画布——预览会演一个成片里没有的效果");

// ② 画布：键判调色前那一帧、预乘交出去、失败与缓存各只有一处
const canvas = read("desktop/src/gradeCanvas.ts");
assert.equal(count(canvas, /distance\(/g), 1, `距离算了 ${count(canvas, /distance\(/g)} 处，只要一处`);
const keyAt = canvas.indexOf("distance(src.rgb * 255.0, uKey)");
const gradeAt = canvas.indexOf("vec3 c = basics(src.rgb, uBasics)");
assert.ok(keyAt > 0 && gradeAt > keyAt, "键没有走在调色之前——导出那趟 geq 挂在 color_filter 之前，两端就不是同一幅画");
assert.match(canvas, /fragColor = vec4\(c \* a, a\);/, "画布没有预乘交出去：那一块洞不会让下面那一层露出来");
assert.match(canvas, /if \(uMatte > 0\.5\) \{ fragColor = vec4\(a, a, a, 1\.0\); return; \}/, "「看遮罩」没有画那一张黑白 matte");
assert.match(canvas, /alpha: true, premultipliedAlpha: true/, "画布缓冲不带 alpha——洞永远是一块不透明的矩形");
assert.doesNotMatch(canvas, /alpha: false/, "还留着那条不带 alpha 的旧腿（两条腿只会有一块画布画得对）");
assert.equal(count(canvas, /canvasKey\(/g), 3, `程序缓存的钥匙不在一处（定义 + 两处使用），数到 ${count(canvas, /canvasKey\(/g)}`);
assert.match(canvas, /id: canvasKey\(grade, chroma\)/, "编译出来的程序没把「有没有键」记进身份——换了键还在用旧着色器");
assert.match(canvas, /state\.built\.id !== wanted/, "画布局部没按那份身份决定重编");
// 界面不许自带那一段距离的任何一个数：那些数只活在 `compositing.chroma_row` 里。
assert.doesNotMatch(canvas, /17\.85|30\.6|12\.75|0\.12|0\.05/, "画布里长出了引擎的那几个数");
assert.match(canvas, /for \(const name of \["uKey", "uLow", "uHigh", "uWidth", "uSoft", "uInvert", "uMatte"\]\)/, "键的 uniform 不是一处取的");
assert.match(canvas, /chroma: ChromaRow \| null = null,\n  matte = false,/, "画布那两个入参的形状变了");

// ③ 视图：一次判断、一次交数、失败那一句说得出是谁画不出来
const editor = read("desktop/src/views/Preview.tsx");
assert.equal(count(editor, /chromaNeedsCanvas\(/g), 1, "「这一段要不要画布」在视图里不止一处");
assert.match(editor, /const canvasChroma = plan && chromaNeedsCanvas\(plan\.chroma\) \? plan\.chroma : null;/, "键没走那唯一一处判断");
assert.match(editor, /const chromaMatte = useApp\(\)\.chromaMatte;/, "「看遮罩」不是由那一处应用状态说的");
assert.match(editor, /painted = paintGrade\(canvas, source, canvasGrade, plan\?\.color_basics \?\? \[1, 1, 1\], canvasChroma, chromaMatte\);/, "画布没拿到引擎那份数");
assert.match(editor, /\}, \[canvasGrade\?\.id, plan\?\.color_basics, canvasChroma, chromaMatte, playing, url\]\);/, "换了键或换了那一档，画布不重画");
assert.match(editor, /预览画不出这个色度键（这台浏览器没有可用的 WebGL2），画面按未抠显示；导出不受影响/, "画不出来时屏幕上没有那句话");
assert.match(editor, /canvasChroma && !canvasGrade && canvasFailed/, "两句话会同时说（立方表与色度键各报各的，但只能报一条）");
assert.doesNotMatch(editor, /setClipChroma\(/, "视图自己写键——写键的那一只手在检查器与 store 里");

// ④ 检查器：三个默认值都从能力表来，一颗勾不改工程
const inspector = read("desktop/src/views/Inspector.tsx");
assert.match(inspector, /const defaults: ChromaKey = \{/, "挂上抠像写的那一份不是「由那三个数拼出来的键」");
for (const knob of ["chroma_color_default", "chroma_similarity_default", "chroma_blend_default"]) {
  assert.ok(inspector.includes(`limits?.${knob}`), `界面没读引擎下发的 ${knob}`);
}
assert.doesNotMatch(inspector, /"#00[fF]00[fF]"/, "界面自带了一个绿——键色的默认值归引擎");
assert.doesNotMatch(inspector, /similarity\s*-\s*blend/, "界面自己算了那一段软边（那份换算只许在引擎里）");
assert.match(inspector, /<ChromaFields key=\{`chroma-\$\{clip\.id\}`\} clip=\{clip\}/, "那一组没有按片段重建（两条片段的键会串在一起）");
assert.match(inspector, /clip && !clip\.text && project\?\.tracks\.find\(\(t\) => t\.id === clip\.track_id\)\?\.kind === "video"/, "文字层或声音轨上也长出了这一组");
assert.match(inspector, /onClick=\{\(\) => setClipChroma\(clip\.id, null\)\}>摘掉键</, "摘掉键走的不是那一条普通命令");
assert.match(inspector, /aria-pressed=\{app\.chromaMatte\}[^>]*onClick=\{\(\) => setChromaMatte\(!app\.chromaMatte\)\}>看遮罩</, "「看遮罩」那颗按钮没有把状态说给读屏");
assert.match(inspector, /className="insp-section chroma-section"/, "这一组不吃检查器那一档间距（自己长一套就是第二份刻度）");
assert.equal(count(inspector, /"clip\.chroma"/g), 1, "这一串名目在检查器里出现不止一次（命令只在 store 那一处交，这里只该剩历史表那一个标签）");
assert.match(inspector, /"clip\.chroma": "调整色度键"/, "历史里念不出这一手是什么");

// ⑤ store：一次交一份整键，一处说「看遮罩」
const store = read("desktop/src/store.ts");
assert.equal(count(store, /op: "clip\.chroma"/g), 1, "写键的命令在 store 里不止一处");
assert.match(store, /editAtRevision\(\[\{ op: "clip\.chroma", clip_id: clipId, chroma \}\], projectId, revision, "调整色度键"\)/, "写键没走那条带版本检查的普通链");
assert.match(store, /export function setChromaMatte\(chromaMatte: boolean\) \{ set\(\{ chromaMatte \}\); \}/, "「看遮罩」那一档还留着一个 mutation？");
assert.equal(count(store, /chromaMatte: boolean;/g), 1);
assert.equal(count(store, /chromaMatte: false,/g), 1, "初始状态里那一档写了两遍（换一个工程就不止是重置预览）");

// ⑥ 契约与提示：那份数的六个格、那一句中文
const engine = read("desktop/src/engine.ts");
assert.match(engine, /export type ChromaRow = \{ color: number\[\]; low: number; high: number; width: number; soft: boolean; inverted: boolean \};/, "清单里那份键的数换了形状");
assert.match(engine, /export type ChromaKey = \{ color: string; similarity: number; blend: number; inverted: boolean \};/, "写进去的那一份键换了形状");
assert.match(engine, /chroma\?: ChromaRow \| null;/, "预览清单的类型里没有被抠走的那一行");
assert.match(engine, /INVALID_CHROMA: "[^"]*色度键[^"]*"/, "引擎那句拒法在界面上念不出中文");
assert.doesNotMatch(engine, /INVALID_CHROMA: "[^"]{0,11}"/, "中文提示短得过不了词表那一道");

// ⑦ 样式：这一组只吃刻度，不长第二套字号与圆角
const css = read("desktop/src/styles.css");
assert.doesNotMatch(css, /chroma/, "样式里为色度键写了单独一档字号或圆角（刻度之外不该有第二套）");

console.log("PASS: 色度键只由引擎那一份数决定，画布判一次、走在调色之前、预乘交出洞，界面三个默认值都来自能力表");
