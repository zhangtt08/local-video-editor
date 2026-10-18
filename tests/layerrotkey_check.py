"""层的转角进那张窗表（1.204）：同一层两窗各转各的，落的格子就是导出执行的那一格。

这一档只问一件事：**转角成了第五个能动的数**之后，两端还同不同意同一份窗表。
量的不是串里的字，是交付文件里的像素——因为「窗表切了两次、执行却只转了一个角度」这类错，
串看起来完全正常（`grep -c rotate` 数着还是两次），只有按帧读数才看得出来。

断的四件事：

1. 两窗两个角度：早一格（转角 0）带子是**左右**分深浅，晚一格（转角 90）带子是**上下**分深浅，
   而各自另一对方向必须相等——这正是 1.203 量过的方向（+90° 把左边送到上边）。
2. 阶梯的边：`layer_schedule` 交回的第一格值就是那枚针的值（不是段中点），所以在**段起点头一格**
   按 `lt()` 比秒，落的是那一个角度；段尾那一格还是旧角度。
3. 一处说法：那份名单五个数 == `layer_curve` 每窗那五个键 == 清单里每窗那一个转角 == 串里
   `rotate=a=` 带的那一个数 == capabilities 那份名单 == 界面那张名字表。量到的一条与猜的不同：
   **0° 那一窗不出现 rotate**（静态那条规矩在逐窗这一腿同样说话），所以次数是 1 而不是窗数 2——
   这一条本来是我自己写错的期望，被真实串否掉了。
4. 值域与静态那一条同一条带（±180），越界两路写入都拒；一枚针钉在静态同一个值上时，
   把 `:enable` 摘掉之后与「没有针」逐字节相同（升级不许改画面）。
"""

import re
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.animation import LAYER_KEY_PROPS, layer_curve, layer_schedule
from agentcut.contracts import LAYER_ROTATION_MAX, Project
from agentcut.contracts import TIMEBASE as T
from agentcut.grade import layer_stages
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
FRAMES = 30


def run(args, timeout=900):
    return subprocess.run(
        [str(a) for a in args], capture_output=True, check=True, timeout=timeout,
        creationflags=0x08000000,
    )


def plates(folder: Path) -> tuple[Path, Path]:
    base = folder / "base.png"
    run([FFMPEG, "-v", "error", "-y", "-f", "lavfi",
         "-i", f"color=c=0x{BASE_GREY:02x}{BASE_GREY:02x}{BASE_GREY:02x}"
                f":s={SRC_W}x{SRC_H}:r=30:d=1",
         "-frames:v", "1", str(base)])
    band = folder / "band.png"
    dark = f"color=c=0x{BAND_DARK:02x}{BAND_DARK:02x}{BAND_DARK:02x}"
    light = f"color=c=0x{BAND_LIGHT:02x}{BAND_LIGHT:02x}{BAND_LIGHT:02x}"
    run([FFMPEG, "-v", "error", "-y",
         "-f", "lavfi", "-i", f"{dark}:s={SRC_W // 2}x{SRC_H}:r=30",
         "-f", "lavfi", "-i", f"{light}:s={SRC_W // 2}x{SRC_H}:r=30",
         "-filter_complex", "[0:v][1:v]hstack=inputs=2", "-frames:v", "1", str(band)])
    return base, band


def grey_at(path: Path, fx: float, fy: float, ss: float) -> int:
    """交付文件在某一秒、某一处的灰度：整帧解码后按分数位置取（这台 crop 不可靠）。"""
    raw = run([FFMPEG, "-v", "error", "-ss", f"{ss:.3f}", "-i", str(path),
               "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]).stdout
    assert len(raw) >= FRAME_W * FRAME_H * 3, f"{path.name} 解出来 {len(raw)} 字节"
    row = raw[int(FRAME_H * fy) * FRAME_W * 3 : (int(FRAME_H * fy) + 1) * FRAME_W * 3]
    return row[int(FRAME_W * fx) * 3]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-lyk-") as scratch:
        folder = Path(scratch)
        media = MediaService(folder / "lyk-db.sqlite3", [folder], folder / "lyk-cache",
                             FFMPEG, FFPROBE)
        exports = folder / "exports"
        runtime = JobRuntime(folder / "lyk-api.sqlite3", FFMPEG, exports, [exports, folder])
        runtime.ensure_worker()
        token = "lykcheck" + "e" * 55
        app = create_app(folder / "lyk-api.sqlite3", token, media=media, jobs=runtime)
        with TestClient(app, base_url="http://127.0.0.1",
                        headers={"Authorization": f"Bearer {token}"}) as client:
            base, band = plates(folder)
            base_probe = client.post("/v1/media/import", json={"path": str(base)}).json()
            band_probe = client.post("/v1/media/import", json={"path": str(band)}).json()
            revision: dict = {}

            def render(project: str, tag: str, ss: float = 0.4) -> Path:
                stamp = f"{round(ss * 1000):04d}"  # request_id 不许有点：那是个 id 词法，不是数
                answer = client.post(project + "/renders", json={
                    "request_id": f"{tag}-{stamp}", "expected_revision": revision[project],
                    "preset_id": PRESET, "filename": f"{tag}-{stamp}.mp4", "fit": "stretch",
                })
                # 拒绝的正文必须先打出来：上一轮就是把「引擎回 422」读成了 KeyError，证据丢了。
                assert answer.status_code == 200, answer.text[:400]
                job = answer.json()["job"]
                done = job
                for _ in range(900):
                    done = client.get(f"/v1/jobs/{job['id']}").json()["job"]
                    if done["status"] in {"succeeded", "failed", "cancelled"}:
                        break
                assert done["status"] == "succeeded", done
                return Path(done["output_path"])

            def seed(name: str, request: str) -> str:
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
                        {"op": "clip.add", "clip": {"id": "c", "asset_id": "a", "track_id": "v",
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
                    "request_id": tag, "expected_revision": revision[path],
                    "commands": [command],
                })

            def key(prop: str, frame: int, value: float):
                return {"property": prop, "at_ticks": frame * T // 30, "value": value,
                        "interpolation": "hold"}

            def layer(keys=None, rotation=0.0, mode="normal", asset="bd"):
                return {"kind": "layer", "asset_id": asset, "mode": mode, "mix": 1.0,
                        "offset_x": 0.0, "offset_y": 0.0, "scale": 1.0, "rotation": rotation,
                        "keys": keys or [], "enabled": True}

            def graph(path: str) -> str:
                doc = client.get(path).json()
                return "\n".join(compile_render_plan(Project(**doc), PRESET,
                                                     fit="stretch").filters)

            # 1) 两窗两个角度：早一格左右分深浅，晚一格上下分深浅，各自另一对方向必须相等。
            path = seed("转两回", "lyk-two")
            keys = [key("rotation", 0, 0.0), key("rotation", FRAMES // 2, 90.0)]
            answer = write(path, [layer(keys=keys)], tag="lyk-two-w")
            assert answer.status_code == 200, answer.text
            revision[path] = answer.json()["project"]["revision"]
            clip = Project(**client.get(path).json()).clips["c"]
            table = layer_schedule(clip, T // 30)[0]
            assert len(table) == 2, table
            assert [round(w["value"][4]) for w in table] == [0, 90], table
            early = render(path, "lyk-early", 0.400)
            late = render(path, "lyk-late", 0.900)
            # 0.4s 在第一格（转角 0）：左右分深浅，上下同一档
            left = grey_at(early, 0.25, 0.5, 0.400)
            right = grey_at(early, 0.75, 0.5, 0.400)
            up = grey_at(early, 0.25, 0.2, 0.400)
            down = grey_at(early, 0.25, 0.8, 0.400)
            assert right - left > 60, (left, right)
            assert abs(up - down) <= 2, (up, down)
            # 0.9s 在第二格（转角 90）：上下分深浅，左右同一档
            left2 = grey_at(late, 0.25, 0.2, 0.900)
            right2 = grey_at(late, 0.75, 0.2, 0.900)
            top2 = grey_at(late, 0.5, 0.2, 0.900)
            bot2 = grey_at(late, 0.5, 0.8, 0.900)
            assert bot2 - top2 > 60, (top2, bot2)
            assert abs(left2 - right2) <= 2, (left2, right2)
            print(f"   两窗两个角度：0.4s 左 {left} 右 {right}（上 {up} 下 {down} 同档）、"
                  f"0.9s 上 {top2} 下 {bot2}（左 {left2} 右 {right2} 同档）")

            # 2) 阶梯的边：段起点头一格执行的就是那枚针的值，段尾最后一格还是旧角度。
            #    （两边都离边界一帧，避免 `-ss` 落在哪一帧的浮点抖；若编译用的是段**中点**的值，
            #    0.533 这一格就还是旧角度——这一条因此是能红得起来的。）
            edge = render(path, "lyk-edge", 0.533)
            before = render(path, "lyk-before", 0.466)
            step = grey_at(edge, 0.5, 0.8, 0.533) - grey_at(edge, 0.5, 0.2, 0.533)
            assert step > 60, ("段起点头一格没换角度", step)
            held = grey_at(before, 0.75, 0.5, 0.466) - grey_at(before, 0.25, 0.5, 0.466)
            assert held > 60, ("段尾提前换了", held)

            # 3) 一处说法：五个数、那张名字表、串里那几个角度、清单那几行，全对得上。
            text = graph(path)
            # 量到的事实，不是我原先猜的「两窗就两次 rotate」：0° 那一窗走的是**不转**那一步
            # （1.203 钉过的静态规矩：转角为 0 就不出现 rotate）。所以串里只出现一次 rotate，
            # 而且带的那一个数是 90——mask 的次数必须与它一致，不然就是「转了却没按 alpha 合」。
            assert text.count("rotate=a=") == 1, text[:300]
            assert "rotate=a='90.0*PI/180'" in text, text[:300]
            assert "rotate=a='0.0*PI/180'" not in text, "0° 那一窗也被转了：静态那条腿被走上"
            assert text.count("maskedmerge") == 1, text[:300]
            assert LAYER_KEY_PROPS == ("offset_x", "offset_y", "scale", "mix", "rotation")
            curve = layer_curve(clip, table)
            assert set(curve[0]) == {"offset", "easing", "offset_x", "offset_y", "scale",
                                     "mix", "rotation"}, curve[0]
            assert [w["rotation"] for w in curve] == [0.0, 90.0], curve
            row = client.get(path + "/preview-manifest").json()["clips"]["c"]["layer"][0]
            assert [w["rotation"] for w in row["windows"]] == [w["value"][4] for w in table], row
            caps = client.get("/v1/capabilities").json()
            assert "rotation" in caps["grade_limits"]["layer_key_props"], caps["grade_limits"]
            assert caps["features"]["layer_rotation"] is True
            assert layer_stages(clip.color)[0]["rotation"] == 0.0, "静态那一个数被针改了"

            # 4) 值域与静态同一条带，越界两路都拒；拒了不涨版本。
            before_rev = revision[path]
            for value in (LAYER_ROTATION_MAX + 1.0, -(LAYER_ROTATION_MAX + 1.0)):
                for op in ("clip.grade", "clip.color"):
                    refused = write(path, [layer(keys=[key("rotation", 3, value)])], op=op,
                                    tag=f"lyk-over-{abs(value):.0f}-{op[5:]}")
                    assert refused.status_code == 422, refused.text[:200]
                    assert "rotation" in refused.text, refused.text[:200]
            assert client.get(path).json()["revision"] == before_rev, "拒绝涨了版本"

            # 5) 一枚针钉在静态同一个角度上：摘掉 `:enable` 之后与「没有针」逐字节相同。
            still = seed("一枚钉在静态值", "lyk-held")
            answer = write(still, [layer(rotation=45.0)], tag="lyk-held-static")
            assert answer.status_code == 200, answer.text
            revision[still] = answer.json()["project"]["revision"]
            bare = graph(still)
            answer = write(still, [layer(rotation=45.0, keys=[key("rotation", 0, 45.0)])],
                           tag="lyk-held-key")
            assert answer.status_code == 200, answer.text
            revision[still] = answer.json()["project"]["revision"]
            pinned = graph(still)
            # 一枚针自己就是一格窗，那一格覆盖整段：静态那条腿本来就不带 `enable`，
            # 所以这里把「有没有 enable」这件事交给正则抹平，只比那一只转过去的那一步。
            stripped = re.sub(r":enable='between\(t,[^)]*\)'", "", pinned)
            assert stripped == bare, (pinned[:200], bare[:200])
            print("   钉在静态同一个值的针：摘掉 enable 与没有针逐字节相同")

            print("PASS: 转角是那张窗表上的第五个数——两窗各转各的、段起点头一格就换、"
                  "五个数一处说法、越界两路都拒、钉在静态值不改画面")


if __name__ == "__main__":
    main()
