"""Timeline markers: the reducer owns them, the split plan only names ordinary `clip.split`
commands, and a human's beat mark and an Agent's `marker.set` land on the same integer tick.

The plan is asserted in exact frame ticks because the whole point of a marker is to cut at a
specific frame — a plan that is "about right" would leave a one-frame flash at every beat.
"""

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import (
    Asset,
    Clip,
    CreateProject,
    EditBatch,
    EditorError,
    Project,
    RestoreProject,
    Track,
    project_content_ticks,
)
from agentcut.http_api import create_app
from agentcut.markers import split_plan
from agentcut.projects import ProjectStore
from agentcut.timeline import apply_commands, validate_timeline

WIDTH, HEIGHT, FPS = 320, 180, 30
FRAME = T // FPS


def frames(count: int) -> int:
    return count * T // FPS


def clip(clip_id: str, track_id: str, start: int, length: int) -> Clip:
    return Clip(
        id=clip_id,
        asset_id="a",
        track_id=track_id,
        position_ticks=frames(start),
        duration_ticks=frames(length),
    )


def project() -> Project:
    return Project(
        id="p",
        name="markers",
        tracks=[Track(id="v", kind="video", name="v"), Track(id="w", kind="video", name="w")],
        assets={"a": Asset(id="a", kind="image", label="a", reference="r")},
        clips={
            "c1": clip("c1", "v", 0, 40),
            "c2": clip("c2", "v", 50, 30),
            "c3": clip("c3", "w", 0, 100),
        },
    )


def edit(target: Project, commands: list, request_id: str = "check") -> Project:
    batch = EditBatch(request_id=request_id, expected_revision=target.revision, commands=commands)
    return apply_commands(target, batch.commands)


def marker(mid: str, at_frames: int, name: str = "beat", **changes) -> dict:
    body = {"id": mid, "at_ticks": frames(at_frames), "name": name} | changes
    return {"op": "marker.set", "marker": body}


def marked() -> Project:
    # a: inside c1 and c3.  b: on c1's trailing edge (and in the gap before c2), inside c3.
    # c: inside c2 and c3.  A mark past every clip cannot exist at all: the reducer refuses it,
    # so "this mark cut nothing" is only ever about an edge or a gap, which the track filter shows.
    return edit(
        project(),
        [marker("a", 20), marker("b", 40, "on the edge"), marker("c", 60, "punch in")],
    )


def reducer_suite() -> None:
    start = project()
    assert start.markers == [] and project_content_ticks(start) == frames(100)

    moved = edit(start, [marker("m1", 10), marker("m2", 40, "punch in")])
    assert [(m.id, m.at_ticks) for m in moved.markers] == [("m1", frames(10)), ("m2", frames(40))]

    # The same id means the same mark: it moves and renames, it does not pile up.
    upserted = edit(moved, [marker("m1", 12, "moved beat")])
    assert [(m.id, m.at_ticks) for m in upserted.markers] == [
        ("m1", frames(12)),
        ("m2", frames(40)),
    ]
    recolored = edit(upserted, [marker("m2", 40, "punch in", color="cyan")])
    assert [(m.color, m.at_ticks) for m in recolored.markers] == [
        ("amber", frames(12)),
        ("cyan", frames(40)),
    ]

    gone = edit(recolored, [{"op": "marker.remove", "marker_id": "m1"}])
    assert [m.id for m in gone.markers] == ["m2"]

    for bad, code in (
        ([marker("far", 101)], "INVALID_MARKER"),
        ([{"op": "marker.remove", "marker_id": "nope"}], "NOT_FOUND"),
        ([marker("ok", 5), marker("ok2", 200)], "INVALID_MARKER"),
    ):
        try:
            edit(recolored, bad)
        except EditorError as error:
            assert error.code == code, (code, error.code, error.message)
        else:
            raise AssertionError(f"{bad} should have been refused")

    # One batch may lengthen the content and then mark inside the new part: the horizon is the
    # content as it stands when the command is reached, not as it was when the batch started.
    extended = edit(
        gone,
        [
            {
                "op": "clip.add",
                "clip": {
                    "id": "c4",
                    "asset_id": "a",
                    "track_id": "w",
                    "position_ticks": frames(100),
                    "duration_ticks": frames(20),
                },
            },
            marker("late", 115, "after the extension"),
        ],
    )
    assert [m.id for m in extended.markers] == ["m2", "late"]

    # A hand-written project with two marks sharing an id is refused, not silently deduplicated.
    tampered = extended.model_copy(deep=True)
    tampered.markers = [tampered.markers[0], tampered.markers[0].model_copy(deep=True)]
    try:
        validate_timeline(tampered)
    except EditorError as error:
        assert error.code == "INVALID_PROJECT", error.message
    else:
        raise AssertionError("duplicate marker ids have to be refused")

    # Reading a pre-v11 snapshot keeps working: no markers key means no markers, not a crash.
    legacy = Project.model_validate(
        {
            "schema_version": 10,
            "id": "old",
            "name": "legacy",
            "revision": 4,
            "tracks": [{"id": "v", "kind": "video", "name": "v"}],
            "assets": {"a": {"id": "a", "kind": "image", "label": "a", "reference": "r"}},
            "clips": {},
        }
    )
    assert legacy.markers == [] and legacy.schema_version == 10
    validate_timeline(legacy)
    print(
        "   reducer: upsert moves one mark, the horizon follows the content, "
        "v10 snapshots still read"
    )


def plan_suite() -> None:
    source = marked()
    plan = split_plan(source)
    assert plan["markers"] == 3 and plan["clips"] == 3 and plan["splits"] == 5, plan
    assert plan["unused"] == [], plan["unused"]
    assert plan["content_ticks"] == frames(100)
    # Clips are visited by (position, id) and each clip is cut right to left, so the ids the plan
    # mints are deterministic: the same project always produces the same batch.
    assert [(c["clip_id"], c["at_ticks"], c["right_clip_id"]) for c in plan["commands"]] == [
        ("c1", frames(20), "c1-m0"),
        ("c3", frames(60), "c3-m0"),
        ("c3", frames(40), "c3-m1"),
        ("c3", frames(20), "c3-m2"),
        ("c2", frames(60), "c2-m0"),
    ], plan["commands"]

    cut = edit(source, plan["commands"])
    assert len(cut.clips) == 8, sorted(cut.clips)
    for origin in ("c1", "c2", "c3"):
        pieces = sorted(
            (item.position_ticks, item.position_ticks + item.duration_ticks)
            for item in cut.clips.values()
            if item.id == origin or item.id.startswith(f"{origin}-m")
        )
        was = source.clips[origin]
        assert pieces[0][0] == was.position_ticks and pieces[-1][1] == (
            was.position_ticks + was.duration_ticks
        ), (origin, pieces)
        assert all(left[1] == right[0] for left, right in zip(pieces, pieces[1:])), (origin, pieces)
        assert all(stop > start for start, stop in pieces), (origin, pieces)
    assert [m.at_ticks for m in source.markers] == [m.at_ticks for m in cut.markers], (
        "cutting at a mark leaves the mark where it was"
    )

    # Two marks one frame apart still cut two frames apart, and the right-to-left order per clip is
    # what keeps the earlier coordinates valid.
    near = edit(source, [marker("e", 21, "one frame later")])
    tight = split_plan(near, ["v"])
    assert [(c["clip_id"], c["at_ticks"]) for c in tight["commands"]] == [
        ("c1", frames(21)),
        ("c1", frames(20)),
        ("c2", frames(60)),
    ], tight["commands"]
    assert tight["unused"] == [frames(40)], "an edge mark plans nothing on this track"
    sliced = edit(near, tight["commands"])
    assert sorted(
        (item.id, item.position_ticks, item.duration_ticks)
        for item in sliced.clips.values()
        if item.id.startswith("c1")
    ) == [
        ("c1", frames(0), frames(20)),
        ("c1-m0", frames(21), frames(19)),
        ("c1-m1", frames(20), frames(1)),
    ], sorted(sliced.clips)

    empty = split_plan(project())
    assert empty["commands"] == [] and empty["markers"] == 0 and empty["unused"] == []
    print("   plan: edge and outside marks are dropped, pieces tile the original span exactly")


def http_suite(folder: Path) -> None:
    token = "markertoken" + "7" * 52
    app = create_app(folder / "marker-api.sqlite3", token)
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
        caps = client.get("/v1/capabilities").json()
        assert caps["features"]["timeline_markers"] is True, caps["features"]
        assert caps["project_schema_version"] == 12, caps
        assert {"marker.set", "marker.remove"} <= set(caps["commands"]), caps["commands"]
        created = client.post(
            "/v1/projects",
            json={
                "request_id": "new",
                "name": "标记验收",
                "settings": {"width": WIDTH, "height": HEIGHT},
            },
        ).json()["project"]
        path = f"/v1/projects/{created['id']}"
        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "seed",
                "expected_revision": 0,
                "commands": [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "主画面"}},
                    {
                        "op": "asset.register",
                        "asset": {
                            "id": "a",
                            "kind": "image",
                            "label": "色块",
                            "reference": "r",
                            "duration_ticks": None,
                        },
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "one",
                            "asset_id": "a",
                            "track_id": "v",
                            "position_ticks": 0,
                            "duration_ticks": frames(60),
                        },
                    },
                    marker("a", 20, "第一拍"),
                    marker("b", 40, "第二拍"),
                ],
            },
        )
        assert seeded.status_code == 200, seeded.text
        body = seeded.json()["project"]
        assert [(m["id"], m["at_ticks"]) for m in body["markers"]] == [
            ("a", frames(20)),
            ("b", frames(40)),
        ]
        assert body["schema_version"] == 12

        scan = path + "/markers/split"
        read = client.post(scan, json={"request_id": "plan", "expected_revision": 1})
        assert read.status_code == 200, read.text
        report = read.json()
        assert report["committed"] is False and client.get(path).json()["revision"] == 1
        assert report["markers"]["splits"] == 2 and report["markers"]["clips"] == 1, report[
            "markers"
        ]

        dry = client.post(
            scan, json={"request_id": "dry", "expected_revision": 1, "apply": True, "dry_run": True}
        )
        assert dry.json()["committed"] is False and client.get(path).json()["revision"] == 1
        # dry_run returns the prospective snapshot, but nothing is saved: the stored project still
        # has the single clip.
        assert sorted(dry.json()["project"]["clips"]) == ["one", "one-m0", "one-m1"]
        assert sorted(client.get(path).json()["clips"]) == ["one"], client.get(path).json()["clips"]

        applied = client.post(
            scan, json={"request_id": "apply", "expected_revision": 1, "apply": True}
        )
        assert applied.status_code == 200, applied.text
        result = applied.json()
        assert result["committed"] is True and result["project"]["revision"] == 2
        assert sorted(result["project"]["clips"]) == ["one", "one-m0", "one-m1"]
        assert [m["id"] for m in result["project"]["markers"]] == ["a", "b"]

        # A mark that still has work to do, sent against a stale revision, is refused by the
        # optimistic lock rather than applied twice.
        third = client.post(
            path + "/edits",
            json={
                "request_id": "third",
                "expected_revision": 2,
                "commands": [marker("c", 30, "第三拍")],
            },
        )
        assert third.status_code == 200, third.text
        stale = client.post(
            scan, json={"request_id": "apply", "expected_revision": 1, "apply": True}
        )
        assert stale.status_code == 409, stale.text
        assert client.get(path).json()["revision"] == 3
        second = client.post(
            scan, json={"request_id": "cut2", "expected_revision": 3, "apply": True}
        )
        assert second.status_code == 200, second.text
        assert sorted(second.json()["project"]["clips"]) == [
            "one",
            "one-m0",
            "one-m1",
            "one-m1-m0",
        ], second.json()["project"]["clips"]
        assert second.json()["project"]["revision"] == 4
        # Every mark is now on a piece edge: an empty plan is refused instead of burning a revision.
        again = client.post(
            scan, json={"request_id": "again", "expected_revision": 4, "apply": True}
        )
        assert again.status_code == 422 and "INVALID_MARKER_SPLIT" in again.text, again.text
        assert client.get(path).json()["revision"] == 4
        ghost = client.post(
            "/v1/projects/nope/markers/split", json={"request_id": "ghost", "expected_revision": 1}
        )
        assert ghost.status_code == 404, ghost.text
        filtered = client.post(
            scan, json={"request_id": "filtered", "expected_revision": 2, "track_ids": ["w"]}
        )
        assert filtered.json()["markers"]["commands"] == [], filtered.text
    print(
        "   http: plan writes nothing, apply is one revision, a stale apply is refused,"
        " and an empty plan cannot burn a revision"
    )


def restart_suite(folder: Path) -> None:
    """Markers are durable project state: a reopen and a history restore both have to carry them."""
    path = folder / "marker-store.sqlite3"
    store = ProjectStore(path)
    created = store.create(CreateProject(request_id="new", name="restart")).project
    withmarks = store.mutate(
        created.id,
        EditBatch(
            request_id="marks",
            expected_revision=created.revision,
            commands=[
                {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "主画面"}},
                {
                    "op": "asset.register",
                    "asset": {
                        "id": "a",
                        "kind": "image",
                        "label": "a",
                        "reference": "r",
                        "duration_ticks": None,
                    },
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "one",
                        "asset_id": "a",
                        "track_id": "v",
                        "position_ticks": 0,
                        "duration_ticks": frames(60),
                    },
                },
                marker("a", 20, "keep me"),
                marker("b", 40, "me too"),
            ],
        ),
    ).project
    assert ProjectStore(path).get(created.id).markers == withmarks.markers
    assert ProjectStore(path).get(created.id).schema_version == 12

    cut = store.mutate(
        created.id,
        EditBatch(
            request_id="cut",
            expected_revision=withmarks.revision,
            commands=split_plan(withmarks)["commands"],
        ),
    ).project
    assert sorted(cut.clips) == ["one", "one-m0", "one-m1"]
    restored = store.mutate(
        created.id,
        RestoreProject(
            request_id="undo", expected_revision=cut.revision, target_revision=withmarks.revision
        ),
    ).project
    assert sorted(restored.clips) == ["one"] and [m.name for m in restored.markers] == [
        "keep me",
        "me too",
    ], restored.markers
    assert restored.revision > cut.revision, "a restore is a new revision, not a rewind"
    print("   restart: a reopen reads the same marks, and undoing the cut keeps the marks")


def main() -> None:
    reducer_suite()
    plan_suite()
    with tempfile.TemporaryDirectory(prefix="agentcut-markers-") as folder:
        root = Path(folder)
        http_suite(root)
        restart_suite(root)
    print(
        "PASS: markers are reducer-owned, tick-exact, durable across a reopen and a restore, and "
        "split into ordinary clip.split commands"
    )


if __name__ == "__main__":
    main()
