import type { Clip } from "./engine";

export type SplitTrim = { edge: "head" | "tail"; delta_ticks: number };

/**
 * The one place that turns a dragged edge into a `clip.link_split_trim`.
 *
 * A linked pair dragged with Alt held is a J/L cut: only this member's edge moves. The drag already
 * knows the window it wants, so the edge and the signed movement are read back from it here -- and
 * only accepted when recomputing the window from `(edge, delta)` gives exactly what was asked for.
 * Anything else (a ripple, a linked pair moved together, a window that is not a single-edge move)
 * returns null and the caller keeps using `clip.trim`, so the named command can never quietly mean
 * something different from the drag.
 */
export function linkSplitTrim(clip: Clip, sourceIn: number, duration: number, position?: number): SplitTrim | null {
  const end = clip.position_ticks + clip.duration_ticks;
  const head = position === undefined ? clip.position_ticks : position;
  const delta = head - clip.position_ticks;
  if (head !== clip.position_ticks) {
    // The head moved: the source has to slide by the same signed amount and the far end stays put.
    if (sourceIn - clip.source_in_ticks !== delta || head + duration !== end) return null;
    return delta === 0 ? null : { edge: "head", delta_ticks: delta };
  }
  if (sourceIn !== clip.source_in_ticks) return null;
  const tail = duration - clip.duration_ticks;
  return tail === 0 ? null : { edge: "tail", delta_ticks: tail };
}
