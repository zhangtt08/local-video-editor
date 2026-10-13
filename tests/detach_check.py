"""Detach a video clip's embedded audio onto its own audio track."""

import hashlib
import re
import subprocess
import tempfile
from pathlib import Path

from agentcut.animation import preview_manifest
from agentcut.contracts import TIMEBASE, EditBatch, EditorError, Project
from agentcut.render import compile_render_plan
from agentcut.timeline import apply_commands

T = TIMEBASE
ROOT = Path(__file__).resolve().parent.parent


def batch(commands, revision=0, request="check", dry=False):
    return EditBatch.model_validate(
        {"request_id": request, "expected_revision": revision, "commands": commands, "dry_run": dry}
    )


def ffmpeg():
    return ROOT / "desktop/resources/bin/ffmpeg.exe"


def run(args):
    return subprocess.run(
        [str(ffmpeg()), "-v", "error", "-y", *args],
        capture_output=True,
        check=True,
        timeout=90,
        creationflags=0x08000000,
    ).stdout


def mean_volume(path: Path) -> float:
    proc = subprocess.run(
        [str(ffmpeg()), "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True,
        timeout=90,
        creationflags=0x08000000,
        text=True,
    )
    match = re.search(r"mean_volume: (-?\d+\.?\d*) dB", proc.stderr)
    assert match, proc.stderr
    return float(match.group(1))


def main():
    with tempfile.TemporaryDirectory(prefix="agentcut-detach-") as folder:
        folder = Path(folder)
        blue = folder / "blue.mp4"
        run(
            [
                "-f",
                "lavfi",
                "-i",
                "color=blue:s=320x180:r=30:d=2",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:duration=2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(blue),
            ]
        )
        probe_hash = hashlib.sha256(blue.read_bytes()).hexdigest()
        track_asset = {
            "id": "clip",
            "kind": "video",
            "label": "clip",
            "reference": "test",
            "duration_ticks": 2 * T,
            "verified": {
                "probe_id": "clip",
                "path": str(blue),
                "kind": "video",
                "label": "clip",
                "size_bytes": blue.stat().st_size,
                "content_sha256": probe_hash,
                "duration_ticks": 2 * T,
                "width": 320,
                "height": 180,
                "has_audio": True,
            },
        }
        p = Project.model_validate(
            {
                "id": "d",
                "name": "detach",
                "settings": {"width": 320, "height": 180},
                "tracks": [
                    {"id": "v", "kind": "video", "name": "v"},
                    {"id": "a", "kind": "audio", "name": "a"},
                ],
                "assets": {"clip": track_asset},
                "clips": {
                    "c": {
                        "id": "c",
                        "asset_id": "clip",
                        "track_id": "v",
                        "position_ticks": 0,
                        "duration_ticks": 2 * T,
                    }
                },
            }
        )

        # metadata-less path: detach without asset verified fails clearly
        try:
            apply_commands(
                p.model_copy(
                    deep=True,
                    update={
                        "assets": {"clip": p.assets["clip"].model_copy(update={"verified": None})}
                    },
                ),
                batch(
                    [
                        {
                            "op": "clip.detach_audio",
                            "clip_id": "c",
                            "audio_clip_id": "d",
                            "track_id": "a",
                        }
                    ]
                ).commands,
            )
            raise AssertionError("expected NO_EMBEDDED_AUDIO")
        except EditorError as err:
            assert err.code == "NO_EMBEDDED_AUDIO", err.code

        detached = apply_commands(
            p,
            batch(
                [{"op": "clip.detach_audio", "clip_id": "c", "audio_clip_id": "d", "track_id": "a"}]
            ).commands,
        )
        assert detached.clips["c"].embedded_audio is False
        assert detached.clips["d"].track_id == "a" and detached.clips["d"].position_ticks == 0
        assert detached.clips["d"].link_id == detached.clips["c"].link_id
        assert detached.clips["d"].link_id is not None
        monitor = preview_manifest(detached)
        assert monitor["clips"]["c"]["sound_enabled"] is False
        assert monitor["clips"]["d"]["sound_enabled"] is True
        muted = detached.model_copy(deep=True)
        next(track for track in muted.tracks if track.id == "a").muted = True
        assert preview_manifest(muted)["clips"]["d"]["sound_enabled"] is False

        whole = compile_render_plan(p, "h264-source-quality")
        full_out = folder / "whole.mp4"
        subprocess.run(
            whole.ffmpeg_argv(str(ffmpeg()), str(full_out)),
            capture_output=True,
            timeout=90,
            creationflags=0x08000000,
            check=True,
        )
        detached_plan = compile_render_plan(detached, "h264-source-quality")
        split_out = folder / "split.mp4"
        subprocess.run(
            detached_plan.ffmpeg_argv(str(ffmpeg()), str(split_out)),
            capture_output=True,
            timeout=90,
            creationflags=0x08000000,
            check=True,
        )

        loud_whole = mean_volume(full_out)
        loud_split = mean_volume(split_out)
        assert abs(loud_whole - loud_split) < 3.0, (loud_whole, loud_split)
        print(
            "PASS: detach moves embedded sound to audio track "
            f"(mean {loud_whole:.1f} vs {loud_split:.1f} dB)"
        )


if __name__ == "__main__":
    main()
