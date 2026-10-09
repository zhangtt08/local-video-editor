import type { AnimatedEffect, Asset, Capabilities, Clip, Curve, MaskProperty, Project, ShapeMask, WipeChannel } from "./engine";
import { TIMEBASE } from "./time";

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

/** 遮罩跟踪的三个旋钮：挡住最多猜几帧、要不要在整幅画面上重找、遮罩随远近缩放。
 *  它们是「下一次请求怎么发」的默认值，不是工程数据——写进工程要经 `updateProjectMeta`，那会每
 *  点一次涨一个 revision 并清空撤销栈，等于拿用户的编辑历史换一个勾选。所以它们跟着应用走
 *  （与代理宽度同一处），换一个工程、重开一次窗口都还在。天花板只由引擎的 `capabilities.limits`
 *  给：存着的数比这台引擎的天花板大，读出来就夹回去。 */
const KNOB_KEYS = { gap: "agentcut.trackGap", sweep: "agentcut.trackSweep", scale: "agentcut.trackScale" };

export type TrackingKnobs = { gap: number; sweep: boolean; scale: boolean };

export function readTrackingDefaults(fallbackGap: number, gapCeiling: number): TrackingKnobs {
  const clamp = (value: number) => Math.max(0, Math.min(Math.round(value), gapCeiling));
  try {
    // 没存过与存了个 0 是两件事：`Number(null)` 恰好是 0，直接拿去判范围会把「一次都不猜」
    // 当成空存储的默认。先按字符串判缺失，再换算。
    const raw = localStorage.getItem(KNOB_KEYS.gap);
    const stored = raw === null || raw === "" ? Number.NaN : Number(raw);
    const gap = Number.isFinite(stored) && stored >= 0 ? clamp(stored) : clamp(fallbackGap);
    // 没存过就是开着的（引擎的默认就是 true），所以只有明确的 "0" 才算关。
    return { gap, sweep: localStorage.getItem(KNOB_KEYS.sweep) !== "0", scale: localStorage.getItem(KNOB_KEYS.scale) !== "0" };
  } catch {
    return { gap: clamp(fallbackGap), sweep: true, scale: true };
  }
}

export function rememberTrackingDefaults(knobs: Partial<TrackingKnobs>): void {
  try {
    if (knobs.gap !== undefined) localStorage.setItem(KNOB_KEYS.gap, String(knobs.gap));
    if (knobs.sweep !== undefined) localStorage.setItem(KNOB_KEYS.sweep, knobs.sweep ? "1" : "0");
    if (knobs.scale !== undefined) localStorage.setItem(KNOB_KEYS.scale, knobs.scale ? "1" : "0");
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
