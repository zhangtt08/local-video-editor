/** The grade graph's ordering rules, asserted without a browser: what a card says about its node,
 *  where a dragged card lands, and that a move is a move — same nodes, one position changed. */

import assert from "node:assert/strict";

import { cardsFor, dropIndex, moveWithin } from "../desktop/src/gradeGraph";

const chain = [
  { kind: "white_balance", enabled: true, mix: 0.5, blend: "screen" },
  {
    kind: "parallel",
    enabled: true,
    branches: [
      { kind: "curve", enabled: true, mix: 1 },
      { kind: "wheels", enabled: false, mix: 0.25 },
      { kind: "white_balance", enabled: true, mix: 1 },
    ],
  },
  { kind: "transfer", enabled: true, target: "bt709" },
] as never as Parameters<typeof cardsFor>[0];

const cards = cardsFor(chain);
assert.equal(cards.length, 3);
assert.equal(cards[0].label, "1. 白平衡");
assert.match(cards[0].detail, /强度 50%/, cards[0].detail);
assert.doesNotMatch(cards[0].detail, /100%/, cards[0].detail);
assert.equal(cards[1].kind, "parallel");
assert.match(cards[1].detail, /^3 支/, cards[1].detail);
assert.equal(cards[1].lanes.length, 3);
assert.deepEqual(cards[1].lanes.map((lane) => lane.enabled), [true, false, true]);
assert.match(cards[1].lanes[1].detail, /强度 25%/, cards[1].lanes[1].detail);
assert.equal(cards[2].label, "3. 色彩空间");
assert.equal(cards[2].lanes.length, 0);
assert.equal(cards.every((card) => card.enabled), true);

assert.equal(dropIndex(0, 5), 0, "an empty chain has nowhere to drop");
assert.equal(dropIndex(3, -3), 0, "a drag past the left edge lands on the first slot");
assert.equal(dropIndex(3, 99), 2, "a drag past the right edge lands on the last slot");

const before = ["a", "b", "c", "d"];
const moved = moveWithin(before, 0, 2);
assert.deepEqual(before, ["a", "b", "c", "d"], "the source list must not be mutated");
assert.deepEqual(moved, ["b", "c", "a", "d"]);
assert.equal(moved.length, before.length);
assert.deepEqual([...moved].sort(), [...before].sort(), "a move never adds or loses a node");
assert.deepEqual(moveWithin(before, 2, 2), before, "dropping a card on itself changes nothing");
assert.deepEqual(moveWithin(before, 9, 0), before, "an impossible index is a no-op, not a splice");
assert.deepEqual(moveWithin(before, 1, 99), ["a", "c", "d", "b"], "a drop past the end goes last");
assert.notEqual(moveWithin(before, 1, 1), before, "the caller always gets a fresh array to write");

const disabled = cardsFor([
  { kind: "curve", enabled: false, mix: 1 },
] as never as Parameters<typeof cardsFor>[0]);
assert.equal(disabled[0].enabled, false, "a bypassed node has to look bypassed in the picture");

console.log("PASS: grade graph — cards describe their nodes, drops clamp, moves stay pure");
