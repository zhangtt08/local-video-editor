import type { Effects, MaskProperty, ShapeMask } from "./engine";

export const EFFECT_FIELDS: { property: keyof Effects; label: string; unit: string; min: number; max: number; step: number; factor: number }[] = [
  { property: "x", label: "位置 X", unit: "%", min: -200, max: 200, step: 1, factor: 100 },
  { property: "y", label: "位置 Y", unit: "%", min: -200, max: 200, step: 1, factor: 100 },
  { property: "scale", label: "缩放", unit: "%", min: 5, max: 400, step: 1, factor: 100 },
  { property: "rotation", label: "旋转", unit: "°", min: -360, max: 360, step: 1, factor: 1 },
  { property: "opacity", label: "不透明度", unit: "%", min: 0, max: 100, step: 1, factor: 100 },
  { property: "gain", label: "音量", unit: "%", min: 0, max: 400, step: 1, factor: 100 },
];


/** Rectangle and ellipse masks keyframe their own box; values stay in the mask's normalized units. */
export const MASK_ANIM_FIELDS: { property: MaskProperty; label: string; unit: string; min: number; max: number; step: number; factor: number; field: "center_x" | "center_y" | "width" | "height" }[] = [
  { property: "mask_x", label: "遮罩中心 X", unit: "%", min: 0, max: 100, step: 1, factor: 100, field: "center_x" },
  { property: "mask_y", label: "遮罩中心 Y", unit: "%", min: 0, max: 100, step: 1, factor: 100, field: "center_y" },
  { property: "mask_width", label: "遮罩宽度", unit: "%", min: 1, max: 200, step: 1, factor: 100, field: "width" },
  { property: "mask_height", label: "遮罩高度", unit: "%", min: 1, max: 200, step: 1, factor: 100, field: "height" },
];

/** Any non-inverted mask can be keyframed; a free-form outline only moves (see `maskAnimFields`). */
export const canAnimateMask = (mask?: ShapeMask | null): mask is ShapeMask =>
  Boolean(mask && !mask.inverted);

/** The curves a mask of this shape actually has: a path has no size, only a centre. */
export const maskAnimFields = (mask?: ShapeMask | null) =>
  !mask
    ? []
    : mask.shape === "path"
      ? MASK_ANIM_FIELDS.filter((field) => field.property === "mask_x" || field.property === "mask_y")
      : MASK_ANIM_FIELDS;

/** Label lookup for the keyframe list, which mixes effect and mask properties. */
export const FIELD_LABEL: Record<string, string> = Object.fromEntries(
  [...EFFECT_FIELDS, ...MASK_ANIM_FIELDS].map((field) => [field.property, field.label]),
);
