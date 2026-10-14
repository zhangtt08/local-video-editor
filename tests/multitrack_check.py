"""1.157 的多目标遮罩跟踪：一组目标一次跑完，各自的账分别成立。

这里判的四件事，每一件都是「跑通了」看不出来的：
- 同一段窗口的多个目标只解码一次（回复里的 `decoded_passes`），不是每人把画面重读一遍；
- 每个目标各按自己片段的曲线预算与 `merge` 收短，一个装不下就整组点名拒绝，什么都没写、版本不涨；
- 整组落进一个批次：只涨一个版本，撤销一步整批退回；
- 段数上限只活在契约里，界面与 capabilities 都从它下来，没有第二个写死的数。

夹具是一块 320x180 的板子、两个反向行走的方块（各占一行）。先单独把两个盒子跟一遍并和解析真值比，
确认画面里确实有两个可分辨的主体——否则后面任何「跟错了」都会被我读成引擎的缺陷。
"""

import re
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import (
    TRACK_TARGET_LIMIT,
    FrameRate,
    MaskTrackRequest,
    MaskTrackTarget,
)
from agentcut.http_api import create_app
from agentcut.media import MediaService
from agentcut.timeline import CLIP_KEYFRAME_LIMIT
from agentcut.tracking import analyse_window, follow_window

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
WIDTH, HEIGHT, FPS, SIZE = 320, 180, 30, 22
SECONDS = 2
FRAMES = SECONDS * FPS
FRAME_TICKS = T // FPS
CLIP_TICKS = FRAMES * FRAME_TICKS
A_X0, A_Y, B_X0, B_Y = 40, 54, 250, 112
SPEED = 90  # px/s：两个主体朝相反方向走，两条路径不可能是同一个模板的两次读数
BOX = (0.16, 0.24)
TRUTHS = {"ca": (A_X0, A_Y, 1), "cb": (B_X0, B_Y, -1)}


def truth(at: float, left: int, top: int, sign: int) -> tuple[float, float]:
    return (left + sign * SPEED * at + SIZE / 2) / WIDTH, (top + SIZE / 2) / HEIGHT


def mask_at(left: int, top: int, sign: int) -> dict:
    centre_x, centre_y = truth(0.0, left, top, sign)
    return {
        "shape": "ellipse", "center_x": centre_x, "center_y": centre_y,
        "width": BOX[0], "height": BOX[1], "feather": 0.0, "inverted": False,
    }


def render_plate(source: Path) -> None:
    """两个方块各由一路 `overlay` 推着走：`drawbox` 的 x 不按帧重算，画出来是两块死的板子。

    这是先量过的：同一句 `drawbox=x=…t` 会让跟踪在第一帧就跟丢，夹具自己不说谎，后面的判据才有意义。
    """
    argv = [
        str(FFMPEG), "-v", "error", "-y",
        "-f", "lavfi", "-i", f"color=c=0x181818:s={WIDTH}x{HEIGHT}:r={FPS}",
        "-f", "lavfi", "-i", f"color=c=white:s={SIZE}x{SIZE}:r={FPS}",
        "-f", "lavfi", "-i", f"color=c=0xd0d0d0:s={SIZE}x{SIZE}:r={FPS}",
        "-filter_complex",
        f"[0:v][1:v]overlay=x={A_X0}+{SPEED}*t:y={A_Y}:shortest=1[b];"
        f"[b][2:v]overlay=x={B_X0}-{SPEED}*t:y={B_Y}:shortest=1,format=yuv420p[v]",
        "-map", "[v]", "-t", str(SECONDS), "-c:v", "libx264", "-preset", "ultrafast", str(source),
    ]
    done = subprocess.run(argv, capture_output=True, check=False)
    assert done.returncode == 0, done.stderr[-600:].decode(errors="replace")


def group(clip_id: str, frames: int = FRAMES, **target) -> dict:
    return {"clip_id": clip_id, "frames": frames, **target}


def fixture_suite(folder: Path) -> None:
    """先证明夹具自己不说谎：两块反向的板子，各自都跟得住。"""
    source = folder / "plate.mp4"
    render_plate(source)
    width, decoded = analyse_window(
        FFMPEG, source, WIDTH, HEIGHT, FrameRate(), 0, FRAME_TICKS, FRAMES
    )
    assert len(decoded) == FRAMES, f"the plate decoded {len(decoded)} of {FRAMES} frames"
    worst_all, walks = 0.0, {}
    for clip_id, (left, top, sign) in TRUTHS.items():
        centre_x, centre_y = truth(0.0, left, top, sign)
        result = follow_window(
            decoded, width, (centre_x, centre_y, BOX[0], BOX[1]), 10, FrameRate(), FRAME_TICKS
        )
        worst = max(
            abs(point["mask_x"] - truth(index / FPS, left, top, sign)[0])
            + abs(point["mask_y"] - truth(index / FPS, left, top, sign)[1])
            for index, point in enumerate(result["points"])
        )
        assert worst < 0.05, f"{clip_id}: off its own truth by {worst:.4f}"
        assert result["lost_at_ticks"] is None, (clip_id, result["lost_at_ticks"])
        worst_all = max(worst_all, worst)
        walks[clip_id] = result["points"][-1]["mask_x"] - result["points"][0]["mask_x"]
    assert walks["ca"] > 0.2 and walks["cb"] < -0.2, walks
    print(
        f"   夹具：两块 {SIZE}px 的方板在 {WIDTH}px 画面上反向走，A 走过 {walks['ca']:.3f} 幅宽、"
        f"B 走过 {walks['cb']:.3f} 幅宽，各自跟 {FRAMES} 帧、最差偏差 {worst_all:.4f}"
    )


def seed(client: TestClient, path: str, probe: dict) -> int:
    revision = client.get(path).json()["revision"]
    commands = [
        {"op": "track.add", "track": {"id": "v1", "kind": "video", "name": "v1"}},
        {"op": "track.add", "track": {"id": "v2", "kind": "video", "name": "v2"}},
        {
            "op": "asset.import", "asset_id": "a", "label": "plate",
            "probe_id": probe["id"], "verified": probe["verified"],
        },
    ]
    for clip_id, track_id in (("ca", "v1"), ("cb", "v2")):
        left, top, sign = TRUTHS[clip_id]
        commands.append(
            {
                "op": "clip.add",
                "clip": {
                    "id": clip_id, "asset_id": "a", "track_id": track_id, "position_ticks": 0,
                    "duration_ticks": CLIP_TICKS, "mask": mask_at(left, top, sign),
                },
            }
        )
    seeded = client.post(
        path + "/edits",
        json={"request_id": "seed", "expected_revision": revision, "commands": commands},
    )
    assert seeded.status_code == 200, seeded.text[:400]
    return seeded.json()["project"]["revision"]


def shared_decode_suite(folder: Path) -> None:
    """一次请求带两个目标：同一段窗口只解码一次，两条路径各写各的。"""
    media = MediaService(
        folder / "db.sqlite3", [folder / "media"], folder / "cache", FFMPEG, FFPROBE
    )
    source = folder / "media" / "plate.mp4"
    source.parent.mkdir(exist_ok=True)
    render_plate(source)
    token = "multitrack" + "e" * 52
    app = create_app(folder / "api.sqlite3", token, media=media)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        caps = client.get("/v1/capabilities").json()
        assert caps["features"]["mask_track_group"] is True, caps["features"]
        assert caps["limits"]["track_max_targets"] == TRACK_TARGET_LIMIT, caps["limits"]
        probe = client.post("/v1/media/import", json={"path": str(source)}).json()
        project = client.post(
            "/v1/projects", json={"request_id": "new", "name": "group"}
        ).json()["project"]
        path = f"/v1/projects/{project['id']}"
        start = seed(client, path, probe)

        first = client.post(
            path + "/mask-track",
            json={
                "request_id": "both", "expected_revision": start,
                "targets": [group("ca"), group("cb", estimate_scale=False)],
            },
        )
        assert first.status_code == 200, first.text[:400]
        body = first.json()
        tracking = body["tracking"]
        assert tracking["target_count"] == 2 and tracking["decoded_passes"] == 1, tracking
        assert tracking["frames_decoded"] == tracking["targets"][0]["sampled_frames"], tracking
        assert tracking["targets"][0]["shared_decode"] is False, tracking["targets"][0]
        assert tracking["targets"][1]["shared_decode"] is True, tracking["targets"][1]
        assert body["committed"] is True and body["project"]["revision"] == start + 1, (
            "一组是一个批次：版本只能动一步"
        )
        clips = body["project"]["clips"]
        for clip_id, (left, top, sign) in TRUTHS.items():
            marks = [key for key in clips[clip_id]["keyframes"] if key["property"] == "mask_x"]
            assert len(marks) == FRAMES, (clip_id, len(marks))
            worst = max(
                abs(key["value"] - truth(key["at_ticks"] / T, left, top, sign)[0])
                for key in marks
            )
            assert worst < 0.05, (clip_id, worst)
            travel = marks[-1]["value"] - marks[0]["value"]
            assert (travel > 0) == (sign > 0), (clip_id, travel)
        sized = {key["property"] for key in clips["ca"]["keyframes"]}
        plain = {key["property"] for key in clips["cb"]["keyframes"]}
        assert {"mask_width", "mask_height"} <= sized, sorted(sized)
        assert "mask_width" not in plain, "一个目标关掉缩放，另一个的缩放曲线不许串过去"
        assert tracking["targets"][0]["scale_estimated"] is True
        assert tracking["targets"][1]["scale_estimated"] is False
        print(
            f"   一组 {tracking['target_count']} 个目标只读了 {tracking['decoded_passes']} 趟画面"
            f"（{tracking['frames_decoded']} 帧），两段各写 {FRAMES} 个中心点"
        )

        # 各自的 merge：同一次运行里，A 续上自己已有的前半条，B 整条重写。续跟之前把 A 的遮罩挪回
        # 那一刻的主体上——这正是界面「接着跟」的用法，跟踪器从遮罩现在的地方起手往外找。
        anchor_x, anchor_y = truth(30 / FPS, *TRUTHS["ca"])
        anchored = client.post(
            path + "/edits",
            json={
                "request_id": "anchor", "expected_revision": start + 1,
                "commands": [
                    {
                        "op": "clip.mask", "clip_id": "ca",
                        "mask": {
                            "shape": "ellipse", "center_x": anchor_x, "center_y": anchor_y,
                            "width": BOX[0], "height": BOX[1], "feather": 0.0, "inverted": False,
                        },
                    }
                ],
            },
        )
        assert anchored.status_code == 200, anchored.text[:300]
        continued = client.post(
            path + "/mask-track",
            json={
                "request_id": "continue", "expected_revision": start + 2,
                "targets": [
                    group("ca", frames=30, from_ticks=30 * FRAME_TICKS),
                    group("cb", frames=FRAMES, estimate_scale=False),
                ],
            },
        )
        assert continued.status_code == 200, continued.text[:400]
        receipts = continued.json()["tracking"]["targets"]
        assert receipts[0]["kept_frames"] == 30, receipts[0]
        assert receipts[1]["kept_frames"] == 0, receipts[1]
        assert receipts[0]["replaced_frames"] == 30, receipts[0]
        assert receipts[1]["replaced_frames"] == 60, receipts[1]
        assert abs(receipts[0]["seam_jump"]) < 0.02, receipts[0]
        assert continued.json()["project"]["revision"] == start + 3, "一整组仍只涨一个版本"

        split = client.post(
            path + "/mask-track",
            json={
                "request_id": "split", "expected_revision": start + 3, "dry_run": True,
                "targets": [
                    group("ca", frames=30),
                    group("cb", frames=20, from_ticks=10 * FRAME_TICKS, estimate_scale=False),
                ],
            },
        )
        assert split.status_code == 200, split.text[:300]
        assert split.json()["tracking"]["decoded_passes"] == 2, split.json()["tracking"]
        assert split.json()["committed"] is False, "干跑不许写"

        before = client.get(path).json()["revision"]
        twice = client.post(
            path + "/mask-track",
            json={
                "request_id": "twice", "expected_revision": before,
                "targets": [group("ca"), group("ca")],
            },
        )
        assert twice.status_code == 422, twice.text[:300]
        error = twice.json()["error"]
        assert error["code"] == "MASK_TRACK_DUPLICATE", error
        assert error["details"]["clip_ids"] == ["ca"], error["details"]
        assert client.get(path).json()["revision"] == before, "拒绝不涨版本"
        again = client.post(
            path + "/mask-track",
            json={"request_id": "again", "expected_revision": before, "targets": [group("ca")]},
        )
        assert again.status_code == 200, again.text[:300]
        gone = client.post(
            path + "/clips/ca/track", json={"request_id": "old", "expected_revision": before + 1}
        )
        assert gone.status_code in (404, 405), gone.status_code


def budget_suite(folder: Path) -> None:
    """挤不动的那一段是它自己的账：整组停下来，另一段一条曲线都不许多写。"""
    media = MediaService(
        folder / "db.sqlite3", [folder / "media"], folder / "cache", FFMPEG, FFPROBE
    )
    source = folder / "media" / "plate.mp4"
    source.parent.mkdir(exist_ok=True)
    render_plate(source)
    token = "multitrack" + "e" * 52
    app = create_app(folder / "api.sqlite3", token, media=media)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        probe = client.post("/v1/media/import", json={"path": str(source)}).json()
        project = client.post(
            "/v1/projects", json={"request_id": "new", "name": "crowded"}
        ).json()["project"]
        path = f"/v1/projects/{project['id']}"
        start = seed(client, path, probe)
        filled = CLIP_KEYFRAME_LIMIT - 1
        crowd = client.post(
            path + "/edits",
            json={
                "request_id": "crowd", "expected_revision": start,
                "commands": [
                    {
                        "op": "keyframes.replace", "clip_id": "cb", "property": "opacity",
                        "keyframes": [
                            {
                                "property": "opacity", "at_ticks": index * FRAME_TICKS,
                                "value": 1.0, "interpolation": "linear",
                            }
                            for index in range(filled)
                        ],
                    }
                ],
            },
        )
        assert crowd.status_code == 200, crowd.text[:300]
        head = crowd.json()["project"]["revision"]
        blocked = client.post(
            path + "/mask-track",
            json={
                "request_id": "blocked", "expected_revision": head,
                "targets": [group("ca"), group("cb")],
            },
        )
        assert blocked.status_code == 422, blocked.text[:300]
        refused = blocked.json()["error"]
        assert refused["code"] == "MASK_TRACK_BUDGET", refused
        assert refused["details"]["clip_id"] == "cb", refused["details"]
        assert refused["details"]["target_position"] == 2, refused["details"]
        for key in ("frames_requested", "capacity_frames", "curves_per_point", "keyframe_limit",
                    "curves_used"):
            assert refused["details"][key] is not None, (key, refused["details"])
        after = client.get(path).json()
        assert after["revision"] == head, "整组被拒就不许写任何一段"
        assert not [
            key for key in after["clips"]["ca"]["keyframes"]
            if key["property"] == "mask_x"
        ], "另一段不许被写一半"
        room = client.post(
            path + "/mask-track",
            json={"request_id": "room", "expected_revision": head, "targets": [group("ca")]},
        )
        assert room.status_code == 200, room.text[:300]
        assert room.json()["committed"] is True, "把挤不动的那段拿掉，这一组照旧交得出路径"
        print(
            f"   预算：{filled} 条曲线占满 cb 后 capacity={refused['details']['capacity_frames']}，"
            "整组点名拒绝且 ca 一条不写；只留 ca 时照旧跟满"
        )


def contract_suite() -> None:
    fields = MaskTrackRequest.model_fields
    assert "targets" in fields, sorted(fields)
    for moved in ("clip_id", "from_ticks", "frames", "merge", "reacquire", "max_gap_frames"):
        assert moved not in fields, f"{moved} 还留在请求顶层"
        assert moved in MaskTrackTarget.model_fields, f"{moved} 没有落到目标上"
    assert "sequence_id" in fields, "一整组只落在一个合成里，所以它是请求级的"
    assert "sequence_id" not in MaskTrackTarget.model_fields, "目标不许各自挑合成"
    too_many = [MaskTrackTarget(clip_id=f"c{index}") for index in range(TRACK_TARGET_LIMIT + 1)]
    try:
        MaskTrackRequest(request_id="r", expected_revision=1, targets=too_many)
    except ValidationError:
        pass
    else:
        raise AssertionError("超过段数上限的一组必须被契约拒绝")
    rules = MaskTrackRequest.model_fields["targets"].metadata
    assert any(getattr(rule, "min_length", None) == 1 for rule in rules), rules


def surface_suite() -> None:
    """旧的那条「一片段一条路」的入口，在源码与界面上都不许还留着。"""
    effects = (ROOT / "desktop/src/effects.ts").read_text(encoding="utf-8")
    fallback = re.search(r"track_max_targets \?\? (\d+)", effects)
    assert fallback, "分组没有从 capabilities 读段数上限"
    assert int(fallback.group(1)) == TRACK_TARGET_LIMIT, (
        f"界面兜底 {fallback.group(1)} 与契约 {TRACK_TARGET_LIMIT} 不是同一个数"
    )
    inspector = (ROOT / "desktop/src/views/Inspector.tsx").read_text(encoding="utf-8")
    assert inspector.count("trackGroup(") == 1, "分组判断只许有一处"
    assert inspector.count("trackWindow(") == 2, "单段的两个入口仍走同一个判断"
    store = (ROOT / "desktop/src/store.ts").read_text(encoding="utf-8")
    assert "decoded_passes" in store, "回执里省下的那几趟读片没告诉用户"
    assert "clip.mask_track" in store, "写回仍要走那一条普通命令"
    api = (ROOT / "src/agentcut/http_api.py").read_text(encoding="utf-8")
    assert "/clips/{clip_id}/track" not in api, "旧路由还在，两处入口必然分家"
    assert api.count("/mask-track") == 1, api.count("/mask-track")
    tracking = (ROOT / "src/agentcut/tracking.py").read_text(encoding="utf-8")
    assert "def track_mask(" not in tracking, "解码与跟随又粘回一个函数，共享就没了落点"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "一组多个目标一次跑完" in readme, "交付表里没说这一档"
    assert "mask-track" in readme, "交付表没有点名那条组路由"
    assert "多目标跟踪（1.85 起单目标" not in readme, "还差的那一栏仍挂着已交付的东西"
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "mask_track_group" in agents, "协作规则里还没有这一档的名字"


def main() -> None:
    for suite in (fixture_suite, shared_decode_suite, budget_suite):
        with tempfile.TemporaryDirectory(prefix=f"agentcut-{suite.__name__}-") as name:
            suite(Path(name))
    contract_suite()
    surface_suite()
    print(
        "PASS: 一组目标一次跑完——同一段窗口只解码一次、每个目标各按自己的预算与 merge 收短、"
        "整组一个版本一步撤销、拥挤的那段点名拒绝而另一条曲线都不许多写，段数上限只在契约里"
    )


if __name__ == "__main__":
    main()
