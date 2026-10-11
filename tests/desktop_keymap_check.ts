/** 1.134：命令键位只有一张表，它能改、会冲突、落得了库，而且每条都还有界面上那个孪生。
 *
 * 以前 `App.tsx` 里是一条 if 链，「Ctrl+B」这三个字在 `Help.tsx` 的快捷键页又抄了一遍给人看：
 * 两处会有一天说出不同的键，而人没有地方改。这里跑的是**真 store**（照 `desktop_snappref_check.ts`
 * 的先例先摆好假 localStorage 再 import），断的是行为：
 *
 *  ① `DEFAULT_MAP` 就是这次改动之前实际在按的那套键——逐条对，不对就是改了行为；
 *  ② 解析只有一处：Ctrl+Z 与 Ctrl+Shift+Z 要分到两件事（精确 Shift 的那条赢），而 Ctrl+Shift+A
 *    仍然就是全选（标 "any" 的那条）；裸 M 记标记、Ctrl+M 开导出，两条不许互相抢；
 *  ③ 改键改的是分发，不是文案：改完之后旧键不再做事、新键做那件事，落进 localStorage 的只有改过
 *    的那一条，重开窗口读回来的还是它；
 *  ④ 冲突与不可用都要点名——抢了「撤销」的键要说抢的是谁，没有修饰键的单键直接拒（那会抢掉
 *    正在打字的人）；被拒的那一次现值一个字不动；
 *  ⑤ 视图里不许留第二处字面量：`App.tsx` 里那几个老比较没了，`Help.tsx` 也不再自己写「Ctrl+B」；
 *  ⑥ 每条命令都得有那条鼠标路：表里 `twin` 不为空，而 `runKeyCommand` 的开关里每个 id 都有一格。
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const SRC = "C:/Users/Administrator/Desktop/项目/agentcut/";

const store = new Map<string, string>();
// 改键的成功与拒绝都要念一句话出来，而那句话经由 `store.toast` 的定时器挂在窗口上；
// node 里没有 window，所以这里给一个只记账的假面（断言看的是键位本身，不是那条 toast 的寿命）。
const scheduled: Array<() => void> = [];
Object.assign(globalThis, {
  localStorage: {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
  },
  window: {
    setTimeout: (fn: () => void) => void scheduled.push(fn) || scheduled.length,
    clearTimeout: () => undefined,
  },
});

const { DEFAULT_MAP, COMMANDS, chordWords, matchCommand, rebind, mergeMap, changedFromDefault, chordFromEvent } = await import(
  "../desktop/src/keymap"
);
const { keymap, remap } = await import("../desktop/src/store");

const press = (key: string, modifiers: { ctrl?: boolean; alt?: boolean; shift?: boolean; meta?: boolean } = {}) => ({
  key,
  ctrlKey: Boolean(modifiers.ctrl),
  altKey: Boolean(modifiers.alt),
  shiftKey: Boolean(modifiers.shift),
  metaKey: Boolean(modifiers.meta),
});

// —— ① 出厂那张表就是这次改动之前在按的那套 —————————————————————————
const SHIPPED: Array<[string, string, boolean | undefined, boolean | "any"]> = [
  ["undo", "z", true, false],
  ["redo", "z", true, true],
  ["duplicate", "d", true, "any"],
  ["select-all", "a", true, "any"],
  ["copy", "c", true, "any"],
  ["paste", "v", true, "any"],
  ["split", "b", true, "any"],
  ["export-panel", "m", true, "any"],
  ["marker", "m", undefined, "any"],
  ["group", "g", true, false],
  ["ungroup", "g", true, true],
  ["link", "l", true, false],
  ["unlink", "l", true, true],
];
assert.equal(COMMANDS.length, SHIPPED.length, "能改的命令一共就这些条，多一条少一条都得先过这一格");
for (const [id, key, ctrl, shift] of SHIPPED) {
  const chord = DEFAULT_MAP[id as keyof typeof DEFAULT_MAP];
  assert.equal(chord.key, key, `出厂键位变了：${id} 该按 ${key}`);
  assert.equal(chord.ctrl, ctrl, `${id} 的修饰键对不对得上以前那条 if 链：Ctrl=${ctrl}`);
  assert.equal(chord.alt, undefined, `${id} 出厂不带 Alt`);
  assert.equal(chord.shift, shift, `${id} 的 Shift 语义：${shift}`);
}

// —— ② 解析只有一处，而且精确 Shift 的那条赢 ————————————————————————
const map = keymap();
assert.equal(matchCommand(map, press("z", { ctrl: true })), "undo", "Ctrl+Z 是撤销");
assert.equal(matchCommand(map, press("Z", { ctrl: true })), "undo", "大写 Z 也是同一条（读的是小写形式）");
assert.equal(matchCommand(map, press("z", { ctrl: true, shift: true })), "redo", "按下 Shift 就换一件事：Ctrl+Shift+Z 是重做");
assert.equal(matchCommand(map, press("z", { meta: true })), "undo", "Mac 的 ⌘ 与 Windows 的 Ctrl 是同一条");
assert.equal(matchCommand(map, press("a", { ctrl: true, shift: true })), "select-all", "标了 any 的那条不管 Shift 按没按");
assert.equal(matchCommand(map, press("g", { ctrl: true })), "group", "Ctrl+G 组合");
assert.equal(matchCommand(map, press("g", { ctrl: true, shift: true })), "ungroup", "Ctrl+Shift+G 取消组合");
assert.equal(matchCommand(map, press("l", { ctrl: true, shift: true })), "unlink", "Ctrl+Shift+L 解除链接");
assert.equal(matchCommand(map, press("m")), "marker", "不带修饰的 M 记标记");
assert.equal(matchCommand(map, press("m", { ctrl: true })), "export-panel", "同一个字母带 Ctrl 是另一条命令，两条不许互抢");
assert.equal(matchCommand(map, press("m", { alt: true })), null, "带 Alt 的 M 谁都不做——不许把没定义的组合猜成一条命令");
assert.equal(matchCommand(map, press("Shift")), null, "只按下 Shift 不算一次按键");
assert.equal(matchCommand(map, press("b", { ctrl: true })), "split", "Ctrl+B 剪开");
assert.equal(matchCommand(map, press("b")), null, "裸 B 不是分割工具那条键（工具键跟着上下文，不在这张表里）");
// 上面那两条靠的是**顺序里恰好没人抢**，所以这里把两种会抢的情形各摆一次：
// 一条标 "any" 的键排在精确那条之前，和一条裸键排在带修饰那条之前——解析处必须让更具体的那条赢。
const looseFirst = { ...map, undo: { key: "z", ctrl: true, shift: "any" } };
assert.equal(
  matchCommand(looseFirst, press("z", { ctrl: true, shift: true })),
  "redo",
  "specific-shift wins: 一条标 any 的键排在前面，也不许把按下 Shift 的那件事抢走",
);
const bareFirst = { ...map, undo: { key: "m", shift: "any" } };
assert.equal(
  matchCommand(bareFirst, press("m", { ctrl: true })),
  "export-panel",
  "modifier-required wins: 没修饰的那条不许把带 Ctrl 的按下去也接走",
);

// —— ②b 改键时读的那一次按下 ——————————————————————————
assert.equal(chordFromEvent(press("Shift")), null, "只按下修饰键时界面要继续等，不许把「Shift」当成一条新键位存进去");
assert.deepEqual(chordFromEvent(press("k", { ctrl: true })), { key: "k", shift: false, ctrl: true }, "Ctrl+K 读成 {k, ctrl}，Shift 按精确状态记");
assert.deepEqual(chordFromEvent(press("z", { meta: true, shift: true })), { key: "z", shift: true, ctrl: true }, "Mac 的 ⌘ 与 Ctrl 存成同一个位");

// —— ③ 改的是分发，不是文案，而且落得了库 ———————————————————————————
assert.ok(remap.set("split", { key: "x", ctrl: true, shift: "any" }), "改键要成功");
assert.equal(matchCommand(keymap(), press("x", { ctrl: true })), "split", "rebound-key dispatches: 新键做那件事");
assert.equal(matchCommand(keymap(), press("b", { ctrl: true })), null, "old-key goes silent: 旧键就不再做事了");
const persisted = JSON.parse(store.get("agentcut.keys") ?? "{}") as Record<string, unknown>;
assert.deepEqual(Object.keys(persisted), ["split"], "落库的只有改过的那一条，默认表不占存储");
assert.equal(chordWords(keymap().split), "Ctrl / ⌘ + X", "念出来的顺序是人预期的那个：修饰键在前、键在后");
assert.equal(chordWords(DEFAULT_MAP.redo), "Ctrl / ⌘ + Shift + Z", "带 Shift 的那条要念得出 Shift，而且顺序是人预期的那个");

// 重开窗口：读回来的就是写出去的那一份（同一个字符串，不重算）。
const again = mergeMap(JSON.parse(JSON.stringify(persisted)) as unknown);
assert.equal(again.split.key, "x", "重启以后改过的键还在");
assert.equal(again.copy.key, "c", "没改过的那条仍是出厂的键");

// —— ④ 冲突与不可用都点名，被拒不写半个字 ————————————————————————————
const clash = rebind(keymap(), "copy", { key: "z", ctrl: true, shift: false });
assert.equal(clash.ok, false, "一个键不能同时属于两条命令");
assert.equal(clash.takes, "undo", "要说清抢的是哪一条，而不是只回一句「冲突」");
assert.ok(String(clash.why).includes("撤销"), "那句话里带着被抢那条命令的名字");
assert.ok(!remap.set("copy", { key: "z", ctrl: true, shift: false }), "界面上点这一下要失败");
assert.equal(keymap().copy.key, "c", "被拒的那一次现值一个字都不动");
assert.equal(matchCommand(keymap(), press("c", { ctrl: true })), "copy", "所以 Ctrl+C 还是复制");
assert.equal(rebind(keymap(), "copy", { key: "j" }).ok, false, "没有修饰键的单键要拒：那会抢掉正在打字的人");
assert.ok(String(rebind(keymap(), "copy", { key: "j" }).why).includes("修饰键"), "那句拒绝要说清为什么");
assert.equal(remap.set("marker", { key: "n", ctrl: true, alt: true, shift: "any" }), true, "带 Alt 的组合是能改的");
assert.equal(chordWords(keymap().marker), "Ctrl / ⌘ + Alt + N", "两个修饰键都念得出来");

// 一把脏数据：认不出的 id、空键、没修饰的键都要丢掉，而不是让界面崩。
const poisoned = mergeMap({ split: { key: "" }, nonsense: 1, undo: { key: "z" }, copy: { key: "c", ctrl: true, shift: true } });
assert.equal(poisoned.split.key, "b", "空键丢掉之后那条回到出厂——存储坏了不等于把剪开弄没");
assert.equal(poisoned.undo.shift, false, "没修饰的读回值不接管出厂那条");
assert.equal(poisoned.copy.shift, true, "形状对的那条照收");

// —— ④b 一键回到出厂：改过的痕迹连存储里都不许留 ————————————————————
remap.reset();
assert.equal(matchCommand(keymap(), press("b", { ctrl: true })), "split", "reset-restores: 回到出厂那一套，剪开又是 Ctrl+B");
assert.equal(matchCommand(keymap(), press("x", { ctrl: true })), null, "改过的那个键不再做剪开");
assert.equal(matchCommand(keymap(), press("m", { ctrl: true, alt: true })), null, "marker 那个 Alt 组合也跟着回去了");
assert.deepEqual(JSON.parse(store.get("agentcut.keys") ?? "null"), {}, "存储里改过的痕迹也清干净：重开窗口读不回一个已经不存在的键位");

// —— ⑤ 视图里不许再留第二处字面量 ————————————————————————————
const app = readFileSync(SRC + "desktop/src/App.tsx", "utf8");
const help = readFileSync(SRC + "desktop/src/views/Help.tsx", "utf8");
assert.ok(app.includes("matchCommand(keymap(), event)"), "按键分发只问这一处");
assert.ok(app.includes("runKeyCommand(command, event)"), "做的事也只有那一个开关");
assert.ok(!app.includes('event.key.toLowerCase() === "z"'), "老的逐条比较不许还留着");
assert.ok(!app.includes('["a", "c", "v"].includes(key)'), "复制/粘贴/全选不再各写一遍字面量");
assert.ok(!app.includes('key === "b" && '), "剪开那条也是");
assert.ok(!help.includes('"Ctrl+B"') && !help.includes('"Ctrl+Z"'), "帮助页不再自己抄一份键名");
const timeline = readFileSync(SRC + "desktop/src/views/Timeline.tsx", "utf8");
assert.ok(timeline.includes("chordWords(keymap().split)"), "tooltip-live: 那颗「分割」按钮悬停里念的是当前键位");
assert.ok(timeline.includes("chordWords(keymap().copy)") && timeline.includes("chordWords(keymap().paste)"), "复制/粘贴那两句也一样");
assert.ok(!timeline.includes("（Ctrl+B）") && !timeline.includes("（Ctrl+C）") && !timeline.includes("（Ctrl+V）"), "视图里不许留着写死的键名：改了键之后那句就成了假话");
assert.ok(timeline.includes("chordWords(keymap().redo)"), "redo-live: 重做那颗也跟着表念");
const titlebar = readFileSync(SRC + "desktop/src/TitleBar.tsx", "utf8");
const inspector = readFileSync(SRC + "desktop/src/views/Inspector.tsx", "utf8");
const engineHint = readFileSync(SRC + "desktop/src/engine.ts", "utf8");
assert.ok(titlebar.includes('chordWords(keymap()["export-panel"])'), "导出按钮的悬停念的也是当前键位");
assert.ok(inspector.includes("chordWords(keymap().duplicate)"), "检查器那句「复制一段」也是");
for (const [name, src] of [["Timeline", timeline], ["TitleBar", titlebar], ["Inspector", inspector]] as const) {
  assert.ok(!/（Ctrl\+[A-Z]/.test(src), `${name} 里不许再留着写死的键名`);
}
assert.ok(!engineHint.includes("用撤销（Ctrl+Z）"), "hint-no-chord: 引擎错误的那句中文说明里不许写死撤销的键名");
assert.ok(help.includes("COMMANDS.map"), "那一节的每一行都从那张表来");
assert.ok(help.includes("remap.set(armed, chord)"), "改键走的是 store 那唯一的一处");
assert.ok(changedFromDefault(DEFAULT_MAP) && Object.keys(changedFromDefault(DEFAULT_MAP)).length === 0, "没人改过的时候落库是空的");

// —— ⑥ 每条命令都还有那条鼠标路 ————————————————————————————
const storeSrc = readFileSync(SRC + "desktop/src/store.ts", "utf8");
for (const item of COMMANDS) {
  assert.ok(item.twin.length > 4, `${item.id} 必须有界面上那个孪生：键盘不是唯一的路`);
  assert.ok(storeSrc.includes(`case "${item.id}":`), `${item.id} 在那一个开关里要有一格——表里能选、按下去没人做，是更糟的键位表`);
}

// 时间线那种上下文数字与本检查无关，但顺手钉一下这张表的边界：手感键不许被塞进来。
assert.ok(!COMMANDS.some((item) => ["space", "arrowleft", "i", "o", "k"].includes(item.id)), "方向键、I/O、空格这些跟着焦点走的不算命令");

console.log("PASS: 命令键位一张表、解析一处、改得动也落得了库，冲突点名到被抢的那条，十三件事都还有界面上那个按钮");
