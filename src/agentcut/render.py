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

from .animation import expression, sound_enabled
from .compositing import blend_track
from .contracts import MASK_FIELDS, TIMEBASE, EditorError, Project, render_presets
from .grade import grade_filter
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
from .transitions import curve_expression, envelopes


def sec(ticks: int) -> str:
    return f"{ticks / TIMEBASE:.6f}"


def ms(ticks: int) -> int:
    return max(0, round(ticks / TIMEBASE * 1000))


def color_filter(clip) -> str:
    color = clip.color
    grade = grade_filter(color)
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


def output_args(preset: dict, sample_rate: int, frame_rate: float) -> list[str]:
    """Encode and mux arguments for one preset, switched by the codec the preset names.

    The vocabulary is closed here, not in the caller: a preset may only name a codec this function
    knows, so a render request steers FFmpeg with an id and nothing else. Each branch is what that
    encoder actually accepts rather than one template forced on all of them — VP9 takes no
    `-preset` and wants `-b:v 0` beside its crf, ProRes takes neither and is chosen by a profile,
    PCM has no bitrate, and `-movflags` belongs to the mp4/mov muxer only.
    """
    codec = preset["codec"]
    video = ["-c:v", codec]
    if codec in ("libx264", "libx265"):
        video += ["-preset", str(preset["encoder_preset"]), "-crf", str(preset["crf"])]
        if codec == "libx265":
            # hvc1, not hev1: the parameter sets go into the sample description, which is what lets
            # QuickTime and editors play the file instead of only FFmpeg reading it back.
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
    else:
        raise EditorError(
            "UNKNOWN_PRESET", f"this build cannot encode {codec}", 422, preset_id=preset["id"]
        )
    # GOP sizing stays the same on every codec: the checks in curvefidelity/gradelevels read frames
    # at arbitrary times, and a keyframe every two seconds is what makes that cheap.
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
    mux = ["-movflags", "+faststart"] if preset["container"] in ("mp4", "mov") else []
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
    counter: int = 0
    text_files: dict[str, str] = field(default_factory=dict)
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
            "-filter_complex",
            ";".join(self.filters),
            "-map",
            self.video_label,
            "-map",
            self.audio_label,
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
            "-filter_complex",
            ";".join([*self.filters, f"{self.audio_label}anullsink"]),
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
    _transparent: bool = False,
    _duration_ticks: int | None = None,
) -> RenderPlan:
    if not _transparent:
        validate_timeline(project)
    if sequence_id is not None:
        _duration_ticks = (
            project.sequences[sequence_id].duration_ticks
            if sequence_id in project.sequences
            else None
        )
        project = sequence_view(project, sequence_id)
    preset = preset_by_id(preset_id)
    settings = project.settings
    out_w, out_h = preview_size or preset["scale"] or (settings.width, settings.height)
    fps = f"{settings.frame_rate.numerator}/{settings.frame_rate.denominator}"
    rate = settings.frame_rate.numerator / settings.frame_rate.denominator
    size = f"{out_w}x{out_h}"
    # The preset's sampling format runs through the whole picture chain, not just the encoder flag:
    # a 4:4:10-bit intermediate has to keep 4:4:4 from the decode and the framing stages too, or the
    # chroma is thrown away upstream and the wrapper only looks deep. Every H.264/HEVC/VP9 preset
    # says yuv420p, so the graphs those presets compile are unchanged.
    pixel_format = preset["pixel_format"]

    video_tracks = [track for track in project.tracks if track.kind == "video" and not track.hidden]
    audio_tracks = [track for track in project.tracks if track.kind == "audio" and not track.muted]

    layers: list[list[dict]] = []
    visible: list[tuple[object, list[dict]]] = []
    for track in video_tracks:
        entries = _entries_for_track(project, track)
        if entries:
            layers.append(entries)
            visible.append((track, entries))
    if not layers and _duration_ticks is None:
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

    total = _duration_ticks or 0
    for entries in layers:
        total = max(
            total,
            *[entry["clip"].position_ticks + entry["clip"].duration_ticks for entry in entries],
        )
    for entry in sounds:
        total = max(total, entry["clip"].position_ticks + entry["clip"].duration_ticks)

    compositing = (
        _transparent
        or not layers
        or len(layers) > 1
        or any(track.blend_mode != "normal" for track, _ in visible)
        or any(
            entry["asset"].kind in {"text", "sequence"}
            or entry["clip"].mask
            or entry["clip"].transition_in
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
    plan = RenderPlan(mode="layered" if compositing else "cut")
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
    fit_stage = f"{sizing}setsar=1,fps={fps},format={pixel_format},settb=AVTB"

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
            plan.text_files.update(child.text_files)
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
            f"color=c={'black@0' if _transparent else 'black'}:s={size}:r={fps},format=rgba",
            duration_ticks,
        )
        label = plan.tag("blank")
        plan.filters.append(
            f"[{index}:v]fps={fps},format={'rgba' if _transparent else pixel_format},"
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
            color = color_filter(clip)
            ramp = clip_ramp(clip, settings)
            if entry["verified"].kind == "image":
                plan.filters.append(f"{source}{color}{fit_stage}{label}")
            else:
                if ramp:
                    source = ramp_video(plan, source, ramp, fps, settings.frame_ticks / TIMEBASE)
                    paced = ""
                else:
                    paced = f"setpts=(PTS-STARTPTS)/{clip.speed_percent / 100},"
                plan.filters.append(
                    f"{source}{paced}{color}{fit_stage},"
                    f"trim=duration={sec(clip.duration_ticks)},setpts=PTS-STARTPTS{label}"
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

    if plan.mode == "cut":
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
                if mixed_track:
                    weight = curve_expression(
                        transition_curves[clip.id]["picture"], clip.duration_ticks, "T"
                    )
                    opacity = f"({opacity})*({weight})"
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
                    alpha.append(f"({alpha_expression(clip.mask, mask_values)})")
                if clip.effects.opacity != 1 or "opacity" in animated or mixed_track:
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
                if clip.effects.scale != 1 or "scale" in animated:
                    transform += (
                        f"scale=w='max(2,trunc(iw*({scale})/2)*2)':"
                        f"h='max(2,trunc(ih*({scale})/2)*2)':eval=frame,"
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
                    font = (
                        "C\\:/Windows/Fonts/msyh.ttc"
                        if os.name == "nt"
                        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
                    )
                    font_size = out_h * text.font_size
                    y = "(h-text_h)/2"
                    if text.align == "top":
                        y = "h*0.08"
                    elif text.align == "bottom":
                        y = "h-text_h-h*0.08"
                    # drawtext's own box plate is unreliable, so express the subtitle
                    # backing as an alpha band via geq (same pattern as dip_black).
                    band = ""
                    if text.box:
                        band_h = font_size * 1.5
                        if text.align == "top":
                            y0 = out_h * 0.08
                        elif text.align == "bottom":
                            y0 = out_h - band_h - out_h * 0.04
                        else:
                            y0 = (out_h - band_h) / 2
                        y1 = y0 + band_h
                        band = (
                            "format=rgba,geq=r='0':g='0':b='0':"
                            f"a='if(gte(Y,{y0:.1f})*lt(Y,{y1:.1f}),115,0)',"
                        )
                    title = (
                        f"{band}"
                        f"drawtext=fontfile='{font}':textfile={name}:expansion=none:"
                        f"fontsize={font_size}:fontcolor={text.color}:bordercolor=black:"
                        f"borderw={max(1, font_size * 0.04)}:line_spacing={font_size * 0.2}:"
                        f"x=(w-text_w)/2:y={y},"
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
                head = (
                    f"{video_source}{paced}"
                    f"{title}"
                    f"{color_filter(clip)}"
                    f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
                    f"format=rgba,pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color=black@0,"
                    "setsar=1"
                )
                body = (
                    f"{transform}"
                    f"tpad=start_duration={sec(clip.position_ticks)}:start_mode=add:color=black@0,"
                    f"settb=AVTB{chain}"
                )
                if not path_mask:
                    plan.filters.append(f"{head},{body}")
                else:
                    plane_w, plane_h = raster_size(out_w, out_h)
                    # The outline carries its own size and anchor; a path mask's box fields are the
                    # editor's handle, so the drawn geometry (not a stale box) decides where the cut
                    # lands, and a keyframed centre moves it from exactly there.
                    left, top, right, bottom = path_bounds(path_mask)
                    box_w = max(2, int(round(plane_w * (right - left))))
                    box_h = max(2, int(round(plane_h * (bottom - top))))
                    # A feather spreads the ramp past the outline and the patch is only as big as
                    # the outline, so the ramp is baked into a padded plate instead of being cut
                    # off at the shape's own bounding box.
                    sigma = feather_sigma(box_w, box_h, path_mask.feather)
                    pad = int(3 * sigma) + 2
                    patch_w, patch_h = box_w + 2 * pad, box_h + 2 * pad
                    # `feather_sigma` measures the short edge, so the inset is corrected by the
                    # short edge's own ratio — otherwise a wide patch would blur the ramp too far.
                    shrink = min(box_w, box_h) / min(patch_w, patch_h)
                    png = mask_png(
                        unit_path(
                            path_mask.model_copy(update={"feather": path_mask.feather * shrink}),
                            box_w / patch_w,
                            box_h / patch_h,
                        ),
                        patch_w,
                        patch_h,
                    )
                    name = "mask-" + hashlib.sha256(png).hexdigest()[:24] + ".png"
                    plan.binary_files[name] = png
                    source = plan.add_still(name, total, str(fps))
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
                    anchor_x = plane_w * ((left + right) / 2 - path_mask.center_x) - patch_w / 2
                    anchor_y = plane_h * ((top + bottom) / 2 - path_mask.center_y) - patch_h / 2
                    centre_x = expression(clip, "mask_x", "t")
                    centre_y = expression(clip, "mask_y", "t")
                    plan.filters.append(f"{head},settb=AVTB,split=2{keep}{alpha_plane}")
                    plan.filters.append(f"{alpha_plane}alphaextract,format=gray{frame_alpha}")
                    # The patch is baked once and then *moved* over the plate: `overlay` accepts
                    # frame-time x/y without changing its output size, while a per-frame `scale`
                    # would hand the next filter a frame whose size keeps changing (the crash 1.48
                    # fixed). So a free-form mask animates its position; shape and size stay drawn.
                    plan.filters.append(f"[{canvas}:v]format=gray,settb=AVTB{plate}")
                    # A wide feather is baked on a proportionally smaller grid inside `mask_png`,
                    # so the patch is rescaled to its plane size before it is moved.
                    plan.filters.append(
                        f"[{source}:v]format=gray,settb=AVTB,"
                        f"scale={patch_w}:{patch_h}:flags=bicubic{cut}"
                    )
                    plan.filters.append(
                        f"{plate}{cut}overlay=x='{plane_w}*({centre_x}){anchor_x:+.6f}'"
                        f":y='{plane_h}*({centre_y}){anchor_y:+.6f}':eval=frame{flat}"
                    )
                    plan.filters.append(
                        f"{flat}{frame_alpha}scale2ref=flags=bicubic{sized}{kept_alpha}"
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
        plan.filters.append(f"{current}format={'rgba' if _transparent else pixel_format}[vout]")
        plan.summary["layers"] = len(layers)
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
        chain = (
            f"{paced_audio}asetpts=PTS-STARTPTS,"
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
        frame = settings.frame_ticks
        plan.filters.append(
            f"{plan.video_label}trim=start_frame={start // frame}:end_frame={end // frame},"
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

    plan.output_args = output_args(preset, settings.sample_rate, rate)
    plan.summary.update(
        {
            "encoder": f"{preset['label']} ({preset['container']})",
            "preset_id": preset["id"],
            "container": preset["container"],
            "video_codec": preset["codec"],
            "audio_codec": preset["audio_codec"],
            "pixel_format": preset["pixel_format"],
            "resolution": size,
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
