"""1.295：帧级确定性自检——同一时刻重画必须逐字节相同，不同时刻不许画成同一张。

为什么单独一档：这一项目对「两端一致」量了很多（导出与预览逐像素对得上），但**同一端自己**
稳不稳没有门禁。渲染链上有派生缓存（帧、代理、缩略图共用一套缓存目录），缓存键只要少写一个
维度——少了 `sequence_id`、少了落格后的 tick——就会出现两种都过得了现有门禁的坏法：
* 换时刻仍回同一张图（键里根本没有时刻）；
* 先画谁影响画成什么（键里有状态泄漏）。

所以这一档判四件事，缺一不可：同 t 三趟（正序 / 倒序 / 错位）逐字节相同、引擎自检那条路与外面
这几趟读的是同一批图、**不同 t 必须各不相同**（只判前两条的话，一支永远返回同一张 PNG 的桩能
拿满分），以及两条拒绝各自按名字回。

跑法：空闲机器单跑 `uv run python tests/framestability_check.py`（要随包 ffmpeg 造夹具素材）。
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut.http_api import create_app  # noqa: E402
from agentcut.jobs import JobRuntime  # noqa: E402
from agentcut.media import MediaService  # noqa: E402

FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SECOND = 70_560_000
FRAME = SECOND // 30


def fail(message: str) -> None:
    raise SystemExit("FAIL: " + message)


def plate(folder: Path, source: str, name: str) -> Path:
    """一块**每帧都在变**的画面。纯色不行：两段纯色之间任何两帧都逐字节相同，
    那不是缓存键少了时刻，那是夹具在说谎——第一版就红在这里（五个时刻只画出四张图）。"""
    target = folder / name
    from subprocess import run

    done = [str(FFMPEG), "-v", "error", "-y", "-nostdin",
            "-f", "lavfi", "-i", f"{source}=s=320x180:r=30:d=4",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target)]
    if run(done, capture_output=True).returncode != 0:
        fail(f"造不出画面夹具 {name}")
    return target


def client_for(folder: Path):
    media = MediaService(folder / "f-db.sqlite3", [folder], folder / "f-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "f-api.sqlite3", FFMPEG, folder / "deliverables", [folder / "deliverables"]
    )
    token = "stability" + "f" * 52
    return create_app(folder / "f-api.sqlite3", token, media=media, jobs=runtime), token


def edit(client, pid, revision, request_id, commands):
    done = client.post(
        f"/v1/projects/{pid}/edits",
        json={"request_id": request_id, "expected_revision": revision, "commands": commands},
    )
    assert done.status_code == 200, done.text
    return done.json()["project"]


def frame(client, pid, at_ticks: int) -> str:
    got = client.get(f"/v1/projects/{pid}/frame", params={"at_ticks": at_ticks})
    assert got.status_code == 200, got.text
    landed = int(got.headers["X-Frame-Ticks"])
    assert landed == at_ticks, f"{at_ticks} 被落格成了 {landed}——这一档的判据就散了"
    return hashlib.sha256(got.content).hexdigest()


def seed(client, first: dict, second: dict) -> str:
    made = client.post(
        "/v1/projects",
        json={"request_id": "f-new", "name": "Stability",
              "settings": {"width": 320, "height": 180,
                           "frame_rate": {"numerator": 30, "denominator": 1}}},
    )
    assert made.status_code == 200, made.text
    pid = made.json()["project"]["id"]
    edit(client, pid, made.json()["project"]["revision"], "f-seed", [
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
        # 一条缩放曲线：让「同一段里的不同时刻」真的画出不同的东西，缓存键少一个维度就会露馅。
        {"op": "keyframe.set", "clip_id": "one",
         "keyframe": {"property": "scale", "at_ticks": 0, "value": 1.0}},
        {"op": "keyframe.set", "clip_id": "one",
         "keyframe": {"property": "scale", "at_ticks": 2 * SECOND, "value": 0.45}},
    ])
    return pid


# 五个落点：曲线正在走的两帧、接缝前后各一帧、第二段里一帧。全部整数帧，容不下「差不多」。
TIMES = (FRAME * 5, FRAME * 45, 2 * SECOND - FRAME, 2 * SECOND + FRAME, 3 * SECOND + FRAME * 10)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-stability-") as raw:
        folder = Path(raw)
        first, second = plate(folder, "testsrc", "one.mp4"), plate(folder, "testsrc2", "two.mp4")
        app, token = client_for(folder)
        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["frame_stability"] is True, caps["features"]

            red = client.post("/v1/media/import", json={"path": str(first)}).json()["verified"]
            blue = client.post("/v1/media/import", json={"path": str(second)}).json()["verified"]
            pid = seed(client, red, blue)
            revision = client.get(f"/v1/projects/{pid}").json()["revision"]

            # ① 正序两趟：同一时刻逐字节相同。
            forward = [frame(client, pid, at) for at in TIMES]
            again = [frame(client, pid, at) for at in TIMES]
            assert forward == again, [
                f"{at} 第二趟画成了别的" for at, a, b in zip(TIMES, forward, again) if a != b
            ]

            # ② 倒序一趟：先画谁不影响画成什么。
            backwards = {at: frame(client, pid, at) for at in reversed(TIMES)}
            assert [backwards[at] for at in TIMES] == forward, "换了顺序就画成别的"

            # ③ 不同时刻必须各不相同：缺这一条，前三条判的是一支常量桩。
            assert len(set(forward)) == len(forward), (
                f"{len(TIMES)} 个时刻只画出 {len(set(forward))} 张不同的图——"
                "缓存键少写了时刻这一维度，或者夹具根本没有变化"
            )
            print(f"   稳定：{len(TIMES)} 个时刻 × 正序/再一遍/倒序 三趟逐字节相同，"
                  f"且 {len(set(forward))} 张各不相同")

            # ④ 引擎自检那条路：一次调用回同样的结论，且报的哈希与外面这几张是同一批图。
            checked = client.post(f"/v1/projects/{pid}/frame-stability",
                                  json={"at_ticks": list(TIMES)})
            assert checked.status_code == 200, checked.text
            report = checked.json()
            assert report["stable"] is True, report
            assert report["mismatched"] == [], report
            assert report["passes"] == 3, report
            assert [row["at_ticks"] for row in report["frames"]] == list(TIMES), report
            assert [row["sha256"] for row in report["frames"]] == forward, (
                "引擎自检报的图与外面这几趟不是同一批——两条路读的不是同一条渲染链"
            )
            assert report["distinct"] == len(set(forward)), report
            assert report["revision"] == revision, "自检写进了库"
            print(f"   自检：POST /frame-stability 一次回 {report['passes']} 趟，"
                  f"stable=true、distinct={report['distinct']}，哈希与外面这几张逐条相同")

            # ⑤ 拒绝：没给落点与给太多，各自按名字回，且版本一步不涨。
            #    上限由引擎说（`stability.MAX_TIMES`），契约不拦——那条 422 体是 pydantic 的英文，
            #    人和 Agent 都读不到「分成几批问」这条出路。
            bare = client.post(f"/v1/projects/{pid}/frame-stability", json={"at_ticks": []})
            assert bare.status_code == 422, bare.text
            assert bare.json()["error"]["code"] == "STABILITY_NO_TIMES", bare.json()
            too_many = client.post(
                f"/v1/projects/{pid}/frame-stability",
                json={"at_ticks": [FRAME * n for n in range(1, 12)]},
            )
            assert too_many.status_code == 422, too_many.text
            assert too_many.json()["error"]["code"] == "STABILITY_TOO_MANY", too_many.json()
            frozen = client.get(f"/v1/projects/{pid}").json()["revision"]
            assert frozen == revision, "有一条拒绝写进了库"
            print("   拒绝：没交落点 / 落点太多，两条各按名字回，版本一步没涨")
        print("framestability_check: all green")


if __name__ == "__main__":
    main()
