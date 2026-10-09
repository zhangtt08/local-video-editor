"""1.97 整轨一次搬完老淡：规划与写入必须是同一条判断，成片必须一个像素都不动。

1.96 的 `clip.fade_adopt` 一次搬一条属性一个片段。老素材通常不是一段而是一整轨几十段，
逐段点开检查器不是「吸收剪映/达芬奇的交互优点」，是给人加活。这一版加一条只读规划
`POST /v1/projects/{id}/tracks/{tid}/fade-adopt`：走一遍这条轨，把能搬的排成普通的
`clip.fade_adopt` 命令，把搬不动的连原因与实际看到的关键帧一起交回。

四条要紧的事，逐条钉住：

* **规划就是那条判断**：规划函数调的就是 reducer 用的 `_fade_adoption`，所以它交回的命令一定是同一个
  reducer 会接受的命令。反过来如果规划自己再写一套「大概能搬」的规则，两边迟早分家——那时一条
  整轨批处理会因为一段被拒而把 40 段一起回滚。
* **不说话的东西不列**：这条属性上没有关键帧的片段根本不出现在报告里。整轨报告的价值是「哪几段
  有问题、为什么」，把 N 段「这里没有淡」混进去就把它埋了。
* **一次写入 = 一个 revision**：`apply=true` 交一个批次，不是 N 个。
* **画面不动**：同一条时间线搬前搬后各渲一遍，八个时刻的中心像素逐个比，容差 1 阶。
"""

import tempfile
from pathlib import Path

import fadeadopt_check as single
from fade_check import RATE, SECONDS, asset, build, made_clip, pixel, slate
from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import (
    EditBatch,
    Keyframe,
    Project,
    SequenceSettings,
    Track,
)
from agentcut.http_api import create_app
from agentcut.timeline import apply_commands, fade_adopt_track_plan

TOKEN = "fade-batch-" + "d" * 40
AUDIO = {
    "id": "sound",
    "kind": "audio",
    "label": "声",
    "reference": "r",
    "duration_ticks": SECONDS * T,
}


def moved(clip, clip_id, position):
    clip.id = clip_id
    clip.position_ticks = position
    return clip


def legacy_gain(seconds, clip_id="g", position=0):
    """一条按老写法写在音量曲线上的淡：边上 0、斜坡尽头取这条片段的静止增益。"""
    clip = made_clip("v2", clip_id, "white", None)
    clip.effects.gain = 1.0
    clip.position_ticks = position
    clip.keyframes = [
        Keyframe(property="gain", at_ticks=0, value=0.0, interpolation="ease"),
        Keyframe(property="gain", at_ticks=int(seconds * T), value=1.0, interpolation="ease"),
    ]
    return clip


def audio_with_opacity(clip_id="au"):
    """一条音量轨上的音频片段，画面透明度上摆着老淡——引擎根本不允许给音频淡画面。"""
    clip = made_clip("au1", clip_id, "sound", None)
    clip.keyframes = [
        Keyframe(property="opacity", at_ticks=0, value=0.0, interpolation="ease"),
        Keyframe(property="opacity", at_ticks=T, value=1.0, interpolation="ease"),
    ]
    return clip


def track_project(white, black, clips, with_audio_track=True):
    """黑底 v1 + 一轨待搬的 v2（可选再挂一条音量轨）。"""
    items = {
        "b": made_clip("v1", "b", "black", None),
        **{clip.id: clip for clip in clips},
    }
    tracks = [Track(id="v1", kind="video", name="底"), Track(id="v2", kind="video", name="上")]
    if with_audio_track:
        tracks.append(Track(id="au1", kind="audio", name="声"))
    return Project(
        id="p",
        name="batch",
        settings=SequenceSettings(width=160, height=90, sample_rate=RATE),
        tracks=tracks,
        assets={"black": black, "white": white, "sound": AUDIO},
        clips=items,
    )


def validated(target, commands):
    return EditBatch.model_validate(
        {"request_id": "batch", "expected_revision": target.revision, "commands": commands}
    ).commands


def plan_suite() -> None:
    white = {
        "id": "white",
        "kind": "video",
        "label": "w",
        "reference": "r",
        "duration_ticks": SECONDS * T,
    }
    black = {
        "id": "black",
        "kind": "video",
        "label": "b",
        "reference": "r",
        "duration_ticks": SECONDS * T,
    }
    both = moved(single.legacy(), "w", 0)
    one = moved(single.legacy(in_seconds=0.5, out_seconds=0), "x", SECONDS * T)
    hand = moved(
        # 数值合法（仍是 0 或静止值）、位置多一个：这是「淡里夹了别人敲的点」那一条，
        # 不是「斜坡够不到静止值」那一条。
        single.legacy(
            extra=[Keyframe(property="opacity", at_ticks=2 * T, value=1.0, interpolation="ease")]
        ),
        "y",
        2 * SECONDS * T,
    )
    straight = moved(single.legacy(interpolation="linear"), "h", 5 * SECONDS * T)
    clean = made_clip("v2", "z", "white", None)
    clean.position_ticks = 3 * SECONDS * T
    gain = legacy_gain(1.0, "g", 4 * SECONDS * T)
    project = track_project(white, black, [hand, gain, clean, one, both, straight])
    # 报告按片段时间线位置排，而不是按字典插入顺序——界面与 Agent 读到的顺序应当是「从上到下」。
    plan = fade_adopt_track_plan(project, "v2")
    assert [item["clip_id"] for item in plan["clips"]] == ["w", "x", "y", "g", "h"], plan["clips"]
    assert plan["adopted"] == 3 and plan["skipped"] == 2, plan
    assert [command["clip_id"] for command in plan["commands"]] == ["w", "x", "g"], plan["commands"]
    assert all(command["op"] == "clip.fade_adopt" for command in plan["commands"])
    assert {(c["clip_id"], c["property"]) for c in plan["commands"]} == {
        ("w", "opacity"),
        ("x", "opacity"),
        ("g", "gain"),
    }
    # 没有淡的片段根本不出现在报告里（z 一条关键帧都没有）。
    assert "z" not in [item["clip_id"] for item in plan["clips"]]
    entry = {item["clip_id"]: item for item in plan["clips"]}
    assert entry["w"]["in_ticks"] == T and entry["w"]["out_ticks"] == T, entry["w"]
    assert entry["w"]["shape"] == "ease_in_out" and entry["w"]["keyframe_count"] == 4, entry["w"]
    assert entry["x"]["in_ticks"] == T // 2 and entry["x"]["out_ticks"] == 0, entry["x"]
    assert entry["g"]["property"] == "gain" and entry["g"]["in_ticks"] == T, entry["g"]
    # 搬不动的那条把原因与实际看到的点交回，而不是只说一句「不行」。
    assert entry["y"]["skipped"] == "other keyframes are mixed into the fade", entry["y"]
    assert entry["y"]["extra_at_ticks"] == [2 * T], entry["y"]
    assert len(entry["y"]["keyframes"]) == 5, entry["y"]
    assert entry["y"]["clip_duration_ticks"] == SECONDS * T, entry["y"]
    # 同一轨上两种不同的「搬不动」：夹了点、以及斜坡不是缓动的（老淡只用 ease，线性的是人手K的）。
    assert entry["h"]["skipped"] == "the ramp is not the eased shape a fade used", entry["h"]
    assert len(entry["h"]["keyframes"]) == 4 and entry["h"]["resting_value"] == 1.0, entry["h"]

    # 规划是纯读：调两次、比调之前，工程一字不动。
    snapshot = project.model_dump()
    fade_adopt_track_plan(project, "v2")
    assert project.model_dump() == snapshot, "规划不许碰工程"

    # 规划与写入同源：把规划交回的命令交给 reducer，落库的窗口必须等于规划报的那两个数。
    adopted = apply_commands(project, validated(project, plan["commands"]))
    for item in plan["clips"]:
        if "skipped" in item:
            continue
        clip = adopted.clips[item["clip_id"]]
        window = clip.fade.window(item["property"])
        assert window == (item["in_ticks"], item["out_ticks"]), (item, window)
        assert clip.fade.shape(item["property"]) == "ease_in_out", item
        assert not [k for k in clip.keyframes if k.property == item["property"]], item
    # 手敲的那条一字未动，音量淡也不顺带被删。
    assert [k.at_ticks for k in adopted.clips["y"].keyframes] == [0, T, 2 * T, 3 * T, 4 * T]
    assert adopted.clips["z"].fade is None
    # 搬完再规划一次：能搬的都搬完了，报告里只剩那两条本来就不能动的（不是「一段没有淡」的噪音）。
    again = fade_adopt_track_plan(adopted, "v2")
    assert again["adopted"] == 0 and again["commands"] == [], again
    assert [item["clip_id"] for item in again["clips"]] == ["y", "h"], again["clips"]
    # 音频片段上的 opacity：规划跳过并说明原因，绝不排成一条必被 reducer 拒绝的命令。
    sound = track_project(white, black, [audio_with_opacity()])
    audio_plan = fade_adopt_track_plan(sound, "au1")
    assert audio_plan["commands"] == [], audio_plan
    assert audio_plan["skipped"] == 1, audio_plan
    assert audio_plan["clips"][0]["skipped"] == "audio has no opacity to fade", audio_plan["clips"]
    assert audio_plan["clips"][0]["asset_kind"] == "audio", audio_plan["clips"]
    # 空轨道：没有片段也就没有可说的。
    empty = fade_adopt_track_plan(project, "v1")
    assert empty["adopted"] == 0 and empty["clips"] == [], empty
    print(
        "   规划与 reducer 同源：三段落库的窗口等于规划报的数、手敲那条一字未动、"
        "没有淡的片段不出现在报告里"
    )


def http_suite() -> None:
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        # 工程仓库是 lifespan 挂上去的，不进 `with` 就没有 `app.state.projects`。
        with TestClient(
            create_app(root / "db.sqlite", TOKEN),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {TOKEN}"},
        ) as client:
            http_round_trip(client)


def http_round_trip(client) -> None:
    caps = client.get("/v1/capabilities").json()
    assert caps["features"]["clip_fade_adopt_track"] is True, caps["features"]
    created = client.post("/v1/projects", json={"request_id": "new", "name": "batch"}).json()[
        "project"
    ]
    pid = created["id"]
    white = {
        "id": "white",
        "kind": "video",
        "label": "w",
        "reference": "r",
        "duration_ticks": SECONDS * T,
    }
    keys = [
        {"property": "opacity", "at_ticks": 0, "value": 0.0, "interpolation": "ease"},
        {"property": "opacity", "at_ticks": T, "value": 1.0, "interpolation": "ease"},
    ]
    commands = [
        {"op": "track.add", "track": {"id": "v1", "kind": "video", "name": "画面"}},
        {"op": "asset.register", "asset": white},
    ]
    for index in range(3):
        commands.append(
            {
                "op": "clip.add",
                "clip": {
                    "id": f"c{index}",
                    "asset_id": "white",
                    "track_id": "v1",
                    "position_ticks": index * SECONDS * T,
                    "source_in_ticks": 0,
                    "duration_ticks": SECONDS * T,
                    "keyframes": keys,
                },
            }
        )
    # 第四条：淡到一半又手敲了一个点，整轨规划要把它点名跳过。
    commands.append(
        {
            "op": "clip.add",
            "clip": {
                "id": "bad",
                "asset_id": "white",
                "track_id": "v1",
                "position_ticks": 3 * SECONDS * T,
                "source_in_ticks": 0,
                "duration_ticks": SECONDS * T,
                "keyframes": [
                    *keys,
                    {"property": "opacity", "at_ticks": 2 * T, "value": 0.6},
                ],
            },
        }
    )
    seeded = client.post(
        f"/v1/projects/{pid}/edits",
        json={
            "request_id": "seed",
            "expected_revision": created["revision"],
            "commands": commands,
        },
    ).json()["project"]
    path = f"/v1/projects/{pid}/tracks/v1/fade-adopt"
    planned = client.post(
        path, json={"request_id": "plan", "expected_revision": seeded["revision"]}
    ).json()
    assert planned["committed"] is False, planned
    assert planned["project"]["revision"] == seeded["revision"], "只读规划不落库"
    body = planned["fade_adoption"]
    assert body["adopted"] == 3 and body["skipped"] == 1, body
    assert len(body["commands"]) == 3, body["commands"]
    assert [item["clip_id"] for item in body["clips"] if "skipped" in item] == ["bad"], body
    got = client.get(f"/v1/projects/{pid}").json()
    assert len(got["clips"]["c0"]["keyframes"]) == 2, "规划不该动片段"
    assert got["revision"] == seeded["revision"]
    dry = client.post(
        path,
        json={
            "request_id": "dry",
            "expected_revision": seeded["revision"],
            "apply": True,
            "dry_run": True,
        },
    ).json()
    assert dry["committed"] is False, dry
    assert dry["project"]["revision"] == seeded["revision"] + 1, "预览给的是将要落库的那个号"
    assert dry["base_revision"] == seeded["revision"], dry
    assert dry["project"]["clips"]["c0"]["fade"]["opacity_in_ticks"] == T, dry["project"]["clips"][
        "c0"
    ]["fade"]
    assert client.get(f"/v1/projects/{pid}").json()["revision"] == seeded["revision"], (
        "dry run 不落库"
    )
    applied = client.post(
        path,
        json={
            "request_id": "apply",
            "expected_revision": seeded["revision"],
            "apply": True,
        },
    ).json()
    assert applied["committed"] is True, applied
    # 三段落库只涨一个版本，这才叫「一次操作」。
    assert applied["project"]["revision"] == seeded["revision"] + 1, applied["project"]
    for index in range(3):
        clip = applied["project"]["clips"][f"c{index}"]
        assert (clip["fade"]["opacity_in_ticks"], clip["fade"]["opacity_out_ticks"]) == (
            T,
            0,
        ), clip
        assert clip["keyframes"] == [], clip["keyframes"]
    assert applied["project"]["clips"]["bad"]["keyframes"], "搬不动的那条不该被碰"
    # 再点一次：没东西可搬，点名拒绝并把每一段的说法带回来，而不是空跑一个 revision。
    before = applied["project"]["revision"]
    none = client.post(
        path,
        json={
            "request_id": "none",
            "expected_revision": before,
            "apply": True,
        },
    )
    assert none.status_code == 422, none.text[:200]
    assert none.json()["error"]["code"] == "FADE_ADOPT_NONE", none.json()
    details = none.json()["error"]["details"]
    assert details["track_id"] == "v1", details
    assert details["inspected"] == 1, details
    assert details["skipped"] == [
        {
            "clip_id": "bad",
            "property": "opacity",
            "reason": "the ramp does not run between 0.0 and the resting value",
        }
    ], details
    assert client.get(f"/v1/projects/{pid}").json()["revision"] == before, "被拒不涨版本"
    missing = client.post(
        f"/v1/projects/{pid}/tracks/nope/fade-adopt",
        json={"request_id": "missing", "expected_revision": before},
    )
    assert missing.status_code == 404, missing.text[:200]
    assert missing.json()["error"]["details"]["track_id"] == "nope", missing.json()
    empty = client.post(
        f"/v1/projects/{pid}/edits",
        json={
            "request_id": "bare",
            "expected_revision": before,
            "commands": [{"op": "track.add", "track": {"id": "v9", "kind": "video", "name": "空"}}],
        },
    ).json()["project"]["revision"]
    bare = client.post(
        f"/v1/projects/{pid}/tracks/v9/fade-adopt",
        json={"request_id": "bare9", "expected_revision": empty},
    )
    assert bare.status_code == 404, bare.text[:200]
    assert "no clips" in bare.json()["error"]["message"], bare.json()
    assert bare.json()["error"]["details"]["track_id"] == "v9", bare.json()
    print("   HTTP：只读规划不落库、整轨一次只涨一个 revision、没得搬与被拒都不许偷偷写版本")


def media_suite(folder: Path) -> None:
    white = slate(folder, "bw", "0xFFFFFF", False)
    black = slate(folder, "bb", "0x000000", False)
    white_asset = asset(white, "white", "video", False)
    black_asset = asset(black, "black", "video", False)
    clips = [
        moved(single.legacy(), "w", 0),
        moved(single.legacy(in_seconds=1.5, out_seconds=0.5), "x", SECONDS * T),
        legacy_gain(1.0, "g", 2 * SECONDS * T),
    ]
    project = track_project(white_asset, black_asset, clips)
    # 三段上层各配一段黑底：整条时间线每一刻都有两层，测到的像素才是这条合成真正会交出去的东西。
    for span in (1, 2):
        bottom = made_clip("v1", f"b{span}", "black", None)
        bottom.position_ticks = span * SECONDS * T
        project.clips[f"b{span}"] = bottom
    plan = fade_adopt_track_plan(project, "v2")
    assert plan["adopted"] == 3, plan
    after = apply_commands(project, validated(project, plan["commands"]))
    first, _ = build(project, folder, "batch-before.mp4")
    second, _ = build(after, folder, "batch-after.mp4")
    worst = 0
    for span in range(3):
        for probe in (0.0, 0.5, 1.0, 2.0, 3.0, SECONDS - 0.05):
            at = span * SECONDS + probe
            left, right = pixel(first, at), pixel(second, at)
            worst = max(worst, abs(left - right))
            assert abs(left - right) <= 1, (at, left, right)
    assert worst == 0, f"整轨搬完最差偏差 {worst} 阶，不是 0"
    print(f"   成片：三段老淡一次搬完，18 个时刻的中心像素逐个相同（最差 {worst} 阶）")


def vocabulary_suite() -> None:
    """引擎能说出的每一句「搬不动」，界面都必须有中文说法。

    与 `tests/error_vocabulary_check.py` 同一规矩，只是这一处配的是拒绝的**句子**而不是错误码：
    整轨报告一次列几十条，人读的是「哪几段、为什么」，印英文句子等于没报。表缺一条就红，
    这样加一条新拒绝的人一定会同时补上中文。
    """
    import inspect
    import re
    from pathlib import Path

    from agentcut.timeline import _fade_adoption, fade_adopt_track_plan

    source = inspect.getsource(_fade_adoption) + inspect.getsource(fade_adopt_track_plan)
    reasons = set(re.findall(r'return None, "([^"]+)"', source)) | set(
        re.findall(r'"skipped": "([^"]+)"', source)
    )
    assert reasons, "没从引擎里读到拒绝的句子——这个检查自己就空了"
    table = (Path(__file__).resolve().parent.parent / "desktop" / "src" / "effects.ts").read_text(
        encoding="utf-8"
    )
    block = table.split("FADE_ADOPT_REASONS: Record<string, string> = {", 1)[1].split("};", 1)[0]
    labeled = set(re.findall(r'^\s*"([^"]+)":', block, re.MULTILINE))
    missing = sorted(reasons - labeled)
    assert not missing, f"这些拒绝没有中文说法：{missing}"
    assert '""' not in block, "中文说法不许是空串"
    print(f"   词表对上：引擎的 {len(reasons)} 句「搬不动」都在 effects.ts 的表里有中文说法")


def main() -> None:
    plan_suite()
    vocabulary_suite()
    http_suite()
    with tempfile.TemporaryDirectory(prefix="agentcut-fadebatch-") as scratch:
        media_suite(Path(scratch))
    print("PASS: 整轨规划与 reducer 同源、一次写入一个版本、画面一字不动、搬不动的都点名")


if __name__ == "__main__":
    main()
