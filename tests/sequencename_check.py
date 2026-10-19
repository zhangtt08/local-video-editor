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

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import (
    CreateProject,
    EditBatch,
    EditorError,
    Sequence,
    SequenceAdd,
    capabilities,
)
from agentcut.projects import ProjectStore

FRAME = T // 30


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

        caps = capabilities()
        assert caps["features"]["sequence_lookup_by_name"] is True

    owners = 0
    root = Path(__file__).resolve().parent.parent
    for name in ("contracts.py", "timeline.py", "projects.py", "http_api.py"):
        text = (root / "src/agentcut" / name).read_text(encoding="utf-8")
        owners += text.count("seq.name ==")
    assert owners == 1, f"名字折 id 的地方不止一处：{owners}"
    print(
        "PASS: 名字只是入口——唯一的名字与 id 同一扇门、撞名逐条交回绝不取第一个、"
        "找不到就点名现有名单、两个都给就拒、拒了不涨 revision"
    )


if __name__ == "__main__":
    main()
