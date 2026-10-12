"""One-click colour management may read the source end off the file itself (1.150).

`clip.color_manage` used to require a person or an Agent to name the curve the source was authored
in — one more thing to know about a file before touching it, while the file itself usually carries
that answer. This gate covers the four things that could go wrong when a file is allowed to answer:

* the tags are stored as ffprobe spelled them, and the round trip is the measured one: writing
  `-color_trc gamma22` lands on disk as `bt470m`, and `-color_trc unknown` writes no key at all;
* only `color_transfer` names a tone curve, so a file that tags a matrix or primaries is refused
  rather than inferred, and every refusal carries the tags it found;
* `auto_source` writes exactly the pair the hand-picked command writes — same nodes, same compiled
  filter, same pixels out of FFmpeg — because there is one reducer path, not a second;
* a payload that never mentions `auto_source` still replays as the pre-1.150 receipt it was.

The seven curves and the tag table come from `contracts`; the arithmetic is not re-derived here
because `colormanage_check.py` already pins the conversion maths against published transfer
functions. This file pins the *reading*, the *refusal*, and the *sameness*.
"""

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentcut.colortags import detect_space
from agentcut.contracts import (
    COLOR_SPACES,
    COLOR_TRANSFER_TAGS,
    TIMEBASE,
    ClipColorManage,
    CreateProject,
    EditBatch,
    EditorError,
    Project,
    VerifiedMedia,
    capabilities,
)
from agentcut.http_api import create_app
from agentcut.media import MediaService
from agentcut.projects import ProjectStore
from agentcut.render import compile_render_plan
from agentcut.timeline import apply_commands

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
T = TIMEBASE
WIDTH, HEIGHT = 32, 24
# The measured rows, stated here as data so a table edit has to be noticed by this file.
MEASURED = {
    "bt709": "rec709",
    "iec61966-2-1": "srgb",
    "bt470m": "gamma22",
    "linear": "linear",
}
REFUSALS = {
    "sd": ("smpte170m", "unmatched_transfer_tag"),
    "matrix": (None, "no_transfer_tag"),
    "plain": (None, "no_color_tags"),
}


def ffmpeg(args, timeout=180):
    return subprocess.run(
        [str(FFMPEG), "-v", "error", "-y", *args],
        capture_output=True,
        check=True,
        timeout=timeout,
        creationflags=0x08000000,
    )


def build(folder: Path) -> dict[str, Path]:
    """Four files that differ only in the colour tags they carry, written by this repo's FFmpeg."""
    base = ["-f", "lavfi", "-i", f"color=c=0x804020:s={WIDTH}x{HEIGHT}:r=25", "-t", "1"]
    specs = {
        "bt709": [
            *base,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
        ],
        "srgb": [*base, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-color_trc", "iec61966-2-1"],
        # Measured: this spelling lands on disk as `bt470m`, which is the same stored enum.
        "gamma_written": [*base, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-color_trc", "gamma22"],
        "sd": [*base, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-color_trc", "smpte170m"],
        "matrix": [
            *base,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
        ],
        "plain": [*base, "-c:v", "libx264", "-pix_fmt", "yuv420p"],
    }
    out = {}
    for name, argv in specs.items():
        path = folder / f"{name}.mp4"
        ffmpeg([*argv, str(path)])
        out[name] = path
    # A clip with no picture is the read route's other refusal, so the fixture has to exist.
    tone = folder / "tone.m4a"
    ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "1",
            "-c:a",
            "aac",
            str(tone),
        ]
    )
    out["tone"] = tone
    return out


def verified_for(path: Path, tags: dict) -> dict:
    """A probe record carrying only what this test needs, with the tags as the file said them.

    The size and hash are real when the file exists and inert when the case is a pure table read:
    `detect_space` never looks at either, so a synthetic record cannot smuggle in a dependency.
    """
    exists = path.is_file()
    return {
        "probe_id": "p",
        "path": str(path),
        "kind": "video",
        "label": path.name,
        "size_bytes": path.stat().st_size if exists else 1,
        "content_sha256": (hashlib.sha256(path.read_bytes()).hexdigest() if exists else "0" * 64),
        "duration_ticks": T,
        "width": WIDTH,
        "height": HEIGHT,
        "frame_rate": {"numerator": 25, "denominator": 1},
        **tags,
    }


def project_of(*pairs: dict) -> Project:
    """Index what the fixtures declare by their own ids, not by the caller's dict keys."""
    assets = {pair["asset"]["id"]: pair["asset"] for pair in pairs}
    clips = {pair["clip"]["id"]: pair["clip"] for pair in pairs}
    return Project.model_validate(
        {
            "id": "p",
            "name": "colortags",
            "settings": {"width": WIDTH, "height": HEIGHT},
            "tracks": [
                {"id": "v", "kind": "video", "name": "v"},
                {"id": "a", "kind": "audio", "name": "a"},
            ],
            "assets": assets,
            "clips": clips,
        }
    )


def clip_pair(clip_id: str, asset_id: str, tags: dict, source: Path) -> dict:
    return {
        "asset": {
            "id": asset_id,
            "kind": "video",
            "label": source.name,
            "reference": "unused",
            "duration_ticks": T,
            "verified": verified_for(source, tags),
        },
        "clip": {
            "id": clip_id,
            "asset_id": asset_id,
            "track_id": "v",
            "position_ticks": 0,
            "duration_ticks": T,
        },
    }


def edit(project: Project, *commands, request: str = "ct") -> Project:
    batch = EditBatch.model_validate(
        {"request_id": request, "expected_revision": project.revision, "commands": list(commands)}
    )
    return apply_commands(project, batch.commands)


def manage(clip_id: str, **fields) -> dict:
    """`source_space` stays required (omitting it must not silently mean "take the pair off")."""
    return {"op": "clip.color_manage", "clip_id": clip_id, "source_space": None, **fields}


def nodes(project: Project, clip_id: str) -> list[dict]:
    return [json.loads(node.model_dump_json()) for node in project.clips[clip_id].color.grade]


def compiled_filter(project: Project) -> str:
    plan = compile_render_plan(project, "h264-source-quality")
    return (
        json.dumps(plan.text_files)
        + "|"
        + " ".join(str(item) for item in plan.ffmpeg_argv(str(FFMPEG), "out.mp4"))
    )


def probe_suite(folder: Path) -> None:
    """ffprobe's own spellings survive into the stored record, including the gamma22 round trip."""
    media = MediaService(folder / "db.sqlite3", [folder], folder / "cache", FFMPEG, FFPROBE)
    sources = build(folder)
    got = {name: media.import_file(str(path)).verified for name, path in sources.items()}

    assert got["bt709"].color_transfer == "bt709", got["bt709"].color_transfer
    assert got["bt709"].color_space == "bt709" and got["bt709"].color_range == "tv"
    assert got["srgb"].color_transfer == "iec61966-2-1"
    # The measured surprise: `-color_trc gamma22` reads back as `bt470m`, not `gamma22`.
    assert got["gamma_written"].color_transfer == "bt470m", got["gamma_written"].color_transfer
    assert got["sd"].color_transfer == "smpte170m"
    assert got["matrix"].color_transfer is None and got["matrix"].color_space == "bt709"
    assert got["plain"].color_transfer is None and got["plain"].color_space is None
    for name, want in (
        ("bt709", "rec709"),
        ("srgb", "srgb"),
        ("gamma_written", "gamma22"),
    ):
        space, report = detect_space(got[name])
        assert space == want and report["reason"] == "detected", (name, space, report)
    for name in ("sd", "matrix", "plain"):
        space, report = detect_space(got[name])
        assert space is None and report["reason"] == REFUSALS[name][1], (name, report)
    print("PASS probe: tags stored as ffprobe spells them, gamma22 lands as bt470m")


def detect_suite(folder: Path) -> None:
    """The closed set of reasons, each with the tags as evidence."""
    tags = dict(color_transfer=None, color_space=None, color_primaries=None, color_range=None)
    cases = [
        (dict(tags, color_transfer="bt709"), "rec709", "detected"),
        (dict(tags, color_transfer="iec61966-2-1"), "srgb", "detected"),
        (dict(tags, color_transfer="bt470m"), "gamma22", "detected"),
        (dict(tags, color_transfer="linear"), "linear", "detected"),
        (dict(tags, color_transfer="smpte170m"), None, "unmatched_transfer_tag"),
        (dict(tags, color_space="bt709", color_primaries="bt709"), None, "no_transfer_tag"),
        (tags, None, "no_color_tags"),
    ]
    for record, want_space, want_reason in cases:
        space, report = detect_space(
            VerifiedMedia.model_validate(verified_for(folder / "x", record))
        )
        assert space == want_space and report["reason"] == want_reason, (record, space, report)
        for key in ("color_transfer", "color_space", "color_primaries", "color_range"):
            assert report[key] == record[key], (key, report)
    assert detect_space(None)[1]["reason"] == "no_color_tags"
    assert {tag: space for tag, space in COLOR_TRANSFER_TAGS} == MEASURED, COLOR_TRANSFER_TAGS
    print("PASS detect: four curves resolve, three reasons refuse with the tags as evidence")


def reducer_suite(folder: Path) -> None:
    """`auto_source` is the same write, not a second one; a refusal names the file and writes
    nothing."""
    sources = build(folder)
    tagged = clip_pair(
        "c", "at", {"color_transfer": "bt709", "color_space": "bt709"}, sources["bt709"]
    )
    manual = clip_pair(
        "d", "am", {"color_transfer": "bt709", "color_space": "bt709"}, sources["bt709"]
    )
    manual["clip"]["position_ticks"] = T
    sd = clip_pair("s", "as", {"color_transfer": "smpte170m"}, sources["sd"])
    sd["clip"]["position_ticks"] = 2 * T
    project = project_of(tagged, manual, sd)

    written = edit(
        project,
        manage("c", auto_source=True),
        manage("d", source_space="rec709"),
    )
    assert nodes(written, "c") == nodes(written, "d"), (nodes(written, "c"), nodes(written, "d"))
    pair = nodes(written, "c")
    assert len(pair) == 2 and pair[0]["purpose"] == "color_manage", pair
    assert pair[0]["input_space"] == "rec709" and pair[0]["output_space"] == "linear"
    assert pair[1]["input_space"] == "linear" and pair[1]["output_space"] == "rec709"

    # Both ends of the chain compile the exporter's own command line identically. Each variant is
    # its own one-clip project, so the comparison is the filter string and nothing else.
    solo_auto = edit(
        project_of(clip_pair("c", "at", {"color_transfer": "bt709"}, sources["bt709"])),
        manage("c", auto_source=True),
    )
    solo_hand = edit(
        project_of(clip_pair("c", "at", {"color_transfer": "bt709"}, sources["bt709"])),
        manage("c", source_space="rec709"),
    )
    assert compiled_filter(solo_auto) == compiled_filter(solo_hand), "auto compiled differently"

    # A file that does not name a curve is refused by name, and nothing is written.
    try:
        edit(project, manage("s", auto_source=True))
        raise AssertionError("an SD transfer tag was accepted as if it were one of ours")
    except EditorError as error:
        details = error.details
        assert error.code == "COLOR_SPACE_UNDETECTED", error.code
        assert details["reason"] == "unmatched_transfer_tag", details
        assert details["color_transfer"] == "smpte170m", details
        assert details["clip_id"] == "s", details

    # Two answers to one question is refused by the contract itself.
    try:
        ClipColorManage(
            op="clip.color_manage", clip_id="c", source_space="rec709", auto_source=True
        )
        raise AssertionError("both source answers were accepted")
    except ValidationError as error:
        assert "not both" in str(error), str(error)[:200]

    # Taking the pair off is untouched by the new field: no auto_source, source null.
    off = edit(written, manage("c", source_space=None))
    assert nodes(off, "c") == [], nodes(off, "c")
    print(
        "PASS reducer: auto writes the hand-picked pair, refusal names the tag and writes nothing"
    )


def pixels_suite(folder: Path) -> None:
    """One export, two clips, same pixels: the auto path is not a different picture."""
    sources = build(folder)
    tagged = clip_pair("c", "at", {"color_transfer": "bt709"}, sources["bt709"])
    manual = clip_pair("d", "am", {"color_transfer": "bt709"}, sources["bt709"])
    manual["clip"]["position_ticks"] = T
    project = edit(
        project_of(tagged, manual),
        manage("c", auto_source=True),
        manage("d", source_space="rec709"),
    )
    out = folder / "both.mp4"
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
    assert result.returncode == 0, result.stderr.decode(errors="replace")[-500:]

    def pixel(at: float) -> tuple[int, int, int]:
        raw = subprocess.run(
            [
                str(FFMPEG),
                "-v",
                "error",
                "-ss",
                str(at),
                "-i",
                str(out),
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ],
            capture_output=True,
            check=True,
            timeout=120,
            creationflags=0x08000000,
        ).stdout
        assert len(raw) >= 3, len(raw)
        return (raw[0], raw[1], raw[2])

    auto_shot, hand_shot = pixel(0.4), pixel(1.4)
    assert auto_shot == hand_shot, (auto_shot, hand_shot)
    assert auto_shot != (128, 64, 32), f"the wrap converted nothing: {auto_shot}"
    print(f"PASS pixels: auto {auto_shot} == hand-picked {hand_shot}, and both differ from source")


def http_suite(folder: Path) -> None:
    """The read route answers over real imported media, writes nothing, and refuses a clip with no
    picture."""
    sources = build(folder)
    media = MediaService(folder / "api.sqlite3", [folder], folder / "cache", FFMPEG, FFPROBE)
    store = ProjectStore(media.db_path, media)
    probes = {
        name: media.import_file(str(sources[name]))
        for name in ("bt709", "sd", "plain", "matrix", "tone")
    }
    token = "colortags-" + "0" * 40
    with TestClient(
        create_app(store.path, token, media),
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        project = store.create(
            CreateProject(request_id="new", name="api", settings={"width": WIDTH, "height": HEIGHT})
        ).project

        def edit_batch(revision: int, commands: list, request_id: str):
            return client.post(
                f"/v1/projects/{project.id}/edits",
                json={
                    "request_id": request_id,
                    "expected_revision": revision,
                    "commands": commands,
                },
            )

        seed = [
            {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
            {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "a"}},
        ]
        seed += [
            {
                "op": "asset.import",
                "asset_id": name,
                "label": name,
                "probe_id": probe.id,
                "verified": probe.verified.model_dump(),
            }
            for name, probe in probes.items()
        ]
        seed += [
            {
                "op": "clip.add",
                "clip": {
                    "id": clip_id,
                    "asset_id": asset_id,
                    "track_id": track_id,
                    "position_ticks": index * T,
                    "duration_ticks": T,
                },
            }
            for index, (clip_id, asset_id, track_id) in enumerate(
                (
                    ("hd", "bt709", "v"),
                    ("sd", "sd", "v"),
                    ("bare", "plain", "v"),
                    ("matt", "matrix", "v"),
                    ("au", "tone", "a"),
                )
            )
        ]
        answer = edit_batch(project.revision, seed, "seed")
        assert answer.status_code == 200, answer.text[:400]
        revision = answer.json()["project"]["revision"]

        def read(clip_id: str):
            return client.post(
                f"/v1/projects/{project.id}/clips/{clip_id}/color-space",
                json={"sequence_id": None},
            )

        hit = read("hd").json()
        assert hit["space"] == "rec709" and hit["reason"] == "detected", hit
        assert hit["auto_source_would_work"] is True and hit["color_primaries"] == "bt709", hit
        assert hit["color_spaces"] == list(COLOR_SPACES), hit["color_spaces"]
        for clip_id, reason, tag in (
            ("sd", "unmatched_transfer_tag", "smpte170m"),
            ("matt", "no_transfer_tag", None),
            ("bare", "no_color_tags", None),
        ):
            miss = read(clip_id).json()
            assert miss["space"] is None and miss["reason"] == reason, (clip_id, miss)
            assert miss["tag"] == tag and miss["auto_source_would_work"] is False, (clip_id, miss)

        # Writing through the route's answer: the same space the read named is what lands.
        written = edit_batch(revision, [manage("hd", auto_source=True)], "auto-write")
        assert written.status_code == 200, written.text[:400]
        chain = written.json()["project"]["clips"]["hd"]["color"]["grade"]
        assert [node["input_space"] for node in chain] == ["rec709", "linear"], chain
        assert [node["purpose"] for node in chain] == ["color_manage", "color_manage"], chain

        refused = edit_batch(
            written.json()["project"]["revision"], [manage("sd", auto_source=True)], "auto-refuse"
        )
        assert refused.status_code == 422, refused.text[:300]
        problem = refused.json()["error"]
        assert problem["code"] == "COLOR_SPACE_UNDETECTED", problem
        assert problem["details"]["color_transfer"] == "smpte170m", problem["details"]
        assert problem["details"]["clip_id"] == "sd", problem["details"]

        gone = read("nope")
        assert gone.status_code == 404, gone.text[:200]
        assert gone.json()["error"]["details"]["clip_id"] == "nope", gone.json()

        # A clip with no picture has no transfer characteristic to read: named refusal, not null.
        audio = read("au")
        assert audio.status_code == 422, audio.text[:200]
        assert audio.json()["error"]["code"] == "INVALID_COLOR", audio.json()
        assert audio.json()["error"]["details"]["clip_id"] == "au", audio.json()

        # The read is a read: replay every one of them and the revision must not have moved.
        for clip_id in ("hd", "sd", "bare", "matt", "nope"):
            read(clip_id)
        live = client.get(f"/v1/projects/{project.id}").json()["revision"]
        assert live == written.json()["project"]["revision"], (live, written.json())
    print("PASS http: the read names curve or reason, the write matches it, refusals move nothing")


# The fingerprint the 1.149 tree computed for a `clip.color_manage` that only said "take the pair
# off". Captured by running that commit's own `projects.ProjectStore._fingerprint` over this exact
# payload (its model had no `auto_source` field at all), so it is an outside fact rather than a
# number this release can recompute. If the default leaked into the hash, a receipt written before
# 1.150 would no longer match on retry and the store would run the same edit a second time.
PRE_1150_FINGERPRINT = "3abfc7a3ec20c1d11eeb69b716e51b5977fe10d4a834994233e072f99639a4ab"


def receipt_suite(folder: Path) -> None:
    """A receipt written before `auto_source` exists still replays as the command it was.

    The pair that could have split is the one that writes the same thing: a pre-1.150 payload said
    `source_space: null` (take the pair off), and a 1.150 client may send that same command with the
    new field filled in by the default. Asking the file for the answer has to be a different command.
    """
    store = ProjectStore(folder / "rc.sqlite3")

    def fingerprint(payload: dict) -> str:
        batch = EditBatch.model_validate(
            {"request_id": "r", "expected_revision": 1, "commands": [payload]}
        )
        return store._fingerprint("timeline.edit", batch)

    off = {"op": "clip.color_manage", "clip_id": "c", "source_space": None}
    assert fingerprint(off) == PRE_1150_FINGERPRINT, fingerprint(off)
    assert fingerprint({**off, "auto_source": False}) == PRE_1150_FINGERPRINT, "default split it"
    assert fingerprint({**off, "auto_source": True}) != PRE_1150_FINGERPRINT, "auto hashed as no-op"
    print("PASS receipts: auto_source=false keeps a pre-1.150 receipt replaying as itself")


def capability_suite() -> None:
    caps = capabilities()
    assert caps["features"]["color_manage_auto"] is True
    assert caps["color_transfer_tags"] == [
        {"tag": tag, "space": space} for tag, space in COLOR_TRANSFER_TAGS
    ], caps["color_transfer_tags"]
    print("PASS capabilities: the flag and the table go out from one place")


def main() -> None:
    assert FFMPEG.is_file(), f"this gate needs the bundled FFmpeg at {FFMPEG}"
    capability_suite()
    detect_suite(Path("."))
    with tempfile.TemporaryDirectory() as tmp:
        probe_suite(Path(tmp))
    for suite in (reducer_suite, pixels_suite, http_suite, receipt_suite):
        with tempfile.TemporaryDirectory() as tmp:
            suite(Path(tmp))


if __name__ == "__main__":
    main()
