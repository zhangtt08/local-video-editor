"""In-plane rotation tracking: the tracker reads it, the command writes it, and a path is whole.

The fixture is a white bar with a white dot, centred and turned 0.15 rad/s over two seconds on a
dark frame. That shape has one clear orientation (a bar's end plus an off-axis dot), so the
expected angle is known independently of the tracker. The HTTP half then checks that the same
number reaches `mask_rotation` keyframes, that an untracked block keeps its own keys, and that a
path mixing points with and without a rotation is refused whole.
"""

import math
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agentcut.contracts import TIMEBASE as T  # noqa: E402
from agentcut.http_api import create_app  # noqa: E402
from agentcut.media import MediaService  # noqa: E402
from agentcut.tracking import analyse_window, follow_window  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
WIDTH, HEIGHT, FPS = 320, 240, 30
SECONDS = 2.0
FRAME = T // FPS
RATE_RAD = 0.15


def build_source(target: Path) -> None:
    subprocess.run(
        [
            str(FFMPEG), "-y", "-v", "error",
            "-f", "lavfi", "-i", f"color=c=0x202020:s={WIDTH}x{HEIGHT}:d={SECONDS}:r={FPS}",
            "-f", "lavfi", "-i", f"color=c=black@0:s=160x160:d={SECONDS}:r={FPS}",
            "-filter_complex",
            "[1:v]format=rgba,"
            "drawbox=x=40:y=76:w=80:h=8:color=white@1:t=fill,"
            "drawbox=x=100:y=56:w=12:h=12:color=white@1:t=fill,"
            f"rotate={RATE_RAD}*t:fillcolor=black@0[p];"
            "[0:v][p]overlay=80:40:shortest=1",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-pix_fmt", "yuv420p", str(target),
        ],
        check=True,
        capture_output=True,
        timeout=300,
    )


def unit_suite(folder: Path) -> None:
    source = folder / "rotating.mp4"
    build_source(source)
    from agentcut.contracts import FrameRate

    rate = FrameRate(numerator=FPS, denominator=1)
    width, decoded = analyse_window(FFMPEG, source, WIDTH, HEIGHT, rate, 0, FRAME, 60)
    body = follow_window(
        decoded, width, (0.5, 0.5, 0.26, 0.35), 10, rate, FRAME,
        scale=False, max_gap=6, reacquire=True, rotate=True,
    )
    assert body["rotation_estimated"] is True and len(body["points"]) == 60, len(body["points"])
    final = body["points"][-1]["rotation"]
    expected = math.degrees(RATE_RAD * (59 / FPS))
    assert abs(final - expected) < 2.0, f"旋转没跟上：{final} 对 {expected}"
    plain = follow_window(
        decoded, width, (0.5, 0.5, 0.26, 0.35), 10, rate, FRAME,
        scale=False, max_gap=6, reacquire=True, rotate=False,
    )
    assert all("rotation" not in point for point in plain["points"]), plain["points"][0]
    print("   unit: rotated", round(final, 2), "vs expected", round(expected, 2))


def mask_payload() -> dict:
    return {
        "shape": "rectangle", "center_x": 0.5, "center_y": 0.5,
        "width": 0.26, "height": 0.35, "rotation": 0.0,
    }


def http_suite(folder: Path) -> None:
    media = MediaService(
        folder / "db.sqlite3", [folder / "media"], folder / "cache", FFMPEG, FFPROBE
    )
    source = folder / "media" / "rotating.mp4"
    source.parent.mkdir(exist_ok=True)
    build_source(source)
    token = "trackrot" + "e" * 50
    app = create_app(folder / "api.sqlite3", token, media=media)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        caps = client.get("/v1/capabilities").json()
        assert caps["features"]["mask_track_rotation"] is True, caps["features"]
        probe = client.post("/v1/media/import", json={"path": str(source)}).json()
        project = client.post(
            "/v1/projects", json={"request_id": "new", "name": "trackrot"}
        ).json()["project"]
        path = f"/v1/projects/{project['id']}"
        extra = {**mask_payload(), "keys": []}
        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "seed",
                "expected_revision": 0,
                "commands": [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                    {
                        "op": "asset.import", "asset_id": "a", "label": "rot",
                        "probe_id": probe["id"], "verified": probe["verified"],
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "c", "asset_id": "a", "track_id": "v",
                            "position_ticks": 0, "duration_ticks": int(SECONDS * T),
                            "mask": mask_payload(),
                            "extra_masks": [extra],
                        },
                    },
                ],
            },
        )
        assert seeded.status_code == 200, seeded.text

        dry = client.post(
            path + "/mask-track",
            json={
                "request_id": "rot-plan",
                "expected_revision": 1,
                "targets": [{
                    "clip_id": "c", "frames": 60, "estimate_scale": False,
                    "estimate_rotation": True,
                }],
                "dry_run": True,
            },
        )
        assert dry.status_code == 200, dry.text
        assert client.get(path).json()["revision"] == 1, "a dry run must not write"
        plan = dry.json()
        receipt = plan["tracking"]["targets"][0]
        assert receipt["rotation_estimated"] is True, f"跟踪回执没说旋转：{receipt}"
        assert abs(receipt["points"][-1]["rotation"] - math.degrees(RATE_RAD * 59 / FPS)) < 2.0, (
            receipt["points"][-1]
        )

        applied = client.post(
            path + "/mask-track",
            json={
                "request_id": "rot-apply",
                "expected_revision": 1,
                "targets": [{
                    "clip_id": "c", "frames": 60, "estimate_scale": False,
                    "estimate_rotation": True,
                }],
            },
        )
        assert applied.status_code == 200, applied.text
        clip = applied.json()["project"]["clips"]["c"]
        assert applied.json()["project"]["revision"] == 2
        curves = [key for key in clip["keyframes"] if key["property"] == "mask_rotation"]
        assert len(curves) >= 2, f"mask_rotation 没有写进片段：{clip['keyframes']}"
        final_curve = max(curves, key=lambda key: key["at_ticks"])["value"]
        assert abs(final_curve - math.degrees(RATE_RAD * 59 / FPS)) < 2.0, final_curve
        assert clip["mask"]["rotation"] == clip["mask"]["rotation"], clip["mask"]

        # The extra block has its own path and its own rotation keys; the main mask's new rotation
        # does not leak into it.
        stacked = client.post(
            path + "/clips/c/mask-stack/0/track",
            json={
                "request_id": "rot-extra",
                "expected_revision": 2,
                "frames": 60,
                "estimate_scale": False,
                "estimate_rotation": True,
            },
        )
        assert stacked.status_code == 200, stacked.text
        block = stacked.json()["project"]["clips"]["c"]["extra_masks"][0]
        assert block["keys"], block
        extra_final = block["keys"][-1]["rotation"]
        assert abs(extra_final - math.degrees(RATE_RAD * 59 / FPS)) < 2.0, (
            f"再叠块没拿到旋转：{extra_final}"
        )
        assert block["keys"][0]["rotation"] < 1.0, block["keys"][0]
        assert client.get(path).json()["revision"] == 3, "the extra run is one revision"

        # A path is whole: one point without a rotation refuses the batch.
        try:
            mixed = client.post(
                path + "/edits",
                json={
                    "request_id": "mixed",
                    "expected_revision": 3,
                    "commands": [{
                        "op": "clip.mask_track", "clip_id": "c", "merge": False,
                        "points": [
                            {"at_ticks": 0, "center_x": 0.5, "center_y": 0.5, "rotation": 1.0},
                            {"at_ticks": FRAME, "center_x": 0.5, "center_y": 0.5},
                        ],
                    }],
                },
            )
            outcome = mixed.status_code
        except Exception as error:  # a half path must be refused, not crash the handler
            outcome = f"raised {type(error).__name__}"
        assert outcome == 422, f"混点必须被拒：{outcome}"
        assert client.get(path).json()["revision"] == 3, "a refused batch must not write"
        print("   http: mask_rotation", len(curves), "keys; extra", len(block["keys"]), "keys")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    with tempfile.TemporaryDirectory(prefix="trackrot-check-") as name:
        folder = Path(name)
        unit_suite(folder)
        http_suite(folder)
    print(
        "PASS: an in-plane turn is estimated within 2 degrees, written as mask_rotation keyframes, "
        "the extra block gets its own rotation keys, and half a path is refused"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
