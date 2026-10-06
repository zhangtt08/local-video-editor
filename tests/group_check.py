"""Atomic group edits, transition ownership, disjoint ripple ranges and shared HTTP."""

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE, CreateProject, EditBatch, EditorError, RestoreProject
from agentcut.http_api import create_app
from agentcut.projects import ProjectStore
from agentcut.timeline import apply_commands

T = TIMEBASE


def batch(commands, revision=0, request="check", dry=False):
    return EditBatch.model_validate(
        {"request_id": request, "expected_revision": revision, "commands": commands, "dry_run": dry}
    )


def main():
    with tempfile.TemporaryDirectory(prefix="agentcut-group-") as folder:
        store = ProjectStore(Path(folder) / "group.sqlite3")
        p = store.create(CreateProject(request_id="new", name="group")).project
        commands = [
            {"op": "track.add", "track": {"id": i, "kind": k, "name": i}}
            for i, k in (("v", "video"), ("target", "video"), ("a", "audio"))
        ]
        commands += [
            {
                "op": "asset.register",
                "asset": {
                    "id": "image",
                    "kind": "image",
                    "label": "image",
                    "reference": "metadata",
                },
            },
            {
                "op": "asset.register",
                "asset": {
                    "id": "sound",
                    "kind": "audio",
                    "label": "sound",
                    "reference": "metadata",
                    "duration_ticks": 10 * T,
                },
            },
        ]
        clips = [
            {
                "id": i,
                "asset_id": "sound" if track == "a" else "image",
                "track_id": track,
                "position_ticks": pos * T,
                "duration_ticks": duration * T,
            }
            for i, track, pos, duration in (
                ("left", "v", 0, 2),
                ("right", "v", 2, 2),
                ("tail", "v", 5, 2),
                ("music", "a", 0, 8),
            )
        ]
        commands += [
            {"op": "clips.add", "clips": clips},
            {
                "op": "transition.set",
                "clip_id": "right",
                "from_clip_id": "left",
                "duration_ticks": T,
            },
        ]
        p = store.mutate(p.id, batch(commands)).project
        assert p.clips["tail"].position_ticks == 4 * T
        original = p.model_dump()
        move = {
            "op": "clips.move",
            "clip_ids": ["left", "right", "music"],
            "delta_ticks": T,
            "track_map": {"v": "target"},
        }
        moved = apply_commands(p, batch([move]).commands)
        assert (
            moved.clips["left"].position_ticks == T and moved.clips["right"].position_ticks == 2 * T
        )
        assert moved.clips["right"].transition_in.from_clip_id == "left"
        assert (
            moved.clips["music"].position_ticks == T and moved.clips["music"].source_in_ticks == 0
        )
        assert moved.clips["tail"].position_ticks == 4 * T
        for selected, expected in (
            (["right"], 3 * T),
            (["left", "right"], T),
            (["left", "tail"], 0),
        ):
            removed = apply_commands(
                p, batch([{"op": "clips.remove", "clip_ids": selected, "ripple": True}]).commands
            )
            assert (
                removed.clips["right" if "right" not in selected else "tail"].position_ticks
                == expected
            )
            assert removed.clips["music"].position_ticks == 0
        divided = apply_commands(
            p,
            batch(
                [
                    {
                        "op": "clips.split",
                        "clip_ids": ["left", "music"],
                        "at_ticks": T // 2,
                        "right_clip_ids": {"left": "left-half", "music": "music-half"},
                    }
                ]
            ).commands,
        )
        assert divided.clips["right"].transition_in.from_clip_id == "left-half"
        assert divided.clips["music-half"].source_in_ticks == T // 2
        locked = p.model_copy(deep=True)
        locked.tracks[1].locked = True
        invalid = [
            (p, {**move, "clip_ids": ["left", "left"]}, "INVALID_SELECTION"),
            (p, {**move, "clip_ids": ["left", "missing"]}, "NOT_FOUND"),
            (locked, move, "TRACK_LOCKED"),
            (p, {**move, "delta_ticks": -T}, "TIME_OVERFLOW"),
            (p, {**move, "delta_ticks": 1}, "TIME_NOT_ALIGNED"),
            (p, {**move, "track_map": {"v": "a"}}, "TRACK_KIND_MISMATCH"),
            (
                p,
                {
                    "op": "clips.split",
                    "clip_ids": ["left", "music"],
                    "at_ticks": 3 * T // 2,
                    "right_clip_ids": {"left": "x", "music": "y"},
                },
                "TRANSITION_EDIT_CONFLICT",
            ),
            (
                p,
                {
                    "op": "clips.split",
                    "clip_ids": ["left", "music"],
                    "at_ticks": T // 2,
                    "right_clip_ids": {"left": "x", "music": "x"},
                },
                "DUPLICATE_ID",
            ),
        ]
        for state, command, code in invalid:
            snapshot = state.model_dump()
            try:
                apply_commands(state, batch([command]).commands)
            except EditorError as error:
                assert error.code == code, (code, error)
            else:
                raise AssertionError(code)
            assert state.model_dump() == snapshot
        assert p.model_dump() == original
        many = [
            {
                "id": f"many-{i}",
                "asset_id": "image",
                "track_id": "target",
                "position_ticks": i * T,
                "duration_ticks": T,
            }
            for i in range(300)
        ]
        accepted = apply_commands(p, batch([{"op": "clips.add", "clips": many}]).commands)
        assert len(accepted.clips) == 304
        with TestClient(
            create_app(Path(folder) / "group.sqlite3", "group-test-token-" + "x" * 32),
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer group-test-token-" + "x" * 32},
        ) as client:
            url = f"/v1/projects/{p.id}/edits"
            request = batch([move], 1, "group-http", True)
            response = client.post(url, json=request.model_dump())
            assert response.status_code == 200, response.text
            assert not response.json()["committed"] and store.get(p.id).revision == 1
            request.dry_run = False
            response = client.post(url, json=request.model_dump())
            assert response.status_code == 200, response.text
            assert response.json()["project"]["revision"] == 2
            assert client.post(url, json=request.model_dump()).json()["replayed"]
            bad = client.post(
                url,
                json=batch(
                    [{**move, "clip_ids": ["left", "missing"]}], 2, "group-rollback"
                ).model_dump(),
            )
            assert bad.status_code == 404 and store.get(p.id).revision == 2
        restored = store.mutate(
            p.id, RestoreProject(request_id="restore-group", expected_revision=2, target_revision=1)
        ).project
        assert restored.revision == 3 and restored.clips["left"].position_ticks == 0
    print(
        "PASS: groups, delta, transitions, ripple union, locks, split/add, "
        "HTTP rollback/replay/restore"
    )


if __name__ == "__main__":
    main()
