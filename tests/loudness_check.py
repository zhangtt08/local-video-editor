"""Loudness metering against synthetic stereo tones with a known level difference: the meter must
agree with the ratio, the suggested gain must be the one that lands on target, and an exported clip
normalised with that gain must really measure at the target."""

import array
import hashlib
import math
import subprocess
import tempfile
import wave
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import ClipEffects, EditBatch, EditorError, Project, VerifiedMedia
from agentcut.http_api import create_app
from agentcut.loudness import measure, normalize_gain
from agentcut.media import MediaService
from agentcut.render import compile_render_plan
from agentcut.timeline import apply_commands, validate_timeline

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
WIDTH, HEIGHT = 320, 180
SECONDS = 2.0
LOUD = 0.5
QUIET = 0.125  # 12.04 dB below LOUD, which the meter has to reproduce
TARGET = -16.0


def tone(target: Path, volume: float) -> None:
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
            f"sine=frequency=1000:duration={SECONDS}:sample_rate=48000",
            "-af",
            f"volume={volume},aformat=channel_layouts=stereo",
            "-c:a",
            "pcm_s16le",
            str(target),
        ],
        check=True,
        capture_output=True,
        timeout=300,
        creationflags=0x08000000,
    )


def video(target: Path, audio: Path) -> None:
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
            f"color=c=0x404040:s={WIDTH}x{HEIGHT}:d={SECONDS}",
            "-i",
            str(audio),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(target),
        ],
        check=True,
        capture_output=True,
        timeout=300,
        creationflags=0x08000000,
    )


def clip_payload(**changes) -> dict:
    clip = {
        "id": "c",
        "asset_id": "a",
        "track_id": "v",
        "position_ticks": 0,
        "duration_ticks": int(SECONDS * T),
    }
    clip.update(changes)
    return clip


def project_payload(clip: dict, source: Path, canvas: tuple[int, int] = (WIDTH, HEIGHT)) -> Project:
    verified = VerifiedMedia.model_validate(
        {
            "probe_id": "a",
            "path": str(source),
            "kind": "video",
            "label": "tone",
            "size_bytes": source.stat().st_size,
            "content_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "duration_ticks": int(SECONDS * T),
            "width": WIDTH,
            "height": HEIGHT,
            "has_audio": True,
        }
    )
    project = Project.model_validate(
        {
            "id": "p",
            "name": "loudness",
            "settings": {"width": canvas[0], "height": canvas[1]},
            "tracks": [{"id": "v", "kind": "video", "name": "v"}],
            "assets": {
                "a": {
                    "id": "a",
                    "kind": "video",
                    "label": "a",
                    "reference": "r",
                    "duration_ticks": int(SECONDS * T),
                    "verified": verified.model_dump(),
                }
            },
            "clips": {"c": clip},
        }
    )
    validate_timeline(project)
    return project


def apply(project: Project, commands: list[dict]) -> Project:
    batch = EditBatch(request_id="check", expected_revision=project.revision, commands=commands)
    return apply_commands(project, batch.commands)


def export(project: Project, out: Path, job: Path) -> None:
    plan = compile_render_plan(project, "h264-source-quality")
    job.mkdir(exist_ok=True)
    for name, body in plan.text_files.items():
        (job / name).write_text(body, encoding="utf-8")
    process = subprocess.run(
        plan.ffmpeg_argv(str(FFMPEG), str(out)),
        cwd=job,
        capture_output=True,
        timeout=300,
        creationflags=0x08000000,
    )
    assert process.returncode == 0, process.stderr.decode(errors="replace")[-800:]


def _biquad(
    values: list[float], b0: float, b1: float, b2: float, a1: float, a2: float
) -> list[float]:
    out: list[float] = []
    x1 = x2 = y1 = y2 = 0.0
    for value in values:
        y = b0 * value + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1 = x1, value
        y2, y1 = y1, y
        out.append(y)
    return out


# K-weighting for 48 kHz, from ITU-R BS.1770-4. The spec prints stage 2 as a1=-1.9909457,
# a2=0.9909375; taken literally that pair puts one pole at 1.0008 and a naive recursion then
# diverges over two seconds of audio, so the intended critically damped poles at sqrt(a2) are used.
SHELF = (1.5351248, -2.6916961, 1.1983925, -1.6903595, 0.7322431)
RLB = (1.0, -2.0, 1.0, -1.99091698, 0.9909375)


def reference_lufs(path: Path) -> float:
    """Integrated loudness decoded from the PCM itself: no FFmpeg, no text parsing."""
    with wave.open(str(path), "rb") as handle:
        rate, channels, width = handle.getframerate(), handle.getnchannels(), handle.getsampwidth()
        raw = handle.readframes(handle.getnframes())
    assert (rate, width, channels) == (48000, 2, 2), (rate, width, channels)
    samples = array.array("h")
    samples.frombytes(raw)
    total = 0.0
    for channel in range(channels):
        plane = [value / 32768.0 for value in samples[channel::channels]]
        filtered = _biquad(_biquad(plane, *SHELF), *RLB)
        total += sum(value * value for value in filtered) / len(filtered)
    return -0.691 + 10 * math.log10(total)


def measure_suite(folder: Path) -> None:
    loud = measure(FFMPEG, folder / "loud.wav")
    quiet = measure(FFMPEG, folder / "quiet.wav")
    assert loud["integrated_lufs"] > quiet["integrated_lufs"], (loud, quiet)
    assert loud["true_peak_dbtp"] > quiet["true_peak_dbtp"], (loud, quiet)
    difference = loud["integrated_lufs"] - quiet["integrated_lufs"]
    want = 20 * math.log10(LOUD / QUIET)
    assert abs(difference - want) < 0.3, (difference, want)
    assert loud["lra_lu"] is None or loud["lra_lu"] <= 5.0, loud
    print(
        f"   measured {loud['integrated_lufs']} LUFS / {loud['true_peak_dbtp']} dBTP against "
        f"{quiet['integrated_lufs']} LUFS / {quiet['true_peak_dbtp']} dBTP: {difference:.2f} dB "
        f"apart, the tones are {want:.2f} dB apart"
    )

    # A constant offset in the meter would pass every relative gate above, and the gain formula
    # would then happily deliver audio a client's own meter reads several LU off target. So compare
    # the absolute number against BS.1770 computed from the decoded samples themselves.
    for name, reading in (("loud", loud), ("quiet", quiet)):
        reference = reference_lufs(folder / f"{name}.wav")
        delta = reading["integrated_lufs"] - reference
        assert abs(delta) <= 0.2, (name, reading["integrated_lufs"], reference, delta)
        print(
            f"   {name}.wav is calibrated: the meter says {reading['integrated_lufs']} LUFS, "
            f"BS.1770 decoded from the PCM says {reference:.2f} LUFS ({delta:+.2f} LU)"
        )

    silent = folder / "silent.wav"
    subprocess.run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-t",
            "1",
            "-c:a",
            "pcm_s16le",
            str(silent),
        ],
        check=True,
        capture_output=True,
        timeout=300,
        creationflags=0x08000000,
    )
    refused = False
    try:
        body = measure(FFMPEG, silent)
    except EditorError as error:
        assert error.code == "LOUDNESS_FAILED", error.payload()
        refused = True
    if not refused:
        # Some builds report -inf as a number; either way no gain may be invented for it.
        assert body["integrated_lufs"] <= -70.0, body
        try:
            normalize_gain(body)
        except EditorError as error:
            assert error.code == "LOUDNESS_FAILED", error.payload()
        else:
            raise AssertionError("a silent clip has no loudness to match")
    print("   a silent file is refused rather than given an infinite gain")


def gain_suite(folder: Path) -> None:
    loud = measure(FFMPEG, folder / "loud.wav")
    plan = normalize_gain(loud, target_lufs=TARGET)
    wanted = 10 ** ((TARGET - loud["integrated_lufs"]) / 20)
    headroom = 10 ** ((-1.0 - loud["true_peak_dbtp"]) / 20)
    assert abs(plan["gain"] - min(wanted, headroom)) < 1e-3, plan
    assert 0.0 <= plan["gain"] <= 4.0, plan
    assert plan["reaches_target"] is True and plan["limited_by"] == "", plan

    # A ceiling that binds must be reported, not hidden behind a gain that would clip.
    hot = {"integrated_lufs": -20.0, "true_peak_dbtp": -0.5, "lra_lu": 1.0}
    held = normalize_gain(hot, target_lufs=TARGET)
    assert held["limited_by"] == "ceiling" and held["gain"] < 1.585, held
    assert held["predicted_peak_dbtp"] <= -0.99 and held["predicted_lufs"] < TARGET, held
    assert held["reaches_target"] is False, held
    # A clip further away than the gain range can reach says so instead of pretending.
    far = normalize_gain(
        {"integrated_lufs": -60.0, "true_peak_dbtp": -60.0, "lra_lu": 0.0}, target_lufs=TARGET
    )
    assert far["gain"] == 4.0 and far["limited_by"] == "gain_range", far
    assert far["reaches_target"] is False and far["predicted_lufs"] < TARGET, far
    print(
        f"   gain {plan['gain']} lands the loud tone at {plan['predicted_lufs']} LUFS "
        f"(peak {plan['predicted_peak_dbtp']} dBTP); the hot clip is held to {held['gain']} by the "
        f"ceiling and only reaches {held['predicted_lufs']} LUFS"
    )


def http_suite(folder: Path) -> None:
    (folder / "media").mkdir(exist_ok=True)
    source = folder / "media" / "api.mp4"
    video(source, folder / "quiet.wav")
    media = MediaService(
        folder / "db.sqlite3", [folder / "media"], folder / "cache", FFMPEG, FFPROBE
    )
    token = "loudness" + "e" * 54
    app = create_app(folder / "api.sqlite3", token, media=media)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        caps = client.get("/v1/capabilities").json()
        assert caps["features"]["loudness_metering"] is True, caps["features"]
        assert "clip.effects" in caps["commands"]
        probe = client.post("/v1/media/import", json={"path": str(source)}).json()
        project = client.post(
            "/v1/projects", json={"request_id": "new", "name": "loudness"}
        ).json()["project"]
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
                        "asset_id": "a",
                        "label": "tone",
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
        scan = path + "/clips/c/loudness"

        read = client.post(
            scan, json={"request_id": "scan", "expected_revision": 1, "target_lufs": -28.0}
        )
        assert read.status_code == 200, read.text
        body = read.json()
        assert body["committed"] is False and client.get(path).json()["revision"] == 1
        found = body["loudness"]
        assert found["integrated_lufs"] < -20.0 and 1.0 < found["gain"] < 4.0, found
        assert found["limited_by"] == "" and found["reaches_target"] is True, found
        print(
            "   http scan:",
            f"{found['integrated_lufs']} LUFS, gain {found['gain']} predicts "
            f"{found['predicted_lufs']} LUFS, limited_by={found['limited_by']!r}",
        )

        preview = client.post(
            scan,
            json={
                "request_id": "dry",
                "expected_revision": 1,
                "apply": True,
                "dry_run": True,
                "target_lufs": -28.0,
            },
        )
        assert preview.json()["committed"] is False and client.get(path).json()["revision"] == 1

        applied = client.post(
            scan,
            json={
                "request_id": "apply",
                "expected_revision": 1,
                "apply": True,
                "target_lufs": -28.0,
            },
        )
        assert applied.status_code == 200, applied.text
        result = applied.json()
        assert result["committed"] is True and result["project"]["revision"] == 2
        effects = result["project"]["clips"]["c"]["effects"]
        assert effects["gain"] == found["gain"], effects
        assert effects["scale"] == 1.0 and effects["opacity"] == 1.0, effects

        replay = client.post(
            scan,
            json={
                "request_id": "apply",
                "expected_revision": 1,
                "apply": True,
                "target_lufs": -28.0,
            },
        )
        assert replay.json()["replayed"] is True and replay.json()["project"]["revision"] == 2
        conflict = client.post(
            scan, json={"request_id": "again", "expected_revision": 1, "apply": True}
        )
        assert conflict.status_code == 409, conflict.text
        ghost = client.post(
            path + "/clips/nope/loudness", json={"request_id": "ghost", "expected_revision": 2}
        )
        assert ghost.status_code == 404, ghost.text
        softer = client.post(
            scan, json={"request_id": "soft", "expected_revision": 2, "target_lufs": -30.0}
        )
        assert softer.json()["loudness"]["gain"] < found["gain"], softer.text
        out_of_range = client.post(
            scan, json={"request_id": "loud", "expected_revision": 2, "target_lufs": -31.0}
        )
        assert out_of_range.status_code == 422, out_of_range.text
        assert client.get(path).json()["revision"] == 2, "a read-only scan must not write"


def media_suite(folder: Path) -> None:
    """The gain the engine suggests must land the exported audio on the target."""
    source = folder / "export.mp4"
    video(source, folder / "loud.wav")
    project = project_payload(clip_payload(), source)
    measured = measure(FFMPEG, source)
    plan = normalize_gain(measured, target_lufs=TARGET)
    effects = ClipEffects(gain=plan["gain"])
    normalised = apply(
        project, [{"op": "clip.effects", "clip_id": "c", "effects": effects.model_dump()}]
    )
    out = folder / "normalised.mp4"
    export(normalised, out, folder / "loud-job")
    after = measure(FFMPEG, out)
    assert abs(after["integrated_lufs"] - TARGET) < 1.0, (measured, after)
    assert after["true_peak_dbtp"] <= -0.8, after
    print(
        f"   exported gain {plan['gain']}: {measured['integrated_lufs']} -> "
        f"{after['integrated_lufs']} LUFS against a {TARGET} LUFS target "
        f"(true peak {after['true_peak_dbtp']} dBTP)"
    )


def track_suite(folder: Path) -> None:
    """One call aligns every clip on a track, and the exported mix then measures at the target."""
    root = folder / "track"
    root.mkdir(exist_ok=True)
    media = MediaService(
        folder / "track-db.sqlite3", [root], folder / "track-cache", FFMPEG, FFPROBE
    )
    token = "loudtrack" + "e" * 53
    app = create_app(folder / "track-api.sqlite3", token, media=media)
    commands: list[dict] = []
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        for index, level in enumerate((0.5, 0.25, 0.125)):
            tone(root / f"lvl{index}.wav", level)
            video(root / f"lvl{index}.mp4", root / f"lvl{index}.wav")
            probe = client.post(
                "/v1/media/import", json={"path": str(root / f"lvl{index}.mp4")}
            ).json()
            commands.append(
                {
                    "op": "asset.import",
                    "asset_id": f"a{index}",
                    "label": f"level {level}",
                    "probe_id": probe["id"],
                    "verified": probe["verified"],
                }
            )
            commands.append(
                {
                    "op": "clip.add",
                    "clip": {
                        "id": f"c{index}",
                        "asset_id": f"a{index}",
                        "track_id": "v",
                        "position_ticks": index * int(SECONDS * T),
                        "duration_ticks": int(SECONDS * T),
                    },
                }
            )
        project = client.post("/v1/projects", json={"request_id": "new", "name": "track"}).json()[
            "project"
        ]
        path = f"/v1/projects/{project['id']}"
        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "seed",
                "expected_revision": 0,
                "commands": [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "口播"}},
                    *commands,
                ],
            },
        )
        assert seeded.status_code == 200, seeded.text
        scan = path + "/tracks/v/loudness"

        read = client.post(
            scan, json={"request_id": "scan", "expected_revision": 1, "target_lufs": -28.0}
        )
        assert read.status_code == 200, read.text
        body = read.json()
        assert body["committed"] is False and client.get(path).json()["revision"] == 1
        report = body["loudness"]
        assert report["measured"] == 3 and report["changed"] == 3, report
        assert report["off_target"] == 0, report
        gains = [item["gain"] for item in report["clips"]]
        assert gains == sorted(gains) and gains[0] < 1.0 < gains[-1] <= 4.0, gains
        assert all(item["reaches_target"] and item["limited_by"] == "" for item in report["clips"])
        print(
            "   track meter:",
            [(item["clip_id"], item["integrated_lufs"], item["gain"]) for item in report["clips"]],
        )

        dry = client.post(
            scan,
            json={
                "request_id": "dry",
                "expected_revision": 1,
                "apply": True,
                "dry_run": True,
                "target_lufs": -28.0,
            },
        )
        assert dry.json()["committed"] is False and client.get(path).json()["revision"] == 1

        applied = client.post(
            scan,
            json={
                "request_id": "apply",
                "expected_revision": 1,
                "apply": True,
                "target_lufs": -28.0,
            },
        )
        assert applied.status_code == 200, applied.text
        result = applied.json()
        assert result["committed"] is True and result["project"]["revision"] == 2
        for item in report["clips"]:
            assert result["project"]["clips"][item["clip_id"]]["effects"]["gain"] == item["gain"], (
                item
            )

        again = client.post(
            scan, json={"request_id": "rescan", "expected_revision": 2, "target_lufs": -28.0}
        )
        aligned = again.json()["loudness"]
        assert aligned["changed"] == 0 and aligned["commands"] == [], aligned
        assert aligned["measured"] == 3, aligned
        nothing = client.post(
            scan,
            json={
                "request_id": "twice",
                "expected_revision": 2,
                "apply": True,
                "target_lufs": -28.0,
            },
        )
        assert nothing.json()["error"]["code"] == "INVALID_LOUDNESS_TARGET", nothing.text

        current = client.get(path).json()
        project_obj = Project.model_validate(current)
        out = folder / "aligned.mp4"
        export(project_obj, out, folder / "aligned-job")
        mix = measure(FFMPEG, out)
        assert abs(mix["integrated_lufs"] + 28.0) < 1.0, mix
        print(
            f"   exported mix measures {mix['integrated_lufs']} LUFS / {mix['true_peak_dbtp']} dBTP"
        )

        keyed = client.post(
            path + "/edits",
            json={
                "request_id": "keyframe",
                "expected_revision": 2,
                "commands": [
                    {
                        "op": "keyframe.set",
                        "clip_id": "c0",
                        "keyframe": {"property": "gain", "at_ticks": 0, "value": 1.0},
                    }
                ],
            },
        )
        assert keyed.status_code == 200, keyed.text
        refused = client.post(
            path + "/clips/c0/loudness", json={"request_id": "anim", "expected_revision": 3}
        )
        assert "keyframes" in refused.json()["error"]["message"], refused.text
        skipped = client.post(
            scan, json={"request_id": "skipped", "expected_revision": 3, "target_lufs": -28.0}
        )
        report = skipped.json()["loudness"]
        assert report["measured"] == 2 and report["changed"] == 0, report
        assert "keyframes" in report["clips"][0]["skipped"], report["clips"][0]
        print("   a keyframed volume is skipped by both endpoints:", report["clips"][0]["skipped"])


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-loudness-") as scratch:
        folder = Path(scratch)
        tone(folder / "loud.wav", LOUD)
        tone(folder / "quiet.wav", QUIET)
        measure_suite(folder)
        gain_suite(folder)
        http_suite(folder)
        media_suite(folder)
        track_suite(folder)
    print(
        "PASS: the meter reproduces a known level difference, the suggested gain is the one that",
        "lands on target under a true-peak ceiling, and the exported audio really measures there",
    )


if __name__ == "__main__":
    main()
