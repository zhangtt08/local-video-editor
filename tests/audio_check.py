"""Audio-only delivery: `codec=None` has to mean *no picture is compiled at all*, and the mix that
comes out has to be the same authoritative mix the video presets use — master gain, ducking, limiter
and all. Three layers of evidence:

1. contract + argv: an audio preset gets `-vn`, no `-c:v`, no `-pix_fmt`, no `-movflags`, and the
   container suffix rule follows it (`.mp3` / `.wav` / `.flac`).
2. graph: the compiled plan carries no scale/pad/overlay/`[vout]` stage and maps exactly one stream,
   and a timeline with nothing audible is refused by name rather than producing a silent file.
3. real exports through the job worker: ffprobe says one audio stream of the right codec and length,
   both tones are measurable in it, and its integrated loudness matches the H.264 export of the same
   revision — so the deliverable is the reviewed mix, not a re-guess of it.
"""

import json
import math
import re
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import OUTPUT_CONTAINERS, render_presets
from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService
from agentcut.render import compile_render_plan, output_args

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SRC_W, SRC_H = 320, 180
SECONDS = 3.0
TALK = 440.0
MUSIC = 220.0
# container, the encoder the preset names, the codec tag ffprobe reports, and the bitrate if any
# (libmp3lame encodes, ffprobe reports "mp3" — the two vocabularies are not the same).
AUDIO_PRESETS = {
    "audio-mp3": ("mp3", "libmp3lame", "mp3", "192k"),
    "audio-wav": ("wav", "pcm_s24le", "pcm_s24le", None),
    "audio-flac": ("flac", "flac", "flac", None),
}


def run(args, timeout=600):
    done = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=0x08000000)
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-600:]
    return done.stdout


def tone_source(folder: Path) -> Path:
    """A picture with a 440 Hz voice on it: the audio-only export must keep the voice."""
    target = folder / "talk.mp4"
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
            f"color=c=0x303030:s={SRC_W}x{SRC_H}:r=30:d={SECONDS}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={TALK}:sample_rate=48000:duration={SECONDS}",
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
            "-b:a",
            "192k",
            "-shortest",
            str(target),
        ]
    )
    return target


def music_source(folder: Path) -> Path:
    target = folder / "music.wav"
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
            f"sine=frequency={MUSIC}:sample_rate=48000:duration={SECONDS}",
            "-af",
            "volume=0.5",
            str(target),
        ]
    )
    return target


def silent_source(folder: Path) -> Path:
    """Video with no sound at all: an audio deliverable has nothing to export from this."""
    target = folder / "quiet.mp4"
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
            f"color=c=0x202020:s={SRC_W}x{SRC_H}:r=30:d=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(target),
        ]
    )
    return target


def project_payload(
    clips: list[Path], extra_audio: Path | None = None, overlay: Path | None = None
):
    from agentcut.contracts import Project, VerifiedMedia
    from agentcut.timeline import validate_timeline

    def verified(path: Path, index: int) -> dict:
        info = json.loads(
            run(
                [
                    str(FFPROBE),
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(path),
                ]
            )
        )
        video = next((row for row in info["streams"] if row["codec_type"] == "video"), None)
        audio = next((row for row in info["streams"] if row["codec_type"] == "audio"), None)
        return VerifiedMedia.model_validate(
            {
                "probe_id": f"a{index}",
                "path": str(path),
                "kind": "video" if video else "audio",
                "label": path.stem,
                "size_bytes": path.stat().st_size,
                "content_sha256": "0" * 64,
                "duration_ticks": int(float(info["format"]["duration"]) * T),
                "width": int(video["width"]) if video else SRC_W,
                "height": int(video["height"]) if video else SRC_H,
                "has_audio": audio is not None,
            }
        ).model_dump()

    tracks = [{"id": "v", "kind": "video", "name": "画面"}]
    assets = {}
    timeline_clips = {}
    for index, path in enumerate(clips):
        assets[f"a{index}"] = {
            "id": f"a{index}",
            "kind": "video",
            "label": path.stem,
            "reference": "r",
            "duration_ticks": int(SECONDS * T),
            "verified": verified(path, index),
        }
        timeline_clips[f"c{index}"] = {
            "id": f"c{index}",
            "asset_id": f"a{index}",
            "track_id": "v",
            "position_ticks": 0,
            "duration_ticks": int(SECONDS * T),
            "effects": {"x": 0, "y": 0, "scale": 1, "rotation": 0, "opacity": 1},
        }
    if extra_audio is not None:
        tracks.append({"id": "a", "kind": "audio", "name": "配乐"})
        assets["am"] = {
            "id": "am",
            "kind": "audio",
            "label": "music",
            "reference": "r",
            "duration_ticks": int(SECONDS * T),
            "verified": verified(extra_audio, 9),
        }
        timeline_clips["cm"] = {
            "id": "cm",
            "asset_id": "am",
            "track_id": "a",
            "position_ticks": 0,
            "duration_ticks": int(SECONDS * T),
        }
    if overlay is not None:
        # A second picture track whose clip carries no sound: the audio-only plan must not even
        # open this file, which is what separates "not mapped" from "never decoded".
        tracks.append({"id": "v2", "kind": "video", "name": "上层"})
        assets["ov"] = {
            "id": "ov",
            "kind": "video",
            "label": overlay.stem,
            "reference": "r",
            "duration_ticks": int(SECONDS * T),
            "verified": verified(overlay, 7),
        }
        timeline_clips["co"] = {
            "id": "co",
            "asset_id": "ov",
            "track_id": "v2",
            "position_ticks": 0,
            "duration_ticks": int(SECONDS * T),
        }
    project = Project.model_validate(
        {
            "id": "p",
            "name": "audio",
            "settings": {
                "width": SRC_W,
                "height": SRC_H,
                "frame_rate": {"numerator": 30, "denominator": 1},
            },
            "tracks": tracks,
            "assets": assets,
            "clips": timeline_clips,
        }
    )
    validate_timeline(project)
    return project


def amplitude(path: Path, frequency: float, from_seconds: float = 1.0) -> float:
    raw = run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            "48000",
            "-f",
            "s16le",
            "-",
        ],
        timeout=300,
    )
    samples = [
        int.from_bytes(raw[i : i + 2], "little", signed=True) for i in range(0, len(raw) - 1, 2)
    ]
    start = int(from_seconds * 48000)
    window = samples[start : start + 4096]
    step = 2 * math.pi * frequency / 48000
    real = sum(v * math.cos(step * i) for i, v in enumerate(window))
    imag = sum(v * math.sin(step * i) for i, v in enumerate(window))
    return 2 * math.hypot(real, imag) / len(window) / 32768


def lufs(path: Path) -> float:
    text = subprocess.run(
        [str(FFMPEG), "-i", str(path), "-filter_complex", "ebur128", "-f", "null", "-"],
        capture_output=True,
        timeout=300,
        creationflags=0x08000000,
    ).stderr.decode(errors="replace")
    summary = text.rsplit("Summary:", 1)[-1]
    match = re.search(r"I:\s*(-?[\d.]+)\s*LUFS", summary)
    assert match, text[-600:]
    return float(match.group(1))


def streams(path: Path) -> list[dict]:
    data = json.loads(
        run(
            [
                str(FFPROBE),
                "-v",
                "error",
                "-show_entries",
                "stream=index,codec_type,codec_name,sample_rate,channels:format=format_name,duration",
                "-of",
                "json",
                str(path),
            ]
        )
    )
    return data["streams"], data["format"]


def contract_suite() -> None:
    presets = {item["id"]: item for item in render_presets()}
    for preset_id, (container, audio_codec, _tag, bitrate) in AUDIO_PRESETS.items():
        row = presets[preset_id]
        assert row["codec"] is None and row["scale"] is None, row
        assert row["pixel_format"] is None, row
        assert row["container"] == container and row["audio_codec"] == audio_codec, row
        assert row["container"] in OUTPUT_CONTAINERS, row
        args = output_args(row, 48000, 30.0)
        joined = " ".join(args)
        assert "-vn" in args, joined
        assert "-c:v" not in joined and "-pix_fmt" not in joined, joined
        assert "-movflags" not in joined, joined
        assert f"-c:a {audio_codec}" in joined, joined
        assert (f"-b:a {bitrate}" in joined) if bitrate else ("-b:a" not in joined), joined
        assert "-ar 48000 -ac 2" in joined, joined
    # A video preset must not pick up the audio-only shape, nor an audio name a video file.
    video = " ".join(output_args(presets["h264-1080p"], 48000, 30.0))
    assert "-vn" not in video and "-c:v libx264" in video, video
    print(
        f"   {len(presets)} presets: {sorted(AUDIO_PRESETS)} carry no picture "
        "(-vn, no -c:v, no -pix_fmt, no -movflags)"
    )


def graph_suite(folder: Path) -> None:
    talk = tone_source(folder)
    music = music_source(folder)
    quiet = silent_source(folder)
    project = project_payload([talk], extra_audio=music, overlay=quiet)
    audio = compile_render_plan(project, "audio-mp3")
    video = compile_render_plan(project, "h264-source-quality")
    assert audio.mode == "audio", audio.mode
    assert audio.video_label == "", audio.video_label
    assert audio.audio_label == "[aout]", audio.audio_label
    chain = ";".join(audio.filters)
    for token in ("scale=", "pad=", "overlay", "concat=n=", "[vout]", "geq=", "drawtext"):
        assert token not in chain, (token, chain[:400])
    argv = " ".join(audio.ffmpeg_argv("ffmpeg", "out.mp3"))
    assert argv.count("-map") == 1 and "[aout]" in argv, argv
    assert "-vn" in argv, argv
    # The picture chain is not merely unmapped: the silent overlay is never even opened as an input,
    # while the video preset has to decode it. That is the difference between a fast MP3 and a
    # full render whose picture is thrown away at the muxer.
    audio_inputs = " ".join(audio.input_args)
    video_inputs = " ".join(video.input_args)
    assert str(quiet) not in audio_inputs, audio.input_args
    assert str(quiet) in video_inputs, "the video preset must still open the picture-only clip"
    assert str(talk) in audio_inputs and str(music) in audio_inputs, audio.input_args
    assert audio.input_args.count("-i") == 3, (
        audio.input_args
    )  # anullsrc base + the two audible files
    assert len(audio.filters) < len(video.filters), (len(audio.filters), len(video.filters))
    assert any("scale=" in stage for stage in video.filters), video.filters
    print(
        f"   audio plan: {len(audio.filters)} filter stages and 3 inputs vs "
        f"{len(video.filters)} stages for the video preset — the silent clip is never opened"
    )

    quiet = project_payload([silent_source(folder)])
    try:
        compile_render_plan(quiet, "audio-wav")
    except Exception as error:  # noqa: BLE001 - the point is the named refusal
        assert getattr(error, "code", None) == "EMPTY_TIMELINE", type(error).__name__
        assert "audible" in str(error), str(error)
    else:
        raise AssertionError("a picture-only timeline produced an audio deliverable")
    # The same timeline still renders as a picture, so the refusal is about audio, not the cut.
    assert compile_render_plan(quiet, "h264-source-quality").video_label == "[vout]"
    print("   a silent picture timeline is refused for audio by name, and still renders as video")


def wait(client: TestClient, job_id: str) -> dict:
    status = {}
    for _ in range(900):
        status = client.get("/v1/jobs/" + job_id).json()
        if status["job"]["status"] in {"succeeded", "failed", "cancelled"}:
            break
    return status["job"]


def media_suite(folder: Path) -> None:
    media = MediaService(folder / "aud-db.sqlite3", [folder], folder / "aud-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "aud-api.sqlite3", FFMPEG, folder / "exports", [folder / "exports", folder]
    )
    runtime.ensure_worker()
    token = "audcheck" + "e" * 56
    app = create_app(folder / "aud-api.sqlite3", token, media=media, jobs=runtime)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        caps = client.get("/v1/capabilities").json()
        assert caps["features"]["audio_delivery"] is True, caps["features"]
        assert "mp3" in caps["output_containers"] and "wav" in caps["output_containers"], caps
        talk = tone_source(folder)
        music = music_source(folder)
        probes = {
            name: client.post("/v1/media/import", json={"path": str(path)}).json()
            for name, path in (("talk", talk), ("music", music))
        }
        created = client.post(
            "/v1/projects",
            json={
                "request_id": "new",
                "name": "audio",
                "settings": {
                    "width": SRC_W,
                    "height": SRC_H,
                    "frame_rate": {"numerator": 30, "denominator": 1},
                },
            },
        ).json()["project"]
        path = f"/v1/projects/{created['id']}"
        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "seed",
                "expected_revision": 0,
                "commands": [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
                    {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "配乐"}},
                    {
                        "op": "asset.import",
                        "asset_id": "tv",
                        "label": "口播",
                        "probe_id": probes["talk"]["id"],
                        "verified": probes["talk"]["verified"],
                    },
                    {
                        "op": "asset.import",
                        "asset_id": "ma",
                        "label": "配乐",
                        "probe_id": probes["music"]["id"],
                        "verified": probes["music"]["verified"],
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "c1",
                            "asset_id": "tv",
                            "track_id": "v",
                            "position_ticks": 0,
                            "duration_ticks": int(SECONDS * T),
                        },
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "c2",
                            "asset_id": "ma",
                            "track_id": "a",
                            "position_ticks": 0,
                            "duration_ticks": int(SECONDS * T),
                        },
                    },
                ],
            },
        )
        assert seeded.status_code == 200, seeded.text
        revision = seeded.json()["project"]["revision"]

        # The suffix belongs to the container: an .mp4 name cannot carry an MP3, and the other way
        # round an .mp3 name cannot carry the video preset.
        for preset_id, wrong, wanted in (
            ("audio-mp3", "x.mp4", ".mp3"),
            ("h264-1080p", "x.mp3", ".mp4"),
        ):
            clash = client.post(
                path + "/renders",
                json={
                    "request_id": f"clash-{preset_id}",
                    "expected_revision": revision,
                    "preset_id": preset_id,
                    "filename": wrong,
                },
            )
            assert clash.status_code == 422, clash.text
            assert wanted in clash.text, clash.text
        print("   .mp4 cannot carry an MP3 preset and .mp3 cannot carry a video preset")

        outputs = {}
        for index, preset_id in enumerate(("h264-source-quality", *sorted(AUDIO_PRESETS))):
            container = {
                "h264-source-quality": "mp4",
                "audio-mp3": "mp3",
                "audio-flac": "flac",
                "audio-wav": "wav",
            }[preset_id]
            job = client.post(
                path + "/renders",
                json={
                    "request_id": f"ship{index}",
                    "expected_revision": revision,
                    "preset_id": preset_id,
                    "filename": f"混音-{preset_id}.{container}",
                },
            )
            assert job.status_code == 200, job.text
            summary = wait(client, job.json()["job"]["id"])
            assert summary["status"] == "succeeded", summary
            out = Path(summary["output_path"])
            outputs[preset_id] = out
            rows, fmt = streams(out)
            assert abs(float(fmt["duration"]) - SECONDS) <= 0.12, (preset_id, fmt["duration"])
            if preset_id == "h264-source-quality":
                assert fmt["format_name"].startswith("mov"), fmt
                continue
            # The demuxer name is the container the file really is, not the asked-for extension.
            assert fmt["format_name"] == AUDIO_PRESETS[preset_id][0], (preset_id, fmt)
            assert [row["codec_type"] for row in rows] == ["audio"], (preset_id, rows)
            row = rows[0]
            assert row["codec_name"] == AUDIO_PRESETS[preset_id][2], (preset_id, row)
            assert int(row["sample_rate"]) == 48000 and int(row["channels"]) == 2, row
            assert out.stat().st_size > 1000, out
            print(
                f"   {preset_id}: {row['codec_name']} {row['sample_rate']}Hz×{row['channels']}, "
                f"{float(fmt['duration']):.3f}s, {out.stat().st_size} B, one stream only"
            )

        for preset_id in sorted(AUDIO_PRESETS):
            talk_level = amplitude(outputs[preset_id], TALK)
            music_level = amplitude(outputs[preset_id], MUSIC)
            assert talk_level > 0.03 and music_level > 0.01, (preset_id, talk_level, music_level)
        print(
            f"   both sources are in the mix: 440 Hz {amplitude(outputs['audio-mp3'], TALK):.3f} "
            f"and 220 Hz {amplitude(outputs['audio-mp3'], MUSIC):.3f} on the MP3"
        )

        video_lufs = lufs(outputs["h264-source-quality"])
        for preset_id in sorted(AUDIO_PRESETS):
            measured = lufs(outputs[preset_id])
            assert abs(measured - video_lufs) <= 0.6, (preset_id, measured, video_lufs)
            print(
                f"   {preset_id} measures {measured:+.1f} LUFS vs the video export's "
                f"{video_lufs:+.1f}"
            )

        settings = seeded.json()["project"]["settings"]
        marked = client.post(
            path,
            json={
                "request_id": "marks",
                "expected_revision": revision,
                "settings": {**settings, "in_ticks": int(1.0 * T), "out_ticks": int(2.0 * T)},
            },
        )
        assert marked.status_code == 200, marked.text
        window = marked.json()["project"]["revision"]
        job = client.post(
            path + "/renders",
            json={
                "request_id": "range-mp3",
                "expected_revision": window,
                "preset_id": "audio-mp3",
                "filename": "区间.mp3",
                "range": "marks",
            },
        )
        assert job.status_code == 200, job.text
        summary = wait(client, job.json()["job"]["id"])
        assert summary["status"] == "succeeded", summary
        _, fmt = streams(Path(summary["output_path"]))
        assert abs(float(fmt["duration"]) - 1.0) <= 0.12, fmt
        print(f"   区间音频导出实测 {float(fmt['duration']):.3f} 秒，对入出点之间的 1.000 秒")


def main() -> None:
    import tempfile

    contract_suite()
    with tempfile.TemporaryDirectory(prefix="agentcut-audio-") as scratch:
        folder = Path(scratch)
        graph_suite(folder)
        media_suite(folder)
    print(
        "PASS: MP3/WAV/FLAC deliverables compile no picture at all, carry one audio stream of the "
        "right codec, hold both sources, and land on the same loudness as the video export"
    )


if __name__ == "__main__":
    main()
