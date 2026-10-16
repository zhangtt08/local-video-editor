"""1.184：写入回执可以只回数字——`POST /edits?receipt=slim` 不再代带整份工程。

为什么这一笔值得做：`/edits` 的答文里那份工程本体就是正文的大头（1.180 收尾量过一次，1.183 那轮
把同一族里最大的一笔——预览清单——收掉了）。界面要的正是那份状态（它是唯一权威，UI 不许自己算），
所以默认 `full` 一字不动；要省的是「知道自己写了什么、只需要 revision 去接下一笔」的那类调用者。

钉六件事，逐条都能反证：

* **默认那条路没动**：不带 `receipt` 的答文里仍有 `project`，revision 照旧从它里面读。
* **slim 真的没有整份工程**：`project` 这个键根本不在，键集合就是那六个数。
* **slim 给的 revision 能用**：拿它当下一笔的 `expected_revision` 必须写得进去（省了还得够用）。
* **幂等重放照旧**：同一个 `request_id` 再问一次，`replayed` 为真、revision 不涨、也没有工程。
* **dry_run 与 slim 共处**：`committed` 为假、报的是候选那一版，而工程本身没落库。
* **乱写被点名**：`receipt=nope` 回 422，句子里写着两种合法取值；同族那两条（新建、恢复）仍带工程。
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from agentcut.contracts import TIMEBASE, CreateProject, EditBatch  # noqa: E402
from agentcut.http_api import create_app  # noqa: E402
from agentcut.projects import ProjectStore  # noqa: E402

F = TIMEBASE // 30
CLIPS = 200
SLIM_KEYS = {"receipt", "project_id", "revision", "base_revision", "committed", "replayed"}


def seed_commands() -> list:
    commands = [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "pic"}},
        {
            "op": "asset.register",
            "asset": {"id": "m", "kind": "image", "label": "still", "reference": "untrusted"},
        },
    ]
    for index in range(CLIPS):
        commands.append(
            {
                "op": "clip.add",
                "clip": {
                    "id": f"c{index:03d}",
                    "asset_id": "m",
                    "track_id": "v",
                    "position_ticks": index * F,
                    "duration_ticks": F,
                    "keyframes": [
                        {"property": "x", "at_ticks": 0, "value": 0.1},
                        {"property": "x", "at_ticks": F, "value": 0.4},
                    ],
                },
            }
        )
    return commands


def move(request_id: str, revision: int, clip_id: str = "c000", dry: bool = False) -> dict:
    body = {
        "request_id": request_id,
        "expected_revision": revision,
        "commands": [
            {
                "op": "keyframe.set",
                "clip_id": clip_id,
                "keyframe": {"property": "y", "at_ticks": 0, "value": 0.25},
            }
        ],
    }
    if dry:
        body["dry_run"] = True
    return EditBatch.model_validate(body).model_dump(mode="json")


def size(answer) -> int:
    return len(json.dumps(answer.json()).encode())


def main() -> None:
    token = "edit-receipt-" + "a" * 40
    with tempfile.TemporaryDirectory() as folder:
        store = ProjectStore(Path(folder) / "db.sqlite")
        created = store.create(CreateProject(request_id="new", name="receipts")).project
        project_id = created.id
        with TestClient(
            create_app(store.path, token),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            path = f"/v1/projects/{project_id}/edits"
            batch = {
                "request_id": "seed",
                "expected_revision": 0,
                "commands": seed_commands(),
            }
            seeded = client.post(path, json=batch)
            assert seeded.status_code == 200, json.dumps(seeded.json())[:400]
            revision = seeded.json()["project"]["revision"]
            assert len(seeded.json()["project"]["clips"]) == CLIPS

            # 1. 默认那条路：`project` 还在，revision 仍从里面读。
            full = client.post(path, json=move("full-1", revision))
            assert full.status_code == 200, json.dumps(full.json())[:300]
            assert "project" in full.json() and full.json()["committed"] is True
            full_bytes = size(full)
            revision = full.json()["project"]["revision"]

            # 2. slim：整份工程根本不在，键集合就是那六个数。
            slim = client.post(path + "?receipt=slim", json=move("slim-1", revision))
            assert slim.status_code == 200, json.dumps(slim.json())[:300]
            body = slim.json()
            assert "project" not in body, sorted(body)
            assert set(body) == SLIM_KEYS, sorted(body)
            assert body["project_id"] == project_id and body["committed"] is True
            assert body["replayed"] is False
            slim_bytes = size(slim)
            assert slim_bytes * 20 < full_bytes, (slim_bytes, full_bytes)

            # 3. 省下来的那个数必须够用：拿 slim 报的 revision 直接接下一笔。
            assert body["revision"] == revision + 1, (body["revision"], revision)
            nxt = client.post(path + "?receipt=slim", json=move("slim-2", body["revision"]))
            assert nxt.status_code == 200, json.dumps(nxt.json())[:300]
            assert nxt.json()["revision"] == body["revision"] + 1
            revision = nxt.json()["revision"]

            # 4. 幂等重放：同一个 request_id 再问，replayed 真、revision 不涨、也没有工程。
            again = client.post(path + "?receipt=slim", json=move("slim-2", body["revision"]))
            assert again.status_code == 200, json.dumps(again.json())[:300]
            replay = again.json()
            assert replay["replayed"] is True
            assert replay["revision"] == nxt.json()["revision"], replay
            assert "project" not in replay

            # 5. dry_run 与 slim 共处：committed 假、报候选那一版，工程本身不涨。
            dry = client.post(path + "?receipt=slim", json=move("dry-1", revision, dry=True))
            assert dry.status_code == 200, json.dumps(dry.json())[:300]
            assert dry.json()["committed"] is False and dry.json()["revision"] == revision + 1
            assert client.get(f"/v1/projects/{project_id}").json()["revision"] == revision

            # 6. 乱写被点名，且句子里写着两种合法取值。
            bad = client.post(path + "?receipt=nope", json=move("bad-1", revision))
            assert bad.status_code == 422, json.dumps(bad.json())[:300]
            refusal = bad.json()["error"]
            assert refusal["code"] == "INVALID_REQUEST" and refusal["details"]["receipt"] == "nope"
            assert "full" in refusal["message"] and "slim" in refusal["message"], refusal
            # 被拒的那一笔不许留下版本。
            assert client.get(f"/v1/projects/{project_id}").json()["revision"] == revision

            # 同族那两条仍带整份工程：只有 `/edits` 这一条收过口。
            other = client.post("/v1/projects", json={"request_id": "new-2", "name": "again"})
            assert other.status_code == 200 and "project" in other.json()
            restored = client.post(
                f"/v1/projects/{project_id}/restore",
                json={"request_id": "back-1", "expected_revision": revision, "target_revision": 1},
            )
            assert restored.status_code == 200, json.dumps(restored.json())[:300]
            assert "project" in restored.json()
    print(
        f"editreceipt_check: 默认仍带工程、slim 只回六个数（{full_bytes} → {slim_bytes} 字节）、"
        "那个 revision 接得上下一笔、重放与 dry_run 与拒绝都钉住"
    )


if __name__ == "__main__":
    main()
