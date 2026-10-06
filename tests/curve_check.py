"""Value graph geometry, atomic keyframe moves and an actual animated output frame."""

import math
import re
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.animation import graph_curve, property_curve, sample
from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import Clip, CreateProject, EditBatch, EditorError, Keyframe
from agentcut.http_api import create_app
from agentcut.media import MediaService
from agentcut.projects import ProjectStore
from agentcut.timeline import apply_commands

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "curve-check-" + "b" * 48


def cubic_svg_y(path, u):
    """Read SVG's control points independently to compare to the scalar animation clock."""
    nums = list(map(float, re.findall(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", path)))
    x0, y0, x1, y1, x2, y2, x3, y3 = nums
    assert math.isclose(x1, x0 + (x3 - x0) / 3, abs_tol=1e-10)
    assert math.isclose(x2, x0 + (x3 - x0) * 2 / 3, abs_tol=1e-10)
    return (1 - u) ** 3 * y0 + 3 * (1 - u) ** 2 * u * y1 + 3 * (1 - u) * u**2 * y2 + u**3 * y3


def main():
    clip = Clip(id="c", asset_id="m", track_id="v", position_ticks=0, duration_ticks=4 * T)
    clip.keyframes = [
        Keyframe(property="opacity", at_ticks=0, value=0, interpolation="ease"),
        Keyframe(property="opacity", at_ticks=4 * T, value=1),
    ]
    for offset, duration in ((0, 4 * T), (T, 2 * T), (2 * T, T)):
        window = clip.model_copy(
            update={"animation_offset_ticks": offset, "duration_ticks": duration}
        )
        graph = graph_curve(window, "opacity")
        for u in (0, 0.125, 0.5, 0.875, 1):
            assert math.isclose(
                cubic_svg_y(graph["path"], u),
                sample(window, "opacity", round(u * duration)),
                abs_tol=1e-10,
            )
        assert all(0 <= k["at_ticks"] <= duration for k in graph["keys"])
    held = clip.model_copy(deep=True)
    held.keyframes[0].interpolation = "hold"
    assert "H 1.0 V 1.0" in graph_curve(held, "opacity")["path"]
    assert sample(held, "opacity", 4 * T - 1) == 0
    assert sample(held, "opacity", 4 * T) == 1
    dense = clip.model_copy(deep=True)
    dense.keyframes = [
        Keyframe(property="x", at_ticks=i * T, value=(i % 10) / 10) for i in range(2000)
    ]
    dense.duration_ticks = 1999 * T
    started = time.perf_counter()
    assert len(property_curve(dense, "x")) == 2000
    elapsed = time.perf_counter() - started
    assert elapsed < 2, f"dense curve compilation too slow: {elapsed}s"

    with tempfile.TemporaryDirectory(prefix="agentcut-curves-") as scratch:
        folder = Path(scratch)
        media_dir = folder / "media"
        media_dir.mkdir()
        ffmpeg = ROOT / "desktop/resources/bin/ffmpeg.exe"
        ffprobe = ROOT / "desktop/resources/bin/ffprobe.exe"
        source = media_dir / "blue.mp4"
        subprocess.run(
            [
                str(ffmpeg),
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=blue:s=160x90:r=30:d=4",
                "-c:v",
                "libx264",
                str(source),
            ],
            check=True,
            creationflags=0x08000000,
        )
        media = MediaService(
            folder / "test.sqlite3", [media_dir], folder / "cache", ffmpeg, ffprobe
        )
        store = ProjectStore(media.db_path, media)
        project = store.create(CreateProject(request_id="new", name="curves")).project
        probe = media.import_file(str(source))
        project = store.mutate(
            project.id,
            EditBatch.model_validate(
                {
                    "request_id": "seed",
                    "expected_revision": 0,
                    "commands": [
                        {
                            "op": "track.add",
                            "track": {"id": "v", "kind": "video", "name": "picture"},
                        },
                        {
                            "op": "asset.import",
                            "asset_id": "m",
                            "label": "blue",
                            "probe_id": probe.id,
                            "verified": probe.verified.model_dump(),
                        },
                        {"op": "clip.add", "clip": clip.model_dump()},
                    ],
                }
            ),
        ).project
        move = {
            "op": "keyframe.move",
            "clip_id": "c",
            "from_ticks": 4 * T,
            "keyframe": {
                "property": "opacity",
                "at_ticks": 2 * T,
                "value": 0.8,
                "interpolation": "linear",
            },
        }
        with TestClient(
            create_app(store.path, TOKEN, media),
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client:
            before = client.get(f"/v1/projects/{project.id}/history").json()
            read = client.post(
                "/v1/animation/curve?property=opacity", json=project.clips["c"].model_dump()
            )
            assert read.status_code == 200, read.text
            assert read.json() == graph_curve(project.clips["c"], "opacity") | {"limits": [0, 1]}
            values = client.post(
                f"/v1/animation/sample?at_ticks={T}", json=project.clips["c"].model_dump()
            )
            assert values.status_code == 200, values.text
            assert values.json()["values"]["opacity"] == 0.15625
            saved = client.get(f"/v1/projects/{project.id}/clips/c/sample?at_ticks={T}")
            assert saved.json()["values"] == values.json()["values"]
            changed = project.clips["c"].model_copy(deep=True)
            changed.keyframes[-1].value = 0.8
            candidate_values = client.post(
                f"/v1/animation/sample?at_ticks={T}", json=changed.model_dump()
            )
            assert candidate_values.json()["values"]["opacity"] == 0.125
            for at in (-1, changed.duration_ticks + 1, "nan"):
                assert (
                    client.post(
                        f"/v1/animation/sample?at_ticks={at}", json=changed.model_dump()
                    ).status_code
                    == 422
                )
            assert store.get(project.id) == project
            assert client.get(f"/v1/projects/{project.id}/history").json() == before
            body = {"request_id": "move", "expected_revision": 1, "commands": [move]}
            dry = client.post(f"/v1/projects/{project.id}/edits", json=body | {"dry_run": True})
            assert dry.status_code == 200 and not dry.json()["committed"]
            assert store.get(project.id).revision == 1
            moved = client.post(f"/v1/projects/{project.id}/edits", json=body)
            assert moved.status_code == 200, moved.text
            retry = client.post(f"/v1/projects/{project.id}/edits", json=body)
            assert retry.status_code == 200 and retry.json()["replayed"]
            assert store.get(project.id).revision == 2
            current = store.get(project.id)
            assert current.clips["c"].keyframes[-1].at_ticks == 2 * T
            pixel, _ = media.render_frame(current, T)
            path = folder / "frame.png"
            path.write_bytes(pixel)
            rgb = subprocess.run(
                [
                    str(ffmpeg),
                    "-v",
                    "error",
                    "-i",
                    str(path),
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "pipe:1",
                ],
                capture_output=True,
                check=True,
                creationflags=0x08000000,
            ).stdout
            assert 95 <= rgb[2] <= 108, rgb[:3]
            bad = client.post(
                f"/v1/projects/{project.id}/edits",
                json={
                    "request_id": "collision",
                    "expected_revision": 2,
                    "commands": [move | {"from_ticks": 0}],
                },
            )
            assert bad.status_code == 422 and bad.json()["error"]["code"] == "KEYFRAME_COLLISION"
            assert store.get(project.id) == current
            assert (
                client.post(
                    "/v1/animation/curve?property=script", json=clip.model_dump()
                ).status_code
                == 422
            )
            assert (
                client.post(
                    "/v1/animation/curve?property=opacity",
                    json=clip.model_dump() | {"script": "anything"},
                ).status_code
                == 422
            )

        for commands, expected in (
            ([move | {"from_ticks": T}], "KEYFRAME_NOT_FOUND"),
            ([move | {"keyframe": {**move["keyframe"], "at_ticks": 5 * T}}], "INVALID_KEYFRAME"),
            (
                [
                    {"op": "track.update", "track_id": "v", "locked": True},
                    move | {"from_ticks": 2 * T},
                ],
                "TRACK_LOCKED",
            ),
        ):
            try:
                apply_commands(
                    current,
                    EditBatch.model_validate(
                        {"request_id": "bad", "expected_revision": 2, "commands": commands}
                    ).commands,
                )
                raise AssertionError("move should fail")
            except EditorError as error:
                assert error.code == expected, error.code
            assert current == store.get(project.id)
        trimmed = current.model_copy(deep=True)
        trimmed.clips["c"].animation_offset_ticks = T
        trimmed.clips["c"].duration_ticks = 2 * T
        moved = apply_commands(
            trimmed,
            EditBatch.model_validate(
                {
                    "request_id": "offset",
                    "expected_revision": 2,
                    "commands": [
                        move
                        | {
                            "from_ticks": T,
                            "keyframe": {**move["keyframe"], "at_ticks": 3 * T // 2},
                        }
                    ],
                }
            ).commands,
        )
        assert moved.clips["c"].keyframes[-1].at_ticks == 5 * T // 2
        assert moved.clips["c"].keyframes[0] == trimmed.clips["c"].keyframes[0]
    print(
        f"PASS: scalar/SVG clipped curves, hold edges, 2000 keys ({elapsed * 1000:.1f}ms), "
        "move replay/rollback/locks/offset and real pixels"
    )


if __name__ == "__main__":
    main()
