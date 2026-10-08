import type { AnimatedEffect, Capabilities, Clip, MaskProperty, ShapeMask } from "./engine";

/**
 * 柔焦滑杆的上限（占画面高的百分比）。两个数都由引擎下发：`limits.blur_fraction` 是契约里
 * 的比例上限，`limits.blur_radius_limit_px` 是导出/预览半径一致性和实测过的最大像素半径，
 * 按当前画幅高折算后取小——旧引擎不下发这两个字段时返回 0，界面就不显示这一行。
 */
export function blurMaxPercent(caps: Capabilities | null, frameHeight: number): number {
  if (!caps?.features.clip_blur || frameHeight <= 0) return 0;
  return Math.min(
    (caps.limits.blur_fraction ?? 0) * 100,
    ((caps.limits.blur_radius_limit_px ?? 0) / frameHeight) * 100,
  );
}

/**
 * 清晰（unsharp）两条滑杆的上限，同样全部由引擎下发：强度上限 `limits.sharpen_amount`；半径上限取
 * `limits.sharpen_radius_fraction` 与「验证过的像素半径 / 画面高」的小者——与柔焦共用同一个实测带，
 * 因为两端都是同一次高斯采样。旧引擎不下发 `clip_sharpen` 时返回 0，界面把两行都收起来。
 */
export function sharpenLimits(
  caps: Capabilities | null,
  frameHeight: number,
): { amount: number; radiusPercent: number } {
  if (!caps?.features.clip_sharpen || frameHeight <= 0) return { amount: 0, radiusPercent: 0 };
  return {
    amount: caps.limits.sharpen_amount ?? 0,
    radiusPercent: Math.min(
      (caps.limits.sharpen_radius_fraction ?? 0) * 100,
      ((caps.limits.blur_radius_limit_px ?? 0) / frameHeight) * 100,
    ),
  };
}

// The animatable set, not `keyof Effects`: `blur` is a static radius the exporter cannot animate.
export const EFFECT_FIELDS: { property: AnimatedEffect; label: string; unit: string; min: number; max: number; step: number; factor: number }[] = [
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

/** The three curves the stabiliser writes, plus rotation — the same set the engine guards. */
const STABILIZED = ["x", "y", "rotation", "scale"] as const;

/**
 * 「画面稳定」按不下去的原因，`null` 表示可以按。界面和引擎守同一条判断，所以点下去不会拿到
 * 另一套说法：变速片段量不准，已经K过位移/缩放/旋转的片段会被再抵消一遍——稳定是把纠偏叠加在
 * 片段已有的动画上，而引擎认不出哪一条是它上一次写的，只能让人先把它清掉。
 */
export const stabilizeBlocked = (clip: Clip): string | null => {
  if (clip.speed_curve?.length || (clip.speed_percent ?? 100) !== 100) {
    return "带变速的片段还不能稳定：抖动是按「一帧对一帧」量的，播放速度变了就对不上。把这段的速度改回 100% 再稳定。";
  }
  if (clip.stabilization) {
    // 这四条曲线是稳定自己写的：再按一次会按新的强度重算一遍，不是叠第二遍，所以不挡路。
    return null;
  }
  const keyed = STABILIZED.filter((property) =>
    (clip.keyframes ?? []).some((point) => point.property === property),
  ).map((property) => FIELD_LABEL[property]);
  if (keyed.length) {
    return `这段画面已经K了${keyed.join("、")}：稳定会把同一段抖动再抵消一遍，画面会朝反方向偏。撤销这一步，或在曲线编辑器里清掉这几条，再按一次。`;
  }
  return null;
};

