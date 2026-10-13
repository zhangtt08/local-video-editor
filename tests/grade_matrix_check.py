"""调色链 × 交付开关：柔边宽度与灰色平台电平在换率／透明／标记区间之后必须是同一个数。

1.141 把交付开关之间乘了一遍，这次把**画面内容**也乘进去：片段带 `blur`（柔边）与
`clip.color.exposure`（曝光），
再分别按 ① 不透明、时间线率；② 透明 ProRes、按 25 交；③ 标记 1..2 秒、按 23.976 交 三份出来。

为什么量这两个数而不是「像素相等」：换率会重采样、透明会走另一条 format 链，逐位相等本来就不是承诺；
而**柔边宽度**（gblur 的物理量）、**平台电平**（曝光的物理量）与**区间长度**（帧尺的物理量）
是这套链子真正要保证不变的东西——
1.64 那次就是靠边宽抓到「预览是柔的、导出是锐的」。容差按测量本身给：同一支 FFmpeg 在同一帧上重复读
的抖动远小于 0.1 px，所以跨交付方式给 0.35 px 已经是宽。

打出来的都是这台机器量出来的数。
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
FRAME = T // 30
EDGE = SRC_W / 2
BLUR = 0.03  # 1080 成片上约 32 px，留在实测的 1–64 px 带里
EXPOSURE = 0.5  # 一档半的曝光：中灰 128 乘 2^0.5 约 181，离顶还远
AT = 0.45


def run(args, timeout=1800):
    return subprocess.run(
        [str(a) for a in args],
        capture_output=True,
        check=True,
        timeout=timeout,
        creationflags=0x08000000,
    )


def source(folder: Path) -> Path:
    """一条硬边：左黑右**中灰**，三秒 90 帧。

    右边不能是纯白：曝光压到 255 就裁顶了，那样「曝光有没有落到成片里」就读不出来。
    中灰 128 加半档曝光是 181，再乘 0.5 的不透明度是 90——离两端都有距离。
    """
    target = folder / "gm-edge.mp4"
    run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            # 右边是**中灰**而不是纯白：`gain=1.25` 压在 255 上会被裁掉，那样「增益有没有落到
            # 成片里」就读不出来了；128 乘上去是 160，离上下两端都有距离。
            f"nullsrc=s={SRC_W}x{SRC_H}:r=30:d=3,geq=lum_expr='128*gt(X,{int(EDGE - 1)})',"
            "format=gray",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv444p",
            "-crf",
            "8",
            target,
        ]
    )
    return target


def gray_row(path: Path, at: float) -> tuple[int, list[float]]:
    """解出中间那一行的亮度（0..255），一行就是一个一维剖面。"""
    decode = ["-c:v", "libvpx-vp9"] if path.suffix == ".webm" else []
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
    )["streams"][0]
    width, height = int(payload["width"]), int(payload["height"])
    raw = run(
        [
            FFMPEG,
            "-v",
            "error",
            *decode,
            "-ss",
            f"{at:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "format=gray",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ]
    ).stdout
    if len(raw) < width * height:
        raise AssertionError(f"{path.name} 读不到一帧：{len(raw)} 字节 vs {width}x{height}")
    row = height // 2
    return width, [raw[row * width + x] for x in range(width)]


def crossing(profile: list[float], width: int, level: float) -> float:
    """剖面**上升**穿过某个电平的位置（亚像素，线性插值）。"""
    for index in range(1, width):
        a, b = profile[index - 1], profile[index]
        if a < level <= b:
            return index - 1 + (level - a) / (b - a)
    raise AssertionError(f"剖面没有穿过电平 {level}：{profile[:6]}…{profile[-6:]}")


def edge_and_level(path: Path, at: float = AT) -> tuple[float, float, float]:
    """边宽按这一条剖面**自己的**黑白两端量（不透明度会把整幅压暗，255 不是天花板）；
    平台电平取右端的众数——那是曝光与不透明度合成之后真正落盘的读数。"""
    width, profile = gray_row(path, at)
    top = max(profile)
    assert top > 30, (path.name, top)
    # 边宽除以**这一幅的宽度**才可比：blur 是画面高的比例，而不同预设交出的画幅不同。
    ramp = crossing(profile, width, top * 0.9) - crossing(profile, width, top * 0.1)
    white = sorted(profile[int(width * 0.85) : int(width * 0.95)])
    return ramp / width, white[len(white) // 2], ramp


def container_duration(path: Path) -> float:
    """时长读容器：webm 的流里根本没有 duration（1.137 就栽过一次）。"""
    payload = json.loads(
        run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "json", path]
        ).stdout.decode()
    )
    return float(payload["format"]["duration"])


def alpha_at(path: Path, at: float = AT) -> int:
    decode = ["-c:v", "libvpx-vp9"] if path.suffix == ".webm" else []
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
    )["streams"][0]
    width, height = int(payload["width"]), int(payload["height"])
    raw = run(
        [
            FFMPEG,
            "-v",
            "error",
            *decode,
            "-ss",
            f"{at:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "alphaextract",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ]
    ).stdout
    return raw[(height // 2) * width + width // 2]


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
        "request_id": f"gm-{key}",
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
    with tempfile.TemporaryDirectory(prefix="agentcut-gm-") as scratch:
        folder = Path(scratch)
        media = MediaService(
            folder / "gm-db.sqlite3", [folder], folder / "gm-cache", FFMPEG, FFPROBE
        )
        runtime = JobRuntime(
            folder / "gm-api.sqlite3", FFMPEG, folder / "exports", [folder / "exports", folder]
        )
        runtime.ensure_worker()
        token = "gmcheck" + "e" * 57
        app = create_app(folder / "gm-api.sqlite3", token, media=media, jobs=runtime)
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
                json={"request_id": "gm-new", "name": "调色与交付", "settings": settings},
            ).json()["project"]
            path = f"/v1/projects/{project['id']}"
            seeded = client.post(
                path + "/edits",
                json={
                    "request_id": "gm-seed",
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
                        {
                            "op": "clip.effects",
                            "clip_id": "c",
                            "effects": {"blur": BLUR, "opacity": 0.5},
                        },
                        {
                            "op": "clip.color",
                            "clip_id": "c",
                            "color": {"exposure": EXPOSURE, "contrast": 1.0},
                        },
                    ],
                },
            )
            assert seeded.status_code == 200, seeded.text
            revision = seeded.json()["project"]["revision"]
            # 柔边宽度就是「blur 真落到成片」的证据：没落上去是 0 px，后面 >1.0 会红。

            control = ship(
                client,
                path,
                revision,
                "control",
                {"preset_id": "h264-1080p", "filename": "control.mp4"},
            )
            width = ship(
                client,
                path,
                revision,
                "transparent",
                {
                    "preset_id": "prores-4444-alpha",
                    "transparent": True,
                    "output_frame_rate": {"numerator": 25, "denominator": 1},
                },
            )
            marked = client.post(
                path,
                json={
                    "request_id": "gm-marks",
                    "expected_revision": revision,
                    "settings": {**settings, "in_ticks": 30 * FRAME, "out_ticks": 60 * FRAME},
                },
            )
            assert marked.status_code == 200, marked.text
            revision = marked.json()["project"]["revision"]
            window = ship(
                client,
                path,
                revision,
                "window",
                {
                    "preset_id": "vp9-1080p-web-alpha",
                    "transparent": True,
                    "range": "marks",
                    "output_frame_rate": {"numerator": 24000, "denominator": 1001},
                    "filename": "区间调色.webm",
                },
            )

            base_edge, base_white, base_px = edge_and_level(control)
            other_edge, other_white, other_px = edge_and_level(width)
            third_edge, third_white, third_px = edge_and_level(window)
            width_alpha = alpha_at(width)
            window_alpha = alpha_at(window)
            assert abs(other_edge - base_edge) <= 0.002, (base_edge, other_edge)
            assert abs(third_edge - base_edge) <= 0.002, (base_edge, third_edge)
            # 中灰 128 × 2^0.5（曝光 +0.5 档）× 0.5（不透明度）≈ 90.5：读数离这个数
            # 超过 5 级，就是曝光或合成掉了。
            assert base_edge > 0.01 and 85 < base_white < 96, (base_edge, base_white)
            # 「合成之后是同一个数」还不够：把透明度烘进 RGB（丢掉 alpha 平面）也能合成出同一个数。
            # 所以还要钉住透明母版自己那两样——平面里真的有一层 0.5 的透明度，RGB 保持满值不发暗。
            assert 120 <= width_alpha <= 135, width_alpha
            assert 120 <= window_alpha <= 135, window_alpha
            assert other_white >= 150 and third_white >= 150, (other_white, third_white)
            # 区间那一份必须还是标里的第 1..2 秒：换率之后帧尺是交付的那把（1.139）。
            assert abs(container_duration(control) - 3.0) <= 1.0 / 24.0, container_duration(control)
            assert abs(container_duration(window) - 1.0) <= 1.0 / 24.0, container_duration(window)
            assert abs(container_duration(width) - 3.0) <= 1.0 / 25.0, container_duration(width)
            # 电平要按**合成之后**比：透明母版把透明度交给 alpha 平面、RGB 保持满值，
            # 不透明那一版是同一张图压在黑底上。255 × (127/255) 应落回 127。
            assert abs(other_white * width_alpha / 255 - base_white) <= 4, (
                base_white,
                other_white,
                width_alpha,
            )
            assert abs(third_white * window_alpha / 255 - base_white) <= 4, (
                base_white,
                third_white,
                window_alpha,
            )
            print(
                f"   柔边宽度（占画面宽的比例）：不透明 {base_edge:.4f}（{base_px:.1f} px）、"
                f"透明@25 {other_edge:.4f}（{other_px:.1f} px）、"
                f"区间@23.976 {third_edge:.4f}（{third_px:.1f} px）"
            )
            print(
                f"   灰色平台电平：{base_white:.0f}（不透明压在黑底）/ {other_white:.0f}"
                f"×alpha {width_alpha}/255 / {third_white:.0f}×alpha {window_alpha}/255"
                " —— 合成之后落回同一个数"
            )


if __name__ == "__main__":
    main()
    print(
        "PASS: 调色链（柔焦 + 曝光 + 不透明度）乘上交付开关之后，柔边宽度按画面宽的比例跨三种"
        "交付方式一致（差 ≤0.002），灰色平台电平按各自 alpha 合成之后落回同一个数（≤4 级），"
        "透明平面没被换率丢掉"
    )
