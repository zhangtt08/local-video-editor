"""A CMX3600 edit decision list for one picture track.

Why an EDL instead of a render: a project that was cut here should be reviewable in the tools a
colourist or an online editor already owns. An EDL is the smallest interchange that every one of
them reads (Resolve, Premiere, Final Cut, Avid via conversion), and it is plain text — so the exact
cutting order, source in-points and record in-points can be diffed and tested here without another
application in the loop.

What this writes is deliberately narrow: one track, straight cuts, 100 % speed, video clips only.
Those are the only things a CMX3600 list carries without inventing syntax (transitions need `D`
records with a duration, speed changes need a time-warp comment that only some readers honour, and
gaps need black events). A clip that cannot be said honestly is refused by name instead of being
left out — an EDL that silently drops a shot is worse than no EDL.

Timecode is non-drop frames at an integer rate. A fractional rate (29.97, 23.976) needs the drop /
non-drop decision and its own arithmetic, so it is refused by name rather than rounded.
"""

from __future__ import annotations

import json
import math
import re
import uuid
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from urllib.parse import unquote, urlparse
from xml.sax.saxutils import quoteattr

from .contracts import TIMEBASE, Asset, Clip, EditorError


def _rate_numbers(project) -> tuple[int, int]:
    rate = project.settings.frame_rate
    if rate.denominator != 1:
        raise EditorError(
            "EDL_RATE",
            "an EDL is written at whole frames per second; this timeline is "
            f"{rate.numerator}/{rate.denominator} fps. Switch the project to 24/25/30/50/60 or "
            "deliver a file instead.",
            422,
            numerator=rate.numerator,
            denominator=rate.denominator,
        )
    return rate.numerator, rate.denominator


def timecode(ticks: int, fps: int) -> str:
    """Non-drop HH:MM:SS:FF at a whole frame rate, rounded down to the frame the viewer sees."""
    frame_ticks = TIMEBASE // fps
    frames = max(0, int(ticks) // frame_ticks)
    seconds, frame = divmod(frames, fps)
    minutes, second = divmod(seconds, 60)
    hour, minute = divmod(minutes, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}:{frame:02d}"


def reel_name(label: str) -> str:
    """CMX reels are up to eight capitals/digits/underscores; anything else is replaced, not cut."""
    cleaned = re.sub(r"[^A-Z0-9]", "_", (label or "").upper())[:8].strip("_")
    return cleaned or "AX"


def _problem(project, clip) -> str | None:
    asset = project.assets.get(clip.asset_id)
    if asset is None or asset.kind != "video":
        return "an EDL carries picture only; this clip is not a video asset"
    if clip.speed_percent != 100:
        return "an EDL has no speed field; set the clip back to 100 % or deliver a file"
    if clip.transition_in is not None:
        return "an EDL needs a dissolve record for a transition; this clip has one"
    if clip.duration_ticks <= 0:
        return "a clip with no length has no source out-point"
    return None


def build_edl(project, track_id: str) -> dict:
    """The list for one picture track, as text plus the events it is made of."""
    track = next((item for item in project.tracks if item.id == track_id), None)
    if track is None:
        raise EditorError("NOT_FOUND", "track is not in this project", 404, track_id=track_id)
    if track.kind != "video":
        raise EditorError(
            "EDL_UNSUPPORTED",
            "an EDL lists picture; this track carries sound. Pick a picture track.",
            422,
            track_id=track_id,
        )
    clips = sorted(
        (clip for clip in project.clips.values() if clip.track_id == track_id),
        key=lambda clip: (clip.position_ticks, clip.id),
    )
    if not clips:
        raise EditorError("EDL_EMPTY", "this track has no clips to list", 422, track_id=track_id)
    refused = [
        {"clip_id": clip.id, "reason": problem}
        for clip in clips
        if (problem := _problem(project, clip)) is not None
    ]
    if refused:
        raise EditorError(
            "EDL_UNSUPPORTED",
            "this track holds edits a CMX3600 list cannot say; nothing was written. "
            "Remove or convert them, or deliver a file instead.",
            422,
            track_id=track_id,
            clips=refused,
        )
    fps, _ = _rate_numbers(project)
    events = []
    for number, clip in enumerate(clips, 1):
        asset = project.assets[clip.asset_id]
        events.append(
            {
                "number": number,
                "clip_id": clip.id,
                "reel": reel_name(asset.label),
                "source_in_ticks": clip.source_in_ticks,
                "record_in_ticks": clip.position_ticks,
                "duration_ticks": clip.duration_ticks,
                "source_in": timecode(clip.source_in_ticks, fps),
                "source_out": timecode(clip.source_in_ticks + clip.duration_ticks, fps),
                "record_in": timecode(clip.position_ticks, fps),
                "record_out": timecode(clip.position_ticks + clip.duration_ticks, fps),
                "label": asset.label,
            }
        )
    title = " ".join(project.name.replace("\r", " ").replace("\n", " ").split())[:64] or "AgentCut"
    lines = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""]
    for event in events:
        lines.append(
            f"{event['number']:03d}  {event['reel']:<8} V     C        "
            f"{event['source_in']} {event['source_out']} {event['record_in']} {event['record_out']}"
        )
        lines.append(f"* FROM CLIP NAME: {event['label']}")
        lines.append("")
    end = max(event["record_in_ticks"] + event["duration_ticks"] for event in events)
    return {
        "track_id": track_id,
        "track_name": track.name,
        "frame_rate": fps,
        "duration_ticks": end,
        "events": events,
        "text": "\n".join(lines),
    }


# ---------------------------------------------------------------------------
# 1.289：工程格式互操作（OpenTimelineIO / FCPXML / SRT）
#
# 吸收开源剪辑生态里最通用的一件事：把可编辑时间线当作交换单位。OpenTimelineIO 是
# 业界读得最广的那张 JSON，OpenCut / OpenChatCut 也都把它当出口。AgentCut 的差别不在
# 「也能导出」，而在导入也走同一个 reducer：先交回普通命令，人审过再提交，一次一个
# revision。这里没有第二条写入路径。
# ---------------------------------------------------------------------------

def _rate(project) -> tuple[int, int]:
    rate = project.settings.frame_rate
    return int(rate.numerator), int(rate.denominator)


def _fps(project) -> float:
    numerator, denominator = _rate(project)
    return numerator / denominator


def _media_path(asset: Asset) -> str | None:
    verified = asset.verified
    return verified.path if verified is not None else None


def _file_url(asset: Asset) -> str:
    path = _media_path(asset)
    if path:
        try:
            return Path(path).as_uri()
        except ValueError:
            return path
    return asset.reference


def _otio_time(ticks: int, fps: float) -> dict:
    return {
        "OTIO_SCHEMA": "RationalTime.1",
        "rate": fps,
        "value": round(ticks / TIMEBASE * fps, 9),
    }


def _otio_range(start_ticks: int, duration_ticks: int, fps: float) -> dict:
    return {
        "OTIO_SCHEMA": "TimeRange.1",
        "start_time": _otio_time(start_ticks, fps),
        "duration": _otio_time(duration_ticks, fps),
    }


def _otio_clip(project, clip) -> dict:
    fps = _fps(project)
    asset = project.assets.get(clip.asset_id)
    metadata = {"agentcut": {"clip": clip.model_dump(mode="json")}}
    if clip.text is not None or asset is None:
        reference = {"OTIO_SCHEMA": "MissingReference.1"}
    else:
        reference = {
            "OTIO_SCHEMA": "ExternalReference.1",
            "target_url": _file_url(asset),
            "name": asset.label,
        }
    name = clip.text.body[:64] if clip.text else (asset.label if asset else clip.id)
    return {
        "OTIO_SCHEMA": "Clip.1",
        "name": name,
        "source_range": _otio_range(clip.source_in_ticks, clip.duration_ticks, fps),
        "media_reference": reference,
        "metadata": metadata,
    }


def build_otio(project) -> dict:
    """The whole timeline as OpenTimelineIO JSON, tracks and gaps included.

    Read-only. Gaps are real ``Gap.1`` children, so a reader that trusts record times sees
    the same edit. Each clip also carries its own AgentCut record under
    ``metadata.agentcut.clip``, so a round trip through this file keeps colour, masks and
    keyframes instead of flattening them to a cut list.
    """
    fps = _fps(project)
    stacks = []
    for track in project.tracks:
        clips = sorted(
            (item for item in project.clips.values() if item.track_id == track.id),
            key=lambda item: (item.position_ticks, item.id),
        )
        children: list[dict] = []
        cursor = 0
        for clip in clips:
            if clip.position_ticks > cursor:
                children.append(
                    {
                        "OTIO_SCHEMA": "Gap.1",
                        "source_range": _otio_range(0, clip.position_ticks - cursor, fps),
                    }
                )
            children.append(_otio_clip(project, clip))
            cursor = clip.position_ticks + clip.duration_ticks
        stacks.append(
            {
                "OTIO_SCHEMA": "Track.1",
                "name": track.name,
                "kind": "Video" if track.kind == "video" else "Audio",
                "metadata": {"agentcut": {"track_id": track.id, "kind": track.kind}},
                "children": children,
            }
        )
    numerator, denominator = _rate(project)
    return {
        "OTIO_SCHEMA": "Timeline.1",
        "name": project.name,
        "global_start_time": _otio_time(0, fps),
        "metadata": {
            "agentcut": {
                "project_id": project.id,
                "frame_rate": {"numerator": numerator, "denominator": denominator},
                "width": project.settings.width,
                "height": project.settings.height,
            }
        },
        "tracks": {
            "OTIO_SCHEMA": "Stack.1",
            "name": "tracks",
            "children": stacks,
        },
    }


def _fcp_time(ticks: int, project) -> str:
    """FCPXML rational time; frame-aligned ticks come out as ``n/dfs`` exactly."""
    numerator, denominator = _rate(project)
    raw_num = int(ticks) * numerator
    raw_den = TIMEBASE * denominator
    divisor = math.gcd(abs(raw_num), raw_den) or 1
    return f"{raw_num // divisor}/{raw_den // divisor}s"


def _has_audio(asset: Asset) -> int:
    verified = asset.verified
    return 1 if asset.kind == "video" and verified is not None and bool(
        getattr(verified, "has_audio", False)
    ) else 0


def build_fcpxml(project) -> dict:
    """Final Cut Pro XML 1.9 for the whole timeline.

    Edits FCPXML could technically say but this exporter does not (speed ramps,
    transitions, text layers) are counted in ``omitted`` with the clip ids that carry
    them. A reader therefore knows the spine is a straight-cut approximation instead of
    discovering a missing shot later.
    """
    numerator, denominator = _rate(project)
    fps_label = f"{numerator}x{denominator}" if denominator != 1 else str(numerator)
    width, height = project.settings.width, project.settings.height
    frame_duration = f"1/{numerator}s" if denominator == 1 else f"{denominator}/{numerator}s"
    resources = [
        f'<format id="r1" name="FFVideoFormat{height}p{fps_label}" '
        f'frameDuration="{frame_duration}" width="{width}" height="{height}"/>'
    ]
    assets: dict[str, str] = {}
    omitted: list[dict] = []
    spine: list[str] = []
    cursor = 0
    end = 0
    for track in project.tracks:
        if track.kind != "video":
            continue
        clips = sorted(
            (item for item in project.clips.values() if item.track_id == track.id),
            key=lambda item: (item.position_ticks, item.id),
        )
        def omit(clip, reason: str) -> None:
            """Keep the record time honest: an omitted clip stays a gap of its own length."""
            nonlocal cursor, end
            omitted.append({"clip_id": clip.id, "reason": reason})
            if clip.position_ticks > cursor:
                cursor = clip.position_ticks
            until = clip.position_ticks + clip.duration_ticks
            if until > cursor:
                spine.append(
                    f'<gap name="略去" offset="{_fcp_time(cursor, project)}" '
                    f'duration="{_fcp_time(until - cursor, project)}"/>'
                )
                cursor = until
                end = max(end, cursor)

        for clip in clips:
            asset = project.assets.get(clip.asset_id)
            if clip.text is not None or asset is None:
                omit(clip, "文字层不进 FCPXML 的 spine")
                continue
            if clip.speed_percent != 100:
                omit(clip, "变速要 timeMap，这一档不写")
                continue
            if clip.transition_in is not None:
                omitted.append({"clip_id": clip.id, "reason": "转场要 transition 资源，这一档不写"})
            if clip.position_ticks > cursor:
                spine.append(
                    f'<gap name="空隙" offset="{_fcp_time(cursor, project)}" '
                    f'duration="{_fcp_time(clip.position_ticks - cursor, project)}"/>'
                )
            ref = assets.get(asset.id)
            if ref is None:
                ref = f"a{len(assets) + 1}"
                assets[asset.id] = ref
                duration = asset.duration_ticks or clip.source_in_ticks + clip.duration_ticks
                resources.append(
                    f'<asset id="{ref}" name={quoteattr(asset.label)} start="0s" '
                    f'duration="{_fcp_time(int(duration), project)}" hasVideo="1" '
                    f'hasAudio="{_has_audio(asset)}" format="r1">'
                    f'<media-rep kind="original-media" '
                    f'src={quoteattr(_file_url(asset))}/></asset>'
                )
            spine.append(
                f'<asset-clip ref="{ref}" offset="{_fcp_time(clip.position_ticks, project)}" '
                f'start="{_fcp_time(clip.source_in_ticks, project)}" '
                f'duration="{_fcp_time(clip.duration_ticks, project)}" '
                f'name={quoteattr(asset.label)}/>'
            )
            cursor = clip.position_ticks + clip.duration_ticks
            end = max(end, cursor)
    text = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n'
        f'<fcpxml version="1.9">\n<resources>\n{"".join(resources)}\n</resources>\n'
        '<library><event name="AgentCut"><project name='
        f"{quoteattr(project.name)}><sequence format=\"r1\" "
        f'duration="{_fcp_time(end, project)}" tcStart="0s" tcFormat="NDF"><spine>\n'
        f'{"".join(spine)}\n</spine></sequence></project></event></library>\n</fcpxml>\n'
    )
    return {
        "xml": text,
        "duration_ticks": end,
        "frame_rate": fps_label,
        "assets": [{"asset_id": asset_id, "ref": ref} for asset_id, ref in assets.items()],
        "omitted": omitted,
        "complete": not omitted,
    }


def _snap(ticks: float, project) -> int:
    frame = project.settings.frame_ticks
    return int(round(ticks / frame)) * frame


def _basename(url: str) -> str:
    parsed = urlparse(url)
    name = unquote(parsed.path if parsed.scheme else url).replace("\\", "/")
    return name.rsplit("/", 1)[-1]


def _clock(value: dict | None) -> tuple[float, float]:
    if not isinstance(value, dict):
        return 0.0, 0.0
    rate = float(value.get("rate") or 0)
    return float(value.get("value") or 0), rate


def _range_seconds(item: dict) -> tuple[float, float]:
    span = item.get("source_range") or {}
    start, start_rate = _clock(span.get("start_time"))
    duration, duration_rate = _clock(span.get("duration"))
    start_sec = start / start_rate if start_rate else 0.0
    duration_sec = duration / duration_rate if duration_rate else 0.0
    return start_sec, duration_sec


def otio_import_plan(project, document: dict) -> dict:
    """Turn an OTIO timeline into ordinary commands, or refuse it by name.

    Nothing is written here. The caller reviews ``commands`` and submits them through the
    same ``/edits`` path people use, so an imported cut is one revision and undoes in one
    step. Media is matched by file name against assets this engine already verified; a
    name that matches nothing (or two different assets) is refused instead of guessed.
    """
    if not isinstance(document, dict):
        raise EditorError("OTIO_UNSUPPORTED", "an OTIO document must be a JSON object", 422)
    schema = str(document.get("OTIO_SCHEMA") or "")
    if not schema.startswith("Timeline."):
        raise EditorError(
            "OTIO_UNSUPPORTED",
            "this JSON is not an OpenTimelineIO timeline (expected OTIO_SCHEMA Timeline.1)",
            422,
            found=schema or None,
        )
    stack = document.get("tracks") or {}
    tracks = stack.get("children") if isinstance(stack, dict) else None
    if not isinstance(tracks, list) or not tracks:
        raise EditorError("OTIO_EMPTY", "this timeline has no tracks", 422)
    video_tracks = [track for track in project.tracks if track.kind == "video"]
    audio_tracks = [track for track in project.tracks if track.kind == "audio"]
    wanted_video = [track for track in tracks if track.get("kind") == "Video"]
    wanted_audio = [track for track in tracks if track.get("kind") == "Audio"]
    unknown = [
        {"name": track.get("name"), "kind": track.get("kind")}
        for track in tracks
        if track.get("kind") not in {"Video", "Audio"}
    ]
    if unknown:
        raise EditorError(
            "OTIO_UNSUPPORTED",
            "only Video and Audio tracks are imported; other track kinds are refused by name",
            422,
            tracks=unknown,
        )
    if len(wanted_video) > len(video_tracks) or len(wanted_audio) > len(audio_tracks):
        raise EditorError(
            "OTIO_TRACK_COUNT",
            "this timeline has more tracks than the project: add tracks first, then import",
            422,
            wanted={"video": len(wanted_video), "audio": len(wanted_audio)},
            available={"video": len(video_tracks), "audio": len(audio_tracks)},
        )

    by_name: dict[str, list[Asset]] = {}
    for asset in project.assets.values():
        path = _media_path(asset)
        names = {asset.label.lower()}
        if path:
            names.add(_basename(path).lower())
        for name in names:
            by_name.setdefault(name, []).append(asset)

    commands: list[dict] = []
    report_tracks = []
    unmatched: list[dict] = []
    ambiguous: list[dict] = []
    range_problems: list[dict] = []
    dropped = {"transitions": 0, "markers": 0, "effects": 0}
    imported_clips = 0
    imported_text = 0
    gaps = 0

    for otio_track in tracks:
        kind = otio_track.get("kind")
        if kind == "Video":
            pool = video_tracks
            index = wanted_video.index(otio_track)
        else:
            pool = audio_tracks
            index = wanted_audio.index(otio_track)
        track = pool[index]
        for clip in sorted(
            (item for item in project.clips.values() if item.track_id == track.id),
            key=lambda item: item.id,
        ):
            commands.append({"op": "clip.remove", "clip_id": clip.id})
        cursor = 0.0
        count = 0
        for child in otio_track.get("children") or []:
            child_schema = str(child.get("OTIO_SCHEMA") or "")
            if child_schema.startswith("Gap."):
                _, gap_sec = _range_seconds(child)
                cursor += gap_sec
                gaps += 1
                continue
            if child_schema.startswith("Transition."):
                dropped["transitions"] += 1
                continue
            if not child_schema.startswith("Clip."):
                raise EditorError(
                    "OTIO_UNSUPPORTED",
                    "only Clip, Gap and Transition children are understood in a track",
                    422,
                    track=otio_track.get("name"),
                    found=child_schema or None,
                )
            if child.get("markers"):
                dropped["markers"] += len(child["markers"])
            if child.get("effects"):
                dropped["effects"] += len(child["effects"])
            start_sec, duration_sec = _range_seconds(child)
            record = ((child.get("metadata") or {}).get("agentcut") or {}).get("clip")
            base: dict
            if isinstance(record, dict):
                base = dict(record)
                for key in ("track_id", "position_ticks", "id"):
                    base.pop(key, None)
            else:
                reference = child.get("media_reference") or {}
                url = reference.get("target_url") or ""
                name = _basename(url).lower() if url else ""
                matches = by_name.get(name, []) if name else []
                if not matches:
                    unmatched.append({"name": child.get("name"), "target_url": url or None})
                    continue
                if len(matches) > 1:
                    ambiguous.append(
                        {"name": child.get("name"), "candidates": [item.id for item in matches]}
                    )
                    continue
                base = {"asset_id": matches[0].id}
            position_ticks = _snap(cursor * TIMEBASE, project)
            source_in = _snap(start_sec * TIMEBASE, project)
            duration = _snap(duration_sec * TIMEBASE, project)
            asset = project.assets.get(str(base.get("asset_id") or ""))
            if asset is not None and asset.duration_ticks:
                room = max(0, int(asset.duration_ticks) - source_in)
                if duration > room:
                    duration = _snap(room, project)
                if duration <= 0:
                    range_problems.append(
                        {
                            "name": child.get("name"),
                            "reason": "the source window starts at or past this asset's end",
                            "asset_id": asset.id,
                        }
                    )
                    continue
            if duration <= 0 or position_ticks < 0 or source_in < 0:
                range_problems.append({"name": child.get("name"), "reason": "invalid range"})
                continue
            item = Clip.model_validate(
                {
                    **base,
                    "id": f"otio_{uuid.uuid4().hex[:12]}",
                    "track_id": track.id,
                    "position_ticks": position_ticks,
                    "source_in_ticks": source_in,
                    "duration_ticks": duration,
                }
            )
            commands.append({"op": "clip.add", "clip": item.model_dump(mode="json")})
            if item.text is not None:
                imported_text += 1
            imported_clips += 1
            count += 1
            cursor += duration_sec
        report_tracks.append(
            {
                "track_id": track.id,
                "name": otio_track.get("name") or track.name,
                "kind": "video" if kind == "Video" else "audio",
                "clips": count,
            }
        )

    if unmatched:
        raise EditorError(
            "OTIO_MEDIA_UNMATCHED",
            "some clips point at files this project has not imported; nothing was planned. "
            "Import those files first, then run the plan again.",
            422,
            unmatched=unmatched,
        )
    if ambiguous:
        raise EditorError(
            "OTIO_MEDIA_AMBIGUOUS",
            "a file name matches more than one asset here; rename one or pick by hand",
            422,
            ambiguous=ambiguous,
        )
    if range_problems:
        raise EditorError(
            "OTIO_CLIP_RANGE",
            "some clips do not fit their source media; nothing was planned",
            422,
            clips=range_problems,
        )
    if not imported_clips:
        raise EditorError("OTIO_EMPTY", "this timeline has no clips to import", 422)
    return {
        "commands": commands,
        "tracks": report_tracks,
        "clips": imported_clips,
        "text_clips": imported_text,
        "gaps": gaps,
        "dropped": dropped,
        "revision": project.revision,
    }


# ---------------------------------------------------------------------------
# 1.292：把别人的工程读进来 —— FCPXML / FCP7(Premiere) XML / EDL / 剪映草稿
#
# 为什么这一族是差异化的正面：Agent 要「模仿剪辑」，最省力的路不是让它在文档里重新
# 发明一遍别人剪好的节奏，而是把那份节奏直接读成一条可审的计划。所以这四个读法遵守
# 同一条纪律：
#   ① 只交普通命令（清空它接管的轨道 + 逐段 ``clip.add``），apply 走同一条 ``/edits``，
#      一次一个 revision —— 这里没有第二条写入路径；
#   ② 素材只按文件名对到**本机已核过**的媒体夹里；对不上、对上一对二，都点名拒绝，不猜；
#   ③ 这份格式里根本没有的东西（调色、遮罩、变速曲线、插件）逐类点名报在 ``omitted`` 里，
#      并置 ``complete=False`` —— 宁可说「这一段我没搬过来」，也不悄悄交出一半的时间线。
# 一个名字（``_ImportLedger``）决定「这一段能不能说、怎么说、说不成记在哪」。
# ---------------------------------------------------------------------------


def _assets_by_name(project) -> dict[str, list[Asset]]:
    """One place decides how a name written in another tool finds an asset here."""
    by_name: dict[str, list[Asset]] = {}
    for asset in project.assets.values():
        path = _media_path(asset)
        names = {asset.label.lower()}
        if path:
            names.add(_basename(path).lower())
        for name in names:
            by_name.setdefault(name, []).append(asset)
    return by_name


class _ImportLedger:
    """Accumulates ordinary ``clip.add`` commands plus an honest account of what was left out.

    Every interchange reader fills this instead of repeating the matching, the source-window
    clamp and the refusal bookkeeping — those three are where a silent guess would hide.
    """

    def __init__(self, project, source: str) -> None:
        self.project = project
        self.source = source
        self.by_name = _assets_by_name(project)
        self.commands: list[dict] = []
        self.tracks: list[dict] = []
        self.omitted: list[dict] = []
        self.unmatched: list[dict] = []
        self.ambiguous: list[dict] = []
        self.bad_range: list[dict] = []
        self.clips = 0
        self.text_clips = 0
        self.gaps = 0
        self._seen_tracks: set[str] = set()

    # —— 记账 ————————————————————————————————————————————————
    def omit(self, kind: str, reason: str, **what) -> None:
        kept = {key: value for key, value in what.items() if value is not None}
        self.omitted.append({"kind": kind, "reason": reason, **kept})

    def clear_track(self, track) -> None:
        """The reader owns this track's contents: remove what is there before adding."""
        if track.id in self._seen_tracks:
            return
        self._seen_tracks.add(track.id)
        for clip in sorted(
            (item for item in self.project.clips.values() if item.track_id == track.id),
            key=lambda item: item.id,
        ):
            self.commands.append({"op": "clip.remove", "clip_id": clip.id})
        self.tracks.append({"track_id": track.id, "name": track.name,
                            "kind": track.kind, "clips": 0})

    def _row(self, track) -> dict | None:
        for row in self.tracks:
            if row["track_id"] == track.id:
                return row
        return None

    def gap(self, track, seconds: float) -> None:
        """A gap is a hole, not a clip: it counts, and it never inflates a track's clip count."""
        del seconds
        self.gaps += 1
        row = self._row(track) if track is not None else None
        if row is not None:
            row.setdefault("gaps", 0)
            row["gaps"] += 1

    # —— 那一段能不能说 ——
    def add(self, track, *, name: str, seconds: float, duration: float,
            source_in: float = 0.0, asset_name: str | None = None,
            text: str | None = None) -> bool:
        """Queue one clip on ``track``; return False when it is refused by name instead."""
        if duration <= 0 or seconds < 0:
            self.bad_range.append({"name": name, "reason": "invalid range",
                                   "start": seconds, "duration": duration})
            return False
        base: dict = {}
        if text is not None:
            base = {"text": {"body": text}}
        else:
            key = (asset_name or name or "").lower()
            if not key:
                self.unmatched.append({"name": name, "reason": "no media name in this item"})
                return False
            matches = self.by_name.get(key, [])
            if not matches:
                self.unmatched.append({"name": name, "media": asset_name or name})
                return False
            if len(matches) > 1:
                self.ambiguous.append({"name": name, "media": asset_name or name,
                                       "candidates": [item.id for item in matches]})
                return False
            asset = matches[0]
            base = {"asset_id": asset.id}
            if asset.duration_ticks:
                start_ticks = int(_snap(source_in * TIMEBASE, self.project))
                room = max(0, int(asset.duration_ticks) - start_ticks)
                if duration * TIMEBASE > room:
                    duration = room / TIMEBASE
        position = _snap(seconds * TIMEBASE, self.project)
        source_in_ticks = _snap(source_in * TIMEBASE, self.project)
        duration_ticks = _snap(duration * TIMEBASE, self.project)
        if duration_ticks <= 0:
            self.bad_range.append({"name": name, "reason": "the source window starts at or past "
                                                           "this asset's end", "start": source_in})
            return False
        item = Clip.model_validate({
            **base,
            "id": f"{self.source}_{uuid.uuid4().hex[:12]}",
            "track_id": track.id,
            "position_ticks": position,
            "source_in_ticks": source_in_ticks,
            "duration_ticks": duration_ticks,
        })
        self.commands.append({"op": "clip.add", "clip": item.model_dump(mode="json")})
        self.clips += 1
        if item.text is not None:
            self.text_clips += 1
        row = self._row(track)
        if row is not None:
            row["clips"] += 1
        return True

    # —— 交账 ——
    def finish(self, *, empty_code: str, unmatched_code: str) -> dict:
        if self.unmatched:
            raise EditorError(
                unmatched_code,
                "some items point at files this project has not imported; nothing was planned. "
                "Import those files first, then run the plan again.",
                422,
                items=self.unmatched,
            )
        if self.ambiguous:
            raise EditorError(
                "INTERCHANGE_MEDIA_AMBIGUOUS",
                "a media name matches more than one asset here; rename one or pick by hand",
                422,
                items=self.ambiguous,
            )
        if self.bad_range:
            raise EditorError(
                "INTERCHANGE_CLIP_RANGE",
                "some items do not fit their source media; nothing was planned",
                422,
                items=self.bad_range,
            )
        if not self.clips:
            raise EditorError(empty_code, "this document has no clips that can be imported", 422)
        return {
            "commands": self.commands,
            "tracks": self.tracks,
            "clips": self.clips,
            "text_clips": self.text_clips,
            "gaps": self.gaps,
            "omitted": self.omitted,
            "complete": not self.omitted,
            "revision": self.project.revision,
        }


def _iso_seconds(value: str | None) -> float:
    """FCPXML writes rational seconds: ``1s``, ``1001/30000s``, ``PT1.5S``. None when unreadable."""
    if not value:
        return 0.0
    text = value.strip()
    if text.endswith("s"):
        text = text[:-1]
    if "/" in text:
        head, _, tail = text.partition("/")
        try:
            return float(head) / float(tail)
        except (TypeError, ValueError, ZeroDivisionError):
            raise EditorError("FCPXML_TIMECODE",
                              f"cannot read this duration: {value!r}", 422) from None
    try:
        return float(text)
    except ValueError:
        raise EditorError("FCPXML_TIMECODE", f"cannot read this duration: {value!r}", 422) from None


def _strip_tag(name: str) -> str:
    return name.rsplit("}", 1)[-1]


_DTD_ENTITY = re.compile(r"<!ENTITY", re.IGNORECASE)
_DTD_EXTERNAL = re.compile(r"<!DOCTYPE[^>]*\b(SYSTEM|PUBLIC)\b", re.IGNORECASE)



def _frames_to_seconds(value: str | None, timebase: int) -> float:
    if timebase <= 0:
        raise EditorError("INTERCHANGE_RATE", "this document declares no usable frame "
                                              "rate", 422)
    return int(value or 0) / timebase


def fcpxml_import_plan(project, document: str) -> dict:
    """Read an FCPXML sequence into ordinary commands, naming what it cannot carry.

    FCPXML is the one interchange with a published DTD that Final Cut, Resolve, Kdenlive,
    Premiere (via export) and Shotcut all write, so it covers the most ground per line of
    parsing. Items are placed by their absolute ``offset`` — no cursor arithmetic, so an
    overlapping ``layer`` cannot drift.
    """
    # The two XML prolog constructs that make a parser do unbounded work are refused before
    # any parsing happens. Each reader names its own code literally: the vocabulary gate
    # follows a code from the raise to the Chinese hint, so a shared helper would hide it.
    if _DTD_ENTITY.search(document):
        raise EditorError("FCPXML_MALFORMED_ENTITIES",
                          "entity declarations are not accepted in an interchange document", 422)
    if _DTD_EXTERNAL.search(document):
        raise EditorError("FCPXML_MALFORMED_EXTERNAL_DTD",
                          "this document refers to an external DTD; save it as a standalone "
                          "file and try again", 422)
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as error:
        raise EditorError("FCPXML_MALFORMED",
                          f"this is not well-formed XML: {error}", 422) from None
    if _strip_tag(root.tag) != "fcpxml":
        raise EditorError("FCPXML_MALFORMED", "the root element is not <fcpxml>", 422,
                          found=root.tag)
    ledger = _ImportLedger(project, "fcpxml")
    resources = root.find("resources")
    assets: dict[str, dict] = {}
    formats: dict[str, dict] = {}
    compound: set[str] = set()
    for node in resources if resources is not None else []:
        tag = _strip_tag(node.tag)
        if tag == "asset":
            assets[node.get("id") or ""] = dict(node.attrib)
            if any(_strip_tag(child.tag) == "spine" for child in node):
                compound.add(node.get("id") or "")
        elif tag == "format":
            formats[node.get("id") or ""] = dict(node.attrib)
    sequences = [node for node in root.iter() if _strip_tag(node.tag) == "sequence"]
    if not sequences:
        raise EditorError("FCPXML_EMPTY", "this document has no <sequence>", 422)
    if len(sequences) > 1:
        ledger.omit("sequence", "only the first sequence is read", count=len(sequences) - 1)
    sequence = sequences[0]
    spine = next((node for node in sequence if _strip_tag(node.tag) == "spine"), None)
    if spine is None:
        raise EditorError("FCPXML_EMPTY", "this sequence has no <spine>", 422)

    video_tracks = [track for track in project.tracks if track.kind == "video"]
    audio_tracks = [track for track in project.tracks if track.kind == "audio"]
    layers = sorted({int(item.get("layer") or 1)
                     for item in spine if _strip_tag(item.tag) in {"asset-clip", "asset-ref",
                                                                   "title", "map"}})
    if len(layers) > len(video_tracks):
        raise EditorError("FCPXML_TRACK_COUNT",
                          "this sequence has more picture layers than the project: add tracks "
                          "first, then import", 422,
                          wanted=len(layers), available=len(video_tracks))
    lane_count = sum(1 for item in spine if _strip_tag(item.tag) == "lane")
    if lane_count > len(audio_tracks):
        raise EditorError("FCPXML_TRACK_COUNT",
                          "this sequence has more audio lanes than the project: add tracks "
                          "first, then import", 422,
                          wanted=lane_count, available=len(audio_tracks))

    for order, layer in enumerate(layers):
        track = video_tracks[order]
        ledger.clear_track(track)
        items = [item for item in spine
                 if _strip_tag(item.tag) in {"asset-clip", "asset-ref", "title", "map"}
                 and int(item.get("layer") or 1) == layer]
        for item in sorted(items, key=lambda node: _iso_seconds(node.get("offset"))):
            tag = _strip_tag(item.tag)
            for child in item:
                child_tag = _strip_tag(child.tag)
                if child_tag == "speed":
                    ledger.omit("speed", "a speed change is a curve here, not an average rate",
                                at=item.get("offset"))
                elif child_tag in {"effect", "color-board"}:
                    ledger.omit("effect", "colour and plugin effects do not travel in FCPXML",
                                name=child.get("name"))
                elif child_tag == "adjust-volume":
                    ledger.omit("volume", "a keyframed volume is not carried",
                                name=child.get("name"))
                elif child_tag == "alpha":
                    ledger.omit("mask", "a mask shape is not carried", name=child.get("name"))
            if tag == "title":
                body = "".join(node.text or "" for node in item.iter()
                               if _strip_tag(node.tag) == "text")
                ledger.add(track, name=item.get("name") or "title",
                           seconds=_iso_seconds(item.get("offset")),
                           duration=_iso_seconds(item.get("duration")),
                           text=body or (item.get("name") or ""))
                continue
            ref = item.get("ref") or ""
            record = assets.get(ref)
            if record is None:
                ledger.omit("missing-asset", "this item refers to a resource id not in "
                                             "<resources>", ref=ref or None)
                continue
            if ref in compound:
                ledger.omit("compound", "a nested <spine> is a compound clip; it is not "
                                        "flattened here", name=record.get("name"))
                continue
            src = record.get("src") or ""
            ledger.add(track, name=record.get("name") or ref,
                       seconds=_iso_seconds(item.get("offset")),
                       duration=_iso_seconds(item.get("duration")),
                       source_in=_iso_seconds(item.get("start") or record.get("start")),
                       asset_name=_basename(unquote(urlparse(src).path)) if src else None)
        for item in spine:
            if _strip_tag(item.tag) == "gap" and int(item.get("layer") or 1) == layer:
                ledger.gap(track, _iso_seconds(item.get("duration")))
    for lane_order, lane in enumerate(node for node in spine if _strip_tag(node.tag) == "lane"):
        track = audio_tracks[lane_order]
        ledger.clear_track(track)
        for item in sorted((node for node in lane if _strip_tag(node.tag) in {"audio-clip",
                                                                            "asset-clip",
                                                                            "audio-src"}),
                           key=lambda node: _iso_seconds(node.get("offset"))):
            ref = item.get("ref") or ""
            record = assets.get(ref) or {}
            src = record.get("src") or ""
            ledger.add(track, name=record.get("name") or ref,
                       seconds=_iso_seconds(item.get("offset")),
                       duration=_iso_seconds(item.get("duration")),
                       source_in=_iso_seconds(item.get("start") or record.get("start")),
                       asset_name=_basename(unquote(urlparse(src).path)) if src else None)
    for node in root.iter():
        if _strip_tag(node.tag) in {"transition"}:
            ledger.omit("transition", "a transition is not carried; re-add it here",
                        name=node.get("name"))
    return ledger.finish(empty_code="FCPXML_EMPTY", unmatched_code="FCPXML_MEDIA_UNMATCHED")


def fcp7xml_import_plan(project, document: str) -> dict:
    """Read an FCP7 / Premiere «Export XML» (xmeml) sequence into ordinary commands.

    Adobe documents this as the interchange with FCP7, and OTIO's own ``fcp_xml`` adapter is
    built on the same reading, so the shape is stable: frame integers, one ``<track>`` per
    track, ``<in>/<out>`` for the source window and ``<start>/<end>`` for the record window.
    """
    if _DTD_ENTITY.search(document):
        raise EditorError("XMEML_MALFORMED_ENTITIES",
                          "entity declarations are not accepted in an interchange document", 422)
    if _DTD_EXTERNAL.search(document):
        raise EditorError("XMEML_MALFORMED_EXTERNAL_DTD",
                          "this document refers to an external DTD; save it as a standalone "
                          "file and try again", 422)
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError as error:
        raise EditorError("XMEML_MALFORMED",
                          f"this is not well-formed XML: {error}", 422) from None
    if _strip_tag(root.tag) != "xmeml":
        raise EditorError("XMEML_MALFORMED", "the root element is not <xmeml>", 422,
                          found=root.tag)
    ledger = _ImportLedger(project, "xmeml")
    sequence = next((node for node in root.iter() if _strip_tag(node.tag) == "sequence"), None)
    if sequence is None:
        raise EditorError("XMEML_EMPTY", "this document has no <sequence>", 422)
    timebase = 0
    rate = next((node for node in sequence.iter() if _strip_tag(node.tag) == "rate"), None)
    if rate is not None:
        base = next((node for node in rate if _strip_tag(node.tag) == "timebase"), None)
        if base is not None and base.text:
            timebase = int(float(base.text))
    if timebase <= 0:
        raise EditorError("XMEML_RATE", "this sequence declares no <timebase>; set the frame "
                                        "rate in the source application and export again", 422)
    files: dict[str, str] = {}
    for node in root.iter():
        if _strip_tag(node.tag) != "file":
            continue
        path = next((child.text for child in node
                     if _strip_tag(child.tag) in {"pathurl", "filepath"} and child.text), None)
        if path:
            files[node.get("id") or ""] = path
    pools = {"video": [track for track in project.tracks if track.kind == "video"],
             "audio": [track for track in project.tracks if track.kind == "audio"]}
    # Adobe writes <media><video><track>, older FCP7 writers put <video> straight under
    # <sequence>; both are read, and only the direct children of that one container count,
    # so a nested sequence's tracks cannot be mistaken for this one's.
    container = next((node for node in sequence if _strip_tag(node.tag) == "media"), sequence)
    for group in container:
        group_tag = _strip_tag(group.tag)
        if group_tag not in pools:
            continue
        pool = pools[group_tag]
        tracks = [node for node in group if _strip_tag(node.tag) == "track"]
        if len(tracks) > len(pool):
            raise EditorError("XMEML_TRACK_COUNT",
                              f"this sequence has more {group_tag} tracks than the project: add "
                              "tracks first, then import", 422,
                              wanted=len(tracks), available=len(pool))
        for order, track_node in enumerate(tracks):
            track = pool[order]
            ledger.clear_track(track)
            for item in track_node:
                tag = _strip_tag(item.tag)
                if tag == "gapitem":
                    ledger.gap(track, _frames_to_seconds(item.findtext("end"), timebase)
                               - _frames_to_seconds(item.findtext("start"), timebase))
                    continue
                if tag != "clipitem":
                    continue
                for child in item:
                    child_tag = _strip_tag(child.tag)
                    if child_tag == "rate":
                        ledger.omit("speed", "a stretched clip is a curve here",
                                    name=item.get("name"))
                    elif child_tag in {"effect", "filter"}:
                        ledger.omit("effect", "plugin effects do not travel in this format",
                                    name=child.get("name") or child.findtext("effectid"))
                file_node = next((child for child in item if _strip_tag(child.tag) == "file"), None)
                if file_node is None:
                    ledger.omit("generator", "a clip with no <file> is generated in the source "
                                             "app", name=item.get("name"))
                    continue
                ref = file_node.get("id") or ""
                path = files.get(ref) or (file_node.text or "")
                start = _frames_to_seconds(item.findtext("start"), timebase)
                end = _frames_to_seconds(item.findtext("end"), timebase)
                ledger.add(track, name=item.get("name") or ref,
                           seconds=start,
                           duration=end - start,
                           source_in=_frames_to_seconds(item.findtext("in"), timebase),
                           asset_name=_basename(unquote(urlparse(path).path)) if path else None)
    return ledger.finish(empty_code="XMEML_EMPTY", unmatched_code="XMEML_MEDIA_UNMATCHED")


_EDL_EVENT = re.compile(
    r"^(?P<event>\d{3})\s+(?P<reel>\S+)\s+(?P<channel>[AB][AB]?|V)\s+"
    r"(?P<kind>[VCWD])\s+(?P<src_in>\d{2}:\d{2}:\d{2}[:;]\d{2})\s+"
    r"(?P<src_out>\d{2}:\d{2}:\d{2}[:;]\d{2})\s+"
    r"(?P<rec_in>\d{2}:\d{2}:\d{2}[:;]\d{2})\s+"
    r"(?P<rec_out>\d{2}:\d{2}:\d{2}[:;]\d{2})(?:\s+(?P<trail>.*))?$"
)
_EDL_FROM = re.compile(r"^\*\s+FROM CLIP NAME:\s*(.+?)\s*$", re.IGNORECASE)


def _tc_seconds(frame: str, fps: int) -> float:
    """CMX3600 timecode is HH:MM:SS:FF; a ';' in the frames field means drop-frame."""
    parts = frame.split(":")
    if fps <= 0:
        raise EditorError("EDL_RATE", "this list declares no usable frame rate", 422)
    if parts[3].startswith(";"):
        raise EditorError("EDL_DROP_FRAME", "drop-frame timecode is not read yet; export this "
                                            "list as NON-DROP FRAME", 422)
    whole = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return whole + int(parts[3]) / fps


def edl_import_plan(project, document: str) -> dict:
    """Read a CMX3600 list back: the same narrow claim its writer makes, in the other direction.

    Straight cuts on integer, non-drop frames are what an EDL actually carries. A dissolve,
    a wipe or a drop-frame list is refused by name rather than approximated — the writer of
    this format refuses them too, so a reader that guessed would accept its own refusal.
    """
    numerator, denominator = _rate_numbers(project)
    if numerator % denominator:
        raise EditorError("EDL_RATE", "this project runs at a fractional frame rate; drop-frame "
                                      "arithmetic is not read yet", 422,
                          found=f"{numerator}/{denominator}")
    fps = numerator // denominator
    ledger = _ImportLedger(project, "edl")
    video_tracks = [track for track in project.tracks if track.kind == "video"]
    audio_tracks = [track for track in project.tracks if track.kind == "audio"]
    names: dict[str, str] = {}
    current_reel = ""
    channels = {"video": [], "audio": []}
    events: list[dict] = []
    for raw in document.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("TITLE:"):
            continue
        if line.upper().startswith("FCM:"):
            if "DROP" in line.upper() and "NON" not in line.upper():
                raise EditorError("EDL_DROP_FRAME", "this list is drop-frame; export it as "
                                                    "NON-DROP FRAME", 422, found=line)
            continue
        named = _EDL_FROM.match(line)
        if named:
            if current_reel:
                names[current_reel] = named.group(1)
            continue
        matched = _EDL_EVENT.match(line)
        if not matched:
            continue
        event = matched.groupdict()
        current_reel = event["reel"]
        events.append(event)
    if not events:
        raise EditorError("EDL_EMPTY", "no CMX3600 events were found in this list", 422)
    for event in events:
        kind = event["kind"].upper()
        if kind in {"D", "W", "K"}:
            ledger.omit("transition", "a dissolve / wipe / key event is not read",
                        event=event["event"], kind=kind)
            continue
        bucket = "video" if event["channel"] == "V" else "audio"
        if event["channel"] not in channels[bucket]:
            channels[bucket].append(event["channel"])
    if len(channels["video"]) > len(video_tracks) or len(channels["audio"]) > len(audio_tracks):
        raise EditorError("EDL_TRACK_COUNT",
                          "this list has more channels than the project has tracks: add tracks "
                          "first, then import", 422,
                          wanted={"video": len(channels["video"]), "audio": len(channels["audio"])},
                          available={"video": len(video_tracks), "audio": len(audio_tracks)})
    for bucket, pool in (("video", video_tracks), ("audio", audio_tracks)):
        for channel in channels[bucket]:
            ledger.clear_track(pool[channels[bucket].index(channel)])
    for event in events:
        if event["kind"].upper() in {"D", "W", "K"}:
            continue
        bucket = "video" if event["channel"] == "V" else "audio"
        pool = video_tracks if bucket == "video" else audio_tracks
        track = pool[channels[bucket].index(event["channel"])]
        src_in = _tc_seconds(event["src_in"], fps)
        src_out = _tc_seconds(event["src_out"], fps)
        rec_in = _tc_seconds(event["rec_in"], fps)
        if src_out <= src_in:
            ledger.bad_range.append({"event": event["event"], "reason": "source out is at or "
                                                                       "before source in"})
            continue
        ledger.add(track, name=event["event"],
                   seconds=rec_in,
                   duration=src_out - src_in,
                   source_in=src_in,
                   asset_name=names.get(event["reel"]) or event["reel"])
    return ledger.finish(empty_code="EDL_EMPTY", unmatched_code="EDL_MEDIA_UNMATCHED")


_JIANYYING_ENCRYPTED = ("encrypted", "draft_content.json is encrypted")


def jianying_import_plan(project, document) -> dict:
    """Read a 剪映 / CapCut ``draft_content.json`` (the plain-text ones) into ordinary commands.

    Drafts written by 剪映 6 and later are encrypted; this reader does not try to decrypt them
    and says so by name. What it does read is the plaintext shape every community writer uses:
    microsecond ranges, ``material_id`` -> ``materials.*``, per-track segment lists.
    """
    if isinstance(document, (str, bytes)):
        try:
            document = json.loads(document)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise EditorError(
                "JIANYING_ENCRYPTED",
                "this draft is not JSON text; 剪映 6+ encrypts draft_content.json and this "
                "reader does not. Export an EDL, FCPXML or OTIO from the source app instead",
                422,
            ) from None
    if not isinstance(document, dict):
        raise EditorError("JIANYING_MALFORMED", "a draft must be a JSON object", 422)
    if document.get("encrypted"):
        raise EditorError("JIANYING_ENCRYPTED", "this draft declares itself encrypted; nothing "
                                                "was read", 422)
    tracks = document.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        raise EditorError("JIANYING_EMPTY", "this draft has no tracks", 422)
    materials = document.get("materials") or {}
    by_material: dict[str, dict] = {}
    for group in ("videos", "audios", "texts", "flames"):
        for item in materials.get(group) or []:
            if isinstance(item, dict) and item.get("id"):
                by_material[str(item["id"])] = item
    ledger = _ImportLedger(project, "jianying")
    pools = {"video": [track for track in project.tracks if track.kind == "video"],
             "audio": [track for track in project.tracks if track.kind == "audio"]}
    wanted = {"video": 0, "audio": 0}
    for track in tracks:
        kind = str(track.get("type") or "").lower()
        if kind in {"video", "audio"}:
            wanted[kind] += 1
    if wanted["video"] > len(pools["video"]) or wanted["audio"] > len(pools["audio"]):
        raise EditorError("JIANYING_TRACK_COUNT",
                          "this draft has more tracks than the project: add tracks first, then "
                          "import", 422,
                          wanted=wanted,
                          available={"video": len(pools["video"]), "audio": len(pools["audio"])})
    seen = {"video": 0, "audio": 0}
    for track in tracks:
        kind = str(track.get("type") or "").lower()
        if kind not in pools:
            ledger.omit("track", "a sticker / caption style track is not read", kind=kind)
            continue
        target = pools[kind][seen[kind]]
        seen[kind] += 1
        ledger.clear_track(target)
        for segment in track.get("segments") or []:
            if not isinstance(segment, dict):
                continue
            material = by_material.get(str(segment.get("material_id") or "")) or {}
            target_range = segment.get("target_timerange") or {}
            source_range = segment.get("source_timerange") or {}
            start = float(target_range.get("start") or 0) / 1_000_000
            duration = float(target_range.get("duration") or 0) / 1_000_000
            source_in = float(source_range.get("start") or 0) / 1_000_000
            if segment.get("speed", 1) not in (1, 1.0, None):
                ledger.omit("speed", "a draft speed is folded into the source window, not a "
                                     "curve", at=start)
            if material.get("animations"):
                ledger.omit("keyframes", "draft keyframes are not carried",
                            name=material.get("path"))
            body = material.get("content")
            path = material.get("path") or ""
            if isinstance(path, dict):
                path = path.get("resource") or ""
            if body and kind == "video":
                ledger.add(target, name=str(segment.get("id") or "text"), seconds=start,
                           duration=duration, text=str(body))
                continue
            ledger.add(target, name=str(segment.get("id") or "clip"), seconds=start,
                       duration=duration, source_in=source_in,
                       asset_name=_basename(unquote(urlparse(str(path)).path)) if path else None)
    return ledger.finish(empty_code="JIANYING_EMPTY", unmatched_code="JIANYING_MEDIA_UNMATCHED")


# ---------------------------------------------------------------------------
# 一个入口，先认格式再谈导入
#
# 「适配大多数工程文件格式」对 Agent 有用的形状是：交一份路径或一段文本过来，引擎说得出
# 这是哪一种、能搬什么、搬不了的是哪几段——而不是要 Agent 先自己猜对参数名。所以这里只有
# 一个判断（detect_interchange）和一个分发（read_interchange），四个读法共用同一条
# 「只交普通命令」的出口。
# ---------------------------------------------------------------------------

def detect_interchange(text: str) -> str:
    """Name the format of an interchange document, or refuse to guess.

    Each answer is decided on something only that format writes — an OTIO schema key, a
    root element, a CMX3600 event line, a draft's ``tracks`` + ``materials`` pair — so two
    formats can never claim the same bytes.
    """
    head = text.lstrip()
    if head.startswith("{") or head.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            raise EditorError(
                "INTERCHANGE_UNKNOWN",
                "this looks like JSON but does not parse; it may be an encrypted 剪映 draft "
                "(剪映 6+ encrypts draft_content.json) — export OTIO, FCPXML or an EDL instead",
                422,
            ) from None
        if isinstance(parsed, dict):
            schema = str(parsed.get("OTIO_SCHEMA") or "")
            if schema.startswith("Timeline."):
                return "otio"
            if isinstance(parsed.get("tracks"), list) and "materials" in parsed:
                return "jianying"
        raise EditorError("INTERCHANGE_UNKNOWN",
                          "this JSON is not a timeline this engine reads", 422,
                          keys=sorted(parsed)[:8] if isinstance(parsed, dict) else None)
    if "<" in head[:400]:
        probe = head[:4000].lower()
        if "<fcpxml" in probe:
            return "fcpxml"
        if "<xmeml" in probe:
            return "xmeml"
    lines = [line for line in text.splitlines() if line.strip()]
    events = [line for line in lines if _EDL_EVENT.match(line.strip())]
    if events and len(events) >= max(1, len(lines) // 4):
        return "edl"
    raise EditorError(
        "INTERCHANGE_UNKNOWN",
        "cannot tell what this document is; pass format=otio|fcpxml|xmeml|edl|jianying "
        "to say so explicitly",
        422,
        first=(lines[0][:60] if lines else None),
    )


def read_interchange(project, document, format: str | None = None) -> dict:
    """Plan any supported interchange document as ordinary commands.

    Returns the plan plus the format it settled on, so a caller can see what was read
    rather than trusting a parameter. Nothing is written here.
    """
    if isinstance(document, dict):
        text = json.dumps(document)
        guessed = "otio" if str(document.get("OTIO_SCHEMA") or "").startswith("Timeline.") \
            else "jianying"
    else:
        text = document
        guessed = ""
    chosen = format or guessed or detect_interchange(text)
    readers = {
        "otio": lambda: otio_import_plan(project, json.loads(text) if isinstance(
            document, str) else document),
        "fcpxml": lambda: fcpxml_import_plan(project, text),
        "xmeml": lambda: fcp7xml_import_plan(project, text),
        "edl": lambda: edl_import_plan(project, text),
        "jianying": lambda: jianying_import_plan(project, text if isinstance(document, str)
                                                 else document),
    }
    if chosen not in readers:
        raise EditorError("INTERCHANGE_UNKNOWN",
                          f"this engine does not read {chosen!r}", 422,
                          supported=sorted(readers))
    plan = readers[chosen]()
    return {"format": chosen, **plan}


