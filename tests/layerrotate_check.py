"""第二路画面会转（1.203）：四角是**透明**的、方向与浏览器同一边——只能按像素量。

这一档之所以必须自己导一遍文件，是三件事都不在串里说出来就看不见：

1. `blend` 看不见 alpha。转过的层四个角是透明的，若还按 1.198 那一步用 `all_opacity`，
   透明角也会被算进权重，而 `rotate` 交回的角上 RGB 是黑的——`multiply` 那一档会把角量成 0。
   所以这一层的权重折进 alpha 后走 `maskedmerge`（逐格插值），角的期望值就是底片本身。
2. 方向：`rotate=a='θ*PI/180'`（θ 为正）在这台 FFmpeg 上把**左半边送到上边**，与 CSS
   的 `rotate(θdeg)` 顺时针同一边——2026-10-18 用一张「左深右浅」的带子板量过（下面第 4 节）。
   两腿同号，所以界面不需要取反；谁哪天反了，这一节就红。
3. 外接框：`ow/oh` 必须是 `|w·cos|+|h·sin|` 那一对。给小了会切掉转出去的那三角，给大了多出的
   是透明角——两种都让「层盖住哪一块」与浏览器不一致。第 2 节那一点（角上==底片、中心==按
   W3C 现算）与第 4 节那两半，一起把尺寸钉住。

断的全是量出来的数：端点 B0/L0 各由一份只有那张图的工程量出来，期望值由 (B0, L0) 现算。
"""

import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import LAYER_ROTATION_MAX, Project
from agentcut.contracts import TIMEBASE as T
from agentcut.grade import LAYER_FIELDS, layer_stages
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService
from agentcut.render import compile_render_plan

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SRC_W, SRC_H = 320, 180
PRESET = "h264-1080p"
FRAME_W, FRAME_H = 1920, 1080
BASE_GREY, LAYER_GREY = 0x80, 0xC8
BAND_DARK, BAND_LIGHT = 0x40, 0xC0
MODES = ["multiply", "screen", "normal", "difference"]


def run(args, timeout=900):
    return subprocess.run(
        [str(a) for a in args], capture_output=True, check=True, timeout=timeout,
        creationflags=0x08000000,
    )


def plate(folder: Path, name: str, grey: int) -> Path:
    target = folder / name
    run([
        FFMPEG, "-v", "error", "-y", "-f", "lavfi",
        "-i", f"color=c=0x{grey:02x}{grey:02x}{grey:02x}:s={SRC_W}x{SRC_H}:r=30:d=1",
        "-frames:v", "1", str(target),
    ])
    return target


def band_plate(folder: Path, name: str) -> Path:
    """左半深、右半浅：转 90° 之后上下哪一头深，就是「顺时针还是逆时针」这句话本身。"""
    target = folder / name
    dark = f"color=c=0x{BAND_DARK:02x}{BAND_DARK:02x}{BAND_DARK:02x}"
    light = f"color=c=0x{BAND_LIGHT:02x}{BAND_LIGHT:02x}{BAND_LIGHT:02x}"
    run([
        FFMPEG, "-v", "error", "-y",
        "-f", "lavfi", "-i", f"{dark}:s={SRC_W // 2}x{SRC_H}:r=30",
        "-f", "lavfi", "-i", f"{light}:s={SRC_W // 2}x{SRC_H}:r=30",
        "-filter_complex", "[0:v][1:v]hstack=inputs=2", "-frames:v", "1", str(target),
    ])
    return target


def grey_at(path: Path, fx: float, fy: float) -> int:
    """交付文件里某一点的灰度：整帧解码后按分数位置取（这台 FFmpeg 的 crop 不可靠）。"""
    raw = run([
        FFMPEG, "-v", "error", "-ss", "0.400", "-i", str(path),
        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]).stdout
    assert len(raw) >= FRAME_W * FRAME_H * 3, f"{path.name} 解出来 {len(raw)} 字节"
    row = raw[int(FRAME_H * fy) * FRAME_W * 3 : (int(FRAME_H * fy) + 1) * FRAME_W * 3]
    return row[int(FRAME_W * fx) * 3]


def blend(mode: str, backdrop: float, top: float) -> float:
    """W3C 的合成定义，独立写一遍：不从产品里 import，不然这一档只能证明它自己等于自己。"""
    if mode == "normal":
        return top
    if mode == "multiply":
        return backdrop * top / 255.0
    if mode == "screen":
        return 255.0 - (255.0 - backdrop) * (255.0 - top) / 255.0
    if mode == "difference":
        return abs(backdrop - top)
    raise AssertionError(f"没有这一档：{mode}")


def centre(mode: str, base_value: int, layer_value: int, mix: float) -> float:
    return blend(mode, base_value, layer_value) * mix + base_value * (1.0 - mix)


def main() -> None:  # noqa: C901 - 一档门禁按节读，比拆成十个互相递状态的函数清楚
    with tempfile.TemporaryDirectory(prefix="agentcut-lr-") as scratch:
        folder = Path(scratch)
        media = MediaService(
            folder / "lr-db.sqlite3", [folder], folder / "lr-cache", FFMPEG, FFPROBE
        )
        exports = folder / "exports"
        runtime = JobRuntime(folder / "lr-api.sqlite3", FFMPEG, exports, [exports, folder])
        runtime.ensure_worker()
        token = "lrcheck" + "e" * 56
        app = create_app(folder / "lr-api.sqlite3", token, media=media, jobs=runtime)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            base = plate(folder, "base.png", BASE_GREY)
            layer = plate(folder, "layer.png", LAYER_GREY)
            band = band_plate(folder, "band.png")
            base_probe = client.post("/v1/media/import", json={"path": str(base)}).json()
            layer_probe = client.post("/v1/media/import", json={"path": str(layer)}).json()
            band_probe = client.post("/v1/media/import", json={"path": str(band)}).json()

            revision: dict = {}

            def render(project: str, tag: str, fit: str = "stretch") -> Path:
                job = client.post(project + "/renders", json={
                    "request_id": f"{tag}-render", "expected_revision": revision[project],
                    "preset_id": PRESET, "filename": f"{tag}.mp4", "fit": fit,
                }).json()["job"]
                done = job
                for _ in range(900):
                    done = client.get(f"/v1/jobs/{job['id']}").json()["job"]
                    if done["status"] in {"succeeded", "failed", "cancelled"}:
                        break
                assert done["status"] == "succeeded", done
                return Path(done["output_path"])

            def seed(name: str, asset: str, request: str) -> str:
                created = client.post("/v1/projects", json={
                    "request_id": f"{request}-new", "name": name,
                    "settings": {"width": SRC_W, "height": SRC_H,
                                 "frame_rate": {"numerator": 30, "denominator": 1}},
                }).json()["project"]
                path = f"/v1/projects/{created['id']}"
                answer = client.post(path + "/edits", json={
                    "request_id": f"{request}-seed", "expected_revision": 0,
                    "commands": [
                        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                        {"op": "asset.import", "asset_id": "a", "label": "底",
                         "probe_id": base_probe["id"], "verified": base_probe["verified"]},
                        {"op": "asset.import", "asset_id": "ly", "label": "层",
                         "probe_id": layer_probe["id"], "verified": layer_probe["verified"]},
                        {"op": "asset.import", "asset_id": "bd", "label": "带",
                         "probe_id": band_probe["id"], "verified": band_probe["verified"]},
                        {"op": "clip.add", "clip": {"id": "c", "asset_id": asset, "track_id": "v",
                                                    "position_ticks": 0, "duration_ticks": T}},
                    ],
                })
                assert answer.status_code == 200, answer.text
                revision[path] = answer.json()["project"]["revision"]
                return path

            def write(path: str, grade: list, op: str = "clip.grade", tag: str = ""):
                command = (
                    {"op": op, "clip_id": "c", "grade": grade}
                    if op == "clip.grade"
                    else {"op": op, "clip_id": "c", "color": {"exposure": 0.0, "grade": grade}}
                )
                return client.post(path + "/edits", json={
                    "request_id": tag or f"{path[-6:]}-w", "expected_revision": revision[path],
                    "commands": [command],
                })

            def layer_node(mode: str = "multiply", mix: float = 1.0, asset: str = "ly",
                           offset_x: float = 0.0, scale: float = 1.0, rotation: float = 0.0,
                           keys: list | None = None):
                node = {"kind": "layer", "asset_id": asset, "mode": mode, "mix": mix,
                        "offset_x": offset_x, "offset_y": 0.0, "scale": scale,
                        "rotation": rotation, "enabled": True}
                if keys is not None:
                    node["keys"] = keys
                return node

            def graph(path: str) -> str:
                doc = client.get(path).json()
                return "\n".join(compile_render_plan(Project(**doc), PRESET,
                                                     fit="stretch").filters)

            # 1) 0° 就是 1.190 那一张矩形：不给那一格与给 0，编译串逐字节相同，
            #    而且串里不许出现 `rotate=` / `maskedmerge`（转过的腿没被偷偷走上）。
            plain_path = seed("底片", "a", "lr-plain")
            base_value = grey_at(render(plain_path, "lr-plain"), 0.5, 0.5)
            alone_path = seed("层", "ly", "lr-alone")
            layer_value = grey_at(render(alone_path, "lr-alone"), 0.5, 0.5)
            assert base_value != layer_value, (base_value, layer_value)
            print(f"   端点：底片交付 {base_value}、层交付 {layer_value}")

            path = plain_path
            zero = layer_node("screen")
            answer = write(path, [dict(zero, rotation=0.0)], tag="lr-zero")
            assert answer.status_code == 200, answer.text
            revision[path] = answer.json()["project"]["revision"]
            with_zero = graph(path)
            answer = write(path, [{k: v for k, v in zero.items() if k != "rotation"}],
                           tag="lr-legacy")
            assert answer.status_code == 200, answer.text
            revision[path] = answer.json()["project"]["revision"]
            assert graph(path) == with_zero, "0° 与「没有那一格」交回的不是同一份串"
            assert "rotate=" not in with_zero and "maskedmerge" not in with_zero, with_zero[:200]

            # 2) 透明角：45°、只占半张画布。中心必须等于按 W3C 现算的那一个数，
            #    而外接框的角（转出去的三角之外）必须**逐值等于底片**——
            #    `multiply` 是最尖的一档：alpha 一旦被忽略，那里就是 0 而不是 B0。
            #    取样点：外接框右上角的空三角里，离框边 40px、离斜边 214px（几何现算）。
            corner = (1451 / FRAME_W, 50 / FRAME_H)
            for mode in MODES:
                answer = write(path, [layer_node(mode, 1.0, scale=0.5, rotation=45.0)],
                               tag=f"lr-corner-{mode}")
                assert answer.status_code == 200, answer.text
                revision[path] = answer.json()["project"]["revision"]
                shot = render(path, f"lr-corner-{mode}")
                mid = grey_at(shot, 0.5, 0.5)
                want = centre(mode, base_value, layer_value, 1.0)
                assert abs(mid - want) <= 6, (mode, mid, want)
                edge = grey_at(shot, *corner)
                assert abs(edge - base_value) <= 2, (mode, edge, base_value)
                assert "maskedmerge" in graph(path), mode
                print(f"   {mode} 45°：中心 {mid}（要看 {round(want, 1)}）、角 {edge}（底片 "
                      f"{base_value}）")

            # 3) 权重折进了 alpha，不是又乘了一遍：mix=0.5 的中心是 B0 与 mix=1 的中点，
            #    mix=0 逐值等于底片；两种权重下角落都还是底片。
            for label, mix in (("half", 0.5), ("zero", 0.0)):
                answer = write(path, [layer_node("multiply", mix, scale=0.5, rotation=45.0)],
                               tag=f"lr-mix-{label}")
                assert answer.status_code == 200, answer.text
                revision[path] = answer.json()["project"]["revision"]
                shot = render(path, f"lr-mix-{label}")
                want = centre("multiply", base_value, layer_value, mix)
                got = grey_at(shot, 0.5, 0.5)
                assert abs(got - want) <= 3, (label, got, want)
                assert abs(grey_at(shot, *corner) - base_value) <= 2, label
                assert f"colorchannelmixer=aa={mix:g}" in graph(path), graph(path)[:300]

            # 4) 方向与 CSS 同一边：左深右浅的带子转 +90°，深的必须到**上边**。
            answer = write(path, [layer_node("normal", 1.0, asset="bd", rotation=90.0)],
                           tag="lr-dir")
            assert answer.status_code == 200, answer.text
            revision[path] = answer.json()["project"]["revision"]
            shot = render(path, "lr-dir")
            top = grey_at(shot, 0.5, 0.185)
            bottom = grey_at(shot, 0.5, 0.815)
            assert "rotate=a='90.0*PI/180'" in graph(path), graph(path)[:300]
            assert top < bottom, (top, bottom)
            print(f"   +90°：上 {top} 深、下 {bottom} 浅（顺时针，与 rotate(90deg) 同一边）")

            # 5) 一处说法：契约的数 == `layer_stages` == 清单那一行 == 串里那一个数。
            answer = write(path, [layer_node("screen", 1.0, scale=0.5, rotation=-33.5)],
                           tag="lr-truth")
            assert answer.status_code == 200, answer.text
            revision[path] = answer.json()["project"]["revision"]
            doc = Project(**client.get(path).json())
            stage = layer_stages(doc.clips["c"].color)[0]
            row = client.get(path + "/preview-manifest").json()["clips"]["c"]["layer"][0]
            text = graph(path)
            assert stage["rotation"] == -33.5 == doc.clips["c"].color.grade[0].rotation, stage
            assert row["rotation"] == stage["rotation"], row
            assert {k: row[k] for k in LAYER_FIELDS} == stage, (row, stage)
            assert "rotate=a='-33.5*PI/180'" in text, text[:300]
            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["layer_rotation"] is True, caps["features"]
            assert caps["grade_limits"]["layer_rotation_max"] == LAYER_ROTATION_MAX
            assert LAYER_ROTATION_MAX == 180.0

            # 6) 带针的那一层：转角是静态的那一个数（不在 `LayerProperty` 名单里），
            #    每一窗各转一次、各带自己的 mask，段数与窗数一起长。
            keys = [
                {"property": "offset_x", "at_ticks": 0, "value": -0.3, "interpolation": "hold"},
                {"property": "offset_x", "at_ticks": T // 2, "value": 0.3,
                 "interpolation": "hold"},
            ]
            answer = write(path, [layer_node("multiply", 1.0, scale=0.5, rotation=30.0,
                                             keys=keys)], tag="lr-keyed")
            assert answer.status_code == 200, answer.text
            revision[path] = answer.json()["project"]["revision"]
            text = graph(path)
            windows = text.count("rotate=a='30.0*PI/180'")
            assert 2 <= windows <= 8, windows
            assert text.count("maskedmerge") == windows, (windows, text.count("maskedmerge"))
            # 取样的那一格（t=0.4s）落在第一窗：层心被挪到 x=384，那里就是量得到的地方。
            assert abs(grey_at(render(path, "lr-keyed"), 384 / FRAME_W, 0.5)
                       - centre("multiply", base_value, layer_value, 1.0)) <= 6
            manifest = client.get(path + "/preview-manifest").json()["clips"]["c"]["layer"][0]
            assert len(manifest["windows"]) == windows, (len(manifest["windows"]), windows)
            assert manifest["rotation"] == 30.0, manifest

            # 7) 越界那一条：两路写入都拒，且拒了不涨版本（与位置/缩放同一条带的规矩）。
            before = revision[path]
            for value in (181.0, -181.0):
                for op in ("clip.grade", "clip.color"):
                    name = f"lr-over-{abs(value):.0f}-{op[5:]}"
                    refused = write(path, [layer_node(rotation=value)], op=op, tag=name)
                    assert refused.status_code == 422, refused.text
                    assert "rotation" in refused.text, refused.text[:200]
            assert client.get(path).json()["revision"] == before, "拒绝涨了版本"

            print(
                "PASS: 0° 串一字未改且不出现 rotate/maskedmerge、四角逐值等于底片（multiply 那档 "
                "最尖）、权重只折进 alpha 一次、+90° 与 rotate(90deg) 同边、那一个数一处说法、"
                "带针那层逐窗各转各合、越界两路都拒"
            )


if __name__ == "__main__":
    main()
