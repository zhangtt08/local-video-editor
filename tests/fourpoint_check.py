"""Four-point editing: two source points and two destination points, resolved into ordinary
placement commands, then measured in a real export — trimmed when the source is long, re-timed
when it is short, and never silently guessing."""

import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import Clip, ClipColor, FourPointRequest, Project
from agentcut.fourpoint import plan
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
FRAME = 2_352_000
T2, T4, T6 = 2 * T, 4 * T, 6 * T


def run(argv, timeout=420):
    return subprocess.run(
        argv, capture_output=True, check=True, timeout=timeout, creationflags=0x08000000
    )


def source(folder: Path) -> Path:
    target = folder / "fourpoint.mp4"
    run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=320x180:r=30:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-f",
            "lavfi",
            "-i",
            "color=c=green:s=320x180:r=30:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=2",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:r=30:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1320:duration=2",
            "-filter_complex",
            "[0:v][1:a][2:v][3:a][4:v][5:a]concat=n=3:v=1:a=1[v][a]",
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
    )
    return target


def project_of(clip_source: Path) -> Project:
    return Project.model_validate(
        {
            "id": "p",
            "name": "four-point",
            "settings": {
                "width": 320,
                "height": 180,
                "frame_rate": {"numerator": 30, "denominator": 1},
            },
            "tracks": [
                {"id": "v", "kind": "video", "name": "v"},
                {"id": "a", "kind": "audio", "name": "a"},
            ],
            "assets": {
                "s": {
                    "id": "s",
                    "kind": "video",
                    "label": "s",
                    "reference": "r",
                    "duration_ticks": T6,
                    "verified": {
                        "probe_id": "a",
                        "path": str(clip_source),
                        "kind": "video",
                        "label": "s",
                        "size_bytes": clip_source.stat().st_size,
                        "content_sha256": "0" * 64,
                        "duration_ticks": T6,
                        "width": 320,
                        "height": 180,
                        "has_audio": True,
                    },
                },
                "tone": {
                    "id": "tone",
                    "kind": "audio",
                    "label": "tone",
                    "reference": "r",
                    "duration_ticks": T6,
                    "verified": {
                        "probe_id": "b",
                        "path": str(clip_source),
                        "kind": "audio",
                        "label": "tone",
                        "size_bytes": clip_source.stat().st_size,
                        "content_sha256": "1" * 64,
                        "duration_ticks": T6,
                        "width": None,
                        "height": None,
                        "has_audio": True,
                    },
                },
            },
            "clips": {},
        }
    )


def ask(project: Project, **overrides):
    body = {
        "asset_id": "s",
        "track_id": "v",
        "clip_id": "c1",
        "source_in_ticks": 0,
        "source_out_ticks": T2,
        "dest_in_ticks": 0,
        "dest_out_ticks": T2,
    } | overrides
    return plan(project, **body)


def plan_suite(folder: Path) -> None:
    project = project_of(source(folder))

    commands, notes = ask(project)
    clip = commands[0]["clip"]
    assert commands[0]["op"] == "clip.insert" and notes["resolution"] == "exact", notes
    assert (clip["duration_ticks"], clip["source_in_ticks"], clip["speed_percent"]) == (T2, 0, 100)
    # 1.267 把 25/400 收成两个常量时，把 `Clip.speed_percent` 的默认值一起收掉了——老工程、
    # 老客户端的 clip.add 都不带这一格，于是随包自检当场 422。默认值是兼容承诺，不是量程的
    # 重复；这一判让它再被删掉时红在这里（而不是在某一支冻结引擎上）。
    assert Clip.model_fields["speed_percent"].default == 100, "clip.add 省略变速时不再默认原速"

    commands, notes = ask(project, source_out_ticks=T6, dest_out_ticks=T2)
    assert notes["resolution"] == "trimmed" and notes["consumed_source_ticks"] == T2, notes
    assert commands[0]["clip"]["duration_ticks"] == T2

    commands, notes = ask(project, source_out_ticks=T2, dest_out_ticks=T4, fit="speed")
    assert notes["resolution"] == "re-timed" and notes["speed_percent"] == 50, notes
    assert notes["consumed_source_ticks"] == T2, notes
    assert commands[0]["clip"]["duration_ticks"] == T4

    for overrides, want in (
        ({"fit": "auto"}, "exact"),
        ({"source_out_ticks": T6, "dest_out_ticks": T2, "fit": "auto"}, "trimmed"),
        ({"source_out_ticks": T2, "dest_out_ticks": T4, "fit": "auto"}, "re-timed"),
    ):
        _, notes = ask(project, **overrides)
        assert notes["resolution"] == want, (overrides, notes)
    print("   four-point: fit=auto picks trim / speed / exact from the four numbers themselves")

    for bad, code in (
        ({"source_out_ticks": T2, "dest_out_ticks": T4, "fit": "trim"}, "INVALID_FOUR_POINT"),
        ({"source_out_ticks": T6, "dest_out_ticks": T4, "fit": "speed"}, "INVALID_FOUR_POINT"),
        ({"source_out_ticks": T2, "dest_out_ticks": 20 * T, "fit": "speed"}, "INVALID_FOUR_POINT"),
        ({"source_in_ticks": 1}, "INVALID_FOUR_POINT"),
        ({"dest_in_ticks": FRAME // 2}, "INVALID_FOUR_POINT"),
        ({"source_out_ticks": T6 + FRAME}, "SOURCE_OUT_OF_BOUNDS"),
        ({"source_in_ticks": T4, "source_out_ticks": T2}, "INVALID_FOUR_POINT"),
        ({"dest_in_ticks": T2, "dest_out_ticks": T2}, "INVALID_FOUR_POINT"),
        ({"track_id": "a"}, "INVALID_FOUR_POINT"),
        ({"asset_id": "tone", "track_id": "v"}, "INVALID_FOUR_POINT"),
        ({"asset_id": "nope"}, "NOT_FOUND"),
        ({"track_id": "nope"}, "NOT_FOUND"),
    ):
        try:
            ask(project, **bad)
        except Exception as failure:
            assert getattr(failure, "code", None) == code, (bad, code, failure)
            continue
        raise AssertionError(f"{bad} must be refused")

    unverified = project.model_copy(deep=True)
    unverified.assets["s"].verified = None
    try:
        ask(unverified)
    except Exception as failure:
        assert getattr(failure, "code", None) == "UNVERIFIED_ASSET", failure
    else:
        raise AssertionError("an unverified asset must be refused")

    commands, _ = ask(project, mode="overwrite", ripple_track_ids=["v"])
    assert commands[0]["op"] == "clip.overwrite" and "ripple_track_ids" not in commands[0], commands
    print(
        "   four-point: exact / trimmed / re-timed all resolve to one placement command, and twelve"
        " impossible point sets are refused with the code that says why"
    )


def pixel(path: Path, at: float) -> tuple[int, int, int]:
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
    return (raw[0], raw[1], raw[2])


def pitch(path: Path, at: float, seconds: float = 0.6) -> float:
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


def duration(path: Path) -> float:
    out = run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)]
    )
    return float(json.loads(out.stdout.decode())["format"]["duration"])


def http_suite(folder: Path) -> None:
    media = MediaService(folder / "fp-db.sqlite3", [folder], folder / "fp-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(folder / "fp-api.sqlite3", FFMPEG, folder / "out", [folder / "out"])
    runtime.ensure_worker()
    token = "fourpoint" + "c" * 53
    app = create_app(folder / "fp-api.sqlite3", token, media=media, jobs=runtime)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        features = client.get("/v1/capabilities").json()["features"]
        assert features["four_point_editing"] is True, features
        clip = source(folder)
        probe = client.post("/v1/media/import", json={"path": str(clip)}).json()
        created = client.post(
            "/v1/projects", json={"request_id": "new", "name": "four-point"}
        ).json()["project"]
        path = f"/v1/projects/{created['id']}"
        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "seed",
                "expected_revision": 0,
                "commands": [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                    {
                        "op": "asset.import",
                        "asset_id": "s",
                        "label": "fp",
                        "probe_id": probe["verified"]["probe_id"],
                        "verified": probe["verified"],
                    },
                ],
            },
        )
        assert seeded.status_code == 200, seeded.text
        revision = seeded.json()["project"]["revision"]

        def four(request_id, body, apply=False, dry=False):
            return client.post(
                path + "/four-point",
                json={
                    "request_id": request_id,
                    "expected_revision": revision,
                    "asset_id": "s",
                    "track_id": "v",
                    "source_in_ticks": T,
                    "source_out_ticks": 3 * T,
                    "dest_in_ticks": 0,
                    "dest_out_ticks": T4,
                    "fit": "speed",
                    "apply": apply,
                    "dry_run": dry,
                    **body,
                },
            )

        planned = four("f-plan", {})
        assert planned.status_code == 200 and planned.json()["committed"] is False, planned.text
        assert planned.json()["four_point"]["speed_percent"] == 50, planned.text
        assert client.get(path).json()["revision"] == revision, "planning must not write"
        assert len(planned.json()["commands"]) == 1

        preview = four("f-dry", {}, apply=True, dry=True)
        assert preview.json()["committed"] is False and not preview.json().get("replayed")
        assert client.get(path).json()["revision"] == revision, "a dry run must not write"

        applied = four("f-apply", {}, apply=True)
        assert applied.status_code == 200, applied.text
        body = applied.json()
        assert body["committed"] is True and body["project"]["revision"] == revision + 1, body
        placed = next(iter(body["project"]["clips"].values()))
        assert (placed["duration_ticks"], placed["source_in_ticks"]) == (T4, T), placed
        assert placed["speed_percent"] == 50, placed
        assert body["four_point"]["consumed_source_ticks"] == T2, body
        replay = four("f-apply", {}, apply=True)
        assert replay.json()["replayed"] is True
        assert client.get(path).json()["revision"] == revision + 1, (
            "a replay must not add a revision"
        )
        stale = client.post(
            path + "/four-point",
            json={
                "request_id": "f-stale",
                "expected_revision": revision,
                "asset_id": "s",
                "track_id": "v",
                "source_in_ticks": T2,
                "source_out_ticks": T4,
                "dest_in_ticks": T4,
                "dest_out_ticks": T6,
                "apply": True,
            },
        )
        assert stale.status_code == 409, stale.text
        print(
            "   four-point: plan / dry-run write nothing, one apply is one revision, a replay adds"
            " none, and a stale revision is refused"
        )

        job = client.post(
            path + "/renders",
            json={
                "request_id": "f-render",
                "expected_revision": revision + 1,
                "preset_id": "h264-720p-web",
                "filename": "fourpoint-slow.mp4",
            },
        ).json()["job"]
        status = {}
        for _ in range(900):
            status = client.get("/v1/jobs/" + job["id"]).json()["job"]
            if status["status"] in {"succeeded", "failed", "cancelled"}:
                break
        assert status["status"] == "succeeded", status
        out = Path(status["output_path"])
        assert abs(duration(out) - 4.0) <= 0.05, duration(out)
        early, late = pixel(out, 0.4), pixel(out, 3.6)
        assert early[0] > 150 and early[1] < 90, ("source 1.25 s is still red", early)
        assert late[1] > 90 and late[0] < 60, ("source 2.75 s is green: 2 s fills 4 s", late)
        first_pitch, second_pitch = pitch(out, 0.4), pitch(out, 3.6)
        assert 400 < first_pitch < 480, first_pitch
        assert 800 < second_pitch < 960, second_pitch
        print(
            "   four-point: the re-timed placement renders 4.000 s, red then green, with"
            f" {round(first_pitch)} Hz then {round(second_pitch)} Hz — pitch held, time stretched"
        )

        trimmed = client.post(
            path + "/four-point",
            json={
                "request_id": "f-trim",
                "expected_revision": revision + 1,
                "asset_id": "s",
                "track_id": "v",
                "source_in_ticks": T2,
                "source_out_ticks": T6,
                "dest_in_ticks": T4,
                "dest_out_ticks": T6,
                "fit": "trim",
                "mode": "overwrite",
                "apply": True,
            },
        ).json()
        assert trimmed["four_point"]["resolution"] == "trimmed", trimmed["four_point"]
        second = [
            clip for clip in trimmed["project"]["clips"].values() if clip["position_ticks"] == T4
        ]
        assert len(second) == 1 and second[0]["duration_ticks"] == T2, second
        assert second[0]["source_in_ticks"] == T2, second[0]
        job2 = client.post(
            path + "/renders",
            json={
                "request_id": "f-render2",
                "expected_revision": trimmed["project"]["revision"],
                "preset_id": "h264-720p-web",
                "filename": "fourpoint-trim.mp4",
            },
        ).json()["job"]
        for _ in range(900):
            status = client.get("/v1/jobs/" + job2["id"]).json()["job"]
            if status["status"] in {"succeeded", "failed", "cancelled"}:
                break
        assert status["status"] == "succeeded", status
        out2 = Path(status["output_path"])
        assert abs(duration(out2) - 6.0) <= 0.05, duration(out2)
        head, tail = pixel(out2, 0.4), pixel(out2, 5.6)
        assert head[0] > 150, ("the first placement is untouched", head)
        # Source 2–6 s into a 2 s window: the trim keeps green (2–4 s) and drops blue (4–6 s),
        # so seeing blue anywhere in the last placement would mean nothing was trimmed.
        assert tail[1] > 90 and tail[2] < 60, ("the trimmed window is green, not blue", tail)
        assert pixel(out2, 5.95)[2] < 60, "the dropped tail must never reach the picture"
        print(
            "   four-point: the trimmed overwrite covers 4–6 s and stays green to the last frame;"
            " the blue tail the trim dropped never appears"
        )

        revision_now = trimmed["project"]["revision"]
        undone = client.post(
            path + "/restore",
            json={
                "request_id": "f-undo",
                "expected_revision": revision_now,
                "target_revision": revision,
            },
        )
        assert undone.status_code == 200, undone.text
        back = undone.json()["project"]
        assert back["revision"] == revision_now + 1, back["revision"]
        assert back["clips"] == {}, "restoring before any placement empties the timeline again"
        assert len(client.get(path + "/history").json()["history"]) >= 4
        print("   four-point: restoring to before the placements is itself a new revision")


def contract_suite() -> None:
    for bad in (
        {"source_in_ticks": -1},
        {"fit": "stretch"},
        {"mode": "paste"},
        {"source_in_ticks": 1.5},
    ):
        body = {
            "request_id": "x",
            "expected_revision": 1,
            "asset_id": "s",
            "track_id": "v",
            "source_in_ticks": 0,
            "source_out_ticks": T2,
            "dest_in_ticks": 0,
            "dest_out_ticks": T2,
        } | bad
        try:
            FourPointRequest(**body)
        except ValidationError:
            continue
        raise AssertionError(f"{bad} must not validate")
    request = FourPointRequest(
        request_id="x",
        expected_revision=1,
        asset_id="s",
        track_id="v",
        source_in_ticks=0,
        source_out_ticks=T2,
        dest_in_ticks=0,
        dest_out_ticks=T2,
    )
    assert request.fit == "trim" and request.mode == "insert" and request.apply is False
    assert ClipColor().grade == []
    print(
        "   four-point: the contract takes four integers and refuses half-written or stretched asks"
    )


def main():
    import tempfile

    with tempfile.TemporaryDirectory(prefix="agentcut-fourpoint-") as scratch:
        folder = Path(scratch)
        contract_suite()
        plan_suite(folder)
        http_suite(folder)
    print(
        "PASS: four points resolve to one legal placement — exact, trimmed or re-timed — with real"
        " pixels and audio proving the window and the speed"
    )


if __name__ == "__main__":
    main()
