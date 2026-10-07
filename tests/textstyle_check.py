"""Text styling: one set of numbers, drawn twice — by FFmpeg's `drawtext` and by the browser.

The knobs added in 1.63 (face, alignment, outline, hard shadow, plate colour and opacity, line
spacing) are fractions of the glyph size, so one value means the same thing in both renderers.
This check asserts three things separately:

- the compiled filter carries those numbers, and the **default** style still compiles to the 1.62
  rendering (4 % black outline, 0.2 line spacing, a 115/255 black band) — an old project must not
  change pixels just because the contract grew;
- the pixels in a delivered H.264 file move as each knob says, measured against a control render
  that differs in exactly one field;
- the machine is honest about fonts: `capabilities.text_fonts` publishes only faces whose file
  exists, and a face that is not installed is refused by name, never silently substituted.
"""

import hashlib
import re
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentcut import render as render_module
from agentcut.contracts import TEXT_FONTS, Project, TextStyle, capabilities
from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app
from agentcut.render import compile_render_plan, text_font_path, text_fonts_available

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/node_modules/ffmpeg-static/ffmpeg.exe"
WIDTH, HEIGHT = 320, 180
BODY = "文字样式"


def run(args: list[str]) -> bytes:
    done = subprocess.run(
        [str(FFMPEG), "-v", "error", *args],
        capture_output=True,
        check=True,
        timeout=300,
        creationflags=0x08000000,
    )
    return done.stdout


def source(folder: Path) -> Path:
    path = folder / "black.mp4"
    run(
        [
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={WIDTH}x{HEIGHT}:r=30:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv444p",
            "-crf",
            "10",
            str(path),
        ]
    )
    return path


def project_with(video: Path, text: dict) -> Project:
    verified = {
        "probe_id": "a",
        "path": str(video),
        "kind": "video",
        "label": "black",
        "size_bytes": video.stat().st_size,
        "content_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
        "duration_ticks": T,
        "width": WIDTH,
        "height": HEIGHT,
        "has_audio": False,
    }
    return Project.model_validate(
        {
            "id": "p",
            "name": "text",
            "settings": {"width": WIDTH, "height": HEIGHT},
            "tracks": [{"id": "v", "kind": "video", "name": "v"}],
            "assets": {
                "a": {
                    "id": "a",
                    "kind": "text",
                    "label": "t",
                    "reference": "generated:text",
                    "duration_ticks": T,
                },
                "src": {
                    "id": "src",
                    "kind": "video",
                    "label": "black",
                    "reference": "unused",
                    "duration_ticks": T,
                    "verified": verified,
                },
            },
            "clips": {
                "c": {
                    "id": "c",
                    "asset_id": "a",
                    "track_id": "v",
                    "position_ticks": 0,
                    "duration_ticks": T,
                    "text": {"body": BODY, **text},
                }
            },
        }
    )


def filters(project: Project) -> str:
    plan = compile_render_plan(project, "h264-source-quality")
    return " ".join(step for step in plan.filters if "drawtext" in step or "geq=" in step)


def render(project: Project, folder: Path, name: str) -> Path:
    out = folder / name
    plan = compile_render_plan(project, "h264-source-quality")
    for file_name, body in plan.text_files.items():
        (folder / file_name).write_text(body, encoding="utf-8")
    done = subprocess.run(
        plan.ffmpeg_argv(str(FFMPEG), str(out)),
        cwd=folder,
        capture_output=True,
        timeout=300,
        creationflags=0x08000000,
    )
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-800:]
    return out


def frame(video: Path) -> list[list[tuple[int, int, int]]]:
    raw = run(
        [
            "-ss",
            "0.5",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )
    assert len(raw) == WIDTH * HEIGHT * 3, len(raw)
    rows = []
    for y in range(HEIGHT):
        line = raw[y * WIDTH * 3 : (y + 1) * WIDTH * 3]
        rows.append([tuple(line[x * 3 : x * 3 + 3]) for x in range(WIDTH)])
    return rows


def bright(rows: list[list[tuple[int, int, int]]]) -> list[tuple[int, int]]:
    return [(x, y) for y in range(len(rows)) for x in range(len(rows[0])) if sum(rows[y][x]) > 150]


def tinted(rows: list[list[tuple[int, int, int]]], pick) -> list[tuple[int, int]]:
    return [
        (x, y)
        for y in range(len(rows))
        for x in range(len(rows[0]))
        if pick(rows[y][x]) and sum(rows[y][x]) > 150
    ]


def contract_suite() -> None:
    default = TextStyle(body="x").model_dump()
    assert default["outline_width"] == 0.04, "the 1.62 border was 4 % of the glyph size"
    assert default["line_spacing"] == 0.2 and default["box_opacity"] == 0.45
    assert default["font"] == "yahei" and default["text_align"] == "center"
    assert default["shadow_x"] == 0.0 and default["shadow_y"] == 0.0
    for bad in (
        {"body": "x", "outline_width": 0.5},
        {"body": "x", "font": "comic sans"},
        {"body": "x", "text_align": "justify"},
        {"body": "x", "box_color": "red"},
        {"body": "x", "box_opacity": 1.5},
        {"body": "x", "line_spacing": -0.1},
        {"body": "x", "shadow_x": 2},
    ):
        try:
            TextStyle(**bad)
        except ValidationError:
            continue
        raise AssertionError(f"{bad} must not validate")
    print("   contract: the defaults are the 1.62 rendering; seven out-of-range styles refused")


def font_suite() -> None:
    published = text_fonts_available()
    assert [entry["id"] for entry in published] == list(TEXT_FONTS), published
    for entry in published:
        assert entry["family"] and entry["label"], entry
        assert Path(render_module.FONT_ROOT, TEXT_FONTS[entry["id"]][0]).is_file(), entry
    caps = capabilities(text_fonts=published)
    assert caps["features"]["text_styling"] is True
    assert caps["text_fonts"] == published
    escaped = text_font_path("hei")
    # The shape is load-bearing: with a backslash separator drawtext falls back to a default face
    # without any error, and two different fonts then render byte-identical.
    assert escaped.endswith("/simhei.ttf") and "\\:/" in escaped, escaped
    assert "\\" not in escaped.replace("\\:", ""), escaped

    # A machine without those files must say so, not draw a different face and keep quiet.
    saved_root, saved_os = render_module.FONT_ROOT, render_module.os.name
    try:
        with tempfile.TemporaryDirectory() as empty:
            render_module.FONT_ROOT = empty
            assert text_fonts_available() == []
            assert capabilities()["text_fonts"] == []
            try:
                text_font_path("hei")
            except Exception as error:
                assert getattr(error, "code", "") == "FONT_UNAVAILABLE", error
                assert "capabilities" in str(error), str(error)
            else:
                raise AssertionError("a missing face must be refused, not substituted")
    finally:
        render_module.FONT_ROOT, render_module.os.name = saved_root, saved_os
    print(
        f"   fonts: {len(published)} faces published because their files exist; with an empty font "
        "folder the list is empty and the request is refused by name"
    )


def filter_suite(video: Path) -> None:
    plain = filters(project_with(video, {}))
    size = HEIGHT * 0.06
    assert f"borderw={round(0.04 * size)}" in plain, plain
    assert "bordercolor=#000000" in plain, plain
    assert f"line_spacing={round(0.2 * size)}" in plain, plain
    assert "msyh" in plain and "x=(w-text_w)/2" in plain, plain
    assert "shadowx" not in plain and "geq=" not in plain, "no shadow or plate until asked"

    styled = filters(
        project_with(
            video,
            {
                "font": "kai",
                "text_align": "left",
                "outline_width": 0.18,
                "outline_color": "#ff0000",
                "shadow_x": 0.5,
                "shadow_y": -0.25,
                "shadow_color": "#00ff00",
                "box": True,
                "box_color": "#404040",
                "box_opacity": 0.8,
                "line_spacing": 1,
            },
        )
    )
    assert "simkai" in styled, styled
    assert f"borderw={round(0.18 * size)}" in styled, styled
    assert "bordercolor=#ff0000" in styled, styled
    assert f"shadowx={round(0.5 * size)}" in styled, styled
    assert f"shadowy={round(-0.25 * size)}" in styled, styled
    assert "shadowcolor=#00ff00" in styled, styled
    assert "x=w*0.08" in styled, styled
    assert "line_spacing=216" in styled or f"line_spacing={round(1 * size)}" in styled, styled
    assert "geq=r='64':g='64':b='64'" in styled, styled
    assert "a='if(gte(Y" in styled and ",204,0)'" in styled, styled
    right = filters(project_with(video, {"text_align": "right"}))
    assert "x=w-text_w-w*0.08" in right, right
    assert re.search("expansion=none", styled) and re.search(
        r"textfile=text-[0-9a-f]{64}\.txt", styled
    )
    assert BODY not in styled and BODY not in plain, "the body must reach FFmpeg only as a file"
    print(
        "   filter: the default style compiles to the 1.62 numbers, and every knob arrives at "
        "drawtext as an integer scaled by the glyph size"
    )


def pixel_suite(folder: Path, video: Path) -> None:
    # Bigger glyphs than the default, so a stroke-level measurement is not counting a handful of px.
    base = {"font_size": 0.12}
    plain = frame(render(project_with(video, base), folder, "t-plain.mp4"))
    plain_bright = bright(plain)
    assert len(plain_bright) > 400, len(plain_bright)

    heavy = frame(
        render(
            project_with(video, {**base, "outline_width": 0.2, "outline_color": "#ff0000"}),
            folder,
            "t-outline.mp4",
        )
    )
    red = tinted(heavy, lambda px: px[0] > 120 and px[1] < 90 and px[2] < 90)
    assert len(red) > len(plain_bright) * 0.2, (len(red), len(plain_bright))
    assert len(bright(heavy)) > len(plain_bright), "a thicker outline covers more pixels"

    shadow = frame(
        render(
            project_with(video, {**base, "shadow_x": 0.9, "shadow_color": "#00ff00"}),
            folder,
            "t-shadow.mp4",
        )
    )
    green = tinted(shadow, lambda px: px[1] > 120 and px[0] < 90 and px[2] < 90)
    assert green, "the shadow must land on the picture, not only in the request"
    shift = sum(x for x, _ in green) / len(green) - sum(x for x, _ in plain_bright) / len(
        plain_bright
    )
    assert shift > 6, (shift, round(0.9 * HEIGHT * 0.12))

    plate = frame(
        render(
            project_with(video, {**base, "box": True, "box_color": "#404040", "box_opacity": 1.0}),
            folder,
            "t-plate.mp4",
        )
    )
    band_rows = [row for row in range(HEIGHT) if 90 < sum(plate[row][10]) < 260]
    assert band_rows, "the plate has to cover a band the plain render does not have"
    level = sum(plate[band_rows[len(band_rows) // 2]][10]) / 3
    assert abs(level - 64) <= 6, level

    left = frame(render(project_with(video, {**base, "text_align": "left"}), folder, "t-left.mp4"))
    right = frame(
        render(project_with(video, {**base, "text_align": "right"}), folder, "t-right.mp4")
    )
    centre_left = sum(x for x, _ in bright(left)) / len(bright(left))
    centre_right = sum(x for x, _ in bright(right)) / len(bright(right))
    assert centre_right - centre_left > WIDTH * 0.3, (centre_left, centre_right)

    hei = frame(render(project_with(video, {**base, "font": "hei"}), folder, "t-hei.mp4"))
    song = frame(render(project_with(video, {**base, "font": "song"}), folder, "t-song.mp4"))
    differ = sum(
        1 for y in range(HEIGHT) for x in range(WIDTH) if abs(sum(hei[y][x]) - sum(song[y][x])) > 40
    )
    assert differ > 300, differ
    # Three faces must be three pictures: a silent fallback collapses them together.
    kai = frame(render(project_with(video, {**base, "font": "kai"}), folder, "t-kai.mp4"))
    collapsed = sum(
        1 for y in range(HEIGHT) for x in range(WIDTH) if abs(sum(kai[y][x]) - sum(hei[y][x])) > 40
    )
    assert collapsed > 300, collapsed
    print(
        f"   pixels: outline {len(red)} red px, shadow shifted {shift:.1f} px right of the glyphs, "
        f"plate band at {level:.0f} (asked 64), left/right centroids {centre_left:.0f} vs "
        f"{centre_right:.0f}, two faces differ on {differ} px"
    )


def http_suite(folder: Path, video: Path) -> None:
    token = "text-" + "9" * 48
    with TestClient(
        create_app(folder / "db.sqlite3", token),
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        caps = client.get("/v1/capabilities").json()
        assert caps["features"]["text_styling"] is True
        assert {entry["id"] for entry in caps["text_fonts"]} == set(TEXT_FONTS), caps["text_fonts"]
        project = client.post("/v1/projects", json={"request_id": "new", "name": "text"}).json()[
            "project"
        ]
        path = f"/v1/projects/{project['id']}"

        def edit(request_id, revision, commands, dry=False):
            return client.post(
                path + "/edits",
                json={
                    "request_id": request_id,
                    "expected_revision": revision,
                    "commands": commands,
                    "dry_run": dry,
                },
            )

        seed = [
            {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
            {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "a"}},
            {
                "op": "asset.register",
                "asset": {
                    "id": "txt",
                    "kind": "text",
                    "label": "t",
                    "reference": "r",
                    "duration_ticks": T,
                },
            },
            {
                "op": "asset.register",
                "asset": {
                    "id": "snd",
                    "kind": "audio",
                    "label": "s",
                    "reference": "r",
                    "duration_ticks": T,
                },
            },
            {
                "op": "clip.add",
                "clip": {
                    "id": "c",
                    "asset_id": "txt",
                    "track_id": "v",
                    "position_ticks": 0,
                    "duration_ticks": T,
                    "text": {"body": "标题"},
                },
            },
            {
                "op": "clip.add",
                "clip": {
                    "id": "s",
                    "asset_id": "snd",
                    "track_id": "a",
                    "position_ticks": 0,
                    "duration_ticks": T,
                },
            },
        ]
        assert edit("seed", 0, seed).status_code == 200
        style = {
            "body": "标题",
            "font_size": 0.1,
            "color": "#ffeedd",
            "align": "top",
            "box": True,
            "font": "mono",
            "text_align": "right",
            "outline_width": 0.1,
            "outline_color": "#123456",
            "shadow_x": 0.2,
            "shadow_y": -0.2,
            "shadow_color": "#654321",
            "box_color": "#223344",
            "box_opacity": 0.7,
            "line_spacing": 0.6,
        }
        saved = edit("style", 1, [{"op": "clip.text", "clip_id": "c", "text": style}])
        assert saved.status_code == 200, saved.text
        stored = saved.json()["project"]["clips"]["c"]["text"]
        assert stored == style, {
            k: (v, stored.get(k)) for k, v in style.items() if stored.get(k) != v
        }
        patched = edit(
            "patch", 2, [{"op": "clip.patch", "clip_id": "c", "text": {"outline_width": 0.02}}]
        )
        assert patched.status_code == 200, patched.text
        after = patched.json()["project"]["clips"]["c"]["text"]
        assert after["outline_width"] == 0.02 and after["font"] == "mono", after
        audio = edit("audio", 3, [{"op": "clip.patch", "clip_id": "s", "text": {"font": "hei"}}])
        assert audio.status_code == 422 and audio.json()["error"]["code"] == "INVALID_TEXT", (
            audio.json()
        )
        bad = edit("bad", 3, [{"op": "clip.text", "clip_id": "c", "text": {"outline_width": 9}}])
        assert bad.status_code == 422, bad.status_code
        assert client.get(path).json()["revision"] == 3, "a refused style write must not commit"
        print(
            "   http: a 15-field style round-trips through clip.text and clip.patch, an audio clip "
            "and an out-of-range width are refused, and the revision only moves for accepted writes"
        )


def main() -> None:
    contract_suite()
    font_suite()
    with tempfile.TemporaryDirectory(prefix="agentcut-text-") as scratch:
        folder = Path(scratch)
        video = source(folder)
        filter_suite(video)
        pixel_suite(folder, video)
        http_suite(folder, video)
    print(
        "PASS: text styling compiles to drawtext, lands in the delivered pixels, round-trips over "
        "HTTP, and keeps the 1.62 rendering for a project that never asked for any of it"
    )


if __name__ == "__main__":
    main()
