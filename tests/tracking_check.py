"""Mask tracking against synthetic ground truth: a known trajectory must come back out of the
tracker, a vanished target must be reported as lost, and the exported mask must follow the object.

The source is generated here, pixel by pixel, so the analytic centre of the moving square is exact.
"""

import hashlib
import math
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import (
    Clip,
    EditBatch,
    EditorError,
    FrameRate,
    Project,
    VerifiedMedia,
)
from agentcut.http_api import create_app
from agentcut.media import MediaService
from agentcut.render import compile_render_plan
from agentcut.timeline import apply_commands, validate_timeline
from agentcut.tracking import decode_luma, track_box, track_mask

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
WIDTH, HEIGHT = 320, 180
FPS = 30
SIZE = 22
BOX = (0.16, 0.24)


def path_at(seconds: float) -> tuple[float, float]:
    phase = seconds / 3.0
    return 0.25 + 0.5 * phase, 0.5 + 0.18 * math.sin(2 * math.pi * phase)


def analytic_size(seconds: float) -> float:
    return SIZE * (1 + 2 * seconds / 3)


def render_source(
    target: Path,
    vanish_after: float | None = None,
    motion: bool = True,
    grow: bool = False,
    occlusion: tuple[float, float] | None = None,
    flat: bool = False,
) -> None:
    """A dark noise field with a bright square walking a sine path; optional mid-clip vanish."""
    frame_bytes = WIDTH * HEIGHT * 3
    process = subprocess.Popen(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-y",
            "-nostdin",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{WIDTH}x{HEIGHT}",
            "-r",
            str(FPS),
            "-i",
            "pipe:0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=0x08000000,
    )
    assert process.stdin is not None
    for index in range(FPS * 3):
        seconds = index / FPS
        cx, cy = path_at(seconds) if motion else (0.5, 0.5)
        size = analytic_size(seconds) if grow else SIZE
        hidden = vanish_after is not None and seconds >= vanish_after
        bar = occlusion is not None and occlusion[0] <= seconds < occlusion[1]
        rows = bytearray(frame_bytes)
        for y in range(HEIGHT):
            base = y * WIDTH * 3
            for x in range(WIDTH):
                value = ((x * 17 + y * 31) * 2654435761 >> 7) & 63
                inside = (
                    not hidden
                    and abs(x - cx * WIDTH) <= size / 2
                    and abs(y - cy * HEIGHT) <= size / 2
                )
                behind = bar and abs(x - cx * WIDTH) <= 60 and abs(y - cy * HEIGHT) <= 60
                level = 200 if flat else 4 if behind else (245 if inside else value)
                offset = base + x * 3
                rows[offset] = level
                rows[offset + 1] = level
                rows[offset + 2] = level
        process.stdin.write(bytes(rows))
    process.stdin.close()
    error = process.stderr.read()
    assert process.wait(timeout=180) == 0, error.decode(errors="replace")[-500:]


def analyse(
    source: Path, frames: int = 90, search: int = 10, start: int = 0, scale: bool = True
) -> dict:
    return track_mask(
        FFMPEG,
        source,
        WIDTH,
        HEIGHT,
        FrameRate(),
        (path_at(start / T)[0], path_at(start / T)[1], BOX[0], BOX[1]),
        frames,
        start,
        T // FPS,
        search,
        scale,
    )


def ground_truth_suite(folder: Path) -> None:
    source = folder / "moving.mp4"
    render_source(source)
    result = analyse(source)
    assert result["analysis_width"] == 256 and result["analysis_height"] == 144, result
    assert result["sampled_frames"] == 90 and result["lost_at_ticks"] is None, result
    worst = 0.0
    for point in result["points"]:
        want_x, want_y = path_at(point["at_ticks"] / T)
        worst = max(worst, abs(point["mask_x"] - want_x), abs(point["mask_y"] - want_y))
    print(f"   tracked {len(result['points'])} frames, worst centre error {worst * WIDTH:.2f} px")
    assert worst < 0.012, worst

    # A static box must not wander.
    still = folder / "still.mp4"
    render_source(still, motion=False)
    static = track_box_frames(still, 20)
    drift = max(abs(centre[0] - 0.5) + abs(centre[1] - 0.5) for centre in static)
    assert drift < 0.02, drift

    # When the target disappears, tracking must stop rather than follow noise.
    gone = folder / "vanish.mp4"
    render_source(gone, vanish_after=1.5)
    lost = analyse(gone)
    assert lost["lost_at_ticks"] is not None, lost
    error = abs(lost["lost_at_ticks"] - 1.5 * T)
    assert error < 0.6 * T, (lost["lost_at_ticks"] / T, error / T)
    print(
        f"   lost reported at {lost['lost_at_ticks'] / T:.2f}s "
        f"after {len(lost['points'])} tracked frames (target vanished at 1.50s)"
    )

    # Brief occlusion: glide with the motion model, then re-find the same target.
    hidden = folder / "occluded.mp4"
    render_source(hidden, occlusion=(1.0, 1.6))
    through = analyse(hidden)
    assert through["lost_at_ticks"] is None, through
    assert through["predicted_frames"] >= 10, through
    assert len(through["gaps"]) == 1, through["gaps"]
    gap = through["gaps"][0]
    assert abs(gap["from_ticks"] / T - 1.0) < 0.25 and abs(gap["to_ticks"] / T - 1.6) < 0.25, gap
    after = [point for point in through["points"] if point["at_ticks"] / T > 1.8]
    worst_after = max(abs(point["mask_x"] - path_at(point["at_ticks"] / T)[0]) for point in after)
    assert worst_after * WIDTH < 4.0, worst_after
    print(
        f"   glided through occlusion {gap['from_ticks'] / T:.2f}-{gap['to_ticks'] / T:.2f}s "
        f"({through['predicted_frames']} predicted frames), re-found within "
        f"{worst_after * WIDTH:.2f} px"
    )

    # A target walking toward the camera: the box has to grow with it.
    growing = folder / "growing.mp4"
    render_source(growing, grow=True)
    sized = analyse(growing)
    assert sized["lost_at_ticks"] is None, sized
    checked = []
    for seconds in (1.0, 2.0, 2.9):
        point = min(sized["points"], key=lambda p: abs(p["at_ticks"] / T - seconds))
        want = analytic_size(point["at_ticks"] / T) / SIZE
        checked.append((seconds, point["width"] / BOX[0], want))
        assert abs(point["width"] / BOX[0] - want) / want < 0.22, (seconds, point, want)
    print("   box growth", [(at, round(got, 2), round(want, 2)) for at, got, want in checked])

    # With scale estimation off the box must stay put, and it must visibly be the worse choice.
    def centre_drift(body: dict) -> float:
        return (
            max(
                abs(point["mask_x"] - path_at(point["at_ticks"] / T)[0]) for point in body["points"]
            )
            * WIDTH
        )

    fixed = analyse(growing, scale=False)
    assert all(point["width"] == BOX[0] for point in fixed["points"]), fixed["points"][-1]
    assert centre_drift(sized) < 6.0, centre_drift(sized)
    assert centre_drift(sized) < centre_drift(fixed), (centre_drift(sized), centre_drift(fixed))
    print(
        f"   with scale off the box stays {BOX[0]} wide but the centre drifts to "
        f"{centre_drift(fixed):.1f} px, against {centre_drift(sized):.1f} px when it follows growth"
    )


def track_box_frames(source: Path, frames: int) -> list[tuple[float, float]]:
    width, height, decoded = decode_luma(
        FFMPEG,
        source,
        0.0,
        frames / FPS,
        FrameRate(),
        WIDTH,
        HEIGHT,
        frames,
    )
    result = track_box(decoded, width, (0.5, 0.5, 0.2, 0.3), 6)
    assert result["lost_at"] is None, result
    return [(box[0], box[1]) for box in result["boxes"]]


def apply(project: Project, commands: list[dict]) -> Project:
    batch = EditBatch(request_id="check", expected_revision=project.revision, commands=commands)
    return apply_commands(project, batch.commands)


def project_payload(clip: dict, canvas: tuple[int, int] = (1920, 1080)) -> Project:
    return Project.model_validate(
        {
            "id": "p",
            "name": "tracking",
            "settings": {"width": canvas[0], "height": canvas[1]},
            "tracks": [{"id": "v", "kind": "video", "name": "v"}],
            "assets": {
                "a": {
                    "id": "a",
                    "kind": "video",
                    "label": "a",
                    "reference": "r",
                    "duration_ticks": 3 * T,
                }
            },
            "clips": {"c": clip},
        }
    )


def mask_box(**changes) -> dict:
    mask = {
        "shape": "ellipse",
        "center_x": 0.25,
        "center_y": 0.5,
        "width": BOX[0],
        "height": BOX[1],
        "feather": 0.0,
        "inverted": False,
        "vertices": None,
    }
    mask.update(changes)
    return mask


def clip_payload(**changes) -> dict:
    clip = {
        "id": "c",
        "asset_id": "a",
        "track_id": "v",
        "position_ticks": 0,
        "duration_ticks": 3 * T,
        "mask": mask_box(),
    }
    clip.update(changes)
    return clip


def reducer_suite(folder: Path) -> None:
    project = project_payload(clip_payload())
    project.assets["a"].verified = None
    validate_timeline(project)
    points = [
        {"at_ticks": 0, "center_x": 0.3, "center_y": 0.5},
        {"at_ticks": T // FPS, "center_x": 0.4, "center_y": 0.52},
    ]
    edited = apply(project, [{"op": "clip.mask_track", "clip_id": "c", "points": points}])
    tracked = edited.clips["c"]
    assert tracked.mask is not None and tracked.mask.center_x == 0.3
    assert [(k.property, k.at_ticks, round(k.value, 6)) for k in tracked.keyframes] == [
        ("mask_x", 0, 0.3),
        ("mask_x", T // FPS, 0.4),
        ("mask_y", 0, 0.5),
        ("mask_y", T // FPS, 0.52),
    ], tracked.keyframes
    assert Clip.model_validate(tracked.model_dump())

    sized = [
        {"at_ticks": 0, "center_x": 0.3, "center_y": 0.5, "width": 0.16, "height": 0.24},
        {"at_ticks": T // FPS, "center_x": 0.4, "center_y": 0.52, "width": 0.28, "height": 0.42},
    ]
    grown = apply(project, [{"op": "clip.mask_track", "clip_id": "c", "points": sized}])
    box = grown.clips["c"]
    assert box.mask is not None and (box.mask.width, box.mask.height) == (0.16, 0.24), box.mask
    assert sorted({key.property for key in box.keyframes}) == [
        "mask_height",
        "mask_width",
        "mask_x",
        "mask_y",
    ], box.keyframes
    assert len(box.keyframes) == 8, box.keyframes
    assert [(key.at_ticks, key.value) for key in box.keyframes if key.property == "mask_width"] == [
        (0, 0.16),
        (T // FPS, 0.28),
    ], box.keyframes
    assert Clip.model_validate(box.model_dump())

    half = [sized[0], {"at_ticks": T // FPS, "center_x": 0.4, "center_y": 0.52}]
    try:
        apply(project, [{"op": "clip.mask_track", "clip_id": "c", "points": half}])
    except ValidationError as error:
        assert "both width and height" in str(error), error
    else:
        raise AssertionError("a half-sized track path must be refused, not silently truncated")

    for label, clip_data in (
        ("no mask", clip_payload(mask=None)),
        ("inverted", clip_payload(mask=mask_box(inverted=True))),
        (
            "speed curve",
            clip_payload(
                speed_curve=[{"at_ticks": 0, "percent": 100}, {"at_ticks": 2 * T, "percent": 200}]
            ),
        ),
    ):
        base = project_payload(clip_data)
        try:
            apply(base, [{"op": "clip.mask_track", "clip_id": "c", "points": points}])
        except EditorError as error:
            assert error.code == "INVALID_MASK", (label, error.payload())
        else:
            raise AssertionError(f"{label} must refuse tracking")

    past = project_payload(clip_payload())
    try:
        apply(
            past,
            [
                {
                    "op": "clip.mask_track",
                    "clip_id": "c",
                    "points": [
                        {"at_ticks": 0, "center_x": 0.3, "center_y": 0.5},
                        {"at_ticks": 4 * T, "center_x": 0.4, "center_y": 0.5},
                    ],
                }
            ],
        )
    except EditorError as error:
        assert error.code == "INVALID_KEYFRAME", error.payload()
    else:
        raise AssertionError("points beyond the clip must be refused")


def http_suite(folder: Path) -> None:
    media = MediaService(
        folder / "db.sqlite3", [folder / "media"], folder / "cache", FFMPEG, FFPROBE
    )
    source = folder / "media" / "moving.mp4"
    source.parent.mkdir(exist_ok=True)
    render_source(source)
    token = "tracking" + "e" * 54
    app = create_app(folder / "api.sqlite3", token, media=media)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        caps = client.get("/v1/capabilities").json()
        assert caps["features"]["mask_tracking"] is True, caps["features"]
        assert "clip.mask_track" in caps["commands"]
        probe = client.post("/v1/media/import", json={"path": str(source)}).json()
        assert "verified" in probe, probe
        project = client.post("/v1/projects", json={"request_id": "new", "name": "track"}).json()[
            "project"
        ]
        path = f"/v1/projects/{project['id']}"
        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "seed",
                "expected_revision": 0,
                "commands": [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                    {
                        "op": "asset.import",
                        "asset_id": "a",
                        "label": "moving",
                        "probe_id": probe["id"],
                        "verified": probe["verified"],
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "c",
                            "asset_id": "a",
                            "track_id": "v",
                            "position_ticks": 0,
                            "duration_ticks": 3 * T,
                            "mask": mask_box(),
                        },
                    },
                ],
            },
        )
        assert seeded.status_code == 200, seeded.text

        dry = client.post(
            path + "/clips/c/track",
            json={"request_id": "dry", "expected_revision": 1, "frames": 40, "dry_run": True},
        )
        assert dry.status_code == 200, dry.text
        assert dry.json()["committed"] is False
        assert client.get(path).json()["revision"] == 1, "a dry run must not write"
        preview = dry.json()["tracking"]
        assert preview["tracked_frames"] == 40 and preview["lost_at_ticks"] is None, preview

        written = client.post(
            path + "/clips/c/track",
            json={"request_id": "track", "expected_revision": 1, "frames": 40},
        )
        assert written.status_code == 200, written.text
        body = written.json()
        assert body["committed"] is True and body["project"]["revision"] == 2
        clip = body["project"]["clips"]["c"]
        marks = sorted(k["at_ticks"] for k in clip["keyframes"] if k["property"] == "mask_x")
        assert marks == [index * (T // FPS) for index in range(40)], marks[:5]
        assert clip["mask"]["center_x"] == preview["points"][0]["center_x"], preview
        assert preview["scale_estimated"] is True, preview
        assert (
            sorted(k["at_ticks"] for k in clip["keyframes"] if k["property"] == "mask_width")
            == marks
        )
        assert clip["mask"]["width"] == preview["points"][0]["width"], preview["points"][0]
        for key in clip["keyframes"]:
            if key["property"] == "mask_x":
                want_x, _ = path_at(key["at_ticks"] / T)
                assert abs(key["value"] - want_x) < 0.012, (key, want_x)

        replay = client.post(
            path + "/clips/c/track",
            json={"request_id": "track", "expected_revision": 1, "frames": 40},
        )
        assert replay.json()["replayed"] is True and replay.json()["project"]["revision"] == 2
        unsized = client.post(
            path + "/clips/c/track",
            json={
                "request_id": "noscale",
                "expected_revision": 2,
                "frames": 20,
                "estimate_scale": False,
                "dry_run": True,
            },
        )
        assert unsized.status_code == 200, unsized.text
        assert client.get(path).json()["revision"] == 2, "a dry run must not write"
        assert not any("width" in point for point in unsized.json()["tracking"]["points"]), (
            unsized.json()["tracking"]["points"][0]
        )
        conflict = client.post(
            path + "/clips/c/track",
            json={"request_id": "again", "expected_revision": 1, "frames": 20},
        )
        assert conflict.status_code == 409, conflict.text
        assert client.get(path).json()["revision"] == 2

        too_far = client.post(
            path + "/clips/c/track",
            json={"request_id": "far", "expected_revision": 2, "frames": 900},
        )
        assert too_far.json()["error"]["code"] == "SOURCE_OUT_OF_BOUNDS", too_far.text
        out_of_clip = client.post(
            path + "/clips/c/track",
            json={"request_id": "edge", "expected_revision": 2, "from_ticks": 3 * T, "frames": 10},
        )
        assert out_of_clip.json()["error"]["code"] == "INVALID_TRACK_TARGET", out_of_clip.text
        no_mask = client.post(
            path + "/edits",
            json={
                "request_id": "unmask",
                "expected_revision": 2,
                "commands": [{"op": "clip.mask", "clip_id": "c", "mask": None}],
            },
        )
        assert no_mask.json()["error"]["code"] == "INVALID_MASK", no_mask.text
        assert client.get(path).json()["revision"] == 2, "tracking keyframes need their mask"

        restored = client.post(
            path + "/restore",
            json={"request_id": "undo", "expected_revision": 2, "target_revision": 1},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["project"]["clips"]["c"]["keyframes"] == []
        assert client.get(path + "/clips/c/track").status_code in (404, 405, 422)


def media_suite(folder: Path) -> None:
    """The tracked keyframes must move the exported mask, not just the preview."""
    source = folder / "export.mp4"
    render_source(source)
    verified = {
        "probe_id": "a",
        "path": str(source),
        "kind": "video",
        "label": "moving",
        "size_bytes": source.stat().st_size,
        "content_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "duration_ticks": 3 * T,
        "width": WIDTH,
        "height": HEIGHT,
        "has_audio": False,
    }
    project = project_payload(
        clip_payload(mask=mask_box(center_x=path_at(0)[0], center_y=path_at(0)[1])),
        (WIDTH, HEIGHT),
    )
    project.assets["a"].verified = VerifiedMedia.model_validate(verified)
    validate_timeline(project)
    result = analyse(source, frames=60)
    tracked = apply(
        project,
        [
            {
                "op": "clip.mask_track",
                "clip_id": "c",
                "points": [
                    {
                        "at_ticks": point["at_ticks"],
                        "center_x": point["mask_x"],
                        "center_y": point["mask_y"],
                    }
                    for point in result["points"]
                ],
            }
        ],
    )
    out = folder / "tracked.mp4"
    plan = compile_render_plan(tracked, "h264-source-quality")
    job = folder / "job"
    job.mkdir(exist_ok=True)
    for name, body in plan.text_files.items():
        (job / name).write_text(body, encoding="utf-8")
    process = subprocess.run(
        plan.ffmpeg_argv(str(FFMPEG), str(out)),
        cwd=job,
        capture_output=True,
        timeout=300,
        creationflags=0x08000000,
    )
    assert process.returncode == 0, process.stderr.decode(errors="replace")[-800:]

    def centroid(at: float) -> tuple[float, float, int]:
        raw = subprocess.run(
            [
                str(FFMPEG),
                "-v",
                "error",
                "-ss",
                f"{at:.6f}",
                "-i",
                str(out),
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "gray",
                "pipe:1",
            ],
            capture_output=True,
            timeout=180,
            check=True,
            creationflags=0x08000000,
        ).stdout
        assert len(raw) == WIDTH * HEIGHT, len(raw)
        xs = sum(x for y in range(HEIGHT) for x in range(WIDTH) if raw[y * WIDTH + x] > 150)
        ys = sum(y for y in range(HEIGHT) for x in range(WIDTH) if raw[y * WIDTH + x] > 150)
        count = sum(1 for y in range(HEIGHT) for x in range(WIDTH) if raw[y * WIDTH + x] > 150)
        return xs / count / WIDTH, ys / count / HEIGHT, count

    for seconds in (0.4, 1.1, 1.8):
        got_x, got_y, count = centroid(seconds)
        want_x, want_y = path_at(seconds)
        assert count > 200, (seconds, count)
        assert abs(got_x - want_x) < 0.03 and abs(got_y - want_y) < 0.03, (
            seconds,
            (got_x, got_y),
            (want_x, want_y),
        )
    # Past the last tracked frame the mask holds, so the object walks out of it.
    _, _, stranded = centroid(2.6)
    assert stranded < 200, stranded
    print(
        "   exported mask follows the object within 3% of frame at t=0.4/1.1/1.8 and holds after",
        f" the last tracked frame (bright pixels left: {stranded})",
    )


def sized_export_suite(folder: Path) -> None:
    """The size the tracker wrote has to open the exported mask, not only the preview one.

    A flat bright source makes the revealed area equal to the mask's own area, so counting lit
    pixels measures the tracked `mask_width`/`mask_height` instead of the object inside it.
    """
    source = folder / "flat.mp4"
    render_source(source, flat=True)
    project = project_payload(
        clip_payload(mask=mask_box(center_x=path_at(0)[0], center_y=path_at(0)[1])),
        (WIDTH, HEIGHT),
    )
    project.assets["a"].verified = VerifiedMedia.model_validate(
        {
            "probe_id": "a",
            "path": str(source),
            "kind": "video",
            "label": "flat",
            "size_bytes": source.stat().st_size,
            "content_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "duration_ticks": 3 * T,
            "width": WIDTH,
            "height": HEIGHT,
            "has_audio": False,
        }
    )
    validate_timeline(project)
    sized = analyse(folder / "growing.mp4", frames=60)
    anchor = sized["points"][0]
    tracked = apply(
        project,
        [
            {
                "op": "clip.mask_track",
                "clip_id": "c",
                "points": [
                    {
                        "at_ticks": point["at_ticks"],
                        "center_x": anchor["mask_x"],
                        "center_y": anchor["mask_y"],
                        "width": point["width"],
                        "height": point["height"],
                    }
                    for point in sized["points"]
                ],
            }
        ],
    )
    clip = tracked.clips["c"]
    assert clip.mask is not None and clip.mask.width == anchor["width"], clip.mask

    out = folder / "sized.mp4"
    plan = compile_render_plan(tracked, "h264-source-quality")
    job = folder / "sized-job"
    job.mkdir(exist_ok=True)
    for name, body in plan.text_files.items():
        (job / name).write_text(body, encoding="utf-8")
    process = subprocess.run(
        plan.ffmpeg_argv(str(FFMPEG), str(out)),
        cwd=job,
        capture_output=True,
        timeout=300,
        creationflags=0x08000000,
    )
    assert process.returncode == 0, process.stderr.decode(errors="replace")[-800:]

    def lit(at: float) -> int:
        raw = subprocess.run(
            [
                str(FFMPEG),
                "-v",
                "error",
                "-ss",
                f"{at:.6f}",
                "-i",
                str(out),
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "gray",
                "pipe:1",
            ],
            capture_output=True,
            timeout=180,
            check=True,
            creationflags=0x08000000,
        ).stdout
        assert len(raw) == WIDTH * HEIGHT, len(raw)
        return sum(1 for pixel in raw if pixel > 150)

    def tracked_width(at: float) -> float:
        point = min(sized["points"], key=lambda p: abs(p["at_ticks"] / T - at))
        return point["width"] / anchor["width"]

    early, late = lit(0.3), lit(2.6)
    want = tracked_width(2.6) / tracked_width(0.3)
    assert late > 3 * early, (early, late)
    assert abs(math.sqrt(late / early) - want) / want < 0.15, (early, late, want)
    print(
        f"   tracked size opens the exported mask from {early} to {late} lit pixels: the picture "
        f"measures {math.sqrt(late / early):.2f} linear scale, the path asked for {want:.2f}"
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-tracking-") as scratch:
        folder = Path(scratch)
        ground_truth_suite(folder)
        reducer_suite(folder)
        http_suite(folder)
        media_suite(folder)
        sized_export_suite(folder)
    print(
        "PASS: the tracker recovers a known trajectory, reports a vanished target instead of",
        "guessing, writes mask motion atomically through the reducer, and moves and resizes the",
        "exported mask",
    )


if __name__ == "__main__":
    main()
