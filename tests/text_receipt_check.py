"""Replay actual v1.5/v1.7 canonical text payload shapes without rewriting history."""

import hashlib
import json
import tempfile
from pathlib import Path

from agentcut.contracts import TIMEBASE, CreateProject, EditBatch, EditorError
from agentcut.projects import ProjectStore


def digest(payload):
    return hashlib.sha256(
        json.dumps(["edit", payload], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def main():
    with tempfile.TemporaryDirectory(prefix="agentcut-text-receipts-") as folder:
        store = ProjectStore(Path(folder) / "test.sqlite3")
        p = store.create(CreateProject(request_id="new", name="text")).project
        p = store.mutate(
            p.id,
            EditBatch.model_validate(
                {
                    "request_id": "seed",
                    "expected_revision": 0,
                    "commands": [
                        {"op": "track.add", "track": {"id": "v", "name": "v", "kind": "video"}},
                        {
                            "op": "asset.register",
                            "asset": {
                                "id": "text",
                                "kind": "text",
                                "label": "text",
                                "reference": "generated:text",
                            },
                        },
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "c",
                                "asset_id": "text",
                                "track_id": "v",
                                "position_ticks": 0,
                                "duration_ticks": TIMEBASE,
                                "text": {"body": "seed"},
                            },
                        },
                    ],
                }
            ),
        ).project
        for version in ("1.5", "1.7"):
            text = {"body": "legacy", "font_size": 0.06, "color": "#FFFFFF"}
            if version == "1.7":
                text.update(align="center", box=False)
            payload = {
                "request_id": "text-" + version.replace(".", ""),
                "expected_revision": p.revision,
                "commands": [{"op": "clip.text", "clip_id": "c", "text": text}],
            }
            request = EditBatch.model_validate(payload)
            result = store.mutate(p.id, request)
            # Seed the old release's receipt hash in this disposable fixture only.
            with store.connection(write=True) as db:
                db.execute(
                    "UPDATE receipts SET fingerprint=? WHERE scope=? AND request_id=?",
                    (digest(payload), p.id, request.request_id),
                )
            assert store.mutate(p.id, request).replayed
            changed = json.loads(json.dumps(payload))
            changed["commands"][0]["text"]["body"] = "different"
            try:
                store.mutate(p.id, EditBatch.model_validate(changed))
                raise AssertionError("different text must still conflict")
            except EditorError as error:
                assert error.code == "IDEMPOTENCY_CONFLICT"
            p = result.project
        # Add/insert/overwrite and bulk paste carry nested TextStyle too.
        for op in ("clip.add", "clip.insert", "clip.overwrite", "clips.add"):
            clip = p.clips["c"].model_dump()
            command = {"op": op, "clips": [clip]} if op == "clips.add" else {"op": op, "clip": clip}
            if op == "clip.insert":
                command["ripple_track_ids"] = None
            legacy = {"request_id": "shape", "expected_revision": 0, "commands": [command]}
            for field in (
                "group_id",
                "link_id",
                "link_source_offset_ticks",
                "embedded_audio",
                "mask",
                "speed_curve",
            ):
                clip.pop(field)
            clip["color"].pop("grade", None)
            # A v1.5-era nested style carried only these three keys; anything the model has grown
            # since must be stripped here as well, or this fixture is a 1.5 payload in name only.
            for name in [key for key in clip["text"] if key not in ("body", "font_size", "color")]:
                clip["text"].pop(name)
            if op != "clips.add":
                clip.pop("transition_in")
            if op == "clip.add":
                for field in (
                    "speed_percent",
                    "effects",
                    "color",
                    "keyframes",
                    "animation_offset_ticks",
                ):
                    clip.pop(field)
            request = EditBatch.model_validate(legacy)
            assert ProjectStore._fingerprint("edit", request) == digest(legacy), op
    print("PASS: v1.5/v1.7 text receipt replay, nested text defaults and real payload conflicts")


if __name__ == "__main__":
    main()
