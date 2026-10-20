"""两端同洞：预览那一格的像素与导出那一片的像素，逐点比同一处（1.222 第 1 项）。

为什么要有这一档：遮罩在两端是两套完全不同的机制——导出是同一条 alpha 上乘括号
（`geq` 的 `alpha(X,Y)*A*B`），预览是同一幅画面上叠 `mask-image` 再 `mask-composite:
intersect`。1.221 那轮证到的是「Chromium 认下这两层图」（computed style 读出
`intersect, intersect`），**没有**证到「预览里那个洞与成片里那个洞是同一个洞」。
computed style 会说谎：它只说明式子被解析了，不说明画出来的东西一样。

这一档把两端都落成像素再逐点比：

* 导出那一片：真跑一次渲染任务（`POST /v1/projects/{id}/renders` → 轮询 `/v1/jobs`），
  随包 ffmpeg 取第一帧；
* 预览那一格：`scripts/two_end_shot.cjs` 把渲染层伺服起来、深链进同一个工程，用
  `--headless=new` 的 Edge 经 CDP `Page.captureScreenshot` 只截 `.masked-picture` 那块矩形
  ——这条腿是这台机器上实测能出图的那一条（`msedge --screenshot` 那个写法不出图）；
* 比的是**内容**：归一化画面上 25×15 的格点逐点二值化（均值 >128 记「亮」），
  离任何一条遮罩边不足 3 px 的点**按各自分辨率剔除**——羽化是 0，边就是边，但边界处
  抗锯齿与色度二次采样会推开一两个像素，那不该算成分歧。

四件事必须同时成立，缺一就是假的：

① 保留下来的格点两端**一个都不许分歧**；
② 每一格还不止要「两端一样」，要**按几何该亮就亮、该暗就暗**——四类点
   （两块都留、只主遮罩留、只再叠那块留、两块都外）的该亮该暗只由两块矩形的坐标算，
   不看像素，所以「两端一致地全黑」通不过；
③ 对照那一趟（只有主遮罩）：「只主遮罩留」那一批点必须亮；
④ 再叠一块之后：同一批点必须在**两端同时**由亮转暗。
   ③+④ 才是「量具看得见那块多出来的洞」——只有 ① 的话，两端一致地什么都没切也能过关。

拍照之前先证明那一格值得拍（在 `two_end_shot.cjs` 里）：矩形面积>0、图解码完、
遮罩层数等于引擎交下来的张数、画面**铺满**格子、没有遮罩编辑的参考线混进来。
照片腿抖动重试一次，而且重试了几次必须说出来——真缺陷会连着抖两次。

跑法：空闲机器单跑 `uv run python tests/twoband_check.py`。缺渲染层、缺 node、缺 Edge、
缺随包 ffmpeg 一律点名，不许静悄悄跳过。
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
TOKEN = "twobandcheck" + "b" * 40
SECOND = 70_560_000
WIDTH, HEIGHT = 320, 180
PORT = 0
# 主遮罩留中间一大块，再叠那块留在右上：交集是右上那一小块，
# 「只主遮罩留」的那一格是主遮罩里被再叠那块切掉的其余部分。
PRIMARY = {"shape": "rectangle", "center_x": 0.5, "center_y": 0.5, "width": 0.8,
           "height": 0.8, "feather": 0.0}
EXTRA = {"shape": "rectangle", "center_x": 0.8, "center_y": 0.28, "width": 0.34,
         "height": 0.3, "feather": 0.0}
GRID_X, GRID_Y = 25, 15
EDGE_PX = 3.0
MIN_POINTS = 12


def fail(message: str) -> None:
    raise SystemExit("FAIL: " + message)


def require_prerequisites() -> None:
    if not (RENDERER / "index.html").exists():
        fail(f"渲染层没构建：{RENDERER}（cd desktop && npm run build:renderer）")
    if not SHOT.exists():
        fail(f"照片腿不在：{SHOT}")
    if not EDGE.exists():
        fail(f"没有可用的浏览器：{EDGE}（设 AGENCUT_EDGE）")
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


def stream_size(path: Path) -> tuple[int, int]:
    answer = json.loads(
        run([str(FFPROBE), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "json", str(path)])
        .decode("utf-8", errors="replace")
    )
    stream = answer["streams"][0]
    return int(stream["width"]), int(stream["height"])


def first_frame(path: Path) -> tuple[int, int, bytes]:
    """两端同一把尺：都经随包 ffmpeg 解码成 rgb24，再按归一化坐标取样。"""
    width, height = stream_size(path)
    argv = [str(FFMPEG), "-v", "error"]
    if path.suffix == ".mp4":
        argv += ["-i", str(path), "-vf", "select=eq(n\\,0)", "-frames:v", "1"]
    else:
        argv += ["-i", str(path)]
    argv += ["-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    raw = run(argv)
    want = width * height * 3
    assert len(raw) >= want, f"{path.name} 只解出 {len(raw)} 字节，要 {want}"
    return width, height, raw[:want]


def bright_at(rgb: bytes, width: int, height: int):
    def at(x: float, y: float) -> bool:
        offset = (int(y * height) * width + int(x * width)) * 3
        return (rgb[offset] + rgb[offset + 1] + rgb[offset + 2]) / 3 > 128

    return at


def near_edge(x: float, y: float, width: int, height: int, rects) -> bool:
    for rect in rects:
        for edge in (rect["center_x"] - rect["width"] / 2, rect["center_x"] + rect["width"] / 2):
            if abs(x - edge) * width < EDGE_PX:
                return True
        for edge in (rect["center_y"] - rect["height"] / 2, rect["center_y"] + rect["height"] / 2):
            if abs(y - edge) * height < EDGE_PX:
                return True
    return False


def inside(rect: dict, x: float, y: float) -> bool:
    return (abs(x - rect["center_x"]) < rect["width"] / 2
            and abs(y - rect["center_y"]) < rect["height"] / 2)


def buckets(export_size, preview_size):
    """按两块矩形的几何把格点分成四类；任一端离边太近就整个点不参与比对。

    分类只看几何，不看像素——「亮不亮」是后面按每一趟该是什么样来判的。
    """
    out = {"both": [], "primary_only": [], "extra_only": [], "outside": []}
    for column in range(GRID_X):
        for row in range(GRID_Y):
            x = (column + 0.5) / GRID_X
            y = (row + 0.5) / GRID_Y
            if (near_edge(x, y, export_size[0], export_size[1], [PRIMARY, EXTRA])
                    or near_edge(x, y, preview_size[0], preview_size[1], [PRIMARY, EXTRA])):
                continue
            in_primary, in_extra = inside(PRIMARY, x, y), inside(EXTRA, x, y)
            key = ("both" if in_primary and in_extra else
                   "primary_only" if in_primary else
                   "extra_only" if in_extra else "outside")
            out[key].append((x, y))
    return out


def wants_bright(region: str, with_extra: bool) -> bool:
    """这一类点在这一次画面上**应该**是亮的还是暗的——由几何决定，不由像素决定。"""
    if region == "both":
        return True
    if region == "primary_only":
        return not with_extra
    return False


def engine(data_dir: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    env["AGENTCUT_TOKEN"] = TOKEN
    process = subprocess.Popen(
        [
            sys.executable, "-m", "agentcut", "api", "--port", str(PORT), "--json",
            "--data-dir", str(data_dir), "--cache-dir", str(data_dir / "cache"),
            "--output-dir", str(data_dir / "out"), "--media-root", str(data_dir),
            "--ffmpeg", str(FFMPEG), "--ffprobe", str(FFPROBE),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(ROOT),
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


def export_frame(pid: str, revision: int, key: str) -> Path:
    presets = request("/v1/render-presets")["presets"]
    mp4 = next(item for item in presets if item.get("container") == "mp4")
    answer = request(
        f"/v1/projects/{pid}/renders",
        {"request_id": f"2b-{key}", "expected_revision": revision,
         "preset_id": mp4["id"], "filename": f"{key}.mp4"},
        "POST",
    )
    job_id = answer["job"]["id"]
    deadline = time.time() + 600
    while time.time() < deadline:
        job = request(f"/v1/jobs/{job_id}")["job"]
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.4)
    else:
        raise AssertionError(f"任务 {job_id} 没有到点")
    assert job["status"] == "succeeded", json.dumps(job, ensure_ascii=False)[:500]
    out = Path(job["output_path"])
    assert out.exists(), f"任务说成功了但文件不在：{out}"
    return out


def preview_shot(pid: str, layers: int, folder: Path) -> tuple[Path, dict]:
    png = folder / f"preview-{layers}.png"
    argv = [
        "node", str(SHOT),
        "--renderer", str(RENDERER),
        "--engine", f"http://127.0.0.1:{PORT}",
        "--token", TOKEN,
        "--project", pid,
        "--clip", "c",
        "--out", str(png),
        "--layers", str(layers),
        "--edge", str(EDGE),
    ]
    retries = 0
    while True:
        answer = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(ROOT), creationflags=0x08000000, timeout=300,
        )
        if answer.returncode == 0:
            break
        # 上一趟的浏览器可能还没退干净，附着的那一页就没了（1.219 在形状扫描上量到过这一抖）：
        # 重试一次，但**必须说出口**——真缺陷会连着抖两次，静悄悄重试只会把门禁用它自己的抖动喂饱。
        if retries >= 1:
            raise AssertionError(
                f"照片腿退出 {answer.returncode}（重试过一次还是这样）: {answer.stderr[-600:]}"
            )
        retries += 1
        time.sleep(2.0)
    info = json.loads(answer.stdout.strip().splitlines()[-1])
    assert Path(info["out"]).exists(), "照片腿说写完了但文件不在"
    if retries:
        print(f"   照片腿重试了 {retries} 次才拍到第 {layers} 层那一格")
    return png, info


def compare(png: Path, mp4: Path, with_extra: bool, label: str) -> dict:
    export = first_frame(mp4)
    preview = first_frame(png)
    groups = buckets(export[:2], preview[:2])
    read_export = bright_at(export[2], export[0], export[1])
    read_preview = bright_at(preview[2], preview[0], preview[1])
    disagreements = []
    wrong = []
    counts = {}
    for key, points in groups.items():
        expect = wants_bright(key, with_extra)
        tally = {"points": len(points), "export": 0, "preview": 0,
                 "expect": "亮" if expect else "暗"}
        for (x, y) in points:
            e, p = read_export(x, y), read_preview(x, y)
            tally["export"] += 1 if e else 0
            tally["preview"] += 1 if p else 0
            if e != p:
                disagreements.append((key, round(x, 4), round(y, 4), e, p))
            if e != expect or p != expect:
                wrong.append((key, round(x, 4), round(y, 4), "导出" if e != expect else "",
                              "预览" if p != expect else ""))
        counts[key] = tally
    return {"label": label, "counts": counts, "disagreements": disagreements,
            "wrong": wrong, "export": export[:2], "preview": preview[:2]}


def report(answer: dict) -> str:
    return (f"{answer['label']}：尺寸 导出 {answer['export']} 预览 {answer['preview']}，"
            + json.dumps(answer["counts"], ensure_ascii=False))


def main() -> None:
    require_prerequisites()
    global PORT
    PORT = free_port()
    with tempfile.TemporaryDirectory(prefix="agentcut-twoband-") as temp:
        folder = Path(temp)
        plate = folder / "white.png"
        run([str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
             "-i", f"color=white:s={WIDTH}x{HEIGHT}", "-frames:v", "1", str(plate)])
        process = engine(folder)
        try:
            made = request(
                "/v1/projects",
                {"request_id": "2b-new", "name": "两端同洞",
                 "settings": {"width": WIDTH, "height": HEIGHT,
                              "frame_rate": {"numerator": 30, "denominator": 1}}},
                "POST",
            )
            pid = made["project"]["id"]
            probe = request("/v1/media/import", {"path": str(plate)}, "POST")
            request(
                f"/v1/projects/{pid}/edits",
                {"request_id": "2b-seed", "expected_revision": made["project"]["revision"],
                 "commands": [
                     {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
                     {"op": "asset.import", "asset_id": "w", "label": "白板",
                      "probe_id": probe["id"], "verified": probe["verified"]},
                     {"op": "clip.add", "clip": {
                         "id": "c", "asset_id": "w", "track_id": "v",
                         "position_ticks": 0, "duration_ticks": 2 * SECOND}},
                     {"op": "clip.mask", "clip_id": "c", "mask": PRIMARY},
                 ]},
                "POST",
            )
            revision = request(f"/v1/projects/{pid}")["revision"]

            control_png, control_info = preview_shot(pid, 1, folder)
            control_mp4 = export_frame(pid, revision, "control")
            control = compare(control_png, control_mp4, False, "对照（只有主遮罩）")

            stacked = request(
                f"/v1/projects/{pid}/edits",
                {"request_id": "2b-stack", "expected_revision": revision,
                 "commands": [{"op": "clip.mask_stack", "clip_id": "c", "masks": [EXTRA]}]},
                "POST",
            )["project"]["revision"]
            stack_png, stack_info = preview_shot(pid, 2, folder)
            stack_mp4 = export_frame(pid, stacked, "stacked")
            answer = compare(stack_png, stack_mp4, True, "再叠一块之后")

            assert control_info["mask_layers"] == 1, control_info
            assert stack_info["mask_layers"] == 2, stack_info
            assert "intersect" in str(stack_info["mask_composite"]), stack_info

            for each in (control, answer):
                assert not each["disagreements"], (
                    f"{report(each)} 两端在 {len(each['disagreements'])} 个格点上分歧，"
                    f"前六个 {each['disagreements'][:6]}"
                )
                assert not each["wrong"], (
                    f"{report(each)} 有 {len(each['wrong'])} 个格点没有按几何该亮/该暗，"
                    f"前六个 {each['wrong'][:6]}"
                )
                for key in ("both", "primary_only", "outside"):
                    assert each["counts"][key]["points"] >= MIN_POINTS, report(each)
                assert each["counts"]["extra_only"]["points"] >= 1, report(each)

            total = sum(len(v) for v in buckets(answer["export"], answer["preview"]).values())
            flip = answer["counts"]["primary_only"]["points"]
            print(
                "PASS: 预览那一格与成片那一帧逐点同侧——两端尺寸 "
                f"导出 {answer['export']} 预览 {answer['preview']}，{total} 个格点零分歧，"
                f"并且每一格都按几何该亮/该暗；再叠那块把主遮罩内 {flip} 个格点"
                f"由亮按成暗，预览与导出同时翻（对照那一趟同样 {flip} 个点是亮的）"
            )
        finally:
            process.kill()


if __name__ == "__main__":
    main()
