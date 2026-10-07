/** Free-form mask outline editing, asserted without a browser: a double-clicked vertex lands on the
 *  edge it was picked on (not at the end of the list), the edge's curvature survives the split, and the
 *  mask the caller passed in is never mutated. */

import assert from "node:assert/strict";

import { nearestEdge, withVertex, type OutlineVertex } from "../desktop/src/maskOutline";

const vertex = (x: number, y: number, out: [number, number] = [0, 0], inn: [number, number] = [0, 0]): OutlineVertex => ({ x, y, handle_out: out, handle_in: inn });
const square = [vertex(0.1, 0.1), vertex(0.9, 0.1), vertex(0.9, 0.9), vertex(0.1, 0.9)];
const mask = (vertices: OutlineVertex[]) => ({ shape: "path" as const, center_x: 0.5, center_y: 0.5, width: 0.8, height: 0.8, feather: 0, inverted: false, vertices });

// 1. A point picked on the edge v1→v2 is spliced between them. Appending it (the old behaviour) would
//    put index 4 here and fold the closed outline across itself.
const before = mask(square);
const inserted = withVertex(before, { x: 0.95, y: 0.5 });
assert.equal(inserted.vertices?.length, 5);
assert.deepEqual(inserted.vertices?.[2], { x: 0.95, y: 0.5, handle_out: [0, 0], handle_in: [0, 0] });
assert.deepEqual(inserted.vertices?.[1], square[1], "the edge's start keeps its spot");
assert.deepEqual(inserted.vertices?.[3], square[2], "the edge's end keeps its spot");
assert.equal(nearestEdge(square, { x: 0.95, y: 0.5 }).edge, 1);
// Straight edges get a corner, and no handle rewriting.
assert.deepEqual(inserted.vertices?.[1].handle_out, [0, 0]);
assert.deepEqual(inserted.vertices?.[3].handle_in, [0, 0]);

// 2. The caller's mask is untouched — the write object is a fresh copy.
assert.deepEqual(before.vertices, square);
assert.equal(before.vertices?.length, 4);

// 3. A curved edge splits exactly: the neighbour arms shrink by t and 1−t along the same direction, and
//    the new vertex leaves and arrives along one straight tangent (G1 through the point).
const bow = [vertex(0.1, 0.2, [0.2, 0.1]), vertex(0.9, 0.2, [-0.1, 0.2], [-0.2, -0.1]), vertex(0.9, 0.8), vertex(0.1, 0.8)];
const a = bow[0], b = bow[1];
const picked = nearestEdge(bow, { x: 0.5, y: 0.2 });
assert.equal(picked.edge, 0);
const t = picked.t;
// edge 0 is the cubic (0.1,0.2) (0.3,0.3) (0.7,0.1) (0.9,0.2), whose midpoint is exactly (0.5,0.2).
const split = withVertex(mask(bow), { x: 0.5, y: 0.2 }).vertices!;
const [na, nv, nb] = [split[0], split[1], split[2]];
assert.deepEqual(bow[0].handle_out, [0.2, 0.1], 'the caller vertex list is never rewritten');
assert.deepEqual(bow[1].handle_in, [-0.2, -0.1], 'nor is the neighbour it splits into');
const scale = (arm: [number, number], k: number): [number, number] => [arm[0] * k, arm[1] * k];
assert.ok(Math.abs(na.handle_out[0] - scale(a.handle_out, t)[0]) < 1e-12, JSON.stringify(na.handle_out));
assert.ok(Math.abs(na.handle_out[1] - scale(a.handle_out, t)[1]) < 1e-12);
assert.ok(Math.abs(nb.handle_in[0] - scale(b.handle_in, 1 - t)[0]) < 1e-12, JSON.stringify(nb.handle_in));
assert.ok(Math.abs(nb.handle_in[1] - scale(b.handle_in, 1 - t)[1]) < 1e-12);
const cross = nv.handle_out[0] * nv.handle_in[1] - nv.handle_out[1] * nv.handle_in[0];
const lengths = Math.hypot(...nv.handle_out) * Math.hypot(...nv.handle_in);
assert.ok(Math.abs(cross) < 1e-12 * (lengths || 1), "the two arms stay on one line");
assert.ok(nv.handle_out[0] * nv.handle_in[0] + nv.handle_out[1] * nv.handle_in[1] < 0, "they point opposite ways");
assert.notDeepEqual(nv.handle_out, [0, 0], "a point added on a curve is not a corner");

// 4. Clicking exactly on an existing vertex still leaves smoothing on both sides (t is clamped away
//    from 0 and 1, which would otherwise flatten a neighbour's arm to nothing).
const onCorner = withVertex(mask(bow), { x: 0.9, y: 0.2 }).vertices!;
assert.ok(Math.hypot(...onCorner[1].handle_out) > 0, "the edge's start keeps part of its arm");
assert.ok(Math.hypot(...onCorner[2].handle_in) > 0, "the edge's end keeps part of its arm");
assert.equal(onCorner.length, 5);

console.log("desktop_mask_check: outline inserts on the picked edge, splits the curve exactly, copies the input");
