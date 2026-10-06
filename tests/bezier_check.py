"""Independent cubic geometry, native FFmpeg evaluation, bounds and old receipts."""

import hashlib
import json
import math
import struct
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentcut.animation import expression, property_curve, sample
from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import Bezier, Clip, CreateProject, EditBatch, Keyframe
from agentcut.http_api import create_app
from agentcut.projects import ProjectStore

ROOT = Path(__file__).resolve().parent.parent


def cubic(p0, p1, p2, p3, u):
    # De Casteljau, independent of the production polynomial evaluator.
    a, b, c = [(1 - u) * x + u * y for x, y in ((p0, p1), (p1, p2), (p2, p3))]
    d, e = (1 - u) * a + u * b, (1 - u) * b + u * c
    return (1 - u) * d + u * e


def independent(control, at):
    if at <= 0 or at >= 1:
        return max(0, min(1, at))
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        value = cubic(0, control[0], control[2], 1, mid)
        if value == at:
            return cubic(0, control[1], control[3], 1, mid)
        if value < at:
            lo = mid
        else:
            hi = mid
    return cubic(0, control[1], control[3], 1, (lo + hi) / 2)


def main():
    ffmpeg = ROOT / "desktop/resources/bin/ffmpeg.exe"
    tested = 0
    for control in (
        (0.12, 0.8, 0.8, 0.1),
        (1, 0, 0, 1),
        (0, 0, 0, 1),
        (1, 0, 1, 1),
        (0.2, -0.5, 0.8, 1.5),
    ):
        bezier = Bezier(x1=control[0], y1=control[1], x2=control[2], y2=control[3])
        clip = Clip(
            id="c",
            asset_id="m",
            track_id="v",
            position_ticks=0,
            duration_ticks=2 * T,
            keyframes=[
                Keyframe(
                    property="opacity", at_ticks=0, value=0.2, interpolation="bezier", bezier=bezier
                ),
                Keyframe(property="opacity", at_ticks=2 * T, value=0.8),
            ],
        )
        for offset, duration in ((0, 2 * T), (T // 4, T), (T, T // 2)):
            window = clip.model_copy(
                update={"animation_offset_ticks": offset, "duration_ticks": duration}
            )
            curve = property_curve(window, "opacity")
            for i in range(61):
                at = duration * i / 60
                expected = 0.2 + 0.6 * independent(control, (at + offset) / (2 * T))
                assert math.isclose(sample(window, "opacity", at), expected, abs_tol=1e-10)
                fraction = at / duration
                left, right = next(
                    (
                        (a, b)
                        for a, b in zip(curve, curve[1:])
                        if a["offset"] <= fraction <= b["offset"]
                    ),
                    (curve[-2], curve[-1]),
                )
                easing = list(map(float, left["easing"][13:-1].split(",")))
                mix = independent(
                    easing, (fraction - left["offset"]) / (right["offset"] - left["offset"])
                )
                value = left["value"] + (right["value"] - left["value"]) * mix
                assert math.isclose(value, expected, abs_tol=2e-8), (
                    control,
                    offset,
                    at,
                    value,
                    expected,
                    curve,
                )
            # Native per-sample eval verifies clock inversion and controlled expression syntax.
            expr = expression(window, "opacity")
            result = subprocess.run(
                [
                    str(ffmpeg),
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    f"aevalsrc='{expr}':s=100:d={duration / T}",
                    "-f",
                    "f64le",
                    "pipe:1",
                ],
                capture_output=True,
                check=True,
                creationflags=0x08000000,
            )
            values = struct.unpack("<" + "d" * (len(result.stdout) // 8), result.stdout)
            for i, value in enumerate(values[: math.ceil(duration / T * 100)]):
                assert abs(value - sample(window, "opacity", i * T / 100)) < 1e-8, (
                    control,
                    i,
                    value,
                )
            tested += 1
        # geq cache must initialize at frame zero and update across every frame.
        expr = expression(clip, "opacity", "T")
        result = subprocess.run(
            [
                str(ffmpeg),
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=white:s=16x16:r=30:d=2",
                "-vf",
                f"format=gray,geq=lum='255*({expr})'",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "gray",
                "pipe:1",
            ],
            capture_output=True,
            check=True,
            creationflags=0x08000000,
        )
        assert len(result.stdout) == 60 * 256
        for i in range(60):
            expected = sample(clip, "opacity", i * T / 30) * 255
            assert all(abs(v - expected) <= 1.01 for v in result.stdout[i * 256 : (i + 1) * 256]), (
                control,
                i,
                expected,
            )

    with tempfile.TemporaryDirectory() as folder:
        store = ProjectStore(Path(folder) / "db.sqlite")
        project = store.create(CreateProject(request_id="new", name="Bezier")).project
        old = {
            "request_id": "old",
            "expected_revision": 0,
            "commands": [
                {
                    "op": "keyframe.set",
                    "clip_id": "c",
                    "keyframe": {
                        "property": "x",
                        "at_ticks": 0,
                        "value": 0.0,
                        "interpolation": "ease",
                    },
                }
            ],
        }
        canonical = json.dumps(["edit", old], sort_keys=True, separators=(",", ":"))
        assert (
            ProjectStore._fingerprint("edit", EditBatch.model_validate(old))
            == hashlib.sha256(canonical.encode()).hexdigest()
        )
        seed = {
            "request_id": "seed",
            "expected_revision": 0,
            "commands": [
                {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "picture"}},
                {
                    "op": "asset.register",
                    "asset": {
                        "id": "m",
                        "kind": "image",
                        "label": "still",
                        "reference": "untrusted",
                    },
                },
                {"op": "clip.add", "clip": clip.model_dump(mode="json")},
            ],
        }
        project = store.mutate(project.id, EditBatch.model_validate(seed)).project
        token = "bezier-check-" + "a" * 40
        with TestClient(
            create_app(store.path, token),
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer " + token},
        ) as client:
            move = {
                "request_id": "handles",
                "expected_revision": 1,
                "commands": [
                    {
                        "op": "keyframe.move",
                        "clip_id": "c",
                        "from_ticks": 0,
                        "keyframe": {
                            **clip.keyframes[0].model_dump(mode="json"),
                            "bezier": {"x1": 0.1, "y1": 0.4, "x2": 0.9, "y2": 0.8},
                        },
                    }
                ],
            }
            dry = client.post(f"/v1/projects/{project.id}/edits", json=move | {"dry_run": True})
            assert dry.status_code == 200, dry.text
            saved = client.post(f"/v1/projects/{project.id}/edits", json=move)
            assert saved.status_code == 200 and saved.json()["project"] == dry.json()["project"]
            assert client.post(f"/v1/projects/{project.id}/edits", json=move).json()["replayed"]
            invalid = {**move, "request_id": "out-of-range", "expected_revision": 2}
            invalid["commands"] = [
                {
                    **move["commands"][0],
                    "keyframe": {
                        **move["commands"][0]["keyframe"],
                        "bezier": {"x1": 0.1, "y1": -4, "x2": 0.9, "y2": 4},
                    },
                }
            ]
            assert client.post(f"/v1/projects/{project.id}/edits", json=invalid).status_code == 422
            assert client.get(f"/v1/projects/{project.id}").json()["revision"] == 2
            restored = client.post(
                f"/v1/projects/{project.id}/restore",
                json={"request_id": "restore", "expected_revision": 2, "target_revision": 1},
            )
            assert restored.status_code == 200, restored.text
            assert (
                restored.json()["project"]["clips"]["c"]["keyframes"]
                == clip.model_dump(mode="json")["keyframes"]
            )
    for invalid in ({"x1": -1}, {"y2": float("nan")}, {"x2": 2}):
        try:
            Bezier.model_validate(invalid)
        except ValidationError:
            pass
        else:
            raise AssertionError(invalid)
    print(
        f"PASS: {tested} independent clipped curves, temporal degeneracies/overshoot, "
        "FFmpeg audio/pixel expressions, atomic edits, retry/restore and old fingerprint"
    )


if __name__ == "__main__":
    main()
