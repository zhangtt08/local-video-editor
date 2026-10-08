/** 自动调色按钮的门：量不到画面的，就不该亮着让人按下弹错。

 `GradeFields.tsx` calls `autoGradeBlocker` once for the button's `disabled` and the same returned
 sentence for its `tooltip`, so the grey-out and the explanation cannot drift apart. The cases below
 are the shapes that really occur: a still (measurable), a text layer (no frames), an audio asset,
 and a video clip parked on an audio track — which renders no frame even though the asset has one.
 Each refusal must name a way out that actually works, not just say "重试".
 */

import assert from "node:assert/strict";

import { AUTO_GRADE_NOT_PICTURE, AUTO_GRADE_NO_ENGINE, autoGradeBlocker } from "../desktop/src/effects";

assert.equal(
  autoGradeBlocker("video", "video", "video", true),
  null,
  "a verified video on a picture track is measurable",
);
assert.equal(
  autoGradeBlocker("image", "image", "video", true),
  null,
  "a still image is a picture too — 剪映 lets you auto-grade one",
);
assert.equal(
  autoGradeBlocker(undefined, undefined, "video", true),
  AUTO_GRADE_NOT_PICTURE,
  "no clip selected, nothing to measure",
);
assert.equal(
  autoGradeBlocker("text", undefined, "video", true),
  AUTO_GRADE_NOT_PICTURE,
  "a text layer has no frames of its own",
);
assert.equal(
  autoGradeBlocker("audio", "audio", "audio", true),
  AUTO_GRADE_NOT_PICTURE,
  "audio has no picture at all",
);
assert.equal(
  autoGradeBlocker("video", "video", "audio", true),
  AUTO_GRADE_NOT_PICTURE,
  "a video clip on an audio track renders no frame — the engine refuses it the same way",
);
assert.equal(
  autoGradeBlocker("video", "video", "video", false),
  AUTO_GRADE_NO_ENGINE,
  "without the media engine the numbers cannot be measured",
);
assert.ok(
  AUTO_GRADE_NOT_PICTURE.includes("画面轨") && AUTO_GRADE_NOT_PICTURE.includes("色阶"),
  "the reason has to name two exits that really work: move to a picture track, or set the points by hand",
);
assert.ok(
  AUTO_GRADE_NO_ENGINE.includes("素材就绪") && AUTO_GRADE_NO_ENGINE.includes("色阶"),
  "the engine-off reason has to say what to wait for and what to do meanwhile",
);
assert.ok(!AUTO_GRADE_NOT_PICTURE.includes("重试"), "a refusal that only says 重试 is not a way out");

console.log("desktop_autograde_check: the auto-grade gate blocks exactly the unmeasurable cases");
