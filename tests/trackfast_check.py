"""Fast in-plane rotation: the angle is predicted from the last turn, and one full turn is a wall.

1.271 read a turn by searching ±6° around the last angle. That is enough for a slow pan, but a
subject turning 10° or more per frame walks out of the window and the run stops after a couple of
frames. This check pins the three facts of the fix on a synthetic bar + dot whose angle is known
from the filter that drew it:

- a steady 13.7°/frame turn tracks every frame within 2° (the old code stopped after 3);
- a turn that reverses direction (15°/frame, then −15°/frame) is caught again after the reversal;
- a turn past one full circle stops at the mask contract's ±360° instead of writing an angle the
  reducer would refuse, and both receipts name the frame where that happened.

The last one is not a defect swept under the rug: `mask_rotation` is defined in [-360, 360], so no
single tracked path can hold more than one turn. Splitting the shot after that turn is the exit the
interface says.
"""

import math
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agentcut.contracts import TIMEBASE as T  # noqa: E402
from agentcut.contracts import FrameRate  # noqa: E402
from agentcut.http_api import create_app  # noqa: E402
from agentcut.media import MediaService  # noqa: E402
from agentcut.tracking import analyse_window, follow_window  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
WIDTH, HEIGHT, FPS = 320, 240, 30
SECONDS = 2.0
FRAME = T // FPS
FRAMES = 20
BOX = (0.5, 0.5, 0.26, 0.35)


def build_source(target: Path, deg_per_frame: float, reverse: bool = False) -> None:
    if reverse:
        half = 0.5 * FPS * deg_per_frame
        turn = math.radians(deg_per_frame) * FPS
        expr = f"if(lt(t\\,0.5)\\,{turn}*t\\,{math.radians(half)}-{turn}*(t-0.5))"
    else:
        expr = f"{math.radians(deg_per_frame) * FPS}*t"
    subprocess.run(
        [
            str(FFMPEG), "-y", "-v", "error",
            "-f", "lavfi", "-i", f"color=c=0x202020:s={WIDTH}x{HEIGHT}:d={SECONDS}:r={FPS}",
            "-f", "lavfi", "-i", f"color=c=black@0:s=160x160:d={SECONDS}:r={FPS}",
            "-filter_complex",
            "[1:v]format=rgba,"
            "drawbox=x=40:y=76:w=80:h=8:color=white@1:t=fill,"
            "drawbox=x=100:y=56:w=12:h=12:color=white@1:t=fill,"
            f"rotate={expr}:fillcolor=black@0[p];"
            "[0:v][p]overlay=80:40:shortest=1",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-pix_fmt", "yuv420p", str(target),
        ],
        check=True,
        capture_output=True,
        timeout=300,
    )


def follow(folder: Path, rate_deg: float, reverse: bool = False) -> dict:
    source = folder / f"turn-{rate_deg}{'-back' if reverse else ''}.mp4"
    build_source(source, rate_deg, reverse)
    rate = FrameRate(numerator=FPS, denominator=1)
    width, decoded = analyse_window(FFMPEG, source, WIDTH, HEIGHT, rate, 0, FRAME, FRAMES)
    return follow_window(
        decoded, width, BOX, 10, rate, FRAME,
        scale=False, max_gap=4, reacquire=True, rotate=True,
    )


def unit_suite(folder: Path) -> None:
    fast = follow(folder, 13.7)
    angles = [point["rotation"] for point in fast["points"]]
    assert len(angles) == FRAMES, f"13.7°/帧 应每帧都有点：{len(angles)}"
    worst = max(abs(value - 13.7 * index) for index, value in enumerate(angles))
    assert worst < 2.0, f"13.7°/帧 读歪了 {worst} 度：{angles}"
    assert fast["gaps"] == [] and fast["lost_at_ticks"] is None, fast
    assert fast["angle_limit_at_ticks"] is None
    print(f"   13.7°/frame: {len(angles)} frames, worst {worst:.2f}°")

    back = follow(folder, 15, reverse=True)
    values = [point["rotation"] for point in back["points"]]
    assert len(values) == FRAMES, len(values)
    expected = [15 * i if i <= 15 else 225 - 15 * (i - 15) for i in range(FRAMES)]
    worst = max(abs(value - want) for value, want in zip(values, expected))
    assert worst < 2.0, f"转向那次没跟上：{values}"
    assert back["angle_limit_at_ticks"] is None
    print(f"   15°/frame reversed: worst {worst:.2f}° across the turn-around")

    static = follow(folder, 0)
    assert [point["rotation"] for point in static["points"]] == [0.0] * FRAMES
    assert static["angle_limit_at_ticks"] is None
    print("   static: every angle stayed 0")

    wall = follow(folder, 25)
    turns = [point["rotation"] for point in wall["points"]]
    assert wall["lost_at_ticks"] is not None, "转过一圈之后不该假装还跟得上"
    assert wall["angle_limit_at_ticks"] == wall["lost_at_ticks"], wall
    assert wall["angle_limit_at_ticks"] == 15 * FRAME, wall["angle_limit_at_ticks"]
    assert len(turns) == 15 and turns[-1] == 350.0, turns
    assert max(turns) <= 360.0, turns
    print(f"   25°/frame: stopped at {turns[-1]}° after {len(turns)} frames, limit named")


def mask_payload() -> dict:
    return {
        "shape": "rectangle", "center_x": 0.5, "center_y": 0.5,
        "width": 0.26, "height": 0.35, "rotation": 0.0,
    }


def http_suite(folder: Path) -> None:
    media = MediaService(
        folder / "db.sqlite3", [folder / "media"], folder / "cache", FFMPEG, FFPROBE
    )
    source = folder / "media" / "turn-25.mp4"
    source.parent.mkdir(exist_ok=True)
    build_source(source, 25)
    token = "trackfast" + "f" * 50
    app = create_app(folder / "api.sqlite3", token, media=media)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        probe = client.post("/v1/media/import", json={"path": str(source)}).json()
        project = client.post(
            "/v1/projects", json={"request_id": "new", "name": "trackfast"}
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
                        "op": "asset.import", "asset_id": "a", "label": "turn",
                        "probe_id": probe["id"], "verified": probe["verified"],
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "c", "asset_id": "a", "track_id": "v",
                            "position_ticks": 0, "duration_ticks": int(SECONDS * T),
                            "mask": mask_payload(),
                        },
                    },
                ],
            },
        )
        assert seeded.status_code == 200, seeded.text
        dry = client.post(
            path + "/mask-track",
            json={
                "request_id": "fast-plan", "expected_revision": 1,
                "targets": [{
                    "clip_id": "c", "frames": FRAMES,
                    "estimate_scale": False, "estimate_rotation": True,
                }],
                "dry_run": True,
            },
        )
        assert dry.status_code == 200, dry.text
        receipt = dry.json()["tracking"]["targets"][0]
        assert receipt["angle_limit_at_ticks"] == 15 * FRAME, receipt
        assert receipt["lost_at_ticks"] == receipt["angle_limit_at_ticks"], receipt
        assert receipt["tracked_frames"] == 15, receipt
        assert max(point["rotation"] for point in receipt["points"]) <= 360.0
        assert client.get(path).json()["revision"] == 1, "a dry run must not write"

        applied = client.post(
            path + "/mask-track",
            json={
                "request_id": "fast-apply", "expected_revision": 1,
                "targets": [{
                    "clip_id": "c", "frames": FRAMES,
                    "estimate_scale": False, "estimate_rotation": True,
                }],
            },
        )
        assert applied.status_code == 200, applied.text
        clip = applied.json()["project"]["clips"]["c"]
        keys = [key for key in clip["keyframes"] if key["property"] == "mask_rotation"]
        assert keys and max(key["value"] for key in keys) == 350.0, keys[-3:]
        assert min(key["value"] for key in keys) >= -360.0, "写出来的角度越界"
        assert applied.json()["tracking"]["targets"][0]["angle_limit_at_ticks"] == 15 * FRAME
        print(f"   http: {len(keys)} mask_rotation keys, top {keys[-1]['value']}°, limit named")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    with tempfile.TemporaryDirectory(prefix="trackfast-check-") as name:
        folder = Path(name)
        unit_suite(folder)
        http_suite(folder)
    print(
        "PASS: a fast turn is predicted and followed, a reversal is picked up again, and a turn "
        "past ±360° stops at the contract limit with both receipts naming that frame"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
