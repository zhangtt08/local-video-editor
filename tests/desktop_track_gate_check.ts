/** 整轨的分析按钮对空轨必须是灰的：1.79 起引擎会点名「这条轨上没有片段」，按下去只会弹错。

 The predicate below is the one `Timeline.tsx` calls for 整轨响度 / 整轨去空白 / 自动闪避, so the
 grey-out and the tooltip cannot drift from each other. The differential case is a track whose
 clips all live on another id -- exactly what `sequence.nest` leaves behind on the root -- which must
 still be blocked, and the reason has to name a way out that actually works.
 */

import assert from "node:assert/strict";

import { EMPTY_TRACK_HINT, trackToolBlocker } from "../desktop/src/effects";
import type { Clip } from "../desktop/src/engine";

const clip = (over: Partial<Clip>): Clip =>
  ({ id: "c", track_id: "a", ...over } as unknown as Clip);

assert.equal(
  trackToolBlocker("a", []),
  EMPTY_TRACK_HINT,
  "a track with nothing on it must not offer the whole-track tools",
);
assert.equal(
  trackToolBlocker("a", [clip({ id: "c1", track_id: "a" })]),
  null,
  "one clip is enough to make the button live again",
);
assert.equal(
  trackToolBlocker("a", [clip({ id: "c1", track_id: "b" })]),
  EMPTY_TRACK_HINT,
  "clips on another track do not count -- after nesting, the root's same-named track is empty",
);
assert.equal(
  trackToolBlocker("a", [clip({ id: "c1", track_id: "a" }), clip({ id: "c2", track_id: "b" })]),
  null,
  "a single clip on this track must not be outvoted by clips elsewhere",
);

assert.ok(/[一-鿿]/.test(EMPTY_TRACK_HINT), `the reason must be Chinese: ${EMPTY_TRACK_HINT}`);
assert.ok(
  EMPTY_TRACK_HINT.includes("拖上时间线"),
  `the reason must name the way in: ${EMPTY_TRACK_HINT}`,
);
assert.ok(
  EMPTY_TRACK_HINT.includes("面包屑"),
  `the reason must name the way into the comp: ${EMPTY_TRACK_HINT}`,
);

console.log(
  "PASS: 整轨响度 / 整轨去空白 / 自动闪避 grey out on an empty track, the reason names both exits, "
    + "and clips elsewhere do not re-enable them",
);
