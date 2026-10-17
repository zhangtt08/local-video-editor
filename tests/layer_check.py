"""第二路画面（`layer` 节点）：链上第一次叠进**工程里的另一张图**，只能按像素验。

`composite` 那条边读的是这条链自己进来的那幅画；这一条读的是另一张素材，所以「方式与权重落到了
FFmpeg」这句话必须重新量一遍——而且量的是**换过操作数之后**的 `normal`：FFmpeg 的
`blend=all_mode=normal` 交回第一个输入，浏览器的 `mix-blend-mode: normal` 交回上面那一层，
编译时把层放到第一位，两端才说同一句话（`tests/desktop_layer_check.ts` 钉的是界面读同一份清单，
这一档钉的是文件里的像素）。

断的全是量出来的数：

1. 两个自己量的端点：底片单独导出的那一个值 B0、层那张图单独导出的那一个值 L0。期望值由
   (B0, L0) 现算，不从公式表抄——缩放与 yuv 往返都在这两个数里。
2. 八种方式在 `mix=1` 上各自等于按 W3C 定义现算的那一个数（容差 ±6 是这把尺的抖）。
3. `mix=0` 逐值等于 B0（任何方式都是），`mix=0.5` 是 B0 与 `mix=1` 的中点——这一条不需要知道
   FFmpeg 的 opacity 约定就能证伪「权重没真的进到 blend」。
4. 一处说法：`grade.layer_stages` == 监视器清单里那一条 == 编译串里那几段 blend 与那几路输入。
5. 补边交付（`contain`）时边带上的像素必须与不挂层**逐字节相同**：层只能盖画面那块。
6. 三条拒绝各点名，且**两条写入路都要拒**——`clip.grade` 与 `clip.color` 都写得进整条链。
7. 半张出界用**左右两半各一档灰度**的那张图来量：交付的必须是「按完整尺寸缩好、再裁出与画面相交
   那一片」。「整个挤进相交那块」和「裁的位置差半张」在这张图上给出的是**另一档灰度**，纯灰板子
   两样都看不出，所以这一条只能靠带子。
"""

import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import GRADE_LAYER_LIMIT, ClipColor, Project
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
FRAME_W, FRAME_H = 1920, 1080  # 这一档预设交付的就是 1080p；取样按分数换算
BASE_GREY = 0x80
LAYER_GREY = 0xC8
BAND_DARK, BAND_LIGHT = 0x40, 0xC0
MODES = ["normal", "multiply", "screen", "overlay", "darken", "lighten", "difference", "exclusion"]


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
    """左半深、右半浅的一张图：只有带子能分清「缩好后裁一半」与「整个挤进那半」。"""
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


def grey_at(path: Path, fx: float = 0.5, fy: float = 0.5) -> int:
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
    if mode == "overlay":
        if backdrop <= 128.0:
            return 2.0 * backdrop * top / 255.0
        return 255.0 - 2.0 * (255.0 - backdrop) * (255.0 - top) / 255.0
    if mode == "darken":
        return min(backdrop, top)
    if mode == "lighten":
        return max(backdrop, top)
    if mode == "difference":
        return abs(backdrop - top)
    if mode == "exclusion":
        return backdrop + top - 2.0 * backdrop * top / 255.0
    raise AssertionError(f"没有这一档：{mode}")


def main() -> None:  # noqa: C901 - 一档门禁按节读，比拆成十个互相递状态的函数清楚
    with tempfile.TemporaryDirectory(prefix="agentcut-ly-") as scratch:
        folder = Path(scratch)
        media = MediaService(
            folder / "ly-db.sqlite3", [folder], folder / "ly-cache", FFMPEG, FFPROBE
        )
        exports = folder / "exports"
        runtime = JobRuntime(folder / "ly-api.sqlite3", FFMPEG, exports, [exports, folder])
        runtime.ensure_worker()
        token = "lycheck" + "e" * 56
        app = create_app(folder / "ly-api.sqlite3", token, media=media, jobs=runtime)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            base = plate(folder, "base.png", BASE_GREY)
            layer = plate(folder, "layer.png", LAYER_GREY)
            band = band_plate(folder, "band.png")
            base_probe = client.post("/v1/media/import", json={"path": str(base)}).json()
            layer_probe = client.post("/v1/media/import", json={"path": str(layer)}).json()
            band_probe = client.post("/v1/media/import", json={"path": str(band)}).json()

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

            revision: dict = {}

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
                        # 一格「有名字但没有验过的媒体」：reference 是不可信元数据，这一格必须被点名
                        {"op": "asset.register", "asset": {"id": "u", "kind": "image",
                                                           "label": "没验过", "reference": "x"}},
                        {"op": "asset.register", "asset": {"id": "vid", "kind": "audio",
                                                           "label": "不是图像", "reference": "x",
                                                           "duration_ticks": T}},
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

            def layer_node(mode: str, mix: float = 1.0, asset: str = "ly", enabled: bool = True,
                           offset_x: float = 0.0, offset_y: float = 0.0, scale: float = 1.0):
                return {"kind": "layer", "asset_id": asset, "mode": mode, "mix": mix,
                        "offset_x": offset_x, "offset_y": offset_y, "scale": scale,
                        "enabled": enabled}

            def curve(enabled: bool = True):
                return {"kind": "curve", "channel": "rgb", "enabled": enabled,
                        "points": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]}

            # 1) 两个端点：各自由一份只有那一张图的工程量出来
            plain_path = seed("底片", "a", "ly-plain")
            base_value = grey_at(render(plain_path, "ly-plain"))
            alone_path = seed("层", "ly", "ly-alone")
            layer_value = grey_at(render(alone_path, "ly-alone"))
            assert base_value != layer_value, (base_value, layer_value)
            print(f"   端点：底片交付 {base_value}（源 128）、层交付 {layer_value}（源 200）")

            # 2) 八种方式各导一次，与按 (B0, L0) 现算的 W3C 值比
            path = plain_path
            seen = {}
            for mode in MODES:
                answer = write(path, [layer_node(mode, 1.0)], tag=f"ly-{mode}")
                assert answer.status_code == 200, answer.text
                revision[path] = answer.json()["project"]["revision"]
                value = grey_at(render(path, f"ly-{mode}"))
                expected = blend(mode, base_value, layer_value)
                seen[mode] = value
                assert abs(value - expected) <= 6, (mode, value, expected)
            assert len(set(seen.values())) >= 6, seen  # 「方式被忽略」这一整类由这条兜住

            # 3) 权重：0 回底、0.5 是中点、停用等于没挂
            for mix, label in ((0.0, "zero"), (0.5, "half")):
                answer = write(path, [layer_node("screen", mix)], tag=f"ly-{label}")
                revision[path] = answer.json()["project"]["revision"]
                value = grey_at(render(path, f"ly-{label}"))
                want = base_value if mix == 0 else (base_value + seen["screen"]) / 2.0
                assert abs(value - want) <= (2 if mix == 0 else 4), (label, value, want)
            answer = write(path, [layer_node("screen", 1.0, enabled=False)], tag="ly-off")
            revision[path] = answer.json()["project"]["revision"]
            assert grey_at(render(path, "ly-off")) == base_value, "停用的层等于没挂"

            # 4) 一处说法：清单 == `layer_stages` == 编译串里的 blend 与那几路输入
            grade = [layer_node("screen", 0.5), layer_node("difference", 0.75)]
            answer = write(path, grade, tag="ly-count")
            assert answer.status_code == 200, answer.text
            revision[path] = answer.json()["project"]["revision"]
            document = client.get(path).json()
            entry = client.get(path + "/preview-manifest").json()["clips"]["c"]["layer"]
            stages = layer_stages(ClipColor(grade=grade))
            assert entry == stages, (entry, stages)
            assert [row["mode"] for row in entry] == ["screen", "difference"], entry
            assert all(set(row) == set(LAYER_FIELDS) for row in entry), entry
            plan = compile_render_plan(Project(**document), PRESET, fit="stretch")
            text = "\n".join(plan.filters)
            assert text.count("blend=all_mode=screen") == 1, text
            assert text.count("blend=all_mode=difference") == 1, text
            assert text.count("blend=all_mode=normal:all_opacity") == 2, text
            stills = [a for a in plan.input_args if a.endswith("layer.png")]
            assert len(stills) == 2, plan.input_args

            # 4b) 1.190 的位置与大小：层只盖它该盖的那一片，出界的部分不画也不多开一路输入
            corner = [layer_node("screen", 1.0, offset_x=-0.25, offset_y=0.0, scale=0.5)]
            answer = write(path, corner, tag="ly-corner")
            assert answer.status_code == 200, answer.text
            revision[path] = answer.json()["project"]["revision"]
            placed = render(path, "ly-corner")
            inside = grey_at(placed, fx=0.25, fy=0.5)
            outside = grey_at(placed, fx=0.78, fy=0.5)
            assert inside > base_value, (inside, base_value)
            assert outside == base_value, (outside, base_value)
            entry = client.get(path + "/preview-manifest").json()["clips"]["c"]["layer"]
            assert entry[0]["offset_x"] == -0.25 and entry[0]["scale"] == 0.5, entry
            # 整层都在画面外：像素与不挂层相同，编译里也不许多开那一路输入
            gone = [layer_node("screen", 1.0, offset_x=1.0, scale=0.05)]
            answer = write(path, gone, tag="ly-gone")
            assert answer.status_code == 200, answer.text
            revision[path] = answer.json()["project"]["revision"]
            assert grey_at(render(path, "ly-gone")) == base_value, "出界的层还是画了一点"
            offscreen = compile_render_plan(
                Project(**client.get(path).json()), PRESET, fit="stretch")
            stills = [a for a in offscreen.input_args if a.endswith("layer.png")]
            assert not stills, offscreen.input_args
            graph = chr(10).join(offscreen.filters)
            assert "blend=all_mode=screen" not in graph, graph[:200]

            # 4c) 半张出界（带子那张）：先按完整尺寸缩好、再裁出与画面相交的那一片。
            #     相交区落在画面左半，看的必须是层的**右**半（浅带）；「整个挤进左半」会在那里
            #     露出深带，「裁的位置差半张」会把浅带换成深带——两种做法都量得到。
            band_path = seed("带片", "bd", "ly-band")
            band_shot = render(band_path, "ly-band")
            dark_value = grey_at(band_shot, fx=0.25, fy=0.5)
            light_value = grey_at(band_shot, fx=0.78, fy=0.5)
            assert dark_value != light_value, (dark_value, light_value)
            assert light_value != base_value, (light_value, base_value)
            print(f"   带子交付：左半 {dark_value}、右半 {light_value}（底片 {base_value}）")
            clipped = [layer_node("screen", 1.0, asset="bd", offset_x=-0.5)]
            answer = write(path, clipped, tag="ly-clipped")
            assert answer.status_code == 200, answer.text
            revision[path] = answer.json()["project"]["revision"]
            shot = render(path, "ly-clipped")
            want = blend("screen", base_value, light_value)
            for fx in (0.10, 0.40):
                value = grey_at(shot, fx=fx, fy=0.5)
                assert abs(value - want) <= 6, f"出界那半边裁错：fx={fx} 量到 {value}，要看 {want}"
            assert grey_at(shot, fx=0.75, fy=0.5) == base_value, "出界的那半画进了画面"
            flow = chr(10).join(compile_render_plan(
                Project(**client.get(path).json()), PRESET, fit="stretch").filters)
            assert f"scale={FRAME_W}:{FRAME_H}" in flow, flow[:200]
            assert f"crop={FRAME_W // 2}:{FRAME_H}:{FRAME_W // 2}:0" in flow, flow[:200]

            # 5) 补边：边带逐字节不变，画面里叠上了
            wide = client.post("/v1/projects", json={
                "request_id": "ly-wide-new", "name": "方画幅补边",
                "settings": {"width": 1000, "height": 1000,
                             "frame_rate": {"numerator": 30, "denominator": 1}},
            }).json()["project"]
            wpath = f"/v1/projects/{wide['id']}"
            answer = client.post(wpath + "/edits", json={
                "request_id": "ly-wide-seed", "expected_revision": 0,
                "commands": [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                    {"op": "asset.import", "asset_id": "a", "label": "底",
                     "probe_id": base_probe["id"], "verified": base_probe["verified"]},
                    {"op": "asset.import", "asset_id": "ly", "label": "层",
                     "probe_id": layer_probe["id"], "verified": layer_probe["verified"]},
                    {"op": "clip.add", "clip": {"id": "c", "asset_id": "a", "track_id": "v",
                                                "position_ticks": 0, "duration_ticks": T}},
                ],
            })
            assert answer.status_code == 200, answer.text
            revision[wpath] = answer.json()["project"]["revision"]
            bare = render(wpath, "ly-bare", fit="contain")
            answer = write(wpath, [layer_node("screen", 1.0)], tag="ly-boxed")
            revision[wpath] = answer.json()["project"]["revision"]
            boxed = render(wpath, "ly-boxed", fit="contain")
            assert grey_at(boxed, fx=0.02, fy=0.5) == grey_at(bare, fx=0.02, fy=0.5), "层盖到边上"
            assert grey_at(boxed, fx=0.5, fy=0.5) > grey_at(bare, fx=0.5, fy=0.5), "画面里没叠上"

            # 6) 三条拒绝，两条写入路都要拒；拒了不涨版本、不落文件
            four = [layer_node("screen") for _ in range(GRADE_LAYER_LIMIT + 1)]
            for op, label in (("clip.grade", "grade"), ("clip.color", "color")):
                before = client.get(path).json()["revision"]
                refused = write(path, four, op=op, tag=f"ly-limit-{label}")
                assert refused.status_code == 422, refused.text
                body = refused.json()["error"]
                assert body["code"] == "LAYER_LIMIT", body
                assert body["details"]["limit"] == GRADE_LAYER_LIMIT, body
                assert client.get(path).json()["revision"] == before, "拒了还涨版本"
                missing = write(path, [layer_node("screen", asset="nope")], op=op,
                                tag=f"ly-missing-{label}")
                assert missing.status_code == 422, missing.text
                assert missing.json()["error"]["code"] == "LAYER_ASSET_UNAVAILABLE", missing.text
                assert missing.json()["error"]["details"]["asset_id"] == "nope"
            # 「素材存在但不是图像」那一格：把层指向一个没验过媒体的注册素材
            unverified = write(path, [layer_node("screen", asset="u")], tag="ly-unverified")
            assert unverified.status_code == 422, unverified.text
            assert unverified.json()["error"]["code"] == "LAYER_ASSET_UNAVAILABLE"
            assert unverified.json()["error"]["details"]["reason"] == "unverified", unverified.text
            notimage = write(path, [layer_node("screen", asset="vid")], tag="ly-notimage")
            assert notimage.json()["error"]["details"]["reason"] == "kind", notimage.text
            assert notimage.json()["error"]["details"]["asset_kind"] == "audio"
            misplaced = write(path, [layer_node("screen"), curve()], tag="ly-position")
            assert misplaced.status_code == 422, f"LAYER_POSITION 没被点名：{misplaced.text[:120]}"
            assert misplaced.json()["error"]["code"] == "LAYER_POSITION", misplaced.text
            assert misplaced.json()["error"]["details"]["following"] == ["curve"]
            tail_ok = write(path, [curve(), layer_node("screen")], tag="ly-tail")
            assert tail_ok.status_code == 200, tail_ok.text
            revision[path] = tail_ok.json()["project"]["revision"]
            dry = client.post(path + "/edits", json={
                "request_id": "ly-dry", "expected_revision": revision[path], "dry_run": True,
                "commands": [{"op": "clip.grade", "clip_id": "c", "grade": four}],
            })
            assert dry.status_code == 422 and dry.json()["error"]["code"] == "LAYER_LIMIT"
            assert client.get(path).json()["revision"] == revision[path]
            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["grade_layer"] is True
            assert caps["grade_limits"]["max_layers"] == GRADE_LAYER_LIMIT
            print(f"   八档逐条：{seen}")
            print("   补边不盖黑边、两条写入路都被点名拒、dry_run 不留版本")
    print("PASS: 第二路画面按八种方式落到像素、权重是中点、半张出界裁的是缩好那张的另一半、"
          "补边不盖黑边、拒绝两条写入路都点名")


if __name__ == "__main__":
    main()
