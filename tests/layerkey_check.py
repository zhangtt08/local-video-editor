"""第二路画面自己那几枚针（1.192）：那一层在成片里真的挪了位置，才叫按窗动。

这一档不重跑八种混合方式——那是 `tests/layer_check.py` 的事，它一个字没改仍然全绿。这里断的是
**位置随时间换**这一件事，而且期望值由两处自己量出来的端点现算，不从产品 import：

1. 端点：带子那张图单独交付时左半与右半各是几（缩放与 yuv 往返都在里面）、底片单独交付是几。
2. 两窗交付：前半那一格，层盖住的那一段读到的是带子那半，画面另一侧逐字节等于底片；
   后半那一格反过来。`blend`/`overlay` 的 `enable` 若不真的按时间生效，这两格会是同一张图。
3. 一处说法：`animation.layer_schedule` == 监视器清单里那一行的 `windows` == 编译串里
   那几次 `overlay:enable`，段数不超过引擎自己下发的 `limits.layer_schedule_segments`。
4. 两腿同一个算法：一枚针（整段同值）时，走多窗那条腿与走静态那条腿交回的矩形必须是同一组数。
5. 三条拒绝各点名、两条写入路都问（`clip.grade` 与 `clip.color`），拒绝不涨 revision。
6. 老工程：v23 那份载荷里根本没有 `keys`，读进来与 `keys: []` 编译出的串逐字节相同。
"""

import re
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut import contracts
from agentcut.animation import layer_curve, layer_schedule
from agentcut.contracts import LAYER_KEY_LIMIT, LAYER_SCHEDULE_MAX, Project
from agentcut.contracts import TIMEBASE as T
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
BASE_GREY = 0x80
BAND_DARK, BAND_LIGHT = 0x40, 0xC0
FRAMES = 30  # 这一档种下去的就是 1 秒 30 帧


def run(args, timeout=900):
    return subprocess.run(
        [str(a) for a in args], capture_output=True, check=True, timeout=timeout,
        creationflags=0x08000000,
    )


def band_plate(folder: Path) -> Path:
    target = folder / "band.png"
    dark = f"color=c=0x{BAND_DARK:02x}{BAND_DARK:02x}{BAND_DARK:02x}"
    light = f"color=c=0x{BAND_LIGHT:02x}{BAND_LIGHT:02x}{BAND_LIGHT:02x}"
    run([
        FFMPEG, "-v", "error", "-y",
        "-f", "lavfi", "-i", f"{dark}:s={SRC_W // 2}x{SRC_H}:r=30",
        "-f", "lavfi", "-i", f"{light}:s={SRC_W // 2}x{SRC_H}:r=30",
        "-filter_complex", "[0:v][1:v]hstack=inputs=2", "-frames:v", "1", str(target),
    ])
    return target


def grey_at(path: Path, at: float, fx: float, fy: float = 0.5) -> int:
    """交付文件里某一帧某一点的灰度：整帧解码后按分数位置取（这台 FFmpeg 的 crop 不可靠）。"""
    raw = run([
        FFMPEG, "-v", "error", "-ss", f"{at:.3f}", "-i", str(path),
        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]).stdout
    assert len(raw) >= FRAME_W * FRAME_H * 3, f"{path.name} 解出来 {len(raw)} 字节"
    row = raw[int(FRAME_H * fy) * FRAME_W * 3 : (int(FRAME_H * fy) + 1) * FRAME_W * 3]
    return row[int(FRAME_W * fx) * 3]


def main() -> None:  # noqa: C901 - 一档门禁按节读，比拆成十个互相递状态的函数清楚
    with tempfile.TemporaryDirectory(prefix="agentcut-lyk-") as scratch:
        folder = Path(scratch)
        media = MediaService(
            folder / "lyk-db.sqlite3", [folder], folder / "lyk-cache", FFMPEG, FFPROBE
        )
        exports = folder / "exports"
        runtime = JobRuntime(folder / "lyk-api.sqlite3", FFMPEG, exports, [exports, folder])
        runtime.ensure_worker()
        token = "lykcheck" + "e" * 56
        app = create_app(folder / "lyk-api.sqlite3", token, media=media, jobs=runtime)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            base = folder / "base.png"
            run([
                FFMPEG, "-v", "error", "-y", "-f", "lavfi",
                "-i", f"color=c=0x{BASE_GREY:02x}{BASE_GREY:02x}{BASE_GREY:02x}"
                      f":s={SRC_W}x{SRC_H}:r=30:d=1",
                "-frames:v", "1", str(base),
            ])
            band = band_plate(folder)
            base_probe = client.post("/v1/media/import", json={"path": str(base)}).json()
            band_probe = client.post("/v1/media/import", json={"path": str(band)}).json()

            revision: dict = {}

            def render(project: str, tag: str) -> Path:
                job = client.post(project + "/renders", json={
                    "request_id": f"{tag}-render", "expected_revision": revision[project],
                    "preset_id": PRESET, "filename": f"{tag}.mp4", "fit": "stretch",
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
                        {"op": "asset.import", "asset_id": "bd", "label": "带",
                         "probe_id": band_probe["id"], "verified": band_probe["verified"]},
                        {"op": "clip.add", "clip": {"id": "c", "asset_id": asset, "track_id": "v",
                                                    "position_ticks": 0,
                                                    "duration_ticks": FRAMES * T // 30}},
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

            def key(prop: str, frame: int, value: float):
                return {"property": prop, "at_ticks": frame * T // 30, "value": value,
                        "interpolation": "hold"}

            def layer(keys=None, offset_x=0.0, scale=1.0, mode="normal", asset="bd"):
                return {"kind": "layer", "asset_id": asset, "mode": mode, "mix": 1.0,
                        "offset_x": offset_x, "offset_y": 0.0, "scale": scale,
                        "keys": keys or [], "enabled": True}

            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["layer_keyframes"] is True
            assert caps["limits"]["layer_key_limit"] == LAYER_KEY_LIMIT
            assert caps["limits"]["layer_schedule_segments"] == LAYER_SCHEDULE_MAX
            assert caps["grade_limits"]["layer_key_props"] == ["offset_x", "offset_y", "scale"]

            # 1) 端点：带子自己交付时左右两半各是几、底片自己是几
            band_path = seed("带", "bd", "lyk-band")
            band_file = render(band_path, "lyk-band")
            dark_seen = grey_at(band_file, 0.4, 0.12)
            light_seen = grey_at(band_file, 0.4, 0.875)
            base_path = seed("底", "a", "lyk-base")
            base_seen = grey_at(render(base_path, "lyk-base"), 0.4, 0.12)
            assert dark_seen != light_seen != base_seen, (dark_seen, light_seen, base_seen)
            print(f"   端点：带子左半 {dark_seen}、右半 {light_seen}、底片 {base_seen}")

            # 2) 两窗交付：前半盖左边、后半盖右边，两侧各自与底片相同。
            #    盖住那一片读到的是带子的**哪一半**由 1.190 那条裁法决定（层先按完整尺寸缩好，
            #    再裁出与画面相交那一片）：offset_x=-0.5 时层心挪到画面左外面，露出的正是右半；
            #    offset_x=+0.5 时相反。上一版预期写反了，是这一格真量出来的。
            moved = [key("offset_x", 0, -0.5), key("offset_x", 15, 0.5)]
            path = seed("动", "a", "lyk-move")
            answer = write(path, [layer(moved)], tag="lyk-move-w")
            assert answer.status_code == 200, answer.text
            revision[path] = answer.json()["project"]["revision"]
            movie = render(path, "lyk-move")
            early_left = grey_at(movie, 0.20, 0.12)
            early_right = grey_at(movie, 0.20, 0.875)
            late_left = grey_at(movie, 0.80, 0.12)
            late_right = grey_at(movie, 0.80, 0.875)
            near = lambda a, b: abs(a - b) <= 6  # noqa: E731 - 这把尺的抖就是几格
            assert near(early_left, light_seen), (early_left, light_seen)
            assert near(early_right, base_seen), (early_right, base_seen)
            assert near(late_left, base_seen), (late_left, base_seen)
            assert near(late_right, dark_seen), (late_right, dark_seen)
            assert early_left != late_left and early_right != late_right, "两格是同一张图"
            print(f"   两窗：前半 [{early_left},{early_right}]、"
                  f"后半 [{late_left},{late_right}]")

            # 3) 一处说法：窗表 == 清单里那一行的 windows == 编译串里那几次 overlay:enable
            document = client.get(path).json()
            row = client.get(path + "/preview-manifest").json()["clips"]["c"]["layer"][0]
            project = Project(**document)
            live = project.clips["c"]
            table = layer_schedule(live, T // 30)[0]
            assert row["windows"] == layer_curve(live, table), (row["windows"], table)
            assert len(table) == 2, table
            assert [window["value"][0] for window in table] == [-0.5, 0.5], table
            plan = compile_render_plan(project, PRESET, fit="stretch")
            text = "\n".join(plan.filters)
            assert text.count("overlay=x=") == 2 and text.count("enable='between(") == 6, text
            assert "[lysp" in text and "split=2" in text, text
            # 两次 overlay 落在哪两个 x 由交付帧宽 1920 现算：这一层 scale 1.0（铺满画面框），
            # offset_x ∓0.5 把层心挪到边外半幅，于是可见那一片宽 960，一窗在 x=0、一窗在 x=960。
            # x=0 那一窗裁的是层的**右**半（crop 起点 960）——1.190 那条「先按完整尺寸缩好、再裁
            # 出与画面相交那一片」在按窗动的时候还是同一句话，两半会随位置换边。
            spots = sorted(int(value) for value in re.findall(r"overlay=x=(-?\d+)", text))
            assert spots == [0, 960], (spots, text[:400])
            assert "crop=960:1080:960:0" in text, text[:400]

            # 4) 两腿同一个算法：一枚针（整段同值）与静态那一个数，交回的矩形必须是一组数
            single = [key("offset_x", 0, -0.5)]
            one_path = seed("单窗", "a", "lyk-one")
            answer = write(one_path, [layer(single)], tag="lyk-one-w")
            assert answer.status_code == 200, answer.text
            revision[one_path] = answer.json()["project"]["revision"]
            static_path = seed("静态", "a", "lyk-static")
            answer = write(static_path, [layer(None, offset_x=-0.5)], tag="lyk-static-w")
            assert answer.status_code == 200, answer.text
            revision[static_path] = answer.json()["project"]["revision"]

            def geometry(where: str) -> list[str]:
                held = Project(**client.get(where).json())
                built = "\n".join(compile_render_plan(held, PRESET, fit="stretch").filters)
                return [
                    token_piece
                    for line in built.splitlines()
                    if "overlay=x=" in line
                    for token_piece in [line.split("overlay=")[1].split(":enable")[0]]
                ]

            assert geometry(one_path) == geometry(static_path), (
                geometry(one_path), geometry(static_path)
            )
            print(f"   两腿同一组数：{geometry(static_path)}")

            # 5) 三条拒绝：越界、撞针、超额，两条写入路都点名，且拒绝不涨 revision
            before = revision[path]
            duration = FRAMES * T // 30
            refusals = [
                ("LAYER_KEY_RANGE", [layer([key("offset_x", FRAMES + 5, 0.2)])]),
                ("LAYER_KEY_CLASH", [layer([key("scale", 3, 0.5), key("scale", 3, 0.8)])]),
                ("LAYER_KEY_LIMIT", [
                    layer([key("offset_x", frame, 0.02 * frame)
                           for frame in range(1, LAYER_KEY_LIMIT + 2)])
                ]),
            ]
            for code, grade in refusals:
                for op in ("clip.grade", "clip.color"):
                    answer = write(path, grade, op=op, tag=f"lyk-{code}-{op[5:]}")
                    assert answer.status_code == 422, (code, op, answer.text[:160])
                    body = answer.json()["error"]
                    assert body["code"] == code, (code, body)
                    assert duration > 0 and body["details"], body
            assert client.get(path).json()["revision"] == before, "拒绝涨了版本"

            # 6) 老工程：v23 那份载荷里根本没有 `keys` 这一格，读进来就是空表，而且编译出的串
            #    与「明确给了空表」逐字节相同——升级不许改动画面的一个像素。
            legacy_doc = client.get(static_path).json()
            stored = "\n".join(
                compile_render_plan(Project(**legacy_doc), PRESET, fit="stretch").filters
            )
            for node in legacy_doc["clips"]["c"]["color"]["grade"]:
                node.pop("keys", None)
            legacy_doc["schema_version"] = 23
            legacy = Project(**legacy_doc)
            needle = legacy.clips["c"].color.grade[0]
            assert isinstance(needle, contracts.GradeLayer) and needle.keys == [], needle
            assert contracts.GradeLayer(**needle.model_dump(exclude={"keys"})) == needle
            assert "\n".join(
                compile_render_plan(legacy, PRESET, fit="stretch").filters
            ) == stored, "keys 缺席的那份读出来换了串"

            # 7) 针多不等于窗多，而天花板真的会咬：15 枚互不相同的针落在 30 帧上，
            #    `frame_windows` 只能交回 `limits.layer_schedule_segments` 那几段（4 帧一段）。
            crowd = [key("offset_x", frame, -0.5 + frame / 60) for frame in range(0, 30, 2)]
            busy = seed("挤", "a", "lyk-crowd")
            answer = write(busy, [layer(crowd)], tag="lyk-crowd-w")
            assert answer.status_code == 200, answer.text
            revision[busy] = answer.json()["project"]["revision"]
            busy_doc = client.get(busy).json()
            busy_clip = Project(**busy_doc).clips["c"]
            steps = layer_schedule(busy_clip, T // 30)[0]
            assert len(crowd) == 15, len(crowd)
            assert len(steps) == LAYER_SCHEDULE_MAX, (len(steps), LAYER_SCHEDULE_MAX)
            assert len(steps) != len(crowd), "窗数等于针数，那切段这一条就没跑"
            manifest = client.get(busy + "/preview-manifest").json()["clips"]["c"]["layer"][0]
            assert manifest["windows"] == layer_curve(busy_clip, steps)
            print(f"   {len(crowd)} 枚针下发 {len(steps)} 窗（上限 {LAYER_SCHEDULE_MAX}）")

            print(
                "PASS: 那一层在两格里各盖了自己那一片、清单==窗表==编译串、"
                "两腿同一组数、三条拒绝各点名两路都问、keys 缺席读回相同"
            )


if __name__ == "__main__":
    main()
