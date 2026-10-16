"""1.186：`GET /v1/projects/{id}/clips?clips=…` 只读被点名的那几段，不搬整份文档。

两万段工程实测整份工程回执 738 ms / 11.99 MB（`scale_paths_1183.log` 那一轮量的），而 Agent 十次里有
九次只关心几段的记录。这一条**不新增任何判断**：交回的每条 clip 就是那份文档里的同一条，逐字节相同；
`sequence_view` 用的也是预览清单那一个函数，不另写一套「合成里怎么看片段」。

钉五件事，逐条都能反证：

* **同一条 == 同一份字节**：点名叫回的 clip 与 `GET /v1/projects/{id}` 文档里的那条完全相等。
* **顺序与去重跟着调用方**：`clips=c&clips=a&clips=c` 交回 `["c","a"]`——不多不少、不重排。
* **不点名就被拒**：`clips` 是必需的，那句拒绝要指一条真出路（整份文档那条路由），而不是悄悄回空表。
* **不存在的段名点名拒**：404 带 `details.clip_ids`；超过上限 422 带 `requested` 与 `limit`。
* **上限只有一处说法**：`capabilities` 里 `project_clips_max` 与 `preview_manifest_clips_max` 都等于
  契约里那一个常数（同一条 query string 的预算，不该有两个数）。
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from agentcut.contracts import (  # noqa: E402
    CLIP_SUBSET_LIMIT,
    CreateProject,
    EditBatch,
    capabilities,
)
from agentcut.http_api import create_app  # noqa: E402
from agentcut.projects import ProjectStore  # noqa: E402

F = 70_560_000 // 30


def seeded(store: ProjectStore) -> str:
    project = store.create(CreateProject(request_id="new", name="clipread")).project
    commands = [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "pic"}},
        {
            "op": "asset.register",
            "asset": {"id": "m", "kind": "image", "label": "still", "reference": "untrusted"},
        },
    ]
    for index, clip_id in enumerate(("a", "b", "c")):
        commands.append(
            {
                "op": "clip.add",
                "clip": {
                    "id": clip_id,
                    "asset_id": "m",
                    "track_id": "v",
                    "position_ticks": index * 4 * F,
                    "duration_ticks": 4 * F,
                    "keyframes": [{"property": "x", "at_ticks": 0, "value": 0.1 + index / 10}],
                },
            }
        )
    store.mutate(
        project.id,
        EditBatch.model_validate(
            {"request_id": "seed", "expected_revision": 0, "commands": commands}
        ),
    )
    return project.id


def main() -> None:
    token = "clip-read-" + "a" * 40
    with tempfile.TemporaryDirectory() as folder:
        store = ProjectStore(Path(folder) / "db.sqlite")
        project_id = seeded(store)
        with TestClient(
            create_app(store.path, token),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            whole = client.get(f"/v1/projects/{project_id}").json()
            path = f"/v1/projects/{project_id}/clips"

            named = client.get(path, params=[("clips", "a"), ("clips", "b")])
            assert named.status_code == 200, json.dumps(named.json())[:300]
            body = named.json()
            assert body["project_id"] == project_id and body["revision"] == whole["revision"]
            assert body["sequence_id"] is None
            # 「不多不少」：键集合就是点名的那些，值与整份文档里的同一条逐字节相同。
            assert sorted(body["clips"]) == ["a", "b"], sorted(body["clips"])
            for clip_id in ("a", "b"):
                assert body["clips"][clip_id] == whole["clips"][clip_id], clip_id
            # 省在哪要说得出：这条根本不回文档的那几个键（不是「碰巧小一点」）。
            assert set(body) == {"project_id", "revision", "sequence_id", "clips"}, sorted(body)
            for extra in ("settings", "tracks", "assets", "sequences", "name"):
                assert extra not in body, extra

            order = client.get(path, params=[("clips", "c"), ("clips", "a"), ("clips", "c")])
            assert list(order.json()["clips"]) == ["c", "a"], list(order.json()["clips"])
            assert order.json()["clips"]["c"] == whole["clips"]["c"]

            bare = client.get(path)
            assert bare.status_code == 422, json.dumps(bare.json())[:300]
            refusal = bare.json()["error"]
            assert refusal["code"] == "INVALID_REQUEST"
            # 拒绝必须指一条真走得通的出路，而不是把人支到墙上。
            assert f"/v1/projects/{project_id}" in refusal["message"], refusal
            assert client.get(f"/v1/projects/{project_id}").status_code == 200

            gone = client.get(path, params=[("clips", "a"), ("clips", "nope")])
            assert gone.status_code == 404, json.dumps(gone.json())[:300]
            assert gone.json()["error"]["details"]["clip_ids"] == "nope", gone.json()

            too_many = client.get(path, params=[("clips", "a")] * (CLIP_SUBSET_LIMIT + 1))
            assert too_many.status_code == 422, json.dumps(too_many.json())[:300]
            over = too_many.json()["error"]
            assert over["details"]["limit"] == CLIP_SUBSET_LIMIT
            assert over["details"]["requested"] == CLIP_SUBSET_LIMIT + 1
            # 被拒之后正常那条路仍走得通（守卫不许顺手把门堵死）。
            kept = client.get(path, params=[("clips", "a")]).json()["clips"]["a"]
            assert kept == whole["clips"]["a"]

    features = capabilities()["features"]
    assert features["project_clips_max"] == 256 == features["preview_manifest_clips_max"], features
    print(
        f"clipread_check: 点名的段与整份文档里同一条相等（{len(json.dumps(whole))} → "
        f"{len(json.dumps(body))} 字节），顺序去重、三种拒绝与「上限只有一个数」都钉住"
    )


if __name__ == "__main__":
    main()
