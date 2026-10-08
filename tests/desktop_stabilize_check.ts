/** The 画面稳定 button must refuse for the same reasons the engine refuses, and say what to do.

 A press that the engine would answer with `STABILIZE_CONFLICT` is a wasted round trip that reads the
 whole clip through FFmpeg; the Inspector therefore greys the button out with the reason in its title.
 Both halves are pinned here without a browser: the predicate is the one the Inspector calls, and the
 differential case is a mask curve, which the stabiliser never writes and so must not block.
 */

import assert from "node:assert/strict";

import { stabilizeBlocked } from "../desktop/src/effects";
import type { Clip } from "../desktop/src/engine";

const clip = (over: Partial<Clip>): Clip =>
  ({ id: "c", track_id: "v", asset_id: "a", speed_percent: 100, ...over } as unknown as Clip);

const plain = stabilizeBlocked(clip({}));
assert.equal(plain, null, `a clean clip at 100% must be stabilisable, got: ${plain}`);

const ramp = stabilizeBlocked(clip({ speed_curve: [{ at_ticks: 0, speed_percent: 100 }] }));
assert.ok(ramp?.includes("100%"), `a speed curve must be refused with its exit, got: ${ramp}`);
const fast = stabilizeBlocked(clip({ speed_percent: 200 }));
assert.equal(fast, ramp, "a respeeded clip and a ramped clip are refused for the same reason");

const scaled = stabilizeBlocked(clip({ keyframes: [{ property: "scale", at_ticks: 0, value: 1 }] }));
assert.ok(scaled?.includes("缩放"), `the refusal must name the curve it would reuse, got: ${scaled}`);
assert.ok(scaled?.includes("撤销"), `the refusal must name an exit that works, got: ${scaled}`);

const moved = stabilizeBlocked(clip({
  keyframes: [
    { property: "x", at_ticks: 0, value: 0.1 },
    { property: "rotation", at_ticks: 0, value: 0 },
    { property: "mask_x", at_ticks: 0, value: 0.5 },
  ],
}));
assert.ok(moved?.includes("位置 X") && moved.includes("旋转"), `got: ${moved}`);
assert.ok(!moved.includes("缩放"), `a clip that never keyed 缩放 must not be told it did: ${moved}`);
assert.ok(moved.includes("再抵消一遍"), `the reason must say what would go wrong, got: ${moved}`);

const opacity = stabilizeBlocked(clip({ keyframes: [{ property: "opacity", at_ticks: 0, value: 0.5 }] }));
assert.equal(opacity, null, `a fade curve is not the stabiliser's, so it must not block: ${opacity}`);

/** The record is what tells a re-press from a double-correction: with it, the same curves are ours. */
const record = {
  strength: 1, max_crop: 0.1, points: 59, translation_correction: 0.02, roll_correction: 0,
  zoom_to_hide_borders: 1.04, analysed_frames: 59,
};
const owned = stabilizeBlocked(clip({
  stabilization: record,
  keyframes: [
    { property: "x", at_ticks: 0, value: 0.1 },
    { property: "scale", at_ticks: 0, value: 1 },
  ],
}));
assert.equal(owned, null, `a clip carrying its own stabilisation must be re-pressable, got: ${owned}`);
const ownedRamp = stabilizeBlocked(clip({ stabilization: record, speed_percent: 200 }));
assert.ok(ownedRamp?.includes("100%"), `ownership must not outvote the speed rule, got: ${ownedRamp}`);

console.log(
  "PASS: 画面稳定 is offered exactly when the engine would accept it — speed cases and the four "
  + "transform curves block with a named exit, mask and opacity curves do not, and the clip's own "
  + "stabilisation record re-opens the button without overruling the speed rule",
);
