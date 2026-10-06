import assert from "node:assert/strict";

import { histogram, vectorscope, waveform } from "../desktop/src/scopes";

function solid(red: number, green: number, blue: number, width = 8, height = 8) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < width * height; i += 1) {
    data[i * 4] = red;
    data[i * 4 + 1] = green;
    data[i * 4 + 2] = blue;
    data[i * 4 + 3] = 255;
  }
  return { data, width, height };
}

// solid red: only the red bucket lights up, and red is flagged as clipped
const red = histogram(solid(255, 0, 0), 64);
const topR = red.r[red.r.length - 1];
assert.ok(topR > 0.99, `red bucket should be full, got ${topR}`);
assert.equal(red.g[0] > 0.99, true, "green bucket holds the black level");
assert.equal(red.luma[red.luma.length - 1] < 0.01, true, "luma stays low");
assert.ok(red.clipped.r === 1, "every red sample is clipped");

// mid grey sits mid-scale on all three channels
const grey = histogram(solid(128, 128, 128), 64);
const mid = Math.max(...Array.from(grey.r));
assert.ok(mid > 0.99);
const bucket = grey.r.findIndex((value) => value > 0.5);
assert.ok(bucket > 24 && bucket < 40, `grey should land mid-bucket, got ${bucket}`);
assert.equal(grey.clipped.r, 0);

// Uniform red is one horizontal trace at max red, with green/blue at black.
const wave = waveform(solid(255, 0, 0), 16, 8);
for (let x = 0; x < wave.width; x += 1) {
  for (let y = 0; y < wave.height; y += 1) {
    assert.equal(wave.r[x * wave.height + y] > 0, y === 0);
    assert.equal(wave.g[x * wave.height + y] > 0, y === wave.height - 1);
  }
}
const split = solid(0, 0, 0, 2, 2);
for (let row = 0; row < 2; row += 1) split.data[(row * 2 + 1) * 4] = 255;
const horizontal = waveform(split, 2, 8);
assert.equal(horizontal.r[7], 1, "left image column is black");
assert.equal(horizontal.r[8], 1, "right image column is max red");
assert.equal(horizontal.r[0], 0);
assert.equal(horizontal.r[15], 0);

// vectorscope: pure red traces the 0-degree axis, centre-right of the grid
const scope = vectorscope(solid(255, 0, 0), 64);
let lit = 0;
let bestX = 0;
for (let y = 0; y < scope.size; y += 1) {
  for (let x = 0; x < scope.size; x += 1) {
    if (scope.grid[y * scope.size + x] > 0.5) {
      lit += 1;
      if (x > bestX) bestX = x;
    }
  }
}
assert.ok(lit > 0, "vectorscope should trace pure red");
assert.ok(bestX >= 32, `red should land on the right half, got x=${bestX}`);
const centre = scope.grid[32 * scope.size + 32];
assert.ok(centre < 0.5, "pure red should not sit on the centre (that is grey)");

// neutral grey collapses onto the centre dot of the vectorscope
const neutral = vectorscope(solid(128, 128, 128), 64);
assert.ok(neutral.grid[32 * scope.size + 32] > 0.5, "neutral collapses to the centre");

console.log("PASS: histogram, waveform and vectorscope math");
