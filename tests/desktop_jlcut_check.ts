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

console.log(
  `PASS: 链接的差值只有一处说法（${cases.length} 个轴各一条，界面读引擎的四个数，拉回同步一条命令）`,
);
