"""Grade nodes: one per-channel polyline feeds FFmpeg and the browser table; edits stay atomic."""

import hashlib
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentcut.animation import preview_manifest
from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import ClipColor, EditBatch, Project
from agentcut.grade import grade_filter, grade_tables
from agentcut.http_api import create_app
from agentcut.projects import ProjectStore
from agentcut.render import compile_render_plan

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/node_modules/ffmpeg-static/ffmpeg.exe"

RGB_CURVE = {
    "kind": "curve",
    "channel": "rgb",
    "points": [
        {"x": 0.0, "y": 0.0},
        {"x": 0.25, "y": 0.15},
        {"x": 0.5, "y": 0.62},
        {"x": 0.75, "y": 0.9},
        {"x": 1.0, "y": 1.0},
    ],
}
GREEN_CURVE = {**RGB_CURVE, "channel": "green"}
WHEELS = {
    "kind": "wheels",
    "lift": [0.06, -0.02, 0.0],
    "gamma": [1.1, 1.0, 0.92],
    "gain": [1.05, 1.0, 0.96],
}
BALANCE = {"kind": "white_balance", "temperature": 0.3, "tint": -0.2}
BANDS = (32, 128, 224)
SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,()-+*/=':")


def clamp(value: float) -> float:
    return 0.0 if value < 0 else 1.0 if value > 1 else value


# Quoted from the published definitions, not imported from agentcut.grade, so the shipped compiler
# and this reference share nothing but the specs.
GAMMAS = {"gamma18": 1.8, "gamma20": 2.0, "gamma22": 2.2, "gamma24": 2.4, "rec709": 2.4}


def decode(space: str, value: float) -> float:
    if space == "linear":
        return value
    if space == "srgb":
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
    return value ** GAMMAS[space]


def encode(space: str, value: float) -> float:
    if space == "linear":
        return value
    if space == "srgb":
        return 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055
    return value ** (1 / GAMMAS[space])


def blend_reference(mode: str, backdrop: float, picture: float) -> float:
    """The W3C separable blend functions, written out independently of the shipped module."""
    if mode == "normal":
        return picture
    if mode == "multiply":
        return backdrop * picture
    if mode == "screen":
        return backdrop + picture - backdrop * picture
    if mode == "overlay":
        if backdrop <= 0.5:
            return 2.0 * backdrop * picture
        return 1.0 - 2.0 * (1.0 - backdrop) * (1.0 - picture)
    if mode == "darken":
        return min(backdrop, picture)
    if mode == "lighten":
        return max(backdrop, picture)
    if mode == "difference":
        return abs(backdrop - picture)
    if mode == "exclusion":
        return backdrop + picture - 2.0 * backdrop * picture
    raise AssertionError(mode)


def predict(nodes: list[dict], index: int) -> list[float]:
    """Reference 256-entry transfer table, evaluated here without the shipped compiler."""

    def curve(node: dict, value: float) -> float:
        xs = [point["x"] for point in node["points"]]
        ys = [point["y"] for point in node["points"]]
        if value <= xs[0]:
            return ys[0]
        if value >= xs[-1]:
            return ys[-1]
        step = next(i for i in range(len(xs) - 1) if value <= xs[i + 1])
        return ys[step] + (value - xs[step]) * (ys[step + 1] - ys[step]) / (xs[step + 1] - xs[step])

    table = []
    for position in range(256):
        value = position / 255
        for node in nodes:
            if not node.get("enabled", True) or not node.get("mix", 1):
                continue
            before = value
            if node["kind"] == "curve":
                channel = node.get("channel", "rgb")
                if channel == "rgb" or {"red": 0, "green": 1, "blue": 2}[channel] == index:
                    value = curve(node, value)
            elif node["kind"] == "transfer":
                value = clamp(encode(node["output_space"], decode(node["input_space"], value)))
            elif node["kind"] == "white_balance":
                warm, green, shift = 0.30, 0.20, 0.10
                factors = (
                    1 + warm * node["temperature"] + shift * node["tint"],
                    1 - green * node["tint"],
                    1 - warm * node["temperature"] + shift * node["tint"],
                )
                value = clamp(value * factors[index])
            else:
                value = clamp(
                    max(value, 0.0) ** (1 / node["gamma"][index]) * node["gain"][index]
                    + node["lift"][index]
                )
            value = clamp(
                before
                + node.get("mix", 1)
                * (blend_reference(node.get("blend", "normal"), before, value) - before)
            )
        table.append(clamp(value))
    return table


def run(args: list[str]) -> bytes:
    result = subprocess.run(
        [str(FFMPEG), "-v", "error", *args],
        capture_output=True,
        check=True,
        timeout=120,
        creationflags=0x08000000,
    )
    return result.stdout


def banded_source(folder: Path) -> Path:
    path = folder / "bands.mp4"
    inputs = []
    for level in BANDS:
        colour = f"0x{level:02x}{level:02x}{level:02x}"
        inputs += ["-f", "lavfi", "-i", f"color={colour}:s=120x180:r=30"]
    run(
        [
            *inputs,
            "-filter_complex",
            "hstack=inputs=3",
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


def make_project(source: Path, grade: list[dict], color: dict | None = None) -> Project:
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
            "name": "grade",
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
                    "color": {"grade": grade, **(color or {})},
                }
            },
        }
    )


def render(project: Project, folder: Path, name: str) -> Path:
    out = folder / name
    plan = compile_render_plan(project, "h264-source-quality")
    for file_name, body in plan.text_files.items():
        (folder / file_name).write_text(body, encoding="utf-8")
    result = subprocess.run(
        plan.ffmpeg_argv(str(FFMPEG), str(out)),
        cwd=folder,
        capture_output=True,
        timeout=180,
        creationflags=0x08000000,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")[-800:]
    return out


def band_levels(video: Path) -> list[list[float]]:
    raw = run(
        [
            "-ss",
            "0.5",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            "scale=3:1:flags=area",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )
    assert len(raw) == 9, len(raw)
    return [[raw[3 * band + channel] for band in range(3)] for channel in range(3)]


def http_suite(folder: Path) -> None:
    token = "grade-" + "b" * 48
    with TestClient(
        create_app(folder / "db.sqlite3", token),
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        capabilities = client.get("/v1/capabilities").json()
        assert capabilities["project_schema_version"] == 11
        assert capabilities["features"]["grade_nodes"] is True
        assert "clip.grade" in capabilities["commands"]

        project = client.post("/v1/projects", json={"request_id": "new", "name": "grade"}).json()[
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
                    "track_id": "a",
                    "position_ticks": 0,
                    "duration_ticks": T,
                },
            },
        ]
        response = edit("seed", 0, seed)
        assert response.status_code == 200, response.text

        nodes = [RGB_CURVE, WHEELS]
        command = {"op": "clip.grade", "clip_id": "c", "grade": nodes}
        first = edit("g1", 1, [command])
        assert first.status_code == 200, first.text
        saved = first.json()["project"]["clips"]["c"]["color"]
        assert saved["grade"][0]["points"][2]["y"] == 0.62
        assert (saved["exposure"], saved["contrast"], saved["saturation"]) == (0.0, 1.0, 1.0), (
            "a grade write must not disturb the legacy tone controls"
        )

        replay = edit("g1", 1, [command])
        assert replay.json()["replayed"] is True and replay.json()["project"]["revision"] == 2

        conflict = edit("g2", 1, [{"op": "clip.grade", "clip_id": "c", "grade": []}])
        assert conflict.status_code == 409, conflict.text

        dry = edit("g3", 2, [{"op": "clip.grade", "clip_id": "c", "grade": [BALANCE]}], dry=True)
        assert dry.status_code == 200 and not dry.json()["committed"], dry.text
        assert dry.json()["project"]["clips"]["c"]["color"]["grade"][0]["kind"] == "white_balance"
        assert client.get(path).json()["revision"] == 2

        audio = edit("g4", 2, [{"op": "clip.grade", "clip_id": "s", "grade": [BALANCE]}])
        assert audio.json()["error"]["code"] == "INVALID_COLOR", audio.text
        assert client.get(path).json()["revision"] == 2

        descending = {
            "kind": "curve",
            "points": [{"x": 0.5, "y": 0.5}, {"x": 0.25, "y": 0.75}],
        }
        bad = edit("g5", 2, [{"op": "clip.grade", "clip_id": "c", "grade": [descending]}])
        assert bad.status_code == 422, bad.text
        too_many = edit("g5b", 2, [{"op": "clip.grade", "clip_id": "c", "grade": [WHEELS] * 9}])
        assert too_many.status_code == 422, too_many.text

        patch = edit(
            "g6",
            2,
            [
                {"op": "clip.patch", "clip_id": "c", "color": {"exposure": 0.5}},
                {"op": "clip.patch", "clip_id": "c", "color": {"grade": [BALANCE]}},
            ],
        )
        assert patch.status_code == 200, patch.text
        merged = patch.json()["project"]["clips"]["c"]["color"]
        assert merged["exposure"] == 0.5 and merged["grade"][0]["kind"] == "white_balance", merged

        cleared = edit(
            "g7",
            3,
            [
                {"op": "clip.patch", "clip_id": "c", "color": {"grade": []}},
                {"op": "clip.patch", "clip_id": "c", "color": {"exposure": 0.0}},
            ],
        )
        result = cleared.json()["project"]["clips"]["c"]["color"]
        assert result["grade"] == [] and result["exposure"] == 0.0, result

        locked = edit(
            "g8",
            4,
            [
                {"op": "track.update", "track_id": "v", "locked": True},
                {"op": "clip.grade", "clip_id": "c", "grade": [WHEELS]},
            ],
        )
        assert locked.json()["error"]["code"] == "TRACK_LOCKED", locked.text
        assert client.get(path).json()["revision"] == 4, "locked batch must not write"

        unlock = edit("g9", 4, [{"op": "track.update", "track_id": "v", "locked": False}])
        assert unlock.status_code == 200, unlock.text
        manifest = client.post("/v1/preview-manifest", json=unlock.json()["project"]).json()
        assert manifest["clips"]["c"]["grade"] is None, "an empty chain must not request a LUT"

        written = edit(
            "g10",
            5,
            [{"op": "clip.grade", "clip_id": "c", "grade": [WHEELS, GREEN_CURVE]}],
        )
        assert written.status_code == 200, written.text
        tables = client.post("/v1/preview-manifest", json=written.json()["project"]).json()[
            "clips"
        ]["c"]
        grade = tables["grade"]
        assert grade["id"].startswith("g") and len(grade["r"]) == 256
        assert f"url(#{grade['id']})" in tables["color_filter"]
        for index, channel in enumerate(("r", "g", "b")):
            expected = predict([WHEELS, GREEN_CURVE], index)
            for sample in (0, 40, 128, 200, 255):
                assert abs(grade[channel][sample] - expected[sample]) * 255 < 0.75, (
                    channel,
                    sample,
                )

        history = client.get(path + "/history").json()["history"]
        restore = client.post(
            path + "/restore",
            json={
                "request_id": "g11",
                "expected_revision": 6,
                "target_revision": next(h["revision"] for h in history if h["revision"] == 1),
            },
        )
        assert restore.status_code == 200, restore.text
        assert restore.json()["project"]["revision"] == 7
        restored = restore.json()["project"]
        assert restored["clips"]["c"]["color"]["grade"] == [], restored["clips"]["c"]["color"]
        assert restored["revision"] == 7

        half = {**RGB_CURVE, "mix": 0.5}
        mixed = edit("g12", 7, [{"op": "clip.grade", "clip_id": "c", "grade": [half]}])
        assert mixed.status_code == 200, mixed.text
        stored = mixed.json()["project"]["clips"]["c"]["color"]["grade"][0]
        assert stored["mix"] == 0.5, stored
        tables = client.post("/v1/preview-manifest", json=mixed.json()["project"]).json()["clips"][
            "c"
        ]["grade"]
        reference = predict([RGB_CURVE], 0)
        for sample in (0, 40, 128, 200, 255):
            assert abs(tables["r"][sample] - (reference[sample] + sample / 255) / 2) < 1e-6, (
                sample,
                tables["r"][sample],
            )
            assert abs(tables["g"][sample] - tables["r"][sample]) < 1e-9, sample

        skipped = edit(
            "g13", 8, [{"op": "clip.grade", "clip_id": "c", "grade": [{**RGB_CURVE, "mix": 0}]}]
        )
        assert skipped.status_code == 200, skipped.text
        assert skipped.json()["project"]["clips"]["c"]["color"]["grade"][0]["mix"] == 0
        assert (
            client.post("/v1/preview-manifest", json=skipped.json()["project"]).json()["clips"][
                "c"
            ]["grade"]
            is None
        ), "a zero-strength chain must not ask for a LUT"
        assert grade_filter(ClipColor.model_validate({"grade": [{**RGB_CURVE, "mix": 0}]})) == ""

        too_much = edit(
            "g14", 9, [{"op": "clip.grade", "clip_id": "c", "grade": [{**RGB_CURVE, "mix": 1.5}]}]
        )
        assert too_much.status_code == 422, too_much.text
        assert client.get(path).json()["revision"] == 9, "an invalid strength must not write"

        plain_node = EditBatch.model_validate(
            {
                "request_id": "old-shape",
                "expected_revision": 9,
                "commands": [{"op": "clip.grade", "clip_id": "c", "grade": [RGB_CURVE]}],
            }
        )
        explicit_node = EditBatch.model_validate(
            {
                "request_id": "old-shape",
                "expected_revision": 9,
                "commands": [
                    {"op": "clip.grade", "clip_id": "c", "grade": [{**RGB_CURVE, "mix": 1.0}]}
                ],
            }
        )
        assert ProjectStore._fingerprint("edit", plain_node) == ProjectStore._fingerprint(
            "edit", explicit_node
        ), "a v10 node without strength keeps its stored receipt digest"


def media_suite(folder: Path) -> None:
    source = banded_source(folder)
    levels = band_levels(render(make_project(source, []), folder, "plain.mp4"))
    for channel in range(3):
        for band, expected in enumerate(BANDS):
            assert abs(levels[channel][band] - expected) <= 4, levels

    nodes = [GREEN_CURVE, WHEELS]
    measured = band_levels(render(make_project(source, nodes), folder, "graded.mp4"))
    tables = grade_tables(make_project(source, nodes).clips["c"].color)
    for channel in range(3):
        expected = predict(nodes, channel)
        for band, input_level in enumerate(BANDS):
            assert abs(measured[channel][band] - expected[input_level] * 255) <= 4, (
                channel,
                band,
                measured[channel][band],
                expected[input_level] * 255,
            )
            assert abs(tables["rgb"[channel]][input_level] - expected[input_level]) * 255 <= 1.5, (
                "browser LUT drifted from the rendered pixels",
                channel,
                band,
            )

    half_nodes = [{**GREEN_CURVE, "mix": 0.5}, {**WHEELS, "mix": 0.5}]
    half = band_levels(render(make_project(source, half_nodes), folder, "halfmix.mp4"))
    half_tables = grade_tables(make_project(source, half_nodes).clips["c"].color)
    for channel in range(3):
        reference = predict(half_nodes, channel)
        for band, input_level in enumerate(BANDS):
            assert abs(half[channel][band] - reference[input_level] * 255) <= 4, (
                channel,
                band,
                half[channel][band],
                reference[input_level] * 255,
            )
            assert (
                abs(half_tables["rgb"[channel]][input_level] - reference[input_level]) * 255 <= 1.5
            )
    apart = max(abs(half[c][b] - measured[c][b]) for c in range(3) for b in range(3))
    assert apart > 6, ("half strength must land away from full strength in the pixels", apart)

    stage = grade_filter(make_project(source, nodes).clips["c"].color)
    assert stage.startswith("lutrgb=") and len(stage) < 6000, len(stage)
    assert set(stage) <= SAFE, set(stage) - SAFE
    assert ";" not in stage and '"' not in stage and "\\" not in stage and " " not in stage
    assert (
        grade_filter(make_project(source, [{**RGB_CURVE, "enabled": False}]).clips["c"].color) == ""
    )
    assert grade_tables(make_project(source, []).clips["c"].color) is None

    tone_only = make_project(source, [], {"exposure": 0.5, "saturation": 0.4})
    legacy_only = "\n".join(compile_render_plan(tone_only, "h264-source-quality").filters)
    assert "colorchannelmixer=rr=" in legacy_only
    assert "if(lt(val," not in legacy_only, "an empty chain must add no grade stage"

    both = "\n".join(
        compile_render_plan(
            make_project(source, [WHEELS], {"exposure": 0.5}), "h264-source-quality"
        ).filters
    )
    assert "colorchannelmixer=rr=" in both and "lutrgb=r='clip(if(lt(val," in both, both[:400]
    assert both.index("colorchannelmixer=rr=") < both.index("lutrgb=r='clip(if(lt(val"), (
        "legacy tone must be applied before the grade chain"
    )

    v9 = Project.model_validate(
        {
            "id": "old",
            "name": "v9",
            "schema_version": 9,
            "settings": {"width": 360, "height": 180},
            "tracks": [{"id": "v", "kind": "video", "name": "v"}],
            "assets": {
                "a": {
                    "id": "a",
                    "kind": "video",
                    "label": "a",
                    "reference": "r",
                    "duration_ticks": T,
                }
            },
            "clips": {
                "c": {
                    "id": "c",
                    "asset_id": "a",
                    "track_id": "v",
                    "position_ticks": 0,
                    "duration_ticks": T,
                    "color": {"exposure": 1.0, "contrast": 1.2, "saturation": 0.8},
                }
            },
        }
    )
    assert v9.clips["c"].color.grade == []
    assert preview_manifest(v9)["clips"]["c"]["grade"] is None


def main():
    with tempfile.TemporaryDirectory(prefix="agentcut-grade-") as scratch:
        folder = Path(scratch)
        http_suite(folder)
        media_suite(folder)
        transfer_suite(folder)
        blend_suite(folder)
    print(
        "PASS: grade node contracts, atomic HTTP edits, replay/lock/restore, "
        "browser LUT parity and real H.264 pixels"
    )


TOE_BANDS = (0, 4, 12, 32, 96, 255)


def toe_source(folder: Path) -> Path:
    """Six equal bands, three of them inside the toe where a coarse sampling grid goes wrong."""
    target = folder / "toe.mp4"
    inputs: list[str] = []
    for level in TOE_BANDS:
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
            str(target),
        ]
    )
    return target


def toe_levels(video: Path) -> list[float]:
    """Area scaling to 6x1 box-averages each 60x180 band into one number."""
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
    return [raw[3 * band] for band in range(6)]


def transfer_suite(folder: Path) -> None:
    """Colour-space nodes: the published function, the browser table and the rendered pixels."""
    source = toe_source(folder)
    for space in ("linear", "srgb", "gamma18", "gamma20", "gamma22", "gamma24", "rec709"):
        worst = max(
            abs(encode(space, decode(space, value / 255)) * 255 - value) for value in range(256)
        )
        assert worst < 1e-9, (space, worst)
    assert abs(decode("srgb", 0.5) - 0.214041) < 1e-5, decode("srgb", 0.5)
    assert abs(encode("srgb", 0.18) * 255 - 117.65) < 0.1, encode("srgb", 0.18)
    assert decode("rec709", 0.5) == decode("gamma24", 0.5), "BT.1886 without lift is gamma 2.4"

    pairs = (
        ("srgb", "rec709"),
        ("rec709", "srgb"),
        ("linear", "srgb"),
        ("srgb", "linear"),
        ("gamma22", "srgb"),
        ("srgb", "gamma18"),
    )
    for source_space, target_space in pairs:
        nodes = [{"kind": "transfer", "input_space": source_space, "output_space": target_space}]
        tables = grade_tables(make_project(source, nodes).clips["c"].color)
        reference = predict(nodes, 0)
        worst = max(abs(tables["r"][value] - reference[value]) for value in range(256))
        assert worst * 255 <= 0.5, (source_space, target_space, worst * 255)
    print("   transfer: the browser table follows the published function within half a level")

    plain = toe_levels(render(make_project(source, []), folder, "toe-plain.mp4"))
    for band, level in enumerate(TOE_BANDS):
        assert abs(plain[band] - level) <= 4, (band, level, plain)

    nodes = [{"kind": "transfer", "input_space": "srgb", "output_space": "rec709"}]
    graded = toe_levels(render(make_project(source, nodes), folder, "toe-srgb-rec709.mp4"))
    reference = predict(nodes, 0)
    tables = grade_tables(make_project(source, nodes).clips["c"].color)
    # Compare against the levels that actually arrived on disk (the source encode itself shifts
    # near-black by a level or two), so this measures the grade stage and not the codec.
    arrived = [round(value) for value in plain]
    for band, level in enumerate(TOE_BANDS):
        assert abs(graded[band] - reference[arrived[band]] * 255) <= 4, (
            band,
            arrived[band],
            graded[band],
            reference[arrived[band]] * 255,
        )
        assert abs(tables["r"][level] - reference[level]) * 255 <= 1.5, (band, level)
    assert graded[2] - graded[1] > 6, "the toe must lift visibly, not by a rounding"
    print(
        "   transfer: rendered bands "
        + str(arrived)
        + " become "
        + str([round(value) for value in graded])
        + " against the published curve "
        + str([round(reference[level] * 255) for level in arrived])
    )

    half_nodes = [{"kind": "transfer", "input_space": "srgb", "output_space": "rec709", "mix": 0.5}]
    half = toe_levels(render(make_project(source, half_nodes), folder, "toe-half.mp4"))
    half_reference = predict(half_nodes, 0)
    for band, level in enumerate(arrived):
        assert abs(half[band] - half_reference[level] * 255) <= 4, (band, level)
    assert grade_filter(make_project(source, [{**nodes[0], "mix": 0.0}]).clips["c"].color) == ""
    assert (
        grade_tables(make_project(source, [{**nodes[0], "enabled": False}]).clips["c"].color)
        is None
    )

    for bad in (
        {"kind": "transfer", "input_space": "acescg", "output_space": "srgb"},
        {"kind": "transfer", "input_space": "srgb"},
    ):
        try:
            ClipColor(grade=[bad])
        except ValidationError:
            continue
        raise AssertionError(f"{bad} must not validate")
    print("   transfer: unknown spaces and half-written nodes are refused by the contract")


BLEND_MODES = (
    "normal",
    "multiply",
    "screen",
    "overlay",
    "darken",
    "lighten",
    "difference",
    "exclusion",
)


def blend_suite(folder: Path) -> None:
    """Node blend modes: every one of them is a per-channel function of the node's own input."""
    source = toe_source(folder)
    lift = {"kind": "curve", "channel": "rgb", "points": [{"x": 0, "y": 0.25}, {"x": 1, "y": 1.0}]}

    def node_output(value: float) -> float:
        return value + 0.25 * (1.0 - value)

    for mode in BLEND_MODES:
        nodes = [{**lift, "blend": mode}]
        tables = grade_tables(make_project(source, nodes).clips["c"].color)
        worst = 0.0
        for index in range(256):
            backdrop = index / 255
            expected = blend_reference(mode, backdrop, node_output(backdrop))
            measured = backdrop if tables is None else tables["r"][index]
            worst = max(worst, abs(measured - expected))
        assert worst * 255 <= 0.5, (mode, worst * 255)
        assert tables is None or (tables["r"] == tables["g"] == tables["b"]), mode
    print("   blend: all eight modes match the published separable formulas within half a level")

    # A blend that cannot change anything must add no stage at all, not an expensive no-op.
    assert (
        grade_tables(make_project(source, [{**lift, "blend": "darken"}]).clips["c"].color) is None
    )
    assert grade_filter(make_project(source, [{**lift, "blend": "darken"}]).clips["c"].color) == ""
    assert grade_filter(make_project(source, [{**lift, "blend": "lighten"}]).clips["c"].color) != ""
    for mode in BLEND_MODES:
        assert grade_filter(
            make_project(source, [{**lift, "blend": mode, "mix": 0.0}]).clips["c"].color
        ) == (""), mode
    print("   blend: an identity blend and mix=0 both add no filter stage")

    nodes = [{**lift, "blend": "screen"}]
    measured = toe_levels(render(make_project(source, nodes), folder, "blend-screen.mp4"))
    reference = predict(nodes, 0)
    arrived = [
        round(value)
        for value in toe_levels(render(make_project(source, []), folder, "blend-plain.mp4"))
    ]
    for band, level in enumerate(arrived):
        assert abs(measured[band] - reference[level] * 255) <= 4, (band, level, measured[band])
    difference = [{**lift, "blend": "difference"}]
    inverted = toe_levels(render(make_project(source, difference), folder, "blend-difference.mp4"))
    difference_reference = predict(difference, 0)
    for band, level in enumerate(arrived):
        assert abs(inverted[band] - difference_reference[level] * 255) <= 4, (band, level)
    assert max(abs(a - b) for a, b in zip(measured, inverted)) > 20, (
        "screen and difference must not render the same picture",
        measured,
        inverted,
    )
    print(
        "   blend: rendered bands "
        + str(arrived)
        + " become "
        + str([round(value) for value in measured])
        + " under screen and "
        + str([round(value) for value in inverted])
        + " under difference"
    )

    try:
        ClipColor(grade=[{**lift, "blend": "hardlight"}])
    except ValidationError:
        pass
    else:
        raise AssertionError("an unknown blend mode must not validate")
    print("   blend: unknown blend modes are refused by the contract")


if __name__ == "__main__":
    main()
