"""Insert/overwrite intervals, source clocks, lock protection and real HTTP receipts."""

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.animation import sample
from agentcut.contracts import (
    MAX_TICKS,
    TIMEBASE,
    Asset,
    EditBatch,
    EditorError,
    Project,
    TextStyle,
)
from agentcut.http_api import create_app
from agentcut.timeline import apply_commands


def main():
    project = Project.model_validate(
        {
            "id": "p",
            "name": "placement",
            "tracks": [
                {"id": "v", "kind": "video", "name": "v"},
                {"id": "a", "kind": "audio", "name": "a"},
            ],
            "assets": {
                "video": {
                    "id": "video",
                    "kind": "video",
                    "label": "v",
                    "reference": "test",
                    "duration_ticks": 12 * TIMEBASE,
                },
                "audio": {
                    "id": "audio",
                    "kind": "audio",
                    "label": "a",
                    "reference": "test",
                    "duration_ticks": 12 * TIMEBASE,
                },
            },
            "clips": {
                "c": {
                    "id": "c",
                    "asset_id": "video",
                    "track_id": "v",
                    "position_ticks": 0,
                    "source_in_ticks": TIMEBASE,
                    "duration_ticks": 4 * TIMEBASE,
                    "speed_percent": 200,
                    "keyframes": [
                        {"property": "x", "at_ticks": 0, "value": 0.0, "interpolation": "ease"},
                        {"property": "x", "at_ticks": 4 * TIMEBASE, "value": 1.0},
                    ],
                },
                "sound": {
                    "id": "sound",
                    "asset_id": "audio",
                    "track_id": "a",
                    "position_ticks": 0,
                    "duration_ticks": 4 * TIMEBASE,
                },
                "tail": {
                    "id": "tail",
                    "asset_id": "video",
                    "track_id": "v",
                    "position_ticks": 5 * TIMEBASE,
                    "duration_ticks": TIMEBASE,
                },
            },
        }
    )
    incoming = {
        "id": "new",
        "asset_id": "video",
        "track_id": "v",
        "position_ticks": TIMEBASE,
        "source_in_ticks": 2 * TIMEBASE,
        "duration_ticks": TIMEBASE,
    }

    def request(op, clip=None, **extra):
        return EditBatch.model_validate(
            {
                "request_id": "edit",
                "expected_revision": 0,
                "commands": [{"op": op, "clip": clip or incoming, **extra}],
            }
        )

    inserted = apply_commands(project, request("clip.insert", ripple_track_ids=["v", "a"]).commands)
    assert inserted.clips["c"].duration_ticks == TIMEBASE
    assert inserted.clips["tail"].position_ticks == 6 * TIMEBASE
    right = next(
        c
        for c in inserted.clips.values()
        if c.asset_id == "video" and c.position_ticks == 2 * TIMEBASE
    )
    assert right.source_in_ticks == 3 * TIMEBASE and right.animation_offset_ticks == TIMEBASE
    assert sample(right, "x", TIMEBASE) == sample(project.clips["c"], "x", 2 * TIMEBASE)
    assert (
        next(
            c
            for c in inserted.clips.values()
            if c.track_id == "a" and c.position_ticks == 2 * TIMEBASE
        ).source_in_ticks
        == TIMEBASE
    )
    assert project.clips["c"].duration_ticks == 4 * TIMEBASE  # original never changes
    assert (
        apply_commands(project, request("clip.insert").commands).clips["sound"]
        == project.clips["sound"]
    )
    assert apply_commands(project, request("clip.insert").commands) == apply_commands(
        project, request("clip.insert").commands
    )
    overwritten = apply_commands(project, request("clip.overwrite").commands)
    right = next(
        c
        for c in overwritten.clips.values()
        if c.asset_id == "video" and c.position_ticks == 2 * TIMEBASE
    )
    assert right.source_in_ticks == 5 * TIMEBASE and right.duration_ticks == 2 * TIMEBASE
    assert right.animation_offset_ticks == 2 * TIMEBASE
    assert overwritten.clips["tail"] == project.clips["tail"]
    assert overwritten.clips["sound"] == project.clips["sound"]
    prefix = apply_commands(
        project,
        request(
            "clip.overwrite", {**incoming, "position_ticks": 0, "duration_ticks": 2 * TIMEBASE}
        ).commands,
    )
    assert (
        prefix.clips["c"].position_ticks == 2 * TIMEBASE
        and prefix.clips["c"].source_in_ticks == 5 * TIMEBASE
    )
    suffix = apply_commands(
        project,
        request(
            "clip.overwrite",
            {**incoming, "position_ticks": 3 * TIMEBASE, "duration_ticks": 2 * TIMEBASE},
        ).commands,
    )
    assert suffix.clips["c"].duration_ticks == 3 * TIMEBASE
    covered = apply_commands(
        project,
        request(
            "clip.overwrite", {**incoming, "position_ticks": 0, "duration_ticks": 5 * TIMEBASE}
        ).commands,
    )
    assert "c" not in covered.clips and covered.clips["tail"] == project.clips["tail"]
    for kind in ("image", "text"):
        static = project.model_copy(deep=True)
        static.assets["still"] = Asset(id="still", kind=kind, label=kind, reference="test")
        static.clips["c"].asset_id = "still"
        static.clips["c"].source_in_ticks = 0
        static.clips["c"].speed_percent = 100
        static.clips["c"].text = TextStyle(body="subtitle") if kind == "text" else None
        result = apply_commands(static, request("clip.overwrite").commands)
        right = next(
            c
            for c in result.clips.values()
            if c.asset_id == "still" and c.position_ticks == 2 * TIMEBASE
        )
        assert right.source_in_ticks == 0 and right.animation_offset_ticks == 2 * TIMEBASE
    for command, code in [
        (request("clip.insert", ripple_track_ids=[]), "INVALID_RIPPLE_TRACKS"),
        (request("clip.insert", ripple_track_ids=["v", "v"]), "INVALID_RIPPLE_TRACKS"),
        (request("clip.insert", ripple_track_ids=["v", "missing"]), "MISSING_REFERENCE"),
        (request("clip.overwrite", {**incoming, "id": "c"}), "DUPLICATE_ID"),
        (
            request("clip.overwrite", {**incoming, "position_ticks": TIMEBASE + 1}),
            "TIME_NOT_ALIGNED",
        ),
        (
            request("clip.overwrite", {**incoming, "source_in_ticks": 12 * TIMEBASE}),
            "SOURCE_OUT_OF_BOUNDS",
        ),
    ]:
        try:
            apply_commands(project, command.commands)
        except EditorError as error:
            assert error.code == code, error
        else:
            raise AssertionError(code)
    locked = project.model_copy(deep=True)
    locked.tracks[1].locked = True
    try:
        apply_commands(locked, request("clip.insert", ripple_track_ids=["v", "a"]).commands)
    except EditorError as error:
        assert error.code == "TRACK_LOCKED" and locked.clips == project.clips
    else:
        raise AssertionError("locked ripple track was edited")
    edge = project.model_copy(deep=True)
    q = edge.settings.frame_ticks
    edge.clips["tail"].position_ticks = MAX_TICKS // q * q - TIMEBASE
    try:
        apply_commands(edge, request("clip.insert").commands)
    except EditorError as error:
        assert error.code == "TIME_OVERFLOW"
    else:
        raise AssertionError("ripple exceeded JSON clock")
    fractional = project.model_copy(deep=True)
    fractional.settings.frame_rate.numerator = 30000
    fractional.settings.frame_rate.denominator = 1001
    fractional.clips = {}
    try:
        apply_commands(
            fractional,
            request(
                "clip.insert",
                {
                    **incoming,
                    "position_ticks": 0,
                    "duration_ticks": fractional.settings.frame_ticks,
                },
                ripple_track_ids=["v", "a"],
            ).commands,
        )
    except EditorError as error:
        assert error.code == "TIME_NOT_ALIGNED"
    else:
        raise AssertionError("incompatible cross-track clocks accepted")
    with tempfile.TemporaryDirectory(prefix="agentcut-placement-") as folder:
        with TestClient(
            create_app(Path(folder) / "test.sqlite", "x" * 32), base_url="http://127.0.0.1"
        ) as client:
            client.headers["Authorization"] = "Bearer " + "x" * 32
            created = client.post(
                "/v1/projects", json={"request_id": "create", "name": "HTTP placement"}
            ).json()["project"]
            url = f"/v1/projects/{created['id']}/edits"
            seed = {
                "request_id": "seed",
                "expected_revision": 0,
                "commands": [
                    *[{"op": "track.add", "track": t.model_dump()} for t in project.tracks],
                    *[
                        {"op": "asset.register", "asset": a.model_dump()}
                        for a in project.assets.values()
                    ],
                    *[{"op": "clip.add", "clip": c.model_dump()} for c in project.clips.values()],
                ],
            }
            assert client.post(url, json=seed).status_code == 200
            body = request("clip.insert", ripple_track_ids=["v", "a"]).model_dump()
            body.update(expected_revision=1, dry_run=True)
            preview = client.post(url, json=body)
            assert preview.status_code == 200, preview.text
            assert client.get(f"/v1/projects/{created['id']}").json()["revision"] == 1
            body["dry_run"] = False
            committed = client.post(url, json=body).json()
            assert committed["project"]["clips"] == preview.json()["project"]["clips"]
            assert client.post(url, json=body).json()["replayed"]
            schema = client.get("/v1/contracts").text
            assert "clip.insert" in schema and "clip.overwrite" in schema
    print("PASS: insert/overwrite, sync tracks, speed/animation clocks, locks, HTTP receipts")


if __name__ == "__main__":
    main()
