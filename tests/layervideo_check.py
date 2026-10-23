"""1.274: the second picture can be moving footage, not just a still.

The base is a blue still; the layer is a two-second video that is red for the first second and
green for the second, scaled to the centre half. Two exported frames decide the whole feature:
0.4 s must be red in the centre, 1.4 s green, while a corner stays the blue base. A still layer
would give the same colour at both times, so the pair is not satisfiable by a frozen frame.

The write path is measured too: a one-second video layered over a two-second clip has no source
left for the tail, is refused by name (`LAYER_ASSET_UNAVAILABLE`, reason `too_short`) and writes
nothing. The preview manifest hands the interface `kind: "video"` with `motion: "paused"` — the
monitor draws it while paused or stepping, not during playback (the 1.195 measurement: a second
decoder halved the frame rate).
"""

import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
PRESET = "h264-1080p"
FRAME_W, FRAME_H = 1920, 1080
BASE = (0, 0, 200)
RED, GREEN = (220, 20, 20), (20, 200, 20)


def run(args, timeout=900):
    return subprocess.run(
        [str(a) for a in args], capture_output=True, check=True, timeout=timeout,
        creationflags=0x08000000,
    )


def still(folder: Path, name: str, colour: tuple[int, int, int]) -> Path:
    target = folder / name
    run([
        FFMPEG, "-v", "error", "-y", "-f", "lavfi",
        "-i", f"color=c=0x{colour[0]:02x}{colour[1]:02x}{colour[2]:02x}:s=320x180:r=30:d=1",
        "-frames:v", "1", str(target),
    ])
    return target


def two_colour_video(folder: Path, name: str, seconds: float) -> Path:
    target = folder / name
    first = seconds / 2
    second = seconds - first
    red = f"0x{RED[0]:02x}{RED[1]:02x}{RED[2]:02x}"
    green = f"0x{GREEN[0]:02x}{GREEN[1]:02x}{GREEN[2]:02x}"
    run([
        FFMPEG, "-v", "error", "-y",
        "-f", "lavfi", "-i", f"color=c={red}:s=320x180:r=30:d={first}",
        "-f", "lavfi", "-i", f"color=c={green}:s=320x180:r=30:d={second}",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p",
        str(target),
    ])
    return target


def rgb_at(path: Path, at: float, fx: float, fy: float) -> tuple[int, int, int]:
    raw = run([
        FFMPEG, "-v", "error", "-ss", f"{at:.3f}", "-i", str(path), "-frames:v", "1",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]).stdout
    assert len(raw) >= FRAME_W * FRAME_H * 3, f"{path.name} 解出来 {len(raw)} 字节"
    row = raw[int(FRAME_H * fy) * FRAME_W * 3 : (int(FRAME_H * fy) + 1) * FRAME_W * 3]
    offset = int(FRAME_W * fx) * 3
    return row[offset], row[offset + 1], row[offset + 2]


def near(value: tuple[int, int, int], want: tuple[int, int, int], tolerance: int = 36) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(value, want))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-layervideo-") as scratch:
        folder = Path(scratch)
        media = MediaService(
            folder / "lv-db.sqlite3", [folder], folder / "lv-cache", FFMPEG, FFPROBE
        )
        exports = folder / "exports"
        runtime = JobRuntime(folder / "lv-api.sqlite3", FFMPEG, exports, [exports, folder])
        runtime.ensure_worker()
        token = "layervideo" + "e" * 50
        app = create_app(folder / "lv-api.sqlite3", token, media=media, jobs=runtime)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            base = still(folder, "base.png", BASE)
            moving = two_colour_video(folder, "moving.mp4", 2.0)
            short = two_colour_video(folder, "short.mp4", 1.0)
            base_probe = client.post("/v1/media/import", json={"path": str(base)}).json()
            moving_probe = client.post("/v1/media/import", json={"path": str(moving)}).json()
            short_probe = client.post("/v1/media/import", json={"path": str(short)}).json()

            project = client.post(
                "/v1/projects", json={"request_id": "new", "name": "layervideo"}
            ).json()["project"]
            path = f"/v1/projects/{project['id']}"
            seeded = client.post(
                path + "/edits",
                json={
                    "request_id": "seed",
                    "expected_revision": 0,
                    "commands": [
                        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                        {
                            "op": "asset.import", "asset_id": "base", "label": "base",
                            "probe_id": base_probe["id"], "verified": base_probe["verified"],
                        },
                        {
                            "op": "asset.import", "asset_id": "moving", "label": "moving",
                            "probe_id": moving_probe["id"], "verified": moving_probe["verified"],
                        },
                        {
                            "op": "asset.import", "asset_id": "short", "label": "short",
                            "probe_id": short_probe["id"], "verified": short_probe["verified"],
                        },
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "c", "asset_id": "base", "track_id": "v",
                                "position_ticks": 0, "duration_ticks": 2 * T,
                            },
                        },
                    ],
                },
            )
            assert seeded.status_code == 200, seeded.text
            layer = {
                "kind": "layer", "asset_id": "moving", "mode": "normal", "mix": 1.0,
                "offset_x": 0.0, "offset_y": 0.0, "scale": 0.5, "rotation": 0.0,
                "enabled": True,
            }
            placed = client.post(
                path + "/edits",
                json={
                    "request_id": "layer", "expected_revision": 1,
                    "commands": [{"op": "clip.grade", "clip_id": "c", "grade": [layer]}],
                },
            )
            assert placed.status_code == 200, placed.text
            document = placed.json()["project"]

            manifest = client.post(
                "/v1/preview-manifest", json=document
            ).json()
            row = manifest["clips"]["c"]["layer"][0]
            assert row["paintable"] is True, row
            assert row["kind"] == "video", row
            assert row["motion"] == "paused", row
            print("   manifest: video layer is paintable and only drawn while paused")

            job = client.post(
                path + "/renders",
                json={
                    "request_id": "lv-render", "expected_revision": 2,
                    "preset_id": PRESET, "filename": "lv.mp4", "fit": "stretch",
                },
            ).json()["job"]
            done = job
            for _ in range(900):
                done = client.get(f"/v1/jobs/{job['id']}").json()["job"]
                if done["status"] in {"succeeded", "failed", "cancelled"}:
                    break
            assert done["status"] == "succeeded", done
            output = Path(done["output_path"])
            early = rgb_at(output, 0.4, 0.5, 0.5)
            late = rgb_at(output, 1.4, 0.5, 0.5)
            corner = rgb_at(output, 1.4, 0.1, 0.1)
            assert near(early, RED), f"0.4 秒的中心不是视频第一段：{early}"
            assert near(late, GREEN), f"1.4 秒的中心不是视频第二段：{late}"
            assert near(corner, BASE), f"层外那一角不该被视频盖住：{corner}"
            print(f"   export: centre {early} -> {late}, corner {corner}")

            # A one-second video cannot cover a two-second clip: the write is refused by name.
            try:
                refused = client.post(
                    path + "/edits",
                    json={
                        "request_id": "too-short", "expected_revision": 2,
                        "commands": [{
                            "op": "clip.grade", "clip_id": "c",
                            "grade": [{**layer, "asset_id": "short"}],
                        }],
                    },
                )
                outcome = (refused.status_code, refused.json())
            except Exception as error:  # the refusal must be a clean 422, not a crash
                outcome = f"raised {type(error).__name__}"
            assert isinstance(outcome, tuple) and outcome[0] == 422, f"短素材必须被拒：{outcome}"
            body = outcome[1]["error"]
            assert body.get("code") == "LAYER_ASSET_UNAVAILABLE", body
            assert body.get("details", {}).get("reason") == "too_short", body
            assert client.get(path).json()["revision"] == 2, "被拒的编辑不许涨版本"
            print("   short video: 422 LAYER_ASSET_UNAVAILABLE / too_short, nothing written")

    print(
        "PASS: a video layer changes with time in the exported file, the corner keeps the base, "
        "the manifest says video/paused, and a too-short source is refused by name"
    )


if __name__ == "__main__":
    main()
