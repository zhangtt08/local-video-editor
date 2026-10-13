/** 1.130：一键色彩管理在界面这一侧只有一份读法、一条命令。
 *
 * 引擎那条 `clip.color_manage` 写下两个盖了章的转换节点，界面这边不许自己拼这两个节点，也不许
 * 「看哪两个转换节点像是色彩管理」——认人只认章。所以这里断的是四件事：① `managedPair` 只按
 * `purpose` 认这一对，位置、邻居、中间被改过都不影响；②「装不装得下」的判断只有一处实现，
 * 而且是「取下旧的一对以后再放两个」而不是「现在还剩两个位置」，否则已经套着的满链就换不了空间；
 * ③ 两张下拉菜单的候选来自引擎下发的 `capabilities.color_spaces`，界面那份中文表只是翻译；
 * ④ 交出去的载荷就是那一条命令的四个字段，一个字节都不多。
 */

// `REPO_ROOT` is defined by tests/desktop_ts_check.py at bundle time.
declare const REPO_ROOT: string;
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { manageFits, manageSpaces, managedPair, managedWords, taggedCount } from "../desktop/src/colorManage";
import { COLOR_SPACES, type ColorSpace, type GradeNode } from "../desktop/src/engine";

const SRC = REPO_ROOT + "desktop/src/";
const store = readFileSync(SRC + "store.ts", "utf8");
const grade = readFileSync(SRC + "views/GradeFields.tsx", "utf8");
const engine = readFileSync(SRC + "engine.ts", "utf8");
const inspector = readFileSync(SRC + "views/Inspector.tsx", "utf8");
const help = readFileSync(SRC + "views/Help.tsx", "utf8");
const reader = readFileSync(SRC + "colorManage.ts", "utf8");

const head = (input: ColorSpace, output: ColorSpace, purpose?: "color_manage"): GradeNode => ({
  kind: "transfer",
  input_space: input,
  output_space: output,
  enabled: true,
  ...(purpose ? { purpose } : {}),
});
const curve = (): GradeNode => ({
  kind: "curve",
  channel: "rgb",
  points: [
    { x: 0, y: 0 },
    { x: 0.5, y: 0.28 },
    { x: 1, y: 1 },
  ],
  enabled: true,
});
const levels = (): GradeNode => ({ kind: "levels", channel: "rgb", black: 0.05, white: 0.95, gamma: 1.1, enabled: true });

// —— ① 只认章：完整的一对、缺一只、方向不对、被挪了位置 ————————————————
const pairCases: { title: string; nodes: GradeNode[]; expected: { source: ColorSpace; display: ColorSpace } | null }[] = [
  {
    title: "空链",
    nodes: [],
    expected: null,
  },
  {
    title: "只有手工加的两个转换节点（没盖章）",
    nodes: [head("srgb", "linear"), head("linear", "rec709")],
    expected: null,
  },
  {
    title: "套在空链上的一对",
    nodes: [head("srgb", "linear", "color_manage"), head("linear", "rec709", "color_manage")],
    expected: { source: "srgb", display: "rec709" },
  },
  {
    title: "中间夹着曲线与色阶的一对",
    nodes: [head("gamma22", "linear", "color_manage"), curve(), levels(), head("linear", "srgb", "color_manage")],
    expected: { source: "gamma22", display: "srgb" },
  },
  {
    title: "章还在、顺序被人在链子里拖乱了",
    nodes: [curve(), head("linear", "rec709", "color_manage"), head("srgb", "linear", "color_manage")],
    expected: null,
  },
  {
    title: "另一半被手工删掉，只剩一只盖过章的",
    nodes: [head("srgb", "linear", "color_manage"), curve()],
    expected: null,
  },
  {
    title: "盖章的那对底下还压着一只未盖章的转换",
    nodes: [head("srgb", "linear", "color_manage"), head("gamma18", "linear"), curve(), head("linear", "rec709", "color_manage")],
    expected: { source: "srgb", display: "rec709" },
  },
];
for (const item of pairCases) {
  assert.deepEqual(managedPair(item.nodes), item.expected, item.title);
}
assert.equal(taggedCount(pairCases[5].nodes), 1, "少一半要说得出少了几只");
assert.equal(taggedCount(pairCases[1].nodes), 0, "未盖章的转换节点不是这一对的");

// —— ② 装不装得下：取下旧的以后再放两个，而不是数剩下的空格 ——————————
const fitCases: { title: string; nodes: GradeNode[]; expected: boolean }[] = [
  { title: "满链八个空格都不剩", nodes: Array.from({ length: 8 }, curve), expected: false },
  { title: "七个节点，加这一对正好满", nodes: Array.from({ length: 7 }, curve), expected: false },
  { title: "六个节点，放得下", nodes: Array.from({ length: 6 }, curve), expected: true },
  {
    title: "已经套着的满链：换一套空间不该被挡住",
    nodes: [head("srgb", "linear", "color_manage"), ...Array.from({ length: 6 }, curve), head("linear", "rec709", "color_manage")],
    expected: true,
  },
  {
    title: "只剩一只盖章的：取下它以后还差一个位置",
    nodes: [head("srgb", "linear", "color_manage"), ...Array.from({ length: 7 }, curve)],
    expected: false,
  },
  { title: "空链当然放得下", nodes: [], expected: true },
];
for (const item of fitCases) {
  assert.equal(manageFits(item.nodes, 8), item.expected, item.title);
}
assert.equal(manageFits(fitCases[2].nodes, 9), true, "上限由引擎下发，界面照这个数判");
assert.equal(manageFits(fitCases[2].nodes, 7), false, "同一个判断换个上限要给回相反的答案");

// —— ③ 名单归引擎，中文表只是翻译 ————————————
const spaces = manageSpaces(["srgb", "linear", "rec709"], COLOR_SPACES);
assert.deepEqual(
  spaces.map(([name]) => name),
  ["srgb", "linear", "rec709"],
  "顺序与成员都跟着引擎下发的那一份",
);
assert.equal(spaces[0][1], "sRGB（网页与屏幕录制）", "认得的名字翻译成中文");
const drifted = manageSpaces(["srgb", "hlg", "rec709"], COLOR_SPACES);
assert.equal(drifted.length, 3, "引擎新认得的空间不许被翻译表悄悄丢掉");
assert.ok(drifted[1][1].includes("hlg"), "翻译不出来就照原样念，别丢");
assert.deepEqual(
  manageSpaces(undefined, COLOR_SPACES).map(([name]) => name),
  COLOR_SPACES.map(([name]) => name),
  "引擎没回这一字段时用界面那张表兜底",
);
assert.equal(COLOR_SPACES.length, 7, "界面这张中文表与契约的七个名字一一对应（成员由 tests/colormanage_check.py 核）");

const label = (name: ColorSpace) => manageSpaces(undefined, COLOR_SPACES).find(([entry]) => entry === name)?.[1] ?? name;
const said = managedWords({ source: "srgb", display: "rec709" }, 2, label);
assert.ok(said.includes("sRGB") && said.includes("Rec.709") && said.includes("线性光"), `套着的状态要说清两头：${said}`);
const none = managedWords(null, 0, label);
assert.ok(none.includes("没有套色彩管理") && none.includes("存储值"), `没套上要说「按存储值调」：${none}`);
const broken = managedWords(null, 1, label);
assert.ok(broken.includes("不成一对") && !broken.includes("没有套色彩管理"), `只剩一只时要说「不成一对」，不能念成没套上：${broken}`);
assert.ok(broken.includes("套上") && broken.includes("取下"), "缺的那一半要说得出两条走得通的出路");

// —— ④ 交出去的只有一条命令，界面不自己拼那两个节点 ——————————————————
assert.equal(store.split('"clip.color_manage"').length - 1, 1, "整个 store 只有一处写这条命令");
assert.ok(
  store.includes('{ op: "clip.color_manage", clip_id: clipId, source_space: source, display_space: display }'),
  "载荷就是那四个字段，没有第二个来源",
);
assert.ok(store.includes('source === null ? "取下色彩管理" : "套上色彩管理（在线性光里调色）"'), "历史标签分套上与取下两种");
assert.ok(!/colorManageClip[\s\S]{0,400}kind: "transfer"/.test(store.slice(store.indexOf("export function colorManageClip"), store.indexOf("export function colorManageClip") + 400)), "store 不许自己造那两个转换节点");
assert.ok(!reader.includes("op:"), "读的那一份不写命令");
assert.ok(grade.includes("manageFits(nodes, limits.nodes)"), "按钮亮不亮问那一处判断");
assert.ok(grade.includes("managedPair(nodes)") && grade.includes("taggedCount(nodes)"), "当前套的是哪一对也问同一处");
assert.ok(grade.includes("manageSpaces(app.caps?.color_spaces, COLOR_SPACES)"), "候选名单来自引擎下发的那一份");
assert.equal(grade.split("colorManageClip(clipId,").length - 1, 2, "套上与取下两个按钮走同一个口子");
assert.ok(grade.includes("disabled={Boolean(manageBlock) || locked || Boolean(app.busy)}"), "只会弹错的按钮不亮着");
assert.ok(grade.includes("disabled={!managedTagged || locked || Boolean(app.busy)}"), "没有可取的就不亮「取下」");
assert.ok(!grade.includes("purpose"), "调色面板不自己写那个章：盖章是引擎那一次说一不二的决定");
assert.equal(engine.split('"color_manage"').length - 1, 1, "整个界面只有节点类型这一处认识那个章的名字");
assert.ok(grade.includes("aria-label=\"色彩管理来源空间\"") && grade.includes("aria-label=\"色彩管理输出空间\""), "两张下拉菜单有读屏叫得出名字");

// —— ⑤ 契约、错误词汇与帮助 ————————————————————————————————
assert.ok(engine.includes('purpose?: "color_manage" | null'), "转换节点的类型带得上引擎那个章");
assert.ok(engine.includes("color_spaces?: ColorSpace[]"), "capabilities 里带着那份名单");
for (const code of ["COLOR_MANAGE_NOT_SET", "COLOR_MANAGE_IDENTITY", "COLOR_MANAGE_LIMIT", "COLOR_MANAGE_NO_CHANGE"]) {
  const sentence = engine.match(new RegExp(`      ${code}: "([^"]*)",`));
  assert.ok(sentence, `${code} 没有中文说法，界面会把英文原样念出来`);
  assert.ok(sentence[1].length >= 24, `${code} 的中文说法太短，说不出出路：${sentence[1]}`);
}
assert.ok(inspector.includes('"clip.color_manage": "色彩管理套叠"'), "历史里这一步要有中文名");
assert.ok(help.includes("调色节点·一键色彩管理"), "帮助里要写这一键");
assert.ok(help.includes("[0,20,44,103,183,252]"), "帮助里写的是实测出来的那组数，不是形容词");

console.log("PASS: 色彩管理在界面这一侧只有一份读法、一条命令、两张跟着引擎的下拉菜单");
