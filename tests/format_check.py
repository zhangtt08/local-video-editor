"""Delivery formats: a preset names a container and a codec pair, and the file that lands on disk
has to be that stream in that wrapper — measured with ffprobe on the real export, not read off the
filter string. Three things get proven here:

1. the closed vocabulary. Every preset names a container/codec/audio codec the engine knows, and
   each codec's FFmpeg arguments are the ones that encoder actually accepts (VP9 refuses `-preset`
   and needs `-b:v 0`, ProRes takes neither, PCM has no bitrate, `-movflags` is mp4/mov only).
2. the sampling format is threaded through the picture chain, not just the encoder flag: the same
   timeline exported as ProRes 4:4:4 keeps a chroma edge one pixel wide where the H.264 4:2:0 export
   spreads it, measured on the decoded frame.
3. the contract's suffix rule follows the preset, so a `.mp4` name cannot be used to deliver a
   WebM track set, and the file that is written is probeable end to end with sound intact.
"""

import json
import math
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import (
    OUTPUT_AUDIO_CODECS,
    OUTPUT_CODECS,
    OUTPUT_CONTAINERS,
    render_presets,
)
from agentcut.contracts import (
    TIMEBASE as T,
)
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService
from agentcut.render import compile_render_plan, output_args

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SRC_W, SRC_H = 320, 180
SECONDS = 2.0
TONE = 440.0
# Two solid bars meeting at x=160, drawn in a full-chroma frame: pure red and pure blue differ by
# ~155 levels in Cb, so the width of the transition in the U plane is a direct read-out of how much
# chroma survived the export. (Named colours would not do: FFmpeg's "green" is 0x008000, whose Cb is
# within a couple of levels of red's, and the seam would be invisible for a reason that has nothing
# to do with subsampling.)
RED, BLUE = 144, 160
FILTER = (
    f"color=c=0x808080:s={SRC_W}x{SRC_H}:r=30:d={SECONDS},"
    "format=yuv444p,"
    f"drawbox=x={RED}:y=60:w=16:h=60:color=0xFF0000:t=fill,"
    f"drawbox=x={BLUE}:y=60:w=16:h=60:color=0x0000FF:t=fill"
)


def run(args, timeout=600):
    return subprocess.run(
        args, capture_output=True, check=True, timeout=timeout, creationflags=0x08000000
    )


def source(folder: Path) -> Path:
    """A full-chroma source: yuv444p, so a 4:2:0 export can be told apart from a 4:4:4 one."""
    target = folder / "formats.mp4"
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
            FILTER,
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={TONE}:sample_rate=48000:duration={SECONDS}",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv444p",
            "-crf",
            "10",
            "-c:a",
            "aac",
            "-shortest",
            str(target),
        ]
    )
    return target


def probe(path: Path, entries: str, stream: str | None = None) -> dict:
    argv = [str(FFPROBE), "-v", "error"]
    if stream:
        argv += ["-select_streams", stream]
    argv += ["-show_entries", entries, "-of", "json", str(path)]
    return json.loads(run(argv).stdout.decode())


def streams(path: Path) -> list[dict]:
    data = probe(
        path,
        "stream=index,codec_type,codec_name,pix_fmt,width,height,sample_rate,channels,duration",
    )
    return data["streams"]


def container_info(path: Path) -> dict:
    # `format=tags` is not a thing; the tag dictionary lives in its own `format_tags` section.
    return probe(path, "format=format_name,duration:format_tags")["format"]


def format_tag(path: Path, key: str) -> str:
    # ffprobe pads a fourcc, and a major brand of `qt  ` is the same fact as `qt`.
    return str(container_info(path).get("tags", {}).get(key, "")).strip()


def chroma_edge(path: Path) -> tuple[int, list[int]]:
    """Pixels in the U plane whose value sits clearly between the two bar plateaus."""
    rows = streams(path)
    video = next(row for row in rows if row["codec_type"] == "video")
    # The sampling below assumes the canvas equals the source; a different size means the export
    # was resampled, which would blur both sides of the comparison and make the measurement a lie.
    assert (video["width"], video["height"]) == (SRC_W, SRC_H), (path.name, video)
    raw = run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv444p",
            "-",
        ],
        timeout=300,
    ).stdout
    plane = SRC_W * SRC_H
    row = SRC_W * (SRC_H // 2)
    strip = raw[plane + row : plane + row + SRC_W]
    red = sorted(strip[RED + 3 : RED + 9])[4]
    blue = sorted(strip[BLUE + 4 : BLUE + 10])[4]
    low, high = min(red, blue), max(red, blue)
    span = high - low
    # The two bars must be distinguishable at all, or a "0 pixel wide seam" would mean nothing.
    assert span > 60, (red, blue)
    inside = [value for value in strip[RED + 2 : BLUE + 12]]
    width = sum(1 for value in inside if value > low + span * 0.2 and value < high - span * 0.2)
    return width, [red, blue]


def tone_amplitude(path: Path) -> float:
    """Goertzel magnitude at 440 Hz over the whole decoded mono mix, normalized 0..1."""
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
    ).stdout
    samples = [
        int.from_bytes(raw[i : i + 2], "little", signed=True) for i in range(0, len(raw) - 1, 2)
    ]
    window = samples[len(samples) // 2 : len(samples) // 2 + 4096]
    step = 2 * math.pi * TONE / 48000
    real = imag = 0.0
    for index, value in enumerate(window):
        angle = step * index
        real += value * math.cos(angle)
        imag += value * math.sin(angle)
    return 2 * math.hypot(real, imag) / len(window) / 32768


def contract_suite() -> None:
    presets = {item["id"]: item for item in render_presets()}
    for preset in presets.values():
        assert preset["container"] in OUTPUT_CONTAINERS, preset
        assert preset["codec"] in OUTPUT_CODECS, preset
        assert preset["audio_codec"] in OUTPUT_AUDIO_CODECS, preset
        assert set(preset) == {
            "id",
            "label",
            "container",
            "codec",
            "crf",
            "encoder_preset",
            "audio_codec",
            "audio_bitrate",
            "pixel_format",
            "profile",
            "scale",
        }, sorted(preset)
    argv = {preset_id: output_args(preset, 48000, 25.0) for preset_id, preset in presets.items()}
    for preset_id, args in argv.items():
        joined = " ".join(args)
        if presets[preset_id]["codec"] is None:
            # An audio-only preset has no picture arguments at all; tests/audio_check.py owns that
            # shape, and asserting `-pix_fmt None` here would only prove the loop runs.
            assert "-c:v" not in joined and "-pix_fmt" not in joined, (preset_id, joined)
            continue
        assert f"-pix_fmt {presets[preset_id]['pixel_format']}" in joined, (preset_id, joined)
        assert "-ar 48000 -ac 2" in joined, joined
        if presets[preset_id]["container"] in ("mp4", "mov"):
            assert "-movflags +faststart" in joined, (preset_id, joined)
        else:
            assert "-movflags" not in joined, (preset_id, joined)

    base = " ".join(argv["h264-1080p"])
    assert "-preset veryfast -crf 23" in base and "-tag:v" not in base, base
    hevc = " ".join(argv["h265-1080p"])
    assert "-tag:v hvc1" in hevc and "-preset medium -crf 24" in hevc, hevc
    vp9 = " ".join(argv["vp9-1080p-web"])
    # A VP9 rate-control trap: crf alone with the default target bitrate clamps the quality, so the
    # bitrate has to be zeroed explicitly. And there is no -preset for this encoder.
    assert "-b:v 0 -crf 32" in vp9 and "-preset" not in vp9, vp9
    assert "-c:a libopus -b:a 128k" in vp9, vp9
    prores = " ".join(argv["prores-422hq"])
    assert "-profile:v 3" in prores and "-crf" not in prores, prores
    assert "-c:a pcm_s24le" in prores and "-b:a" not in prores, prores
    assert presets["prores-422hq"]["pixel_format"] == "yuv444p10le", presets["prores-422hq"]

    # A preset naming a codec this builder does not know must be refused, not passed through.
    fake = dict(presets["h264-1080p"], codec="libx999")
    try:
        output_args(fake, 48000, 25.0)
    except Exception as error:  # noqa: BLE001 - the point is that it raises at all
        assert getattr(error, "code", None) == "UNKNOWN_PRESET", type(error).__name__
    else:
        raise AssertionError("an unknown codec was accepted into the FFmpeg argv")
    print(
        f"   {len(presets)} presets over containers {OUTPUT_CONTAINERS}, codecs {OUTPUT_CODECS}: "
        "each codec gets the arguments it accepts, and nothing but a preset id reaches FFmpeg"
    )


def graph_suite(folder: Path) -> None:
    clip = source(folder)
    project = compile_project(clip)
    deep = compile_render_plan(project, "prores-422hq")
    flat = compile_render_plan(project, "h264-source-quality")
    deep_chain = [stage for stage in deep.filters if "format=" in stage]
    flat_chain = [stage for stage in flat.filters if "format=" in stage]
    assert any("format=yuv444p10le" in stage for stage in deep_chain), deep_chain
    assert all("yuv444p10le" not in stage for stage in flat_chain), flat_chain
    assert any("format=yuv420p" in stage for stage in flat_chain), flat_chain
    # The framing stage carries the format too: leaving it 4:2:0 would squeeze the chroma away
    # upstream and let the wrapper only pretend to be deep.
    assert any("setsar=1,fps=30/1,format=yuv444p10le" in stage for stage in deep_chain), deep_chain
    assert "[vout]" in "".join(deep_chain) and "yuv444p10le[vout]" in "".join(deep_chain), (
        deep_chain
    )
    print(
        "   the sampling format runs from the decode and framing stages to [vout], not just the "
        "-pix_fmt flag"
    )


def project_payload(clip_source: Path):
    from agentcut.contracts import Project, VerifiedMedia
    from agentcut.timeline import validate_timeline

    verified = VerifiedMedia.model_validate(
        {
            "probe_id": "a",
            "path": str(clip_source),
            "kind": "video",
            "label": "formats",
            "size_bytes": clip_source.stat().st_size,
            "content_sha256": "0" * 64,
            "duration_ticks": int(SECONDS * T),
            "width": SRC_W,
            "height": SRC_H,
            "has_audio": True,
        }
    )
    project = Project.model_validate(
        {
            "id": "p",
            "name": "formats",
            "settings": {
                "width": SRC_W,
                "height": SRC_H,
                "frame_rate": {"numerator": 30, "denominator": 1},
            },
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
            "clips": {
                "c": {
                    "id": "c",
                    "asset_id": "a",
                    "track_id": "v",
                    "position_ticks": 0,
                    "duration_ticks": int(SECONDS * T),
                }
            },
        }
    )
    validate_timeline(project)
    return project


def compile_project(clip_source: Path):
    return project_payload(clip_source)


def wait(client: TestClient, job_id: str) -> dict:
    status = {}
    for _ in range(900):
        status = client.get("/v1/jobs/" + job_id).json()
        if status["job"]["status"] in {"succeeded", "failed", "cancelled"}:
            break
    return status


def media_suite(folder: Path) -> dict:
    media = MediaService(folder / "fmt-db.sqlite3", [folder], folder / "fmt-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "fmt-api.sqlite3",
        FFMPEG,
        folder / "exports",
        [folder / "exports", folder],
    )
    runtime.ensure_worker()
    token = "fmtcheck" + "e" * 56
    app = create_app(folder / "fmt-api.sqlite3", token, media=media, jobs=runtime)
    path = None
    outputs: dict[str, Path] = {}
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        caps = client.get("/v1/capabilities").json()
        assert caps["features"]["multi_codec_delivery"] is True, caps["features"]
        assert caps["output_containers"] == list(OUTPUT_CONTAINERS), caps.get("output_containers")
        ids = [item["id"] for item in caps["render_presets"]]
        for wanted in ("h265-1080p", "h265-2160p", "vp9-1080p-web", "prores-422hq"):
            assert wanted in ids, ids

        clip = source(folder)
        probe_body = client.post("/v1/media/import", json={"path": str(clip)}).json()
        created = client.post(
            "/v1/projects",
            json={
                "request_id": "new",
                "name": "formats",
                # The canvas equals the source, so a 1:1 preset resamples nothing: the chroma
                # measurements below then say something about the export, not about a scale filter.
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
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                    {
                        "op": "asset.import",
                        "asset_id": "a",
                        "label": "a",
                        "probe_id": probe_body["id"],
                        "verified": probe_body["verified"],
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

        # The suffix belongs to the preset now, so both halves are exercised: a wrong extension is
        # refused naming the container it wanted, and a correct non-mp4 one is accepted.
        clash = client.post(
            path + "/renders",
            json={
                "request_id": "clash",
                "expected_revision": revision,
                "preset_id": "vp9-1080p-web",
                "filename": "错的容器.mp4",
            },
        )
        assert clash.status_code == 422, clash.text
        assert ".webm" in clash.text, clash.text
        ghost = client.post(
            path + "/renders",
            json={
                "request_id": "ghost",
                "expected_revision": revision,
                "preset_id": "no-such-preset",
                "filename": "x.mp4",
            },
        )
        assert ghost.status_code == 422, ghost.text
        assert "UNKNOWN_PRESET" in ghost.text or "unknown render preset" in ghost.text, ghost.text
        assert ghost.json()["error"]["code"] != "OUTPUT_NAME_INVALID", ghost.text
        print("   a .mp4 name cannot carry a WebM preset; an unknown preset is still named as such")

        wanted = {
            "h264-source-quality": ("mp4", "h264", "aac", "yuv420p"),
            "h265-1080p": ("mp4", "hevc", "aac", "yuv420p"),
            "vp9-1080p-web": ("webm", "vp9", "opus", "yuv420p"),
            "prores-422hq": ("mov", "prores", "pcm_s24le", "yuv444p10le"),
        }
        for index, (preset_id, expect) in enumerate(wanted.items()):
            container, video_codec, audio_codec, pix_fmt = expect
            job = client.post(
                path + "/renders",
                json={
                    "request_id": f"ship{index}",
                    "expected_revision": revision,
                    "preset_id": preset_id,
                    "filename": f"交付-{preset_id}.{container}",
                },
            )
            assert job.status_code == 200, job.text
            summary = wait(client, job.json()["job"]["id"])["job"]
            assert summary["status"] == "succeeded", summary
            out = Path(summary["output_path"])
            assert out.suffix == f".{container}", out
            outputs[preset_id] = out

        sizes = {}
        for preset_id, out in outputs.items():
            container, video_codec, audio_codec, pix_fmt = wanted[preset_id]
            rows = streams(out)
            video = next(row for row in rows if row["codec_type"] == "video")
            audio = next(row for row in rows if row["codec_type"] == "audio")
            assert video["codec_name"] == video_codec, (preset_id, video)
            assert audio["codec_name"] == audio_codec, (preset_id, audio)
            assert video["pix_fmt"] == pix_fmt, (preset_id, video)
            assert int(audio["sample_rate"]) == 48000 and int(audio["channels"]) == 2, audio
            brand = format_tag(out, "major_brand")
            info = container_info(out)
            if container == "mov":
                assert brand == "qt", (preset_id, brand)
            elif container == "webm":
                # ffprobe names the demuxer "matroska,webm" for both halves of the family, so the
                # DocType in the EBML header is what proves this is a WebM and not an MKV.
                assert info["format_name"] == "matroska,webm", (preset_id, info["format_name"])
                assert b"webm" in out.read_bytes()[:64], out.read_bytes()[:64]
            else:
                assert brand == "isom", (preset_id, brand)
            seconds = float(info["duration"])
            tolerance = 0.12 if container == "webm" else 0.02
            assert abs(seconds - SECONDS) <= tolerance, (preset_id, seconds)
            amplitude = tone_amplitude(out)
            assert amplitude > 0.05, (preset_id, amplitude)
            sizes[preset_id] = out.stat().st_size
            print(
                f"   {preset_id}: {video['codec_name']}/{video['pix_fmt']} + "
                f"{audio['codec_name']} {audio['sample_rate']}Hz, {seconds:.3f}s, "
                f"440 Hz tone {amplitude:.3f}, {sizes[preset_id] / 1024:.0f} KiB"
            )
        # Same timeline, same canvas, two sampling formats: the deep one has to really keep the
        # chroma, so the red|blue seam is measured on the two 1:1 exports instead of being trusted
        # from the `-pix_fmt` flag.
        edges = {
            name: chroma_edge(outputs[name]) for name in ("h264-source-quality", "prores-422hq")
        }
    shallow, deep = edges["h264-source-quality"][0], edges["prores-422hq"][0]
    assert deep <= 1, edges
    assert shallow >= 2, edges
    assert deep < shallow, edges
    print(
        f"   the red|blue seam is {deep} pixel wide in Cb on the ProRes 4:4:4 export and "
        f"{shallow} on the H.264 4:2:0 one (plateaus {edges['prores-422hq'][1]})"
    )


def main() -> None:
    import tempfile

    contract_suite()
    with tempfile.TemporaryDirectory(prefix="agentcut-format-") as scratch:
        folder = Path(scratch)
        graph_suite(folder)
        media_suite(folder)
    print(
        "PASS: four delivery formats exported through the job worker are the streams their preset "
        "names, with sound, right duration, and the deep one measurably keeps its chroma"
    )


if __name__ == "__main__":
    main()
