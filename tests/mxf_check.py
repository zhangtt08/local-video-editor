"""MXF delivery: two presets out of the same closed table, measured against the real container.

AgentCut already shipped ProRes in .mov; what a broadcast / post house actually asks for is MXF.
The whole point of the preset table is that a caller cannot aim FFmpeg at an arbitrary muxer, so
the new rows have to be proven where it counts: the file that comes out has to *be* MXF, carry the
codec the preset names, keep the duration, and survive a tail decode. And because MXF refuses to
write a header for anything but 48 kHz audio, that constraint is enforced in this build with a
named refusal instead of an FFmpeg error about a file the user never asked to open.

No HTTP and no job runner: the plan is compiled by the same function the job uses, written by the
same FFmpeg binary the desktop ships, and read back with the same ffprobe.
"""

import json
import subprocess
import tempfile
from pathlib import Path

from agentcut.contracts import (
    OUTPUT_CONTAINERS,
    TIMEBASE,
    EditorError,
    Project,
    capabilities,
    render_presets,
)
from agentcut.render import compile_render_plan

T = TIMEBASE
ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"


def run(args, timeout=180):
    return subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", *args],
        capture_output=True,
        check=True,
        timeout=timeout,
        creationflags=0x08000000,
    )


def probe(path):
    out = subprocess.run(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        check=True,
        timeout=60,
        text=True,
    ).stdout
    return json.loads(out)


def project(sample_rate=48000):
    return Project.model_validate(
        {
            "id": "mx",
            "name": "mxf",
            "settings": {
                "width": 320,
                "height": 180,
                "frame_rate": {"numerator": 25, "denominator": 1},
                "sample_rate": sample_rate,
            },
            "tracks": [
                {"id": "v", "kind": "video", "name": "v"},
                {"id": "a", "kind": "audio", "name": "a"},
            ],
            "assets": {
                "pic": {
                    "id": "pic",
                    "kind": "video",
                    "label": "pic",
                    "reference": "pic",
                    "duration_ticks": 2 * T,
                },
                "tone": {
                    "id": "tone",
                    "kind": "audio",
                    "label": "tone",
                    "reference": "tone",
                    "duration_ticks": 2 * T,
                },
            },
            "clips": {
                "c1": {
                    "id": "c1",
                    "asset_id": "pic",
                    "track_id": "v",
                    "position_ticks": 0,
                    "duration_ticks": 2 * T,
                },
                "c2": {
                    "id": "c2",
                    "asset_id": "tone",
                    "track_id": "a",
                    "position_ticks": 0,
                    "duration_ticks": 2 * T,
                },
            },
        }
    )


def export(folder: Path, preset: str, sample_rate=48000):
    """One real deliverable, written by the shipped FFmpeg, read back by the shipped ffprobe."""
    plan = compile_render_plan(project(sample_rate), preset)
    target = folder / f"{preset}.mxf"
    subprocess.run(
        plan.ffmpeg_argv(str(FFMPEG), str(target)),
        capture_output=True,
        check=True,
        timeout=300,
        creationflags=0x08000000,
    )
    return plan, target, probe(target)


def main():
    tables = {item["id"]: item for item in render_presets()}
    assert "mxf" in OUTPUT_CONTAINERS, OUTPUT_CONTAINERS
    assert capabilities()["output_containers"] == list(OUTPUT_CONTAINERS), (
        "能力表与契约得是同一份容器清单"
    )
    for preset_id in ("mxf-prores-422hq", "mxf-mpeg2"):
        assert preset_id in tables, preset_id
        assert tables[preset_id]["container"] == "mxf", tables[preset_id]
        assert tables[preset_id]["audio_codec"] == "pcm_s24le", tables[preset_id]
    assert tables["mxf-mpeg2"]["codec"] == "mpeg2video"

    with tempfile.TemporaryDirectory(prefix="agentcut-mxf-") as folder:
        folder = Path(folder)
        run(
            [
                "-f",
                "lavfi",
                "-i",
                "color=red:s=320x180:r=25:d=2",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(folder / "pic.mp4"),
            ]
        )
        run(
            [
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:duration=2",
                str(folder / "tone.wav"),
            ]
        )
        # The hand-built project above names files that do not exist; the plan needs the real ones.
        base = project()
        for asset_id, name, kind in (("pic", "pic.mp4", "video"), ("tone", "tone.wav", "audio")):
            asset = base.assets[asset_id]
            payload = asset.model_dump()
            payload["verified"] = {
                "probe_id": asset_id,
                "path": str(folder / name),
                "kind": kind,
                "label": name,
                "size_bytes": (folder / name).stat().st_size,
                "content_sha256": __import__("hashlib")
                .sha256((folder / name).read_bytes())
                .hexdigest(),
                "duration_ticks": 2 * T,
                "width": 320 if kind == "video" else None,
                "height": 180 if kind == "video" else None,
                "has_audio": kind == "audio",
                "audio_sample_rate": 48000 if kind == "audio" else None,
            }
            base.assets[asset_id] = type(asset).model_validate(payload)

        seen = {}
        # The knob is the quantiser, not a crf: MPEG-2 has no crf, so a preset that wrote one would
        # be asking for something this branch does not know how to say.
        argv = " ".join(compile_render_plan(base, "mxf-mpeg2").ffmpeg_argv(str(FFMPEG), "x.mxf"))
        assert "-q:v 5" in argv, argv[-320:]
        assert "-crf" not in argv, "MPEG-2 那条不许带 crf"
        assert "-movflags" not in argv, "MXF 容器不该收到 mp4/mov 专用的 -movflags"
        for preset_id, want_codec, want_pix in (
            ("mxf-prores-422hq", "prores", "yuv422p10le"),
            ("mxf-mpeg2", "mpeg2video", "yuv420p"),
        ):
            plan = compile_render_plan(base, preset_id)
            target = folder / f"{preset_id}.mxf"
            subprocess.run(
                plan.ffmpeg_argv(str(FFMPEG), str(target)),
                capture_output=True,
                check=True,
                timeout=300,
                creationflags=0x08000000,
            )
            info = probe(target)
            streams = {item["codec_type"]: item for item in info["streams"]}
            assert "mxf" in info["format"]["format_name"], info["format"]
            assert streams["video"]["codec_name"] == want_codec, streams["video"]
            assert streams["video"].get("pix_fmt") == want_pix, streams["video"]
            assert streams["audio"]["codec_name"] == "pcm_s24le", streams["audio"]
            assert streams["audio"]["sample_rate"] == "48000", streams["audio"]
            duration = float(info["format"]["duration"])
            assert abs(duration - 2.0) <= 0.12, (preset_id, duration)
            # The tail has to decode: a container that writes a header but no readable last
            # frames is exactly the failure the desktop's own re-check is meant to catch.
            tail = subprocess.run(
                [
                    str(FFMPEG),
                    "-v",
                    "error",
                    "-sseof",
                    "-0.5",
                    "-i",
                    str(target),
                    "-frames:v",
                    "1",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "-",
                ],
                capture_output=True,
                check=True,
                timeout=120,
                creationflags=0x08000000,
            ).stdout
            assert len(tail) == 320 * 180 * 3, (preset_id, len(tail))
            assert plan.summary["container"] == "mxf", plan.summary
            seen[preset_id] = (streams["video"]["codec_name"], duration, len(target.read_bytes()))

        # MXF writes no audio header for a 44.1 kHz mix: name the constraint, do not let FFmpeg fail
        # with an error about a file the user never asked to open.
        for preset_id in ("mxf-prores-422hq", "mxf-mpeg2"):
            try:
                compile_render_plan(
                    base.model_copy(
                        deep=True,
                        update={
                            "settings": base.settings.model_copy(update={"sample_rate": 44100})
                        },
                    ),
                    preset_id,
                )
                raise AssertionError(f"{preset_id}: 44.1 kHz 竟然排得出 MXF")
            except EditorError as err:
                assert err.code == "MXF_NEEDS_48K", err.code
                assert err.details["preset_id"] == preset_id, err.details
                assert "48000" in err.message, err.message
        # The guard is container-scoped: the same 44.1 kHz project still delivers mp4.
        compile_render_plan(
            base.model_copy(
                deep=True,
                update={"settings": base.settings.model_copy(update={"sample_rate": 44100})},
            ),
            "h264-source-quality",
        )

    print(
        "PASS: MXF 交付走的是同一张闭合预设表——"
        + "，".join(
            f"{key} 出 {value[0]}、{value[1]:.3f} 秒、{value[2] // 1024} KiB"
            for key, value in seen.items()
        )
        + "；44.1 kHz 的 MXF 请求被 MXF_NEEDS_48K 点名拒掉（两条预设各一次），"
        "同一工程改投 mp4 照旧排得出计划"
    )


if __name__ == "__main__":
    main()
