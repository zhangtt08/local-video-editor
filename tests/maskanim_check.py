"""Keyframed rectangle/ellipse masks: one curve drives the FFmpeg alpha and the browser's unit mask.

The exporter compiles the mask box into frame-time expressions and the browser scales one
engine-issued unit image with the same points, so this check measures where the masked edge really
is at several times and compares it with the curve.
"""

import hashlib
import subprocess
import tempfile
import urllib.parse
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.animation import preview_manifest, sample
from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import Clip, EditorError, Project, VerifiedMedia
from agentcut.http_api import create_app
from agentcut.masks import alpha_expression
from agentcut.render import compile_render_plan
from agentcut.timeline import validate_timeline

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FRAME = T // 30
MASK = {
    "shape": "ellipse",
    "center_x": 0.25,
    "center_y": 0.5,
    "width": 0.4,
    "height": 0.8,
    "feather": 0.0,
    "inverted": False,
    "vertices": None,
}


def run(args: list[str], timeout: int = 240) -> bytes:
    result = subprocess.run(
        [str(FFMPEG), "-v", "error", *args],
        capture_output=True,
        timeout=timeout,
        creationflags=0x08000000,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")[-800:]
    return result.stdout


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


def picture(clip: dict, width: int = 320, height: int = 180) -> Project:
    return Project.model_validate(
        {
            "id": "p",
            "name": "maskanim",
            "settings": {"width": width, "height": height},
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


def key(prop: str, at: int, value: float) -> dict:
    return {"property": prop, "at_ticks": at, "value": value, "interpolation": "linear"}


def geometry_suite(folder: Path) -> None:
    dummy = folder / "clip.mp4"
    dummy.write_bytes(b"\x00" * 64)
    verified = {
        "probe_id": "a",
        "path": str(dummy),
        "kind": "video",
        "label": "clip",
        "size_bytes": dummy.stat().st_size,
        "content_sha256": hashlib.sha256(dummy.read_bytes()).hexdigest(),
        "duration_ticks": 3 * T,
        "width": 320,
        "height": 180,
        "has_audio": False,
    }

    def with_media(project: Project) -> Project:
        project.assets["a"].verified = VerifiedMedia.model_validate(verified)
        return project

    moving = picture(clip_payload(keyframes=[key("mask_x", 0, 0.25), key("mask_x", 3 * T, 0.75)]))
    moving = with_media(moving)
    clip = moving.clips["c"]
    validate_timeline(moving)
    for at, want in ((0, 0.25), (FRAME, 0.25 + 0.5 / 90), (45 * FRAME, 0.5), (3 * T, 0.75)):
        assert abs(sample(clip, "mask_x", at) - want) < 1e-12, (at, sample(clip, "mask_x", at))
        assert sample(clip, "mask_y", at) == 0.5

    graph = "\n".join(compile_render_plan(moving, "h264-source-quality").filters)
    line = next(row for row in graph.splitlines() if "alpha(X,Y)" in row and "geq" in row)
    assert "T" in line.split("a='alpha(X,Y)*(")[1], "the mask box must be a function of frame time"
    assert line.count("if(lt((T") >= 2, line[:400]
    static = "\n".join(
        compile_render_plan(with_media(picture(clip_payload())), "h264-source-quality").filters
    )
    quiet = next(row for row in static.splitlines() if "alpha(X,Y)" in row and "geq" in row)
    assert "if(lt((T" not in quiet, "an unkeyframed mask keeps the cheap constant expression"
    assert alpha_expression(clip.mask) in quiet

    # The registers that cache a per-frame bezier must not collide inside one geq evaluator.
    eased = [
        {
            **key("mask_x", 0, 0.25),
            "interpolation": "bezier",
            "bezier": {"x1": 0.4, "y1": 0, "x2": 0.6, "y2": 1},
        },
        key("mask_x", 3 * T, 0.75),
        {
            **key("mask_y", 0, 0.2),
            "interpolation": "bezier",
            "bezier": {"x1": 0.2, "y1": 0, "x2": 0.8, "y2": 1},
        },
        key("mask_y", 3 * T, 0.8),
    ]
    both = picture(clip_payload(keyframes=eased))
    line = next(
        row
        for row in "\n".join(
            compile_render_plan(with_media(both), "h264-source-quality").filters
        ).splitlines()
        if "alpha(X,Y)" in row
    )
    for slot in ("st(11,T+1)", "st(13,T+1)"):
        assert slot in line, slot
    assert "st(11,T+1);st(10" in line and "st(13,T+1);st(12" in line, line[:600]

    manifest = preview_manifest(moving)["clips"]["c"]
    curves = manifest["mask_curves"]
    assert set(curves) == {"mask_x"}, curves
    assert [round(point["value"], 6) for point in curves["mask_x"]] == [0.25, 0.75], curves
    assert [round(point["offset"], 6) for point in curves["mask_x"]] == [0.0, 1.0], curves
    assert [point["easing"] for point in curves["mask_x"]] == ["linear", "linear"], curves
    unit = urllib.parse.unquote(manifest["mask_unit"])
    assert 'x="0" y="0" width="100" height="100"' in unit, unit[:200]
    plain = preview_manifest(picture(clip_payload()))["clips"]["c"]
    assert plain["mask_curves"] is None and plain["mask_unit"] is None, plain


def rejection_suite() -> None:
    corners = [key("mask_x", 0, 0.25), key("mask_x", 3 * T, 0.75)]
    for label, clip in (
        ("no mask", clip_payload(mask=None, keyframes=corners)),
        (
            "path",
            clip_payload(
                mask={
                    **MASK,
                    "shape": "path",
                    "vertices": [
                        {"x": 0.2, "y": 0.2, "handle_out": [0, 0], "handle_in": [0, 0]},
                        {"x": 0.8, "y": 0.2, "handle_out": [0, 0], "handle_in": [0, 0]},
                        {"x": 0.2, "y": 0.8, "handle_out": [0, 0], "handle_in": [0, 0]},
                    ],
                },
                keyframes=corners,
            ),
        ),
        ("inverted", clip_payload(mask={**MASK, "inverted": True}, keyframes=corners)),
    ):
        try:
            validate_timeline(picture(clip))
        except EditorError as error:
            assert error.code == "INVALID_MASK", (label, error.payload())
            assert error.details["clip_id"] == "c", (label, error.details)
            assert error.message, (label, error)
        else:
            raise AssertionError(f"{label} must reject mask keyframes")
    # A feathered, non-inverted ellipse still animates.
    validate_timeline(
        picture(
            clip_payload(
                mask={**MASK, "feather": 0.3},
                keyframes=[key("mask_width", 0, 0.2), key("mask_width", 3 * T, 0.9)],
            )
        )
    )
    try:
        Clip.model_validate(
            clip_payload(keyframes=[key("mask_x", 0, 1.5), key("mask_x", 3 * T, 0.75)])
        )
    except Exception as error:
        assert "mask_x" in str(error), error
    else:
        raise AssertionError("a centre outside the frame must be refused")


def http_suite(folder: Path) -> None:
    token = "maskanim" + "d" * 48
    with TestClient(
        create_app(folder / "db.sqlite3", token),
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        capabilities = client.get("/v1/capabilities").json()
        assert capabilities["features"]["mask_animation"] is True
        assert "keyframe.set" in capabilities["commands"]

        project = client.post("/v1/projects", json={"request_id": "new", "name": "mask"}).json()[
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

        points = [
            key("mask_x", 0, 0.25),
            key("mask_x", 3 * T, 0.75),
            key("mask_height", 0, 0.8),
            key("mask_height", 3 * T, 0.3),
        ]
        command = [{"op": "keyframe.set", "clip_id": "c", "keyframe": point} for point in points]
        written = edit("k1", 1, command)
        assert written.status_code == 200, written.text
        stored = written.json()["project"]["clips"]["c"]["keyframes"]
        assert sorted((k["property"], k["at_ticks"]) for k in stored) == sorted(
            (k["property"], k["at_ticks"]) for k in points
        ), stored

        replay = edit("k1", 1, command)
        assert replay.json()["replayed"] is True and replay.json()["project"]["revision"] == 2
        conflict = edit(
            "k2",
            1,
            [{"op": "keyframe.remove", "clip_id": "c", "property": "mask_x", "at_ticks": 0}],
        )
        assert conflict.status_code == 409, conflict.text

        dry = edit(
            "k3",
            2,
            [{"op": "keyframe.remove", "clip_id": "c", "property": "mask_x", "at_ticks": 0}],
            dry=True,
        )
        assert dry.status_code == 200 and not dry.json()["committed"], dry.text
        assert client.get(path).json()["revision"] == 2, "a dry run must not write"

        sample_at = client.get(
            path + "/clips/c/sample?revision=2&at_ticks=" + str(45 * FRAME)
        ).json()
        assert abs(sample_at["values"]["mask_x"] - 0.5) < 1e-9, sample_at
        assert abs(sample_at["values"]["mask_height"] - 0.55) < 1e-9, sample_at

        curve = client.post(
            "/v1/animation/curve?property=mask_height", json=written.json()["project"]["clips"]["c"]
        ).json()
        assert curve["limits"] == [0.01, 2], curve["limits"]
        assert [point["value"] for point in curve["curve"]] == [0.8, 0.3], curve["curve"]
        assert [point["offset"] for point in curve["curve"]] == [0.0, 1.0], curve["curve"]

        dropped = edit("k4", 2, [{"op": "clip.mask", "clip_id": "c", "mask": None}])
        assert dropped.json()["error"]["code"] == "INVALID_MASK", dropped.text
        assert client.get(path).json()["revision"] == 2, "removing an animated mask must fail whole"

        inverted = edit(
            "k5", 2, [{"op": "clip.mask", "clip_id": "c", "mask": {**MASK, "inverted": True}}]
        )
        assert inverted.json()["error"]["code"] == "INVALID_MASK", inverted.text
        pathed = edit(
            "k6",
            2,
            [
                {
                    "op": "clip.mask",
                    "clip_id": "c",
                    "mask": {
                        **MASK,
                        "shape": "path",
                        "vertices": [
                            {"x": 0.2, "y": 0.2, "handle_out": [0, 0], "handle_in": [0, 0]},
                            {"x": 0.8, "y": 0.2, "handle_out": [0, 0], "handle_in": [0, 0]},
                            {"x": 0.2, "y": 0.8, "handle_out": [0, 0], "handle_in": [0, 0]},
                        ],
                    },
                }
            ],
        )
        assert pathed.json()["error"]["code"] == "INVALID_MASK", pathed.text

        locked = edit(
            "k7",
            2,
            [
                {"op": "track.update", "track_id": "v", "locked": True},
                {"op": "keyframe.set", "clip_id": "c", "keyframe": key("mask_y", T, 0.4)},
            ],
        )
        assert locked.json()["error"]["code"] == "TRACK_LOCKED", locked.text
        assert client.get(path).json()["revision"] == 2, "a locked batch must not write"

        added = edit(
            "k8", 2, [{"op": "keyframe.set", "clip_id": "c", "keyframe": key("mask_y", T, 0.4)}]
        )
        assert added.status_code == 200, added.text
        history = client.get(path + "/history").json()["history"]
        restore = client.post(
            path + "/restore",
            json={
                "request_id": "k9",
                "expected_revision": 3,
                "target_revision": next(
                    entry["revision"] for entry in history if entry["revision"] == 1
                ),
            },
        )
        assert restore.status_code == 200, restore.text
        back = restore.json()["project"]
        assert back["revision"] == 4 and back["clips"]["c"]["keyframes"] == [], back["clips"]["c"][
            "keyframes"
        ]


def trimmed_clock_suite() -> None:
    clip = picture(
        clip_payload(keyframes=[key("mask_x", 0, 0.0), key("mask_x", 3 * T, 1.0)])
    ).clips["c"]
    # Trimming 1s off the head keeps the same source clock, so the visible value starts at 1/3.
    trimmed = picture(
        clip_payload(
            source_in_ticks=0,
            keyframes=[key("mask_x", 0, 0.0), key("mask_x", 3 * T, 1.0)],
            animation_offset_ticks=FRAME * 30,
        )
    )
    trimmed.clips["c"].animation_offset_ticks = FRAME * 30
    assert abs(sample(trimmed.clips["c"], "mask_x", 0) - 1 / 3) < 1e-9, sample(
        trimmed.clips["c"], "mask_x", 0
    )
    assert clip.duration_ticks == trimmed.clips["c"].duration_ticks


def media_suite(folder: Path) -> None:
    source = folder / "white.mp4"
    run(
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=white:s=320x180:r=30:d=3",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ]
    )
    verified = {
        "probe_id": "a",
        "path": str(source),
        "kind": "video",
        "label": "white",
        "size_bytes": source.stat().st_size,
        "content_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "duration_ticks": 3 * T,
        "width": 320,
        "height": 180,
        "has_audio": False,
    }

    def render(mask: dict, name: str) -> Path:
        project = picture(
            clip_payload(
                mask=mask,
                keyframes=[key("mask_x", 0, 0.25), key("mask_x", 3 * T, 0.75)],
            )
        )
        project.assets["a"].verified = VerifiedMedia.model_validate(verified)
        out = folder / name
        plan = compile_render_plan(project, "h264-source-quality")
        job = folder / f"job-{name}"
        job.mkdir(exist_ok=True)
        for fname, body in plan.text_files.items():
            (job / fname).write_text(body, encoding="utf-8")
        result = subprocess.run(
            plan.ffmpeg_argv(str(FFMPEG), str(out)),
            cwd=job,
            capture_output=True,
            timeout=300,
            creationflags=0x08000000,
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")[-1200:]
        return out

    def level(out: Path, at: float, x_ratio: float) -> float:
        raw = run(
            [
                "-ss",
                f"{at:.6f}",
                "-i",
                str(out),
                "-frames:v",
                "1",
                "-vf",
                f"crop=6:6:{int(x_ratio * 320) - 3}:87",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ]
        )
        return sum(raw[i] for i in range(0, len(raw), 3)) / (len(raw) // 3)

    hard = render({**MASK, "center_x": 0.25, "center_y": 0.5}, "moving.mp4")
    # The ellipse spans center +- 0.2, so 0.33 and 0.6 swap sides as the centre crosses them.
    assert level(hard, 0.1, 0.33) > 200 and level(hard, 0.1, 0.6) < 40, (
        level(hard, 0.1, 0.33),
        level(hard, 0.1, 0.6),
    )
    assert level(hard, 1.5, 0.33) > 200 and level(hard, 1.5, 0.6) > 200, (
        level(hard, 1.5, 0.33),
        level(hard, 1.5, 0.6),
    )
    assert level(hard, 2.9, 0.33) < 40 and level(hard, 2.9, 0.6) > 200, (
        level(hard, 2.9, 0.33),
        level(hard, 2.9, 0.6),
    )
    # Half way through, the centre is 0.5: the edge sits at 0.3 and 0.7.
    assert level(hard, 1.5, 0.28) < 40 and level(hard, 1.5, 0.72) < 40, (
        level(hard, 1.5, 0.28),
        level(hard, 1.5, 0.72),
    )

    # Feather makes the edge a ramp: 0.15 of feather spans 0.4367..0.4667 at t=0.1, so 0.45 is half
    # transparent there and fully opaque once the curve carries the centre past it.
    soft = render({**MASK, "center_x": 0.25, "center_y": 0.5, "feather": 0.15}, "feather.mp4")
    ramp = level(soft, 0.1, 0.45)
    assert 20 < ramp < 235, ramp
    assert level(soft, 0.1, 0.65) < 40 and level(soft, 2.9, 0.45) < 40, (
        level(soft, 0.1, 0.65),
        level(soft, 2.9, 0.45),
    )
    assert level(soft, 2.9, 0.65) > 200, level(soft, 2.9, 0.65)


def main():
    with tempfile.TemporaryDirectory(prefix="agentcut-maskanim-") as scratch:
        folder = Path(scratch)
        geometry_suite(folder)
        rejection_suite()
        trimmed_clock_suite()
        http_suite(folder)
        media_suite(folder)
    print(
        "PASS: keyframed mask geometry, frame-time alpha, unit mask plan, animated-clock trimming, "
        "atomic HTTP edits, INVALID_MASK guards, and real pixels that follow the curve"
    )


if __name__ == "__main__":
    main()
