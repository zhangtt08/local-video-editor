"""Automatic speech captions: a local model listens, the ordinary importer lands the text.

The speech recognition is vosk with the small Chinese model from `desktop/resources/asr` — a real
model on disk, not a stub. The check synthesises real speech with the Windows SAPI voice, so what
the engine hears is actual Chinese audio rather than a fixture. It proves four things:

1. the cues the engine returns carry real recognised text and fall inside the clip, on the frame
   grid once the importer snaps them;
2. `apply` lands one revision through the ordinary `captions.import` command — replay returns the
   same revision, an old expected_revision is refused, dry-run writes nothing — and a real export
   actually shows the subtitle pixels on screen;
3. refusal cases say why: a clip without audio, a speed curve, both/neither target, no speech, and
   a language whose model is not on disk;
4. a 200% clip maps source seconds onto half as many timeline ticks, so the text lands where the
   editor hears it.
"""

import subprocess
import tempfile
import textwrap
import wave
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService
from agentcut.subtitles import parse_srt

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
MODELS = ROOT / "desktop/resources/asr"
SENTENCES = ["大家好，欢迎来到剪辑教学。", "今天我们学习自动字幕。"]
SECONDS = 9.0


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


def speak(text: str, path: Path) -> None:
    """One Chinese sentence through the Windows voice, 48 kHz mono — real speech, not a fixture."""
    script = textwrap.dedent(
        f"""
        Add-Type -AssemblyName System.Speech
        $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
        $voices = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -like 'zh*' }}
        if (-not $voices) {{ Write-Host 'NO ZH VOICE'; exit 2 }}
        $s.SelectVoice(($voices | Select-Object -First 1).VoiceInfo.Name)
        $fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
            48000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
            [System.Speech.AudioFormat.AudioChannel]::Mono)
        $s.SetOutputToWaveFile('{path.as_posix()}', $fmt)
        $s.Speak('{text}')
        $s.Dispose()
        """
    )
    done = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        creationflags=0x08000000,
    )
    if done.returncode == 2 or "NO ZH VOICE" in done.stdout:
        raise SystemExit(
            "asr_check needs a Chinese Windows voice (Microsoft Huihui or similar); "
            "install one under Settings > Time & language > Speech"
        )
    assert done.returncode == 0, done.stderr[-400:]
    assert path.is_file() and path.stat().st_size > 44_100 * 4, path.stat()


def speech_fixture(folder: Path) -> Path:
    """Two sentences separated by a full second of silence, so a gap split must happen."""
    first, second = folder / "s1.wav", folder / "s2.wav"
    speak(SENTENCES[0], first)
    speak(SENTENCES[1], second)
    gap = folder / "gap.wav"
    assert (
        run(
            [
                FFMPEG,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000:cl=mono",
                "-t",
                "1.0",
                "-c:a",
                "pcm_s16le",
                gap,
            ]
        ).returncode
        == 0
    )
    joined = folder / "speech.wav"
    listing = folder / "join.txt"
    listing.write_text(
        f"file '{first.as_posix()}'\nfile '{gap.as_posix()}'\nfile '{second.as_posix()}'\n",
        encoding="utf-8",
    )
    assert (
        run(
            [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", listing, "-c:a", "pcm_s16le", joined]
        ).returncode
        == 0
    )
    with wave.open(str(joined), "rb") as handle:
        duration = handle.getnframes() / handle.getframerate()
    assert duration >= 4.0, duration
    return joined


def service(folder: Path, model_dirs: list[Path]):
    media = MediaService(
        folder / "db.sqlite3", [folder], folder / "cache", FFMPEG, FFPROBE, asr_dirs=model_dirs
    )
    exports = folder / "exports"
    jobs = JobRuntime(folder / "db.sqlite3", FFMPEG, exports, [exports, folder])
    jobs.ensure_worker()
    token = "t" * 32
    app = create_app(folder / "db.sqlite3", token, media=media, jobs=jobs)
    return TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    )


def seed_project(client: TestClient, source: Path, *, position=0, speed=None, tag=""):
    """One audio clip on an audio track; returns (project, clip_id, revision, probe)."""
    probe = client.post("/v1/media/import", json={"path": str(source)}).json()
    created = client.post(
        "/v1/projects",
        json={
            "request_id": f"asr-new-{position}{tag}",
            "name": f"asr{position}{tag}",
            "settings": {
                "width": 320,
                "height": 180,
                "frame_rate": {"numerator": 30, "denominator": 1},
            },
        },
    ).json()["project"]
    duration = probe["verified"]["duration_ticks"]
    commands = [
        {"op": "track.add", "track": {"id": "a1", "kind": "audio", "name": "声音"}},
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
                "track_id": "a1",
                "position_ticks": position,
                "duration_ticks": duration,
            },
        },
    ]
    if speed:
        commands.append({"op": "clip.speed", "clip_id": "c", "speed_percent": speed})
    seeded = client.post(
        f"/v1/projects/{created['id']}/edits",
        json={
            "request_id": f"asr-seed-{position}{tag}",
            "expected_revision": 0,
            "commands": commands,
        },
    )
    assert seeded.status_code == 200, seeded.text
    return created, seeded.json()["project"]["revision"], probe


def cue_suite(folder: Path, source: Path) -> tuple[list[dict], str]:
    with service(folder, [MODELS]) as client:
        project, revision, _ = seed_project(client, source, position=2 * T)
        url = f"/v1/projects/{project['id']}/speech-captions"

        missing = client.post(url, json={"request_id": "x1", "expected_revision": revision})
        assert missing.status_code == 422 and missing.json()["error"]["code"] == "INVALID_REQUEST"
        both = client.post(
            url,
            json={
                "request_id": "x2",
                "expected_revision": revision,
                "clip_id": "c",
                "track_id": "a1",
            },
        )
        assert both.status_code == 422 and both.json()["error"]["code"] == "INVALID_REQUEST"

        planned = client.post(
            url, json={"request_id": "asr-plan", "expected_revision": revision, "clip_id": "c"}
        )
        assert planned.status_code == 200, planned.text
        body = planned.json()
        speech = body["speech"]
        assert body["committed"] is False
        cues = speech["cues"]
        assert len(cues) >= 2, cues  # a full second of silence must split the lines
        text = "".join(cue["text"] for cue in cues)
        for phrase in ("大家好", "剪辑", "自动"):
            assert phrase in text, (phrase, text)
        for cue in cues:
            assert 2 * T <= cue["from_ticks"] < cue["to_ticks"] <= 2 * T + int(SECONDS * T), cue
            assert cue["to_ticks"] - cue["from_ticks"] >= T // 30
        first_start = min(cues, key=lambda c: c["from_ticks"])["from_ticks"]
        assert first_start < 2 * T + T, first_start / T  # speech starts right away
        assert speech["model"].startswith("vosk-model-"), speech["model"]
        # the planned command is the importer's own; its SRT re-parses to the same snapped cues
        command = speech["command"]
        assert command["op"] == "captions.import", command["op"]
        snapped = parse_srt(command["srt"], T // 30)
        assert len(snapped) == len(cues), (len(snapped), len(cues))
        assert body["project"]["revision"] == revision  # planning writes nothing

        # A dry run of the apply shows the prospective revision without persisting anything.
        dry = client.post(
            url,
            json={
                "request_id": "asr-dry",
                "expected_revision": revision,
                "clip_id": "c",
                "apply": True,
                "dry_run": True,
            },
        ).json()
        assert dry["committed"] is False, dry["committed"]
        assert dry["project"]["revision"] == revision + 1, dry["project"]["revision"]
        assert client.get(f"/v1/projects/{project['id']}").json()["revision"] == revision

        applied = client.post(
            url,
            json={
                "request_id": "asr-apply",
                "expected_revision": revision,
                "clip_id": "c",
                "apply": True,
            },
        ).json()
        assert applied["committed"] is True, applied
        assert applied["project"]["revision"] == revision + 1
        subtitle_tracks = [t for t in applied["project"]["tracks"] if t["name"] == "字幕"]
        assert len(subtitle_tracks) == 1, applied["project"]["tracks"]
        track_id = subtitle_tracks[0]["id"]
        landed = [c for c in applied["project"]["clips"].values() if c["track_id"] == track_id]
        assert len(landed) == len(cues), (len(landed), len(cues))
        replay = client.post(
            url,
            json={
                "request_id": "asr-apply",
                "expected_revision": revision,
                "clip_id": "c",
                "apply": True,
            },
        ).json()
        assert replay["project"]["revision"] == revision + 1, replay["project"]["revision"]
        assert replay["replayed"] is True, replay

        stale = client.post(
            url,
            json={
                "request_id": "asr-stale",
                "expected_revision": revision - 1,
                "clip_id": "c",
                "apply": True,
            },
        )
        assert stale.status_code == 409, stale.status_code
        # The same speech under a different request maps to the same content-derived ids, so the
        # reducer refuses the second import instead of stacking an identical track — including its
        # dry run, which honestly reports that the batch would not go through.
        for wants_dry in (False, True):
            second = client.post(
                url,
                json={
                    "request_id": f"asr-second-{wants_dry}",
                    "expected_revision": revision + 1,
                    "clip_id": "c",
                    "apply": True,
                    "dry_run": wants_dry,
                },
            )
            assert second.status_code == 422, second.status_code
            assert second.json()["error"]["code"] == "DUPLICATE_ID", second.json()
        assert client.get(f"/v1/projects/{project['id']}").json()["revision"] == revision + 1

        # Re-running with replace_track_id swaps the old subtitle track out in the same batch.
        replaced = client.post(
            url,
            json={
                "request_id": "asr-replace",
                "expected_revision": revision + 1,
                "clip_id": "c",
                "apply": True,
                "replace_track_id": track_id,
            },
        ).json()
        assert replaced["committed"] is True, replaced
        assert replaced["project"]["revision"] == revision + 2, replaced["project"]["revision"]
        # Content-derived ids mean the replace regenerates the same track id and clip ids in
        # place — one subtitle track before, one after, and exactly the same cue count on it.
        names = [t["id"] for t in replaced["project"]["tracks"] if t["name"] == "字幕"]
        assert names == [track_id] == [replaced["speech"]["command"]["track_id"]], names
        regenerated = [
            c for c in replaced["project"]["clips"].values() if c["track_id"] == track_id
        ]
        assert len(regenerated) == len(landed), (len(regenerated), len(landed))
        return replaced, revision + 2


def export_suite(folder: Path, project: dict, revision: int) -> None:
    """The generated captions must reach the picture: white glyphs over the black background.

    The timeline is audio-only, so every bright pixel in the export comes from the subtitle text:
    one frame during the first cue must glow, one frame inside the inter-sentence gap must not.
    """
    exports = folder / "exports"
    exports.mkdir(exist_ok=True)
    with service(folder, [MODELS]) as client:
        job = client.post(
            f"/v1/projects/{project['id']}/renders",
            json={
                "request_id": "asr-render",
                "expected_revision": revision,
                "preset_id": "h264-source-quality",
                "filename": "asr.mp4",
                "folder": str(exports),
            },
        )
        assert job.status_code == 200, job.text
        job_id = job.json()["job"]["id"]
        for _ in range(600):
            state = client.get("/v1/jobs/" + job_id).json()["job"]
            if state["status"] in {"succeeded", "failed", "cancelled"}:
                break
    assert state["status"] == "succeeded", state
    assert state["output_checked"] is True, state["message"]
    landed = Path(state["output_path"])

    def bright_pixels(at_seconds: float) -> int:
        raw = folder / "frame.rgb"
        assert (
            run(
                [
                    FFMPEG,
                    "-y",
                    "-v",
                    "error",
                    "-ss",
                    f"{at_seconds:.3f}",
                    "-i",
                    landed,
                    "-frames:v",
                    "1",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    raw,
                ]
            ).returncode
            == 0
        )
        body = raw.read_bytes()
        return sum(
            1
            for index in range(0, len(body), 3)
            if body[index] > 235 and body[index + 1] > 235 and body[index + 2] > 235
        )

    # The clip sits at 2 s on the timeline: 0.6 s is the empty lead-in, 2.5 s is inside cue one.
    during = bright_pixels(2.5)
    lead_in = bright_pixels(0.6)
    assert during > 10, during  # glyph cores on a 320x180 frame; the lead-in measures 0
    assert lead_in == 0, lead_in


def refusal_suite(folder: Path, silent_source: Path) -> None:
    with service(folder, [MODELS]) as client:
        project, revision, _ = seed_project(client, silent_source, position=0, tag="quiet")
        answer = client.post(
            f"/v1/projects/{project['id']}/speech-captions",
            json={"request_id": "asr-quiet", "expected_revision": revision, "clip_id": "c"},
        )
        assert answer.status_code == 422, answer.text
        problem = answer.json()["error"]
        assert problem["code"] == "SPEECH_NOT_FOUND", problem
        assert "no speech" in problem["message"], problem

        curve = client.post(
            f"/v1/projects/{project['id']}/edits",
            json={
                "request_id": "asr-curve",
                "expected_revision": revision,
                "commands": [
                    {
                        "op": "clip.speed_curve",
                        "clip_id": "c",
                        "points": [
                            {"at_ticks": 0, "percent": 100},
                            {"at_ticks": int(2 * T), "percent": 50},
                        ],
                    }
                ],
            },
        )
        assert curve.status_code == 200, curve.text
        refused = client.post(
            f"/v1/projects/{project['id']}/speech-captions",
            json={
                "request_id": "asr-curve-scan",
                "expected_revision": revision + 1,
                "clip_id": "c",
            },
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["error"]["code"] == "INVALID_CAPTIONS_TARGET", refused.json()
        assert "speed curve" in refused.json()["error"]["message"]

    # A language whose model is absent is refused by name, not silently degraded.
    with service(folder, [folder / "empty-models"]) as client:
        project, revision, _ = seed_project(client, silent_source, position=0, tag="en")
        (folder / "empty-models").mkdir()
        answer = client.post(
            f"/v1/projects/{project['id']}/speech-captions",
            json={
                "request_id": "asr-en",
                "expected_revision": revision,
                "clip_id": "c",
                "language": "en",
            },
        )
        assert answer.status_code == 422, answer.text
        assert answer.json()["error"]["code"] == "SUBTITLES_MODEL_MISSING", answer.json()
        caps = client.get("/v1/capabilities").json()["features"]
        assert caps["speech_captions"] is False, caps


def speed_suite(folder: Path, source: Path) -> None:
    """At 200%, recognised speech lands in half the timeline time; the words stay the same."""
    with service(folder, [MODELS]) as client:
        project, revision, _ = seed_project(client, source, position=0)
        normal = client.post(
            f"/v1/projects/{project['id']}/speech-captions",
            json={"request_id": "asr-speed-base", "expected_revision": revision, "clip_id": "c"},
        ).json()["speech"]["cues"]
        fast, fast_revision, _ = seed_project(client, source, position=0, speed=200, tag="fast")
        quick = client.post(
            f"/v1/projects/{fast['id']}/speech-captions",
            json={
                "request_id": "asr-speed-fast",
                "expected_revision": fast_revision,
                "clip_id": "c",
            },
        ).json()["speech"]["cues"]
        assert quick, quick
        text_normal = "".join(cue["text"] for cue in normal)
        text_fast = "".join(cue["text"] for cue in quick)
        assert text_normal == text_fast, (text_normal, text_fast)
        duration = max(cue["to_ticks"] for cue in normal)
        duration_fast = max(cue["to_ticks"] for cue in quick)
        expected = duration / 2
        assert abs(duration_fast - expected) < 0.35 * T, (duration_fast / T, expected / T)


def main() -> None:

    with tempfile.TemporaryDirectory(prefix="agentcut-asr-") as scratch:
        folder = Path(scratch)
        source = speech_fixture(folder)
        quiet = folder / "quiet.wav"
        assert (
            run(
                [
                    FFMPEG,
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=48000:cl=mono",
                    "-t",
                    "3",
                    "-c:a",
                    "pcm_s16le",
                    quiet,
                ]
            ).returncode
            == 0
        )
        applied, applied_revision = cue_suite(folder, source)
        export_suite(folder, applied["project"], applied_revision)
        refusal_suite(folder, quiet)
        speed_suite(folder, source)
    print(
        "PASS: a local model turned real Chinese speech into a subtitle track through the ordinary "
        "importer — timings fall inside the clip (half at 200%), one apply is one undoable "
        "revision, the text reaches a real export, and every refusal names its reason"
    )


if __name__ == "__main__":
    main()
