/** 一次遮罩跟踪量几帧：上限必须是引擎的数，判断只能有一处。

 1.87 之前界面自己写了一个 300：十二秒的片段只量前十秒，提示却说「导出使用同一份关键帧」。这一版把
 这件事交给 `trackWindow`，上下限从 `capabilities.limits` 传进来。所以门禁不能只测「跑通了」，要测
 它真的听传入的数：换一组上下限，帧数与灰掉的理由都得跟着变——否则就是把另一个数写死在了这里。
 片段自己的曲线预算不在这里算：那是引擎的账，由回复里的 `budget_frames` 说清。
 */

import assert from "node:assert/strict";

import { trackWindow } from "../desktop/src/effects";

// 引擎给的数：短片段整条量完，量不上一帧都不能开跑。
const limits = { track_min_frames: 2, track_max_frames: 900 };

const short = trackWindow(360, false, limits);
assert.equal(short.frames, 360, "a clip inside the ceiling must be measured to its end");
assert.equal(short.blocked, null, short.blocked);

const long = trackWindow(1800, false, limits);
assert.equal(long.frames, 900, "one run stops at the engine's ceiling");
assert.equal(long.blocked, null, long.blocked);

// 播放头快到底：这一次开不了跑，理由要说得出怎么办。
const tail = trackWindow(1, false, limits);
assert.ok(tail.blocked, "a window shorter than the minimum must not start a run");
assert.match(tail.blocked!, /[一-鿿]/, "the reason must be Chinese");
assert.ok(tail.blocked!.includes("把播放头往前挪"), `the reason must name the exit: ${tail.blocked}`);
assert.ok(tail.blocked!.includes("1 帧"), `the reason must say what is left: ${tail.blocked}`);

// 从头重跟时挪播放头没有用，出路得换一条。
const head = trackWindow(1, true, limits);
assert.ok(head.blocked?.includes("关键帧"), `the exit must be one that works from the head: ${head.blocked}`);
assert.ok(!head.blocked!.includes("把播放头往前挪"), `the head must not be told to move the playhead: ${head.blocked}`);

// 数不是这里的：换一组上下限，帧数和灰掉的理由都跟着换。
const other = trackWindow(50, false, { track_min_frames: 8, track_max_frames: 30 });
assert.equal(other.frames, 30, "the ceiling comes from the caller, not from a literal");
assert.equal(trackWindow(7, false, { track_min_frames: 8, track_max_frames: 30 }).blocked !== null, true);
assert.equal(trackWindow(8, false, { track_min_frames: 8, track_max_frames: 30 }).blocked, null);

// 老引擎没给这两个数：兜底是契约的那一对，且不许界面自己数一个更小的。
assert.equal(trackWindow(4000, false, undefined).frames, 900, "the fallback is the contract ceiling");
assert.notEqual(trackWindow(1, true, undefined).blocked, null, "two frames is the contract floor");

console.log(
  "PASS: 跟踪窗口听引擎的数——整条量到结尾、超过上限就停在上限、窗口太短就灰掉并说清出路，"
    + "换一组上下限帧数与理由都跟着变",
);
