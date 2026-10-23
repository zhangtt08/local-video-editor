"""Multi-target tracking: one extra mask follows its own subject while the others stay put.

The fixture is a white box sliding across a dark frame at a known speed. Two extra masks are
stacked: box 0 is static, box 1 starts on the moving subject. Tracking box 1 must write its own
box keys (decimated, but faithful), and box 0 plus the clip's main mask must come back byte for
byte. The test also measures the source's own centroid, so the expected positions are independent
of the tracker's answer.
"""

import math
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agentcut.contracts import (  # noqa: E402
    MASK_EXTRA_KEY_LIMIT,
)
from agentcut.contracts import (
    TIMEBASE as T,
)
from agentcut.http_api import create_app  # noqa: E402
from agentcut.media import MediaService  # noqa: E402
from agentcut.tracking import simplify_path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
WIDTH, HEIGHT, FPS = 320, 240, 30
SECONDS = 3.0
FRAME = T // FPS
START_X, DRIFT = 40.0, 180.0


def build_source(target: Path) -> None:
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
            f"color=c=0x202020:s={WIDTH}x{HEIGHT}:d={SECONDS}:r={FPS}",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=70x70:d=3:r=30",
            # A plain white square has no texture, and normalised correlation needs some: a dark
            # stripe through it keeps the centroid where it was while giving the template edges.
            "-f",
            "lavfi",
            "-i",
            "color=c=0x101010:s=10x70:d=3:r=30",
            "-filter_complex",
            f"[0:v][1:v]overlay=x='{START_X}+{DRIFT}*t/{SECONDS}':y=80:shortest=1[a];"
            f"[a][2:v]overlay=x='{START_X + 30}+{DRIFT}*t/{SECONDS}':y=80:shortest=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ],
        check=True,
        capture_output=True,
        timeout=300,
    )


def centroid(source: Path, seconds: float) -> tuple[float, float]:
    """The white box's centre in picture fractions, read from the decoded frame itself."""
    raw = subprocess.run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-ss",
            f"{seconds:.6f}",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-vf",
            "format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=120,
    ).stdout
    xs: list[int] = []
    ys: list[int] = []
    for index, value in enumerate(raw):
        if value > 200:
            xs.append(index % WIDTH)
            ys.append(index // WIDTH)
    assert xs, f"no white box at {seconds}s"
    return sum(xs) / len(xs) / WIDTH, sum(ys) / len(ys) / HEIGHT


def extra(x: float, y: float, w: float, h: float) -> dict:
    return {
        "shape": "rectangle",
        "center_x": x,
        "center_y": y,
        "width": w,
        "height": h,
        "rotation": 0.0,
        "feather": 0.0,
        "inverted": False,
        "keys": [],
    }


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    with tempfile.TemporaryDirectory(prefix="extratrack-check-") as name:
        folder = Path(name)
        media_root = folder / "media"
        media_root.mkdir()
        source = media_root / "moving.mp4"
        build_source(source)
        left, top = centroid(source, 0.0)
        later = centroid(source, 2.0)
        assert later[0] - left > 0.3, (left, later)
        print("   source box:", round(left, 3), "->", round(later[0], 3))

        media = MediaService(
            folder / "db.sqlite3", [media_root], folder / "cache", FFMPEG, FFPROBE
        )
        token = "extratrack" + "e" * 50
        app = create_app(folder / "api.sqlite3", token, media=media)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["extra_mask_track"] is True, caps["features"]
            assert caps["limits"]["extra_mask_keys"] == MASK_EXTRA_KEY_LIMIT, caps["limits"]
            probe = client.post("/v1/media/import", json={"path": str(source)}).json()
            project = client.post(
                "/v1/projects", json={"request_id": "new", "name": "extratrack"}
            ).json()["project"]
            path = f"/v1/projects/{project['id']}"
            moved = extra(left, top, 70 / WIDTH, 70 / HEIGHT)
            still = extra(0.15, 0.15, 0.16, 0.14)
            seeded = client.post(
                path + "/edits",
                json={
                    "request_id": "seed",
                    "expected_revision": 0,
                    "commands": [
                        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                        {"op": "track.add", "track": {"id": "v2", "kind": "video", "name": "v2"}},
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
                                "duration_ticks": int(SECONDS * T),
                                "mask": {
                                    "shape": "rectangle",
                                    "center_x": 0.5,
                                    "center_y": 0.5,
                                    "width": 0.2,
                                    "height": 0.2,
                                },
                                "extra_masks": [still, moved],
                            },
                        },
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "c2",
                                "asset_id": "a",
                                "track_id": "v2",
                                "position_ticks": 0,
                                "duration_ticks": int(SECONDS * T),
                                "speed_percent": 100,
                                "speed_curve": [
                                    {"at_ticks": 0, "percent": 100},
                                    {"at_ticks": T, "percent": 150},
                                ],
                                "extra_masks": [still],
                            },
                        },
                    ],
                },
            )
            assert seeded.status_code == 200, seeded.text
            before = client.get(path).json()
            main_before = before["clips"]["c"]["mask"]
            still_before = before["clips"]["c"]["extra_masks"][0]

            route = path + "/clips/c/mask-stack/1/track"
            dry = client.post(
                route,
                json={
                    "request_id": "plan",
                    "expected_revision": 1,
                    "from_ticks": 0,
                    "frames": 60,
                    "dry_run": True,
                },
            )
            assert dry.status_code == 200, dry.text
            plan = dry.json()
            assert plan["committed"] is False and client.get(path).json()["revision"] == 1, (
                "干跑必须不写库"
            )
            assert len(plan["commands"]) == 1 and plan["commands"][0]["op"] == "clip.mask_stack"
            assert plan["track"]["written_keys"] <= MASK_EXTRA_KEY_LIMIT, (
                f"写入的框点超过这一块的额度：{plan['track']}"
            )
            assert plan["track"]["tracked_frames"] >= 55, plan["track"]

            applied = client.post(
                route,
                json={
                    "request_id": "apply",
                    "expected_revision": 1,
                    "from_ticks": 0,
                    "frames": 60,
                },
            )
            assert applied.status_code == 200, applied.text
            body = applied.json()
            assert body["project"]["revision"] == 2, body["project"]["revision"]
            after = body["project"]["clips"]["c"]
            assert after["mask"] == main_before, "the main mask moved with the extra block"
            assert after["extra_masks"][0] == still_before, "the untracked block changed"
            keys = after["extra_masks"][1]["keys"]
            assert 2 <= len(keys) <= MASK_EXTRA_KEY_LIMIT, keys
            assert keys == sorted(keys, key=lambda key: key["at_ticks"]), keys
            last = keys[-1]
            assert abs(last["center_x"] - later[0]) < 0.04, (last, later)
            assert keys[0]["center_x"] < 0.3, keys[0]
            print(
                "   tracked keys:",
                len(keys),
                f"x {keys[0]['center_x']:.3f} -> {last['center_x']:.3f}",
                "vs source",
                f"{left:.3f} -> {later[0]:.3f}",
            )

            replay = client.post(
                route,
                json={
                    "request_id": "apply",
                    "expected_revision": 1,
                    "from_ticks": 0,
                    "frames": 60,
                },
            )
            assert replay.status_code == 200 and replay.json()["replayed"] is True, replay.text
            stale = client.post(
                route,
                json={
                    "request_id": "stale",
                    "expected_revision": 1,
                    "from_ticks": 0,
                    "frames": 60,
                },
            )
            assert stale.status_code == 409, stale.text

            bad = client.post(
                route.replace("/mask-stack/1/", "/mask-stack/9/"),
                json={"request_id": "bad-index", "expected_revision": 2, "frames": 30},
            )
            assert bad.status_code == 422, f"越界的块号必须按名字拒绝：{bad.text}"
            assert bad.json()["error"]["code"] == "INVALID_TRACK_TARGET", bad.text
            late = client.post(
                route,
                json={"request_id": "late", "expected_revision": 2, "from_ticks": int(SECONDS * T)},
            )
            assert late.status_code == 422, late.text
            curved = client.post(
                path + "/clips/c2/mask-stack/0/track",
                json={"request_id": "curved", "expected_revision": 2, "frames": 30},
            )
            assert curved.status_code == 422, curved.text
            assert curved.json()["error"]["code"] == "INVALID_MASK", (
                f"带变速曲线的片段必须按名字拒绝：{curved.text}"
            )
            tail = client.post(
                route,
                json={
                    "request_id": "tail",
                    "expected_revision": 2,
                    "from_ticks": int(SECONDS * T) - FRAME,
                    "frames": 60,
                },
            )
            assert tail.status_code == 422, tail.text
            assert tail.json()["error"]["code"] == "SOURCE_OUT_OF_BOUNDS", (
                f"尾部越界必须按名字拒绝：{tail.text}"
            )
            assert client.get(path).json()["revision"] == 2, "refusals must not write"

        # The decimator keeps the ends and only spends a point where a line cannot replace it.
        straight = [
            {"mask_x": i / 99, "mask_y": 0.5, "width": 0.2, "height": 0.2}
            for i in range(100)
        ]
        kept, coarse = simplify_path(straight, 24)
        assert len(kept) == 2 and coarse is False, (len(kept), coarse)
        curved = [
            {"mask_x": 0.5, "mask_y": 0.5 + 0.3 * math.sin(i / 10), "width": 0.2, "height": 0.2}
            for i in range(100)
        ]
        kept, coarse = simplify_path(curved, MASK_EXTRA_KEY_LIMIT)
        assert 2 < len(kept) <= MASK_EXTRA_KEY_LIMIT, len(kept)
        print(
            "   decimator:", len(kept), "keys for a curve,",
            "coarse" if coarse else "within tolerance",
        )
    print(
        "PASS: one extra mask follows its subject, its keys stay inside the block ceiling, "
        "the other block and the main mask are untouched, and every refusal names itself"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
