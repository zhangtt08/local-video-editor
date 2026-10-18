/** 1.107：检查器那一行额度读数，必须是引擎算好的那份回执，不许渲染层自己除一遍。
 *
 * 额度（1.104）与它的可读回执（1.105）都在引擎里；这一版把数搬到界面上。风险很具体：
 * 界面若写成 `${room // cube_samples}`，那么哪天引擎改了「一张满格立方算多少采样点」，
 * 界面还按旧的除数说话——显示的「还放得下 N 张」与真的会放得下几张就对不上了。
 * 所以这里断的是：句子里的数逐字来自回执的字段，且给一张**故意不自洽**的回执时，
 * 说的仍是引擎给的 `room_cubes`，不是界面除出来的那个。
 *
 * 1.210 加的第二把尺：那一行分成「眼前那句」（`line`，只说还放得下几张）与「悬停那句」
 * （`detail`，已用多少、每张要多少、明细列了几条）。这一句原来画到四行——数字在眼前排队，
 * 而人在这格要判的只有一件事：还放不放得下。两边各钉各的，谁把数搬回眼前都会红。
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { gradeCapacity } from "../desktop/src/effects";
import type { GradeCapacity } from "../desktop/src/engine";

// `REPO_ROOT` is defined by tests/desktop_ts_check.py at bundle time.
declare const REPO_ROOT: string;

const base: GradeCapacity = {
  samples: 191607, limit: 200000, room: 8393, room_cubes: 0, room_tables: 2,
  cube_samples: 14739, table_samples: 3072, clips_with_tables: 13,
  worst_clip_id: "c3", worst_clip_samples: 14739,
  by_clip: Object.fromEntries(Array.from({ length: 13 }, (_, i) => [`c${i}`, 14739])),
  by_clip_samples: 191607, other_clips: 0, nested_samples: 0,
};

// 没有回执、或回执不是当前这份工程的：一个字都不许写。
assert.equal(gradeCapacity(null, 7), null, "还没问到引擎就不该有这一行");
assert.equal(gradeCapacity({ value: base, revision: 6 }, 7), null, "revision 对不上就是另一份工程");
assert.equal(gradeCapacity({ value: base, revision: 7 }, undefined), null, "工程还没加载完");

const read = gradeCapacity({ value: base, revision: 7 }, 7);
assert.ok(read, "对得上 revision 就该有这一行");
const cjk = (text: string) => (text.match(/[一-鿿]/g) ?? []).length;
assert.ok(read!.line.includes("还放得下 0 张满格 3D 立方"), read!.line);
assert.ok(read!.line.includes("、2 张满格 1D 表"), read!.line);
assert.ok(cjk(read!.line) <= 24, `眼前那一行 ${cjk(read!.line)} 字，画得下两行吗：${read!.line}`);
// 已用多少是来历：它在这一格的 title 上，不在那一行里。
assert.ok(!read!.line.includes("191607"), `已用的数又被搬回眼前了：${read!.line}`);
assert.ok(read!.detail.includes("191607 / 200000"), read!.detail);
assert.ok(read!.detail.includes("14739") && read!.detail.includes("3072"), "每张表多大也得是引擎给的字");
assert.ok(read!.detail.includes("0 张立方或 2 张 1D 表"), `来历那句也要说同一份数：${read!.detail}`);
// 13 条都列出来了，就不该出现「另有 N 条未列」。
assert.ok(!read!.line.includes("未列") && !read!.detail.includes("未列"), read!.detail);

// 关键的一条：给一张不自洽的回执（room 明明还够除出一张立方，room_cubes 却写着 0）。
// 界面如果自己除，就会说「还放得下 1 张」——那句是界面编的，不是引擎说的。
const skewed: GradeCapacity = { ...base, room: 99999, room_cubes: 0, room_tables: 0 };
const said = gradeCapacity({ value: skewed, revision: 7 }, 7)!;
assert.ok(said.line.includes("还放得下 0 张满格 3D 立方"), said.line);
assert.ok(said.line.includes("、0 张满格 1D 表"), said.line);
assert.ok(!said.line.includes("1 张满格"), "界面自己除了 room——它该说的是引擎给的 room_cubes");
assert.ok(said.detail.includes("0 张立方或 0 张 1D 表"), said.detail);

// 明细被引擎截断成前 20 名时，来历那句要说清还有几条没列；眼前那一行不许跟着变长。
const many: GradeCapacity = {
  ...base,
  clips_with_tables: 25,
  by_clip: Object.fromEntries(Array.from({ length: 20 }, (_, i) => [`c${i}`, 3072])),
  by_clip_samples: 25 * 3072, other_clips: 5, samples: 25 * 3072, room: 200000 - 25 * 3072,
};
const detailed = gradeCapacity({ value: many, revision: 7 }, 7)!;
assert.ok(detailed.detail.includes("明细列前 20 条") && detailed.detail.includes("另有 5 条未列"), detailed.detail);
assert.ok(!detailed.line.includes("未列"), `眼前那一行不该跟着念明细：${detailed.line}`);
assert.ok(cjk(detailed.line) <= 24, `${detailed.line}`);

// 空工程：说的是额度本身，不是「已用 0」。
const zero: GradeCapacity = { ...base, samples: 0, room: 200000, room_cubes: 13, room_tables: 65, clips_with_tables: 0, by_clip: {}, by_clip_samples: 0, other_clips: 0, worst_clip_id: null, worst_clip_samples: 0 };
const first = gradeCapacity({ value: zero, revision: 7 }, 7)!;
assert.ok(first.detail.startsWith("本工程的查找表额度是 200000 个采样点，还没用过"), first.detail);
assert.ok(first.line.includes("还放得下 13 张满格 3D 立方") && first.line.includes("、65 张满格 1D 表"), first.line);
assert.ok(!first.detail.includes("未列"), first.detail);

// 接线：两句各去各的地方——眼前那一行念 line，title 挂 detail。
const grade = readFileSync(REPO_ROOT + "desktop/src/views/GradeFields.tsx", "utf8");
assert.ok(grade.includes("<p className=\"hint\" title={capacityRead.detail}>{capacityRead.line}</p>"), "额度那一行：眼前念 line、来历挂 title——两处都得接上");
assert.equal(grade.split("gradeCapacity(").length - 1, 1, "这一格只在一处把回执念成话");

console.log(
  "PASS: 检查器那行额度只念引擎给的字——不自洽的回执也照念，说明渲染层没有第二套除法；"
    + "1.210 起那句分成眼前（还放得下几张，" + cjk(read.line) + " 字）与悬停（已用多少、每张多少、明细几条），两边各钉各的"
);
