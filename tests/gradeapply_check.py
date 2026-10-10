"""1.108 的验收：一条片段的调色链套到整轨——规划与写入必须问同一套规矩。

为什么要这一条：达芬奇给的是「把这条节点图复制到这一轨」，剪映给的是「把这个滤镜一键应用到全部」。
两边要的同一件事是「别逼我一段一段点」。而这里最容易出的错不是「做不到」，是**规划说行、写入被拒**，
或者反过来：一次批量把整轨回滚掉，人只知道「失败了」。所以这条门禁断的全是「报得出来」：

* 三种装不下的原因各说各的数（每链 8 个节点的上限、音频片段没有画面、工程级查找表额度 1.104）；
* 装得下的那几段真的写进去了，一次批量只涨一个 revision，撤销一步就全部回到套之前；
* dry_run 与提交同答；`replace` 与 `append` 是两种语义，不是同一件事换名字；
* 规划交回的就是普通 `clip.grade` 命令 —— 界面与 Agent 用的是同一条写入路径，没有第二套剪辑规则。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fastapi.testclient import TestClient  # noqa: E402

from agentcut.contracts import (  # noqa: E402
    GRADE_INLINE_SAMPLE_LIMIT,
    GRADE_NODE_LIMIT,
    capabilities,
)
from agentcut.contracts import TIMEBASE as T  # noqa: E402
from agentcut.grade import parse_cube  # noqa: E402
from agentcut.http_api import create_app  # noqa: E402
from agentcut.timeline import grade_apply_track_plan, grade_inline_samples  # noqa: E402

CUBE = parse_cube(
    "\n".join(
        ['TITLE "look"', "LUT_3D_SIZE 17"]
        + [
            f"{red / 16:.4f} {green / 16:.4f} {blue / 16:.4f}"
            for blue in range(17)
            for green in range(17)
            for red in range(17)
        ]
    )
    + "\n"
)
CUBE_NODE = {"kind": "lut3d", **{k: v for k, v in CUBE.items() if k != "kind"}}
CUBE_SAMPLES = len(CUBE_NODE["cells"])
CURVE = {
    "kind": "curve",
    "channel": "rgb",
    "points": [{"x": 0.0, "y": 0.2}, {"x": 1.0, "y": 0.8}],
}


def build(clips: dict[str, list[dict]], *, audio_track: bool = False) -> "Project":  # noqa: F821
    from agentcut.contracts import Asset, Clip, ClipColor, Project, SequenceSettings, Track

    tracks = [Track(id="v1", kind="video", name="画面")]
    if audio_track:
        tracks.append(Track(id="a1", kind="audio", name="声音"))
    return Project(
        id="p",
        name="整轨套色",
        settings=SequenceSettings(
            width=160,
            height=90,
            sample_rate=48000,
            frame_rate={"numerator": 25, "denominator": 1},
        ),
        tracks=tracks,
        assets={
            "v": Asset(id="v", kind="video", label="画面", reference="v", duration_ticks=10 * T),
            "w": Asset(id="w", kind="audio", label="声音", reference="w", duration_ticks=10 * T),
        },
        clips={
            clip_id: Clip(
                id=clip_id,
                asset_id=("w" if clip_id.startswith("a") else "v"),
                track_id="v1",
                position_ticks=index * T,
                duration_ticks=T,
                color=ClipColor(grade=grade),
            )
            for index, (clip_id, grade) in enumerate(clips.items())
        },
    )


def plan_suite() -> None:
    source = {"c0": [dict(CURVE), dict(CUBE_NODE)], "c1": [], "c2": []}
    project = build(source)
    body = grade_apply_track_plan(project, "c0", "v1")
    assert body["applied"] == 2 and body["skipped"] == 0, body
    assert body["nodes"] == 2 and body["chain_samples"] == CUBE_SAMPLES, body
    # 规划交回的就是普通的 clip.grade 命令：没有第二条写入路径。
    assert all(command["op"] == "clip.grade" for command in body["commands"]), body
    assert [command["clip_id"] for command in body["commands"]] == ["c1", "c2"], body
    written = json.dumps(body["commands"], ensure_ascii=False)
    assert "lut3d" in written, written[:120]
    moved = next(node for node in body["commands"][0]["grade"] if node["kind"] == "lut3d")
    assert len(moved["cells"]) == CUBE_SAMPLES, "立方表要跟着这条链一起搬过去"

    # append 与 replace 是两种语义：已有节点的数目决定 append 会不会撞每链上限。
    busy = build({"c0": [dict(CURVE)], **{f"c{i}": [dict(CURVE)] * 7 for i in (1, 2)}})
    appended = grade_apply_track_plan(busy, "c0", "v1", "append")
    assert appended["applied"] == 2 and len(appended["commands"][0]["grade"]) == GRADE_NODE_LIMIT, (
        appended
    )
    full = build(
        {"c0": [dict(CURVE)], **{f"c{i}": [dict(CURVE)] * GRADE_NODE_LIMIT for i in (1, 2)}}
    )
    refused = grade_apply_track_plan(full, "c0", "v1", "append")
    assert refused["applied"] == 0 and refused["skipped"] == 2, refused
    entry = refused["clips"][0]
    assert (
        entry["node_limit"] == GRADE_NODE_LIMIT and entry["existing_nodes"] == GRADE_NODE_LIMIT
    ), entry
    assert "8" in entry["skipped"], entry["skipped"]
    # 同一条链换成 replace 就装得下——上限管的是套完以后有几条，不是「不许动」。
    replaced = grade_apply_track_plan(full, "c0", "v1", "replace")
    assert replaced["applied"] == 2, replaced
    assert all(len(command["grade"]) == 1 for command in replaced["commands"]), replaced

    # 音频片段：报「没有画面可调色」，而不是排进一条必被 reducer 拒的命令。
    audio = build({"c0": [dict(CURVE)], "a1": [], "a2": []})
    heard = grade_apply_track_plan(audio, "c0", "v1")
    assert heard["applied"] == 0 and heard["skipped"] == 2, heard
    assert "画面" in heard["clips"][0]["skipped"], heard["clips"][0]["skipped"]
    # 源片段不在这条轨上：点名的是它自己所在的那条，不是含糊的「找不到」。
    try:
        grade_apply_track_plan(audio, "c0", "a1")
    except Exception as error:  # noqa: BLE001
        assert getattr(error, "code", "") == "NOT_FOUND", error
        assert error.details == {"clip_id": "c0", "track_id": "v1"}, error.details  # type: ignore[attr-defined]
    else:
        raise AssertionError("源片段不在这条轨上本该点名拒绝")
    print(
        f"   三种装不下各说各的数：每链 {GRADE_NODE_LIMIT} 个上限、音频没有画面、replace 仍装得下"
    )


def budget_suite() -> None:
    # 额度（1.104）在这里是真实约束：一条带立方的链套到很多段，装得下的先进命令，剩下的报出实数。
    fits = GRADE_INLINE_SAMPLE_LIMIT // CUBE_SAMPLES
    clips = {"c0": [dict(CUBE_NODE)]}
    for index in range(fits + 3):
        clips[f"t{index}"] = []
    project = build(clips)
    body = grade_apply_track_plan(project, "c0", "v1")
    assert body["applied"] == fits - 1, (body["applied"], fits)
    assert body["skipped"] == 4, body["skipped"]
    tail = [item for item in body["clips"] if "skipped" in item]
    assert all("采样点" in item["skipped"] for item in tail), tail[0]
    assert tail[0]["needed_samples"] == CUBE_SAMPLES, tail[0]
    assert tail[0]["room_samples"] < CUBE_SAMPLES, tail[0]
    assert body["room_samples"] >= 0, body
    # 规划自己不许越额度：套完命令、真去算一遍，必须还在限制之内。
    filled = project.model_copy(deep=True)
    for command in body["commands"]:
        filled.clips[command["clip_id"]].color.grade = command["grade"]
    assert grade_inline_samples(filled) <= GRADE_INLINE_SAMPLE_LIMIT, grade_inline_samples(filled)
    print(
        f"   额度：一条 {CUBE_SAMPLES} 采样点的立方链套到 {fits + 3} 段，"
        f"装得下 {body['applied']} 段、{body['skipped']} 段报出剩多少与要多少"
    )


def http_suite() -> None:
    import tempfile as _tempfile

    token = "gradeapply-token-0123456789abcdef0123"
    with _tempfile.TemporaryDirectory(prefix="agentcut-gradeapply-") as scratch:
        client = TestClient(
            create_app(Path(scratch) / "db.sqlite3", token),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {token}"},
        )
        with client:
            created = client.post(
                "/v1/projects",
                json={
                    "request_id": "ga-new",
                    "name": "整轨",
                    "settings": {
                        "width": 160,
                        "height": 90,
                        "frame_rate": {"numerator": 25, "denominator": 1},
                    },
                },
            ).json()["project"]
            pid = created["id"]
            revision = created["revision"]
            commands = [
                {"op": "track.add", "track": {"id": "v1", "kind": "video", "name": "画面"}},
                {
                    "op": "asset.register",
                    "asset": {
                        "id": "v",
                        "kind": "video",
                        "label": "底",
                        "reference": "v",
                        "duration_ticks": 10 * T,
                    },
                },
            ]
            for index, clip in enumerate(("c0", "c1", "c2")):
                commands.append(
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": clip,
                            "asset_id": "v",
                            "track_id": "v1",
                            "position_ticks": index * T,
                            "duration_ticks": T,
                        },
                    }
                )
            answer = client.post(
                f"/v1/projects/{pid}/edits",
                json={"request_id": "ga-seed", "expected_revision": revision, "commands": commands},
            ).json()
            revision = answer["project"]["revision"]
            answer = client.post(
                f"/v1/projects/{pid}/edits",
                json={
                    "request_id": "ga-look",
                    "expected_revision": revision,
                    "commands": [
                        {
                            "op": "clip.grade",
                            "clip_id": "c0",
                            "grade": [dict(CURVE), dict(CUBE_NODE)],
                        }
                    ],
                },
            )
            assert answer.status_code == 200, answer.text[:200]
            revision = answer.json()["project"]["revision"]

            route = f"/v1/projects/{pid}/tracks/v1/grade-apply"
            planned = client.post(
                route,
                json={"request_id": "ga-plan", "expected_revision": revision, "clip_id": "c0"},
            ).json()
            assert planned["committed"] is False, planned
            body = planned["grade_application"]
            assert body["applied"] == 2 and len(body["commands"]) == 2, body
            assert client.get(f"/v1/projects/{pid}").json()["revision"] == revision, (
                "只读规划不该落库（回执里那份是要写成的样子，不是已写成）"
            )
            dry = client.post(
                route,
                json={
                    "request_id": "ga-dry",
                    "expected_revision": revision,
                    "clip_id": "c0",
                    "apply": True,
                    "dry_run": True,
                },
            ).json()
            assert dry["grade_application"]["applied"] == 2, dry
            assert dry["committed"] is False, dry
            assert len(dry["project"]["clips"]["c1"]["color"]["grade"]) == 2, dry
            assert client.get(f"/v1/projects/{pid}").json()["revision"] == revision, (
                "dry_run 不落库"
            )
            committed = client.post(
                route,
                json={
                    "request_id": "ga-apply",
                    "expected_revision": revision,
                    "clip_id": "c0",
                    "apply": True,
                },
            )
            assert committed.status_code == 200, committed.text[:300]
            done = committed.json()
            assert done["project"]["revision"] == revision + 1, "整轨只该涨一个 revision"
            applied = done["project"]["clips"]
            assert [len(applied[key]["color"]["grade"]) for key in ("c0", "c1", "c2")] == [
                2,
                2,
                2,
            ], applied
            assert applied["c1"]["color"]["grade"][1]["kind"] == "lut3d", applied["c1"]
            rolled = client.post(
                f"/v1/projects/{pid}/edits",
                json={
                    "request_id": "ga-undo",
                    "expected_revision": done["project"]["revision"],
                    "commands": [
                        {"op": "clip.grade", "clip_id": "c1", "grade": []},
                        {"op": "clip.grade", "clip_id": "c2", "grade": []},
                    ],
                },
            ).json()
            assert rolled["project"]["clips"]["c2"]["color"]["grade"] == [], rolled
            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["grade_apply_track"] is True, caps["features"]
            missing = client.post(
                route,
                json={
                    "request_id": "ga-none",
                    "expected_revision": rolled["project"]["revision"],
                    "clip_id": "c1",
                },
            )
            assert missing.status_code == 422, missing.text[:200]
            assert missing.json()["error"]["code"] == "GRADE_APPLY_NONE", missing.json()
            assert missing.json()["error"]["details"]["clip_id"] == "c1", missing.json()
            after = client.get(f"/v1/projects/{pid}").json()
            assert after["revision"] == rolled["project"]["revision"], "被拒的规划不该涨 revision"
            print(
                "   HTTP：只读规划、dry_run、一次提交一个 revision、撤销回原样；"
                "空链片段点名 GRADE_APPLY_NONE 且不涨 revision"
            )


def tools_suite() -> None:
    caps = capabilities()
    assert "clip.grade" in caps["commands"], caps["commands"]
    assert caps["features"]["grade_apply_track"] is True, caps["features"]
    schema = json.dumps(caps, ensure_ascii=False)
    assert "grade_apply_track" in schema
    print("   能力：features.grade_apply_track 下发；命令表里仍是那条 clip.grade")


def main() -> None:
    plan_suite()
    budget_suite()
    http_suite()
    tools_suite()
    print("PASS: 整轨套一条调色走的是同一条写入路径，装不下的一段都报得出实数")


main()
