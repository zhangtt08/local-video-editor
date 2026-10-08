/** A refusal the interface shows has to say which file, clip, track or composition it means.

 `explain()` deliberately replaces the engine's English message with a Chinese sentence naming the
 next action. That is only useful if the sentence still carries the target: "素材原文件已被移动或删除"
 across a library of forty assets asks the editor to guess. 1.75 put `clip_id` / `asset_id` /
 `asset_label` / `track_id` / `sequence_id` into every analysis refusal's `details`, and this pins
 that the shell weaves them in — and stays silent when there is nothing to name.
 */

import assert from "node:assert/strict";

import { EngineError } from "../desktop/src/engine";

const missing = new EngineError(
  "MEDIA_MISSING",
  "source file is gone",
  { clip_id: "s", asset_id: "tone", asset_label: "tone.mp4" },
  410,
);
const shown = missing.explain();
assert.ok(shown.includes("素材原文件已被移动或删除"), `the Chinese hint must survive, got: ${shown}`);
assert.ok(shown.includes("tone.mp4"), `the refusal must name the file, got: ${shown}`);
assert.ok(shown.includes("片段 s"), `and the clip that could not read it, got: ${shown}`);
assert.ok(!shown.includes("素材 tone（"), `the asset id must not repeat behind its own name: ${shown}`);

const ghost = new EngineError("NOT_FOUND", "clip is not in this project", { clip_id: "s" }, 404);
const where = ghost.explain();
assert.ok(where.includes("片段 s"), `a missing clip must be named: ${where}`);
assert.ok(where.includes("合成"), `and the way back to it must be said in Chinese: ${where}`);
assert.ok(!/^[a-z ]+$/.test(where), `an analysis refusal must not reach the editor in English: ${where}`);

// The eleven codes the analysis routes answer with had no Chinese sentence at all before 1.75, so
// the toast showed the engine's English text. Each one now has to say what to do instead.
for (const code of [
  "NOT_FOUND",
  "INVALID_SILENCE_TARGET",
  "INVALID_LOUDNESS_TARGET",
  "INVALID_REFRAME",
  "INVALID_DUCK",
  "DUCK_PLAN_TOO_LARGE",
  "INVALID_TRACK_TARGET",
  "TRACK_FAILED",
  "INVALID_SPEED",
  "PROJECT_LIMIT",
  "TIME_OVERFLOW",
]) {
  const said = new EngineError(code, "source file is gone", {}, 422).explain();
  assert.notEqual(said, "source file is gone", `${code} still shows the engine's English`);
  assert.ok(/[一-鿿]/.test(said), `${code} must answer in Chinese: ${said}`);
  assert.ok(said.length > 12, `${code} is too thin to act on: ${said}`);
}

const bare = new EngineError("TRACK_LOCKED", "track is locked", {}, 422);
assert.equal(
  bare.explain(),
  "轨道已锁定，请解锁或选择其他目标轨道。",
  `a hint with nothing to name must not grow empty brackets: ${bare.explain()}`,
);

const unknown = new EngineError("SOMETHING_NEW", "the engine said this", {}, 422);
assert.equal(unknown.explain(), "the engine said this", "an unhinted code shows the engine's words");

console.log(
  "PASS: the shell weaves the named file, clip, track or composition into every Chinese hint, the "
  + "eleven analysis refusals all answer in Chinese with a way out, and nothing is added when the "
  + "engine named no target",
);
