"""自动语音字幕 has to work on the comp the editor is inside -- and the words have to reach pixels.

1.74 gave the nine analysis endpoints a `sequence_id`, and `sequence_plan_check.py` measured the
seven write-side tools against real media. 自动字幕 was the one left unproven: the code path is the
same two lines (`sequence_view` in, `sequence_id` on the derived batch) but nothing ever sat a real
Chinese voice inside a composition and asked the engine to listen there. Claiming it from the shape
of the diff is exactly how a green gate hides a shipped bug, so this check measures it:

1. the same clip transcribed outside and inside a composition answers the *same* cues — same text,
   same ticks, same content-derived subtitle track, because it is the same audio;
2. after nesting, the root call is honestly a 404 that names the clip (and the empty same-id track
   names itself too) — it no longer pretends there is nothing to transcribe;
3. `apply` lands one revision inside that composition: the comp gains the 字幕 track and its cue
   clips, the root gains nothing but its container clip, and a dry run previews those cues inside
   the comp while the library stays at the revision it was read at;
4. the content-addressed ids still dedup inside a comp (second run refused DUPLICATE_ID, dry run
   included), and `replace_track_id` regenerates the same track in place there as well;
5. the words reach the exported picture. The plate behind them is 0x404040 grey, so no pixel of the
   footage can read as a glyph: every bright sample comes from the subtitle drawn inside the comp.

Everything here runs against real audio synthesised by the Windows Chinese voice and a real vosk
model on disk, and the export is a real file re-opened with ffprobe.
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
WIDTH, HEIGHT = 320, 180
COMP = "s1"
FRAME = T // 30
OFFSET = 2 * T  # the speech clip sits two seconds into the comp
PLATE_SECONDS = 10


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
            "captions_comp_check needs a Chinese Windows voice (Microsoft Huihui or similar); "
            "install one under Settings > Time & language > Speech"
        )
    assert done.returncode == 0, done.stderr[-400:]


def speech_fixture(folder: Path) -> Path:
    """Two sentences with a full second of silence between them, so a gap split must happen."""
    first, second = folder / "s1.wav", folder / "s2.wav"
    speak(SENTENCES[0], first)
    speak(SENTENCES[1], second)
    gap = folder / "gap.wav"
    assert (
        run(
            [
                FFMPEG,
                "-y",
                "-v",
                "error",
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
            [
                FFMPEG,
                "-y",
                "-v",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                listing,
                "-c:a",
                "pcm_s16le",
                joined,
            ]
        ).returncode
        == 0
    )
    with wave.open(str(joined), "rb") as handle:
        seconds = handle.getnframes() / handle.getframerate()
    assert seconds >= 4.0, seconds
    print(f"   speech fixture: {seconds:.3f} s of real synthesised Chinese")
    return joined


def plate(folder: Path) -> Path:
    """The background for the pixel measurement: flat 0x404040, silent, no audio stream."""
    out = folder / "plate.mp4"
    assert (
        run(
            [
                FFMPEG,
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x404040:s={WIDTH}x{HEIGHT}:r=30:d={PLATE_SECONDS}",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-an",
                out,
            ]
        ).returncode
        == 0
    )
    return out


def service(folder: Path) -> TestClient:
    media = MediaService(
        folder / "db.sqlite3",
        [folder],
        folder / "cache",
        FFMPEG,
        FFPROBE,
        asr_dirs=[MODELS],
    )
    exports = folder / "exports"
    jobs = JobRuntime(folder / "db.sqlite3", FFMPEG, exports, [exports, folder])
    jobs.ensure_worker()
    token = "t" * 32
    app = create_app(folder / "db.sqlite3", token, media=media, jobs=jobs)
    return TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    )


def seed(client: TestClient, speech: Path, plate_path: Path) -> tuple[str, int, float]:
    """Grey picture at 0 s, the voice at 2 s on an audio track; returns (project, revision, len)."""
    voice = client.post("/v1/media/import", json={"path": str(speech)}).json()
    background = client.post("/v1/media/import", json={"path": str(plate_path)}).json()
    project = client.post(
        "/v1/projects",
        json={
            "request_id": "cc-new",
            "name": "合成字幕",
            "settings": {
                "width": WIDTH,
                "height": HEIGHT,
                "frame_rate": {"numerator": 30, "denominator": 1},
            },
        },
    ).json()["project"]
    with wave.open(str(speech), "rb") as handle:
        seconds = handle.getnframes() / handle.getframerate()
    answer = client.post(
        f"/v1/projects/{project['id']}/edits",
        json={
            "request_id": "cc-seed",
            "expected_revision": 0,
            "commands": [
                {"op": "track.add", "track": {"id": "v1", "kind": "video", "name": "画面"}},
                {"op": "track.add", "track": {"id": "a1", "kind": "audio", "name": "声音"}},
                {
                    "op": "asset.import",
                    "asset_id": "bg",
                    "label": "bg",
                    "probe_id": background["id"],
                    "verified": background["verified"],
                },
                {
                    "op": "asset.import",
                    "asset_id": "a",
                    "label": "a",
                    "probe_id": voice["id"],
                    "verified": voice["verified"],
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "v",
                        "asset_id": "bg",
                        "track_id": "v1",
                        "position_ticks": 0,
                        "duration_ticks": PLATE_SECONDS * T,
                    },
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "c",
                        "asset_id": "a",
                        "track_id": "a1",
                        "position_ticks": OFFSET,
                        "duration_ticks": voice["verified"]["duration_ticks"],
                    },
                },
            ],
        },
    )
    assert answer.status_code == 200, answer.text
    return project["id"], answer.json()["project"]["revision"], seconds


def ask(client: TestClient, project_id: str, revision: int, **extra) -> dict:
    body = {"request_id": extra.pop("request_id"), "expected_revision": revision, **extra}
    return client.post(f"/v1/projects/{project_id}/speech-captions", json=body)


def bright_pixels(folder: Path, video: Path, at_seconds: float, floor: int) -> int:
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
                video,
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
        if body[index] > floor and body[index + 1] > floor and body[index + 2] > floor
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        speech = speech_fixture(folder)
        grey = plate(folder)
        with service(folder) as client:
            project_id, revision, seconds = seed(client, speech, grey)

            # What the same clip answers while it still lives on the root timeline.
            outside = ask(
                client, project_id, revision, request_id="cc-outside", clip_id="c", apply=False
            ).json()["speech"]
            root_cues = [
                (cue["from_ticks"], cue["to_ticks"], cue["text"]) for cue in outside["cues"]
            ]
            assert len(root_cues) >= 2, root_cues
            print(
                f"   on the root timeline: {len(root_cues)} cues -- "
                f"{' / '.join(text for _, _, text in root_cues)}"
            )

            # 剪映 puts the shot inside a comp the same way; nesting needs a visible picture clip.
            nested = client.post(
                f"/v1/projects/{project_id}/edits",
                json={
                    "request_id": "cc-nest",
                    "expected_revision": revision,
                    "commands": [
                        {
                            "op": "sequence.nest",
                            "clip_ids": ["c", "v"],
                            "name": "口播",
                            "sequence_id": COMP,
                            "asset_id": "seq",
                            "clip_id": "cn",
                        }
                    ],
                },
            )
            assert nested.status_code == 200, nested.text
            document = nested.json()["project"]
            revision = document["revision"]
            comp = document["sequences"][COMP]
            assert sorted(comp["clips"]) == ["c", "v"], sorted(comp["clips"])
            assert list(document["clips"]) == ["cn"], list(document["clips"])
            assert comp["duration_ticks"] == PLATE_SECONDS * T, comp["duration_ticks"]

            # The root no longer has the clip, and it says so by name instead of transcribing air.
            blind = ask(client, project_id, revision, request_id="cc-blind", clip_id="c")
            assert blind.status_code == 404, blind.text
            assert blind.json()["error"] == {
                "code": "NOT_FOUND",
                "message": "clip is not in this project",
                "details": {"clip_id": "c"},
            }, blind.json()
            blind_track = ask(
                client, project_id, revision, request_id="cc-blind-track", track_id="a1"
            )
            assert blind_track.status_code == 404, blind_track.text
            assert blind_track.json()["error"]["details"] == {"track_id": "a1"}, blind_track.json()
            ghost = ask(
                client, project_id, revision, request_id="cc-ghost", clip_id="c", sequence_id="nope"
            )
            assert ghost.status_code == 404, ghost.text
            # 1.214：不存在的合成现在除了点名是哪个 id，还交出现有的一共几个、各叫什么。
            # 正文加宽是这一轮要收的那笔旧账——钉形状的断言跟着走，不是把名单删掉。
            ghost_details = ghost.json()["error"]["details"]
            assert ghost_details["sequence_id"] == "nope", ghost.json()
            assert [row["name"] for row in ghost_details["known"]], ghost.json()
            print(
                f"   nested (revision {revision}): the root names the clip it cannot find "
                "instead of answering about an empty track"
            )

            # Inside the comp the very same audio has to yield the very same cues.
            inside = ask(
                client,
                project_id,
                revision,
                request_id="cc-inside",
                clip_id="c",
                sequence_id=COMP,
                apply=False,
            )
            assert inside.status_code == 200, inside.text
            plan = inside.json()["speech"]
            inside_cues = [
                (cue["from_ticks"], cue["to_ticks"], cue["text"]) for cue in plan["cues"]
            ]
            assert inside_cues == root_cues, (inside_cues, root_cues)
            assert plan["model"].startswith("vosk-model-"), plan["model"]
            assert plan["command"]["op"] == "captions.import"
            assert plan["command"]["track_id"] == outside["command"]["track_id"], (
                plan["command"],
                outside["command"],
            )
            assert inside.json()["project"]["revision"] == revision  # planning writes nothing
            for cue in inside_cues:
                assert OFFSET <= cue[0] < cue[1] <= OFFSET + int(seconds * T) + FRAME, cue
            text = "".join(cue[2] for cue in inside_cues)
            for phrase in ("大家好", "剪辑", "自动"):
                assert phrase in text, (phrase, text)
            print(
                f"   inside {COMP}: identical cues point for point -- {len(inside_cues)} lines, "
                f"same content-derived track {plan['command']['track_id'][:14]}…"
            )

            # The dry run previews inside the comp; the library stays where it was.
            dry = ask(
                client,
                project_id,
                revision,
                request_id="cc-dry",
                clip_id="c",
                sequence_id=COMP,
                apply=True,
                dry_run=True,
            ).json()
            assert dry["committed"] is False, dry["committed"]
            assert dry["project"]["revision"] == revision + 1, dry["project"]["revision"]
            preview = [
                c
                for c in dry["project"]["sequences"][COMP]["clips"].values()
                if c["track_id"] == plan["command"]["track_id"]
            ]
            assert len(preview) == len(inside_cues), (len(preview), len(inside_cues))
            persisted = client.get(f"/v1/projects/{project_id}").json()
            assert persisted["revision"] == revision
            assert sorted(persisted["sequences"][COMP]["clips"]) == ["c", "v"], sorted(
                persisted["sequences"][COMP]["clips"]
            )
            print(
                f"   dry run previews {len(preview)} cue clips inside {COMP} "
                f"and writes nothing (library still revision {revision})"
            )

            applied = ask(
                client,
                project_id,
                revision,
                request_id="cc-apply",
                clip_id="c",
                sequence_id=COMP,
                apply=True,
            )
            assert applied.status_code == 200, applied.text
            answer = applied.json()
            assert answer["committed"] is True, answer
            after = answer["project"]
            revision = after["revision"]
            assert revision == dry["project"]["revision"]
            landed_comp = after["sequences"][COMP]
            subtitle_tracks = [t for t in landed_comp["tracks"] if t["name"] == "字幕"]
            assert len(subtitle_tracks) == 1, landed_comp["tracks"]
            track_id = subtitle_tracks[0]["id"]
            assert track_id == plan["command"]["track_id"]
            subs = sorted(
                (c for c in landed_comp["clips"].values() if c["track_id"] == track_id),
                key=lambda c: c["position_ticks"],
            )
            assert len(subs) == len(inside_cues), (len(subs), len(inside_cues))
            snapped = parse_srt(plan["command"]["srt"], FRAME)
            assert [(c["position_ticks"], c["duration_ticks"]) for c in subs] == [
                (start, stop - start) for start, stop, _ in snapped
            ], (subs, snapped)
            for clip, (_, _, line) in zip(subs, snapped):
                assert clip["text"]["body"] == line, (clip, line)
                assert clip["position_ticks"] % FRAME == 0, clip
            # Only the comp grew. The root keeps its container and the tracks it already had.
            assert list(after["clips"]) == ["cn"], list(after["clips"])
            assert [(t["id"], t["name"]) for t in after["tracks"]] == [
                (t["id"], t["name"]) for t in document["tracks"]
            ], after["tracks"]
            assert after["clips"]["cn"]["keyframes"] == [], after["clips"]["cn"]["keyframes"]
            print(
                f"   apply inside the comp: 字幕 track {track_id[:14]}… with {len(subs)} cue "
                f"clips, root still holds only ['cn'] (revision {revision})"
            )

            # Content-addressed ids dedup inside a comp exactly as they do on the root.
            again = ask(
                client,
                project_id,
                revision,
                request_id="cc-again",
                clip_id="c",
                sequence_id=COMP,
                apply=True,
            )
            assert again.status_code == 422, again.text
            assert again.json()["error"]["code"] == "DUPLICATE_ID", again.json()
            for wants_dry in (False, True):
                second = ask(
                    client,
                    project_id,
                    revision,
                    request_id=f"cc-second-{wants_dry}",
                    clip_id="c",
                    sequence_id=COMP,
                    apply=True,
                    dry_run=wants_dry,
                )
                assert second.status_code == 422, second.text
                assert second.json()["error"]["code"] == "DUPLICATE_ID", second.json()
            assert client.get(f"/v1/projects/{project_id}").json()["revision"] == revision

            replaced = ask(
                client,
                project_id,
                revision,
                request_id="cc-replace",
                clip_id="c",
                sequence_id=COMP,
                apply=True,
                replace_track_id=track_id,
            )
            assert replaced.status_code == 200, replaced.text
            revision = replaced.json()["project"]["revision"]
            names = [
                t["id"]
                for t in replaced.json()["project"]["sequences"][COMP]["tracks"]
                if t["name"] == "字幕"
            ]
            assert names == [track_id], names
            regenerated = [
                c
                for c in replaced.json()["project"]["sequences"][COMP]["clips"].values()
                if c["track_id"] == track_id
            ]
            assert len(regenerated) == len(subs), (len(regenerated), len(subs))
            print(
                f"   replace_track_id inside the comp: same {len(subs)} cues, one 字幕 track "
                f"again, revision {revision}"
            )

            # The exported picture is the artifact the claim is really about.
            exports = folder / "exports"
            exports.mkdir(exist_ok=True)
            job = client.post(
                f"/v1/projects/{project_id}/renders",
                json={
                    "request_id": "cc-render",
                    "expected_revision": revision,
                    "preset_id": "h264-source-quality",
                    "filename": "comp-captions.mp4",
                    "folder": str(exports),
                },
            )
            assert job.status_code == 200, job.text
            job_id = job.json()["job"]["id"]
            state = {}
            for _ in range(600):
                state = client.get("/v1/jobs/" + job_id).json()["job"]
                if state["status"] in {"succeeded", "failed", "cancelled"}:
                    break
            assert state["status"] == "succeeded", state
            assert state["output_checked"] is True, state["message"]
            landed = Path(state["output_path"])
            info = run(
                [
                    FFPROBE,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-show_entries",
                    "stream=codec_type",
                    "-of",
                    "default=nw=1",
                    landed,
                ]
            ).stdout
            assert "codec_type=video" in info and "codec_type=audio" in info, info
            inside_times = [
                (clip["position_ticks"] + clip["duration_ticks"] // 2) / T for clip in subs
            ]
            gaps = [
                (
                    subs[index]["position_ticks"]
                    + subs[index]["duration_ticks"]
                    + subs[index + 1]["position_ticks"]
                )
                / 2
                / T
                for index in range(len(subs) - 1)
            ]
            seen = {}
            for label, moment in [
                ("lead-in", 0.3),
                *[("cue" + str(n), at) for n, at in enumerate(inside_times)],
                *[("gap" + str(n), at) for n, at in enumerate(gaps)],
                ("tail", PLATE_SECONDS - 0.4),
            ]:
                seen[label] = (
                    bright_pixels(folder, landed, moment, 200),
                    bright_pixels(folder, landed, moment, 235),
                )
            print(
                f"   export {landed.name}: "
                + ", ".join(f"{k}={v[0]}/{v[1]}" for k, v in seen.items())
                + " (pixels >200 / >235)"
            )
            for label in ("lead-in", "tail"):
                assert seen[label] == (0, 0), (label, seen[label])
            for index in range(len(gaps)):
                assert seen["gap" + str(index)] == (0, 0), (index, seen)
            for number in range(len(inside_times)):
                # Measured on this fixture: 55 and 30 glyph pixels above 200, 11 and 3 above 235.
                assert seen["cue" + str(number)][0] >= 20, (number, seen)
                assert seen["cue" + str(number)][1] > 0, (number, seen)
            print(
                f"   measured: glyphs on {len(inside_times)} of {len(subs)} cues, "
                f"0 bright pixels in the {len(gaps) + 2} empty windows"
            )


if __name__ == "__main__":
    main()
