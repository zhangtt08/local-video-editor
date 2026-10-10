"""Morphing free-form mask outlines: one window table, cut once by the exporter and drawn by the
browser from the very same numbers.

An outline cannot be an expression the way a box can, so 1.118 compiles it into frame-aligned
constant windows (`animation.mask_shape_schedule`). The exporter bakes one plate per window and the
preview manifest ships that same list, so the shape *steps* on both ends while the mask's centre
keeps sliding continuously. This check measures where the masked edge really is in a delivered file
and compares it with the table the browser was handed — including the frame where the two would
disagree if the export smoothed instead of stepped.
"""

import hashlib
import json
import re
import subprocess
import tempfile
import zlib
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.animation import (
    MASK_SHAPE_SCHEDULE_MAX,
    mask_shape_schedule,
    preview_manifest,
    vertices_at,
)
from agentcut.contracts import (
    MASK_SHAPE_KEY_LIMIT,
    Clip,
    EditBatch,
    EditorError,
    Project,
    VerifiedMedia,
)
from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app
from agentcut.masks import raster_size
from agentcut.render import compile_render_plan
from agentcut.timeline import CLIP_MASK_SHAPE_LIMIT, validate_timeline

FRAME = T // 30
ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
WIDTH, HEIGHT = 320, 180


def run(args: list[str], timeout: int = 240) -> bytes:
    result = subprocess.run(
        [str(FFMPEG), "-v", "error", *args],
        capture_output=True,
        timeout=timeout,
        creationflags=0x08000000,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")[-800:]
    return result.stdout


def outline(edge: float) -> list[dict]:
    """A quad hugging the left edge of the frame, its right side at `edge`."""
    return [
        {"x": edge, "y": 0.0, "handle_out": [0, 0], "handle_in": [0, 0]},
        {"x": edge, "y": 1.0, "handle_out": [0, 0], "handle_in": [0, 0]},
        {"x": 0.0, "y": 1.0, "handle_out": [0, 0], "handle_in": [0, 0]},
        {"x": 0.0, "y": 0.0, "handle_out": [0, 0], "handle_in": [0, 0]},
    ]


MASK = {
    "shape": "path",
    "center_x": 0.5,
    "center_y": 0.5,
    "width": 0.6,
    "height": 0.6,
    "feather": 0.0,
    "inverted": False,
    "vertices": outline(0.05),
}


def shape_keys(last: float = 0.95, interpolation: str = "linear") -> list[dict]:
    return [
        {"at_ticks": 0, "vertices": outline(0.05), "interpolation": interpolation},
        {"at_ticks": 3 * T, "vertices": outline(last), "interpolation": interpolation},
    ]


def clip_payload(**changes) -> dict:
    clip = {
        "id": "c",
        "asset_id": "a",
        "track_id": "v",
        "position_ticks": 0,
        "duration_ticks": 3 * T,
        "mask": dict(MASK),
    }
    clip.update(changes)
    return clip


def picture(clip: dict) -> Project:
    return Project.model_validate(
        {
            "id": "p",
            "name": "maskshape",
            "settings": {"width": WIDTH, "height": HEIGHT},
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


def with_media(project: Project, path: Path) -> Project:
    project.assets["a"].verified = VerifiedMedia.model_validate(
        {
            "probe_id": "a",
            "path": str(path),
            "kind": "video",
            "label": "white",
            "size_bytes": path.stat().st_size,
            "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "duration_ticks": 3 * T,
            "width": WIDTH,
            "height": HEIGHT,
            "has_audio": False,
        }
    )
    return project


def geometry_suite() -> None:
    """The morph answers on the render clock; the window list is all both ends see."""
    clip = picture(clip_payload(mask_shape_keys=shape_keys())).clips["c"]
    # Ends hold, and the middle is the linear walk between the two outlines.
    assert vertices_at(clip, 0)[0].x == 0.05
    assert abs(vertices_at(clip, FRAME)[0].x - (0.05 + 0.9 / 90)) < 1e-9, vertices_at(clip, FRAME)
    assert abs(vertices_at(clip, 45 * FRAME)[0].x - 0.5) < 1e-9
    assert vertices_at(clip, 3 * T)[0].x == 0.95
    # A handle rides the same progress as its vertex, so a curved corner cannot tear off.
    curved = picture(
        clip_payload(
            mask={
                **MASK,
                "vertices": [
                    {"x": 0.1, "y": 0.1, "handle_out": [0.2, 0.0], "handle_in": [0, 0]},
                    {"x": 0.9, "y": 0.1, "handle_out": [0, 0], "handle_in": [-0.2, 0.0]},
                    {"x": 0.5, "y": 0.9, "handle_out": [0, 0], "handle_in": [0, 0]},
                ],
            },
            mask_shape_keys=[
                {
                    "at_ticks": 0,
                    "vertices": [
                        {"x": 0.1, "y": 0.1, "handle_out": [0.2, 0.0], "handle_in": [0, 0]},
                        {"x": 0.9, "y": 0.1, "handle_out": [0, 0], "handle_in": [-0.2, 0.0]},
                        {"x": 0.5, "y": 0.9, "handle_out": [0, 0], "handle_in": [0, 0]},
                    ],
                    "interpolation": "linear",
                },
                {
                    "at_ticks": 3 * T,
                    "vertices": [
                        {"x": 0.3, "y": 0.1, "handle_out": [0.0, 0.2], "handle_in": [0, 0]},
                        {"x": 0.7, "y": 0.1, "handle_out": [0, 0], "handle_in": [0.0, 0.2]},
                        {"x": 0.5, "y": 0.5, "handle_out": [0, 0], "handle_in": [0, 0]},
                    ],
                    "interpolation": "linear",
                },
            ],
        )
    ).clips["c"]
    halfway = vertices_at(curved, 45 * FRAME)
    assert abs(halfway[0].x - 0.2) < 1e-9 and abs(halfway[0].y - 0.1) < 1e-9, halfway
    assert abs(halfway[0].handle_out[0] - 0.1) < 1e-9, halfway
    assert abs(halfway[0].handle_out[1] - 0.1) < 1e-9, halfway

    schedule = mask_shape_schedule(clip, FRAME, MASK_SHAPE_SCHEDULE_MAX)
    assert len(schedule) <= MASK_SHAPE_SCHEDULE_MAX, len(schedule)
    assert schedule[0]["from_ticks"] == 0 and schedule[-1]["to_ticks"] == clip.duration_ticks
    # Windows are whole frames, and their boundaries tile the clip with no gap and no overlap.
    for first, second in zip(schedule, schedule[1:]):
        assert first["to_ticks"] == second["from_ticks"]
        assert second["to_ticks"] % FRAME == 0 or second["to_ticks"] == clip.duration_ticks
    # Each window's outline is the table at its own midpoint — the exporter and the preview both
    # read this, so a step is a decision made once.
    for window in schedule:
        middle = (window["from_ticks"] + window["to_ticks"]) // 2
        assert [v.x for v in vertices_at(clip, middle)] == [v.x for v in window["value"]]

    # A held outline morphs in one jump, and one outline alone is a constant shape: both compile to
    # as few windows as the equality in `frame_windows` allows, never a plate per frame.
    held = picture(clip_payload(mask_shape_keys=shape_keys(interpolation="hold"))).clips["c"]
    held_schedule = mask_shape_schedule(held, FRAME, MASK_SHAPE_SCHEDULE_MAX)
    edges = {round(w["value"][0].x, 6) for w in held_schedule}
    assert edges == {0.05, 0.95} or len(edges) == 1, edges
    only = picture(clip_payload(mask_shape_keys=[shape_keys()[0]])).clips["c"]
    assert len(mask_shape_schedule(only, FRAME, MASK_SHAPE_SCHEDULE_MAX)) == 1
    # A box mask has no outline to morph, and a mask with no keys keeps the graph it always had.
    plain = picture(clip_payload()).clips["c"]
    assert mask_shape_schedule(plain, FRAME, MASK_SHAPE_SCHEDULE_MAX) == []
    assert vertices_at(plain, 0) == plain.mask.vertices
    print("   maskshape: the outline answers on the render clock, windows tile whole frames")


def png_gray(body: bytes) -> tuple[int, int, list[bytes]]:
    """Read back one of the engine's own grayscale plates: the artifact, not its name."""
    assert body[:8] == b"\x89PNG\r\n\x1a\n"
    width = height = 0
    rows: list[bytes] = []
    pos = 8
    while pos < len(body):
        size = int.from_bytes(body[pos : pos + 4], "big")
        tag = body[pos + 4 : pos + 8]
        chunk = body[pos + 8 : pos + 8 + size]
        if tag == b"IHDR":
            width = int.from_bytes(chunk[:4], "big")
            height = int.from_bytes(chunk[4:8], "big")
            assert (chunk[8], chunk[9]) == (8, 0), (chunk[8], chunk[9])
        elif tag == b"IDAT":
            raw = zlib.decompress(chunk)
            step = width + 1
            for y in range(height):
                assert raw[y * step] == 0, "the engine writes unfiltered rows"
                rows.append(raw[y * step + 1 : (y + 1) * step])
        elif tag == b"IEND":
            break
        pos += 8 + size + 4
    assert len(rows) == height, (len(rows), height)
    return width, height, rows


def white_span(row: bytes) -> int:
    low = next((x for x, value in enumerate(row) if value > 128), None)
    if low is None:
        return 0
    return max(x for x, value in enumerate(row) if value > 128) - low + 1


def graph_suite(folder: Path) -> None:
    """One plate per window, each with the enable bounds the preview was told about."""
    dummy = folder / "clip.mp4"
    dummy.write_bytes(b"\x00" * 64)
    keyed = with_media(picture(clip_payload(mask_shape_keys=shape_keys())), dummy)
    plan = compile_render_plan(keyed, "h264-source-quality")
    graph = "\n".join(plan.filters)
    manifest = preview_manifest(keyed)["clips"]["c"]
    windows = manifest["mask_shape"]
    assert windows
    assert len(windows) == len(
        mask_shape_schedule(keyed.clips["c"], FRAME, MASK_SHAPE_SCHEDULE_MAX)
    )
    stepped = re.findall(r"overlay=.*?:eval=frame:enable='between\(t,([0-9.]+),([0-9.]+)\)'", graph)
    assert len(stepped) == len(windows), (len(stepped), len(windows))
    for (start, stop), window in zip(stepped, windows):
        assert abs(float(start) - window["from_ticks"] / T) < 1e-6, (start, window)
        assert abs(float(stop) - window["to_ticks"] / T) < 1e-6, (stop, window)

    # The plate the exporter cut is the outline the preview was told to mask with: the white band in
    # the raster measures the window's own `width`, in the same plane pixels the overlay scales by.
    plates = [body for name, body in plan.binary_files.items() if name.startswith("mask-")]
    assert len(plates) == len(windows), (len(plates), len(windows))
    plane_w, plane_h = raster_size(WIDTH, HEIGHT)
    for body, window in zip(plates, windows):
        width, height, rows = png_gray(body)
        assert width > 0 and height > 0
        span = white_span(rows[height // 2])
        want = max(2, round(plane_w * window["width"]))
        assert abs(span - want) <= 2, (span, want, window["width"])
        tall = white_span(bytes(row[width // 2] for row in rows))
        assert abs(tall - max(2, round(plane_h * window["height"]))) <= 2, (tall, window)
    print(f"   maskshape: {len(windows)} plates measured, each the box the preview masks with")

    # A project that never heard of outlines compiles exactly the graph it compiled before them.
    legacy = with_media(picture(clip_payload()), dummy)
    before = "\n".join(compile_render_plan(legacy, "h264-source-quality").filters)
    assert "eval=frame:enable=" not in before, before[:200]
    emptied = with_media(picture(clip_payload(mask_shape_keys=[])), dummy)
    assert "\n".join(compile_render_plan(emptied, "h264-source-quality").filters) == before
    assert preview_manifest(emptied)["clips"]["c"]["mask_shape"] is None
    assert preview_manifest(legacy)["clips"]["c"]["mask_unit"] is None


def rejection_suite() -> None:
    """Only a free-form outline can morph, and it can only morph into its own node count."""
    for label, clip in (
        ("no mask", clip_payload(mask=None, mask_shape_keys=shape_keys())),
        (
            "box mask",
            clip_payload(
                mask={**MASK, "shape": "ellipse", "vertices": None}, mask_shape_keys=shape_keys()
            ),
        ),
        (
            "topology",
            clip_payload(
                mask_shape_keys=[
                    {"at_ticks": 0, "vertices": outline(0.3)[:3], "interpolation": "linear"},
                    shape_keys()[1],
                ]
            ),
        ),
        ("twice", clip_payload(mask_shape_keys=[shape_keys()[0], dict(shape_keys()[0])])),
    ):
        try:
            validate_timeline(picture(clip))
        except EditorError as error:
            assert error.code == "INVALID_MASK", (label, error.payload())
            assert error.message, (label, error)
            if label == "topology":
                assert "cannot morph into this 4-vertex mask" in error.message, error.message
            if label == "twice":
                assert "one mask outline per time" in error.message, error.message
        else:
            raise AssertionError(f"{label} accepted outlines it cannot render")
    # An inverted outline still only keeps the outside of whatever shape is current.
    validate_timeline(
        picture(clip_payload(mask={**MASK, "inverted": True}, mask_shape_keys=shape_keys()))
    )
    # One outline per time, and the easing follows the same rule as a scalar keyframe: controls are
    # only carried by the curve that reads them, and a bezier without controls uses the defaults.
    try:
        Clip.model_validate(
            clip_payload(
                mask_shape_keys=[
                    {
                        "at_ticks": 0,
                        "vertices": outline(0.3),
                        "interpolation": "linear",
                        "bezier": {"x1": 0.4, "y1": 0, "x2": 0.6, "y2": 1},
                    }
                ]
            )
        )
    except Exception as error:
        assert "bezier" in str(error), error
    else:
        raise AssertionError("controls on a straight outline morph were accepted")
    plain = Clip.model_validate(
        clip_payload(
            mask_shape_keys=[{"at_ticks": 0, "vertices": outline(0.3), "interpolation": "bezier"}]
        )
    )
    assert plain.mask_shape_keys[0].bezier is None, plain.mask_shape_keys[0]
    eased = picture(
        clip_payload(
            mask_shape_keys=[
                {
                    "at_ticks": 0,
                    "vertices": outline(0.05),
                    "interpolation": "bezier",
                    "bezier": {"x1": 0.9, "y1": 0, "x2": 0.9, "y2": 1},
                },
                {"at_ticks": 3 * T, "vertices": outline(0.95), "interpolation": "linear"},
            ]
        )
    ).clips["c"]
    # A late-tanging bezier holds back and then rushes: at a third of the way the outline is still
    # well short of the linear answer, which is the same inversion `bezier_parameter` does for a
    # scalar curve — one easing engine, one set of shapes.
    third = vertices_at(eased, 30 * FRAME)[0].x
    assert third < 0.05 + 0.9 * 30 / 90, third
    print("   maskshape: a morph needs a path mask, one table per time, and the same node count")


def http_suite(folder: Path) -> None:
    token = "maskshape" + "d" * 45
    with TestClient(
        create_app(folder / "http.sqlite3", token),
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        caps = client.get("/v1/capabilities").json()
        assert caps["features"]["path_shape_keys"] is True
        assert caps["limits"]["mask_shape_keys"] == MASK_SHAPE_KEY_LIMIT == CLIP_MASK_SHAPE_LIMIT, (
            "the field's own max_length and the reducer's count must be the same number, or a "
            "batch the reducer accepts dies in validation with a different error than it names"
        )
        assert caps["limits"]["mask_shape_schedule_segments"] == MASK_SHAPE_SCHEDULE_MAX
        assert "mask.shape.set" in caps["commands"] and "mask.shape.remove" in caps["commands"]

        project = client.post("/v1/projects", json={"request_id": "new", "name": "morph"}).json()[
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
                {
                    "op": "asset.register",
                    "asset": {
                        "id": "a",
                        "kind": "video",
                        "label": "m",
                        "reference": "r",
                        "duration_ticks": 3 * T,
                    },
                },
                {"op": "clip.add", "clip": clip_payload()},
            ],
        )
        assert seed.status_code == 200, seed.text
        # The box of a path mask is the outline it was drawn in, so the morph starts from there.
        drawn = seed.json()["project"]["clips"]["c"]["mask"]
        assert abs(drawn["center_x"] - 0.025) < 1e-9, drawn

        written = edit(
            "keys",
            1,
            [
                {
                    "op": "mask.shape.set",
                    "clip_id": "c",
                    "keyframe": {"at_ticks": at, "vertices": verts, "interpolation": "linear"},
                }
                for at, verts in ((0, outline(0.05)), (3 * T, outline(0.95)))
            ],
        )
        assert written.status_code == 200, written.text
        keys = written.json()["project"]["clips"]["c"]["mask_shape_keys"]
        assert [key["at_ticks"] for key in keys] == [0, 3 * T], keys
        assert keys[1]["vertices"][0]["x"] == 0.95, keys

        replay = edit(
            "keys",
            1,
            [
                {
                    "op": "mask.shape.set",
                    "clip_id": "c",
                    "keyframe": {
                        "at_ticks": 0,
                        "vertices": outline(0.05),
                        "interpolation": "linear",
                    },
                },
                {
                    "op": "mask.shape.set",
                    "clip_id": "c",
                    "keyframe": {
                        "at_ticks": 3 * T,
                        "vertices": outline(0.95),
                        "interpolation": "linear",
                    },
                },
            ],
        )
        assert replay.json()["replayed"] is True and replay.json()["project"]["revision"] == 2

        dry = edit(
            "drop",
            2,
            [{"op": "mask.shape.remove", "clip_id": "c", "at_ticks": 3 * T}],
            dry=True,
        )
        assert dry.status_code == 200 and not dry.json()["committed"], dry.text
        assert client.get(path).json()["revision"] == 2, "a dry run must not write"
        assert len(client.get(path).json()["clips"]["c"]["mask_shape_keys"]) == 2

        refused = edit(
            "bad",
            2,
            [
                {
                    "op": "mask.shape.set",
                    "clip_id": "c",
                    "keyframe": {
                        "at_ticks": T,
                        "vertices": outline(0.4)[:3],
                        "interpolation": "linear",
                    },
                }
            ],
        )
        assert refused.json()["error"]["code"] == "INVALID_MASK", refused.text
        assert refused.json()["error"]["details"]["vertices"] == 3, refused.text
        assert client.get(path).json()["revision"] == 2, "a rejected batch must not write half"

        outside = edit(
            "far",
            2,
            [
                {
                    "op": "mask.shape.set",
                    "clip_id": "c",
                    "keyframe": {
                        "at_ticks": 3 * T + FRAME,
                        "vertices": outline(0.4),
                        "interpolation": "linear",
                    },
                }
            ],
        )
        assert outside.json()["error"]["code"] == "INVALID_KEYFRAME", outside.text
        assert outside.json()["error"]["details"]["duration_ticks"] == 3 * T, outside.text

        missing = edit(
            "gone",
            2,
            [{"op": "mask.shape.remove", "clip_id": "c", "at_ticks": 2 * T}],
        )
        assert missing.json()["error"]["code"] == "KEYFRAME_NOT_FOUND", missing.text

        locked = edit(
            "lock",
            2,
            [
                {"op": "track.update", "track_id": "v", "locked": True},
                {
                    "op": "mask.shape.set",
                    "clip_id": "c",
                    "keyframe": {
                        "at_ticks": T,
                        "vertices": outline(0.4),
                        "interpolation": "linear",
                    },
                },
            ],
        )
        assert locked.json()["error"]["code"] == "TRACK_LOCKED", locked.text
        assert client.get(path).json()["revision"] == 2, "a locked batch must not write"
        edit("unlock", 2, [{"op": "track.update", "track_id": "v", "locked": False}])

        # The budget is the contract's own: the 33rd outline names the way out.
        filled = [
            {
                "op": "mask.shape.set",
                "clip_id": "c",
                "keyframe": {
                    "at_ticks": index * FRAME,
                    "vertices": outline(0.05 + index / 90),
                    "interpolation": "linear",
                },
            }
            for index in range(1, CLIP_MASK_SHAPE_LIMIT - 1)
        ]
        room = edit("fill", 3, filled)
        assert room.status_code == 200, room.text
        assert len(room.json()["project"]["clips"]["c"]["mask_shape_keys"]) == CLIP_MASK_SHAPE_LIMIT
        over = edit(
            "over",
            4,
            [
                {
                    "op": "mask.shape.set",
                    "clip_id": "c",
                    "keyframe": {
                        "at_ticks": 2 * T,
                        "vertices": outline(0.5),
                        "interpolation": "linear",
                    },
                }
            ],
        )
        assert over.json()["error"]["code"] == "MASK_SHAPE_LIMIT", over.text
        assert over.json()["error"]["details"]["limit"] == CLIP_MASK_SHAPE_LIMIT, over.text
        assert "split the clip" in over.json()["error"]["message"], over.text
        assert client.get(path).json()["revision"] == 4, "a full mask must not be half written"

        # Replacing the outline at a time already taken is not a new one, so a full mask can still
        # be corrected without deleting anything first.
        occupied = edit(
            "occupied",
            4,
            [
                {
                    "op": "mask.shape.set",
                    "clip_id": "c",
                    "keyframe": {
                        "at_ticks": FRAME,
                        "vertices": outline(0.42),
                        "interpolation": "linear",
                    },
                }
            ],
        )
        assert occupied.status_code == 200, occupied.text
        keys = occupied.json()["project"]["clips"]["c"]["mask_shape_keys"]
        assert len(keys) == CLIP_MASK_SHAPE_LIMIT, keys
        assert abs(keys[1]["vertices"][0]["x"] - 0.42) < 1e-9, keys[1]

        restore = client.post(
            path + "/restore",
            json={
                "request_id": "undo",
                "expected_revision": occupied.json()["project"]["revision"],
                "target_revision": 2,
            },
        )
        assert restore.status_code == 200, restore.text
        assert len(restore.json()["project"]["clips"]["c"]["mask_shape_keys"]) == 2
        assert restore.json()["project"]["revision"] == occupied.json()["project"]["revision"] + 1

        stored = client.get(path).json()["clips"]["c"]
        assert stored["mask_shape_keys"], stored
    print("   maskshape: atomic edits, named rejections, and the budget counted off the contract")


def media_suite(folder: Path) -> None:
    source = folder / "white.mp4"
    run(
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=white:s={WIDTH}x{HEIGHT}:r=30:d=3",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ]
    )
    project = with_media(picture(clip_payload(mask_shape_keys=shape_keys())), source)
    out = folder / "morph.mp4"
    plan = compile_render_plan(project, "h264-source-quality")
    job = folder / "job"
    job.mkdir(exist_ok=True)
    for name, body in plan.text_files.items():
        (job / name).write_text(body, encoding="utf-8")
    for name, body in plan.binary_files.items():
        (job / name).write_bytes(body)
    result = subprocess.run(
        plan.ffmpeg_argv(str(FFMPEG), str(out)),
        cwd=job,
        capture_output=True,
        timeout=600,
        creationflags=0x08000000,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")[-1500:]
    assert out.stat().st_size > 0

    def level(at: float, x_ratio: float) -> float:
        left = int(x_ratio * WIDTH) - 3
        raw = run(
            [
                "-ss",
                f"{at:.6f}",
                "-i",
                str(out),
                "-frames:v",
                "1",
                "-vf",
                f"crop=6:6:{max(0, min(WIDTH - 6, left))}:90",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ]
        )
        assert raw, (at, x_ratio, out.stat().st_size)
        return sum(raw[i] for i in range(0, len(raw), 3)) / (len(raw) // 3)

    windows = mask_shape_schedule(project.clips["c"], FRAME, MASK_SHAPE_SCHEDULE_MAX)

    # `-ss` before `-i` keeps the first frame whose presentation time is at or after the target, so
    # the probe aims a tenth of a frame *before* the one it means to read. Aiming at the frame's own
    # pts would ask for the next one, and at the last frame of the clip that returns nothing at all.
    def clock(frame: int) -> float:
        return (frame - 0.1) / 30

    # The white region is the outline itself: x < edge(t), and edge(t) is the window's own table.
    for index, window in enumerate(windows):
        edge = window["value"][0].x
        frame = (window["from_ticks"] + window["to_ticks"]) // 2 // FRAME
        at = clock(frame)
        inside, outside = max(0.0, edge - 0.04), min(0.99, edge + 0.04)
        assert level(at, inside) > 200, (index, frame, edge, level(at, inside))
        assert level(at, outside) < 40, (index, frame, edge, level(at, outside))
    # The step, not the smooth curve: at the first frame of the second window the export is still
    # holding the previous window's outline, which is where a smoothed export would disagree.
    second = windows[1]
    boundary = second["from_ticks"] // FRAME
    held = windows[0]["value"][0].x
    smooth = 0.05 + 0.9 * boundary / 90
    assert abs(held - smooth) > 0.02, (held, smooth)
    probe = (held + smooth) / 2
    assert level(clock(boundary), probe) > 200, (probe, held, smooth)
    # …and one whole window later the plate has moved on, so the step is the schedule's own length.
    later = windows[3]
    assert level(clock(later["from_ticks"] // FRAME), (later["value"][0].x + held) / 2) > 200, (
        later["value"][0].x
    )
    print(
        f"   maskshape: {len(windows)} steps measured in the delivered file, each one the table "
        "the preview was handed"
    )


def agent_suite() -> None:
    """The Agent reaches the same command through the MCP schema the contract generates.

    `timeline_edit` takes an `EditBatch`, and FastMCP publishes that model's JSON schema verbatim,
    so a discriminator that names the two outline commands is what makes them writable without an
    Agent guessing at a payload — and the vertex table has to be described, or a client
    cannot fill it.
    """
    schema = json.dumps(EditBatch.model_json_schema())
    assert "mask.shape.set" in schema and "mask.shape.remove" in schema, schema[:400]
    assert "MaskShapeKeyframe" in schema, "the outline table has to be a named model in the schema"
    for field in ("handle_out", "handle_in", "interpolation", "at_ticks", "vertices"):
        assert field in schema, field
    # MCP must not grow a second way to write an outline: the commands ride the existing batch tool.
    source = (ROOT / "src/agentcut/mcp_server.py").read_text(encoding="utf-8")
    assert "mask.shape" not in source, "a new MCP tool would be a second authority for one behavior"
    print("   maskshape: the contract's own schema names the outline commands for an Agent")


def main():
    with tempfile.TemporaryDirectory(prefix="agentcut-maskshape-") as scratch:
        folder = Path(scratch)
        geometry_suite()
        graph_suite(folder)
        rejection_suite()
        http_suite(folder)
        agent_suite()
        media_suite(folder)
    print(
        "PASS: morphing free-form mask outlines compile to frame-aligned windows once, and the "
        "delivered pixels, the preview plan and the HTTP edits all read that same table"
    )


if __name__ == "__main__":
    main()
