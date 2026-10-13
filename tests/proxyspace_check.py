"""Proxy cache accounting: a byte limit, least-recently-used eviction, and an explicit sweep.

Proxies are derived playback copies, so dropping one must never hurt the source, the thumbnails or
the waveform — and eviction has to follow actual playback, not the order things were built.
"""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app, signature
from agentcut.media import MediaService

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"


def run(args: list[str], timeout: int = 300) -> bytes:
    result = subprocess.run(
        [str(FFMPEG), "-v", "error", *args],
        capture_output=True,
        timeout=timeout,
        creationflags=0x08000000,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")[-600:]
    return result.stdout


def make_source(path: Path, seconds: int = 3) -> None:
    run(
        [
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=s=1920x1080:r=30:d={seconds}",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            str(path),
        ]
    )


def service(folder: Path, name: str) -> MediaService:
    (folder / "media").mkdir(exist_ok=True)
    return MediaService(
        folder / f"{name}.sqlite3",
        [folder / "media"],
        folder / f"{name}-cache",
        FFMPEG,
        FFPROBE,
    )


def quota_suite(folder: Path) -> None:
    """The engine's own limit must be enforced while building, without touching anything else."""
    media = service(folder, "quota")
    a = folder / "media" / "a.mp4"
    b = folder / "media" / "b.mp4"
    make_source(a, 3)
    make_source(b, 2)
    verified_a = media.summarize(a, "video")
    verified_b = media.summarize(b, "video")
    media.build_cache(verified_a)
    kept = media.build_proxy(verified_a, 640)
    assert kept["state"] == "ready" and len(media.scan_proxies()) == 1
    limit = kept["size_bytes"] + 1000

    os.environ["AGENTCUT_PROXY_CACHE_BYTES"] = str(limit)
    try:
        time.sleep(1.05)
        second = media.build_proxy(verified_b, 640)
        assert second["state"] == "ready" and second["size_bytes"] <= limit, second
        inventory = media.proxy_inventory()
        assert inventory["used_bytes"] <= limit, inventory
        assert inventory["limit_bytes"] == limit, inventory
        assert [entry["source_sha256"] for entry in inventory["proxies"]] == [
            verified_b.content_sha256
        ], inventory
        assert Path(kept["path"]).is_file() is False, "the older proxy must be evicted"
        assert media.proxy_state(verified_a, 640)["state"] == "absent"
        # Sources and the cheap cache files are never eviction candidates.
        assert a.is_file() and b.is_file()
        cache_dir = media.cache_dir_for(verified_a.content_sha256)
        assert (cache_dir / "cache.json").is_file()
        assert (cache_dir / "tile-00.jpg").is_file()
    finally:
        os.environ.pop("AGENTCUT_PROXY_CACHE_BYTES", None)


def sweep_suite(folder: Path) -> None:
    media = service(folder, "sweep")
    a = folder / "media" / "a.mp4"
    b = folder / "media" / "b.mp4"
    make_source(a, 3)
    make_source(b, 2)
    first = media.summarize(a, "video")
    second = media.summarize(b, "video")
    one = media.build_proxy(first, 960)
    two = media.build_proxy(second, 640)
    total = one["size_bytes"] + two["size_bytes"]

    # An orphan sidecar (no video beside it) is dropped by the scan, not counted.
    orphan = media.cache_dir / "orphan" / "proxy-1234.json"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text(json.dumps({"width": 1234}), encoding="utf-8")
    inventory = media.proxy_inventory()
    assert not orphan.exists(), "an orphan sidecar must be cleaned up"
    assert inventory["used_bytes"] == total, (inventory, total)

    # Least recently *used*, not least recently built: serving a proxy moves it to the front, so
    # the budget keeps the one the editor is actually looking at.
    media.touch_proxy(first, 960)
    result = media.prune_proxies(one["size_bytes"])
    assert result["freed_bytes"] == two["size_bytes"], result
    assert result["removed"] == [
        {
            "source_sha256": second.content_sha256,
            "width": 640,
            "size_bytes": two["size_bytes"],
        }
    ], result
    assert media.proxy_state(first, 960)["state"] == "ready", "the just-served proxy must survive"
    assert media.proxy_state(second, 640)["state"] == "absent"

    cleared = media.prune_proxies(0)
    assert cleared["used_bytes"] == 0 and cleared["freed_bytes"] == one["size_bytes"], cleared
    assert media.proxy_inventory()["proxies"] == []
    assert a.is_file() and b.is_file()


def http_suite(folder: Path) -> None:
    media = service(folder, "http")
    clip = folder / "media" / "clip.mp4"
    make_source(clip, 2)
    token = "proxyspace" + "d" * 48
    app = create_app(
        folder / "http.sqlite3", token, media=media, app_info={"base_url": "http://127.0.0.1"}
    )
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        probe = client.post("/v1/media/import", json={"path": str(clip)}).json()
        project = client.post("/v1/projects", json={"request_id": "new", "name": "quota"}).json()[
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
                        "asset_id": "hd",
                        "label": "clip",
                        "probe_id": probe["id"],
                        "verified": probe["verified"],
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "c",
                            "asset_id": "hd",
                            "track_id": "v",
                            "position_ticks": 0,
                            "duration_ticks": 2 * T,
                        },
                    },
                ],
            },
        )
        assert seeded.status_code == 200, seeded.text
        revision = seeded.json()["project"]["revision"]

        assert client.get("/v1/media/proxies").json()["used_bytes"] == 0
        built = client.post(path + "/assets/hd/proxy", json={"width": 640}).json()
        assert built["state"] == "ready", built
        listed = client.get("/v1/media/proxies").json()
        assert listed["used_bytes"] == built["size_bytes"], listed
        assert listed["limit_bytes"] == 4 << 30, listed
        entry = listed["proxies"][0]
        assert set(entry) == {"source_sha256", "width", "size_bytes", "used_at"}, entry
        assert entry["width"] == 640

        served = client.get(built["stream"].split("http://127.0.0.1")[1])
        assert served.status_code == 200
        touched = client.get("/v1/media/proxies").json()["proxies"][0]["used_at"]
        assert touched >= entry["used_at"], (entry, touched)

        assert client.post("/v1/media/proxies/prune", json={"max_bytes": -1}).status_code == 422
        pruned = client.post("/v1/media/proxies/prune", json={"max_bytes": 0})
        assert pruned.status_code == 200, pruned.text
        assert pruned.json()["freed_bytes"] == built["size_bytes"], pruned.json()
        assert client.get("/v1/media/proxies").json()["proxies"] == []
        assert client.get(built["stream"].split("http://127.0.0.1")[1]).status_code == 409
        assert (
            client.get(
                "/v1/assets/hd/proxy/stream?project_id="
                + project["id"]
                + "&width=640&sig="
                + signature(token, f"proxy:{project['id']}:hd:640")
            ).status_code
            == 409
        )
        # Sweeping the cache is not an edit: the project is untouched and still writable.
        assert client.get(path).json()["revision"] == revision
        rebuilt = client.post(path + "/assets/hd/proxy", json={"width": 640}).json()
        assert rebuilt["state"] == "ready"
        assert client.get(path).json()["revision"] == revision


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-proxyspace-") as scratch:
        folder = Path(scratch)
        quota_suite(folder)
        sweep_suite(folder)
        http_suite(folder)
    print(
        "PASS: the proxy byte limit is enforced while building, eviction follows real playback",
        "use, sweeping frees only derived copies, and sources, thumbnails and projects stay intact",
    )


if __name__ == "__main__":
    main()
