"""A render is delivered only after the finished file has been re-opened and measured.

Before 1.60, `succeeded` meant FFmpeg exited 0 and the file was not empty. That is a real gap: an
encoder can stop happily while writing the wrong wrapper, dropping a stream the mix produced, or
cutting the timeline short. So the worker now measures the candidate with the ffprobe standing
beside the very FFmpeg that ran, against the plan it compiled, and only names the file when the
container, the streams, the length and the last half second all answer.

This check has to prove both directions, because a gate that never fires is decoration:

1. every real export through the worker passes, and the job carries the measurement it made;
2. each class of broken artifact is refused with the reason it deserves — unreadable file, wrong
   container, a picture inside a sound-only preset, a missing sound stream, wrong length, and a
   truncated write whose header still reads a full three seconds (measured: ffprobe calls a 30 %
   MP4 complete at 3.000000 s, so the length alone cannot catch it and the tail decode is what
   does);
3. when no ffprobe stands beside FFmpeg, the job says it did not check instead of going quiet.
"""

import json
import os
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import EditorError
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime, ffprobe_beside, verify_output
from agentcut.media import MediaService
from agentcut.render import RenderPlan

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SECONDS = 3.0
SRC_W, SRC_H = 320, 180


def run(args, timeout=600):
    return subprocess.run(
        [str(a) for a in args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=0x08000000,
    )


def ffmpeg_build(folder: Path, name: str, extra: list[str], *, picture: bool = True) -> Path:
    """Write one real artifact with the bundled encoder, so nothing here is a synthetic stand-in."""
    out = folder / name
    build = [FFMPEG, "-y"]
    if picture:
        build += [
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={SRC_W}x{SRC_H}:rate=30/1:duration={SECONDS}",
        ]
    build += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={SECONDS}"]
    result = run([*build, *extra, "-shortest", out])
    assert result.returncode == 0, result.stderr[-400:]
    return out


def plan(container="mp4", seconds=SECONDS, video=True) -> RenderPlan:
    """A plan shaped exactly like the ones the gate is handed in production."""
    return RenderPlan(
        video_label="[vout]" if video else "",
        duration_ticks=int(seconds * T),
        summary={"container": container, "frame_rate": "30/1"},
    )


def refuse(label: str, path: Path, checked: RenderPlan, phrase: str) -> str:
    """Assert the gate rejects this artifact, and name the reason it had to give."""
    try:
        verify_output(FFMPEG, FFPROBE, path, checked)
    except EditorError as failure:
        assert failure.code == "OUTPUT_INVALID", (label, failure.code)
        assert phrase in failure.message, (label, failure.message)
        return failure.message
    raise AssertionError(f"{label} was accepted: {path.name}")


def artifact_suite(folder: Path) -> None:
    """Every rejection class, on a file that really exists, measured by the real ffprobe."""
    complete = ffmpeg_build(
        folder,
        "complete.mp4",
        [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
        ],
    )
    measurement = verify_output(FFMPEG, FFPROBE, complete, plan())
    assert "3.000 秒" in measurement and "2 路流" in measurement, measurement
    assert "h264/aac" in measurement and "mp4" in measurement, measurement
    print(f"   a complete export passes and reports {measurement}")

    junk = folder / "junk.mp4"
    junk.write_text("not a video, just words\n" * 40, encoding="utf-8")
    print("   unreadable:", refuse("text file", junk, plan(), "读不出任何流"))

    wav = ffmpeg_build(folder, "audio.wav", ["-vn", "-c:a", "pcm_s24le"], picture=False)
    print("   wrong container:", refuse("wav as mp3", wav, plan("mp3", video=False), "mp3 容器"))

    # The mirror case: a preset that asked for sound only must not come back holding a picture.
    print(
        "   extra stream:", refuse("mp4 as audio", complete, plan("mp3", video=False), "不该出画面")
    )

    silent = ffmpeg_build(
        folder,
        "silent.mp4",
        ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-an"],
    )
    print("   missing stream:", refuse("no audio", silent, plan(), "没有声音流"))

    short = run([FFMPEG, "-y", "-i", complete, "-t", "1", "-c", "copy", folder / "short.mp4"])
    assert short.returncode == 0, short.stderr[-300:]
    print("   wrong length:", refuse("1 s as 3 s", folder / "short.mp4", plan(), "相差超过"))

    # The header of a fast-start MP4 is written up front, so a write that stopped at 30 % of the
    # bytes still reports both streams and the full length. Only decoding the end notices.
    body = complete.read_bytes()
    clipped = folder / "truncated.mp4"
    clipped.write_bytes(body[: int(len(body) * 0.3)])
    header = json.loads(
        run(
            [
                FFPROBE,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                clipped,
            ]
        ).stdout
    )["format"]["duration"]
    assert abs(float(header) - SECONDS) < 0.15, header
    print("   truncated write:", refuse("30 % of bytes", clipped, plan(), "截断"))
    print(
        f"      (the header read {header} s for both the full and the cut file; "
        "the tail decode is what separated them)"
    )


def sibling_suite(folder: Path) -> None:
    """Which inspector the worker is allowed to trust, and what happens when there is none."""
    assert ffprobe_beside(FFMPEG) == FFPROBE, ffprobe_beside(FFMPEG)
    assert ffprobe_beside(None) is None
    lonely = folder / "no-probe"
    lonely.mkdir()
    # A hard link costs nothing on the same volume; copying 83 MB would make this check slow.
    try:
        os.link(FFMPEG, lonely / "ffmpeg.exe")
    except OSError:
        subprocess.run(["cp", str(FFMPEG), str(lonely / "ffmpeg.exe")], check=True)
    assert ffprobe_beside(lonely / "ffmpeg.exe") is None, "a probe from PATH must not be used"
    print("   ffprobe_beside finds the sibling and refuses to borrow one from elsewhere")


def export(folder: Path, name: str, ffmpeg: Path):
    """One real export through a worker configured with `ffmpeg`, as the API reported it."""
    database = folder / f"{name}-db.sqlite3"
    media = MediaService(database, [folder], folder / f"{name}-cache", FFMPEG, FFPROBE)
    exports_dir = folder / f"{name}-exports"
    runtime = JobRuntime(database, ffmpeg, exports_dir, [exports_dir, folder])
    runtime.ensure_worker()
    token = name + "t" * (56 - len(name))
    app = create_app(database, token, media=media, jobs=runtime)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        caps = client.get("/v1/capabilities").json()
        assert caps["features"]["verified_delivery"] is True, caps["features"]
        source = folder / f"{name}-source.mp4"
        if not source.exists():
            source = ffmpeg_build(
                folder,
                f"{name}-source.mp4",
                ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac"],
            )
        probe = client.post("/v1/media/import", json={"path": str(source)}).json()
        created = client.post(
            "/v1/projects",
            json={
                "request_id": f"{name}-new",
                "name": name,
                "settings": {
                    "width": SRC_W,
                    "height": SRC_H,
                    "frame_rate": {"numerator": 30, "denominator": 1},
                },
            },
        ).json()["project"]
        seeded = client.post(
            f"/v1/projects/{created['id']}/edits",
            json={
                "request_id": f"{name}-seed",
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
        revision = seeded.json()["project"]["revision"]
        job = client.post(
            f"/v1/projects/{created['id']}/renders",
            json={
                "request_id": f"{name}-ship",
                "expected_revision": revision,
                "preset_id": "h264-1080p",
                "filename": f"{name}.mp4",
            },
        )
        assert job.status_code == 200, job.text
        job_id = job.json()["job"]["id"]
        summary = {}
        for _ in range(900):
            summary = client.get("/v1/jobs/" + job_id).json()["job"]
            if summary["status"] in {"succeeded", "failed", "cancelled"}:
                break
    return summary, exports_dir


def worker_suite(folder: Path) -> None:
    """The gate where it runs: what a succeeded job promises, and what a refused file costs."""
    checked, exports_dir = export(folder, "probe", FFMPEG)
    assert checked["status"] == "succeeded", checked
    assert checked["output_checked"] is True, checked
    assert "复检" in checked["message"] and "尾部可解码" in checked["message"], checked["message"]
    landed = Path(checked["output_path"])
    assert landed.exists() and landed.stat().st_size == checked["output_size_bytes"], checked
    assert not list(exports_dir.glob("*.part.*")), list(exports_dir.glob("*.part.*"))
    print(f"   measured delivery: {checked['message']}")

    lonely = folder / "no-probe"
    unchecked, _ = export(folder, "bare", lonely / "ffmpeg.exe")
    assert unchecked["status"] == "succeeded", unchecked
    assert unchecked["output_checked"] is False, unchecked
    assert "未经复检" in unchecked["message"], unchecked["message"]
    assert Path(unchecked["output_path"]).exists()
    print(f"   delivery without a probe: {unchecked['message']}")

    # An inspector that cannot inspect: FFmpeg renamed to ffprobe refuses the options and exits, so
    # the file cannot be measured and the job must not publish it.
    broken = folder / "broken-probe"
    broken.mkdir()
    try:
        os.link(FFMPEG, broken / "ffmpeg.exe")
        os.link(FFMPEG, broken / "ffprobe.exe")
    except OSError:
        subprocess.run(["cp", str(FFMPEG), str(broken / "ffmpeg.exe")], check=True)
        subprocess.run(["cp", str(FFMPEG), str(broken / "ffprobe.exe")], check=True)
    refused, exports_dir = export(folder, "refused", broken / "ffmpeg.exe")
    assert refused["status"] == "failed", refused
    assert refused["error_code"] == "OUTPUT_INVALID", refused
    assert refused["output_checked"] is False, refused
    assert refused["output_path"] is None and refused["output_size_bytes"] is None, refused
    assert "读不出任何流" in refused["message"], refused["message"]
    assert not list(exports_dir.glob("*")), list(exports_dir.glob("*"))
    print(f"   refused candidate, nothing left behind: {refused['message'][:60]}")


def main() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="agentcut-verify-") as scratch:
        folder = Path(scratch)
        artifact_suite(folder)
        sibling_suite(folder)
        worker_suite(folder)
    print(
        "PASS: the worker re-opens every delivery and names it only after container, streams, "
        "length and a decoded tail agree; six kinds of broken file are refused by name, and an "
        "unchecked export says so instead of claiming a measurement"
    )


if __name__ == "__main__":
    main()
