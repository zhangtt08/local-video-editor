"""引擎要先认自己拿到的那份 ffmpeg，再把「不认」说成一句能执行的话。

1.146 的装机复核量出来的那条路：`render.py` 在滤镜图越过 `GRAPH_SCRIPT_LIMIT` 时把图写成文件、
发 `-filter_complex_script`（Windows 的 `CreateProcess` 在 ~32 KB 上直接拒），而 FFmpeg 9 那一支
已经没有这个选项——当时的最后一句话是 FFmpeg 自己的 stderr
（`Unrecognized option 'filter_complex_script'.`），它既不说是谁，也不说怎么办。
这一版量三件事：

1. `parse_ffmpeg_help` 读的是 ffmpeg 自己的自述，两段样本各读对版本与选项在不在；
2. 随包那一份（`desktop/resources/bin/ffmpeg.exe`）实测认这个选项——这是本仓库默认路径的依据；
3. 真的走到那一步：把 `GRAPH_SCRIPT_LIMIT` 压到 1 让短图也走脚本形式，再让能力表说这份 ffmpeg
   不认，交付必须**失败且说清是谁、哪一份、回去的那两个名字**；把表恢复之后同一条请求照常出片。

第 3 条两头都跑：只断「会拒绝」而不断「不拒绝时也照常出片」的门禁，抓不出把守卫写反的错。
"""

import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut import jobs, render
from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime, ffmpeg_support, parse_ffmpeg_help
from agentcut.media import MediaService

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
PRESET = "h264-source-quality"

SIX = """ffmpeg version 6.1.1-essentials_build-www.gyan.dev Copyright (c) 2000-2023
  filter_complex_script  <string>   ..FV.TL. read graph script FROM filename
"""
NINE = """ffmpeg version 9.0.2-full_build-www.gyan.dev Copyright (c) 2000-2026
  filter_complex         <string>   ..FV.TL. filtergraph description
"""


def wait(client: TestClient, job_id: str) -> dict:
    deadline = time.time() + 240
    while time.time() < deadline:
        job = client.get(f"/v1/jobs/{job_id}").json()["job"]
        if job["status"] in ("succeeded", "failed", "cancelled"):
            return job
        time.sleep(0.3)
    raise AssertionError(f"任务 {job_id} 没有到点")


def main() -> None:
    said = parse_ffmpeg_help(SIX)
    assert said["version"] == "6.1.1-essentials_build-www.gyan.dev", said
    assert said["graph_script"] is True, said
    said = parse_ffmpeg_help(NINE)
    assert said["version"] == "9.0.2-full_build-www.gyan.dev", said
    assert said["graph_script"] is False, said
    # 探测那一步量出来的一件事：`ffmpeg -h full` 把版本横幅写在 **stderr**，选项表写在 stdout。
    # 只读 stdout 的版本就是「未知」——拒绝的话里说不出是哪一份 ffmpeg，等于没说；
    # 所以探测读的是两路合起来的自述。（也别再带 `-hide_banner`，那条把横幅整个关掉了。）
    assert parse_ffmpeg_help("  filter_complex_script  <string>  ..FV.TL.\n") == {
        "version": "未知",
        "graph_script": True,
    }, parse_ffmpeg_help("  filter_complex_script  <string>  ..FV.TL.\n")
    real = ffmpeg_support(FFMPEG)
    assert real["graph_script"] is True, real
    assert real["version"].startswith("6."), real
    # 一份 ffmpeg 的自述只量一次：探针挂在每次交付前面就是平白 0.2 s 一次。
    # 不数这一笔的话，「每次都重新跑」这种写法在这条门禁里是看不见的。
    calls: list[int] = []
    real_run = jobs.subprocess.run
    jobs.subprocess.run = lambda *args, **kwargs: (calls.append(1), real_run(*args, **kwargs))[1]
    try:
        again = ffmpeg_support(FFMPEG)
        again2 = ffmpeg_support(FFMPEG)
    finally:
        jobs.subprocess.run = real_run
    assert again == again2 == real, (again, again2)
    assert calls == [], calls
    print(
        f"   自述读得对（6.1.1 认／9.0.2 不认），随包真身实测：版本 {real['version'][:12]}、"
        "认 `-filter_complex_script`"
    )

    with tempfile.TemporaryDirectory(prefix="agentcut-ffg-") as scratch:
        folder = Path(scratch)
        media = MediaService(folder / "ffg.sqlite3", [folder], folder / "cache", FFMPEG, FFPROBE)
        exports = folder / "exports"
        runtime = JobRuntime(folder / "ffg-api.sqlite3", FFMPEG, exports, [exports, folder])
        runtime.ensure_worker()
        token = "ffmpeggraphcheck" + "e" * 50
        app = create_app(folder / "ffg-api.sqlite3", token, media=media, jobs=runtime)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            import subprocess

            subprocess.run(
                [
                    str(FFMPEG),
                    "-v",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=0x7F3F20:s=160x90:r=25:d=1",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-r",
                    "25",
                    str(folder / "one.mp4"),
                ],
                check=True,
                capture_output=True,
                timeout=600,
                creationflags=0x08000000,
            )
            probe = client.post("/v1/media/import", json={"path": str(folder / "one.mp4")}).json()
            created = client.post(
                "/v1/projects",
                json={
                    "request_id": "ffg-new",
                    "name": "长滤镜图",
                    "settings": {
                        "width": 160,
                        "height": 90,
                        "frame_rate": {"numerator": 25, "denominator": 1},
                    },
                },
            ).json()["project"]
            path = f"/v1/projects/{created['id']}"
            seed = client.post(
                path + "/edits",
                json={
                    "request_id": "ffg-seed",
                    "expected_revision": 0,
                    "commands": [
                        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                        {
                            "op": "asset.import",
                            "asset_id": "a0",
                            "label": "one",
                            "probe_id": probe["id"],
                            "verified": probe["verified"],
                        },
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "c0",
                                "asset_id": "a0",
                                "track_id": "v",
                                "position_ticks": 0,
                                "duration_ticks": T,
                            },
                        },
                    ],
                },
            )
            assert seed.status_code == 200, seed.text
            revision = seed.json()["project"]["revision"]

            saved_limit = render.GRAPH_SCRIPT_LIMIT
            saved_support = dict(jobs._FFMPEG_SUPPORT)
            try:
                # 把限度压到 1：任何一条滤镜图都改走脚本形式，于是这一条短链也走到那一步。
                render.GRAPH_SCRIPT_LIMIT = 1
                denied = {"version": "9.9.9-test", "graph_script": False, "path": str(FFMPEG)}
                jobs._FFMPEG_SUPPORT.clear()
                jobs._FFMPEG_SUPPORT[str(FFMPEG)] = denied
                answer = client.post(
                    path + "/renders",
                    json={
                        "request_id": "ffg-denied",
                        "expected_revision": revision,
                        "preset_id": PRESET,
                        "filename": "denied.mp4",
                    },
                )
                assert answer.status_code == 200, answer.text
                done = wait(client, answer.json()["job"]["id"])
                assert done["status"] == "failed", done
                message = done["message"]
                assert "FFMPEG_NO_GRAPH_SCRIPT" in message or "filter_complex_script" in message, (
                    message
                )
                assert "--ffmpeg" in message and "AGENTCUT_FFMPEG" in message, message
                assert "9.9.9-test" in message, message
                print(f"   拒绝那一步说的是人话：{message[:96]}…")

                jobs._FFMPEG_SUPPORT.clear()
                jobs._FFMPEG_SUPPORT[str(FFMPEG)] = {
                    "version": "6.1.1-test",
                    "graph_script": True,
                    "path": str(FFMPEG),
                }
                answer = client.post(
                    path + "/renders",
                    json={
                        "request_id": "ffg-allowed",
                        "expected_revision": revision,
                        "preset_id": PRESET,
                        "filename": "allowed.mp4",
                    },
                )
                done = wait(client, answer.json()["job"]["id"])
                assert done["status"] == "succeeded", done
                print(f"   不拒绝时照常出片：{Path(done['output_path']).name}")
            finally:
                render.GRAPH_SCRIPT_LIMIT = saved_limit
                jobs._FFMPEG_SUPPORT.clear()
                jobs._FFMPEG_SUPPORT.update(saved_support)


if __name__ == "__main__":
    main()
