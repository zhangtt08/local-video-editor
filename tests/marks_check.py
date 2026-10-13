"""Timeline in/out marks: the contract shape, the plan that trims to them, and a real partial
export whose first frame, duration and audio are the marked window — not a re-planned guess."""

import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import Project, SequenceSettings
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService
from agentcut.render import compile_render_plan, marked_range

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
FRAME = 2_352_000  # one frame at 30 fps
SEGOND = 2 * T
SEGMENTS = (("red", 440), ("green", 880), ("blue", 1320))


def run(args, timeout=420):
    return subprocess.run(
        args, capture_output=True, check=True, timeout=timeout, creationflags=0x08000000
    )


def source(folder: Path) -> Path:
    """Six seconds: red/green/blue two seconds each, with a distinct tone per segment."""
    target = folder / "marks.mp4"
    argv = [str(FFMPEG), "-v", "error", "-y", "-nostdin"]
    for colour, tone in SEGMENTS:
        argv += ["-f", "lavfi", "-i", f"color=c={colour}:s=320x180:r=30:d=2"]
        argv += ["-f", "lavfi", "-i", f"sine=frequency={tone}:duration=2"]
    graph = "".join(f"[{2 * i}:v][{2 * i + 1}:a]" for i in range(3)) + "concat=n=3:v=1:a=1[v][a]"
    argv += [
        "-filter_complex",
        graph,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ar",
        "48000",
        str(target),
    ]
    run(argv)
    return target


def duration_seconds(path: Path) -> float:
    raw = run(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ]
    ).stdout
    return float(json.loads(raw)["format"]["duration"])


def frame_at(path: Path, at: float) -> tuple[int, int, int]:
    raw = run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-ss",
            f"{at:.6f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "scale=1:1:flags=area",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    ).stdout
    assert len(raw) == 3, len(raw)
    return (raw[0], raw[1], raw[2])


def tone_at(path: Path, at: float, seconds: float = 0.5) -> float:
    """Zero-crossing rate of the marked window, as a coarse but decisive pitch check."""
    raw = run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-ss",
            f"{at:.6f}",
            "-t",
            str(seconds),
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "s16le",
            "pipe:1",
        ]
    ).stdout
    samples = [
        int.from_bytes(raw[i : i + 2], "little", signed=True) for i in range(0, len(raw) - 1, 2)
    ]
    crossings = sum(1 for left, right in zip(samples, samples[1:]) if (left < 0) != (right < 0))
    return crossings / 2 / (len(samples) / 8000)


def contract_suite() -> None:
    for bad in (
        {"in_ticks": FRAME, "out_ticks": None},
        {"in_ticks": None, "out_ticks": 4 * FRAME},
        {"in_ticks": 1, "out_ticks": 4 * FRAME},
        {"in_ticks": 4 * FRAME, "out_ticks": 4 * FRAME},
        {"in_ticks": 5 * FRAME, "out_ticks": 4 * FRAME},
    ):
        try:
            SequenceSettings(**bad)
        except ValidationError:
            continue
        raise AssertionError(f"{bad} must not validate")
    marks = SequenceSettings(in_ticks=2 * FRAME, out_ticks=5 * FRAME)
    assert (marks.in_ticks, marks.out_ticks) == (2 * FRAME, 5 * FRAME)
    assert SequenceSettings().in_ticks is None, "an unmarked sequence stays the default"
    print("   marks: half-written, sub-frame and inverted ranges are refused by the contract")


def http_suite(folder: Path) -> None:
    media = MediaService(folder / "mk-db.sqlite3", [folder], folder / "mk-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "mk-api.sqlite3", FFMPEG, folder / "deliverables", [folder / "deliverables"]
    )
    runtime.ensure_worker()
    token = "markschk" + "f" * 54
    app = create_app(folder / "mk-api.sqlite3", token, media=media, jobs=runtime)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        features = client.get("/v1/capabilities").json()["features"]
        assert features["timeline_marks"] is True and features["range_export"] is True, features

        clip = source(folder)
        probe = client.post("/v1/media/import", json={"path": str(clip)}).json()
        created = client.post("/v1/projects", json={"request_id": "new", "name": "marks"}).json()[
            "project"
        ]
        path = f"/v1/projects/{created['id']}"
        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "seed",
                "expected_revision": 0,
                "commands": [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                    {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "a"}},
                    {
                        "op": "asset.import",
                        "asset_id": "s",
                        "label": "marks",
                        "probe_id": probe["verified"]["probe_id"],
                        "verified": probe["verified"],
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "c",
                            "asset_id": "s",
                            "track_id": "v",
                            "position_ticks": 0,
                            "duration_ticks": 6 * T,
                        },
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "s1",
                            "asset_id": "s",
                            "track_id": "a",
                            "position_ticks": 0,
                            "duration_ticks": 6 * T,
                        },
                    },
                ],
            },
        )
        assert seeded.status_code == 200, seeded.text
        settings = seeded.json()["project"]["settings"]

        def mark(in_ticks, out_ticks, request_id, revision):
            return client.post(
                path,
                json={
                    "request_id": request_id,
                    "expected_revision": revision,
                    "settings": {**settings, "in_ticks": in_ticks, "out_ticks": out_ticks},
                },
            )

        beyond = mark(2 * T, 7 * T, "m0", 1)
        assert beyond.status_code == 422, beyond.text
        assert beyond.json()["error"]["code"] == "INVALID_MARKS", beyond.text
        assert client.get(path).json()["revision"] == 1, "a refused mark must not burn a revision"

        marked = mark(2 * T, 4 * T, "m1", 1)
        assert marked.status_code == 200, marked.text
        stored = marked.json()["project"]["settings"]
        assert (stored["in_ticks"], stored["out_ticks"]) == (2 * T, 4 * T), stored
        assert marked.json()["project"]["revision"] == 2, "one mark write is one revision"
        settings = {**settings, "in_ticks": 2 * T, "out_ticks": 4 * T}

        project = client.get(path).json()
        assert marked_range(Project.model_validate(project)) == (2 * T, 4 * T)
        trimmed = client.get(path + "/render-plan?preset_id=proxy-540p-fast&range=marks").json()
        full = client.get(path + "/render-plan?preset_id=proxy-540p-fast").json()
        trimmed_argv = " ".join(trimmed["argv_preview"])
        full_argv = " ".join(full["argv_preview"])
        assert "start_frame=60:end_frame=120" in trimmed_argv, trimmed_argv[-600:]
        assert "atrim=start=2.000000:end=4.000000" in trimmed_argv, (
            "the marked window has to cut the audio too"
        )
        assert "start_frame=60" not in full_argv, "a full render must not carry the trim"
        assert trimmed["plan"]["duration_seconds"] == 2.0, trimmed["plan"]["duration_seconds"]
        assert full["plan"]["duration_seconds"] == 6.0, full["plan"]["duration_seconds"]
        assert trimmed["plan"]["range"]["in_ticks"] == 2 * T
        print("   marks: the plan trims to whole frames and reports the marked duration")

        def render(request_id, payload_extra, revision=2):
            body = {
                "request_id": request_id,
                "expected_revision": revision,
                "preset_id": "h264-720p-web",
                **payload_extra,
            }
            return client.post(path + "/renders", json=body)

        range_job = render("r-marks", {"filename": "marked.mp4", "range": "marks"})
        assert range_job.status_code == 200, range_job.text
        assert range_job.json()["job"]["range"] == "marks", range_job.text
        full_job = render("r-full", {"filename": "whole.mp4"})
        assert full_job.status_code == 200, full_job.text
        assert full_job.json()["job"]["range"] == "full", full_job.text
        legacy = render("r-legacy", {"filename": "legacy.mp4"})
        assert legacy.status_code == 200, legacy.text
        replay = render("r-legacy", {"filename": "legacy.mp4"})
        assert replay.json()["job"]["id"] == legacy.json()["job"]["id"], "old payload still replays"
        flipped = render("r-legacy", {"filename": "legacy.mp4", "range": "marks"})
        assert flipped.status_code == 409, flipped.text
        assert flipped.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT", flipped.text
        print("   marks: a request without `range` still replays as itself; changing it conflicts")

        batch = client.post(
            path + "/renders/batch",
            json={
                "request_id": "b1",
                "expected_revision": 2,
                "items": [
                    {"preset_id": "h264-720p-web", "filename": "pair-full.mp4"},
                    {
                        "preset_id": "h264-720p-web",
                        "filename": "pair-marks.mp4",
                        "range": "marks",
                    },
                ],
            },
        )
        assert batch.status_code == 200, batch.text
        jobs = [job["id"] for job in batch.json()["jobs"]]
        assert len(jobs) == 2, jobs

        done = {}
        ids = [range_job.json()["job"]["id"], full_job.json()["job"]["id"], *jobs]
        for job_id in ids:
            status = {}
            for _ in range(900):
                status = client.get("/v1/jobs/" + job_id).json()
                if status["job"]["status"] in {"succeeded", "failed", "cancelled"}:
                    break
            assert status["job"]["status"] == "succeeded", (job_id, status)
            done[job_id] = Path(status["job"]["output_path"])
        marked_file = done[range_job.json()["job"]["id"]]
        whole_file = done[full_job.json()["job"]["id"]]
        pair_full = done[jobs[0]]
        pair_marks = done[jobs[1]]

        assert abs(duration_seconds(whole_file) - 6.0) <= 0.05, duration_seconds(whole_file)
        assert abs(duration_seconds(marked_file) - 2.0) <= 0.05, duration_seconds(marked_file)
        assert abs(duration_seconds(pair_marks) - 2.0) <= 0.05
        assert abs(duration_seconds(pair_full) - 6.0) <= 0.05
        assert marked_file.stat().st_size < whole_file.stat().st_size

        first = frame_at(marked_file, 0.1)
        # lavfi's `green` is RGB (0,128,0), so the thresholds sit on the source's own levels.
        assert first[1] > 90 and first[0] < 40 and first[2] < 40, (
            "the marked window starts on the green segment",
            first,
        )
        assert frame_at(whole_file, 0.1)[0] > 150, "the full export still starts on red"
        same = frame_at(whole_file, 2.5), frame_at(marked_file, 0.5)
        drift = max(abs(a - b) for a, b in zip(*same))
        assert drift <= 4, ("the marked frames are the same frames, not a re-plan", same, drift)
        pitch = tone_at(marked_file, 0.2)
        assert 800 < pitch < 960, ("the marked window carries the 880 Hz segment", pitch)
        whole_pitch = tone_at(whole_file, 0.2)
        assert 400 < whole_pitch < 480, whole_pitch
        print(
            "   marks: real exports are 6.000 s and 2.000 s; the marked file starts green, plays"
            f" {round(pitch)} Hz instead of {round(whole_pitch)} Hz, and its frames match the full"
            f" render at the same source time within {drift} levels"
        )

        cleared = client.post(
            path,
            json={
                "request_id": "m2",
                "expected_revision": 2,
                "settings": {**settings, "in_ticks": None, "out_ticks": None},
            },
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["project"]["settings"]["in_ticks"] is None
        orphan = client.post(
            path + "/renders",
            json={
                "request_id": "r-orphan",
                "expected_revision": cleared.json()["project"]["revision"],
                "preset_id": "h264-720p-web",
                "filename": "orphan.mp4",
                "range": "marks",
            },
        )
        assert orphan.status_code == 422, orphan.text
        assert orphan.json()["error"]["code"] == "INVALID_MARKS", orphan.text
        assert client.get(path + "/jobs").json()["jobs"], "earlier jobs stay in the table"
        queued = [
            job
            for job in client.get(path + "/jobs").json()["jobs"]
            if job["filename"] == "orphan.mp4"
        ]
        assert not queued, "a refused range must not queue a job"
        print(
            "   marks: clearing the range is one revision, and range=marks without marks is refused"
        )

        history = client.get(path + "/history").json()["history"]
        restore = client.post(
            path + "/restore",
            json={
                "request_id": "m3",
                "expected_revision": cleared.json()["project"]["revision"],
                "target_revision": 2,
            },
        )
        assert restore.status_code == 200, restore.text
        back = restore.json()["project"]["settings"]
        assert (back["in_ticks"], back["out_ticks"]) == (2 * T, 4 * T), back
        assert history, "the marked writes are in the history"
        print("   marks: undo brings the marked window back as a new revision")


def plan_suite(folder: Path) -> None:
    """The trim is frame-exact and refuses a range outside the timeline."""
    clip = source(folder)
    project = Project.model_validate(
        {
            "id": "p",
            "name": "marks",
            "settings": {
                "width": 320,
                "height": 180,
                "frame_rate": {"numerator": 30, "denominator": 1},
                "in_ticks": 1 * T,
                "out_ticks": 5 * T,
            },
            "tracks": [{"id": "v", "kind": "video", "name": "v"}],
            "assets": {
                "s": {
                    "id": "s",
                    "kind": "video",
                    "label": "s",
                    "reference": "r",
                    "duration_ticks": 6 * T,
                    "verified": {
                        "probe_id": "a",
                        "path": str(clip),
                        "kind": "video",
                        "label": "s",
                        "size_bytes": clip.stat().st_size,
                        "content_sha256": "0" * 64,
                        "duration_ticks": 6 * T,
                        "width": 320,
                        "height": 180,
                        "has_audio": False,
                    },
                }
            },
            "clips": {
                "c": {
                    "id": "c",
                    "asset_id": "s",
                    "track_id": "v",
                    "position_ticks": 0,
                    "duration_ticks": 6 * T,
                }
            },
        }
    )
    plan = compile_render_plan(project, "proxy-540p-fast", range_ticks=marked_range(project))
    stage = next(stage for stage in plan.filters if "trim=start_frame=" in stage)
    assert "start_frame=30:end_frame=150" in stage, stage
    assert plan.duration_ticks == 4 * T, plan.duration_ticks
    for bad in ((0, 7 * T), (5 * T, 5 * T), (-1, 2 * T)):
        try:
            compile_render_plan(project, "proxy-540p-fast", range_ticks=bad)
        except Exception as failure:  # EditorError, raised by the one authority
            assert "range" in str(failure).lower() or "INVALID_MARKS" in str(failure), failure
            continue
        raise AssertionError(f"{bad} must be refused")
    print("   marks: the frame window is exact and an out-of-timeline range is refused")


def main():
    import tempfile

    with tempfile.TemporaryDirectory(prefix="agentcut-marks-") as scratch:
        folder = Path(scratch)
        contract_suite()
        plan_suite(folder)
        http_suite(folder)
    print(
        "PASS: timeline marks validate, trim the finished mix to whole frames, and a partial"
        " export delivers the same frames, duration and audio as the marked window"
    )


if __name__ == "__main__":
    main()
