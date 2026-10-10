/** 1.107：检查器那一行额度读数，必须是引擎算好的那份回执，不许渲染层自己除一遍。
 *
 * 额度（1.104）与它的可读回执（1.105）都在引擎里；这一版把数搬到界面上。风险很具体：
 * 界面若写成 `${room // cube_samples}`，那么哪天引擎改了「一张满格立方算多少采样点」，
 * 界面还按旧的除数说话——显示的「还放得下 N 张」与真的会放得下几张就对不上了。
 * 所以这里断的是：句子里的数逐字来自回执的字段，且给一张**故意不自洽**的回执时，
 * 说的仍是引擎给的 `room_cubes`，不是界面除出来的那个。
 */

import assert from "node:assert/strict";

import { gradeCapacityLine } from "../desktop/src/effects";
import type { GradeCapacity } from "../desktop/src/engine";

const base: GradeCapacity = {
  samples: 191607, limit: 200000, room: 8393, room_cubes: 0, room_tables: 2,
  cube_samples: 14739, table_samples: 3072, clips_with_tables: 13,
  worst_clip_id: "c3", worst_clip_samples: 14739,
  by_clip: Object.fromEntries(Array.from({ length: 13 }, (_, i) => [`c${i}`, 14739])),
  by_clip_samples: 191607, other_clips: 0, nested_samples: 0,
};

// 没有回执、或回执不是当前这份工程的：一个字都不许写。
assert.equal(gradeCapacityLine(null, 7), null, "还没问到引擎就不该有这一行");
assert.equal(gradeCapacityLine({ value: base, revision: 6 }, 7), null, "revision 对不上就是另一份工程");
assert.equal(gradeCapacityLine({ value: base, revision: 7 }, undefined), null, "工程还没加载完");

const line = gradeCapacityLine({ value: base, revision: 7 }, 7);
assert.ok(line, "对得上 revision 就该有这一行");
assert.ok(line!.includes("191607 / 200000"), line);
assert.ok(line!.includes("还放得下 0 张满格 3D 立方"), line);
assert.ok(line!.includes("或 2 张满格 1D 表"), line);
assert.ok(line!.includes("14739") && line!.includes("3072"), "每张表多大也得是引擎给的字");
// 13 条都列出来了，就不该出现「另有 N 条未列」。
assert.ok(!line!.includes("未列"), line);

// 关键的一条：给一张不自洽的回执（room 明明还够除出一张立方，room_cubes 却写着 0）。
// 界面如果自己除，就会说「还放得下 1 张」——那句是界面编的，不是引擎说的。
const skewed: GradeCapacity = { ...base, room: 99999, room_cubes: 0, room_tables: 0 };
const said = gradeCapacityLine({ value: skewed, revision: 7 }, 7)!;
assert.ok(said.includes("还放得下 0 张满格 3D 立方"), said);
assert.ok(said.includes("或 0 张满格 1D 表"), said);
assert.ok(!said.includes("1 张满格"), "界面自己除了 room——它该说的是引擎给的 room_cubes");

// 明细被引擎截断成前 20 名时，那一行要说清还有几条没列。
const many: GradeCapacity = {
  ...base,
  clips_with_tables: 25,
  by_clip: Object.fromEntries(Array.from({ length: 20 }, (_, i) => [`c${i}`, 3072])),
  by_clip_samples: 25 * 3072, other_clips: 5, samples: 25 * 3072, room: 200000 - 25 * 3072,
};
const detailed = gradeCapacityLine({ value: many, revision: 7 }, 7)!;
assert.ok(detailed.includes("明细列前 20 条") && detailed.includes("另有 5 条未列"), detailed);

// 空工程：说的是额度本身，不是「已用 0」。
const zero: GradeCapacity = { ...base, samples: 0, room: 200000, room_cubes: 13, room_tables: 65, clips_with_tables: 0, by_clip: {}, by_clip_samples: 0, other_clips: 0, worst_clip_id: null, worst_clip_samples: 0 };
const first = gradeCapacityLine({ value: zero, revision: 7 }, 7)!;
assert.ok(first.startsWith("本工程的查找表额度是 200000 个采样点"), first);
assert.ok(first.includes("还放得下 13 张满格 3D 立方") && first.includes("或 65 张满格 1D 表"), first);
assert.ok(!first.includes("未列"), first);

console.log("PASS: 检查器那行额度只念引擎给的字——不自洽的回执也照念，说明渲染层没有第二套除法");
