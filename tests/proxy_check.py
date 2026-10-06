"""Playback proxies: the engine transcodes verified media into a smaller copy used for preview only.

A proxy must never change the project, the render plan or the export, so this check builds one and
then compares the compiled plan byte for byte. It also measures that the proxy really is the same
picture at the same time, only smaller — resolution, duration, frame rate, audio and mean levels.
"""

import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import Project
from agentcut.http_api import create_app, signature
from agentcut.media import MediaService
from agentcut.render import compile_render_plan

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
FRAME = T // 30


def run(args: list[str], timeout: int = 300) -> bytes:
    result = subprocess.run(
        [str(FFMPEG), "-v", "error", *args],
        capture_output=True,
        timeout=timeout,
        creationflags=0x08000000,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")[-600:]
    return result.stdout


def make_source(path: Path, width: int, height: int, seconds: int = 4, audio: bool = True) -> None:
    args = [
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=s={width}x{height}:r=30:d={seconds}",
    ]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac"]
    args += ["-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast", str(path)]
    run(args)


def service(folder: Path, name: str) -> MediaService:
    (folder / "media").mkdir(exist_ok=True)
    return MediaService(
        folder / f"{name}.sqlite3",
        [folder / "media"],
        folder / f"{name}-cache",
        FFMPEG,
        FFPROBE,
    )


def build_suite(folder: Path) -> None:
    media = service(folder, "build")
    big = folder / "media" / "big.mp4"
    make_source(big, 1920, 1080)
    verified = media.summarize(big, "video")
    assert verified.width == 1920 and verified.height == 1080, verified
    assert verified.has_audio is True

    assert media.proxy_state(verified, 960)["state"] == "absent"
    built = media.build_proxy(verified, 960)
    assert built["state"] == "ready", built
    assert (built["display_width"], built["display_height"]) == (960, 540), built
    assert abs(built["duration_ticks"] - verified.duration_ticks) <= 2 * FRAME, built
    assert built["frame_rate"] == {"numerator": 30, "denominator": 1}, built
    assert built["has_audio"] is True and built["video_codec"] == "h264", built
    assert built["source_sha256"] == verified.content_sha256
    proxy = Path(built["path"])
    ratio = big.stat().st_size / proxy.stat().st_size
    assert ratio > 2, f"the proxy should be smaller: {ratio:.2f}x"
    print(
        f"   proxy {proxy.stat().st_size} bytes vs source {big.stat().st_size} "
        f"({ratio:.1f}x smaller), {built['display_width']}x{built['display_height']}"
    )

    # A second request must reuse the cache instead of transcoding again.
    stamp = proxy.stat().st_mtime_ns
    assert media.build_proxy(verified, 960)["state"] == "ready"
    assert proxy.stat().st_mtime_ns == stamp, "rebuilding a ready proxy must be a cache hit"

    other = media.build_proxy(verified, 480)
    assert other["display_width"] == 480 and other["path"] != built["path"], other

    small = folder / "media" / "small.mp4"
    make_source(small, 640, 360, 1)
    assert media.proxy_state(media.summarize(small, "video"), 960)["state"] == "not_needed"
    tone = folder / "media" / "tone.m4a"
    run(["-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "aac", str(tone)])
    assert media.proxy_state(media.summarize(tone, "audio"), 960)["state"] == "not_video"

    # Replacing the file under the same name is a different content hash: no stale proxy is served.
    make_source(big, 1280, 720, 2)
    moved = media.summarize(big, "video")
    assert moved.content_sha256 != verified.content_sha256
    assert media.proxy_state(moved, 960)["state"] == "absent"


def http_suite(folder: Path) -> None:
    media = service(folder, "api")
    clip_path = folder / "media" / "clip.mp4"
    make_source(clip_path, 1920, 1080)
    token = "proxycase" + "b" * 50
    app = create_app(
        folder / "api-http.sqlite3", token, media=media, app_info={"base_url": "http://127.0.0.1"}
    )
    with TestClient(
        app,
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        assert client.get("/v1/capabilities").json()["features"]["proxy_playback"] is True
        probe = client.post("/v1/media/import", json={"path": str(clip_path)}).json()
        assert "verified" in probe, probe
        project = client.post("/v1/projects", json={"request_id": "new", "name": "proxy"}).json()[
            "project"
        ]
        path = f"/v1/projects/{project['id']}"
        seed = [
            {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
            {
                "op": "asset.import",
                "asset_id": "a",
                "label": "clip",
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
                    "duration_ticks": 4 * T,
                },
            },
            {
                "op": "asset.register",
                "asset": {
                    "id": "t",
                    "kind": "text",
                    "label": "title",
                    "reference": "t",
                    "duration_ticks": T,
                },
            },
        ]
        seeded = client.post(
            path + "/edits",
            json={"request_id": "seed", "expected_revision": 0, "commands": seed},
        )
        assert seeded.status_code == 200, seeded.text
        revision = seeded.json()["project"]["revision"]
        stored = seeded.json()["project"]

        plan_before = compile_render_plan(
            Project.model_validate(stored), "h264-source-quality"
        ).ffmpeg_argv(str(FFMPEG), "out.mp4")

        endpoint = path + "/assets/a/proxy"
        # httpx merges per-request headers with the client defaults, so an anonymous call needs
        # its own client.
        anonymous = TestClient(app, base_url="http://127.0.0.1")
        assert anonymous.get(endpoint + "?width=960").status_code == 401
        absent = client.get(endpoint + "?width=960").json()
        assert absent["state"] == "absent" and absent["stream"] is None, absent
        assert client.get(endpoint + "?width=800").json()["error"]["code"] == "INVALID_REQUEST"
        assert (
            client.get(path + "/assets/zzz/proxy?width=960").json()["error"]["code"] == "NOT_FOUND"
        )
        assert (
            client.get(path + "/assets/t/proxy?width=960").json()["error"]["code"]
            == "UNVERIFIED_ASSET"
        )

        built = client.post(endpoint, json={"width": 960})
        assert built.status_code == 200, built.text
        ready = built.json()
        assert ready["state"] == "ready" and ready["display_width"] == 960, ready
        assert ready["stream"].startswith("http://127.0.0.1/v1/assets/a/proxy/stream?"), ready
        assert "sig=" in ready["stream"]

        again = client.get(endpoint + "?width=960").json()
        assert again["state"] == "ready" and again["content_sha256"] == ready["content_sha256"]
        assert client.post(endpoint, json={"width": 960}).json()["state"] == "ready"
        built_stamp = Path(ready["path"]).stat().st_mtime_ns

        stream = ready["stream"].replace("http://127.0.0.1", "")
        served = client.get(stream)
        assert served.status_code == 200, served.status_code
        assert served.headers["accept-ranges"] == "bytes"
        assert b"ftyp" in served.content[:16], served.content[:16]
        assert len(served.content) == ready["size_bytes"], (len(served.content), ready)

        tampered = stream.replace("sig=", "sig=00")
        assert client.get(tampered).status_code == 401, tampered
        missing_width = (
            "/v1/assets/a/proxy/stream?project_id="
            + project["id"]
            + "&width=480&sig="
            + signature(token, f"proxy:{project['id']}:a:480")
        )
        assert client.get(missing_width).status_code == 409

        after = client.get(path).json()
        assert after["revision"] == revision, "building a proxy must not edit the project"
        assert after == stored
        plan_after = compile_render_plan(
            Project.model_validate(after), "h264-source-quality"
        ).ffmpeg_argv(str(FFMPEG), "out.mp4")
        assert plan_after == plan_before, "the export plan must ignore proxies"

        # Undo/restore still works on a project whose media has a proxy, and the proxy itself is
        # keyed by content hash rather than by project.
        restored = client.post(
            path + "/restore",
            json={"request_id": "undo", "expected_revision": revision, "target_revision": 0},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["project"]["revision"] == revision + 1, restored.text
        assert restored.json()["project"]["clips"] == {}
        assert client.get(endpoint + "?width=960").json()["error"]["code"] == "NOT_FOUND"

        second = client.post("/v1/projects", json={"request_id": "new2", "name": "again"}).json()[
            "project"
        ]
        spath = f"/v1/projects/{second['id']}"
        reseeded = client.post(
            spath + "/edits",
            json={
                "request_id": "seed2",
                "expected_revision": 0,
                "commands": seed,
            },
        )
        assert reseeded.status_code == 200, reseeded.text
        reused = client.get(spath + "/assets/a/proxy?width=960").json()
        assert reused["state"] == "ready" and reused["content_sha256"] == ready["content_sha256"]
        assert Path(reused["path"]).stat().st_mtime_ns == built_stamp, "must not re-transcode"


def parity_suite(folder: Path) -> None:
    """The proxy has to be the same picture at the same time, only smaller."""
    media = service(folder, "parity")
    source = folder / "media" / "pattern.mp4"
    make_source(source, 1920, 1080, 3)
    verified = media.summarize(source, "video")
    record = media.build_proxy(verified, 640)
    assert record["state"] == "ready", record
    proxy = Path(record["path"])

    def levels(path: Path, at: float) -> tuple[float, float, float]:
        raw = run(
            [
                "-ss",
                f"{at:.6f}",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                "scale=64:36",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ]
        )
        pixels = list(raw)
        return tuple(round(sum(pixels[index::3]) / (len(pixels) / 3), 2) for index in range(3))

    want = levels(source, 1.5)
    got = levels(proxy, 1.5)
    drift = max(abs(a - b) for a, b in zip(want, got))
    print(f"   source rgb {want} vs proxy {got}, max channel drift {drift}")
    assert sum(got) > 60, f"the proxy frame must not be black: {got}"
    assert drift <= 12, (want, got, drift)

    tail = levels(proxy, 2.9)
    assert sum(tail) > 60, f"seeking near the end of the proxy must work: {tail}"
    meta = json.loads(
        subprocess.run(
            [str(FFPROBE), "-v", "error", "-show_streams", "-of", "json", str(proxy)],
            capture_output=True,
            timeout=120,
            creationflags=0x08000000,
        ).stdout
    )
    video = next(s for s in meta["streams"] if s["codec_type"] == "video")
    assert video["r_frame_rate"] == "30/1", video["r_frame_rate"]
    assert int(video["width"]) * 1080 - int(video["height"]) * 1920 <= 1920, video


def main() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="agentcut-proxy-") as scratch:
        folder = Path(scratch)
        build_suite(folder)
        http_suite(folder)
        parity_suite(folder)
    print(
        "PASS: proxies build from verified media only, are cached by content hash, stream with a "
        "signature, keep the project and export plan untouched, and match the source picture"
    )


if __name__ == "__main__":
    main()
