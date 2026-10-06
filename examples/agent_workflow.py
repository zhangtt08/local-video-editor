"""Runnable API workflow; registers demo metadata and edits without reading media."""

import os
from uuid import uuid4

import httpx

from agentcut.contracts import TIMEBASE


def main():
    token = os.environ.get("AGENTCUT_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("Set the same AGENTCUT_TOKEN used by the running API")
    with httpx.Client(
        base_url=os.environ.get("AGENTCUT_API_URL", "http://127.0.0.1:8765"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    ) as api:

        def call(method, path, payload=None):
            response = api.request(method, path, json=payload)
            response.raise_for_status()
            return response.json()

        assert "clip.split" in call("GET", "/v1/capabilities")["commands"]
        project = call(
            "POST",
            "/v1/projects",
            {
                "request_id": uuid4().hex,
                "name": "Agent editing demo",
            },
        )["project"]
        request = {
            "request_id": uuid4().hex,
            "expected_revision": project["revision"],
            "commands": [
                {"op": "track.add", "track": {"id": "v1", "kind": "video", "name": "Video"}},
                {
                    "op": "asset.register",
                    "asset": {
                        "id": "a1",
                        "kind": "video",
                        "label": "Unverified demo metadata",
                        "reference": "media://demo",
                        "duration_ticks": 10 * TIMEBASE,
                    },
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "c1",
                        "asset_id": "a1",
                        "track_id": "v1",
                        "position_ticks": 0,
                        "source_in_ticks": TIMEBASE,
                        "duration_ticks": 4 * TIMEBASE,
                    },
                },
                {
                    "op": "clip.split",
                    "clip_id": "c1",
                    "at_ticks": 2 * TIMEBASE,
                    "right_clip_id": "c2",
                },
                {"op": "clip.remove", "clip_id": "c2"},
            ],
            "dry_run": True,
        }
        path = f"/v1/projects/{project['id']}/edits"
        preview = call("POST", path, request)
        assert not preview["committed"]
        request["dry_run"] = False
        result = call("POST", path, request)
        assert result["project"] == preview["project"]
        assert call("POST", path, request)["replayed"]
        print(f"Created project {project['id']}; revision={result['project']['revision']}; clips=1")
        print("Timeline state saved. Media decoding/rendering is not yet implemented.")


if __name__ == "__main__":
    main()
