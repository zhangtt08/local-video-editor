"""Sparse edits compose, can be removed independently, and keep old replacement semantics."""

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app


def main():
    with tempfile.TemporaryDirectory() as scratch:
        with TestClient(
            create_app(Path(scratch) / "db.sqlite3", "patch-" + "a" * 48),
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer patch-" + "a" * 48},
        ) as client:
            p = client.post("/v1/projects", json={"request_id": "new", "name": "patch"}).json()[
                "project"
            ]
            path = f"/v1/projects/{p['id']}"

            def edit(request_id, revision, commands, dry=False):
                return client.post(
                    path + "/edits",
                    json={
                        "request_id": request_id,
                        "expected_revision": revision,
                        "commands": commands,
                        "dry_run": dry,
                    },
                )

            seed = [
                {"op": "track.add", "track": {"id": "v", "name": "picture", "kind": "video"}},
                {"op": "track.add", "track": {"id": "a", "name": "sound", "kind": "audio"}},
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
                    "op": "asset.register",
                    "asset": {
                        "id": "sound",
                        "kind": "audio",
                        "label": "sound",
                        "reference": "metadata",
                        "duration_ticks": T,
                    },
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "c",
                        "asset_id": "text",
                        "track_id": "v",
                        "position_ticks": 0,
                        "duration_ticks": T,
                        "text": {"body": "before"},
                        "effects": {"rotation": 30},
                        "color": {"contrast": 1.25},
                        "keyframes": [{"property": "gain", "at_ticks": 0, "value": 0.5}],
                    },
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "s",
                        "asset_id": "sound",
                        "track_id": "a",
                        "position_ticks": 0,
                        "duration_ticks": T,
                    },
                },
            ]
            response = edit("seed", 0, seed)
            assert response.status_code == 200, response.text
            before = response.json()["project"]

            def patch(**fields):
                return {"op": "clip.patch", "clip_id": "c", **fields}

            commands = [
                patch(effects={"x": 0.2}),
                patch(effects={"y": 0.3}),
                patch(color={"exposure": 0.4}),
                patch(color={"saturation": 0.5}),
                patch(text={"body": "中文 after"}),
                patch(text={"font_size": 0.08}),
                patch(text={"box": True, "align": "bottom"}),
            ]
            dry = edit("dry", 1, commands, True)
            assert dry.status_code == 200, dry.text
            candidate = dry.json()["project"]
            c = candidate["clips"]["c"]
            assert (c["effects"]["x"], c["effects"]["y"], c["effects"]["rotation"]) == (
                0.2,
                0.3,
                30,
            )
            assert c["color"] == {"exposure": 0.4, "contrast": 1.25, "saturation": 0.5, "grade": []}
            assert c["text"] == {
                "body": "中文 after",
                "font_size": 0.08,
                "color": "#FFFFFF",
                "align": "bottom",
                "box": True,
                # 1.63's knobs were not part of this patch, so they stay at the defaults that
                # reproduce the pre-1.63 rendering rather than going missing from the record.
                "font": "yahei",
                "text_align": "center",
                "outline_width": 0.04,
                "outline_color": "#000000",
                "shadow_x": 0.0,
                "shadow_y": 0.0,
                "shadow_color": "#000000",
                "box_color": "#000000",
                "box_opacity": 0.45,
                "line_spacing": 0.2,
            }
            assert c["keyframes"] == before["clips"]["c"]["keyframes"]
            assert client.get(path).json() == before
            removed = edit("removed", 1, commands[1:], True).json()["project"]
            assert removed["clips"]["c"]["effects"]["x"] == 0
            assert removed["clips"]["c"]["effects"]["y"] == 0.3
            committed = edit("dry", 1, commands)
            assert committed.json()["project"] == candidate
            assert edit("dry", 1, commands).json()["replayed"]
            assert edit("dry", 1, commands[:-1]).status_code == 409
            # Strict boundary validation; one bad patch rejects the entire transaction.
            for bad in [
                patch(effects={"opacity": 2}),
                patch(color={"bad": 1}),
                patch(text={"font_size": 0}),
                patch(text={"box": "true"}),
                patch(text={"body": "\x00"}),
                patch(effects={"x": None}),
                patch(),
                patch(text={"extra": True}),
            ]:
                rejected = edit("bad", 2, [patch(effects={"x": 0.7}), bad])
                assert rejected.status_code == 422, rejected.text
                assert client.get(path).json() == candidate
            for fields in [{"color": {"exposure": 1}}, {"text": {"body": "invalid"}}]:
                rejected = edit("audio", 2, [{"op": "clip.patch", "clip_id": "s", **fields}])
                assert rejected.status_code == 422
                assert client.get(path).json() == candidate
            locked = edit(
                "lock", 2, [{"op": "track.update", "track_id": "v", "locked": True}]
            ).json()["project"]
            rejected = edit("locked", 3, [patch(text={"body": "locked"})])
            assert (
                rejected.status_code == 422 and rejected.json()["error"]["code"] == "TRACK_LOCKED"
            )
            assert client.get(path).json() == locked
            # Legacy clip.effects/color/text are still full replacements with defaults.
            old = edit(
                "old",
                3,
                [
                    {"op": "track.update", "track_id": "v", "locked": False},
                    {"op": "clip.effects", "clip_id": "c", "effects": {"gain": 0.25}},
                    {"op": "clip.color", "clip_id": "c", "color": {"exposure": 0.2}},
                    {"op": "clip.text", "clip_id": "c", "text": {"body": "old"}},
                ],
            ).json()["project"]["clips"]["c"]
            assert (
                old["effects"]["x"] == 0
                and old["effects"]["rotation"] == 0
                and old["effects"]["gain"] == 0.25
            )
            assert (
                old["color"]["contrast"] == 1
                and old["text"]["font_size"] == 0.06
                and not old["text"]["box"]
            )
            assert client.get("/v1/capabilities").json()["features"]["clip_property_patches"]
            assert "ClipPatch" in client.get("/v1/contracts").json()["EditBatch"]["$defs"]
    print("PASS: sparse edits, removal, rollback, locks, replay, strict types, old replacements")


if __name__ == "__main__":
    main()
