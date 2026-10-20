"""1.236：主遮罩的中心曲线在动时，再叠的几块在两端是不是一起动。

读码时发现的形状：预览那一侧，主遮罩的中心是用 CSS 变量 `--mask-x/--mask-y` 平移的，而那层
`mask-position` 对 `mask-image` 里的**每一层**都生效——再叠的几块于是跟着平移；导出那一侧
`alpha_expression(extra, None, …)` 交的是**静止**中心。两端对同一份工程的「洞」不一样大，
只有把同一时刻的两帧都落成像素才看得见。

这一档钉四件事：

① 主遮罩静止时：两块板在两个时刻都该「外亮内暗」，两端一致（这是量具的对照）；
② 主遮罩的中心曲线把盒子推到右边之后：**预览与导出必须都跟着推**——
   格点 x=0.42 在两个时刻都落在「再叠那块」的洞里，两端都该是暗的；
③ 同一时刻的 x=0.30 在主遮罩之外（主遮罩左缘已经移到 0.35），两端都该暗——这是
   「主遮罩真的动了」的证据，不是两边一起什么都没动；
④ 主遮罩在原位的那一帧上，两个格点的读数与 ① 一致。

跑法：空闲机器单跑 `uv run python tests/maskfollow_check.py`。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

RENDERER = ROOT / "desktop/dist/renderer"
SHOT = ROOT / "scripts/two_end_shot.cjs"
EDGE = Path(
    os.environ.get(
        "AGENTCUT_EDGE",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    )
)
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
TOKEN = "maskfollowcheck" + "b" * 36
SECOND = 70_560_000
FRAME = SECOND // 30
WIDTH, HEIGHT = 320, 180
PORT = 0
# 主遮罩 0.6 宽（0.2..0.8），再叠那块 0.15 宽（0.2..0.35）——两块一叠，露出来的是 0.35..0.8。
PRIMARY = {"shape": "rectangle", "center_x": 0.5, "center_y": 0.5, "width": 0.6,
           "height": 0.6, "feather": 0.0}
EXTRA = {"shape": "rectangle", "center_x": 0.35, "center_y": 0.5, "width": 0.3,
         "height": 0.6, "feather": 0.0}
# 探针都在两块盒子的内部或外部，离边界至少 0.05（画面上十几个像素）。
PROBES = (0.25, 0.30, 0.42, 0.55)


def fail(message: str) -> None:
    raise SystemExit("FAIL: " + message)


def require_prerequisites() -> None:
    if not (RENDERER / "index.html").exists():
        fail(f"渲染层没构建：{RENDERER}（cd desktop && npm run build:renderer）")
    if not SHOT.exists():
        fail(f"照片腿不在：{SHOT}")
    if not EDGE.exists():
        fail(f"没有可用的浏览器：{EDGE}（设 AGENTCUT_EDGE）")
    if not FFMPEG.exists() or not FFPROBE.exists():
        fail(f"没有随包 ffmpeg/ffprobe：{FFMPEG} / {FFPROBE}")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def request(path: str, payload=None, method="GET"):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:600]
        raise AssertionError(f"{method} {path} -> {error.code}: {detail}") from None


def run(argv: list) -> bytes:
    proc = subprocess.run(argv, capture_output=True, creationflags=0x08000000)
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode("utf-8", errors="replace")[-400:]
        raise AssertionError(f"{argv[0]} … 退出 {proc.returncode}: {tail}")
    return proc.stdout


def frame_at(path: Path) -> tuple[int, int, bytes]:
    width, height = stream_size(path)
    raw = run([str(FFMPEG), "-v", "error", "-i", str(path), "-frames:v", "1",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"])
    want = width * height * 3
    assert len(raw) >= want, f"{path.name} 只解出 {len(raw)} 字节，要 {want}"
    return width, height, raw[:want]


def stream_size(path: Path) -> tuple[int, int]:
    answer = json.loads(
        run([str(FFPROBE), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "json", str(path)])
        .decode("utf-8", errors="replace")
    )
    stream = answer["streams"][0]
    return int(stream["width"]), int(stream["height"])


def bright(image, x: float, y: float) -> bool:
    width, height, rgb = image
    offset = (int(y * height) * width + int(x * width)) * 3
    return (rgb[offset] + rgb[offset + 1] + rgb[offset + 2]) / 3 > 128


def engine(data_dir: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    env["AGENTCUT_TOKEN"] = TOKEN
    process = subprocess.Popen(
        [sys.executable, "-m", "agentcut", "api", "--port", str(PORT), "--json",
         "--data-dir", str(data_dir), "--cache-dir", str(data_dir / "cache"),
         "--output-dir", str(data_dir / "out"), "--media-root", str(data_dir),
         "--ffmpeg", str(FFMPEG), "--ffprobe", str(FFPROBE)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", env=env, cwd=str(ROOT),
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        line = process.stdout.readline() if process.stdout else ""
        if not line and process.poll() is not None:
            fail(f"引擎没起来（退出码 {process.returncode}）：{line[:200]}")
        if '"event": "ready"' in line:
            return process
    fail("引擎 120 秒内没有报 ready")
    raise SystemExit(1)


def export_frames(pid: str, revision: int, key: str, folder: Path) -> tuple[Path, Path]:
    presets = {item["id"]: item for item in request("/v1/render-presets")["presets"]}
    preset = presets["dpx-sequence"]
    answer = request(
        f"/v1/projects/{pid}/renders",
        {"request_id": f"mf-{key}", "expected_revision": revision,
         "preset_id": "dpx-sequence", "filename": f"{key}.{preset['container']}"},
        "POST",
    )
    job_id = answer["job"]["id"]
    deadline = time.time() + 600
    job = {}
    while time.time() < deadline:
        job = request(f"/v1/jobs/{job_id}")["job"]
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.4)
    assert job.get("status") == "succeeded", json.dumps(job, ensure_ascii=False)[:500]
    out = Path(job["output_path"])
    folder_out = out.parent if not out.is_dir() else out
    frames = sorted(folder_out.glob(f"*.{preset['container']}"))
    assert len(frames) >= 55, f"导出的帧不足：{len(frames)}"
    return frames[6], frames[54]


def preview_shot(pid: str, tick: int, folder: Path, key: str) -> dict:
    png = folder / f"preview-{key}.png"
    argv = ["node", str(SHOT), "--renderer", str(RENDERER),
            "--engine", f"http://127.0.0.1:{PORT}", "--token", TOKEN,
            "--project", pid, "--clip", "c", "--tick", str(tick),
            "--out", str(png), "--layers", "2", "--edge", str(EDGE)]
    retries = 0
    while True:
        answer = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", cwd=str(ROOT), creationflags=0x08000000,
                                timeout=300)
        if answer.returncode == 0:
            break
        if retries >= 1:
            raise AssertionError(
                f"照片腿退出 {answer.returncode}（重试过一次还是这样）: {answer.stderr[-600:]}"
            )
        retries += 1
        time.sleep(2.0)
    info = json.loads(answer.stdout.strip().splitlines()[-1])
    assert Path(info["out"]).exists(), "照片腿说写完了但文件不在"
    return info


def make_project(folder: Path, animate: bool, follow: bool = False) -> str:
    made = request(
        "/v1/projects",
        {"request_id": f"mf-new-{animate}-{follow}",
         "name": "再叠的块跟着走" + ("（跟）" if follow else "（动）" if animate else "（静）"),
         "settings": {"width": WIDTH, "height": HEIGHT,
                      "frame_rate": {"numerator": 30, "denominator": 1}}},
        "POST",
    )
    pid = made["project"]["id"]
    probe = request("/v1/media/import", {"path": str(folder / "white.png")}, "POST")
    commands = [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
        {"op": "asset.import", "asset_id": "w", "label": "白板",
         "probe_id": probe["id"], "verified": probe["verified"]},
        {"op": "clip.add", "clip": {"id": "c", "asset_id": "w", "track_id": "v",
                                    "position_ticks": 0, "duration_ticks": 2 * SECOND}},
        {"op": "clip.mask", "clip_id": "c", "mask": PRIMARY},
        {"op": "clip.mask_stack", "clip_id": "c", "masks": [EXTRA], "follow": follow},
    ]
    if animate:
        commands += [
            {"op": "keyframe.set", "clip_id": "c",
             "keyframe": {"property": "mask_x", "at_ticks": 0, "value": 0.5,
                          "interpolation": "linear"}},
            {"op": "keyframe.set", "clip_id": "c",
             "keyframe": {"property": "mask_x", "at_ticks": 2 * SECOND, "value": 0.65,
                          "interpolation": "linear"}},
        ]
    request(f"/v1/projects/{pid}/edits",
            {"request_id": f"mf-seed-{animate}", "expected_revision": made["project"]["revision"],
             "commands": commands},
            "POST")
    return pid


def readings(pid: str, folder: Path, key: str) -> dict:
    revision = request(f"/v1/projects/{pid}")["revision"]
    early, late = export_frames(pid, revision, key, folder)
    start = frame_at(early)
    finish = frame_at(late)
    early_png = preview_shot(pid, 6 * FRAME, folder, f"{key}-early")
    late_png = preview_shot(pid, 54 * FRAME, folder, f"{key}-late")
    print(f"   {key} 预览读数：早 {early_png.get('playhead')} / mask_x {early_png.get('mask_x')}；"
          f"晚 {late_png.get('playhead')} / mask_x {late_png.get('mask_x')}")
    preview_start = frame_at(Path(early_png["out"]))
    preview_finish = frame_at(Path(late_png["out"]))
    return {
        "export": {"t0": start, "t18": finish},
        "preview": {"t0": preview_start, "t18": preview_finish},
    }


def main() -> None:
    require_prerequisites()
    global PORT
    PORT = free_port()
    with tempfile.TemporaryDirectory(prefix="agentcut-maskfollow-") as temp:
        folder = Path(temp)
        plate = folder / "white.png"
        run([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
             "-i", f"color=white:s={WIDTH}x{HEIGHT}", "-frames:v", "1", str(plate)])
        process = engine(folder)
        try:
            static = readings(make_project(folder, False), folder, "static")
            moving = readings(make_project(folder, True), folder, "moving")
            following = readings(make_project(folder, True, True), folder, "following")
            # 两块盒子是相乘的：亮 = 同时在主遮罩与再叠那块里面。
            # 主遮罩 [0.2,0.8] 随中心曲线右移；再叠那块 [0.2,0.5] 不动。
            #   静止：任何时刻都亮在 [0.2,0.5]；
            #   主遮罩 0.2s（[0.215,0.815]）：亮在 [0.215,0.5]；
            #   主遮罩 1.8s（[0.335,0.935]）：亮在 [0.335,0.5]。
            expected = {
                ("static", "t0"): (True, True, True, False),
                ("static", "t18"): (True, True, True, False),
                ("moving", "t0"): (True, True, True, False),
                ("moving", "t18"): (False, False, True, False),
                # 1.237：勾上「跟着主遮罩平移」之后，再叠那块随主遮罩一起右移 0.135，
                # 所以 t1.8 的 x=0.55 也落进了它的洞里。
                ("following", "t0"): (True, True, True, False),
                ("following", "t18"): (False, False, True, True),
            }
            names = {"static": "静止", "moving": "主遮罩在动", "following": "跟着主遮罩平移"}
            for name, data in (("static", static), ("moving", moving), ("following", following)):
                for side in ("export", "preview"):
                    for when in ("t0", "t18"):
                        image = data[side][when]
                        actual = tuple(bright(image, x, 0.5) for x in PROBES)
                        want = expected[(name, when)]
                        label = f"{names[name]} / {side} / {when}"
                        print(f"   {label}：{actual}（期望 {want}）")
                        assert actual == want, (label, actual, want)
            # 两端逐点一致（这一档的核心：同一份工程的两个「洞」）。
            for name, data in (("static", static), ("moving", moving), ("following", following)):
                for when in ("t0", "t18"):
                    for x in PROBES:
                        left = bright(data["export"][when], x, 0.5)
                        right = bright(data["preview"][when], x, 0.5)
                        assert left == right, (
                            f"{name} {when} x={x}: 成片 {left} 预览 {right}——两端的洞不一样"
                        )
            print(
                "PASS: 主遮罩右移之后，不跟随的再叠块仍在原地"
                "（x=0.42 都亮、x=0.55 都暗），跟随的那一块跟着右移（x=0.55 由暗转亮）；"
                "主遮罩自己也在动（x=0.30 由亮转暗），静止那一趟两端不动；"
                "三趟两个时刻四个探针两端逐点一致"
            )
        finally:
            process.kill()


if __name__ == "__main__":
    main()
