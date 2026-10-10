import type { MaskShapeWindow, MaskVertex, ShapeMask } from "./engine";

/** The window the engine named for this clip-local moment.
 *
 * A morphing outline is executed as frame-aligned constant windows (`animation.mask_shape_schedule`):
 * the exporter cuts one plate per window, and this only picks which one is current. Nothing here
 * interpolates — a shape the preview invents between two windows is a shape the delivered file will
 * not contain, which is the exact defect the staircase exists to prevent.
 */
export function shapeWindowAt(windows: MaskShapeWindow[] | null | undefined, atTicks: number): MaskShapeWindow | null {
  if (!windows?.length) return null;
  const at = Math.max(0, atTicks);
  for (const window of windows) if (at < window.to_ticks) return window;
  return windows[windows.length - 1];
}

/** Which step of the engine's staircase this moment falls in, 1-based. The panel says it out loud so
 * a person can see the width of one step instead of guessing whether the shape is holding. */
export function shapeWindowIndex(windows: MaskShapeWindow[] | null | undefined, atTicks: number): number {
  if (!windows?.length) return 0;
  const at = Math.max(0, atTicks);
  const index = windows.findIndex((window) => at < window.to_ticks);
  return (index < 0 ? windows.length : index) + 1;
}

/** The outline to draw, to grab, and to send back: this window's table, or the shape as drawn.
 *
 * Starting a drag from the window rather than from `mask.vertices` is what makes the handle you see
 * the handle you move: at a moment in the middle of a morph the stored outline is not on screen.
 */
export function outlineAt(window: MaskShapeWindow | null, mask: ShapeMask | null | undefined): MaskVertex[] {
  return window?.vertices ?? mask?.vertices ?? [];
}

/** The CSS custom properties that place a morphing plate: the engine's own numbers, unscaled.
 *
 * `offset` is how far this window's outline sits from the box the shape was drawn in — the same
 * term the exporter adds to `mask_x` inside the overlay's x expression — and `width`/`height` are
 * the plate's box, not a scale of the mask's, because a free-form mask's size is not keyframable
 * and the export does not couple the two.
 */
export function shapeVariables(window: MaskShapeWindow | null): Record<string, number> {
  if (!window) return {};
  return {
    "--shape-w": window.width,
    "--shape-h": window.height,
    "--shape-ox": window.offset_x,
    "--shape-oy": window.offset_y,
  };
}

/** Whether a vertex drag should record an outline or redraw the static shape.
 *
 * The presence of an outline is the switch, exactly like a stopwatch in After Effects: once a shape
 * is animated, moving a node *is* a keyframe, and the static outline is left where it was drawn.
 */
export function morphArmed(clip: { mask_shape_keys?: unknown[] | null } | null | undefined): boolean {
  return Boolean(clip?.mask_shape_keys?.length);
}
