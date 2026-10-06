/** The browser must read the engine's piece list exactly the way the exporter does.
 *
 * The fixtures below are `describe(segments(clip, frame_ticks), TIMEBASE)` captured from this
 * repository's engine for two curves over a 4 s clip, so this check pins both sides of the seam:
 * the shape the server issues and the source position `pacing()` derives from it.
 */

import assert from "node:assert/strict";

import { pacing, type RampPiece } from "../desktop/src/time";

const U: RampPiece[] = [
  { at: 0.0, duration: 0.6666666666666666, source_at: 0.0, source_duration: 0.6, rate_percent: 90 },
  { at: 0.6666666666666666, duration: 0.6666666666666666, source_at: 0.6, source_duration: 0.4, rate_percent: 60 },
  { at: 1.3333333333333333, duration: 0.6666666666666666, source_at: 1.0, source_duration: 0.26666666666666666, rate_percent: 40 },
  { at: 2.0, duration: 0.3333333333333333, source_at: 1.2666666666666666, source_duration: 0.1, rate_percent: 30 },
  { at: 2.3333333333333335, duration: 0.3333333333333333, source_at: 1.3666666666666667, source_duration: 0.13333333333333333, rate_percent: 40 },
  { at: 2.6666666666666665, duration: 0.3333333333333333, source_at: 1.5, source_duration: 0.2, rate_percent: 60 },
  { at: 3.0, duration: 0.3333333333333333, source_at: 1.7, source_duration: 0.23333333333333334, rate_percent: 70 },
  { at: 3.3333333333333335, duration: 0.3333333333333333, source_at: 1.9333333333333333, source_duration: 0.26666666666666666, rate_percent: 80 },
  { at: 3.6666666666666665, duration: 0.3333333333333333, source_at: 2.2, source_duration: 0.3, rate_percent: 90 },
];
const FREEZE: RampPiece[] = [
  { at: 0.0, duration: 2.0, source_at: 0.0, source_duration: 2.0, rate_percent: 100 },
  { at: 2.0, duration: 2.0, source_at: 1.9666666666666666, source_duration: 0.0, rate_percent: 0 },
];

assert.equal(U.reduce((total, piece) => total + piece.duration, 0).toFixed(6), "4.000000");
assert.equal(
  U.reduce((total, piece) => total + piece.source_duration, 0).toFixed(6),
  "2.500000",
  "the U ramp reads 2.5s of a 4s clip",
);
for (const piece of U) {
  assert.equal(Math.round((piece.source_duration / piece.duration) * 100), piece.rate_percent, piece);
}

// A plain clip keeps the linear reading, with or without a base speed.
assert.deepEqual(pacing(100, null, 1.5), { rate: 1, source: 1.5 });
assert.deepEqual(pacing(250, undefined, 1.5), { rate: 2.5, source: 3.75 });

// Inside a piece the rate is constant, and every boundary is shared by the two neighbours.
for (const piece of U) {
  for (const at of [piece.at + 0.01, piece.at + piece.duration / 2, piece.at + piece.duration - 0.01]) {
    const pace = pacing(100, U, at);
    assert.equal(pace.rate, piece.rate_percent / 100, at);
    assert.ok(
      Math.abs(pace.source - (piece.source_at + (at - piece.at) * pace.rate)) < 1e-12,
      `${at} ${pace.source}`,
    );
    assert.ok(pace.source >= piece.source_at - 1e-12 && pace.source <= piece.source_at + piece.source_duration + 1e-12, at);
  }
}

const slowMiddle = pacing(100, U, 2.0).source;
assert.ok(slowMiddle > 1.2 && slowMiddle < 1.35, `half way reads ${slowMiddle}s`);
assert.ok(Math.abs(pacing(100, U, 4.0).source - 2.5) < 1e-9, "the whole clip ends where its window does");
assert.ok(Math.abs(pacing(100, U, 40).source - 2.5) < 1e-9, "a playhead past the end cannot read past the window");

// The freeze piece holds the last frame the window really contains, one frame back.
assert.deepEqual(pacing(100, FREEZE, 0.5), { rate: 1, source: 0.5 });
for (const at of [2.0, 2.7, 3.99]) {
  const pace = pacing(100, FREEZE, at);
  assert.equal(pace.rate, 0, at);
  assert.equal(pace.source, 1.9666666666666666, at);
}

// A base speed multiplies the plan the same way the exporter's window does.
assert.equal(pacing(200, U, 2.0).rate, pacing(100, U, 2.0).rate, "pieces already carry the base rate");
assert.equal(pacing(200, null, 2.0).source, 4.0);

console.log("PASS: browser pacing reproduces the engine piece list, holds freezes, never reads past the window");
