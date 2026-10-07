"""Nesting must not lose a per-clip filter: a 1.62 LUT node and a 1.63 caption style that live
inside a compound have to land on exactly the same pixels as the same edits on the root timeline.

The inner clips are not in `project.clips` but in `project.sequences[s].clips`, so a filter builder
that walks only the root scope would silently ship the unfiltered picture. Every claim here is read
back from rendered frames, and the last pair proves the comparison is actually sensitive to the
nested grade — without it, 'flat == nested' would also pass when both drop the LUT.
"""

import subprocess
import tempfile
from pathlib import Path

from blend_check import png

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import CreateProject, EditBatch, Project
from agentcut.media import MediaService
from agentcut.projects import ProjectStore
from agentcut.render import compile_render_plan, text_fonts_available

ROOT = Path(__file__).resolve().parent.parent


def lut(red_knot: float) -> dict:
    """A three-point table whose red midpoint is `red_knot`.

    The picture is one solid color, so every channel lands inside exactly one segment; perturbing
    the red knot at 0.5 moves the red the fixture actually reads (a change to the blue table's
    first segment left the frame bit-identical, which is how this fixture was pinned down).
    """
    return {
        "kind": "lut",
        "title": "Nest fx",
        "size": 3,
        "channels": [[0.0, red_knot, 1.0], [0.0, 0.2, 1.0], [0.0, 0.6, 1.0]],
    }


def main() -> None:
    ffmpeg = ROOT / "desktop/resources/bin/ffmpeg.exe"
    ffprobe = ROOT / "desktop/resources/bin/ffprobe.exe"
    installed = text_fonts_available()
    assert installed, "no text face is installed, so this check cannot draw a caption"
    face = next((e["id"] for e in installed if e["id"] == "song"), installed[0]["id"])
    style = {
        "body": "嵌套里的字",
        "font_size": 0.12,
        "color": "#FFEE00",
        "align": "bottom",
        "box": True,
        "font": face,
        "text_align": "right",
        "outline_width": 0.15,
        "outline_color": "#FF0000",
        "shadow_x": 0.5,
        "shadow_color": "#00FF00",
        "box_opacity": 0.9,
        "line_spacing": 0.5,
    }

    with tempfile.TemporaryDirectory(prefix="agentcut-nestfx-") as temp:
        folder = Path(temp)

        def run(argv, **kwargs):
            done = subprocess.run(
                [str(ffmpeg), "-v", "error", *argv],
                capture_output=True,
                creationflags=0x08000000,
                **kwargs,
            )
            assert done.returncode == 0, done.stderr.decode(errors="replace")[-800:]
            return done.stdout

        png(folder / "pic.png", (80, 40, 160))
        media = MediaService(folder / "db.sqlite3", [folder], folder / "cache", ffmpeg, ffprobe)
        store = ProjectStore(media.db_path, media)
        probe = media.import_file(str(folder / "pic.png"))

        def edit(project, commands, seq=None):
            answer = store.mutate(
                project.id,
                EditBatch.model_validate(
                    {
                        "request_id": f"{project.name}-{project.revision}-{seq or 'root'}",
                        "expected_revision": project.revision,
                        "sequence_id": seq,
                        "commands": commands,
                    }
                ),
            )
            return answer.project

        def build(name, *, nest: bool, text: dict) -> Project:
            project = store.create(
                CreateProject(
                    request_id="new-" + name,
                    name=name,
                    settings={"width": 320, "height": 180},
                )
            ).project
            project = edit(
                project,
                [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                    {"op": "track.add", "track": {"id": "t", "kind": "video", "name": "t"}},
                    {
                        "op": "asset.import",
                        "asset_id": "pic",
                        "label": "pic",
                        "probe_id": probe.id,
                        "verified": probe.verified.model_dump(),
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "back",
                            "asset_id": "pic",
                            "track_id": "v",
                            "position_ticks": 0,
                            "duration_ticks": 4 * T,
                        },
                    },
                    {
                        "op": "asset.register",
                        "asset": {
                            "id": "txt",
                            "kind": "text",
                            "label": "txt",
                            "reference": "generated:text",
                            "duration_ticks": 4 * T,
                        },
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "cap",
                            "asset_id": "txt",
                            "track_id": "t",
                            "position_ticks": 0,
                            "duration_ticks": 4 * T,
                            "text": text,
                        },
                    },
                ],
            )
            if nest:
                project = edit(
                    project,
                    [
                        {
                            "op": "sequence.nest",
                            "clip_ids": ["back", "cap"],
                            "name": "inner",
                            "sequence_id": "inner",
                            "asset_id": "ainner",
                            "clip_id": "cinner",
                        }
                    ],
                )
            return project

        def graded(project, table, seq=None):
            return edit(project, [{"op": "clip.grade", "clip_id": "back", "grade": [table]}], seq)

        def frames(project):
            plan = compile_render_plan(project, "h264-source-quality")
            graph = "\n".join(plan.filters)
            # drawtext reads the caption from a sidecar file named in the graph, so the working
            # directory of every grab has to be the folder those files live in.
            for name, body in plan.text_files.items():
                (folder / name).write_text(body, encoding="utf-8")
            out = []
            for at in (0.5, 2.0, 3.5):
                out.append(
                    run(
                        [
                            *plan.input_args,
                            "-filter_complex",
                            ";".join([*plan.filters, f"{plan.audio_label}anullsink"]),
                            "-map",
                            plan.video_label,
                            "-ss",
                            str(at),
                            "-frames:v",
                            "1",
                            "-f",
                            "rawvideo",
                            "-pix_fmt",
                            "rgb24",
                            "pipe:1",
                        ],
                        cwd=folder,
                    )
                )
            return graph, out

        def worst(a, b):
            assert len(a) == len(b) and len(a) == 3
            for f1, f2 in zip(a, b):
                assert len(f1) == len(f2) == 320 * 180 * 3, "a frame came back short"
            return max(abs(x - y) for x, y in zip(b"".join(a), b"".join(b)))

        flat = graded(build("flat", nest=False, text=style), lut(0.4))
        nested = graded(build("nested", nest=True, text=style), lut(0.4), seq="inner")
        # The control: the same picture and the same words with none of the 1.62/1.63 knobs.
        plain = build("plain", nest=False, text={"body": style["body"], "font_size": 0.12})
        moved = graded(build("moved", nest=True, text=style), lut(0.9), seq="inner")

        flat_graph, flat_frames = frames(flat)
        nested_graph, nested_frames = frames(nested)
        plain_graph, plain_frames = frames(plain)
        moved_graph, moved_frames = frames(moved)

        for label, graph in (("flat", flat_graph), ("nested", nested_graph)):
            assert "lutrgb=" in graph, f"{label}: the LUT node never reached the exporter"
            assert "drawtext" in graph, f"{label}: the caption never reached the exporter"
            assert "borderw=" in graph, f"{label}: the outline width was dropped"
            assert "shadowx=" in graph, f"{label}: the hard shadow was dropped"
            assert graph.count("drawtext") == 1, f"{label}: {graph.count('drawtext')} drawtext"

        inside = worst(flat_frames, nested_frames)
        assert inside <= 3, f"nesting changed the picture by {inside} levels"
        painted = worst(flat_frames, plain_frames)
        assert painted > 8, f"the grade and the style together moved {painted} levels"
        alive = worst(nested_frames, moved_frames)
        assert alive > 8, f"the nested LUT only moved {alive} levels, so it is not being applied"
        assert moved_graph != nested_graph and "lutrgb" not in plain_graph

        print(
            f"PASS: nested LUT + caption style match the root timeline ({inside} levels apart), "
            f"the same edits paint {painted} levels over the plain build, and re-pointing the "
            f"inner table alone moves {alive} levels through the compound"
        )


if __name__ == "__main__":
    main()
