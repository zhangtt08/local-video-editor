import type { GradeCapacity } from "./engine";
import type { AnimatedEffect, Asset, Bezier, BlendMode, Capabilities, Clip, Command, Curve, Effects, Keyframe, LayerKeyframe, LayerProperty, LayerWindow, MaskBoxKey, MaskProperty, Project, SharpenSpec, SharpenStatic, SharpenSteps, ShapeMask, SpatialProperty, WipeChannel } from "./engine";
import { DEFAULT_EFFECTS } from "./engine";
import { TIMEBASE } from "./time";

/**
 * 柔焦滑杆的上限（占画面高的百分比）。两个数都由引擎下发：`limits.blur_fraction` 是契约里
 * 的比例上限，`limits.blur_radius_limit_px` 是导出/预览半径一致性和实测过的最大像素半径，
 * 按当前画幅高折算后取小——旧引擎不下发这两个字段时返回 0，界面就不显示这一行。
 */
/** 1.233：把这一段正好放进「几秒」。算的是播放速度：这段消耗的源不变，时长按倍率缩放。
 *  引擎的速度量程是 25%–400%，放不进去就点名这段能放成几秒——不静悄悄夹到边上，
 *  也不绕过那条校验（真的越界时引擎仍会拒）。带曲线变速的片段先拒：一条曲线没有单一倍率。 */
export function fitSpeedPercent(clip: Clip, seconds: number, frame: number): { percent?: number; words: string } {
  if (clip.speed_curve && clip.speed_curve.length) {
    return { words: "这段带着曲线变速：先关掉曲线，再按时长适配。" };
  }
  const speed = clip.speed_percent ?? 100;
  const source = (clip.duration_ticks * speed) / 100;
  const target = Math.round((seconds * TIMEBASE) / frame) * frame;
  if (!(target > 0) || !Number.isFinite(target)) return { words: "目标时长要大于零。" };
  const percent = Math.round((source / target) * 100);
  if (percent < 25 || percent > 400) {
    const shortest = source / 4 / TIMEBASE;
    const longest = source * 4 / TIMEBASE;
    return {
      words: `放不进 ${(target / TIMEBASE).toFixed(2)} 秒：播放速度只有 25%–400%，`
        + `这段能适配成 ${shortest.toFixed(2)}–${longest.toFixed(2)} 秒。`,
    };
  }
  const now = clip.duration_ticks / TIMEBASE;
  if (percent === speed) return { percent, words: `这段现在就是 ${now.toFixed(2)} 秒（${percent}%），不用改。` };
  return {
    percent,
    words: `播放速度 ${speed}% → ${percent}%，这段从 ${now.toFixed(2)} 秒变成 ${(target / TIMEBASE).toFixed(2)} 秒。`,
  };
}


/**
 * 1.263：这一块此刻「怎么走」只有一处说法。
 *
 * `composed` 是引擎那一格 `features.extra_mask_follow_motion`：不认识它的引擎仍然把框点与跟随
 * 当互斥的事来做，那时界面说「先跟后动」就是一句服务端不会兑现的承诺。
 */
export function extraMotionWords(keys: number, follow: boolean, composed: boolean): string {
  if (keys && follow && composed) return `先跟后动 · ${keys} 枚框点`;
  if (keys) return `自己走 · ${keys} 枚框点`;
  return follow ? "跟随主遮罩" : "静止";
}

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

// The six curves the exporter evaluates frame by frame. `blur` sits beside them only through
// `spatialAnimFields` below: it is a window schedule, not a per-frame sigma.
export const EFFECT_FIELDS: { property: AnimatedEffect; label: string; unit: string; min: number; max: number; step: number; factor: number }[] = [
  { property: "x", label: "位置 X", unit: "%", min: -200, max: 200, step: 1, factor: 100 },
  { property: "y", label: "位置 Y", unit: "%", min: -200, max: 200, step: 1, factor: 100 },
  { property: "scale", label: "缩放", unit: "%", min: 5, max: 400, step: 1, factor: 100 },
  { property: "rotation", label: "旋转", unit: "°", min: -360, max: 360, step: 1, factor: 1 },
  { property: "opacity", label: "不透明度", unit: "%", min: 0, max: 100, step: 1, factor: 100 },
  { property: "gain", label: "音量", unit: "%", min: 0, max: 400, step: 1, factor: 100 },
];


/** Rectangle and ellipse masks keyframe their own box; values stay in the mask's normalized units. */
export const MASK_ANIM_FIELDS: { property: MaskProperty; label: string; unit: string; min: number; max: number; step: number; factor: number; field: "center_x" | "center_y" | "width" | "height" | "rotation" | "feather" }[] = [
  { property: "mask_x", label: "遮罩中心 X", unit: "%", min: 0, max: 100, step: 1, factor: 100, field: "center_x" },
  { property: "mask_y", label: "遮罩中心 Y", unit: "%", min: 0, max: 100, step: 1, factor: 100, field: "center_y" },
  { property: "mask_width", label: "遮罩宽度", unit: "%", min: 1, max: 200, step: 1, factor: 100, field: "width" },
  { property: "mask_height", label: "遮罩高度", unit: "%", min: 1, max: 200, step: 1, factor: 100, field: "height" },
  // 1.165: 单位是度、factor 1 —— 这条曲线在人眼前就是那个屏幕角，不是一套比例。
  { property: "mask_rotation", label: "遮罩角度", unit: "°", min: -360, max: 360, step: 1, factor: 1, field: "rotation" },
  // 1.259: 软边也是百分数，但它不是 CSS 量能表达的量——斜坡烘在引擎那张板里，所以这一条
  // 曲线走的是按窗换图那一路（与角度同族），不是 `--mask-*` 那种连续量。
  { property: "mask_feather", label: "遮罩羽化", unit: "%", min: 0, max: 100, step: 1, factor: 100, field: "feather" },
];

/** Any non-inverted mask can be keyframed; a free-form outline only moves (see `maskAnimFields`). */
export const canAnimateMask = (mask?: ShapeMask | null): mask is ShapeMask =>
  Boolean(mask && !mask.inverted);

/** The curves a mask of this shape actually has: a path has no size, only a centre. */
export const maskAnimFields = (mask?: ShapeMask | null, caps?: Capabilities | null) => {
  if (!mask) return [];
  // 判断只在引擎那一处（`Clip.mask_animation_problem`），这里只翻成「这一行摆不摆出来」。
  // 1.165：角度那一行只在这一版引擎报了 `mask_rotation_curves` 时出现——不然是给人在曲线上
  // 写一条必被拒的针。路径遮罩整个没有它：轮廓自己带形状，没有盒可转。
  // 1.166：转过角度的盒也能给宽/高打针了——那张等比图改成每窗一张、各自带自己的角度与边，
  // 所以拧不出别的样子；这一版引擎没报 `mask_rotation_size_curves` 时仍然只给中心两行，
  // 摆上去就是一条老引擎会点名拒绝的曲线。
  const curves = Boolean(caps?.features.mask_rotation_curves);
  const sizeCurves = Boolean(caps?.features.mask_rotation_size_curves);
  // 1.259：软边那一行也只在这一版引擎报了开关时出现——它烘在板子里，老引擎没有这张窗表。
  const featherCurves = Boolean(caps?.features.mask_feather_curves);
  const moveOnly = mask.shape === "path" || (Boolean(mask.rotation) && !sizeCurves);
  return MASK_ANIM_FIELDS.filter((row) => row.property === "mask_rotation"
    ? curves && mask.shape !== "path"
    : row.property === "mask_feather"
      ? featherCurves && mask.shape !== "path"
      : !moveOnly || row.property === "mask_x" || row.property === "mask_y");
};

/**
 * 1.243：播放头正落在某一枚框点上时，卡片里那五个数说的就是**这一枚**。
 * 引擎自 1.238 起，这块盒子一旦有框点就不再读静止值（`extra_box_at` 的第一行），
 * 所以停在一枚框点上却显示静止值，屏幕上的数与执行的那个数不是一回事；
 * 改它也不会有任何变化。停在任何一枚框点之外时交回 `undefined`，卡片仍显示静止值——
 * 它此刻的身份是「下一次打点会记下的那五个数」，界面上那句话也得这么说。
 * 选择只在这一处：检查器不自己 `find`，门禁也照这一句验。
 */
export const boxKeyAt = (mask: ShapeMask, at: number): MaskBoxKey | undefined =>
  (mask.keys ?? []).find((key) => key.at_ticks === at);

/**
 * 1.247：框点可以落在两帧之间——引擎只查范围与次序（`MASK_KEY_RANGE` / `MASK_KEY_CLASH`），
 * Agent 写进来的 `at_ticks` 不必对齐帧。检查器的播放头平时按帧取整，于是点开这样一枚框点的
 * 时刻（`playhead.set` 精确落在它的 tick 上）时，按取整后的帧去找就找不到它。
 * 两把尺子一起问：**播放头此刻的原刻度优先**，其次才是取整到的那一帧——前者让「点开哪一枚」
 * 与「卡片改哪一枚」是同一枚，后者保留平常拖播放头时对整帧框点的识别。
 */
export const boxKeyForPlayhead = (
  mask: ShapeMask,
  exact: number,
  frameTick: number,
): MaskBoxKey | undefined => boxKeyAt(mask, exact) ?? boxKeyAt(mask, frameTick);

/** Label lookup for the keyframe list, which mixes effect and mask properties. */
/** 插值的名字也只从一张表出去：曲线编辑器的两个下拉、轮廓帧那一行、任何将来要说「这一帧怎么过渡」的地方。 */
export const INTERPOLATIONS = { linear: "线性", ease: "缓入缓出", hold: "保持", bezier: "贝塞尔" } as const;

/** 1.257：贝塞尔那一档的四个数——名字、那条带与默认柄只在这里写一次。曲线编辑器那四格与
 *  检查器框点行那四格读的都是这张表；谁再抄一份数字，壳检就红在「有第二处」。 */
export const BEZIER_AXES = [
  { axis: "x1", label: "出点时间", min: 0, max: 1 },
  { axis: "y1", label: "出点数值", min: -4, max: 4 },
  { axis: "x2", label: "入点时间", min: 0, max: 1 },
  { axis: "y2", label: "入点数值", min: -4, max: 4 },
] as const;
export const bezierBand = (axis: string): readonly [number, number] => {
  const row = BEZIER_AXES.find((item) => item.axis === axis);
  return [row?.min ?? 0, row?.max ?? 1];
};
export const DEFAULT_BEZIER: Bezier = { x1: 1 / 3, y1: 0, x2: 2 / 3, y2: 1 };

/** 1.257：框点那一格能选哪几种缓动，只由引擎交下来的那张名单说（界面不许自己滤掉某一种）。
 *  没回这个字段的旧引擎就是它当时认的那三种——这是唯一的兜底，不是第二份判断。 */
export const maskBoxInterpolations = (caps?: Capabilities | null): Keyframe["interpolation"][] =>
  caps?.mask_box_interpolations?.length
    ? caps.mask_box_interpolations
    : ["linear", "hold", "ease"];

export const FIELD_LABEL: Record<string, string> = Object.fromEntries([
  ...[...EFFECT_FIELDS, ...MASK_ANIM_FIELDS].map((field) => [field.property, field.label]),
  ["blur", "柔焦"],
  // 1.123：清晰的两颗旋钮进了可打关键帧那一族，名字也从这里出去——曲线编辑器、检查器、时间线
  // 针的悬停说明都读这一张表，契约里那两条 id 不再当用户界面用。
  ["sharpen", "清晰"],
  ["sharpen_radius", "清晰半径"],
] as [string, string][]);

/** 1.260：条上道号按什么次序排，只由这张名字表的键序说。以前 `needleRows` 按工程里那一串数组
 *  第一次出现的顺序排，而 `timeline.py` 在每条 `keyframe.set` / `keyframe.remove` 收尾都把那一串
 *  按 (属性, 刻度) 重排——Agent 改一条曲线，人看到的另一条针就换了道（1.259 那条扫描腿量到的正是
 *  这件事：同一份夹具，编辑前 x 被道数挤掉，编辑后 x 画到片段左缘、墨压在邻段的时长上）。
 *  表里没有的名字（第二路画面那种复合键）排在有名字的之后，彼此仍按第一次出现——稳定排序把这句
 *  写成一处算术，而不是两处默契。 */
export const PROPERTY_RANK: Record<string, number> = Object.fromEntries(
  Object.keys(FIELD_LABEL).map((property, index) => [property, index]),
);

/** 1.99：柔焦那条曲线也能在曲线编辑器里看与拖。上限与检查器那一行同源（`blurMaxPercent`：
 *  引擎下发的比例上限与实测过的像素带按当前画幅高折算取小），所以这里不会给出一条
 *  画得出、导出会拒的斜坡；老引擎不回 `blur_keyframes` 就没有这条曲线。
 *  1.123：清晰的两颗旋钮同一条路，上限也同源（`sharpenLimits`）。它们不是两条各走各的曲线——
 *  导出把这两个数编进**同一张**窗表（`animation.sharpen_schedule`），所以要么一起出现，要么都不出现。 */
export const spatialAnimFields = (caps: Capabilities | null, frameHeight: number) => {
  const max = blurMaxPercent(caps, frameHeight);
  const limits = sharpenLimits(caps, frameHeight);
  const rows: {
    property: SpatialProperty; label: string; unit: string; min: number; max: number; step: number; factor: number;
  }[] = [];
  if (caps?.features.blur_keyframes && max > 0) {
    rows.push({ property: "blur", label: FIELD_LABEL.blur, unit: "%", min: 0, max, step: 0.5, factor: 100 });
  }
  if (caps?.features.sharpen_keyframes && limits.amount > 0) {
    rows.push({ property: "sharpen", label: FIELD_LABEL.sharpen, unit: "%", min: 0, max: limits.amount * 100, step: 5, factor: 100 });
    rows.push({ property: "sharpen_radius", label: FIELD_LABEL.sharpen_radius, unit: "%", min: 0, max: limits.radiusPercent, step: 0.25, factor: 100 });
  }
  return rows;
};

/** Every curve the editor can offer, in one vocabulary. */
export type CurveField =
  | (typeof EFFECT_FIELDS)[number]
  | (typeof MASK_ANIM_FIELDS)[number]
  | ReturnType<typeof spatialAnimFields>[number];

/** 曲线的起笔就是检查器里现在的那个数：新点按它落，纵轴按它定标。柔焦是 1.99 才进编辑器的，
 *  这一处若只读那六个标量属性，滑杆推到 12% 再按「播放头添加」写的会是 0——用户看到的是曲线把柔焦关了。 */
export const curveBase = (clip: Pick<Clip, "effects" | "mask">, field: CurveField): number =>
  "field" in field
    ? clip.mask?.[field.field] ?? 0
    : (clip.effects ?? DEFAULT_EFFECTS)[field.property as keyof Effects] ?? 0;

/** The three curves the stabiliser writes, plus rotation — the same set the engine guards. */
const STABILIZED = ["x", "y", "rotation", "scale"] as const;

/**
 * 「画面稳定」按不下去的原因，`null` 表示可以按。界面和引擎守同一条判断，所以点下去不会拿到
 * 另一套说法：带变速曲线的片段找不到一个能用的采样步长（恒定速率已经按播放的步长量，所以能稳），
 * 已经K过位移/缩放/旋转的片段会被再抵消一遍——稳定是把纠偏叠加在片段已有的动画上，而引擎认不出
 * 哪一条是它上一次写的，只能让人先把它清掉。
 */
export const stabilizeBlocked = (clip: Clip): string | null => {
  if (clip.speed_curve?.length) {
    return "带变速曲线的片段还不能稳定：抖动要按播放的步长量，速率一直在变就没有那个步长。把这段改成恒定速率（例如 100%）再稳定。";
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


/** 整轨分析按钮对这条轨可用吗？空轨按下去只会拿到引擎的点名拒绝（1.79 起 `NOT_FOUND`）。
 *  按了只会弹错，就不该是可按的：按钮要么按得出东西，要么说清为什么按不了。 */
export const EMPTY_TRACK_HINT =
  "这条轨上还没有片段：先把素材拖上时间线；如果片段都进了预合成，从时间线上方的面包屑进去那条合成再操作。";

export function trackToolBlocker(trackId: string, clips: Clip[]): string | null {
  return clips.some((clip) => clip.track_id === trackId) ? null : EMPTY_TRACK_HINT;
}

/** 一次遮罩跟踪该量几帧。上下限都是引擎的数（`capabilities.limits.track_min_frames` /
 *  `track_max_frames`），界面不自己数一个：1.87 之前这里写死过 300，于是十二秒以上的片段只量了
 *  前十秒，提示却说「导出使用同一份关键帧」。这里只决定「这一次敢要几帧」；引擎还会按这条片段的
 *  曲线预算把窗口再收短（一个跟踪点占 2 或 4 条曲线），那一段由回复里的 `budget_frames` 说清，
 *  界面无权自己猜。`fromHead` 只用来决定那句出路：从片段开头重跟时，挪播放头是没用到的。 */
export function trackWindow(
  remainingFrames: number,
  fromHead: boolean,
  limits?: { track_min_frames?: number; track_max_frames?: number }
): { frames: number; blocked: string | null } {
  const min = limits?.track_min_frames ?? 2;
  const max = limits?.track_max_frames ?? 900;
  if (remainingFrames < min) {
    return {
      frames: min,
      blocked: `这里只剩 ${remainingFrames} 帧，一次跟踪至少要看 ${min} 帧才能量出移动的方向。${
        fromHead ? "把这段切得长一点，或直接在曲线编辑器里给遮罩中心加两个关键帧。" : "把播放头往前挪一些再点。"
      }`,
    };
  }
  return { frames: Math.min(max, remainingFrames), blocked: null };
}

/** 一组遮罩跟踪的目标：一条片段一份窗口，三个旋钮整组共用（它们本来就是应用偏好）。 */
export type TrackTarget = {
  clipId: string; fromTicks: number; frames: number; merge: boolean;
  reacquire?: boolean; maxGapFrames?: number; scale?: boolean; rotate?: boolean;
};

/** 一次跟踪一组遮罩。每段各按自己的长度决定「量几帧」，判断仍然只在 `trackWindow` 里，这里只是把它
 *  逐段调一遍——「这一段太短」那句话和单段完全一样，不存在第二套说法。
 *  播放头不参与：一组的语义就是「把这几段各自从片段开头量到量得完的地方」。若跟着播放头，选中两段时
 *  它只落在其中一段里，另一段会被判成「只剩 0 帧」，那是在挑时段而不是在跟一组。
 *  段数的天花板是引擎的数（`capabilities.limits.track_max_targets`），界面不自带一个：超了就点名要求
 *  少选几段，而不是偷偷截断——截断会让人以为剩下那几段也跟过了。 */
export function trackGroup(
  clips: { id: string; duration_ticks: number }[],
  perFrame: number,
  limits?: { track_min_frames?: number; track_max_frames?: number; track_max_targets?: number },
  knobs?: { reacquire: boolean; maxGapFrames: number; scale: boolean; rotate?: boolean }
): { targets: TrackTarget[]; blocked: string | null } {
  const ceiling = limits?.track_max_targets ?? 8;
  if (clips.length > ceiling) {
    return {
      targets: [],
      blocked: `一次最多跟 ${ceiling} 段（这个数由引擎下发），这次选了 ${clips.length} 段。少选几段再点，或者分几次跟。`,
    };
  }
  const targets: TrackTarget[] = [];
  for (const clip of clips) {
    const window = trackWindow(Math.floor(clip.duration_ticks / perFrame), true, limits);
    if (window.blocked) {
      return { targets: [], blocked: `第 ${targets.length + 1} 段量不动：${window.blocked}` };
    }
    targets.push({
      clipId: clip.id,
      fromTicks: 0,
      frames: window.frames,
      merge: true,
      ...(knobs
        ? {
            reacquire: knobs.reacquire,
            maxGapFrames: knobs.maxGapFrames,
            scale: knobs.scale,
            ...(knobs.rotate === undefined ? {} : { rotate: knobs.rotate }),
          }
        : {}),
    });
  }
  return { targets, blocked: null };
}


/** 遮罩跟踪的三个旋钮：挡住最多猜几帧、要不要在整幅画面上重找、遮罩随远近缩放。
 *  它们是「下一次请求怎么发」的默认值，不是工程数据——写进工程要经 `updateProjectMeta`，那会每
 *  点一次涨一个 revision 并清空撤销栈，等于拿用户的编辑历史换一个勾选。所以它们跟着应用走
 *  （与代理宽度同一处），换一个工程、重开一次窗口都还在。天花板只由引擎的 `capabilities.limits`
 *  给：存着的数比这台引擎的天花板大，读出来就夹回去。 */
const KNOB_KEYS = { gap: "agentcut.trackGap", sweep: "agentcut.trackSweep", scale: "agentcut.trackScale", rotate: "agentcut.trackRotate" };

export type TrackingKnobs = { gap: number; sweep: boolean; scale: boolean; rotate: boolean };

export function readTrackingDefaults(fallbackGap: number, gapCeiling: number): TrackingKnobs {
  const clamp = (value: number) => Math.max(0, Math.min(Math.round(value), gapCeiling));
  try {
    // 没存过与存了个 0 是两件事：`Number(null)` 恰好是 0，直接拿去判范围会把「一次都不猜」
    // 当成空存储的默认。先按字符串判缺失，再换算。
    const raw = localStorage.getItem(KNOB_KEYS.gap);
    const stored = raw === null || raw === "" ? Number.NaN : Number(raw);
    const gap = Number.isFinite(stored) && stored >= 0 ? clamp(stored) : clamp(fallbackGap);
    // 没存过就是开着的（引擎的默认就是 true），所以只有明确的 "0" 才算关。
    return {
      gap,
      sweep: localStorage.getItem(KNOB_KEYS.sweep) !== "0",
      scale: localStorage.getItem(KNOB_KEYS.scale) !== "0",
      // 1.271：旋转估计默认关——它比平移贵，且只在主体真的转时才该开。明确的 "1" 才算开。
      rotate: localStorage.getItem(KNOB_KEYS.rotate) === "1",
    };
  } catch {
    return { gap: clamp(fallbackGap), sweep: true, scale: true, rotate: false };
  }
}

/** 三个旋钮的初值与它们各自的天花板。兜底数字只许写在这里一次：单段面板与多选面板都从这里拿，
 *  否则「引擎没回这个字段时该当多少」就有了两个说法。传进来的仍是 capabilities 那一份数。 */
export function trackingKnobs(limits?: {
  track_gap_default?: number; track_max_gap_frames?: number;
}): TrackingKnobs & { gapCeiling: number } {
  const gapCeiling = limits?.track_max_gap_frames ?? 240;
  return { ...readTrackingDefaults(limits?.track_gap_default ?? 60, gapCeiling), gapCeiling };
}

export function rememberTrackingDefaults(knobs: Partial<TrackingKnobs>): void {
  try {
    if (knobs.gap !== undefined) localStorage.setItem(KNOB_KEYS.gap, String(knobs.gap));
    if (knobs.sweep !== undefined) localStorage.setItem(KNOB_KEYS.sweep, knobs.sweep ? "1" : "0");
    if (knobs.scale !== undefined) localStorage.setItem(KNOB_KEYS.scale, knobs.scale ? "1" : "0");
    if (knobs.rotate !== undefined) localStorage.setItem(KNOB_KEYS.rotate, knobs.rotate ? "1" : "0");
  } catch {
    /* 存不下就这一次生效，下次重开回到引擎给的默认 */
  }
}

/** 自动调色的三道门，一次算清：按了只会弹错的按钮不该亮着（1.82 立下的规矩）。
 *  每句都给出真能走通的出路：换到画面轨、等素材就绪、或直接在色阶里手动填两个点。 */
export const AUTO_GRADE_NOT_PICTURE =
  "自动调色要先看得见画面：只有素材库已校验过的视频或图片能量出自己的黑场与白场。把这段素材放到画面轨上，或者在色阶节点里自己填黑场、白场。";
export const AUTO_GRADE_NO_ENGINE =
  "引擎现在还没接上素材库，读不到这段素材的画面。等标题栏显示素材就绪后再按一次，或者先在色阶里手动填两个输入点。";

export function autoGradeBlocker(
  clipKind: string | undefined,
  assetKind: string | undefined,
  trackKind: string | undefined,
  engineReady: boolean
): string | null {
  // 没有片段、文字层、音频素材都不在「有画面可量」的范围里；素材轨也不是画面轨就渲染不出帧。
  if (clipKind === undefined || clipKind === "text") return AUTO_GRADE_NOT_PICTURE;
  if (!engineReady) return AUTO_GRADE_NO_ENGINE;
  const measurable = assetKind === "video" || assetKind === "image";
  if (!measurable || trackKind !== "video") return AUTO_GRADE_NOT_PICTURE;
  return null;
}

/** 预览里的擦除露出的是空间，不是光。导出在 alpha 上算一条宽 `feather` 的斜坡
 *  （`transitions.wipe_expression`），浏览器只能给一条硬边，所以硬边取那条斜坡的**中点**：
 *  `progress*(1+feather) - feather/2`。进度、轴、方向、羽化宽全部读引擎下发的数——
 *  界面不许自备第二张「名字→方向」的表，也不许自己写 0.02。 */
export function wipeClipPath(
  wipe: Pick<WipeChannel, "axis" | "flipped" | "invert" | "feather">,
  progress: number
): string {
  const edge = Math.max(0, Math.min(1, progress * (1 + wipe.feather) - wipe.feather / 2));
  // 非反向时露出的是行进方向的那一头；反向（把补集交给另一层）就是对面那一头。
  const coversStart = wipe.flipped === wipe.invert;
  const percent = (value: number) => `${Math.round(value * 10000) / 100}%`;
  const hiddenStart = coversStart ? 0 : edge;
  const hiddenEnd = coversStart ? 1 - edge : 0;
  return wipe.axis === "x"
    ? `inset(0 ${percent(hiddenEnd)} 0 ${percent(hiddenStart)})`
    : `inset(${percent(hiddenStart)} 0 ${percent(hiddenEnd)} 0)`;
}

export type FadeProperty = "opacity" | "gain";
export type FadeSide = "in" | "out";

/** 这段素材能淡什么：画面、音量，或两者。引擎只有一条规矩（音频素材没有不透明度可淡，按
 *  `INVALID_FADE` 点名 `asset_kind` 拒），但界面此前在 Inspector 里各算一遍。时间线新加的淡角柄
 *  必须按同一个判断决定拖哪一头，否则就会在一个按下去必定被拒的属性上给出手柄。 */
export function fadeProperties(clip: Clip, asset?: Asset | null): FadeProperty[] {
  const picture = asset?.kind !== "audio";
  const sound = asset?.kind === "audio" || Boolean(asset?.verified?.has_audio) && clip.embedded_audio !== false;
  const list: FadeProperty[] = [];
  if (picture) list.push("opacity");
  if (sound) list.push("gain");
  return list;
}

/** 片段自己那两条边上的淡入／淡出长度（tick）。没有 fade 记录就是全 0——1.90 之前淡是写成关键帧的，
 *  那些老片段照旧按写在曲线里的淡渲染，只是这个读数看不到它们（帮助页写明了这一条）。 */
export function fadeWindows(clip: Clip): Record<FadeProperty, Record<FadeSide, number>> {
  const fade = clip.fade;
  return {
    opacity: { in: fade?.opacity_in_ticks ?? 0, out: fade?.opacity_out_ticks ?? 0 },
    gain: { in: fade?.gain_in_ticks ?? 0, out: fade?.gain_out_ticks ?? 0 },
  };
}

/** 这一头还能要多少 tick：片段长度减去对面那头已经占掉的。
 *  检查器那两行与时间线上的淡角柄都读这一个数——额度从头到尾只有一处来源。 */
export function fadeRoom(clip: Clip, property: FadeProperty, side: FadeSide): number {
  const windows = fadeWindows(clip)[property];
  const other = side === "in" ? windows.out : windows.in;
  return Math.max(0, clip.duration_ticks - other);
}

/** 时间线上拖淡角柄：指针离开这条边多远，这一头就淡多久。
 *  按时间线自己的网格对齐，上限读 `fadeRoom`，所以拖不出一条引擎必定拒绝的淡；
 *  拖回边上（或网格把它对齐到 0）就是取消这一头。 */
export function fadeDragTicks(
  clip: Clip,
  property: FadeProperty,
  side: FadeSide,
  rawTicks: number,
  quantum: number
): number {
  const step = quantum > 0 ? quantum : 1;
  const aligned = Math.round(rawTicks / step) * step;
  return Math.max(0, Math.min(aligned, fadeRoom(clip, property, side)));
}

/** 淡的形状：界面列的必须是引擎 `capabilities.fade_shapes` 那张表（与转场种类同一个规矩）。
 *  老引擎不回它就是空数组——那时这一行根本不出现，界面不许自己发明四个名字。 */
export function fadeShapeChoices(caps?: { fade_shapes?: { id: string; label: string }[] } | null): { id: FadeShape; label: string }[] {
  return (caps?.fade_shapes ?? []).filter((item) => FADE_SHAPE_IDS.includes(item.id as FadeShape)) as { id: FadeShape; label: string }[];
}

const FADE_SHAPE_IDS: FadeShape[] = ["linear", "ease_in", "ease_out", "ease_in_out"];

/** 这一头现在用的形状：引擎没下发就是缓入缓出（那正是 1.95 之前唯一的形状）。 */
export function fadeShape(clip: Clip, property: FadeProperty): FadeShape {
  return clip.fade?.[property === "opacity" ? "opacity_shape" : "gain_shape"] ?? "ease_in_out";
}

export type FadeShape = "linear" | "ease_in" | "ease_out" | "ease_in_out";

/** 「搬成边窗口」这颗按钮该不该亮。它判的是**必要条件**，不是引擎那条规则：这条属性上有关键帧、
 *  且其中某个 0 值正好落在片段的一条边上——不满足就一定搬不动，所以按钮不该亮着（1.82 的规矩）。
 *  满足也不保证搬得动（夹了别的点、起点不是 0、形状不是缓入缓出、已经是窗口），那由引擎点名拒绝，
 *  界面不重复实现第二套判断。 */
export function fadeAdoptHint(clip: Clip, property: FadeProperty): boolean {
  const keys = (clip.keyframes ?? []).filter((key) => key.property === property);
  if (keys.length < 2) return false;
  const head = clip.animation_offset_ticks ?? 0;
  const tail = head + clip.duration_ticks;
  const at = (value: number) => keys.some((key) => Math.abs(key.value) < 1e-9 && key.at_ticks === value);
  return at(head) || at(tail);
}

/**
 * 引擎搬不动淡时交回的那句原因（`timeline._fade_adoption` 的返回值）→ 中文说法。
 *
 * 键就是引擎那句原话，一个字都不许多：`tests/fadebatch_check.py` 会把 `_fade_adoption` 与整轨规划
 * 里出现过的每条 reason 与这张表对起来，缺一条就红。加一张表而不是直接印英文，是因为整轨报告一次
 * 列几十条，人读的是「哪几段、为什么」，不是日志。
 */
export const FADE_ADOPT_REASONS: Record<string, string> = {
  "there are no keyframes on this property": "这条属性上没有关键帧",
  "this property already carries edge windows": "这一头已经是边上的窗口了",
  "some keyframes sit outside the clip": "有关键帧落在片段范围之外",
  "the ramp does not run between 0.0 and the resting value": "斜坡不是从 0 走到这条属性的静止值",
  "the ramp is not the eased shape a fade used": "斜坡不是老淡那种缓动形状",
  "the clip starts faded but never comes back": "开头是淡的，但从来没有回到静止值",
  "the clip ends faded but never started from full": "结尾是淡的，但没有从静止值开始",
  "neither ramp starts at an edge of the clip": "两头都没从片段的边上出发",
  "other keyframes are mixed into the fade": "淡里夹着别的关键帧",
  "audio has no opacity to fade": "音频片段没有画面可淡",
};

/** 整轨搬完之后该说什么。只说数与原因，不替引擎判断。 */
export function fadeAdoptSummary(plan: {
  adopted: number;
  skipped: number;
  clips: { clip_id: string; property: string; skipped?: string }[];
}): { title: string; detail: string } {
  const blocked = plan.clips.filter((item) => item.skipped);
  if (!plan.adopted) {
    if (!blocked.length) {
      return { title: "这条轨没有写成关键帧的淡", detail: "每条淡都已经在自己的两条边上，两个数字读的就是它们。" };
    }
    return {
      title: "这条轨没有能搬的淡",
      detail: `${blocked.length} 段有淡但搬不动：` + blocked.slice(0, 3)
        .map((item) => `${item.clip_id}（${FADE_ADOPT_REASONS[item.skipped ?? ""] ?? "引擎没说原因"}）`)
        .join("、") + (blocked.length > 3 ? `，还有 ${blocked.length - 3} 段` : "") + "。",
    };
  }
  return {
    title: `搬了 ${plan.adopted} 段淡`,
    detail: blocked.length
      ? `另有 ${blocked.length} 段搬不动：${FADE_ADOPT_REASONS[blocked[0].skipped ?? ""] ?? blocked[0].skipped}。画面一个像素都不变。`
      : "画面一个像素都不变：搬的就是原来那条缓入缓出的斜坡。",
  };
}

/** 一次淡角柄拖动的落库单位。`clipId` 带着走，是因为「这一组」不再只有被拖的那一条。 */
export type FadeOp = { clipId: string; property: FadeProperty; side: FadeSide; ticks: number };

/** 1.192：那一层在画面上盖哪一块——导出与预览共用的就这一条式子。
 *  视图不许在别处再抄一遍：抄一份就会有「画面上是这样、文件里是那样」的那一天。
 *  坐标按**画面框**说（与引擎 `layer_rect` 同一口径）：`scale` 1 = 铺满画面框，
 *  `offset` 0 = 层心在画面中心，±1 = 层心挪到那一边的边外。
 *  1.203：`rotation` 是度数，**顺时针为正**（量过：这台 FFmpeg 的 `rotate=a='θ*PI/180'`
 *  把左半边送到上边，与 CSS 的 `rotate(θdeg)` 同一边，所以两腿取同一个数、不取反）。
 *  转动绕元素自己的中心，而引擎的 `layer_rect` 交回的正是「中心不动的那只外接框」；
 *  出界那半由容器裁掉，与导出裁到交付帧同一件事。0 就是不给 `transform`——
 *  那种层的 DOM 与 1.202 一字不差。 */
export const layerStyle = (offsetX: number, offsetY: number, scale: number, rotation = 0) => ({
  width: `${scale * 100}%`,
  height: `${scale * 100}%`,
  left: `${(0.5 + offsetX) * 100 - scale * 50}%`,
  top: `${(0.5 + offsetY) * 100 - scale * 50}%`,
  ...(rotation ? { transform: `rotate(${rotation}deg)` } : {}),
});

/** 引擎那份窗表换成浏览器动画帧：每一窗一格、`easing` 用的就是引擎给的那个串，
 *  四个数一个都不自己算。没有窗（一枚针都没有）就交回 null，那一行走上面那条静态式子。
 *  1.198：`opacity` 也从窗表来——层自己会淡，静态那一个 `mix` 只在没有针的时候说话。 */
export function layerFrames(windows: LayerWindow[] | null | undefined) {
  if (!windows?.length) return null;
  return windows.map((point) => ({
    ...layerStyle(point.offset_x, point.offset_y, point.scale),
    opacity: point.mix,
    // 1.204：每一帧都自己写一遍 transform，**包括 0°**。少写一帧，那一格就会回落到元素行内
    // 那一个静态转角（针与静态是两个不同的数），阶梯就不是引擎那一张窗表了。
    transform: `rotate(${point.rotation ?? 0}deg)`,
    offset: point.offset,
    easing: point.easing,
  }));
}

/** 界面说到这一层能动的那四个数时念的是中文名：唯一的表，键与引擎下发的
 *  `grade_limits.layer_key_props` 逐字对齐（`tests/desktop_layerkey_check.ts` 钉这一条）。 */
/** 1.205：那一层的针进得了动画曲线编辑器。这里只说**显示**的事（单位、步长）：
 *  能动的是哪几个数、各自能到几，全听引擎（`grade_limits.layer_key_props` 与 `layer_key_bands`）。
 *  步长与检查器那几颗框同一档（5%、5°），所以从滑杆推到的数与在曲线上落的点是同一格。 */
export const LAYER_CURVE_UNITS: Record<LayerProperty, { unit: string; factor: number; step: number }> = {
  offset_x: { unit: "%", factor: 100, step: 5 },
  offset_y: { unit: "%", factor: 100, step: 5 },
  scale: { unit: "%", factor: 100, step: 5 },
  mix: { unit: "%", factor: 100, step: 5 },
  rotation: { unit: "°", factor: 1, step: 5 },
};

/** 曲线列表里那一行的身份：`property` 是**复合键**（第几层·哪个数），因为 `scale`、`rotation`
 *  这两个名字与普通曲线撞名——不撞开就会有两行选到同一条数组上。`key` 才是引擎认的那个属性名。 */
export type LayerCurveField = {
  property: string;
  key: LayerProperty;
  layer: number;
  label: string;
  unit: string;
  min: number;
  max: number;
  step: number;
  factor: number;
};

/** 有哪几层、每层能动哪几个数，一次列出来：层的顺序与 `animation.layer_nodes`、清单、编译
 *  那三处是同一份（链里启用的那几层，按链里的顺序数）；名单与量程缺一份就是老引擎，一行都不出现。 */
export function layerCurveFields(
  clip: Clip | undefined,
  props: string[] | undefined,
  bands: Record<string, [number, number]> | undefined,
): LayerCurveField[] {
  if (!clip || !props?.length || !bands) return [];
  const layers = (clip.color?.grade ?? []).filter(
    (node) => node.kind === "layer" && node.enabled,
  );
  const out: LayerCurveField[] = [];
  layers.forEach((node, layer) => {
    props.forEach((prop) => {
      const band = bands[prop];
      const unit = LAYER_CURVE_UNITS[prop as LayerProperty];
      if (!band || !unit) return;
      out.push({
        property: layerNeedleProperty(layer, prop as LayerProperty),
        key: prop as LayerProperty,
        layer,
        label: `第 ${layer + 1} 层 · ${LAYER_KEY_LABEL[prop] ?? prop}`,
        unit: unit.unit,
        min: band[0] * unit.factor,
        max: band[1] * unit.factor,
        step: unit.step,
        factor: unit.factor,
      });
    });
  });
  return out;
}

/** 起笔与纵轴定标用的那一个数：这一层在检查器里现在写着几，就是几（与普通曲线的 `curveBase` 同理）。 */
export function layerCurveBase(clip: Clip, field: LayerCurveField): number {
  const node = clip.color?.grade?.filter((item) => item.kind === "layer" && item.enabled)[field.layer];
  const value = node && (node as unknown as Record<string, number>)[field.key];
  return typeof value === "number" ? value : 0;
}

/** 层的针在针道里的身份：一条 (层, 属性) 就是一道曲线。拼法与 `layerCurveFields` 里那个复合键
 *  同出一处（`layer${layer}:${prop}`），所以曲线编辑器选中的那道与时间线上画出来的那枚是同一个名字。 */
export const layerNeedleProperty = (layer: number, key: LayerProperty) => `layer${layer}:${key}`;

/** 写一层针的口子只需要两个数：第几层、哪个数。曲线编辑器交来的是完整的 `LayerCurveField`
 *  （还带标签与量程），时间线交来的是这一枚针自己——两处共用同一个实现，不另开第二份折刻度。 */
export type LayerNeedleField = { layer: number; key: LayerProperty };

/** 一枚层的针：`at_ticks` 是片段本地的（画在条上的位置就是它），`field` 是写回去要的那两个数。 */
export type LayerNeedle = { field: LayerNeedleField; property: string; at_ticks: number; value: number };

/** 这一颗片段上**每一枚**层的针：刻度折成本片段自己的（画在条上的位置就是它），层的顺序与曲线
 *  编辑器同源（链里启用的那几层，按链里的顺序数），窗口夹法与 `clip.keyframes` 那一条同一个口径。 */
export function layerNeedles(clip: Clip): LayerNeedle[] {
  const offset = clip.animation_offset_ticks ?? 0;
  const out: LayerNeedle[] = [];
  let layer = -1;
  (clip.color?.grade ?? []).forEach((node) => {
    if (node.kind !== "layer" || !node.enabled) return;
    layer += 1;
    (node.keys ?? []).forEach((key) => {
      if (key.at_ticks < offset || key.at_ticks > offset + clip.duration_ticks) return;
      out.push({ field: { layer, key: key.property }, property: layerNeedleProperty(layer, key.property), at_ticks: key.at_ticks - offset, value: key.value });
    });
  });
  return out;
}

/** 这一层现在有的那批针（片段本地刻度，含这一层全部属性）：拖一枚要把整层交回那条 `clip.grade`，
 *  所以读的是整层而不是一个属性——折刻度与 `layerKeysOf` 写回去的那一次正好互为逆。 */export function layerKeysRead(clip: Clip, field: LayerNeedleField): LayerKeyframe[] {
  const offset = clip.animation_offset_ticks ?? 0;
  const layers = (clip.color?.grade ?? []).filter((node) => node.kind === "layer" && node.enabled);
  const node = layers[field.layer];
  const keys = node && node.kind === "layer" ? node.keys ?? [] : [];
  return keys.map((key) => ({ ...key, at_ticks: key.at_ticks - offset }));
}

/** 把「这一串新针」折回链里的**唯一一处**：刻度在这里加回 `animation_offset_ticks`
 *  （读的时候引擎折的那一次在这里还原），命令仍是那一条 `clip.grade`——不新增命令、不新增规则。 */
export function layerKeysOf(clip: Clip, field: LayerNeedleField, keys: LayerKeyframe[]): Clip {
  const offset = clip.animation_offset_ticks ?? 0;
  // 交回来的这一串是「那一层的这一个数」的全部针；**同一层别的数的针原样留着**。
  // 1.204~1.207 这一处是把整层的针直接覆盖成这一串的，所以在动画曲线上改 rotation 会把 offset_x
  // 那几枚抹掉——那一路只有曲线编辑器一个写口、而它的夹具只有一道曲线，直到 1.208 条上画出两枚
  // 不同数的针才被量出来（真页面：三枚针变两枚，offset_x 那一枚还改了名字）。
  const stamped = keys.map((key) => ({ ...key, property: field.key, at_ticks: key.at_ticks + offset }));
  let seen = -1;
  const grade = (clip.color?.grade ?? []).map((node) => {
    if (!(node.kind === "layer" && node.enabled)) return node;
    seen += 1;
    if (seen !== field.layer) return node;
    const others = (node.keys ?? []).filter((key) => key.property !== field.key);
    return { ...node, keys: [...others, ...stamped].sort((a, b) => a.at_ticks - b.at_ticks) };
  });
  return { ...clip, color: { ...(clip.color ?? {}), grade } } as Clip;
}

/** 草稿预览与写入共用同一份链：界面不许自己把那串针再折一次刻度。 */
export function layerKeyCommand(clip: Clip, field: LayerNeedleField, keys: LayerKeyframe[]): Command {
  const next = layerKeysOf(clip, field, keys);
  return { op: "clip.grade", clip_id: clip.id, grade: next.color?.grade };
}

/** 那一层现在这一格执行的是几：读引擎那份阶梯里「不超过播放头的那一级」。
 *  这不是第二次插值——窗表每级一个常数，界面只是挑已经算好的那一级。 */
export function layerStepAt(graph: { curve: { offset: number; value: number }[] } | null, fraction: number): number | null {
  if (!graph?.curve?.length) return null;
  let value = graph.curve[0].value;
  for (const point of graph.curve) {
    if (point.offset > fraction + 1e-9) break;
    value = point.value;
  }
  return value;
}

/** 界面说到这一层能动的那几个数时念的是中文名：唯一的表，键与引擎下发的
 *  `grade_limits.layer_key_props` 逐字对齐（`tests/desktop_layerkey_check.ts` 钉这一条）。 */
export const LAYER_KEY_LABEL: Record<string, string> = {
  offset_x: "这一层往左右",
  offset_y: "这一层往上下",
  scale: "这一层多大一块",
  mix: "这一层的权重",
  rotation: "这一层转多少度",
};

/** 1.193：容器里那两层谁在下面——`normal` 要把「已调色」放上面。
 *  导出那两步是 `(1-mix)·raw + mix·mode(graded, raw)`，而 FFmpeg 的 `normal` 交回**第一个**输入、
 *  CSS 的 `normal` 交回**上面那一层**：不交换这一档，监视器在 mix=1 会显示原图而不是调完的画。
 *  1.189 为图层量过同一条（那次是编译时换操作数）。判断只写在这里，视图只问一次。 */
export const compositeSwap = (mode: BlendMode) => mode === "normal";

/** 这一级在这一刻画不画：只有引擎那一行的 `motion` 说得出口，视图不许自己问「这段素材是什么」。
 *  `"always"` 是图像（两幅都是解码好的位图）；`"paused"` 是视频——本轮量过：暂停与逐帧时把主画面
 *  那一路拓进 canvas 与导出逐格 0 差，而播放中再开一路解码会把动画帧率打掉一半（rAF 181→94），
 *  所以那一档不画。老引擎不回 `motion` 时这里就是假，宁可少画一层。 */
export const compositeLive = (motion: "always" | "paused" | null | undefined, playing: boolean) =>
  motion === "always" || (motion === "paused" && !playing);

/** 播放头那一格换成引擎那把尺上的数：层的针存的是含 `animation_offset_ticks` 的时钟，
 *  与 `Clip.keyframes` 同一条规矩。折那一次只在这里折——视图里再抄一遍就会抄成两套刻度。 */
export const layerKeyTick = (clip: Clip, ticks: number) =>
  ticks - clip.position_ticks + (clip.animation_offset_ticks ?? 0);

/** 1.98：引擎把柔焦曲线编译成一格一步的窗（`spatial_schedule`），浏览器照同一份点表动画 `filter`。
 *  值仍是「占画面高的比例」，所以单位是 cqh——与导出交给 `gblur=sigma=` 的是同一个数。
 *  没有曲线就返回空数组：那一行走的是静态那条路，界面不自己造第二条规则。 */
export function blurFrames(curve: Curve | null | undefined): { filter: string; offset: number; easing: string }[] {
  return (curve ?? []).map((point) => ({
    filter: `blur(${point.value * 100}cqh)`,
    offset: point.offset,
    easing: point.easing,
  }));
}

/** 一片清晰该画几个 `<filter>`：静态那一份，或者窗表里每一窗一份。判断只写在这里——
 *  预览组件不再自己问「这是静态还是有窗」，两处各问一遍迟早会问出不一样的一张表。 */
export const sharpenFilters = (sharpen: SharpenSpec | null | undefined): SharpenStatic[] =>
  !sharpen ? [] : "windows" in sharpen ? sharpen.windows : [sharpen];

/** 「这一片清晰到底有没有窗」也只问这一次：动画那条路只在有窗的时候才挂上去。 */
export const sharpenSteps = (sharpen: SharpenSpec | null | undefined): SharpenSteps | null =>
  sharpen && "windows" in sharpen ? sharpen : null;

/** 1.123：清晰那一串窗在浏览器里的动画帧。CSS 不能只换共享 filter 串里的一项，所以外层那道
 *  包装整个 `filter` 在「这一窗的 def」与 `none` 之间一格一步地切——`none` 的那几格正是导出
 *  不为它串阶段的零强度窗。数与导出来自同一份窗表（`animation.sharpen_windows`）。 */
export function sharpenFrames(
  curve: SharpenSteps["curve"] | null | undefined,
): { filter: string; offset: number; easing: string }[] {
  return (curve ?? []).map((point) => ({
    filter: point.id ? `url(#${point.id})` : "none",
    offset: point.offset,
    easing: point.easing,
  }));
}

/** 拖一次淡角柄，落库的是「这一组」：被拖的那条 + 与它一起被选中的 + 与它们音画链接的伙伴
 *  （剪映是一起动的，1.91 只淡被拖的那一条是它的半件事）。
 *  每一条按**自己**的长度与**自己**能淡的属性算：
 *  放不下就跳过并点名，绝不替用户把那一头清成 0——夹到 0 与「取消这一头」在 `Clip.fade` 里
 *  是同一个数字，界面不许把两件事混为一谈。与现值相同的不写，所以一组里没人变过就一次写入都不发。 */
export function fadeDragBatch(
  project: Project,
  anchorId: string,
  side: FadeSide,
  rawTicks: number,
  quantum: number,
  both: boolean,
  groupIds: string[] = []
): { ops: FadeOp[]; skipped: { clipId: string; why: string }[] } {
  const ops: FadeOp[] = [];
  const skipped: { clipId: string; why: string }[] = [];
  const chosen = new Set<string>([anchorId, ...groupIds]);
  // 链接不传递：一遍就够，把每条目标的同 `link_id` 伙伴拉进来。
  for (const clip of Object.values(project.clips)) {
    if (!clip.link_id || !chosen.has(clip.id)) continue;
    for (const other of Object.values(project.clips)) if (other.link_id === clip.link_id) chosen.add(other.id);
  }
  const trackById = new Map(project.tracks.map((t) => [t.id, t]));
  for (const id of chosen) {
    const clip = project.clips[id];
    if (!clip) continue;
    const track = trackById.get(clip.track_id);
    if (!track) continue;
    if (track.locked) {
      skipped.push({ clipId: id, why: "所在轨道已锁定" });
      continue;
    }
    const options = fadeProperties(clip, project.assets[clip.asset_id]);
    const wanted: FadeProperty = track.kind === "audio" ? "gain" : "opacity";
    const primary = options.includes(wanted) ? wanted : options[0];
    if (!primary) continue; // 既不显示画面也没有声音：按引擎的规矩这种片段存不下来，不替它编一个淡
    for (const property of both ? options : [primary]) {
      const ticks = fadeDragTicks(clip, property, side, rawTicks, quantum);
      if (ticks === fadeWindows(clip)[property][side]) continue;
      ops.push({ clipId: id, property, side, ticks });
    }
  }
  return { ops, skipped };
}

/** 淡入与淡出共用片段的同一段长度：两个窗口加起来超过片段长度，引擎回 `INVALID_FADE`。
 *  这句话在界面先算一遍，因为「按下去必定被拒」的按钮不该亮着（1.82 立下的规矩）。
 *  报出来的余量是片段长度减去对面那头已经占掉的，不是界面自己另写的上限。 */
export function fadeBlocker(
  clip: Clip,
  property: FadeProperty,
  side: FadeSide,
  value: number
): string | null {
  const other = side === "in" ? fadeWindows(clip)[property].out : fadeWindows(clip)[property].in;
  if (value + other <= clip.duration_ticks) return null;
  const room = fadeRoom(clip, property, side);
  const name = side === "in" ? "淡入" : "淡出";
  const opposite = side === "in" ? "淡出" : "淡入";
  return (
    `${name} ${(value / TIMEBASE).toFixed(2)} 秒，加上另一头的${opposite} ` +
    `${(other / TIMEBASE).toFixed(2)} 秒，比这段 ${(clip.duration_ticks / TIMEBASE).toFixed(2)} 秒还长。` +
    `这一头最多还能要 ${(room / TIMEBASE).toFixed(2)} 秒；要更长就把片段剪长一点，或先把对面那头缩短。`
  );
}

/** 1.107：检查器里那一行额度读数（`line`）与它的来历（`detail`，挂在这一行的 title 上）。
 *  它只做两件事——按 revision 决定能不能显示、把引擎给的字填进句子；「还放得下几张」是引擎除的
 *  （`room_cubes` / `room_tables`），这里再除一次就是第二套规则。
 *  1.210：这一句原来把已用多少、每张要多少、明细列了几条全排在眼前，装机量到画上来四行；
 *  眼前那一行只留「还放得下几张」这一件能决定下一步的事，其余数字是来历。 */
export function gradeCapacity(
  cached: { value: GradeCapacity; revision: number } | null,
  revision: number | undefined,
): { line: string; detail: string } | null {
  if (!cached || revision === undefined || cached.revision !== revision) return null;
  const v = cached.value;
  const listed = Object.keys(v.by_clip).length;
  const detail = (
    v.samples
      ? `本工程的查找表已用 ${v.samples} / ${v.limit} 个采样点；`
      : `本工程的查找表额度是 ${v.limit} 个采样点，还没用过；`
  )
    + `一张满格 3D 立方要 ${v.cube_samples} 个、一张满格 1D 表要 ${v.table_samples} 个采样点，`
    + `所以还放得下 ${v.room_cubes} 张立方或 ${v.room_tables} 张 1D 表——这几个数都是引擎除的，界面不再除一遍`
    + (v.clips_with_tables > listed
      ? `；带表的片段共 ${v.clips_with_tables} 条，明细列前 ${listed} 条，另有 ${v.other_clips} 条未列`
      : "")
    + "。";
  return {
    line: `查找表还放得下 ${v.room_cubes} 张满格 3D 立方、${v.room_tables} 张满格 1D 表。`,
    detail,
  };
}
