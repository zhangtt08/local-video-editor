"""Pure RenderPlan compiler: project snapshot + preset -> controlled FFmpeg argv.

No I/O here. Paths must already be server-verified (`Asset.verified`). The emitted argv
contains only encoder flags this module owns — never caller-supplied flags or filters.

Two graph shapes exist on purpose. A single visible video track compiles to one concat
cut list (one decode per clip, cheapest and exactly frame-accurate). Anything layered
compiles per track first, then overlays whole-length tracks with a time-window enable, so
no overlay input ever starts late and stalls the graph.
"""

import hashlib
import os
import re
from dataclasses import dataclass, field

from .animation import (
    expression,
    fade_active,
    mask_shape_schedule,
    outline_mask,
    sharpen_schedule,
    sound_enabled,
    spatial_schedule,
)
from .compositing import blend_track
from .contracts import (
    BLUR_RADIUS_LIMIT_PX,
    DENOISE_FLOOR_DB,
    GBLUR_STEPS,
    MASK_FIELDS,
    MASK_SHAPE_SCHEDULE_MAX,
    TEXT_FONTS,
    TIMEBASE,
    EditorError,
    FrameRate,
    Project,
    checked_output_rate,
    checked_timecode,
    render_presets,
    spatial_radius,
)
from .grade import composite_stages, grade_filter
from .masks import (
    alpha_expression,
    feather_sigma,
    mask_png,
    path_bounds,
    raster_size,
    unit_path,
)
from .speed import base_source_ticks, consumed_source_ticks, segments
from .timeline import sequence_view, validate_timeline
from .transitions import curve_expression, envelopes, wipe_expression


def sec(ticks: int) -> str:
    return f"{ticks / TIMEBASE:.6f}"


def ms(ticks: int) -> int:
    return max(0, round(ticks / TIMEBASE * 1000))


FONT_ROOT = "C:\\Windows\\Fonts" if os.name == "nt" else "/usr/share/fonts/truetype/dejavu"
# Off Windows these faces do not exist, and DejaVu is the only thing drawtext can be pointed at. The
# capability table then publishes just that one face, so the interface and an Agent cannot ask for a
# font this machine would silently substitute.
FONT_FALLBACK = "msyh.ttc" if os.name == "nt" else "DejaVuSans.ttf"


def text_font_file(face_id: str) -> str:
    if os.name == "nt":
        return TEXT_FONTS[face_id][0]
    return FONT_FALLBACK


def text_fonts_available() -> list[dict]:
    """The faces installed here, as ``{id, label, family}`` — ``family`` is the CSS name."""
    ready = []
    for face_id, (_file_name, family, label) in TEXT_FONTS.items():
        path = os.path.join(FONT_ROOT, text_font_file(face_id))
        if not os.path.isfile(path):
            continue
        if os.name == "nt":
            entry = {"id": face_id, "label": label, "family": family}
        else:
            entry = {
                "id": face_id,
                "label": "DejaVu Sans（非 Windows 退路）",
                "family": "DejaVu Sans",
            }
        if entry not in ready:
            ready.append(entry)
    return ready


def text_font_path(face_id: str) -> str:
    """The path ``drawtext`` wants: forward slashes, colon escaped. A missing face is refused, not
    swapped.

    The shape matters and is not obvious: `C\\:\\Windows\\Fonts\\simhei.ttf` does not error, it
    quietly falls back to a default face, so two different fonts render byte-identical. Measured
    both ways against the packaged FFmpeg; `tests/textstyle_check.py` keeps the pixel proof.
    """
    path = os.path.join(FONT_ROOT, text_font_file(face_id))
    if not os.path.isfile(path):
        raise EditorError(
            "FONT_UNAVAILABLE",
            f"the text face {face_id!r} is not installed here; pick one of the faces listed by "
            "GET /v1/capabilities under text_fonts",
            503,
            face_id=face_id,
            installed=[entry["id"] for entry in text_fonts_available()],
        )
    return path.replace("\\", "/").replace(":", "\\:")


def _rgb(color: str) -> tuple[int, int, int]:
    values = tuple(int(color[index : index + 2], 16) for index in (1, 3, 5))
    return values  # type: ignore[return-value]


# Windows' `CreateProcess` takes a command line of ~32 KB, and a keyframe-dense clip reaches it on
# its own; below this the graph still goes inline, above it FFmpeg reads the same text from a file.
GRAPH_SCRIPT_LIMIT = 12_000


def picture_size(
    out_w: int, out_h: int, frame_width: int, frame_height: int, fit: str
) -> tuple[int, int]:
    """The box the composition's picture actually occupies inside the delivered frame.

    `contain` keeps the composition's aspect and bars the rest, so the picture can be narrower or
    shorter than the frame; `cover` and `stretch` fill it. Percentages the viewer reads
    against the picture — caption size, its inset, a spatial radius — belong to this box:
    the preview's own box is locked to the composition's aspect.
    """
    if fit != "contain" or frame_width <= 0 or frame_height <= 0:
        return out_w, out_h
    return (
        max(1, min(out_w, round(out_h * frame_width / frame_height))),
        max(1, min(out_h, round(out_w * frame_height / frame_width))),
    )


def picture_height(out_w: int, out_h: int, frame_width: int, frame_height: int, fit: str) -> int:
    """The height the composition's picture actually occupies inside the delivered frame.

    Both spatial knobs are fractions of the picture, and the browser measures exactly
    that: its preview box is locked to the composition's aspect, so `1cqh` there is
    one percent of the picture. `contain` keeps that aspect and bars the rest, so a 16:9
    timeline delivered to a square or vertical frame shows a picture that is *not*
    `out_h` tall — measuring the radius against the frame would blur it harder than the
    preview by exactly the letterboxing factor. `cover` and `stretch`
    fill the frame, so there the two numbers are the same.
    """
    if fit != "contain" or frame_width <= 0:
        return out_h
    return picture_size(out_w, out_h, frame_width, frame_height, fit)[1]


def focus_radius(fraction: float, knob: str, basis: int) -> float:
    """A fraction of the picture's height turned into pixels, inside the band that was measured.

    Both spatial knobs share the ceiling because both go through the same `gblur` sampling; past it
    the export/preview agreement is claimed nowhere, so the exporter refuses by name instead of
    letting FFmpeg quietly clamp the kernel.
    """
    radius = spatial_radius(fraction, basis)
    if radius > BLUR_RADIUS_LIMIT_PX:
        raise EditorError(
            "BLUR_OUT_OF_RANGE",
            f"{knob} {fraction} is a {radius:.0f} px radius on a {basis} px picture, and the "
            f"export/preview radius match is only verified to {BLUR_RADIUS_LIMIT_PX:.0f} px; the "
            f"most this picture carries is {BLUR_RADIUS_LIMIT_PX / basis:.4f}",
            422,
            **{
                knob: fraction,
                "radius": radius,
                "max_radius_fraction": BLUR_RADIUS_LIMIT_PX / basis,
            },
        )
    return radius


def focus_stages(
    plan, head: str, clip, basis: int, *, frame_ticks: int, alpha: bool = False
) -> str:
    """The layer's soft focus and unsharp mask, applied once the picture sits at output size.

    Returns the chain text, still hanging so the caller continues it with a comma. Both stages run
    before the mask's alpha, which is also how the preview stacks them (CSS `filter` first, then
    `mask-image`), so a blurred-and-clipped shape hides what is behind it the same way on both ends;
    and the alpha arriving here is uniform, which is why `planes=7` and `c3_expr='A'` keep the
    effect off it. Blur is a linear suffix; unsharp needs the original and the blurred copy side by
    side, so it fans out and rejoins. The `clip()` in the blend expression is load-bearing:
    measured, `blend` without it wraps modulo 256 rather than clamping (255 + 0.8·69 came back
    as 54). The blend's output stays unlabeled on purpose: lavfi calls a pad label followed by
    another filter "trailing garbage after a filter", so a closed pad can only end a chain, and
    every caller here has more filters to append. Since 1.123 an animated unsharp mask chains one
    of those fan-out pairs per window (`animation.sharpen_schedule`) — the same staircase soft focus
    has used since 1.98, because `blend` honours `enable` just as `gblur` does.
    """
    schedule = spatial_schedule(clip, "blur", frame_ticks)
    steps = [window for window in sharpen_schedule(clip, frame_ticks) if window["value"][0] > 0]
    if schedule or clip.effects.blur > 0 or clip.effects.sharpen > 0 or steps:
        if alpha:
            # `gblur` samples planes, so the cut chain only asks for the rgba form when a spatial
            # knob is actually on: with both at zero the emitted string stays what it always was,
            # which is what the sampling-format acceptance (`tests/format_check.py`) pins.
            head = f"{head},format=rgba"
    if schedule:
        # 1.98: a keyframed radius compiles to the same windows the browser animates. Each one is an
        # on/off `enable` window because `gblur` cannot read an expression for its sigma — which is
        # precisely why this knob had no keyframes before, when the staircase was only half-present.
        for window in schedule:
            if window["value"] <= 0:
                continue
            radius = focus_radius(window["value"], "blur", basis)
            start = sec(window["from_ticks"])
            stop = sec(window["to_ticks"])
            head = (
                f"{head},gblur=sigma={radius:.4f}:steps={GBLUR_STEPS}"
                f":enable='between(t,{start},{stop})'"
            )
    elif clip.effects.blur > 0:
        radius = focus_radius(clip.effects.blur, "blur", basis)
        head = f"{head},gblur=sigma={radius:.4f}:steps={GBLUR_STEPS}"
    if steps:
        # 1.123: a keyframed unsharp mask compiles to the window list the browser animates, one
        # `gblur` + `blend` pair per step and a single `split` fanning the whole chain. Both stages
        # carry the same `enable` gate because both are measured to honour it: a disabled `blend`
        # hands back its first input untouched, so the picture entering window k's blend is still
        # the original however many windows sit in front of it, and a disabled `gblur` keeps the
        # expensive convolution off frames this window does not own. A window whose amount is 0
        # gets no stage at all — same deal the soft-focus staircase makes.
        def gate(window: dict) -> str:
            return f":enable='between(t,{sec(window['from_ticks'])},{sec(window['to_ticks'])})'"

        chain = plan.tag("sharp")
        sources = [plan.tag("toblu") for _ in steps]
        hazy = [plan.tag("blurd") for _ in steps]
        joined = [plan.tag("sharw") for _ in steps[:-1]]
        plan.filters.append(f"{head},split={len(steps) + 1}{chain}{''.join(sources)}")
        for window, source, out in zip(steps, sources, hazy, strict=True):
            sigma = focus_radius(window["value"][1], "sharpen_radius", basis)
            plan.filters.append(
                f"{source}gblur=sigma={sigma:.4f}:steps={GBLUR_STEPS}:planes=7{gate(window)}{out}"
            )
        for index, (window, out) in enumerate(zip(steps, hazy, strict=True)):
            expression = f"clip(A+{window['value'][0]}*(A-B),0,255)"
            blend = (
                f"{chain}{out}blend="
                + ":".join(f"c{plane}_expr='{expression}'" for plane in (0, 1, 2))
                + f":c3_expr='A'{gate(window)}"
            )
            if index == len(steps) - 1:
                head = blend
            else:
                plan.filters.append(f"{blend}{joined[index]}")
                chain = joined[index]
    elif clip.effects.sharpen > 0:
        amount = clip.effects.sharpen
        sigma = focus_radius(clip.effects.sharpen_radius, "sharpen_radius", basis)
        original, to_blur, blurred = plan.tag("sharp"), plan.tag("toblu"), plan.tag("blurd")
        expression = f"clip(A+{amount}*(A-B),0,255)"
        plan.filters.append(f"{head},split=2{original}{to_blur}")
        plan.filters.append(
            f"{to_blur}gblur=sigma={sigma:.4f}:steps={GBLUR_STEPS}:planes=7{blurred}"
        )
        head = (
            f"{original}{blurred}blend="
            + ":".join(f"c{plane}_expr='{expression}'" for plane in (0, 1, 2))
            + ":c3_expr='A'"
        )
    return head


def color_filter(clip, plan=None) -> str:
    color = clip.color
    grade = grade_filter(color, plan)
    if color.exposure == 0 and color.contrast == 1 and color.saturation == 1:
        return f"format=rgba,{grade}," if grade else ""
    tonal = f"clip((clip(val*{2**color.exposure},0,255)-127.5)*{color.contrast}+127.5,0,255)"
    s = color.saturation
    # CSS saturate's sRGB matrix, shared with the native browser filter plan.
    matrix = [
        0.213 + 0.787 * s,
        0.715 - 0.715 * s,
        0.072 - 0.072 * s,
        0.213 - 0.213 * s,
        0.715 + 0.285 * s,
        0.072 - 0.072 * s,
        0.213 - 0.213 * s,
        0.715 - 0.715 * s,
        0.072 + 0.928 * s,
    ]
    channels = ("rr", "rg", "rb", "gr", "gg", "gb", "br", "bg", "bb")
    return (
        f"format=rgba,lutrgb=r='{tonal}':g='{tonal}':b='{tonal}',colorchannelmixer="
        + ":".join(f"{name}={value}" for name, value in zip(channels, matrix))
        + (f",{grade}" if grade else "")
        + ","
    )


def clip_ramp(clip, settings, quantum: int | None = None) -> list[dict] | None:
    """Constant-rate pieces for a curved clip, or None when it keeps its base speed."""
    if not clip.speed_curve:
        return None
    return segments(clip, quantum or settings.frame_ticks, settings.frame_ticks)


def source_window(clip, settings, quantum: int) -> int:
    """How much source a clip reads: the whole curve, or the constant-speed span.

    A curved clip's picture and sound align to different clocks, so the input has to cover the
    wider of the two; the shorter stream would otherwise hit EOF inside its last piece.
    """
    if not clip.speed_curve:
        return base_source_ticks(clip)
    sample = settings.timebase // settings.sample_rate
    return max(consumed_source_ticks(clip, quantum), consumed_source_ticks(clip, sample))


def _tempos(rate_percent: int) -> list[str]:
    tempo = max(rate_percent, 1) / 100
    chain: list[str] = []
    while tempo < 0.5:
        chain.append("atempo=0.5")
        tempo /= 0.5
    while tempo > 2:
        chain.append("atempo=2")
        tempo /= 2
    chain.append(f"atempo={tempo:.6f}")
    return chain


def ramp_video(plan: "RenderPlan", source: str, ramp: list[dict], fps: str, frame: float) -> str:
    """One decoded stream split into constant-rate pieces, concatenated back to the clip length."""
    ins = [plan.tag("rvin") for _ in ramp]
    plan.filters.append(f"{source}split={len(ramp)}{''.join(ins)}")
    outs = []
    offset = 0.0
    for piece, label_in in zip(ramp, ins):
        label_out = plan.tag("rvseg")
        timeline = sec(piece["timeline"])
        span = piece["source"] / TIMEBASE
        start = f"{offset:.9f}"
        if piece["source"] <= 0:
            hold = piece.get("hold", round(offset * TIMEBASE)) / TIMEBASE
            plan.filters.append(
                f"{label_in}trim=start={hold:.9f}:end={hold + frame:.9f},"
                f"setpts=PTS-STARTPTS,fps={fps},"
                f"tpad=stop_mode=clone:stop_duration={timeline},"
                f"trim=duration={timeline},setpts=PTS-STARTPTS{label_out}"
            )
        else:
            stretch = piece["timeline"] / piece["source"]
            plan.filters.append(
                f"{label_in}trim=start={start}:end={offset + span:.9f},"
                f"setpts=(PTS-STARTPTS)*{stretch:.9f},fps={fps},setpts=PTS-STARTPTS{label_out}"
            )
        outs.append(label_out)
        offset += span
    out = plan.tag("ramped")
    plan.filters.append("".join(outs) + f"concat=n={len(outs)}:v=1:a=0{out}")
    return out


def ramp_audio(plan: "RenderPlan", source: str, ramp: list[dict], sample_rate: int) -> str:
    """Audio counterpart: tempo per piece, silence where the picture freezes."""
    ins = [plan.tag("rain") for _ in ramp]
    plan.filters.append(f"{source}asplit={len(ramp)}{''.join(ins)}")
    outs = []
    offset = 0.0
    for piece, label_in in zip(ramp, ins):
        label_out = plan.tag("raseg")
        timeline = sec(piece["timeline"])
        span = piece["source"] / TIMEBASE
        start = f"{offset:.9f}"
        if piece["source"] <= 0:
            hold = piece.get("hold", round(offset * TIMEBASE)) / TIMEBASE
            plan.filters.append(
                f"{label_in}atrim=start={hold:.9f}:end={hold + 1 / sample_rate:.9f},"
                f"asetpts=PTS-STARTPTS,apad=whole_dur={timeline},"
                f"atrim=duration={timeline},asetpts=PTS-STARTPTS{label_out}"
            )
        else:
            plan.filters.append(
                f"{label_in}atrim=start={start}:end={offset + span:.9f},"
                f"asetpts=PTS-STARTPTS,{','.join(_tempos(piece['rate_percent']))},"
                f"asetpts=PTS-STARTPTS{label_out}"
            )
        outs.append(label_out)
        offset += span
    out = plan.tag("rampeda")
    plan.filters.append("".join(outs) + f"concat=n={len(outs)}:v=0:a=1{out}")
    return out


def preset_by_id(preset_id: str) -> dict:
    for preset in render_presets():
        if preset["id"] == preset_id:
            return preset
    raise EditorError("UNKNOWN_PRESET", "unknown render preset", 422, preset_id=preset_id)


def output_args(
    preset: dict,
    sample_rate: int,
    frame_rate: float,
    *,
    transparent: bool = False,
    timecode: str | None = None,
    delivery_rate=None,
) -> list[str]:
    """Encode and mux arguments for one preset, switched by the codec the preset names.

    The vocabulary is closed here, not in the caller: a preset may only name a codec this function
    knows, so a render request steers FFmpeg with an id and nothing else. Each branch is what that
    encoder actually accepts rather than one template forced on all of them — VP9 takes no
    `-preset` and wants `-b:v 0` beside its crf, ProRes takes neither and is chosen by a profile,
    PCM has no bitrate, and `-movflags` belongs to the mp4/mov muxer only.
    `transparent` is answered here rather than ignored: an encoder whose pixel format has no
    alpha plane cannot carry a matte no matter what the graph above it produced, so the request
    that would silently export an opaque file is refused and pointed at the presets that can.
    `timecode` is the start timecode for the handoff; the string itself is validated by
    `contracts.checked_timecode` (FFmpeg silently rewrites several invalid forms), and it is
    refused here for a deliverable that has no picture to count frames of.
    """
    if transparent and not preset["alpha"]:
        exits = "、".join(str(item["id"]) for item in render_presets() if item["alpha"])
        raise EditorError(
            "TRANSPARENT_NEEDS_ALPHA",
            f"{preset['label']} 这一条写不下透明度（画面格式 "
            f"{preset['pixel_format'] or '没有画面轨'}）；透明背景只有 {exits} 可以，"
            "换成其中一条再导出，或者把「透明背景」去掉",
            422,
            preset_id=preset["id"],
        )
    if preset["sequence"]:
        # 一串图像文件没有容器：起始时间码无处可挂，帧号本身就是位置。收下之后再什么都不做
        # 就是说谎，所以这里点名拒，并指出哪几条带得走时间码。
        if timecode:
            raise EditorError(
                "SEQUENCE_NEEDS_CONTAINER",
                f"{preset['label']} 交出的是一串图像文件，没有容器可以挂起始时间码——"
                "EXR／DPX 的帧号就是位置。要时间码请换成 mov／mp4／mxf／webm 那几条",
                422,
                preset_id=preset["id"],
            )
        # 也没有地方放声音：`-an` 与 ffmpeg_argv 里那条 `-map` 一并免了。
        return ["-c:v", str(preset["codec"]), "-pix_fmt", str(preset["pixel_format"]), "-an"]
    codec = preset["codec"]
    if delivery_rate is not None and codec is None:
        # 和人给一条纯音频交付写时间码同一个道理：帧率是「一秒几帧」，没有画面就没有帧可数。
        raise EditorError(
            "OUTPUT_RATE_NEEDS_PICTURE",
            f"{preset['label']} 这一条只有声音，没有画面可以数帧；「交付帧率」是给画面的，"
            "换成带画面的预设再选，或者把那一栏留空",
            422,
            preset_id=preset["id"],
        )
    video: list[str] = []
    if codec is None:
        # An audio-only deliverable: `-vn` is belt-and-braces next to not mapping a picture at all,
        # because the mp3/wav/flac muxers would refuse a video stream anyway.
        video = ["-vn"]
    else:
        video = ["-c:v", codec]
        if codec in ("libx264", "libx265"):
            video += ["-preset", str(preset["encoder_preset"]), "-crf", str(preset["crf"])]
            if codec == "libx265":
                # hvc1, not hev1: the parameter sets go into the sample description, so QuickTime
                # and editors can play the file, not only FFmpeg reading it back.
                video += ["-tag:v", "hvc1"]
        elif codec == "libvpx-vp9":
            video += [
                "-b:v",
                "0",
                "-crf",
                str(preset["crf"]),
                "-deadline",
                "good",
                "-cpu-used",
                "4",
                "-row-mt",
                "1",
            ]
        elif codec == "prores_ks":
            video += ["-profile:v", str(preset["profile"])]
        elif codec == "mpeg2video":
            # MPEG-2 has no crf: the quality knob is the quantiser (-q:v), 1 best, 31 worst.
            video += ["-q:v", str(preset["quality"])]
        else:
            raise EditorError(
                "UNKNOWN_PRESET", f"this build cannot encode {codec}", 422, preset_id=preset["id"]
            )
        # GOP sizing stays the same on every codec: the checks read frames at arbitrary
        # times, and a keyframe every two seconds is what makes that cheap.
        video += [
            "-pix_fmt",
            preset["pixel_format"],
            "-keyint_min",
            str(max(1, round(frame_rate))),
            "-g",
            str(max(2, round(frame_rate) * 2)),
        ]
    audio = ["-c:a", preset["audio_codec"]]
    if preset["audio_bitrate"]:
        audio += ["-b:a", preset["audio_bitrate"]]
    audio += ["-ar", str(sample_rate), "-ac", "2"]
    if preset["container"] == "mxf" and sample_rate != 48_000:
        raise EditorError(
            "MXF_NEEDS_48K",
            f"MXF 只能写 48 kHz 的音频轨（FFmpeg 在这一条上直接拒写文件头），当前混音是"
            f" {sample_rate} Hz；把工程的采样率改成 48000 再交付，或者改用 mp4/mov 预设",
            422,
            preset_id=preset["id"],
        )
    if timecode and codec is None:
        raise EditorError(
            "TIMECODE_NEEDS_PICTURE",
            f"{preset['label']} 这一条根本没有画面，时间码是给画面数帧的，写上去只会骗人；"
            "要时间码请选一条带画面的交付",
            422,
            preset_id=preset["id"],
        )
    mux = ["-movflags", "+faststart"] if preset["container"] in ("mp4", "mov") else []
    if timecode:
        # 起始时间码存哪儿是各容器自己的事：实测 mov/mp4 写在**流**这一层的 `timecode`，
        # mxf 写在容器层的 `timecode`，webm 写成大写的 `TIMECODE`。复检按这些位置读回来。
        mux += ["-timecode", timecode]

    return [*video, *audio, *mux]


@dataclass
class RenderPlan:
    input_args: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    video_label: str = "[vout]"
    audio_label: str = "[aout]"
    duration_ticks: int = 0
    mode: str = "cut"
    output_args: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    has_audio: bool = True
    counter: int = 0
    text_files: dict[str, str] = field(default_factory=dict)
    graph_in_file: bool = False
    frame_graph_in_file: bool = False
    binary_files: dict[str, bytes] = field(default_factory=dict)

    def tag(self, prefix: str) -> str:
        self.counter += 1
        return f"[{prefix}{self.counter}]"

    def next_input(self) -> int:
        return self.input_args.count("-i")

    def add_lavfi(self, graph: str, duration_ticks: int) -> int:
        index = self.next_input()
        self.input_args += ["-f", "lavfi", "-t", sec(duration_ticks), "-i", graph]
        return index

    def add_still(self, name: str, duration_ticks: int, frame_rate: str) -> int:
        """A looped image from the job directory, used for rasterised path masks."""
        index = self.next_input()
        self.input_args += [
            "-f",
            "image2",
            "-loop",
            "1",
            "-framerate",
            frame_rate,
            "-t",
            sec(duration_ticks),
            "-i",
            name,
        ]
        return index

    def graph_argument(self, graph: str, *, frame: bool = False) -> list[str]:
        """The filtergraph as an argument, or as a script file when it outgrew the command line.

        Windows refuses `CreateProcess` past ~32 KB, and a stabilised clip reaches that on its own:
        one keyframe per frame turns into a chain of `if(lt(t,...))` per overlay. Which form a plan
        uses is decided at compile time (see `GRAPH_SCRIPT_LIMIT`), so a caller that writes
        `text_files` before building the command still gets every file it needs.
        """
        if not (self.frame_graph_in_file if frame else self.graph_in_file):
            return ["-filter_complex", graph]
        return ["-filter_complex_script", "filtergraph-frame.txt" if frame else "filtergraph.txt"]

    def render_graph_text(self) -> str:
        """整条渲染用的图。

        序列不 map 声音，那条 `[aout]` 就得自己落地：悬着的输出 pad 会让 FFmpeg 在 `anull` 上
        报「unconnected output」，整条渲染直接失败（实测退出码 4294967274）。
        """
        tail = [] if self.has_audio else [f"{self.audio_label}anullsink"]
        return ";".join([*self.filters, *tail])

    def frame_graph_text(self) -> str:
        """取单帧的图：画面只要一帧，声音无论如何都落地。"""
        return ";".join([*self.filters, f"{self.audio_label}anullsink"])

    def ffmpeg_argv(self, ffmpeg: str, output_path: str) -> list[str]:
        return [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-progress",
            "pipe:1",
            "-y",
            *self.input_args,
            *self.graph_argument(self.render_graph_text()),
            *(["-map", self.video_label] if self.video_label else []),
            # 图像序列连 `-map` 都不发：那一串文件里根本没有地方放声音（起始时间码由
            # output_args 点名拒，这里负责声音）。
            *(["-map", self.audio_label] if self.has_audio else []),
            "-t",
            sec(self.duration_ticks),
            *self.output_args,
            output_path,
        ]

    def frame_argv(self, ffmpeg: str, at_ticks: int) -> list[str]:
        return [
            ffmpeg,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            *self.input_args,
            *self.graph_argument(self.frame_graph_text(), frame=True),
            "-map",
            self.video_label,
            "-ss",
            sec(at_ticks),
            "-frames:v",
            "1",
            "-an",
            "-c:v",
            "png",
            "-threads",
            "1",
            "-f",
            "image2pipe",
            "pipe:1",
        ]

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "duration_ticks": self.duration_ticks,
            "duration_seconds": round(self.duration_ticks / TIMEBASE, 3),
            "inputs": self.input_args.count("-i"),
            "filter_nodes": len(self.filters),
            "encoder": self.summary.get("encoder"),
            "resolution": self.summary.get("resolution"),
            "frame_rate": self.summary.get("frame_rate"),
            "segments": self.summary.get("segments"),
            "range": self.summary.get("range"),
            "layers": self.summary.get("layers"),
            "audio_layers": self.summary.get("audio_layers"),
            "sources": self.summary.get("sources"),
            # The matte belongs in the dry-run document: a person or an Agent reading a plan has to
            # be able to tell "this file will hold a matte" from the plan itself, not only from the
            # flag they sent in.
            "transparent": self.summary.get("transparent"),
            "timecode": self.summary.get("timecode"),
            "project_frame_rate": self.summary.get("project_frame_rate"),
            "sequence": self.summary.get("sequence"),
            "audio": self.summary.get("audio"),
        }


def path_patch(
    plan: "RenderPlan",
    shape,
    anchor,
    plane_w: int,
    plane_h: int,
    bar_x: float,
    bar_y: float,
    total: int,
    fps: str,
) -> dict:
    """The one geometry a free-form mask's plate is cut and placed with.

    A path mask's alpha cannot be an expression the way a box's is, so each outline becomes one
    tight grayscale plate that `overlay` moves: the feather is baked into a padded patch (the ramp
    has to survive past the shape's own bounds), and `anchor` — the mask's stored box centre — is
    the point the `mask_x`/`mask_y` expressions offset from. A morph calls this once per window, so
    the exporter has exactly one rule for where an outline lands, whatever that outline is.
    """
    left, top, right, bottom = path_bounds(shape)
    box_w = max(2, int(round(plane_w * (right - left))))
    box_h = max(2, int(round(plane_h * (bottom - top))))
    # A feather spreads the ramp past the outline and the patch is only as big as the outline, so
    # the ramp is baked into a padded plate instead of being cut off at the shape's own bounds.
    sigma = feather_sigma(box_w, box_h, shape.feather)
    pad = int(3 * sigma) + 2
    patch_w, patch_h = box_w + 2 * pad, box_h + 2 * pad
    # `feather_sigma` measures the short edge, so the inset is corrected by the short edge's own
    # ratio — otherwise a wide patch would blur the ramp too far.
    shrink = min(box_w, box_h) / min(patch_w, patch_h)
    png = mask_png(
        unit_path(
            shape.model_copy(update={"feather": shape.feather * shrink}),
            box_w / patch_w,
            box_h / patch_h,
        ),
        patch_w,
        patch_h,
    )
    name = "mask-" + hashlib.sha256(png).hexdigest()[:24] + ".png"
    plan.binary_files[name] = png
    return {
        "source": plan.add_still(name, total, str(fps)),
        "patch_w": patch_w,
        "patch_h": patch_h,
        "anchor_x": plane_w * ((left + right) / 2 - anchor.center_x) - patch_w / 2 + bar_x,
        "anchor_y": plane_h * ((top + bottom) / 2 - anchor.center_y) - patch_h / 2 + bar_y,
    }


def _entries_for_track(project: Project, track) -> list[dict]:
    clips = sorted(
        (clip for clip in project.clips.values() if clip.track_id == track.id),
        key=lambda clip: (clip.position_ticks, clip.id),
    )
    entries = []
    for clip in clips:
        asset = project.assets.get(clip.asset_id)
        if asset is None:
            raise EditorError(
                "MISSING_REFERENCE", "clip points at a missing asset", 404, clip_id=clip.id
            )
        verified = asset.verified
        if verified is None and asset.kind not in {"text", "sequence"}:
            raise EditorError(
                "UNVERIFIED_ASSET",
                "render needs imported media: POST /v1/media/import then an asset.import command",
                422,
                asset_id=asset.id,
                label=asset.label,
            )
        entries.append({"clip": clip, "asset": asset, "verified": verified, "track": track})
    return entries


def compile_render_plan(
    project: Project,
    preset_id: str,
    *,
    preview_size: tuple[int, int] | None = None,
    sequence_id: str | None = None,
    fit: str = "contain",
    range_ticks: tuple[int, int] | None = None,
    transparent: bool = False,
    timecode: str | None = None,
    output_frame_rate: FrameRate | None = None,
    _transparent: bool = False,
    _duration_ticks: int | None = None,
) -> RenderPlan:
    if not _transparent:
        validate_timeline(project)
    # 画面什么时候必须带着 alpha 走完：有人明确要透明母版，或者这是嵌套合成（父级要拿它去合成）。
    # 两者在这一个名字下合流，图上就不存在「按不透明算的那半条链」。
    alpha_out = transparent or _transparent
    if sequence_id is not None:
        _duration_ticks = (
            project.sequences[sequence_id].duration_ticks
            if sequence_id in project.sequences
            else None
        )
        project = sequence_view(project, sequence_id)
    preset = preset_by_id(preset_id)
    settings = project.settings
    # 1.138：交付率可以不同于时间线自己的率，先把它判过——时间码要用**这条交付的**帧率判，
    # 不是用时间线的。实测（30 的线标 `00:00:00:29` 按 25 交）：按时间线判会收下，而 muxer
    # 按 25 把那一串改写成 `00:00:01:04` 落盘——1.137 立这条规矩就是为了不让文件替人改数字。
    delivery_rate = checked_output_rate(output_frame_rate)
    # 时间码在这里过一次规矩，干跑、排队与 worker 走的是同一条路。
    timecode = checked_timecode(timecode, delivery_rate or settings.frame_rate)
    out_w, out_h = preview_size or preset["scale"] or (settings.width, settings.height)
    # 两个空间旋钮量的是「画面」的高：预览那个框锁工程比例，成片里画面占多高由 fit 决定。
    picture_w, picture_h = picture_size(out_w, out_h, settings.width, settings.height, fit)
    focus_basis = picture_h
    # 遮罩的坐标与羽化量的都是「画面」；补边交付时帧与画面不是一回事。
    bar_x, bar_y = (out_w - picture_w) / 2, (out_h - picture_h) / 2
    letterbox = (picture_w, picture_h) != (out_w, out_h)
    mask_box = (bar_x, bar_y, picture_w, picture_h) if letterbox else None
    # 交付帧率可以不同于时间线自己的率：`fps=` 那一级负责重采样，GOP 的秒数按交付率算，
    # 而片段位置、区间与遮罩仍按时间线的 tick 走——两套刻度各管各的，才有「同一条时间线交两版」。
    delivery = delivery_rate or settings.frame_rate
    fps = f"{delivery.numerator}/{delivery.denominator}"
    rate = delivery.numerator / delivery.denominator
    size = f"{out_w}x{out_h}"
    # The preset's sampling format runs through the whole picture chain, not just the encoder flag:
    # a 4:4:10-bit intermediate has to keep 4:4:4 from the decode and the framing stages too, or the
    # chroma is thrown away upstream and the wrapper only looks deep. Every H.264/HEVC/VP9 preset
    # says yuv420p, so the graphs those presets compile are unchanged.
    pixel_format = preset["pixel_format"] or "yuv420p"
    # `codec=None` is the audio-only case: no picture is compiled at all, so an MP3 of a long cut
    # costs the mix rather than a full render. The format above is then simply unused.
    audio_only = preset["codec"] is None

    video_tracks = [track for track in project.tracks if track.kind == "video" and not track.hidden]
    audio_tracks = [track for track in project.tracks if track.kind == "audio" and not track.muted]

    layers: list[list[dict]] = []
    visible: list[tuple[object, list[dict]]] = []
    for track in video_tracks:
        entries = _entries_for_track(project, track)
        if entries:
            layers.append(entries)
            visible.append((track, entries))
    if not layers and _duration_ticks is None and not audio_only:
        raise EditorError("EMPTY_TIMELINE", "a render needs visible video or image clips", 422)

    sounds: list[dict] = []
    for track, entries in visible:
        if track.muted:
            continue
        sounds.extend(
            entry
            for entry in entries
            if (
                entry["asset"].kind == "sequence"
                or entry["verified"]
                and entry["verified"].has_audio
            )
            and sound_enabled(entry["clip"], track)
        )
    for track in audio_tracks:
        sounds.extend(
            entry
            for entry in _entries_for_track(project, track)
            if entry["verified"] and entry["verified"].kind != "image"
        )
    sounds.sort(key=lambda item: (item["clip"].position_ticks, item["clip"].id))
    if audio_only and not sounds:
        raise EditorError(
            "EMPTY_TIMELINE",
            "an audio deliverable needs audible material: a sounding clip or a sound track",
            422,
        )

    total = _duration_ticks or 0
    for entries in layers:
        total = max(
            total,
            *[entry["clip"].position_ticks + entry["clip"].duration_ticks for entry in entries],
        )
    for entry in sounds:
        total = max(total, entry["clip"].position_ticks + entry["clip"].duration_ticks)

    compositing = (
        alpha_out
        or not layers
        or len(layers) > 1
        or any(track.blend_mode != "normal" for track, _ in visible)
        or any(
            entry["asset"].kind in {"text", "sequence"}
            or entry["clip"].mask
            or entry["clip"].transition_in
            or fade_active(entry["clip"], "opacity")
            or any(k.property != "gain" for k in entry["clip"].keyframes)
            or any(
                getattr(entry["clip"].effects, name) != default
                for name, default in (
                    ("x", 0),
                    ("y", 0),
                    ("scale", 1),
                    ("rotation", 0),
                    ("opacity", 1),
                )
            )
            for entries in layers
            for entry in entries
        )
    )
    plan = RenderPlan(
        mode="audio" if audio_only else "layered" if compositing else "cut",
        # 序列那一串文件里没有声音的位置，所以连那条 `-map` 都不该发出去（ffmpeg_argv 读这个）。
        has_audio=not preset["sequence"],
    )
    transition_curves = envelopes(project)
    # Three framings, because a 16:9 timeline is delivered to 9:16 more often than not:
    # `contain` keeps every pixel and bars the rest, `cover` fills the frame and crops the
    # overflow, `stretch` fills the frame by distorting it. Only `contain` pads, so only
    # `contain` can leave black bands the exporter must not silently invent.
    if fit == "cover":
        sizing = (
            f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase:flags=bicubic,"
            f"crop={out_w}:{out_h},"
        )
    elif fit == "stretch":
        sizing = f"scale={out_w}:{out_h}:flags=bicubic,"
    else:
        sizing = (
            f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease:flags=bicubic,"
            f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color=black,"
        )
    fit_pre = f"{sizing}setsar=1,fps={fps}"
    fit_post = f"format={pixel_format},settb=AVTB"

    nested_sources = set()

    def clip_input(entry: dict) -> int | None:
        if "input" in entry:
            return entry["input"]
        clip, verified = entry["clip"], entry["verified"]
        if entry["asset"].kind == "sequence":
            sequence = project.sequences[entry["asset"].sequence_id]
            child = compile_render_plan(
                sequence_view(project, sequence.id),
                preset_id,
                preview_size=(out_w, out_h),
                _transparent=True,
                _duration_ticks=sequence.duration_ticks,
            )
            offset = plan.next_input()
            prefix = plan.tag("nest")[1:-1]

            def remap(match):
                label = match.group(1)
                if re.fullmatch(r"\d+:[va]", label):
                    number, stream = label.split(":")
                    return f"[{int(number) + offset}:{stream}]"
                return f"[{prefix}_{label}]"

            def renamed(value):
                return re.sub(r"\[([A-Za-z0-9_]+|\d+:[va])\]", remap, value)

            plan.input_args.extend(child.input_args)
            plan.filters.extend(renamed(f) for f in child.filters)
            plan.text_files.update(
                # The child's own filtergraph is inlined into the parent's, so its script file (if
                # it had one) is both unreferenced and name-colliding here.
                {
                    name: body
                    for name, body in child.text_files.items()
                    if not name.startswith("filtergraph")
                }
            )
            plan.binary_files.update(child.binary_files)
            nested_sources.update(child.summary["sources"])
            video, audio = plan.tag("nestedv"), plan.tag("nesteda")
            duration = sec(base_source_ticks(clip))
            start = sec(clip.source_in_ticks)
            plan.filters.append(
                f"{renamed(child.video_label)}trim=start={start}:duration={duration},setpts=PTS-STARTPTS{video}"
            )
            if entry in sounds:
                plan.filters.append(
                    f"{renamed(child.audio_label)}atrim=start={start}:duration={duration},asetpts=PTS-STARTPTS{audio}"
                )
            else:
                plan.filters.append(f"{renamed(child.audio_label)}anullsink")
            entry.update(input=None, video=video, audio=audio)
            return None
        if entry["asset"].kind == "text":
            index = plan.add_lavfi(
                f"color=c=black@0:s={size}:r={fps},format=rgba", clip.duration_ticks
            )
            entry["input"] = index
            return index
        index = plan.next_input()
        quantum = (
            settings.frame_ticks
            if entry["track"].kind == "video"
            else settings.timebase // settings.sample_rate
        )
        if verified.kind == "image":
            plan.input_args += [
                "-loop",
                "1",
                "-framerate",
                fps,
                "-t",
                sec(clip.duration_ticks),
                "-i",
                verified.path,
            ]
        else:
            plan.input_args += [
                "-ss",
                sec(clip.source_in_ticks),
                "-t",
                sec(source_window(clip, settings, quantum)),
                "-i",
                verified.path,
            ]
        entry["input"] = index
        return index

    def blank_label(duration_ticks: int) -> str:
        index = plan.add_lavfi(
            f"color=c={'black@0' if alpha_out else 'black'}:s={size}:r={fps},format=rgba",
            duration_ticks,
        )
        label = plan.tag("blank")
        plan.filters.append(
            f"[{index}:v]fps={fps},format={'rgba' if alpha_out else pixel_format},"
            f"setsar=1,settb=AVTB{label}"
        )
        return label

    def track_chain(entries: list[dict]) -> tuple[str, list[tuple[int, int]], int]:
        """Concat one track's clips, filling gaps with black, over the whole timeline."""
        labels: list[str] = []
        windows: list[tuple[int, int]] = []
        cursor = 0
        for entry in entries:
            clip = entry["clip"]
            if clip.position_ticks > cursor:
                labels.append(blank_label(clip.position_ticks - cursor))
            index = clip_input(entry)
            label = plan.tag("v")
            source = f"[{index}:v]"
            color = color_filter(clip, plan)
            # The `cut` chain is a second builder for the picture, and it is where a per-clip
            # filter gets forgotten: the preview filters every layer, so this path runs the same
            # spatial stages in the same place (after the fit to output size, before the target
            # pixel format). With both knobs at zero the emitted string is what it always was.
            ramp = clip_ramp(clip, settings)
            if entry["verified"].kind != "image" and not ramp:
                paced = f"setpts=(PTS-STARTPTS)/{clip.speed_percent / 100},"
            elif entry["verified"].kind != "image":
                source = ramp_video(plan, source, ramp, fps, settings.frame_ticks / TIMEBASE)
                paced = ""
            else:
                paced = ""
            trim_tail = (
                ""
                if entry["verified"].kind == "image"
                else f",trim=duration={sec(clip.duration_ticks)},setpts=PTS-STARTPTS"
            )
            composites = composite_stages(clip.color)
            if composites:
                # 第二路画面：这条链的输出要与**进来的那幅画**相合，所以图在这里劈成三路——
                # 一路走完整的调色与适配，两路原图只做同样的适配（`blend` 要两幅一样大、一样时基）。
                work = plan.tag("gwork")
                raws = [plan.tag("gsrc") for _ in range(2)]
                sized = [plan.tag("gsized") for _ in raws]
                plan.filters.append(f"{source}{paced}split={len(raws) + 1}{work}" + "".join(raws))
                for pad, sized_pad in zip(raws, sized):
                    plan.filters.append(f"{pad}{fit_pre},{fit_post}{sized_pad}")
                graded = plan.tag("gout")
                chain = focus_stages(
                    plan,
                    f"{work}{color}{fit_pre}",
                    clip,
                    focus_basis,
                    frame_ticks=settings.frame_ticks,
                    alpha=True,
                )
                plan.filters.append(f"{chain},{fit_post}{trim_tail}{graded}")
                stage = composites[0]
                # 相合必须在 RGB 平面上做：FFmpeg 的 `blend` 是逐平面的，直接在 YUV 上 screen
                # 会把中性灰的色度从 128 抬到 192（实测交付里读出 (255,150,255) 的品红）——
                # 「把原图叠回来」绝不能改颜色。所以三路先各自 format=gbrp，再相合。
                rgb = [plan.tag("grgb") for _ in range(3)]
                plan.filters.append(f"{graded}format=gbrp{rgb[0]}")
                plan.filters.append(f"{sized[0]}format=gbrp{rgb[1]}")
                plan.filters.append(f"{sized[1]}format=gbrp{rgb[2]}")
                # 两段而不是一个旋钮：实测 `all_opacity` 只在 `normal` 上是干净的线性插值
                # （0 给第二路、1 给第一路），而 `screen`／`multiply` 在 op=0 会退回第一路。
                # 一个旋钮同时当「相合方式」和「权重」会谎报两端，所以先按方式相合、再 normal 插值。
                mode_result = plan.tag("gmode")
                plan.filters.append(f"{rgb[0]}{rgb[1]}blend=all_mode={stage['mode']}{mode_result}")
                lerped = plan.tag("glerp")
                plan.filters.append(
                    f"{mode_result}{rgb[2]}blend=all_mode=normal"
                    f":all_opacity={stage['mix']:.6g}{lerped}"
                )
                plan.filters.append(f"{lerped}{fit_post}{label}")
            else:
                head = focus_stages(
                    plan,
                    f"{source}{paced}{color}{fit_pre}",
                    clip,
                    focus_basis,
                    frame_ticks=settings.frame_ticks,
                    alpha=True,
                )
                head = f"{head},{fit_post}"
                if entry["verified"].kind == "image":
                    plan.filters.append(f"{head}{label}")
                else:
                    plan.filters.append(
                        f"{head},trim=duration={sec(clip.duration_ticks)},setpts=PTS-STARTPTS{label}"
                    )
            labels.append(label)
            windows.append((clip.position_ticks, clip.position_ticks + clip.duration_ticks))
            cursor = clip.position_ticks + clip.duration_ticks
        if cursor < total:
            labels.append(blank_label(total - cursor))
        out = plan.tag("track") if len(layers) > 1 else "[vchain]"
        if len(labels) == 1:
            plan.filters.append(f"{labels[0]}copy{out}")
        else:
            plan.filters.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0{out}")
        return out, windows, len(labels)

    if audio_only:
        # The whole picture chain is skipped, not merely unmapped: no clip is decoded, no layer is
        # composited, and the only inputs that appear are the ones the audio loop below pulls.
        plan.video_label = ""
    elif plan.mode == "cut":
        chain, _, pieces = track_chain(layers[0])
        plan.filters.append(f"{chain}format={pixel_format}[vout]")
        plan.summary["segments"] = pieces
    else:
        current = blank_label(total)
        plan.filters.append(f"{current}copy[base]")
        current = "[base]"
        painted = []
        for entries in layers:
            mode = entries[0]["track"].blend_mode
            lower = current
            mixed_track = any(entry["clip"].transition_in for entry in entries)
            if mode != "normal" and not mixed_track:
                blank = plan.add_lavfi(f"color=c=black@0:s={size}:r={fps},format=rgba", total)
                current = plan.tag("transparent")
                plan.filters.append(f"[{blank}:v]settb=AVTB{current}")
            track_parts = []
            for entry in entries:
                clip = entry["clip"]
                index = clip_input(entry)
                scale = expression(clip, "scale")
                rotation = expression(clip, "rotation")
                opacity = expression(clip, "opacity", "T")
                zoom = None
                if mixed_track:
                    weight = curve_expression(
                        transition_curves[clip.id]["picture"], clip.duration_ticks, "T"
                    )
                    opacity = f"({opacity})*({weight})"
                    wipe = transition_curves[clip.id]["wipe"]
                    if wipe:
                        # The reveal is spatial, so it joins the alpha product, not
                        # the scalar weight: the outgoing side already carries the
                        opacity = (
                            f"({opacity})*("
                            + wipe_expression(
                                wipe["kind"],
                                wipe["invert"],
                                curve_expression(wipe["curve"], clip.duration_ticks, "T"),
                            )
                            + ")"
                        )
                    scale_curve = transition_curves[clip.id]["scale"]
                    if any(point["value"] != 1 for point in scale_curve):
                        # `scale` names its clock `t`; only `geq` uses `T`. Feeding it the wrong one
                        # is a graph-level "Invalid argument", not a silent misread.
                        zoom = curve_expression(scale_curve, clip.duration_ticks)
                animated = {k.property for k in clip.keyframes}
                path_mask = clip.mask if clip.mask and clip.mask.shape == "path" else None
                mask_values = (
                    {
                        name: expression(clip, name, "T", (10 + 2 * slot, 11 + 2 * slot))
                        for slot, name in enumerate(MASK_FIELDS)
                        if clip.mask and name in animated
                    }
                    if clip.mask and animated & set(MASK_FIELDS)
                    else None
                )
                alpha = []
                if clip.mask and not path_mask:
                    alpha.append(f"({alpha_expression(clip.mask, mask_values, mask_box)})")
                if (
                    clip.effects.opacity != 1
                    or "opacity" in animated
                    or mixed_track
                    or fade_active(clip, "opacity")
                ):
                    alpha.append(f"({opacity})")
                # One alpha pass, and it has to happen before the size can move: `geq` allocates
                # against the frame it is given, so feeding it the output of a
                # `scale=…:eval=frame` whose dimensions change every frame kills FFmpeg outright
                # (measured: exit 0xC0000409 with no stderr at all).
                transform = (
                    (f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*{'*'.join(alpha)}',")
                    if alpha
                    else ""
                )
                if clip.effects.scale != 1 or "scale" in animated or zoom:
                    # Not `size`: that name already holds the output canvas for every later stage.
                    size_factor = f"({scale})*({zoom})" if zoom else scale
                    transform += (
                        f"scale=w='max(2,trunc(iw*({size_factor})/2)*2)':"
                        f"h='max(2,trunc(ih*({size_factor})/2)*2)':eval=frame,"
                    )
                if clip.effects.rotation != 0 or "rotation" in animated:
                    transform += (
                        f"rotate=angle='({rotation})*PI/180':ow='hypot(iw,ih)':"
                        "oh='hypot(iw,ih)':c=black@0,"
                    )
                chain = plan.tag("layer")
                title = ""
                if clip.text:
                    text = clip.text
                    name = "text-" + hashlib.sha256(text.body.encode()).hexdigest() + ".txt"
                    plan.text_files[name] = text.body
                    font = text_font_path(text.font)
                    font_size = picture_h * text.font_size
                    # 补边宽度：只有 `contain` 会让画面小于帧，其它适配是 0。
                    bar_y, bar_x = (out_h - picture_h) / 2, (out_w - picture_w) / 2
                    y = "(h-text_h)/2"
                    if text.align == "top":
                        y = f"{bar_y + picture_h * 0.08:.2f}"
                    elif text.align == "bottom":
                        y = f"{bar_y + picture_h * 0.92:.2f}-text_h"
                    x = "(w-text_w)/2"
                    if text.text_align == "left":
                        x = f"{bar_x + picture_w * 0.08:.2f}"
                    elif text.text_align == "right":
                        x = f"{bar_x + picture_w * 0.92:.2f}-text_w"
                    # drawtext's own box plate is unreliable, so express the subtitle
                    # backing as an alpha band via geq (same pattern as dip_black).
                    band = ""
                    if text.box:
                        band_h = font_size * 1.5
                        if text.align == "top":
                            y0 = bar_y + picture_h * 0.08
                        elif text.align == "bottom":
                            y0 = bar_y + picture_h * 0.96 - band_h
                        else:
                            y0 = (out_h - band_h) / 2
                        y1 = y0 + band_h
                        alpha = round(text.box_opacity * 255)
                        band = (
                            f"format=rgba,geq=r='{_rgb(text.box_color)[0]}':"
                            f"g='{_rgb(text.box_color)[1]}':b='{_rgb(text.box_color)[2]}':"
                            f"a='if(gte(Y,{y0:.1f})*lt(Y,{y1:.1f}),{alpha},0)',"
                        )
                    shadow = ""
                    if text.shadow_x or text.shadow_y:
                        shadow = (
                            f"shadowx={round(text.shadow_x * font_size)}:"
                            f"shadowy={round(text.shadow_y * font_size)}:"
                            f"shadowcolor={text.shadow_color}:"
                        )
                    title = (
                        f"{band}"
                        f"drawtext=fontfile='{font}':textfile={name}:expansion=none:"
                        f"fontsize={font_size}:fontcolor={text.color}:{shadow}"
                        f"bordercolor={text.outline_color}:"
                        f"borderw={round(text.outline_width * font_size)}:"
                        f"line_spacing={round(text.line_spacing * font_size)}:"
                        f"x={x}:y={y},"
                    )
                ramp = clip_ramp(clip, settings)
                video_source = entry.get("video", f"[{index}:v]")
                if ramp:
                    video_source = ramp_video(
                        plan, video_source, ramp, fps, settings.frame_ticks / TIMEBASE
                    )
                    paced = ""
                else:
                    paced = (
                        f"setpts=(PTS-STARTPTS)/{clip.speed_percent / 100},"
                        f"fps={fps},trim=duration={sec(clip.duration_ticks)},"
                    )
                fit = (
                    f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
                    f"format=rgba,pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color=black@0,"
                    "setsar=1"
                )
                composites = composite_stages(clip.color)
                if composites:
                    # 1.145：分层这条路里每个片段也有自己的一条链
                    # 所以「这条链进来的那幅画」在这里同样定义得清楚——不必再拒。
                    # 融合点必须放在遮罩与不透明度**之前**：两条支此刻共用同一串适配、同一份几何，
                    # 相合只减弱调色，不会改形状，也不会把被遮掉的画面复活。
                    # 另一条支的 alpha 一路带到底，用 `alphamerge` 盖回相合的结果：
                    # 这样 `mix` 无论拧到哪一端，交付文件的 matte 与不挂这一级时**逐帧相同**
                    # （透明母版那一档量的就是这个字节，不是滤镜串）。
                    stage = composites[0]
                    graded = plan.tag("lcxgraded")
                    raws = plan.tag("lcxraw")
                    gfit = plan.tag("lcxgfit")
                    rfit = plan.tag("lcxrfit")
                    gsplit = plan.tag("lcxgsplit")
                    galpha = plan.tag("lcxgalpha")
                    grgb = plan.tag("lcxgrgb")
                    rs1 = plan.tag("lcxrs1")
                    rs2 = plan.tag("lcxrs2")
                    rgb_mode = plan.tag("lcxrgbmode")
                    rgb_lerp = plan.tag("lcxrgblerp")
                    rgb_second = plan.tag("lcxrgbsecond")
                    mode_out = plan.tag("lcxmode")
                    lerped = plan.tag("lcxlerp")
                    merged = plan.tag("lcxmerged")
                    plan.filters.append(f"{video_source}{paced}{title}split=2{graded}{raws}")
                    plan.filters.append(f"{graded}{color_filter(clip, plan)}{fit}{gfit}")
                    plan.filters.append(f"{raws}{fit}{rfit}")
                    plan.filters.append(f"{gfit}split=2{grgb}{gsplit}")
                    plan.filters.append(f"{gsplit}alphaextract,format=gray{galpha}")
                    plan.filters.append(f"{grgb}format=gbrp{rgb_mode}")
                    plan.filters.append(f"{rfit}split=2{rs1}{rs2}")
                    plan.filters.append(f"{rs1}format=gbrp{rgb_lerp}")
                    # 同一个 pad 不能读两次：第二段插值还要用一次原图，所以这里再折一路。
                    plan.filters.append(f"{rs2}format=gbrp{rgb_second}")
                    plan.filters.append(
                        f"{rgb_mode}{rgb_lerp}blend=all_mode={stage['mode']}{mode_out}"
                    )
                    plan.filters.append(
                        f"{mode_out}{rgb_second}blend=all_mode=normal"
                        f":all_opacity={stage['mix']:.6g}{lerped}"
                    )
                    plan.filters.append(f"{lerped}{galpha}alphamerge{merged}")
                    head = f"{merged}format=rgba"
                else:
                    head = f"{video_source}{paced}{title}{color_filter(clip, plan)}{fit}"
                head = focus_stages(plan, head, clip, focus_basis, frame_ticks=settings.frame_ticks)
                body = (
                    f"{transform}"
                    f"tpad=start_duration={sec(clip.position_ticks)}:start_mode=add:color=black@0,"
                    f"settb=AVTB{chain}"
                )
                if not path_mask:
                    plan.filters.append(f"{head},{body}")
                else:
                    plane_w, plane_h = raster_size(picture_w, picture_h)
                    plate_pad = (
                        f",pad={out_w}:{out_h}:{bar_x:.0f}:{bar_y:.0f}"
                        f":color={'white' if path_mask.inverted else 'black'}"
                        if letterbox
                        else ""
                    )
                    # The outline carries its own size and anchor; a path mask's box fields are the
                    # editor's handle, so the drawn geometry (not a stale box) decides where the cut
                    # lands, and a keyframed centre moves it from exactly there.
                    # 1.118: an animated outline is compiled into frame-aligned windows by the same
                    # engine function the preview reads (`animation.mask_shape_schedule`), and one
                    # plate is cut per window below. A mask that does not morph still gets exactly
                    # one window, so the graph this exporter emitted before outlines could move is
                    # emitted byte for byte.
                    outlines = mask_shape_schedule(
                        clip, settings.frame_ticks, MASK_SHAPE_SCHEDULE_MAX
                    )
                    keep = plan.tag("maskkeep")
                    alpha_plane = plan.tag("maskalpha")
                    frame_alpha = plan.tag("maskframe")
                    flat = plan.tag("maskflat")
                    sized = plan.tag("masksized")
                    kept_alpha = plan.tag("maskkept")
                    combined = plan.tag("maskcombined")
                    merged = plan.tag("maskmerged")
                    plate = plan.tag("maskplate")
                    cut = plan.tag("maskcut")
                    # Outside the patch the plate has to be the neutral value of the mask itself:
                    # an inverted free-form mask keeps the picture around the outline.
                    canvas = plan.add_lavfi(
                        f"color=c={'white' if path_mask.inverted else 'black'}"
                        f":s={plane_w}x{plane_h}:r={fps}",
                        total,
                    )
                    centre_x = expression(clip, "mask_x", "t")
                    centre_y = expression(clip, "mask_y", "t")
                    plan.filters.append(f"{head},settb=AVTB,split=2{keep}{alpha_plane}")
                    plan.filters.append(f"{alpha_plane}alphaextract,format=gray{frame_alpha}")
                    # The patch is baked and then *moved* over the plate: `overlay` accepts
                    # frame-time x/y without changing its output size, while a per-frame `scale`
                    # would hand the next filter a frame whose size keeps changing (the crash 1.48
                    # fixed). So the box keeps sliding on its curves while a morph swaps the plate
                    # underneath it — one window at a time, on the same clock those curves read.
                    plan.filters.append(f"[{canvas}:v]format=gray,settb=AVTB{plate_pad}{plate}")
                    stages = outlines or [
                        {"from_ticks": 0, "to_ticks": clip.duration_ticks, "value": None}
                    ]
                    last = len(stages) - 1
                    running = plate
                    for index, window in enumerate(stages):
                        drawn = (
                            path_mask
                            if window["value"] is None
                            else outline_mask(clip, window["value"])
                        )
                        patch = path_patch(
                            plan, drawn, path_mask, plane_w, plane_h, bar_x, bar_y, total, fps
                        )
                        stage_cut = cut if len(stages) == 1 else plan.tag("maskcut")
                        stage_flat = flat if index == last else plan.tag("maskflat")
                        # A wide feather is baked on a smaller grid inside `mask_png`, so the patch
                        # is rescaled to its plane size before it is moved.
                        plan.filters.append(
                            f"[{patch['source']}:v]format=gray,settb=AVTB,"
                            f"scale={patch['patch_w']}:{patch['patch_h']}:flags=bicubic{stage_cut}"
                        )
                        windowed = ""
                        if outlines:
                            windowed = (
                                ":enable='between(t,"
                                f"{sec(window['from_ticks'])},{sec(window['to_ticks'])})'"
                            )
                        plan.filters.append(
                            f"{running}{stage_cut}overlay="
                            f"x='{plane_w}*({centre_x}){patch['anchor_x']:+.6f}'"
                            f":y='{plane_h}*({centre_y}){patch['anchor_y']:+.6f}'"
                            f":eval=frame{windowed}{stage_flat}"
                        )
                        running = stage_flat
                    plan.filters.append(
                        f"{running}{frame_alpha}scale2ref=flags=bicubic{sized}{kept_alpha}"
                    )
                    plan.filters.append(f"{kept_alpha}{sized}blend=all_mode=multiply{combined}")
                    plan.filters.append(f"{keep}{combined}alphamerge{merged}")
                    plan.filters.append(f"{merged}{body}")
                backdrop = current
                if mixed_track:
                    blank = plan.add_lavfi(f"color=c=black@0:s={size}:r={fps},format=rgba", total)
                    backdrop = plan.tag("transparent")
                    plan.filters.append(f"[{blank}:v]settb=AVTB{backdrop}")
                nxt = plan.tag("mix")
                start, stop = clip.position_ticks, clip.position_ticks + clip.duration_ticks
                clock = f"(t-{sec(start)})"
                x, y = expression(clip, "x", clock), expression(clip, "y", clock)
                if mixed_track:
                    # A motion transition moves the whole layer, and the placement below is already
                    # an expression in frame fractions — so the transition and the clip's own
                    # keyframes add, and both ends read the one envelope list the browser is handed.
                    for axis, channel in (("x", "motion_x"), ("y", "motion_y")):
                        points = transition_curves[clip.id][channel]
                        if any(point["value"] for point in points):
                            term = curve_expression(points, clip.duration_ticks, clock)
                            if axis == "x":
                                x = f"({x})+({term})"
                            else:
                                y = f"({y})+({term})"
                plan.filters.append(
                    f"{backdrop}{chain}overlay=eof_action=pass:repeatlast=0:format=auto:"
                    f"x='(W-w)/2+W*({x})':y='(H-h)/2+H*({y})':"
                    f"enable='gte(t,{sec(start)})*lt(t,{sec(stop)})'{nxt}"
                )
                if mixed_track:
                    part = plan.tag("premul")
                    plan.filters.append(f"{nxt}format=gbrap,premultiply=inplace=1{part}")
                    track_parts.append(part)
                    if clip.transition_in and clip.transition_in.kind in {"dip_black", "dip_white"}:
                        white = clip.transition_in.kind == "dip_white"
                        name = "white" if white else "black"
                        neutral = plan.add_lavfi(
                            f"color=c={name}@0:s={size}:r={fps},format=rgba",
                            total,
                        )
                        flash = curve_expression(
                            transition_curves[clip.id]["white" if white else "black"],
                            clip.duration_ticks,
                            f"(T-{sec(start)})",
                        )
                        part = plan.tag("neutral")
                        plan.filters.append(
                            (
                                f"[{neutral}:v]geq=r='{'255' if white else '0'}':"
                                f"g='{'255' if white else '0'}':b='{'255' if white else '0'}':"
                                f"a='255*({flash})',format=gbrap,settb=AVTB{part}"
                            )
                        )
                        track_parts.append(part)
                else:
                    current = nxt
            if mixed_track:
                # ponytail: full-length layers; partition graphs if long 4K runs exceed memory.
                blended = track_parts[0]
                for part in track_parts[1:]:
                    added = plan.tag("plus")
                    plan.filters.append(f"{blended}{part}blend=all_mode=addition:shortest=1{added}")
                    blended = added
                straight = plan.tag("straight")
                plan.filters.append(f"{blended}unpremultiply=inplace=1,format=rgba{straight}")
                current = blend_track(plan, lower, straight, mode)
            elif mode != "normal":
                current = blend_track(plan, lower, current, mode)
            painted.append(len(entries))
        plan.filters.append(f"{current}format={'rgba' if alpha_out else pixel_format}[vout]")
        plan.summary["layers"] = len(layers)
    if not audio_only:
        plan.video_label = "[vout]"

    mixed = ["[abase]"]
    base_audio = plan.add_lavfi(
        f"anullsrc=channel_layout=stereo:sample_rate={settings.sample_rate}", total
    )
    plan.filters.append(
        f"[{base_audio}:a]aformat=sample_rates={settings.sample_rate}:channel_layouts=stereo[abase]"
    )
    for entry in sounds:
        clip, verified = entry["clip"], entry["verified"]
        if verified and (verified.kind == "image" or not verified.has_audio):
            continue
        index = clip_input(entry)
        gain = expression(clip, "gain")
        if any(point["value"] != 1 for point in transition_curves[clip.id]["sound"]):
            weight = curve_expression(transition_curves[clip.id]["sound"], clip.duration_ticks)
            gain = f"({gain})*({weight})"
        delay = ms(clip.position_ticks)
        ramp = clip_ramp(clip, settings, settings.timebase // settings.sample_rate)
        audio_source = entry.get("audio", f"[{index}:a]")
        if ramp:
            paced_audio = ramp_audio(plan, audio_source, ramp, settings.sample_rate)
        else:
            tempo = clip.speed_percent / 100
            tempos = []
            while tempo < 0.5:
                tempos.append("atempo=0.5")
                tempo /= 0.5
            while tempo > 2:
                tempos.append("atempo=2")
                tempo /= 2
            tempos.append(f"atempo={tempo}")
            paced_audio = (
                f"{audio_source}asetpts=PTS-STARTPTS,{','.join(tempos)},"
                f"atrim=0:{sec(clip.duration_ticks)},"
            )
        # One `afftdn` per clip, before the gain, so the level the meter measured is applied to
        # the signal the editor will actually hear in the delivered file.
        # `nf` is pinned, not left at FFmpeg's -50 dB default: measured on the fixture, the
        # knob only does what its label promises once the gate is looking at the region a room
        # recording actually hisses in (-46.7 dBFS band with the default, -55.6 at nr=12 here).
        denoise = (
            f"afftdn=nr={clip.effects.denoise}:nf={DENOISE_FLOOR_DB},"
            if clip.effects.denoise
            else ""
        )
        chain = (
            f"{paced_audio}asetpts=PTS-STARTPTS,{denoise}"
            f"volume='({gain})*{entry['track'].volume}':eval=frame,"
            f"aformat=sample_rates={settings.sample_rate}:channel_layouts=stereo,"
            f"adelay={delay}|{delay}"
        )
        label = plan.tag("a")
        plan.filters.append(chain + label)
        mixed.append(label)
    count = len(mixed) - 1
    # One master gain over the whole mix, applied after the layers are summed so it cannot
    # reintroduce the clipping the per-clip ceilings avoided. A gain of 1.0 adds no stage at all.
    master = f"volume={settings.master_gain}:eval=frame," if settings.master_gain != 1.0 else ""
    # A ceiling, not a loudness maximiser: `level=disabled` switches off FFmpeg's auto-level, which
    # would otherwise push the signal back up to the limit and defeat the point of having one.
    if settings.master_limiter:
        limit = 10.0 ** (settings.master_ceiling_dbtp / 20.0)
        master += f"alimiter=limit={limit:.6f}:attack=5:release=80:level=disabled,"
    if count == 0:
        plan.filters.append("[abase]anull[aout]")
    else:
        plan.filters.append(
            "".join(mixed)
            + f"amix=inputs={len(mixed)}:duration=longest:normalize=0,"
            + f"{master}aformat=sample_rates={settings.sample_rate}:channel_layouts=stereo[aout]"
        )
    plan.audio_label = "[aout]"
    plan.summary["audio_layers"] = count

    if range_ticks is not None:
        # Cut the marked window out of the finished mix rather than re-planning the timeline: the
        # frames, the mix, the master gain and the limiter are exactly what the full export would
        # have produced, so a partial deliverable cannot quietly differ from the reviewed one.
        # Frames for the picture (the stream is already `fps=` normalised), seconds for the sound.
        start, end = range_ticks
        if not 0 <= start < end <= total:
            raise EditorError(
                "INVALID_MARKS",
                f"a rendered range has to sit inside the timeline (0..{total} ticks)",
                422,
                in_ticks=start,
                out_ticks=end,
            )
        # 帧号是**交付流**的帧号：1.138 之后这两把尺可以不同，用时间线的那一把去除，切出来的窗口
        # 会晚 `交付率/时间线率` 一秒开始、再多露出同样长的一截（实测：30 的线标 1..2 秒、按 25 交，
        # 旧的算法交出 20 帧绿 + 5 帧蓝——入点前少了一截、出点后多露了一截）。
        # 两头都向上取整：第一帧不早于入点，最后一帧的起点仍早于出点（end 是开区间）。
        frame = TIMEBASE * delivery.denominator // delivery.numerator
        start_frame = -(-start // frame)
        end_frame = max(start_frame + 1, -(-end // frame))
        if plan.video_label:
            plan.filters.append(
                f"{plan.video_label}trim=start_frame={start_frame}:end_frame={end_frame},"
                f"setpts=PTS-STARTPTS[vrange]"
            )
            plan.video_label = "[vrange]"
        plan.filters.append(
            f"{plan.audio_label}atrim=start={sec(start)}:end={sec(end)},"
            f"asetpts=PTS-STARTPTS[arange]"
        )
        plan.audio_label = "[arange]"
        plan.duration_ticks = end - start
        plan.summary["range"] = {
            "in_ticks": start,
            "out_ticks": end,
            "seconds": round((end - start) / TIMEBASE, 3),
        }
    else:
        plan.duration_ticks = total

    plan.output_args = output_args(
        preset,
        settings.sample_rate,
        rate,
        transparent=transparent,
        timecode=timecode,
        delivery_rate=output_frame_rate,
    )
    plan.summary.update(
        {
            "encoder": f"{preset['label']} ({preset['container']})",
            "preset_id": preset["id"],
            "container": preset["container"],
            "video_codec": preset["codec"],
            "audio_codec": preset["audio_codec"],
            "pixel_format": preset["pixel_format"],
            "transparent": transparent,
            "timecode": timecode,
            # 序列交付写进摘要：不写声音、产出是一串文件的名字，界面与 Agent 读同一份。
            "sequence": bool(preset["sequence"]),
            "audio": not preset["sequence"],
            # 工程自己的率也写一份：读到 `frame_rate` 是 25 时，得知道那是交付的率还是时间线的率。
            "project_frame_rate": (
                f"{settings.frame_rate.numerator}/{settings.frame_rate.denominator}"
            ),
            "resolution": None if audio_only else size,
            "frame_rate": fps,
            "project": {"id": project.id, "name": project.name, "revision": project.revision},
            "tracks": [
                {
                    "id": track.id,
                    "name": track.name,
                    "kind": track.kind,
                    "muted": track.muted,
                    "hidden": track.hidden,
                    "volume": track.volume,
                    "blend_mode": track.blend_mode,
                    "clips": sum(1 for clip in project.clips.values() if clip.track_id == track.id),
                }
                for track in project.tracks
            ],
            "sources": sorted(
                {entry["verified"].path for group in layers for entry in group if entry["verified"]}
                | {entry["verified"].path for entry in sounds if entry["verified"]}
                | nested_sources
            ),
        }
    )
    # Decided here, not when the command line is built: callers hand `text_files` to disk before
    # they ask for argv, and a file that only appears once argv exists is a file nobody writes.
    # The render graph and the single-frame graph differ by their audio sink, so they are two files.
    render_graph = plan.render_graph_text()
    frame_graph = plan.frame_graph_text()
    if len(render_graph) > GRAPH_SCRIPT_LIMIT:
        plan.graph_in_file = True
        plan.text_files["filtergraph.txt"] = render_graph
    if len(frame_graph) > GRAPH_SCRIPT_LIMIT:
        plan.frame_graph_in_file = True
        plan.text_files["filtergraph-frame.txt"] = frame_graph
    return plan


def marked_range(project: Project) -> tuple[int, int] | None:
    """The sequence's marked window, or None when nothing is marked.

    One place reads the marks, so the queued job, the render-plan preview and the worker cannot
    disagree about what `range=marks` means for the same project.
    """
    settings = project.settings
    if settings.in_ticks is None or settings.out_ticks is None:
        return None
    return settings.in_ticks, settings.out_ticks


def timeline_duration(project: Project) -> int:
    ends = [clip.position_ticks + clip.duration_ticks for clip in project.clips.values()]
    return max(ends) if ends else 0
