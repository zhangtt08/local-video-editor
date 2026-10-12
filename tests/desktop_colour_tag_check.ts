/** 1.151：母版可以在容器上声明自己是什么颜色——界面只念引擎那张表，一处都不判颜色。
 *
 * 引擎那边把 `-color_primaries/-color_trc/-colorspace` 写进容器，并把画面按同一档矩阵折过，
 * 所以这一版界面缺的还是克制：① 哪几档能用是 `capabilities.output_colour_tags` 那一张表，
 * 界面连 `primaries`／`transfer`／`matrix` 都不读（读了就是界面在算色彩数学）；
 * ② 带不带得出去只有一处判（`colourTagAllowed`），界面念的、发出去的、存进方案的是同一个值——
 *   1.136 那次两处各算一份的 bug 就是从这个字段上爆的，正反两个方向都要测得到，反向漏了
 *   就等于门禁整个失效；
 * ③ 没挑标记就一个字节都不写（引擎契约是 `extra="forbid"`，多一个不认的键老引擎整条拒收）；
 * ④ 引擎没下发这一档时（老引擎）要说清「没有这一档」，但导出照常出货——把人关在没有路上，
 *   本项目交付过一次，两个方向都得判得住。
 */

import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { resolve } from "node:path";

import { Engine, colourTagAllowed } from "../desktop/src/engine";

/** 界面挑不到的那一档在这里只是「引擎下发的那一行的 id」的替身：渲染层一个字都不许有它。 */
const TAG = "bt709";

type Sent = { url: string; method: string; body: string | undefined };
const sent: Sent[] = [];
Object.assign(globalThis, {
  fetch: async (url: string, init: { method?: string; body?: string }) => {
    sent.push({ url: String(url), method: init.method ?? "GET", body: init.body });
    return {
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ job: { id: "j1" }, jobs: [], plan: {} }),
    };
  },
});

const engine = new Engine("http://127.0.0.1:1", "t".repeat(64));

// —— ② 那一道门禁：四个场合各自单独判，正向也必须真给得出 ——————————————————
const PICTURE = { id: "h264-1080p", container: "mp4", codec: "libx264", alpha: false, sequence: false };
const AUDIO = { id: "mp3-192k", container: "mp3", codec: null, alpha: false, sequence: false };
const SEQUENCE = { id: "exr-sequence", container: "exr", codec: "exr", alpha: false, sequence: true };
const ALPHA = { id: "prores-4444-alpha", container: "mov", codec: "prores_ks", alpha: true, sequence: false };

assert.equal(
  colourTagAllowed(PICTURE as never, false, false, false, TAG),
  TAG,
  "带画面、有容器、不透明：这个标记就该照原样带出去（正向给不出来的门禁，反向也拦不住东西）"
);
assert.equal(colourTagAllowed(AUDIO as never, true, false, false, TAG), null, "音频交付根本没有画面，标记没地方落");
assert.equal(colourTagAllowed(SEQUENCE as never, false, true, false, TAG), null, "一串图像文件没有容器 VUI 可写");
assert.equal(colourTagAllowed(ALPHA as never, false, false, true, TAG), null, "透明母版那一折不由这条滤镜图决定，写上去就是谎话");
assert.equal(colourTagAllowed(PICTURE as never, false, false, false, null), null, "没挑就是 null：连这个键都不该发出去");
assert.equal(colourTagAllowed(null, false, false, false, TAG), null, "还没选到预设就不发标记");
// 反方向：同一份预设只要那三个布尔翻回来，标记就得重新带得出去——判的是调用方算好的那三个条件，
// 而不是界面再按预设长相猜第四套。
assert.equal(colourTagAllowed(ALPHA as never, false, false, false, TAG), TAG, "能装 alpha 的预设在不透明那一次照样能带标记");
assert.equal(colourTagAllowed(SEQUENCE as never, false, false, false, TAG), TAG, "序列那一条是靠 isSequence 拦的，不是靠预设名");
assert.equal(colourTagAllowed(AUDIO as never, false, false, false, TAG), TAG, "音频那一条是靠 audioOnly 拦的，不是另判一遍 codec");

// —— ③ 发出去的形状：挑了才写，没挑一个字都不多 ——————————————————————
await engine.render("p1", 7, "h264-1080p", "母版.mp4", undefined, null, "contain", "full", false, null, null, TAG);
let body = JSON.parse(sent.at(-1)!.body ?? "{}") as Record<string, unknown>;
assert.equal(body.colour_tag, TAG, "请求体里就是面板算出的那一个值");
await engine.render("p1", 7, "h264-1080p", "母版.mp4", undefined, null, "contain", "full", false, null, null, null);
body = JSON.parse(sent.at(-1)!.body ?? "{}");
assert.ok(!("colour_tag" in body), "留空就连这个键都不出现，老引擎的 extra=forbid 才不会整条拒收");
await engine.render("p1", 7, "h264-1080p", "母版.mp4");
body = JSON.parse(sent.at(-1)!.body ?? "{}");
assert.ok(!("colour_tag" in body), "不传这个参数也照样是 1.151 之前的那份请求体");

await engine.renderPlan("p1", "h264-1080p", 7, null, "contain", "full", false, null, null, TAG);
assert.ok(sent.at(-1)!.url.includes(`colour_tag=${encodeURIComponent(TAG)}`), sent.at(-1)!.url);
await engine.renderPlan("p1", "h264-1080p", 7, null, "contain", "full", false, null, null, null);
assert.ok(!sent.at(-1)!.url.includes("colour_tag"), "干跑的 query 也没挑就不写");
await engine.renderPlan("p1", "h264-1080p", 7);
assert.ok(!sent.at(-1)!.url.includes("colour_tag"), "默认值也不多发一个键");

await engine.renderBatch("p1", 7, [
  { preset_id: "h264-1080p", filename: "a.mp4", fit: "contain", colour_tag: TAG },
  { preset_id: "h264-1080p", filename: "b.mp4", fit: "contain" },
]);
const batch = JSON.parse(sent.at(-1)!.body ?? "{}") as { items: Record<string, unknown>[] };
assert.equal(batch.items[0].colour_tag, TAG, "批量里每一条带自己那一个答案");
assert.ok(!("colour_tag" in batch.items[1]), "没挑的那一条不被隔壁顶着写上一个标记");

// —— 接线：三处源码读的都是同一个算出来的值 ——————————————————————————
const sources = ["desktop/src", "src"].map((part) => resolve(process.cwd(), part)).find(existsSync);
assert.ok(sources, "渲染层源码必须能从检查工作目录读到");
const files = readdirSync(sources!, { recursive: true })
  .map((entry) => String(entry).replace(/\\/g, "/"))
  .filter((entry) => /\.(ts|tsx)$/.test(entry) && statSync(resolve(sources!, entry)).isFile());
const read = (entry: string) => readFileSync(resolve(sources!, entry), "utf8");
const engineTs = read("engine.ts");
const store = read("store.ts");
const panel = read("views/ExportPanel.tsx");

// ① 那张表只声明一次、只被读一次；色彩数学那几样在界面里连读都不许读。
// （engine.ts 里 `output_colour_tags` 还出现在引擎那四句中文提示之一，那是念给人才有的话，不是第二份表。）
assert.equal(engineTs.split("output_colour_tags?:").length - 1, 1, "capabilities 里那个字段在渲染层只声明一处");
assert.equal(store.split("output_colour_tags").length - 1, 0, "store 不认这张表，只往下传那个值");
assert.equal(panel.split("caps?.output_colour_tags").length - 1, 1, "面板只在一处读这张表（另一处是中文 fallback，念的是字段名不是值）");
assert.match(
  engineTs,
  /export type OutputColourTag = \{[\s\S]*?primaries\?: unknown;[\s\S]*?transfer\?: unknown;[\s\S]*?matrix\?: unknown;[\s\S]*?\};/,
  "表里那几样 FFmpeg 的话要收成 unknown：界面一旦想拿它算点什么，编译期就该拦住"
);
const maths: string[] = [];
for (const entry of files) {
  read(entry)
    .split(/\r?\n/)
    .forEach((line, index) => {
      if (/\.(primaries|transfer|zscale_matrix|zscale_range|matrix)\b/.test(line)) maths.push(`${entry}:${index + 1}`);
    });
}
assert.deepEqual(maths, [], "渲染层不读那几样颜色参数，更不拼 FFmpeg 参数：${maths.join('、')}");

// ② 一处判、四处念。
assert.equal(engineTs.split("colourTagAllowed(").length - 1, 1, "门禁本体在渲染层只有一处定义");
assert.equal(panel.split("colourTagAllowed(").length - 1, 1, "面板只问那一处，不在别处再判一遍");
const extraCallers = files
  .filter((entry) => entry !== "engine.ts" && entry !== "views/ExportPanel.tsx")
  .filter((entry) => read(entry).includes("colourTagAllowed("))
  .map((entry) => entry);
assert.deepEqual(extraCallers, [], `第二个算值的地方长出来了：${extraCallers.join("、")}`);
assert.match(panel, /const sendColourTag = colourTagAllowed\(preset, audioOnly, isSequence, matte, pickedTag\?\.id \?\? null\);/, "算值那一处的形状与 matteAllowed 同源：三个布尔是调用方算好交进来的");
assert.match(panel, /value=\{sendColourTag \?\? ""\}/, "那个下拉念的就是真发出去的值，不是人手里那个原始选择");
assert.match(panel, /\{sendColourTag \?\? "不写"\}/, "mono 尾巴念的还是同一个值");
assert.equal((panel.match(/colour_tag: sendColourTag/g) ?? []).length, 2, "待发清单里主版本与竖屏副本存的就是发出去的那一个值，正好两条");
assert.match(panel, /renderPlanPreview\(preset\.id, fit, range, matte, sendTimecode, sendFps, sendColourTag\)/, "干跑带的是同一个值");
assert.match(panel, /startRender\(preset\.id, finalName, folder \|\| undefined, fit, range, matte, sendTimecode, sendFps, sendColourTag\)/, "点开始导出带的是同一个值");
assert.match(store, /engine\.render\(project\.id, project\.revision, presetId, filename, folder, state\.sequenceId, fit, range, transparent, timecode, outputFps, colourTag\)/, "store 只往下传，不再判一次");
assert.match(store, /\.renderPlan\(state\.project\.id, presetId, state\.project\.revision, state\.sequenceId, fit, range, transparent, timecode, outputFps, colourTag\)/, "干跑也一样只往下传");
assert.equal(store.split("colourTagAllowed(").length - 1, 0, "store 不自己算值");
assert.match(panel, /tagRows\.map\(\(item\) => \(\s*<option key=\{item\.id\} value=\{item\.id\}>\s*\{item\.label\}/, "下拉里每一档都是照引擎下发的那一行排的");
assert.ok(panel.includes("不带标记（照旧：容器上一个色彩标记都不写）"), "第一条选项要说清留空是什么，别让人以为留空会写个默认值");

// ④ 两个方向都判得住：带不出去要说得出是哪一个原因，引擎没这一档也不能把人关在门外。
assert.equal((panel.match(/disabled=\{[^}]*tag(?:Rows|Blocker)[^}]*\}/g) ?? []).length, 1, "这一个控件之外不许再有第二处按标记拦人");
assert.ok(
  /disabled=\{Boolean\(blocked\) \|\| Boolean\(app\.busy\)\}/.test(panel),
  "「开始导出」那颗按钮的禁用条件里不许出现色彩标记：没标记也要照常出货"
);
for (const phrase of ["这一条交付照旧不带标记", "capabilities 里没有 output_colour_tags 这一档"]) {
  assert.ok(panel.includes(phrase), `引擎没下发这张表时要念得出「没有这一档」：缺 ${phrase}`);
}
for (const phrase of ["只有声音", "一串图像文件", "背景透明"]) {
  assert.ok(panel.includes(phrase), `带不出去的时候要点名叫得出是哪一条：缺 ${phrase}`);
}
for (const phrase of ["mov／mp4／mxf／webm", "把「背景透明」去掉"]) {
  assert.ok(panel.includes(phrase), `那句拒绝要配一条真走得通的出路：缺 ${phrase}`);
}
assert.ok(panel.includes("容器上写任何矩阵都成了与画面无关的话"), "透明那一句要说清为什么写上是谎话");
assert.ok(panel.includes("DaVinci") && panel.includes("它是什么"), "那句提示要说清带标记的母版是给下游读的");
for (const code of ["UNKNOWN_COLOUR_TAG", "COLOUR_TAG_NEEDS_CONTAINER", "COLOUR_TAG_NEEDS_PICTURE", "COLOUR_TAG_NOT_WITH_ALPHA"]) {
  assert.equal(
    (engineTs.match(new RegExp(`^ {6}${code}: "`, "gm")) ?? []).length,
    1,
    `${code} 那句中文提示在渲染层只有一份（提示表里那一个键）`
  );
  assert.equal(store.split(code).length - 1, 0, `store 不抄 ${code} 那份理由表`);
}
assert.ok(!/COLOUR_TAG_|UNKNOWN_COLOUR_TAG/.test(panel), "界面不抄引擎那张拒绝表：码名只有一处认识它");

// —— ①′ 标记值一个字都不许抄进界面 ————————————————————————————
const TAG_VALUES = ["iec61966-2-1", "bt470m", "bt709", "smpte2084"];
// `rec709` 在界面里另有合法身份：它是 1.150 那张「来源／输出色彩空间」表的 id，不是交付标记表的行。
// 所以它只在一处算违规——同一行既提到交付标记又写着它，就是把标记抄成了界面的一句答案。
const SHARED = "rec709";
const TAG_MENTION = /colour[_-]?tag|color[_-]?tag|output_colour|ColourTag|tagRows|pickedTag|tagBlocker|交付色彩/i;
const copied: string[] = [];
const compared: string[] = [];
for (const entry of files) {
  read(entry)
    .split(/\r?\n/)
    .forEach((line, index) => {
      const where = `${entry}:${index + 1}`;
      if (TAG_VALUES.some((value) => line.includes(value))) copied.push(where);
      else if (line.includes(SHARED) && TAG_MENTION.test(line)) copied.push(where);
      if (TAG_MENTION.test(line) && /(===|!==)\s*["'`]/.test(line)) compared.push(where);
    });
}
// 允许清单是一张空表：界面无须「知道」任何标记长什么样，它念的是引擎下发的那张表本身。
// 谁往这里加行，就是在给界面添第二份答案——那份表唯一的主人叫 capabilities.output_colour_tags。
assert.deepEqual(copied, [], `标记值只许待在引擎下发的那张表里，界面一行都不许抄：${copied.join("、")}`);
assert.deepEqual(compared, [], `不许拿标记与任何字面量比较：${compared.join("、")}`);

// —— ②′ 凡是把「这一条交付」念出来的地方，都必须念上标记 ——————————————————————
// 待发清单与交付方案那颗 chip 都在逐条复述交付内容：先前它们只说得出透明与帧率，
// 一份带标记的母版存进方案以后，界面上那句复述就少说一件事（本项目为这类「说半截」交付过缺陷）。
const tagEchoLines = panel
  .split(/\r?\n/)
  .filter((line) => line.includes("entry.colour_tag"));
assert.equal(
  tagEchoLines.length,
  2,
  "逐条复述交付内容的两处（待发清单与方案 chip）都要念上色彩标记，一处不许多一处不许少"
);
assert.ok(/色彩标记 \$\{entry\.colour_tag\}/.test(panel), "复述里用的是那一个真发出去的值，不是再算一次");
const help = read("views/Help.tsx");
assert.ok(help.includes("交付色彩标记"), "帮助里那一节必须认得出这一栏，不能只写在悬停里");
assert.ok(
  /七件事都在这一个面板里[\s\S]{0,240}交付色彩标记/.test(help),
  `导出那一节要把七个开关一次说全，不能停在「预设、文件名、文件夹」：${(help.match(/右侧·导出[\s\S]{0,200}/) ?? [""])[0]}`
);

console.log(
  "PASS: 交付色彩标记只有一张表（capabilities.output_colour_tags）与一处判断（colourTagAllowed）——" +
    "画面／容器／透明三个场合正反都判得到，没挑一个键都不发，引擎没这一档时照样不带标记出货，" +
    "而标记值在 desktop/src 一处都没出现"
);
