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
  {
    kind: "lut",
    enabled: true,
    mix: 0.4,
    title: "Film Look 01",
    size: 33,
    channels: [[0, 0.5, 1], [0, 0.25, 0.5], [0, 1, 1]],
  },
  // 两张 3D 表连着导入是支持的（每张自己成一段），所以每张卡片都得替自己说话。
  { kind: "lut3d", enabled: true, title: "Print 01", size: 17, cells: [0, 0.5, 1] },
  { kind: "lut3d", enabled: true, title: "Print 02", size: 2, cells: [0, 0, 0, 1, 1, 1], resampled_from: 33 },
] as never as Parameters<typeof cardsFor>[0];

const cards = cardsFor(chain);
assert.equal(cards.length, 6);
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
assert.equal(cards[3].label, "4. LUT 查找表");
assert.match(cards[3].detail, /Film Look 01 · 33 点/, cards[3].detail);
assert.match(cards[3].detail, /强度 40%/, cards[3].detail);
assert.equal(cards[3].lanes.length, 0, "a LUT is one node, not a set of branches");

// 3D 表在卡片上就把两件事写明白：浏览器画不出它（只有导出会走它），以及它没有强度可拧
// ——契约里就没有 mix 那个字段，卡片说「强度 100%」就等于允诺一件引擎不会做的事。
assert.equal(cards[4].label, "5. 3D LUT");
assert.match(cards[4].detail, /Print 01 · 17³ 网格 · 仅导出生效/, cards[4].detail);
assert.equal(cards[5].label, "6. 3D LUT");
assert.match(cards[5].detail, /Print 02 · 2³ 网格 · 仅导出生效 · 由 33³ 重采样/, cards[5].detail);
for (const card of [cards[4], cards[5]]) {
  assert.doesNotMatch(card.detail, /强度/, `${card.detail} 里不该有强度`);
  assert.equal(card.lanes.length, 0, "a cube is one node, not a set of branches");
}
// 两张都说话，一张也不代表另一张：链里第二段不能被第一段顶掉。
assert.notEqual(cards[4].detail, cards[5].detail, "each cube describes its own grid");

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
  { kind: "lut3d", enabled: false, title: "Bypassed", size: 2, cells: [0, 0, 0, 1, 1, 1] },
] as never as Parameters<typeof cardsFor>[0]);
assert.equal(disabled[0].enabled, false, "a bypassed node has to look bypassed in the picture");
assert.equal(disabled[1].enabled, false, "a bypassed cube has to look bypassed too");
assert.match(disabled[1].detail, /仅导出生效/, disabled[1].detail);

console.log("PASS: grade graph — cards describe their nodes, drops clamp, moves stay pure");
