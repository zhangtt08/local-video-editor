"""1.104 的验收：工程级 inline 查找表预算只在「装不下」时说话，并且说清谁占的地方。

为什么做这一条：1.103 让一张 17³ 的立方表进了工程状态，实测一张表的 json 是 101 KiB，而每次修改都要
整份快照一遍。每条链有 8 个节点的上限，但**跨片段没有总量上限**——一百个片段各挂一张立方，工程就是
几十 MiB 的状态加同样几十 MiB 的历史。这一版把那条乘法收到一处：全工程 inline 表的采样点总数
有一个额度，
由 `capabilities.grade_limits.max_inline_samples` 下发，reducer 在候选状态上算，超了就点名拒绝。

量什么：
* 一处主人：`capabilities` 里的数与 contracts 的常数相同，界面不许自带数字；
* 计数是真的：1D 按三通道各一行、3D 按 size³×3、并联分支各自算、嵌套合成里的片段也算；
* 边界：正好用到额度上允许，再多一张就拒，且拒的是那一条命令而不是整份工程；
* 拒绝点名：code=GRADE_INLINE_BUDGET、句子给出实数与上限、details 带 samples/limit/worst_clip_id/
  worst_clip_samples——出路（删掉谁）写在数里；
* HTTP：dry_run 与提交同答、拒绝不涨 revision，撤销之后原来那张表又能装进去。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from fastapi.testclient import TestClient  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from agentcut.contracts import (  # noqa: E402
    GRADE_INLINE_SAMPLE_LIMIT,
    Clip,
    ClipColor,
    EditBatch,
    Project,
    Sequence,
    SequenceSettings,
    Track,
    capabilities,
)
from agentcut.contracts import (  # noqa: E402
    TIMEBASE as T,
)
from agentcut.grade import parse_cube  # noqa: E402
from agentcut.timeline import apply_commands, grade_inline_samples  # noqa: E402

CUBE = parse_cube(
    "\n".join(
        ['TITLE "budget"', "LUT_3D_SIZE 17"]
        + [
            f"{red / 16:.4f} {green / 16:.4f} {blue / 16:.4f}"
            for blue in range(17)
            for green in range(17)
            for red in range(17)
        ]
    )
    + "\n"
)["cells"]
CUBE_SAMPLES = len(CUBE)
ONE_D = [i / 1023 for i in range(1024)]


def cube_node():
    return {"kind": "lut3d", "title": "budget", "size": 17, "cells": list(CUBE)}


def one_d_node():
    return {
        "kind": "lut",
        "title": "one-d",
        "size": 1024,
        "channels": [list(ONE_D) for _ in range(3)],
    }


def project(clips: dict[str, list[dict]]) -> Project:
    return Project(
        id="p",
        name="预算",
        settings=SequenceSettings(
            width=64, height=36, sample_rate=48000, frame_rate={"numerator": 25, "denominator": 1}
        ),
        tracks=[Track(id="v1", kind="video", name="画面")],
        assets={
            "a": {
                "id": "a",
                "kind": "video",
                "label": "底",
                "reference": "r",
                "duration_ticks": 10 * T,
            }
        },
        clips={
            clip_id: Clip(
                id=clip_id,
                asset_id="a",
                track_id="v1",
                position_ticks=index * T,
                duration_ticks=T,
                color=ClipColor(grade=grade),
            )
            for index, (clip_id, grade) in enumerate(clips.items())
        },
    )


def run(target: Project, commands: list[dict]) -> Project:
    """reducer 只吃校验过的命令，和 HTTP 层落进来的同一份。"""
    batch = EditBatch.model_validate(
        {"request_id": "gb", "expected_revision": 1, "commands": commands}
    )
    return apply_commands(target, batch.commands)


def count_suite() -> None:
    published = capabilities()["grade_limits"]["max_inline_samples"]
    assert published == GRADE_INLINE_SAMPLE_LIMIT, (published, GRADE_INLINE_SAMPLE_LIMIT)
    assert grade_inline_samples(project({})) == 0
    one = project({"c": [cube_node()]})
    assert grade_inline_samples(one) == CUBE_SAMPLES, CUBE_SAMPLES
    mixed = project({"c": [one_d_node(), cube_node(), {"kind": "white_balance"}]})
    assert grade_inline_samples(mixed) == 3 * 1024 + CUBE_SAMPLES, grade_inline_samples(mixed)
    # 并联分支里的表也是表：两支各一张 1D，算两条。
    branch = project({"c": [{"kind": "parallel", "branches": [one_d_node(), one_d_node()]}]})
    assert grade_inline_samples(branch) == 2 * 3 * 1024, grade_inline_samples(branch)
    # 停用不是删除：节点还在状态里，就还占着地方。
    off = project({"c": [{**cube_node(), "enabled": False}]})
    assert grade_inline_samples(off) == CUBE_SAMPLES, grade_inline_samples(off)
    nested = project({"c": [cube_node()]}).model_copy(deep=True)
    nested.sequences["s1"] = Sequence(
        id="s1",
        name="子合成",
        duration_ticks=T,
        clips={
            "n": Clip(
                id="n",
                asset_id="a",
                track_id="v1",
                position_ticks=0,
                duration_ticks=T,
                color=ClipColor(grade=[cube_node()]),
            )
        },
    )
    assert grade_inline_samples(nested) == 2 * CUBE_SAMPLES, grade_inline_samples(nested)
    print(
        f"   计数：一张 17³ 是 {CUBE_SAMPLES} 个采样点，1D 按三通道各一行算，并联两支各算，"
        "停用的仍占地方"
    )


def boundary_suite() -> None:
    fits = GRADE_INLINE_SAMPLE_LIMIT // CUBE_SAMPLES
    roomy = project({f"c{index}": [cube_node()] for index in range(fits)})
    assert grade_inline_samples(roomy) <= GRADE_INLINE_SAMPLE_LIMIT, grade_inline_samples(roomy)
    # 恰好装得下的那份状态，改个不动表的名字仍然过。
    renamed = run(
        roomy, [{"op": "track.add", "track": {"id": "v2", "kind": "video", "name": "另一条"}}]
    )
    assert any(track.id == "v2" for track in renamed.tracks)
    over = project({f"c{index}": [cube_node()] for index in range(fits + 1)})
    frozen = over.model_copy(deep=True)
    try:
        run(over, [{"op": "clip.grade", "clip_id": "c0", "grade": [cube_node(), cube_node()]}])
    except Exception as error:  # noqa: BLE001
        assert getattr(error, "code", "") == "GRADE_INLINE_BUDGET", error
        details = error.details  # type: ignore[attr-defined]
        assert details["limit"] == GRADE_INLINE_SAMPLE_LIMIT, details
        assert details["samples"] > details["limit"], details
        assert details["worst_clip_samples"] == 2 * CUBE_SAMPLES, details
        assert details["worst_clip_id"] in over.clips, details
    else:
        raise AssertionError("把工程塞得更满本该点名拒绝")
    assert over == frozen, "被拒的一批不该改动原状态"
    # 已经超额的工程不被锁死：不动表的编辑照过，把表删小更是随时可以。
    untouched = run(
        over, [{"op": "track.add", "track": {"id": "v9", "kind": "video", "name": "腾地方的路"}}]
    )
    assert any(track.id == "v9" for track in untouched.tracks)
    shrunk = run(over, [{"op": "clip.grade", "clip_id": "c0", "grade": []}])
    assert grade_inline_samples(shrunk) == fits * CUBE_SAMPLES, grade_inline_samples(shrunk)
    # 界面里的「复制片段」发的是普通 clip.add（命令表里没有 copy/paste 这一对），所以「×片段数」
    # 这条乘法归同一处管：粘贴两张立方越过额度，一样得整批拒。
    pasted = project({f"c{index}": [cube_node()] for index in range(fits - 1)})
    kept_paste = pasted.model_copy(deep=True)
    try:
        run(
            pasted,
            [
                {
                    "op": "clip.add",
                    "clip": {
                        "id": f"p{index}",
                        "asset_id": "a",
                        "track_id": "v1",
                        "position_ticks": (fits + index) * T,
                        "duration_ticks": T,
                        "color": {"grade": [dict(cube_node())]},
                    },
                }
                for index in range(2)
            ],
        )
    except Exception as error:  # noqa: BLE001
        assert getattr(error, "code", "") == "GRADE_INLINE_BUDGET", error
        assert pasted == kept_paste, "被拒的粘贴不该留下半个片段"
    else:
        raise AssertionError("粘贴越过额度本该整批拒")
    print(
        f"   边界：{fits} 张立方恰好装得下（额度 {GRADE_INLINE_SAMPLE_LIMIT} 个采样点），"
        "再多塞一张就拒；"
        "拒的是「更满」这一步，不是把超额工程冻成只读"
    )


def http_suite() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="agentcut-gradebudget-") as scratch:
        folder = Path(scratch)
        token = "gradebudget-token-0123456789abcdef"
        client = TestClient(
            __import__("agentcut.http_api", fromlist=["create_app"]).create_app(
                folder / "db.sqlite3", token
            ),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {token}"},
        )
        with client:
            created = client.post(
                "/v1/projects",
                json={
                    "request_id": "gb-new",
                    "name": "预算",
                    "settings": {
                        "width": 64,
                        "height": 36,
                        "frame_rate": {"numerator": 25, "denominator": 1},
                    },
                },
            ).json()["project"]
            pid, revision = created["id"], created["revision"]
            fits = GRADE_INLINE_SAMPLE_LIMIT // CUBE_SAMPLES
            clip_ids = [f"c{index}" for index in range(fits + 1)]
            client.post(
                f"/v1/projects/{pid}/edits",
                json={
                    "request_id": "gb-seed",
                    "expected_revision": revision,
                    "commands": [
                        {"op": "track.add", "track": {"id": "v1", "kind": "video", "name": "画面"}},
                        {
                            "op": "asset.register",
                            "asset": {
                                "id": "a",
                                "kind": "video",
                                "label": "底",
                                "reference": "r",
                                "duration_ticks": T,
                            },
                        },
                    ],
                },
            ).json()["project"]
            revision = client.get(f"/v1/projects/{pid}").json()["revision"]
            # 一次一张，装到额度为止——这条路径本身就是给人看的证据。
            for index, clip in enumerate(clip_ids):
                answer = client.post(
                    f"/v1/projects/{pid}/edits",
                    json={
                        "request_id": f"gb-clip-{index}",
                        "expected_revision": revision,
                        "commands": [
                            {
                                "op": "clip.add",
                                "clip": {
                                    "id": clip,
                                    "asset_id": "a",
                                    "track_id": "v1",
                                    "position_ticks": index * T,
                                    "duration_ticks": T,
                                },
                            },
                            {"op": "clip.grade", "clip_id": clip, "grade": [cube_node()]},
                        ],
                    },
                )
                if index == fits:
                    assert answer.status_code == 422, answer.text[:200]
                    problem = answer.json()["error"]
                    assert problem["code"] == "GRADE_INLINE_BUDGET", problem
                    assert problem["details"]["samples"] > problem["details"]["limit"], problem
                    after = client.get(f"/v1/projects/{pid}").json()
                    assert after["revision"] == revision, (after["revision"], revision)
                    assert clip not in after["clips"], "被拒的一条不该留下片段"
                    print(
                        f"   HTTP：第 {index + 1} 张 17³ 被拒（{problem['details']['samples']} > "
                        f"{problem['details']['limit']}），revision 一动没动，片段也没多"
                    )
                    # dry_run 与提交同答。
                    dry = client.post(
                        f"/v1/projects/{pid}/edits",
                        json={
                            "request_id": "gb-dry",
                            "expected_revision": revision,
                            "dry_run": True,
                            "commands": [
                                {
                                    "op": "clip.add",
                                    "clip": {
                                        "id": "z",
                                        "asset_id": "a",
                                        "track_id": "v1",
                                        "position_ticks": 900 * T,
                                        "duration_ticks": T,
                                    },
                                },
                                {"op": "clip.grade", "clip_id": "z", "grade": [cube_node()]},
                            ],
                        },
                    )
                    assert dry.status_code == 422, dry.text[:200]
                    assert dry.json()["error"]["code"] == "GRADE_INLINE_BUDGET", dry.json()
                    # 出路真的走得通：先把最占地方那张换成一条曲线，再塞这张表。
                    worst = problem["details"]["worst_clip_id"]
                    freed = client.post(
                        f"/v1/projects/{pid}/edits",
                        json={
                            "request_id": "gb-free",
                            "expected_revision": revision,
                            "commands": [
                                {
                                    "op": "clip.grade",
                                    "clip_id": worst,
                                    "grade": [
                                        {
                                            "kind": "curve",
                                            "channel": "rgb",
                                            "points": [{"x": 0.0, "y": 0.2}, {"x": 1.0, "y": 0.8}],
                                        }
                                    ],
                                }
                            ],
                        },
                    )
                    assert freed.status_code == 200, freed.text[:200]
                    revision = freed.json()["project"]["revision"]
                    added = client.post(
                        f"/v1/projects/{pid}/edits",
                        json={
                            "request_id": "gb-after-free",
                            "expected_revision": revision,
                            "commands": [
                                {
                                    "op": "clip.add",
                                    "clip": {
                                        "id": "z2",
                                        "asset_id": "a",
                                        "track_id": "v1",
                                        "position_ticks": 901 * T,
                                        "duration_ticks": T,
                                    },
                                },
                                {"op": "clip.grade", "clip_id": "z2", "grade": [cube_node()]},
                            ],
                        },
                    )
                    assert added.status_code == 200, f"腾出地方后仍被拒：{added.text[:200]}"
                    print("   出路：把最占地方的那张换成曲线之后，同一条编辑就过了")
                else:
                    assert answer.status_code == 200, answer.text[:200]
                    revision = answer.json()["project"]["revision"]
            caps = client.get("/v1/capabilities").json()
            assert caps["grade_limits"]["max_inline_samples"] == GRADE_INLINE_SAMPLE_LIMIT, caps
            assert "clip.grade" in caps["commands"], "命令表里得能看到 clip.grade"
            print("   能力：额度只由 capabilities.grade_limits.max_inline_samples 下发一处")


def refusal_suite() -> None:
    # 手搓的载荷也要同一处判：一次事务里加两张超额的表，拒的是整批而不是留下半批。
    fits = GRADE_INLINE_SAMPLE_LIMIT // CUBE_SAMPLES
    base = project({f"c{index}": [cube_node()] for index in range(fits - 1)})
    kept = base.model_copy(deep=True)
    try:
        run(
            base,
            [
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "x1",
                        "asset_id": "a",
                        "track_id": "v1",
                        "position_ticks": (fits - 1) * T,
                        "duration_ticks": T,
                    },
                },
                {"op": "clip.grade", "clip_id": "x1", "grade": [cube_node()]},
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "x2",
                        "asset_id": "a",
                        "track_id": "v1",
                        "position_ticks": fits * T,
                        "duration_ticks": T,
                    },
                },
                {"op": "clip.grade", "clip_id": "x2", "grade": [cube_node()]},
            ],
        )
    except Exception as error:  # noqa: BLE001
        assert getattr(error, "code", "") == "GRADE_INLINE_BUDGET", error
        assert base == kept, "被拒的一批不该部分落进状态"
    else:
        raise AssertionError("一批里超出额度也该拒")
    # 一张表自己就爆额度的情形由契约管（网格上限 17³），这里确认那条路先拒。
    try:
        ClipColor(grade=[{"kind": "lut3d", "title": "t", "size": 18, "cells": [0.0] * (18**3 * 3)}])
    except ValidationError:
        pass
    else:
        raise AssertionError("网格上限本该先拒")
    print("   一批同拒：额度是在候选状态上算的，半批落库这种事没有发生")


def main() -> None:
    count_suite()
    boundary_suite()
    refusal_suite()
    http_suite()
    print(
        f"PASS: 工程级 inline 查找表预算只有一处主人（{GRADE_INLINE_SAMPLE_LIMIT} 个采样点），"
        "越界拒得点名、拒的是整批、出路写在 details 里"
    )


main()
