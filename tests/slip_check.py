"""Slip and slide: two edits a human does with the mouse and an Agent does with two integers.

Both are asserted in exact frame ticks, and the exported pixels are decoded to prove what reaches
the screen moved by exactly the requested amount — a slide that only looked right inside the project
state would still cut at the wrong frame.
"""

import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import (
    Asset,
    Clip,
    CreateProject,
    EditBatch,
    EditorError,
    FrameRate,
    Keyframe,
    Project,
    SequenceSettings,
    Track,
    VerifiedMedia,
)
from agentcut.http_api import create_app
from agentcut.projects import ProjectStore
from agentcut.render import compile_render_plan
from agentcut.timeline import apply_commands, validate_timeline

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
WIDTH, HEIGHT, FPS = 320, 180, 25
FRAME = T // FPS
SOURCE_SECONDS = 4


def frames(count: int) -> int:
    return count * T // FPS


def clip(clip_id: str, start: int, length: int, source: int = 0, **changes) -> Clip:
    return Clip(
        id=clip_id,
        asset_id="a",
        track_id="v",
        position_ticks=frames(start),
        duration_ticks=frames(length),
        source_in_ticks=frames(source),
        **changes,
    )


def project(clips: list[Clip] | None = None, source_seconds: int = 200) -> Project:
    return Project(
        id="p",
        name="slip",
        settings=SequenceSettings(
            frame_rate=FrameRate(numerator=FPS, denominator=1), width=WIDTH, height=HEIGHT
        ),
        tracks=[Track(id="v", kind="video", name="v")],
        assets={
            "a": Asset(
                id="a",
                kind="video",
                label="a",
                reference="r",
                duration_ticks=frames(source_seconds),
            )
        },
        clips={item.id: item for item in (clips or default_clips())},
    )


def default_clips() -> list[Clip]:
    return [clip("l", 0, 40), clip("m", 40, 40, 60), clip("r", 80, 40, 120)]


def edit(target: Project, commands: list) -> Project:
    batch = EditBatch(request_id="check", expected_revision=target.revision, commands=commands)
    return apply_commands(target, batch.commands)


def table(target: Project) -> list[tuple[int, int, int]]:
    return [
        (item.position_ticks, item.source_in_ticks, item.duration_ticks)
        for item in sorted(target.clips.values(), key=lambda found: found.position_ticks)
    ]


def refused(actions: list, code: str) -> str:
    try:
        for target in actions:
            edit(target[0], target[1])
    except EditorError as error:
        assert error.code == code, (code, error.code, error.message)
        return error.message
    raise AssertionError(f"{code} was expected but the edit went through")


def reducer_suite() -> None:
    start = project()
    validate_timeline(start)

    forward = edit(start, [{"op": "clip.slip", "clip_id": "m", "source_offset_ticks": frames(10)}])
    assert table(forward) == [
        (0, 0, frames(40)),
        (frames(40), frames(70), frames(40)),
        (frames(80), frames(120), frames(40)),
    ], table(forward)
    back = edit(start, [{"op": "clip.slip", "clip_id": "m", "source_offset_ticks": -frames(50)}])
    assert table(back)[1] == (frames(40), frames(10), frames(40)), table(back)
    assert table(back)[0] == table(start)[0] and table(back)[2] == table(start)[2]

    right = edit(start, [{"op": "clip.slide", "clip_id": "m", "delta_ticks": frames(10)}])
    assert table(right) == [
        (0, 0, frames(50)),
        (frames(50), frames(60), frames(40)),
        (frames(90), frames(130), frames(30)),
    ], table(right)
    left = edit(start, [{"op": "clip.slide", "clip_id": "m", "delta_ticks": -frames(10)}])
    assert table(left) == [
        (0, 0, frames(30)),
        (frames(30), frames(60), frames(40)),
        (frames(70), frames(110), frames(50)),
    ], table(left)
    total = lambda target: max(  # noqa: E731
        item.position_ticks + item.duration_ticks for item in target.clips.values()
    )
    assert total(right) == total(start) == total(left) == frames(120), (
        "a slide never changes length"
    )

    # The middle clip's animation clock travels with the clip; the neighbours keep their own.
    marked = project(
        [
            clip("l", 0, 40),
            clip(
                "m",
                40,
                40,
                60,
                keyframes=[Keyframe(property="x", at_ticks=frames(10), value=0.5)],
                animation_offset_ticks=frames(40),
            ),
            clip("r", 80, 40, 120),
        ]
    )
    slid = edit(marked, [{"op": "clip.slide", "clip_id": "m", "delta_ticks": frames(6)}])
    mover = slid.clips["m"]
    assert mover.animation_offset_ticks == frames(46) and mover.keyframes[0].at_ticks == frames(10)
    assert slid.clips["l"].animation_offset_ticks == marked.clips["l"].animation_offset_ticks
    slipped = edit(marked, [{"op": "clip.slip", "clip_id": "m", "source_offset_ticks": frames(5)}])
    assert slipped.clips["m"].animation_offset_ticks == frames(40), "a slip does not move the clock"

    assert "non-zero" in refused(
        [(start, [{"op": "clip.slide", "clip_id": "m", "delta_ticks": 0}])], "INVALID_SLIDE"
    )
    assert "both ends" in refused(
        [(start, [{"op": "clip.slide", "clip_id": "l", "delta_ticks": frames(5)}])], "INVALID_SLIDE"
    )
    assert "too short" in refused(
        [(start, [{"op": "clip.slide", "clip_id": "m", "delta_ticks": frames(40)}])],
        "INVALID_SLIDE",
    )
    curved = project(
        [
            clip("l", 0, 40),
            clip(
                "m",
                40,
                40,
                60,
                speed_curve=[
                    {"at_ticks": 0, "percent": 100},
                    {"at_ticks": frames(40), "percent": 100},
                ],
            ),
            clip("r", 80, 40, 120),
        ]
    )
    assert curved.clips["m"].speed_curve, "the fixture needs a real curve"
    assert "curve" in refused(
        [(curved, [{"op": "clip.slip", "clip_id": "m", "source_offset_ticks": frames(5)}])],
        "INVALID_SLIP",
    )
    assert "curve" in refused(
        [(curved, [{"op": "clip.slide", "clip_id": "m", "delta_ticks": frames(5)}])],
        "INVALID_SLIDE",
    )
    assert "source" in refused(
        [(start, [{"op": "clip.slip", "clip_id": "r", "source_offset_ticks": frames(60)}])],
        "SOURCE_OUT_OF_BOUNDS",
    )
    assert "head" in refused(
        [(start, [{"op": "clip.slip", "clip_id": "l", "source_offset_ticks": -frames(1)}])],
        "SOURCE_OUT_OF_BOUNDS",
    )
    linked = project([clip("l", 0, 40), clip("m", 40, 40, 60, link_id="k"), clip("r", 80, 40, 120)])
    assert "linked" in refused(
        [(linked, [{"op": "clip.slip", "clip_id": "m", "source_offset_ticks": frames(5)}])],
        "INVALID_SLIP",
    )
    print("   reducer: slip moves only the source window, slide trades frames between neighbours")


def source(path: Path, first: str, second: str) -> None:
    """A two-tone clip: the first half is one colour, the second half another."""
    half = SOURCE_SECONDS / 2
    subprocess.run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-y",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            f"color=c={first}:s={WIDTH}x{HEIGHT}:d={half}:r={FPS}",
            "-f",
            "lavfi",
            "-i",
            f"color=c={second}:s={WIDTH}x{HEIGHT}:d={half}:r={FPS}",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-t",
            str(SOURCE_SECONDS),
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=300,
        creationflags=0x08000000,
    )


def export(target: Project, out: Path, job: Path) -> None:
    plan = compile_render_plan(target, "h264-source-quality")
    job.mkdir(exist_ok=True)
    for name, body in plan.text_files.items():
        (job / name).write_text(body, encoding="utf-8")
    process = subprocess.run(
        plan.ffmpeg_argv(str(FFMPEG), str(out)),
        cwd=job,
        capture_output=True,
        timeout=600,
        creationflags=0x08000000,
    )
    assert process.returncode == 0, process.stderr.decode(errors="replace")[-800:]


def colour(video: Path, at_seconds: float) -> tuple[int, int, int]:
    raw = subprocess.run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-ss",
            f"{at_seconds:.6f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            "scale=1:1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=300,
        creationflags=0x08000000,
    ).stdout
    assert len(raw) == 3, raw
    return raw[0], raw[1], raw[2]


def duration(video: Path) -> float:
    out = subprocess.run(
        [str(FFMPEG), "-i", str(video), "-f", "null", "-"],
        capture_output=True,
        timeout=300,
        creationflags=0x08000000,
    ).stderr.decode(errors="replace")
    import re

    seconds = re.findall(r"time=\s*([\d:.]+)", out)
    assert seconds, out[-400:]
    hours, minutes, rest = seconds[-1].split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(rest)


def media_suite(folder: Path) -> None:
    """The pixels decide: a slipped clip shows the later half, a slid seam moves by frames."""
    media = folder / "media"
    media.mkdir(exist_ok=True)
    red_blue = media / "redblue.mp4"
    source(red_blue, "red", "blue")

    def asset_pair(path: Path, asset_id: str, seconds: float) -> tuple[Asset, VerifiedMedia]:
        body = VerifiedMedia.model_validate(
            {
                "probe_id": asset_id,
                "path": str(path),
                "kind": "video",
                "label": asset_id,
                "size_bytes": path.stat().st_size,
                "content_sha256": "0" * 64,
                "duration_ticks": int(seconds * T),
                "width": WIDTH,
                "height": HEIGHT,
                "has_audio": False,
            }
        )
        return (
            Asset(
                id=asset_id,
                kind="video",
                label=asset_id,
                reference="r",
                duration_ticks=body.duration_ticks,
                verified=body,
            ),
            body,
        )

    asset, _ = asset_pair(red_blue, "a", SOURCE_SECONDS)
    target = Project(
        id="m",
        name="media",
        tracks=[Track(id="v", kind="video", name="v")],
        assets={"a": asset},
        clips={
            "one": Clip(
                id="one",
                asset_id="a",
                track_id="v",
                position_ticks=0,
                duration_ticks=int(2 * T),
            )
        },
    )
    validate_timeline(target)
    plain = folder / "plain.mp4"
    export(target, plain, folder / "job-plain")
    assert colour(plain, 0.5)[0] > 150 and colour(plain, 0.5)[2] < 80, colour(plain, 0.5)
    # The source is red for its first two seconds and blue after that, so a two second slip
    # must make the very first frame of the clip blue while the clip stays where it is.
    slipped = edit(
        target, [{"op": "clip.slip", "clip_id": "one", "source_offset_ticks": int(2 * T)}]
    )
    assert slipped.clips["one"].position_ticks == 0
    moved = folder / "slipped.mp4"
    export(slipped, moved, folder / "job-slipped")
    after = colour(moved, 0.5)
    assert after[2] > 150 and after[0] < 80, after
    print(
        f"   media: the same timeline second shows {colour(plain, 0.5)} before the slip and "
        f"{after} after a two second slip"
    )

    red = media / "red.mp4"
    green = media / "green.mp4"
    blue = media / "blue.mp4"
    for path, tone in ((red, "red"), (green, "0x00A000"), (blue, "blue")):
        subprocess.run(
            [
                str(FFMPEG),
                "-v",
                "error",
                "-y",
                "-nostdin",
                "-f",
                "lavfi",
                "-i",
                f"color=c={tone}:s={WIDTH}x{HEIGHT}:d=4:r={FPS}",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            check=True,
            capture_output=True,
            timeout=300,
            creationflags=0x08000000,
        )
    assets: dict[str, Asset] = {}
    clips: dict[str, Clip] = {}
    for index, (asset_id, path) in enumerate((("ar", red), ("ag", green), ("ab", blue))):
        body, _ = asset_pair(path, asset_id, 4.0)
        assets[asset_id] = body
        clips[f"c{index}"] = Clip(
            id=f"c{index}",
            asset_id=asset_id,
            track_id="v",
            position_ticks=int(index * 2 * T),
            duration_ticks=int(2 * T),
        )
    seams = Project(
        id="s",
        name="seams",
        tracks=[Track(id="v", kind="video", name="v")],
        assets=assets,
        clips=clips,
    )
    validate_timeline(seams)
    before = folder / "seams-before.mp4"
    export(seams, before, folder / "job-seams-before")
    assert colour(before, 1.5)[0] > 150, colour(before, 1.5)
    assert colour(before, 2.5)[1] > 100, colour(before, 2.5)
    assert colour(before, 4.5)[2] > 150, colour(before, 4.5)
    slid = edit(seams, [{"op": "clip.slide", "clip_id": "c1", "delta_ticks": int(T)}])
    after_video = folder / "seams-after.mp4"
    export(slid, after_video, folder / "job-seams-after")
    assert colour(after_video, 1.5)[0] > 150, colour(after_video, 1.5)
    # The seam that used to sit at 2.0s now sits at 3.0s: 2.5s is red, not green any more.
    assert colour(after_video, 2.5)[0] > 150, colour(after_video, 2.5)
    assert colour(after_video, 4.5)[1] > 100, colour(after_video, 4.5)
    assert colour(after_video, 5.5)[2] > 150, colour(after_video, 5.5)
    assert abs(duration(after_video) - duration(before)) < 0.05, (
        duration(before),
        duration(after_video),
    )
    print(
        "   media: the red/green seam moved from 2.0s to 3.0s on screen while the exported "
        f"length stayed {duration(before):.3f}s"
    )


def http_suite(folder: Path) -> None:
    token = "slipcheck" + "4" * 53
    store = ProjectStore(folder / "slip-store.sqlite3")
    app = create_app(folder / "slip-api.sqlite3", token)
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
        caps = client.get("/v1/capabilities").json()
        assert caps["features"]["slip_slide_editing"] is True, caps["features"]
        assert {"clip.slip", "clip.slide"} <= set(caps["commands"]), caps["commands"]
        created = client.post(
            "/v1/projects",
            json={
                "request_id": "new",
                "name": "滑移",
                "settings": {"width": WIDTH, "height": HEIGHT},
            },
        ).json()["project"]
        path = f"/v1/projects/{created['id']}"
        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "seed",
                "expected_revision": 0,
                "commands": [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
                    {
                        "op": "asset.register",
                        "asset": {
                            "id": "a",
                            "kind": "video",
                            "label": "素材",
                            "reference": "r",
                            "duration_ticks": frames(200),
                        },
                    },
                    {
                        "op": "clips.add",
                        "clips": [
                            {
                                "id": "l",
                                "asset_id": "a",
                                "track_id": "v",
                                "position_ticks": 0,
                                "duration_ticks": frames(40),
                            },
                            {
                                "id": "m",
                                "asset_id": "a",
                                "track_id": "v",
                                "position_ticks": frames(40),
                                "duration_ticks": frames(40),
                                "source_in_ticks": frames(60),
                            },
                            {
                                "id": "r",
                                "asset_id": "a",
                                "track_id": "v",
                                "position_ticks": frames(80),
                                "duration_ticks": frames(40),
                                "source_in_ticks": frames(120),
                            },
                        ],
                    },
                ],
            },
        )
        assert seeded.status_code == 200, seeded.text
        both = client.post(
            path + "/edits",
            json={
                "request_id": "both",
                "expected_revision": 1,
                "commands": [
                    {"op": "clip.slip", "clip_id": "m", "source_offset_ticks": frames(8)},
                    {"op": "clip.slide", "clip_id": "m", "delta_ticks": frames(5)},
                ],
            },
        )
        assert both.status_code == 200, both.text
        body = both.json()["project"]
        assert [
            (c["position_ticks"], c["source_in_ticks"], c["duration_ticks"])
            for c in sorted(body["clips"].values(), key=lambda item: item["position_ticks"])
        ] == [
            (0, 0, frames(45)),
            (frames(45), frames(68), frames(40)),
            (frames(85), frames(125), frames(35)),
        ], body["clips"]
        assert body["revision"] == 2
        reopened = ProjectStore(folder / "slip-api.sqlite3").get(created["id"])
        assert reopened.clips["m"].source_in_ticks == frames(68), reopened.clips["m"]

        broken = client.post(
            path + "/edits",
            json={
                "request_id": "broken",
                "expected_revision": 2,
                "commands": [
                    {"op": "clip.slip", "clip_id": "l", "source_offset_ticks": frames(3)},
                    {"op": "clip.slide", "clip_id": "l", "delta_ticks": frames(3)},
                ],
            },
        )
        assert broken.status_code == 422 and "INVALID_SLIDE" in broken.text, broken.text
        after = client.get(path).json()
        assert after["revision"] == 2, "a refused batch writes nothing"
        assert after["clips"]["l"]["source_in_ticks"] == 0
        ghost = client.post(
            path + "/edits",
            json={
                "request_id": "ghost",
                "expected_revision": 2,
                "commands": [{"op": "clip.slip", "clip_id": "nope", "source_offset_ticks": 1}],
            },
        )
        assert ghost.status_code == 404, ghost.text
        stale = client.post(
            path + "/edits",
            json={
                "request_id": "stale",
                "expected_revision": 1,
                "commands": [{"op": "clip.slip", "clip_id": "m", "source_offset_ticks": frames(1)}],
            },
        )
        assert stale.status_code == 409, stale.text
    created_store = store.create(CreateProject(request_id="s-new", name="restart"))
    assert created_store.project.clips == {}
    print(
        "   http: one batch, one revision, refused batches write nothing, restart keeps the windows"
    )


def main() -> None:
    reducer_suite()
    with tempfile.TemporaryDirectory(prefix="agentcut-slip-") as tmp:
        folder = Path(tmp)
        http_suite(folder)
        media_suite(folder)
    print(
        "PASS: slip keeps position and length while the source window moves, slide trades frames "
        "between both neighbours without changing the track length, and the exported pixels agree"
    )


if __name__ == "__main__":
    main()
