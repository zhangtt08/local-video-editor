// The export panel's codec line is written from the preset the engine returned. These assert the
// translation itself: a preset list that gains a format must show that format, and a name this
// table does not know has to appear verbatim rather than being dressed up as yesterday's H.264.
import assert from "node:assert/strict";
import {
  codecText,
  CODEC_NAMES,
  presetIsAudio,
  transitionChoices,
  transitionLabel,
  type Preset,
} from "../desktop/src/engine";

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

const audio = (over: Partial<Preset>): Preset =>
  preset({ container: "mp3", codec: null, pixel_format: null, scale: null, ...over });

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
// An audio-only preset names no picture, so the line says so instead of inventing a video codec.
assert.equal(codecText(audio({ audio_codec: "libmp3lame" })), "仅音频 · MP3");
assert.equal(codecText(audio({ container: "wav", audio_codec: "pcm_s24le" })), "仅音频 · PCM 24-bit");
assert.equal(codecText(audio({ container: "flac", audio_codec: "flac" })), "仅音频 · FLAC");
assert.equal(presetIsAudio(audio({})), true);
assert.equal(presetIsAudio(preset({})), false);
assert.equal(presetIsAudio(null), false, "no preset selected is not an audio deliverable");
// Transition kinds come from the engine's table; the fallback is only what a pre-1.59 engine can honour.
assert.deepEqual(
  transitionChoices(null).map((c) => c.id),
  ["dissolve", "dip_black", "dip_white"],
);
const caps = {
  transition_kinds: [
    { id: "dissolve", label: "交叉溶解" },
    { id: "wipe_from_top", label: "从上擦除" },
    { id: "zoom_in", label: "放大进入" },
  ],
};
assert.deepEqual(transitionChoices(caps), caps.transition_kinds, "the engine list is used verbatim");
assert.equal(transitionLabel(caps, "wipe_from_top"), "从上擦除");
assert.equal(transitionLabel(caps, "wipe_sideways"), "wipe_sideways", "an unknown id is shown, not guessed");
assert.equal(transitionLabel(null, "dip_white"), "闪白", "the fallback covers the three old kinds");

// 1.142：这张表里多了 exr／dpx 两个名字——预设表加一种交付，念它的那张表必须跟着长，
// 否则界面会把 FFmpeg 的编码器名原样甩给人看。
assert.deepEqual(Object.keys(CODEC_NAMES).sort(), [
  "aac",
  "dpx",
  "exr",
  "flac",
  "libmp3lame",
  "libopus",
  "libvpx-vp9",
  "libx264",
  "libx265",
  "pcm_s24le",
  "prores_ks",
]);

console.log(
  "PASS: every preset's codec line is derived from the preset, audio-only lines say 仅音频, unknown " +
    "names pass through, and only the non-default sampling is spelled out"
);
