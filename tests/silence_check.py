"""Silence detection against a synthetic tone with known gaps: the detector must find exactly those
spans, the plan it returns must be ordinary split + ripple-remove commands, and the exported audio
must have no long silence left in it."""

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import (
    Clip,
    EditBatch,
    EditorError,
    Project,
    VerifiedMedia,
    audio_scan_problem,
)
from agentcut.http_api import create_app
from agentcut.media import MediaService
from agentcut.render import compile_render_plan
from agentcut.silence import _detect, analyse, cut_plan
from agentcut.timeline import apply_commands, validate_timeline

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
WIDTH, HEIGHT, FPS = 320, 180, 30
FRAME = T // FPS
SECONDS = 6.0
# Where the generated tone is actually silent, in source seconds.
GATES = ((2.0, 2.8), (4.0, 4.5))


def build_source(target: Path, gates: tuple = GATES) -> None:
    spans = "+".join(f"between(t,{start},{stop})" for start, stop in gates)
    subprocess.run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-y",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={SECONDS}:sample_rate=48000",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x404040:s={WIDTH}x{HEIGHT}:d={SECONDS}",
            "-af",
            f"volume=enable='{spans}':volume=0",
            "-c:a",
            "pcm_s16le",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-shortest",
            str(target),
        ],
        check=True,
        capture_output=True,
        timeout=300,
        creationflags=0x08000000,
    )


def clip_payload(**changes) -> dict:
    clip = {
        "id": "c",
        "asset_id": "a",
        "track_id": "v",
        "position_ticks": 0,
        "duration_ticks": int(SECONDS * T),
    }
    clip.update(changes)
    return clip


def verified_record(path: Path) -> VerifiedMedia:
    return VerifiedMedia.model_validate(
        {
            "probe_id": "a",
            "path": str(path),
            "kind": "video",
            "label": "tone",
            "size_bytes": path.stat().st_size,
            "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "duration_ticks": int(SECONDS * T),
            "width": WIDTH,
            "height": HEIGHT,
            "has_audio": True,
        }
    )


def project_payload(clip: dict, extra_clips: list[dict] = ()) -> Project:
    return Project.model_validate(
        {
            "id": "p",
            "name": "silence",
            "settings": {"width": WIDTH, "height": HEIGHT},
            "tracks": [
                {"id": "v", "kind": "video", "name": "v"},
                {"id": "s", "kind": "audio", "name": "s"},
            ],
            "assets": {
                "a": {
                    "id": "a",
                    "kind": "video",
                    "label": "a",
                    "reference": "r",
                    "duration_ticks": int(SECONDS * T),
                }
            },
            "clips": {"c": clip, **{item["id"]: item for item in extra_clips}},
        }
    )


def scan(clip: Clip, source: Path | None = None, **changes) -> dict:
    return analyse(FFMPEG, source or SOURCE, clip, FRAME, **changes)


def apply(project: Project, commands: list[dict]) -> Project:
    batch = EditBatch(request_id="check", expected_revision=project.revision, commands=commands)
    return apply_commands(project, batch.commands)


SOURCE = Path("")


def detect_suite() -> None:
    """The reported spans must be the real ones, on the frame grid, and never over the word."""
    body = scan(project_payload(clip_payload()).clips["c"])
    gaps = body["gaps"]
    assert len(gaps) == 2, gaps
    assert body["edges"] == [] and body["frame_ticks"] == FRAME, body
    for (start, stop), gap in zip(GATES, gaps):
        assert gap["from_ticks"] % FRAME == 0 and gap["to_ticks"] % FRAME == 0, gap
        assert gap["from_ticks"] / T >= start, gap
        assert gap["from_ticks"] / T - start < 2 * FRAME / T, gap
        assert stop <= gap["to_ticks"] / T <= stop + 2 * FRAME / T, gap
        assert gap["length_ticks"] == gap["to_ticks"] - gap["from_ticks"], gap
    print(
        "   found",
        [(round(g["from_ticks"] / T, 3), round(g["to_ticks"] / T, 3)) for g in gaps],
        f"for gates {GATES}, removed {body['removed_ticks'] / T:.3f}s",
    )

    # A longer floor must drop the shorter gap rather than invent a compromise.
    strict = scan(project_payload(clip_payload()).clips["c"], min_silence_ms=600)
    assert len(strict["gaps"]) == 1 and strict["gaps"][0]["length_ticks"] > 600 * T // 1000, strict
    wide = scan(project_payload(clip_payload()).clips["c"], min_silence_ms=5000)
    assert wide["gaps"] == [] and wide["removed_ticks"] == 0, wide

    # Scanning from mid-clip still reports clip-absolute positions.
    tail = scan(project_payload(clip_payload()).clips["c"], from_ticks=3 * T)
    assert [gap["from_ticks"] for gap in tail["gaps"]] == [121 * FRAME], tail["gaps"]

    # 200% plays the source twice as fast, so each gap halves in clip time.
    fast = scan(project_payload(clip_payload(speed_percent=200)).clips["c"], min_silence_ms=150)
    assert len(fast["gaps"]) == 2, fast["gaps"]
    assert abs(fast["gaps"][0]["length_ticks"] - (GATES[0][1] - GATES[0][0]) * T / 2) < 3 * FRAME, (
        fast
    )
    assert fast["gaps"][0]["from_ticks"] >= T, fast["gaps"][0]
    # The shorter gap halves below the 250 ms floor once snapped inward, so it is not cut at all.
    assert len(scan(project_payload(clip_payload(speed_percent=200)).clips["c"])["gaps"]) == 1

    for label, clip_data in (
        (
            "speed curve",
            clip_payload(
                speed_curve=[{"at_ticks": 0, "percent": 100}, {"at_ticks": T, "percent": 150}]
            ),
        ),
        ("shorter than a frame", clip_payload(duration_ticks=FRAME // 2)),
    ):
        try:
            scan(project_payload(clip_data).clips["c"])
        except EditorError as error:
            assert error.code == "INVALID_SILENCE_TARGET", (label, error.payload())
        else:
            raise AssertionError(f"{label} must refuse a silence scan")


def plan_suite() -> None:
    """The plan is made of existing commands, and the reducer's clocks come out right."""
    base = project_payload(
        clip_payload(keyframes=[{"property": "opacity", "at_ticks": int(5.0 * T), "value": 0.4}])
    )
    body = scan(base.clips["c"])
    commands = cut_plan(base.clips["c"], body["gaps"])
    assert [command["op"] for command in commands] == [
        "clip.split",
        "clip.split",
        "clip.ripple_remove",
        "clip.split",
        "clip.split",
        "clip.ripple_remove",
    ], commands
    assert all(command["clip_id"] != "c" or "at_ticks" in command for command in commands)

    edited = apply(base, commands)
    survivors = sorted(edited.clips.values(), key=lambda item: item.position_ticks)
    assert [item.id for item in survivors] == ["c", "c-gap2", "c-gap0"], [
        item.id for item in survivors
    ]
    removed = body["removed_ticks"]
    assert sum(item.duration_ticks for item in survivors) == int(SECONDS * T) - removed, removed
    cursor = 0
    for item in survivors:
        assert item.position_ticks == cursor, (item.id, item.position_ticks, cursor)
        cursor += item.duration_ticks
    # The source clock must jump over each removed silence, not play it again.
    assert [(item.source_in_ticks, item.duration_ticks) for item in survivors] == [
        (0, 61 * FRAME),
        (int(2.8 * T), 37 * FRAME),
        (int(4.5 * T), 45 * FRAME),
    ], [(item.source_in_ticks, item.duration_ticks) for item in survivors]
    keyed = {
        item.id: [(key.property, key.at_ticks) for key in item.keyframes] for item in survivors
    }
    assert all(marks == [("opacity", int(5.0 * T))] for marks in keyed.values()), keyed
    assert Clip.model_validate(survivors[0].model_dump())
    validate_timeline(edited)
    print(
        "   plan kept",
        [
            (item.id, round(item.position_ticks / T, 3), round(item.source_in_ticks / T, 3))
            for item in survivors
        ],
        "and every survivor keeps the original keyframe list verbatim",
    )

    linked = project_payload(
        clip_payload(link_id="l1"),
        [
            {
                "id": "s1",
                "asset_id": "a",
                "track_id": "s",
                "position_ticks": 0,
                "duration_ticks": int(SECONDS * T),
                "link_id": "l1",
            }
        ],
    )
    for item in (base, linked):
        item.assets["a"].verified = verified_record(SOURCE)
    problem = audio_scan_problem(linked, linked.clips["c"])
    assert problem and "linked" in problem, problem
    assert audio_scan_problem(base, base.clips["c"]) is None
    assert cut_plan(project_payload(clip_payload()).clips["c"], []) == []
    assert cut_plan(
        project_payload(clip_payload()).clips["c"],
        [{"from_ticks": 0, "to_ticks": 3 * FRAME}],
        edges=True,
    ) == [
        {"op": "clip.split", "clip_id": "c", "at_ticks": 3 * FRAME, "right_clip_id": "c-gap0"},
        {"op": "clip.ripple_remove", "clip_id": "c"},
    ], "a leading span is one split plus removing the head piece"


def http_suite(folder: Path) -> None:
    media = MediaService(
        folder / "db.sqlite3", [folder / "media"], folder / "cache", FFMPEG, FFPROBE
    )
    source = folder / "media" / "tone.mp4"
    source.parent.mkdir(exist_ok=True)
    build_source(source)
    token = "silence" + "e" * 55
    app = create_app(folder / "api.sqlite3", token, media=media)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        caps = client.get("/v1/capabilities").json()
        assert caps["features"]["silence_detection"] is True, caps["features"]
        assert "clip.split" in caps["commands"] and "clip.ripple_remove" in caps["commands"]
        probe = client.post("/v1/media/import", json={"path": str(source)}).json()
        assert probe["verified"]["has_audio"] is True, probe
        project = client.post("/v1/projects", json={"request_id": "new", "name": "silence"}).json()[
            "project"
        ]
        path = f"/v1/projects/{project['id']}"
        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "seed",
                "expected_revision": 0,
                "commands": [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                    {
                        "op": "asset.import",
                        "asset_id": "a",
                        "label": "tone",
                        "probe_id": probe["id"],
                        "verified": probe["verified"],
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "c",
                            "asset_id": "a",
                            "track_id": "v",
                            "position_ticks": 0,
                            "duration_ticks": int(SECONDS * T),
                        },
                    },
                ],
            },
        )
        assert seeded.status_code == 200, seeded.text
        scan_path = path + "/clips/c/silence"

        read_only = client.post(scan_path, json={"request_id": "scan", "expected_revision": 1})
        assert read_only.status_code == 200, read_only.text
        body = read_only.json()
        assert body["committed"] is False and client.get(path).json()["revision"] == 1
        found = body["silence"]
        assert len(found["gaps"]) == 2 and len(found["commands"]) == 6, found
        assert found["removed_ticks"] > T // 2, found
        print(
            "   http scan:",
            [(gap["from_ticks"], gap["to_ticks"]) for gap in found["gaps"]],
            f"-> {len(found['commands'])} commands, {found['removed_ticks'] / T:.3f}s",
        )

        preview = client.post(
            scan_path,
            json={
                "request_id": "apply-dry",
                "expected_revision": 1,
                "apply": True,
                "dry_run": True,
                "min_silence_ms": 300,
            },
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["committed"] is False
        assert client.get(path).json()["revision"] == 1, "a dry run must not write"

        written = client.post(
            scan_path, json={"request_id": "apply", "expected_revision": 1, "apply": True}
        )
        assert written.status_code == 200, written.text
        result = written.json()
        assert result["committed"] is True and result["project"]["revision"] == 2
        assert len(result["project"]["clips"]) == 3, result["project"]["clips"].keys()
        assert sorted(
            (round(item["source_in_ticks"] / T, 3), round(item["duration_ticks"] / T, 3))
            for item in result["project"]["clips"].values()
        ) == [(0.0, 2.033), (2.8, 1.233), (4.5, 1.5)], result["project"]["clips"]

        # Re-scanning the cut clip finds nothing left to remove: the gaps are really gone from it.
        after = client.post(scan_path, json={"request_id": "rescan", "expected_revision": 2})
        assert after.json()["silence"]["gaps"] == [] and after.json()["silence"]["commands"] == []
        assert after.json()["committed"] is False

        # The write went through the same receipt store, so replaying those commands is a replay.
        replay = client.post(
            path + "/edits",
            json={
                "request_id": "apply",
                "expected_revision": 1,
                "commands": result["silence"]["commands"],
            },
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["replayed"] is True and replay.json()["project"]["revision"] == 2
        conflict = client.post(
            path + "/edits",
            json={
                "request_id": "again",
                "expected_revision": 1,
                "commands": result["silence"]["commands"],
            },
        )
        assert conflict.status_code == 409, conflict.text
        nothing = client.post(
            scan_path,
            json={
                "request_id": "none",
                "expected_revision": 2,
                "apply": True,
                "min_silence_ms": 5000,
            },
        )
        assert nothing.json()["error"]["code"] == "INVALID_SILENCE_TARGET", nothing.text
        assert client.get(path).json()["revision"] == 2

        # A clip whose media really has no audio track must be refused, not scanned into nothing.
        quiet = folder / "media" / "mute.mp4"
        subprocess.run(
            [
                str(FFMPEG),
                "-v",
                "error",
                "-y",
                "-nostdin",
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x404040:s={WIDTH}x{HEIGHT}:d=2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-an",
                str(quiet),
            ],
            check=True,
            capture_output=True,
            timeout=300,
            creationflags=0x08000000,
        )
        mute_probe = client.post("/v1/media/import", json={"path": str(quiet)}).json()
        assert mute_probe["verified"]["has_audio"] is False, mute_probe
        added = client.post(
            path + "/edits",
            json={
                "request_id": "mute",
                "expected_revision": 2,
                "commands": [
                    {
                        "op": "asset.import",
                        "asset_id": "pic",
                        "label": "mute",
                        "probe_id": mute_probe["id"],
                        "verified": mute_probe["verified"],
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "pic1",
                            "asset_id": "pic",
                            "track_id": "v",
                            "position_ticks": int(SECONDS * T),
                            "duration_ticks": 2 * T,
                        },
                    },
                ],
            },
        )
        assert added.status_code == 200, added.text
        refused = client.post(
            path + "/clips/pic1/silence", json={"request_id": "no-audio", "expected_revision": 3}
        )
        assert refused.json()["error"]["code"] == "INVALID_SILENCE_TARGET", refused.text
        missing = client.post(
            path + "/clips/nope/silence", json={"request_id": "ghost", "expected_revision": 3}
        )
        assert missing.status_code == 404, missing.text

        # The whole-track endpoint walks the same rule: it skips what cannot be scanned.
        whole = client.post(
            path + "/tracks/v/silence", json={"request_id": "track-scan", "expected_revision": 3}
        )
        assert whole.status_code == 200, whole.text
        merged = whole.json()["silence"]
        assert whole.json()["committed"] is False and client.get(path).json()["revision"] == 3
        assert merged["commands"] == [] and merged["removed_ticks"] == 0, merged
        assert [item["clip_id"] for item in merged["clips"]] == ["pic1", "c-gap0", "c-gap2", "c"]
        assert "audio" in merged["clips"][0]["skipped"], merged["clips"][0]
        assert all(item.get("gaps") == [] for item in merged["clips"][1:]), merged["clips"]
        empty = client.post(
            path + "/tracks/v/silence",
            json={"request_id": "track-empty", "expected_revision": 3, "apply": True},
        )
        assert empty.json()["error"]["code"] == "INVALID_SILENCE_TARGET", empty.text
        ghost = client.post(
            path + "/tracks/nope/silence",
            json={"request_id": "track-ghost", "expected_revision": 3},
        )
        assert ghost.status_code == 404, ghost.text


def media_suite(folder: Path) -> None:
    """After the cut the exported audio must not contain a long silence any more."""
    verified = {
        "probe_id": "a",
        "path": str(SOURCE),
        "kind": "video",
        "label": "tone",
        "size_bytes": SOURCE.stat().st_size,
        "content_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "duration_ticks": int(SECONDS * T),
        "width": WIDTH,
        "height": HEIGHT,
        "has_audio": True,
    }
    project = project_payload(clip_payload())
    project.assets["a"].verified = VerifiedMedia.model_validate(verified)
    validate_timeline(project)
    body = scan(project.clips["c"])
    cut = apply(project, cut_plan(project.clips["c"], body["gaps"]))
    out = folder / "cut.mp4"
    plan = compile_render_plan(cut, "h264-source-quality")
    job = folder / "cut-job"
    job.mkdir(exist_ok=True)
    for name, content in plan.text_files.items():
        (job / name).write_text(content, encoding="utf-8")
    process = subprocess.run(
        plan.ffmpeg_argv(str(FFMPEG), str(out)),
        cwd=job,
        capture_output=True,
        timeout=300,
        creationflags=0x08000000,
    )
    assert process.returncode == 0, process.stderr.decode(errors="replace")[-800:]
    meta = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_format", "-of", "json", str(out)],
        capture_output=True,
        check=True,
        timeout=120,
        creationflags=0x08000000,
    ).stdout
    duration = float(json.loads(meta)["format"]["duration"])
    expected = SECONDS - body["removed_ticks"] / T
    assert abs(duration - expected) < 0.1, (duration, expected)

    left = _detect(FFMPEG, out, 0.0, duration, -35.0, 0.25)
    assert left == [], left
    print(
        f"   exported cut is {duration:.3f}s (expected {expected:.3f}s) and silencedetect finds "
        "no gap of 0.25s or longer in it",
    )


def track_suite(folder: Path) -> None:
    """One pass over a whole track: interior cuts plus the leading and trailing holes it closes."""
    source = folder / "edges.mp4"
    build_source(source, gates=((0.0, 0.6), (2.0, 2.6), (4.5, 6.0)))
    project = project_payload(
        clip_payload(id="c", duration_ticks=3 * T),
        [clip_payload(id="b", position_ticks=3 * T, duration_ticks=3 * T, source_in_ticks=3 * T)],
    )
    project.assets["a"].verified = verified_record(source)
    validate_timeline(project)
    commands: list[dict] = []
    removed = 0
    for clip in sorted(project.clips.values(), key=lambda item: -item.position_ticks):
        body = scan(clip, source=source)
        spans = [*body["gaps"], *body["edges"]]
        commands.extend(cut_plan(clip, spans, edges=True))
        removed += sum(span["length_ticks"] for span in spans)
    assert [command["op"] for command in commands].count("clip.ripple_remove") == 3, commands
    assert removed > 2 * T, removed / T
    cut = apply(project, commands)
    survivors = sorted(cut.clips.values(), key=lambda item: item.position_ticks)
    cursor = 0
    for item in survivors:
        assert item.position_ticks == cursor, (item.id, item.position_ticks, cursor)
        cursor += item.duration_ticks
    assert cursor == int(SECONDS * T) - removed, (cursor / T, removed / T)
    print(
        "   track plan kept",
        [
            (item.id, round(item.position_ticks / T, 3), round(item.source_in_ticks / T, 3))
            for item in survivors
        ],
    )

    out = folder / "track-cut.mp4"
    plan = compile_render_plan(cut, "h264-source-quality")
    job = folder / "track-job"
    job.mkdir(exist_ok=True)
    for name, content in plan.text_files.items():
        (job / name).write_text(content, encoding="utf-8")
    process = subprocess.run(
        plan.ffmpeg_argv(str(FFMPEG), str(out)),
        cwd=job,
        capture_output=True,
        timeout=300,
        creationflags=0x08000000,
    )
    assert process.returncode == 0, process.stderr.decode(errors="replace")[-800:]
    left = _detect(FFMPEG, out, 0.0, cursor / T, -35.0, 0.25)
    assert left == [], left
    print(f"   exported track cut is {cursor / T:.3f}s and holds no gap of 0.25s or longer: {left}")


def main() -> None:
    global SOURCE

    with tempfile.TemporaryDirectory(prefix="agentcut-silence-") as scratch:
        folder = Path(scratch)
        SOURCE = folder / "tone.mp4"
        build_source(SOURCE)
        detect_suite()
        plan_suite()
        http_suite(folder)
        media_suite(folder)
        track_suite(folder)
    print(
        "PASS: silence detection finds the real gaps on the frame grid, the plan it returns is",
        "made of ordinary cut commands, and the exported audio has no long silence left",
    )


if __name__ == "__main__":
    main()
