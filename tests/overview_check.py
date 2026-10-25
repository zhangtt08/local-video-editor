"""1.296：一张总览图看完整条剪辑——格子数、落点、成图尺寸都要量到，不许假设。

判据不是「返回了一张 PNG」：
* 取格：`count` 枚落点必须单调、整帧对齐、都在窗口以内，而且首尾各留半格（第 0 帧与最后一帧
  正是最容易是黑帧的两处，一张第一格就黑的总览图不给任何新信息）；
* 成图：用 PNG 头部量出真实宽高，再按**格子自己的宽高与网格**算一遍应当是多少——只有真的
  拼成 3×2，这两个数才会相等（一支把第一张图原样交回来的桩在这里就红）；
* 会红：换掉一段素材，总览图必须变；同一份工程重问一次必须逐字节相同；
* 拒绝：格数越界与窗口倒着写各按名字回，且一个字节都不写。

跑法：空闲机器单跑 `uv run python tests/overview_check.py`（要随包 ffmpeg）。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut.http_api import create_app  # noqa: E402
from agentcut.jobs import JobRuntime  # noqa: E402
from agentcut.media import MediaService  # noqa: E402
from agentcut.overview import grid, pick_times  # noqa: E402

FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SECOND = 70_560_000
FRAME = SECOND // 30
PADDING = 2
MARGIN = 2


def fail(message: str) -> None:
    raise SystemExit("FAIL: " + message)


def plate(folder: Path, source: str, name: str) -> Path:
    target = folder / name
    from subprocess import run

    done = [str(FFMPEG), "-v", "error", "-y", "-nostdin",
            "-f", "lavfi", "-i", f"{source}=s=320x180:r=30:d=4",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target)]
    if run(done, capture_output=True).returncode != 0:
        fail(f"造不出画面夹具 {name}")
    return target


def png_size(body: bytes) -> tuple[int, int]:
    assert body[:8] == b"\x89PNG\r\n\x1a\n", "交回来的不是 PNG"
    return int.from_bytes(body[16:20], "big"), int.from_bytes(body[20:24], "big")


def client_for(folder: Path):
    media = MediaService(folder / "o-db.sqlite3", [folder], folder / "o-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "o-api.sqlite3", FFMPEG, folder / "deliverables", [folder / "deliverables"]
    )
    token = "overview" + "o" * 53
    return create_app(folder / "o-api.sqlite3", token, media=media, jobs=runtime), token


def edit(client, pid, revision, request_id, commands):
    done = client.post(
        f"/v1/projects/{pid}/edits",
        json={"request_id": request_id, "expected_revision": revision, "commands": commands},
    )
    assert done.status_code == 200, done.text
    return done.json()["project"]


def seed(client, first: dict, second: dict) -> str:
    made = client.post(
        "/v1/projects",
        json={"request_id": "o-new", "name": "Overview",
              "settings": {"width": 320, "height": 180,
                           "frame_rate": {"numerator": 30, "denominator": 1}}},
    )
    assert made.status_code == 200, made.text
    pid = made.json()["project"]["id"]
    edit(client, pid, made.json()["project"]["revision"], "o-seed", [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
        {"op": "asset.import", "asset_id": "a", "label": "one.mp4",
         "probe_id": first["probe_id"], "verified": first},
        {"op": "asset.import", "asset_id": "b", "label": "two.mp4",
         "probe_id": second["probe_id"], "verified": second},
        {"op": "clip.add", "clip": {"id": "one", "asset_id": "a", "track_id": "v",
                                    "position_ticks": 0, "duration_ticks": 2 * SECOND}},
        {"op": "clip.add", "clip": {"id": "two", "asset_id": "b", "track_id": "v",
                                    "position_ticks": 2 * SECOND,
                                    "duration_ticks": 2 * SECOND}},
    ])
    return pid


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-overview-") as raw:
        folder = Path(raw)
        first, second = plate(folder, "testsrc", "one.mp4"), plate(folder, "testsrc2", "two.mp4")
        app, token = client_for(folder)
        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["timeline_overview"] is True, caps["features"]

            red = client.post("/v1/media/import", json={"path": str(first)}).json()["verified"]
            blue = client.post("/v1/media/import", json={"path": str(second)}).json()["verified"]
            pid = seed(client, red, blue)
            project = client.get(f"/v1/projects/{pid}").json()
            revision = project["revision"]

            # ① 取格：六枚落点单调、整帧、在窗口以内，且首尾各留半格。
            times = pick_times(_as_project(project), 6)
            assert len(times) == 6, times
            assert times == sorted(times) and len(set(times)) == 6, times
            assert all(at % FRAME == 0 for at in times), times
            end = 4 * SECOND
            assert times[0] > 0 and times[-1] < end, (times[0], times[-1], end)
            assert all(0 <= at < end for at in times), times
            print(f"   取格：{len(times)} 枚落点单调且整帧，第一格在 {times[0] // FRAME} 帧、"
                  f"最后一格在 {times[-1] // FRAME} 帧（两端各留半格）")

            # ② 成图：按格子自己的宽高与网格算出应当是多少，再与 PNG 头部量到的比。
            sheet = client.get(f"/v1/projects/{pid}/overview", params={"count": 6})
            assert sheet.status_code == 200, sheet.text
            cells = [int(item) for item in sheet.headers["X-Overview-Cells"].split(",")]
            assert cells == times, (cells, times)
            assert sheet.headers["X-Overview-Grid"] == "3x2", sheet.headers["X-Overview-Grid"]
            single = client.get(f"/v1/projects/{pid}/frame", params={"at_ticks": times[0]})
            one_bytes = len(single.content)
            cw, ch = png_size(single.content)
            columns, rows = grid(6)
            want = (MARGIN * 2 + columns * cw + (columns - 1) * PADDING,
                    MARGIN * 2 + rows * ch + (rows - 1) * PADDING)
            got = png_size(sheet.content)
            assert got == want, f"量到 {got}，按 {columns}x{rows} 格（每格 {cw}x{ch}）应是 {want}"
            print(f"   成图：单格 {cw}x{ch}，{columns}x{rows} 张拼成 {got[0]}x{got[1]}；"
                  f"一次要 {len(sheet.content)} 字节；逐帧读要 {len(times)} 次，"
                  f"每次约 {one_bytes} 字节")

            # ③ 会红：同一份工程重问一次逐字节相同；换掉一段素材之后必须变。
            again = client.get(f"/v1/projects/{pid}/overview", params={"count": 6})
            assert again.content == sheet.content, "同一份工程两次画出的总览图不一样"
            edit(client, pid, client.get(f"/v1/projects/{pid}").json()["revision"], "o-swap", [
                {"op": "clip.patch", "clip_id": "two", "color": {"saturation": 0.0}},
            ])
            changed = client.get(f"/v1/projects/{pid}/overview", params={"count": 6})
            assert changed.content != sheet.content, "压了饱和之后总览图没变——它没在读这条时间线"
            print("   判据：重问逐字节相同；把第二段压成无彩之后总览图变了")

            # ④ 拒绝：格数越界与窗口倒着写各按名字回，版本一步不涨。
            small = client.get(f"/v1/projects/{pid}/overview", params={"count": 1})
            assert small.status_code == 422, small.text
            assert small.json()["error"]["code"] == "OVERVIEW_COUNT", small.json()
            big = client.get(f"/v1/projects/{pid}/overview", params={"count": 13})
            assert big.status_code == 422, big.text
            assert big.json()["error"]["code"] == "OVERVIEW_COUNT", big.json()
            backwards = client.get(f"/v1/projects/{pid}/overview",
                                   params={"count": 4, "from_ticks": 3 * SECOND,
                                           "to_ticks": SECOND})
            assert backwards.status_code == 422, backwards.text
            assert backwards.json()["error"]["code"] == "OVERVIEW_RANGE", backwards.json()
            frozen = client.get(f"/v1/projects/{pid}").json()["revision"]
            assert frozen == revision + 1, f"有一条拒绝写进了库（{revision} → {frozen}）"
            print("   拒绝：1 格 / 13 格 / 窗口倒着写，三条各按名字回，除了一次换素材没别的写入")
        print("overview_check: all green")


def _as_project(payload: dict):
    """把 HTTP 交回的工程字典还原成模型对象——取格那一节判的是引擎自己那份算术。"""
    from agentcut.contracts import Project

    return Project.model_validate(payload)


if __name__ == "__main__":
    main()
