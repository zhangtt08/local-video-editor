/** 1.163「粘贴属性」界面这一侧：名单、数、句子都只许从引擎那一份出去。

 这一档要挡的三种错，跟 1.158、1.161 撞过的是同三种：
 ① 界面自己抄一份类别名单或中文名（抄的那一份迟早和引擎不一样，红的是话，不是画面）；
 ② 界面在引擎的数上再做一遍算术（「还能粘几段」「差几枚针」这种话一旦自己算，就和回执可能不同）；
 ③ 一句拒绝有两个说法（对话框预览里念的与粘完那支提示里念的必须是同一句）。
 所以这里既量纯函数的行为，也读源码数那一处调用。
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  copyBlocker,
  defaultTicked,
  dialogRows,
  pasteBlocker,
  pasteSaid,
  pasteTargets,
  refusalLines,
} from "../desktop/src/attributePaste";
import type { AttributeCategory, AttributeCategoryReport, AttributePlan } from "../desktop/src/engine";
import { errorHint } from "../desktop/src/engine";
import { humanDuration } from "../desktop/src/time";

declare const REPO_ROOT: string;

const categories: AttributeCategory[] = [
  { id: "color", label: "甲类", note: "甲类搬的是这一份" },
  { id: "effects", label: "乙类", note: "乙类搬的是那一份" },
  { id: "fade", label: "丙类", note: "丙类搬的是两头" },
  { id: "speed", label: "丁类", note: "丁类搬的是速率" },
];

const report: AttributeCategoryReport[] = [
  { category: "color", label: "甲类", note: "甲类搬的是这一份", has_content: true, nodes: 3, adjusted: 1 },
  { category: "effects", label: "乙类", note: "乙类搬的是那一份", has_content: false, fields: [] },
  {
    category: "fade",
    label: "丙类",
    note: "丙类搬的是两头",
    has_content: true,
    windows: [[70_560_000, 0], [0, 141_120_000]],
  },
  { category: "speed", label: "丁类", note: "丁类搬的是速率", has_content: true, speed_percent: 150, curve_points: 0 },
];

const rows = dialogRows(categories, report);

assert.equal(rows.length, categories.length, "对话框排的行数不是能力表那份名单的行数");
assert.deepEqual(
  rows.map((row) => row.id),
  categories.map((row) => row.id),
  "行的顺序被界面重排了：人看到的顺序与引擎下发的顺序不该不同",
);
assert.equal(rows[0].label, "甲类", "中文名不是引擎念的那一个");
assert.equal(rows[1].hasContent, false, "回执说没东西，界面却把它当有");
assert.deepEqual(defaultTicked(rows), ["color", "fade", "speed"], "默认勾的不是「有内容的那些类」");

// 数只念一遍：句子里出现的必须是回执那几个数，而不是界面自己算出来的别的数。
assert.ok(rows[0].count.includes("3"), `甲类那句没念出 nodes=3：${rows[0].count}`);
const fadeSaid = rows[2].count;
assert.ok(
  fadeSaid.includes(`${humanDuration(70_560_000)}→${humanDuration(0)}`) &&
    fadeSaid.includes(`${humanDuration(0)}→${humanDuration(141_120_000)}`),
  `丙类那句不是把回执那两个 tick 念出来的：${fadeSaid}`,
);
assert.ok(rows[3].count.includes("150%"), `丁类那句没念出速率：${rows[3].count}`);

// 老引擎不回回执（或某一类没回）时，界面不许自己补一个「有内容」。
const blind = dialogRows(categories, undefined);
assert.deepEqual(
  blind.map((row) => row.hasContent),
  [false, false, false, false],
  "没有回执时界面自己猜了勾选状态",
);
assert.deepEqual(dialogRows(undefined, report), [], "能力表没有这张名单时不该排出任何一行");

assert.deepEqual(pasteTargets("src", ["a", "src", "b", "a"]), ["a", "b"], "目标里留着来源或重复的那一段");

const open = { id: "p1", revision: 3 };
assert.ok(copyBlocker(null, ["a"], { attribute_paste: true }), "没打开工程时那颗按钮该灰");
assert.ok(copyBlocker(open, [], { attribute_paste: true }), "没选中片段时该灰并说出怎么办");
assert.ok(copyBlocker(open, ["a", "b"], { attribute_paste: true }), "多选时「复制属性」该灰并说出出路");
assert.equal(copyBlocker(open, ["a"], { attribute_paste: true }), null, "一段主选中该能复制");
assert.ok(
  String(copyBlocker(open, ["a"], {})).includes("这一版引擎"),
  "老引擎没这一档时那句出路没念出来",
);

const stored = { projectId: "p1", clipId: "src" };
assert.ok(pasteBlocker(null, open, ["a"], { attribute_paste: true }), "没复制过时那颗按钮该灰");
assert.ok(
  pasteBlocker({ projectId: "other", clipId: "src" }, open, ["a"], { attribute_paste: true }),
  "复制来自别的工程时该灰并点名回哪儿",
);
assert.ok(pasteBlocker(stored, open, [], { attribute_paste: true }), "没有目标时该灰并说清怎么挑目标");
assert.equal(pasteBlocker(stored, open, ["a", "b"], { attribute_paste: true }), null, "该能粘的时候是灰的");

const plan: AttributePlan = {
  source_clip_id: "src",
  sequence_id: null,
  categories: [],
  all_categories: report,
  requested: 3,
  targets: 2,
  commands: [{ op: "clip.color", clip_id: "a", color: {} }],
  written: [{ clip_id: "a", categories: ["color", "speed"] }],
  unchanged: ["b"],
  refusals: [
    { clip_id: "c", category: "fade", code: "INVALID_MASK", message: "masks require a picture track", details: {} },
  ],
  beyond_tail_keyframes: 2,
  dropped_extra_keys: 3,
  target_limit: 64,
  command_limit: 2500,
};

// 同一句拒绝只有一个说法：对话框预览与粘完那支提示共用 refusalLines。
const line = refusalLines(plan)[0];
assert.ok(line.includes("遮罩"), `那句拒绝没念中文：${line}`);
assert.ok(line.includes("丙类"), `那句没念引擎给的中文名，而是念了契约 id：${line}`);
assert.ok(!line.includes("「fade」"), `契约 id 当用户界面用了：${line}`);
assert.ok(line.includes(errorHint("INVALID_MASK")), `引擎只说英文时那句仍是提示表里那一条：${line}`);
// 1.266：引擎自己说中文（带着那两个数）时，这一行不许再让通用提示顶掉它——
// 这正是本轮修掉的那一手，判据住在这个表面（粘贴那几行）上。
const chinese = {
  ...plan,
  refusals: [
    {
      clip_id: "c", category: "fade", code: "MASK_SHAPE_LIMIT",
      message: "this mask already carries 32 outlines",
      details: { clip_id: "c", outlines: 32, limit: 32 },
    },
  ],
};
const woven = refusalLines(chinese)[0];
assert.ok(woven.includes("轮廓帧：最多 32，现在 32"), `上限那一对数没到粘贴那几行眼前：${woven}`);
assert.ok(
  pasteSaid(plan, 3).detail.includes(line),
  "提示里那句与预览里那句不是同一句（一句拒绝有了两个说法）",
);
assert.ok(pasteSaid(plan, 3).title.includes("1 段（选了 3 段）"), "标题里的段数不是回执里那两个数");
assert.ok(pasteSaid(plan, 3).detail.includes("1 段本来就是这份数"), "「已经一样」那段没被如实报出");
assert.ok(pasteSaid(plan, 3).detail.includes("2 枚针"), "落在段尾之外的针数没照实报");
// 1.244：框点与曲线针不是一回事——越尾的框点没有搬过来，句子要这么说，不能套用「仍在工程里」。
assert.ok(pasteSaid(plan, 3).detail.includes("3 枚再叠遮罩的框点"), "没搬过来的框点数没照实报");
assert.ok(pasteSaid(plan, 3).detail.includes("框点不能停在段尾之后"), "没搬框点的原因没说出来");
assert.ok(
  !pasteSaid({ ...plan, dropped_extra_keys: 0 }, 3).detail.includes("再叠遮罩的框点"),
  "一枚框点都没丢时也说了一句丢框点",
);
assert.ok(
  pasteSaid({ ...plan, written: [], unchanged: ["a", "b", "c"], refusals: [] }, 3).title.includes("已经和来源一样"),
  "什么都没写时标题不该说成已粘贴",
);
assert.ok(
  pasteSaid({ ...plan, written: [], unchanged: [], refusals: [plan.refusals[0]] }, 1).title.includes("没能粘进任何一类"),
  "一段都没接住时该点名，而不是说成功",
);

// 认不得的码不许静静落回英文：没有中文那句时退回引擎原话。
assert.ok(
  refusalLines({
    ...plan,
    refusals: [{ ...plan.refusals[0], code: "SOMETHING_NEW", message: "raw engine sentence" }],
  })[0].includes("raw engine sentence"),
  "没有中文提示时该照原样念引擎那句，而不是空白",
);

// ——以下是接线：同一件事只许有一处实现——
const store = readFileSync(REPO_ROOT + "desktop/src/store.ts", "utf8");
const view = readFileSync(REPO_ROOT + "desktop/src/views/AttributeDialog.tsx", "utf8");
const toolbar = readFileSync(REPO_ROOT + "desktop/src/views/Timeline.tsx", "utf8");
const client = readFileSync(REPO_ROOT + "desktop/src/engine.ts", "utf8");
const sheet = readFileSync(REPO_ROOT + "desktop/src/styles.css", "utf8");
const help = readFileSync(REPO_ROOT + "desktop/src/views/Help.tsx", "utf8");
const contracts = readFileSync(REPO_ROOT + "src/agentcut/contracts.py", "utf8");

assert.equal(
  (store.match(/engine\.attributePlan\(/g) ?? []).length,
  2,
  "规划只有两处调用：打开对话框前一次、粘的时候一次；多一处就是第二套算法",
);
assert.equal((client.match(/attribute-plan/g) ?? []).length, 1, "那条路由的拼法在渲染层只许出现一次");
assert.ok(view.includes("askAttributeRows"), "对话框没向引擎要那份回执");
assert.ok(!/categories\s*=\s*\[/.test(view), "对话框自己列了一份类别名单");
assert.ok(!/["']（调色链|效果与变换）["']/.test(view), "视图里抄了引擎的中文名");
for (const row of categories) {
  assert.ok(!view.includes(row.note), `视图里抄了那句「${row.note}」`);
}

// 引擎那张表里的中文名，一个都不许出现在渲染层（那是「界面自抄名单」那一类错的形状）。
const from = contracts.indexOf("ATTRIBUTE_CATEGORIES");
const until = contracts.indexOf("ATTRIBUTE_PASTE_TARGET_LIMIT");
assert.ok(from >= 0 && until > from, "契约里那张类别表找不到了：这张门禁的对照对象没了");
const table = contracts.slice(from, until);
for (const [, label] of table.matchAll(/"label": "([^"]+)"/g)) {
  for (const [where, text] of [
    ["store.ts", store],
    ["AttributeDialog.tsx", view],
    ["Timeline.tsx", toolbar],
    ["attributePaste.ts", readFileSync(REPO_ROOT + "desktop/src/attributePaste.ts", "utf8")],
  ] as const) {
    assert.ok(!text.includes(`"${label}"`), `${where} 里出现了引擎那张表的中文名「${label}」`);
  }
}

assert.ok(toolbar.includes("复制属性") && toolbar.includes("粘贴属性"), "工具条上那两只手不在");
assert.ok(
  toolbar.includes("disabled={Boolean(attributeStop)}") && toolbar.includes("disabled={Boolean(attributePasteStop)}"),
  "两颗按钮没挂在那一处唯一的判断上",
);
assert.ok(toolbar.includes("attributeSourceCopy()"), "工具条读的来源不是 store 那一份");
assert.ok(sheet.includes(".attribute-row {"), "对话框那一排的样式规则不存在（画不出就等于没有）");
assert.ok(sheet.includes(".attribute-refusals {"), "拒绝那几行的样式规则不存在（那几行画不出来就是没说）");
assert.ok(help.includes("时间线·粘贴属性"), "帮助页没念这一格");
assert.ok(help.includes("attribute-plan"), "帮助页没把 Agent 那条路指出来");

console.log(
  `PASS 粘贴属性界面：${rows.length} 行按能力表排、默认勾 ${defaultTicked(rows).length} 类；` +
    `拒绝句 ${line.slice(0, 18)}… 与提示同一句`,
);
