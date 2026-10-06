"""Rolling trim shared-seam edits and ripple-trim tail shifting."""

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE, CreateProject, EditBatch, EditorError
from agentcut.http_api import create_app
from agentcut.projects import ProjectStore
from agentcut.timeline import apply_commands

T = TIMEBASE


def batch(commands, revision=0, request="check", dry=False):
    return EditBatch.model_validate(
        {"request_id": request, "expected_revision": revision, "commands": commands, "dry_run": dry}
    )


def seed(store):
    p = store.create(CreateProject(request_id="new", name="roll")).project
    commands = [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
        {
            "op": "asset.register",
            "asset": {
                "id": "m1",
                "kind": "video",
                "label": "m1",
                "reference": "metadata",
                "duration_ticks": 30 * T,
            },
        },
        {
            "op": "asset.register",
            "asset": {
                "id": "m2",
                "kind": "video",
                "label": "m2",
                "reference": "metadata",
                "duration_ticks": 30 * T,
            },
        },
    ]
    store.mutate(p.id, batch(commands))
    p = store.get(p.id)
    clips = [
        {
            "op": "clip.add",
            "clip": {
                "id": i,
                "asset_id": a,
                "track_id": "v",
                "position_ticks": pos * T,
                "duration_ticks": d * T,
            },
        }
        for i, a, pos, d in (("c1", "m1", 0, 5), ("c2", "m2", 5, 5), ("c3", "m2", 10, 5))
    ]
    return store.mutate(p.id, batch(clips, revision=p.revision, request="seed")).project


def main():
    with tempfile.TemporaryDirectory(prefix="agentcut-roll-") as folder:
        store = ProjectStore(Path(folder) / "roll.sqlite3")
        project = seed(store)

        rolled = apply_commands(
            project,
            batch(
                [{"op": "clip.roll", "clip_id": "c1", "other_clip_id": "c2", "delta_ticks": 2 * T}]
            ).commands,
        )
        assert rolled.clips["c1"].duration_ticks == 7 * T
        assert rolled.clips["c2"].position_ticks == 7 * T
        assert rolled.clips["c2"].duration_ticks == 3 * T
        assert rolled.clips["c2"].source_in_ticks == 2 * T
        assert rolled.clips["c3"].position_ticks == 10 * T

        # rolling the seam back past the source head of the right clip fails as one batch
        try:
            apply_commands(
                project,
                batch(
                    [
                        {
                            "op": "clip.roll",
                            "clip_id": "c1",
                            "other_clip_id": "c2",
                            "delta_ticks": -5 * T,
                        }
                    ]
                ).commands,
            )
            raise AssertionError("expected SOURCE_OUT_OF_BOUNDS / INVALID_ROLL")
        except EditorError:
            pass

        # non-adjacent clips cannot roll
        try:
            apply_commands(
                project,
                batch(
                    [{"op": "clip.roll", "clip_id": "c1", "other_clip_id": "c3", "delta_ticks": T}]
                ).commands,
            )
            raise AssertionError("expected NOT_ADJACENT")
        except EditorError:
            pass

        rippled = apply_commands(
            project,
            batch(
                [
                    {
                        "op": "clip.trim",
                        "clip_id": "c2",
                        "source_in_ticks": 0,
                        "duration_ticks": 3 * T,
                        "ripple": True,
                    }
                ]
            ).commands,
        )
        assert rippled.clips["c3"].position_ticks == 8 * T
        assert project.clips["c3"].position_ticks == 10 * T  # original untouched

        fast = project.model_copy(deep=True)
        fast.clips["c1"].speed_percent = fast.clips["c2"].speed_percent = 200
        fast.clips["c2"].source_in_ticks = 4 * T
        roll = batch(
            [{"op": "clip.roll", "clip_id": "c1", "other_clip_id": "c2", "delta_ticks": T}]
        )
        assert apply_commands(fast, roll.commands).clips["c2"].source_in_ticks == 6 * T
        static = project.model_copy(deep=True)
        for asset in static.assets.values():
            asset.kind = "image"
            asset.duration_ticks = None
        assert apply_commands(static, roll.commands).clips["c2"].source_in_ticks == 0

        linked = apply_commands(
            project,
            batch(
                [
                    {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "sound"}},
                    {
                        "op": "asset.register",
                        "asset": {
                            "id": "sound",
                            "kind": "audio",
                            "label": "sound",
                            "reference": "metadata",
                            "duration_ticks": 30 * T,
                        },
                    },
                    {
                        "op": "clips.add",
                        "clips": [
                            {
                                "id": "a1",
                                "asset_id": "sound",
                                "track_id": "a",
                                "position_ticks": 0,
                                "duration_ticks": 5 * T,
                            },
                            {
                                "id": "a2",
                                "asset_id": "sound",
                                "track_id": "a",
                                "position_ticks": 5 * T,
                                "duration_ticks": 5 * T,
                            },
                        ],
                    },
                    {"op": "clips.link", "clip_ids": ["c1", "a1"], "link_id": "left"},
                    {"op": "clips.link", "clip_ids": ["c2", "a2"], "link_id": "right"},
                ]
            ).commands,
        )
        moved = apply_commands(linked, roll.commands)
        assert moved.clips["a1"].duration_ticks == 6 * T
        assert moved.clips["a2"].position_ticks == 6 * T
        locked = apply_commands(
            linked, batch([{"op": "track.update", "track_id": "a", "locked": True}]).commands
        )
        try:
            apply_commands(locked, roll.commands)
            raise AssertionError("locked linked track must reject roll")
        except EditorError as error:
            assert error.code == "TRACK_LOCKED"
        assert locked.clips["a1"].duration_ticks == 5 * T
        drift = apply_commands(
            linked,
            batch(
                [
                    {
                        "op": "clip.trim",
                        "clip_id": "a2",
                        "source_in_ticks": T,
                        "duration_ticks": 5 * T,
                    }
                ]
            ).commands,
        )
        try:
            apply_commands(drift, roll.commands)
            raise AssertionError("out-of-sync link must reject roll")
        except EditorError as error:
            assert error.code == "LINK_OUT_OF_SYNC"

        # HTTP dry-run does not write; commit shifts the same; replay returns the same version
        token = "roll-test-token-" + "x" * 32
        with TestClient(
            create_app(Path(folder) / "roll.sqlite3", token),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            url = f"/v1/projects/{project.id}/edits"
            request = batch(
                [{"op": "clip.roll", "clip_id": "c1", "other_clip_id": "c2", "delta_ticks": 2 * T}],
                project.revision,
                "roll-http",
                True,
            )
            response = client.post(url, json=request.model_dump())
            assert response.status_code == 200, response.text
            assert (
                not response.json()["committed"]
                and store.get(project.id).revision == project.revision
            )
            request.dry_run = False
            response = client.post(url, json=request.model_dump())
            assert response.status_code == 200, response.text
            assert response.json()["project"]["clips"]["c1"]["duration_ticks"] == 7 * T
            assert client.post(url, json=request.model_dump()).json()["replayed"]

    print("PASS: roll trim, roll bounds/adjacency, ripple trim tail")


if __name__ == "__main__":
    main()
