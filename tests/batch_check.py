"""Batch delivery: one call queues several framings, and a batch that cannot be completed queues
nothing at all. Verified against real exports, because 'queued' is not 'delivered'."""

import json
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import RenderBatch, RenderBatchItem
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SECONDS = 2.0
SRC = (
    "color=c=0x404040:s=320x180:r=30:d=2,drawbox=x=130:y=60:w=60:h=60:color=white:t=fill,"
    "drawbox=x=0:y=0:w=3:h=180:color=white:t=fill"
)


def run(args, timeout=420):
    return subprocess.run(
        args, capture_output=True, check=True, timeout=timeout, creationflags=0x08000000
    )


def source(folder: Path) -> Path:
    target = folder / "wide.mp4"
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
            SRC,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ]
    )
    return target


def geometry(path: Path) -> tuple[int, int]:
    out = run(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(path),
        ]
    ).stdout.decode()
    stream = json.loads(out)["streams"][0]
    return int(stream["width"]), int(stream["height"])


def contract_suite() -> None:
    ok = RenderBatch.model_validate(
        {
            "request_id": "b1",
            "expected_revision": 1,
            "items": [
                {"preset_id": "h264-1080x1920-vertical", "filename": "a.mp4"},
                {"preset_id": "h264-1080-square", "filename": "b.mp4"},
            ],
        }
    )
    assert len(ok.items) == 2 and ok.items[0].fit == "contain", ok
    too_many = [{"preset_id": "p", "filename": f"n{index}.mp4"} for index in range(5)]
    try:
        RenderBatch.model_validate({"request_id": "b", "expected_revision": 1, "items": too_many})
    except ValidationError as error:
        assert "max_length" in str(error) or "at most 4" in str(error), str(error)
    else:
        raise AssertionError("a batch of five deliverables must be refused")
    same = [{"preset_id": "p", "filename": "same.mp4"}, {"preset_id": "p", "filename": "same.mp4"}]
    try:
        RenderBatch.model_validate({"request_id": "b", "expected_revision": 1, "items": same})
    except ValidationError as error:
        assert "own file name" in str(error), str(error)
    else:
        raise AssertionError("two deliverables cannot share one file name")
    for changes, expect in (
        ({"filename": "sub/dir.mp4"}, "bare file name"),
        ({"filename": "no-extension"}, ".mp4"),
        # The required suffix is the preset's container, so an mp4 name on a WebM preset is its own
        # rejection with its own reason.
        ({"preset_id": "vp9-1080p-web", "filename": "a.mp4"}, ".webm"),
        ({"fit": "smart"}, "fit"),
    ):
        item = {"preset_id": "h264-1080p", "filename": "a.mp4"} | changes
        try:
            RenderBatchItem.model_validate(item)
        except ValidationError as error:
            assert expect in str(error), (changes, str(error))
        else:
            raise AssertionError(f"{changes} must be refused")
    print("   contract: four items max, unique bare names, only the three known framings")


def http_suite(folder: Path) -> None:
    media = MediaService(
        folder / "batch-db.sqlite3", [folder], folder / "batch-cache", FFMPEG, FFPROBE
    )
    runtime = JobRuntime(
        folder / "batch-api.sqlite3", FFMPEG, folder / "deliverables", [folder / "deliverables"]
    )
    runtime.ensure_worker()
    token = "batchcheck" + "e" * 54
    app = create_app(folder / "batch-api.sqlite3", token, media=media, jobs=runtime)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        caps = client.get("/v1/capabilities").json()
        assert caps["features"]["batch_delivery"] is True, caps["features"]
        clip = source(folder)
        probe = client.post("/v1/media/import", json={"path": str(clip)}).json()
        created = client.post("/v1/projects", json={"request_id": "new", "name": "batch"}).json()[
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
                        "label": "a",
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

        items = [
            {"preset_id": "h264-source-quality", "filename": "横版.mp4", "fit": "contain"},
            {"preset_id": "h264-1080x1920-vertical", "filename": "竖版.mp4", "fit": "cover"},
            {"preset_id": "h264-1080-square", "filename": "方形.mp4", "fit": "contain"},
        ]
        batch = {"request_id": "deliver", "expected_revision": 1, "items": items}

        preview = client.post(path + "/renders/batch", json={**batch, "dry_run": True})
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["committed"] is False and len(body["jobs"]) == 3, body
        assert [job["fit"] for job in body["jobs"]] == ["contain", "cover", "contain"], body
        assert client.get(f"/v1/projects/{created['id']}/jobs").json()["jobs"] == []
        assert not (folder / "deliverables").exists() or not list(
            (folder / "deliverables").glob("*.mp4")
        ), "a dry batch must not put files on disk"
        print("   dry batch: three jobs described, nothing queued, nothing written")

        sent = client.post(path + "/renders/batch", json=batch)
        assert sent.status_code == 200, sent.text
        jobs = sent.json()["jobs"]
        assert len(jobs) == 3 and all(job["status"] in {"queued", "running"} for job in jobs), jobs
        done = {}
        for job in jobs:
            status = {}
            for _ in range(600):
                status = client.get("/v1/jobs/" + job["id"]).json()
                if status["job"]["status"] in {"succeeded", "failed", "cancelled"}:
                    break
                import time as clock

                clock.sleep(0.5)
            assert status["job"]["status"] == "succeeded", (job, status)
            done[job["filename"]] = Path(status["job"]["output_path"])
        sizes = {name: geometry(file) for name, file in done.items()}
        # The project canvas is the default 1920x1080, and `h264-source-quality`
        # follows it; the other two presets carry their own size.
        assert sizes["横版.mp4"] == (1920, 1080), sizes
        assert sizes["竖版.mp4"] == (1080, 1920), sizes
        assert sizes["方形.mp4"] == (1080, 1080), sizes
        print("   delivered:", ", ".join(f"{name} {w}x{h}" for name, (w, h) in sizes.items()))

        replay = client.post(path + "/renders/batch", json=batch)
        assert replay.status_code == 200, replay.text
        again = replay.json()["jobs"]
        assert [job["id"] for job in again] == [job["id"] for job in jobs], (again, jobs)
        listed = client.get(f"/v1/projects/{created['id']}/jobs").json()["jobs"]
        assert len(listed) == 3, [job["filename"] for job in listed]
        print("   replaying the batch returns the same three jobs and queues nothing new")

        changed = {
            **batch,
            "items": [items[0], {**items[1], "fit": "stretch"}, items[2]],
        }
        clash = client.post(path + "/renders/batch", json=changed)
        assert clash.status_code == 409, clash.text
        assert "request_id" in json.dumps(clash.json()).lower(), clash.text

        stale = client.post(
            path + "/renders/batch", json={**batch, "request_id": "stale", "expected_revision": 0}
        )
        assert stale.status_code == 409, stale.text

        broken = {
            "request_id": "broken",
            "expected_revision": 1,
            "items": [items[0], {"preset_id": "h264-nonexistent", "filename": "坏.mp4"}],
        }
        refused = client.post(path + "/renders/batch", json=broken)
        assert refused.status_code == 422, refused.text
        after = client.get(f"/v1/projects/{created['id']}/jobs").json()["jobs"]
        assert len(after) == 3, [job["filename"] for job in after]
        assert not (folder / "deliverables" / "坏.mp4").exists()
        print("   a bad preset in the second item fails the whole batch: no partial queue")

        duplicate = {
            "request_id": "dupe",
            "expected_revision": 1,
            "items": [items[0], dict(items[0])],
        }
        twice = client.post(path + "/renders/batch", json=duplicate)
        assert twice.status_code == 422, twice.text


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-batch-") as scratch:
        folder = Path(scratch)
        contract_suite()
        http_suite(folder)
    print(
        "PASS: one call delivers three framings, a dry batch writes nothing, a replay returns the "
        "same jobs, and one bad item fails the whole batch instead of queueing half a delivery"
    )


if __name__ == "__main__":
    main()
