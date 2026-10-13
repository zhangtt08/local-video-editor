"""Speed curves: one rate profile compiles into constant-rate pieces shared by FFmpeg and preview.

The pieces are the contract between exporter and browser, so this check measures real decoded
pixels against the plan the exporter was handed, and proves the input window is wide enough.
"""

import hashlib
import json
import math
import struct
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import Clip, EditBatch, Project, SpeedPoint
from agentcut.http_api import create_app
from agentcut.render import compile_render_plan
from agentcut.speed import (
    MAX_SEGMENTS,
    base_source_ticks,
    consumed_source_ticks,
    describe,
    scale_curve,
    segments,
    slice_curve,
)

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
FRAME = T // 30
U_CURVE = [
    {"at_ticks": 0, "percent": 100},
    {"at_ticks": 2 * T, "percent": 25},
    {"at_ticks": 4 * T, "percent": 100},
]
FREEZE = [
    {"at_ticks": 0, "percent": 100},
    {"at_ticks": 2 * T, "percent": 100},
    {"at_ticks": 2 * T + FRAME, "percent": 0},
    {"at_ticks": 4 * T, "percent": 0},
]


def run(args: list[str], timeout: int = 240) -> bytes:
    result = subprocess.run(
        [str(FFMPEG), "-v", "error", *args],
        capture_output=True,
        timeout=timeout,
        creationflags=0x08000000,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")[-800:]
    return result.stdout


def duration_of(video: Path) -> float:
    raw = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_format", "-of", "json", str(video)],
        capture_output=True,
        timeout=60,
        creationflags=0x08000000,
    )
    return float(json.loads(raw.stdout)["format"]["duration"])


def ramp_source(folder: Path, name: str, seconds: int) -> Path:
    """Red climbs 0..255 across the whole file while a 440 Hz tone plays."""
    path = folder / name
    run(
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"nullsrc=s=320x180:r=30:d={seconds},format=rgb24,geq=r='255*T/{seconds}':g='40':b='40'",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}:sample_rate=48000",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-g",
            "30",
            "-c:a",
            "aac",
            str(path),
        ]
    )
    return path


def clip_project(source: Path, curve: list[dict], duration: int, speed: int = 100) -> Project:
    ticks = int(round(duration_of(source) * T))
    verified = {
        "probe_id": "a",
        "path": str(source),
        "kind": "video",
        "label": "ramp",
        "size_bytes": source.stat().st_size,
        "content_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "duration_ticks": ticks,
        "width": 320,
        "height": 180,
        "has_audio": True,
    }
    return Project.model_validate(
        {
            "id": "p",
            "name": "ramp",
            "settings": {"width": 320, "height": 180, "frame_rate": {"numerator": 30}},
            "tracks": [{"id": "v", "kind": "video", "name": "v"}],
            "assets": {
                "a": {
                    "id": "a",
                    "kind": "video",
                    "label": "ramp",
                    "reference": "unused",
                    "duration_ticks": ticks,
                    "verified": verified,
                }
            },
            "clips": {
                "c": {
                    "id": "c",
                    "asset_id": "a",
                    "track_id": "v",
                    "position_ticks": 0,
                    "duration_ticks": duration,
                    "speed_percent": speed,
                    "speed_curve": curve,
                }
            },
        }
    )


def render(project: Project, folder: Path, name: str) -> Path:
    out = folder / name
    plan = compile_render_plan(project, "h264-source-quality")
    job = folder / (name + ".job")
    job.mkdir(exist_ok=True)
    for file_name, body in plan.text_files.items():
        (job / file_name).write_text(body, encoding="utf-8")
    for file_name, body in plan.binary_files.items():
        (job / file_name).write_bytes(body)
    result = subprocess.run(
        plan.ffmpeg_argv(str(FFMPEG), str(out)),
        cwd=job,
        capture_output=True,
        timeout=600,
        creationflags=0x08000000,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")[-1500:]
    return out


def red_at(video: Path, at: float) -> float:
    raw = run(
        [
            "-ss",
            f"{at:.6f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            "crop=8:8:160:90",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )
    assert len(raw) == 8 * 8 * 3, len(raw)
    return sum(raw[3 * index] for index in range(len(raw) // 3)) / (len(raw) // 3)


def pcm(video: Path, at: float, span: float) -> list[int]:
    raw = run(
        [
            "-ss",
            f"{at:.6f}",
            "-t",
            f"{span:.6f}",
            "-i",
            str(video),
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            "48000",
            "pipe:1",
        ]
    )
    return list(struct.unpack(f"<{len(raw) // 2}h", raw))


def mean_abs(video: Path, at: float) -> float:
    samples = pcm(video, at, 0.2)
    assert len(samples) > 4000, len(samples)
    return sum(abs(value) for value in samples) / len(samples)


def pitch_at(video: Path, at: float) -> int:
    samples = pcm(video, at, 0.2)
    assert len(samples) > 4000, len(samples)
    best, bestf = 0.0, 0
    for frequency in range(200, 700):
        magnitude = abs(
            sum(
                value * math.cos(2 * math.pi * frequency * index / 48000)
                for index, value in enumerate(samples)
            )
            / len(samples)
        )
        if magnitude > best:
            best, bestf = magnitude, frequency
    return bestf


def expected_source(plan: list[dict], at: float) -> float:
    """The browser-side reading of the same piece list: rate is constant inside a piece."""
    piece = next((mark for mark in plan if at < mark["at"] + mark["duration"]), plan[-1])
    elapsed = min(max(0.0, at - piece["at"]), piece["duration"])
    return piece["source_at"] + elapsed * piece["rate_percent"] / 100


def timed(clip: Clip, curve: list[dict], duration: int) -> Clip:
    clone = deepcopy(clip)
    clone.speed_curve = [SpeedPoint.model_validate(point) for point in curve]
    clone.duration_ticks = duration
    return clone


def compiler_suite() -> None:
    clip = Project.model_validate(
        {
            "id": "p",
            "name": "c",
            "settings": {"width": 320, "height": 180},
            "tracks": [{"id": "v", "kind": "video", "name": "v"}],
            "assets": {
                "a": {
                    "id": "a",
                    "kind": "video",
                    "label": "a",
                    "reference": "r",
                    "duration_ticks": 20 * T,
                }
            },
            "clips": {
                "c": {
                    "id": "c",
                    "asset_id": "a",
                    "track_id": "v",
                    "position_ticks": 0,
                    "duration_ticks": 4 * T,
                }
            },
        }
    ).clips["c"]

    plain = segments(clip, FRAME)
    assert plain == [{"timeline": 4 * T, "source": 4 * T, "rate_percent": 100}], plain
    assert base_source_ticks(clip) == consumed_source_ticks(clip, FRAME) == 4 * T

    flat = timed(clip, U_CURVE, 4 * T)
    pieces = segments(flat, FRAME)
    assert sum(piece["timeline"] for piece in pieces) == flat.duration_ticks
    assert (
        sum(piece["source"] for piece in pieces) == consumed_source_ticks(flat, FRAME) == 5 * T // 2
    )
    assert all(piece["timeline"] % FRAME == 0 for piece in pieces), pieces
    assert all(piece["source"] % FRAME == 0 for piece in pieces), pieces
    assert len(pieces) <= MAX_SEGMENTS, len(pieces)
    rates = [piece["rate_percent"] for piece in pieces]
    low = rates.index(min(rates))
    assert all(a >= b for a, b in zip(rates[: low + 1], rates[1 : low + 1])), rates
    assert all(a <= b for a, b in zip(rates[low:], rates[low + 1 :])), rates
    assert abs(low - (len(rates) - 1) / 2) <= 1, rates
    assert rates[0] == rates[-1] == 90 and 25 <= min(rates) <= 35, rates
    assert all(piece["timeline"] >= FRAME for piece in pieces), pieces
    for piece in pieces:
        assert abs(piece["source"] / piece["timeline"] * 100 - piece["rate_percent"]) <= 1, piece

    plan = describe(pieces, T)
    assert plan[0]["at"] == 0.0, plan
    assert abs(plan[-1]["source_at"] + plan[-1]["source_duration"] - 2.5) < 1e-9, plan
    for index, mark in enumerate(plan):
        assert abs(mark["at"] - sum(other["duration"] for other in plan[:index])) < 1e-9, plan
        assert (
            abs(mark["source_at"] - sum(other["source_duration"] for other in plan[:index])) < 1e-9
        ), plan
    assert abs(sum(mark["duration"] for mark in plan) - 4.0) < 1e-9, plan
    assert abs(expected_source(plan, 2.0) - 1.25) * T <= FRAME, (
        "half way only 1.25s of source is read"
    )
    assert expected_source(plan, 4.0) > expected_source(plan, 3.0) > expected_source(plan, 2.0)

    # Sound switches rate on the picture's frame boundaries: 83 ms slivers would seam-click.
    sample = T // 48_000
    audio = segments(flat, sample, FRAME)
    assert len(audio) <= 12, [piece["rate_percent"] for piece in audio]
    assert all(piece["timeline"] % FRAME == 0 for piece in audio), audio
    assert all(piece["source"] % sample == 0 for piece in audio), audio
    assert sum(piece["timeline"] for piece in audio) == flat.duration_ticks
    assert sum(piece["source"] for piece in audio) == consumed_source_ticks(flat, sample)
    assert [piece["rate_percent"] for piece in segments(flat, FRAME, FRAME)] == rates, (
        "the picture plan must not change when the marks clock is passed explicitly",
    )

    hold = timed(clip, FREEZE, 4 * T)
    pieces = segments(hold, FRAME)
    assert pieces[-1]["rate_percent"] == 0 and pieces[-1]["source"] == 0, pieces
    assert pieces[0]["rate_percent"] == 100, pieces
    assert sum(piece["source"] for piece in pieces) == consumed_source_ticks(hold, FRAME)
    assert sum(piece["timeline"] for piece in pieces) == 4 * T

    fast = timed(
        clip, [{"at_ticks": 0, "percent": 300}, {"at_ticks": 4 * T, "percent": 300}], 4 * T
    )
    assert consumed_source_ticks(fast, FRAME) == 12 * T, consumed_source_ticks(fast, FRAME)
    assert [piece["rate_percent"] for piece in segments(fast, FRAME)] == [300]

    sawtooth = [
        {"at_ticks": index * T // 2, "percent": 400 if index % 2 == 0 else 5} for index in range(8)
    ] + [{"at_ticks": 4 * T, "percent": 100}]
    steep = timed(clip, sawtooth, 4 * T)
    pieces = segments(steep, FRAME)
    assert len(pieces) <= MAX_SEGMENTS, len(pieces)
    assert sum(piece["timeline"] for piece in pieces) == 4 * T
    assert sum(piece["source"] for piece in pieces) == consumed_source_ticks(steep, FRAME)

    # Slicing keeps the surviving window's consumption, so split and trim cannot invent source time.
    long_curve = [{"at_ticks": 0, "percent": 100}, {"at_ticks": 6 * T, "percent": 20}]
    head, tail = T, 5 * T
    first = consumed_source_ticks(timed(clip, slice_curve(long_curve, 0, head), head), FRAME)
    second = consumed_source_ticks(
        timed(clip, slice_curve(long_curve, head, tail), tail - head), FRAME
    )
    total = consumed_source_ticks(timed(clip, slice_curve(long_curve, 0, tail), tail), FRAME)
    assert abs(first + second - total) <= FRAME, (first, second, total)
    assert abs(total - 10 * T // 3) <= FRAME, total
    piece = slice_curve(long_curve, head, tail)
    assert piece[0]["at_ticks"] == 0 and piece[-1]["at_ticks"] == tail - head, piece
    assert abs(consumed_source_ticks(timed(clip, long_curve, 6 * T), FRAME) - 18 * T // 5) <= FRAME
    scaled = scale_curve(long_curve, 2, 1)
    assert [mark["at_ticks"] for mark in scaled] == [0, 12 * T], scaled
    assert [mark["percent"] for mark in scaled] == [100, 20]


def http_suite(folder: Path) -> None:
    token = "ramp-" + "c" * 48
    with TestClient(
        create_app(folder / "db.sqlite3", token),
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        capabilities = client.get("/v1/capabilities").json()
        assert capabilities["features"]["speed_curve"] is True
        assert "clip.speed_curve" in capabilities["commands"]
        schema = json.dumps(EditBatch.model_json_schema())
        assert "clip.speed_curve" in schema and "at_ticks" in schema, (
            "MCP builds its command schema from this contract"
        )

        project = client.post("/v1/projects", json={"request_id": "new", "name": "ramp"}).json()[
            "project"
        ]
        path = f"/v1/projects/{project['id']}"

        def edit(request_id, revision, commands, dry=False):
            return client.post(
                path + "/edits",
                json={
                    "request_id": request_id,
                    "expected_revision": revision,
                    "commands": commands,
                    "dry_run": dry,
                },
            )

        seed = edit(
            "seed",
            0,
            [
                {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                {"op": "track.add", "track": {"id": "w", "kind": "video", "name": "w"}},
                {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "a"}},
                {
                    "op": "asset.register",
                    "asset": {
                        "id": "m",
                        "kind": "video",
                        "label": "m",
                        "reference": "r",
                        "duration_ticks": 10 * T,
                    },
                },
                {
                    "op": "asset.register",
                    "asset": {
                        "id": "s",
                        "kind": "audio",
                        "label": "s",
                        "reference": "r",
                        "duration_ticks": 10 * T,
                    },
                },
                {
                    "op": "asset.register",
                    "asset": {
                        "id": "i",
                        "kind": "image",
                        "label": "i",
                        "reference": "r",
                        "duration_ticks": 10 * T,
                    },
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "c",
                        "asset_id": "m",
                        "track_id": "v",
                        "position_ticks": 0,
                        "duration_ticks": 4 * T,
                    },
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "e",
                        "asset_id": "m",
                        "track_id": "w",
                        "position_ticks": 0,
                        "duration_ticks": 4 * T,
                    },
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "d",
                        "asset_id": "s",
                        "track_id": "a",
                        "position_ticks": 0,
                        "duration_ticks": 4 * T,
                    },
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "still",
                        "asset_id": "i",
                        "track_id": "v",
                        "position_ticks": 6 * T,
                        "duration_ticks": T,
                    },
                },
            ],
        )
        assert seed.status_code == 200, seed.text

        command = {"op": "clip.speed_curve", "clip_id": "c", "points": U_CURVE}
        first = edit("r1", 1, [command])
        assert first.status_code == 200, first.text
        saved = first.json()["project"]["clips"]["c"]["speed_curve"]
        assert [mark["percent"] for mark in saved] == [100, 25, 100], saved

        replay = edit("r1", 1, [command])
        assert replay.json()["replayed"] is True and replay.json()["project"]["revision"] == 2

        conflict = edit("r2", 1, [{"op": "clip.speed_curve", "clip_id": "c", "points": None}])
        assert conflict.status_code == 409, conflict.text

        dry = edit("r3", 2, [{"op": "clip.speed_curve", "clip_id": "c", "points": None}], dry=True)
        assert dry.status_code == 200 and not dry.json()["committed"], dry.text
        assert dry.json()["project"]["clips"]["c"]["speed_curve"] is None
        assert client.get(path).json()["revision"] == 2, "a dry run must not write"
        assert client.get(path).json()["clips"]["c"]["speed_curve"][1]["percent"] == 25

        manifest = client.post("/v1/preview-manifest", json=first.json()["project"]).json()
        plan = manifest["clips"]["c"]["speed"]
        assert manifest["clips"]["still"]["speed"] is None, "an image clip has no ramp"
        assert abs(sum(mark["duration"] for mark in plan) - 4.0) < 1e-6, plan
        assert abs(expected_source(plan, 2.0) - 1.25) * T <= FRAME, plan

        for label, points in (
            ("r4a", [{"at_ticks": FRAME, "percent": 50}, {"at_ticks": 4 * T, "percent": 100}]),
            (
                "r4b",
                [
                    {"at_ticks": 0, "percent": 100},
                    {"at_ticks": FRAME, "percent": 100},
                    {"at_ticks": FRAME, "percent": 50},
                ],
            ),
            ("r4c", [{"at_ticks": 0, "percent": 401}, {"at_ticks": 4 * T, "percent": 100}]),
            ("r4d", [{"at_ticks": 0, "percent": 100}, {"at_ticks": 40 * T, "percent": 100}]),
            ("r4e", [{"at_ticks": 0, "percent": 100}]),
            ("r4f", [{"at_ticks": 0, "percent": -1}, {"at_ticks": 4 * T, "percent": 100}]),
        ):
            bad = edit(label, 2, [{"op": "clip.speed_curve", "clip_id": "c", "points": points}])
            assert bad.status_code == 422, (label, bad.text)
        assert client.get(path).json()["revision"] == 2, "rejected curves must not write"

        overflow = edit(
            "r5",
            2,
            [
                {
                    "op": "clip.speed_curve",
                    "clip_id": "c",
                    "points": [
                        {"at_ticks": 0, "percent": 400},
                        {"at_ticks": 4 * T, "percent": 400},
                    ],
                }
            ],
        )
        assert overflow.json()["error"]["code"] == "SOURCE_OUT_OF_BOUNDS", overflow.text
        assert client.get(path).json()["revision"] == 2

        still = edit("r6", 2, [{"op": "clip.speed_curve", "clip_id": "still", "points": U_CURVE}])
        assert still.json()["error"]["code"] == "INVALID_SPEED", still.text

        linked = edit("r6b", 2, [{"op": "clips.link", "clip_ids": ["d", "e"], "link_id": "av"}])
        assert linked.status_code == 200, linked.text
        assert client.get(path).json()["revision"] == 3
        mixed = edit("r6c", 3, [{"op": "clip.speed_curve", "clip_id": "d", "points": U_CURVE}])
        assert mixed.json()["error"]["code"] == "INVALID_SPEED", mixed.text
        assert client.get(path).json()["revision"] == 3, "a linked pair cannot take one-sided ramp"
        unlink = edit("r6d", 3, [{"op": "clips.link", "clip_ids": ["d", "e"], "link_id": None}])
        assert unlink.status_code == 200, unlink.text

        locked = edit(
            "r7",
            4,
            [
                {"op": "track.update", "track_id": "v", "locked": True},
                {"op": "clip.speed_curve", "clip_id": "c", "points": None},
            ],
        )
        assert locked.json()["error"]["code"] == "TRACK_LOCKED", locked.text
        assert client.get(path).json()["revision"] == 4, "a locked batch must not write"
        assert (
            edit("r8", 4, [{"op": "track.update", "track_id": "v", "locked": False}]).status_code
            == 200
        )

        split = edit(
            "r9",
            5,
            [{"op": "clip.split", "clip_id": "c", "at_ticks": 2 * T, "right_clip_id": "c2"}],
        )
        assert split.status_code == 200, split.text
        clips = split.json()["project"]["clips"]
        left, right = clips["c"], clips["c2"]
        assert right["speed_curve"][0]["at_ticks"] == 0, right["speed_curve"]
        assert [mark["percent"] for mark in right["speed_curve"]] == [25, 100], right["speed_curve"]
        assert left["duration_ticks"] == right["duration_ticks"] == 2 * T
        halves = consumed_source_ticks(Clip.model_validate(left), FRAME) + consumed_source_ticks(
            Clip.model_validate(right), FRAME
        )
        assert abs(halves - 5 * T // 2) <= 2 * FRAME, halves
        assert right["source_in_ticks"] == left["source_in_ticks"] + consumed_source_ticks(
            Clip.model_validate(left), FRAME
        ), (right["source_in_ticks"], left)

        slower = edit("r10", 6, [{"op": "clip.speed", "clip_id": "c2", "speed_percent": 200}])
        assert slower.status_code == 200, slower.text
        moved = slower.json()["project"]["clips"]["c2"]
        assert moved["duration_ticks"] == T, moved["duration_ticks"]
        assert moved["speed_curve"][-1]["at_ticks"] == moved["duration_ticks"], moved["speed_curve"]
        assert [mark["percent"] for mark in moved["speed_curve"]] == [25, 100], (
            "the base speed scales the time axis, not the rate profile"
        )
        assert consumed_source_ticks(Clip.model_validate(moved), FRAME) == consumed_source_ticks(
            Clip.model_validate(right), FRAME
        ), "doubling the base speed must keep the same source window"

        cleared = edit("r11", 7, [{"op": "clip.speed_curve", "clip_id": "c", "points": None}])
        assert cleared.json()["project"]["clips"]["c"]["speed_curve"] is None

        history = client.get(path + "/history").json()["history"]
        target = next(entry["revision"] for entry in history if entry["revision"] == 2)
        restore = client.post(
            path + "/restore",
            json={"request_id": "r12", "expected_revision": 8, "target_revision": target},
        )
        assert restore.status_code == 200, restore.text
        back = restore.json()["project"]
        assert back["revision"] == 9, "a restore must create a new revision"
        assert [mark["percent"] for mark in back["clips"]["c"]["speed_curve"]] == [100, 25, 100]


def media_suite(folder: Path) -> None:
    four = ramp_source(folder, "ramp4.mp4", 4)
    six = ramp_source(folder, "ramp6.mp4", 6)

    project = clip_project(four, U_CURVE, 4 * T)
    plan = describe(segments(project.clips["c"], FRAME), T)
    video = render(project, folder, "ramp-u.mp4")
    assert abs(duration_of(video) - 4.0) < 1 / 30, duration_of(video)
    for at in (0.5, 1.0, 2.0, 3.0, 3.9):
        want = 255 * expected_source(plan, at) / 4
        got = red_at(video, at)
        assert abs(got - want) <= 6, (at, got, want)
    # The five points above sit near the segment ends. A curve can be right at every knot and wrong
    # in the middle of a piece, so sweep the whole export: every tenth of a second, and record the
    # worst offender rather than stopping at the first.
    swept = []
    for step in range(1, 40):
        at = step / 10
        want = 255 * expected_source(plan, at) / 4
        drift = abs(red_at(video, at) - want)
        swept.append((drift, at, want))
    worst = max(swept)
    assert worst[0] <= 8, f"the ramp drifts {worst[0]:.1f} levels at {worst[1]}s"
    print(
        f"   curve reads true across the export: {len(swept)} probes, worst {worst[0]:.1f} levels"
        f" (at {worst[1]}s)"
    )
    assert abs(red_at(video, 2.0) - 255 * 2.0 / 4) > 30, (
        "a curve the graph ignored sits at the linear level"
    )
    assert 436 <= pitch_at(video, 1.0) <= 444, "atempo must keep the pitch while it shortens audio"

    hold = render(clip_project(four, FREEZE, 4 * T), folder, "ramp-freeze.mp4")
    assert abs(duration_of(hold) - 4.0) < 1 / 30, duration_of(hold)
    tail = [red_at(hold, at) for at in (2.2, 2.6, 3.0, 3.5, 3.95)]
    assert max(tail) - min(tail) <= 1, ("the frozen tail must hold one frame", tail)
    assert 255 * 1.85 / 4 < tail[0] < 255 * 2.15 / 4 + 1, tail
    quiet, loud = mean_abs(hold, 3.0), mean_abs(hold, 0.5)
    assert quiet < 200 < loud, ("the freeze is silent while the moving head is not", quiet, loud)

    # A 300% curve reads three times its timeline of source: the input window has to cover it.
    fast = [{"at_ticks": 0, "percent": 300}, {"at_ticks": 2 * T, "percent": 300}]
    quick = render(clip_project(six, fast, 2 * T), folder, "ramp-fast.mp4")
    assert abs(duration_of(quick) - 2.0) < 1 / 30, duration_of(quick)
    assert red_at(quick, 0.5) < red_at(quick, 1.5) < red_at(quick, 1.9)
    assert red_at(quick, 1.9) > 240, "the ramp must reach the end of the six second source"
    assert 436 <= pitch_at(quick, 1.0) <= 444, pitch_at(quick, 1.0)
    argv = " ".join(
        compile_render_plan(clip_project(six, fast, 2 * T), "h264-source-quality").input_args
    )
    assert "-ss 0.000000 -t 6.000000" in argv, argv

    graph = "\n".join(compile_render_plan(project, "h264-source-quality").filters)
    assert "concat=n=" in graph and "setpts=(PTS-STARTPTS)*" in graph, graph[:400]
    assert all(piece["rate_percent"] > 0 for piece in segments(project.clips["c"], FRAME))
    assert graph.count("[") == graph.count("]"), graph[:400]
    frozen_graph = "\n".join(
        compile_render_plan(clip_project(four, FREEZE, 4 * T), "h264-source-quality").filters
    )
    assert "tpad=stop_mode=clone" in frozen_graph and "apad=whole_dur=" in frozen_graph
    assert "trim=start=1.966666667:end=2.000000000" in frozen_graph, (
        "the freeze holds the last real frame"
    )


def main():
    with tempfile.TemporaryDirectory(prefix="agentcut-ramp-") as scratch:
        folder = Path(scratch)
        compiler_suite()
        http_suite(folder)
        media_suite(folder)
    print(
        "PASS: segment invariants, atomic HTTP edits/replay/locks/rejections, split and base-speed "
        "interaction, real ramp pixels, freeze silence and a 300% source window"
    )


if __name__ == "__main__":
    main()
