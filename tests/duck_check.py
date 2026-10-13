"""Automatic ducking: the envelope must be the trapezoid the maths says, one click must be one
revision, and an exported bed must really sit the requested number of dB below itself while the
driver is talking."""

import array
import math
import subprocess
import tempfile
import wave
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut import duck
from agentcut.animation import sample_values
from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import Project
from agentcut.http_api import create_app
from agentcut.media import MediaService
from agentcut.render import compile_render_plan

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
RATE = 48000
SECONDS = 6.0
BURSTS = ((1.0, 2.5), (3.5, 4.5))
DEPTH = 12.0
FRAME = T // 30
FAKE = 4 * T


def tone_wav(target: Path, frequency: float, amplitude: float, gate: bool) -> None:
    """Write a stereo PCM file: a steady bed, or the same tone gated to the burst windows."""
    frames = int(RATE * SECONDS)
    buffer = array.array("h", bytes(4 * frames))
    for index in range(frames):
        at = index / RATE
        level = amplitude if not gate or any(a <= at < b for a, b in BURSTS) else 0.0
        sample = int(round(32767 * level * math.sin(2 * math.pi * frequency * at)))
        for channel in range(2):
            buffer[2 * index + channel] = sample
    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(buffer.tobytes())


def slate(target: Path) -> None:
    """A silent picture, because a render refuses a timeline with nothing visible on it."""
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
            f"color=c=0x202020:s=320x180:d={SECONDS}:r=30",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ],
        check=True,
        capture_output=True,
        timeout=300,
        creationflags=0x08000000,
    )


def mean_volume(path: Path, at: float, seconds: float) -> float:
    """Average level of one window, measured by FFmpeg on the exported file itself."""
    process = subprocess.run(
        [
            str(FFMPEG),
            "-v",
            "info",
            "-nostdin",
            "-ss",
            f"{at:.3f}",
            "-t",
            f"{seconds:.3f}",
            "-i",
            str(path),
            "-map",
            "0:a",
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=300,
        creationflags=0x08000000,
    )
    text = process.stderr.decode(errors="replace")
    found = [line for line in text.splitlines() if "mean_volume" in line]
    assert found, text[-800:]
    return float(found[-1].split(":")[-1].strip().removesuffix(" dB"))


def reference(at: int, spans, low: float, attack: int, hold: int, release: int) -> float:
    """The trapezoid, written again here without reusing the module's helper."""
    value = 1.0
    for start, stop in spans:
        if at <= start or at >= stop + hold + release:
            factor = 1.0
        elif attack and at < start + attack:
            factor = 1.0 - (1.0 - low) * (at - start) / attack
        elif at <= stop + hold:
            factor = low
        else:
            factor = low + (1.0 - low) * (at - stop - hold) / release
        value = min(value, factor)
    return max(0.0, min(1.0, value))


def polyline_value(points, at: int) -> float:
    """Linear interpolation of kept breakpoints, written again so the gate is not the module."""
    if at <= points[0][0]:
        return points[0][1]
    for (left_at, left), (right_at, right) in zip(points, points[1:]):
        if at <= right_at:
            span = right_at - left_at
            return left + (right - left) * ((at - left_at) / span if span else 0.0)
    return points[-1][1]


class FakeClip:
    id = "fake"
    duration_ticks = int(FAKE)


def math_suite() -> None:
    assert abs(duck.depth_gain(6.0) - 0.5011872) < 1e-6, duck.depth_gain(6.0)
    assert abs(duck.depth_gain(20.0) - 0.1) < 1e-12, duck.depth_gain(20.0)
    assert duck.ramp_ticks(150, FRAME) == 10584000, duck.ramp_ticks(150, FRAME)
    assert duck.ramp_ticks(0, FRAME) == 0
    assert duck.ramp_ticks(1, FRAME) == FRAME, "a ramp must not land between two rendered frames"

    gaps = [
        {"from_ticks": 0, "to_ticks": int(T)},
        {"from_ticks": int(2.5 * T), "to_ticks": int(3.5 * T)},
    ]
    spans = duck.loud_spans(FakeClip(), gaps)
    assert spans == [(int(T), int(2.5 * T)), (int(3.5 * T), int(FAKE))], spans
    assert duck.loud_spans(FakeClip(), [{"from_ticks": 0, "to_ticks": int(FAKE)}]) == []
    assert duck.loud_spans(FakeClip(), []) == [(0, int(FAKE))]

    low = duck.depth_gain(DEPTH)
    attack, hold, release = (
        duck.ramp_ticks(150, FRAME),
        duck.ramp_ticks(120, FRAME),
        duck.ramp_ticks(600, FRAME),
    )
    options = {
        "low": low,
        "attack_ticks": attack,
        "hold_ticks": hold,
        "release_ticks": release,
    }
    points = duck.envelope(spans, int(FAKE), FRAME, **options)
    times = [at for at, _ in points]
    assert times == sorted(set(times)), times
    assert times[0] == 0 and times[-1] == int(FAKE)
    assert points[0][1] == 1.0, points[0]
    # The second utterance runs to the end of the clip, so the bed is still ducked at the last
    # breakpoint: a duck never invents a ramp back up that the driver did not ask for.
    assert points[-1][1] < low + 1e-9, points[-1]
    # A corner that falls between two rendered frames costs the two samples that straddle it, so
    # four per utterance plus the clip's ends is the budget — never one point per frame.
    assert len(points) <= 2 + 5 * len(spans), len(points)
    assert len(points) * 8 < max(1, round(FAKE / FRAME)), len(points)

    frames = max(1, round(FAKE / FRAME))
    grid = {min(FAKE, round(index * FAKE / frames)) for index in range(frames + 1)}
    assert set(times) <= grid, [at for at in times if at not in grid]
    worst = max(
        abs(value - reference(at, spans, low, attack, hold, release)) for at, value in points
    )
    assert worst < 1e-9, worst
    between = max(
        abs(
            polyline_value(points, min(FAKE, round(index * FAKE / frames)))
            - reference(min(FAKE, round(index * FAKE / frames)), spans, low, attack, hold, release)
        )
        for index in range(frames + 1)
    )
    assert between < 5e-4, between
    ducked = duck.ducked_ticks(points)
    expected = sum(
        FAKE / frames
        for index in range(frames)
        if reference(round(index * FAKE / frames), spans, low, attack, hold, release) < 1.0
    )
    # The two definitions differ by the frames that sit exactly on a ramp's shoulder: the polyline
    # counts a whole segment once either end dips below 1.0, the frame count skips the frame still
    # sitting at 1.0. Two frames is that boundary, no more.
    assert abs(ducked - expected) <= 2 * FRAME, (ducked, expected)
    print(
        f"   envelope: {len(points)} breakpoints, worst {worst:.1e} against the trapezoid, "
        f"{ducked / T:.2f} s below full gain for two utterances"
    )

    shallow = duck.envelope(
        spans, int(FAKE), FRAME, low=0.6, attack_ticks=0, hold_ticks=0, release_ticks=0
    )
    deep = duck.envelope(
        spans, int(FAKE), FRAME, low=0.2, attack_ticks=0, hold_ticks=0, release_ticks=0
    )
    assert min(value for _, value in deep) < min(value for _, value in shallow)
    assert duck.envelope([], int(FAKE), FRAME, **options) == []
    plan = duck.plan_clip(FakeClip(), [(0, 1.0), (int(T), 0.25)])
    assert len(plan) == 1 and plan[0]["op"] == "keyframes.replace", plan
    assert plan[0]["keyframes"][1] == {
        "property": "gain",
        "at_ticks": int(T),
        "value": 0.25,
        "interpolation": "linear",
    }, plan
    try:
        duck.plan_clip(FakeClip(), [(0, 1.0), (0, 0.5)])
    except Exception as error:  # noqa: BLE001 - the refusal itself is the gate
        assert getattr(error, "code", "") == "DUCK_PLAN_INVALID", error
    else:
        raise AssertionError("two breakpoints at the same time are not an envelope")


def client_for(folder: Path, name: str):
    media = MediaService(
        folder / f"{name}-db.sqlite3", [folder], folder / f"{name}-cache", FFMPEG, FFPROBE
    )
    token = f"duck{name}" + "e" * max(0, 64 - len(f"duck{name}"))
    app = create_app(folder / f"{name}-api.sqlite3", token, media=media)
    return TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ), token


def seed(client: TestClient, folder: Path) -> str:
    bed = client.post("/v1/media/import", json={"path": str(folder / "bed.wav")}).json()
    voice = client.post("/v1/media/import", json={"path": str(folder / "voice.wav")}).json()
    project = client.post(
        "/v1/projects",
        json={
            "request_id": "new",
            "name": "duck",
            "settings": {
                "width": 320,
                "height": 180,
                "frame_rate": {"numerator": 30, "denominator": 1},
            },
        },
    ).json()["project"]
    seeded = client.post(
        f"/v1/projects/{project['id']}/edits",
        json={
            "request_id": "seed",
            "expected_revision": 0,
            "commands": [
                {"op": "track.add", "track": {"id": "bed", "kind": "audio", "name": "配乐"}},
                {"op": "track.add", "track": {"id": "voice", "kind": "audio", "name": "口播"}},
                {
                    "op": "asset.import",
                    "asset_id": "bed",
                    "label": "bed",
                    "probe_id": bed["id"],
                    "verified": bed["verified"],
                },
                {
                    "op": "asset.import",
                    "asset_id": "voice",
                    "label": "voice",
                    "probe_id": voice["id"],
                    "verified": voice["verified"],
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "music",
                        "asset_id": "bed",
                        "track_id": "bed",
                        "position_ticks": 0,
                        "duration_ticks": int(SECONDS * T),
                    },
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "speech",
                        "asset_id": "voice",
                        "track_id": "voice",
                        "position_ticks": 0,
                        "duration_ticks": int(SECONDS * T),
                    },
                },
            ],
        },
    )
    assert seeded.status_code == 200, seeded.text
    return project["id"]


def http_suite(folder: Path) -> None:
    client, _ = client_for(folder, "http")
    with client:
        caps = client.get("/v1/capabilities").json()
        assert caps["features"]["audio_ducking"] is True, caps["features"]
        assert "keyframes.replace" in caps["commands"], caps["commands"]
        project_id = seed(client, folder)
        path = f"/v1/projects/{project_id}"
        scan = path + "/tracks/bed/duck"
        base = {"request_id": "plan", "expected_revision": 1}

        read = client.post(scan, json=base)
        assert read.status_code == 200, read.text
        body = read.json()
        assert body["committed"] is False and client.get(path).json()["revision"] == 1
        plan = body["duck"]
        speech = [(i["from_ticks"] / T, i["to_ticks"] / T) for i in plan["speech"]]
        assert speech == [(1.0, 2.5), (3.5, 4.5)], speech
        # The contract default is a 9 dB duck; this request did not name a depth.
        assert abs(plan["gain"] - 0.354813) < 1e-5, plan["gain"]
        assert len(plan["commands"]) == 1 and plan["commands"][0]["op"] == "keyframes.replace"
        keyframes = plan["commands"][0]["keyframes"]
        assert keyframes[0]["value"] == 1.0 and keyframes[-1]["value"] == 1.0
        assert plan["clips"][0]["ducked_ticks"] > int(2.5 * T), plan["clips"][0]
        assert plan["clips"][0]["replaced_gain_keyframes"] == 0, plan["clips"][0]
        assert plan["skipped"] == [] and plan["clips"][0].get("skipped") is None, plan
        print(
            f"   plan: speech at {speech}, {len(keyframes)} keyframes, "
            f"{plan['clips'][0]['ducked_ticks'] / T:.2f} s below full gain at {plan['gain']}"
        )

        applied = client.post(scan, json={**base, "request_id": "go", "apply": True})
        assert applied.status_code == 200, applied.text
        result = applied.json()
        assert result["committed"] is True and result["project"]["revision"] == 2
        written = [
            key
            for key in result["project"]["clips"]["music"]["keyframes"]
            if key["property"] == "gain"
        ]
        assert len(written) == len(keyframes), (len(written), len(keyframes))
        assert [key["at_ticks"] for key in written] == [item["at_ticks"] for item in keyframes]
        stored = Project.model_validate(result["project"])
        music = stored.clips["music"]
        under = sample_values(music, int(1.8 * T))["gain"]
        gap = sample_values(music, int(5.6 * T))["gain"]
        head = sample_values(music, 0)["gain"]
        assert abs(under - 0.354813) < 5e-4, under
        assert abs(gap - 1.0) < 1e-6 and abs(head - 1.0) < 1e-6, (gap, head)
        print(
            f"   the clock the browser reads: gain is {under} at 1.8 s, {gap} at 5.6 s, {head} at 0"
        )

        replay = client.post(scan, json={**base, "request_id": "go", "apply": True})
        assert replay.json()["replayed"] is True and replay.json()["project"]["revision"] == 2
        stale = client.post(
            scan, json={**base, "request_id": "stale", "expected_revision": 1, "apply": True}
        )
        assert stale.status_code == 409, stale.text
        assert client.get(path).json()["revision"] == 2

        deeper = client.post(
            scan,
            json={
                "request_id": "deeper",
                "expected_revision": 2,
                "apply": True,
                "depth_db": 20.0,
            },
        )
        assert deeper.status_code == 200, deeper.text
        after = deeper.json()["project"]["clips"]["music"]["keyframes"]
        gains = [key for key in after if key["property"] == "gain"]
        assert len(gains) == len({key["at_ticks"] for key in gains}), "no stacked duplicates"
        floor = min(key["value"] for key in gains)
        assert abs(floor - 0.1) < 5e-4, floor
        assert deeper.json()["project"]["revision"] == 3
        print(f"   re-ducking replaces the envelope instead of stacking: floor now {floor}")

        self_duck = client.post(
            scan,
            json={
                "request_id": "self",
                "expected_revision": 3,
                "driver_track_ids": ["bed"],
            },
        )
        assert self_duck.status_code == 422, self_duck.text
        assert self_duck.json()["error"]["code"] == "INVALID_DUCK", self_duck.text
        ghost = client.post(
            scan,
            json={"request_id": "ghost", "expected_revision": 3, "driver_track_ids": ["nope"]},
        )
        assert ghost.status_code == 404, ghost.text
        missing = client.post(
            path + "/tracks/nope/duck", json={"request_id": "m", "expected_revision": 3}
        )
        assert missing.status_code == 404, missing.text
        assert client.get(path).json()["revision"] == 3, "a refused duck must write nothing"

        for name, keyframes_body in (
            (
                "unsorted",
                [
                    {"property": "gain", "at_ticks": 10, "value": 1.0},
                    {"property": "gain", "at_ticks": 5, "value": 0.5},
                ],
            ),
            (
                "mixed",
                [
                    {"property": "gain", "at_ticks": 0, "value": 1.0},
                    {"property": "opacity", "at_ticks": 10, "value": 0.5},
                ],
            ),
            ("hot", [{"property": "gain", "at_ticks": 0, "value": 9.0}]),
            ("empty", []),
        ):
            refused = client.post(
                path + "/edits",
                json={
                    "request_id": name,
                    "expected_revision": 3,
                    "commands": [
                        {
                            "op": "keyframes.replace",
                            "clip_id": "music",
                            "property": "gain",
                            "keyframes": keyframes_body,
                        }
                    ],
                },
            )
            assert refused.status_code == 422, (name, refused.text)
        assert client.get(path).json()["revision"] == 3, "a rejected replacement writes nothing"

        kept = client.post(
            path + "/edits",
            json={
                "request_id": "other-property",
                "expected_revision": 3,
                "commands": [
                    {
                        "op": "keyframes.replace",
                        "clip_id": "music",
                        "property": "opacity",
                        "keyframes": [{"property": "opacity", "at_ticks": 0, "value": 0.5}],
                    }
                ],
            },
        )
        assert kept.status_code == 200, kept.text
        survivors = kept.json()["project"]["clips"]["music"]["keyframes"]
        assert any(k["property"] == "gain" for k in survivors), survivors
        assert sum(1 for k in survivors if k["property"] == "opacity") == 1, survivors
        print("   replacing one property leaves the other property's curve alone")


def export(folder: Path, name: str, *, duck_it: bool) -> Path:
    client, _ = client_for(folder, name)
    out = folder / f"{name}.mp4"
    with client:
        project_id = seed(client, folder)
        path = f"/v1/projects/{project_id}"
        slate = client.post("/v1/media/import", json={"path": str(folder / "slate.mp4")}).json()
        prepared = client.post(
            path + "/edits",
            json={
                "request_id": "picture",
                "expected_revision": 1,
                "commands": [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
                    {
                        "op": "asset.import",
                        "asset_id": "slate",
                        "label": "slate",
                        "probe_id": slate["id"],
                        "verified": slate["verified"],
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "slate-clip",
                            "asset_id": "slate",
                            "track_id": "v",
                            "position_ticks": 0,
                            "duration_ticks": int(SECONDS * T),
                        },
                    },
                    # The driver is muted so the exported audio is the bed alone: the measurement
                    # then cannot be the speech tone in disguise.
                    {"op": "track.update", "track_id": "voice", "muted": True},
                ],
            },
        )
        assert prepared.status_code == 200, prepared.text
        revision = 2
        if duck_it:
            applied = client.post(
                path + "/tracks/bed/duck",
                json={
                    "request_id": "media-duck",
                    "expected_revision": revision,
                    "apply": True,
                    "depth_db": DEPTH,
                },
            )
            assert applied.status_code == 200, applied.text
            assert applied.json()["project"]["revision"] == 3
            revision = 3
        stored = client.get(path).json()
        assert stored["revision"] == revision
        plan = compile_render_plan(Project.model_validate(stored), "h264-source-quality")
        stages = "".join(stage for stage in plan.filters if "volume=" in stage)
        assert ("if(lt(" in stages) is duck_it, stages[:400]
        job = folder / f"{name}-job"
        job.mkdir(exist_ok=True)
        for label, body in plan.text_files.items():
            (job / label).write_text(body, encoding="utf-8")
        process = subprocess.run(
            plan.ffmpeg_argv(str(FFMPEG), str(out)),
            cwd=job,
            capture_output=True,
            timeout=600,
            creationflags=0x08000000,
        )
        assert process.returncode == 0, process.stderr.decode(errors="replace")[-900:]
    assert out.stat().st_size > 1000, out
    return out


def media_suite(folder: Path) -> None:
    """The exported bed must sit the requested number of dB below itself under the speech."""
    plain = export(folder, "plain", duck_it=False)
    ducked = export(folder, "ducked", duck_it=True)
    windows = (("gap", 5.5, 0.4), ("under speech", 1.5, 0.9))
    readings = {}
    for label, path in (("plain", plain), ("ducked", ducked)):
        readings[label] = {name: mean_volume(path, at, span) for name, at, span in windows}
    flat = readings["plain"]
    assert abs(flat["gap"] - flat["under speech"]) < 0.4, flat
    pulled = readings["ducked"]
    delta = pulled["gap"] - pulled["under speech"]
    assert abs(delta - DEPTH) < 0.8, (pulled, delta)
    assert abs(pulled["gap"] - flat["gap"]) < 0.4, (pulled, flat)
    print(
        f"   exported bed: {flat['under speech']} dB (no duck) -> {pulled['under speech']} dB "
        f"under speech, {pulled['gap']} dB in the gap, {delta:.2f} dB for a {DEPTH} dB duck"
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-duck-") as scratch:
        folder = Path(scratch)
        tone_wav(folder / "bed.wav", 220.0, 0.3, gate=False)
        tone_wav(folder / "voice.wav", 880.0, 0.4, gate=True)
        slate(folder / "slate.mp4")
        math_suite()
        http_suite(folder)
        media_suite(folder)
    print(
        "PASS: the duck envelope is the trapezoid the request asked for, one click is one "
        "revision, and the exported bed really sits the requested dB below itself under speech"
    )


if __name__ == "__main__":
    main()
