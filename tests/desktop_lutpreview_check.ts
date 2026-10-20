// 1.234：立方表在浏览器里由一块 WebGL2 画布画——判据、解码与插值各只有一处。
//
// 这一档跑的是那条判据（`gradeNeedsCanvas`），再把画布那一支钉成源码形状：
// 四面体六支写全、行主序转列主序、格点直接进 3D 纹理（不重排、不翻 Y）、
// 解码只在 `gradeCanvas.ts` 一处；视图只做一次判断，画布与「藏起源」都由同一个数决定。
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { gradeNeedsCanvas } from "../desktop/src/gradeCanvas";

declare const REPO_ROOT: string;

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync) ?? resolve(REPO_ROOT, parts[0]);
  assert.ok(existsSync(found!), `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};
const count = (text: string, needle: RegExp) => (text.match(needle) ?? []).length;

const grade = (stages: unknown[]) => ({ id: "g1", stages }) as never;
const lut = { type: "lut", id: "l1", r: [], g: [], b: [] };
const cube = (cells?: string) => ({
  type: "lut3d", id: "d1", title: "LUT", size: 2, preview: cells !== undefined, ...(cells ? { cells_u8: cells } : {}),
});

// ① 判据：只有真带着格点的那一段才需要画布
assert.equal(gradeNeedsCanvas(null), false, "没有链子也要画布");
assert.equal(gradeNeedsCanvas(undefined), false);
assert.equal(gradeNeedsCanvas(grade([lut])), false, "每通道表本来就用 CSS 滤镜画，不该开画布");
assert.equal(gradeNeedsCanvas(grade([cube()])), false, "格点不在表里（交不出去）也开画布——画出来会是一块空的");
assert.equal(gradeNeedsCanvas(grade([cube("AAAAAA==")])), true, "有格点的立方没开画布");
assert.equal(gradeNeedsCanvas(grade([lut, cube("AAAAAA==")])), true);

// ② 画布那一支：四面体六支写全、矩阵按列主序、格点按红最快直接上传
const source = read("desktop/src/gradeCanvas.ts");
const samples = count(source, /vec3 tetra\(/g);
assert.equal(samples, 1, `四面体插值有 ${samples} 处实现`);
const start = source.indexOf("vec3 tetra(");
const tetra = source.slice(start, source.indexOf("`;", start));
assert.equal(count(tetra, /return c000/g), 6, "四面体的六支没写全（少一支就有一种次序落回最近格点）");
assert.match(source, /const column = \[stage\.m\[0\], stage\.m\[3\], stage\.m\[6\]/, "矩阵没有按列主序摆");
assert.match(
  source,
  /texImage3D\(gl\.TEXTURE_3D, 0, gl\.RGBA8, stage\.size, stage\.size, stage\.size, 0, gl\.RGBA, gl\.UNSIGNED_BYTE, rgba\)/,
  "3D 纹理没有吃引擎那串格点（RGBA8 是 3D 纹理上最保守的一档）",
);
assert.match(source, /rgba\[texel \* 4\] = cells\[texel \* 3\];/, "格点重排了——红最快必须是 x 轴最快");
assert.doesNotMatch(source, /UNPACK_FLIP_Y_WEBGL/, "翻了 Y 就不是同一张表");
assert.equal(count(source, /atob\(/g), 1, "格点解码不止一处");
// 2026-10-20 量到的真缺陷：GLSL ES 3.00 不给 sampler3D 默认精度，漏写这一行整块画布就是黑的。
assert.match(source, /precision highp sampler3D;/, "sampler3D 没写精度——着色器会编译失败");
assert.match(source, /precision highp sampler2D;/, "sampler2D 没写精度");
assert.match(source, /preserveDrawingBuffer: true/, "画布不保留这一帧——截图与读回只能读到黑");

// ③ 视图：一个判断，画布与「藏起源」共用它
const editor = read("desktop/src/views/Preview.tsx");
assert.equal(count(editor, /gradeNeedsCanvas\(/g), 1, "判据在视图里不止一处");
assert.match(editor, /const canvasGrade = plan && gradeNeedsCanvas\(plan\.grade\) \? plan\.grade : null;/, "判据的形状变了");
assert.match(editor, /const canvasLive = canvasGrade !== null && !canvasFailed;/, "「画布活着」没有和失败那条腿分开");
assert.equal(count(editor, /canvasLive \? "grade-source-hidden" : undefined/g), 2, "图片与视频两条腿没有都藏起来");
assert.match(
  editor,
  /\{canvasLive \? <canvas ref=\{gradeCanvas\} className="grade-canvas" aria-hidden="true" \/> : null\}/,
  "画布不是由同一个数决定画不画",
);
assert.match(editor, /painted = paintGrade\(canvas, source, canvasGrade, plan\?\.color_basics \?\? \[1, 1, 1\]\)/, "画布没拿到引擎那三个基础调色数");
assert.match(editor, /try \{[\s\S]{0,140}painted = paintGrade\([\s\S]{0,140}catch \{[\s\S]{0,60}painted = false;/, "抛出来的上传失败没接住");
assert.match(editor, /if \(!painted\) setCanvasFailed\(true\);/, "画布画不出来时没人接着说");
// 2026-10-20 量到的真缺陷：图片少了 crossOrigin，texImage2D 抛 SecurityError，整块画布是黑的。
assert.match(editor, /crossOrigin="anonymous" src=\{url\} alt=\{asset\?\.label\}/, "图片没有按 CORS 取——上传到画布会被判成跨源");
assert.match(editor, /className="layer-error grade-fallback"/, "失败那一句不在屏幕上");
assert.match(editor, /useEffect\(\(\) => \{ setCanvasFailed\(false\); \}, \[canvasGrade\?\.id\]\);/, "换了链子仍记着上一次的失败");
assert.doesNotMatch(editor, /atob\(/, "视图自己解码了格点——解码只许一处");

// ④ 样式：画布与源占同一格；源用 visibility 藏（布局不变，遮罩坐标不随之改）
const css = read("desktop/src/styles.css");
assert.match(css, /\.grade-canvas \{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; display: block; \}/, "画布不在源那一格上");
assert.match(css, /\.grade-source-hidden \{ visibility: hidden; \}/, "源不是藏起来而是移走了");
assert.match(css, /\.grade-fallback \{[^}]*inset: auto 0 0 0/, "失败那一句盖住了整幅画面（画面应当还在，只是没套 LUT）");

console.log("PASS: 立方表只由带格点的那一段决定开画布，四面体六支、红最快、列主序都在，视图只判一次且不解码");
