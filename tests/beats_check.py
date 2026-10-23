"""Beat detection on a synthetic click track: the marks must land on the real beats.

The fixture is generated here, so the expected positions are known independently of the detector:
a 1 kHz click every 0.5 s is 120 BPM, and nothing else in the file should produce a mark. The
suite then checks the two mappings that matter — an asset is 1:1, a clip at 200 % lands every
quarter second — and that the analysis writes nothing at all.
"""

import math
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agentcut import beats  # noqa: E402
from agentcut.contracts import BEAT_MARK_LIMIT, EditorError  # noqa: E402
from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app  # noqa: E402
from agentcut.media import MediaService  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
RATE = 44_100
SECONDS = 6.0
FPS = 30
FRAME = T // FPS


def click_track(target: Path, seconds: float = SECONDS, silent: bool = False) -> None:
    frames = bytearray()
    for index in range(int(RATE * seconds)):
        moment = index / RATE
        value = 0
        phase = moment % 0.5
        if not silent and phase < 0.035:
            value = int(0.8 * 32767 * math.sin(2 * math.pi * 1000 * phase) * math.exp(-phase * 90))
        frames += struct.pack("<h", value)
    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(bytes(frames))


def silent_video(target: Path) -> None:
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
            f"color=c=0x202020:s=160x90:d={SECONDS}:r={FPS}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )


def module_suite(folder: Path) -> None:
    source = folder / "clicks.wav"
    click_track(source)
    body = beats.analyse(FFMPEG, source, 0, SECONDS)
    assert 115.0 <= body["bpm"] <= 125.0, body["bpm"]
    marks = body["seconds"]
    assert len(marks) == 11, marks
    for index, moment in enumerate(marks):
        expected = 0.5 * (index + 1)
        assert abs(moment - expected) < 0.05, (moment, expected)
    sparse = beats.analyse(FFMPEG, source, 0, SECONDS, min_gap_ms=800)
    assert len(sparse["seconds"]) <= 7, (
        f"最短间隔 800ms 仍然给了 {len(sparse['seconds'])} 枚：{sparse['seconds']}"
    )
    gaps = [b - a for a, b in zip(sparse["seconds"], sparse["seconds"][1:])]
    assert all(gap >= 0.75 for gap in gaps), gaps
    quiet = folder / "quiet.wav"
    click_track(quiet, seconds=2.0, silent=True)
    try:
        beats.analyse(FFMPEG, quiet, 0, 2.0)
    except EditorError as error:
        assert error.code == "BEAT_QUIET", error.payload()
    else:
        raise AssertionError("a silent window must refuse rather than invent beats")
    print("   module:", len(marks), "beats,", body["bpm"], "BPM, sparse", len(sparse["seconds"]))


def http_suite(folder: Path) -> None:
    media = MediaService(
        folder / "db.sqlite3", [folder / "media"], folder / "cache", FFMPEG, FFPROBE
    )
    source = folder / "media" / "clicks.wav"
    source.parent.mkdir(exist_ok=True)
    click_track(source)
    mute = folder / "media" / "mute.mp4"
    silent_video(mute)
    token = "beats" + "e" * 55
    app = create_app(folder / "api.sqlite3", token, media=media)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        caps = client.get("/v1/capabilities").json()
        assert caps["features"]["beat_detect"] is True, caps["features"]
        assert caps["limits"]["beat_marks"] == BEAT_MARK_LIMIT, caps["limits"]
        click = client.post("/v1/media/import", json={"path": str(source)}).json()
        silent = client.post("/v1/media/import", json={"path": str(mute)}).json()
        assert click["verified"]["has_audio"] is True, click
        assert silent["verified"]["has_audio"] is False, silent
        project = client.post("/v1/projects", json={"request_id": "new", "name": "beats"}).json()[
            "project"
        ]
        path = f"/v1/projects/{project['id']}"
        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "seed",
                "expected_revision": 0,
                "commands": [
                    {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "a"}},
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                    {
                        "op": "asset.import",
                        "asset_id": "click",
                        "label": "clicks",
                        "probe_id": click["id"],
                        "verified": click["verified"],
                    },
                    {
                        "op": "asset.import",
                        "asset_id": "silent",
                        "label": "mute",
                        "probe_id": silent["id"],
                        "verified": silent["verified"],
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "fast",
                            "asset_id": "click",
                            "track_id": "a",
                            "position_ticks": T,
                            "duration_ticks": 3 * T,
                            "speed_percent": 200,
                        },
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "mute",
                            "asset_id": "silent",
                            "track_id": "v",
                            "position_ticks": 0,
                            "duration_ticks": int(SECONDS * T),
                            "speed_percent": 100,
                        },
                    },
                ],
            },
        )
        assert seeded.status_code == 200, seeded.text
        route = path + "/audio/beats"

        asset = client.post(route, json={"asset_id": "click"})
        assert asset.status_code == 200, asset.text
        body = asset.json()
        assert body["clip_id"] is None and body["asset_id"] == "click", body
        assert len(body["beats"]) == 11, body["beats"]
        starts = [tick / T for tick in body["beats"]]
        for index, moment in enumerate(starts):
            assert abs(moment - 0.5 * (index + 1)) < 0.05, (moment, index)
        assert client.get(path).json()["revision"] == 1, "beat analysis must not write"

        fast = client.post(route, json={"clip_id": "fast"})
        assert fast.status_code == 200, fast.text
        marks = [tick / T for tick in fast.json()["beats"]]
        assert marks and abs(marks[0] - 1.25) < 0.05, (
            f"200% 的片段第一枚不在 1.25 秒：{marks}"
        )
        gaps = [b - a for a, b in zip(marks, marks[1:])]
        assert all(abs(gap - 0.25) < 0.04 for gap in gaps), (
            f"200% 的片段没有把源里的半秒映射成时间线上的四分之一秒：{gaps}"
        )
        assert marks == sorted(marks) and len(set(marks)) == len(marks), marks
        assert client.get(path).json()["revision"] == 1, "a clip scan must not write either"

        for payload, why in (
            ({"asset_id": "click", "clip_id": "fast"}, "both targets"),
            ({}, "no target"),
        ):
            refused = client.post(route, json=payload)
            assert refused.status_code == 422, (why, refused.text)
        missing = client.post(route, json={"asset_id": "nope"})
        assert missing.status_code == 404, missing.text
        no_audio = client.post(route, json={"clip_id": "mute"})
        assert no_audio.status_code == 422, f"没有音轨的片段必须按名字拒绝：{no_audio.text}"
        assert no_audio.json()["error"]["code"] == "INVALID_BEAT_TARGET", (
            f"没有音轨的片段必须按名字拒绝：{no_audio.text}"
        )

        curved = client.post(
            path + "/edits",
            json={
                "request_id": "curve",
                "expected_revision": 1,
                "commands": [
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "curved",
                            "asset_id": "click",
                            "track_id": "a",
                            "position_ticks": 10 * T,
                            "duration_ticks": 2 * T,
                            "speed_percent": 100,
                            "speed_curve": [
                                {"at_ticks": 0, "percent": 100},
                                {"at_ticks": T, "percent": 150},
                            ],
                        },
                    }
                ],
            },
        )
        assert curved.status_code == 200, curved.text
        refused = client.post(route, json={"clip_id": "curved"})
        assert refused.status_code == 422, (
            f"带变速曲线的片段必须按名字拒绝：{refused.text}"
        )
        assert refused.json()["error"]["code"] == "INVALID_BEAT_TARGET", (
            f"带变速曲线的片段必须按名字拒绝：{refused.text}"
        )
        assert client.get(path).json()["revision"] == 2, "refusals must not write"
        print("   http: asset 11 beats, 200% clip", len(marks), "beats, refusals named, revision 2")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    with tempfile.TemporaryDirectory(prefix="beats-check-") as name:
        folder = Path(name)
        module_suite(folder)
        http_suite(folder)
    print(
        "PASS: 120 BPM clicks land within 50 ms, a 200% clip halves the spacing, a silent or "
        "audio-less target is refused by name, and the analysis never writes a revision"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
