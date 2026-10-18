"""层的针进动画曲线编辑器（1.205）：那条读路由交回的必须就是导出执行的那张窗表。

这一档为什么单独一档：曲线编辑器画的、检查器钉的、导出执行的，现在走的是**三条不同的路**
（一条读、一条状态写入、一条编译）。只要其中任何一处自己算了一遍台阶，就会出现
「屏幕上是一级台阶、文件里是另一级」。所以断的全是同一份数的三个面：

1. `POST /v1/animation/layer_curve` 的 `curve` 逐点等于引擎那张窗表
   （`animation.layer_curve(clip, layer_schedule(...))`）——不是等于另一份公式；
   ——不是等于另一份公式，而是等于那张窗表本身；`path` 里必须全是 `H`/`V`（阶梯）。
2. `limits` 等于契约 `LAYER_KEY_LIMITS[prop]`，`keys` 的刻度按 `animation_offset_ticks` **折过一次**
   （与 `graph_curve` 同一口径），并且落在片段外的针不交回来。
3. 一枚针都没有时交回一级平台阶（值就是静态那一个数），`keys` 是空表——
   界面因此不必自己补一条线。
4. 写入还是那一条 `clip.grade`：把读到的局部刻度加回去再写，读回来的局部刻度与原来逐枚相同
   （往返不漂），且这一趟不新增错误码。
5. 三种越界各点名拒（第几层不存在、格长小于 1、属性名不在名单里），并且**读路由不涨版本**。
6. `capabilities` 里那五档的量程与 `LAYER_KEY_LIMITS` 一条条对上，开关 `layer_curve` 在。
"""

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.animation import layer_curve, layer_schedule
from agentcut.contracts import LAYER_KEY_LIMITS, LAYER_ROTATION_MAX, Project
from agentcut.contracts import TIMEBASE as T
from agentcut.grade import LAYER_FIELDS
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService
from agentcut.render import compile_render_plan

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
TICKS = T  # 一段一秒
QUANTUM = T // 30


def plate(folder: Path, name: str, grey: int) -> Path:
    import subprocess

    target = folder / name
    subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
         "-i", f"color=c=0x{grey:02x}{grey:02x}{grey:02x}:s=320x180:r=30:d=1",
         "-frames:v", "1", str(target)],
        capture_output=True, check=True, timeout=600, creationflags=0x08000000,
    )
    return target


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-lcv-") as scratch:
        folder = Path(scratch)
        media = MediaService(
            folder / "lcv-db.sqlite3", [folder], folder / "lcv-cache", FFMPEG, FFPROBE
        )
        exports = folder / "exports"
        runtime = JobRuntime(folder / "lcv-api.sqlite3", FFMPEG, exports, [exports, folder])
        token = "lcvcheck" + "e" * 55
        app = create_app(folder / "lcv-api.sqlite3", token, media=media, jobs=runtime)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            base = plate(folder, "base.png", 0x80)
            layer = plate(folder, "layer.png", 0xC8)
            base_probe = client.post("/v1/media/import", json={"path": str(base)}).json()
            layer_probe = client.post("/v1/media/import", json={"path": str(layer)}).json()

            def key(prop: str, frame: int, value: float):
                return {"property": prop, "at_ticks": frame * QUANTUM, "value": value,
                        "interpolation": "hold"}

            def layer_node(keys=None, rotation=0.0, scale=1.0, mix=1.0):
                return {"kind": "layer", "asset_id": "ly", "mode": "normal", "mix": mix,
                        "offset_x": 0.0, "offset_y": 0.0, "scale": scale, "rotation": rotation,
                        "keys": keys or [], "enabled": True}

            created = client.post("/v1/projects", json={
                "request_id": "lcv-new", "name": "层的曲线",
                "settings": {"width": 320, "height": 180,
                             "frame_rate": {"numerator": 30, "denominator": 1}},
            }).json()["project"]
            path = f"/v1/projects/{created['id']}"
            revision = created["revision"]
            seed = client.post(path + "/edits", json={
                "request_id": "lcv-seed", "expected_revision": revision,
                "commands": [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                    {"op": "asset.import", "asset_id": "a", "label": "底",
                     "probe_id": base_probe["id"], "verified": base_probe["verified"]},
                    {"op": "asset.import", "asset_id": "ly", "label": "层",
                     "probe_id": layer_probe["id"], "verified": layer_probe["verified"]},
                    {"op": "clip.add", "clip": {"id": "c", "asset_id": "a", "track_id": "v",
                                                "position_ticks": 0, "duration_ticks": TICKS}},
                ],
            })
            assert seed.status_code == 200, seed.text[:300]
            revision = seed.json()["project"]["revision"]

            def write(grade: list, tag: str):
                nonlocal revision
                answer = client.post(path + "/edits", json={
                    "request_id": tag, "expected_revision": revision,
                    "commands": [{"op": "clip.grade", "clip_id": "c", "grade": grade}],
                })
                assert answer.status_code == 200, answer.text[:300]
                revision = answer.json()["project"]["revision"]

            def curve_body(prop: str, layer_index: int = 0, clip: dict | None = None,
                           quantum: int = QUANTUM):
                doc = client.get(path).json()
                target = clip if clip is not None else doc["clips"]["c"]
                return client.post(
                    f"/v1/animation/layer_curve?property={prop}&layer={layer_index}"
                    f"&quantum={quantum}",
                    json=target,
                )

            # 1) 有针：读回来的阶梯 == 那张窗表，逐点、一个不多一个不少
            write([layer_node(keys=[key("rotation", 0, 0.0), key("rotation", 15, 90.0)])],
                  "lcv-rot-1")
            doc = client.get(path).json()
            clip = Project(**doc).clips["c"]
            table = layer_schedule(clip, QUANTUM)[0]
            windows = layer_curve(clip, table)
            answer = curve_body("rotation")
            assert answer.status_code == 200, answer.text[:300]
            graph = answer.json()
            assert [p["value"] for p in graph["curve"][:len(windows)]] == [
                w["rotation"] for w in windows], (graph["curve"], windows)
            assert graph["curve"][-1]["offset"] == 1.0, graph["curve"]
            assert all(p["easing"] == "steps(1, end)" for p in graph["curve"]), graph["curve"]
            # 阶梯只该有 M / H / V：出现 C（贝塞尔）或 L（斜线）就是在补中间态。
            heads = {row[0] for row in graph["path"].split() if row[0].isalpha()}
            assert heads <= {"M", "H", "V"}, graph["path"]
            assert graph["limits"] == list(LAYER_KEY_LIMITS["rotation"]), graph["limits"]
            assert graph["layer"] == 0 and graph["asset_id"] == "ly", graph
            fold = clip.animation_offset_ticks or 0
            times = [k["at_ticks"] for k in graph["keys"]]
            assert times == [0 - fold, 15 * QUANTUM - fold], graph["keys"]
            print(f"   读回来的阶梯：{[(p['offset'], p['value']) for p in graph['curve']]}")

            # 2) 写回来的还是那一条 clip.grade：局部刻度加回去再写，读回来逐枚相同（往返不漂）
            local = [[k["at_ticks"], k["value"]] for k in graph["keys"]]
            fold = clip.animation_offset_ticks or 0
            stored = [{"property": "rotation", "at_ticks": tick + fold, "value": value,
                       "interpolation": "hold"} for tick, value in local]
            write([layer_node(keys=stored)], "lcv-rot-2")
            again = curve_body("rotation").json()
            assert [[k["at_ticks"], k["value"]] for k in again["keys"]] == local, again["keys"]
            assert again["path"] == graph["path"], "写回同一串针，画出来的台阶变了"
            compiled = "\n".join(compile_render_plan(Project(**client.get(path).json()),
                                                    "h264-1080p", fit="stretch").filters)
            assert compiled.count("rotate=a=") == 1, compiled[:300]

            # 3) 一枚针都没有：一级平台阶、值就是静态那一个数，keys 是空表
            write([layer_node(rotation=33.0)], "lcv-flat-2")
            flat = curve_body("rotation").json()
            assert [p["value"] for p in flat["curve"]] == [33.0, 33.0], flat["curve"]
            assert flat["keys"] == [], flat["keys"]
            assert [p["offset"] for p in flat["curve"]] == [0.0, 1.0], flat["curve"]

            # 4) 五个数各有自己的量程，读那一个数就画那一个数（不是把转角借来画别的一条）
            for prop, value in (("offset_x", -0.5), ("scale", 2.0), ("mix", 0.25),
                                ("rotation", -45.0), ("offset_y", 0.5)):
                write([layer_node(keys=[key(prop, 0, value), key(prop, 20, value / 2)])],
                      f"lcv-{prop}-2")
                got = curve_body(prop).json()
                assert got["limits"] == list(LAYER_KEY_LIMITS[prop]), (prop, got["limits"])
                assert [p["value"] for p in got["curve"][:2]] == [value, value / 2], (prop, got)
            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["layer_curve"] is True, caps["features"]
            bands = caps["grade_limits"]["layer_key_bands"]
            assert {k: tuple(v) for k, v in bands.items()} == {
                k: tuple(v) for k, v in LAYER_KEY_LIMITS.items()}, bands
            assert caps["grade_limits"]["layer_key_props"] == list(LAYER_KEY_LIMITS), bands

            # 5) 三种越界各点名，且读路由不涨版本
            before = revision
            refusals = [
                ("rotation", 3, QUANTUM, "LAYER_CURVE_TARGET"),   # 没有第三层
                ("rotation", 0, 0, "LAYER_CURVE_TARGET"),        # 格长小于 1
                ("blur", 0, QUANTUM, None),                      # 不是那五个数之一
            ]
            for prop, layer_index, quantum, code in refusals:
                answer = curve_body(prop, layer_index, quantum=quantum)
                assert answer.status_code == 422, (prop, layer_index, quantum, answer.text[:200])
                if code:
                    assert answer.json()["error"]["code"] == code, answer.text[:200]
                    assert answer.json()["error"]["details"], answer.text[:200]
            assert client.get(path).json()["revision"] == before, "读路由涨了版本"

            # 5b) 刻度只折一次：针存在的是含 `animation_offset_ticks` 的时钟，读回来要减去那一次，
            #     写回去再加回来——往返必须落在同一格。（这一节是突变逼出来的：剪过的片段
            #     offset 不为 0 时，「忘记折」才会看得见；第一版没有它，那条突变是绿的。）
            trimmed = client.post("/v1/projects", json={
                "request_id": "lcv-fold-new", "name": "剪过的层",
                "settings": {"width": 320, "height": 180,
                             "frame_rate": {"numerator": 30, "denominator": 1}},
            }).json()["project"]
            tpath = f"/v1/projects/{trimmed['id']}"
            trev = trimmed["revision"]
            fold_ticks = 5 * QUANTUM
            seed2 = client.post(tpath + "/edits", json={
                "request_id": "lcv-fold-seed", "expected_revision": trev,
                "commands": [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                    {"op": "asset.import", "asset_id": "a", "label": "底",
                     "probe_id": base_probe["id"], "verified": base_probe["verified"]},
                    {"op": "asset.import", "asset_id": "ly", "label": "层",
                     "probe_id": layer_probe["id"], "verified": layer_probe["verified"]},
                    {"op": "clip.add", "clip": {"id": "c", "asset_id": "a", "track_id": "v",
                                                "position_ticks": 0, "duration_ticks": TICKS,
                                                "animation_offset_ticks": fold_ticks}},
                    {"op": "clip.grade", "clip_id": "c", "grade": [layer_node(
                        keys=[{"property": "scale", "at_ticks": fold_ticks + 2 * QUANTUM,
                               "value": 1.5, "interpolation": "hold"}])]},
                ],
            })
            assert seed2.status_code == 200, seed2.text[:300]
            trev = seed2.json()["project"]["revision"]
            tclip = client.get(tpath).json()["clips"]["c"]
            folded = client.post(
                f"/v1/animation/layer_curve?property=scale&layer=0&quantum={QUANTUM}", json=tclip
            ).json()
            assert [k["at_ticks"] for k in folded["keys"]] == [2 * QUANTUM], folded["keys"]
            # 把那一个局部刻度原样写回去（加回 offset 一次），读回来还得是同一格——多折或不折都会漂
            offset2 = tclip.get("animation_offset_ticks") or 0
            back = [{
                "property": "scale", "at_ticks": k["at_ticks"] + offset2,
                "value": k["value"], "interpolation": "hold",
            } for k in folded["keys"]]
            write2 = client.post(tpath + "/edits", json={
                "request_id": "lcv-fold-write", "expected_revision": trev,
                "commands": [{"op": "clip.grade", "clip_id": "c",
                              "grade": [layer_node(keys=back)]}],
            })
            assert write2.status_code == 200, write2.text[:300]
            again = client.post(
                f"/v1/animation/layer_curve?property=scale&layer=0&quantum={QUANTUM}",
                json=client.get(tpath).json()["clips"]["c"],
            ).json()
            assert [k["at_ticks"] for k in again["keys"]] == [2 * QUANTUM], again["keys"]
            print(f"   刻度折一次：存 {fold_ticks + 2 * QUANTUM} 读回 {2 * QUANTUM}，往返不漂")

            # 6) 那一层被停用时不再是「第 0 层」：层的顺序只由一处数（与导出、清单同一份）
            disabled = client.post(path + "/edits", json={
                "request_id": "lcv-off", "expected_revision": before,
                "commands": [{"op": "clip.grade", "clip_id": "c", "grade": [dict(
                    layer_node(rotation=33.0), enabled=False)]}],
            })
            assert disabled.status_code == 200, disabled.text[:300]
            revision = disabled.json()["project"]["revision"]
            gone = curve_body("rotation")
            assert gone.status_code == 422, gone.text[:200]
            assert "0" in str(gone.json()["error"]["details"]["layers"]), gone.text[:200]
            assert LAYER_FIELDS[-1] == "rotation", LAYER_FIELDS
            assert LAYER_ROTATION_MAX == 180.0

            print("PASS: 那条读路由交回的就是窗表；五个数各有量程；往返不漂；"
                  "一枚针没有是一级平台阶；三种越界点名且不涨版本；停用那层不再是第 0 层")


if __name__ == "__main__":
    main()
