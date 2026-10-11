"""Colour management as one write: the wrap goes on, grades in linear light, and comes off clean.

`clip.color_manage` puts a `source -> linear` node in front of a clip's chain and a `linear ->
display` node behind it, tags both, and leaves everything in the middle alone. Three properties are
worth a gate, because each is a way a feature like this usually goes wrong:

* the pair is found by the tag the command writes, so taking it off hands back exactly the chain it
  found — including nodes somebody placed by hand in between, which a pattern match would eat;
* the tag is metadata: the same two nodes with and without it compile to the same stage id and the
  same numbers, so the browser preview and the export cannot disagree about a managed clip;
* grading in linear light is a different picture, not a re-labelled one, and the pair alone is not a
  grade at all — a matching source and display export band for band identical to the control.

The maths is checked against sRGB's published piecewise function and BT.1886's pure power, both
written out in this file rather than imported from the compiler under test, and then against pixels
that really left FFmpeg.
"""

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import get_args

from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from agentcut.contracts import (
    GRADE_NODE_LIMIT,
    TIMEBASE,
    ClipColor,
    ClipColorManage,
    ColorSpace,
    Command,
    EditBatch,
    EditorError,
    Project,
    capabilities,
)
from agentcut.contracts import TIMEBASE as T
from agentcut.grade import grade_filter, grade_tables
from agentcut.http_api import create_app
from agentcut.render import compile_render_plan
from agentcut.timeline import apply_commands

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"

CURVE = {
    "kind": "curve",
    "channel": "rgb",
    "points": [{"x": 0.0, "y": 0.0}, {"x": 0.5, "y": 0.28}, {"x": 1.0, "y": 1.0}],
}
BANDS = (0, 16, 48, 128, 208, 255)

# The published transfer functions, re-stated here so the gate does not test the compiler with the
# compiler's own arithmetic. sRGB has a linear toe; BT.1886 with no lift is a plain power of 2.4.
GAMMAS = {"gamma18": 1.8, "gamma20": 2.0, "gamma22": 2.2, "gamma24": 2.4, "rec709": 2.4}
SPACE_NAMES = ("linear", "srgb", "gamma18", "gamma20", "gamma22", "gamma24", "rec709")


def to_linear(space: str, value: float) -> float:
    if space == "linear":
        return value
    if space == "srgb":
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
    return value ** GAMMAS[space]


def from_linear(space: str, value: float) -> float:
    if space == "linear":
        return value
    if space == "srgb":
        return 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055
    return value ** (1 / GAMMAS[space])


def clamp(value: float) -> float:
    return 0.0 if value < 0 else 1.0 if value > 1 else value


def reference(nodes: list[dict]) -> list[float]:
    """The 256-entry red table these nodes should compile to, evaluated here."""
    table = []
    for level in range(256):
        value = level / 255
        for node in nodes:
            if node["kind"] == "transfer":
                value = clamp(
                    from_linear(node["output_space"], to_linear(node["input_space"], value))
                )
            elif node["kind"] == "curve":
                xs = [point["x"] for point in node["points"]]
                ys = [point["y"] for point in node["points"]]
                if value <= xs[0]:
                    value = ys[0]
                elif value >= xs[-1]:
                    value = ys[-1]
                else:
                    step = next(i for i in range(len(xs) - 1) if value <= xs[i + 1])
                    value = ys[step] + (value - xs[step]) * (ys[step + 1] - ys[step]) / (
                        xs[step + 1] - xs[step]
                    )
            else:
                raise AssertionError(node["kind"])
        table.append(value)
    return table


def run(args, timeout=180):
    return subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", *args],
        capture_output=True,
        check=True,
        timeout=timeout,
        creationflags=0x08000000,
    )


def nodes_of(project: Project, clip_id: str = "c") -> list[dict]:
    return [json.loads(node.model_dump_json()) for node in project.clips[clip_id].color.grade]


def project_with(
    source: Path, grade: list[dict], kind: str = "video", second: bool = False
) -> Project:
    verified = {
        "probe_id": "a",
        "path": str(source),
        "kind": kind,
        "label": "bands",
        "size_bytes": source.stat().st_size,
        "content_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "duration_ticks": T,
        "width": 360 if kind == "video" else None,
        "height": 180 if kind == "video" else None,
        "has_audio": kind == "audio",
        "audio_sample_rate": 48000 if kind == "audio" else None,
    }
    clips = {
        "c": {
            "id": "c",
            "asset_id": "a",
            "track_id": "v",
            "position_ticks": 0,
            "duration_ticks": T,
            "color": {"grade": grade},
        }
    }
    if second:
        clips["d"] = {**clips["c"], "id": "d", "position_ticks": T}
    return Project.model_validate(
        {
            "id": "p",
            "name": "colormanage",
            "settings": {"width": 360, "height": 180},
            "tracks": [{"id": "v", "kind": kind, "name": "v"}],
            "assets": {
                "a": {
                    "id": "a",
                    "kind": kind,
                    "label": "bands",
                    "reference": "unused",
                    "duration_ticks": T,
                    "verified": verified,
                }
            },
            "clips": clips,
        }
    )


def edit(project: Project, *commands, request: str = "cm") -> Project:
    batch = EditBatch.model_validate(
        {
            "request_id": request,
            "expected_revision": project.revision + 1,
            "commands": list(commands),
        }
    )
    return apply_commands(project, batch.commands)


def manage(clip_id: str = "c", **fields) -> dict:
    return {"op": "clip.color_manage", "clip_id": clip_id, **fields}


def tagged(nodes: list[dict]) -> list[dict]:
    return [node for node in nodes if node.get("purpose") == "color_manage"]


def refusal(project: Project, command: dict, code: str, label: str) -> dict:
    """Ask for the same refusal twice, on two copies of the same project.

    The reducer must be pure and say the same thing both times: `apply_commands` works on a deep
    copy, so a refusal that mutated its input would show up as the second copy reading a different
    chain — the numbers below are compared, not trusted.
    """
    first = project.model_copy(deep=True)
    seen: dict | None = None
    for attempt in (0, 1):
        try:
            edit(first, command, request=f"cm-{label}-{attempt}")
        except EditorError as error:
            assert error.code == code, (label, error.code, error.message)
            assert error.status == 422, (label, error.status)
            payload = {"code": error.code, "message": error.message, "details": error.details}
            if seen is None:
                seen = payload
            else:
                assert payload == seen, (label, payload, seen)
        else:
            raise AssertionError(f"{label}: {code} was not raised")
    assert nodes_of(first) == nodes_of(project), f"{label}: the refused batch touched the project"
    assert first.revision == project.revision, f"{label}: a refusal must not advance the revision"
    return seen or {}


def bands_source(folder: Path) -> Path:
    """Six flat bands, two of them dark enough to expose a wrap that is secretly a grade."""
    target = folder / "bands.mp4"
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
            str(target),
        ]
    )
    return target


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
    assert result.returncode == 0, result.stderr.decode(errors="replace")[-600:]
    return out


def band_levels(video: Path) -> list[int]:
    raw = run(
        [
            "-ss",
            "0.5",
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
    ).stdout
    assert len(raw) == 18, len(raw)
    return [raw[3 * band] for band in range(6)]


def contract_suite() -> None:
    """The command and its spaces are published from one place; half-written calls are refused."""
    published = capabilities()
    assert "clip.color_manage" in published["commands"], published["commands"]
    assert published["color_spaces"] == list(SPACE_NAMES), published["color_spaces"]
    # one source of truth: the published list is the contract's own Literal, not a copy of it
    assert set(published["color_spaces"]) == set(get_args(ColorSpace)), get_args(ColorSpace)

    command = ClipColorManage(op="clip.color_manage", clip_id="c", source_space="srgb")
    assert command.display_space == "rec709", command
    for bad in (
        {"op": "clip.color_manage", "clip_id": "c", "source_space": "acescg"},
        {"op": "clip.color_manage", "clip_id": "c"},
        {
            "op": "clip.color_manage",
            "clip_id": "c",
            "source_space": "srgb",
            "display_space": "logc",
        },
    ):
        try:
            TypeAdapter(Command).validate_python(bad)
        except ValidationError:
            continue
        raise AssertionError(f"{bad} must not validate")

    # The tag is a closed word, not a free-form label someone could invent and orphan removal on.
    try:
        ClipColor(
            grade=[
                {
                    "kind": "transfer",
                    "input_space": "srgb",
                    "output_space": "linear",
                    "purpose": "grade",
                }
            ]
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("an unregistered purpose must not validate")

    # The desktop's own pick-list has to be the engine's vocabulary. It is ordered by what people
    # use most, so the sets are compared rather than the lists: a name only the interface knows
    # about would be a button writing a command the contract refuses.
    text = (ROOT / "desktop/src/engine.ts").read_text(encoding="utf-8")
    block = text[text.index("export const COLOR_SPACES") :]
    listed = set(re.findall(r'^\s*\["([a-z0-9]+)",', block[: block.index("\n];")], re.M))
    assert listed == set(SPACE_NAMES), (sorted(listed), SPACE_NAMES)
    print("   contract: the op, the seven spaces and the one tag are all closed vocabularies")


def structure_suite(folder: Path) -> None:
    source = bands_source(folder)
    plain = project_with(source, [CURVE])
    wrapped = edit(plain, manage(source_space="srgb"))
    chain = nodes_of(wrapped)

    assert len(chain) == 3, chain
    assert chain[0] == {
        "kind": "transfer",
        "input_space": "srgb",
        "output_space": "linear",
        "purpose": "color_manage",
        "enabled": True,
        "mix": 1.0,
        "blend": "normal",
    }, chain[0]
    assert chain[2] == {
        "kind": "transfer",
        "input_space": "linear",
        "output_space": "rec709",
        "purpose": "color_manage",
        "enabled": True,
        "mix": 1.0,
        "blend": "normal",
    }, chain[2]
    assert chain[1] == nodes_of(plain)[0], "the middle of the chain has to travel through untouched"

    twice = edit(wrapped, manage(source_space="gamma22", display_space="srgb"))
    after = nodes_of(twice)
    assert len(tagged(after)) == 2, "re-running replaces the pair, it does not stack a second one"
    assert (after[0]["input_space"], after[-1]["output_space"]) == ("gamma22", "srgb"), after
    assert after[1] == nodes_of(plain)[0], after

    back = edit(wrapped, manage(source_space=None))
    assert nodes_of(back) == nodes_of(plain), (nodes_of(back), nodes_of(plain))

    # a hand-placed conversion next to the pair must survive both the wrap and the unwrap
    hand = {"kind": "transfer", "input_space": "gamma22", "output_space": "linear"}
    mixed = project_with(source, [hand, CURVE])
    wrapped_mixed = edit(mixed, manage(source_space="srgb"))
    assert len(tagged(nodes_of(wrapped_mixed))) == 2, nodes_of(wrapped_mixed)
    assert nodes_of(wrapped_mixed)[1] == nodes_of(mixed)[0], (
        "the untagged conversion is not the pair's"
    )
    assert nodes_of(edit(wrapped_mixed, manage(source_space=None))) == nodes_of(mixed)

    # only one partner left: the command re-pairs it instead of leaving a half-managed clip
    orphan = project_with(
        source,
        [
            {
                "kind": "transfer",
                "input_space": "srgb",
                "output_space": "linear",
                "purpose": "color_manage",
            },
            CURVE,
        ],
    )
    repaired = nodes_of(edit(orphan, manage(source_space="gamma22")))
    assert len(repaired) == 3 and len(tagged(repaired)) == 2, repaired
    assert (repaired[0]["input_space"], repaired[-1]["output_space"]) == ("gamma22", "rec709"), (
        repaired
    )

    # two clips, one batch: each gets its own pair, and neither borrows the other's tag
    pair = project_with(source, [CURVE], second=True)
    both = edit(pair, manage(source_space="srgb"), manage(clip_id="d", source_space="gamma22"))
    assert len(tagged(nodes_of(both))) == 2, nodes_of(both)
    assert (
        both.clips["c"].color.grade[0].input_space,
        both.clips["d"].color.grade[0].input_space,
    ) == (
        "srgb",
        "gamma22",
    ), nodes_of(both, "d")
    assert (
        both.clips["c"].color.grade[-1].output_space,
        both.clips["d"].color.grade[-1].output_space,
    ) == (
        "rec709",
        "rec709",
    )
    print("   structure: the pair goes on, comes off, re-pairs and never eats the middle")


def refusal_suite(folder: Path) -> None:
    source = bands_source(folder)
    plain = project_with(source, [CURVE])
    wrapped = edit(plain, manage(source_space="srgb"))

    not_set = refusal(plain, manage(source_space=None), "COLOR_MANAGE_NOT_SET", "not-set")
    assert not_set["details"]["nodes"] == 1, not_set
    assert "clip.color_manage" in not_set["message"], (
        "the exit has to name the command that sets it"
    )

    identity = refusal(
        plain,
        manage(source_space="linear", display_space="linear"),
        "COLOR_MANAGE_IDENTITY",
        "identity",
    )
    assert (identity["details"]["source_space"], identity["details"]["display_space"]) == (
        "linear",
        "linear",
    ), identity

    repeated = refusal(wrapped, manage(source_space="srgb"), "COLOR_MANAGE_NO_CHANGE", "no-change")
    assert (repeated["details"]["source_space"], repeated["details"]["display_space"]) == (
        "srgb",
        "rec709",
    ), repeated

    # the budget counts the pair *after* the old one comes off, so a full chain can be re-wrapped
    full = project_with(source, [CURVE] * GRADE_NODE_LIMIT)
    crowded = refusal(full, manage(source_space="srgb"), "COLOR_MANAGE_LIMIT", "limit-full")
    assert (
        crowded["details"]["limit"],
        crowded["details"]["nodes"],
        crowded["details"]["room"],
    ) == (
        GRADE_NODE_LIMIT,
        GRADE_NODE_LIMIT,
        0,
    ), crowded

    tight = project_with(source, [CURVE] * (GRADE_NODE_LIMIT - 1))
    one_room = refusal(tight, manage(source_space="srgb"), "COLOR_MANAGE_LIMIT", "limit-one")
    assert one_room["details"]["room"] == 1, one_room

    paired = edit(
        project_with(source, [CURVE] * (GRADE_NODE_LIMIT - 2)), manage(source_space="srgb")
    )
    assert len(nodes_of(paired)) == GRADE_NODE_LIMIT, nodes_of(paired)
    swapped = edit(paired, manage(source_space="gamma20", display_space="gamma18"))
    assert len(nodes_of(swapped)) == GRADE_NODE_LIMIT, (
        "the room freed by the old pair must be usable"
    )

    audio = refusal(
        project_with(source, [], kind="audio"),
        manage(source_space="srgb"),
        "INVALID_COLOR",
        "audio",
    )
    assert "audio" in audio["message"], audio
    print("   refusals: nothing is written, and every message says how to make room")


def maths_suite(folder: Path) -> None:
    source = bands_source(folder)
    plain = project_with(source, [CURVE])
    wrapped = edit(plain, manage(source_space="srgb"))

    for space in SPACE_NAMES:
        color = ClipColor(
            grade=[
                {"kind": "transfer", "input_space": space, "output_space": "linear"},
                {"kind": "transfer", "input_space": "linear", "output_space": space},
            ]
        )
        assert grade_filter(color) == "", space
        assert grade_tables(color) is None, (space, grade_tables(color))

    tables = grade_tables(wrapped.clips["c"].color)
    assert tables is not None and len(tables["stages"]) == 1, tables
    stage = tables["stages"][0]
    expected = reference(
        [
            {"kind": "transfer", "input_space": "srgb", "output_space": "linear"},
            CURVE,
            {"kind": "transfer", "input_space": "linear", "output_space": "rec709"},
        ]
    )
    worst = max(abs(stage["r"][level] - expected[level]) for level in range(256))
    assert worst * 255 <= 0.5, worst * 255
    assert stage["r"] == stage["g"] == stage["b"], "an rgb curve stays neutral in every channel"

    # the tag must not reach the maths: the browser and the export read the same table
    untagged = grade_tables(
        ClipColor(
            grade=[
                {"kind": "transfer", "input_space": "srgb", "output_space": "linear"},
                CURVE,
                {"kind": "transfer", "input_space": "linear", "output_space": "rec709"},
            ]
        )
    )
    assert untagged["id"] == tables["id"], (untagged["id"], tables["id"])
    assert untagged["stages"][0] == stage

    display = grade_tables(ClipColor(grade=[CURVE]))["stages"][0]
    gap = max(abs(stage["r"][level] - display["r"][level]) for level in range(256))
    assert gap * 255 > 20, "linear-light grading has to be a different picture, not a renamed one"
    print(
        "   maths: the pair follows the published curve within half a level, is worth %d levels at "
        "its worst, and adds nothing by itself" % round(gap * 255)
    )


def media_suite(folder: Path) -> None:
    source = bands_source(folder)

    def export(grade, name):
        return band_levels(render(project_with(source, grade), folder, name))

    control = export([], "cm-control.mp4")
    for band, level in enumerate(BANDS):
        assert abs(control[band] - level) <= 3, (band, level, control)

    wrapped_pair = export(
        [
            {
                "kind": "transfer",
                "input_space": "srgb",
                "output_space": "linear",
                "purpose": "color_manage",
            },
            {
                "kind": "transfer",
                "input_space": "linear",
                "output_space": "srgb",
                "purpose": "color_manage",
            },
        ],
        "cm-pair.mp4",
    )
    assert wrapped_pair == control, (wrapped_pair, control)

    display = export([CURVE], "cm-display.mp4")
    chain = nodes_of(edit(project_with(source, [CURVE]), manage(source_space="srgb")))
    linear = export(chain, "cm-linear.mp4")
    arrived = control
    predicted = reference([CURVE])
    managed = reference(
        [
            {"kind": "transfer", "input_space": "srgb", "output_space": "linear"},
            CURVE,
            {"kind": "transfer", "input_space": "linear", "output_space": "rec709"},
        ]
    )
    for band in range(6):
        assert abs(display[band] - round(predicted[arrived[band]] * 255)) <= 4, (
            band,
            arrived[band],
            display[band],
        )
        assert abs(linear[band] - round(managed[arrived[band]] * 255)) <= 4, (
            band,
            arrived[band],
            linear[band],
        )
    assert linear[3] - display[3] > 20, (display, linear)
    print(
        "   media: control %s, display-space %s, linear-light %s — the reference predicted both"
        % (control, display, linear)
    )


def http_suite(folder: Path) -> None:
    token = "cm-" + "c" * 52
    with TestClient(
        create_app(folder / "cm.sqlite3", token),
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        published = client.get("/v1/capabilities").json()
        assert "clip.color_manage" in published["commands"], published["commands"]
        assert published["color_spaces"] == list(SPACE_NAMES)

        project = client.post("/v1/projects", json={"request_id": "new", "name": "cm"}).json()[
            "project"
        ]
        path = f"/v1/projects/{project['id']}"

        def edit_http(request_id, revision, commands, dry=False):
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
                    "duration_ticks": TIMEBASE,
                },
            },
            {
                "op": "clip.add",
                "clip": {
                    "id": "c",
                    "asset_id": "pic",
                    "track_id": "v",
                    "position_ticks": 0,
                    "duration_ticks": TIMEBASE,
                    "color": {"grade": [CURVE]},
                },
            },
        ]
        assert edit_http("seed", 0, seed).status_code == 200

        dry = edit_http("dry", 1, [manage(source_space="srgb")], dry=True)
        assert dry.status_code == 200, dry.text
        assert dry.json()["committed"] is False, dry.json()
        grade = dry.json()["project"]["clips"]["c"]["color"]["grade"]
        assert [node["kind"] for node in grade] == ["transfer", "curve", "transfer"], grade

        written = edit_http("real", 1, [manage(source_space="srgb")])
        assert written.status_code == 200, written.text
        assert written.json()["committed"] is True, written.json()
        grade = written.json()["project"]["clips"]["c"]["color"]["grade"]
        assert [node["kind"] for node in grade] == ["transfer", "curve", "transfer"], grade
        assert [node.get("purpose") for node in grade] == ["color_manage", None, "color_manage"], (
            grade
        )
        assert written.json()["project"]["revision"] == 2, written.json()["project"]["revision"]

        blocked = edit_http("again", 2, [manage(source_space="srgb")])
        assert blocked.status_code == 422, blocked.text
        assert blocked.json()["error"]["code"] == "COLOR_MANAGE_NO_CHANGE", blocked.json()
        assert client.get(path).json()["revision"] == 2, "a refusal must leave the project alone"

        # a second app over the same database: the tag has to survive the process, not just the call
        with TestClient(
            create_app(folder / "cm.sqlite3", token),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {token}"},
        ) as reloaded:
            stored = reloaded.get(path).json()
            assert [node.get("purpose") for node in stored["clips"]["c"]["color"]["grade"]] == [
                "color_manage",
                None,
                "color_manage",
            ], stored["clips"]["c"]["color"]["grade"]

            undone = reloaded.post(
                path + "/restore",
                json={"request_id": "undo", "expected_revision": 2, "target_revision": 1},
            )
            assert undone.status_code == 200, undone.text
            grade = undone.json()["project"]["clips"]["c"]["color"]["grade"]
            assert len(grade) == 1, grade
            assert undone.json()["project"]["revision"] == 3, undone.json()["project"]["revision"]
        print("   http: dry runs write nothing, the pair survives a reload, one undo takes it off")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-cm-") as scratch:
        folder = Path(scratch)
        contract_suite()
        structure_suite(folder)
        refusal_suite(folder)
        maths_suite(folder)
        media_suite(folder)
        http_suite(folder)
    print(
        "PASS: clip.color_manage wraps the chain, grades in linear light, follows the published "
        "curve in real exported pixels, and comes off with nothing left behind"
    )


if __name__ == "__main__":
    main()
