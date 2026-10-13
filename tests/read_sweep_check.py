"""A read that fails has to say which id it was given, and an unknown project never looks empty.

The GET side of the API is what a client probes when it is lost: history, a caption track, a frame,
a sample, a proxy, a render plan, a job list. Before 1.76 thirteen of those answered
`{"code":"NOT_FOUND","message":"...","details":{}}` — the caller had just supplied the id, but a
person reading a log or an Agent comparing two attempts could not tell *which* lookup failed. Worse,
`GET /v1/projects/{unknown}/jobs` answered 200 with an empty list, so a mistyped project id
looked exactly like a project that had never rendered, while the history route next to it
answered 404.
"""

import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"


def tone(folder: Path) -> Path:
    target = folder / "tone.mp4"
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
            "sine=frequency=440:duration=1:sample_rate=48000",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x404040:s=320x180:d=1",
            "-c:a",
            "pcm_s16le",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-shortest",
            str(target),
        ],
        capture_output=True,
        check=True,
        timeout=300,
        creationflags=0x08000000,
    )
    return target


# (path, the id a refusal has to name back). `{pid}` / `{probe}` are filled in per run.
ASKS = [
    ("/v1/projects/ghost/history", "project_id"),
    ("/v1/projects/ghost", "project_id"),
    ("/v1/projects/{pid}/captions/ghost", "track_id"),
    ("/v1/projects/ghost/captions/c1", "project_id"),
    ("/v1/projects/ghost/asset-urls", "project_id"),
    ("/v1/projects/ghost/jobs", "project_id"),
    ("/v1/projects/ghost/preview-manifest?revision=1", "project_id"),
    ("/v1/projects/ghost/frame?at_ticks=0", "project_id"),
    ("/v1/projects/ghost/render-plan?preset_id=h264-720p-web&revision=1", "project_id"),
    ("/v1/media/ghost", "probe_id"),
    ("/v1/media/ghost/stream", "probe_id"),
    ("/v1/media/ghost/file/x", "probe_id"),
    ("/v1/projects/{pid}/assets/ghost/proxy?width=320", "asset_id"),
    ("/v1/projects/{pid}/clips/ghost/sample?at_ticks=0", "clip_id"),
    ("/v1/projects/{pid}/preview-manifest?revision=1&sequence_id=ghost", "sequence_id"),
]


def main() -> None:
    with tempfile.TemporaryDirectory() as raw:
        folder = Path(raw)
        source = tone(folder)
        media = MediaService(folder / "db.sqlite3", [folder], folder / "cache", FFMPEG, FFPROBE)
        runtime = JobRuntime(folder / "api.sqlite3", FFMPEG, folder / "out", [folder / "out"])
        runtime.ensure_worker()
        token = "readsweep" + "a" * 52
        app = create_app(folder / "api.sqlite3", token, media=media, jobs=runtime)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            imported = client.post("/v1/media/import", json={"path": str(source)}).json()
            pid = client.post("/v1/projects", json={"request_id": "new", "name": "reads"}).json()[
                "project"
            ]["id"]
            made = client.post(
                f"/v1/projects/{pid}/edits",
                json={
                    "request_id": "seed",
                    "expected_revision": 0,
                    "commands": [
                        {"op": "track.add", "track": {"id": "c1", "kind": "audio", "name": "c1"}},
                        {
                            "op": "asset.import",
                            "asset_id": "a1",
                            "label": "tone",
                            "probe_id": imported["id"],
                            "verified": imported["verified"],
                        },
                        {
                            "op": "clip.add",
                            "clip": {
                                "id": "k",
                                "asset_id": "a1",
                                "track_id": "c1",
                                "position_ticks": 0,
                                "duration_ticks": T,
                            },
                        },
                    ],
                },
            )
            assert made.status_code == 200, made.text

            # The reads that must keep working, so the naming fix cannot become a refusal machine.
            for path in (
                f"/v1/projects/{pid}/history",
                f"/v1/projects/{pid}",
                f"/v1/projects/{pid}/asset-urls",
                f"/v1/projects/{pid}/jobs",
                f"/v1/projects/{pid}/captions/c1",
                f"/v1/media/{imported['id']}",
                f"/v1/projects/{pid}/preview-manifest?revision=1",
            ):
                answer = client.get(path)
                assert answer.status_code == 200, (
                    f"{path} -> {answer.status_code} {answer.text[:120]}"
                )
            print("   seven honest reads still answer 200")

            problems = []
            for path, key in ASKS:
                answer = client.get(path.replace("{pid}", pid))
                if answer.status_code >= 500:
                    problems.append(f"{path} 5xx: {answer.text[:160]}")
                    continue
                if answer.status_code < 400:
                    problems.append(
                        f"{path} answered {answer.status_code}; an unknown id must not look like "
                        "an empty result"
                    )
                    continue
                error = answer.json()["error"]
                code = str(error.get("code") or "")
                details = error.get("details") or {}
                if not code or not str(error.get("message") or "").strip():
                    problems.append(f"{path}: nameless refusal {answer.text[:120]}")
                    continue
                if key not in details:
                    problems.append(f"{path} {code} names no {key}: {details}")
                    continue
                if details[key] not in {"ghost", "c1", "x", "a1"}:
                    problems.append(f"{path} names the wrong {key}: {details}")
            named = len(ASKS) - len(problems)
            for line in problems:
                print("   PROBLEM", line)
            assert not problems, problems
            print(
                f"   {named} failed reads across the GET surface each name the id they were given "
                "(project, probe, clip, track, asset or composition)"
            )

            # A source file that moved is the other read failure a person actually meets.
            source.unlink()
            gone = client.get(f"/v1/media/{imported['id']}")
            assert gone.status_code == 410, gone.text
            error = gone.json()["error"]
            assert error["code"] == "MEDIA_MISSING", error
            assert error["details"].get("probe_id") == imported["id"], error
            print("   a moved source answers 410 and names the probe it cannot re-hash")
    print(
        "PASS: every read refusal says which id it means, an unknown project never answers an "
        "empty 200, and honest reads are untouched"
    )


if __name__ == "__main__":
    main()
