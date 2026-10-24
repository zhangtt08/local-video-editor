// 1.278：片段右键菜单——`keymap.ts` 里那句「片段右键菜单与工具条」第一次真的指得到东西。
//
// 这一档钉的是**菜单不许长出第二个说法**：名字与键位读 keymap 那一份，能不能点读 clipRules
// 那一份（检查器与菜单共用），浮层挂到 body 上并把盒子夹在视口里，关掉后焦点交回原处。
// 真页面上「右键选中了谁、点了写没写进去」由 `tests/contextmenu_check.py` 量。
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import type { Clip, Project } from "../desktop/src/engine";
import { canDetachAudio, canLinkClips } from "../desktop/src/clipRules";
import { COMMANDS, DEFAULT_MAP, chordWords, commandLabel } from "../desktop/src/keymap";

declare const REPO_ROOT: string;

const read = (...parts: string[]) => {
  const found = parts.map((part) => resolve(process.cwd(), part)).find(existsSync) ?? resolve(REPO_ROOT, parts[0]);
  assert.ok(existsSync(found!), `找不到源文件：${parts.join(" 或 ")}`);
  return readFileSync(found!, "utf8");
};
const count = (text: string, needle: RegExp) => (text.match(needle) ?? []).length;

const timeline = read("desktop/src/views/Timeline.tsx");
const menu = read("desktop/src/ContextMenu.tsx");
const css = read("desktop/src/styles.css");
const app = read("desktop/src/App.tsx");
const inspector = read("desktop/src/views/Inspector.tsx");

// ① 两个入口都在：片段上有右键、空白轨道上有右键；宿主真的挂进应用。
assert.match(timeline, /onContextMenu=\{clipMenu\}/, "片段上没有右键入口");
assert.match(timeline, /onContextMenu=\{laneMenu\}/, "空白轨道上没有右键入口");
assert.ok(app.includes("<ContextMenuHost />"), "右键菜单的宿主没有挂进 App");
assert.ok(app.includes('from "./ContextMenu"'), "App 没有引入 ContextMenuHost");
assert.equal(count(menu, /export function openContextMenu/g), 1, "打开菜单的入口不止一处");
assert.equal(count(menu, /export function closeContextMenu/g), 1, "关闭菜单的入口不止一处");

// ② 浮层：挂到 body（时间线的 overflow/transform 会裁掉 fixed），两轴都夹在视口里。
assert.ok(menu.includes("createPortal("), "没有用 portal");
assert.ok(menu.includes("document.body"), "portal 没挂到 body");
assert.ok(menu.includes("window.innerWidth") && menu.includes("window.innerHeight"), "没有按视口夹位置");
assert.match(menu, /const below = request\.at\.y \+ height \+ EDGE_PIXELS <= window\.innerHeight/, "下边放不下时没有翻到指针上方");
// 量布局尺寸而不是矩形：开门动画停在 scale(.98)，矩形比真盒子小 2%——右下角会因此推出视口。
assert.ok(menu.includes("const width = node.offsetWidth;") && menu.includes("const height = node.offsetHeight;"), "量的是动画中的矩形而不是布局尺寸");
assert.ok(!/getBoundingClientRect\(\)/.test(menu), "菜单仍在拿 getBoundingClientRect 量摆放盒子");

// ③ 无障碍与键盘：菜单有名字、条目是 menuitem、方向键/Home/End/Escape 都在，外面按下就关。
assert.match(menu, /role="menu"/, "没有 role=menu");
assert.match(menu, /role="menuitem"/, "没有 role=menuitem");
for (const key of ["Escape", "Tab", "ArrowDown", "ArrowUp", "Home", "End"]) {
  assert.ok(menu.includes(`"${key}"`), `键盘少了 ${key}`);
}
assert.match(menu, /document\.addEventListener\("pointerdown", away, true\)/, "没有在外面按下时关掉");
assert.match(menu, /focus\(\{ preventScroll: true \}\)/, "关掉后没有把焦点交回原处");
assert.match(menu, /event\.stopPropagation\(\)/, "菜单里的按键会漏给全局快捷键");

// ④ 先关再执行：菜单不许在动作落库之后还挡在画面上，也不许点完还挂着。
const choose = menu.slice(menu.indexOf("const choose"), menu.indexOf("return createPortal"));
assert.ok(choose.length > 0 && choose.indexOf("onClose()") < choose.indexOf("entry.run()"), "点一项的顺序不是「先关再执行」");

// ⑤ 名字与键位只有 keymap 那一份：每一条命令都读 commandLabel 与 chordWords(keys[...])。
const builder = timeline.slice(timeline.indexOf("const clipMenu"), timeline.indexOf("  // 转场那块牌子占住左下角多宽"));
assert.ok(builder.length > 0, "找不到片段菜单的构造处");
for (const id of ["split-at-playhead", "copy", "paste", "duplicate", "delete-selection", "ripple-delete", "group", "ungroup", "link", "unlink"]) {
  assert.ok(builder.includes(`commandLabel("${id}")`), `菜单里「${id}」没有读 keymap 的名字`);
}
assert.ok(count(builder, /chordWords\(keys[.[]/g) >= 10, "键位提示没有读 keymap 那一份");
const hintLines = timeline.split("\n").filter((line) => /hint:/.test(line));
assert.ok(hintLines.length >= 10, `读到 ${hintLines.length} 条带键位提示的菜单项`);
assert.ok(hintLines.every((line) => line.includes("chordWords(")), "有一条键位提示是手写的");

// ⑥ 能点不能点读 clipRules 那一份——菜单与检查器同一个函数。
assert.ok(builder.includes("canLinkClips(project, members)"), "「链接音画」没有读共用判据");
assert.ok(builder.includes("canDetachAudio(project, clip)"), "「拆出音频」没有读共用判据");
assert.match(inspector, /canLinkClips\(project, clips\)/, "检查器没有读共用判据");
assert.match(inspector, /canDetachAudio\(project, clip\)/, "检查器那颗拆音按钮没有读共用判据");
assert.ok(!inspector.includes("kinds.size === 2"), "检查器还留着自己那份链接条件");

// ⑦ 右键落在没选中的一段上：先选中它（不然菜单改的是别人）。
assert.ok(builder.includes("if (!selected) selectClip(clip.id);"), "右键没有先选中被点的那一段");

// ⑧ 样式：抬起来的一层、14px 圆角、36px 行高、字号只从刻度里取。
const block = css.slice(css.indexOf(".ctx-menu"), css.indexOf("@keyframes ctx-in"));
assert.ok(block.length > 0, "样式表里没有 .ctx-menu");
assert.match(block, /border-radius: var\(--r-md\)/, "菜单没有用那一档圆角");
assert.match(block, /min-height: 36px/, "菜单行高不到 36px");
assert.match(block, /font-size: var\(--fs-body\)/, "条目字号没有读刻度");
assert.match(block, /font-size: var\(--fs-micro\)/, "键位没有读最小那一档");
assert.doesNotMatch(block, /font-size:\s*\d/, "菜单自己写了一档字号");

// ⑨ keymap 那句孪生说明现在是真的：它说的那个菜单就是这两个入口。
const duplicate = COMMANDS.find((item) => item.id === "duplicate");
assert.ok(duplicate && duplicate.twin.includes("片段右键菜单"), "keymap 里那句孪生说明被删了");
assert.equal(DEFAULT_MAP.duplicate.key, "d", "复制的默认键位不该被这一档改动");
assert.equal(chordWords(DEFAULT_MAP.duplicate), "Ctrl / ⌘ + D", chordWords(DEFAULT_MAP.duplicate));

// ⑩ 两条判据的边界（纯函数，不需要引擎）。
const project = {
  assets: {
    v: { kind: "video", verified: { has_audio: true } },
    a: { kind: "audio", verified: {} },
    mute: { kind: "video", verified: { has_audio: false } },
    img: { kind: "image", verified: {} },
  },
} as unknown as Project;
const clip = (id: string, asset: string, extra: Record<string, unknown> = {}) =>
  ({ id, asset_id: asset, position_ticks: 0, duration_ticks: 100, ...extra }) as unknown as Clip;

assert.equal(canLinkClips(project, [clip("v", "v"), clip("a", "a")]), true, "对得上的音画说不能链接");
assert.equal(canLinkClips(project, [clip("v", "v"), clip("a", "a", { position_ticks: 5 })]), false, "开始不一样仍说能链接");
assert.equal(canLinkClips(project, [clip("v", "v"), clip("a", "a", { duration_ticks: 90 })]), false, "时长不一样仍说能链接");
assert.equal(canLinkClips(project, [clip("v", "v"), clip("a", "a", { speed_percent: 200 })]), false, "速度不一样仍说能链接");
assert.equal(canLinkClips(project, [clip("v", "v"), clip("v2", "v")]), false, "两段画面说能链接");
assert.equal(canLinkClips(project, [clip("v", "v")]), false, "只有一段说能链接");

assert.equal(canDetachAudio(project, clip("v", "v")), true, "带声音的画面说不能拆");
assert.equal(canDetachAudio(project, clip("v", "v", { embedded_audio: false })), false, "已经标成没有内嵌声音仍说能拆");
assert.equal(canDetachAudio(project, clip("a", "a")), false, "纯声音片段说能拆");
assert.equal(canDetachAudio(project, clip("m", "mute")), false, "没有声道的画面说能拆");
assert.equal(canDetachAudio(project, clip("i", "img")), false, "图片说能拆");
assert.equal(canDetachAudio(project, undefined), false, "没有片段也说能拆");

console.log(
  `PASS: 片段右键菜单接上了那句写了很久的孪生说明——${hintLines.length} 条键位读 keymap、` +
    `十个名字读 commandLabel、能点不能点读 clipRules（检查器同一份），浮层挂 body 且两轴夹在视口里，` +
    `方向键/Home/End/Escape 与「关掉后交回焦点」都在，样式只用三档字号与 14px 圆角`,
);
