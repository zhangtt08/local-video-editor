/** 链接的差值只有一处说法：引擎报的四个轴，界面照着念，不自己再算一遍。
 *
 * 1.127 加的是「只动链接的一边」（J/L cut）。引擎那边 `link_status` 早就把每个成员相对基准的
 * 位置、源入点、时长、速度差算好了，缺的是两件事：① 一句说得清「差了多久、哪一边」的人话——
 * 1.127 之前界面只写「音画已失步：位置、源入点、时长或速度不同」，把四个数扔回给人自己找；
 * ② 一步走得通的出路，也就是 `clips.link_reconcile`。所以这里断的是：那句话唯一的数字来源是
 * 引擎的 `differences`（视图不许自己算，也不许自带时基常量），而「拉回同步」交出去的是一条
 * `clips.link_reconcile`，不是界面拼出来的三条 `clip.trim`。
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { linkOffsetParts, linkOffsetSentence } from "../desktop/src/linkOffset";
import { linkSplitTrim, type SplitTrim } from "../desktop/src/splitTrim";
import { offsetWords } from "../desktop/src/time";
import type { LinkStatus } from "../desktop/src/engine";

const SECOND = 70_560_000;
// 一个只把引擎给的 ticks 变成字的面子；断言看的是它收到的是哪个数，不是它怎么格式化。
const say = (ticks: number) => `${ticks / SECOND}s`;

const link = (
  anchor: string,
  differences: LinkStatus["differences"],
  synchronized = false,
): LinkStatus => ({
  clip_ids: Object.keys(differences),
  synchronized,
  anchor_clip_id: anchor,
  differences,
});

const nameOf = (id: string) => (id.startsWith("a") ? `声音 ${id}` : `画面 ${id}`);

// —— ① 每个轴各说各的，正负分开，零不念 ——————————————————————————————
const cases: { title: string; status: LinkStatus; expected: string[] }[] = [
  {
    title: "声音比画面短一秒",
    status: link("vp_a", { vp_a: { position_ticks: 0, source_ticks: 0, duration_ticks: 0, speed_percent: 0 }, ap_a: { position_ticks: 0, source_ticks: 0, duration_ticks: SECOND, speed_percent: 0 } }),
    expected: ["比基准长 1s"],
  },
  {
    title: "画面被剪短之后声音长出来",
    status: link("vp_a", { ap_a: { position_ticks: 0, source_ticks: 0, duration_ticks: -SECOND, speed_percent: 0 } }),
    expected: ["比基准短 1s"],
  },
  {
    title: "声音晚一秒开始",
    status: link("vp_b", { ap_b: { position_ticks: SECOND, source_ticks: SECOND, duration_ticks: 0, speed_percent: 0 } }),
    expected: ["开始比基准晚 1s", "源入点比基准靠后 1s"],
  },
  {
    title: "声音早半秒开始",
    status: link("vp_b", { ap_b: { position_ticks: -SECOND / 2, source_ticks: -SECOND / 2, duration_ticks: 0, speed_percent: 0 } }),
    expected: ["开始比基准早 0.5s", "源入点比基准靠前 0.5s"],
  },
  {
    title: "只有速度不同",
    status: link("vp_c", { ap_c: { position_ticks: 0, source_ticks: 0, duration_ticks: 0, speed_percent: 25 } }),
    expected: ["速度差 +25%"],
  },
  {
    title: "慢下来的那一路",
    status: link("vp_c", { ap_c: { position_ticks: 0, source_ticks: 0, duration_ticks: 0, speed_percent: -20 } }),
    expected: ["速度差 -20%"],
  },
  {
    title: "一个轴都没差",
    status: link("vp_d", { ap_d: { position_ticks: 0, source_ticks: 0, duration_ticks: 0, speed_percent: 0 } }),
    expected: [],
  },
];

for (const item of cases) {
  const member = Object.keys(item.status.differences).find((id) => id !== item.status.anchor_clip_id)!;
  assert.deepEqual(
    linkOffsetParts(item.status.differences[member], say),
    item.expected,
    `${item.title}：念出来的不只是一句「已失步」`,
  );
}

// 引擎把差值按「相对基准」报，所以基准自己那一条永远是零，界面不许再自己找基准。
const cut = link("vp_a", {
  vp_a: { position_ticks: 0, source_ticks: 0, duration_ticks: 0, speed_percent: 0 },
  ap_a: { position_ticks: 0, source_ticks: 0, duration_ticks: SECOND, speed_percent: 0 },
});
assert.equal(
  linkOffsetSentence(cut, nameOf, say),
  "以画面 vp_a 为基准 · 声音 ap_a：比基准长 1s",
  "整句要同时点名基准与动过的那一路",
);
// 三方都在的链接：每个动过的成员各占一段，不许只报第一个。
const three = link("vp_a", {
  vp_a: { position_ticks: 0, source_ticks: 0, duration_ticks: 0, speed_percent: 0 },
  ap_a: { position_ticks: 0, source_ticks: 0, duration_ticks: SECOND, speed_percent: 0 },
  ap_x: { position_ticks: -2 * SECOND, source_ticks: 0, duration_ticks: 0, speed_percent: 0 },
});
assert.equal(
  linkOffsetSentence(three, nameOf, say),
  "以画面 vp_a 为基准 · 声音 ap_a：比基准长 1s；声音 ap_x：开始比基准早 2s",
  "多个成员的差值要逐个点名",
);
// 只剩速度不同的那种，不能读成「什么都没动」。
const speed = link("vp_c", {
  vp_c: { position_ticks: 0, source_ticks: 0, duration_ticks: 0, speed_percent: 0 },
  ap_c: { position_ticks: 0, source_ticks: 0, duration_ticks: 0, speed_percent: 25 },
});
assert.match(linkOffsetSentence(speed, nameOf, say), /声音 ap_c：速度差 \+25%/, "速度差也要进句子");

// —— ② 视图只准走这一处，且不许自带第二套算式 ————————————————————
const view = readFileSync("desktop/src/views/Inspector.tsx", "utf8");
const store = readFileSync("desktop/src/store.ts", "utf8");
assert.match(view, /linkOffsetSentence\(link,/, "失步那句要走唯一的那个函数");
assert.doesNotMatch(view, /音画已失步：位置、源入点、时长或速度不同/, "旧的「四个轴自己找」那句不许回来");
assert.match(view, /reconcileLink\(id!\)/, "「拉回同步」按的是一条 clips.link_reconcile，不是界面拼三条修剪");
assert.match(view, /asset\?\.label \|\| clipId/, "句子里念的是素材的名字，片段 id 只是没有名字时的兜底");
assert.doesNotMatch(view, /`声音 \$\{clipId\}`/, "不许把内部片段 id 当名字念给人听");

const reconcile = store.match(/export function reconcileLink[\s\S]*?\n\}/)?.[0] ?? "";assert.ok(reconcile, "store 里要有 reconcileLink 这一个入口");
assert.match(reconcile, /op: "clips\.link_reconcile", link_id: linkId/, "交出去的就是引擎那条命令");
assert.doesNotMatch(reconcile, /position_ticks|duration_ticks/, "界面不许自己算回哪个窗口");
assert.equal(
  (store.match(/"clips\.link_reconcile"/g) ?? []).length,
  1,
  "这个 op 在渲染层只许出现一处，别处再拼一份就是第二套说法",
);

// 时基常量不许进这句话：数字只能从引擎的 differences 过来，格式化由外面注入。
const module = readFileSync("desktop/src/linkOffset.ts", "utf8");
assert.doesNotMatch(module, /70_?560_?000|TIMEBASE/, "linkOffset 不许自带第二份时基");
assert.doesNotMatch(module, /differences\[[^\]]+\]\.[a-z_]+\s*[-+*/]\s*/, "不许在引擎的数上再做算术");

// —— ③ 命令表：OPS 那份中文名要盖住引擎新加的两条 ——————————————————
assert.match(view, /"clip\.link_split_trim": "[^"]*J\/L[^"]*"/, "历史里要认得分边修剪这条，且写明是 J/L");
assert.match(view, /"clips\.link_reconcile": "拉回音画同步"/, "拉回同步在历史里的名字");

const contract = readFileSync("src/agentcut/contracts.py", "utf8");
for (const op of ["clip.link_split_trim", "clips.link_reconcile"]) {
  assert.ok(contract.includes(`"${op}"`), `契约里要有 ${op}：界面不许发一条引擎不认的命令`);
}

// —— ④ 一把抓的 J/L cut：拖一条链接的边，只有一次单边的移动才算分边修剪 ————————————
// The drag already knows the window it wants; this is the only place that reads an edge and a
// signed movement back out of it, and it refuses whenever the window is not a single-edge move.
const dragged = { position_ticks: 70, duration_ticks: 140, source_in_ticks: 200 } as unknown as Parameters<typeof linkSplitTrim>[0];
const windows: { title: string; args: [number, number, number?]; expected: SplitTrim | null }[] = [
  { title: "尾巴剪短 40", args: [200, 100], expected: { edge: "tail", delta_ticks: -40 } },
  { title: "尾巴放长 40", args: [200, 180], expected: { edge: "tail", delta_ticks: 40 } },
  { title: "片头向左让 20", args: [180, 160, 50], expected: { edge: "head", delta_ticks: -20 } },
  { title: "片头向右进 20", args: [220, 120, 90], expected: { edge: "head", delta_ticks: 20 } },
  { title: "片头动了但源没跟着走", args: [200, 160, 50], expected: null },
  { title: "两头一起动", args: [200, 180, 50], expected: null },
  { title: "一格没动", args: [200, 140], expected: null },
  { title: "只是划动源窗口", args: [220, 140], expected: null },
  { title: "源动了、时长也动了，但没说片头去哪了", args: [220, 120], expected: null },
];
for (const item of windows) {
  assert.deepEqual(linkSplitTrim(dragged, ...item.args), item.expected, `${item.title}：不是单边移动就不许叫分边修剪`);
}

const timeline = readFileSync("desktop/src/views/Timeline.tsx", "utf8");
assert.match(
  timeline,
  /trimClip\(clip\.id, final\.source_in_ticks, final\.duration_ticks, final\.position_ticks, event\.altKey, event\.shiftKey\)/,
  "Alt 这只手真的要把 bypass 交到 trimClip，否则 Help 上那行是空的",
);
assert.equal(
  (timeline.match(/Alt 只动这一边（音画链接时就是 J\/L cut）/g) ?? []).length,
  2,
  "两个边把手都要自己说得出 Alt 这一只手，不该只在快捷键页里找",
);
assert.equal((store.match(/linkSplitTrim\(/g) ?? []).length, 1, "边到命令的换算只许有一处");
assert.equal((store.match(/"clip\.link_split_trim"/g) ?? []).length, 1, "这条 op 在渲染层只许出现一处");
assert.match(store, /!ripple && bypass && clip\.link_id/, "涟漪与整对移动不许被读成分边修剪");
assert.match(store, /"分边修剪（J\/L cut）"/, "历史里念得出这一次是什么");
const help = readFileSync("desktop/src/views/Help.tsx", "utf8");
assert.match(help, /按住 Alt 直接拖链接片段的某一边/, "快捷键页说的是这一只手，不是两步的替代路径");
assert.doesNotMatch(module, /linkedSelection|bypass/, "linkOffset 只管念数，选不选联动不归它");
assert.doesNotMatch(readFileSync("desktop/src/splitTrim.ts", "utf8"), /70_?560_?000|linkedSelection/, "换算不许自带时基，也不许自己判联动");

// —— ⑤ 差值的说法不许念零：音频按采样走，比画面差半帧是真的会发生
const FPS30 = { numerator: 30, denominator: 1 } as const;
const offsets: { value: number; want: string; title: string }[] = [
  { value: 70_560_000, want: "00:00:01:00", title: "整一秒按时间码念" },
  { value: 2_275_560, want: "32.3 毫秒", title: "装机实测那一次：不足一帧" },
  { value: -2_275_560, want: "32.3 毫秒", title: "负的一样按大小念，方向由句子给" },
  { value: 1_470, want: "21 微秒", title: "一个采样也不能说成零" },
];
for (const item of offsets) {
  assert.equal(offsetWords(item.value, FPS30), item.want, `${item.title}`);
  assert.doesNotMatch(offsetWords(item.value, FPS30), /00:00:00:00/, `${item.title}：不足一帧不许念成 00:00:00:00`);
}
assert.equal(
  view.split("offsetWords(value, project.settings.frame_rate)").length - 1,
  1,
  "差值句子用的是那个永不念零的格式化",
);
assert.equal(
  view.split("timecode(value, project.settings.frame_rate)").length - 1,
  0,
  "同一句里不许留着会念零的那一个",
);

console.log(
  `PASS: 链接的差值只有一处说法（${cases.length} 个轴各一条，界面读引擎的四个数，拉回同步一条命令；` +
    `单边移动 ${windows.length} 种窗口各判各的，Alt 那只手交的是 bypass）`,
);
