"""1.132: the home page's numbers come from the engine, not from 40 full project downloads.

`refreshProjects()` used to fetch every listed project in order to count its clips. For a normal
project that is wasteful; for the 20,000-clip project measured in 1.131 it is 12,103,495 bytes per
row, fetched before the deep-linked project is even opened — one of the reasons the packaged page
never painted a frame. The store now writes three summary numbers next to each document, and the
list hands them out.

Checked here: the numbers agree with what the full project says, they are recomputed for rows
written before the columns existed, a new write refreshes them, the list payload stays tiny while
the project payload grows, and the renderer no longer pulls whole projects to count them.
"""

import contextlib
import json
import sqlite3
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import CreateProject, EditBatch, Project
from agentcut.http_api import create_app
from agentcut.projects import ProjectStore

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "summary-" + "a" * 52


def seed(store: ProjectStore, name: str, clips: int) -> Project:
    created = store.create(CreateProject(request_id=f"new-{name}", name=name))
    project = created.project
    commands = [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
        {
            "op": "asset.register",
            "asset": {
                "id": "a",
                "kind": "video",
                "label": "a",
                "reference": "r",
                "duration_ticks": (clips + 2) * T,
            },
        },
    ] + [
        {
            "op": "clip.add",
            "clip": {
                "id": f"c{index}",
                "asset_id": "a",
                "track_id": "v",
                "position_ticks": index * T,
                "duration_ticks": T,
            },
        }
        for index in range(clips)
    ]
    batch = EditBatch.model_validate(
        {
            "request_id": f"seed-{name}",
            "expected_revision": project.revision,
            "commands": commands,
        }
    )
    return store.mutate(project.id, batch).project


def summary_of(store: ProjectStore, project_id: str) -> dict:
    row = next(item for item in store.list_projects() if item["id"] == project_id)
    return row


def check(store: ProjectStore, project: Project) -> None:
    from agentcut.contracts import project_content_ticks

    row = summary_of(store, project.id)
    assert row["clips"] == len(project.clips), f"列表这一段对片段数说了假话：{row}"
    assert row["assets"] == len(project.assets), f"列表这一段对素材数说了假话：{row}"
    assert row["content_ticks"] == project_content_ticks(project), (
        f"列表的时长不是引擎那一个数：{row}"
    )
    assert row["name"] == project.name and row["revision"] == project.revision, row
    print(
        "   list row: %s clips=%d assets=%d content=%s ticks (revision %d)"
        % (row["name"], row["clips"], row["assets"], row["content_ticks"], row["revision"])
    )


def structure_suite() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-summary-") as folder:
        path = Path(folder) / "p.sqlite3"
        store = ProjectStore(path)
        big = seed(store, "big", 300)
        small = seed(store, "small", 2)
        check(store, big)
        check(store, small)

        # a write has to refresh the numbers, not just create them
        after = store.get(big.id)
        batch = EditBatch.model_validate(
            {
                "request_id": "one-more",
                "expected_revision": after.revision,
                "commands": [
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "c999",
                            "asset_id": "a",
                            "track_id": "v",
                            "position_ticks": 300 * T,
                            "duration_ticks": T,
                        },
                    }
                ],
            }
        )
        grown = store.mutate(big.id, batch).project
        check(store, grown)
        assert grown.clips.keys() != big.clips.keys(), "the extra clip should have landed"

        # rows written before the columns existed get their numbers on the next open
        with contextlib.closing(sqlite3.connect(path)) as raw:
            with raw:
                raw.execute("UPDATE projects SET clips=NULL, assets=NULL, content_ticks=NULL")
        reopened = ProjectStore(path)
        for project in (grown, small):
            row = summary_of(reopened, project.id)
            assert row["clips"] == len(project.clips), f"旧行没有被补数：{row} / {project.id}"
            assert row["content_ticks"] > 0, row
        with contextlib.closing(sqlite3.connect(path)) as raw:
            version = raw.execute("PRAGMA user_version").fetchone()[0]
            columns = {row[1] for row in raw.execute("PRAGMA table_info(projects)")}
        assert version == 3, version
        assert {"clips", "assets", "content_ticks"} <= columns, columns
        print("   migration: legacy rows are counted once at open, user_version=3")

        # the point of all this: the list is small even when the projects are not
        listed = json.dumps(reopened.list_projects(), ensure_ascii=False).encode("utf-8")
        with contextlib.closing(sqlite3.connect(path)) as raw:
            document = raw.execute(
                "SELECT document FROM projects WHERE id=?", (grown.id,)
            ).fetchone()[0]
        one = Project.model_validate_json(document)
        payload = len(json.dumps(one.model_dump(mode="json"), ensure_ascii=False).encode("utf-8"))
        assert len(listed) * 20 < payload, (len(listed), payload)
        print(
            "   traffic: the list of two projects is %d bytes, "
            "one 301-clip project alone is %d bytes" % (len(listed), payload)
        )


def http_suite() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-summary-http-") as folder:
        root = Path(folder)
        store = ProjectStore(root / "http.sqlite3")
        project = seed(store, "http", 12)
        with TestClient(
            create_app(root / "http.sqlite3", TOKEN),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {TOKEN}"},
        ) as client:
            listed = client.get("/v1/projects?limit=100").json()["projects"][0]
            assert {"clips", "assets", "content_ticks"} <= set(listed), listed
            assert listed["clips"] == len(project.clips), f"HTTP 那一层没把数交出去：{listed}"
            assert listed["content_ticks"] == 12 * T, listed
            caps = client.get("/v1/capabilities").json()
            assert "clip.color_manage" in caps["commands"], "the 1.130 command is still published"
            print("   http: GET /v1/projects hands out the numbers the home page needs")


def renderer_suite() -> None:
    text = (ROOT / "desktop/src/store.ts").read_text(encoding="utf-8")
    start = text.index("export async function refreshProjects()")
    body = text[start : text.index("\n}", start)]
    assert "engine.project(" not in body and "engine!.project(" not in body, body[:400]
    assert "content_ticks" in body, "the list's number has to be the one shown"
    assert "Promise.all" not in body, "no fan-out of per-project reads left in the list path"
    engine = (ROOT / "desktop/src/engine.ts").read_text(encoding="utf-8")
    assert "content_ticks: number" in engine, "the client type has to carry the new keys"
    print("   renderer: refreshProjects asks once, and its type says so")


def main() -> None:
    structure_suite()
    http_suite()
    renderer_suite()
    print(
        "PASS: the project list carries the home page's numbers, legacy rows are counted at open, "
        "and the renderer stopped downloading whole projects to do arithmetic"
    )


if __name__ == "__main__":
    main()
