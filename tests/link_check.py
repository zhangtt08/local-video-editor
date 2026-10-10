"""Saved associations, paired cuts/trims, independent drift and legacy receipts."""

import hashlib
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import (
    SCHEMA_VERSION,
    TIMEBASE,
    CreateProject,
    EditBatch,
    EditorError,
    RestoreProject,
)
from agentcut.http_api import create_app
from agentcut.projects import ProjectStore
from agentcut.timeline import apply_commands, link_status

T = TIMEBASE


def batch(commands, revision=0, request="check", dry=False):
    return EditBatch.model_validate(
        {"request_id": request, "expected_revision": revision, "commands": commands, "dry_run": dry}
    )


def main():
    with tempfile.TemporaryDirectory(prefix="agentcut-links-") as folder:
        path = Path(folder) / "links.sqlite3"
        store = ProjectStore(path)
        p = store.create(CreateProject(request_id="new", name="links")).project
        setup = [
            {"op": "track.add", "track": {"id": k, "kind": kind, "name": k}}
            for k, kind in (("v", "video"), ("a", "audio"))
        ]
        setup += [
            {
                "op": "asset.register",
                "asset": {
                    "id": k,
                    "kind": kind,
                    "label": k,
                    "reference": "metadata",
                    "duration_ticks": 10 * T,
                },
            }
            for k, kind in (("video", "video"), ("sound", "audio"))
        ]
        setup += [
            {
                "op": "clips.add",
                "clips": [
                    {
                        "id": k,
                        "asset_id": asset,
                        "track_id": track,
                        "position_ticks": T,
                        "source_in_ticks": source * T,
                        "duration_ticks": 4 * T,
                        "keyframes": [{"property": "gain", "at_ticks": 2 * T, "value": 0.5}],
                    }
                    for k, asset, track, source in (
                        ("picture", "video", "v", 1),
                        ("voice", "sound", "a", 2),
                    )
                ],
            }
        ]
        p = store.mutate(p.id, batch(setup, request="setup")).project
        associations = [
            {"op": "clips.group", "clip_ids": ["picture", "voice"], "group_id": "group"},
            {"op": "clips.link", "clip_ids": ["picture", "voice"], "link_id": "pair"},
        ]
        dry = store.mutate(p.id, batch(associations, p.revision, "associate", True))
        assert not dry.committed and dry.project.clips["picture"].group_id == "group"
        assert store.get(p.id).clips["picture"].group_id is None
        p = store.mutate(p.id, batch(associations, p.revision, "associate")).project
        assert ProjectStore(path).get(p.id).clips["voice"].link_source_offset_ticks == T
        assert link_status(p)["pair"]["synchronized"]
        assert store.mutate(p.id, batch(associations, 1, "associate")).replayed
        trim = {
            "op": "clip.trim_linked",
            "clip_id": "picture",
            "position_ticks": 2 * T,
            "source_in_ticks": 2 * T,
            "duration_ticks": 3 * T,
        }
        shortened = apply_commands(p, batch([trim]).commands)
        assert shortened.clips["voice"].source_in_ticks == 3 * T
        assert shortened.clips["voice"].animation_offset_ticks == T
        assert (
            shortened.clips["picture"].duration_ticks
            == shortened.clips["voice"].duration_ticks
            == 3 * T
        )
        assert link_status(shortened)["pair"]["synchronized"]
        locked = apply_commands(
            p, batch([{"op": "track.update", "track_id": "a", "locked": True}]).commands
        )
        try:
            apply_commands(locked, batch([trim]).commands)
        except EditorError as error:
            assert error.code == "TRACK_LOCKED"
        else:
            raise AssertionError("linked trim changed locked audio")
        assert locked.clips["picture"].source_in_ticks == T
        cut = {
            "op": "clips.split",
            "clip_ids": ["picture", "voice"],
            "at_ticks": 3 * T,
            "right_clip_ids": {"picture": "picture-r", "voice": "voice-r"},
        }
        divided = apply_commands(p, batch([cut]).commands)
        right_link = divided.clips["picture-r"].link_id
        assert (
            right_link and right_link != "pair" and divided.clips["voice-r"].link_id == right_link
        )
        assert all(s["synchronized"] for s in link_status(divided).values())
        assert all(c.group_id == "group" for c in divided.clips.values())
        moved = apply_commands(
            divided,
            batch(
                [{"op": "clips.move", "clip_ids": ["picture-r", "voice-r"], "delta_ticks": T}]
            ).commands,
        )
        assert all(s["synchronized"] for s in link_status(moved).values())
        single = apply_commands(
            p,
            batch(
                [
                    {
                        "op": "clip.split",
                        "clip_id": "picture",
                        "at_ticks": 3 * T,
                        "right_clip_id": "single-r",
                    }
                ]
            ).commands,
        )
        assert (
            single.clips["single-r"].link_id is None
            and not link_status(single)["pair"]["synchronized"]
        )
        drifted = apply_commands(
            p,
            batch(
                [{"op": "clip.move", "clip_id": "voice", "track_id": "a", "position_ticks": 2 * T}]
            ).commands,
        )
        assert link_status(drifted)["pair"]["differences"]["voice"]["position_ticks"] == T
        try:
            apply_commands(drifted, batch([trim]).commands)
        except EditorError as error:
            assert error.code == "LINK_OUT_OF_SYNC"
        else:
            raise AssertionError("drift was silently reset")
        unlinked = apply_commands(
            p, batch([{"op": "clips.link", "clip_ids": ["picture"], "link_id": None}]).commands
        )
        assert all(
            c.link_id is None and c.link_source_offset_ticks == 0 for c in unlinked.clips.values()
        )
        removed = apply_commands(p, batch([{"op": "clip.remove", "clip_id": "voice"}]).commands)
        assert (
            removed.clips["picture"].group_id is None and removed.clips["picture"].link_id is None
        )
        # Same linked cut produced by insertion across both tracks retains two separate pairs.
        inserted = apply_commands(
            p,
            batch(
                [
                    {
                        "op": "clip.insert",
                        "clip": {
                            "id": "insert",
                            "asset_id": "video",
                            "track_id": "v",
                            "position_ticks": 3 * T,
                            "duration_ticks": T,
                        },
                        "ripple_track_ids": ["v", "a"],
                    }
                ]
            ).commands,
        )
        assert len(link_status(inserted)) == 2 and all(
            s["synchronized"] for s in link_status(inserted).values()
        )
        # Expanded v4 clips.add and v3 insertion defaults retain byte-identical canonical hashes.
        for op in ("clips.add", "clip.insert", "clip.overwrite"):
            clip = store.get(p.id, 1).clips["picture"].model_dump()
            command = {"op": op, "clips": [clip]} if op == "clips.add" else {"op": op, "clip": clip}
            request = batch([command])
            legacy = request.model_dump(exclude={"dry_run", "sequence_id"})
            old_clip = legacy["commands"][0].get(
                "clip", legacy["commands"][0].get("clips", [None])[0]
            )
            for field in (
                "group_id",
                "link_id",
                "link_source_offset_ticks",
                "embedded_audio",
                "mask",
                "speed_curve",
                "stabilization",  # 1.69: a clip that never mentions one is older
                "fade",  # 1.90: a clip that never mentions a fade window is older
                "mask_shape_keys",  # 1.118: 没提过轮廓帧的载荷就是 1.118 之前写的
            ):
                old_clip.pop(field)
            old_clip["color"].pop("grade", None)
            for keyframe in old_clip.get("keyframes", []):
                keyframe.pop("bezier", None)
            if op != "clips.add":
                old_clip.pop("transition_in")
            digest = hashlib.sha256(
                json.dumps(["edit", legacy], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            assert ProjectStore._fingerprint("edit", request) == digest
        restored = store.mutate(
            p.id, RestoreProject(request_id="undo", expected_revision=p.revision, target_revision=1)
        ).project
        assert restored.schema_version == SCHEMA_VERSION
        assert restored.revision == p.revision + 1
        assert restored.clips["picture"].group_id is None
        with TestClient(
            create_app(db_path=path, token="x" * 32), base_url="http://127.0.0.1"
        ) as client:
            headers = {"Authorization": "Bearer " + "x" * 32}
            response = client.post(
                f"/v1/projects/{p.id}/edits",
                headers=headers,
                json=batch(associations, restored.revision, "http").model_dump(),
            )
            assert response.status_code == 200, response.text
            plan = client.get(f"/v1/projects/{p.id}/preview-manifest", headers=headers).json()
            assert plan["links"]["pair"]["synchronized"]
            retry = client.post(
                f"/v1/projects/{p.id}/edits",
                headers=headers,
                json=batch(associations, restored.revision, "http").model_dump(),
            )
            assert retry.json()["replayed"]
    print(
        "PASS: saved groups/links, paired edits, locks, drift, cleanup, "
        "undo, v3/v4 receipts and HTTP"
    )


if __name__ == "__main__":
    main()
