"""1.238：再叠的那一块可以带自己的框点——两端同一张整帧窗表。

这一档量的是「一块盒子自己会动」：主遮罩不动，第二块在两个时刻各记一枚框点（五个数一起），
导出按窗表把五个数折进 alpha 的阶梯，预览按同一份窗表每窗换一张烘好的整画面图。
两端在同一时刻读到的洞必须是同一个。

判据（五个探针 × 两个时刻 × 两端）：
* t=0.2s：露出 [0.2, 0.35]（x=0.25/0.30 亮），x=0.42 及以外暗；
* t=1.8s：那一块已经右移到 ~[0.367, 0.517]，x=0.42/0.50 亮、x=0.30 暗；
* 还有一档不带框点的对照：两个时刻都是 [0.2, 0.35]（旧工程一字不变）。
另外三条拒绝各点名：越界的框点、同一时刻两枚、主遮罩上打框点。
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
# 这块从 [0.2,0.35] 右移到 [0.4,0.55]：两枚框点说的是同一块盒子的五个数。
EXTRA = {"shape": "rectangle", "center_x": 0.275, "center_y": 0.5, "width": 0.15,
         "height": 0.6, "feather": 0.0}
MOVED = {"center_x": 0.475, "center_y": 0.5, "width": 0.15, "height": 0.6, "rotation": 0.0}
PROBES = (0.25, 0.30, 0.42, 0.50, 0.60)


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


def key(at: int, box: dict) -> dict:
    return {"at_ticks": at, "interpolation": "linear", **box}


def make_project(folder: Path, moving: bool) -> str:
    made = request(
        "/v1/projects",
        {"request_id": f"em-new-{moving}",
         "name": "再叠的块自己会动" + ("（动）" if moving else "（静）"),
         "settings": {"width": WIDTH, "height": HEIGHT,
                      "frame_rate": {"numerator": 30, "denominator": 1}}},
        "POST",
    )
    pid = made["project"]["id"]
    probe = request("/v1/media/import", {"path": str(folder / "white.png")}, "POST")
    extra = dict(EXTRA)
    if moving:
        extra = {**EXTRA, "keys": [
            key(0, {"center_x": EXTRA["center_x"], "center_y": EXTRA["center_y"],
                    "width": EXTRA["width"], "height": EXTRA["height"], "rotation": 0.0}),
            key(2 * SECOND, MOVED),
        ]}
    request(
        f"/v1/projects/{pid}/edits",
        {"request_id": f"em-seed-{moving}", "expected_revision": made["project"]["revision"],
         "commands": [
             {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
             {"op": "asset.import", "asset_id": "w", "label": "白板",
              "probe_id": probe["id"], "verified": probe["verified"]},
             {"op": "clip.add", "clip": {"id": "c", "asset_id": "w", "track_id": "v",
                                         "position_ticks": 0, "duration_ticks": 2 * SECOND}},
             {"op": "clip.mask", "clip_id": "c", "mask": PRIMARY},
             {"op": "clip.mask_stack", "clip_id": "c", "masks": [extra]},
         ]},
        "POST",
    )
    return pid


def readings(pid: str, folder: Path, key_name: str) -> dict:
    revision = request(f"/v1/projects/{pid}")["revision"]
    early, late = export_frames(pid, revision, key_name, folder)
    start = frame_at(early)
    finish = frame_at(late)
    early_png = preview_shot(pid, 6 * FRAME, folder, f"{key_name}-early")
    late_png = preview_shot(pid, 54 * FRAME, folder, f"{key_name}-late")
    preview_start = frame_at(Path(early_png["out"]))
    preview_finish = frame_at(Path(late_png["out"]))
    return {
        "export": {"t0": start, "t18": finish},
        "preview": {"t0": preview_start, "t18": preview_finish},
    }


def refusal_suite(pid: str) -> list[str]:
    revision = request(f"/v1/projects/{pid}")["revision"]
    seen = []

    def attempt(commands: list, tag: str) -> None:
        try:
            request(f"/v1/projects/{pid}/edits",
                    {"request_id": f"em-bad-{tag}", "expected_revision": revision,
                     "commands": commands}, "POST")
        except AssertionError as error:
            seen.append(str(error))
            return
        raise AssertionError(f"{tag} 本该被拒")

    body = {"center_x": 0.3, "center_y": 0.5, "width": 0.2, "height": 0.5, "rotation": 0.0}
    attempt([{"op": "clip.mask_stack", "clip_id": "c",
              "masks": [{**EXTRA, "keys": [key(3 * SECOND, body)]}]}], "range")
    attempt([{"op": "clip.mask_stack", "clip_id": "c",
              "masks": [{**EXTRA, "keys": [key(0, body), key(0, body)]}]}], "clash")
    attempt([{"op": "clip.mask", "clip_id": "c",
              "mask": {**PRIMARY, "keys": [key(0, body)]}}], "primary")
    joined = " | ".join(seen)
    assert "MASK_KEY_RANGE" in joined, seen
    assert "MASK_KEY_CLASH" in joined, seen
    assert "INVALID_REQUEST" in joined or "INVALID_MASK" in joined, seen
    after = request(f"/v1/projects/{pid}")["revision"]
    assert after == revision, ("被拒的写入涨了版本", revision, after)
    return seen


def main() -> None:
    require_prerequisites()
    global PORT
    PORT = free_port()
    with tempfile.TemporaryDirectory(prefix="agentcut-extramotion-") as temp:
        folder = Path(temp)
        plate = folder / "white.png"
        run([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
             "-i", f"color=white:s={WIDTH}x{HEIGHT}", "-frames:v", "1", str(plate)])
        process = engine(folder)
        try:
            static = readings(make_project(folder, False), folder, "static")
            moving_pid = make_project(folder, True)
            moving = readings(moving_pid, folder, "moving")
            row = request(f"/v1/projects/{moving_pid}/preview-manifest")["clips"]["c"]
            windows = (row.get("extra_mask_windows") or [None])[0] or []
            assert len(windows) >= 2, ("框点没有切成窗", windows)
            assert windows[0]["image"] != windows[-1]["image"], (
                "两端窗里的图一模一样——框点没被烘进去"
            )
            # 亮 = 同时在主遮罩 [0.2,0.8] 与那一块里面；主遮罩不动，动的只有再叠的那一块。
            expected = {
                ("static", "t0"): (True, True, False, False, False),
                ("static", "t18"): (True, True, False, False, False),
                ("moving", "t0"): (True, True, False, False, False),
                ("moving", "t18"): (False, False, True, True, False),
            }
            names = {"static": "不带框点", "moving": "带框点"}
            for name, data in (("static", static), ("moving", moving)):
                for side in ("export", "preview"):
                    for when in ("t0", "t18"):
                        image = data[side][when]
                        actual = tuple(bright(image, x, 0.5) for x in PROBES)
                        want = expected[(name, when)]
                        label = f"{names[name]} / {side} / {when}"
                        print(f"   {label}：{actual}（期望 {want}）")
                        assert actual == want, (label, actual, want)
            for name, data in (("static", static), ("moving", moving)):
                for when in ("t0", "t18"):
                    for x in PROBES:
                        left = bright(data["export"][when], x, 0.5)
                        right = bright(data["preview"][when], x, 0.5)
                        assert left == right, (
                            f"{name} {when} x={x}: 成片 {left} 预览 {right}——两端的洞不一样"
                        )
            refusals = refusal_suite(moving_pid)
            print(f"   拒绝：{len(refusals)} 条各自点名（越界／同刻两枚／主遮罩带框点）")
            print(
                "PASS: 带框点的那一块在 t=1.8s 从 [0.2,0.35] 移到 [0.37,0.52]——"
                "x=0.42/0.50 由暗转亮、x=0.30 由亮转暗，成片与预览逐点一致；"
                "不带框点的那一趟两个时刻不动；越界/同刻两枚/主遮罩带框点都被点名拒绝且不涨版本"
            )
        finally:
            process.kill()


if __name__ == "__main__":
    main()
