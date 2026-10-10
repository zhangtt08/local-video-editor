"""Grade nodes: one per-channel polyline feeds FFmpeg and the browser table; edits stay atomic."""

import hashlib
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentcut.animation import preview_manifest
from agentcut.contracts import SCHEMA_VERSION, ClipColor, EditBatch, Project, capabilities
from agentcut.contracts import TIMEBASE as T
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


def lut_stage(color) -> dict | None:
    """The single LUT stage a per-channel-only chain compiles to, or None for a no-op chain.

    Asserting there is exactly one stage is part of the claim: these chains hold no cross-channel
    node, so a second stage would mean the compiler split a run it should have collapsed.
    """
    compiled = grade_tables(color)
    if compiled is None:
        return None
    assert len(compiled["stages"]) == 1, compiled
    assert compiled["stages"][0]["type"] == "lut", compiled
    return compiled["stages"][0]


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

    def operation(node: dict, value: float) -> float | None:
        """One operation on the value entering it; None when it does not touch this channel."""
        if node["kind"] == "curve":
            channel = node.get("channel", "rgb")
            if channel != "rgb" and {"red": 0, "green": 1, "blue": 2}[channel] != index:
                return None
            return curve(node, value)
        if node["kind"] == "transfer":
            return clamp(encode(node["output_space"], decode(node["input_space"], value)))
        if node["kind"] == "white_balance":
            warm, green, shift = 0.30, 0.20, 0.10
            factors = (
                1 + warm * node["temperature"] + shift * node["tint"],
                1 - green * node["tint"],
                1 - warm * node["temperature"] + shift * node["tint"],
            )
            return clamp(value * factors[index])
        if node["kind"] == "parallel":
            # Resolve semantics: each branch re-reads the node's input, the node outputs the mean,
            # and a bypassed branch contributes that input (so it never renumbers the others).
            # 1.120: `weights` are that mixer's knobs — absent means every branch counts the same,
            # which is the mean above; all zero means the node adds nothing at all, so it leaves
            # this channel alone (None), because there is nothing left to divide by.
            parts = []
            for branch in node["branches"]:
                out = node_step(branch, value)
                parts.append(value if out is None else out)
            weights = list(node.get("weights") or [])
            if not weights:
                return sum(parts) / len(parts)
            total = sum(weights)
            if not total:
                return None
            return sum(part * weight for part, weight in zip(parts, weights, strict=True)) / total
        return clamp(
            max(value, 0.0) ** (1 / node["gamma"][index]) * node["gain"][index]
            + node["lift"][index]
        )

    def node_step(node: dict, value: float) -> float | None:
        """A node or branch with its own strength and blend, or None when it changes nothing."""
        if not node.get("enabled", True) or not node.get("mix", 1):
            return None
        inner = operation(node, value)
        if inner is None:
            return None
        return clamp(
            value
            + node.get("mix", 1)
            * (blend_reference(node.get("blend", "normal"), value, inner) - value)
        )

    table = []
    for position in range(256):
        value = position / 255
        for node in nodes:
            stepped = node_step(node, value)
            if stepped is not None:
                value = stepped
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
        assert capabilities["project_schema_version"] == SCHEMA_VERSION
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
        grade = tables["grade"]["stages"][0]
        assert grade["id"].startswith("l") and len(grade["r"]) == 256
        assert f"url(#{tables['grade']['id']})" in tables["color_filter"]
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
        ]["grade"]["stages"][0]
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
    tables = lut_stage(make_project(source, nodes).clips["c"].color)
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
    half_tables = lut_stage(make_project(source, half_nodes).clips["c"].color)
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


CHANNELS = ("r", "g", "b")


def parallel_math_suite(folder: Path) -> None:
    """并联节点：每一支都从本节点的输入重新开始算，节点输出是各支的平均值。"""
    source = banded_source(folder)
    lift = {
        "kind": "curve",
        "channel": "rgb",
        "points": [{"x": 0.0, "y": 0.25}, {"x": 1.0, "y": 1.0}],
    }
    crush = {
        "kind": "wheels",
        "lift": [0.0, 0.0, 0.0],
        "gamma": [0.45, 0.6, 0.8],
        "gain": [0.9, 1.0, 1.1],
    }
    neutral = {"kind": "white_balance", "temperature": 0.0, "tint": 0.0}
    warm = {"kind": "white_balance", "temperature": 0.3, "tint": 0.0}
    cool = {"kind": "white_balance", "temperature": -0.3, "tint": 0.0}

    def tables(nodes: list[dict]) -> dict | None:
        return lut_stage(make_project(source, nodes).clips["c"].color)

    def drift(left: dict, right: dict, name: str) -> float:
        return max(abs(left[name][key] - right[name][key]) * 255 for key in range(256))

    graph = {"kind": "parallel", "branches": [lift, crush]}
    measured = tables([graph])
    assert measured is not None
    worst = max(
        abs(measured[name][key] - predict([graph], index)[key]) * 255
        for index, name in enumerate(CHANNELS)
        for key in range(256)
    )
    assert worst <= 0.5, worst
    serial = tables([lift, crush])
    gap = max(drift(measured, serial, name) for name in CHANNELS)
    assert gap > 8.0, ("a parallel node is not a serial chain wearing a new name", gap)
    reversed_serial = tables([crush, lift])
    order = max(drift(serial, reversed_serial, name) for name in CHANNELS)
    assert order > 2.0, ("serial order must change the picture", order)
    swapped = tables([{"kind": "parallel", "branches": [crush, lift]}])
    symmetric = max(drift(measured, swapped, name) for name in CHANNELS)
    assert symmetric < 1e-9, ("a mean does not care about branch order", symmetric)
    print(
        "   parallel: the mean of the branches is the shipped arithmetic "
        f"(table follows the reference within {worst:.3f} levels, "
        f"{gap:.1f} levels away from the same two operations in series, "
        f"{order:.1f} levels of order dependence in series, branch order exactly free)"
    )

    bypassed = tables([{"kind": "parallel", "branches": [lift, {**neutral, "enabled": False}]}])
    halved = tables([{**lift, "mix": 0.5}])
    assert max(drift(bypassed, halved, name) for name in CHANNELS) <= 0.5, (
        "a bypassed branch contributes its input, so one live branch of two is half strength"
    )

    opposing = tables([{"kind": "parallel", "branches": [warm, cool]}])
    assert opposing is not None, (
        "only the top of the range clamps, so the pair is not exactly empty"
    )
    # (1.09 + 0.91) / 2 is 1.0 on red and blue, and (1.0 + 1.0) / 2 on green: the branches cancel up
    # to the point where the brighter one starts clipping, which is 1/1.09 = 0.9174 → level 233.
    # A serial chain cannot cancel at all, and the simplified polyline holds the cancellation to
    # within half a level.
    opposing_nodes = [{"kind": "parallel", "branches": [warm, cool]}]
    for index, name in enumerate(CHANNELS):
        reference = predict(opposing_nodes, index)
        for key in range(234):
            assert abs(opposing[name][key] * 255 - key) <= 0.5, (
                name,
                key,
                opposing[name][key] * 255,
            )
        assert max(abs(opposing[name][key] - reference[key]) * 255 for key in range(256)) <= 0.5
    chained = tables([warm, cool])
    off = max(abs(chained[name][128] - 128 / 255) * 255 for name in CHANNELS)
    assert off > 1.0, ("the same two branches in series must not cancel", off)
    print(
        "   parallel: +0.3 and -0.3 colour temperature cancel within half a level on every level "
        f"below the clamp (234 of 256), while in series the mid grey is {off:.2f} levels off"
    )

    red_only = {
        "kind": "curve",
        "channel": "red",
        "points": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.5}],
    }
    mixed = tables([{"kind": "parallel", "branches": [red_only, neutral]}])
    assert all(abs(mixed["g"][key] - key / 255) < 1e-9 for key in range(256)), (
        "a red-only branch must not move green: the other branch is the identity, and their mean is"
    )
    assert all(abs(mixed["b"][key] - key / 255) < 1e-9 for key in range(256))
    assert abs(mixed["r"][128] - 0.375) < 0.002, mixed["r"][128]

    blended = tables(
        [{"kind": "parallel", "branches": [lift, crush], "blend": "lighten", "mix": 0.75}]
    )
    reference = predict(
        [{"kind": "parallel", "branches": [lift, crush], "blend": "lighten", "mix": 0.75}], 0
    )
    assert max(abs(blended["r"][key] - reference[key]) * 255 for key in range(256)) <= 0.5

    stage = grade_filter(make_project(source, [graph]).clips["c"].color)
    assert stage.startswith("lutrgb=") and set(stage) <= SAFE, stage[:120]
    expressions = {name: stage.split(f"{name}='")[1].split("'")[0] for name in CHANNELS}
    assert len(set(expressions.values())) == 3, "the three channels must not share one expression"
    assert grade_filter(make_project(source, [{**graph, "mix": 0.0}]).clips["c"].color) == "", (
        "a parallel node at zero strength must add no stage"
    )
    print("   parallel: the FFmpeg expression is compiled from the same mean, per channel")

    for bad in (
        {"kind": "parallel", "branches": []},
        {"kind": "parallel", "branches": [neutral] * 5},
        {"kind": "parallel", "branches": [{"kind": "parallel", "branches": [neutral]}]},
        {"kind": "parallel", "branches": [{"kind": "curves"}]},
    ):
        try:
            ClipColor(grade=[bad])
        except ValidationError:
            continue
        raise AssertionError(f"{str(bad)[:60]} must not validate")
    print("   parallel: empty, over-full and nested branch lists are refused by the contract")


def parallel_media_suite(folder: Path) -> None:
    """The branch mean has to survive the encoder, not only the compiler."""
    source = banded_source(folder)
    lift = {
        "kind": "curve",
        "channel": "rgb",
        "points": [{"x": 0.0, "y": 0.25}, {"x": 1.0, "y": 1.0}],
    }
    crush = {
        "kind": "wheels",
        "lift": [0.0, 0.0, 0.0],
        "gamma": [0.45, 0.6, 0.8],
        "gain": [0.9, 1.0, 1.1],
    }
    graph = {"kind": "parallel", "branches": [lift, crush]}
    levels = band_levels(render(make_project(source, [graph]), folder, "parallel.mp4"))
    serial_levels = band_levels(render(make_project(source, [lift, crush]), folder, "serial.mp4"))
    worst = 0.0
    for channel in range(3):
        expected = predict([graph], channel)
        for band, input_level in enumerate(BANDS):
            worst = max(worst, abs(levels[channel][band] - expected[input_level] * 255))
    assert worst <= 4.0, (worst, levels)
    apart = max(abs(levels[c][b] - serial_levels[c][b]) for c in range(3) for b in range(3))
    assert apart > 6.0, ("the delivered pixels must show the mean, not the chain", apart)
    print(
        "   parallel: rendered bands "
        + str([[int(value) for value in row] for row in zip(*levels)])
        + f" follow the branch mean within {worst:.2f} levels and sit {apart:.1f} levels from"
        " the same two operations in series"
    )
    assert "lutrgb=" in "\n".join(
        compile_render_plan(make_project(source, [graph]), "h264-source-quality").filters
    )


def parallel_http_suite(folder: Path) -> None:
    """A graph write is an ordinary edit: one revision, replayable, browser reads the mean."""
    token = "par-" + "b" * 48
    with TestClient(
        create_app(folder / "db-par.sqlite3", token),
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        features = client.get("/v1/capabilities").json()["features"]
        assert features["grade_parallel_branches"] is True, features

        project = client.post(
            "/v1/projects", json={"request_id": "new", "name": "parallel"}
        ).json()["project"]
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
                "op": "clip.add",
                "clip": {
                    "id": "c",
                    "asset_id": "pic",
                    "track_id": "v",
                    "position_ticks": 0,
                    "duration_ticks": T,
                },
            },
        ]
        assert edit("seed", 0, seed).status_code == 200

        warm = {"kind": "white_balance", "temperature": 0.4, "tint": 0.0}
        cool = {"kind": "white_balance", "temperature": -0.2, "tint": 0.1}
        curve = {**RGB_CURVE, "mix": 0.6}
        graph = {
            "kind": "parallel",
            "branches": [warm, cool, curve],
            "blend": "screen",
            "mix": 0.8,
        }
        command = {"op": "clip.grade", "clip_id": "c", "grade": [graph]}

        planned = edit("p1", 1, [command], dry=True)
        assert planned.status_code == 200 and not planned.json()["committed"], planned.text
        assert client.get(path).json()["revision"] == 1, "a dry run must not write the graph"

        written = edit("p2", 1, [command])
        assert written.status_code == 200, written.text
        stored = written.json()["project"]["clips"]["c"]["color"]["grade"][0]
        assert stored["kind"] == "parallel" and len(stored["branches"]) == 3, stored
        assert stored["branches"][2]["mix"] == 0.6 and stored["blend"] == "screen", stored
        assert written.json()["project"]["revision"] == 2, "one graph write is one revision"

        again = edit("p2", 1, [command])
        assert again.json()["replayed"] is True and again.json()["project"]["revision"] == 2
        stale = edit("p3", 1, [{"op": "clip.grade", "clip_id": "c", "grade": []}])
        assert stale.status_code == 409, stale.text

        manifest = client.post("/v1/preview-manifest", json=written.json()["project"]).json()[
            "clips"
        ]["c"]
        grade = manifest["grade"]["stages"][0]
        assert grade is not None and len(grade["r"]) == 256
        assert f"url(#{manifest['grade']['id']})" in manifest["color_filter"]
        drift = max(
            abs(grade[name][key] - predict([graph], index)[key]) * 255
            for index, name in enumerate(CHANNELS)
            for key in range(256)
        )
        assert drift <= 0.5, drift

        muted = edit(
            "p4",
            2,
            [
                {
                    "op": "clip.grade",
                    "clip_id": "c",
                    "grade": [{**graph, "branches": [warm, cool, {**curve, "enabled": False}]}],
                }
            ],
        )
        assert muted.status_code == 200, muted.text
        assert len(muted.json()["project"]["clips"]["c"]["color"]["grade"][0]["branches"]) == 3
        quieter = client.post("/v1/preview-manifest", json=muted.json()["project"]).json()["clips"][
            "c"
        ]["grade"]["stages"][0]
        moved = max(
            abs(quieter[name][key] - grade[name][key]) * 255
            for name in CHANNELS
            for key in (64, 128, 192)
        )
        assert moved > 1.0, (
            "disabling one of three branches must fade the mean, not delete it",
            moved,
        )
        assert len(quieter["r"]) == 256

        rejected = edit(
            "p5",
            3,
            [{"op": "clip.grade", "clip_id": "c", "grade": [{"kind": "parallel", "branches": []}]}],
        )
        assert rejected.status_code == 422, rejected.text
        assert client.get(path).json()["revision"] == 3, (
            "a refused graph write must not burn a revision"
        )

        nested = edit(
            "p6",
            3,
            [
                {
                    "op": "clip.grade",
                    "clip_id": "c",
                    "grade": [
                        {"kind": "parallel", "branches": [{"kind": "parallel", "branches": [warm]}]}
                    ],
                }
            ],
        )
        assert nested.status_code == 422, nested.text

        history = client.get(path + "/history").json()["history"]
        assert 2 in [entry["revision"] for entry in history]
        restore = client.post(
            path + "/restore",
            json={"request_id": "p7", "expected_revision": 3, "target_revision": 2},
        )
        assert restore.status_code == 200, restore.text
        back = restore.json()["project"]["clips"]["c"]["color"]["grade"][0]
        assert back["branches"][2]["enabled"] is True, back
        assert restore.json()["project"]["revision"] == 4, "a restore is a new revision"
        print(
            "   parallel: HTTP writes one graph as one revision, replays it, refuses empty and "
            f"nested branch lists, and the browser LUT follows the mean within {drift:.3f} levels"
        )


def weight_math_suite(folder: Path) -> None:
    """1.120：并联节点的分支权重——不给就是 1.119 那份均分，给全了就是达芬奇那排混频旋钮。

    断的四件事：默认一字不改（不给权重与全 1 逐位相同，老工程的表不会因这一版抖一下）；权重把结果
    拉到被加权那一支那边去（2:0 与单独那一条分支**逐位相同**，这不是近似而是同一条映射）；全 0 是
    「这一节不改画面」而不是黑场；权重只由形状约束——覆盖不全、超出 0..2 都在契约层就拒。
    """
    source = banded_source(folder)
    lift = {
        "kind": "curve",
        "channel": "rgb",
        "points": [{"x": 0.0, "y": 0.25}, {"x": 1.0, "y": 1.0}],
    }
    crush = {
        "kind": "wheels",
        "lift": [0.0, 0.0, 0.0],
        "gamma": [0.45, 0.6, 0.8],
        "gain": [0.9, 1.0, 1.1],
    }

    def tables(nodes: list[dict]) -> dict | None:
        return lut_stage(make_project(source, nodes).clips["c"].color)

    def graph(weights=None, branches=(lift, crush)) -> dict:
        made = {"kind": "parallel", "branches": [dict(branch) for branch in branches]}
        if weights is not None:
            made["weights"] = list(weights)
        return made

    def drift(left: dict, right: dict, name: str) -> float:
        return max(abs(left[name][key] - right[name][key]) * 255 for key in range(256))

    plain, ones = tables([graph()]), tables([graph([1.0, 1.0])])
    assert plain is not None and ones is not None
    for name in CHANNELS:
        assert plain[name] == ones[name], (
            f"不给权重必须与全 1 逐位相同，{name} 差了 {drift(plain, ones, name)}"
        )

    tilted, alone = tables([graph([2.0, 0.0])]), tables([lift])
    for name in CHANNELS:
        assert tilted[name] == alone[name], (
            f"2:0 就是只剩那一支：{name} 最大差 {drift(tilted, alone, name)}"
        )
    flipped = tables([graph([0.0, 2.0])])
    assert flipped is not None and alone is not None
    for name in CHANNELS:
        assert drift(flipped, alone, name) > 8.0, f"反过来加权必须看得见差别：{name} 几乎没有动"

    pulled = tables([graph([1.0, 2.0])])
    assert pulled is not None
    for index, name in enumerate(CHANNELS):
        reference = predict([graph([1.0, 2.0])], index)
        worst = max(abs(pulled[name][key] - reference[key]) * 255 for key in range(256))
        assert worst <= 0.5, f"{name} 与独立参考表差 {worst}，加权平均不是这么算的"

    assert tables([graph([0.0, 0.0])]) is None, "全 0 权重必须整节不改画面，而不是编译出一张黑表"

    for label, weights in (
        ("只覆盖一支", [1.0]),
        ("多出格来", [1.0, 1.0, 1.0]),
        ("超出上限", [3.0, 0.0]),
        ("负数", [-0.5, 1.0]),
    ):
        try:
            make_project(source, [graph(weights)])
        except ValidationError:
            continue
        raise AssertionError(
            f"{label}的权重（{weights}）被收下了，它会写进一份两端算不出同一结果的工程"
        )

    unweighted = make_project(source, [graph()]).clips["c"].color.grade[0]
    assert unweighted.weights == [], f"1.119 那份载荷读进来应当没有权重：{unweighted.weights}"
    assert capabilities(True, False, [])["features"]["grade_branch_weights"] is True
    print(
        "   weights: default==all-one bit for bit, 2:0 equals the lone branch, all-zero is a no-op"
    )


def weight_media_suite(folder: Path) -> None:
    """权重走到真实成片：同一条并联节点，2:0 与 0:2 交付的灰阶带必须各自落在被加权那一支那边。"""
    source = banded_source(folder)
    lift = {
        "kind": "curve",
        "channel": "rgb",
        "points": [{"x": 0.0, "y": 0.25}, {"x": 1.0, "y": 1.0}],
    }
    crush = {
        "kind": "wheels",
        "lift": [0.0, 0.0, 0.0],
        "gamma": [0.45, 0.6, 0.8],
        "gain": [0.9, 1.0, 1.1],
    }

    def levels(weights) -> list[list[float]]:
        graph = {"kind": "parallel", "branches": [dict(lift), dict(crush)]}
        if weights is not None:
            graph["weights"] = list(weights)
        return band_levels(render(make_project(source, [graph]), folder, f"weight-{weights}.mp4"))

    mean, first, second = levels(None), levels([2.0, 0.0]), levels([0.0, 2.0])

    def apart(left: list[list[float]], right: list[list[float]]) -> float:
        return max(
            abs(a - b)
            for row_left, row_right in zip(left, right, strict=True)
            for a, b in zip(row_left, row_right, strict=True)
        )

    assert apart(mean, first) > 2.0, (
        f"2:0 交回来的画面与均分只差 {apart(mean, first)}：加权没走到成片"
    )
    assert apart(mean, second) > 2.0, (
        f"0:2 交回来的画面与均分只差 {apart(mean, second)}：加权没走到成片"
    )
    assert apart(first, second) > 2.0, "两个极端权重交出同一幅画：这一节其实没在听权重"
    dark = 0
    assert first[dark][0] > mean[dark][0] > second[dark][0], (
        f"暗带该按权重偏置：lift 重的交出 {first[dark][0]}，均分 {mean[dark][0]}，"
        f"wheels 重的 {second[dark][0]}"
    )
    print(
        "   weights: the delivered dark band reads "
        f"{first[dark][0]} at 2:0, {mean[dark][0]} as the mean, {second[dark][0]} at 0:2"
    )


def weight_receipt_suite() -> None:
    """1.120 给并联节点加的这份默认字段不许把老回执劈成两半。"""
    command = {
        "op": "clip.patch",
        "clip_id": "c",
        "color": {
            "grade": [
                {
                    "kind": "parallel",
                    "branches": [
                        {
                            "kind": "curve",
                            "channel": "rgb",
                            "points": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}],
                        }
                    ],
                }
            ]
        },
    }
    with_empty = dict(command)
    with_empty["color"] = {
        **command["color"],
        "grade": [{**command["color"]["grade"][0], "weights": []}],
    }
    first = EditBatch(request_id="same", expected_revision=1, commands=[command])
    second = EditBatch(request_id="same", expected_revision=1, commands=[with_empty])
    assert ProjectStore._fingerprint("edit", first) == ProjectStore._fingerprint("edit", second), (
        "带 `weights: []` 的同一份载荷与不提权重的载荷必须命中同一张回执，"
        "否则 1.120 之前写下的请求一重试就变成第二次写入"
    )
    print("   weights: an empty table hashes as a payload that never mentioned one")


def main():
    with tempfile.TemporaryDirectory(prefix="agentcut-grade-") as scratch:
        folder = Path(scratch)
        http_suite(folder)
        media_suite(folder)
        transfer_suite(folder)
        blend_suite(folder)
        parallel_math_suite(folder)
        parallel_media_suite(folder)
        parallel_http_suite(folder)
        weight_math_suite(folder)
        weight_media_suite(folder)
        weight_receipt_suite()
    print(
        "PASS: grade node contracts, atomic HTTP edits, replay/lock/restore, parallel branch "
        "means and their 1.120 mixer weights, browser LUT parity and real H.264 pixels"
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
        tables = lut_stage(make_project(source, nodes).clips["c"].color)
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
    tables = lut_stage(make_project(source, nodes).clips["c"].color)
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
        tables = lut_stage(make_project(source, nodes).clips["c"].color)
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
