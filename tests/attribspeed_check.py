"""1.179 粘贴属性的规划成本：整串一次过 reducer，逐段重问只在被拒之后，两条路交回同一份报告。

两万段工程的实测（验收存储 `scale_attributes.log`）：64 个目标的规划要 **118.9 s**，而同一批命令
真正写下去只要 2,985 ms——因为「每个目标把已收下的那串再重放一遍」在 13.4 MB 的工程上就是把整份
工程重放 64 遍。这一版改成先一次过整串；只有那一次被拒才退回逐段、逐类重问（一次编辑的上限那条
判断读的是真正落进去的条数，不能不重问）。

钉四件事，每条都能反证：

* **只过一遍**：一串全都接得下时 `apply_commands` 恰好被叫 1 次——不是 1 + 目标数，也不是类别数。
* **两条路一字不差**：把 1.178 那套「逐段累积重放」用产品自己的原件（`_category_commands` 与
  `apply_commands`）在测试里再跑一遍，命令表、`written`、`unchanged`、`refusals`、越界针数逐项相等。
  全都接得下、有一部分被拒、被一次编辑的上限截断，三份夹具各比一次。
* **拒了才重问**：被拒那两份夹具里调用次数必须 > 1，否则这条门禁根本看不见慢路。
* **没东西可搬就一次都不问**：整串为空时 reducer 一次都不该被叫。
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from attributepaste_check import fixture  # noqa: E402

from agentcut import attributes  # noqa: E402
from agentcut.attributes import (  # noqa: E402
    ATTRIBUTE_IDS,
    _category_commands,
    attribute_plan,
)
from agentcut.contracts import (  # noqa: E402
    ATTRIBUTE_CATEGORY_IDS,
    EditBatch,
    EditorError,
    Stabilization,
)
from agentcut.timeline import apply_commands  # noqa: E402

FIELDS = ("commands", "written", "unchanged", "refusals", "beyond_tail_keyframes")


@contextmanager
def counting():
    """数 `attributes` 那一头真正叫了几次 reducer，行为一点不变（转发给同一个原件）。"""
    calls: list[int] = []
    real = attributes.apply_commands

    def spy(project, commands, sequence_id=None):
        calls.append(len(commands))
        return real(project, commands, sequence_id)

    attributes.apply_commands = spy
    try:
        yield calls
    finally:
        attributes.apply_commands = real


def reference(project, source_id: str, target_ids: list[str], categories: list[str]) -> dict:
    """1.178 的那一路，原样搬进测试当尺子：每段都把「已收下的 + 这一段的」整串重放一次。"""
    root = project
    source = root.clips[source_id]
    accepted: list[dict] = []
    written: list[dict] = []
    unchanged: list[str] = []
    refusals: list[dict] = []
    beyond_tail = 0

    def commit(commands: list[dict]) -> dict | None:
        nonlocal accepted
        batch = EditBatch.model_validate(
            {"request_id": "ref", "expected_revision": 0, "commands": accepted + commands}
        )
        try:
            apply_commands(root, batch.commands)
        except EditorError as error:
            return {"code": error.code, "message": error.message, "details": error.details}
        accepted += commands
        return None

    targets = [item for item in dict.fromkeys(target_ids) if item != source_id]
    for clip_id in sorted(targets, key=lambda item: root.clips[item].position_ticks):
        groups: list[tuple[str, list[dict], int]] = []
        for category in categories:
            commands, beyond = _category_commands(category, source, root.clips[clip_id])
            if commands:
                groups.append((category, commands, beyond))
        if not groups:
            unchanged.append(clip_id)
            continue
        whole = [command for _, commands, _ in groups for command in commands]
        if len(accepted) + len(whole) > attributes.MAX_COMMANDS_PER_BATCH:
            refusals.append(attributes._over_limit(clip_id, len(whole), len(accepted)))
            continue
        error = commit(whole)
        if error is None:
            beyond_tail += sum(beyond for _, _, beyond in groups)
            written.append({"clip_id": clip_id, "categories": [name for name, _, _ in groups]})
            continue
        landed: list[str] = []
        for category, commands, beyond in groups:
            error = commit(commands)
            if error is None:
                landed.append(category)
                beyond_tail += beyond
            else:
                refusals.append({**error, "clip_id": clip_id, "category": category})
        if landed:
            written.append({"clip_id": clip_id, "categories": landed})
    return {
        "commands": accepted,
        "written": written,
        "unchanged": unchanged,
        "refusals": refusals,
        "beyond_tail_keyframes": beyond_tail,
    }


def same_report(plan: dict, want: dict, label: str) -> None:
    bad = [name for name in FIELDS if plan[name] != want[name]]
    assert not bad, f"{label}：快慢两条路在这些项上不一样：{bad}"


def stabilised(project):
    project.clips["b"].stabilization = Stabilization(
        strength=0.8,
        max_crop=0.1,
        points=20,
        translation_correction=4.0,
        roll_correction=0.2,
        zoom_to_hide_borders=1.05,
        analysed_frames=30,
    )
    return project


def all_land() -> dict:
    """三段画面全接得下：整串一次过，reducer 恰好被叫 1 次。"""
    project = fixture()
    targets = ["a", "b", "narrow"]
    with counting() as calls:
        plan = attribute_plan(project, "src", targets, list(ATTRIBUTE_CATEGORY_IDS))
    want = reference(project, "src", targets, list(ATTRIBUTE_CATEGORY_IDS))
    same_report(plan, want, "全都接得下")
    assert plan["refusals"] == [], f"三段画面之间不该有拒绝：{plan['refusals']}"
    assert len(plan["written"]) == 3, f"三段都该落进去：{plan['written']}"
    assert calls == [len(plan["commands"])], f"整串一次过才对，实际叫了 {len(calls)} 次：{calls}"
    return {"passes": len(calls), "commands": len(plan["commands"])}


def partial_refusal() -> dict:
    """有一部分接不下：那一次整串被拒，之后逐段逐类重问，报告与 1.178 那一路一字不差。"""
    out = {}
    for label, targets, make in (
        ("稳定过的那段", ["b"], stabilised),
        ("混着音频段", ["a", "b", "aud"], stabilised),
    ):
        project = make(fixture())
        whole = [
            command
            for clip_id in targets
            for category in ATTRIBUTE_IDS
            for command in _category_commands(
                category, project.clips["src"], project.clips[clip_id]
            )[0]
        ]
        with counting() as calls:
            plan = attribute_plan(project, "src", targets, list(ATTRIBUTE_CATEGORY_IDS))
        want = reference(project, "src", targets, list(ATTRIBUTE_CATEGORY_IDS))
        same_report(plan, want, label)
        assert plan["refusals"], f"{label}：这份夹具本来就该有拒绝，好让慢路被走到"
        assert len(calls) > 1, f"{label}：被拒之后只问了一次，慢路根本没跑到"
        assert calls[0] == len(whole), (
            f"{label}：头一次问该把整串候选都带上（{len(whole)} 条），实际是 {calls[0]} 条"
        )
        out[label] = {"passes": len(calls), "refusals": len(plan["refusals"])}
    return out


def limit_recounted() -> dict:
    """上限读的是真正落进去的条数：整串被拒之后那几条预筛拒绝必须整个重数，不能留一半。

    两份夹具都靠「音频段排在最前（位置 0）且接不下调色」把整串那次问弄失败：
    - 上限 1：连第一段都装不下，预筛就把三段全拒了，reducer 一次都不该被叫；
    - 上限 2：预筛以为音频段那 2 条落得进去，于是第二段是「2+2=4 条」被拒；真正走慢路时
      音频段只落 1 条（effects），第二段该按「1+2=3 条」被拒。数目不同，正是这条分支的签名。
    """
    out = {}
    for label, limit, targets, want_commands in (
        ("上限 1：一段都装不下", 1, ["aud", "a", "b"], None),
        ("上限 2：慢路重新数", 2, ["aud", "a"], 3),
    ):
        project = fixture()
        real = attributes.MAX_COMMANDS_PER_BATCH
        attributes.MAX_COMMANDS_PER_BATCH = limit
        try:
            with counting() as calls:
                plan = attribute_plan(project, "src", targets, ["color", "effects"])
            want = reference(project, "src", targets, ["color", "effects"])
        finally:
            attributes.MAX_COMMANDS_PER_BATCH = real
        same_report(plan, want, label)
        assert plan["refusals"], f"{label}：上限收到 {limit} 还没有任何截断，夹具没在量这条分支"
        if want_commands is None:
            assert calls == [], f"{label}：一段都装不下却问了 reducer：{calls}"
            assert all(row["category"] is None for row in plan["refusals"]), plan["refusals"]
        else:
            assert len(calls) > 1, f"{label}：被拒之后没有逐段重问"
            rows = [row for row in plan["refusals"] if row["category"] is None]
            assert [row["details"]["commands"] for row in rows] == [want_commands], (
                f"{label}：预筛那几条拒绝没被重数，交回的是 {rows}"
            )
        out[label] = {"passes": len(calls), "refusals": len(plan["refusals"])}
    return out


def nothing_to_move() -> dict:
    """没东西可搬：整串为空，reducer 一次都不该被叫。"""
    project = fixture()
    project.clips["a"].speed_percent = project.clips["src"].speed_percent
    with counting() as calls:
        plan = attribute_plan(project, "src", ["a"], ["speed"])
    assert calls == [], f"一段都没话要说却问了 reducer：{calls}"
    assert plan["commands"] == [] and plan["unchanged"] == ["a"], plan
    return {"unchanged": plan["unchanged"]}


def vocabulary_stays() -> None:
    """一次都不涨 revision，规划也不许改手里那份工程（读的是同一份状态）。"""
    project = fixture()
    before = project.model_dump()
    with counting() as calls:
        attribute_plan(project, "src", ["a", "b", "narrow"], list(ATTRIBUTE_CATEGORY_IDS))
    assert len(calls) == 1
    assert project.model_dump() == before, "规划把自己那份工程改了"
    assert set(ATTRIBUTE_IDS) == set(ATTRIBUTE_CATEGORY_IDS), "类别名单有了第二份主人"


def main() -> None:
    moved = all_land()
    refused = partial_refusal()
    capped = limit_recounted()
    empty = nothing_to_move()
    vocabulary_stays()
    print(
        f"   全都接得下：{moved['commands']} 条命令、reducer 被叫 {moved['passes']} 次"
        "（1.178 那一路要按段数问）"
    )
    for label, row in refused.items():
        print(f"   {label}：问了 {row['passes']} 次、拒 {row['refusals']} 条，报告与旧路相等")
    for label, row in capped.items():
        print(f"   {label}：问了 {row['passes']} 次、拒 {row['refusals']} 条，两条路相等")
    print(f"   没东西可搬：一次都没问，unchanged={empty['unchanged']}")
    print("PASS: 规划的快路只过一遍 reducer，慢路被拒时才接手，两条路交回同一份报告")


if __name__ == "__main__":
    main()
