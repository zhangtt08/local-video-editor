"""1.164 遮罩可旋转：式子、图、拒绝，最后是真像素。

一条角度要在四处落地，任何一处各写各的红的是话、不是画面：
① 契约给矩形/椭圆的盒子一枚 `rotation`（±360°，屏幕角，正数顺时针，与画面旋转同一个读法），
   路径遮罩带角度点名拒收；
② 导出的 `alpha_expression` 把取样点绕遮罩中心转回去——各向异性的盒必须先折成同一个单位，
   所以式子里带画面高/宽之比（有画面框时是框的比值）；零角度那一支交出去的字节必须与 1.163
   逐字相同，否则这版就悄悄改了两年没动过的那一路；
③ 界面拿到的是引擎烘好的那张**整画面等比**图（`viewBox` 的比例就是画面的比例），它只做一件事：
   按引擎下发的中心曲线平移；
④ 真像素：同一段红画面只改角度，逐点与按定义独立写出的判定对得上，而且 +30° 的长轴必须朝
   屏幕下方歪、−45° 朝上——换符号就红。
"""

import struct
import subprocess
import tempfile
from math import atan2, cos, degrees, radians, sin
from pathlib import Path
from urllib.parse import unquote

from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentcut import contracts
from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import CreateProject, EditBatch, Project, ShapeMask
from agentcut.http_api import create_app
from agentcut.masks import alpha_expression, animated_mask_image, cover_svg_image, mask_image
from agentcut.media import MediaService
from agentcut.projects import ProjectStore
from agentcut.render import compile_render_plan

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
TOKEN = "maskrot-check-" + "t" * 48
HARD = {"shape": "rectangle", "center_x": 0.5, "center_y": 0.5, "width": 0.5, "height": 0.2}
# 1.163 之前那一路的原文，钉在这里而不是再算一遍：这一版不许动没转的那一支。
PLAIN_RECT = "lte(abs((X/W-(0.5))*2/(0.5)),1)*lte(abs((Y/H-(0.5))*2/(0.2)),1)"


def principal_axis(data: bytes, width: int, height: int) -> float:
    """红那块的主轴角（度，屏幕 y 向下、顺时针为正）。"""
    n = sxx = syy = sxy = 0
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            i = (y * width + x) * 3
            if data[i] > 150 and data[i + 1] < 90 and data[i + 2] < 90:
                n += 1
                sxx += x * x
                syy += y * y
                sxy += x * y
    if n < 40:
        return float("nan")
    mean_x = sum(
        x for y in range(0, height, 2) for x in range(0, width, 2)
        if data[(y * width + x) * 3] > 150 and data[(y * width + x) * 3 + 1] < 90
    ) / n
    mean_y = sum(
        y for y in range(0, height, 2) for x in range(0, width, 2)
        if data[(y * width + x) * 3] > 150 and data[(y * width + x) * 3 + 1] < 90
    ) / n
    cxx = sxx / n - mean_x * mean_x
    cyy = syy / n - mean_y * mean_y
    cxy = sxy / n - mean_x * mean_y
    return degrees(atan2(2 * cxy, cxx - cyy) / 2)


def main():
    # ① 契约
    assert ShapeMask().rotation == 0.0, ShapeMask()
    for angle in (-360.0, -45.0, 30.0, 360.0):
        assert ShapeMask(rotation=angle).rotation == angle, angle
    for bad in (360.1, -360.1, 400):
        try:
            ShapeMask(rotation=bad)
            raise AssertionError(f"角度 {bad} 竟然收了")
        except ValidationError:
            pass
    vertices = [{"x": 0.2, "y": 0.2}, {"x": 0.7, "y": 0.3}, {"x": 0.4, "y": 0.8}]
    try:
        ShapeMask(shape="path", vertices=vertices, rotation=20.0)
        raise AssertionError("路径遮罩带角度竟然收了")
    except ValidationError as error:
        assert "only a rectangle or ellipse mask can be rotated" in str(error), error
    print("   契约：默认 0°，±360° 收，超范围与路径带角度点名拒收")

    # ② 式子
    assert alpha_expression(ShapeMask(**HARD)) == PLAIN_RECT, alpha_expression(ShapeMask(**HARD))
    turned = alpha_expression(ShapeMask(**HARD, rotation=90.0))
    assert "+((Y/H)-(0.5))*(H/W)*1.000000000)" in turned, turned
    assert "-((X/W)-(0.5))*1.000000000)" in turned, turned
    assert "PI" not in turned and "sin(" not in turned, "角度该在引擎里就化成常数"
    framed = alpha_expression(ShapeMask(**HARD, rotation=30.0), None, (0.0, 30.0, 160.0, 90.0))
    assert "H/W" not in framed and "0.562500000" in framed, framed
    assert "0.866025404" in framed and "0.500000000" in framed, framed
    assert alpha_expression(ShapeMask(shape="ellipse", rotation=30.0)) != alpha_expression(
        ShapeMask(shape="ellipse")
    ), "带角度的式子与不带角度的一字未改——这一版什么都没转"
    assert alpha_expression(ShapeMask(**HARD, rotation=180.0, inverted=True)).startswith("(1-(")
    print("   式子：零角度原文未动，30°/90° 化成了常数，画面框那一档用框的比值")

    # ③ 图
    assert 'viewBox="0 0 100 100"' in unquote(mask_image(ShapeMask(**HARD), 320, 180))
    spun = unquote(mask_image(ShapeMask(**HARD, rotation=30.0), 320, 180))
    assert 'viewBox="0 0 1000.0000 562.5000"' in spun, spun[:160]
    assert 'transform="rotate(30.000000 500.0000 281.2500)"' in spun, spun[:400]
    unit = unquote(animated_mask_image(ShapeMask(**HARD, rotation=30.0), 320, 180))
    assert 'transform="rotate(30.000000 500.0000 281.2500)"' in unit, unit[:400]
    soft = unquote(cover_svg_image(ShapeMask(shape="ellipse", feather=0.4, rotation=45.0), 64, 36))
    assert "radialGradient" in soft and "rotate(45.000000" in soft, soft[:300]
    print("   图：旋转走整画面那张等比图，零角度走的还是老那一张单位图")

    with tempfile.TemporaryDirectory(prefix="agentcut-maskrot-") as temp:
        folder = Path(temp)
        media_dir = folder / "media"
        media_dir.mkdir()
        media = MediaService(folder / "db.sqlite3", [media_dir], folder / "cache", FFMPEG, FFPROBE)
        store = ProjectStore(media.db_path, media)
        p = store.create(CreateProject(request_id="new", name="maskrot")).project
        path = media_dir / "red.mp4"
        subprocess.run(
            [
                str(FFMPEG),
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=red:s=320x180:r=30:d=2",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=2",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                str(path),
            ],
            check=True,
            creationflags=0x08000000,
        )
        probe = media.import_file(str(path))
        seeded = store.mutate(
            p.id,
            EditBatch.model_validate(
                {
                    "request_id": "seed",
                    "expected_revision": 0,
                    "commands": [
                        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                        {
                            "op": "asset.import",
                            "asset_id": "a",
                            "label": "a",
                            "probe_id": probe.id,
                            "verified": probe.verified.model_dump(),
                        },
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "c",
                                "asset_id": "a",
                                "track_id": "v",
                                "position_ticks": 0,
                                "duration_ticks": 2 * T,
                            },
                        },
                        # 第二段是 1.163 那一路「粘贴属性」的落点：整枚遮罩要连着角度一起过去。
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "c2",
                                "asset_id": "a",
                                "track_id": "v",
                                "position_ticks": 2 * T,
                                "duration_ticks": T,
                            },
                        },
                    ],
                }
            ),
        ).project

        with TestClient(
            create_app(store.path, TOKEN, media),
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client:
            caps = client.get("/v1/capabilities").json()
            # ④ capabilities：钉字面量，不从 contracts 再算一遍
            assert caps["project_schema_version"] == 21, caps["project_schema_version"]
            assert caps["features"]["mask_rotation"] is True, caps["features"]
            assert caps["limits"]["mask_rotation_limit"] == 360.0, caps["limits"]
            assert caps["app_version"] == contracts.APP_VERSION == "1.165.0", caps["app_version"]

            head = {"revision": seeded.revision}

            def edit(commands, request_id, dry=False):
                body = {
                    "request_id": request_id,
                    "expected_revision": head["revision"],
                    "commands": commands,
                    "dry_run": dry,
                }
                return client.post(f"/v1/projects/{seeded.id}/edits", json=body)

            def mask_body(angle):
                return {"op": "clip.mask", "clip_id": "c", "mask": {**HARD, "rotation": angle}}

            written = edit([mask_body(30.0)], "angle-30")
            assert written.status_code == 200, written.text
            head["revision"] = written.json()["project"]["revision"]
            assert written.json()["project"]["clips"]["c"]["mask"]["rotation"] == 30.0

            too_much = edit([mask_body(361.0)], "over-range")
            assert too_much.status_code == 422, too_much.text
            assert client.get(f"/v1/projects/{seeded.id}").json()["revision"] == head["revision"]

            size_curve = edit(
                [
                    {
                        "op": "keyframe.set",
                        "clip_id": "c",
                        "keyframe": {"property": "mask_width", "at_ticks": 0, "value": 0.4},
                    }
                ],
                "size-curve",
            )
            assert size_curve.json()["error"]["code"] == "INVALID_MASK", size_curve.text
            assert "遮罩角度" in size_curve.json()["error"]["message"], size_curve.text
            after = client.get(f"/v1/projects/{seeded.id}").json()
            assert after["revision"] == head["revision"], "被拒的一笔把版本涨了"
            assert after["clips"]["c"]["mask"]["rotation"] == 30.0, after["clips"]["c"]["mask"]
            centre_curve = edit(
                [
                    {
                        "op": "keyframe.set",
                        "clip_id": "c",
                        "keyframe": {"property": "mask_x", "at_ticks": 0, "value": 0.45},
                    }
                ],
                "centre-curve",
            )
            assert centre_curve.status_code == 200, centre_curve.text
            head["revision"] = centre_curve.json()["project"]["revision"]
            print("   拒绝：宽/高曲线点名要人把角度转回 0°，中心曲线照写不误，版本没被顶上去")

            manifest = client.get(f"/v1/projects/{seeded.id}/preview-manifest").json()
            entry = manifest["clips"]["c"]
            assert sorted(entry["mask_curves"]) == ["mask_x"], sorted(entry["mask_curves"])
            unit_view = unquote(entry["mask_unit"])
            assert 'viewBox="0 0 1000.0000 562.5000"' in unit_view, unit_view[:160]
            assert "rotate(30.000000" in unit_view, unit_view[:300]
            preview = client.post(
                "/v1/mask/preview?frame_width=320&frame_height=180", json={**HARD, "rotation": 30.0}
            )
            assert preview.status_code == 200, preview.text
            assert "rotate(30.000000" in unquote(preview.json()["mask_image"]), preview.text
            print("   预览清单：下发的就是那张等比旋转图，界面只许平移")

            # 量像素之前把这枚中心针拔掉：留着它，盒子早就不在 (0.5,0.5) 上了，
            # 而下面那份按定义写的判定认的是画好的那个中心——针留着就是夹具自己说谎。
            unkey = edit(
                [{"op": "keyframe.remove", "clip_id": "c", "property": "mask_x", "at_ticks": 0}],
                "unkey",
            )
            assert unkey.status_code == 200, unkey.text
            assert not unkey.json()["project"]["clips"]["c"]["keyframes"], unkey.text
            head["revision"] = unkey.json()["project"]["revision"]

            # 1.163 那一路「粘贴属性」：整枚遮罩要连着角度一起落到那一段上，
            # 落完之后同一条限制照旧——转过的盒还是不能打宽/高曲线。
            planned = client.post(
                f"/v1/projects/{seeded.id}/clips/c/attribute-plan",
                json={
                    "request_id": "paste-ask",
                    "expected_revision": head["revision"],
                    "source_clip_id": "c",
                    "target_clip_ids": ["c2"],
                    "categories": ["mask"],
                },
            )
            assert planned.status_code == 200, planned.text
            commands = planned.json()["attribute_plan"]["commands"]
            turned = [c for c in commands if c.get("op") == "clip.mask"]
            assert [c["mask"]["rotation"] for c in turned] == [30.0], commands
            pasted = edit(commands, "paste-land")
            assert pasted.status_code == 200, pasted.text
            head["revision"] = pasted.json()["project"]["revision"]
            landed = pasted.json()["project"]["clips"]["c2"]["mask"]
            assert landed["rotation"] == 30.0 and landed["shape"] == "rectangle", landed
            second_refusal = edit(
                [
                    {
                        "op": "keyframe.set",
                        "clip_id": "c2",
                        "keyframe": {"property": "mask_height", "at_ticks": 0, "value": 0.3},
                    }
                ],
                "paste-curve",
            )
            assert second_refusal.json()["error"]["code"] == "INVALID_MASK", second_refusal.text
            print("   粘贴属性：整枚遮罩连着角度一起落进那一段，落完那条限制照旧拒")

            def shot(angle, request_id):
                step = edit([mask_body(angle)], request_id)
                assert step.status_code == 200, step.text
                head["revision"] = step.json()["project"]["revision"]
                response = client.get(
                    f"/v1/projects/{seeded.id}/frame?revision={head['revision']}&at_ticks={T}"
                )
                assert response.status_code == 200, response.text
                w, h = struct.unpack(">II", response.content[16:24])
                raw = subprocess.run(
                    [
                        str(FFMPEG),
                        "-v",
                        "error",
                        "-i",
                        "pipe:0",
                        "-f",
                        "rawvideo",
                        "-pix_fmt",
                        "rgb24",
                        "pipe:1",
                    ],
                    input=response.content,
                    capture_output=True,
                    check=True,
                    creationflags=0x08000000,
                ).stdout
                return {"w": w, "h": h, "raw": raw}

            def axes(fx, fy, angle, w, h):
                """取样点落回遮罩自己的两条轴上的偏移（像素），按定义算，不看引擎那份字符串。"""
                theta = radians(angle)
                px, py = (fx - 0.5) * w, (fy - 0.5) * h
                return px * cos(theta) + py * sin(theta), -px * sin(theta) + py * cos(theta)

            def inside(fx, fy, angle, w, h):
                ux, uy = axes(fx, fy, angle, w, h)
                return abs(ux) <= HARD["width"] * w / 2 and abs(uy) <= HARD["height"] * h / 2

            def clear(fx, fy, angle, w, h):
                """离边界不到 3 像素的那些点不判：那一个像素亮还是黑，geq 说了不算。"""
                ux, uy = axes(fx, fy, angle, w, h)
                gap = (
                    abs(abs(ux) - HARD["width"] * w / 2),
                    abs(abs(uy) - HARD["height"] * h / 2),
                )
                return min(gap) > 3.0

            def red(shot_of, fx, fy):
                w, h, raw = shot_of["w"], shot_of["h"], shot_of["raw"]
                i = (int(fy * h) * w + int(fx * w)) * 3
                return raw[i] > 150 and raw[i + 1] < 90 and raw[i + 2] < 90

            frames = {0.0: shot(0.0, "flat")}
            for angle, request_id in ((30.0, "flat-30"), (90.0, "flat-90"), (-45.0, "flat-m45")):
                frames[angle] = shot(angle, request_id)

            checked = 0
            turned_points = 0
            for angle, frame in frames.items():
                w, h = frame["w"], frame["h"]
                for fx in (0.26, 0.34, 0.42, 0.5, 0.58, 0.66, 0.74, 0.82):
                    for fy in (0.28, 0.4, 0.5, 0.6, 0.72):
                        if not (clear(fx, fy, angle, w, h) and clear(fx, fy, 0.0, w, h)):
                            continue
                        seen = "亮" if red(frame, fx, fy) else "黑"
                        want = "亮" if inside(fx, fy, angle, w, h) else "黑"
                        if seen != want:
                            raise AssertionError(
                                f"角度 {angle} 在 ({fx},{fy})：画面上{seen}，按定义该{want}"
                            )
                        checked += 1
                # 符号钉在「沿自己的长轴那一点亮、它的镜像不亮」上：+30° 朝屏幕下方斜，−45° 朝上；
                # 转成 90° 是另一种不对称——原来朝外的长轴那头换成朝 y 才亮。两条都是换符号就红。
                flat = frames[0.0]
                if angle in (30.0, -45.0):
                    reach = 0.9 * HARD["width"] * w / 2
                    theta = radians(angle)
                    along = (0.5 + reach * cos(theta) / w, 0.5 + reach * sin(theta) / h)
                    across = (0.5 + reach * cos(theta) / w, 0.5 - reach * sin(theta) / h)
                    assert inside(*along, angle, w, h) and clear(*along, angle, w, h), along
                    assert not inside(*across, angle, w, h), across
                    assert not inside(*along, 0.0, w, h), "转过的这点在没转的那格也是亮的"
                    assert red(frame, *along), f"角度 {angle}：长轴那端按定义是亮的，画面上却是黑的"
                    assert not red(frame, *across), f"角度 {angle}：镜像那点画面上亮了，符号反了"
                    assert not red(flat, *along), "没转的那格居然也亮着同一点"
                    turned_points += 1
                elif angle == 90.0:
                    up = (0.5, 0.5 + 0.9 * HARD["width"] * w / 2 / h)
                    assert inside(*up, 90.0, w, h) and clear(*up, 90.0, w, h), up
                    assert not inside(*up, 0.0, w, h)
                    assert red(frame, *up) and not red(flat, *up), "转 90° 之后长轴没换到竖的那头"
                    turned_points += 1
            assert checked > 60 and turned_points == 3, (checked, turned_points)
            print(f"   真像素：{checked} 个点与独立判定全对上，三档角度的长轴各自歪对了方向")

            # 1.165：角度可以打关键帧了，而两端执行的是同一份按帧对齐的窗表。
            turning = edit(
                [
                    {"op": "keyframe.set", "clip_id": "c",
                     "keyframe": {"property": "mask_rotation", "at_ticks": 0, "value": 0.0}},
                    {"op": "keyframe.set", "clip_id": "c",
                     "keyframe": {"property": "mask_rotation", "at_ticks": 2 * T, "value": 90.0}},
                ],
                "angle-curve",
            )
            assert turning.status_code == 200, turning.text
            head["revision"] = turning.json()["project"]["revision"]
            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["mask_rotation_curves"] is True, caps["features"]
            assert caps["limits"]["mask_rotation_schedule_segments"] == 12, caps["limits"]
            over = edit(
                [{"op": "keyframe.set", "clip_id": "c",
                  "keyframe": {"property": "mask_rotation", "at_ticks": T, "value": 400.0}}],
                "angle-over",
            )
            assert over.status_code == 422, over.text
            assert client.get(f"/v1/projects/{seeded.id}").json()["revision"] == head["revision"]

            # 1.165：轮廓遮罩没有盒可转。静态那一格 ShapeMask 早就拒了，
            # 曲线这一格同理由 validator 拒——界面把这一行摆出来，
            # 人按下去就是一条导出根本不执行的针。
            as_path = edit(
                [{"op": "clip.mask", "clip_id": "c2", "mask": {
                    "shape": "path", "center_x": 0.5, "center_y": 0.5,
                    "width": 0.5, "height": 0.2,
                    "vertices": [{"x": 0.25, "y": 0.25}, {"x": 0.75, "y": 0.3},
                                 {"x": 0.5, "y": 0.8}]}}],
                "path-mask",
            )
            assert as_path.status_code == 200, as_path.text
            head["revision"] = as_path.json()["project"]["revision"]
            path_angle = edit(
                [{"op": "keyframe.set", "clip_id": "c2",
                  "keyframe": {"property": "mask_rotation", "at_ticks": 0, "value": 20.0}}],
                "path-angle-curve",
            )
            assert path_angle.json()["error"]["code"] == "INVALID_MASK", path_angle.text
            assert "has no box to turn" in path_angle.json()["error"]["message"], path_angle.text
            kept = client.get(f"/v1/projects/{seeded.id}").json()["revision"]
            assert kept == head["revision"], "被拒的一笔把版本涨了"
            path_move = edit(
                [{"op": "keyframe.set", "clip_id": "c2",
                  "keyframe": {"property": "mask_y", "at_ticks": 0, "value": 0.55}}],
                "path-move-curve",
            )
            assert path_move.status_code == 200, path_move.text
            head["revision"] = path_move.json()["project"]["revision"]
            print("   拒绝：轮廓遮罩的角度针被拒、中心针照写，矩形那一路同一条针写得进去")

            stepped = client.get(f"/v1/projects/{seeded.id}/preview-manifest").json()["clips"]["c"]
            windows = stepped["mask_rotation_windows"]
            angles = [window["angle"] for window in windows]
            points_curve = stepped["mask_curves"]["mask_rotation"]
            assert len(windows) <= 12, windows
            assert angles == sorted(angles) and angles[-1] > angles[0], angles
            assert [point["easing"] for point in points_curve] == ["steps(1, end)"] * len(angles)
            assert [round(point["value"], 6) for point in points_curve] == [
                round(angle, 6) for angle in angles
            ], (points_curve, angles)
            sizes = [len(window["image"]) for window in windows]
            assert max(sizes) < 2048, sizes
            last = unquote(windows[-1]["image"])
            assert 'viewBox="0 0 1000.0000 562.5000"' in last, last[:120]
            assert f"rotate({angles[-1]:.6f} " in last, last[:220]
            print(f"   窗表：{len(windows)} 段、每段一张 {min(sizes)}..{max(sizes)} B 的等比图，"
                  f"预览清单下发的角度曲线就是这份阶梯（两端同一张表）")

            live = Project.model_validate(client.get(f"/v1/projects/{seeded.id}").json())
            plan = "\n".join(compile_render_plan(live, "h264-source-quality").filters)
            frame = live.settings.frame_ticks
            # 换窗用的是严格小于：一帧的 T 就是这一帧自己的起点，`lte` 会把边界那一帧留在旧窗里。
            assert "if(lte(" not in plan, plan[:200]
            assert "cos(PI/180*(if(lt(T," in plan, plan[:400]
            for window in windows[:-1]:
                # 换窗那一步落在那一帧的**中间**，不落在它的起点：一帧的 T 就是这一帧自己，
                # 拿打印出来的秒数去比，判的就只剩浮点数的最后一位。
                half = (window["to_ticks"] - frame // 2) / T
                assert f"{half:.12f}" in plan, (window, f"{half:.12f}")

            def axis_at(at: int) -> float:
                response = client.get(
                    f"/v1/projects/{seeded.id}/frame?revision={head['revision']}&at_ticks={at}"
                )
                assert response.status_code == 200, response.text
                width, height = struct.unpack(">II", response.content[16:24])
                raw = subprocess.run(
                    [str(FFMPEG), "-v", "error", "-i", "pipe:0", "-f", "rawvideo",
                     "-pix_fmt", "rgb24", "pipe:1"],
                    input=response.content, capture_output=True, check=True,
                    creationflags=0x08000000,
                ).stdout
                return principal_axis(raw, width, height)

            window_at = lambda at: next(  # noqa: E731
                window["angle"] for window in windows
                if window["from_ticks"] <= at < window["to_ticks"]
            )
            early, late = axis_at(T // 30), axis_at(T * 59 // 30)
            assert abs(early - window_at(T // 30)) <= 3.0, (early, window_at(T // 30))
            assert abs(late - window_at(T * 59 // 30)) <= 3.0, (late, window_at(T * 59 // 30))
            assert late - early > 30, (early, late)
            print(f"   真像素跟着阶梯走：开头主轴 {early:.1f}°、结尾 {late:.1f}°，"
                  f"与该刻那一段窗的角度对得上")

            # 边界那一格单独钉：换窗的第一帧必须已经吃新窗，前一帧还停在旧窗。
            # 装机复核抓到过一次「两端各差一格」——量两头都落在窗中间时看不出来。
            by_from = {window["from_ticks"]: window["angle"] for window in windows}
            edges = [t for t in {w["to_ticks"] for w in windows[:-1]} if t in by_from]
            edge = max(edges, key=lambda t: -abs(by_from[t] - 45.0))
            hold = next(w["angle"] for w in windows if w["to_ticks"] == edge)
            axis_edge, axis_hold = axis_at(edge), axis_at(edge - frame)
            assert abs(axis_edge - by_from[edge]) <= 3.0, (axis_edge, by_from[edge], hold)
            assert abs(axis_hold - hold) <= 3.0, (axis_hold, hold, by_from[edge])
            assert abs(axis_edge - axis_hold) >= 3.0, (axis_edge, axis_hold)
            print(f"   边界：第 {edge // frame} 帧已是 {by_from[edge]:.1f}°（前一帧 {hold:.1f}°），"
                  f"画面上量到 {axis_edge:.1f}°／{axis_hold:.1f}°")

    print("PASS: 遮罩角度在契约、式子、下发的图与真像素四路同指一件事，零角度那一路一字未改")


if __name__ == "__main__":
    main()
