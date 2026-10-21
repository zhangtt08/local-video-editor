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
# 1.257：框点也能带贝塞尔。这一对柄把进度顶到 1 之外（中段冲出终点再回来），
# 所以「窗表按三次曲线走」这件事是看得见的，而不是又一条只在端点不同的式子。
BEZIER_HANDS = {"x1": 1 / 3, "y1": 2.0, "x2": 2 / 3, "y2": 2.0}
# 1.258：羽化也能跟着框点换。斜坡是从边往里量的一条 `clip((1-x)/feather,0,1)`，
# 所以同一格在硬边时亮、在宽斜坡时暗——量的就是这一对。0.60 那一格留在斜坡内侧不动，
# 它是「只有软边在动，别的一个数都没被牵连」的对照。
SOFT = {"shape": "rectangle", "center_x": 0.5, "center_y": 0.5, "width": 0.3,
        "height": 0.6, "feather": 0.0}
SOFT_FIRST = {"center_x": 0.5, "center_y": 0.5, "width": 0.3, "height": 0.6,
              "rotation": 0.0, "feather": 0.0}
SOFT_LAST = {"center_x": 0.5, "center_y": 0.5, "width": 0.3, "height": 0.6,
             "rotation": 0.0, "feather": 0.25}
SOFT_PROBES = (0.60, 0.64)


def cubic(p1: float, p2: float, u: float) -> float:
    """一条立方缓动在参数 u 上的那一格——量具自己写，不从产品 import。"""
    rest = 1.0 - u
    return 3 * rest * rest * u * p1 + 3 * rest * u * u * p2 + u * u * u


def bezier_progress(at: float, x1: float, x2: float, y1: float, y2: float) -> float:
    """把时间反解成参数（二分），再按那条三次式取纵坐标。"""
    low, high = 0.0, 1.0
    for _ in range(80):
        middle = (low + high) / 2
        if cubic(x1, x2, middle) < at:
            low = middle
        else:
            high = middle
    return cubic(y1, y2, (low + high) / 2)


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


def export_frames(
    pid: str, revision: int, key: str, folder: Path, early: int = 6, late: int = 54
) -> tuple[Path, Path]:
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
    print(f"   {key}: 从 {folder_out.name}/ 取 {frames[early].name} 与 {frames[late].name}"
          f"（共 {len(frames)} 帧）")
    return frames[early], frames[late]


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


def key(at: int, box: dict, interpolation: str = "linear", handles: dict | None = None) -> dict:
    row = {"at_ticks": at, "interpolation": interpolation, **box}
    if handles is not None:
        row["bezier"] = dict(handles)
    return row


def make_project(folder: Path, moving: bool, bezier: bool = False, soft: bool = False,
                 inherit: bool = False, plain: bool = False) -> str:
    tag = ("soft" if soft else "inherit" if inherit else "plain" if plain
           else "bezier" if bezier else ("moving" if moving else "static"))
    made = request(
        "/v1/projects",
        {"request_id": f"em-new-{tag}",
         "name": "再叠的块自己会动" + {"bezier": "（贝塞尔）", "moving": "（动）",
                                      "soft": "（软边）", "inherit": "（羽化不写）",
                                      "plain": "（静止软边）"}.get(tag, ""),
         "settings": {"width": WIDTH, "height": HEIGHT,
                      "frame_rate": {"numerator": 30, "denominator": 1}}},
        "POST",
    )
    pid = made["project"]["id"]
    probe = request("/v1/media/import", {"path": str(folder / "white.png")}, "POST")
    extra = dict(EXTRA)
    if moving:
        first = key(0, {"center_x": EXTRA["center_x"], "center_y": EXTRA["center_y"],
                        "width": EXTRA["width"], "height": EXTRA["height"], "rotation": 0.0},
                    "bezier", BEZIER_HANDS) if bezier else key(
            0, {"center_x": EXTRA["center_x"], "center_y": EXTRA["center_y"],
                "width": EXTRA["width"], "height": EXTRA["height"], "rotation": 0.0})
        extra = {**EXTRA, "keys": [first, key(2 * SECOND, MOVED)]}
    if soft:
        extra = {**SOFT, "keys": [key(0, SOFT_FIRST), key(2 * SECOND, SOFT_LAST)]}
    if inherit:
        # 1.257 那一版的框点里根本没有羽化这一格：写了框点而没写羽化，读进来就必须仍是
        # 这一块自己静止的那一个数——这里让静止值是 0.2，两枚框点只报几何的那五个数。
        still = {**SOFT, "feather": 0.2}
        box = {**SOFT_FIRST, "feather": None}
        box.pop("feather")
        extra = {**still, "keys": [key(0, box), key(2 * SECOND, box)]}
    if plain:
        extra = {**SOFT, "feather": 0.2}
    request(
        f"/v1/projects/{pid}/edits",
        {"request_id": f"em-seed-{tag}", "expected_revision": made["project"]["revision"],
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


def readings(pid: str, folder: Path, key_name: str, early: int = 6, late: int = 54) -> dict:
    revision = request(f"/v1/projects/{pid}")["revision"]
    early_frame, late_frame = export_frames(pid, revision, key_name, folder, early, late)
    start = frame_at(early_frame)
    finish = frame_at(late_frame)
    early_png = preview_shot(pid, early * FRAME, folder, f"{key_name}-early")
    late_png = preview_shot(pid, late * FRAME, folder, f"{key_name}-late")
    preview_start = frame_at(Path(early_png["out"]))
    preview_finish = frame_at(Path(late_png["out"]))
    return {
        "export": {"t0": start, "t18": finish},
        "preview": {"t0": preview_start, "t18": preview_finish},
    }


def feather_terms() -> None:
    """那条斜坡在编译串里怎么说：一个数就写那个数，只有式子才带那个下限。

    这一条不是给「画面对不对」补证据（那一头有像素），它守的是旧工程那一路的字——窗表里
    那一格若被化成 `0.200000000` 而产品又照字面抄进串里，静止那一路的串就改了形。
    """
    from agentcut.contracts import ShapeMask
    from agentcut.masks import alpha_expression

    still = ShapeMask(shape="rectangle", center_x=0.5, center_y=0.5, width=0.3,
                      height=0.6, feather=0.2)
    literal = alpha_expression(still)
    assert "/0.2," in literal and "max(" not in literal, ("静止那一路换了写法", literal)
    padded = alpha_expression(still, {"mask_feather": "0.200000000"})
    assert padded == literal, ("窗表里那个数没有化成同一个字面量", padded, literal)
    stepped = alpha_expression(still, {"mask_feather": "if(lt(T,1.000000000),0.0,0.2)"})
    assert "max(if(lt(" in stepped, ("一条式子没有那个下限", stepped)
    hard = still.model_copy(update={"feather": 0.0})
    assert alpha_expression(hard) == alpha_expression(hard, {"mask_feather": "0.0"}), (
        "一个零羽化在两条路上不再是同一条边")


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
    # 1.257：带了柄却没选贝塞尔、以及贝塞尔把五个数甩出自己那条带——都在契约那一层就拒。
    attempt([{"op": "clip.mask_stack", "clip_id": "c",
              "masks": [{**EXTRA, "keys": [key(0, body, "linear", BEZIER_HANDS)]}]}], "orphan")
    attempt([{"op": "clip.mask_stack", "clip_id": "c", "masks": [{**EXTRA, "keys": [
        key(0, {**body, "center_x": 0.95}, "bezier", {"x1": 0.5, "y1": 4.0, "x2": 0.5, "y2": 4.0}),
        key(SECOND, {**body, "center_x": 1.0})]}]}], "overshoot")
    # 1.258：软边也有自己那条带（0..1）——0.9 → 1.0 那一段被同一对柄甩过 1 也必须拒。
    attempt([{"op": "clip.mask_stack", "clip_id": "c", "masks": [{**EXTRA, "keys": [
        key(0, {**SOFT_FIRST, "feather": 0.9}, "bezier",
            {"x1": 0.5, "y1": 4.0, "x2": 0.5, "y2": 4.0}),
        key(SECOND, {**SOFT_FIRST, "feather": 1.0})]}]}], "softovershoot")
    joined = " | ".join(seen)
    assert "MASK_KEY_RANGE" in joined, seen
    assert "MASK_KEY_CLASH" in joined, seen
    assert "INVALID_REQUEST" in joined or "INVALID_MASK" in joined, seen
    assert "bezier controls require" in joined, seen
    # 那两条各自要点名自己那一格：`bezier curve exceeds` 是两条的公共后缀，只判它等于没判。
    assert "center_x bezier curve exceeds" in joined, seen
    assert "feather bezier curve exceeds" in joined, seen
    after = request(f"/v1/projects/{pid}")["revision"]
    assert after == revision, ("被拒的写入涨了版本", revision, after)
    return seen


def contract_suite(pid: str) -> None:
    """名单只由引擎说一次；而 1.256 那份回执在新字段上必须仍然命中自己。"""
    names = request("/v1/capabilities")["mask_box_interpolations"]
    assert names == ["linear", "hold", "ease", "bezier"], names
    revision = request(f"/v1/projects/{pid}")["revision"]
    body = {"center_x": 0.3, "center_y": 0.5, "width": 0.2, "height": 0.5, "rotation": 0.0}
    plain = {**EXTRA, "keys": [key(0, body)]}
    first = request(
        f"/v1/projects/{pid}/edits",
        {"request_id": "em-receipt-1", "expected_revision": revision,
         "commands": [{"op": "clip.mask_stack", "clip_id": "c", "masks": [plain]}]},
        "POST",
    )
    assert first["replayed"] is False, first
    assert first["project"]["revision"] == revision + 1, first
    # 同一笔重发：把那一格显式写成 null（1.257 之后模型里多出来的字段）。指纹要认得这是同一份载荷。
    with_nulls = json.loads(json.dumps(plain))
    for row in with_nulls["keys"]:
        row["bezier"] = None
    again = request(
        f"/v1/projects/{pid}/edits",
        {"request_id": "em-receipt-1", "expected_revision": revision,
         "commands": [{"op": "clip.mask_stack", "clip_id": "c", "masks": [with_nulls]}]},
        "POST",
    )
    assert again["replayed"] is True, ("显式写了 bezier:null 就把旧回执裂成了两半", again)
    assert again["project"]["revision"] == revision + 1, again


def curve_suite(pid: str) -> dict:
    """贝塞尔那一趟：窗表按三次曲线走（量具自己算），两端画的还是同一张表。"""
    row = request(f"/v1/projects/{pid}/preview-manifest")["clips"]["c"]
    windows = (row.get("extra_mask_windows") or [None])[0] or []
    assert len(windows) >= 2, ("贝塞尔那一条没有切成窗", windows)
    span = MOVED["center_x"] - EXTRA["center_x"]
    peak = 0.0
    for window in windows:
        at = window["from_ticks"] / (2 * SECOND)
        wanted = EXTRA["center_x"] + span * bezier_progress(
            at, BEZIER_HANDS["x1"], BEZIER_HANDS["x2"], BEZIER_HANDS["y1"], BEZIER_HANDS["y2"]
        )
        assert abs(window["box"]["center_x"] - wanted) < 2e-3, (
            "那一窗的盒中心不等于三次曲线在该窗起点的那一个",
            window["from_ticks"], window["box"]["center_x"], wanted)
        peak = max(peak, window["box"]["center_x"])
    assert peak > MOVED["center_x"] + 0.01, (
        "中段没有冲出终点——那这条柄等于没被执行", peak, MOVED["center_x"])
    for window in windows:
        assert 0.0 <= window["box"]["center_x"] <= 1.0, window["box"]
        for name in ("center_y", "width", "height"):
            assert abs(window["box"][name] - EXTRA[name]) < 1e-9, (name, window["box"])
    return {"windows": windows, "peak": peak}


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
            # 1.255：每一窗带着它**执行的那串数**。界面画那一框、拖那一框读的就是这一份，
            # 不在浏览器里再插一次值。期望由夹具自己那两枚框点按线性算法现算，不从产品 import。
            # 1.258：这一串多了羽化——没写在框点上的那一格交回的就是这一块自己静止的那个数。
            assert windows[0]["box"] == {
                "center_x": EXTRA["center_x"], "center_y": EXTRA["center_y"],
                "width": EXTRA["width"], "height": EXTRA["height"], "rotation": 0.0,
                "feather": EXTRA["feather"],
            }, ("第一窗交回的盒不是起点那一枚框点", windows[0].get("box"))
            span = MOVED["center_x"] - EXTRA["center_x"]
            for window in windows:
                wanted = EXTRA["center_x"] + span * window["from_ticks"] / (2 * SECOND)
                assert abs(window["box"]["center_x"] - wanted) < 1e-6, (
                    "那一窗交回的盒中心不等于这一格该执行的那一个",
                    window["from_ticks"], window["box"]["center_x"], wanted)
                for name in ("center_y", "width", "height", "feather"):
                    assert abs(window["box"][name] - EXTRA[name]) < 1e-9, (
                        "只有中心在动，其余几个数不该跟着变", name, window["box"])
            assert windows[0]["box"] != windows[-1]["box"], (
                "两窗交回同一个盒——那一框就不可能跟着动")
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
            curve_pid = make_project(folder, True, bezier=True)
            curve = curve_suite(curve_pid)
            # 帧 27 与 54 各自落在哪一窗，由引擎交下来的那张表说；亮/暗的归类只按那两格的盒坐标算。
            def window_at(tick: int) -> dict:
                return next(
                    item for item in curve["windows"]
                    if item["from_ticks"] <= tick < item["to_ticks"]
                )

            def pattern(box: dict) -> tuple:
                margin = 0.012
                edges = (box["center_x"] - box["width"] / 2, box["center_x"] + box["width"] / 2)
                main = (
                    PRIMARY["center_x"] - PRIMARY["width"] / 2,
                    PRIMARY["center_x"] + PRIMARY["width"] / 2,
                )
                return tuple(
                    edges[0] + margin <= x <= edges[1] - margin
                    and main[0] + margin <= x <= main[1] - margin
                    for x in PROBES
                )

            curve_frames = readings(curve_pid, folder, "curve", early=27, late=54)
            for when, tick in (("t0", 27 * FRAME), ("t18", 54 * FRAME)):
                want = pattern(window_at(tick)["box"])
                for side in ("export", "preview"):
                    image = curve_frames[side][when]
                    actual = tuple(bright(image, x, 0.5) for x in PROBES)
                    label = f"贝塞尔 / {side} / {when}"
                    print(f"   {label}：{actual}（期望 {want}）")
                    assert actual == want, (label, actual, want)
            linear_at_27 = pattern(window_at(27 * FRAME)["box"])
            assert linear_at_27 != (False, True, True, False, False), (
                "0.9 秒那一格与线性一模一样——这条柄根本没被执行"
            )
            for when in ("t0", "t18"):
                for x in PROBES:
                    left = bright(curve_frames["export"][when], x, 0.5)
                    right = bright(curve_frames["preview"][when], x, 0.5)
                    assert left == right, (
                        f"贝塞尔 {when} x={x}: 成片 {left} 预览 {right}——两端的洞不一样"
                    )
            soft_pid = make_project(folder, False, soft=True)
            soft_rows = request(f"/v1/projects/{soft_pid}/preview-manifest")["clips"]["c"]
            soft_windows = (soft_rows.get("extra_mask_windows") or [None])[0] or []
            assert len(soft_windows) >= 2, ("羽化那两枚框点没切成窗", soft_windows)
            edges = [window["box"]["feather"] for window in soft_windows]
            assert edges[0] == 0.0, ("第一窗的羽化不是起点那一枚框点的那一个", edges[:2])
            assert edges == sorted(edges) and len(set(edges)) > 1, (
                "羽化没有一窗一窗地涨上去", edges)
            # 每一窗的那一格就是**这一窗起点**按线性该执行的那一个数（窗宽由段数上限决定，
            # 所以不能拿终点那一枚当最后一窗的读数——那正是 1.182 立下的那条规矩）。
            for window in soft_windows:
                wanted = SOFT_LAST["feather"] * window["from_ticks"] / (2 * SECOND)
                assert abs(window["box"]["feather"] - wanted) < 1e-6, (
                    "那一窗的羽化不等于它起点该执行的那一个",
                    window["from_ticks"], window["box"]["feather"], wanted)
            assert soft_windows[0]["image"] != soft_windows[-1]["image"], (
                "软边变了，烘出来的那张图却没变")
            soft = readings(soft_pid, folder, "soft")
            want_soft = {("export", "t0"): (True, True), ("export", "t18"): (True, False),
                         ("preview", "t0"): (True, True), ("preview", "t18"): (True, False)}
            for side in ("export", "preview"):
                for when in ("t0", "t18"):
                    actual = tuple(bright(soft[side][when], x, 0.5) for x in SOFT_PROBES)
                    label = f"软边 / {side} / {when}"
                    print(f"   {label}：{actual}（期望 {want_soft[(side, when)]}）")
                    assert actual == want_soft[(side, when)], (label, actual)
            for when in ("t0", "t18"):
                for x in SOFT_PROBES:
                    left = bright(soft["export"][when], x, 0.5)
                    right = bright(soft["preview"][when], x, 0.5)
                    assert left == right, (
                        f"软边 {when} x={x}: 成片 {left} 预览 {right}——两端的斜坡不是同一条")
            # 1.257 那份载荷（框点里没这一格）读进来必须与静止那一路一模一样。
            inherit_pid = make_project(folder, False, inherit=True)
            plain_pid = make_project(folder, False, plain=True)
            inherit_rows = (request(f"/v1/projects/{inherit_pid}/preview-manifest")
                            ["clips"]["c"].get("extra_mask_windows") or [None])[0] or []
            assert {window["box"]["feather"] for window in inherit_rows} == {0.2}, (
                "没写羽化的框点改掉了这一块静止的那个数",
                [window["box"]["feather"] for window in inherit_rows])
            with_feather = readings(inherit_pid, folder, "inherit")
            without = readings(plain_pid, folder, "plain")
            for side in ("export", "preview"):
                for when in ("t0", "t18"):
                    actual = tuple(bright(with_feather[side][when], x, 0.5)
                                   for x in SOFT_PROBES)
                    assert actual == tuple(bright(without[side][when], x, 0.5)
                                           for x in SOFT_PROBES), (
                        f"没写羽化的框点把画面改了：{side} {when} {actual}")
                    assert actual == (True, False), (
                        f"静止 0.2 的软边该是 {side} {when} (True, False)，读到 {actual}")
            feather_terms()
            contract_suite(moving_pid)
            refusals = refusal_suite(moving_pid)
            names = "越界／同刻两枚／主遮罩带框点／带柄没选贝塞尔／甩出自己那条带／甩出软边那条带"
            print(f"   拒绝：{len(refusals)} 条各自点名（{names}）")
            print(
                "PASS: 带框点的那一块在 t=1.8s 从 [0.2,0.35] 移到 [0.37,0.52]——"
                "x=0.42/0.50 由暗转亮、x=0.30 由亮转暗，成片与预览逐点一致；"
"不带框点的那一趟两个时刻不动；越界/同刻两枚/主遮罩带框点都被点名拒绝且不涨版本；"
                "贝塞尔那一趟中段冲出终点再回来：每一窗的盒中心等于量具自己二分算出"
                "的那条三次曲线（容差 2e-3），两个时刻成片与预览逐点一致；同一笔载荷"
                "显式写了 bezier:null 仍命中 1.256 那份回执（replayed 真、版本不涨）；"
                "软边那一趟涨在窗表的每一格上：x=0.64 由亮转暗而斜坡内侧的 x=0.60 一直亮，"
                "成片与预览逐点一致；没写软边的框点与不带框点的那一块读出同一对数"
            )
        finally:
            process.kill()


if __name__ == "__main__":
    main()
