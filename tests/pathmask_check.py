"""Path masks: one vertex list rasterised for FFmpeg and drawn as SVG; edits stay atomic."""

import hashlib
import struct
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import Project, ShapeMask
from agentcut.http_api import create_app
from agentcut.masks import coverage, mask_png, raster_size
from agentcut.render import compile_render_plan

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/node_modules/ffmpeg-static/ffmpeg.exe"


def vertex(x, y, out=(0.0, 0.0), inn=(0.0, 0.0)):
    return {"x": x, "y": y, "handle_out": list(out), "handle_in": list(inn)}


TRIANGLE = [vertex(0, 0), vertex(0.5, 0), vertex(0, 1)]
CURVED = [
    vertex(0.2, 0.2, out=(0.25, -0.25), inn=(-0.25, 0.25)),
    vertex(0.8, 0.2, out=(0.25, 0.25), inn=(-0.25, -0.25)),
    vertex(0.8, 0.8, out=(-0.25, 0.25), inn=(0.25, -0.25)),
    vertex(0.2, 0.8, out=(-0.25, -0.25), inn=(0.25, 0.25)),
]


def run(args):
    return subprocess.run(
        [str(FFMPEG), "-v", "error", *args],
        capture_output=True,
        check=True,
        timeout=180,
        creationflags=0x08000000,
    ).stdout


def source_video(folder: Path, colour: str, name: str) -> Path:
    path = folder / name
    subprocess.run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color={colour}:s=320x180:r=30:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        capture_output=True,
        check=True,
        timeout=120,
        creationflags=0x08000000,
    )
    return path


def asset(clip_id: str, path: Path) -> dict:
    return {
        "id": clip_id,
        "kind": "video",
        "label": clip_id,
        "reference": "unused",
        "duration_ticks": T,
        "verified": {
            "probe_id": clip_id,
            "path": str(path),
            "kind": "video",
            "label": clip_id,
            "size_bytes": path.stat().st_size,
            "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "duration_ticks": T,
            "width": 320,
            "height": 180,
            "has_audio": False,
        },
    }


def project(
    base: Path, top: Path, mask: dict | None, keyframes: list[dict] | None = None
) -> Project:
    return Project.model_validate(
        {
            "id": "p",
            "name": "pathmask",
            "settings": {"width": 320, "height": 180},
            "tracks": [
                {"id": "base", "kind": "video", "name": "base"},
                {"id": "top", "kind": "video", "name": "top"},
            ],
            "assets": {"green": asset("green", base), "red": asset("red", top)},
            "clips": {
                "g": {
                    "id": "g",
                    "asset_id": "green",
                    "track_id": "base",
                    "position_ticks": 0,
                    "duration_ticks": T,
                },
                "r": {
                    "id": "r",
                    "asset_id": "red",
                    "track_id": "top",
                    "position_ticks": 0,
                    "duration_ticks": T,
                    **({"mask": mask} if mask else {}),
                    **({"keyframes": keyframes} if keyframes else {}),
                },
            },
        }
    )


def render(project: Project, folder: Path, name: str) -> Path:
    out = folder / name
    plan = compile_render_plan(project, "h264-source-quality")
    job = folder / f"job-{name}"
    job.mkdir(exist_ok=True)
    for file_name, body in plan.text_files.items():
        (job / file_name).write_text(body, encoding="utf-8")
    for file_name, body in plan.binary_files.items():
        (job / file_name).write_bytes(body)
    result = subprocess.run(
        plan.ffmpeg_argv(str(FFMPEG), str(out)),
        cwd=job,
        capture_output=True,
        timeout=240,
        creationflags=0x08000000,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")[-900:]
    return out


def pixel(video: Path, x: int, y: int, at: str = "0.5") -> list[int]:
    raw = run(
        [
            "-ss",
            at,
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )
    offset = (y * 320 + x) * 3
    return list(raw[offset : offset + 3])


def red(value: list[int]) -> bool:
    return value[0] > 180 and value[1] < 90


def png_level(folder: Path, mask: ShapeMask, name: str, spots: list[tuple[int, int]]) -> list[int]:
    """Sample the shipped PNG after FFmpeg decodes it, at the resolution the encoder used."""
    path = folder / f"{name}.png"
    body = mask_png(mask, *raster_size(320, 180))
    path.write_bytes(body)
    width, height = struct.unpack(">II", body[16:24])
    raw = run(["-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"])
    assert len(raw) == width * height, (len(raw), width, height)
    return [raw[round(y * height / 180) * width + round(x * width / 320)] for x, y in spots]


def geometry_suite(folder: Path) -> None:
    straight = ShapeMask.model_validate({"shape": "path", "vertices": TRIANGLE})
    width, height = raster_size(320, 180)
    values = coverage(straight, width, height)
    inside = values[int(0.1 * height) * width + int(0.1 * width)]
    outside = values[int(0.9 * height) * width + int(0.9 * width)]
    assert inside == 255 and outside == 0, (inside, outside)
    area = sum(values) / (width * height) / 255
    assert abs(area - 0.25) < 0.01, area

    curved = ShapeMask.model_validate({"shape": "path", "vertices": CURVED})
    curved_values = coverage(curved, width, height)
    corner = curved_values[2 * width + 2]
    centre = curved_values[(height // 2) * width + width // 2]
    assert corner < 40 and centre == 255, (corner, centre)
    hull_area = sum(1 for value in values if value > 127) / (width * height)
    curved_area = sum(1 for value in curved_values if value > 127) / (width * height)
    assert curved_area > hull_area + 0.1, (curved_area, hull_area)

    png = mask_png(curved, width, height)
    assert png[:8] == b"\x89PNG\r\n\x1a\n", png[:8]
    assert len(png) > 200
    feathered = mask_png(
        ShapeMask.model_validate({"shape": "path", "vertices": TRIANGLE, "feather": 0.4}),
        width,
        height,
    )
    assert len(feathered) > 200, len(feathered)
    straight_mask = ShapeMask.model_validate({"shape": "path", "vertices": TRIANGLE})
    # (2,2) sits inside the wedge, (200,20) is outside its hypotenuse, (168,20) is just outside.
    spots = [(2, 2), (200, 20), (168, 20)]
    normal = png_level(folder, straight_mask, "coverage-normal", spots)
    assert normal == [255, 0, 0], normal
    flipped = png_level(
        folder,
        ShapeMask.model_validate({"shape": "path", "vertices": TRIANGLE, "inverted": True}),
        "coverage-inverted",
        spots,
    )
    assert flipped == [0, 255, 255], flipped
    soft = png_level(
        folder,
        ShapeMask.model_validate({"shape": "path", "vertices": TRIANGLE, "feather": 0.5}),
        "coverage-feather",
        spots,
    )
    assert 0 < soft[2] < 250, ("feather must leave a soft ramp outside the outline", soft)
    assert soft[1] < soft[2], ("the ramp must fall off away from the edge", soft)
    assert normal[2] == 0 and normal[1] == 0, ("an unfeathered edge stays hard", normal)


def media_suite(folder: Path) -> None:
    base = source_video(folder, "green", "green.mp4")
    top = source_video(folder, "red", "red.mp4")

    plain = render(project(base, top, None), folder, "plain.mp4")
    for x, y in ((20, 20), (300, 20), (20, 160), (300, 160)):
        assert red(pixel(plain, x, y)), (x, y, pixel(plain, x, y))

    triangle = {"shape": "path", "vertices": TRIANGLE}
    masked = render(project(base, top, triangle), folder, "triangle.mp4")
    assert red(pixel(masked, 20, 20)), pixel(masked, 20, 20)
    for x, y in ((300, 20), (20, 160), (300, 160), (160, 90)):
        assert not red(pixel(masked, x, y)), (x, y, pixel(masked, x, y))

    inverted = {"shape": "path", "vertices": TRIANGLE, "inverted": True}
    flipped = render(project(base, top, inverted), folder, "inverted.mp4")
    assert not red(pixel(flipped, 20, 20)), pixel(flipped, 20, 20)
    assert red(pixel(flipped, 300, 160)), pixel(flipped, 300, 160)

    curved = {"shape": "path", "vertices": CURVED}
    round_clip = render(project(base, top, curved), folder, "curved.mp4")
    assert red(pixel(round_clip, 160, 90)), pixel(round_clip, 160, 90)
    assert not red(pixel(round_clip, 8, 8)), pixel(round_clip, 8, 8)

    feathered = {"shape": "path", "vertices": TRIANGLE, "feather": 0.5}
    soft = render(project(base, top, feathered), folder, "feather.mp4")
    edge = pixel(soft, 120, 60)
    assert 60 < edge[0] < 220 and 40 < edge[1] < 200, edge

    # The outline was drawn over the left half (x 0..160 of a 320-wide frame). Writing a path mask
    # fits its box to the outline, so the box below is what `clip.mask` stores — and a centre curve
    # then reads as the picture coordinate the subject sits at. Sweeping it half a frame right has
    # to carry the cut with it: a point only the *moved* triangle covers starts green and ends red,
    # while a point the drawn triangle covers does the opposite.
    fitted = {**triangle, "center_x": 0.25, "center_y": 0.5, "width": 0.5, "height": 1.0}
    still = render(project(base, top, fitted), folder, "fitted.mp4")
    for x, y in ((40, 60), (150, 170), (250, 60), (300, 160)):
        assert red(pixel(still, x, y)) == red(pixel(masked, x, y)), (
            x,
            y,
            pixel(still, x, y),
            pixel(masked, x, y),
        )
    swept = render(
        project(
            base,
            top,
            fitted,
            [
                {"property": "mask_x", "at_ticks": 0, "value": 0.25, "interpolation": "linear"},
                {"property": "mask_x", "at_ticks": T, "value": 0.75, "interpolation": "linear"},
            ],
        ),
        folder,
        "swept.mp4",
    )
    assert not red(pixel(swept, 250, 60, "0.05")), pixel(swept, 250, 60, "0.05")
    assert red(pixel(swept, 250, 60, "0.95")), pixel(swept, 250, 60, "0.95")
    assert red(pixel(swept, 40, 60, "0.05")), pixel(swept, 40, 60, "0.05")
    assert not red(pixel(swept, 40, 60, "0.95")), pixel(swept, 40, 60, "0.95")
    held = render(
        project(
            base,
            top,
            fitted,
            [
                {"property": "mask_x", "at_ticks": 0, "value": 0.25, "interpolation": "linear"},
                {"property": "mask_x", "at_ticks": T, "value": 0.25, "interpolation": "linear"},
            ],
        ),
        folder,
        "held.mp4",
    )
    # A curve that never moves the mask must land exactly where the static one does.
    assert red(pixel(held, 40, 60, "0.5")) == red(pixel(still, 40, 60))
    assert not red(pixel(held, 250, 60, "0.5"))
    print(
        "   pathmask: fitting the box is the identity on the drawn outline, and a keyframed centre"
        " sweeps it — (250,60) goes green→red while (40,60) goes red→green, a flat curve reproduces"
        " the static cut"
    )

    plan = compile_render_plan(project(base, top, triangle), "h264-source-quality")
    assert len(plan.binary_files) == 1, plan.binary_files
    name = next(iter(plan.binary_files))
    assert name.startswith("mask-") and name.endswith(".png")
    # One more input than a box mask: the free-form cut is a patch over a neutral plate, and the
    # plate has to exist for the whole clip so `overlay` can move the patch frame by frame.
    assert plan.input_args.count("-i") == 6, plan.input_args
    assert "color=c=black:s=320x180" in " ".join(plan.input_args), plan.input_args
    joined = "\n".join(plan.filters)
    for stage in ("alphaextract", "scale2ref", "blend=all_mode=multiply", "alphamerge"):
        assert stage in joined, stage
    assert "overlay=x='320*(0.5)" in joined, joined
    assert "eval=frame" in joined, "the patch has to move on the render clock"
    assert "a='alpha(X,Y)*(" not in joined, "a path mask must not add a per-pixel alpha equation"
    shape_plan = compile_render_plan(
        project(base, top, {"shape": "ellipse", "feather": 0.3}), "h264-source-quality"
    )
    assert not shape_plan.binary_files and "alphamerge" not in "\n".join(shape_plan.filters)


def nested_suite(folder: Path) -> None:
    """A path mask inside a nested sequence must ship its raster with the parent plan."""
    base = source_video(folder, "green", "nest-green.mp4")
    top = source_video(folder, "red", "nest-red.mp4")
    project = Project.model_validate(
        {
            "id": "n",
            "name": "nested",
            "schema_version": 11,
            "settings": {"width": 320, "height": 180},
            "tracks": [{"id": "v", "kind": "video", "name": "v"}],
            "assets": {
                "green": asset("green", base),
                "red": asset("red", top),
                "seq": {
                    "id": "seq",
                    "kind": "sequence",
                    "sequence_id": "inner",
                    "label": "inner",
                    "reference": "s",
                    "duration_ticks": T,
                },
            },
            "clips": {
                "outer": {
                    "id": "outer",
                    "asset_id": "seq",
                    "track_id": "v",
                    "position_ticks": 0,
                    "duration_ticks": T,
                }
            },
            "sequences": {
                "inner": {
                    "id": "inner",
                    "name": "inner",
                    "duration_ticks": T,
                    "tracks": [
                        {"id": "i1", "kind": "video", "name": "i1"},
                        {"id": "i2", "kind": "video", "name": "i2"},
                    ],
                    "clips": {
                        "g": {
                            "id": "g",
                            "asset_id": "green",
                            "track_id": "i1",
                            "position_ticks": 0,
                            "duration_ticks": T,
                        },
                        "r": {
                            "id": "r",
                            "asset_id": "red",
                            "track_id": "i2",
                            "position_ticks": 0,
                            "duration_ticks": T,
                            "mask": {"shape": "path", "vertices": TRIANGLE},
                        },
                    },
                }
            },
        }
    )
    out = render(project, folder, "nested-mask.mp4")
    assert red(pixel(out, 20, 20)), pixel(out, 20, 20)
    assert not red(pixel(out, 300, 160)), pixel(out, 300, 160)


def http_suite(folder: Path) -> None:
    token = "pathmask-" + "e" * 48
    with TestClient(
        create_app(folder / "db.sqlite3", token),
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        capabilities = client.get("/v1/capabilities").json()
        assert capabilities["features"]["path_masks"] is True
        project = client.post("/v1/projects", json={"request_id": "new", "name": "path"}).json()[
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

        seed = [
            {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
            {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "a"}},
            {
                "op": "asset.register",
                "asset": {
                    "id": "pic",
                    "kind": "video",
                    "label": "p",
                    "reference": "r",
                    "duration_ticks": T,
                },
            },
            {
                "op": "asset.register",
                "asset": {
                    "id": "snd",
                    "kind": "audio",
                    "label": "s",
                    "reference": "r",
                    "duration_ticks": T,
                },
            },
            {
                "op": "clip.add",
                "clip": {
                    "id": "c",
                    "asset_id": "pic",
                    "track_id": "v",
                    "position_ticks": 0,
                    "duration_ticks": T,
                },
            },
            {
                "op": "clip.add",
                "clip": {
                    "id": "s",
                    "asset_id": "snd",
                    "track_id": "a",
                    "position_ticks": 0,
                    "duration_ticks": T,
                },
            },
        ]
        assert edit("seed", 0, seed).status_code == 200

        mask = {"shape": "path", "vertices": TRIANGLE, "feather": 0.2}
        command = {"op": "clip.mask", "clip_id": "c", "mask": mask}
        written = edit("m1", 1, [command])
        assert written.status_code == 200, written.text
        saved = written.json()["project"]["clips"]["c"]["mask"]
        assert saved["shape"] == "path" and len(saved["vertices"]) == 3
        assert saved["vertices"][0]["handle_out"] == [0.0, 0.0]
        # v13: the box is the drawn outline, not the shape's default. This is what a centre curve is
        # keyed against, so a mask arriving through `clip.mask` has to arrive fitted.
        assert abs(saved["center_x"] - 0.25) < 1e-9 and abs(saved["center_y"] - 0.5) < 1e-9, saved
        assert abs(saved["width"] - 0.5) < 1e-9 and abs(saved["height"] - 1.0) < 1e-9, saved
        arrived = edit(
            "m13",
            2,
            [
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "also",
                        "asset_id": "pic",
                        "track_id": "v",
                        "position_ticks": 2 * T,
                        "duration_ticks": T,
                        "mask": mask,
                    },
                }
            ],
            dry=True,
        )
        assert arrived.status_code == 200, arrived.text
        assert arrived.json()["committed"] is False
        # The same outline reaching the timeline inside a whole clip must land in the same place —
        # otherwise one mask would sit in two spots depending on the command that carried it.
        inline = arrived.json()["project"]["clips"]["also"]["mask"]
        assert inline == saved, (inline, saved)

        replay = edit("m1", 1, [command])
        assert replay.json()["replayed"] is True and replay.json()["project"]["revision"] == 2

        dry = edit("m2", 2, [{"op": "clip.mask", "clip_id": "c", "mask": None}], dry=True)
        assert not dry.json()["committed"]
        assert client.get(path).json()["revision"] == 2

        audio = edit("m3", 2, [{"op": "clip.mask", "clip_id": "s", "mask": mask}])
        assert audio.json()["error"]["code"] in {"INVALID_MASK", "INVALID_CLIP"}, audio.text

        too_few = edit(
            "m4",
            2,
            [
                {
                    "op": "clip.mask",
                    "clip_id": "c",
                    "mask": {"shape": "path", "vertices": TRIANGLE[:2]},
                }
            ],
        )
        assert too_few.status_code == 422, too_few.text
        duplicate = edit(
            "m5",
            2,
            [
                {
                    "op": "clip.mask",
                    "clip_id": "c",
                    "mask": {"shape": "path", "vertices": [TRIANGLE[0], TRIANGLE[0], TRIANGLE[2]]},
                }
            ],
        )
        assert duplicate.status_code == 422, duplicate.text
        wrong_shape = edit(
            "m6",
            2,
            [
                {
                    "op": "clip.mask",
                    "clip_id": "c",
                    "mask": {"shape": "ellipse", "vertices": TRIANGLE},
                }
            ],
        )
        assert wrong_shape.status_code == 422, wrong_shape.text
        assert client.get(path).json()["revision"] == 2, "rejected mask writes must not stick"

        manifest = client.get(path + "/preview-manifest").json()
        image = manifest["clips"]["c"]["mask_image"]
        assert image.startswith('url("data:image/svg+xml,')
        decoded = __import__("urllib.parse", fromlist=["unquote"]).unquote(image)
        assert "<path d=" in decoded and "feGaussianBlur" in decoded, decoded[:200]

        preview = client.post("/v1/mask/preview?frame_width=640&frame_height=360", json=mask)
        assert preview.status_code == 200, preview.text
        assert client.get(path).json()["revision"] == 2, (
            "candidate mask preview must stay read-only"
        )

        locked = edit(
            "m7",
            2,
            [
                {"op": "track.update", "track_id": "v", "locked": True},
                {
                    "op": "clip.mask",
                    "clip_id": "c",
                    "mask": {"shape": "path", "vertices": CURVED},
                },
            ],
        )
        assert locked.json()["error"]["code"] == "TRACK_LOCKED", locked.text
        assert client.get(path).json()["revision"] == 2

        history = client.get(path + "/history").json()["history"]
        restore = client.post(
            path + "/restore",
            json={
                "request_id": "m8",
                "expected_revision": 2,
                "target_revision": next(h["revision"] for h in history if h["revision"] == 1),
            },
        )
        assert restore.status_code == 200, restore.text
        assert restore.json()["project"]["clips"]["c"]["mask"] is None
        assert restore.json()["project"]["revision"] == 3


def main():
    with tempfile.TemporaryDirectory(prefix="agentcut-pathmask-") as scratch:
        folder = Path(scratch)
        geometry_suite(folder)
        http_suite(folder)
        media_suite(folder)
        nested_suite(folder)
    print(
        "PASS: path geometry, curved outlines, real triangle/invert/feather pixels, "
        "atomic HTTP edits, read-only candidates, old-shape masks and a nested sequence"
    )


if __name__ == "__main__":
    main()
