"""标记区间 × 交付帧率：区间裁剪的帧号必须由**交付流**那把尺量。

1.138 让「交付的帧率」可以不同于「时间线自己的帧率」。`render.py` 里那句切区间的注释早就写着
「流已经被 `fps=` 归一过了」，可除数用的是 `settings.frame_ticks`（时间线的一帧）。两把尺一直是
同一个数的时候这不会露出来；1.138 之后它露了——实测（30 的线标 1..2 秒、按 25 交）落盘的是
20 帧绿 + 5 帧蓝：**入点前少了一截，出点后多露了一截**，而 `plan.range.seconds` 还写着 1.0。
按 23.976 交是 18 帧绿 + 6 帧蓝。

这里断的是内容，不是帧数——帧数对不对回答不了「切的是哪一段」：

1. 每秒一个纯色的三秒源，标 0..1 秒与 1..2 秒两个窗口，分别按 30（跟时间线）、25、23.976 交，
   **逐帧读 RGB**：窗口里一帧都不许多带别的颜色（红/绿/蓝就是源自己的三个 1 秒）。
2. 帧号是交付流的号：30 的线交 30 时还是 `start_frame=30:end_frame=60`（与 1.138 之前逐字相同，
   这条改动不影响没换率的人），交 25 是 25..50，交 23.976 是 24..48（两头都向上取整：
   第一帧不早于入点，最后一帧的起点仍早于出点）。
3. 声音那一头本来就用秒（`atrim=start=1.000000:end=2.000000`），三个率下同一条——图与声
   不必共用一把帧尺，但必须说同一个窗口。
"""

import json
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SRC_W, SRC_H = 320, 180
PRESET = "h264-1080p"
FRAME = T // 30
SECOND = T


def run(args, timeout=900):
    return subprocess.run(
        [str(a) for a in args],
        capture_output=True,
        check=True,
        timeout=timeout,
        creationflags=0x08000000,
    )


def source(folder: Path) -> Path:
    """三秒、每秒一个纯色：0..1 红、1..2 绿、2..3 蓝。切错了就会掺进别的颜色。"""
    target = folder / "rgb-3s.mp4"
    parts: list[str] = []
    for colour in ("red", "green", "blue"):
        parts += ["-f", "lavfi", "-i", f"color=c={colour}:s={SRC_W}x{SRC_H}:r=30:d=1"]
    run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            *parts,
            "-filter_complex",
            "concat=3",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            str(target),
        ]
    )
    return target


def frame_colours(path: Path) -> list[str]:
    """每一帧缩成 1x1 读出 RGB——只有内容能回答「切到了哪一秒」。"""
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
    ).stdout
    names = []
    for index in range(0, len(raw) - 2, 3):
        red, green, blue = raw[index : index + 3]
        names.append(
            "红"
            if red > 150
            else "蓝"
            if blue > 150
            else "绿"
            if green > 90
            else f"其它{red}:{green}:{blue}"
        )
    return names


def video_stats(path: Path) -> dict:
    payload = json.loads(
        run(
            [
                FFPROBE,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=avg_frame_rate,nb_frames,duration",
                "-of",
                "json",
                str(path),
            ]
        ).stdout.decode()
    )
    return payload["streams"][0]


def plan_window(argv: list[str]) -> str:
    joined = ";".join(argv)
    for part in joined.split(";"):
        if "trim=start_frame" in part:
            return part[part.index("trim=start_frame") :].split(",")[0]
    raise AssertionError(f"计划里没有那一刀：{joined[:200]}")


def _frames(window: str) -> tuple[int, int]:
    """`trim=start_frame=A:end_frame=B` → (A, B)。"""
    body = window.split("=", 1)[1]
    items = dict(pair.split("=") for pair in body.split(":"))
    return int(items["start_frame"]), int(items["end_frame"])


def wait(client: TestClient, job_id: str) -> dict:
    deadline = time.time() + 600
    while time.time() < deadline:
        job = client.get(f"/v1/jobs/{job_id}").json()["job"]
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.4)
    raise AssertionError(f"任务 {job_id} 没有到点")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-dr-") as scratch:
        folder = Path(scratch)
        media = MediaService(
            folder / "dr-db.sqlite3", [folder], folder / "dr-cache", FFMPEG, FFPROBE
        )
        runtime = JobRuntime(
            folder / "dr-api.sqlite3", FFMPEG, folder / "exports", [folder / "exports", folder]
        )
        runtime.ensure_worker()
        token = "drcheck" + "e" * 57
        app = create_app(folder / "dr-api.sqlite3", token, media=media, jobs=runtime)
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
            project = client.post(
                "/v1/projects",
                json={"request_id": "dr-new", "name": "区间与率", "settings": settings},
            ).json()["project"]
            path = f"/v1/projects/{project['id']}"
            seeded = client.post(
                path + "/edits",
                json={
                    "request_id": "dr-seed",
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
                                "duration_ticks": 3 * SECOND,
                            },
                        },
                    ],
                },
            )
            assert seeded.status_code == 200, seeded.text
            revision = seeded.json()["project"]["revision"]

            rates = [
                None,
                {"numerator": 25, "denominator": 1},
                {"numerator": 24000, "denominator": 1001},
            ]
            expect_window = {
                "30/1": "trim=start_frame=30:end_frame=60",
                "25/1": "trim=start_frame=25:end_frame=50",
                "24000/1001": "trim=start_frame=24:end_frame=48",
            }
            expect_first = {
                "30/1": "trim=start_frame=0:end_frame=30",
                "25/1": "trim=start_frame=0:end_frame=25",
                "24000/1001": "trim=start_frame=0:end_frame=24",
            }

            def marks(in_ticks: int, out_ticks: int, request_id: str) -> None:
                nonlocal revision
                answer = client.post(
                    path,
                    json={
                        "request_id": request_id,
                        "expected_revision": revision,
                        "settings": {**settings, "in_ticks": in_ticks, "out_ticks": out_ticks},
                    },
                )
                assert answer.status_code == 200, answer.text
                revision = answer.json()["project"]["revision"]

            # ---- 1..2 秒：干跑先看刀落在哪一帧，再落盘逐帧验内容
            marks(SECOND, 2 * SECOND, "dr-marks-mid")
            query = f"{path}/render-plan?preset_id={PRESET}&range=marks&revision={revision}"
            for fps in rates:
                suffix = (
                    "" if fps is None else f"&output_fps={fps['numerator']}%2F{fps['denominator']}"
                )
                body = client.get(query + suffix).json()
                label = body["plan"]["frame_rate"]
                said = plan_window(body["argv_preview"])
                assert said == expect_window[label], (label, said, expect_window[label])
                assert "atrim=start=1.000000:end=2.000000" in ";".join(body["argv_preview"]), label
                assert body["plan"]["range"]["seconds"] == 1.0, body["plan"]
            print(
                "   1..2 秒的窗口：30 交还是 30..60 帧（与 1.138 之前逐字相同），25 交是 25..50，"
                "23.976 交是 24..48；声音那三处仍是同一句 atrim"
            )

            tallies: dict[str, dict[str, int]] = {}
            frames: dict[str, tuple[str, int, float]] = {}
            for index, fps in enumerate(rates):
                body = {
                    "request_id": f"dr-mid-{index}",
                    "expected_revision": revision,
                    "preset_id": PRESET,
                    "filename": f"中段-{index}.mp4",
                    "range": "marks",
                }
                if fps:
                    body["output_frame_rate"] = fps
                answer = client.post(path + "/renders", json=body)
                assert answer.status_code == 200, answer.text
                job = wait(client, answer.json()["job"]["id"])
                assert job["status"] == "succeeded", job
                target = Path(job["output_path"])
                stats = video_stats(target)
                colours = frame_colours(target)
                label = stats["avg_frame_rate"]
                tallies[label] = {key: colours.count(key) for key in set(colours)}
                frames[label] = (label, len(colours), float(stats["duration"]))
                assert set(colours) == {"绿"}, (label, tallies[label])
            print(
                "   逐帧读回来的内容："
                + "、".join(f"{key} {value['绿']}帧全是绿" for key, value in tallies.items())
            )

            # ---- 0..1 秒：入点是 0 时不许少给一帧，也不许多给一秒之外的东西
            marks(0, SECOND, "dr-marks-head")
            head_query = f"{path}/render-plan?preset_id={PRESET}&range=marks&revision={revision}"
            for fps in rates:
                suffix = (
                    "" if fps is None else f"&output_fps={fps['numerator']}%2F{fps['denominator']}"
                )
                body = client.get(head_query + suffix).json()
                label = body["plan"]["frame_rate"]
                assert plan_window(body["argv_preview"]) == expect_first[label], (
                    label,
                    body["plan"],
                )

            for index, fps in enumerate(rates):
                body = {
                    "request_id": f"dr-head-{index}",
                    "expected_revision": revision,
                    "preset_id": PRESET,
                    "filename": f"开头-{index}.mp4",
                    "range": "marks",
                }
                if fps:
                    body["output_frame_rate"] = fps
                answer = client.post(path + "/renders", json=body)
                assert answer.status_code == 200, answer.text
                job = wait(client, answer.json()["job"]["id"])
                assert job["status"] == "succeeded", job
                target = Path(job["output_path"])
                stats = video_stats(target)
                colours = frame_colours(target)
                label = stats["avg_frame_rate"]
                assert set(colours) == {"红"}, (label, colours[:6], colours[-6:])
                print(f"   0..1 秒按 {label} 交：{len(colours)} 帧全是红（{stats['duration']} 秒）")

            # ---- 短到不足一帧交付的窗口：宁可多给一帧，也不交出一个零帧的切口
            # 60 的线标 1..2 帧（16.7 ms 一段），按 25 交时两头向上取整会撞到同一个帧号。
            body = client.get(
                f"{path}/render-plan?preset_id={PRESET}&range=marks&revision={revision}"
                "&output_fps=25"
            ).json()
            wide_start, wide_end = _frames(plan_window(body["argv_preview"]))
            assert wide_end > wide_start, body["plan"]

            short = client.post(
                "/v1/projects",
                json={
                    "request_id": "dr-new60",
                    "name": "六十格一秒",
                    "settings": {
                        "width": SRC_W,
                        "height": SRC_H,
                        "frame_rate": {"numerator": 60, "denominator": 1},
                    },
                },
            ).json()["project"]
            spath = f"/v1/projects/{short['id']}"
            client.post(
                spath + "/edits",
                json={
                    "request_id": "dr-seed60",
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
            answer = client.post(
                spath,
                json={
                    "request_id": "dr-marks60",
                    "expected_revision": 1,
                    "settings": {
                        "width": SRC_W,
                        "height": SRC_H,
                        "frame_rate": {"numerator": 60, "denominator": 1},
                        "in_ticks": T // 60,
                        "out_ticks": 2 * (T // 60),
                    },
                },
            )
            assert answer.status_code == 200, answer.text
            tiny = client.get(
                f"{spath}/render-plan?preset_id={PRESET}&range=marks&revision=2&output_fps=25"
            ).json()
            assert plan_window(tiny["argv_preview"]) == "trim=start_frame=1:end_frame=2", tiny[
                "argv_preview"
            ][-6:]
            same = client.get(
                f"{spath}/render-plan?preset_id={PRESET}&range=marks&revision=2"
            ).json()
            assert plan_window(same["argv_preview"]) == "trim=start_frame=1:end_frame=2", same[
                "plan"
            ]
            print("   60 的线标一帧按 25 交：两头取整会撞到同一个帧号，那一刀被撑成一帧而不是零帧")

            # ---- 换率不许把区间本身挪动：三种交付读回来的秒数差不过一帧
            for label, (_name, count, duration) in frames.items():
                limit = 1.0 / (24.0 if label == "24000/1001" else 25.0)
                assert abs(duration - 1.0) <= limit, (label, duration)
                assert count in (24, 25, 30), (label, count)
            print(
                "   三个率各自的时长都还在标记的那一秒里："
                + "、".join(f"{key} {value[2]:.3f}s/{value[1]}帧" for key, value in frames.items())
            )


if __name__ == "__main__":
    main()
