"""1.183：预览清单的 `clips` 子集只是一层视图，不是第二条编译路径。

两万段工程的实测（验收存储 `scale_paths_1183.log`）：整份清单 5,516 ms / 33.11 MB，而只读三段
根本不该付这个价。子集仍在 `preview_manifest` 这一个编译者里筛，所以这里钉的是「少给 ≠ 改口径」。

钉六件事，逐条都能反证：

* **同一条目 == 同一份字节**：子集里每条 clip，逐字段等于全量那份的同一条。
* **工程级的键不跟着缩**：混合轨、合成模式、链接状态、revision 两边一字不差。
* **邻段被筛掉，淡还在**：只点名前一段时，它的淡尾曲线仍与全量相等——那条曲线住在后一段的
  `transition_in` 里，所以「按子集筛片段」绝不能把索引也一起筛掉。
* **嵌套合成跟着一起缩**：递归把子集传下去，`sequences[…]["clips"]` 里同一条仍是同一份字节——
  不然只点名一段照样把整份拖回来。
* **默认那条路没动**：不带 `clips` 的 GET 与「点名全部 id（含重复）」的 GET 字节相同。
* **三种乱要法都被拒**：不存在的段名点名拒（404）、空白段名 422、超过 `capabilities` 下发的上限
  422 并报出请求数与上限；被拒之后正常那条路仍然走得通。
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from agentcut.animation import preview_manifest  # noqa: E402
from agentcut.contracts import (  # noqa: E402
    CLIP_SUBSET_LIMIT,
    Clip,
    CreateProject,
    EditBatch,
    Keyframe,
    Project,
    Sequence,
    ShapeMask,
    Track,
    Transition,
    capabilities,
)
from agentcut.http_api import create_app  # noqa: E402
from agentcut.projects import ProjectStore  # noqa: E402

F = 70_560_000 // 30


def clip(id_: str, **update) -> Clip:
    base = {
        "id": id_,
        "asset_id": "m",
        "track_id": "v",
        "position_ticks": 0,
        "duration_ticks": 10 * F,
        "keyframes": [
            Keyframe(property="x", at_ticks=0, value=0.1),
            Keyframe(property="x", at_ticks=5 * F, value=0.7),
            Keyframe(property="opacity", at_ticks=2 * F, value=0.4),
        ],
        "mask": ShapeMask(
            shape="ellipse", center_x=0.5, center_y=0.5, width=0.4, height=0.3, rotation=12.0
        ),
    }
    base.update(update)
    return Clip(**base)


def seeded(store: ProjectStore) -> str:
    """一条带盒遮罩与两枚针的 `a`，一段与它重叠、把淡带进来的 `b`，一段什么都不动的 `c`。"""
    project = store.create(CreateProject(request_id="new", name="subset")).project
    first = clip("a")
    second = clip(
        "b",
        position_ticks=8 * F,
        mask=None,
        transition_in=Transition(from_clip_id="a", kind="dissolve", duration_ticks=2 * F),
    )
    third = clip("c", position_ticks=18 * F, mask=None, keyframes=[])
    commands = [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "pic"}},
        {
            "op": "asset.register",
            "asset": {"id": "m", "kind": "image", "label": "still", "reference": "untrusted"},
        },
        *[
            {"op": "clip.add", "clip": item.model_dump(mode="json")}
            for item in (first, second, third)
        ],
    ]
    store.mutate(
        project.id,
        EditBatch.model_validate(
            {"request_id": "seed", "expected_revision": 0, "commands": commands}
        ),
    )
    return project.id


def whole_project_keys(manifest: dict) -> dict:
    return {key: value for key, value in manifest.items() if key != "clips"}


def in_process(project) -> None:
    full = preview_manifest(project)
    assert sorted(full["clips"]) == ["a", "b", "c"], sorted(full["clips"])

    single = preview_manifest(project, clip_ids=["a"])
    assert sorted(single["clips"]) == ["a"], sorted(single["clips"])
    # 「少给 ≠ 改口径」：留下的那一条必须与全量的同一条逐字节相同。
    assert single["clips"]["a"] == full["clips"]["a"]
    # 淡尾住在 `b.transition_in` 里，只点名 `a` 时它不能消失或改形状。
    assert single["clips"]["a"]["transition"] == full["clips"]["a"]["transition"]
    assert json.dumps(single["clips"]["a"]["transition"]) != json.dumps(
        {"picture": [], "sound": []}
    ), "the transition envelope came back empty, so this case proves nothing"
    # 工程级事实不属于某一段片段，子集请求不许把它们一起缩掉。
    assert whole_project_keys(single) == whole_project_keys(full)

    pair = preview_manifest(project, clip_ids=["b", "c"])
    assert pair["clips"] == {k: full["clips"][k] for k in ("b", "c")}
    # 什么都不动的那一段，取它自己与在全量里也必须是同一份字节。
    assert pair["clips"]["c"] == full["clips"]["c"]
    assert preview_manifest(project, clip_ids=["a", "b", "c"]) == full
    assert preview_manifest(project, clip_ids=[]) == {**full, "clips": {}}


def over_http(project_id: str, client: TestClient) -> None:
    path = f"/v1/projects/{project_id}/preview-manifest"
    full = client.get(path).json()
    # 桌面合成器发的就是这一条 URL，所以子集只能是外加的一层，默认那条路一字不变。
    named = client.get(
        path, params=[("clips", "a"), ("clips", "b"), ("clips", "c"), ("clips", "a")]
    )
    assert named.status_code == 200
    assert named.json() == full, "naming every clip changed the reply, not just its size"
    subset = client.get(path, params=[("clips", "b")]).json()
    assert subset["clips"] == {"b": full["clips"]["b"]}
    assert whole_project_keys(subset) == whole_project_keys(full)

    gone = client.get(path, params=[("clips", "a"), ("clips", "nope")])
    assert gone.status_code == 404, gone.json()
    refusal = gone.json()["error"]
    assert refusal["code"] == "NOT_FOUND"
    assert refusal["details"]["clip_ids"] == "nope", gone.json()

    # 1.187：「这一段都别编译」得有自己的一句话（列表参数不能为空）：清空片段表，
    # 但工程级那几个键一个不许少；两种说法同时出现要被拒。
    none = client.get(path, params=[("no_clips", "1")]).json()
    assert none["clips"] == {}, sorted(none["clips"])
    assert whole_project_keys(none) == whole_project_keys(full)
    assert capabilities()["features"]["preview_manifest_no_clips"] is True
    both = client.get(path, params=[("no_clips", "1"), ("clips", "a")])
    assert both.status_code == 422, both.json()
    refusal = both.json()["error"]
    assert refusal["code"] == "INVALID_REQUEST" and refusal["details"]["named"] == 1, refusal

    blank = client.get(path + "?clips=")
    assert blank.status_code == 422, blank.json()
    # 空白段名不是「什么都别描述」：它连合法 id 都不是，拒的时候要能看出拒的是哪一个参数。
    assert blank.json()["error"]["code"] == "INVALID_REQUEST", blank.json()
    assert "clips" in json.dumps(blank.json()), blank.json()

    too_many = client.get(path, params=[("clips", "a")] * (CLIP_SUBSET_LIMIT + 1))
    assert too_many.status_code == 422, too_many.json()
    body = too_many.json()["error"]
    assert body["code"] == "INVALID_REQUEST" and body["details"]["limit"] == 256, body
    assert body["details"]["requested"] == CLIP_SUBSET_LIMIT + 1, body
    # 拒了不能顺手把正常那条路也堵住。
    assert client.get(path, params=[("clips", "a")]).json()["clips"] == {
        "a": full["clips"]["a"]
    }
    assert capabilities()["features"]["preview_manifest_clips_max"] == 256


def nested() -> None:
    """嵌套合成里的同一子集：递归把 `clip_ids` 往下传，否则点名一段照样拖回整份。"""
    root = Project(
        id="p",
        name="p",
        tracks=[Track(id="v", kind="video", name="pic")],
        clips={"one": clip("one"), "two": clip("two", position_ticks=8 * F)},
        sequences={
            "s": Sequence(
                id="s",
                name="sub",
                duration_ticks=12 * F,
                tracks=[Track(id="v2", kind="video", name="sub")],
                clips={
                    "one": clip("one", track_id="v2"),
                    "two": clip("two", track_id="v2", position_ticks=8 * F),
                },
            )
        },
    )
    full = preview_manifest(root)
    assert sorted(full["sequences"]["s"]["clips"]) == ["one", "two"]
    sub = preview_manifest(root, clip_ids=["one"])
    assert list(sub["clips"]) == ["one"], list(sub["clips"])
    assert list(sub["sequences"]["s"]["clips"]) == ["one"], list(sub["sequences"]["s"]["clips"])
    assert sub["sequences"]["s"]["clips"]["one"] == full["sequences"]["s"]["clips"]["one"]


def main() -> None:
    token = "preview-subset-" + "a" * 40
    with tempfile.TemporaryDirectory() as folder:
        store = ProjectStore(Path(folder) / "db.sqlite")
        project_id = seeded(store)
        with TestClient(
            create_app(store.path, token),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            over_http(project_id, client)
        in_process(store.get(project_id))
    nested()
    print("previewsubset_check: 子集是视图（字节相同、工程级键不缩、淡尾留住）与三种拒绝都钉住")


if __name__ == "__main__":
    main()
