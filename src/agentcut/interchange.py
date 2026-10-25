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

import math
import re
import uuid
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
