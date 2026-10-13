"""Derived-cache quota: the inventory has to match what is actually on disk, a dry run has to delete
nothing, a real prune has to stop at the budget in least-recently-used order, and a pruned entry has
to come back when something asks for it again."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import APP_VERSION
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService, cache_limit_bytes

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"


def run(args, timeout=420):
    done = subprocess.run(
        args, capture_output=True, check=True, timeout=timeout, creationflags=0x08000000
    )
    return done.stdout


def tree_bytes(folder: Path) -> int:
    return sum(item.stat().st_size for item in folder.rglob("*") if item.is_file())


def make_media(folder: Path) -> list[Path]:
    """Two clips and one still: each produces filmstrip tiles, and the clips also a waveform."""
    made = []
    for name, colour, size in (("wide", "red", "s=320x180"), ("tall", "green", "s=240x320")):
        target = folder / f"{name}.mp4"
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
                f"color=c={colour}:{size}:r=30:d=2",
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
        made.append(target)
    still = folder / "still.png"
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
            "color=c=blue:s=320x180:r=30:d=1",
            "-frames:v",
            "1",
            str(still),
        ]
    )
    made.append(still)
    return made


def age(path: Path, seconds: int) -> None:
    """Make a derived entry look stale, so the eviction order below is a fact of this test."""
    info = path.stat()
    os.utime(path, (info.st_atime - seconds, info.st_mtime - seconds))


def find_url(payload: dict, needle: str) -> str:
    stack = [payload]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
        elif isinstance(current, str) and needle in current:
            return current
    raise AssertionError(f"no url containing {needle!r}: {json.dumps(payload)[:300]}")


def main() -> None:
    folder = Path(tempfile.mkdtemp(prefix="agentcut-cache-"))
    # Sources and cache in separate trees: the prune guard refuses to touch anything inside a
    # registered media root, so sharing one folder would hide the behaviour under test.
    sources = folder / "sources"
    sources.mkdir()
    cache = folder / "cache"
    media = make_media(sources)
    engine = MediaService(folder / "cc-db.sqlite3", [sources], cache, FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "cc-api.sqlite3", FFMPEG, folder / "deliverables", [folder / "deliverables"]
    )
    runtime.ensure_worker()
    token = "cachecheck" + "f" * 53
    app = create_app(folder / "cc-api.sqlite3", token, media=engine, jobs=runtime)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        caps = client.get("/v1/capabilities").json()
        assert caps["features"]["cache_pruning"] is True, caps["features"]
        assert caps["app_version"] == APP_VERSION, caps["app_version"]

        probes = [
            client.post("/v1/media/import", json={"path": str(item)}).json() for item in media
        ]
        assert all(probe["verified"]["content_sha256"] for probe in probes)
        on_disk = tree_bytes(cache)
        assert on_disk > 0, "importing should have produced derived files"

        listed = client.get("/v1/media/cache").json()
        assert listed["used_bytes"] == on_disk, (listed["used_bytes"], on_disk)
        assert sum(entry["size_bytes"] for entry in listed["entries"]) == on_disk
        assert len(listed["entries"]) == 3, listed["entries"]
        assert listed["limit_bytes"] == cache_limit_bytes(), listed["limit_bytes"]
        assert all(entry["files"] > 0 for entry in listed["entries"])
        print(
            f"   cache: {len(listed['entries'])} derived entries and {on_disk} bytes on disk; the"
            f" inventory reports exactly that against a {listed['limit_bytes']}-byte budget"
        )

        # Age one entry so "least recently used" is a fact of this test, not an assumption.
        oldest = min(listed["entries"], key=lambda entry: entry["used_at"])
        target = cache / oldest["digest"][:2] / oldest["digest"]
        age(target, 3600)
        order = [entry["digest"] for entry in client.get("/v1/media/cache").json()["entries"]]
        assert order[-1] == oldest["digest"], order

        budget = on_disk - oldest["size_bytes"] + 1
        preview = client.post(
            "/v1/media/cache/prune", json={"max_bytes": budget, "dry_run": True}
        ).json()
        assert preview["dry_run"] is True and preview["removed"], preview
        assert [entry["digest"] for entry in preview["removed"]] == [oldest["digest"]], preview
        assert preview["used_bytes_before"] == on_disk, preview
        assert preview["used_bytes_after"] <= budget, preview
        assert tree_bytes(cache) == on_disk, "a dry run deleted something"
        assert all((cache / digest[:2] / digest).is_dir() for digest in order), (
            "dry run removed a dir"
        )
        print(
            f"   cache: a dry run planned to free {preview['freed_bytes']} bytes and left all"
            f" {tree_bytes(cache)} bytes in place"
        )

        pruned = client.post("/v1/media/cache/prune", json={"max_bytes": budget}).json()
        after = tree_bytes(cache)
        assert pruned["used_bytes_after"] == after == on_disk - pruned["freed_bytes"], (
            after,
            pruned,
        )
        assert after <= budget, (after, budget)
        assert [entry["digest"] for entry in pruned["removed"]] == [oldest["digest"]], pruned
        assert not target.exists(), "the pruned directory is still on disk"
        kept = client.get("/v1/media/cache").json()["entries"]
        assert {entry["digest"] for entry in kept} == set(order) - {oldest["digest"]}, kept
        print(
            f"   cache: pruning to {budget} bytes dropped the least recently used entry"
            f" ({pruned['freed_bytes']} bytes); {len(kept)} entries remain"
        )

        # The promise that makes this safe: a deleted entry comes back when something asks for it.
        victim = next(
            probe for probe in probes if probe["verified"]["content_sha256"] == oldest["digest"]
        )
        tile = find_url(victim["urls"], victim["thumbnails"][0])
        revived = client.get(tile, headers={"Authorization": ""})
        assert revived.status_code == 200, (revived.status_code, revived.text[:200])
        assert (target / victim["thumbnails"][0]).is_file(), "the tile was not rebuilt on disk"
        rebuilt = tree_bytes(cache)
        assert rebuilt > after, "the rebuilt entry should occupy disk again"
        print(
            f"   cache: asking for the pruned tile served {len(revived.content)} bytes and put"
            f" {rebuilt - after} back on disk"
        )

        present = [entry["digest"] for entry in client.get("/v1/media/cache").json()["entries"]]
        assert len(present) == 3, present  # the rebuild brought the third entry back
        protected = client.post(
            "/v1/media/cache/prune", json={"max_bytes": 0, "keep": present}
        ).json()
        assert protected["removed"] == [] and protected["used_bytes_after"] == tree_bytes(cache), (
            protected
        )
        print("   cache: `keep` protects the listed hashes, so even a zero budget deletes nothing")

        everything = client.post("/v1/media/cache/prune", json={"max_bytes": 0}).json()
        assert everything["used_bytes_after"] == 0, everything
        assert tree_bytes(cache) == 0, [str(path) for path in cache.rglob("*")]
        print(
            f"   cache: a zero budget clears the derived cache ({everything['freed_bytes']} bytes)"
        )

    nested = folder / "nested"
    nested.mkdir()
    shelter = MediaService(
        folder / "cc-nested.sqlite3", [nested], nested / "cache", FFMPEG, FFPROBE
    )
    shelter.build_cache(shelter.summarize(make_media(nested)[0], "video"))
    before = tree_bytes(nested)
    assert before > 0, "the nested fixture produced nothing to protect"
    plan = shelter.prune_cache(0)
    assert plan["removed"] == [] and tree_bytes(nested) == before, plan
    print("   cache: with the cache inside a registered media root, prune deletes nothing")
    # A budget is only a budget if it holds without anyone remembering to ask for it. Sources stay
    # outside the cache here: the media-root guard would (correctly) refuse to evict anything.
    tight = folder / "tight"
    tight_sources = tight / "sources"
    tight_sources.mkdir(parents=True)
    os.environ["AGENTCUT_CACHE_BYTES"] = "60000"
    try:
        bounded = MediaService(
            folder / "cc-tight.sqlite3", [tight_sources], tight / "cache", FFMPEG, FFPROBE
        )
        for item in make_media(tight_sources):
            bounded.build_cache(
                bounded.summarize(item, "video" if item.suffix == ".mp4" else "image")
            )
        inside = tree_bytes(tight / "cache")
        survivors = {entry["digest"] for entry in bounded.cache_inventory()["entries"]}
        assert inside <= 60000, f"the cache grew past its own budget: {inside} bytes"
        assert len(survivors) == 1, survivors
        print(
            f"   cache: building three entries past a 60,000-byte budget bounded it at {inside}"
            f" bytes with {len(survivors)} entry left, on its own"
        )
    finally:
        del os.environ["AGENTCUT_CACHE_BYTES"]

    shutil.rmtree(folder, ignore_errors=True)
    print("PASS: the derived cache is inventoried honestly, bounded in LRU order, and rebuilds")


if __name__ == "__main__":
    main()
