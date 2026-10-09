import type { Fraction, RampPiece } from "./time";

export type VerifiedMedia = {
  probe_id: string;
  path: string;
  kind: "video" | "audio" | "image";
  label: string;
  size_bytes: number;
  content_sha256: string;
  duration_ticks: number;
  width: number | null;
  height: number | null;
  frame_rate: Fraction | null;
  has_audio: boolean;
  audio_sample_rate: number | null;
  audio_channels: number | null;
  video_codec: string | null;
  audio_codec: string | null;
};

export type Asset = {
  id: string;
  kind: "video" | "audio" | "image" | "text" | "sequence";
  label: string;
  reference: string;
  duration_ticks: number | null;
  verified: VerifiedMedia | null;
  sequence_id?: string | null;
};

export type Track = {
  id: string;
  kind: "video" | "audio";
  name: string;
  muted: boolean;
  hidden: boolean;
  volume: number;
  locked?: boolean;
  blend_mode?: BlendMode;
};

/** The properties that can carry keyframes. `blur` is deliberately not one of them: the exporter
 * has no per-frame radius, so the soft focus is a static knob and `keyof Effects` is no longer the
 * same set as the animatable set. */
export type AnimatedEffect = "x" | "y" | "scale" | "rotation" | "opacity" | "gain";
export type Effects = { x: number; y: number; scale: number; rotation: number; opacity: number; gain: number; blur: number; sharpen: number; sharpen_radius: number; denoise: number };
export type MaskProperty = "mask_x" | "mask_y" | "mask_width" | "mask_height";
/** 1.98: 柔焦可以打关键帧，但走的是引擎编译出的阶梯（`spatial_schedule`），不是这六个标量属性那条式子。 */
export type SpatialProperty = "blur";
export type Property = AnimatedEffect | MaskProperty | SpatialProperty;
export type SampledValues = Record<AnimatedEffect, number> & { mask_x: number; mask_y: number; mask_width: number; mask_height: number };
export const DEFAULT_EFFECTS: Effects = { x: 0, y: 0, scale: 1, rotation: 0, opacity: 1, gain: 1, blur: 0, sharpen: 0, sharpen_radius: 0.004, denoise: 0 };
export type GradeChannel = "rgb" | "red" | "green" | "blue";
export type GradeCurvePoint = { x: number; y: number };
export type BlendMode =
  | "normal" | "multiply" | "screen" | "overlay" | "darken" | "lighten" | "difference" | "exclusion";

// One vocabulary for track compositing and for grade-node blending, with the labels the UI shows.
export const BLEND_MODES: [BlendMode, string][] = [
  ["normal", "正常"],
  ["multiply", "正片叠底"],
  ["screen", "滤色"],
  ["overlay", "叠加"],
  ["darken", "变暗"],
  ["lighten", "变亮"],
  ["difference", "差值"],
  ["exclusion", "排除"],
];
export const blendLabel = (mode: BlendMode): string =>
  BLEND_MODES.find(([value]) => value === mode)?.[1] ?? mode;

export type GradeOperation =
  | { kind: "curve"; channel: GradeChannel; points: GradeCurvePoint[]; enabled: boolean; mix?: number; blend?: BlendMode }
  | { kind: "white_balance"; temperature: number; tint: number; enabled: boolean; mix?: number; blend?: BlendMode }
  | { kind: "wheels"; lift: number[]; gamma: number[]; gain: number[]; enabled: boolean; mix?: number; blend?: BlendMode }
  /** 色阶：输入黑场、白场与中间调 gamma。仍然是每通道一条函数，所以整条链照样塌成一张表。 */
  | { kind: "levels"; channel: GradeChannel; black: number; white: number; gamma: number; enabled: boolean; mix?: number; blend?: BlendMode }
  /** 通道混合器：3x3 作用在存储值上。没有 blend 字段是刻意的——矩阵与非线性混合模式的复合不再是矩阵。 */
  | { kind: "matrix"; coefficients: number[]; enabled: boolean; mix?: number }
  | { kind: "transfer"; input_space: ColorSpace; output_space: ColorSpace; enabled: boolean; mix?: number; blend?: BlendMode }
  /** 导入的 1D 查找表：三个通道各一条折线，采样点由引擎解析 `.cube` 文件得到，界面不自己读文件。 */
  | { kind: "lut"; title: string; size: number; channels: number[][]; enabled: boolean; mix?: number; blend?: BlendMode };
/** 引擎 `/v1/lut/parse` 的回复：可直接放进调色链的节点内容（不含启用、强度等每节点默认值）。 */
export type LutPayload = { title: string; size: number; channels: number[][]; resampled_from?: number };
/** A parallel branch is always a single per-channel operation, so the graph never nests -- and the
 *  mixer is excluded here exactly as the contract excludes it: averaging a cross-channel map into a
 *  table is not something either end can compile. */
export type GradeMixer = { kind: "matrix"; coefficients: number[]; enabled: boolean; mix?: number };
export type GradeBranch = Exclude<GradeOperation, GradeMixer>;
export type GradeParallel = { kind: "parallel"; branches: GradeBranch[]; enabled: boolean; mix?: number; blend?: BlendMode };
export type GradeNode = GradeOperation | GradeParallel;
export type ColorSpace =
  | "linear" | "srgb" | "gamma18" | "gamma20" | "gamma22" | "gamma24" | "rec709";
export const COLOR_SPACES: [ColorSpace, string][] = [
  ["srgb", "sRGB（网页与屏幕录制）"],
  ["rec709", "Rec.709 / BT.1886（广播时间线，等同 gamma 2.4）"],
  ["gamma22", "gamma 2.2"],
  ["gamma24", "gamma 2.4"],
  ["gamma20", "gamma 2.0"],
  ["gamma18", "gamma 1.8"],
  ["linear", "线性（场景光）"],
];
export const DEFAULT_TRANSFER = { input_space: "srgb", output_space: "rec709" } as const;
export type GradeTables = { id: string; stages: GradeStage[] };
/** 引擎把一条调色链编译成有序阶段：每通道一张表，或一个 3x3 通道混合。顺序有意义 ——
 *  「曲线→通道混合」与「通道混合→曲线」是两张不同的图，两端都按这份列表走。 */
export type GradeStage =
  | { id: string; type: "lut"; r: number[]; g: number[]; b: number[] }
  | { id: string; type: "matrix"; m: number[] };
/** feColorMatrix 要 20 个数：把 3x3 摆成 RGBA 行，alpha 原样通过。滤镜上已写
 *  color-interpolation-filters="sRGB"，所以矩阵作用在和导出一样的存储值上，不是线性光。 */
export const feColorMatrixValues = (m: number[]): number[] => [
  m[0], m[1], m[2], 0, 0,
  m[3], m[4], m[5], 0, 0,
  m[6], m[7], m[8], 0, 0,
  0, 0, 0, 1, 0,
];
export type ClipColor = { exposure: number; contrast: number; saturation: number; grade?: GradeNode[] };
/** 文字层：所有比例值都以「字号的几分之几」表达，与导出侧 drawtext 读同一组数（见 textStyle.ts）。 */
export type TextStyle = {
  body: string;
  font_size: number;
  color: string;
  align?: "top" | "center" | "bottom";
  box?: boolean;
  font?: string;
  text_align?: "left" | "center" | "right";
  outline_width?: number;
  outline_color?: string;
  shadow_x?: number;
  shadow_y?: number;
  shadow_color?: string;
  box_color?: string;
  box_opacity?: number;
  line_spacing?: number;
};
/** 引擎按本机实际装着的字体下发，界面照这份表建选择器。 */
export type TextFont = { id: string; label: string; family: string };
export const DEFAULT_COLOR: ClipColor = { exposure: 0, contrast: 1, saturation: 1, grade: [] };
export const DEFAULT_WHEELS = { lift: [0, 0, 0], gamma: [1, 1, 1], gain: [1, 1, 1] };
export const DEFAULT_CURVE_POINTS: GradeCurvePoint[] = [
  { x: 0, y: 0 },
  { x: 1, y: 1 },
];
export type MaskVertex = { x: number; y: number; handle_out: [number, number]; handle_in: [number, number] };
export type ShapeMask = { shape: "rectangle" | "ellipse" | "path"; center_x: number; center_y: number; width: number; height: number; feather: number; inverted: boolean; vertices?: MaskVertex[] | null };

/** The clip's own fade windows, in ticks measured from each edge. 0 means that edge is untouched.
 *  `*_shape` (1.95) is how the property approaches its resting value along that window; the engine
 *  issues the list of names, and every edge defaults to the smoothstep pre-1.95 fades used. */
export type FadeShape = "linear" | "ease_in" | "ease_out" | "ease_in_out";
export type FadeEnvelope = { opacity_in_ticks: number; opacity_out_ticks: number; gain_in_ticks: number; gain_out_ticks: number; opacity_shape?: FadeShape; gain_shape?: FadeShape };
export const DEFAULT_MASK: ShapeMask = { shape: "ellipse", center_x: .5, center_y: .5, width: .6, height: .6, feather: 0, inverted: false, vertices: null };
export const DEFAULT_PATH: MaskVertex[] = [
  { x: .3, y: .25, handle_out: [0, 0], handle_in: [0, 0] },
  { x: .7, y: .35, handle_out: [0, 0], handle_in: [0, 0] },
  { x: .45, y: .75, handle_out: [0, 0], handle_in: [0, 0] },
];
export type Bezier = { x1: number; y1: number; x2: number; y2: number };
export type Keyframe = { property: Property; at_ticks: number; value: number; interpolation: "hold" | "linear" | "ease" | "bezier"; bezier?: Bezier | null };
export type Curve = { offset: number; value: number; easing: string }[];
export type AnimationGraph = { property: Property; duration_ticks: number; limits: [number, number]; path: string; curve: Curve; keys: Keyframe[] };
/** 转场种类由引擎的 capabilities.transition_kinds 下发；这里是同一份清单的类型。 */
export type TransitionKind = "dissolve" | "dip_black" | "dip_white" | "wipe_from_left" | "wipe_from_right" | "wipe_from_top" | "wipe_from_bottom" | "zoom_in" | "zoom_out";
export type TransitionChoice = { id: string; label: string };
export type Transition = { from_clip_id: string; kind: TransitionKind; duration_ticks: number };
export type LinkStatus = { clip_ids: string[]; synchronized: boolean; anchor_clip_id: string; differences: Record<string, { position_ticks: number; source_ticks: number; duration_ticks: number; speed_percent: number }> };
export type SpeedPoint = { at_ticks: number; percent: number };

/** 一条擦除：轴、方向、羽化宽与 0..1 的进度点表，全部由引擎下发（`transitions.envelopes`）。
 *  界面不许自备第二张「名字→方向」的表，也不许自己写羽化宽。 */
export type WipeChannel = { kind: string; invert: boolean; axis: "x" | "y"; flipped: boolean; feather: number; curve: Curve };

/** 转场的每一路都是引擎算好的一条点表：标量权重、黑/白闪、放大倍率、整层位移，以及那条擦除。 */
export type TransitionEnvelope = {
  picture: Curve;
  sound: Curve;
  black: Curve;
  white: Curve;
  scale: Curve;
  motion_x: Curve;
  motion_y: Curve;
  wipe: WipeChannel | null;
};

export type PreviewManifest = { revision: number; sequence_id?: string | null; sequences?: Record<string, PreviewManifest>; track_blend_modes?: Record<string, NonNullable<Track["blend_mode"]>>; mixed_track_ids: string[]; clips: Record<string, { duration_ms: number; sound_enabled: boolean; color_filter: string; grade?: GradeTables | null; sharpen?: { id: string; amount: number; bbox: [number, number] } | null; speed?: RampPiece[] | null; mask_image?: string | null; mask_curves?: Record<MaskProperty, Curve> | null; mask_unit?: string | null; spatial?: Record<SpatialProperty, Curve> | null; edge_filter?: string | null; curves: Record<AnimatedEffect, Curve>; transition: TransitionEnvelope; fade?: Record<"opacity" | "gain", Curve> | null }> };

/** 引擎给这条片段记下的那一次稳定：有了它，再按一次是换一档强度而不是叠第二遍。 */
export type Stabilization = {
  strength: number;
  max_crop: number;
  points: number;
  translation_correction: number;
  roll_correction: number;
  zoom_to_hide_borders: number;
  analysed_frames: number;
};

export type Clip = {
  mask?: ShapeMask | null;
  fade?: FadeEnvelope | null;
  id: string;
  asset_id: string;
  track_id: string;
  position_ticks: number;
  source_in_ticks: number;
  duration_ticks: number;
  effects?: Effects;
  color?: ClipColor;
  text?: TextStyle | null;
  speed_percent?: number;
  speed_curve?: SpeedPoint[] | null;
  stabilization?: Stabilization | null;
  keyframes?: Keyframe[];
  animation_offset_ticks?: number;
  transition_in?: Transition | null;
  group_id?: string | null;
  link_id?: string | null;
  link_source_offset_ticks?: number;
  embedded_audio?: boolean;
};

export type Sequence = { id: string; name: string; duration_ticks: number; tracks: Track[]; clips: Record<string, Clip> };

export type Marker = {
  id: string;
  at_ticks: number;
  name: string;
  color?: "amber" | "cyan" | "green" | "red" | "violet";
};

/** 一条交付项：预设、画幅适配与导出范围，与引擎的 RenderBatchItem 同一组词。 */
export type RenderBatchItem = {
  preset_id: string;
  filename: string;
  folder?: string | null;
  sequence_id?: string | null;
  fit: RenderFit;
  range?: RenderRange;
};

/** 存在工程里的交付方案：一组交付项加一个名字，人和 Agent 都按同一个列表出货。 */
export type DeliveryRecipe = { id: string; name: string; items: RenderBatchItem[] };

export type Project = {
  schema_version: number;
  id: string;
  name: string;
  revision: number;
  notes: string;
  settings: {
    timebase: number;
    frame_rate: Fraction;
    sample_rate: number;
    width: number;
    height: number;
    /** 母带音量：旧引擎不回这个字段，缺省按 1 处理。 */
    master_gain?: number;
    master_limiter?: boolean;
    master_ceiling_dbtp?: number;
    in_ticks?: number | null;
    out_ticks?: number | null;
    /** 监视器上显示哪一条安全参考线：关 / 动作区 / 字幕区。纯显示状态，不影响导出。 */
    safe_area?: "off" | "action" | "title";
  };
  assets: Record<string, Asset>;
  tracks: Track[];
  clips: Record<string, Clip>;
  sequences?: Record<string, Sequence>;
  markers?: Marker[];
  /** v12 新增：交付方案。旧工程读出来就是没有这个字段，按空列表处理。 */
  recipes?: DeliveryRecipe[];
};

export type MutationResult = {
  project: Project;
  committed: boolean;
  replayed: boolean;
  base_revision: number | null;
};

export type Command = Record<string, unknown>;

export type ProbeUrls = { thumbnails: string[]; waveform: string; stream: string };

export type ProxyRecord = {
  state: "absent" | "ready" | "not_needed" | "not_video";
  width: number;
  display_width?: number;
  display_height?: number;
  size_bytes?: number;
  source_width?: number;
  source_height?: number;
  path?: string;
  stream: string | null;
};

export type ProxyUsage = {
  limit_bytes: number;
  used_bytes: number;
  proxies: { source_sha256: string; width: number; size_bytes: number; used_at: number }[];
};

/** 整个派生缓存（缩略图 + 波形 + 代理）的占用，按内容哈希成项。 */
export type CacheUsage = {
  limit_bytes: number;
  used_bytes: number;
  entries: {
    digest: string;
    size_bytes: number;
    files: number;
    used_at: number;
    has_proxy: boolean;
  }[];
};

export type CachePruneResult = {
  limit_bytes: number;
  dry_run: boolean;
  used_bytes_before: number;
  used_bytes_after: number;
  freed_bytes: number;
  removed: { digest: string; size_bytes: number; files: number; has_proxy: boolean }[];
  kept: number;
};

export type EditPlan = { committed: boolean; project: Project; commands: Record<string, unknown>[]; [key: string]: unknown };

export type Probe = {
  id: string;
  verified: VerifiedMedia;
  thumbnails: string[];
  waveform: number[];
  cache_dir: string;
  latency_ms: number;
  urls: ProbeUrls;
};

export type ProbeRow = { id: string; path: string; created_at: string };

/** 交付画幅：完整保留（加边）、裁切填满、拉伸填满。与引擎的 RenderFit 同一组词。 */
export type RenderFit = "contain" | "cover" | "stretch";
/** 导出整条时间线，还是只导出入出点区间。与引擎的 RenderRange 同一组词。 */
export type RenderRange = "full" | "marks";

export const FIT_MODES: { id: RenderFit; label: string; hint: string }[] = [
  { id: "contain", label: "完整保留", hint: "画面全部留下，多出来的地方补黑边" },
  { id: "cover", label: "裁切填满", hint: "撑满画幅，超出的一边被裁掉（会丢画面）" },
  { id: "stretch", label: "拉伸填满", hint: "撑满画幅但比例变形，只在素材本身就是该比例时用" },
];

export type RenderJob = {
  id: string;
  project_id: string;
  revision: number;
  sequence_id?: string | null;
  preset_id: string;
  filename: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  total_ticks: number;
  rendered_ticks: number;
  message: string;
  error_code: string | null;
  output_path: string | null;
  output_size_bytes: number | null;
  /** 引擎是否用同一目录下的 ffprobe 重新打开并量过这个文件；false 表示未经复检就交付。 */
  output_checked: boolean;
  created_at: string;
  updated_at: string;
  elapsed_seconds: number | null;
  progress?: number;
};

export type Preset = {
  id: string;
  label: string;
  /** 容器与编解码器由引擎的预设表决定，界面只念出来，不自己拼 FFmpeg 参数。 */
  container: string;
  /** null 表示这条交付根本没有画面（MP3/WAV/FLAC），导出面板据此收起与画幅有关的一切。 */
  codec: string | null;
  crf: number | null;
  encoder_preset: string | null;
  audio_codec: string;
  audio_bitrate: string | null;
  pixel_format: string | null;
  profile: number | null;
  scale: [number, number] | null;
};

/**
 * The transition list the picker shows. An engine older than 1.59 reports no list, so the three
 * kinds it can honour are the fallback; anything newer drives the interface from its own table,
 * which is why adding a kind to the contract is enough to make it pickable.
 */
export function transitionChoices(caps?: { transition_kinds?: TransitionChoice[] } | null): TransitionChoice[] {
  return caps?.transition_kinds?.length
    ? caps.transition_kinds
    : [{ id: "dissolve", label: "交叉溶解" }, { id: "dip_black", label: "淡黑" }, { id: "dip_white", label: "闪白" }];
}

export function transitionLabel(
  caps: { transition_kinds?: TransitionChoice[] } | null | undefined,
  kind: string,
): string {
  return transitionChoices(caps).find((choice) => choice.id === kind)?.label ?? kind;
}

export function presetIsAudio(preset: Preset | null): boolean {
  return preset !== null && preset.codec === null;
}

/** 引擎给的是 FFmpeg 的编码器名，这一层只负责念给人听；不认识的名字原样显示，不猜。 */
export const CODEC_NAMES: Record<string, string> = {
  libx264: "H.264",
  libx265: "HEVC",
  "libvpx-vp9": "VP9",
  prores_ks: "ProRes 422 HQ",
  aac: "AAC",
  libopus: "Opus",
  pcm_s24le: "PCM 24-bit",
  libmp3lame: "MP3",
  flac: "FLAC",
};

const SAMPLING_NAMES: Record<string, string> = {
  yuv420p: "4:2:0 8-bit",
  yuv444p10le: "4:4:4 10-bit",
};

/**
 * The codec line under a preset. Written from the preset the engine returned, never from a string
 * baked into the panel: a preset list that grows a format must show that format, not yesterday's
 * "H.264 / AAC". Sampling is only named when it differs from the plain 4:2:0 8-bit every H.264
 * delivery uses, so the common rows stay short; an audio-only preset says so instead of naming a
 * picture it does not have.
 */
export function codecText(item: Preset): string {
  const audio = CODEC_NAMES[item.audio_codec] ?? item.audio_codec;
  if (item.codec === null) return `仅音频 · ${audio}`;
  const video = CODEC_NAMES[item.codec] ?? item.codec;
  const sampling = item.pixel_format ? SAMPLING_NAMES[item.pixel_format] : undefined;
  return `${video} / ${audio}${sampling && item.pixel_format !== "yuv420p" ? ` · ${sampling}` : ""}`;
}

export type Capabilities = {
  api_version: string;
  /** 安全区的内缩量（占画面边长的比例），由引擎给出，界面不自己另写一套数字。 */
  safe_area_insets?: { action: number; title: number };
  mask_vertex_limit?: number;
  /** 调色链的形状上限（节点数、并联支数、曲线点数、LUT 采样数）由引擎下发，界面照此限制。 */
  grade_limits?: {
    max_nodes: number;
    max_branches: number;
    max_curve_points: number;
    max_lut_samples: number;
    levels_black_max?: number;
    levels_white_min?: number;
    levels_gamma_min?: number;
    levels_gamma_max?: number;
    matrix_limit?: number;
  };
  /** 可选的转场种类与中文名：界面列的是这份表，不是自己写死的三个。 */
  transition_kinds?: TransitionChoice[];
  /** 1.95：淡的形状（线性 / 缓入 / 缓出 / 缓入缓出）。下拉列的是这份表；老引擎不回就没有这一行。 */
  fade_shapes?: TransitionChoice[];
  /** 本机装着的文字字体（id / 中文名 / CSS family）；选择器列的是这份表。 */
  text_fonts?: TextFont[];
  /** 引擎自身的构建号；旧引擎不回这个字段，界面按空字符串处理。 */
  app_version?: string;
  project_schema_version: number;
  timebase: number;
  max_commands_per_batch: number;
  commands: string[];
  features: Record<string, boolean>;
  limits: { max_tracks: number; max_assets: number; max_clips: number; sample_rates: number[]; blur_fraction?: number; blur_radius_limit_px?: number; sharpen_amount?: number; sharpen_radius_fraction?: number; sharpen_radius_default?: number; denoise_db?: number; stabilize_max_crop?: number; stabilize_smoothing_frames?: number; track_max_gap_frames?: number; track_gap_default?: number; track_min_frames?: number; track_max_frames?: number };
  render_presets: Preset[];
};

/** 1.97 整轨规划的一项：要么是能搬的淡（带着将要落库的两个数），要么是搬不动的原因。 */
export type FadeAdoptionEntry = {
  clip_id: string;
  property: "opacity" | "gain";
  in_ticks?: number;
  out_ticks?: number;
  shape?: string;
  keyframe_count?: number;
  skipped?: string;
};

export type FadeAdoptionPlan = {
  track_id: string;
  clips: FadeAdoptionEntry[];
  adopted: number;
  skipped: number;
  commands: Record<string, unknown>[];
};

export class EngineError extends Error {
  code: string;
  details: Record<string, unknown>;
  status: number;

  constructor(code: string, message: string, details: Record<string, unknown>, status: number) {
    super(message);
    this.code = code;
    this.details = details;
    this.status = status;
  }

  /** 每个错误都要给出下一步动作——这是降低上手难度的关键，不是装饰。 */
  explain(): string {
    const hints: Record<string, string> = {
      UNAUTHORIZED: "引擎密钥不匹配，请重启软件或在 Agent 面板重新复制配置。",
      REVISION_CONFLICT: "时间线刚被 Agent 或另一次操作改过。界面已自动读取最新版本，请重做这一步。",
      IDEMPOTENCY_CONFLICT: "同一个请求号被用于不同内容，属于程序保护，不影响你的剪辑。",
      REQUEST_ALREADY_COMMITTED: "这次预览请求已经用过了，换一次操作即可。",
      CLIP_OVERLAP: "同轨重叠需要转场。先将镜头首尾衔接，再在后一个镜头的属性面板添加转场。",
      INVALID_TRANSITION: "选择首尾衔接的两个镜头，转场需短于每个镜头。",
      INVALID_MASK: "遮罩只能用于画面轨片段，请检查轨道和遮罩范围。整批操作没有被保存。",
      INVALID_LUT: "这个 .cube 文件引擎读不了：只有 1D（逐通道）查找表能用，3D 表会跨通道混合，暂不支持。",
      INVALID_BLEND_MODE: "混合模式只能用于画面轨。整批操作没有被保存。",
      INVALID_SELECTION: "选中的片段已变化，请重新选择后操作。整组没有被修改。",
      NEST_LAYER_CONFLICT: "所选图层之间还有重叠镜头，请一并选择，避免预合成后改变叠放顺序。",
      SEQUENCE_CYCLE: "合成不能包含自身或它的上级合成。整批操作没有被保存。",
      SEQUENCE_DEPTH: "最多支持 8 层嵌套，请减少合成层级。",
      SEQUENCE_OUT_OF_BOUNDS: "内部片段超过合成结尾，请先增加合成时长。",
      SEQUENCE_IN_USE: "这个合成还在使用，请先删除引用它的片段。",
      KEYFRAME_NOT_FOUND: "这个关键帧已被移走或删除，请重新选择。",
      KEYFRAME_COLLISION: "目标时间已有同属性关键帧，原点没有修改；放大曲线并选一个空位置。",
      INVALID_TRACK_MAP: "整组轨道映射已失效，请重新选择目标轨道。",
      TRANSITION_EDIT_CONFLICT: "此处位于转场重叠区间。先移除转场，再分割、插入或覆盖。",
      TIME_NOT_ALIGNED: "片段必须落在整帧或整采样点上。跨轨插入若帧率与采样时钟不兼容，请关闭“同步未锁轨道”或调整区间。",
      TRACK_LOCKED: "轨道已锁定，请解锁或选择其他目标轨道。",
      INVALID_RIPPLE_TRACKS: "同步轨道必须包含目标轨道，且不能重复。",
      SOURCE_OUT_OF_BOUNDS: "片段超出了素材可用长度。缩短这段，或换一段更长的素材。",
      TRACK_KIND_MISMATCH: "音频只能放在音频轨，视频/图片只能放在画面轨。",
      ASSET_IN_USE: "素材还在时间线上使用，先删掉相关片段。",
      TRACK_NOT_EMPTY: "这条轨道上还有片段，先清空再删除轨道。",
      MISSING_REFERENCE: "片段引用的素材或轨道不存在。",
      UNVERIFIED_ASSET: "这段素材只有元数据、没有真正导入文件，无法渲染。请从素材库导入后重试。",
      MEDIA_NOT_ALLOWED: "文件不在允许的素材文件夹里。用“导入素材”按钮，或在设置里添加那个文件夹。",
      MEDIA_TYPE_UNSUPPORTED: "这个文件类型不被支持。常用视频/音频/图片都可以。",
      MEDIA_PROBE_FAILED: "文件损坏或编码不被 FFmpeg 识别，换个文件试试。",
      MEDIA_MISSING: "素材原文件已被移动或删除，请重新导入。",
      MEDIA_TOOL_MISSING: "找不到 FFmpeg，随安装包自带的 bin 目录被删了。",
      MEDIA_UNAVAILABLE: "当前引擎没有启用媒体功能（没有可写的素材目录）。",
      FFMPEG_FAILED: "编码器报错，通常是个别素材的编码异常；可先用 540p 代理试一次。",
      STALE_REVISION: "渲染历史快照与提交版本不一致，请重新提交导出。",
      INTERRUPTED: "软件重启打断了这次渲染，重新点渲染即可。",
      EMPTY_TIMELINE: "时间线上还没有可用画面，先从素材库拖一段进来。",
      OUTPUT_NOT_ALLOWED: "输出文件夹没有被授权。在导出面板重新选择一次文件夹。",
      NO_OUTPUT: "编码结束但没有产出文件，通常是磁盘空间或权限问题。",
      INVALID_PROBE: "素材记录与服务端探测不一致，请重新导入这个文件。",
      STORAGE_UNAVAILABLE: "本地数据库被占用，稍等一秒重试；写入是原子的，不会丢数据。",
      API_UNAVAILABLE: "剪辑引擎没在运行。点右上角状态灯重启引擎。",
      INVALID_REQUEST: "请求字段不符合契约。界面已把这一步的错误原因显示在这里。",
      STABILIZE_INVALID: "这段还不能稳定：只有放在画面轨、按 100% 原速播放、且真正导入进来的视频素材能量出抖动。先把它放回画面轨或把速度改回 100%。",
      STABILIZE_FAILED: "画面对不上第一帧的帧太少，量不出相机怎么动——片段太短、太暗或切得比跟踪还快。这段保持原样，换一段更稳的参照。",
      AUTO_GRADE_INVALID: "自动调色要先看得见画面：只有已经校验过的视频或图片素材能测出自己的黑场与白场，音频和文字没有画面可言。把这段素材放到画面轨上再按，或者直接在调色里手动填色阶的黑场、白场。",
      AUTO_GRADE_FAILED: "剪辑引擎没能读出这段素材的任何一帧：可能是源文件被换掉或删掉了，也可能片段的入出点落在了素材长度之外。先确认文件还在、重新导入一次，再按自动调色；工程没有被改动，历史里也不会多出一步。",
      AUTO_GRADE_NO_RANGE: "量出来的黑场和白场几乎挨在一起（不到 16 个色阶），这条画面没有可以拉开的层次——多半是一色底板、全黑或全白。换个取样范围、把「两端忽略」调大一些，或者直接用色阶节点自己填黑场白场。",
      AUTO_GRADE_CONFLICT: "这条片段上已经有色阶节点了，再来一次会把同一段拉伸叠两遍，画面朝一个方向越推越极端。要么先在调色里把那个节点删掉，要么把「替换已有色阶」打开，让引擎重算并顶替它，仍然只占一个节点。",
      AUTO_GRADE_LIMIT: "调色的链子上限是 8 个节点，这一次放不下（分通道 rgb 模式要占 3 个）。删掉一个不再用的节点，或者改用亮度（luma）模式——它只加 1 个节点，也不会凭空造出色偏。",
      STABILIZE_CONFLICT: "这段画面已经K过位移/缩放/旋转，再稳定一次会把同一段抖动抵消两遍、画面朝反方向偏。撤销这一步，或在曲线编辑器里清掉那几条，再按一次。",
      STABILIZE_LOCKED: "这段画面还带着一次稳定：抵消按「一帧源画面对一个关键帧」量出来，占的正是位移/缩放/旋转这三条曲线。改速度会让它按错的速率播放，主体跟随重构图又会把这几条整条改写、顺手抹掉稳定。先「取消稳定」（或画面稳定填 0），再做这一步，之后想稳定就再按一次。",
      BLUR_OUT_OF_RANGE: "柔焦/清晰的半径超出了导出与预览验证过一致的范围。把数值调小；滑杆的上限就是引擎在当前画幅下允许的最大值。",
      NOT_FOUND: "这条时间线上找不到它——片段或轨道可能在另一个合成里（从时间线上方的面包屑进去再操作），或者已经被删掉。",
      INVALID_SILENCE_TARGET: "这段没有可剪的静音，或它还不能剪：带变速曲线的片段要先去掉速度；也可以把阈值调低（默认 -35 dB）、把最短静音调短（默认 0.25 秒）再扫一次。",
      INVALID_LOUDNESS_TARGET: "这段量不了响度：需要真正导入的音频，且音量没有被关键帧占用。先清掉音量曲线，或换一段素材。",
      INVALID_REFRAME: "主体跟随要一条画了遮罩、遮罩中心有动画的片段：先画遮罩再按「跟踪主体」，或自己在位移/缩放上手打关键帧。",
      INVALID_DUCK: "自动闪避要两条不同的声音轨：一条说话、一条被压。目标轨不能给自己闪避。",
      DUCK_PLAN_TOO_LARGE: "一次要闪避的片段太多（上限 90 条）：先用「去空白」把口播切成几段，或把配乐拆成几条片段再分次闪避。",
      INVALID_TRACK_TARGET: "要跟踪的窗口超出了这条片段：缩短帧数，或从更早的一帧开始。",
      MASK_TRACK_BUDGET: "这条片段的曲线已经写满了：一个跟踪点要占 4 条曲线（中心 X/Y 加宽高），片段最多 2000 条。把这段切成几条短片段分别跟、删掉不要的关键帧，或者关掉尺寸估计（一个点只占 2 条）；也能把播放头挪到已经跟好的末尾，用「接着跟」续一小段。",
      TRACK_FAILED: "画面里没有跟得住的东西：把遮罩盖到纹理明显的主体上再试，或加大搜索半径、减少帧数。",
      INVALID_SPEED: "这个速度改不了：图片和文字没有播放速度，曲线变速要真正的媒体片段。",
      PROJECT_LIMIT: "工程到了契约上限（片段、轨道或关键帧的数量）：删掉不用的素材与曲线，或把长段落拆成几条片段。",
      TIME_OVERFLOW: "这一步超出了可保存的时间范围：把内容往前挪，或缩短这段。",
      API_ERROR: "接口回了一句引擎没有写明的错误：重新读一次工程再试；一直出现就记下操作顺序，方便排查。",
      MEDIA_FAILED: "媒体引擎这一次没给出画面：确认素材还在原位、桌面端在运行后重试；持续失败就点一下「清理缓存」再试。",
      // 1.81: 每一条引擎可能报的拒绝都要有中文说法，
      // 少了哪一条，界面上露出来的就是英文原句。
      ALREADY_DETACHED: "这一段的声音已经和画面分开了，不需要再拆一次；要合回去用「重新链接」。",
      ASSET_MEDIA_CONFLICT: "这个素材已经被别的片段用着，不能改成别的文件或别的长度；先把它用到的片段删掉或复制一份新素材。",
      BUNDLE_TOO_LARGE: "工程包超过 2 GB 上限：把没用到的素材从素材库删掉，或者分几个工程来做。",
      DUCK_PLAN_INVALID: "自动闪避量不出来：请先确认「说话的那条轨」上有能听声音的片段（不是纯画面、也不是带变速曲线的）。",
      DUPLICATE_ID: "这个编号已经被用了：片段、轨道或素材的 id 在一个工程里必须唯一，换一个编号再提交。",
      FONT_UNAVAILABLE: "这台机器上没有这款字体，字幕会退回默认字体。装好字体后重启 AgentCut 就能选到。",
      FRAME_UNAVAILABLE: "这一帧取不到：时间线上这个位置可能没有片段，或者素材已经被移走。换个时间点或先补上素材。",
      INSUFFICIENT_SPACE: "输出盘空间不够。清出空间或把导出文件夹换到大盘上再试。",
      INVALID_AV_LINK: "音画链接只能连有声音的片段和画面片段，而且两条轨要能对齐；先确认两边都不是纯画面或纯声音。",
      INVALID_BUNDLE: "这个工程包读不了：它可能不是 AgentCut 导出的，或者版本太新。用 1.x 导出的包再试一次。",
      INVALID_CAPTIONS_TARGET: "这段没法自动字幕：要么没有可听的音轨，要么带变速曲线。带曲线的先改成恒定速度。",
      INVALID_COLOR: "这个颜色值引擎不认。用界面里的取色器，或者写成 #rrggbb / 0-1 之间的三个分量。",
      INVALID_DETACH: "这段拆不开：它可能已经拆过、或者是链接过来的从属片段。先在时间线上选中主片段再拆。",
      FADE_ADOPT_SHAPE: "这条淡搬不成边窗口：它不是 1.90 之前那种「从 0 缓到静止值」的淡——可能夹着别的关键帧、起点不是 0、形状不是缓入缓出，或者这一头已经是边窗口了。details 里逐条列出了这条属性上的关键帧与片段的静止值；先在曲线编辑器里把它们整理成一条从边上出发的淡（或直接删掉，再拖时间线的淡角柄重做一遍）。",
      FADE_ADOPT_NONE: "这一轨上没有写成关键帧的淡可搬：每条片段的淡都已经在自己的两条边上（检查器那两个数字就是），或者这段本来就没有淡。要加淡直接拖时间线两边的淡角柄，或在检查器「淡入淡出」里填秒数。",
      INVALID_FADE: "淡入淡出放不下：这个片段比要淡的时间还短。先缩短淡入淡出，或者把片段留长一点。",
      INVALID_FOUR_POINT: "四点剪辑的四个位置对不上：源入点要在源出点之前，时间线入点也要在出点之前，且素材要够长。",
      INVALID_KEYFRAME: "这个关键帧写不了：属性名要选得对，时间要落在片段里，数值也别超出范围。用动画曲线面板改最稳。",
      INVALID_MARKER: "这个标记动不了：编号要在工程里存在，名字和颜色也要合法（颜色用 #rrggbb）。",
      INVALID_MARKER_SPLIT: "按标记分割没能切出东西：这个标记的位置可能正好在片段开头或结尾，那里切不出两段。",
      INVALID_MARKS: "入点出点不成区间：入点要在出点之前，且都要落在时间线里。清掉标记可以点标尺上的清除。",
      INVALID_PROJECT: "这份工程数据引擎不认：字段缺失或类型不对。如果是外部改过的工程，请用界面重新保存一份。",
      INVALID_RECIPE: "这套交付方案不完整：预设、适配、范围、文件名要齐全，且预设 id 要在能力表里存在。",
      INVALID_ROLL: "这个滚点动不了：它两侧都要有片段，而且不能把哪一侧剪成负长度。",
      INVALID_SLIDE: "左右滑移放不下：相邻片段得让得出这段位移，不然另一段会被剪成负长度。",
      INVALID_SLIP: "划动素材窗口不行：源入点不能越过素材的头或尾。先确认素材比片段长，或者缩短片段。",
      INVALID_SOURCE_RANGE: "源素材的入出点不成一段：入点要在出点之前，且都要落在素材长度之内。",
      INVALID_SPLIT: "这里切不开：切点要落在片段内部（不能在开头或结尾），也得对齐到整帧。",
      INVALID_SUBTITLE: "这份字幕读不了：SRT 的时间行格式不对或者顺序颠倒。用界面导出一份再改，别手写时间码。",
      INVALID_TEXT: "文字片段缺内容：正文不能为空，字号和颜色要在范围内。双击时间线上的文字片段就能改。",
      JOB_ALREADY_DONE: "这个任务已经结束了，取消不了。要看结果去右侧的导出记录。",
      LINK_OUT_OF_SYNC: "音画链接的两边长度已经不一致，不能这样提交。先解开链接，或者把两边修齐。",
      LOUDNESS_FAILED: "响度表读不出这段声音：纯静音没有响度可对齐，其它情况请确认素材能正常解码。",
      MEDIA_CACHE_ENTRY_MISSING: "这份派生数据已经不在了（缓存被清过）。重新打开一次素材就会自动重建。",
      MEDIA_EMPTY: "这个文件是空的或者读不出内容。确认文件完整后重新导入。",
      MEDIA_NOT_FOUND: "原文件不在这个位置了。把素材放回原来的文件夹，或者在素材库里重新指向新位置。",
      MEDIA_NO_AUDIO: "这个素材没有声音，所以听不了响度、也去不了空白。要处理声音得先换成带音轨的素材。",
      MEDIA_NO_IMAGE: "这个素材没有画面，做不了缩略图、遮罩或跟踪。要处理画面得先换成视频或图片。",
      MEDIA_NO_VIDEO: "这段素材里没有视频流。要放到画面轨上得先用带画面的文件。",
      MEDIA_PATH_INVALID: "路径要写完整的绝对路径（例如 C:\\素材\\a.mp4），相对路径和 UNC 路径都不接受。",
      MEDIA_PROBE_TIMEOUT: "探测这个文件超时了。文件可能太大或在慢盘/网络盘上；等一会儿再试，或把它拷到本地。",
      MEDIA_STALE: "这条记录已经过期（素材被重新导入过）。重新读一次素材清单再操作。",
      MEDIA_ZERO_DURATION: "这个素材时长为 0，上不了时间线。确认文件能正常播放再导入。",
      NOT_ADJACENT: "这两段不相邻，中间还有别的东西。先把它移开或选中真正挨着的两段。",
      NO_EMBEDDED_AUDIO: "这个视频里没有内嵌音轨，所以没法拆出声音。要配音得另外导入音频素材。",
      OUTPUT_INVALID: "导出的文件没通过复检（容器、流或时长不对）。候选文件已经销毁，最终文件名一次都没出现——请重试或换一个预设。",
      OUTPUT_NAME_INVALID: "文件名不合规则：不要带路径分隔符，扩展名要和选的容器一致（例如 .mp4）。",
      OUTPUT_ROOT_INVALID: "这个导出文件夹不在允许列表里。在界面里选一次导出位置，或把它加进输出目录列表。",
      PROBE_NOT_FOUND: "找不到这条素材记录。先在素材库里导入文件，再把它拖上时间线。",
      PROXY_FAILED: "代理生成失败，回放会直接用原片（可能卡）。清一下缓存或检查磁盘空间后重试。",
      PROXY_UNAVAILABLE: "这台机器上暂时不能生成代理。可以先用原片剪，或者在设置里关掉代理。",
      RENDER_UNAVAILABLE: "渲染引擎现在不可用（FFmpeg 缺失或被占用）。确认桌面端在运行后重试。",
      REVISION_OVERFLOW: "这个工程的版本数已经到顶，需要归档后开新工程。把当前工程复制一份继续做即可。",
      SILENCE_FAILED: "静音检测没跑成：素材可能读不出声音。先在素材库里确认这个文件能正常播放。",
      SPEECH_FAILED: "语音识别这次没跑完。素材太长可以先分段，或者确认模型目录还在原位。",
      SPEECH_NOT_FOUND: "这段里没听出说话。确认素材有人声、音量别太小；也可以改用「导入 SRT」。",
      SUBTITLES_MODEL_MISSING: "本机缺少这个语言的语音模型。把模型文件夹放到 asr 目录，或用 AGENTCUT_ASR_MODELS 指路。",
      SUBTITLES_UNAVAILABLE: "这台机器上没装语音识别引擎，自动字幕暂时用不了。可以先把字幕写成 SRT 再导入。",
      SUBTITLE_LIMIT: "字幕条数太多了。合并一些短句，或者分几条字幕轨来放。",
      UNKNOWN_PRESET: "没有这个导出预设。能力表里列出的 id 才是可用的；界面下拉里选一个即可。",
    };
    const hint = hints[this.code];
    if (!hint) return this.message;
    // The engine names the file, clip, track or composition a refusal is about. A generic sentence
    // on top of that still leaves a person guessing which of forty assets moved.
    const details = this.details ?? {};
    const named: string[] = [];
    const file = typeof details.asset_label === "string" ? details.asset_label : "";
    const asset = typeof details.asset_id === "string" ? details.asset_id : "";
    if (file) named.push(`素材 ${file}`);
    else if (asset) named.push(`素材 ${asset}`);
    for (const [key, word] of [
      ["clip_id", "片段"],
      ["track_id", "轨道"],
      ["sequence_id", "合成"],
    ] as const) {
      const value = details[key];
      if (typeof value === "string" && value && value !== asset) named.push(`${word} ${value}`);
    }
    return named.length ? `${hint}（${named.join("、")}）` : hint;
  }
}

export function newId(prefix: string): string {
  const random = crypto.randomUUID().replace(/-/g, "").slice(0, 12);
  return `${prefix}${random}`;
}

export class Engine {
  constructor(
    private base: string,
    private token: string
  ) {}

  get baseUrl(): string {
    return this.base;
  }

  get bearer(): string {
    return this.token;
  }

  private async request<T>(method: string, path: string, body?: unknown, timeoutMs = 20000): Promise<T> {
    // 引擎假死时让请求失败而不是永远挂起：界面 busy 状态因此总能解除。
    const response = await fetch(`${this.base}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${this.token}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(timeoutMs),
    });
    const text = await response.text();
    let data: unknown = undefined;
    try {
      data = text ? JSON.parse(text) : undefined;
    } catch {
      data = { raw: text };
    }
    if (!response.ok) {
      const error = (data as { error?: { code?: string; message?: string; details?: unknown } })
        ?.error;
      throw new EngineError(
        error?.code ?? `HTTP_${response.status}`,
        error?.message ?? response.statusText,
        (error?.details as Record<string, unknown>) ?? {},
        response.status
      );
    }
    return data as T;
  }

  info() {
    return this.request<Record<string, unknown>>("GET", "/v1/info");
  }

  capabilities() {
    return this.request<Capabilities>("GET", "/v1/capabilities");
  }

  projects() {
    return this.request<{ projects: { id: string; name: string; revision: number }[] }>(
      "GET",
      "/v1/projects?limit=100"
    );
  }

  project(id: string, revision?: number) {
    return this.request<Project>("GET", `/v1/projects/${id}${revision === undefined ? "" : `?revision=${revision}`}`);
  }

  create(name: string, settings?: Partial<Project["settings"]>) {
    return this.request<MutationResult>("POST", "/v1/projects", {
      request_id: newId("ui-create-"),
      name,
      ...(settings ? { settings } : {}),
    });
  }

  update(id: string, revision: number, patch: { name?: string; notes?: string; settings?: object }) {
    return this.request<MutationResult>("POST", `/v1/projects/${id}`, {
      request_id: newId("ui-update-"),
      expected_revision: revision,
      ...patch,
    });
  }

  edit(id: string, revision: number, commands: Command[], dryRun = false, sequenceId: string | null = null) {
    return this.request<MutationResult>("POST", `/v1/projects/${id}/edits`, {
      request_id: newId("ui-edit-"),
      expected_revision: revision,
      commands,
      dry_run: dryRun,
      sequence_id: sequenceId,
    });
  }

  history(id: string) {
    return this.request<{ history: { revision: number; operation: string; request_id: string; created_at: string }[] }>(
      "GET",
      `/v1/projects/${id}/history?limit=100`
    );
  }

  restore(id: string, revision: number, target: number) {
    return this.request<MutationResult>("POST", `/v1/projects/${id}/restore`, {
      request_id: newId("ui-restore-"),
      expected_revision: revision,
      target_revision: target,
    });
  }

  importMedia(path: string) {
    // 大素材的缩略图与波形解码可能超过默认 20 秒。
    return this.request<Probe>("POST", "/v1/media/import", { path }, 600000);
  }

  probe(id: string) {
    return this.request<Probe>("GET", `/v1/media/${id}`);
  }

  probes() {
    return this.request<{ probes: ProbeRow[] }>("GET", "/v1/media/probes");
  }

  /** Project manifest plus every referenced file, fetched as one download. */
  async bundle(projectId: string) {
    const response = await fetch(`${this.base}/v1/projects/${projectId}/bundle`, {
      headers: { Authorization: `Bearer ${this.token}` },
      signal: AbortSignal.timeout(600000),
    });
    if (!response.ok) {
      const data = (await response.json().catch(() => null)) as
        | { error?: { code?: string; message?: string } }
        | null;
      throw new EngineError(
        data?.error?.code ?? `HTTP_${response.status}`,
        data?.error?.message ?? response.statusText,
        {},
        response.status
      );
    }
    return response.blob();
  }

  async importBundle(file: File, requestId: string) {
    const response = await fetch(`${this.base}/v1/bundle?request_id=${encodeURIComponent(requestId)}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${this.token}`, "Content-Type": "application/zip" },
      body: file,
      signal: AbortSignal.timeout(600000),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const error = (data as { error?: { code?: string; message?: string; details?: unknown } })?.error;
      throw new EngineError(
        error?.code ?? `HTTP_${response.status}`,
        error?.message ?? response.statusText,
        (error?.details as Record<string, unknown>) ?? {},
        response.status
      );
    }
    return (data as MutationResult).project;
  }

  async frame(projectId: string, revision: number, atTicks: number, signal: AbortSignal, sequenceId: string | null = null) {
    const response = await fetch(`${this.base}/v1/projects/${projectId}/frame?revision=${revision}&at_ticks=${Math.floor(atTicks)}${sequenceId ? `&sequence_id=${sequenceId}` : ""}`, {
      headers: { Authorization: `Bearer ${this.token}` }, signal,
    });
    if (!response.ok) throw new EngineError("FRAME_UNAVAILABLE", "暂时无法计算合成画面，请暂停后重试。", {}, response.status);
    return { blob: await response.blob(), atTicks: Number(response.headers.get("X-Frame-Ticks")) };
  }


  mediaConfig() {
    return this.request<{ media_roots: string[]; cache_dir: string; ffmpeg: string; ffprobe: string }>(
      "GET",
      "/v1/media/config"
    );
  }

  assetUrls(projectId: string) {
    return this.request<{ assets: Record<string, { stream: string }> }>(
      "GET",
      `/v1/projects/${projectId}/asset-urls`
    );
  }

  proxyState(projectId: string, assetId: string, width: number) {
    return this.request<ProxyRecord>("GET", `/v1/projects/${projectId}/assets/${assetId}/proxy?width=${width}`);
  }

  proxyBuild(projectId: string, assetId: string, width: number) {
    return this.request<ProxyRecord>("POST", `/v1/projects/${projectId}/assets/${assetId}/proxy`, { width }, 900000);
  }

  proxyInventory() {
    return this.request<ProxyUsage>("GET", "/v1/media/proxies");
  }

  cacheInventory() {
    return this.request<CacheUsage>("GET", "/v1/media/cache");
  }

  /** 四点式之外的另一个「引擎替你算」的入口：把跟好的遮罩路径变成跟随用的平移+缩放。 */
  reframe(projectId: string, clipId: string, body: Record<string, unknown>) {
    return this.request<EditPlan>(
      "POST", `/v1/projects/${projectId}/clips/${clipId}/reframe`, body, 120000
    );
  }

  /** 画面稳定：引擎读一次随包 FFmpeg 解码的画面，把相机的抖动量出来，再写成 x/y/scale 关键帧。 */
  /** 自动调色：引擎读这段素材自己的画面，量出黑场白场，写回一个普通色阶节点。 */
  autoGrade(projectId: string, clipId: string, body: Record<string, unknown>) {
    return this.request<{
      committed?: boolean;
      replayed?: boolean;
      project?: unknown;
      commands: Record<string, unknown>[];
      auto_grade?: {
        mode: string;
        measured: {
          frames: number; pixels: number; percentile: number; skipped_pixels: number;
          analysis: string; bounds: Record<string, number[]>;
        };
        nodes: Record<string, unknown>[];
        removed: number[];
        chain_length?: number;
        reason?: string;
      };
    }>("POST", `/v1/projects/${projectId}/clips/${clipId}/auto-grade`, body, 300000);
  }

  stabilize(projectId: string, clipId: string, body: Record<string, unknown>) {
    return this.request<{ stabilization?: Record<string, unknown> } & Record<string, unknown>>(
      "POST", `/v1/projects/${projectId}/clips/${clipId}/stabilize`, body, 900000
    );
  }

  maskTrack(projectId: string, clipId: string, body: Record<string, unknown>) {
    return this.request<{
      tracking: {
        points: { at_ticks: number; center_x: number; center_y: number; width?: number; height?: number }[];
        tracked_frames: number; predicted_frames: number; scale_estimated: boolean;
        reacquire: boolean; reacquired_frames: number; reacquired_at_ticks: number[];
        gap_closure: number;
        gaps: { from_ticks: number; to_ticks: number }[]; lost_at_ticks: number | null;
        first_at_ticks: number; last_at_ticks: number;
        merged?: boolean; kept_frames?: number; replaced_frames?: number;
        budget_frames?: number;
        seam_ticks?: number; seam_jump?: number;
      };
      committed: boolean;
    }>("POST", `/v1/projects/${projectId}/clips/${clipId}/track`, body, 600000);
  }

  silenceScan(projectId: string, clipId: string, body: Record<string, unknown>) {
    return this.request<{
      committed: boolean;
      silence: {
        gaps: { from_ticks: number; to_ticks: number; length_ticks: number }[];
        removed_ticks: number;
        commands: Record<string, unknown>[];
      };
    }>("POST", `/v1/projects/${projectId}/clips/${clipId}/silence`, body, 300000);
  }

  /** 解析 .cube 文本：查找表只由引擎那一个解析器读，界面与 Agent 拿到的数完全一致。 */
  lutParse(content: string) {
    return this.request<LutPayload>("POST", "/v1/lut/parse", { content });
  }

  /** 本地语音识别：把选中片段（或整条轨）的说话转成字幕命令，落库走 captions.import。 */
  speechCaptions(projectId: string, body: Record<string, unknown>) {
    return this.request<{
      committed: boolean;
      speech: {
        cues: { from_ticks: number; to_ticks: number; text: string }[];
        srt: string;
        command: Record<string, unknown>;
        commands: Record<string, unknown>[];
        language: string;
        model: string;
      };
    }>("POST", `/v1/projects/${projectId}/speech-captions`, body, 600000);
  }

  loudnessScan(projectId: string, clipId: string, body: Record<string, unknown>) {
    return this.request<{
      committed: boolean;
      loudness: {
        integrated_lufs: number; true_peak_dbtp: number; gain: number;
        predicted_lufs: number; predicted_peak_dbtp: number; limited_by: string;
        reaches_target: boolean; target_lufs: number;
      };
    }>("POST", `/v1/projects/${projectId}/clips/${clipId}/loudness`, body, 300000);
  }

  loudnessTrack(projectId: string, trackId: string, body: Record<string, unknown>) {
    return this.request<{
      committed: boolean;
      loudness: {
        clips: Record<string, unknown>[]; measured: number; changed: number;
        off_target: number; target_lufs: number; commands: Record<string, unknown>[];
      };
    }>("POST", `/v1/projects/${projectId}/tracks/${trackId}/loudness`, body, 600000);
  }

  masterLoudness(projectId: string, body: Record<string, unknown>) {
    return this.request<{
      committed: boolean;
      project: Record<string, unknown>;
      master: {
        integrated_lufs: number; true_peak_dbtp: number; gain: number;
        predicted_lufs: number; predicted_peak_dbtp: number; limited_by: string;
        reaches_target: boolean; target_lufs: number;
        current_master_gain: number; proposed_master_gain: number;
        limiter?: boolean; ceiling_applied_dbtp?: number; measured_reaches_target?: boolean;
        after?: { integrated_lufs: number; true_peak_dbtp: number; lra_lu: number | null };
      };
    }>("POST", `/v1/projects/${projectId}/master/loudness`, body, 600000);
  }

  markerSplit(projectId: string, body: Record<string, unknown>) {
    return this.request<{
      committed: boolean;
      markers: {
        markers: number; splits: number; clips: number; unused: number[];
        content_ticks: number; commands: Record<string, unknown>[];
      };
    }>("POST", `/v1/projects/${projectId}/markers/split`, body, 60000);
  }
  duckTrack(projectId: string, trackId: string, body: Record<string, unknown>) {
    return this.request<{
      committed: boolean;
      duck: {
        speech: { from_ticks: number; to_ticks: number }[];
        clips: {
          clip_id: string; skipped?: string; keyframes?: number;
          ducked_ticks?: number; replaced_gain_keyframes?: number;
        }[];
        skipped: { clip_id: string; skipped: string }[];
        depth_db: number; gain: number;
        attack_ticks: number; hold_ticks: number; release_ticks: number;
        commands: Record<string, unknown>[];
      };
    }>("POST", `/v1/projects/${projectId}/tracks/${trackId}/duck`, body, 600000);
  }
  silenceTrack(projectId: string, trackId: string, body: Record<string, unknown>) {
    return this.request<{
      committed: boolean;
      silence: {
        clips: { clip_id: string; skipped?: string; removed_ticks?: number }[];
        removed_ticks: number;
        commands: Record<string, unknown>[];
      };
    }>("POST", `/v1/projects/${projectId}/tracks/${trackId}/silence`, body, 600000);
  }

  /** 1.97：走一遍这条轨，把 1.90 之前写成关键帧的淡排成普通的 `clip.fade_adopt` 命令。只读。 */
  fadeAdoptTrack(projectId: string, trackId: string, body: Record<string, unknown>) {
    return this.request<{
      committed: boolean;
      fade_adoption: FadeAdoptionPlan;
    }>("POST", `/v1/projects/${projectId}/tracks/${trackId}/fade-adopt`, body, 600000);
  }

  proxyPrune(maxBytes: number | null) {
    return this.request<{ used_bytes: number; freed_bytes: number; removed: unknown[] }>(
      "POST", "/v1/media/proxies/prune", { max_bytes: maxBytes }, 120000
    );
  }

  cachePrune(body: { max_bytes?: number | null; keep?: string[]; dry_run?: boolean }) {
    return this.request<CachePruneResult>("POST", "/v1/media/cache/prune", body, 120000);
  }

  renderPlan(projectId: string, presetId: string, revision?: number, sequenceId: string | null = null, fit: RenderFit = "contain", range: RenderRange = "full") {
    const query = new URLSearchParams({ preset_id: presetId });
    if (revision !== undefined) query.set("revision", String(revision));
    if (sequenceId) query.set("sequence_id", sequenceId);
    if (fit !== "contain") query.set("fit", fit);
    if (range !== "full") query.set("range", range);
    return this.request<{ plan: Record<string, unknown>; argv_preview: string[] }>(
      "GET",
      `/v1/projects/${projectId}/render-plan?${query.toString()}`
    );
  }

  fourPoint(projectId: string, body: Record<string, unknown>) {
    return this.request<{ committed: boolean; project: Project; four_point: Record<string, unknown>; commands: Record<string, unknown>[] }>(
      "POST", `/v1/projects/${projectId}/four-point`, body, 120000
    );
  }

  previewManifest(projectId: string, revision: number, sequenceId: string | null = null) {
    return this.request<PreviewManifest>("GET", `/v1/projects/${projectId}/preview-manifest?revision=${revision}${sequenceId ? `&sequence_id=${sequenceId}` : ""}`);
  }

  clipSample(projectId: string, revision: number, clipId: string, at: number) {
    return this.request<{ revision: number; values: SampledValues }>("GET", `/v1/projects/${projectId}/clips/${clipId}/sample?revision=${revision}&at_ticks=${at}`);
  }

  animationSample(clip: Clip, at: number) {
    return this.request<{ values: SampledValues }>("POST", `/v1/animation/sample?at_ticks=${at}`, clip);
  }

  animationCurve(clip: Clip, property: Property) {
    return this.request<AnimationGraph>("POST", `/v1/animation/curve?property=${property}`, clip);
  }

  previewCandidate(project: Project, sequenceId: string | null = null) {
    return this.request<PreviewManifest>("POST", `/v1/preview-manifest${sequenceId ? `?sequence_id=${sequenceId}` : ""}`, project);
  }

  maskPreview(mask: ShapeMask, frameWidth?: number, frameHeight?: number) {
    const query = frameWidth && frameHeight ? `?frame_width=${frameWidth}&frame_height=${frameHeight}` : "";
    return this.request<{ mask_image: string }>("POST", `/v1/mask/preview${query}`, mask);
  }

  captions(projectId: string, revision: number, trackId: string, sequenceId: string | null = null) {
    return this.request<{ revision: number; srt: string }>("GET", `/v1/projects/${projectId}/captions/${trackId}?revision=${revision}${sequenceId ? `&sequence_id=${sequenceId}` : ""}`);
  }

  render(projectId: string, revision: number, presetId: string, filename: string, folder?: string, sequenceId: string | null = null, fit: RenderFit = "contain", range: RenderRange = "full") {
    return this.request<{ job: RenderJob; plan: Record<string, unknown> }>(
      "POST",
      `/v1/projects/${projectId}/renders`,
      {
        request_id: newId("ui-render-"),
        expected_revision: revision,
        preset_id: presetId,
        filename,
        folder: folder ?? null,
        sequence_id: sequenceId,
        fit,
        range,
      }
    );
  }

  renderBatch(
    projectId: string,
    revision: number,
    items: { preset_id: string; filename: string; fit: RenderFit; range?: RenderRange }[],
    folder?: string
  ) {
    return this.request<{ committed: boolean; jobs: RenderJob[] }>(
      "POST",
      `/v1/projects/${projectId}/renders/batch`,
      {
        request_id: newId("ui-batch-"),
        expected_revision: revision,
        items: items.map((item) => ({ ...item, folder: folder ?? null })),
      },
      30000
    );
  }

  job(id: string) {
    return this.request<{ job: RenderJob; plan: Record<string, unknown> | null }>("GET", `/v1/jobs/${id}`);
  }

  jobs(projectId: string) {
    return this.request<{ jobs: RenderJob[] }>("GET", `/v1/projects/${projectId}/jobs?limit=20`);
  }

  cancelJob(id: string) {
    return this.request<{ job: RenderJob }>("POST", `/v1/jobs/${id}/cancel`);
  }

  addOutputRoot(path: string) {
    return this.request<{ output_roots: string[] }>("POST", "/v1/outputs/roots", { path });
  }

  outputRoots() {
    return this.request<{ output_roots: string[] }>("GET", "/v1/outputs/roots");
  }
}

export const trackAdd = (track: Omit<Track, "muted" | "hidden" | "volume">): Command => ({
  op: "track.add",
  track: { ...track, muted: false, hidden: false, volume: 1 },
});

export const trackUpdate = (trackId: string, patch: Partial<Omit<Track, "id" | "kind">>): Command => ({
  op: "track.update",
  track_id: trackId,
  ...patch,
});

export const trackRemove = (trackId: string): Command => ({ op: "track.remove", track_id: trackId });

export const assetImport = (probe: Probe, assetId: string, label: string): Command => ({
  op: "asset.import",
  asset_id: assetId,
  label,
  probe_id: probe.id,
  verified: { ...probe.verified, probe_id: probe.id },
});

export const assetRemove = (assetId: string): Command => ({ op: "asset.remove", asset_id: assetId });

export const clipAdd = (clip: Clip): Command => ({ op: "clip.add", clip });

export const clipMove = (clipId: string, trackId: string, position: number): Command => ({
  op: "clip.move",
  clip_id: clipId,
  track_id: trackId,
  position_ticks: position,
});

export const clipTrim = (clipId: string, sourceIn: number, duration: number): Command => ({
  op: "clip.trim",
  clip_id: clipId,
  source_in_ticks: sourceIn,
  duration_ticks: duration,
});

export const clipSplit = (clipId: string, at: number, rightId: string): Command => ({
  op: "clip.split",
  clip_id: clipId,
  at_ticks: at,
  right_clip_id: rightId,
});

export const clipRemove = (clipId: string): Command => ({ op: "clip.remove", clip_id: clipId });

