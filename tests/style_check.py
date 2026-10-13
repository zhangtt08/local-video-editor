"""Text layer styling: vertical anchoring and the background plate."""

import hashlib
import subprocess
import tempfile
from pathlib import Path

from agentcut.contracts import TIMEBASE, Project
from agentcut.render import compile_render_plan

ROOT = Path(__file__).resolve().parent.parent
T = TIMEBASE


def ffmpeg() -> Path:
    return ROOT / "desktop/resources/bin/ffmpeg.exe"


def frame_brightness(path: Path, y0: float, y1: float) -> float:
    raw = subprocess.run(
        [
            str(ffmpeg()),
            "-v",
            "error",
            "-ss",
            "0.5",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            f"crop=iw:ih*{y1 - y0}:0:ih*{y0}",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
        timeout=60,
        creationflags=0x08000000,
    ).stdout
    return sum(raw) / len(raw)


def make_project(bg_path: Path, text_override: dict) -> Project:
    sha = hashlib.sha256(Path(bg_path).read_bytes()).hexdigest()
    return Project.model_validate(
        {
            "id": "p",
            "name": "style",
            "settings": {"width": 320, "height": 180},
            "tracks": [
                {"id": "v", "kind": "video", "name": "v"},
                {"id": "title", "kind": "video", "name": "title"},
            ],
            "assets": {
                "bg": {
                    "id": "bg",
                    "kind": "video",
                    "label": "bg",
                    "reference": "t",
                    "duration_ticks": 2 * T,
                    "verified": {
                        "probe_id": "bg",
                        "path": str(bg_path),
                        "kind": "video",
                        "label": "bg",
                        "size_bytes": Path(bg_path).stat().st_size,
                        "content_sha256": sha,
                        "duration_ticks": 2 * T,
                        "width": 320,
                        "height": 180,
                        "has_audio": False,
                    },
                },
                "title": {"id": "title", "kind": "text", "label": "text", "reference": "t"},
            },
            "clips": {
                "bg": {
                    "id": "bg",
                    "asset_id": "bg",
                    "track_id": "v",
                    "position_ticks": 0,
                    "duration_ticks": 2 * T,
                },
                "t": {
                    "id": "t",
                    "asset_id": "title",
                    "track_id": "title",
                    "position_ticks": 0,
                    "duration_ticks": 2 * T,
                    "text": {
                        "body": "底部字幕",
                        "font_size": 0.1,
                        "color": "#000000",
                        **text_override,
                    },
                },
            },
        }
    )


def main():
    with tempfile.TemporaryDirectory(prefix="agentcut-style-") as folder:
        folder = Path(folder)
        silent = folder / "bg.mp4"
        subprocess.run(
            [
                str(ffmpeg()),
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=white:s=320x180:r=30:d=2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(silent),
            ],
            capture_output=True,
            check=True,
            timeout=60,
            creationflags=0x08000000,
        )

        # compile-level assertions
        plan = compile_render_plan(
            make_project(silent, {"align": "bottom", "box": True}), "h264-source-quality"
        )
        filters = "\n".join(plan.filters)
        assert "geq=r='0':g='0':b='0':a='if(gte(Y" in filters
        assert "y=165.60-text_h" in filters, filters  # 180 高的画面，92% 处

        plan_center = compile_render_plan(make_project(silent, {}), "h264-source-quality")
        filters_center = "\n".join(plan_center.filters)
        assert "geq=r='0'" not in filters_center and "y=(h-text_h)/2" in filters_center, (
            filters_center
        )

        # pixel-level: a bottom plate must darken the bottom band
        cases = {"plate": folder / "plate.mp4", "plain": folder / "plain.mp4"}
        for key, out in cases.items():
            src = make_project(silent, {"align": "bottom", "box": key == "plate"})
            plan = compile_render_plan(src, "h264-source-quality")
            work = folder / f"work-{key}"
            work.mkdir()
            for name, body in plan.text_files.items():
                (work / name).write_text(body, encoding="utf-8")
            subprocess.run(
                plan.ffmpeg_argv(str(ffmpeg()), str(out)),
                capture_output=True,
                timeout=90,
                creationflags=0x08000000,
                check=True,
                cwd=work,
            )

        def band_mean(path: Path, y0: float, y1: float) -> float:
            raw = subprocess.run(
                [
                    str(ffmpeg()),
                    "-v",
                    "error",
                    "-ss",
                    "0.5",
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    "-vf",
                    f"crop=iw:ih*{y1 - y0}:0:ih*{y0}",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "gray",
                    "pipe:1",
                ],
                capture_output=True,
                check=True,
                timeout=60,
                creationflags=0x08000000,
            ).stdout
            return sum(raw) / max(1, len(raw))

        plate_dark = band_mean(cases["plate"], 0.80, 0.92)
        plain_dark = band_mean(cases["plain"], 0.80, 0.92)
        assert plate_dark + 30 < plain_dark, (plate_dark, plain_dark)
        print(
            "PASS: text align/box anchoring "
            f"(bottom plate mean {plate_dark:.0f} vs plain {plain_dark:.0f})"
        )


if __name__ == "__main__":
    main()
