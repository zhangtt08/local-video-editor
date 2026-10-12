"""交付开关的交叉表：透明、时间码、标记区间、交付帧率——四个开关一起按下去，文件还同一件事吗。

1.136 交了背景透明，1.137 交了起始时间码，1.138 交了交付帧率，1.139/1.140 修的是「交付率 × 区间」
与「交付率 × 时间码」两条接缝。每个开关单看都有自己的门禁；**没人钉过它们一起按下去会怎样**，
而 1.139 那次的教训就是「每个开关单看都对，乘在一起才是真产物」。

这一份读的全是文件本身，而且带**位置签名**：源是红/绿/蓝各一秒的三秒片。为什么非要颜色——
1.139 那个缺陷在只数帧数的门禁下是隐形的（`-t` 把文件截成一秒 24 帧，帧数、时长、率全对，
只有落在里面的内容是另一段）。所以这里既数帧、也认每一帧是哪一秒。

* 透明（`transparent`）在按 `fps=` 重采样之后还在不在，数值还是不是那一档；
* 时间码（`timecode`）在「标记区间 + 23.976 + webm alpha」那份文件里读回来是不是原来那一串
  （webm 的键是大写、写在容器标签——1.137 量的事实，这里两个位置都读）；
* 标记区间（`range=marks`）在带 alpha 的容器里，帧号是不是按**交付**那把尺数出来的；
* 不写时间码时，那一整个标签必须不在文件里（不许留个空的骗人）。

实测的数打出来（不写预测）。
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

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SRC_W, SRC_H = 320, 180
FRAME = T // 30
TC = "00:00:00:24"


def run(args, timeout=1800):
    return subprocess.run(
        [str(a) for a in args],
        capture_output=True,
        check=True,
        timeout=timeout,
        creationflags=0x08000000,
    )


def source(folder: Path) -> Path:
    """三秒、每秒一个纯色：红／绿／蓝。切错段的后果只有颜色会说。"""
    target = folder / "matrix-source.mp4"
    parts: list[str] = []
    # 三个**满值**纯色：CSS 的 green 是 0x008000（半绿），认颜色时会撞上阈值，所以写死十六进制。
    for colour in ("0xFF0000", "0x00FF00", "0x0000FF"):
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
            target,
        ]
    )
    return target


def frame_size(path: Path) -> tuple[int, int]:
    payload = json.loads(
        run(
            [
                FFPROBE,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "json",
                path,
            ]
        ).stdout.decode()
    )
    stream = payload["streams"][0]
    return int(stream["width"]), int(stream["height"])


def decode(path: Path, extra: str, pix: str) -> bytes:
    """webm 的 alpha 平面只有 libvpx-vp9 解得开（1.136 量的事实）。"""
    decode_args = ["-c:v", "libvpx-vp9"] if path.suffix == ".webm" else []
    return run(
        [
            FFMPEG,
            "-v",
            "error",
            *decode_args,
            "-i",
            str(path),
            "-vf",
            extra,
            "-f",
            "rawvideo",
            "-pix_fmt",
            pix,
            "-",
        ]
    ).stdout


def frame_alpha(path: Path, fx: float = 0.5, fy: float = 0.5) -> int:
    """把整条流的 alpha 平面解出来，取中间那一格（每一帧都取同一个位置的中位数）。"""
    width, height = frame_size(path)
    raw = decode(path, "alphaextract", "gray")
    frame_bytes = width * height
    if not frame_bytes or len(raw) < frame_bytes:
        raise AssertionError(f"alpha 平面读不到：{len(raw)} 字节 vs 一帧 {frame_bytes}")
    values = []
    for start in range(0, len(raw) - frame_bytes + 1, frame_bytes):
        plane = raw[start : start + frame_bytes]
        values.append(
            plane[min(int(fy * height), height - 1) * width + min(int(fx * width), width - 1)]
        )
    values.sort()
    return values[len(values) // 2]


def frame_names(path: Path) -> list[str]:
    raw = decode(path, "scale=1:1", "rgb24")
    names: list[str] = []
    for index in range(0, len(raw) - 2, 3):
        red, green, blue = raw[index : index + 3]
        if red > 150 and green < 100 and blue < 100:
            names.append("红")
        elif green > 150 and red < 100 and blue < 100:
            names.append("绿")
        elif blue > 150 and red < 100 and green < 100:
            names.append("蓝")
        else:
            # 不是那三个纯色之一，就别硬归类——丢了 alpha 的文件正是落在这里。
            names.append(f"其它{red}:{green}:{blue}")
    return names


def video(path: Path) -> dict:
    payload = json.loads(
        run(
            [
                FFPROBE,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=avg_frame_rate,nb_frames,duration:stream_tags=timecode",
                "-of",
                "json",
                path,
            ]
        ).stdout.decode()
    )
    return payload["streams"][0]


def frame_count(path: Path) -> int:
    """容器不一定把 nb_frames 写在头里（webm 就不写）——数一遍才是帧数。"""
    payload = json.loads(
        run(
            [
                FFPROBE,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-count_frames",
                "-show_entries",
                "stream=nb_read_frames",
                "-of",
                "json",
                path,
            ]
        ).stdout.decode()
    )
    return int(payload["streams"][0]["nb_read_frames"])


def container_duration(path: Path) -> float:
    """webm 的流里没有 duration（1.137 也遇过：位置各家不同）——容器那一份是有的。"""
    payload = json.loads(
        run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "json", path]
        ).stdout.decode()
    )
    return float(payload["format"]["duration"])


def timecode_tags(path: Path) -> dict:
    """mov/mp4 写在**流**标签，mxf/webm 写在**容器**标签，webm 那个键还是大写：两处都读。"""
    stream = video(path).get("tags") or {}
    container = (
        json.loads(
            run(
                [FFPROBE, "-v", "error", "-show_entries", "format_tags", "-of", "json", path]
            ).stdout.decode()
        )
        .get("format", {})
        .get("tags", {})
        or {}
    )
    return {key.lower(): str(value) for key, value in {**stream, **container}.items()}


def wait(client: TestClient, job_id: str) -> dict:
    deadline = time.time() + 900
    while time.time() < deadline:
        job = client.get(f"/v1/jobs/{job_id}").json()["job"]
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.4)
    raise AssertionError(f"任务 {job_id} 没有到点")


def ship(client: TestClient, path: str, revision: int, key: str, body: dict) -> Path:
    payload = {
        "request_id": f"mx-{key}",
        "expected_revision": revision,
        "filename": f"{key}.mov",
        **body,
    }
    answer = client.post(path + "/renders", json=payload)
    assert answer.status_code == 200, answer.text
    job = wait(client, answer.json()["job"]["id"])
    assert job["status"] == "succeeded", job
    return Path(job["output_path"])


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-mx-") as scratch:
        folder = Path(scratch)
        media = MediaService(
            folder / "mx-db.sqlite3", [folder], folder / "mx-cache", FFMPEG, FFPROBE
        )
        runtime = JobRuntime(
            folder / "mx-api.sqlite3", FFMPEG, folder / "exports", [folder / "exports", folder]
        )
        runtime.ensure_worker()
        token = "mxcheck" + "e" * 57
        app = create_app(folder / "mx-api.sqlite3", token, media=media, jobs=runtime)
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
                json={"request_id": "mx-new", "name": "交付交叉表", "settings": settings},
            ).json()["project"]
            path = f"/v1/projects/{project['id']}"
            seeded = client.post(
                path + "/edits",
                json={
                    "request_id": "mx-seed",
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
                                "effects": {"opacity": 0.5},
                            },
                        },
                    ],
                },
            )
            assert seeded.status_code == 200, seeded.text
            revision = seeded.json()["project"]["revision"]

            # ① 对照：带 alpha 的容器、整片、不换率——颜色与 alpha 都要是它们自己的数
            control = ship(
                client,
                path,
                revision,
                "control",
                {"preset_id": "prores-4444-alpha", "transparent": True},
            )
            base = frame_alpha(control)
            control_stats = video(control)
            assert control_stats["avg_frame_rate"] == "30/1", control_stats
            assert frame_count(control) in (90, 91), control_stats
            control_colours = frame_names(control)
            assert set(control_colours) == {"红", "绿", "蓝"}, (
                len(control_colours),
                {key: control_colours.count(key) for key in set(control_colours)},
            )
            assert 120 <= base <= 135, base

            # ② 同一份透明母版按 25 交：重采样之后平面还在、数值还是那一档、三段颜色也没丢
            resampled = ship(
                client,
                path,
                revision,
                "rate25",
                {
                    "preset_id": "prores-4444-alpha",
                    "transparent": True,
                    "output_frame_rate": {"numerator": 25, "denominator": 1},
                },
            )
            said = video(resampled)
            after = frame_alpha(resampled)
            assert said["avg_frame_rate"] == "25/1", said
            assert frame_count(resampled) in (75, 76), said
            assert set(frame_names(resampled)) == {"红", "绿", "蓝"}, said
            assert abs(after - base) <= 2, (base, after)
            print(
                f"   透明 × 交付率：不交换 alpha 中间格 {base}，按 25 交还是 {after}"
                f"（{said['nb_frames'] or frame_count(resampled)} 帧 / {said['avg_frame_rate']}）"
            )

            # ③ 标记 1..2 秒（入出点在工程设置上，不是批命令）
            marked = client.post(
                path,
                json={
                    "request_id": "mx-marks",
                    "expected_revision": revision,
                    "settings": {**settings, "in_ticks": 30 * FRAME, "out_ticks": 60 * FRAME},
                },
            )
            assert marked.status_code == 200, marked.text
            revision = marked.json()["project"]["revision"]

            # 23.976 的一秒只有 00–23 帧：这一串必须被拒——1.140 那条规矩换个容器再说一遍
            refused = client.get(
                f"{path}/render-plan?preset_id=vp9-1080p-web-alpha&revision={revision}"
                f"&timecode={TC}&output_fps=24000%2F1001"
            )
            assert refused.status_code == 422, refused.text
            assert "24000/1001" in refused.json()["error"]["message"], refused.json()
            print(
                f"   带 alpha 的容器也一样：23.976 上写 {TC} 被拒"
                f"（{refused.json()['error']['code']}）"
            )

            # ④ 四个开关一起按
            both = ship(
                client,
                path,
                revision,
                "allfour",
                {
                    "preset_id": "vp9-1080p-web-alpha",
                    "transparent": True,
                    "range": "marks",
                    "timecode": "00:00:00:23",
                    "output_frame_rate": {"numerator": 24000, "denominator": 1001},
                    "filename": "四开关.webm",
                },
            )
            stats = video(both)
            tags = timecode_tags(both)
            window_alpha = frame_alpha(both)
            colours = frame_names(both)
            assert stats["avg_frame_rate"] == "24000/1001", stats
            assert tags.get("timecode") == "00:00:00:23", tags
            assert frame_count(both) in (24, 25), stats
            assert abs(container_duration(both) - 1.0) <= 1.0 / 24.0, stats
            assert set(colours) == {"绿"}, (len(colours), sorted(set(colours)))
            assert abs(window_alpha - base) <= 3, (base, window_alpha)
            print(
                f"   四开关一起按：{both.name} 读回 {stats['avg_frame_rate']} / "
                f"{frame_count(both)} 帧 / {container_duration(both):.3f} 秒 / 时间码 "
                f"{tags.get('timecode')} / alpha {window_alpha} / 逐帧颜色 {sorted(set(colours))}"
            )

            # ⑤ 不写时间码时那一整个标签必须不在；50 fps 的透明母版平面也还在
            plain = ship(
                client,
                path,
                revision,
                "notimecode",
                {
                    "preset_id": "prores-4444-alpha",
                    "transparent": True,
                    "output_frame_rate": {"numerator": 50, "denominator": 1},
                    "filename": "没有时间码.mov",
                },
            )
            plain_tags = timecode_tags(plain)
            assert "timecode" not in plain_tags, plain_tags
            assert abs(frame_alpha(plain) - base) <= 2, (base, frame_alpha(plain))
            print(
                f"   不写的时候那一整个标签不在文件里（读到 {sorted(plain_tags) or '空'}），"
                f"50 fps 的透明母版中间格仍是 {frame_alpha(plain)}"
            )


if __name__ == "__main__":
    main()
    print(
        "PASS: 交付开关的交叉表——透明平面在重采样后还在（前后差 ≤2）、四开关一起按时文件读回"
        "自己那一档率、自己那一段时间（逐帧颜色全是标里那一秒）与自己那串时间码，不写时标签整个不在"
    )
