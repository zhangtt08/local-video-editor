"""Mask tracking against synthetic ground truth: a known trajectory must come back out of the
tracker, a vanished target must be reported as lost, a target that comes back after a long
occlusion — somewhere the motion model never predicted it — must be re-found and reported as
re-found, and the exported mask must follow the object.

The source is generated here, pixel by pixel, so the analytic centre of the moving square is exact.
"""

import hashlib
import math
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import (
    TRACK_GAP_DEFAULT,
    TRACK_GAP_MAX,
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
# The long-occlusion fixture: the subject is under a flat bar from 1.0s to 2.4s (42 frames at 30fps,
# longer than one glide window) and steps 0.15 of the frame width sideways at 1.7s, while hidden.
HIDDEN = (1.0, 2.4)
SHIFT = (1.7, 0.15, 0.0)


def path_at(seconds: float) -> tuple[float, float]:
    phase = seconds / 3.0
    return 0.25 + 0.5 * phase, 0.5 + 0.18 * math.sin(2 * math.pi * phase)


def analytic_size(seconds: float) -> float:
    return SIZE * (1 + 2 * seconds / 3)


def truth_at(seconds: float, shift: tuple[float, float, float] | None) -> tuple[float, float]:
    """Where the fixture's target actually is: the sine path, stepped by `shift` from its tick.

    The generator draws from this one function, so a test that asks "did the tracker follow the
    object" is comparing against the same arithmetic that put the object there.
    """
    cx, cy = path_at(seconds)
    if shift is not None and seconds >= shift[0]:
        cx, cy = cx + shift[1], cy + shift[2]
    return cx, cy


def render_source(
    target: Path,
    vanish_after: float | None = None,
    motion: bool = True,
    grow: bool = False,
    occlusion: tuple[float, float] | None = None,
    flat: bool = False,
    shift: tuple[float, float, float] | None = None,
    decoy: tuple[float, float, float, int] | None = None,
) -> None:
    """A dark noise field with a bright square walking a sine path; optional mid-clip vanish.

    `shift` steps the target by a fraction of the frame at a given second (a re-entry the motion
    model cannot predict), `decoy` switches on another square of `size` px from a given second, and
    `occlusion` paints a flat grey bar over whatever the target is standing on.
    """
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
        cx, cy = truth_at(seconds, shift) if motion else (0.5, 0.5)
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
                if decoy is not None and seconds >= decoy[0]:
                    _, decoy_x, decoy_y, decoy_size = decoy
                    if abs(x - decoy_x * WIDTH) <= decoy_size / 2 and (
                        abs(y - decoy_y * HEIGHT) <= decoy_size / 2
                    ):
                        level = 250
                offset = base + x * 3
                rows[offset] = level
                rows[offset + 1] = level
                rows[offset + 2] = level
        process.stdin.write(bytes(rows))
    process.stdin.close()
    error = process.stderr.read()
    assert process.wait(timeout=180) == 0, error.decode(errors="replace")[-500:]


def analyse(
    source: Path,
    frames: int = 90,
    search: int = 10,
    start: int = 0,
    scale: bool = True,
    shift: tuple[float, float, float] | None = None,
    reacquire: bool = True,
    max_gap: int = TRACK_GAP_DEFAULT,
) -> dict:
    return track_mask(
        FFMPEG,
        source,
        WIDTH,
        HEIGHT,
        FrameRate(),
        (truth_at(start / T, shift)[0], truth_at(start / T, shift)[1], BOX[0], BOX[1]),
        frames,
        start,
        T // FPS,
        search,
        scale,
        max_gap,
        reacquire,
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
    # A target found again inside the local search radius is not a global re-acquisition: the reply
    # may only claim one when the whole-picture sweep is what actually located it.
    assert through["reacquire"] is True and not through["reacquired_at"], through
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


def reacquisition_suite(folder: Path) -> None:
    """A target hidden for longer than one glide window, and stepping sideways while it is out of
    view, has to come back as a measured path. The control run turns only the whole-picture search
    off, so the difference between the two runs is the search itself and not a wider guess window.
    """
    shift = SHIFT
    source = folder / "long-hidden.mp4"
    render_source(source, occlusion=HIDDEN, shift=shift)
    started = time.perf_counter()
    found = analyse(source, shift=shift)
    took = time.perf_counter() - started
    frame = T // FPS
    assert found["reacquire"] is True and found["lost_at_ticks"] is None, found["lost_at_ticks"]
    assert found["reacquired_frames"] == 1, found["reacquired_frames"]
    back_at = found["reacquired_at"][0]
    assert abs(back_at / T - 2.4) < 0.1, back_at / T
    assert len(found["gaps"]) == 1, found["gaps"]
    start, stop = (
        found["gaps"][0]["from_ticks"] // frame,
        found["gaps"][0]["to_ticks"] // frame,
    )
    assert found["predicted_frames"] == stop - start, (found["predicted_frames"], found["gaps"])
    assert found["tracked_frames"] == 90, found["tracked_frames"]
    after = [point for point in found["points"] if point["at_ticks"] / T > 2.5]
    worst = max(abs(point["mask_x"] - truth_at(point["at_ticks"] / T, shift)[0]) for point in after)
    assert worst * WIDTH < 4.0, worst
    assert found["gap_closure"] > 0.02, found["gap_closure"]
    # The guesses inside the gap are re-anchored to the sightings that bound them, so not one of
    # them may leave the interval between the last real position and the re-found one.
    span = sorted((found["points"][start - 1]["mask_x"], found["points"][stop]["mask_x"]))
    strayed = [
        point["mask_x"]
        for point in found["points"][start:stop]
        if not span[0] - 1e-9 <= point["mask_x"] <= span[1] + 1e-9
    ]
    assert not strayed, strayed

    local = analyse(source, shift=shift, reacquire=False)
    assert local["lost_at_ticks"] is not None and local["reacquired_frames"] == 0, local
    assert local["tracked_frames"] == start, (local["tracked_frames"], start)
    assert (
        max(
            abs(point["mask_x"] - truth_at(point["at_ticks"] / T, shift)[0])
            for point in local["points"]
        )
        * WIDTH
        < 4.0
    ), "the frames before the gap must still be tracked exactly"
    print(
        f"   re-acquired a target hidden for {stop - start} frames ({(stop - start) / FPS:.2f}s) "
        f"that stepped {(shift[1] * WIDTH):.0f} px sideways while out of view: "
        f"{found['tracked_frames']}/{90} frames measured, back at {back_at / T:.2f}s, "
        f"glide had to be shifted by {found['gap_closure']:.3f} of the frame width, {took:.1f}s"
    )
    print(
        f"   control (same window, whole-picture search off): lost at "
        f"{local['lost_at_ticks'] / T:.2f}s after only {local['tracked_frames']} frames"
    )
    assert took < 120.0, f"re-acquisition took {took:.1f}s for a 90-frame clip"


def decoy_suite(folder: Path) -> None:
    """The sweep looks for the *template*, not for anything bright: an identical square coming back
    somewhere else is a legitimate re-find and has to be reported as one, while a square of a
    different build must not be followed at all.
    """
    twin = folder / "decoy-twin.mp4"
    render_source(twin, vanish_after=1.5, decoy=(1.6, 0.72, 0.72, SIZE))
    moved = analyse(twin)
    assert moved["reacquired_frames"] >= 1 and moved["lost_at_ticks"] is None, moved
    last = moved["points"][-1]
    drift = max(abs(last["mask_x"] - 0.72) * WIDTH, abs(last["mask_y"] - 0.72) * HEIGHT)
    assert drift < 4.0, drift
    assert moved["gap_closure"] > 0.05, moved["gap_closure"]
    print(
        f"   a same-build square at another place is re-found and reported: closure "
        f"{moved['gap_closure']:.3f} of the frame width, {moved['reacquired_frames']} re-find, "
        f"ending {drift:.2f} px off it"
    )

    blob = folder / "decoy-blob.mp4"
    render_source(blob, vanish_after=1.5, decoy=(1.6, 0.72, 0.72, 3 * SIZE))
    honest = analyse(blob)
    assert honest["reacquired_frames"] == 0, honest
    assert honest["lost_at_ticks"] is not None, honest
    print(
        f"   a three-times-bigger flat square is not followed: still lost at "
        f"{honest['lost_at_ticks'] / T:.2f}s with {honest['tracked_frames']} measured frames"
    )

    wiring = (ROOT / "src" / "agentcut" / "stabilize.py").read_text(encoding="utf-8")
    assert "reacquire=False" in wiring, (
        "stabilization anchors must not be allowed to jump the picture"
    )


def interface_suite() -> None:
    """The numbers the reply added have to reach the person who pressed the button, not only the
    Agent reading JSON: the client type declares them, the toast speaks them, and the tooltip and
    help page describe the re-find instead of the old glide-only story.
    """
    engine = (ROOT / "desktop" / "src" / "engine.ts").read_text(encoding="utf-8")
    store = (ROOT / "desktop" / "src" / "store.ts").read_text(encoding="utf-8")
    inspector = (ROOT / "desktop" / "src" / "views" / "Inspector.tsx").read_text(encoding="utf-8")
    help_page = (ROOT / "desktop" / "src" / "views" / "Help.tsx").read_text(encoding="utf-8")
    declaration = engine[engine.index("maskTrack(") : engine.index("silenceScan(")]
    for field in ("reacquire", "reacquired_frames", "reacquired_at_ticks", "gap_closure"):
        assert field in declaration, f"the tracking reply type does not declare {field}"
    assert "stats.reacquired_frames > 0" in store, "the toast never says the target was re-found"
    assert "stats.reacquired_at_ticks[0]" in store, "the toast does not say when it was re-found"
    assert "stats.gap_closure" in store, "the toast does not say how far the guesses had to move"
    assert "重新找" in inspector, "the button still promises the glide-only behaviour"
    assert "重新找" in help_page and "补的那一段随后按找回的真实位置校正" in help_page, help_page[
        :80
    ]
    print("   interface: the reply's re-find fields are declared, toasted and explained")


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

    # A second run over a later window has to *continue* the path, not delete the part of it that
    # already worked: before 1.73 re-tracking a later stretch wiped every point outside it, so the
    # mask snapped back to its drawn box over the first half of the shot.
    # Work on a copy: `apply` hands back the mutated candidate, and the cases below this one still
    # expect the project as it was left by the first track.
    joined = edited.model_copy(deep=True)
    tail = [
        {"at_ticks": T // FPS, "center_x": 0.9, "center_y": 0.5},
        {"at_ticks": 2 * T // FPS, "center_x": 0.95, "center_y": 0.52},
    ]
    merged = apply(
        joined,
        [{"op": "clip.mask_track", "clip_id": "c", "merge": True, "points": tail}],
    ).clips["c"]
    kept = [(key.property, key.at_ticks, round(key.value, 6)) for key in merged.keyframes]
    assert ("mask_x", 0, 0.3) in kept, f"the merge deleted the segment before the window: {kept}"
    assert ("mask_x", T // FPS, 0.9) in kept, kept
    assert len([entry for entry in kept if entry[0] == "mask_x"]) == 3, kept
    assert merged.mask is not None and merged.mask.center_x == 0.3, merged.mask
    replaced = apply(
        joined.model_copy(deep=True),
        [{"op": "clip.mask_track", "clip_id": "c", "merge": False, "points": tail}],
    ).clips["c"]
    assert len([key for key in replaced.keyframes if key.property == "mask_x"]) == 2, (
        "merge=False must still rewrite the whole path (从头重跟)"
    )
    print(
        "   reducer: merge=True keeps the earlier segment and replaces only its window; "
        "merge=False still rewrites the whole path"
    )

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

        # 1.73: a run that loses the subject can be continued instead of started over. Re-tracking
        # the last 20 frames has to leave the first 20 alone and rewrite only its own window --
        # before this, every point outside the new window was deleted, so the mask snapped back to
        # where it had been drawn over the first half of the shot.
        want_x, want_y = path_at(20 / FPS)
        anchored = client.post(
            path + "/edits",
            json={
                "request_id": "anchor",
                "expected_revision": 2,
                "commands": [
                    {
                        "op": "clip.mask",
                        "clip_id": "c",
                        "mask": {
                            "shape": "ellipse",
                            "center_x": want_x,
                            "center_y": want_y,
                            "width": 0.16,
                            "height": 0.24,
                            "feather": 0.0,
                            "inverted": False,
                        },
                    }
                ],
            },
        )
        assert anchored.status_code == 200, anchored.text[:300]
        joined = client.post(
            path + "/clips/c/track",
            json={
                "request_id": "join",
                "expected_revision": anchored.json()["project"]["revision"],
                "from_ticks": 20 * (T // FPS),
                "frames": 20,
            },
        )
        assert joined.status_code == 200, joined.text[:300]
        body = joined.json()
        assert body["project"]["revision"] == 4
        clip = body["project"]["clips"]["c"]
        marks = sorted(k["at_ticks"] for k in clip["keyframes"] if k["property"] == "mask_x")
        assert marks == [index * (T // FPS) for index in range(40)], marks[:5] + marks[-5:]
        tracking = body["tracking"]
        assert tracking["merged"] is True, tracking
        assert tracking["kept_frames"] == 20, tracking
        assert tracking["replaced_frames"] == 20, tracking
        assert tracking["seam_ticks"] == T // FPS, tracking
        for key in clip["keyframes"]:
            if key["property"] != "mask_x":
                continue
            want_x, _ = path_at(key["at_ticks"] / T)
            assert abs(key["value"] - want_x) < 0.012, (key, want_x)
        assert abs(tracking["seam_jump"]) < 0.012, tracking
        print(
            "   http: continuing a track keeps the first 20 points, rewrites only its window, and "
            f"reports the seam ({tracking['seam_jump']:.4f} of a frame wide, "
            f"{tracking['seam_ticks'] * FPS // T} frame apart)"
        )
        restarted = client.post(
            path + "/clips/c/track",
            json={
                "request_id": "restart",
                "expected_revision": 4,
                "from_ticks": 20 * (T // FPS),
                "frames": 20,
                "merge": False,
            },
        )
        assert restarted.status_code == 200, restarted.text[:300]
        marks = sorted(
            k["at_ticks"]
            for k in restarted.json()["project"]["clips"]["c"]["keyframes"]
            if k["property"] == "mask_x"
        )
        assert marks == [(20 + index) * (T // FPS) for index in range(20)], (
            "merge=False must still rewrite the whole path (从头重跟)"
        )
        print("   http: merge=False still wipes the earlier segment, so 从头重跟 stays available")
        unsized = client.post(
            path + "/clips/c/track",
            json={
                "request_id": "noscale",
                "expected_revision": 5,
                "frames": 20,
                "estimate_scale": False,
                "dry_run": True,
            },
        )
        assert unsized.status_code == 200, unsized.text
        assert client.get(path).json()["revision"] == 5, "a dry run must not write"
        assert not any("width" in point for point in unsized.json()["tracking"]["points"]), (
            unsized.json()["tracking"]["points"][0]
        )
        conflict = client.post(
            path + "/clips/c/track",
            json={"request_id": "again", "expected_revision": 1, "frames": 20},
        )
        assert conflict.status_code == 409, conflict.text
        assert client.get(path).json()["revision"] == 5

        # v13: a free-form outline may be tracked too, but only for translation — the engine must
        # not hand back size curves the exporter would refuse. Both steps are dry runs so the
        # revision sequence below stays as written.
        too_far = client.post(
            path + "/clips/c/track",
            json={"request_id": "far", "expected_revision": 5, "frames": 900},
        )
        assert too_far.json()["error"]["code"] == "SOURCE_OUT_OF_BOUNDS", too_far.text
        out_of_clip = client.post(
            path + "/clips/c/track",
            json={"request_id": "edge", "expected_revision": 5, "from_ticks": 3 * T, "frames": 10},
        )
        assert out_of_clip.json()["error"]["code"] == "INVALID_TRACK_TARGET", out_of_clip.text
        no_mask = client.post(
            path + "/edits",
            json={
                "request_id": "unmask",
                "expected_revision": 5,
                "commands": [{"op": "clip.mask", "clip_id": "c", "mask": None}],
            },
        )
        assert no_mask.json()["error"]["code"] == "INVALID_MASK", no_mask.text
        assert client.get(path).json()["revision"] == 5, "tracking keyframes need their mask"

        restored = client.post(
            path + "/restore",
            json={"request_id": "undo", "expected_revision": 5, "target_revision": 1},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["project"]["clips"]["c"]["keyframes"] == []
        assert client.get(path + "/clips/c/track").status_code in (404, 405, 422)

        # v13: a free-form outline may be tracked too, but only for translation. Written for real
        # (not a dry run) so the reducer, the contract and the exporter all have to agree on what
        # the endpoint produced — a size curve on a path mask would fail validation here.
        box = client.get(path).json()["clips"]["c"]["mask"]
        triangle = {
            "shape": "path",
            "feather": box["feather"],
            "vertices": [
                {
                    "x": box["center_x"] - box["width"] / 2,
                    "y": box["center_y"] - box["height"] / 2,
                    "handle_out": [0, 0],
                    "handle_in": [0, 0],
                },
                {
                    "x": box["center_x"] + box["width"] / 2,
                    "y": box["center_y"] - box["height"] / 2,
                    "handle_out": [0, 0],
                    "handle_in": [0, 0],
                },
                {
                    "x": box["center_x"],
                    "y": box["center_y"] + box["height"] / 2,
                    "handle_out": [0, 0],
                    "handle_in": [0, 0],
                },
            ],
        }
        revision = client.get(path).json()["revision"]
        swap = client.post(
            path + "/edits",
            json={
                "request_id": "topath",
                "expected_revision": revision,
                "commands": [{"op": "clip.mask", "clip_id": "c", "mask": triangle}],
            },
        )
        assert swap.status_code == 200, swap.text
        stored = swap.json()["project"]["clips"]["c"]["mask"]
        assert stored["shape"] == "path", stored
        # v13 fits the box to the drawn outline: for this triangle that is the rectangle it came
        # from, so the tracked start box — and therefore the whole path — is unchanged.
        assert abs(stored["width"] - box["width"]) < 1e-9, (stored, box)
        assert abs(stored["center_x"] - box["center_x"]) < 1e-9, (stored, box)
        assert abs(stored["center_y"] - box["center_y"]) < 1e-9, (stored, box)
        followed = client.post(
            path + "/clips/c/track",
            json={
                "request_id": "pathtrack",
                "expected_revision": swap.json()["project"]["revision"],
                "frames": 20,
            },
        )
        assert followed.status_code == 200, followed.text
        proof = followed.json()["tracking"]
        assert proof["scale_estimated"] is False, proof
        assert not any("width" in point for point in proof["points"]), proof["points"][0]
        written = {
            item["property"] for item in followed.json()["project"]["clips"]["c"]["keyframes"]
        }
        assert written == {"mask_x", "mask_y"}, written
        print(
            "   tracking: a free-form outline is tracked for translation only — the endpoint says"
            " scale_estimated=false, and the written curves are mask_x/mask_y with no size curve"
        )

        # 1.85 over the real seam: a clip whose subject is hidden for longer than one glide window
        # and steps sideways while out of view. The two runs differ only in `reacquire`, so the
        # reply that comes back measured tells the story the one that does not cannot.
        limits = client.get("/v1/capabilities").json()["limits"]
        assert limits["track_max_gap_frames"] == TRACK_GAP_MAX, limits
        assert limits["track_gap_default"] == TRACK_GAP_DEFAULT, limits
        hidden_source = folder / "media" / "api-long-hidden.mp4"
        render_source(hidden_source, occlusion=HIDDEN, shift=SHIFT)
        hidden_probe = client.post("/v1/media/import", json={"path": str(hidden_source)}).json()
        assert "verified" in hidden_probe, hidden_probe
        revision = client.get(path).json()["revision"]
        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "seed-hidden",
                "expected_revision": revision,
                "commands": [
                    {
                        "op": "asset.import",
                        "asset_id": "b",
                        "label": "long-hidden",
                        "probe_id": hidden_probe["id"],
                        "verified": hidden_probe["verified"],
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "c2",
                            "asset_id": "b",
                            "track_id": "v",
                            "position_ticks": 3 * T,
                            "duration_ticks": 3 * T,
                            "mask": mask_box(),
                        },
                    },
                ],
            },
        )
        assert seeded.status_code == 200, seeded.text[:300]
        revision = seeded.json()["project"]["revision"]

        off = client.post(
            path + "/clips/c2/track",
            json={
                "request_id": "no-sweep",
                "expected_revision": revision,
                "frames": 90,
                "reacquire": False,
                "dry_run": True,
            },
        )
        assert off.status_code == 200, off.text[:300]
        assert client.get(path).json()["revision"] == revision, "a dry run must not write"
        blind = off.json()["tracking"]
        assert blind["reacquire"] is False and blind["reacquired_frames"] == 0, blind
        assert blind["lost_at_ticks"] is not None and blind["tracked_frames"] < 45, blind

        swept = client.post(
            path + "/clips/c2/track",
            json={"request_id": "sweep", "expected_revision": revision, "frames": 90},
        )
        assert swept.status_code == 200, swept.text[:300]
        body = swept.json()
        assert body["project"]["revision"] == revision + 1, body["project"]["revision"]
        proof = body["tracking"]
        assert proof["reacquired_frames"] == 1 and proof["lost_at_ticks"] is None, proof
        assert proof["tracked_frames"] == 90 == len(proof["points"]), proof
        assert abs(proof["reacquired_at_ticks"][0] / T - HIDDEN[1]) < 0.1, proof
        assert proof["gap_closure"] > 0.02, proof
        back = proof["reacquired_at_ticks"][0]
        written = [
            key
            for key in body["project"]["clips"]["c2"]["keyframes"]
            if key["property"] == "mask_x" and key["at_ticks"] >= back + 2 * (T // FPS)
        ]
        assert written, proof
        for key in written:
            want_x, _ = truth_at(key["at_ticks"] / T, SHIFT)
            assert abs(key["value"] - want_x) < 0.02, (key, want_x)
        print(
            f"   http: reacquire=false stops after {blind['tracked_frames']} frames, the sweep on"
            f" measures all {proof['tracked_frames']} and re-finds at "
            f"{proof['reacquired_at_ticks'][0] / T:.2f}s on the stepped path"
        )

        beyond = client.post(
            path + "/clips/c2/track",
            json={
                "request_id": "beyond",
                "expected_revision": body["project"]["revision"],
                "frames": 90,
                "max_gap_frames": TRACK_GAP_MAX + 1,
            },
        )
        assert beyond.status_code == 422, beyond.text[:200]
        assert client.get(path).json()["revision"] == body["project"]["revision"], (
            "a contract refusal must not write"
        )

        # A split tail carries `animation_offset_ticks`, so the source window it is analysed, the
        # ticks its keyframes are stored at, and the clock the renderer samples are three different
        # numbers for the same frame. Nothing above sets an offset, so this is where that seam is
        # measured: split the moving clip at 1 s, put the mask on the object the *tail* shows first,
        # and require both the ticks and the values to land where the picture says they should.
        revision = client.get(path).json()["revision"]
        split = client.post(
            path + "/edits",
            json={
                "request_id": "split",
                "expected_revision": revision,
                "commands": [
                    {"op": "clip.split", "clip_id": "c", "at_ticks": T, "right_clip_id": "c4"}
                ],
            },
        )
        assert split.status_code == 200, split.text[:300]
        tail = split.json()["project"]["clips"]["c4"]
        assert (tail["position_ticks"], tail["source_in_ticks"]) == (T, T), tail
        assert tail["animation_offset_ticks"] == T, tail
        want_x, want_y = path_at(1.0)
        moved = client.post(
            path + "/edits",
            json={
                "request_id": "move-tail",
                "expected_revision": split.json()["project"]["revision"],
                "commands": [
                    {
                        "op": "clip.mask",
                        "clip_id": "c4",
                        "mask": mask_box(center_x=want_x, center_y=want_y),
                    }
                ],
            },
        )
        assert moved.status_code == 200, moved.text[:300]
        offset_run = client.post(
            path + "/clips/c4/track",
            json={
                "request_id": "offset",
                "expected_revision": moved.json()["project"]["revision"],
                "frames": 45,
            },
        )
        assert offset_run.status_code == 200, offset_run.text[:400]
        ran = offset_run.json()
        assert ran["tracking"]["tracked_frames"] == 45, ran["tracking"]
        curve = sorted(
            (key["at_ticks"], key["value"])
            for key in ran["project"]["clips"]["c4"]["keyframes"]
            if key["property"] == "mask_x"
        )
        step = T // FPS
        # The split copies the head's earlier curves onto the tail, so only the ticks this run was
        # given are compared; the inherited ones sit before the tail's own window and clamp there.
        window = [(at, value) for at, value in curve if T <= at <= T + 44 * step]
        assert [at for at, _ in window] == [T + index * step for index in range(45)], window[:3]
        worst_offset = 0.0
        for at, value in window:
            want, _ = path_at(1.0 + (at - T) / T)
            worst_offset = max(worst_offset, abs(value - want))
        assert worst_offset < 0.012, worst_offset
        print(
            f"   offset: a split tail (offset 1s) tracked 45 frames, its keyframes sit on "
            f"the original clock and every one of them is within {worst_offset * WIDTH:.2f} px of "
            "the object at that source frame"
        )

        # 1.86: the analysis has to sample the frames the timeline *shows*. A clip at 200 % spends
        # two source frames on every frame it plays, so one analysed frame per source frame would
        # measure a picture the viewer never sees and write it onto the ticks that do.
        revision = client.get(path).json()["revision"]
        sped = client.post(
            path + "/edits",
            json={
                "request_id": "sped",
                "expected_revision": revision,
                "commands": [
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "c5",
                            "asset_id": "a",
                            "track_id": "v",
                            "position_ticks": 6 * T,
                            "duration_ticks": T + T // 2,
                            "speed_percent": 200,
                            "mask": mask_box(
                                center_x=path_at(0.0)[0],
                                center_y=path_at(0.0)[1],
                            ),
                        },
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "c6",
                            "asset_id": "a",
                            "track_id": "v",
                            "position_ticks": 8 * T,
                            "duration_ticks": T,
                            "speed_percent": 50,
                            "mask": mask_box(
                                center_x=path_at(0.0)[0],
                                center_y=path_at(0.0)[1],
                            ),
                        },
                    },
                ],
            },
        )
        assert sped.status_code == 200, sped.text[:300]
        revision = sped.json()["project"]["revision"]
        strides = {}
        for clip_id, frames, wanted_rate in (("c5", 45, "15/1"), ("c6", 30, "60/1")):
            run = client.post(
                path + f"/clips/{clip_id}/track",
                json={
                    "request_id": f"stride-{clip_id}",
                    "expected_revision": revision,
                    "frames": frames,
                },
            )
            assert run.status_code == 200, run.text[:400]
            reply = run.json()["tracking"]
            # The window read has to be the whole one: a `-t` that forgot the speed would hand
            # back a shorter path whose every point is still correct.
            assert reply["tracked_frames"] == frames, (clip_id, reply)
            revision = run.json()["project"]["revision"]
            assert reply["speed_percent"] != 100 and reply["sample_rate"] == wanted_rate, reply
            shown = sorted(
                (key["at_ticks"], key["value"])
                for key in run.json()["project"]["clips"][clip_id]["keyframes"]
                if key["property"] == "mask_x"
            )
            speed = reply["speed_percent"] / 100
            worst_shown = max(abs(value - path_at(at / T * speed)[0]) for at, value in shown)
            # What the old stride measured: the object where the source plays it, one frame per
            # source frame. Kept as a foil so the assertion above cannot pass by accident.
            worst_source = max(abs(value - path_at(at / T)[0]) for at, value in shown)
            strides[clip_id] = (speed, worst_shown, worst_source)
            assert worst_shown * WIDTH < 4.0, (clip_id, worst_shown)
            if speed != 1.0:
                assert worst_source * WIDTH > 20.0, (clip_id, worst_source)
        print(
            "   stride: a 200 % clip sampled at 15/1 fps and a 50 % clip at 60/1 fps both "
            "follow the object the timeline shows (worst "
            f"{strides['c5'][1] * WIDTH:.2f} / {strides['c6'][1] * WIDTH:.2f} px) and are "
            f"{strides['c5'][2] * WIDTH:.0f} / {strides['c6'][2] * WIDTH:.0f} px away from "
            "the frames they never played"
        )


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
        reacquisition_suite(folder)
        decoy_suite(folder)
        interface_suite()
        reducer_suite(folder)
        http_suite(folder)
        media_suite(folder)
        sized_export_suite(folder)
    print(
        "PASS: the tracker recovers a known trajectory, reports a vanished target instead of",
        "guessing, re-finds a target that comes back after a long occlusion out of view (and does",
        "not follow a square that merely looks bright), writes mask motion atomically through the",
        "reducer, and moves and resizes the exported mask",
    )


if __name__ == "__main__":
    main()
