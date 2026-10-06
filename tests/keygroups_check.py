"""Atomic keyframe selection edits: occupied selected targets, clocks and rollback."""

import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app

TOKEN = "keygroups-test-" + "k" * 40


def main():
    with tempfile.TemporaryDirectory(prefix="agentcut-keygroups-") as scratch:
        with TestClient(
            create_app(Path(scratch) / "db.sqlite3", TOKEN),
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client:

            def post(path, body):
                r = client.post(path, json=body)
                assert r.status_code == 200, r.text
                return r.json()

            p = post("/v1/projects", {"request_id": "new", "name": "selection"})["project"]
            url = f"/v1/projects/{p['id']}"
            points = [
                {
                    "property": "opacity",
                    "at_ticks": T,
                    "value": 0.2,
                    "interpolation": "bezier",
                    "bezier": {"x1": 0.12, "y1": 0.8, "x2": 0.8, "y2": 0.1},
                },
                {"property": "opacity", "at_ticks": 3 * T, "value": 0.5, "interpolation": "ease"},
                {"property": "opacity", "at_ticks": 5 * T, "value": 0.8},
                {"property": "x", "at_ticks": 7 * T, "value": 0.1},
                {"property": "opacity", "at_ticks": 0, "value": 0.1},
            ]
            p = post(
                url + "/edits",
                {
                    "request_id": "seed",
                    "expected_revision": 0,
                    "commands": [
                        {
                            "op": "track.add",
                            "track": {"id": "v", "kind": "video", "name": "picture"},
                        },
                        {
                            "op": "asset.register",
                            "asset": {
                                "id": "a",
                                "kind": "image",
                                "label": "still",
                                "reference": "meta:still",
                            },
                        },
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "c",
                                "asset_id": "a",
                                "track_id": "v",
                                "position_ticks": 0,
                                "duration_ticks": 6 * T,
                                "animation_offset_ticks": T,
                                "keyframes": points,
                            },
                        },
                    ],
                },
            )["project"]
            original = p["clips"]["c"]["keyframes"]
            keys = [k for k in original if k["property"] == "opacity" and k["at_ticks"] >= T]
            # A forward group shift occupies a selected point's old time; a sequence of
            # single-point commands would reject it, so the final set is authoritative.
            move = {
                "op": "keyframes.move",
                "clip_id": "c",
                "moves": [
                    {
                        "from_ticks": k["at_ticks"] - T,
                        "keyframe": {**k, "at_ticks": k["at_ticks"] + T},
                    }
                    for k in keys
                ],
            }
            request = {
                "request_id": "move",
                "expected_revision": 1,
                "commands": [move],
                "dry_run": True,
            }
            history = client.get(url + "/history").json()
            dry = post(url + "/edits", request)["project"]
            assert client.get(url).json() == p and client.get(url + "/history").json() == history
            request["dry_run"] = False
            p = post(url + "/edits", request)["project"]
            assert p == dry and post(url + "/edits", request)["replayed"]
            after = p["clips"]["c"]["keyframes"]
            assert [k["at_ticks"] for k in after if k["property"] == "opacity"] == [
                0,
                3 * T,
                5 * T,
                7 * T,
            ]
            assert next(k for k in after if k["at_ticks"] == 3 * T)["bezier"] == keys[0]["bezier"]
            assert next(k for k in after if k["property"] == "x") == next(
                k for k in original if k["property"] == "x"
            )

            def rejected(commands, code, status=422):
                before = client.get(url).json()
                history_before = client.get(url + "/history").json()
                response = client.post(
                    url + "/edits",
                    json={
                        "request_id": "bad-" + code,
                        "expected_revision": p["revision"],
                        "commands": commands,
                    },
                )
                assert (
                    response.status_code == status and response.json()["error"]["code"] == code
                ), response.text
                assert (
                    client.get(url).json() == before
                    and client.get(url + "/history").json() == history_before
                )

            first = next(k for k in after if k["property"] == "opacity" and k["at_ticks"] == 3 * T)
            item = {"from_ticks": 2 * T, "keyframe": {**first, "at_ticks": 4 * T}}
            rejected([{**move, "moves": [item]}], "KEYFRAME_COLLISION")
            rejected([{**move, "moves": [item, item]}], "INVALID_SELECTION")
            rejected([{**move, "moves": [{**item, "from_ticks": T}]}], "KEYFRAME_NOT_FOUND", 404)
            rejected(
                [
                    {
                        **move,
                        "moves": [{**item, "keyframe": {**item["keyframe"], "at_ticks": 7 * T}}],
                    }
                ],
                "INVALID_KEYFRAME",
            )
            rejected(
                [
                    {"op": "clip.patch", "clip_id": "c", "effects": {"x": 0.2}},
                    {**move, "moves": [item]},
                ],
                "KEYFRAME_COLLISION",
            )
            request = {
                "request_id": "locked",
                "expected_revision": 2,
                "commands": [{"op": "track.update", "track_id": "v", "locked": True}],
            }
            p = post(url + "/edits", request)["project"]
            rejected([move], "TRACK_LOCKED")
            p = post(
                url + "/edits",
                {
                    "request_id": "unlock",
                    "expected_revision": 3,
                    "commands": [{"op": "track.update", "track_id": "v", "locked": False}],
                },
            )["project"]
            removal = {
                "op": "keyframes.remove",
                "clip_id": "c",
                "keyframes": [
                    {"property": "opacity", "at_ticks": k["at_ticks"] - T}
                    for k in after
                    if k["property"] == "opacity" and k["at_ticks"] >= T
                ],
            }
            p = post(
                url + "/edits",
                {"request_id": "remove", "expected_revision": 4, "commands": [removal]},
            )["project"]
            assert p["clips"]["c"]["keyframes"] == [
                k for k in after if k["property"] == "x" or k["at_ticks"] == 0
            ]
            p = post(
                url + "/restore",
                {"request_id": "restore", "expected_revision": 5, "target_revision": 1},
            )["project"]
            assert p["revision"] == 6 and p["clips"]["c"]["keyframes"] == original
            # 2000 points still fit one command, beyond the 100-command batch limit.
            dense = [
                {"property": "x", "at_ticks": i * T // 1000, "value": 0.1} for i in range(2000)
            ]
            p = post(
                url + "/edits",
                {
                    "request_id": "dense",
                    "expected_revision": 6,
                    "commands": [
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "dense",
                                "asset_id": "a",
                                "track_id": "v",
                                "position_ticks": 6 * T,
                                "duration_ticks": 4 * T,
                                "keyframes": dense,
                            },
                        }
                    ],
                },
            )["project"]
            dense_move = {
                "op": "keyframes.move",
                "clip_id": "dense",
                "moves": [
                    {"from_ticks": k["at_ticks"], "keyframe": {**k, "at_ticks": k["at_ticks"] + T}}
                    for k in dense
                ],
            }
            p = post(
                url + "/edits",
                {"request_id": "dense-move", "expected_revision": 7, "commands": [dense_move]},
            )["project"]
            assert (
                len(p["clips"]["dense"]["keyframes"]) == 2000
                and p["clips"]["dense"]["keyframes"][-1]["at_ticks"] == dense[-1]["at_ticks"] + T
            )
            invalid = client.post(
                url + "/edits",
                json={
                    "request_id": "empty",
                    "expected_revision": 8,
                    "commands": [{**dense_move, "moves": []}],
                },
            )
            assert invalid.status_code == 422
            assert client.get("/v1/capabilities").json()["features"]["multi_keyframe_editing"]
            contract = json.dumps(client.get("/v1/contracts").json())
            assert "keyframes.move" in contract and "keyframes.remove" in contract
    print(
        "PASS: atomic occupied-selected moves, offset clocks, controls, "
        "dry-run/replay/restore, locks/rollback and 2000-key command"
    )


if __name__ == "__main__":
    main()
