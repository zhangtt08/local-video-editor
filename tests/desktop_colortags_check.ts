/** 1.150：来源那一头可以由素材文件自己回答——界面只念引擎的话，一处都不判。
 *
 * 引擎给 `clip.color_manage` 加了 `auto_source`，并配了一次只读的回执（`POST …/color-space`）
 * 与一张随 capabilities 下发的对照表。这一版界面缺的不是控件，是克制，所以断的四件事：
 * ① 交出去的仍是那一条 `clip.color_manage`，只是多挂一个 `auto_source: true`——不新增 op，
 *    不在客户端补一段 reducer；
 * ② 「哪个标记算哪条曲线」在界面里没有第二份答案：整棵 desktop/src 连一个标记值都不出现，
 *    那张表只在一处被念出来，而念出来的返回值只能是话、不能是某个色彩空间；
 * ③ 门禁两个方向都判得到：引擎没下发 `color_manage_auto` 时那个勾根本不该出现，而手工那张
 *    下拉菜单必须照常能选（只知拒绝的门禁会把人关在没有路上，这条本项目交付过一次）；
 *    按钮亮不亮只看引擎那两个字段——标记长得再像能用，引擎说不能用就不用。
 * ④ 写之前真去问了那个只读端点（字面路径），而不是翻一遍 /v1/contracts 自己猜。
 */

import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { resolve } from "node:path";

import {
  autoSourceBlocker,
  autoSourceOffered,
  colorSpaceWords,
  handPickLive,
  handPickWords,
  manageSourceValue,
  shouldReadColorSpace,
  transferTagWords,
} from "../desktop/src/colorManage";
import { COLOR_SPACES, type ClipColorSpaceReport, type ColorSpace } from "../desktop/src/engine";

const label = (name: ColorSpace) => COLOR_SPACES.find(([entry]) => entry === name)?.[1] ?? name;

/** 引擎那次只读的回执长什么样，就按契约的样子造一份——四个标记字段一个都不省，
 *  因为拒绝的那一句必须把「读到了什么」一起念出来。 */
const receipt = (patch: Partial<ClipColorSpaceReport>): ClipColorSpaceReport => ({
  clip_id: "clip_1",
  asset_id: "asset_1",
  asset_label: "clip.mp4",
  space: null,
  auto_source_would_work: false,
  color_spaces: ["srgb", "rec709", "gamma22", "linear"],
  reason: "no_color_tags",
  tag: null,
  color_transfer: null,
  color_space: null,
  color_primaries: null,
  color_range: null,
  ...patch,
});

const detected = receipt({
  space: "rec709",
  auto_source_would_work: true,
  reason: "detected",
  tag: "bt709",
  color_transfer: "bt709",
  color_space: "bt709",
  color_primaries: "bt709",
  color_range: "tv",
});
const matrixOnly = receipt({
  reason: "no_transfer_tag",
  color_space: "bt709",
  color_primaries: "bt709",
  color_range: "tv",
});
const unmatched = receipt({ reason: "unmatched_transfer_tag", tag: "smpte2084", color_transfer: "smpte2084" });

// —— ① 那句「这份文件到底说了什么」：认出来了、被拒绝了、还没问过，三种都说得出 ——————
const said = colorSpaceWords(detected, label, "idle");
assert.ok(said.includes("Rec.709"), `认出来了要念引擎认的那条曲线，不许换成别的：${said}`);
assert.ok(said.includes("bt709"), `要念引擎实际读到的那个标记，人才对得上：${said}`);
assert.ok(!said.includes("手工"), `认出来了就不该把人支去手工那条路：${said}`);
assert.ok(colorSpaceWords(matrixOnly, label, "idle").includes("写了基色或量程"), `矩阵与基色定不出曲线，这句要说清：${colorSpaceWords(matrixOnly, label, "idle")}`);
assert.ok(
  colorSpaceWords(unmatched, label, "idle").includes("color_transfer=smpte2084"),
  `拒绝要把读到的标记点出来，不许只说「不支持」：${colorSpaceWords(unmatched, label, "idle")}`
);
assert.ok(colorSpaceWords(unmatched, label, "idle").includes("color_primaries=没写"), "没写的那一项要念成没写，不许假装有值");
const future = receipt({ reason: "a_reason_this_ui_has_never_seen", tag: "x", color_transfer: "x" });
assert.ok(
  colorSpaceWords(future, label, "idle").includes("a_reason_this_ui_has_never_seen"),
  `引擎将来新增的理由照原样念，不许换成一句顺耳的：${colorSpaceWords(future, label, "idle")}`
);
assert.ok(colorSpaceWords(null, label, "asking").includes("正在问"), "问的过程也有一句话，别留一片空白");
assert.ok(colorSpaceWords(null, label, "failed").includes("没给回执"), "问失败了要说「没给回执」，不能念成「这文件没标记」");
assert.ok(colorSpaceWords(null, label, "failed").includes("去掉"), "问失败了那句里要有真走得通的出路");
assert.ok(colorSpaceWords(null, label, "idle").includes("还没问过"), "没问过就说没问过");

// —— ② 门禁两个方向都判：没有这一档 ≠ 把手工那条路也关掉 ————————————————————————————
assert.equal(autoSourceOffered(undefined), false, "capabilities 还没回来就是没有这一档");
assert.equal(autoSourceOffered({}), false, "引擎没下发这个 flag 就没有");
assert.equal(autoSourceOffered({ color_manage_auto: false }), false, "引擎明说没有，界面不许当成有");
assert.equal(autoSourceOffered({ color_manage_auto: true }), true, "引擎说这一档在，界面就该给得出");

assert.equal(handPickLive(false, false), true, "引擎没这一档：手工那张下拉菜单照常能用");
assert.equal(handPickLive(true, false), true, "引擎没这一档：绝不许出现「勾着却灰掉」的死角");
assert.equal(handPickLive(false, true), true, "有这一档但没勾：还是人自己点");
assert.equal(handPickLive(true, true), false, "勾了自带标记：契约不许两头都答，这张下拉菜单先灰");
assert.ok(!handPickWords(false, false).includes("那个勾"), "引擎没这一档时不许提一个根本不存在的控件");
assert.ok(handPickWords(true, true).includes("去掉"), "灰掉的时候要说出真走得通的出路");
assert.ok(handPickWords(false, true).includes("手工"), "有这一档没勾的时候，手工那条路也要说得出");

assert.equal(shouldReadColorSpace(true, true, false), true, "有这一档、勾了、这段是画面：去问");
assert.equal(shouldReadColorSpace(false, true, false), false, "引擎没这一档就不发那次读——发了也只会被拒");
assert.equal(shouldReadColorSpace(true, true, true), false, "音频那段去问引擎会回 INVALID_COLOR：明知会被拒绝的读不发出去");
assert.equal(shouldReadColorSpace(true, false, false), false, "没勾就不问");

assert.equal(manageSourceValue(true, true, "srgb"), null, "勾了自带标记：来源那一头交 null，由文件回答");
assert.equal(manageSourceValue(false, true, "srgb"), "srgb", "引擎没这一档：人点的那个事一个字节都不改");
assert.equal(manageSourceValue(true, false, "srgb"), "srgb", "有这一档没勾：照人点的走");

// —— ③ 亮不亮只听引擎那两个字段，不从标记推 ——————————————————————————
assert.equal(autoSourceBlocker(true, true, detected, "idle"), null, "引擎说能用就用");
assert.equal(autoSourceBlocker(false, true, null, "idle"), null, "没有这一档时这条判断不该拦住手工那一次写");
const held = autoSourceBlocker(true, true, matrixOnly, "idle");
assert.ok(held !== null && held !== undefined, "引擎说这份文件定不出曲线，这颗按钮就不该亮着骗人");
assert.ok(held!.includes("color_space=bt709"), `按住的时候要念出它读到了什么：${held}`);
assert.ok(held!.includes("手工") && held!.includes("去掉"), `出路得是真走得通的那两条：${held}`);
// 标记看着明明能用，但引擎那句布尔说不能——听引擎的。从标记推出「应该也能用」，
// 就是界面在替素材编一个引擎并没有给出的答案。
const contradicted = receipt({ ...detected, auto_source_would_work: false });
assert.ok(autoSourceBlocker(true, true, contradicted, "idle"), "亮不亮只看 auto_source_would_work，不看标记长得像不像");
// 反方向也得判：引擎说能用，界面不许因为「这条理由我没见过」就把人按住。
const forward = receipt({ space: null, reason: "a_reason_this_ui_has_never_seen", auto_source_would_work: true });
assert.equal(autoSourceBlocker(true, true, forward, "idle"), null, "门禁只拒绝它确认拒绝的：没听过的理由不许把按钮焊死");
assert.ok(autoSourceBlocker(true, true, null, "asking")!.includes("稍等"), "还没问完就按住，并说清等什么");
assert.ok(autoSourceBlocker(true, true, null, "asking")!.includes("去掉"), "等不及的时候要有手工那条路");

// —— ②′ 那张对照表只念不算 ——————————————————————————————————
const table = [
  { tag: "iec61966-2-1", space: "srgb" as const },
  { tag: "bt709", space: "rec709" as const },
  { tag: "bt470m", space: "gamma22" as const },
  { tag: "linear", space: "linear" as const },
];
const shown = transferTagWords(table, label);
assert.ok(shown !== null && shown.includes("iec61966-2-1→sRGB"), `表照引擎下发的那一份念：${shown}`);
assert.ok(shown !== null && shown.includes("bt470m→gamma 2.2"), `曲线名翻成中文，标记名一个字都不改：${shown}`);
assert.equal(shown!.split("、").length, table.length, "几行就念几条，界面不往表里加自己认识的、也不减");
assert.equal(transferTagWords(undefined, label), null, "老引擎没这张表就不提它");
assert.equal(transferTagWords([], label), null, "表是空的也不硬凑一句");

// —— ④⑤ 接线：一条命令、一个只读端点、一个门禁 ————————————————————
const sources = ["desktop/src", "src"].map((part) => resolve(process.cwd(), part)).find(existsSync);
assert.ok(sources, "渲染层源码必须能从检查工作目录读到");
const files = readdirSync(sources!, { recursive: true })
  .map((entry) => String(entry).replace(/\\/g, "/"))
  .filter((entry) => /\.(ts|tsx)$/.test(entry) && statSync(resolve(sources!, entry)).isFile());
const read = (entry: string) => readFileSync(resolve(sources!, entry), "utf8");
const store = read("store.ts");
const engine = read("engine.ts");
const reader = read("colorManage.ts");
const grade = read("views/GradeFields.tsx");
const inspector = read("views/Inspector.tsx");

// ④ 交出去的仍是那一条 clip.color_manage，只是多挂一个开关。
assert.equal(store.split('"clip.color_manage"').length - 1, 1, "这条命令在 store 只有一处");
assert.ok(
  store.includes('{ op: "clip.color_manage", clip_id: clipId, source_space: source, display_space: display }'),
  "命令本体一字未动：来源与输出照旧的字段名",
);
assert.ok(store.includes("if (autoSource) command.auto_source = true;"), "开关只在人真勾了的时候才挂上去");
assert.equal(store.split("auto_source").length - 1, 1, "整个 store 只有一处会写 auto_source");
const submitPath = store.slice(store.indexOf("export function colorManageClip"), store.indexOf("export async function readClipColorSpace"));
assert.ok(!/op: "clip\.(?!color_manage)/.test(submitPath), "这条路上不许长出第二个 op");
assert.ok(store.includes('"套上色彩管理（来源按文件自带标记）"'), "历史里要分得开这两种套法");
assert.ok(!grade.includes('op: "'), "面板不自己拼命令：写入只从 store 那一个口子下去");
assert.ok(!grade.includes("clip.color_manage"), "op 的名字只有一处认识它，面板只是按下去");
assert.ok(
  grade.includes("onClick={() => colorManageClip(clipId, managePicked, manageDisplay, autoOn)}"),
  "这一行的提交把开关交进那一个口子",
);
assert.ok(grade.includes("onClick={() => colorManageClip(clipId, null, manageDisplay)}"), "「取下」不写开关：null 且不 auto 仍是取下来");
assert.ok(grade.includes("manageSourceValue(manageAutoGate, manageAuto, manageSource)"), "来源那一头写什么也只有一处判");
assert.ok(inspector.includes('"clip.color_manage": "色彩管理套叠"'), "历史那一步的中文名没被换掉");
assert.ok(!inspector.includes("clip.color_space"), "没有为这次新增发明第二条命令");

// ⑤ 写之前真去问了那个只读端点，路径是字面的，不是翻契约猜的。
assert.equal(
  engine.split("`/v1/projects/${projectId}/clips/${clipId}/color-space`").length - 1,
  1,
  "那次只读在渲染层只有一个出处，而且走的是 /color-space 这条字面路径",
);
assert.ok(
  engine.includes("clipColorSpace(projectId: string, clipId: string, body: { sequence_id: string | null })"),
  "请求体就是契约那一个字段：sequence_id，界面不多给",
);
assert.ok(!engine.includes("v1/contracts"), "界面不许去读契约再猜该发什么");
assert.ok(!reader.includes("/v1/"), "念回执的那一份不碰 URL：它只把引擎的话翻成中文");
assert.ok(!reader.includes("op:"), "读的那一份不写命令");
assert.ok(store.includes("engine.clipColorSpace(projectId, clipId, { sequence_id: state.sequenceId })"), "那次只读也只走一个口子");
assert.ok(grade.includes("readClipColorSpace(spaceProjectId, clipId)"), "这一行在写之前就去问了");
assert.ok(grade.includes("shouldReadColorSpace(manageAutoGate, manageAuto, assetKind === \"audio\")"), "问不问由那一处判断，含音频那条拒绝");
assert.ok(grade.includes("autoSourceBlocker(manageAutoGate, manageAuto, spaceRead, spacePhase)"), "亮不亮读的是那份回执，不是标记");
assert.ok(grade.includes("manageAutoBlock !== null"), "回执说走不通的时候，这条链子真的把按钮按住");
assert.ok(grade.includes("{autoOn ? <p className=\"hint\" title={tagTable ?? undefined}>{spaceLine}</p> : null}"), "问到的那句话写在行上，不是只藏在悬停里");
// 1.210：引擎那张标记对照表是「这一格认得哪些曲线」的来历，与那份回执不是同一件事；
// 它原来各占一行灰字（一格三行），现在挂在那一行的 title 上，眼前只留一行。
assert.match(grade, /<p className="hint" title=\{tagTable \?\? undefined\}>\{spaceLine\}<\/p>/, "那张对照表挂在这一行的 title 上");
assert.equal(grade.split("transferTagWords(").length - 1, 1, "念表只在面板一处调用，别在别处再念一遍");

// ③′ 门禁的来源是 capabilities，而且那句「这一版引擎没有」看得见。
assert.ok(grade.includes("autoSourceOffered(app.caps?.features)"), "有没有这一档只问 capabilities");
assert.equal(grade.split("autoSourceOffered(").length - 1, 1, "门禁只问那一个助手，不在别处再判一遍");
assert.equal(grade.split("color_manage_auto").length - 1, 1, "flag 的名字在面板里只出现在那句明说的fallback里");
// 1.209 那句话从「capabilities 里没有 color_manage_auto 这一档」收成「这一版引擎没有 color_manage_auto 这一档」：
// 说的是同一件事，钉的也是同一件事——缺这一档时必须点名，不许悄悄把控件藏起来。
assert.ok(/没有 color_manage_auto 这一档/.test(grade), "引擎没这一档要说出来，不许悄悄藏控件");
assert.match(
  grade,
  /manageAutoGate \? <label[\s\S]{0,700}来源按文件自带标记[\s\S]{0,1400}: <p className="hint">/,
  "引擎没下发这一档时那个勾根本不出现，而为什么写在行上",
);
assert.ok(grade.includes("disabled={!handPickLive(manageAuto, manageAutoGate)}"), "手工那张下拉菜单只在被自带标记顶掉时才灰");
assert.ok(grade.includes("title={handPickWords(manageAuto, manageAutoGate)}"), "灰掉时那句出路跟着控件一起给");
assert.ok(grade.includes("aria-label=\"色彩管理来源按文件自带标记\""), "那个勾有读屏叫得出名字");

// ②″ 标记值一个都不许抄进界面：表在引擎那一份，界面念它。
const TAG_VALUES = ["iec61966-2-1", "bt470m", "bt709"];
const copied: string[] = [];
const compared: string[] = [];
for (const entry of files) {
  read(entry)
    .split(/\r?\n/)
    .forEach((line, index) => {
      if (TAG_VALUES.some((value) => line.includes(value))) copied.push(`${entry}:${index + 1}`);
      if (/\.tag\s*===|tag:\s*"[a-z0-9-]+"\s*[,}]/.test(line)) compared.push(`${entry}:${index + 1}`);
    });
}
// 允许清单是一张空表：连「显示用的字面量」都不必存在，因为念的是引擎下发的表本身。
// 谁要往这里加行，就是在给界面添第二份答案——那份表唯一的主人叫 capabilities.color_transfer_tags。
const ALLOWED: string[] = [];
assert.deepEqual(copied, ALLOWED, `标记值只许待在引擎下发的那张表里，界面一行都不许抄：${copied.join("、")}`);
assert.deepEqual(compared, [], `不许拿标记做比较，也不许在界面里攒表：${compared.join("、")}`);
assert.equal(engine.split("color_transfer_tags").length - 1, 1, "capabilities 里那个字段在渲染层只声明一处");
assert.equal(reader.split("color_transfer_tags").length - 1, 0, "读的那一份连字段名都不碰：面板把下发的那一份交进来");
assert.equal(grade.split("color_transfer_tags").length - 1, 1, "面板只在一处念这张表");
assert.match(
  reader,
  /export function transferTagWords\([\s\S]*?\): string \| null \{/,
  "念表那个助手的返回值只能是话，不能是某个色彩空间",
);
assert.ok(reader.includes("report.space"), "念出来的那条曲线只可能是回执里那一个字段");
assert.equal(reader.split("ColorSpace | null").length - 1, 1, "界面唯一可能产出色空间的地方就是「交 null 还是交人点的那个」那一处");

console.log(
  "PASS: 来源那一头由文件自己回答——只读那次真问了 /color-space、按钮只听引擎那句 auto_source_would_work、"
  + "标记值在界面一处都不抄、引擎没这一档时手工那条路照常能走",
);
