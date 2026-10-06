"""Safe-area guides: which reference line the monitor draws is project state, the inset numbers
come from the engine, and turning them on has to change nothing about the delivered file."""

import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentcut.contracts import SAFE_AREA_INSETS, SequenceSettings, render_presets
from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService
from agentcut.projects import ProjectStore

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"


def run(args, timeout=420):
    done = subprocess.run(
        args, capture_output=True, check=True, timeout=timeout, creationflags=0x08000000
    )
    return done.stdout


def source(folder: Path) -> Path:
    target = folder / "guides.mp4"
    run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-y",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=320x180:r=30:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(target),
        ]
    )
    return target


def pixel(path, at):
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
    )
    return (raw[0], raw[1], raw[2])


def contract_suite() -> None:
    assert SequenceSettings().safe_area == "off", "a plain sequence shows no guide"
    for mode in ("off", "action", "title"):
        assert SequenceSettings(safe_area=mode).safe_area == mode
    for bad in ("titles", "ACTION", 3.5, ""):
        try:
            SequenceSettings(safe_area=bad)
        except ValidationError:
            continue
        raise AssertionError(f"settings accepted guide {bad!r}")
    # An older document (no key at all) still reads, and reads as "off".
    assert SequenceSettings.model_validate({"width": 640, "height": 360}).safe_area == "off"
    assert set(SAFE_AREA_INSETS) == {"action", "title"}
    assert 0 < SAFE_AREA_INSETS["action"] < SAFE_AREA_INSETS["title"] < 0.2
    print("   guides: a three-way choice, old documents read as off, the insets are ordered")


def http_suite(folder: Path) -> None:
    media = MediaService(folder / "sa-db.sqlite3", [folder], folder / "sa-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "sa-api.sqlite3", FFMPEG, folder / "deliverables", [folder / "deliverables"]
    )
    runtime.ensure_worker()
    token = "safearea" + "e" * 56
    app = create_app(folder / "sa-api.sqlite3", token, media=media, jobs=runtime)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        caps = client.get("/v1/capabilities").json()
        assert caps["features"]["safe_area_guides"] is True, caps["features"]
        assert caps["safe_area_insets"] == SAFE_AREA_INSETS, caps["safe_area_insets"]
        assert "proxy-540p-fast" in {preset["id"] for preset in render_presets()}
        print(
            "   guides: capabilities carries the flag and the engine's own insets "
            f"{caps['safe_area_insets']}"
        )

        clip = source(folder)
        probe = client.post("/v1/media/import", json={"path": str(clip)}).json()
        created = client.post("/v1/projects", json={"request_id": "new", "name": "guides"}).json()[
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
                    {
                        "op": "asset.import",
                        "asset_id": "a",
                        "label": "g",
                        "probe_id": probe["verified"]["probe_id"],
                        "verified": probe["verified"],
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "c",
                            "asset_id": "a",
                            "track_id": "v",
                            "position_ticks": 0,
                            "duration_ticks": 2 * T,
                        },
                    },
                ],
            },
        )
        revision = seeded.json()["project"]["revision"]
        settings = seeded.json()["project"]["settings"]
        assert settings["safe_area"] == "off", settings

        def write(request_id, mode, base=None, **extra):
            return client.post(
                path,
                json={
                    "request_id": request_id,
                    "expected_revision": base if base is not None else revision,
                    "settings": {**settings, "safe_area": mode},
                    **extra,
                },
            )

        moved = write("g-title", "title")
        assert moved.status_code == 200, moved.text
        assert moved.json()["project"]["settings"]["safe_area"] == "title", moved.text
        assert client.get(path).json()["settings"]["safe_area"] == "title"
        assert moved.json()["project"]["revision"] == revision + 1, moved.text
        replay = write("g-title", "title")
        assert replay.json().get("replayed") is True, replay.text
        assert client.get(path).json()["revision"] == revision + 1, "a replay added a revision"
        refused = write("g-bad", "titles")
        assert refused.status_code == 422, refused.text
        assert client.get(path).json()["settings"]["safe_area"] == "title", (
            "a refusal changed the guide"
        )
        assert client.get(path).json()["revision"] == revision + 1, "a refusal burned a revision"
        stale = write("g-stale", "action", base=revision)
        assert stale.status_code == 409, stale.text
        print(
            "   guides: one write is one revision, a replay returns its receipt, a bad name"
            "is refused without touching the project"
        )

        reopened = ProjectStore(folder / "sa-api.sqlite3").get(created["id"])
        assert reopened.settings.safe_area == "title", reopened.settings
        assert reopened.revision == revision + 1

        # The whole point of a monitor guide: it must not leak into the delivered file.
        plain = client.post(
            path + "/renders",
            json={
                "request_id": "g-render-title",
                "expected_revision": revision + 1,
                "preset_id": "proxy-540p-fast",
                "filename": "with-guide.mp4",
            },
        ).json()["job"]
        back = write("g-off", "off", base=revision + 1)
        assert back.json()["project"]["revision"] == revision + 2, back.text
        other = client.post(
            path + "/renders",
            json={
                "request_id": "g-render-off",
                "expected_revision": revision + 2,
                "preset_id": "proxy-540p-fast",
                "filename": "without-guide.mp4",
            },
        ).json()["job"]
        files = {}
        for job in (plain, other):
            status = {}
            for _ in range(600):
                status = client.get("/v1/jobs/" + job["id"]).json()["job"]
                if status["status"] in {"succeeded", "failed", "cancelled"}:
                    break
                import time

                time.sleep(0.5)
            assert status["status"] == "succeeded", status
            files[job["filename"]] = Path(status["output_path"])
        durations = {
            name: float(
                subprocess.run(
                    [
                        str(FFPROBE),
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "csv=p=0",
                        str(target),
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
            )
            for name, target in files.items()
        }
        samples = {
            name: [pixel(target, at) for at in (0.2, 1.0, 1.8)] for name, target in files.items()
        }
        assert abs(durations["with-guide.mp4"] - 2.0) <= 0.05, durations
        assert samples["with-guide.mp4"] == samples["without-guide.mp4"], samples
        assert all(rgb[0] > 120 and rgb[1] < 60 for rgb in samples["with-guide.mp4"]), samples
        print(
            "   guides: exporting the same timeline with the guide on and off gives identical"
            f" frames {samples['with-guide.mp4'][1]} at {durations['with-guide.mp4']:.3f} s"
        )

        undone = client.post(
            path + "/restore",
            json={
                "request_id": "undo",
                "expected_revision": revision + 2,
                "target_revision": revision + 1,
            },
        )
        assert undone.json()["project"]["settings"]["safe_area"] == "title", undone.text
        assert undone.json()["project"]["revision"] == revision + 3, undone.text
        print("   guides: restoring an older snapshot restores the guide as it was")


def main() -> None:
    folder = Path(tempfile.mkdtemp(prefix="agentcut-guides-"))
    contract_suite()
    http_suite(folder)
    print("PASS: safe-area guides are project state, engine-numbered, invisible to the render")


if __name__ == "__main__":
    main()
