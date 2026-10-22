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
  // 1.81: a sample from every family that used to fall through to English. The vocabulary gate
  // checks all 116 codes exist; this checks the runtime path actually speaks Chinese for them.
  "MEDIA_NOT_FOUND",
  "MEDIA_PATH_INVALID",
  "PROBE_NOT_FOUND",
  "LOUDNESS_FAILED",
  "SPEECH_NOT_FOUND",
  "SUBTITLES_MODEL_MISSING",
  "INVALID_SPLIT",
  "INVALID_MARKER_SPLIT",
  "NOT_ADJACENT",
  "DUPLICATE_ID",
  "REVISION_OVERFLOW",
  "OUTPUT_INVALID",
  "UNKNOWN_PRESET",
  "FONT_UNAVAILABLE",
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

// 引擎自己已经说中文的那一类拒绝（时间码点名是哪一段数字不对），具体那半句不能被通用提示盖掉。
const specific = new EngineError(
  "TIMECODE_INVALID",
  "时间码 '01:60:00:00' 不能用：分钟最多 59，收到 60。写法 HH:MM:SS:FF",
  { value: "01:60:00:00" },
  422
);
assert.ok(specific.explain().includes("分钟最多 59"), `the engine's own detail was overwritten: ${specific.explain()}`);
// 引擎只说英文时，中文那句仍是人看到的——这条是 1.75 以来的老规矩，不许被上面那半句带走。
const english = new EngineError("TRACK_LOCKED", "track is locked", {}, 422);
assert.equal(english.explain(), "轨道已锁定，请解锁或选择其他目标轨道。", "english message lost its hint");

const unknown = new EngineError("SOMETHING_NEW", "the engine said this", {}, 422);
assert.equal(unknown.explain(), "the engine said this", "an unhinted code shows the engine's words");

// 1.265：`PROJECT_LIMIT` 过去交回的是「project exceeds the supported contract limits」加一份空的
// details，而界面那句中文给的出路是「把长段落拆成几条片段」——那一下只会让片段更多。两头现在都改：
// 引擎点名是哪一格与两个数，界面念出那一格、两个数，并且只指真减得下数的出路。
const crowded = new EngineError(
  "PROJECT_LIMIT",
  "clips rejected by the contract: Dictionary should have at most 20000 items after validation, not 20001",
  { contract_path: "clips", reason: "too_long", max_length: 20000, actual_length: 20001 },
  422,
);
const advice = crowded.explain();
assert.ok(advice.includes("最多 20000"), `那两个数得让人看得见：${advice}`);
assert.ok(advice.includes("现在要存 20001"), `这一次要存的数也得带出来：${advice}`);
assert.ok(advice.includes("这一格片段"), `契约字段名要念成中文那一面：${advice}`);
assert.ok(!advice.includes("clips"), `不许把契约里的字段名原样印给人：${advice}`);
assert.ok(!advice.includes("拆成几条片段"), `不许再指那条只会让片段更多的手：${advice}`);
assert.ok(advice.includes("删掉"), `上限那句得说一条真减得下数的出路：${advice}`);
// 反向：数字不在 details 里时不许编一个数出来。
const plain = new EngineError("PROJECT_LIMIT", "no numbers here", {}, 422);
assert.ok(!plain.explain().includes("最多"), `没有数就不许说一句带数的话：${plain.explain()}`);

console.log(
  "PASS: the shell weaves the named file, clip, track or composition into every Chinese hint, the "
  + "eleven analysis refusals all answer in Chinese with a way out, and nothing is added when the "
  + "engine named no target",
);
