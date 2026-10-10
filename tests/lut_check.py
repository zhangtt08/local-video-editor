"""1D LUT import: the engine owns the only `.cube` reader, and its table is what FFmpeg draws.

Four independent angles, because a LUT is exactly the kind of feature that can look shipped while
reading the wrong file. The samples are asserted against the numbers we wrote into the file (truth
by construction, not by re-running the parser). The compiled `lutrgb` stage is pushed through
FFmpeg's own evaluator as a 256-level ramp, per channel, with no encoder in the way. An imported
payload goes back in through `clip.grade` as a ready-to-send node. And a real H.264 render is
measured band by band. Refusals are asserted with their reason, and so is the rule that a
half-written grade node is a bad *request*, never an internal error.
"""

import hashlib
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import ClipColor, LutParse, Project, capabilities
from agentcut.grade import grade_filter, grade_tables, parse_1d_cube
from agentcut.http_api import create_app
from agentcut.render import compile_render_plan

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/node_modules/ffmpeg-static/ffmpeg.exe"
SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,()-+*/=':")
BANDS = (4, 20, 64, 128, 196, 250)
TOLERANCE = 1.5


# A deliberate non-identity table with three different shapes, so a parser that mis-reads the row
# order, the channel order or the grid spacing cannot pass. The channels stay close to each other on
# purpose: a saturated single-channel lift would make the 4:2:0 render chroma-bleed, and the media
# stage of this check measures what the encoder actually wrote, not an idealised rgb.
def cube_rows(count: int) -> list[tuple[float, float, float]]:
    rows = []
    for index in range(count):
        value = index / (count - 1)
        red = 0.05 + 0.95 * value**1.6
        green = value**1.15
        blue = min(1.0, 1.05 * value**0.85)
        rows.append((round(red, 6), round(green, 6), round(blue, 6)))
    return rows


def neutral_rows(count: int) -> list[tuple[float, float, float]]:
    """One strong S-curve applied to all three channels, so the rendered pixels stay neutral grey.

    The per-channel shapes are proved against FFmpeg's own evaluator below, where no encoder is
    involved. This table is for the render stage: 4:2:0 chroma costs a saturated near-black pixel
    several levels all by itself, and that would measure the codec rather than the imported file.
    """
    curve = []
    for index in range(count):
        value = index / (count - 1)
        level = round(min(1.0, 1.08 * value * value * (3 - 2 * value)), 6)
        curve.append((level, level, level))
    return curve


def cube_text(count: int = 33, *, rows: list[tuple[float, float, float]] | None = None) -> str:
    lines = [f"# written by a test, {count} samples", "TITLE Film Look 01", f"LUT_1D_SIZE {count}"]
    lines += [f"{red:.6f} {green:.6f} {blue:.6f}" for red, green, blue in rows or cube_rows(count)]
    return "\n".join(lines) + "\n"


def lut_at(samples: list[float], value: float) -> float:
    """The published reading of a 1D grid: even spacing of 1/(n-1), linear between the samples."""
    if value <= 0:
        return samples[0]
    if value >= 1:
        return samples[-1]
    position = value * (len(samples) - 1)
    index = int(position)
    if index >= len(samples) - 1:
        return samples[-1]
    fraction = position - index
    return samples[index] + fraction * (samples[index + 1] - samples[index])


def run(args: list[str]) -> bytes:
    done = subprocess.run(
        [str(FFMPEG), "-v", "error", *args],
        capture_output=True,
        check=True,
        timeout=300,
        creationflags=0x08000000,
    )
    return done.stdout


def band_source(folder: Path) -> Path:
    path = folder / "bands.mp4"
    inputs: list[str] = []
    for level in BANDS:
        colour = f"0x{level:02x}{level:02x}{level:02x}"
        inputs += ["-f", "lavfi", "-i", f"color={colour}:s=60x180:r=30"]
    run(
        [
            *inputs,
            "-filter_complex",
            "hstack=inputs=6",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
    )
    return path


def band_levels(video: Path) -> list[tuple[int, int, int]]:
    raw = run(
        [
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            "scale=6:1:flags=area",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )
    assert len(raw) == 18, len(raw)
    return [tuple(raw[3 * band : 3 * band + 3]) for band in range(6)]


def project_with(source: Path, grade: list[dict]) -> Project:
    verified = {
        "probe_id": "a",
        "path": str(source),
        "kind": "video",
        "label": "bands",
        "size_bytes": source.stat().st_size,
        "content_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "duration_ticks": T,
        "width": 360,
        "height": 180,
        "has_audio": False,
    }
    return Project.model_validate(
        {
            "id": "p",
            "name": "lut",
            "settings": {"width": 360, "height": 180},
            "tracks": [{"id": "v", "kind": "video", "name": "v"}],
            "assets": {
                "a": {
                    "id": "a",
                    "kind": "video",
                    "label": "bands",
                    "reference": "unused",
                    "duration_ticks": T,
                    "verified": verified,
                }
            },
            "clips": {
                "c": {
                    "id": "c",
                    "asset_id": "a",
                    "track_id": "v",
                    "position_ticks": 0,
                    "duration_ticks": T,
                    "color": {"grade": grade},
                }
            },
        }
    )


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


def ramp_through(stage: str) -> list[tuple[int, int, int]]:
    """FFmpeg's own answer for all 256 input levels, with no encoder and no project in the way."""
    raw = run(
        [
            "-f",
            "lavfi",
            "-i",
            f"nullsrc=s=256x2:r=1,format=rgb24,geq=r='X':g='X':b='X',{stage}",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )
    return [tuple(raw[768 + 3 * column : 768 + 3 * column + 3]) for column in range(256)]


def parse_suite() -> dict:
    rows = cube_rows(33)
    payload = parse_1d_cube(cube_text(33))
    assert payload["title"] == "Film Look 01", payload["title"]
    assert payload["size"] == 33 and len(payload["channels"][0]) == 33
    for channel in range(3):
        got = payload["channels"][channel]
        want = [row[channel] for row in rows]
        assert got == want, (channel, got[:3], want[:3])
    assert "resampled_from" not in payload

    # Values outside 0..1 are clamped: the contract's domain is 0..1 and a file may overshoot.
    overshoot = parse_1d_cube("LUT_1D_SIZE 2\n-0.4 1.2 0.5\n1.5 -1.0 0.5")
    assert overshoot["channels"] == [[0.0, 1.0], [1.0, 0.0], [0.5, 0.5]], overshoot["channels"]

    # A quoted title, lowercase keywords, comments, and CRLF endings are all out in the wild.
    lower = parse_1d_cube("lut_1d_size 2\r\n# note\r\n\r\n0 0 0\r\n1 1 1\r\n")
    assert lower["size"] == 2 and lower["title"] == "LUT", lower
    assert lower["channels"][0] == [0.0, 1.0]
    named = parse_1d_cube('TITLE "Kodak 2383 print"\nLUT_1D_SIZE 2\n0 0 0\n1 1 1\n')
    assert named["title"] == "Kodak 2383 print", named["title"]

    # 1024 rows fit the contract as they are; anything bigger is resampled and says so out loud.
    assert parse_1d_cube(cube_text(1024))["size"] == 1024
    ClipColor(grade=[{"kind": "lut", **parse_1d_cube(cube_text(256))}])
    large = parse_1d_cube("LUT_1D_SIZE 2048\n" + "\n".join("0.25 0.5 0.75" for _ in range(2048)))
    assert large["size"] == capabilities()["grade_limits"]["max_lut_samples"], large["size"]
    assert large["resampled_from"] == 2048 and large["channels"][1][0] == 0.5

    refusals = {
        "LUT_3D_SIZE 2\n0 0 0\n1 1 1\n": "3D LUT",
        "0 0 0\n1 1 1\n": "LUT_1D_SIZE",
        "LUT_1D_SIZE 3\n0 0 0\n1 1 1\n": "expected 3 rows",
        # More rows than the header counts is the same lie in the other direction: trusting the
        # header would silently drop the tail, trusting the rows would move every grid point.
        "LUT_1D_SIZE 2\n0 0 0\n0.5 0.5 0.5\n1 1 1\n": "expected 2 rows",
        "LUT_1D_SIZE 2\n0 0 0\n1 1\n": "cannot read the row",
        "LUT_1D_SIZE 2\n0 0 0\n1 1 1\nDOMAIN_MIN 0.1 0.1 0.1\n": "DOMAIN",
        "LUT_1D_SIZE x\n": "whole number",
    }
    for text, reason in refusals.items():
        try:
            parse_1d_cube(text)
        except Exception as error:
            assert reason.lower() in str(error).lower(), (text[:24], str(error))
            assert type(error).__name__ == "EditorError" and error.code == "INVALID_LUT"
            assert error.status == 422
        else:
            raise AssertionError(f"{text!r} must be refused")
    try:
        LutParse(content="")
    except ValidationError:
        pass
    else:
        raise AssertionError("an empty file must be refused by the contract")
    print(
        "   parse: the samples come back exactly as written, clamps and resamples are honest, "
        "and seven malformed files are each refused with their reason"
    )
    return payload


def table_suite(payload: dict) -> None:
    """The compiled per-channel table is the file's own curve, within a level and a half."""
    rows = cube_rows(payload["size"])
    color = ClipColor(grade=[{"kind": "lut", **payload}])
    compiled = grade_tables(color)
    assert compiled is not None and len(compiled["stages"]) == 1, compiled
    tables = compiled["stages"][0]
    assert tables["type"] == "lut", tables
    assert tables is not None and len(tables["r"]) == 256
    worst = 0.0
    for channel, name in enumerate(("r", "g", "b")):
        samples = [row[channel] for row in rows]
        for level in range(256):
            want = lut_at(samples, level / 255) * 255
            worst = max(worst, abs(tables[name][level] * 255 - want))
    assert worst <= TOLERANCE, worst
    print(f"   table: all 768 browser entries follow the file within {worst:.3f} levels")

    stage = grade_filter(color)
    assert stage.startswith("lutrgb=") and len(stage) < 6000, len(stage)
    assert set(stage) <= SAFE, sorted(set(stage) - SAFE)
    drawn = ramp_through(stage)
    drift = {}
    for channel, name in enumerate(("r", "g", "b")):
        samples = [row[channel] * 255 for row in rows]
        drift[name] = max(
            abs(drawn[level][channel] - lut_at(samples, level / 255)) for level in range(256)
        )
    assert max(drift.values()) <= TOLERANCE + 0.5, drift
    print(
        "   ffmpeg: FFmpeg's own evaluator of the compiled stage tracks the file's own ramps "
        f"on all 256 inputs (red {drift['r']:.2f}, green {drift['g']:.2f}, blue {drift['b']:.2f})"
    )

    # A LUT is one node among others: mixed into a chain it still collapses to one shared table.
    chain = ClipColor(
        grade=[
            {"kind": "lut", **payload, "mix": 0.5},
            {
                "kind": "curve",
                "channel": "rgb",
                "points": [{"x": 0, "y": 0}, {"x": 0.5, "y": 0.4}, {"x": 1, "y": 1}],
            },
        ]
    )
    chained_chain = grade_tables(chain)
    assert chained_chain is not None and len(chained_chain["stages"]) == 1, chained_chain
    chained = chained_chain["stages"][0]
    assert chained["id"] != tables["id"]
    half = max(
        abs(chained["r"][level] * 255 - (tables["r"][level] + level) / 2) for level in range(256)
    )
    assert half * 2 < 255, half
    assert grade_filter(ClipColor(grade=[{"kind": "lut", **payload, "mix": 0.0}])) == "", (
        "a LUT at zero strength must not add a stage at all"
    )
    assert grade_tables(ClipColor(grade=[{"kind": "lut", **payload, "enabled": False}])) is None

    # A LUT is also a legal branch of a parallel node. Averaging it with a sibling must still be one
    # table per channel, so this checks the composition rule, not just the node itself.
    factors = (1 + 0.30 * 0.4, 1.0, 1 - 0.30 * 0.4)
    merged_chain = grade_tables(
        ClipColor(
            grade=[
                {
                    "kind": "parallel",
                    "branches": [
                        {"kind": "lut", **payload},
                        {"kind": "white_balance", "temperature": 0.4, "tint": 0.0},
                    ],
                }
            ]
        )
    )
    assert merged_chain is not None and len(merged_chain["stages"]) == 1, merged_chain
    merged = merged_chain["stages"][0]
    worst = 0.0
    for channel, name in enumerate(("r", "g", "b")):
        samples = [row[channel] for row in rows]
        for level in range(256):
            value = level / 255
            branch = min(1.0, max(0.0, value * factors[channel]))
            want = (lut_at(samples, value) + branch) / 2
            worst = max(worst, abs(merged[name][level] - want) * 255)
    assert worst <= TOLERANCE, worst
    print(
        f"   parallel: a LUT branch averaged with a white-balance sibling stays one table "
        f"(worst {worst:.3f} levels)"
    )
    print("   chain: a LUT composes with a curve node, and mix 0 / disabled still bypass the stage")


def media_suite(folder: Path) -> None:
    source = band_source(folder)
    payload = parse_1d_cube(cube_text(33, rows=neutral_rows(33)))
    plain = band_levels(render(project_with(source, []), folder, "lut-plain.mp4"))
    graded = band_levels(
        render(project_with(source, [{"kind": "lut", **payload}]), folder, "lut-on.mp4")
    )
    tables = grade_tables(ClipColor(grade=[{"kind": "lut", **payload}]))["stages"][0]
    # The bands are measured after they arrive on disk, so the comparison is against what the
    # encoder actually wrote: near-black costs a level or two of its own.
    for band, levels in enumerate(plain):
        for channel, level in enumerate(levels):
            assert abs(level - BANDS[band]) <= 4, (band, level, BANDS[band])
    moved = 0.0
    for band, arrived in enumerate(plain):
        for channel, name in enumerate(("r", "g", "b")):
            want = tables[name][arrived[channel]] * 255
            drift = abs(graded[band][channel] - want)
            moved = max(moved, abs(graded[band][channel] - arrived[channel]))
            assert drift <= 4, (band, arrived, name, graded[band][channel], want, drift)
    assert moved > 24, moved
    print(
        "   media: rendered bands "
        + str([list(value) for value in plain])
        + " become "
        + str([list(value) for value in graded])
        + f" against the imported table (largest shift {round(moved)} levels, all 18 samples)"
    )


def http_suite(folder: Path) -> None:
    token = "lut-" + "c" * 48
    with TestClient(
        create_app(folder / "db.sqlite3", token),
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        caps = client.get("/v1/capabilities").json()
        assert caps["features"]["lut_import"] is True
        assert caps["grade_limits"]["max_lut_samples"] == 1024
        assert caps["grade_limits"]["max_nodes"] == 8
        assert "LutParse" in client.get("/v1/contracts").json()

        reply = client.post("/v1/lut/parse", json={"content": cube_text(17)})
        assert reply.status_code == 200, reply.text
        payload = reply.json()
        assert payload["size"] == 17 and len(payload["channels"][2]) == 17

        refused = client.post("/v1/lut/parse", json={"content": "LUT_3D_SIZE 4\n0 0 0\n"})
        assert refused.status_code == 422 and refused.json()["error"]["code"] == "INVALID_LUT", (
            refused.status_code,
            refused.json(),
        )
        # 1.103 起这个端点两种表都认，所以这份文件被拒的理由必须是「行数不是 size³」，
        # 而不是「这里不接受 3D」；完整的 3D 表逐段验在 tests/lut3d_check.py。
        message = refused.json()["error"]["message"]
        assert "expected 64 rows" in message and "cube" in message, message
        assert "not supported" not in message, message

        project = client.post("/v1/projects", json={"request_id": "new", "name": "lut"}).json()[
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
            {"op": "track.add", "track": {"id": "s", "kind": "audio", "name": "s"}},
            {
                "op": "asset.register",
                "asset": {
                    "id": "pic",
                    "kind": "video",
                    "label": "p",
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
                    "asset_id": "pic",
                    "track_id": "v",
                    "position_ticks": 0,
                    "duration_ticks": T,
                },
            },
            {
                "op": "clip.add",
                "clip": {
                    "id": "s",
                    "asset_id": "snd",
                    "track_id": "s",
                    "position_ticks": 0,
                    "duration_ticks": T,
                },
            },
        ]
        assert edit("seed", 0, seed).status_code == 200

        # The parse reply is a ready-to-send node: straight from the file into `clip.grade`.
        saved = edit(
            "lut1",
            1,
            [
                {
                    "op": "clip.grade",
                    "clip_id": "c",
                    "grade": [{"kind": "lut", **payload, "title": payload["title"][:64]}],
                }
            ],
        )
        assert saved.status_code == 200, saved.text
        node = saved.json()["project"]["clips"]["c"]["color"]["grade"][0]
        assert node["kind"] == "lut" and node["size"] == 17
        assert node["channels"] == payload["channels"], "the round trip must not lose samples"
        replay = edit(
            "lut1",
            1,
            [
                {
                    "op": "clip.grade",
                    "clip_id": "c",
                    "grade": [{"kind": "lut", **payload, "title": payload["title"][:64]}],
                }
            ],
        )
        assert replay.status_code == 200 and replay.json()["replayed"] is True
        assert replay.json()["project"]["revision"] == 2

        # A grade node reaching `clip.patch` is an `Any` value in that contract, but the command
        # union still resolves it against the node models: every payload below is refused by the
        # contract boundary with the offending field named in `details.issues` -- never an internal
        # error, and never written to the project.
        node = {"kind": "lut", "size": 2, "channels": [[0.0, 1.0], [0.0, 0.5], [0.0, 1.0]]}
        broken = [
            {
                "op": "clip.patch",
                "clip_id": "c",
                "color": {"grade": [{"kind": "lut", "size": 3, "channels": node["channels"]}]},
            },
            {
                "op": "clip.patch",
                "clip_id": "c",
                "color": {
                    "grade": [
                        {"kind": "lut", "size": 2, "channels": [[0.0, 1.0], [0.0, 0.5], [0.0, 1.5]]}
                    ]
                },
            },
            {"op": "clip.patch", "clip_id": "c", "color": {"grade": [{"kind": "spectron"}]}},
            {"op": "clip.patch", "clip_id": "c", "color": {"grade": [node] * 9}},
            {"op": "clip.patch", "clip_id": "c", "effects": {"opacity": 7}},
            {"op": "clip.patch", "clip_id": "c", "text": {"font_size": "big"}},
            {
                "op": "clip.grade",
                "clip_id": "c",
                "grade": [{"kind": "lut", "size": 2, "channels": [[0.0, 1.0], [0.0, 0.5]]}],
            },
        ]
        for position, command in enumerate(broken):
            answer = edit(f"bad-{position}", 2, [command])
            assert answer.status_code == 422, (command, answer.status_code, answer.text[:400])
            error = answer.json()["error"]
            assert error["code"] == "INVALID_REQUEST", error
            assert error["details"]["issues"], error
            assert client.get(path).json()["revision"] == 2, "a refused write must not move it"
        assert client.get(path).json()["clips"]["c"]["color"]["grade"][0]["size"] == 17

        audio = edit("bad-audio", 2, [{"op": "clip.patch", "clip_id": "s", "color": {"grade": []}}])
        assert audio.status_code == 422 and audio.json()["error"]["code"] == "INVALID_COLOR"

        preview = client.post("/v1/preview-manifest", json=client.get(path).json()).json()
        grade = preview["clips"]["c"]["grade"]
        assert grade is not None and len(grade["stages"]) == 1, grade
        stage = grade["stages"][0]
        assert len(stage["r"]) == 256 and stage["id"].startswith("l")
        assert f"url(#{grade['id']})" in preview["clips"]["c"]["color_filter"]
        print(
            "   http: parse -> clip.grade round-trips 17x3 samples, seven bad payloads answer 422 "
            "INVALID_REQUEST naming the field, and the browser table ships with the manifest"
        )


def main() -> None:
    payload = parse_suite()
    table_suite(payload)
    with tempfile.TemporaryDirectory(prefix="agentcut-lut-") as scratch:
        folder = Path(scratch)
        media_suite(folder)
        http_suite(folder)
    print(
        "PASS: .cube 1D import parsed by one engine reader, compiled into the shared per-channel "
        "table, drawn by FFmpeg, rendered into real pixels, and refused by name when it is not"
    )


main()
