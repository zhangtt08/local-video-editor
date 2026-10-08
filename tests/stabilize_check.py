"""Stabilisation: the camera's own motion is measured, and the delivered picture gets steadier.

A stabiliser is easy to fake — writing keyframes that flatter the plan's own arithmetic proves
nothing about the video. So this check measures twice: once against a fixture whose window position
is a closed-form function of `t` (the tracker's job is to recover it), and once on the frames the
shipped FFmpeg renders *after* the correction (the feature's job is to reduce them). The fixture is
built as a slow pan plus two frequencies of shake, because a stabiliser that only knows how to
freeze a frame would pass a jitter-only test and destroy every moving shot in the library.
"""

import math
import random
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import (
    STABILIZE_SMOOTHING_FRAMES,
    TIMEBASE,
    CreateProject,
    Project,
)
from agentcut.http_api import create_app
from agentcut.media import MediaService
from agentcut.projects import ProjectStore
from agentcut.render import compile_render_plan
from agentcut.stabilize import measure

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
# The plate is deliberately much bigger than the frame: the roll fixture rotates it by a degree, and
# a crop window that came near the plate's edge would sample the black corners the rotation exposes
# instead of picture — which would read as a tracker failure and not as the fixture lying.
PLATE_W, PLATE_H = 900, 560
WIDTH, HEIGHT = 640, 360
FPS = 30
SECONDS = 2.0
T = TIMEBASE
PAN_X = 20.0  # px/s of intended horizontal pan
SHAKE_X = 6.0  # px amplitude at 4 Hz: slow enough that a frame's position is pinned by the clock,
SHAKE_X2 = 3.0  # px at 9 Hz
SHAKE_Y = 5.0
ALT = 8.0  # px: the second fixture jumps to the other side of its centre every frame, which is what
# a handheld impact looks like at 30 fps. Two fixtures, because two claims need different ground:
# the analytic path can only be checked against something the encoder's clock cannot slip (a slow
# wave), while "the delivered picture got steadier" needs shake big enough to see over the
# tracker's own one-pixel resolution — a 4 Hz sine moves less between frames than that noise.
# The crop window's own travel budget: the plate is 80 px wider and 60 px taller than the frame.
X_ROOM = PLATE_W - WIDTH
Y_ROOM = PLATE_H - HEIGHT
# The same term, written in the two languages the fixture has to agree on.
ALT_FFMPEG = f"{2 * ALT:.0f}*mod(floor({FPS}*t),2)-{ALT:.0f}"
ROLL = 1.0  # degrees the third fixture rolls by, to the other side every frame


def window_x(t: float) -> float:
    return (
        20.0
        + PAN_X * t
        + SHAKE_X * math.sin(2 * math.pi * 4 * t)
        + SHAKE_X2 * math.sin(2 * math.pi * 9 * t)
    )


def window_y(t: float) -> float:
    return 25.0 + SHAKE_Y * math.sin(2 * math.pi * 5 * t + 1.0)


def truth(index: int) -> tuple[float, float]:
    """Where the picture sits at frame `index`, relative to frame 0, as fractions of the frame.

    The window moving right pushes the picture left, so the sign is inverted — that inversion is
    itself part of what the check pins, because a correction applied with the wrong sign makes the
    shake twice as bad and still looks like motion.
    """
    t = index / FPS
    return (
        -(window_x(t) - window_x(0.0)) / WIDTH,
        -(window_y(t) - window_y(0.0)) / HEIGHT,
    )


def plate(path: Path) -> None:
    """Blocks and discs, seeded: structure the encoder survives.

    A per-pixel noise plate is the worst fixture possible — H.264 quantises it away, every block
    comes back a slightly different grey, and the tracker faithfully follows that as if it were the
    picture. This one keeps its detail at 6 px and above.
    """
    random.seed(20261008)
    block = 24
    cols = PLATE_W // block + 1
    rows_count = PLATE_H // block + 1
    planes = [
        [[random.randrange(256) for _ in range(cols)] for _ in range(rows_count)] for _ in range(3)
    ]
    discs = [
        (random.randrange(PLATE_W), random.randrange(PLATE_H), random.randrange(20, 60))
        for _ in range(40)
    ]
    rows = []
    for y in range(PLATE_H):
        row = bytearray([0])
        for x in range(PLATE_W):
            cell_y, cell_x = y // block, x // block
            value, red, blue = (
                planes[0][cell_y][cell_x],
                planes[1][cell_y][cell_x],
                planes[2][cell_y][cell_x],
            )
            for cx, cy, radius in discs:
                if (x - cx) ** 2 + (y - cy) ** 2 < radius * radius:
                    value, red = (value + 90) % 256, (red + 40) % 256
            row += bytes([value, red, blue])
        rows.append(bytes(row))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", PLATE_W, PLATE_H, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def build(folder: Path, name: str, expr_x: str, expr_y: str, pre: str = "") -> Path:
    out = folder / name
    subprocess.run(
        [
            str(FFMPEG),
            "-y",
            "-v",
            "error",
            "-loop",
            "1",
            "-i",
            str(folder / "plate.png"),
            "-t",
            str(SECONDS),
            "-vf",
            # `fps` first, then `crop`: the crop expression reads the frame's own timestamp, and a
            # looped still arrives at the image2 default rate, so putting `fps` after it makes the
            # window a staircase sampled at the wrong clock and the analytic truth stops being true.
            f"fps={FPS},{pre}crop={WIDTH}:{HEIGHT}:x='{expr_x}':y='{expr_y}',format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "14",
            str(out),
        ],
        check=True,
    )
    return out


def expect_status(code: str) -> int:
    """The HTTP status this engine owes for that error name — 404 for a missing thing, else 422."""
    return 404 if code == "NOT_FOUND" else 422


def wiggle(offsets: list[list[float]]) -> float:
    """RMS distance from each frame's own neighbours: the part an editor calls shake.

    A maximum would do the same job on a big shake and the opposite job on a small one — the
    tracker resolves one analysis pixel (2.5 px here), so a *perfectly* stabilised clip still
    measures a 2.5 px worst-case jump. Averaged over the path, that floor is 0.9 px and the
    fixture's 8 px jolt is 30 times above it.
    """
    return math.sqrt(
        sum(
            (point[axis] - (offsets[index - 1][axis] + offsets[index + 1][axis]) / 2) ** 2
            for index, point in enumerate(offsets[1:-1], start=1)
            for axis in (0, 1)
        )
        / (2 * (len(offsets) - 2))
    )


def travel(offsets: list[list[float]]) -> float:
    """The intended motion: where the picture ends up relative to where it started."""
    return max(abs(offsets[-1][0] - offsets[0][0]), abs(offsets[-1][1] - offsets[0][1]))


def main() -> None:
    token = "s" * 48
    with tempfile.TemporaryDirectory(prefix="agentcut-stabilize-") as temp:
        folder = Path(temp)
        plate(folder / "plate.png")
        # The window has to stay inside the plate or FFmpeg clamps it and the fixture stops saying
        # what it claims: the first draft of this check wrote a 60 px pan into an 80 px room and
        # measured 40, then blamed the tracker.
        assert max(window_x(t / FPS) for t in range(int(SECONDS * FPS) + 1)) <= X_ROOM
        assert max(window_y(t / FPS) for t in range(int(SECONDS * FPS) + 1)) <= Y_ROOM
        shake = build(
            folder,
            "shake.mp4",
            "20+20*t+6*sin(8*PI*t)+3*sin(18*PI*t)",
            "25+5*sin(10*PI*t+1)",
        )
        # Same pan, but the smooth shake is replaced by a per-frame jolt of +-8 px.
        jolt = build(folder, "jolt.mp4", f"20+20*t+{ALT_FFMPEG}", "25+5*sin(10*PI*t+1)")
        # A third fixture rolls the whole plate by +-1 degree every frame: the stabiliser has to
        # take the roll off too, or a handheld shot still twitches at its corners.
        rolled = build(
            folder,
            "roll.mp4",
            "20+20*t",
            "25",
            pre=(
                f"rotate=a='(2*mod(floor({FPS}*t),2)-1)*{ROLL:.0f}*PI/180'"
                f":ow={PLATE_W}:oh={PLATE_H}:fillcolor=black@0,"
            ),
        )

        media = MediaService(folder / "db.sqlite3", [folder], folder / "cache", FFMPEG, FFPROBE)
        store = ProjectStore(media.db_path, media)
        probe = media.import_file(str(shake))
        jolt_probe = media.import_file(str(jolt))
        roll_probe = media.import_file(str(rolled))
        client = TestClient(
            create_app(media.db_path, token, media),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {token}"},
        )
        project = store.create(
            CreateProject(
                request_id="new",
                name="stab",
                settings={
                    "width": WIDTH,
                    "height": HEIGHT,
                    "frame_rate": {"numerator": FPS, "denominator": 1},
                },
            )
        ).project
        seed = [
            {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
            {"op": "track.add", "track": {"id": "j", "kind": "video", "name": "j"}},
            {
                "op": "asset.import",
                "asset_id": "shake",
                "label": "shake",
                "probe_id": probe.id,
                "verified": probe.verified.model_dump(),
            },
            {
                "op": "asset.import",
                "asset_id": "jolt",
                "label": "jolt",
                "probe_id": jolt_probe.id,
                "verified": jolt_probe.verified.model_dump(),
            },
            {"op": "track.add", "track": {"id": "h1", "kind": "video", "name": "h1"}},
            {"op": "track.add", "track": {"id": "h2", "kind": "video", "name": "h2"}},
            {
                "op": "clip.add",
                "clip": {
                    "id": "again",
                    "asset_id": "shake",
                    "track_id": "h1",
                    "position_ticks": 0,
                    "duration_ticks": int(SECONDS * T),
                },
            },
            {
                "op": "clip.add",
                "clip": {
                    "id": "tightclip",
                    "asset_id": "shake",
                    "track_id": "h2",
                    "position_ticks": 0,
                    "duration_ticks": int(SECONDS * T),
                },
            },
            {
                "op": "clip.add",
                "clip": {
                    "id": "r",
                    "asset_id": "roll",
                    # On the same track, after the jolt clip: the roll assertions render and measure
                    # the second half of the timeline, and nothing else changes for the clips above.
                    "track_id": "j",
                    "position_ticks": int(SECONDS * T),
                    "duration_ticks": int(SECONDS * T),
                },
            },
            {
                "op": "clip.add",
                "clip": {
                    "id": "hard",
                    "asset_id": "jolt",
                    "track_id": "j",
                    "position_ticks": 0,
                    "duration_ticks": int(SECONDS * T),
                },
            },
            {
                "op": "asset.import",
                "asset_id": "roll",
                "label": "roll",
                "probe_id": roll_probe.id,
                "verified": roll_probe.verified.model_dump(),
            },
            {
                "op": "clip.add",
                "clip": {
                    "id": "c",
                    "asset_id": "shake",
                    "track_id": "v",
                    "position_ticks": 0,
                    "duration_ticks": int(SECONDS * T),
                },
            },
            {
                "op": "clip.add",
                "clip": {
                    "id": "fast",
                    "asset_id": "shake",
                    "track_id": "v",
                    "position_ticks": int(SECONDS * T),
                    # 200% over one second of timeline spends the whole two seconds of source.
                    "duration_ticks": int(SECONDS * T / 2),
                    "speed_percent": 200,
                },
            },
        ]
        with client:
            seeded = client.post(
                f"/v1/projects/{project.id}/edits",
                json={"request_id": "seed", "expected_revision": 0, "commands": seed},
            )
            assert seeded.status_code == 200, seeded.text[:400]
            revision = seeded.json()["project"]["revision"]

            # ---- the measurement, against a fixture whose path is written down ------------------
            motion = measure(
                FFMPEG,
                shake,
                WIDTH,
                HEIGHT,
                project.settings.frame_rate,
                0,
                int(SECONDS * T),
                project.settings.frame_ticks,
            )
            offsets = motion["offsets"]
            # One analysis pixel is the tracker's resolution; anything looser and this check would
            # pass on a measurement that is simply wrong.
            step = WIDTH / motion["analysis_width"] / WIDTH
            worst = max(
                abs(abs(point[axis]) - abs(truth(index + 1)[axis]))
                for index, point in enumerate(offsets)
                for axis in (0, 1)
            )
            assert worst <= 2 * step, (
                f"the tracker is off by {worst:.5f} frames ({worst * WIDTH:.1f} px)"
            )
            # The sign is what makes the correction a correction rather than an echo, but a frame
            # that sits within a pixel of the start has no sign worth naming: only the frames the
            # tracker can actually resolve are compared.
            checked = 0
            for index, point in enumerate(offsets):
                for axis in (0, 1):
                    wanted = truth(index + 1)[axis]
                    if abs(wanted) < 2 * step:
                        continue
                    checked += 1
                    assert point[axis] * wanted > 0, (index, point[axis], wanted)
            assert checked > len(offsets), f"only {checked} frames carried a resolvable sign"
            print(
                f"measured {len(offsets)} frames against the written path: worst magnitude error "
                f"{worst * WIDTH:.1f} px at {step * WIDTH:.1f} px of analysis resolution"
            )

            # ---- dry_run writes nothing ---------------------------------------------------------
            dry = client.post(
                f"/v1/projects/{project.id}/clips/c/stabilize",
                json={"request_id": "dry", "expected_revision": revision, "dry_run": True},
            ).json()
            assert dry["project"]["revision"] == revision + 1, dry["project"]["revision"]
            head = client.get(f"/v1/projects/{project.id}").json()
            assert head["revision"] == revision, "a dry run moved the project head"
            assert not head["clips"]["c"]["keyframes"], "a dry run wrote keyframes"
            assert dry["stabilization"]["written_points"] > 0
            print(
                "dry_run plans "
                f"{dry['stabilization']['written_points']} points and persists none "
                f"(head still r{revision})"
            )

            # ---- the real write, then a render, then the same measurement again ------------------
            def ship(clip_id: str, request_id: str, at: int, body: dict) -> tuple[dict, list]:
                written = client.post(
                    f"/v1/projects/{project.id}/clips/{clip_id}/stabilize",
                    json={"request_id": request_id, "expected_revision": at, **body},
                ).json()
                assert "error" not in written, written
                stored = Project.model_validate(written["project"])
                plan = compile_render_plan(stored, "h264-source-quality")
                out = folder / f"{request_id}.mp4"
                argv = plan.ffmpeg_argv(str(FFMPEG), str(out))
                if request_id == "full":
                    # One keyframe per frame is a graph of tens of kilobytes: this is the render
                    # that has to leave the command line, and the check says so out loud rather
                    # than letting a silent regression back to inline arguments pass anyway.
                    assert plan.graph_in_file, "the stabilised graph went back on the command line"
                    assert "-filter_complex_script" in argv
                    assert plan.text_files["filtergraph.txt"].count("if(lt(") > 100
                for name, body in plan.text_files.items():
                    (folder / name).write_text(body, encoding="utf-8")
                done = subprocess.run(
                    argv,
                    cwd=str(folder),
                    capture_output=True,
                )
                assert done.returncode == 0, done.stderr.decode(errors="replace")[-600:]
                after = measure(
                    FFMPEG,
                    out,
                    WIDTH,
                    HEIGHT,
                    stored.settings.frame_rate,
                    0,
                    int(SECONDS * T),
                    stored.settings.frame_ticks,
                )
                return written, after["offsets"]

            # The jolt clip is the one on top, so the composited frame is its picture: this is the
            # only place the check claims a *delivered* file got steadier, and it is measured on the
            # same anchors as everything else.
            jolted = measure(
                FFMPEG,
                jolt,
                WIDTH,
                HEIGHT,
                project.settings.frame_rate,
                0,
                int(SECONDS * T),
                project.settings.frame_ticks,
            )
            before = wiggle(jolted["offsets"])
            assert before * WIDTH > 4 * step * WIDTH, (
                f"the fixture's own jolt is {before * WIDTH:.1f} px, which the tracker cannot see "
                "off one analysis pixel — the test would be measuring its own noise"
            )
            full, steady = ship("hard", "full", revision, {"strength": 1.0, "max_crop": 0.1})
            after_wiggle = wiggle(steady)
            assert after_wiggle < before * 0.4, (
                f"the delivered picture still wiggles {after_wiggle:.5f} of a frame "
                f"(was {before:.5f})"
            )
            counts: dict[str, int] = {}
            for point in full["project"]["clips"]["hard"]["keyframes"]:
                counts[point["property"]] = counts.get(point["property"], 0) + 1
            notes = full["stabilization"]
            # The compositor scales about the centre and then shifts by `x`, so the layer still
            # covers the frame only while |x| <= (scale-1)/2. That is the inequality the zoom is
            # chosen to satisfy; checking it is what makes "no border" a claim that can fail — the
            # pixel check below cannot see a border at all, because other clips sit underneath.
            zoom = notes["zoom_to_hide_borders"]
            assert zoom >= 1 + 2 * notes["translation_correction"] - 1e-6, notes
            for name in ("x", "y"):
                moved = max(
                    abs(point["value"])
                    for point in full["project"]["clips"]["hard"]["keyframes"]
                    if point["property"] == name
                )
                assert moved <= (zoom - 1) / 2 + 1e-6, (name, moved, zoom)
            expected = {
                "x": notes["written_points"],
                "y": notes["written_points"],
                "scale": 2,
            }
            if notes["roll_correction"] > 0:
                expected["rotation"] = notes["written_points"]
            assert counts == expected, (counts, notes["roll_correction"])
            assert notes["clamped_axes"] == 0, notes
            print(
                f"strength 1.0: shake {before * WIDTH:.1f} px -> "
                f"{after_wiggle * WIDTH:.1f} px in the "
                f"rendered file, {counts['x']}+{counts['y']} keyframes at zoom "
                f"{notes['zoom_to_hide_borders']:.3f}"
            )

            # Strength 0 has to be the shot exactly as it was filmed, and 0.5 exactly half as
            # insistent. Only the full correction is rendered: one clip per claim keeps the layer
            # order out of the argument, and these two are claims about what gets written.
            none = client.post(
                f"/v1/projects/{project.id}/clips/c/stabilize",
                json={
                    "request_id": "none",
                    # The full-strength write above moved the head; start from where it is now.
                    "expected_revision": full["project"]["revision"],
                    "strength": 0.0,
                    "max_crop": 0.1,
                },
            ).json()
            assert none["project"]["clips"]["c"]["keyframes"] == [], "strength 0 wrote keyframes"
            assert none["stabilization"]["translation_correction"] == 0.0, none["stabilization"]
            whole = client.post(
                f"/v1/projects/{project.id}/clips/c/stabilize",
                json={
                    "request_id": "whole",
                    "expected_revision": full["project"]["revision"],
                    "strength": 1.0,
                    "max_crop": 0.1,
                },
            ).json()
            # A second run on a clip that already carries the correction has to refuse, not
            # subtract the same motion twice.
            twice = client.post(
                f"/v1/projects/{project.id}/clips/c/stabilize",
                json={"request_id": "twice", "expected_revision": whole["project"]["revision"]},
            )
            assert twice.status_code == 422, twice.text[:200]
            assert twice.json()["error"]["code"] == "STABILIZE_CONFLICT", twice.text[:200]
            assert set(twice.json()["error"]["details"]["properties"]) >= {"x", "y"}, twice.text
            assert (
                client.get(f"/v1/projects/{project.id}").json()["revision"]
                == whole["project"]["revision"]
            ), "a refused second run still moved the head"
            print(
                "stabilising a clip that already animates x/y/rotation/scale is refused as "
                "STABILIZE_CONFLICT instead of correcting twice"
            )
            half = client.post(
                f"/v1/projects/{project.id}/clips/again/stabilize",
                json={
                    "request_id": "half",
                    "expected_revision": whole["project"]["revision"],
                    "strength": 0.5,
                    "max_crop": 0.1,
                },
            ).json()
            assert (
                abs(
                    half["stabilization"]["translation_correction"]
                    - whole["stabilization"]["translation_correction"] / 2
                )
                < 1e-5
            ), (whole["stabilization"], half["stabilization"])
            print(
                "strength 0 writes no keyframes at all; 0.5 asks for half the correction "
                f"({half['stabilization']['translation_correction']:.5f} vs "
                f"{whole['stabilization']['translation_correction']:.5f} of a frame)"
            )
            revision = half["project"]["revision"]

            # A pan must survive being stabilised, or the feature is a freeze-frame.
            panned = build(folder, "pan.mp4", "20+20*t", "25")
            probe2 = media.import_file(str(panned))
            edit = client.post(
                f"/v1/projects/{project.id}/edits",
                json={
                    "request_id": "pan",
                    "expected_revision": half["project"]["revision"],
                    "commands": [
                        {"op": "track.add", "track": {"id": "pv", "kind": "video", "name": "pv"}},
                        {
                            "op": "asset.import",
                            "asset_id": "pan",
                            "label": "pan",
                            "probe_id": probe2.id,
                            "verified": probe2.verified.model_dump(),
                        },
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "p",
                                "asset_id": "pan",
                                "track_id": "pv",
                                "position_ticks": 0,
                                "duration_ticks": int(SECONDS * T),
                            },
                        },
                    ],
                },
            ).json()["project"]
            wide = measure(
                FFMPEG,
                panned,
                WIDTH,
                HEIGHT,
                project.settings.frame_rate,
                0,
                int(SECONDS * T),
                project.settings.frame_ticks,
            )
            kept = client.post(
                f"/v1/projects/{project.id}/clips/p/stabilize",
                json={"request_id": "pan-stab", "expected_revision": edit["revision"]},
            ).json()
            assert "error" not in kept, kept
            stored = Project.model_validate(kept["project"])
            plan = compile_render_plan(stored, "h264-source-quality")
            out = folder / "panned.mp4"
            pan_argv = plan.ffmpeg_argv(str(FFMPEG), str(out))
            for name, body in plan.text_files.items():
                (folder / name).write_text(body, encoding="utf-8")
            done = subprocess.run(pan_argv, cwd=str(folder), capture_output=True)
            assert done.returncode == 0, done.stderr.decode(errors="replace")[-400:]
            held = measure(
                FFMPEG,
                out,
                WIDTH,
                HEIGHT,
                stored.settings.frame_rate,
                0,
                int(SECONDS * T),
                stored.settings.frame_ticks,
            )
            wanted = travel(wide["offsets"])
            got = travel(held["offsets"])
            assert got >= wanted * 0.7, f"the pan was eaten: {got:.4f} of {wanted:.4f} of a frame"
            assert kept["stabilization"]["smoothing_radius_frames"] == min(
                STABILIZE_SMOOTHING_FRAMES, len(wide["offsets"]) // 4
            )
            print(
                f"a 20 px/s pan keeps {got / wanted * 100:.0f}% of its travel "
                f"({wanted * WIDTH:.1f} px -> {got * WIDTH:.1f} px) while shake comes off"
            )

            # ---- 1.67: the same control has to take a roll off, not only a slide --------------
            turned = measure(
                FFMPEG,
                rolled,
                WIDTH,
                HEIGHT,
                project.settings.frame_rate,
                0,
                int(SECONDS * T),
                project.settings.frame_ticks,
            )
            rolls = turned["rolls"]
            peak = max(range(len(rolls)), key=lambda index: abs(rolls[index]))
            # The measurement is relative to the first frame, and frame 0 sits at −ROLL, so the
            # swing the stabiliser has to find is the full 2·ROLL, not one side of it.
            assert abs(abs(rolls[peak]) - 2 * ROLL) < 0.5, (rolls[peak], 2 * ROLL)
            roll_before = wiggle([[roll, 0.0] for roll in rolls])
            roll_revision = client.get(f"/v1/projects/{project.id}").json()["revision"]
            turned_steady = client.post(
                f"/v1/projects/{project.id}/clips/r/stabilize",
                json={
                    "request_id": "roll",
                    "expected_revision": roll_revision,
                    "strength": 1.0,
                    "max_crop": 0.25,
                },
            ).json()
            assert "error" not in turned_steady, turned_steady
            turned_notes = turned_steady["stabilization"]
            assert abs(turned_notes["measured_roll"] - 2 * ROLL) < 0.5, turned_notes
            written_rotation = {
                point["at_ticks"]: point["value"]
                for point in turned_steady["project"]["clips"]["r"]["keyframes"]
                if point["property"] == "rotation"
            }
            # The correction has to fight the roll, not follow it: at the frame that leaned the most
            # one way, the written angle leans the other.
            at_peak = (peak + 1) * project.settings.frame_ticks
            assert written_rotation[at_peak] * rolls[peak] < 0, (
                written_rotation[at_peak],
                rolls[peak],
            )
            turned_plan = compile_render_plan(
                Project.model_validate(turned_steady["project"]), "h264-source-quality"
            )
            turned_argv = turned_plan.ffmpeg_argv(str(FFMPEG), str(folder / "rolled.mp4"))
            for name, body in turned_plan.text_files.items():
                (folder / name).write_text(body, encoding="utf-8")
            turned_done = subprocess.run(
                turned_argv, cwd=str(folder), capture_output=True, check=False
            )
            assert turned_done.returncode == 0, turned_done.stderr.decode(errors="replace")[-400:]
            held_roll = measure(
                FFMPEG,
                folder / "rolled.mp4",
                WIDTH,
                HEIGHT,
                project.settings.frame_rate,
                int(SECONDS * T),
                int(SECONDS * T),
                project.settings.frame_ticks,
            )
            roll_after = wiggle([[roll, 0.0] for roll in held_roll["rolls"]])
            assert roll_after < roll_before * 0.4, (
                f"the delivered picture still rolls {roll_after:.2f} degrees "
                f"(was {roll_before:.2f})"
            )
            print(
                f"roll: {rolls[peak]:+.2f} degrees of swing relative to frame 0, which is the "
                f"2x{ROLL:g} the fixture alternates by; the exported file rolls "
                f"{roll_after:.2f} degrees instead of {roll_before:.2f}, with the correction "
                "leaning the other way"
            )

            # No border may show: the zoom has to cover the largest correction.
            raw = subprocess.run(
                [
                    str(FFMPEG),
                    "-v",
                    "error",
                    "-i",
                    str(folder / "full.mp4"),
                    "-vf",
                    "crop=2:360:0:0",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "pipe:1",
                ],
                capture_output=True,
            )
            assert raw.returncode == 0, raw.stderr.decode(errors="replace")[-300:]
            # A border the correction failed to hide is a strip of *pure* black down every row of
            # every frame; a dark block in the plate is not, so the count is what means something.
            black = sum(
                1
                for start in range(0, len(raw.stdout), 3)
                if raw.stdout[start : start + 3] == b"\x00\x00\x00"
            )
            pixels = len(raw.stdout) // 3
            assert black < pixels * 0.02, f"{black} of {pixels} edge pixels are pure black"
            print(
                f"the corrected frame keeps picture at its left edge ({black} of {pixels} edge "
                "pixels are pure black)"
            )

            # ---- refusals by name ---------------------------------------------------------------
            audio = client.post(
                f"/v1/projects/{project.id}/edits",
                json={
                    "request_id": "aud",
                    "expected_revision": client.get(f"/v1/projects/{project.id}").json()[
                        "revision"
                    ],
                    "commands": [
                        {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "a"}},
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "tone",
                                "asset_id": "shake",
                                "track_id": "a",
                                "position_ticks": 0,
                                "duration_ticks": int(SECONDS * T),
                            },
                        },
                    ],
                },
            ).json()["project"]["revision"]
            refused = client.post(
                f"/v1/projects/{project.id}/clips/tone/stabilize",
                json={"request_id": "no-audio", "expected_revision": audio},
            )
            assert refused.status_code == 422, refused.text[:200]
            assert refused.json()["error"]["code"] == "STABILIZE_INVALID", refused.text[:200]
            sped = client.post(
                f"/v1/projects/{project.id}/clips/fast/stabilize",
                json={"request_id": "no-speed", "expected_revision": audio},
            )
            assert sped.status_code == 422, sped.text[:200]
            assert sped.json()["error"]["code"] == "STABILIZE_INVALID", sped.text[:200]
            assert client.get(f"/v1/projects/{project.id}").json()["revision"] == audio
            print(
                "an audio clip and a 200% clip are both refused as "
                "STABILIZE_INVALID without moving "
                "the head"
            )

            # A crop budget of 0 cannot hide anything: the plan has to say so rather than lie.
            tight = client.post(
                f"/v1/projects/{project.id}/clips/tightclip/stabilize",
                json={
                    "request_id": "tight",
                    "expected_revision": audio,
                    "strength": 1.0,
                    "max_crop": 0.0,
                },
            ).json()
            assert tight["stabilization"]["clamped_axes"] > 0, tight["stabilization"]
            assert "warning" in tight["stabilization"], tight["stabilization"]
            print(
                "max_crop 0 reports "
                f"{tight['stabilization']['clamped_axes']} clamped axes and says why"
            )

            # A retry — the same request_id, with the same payload or another one — must not write a
            # second correction. The guard on the clip's own keyframes answers before the receipt
            # layer does, so both doors close with the reason named, and the document is left
            # exactly as the first run put it.
            written = tight["project"]["clips"]["tightclip"]["keyframes"]
            head = tight["project"]["revision"]
            for label, body in (
                (
                    "same payload",
                    {
                        "request_id": "tight",
                        "expected_revision": head,
                        "strength": 1.0,
                        "max_crop": 0.0,
                    },
                ),
                (
                    "other strength",
                    {"request_id": "tight", "expected_revision": head, "strength": 0.5},
                ),
            ):
                again = client.post(
                    f"/v1/projects/{project.id}/clips/tightclip/stabilize", json=body
                )
                assert again.status_code == 422, (label, again.text[:200])
                assert again.json()["error"]["code"] == "STABILIZE_CONFLICT", (
                    label,
                    again.text[:200],
                )
            current = client.get(f"/v1/projects/{project.id}").json()
            assert current["revision"] == head, "a retried stabilisation moved the head"
            assert current["clips"]["tightclip"]["keyframes"] == written, (
                "a retried stabilisation changed the keyframes"
            )
            print(
                "a retried request_id is refused by name whichever way it arrives, head and "
                "keyframes untouched"
            )

            # Every way an Agent can point this at nothing has to answer by name, not with a 500.
            untouched = client.get(f"/v1/projects/{project.id}").json()["revision"]
            for clip_id, expect in (("ghost", "NOT_FOUND"), ("c", "INVALID_REQUEST")):
                answer = client.post(
                    f"/v1/projects/{project.id}/clips/{clip_id}/stabilize",
                    json={
                        "request_id": f"probe-{clip_id}-{expect}",
                        "expected_revision": untouched,
                        "strength": 4 if expect == "INVALID_REQUEST" else 1,
                    },
                )
                assert answer.status_code == expect_status(expect), answer.text[:200]
                assert answer.json()["error"]["code"] == expect, answer.text[:200]
            head = client.get(f"/v1/projects/{project.id}").json()["revision"]
            assert head == untouched, f"a refused probe moved the head to {head}"
            print(
                "a clip that does not exist and a strength of 4 are refused by name, head unmoved"
            )

            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["clip_stabilize"] is True, caps["features"]
            assert caps["limits"]["stabilize_max_crop"] == 0.25, caps["limits"]
            schema = client.get("/openapi.json").json()
            assert "/v1/projects/{project_id}/clips/{clip_id}/stabilize" in schema["paths"]
            print("capabilities publish clip_stabilize and the OpenAPI document names the route")
        print(
            "PASS: the tracker recovers a written camera path to within "
            f"{worst * WIDTH:.1f} px, the rendered file after stabilising wiggles "
            f"{after_wiggle * WIDTH:.1f} px instead of {before * WIDTH:.1f} px and rolls "
            f"{roll_after:.2f} degrees instead of {roll_before:.2f}; a 20 px/s pan keeps "
            f"{got / wanted * 100:.0f}% of its travel, strength 0 writes nothing, borders stay "
            "covered, and audio/speed/max_crop cases are refused by name"
        )


if __name__ == "__main__":
    main()
