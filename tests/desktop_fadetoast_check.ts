/** 整轨搬完之后那句中文报告（1.97）。文案是界面自己写的，但**原因必须来自引擎那句原话的翻译表**。
 *
 * `tests/fadebatch_check.py` 已经把「引擎能说出的每一句搬不动」与 `FADE_ADOPT_REASONS` 的键对上了；
 * 这条门禁管的是另一半：读数取自规划而不是界面自己数的，一条都不许多、也不许漏，
 * 未知原因不许把提示写成空串（空串的报告等于没报告）。
 */

import assert from "node:assert/strict";

import { FADE_ADOPT_REASONS, fadeAdoptSummary } from "../desktop/src/effects";

const entry = (clip_id: string, skipped?: string) => ({ clip_id, property: "opacity", skipped });

// 什么都没得搬、也没东西被挡住：说的是「淡都已经在边上了」，不是失败。
const clean = fadeAdoptSummary({ adopted: 0, skipped: 0, clips: [] });
assert.equal(clean.title, "这条轨没有写成关键帧的淡");
assert.match(clean.detail, /已经在自己的两条边上/);

// 搬完了：标题报的是规划给的段数，正文明确「画面不变」——这是这条命令的全部承诺。
const moved = fadeAdoptSummary({ adopted: 3, skipped: 0, clips: [entry("w"), entry("x")] });
assert.equal(moved.title, "搬了 3 段淡");
assert.match(moved.detail, /画面一个像素都不变/);

// 搬了一部分：挡住的那几条要点名，原因得是中文（表里的说法），不是引擎的英文原句。
const mixed = fadeAdoptSummary({
  adopted: 2,
  skipped: 1,
  clips: [entry("w"), entry("bad", "other keyframes are mixed into the fade")],
});
assert.equal(mixed.title, "搬了 2 段淡");
assert.match(mixed.detail, /另有 1 段搬不动：淡里夹着别的关键帧/, mixed.detail);

// 一段都搬不动：报告列前三个 clip_id 与其各自的原因，剩下的只报个数——不是整屏日志。
const blocked = fadeAdoptSummary({
  adopted: 0,
  skipped: 5,
  clips: [
    entry("c1", "the ramp is not the eased shape a fade used"),
    entry("c2", "some keyframes sit outside the clip"),
    entry("c3", "neither ramp starts at an edge of the clip"),
    entry("c4", "this property already carries edge windows"),
    entry("c5", "audio has no opacity to fade"),
  ],
});
assert.equal(blocked.title, "这条轨没有能搬的淡");
assert.match(blocked.detail, /5 段有淡但搬不动/, blocked.detail);
for (const name of ["c1", "c2", "c3"]) assert.match(blocked.detail, new RegExp(name), blocked.detail);
assert.ok(!blocked.detail.includes("c4"), "第四个不该被列出来，只进「还有几段」的数");
assert.match(blocked.detail, /还有 2 段/, blocked.detail);
assert.match(blocked.detail, /斜坡不是老淡那种缓动形状/, blocked.detail);
assert.match(blocked.detail, /有关键帧落在片段范围之外/, blocked.detail);
assert.match(blocked.detail, /两头都没从片段的边上出发/, blocked.detail);

// 引擎将来加一句而表里没配：不许印成空串，也不许把英文原句悄悄丢掉——写一句「引擎没说原因」。
const unknown = fadeAdoptSummary({ adopted: 1, skipped: 1, clips: [entry("q", "a brand new refusal")] });
assert.ok(unknown.detail.includes("a brand new refusal"), unknown.detail);
assert.ok(!unknown.detail.includes("：。"), "原因不许是空的");

// 表本身：每条中文说法都得是非空字符串，键不能重复到丢一条。
const labels = Object.values(FADE_ADOPT_REASONS);
assert.ok(labels.length >= 10, `表至少该有十条，现在 ${labels.length}`);
assert.ok(labels.every((text) => typeof text === "string" && text.length > 0), "中文说法不许为空");
assert.ok(labels.every((text) => !/[a-z]{4,}/.test(text)), `不该把英文原句当翻译：${labels.join("|")}`);

console.log(
  "PASS: 整轨报告读的是规划的数、原因走中文表、未知原因不留空串，表里每条说法都非空且不是英文"
);
