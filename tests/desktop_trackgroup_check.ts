/** 一组遮罩跟踪：段数上限、每段的窗口、以及「量不动」那句理由，都必须只有一处判断。

 1.157 把「跟踪所选」交给 `trackGroup`。它不许自己数帧——每段仍然问一次 `trackWindow`，所以上下文
 里换一组上下限，帧数与理由都要跟着变；也不许把超上限的选择偷偷截断，那会让人以为剩下那几段也跟过
 了。这一档把这两件事各钉一次。
 */

import assert from "node:assert/strict";

import { trackGroup, trackWindow } from "../desktop/src/effects";

const limits = { track_min_frames: 2, track_max_frames: 900, track_max_targets: 8 };
const knobs = { reacquire: false, maxGapFrames: 25, scale: false };
const many = (count: number, frames = 300) =>
  Array.from({ length: count }, (_, index) => ({ id: `c${index}`, duration_ticks: frames }));

// 一整组各自量到自己的结尾，旋钮每段都带着：一次点击发的是一份请求。
const eight = trackGroup(many(8), 1, limits, knobs);
assert.equal(eight.blocked, null, `eight targets must fit: ${eight.blocked}`);
assert.equal(eight.targets.length, 8, "one entry per selected clip, none merged away");
assert.deepEqual(
  eight.targets.map((target) => target.frames),
  many(8).map(() => 300),
  "每段各按自己的长度量，不是一条统一帧数",
);
assert.ok(
  eight.targets.every(
    (target) => target.fromTicks === 0 && target.merge && target.reacquire === false
    && target.maxGapFrames === 25 && target.scale === false,
  ),
  "每一段都要带上播放头的起点与三个旋钮",
);

// 段数超上限：点名要少选，而不是截断到八段。
const nine = trackGroup(many(9), 1, limits);
assert.ok(nine.blocked, "九段必须被点名拒绝，而不是偷偷只跟八段");
assert.equal(nine.targets.length, 0, "被拒绝的一组不许留下一半目标");
assert.ok(nine.blocked!.includes("8 段"), `上限要念出来：${nine.blocked}`);
assert.ok(nine.blocked!.includes("引擎"), `要说清那是引擎的数：${nine.blocked}`);
assert.ok(nine.blocked!.includes("少选"), `要给一条真正走得通的出路：${nine.blocked}`);

// 换一组上限，判断跟着走：这里没有第二个写死的数。
const narrow = trackGroup(many(3), 1, { ...limits, track_max_targets: 2 });
assert.ok(narrow.blocked?.includes("2 段"), `上限换了理由也要换：${narrow.blocked}`);

// 某一段太短：说的是 `trackWindow` 那句话，只是加上了是第几段。
const short = trackGroup([{ id: "tiny", duration_ticks: 1 }, ...many(2)], 1, limits);
assert.ok(short.blocked, "太短的一段不能让整组照跑");
assert.equal(short.targets.length, 0, "一组要么全排好，要么一个都不发");
assert.equal(
  short.blocked,
  `第 1 段量不动：${trackWindow(1, true, limits).blocked}`,
  "分组不许另写一套「为什么量不动」的说法",
);

// 上限缺失时的兜底只能是契约那个数，且不许在这里变成一个更小的数。
assert.equal(
  trackGroup(many(8), 1, undefined).blocked,
  null,
  "没有 capabilities 时兜底要撑到契约的段数上限",
);
assert.notEqual(
  trackGroup(many(9), 1, undefined).blocked,
  null,
  "兜底也不是把超额的选择咽下来",
);
assert.equal(
  trackGroup([{ id: "long", duration_ticks: 4000 }], 1, limits).targets[0].frames,
  900,
  "一段的长度超过单次帧上限时，仍由 trackWindow 收在上限",
);

console.log(
  "PASS: 分组跟踪只有一处判断——每段各按自己的长度量、旋钮全带上、超段数上限点名要少选而不是截断、"
    + "太短那段沿用 trackWindow 那句话，换一组上下限理由跟着变",
);
