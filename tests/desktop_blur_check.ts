/** The soft-focus slider must never offer what the exporter would refuse — asserted without a
 * browser, by driving the same helper the Inspector uses.
 *
 * `blur` is the one picture knob that is deliberately *not* in EFFECT_FIELDS: the exporter has no
 * per-frame radius, so the interface must not grow a keyframe diamond for it. Both halves are
 * pinned here.
 */

import assert from "node:assert/strict";

import { blurMaxPercent, EFFECT_FIELDS } from "../desktop/src/effects";
import { DEFAULT_EFFECTS } from "../desktop/src/engine";
import type { Capabilities } from "../desktop/src/engine";

const FRACTION = 0.25;
const RADIUS_LIMIT = 64;

function caps(blur: boolean): Capabilities {
  return {
    api_version: "v1",
    project_schema_version: 12,
    timebase: 70_560_000,
    max_commands_per_batch: 200,
    commands: [],
    features: { clip_blur: blur },
    limits: {
      max_tracks: 128,
      max_assets: 10_000,
      max_clips: 20_000,
      sample_rates: [48_000],
      blur_fraction: FRACTION,
      blur_radius_limit_px: RADIUS_LIMIT,
    },
    render_presets: [],
  } as unknown as Capabilities;
}

assert.equal(DEFAULT_EFFECTS.blur, 0, "a fresh clip must not be blurred");
assert.deepEqual(
  EFFECT_FIELDS.map((field) => field.property),
  ["x", "y", "scale", "rotation", "opacity", "gain"],
  "blur is a static radius: it must not appear in the keyframable field list",
);

assert.equal(blurMaxPercent(null, 1080), 0, "no capabilities means no slider");
assert.equal(blurMaxPercent(caps(false), 1080), 0, "an engine without clip_blur stays hidden");
assert.equal(blurMaxPercent(caps(true), 0), 0, "a frame of unknown height stays hidden");

// The band that was measured is the band the interface may offer, at every delivery height.
for (const height of [200, 720, 1080, 2160, 4320]) {
  const percent = blurMaxPercent(caps(true), height);
  assert.ok(percent > 0 && (percent / 100) * height <= RADIUS_LIMIT + 1e-9, `${height}: ${percent}`);
}
assert.equal(blurMaxPercent(caps(true), 200), FRACTION * 100, "short frames are bound by the fraction");
assert.equal(
  blurMaxPercent(caps(true), 1080),
  (RADIUS_LIMIT / 1080) * 100,
  "tall frames are bound by the measured radius band, not the fraction",
);

const tallPercent = (RADIUS_LIMIT / 1080) * 100;
console.log(
  `PASS: 柔焦 offers ${tallPercent.toFixed(2)}% of a 1080 frame at most and never asks for more ` +
    `than ${RADIUS_LIMIT} px at any delivery height; blur stays out of the keyframable list, and ` +
    "an engine without clip_blur shows nothing",
);
