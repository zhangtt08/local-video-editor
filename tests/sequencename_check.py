"""按可见名点合成（1.213）：名字是入口，身份仍是 id。

夹具不碰媒体、不碰 FFmpeg——`sequence.add` 只要一个 `Sequence`（id / name / duration_ticks），
所以这一档几秒跑完，也不会因为本机缺二进制而假红。量四件事：

1. 名字唯一 → `EditBatch.sequence_name` 写进**那一个**合成，别的合成与主时间线一字不动。
2. 名字撞了 → `SEQUENCE_NAME_AMBIGUOUS`，正文逐条交回撞名的那几个 id；**绝不取第一个**。
   `Sequence.name` 只限长度、没有唯一约束，两次预合成同名是界面本来就允许的做法。
3. 名字找不到 → `SEQUENCE_NAME_NOT_FOUND`，正文点名现有的一共几个、各叫什么、id 是什么。
4. 两个都给 → `SEQUENCE_TARGET_BOTH`；都不给 → 主时间线，与今天一字不差。

还断一条主人：全仓只许有一处把名字折成 id（别处再写一遍 `seq.name ==` 就有两套答案）。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import (
    CreateProject,
    EditBatch,
    EditorError,
    Sequence,
    SequenceAdd,
    capabilities,
)
from agentcut.http_api import create_app
from agentcut.projects import ProjectStore
from agentcut.timeline import resolve_sequence, sequence_view

FRAME = T // 30

# 名字折 id 的主人只许有一处，扫描范围要盖住所有可能再写一遍的模块。
_SCANNED = (
    "contracts.py",
    "timeline.py",
    "projects.py",
    "http_api.py",
    "animation.py",
    "attributes.py",
)


def tail_clips(store: ProjectStore, pid: str) -> None:
    """往 `片尾` 那一个合成里放一条轨与两段带针的片段——回执那几扇门要读的真东西。"""
    revision = store.get(pid).revision
    store.mutate(
        pid,
        EditBatch.model_validate(
            {
                "request_id": "tail-seed",
                "expected_revision": revision,
                "sequence_id": "s-tail",
                "commands": [
                    {"op": "track.add", "track": {"id": "t-tail", "kind": "video", "name": "tail"}},
                    {
                        "op": "asset.register",
                        "asset": {
                            "id": "still",
                            "kind": "image",
                            "label": "still",
                            "reference": "untrusted",
                        },
                    },
                ],
            }
        ),
    )
    for index, clip_id in enumerate(("cx", "cy")):
        store.mutate(
            pid,
            EditBatch.model_validate(
                {
                    "request_id": f"tail-{clip_id}",
                    "expected_revision": store.get(pid).revision,
                    "sequence_id": "s-tail",
                    "commands": [
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": clip_id,
                                "asset_id": "still",
                                "track_id": "t-tail",
                                "position_ticks": index * 2 * FRAME,
                                "duration_ticks": 2 * FRAME,
                                "keyframes": [
                                    {"property": "x", "at_ticks": 0, "value": 0.1 + index / 10}
                                ],
                            },
                        }
                    ],
                }
            ),
        )


def add_sequence(store, pid: str, sid: str, name: str) -> int:
    made = store.mutate(
        pid,
        EditBatch.model_validate(
            {
                "request_id": f"add-{sid}",
                "expected_revision": store.get(pid).revision,
                "commands": [
                    SequenceAdd(
                        op="sequence.add",
                        sequence=Sequence(
                            id=sid, name=name, duration_ticks=FRAME * 12
                        ),
                    )
                ],
            }
        ),
    )
    return made.project.revision


def add_track(store, pid: str, revision: int, tag: str, **target):
    return store.mutate(
        pid,
        EditBatch.model_validate(
            {
                "request_id": f"track-{tag}",
                "expected_revision": revision,
                "commands": [
                    {
                        "op": "track.add",
                        "track": {"id": f"t-{tag}", "kind": "video", "name": tag},
                    }
                ],
                **target,
            }
        ),
    )


def refused(action) -> EditorError:
    try:
        action()
    except EditorError as error:
        return error
    raise AssertionError("这一条该被拒，却写进去了")


def ids(sequence) -> list[str]:
    return [track.id for track in sequence.tracks]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-seqname-") as temp:
        store = ProjectStore(Path(temp) / "db.sqlite3")
        pid = store.create(
            CreateProject(request_id="new", name="名字入口")
        ).project.id
        revision = add_sequence(store, pid, "s-head", "片头")
        revision = add_sequence(store, pid, "s-tail", "片尾")

        # ① 唯一的名字与 id 是同一扇门：落进那一个合成，别处一字不动。
        by_name = add_track(store, pid, revision, "by-name", sequence_name="片尾")
        project = by_name.project
        assert project.revision == revision + 1, "一次批次该只涨一次"
        assert "t-by-name" in ids(project.sequences["s-tail"]), "没写进那一个合成"
        assert "t-by-name" not in ids(project.sequences["s-head"]), "写错了合成"
        assert all(track.id != "t-by-name" for track in project.tracks), "写到主时间线上了"
        revision = project.revision

        # ② 都不给 = 主时间线；只给 id 照旧（这两条是「不改变今天」的对照）。
        plain = add_track(store, pid, revision, "root")
        assert any(track.id == "t-root" for track in plain.project.tracks)
        revision = plain.project.revision
        by_id = add_track(store, pid, revision, "by-id", sequence_id="s-head")
        assert "t-by-id" in ids(by_id.project.sequences["s-head"]), "id 那一路被改坏了"
        revision = by_id.project.revision

        # ③ 两个都给：不猜优先级。
        both = refused(
            lambda: add_track(
                store, pid, revision, "both",
                sequence_id="s-head", sequence_name="片头",
            )
        )
        assert both.code == "SEQUENCE_TARGET_BOTH", both

        # ④ 撞名：绝不取第一个，正文逐条交回。
        revision = add_sequence(store, pid, "s-head2", "片头")
        clash = refused(
            lambda: add_track(store, pid, revision, "clash", sequence_name="片头")
        )
        assert clash.code == "SEQUENCE_NAME_AMBIGUOUS", clash
        assert sorted(clash.details["sequence_ids"]) == ["s-head", "s-head2"]
        after = store.get(pid)
        assert after.revision == revision, "一次拒绝不该涨 revision"
        assert all("t-clash" not in ids(seq) for seq in after.sequences.values())

        # ⑤ 名字找不到：点名现有的一共几个、各叫什么。
        gone = refused(
            lambda: add_track(store, pid, revision, "gone", sequence_name="没有的名字")
        )
        assert gone.code == "SEQUENCE_NAME_NOT_FOUND", gone
        assert len(gone.details["known"]) == 3, gone.details
        assert {row["name"] for row in gone.details["known"]} == {"片头", "片尾"}

        # ⑥ 1.214：读取侧同一扇门（`sequence_view`）。
        #    断的是 id 优先、名字唯一才算数、撞名与找不到都不猜；
        #    17 个读路由共用这一处主人，所以这里量一次就够。
        #    撞名与找不到都不猜」，而且 17 个读路由共用这一处——所以这里量一次就够。
        view_by_name = sequence_view(store.get(pid), "片尾")
        view_by_id = sequence_view(store.get(pid), "s-tail")
        assert [t.id for t in view_by_name.tracks] == [
            t.id for t in view_by_id.tracks
        ], "两条路读到的不是同一份"
        assert [t.id for t in sequence_view(store.get(pid), "s-head").tracks] == ["t-by-id"]
        clash_view = refused(lambda: sequence_view(store.get(pid), "片头"))
        assert clash_view.code == "SEQUENCE_NAME_AMBIGUOUS", clash_view
        assert sorted(clash_view.details["sequence_ids"]) == ["s-head", "s-head2"]
        gone_view = refused(lambda: sequence_view(store.get(pid), "查无此名"))
        assert gone_view.code == "NOT_FOUND", gone_view
        assert len(gone_view.details["known"]) == 3, gone_view.details
        assert gone_view.details["sequence_id"] == "查无此名", gone_view.details

        # ⑦ id 优先：有一个合成的**名字**恰好等于别的合成的 id 时，认出来的必须是那个 id。
        collision = store.mutate(
            pid,
            EditBatch.model_validate(
                {
                    "request_id": "add-collision",
                    "expected_revision": store.get(pid).revision,
                    "commands": [
                        SequenceAdd(
                            op="sequence.add",
                            sequence=Sequence(
                                id="s-shadow", name="s-tail", duration_ticks=FRAME * 12
                            ),
                        )
                    ],
                }
            ),
        ).project
        assert sequence_view(collision, "s-tail").clips == collision.sequences["s-tail"].clips
        assert [t.id for t in sequence_view(collision, "s-tail").tracks] == [
            t.id for t in collision.sequences["s-tail"].tracks
        ], "名字撞上了 id 的优先级——那个 id 指向的合成被名字顶掉了"
        both_named = refused(lambda: sequence_view(collision, "片头"))
        assert both_named.code == "SEQUENCE_NAME_AMBIGUOUS", both_named

        # ⑨ 1.216：回执交回的是**解析后的 id**，不是调用方发进来的那一行。
        #    名字发进去、回给名字，调用方要往下链就得自己再算一次——而它手里没有主人。
        #    只读的那几扇 POST 门（attribute-plan / color-space）与 GET 同一规矩认名字；
        #    写的那一侧（EditBatch.sequence_id）仍只认 id，身份没放宽。
        tail_clips(store, pid)
        token = "sequencename-" + "a" * 34
        with TestClient(
            create_app(store.path, token),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            path = f"/v1/projects/{pid}/clips"
            by_name = client.get(path, params=[("clips", "cx"), ("sequence_id", "片尾")])
            by_id = client.get(path, params=[("clips", "cx"), ("sequence_id", "s-tail")])
            assert by_name.status_code == 200, by_name.text[:300]
            assert by_name.json() == by_id.json(), "名字与 id 两路读到的不是同一份回执"
            assert by_name.json()["sequence_id"] == "s-tail", by_name.json()["sequence_id"]

            manifest = client.get(
                f"/v1/projects/{pid}/preview-manifest", params=[("sequence_id", "片尾")]
            )
            assert manifest.status_code == 200, manifest.text[:200]
            assert manifest.json()["sequence_id"] == "s-tail", manifest.json()["sequence_id"]

            revision = store.get(pid).revision
            plan = client.post(
                f"/v1/projects/{pid}/clips/cx/attribute-plan",
                json={
                    "request_id": "plan-name",
                    "expected_revision": revision,
                    "source_clip_id": "cx",
                    "target_clip_ids": ["cy"],
                    "categories": ["animation"],
                    "sequence_id": "片尾",
                },
            )
            assert plan.status_code == 200, plan.text[:300]
            body = plan.json()["attribute_plan"]
            assert body["sequence_id"] == "s-tail", body["sequence_id"]

            shade = client.post(
                f"/v1/projects/{pid}/clips/cx/color-space", json={"sequence_id": "片尾"}
            )
            assert shade.status_code == 200, shade.text[:300]

            # 交付计划是这一族里最容易「静悄悄分叉」的一处：那一条 GET 认名字，而计划里
            # 「这一条合成交付多久」以前只在 id 认得到时才填。用一条**空合成**量它——
            # 没有片段就没有素材要验，两路交回的整数应当一字不差。
            store.mutate(
                pid,
                EditBatch.model_validate(
                    {
                        "request_id": "empty-seq",
                        "expected_revision": store.get(pid).revision,
                        "commands": [
                            SequenceAdd(
                                op="sequence.add",
                                sequence=Sequence(
                                    id="s-empty", name="空场", duration_ticks=3 * FRAME
                                ),
                            )
                        ],
                    }
                ),
            ).project
            plan_query = [("preset_id", "h264-1080p")]
            named_plan = client.get(
                f"/v1/projects/{pid}/render-plan", params=plan_query + [("sequence_id", "空场")]
            )
            id_plan = client.get(
                f"/v1/projects/{pid}/render-plan", params=plan_query + [("sequence_id", "s-empty")]
            )
            assert named_plan.status_code == 200, named_plan.text[:300]
            assert named_plan.json() == id_plan.json(), (
                "同一条合成，按名字与按 id 交出的不是同一份计划"
            )
            assert named_plan.json()["plan"]["duration_ticks"] == 3 * FRAME, (
                named_plan.json()["plan"]["duration_ticks"]
            )
            print(
                f"1.216 交付计划：空合成「空场」按名字与按 id 交回同一份，"
                f"时长 {named_plan.json()['plan']['duration_ticks']} ticks"
            )

            # 撞名在 HTTP 上仍是那句点名两个 id 的拒绝，回执里没有「猜第一个」。
            clash = client.get(path, params=[("clips", "a"), ("sequence_id", "片头")])
            assert clash.status_code == 422, clash.text[:200]
            assert clash.json()["error"]["code"] == "SEQUENCE_NAME_AMBIGUOUS", clash.json()
            assert sorted(clash.json()["error"]["details"]["sequence_ids"]) == [
                "s-head",
                "s-head2",
            ], clash.json()

            # 反面：写的一扇门不许因为名字进来就少涨一次 revision，也不许悄悄写到别的合成。
            # 数是在这最后一次写入之前取的——上面那一节自己就涨过几次 revision。
            before = store.get(pid).revision
            write = client.post(
                f"/v1/projects/{pid}/edits",
                json={
                    "request_id": "write-by-name",
                    "expected_revision": before,
                    "sequence_id": "片尾",
                    "commands": [
                        {"op": "track.add", "track": {"id": "t-no", "kind": "video", "name": "no"}}
                    ],
                },
            )
            assert write.status_code == 422, write.text[:200]
            after = store.get(pid)
            assert after.revision == before, "一次被拒的写入涨了 revision"
            assert all("t-no" not in [t.id for t in seq.tracks] for seq in after.sequences.values())
            assert all(t.id != "t-no" for t in after.tracks)

        # 主人在哪：回执不许再自己回显调用方那一行（出现即红），也不许多一处名字折 id。
        src = Path(__file__).resolve().parent.parent / "src/agentcut"
        for name in ("http_api.py", "animation.py", "attributes.py"):
            assert '"sequence_id": sequence_id' not in (src / name).read_text(
                encoding="utf-8"
            ), f"{name} 还在原样回显调用方发进来的那一行"
        # 接线：认名字这一步在「读视图」「写回那一条合成」「交付时长」三处都必须过主人。
        for name, needle in (
            ("timeline.py", "target = resolve_sequence(root, sequence_id)"),
            ("timeline.py", "root.sequences[target].tracks = candidate.tracks"),
            ("render.py", "resolved = resolve_sequence(project, sequence_id)"),
            ("render.py", "project.sequences[resolved].duration_ticks"),
        ):
            assert needle in (src / name).read_text(encoding="utf-8"), (name, needle)
        assert "if sequence_id in project.sequences" not in (src / "render.py").read_text(
            encoding="utf-8"
        ), "render 又在认不出的时候当作没有时长（静悄悄那种分叉）"
        texts = {name: (src / name).read_text(encoding="utf-8") for name in _SCANNED}
        owners = sum(text.count("seq.name ==") for text in texts.values())
        assert owners == 1, f"名字折 id 的地方不止一处：{owners}"
        for model, field in (
            ("AttributePlanRequest", "SequenceRef"),
            ("ClipColorSpaceRead", "SequenceRef"),
            ("EditBatch", "Identifier"),
        ):
            block = texts["contracts.py"].split(f"class {model}(")[1].split("\nclass ")[0]
            assert f"sequence_id: {field} | None = None" in block, (model, field)

        # 幂等：把已经解析出来的 id 再交给主人，答案不变（回执链下一跳因此不会漂）。
        root = store.get(pid)
        once = resolve_sequence(root, "片尾")
        assert once == "s-tail" and resolve_sequence(root, once) == once
        assert resolve_sequence(root, None) is None

        caps = capabilities()
        assert caps["features"]["sequence_lookup_by_name"] is True
        assert caps["features"]["sequence_read_by_name"] is True

        # ⑧ 1.215：读的那一侧不再把名字挡在参数校验层。这里钉形状：任何一处再把
        #    sequence_id 声明回 Identifier，中文名就又被 422 拦在门外（那是回归）。
        for name in ("http_api.py", "mcp_server.py"):
            text = (Path(__file__).resolve().parent.parent / "src/agentcut" / name).read_text(
                encoding="utf-8")
            assert "sequence_id: Identifier" not in text, name
            assert "sequence_id: SequenceRef" in text, name
    print(
        "PASS: 名字只是入口——唯一的名字与 id 同一扇门、撞名逐条交回绝不取第一个、"
        "找不到就点名现有名单、两个都给就拒、拒了不涨 revision；"
        "1.216 的回执交回解析后的 id，只读的 POST 门也认名字，写的那一侧仍只认 id"
    )


if __name__ == "__main__":
    main()
