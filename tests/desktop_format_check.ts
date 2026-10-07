// The export panel's codec line is written from the preset the engine returned. These assert the
// translation itself: a preset list that gains a format must show that format, and a name this
// table does not know has to appear verbatim rather than being dressed up as yesterday's H.264.
import assert from "node:assert/strict";
import { codecText, CODEC_NAMES, type Preset } from "../desktop/src/engine";

const preset = (over: Partial<Preset>): Preset => ({
  id: "x",
  label: "x",
  container: "mp4",
  codec: "libx264",
  crf: 23,
  encoder_preset: "veryfast",
  audio_codec: "aac",
  audio_bitrate: "192k",
  pixel_format: "yuv420p",
  profile: null,
  scale: [1920, 1080],
  ...over,
});

assert.equal(codecText(preset({})), "H.264 / AAC");
assert.equal(codecText(preset({ codec: "libx265" })), "HEVC / AAC");
assert.equal(
  codecText(preset({ container: "webm", codec: "libvpx-vp9", audio_codec: "libopus", audio_bitrate: "128k" })),
  "VP9 / Opus",
);
assert.equal(
  codecText(
    preset({
      container: "mov",
      codec: "prores_ks",
      crf: null,
      encoder_preset: null,
      audio_codec: "pcm_s24le",
      audio_bitrate: null,
      pixel_format: "yuv444p10le",
      profile: 3,
      scale: null,
    }),
  ),
  "ProRes 422 HQ / PCM 24-bit · 4:4:4 10-bit",
);
// An unknown codec is shown as the engine named it: inventing a friendly label would hide a preset
// the shell has not been updated for.
assert.equal(codecText(preset({ codec: "av1", audio_codec: "opus" })), "av1 / opus");
// The 4:2:0 8-bit case carries no sampling suffix, so the common rows stay short; the deep ones do.
assert.ok(!codecText(preset({})).includes("4:2:0"), codecText(preset({})));
assert.ok(codecText(preset({ pixel_format: "yuv444p10le" })).includes("4:4:4 10-bit"));
assert.deepEqual(Object.keys(CODEC_NAMES).sort(), [
  "aac",
  "libopus",
  "libvpx-vp9",
  "libx264",
  "libx265",
  "pcm_s24le",
  "prores_ks",
]);

console.log(
  "PASS: every preset's codec line is derived from the preset, unknown names pass through, and only " +
    "the non-default sampling is spelled out"
);
