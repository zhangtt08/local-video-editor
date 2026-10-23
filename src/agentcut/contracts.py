"""Versioned JSON contracts; no HTTP, MCP, database, or media engine imports."""



import re
from typing import Annotated, Any, Literal, Union, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .gamut import (
    DEFAULT_FOLD_TRANSFER,
    FOLD_TRANSFERS,
    WORKING_PRIMARIES,
    fold_transfer_rows,
    gamut_presets,
)

TIMEBASE = 70_560_000

MAX_TICKS = 2**53 - 1  # JSON integers remain exact in JavaScript clients.

SCHEMA_VERSION = (

    30  # v30 lets that soft edge become a curve of its own (`mask_feather`); a v29 row can name
    #     no such property, so an older engine must fail the keyframe rather than drop the ramp. v29
    #     lets one of those box keys carry its own feather: a v28 row's key has no such field

    #     and `Contract` forbids unknown ones, so an older engine fails the row rather than quietly

    #     rendering a hard edge. v28 lets a box key ride a bezier curve: a v27 row names only

    #     linear/hold/ease, so an older engine must fail that literal rather than invent an easing.

    #     v27 lets an extra box carry its own box keys (a v26 row has none and reads as the one
    #     static box it always was). v26 lets those extra boxes follow the main mask's centre
    #     (a v25 row carries no flag and
    #     stays put, which is exactly what the missing field meant). v25 lets one clip carry a
    #     second box to cut with; a v24 row has none and reads
    #     as "just the one mask", which is exactly what the missing field meant.
    #     v24 lets that picture move: a layer carries its own keys, so a v23 row has none and
    #     reads as the static offset/scale it already carried. v23 gives that picture a place
    #     and a size; v22 rows have them absent and read as
    #     "cover the picture box", which is exactly what the missing fields meant. v22 lets a
    #     chain read a second picture; v21 rows carry no layer node at all, and an

    #     older engine must fail the union rather than guess at one. v21 lets that angle carry

    #     keyframes; v20 rows leave the curve absent and a flat angle is the very picture every

    #     one of those deliveries was measured against, so they read unchanged

)

PATH_BOX_SCHEMA_VERSION = 13  # the last shape that needs fitting on load; see `projects._fitted`

# One place: /v1/info, the OpenAPI document and the desktop shell must agree.

APP_VERSION = "1.273.0"

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]
# 1.215：读的那一侧可以写 id，也可以写**唯一的合成名**（人看得到的那一行）。
# 写命令里的 `sequence_id` 仍是 `Identifier`——身份不动；名字只在读的门上折成 id，
# 折的那一处主人是 `sequences_named`，参数类型放宽只是让值能走到它面前。
SequenceRef = Annotated[str, Field(min_length=1, max_length=256)]

Ticks = Annotated[int, Field(ge=0, le=MAX_TICKS)]

Duration = Annotated[int, Field(gt=0, le=MAX_TICKS)]

Revision = Annotated[int, Field(ge=0, le=MAX_TICKS)]





class Contract(BaseModel):

    model_config = ConfigDict(extra="forbid", strict=True)





class FrameRate(Contract):

    numerator: Annotated[int, Field(gt=0, le=240_000)] = 30

    denominator: Annotated[int, Field(gt=0, le=10_000)] = 1





class SequenceSettings(Contract):

    timebase: Literal[70_560_000] = TIMEBASE

    frame_rate: FrameRate = Field(default_factory=FrameRate)

    sample_rate: Literal[44_100, 48_000, 96_000] = 48_000

    width: Annotated[int, Field(gt=0, le=16_384)] = 1920

    height: Annotated[int, Field(gt=0, le=16_384)] = 1080

    master_gain: Annotated[float, Field(ge=0, le=4)] = 1.0

    master_limiter: bool = False

    master_ceiling_dbtp: Annotated[float, Field(ge=-12.0, le=0.0)] = -1.0

    # A marked range, in whole frames, for partial export and four-point editing. Both or neither:

    # half a range has no meaning, and a sub-frame mark would make the exporter's frame count and

    # the interface's ruler disagree.

    in_ticks: Annotated[int, Field(ge=0)] | None = None

    out_ticks: Annotated[int, Field(ge=0)] | None = None

    # Which broadcast guide to draw over the monitor. Display state, not render state: nothing about

    # the export changes, so the inset numbers below are the single authority for the overlay.

    safe_area: Literal["off", "action", "title"] = "off"

    # 工程图（调色之后那一幅）按哪档基色解释。默认 `rec709` 就是今天的老样子：不多一级、不折

    # 任何东西，任何一份旧工程读进来画面都不变。可选名单在 `gamut.WORKING_PRIMARIES`，这里不

    # 另写一份；素材自己从哪档来仍由那一段的色彩管理判断（`clip.color_manage` 只管曲线）。

    working_primaries: str = "rec709"



    @model_validator(mode="after")

    def known_working_primaries(self):

        if self.working_primaries not in WORKING_PRIMARIES:

            raise ValueError(

                "工程基色只认 "

                + "、".join(WORKING_PRIMARIES)

                + f"（名单在 gamut，这里不另写一份），来的是 {self.working_primaries}"

            )

        return self



    # 上面那一趟折叠在乘那九个数之前，把存储值抬进线性光用的是哪档曲线。名单在

    # `gamut.TRANSFER_CURVES`，这里不另写一份；默认那一档就是 1.153 以来一直在用的那一条，

    # 所以任何一份旧工程读进来，那张立方体与预览那两级表都不变。为什么要交出来声明：同一个

    # 名字有两条曲线是量出来的（两条各自差多少写在 `gamut` 那张表上面），而「这一幅实际是谁

    # 编的」引擎不知道——猜一次就把一个已经量过的折叠换成另一个没量过的。

    fold_transfer: str = DEFAULT_FOLD_TRANSFER



    @model_validator(mode="after")

    def known_fold_transfer(self):

        if self.fold_transfer not in FOLD_TRANSFERS:

            raise ValueError(

                "折叠曲线只认 "

                + "、".join(FOLD_TRANSFERS)

                + f"（名单在 gamut，这里不另写一份），来的是 {self.fold_transfer}"

            )

        return self



    @model_validator(mode="after")

    def exact_frame_clock(self):

        if (self.timebase * self.frame_rate.denominator) % self.frame_rate.numerator:

            raise ValueError("frame rate cannot be represented exactly by this timebase")

        if self.timebase % self.sample_rate:

            raise ValueError("sample rate cannot be represented exactly by this timebase")

        if (self.in_ticks is None) != (self.out_ticks is None):

            raise ValueError("a marked range needs both an in and an out point")

        if self.in_ticks is not None:

            if self.in_ticks % self.frame_ticks or self.out_ticks % self.frame_ticks:

                raise ValueError("marks have to sit on whole frames")

            if self.in_ticks >= self.out_ticks:

                raise ValueError("the in point has to be before the out point")

        return self



    @property

    def frame_ticks(self) -> int:

        return self.timebase * self.frame_rate.denominator // self.frame_rate.numerator





class VerifiedMedia(Contract):

    """A media file the media service resolved, hashed and probed itself."""



    probe_id: Identifier

    path: Annotated[str, Field(min_length=1, max_length=2048)]

    kind: Literal["video", "audio", "image"]

    label: Annotated[str, Field(min_length=1, max_length=256)]

    size_bytes: Annotated[int, Field(ge=0)]

    content_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    duration_ticks: Ticks

    width: Annotated[int | None, Field(ge=0, le=16_384)] = None

    height: Annotated[int | None, Field(ge=0, le=16_384)] = None

    frame_rate: FrameRate | None = None

    has_audio: bool = False

    audio_sample_rate: Annotated[int | None, Field(ge=0)] = None

    audio_channels: Annotated[int | None, Field(ge=0)] = None

    video_codec: Annotated[str | None, Field(max_length=64)] = None

    audio_codec: Annotated[str | None, Field(max_length=64)] = None

    # The colour tags as the file itself spelled them, read by the probe and stored with the

    # record. `None` here is a fact about the file (it said nothing), not an invitation to assume:

    # see `colortags.detect_space`.

    color_space: Annotated[str | None, Field(max_length=32)] = None

    color_primaries: Annotated[str | None, Field(max_length=32)] = None

    color_transfer: Annotated[str | None, Field(max_length=32)] = None

    color_range: Annotated[str | None, Field(max_length=32)] = None

    mtime: Annotated[int, Field(ge=0)] = 0

    cached_at: Annotated[str, Field(max_length=64)] = ""





class Asset(Contract):

    id: Identifier

    kind: Literal["video", "audio", "image", "text", "sequence"]

    label: Annotated[str, Field(min_length=1, max_length=256)]

    reference: Annotated[str, Field(min_length=1, max_length=2048)]

    duration_ticks: Duration | None = None

    verified: VerifiedMedia | None = None

    sequence_id: Identifier | None = None



    @model_validator(mode="after")

    def timed_media(self):

        if self.kind in {"video", "audio"} and self.duration_ticks is None:

            raise ValueError("video/audio metadata requires duration_ticks")

        if (self.kind == "sequence") != (self.sequence_id is not None):

            raise ValueError("sequence assets require sequence_id; media assets cannot carry it")

        if self.kind == "sequence" and self.verified is not None:

            raise ValueError("sequences are generated, not verified files")

        return self





class MediaProbe(Contract):

    """Server-issued import handle. Clients reference it by id; they never hand back a path."""



    id: Identifier

    verified: VerifiedMedia

    thumbnails: Annotated[list[str], Field(max_length=32)] = Field(default_factory=list)

    waveform: Annotated[list[float], Field(max_length=4096)] = Field(default_factory=list)

    cache_dir: Annotated[str, Field(min_length=1, max_length=2048)]

    latency_ms: int = 0





BlendMode = Literal[

    "normal", "multiply", "screen", "overlay", "darken", "lighten", "difference", "exclusion"

]





class Track(Contract):

    id: Identifier

    kind: Literal["video", "audio"]

    name: Annotated[str, Field(min_length=1, max_length=128)]

    muted: bool = False

    hidden: bool = False

    locked: bool = False

    volume: Annotated[float, Field(ge=0, le=4)] = 1.0

    blend_mode: BlendMode = "normal"





EffectProperty = Literal["x", "y", "scale", "rotation", "opacity", "gain"]

# 1.98: soft focus joins the keyable set, but through its own compiled staircase rather than through

# the scalar-expression path above — `gblur` cannot read an expression for its sigma, so

# `animation.spatial_schedule` turns the curve into windows that both ends consume (see

# `SPATIAL_SCHEDULE_MAX`). 1.123: the unsharp mask joins the same way, with one twist — its amount

# and its radius are two curves that have to step on the same frame, so they compile together

# (`animation.sharpen_schedule`) into one window table. Each step of that table costs a `gblur`

# *and* a `blend`, which measures dearer than the bare `gblur` soft focus needs, so it carries its

# own, smaller ceiling (`SHARPEN_SCHEDULE_MAX`). `denoise` stays patch-only: the browser has no FFT

# denoise at all, so a curve there would be a promise one end cannot keep.

SpatialProperty = Literal["blur", "sharpen", "sharpen_radius"]

# What `clip.patch` may write is wider than what can be keyframed: `denoise` has no per-frame form.

EffectField = EffectProperty | SpatialProperty | Literal["denoise"]

# Rectangle and ellipse masks keyframe in the mask's own normalized space, so the exporter and the

# browser interpolate the same numbers. A free-form (path) mask rasterizes its outline once and can

# be moved with mask_x/mask_y; its drawn shape now animates too, but through its own table — one

# outline per moment (`Clip.mask_shape_keys`), not a scalar curve per vertex. `MaskShapeKeyframe`.

MaskProperty = Literal[
    "mask_x", "mask_y", "mask_width", "mask_height", "mask_rotation", "mask_feather"
]

# 1.165: 角度也在这一族里，但它不是斜坡。预览那张图只能按窗换（上一轮量过：`mask-image` 不吃图层

# 的 `transform`），所以 `animation.mask_rotation_schedule` 把曲线采成整帧对齐的常值窗，导出按同一份

# 窗表拼角度的分段式子——阶梯是唯一权威，两端不许各算一条。1.259：软边同一条理——那条斜坡住在

# 烘出来的那张图里（`masks.svg_image` 的渐变停靠点），CSS 没有能改它的量，所以带软边针的那一块

# 也按窗走（见 `animation.mask_box_schedule` 那一处判断）。

MASK_FIELDS = {

    "mask_x": "center_x",

    "mask_y": "center_y",

    "mask_width": "width",

    "mask_height": "height",

    "mask_rotation": "rotation",

    # 1.259：软边也是这一族的一个数（0..1，与那一格自己声明的同一条带）。

    "mask_feather": "feather",

}

MASK_SIZE_FIELDS = {"mask_width", "mask_height"}
# 1.258：那一串框点数的名字表——次序必须与 `animation.MASK_EXTRA_FIELDS` 逐位相同（有门禁按位对），
# 导出那一步靠它取值名。1.259 起它就是 `MASK_FIELDS` 本身：主遮罩那六个数与再叠那一块的六个数，
# 名字与次序从此是一个主人。

MASK_BOX_VALUES = tuple(MASK_FIELDS)
# 1.221：一条片段可以再叠几块**矩形/椭圆**的遮罩，与主遮罩相乘（交集）。
# 上限 4 是把「两端的图都要各出一张」这件事收在一个能预算的数上：导出那条 alpha 是
# `alpha(X,Y)*A*B*C*D`，浏览器那一侧是 `mask-composite: intersect` 叠同样几层。
MASK_STACK_LIMIT = 4

Property = EffectProperty | MaskProperty | SpatialProperty

PROPERTY_LIMITS = {

    "x": (-2, 2),

    "y": (-2, 2),

    "scale": (0.05, 4),

    "rotation": (-360, 360),

    "opacity": (0, 1),

    "gain": (0, 4),

    "mask_x": (0, 1),

    "mask_y": (0, 1),

    "mask_width": (0.01, 2),

    "mask_height": (0.01, 2),

    "mask_feather": (0.0, 1.0),

}





# Soft focus as a fraction of the frame height: sigma_px = blur * height, so one number looks

# the same at every delivery size. `gblur=sigma=` in the export and `filter: blur(Ncqh)` in the

# preview are the same Gaussian by definition (a CSS blur radius *is* a standard deviation),

# which is why this is a fraction rather than the "degree" people type into 剪映.

#

# Measured on the FFmpeg and the Chromium this app ships, using a step edge and reading where the

# profile crosses 50%, 84.13% and 15.87% (those three points give the standard deviation directly):

# `gblur=sigma=S` at the default `steps=1` really behaves like 0.81*S, which is why the exporter

# asks for `steps=6`. Over a nominal radius of 1..64 px that measures 0.954..0.991 * S, and

# Chromium's `blur(Rpx)` over the same band measures 0.96..1.07 * R, so both ends land on the same

# radius within about 2% above 8 px and within half a pixel below it.

#

# `BLUR_LIMIT` is a quarter of the frame height because past that the picture has already averaged

# into one color. `BLUR_RADIUS_LIMIT_PX` is the top of the measured band — the step-edge probe runs

# out of contrast above it, so a bigger radius is refused by name rather than claimed as verified.

# One refusal that 1.98 already answered: `gblur` has no per-frame sigma, only the on/off `enable`

# window, so an animated radius is a staircase and the staircase is the single authority

# (`animation.spatial_schedule`) — the exporter chains `gblur=sigma=…:enable='between(t,…)'` per

# step and the browser animates the very same steps (`easing: "steps(1, end)"`), so neither end

# quietly smooths over what the other is doing. The unsharp mask is now keyed the same way (1.123),

# through `animation.sharpen_schedule`, because `blend` also honours `enable`: measured on the

# FFmpeg this app ships, amount 3 gated to 0.9..1.3 s left frames 5, 25 and 55 bit-identical to the

# same graph with amount 0, and changed only 31 and 37.

BLUR_LIMIT = 0.25

BLUR_RADIUS_LIMIT_PX = 64.0

GBLUR_STEPS = 6

# How many on/off windows one animated soft-focus curve may compile into. Each step is one extra

# `gblur` stage in the export graph, and the browser animates the same count, so this is the one

# number that bounds both ends' cost. Measured here: three chained `gblur` stages encode six

# seconds of 320x180 in 0.12 s, so twenty-four is comfortably affordable while still being coarse

# enough that a long ramp is scheduled in wide steps rather than one step per frame.

SPATIAL_SCHEDULE_MAX = 24

# The unsharp staircase gets its own, smaller ceiling because a step here is a pair of stages, not

# one: `split` once for the whole chain, then a `gblur` and a `blend` per window. Measured on the

# FFmpeg this app ships (6 s of testsrc, libx264 ultrafast, chained windows of one unsharp mask):

# 320x180 encodes in 0.47 s with one window, 1.35 s with four, 2.53 s with eight, 3.68 s with

# twelve, 7.18 s with twenty-four — linear, about 0.29 s per extra window at this size, and 1280x720

# costs the same per window as 320x180 at this preset. Eight keeps one animated knob inside roughly

# five times the static cost; past that a focus-pull ramp would be scheduled in steps too fine to

# see and too expensive to deliver.

SHARPEN_SCHEDULE_MAX = 8

# A morphing free-form mask compiles the same way: one frame-aligned window per constant outline,

# and both ends read that one list. The ceiling has to be smaller than the soft-focus one because a

# window here is a rasterised plate, not a number — `masks.coverage` is a Python scanline fill, so

# the cost of a window grows with the area the outline covers (measured below, in `docs/api.md`).

MASK_SHAPE_SCHEDULE_MAX = 12

# How many outlines one mask may carry. Each one is a whole vertex table in project state, so this

# is the budget that keeps a morph affordable to save, undo, and rasterise; the interface counts it

# out of `capabilities.limits` rather than carrying its own number.

# 1.165: 一枚会转的遮罩最多切成几段窗。每窗一张等比图随预览清单下发，导出那边每窗折进角度式子里

# 的一次 `if`；上限只有这一个数，两端都读它。

MASK_ROTATION_SCHEDULE_MAX = 12

MASK_SHAPE_KEY_LIMIT = 32

# 1.266：一次导入最多几条字幕。这个数过去只写在 `subtitles.parse_srt` 的那一句英文里，
# 既不在能力表、也不在拒绝的 details 里——人被挡住时看不见上限，Agent 也问不到。
# 现在它是这唯一的一处，能力表下发它，拒绝带着「第几条撞上上限」一起交回。

SUBTITLE_CUE_LIMIT = 2000

# 1.268：一次节拍分析最多交回几枚位置。它不是标记的总上限（那个是 2000），而是「一次点下去
# 界面上不会多到没法读」的那一档：30 秒 120 BPM 是 60 枚，512 足够一整首三分半的曲子。
BEAT_MARK_LIMIT = 512

# 1.238: 再叠的那一块自己最多带几枚框点。它们不是 `clip.keyframes` 里那五条曲线——
# 一套点说的是一整块盒子的五个数（中心两个、宽高、角度），同一次窗切段里一起换。
MASK_EXTRA_KEY_LIMIT = 24

# A keyframed radius is bounded by the very same ceiling the static knob uses, so a curve

# cannot reach past what one click can. It lives down here because `BLUR_LIMIT` is defined

# after `PROPERTY_LIMITS`.

PROPERTY_LIMITS["blur"] = (0.0, BLUR_LIMIT)

# Sharpen is an unsharp mask, so it carries the two numbers that operation always has: an amount

# (what 剪映 calls the degree, AE and Resolve call Amount) and a radius. The radius uses the same

# unit as soft focus - a fraction of the frame height, capped by the same measured band - because

# a fixed 3x3 Laplacian kernel would look different at 1080p and 4K, and this project's knobs are

# defined against the frame, not a pixel count. Default ~4 px at 1080p: edge, not glow.

SHARPEN_LIMIT = 2.0

SHARPEN_RADIUS_DEFAULT = 0.004

# A keyframed unsharp knob is bounded by the very same ceilings the static knobs use, so a curve

# cannot reach past what one click can: the amount tops out where the slider does, and the radius

# shares soft focus's measured band because it is the same fraction of the same frame.

PROPERTY_LIMITS["sharpen"] = (0.0, SHARPEN_LIMIT)

PROPERTY_LIMITS["sharpen_radius"] = (0.0, BLUR_LIMIT)

# 一条角度曲线的针能到的范围，就是那颗旋钮能到的范围：静态拧得到的，曲线不许超过它。

# 常数定义在这儿——`PROPERTY_LIMITS` 与 `ShapeMask` 都要读它，谁也不能自带另一个数。

MASK_ROTATION_LIMIT = 360.0

PROPERTY_LIMITS["mask_rotation"] = (-MASK_ROTATION_LIMIT, MASK_ROTATION_LIMIT)

# 音频降噪：一个旋钮，dB of broadband reduction handed straight to FFmpeg's `afftdn=nr=`.

# 24 dB is where the filter starts eating speech on the measured fixture, so that is the ceiling.

DENOISE_LIMIT = 24.0

# The floor the gate is told to look for. FFmpeg's own default (-50) sits under the hiss of a

# real room recording, which leaves the knob reducing nothing at all; measured, -30 dBFS is

# where one knob position becomes the reduction the label promises.

DENOISE_FLOOR_DB = -30.0

# Stabilisation: how much of the frame may be spent hiding the borders the correction exposes, and

# how wide a window decides which part of the motion is the intended one (30 frames at 30fps = 1s).

STABILIZE_STRENGTH_LIMIT = 1.0

STABILIZE_MAX_CROP_LIMIT = 0.25

STABILIZE_SMOOTHING_FRAMES = 30

# Mask tracking: how long a lost target keeps being guessed (and searched for again) before the path

# is said to be lost, and how far the picture is shrunk for the sweep that looks for it everywhere.

# 60 frames is two seconds at 30fps — long enough for a person to walk behind a column, short enough

# that the guesses stay near the last real sighting.

TRACK_GAP_DEFAULT = 60

TRACK_GAP_MAX = 240

TRACK_REAQUIRE_SCALE = 4

# One tracking run is a synchronous analysis, so its length has a ceiling: 900 frames is thirty

# seconds at 30fps, and measured at 20-45 ms per frame that is a run of a few tens of seconds. The

# interface must ask for the whole remaining clip and say so when the clip is longer than this —

# a window narrower than the clip is what makes a tracked mask silently hold still.

TRACK_FRAMES_MIN = 2

TRACK_FRAMES_MAX = 900

# How many subjects one run may follow. Each target costs its own correlation pass, so the

# ceiling bounds the synchronous call the way TRACK_FRAMES_MAX bounds one target's window; the

# interface reads this number from capabilities.limits and must not carry its own.

TRACK_TARGET_LIMIT = 8





def spatial_radius(fraction: float, frame_height: int) -> float:

    """The one definition of a spatial radius: this fraction of the frame height, in pixels.



    Soft focus and sharpening share it. The export writes it as `gblur=sigma=`; the preview writes

    the same fraction as `blur(<fraction*100>cqh)` or, for the sharpening Gaussian, as an

    `objectBoundingBox` `feGaussianBlur` stdDeviation pair derived from the delivery aspect. All of

    them are the same number of pixels because the units are defined against the frame, so neither

    end is free to invent its own units for "how blurry" or "how sharp".

    """

    return fraction * frame_height





class ClipEffects(Contract):

    x: Annotated[float, Field(ge=-2, le=2)] = 0.0

    y: Annotated[float, Field(ge=-2, le=2)] = 0.0

    scale: Annotated[float, Field(ge=0.05, le=4)] = 1.0

    rotation: Annotated[float, Field(ge=-360, le=360)] = 0.0

    opacity: Annotated[float, Field(ge=0, le=1)] = 1.0

    gain: Annotated[float, Field(ge=0, le=4)] = 1.0

    blur: Annotated[float, Field(ge=0, le=BLUR_LIMIT)] = 0.0

    # Unsharp mask, one formula on both ends:

    #     out = clip(source + sharpen * (source - gaussian(source)), 0, 255)

    # The export runs `split` + `gblur=...:steps=6:planes=7` + a `blend` with

    # `c*_expr='clip(A+a*(A-B),0,255)'` and `c3_expr='A'`. The `clip()` is load-bearing:

    # measured, `blend` without it wraps modulo 256 instead of clamping (255+0.8*69 read back

    # as 54). The preview runs `feGaussianBlur` + `feComposite operator="arithmetic"` with

    # k2=1+a, k3=-a, which clamps by definition; on a hard edge the two agree to <=3 levels

    # (export 77/68/57/44, browser 74/65/54/43, plate at 100). Both knobs keyframe from 1.123,

    # through the same compiled window table the amount and the radius share, and both stay inside

    # the measured band.

    sharpen: Annotated[float, Field(ge=0, le=SHARPEN_LIMIT)] = 0.0

    sharpen_radius: Annotated[float, Field(ge=0, le=BLUR_LIMIT)] = SHARPEN_RADIUS_DEFAULT

    # 音频降噪只在导出里生效：浏览器预览没有等价的 FFT 降噪，宁可写明「导出才有」，也不在预览里

    # 演一个交付文件里没有的效果（母带限制器同一待遇）。0 就是不加这一级。

    denoise: Annotated[float, Field(ge=0, le=DENOISE_LIMIT)] = 0.0





# The grade chain's shape limits live here and nowhere else: the interface enumerates its picker and

# clamps its inputs from `capabilities.grade_limits`, so a node the compiler cannot honour can never

# be built by hand. `LUT_SAMPLE_LIMIT` is 1024 because a `.cube` 1D table ships with 256 or 1024

# rows as often as 33 — a limit below that would refuse files people already own.

CURVE_POINT_LIMIT = 16

LUT_SAMPLE_LIMIT = 1024

# The levels node's own ranges, published through `capabilities.grade_limits` so the interface

# cannot offer a stretch the compiler would refuse. `black` and `white` are input points on the

# 0..1 axis, and they must leave a real span between them: `white > black` is checked below.

LEVELS_BLACK_MAX = 0.9

LEVELS_WHITE_MIN = 0.1

LEVELS_GAMMA_MIN = 0.1

LEVELS_GAMMA_MAX = 10.0

# The channel mixer's coefficients: wide enough to swap and amplify channels (a hue-rotate needs

# values past 1), narrow enough that a mistyped matrix cannot multiply a channel by a thousand.

MATRIX_LIMIT = 4.0

# Auto levels decodes the clip's own frames: how many, and how much of the picture may be clipped

# at each end. Half a percent is the broadcast convention, and the ceiling is generous enough that

# an editor can ask for a hard clip on a noisy source.

AUTO_GRADE_SAMPLES_MAX = 24

AUTO_GRADE_SAMPLES_DEFAULT = 12

AUTO_PERCENTILE_MAX = 0.10

AUTO_PERCENTILE_DEFAULT = 0.005





class GradeCurvePoint(Contract):

    x: Annotated[float, Field(ge=0, le=1)]

    y: Annotated[float, Field(ge=-0.5, le=1.5)]





# Every node blends its own result with its input by this strength, like Resolve's Mix slider.

GradeMix = Annotated[float, Field(ge=0, le=1)]

# 并联节点混频台上的一路增益。上限 2 而不是 1：达芬奇那排旋钮能把一路拉过另一路，

# 只给 0..1 就压不出「这一条分支说了算」的那种偏置。

# 接口的上限与 `capabilities.grade_limits` 下发的是同一个数——界面 clamp 自己的输入框、

# 契约拒绝写入，两端永远是一个数。

GRADE_BRANCH_WEIGHT_MAX = 2.0

GradeBranchWeight = Annotated[float, Field(ge=0, le=GRADE_BRANCH_WEIGHT_MAX)]





# The transfer-function names, in the order the interface lists them. `COLOR_SPACES` is what

# the engine publishes; a renderer that typed its own list would drift from this one silently.

COLOR_SPACES: tuple[str, ...] = (

    "linear",

    "srgb",

    "gamma18",

    "gamma20",

    "gamma22",

    "gamma24",

    "rec709",

)

ColorSpace = Literal["linear", "srgb", "gamma18", "gamma20", "gamma22", "gamma24", "rec709"]



# 1.150: which file-carried tag spells which of the seven curves above. The transfer

# characteristic (`-color_trc` when writing, `color_transfer` when ffprobe reads it back) is the

# only tag that names a tone curve: the matrix coefficients (`color_space`) say how Y/R'G'B' is

# folded and the primaries say where the phosphors sit — neither determines the curve, so neither

# is used here, and a file that tags only those comes back as undetected rather than guessed at.

# These four rows are the names this release read off its own bundled FFmpeg: writing

# `-color_trc bt709|iec61966-2-1|linear` returns that same spelling, while writing

# `-color_trc gamma22` returns `bt470m` (one stored enum, two names), and `-color_trc unknown`

# writes no `color_transfer` key at all. A tag that is present but absent from this table — e.g.

# the `smpte170m` an SD file carries — is a named refusal, not a silent default. `gamma18`,

# `gamma20` and `gamma24` have no measured tag, so those three stay a manual choice.

COLOR_TRANSFER_TAGS: tuple[tuple[str, ColorSpace], ...] = (

    ("iec61966-2-1", "srgb"),

    ("bt709", "rec709"),

    ("bt470m", "gamma22"),

    ("linear", "linear"),

)



# 1.151: what a delivered master may declare about its own colour. One row, because that is all

# this engine can state truthfully today: the timeline renders display-referred values and the

# colour-managed chain's display end defaults to Rec.709, and the RGB->YUV fold is the third thing a

# `bt709` tag asserts. The fold is *not* free — bundled FFmpeg leaves it to the encoder's own

# swscale context, which measures as BT.601 (the fixture's solid colour lands at RGB (126,63,30) and

# comes back YUV=(83,104,158), the BT.601 prediction), so naming the tag also swaps the last stage

# of the graph to planar RGB at the preset's own depth followed by `zscale=matrix=709` (the same

# source then measures (80,107,157), i.e. BT.709). The RGB stage is not decoration: `zscale` refuses

# a YUV input outright (`code 3074: no path between colorspaces`), which is what a tagged delivery

# of real footage hit before it. Writing the tag without swapping the fold is the lie this row

# exists to prevent.

OUTPUT_COLOUR_TAGS: tuple[dict[str, str], ...] = (

    {

        "id": "bt709",

        "label": "BT.709（高清显示端交接母版）",

        "primaries": "bt709",

        "transfer": "bt709",

        "matrix": "bt709",

        # The values this build's `zscale` takes for the same matrix and the same range

        # (`-h filter=zscale` lists both spellings; the short ones are what its table shows

        # first). `range` has to be said out loud: left at "input", zscale takes an RGB source's

        # full range with it and the file comes back `yuvj420p` + `color_range=pc` while the

        # samples are limited-range numbers — a second container claim that the pixels contradict.

        "zscale_matrix": "709",

        "zscale_range": "tv",

    },

    # 1.152 第二档。名字要说它真的做的事：这一档改的是**折叠**，不是基色。工程的 RGB 就是

    # 709/sRGB 那套基色，所以基色与曲线照旧声明 bt709，只有 RGB→YUV 那组系数换成 601，交出的

    # 是一张「按 601 折、按 709 读」的老式母版——标清带与不少硬件/播放器就认这一套。

    # 三个数都是量回来的（64×36 纯色 (126,63,30)，随包 FFmpeg 6.1.1）：`zscale=matrix=170m` 折出

    # (83,104,158)，与 ITU-R BT.601 那组 0.299/0.587/0.114 的独立算式一字不差；mp4 与 MXF 两个

    # 容器都把 `color_space=smpte170m`+`color_primaries=bt709`+`color_trc=bt709`+`color_range=tv`

    # 原样读回；按这四样解回 RGB 得 (126,63,30)，与源差 (0,0,0)。

    {

        "id": "bt601",

        "label": "BT.601 折叠（标清与老母版：矩阵按 601，基色与曲线仍是工程的 709）",

        "primaries": "bt709",

        "transfer": "bt709",

        "matrix": "smpte170m",

        # 随包 zscale 认的短拼法是 `170m`（`-h filter=zscale` 那张表先列它），长拼法 `smpte170m`

        # 也在表里；容器那一侧要写的值是 FFmpeg 的枚举名 `smpte170m`，两边不是一回事，所以分开写。

        "zscale_matrix": "170m",

        "zscale_range": "tv",

    },

    # 1.153 第三档：宽色域。这一档**换基色**，所以它比前两档多两件事——图里要多一站，而那一站的

    # 九个数必须有外部出处。`shift_from`/`shift_to` 就是「图里那份 RGB 的基色」与「容器声明的基色」

    # 两端；渲染器据此把立方体交给 `lut3d`（`gamut.delivery_cube`），折叠再按 2020-NCL 走。

    # 数都是量回来的（64×36 素材里那一格 (126,63,30)，随包 FFmpeg 6.1.1）：交出的 YUV

    # (81,109,146)，与「BT.2020 公布的 rec709→rec2020 那张表 + 0.2627/0.6780/0.0593 系数」独立算出

    # 的 (82,109,145) 差 (1,0,1)；容器读回 `color_space=bt2020nc`＋`color_primaries=bt2020`＋

    # `bt709`＋`tv`，mp4 与 MXF 都一样；一台老实的观看者按这四样解回来得 (126,62,28)，与源差

    # (0,1,2)。判「这句基色兑不兑得了现」用纯色（`flat_suite`）：五种画面格式各取一条代表，

    # 每片纯色按容器那四样标记解回来，最差的一条不超过判据 4 阶就算过，所以这一档不挑预设。

    # 量到的阶数由那把尺当场核对 README 那一行；注释不再抄一份会过期的数——1.156 就是被这种

    # 手抄绊过一次。立方体在格与格之间的插值用 2×2 块的渐变判（`ramp_suite`），格数本身用

    # 数学判（`cube_suite`：33³ 的格子）。

    # 这一档也是那条规矩的来源：**互逆的一对错曲线是自洽检查抓不到的**。把 BT.709 编码侧的 0.45

    # 与解码侧的 1/0.45 对调之后，纯色往返、恒等立方体的控制组全都照常绿，只有换基色把某个通道

    # 推到极暗时才会把它算成负数、被夹成 0，量到解回差 85 阶。渐变逐列比就是为这个洞放的。

    # 为什么不用 `colorchannelmixer`：那一站乘的是存储值，基色转换必须在线性光里做；1.152 实测

    # 「zscale 进线性 → colorchannelmixer → 回 709」这一对在 16 位上仍与标准算式差 3–7 阶。

    # 下一档（P3-D65）见下面那一段：1.153 在这里写下的那句「要做真正的色域压缩」是错的，

    # 错的缘由与这一条同族——一对互为逆阵的矩阵，方向用反了也仍然自洽。

    {

        "id": "bt2020",

        "label": (

            "BT.2020 宽色母版（基色按 BT.2020 公布表换过去，曲线仍是 709；"

            "浏览器不做宽色域管理，所以预览会比成片淡，导出的那一份才是按标准算式量过的那一张。"

            "按容器标记解回纯色，表里五种画面格式（含 8 位 4:2:0）都不差 1 阶）"

        ),

        "primaries": "bt2020",

        "transfer": "bt709",

        "matrix": "bt2020nc",

        "zscale_matrix": "2020_ncl",

        "zscale_range": "tv",

        "shift_from": "rec709",

        "shift_to": "rec2020",

    },

    # P3-D65（容器里写 `smpte432`）这一档 1.156 交出去了，交出去的第一步是把 1.153 写在这里的

    # 那句谎话推翻：当时记的是「把 709 的画面换进 P3-D65 之后按标记解回来，蓝通道被夹掉 30 阶

    # （709 的绿原色在 P3-D65 之外），那是需要真正的色域压缩」。量的数是反的——那句话说的

    # 是 **P3→709** 那张表的动作，而不是交付要乘的那一张。两张表都在 `tests/gamut_check.py`

    # 那颗锚上（1.52 对过公布值的九个数除以行和）：

    #   709→P3-D65 = 0.82246 0.17754 0 / 0.03319 0.96681 0 / 0.01708 0.07240 0.91052，

    #     九个系数全非负、每行和为 1，33³ 的 35937 格里**一格都不出 [0,1]**；

    #   P3-D65→709 = 1.22494 -0.22494 0 / …，最小系数 -0.22494，35937 格里 16413 格出界。

    # 几何上这件事没有争议：两档同蓝原色 (0.150,0.060)、同 D65 白点，P3 只是把红与绿往外推，

    # 所以 709 的整张三角形在 P3 之内——把画面搬进 P3 是**放宽**，不夹不压，一张矩阵就说完了。

    # 于是这一档与 `bt709`／`bt2020` 同进同退：折叠与曲线照旧是 BT.709 的那一组（`matrix=709`、

    # 容器写 `bt709`/`bt709`/`smpte432`——广色屏的 Y′CbCr 用 709 系数是这一档的常规写法，

    # 也是这一条链真正做了的两件事，标签只写做了的），换基色那一站由立方体做。

    # 「哪一张矩阵才会夹」这一条不是记在文档里，是钉在 `tests/colour_tag_check.py` 的

    # `compression_suite` 上：它对表里每一个换基色的档双向判——前向那张必须一格都不出界，

    # 反向那张必须真出界（谁把矩阵写成反方向，立方体立刻被夹，那条当场红）。

    {

        "id": "p3-d65",

        "label": (

            "P3-D65 广色母版（基色按 P3-D65 原色换过去，曲线与折叠仍是 709；"

            "709 的三原色都在 P3-D65 之内，这一档是放宽不是压缩，立方体每一格都落在画面里。"

            "浏览器不做宽色域管理，所以预览会比成片淡）"

        ),

        "primaries": "smpte432",

        "transfer": "bt709",

        "matrix": "bt709",

        "zscale_matrix": "709",

        "zscale_range": "tv",

        "shift_from": "rec709",

        "shift_to": "p3-d65",

    },

)



# The closed vocabulary an Agent may name. It is derived from the table, never written twice.

COLOUR_TAG_CODES = tuple(str(row["id"]) for row in OUTPUT_COLOUR_TAGS)





def colour_tag_presets() -> dict[str, list[str]]:

    """每一档带得出去的预设 id——只在这一处算，引擎的拒绝与界面的灰态共读这一份。



    三档是同一份名单：能不能挂标记只由「有没有容器、有没有画面」说话，与是哪一档无关。

    宽色域那一档一度在这里额外要求 10 位 4:4:4，把那条要求撤掉是因为撑它的那把量具自己不成

    立：那条渐变每两个像素换一次色度，4:2:0（乃至 4:2:2）本来就带不动，同一份像素上连不带

    立方体的控制档都解到 126 阶——那个数说的是抽样，不是「基色是 2020」这句话。换成一纯色

    去量（基色声明真假所指的就是这个）：五种画面格式各取一条、三片贴着 709 边界的暗饱和纯色，最差

    是 8 位 4:2:0 的 2 阶，控制档 1 阶。判据与这两个数都由 `colour_tag_check` 当场重量。

    """

    picture = [

        str(item["id"])

        for item in render_presets()

        if not item["sequence"] and item["codec"] is not None

    ]

    return {str(row["id"]): picture for row in OUTPUT_COLOUR_TAGS}





class GradeCurve(Contract):

    """Per-channel transfer curve; the engine samples it into the shared 8-bit table."""



    kind: Literal["curve"] = "curve"

    channel: Literal["rgb", "red", "green", "blue"] = "rgb"

    points: Annotated[list[GradeCurvePoint], Field(min_length=2, max_length=CURVE_POINT_LIMIT)]

    enabled: bool = True

    mix: GradeMix = 1.0

    blend: BlendMode = "normal"



    @model_validator(mode="after")

    def increasing_x(self):

        xs = [point.x for point in self.points]

        if any(right <= left for left, right in zip(xs, xs[1:])):

            raise ValueError("curve points must increase in x")

        return self





class GradeWhiteBalance(Contract):

    kind: Literal["white_balance"] = "white_balance"

    temperature: Annotated[float, Field(ge=-1, le=1)] = 0.0

    tint: Annotated[float, Field(ge=-1, le=1)] = 0.0

    enabled: bool = True

    mix: GradeMix = 1.0

    blend: BlendMode = "normal"





class GradeWheels(Contract):

    """Resolve-style lift/gamma/gain, one value per RGB channel."""



    kind: Literal["wheels"] = "wheels"

    lift: Annotated[list[float], Field(min_length=3, max_length=3)] = Field(

        default_factory=lambda: [0.0, 0.0, 0.0]

    )

    gamma: Annotated[list[float], Field(min_length=3, max_length=3)] = Field(

        default_factory=lambda: [1.0, 1.0, 1.0]

    )

    gain: Annotated[list[float], Field(min_length=3, max_length=3)] = Field(

        default_factory=lambda: [1.0, 1.0, 1.0]

    )

    enabled: bool = True

    mix: GradeMix = 1.0

    blend: BlendMode = "normal"



    @model_validator(mode="after")

    def ranges(self):

        if any(not -0.5 <= value <= 0.5 for value in self.lift):

            raise ValueError("lift must be in [-0.5, 0.5]")

        if any(not 0.1 <= value <= 10 for value in self.gamma):

            raise ValueError("gamma must be in [0.1, 10]")

        if any(not 0 <= value <= 4 for value in self.gain):

            raise ValueError("gain must be in [0, 4]")

        return self





class GradeLevels(Contract):

    """Input-range levels on one channel group: black point, white point, midtone gamma.



    The two input points say where this picture's own black and white sit; gamma moves the midtones

    between them without dragging either end. Like every other node here it is a per-channel

    function, so the chain still collapses to one table per channel and FFmpeg and the browser keep

    reading the same polyline. The two points are added to the sampling grid, because a stretch this

    steep is otherwise chorded away between the knots.

    """



    kind: Literal["levels"] = "levels"

    channel: Literal["rgb", "red", "green", "blue"] = "rgb"

    black: Annotated[float, Field(ge=0, le=LEVELS_BLACK_MAX)] = 0.0

    white: Annotated[float, Field(ge=LEVELS_WHITE_MIN, le=1)] = 1.0

    gamma: Annotated[float, Field(ge=LEVELS_GAMMA_MIN, le=LEVELS_GAMMA_MAX)] = 1.0

    enabled: bool = True

    mix: GradeMix = 1.0

    blend: BlendMode = "normal"



    @model_validator(mode="after")

    def ordered_points(self):

        if self.white <= self.black:

            raise ValueError("the white point must sit above the black point")

        return self





class GradeMatrix(Contract):

    """Channel mixer: one 3x3 applied to the stored picture values, row-major red/green/blue out.



    The first cross-channel node in this chain, and the reason the chain compiles to an ordered

    stage list instead of a single table: a matrix sandwiched between two per-channel curves is not

    itself a per-channel curve. Both renderers walk that list, and they walk the *same* math —

    FFmpeg's ``colorchannelmixer`` and SVG's ``feColorMatrix`` (with

    ``color-interpolation-filters="sRGB"``) are the same affine map on the same stored 8-bit values,

    so a hue shift or a BT.709 luma mix looks identical in the monitor and in the file.



    It is deliberately *not* a colour-management transform: those happen in linear light, which an

    8-bit stage on either side of the matrix cannot hold without banding in the shadows. And it has

    no ``blend`` field on purpose: blending a matrix with its input through a non-linear mode

    (``in × matrix(in)``) is no longer a matrix at all, so the contract cannot offer it.

    """



    kind: Literal["matrix"] = "matrix"

    coefficients: Annotated[list[float], Field(min_length=9, max_length=9)]

    enabled: bool = True

    mix: GradeMix = 1.0



    @model_validator(mode="after")

    def in_range(self):

        if any(not -MATRIX_LIMIT <= value <= MATRIX_LIMIT for value in self.coefficients):

            raise ValueError(f"coefficients must be within [-{MATRIX_LIMIT}, {MATRIX_LIMIT}]")

        return self





class GradeTransfer(Contract):

    """Colour-space conversion: one published EOTF in, one OETF out, applied to every channel.



    Only the transfer function is modelled — no primaries and no matrix — so a chain of these nodes

    normalises gamma (an sRGB screen recording onto a BT.1886 timeline) without pretending to be a

    full ICC/ACES pipeline. `rec709` is BT.1886 with zero black lift, which is exactly gamma 2.4;

    both names are offered because editors think in both vocabularies.

    """



    kind: Literal["transfer"] = "transfer"

    input_space: ColorSpace

    output_space: ColorSpace

    # `clip.color_manage` writes a *pair* of these and tags both, so taking it off removes

    # the two nodes that command added and nothing a person placed by hand.

    purpose: Literal["color_manage"] | None = None

    enabled: bool = True

    mix: GradeMix = 1.0

    blend: BlendMode = "normal"





class GradeLUT(Contract):

    """An imported 1D lookup table: three per-channel sample lists, one value per input level.



    This is the `.cube` `LUT_1D_SIZE` flavour — the only kind that stays a per-channel function, so

    the whole grade chain still compiles to one table per channel and both renderers keep reading

    the same data. A 3D LUT mixes channels (its output red depends on input green and blue), so it

    is a node of its own (`GradeLut3D`) that breaks the collapsed run instead of joining this

    table. Grid spacing is the importer's `1/(size-1)`; the sampler interpolates linearly between

    samples, exactly like the curve nodes' piecewise sections.

    """



    kind: Literal["lut"] = "lut"

    title: Annotated[str, Field(max_length=64)] = "LUT"

    size: Annotated[int, Field(ge=2, le=LUT_SAMPLE_LIMIT)]

    channels: Annotated[

        list[

            Annotated[

                list[Annotated[float, Field(ge=0, le=1)]],

                Field(min_length=2, max_length=LUT_SAMPLE_LIMIT),

            ]

        ],

        Field(min_length=3, max_length=3),

    ]

    enabled: bool = True

    mix: GradeMix = 1.0

    blend: BlendMode = "normal"



    @model_validator(mode="after")

    def channels_match_size(self):

        if any(len(table) != self.size for table in self.channels):

            raise ValueError("each LUT channel must carry exactly `size` samples")

        return self





# A 3D LUT is stored inline, so its grid has a ceiling of its own: 17 samples per edge = 49k floats,

# already the largest table worth keeping inside project state. Bigger files are resampled by the

# importer and say so in `resampled_from` — the deal 1.63 made for oversized 1D tables.

LUT3D_SIZE_LIMIT = 17

# Every revision re-snapshots the whole project, and an imported table travels inside that

# snapshot, so the budget on inline lookup samples is project-wide rather than per chain:

# 200,000 numbers is about 1.4 MiB of project JSON (a measured 17-cube holds 14,739 numbers in

# 101 KiB), i.e. thirteen full-size cubes or sixty-five max-size 1D tables for the whole project.

# The interface reads it from `capabilities.grade_limits`.

GRADE_INLINE_SAMPLE_LIMIT = 200_000





class GradeLut3D(Contract):

    """An imported 3D lookup table: a cube of RGB samples, cross-channel by construction.



    Output red depends on green and blue too, so this node cannot join a collapsed per-channel

    run: it breaks it as the channel matrix does, and cannot live in a parallel branch for the

    same reason. `interp` is not a knob — the exporter always asks FFmpeg for tetrahedral

    interpolation, which keeps a resampled 17-cube a smooth approximation rather than a poster.



    There is deliberately no `mix`/`blend`: the browser cannot draw this node at all

    (`capabilities.features.lut3d_preview` is false), so a strength would be a number that only ever

    moves one of the two ends — the same honesty the denoise knob is held to.

    """



    kind: Literal["lut3d"] = "lut3d"

    title: Annotated[str, Field(max_length=64)] = "3D LUT"

    size: Annotated[int, Field(ge=2, le=LUT3D_SIZE_LIMIT)]

    cells: Annotated[list[Annotated[float, Field(ge=0, le=1)]], Field(min_length=24)]

    # The importer resamples an oversized grid instead of refusing it; the original edge count

    # travels on the node, so the notice stays with the look instead of only in one reply.

    resampled_from: Annotated[int | None, Field(default=None, ge=2)] = None

    enabled: bool = True



    @model_validator(mode="after")

    def grid_matches_size(self):

        if len(self.cells) != self.size**3 * 3:

            raise ValueError("a 3D LUT needs exactly 3 * size**3 samples")

        if self.resampled_from is not None and self.resampled_from <= self.size:

            raise ValueError("resampled_from must be larger than the stored grid")

        return self





# A parallel branch stays per-channel on purpose: the node outputs the mean of its branches, and the

# mean of a cross-channel map with anything else is not something the chain can still compile to a

# table. Refusing it here is what keeps the compiler from ever meeting a matrix inside a branch.

# 1.124: a branch may now be *another mixer*. This is not new arithmetic — averaging per-channel

# functions is closed, so a whole tree still collapses to one table per channel, and

# `grade.node_function` already resolves each branch through `step_function`, which dispatches on

# `kind`. What a tree does need is a bound, checked once per chain node rather than per level:

# `GRADE_MIXER_DEPTH` counts mixers (a flat mixer is 1), and the subtree shares the chain's

# `GRADE_NODE_LIMIT`, so nesting cannot smuggle past the budget one node already had.

GradeBranch = Union[

    GradeCurve,

    GradeWhiteBalance,

    GradeWheels,

    GradeLevels,

    GradeTransfer,

    GradeLUT,

    "GradeParallel",

]



GRADE_NODE_LIMIT = 8

GRADE_BRANCH_LIMIT = 4

# 一层套一层的混频台最多几层。`capabilities.grade_limits.max_mixer_depth` 就是它，界面不许自己写。

GRADE_MIXER_DEPTH = 3


# 一条链最多叠几层外部画面。每多一层就是多解一路画面、多两段 blend，而监视器多一个 DOM 图层——

# `capabilities.grade_limits.max_layers` 下发的就是这个数，界面不许自己数。

GRADE_LAYER_LIMIT = 3

# 层自己的位置与缩放：偏移按画面框的「一半」说（1 就是整个层心挪到边外），缩放 0.05..4。

LAYER_OFFSET_MAX = 1.0

LAYER_SCALE_MIN = 0.05

LAYER_SCALE_MAX = 4.0

# 1.203：那一层自己可以转。按**度**说（与界面同一个单位，不是弧度也不是百分比），左右各到半圈；
# 半圈之外没有新形状（转 181° 就是转 -179°），所以上限就是 180，不许多给一个数。
# 这一档只能静态：针那一张名单（`LayerProperty`）里没有它，界面也就不给它的打点按钮。

LAYER_ROTATION_MAX = 180.0


# 1.192：那一层自己也能动。可动的就是它自己那三个数（不是新属性名，也不是新单位），
# 所以一根针的值域与静态那三个同一条带——否则「打点」与「填框」会给出两套合法区间。

LayerProperty = Literal["offset_x", "offset_y", "scale", "mix", "rotation"]

LAYER_KEY_LIMITS = {

    "offset_x": (-LAYER_OFFSET_MAX, LAYER_OFFSET_MAX),

    "offset_y": (-LAYER_OFFSET_MAX, LAYER_OFFSET_MAX),

    "scale": (LAYER_SCALE_MIN, LAYER_SCALE_MAX),

    # 1.198：这一层自己的淡。值域与静态那个字段 `GradeMix` 同一条带（0..1），所以「在检查器里
    # 拧」与「打一枚针」不会给出两套合法区间。
    "mix": (0.0, 1.0),

    # 1.204：转角也能打点。同一条带（±LAYER_ROTATION_MAX）——与位置、大小、淡那一个理由：
    # 「拧滑杆」与「落一枚针」必须落在同一区间里，否则界面允许、引擎拒绝。
    "rotation": (-LAYER_ROTATION_MAX, LAYER_ROTATION_MAX),

}

# 一层最多带几枚针。满了点名拒（少钉几枚，或切成两层各自动），不抽稀——与遮罩轮廓那一族同
# 一条规矩：额度是挡扩张的，不是替人挑画面的。

LAYER_KEY_LIMIT = 24

# 一份窗表最多切几段。每一段是一路 `crop` 加两段 `blend` 再加一次 `overlay`，比柔焦那一段只
# 多一个 `gblur` 贵得多，所以这一族自己带一个更小的天花板。

LAYER_SCHEDULE_MAX = 8





def branch_tree(node) -> tuple[int, int]:

    """一棵支路树的 (混频台层数, 里面的操作数)。叶子是 0 层、1 个操作。"""

    if getattr(node, "kind", "") != "parallel":

        return 0, 1

    depth = 0

    operations = 0

    for branch in node.branches:

        child_depth, child_operations = branch_tree(branch)

        depth = max(depth, child_depth)

        operations += child_operations

    return depth + 1, operations + 1





class GradeParallel(Contract):

    """Parallel node: every branch transforms this node's own input, and the node outputs the

    average of the branch results.



    This is what makes it different from putting the same operations in series — two branches that

    each pull in opposite directions average instead of stacking, so the graph stays editable rather

    than a pile of compounding corrections. Averaging per-channel functions is still a per-channel

    function, so the whole graph keeps compiling down to one table per channel that both the browser

    and FFmpeg read; nothing about the render path changes.

    """



    kind: Literal["parallel"] = "parallel"

    branches: Annotated[list[GradeBranch], Field(min_length=1, max_length=GRADE_BRANCH_LIMIT)]

    enabled: bool = True

    mix: GradeMix = 1.0

    blend: BlendMode = "normal"

    # 1.120：混频台那一排旋钮。分支本身就是操作（`GradeBranch` 是这些类的联合），权重不能挂在分支上

    # ——那会让串联的曲线也长出一个没意义的旋钮。它按位置挂在节点上：给就必须给全，不给就是均分。

    # 全 0 是「这一节不改画面」而不是黑场：分支是对进来的画面做的那一映射，都不加权重就是不加。

    weights: Annotated[list[GradeBranchWeight], Field(max_length=GRADE_BRANCH_LIMIT)] = Field(

        default_factory=list

    )

    # 1.122：每一支先按自己的混合方式与进来的画面相合，再按权重取平均。全 normal 时相合就是原样，

    # 于是这一版与 1.120 逐位相同；停用的一支仍是直通（它的模式不参与，不然「直通」就名不副实）。

    blends: Annotated[list[BlendMode], Field(max_length=GRADE_BRANCH_LIMIT)] = Field(

        default_factory=list

    )



    @model_validator(mode="after")

    def matched_weights(self):

        for name, given in (("weights", self.weights), ("blends", self.blends)):

            if given and len(given) != len(self.branches):

                raise ValueError(f"branch {name} must cover every branch or none at all")

        return self



    @model_validator(mode="after")

    def bounded_tree(self):

        depth, operations = branch_tree(self)

        if depth > GRADE_MIXER_DEPTH:

            raise ValueError(

                f"a mixer tree may nest {GRADE_MIXER_DEPTH} levels deep, this one nests {depth}"

            )

        if operations > GRADE_NODE_LIMIT:

            raise ValueError(

                f"one chain node's tree may hold {GRADE_NODE_LIMIT} operations, this one holds "

                f"{operations}"

            )

        return self





# `GradeBranch` names this class before it exists, so the forward reference is resolved here — the

# union is the branch vocabulary, and a branch may be another mixer.

GradeParallel.model_rebuild()





class GradeComposite(Contract):

    """第二路画面：把这条链的输出与**进来的那幅画**相合。



    达芬奇节点图里的 Key→Mix、AE 的「与原图叠加」都是这一条边：节点图第一次有两条画面，

    而不是一条。前面那些节点全是「一幅进、一幅出」的每通道函数，这一条不是——它要读两幅画，

    所以链子在这里第一次需要 `split` 与 `blend`。



    语义只有一句：**位置不影响结果**。非-composite 的节点照常按顺序构成前向路径，

    composite 按它们在链里出现的顺序，一次接一次地把「原图」与「到目前为止的结果」相合。

    `mix` 是那一层的权重（0 = 只看原图，1 = 只看调完的），`mode` 是相合的方式。

    """



    kind: Literal["composite"] = "composite"

    mode: BlendMode = "screen"

    mix: GradeMix = 0.5

    enabled: bool = True


class Bezier(Contract):

    x1: Annotated[float, Field(ge=0, le=1)] = 1 / 3

    y1: Annotated[float, Field(ge=-4, le=4)] = 0.0

    x2: Annotated[float, Field(ge=0, le=1)] = 2 / 3

    y2: Annotated[float, Field(ge=-4, le=4)] = 1.0





class LayerKeyframe(Contract):

    """1.192：第二路画面自己的一枚针。

    尺子还是大家那一把：存的是含 `animation_offset_ticks` 的时钟，`animation.layer_value_at`
    采样时折的那一次与 `sample` 折的是同一次。这一层的针住在链里，而链是一次**状态写入**
    （`clip.color` 收进来什么就存什么），所以不在写的时候挪针——一次隐式的 rebase 会让
    dry-run、粘贴属性与撤销各数出一个落点。落在这一段之外由 `timeline._check_layer_clock`
    点名拒，不是夹住。

    三个数也不各走各的格子：`animation.layer_schedule` 一次采样那一组三元，边界一起换。
    """

    property: LayerProperty

    at_ticks: Ticks

    value: float

    interpolation: Literal["linear", "hold", "ease", "bezier"] = "linear"

    bezier: Bezier | None = None

    @model_validator(mode="after")

    def property_range(self):

        lo, hi = LAYER_KEY_LIMITS[self.property]

        if not lo <= self.value <= hi:

            raise ValueError(f"layer {self.property} must be in [{lo}, {hi}]")

        if self.bezier is not None and self.interpolation != "bezier":

            raise ValueError("bezier controls require bezier interpolation")

        return self





class GradeLayer(Contract):

    """第二路画面：把**另一张图像素材**叠在这条链的输出上（AE 的图层·达芬奇往上叠一层媒体）。



    与 `GradeComposite` 的区别只有一件事：那一条读的是这条链自己进来的那幅画，这一条读的是

    工程里另一张图，所以它带 `asset_id` 而那条边不带。相合的方式与权重是同一份词表（`BlendMode`

    与 `GradeMix`），两端逐模式逐权重量过才敢下发（见 `capabilities.features.grade_layer`）。



    位置是写进去之前就要定死的一条：这一层必须在链尾，它后面不能再有会改画面的节点。导出把各层

    按链里的顺序一段接一段相合，浏览器把每张图按同一顺序画成 DOM 图层——同序才同图；一旦有节点

    排在层后面，浏览器只能把层画在整条滤镜链之上，两端就不是同一幅画了。那种排法按 `LAYER_POSITION`

    点名拒绝，出路写清楚（把这一层拖到链尾）。

    """



    kind: Literal["layer"] = "layer"

    asset_id: Identifier

    mode: BlendMode = "screen"

    mix: GradeMix = 0.5

    # 1.190：层自己的位置与大小。三个数都按**画面框**说（0 = 画面中心，1 = 那一边的边外），
    # 与盒遮罩同一口径；缩放 1 = 铺满画面框。上下限由 `capabilities.grade_limits` 下发。
    offset_x: Annotated[float, Field(ge=-LAYER_OFFSET_MAX, le=LAYER_OFFSET_MAX)] = 0.0

    offset_y: Annotated[float, Field(ge=-LAYER_OFFSET_MAX, le=LAYER_OFFSET_MAX)] = 0.0

    scale: Annotated[float, Field(ge=LAYER_SCALE_MIN, le=LAYER_SCALE_MAX)] = 1.0

    # 1.203：这一层自己的转角，单位是**度**（顺时针，与浏览器 `rotate()` 同一个方向）。
    # 0 就是 1.190 那一张矩形；老工程读进来没有这一格，交回 0，编译串一字不改。
    rotation: Annotated[float, Field(ge=-LAYER_ROTATION_MAX, le=LAYER_ROTATION_MAX)] = 0.0

    # 1.192：这一层自己的针。空表就是 1.190 那一版（一段一个值），老工程读进来一字不差。

    keys: list[LayerKeyframe] = []

    enabled: bool = True





GradeNode = (

    GradeCurve

    | GradeWhiteBalance

    | GradeWheels

    | GradeLevels

    | GradeMatrix

    | GradeTransfer

    | GradeLUT

    | GradeLut3D

    | GradeParallel

    | GradeComposite

    | GradeLayer

)





class ClipColor(Contract):

    exposure: Annotated[float, Field(ge=-2, le=2)] = 0.0

    contrast: Annotated[float, Field(ge=0, le=2)] = 1.0

    saturation: Annotated[float, Field(ge=0, le=2)] = 1.0

    grade: Annotated[list[GradeNode], Field(max_length=GRADE_NODE_LIMIT)] = Field(

        default_factory=list

    )



    @model_validator(mode="after")

    def one_second_picture_edge(self):

        # 一条链最多一条第二输入边。这不是省功夫：每多一条就要多劈一路原图，而「第 k 条把第 k−1 条

        # 的结果当成链的输出」这种语义没人能从图上读出来——与其给一个说不清的旋钮，不如点名拒绝，

        # 并把真走得通的出路交回去（两条边就串成两段链，或用嵌套合成）。

        used = [node for node in self.grade if node.kind == "composite" and node.enabled]

        if len(used) > 1:

            raise EditorError(

                "COMPOSITE_LIMIT",

                f"一条调色链最多一条「叠一层原图」（这里有 {len(used)} 个）："

                "两条边叠在一起时「链的输出」指哪一段说不清。"

                "要两层效果就把没调色的那份放到另一条画面轨上用轨道混合方式，"

                "或者拆成两段嵌套合成",

                422,

                count=len(used),

            )

        return self

    @model_validator(mode="after")
    def layers_are_counted_and_last(self):
        # 两条判断各一条：条数（每层多一路解码、多两段 blend、多一个 DOM 图层）与位置（链尾，
        # 见 `GradeLayer` 那一句）。位置不是洁癖：浏览器把层画在整条滤镜链之上，导出按链里的顺序
        # 一段一段相合，中间隔着会改画面的节点时，两端就不是同一幅画。
        layers = [node for node in self.grade if node.kind == "layer" and node.enabled]
        if len(layers) > GRADE_LAYER_LIMIT:
            raise EditorError(
                "LAYER_LIMIT",
                f"一条调色链最多叠 {GRADE_LAYER_LIMIT} 层外部画面（这里有 {len(layers)} 个）："
                "每多一层就要多解一路画面。要更多层就把其中几层先合成一张图，"
                "或者把一层放到另一条画面轨上用那条轨的混合方式",
                422,
                count=len(layers),
                limit=GRADE_LAYER_LIMIT,
            )
        if layers:
            last = max(index for index, node in enumerate(self.grade) if node.kind == "layer")
            following = [
                node for node in self.grade[last + 1 :] if node.enabled and node.kind != "layer"
            ]
            if following:
                raise EditorError(
                    "LAYER_POSITION",
                    "外部画面层必须在链尾：这一层后面还有 "
                    f"{len(following)} 个会改画面的节点（{following[0].kind}）。导出按顺序相合、"
                    "浏览器按同一顺序画层，中间隔着节点两端就不是同一幅画；"
                    "把这一层移到链尾即可（界面上那颗「移到最后」）",
                    422,
                    following=[node.kind for node in following],
                )
        # 第三条判断是关于层自己那几枚针的（1.192）：同一格给同一条属性钉两枚，`_walk` 那把
        # 唯一的尺子就没有「这一段走哪一条」的答案；针数超过额度则是拿编译期换一次点击。
        # 两条都点名走得通的出路，不抽稀、不假装看不见。
        for node in layers:
            seen: set[tuple[str, int]] = set()
            for key in node.keys:
                spot = (key.property, key.at_ticks)
                if spot in seen:
                    raise EditorError(
                        "LAYER_KEY_CLASH",
                        f"这一层在 {key.at_ticks} 那一格给「{key.property}」钉了两枚针："
                        "同一格只能有一个答案，把其中一枚挪开或删掉",
                        422,
                        asset_id=node.asset_id,
                        property=key.property,
                        at_ticks=key.at_ticks,
                        keys=len(node.keys),
                    )
                seen.add(spot)
            if len(node.keys) > LAYER_KEY_LIMIT:
                raise EditorError(
                    "LAYER_KEY_LIMIT",
                    f"这一层带了 {len(node.keys)} 枚针，引擎收的是 {LAYER_KEY_LIMIT} 枚："
                    "少钉几枚，或者把这段切成两层各自动，不要一段上挤满",
                    422,
                    asset_id=node.asset_id,
                    keys=len(node.keys),
                    limit=LAYER_KEY_LIMIT,
                )
        return self





class MaskVertex(Contract):

    """One path node in normalized picture coordinates; handles are offsets from the node."""



    x: Annotated[float, Field(ge=0, le=1)]

    y: Annotated[float, Field(ge=0, le=1)]

    handle_out: Annotated[list[float], Field(min_length=2, max_length=2)] = Field(

        default_factory=lambda: [0.0, 0.0]

    )

    handle_in: Annotated[list[float], Field(min_length=2, max_length=2)] = Field(

        default_factory=lambda: [0.0, 0.0]

    )



    @model_validator(mode="after")

    def handle_range(self):

        for pair in (self.handle_out, self.handle_in):

            if any(not -1 <= value <= 1 for value in pair):

                raise ValueError("path handles must be within [-1, 1] of the node")

        return self





MASK_VERTEX_LIMIT = 64


# How many clip ids one id-named read may carry (`preview-manifest` since 1.183, `clips` since
# 1.186). The cap is the query string's own budget — these ids ride a GET — not a judgment about
# how many clips matter at once. One number because one physics: the same URL, the same limit.
CLIP_SUBSET_LIMIT = 256

PathVertices = Annotated[list[MaskVertex], Field(min_length=3, max_length=MASK_VERTEX_LIMIT)]





# 1.267：播放速度的量程只有一个主人。此前 25 与 400 抄在四处（两条命令的字段、曲线点的上限、
# 四点剪辑那一句判断），渲染层还自己抄了第五处——上限挪一次就有四处谎。

SPEED_PERCENT_MIN = 25

SPEED_PERCENT_MAX = 400


class SpeedPoint(Contract):

    """One node of a speed profile: timeline offset inside the clip and relative percent."""



    at_ticks: Ticks

    percent: Annotated[int, Field(ge=0, le=SPEED_PERCENT_MAX)]





SPEED_POINT_LIMIT = 64

SpeedCurve = Annotated[list[SpeedPoint], Field(min_length=2, max_length=SPEED_POINT_LIMIT)]





class MaskBoxKey(Contract):

    """再叠那块的一枚框点：整块盒子的五个数，在同一个时刻一起换。"""

    at_ticks: Ticks

    center_x: Annotated[float, Field(ge=0, le=1)]

    center_y: Annotated[float, Field(ge=0, le=1)]

    width: Annotated[float, Field(ge=0.01, le=2)]

    height: Annotated[float, Field(ge=0.01, le=2)]

    rotation: Annotated[float, Field(ge=-MASK_ROTATION_LIMIT, le=MASK_ROTATION_LIMIT)] = 0.0

    # 1.258：羽化可以不管——没写这一格就是「这一块自己静止的那个数」，所以 1.257 之前写下的框点
    #     读进来画面一字不改。写了才跟着这一枚一起换，与那五个数同一批整帧边界。

    feather: Annotated[float | None, Field(ge=0, le=1)] = None

    # The five numbers step together, so the segment's interpolation is the whole transition.
    interpolation: Literal["linear", "hold", "ease", "bezier"] = "linear"

    # 1.257：那五个数一起走同一条缓动，所以这一格只需要一份控制柄——不是每条边各一对。

    bezier: Bezier | None = None

    @model_validator(mode="after")
    def controls_need_the_curve(self):
        if self.bezier is not None and self.interpolation != "bezier":
            raise ValueError("bezier controls require bezier interpolation")
        return self


# 1.257：那五个数各自的那条带只有一个主人——`MaskBoxKey` 自己声明的 `ge`/`le`，
#     这里把它读出来给拒绝那一手用，不抄第二份数。

MASK_BOX_BANDS = {
    name: (
        next(item.ge for item in info.metadata if hasattr(item, "ge")),
        next(item.le for item in info.metadata if hasattr(item, "le")),
    )
    for name, info in MaskBoxKey.model_fields.items()
    if name not in ("at_ticks", "interpolation", "bezier")
}

# 框点那几种缓动的名单也只由这里说一次：从契约那条 Literal 读出来，不抄第二份。

MASK_BOX_INTERPOLATIONS = tuple(get_args(MaskBoxKey.model_fields["interpolation"].annotation))

# 1.258：框点可以**不管**羽化（没写就是这一块自己静止的那个数）。这一格归谁，只在这一个主人问一次
#     ——采样那一手与越界那一条都问它，不许各自再判一次 `is None`。

MASK_EXTRA_INHERITED = ("feather",)


def box_value(extra, key, name: str) -> float:
    """这一枚框点在那一个数上的值；没写的那一格交回这一块盒子自己静止的那一个。"""
    got = getattr(key, name)
    return getattr(extra, name) if got is None and name in MASK_EXTRA_INHERITED else got


class ShapeMask(Contract):

    shape: Literal["rectangle", "ellipse", "path"] = "ellipse"

    center_x: Annotated[float, Field(ge=0, le=1)] = 0.5

    center_y: Annotated[float, Field(ge=0, le=1)] = 0.5

    width: Annotated[float, Field(ge=0.01, le=2)] = 0.6

    height: Annotated[float, Field(ge=0.01, le=2)] = 0.6

    # 1.164: the box's own angle in degrees, positive clockwise — the same reading as 画面旋转, and

    # measured in picture pixels, not in the box's own fractions: a 0.6x0.3 box turned 45° has to

    # *look* like 45° on screen. A free-form outline carries its shape as drawn, so it has no angle.

    rotation: Annotated[float, Field(ge=-MASK_ROTATION_LIMIT, le=MASK_ROTATION_LIMIT)] = 0.0

    feather: Annotated[float, Field(ge=0, le=1)] = 0.0

    inverted: bool = False

    vertices: PathVertices | None = None



    @model_validator(mode="after")

    def path_requires_vertices(self):

        if self.shape == "path" and not self.vertices:

            raise ValueError("a path mask needs at least three vertices")

        if self.shape != "path" and self.vertices:

            raise ValueError("only a path mask can carry vertices")

        if self.shape == "path" and self.rotation:

            raise ValueError("only a rectangle or ellipse mask can be rotated")

        if self.vertices is not None:

            seen = {(round(vertex.x, 9), round(vertex.y, 9)) for vertex in self.vertices}

            if len(seen) != len(self.vertices):

                raise ValueError("path vertices must be distinct")

        return self





class ExtraShapeMask(ShapeMask):

    """再叠的一块：与主遮罩同一种盒子，外加它自己的框点（主遮罩的针仍在 `clip.keyframes`）。"""

    keys: Annotated[list[MaskBoxKey], Field(max_length=MASK_EXTRA_KEY_LIMIT)] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def bezier_stays_in_band(self):
        """一条贝塞尔段能把这一串的数各自甩到两端之外——每一格有自己的那条带，越界就是拒。

        带的两个数不在这里再抄一份：就是 `MaskBoxKey` 那些字段自己声明的 `ge`/`le`。
        没写的那一格（目前只有羽化）走的仍是 `box_value` 那一个主人，不是这里再判一次。
        """
        from .animation import bezier_extrema, bezier_value

        ordered = sorted(self.keys, key=lambda key: key.at_ticks)
        for left, right in zip(ordered, ordered[1:]):
            if left.interpolation != "bezier":
                continue
            controls = left.bezier or Bezier()
            for name, (low, high) in MASK_BOX_BANDS.items():
                start = box_value(self, left, name)
                for u in bezier_extrema(controls.y1, controls.y2):
                    value = start + (
                        box_value(self, right, name) - start
                    ) * bezier_value(controls.y1, controls.y2, u)
                    if not low - 1e-10 <= value <= high + 1e-10:
                        raise ValueError(f"{name} bezier curve exceeds [{low}, {high}]")
        return self


class Keyframe(Contract):

    property: Property

    at_ticks: Ticks

    value: float

    interpolation: Literal["linear", "hold", "ease", "bezier"] = "linear"

    bezier: Bezier | None = None



    @model_validator(mode="after")

    def property_range(self):

        lo, hi = PROPERTY_LIMITS[self.property]

        if not lo <= self.value <= hi:

            raise ValueError(f"{self.property} must be in [{lo}, {hi}]")

        if self.bezier is not None and self.interpolation != "bezier":

            raise ValueError("bezier controls require bezier interpolation")

        return self





class MaskShapeKeyframe(Contract):

    """One outline of a free-form mask at one moment: the whole vertex table, never a scalar.



    A morph is a vector, and giving every vertex coordinate its own property name would mean 256

    curves for a 64-vertex outline — a budget the mask tracker already spends on boxes. So one

    outline carries the table as drawn, and `animation.vertices_at` walks it component by component

    through the very same `_interpolate` every scalar curve answers with; the easing a person picks

    in the curve editor is the easing a morph gets.



    Topology is fixed by construction: every outline on a mask has the vertex count that mask was

    drawn with, so an outline key is a morph, not a redraw. Adding a node to a shape that is already

    animated is a different decision, and it is refused by name rather than silently renumbered.

    """



    at_ticks: Ticks

    vertices: PathVertices

    interpolation: Literal["linear", "hold", "ease", "bezier"] = "linear"

    bezier: Bezier | None = None



    @model_validator(mode="after")

    def controls_match_interpolation(self):

        if self.bezier is not None and self.interpolation != "bezier":

            raise ValueError("bezier controls require bezier interpolation")

        return self





# The text faces this build can draw with. Each entry is (Windows font file, the CSS family the

# browser needs, the label the interface shows); `capabilities.text_fonts` publishes the list after

# dropping any file that is not on disk, so neither the picker nor an Agent can name a face this

# machine cannot render.

TEXT_FONTS: dict[str, tuple[str, str, str]] = {

    "yahei": ("msyh.ttc", "Microsoft YaHei", "微软雅黑"),

    "hei": ("simhei.ttf", "SimHei", "黑体"),

    "song": ("simsun.ttc", "SimSun", "宋体"),

    "kai": ("simkai.ttf", "KaiTi", "楷体"),

    "arial": ("arial.ttf", "Arial", "Arial"),

    "mono": ("consolab.ttf", "Consolas", "等宽 Consolas"),

}

TEXT_COLORS = r"^#[0-9a-fA-F]{6}$"





class TextStyle(Contract):

    """One text layer. Every knob is a number both renderers can honour exactly: FFmpeg's

    ``drawtext`` and CSS take the same offsets, widths and colours, scaled by the same font size.



    What is deliberately absent: shadow blur and letter spacing. ``drawtext`` has no blur and no

    tracking, so offering them would mean a preview that shows something the delivered file does not

    contain — the same reason a cross-channel 3D LUT is labelled 预览不生效 instead of approximated.

    Defaults reproduce the

    1.62 rendering (4% black outline, 0.2 line spacing, 45 %-opaque black band), so an old project

    reads back with the pixels it had.

    """



    body: Annotated[str, Field(min_length=1, max_length=4000, pattern=r"^[^\x00]*$")]

    font_size: Annotated[float, Field(ge=0.01, le=0.2)] = 0.06

    color: Annotated[str, Field(pattern=TEXT_COLORS)] = "#FFFFFF"

    align: Literal["top", "center", "bottom"] = "center"

    box: bool = False

    font: Literal["yahei", "hei", "song", "kai", "arial", "mono"] = "yahei"

    text_align: Literal["left", "center", "right"] = "center"

    outline_width: Annotated[float, Field(ge=0, le=0.2)] = 0.04

    outline_color: Annotated[str, Field(pattern=TEXT_COLORS)] = "#000000"

    shadow_x: Annotated[float, Field(ge=-1, le=1)] = 0.0

    shadow_y: Annotated[float, Field(ge=-1, le=1)] = 0.0

    shadow_color: Annotated[str, Field(pattern=TEXT_COLORS)] = "#000000"

    box_color: Annotated[str, Field(pattern=TEXT_COLORS)] = "#000000"

    box_opacity: Annotated[float, Field(ge=0, le=1)] = 0.45

    line_spacing: Annotated[float, Field(ge=0, le=2)] = 0.2





# The transition vocabulary in one place: the contract, the capability document and the picker all

# read this list, so a kind cannot appear in the interface before the exporter can honour it. The

# `Literal` below has to name the same ids, and `tests/transition_check.py` asserts the two agree.

TransitionKind = Literal[

    "dissolve",

    "dip_black",

    "dip_white",

    "wipe_from_left",

    "wipe_from_right",

    "wipe_from_top",

    "wipe_from_bottom",

    "zoom_in",

    "zoom_out",

    "push_from_left",

    "push_from_right",

    "push_from_top",

    "push_from_bottom",

]

TRANSITION_KINDS: tuple[dict, ...] = (

    {"id": "dissolve", "label": "交叉溶解"},

    {"id": "dip_black", "label": "淡黑"},

    {"id": "dip_white", "label": "闪白"},

    {"id": "wipe_from_left", "label": "从左擦除"},

    {"id": "wipe_from_right", "label": "从右擦除"},

    {"id": "wipe_from_top", "label": "从上擦除"},

    {"id": "wipe_from_bottom", "label": "从下擦除"},

    {"id": "zoom_in", "label": "放大进入"},

    {"id": "zoom_out", "label": "缩出"},

    # 名字说的是**新画面从哪一边进来**（与「从左擦除」同一把尺）。推移：两段像同一条胶片一样一起走，

    # 旧画面从对面那一边退出，接缝横穿画面，两层永远不重叠。

    # 「滑动」（新画面滑进来盖住原地不动的旧画面）故意不提供：这条导出链把预乘后的各层**相加**

    # （见 transitions 的说明与擦除那条互补 alpha），重叠区会被双计成一片亮边——实测两幅纯色

    # 叠出来是 (222,61,220)。要交滑动，得先有一条画面空间的互补 alpha，两端都得改。

    {"id": "push_from_left", "label": "推移·从左入"},

    {"id": "push_from_right", "label": "推移·从右入"},

    {"id": "push_from_top", "label": "推移·从上入"},

    {"id": "push_from_bottom", "label": "推移·从下入"},

)





class Transition(Contract):

    from_clip_id: Identifier

    kind: TransitionKind = "dissolve"

    duration_ticks: Duration





# 淡的形状：值沿着窗口「靠上」静止值的方式。界面列的是这张表（与 transition_kinds 同一个规矩），

# 而 `FADE_SHAPE_CURVES` 是唯一一处把形状变成曲线的地方——导出与预览都只读那条曲线。

# 默认 `ease_in_out` 就是 1.95 之前所有淡用的 smoothstep，所以老工程读进来、渲染出去一字不差。

FadeShape = Literal["linear", "ease_in", "ease_out", "ease_in_out"]

FADE_SHAPES: tuple[dict, ...] = (

    {"id": "linear", "label": "线性"},

    {"id": "ease_in", "label": "缓入"},

    {"id": "ease_out", "label": "缓出"},

    {"id": "ease_in_out", "label": "缓入缓出"},

)

FADE_SHAPE_CURVES: dict[str, object] = {

    "linear": None,  # 普通直线段

    "ease_in_out": "ease",  # 引擎早就有的 smoothstep

    "ease_in": (0.42, 0.0, 1.0, 1.0),  # CSS ease-in

    "ease_out": (0.0, 0.0, 0.58, 1.0),  # CSS ease-out

}





class FadeEnvelope(Contract):

    """How long each edge of this clip takes to arrive and leave, per property.



    A fade is a property of the clip's *edges*, not a point on its curve. Stored as keyframes it was

    wrong three ways at once: asking for a fade-out deleted the fade-in (the reducer replaced the

    whole curve), a fade on a ducked or hand-keyed curve threw away every interior point, and

    trimming the tail left the fade past the new end, where nothing renders it. Measured from

    the edges instead all three are impossible, and the window survives any edit that moves an edge.

    """



    opacity_in_ticks: Ticks = 0

    opacity_out_ticks: Ticks = 0

    gain_in_ticks: Ticks = 0

    gain_out_ticks: Ticks = 0

    # 1.95: how the property approaches its resting value along that window. The default is exactly

    # the smoothstep every pre-1.95 fade used, so an old project reads and renders unchanged.

    opacity_shape: FadeShape = "ease_in_out"

    gain_shape: FadeShape = "ease_in_out"



    def window(self, prop: str) -> tuple[int, int]:

        """This property's `(in, out)` pair, so callers never repeat the field-name dance."""

        return (

            getattr(self, f"{prop}_in_ticks"),

            getattr(self, f"{prop}_out_ticks"),

        )



    def shape(self, prop: str) -> str:

        return getattr(self, f"{prop}_shape")





class Stabilization(Contract):

    """One stabilisation run's decision, stored on the clip it was written for.



    The correction itself is ordinary `x`/`y`/`rotation`/`scale` keyframes, indistinguishable from a

    hand-keyed move once it is in the document. This record is what lets the engine know that those

    four curves belong to the stabiliser, so a second press can *replace* them (change the strength,

    pay one click) instead of stacking a second copy of the same measurement, and a speed change can

    refuse by name instead of quietly mis-aligning a correction that was measured one point per

    source frame.

    """



    strength: Annotated[float, Field(ge=0, le=STABILIZE_STRENGTH_LIMIT)]

    max_crop: Annotated[float, Field(ge=0, le=STABILIZE_MAX_CROP_LIMIT)]

    points: Annotated[int, Field(ge=1, le=240)]

    translation_correction: Annotated[float, Field(ge=0)]

    roll_correction: Annotated[float, Field(ge=0)]

    zoom_to_hide_borders: Annotated[float, Field(ge=1)]

    analysed_frames: Annotated[int, Field(ge=1)]





class Clip(Contract):

    id: Identifier

    asset_id: Identifier

    track_id: Identifier

    position_ticks: Ticks

    source_in_ticks: Ticks = 0

    duration_ticks: Duration

    # 100 是兼容承诺：老工程、老客户端的 clip.add 都不带这一格，省略就是原速；量程那次去重
    # 只该收「25/400 抄了几处」这件事，不许把默认值一起收掉（1.267 一度收掉，随包自检当场红）。
    speed_percent: Annotated[int, Field(ge=SPEED_PERCENT_MIN, le=SPEED_PERCENT_MAX)] = 100

    text: TextStyle | None = None

    effects: ClipEffects = Field(default_factory=ClipEffects)

    color: ClipColor = Field(default_factory=ClipColor)

    mask: ShapeMask | None = None
    # 1.221：主遮罩之外再叠的几块，与主遮罩**相乘**（都留着的那一块才露出来）。
    # 关键帧仍只跟着主遮罩走——那五条 `mask_*` 曲线说的是「这一条片段的那一个洞」，
    # 一块会动的第二洞要的是另一套寻址，不在这版里；界面上这一句是明说的。
    extra_masks: Annotated[list[ExtraShapeMask], Field(max_length=MASK_STACK_LIMIT)] = (
        Field(default_factory=list)
    )
    # 1.237：再叠的这几块可以跟着主遮罩的**中心平移**一起走（大小与角度仍各自保留）。
    # 默认关：旧工程里它们本来就原地不动，这一格缺席等于 false，画面一字不变。
    extra_masks_follow: bool = False

    fade: FadeEnvelope | None = None

    speed_curve: SpeedCurve | None = None

    stabilization: Stabilization | None = None

    keyframes: Annotated[list[Keyframe], Field(max_length=2000)] = Field(default_factory=list)

    mask_shape_keys: Annotated[list[MaskShapeKeyframe], Field(max_length=MASK_SHAPE_KEY_LIMIT)] = (

        Field(default_factory=list)

    )

    animation_offset_ticks: Ticks = 0

    transition_in: Transition | None = None

    group_id: Identifier | None = None

    link_id: Identifier | None = None

    link_source_offset_ticks: Annotated[int, Field(ge=-MAX_TICKS, le=MAX_TICKS)] = 0

    embedded_audio: bool = True



    @model_validator(mode="after")

    def speed_curve_shape(self):

        if self.speed_curve is None:

            return self

        marks = [point.at_ticks for point in self.speed_curve]

        if any(right <= left for left, right in zip(marks, marks[1:])):

            raise ValueError("speed curve offsets must increase")

        if marks[0] != 0:

            raise ValueError("speed curve must start at the clip head")

        if marks[-1] > self.duration_ticks:

            raise ValueError("speed curve exceeds the clip duration")

        return self



    def mask_shape_problem(self) -> str | None:

        """Why this clip's outline keyframes cannot be honoured, or None when they can.



        One judgment in one place: the timeline validator asks it after every mutation, the reducer

        asks it before it writes another outline onto a clip that is already full, and the export

        and the preview both draw the table this function signed off on.

        """

        if not self.mask_shape_keys:

            return None

        if self.mask is None or self.mask.shape != "path":

            return "a mask outline animates only a free-form (path) mask"

        drawn = len(self.mask.vertices or [])

        seen = set()

        for key in self.mask_shape_keys:

            if len(key.vertices) != drawn:

                return (

                    f"an outline of {len(key.vertices)} vertices cannot morph into this "

                    f"{drawn}-vertex mask: change the node count on the static shape first, or "

                    "delete this mask's outline keyframes"

                )

            if key.at_ticks in seen:

                return "one mask outline per time"

            seen.add(key.at_ticks)

        return None



    def mask_animation_problem(self) -> str | None:

        """Why this clip's mask keyframes cannot be honoured, or None when they can.



        The reducer edits a clip in place, so this is checked once by the timeline validator after

        every mutation rather than by a model validator that an in-place write would bypass.

        """

        shape = self.mask_shape_problem()

        if shape:

            return shape

        if not any(key.property in MASK_FIELDS for key in self.keyframes):

            return None

        if self.mask is None:

            return "mask keyframes need a mask on the clip"

        if self.mask.inverted:

            return "an inverted mask keeps the outside, which a keyframed shape cannot follow"

        if self.mask.shape == "path" and any(

            key.property in MASK_SIZE_FIELDS for key in self.keyframes

        ):

            return (

                "a free-form mask can move but cannot resize yet: keyframe 遮罩中心 only, "

                "or redraw the outline per shot"

            )

        # 1.165: ShapeMask refuses a *static* angle on a path for the same reason — an outline

        # carries its own shape, so an angle curve would be a number the exporter has nothing to

        # turn. Same judgment, so the keyframed one has to be refused here too.

        if self.mask.shape == "path" and any(

            key.property in ("mask_rotation", "mask_feather") for key in self.keyframes

        ):

            return (

                "a free-form outline has no box to turn and its 软边 is baked with the plate: "

                "遮罩角度与遮罩羽化 only exist on a rectangle or "

                "ellipse mask, so keyframe the outline frames instead"

            )

        # 1.164 through 1.165 refused this pair, because one rotated plate stretched non-uniformly

        # would shear the angle. The per-window plate answers it: `mask_box_schedule` steps the

        # angle and the two edges on the same frame boundary, so both ends execute the same box in

        # the same frame — 遮罩宽度/遮罩高度 on a turning box are now ordinary stepped curves.

        return None



    @model_validator(mode="after")

    def unique_keyframes(self):

        keys = {(k.property, k.at_ticks) for k in self.keyframes}

        if len(keys) != len(self.keyframes):

            raise ValueError("one keyframe per property and time")

        from .animation import bezier_extrema, bezier_value



        for prop in PROPERTY_LIMITS:

            ordered = sorted(

                (k for k in self.keyframes if k.property == prop), key=lambda k: k.at_ticks

            )

            lo, hi = PROPERTY_LIMITS[prop]

            for left, right in zip(ordered, ordered[1:]):

                if left.interpolation != "bezier":

                    continue

                controls = left.bezier or Bezier()

                for u in bezier_extrema(controls.y1, controls.y2):

                    value = left.value + (right.value - left.value) * bezier_value(

                        controls.y1, controls.y2, u

                    )

                    if not lo - 1e-10 <= value <= hi + 1e-10:

                        raise ValueError(f"{prop} bezier curve exceeds [{lo}, {hi}]")

        return self





class Sequence(Contract):

    id: Identifier

    name: Annotated[str, Field(min_length=1, max_length=256)]

    duration_ticks: Duration

    tracks: Annotated[list[Track], Field(max_length=128)] = Field(default_factory=list)

    clips: Annotated[dict[str, Clip], Field(max_length=20_000)] = Field(default_factory=dict)





RenderFit = Literal["contain", "cover", "stretch"]

RenderRange = Literal["full", "marks"]





def preset_container(preset_id: str) -> str | None:

    """The container one preset writes, or None when no such preset exists.



    `render_presets` is the only table of delivery targets, so the suffix a file name carries is

    read from there instead of written down again beside each new format.

    """

    for item in render_presets():

        if item["id"] == preset_id:

            return item["container"]

    return None





def checked_render_name(value):

    """One rule for one field: a bare file name carrying its preset's container suffix, shared by

    the single and the batch request. An unknown preset id is left to `render.preset_by_id`, which

    names it and reports it as UNKNOWN_PRESET."""

    name = value.filename

    if "/" in name or "\\" in name or "\x00" in name or name in {".", ".."}:

        raise ValueError("filename must be a bare file name")

    container = preset_container(value.preset_id)

    if container is not None and not name.lower().endswith(f".{container}"):

        raise ValueError(f"filename must end with .{container} for the {value.preset_id} preset")

    return value





TIMECODE_SHAPE = "HH:MM:SS:FF"

# SMPTE 的丢帧码只在 29.97 / 59.94 这两个率上有定义。实测：整数 30 上写 `01:02:03;04`，FFmpeg

# 照样原样塞进 mov 的流标签里——所以这条规矩得由引擎拿着，不能指望 muxer。

TIMECODE_DROP_RATES = ((30000, 1001), (60000, 1001))

_TIMECODE_PARTS = re.compile(r"^(\d{2}):(\d{2}):(\d{2})([:;])(\d{2})$")





def timecode_frames(rate: FrameRate) -> int:

    """这条率上一秒里有几个帧号：30000/1001 是 30（帧号 00–29），24000/1001 是 24。"""

    return round(rate.numerator / rate.denominator)





# 交付帧率是一张闭表。PAL 机房要 25、NTSC 交 29.97、胶片感要 24／23.976、高帧率要 50／59.94／60；

# 表外一律拒（`UNKNOWN_OUTPUT_RATE`，句子把可选项念出来）：时间线时钟是 TIMEBASE，随便一个率会

# 让「一格画面」对不上一个整数 tick，两端就再也说不清同一件事。

OUTPUT_FRAME_RATES: tuple[tuple[int, int, str], ...] = (

    (24, 1, "24"),

    (24000, 1001, "23.976"),

    (25, 1, "25"),

    (30000, 1001, "29.97"),

    (30, 1, "30"),

    (50, 1, "50"),

    (60000, 1001, "59.94"),

    (60, 1, "60"),

)





def _refuse_output_rate(numerator: int, denominator: int, got: object) -> "EditorError":

    choices = "／".join(label for _, _, label in OUTPUT_FRAME_RATES)

    return EditorError(

        "UNKNOWN_OUTPUT_RATE",

        f"交付帧率只能是这几档：{choices}（现在收到 {numerator}/{denominator}）；"

        f"留空就跟时间线自己的率一致",

        422,

        got=got,

        choices=[list(item[:2]) for item in OUTPUT_FRAME_RATES],

    )





def _require_output_rate(numerator: int, denominator: int, got: object) -> FrameRate:

    """表内才构造 `FrameRate`，表外只有一种说法。判断只在这一处，HTTP 与契约共用它。"""

    for candidate, co_denominator, _ in OUTPUT_FRAME_RATES:

        if numerator == candidate and denominator == co_denominator:

            return FrameRate(numerator=numerator, denominator=denominator)

    raise _refuse_output_rate(numerator, denominator, got)





def checked_output_rate(value: FrameRate | None) -> FrameRate | None:

    """`None` 是 1.138 之前的原意：交付跟时间线自己的率一致。"""

    if value is None:

        return None

    return _require_output_rate(

        value.numerator, value.denominator, f"{value.numerator}/{value.denominator}"

    )





def parse_frame_rate(text: str | None) -> FrameRate | None:

    """query 与文本框只能带字符串：`25` 或 `30000/1001`。空等于没有。"""

    if text is None or not text.strip():

        return None

    parts = text.strip().split("/")

    if len(parts) == 1:

        parts = [parts[0], "1"]

    if len(parts) != 2 or not all(part.strip().isdigit() for part in parts):

        raise EditorError(

            "UNKNOWN_OUTPUT_RATE",

            f"帧率要写成整数或 分子/分母（例：25 或 30000/1001），收到 {text!r}",

            422,

            got=text,

        )

    numerator, denominator = (int(part.strip()) for part in parts)

    return _require_output_rate(numerator, denominator, text)





def checked_timecode(value: str | None, rate: FrameRate) -> str | None:

    """One rule, before FFmpeg ever sees the string.



    FFmpeg's own parser is looser than the standard and *silently rewrites* what it accepts:

    `1:2:3:4` goes through as written, `01:02:03.04` comes back as `01:02:03;04` (dot becomes

    drop-frame), and an out-of-range minute `01:60:00:00` is carried into the hours as

    `02:00:00:00`. A person handing off a master must get that refusal instead of a file whose

    timecode is not the one they typed.

    """

    if value is None:

        return None

    parts = _TIMECODE_PARTS.match(value)

    if not parts:

        raise EditorError(

            "TIMECODE_INVALID",

            f"时间码得写成 {TIMECODE_SHAPE}（每段两位数字，分隔符用 : 或 ;），收到的是 {value!r}；"

            "例：01:00:00:00",

            422,

            value=value,

        )

    hours, minutes, seconds, separator, frames = (

        int(parts.group(1)),

        int(parts.group(2)),

        int(parts.group(3)),

        parts.group(4),

        int(parts.group(5)),

    )

    limit = timecode_frames(rate)

    problems: list[str] = []

    if hours > 23:

        problems.append(f"小时最多 23，收到 {hours}")

    if minutes > 59:

        problems.append(f"分钟最多 59，收到 {minutes}")

    if seconds > 59:

        problems.append(f"秒最多 59，收到 {seconds}")

    if frames >= limit:

        problems.append(

            f"这一条画面的帧率是 {rate.numerator}/{rate.denominator}，"

            f"帧号只能 00–{limit - 1:02d}，收到 {frames:02d}"

        )

    if separator == ";" and (rate.numerator, rate.denominator) not in TIMECODE_DROP_RATES:

        problems.append(

            "分号那种是丢帧码（drop-frame），SMPTE 只在 29.97 与 59.94 上定义它；"

            "这一条画面的帧率不是那两个率，请改用冒号"

        )

    if problems:

        raise EditorError(

            "TIMECODE_INVALID",

            f"时间码 {value!r} 不能用：" + "；".join(problems) + f"。写法 {TIMECODE_SHAPE}",

            422,

            value=value,

        )

    return value





# How far the subject may drift from the middle of the frame between two auto-reframe keyframes,

# measured in frame widths. One number so the planner default and the request default cannot drift.

REFRAME_TOLERANCE = 0.01





class ReframeRequest(Contract):

    """Turn the mask path a track produced into the layer motion that keeps the subject centred.



    `max_scale` is how far the engine may zoom to hide the edge a pan would expose: a

    full-frame layer shifted half a frame wide needs twice the size to still cover the picture.

    `tolerance` is how far the subject may sit from the middle between two follow keyframes, in

    frame widths: smaller holds the subject tighter and costs more keyframes.

    """



    request_id: Identifier

    expected_revision: Revision

    # Read the ids below -- and apply the batch -- inside one nested composition.

    sequence_id: Identifier | None = None

    max_scale: Annotated[float, Field(ge=1.0, le=4.0)] = 2.0

    tolerance: Annotated[float, Field(gt=0.0, le=0.25)] = REFRAME_TOLERANCE

    apply: bool = False

    dry_run: bool = False





class RenderBatchItem(Contract):

    """One deliverable inside a batch: a preset, a framing and a file name."""



    preset_id: Identifier

    filename: Annotated[str, Field(min_length=1, max_length=128)]

    folder: Annotated[str | None, Field(max_length=2048)] = None

    sequence_id: Identifier | None = None

    fit: RenderFit = "contain"

    range: RenderRange = "full"

    transparent: bool = False

    timecode: Annotated[str | None, Field(max_length=24)] = None

    output_frame_rate: FrameRate | None = None

    # 1.151: declare the colour of the delivered picture, or say nothing (`None`). Only a

    # set value joins a render's fingerprint, so receipts written before this field replay.

    colour_tag: Annotated[str | None, Field(max_length=24)] = None



    @model_validator(mode="after")

    def safe_filename(self):

        return checked_render_name(self)





class DeliveryRecipe(Contract):

    """A named delivery plan stored on the project: the presets, framing and marks a team ships

    every time, so a click and an Agent command reuse one list instead of retyping it. It holds

    choices only — never encoder flags, and the render still re-checks them at job time."""



    id: Identifier

    name: Annotated[str, Field(min_length=1, max_length=64)]

    # The batch this feeds takes at most four deliverables, so a recipe never stores items that

    # could not be shipped in one go.

    items: Annotated[list[RenderBatchItem], Field(min_length=1, max_length=4)]



    @model_validator(mode="after")

    def distinct_names(self):

        names = [item.filename for item in self.items]

        if len(set(names)) != len(names):

            raise ValueError("two deliverables in a recipe cannot write the same file")

        return self





class RecipeSet(Contract):

    """Create a delivery recipe, or replace the one that already carries this id."""



    op: Literal["recipe.set"]

    recipe: DeliveryRecipe





class RecipeRemove(Contract):

    op: Literal["recipe.remove"]

    recipe_id: Identifier





class Marker(Contract):

    """A named point on the timeline. Markers belong to the project, not to a clip, and they stay

    where they were placed when clips ripple past them — the same contract every editor's ruler

    offers, so a human's beat marks and an Agent's scene notes refer to the same integer tick."""



    id: Identifier

    at_ticks: Ticks

    name: Annotated[str, Field(min_length=1, max_length=64)]

    color: Literal["amber", "cyan", "green", "red", "violet"] = "amber"





class Project(Contract):

    schema_version: Annotated[int, Field(ge=1, le=SCHEMA_VERSION)] = SCHEMA_VERSION

    id: Identifier

    name: Annotated[str, Field(min_length=1, max_length=256)]

    revision: Revision = 0

    settings: SequenceSettings = Field(default_factory=SequenceSettings)

    assets: Annotated[dict[str, Asset], Field(max_length=10_000)] = Field(default_factory=dict)

    tracks: Annotated[list[Track], Field(max_length=128)] = Field(default_factory=list)

    clips: Annotated[dict[str, Clip], Field(max_length=20_000)] = Field(default_factory=dict)

    sequences: Annotated[dict[str, Sequence], Field(max_length=1000)] = Field(default_factory=dict)

    markers: Annotated[list[Marker], Field(max_length=2000)] = Field(default_factory=list)

    recipes: Annotated[list[DeliveryRecipe], Field(max_length=64)] = Field(default_factory=list)

    notes: Annotated[str, Field(max_length=4000)] = ""





class SequenceNest(Contract):

    op: Literal["sequence.nest"]

    clip_ids: Annotated[list[Identifier], Field(min_length=1, max_length=20_000)]

    sequence_id: Identifier

    asset_id: Identifier

    clip_id: Identifier

    name: Annotated[str, Field(min_length=1, max_length=256)]





class SequenceAdd(Contract):

    op: Literal["sequence.add"]

    sequence: Sequence





class SequenceUpdate(Contract):

    op: Literal["sequence.update"]

    sequence_id: Identifier

    name: Annotated[str | None, Field(min_length=1, max_length=256)] = None

    duration_ticks: Duration | None = None



    @model_validator(mode="after")

    def something_to_do(self):

        if self.name is None and self.duration_ticks is None:

            raise ValueError("provide name or duration_ticks")

        return self





class SequenceRemove(Contract):

    op: Literal["sequence.remove"]

    sequence_id: Identifier





class TrackAdd(Contract):

    op: Literal["track.add"]

    track: Track

    index: Annotated[int | None, Field(ge=0, le=128)] = None





class AssetRegister(Contract):

    op: Literal["asset.register"]

    asset: Asset





class AssetImport(Contract):

    """Attach a media record the server probed. The path is never caller-supplied here."""



    op: Literal["asset.import"]

    asset_id: Identifier

    label: Annotated[str, Field(min_length=1, max_length=256)]

    probe_id: Identifier

    verified: VerifiedMedia



    @model_validator(mode="after")

    def matching_probe(self):

        if self.verified.probe_id != self.probe_id:

            raise ValueError("verified record must carry the same probe_id")

        return self





class AssetRemove(Contract):

    op: Literal["asset.remove"]

    asset_id: Identifier





class TrackRemove(Contract):

    op: Literal["track.remove"]

    track_id: Identifier





class TrackUpdate(Contract):

    op: Literal["track.update"]

    track_id: Identifier

    name: Annotated[str | None, Field(min_length=1, max_length=128)] = None

    muted: bool | None = None

    hidden: bool | None = None

    locked: bool | None = None

    volume: Annotated[float | None, Field(ge=0, le=4)] = None

    blend_mode: BlendMode | None = None





class ClipAdd(Contract):

    op: Literal["clip.add"]

    clip: Clip





class ClipInsert(Contract):

    op: Literal["clip.insert"]

    clip: Clip

    # None moves only the destination track; explicit tracks must include it.

    ripple_track_ids: Annotated[list[Identifier] | None, Field(max_length=128)] = None





class ClipOverwrite(Contract):

    op: Literal["clip.overwrite"]

    clip: Clip





class ClipMove(Contract):

    op: Literal["clip.move"]

    clip_id: Identifier

    track_id: Identifier

    position_ticks: Ticks





class ClipsAdd(Contract):

    op: Literal["clips.add"]

    clips: Annotated[list[Clip], Field(min_length=1, max_length=20_000)]





class ClipsMove(Contract):

    op: Literal["clips.move"]

    clip_ids: Annotated[list[Identifier], Field(min_length=1, max_length=20_000)]

    delta_ticks: Annotated[int, Field(ge=-MAX_TICKS, le=MAX_TICKS)]

    track_map: dict[Identifier, Identifier] = Field(default_factory=dict)





class ClipsRemove(Contract):

    op: Literal["clips.remove"]

    clip_ids: Annotated[list[Identifier], Field(min_length=1, max_length=20_000)]

    ripple: bool = False





class ClipsSplit(Contract):

    op: Literal["clips.split"]

    clip_ids: Annotated[list[Identifier], Field(min_length=1, max_length=20_000)]

    at_ticks: Ticks

    right_clip_ids: dict[Identifier, Identifier]





class ClipTrim(Contract):

    op: Literal["clip.trim"]

    clip_id: Identifier

    source_in_ticks: Ticks

    duration_ticks: Duration

    position_ticks: Ticks | None = None

    ripple: bool = False





class ClipSlip(Contract):

    """Change which part of the source a clip shows, without moving it or changing its length.



    The clip keeps its position and duration, so nothing around it moves and the track stays the

    same length; only the source window slides. A clip whose volume/picture is animated keeps its

    keyframes attached to the timeline window, which is exactly what a slip means.

    """



    op: Literal["clip.slip"]

    clip_id: Identifier

    source_offset_ticks: int





class ClipSlide(Contract):

    """Move a clip along its track, taking frames from one neighbour and giving the same number to

    the other, so the track's content length does not change at all.



    Both neighbours keep their own source clock: the one being eaten into starts or ends later in

    its own media. That is what makes a slide different from a move plus two trims done by hand.

    """



    op: Literal["clip.slide"]

    clip_id: Identifier

    delta_ticks: int





class ClipRoll(Contract):

    op: Literal["clip.roll"]

    clip_id: Identifier  # the clip left of the seam, which grows/shrinks at its tail

    other_clip_id: Identifier  # the clip right of the seam, which mirrors

    delta_ticks: Annotated[int, Field(ge=-MAX_TICKS, le=MAX_TICKS)]





class ClipTrimLinked(ClipTrim):

    op: Literal["clip.trim_linked"]





class ClipLinkSplitTrim(Contract):

    """Move one member's edge of an audio/video link on its own: a J or L cut.



    `clip.trim_linked` moves both sides of the pair together, which is what trimming linked

    sound and picture normally means. Here only the named member's `edge` moves, by

    `delta_ticks` to the right, and the partner keeps both of its edges: that is the shape

    of a J/L cut, the sound running past the picture (or the picture past the sound).



    The link record survives on purpose. The pair then reads as deliberately out of sync

    in `link_status`, with the offset counted in ticks, and `clips.link_reconcile` is the

    one step back. An edge that would land between two of that track's own quanta is

    refused by name instead of being quietly rounded.

    """



    op: Literal["clip.link_split_trim"]

    clip_id: Identifier

    edge: Literal["head", "tail"]

    # Signed movement of that one edge along the timeline, in ticks.

    delta_ticks: Annotated[int, Field(gt=-MAX_TICKS, lt=MAX_TICKS)]





class ClipsLinkReconcile(Contract):

    """Pull every member of a link back onto the anchor's window.



    The anchor is the same clip `link_status` reports, and each member keeps the source

    phase it was given when the link was made (`link_source_offset_ticks`), so reconciling

    after a J/L cut restores the sound under the picture without inventing a sync point.

    A member whose source cannot reach that window is refused by name, not clipped to fit.

    """



    op: Literal["clips.link_reconcile"]

    link_id: Identifier





class ClipsGroup(Contract):

    op: Literal["clips.group"]

    clip_ids: Annotated[list[Identifier], Field(min_length=1, max_length=20_000)]

    group_id: Identifier | None





class ClipColorSpaceRead(Contract):

    """Ask what the file says, without writing anything.



    `clip.color_manage` with `auto_source` is the writer; this is the reader an Agent or the

    interface consults first, so a button can say which curve the asset carries (or name the reason

    it cannot) before anybody commits a command that would be refused. It reads the same

    `colortags.detect_space`, so the answer here and the one the reducer uses cannot diverge.

    """



    sequence_id: SequenceRef | None = None





class ClipsLink(Contract):

    op: Literal["clips.link"]

    clip_ids: Annotated[list[Identifier], Field(min_length=1, max_length=20_000)]

    link_id: Identifier | None





class ClipColorManage(Contract):

    """Grade this clip in linear light and deliver it display-referred, in one step.



    A colour-managed workflow is a *pair* of conversions: read the source from the space it was

    authored in, work in linear, then write out the transfer function the display expects. By

    hand that is two transfer nodes in the right order on every clip, added and removed

    together. This command writes the pair around whatever the clip already holds and tags both

    nodes, so running it again replaces the pair instead of stacking a second one, and the

    middle of the chain is never touched.



    `source_space = null` takes the pair off again.



    `auto_source = true` asks the file to answer for itself: the source end then comes from the

    colour tags the probe stored on that asset (`COLOR_TRANSFER_TAGS` is the only translation),

    and a file whose tags do not name a tone curve is refused by name instead of being read as

    something convenient. It cannot be combined with a hand-picked `source_space`: two answers to

    one question is the bug, not the feature.

    """



    op: Literal["clip.color_manage"]

    clip_id: Identifier

    source_space: ColorSpace | None

    display_space: ColorSpace = "rec709"

    auto_source: bool = False



    @model_validator(mode="after")

    def one_source_answer(self):

        if self.auto_source and self.source_space is not None:

            raise ValueError(

                "auto_source takes the source end from the file's own colour tags, so name either "

                f"that or a source_space ({self.source_space}) by hand, not both"

            )

        return self





class ClipEffectsSet(Contract):

    op: Literal["clip.effects"]

    clip_id: Identifier

    effects: ClipEffects





class ClipMaskSet(Contract):

    op: Literal["clip.mask"]

    clip_id: Identifier

    mask: ShapeMask | None





class ClipSpeedCurveSet(Contract):

    op: Literal["clip.speed_curve"]

    clip_id: Identifier

    points: SpeedCurve | None = None





class ClipStabilizeRecord(Contract):

    """Attach or clear the record of a stabilisation run.



    The engine's own analysis is the only thing that writes one in normal use, because the record

    claims *why* those four curves exist. It needs no separate authority: an Agent that hand-wrote

    the same numbers could already have written the keyframes themselves, and what the record buys

    is a re-press that replaces rather than stacks.

    """



    op: Literal["clip.stabilize_record"]

    clip_id: Identifier

    record: Stabilization | None = None





class ClipSpeedSet(Contract):

    op: Literal["clip.speed"]

    clip_id: Identifier

    speed_percent: Annotated[int, Field(ge=SPEED_PERCENT_MIN, le=SPEED_PERCENT_MAX)]

    ripple: bool = True





class ClipColorSet(Contract):

    op: Literal["clip.color"]

    clip_id: Identifier

    color: ClipColor





class ClipGradeSet(Contract):

    op: Literal["clip.grade"]

    clip_id: Identifier

    grade: Annotated[list[GradeNode], Field(max_length=GRADE_NODE_LIMIT)]





class ClipTextSet(Contract):

    op: Literal["clip.text"]

    clip_id: Identifier

    text: TextStyle





class ClipPatch(Contract):

    op: Literal["clip.patch"]

    clip_id: Identifier

    effects: dict[EffectField, float] | None = None

    color: dict[Literal["exposure", "contrast", "saturation", "grade"], Any] | None = None

    text: dict[str, str | float | bool] | None = None



    @model_validator(mode="after")

    def valid_fields(self):

        if not (self.effects or self.color or self.text):

            raise ValueError("provide at least one changed property")

        if self.effects is not None:

            ClipEffects.model_validate(self.effects)

        if self.color is not None:

            ClipColor.model_validate({"grade": [], **self.color})

        # Re-read the patch through TextStyle rather than a hand-listed key union: the style grew in

        # 1.63 and a second list of its fields would have gone stale the same day.

        if self.text is not None:

            TextStyle.model_validate({"body": "validation", **self.text})

        return self





class ClipFade(Contract):

    """Set one edge of one property's fade window. `duration_ticks: 0` clears the side it names.



    1.95 adds `shape`, and either field alone is a complete request: dragging the corner sends a

    length, the shape dropdown sends only the shape and leaves the window exactly where it was.

    """



    op: Literal["clip.fade"]

    clip_id: Identifier

    property: Literal["opacity", "gain"]

    duration_ticks: Ticks | None = None

    mode: Literal["in", "out", "both"] = "both"

    shape: FadeShape | None = None



    @model_validator(mode="after")

    def names_something(self):

        if self.duration_ticks is None and self.shape is None:

            raise ValueError("provide duration_ticks, shape, or both")

        return self





class ClipFadeAdopt(Contract):

    """Move a pre-1.90 keyframe fade into this clip's edge windows.



    Before 1.90 a fade was written as two keyframes on the property, replacing its whole curve: it

    could not coexist with a duck, and it did not follow a trim. Such a fade is still an ordinary

    curve today, invisible to the inspector's two rows and to the timeline's corner handles. This

    command recognises exactly the shape the old reducer wrote — a ramp from `0.0` at an edge up to

    the property's resting value, eased, and nothing else on that property — and turns it into

    `Clip.fade` windows, deleting the keyframes it absorbed. The picture does not move: easing

    `0 -> resting` is the same curve as `resting × smoothstep`, which `tests/fadeadopt_check.py`

    measures by rendering the same timeline on both sides of the adoption.



    Anything else (extra points, a non-zero floor, a hand-keyed shape, a window already on that

    property) is refused by name with what was found, rather than guessed at.

    """



    op: Literal["clip.fade_adopt"]

    clip_id: Identifier

    property: Literal["opacity", "gain"]





class MarkerSet(Contract):

    """Create a marker, or move and rename the one that already carries this id."""



    op: Literal["marker.set"]

    marker: Marker





class MarkerRemove(Contract):

    op: Literal["marker.remove"]

    marker_id: Identifier





class TransitionSet(Contract):

    op: Literal["transition.set"]

    clip_id: Identifier

    from_clip_id: Identifier

    kind: TransitionKind = "dissolve"

    duration_ticks: Duration





class TransitionRemove(Contract):

    op: Literal["transition.remove"]

    clip_id: Identifier





class CaptionsImport(Contract):

    op: Literal["captions.import"]

    track_id: Identifier

    asset_id: Identifier

    srt: Annotated[str, Field(min_length=1, max_length=500_000)]

    offset_ticks: Ticks = 0





class KeyframeSet(Contract):

    op: Literal["keyframe.set"]

    clip_id: Identifier

    keyframe: Keyframe





class KeyframeRemove(Contract):

    op: Literal["keyframe.remove"]

    clip_id: Identifier

    property: Property

    at_ticks: Ticks





class KeyframeMove(Contract):

    op: Literal["keyframe.move"]

    clip_id: Identifier

    from_ticks: Ticks

    keyframe: Keyframe





class KeyframeMoveItem(Contract):

    from_ticks: Ticks

    keyframe: Keyframe





class KeyframesMove(Contract):

    op: Literal["keyframes.move"]

    clip_id: Identifier

    moves: Annotated[list[KeyframeMoveItem], Field(min_length=1, max_length=2000)]





class KeyframePosition(Contract):

    property: Property

    at_ticks: Ticks





class KeyframesRemove(Contract):

    op: Literal["keyframes.remove"]

    clip_id: Identifier

    keyframes: Annotated[list[KeyframePosition], Field(min_length=1, max_length=2000)]





class KeyframesReplace(Contract):

    """Write a whole curve for one property in a single command.



    Bulk automation — a duck envelope over a music bed, a tracked mask over a shot — needs

    hundreds of points, and one command per point would run past the batch limit and split a

    single editorial decision across several revisions. Times are clip-local, like `keyframe.set`.

    """



    op: Literal["keyframes.replace"]

    clip_id: Identifier

    property: Property

    keyframes: Annotated[list[Keyframe], Field(min_length=1, max_length=2000)]



    @model_validator(mode="after")

    def one_property(self):

        if any(key.property != self.property for key in self.keyframes):

            raise ValueError("a replacement writes one property only")

        times = [key.at_ticks for key in self.keyframes]

        if any(right <= left for left, right in zip(times, times[1:])):

            raise ValueError("replacement times must increase")

        return self





class MaskTrackPoint(Contract):

    at_ticks: Ticks

    center_x: Annotated[float, Field(ge=0.001, le=0.999)]

    center_y: Annotated[float, Field(ge=0.001, le=0.999)]

    width: Annotated[float | None, Field(ge=0.01, le=2)] = None

    height: Annotated[float | None, Field(ge=0.01, le=2)] = None

    # 1.271：跟踪也会读画面里的旋转。与宽高同一个规矩：每一点都带，或者一点都不带。

    rotation: Annotated[float | None, Field(ge=-MASK_ROTATION_LIMIT, le=MASK_ROTATION_LIMIT)] = (
        None
    )





class ClipMaskStackSet(Contract):
    """主遮罩之外那几块的整体写入：与 `clip.mask`、`clip.grade` 同一个规矩——一次交回一整串，
    不在服务端猜「第几块要换成什么」，也不给同一份状态留第二个主人。"""

    op: Literal["clip.mask_stack"]
    clip_id: Identifier
    masks: Annotated[list[ExtraShapeMask], Field(max_length=MASK_STACK_LIMIT)]
    # None 就是「这一笔不动那一格」，所以打开/关闭可以和整串一起交，也可以单独交。
    follow: bool | None = None


class ClipMaskTrack(Contract):

    """One atomic rewrite of a box mask's motion from a tracked path.



    The points are clip-local ticks; the reducer keeps the animation clock correct. Either the

    engine's own tracker or an Agent that analysed the media can supply them. A point may carry the

    box size, in which case the mask's width and height animate along with its centre, but a single

    path is either fully sized or centre-only: a half-sized path would silently drop the scale.

    """



    op: Literal["clip.mask_track"]

    clip_id: Identifier

    merge: bool = True

    points: Annotated[list[MaskTrackPoint], Field(min_length=2, max_length=2000)]



    @model_validator(mode="after")

    def advancing(self):

        marks = [point.at_ticks for point in self.points]

        if any(right <= left for left, right in zip(marks, marks[1:])):

            raise ValueError("tracked points must advance in time")

        shapes = {(point.width is not None, point.height is not None) for point in self.points}

        if len(shapes) > 1 or not shapes <= {(True, True), (False, False)}:

            raise ValueError("every tracked point must carry both width and height, or neither")

        turns = {point.rotation is not None for point in self.points}

        if len(turns) > 1:

            raise ValueError("every tracked point must carry a rotation, or none of them")

        return self





class MaskShapeSet(Contract):

    """Record one outline of a free-form mask at one clip-local time.



    The time is clip-local like every other keyframe command and the reducer folds the clip's

    animation offset in, so trimming the head does not slide the morph. Writing over an outline that

    already sits at that time replaces it — the same semantics `keyframe.set` has, because a second

    command that almost replaces would give one intent two spellings.

    """



    op: Literal["mask.shape.set"]

    clip_id: Identifier

    keyframe: MaskShapeKeyframe





class MaskShapeRemove(Contract):

    op: Literal["mask.shape.remove"]

    clip_id: Identifier

    at_ticks: Ticks





class ClipRippleRemove(Contract):

    op: Literal["clip.ripple_remove"]

    clip_id: Identifier





class ClipSplit(Contract):

    op: Literal["clip.split"]

    clip_id: Identifier

    at_ticks: Ticks

    right_clip_id: Identifier





class ClipRemove(Contract):

    op: Literal["clip.remove"]

    clip_id: Identifier





class ClipDetachAudio(Contract):

    op: Literal["clip.detach_audio"]

    clip_id: Identifier

    audio_clip_id: Identifier

    track_id: Identifier





Command = Annotated[

    SequenceNest

    | SequenceAdd

    | SequenceUpdate

    | SequenceRemove

    | TrackAdd

    | TrackRemove

    | TrackUpdate

    | AssetRegister

    | AssetImport

    | AssetRemove

    | ClipAdd

    | ClipInsert

    | ClipOverwrite

    | ClipMove

    | ClipsAdd

    | ClipsMove

    | ClipsRemove

    | ClipsSplit

    | ClipsGroup

    | ClipsLink

    | ClipTrim

    | ClipTrimLinked

    | ClipLinkSplitTrim

    | ClipsLinkReconcile

    | ClipRoll

    | ClipSplit

    | ClipSlip

    | ClipSlide

    | ClipRemove

    | ClipRippleRemove

    | ClipDetachAudio

    | ClipEffectsSet

    | ClipMaskSet
    | ClipMaskStackSet

    | ClipMaskTrack

    | ClipSpeedSet

    | ClipSpeedCurveSet

    | ClipStabilizeRecord

    | ClipColorSet

    | ClipColorManage

    | ClipGradeSet

    | ClipTextSet

    | ClipPatch

    | ClipFade

    | ClipFadeAdopt

    | MarkerSet

    | MarkerRemove

    | RecipeSet

    | RecipeRemove

    | TransitionSet

    | TransitionRemove

    | CaptionsImport

    | KeyframeSet

    | KeyframeRemove

    | KeyframeMove

    | KeyframesMove

    | KeyframesRemove

    | KeyframesReplace

    | MaskShapeSet

    | MaskShapeRemove,

    Field(discriminator="op"),

]





class CreateProject(Contract):

    request_id: Identifier

    name: Annotated[str, Field(min_length=1, max_length=256)]

    settings: SequenceSettings = Field(default_factory=SequenceSettings)





# 一批编辑命令的上限。以前的 100 在三个地方各写了一遍同一个字面量（契约、能力表、界面），

# 而它挡住的正好是「粘一大组」这种真会做的事。量过的曲线（本机，一次写入 + 一次读回整份工程）：

# 250 条 0.05s、1000 条 0.21s、2500 条 0.57s，

# 5000 条要 1.32s；累计到 8750 段时工程 JSON 是 5.7 MiB。

# 取 2500 是把「一次动作写完读回还在一秒内」那一格落成数字。

# 数只在这里写一次：能力表与界面读的都是它，不许再抄第二份。

MAX_COMMANDS_PER_BATCH = 2_500





def sequences_named(project: "Project", name: str) -> list[str]:
    """把「人看得到的那一行」折成候选 id：**全仓只有这一处这样找**。

    返回的是列表而不是一个 id——唯一才算数，撞了就要拒。写入侧（`EditBatch.target_sequence`）
    与读取侧（`timeline.sequence_view`）共用它，否则同一句「按名字找合成」会有两套答案。
    """
    return sorted(sid for sid, seq in project.sequences.items() if seq.name == name)


class EditBatch(Contract):

    request_id: Identifier

    expected_revision: Revision

    commands: Annotated[list[Command], Field(min_length=1, max_length=MAX_COMMANDS_PER_BATCH)]

    dry_run: bool = False

    sequence_id: Identifier | None = None

    sequence_name: Annotated[str | None, Field(min_length=1, max_length=256)] = None

    def target_sequence(self, project: "Project") -> str | None:
        """Which timeline this batch means, as an id.

        名字是入口，不是身份：这里只把「人看得到的那一行」折成工程里已经存着的那个 id，
        下游（`apply_commands`、`sequence_view`）拿到的仍是 id，不新增第二套语义。
        三条拒绝都不猜：两个都给就是没决定听哪个；名字撞了就把撞的那几个 id 逐条交回
        （`Sequence.name` 只限长度、没有唯一约束）；名字找不到就点名现有的一共几个、各叫什么。
        """
        if self.sequence_id is not None and self.sequence_name is not None:
            raise EditorError(
                "SEQUENCE_TARGET_BOTH",
                "sequence_id and sequence_name both point at one timeline; give exactly one",
                422,
                sequence_id=self.sequence_id,
                sequence_name=self.sequence_name,
            )
        if self.sequence_name is None:
            return self.sequence_id
        named = sequences_named(project, self.sequence_name)
        if not named:
            raise EditorError(
                "SEQUENCE_NAME_NOT_FOUND",
                f"no composition in this project is named {self.sequence_name!r}; "
                f"{len(project.sequences)} exist",
                404,
                sequence_name=self.sequence_name,
                known=[
                    {"sequence_id": sid, "name": seq.name}
                    for sid, seq in sorted(project.sequences.items())
                ],
            )
        if len(named) > 1:
            raise EditorError(
                "SEQUENCE_NAME_AMBIGUOUS",
                f"{len(named)} compositions are named {self.sequence_name!r}; names are not "
                "unique here, pass sequence_id",
                422,
                sequence_name=self.sequence_name,
                sequence_ids=named,
            )
        return named[0]





class BundleImport(Contract):

    request_id: Identifier

    content_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]





class RestoreProject(Contract):

    request_id: Identifier

    expected_revision: Revision

    target_revision: Revision





class ProjectUpdate(Contract):

    request_id: Identifier

    expected_revision: Revision

    name: Annotated[str | None, Field(min_length=1, max_length=256)] = None

    notes: Annotated[str | None, Field(max_length=4000)] = None

    settings: SequenceSettings | None = None



    @model_validator(mode="after")

    def something_to_do(self):

        if self.name is None and self.notes is None and self.settings is None:

            raise ValueError("provide name, notes or settings")

        return self





class MutationResult(Contract):

    project: Project

    committed: bool

    replayed: bool = False

    base_revision: Revision | None = None





class ImportRequest(Contract):

    path: Annotated[str, Field(min_length=1, max_length=2048)]





class ProxyRequest(Contract):

    """Build a smaller playback copy of one verified asset. Preview only — the export always uses

    the original, and nothing about the project changes."""



    width: Literal[480, 640, 960, 1280]





class MaskTrackTarget(Contract):

    """One subject to follow: a clip whose own box mask says where the target sits.



    The window and the knobs belong to the target, not to the run. Two subjects in one shot often

    need different lengths (one leaves the frame early) and different settings (a face does not

    need the scale estimate, a car walking toward the camera does). One clip carries one mask path,

    so listing the same clip twice in one run is refused by name rather than letting the second

    target quietly rewrite the first.

    """



    clip_id: Identifier

    from_ticks: Ticks = 0

    frames: Annotated[int, Field(ge=TRACK_FRAMES_MIN, le=TRACK_FRAMES_MAX)] = 120

    search_radius: Annotated[int, Field(ge=2, le=16)] = 10

    estimate_scale: bool = True

    # 1.271：in-plane rotation, searched around the last angle on every sighting. A free-form path
    # has no angle to turn, so the plan switches it off there just as it does for scale.
    estimate_rotation: bool = False

    max_gap_frames: Annotated[int, Field(ge=0, le=TRACK_GAP_MAX)] = TRACK_GAP_DEFAULT

    reacquire: bool = True

    merge: bool = True





class ExtraMaskTrackRequest(Contract):

    """Follow one block of the extra-mask stack and write its own box keys.

    The main mask has `mask_track`; this is the same tracker aimed at one of the boxes above it,
    so one clip can now follow several subjects: each block gets its own path, and the others stay
    exactly as they were. The path is decimated to the block's key ceiling (`MASK_EXTRA_KEY_LIMIT`)
    by keeping the samples a straight line cannot replace. `from_ticks` is clip-local; a constant
    speed is mapped through, a speed curve is refused because its time is not linear.

    """

    request_id: Identifier

    expected_revision: Revision

    sequence_id: Identifier | None = None

    from_ticks: Ticks = 0

    frames: Annotated[int, Field(ge=TRACK_FRAMES_MIN, le=TRACK_FRAMES_MAX)] = 120

    search_radius: Annotated[int, Field(ge=2, le=16)] = 10

    estimate_scale: bool = True

    estimate_rotation: bool = False

    max_gap_frames: Annotated[int, Field(ge=0, le=TRACK_GAP_MAX)] = TRACK_GAP_DEFAULT

    reacquire: bool = True

    dry_run: bool = False





class MaskTrackRequest(Contract):

    """Follow one or more box masks across the picture in a single run.



    A group is one decision. Every target's clip, mask, media and curve budget are checked before a

    single frame is decoded, so a group that cannot be analysed refuses by naming the target instead

    of half-writing the easy ones; all the paths then land in one batch at one revision, and one

    undo takes them back together. Targets that read the same window of the same file share one

    decode, so following three subjects in one shot costs one pass over the media rather than three.



    While a target is hidden its centre is guessed from recent motion for at most

    `max_gap_frames` frames, and every one of those frames is searched again over the whole picture

    when `reacquire` is on, so a subject that comes back somewhere else is found rather than lost.

    """



    request_id: Identifier

    expected_revision: Revision

    # The whole group is applied inside one composition: a batch carries one sequence id, so

    # targets in two different compositions are two runs rather than one that silently picks one.

    sequence_id: Identifier | None = None

    targets: Annotated[list[MaskTrackTarget], Field(min_length=1, max_length=TRACK_TARGET_LIMIT)]

    dry_run: bool = False





class ClipStabilizeRequest(Contract):

    """Analyse the clip's own frames and write the inverse of the camera's jitter as keyframes.



    `strength` is how wide a window decides which part of the motion counts as intended (0 keeps the

    shot exactly as shot, 1 smooths over a second of it); `max_crop` is how much of the frame the

    editor is willing to spend hiding the borders the correction exposes.

    """



    request_id: Identifier

    expected_revision: Revision

    # Read the ids below -- and apply the batch -- inside one nested composition.

    sequence_id: Identifier | None = None

    strength: Annotated[float, Field(ge=0, le=STABILIZE_STRENGTH_LIMIT)] = 1.0

    max_crop: Annotated[float, Field(ge=0, le=STABILIZE_MAX_CROP_LIMIT)] = 0.1

    dry_run: bool = False





class AutoGradeRequest(Contract):

    """Measure the clip's own picture and write the levels node that stretches it to full range.



    `percentile` is how much of the sampled pixels may be discarded at each end before black and

    white are declared: half a percent ignores a few hot or dead pixels instead of letting one

    specular highlight decide where white sits. `samples` is how many frames inside the clip's own

    source window get decoded. `mode` picks one luma-based stretch (it cannot invent a colour cast)

    or three per-channel stretches (it removes a cast, and costs three nodes). `replace` follows the

    stabilise rule: pressing again re-computes the correction instead of stacking a second copy,

    so with it off an existing levels node is refused by name rather than quietly doubled.

    """



    request_id: Identifier

    expected_revision: Revision

    # Read the ids below -- and apply the batch -- inside one nested composition.

    sequence_id: Identifier | None = None

    percentile: Annotated[float, Field(ge=0, le=AUTO_PERCENTILE_MAX)] = AUTO_PERCENTILE_DEFAULT

    samples: Annotated[int, Field(ge=1, le=AUTO_GRADE_SAMPLES_MAX)] = AUTO_GRADE_SAMPLES_DEFAULT

    mode: Literal["luma", "rgb"] = "luma"

    replace: bool = True

    apply: bool = False

    dry_run: bool = False





def project_content_ticks(project) -> int:

    """Where the ruler ends: the furthest clip edge on the timeline being edited.



    Markers are bounded by this, so the reducer that validates a marker and the plan that reports

    which markers fell on empty ruler cannot drift apart on how long the content is.

    """

    return max(

        (clip.position_ticks + clip.duration_ticks for clip in project.clips.values()), default=0

    )





def audio_scan_problem(project, clip) -> str | None:

    """Why this clip's audio cannot be analysed, or None when it can.



    Silence scanning and loudness metering share one answer, so a clip that is refused in one place

    cannot be silently skipped in the other.

    """

    asset = project.assets.get(clip.asset_id)

    if asset is None or asset.kind not in {"video", "audio"}:

        return "only video or audio clips carry audio to analyse"

    verified = asset.verified

    if verified is None:

        return "register the server-verified asset before analysing its audio"

    if verified.has_audio is not True:

        return "this clip's media has no audio track"

    if asset.kind == "video" and not clip.embedded_audio:

        return "this clip's sound lives on another clip; analyse the clip that holds the audio"

    if clip.speed_curve:

        return "a clip with a speed curve cannot be analysed yet: time is not linear there"

    if clip.link_id is not None:

        return "this clip is linked to another one; handle each clip separately"

    return None





class LoudnessRequest(Contract):

    """Measure one clip's audio against a loudness target, and optionally apply the matching gain.



    The gain is the only thing written: `clip.effects` carries one linear `gain`, so the browser

    preview and the export apply the same number and no dynamics processing is invented here.

    """



    request_id: Identifier

    expected_revision: Revision

    # Read the ids below -- and apply the batch -- inside one nested composition.

    sequence_id: Identifier | None = None

    target_lufs: Annotated[float, Field(ge=-30.0, le=-6.0)] = -16.0

    ceiling_dbtp: Annotated[float, Field(ge=-9.0, le=0.0)] = -1.0

    apply: bool = False

    dry_run: bool = False





# 「粘贴属性」能搬的那几类，一张表说清三件事：id（命令与回执里写的）、界面念的中文名，

# 以及这一类到底搬什么。剪映叫「粘贴属性」、达芬奇叫 Paste Attributes、AE 是复制粘贴效果栈——

# 三家给的是同一个承诺，所以这张表是唯一的名单：对话框排出它，能力表下发它，规划按它建命令。

# 为什么没有「画面稳定」与「转场」两行：前者是**这一段素材**被量出来的相机运动，后者属于

# 这一段与邻居之间的那对关系，都不是这一段自己的属性，搬过去就是一句没人能核对的声明。

ATTRIBUTE_CATEGORIES: tuple[dict[str, str], ...] = (

    {

        "id": "color",

        "label": "调色链",

        "note": "整条链一起搬，包括套着的色彩管理那一对与 3D LUT；每链的节点上限仍由引擎判。",

    },

    {

        "id": "effects",

        "label": "效果与变换",

        "note": "位置、缩放、旋转、不透明度、增益、柔焦、清晰与降噪这些静止的值，整份替换。",

    },

    {

        "id": "animation",

        "label": "关键帧动画",

        "note": "一条曲线一次替换；落在目标段尾之后的针仍在工程里但不渲染，数目照实报。",

    },

    {

        "id": "mask",

        "label": "遮罩",

        "note": "整条遮罩链：主遮罩、再叠的那几块（连各自的框点与跟随）、四条曲线的针与轮廓帧。",

    },

    {

        "id": "fade",

        "label": "淡入淡出",

        "note": "两头的窗口长度与形状；对面那头装不下时这一段整类跳过，不会写半个。",

    },

    {

        "id": "speed",

        "label": "变速",

        "note": "改的是这一段怎么播：这一段自己的长度按速率换算（源窗口不变），"

        "后面的片段不被推开；已经稳定过的段会点名拒绝。",

    },

    {

        "id": "text",

        "label": "文字样式",

        "note": "只搬这行字长什么样，每段自己打的内容留着。",

    },

)

ATTRIBUTE_CATEGORY_IDS = tuple(row["id"] for row in ATTRIBUTE_CATEGORIES)

# 一次粘多少段：规划要把每一类都交给 reducer 验一遍，而每次验都要深拷贝这份工程，

# 所以这是一个由实测出来的代价决定的数，不是「够用了」的猜测（数记在 attributes 那轮的验收里）。

ATTRIBUTE_PASTE_TARGET_LIMIT = 64





class GradeApplyTrackRequest(Contract):

    """Copy one clip's grade chain onto every other clip of that track, in one edit.



    `apply=false` is the read-only plan: the ordinary `clip.grade` commands come back together with

    each clip that cannot take the chain and why (node cap, audio clip, or the project's inline

    lookup-table budget from 1.104). `apply=true` writes the same list as one batch, so a whole

    track costs one revision and one history entry. The rules stay the reducer's; this only walks

    the track. `mode` is `replace` (each target ends up with exactly this chain) or `append`

    (this chain goes on the end of what the target already has).

    """



    request_id: Identifier

    expected_revision: Revision

    clip_id: Identifier

    mode: Literal["replace", "append"] = "replace"

    sequence_id: Identifier | None = None

    apply: bool = False

    dry_run: bool = False





class AttributePlanRequest(Contract):

    """Which aspects of one clip should be copied onto which other clips.



    Read-only by design: the response carries the ordinary commands (`clip.color`、`clip.effects`、

    `keyframes.replace`、`clip.mask`、`clip.fade`、`clip.speed`、`clip.text`) plus one entry for

    each clip the reducer would refuse, in the reducer's own words. The caller submits that list

    through `timeline_edit`, so a human click and an Agent batch write the same commands and this

    route never becomes a second writer of project state. The per-target decision is

    `apply_commands` itself — see `attributes.attribute_plan`.

    """



    request_id: Identifier

    expected_revision: Revision

    source_clip_id: Identifier

    target_clip_ids: list[Identifier]

    categories: list[str]

    sequence_id: SequenceRef | None = None





class FadeAdoptTrackRequest(Contract):

    """Move every pre-1.90 keyframe fade on one track into the edge windows, in one edit.



    `apply=false` is the read-only plan: the ordinary `clip.fade_adopt` commands come back with the

    clips that cannot move and the reason for each, and nothing is written — an Agent submits those

    commands through `timeline_edit` to commit them. `apply=true` runs the same list as

    one batch, so a whole track costs one revision. The rule stays the reducer's (`_fade_adoption`);

    this only walks the track.

    """



    request_id: Identifier

    expected_revision: Revision

    sequence_id: Identifier | None = None

    apply: bool = False

    dry_run: bool = False





class FourPointRequest(Contract):

    """Two source points plus two destination points, resolved into one placement command.



    The four integers are what a human sets with `I`/`O` on the source monitor and on the

    timeline ruler; an Agent has no eyes and passes them directly. The engine decides whether the

    source has

    to be trimmed or re-timed to fill the destination and returns ordinary `clip.insert` /

    `clip.overwrite` commands, so the reducer stays the only place that decides what a legal edit

    is.

    """



    request_id: Identifier

    expected_revision: Revision

    asset_id: Identifier

    track_id: Identifier

    source_in_ticks: Ticks

    source_out_ticks: Ticks

    dest_in_ticks: Ticks

    dest_out_ticks: Ticks

    fit: Literal["trim", "speed", "auto"] = "trim"

    mode: Literal["insert", "overwrite"] = "insert"

    ripple_track_ids: Annotated[list[Identifier] | None, Field(max_length=128)] = None

    apply: bool = False

    dry_run: bool = False





class MarkerSplitRequest(Contract):

    """Split every clip a marker falls inside, so a marked beat becomes a cut point.



    The plan is made of the ordinary `clip.split` commands, so the reducer stays the only place that

    decides what a split does. A marker over empty ruler, or within one frame of a clip edge, is not

    planned rather than producing a zero-length clip.

    """



    request_id: Identifier

    expected_revision: Revision

    track_ids: Annotated[list[Identifier] | None, Field(max_length=128)] = None

    # 1.270：也可以直接点名叫切点（节拍那一条一次点击就切好），不必先把它们写成标记。
    # 上限与一次节拍分析交回的枚数同一个数；标记本身仍由调用方决定要不要一起写。
    at_ticks: Annotated[list[Ticks], Field(min_length=1, max_length=BEAT_MARK_LIMIT)] | None = None

    apply: bool = False

    dry_run: bool = False





class SilenceRequest(Contract):

    """Scan one clip's audio for quiet stretches and hand back the commands that remove them.



    The plan is made of the ordinary `clip.split` / `clip.ripple_remove` commands, so the reducer

    stays the only place that decides what a cut does; `apply` lets the engine submit it as one

    batch, while a client that wants different boundaries can edit the commands before sending them.

    """



    request_id: Identifier

    expected_revision: Revision

    # Read the ids below -- and apply the batch -- inside one nested composition.

    sequence_id: Identifier | None = None

    threshold_db: Annotated[float, Field(ge=-80.0, le=-6.0)] = -35.0

    min_silence_ms: Annotated[int, Field(ge=80, le=5000)] = 250

    from_ticks: Ticks = 0

    to_ticks: Ticks | None = None

    trim_edges: bool = False

    apply: bool = False

    dry_run: bool = False





class BeatRequest(Contract):

    """Listen to one asset or clip and hand back where its beats fall, in timeline ticks.

    This is a read-only analysis: no request_id, no revision, no writes. The positions it returns
    are ordinary ticks a person can turn into `marker.set` commands and an Agent can plan against;
    turning them into cuts stays the existing `marker.split` decision.

    Name exactly one of `asset_id` and `clip_id`. An asset is analysed 1:1; a clip is analysed in
    the window it actually plays and mapped back through its speed, which is the difference between
    a mark on the music and a mark on the picture. A speed curve has no single ratio, so it is
    refused by name rather than guessed at.

    """

    sequence_id: Identifier | None = None

    asset_id: Identifier | None = None

    clip_id: Identifier | None = None

    min_gap_ms: Annotated[int, Field(ge=80, le=2000)] = 200

    sensitivity: Annotated[float, Field(ge=0.5, le=2.0)] = 1.0

    @model_validator(mode="after")
    def _exactly_one_target(self):
        if (self.asset_id is None) == (self.clip_id is None):
            raise ValueError("name exactly one of asset_id or clip_id")
        return self





class SpeechCaptionsRequest(Contract):

    """Transcribe speech into subtitle cues and hand back the one command that lands them.



    The plan is the ordinary `captions.import` the SRT importer takes, so the reducer keeps creating

    the track, the text asset and every cue clip; `apply` lets the engine submit it as one batch. A

    client that wants to retime or reword a line edits the SRT before sending the command itself.

    """



    request_id: Identifier

    expected_revision: Revision

    # Read the ids below -- and apply the batch -- inside one nested composition.

    sequence_id: Identifier | None = None

    clip_id: Identifier | None = None

    track_id: Identifier | None = None

    language: Literal["zh", "en"] = "zh"

    max_chars: Annotated[int, Field(ge=4, le=60)] = 16

    # A previous auto-caption track to remove in the same batch, so re-running the button replaces

    # its own output instead of stacking a second identical track under the same speech.

    replace_track_id: Identifier | None = None

    apply: bool = False

    dry_run: bool = False





class DuckRequest(Contract):

    """Plan the gain keyframes that pull one track back while another one is talking.



    Like the silence scan, this hands back ordinary commands, so the reducer stays the only place

    that decides what a keyframe does to a clip; `apply` lets the engine submit them as one batch,

    and a client that wants a shallower duck can edit the envelope before sending it back.

    """



    request_id: Identifier

    expected_revision: Revision

    # Read the ids below -- and apply the batch -- inside one nested composition.

    sequence_id: Identifier | None = None

    driver_track_ids: Annotated[list[Identifier] | None, Field(max_length=32)] = None

    depth_db: Annotated[float, Field(ge=1.0, le=36.0)] = 9.0

    attack_ms: Annotated[int, Field(ge=0, le=3000)] = 150

    hold_ms: Annotated[int, Field(ge=0, le=3000)] = 120

    release_ms: Annotated[int, Field(ge=0, le=5000)] = 600

    threshold_db: Annotated[float, Field(ge=-80.0, le=-6.0)] = -35.0

    min_silence_ms: Annotated[int, Field(ge=80, le=5000)] = 250

    apply: bool = False

    dry_run: bool = False





class ProxyPrune(Contract):

    """Free derived playback copies down to `max_bytes` (default: the engine's own limit)."""



    max_bytes: Annotated[int | None, Field(ge=0)] = None





class CachePrune(Contract):

    """Bound the whole derived cache — filmstrip tiles, waveform peaks and proxies together.



    `keep` protects content hashes the caller is still looking at, and `dry_run` returns the same

    plan without deleting anything: a destructive disk operation should be previewable.

    """



    max_bytes: Annotated[int | None, Field(ge=0)] = None

    keep: Annotated[list[Identifier], Field(max_length=64)] = Field(default_factory=list)

    dry_run: bool = False





class LutParse(Contract):

    """The text of a `.cube` file, handed to the engine's one parser.



    The client uploads the file content instead of interpreting it: there is exactly one `.cube`

    reader, in the engine, so the interface and an Agent cannot disagree about what a LUT means.

    The reply is a ready-to-send `GradeLUT` payload (without the per-node defaults).

    """



    content: Annotated[str, Field(min_length=1, max_length=524_288)]





class RenderRequest(Contract):

    request_id: Identifier

    expected_revision: Revision

    preset_id: Identifier

    filename: Annotated[str, Field(min_length=1, max_length=128)]

    folder: Annotated[str | None, Field(max_length=2048)] = None

    sequence_id: Identifier | None = None

    fit: RenderFit = "contain"

    # `marks` renders only the sequence's marked range; `full` is every render made before this

    # field existed, so the default keeps old requests and old receipts meaning the same thing.

    range: RenderRange = "full"

    # 透明背景母版。False 就是这个字段出现之前所有请求的含义，所以旧凭据重放还是它自己；

    # 它只在预设 `alpha` 为真时被接受，否则在编计划的那一步就拒掉。

    transparent: bool = False

    # 起始时间码：写给交接用的（`None` 就是没有）。合法性由 `checked_timecode` 判，不在这里判，

    # 因为它要读这条时间线自己的帧率。

    timecode: Annotated[str | None, Field(max_length=24)] = None

    # 交付帧率：把这条时间线交成另一个率（PAL／NTSC／胶片感交接）。`None` 就是 1.138 之前的含义——

    # 跟时间线自己的率一致。可选值是一张闭表，见 `checked_output_rate`。

    output_frame_rate: FrameRate | None = None

    # 1.151: declare the colour of the delivered picture, or say nothing (`None`). Only a

    # set value joins a render's fingerprint, so receipts written before this field replay.

    colour_tag: Annotated[str | None, Field(max_length=24)] = None



    @model_validator(mode="after")

    def safe_filename(self):

        return checked_render_name(self)





DEFAULT_MASTER_LUFS = -14.0



# ITU-R BT.601/709 guide insets, as a fraction of the frame: action-safe 3.5%, title-safe 5%.

# One pair of numbers so the monitor overlay and anything that later burns in a guide cannot drift.

SAFE_AREA_INSETS = {"action": 0.035, "title": 0.05}





class MasterLoudnessRequest(Contract):

    """Measure the whole mix through a throwaway render and land it on a platform loudness target.



    The measurement is not a sum of guesses: the probe renders the same audio graph the export uses,

    at a tiny canvas, and FFmpeg's own EBU R128 meter reads that file. Only then is one linear

    master gain suggested, still capped by the true-peak ceiling and the 0-4 range.

    """



    request_id: Identifier

    expected_revision: Revision

    target_lufs: Annotated[float, Field(ge=-30.0, le=-6.0)] = DEFAULT_MASTER_LUFS

    ceiling_dbtp: Annotated[float, Field(ge=-9.0, le=0.0)] = -1.0

    limiter: bool = False

    apply: bool = False

    dry_run: bool = False





class RenderBatch(Contract):

    """Several deliverables from one read of the timeline.



    A short-video editor ships the same cut to a horizontal and a vertical platform in one go, so

    the engine has to be the place that promises all-or-nothing: a client that loops over `renders`

    can leave half a delivery queued when the second item turns out to be invalid.

    """



    request_id: Identifier

    expected_revision: Revision

    items: Annotated[list[RenderBatchItem], Field(min_length=1, max_length=4)]

    dry_run: bool = False



    @model_validator(mode="after")

    def distinct_names(self):

        names = [item.filename for item in self.items]

        if len(set(names)) != len(names):

            raise ValueError("each deliverable in a batch needs its own file name")

        return self





class RenderJob(Contract):

    id: Identifier

    project_id: Identifier

    revision: Revision

    sequence_id: Identifier | None = None

    preset_id: Identifier

    fit: RenderFit = "contain"

    range: RenderRange = "full"

    # 任务自己带着这个勾：worker 到点重编计划时按它渲染，排队的人看到的和落地的是同一张画面。

    # 老任务文档里没有这一行，读回来就是 False。

    transparent: bool = False

    # 任务带着它，worker 到点重编计划时写的还是同一个时间码；老任务文档没有这一行，读回来是 None。

    timecode: Annotated[str | None, Field(max_length=24)] = None

    # 交付帧率同理：排队时选的那个率，落地的文件就得是那个率。

    output_frame_rate: FrameRate | None = None

    # 1.151: declare the colour of the delivered picture, or say nothing (`None`). Only a

    # set value joins a render's fingerprint, so receipts written before this field replay.

    colour_tag: Annotated[str | None, Field(max_length=24)] = None

    filename: Annotated[str, Field(max_length=2048)]

    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]

    total_ticks: Ticks = 0

    rendered_ticks: Ticks = 0

    message: Annotated[str, Field(max_length=4000)] = ""

    error_code: Annotated[str | None, Field(max_length=64)] = None

    output_path: Annotated[str | None, Field(max_length=2048)] = None

    output_size_bytes: Annotated[int | None, Field(ge=0)] = None

    # Whether the finished file was re-opened and measured before it was called a delivery. False is

    # a real state, not a default to ignore: it means no ffprobe stood beside the FFmpeg that ran

    # this job, so `message` says the file went out unchecked.

    output_checked: bool = False

    created_at: Annotated[str, Field(max_length=64)] = ""

    updated_at: Annotated[str, Field(max_length=64)] = ""

    elapsed_seconds: Annotated[float | None, Field(ge=0)] = None



    @property

    def progress(self) -> float:

        if not self.total_ticks:

            return 0.0

        return min(1.0, self.rendered_ticks / self.total_ticks)





class JobView(Contract):

    job: RenderJob

    plan: Annotated[dict, Field(max_length=200_000)] = Field(default_factory=dict)





class EditorError(Exception):

    def __init__(self, code: str, message: str, status: int = 422, **details):

        super().__init__(message)

        self.code, self.message, self.status, self.details = code, message, status, details



    def payload(self) -> dict:

        return {"code": self.code, "message": self.message, "details": self.details}





# Containers this build can write. A request picks a preset id, the preset names one of these, and

# `jobs` requires the file name to carry the matching extension — so a delivered file is never a

# stream the container cannot hold, and no caller can aim FFmpeg at an arbitrary muxer.

OUTPUT_CONTAINERS = ("mp4", "mov", "webm", "mxf", "mp3", "wav", "flac", "exr", "dpx")



# The codecs `render.output_args` knows how to ask for. Anything outside this set is refused rather

# than passed through, which is what keeps the preset table a closed vocabulary of encoder knobs.

# `None` means the deliverable carries no picture at all: the mix is the product.

# `exr`/`dpx` are the two image-sequence writers — one file per frame, no container for audio.

OUTPUT_CODECS = (

    None,

    "libx264",

    "libx265",

    "libvpx-vp9",

    "prores_ks",

    "mpeg2video",

    "exr",

    "dpx",

)

# `""` means the deliverable carries no sound at all — only the two image-sequence presets get to

# say that, because a string of image files has nowhere to put a mix.

OUTPUT_AUDIO_CODECS = ("aac", "libopus", "pcm_s24le", "libmp3lame", "flac", "")





def _preset(

    preset_id: str,

    label: str,

    container: str,

    codec: str | None,

    *,

    crf: int | None,

    encoder_preset: str | None,

    audio_codec: str,

    audio_bitrate: str | None,

    pixel_format: str | None,

    scale: list[int] | None,

    profile: int | None = None,

    quality: int | None = None,

    alpha: bool = False,

    sequence: bool = False,

) -> dict:

    """One delivery target: encoder knobs from a closed set, never raw FFmpeg arguments.



    `crf`, `encoder_preset` and `audio_bitrate` are None where the codec has no such knob: ProRes is

    chosen by a profile, VP9 needs an explicit zero video bitrate next to its crf, and PCM is

    lossless so a bitrate would be a lie. `pixel_format` is not cosmetic — it decides the chroma

    subsampling the final graph stage is written to, so a 4:4:10-bit intermediate really does keep

    the colour the composite had. `alpha` is the one statement of whether a preset has room for a

    transparency band: only such a preset may take a request's `transparent` flag, and the export

    panel's tickbox reads the same field, so a matte can never be dropped on the floor while

    everyone involved believes the file still carries one.

    """

    return {

        "id": preset_id,

        "label": label,

        "container": container,

        "codec": codec,

        "crf": crf,

        "encoder_preset": encoder_preset,

        "audio_codec": audio_codec,

        "audio_bitrate": audio_bitrate,

        "pixel_format": pixel_format,

        "profile": profile,

        "quality": quality,

        "scale": scale,

        "alpha": alpha,

        # 图像序列没有容器可以装东西：声音与起始时间码都无处安放，所以引擎点名拒，

        # 而不是收下之后再什么都不做。

        "sequence": sequence,

    }





def render_presets() -> list[dict]:

    """Controlled output presets. Callers choose one; they never pass encoder flags."""



    return [

        _preset(

            "h264-source-quality",

            "原始画质 H.264（推荐交付）",

            "mp4",

            "libx264",

            crf=18,

            encoder_preset="medium",

            audio_codec="aac",

            audio_bitrate="256k",

            pixel_format="yuv420p",

            scale=None,

        ),

        _preset(

            "h264-1080p",

            "1080p 标准（体积均衡）",

            "mp4",

            "libx264",

            crf=23,

            encoder_preset="veryfast",

            audio_codec="aac",

            audio_bitrate="192k",

            pixel_format="yuv420p",

            scale=[1920, 1080],

        ),

        _preset(

            "h264-720p-web",

            "720p 网络分享（最小体积）",

            "mp4",

            "libx264",

            crf=26,

            encoder_preset="veryfast",

            audio_codec="aac",

            audio_bitrate="128k",

            pixel_format="yuv420p",

            scale=[1280, 720],

        ),

        _preset(

            "h264-2160p",

            "4K 高画质存档",

            "mp4",

            "libx264",

            crf=20,

            encoder_preset="slow",

            audio_codec="aac",

            audio_bitrate="320k",

            pixel_format="yuv420p",

            scale=[3840, 2160],

        ),

        _preset(

            "h264-1080x1920-vertical",

            "9:16 竖屏（抖音/Shorts 交付）",

            "mp4",

            "libx264",

            crf=20,

            encoder_preset="veryfast",

            audio_codec="aac",

            audio_bitrate="192k",

            pixel_format="yuv420p",

            scale=[1080, 1920],

        ),

        _preset(

            "h264-1080-square",

            "1:1 方形（信息流卡片）",

            "mp4",

            "libx264",

            crf=21,

            encoder_preset="veryfast",

            audio_codec="aac",

            audio_bitrate="160k",

            pixel_format="yuv420p",

            scale=[1080, 1080],

        ),

        _preset(

            "proxy-540p-fast",

            "540p 代理（快速查看/审片）",

            "mp4",

            "libx264",

            crf=30,

            encoder_preset="superfast",

            audio_codec="aac",

            audio_bitrate="96k",

            pixel_format="yuv420p",

            scale=[960, 540],

        ),

        # HEVC's rate-control tiers were measured, not guessed (see docs/optimization.md 1.57): on a

        # 2-second 1080p synthetic clip x265 crf 24 reached SSIM 0.996687 where x264 crf 23 gave

        # 0.996313, so this is a quality tier, not a promised size win — the label says no more than

        # that. hvc1 (not hev1) so QuickTime and editors accept the MP4.

        _preset(

            "h265-1080p",

            "1080p HEVC/H.265（需播放器支持）",

            "mp4",

            "libx265",

            crf=24,

            encoder_preset="medium",

            audio_codec="aac",

            audio_bitrate="192k",

            pixel_format="yuv420p",

            scale=[1920, 1080],

        ),

        _preset(

            "h265-2160p",

            "4K HEVC/H.265 存档",

            "mp4",

            "libx265",

            crf=22,

            encoder_preset="medium",

            audio_codec="aac",

            audio_bitrate="256k",

            pixel_format="yuv420p",

            scale=[3840, 2160],

        ),

        _preset(

            "vp9-1080p-web",

            "1080p WebM/VP9（网页与开放分发）",

            "webm",

            "libvpx-vp9",

            crf=32,

            encoder_preset=None,

            audio_codec="libopus",

            audio_bitrate="128k",

            pixel_format="yuv420p",

            scale=[1920, 1080],

        ),

        _preset(

            "prores-422hq",

            "ProRes 422 HQ 中间码（后期交接，体积大）",

            "mov",

            "prores_ks",

            crf=None,

            encoder_preset=None,

            audio_codec="pcm_s24le",

            audio_bitrate=None,

            pixel_format="yuv444p10le",

            scale=None,

            profile=3,

        ),

        # 透明通道母版：给 After Effects / DaVinci 做合成回环的那一条。ProRes 4444 是这一行的

        # 名字，profile 4 才有 alpha；`alpha=True` 是「装得下透明度」唯一的一处说法，

        # render.output_args 的拒绝和导出面板那个勾都读它，所以两边不可能各说一套。

        _preset(

            "prores-4444-alpha",

            "ProRes 4444 透明母版（AE / DaVinci 合成回环）",

            "mov",

            "prores_ks",

            crf=None,

            encoder_preset=None,

            audio_codec="pcm_s24le",

            audio_bitrate=None,

            pixel_format="yuva444p10le",

            scale=None,

            profile=4,

            alpha=True,

        ),

        # VP9 也能带 alpha，体积比 ProRes 小得多，网页上的叠加层用这一条。它的透明度是挂在每个

        # block 后面的附带通道里的，ffprobe 在流这一层只报 yuv420p——所以这条的复检必须真解一帧

        # 去看 alpha 平面，不能读容器元数据就下结论（tests/alphamaster_check.py 就是这么量的）。

        _preset(

            "vp9-1080p-web-alpha",

            "1080p WebM/VP9 透明（网页叠加层）",

            "webm",

            "libvpx-vp9",

            crf=32,

            encoder_preset=None,

            audio_codec="libopus",

            audio_bitrate="128k",

            pixel_format="yuva420p",

            scale=[1920, 1080],

            alpha=True,

        ),

        # MXF：广播与后期机房之间的包装。容器只认这条表，文件名后缀与复检读的都是同一处，

        # 所以不会出现「写着 .mxf 其实是 mp4」。MXF 的音频轨只接受 48 kHz（FFmpeg 那边直接拒

        # 写头），这条约束在 render.output_args 一处挡下来，而不是等 FFmpeg 报一句看不懂的话。

        _preset(

            "mxf-prores-422hq",

            "MXF ProRes 422 HQ（机房交接，PCM 24 位）",

            "mxf",

            "prores_ks",

            crf=None,

            encoder_preset=None,

            audio_codec="pcm_s24le",

            audio_bitrate=None,

            pixel_format="yuv422p10le",

            scale=None,

            profile=3,

        ),

        _preset(

            "mxf-mpeg2",

            "MXF MPEG-2（广播母带，PCM 24 位）",

            "mxf",

            "mpeg2video",

            crf=None,

            encoder_preset=None,

            audio_codec="pcm_s24le",

            audio_bitrate=None,

            pixel_format="yuv420p",

            scale=None,

            quality=5,

        ),

        # Audio-only deliverables: `codec=None` means the picture chain is never compiled, so an MP3

        # of a three-minute cut costs the mix, not a full render. The mix is the same authoritative

        # one the video presets use — master gain, ducking envelopes and the limiter included.

        # 1.142：开链交付。这台 FFmpeg 实测写得出、也读得回 alpha 平面——rgba64le 与 gbrap10le

        # 读回来的 alpha 都是 127，RGB 仍是 255,0,0，不是把透明度烘进画面那种。

        _preset(

            "exr-sequence",

            "OpenEXR 图像序列（16 位，带 alpha）",

            "exr",

            "exr",

            crf=None,

            encoder_preset=None,

            audio_codec="",

            audio_bitrate=None,

            pixel_format="rgba64le",

            scale=None,

            alpha=True,

            sequence=True,

        ),

        _preset(

            "dpx-sequence",

            "DPX 图像序列（10 位，带 alpha）",

            "dpx",

            "dpx",

            crf=None,

            encoder_preset=None,

            audio_codec="",

            audio_bitrate=None,

            pixel_format="gbrap10le",

            scale=None,

            alpha=True,

            sequence=True,

        ),

        _preset(

            "audio-mp3",

            "MP3 音频（口播与配乐交付）",

            "mp3",

            None,

            crf=None,

            encoder_preset=None,

            audio_codec="libmp3lame",

            audio_bitrate="192k",

            pixel_format=None,

            scale=None,

        ),

        _preset(

            "audio-wav",

            "WAV 音频（24 位无损，进混音台）",

            "wav",

            None,

            crf=None,

            encoder_preset=None,

            audio_codec="pcm_s24le",

            audio_bitrate=None,

            pixel_format=None,

            scale=None,

        ),

        _preset(

            "audio-flac",

            "FLAC 音频（无损存档，体积小）",

            "flac",

            None,

            crf=None,

            encoder_preset=None,

            audio_codec="flac",

            audio_bitrate=None,

            pixel_format=None,

            scale=None,

        ),

    ]





def capabilities(

    media_ready: bool = False, speech_ready: bool = False, text_fonts: list[dict] | None = None

) -> dict:

    return {

        "api_version": "v1",

        # The text faces installed here, as `{id, label, family}`. The interface builds its font

        # picker from this list and the browser draws with `family`, so a face the exporter cannot

        # load is never offered to a person or an Agent.

        "text_fonts": list(text_fonts or []),

        # The guide geometry the monitor draws: the engine owns the numbers so the overlay cannot

        # drift from any future burn-in or export check.

        "safe_area_insets": SAFE_AREA_INSETS,

        "mask_vertex_limit": MASK_VERTEX_LIMIT,

        # The grade chain's own shape limits, published the same way: the node picker, the curve

        # point budget, the branch count and the largest LUT grid all come from here, so the

        # interface cannot offer a node the compiler would refuse.

        "grade_limits": {

            "max_nodes": GRADE_NODE_LIMIT,

            "max_branches": GRADE_BRANCH_LIMIT,

            "branch_weight_max": GRADE_BRANCH_WEIGHT_MAX,

            # 1.124：一支也可以是一台混频台。层数、以及「一个链节点底下的树总共多少个操作」都由

            # 这里下发——界面不许自己数层数，也不许自己写那个 8。

            "max_mixer_depth": GRADE_MIXER_DEPTH,

            "max_tree_operations": GRADE_NODE_LIMIT,

            # 1.189：第二路画面是另一张素材。条数与「能不能叠」都由这里下发。

            "max_layers": GRADE_LAYER_LIMIT,

            "layer_offset_max": LAYER_OFFSET_MAX,

            "layer_scale_min": LAYER_SCALE_MIN,

            "layer_scale_max": LAYER_SCALE_MAX,

            # 1.203：转角的上限同样只由这里下发；老引擎不回这个数，界面就不给那一颗旋钮。

            "layer_rotation_max": LAYER_ROTATION_MAX,

            # 1.192：那一层能动的是哪三个数也只由引擎说一次（界面不许自备一份属性名表）。

            "layer_key_props": list(get_args(LayerProperty)),

            # 1.205：那五个数各自能到几，也只由这里说一次（曲线编辑器画纵轴、检查器打点、写入时
            # 那句拒绝必须问的是同一条带，不然「界面允许、引擎拒绝」就又回来了）。
            "layer_key_bands": {
                name: [band[0], band[1]] for name, band in LAYER_KEY_LIMITS.items()
            },

            "max_curve_points": CURVE_POINT_LIMIT,

            "max_lut_samples": LUT_SAMPLE_LIMIT,

            # A 3D LUT's grid lives inline in project state, so the importer resamples anything

            # larger to this edge count and reports `resampled_from`.

            "max_lut3d_size": LUT3D_SIZE_LIMIT,

            "max_inline_samples": GRADE_INLINE_SAMPLE_LIMIT,

            "levels_black_max": LEVELS_BLACK_MAX,

            "levels_white_min": LEVELS_WHITE_MIN,

            "levels_gamma_min": LEVELS_GAMMA_MIN,

            "levels_gamma_max": LEVELS_GAMMA_MAX,

            "matrix_limit": MATRIX_LIMIT,

        },

        # The transition picker enumerates this list rather than carrying its own copy, so a kind

        # the exporter cannot honour can never appear in the interface.

        "transition_kinds": [dict(item) for item in TRANSITION_KINDS],

        # 淡的形状同一条规矩：界面列的是这份表，不是自己写的四个名字。

        "fade_shapes": [dict(item) for item in FADE_SHAPES],

        "color_spaces": list(COLOR_SPACES),

        # 1.257：框点那几种缓动由引擎交下来——界面不许自己滤掉某一种，也不许自备第二份名单。

        "mask_box_interpolations": list(MASK_BOX_INTERPOLATIONS),

        # 1.150: the translation `clip.color_manage`'s `auto_source` actually uses. A renderer that

        # guessed which tag means which curve would disagree with the engine, so the table goes out.

        "color_transfer_tags": [{"tag": tag, "space": space} for tag, space in COLOR_TRANSFER_TAGS],

        # 基色转换表：矩阵由引擎算（`gamut.py`），界面与 Agent 都从这一处读。手抄的九个数迟早和

        # 另一侧不一样，而这种不一致在成片里只表现为「颜色有点偏」。

        "gamut_matrices": gamut_presets(),

        # 1.163：「粘贴属性」能搬的那几类，连界面念的中文名与「这一类到底搬什么」那句话一起交。

        # 对话框排出这一份，界面不许自己再列一遍名单。

        "attribute_categories": [dict(row) for row in ATTRIBUTE_CATEGORIES],

        # 1.159：工程基色可选的那几档，由 `gamut.PRIMARIES` 现算——界面那张下拉菜单列的就是

        # 这一份，抄一份就会与引擎拒收的那一份不一致。

        "working_primaries": list(WORKING_PRIMARIES),

        # 1.161：折叠那一步走哪档曲线，连同「这一档是谁」那句话一起交出去——一个名字两条

        # 曲线，所以名单必须带着区分说话，界面不许自己再编一遍句子。

        "fold_transfers": fold_transfer_rows(),

        "output_containers": list(OUTPUT_CONTAINERS),

        # 哪几条预设真的装得下透明度。界面那个勾和引擎那句拒绝读的都是同一份预设表，

        # 所以「勾了透明却导出一个不透明的文件」这件事没有发生的余地。

        "alpha_presets": [item["id"] for item in render_presets() if item["alpha"]],

        # 序列那两条也单独下发：界面要说「声音与时间码进不去序列」，靠的是这一份，不自己猜表。

        "sequence_presets": [item["id"] for item in render_presets() if item["sequence"]],

        # 时间码的写法与「哪两个率才有丢帧码」由引擎说，界面不许自己写死一份正则：

        # 这两条就是 `checked_timecode` 用的同一组常量。

        # 交付帧率的那张闭表也下发出去：界面排出来的就是这几档，不许自己再列一份。

        # 1.151: the one claim a master may make about its own colour, and the flags that

        # make it true. An interface that listed its own tag names would drift from this.

        "output_colour_tags": [dict(row) for row in OUTPUT_COLOUR_TAGS],

        # 每一档带得出去的预设（宽色那一档要 10 位 4:4:4）：界面据此灰态，引擎据此拒绝，

        # 两处读同一份，不许界面自己再判一次像素格式。

        "output_colour_tag_presets": colour_tag_presets(),

        "output_frame_rates": [

            {"numerator": numerator, "denominator": denominator, "label": label}

            for numerator, denominator, label in OUTPUT_FRAME_RATES

        ],

        "timecode_shape": TIMECODE_SHAPE,

        "timecode_drop_rates": [list(item) for item in TIMECODE_DROP_RATES],

        # The build identity, next to the schema it speaks: an Agent reading this document can tell

        # which engine answered, and the desktop shows it in the title bar.

        "app_version": APP_VERSION,

        "project_schema_version": SCHEMA_VERSION,

        "timebase": TIMEBASE,

        "max_commands_per_batch": MAX_COMMANDS_PER_BATCH,

        "commands": [

            "sequence.nest",

            "sequence.add",

            "sequence.update",

            "sequence.remove",

            "track.add",

            "track.remove",

            "track.update",

            "asset.register",

            "asset.import",

            "asset.remove",

            "clip.add",

            "clip.insert",

            "clip.overwrite",

            "clip.move",

            "clips.add",

            "clips.move",

            "clips.remove",

            "clips.split",

            "clips.group",

            "clips.link",

            "clip.trim",

            "clip.trim_linked",

            "clip.link_split_trim",

            "clips.link_reconcile",

            "clip.roll",

            "clip.split",

            "clip.slip",

            "clip.slide",

            "clip.remove",

            "clip.ripple_remove",

            "clip.detach_audio",

            "clip.effects",

            "clip.mask",
            "clip.mask_stack",

            "clip.mask_track",

            "clip.speed",

            "clip.speed_curve",

            "clip.stabilize_record",

            "clip.color",

            "clip.color_manage",

            "clip.grade",

            "clip.text",

            "clip.patch",

            "clip.fade",

            "clip.fade_adopt",

            "marker.set",

            "marker.remove",

            "recipe.set",

            "recipe.remove",

            "transition.set",

            "transition.remove",

            "captions.import",

            "keyframe.set",

            "keyframe.remove",

            "keyframe.move",

            "keyframes.move",

            "keyframes.remove",

            "keyframes.replace",

            "mask.shape.set",

            "mask.shape.remove",

        ],

        "features": {

            "atomic_batch": True,

            "multi_clip_editing": True,

            "persistent_groups": True,

            "linked_av_editing": True,

            "dry_run": True,

            "revision_conflicts": True,

            "durable_idempotency": True,

            "history_restore": True,

            "asset_metadata_registration": True,

            "media_probe": media_ready,

            "thumbnails": media_ready,

            "waveform": media_ready,

            "preview_stream": media_ready,

            "composite_frames": media_ready,

            "project_bundles": media_ready,
            "preview_manifest_clips_max": CLIP_SUBSET_LIMIT,
            "project_clips_max": CLIP_SUBSET_LIMIT,
            # 1.187: a list query parameter cannot be empty, so "describe no clip at all"
            # needs its own word. Without it a caller whose playhead sits in a gap cannot
            # ask for less than the whole project.
            "preview_manifest_no_clips": True,
            "edit_receipt_slim": True,

            "render": media_ready,

            "render_jobs": media_ready,

            "straight_cut_compositing": media_ready,

            "layered_overlay": media_ready,

            "keyframes": True,

            "bezier_keyframes": True,

            "multi_keyframe_editing": True,

            "animation_curves": True,

            "clip_effects": True,

            "clip_property_patches": True,

            "sequence_lookup_by_name": True,

            "sequence_read_by_name": True,

            "nested_sequences": True,

            "shape_masks": True,

            "path_masks": True,

            "mask_animation": True,

            # 1.164: a rectangle/ellipse box carries its own angle. The browser can only paint a

            # rotated mask from an image the engine baked (measured on the Chromium this app ships

            # with - a CSS transform on the masked layer leaves the mask axis-aligned), so the angle

            # is executed as frames, one plate per window, never as one stretched unit image.

            "mask_rotation": True,
            "mask_stack": True,
            "mask_stack_follow": True,
            "extra_mask_motion": True,
            # 1.258：那一串框点里也可以带羽化。界面据此决定「停在框点上改羽化」写的是这一枚
            # 还是这一块自己——不认识这一格的引擎会连整条写入一起拒。
            "extra_mask_feather": True,
            # 1.263「先跟后动」：带框点的那一块也可以同时被主遮罩带着走——窗表是它自己的，
            # 位移是主遮罩这一帧挪了多少。不认识这一格的引擎仍然把两者当成互斥来做，
            # 所以界面那句「先跟后动」只能在这一格报得出时说。
            "extra_mask_follow_motion": True,

            "extra_mask_track": media_ready,

            "mask_track_rotation": True,

            # 1.165: that angle accepts keyframes. Both ends execute one frame-aligned staircase

            # (`animation.mask_box_schedule`), which is why this is a switch of its own: an engine

            # without it refuses the curve by name rather than pretending to smooth it.

            "mask_rotation_curves": True,

            # 1.259：软边也能打成曲线。它不是 CSS 量能表达的东西（斜坡住在烘出来的那张板里），
            # 所以带软边针的那一块按窗换图——界面没有这一格就只给中心那两条，不许长出第二份判断。
            "mask_feather_curves": True,

            # 1.166: a turning box also accepts 遮罩宽度/遮罩高度 curves. They are not continuous

            # either - the same table steps the angle and the two edges on the same boundary,

            # because one rotated plate stretched non-uniformly would shear the angle. An engine

            # without this switch refuses that combination by name.

            "mask_rotation_size_curves": True,

            # 1.118: a free-form outline can morph. The exporter executes it as frame-aligned

            # constant windows (`animation.mask_shape_schedule`) and the preview ships that same

            # window list, so this says "the shape steps on both ends", not "the shape is smooth".

            "path_shape_keys": True,

            "mask_tracking": media_ready,

            "mask_track_group": media_ready,

            "silence_detection": media_ready,

            "loudness_metering": media_ready,

            # A local speech model turns one clip's own audio into an SRT the importer lands.

            "speech_captions": media_ready and speech_ready,

            "output_fit_modes": media_ready,

            "multi_codec_delivery": media_ready,

            "audio_delivery": media_ready,

            # Every finished job is re-opened and measured before it is called a delivery.

            "verified_delivery": media_ready,

            "batch_delivery": media_ready,

            "master_loudness": media_ready,

            "master_limiter": media_ready,

            "audio_ducking": media_ready,

            "timeline_markers": True,

            "beat_detect": media_ready,

            "delivery_recipes": media_ready,

            "safe_area_guides": True,

            "subject_reframe": True,

            "cache_pruning": media_ready,

            "slip_slide_editing": True,

            "track_blend_modes": True,

            "track_lock": True,

            "ripple_delete": True,

            "insert_edit": True,

            "overwrite_edit": True,

            "transitions": True,

            "wipe_transitions": True,

            "zoom_transitions": True,

            # 1.94: push/slide move whole layers. The offsets ride the same clip-local clock the

            # clip's own x/y keyframes use, so the exporter and the browser read one envelope list.

            "motion_transitions": True,

            "speed_change": True,

            "speed_curve": True,

            "color_correction": True,

            # 1.150: `clip.color_manage` can take its source end from the file's own colour tags.

            "color_manage_auto": True,

            # 1.151: `RenderRequest.colour_tag` swaps the fold and writes the tags.

            "colour_tag_delivery": True,

            "grade_nodes": True,

            "grade_node_mix": True,

            "lut_import": True,

            "lut3d": True,

            # 1.234：浏览器这一端也能画立方表了——`gradeCanvas.ts` 用 WebGL2 采样同一张表、
            # 同一个四面体插值档，与导出的 `lut3d=…:interp=tetrahedral` 读的是同一批格点。
            # 唯一的例外是链上还有第二路画面（composite / layer）：那要两个输入，画布只接一个，
            # 引擎在那条链上把立方阶段标成 `preview: false`，界面照旧说「预览不生效」。

            "lut3d_preview": True,

            # 1.144：链子的第二路画面输入。编译与导出这一端是真的生效（`split` + `blend`），

            # 浏览器没有能画两条输入的滤镜原语，所以预览那一路它被明说成「不生效」——与 3D LUT

            # 同一个口径：只有一端能执行的强度不是强度，说不出口的差别才是骗人。

            "grade_composite": True,

            # `GET /v1/projects/{id}/grade-capacity` and MCP `grade_capacity` read the same

            # numbers the reducer refuses with, so usage can be asked before an edit.

            "grade_capacity": True,

            # 一条片段的调色链能不能一次套到整轨（规划与写入同一条规矩）。

            "grade_apply_track": True,

            # 一段的这几类属性一次粘到别的段上（规划与写入同一条 reducer，见 attributes）。

            "attribute_paste": True,

            "text_styling": True,

            "clip_blur": True,

            "clip_sharpen": True,

            "clip_stabilize": True,

            "clip_denoise": True,

            "grade_levels": True,

            "grade_matrix": True,

            # Measuring a clip's own frames needs the media engine, like every other analysis here.

            "clip_auto_grade": media_ready,

            "grade_node_blend_modes": True,

            "grade_parallel_branches": True,

            # 并联节点的分支增益：下发这个，界面才知道那一排旋钮不是自己想象出来的。

            "grade_branch_weights": True,

            "grade_branch_blend_modes": True,

            # 1.124：支路能再是一台混频台（树）。开关说的只是「引擎收不收这种载荷」，

            # 层数与操作数在上面对下发。

            "grade_mixer_trees": True,

            # 1.189：第二路画面可以是另一张图像素材（链尾、按顺序叠）。开关说的只是

            # 「引擎收不收这种载荷」，条数在 grade_limits.max_layers，模式就是 BlendMode 那张表。

            "grade_layer": True,

            # 1.190：层可以只盖画面的一角。开关说的还是「引擎收不收这种载荷」。

            "grade_layer_placement": True,

            # 1.192：那一层的位置与大小现在能按窗动。开关口径不变——「引擎收不收这种载荷」；
            # 针的额度在 limits.layer_key_limit，一次最多几段在 limits.layer_schedule_segments。

            "layer_keyframes": True,

            # 1.205：那一层的阶梯进得了曲线编辑器（读路由 `/v1/animation/layer_curve`）。
            # 界面这一档只有在这个开关为真时才排那几行属性，老引擎不回就是没有。

            "layer_curve": True,

            # 1.193：「叠一层原图」这条边现在监视器真的画（逐档与导出对过表）。哪一段画得了由
            # `preview-manifest` 那一行的 `paintable` 说，界面无条件听引擎，不再自己问素材是什么。

            "composite_preview": True,

            # 1.203：第二路画面会转。导出走 `rotate` + 一条按 alpha 做的 mask，监视器走同一转角
            # 的 `rotate()`；两边逐档量过（`tests/layerrotate_check.py`）才敢下发这一格。

            "layer_rotation": True,

            "timeline_marks": True,

            "range_export": True,

            "four_point_editing": True,

            "color_space_transform": True,

            "proxy_playback": media_ready,

            "text_titles": True,

            "srt_captions": True,

            "clip_fades": True,

            # 1.90: a fade is stored as the clip's own edge windows (`Clip.fade`) and multiplied

            # into the property curve at render, so an in-fade and an out-fade coexist and neither

            # one erases a duck or hand-keyed curve. `clip_fades` alone was the keyframe behaviour.

            "clip_fade_envelopes": True,

            # 1.95: a fade window now carries a shape (linear / 缓入 / 缓出 / 缓入缓出).

            # `clip_fade_shapes` says the shape exists; `capabilities.fade_shapes` is the only list

            # the interface may read those names and labels from.

            "clip_fade_shapes": True,

            # 1.96: a pre-1.90 keyframe fade can be moved into the edge windows in one command.

            "clip_fade_adopt": True,

            # 1.97: the same move across one whole track, as a plan or as a single edit.

            "clip_fade_adopt_track": True,

            # 1.98: soft focus can be keyframed. It compiles to a bounded staircase that both ends

            # consume, so `limits.blur_schedule_segments` says how coarse the steps may get.

            "blur_keyframes": True,

            # 1.123: so can the unsharp mask's amount and radius — together, on one frame grid, so

            # the two curves cannot step past each other. Its own ceiling is in the same list.

            "sharpen_keyframes": True,

        },

        "limits": {

            "max_tracks": 128,

            "max_assets": 10_000,

            "max_clips": 20_000,

            "max_sequence_depth": 8,

            "blur_fraction": BLUR_LIMIT,

            "blur_radius_limit_px": BLUR_RADIUS_LIMIT_PX,

            "sharpen_amount": SHARPEN_LIMIT,

            "sharpen_radius_fraction": BLUR_LIMIT,

            "sharpen_radius_default": SHARPEN_RADIUS_DEFAULT,

            "blur_schedule_segments": SPATIAL_SCHEDULE_MAX,

            "sharpen_schedule_segments": SHARPEN_SCHEDULE_MAX,

            # A morphing outline is bounded by the same kind of number: how many outlines one mask

            # carries, and how many plates the export and the preview each execute.

            "mask_rotation_limit": MASK_ROTATION_LIMIT,

            "mask_shape_keys": MASK_SHAPE_KEY_LIMIT,
            "extra_masks": MASK_STACK_LIMIT,
            "extra_mask_keys": MASK_EXTRA_KEY_LIMIT,

            "mask_shape_schedule_segments": MASK_SHAPE_SCHEDULE_MAX,

            "mask_rotation_schedule_segments": MASK_ROTATION_SCHEDULE_MAX,

            # 1.192：第二路画面那三个数一共几枚针、一次下发几段（每段是一路 crop 加两段
            # blend 再加一次 overlay，所以这一族自己带一个比柔焦更小的天花板）。

            "layer_key_limit": LAYER_KEY_LIMIT,

            "layer_schedule_segments": LAYER_SCHEDULE_MAX,

            "denoise_db": DENOISE_LIMIT,

            "auto_grade_samples_max": AUTO_GRADE_SAMPLES_MAX,

            "auto_grade_percentile_max": AUTO_PERCENTILE_MAX,

            "stabilize_max_crop": STABILIZE_MAX_CROP_LIMIT,

            "stabilize_smoothing_frames": STABILIZE_SMOOTHING_FRAMES,

            "track_max_gap_frames": TRACK_GAP_MAX,

            "track_gap_default": TRACK_GAP_DEFAULT,

            "track_min_frames": TRACK_FRAMES_MIN,

            "track_max_frames": TRACK_FRAMES_MAX,

            "track_max_targets": TRACK_TARGET_LIMIT,

            "attribute_paste_targets": ATTRIBUTE_PASTE_TARGET_LIMIT,

            "subtitle_cues": SUBTITLE_CUE_LIMIT,

            "beat_marks": BEAT_MARK_LIMIT,

            "sample_rates": [44_100, 48_000, 96_000],

        },

        "render_presets": render_presets(),

    }

