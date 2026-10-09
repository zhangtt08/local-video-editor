"""Versioned JSON contracts; no HTTP, MCP, database, or media engine imports."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TIMEBASE = 70_560_000
MAX_TICKS = 2**53 - 1  # JSON integers remain exact in JavaScript clients.
SCHEMA_VERSION = 13  # v13 gives a path mask a real box; older rows are fitted on load (ge=1).
APP_VERSION = "1.88.0"  # one place: /v1/info, the OpenAPI document and the desktop shell must agree
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]
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
# What `clip.patch` may write is wider than what can be keyframed: `blur`, `sharpen` and
# `sharpen_radius` have no per-frame form (see ClipEffects), so they are patchable without being
# animatable properties.
EffectField = EffectProperty | Literal["blur", "sharpen", "sharpen_radius", "denoise"]
# Rectangle and ellipse masks keyframe in the mask's own normalized space, so the exporter and the
# browser interpolate the same numbers. A free-form (path) mask rasterizes its outline once and can
# be moved with mask_x/mask_y, but its drawn shape and size cannot change over time yet.
MaskProperty = Literal["mask_x", "mask_y", "mask_width", "mask_height"]
MASK_FIELDS = {
    "mask_x": "center_x",
    "mask_y": "center_y",
    "mask_width": "width",
    "mask_height": "height",
}
MASK_SIZE_FIELDS = {"mask_width", "mask_height"}
Property = EffectProperty | MaskProperty
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
# Two absences, each for the same reason: no keyframes (the only per-frame hook `gblur` offers is
# `enable`, an on/off window, so an animated radius would export as a staircase while the preview
# interpolates smoothly) and no sharpen (`unsharp` convolves a box-window kernel, not a Gaussian of
# the named radius, so one name would be two functions).
BLUR_LIMIT = 0.25
BLUR_RADIUS_LIMIT_PX = 64.0
GBLUR_STEPS = 6
# Sharpen is an unsharp mask, so it carries the two numbers that operation always has: an amount
# (what 剪映 calls the degree, AE and Resolve call Amount) and a radius. The radius uses the same
# unit as soft focus - a fraction of the frame height, capped by the same measured band - because
# a fixed 3x3 Laplacian kernel would look different at 1080p and 4K, and this project's knobs are
# defined against the frame, not a pixel count. Default ~4 px at 1080p: edge, not glow.
SHARPEN_LIMIT = 2.0
SHARPEN_RADIUS_DEFAULT = 0.004
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
    # (export 77/68/57/44, browser 74/65/54/43, plate at 100). Same restrictions as `blur`: no
    # keyframes (there is no per-frame radius to animate), and only inside the measured band.
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


ColorSpace = Literal["linear", "srgb", "gamma18", "gamma20", "gamma22", "gamma24", "rec709"]


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
    enabled: bool = True
    mix: GradeMix = 1.0
    blend: BlendMode = "normal"


class GradeLUT(Contract):
    """An imported 1D lookup table: three per-channel sample lists, one value per input level.

    This is the `.cube` `LUT_1D_SIZE` flavour — the only kind that stays a per-channel function, so
    the whole grade chain still compiles to one table per channel and both renderers keep reading
    the same data. A 3D LUT mixes channels (its output red depends on input green and blue) and is
    refused at parse time with that sentence rather than silently flattened. Grid spacing is the
    importer's `1/(size-1)`; the sampler interpolates linearly between samples, exactly like the
    curve nodes' piecewise sections.
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


# A parallel branch stays per-channel on purpose: the node outputs the mean of its branches, and the
# mean of a cross-channel map with anything else is not something the chain can still compile to a
# table. Refusing it here is what keeps the compiler from ever meeting a matrix inside a branch.
GradeBranch = GradeCurve | GradeWhiteBalance | GradeWheels | GradeLevels | GradeTransfer | GradeLUT

GRADE_NODE_LIMIT = 8
GRADE_BRANCH_LIMIT = 4


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


GradeNode = (
    GradeCurve
    | GradeWhiteBalance
    | GradeWheels
    | GradeLevels
    | GradeMatrix
    | GradeTransfer
    | GradeLUT
    | GradeParallel
)


class ClipColor(Contract):
    exposure: Annotated[float, Field(ge=-2, le=2)] = 0.0
    contrast: Annotated[float, Field(ge=0, le=2)] = 1.0
    saturation: Annotated[float, Field(ge=0, le=2)] = 1.0
    grade: Annotated[list[GradeNode], Field(max_length=GRADE_NODE_LIMIT)] = Field(
        default_factory=list
    )


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
PathVertices = Annotated[list[MaskVertex], Field(min_length=3, max_length=MASK_VERTEX_LIMIT)]


class SpeedPoint(Contract):
    """One node of a speed profile: timeline offset inside the clip and relative percent."""

    at_ticks: Ticks
    percent: Annotated[int, Field(ge=0, le=400)]


SPEED_POINT_LIMIT = 64
SpeedCurve = Annotated[list[SpeedPoint], Field(min_length=2, max_length=SPEED_POINT_LIMIT)]


class ShapeMask(Contract):
    shape: Literal["rectangle", "ellipse", "path"] = "ellipse"
    center_x: Annotated[float, Field(ge=0, le=1)] = 0.5
    center_y: Annotated[float, Field(ge=0, le=1)] = 0.5
    width: Annotated[float, Field(ge=0.01, le=2)] = 0.6
    height: Annotated[float, Field(ge=0.01, le=2)] = 0.6
    feather: Annotated[float, Field(ge=0, le=1)] = 0.0
    inverted: bool = False
    vertices: PathVertices | None = None

    @model_validator(mode="after")
    def path_requires_vertices(self):
        if self.shape == "path" and not self.vertices:
            raise ValueError("a path mask needs at least three vertices")
        if self.shape != "path" and self.vertices:
            raise ValueError("only a path mask can carry vertices")
        if self.vertices is not None:
            seen = {(round(vertex.x, 9), round(vertex.y, 9)) for vertex in self.vertices}
            if len(seen) != len(self.vertices):
                raise ValueError("path vertices must be distinct")
        return self


class Bezier(Contract):
    x1: Annotated[float, Field(ge=0, le=1)] = 1 / 3
    y1: Annotated[float, Field(ge=-4, le=4)] = 0.0
    x2: Annotated[float, Field(ge=0, le=1)] = 2 / 3
    y2: Annotated[float, Field(ge=-4, le=4)] = 1.0


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
    contain — the same reason the grade chain refuses a cross-channel 3D LUT. Defaults reproduce the
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
)


class Transition(Contract):
    from_clip_id: Identifier
    kind: TransitionKind = "dissolve"
    duration_ticks: Duration


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
    speed_percent: Annotated[int, Field(ge=25, le=400)] = 100
    text: TextStyle | None = None
    effects: ClipEffects = Field(default_factory=ClipEffects)
    color: ClipColor = Field(default_factory=ClipColor)
    mask: ShapeMask | None = None
    speed_curve: SpeedCurve | None = None
    stabilization: Stabilization | None = None
    keyframes: Annotated[list[Keyframe], Field(max_length=2000)] = Field(default_factory=list)
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

    def mask_animation_problem(self) -> str | None:
        """Why this clip's mask keyframes cannot be honoured, or None when they can.

        The reducer edits a clip in place, so this is checked once by the timeline validator after
        every mutation rather than by a model validator that an in-place write would bypass.
        """
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


class ClipsGroup(Contract):
    op: Literal["clips.group"]
    clip_ids: Annotated[list[Identifier], Field(min_length=1, max_length=20_000)]
    group_id: Identifier | None


class ClipsLink(Contract):
    op: Literal["clips.link"]
    clip_ids: Annotated[list[Identifier], Field(min_length=1, max_length=20_000)]
    link_id: Identifier | None


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
    speed_percent: Annotated[int, Field(ge=25, le=400)]
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
    op: Literal["clip.fade"]
    clip_id: Identifier
    property: Literal["opacity", "gain"]
    duration_ticks: Duration
    mode: Literal["in", "out", "both"] = "both"


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
        return self


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
    | ClipRoll
    | ClipSplit
    | ClipSlip
    | ClipSlide
    | ClipRemove
    | ClipRippleRemove
    | ClipDetachAudio
    | ClipEffectsSet
    | ClipMaskSet
    | ClipMaskTrack
    | ClipSpeedSet
    | ClipSpeedCurveSet
    | ClipStabilizeRecord
    | ClipColorSet
    | ClipGradeSet
    | ClipTextSet
    | ClipPatch
    | ClipFade
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
    | KeyframesReplace,
    Field(discriminator="op"),
]


class CreateProject(Contract):
    request_id: Identifier
    name: Annotated[str, Field(min_length=1, max_length=256)]
    settings: SequenceSettings = Field(default_factory=SequenceSettings)


class EditBatch(Contract):
    request_id: Identifier
    expected_revision: Revision
    commands: Annotated[list[Command], Field(min_length=1, max_length=100)]
    dry_run: bool = False
    sequence_id: Identifier | None = None


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


class MaskTrackRequest(Contract):
    """Analyse the clip's media and move its box mask along with the picture.

    While the target is hidden the centre is guessed from recent motion for at most
    `max_gap_frames` frames, and every one of those frames is searched again over the whole picture
    when `reacquire` is on, so a subject that comes back somewhere else is found rather than lost.
    """

    request_id: Identifier
    expected_revision: Revision
    # Read the ids below -- and apply the batch -- inside one nested composition.
    sequence_id: Identifier | None = None
    from_ticks: Ticks = 0
    frames: Annotated[int, Field(ge=TRACK_FRAMES_MIN, le=TRACK_FRAMES_MAX)] = 120
    search_radius: Annotated[int, Field(ge=2, le=16)] = 10
    estimate_scale: bool = True
    max_gap_frames: Annotated[int, Field(ge=0, le=TRACK_GAP_MAX)] = TRACK_GAP_DEFAULT
    reacquire: bool = True
    merge: bool = True
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
OUTPUT_CONTAINERS = ("mp4", "mov", "webm", "mp3", "wav", "flac")
# The codecs `render.output_args` knows how to ask for. Anything outside this set is refused rather
# than passed through, which is what keeps the preset table a closed vocabulary of encoder knobs.
# `None` means the deliverable carries no picture at all: the mix is the product.
OUTPUT_CODECS = (None, "libx264", "libx265", "libvpx-vp9", "prores_ks")
OUTPUT_AUDIO_CODECS = ("aac", "libopus", "pcm_s24le", "libmp3lame", "flac")


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
) -> dict:
    """One delivery target: encoder knobs from a closed set, never raw FFmpeg arguments.

    `crf`, `encoder_preset` and `audio_bitrate` are None where the codec has no such knob: ProRes is
    chosen by a profile, VP9 needs an explicit zero video bitrate next to its crf, and PCM is
    lossless so a bitrate would be a lie. `pixel_format` is not cosmetic — it decides the chroma
    subsampling the final graph stage is written to, so a 4:4:10-bit intermediate really does keep
    the colour the composite had.
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
        "scale": scale,
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
        # Audio-only deliverables: `codec=None` means the picture chain is never compiled, so an MP3
        # of a three-minute cut costs the mix, not a full render. The mix is the same authoritative
        # one the video presets use — master gain, ducking envelopes and the limiter included.
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
            "max_curve_points": CURVE_POINT_LIMIT,
            "max_lut_samples": LUT_SAMPLE_LIMIT,
            "levels_black_max": LEVELS_BLACK_MAX,
            "levels_white_min": LEVELS_WHITE_MIN,
            "levels_gamma_min": LEVELS_GAMMA_MIN,
            "levels_gamma_max": LEVELS_GAMMA_MAX,
            "matrix_limit": MATRIX_LIMIT,
        },
        # The transition picker enumerates this list rather than carrying its own copy, so a kind
        # the exporter cannot honour can never appear in the interface.
        "transition_kinds": [dict(item) for item in TRANSITION_KINDS],
        "output_containers": list(OUTPUT_CONTAINERS),
        # The build identity, next to the schema it speaks: an Agent reading this document can tell
        # which engine answered, and the desktop shows it in the title bar.
        "app_version": APP_VERSION,
        "project_schema_version": SCHEMA_VERSION,
        "timebase": TIMEBASE,
        "max_commands_per_batch": 100,
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
            "clip.roll",
            "clip.split",
            "clip.slip",
            "clip.slide",
            "clip.remove",
            "clip.ripple_remove",
            "clip.detach_audio",
            "clip.effects",
            "clip.mask",
            "clip.mask_track",
            "clip.speed",
            "clip.speed_curve",
            "clip.stabilize_record",
            "clip.color",
            "clip.grade",
            "clip.text",
            "clip.patch",
            "clip.fade",
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
            "nested_sequences": True,
            "shape_masks": True,
            "path_masks": True,
            "mask_animation": True,
            "mask_tracking": media_ready,
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
            "speed_change": True,
            "speed_curve": True,
            "color_correction": True,
            "grade_nodes": True,
            "grade_node_mix": True,
            "lut_import": True,
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
            "timeline_marks": True,
            "range_export": True,
            "four_point_editing": True,
            "color_space_transform": True,
            "proxy_playback": media_ready,
            "text_titles": True,
            "srt_captions": True,
            "clip_fades": True,
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
            "denoise_db": DENOISE_LIMIT,
            "auto_grade_samples_max": AUTO_GRADE_SAMPLES_MAX,
            "auto_grade_percentile_max": AUTO_PERCENTILE_MAX,
            "stabilize_max_crop": STABILIZE_MAX_CROP_LIMIT,
            "stabilize_smoothing_frames": STABILIZE_SMOOTHING_FRAMES,
            "track_max_gap_frames": TRACK_GAP_MAX,
            "track_gap_default": TRACK_GAP_DEFAULT,
            "track_min_frames": TRACK_FRAMES_MIN,
            "track_max_frames": TRACK_FRAMES_MAX,
            "sample_rates": [44_100, 48_000, 96_000],
        },
        "render_presets": render_presets(),
    }
