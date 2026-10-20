"""Render failures have to say something usable.

FFmpeg can die without writing a byte — a Windows exception code and nothing else — and the job used
to read "FFmpeg 退出码 3221225477：". A person at a failed export and an Agent reading
over HTTP need more: the code named, the silence admitted, and whatever the process did say kept
intact.
"""

import time
from pathlib import Path

import scratch
from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime, describe_exit
from agentcut.media import MediaService

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"


def words(message: str) -> str:
    return " ".join(message.split())


def pure_suite() -> None:
    crash = describe_exit(3221225477, "")
    assert "0xC0000005" in crash and "没有留下任何错误输出" in crash, crash
    assert "访问越界" in crash, crash
    stack = describe_exit(-1073741571, "")
    assert "0xC00000FD" in stack, stack
    overrun = describe_exit(-1073740791, "")
    assert "0xC0000409" in overrun, overrun
    loud = describe_exit(23, chr(10).join(["line one", "bogus codec" * 900]))
    assert loud.startswith("FFmpeg 退出码 23："), loud[:40]
    assert loud.endswith("bogus codec"), loud[-40:]
    assert len(loud) <= 16 + 3000, len(loud)
    assert "line one" not in loud, "the head of a long log is not the useful part"
    quiet = describe_exit(1, "   \n")
    assert quiet == "FFmpeg 退出码 1，且没有留下任何错误输出", quiet
    ordinary = describe_exit(0, "ignored")
    assert "退出码 0" in ordinary, ordinary
    print(f"   describe: crash codes named ({words(crash)[:64]}…), tails kept, silence admitted")


def live_suite(folder: Path) -> None:
    service = MediaService(folder / "rf-db.sqlite3", [folder], folder / "rf-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "rf-api.sqlite3", FFMPEG, folder / "deliverables", [folder / "deliverables"]
    )
    runtime.ensure_worker()
    token = "renderfailchk" + "f" * 51
    app = create_app(folder / "rf-api.sqlite3", token, media=service, jobs=runtime)
    clip = folder / "gone.mp4"
    clip.write_bytes(b"\x00" * 512)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        probe = client.post("/v1/media/import", json={"path": str(clip)})
        if probe.status_code != 200:
            # A file that is not media is refused at import, which is the better answer; the render
            # path is then exercised by deleting a clip the engine did accept.
            print(f"   import refuses a non-media file ({probe.json()['error']['code']})")
            real = folder / "real.mp4"
            import subprocess

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
                    "color=c=0x404040:s=320x180:r=30:d=1",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(real),
                ],
                check=True,
                capture_output=True,
                timeout=300,
                creationflags=0x08000000,
            )
            probe = client.post("/v1/media/import", json={"path": str(real)})
            clip = real
        assert probe.status_code == 200, probe.text
        verified = probe.json()["verified"]
        pid = client.post(
            "/v1/projects", json={"request_id": "new", "name": "render failure"}
        ).json()["project"]["id"]
        path = f"/v1/projects/{pid}"
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
                        "probe_id": verified["probe_id"],
                        "verified": verified,
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "c",
                            "asset_id": "a",
                            "track_id": "v",
                            "position_ticks": 0,
                            "duration_ticks": T,
                        },
                    },
                ],
            },
        )
        assert seeded.status_code == 200, seeded.text
        revision = seeded.json()["project"]["revision"]
        clip.unlink()
        queued = client.post(
            path + "/renders",
            json={
                "request_id": "r",
                "expected_revision": revision,
                "preset_id": "h264-source-quality",
                "filename": "never.mp4",
            },
        )
        assert queued.status_code == 200, queued.text
        job = queued.json()["job"]
        status = {}
        for _ in range(200):
            status = client.get("/v1/jobs/" + job["id"]).json()["job"]
            if status["status"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.5)
        assert status["status"] == "failed", status
        assert status["error_code"] == "FFMPEG_FAILED", status
        message = words(status["message"])
        assert "FFmpeg" in message and "退出码" in message, message
        assert not message.endswith("："), message
        assert len(message) > len("FFmpeg 退出码 23："), message
        print(f"   a deleted source reports: {message[:150]}")


def main() -> None:
    pure_suite()
    live_suite(scratch.make("agentcut-renderfail-"))
    print(
        "PASS: a failed render names the code, keeps whatever FFmpeg said, and admits the silence"
    )


if __name__ == "__main__":
    main()
