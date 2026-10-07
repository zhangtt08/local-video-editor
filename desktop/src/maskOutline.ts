/** Free-form outline editing: where a double-clicked vertex belongs, and what the outline looks like
 *  once it is there. Pure geometry, no React, so `tests/desktop_mask_check.ts` can assert it directly.
 *
 *  A closed path is read in vertex order, so a point picked on the edge between v1 and v2 has to be
 *  spliced between them — appending it to the end folds the outline across itself. The edge's cubic is
 *  then split at that position (de Casteljau), which keeps both halves on the original curve and hands
 *  the new vertex tangents inherited from it. */

import type { MaskVertex, ShapeMask } from "./engine";

/** Re-exported so the shell check can build vertices without importing the generated contract twice. */
export type OutlineVertex = MaskVertex;

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

/** Control points of the edge `a → b`: with no handles it degenerates to the straight segment. */
export const edgeControls = (a: MaskVertex, b: MaskVertex) => ({
  p0: { x: a.x, y: a.y },
  p1: { x: a.x + a.handle_out[0], y: a.y + a.handle_out[1] },
  p2: { x: b.x + b.handle_in[0], y: b.y + b.handle_in[1] },
  p3: { x: b.x, y: b.y },
});

export const cubicPoint = (a: MaskVertex, b: MaskVertex, t: number) => {
  const { p0, p1, p2, p3 } = edgeControls(a, b);
  const mt = 1 - t;
  return {
    x: mt * mt * mt * p0.x + 3 * mt * mt * t * p1.x + 3 * mt * t * t * p2.x + t * t * t * p3.x,
    y: mt * mt * mt * p0.y + 3 * mt * mt * t * p1.y + 3 * mt * t * t * p2.y + t * t * t * p3.y,
  };
};

/** The edge nearest `point`, plus the position along it. Curves are sampled, so the nearest point is
 *  on the visible outline rather than on the chord between its endpoints. */
export function nearestEdge(vertices: MaskVertex[], point: { x: number; y: number }) {
  let edge = 0, at = 0.5, best = Infinity;
  for (let index = 0; index < vertices.length; index += 1) {
    const a = vertices[index], b = vertices[(index + 1) % vertices.length];
    const curved = a.handle_out[0] || a.handle_out[1] || b.handle_in[0] || b.handle_in[1];
    const steps = curved ? 24 : 8;
    for (let step = 0; step <= steps; step += 1) {
      const at_ = cubicPoint(a, b, step / steps);
      const distance = (at_.x - point.x) ** 2 + (at_.y - point.y) ** 2;
      if (distance < best) { best = distance; edge = index; at = step / steps; }
    }
  }
  // Splitting at t=0 or 1 would flatten the neighbour's smoothing to nothing, so keep some handle both sides.
  return { edge, t: Math.min(0.95, Math.max(0.05, at)) };
}

/** A closed outline needs three points, so the last three are never deletable. Returns null when the
 *  index is out of range or the shape would collapse — the caller shows that as a disabled button. */
export function withoutVertex(mask: ShapeMask, index: number): ShapeMask | null {
  const list = mask.vertices ?? [];
  if (index < 0 || index >= list.length || list.length <= 3) return null;
  return { ...mask, vertices: list.filter((_, position) => position !== index) };
}

/** Drop both tangents: the curve passing through this vertex becomes two straight edges. */
export function asCorner(mask: ShapeMask, index: number): ShapeMask | null {
  const list = mask.vertices ?? [];
  const current = list[index];
  if (!current) return null;
  const smoothed = current.handle_out[0] || current.handle_out[1] || current.handle_in[0] || current.handle_in[1];
  if (!smoothed) return null;
  return { ...mask, vertices: list.map((entry, position) => position === index ? { ...entry, handle_out: [0, 0], handle_in: [0, 0] } : entry) };
}

/** The inverse: hand the corner the tangent a curve through its two neighbours would carry
 *  (Catmull-Rom to Bézier, one sixth of the neighbour chord per arm), so a drawn corner can be
 *  softened without dragging two handles blind. */
export function asSmooth(mask: ShapeMask, index: number): ShapeMask | null {
  const list = mask.vertices ?? [];
  const current = list[index];
  if (!current || list.length < 4) return null;
  if (current.handle_out[0] || current.handle_out[1] || current.handle_in[0] || current.handle_in[1]) return null;
  const previous = list[(index - 1 + list.length) % list.length], next = list[(index + 1) % list.length];
  const arm: [number, number] = [(next.x - previous.x) / 6, (next.y - previous.y) / 6];
  return { ...mask, vertices: list.map((entry, position) => position === index ? { ...entry, handle_out: arm, handle_in: [-arm[0], -arm[1]] } : entry) };
}
/** Insert `point` on the edge it is nearest to, rewriting the two bordering vertices' handles so the
 *  outline keeps its curvature. Vertices are copied; the mask that comes back is a fresh write object. */
export function withVertex(mask: ShapeMask, point: { x: number; y: number }): ShapeMask {
  const list = mask.vertices ?? [];
  const vertices = list.map((entry) => ({
    ...entry, handle_in: [...entry.handle_in] as [number, number], handle_out: [...entry.handle_out] as [number, number],
  }));
  if (vertices.length < 2) return { ...mask, vertices: [...vertices, { ...point, handle_out: [0, 0], handle_in: [0, 0] }] };
  const { edge, t } = nearestEdge(list, point);
  const a = list[edge], b = list[(edge + 1) % list.length];
  const next = (edge + 1) % list.length;
  const curved = Boolean(a.handle_out[0] || a.handle_out[1] || b.handle_in[0] || b.handle_in[1]);
  const { p0, p1, p2, p3 } = edgeControls(a, b);
  const A = { x: lerp(p0.x, p1.x, t), y: lerp(p0.y, p1.y, t) };
  const B = { x: lerp(p1.x, p2.x, t), y: lerp(p1.y, p2.y, t) };
  const C = { x: lerp(p2.x, p3.x, t), y: lerp(p2.y, p3.y, t) };
  const D = { x: lerp(A.x, B.x, t), y: lerp(A.y, B.y, t) };
  const E = { x: lerp(B.x, C.x, t), y: lerp(B.y, C.y, t) };
  const F = { x: lerp(D.x, E.x, t), y: lerp(D.y, E.y, t) };
  if (curved) {
    vertices[edge].handle_out = [A.x - p0.x, A.y - p0.y];
    vertices[next].handle_in = [C.x - p3.x, C.y - p3.y];
  }
  const added: MaskVertex = curved
    ? { x: point.x, y: point.y, handle_out: [E.x - F.x, E.y - F.y], handle_in: [D.x - F.x, D.y - F.y] }
    : { x: point.x, y: point.y, handle_out: [0, 0], handle_in: [0, 0] };
  vertices.splice(edge + 1, 0, added);
  return { ...mask, vertices };
}
