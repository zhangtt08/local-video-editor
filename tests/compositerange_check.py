"""第二路画面输入 × 标记区间 × 交付帧率：两条支的帧号对不对齐，只有位置签名能回答。

cut 那条路上，调色那一路带 `trim=duration=`，原图那一路不带；两者靠 `blend` 逐帧配对。
若区间或帧率让两条支的时基错开一位，交回来的就是「把红色那一秒叠进绿色这一秒」——
灰度量不出来（三秒都是同一个亮度级），所以源换成**红／绿／蓝各一秒**的位置签名。

三件事同时按下：`range=marks`（区间写在工程设置上，用 POST 改工程，PUT 是不存在的动词）、
`output_frame_rate=25/1`、`clip.color.grade` 里那条 `composite`。

仪表的两笔账（都是这轮量出来的）：① 绿色那一秒不用饱和绿，用 `0x40A040`——饱和绿在 4:2:0
往返里被色度 ringing 顶到 255，180 与 254 读出来是同一个数；② 分类不能用「一个通道 >150、
另两个 <100」这种阈值，`screen` 本来就会把暗的两个通道抬起来（mix=1 那一份实测 134:244:133），
所以按**支配度**判：绿要高出另两个通道 60 级以上，红／蓝同理，否则原样报数。
"""

import subprocess
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SRC_W, SRC_H = 320, 180
PRESET = "h264-1080p"
DOMINANCE = 60


def run(args, timeout=900):
    return subprocess.run(
        [str(a) for a in args],
        capture_output=True,
        check=True,
        timeout=timeout,
        creationflags=0x08000000,
    ).stdout


def source(folder: Path) -> Path:
    target = folder / "rgb-3s.mp4"
    run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0xB40000:s=320x180:r=30:d=1",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x40A040:s=320x180:r=30:d=1",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x0000B4:s=320x180:r=30:d=1",
            "-filter_complex",
            "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv444p",
            "-r",
            "30",
            str(target),
        ]
    )
    return target


def pixels(path: Path) -> list[tuple[int, int, int]]:
    """每一帧一个三元组：`scale=1:1` 把整幅压到一像素，一帧三个字节。"""
    raw = run(
        [
            FFMPEG,
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            "scale=1:1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ]
    )
    return [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw) - 2, 3)]


def name_of(pixel: tuple[int, int, int]) -> str:
    red, green, blue = pixel
    if green - max(red, blue) >= DOMINANCE:
        return "绿"
    if red - max(green, blue) >= DOMINANCE:
        return "红"
    if blue - max(red, green) >= DOMINANCE:
        return "蓝"
    return f"其它{red}:{green}:{blue}"


def wait(client: TestClient, job_id: str) -> dict:
    deadline = time.time() + 600
    while time.time() < deadline:
        job = client.get(f"/v1/jobs/{job_id}").json()["job"]
        if job["status"] in ("succeeded", "failed", "cancelled"):
            return job
        time.sleep(0.4)
    raise AssertionError(f"任务 {job_id} 没有到点")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-cxr-") as scratch:
        folder = Path(scratch)
        media = MediaService(
            folder / "cxr-db.sqlite3", [folder], folder / "cxr-cache", FFMPEG, FFPROBE
        )
        exports = folder / "exports"
        runtime = JobRuntime(folder / "cxr-api.sqlite3", FFMPEG, exports, [exports, folder])
        runtime.ensure_worker()
        token = "cxrcheck" + "e" * 56
        app = create_app(folder / "cxr-api.sqlite3", token, media=media, jobs=runtime)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            clip = source(folder)
            probe = client.post("/v1/media/import", json={"path": str(clip)}).json()
            settings = {
                "width": SRC_W,
                "height": SRC_H,
                "frame_rate": {"numerator": 30, "denominator": 1},
            }
            made = client.post(
                "/v1/projects",
                json={"request_id": "cxr-new", "name": "位置签名", "settings": settings},
            ).json()["project"]
            path = f"/v1/projects/{made['id']}"
            seed = client.post(
                path + "/edits",
                json={
                    "request_id": "cxr-seed",
                    "expected_revision": 0,
                    "commands": [
                        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                        {
                            "op": "asset.import",
                            "asset_id": "a",
                            "label": "a",
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
                                "duration_ticks": 3 * T,
                            },
                        },
                    ],
                },
            )
            assert seed.status_code == 200, seed.text
            revision = seed.json()["project"]["revision"]
            marked = client.post(
                path,
                json={
                    "request_id": "cxr-marks",
                    "expected_revision": revision,
                    "settings": {**settings, "in_ticks": T, "out_ticks": 2 * T},
                },
            )
            assert marked.status_code == 200, marked.text
            revision = marked.json()["project"]["revision"]

            def ship(tag: str, grade: list, exposure: float) -> list[tuple[int, int, int]]:
                nonlocal revision
                answer = client.post(
                    path + "/edits",
                    json={
                        "request_id": f"cxr-{tag}-edit",
                        "expected_revision": revision,
                        "commands": [
                            {
                                "op": "clip.color",
                                "clip_id": "c",
                                "color": {"exposure": exposure, "grade": grade},
                            }
                        ],
                    },
                )
                assert answer.status_code == 200, answer.text
                revision = answer.json()["project"]["revision"]
                job = client.post(
                    path + "/renders",
                    json={
                        "request_id": f"cxr-{tag}-job",
                        "expected_revision": revision,
                        "preset_id": PRESET,
                        "range": "marks",
                        "output_frame_rate": {"numerator": 25, "denominator": 1},
                        "filename": f"{tag}.mp4",
                    },
                )
                assert job.status_code == 200, job.text
                done = wait(client, job.json()["job"]["id"])
                assert done["status"] == "succeeded", done
                said = pixels(Path(done["output_path"]))
                assert 24 <= len(said) <= 26, (tag, len(said))
                assert {name_of(p) for p in said} == {"绿"}, (tag, [name_of(p) for p in said][:6])
                return said

            def green(frame: tuple[int, int, int]) -> int:
                return frame[1]

            graded = ship("graded", [], 0.5)
            ungraded = ship("ungraded", [], 0.0)
            at_zero = ship("mix0", [{"kind": "composite", "mode": "screen", "mix": 0.0}], 0.5)
            at_one = ship("mix1", [{"kind": "composite", "mode": "screen", "mix": 1.0}], 0.5)
            at_half = ship("mixhalf", [{"kind": "composite", "mode": "screen", "mix": 0.5}], 0.5)
            middle = len(graded) // 2
            assert green(graded[middle]) - green(ungraded[middle]) > 20, (
                graded[middle],
                ungraded[middle],
            )
            # mix=0 逐值回到**这条链的输入**（不调曝光那一份），mix=1 比调完的更亮，0.5 落在中间：
            # 三条一起才说明配对的是同一帧，而不是隔壁那一秒。
            assert abs(green(at_zero[middle]) - green(ungraded[middle])) <= 4, (
                at_zero[middle],
                ungraded[middle],
            )
            assert green(at_one[middle]) > green(graded[middle]) + 8, (
                at_one[middle],
                graded[middle],
            )
            lo, hi = green(at_zero[middle]), green(at_one[middle])
            assert lo + 8 < green(at_half[middle]) < hi - 8, (at_half[middle], lo, hi)
            print(
                f"   标记 1..2 秒按 25 交：{len(graded)} 帧全是绿；"
                f"不调 {green(ungraded[middle])}／调完 {green(graded[middle])}／"
                f"mix=0 {green(at_zero[middle])}／0.5 {green(at_half[middle])}／"
                f"1 {green(at_one[middle])}：两条支配的是同一帧"
            )


if __name__ == "__main__":
    main()
