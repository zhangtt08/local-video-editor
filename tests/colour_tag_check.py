"""1.151: a master may declare its colour, but only if the graph really folded it that way.

The trap this gate exists for is specific and measured: `-colorspace bt709` writes the container tag
and changes nothing else. Bundled FFmpeg does the RGB->YUV fold in the *encoder's* swscale context,
which uses BT.601 — the fixture's solid colour lands in the PNG as RGB (126,63,30), and an untagged
h264 delivery of it comes back as YUV (83,104,158), exactly the BT.601 prediction, while BT.709
predicts (80,107,157). So a tag written beside the old graph would be a claim about a picture the
file does not hold, and the container is the only thing a downstream colour pipeline can read.

The switch therefore does two things at once, and this file checks both against the same frame:
* the last stage of the graph becomes `zscale=matrix=709,format=<preset's pixel format>`;
* the container gets `-color_primaries/-color_trc/-colorspace`.

The reference numbers are re-derived here from the published coefficients, not imported from the
engine, so a wrong matrix in the code cannot agree with itself. Untagged deliveries must keep the
byte-for-byte argv they had before this field existed, and presets that carry no YUV fold at all
(an EXR/DPX sequence, an audio-only file) are refused by name rather than tagged loosely.
"""

import hashlib
import json
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.colortags import detect_space
from agentcut.contracts import (
    COLOR_SPACES,
    COLOR_TRANSFER_TAGS,
    COLOUR_TAG_CODES,
    OUTPUT_COLOUR_TAGS,
    TIMEBASE,
    CreateProject,
    EditBatch,
    EditorError,
    RenderRequest,
    VerifiedMedia,
    capabilities,
)
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime, request_fingerprint
from agentcut.media import MediaService
from agentcut.projects import ProjectStore
from agentcut.render import compile_render_plan, output_args, render_presets
from agentcut.timeline import apply_commands

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
T = TIMEBASE
WIDTH, HEIGHT = 64, 36
SOURCE_RGB = (128, 64, 32)


def reference_yuv(rgb, kr, kg, kb):
    """BT.601 / BT.709 luma-chroma fold, limited range, from the published coefficients.

    The source RGB is passed in because lavfi's own `color=` lands on YUV before the PNG is
    written: the check measures what the fixture really holds instead of assuming the nominal
    value survived a conversion it does not control.
    """
    r, g, b = (channel / 255.0 for channel in rgb)
    y = kr * r + kg * g + kb * b
    u = 0.5 * (b - y) / (1 - kb)
    v = 0.5 * (r - y) / (1 - kr)
    return tuple(round(value) for value in (16 + 219 * y, 128 + 224 * u, 128 + 224 * v))


BT601 = reference_yuv(SOURCE_RGB, 0.299, 0.587, 0.114)
BT709 = reference_yuv(SOURCE_RGB, 0.2126, 0.7152, 0.0722)


def run(argv, timeout=240):
    proc = subprocess.run(
        [str(x) for x in argv], capture_output=True, timeout=timeout, creationflags=0x08000000
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")[-500:]
    return proc.stdout


def _await(runtime, job_id: str, seconds: int = 240) -> None:
    """Drain the queue: the receipt assertions are only worth anything once the jobs ran."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        job = runtime._load(job_id)
        if job.status not in ("queued", "running"):
            assert job.status == "succeeded", (job.status, job.error_code, job.message)
            return
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} never left the queue")


def build_project(folder: Path):
    """One solid-RGB image on one video track: the exact pixels the fold has to describe."""
    png = folder / "solid.png"
    run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x{SOURCE_RGB[0]:02x}{SOURCE_RGB[1]:02x}{SOURCE_RGB[2]:02x}"
            f":s={WIDTH}x{HEIGHT}",
            "-frames:v",
            "1",
            str(png),
        ]
    )
    media = MediaService(folder / "db.sqlite3", [folder], folder / "cache", FFMPEG, FFPROBE)
    store = ProjectStore(media.db_path, media)
    probe = media.import_file(str(png))
    project = store.create(
        CreateProject(request_id="new", name="tag", settings={"width": WIDTH, "height": HEIGHT})
    ).project
    batch = EditBatch.model_validate(
        {"request_id": "seed", "expected_revision": project.revision, "commands": _commands(probe)}
    )
    return apply_commands(project, batch.commands)


def _commands(probe):
    return [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
        {
            "op": "asset.import",
            "asset_id": "s",
            "label": "s",
            "probe_id": probe.id,
            "verified": probe.verified.model_dump(),
        },
        {
            "op": "clip.add",
            "clip": {
                "id": "c",
                "asset_id": "s",
                "track_id": "v",
                "position_ticks": 0,
                "duration_ticks": T,
            },
        },
    ]


def plan_for(project, tag):
    return compile_render_plan(project, "h264-720p-web", colour_tag=tag, range_ticks=(0, T))


def compile_suite(folder: Path) -> None:
    project = build_project(folder)
    plain = plan_for(project, None)
    tagged = plan_for(project, "bt709")
    plain_argv = " ".join(plain.ffmpeg_argv(str(FFMPEG), "out.mp4"))
    tagged_argv = " ".join(tagged.ffmpeg_argv(str(FFMPEG), "out.mp4"))

    assert "-colorspace" not in plain_argv, plain_argv[-300:]
    assert "-color_primaries" not in plain_argv and "-color_trc" not in plain_argv
    assert "zscale" not in json.dumps(plain.filters), plain.filters
    for flag, value in (
        ("-color_primaries", "bt709"),
        ("-color_trc", "bt709"),
        ("-colorspace", "bt709"),
    ):
        assert f"{flag} {value}" in tagged_argv, (flag, tagged_argv[-400:])
    assert any("zscale=matrix=709:range=tv,format=yuv420p" in line for line in tagged.filters), (
        tagged.filters
    )
    # The dry-run document itself has to carry the claim, the way the matte and the timecode do: a
    # reader must be able to tell "this file will declare BT.709" from the plan, not only from the
    # field they sent in.
    assert plain.summary["colour_tag"] is None, plain.summary
    assert tagged.summary["colour_tag"] == "bt709", tagged.summary
    # The switch only ever adds: everything else about the two plans has to agree.
    assert plain.mode == tagged.mode and plain.duration_ticks == tagged.duration_ticks
    print("PASS compile: untagged argv carries no colour claim; tagged adds the trio + the fold")


def export(folder: Path, project, tag, name) -> Path:
    plan = plan_for(project, tag)
    for file_name, body in plan.text_files.items():
        (folder / file_name).write_text(body, encoding="utf-8")
    out = folder / name
    run(plan.ffmpeg_argv(str(FFMPEG), str(out)))
    return out


def pixels_suite(folder: Path) -> None:
    project = build_project(folder)
    untagged = export(folder, project, None, "untagged.mp4")
    tagged = export(folder, project, "bt709", "tagged.mp4")

    def planes(path: Path) -> tuple[int, int, int]:
        raw = run(
            [
                FFMPEG,
                "-v",
                "error",
                "-i",
                path,
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "yuv444p",
                "pipe:1",
            ]
        )
        # Plane offsets come from the frame the file really holds: a preset may deliver a
        # different raster than the timeline, and indexing by the project's size would read
        # three luma pixels and call them Y/U/V (which is exactly what it did first).
        stream = frames(path)
        size = int(stream["width"]) * int(stream["height"])
        assert len(raw) >= size * 3, (len(raw), size)
        return raw[0], raw[size], raw[2 * size]

    def frames(path: Path) -> dict:
        info = json.loads(
            run(
                [
                    FFPROBE,
                    "-v",
                    "error",
                    "-select_streams",
                    "v",
                    "-show_streams",
                    "-print_format",
                    "json",
                    path,
                ]
            ).decode()
        )
        return info["streams"][0]

    def tags(path: Path) -> dict:
        info = json.loads(
            run(
                [
                    FFPROBE,
                    "-v",
                    "error",
                    "-select_streams",
                    "v",
                    "-show_streams",
                    "-print_format",
                    "json",
                    path,
                ]
            ).decode()
        )
        return {k: v for k, v in info["streams"][0].items() if k.startswith("color")}

    # What the fixture actually holds, measured rather than assumed.
    solid = run(
        [
            FFMPEG,
            "-v",
            "error",
            "-i",
            folder / "solid.png",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )
    rgb = tuple(solid[:3])
    want601 = reference_yuv(rgb, 0.299, 0.587, 0.114)
    want709 = reference_yuv(rgb, 0.2126, 0.7152, 0.0722)
    assert BT601 != BT709, (BT601, BT709)
    before, after = planes(untagged), planes(tagged)

    def close(got, want):
        return all(abs(g - w) <= 1 for g, w in zip(got, want))

    assert close(before, want601), (before, want601)
    assert close(after, want709), (after, want709)
    assert not close(after, want601), (after, want601)
    untagged_tags, tagged_tags = tags(untagged), tags(tagged)
    assert "color_space" not in untagged_tags, untagged_tags
    assert tagged_tags["color_space"] == "bt709", tagged_tags
    assert tagged_tags["color_transfer"] == "bt709" and tagged_tags["color_primaries"] == "bt709"
    # Range is the third thing a master claims. Measured the hard way first: leaving `zscale`'s
    # range at "input" carried the RGB source's full range through and the file came back
    # `yuvj420p` + `color_range=pc` around limited-range numbers, which is the same kind of lie
    # as a wrong matrix.
    assert tagged_tags.get("color_range") in (None, "tv"), tagged_tags
    assert str(frames(untagged)["pix_fmt"]) == "yuv420p", frames(untagged)
    assert str(frames(tagged)["pix_fmt"]) == "yuv420p", frames(tagged)
    print(
        f"PASS pixels: source {rgb}: untagged folds {before} (601 predicts {want601}), "
        f"tagged folds {after} (709 predicts {want709}), tags {tagged_tags}"
    )
    return tagged


def roundtrip_suite(folder: Path, master: Path) -> None:
    """The engine must recognise its own master, which is the point of writing the tags at all."""
    media = MediaService(folder / "rt.sqlite3", [folder], folder / "rt-cache", FFMPEG, FFPROBE)
    verified = media.import_file(str(master)).verified
    space, report = detect_space(verified)
    assert space == "rec709", (space, report)
    plain = media.import_file(str(folder / "untagged.mp4")).verified
    assert detect_space(plain)[0] is None, detect_space(plain)[1]
    print("PASS round trip: the tagged master reads back as rec709, the untagged one says nothing")


def refusal_suite(folder: Path) -> None:
    project = build_project(folder)
    presets = {str(item["id"]): item for item in render_presets()}
    for preset_id in ("exr-sequence", "dpx-sequence"):
        try:
            compile_render_plan(project, preset_id, colour_tag="bt709")
            raise AssertionError(f"{preset_id} accepted a colour tag it cannot carry")
        except Exception as error:  # noqa: BLE001
            assert getattr(error, "code", None) == "COLOUR_TAG_NEEDS_CONTAINER", (preset_id, error)
            assert getattr(error, "details", {}).get("preset_id") == preset_id
    # Asked of the argument builder, not of a whole project: a picture-less timeline is refused for
    # its own good reason long before the preset's shape is consulted, and mixing the two up would
    # leave this branch asserted by an error that has nothing to do with colour.
    for preset_id in ("audio-mp3", "audio-wav", "audio-flac"):
        try:
            output_args(presets[preset_id], 48_000, 30.0, colour_tag="bt709")
            raise AssertionError(f"{preset_id} accepted a colour tag")
        except EditorError as error:
            assert error.code == "COLOUR_TAG_NEEDS_PICTURE", (preset_id, error.code)
            assert error.details["preset_id"] == preset_id

    try:
        compile_render_plan(project, "h264-720p-web", colour_tag="p3-dci")
        raise AssertionError("an unknown tag was accepted")
    except EditorError as error:
        assert error.code == "UNKNOWN_COLOUR_TAG", error.code
        assert error.details["known"] == ["bt709"], error.details
    # A transparent master carries its rgba all the way to the encoder, so which matrix folded the
    # picture is not this graph's business: the claim is refused rather than guessed at...
    try:
        compile_render_plan(project, "vp9-1080p-web-alpha", colour_tag="bt709", transparent=True)
        raise AssertionError("an alpha master accepted a colour claim it cannot back")
    except EditorError as error:
        assert error.code == "COLOUR_TAG_NOT_WITH_ALPHA", error.code
        assert error.details["colour_tag"] == "bt709", error.details
    # ...and the same preset asked honestly (no tag) still compiles the alpha chain it always did.
    plain_alpha = compile_render_plan(project, "vp9-1080p-web-alpha", transparent=True)
    assert any("format=rgba[vout]" in line for line in plain_alpha.filters), plain_alpha.filters
    print(
        "PASS refusals: sequences, audio, unknown ids and alpha masters each name the reason, "
        "and the untagged alpha chain is untouched"
    )


def http_suite(folder: Path) -> None:
    """The query surface has to reach the same plan the exporter builds, and refuse bad ids."""
    media = MediaService(folder / "http.sqlite3", [folder], folder / "http-cache", FFMPEG, FFPROBE)
    store = ProjectStore(media.db_path, media)
    # One database for the store and the render queue, the way the app runs it: the worker reads the
    # project snapshot out of the file the store wrote it to.
    runtime = JobRuntime(
        media.db_path, FFMPEG, folder / "exports", [folder / "exports", folder]
    )
    png = folder / "solid.png"
    run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x{SOURCE_RGB[0]:02x}{SOURCE_RGB[1]:02x}{SOURCE_RGB[2]:02x}"
            f":s={WIDTH}x{HEIGHT}",
            "-frames:v",
            "1",
            str(png),
        ]
    )
    probe = media.import_file(str(png))
    token = "colourtag-" + "0" * 40
    with TestClient(
        create_app(store.path, token, media, jobs=runtime),
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        created = client.post(
            "/v1/projects",
            json={
                "request_id": "new",
                "name": "tag",
                "settings": {"width": WIDTH, "height": HEIGHT},
            },
        ).json()
        project = created.get("project", created)
        pid, revision = project["id"], project["revision"]
        commands = [
            {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
            {
                "op": "asset.import",
                "asset_id": "s",
                "label": "s",
                "probe_id": probe.id,
                "verified": probe.verified.model_dump(),
            },
            {
                "op": "clip.add",
                "clip": {
                    "id": "c",
                    "asset_id": "s",
                    "track_id": "v",
                    "position_ticks": 0,
                    "duration_ticks": T,
                },
            },
        ]
        seeded = client.post(
            f"/v1/projects/{pid}/edits",
            json={"request_id": "seed", "expected_revision": revision, "commands": commands},
        )
        assert seeded.status_code == 200, seeded.text[:300]

        def plan(params):
            answer = client.get(f"/v1/projects/{pid}/render-plan", params=params)
            assert answer.status_code == 200, answer.text[:300]
            return " ".join(answer.json()["argv_preview"])

        base = {"preset_id": "h264-720p-web"}
        assert "-colorspace" not in plan(base), plan(base)[-200:]
        tagged = plan(dict(base, colour_tag="bt709"))
        assert "-colorspace bt709" in tagged and "zscale=matrix=709:range=tv" in tagged, tagged[
            -300:
        ]
        bad = client.get(f"/v1/projects/{pid}/render-plan", params=dict(base, colour_tag="nope"))
        assert bad.status_code == 422, bad.text[:200]
        error = bad.json()["error"]
        assert error["code"] == "UNKNOWN_COLOUR_TAG", error
        assert error["details"]["colour_tag"] == "nope", error["details"]

        # The receipt keys the delivery, not the plan: retrying the same request_id has to hand back
        # the same job, and asking that id for a tagged master is a different delivery — refused,
        # never silently answered with the untagged file that was already queued.
        revision = seeded.json()["project"]["revision"]
        plain_body = {
            "request_id": "one",
            "expected_revision": revision,
            "preset_id": "h264-720p-web",
            "filename": "plain.mp4",
        }

        def queue(body):
            answer = client.post(f"/v1/projects/{pid}/renders", json=body)
            return answer.status_code, answer.json()

        status, first = queue(plain_body)
        assert status == 200, first
        plain_job = first["job"]
        assert plain_job["colour_tag"] is None, plain_job
        status, again = queue(plain_body)
        assert status == 200, again
        assert again["job"]["id"] == plain_job["id"], "the same request_id queued it a second time"
        status, moved = queue(dict(plain_body, colour_tag="bt709"))
        assert status == 409, moved
        assert moved["error"]["code"] == "IDEMPOTENCY_CONFLICT", moved
        status, second = queue(
            dict(plain_body, request_id="two", filename="tagged.mp4", colour_tag="bt709")
        )
        assert status == 200, second
        tagged_job = second["job"]
        assert tagged_job["colour_tag"] == "bt709", tagged_job
        assert tagged_job["id"] != plain_job["id"], (tagged_job["id"], plain_job["id"])
        # The plan shown beside a queued job is that job's own plan, and it has to say the tagged
        # master is tagged. Deterministic by construction: the runtime has a single worker thread,
        # so this second delivery is still queued while the first one is being encoded.
        shown = client.get(f"/v1/jobs/{tagged_job['id']}").json()
        assert shown["job"]["status"] in ("queued", "running"), shown["job"]
        assert shown["plan"]["colour_tag"] == "bt709", shown["plan"]
        # Both deliveries really ran, and the tag survived the round trip through the stored job.
        for job_id in (plain_job["id"], tagged_job["id"]):
            _await(runtime, job_id)
        kept = runtime._load(tagged_job["id"])
        dropped = runtime._load(plain_job["id"])
        assert kept.colour_tag == "bt709", kept
        assert dropped.colour_tag is None, dropped
    print(
        "PASS http: the query surface reaches the same plan, an unknown id is refused by name, and "
        "the queued receipts replay or conflict the way the delivery they describe says"
    )


def capability_suite() -> None:
    # Every preset that can carry a claim folds through YUV. Asserted here rather than branched on
    # in the exporter: an RGB video preset added later must make this red, not quietly ride a
    # `zscale` stage that changes nothing about it.
    foldable = [
        str(item["id"])
        for item in render_presets()
        if not item["sequence"] and item["codec"] is not None
    ]
    formats = {str(item["id"]): str(item["pixel_format"]) for item in render_presets()}
    rgb_video = [pid for pid in foldable if not formats[pid].startswith("yuv")]
    assert not rgb_video, f"these presets carry no YUV fold to tag: {rgb_video}"
    caps = capabilities()
    row = OUTPUT_COLOUR_TAGS[0]
    assert caps["output_colour_tags"] == [dict(item) for item in OUTPUT_COLOUR_TAGS]
    assert [str(item["id"]) for item in caps["output_colour_tags"]] == list(COLOUR_TAG_CODES)
    assert caps["features"]["colour_tag_delivery"] is True
    assert row["matrix"] == row["primaries"] == row["transfer"] == "bt709", row
    assert row["zscale_matrix"] == "709", row
    # A tag may only name a curve this engine can actually convert to: the delivery table and the
    # probe table have to stay joined, or a tagged master would promise a transfer nothing can read.
    assert dict(COLOR_TRANSFER_TAGS)[row["transfer"]] in COLOR_SPACES, row
    print(f"PASS capabilities: {len(COLOUR_TAG_CODES)} tag(s) published from one table")


# The digest the previous release stored for the request built below. Captured by parsing that
# commit's own `jobs.py`, lifting the `canonical = json.dumps(...)` statement out of
# `_submit_locked`, and evaluating it against that commit's own `RenderRequest` — so it is a fact
# from outside this release, not a number 1.151 can recompute and agree with. If a defaulted field
# leaked into the hash, every receipt written before 1.151 would stop replaying and the store would
# queue the same delivery a second time under a new file name.
PRE_1151_CANONICAL = '["proj_pin_1","h264-720p-web","show.mp4",null,"contain"]'
PRE_1151_FINGERPRINT = "39931bfe33e7b53745dd5d50caa79cb82065636e61bd8a6fdddc4de611a5c4cb"


def receipt_suite(folder: Path) -> None:
    """The tagged master is a different delivery; the untagged one is byte-for-byte the old."""
    base = RenderRequest(
        request_id="req_pin",
        expected_revision=7,
        preset_id="h264-720p-web",
        filename="show.mp4",
        folder=None,
        fit="contain",
    )
    assert request_fingerprint("proj_pin_1", base) == PRE_1151_FINGERPRINT, (
        "an untagged request no longer replays as the receipt 1.150 wrote"
    )
    assert (
        hashlib.sha256(PRE_1151_CANONICAL.encode()).hexdigest() == PRE_1151_FINGERPRINT
    ), "the two pins disagree about what joined the hash"
    # A 1.151 client that names the new field and leaves it null must not split the receipt either:
    # that is the same delivery, spelled with one more key.
    assert (
        request_fingerprint("proj_pin_1", base.model_copy(update={"colour_tag": None}))
        == PRE_1151_FINGERPRINT
    ), "an explicit null colour_tag split a pre-1.151 receipt"
    assert (
        request_fingerprint("proj_pin_1", base.model_copy(update={"colour_tag": "bt709"}))
        != PRE_1151_FINGERPRINT
    ), "a tagged master hashed as the untagged one, so a retry would return the wrong file"

    # A tagged delivery on a fresh id really does carry the tag through to the job record — that
    # half is checked where the project is actually persisted (`http_suite`).

    old = VerifiedMedia.model_validate(
        {
            "probe_id": "p",
            "path": "x.mp4",
            "kind": "video",
            "label": "x",
            "size_bytes": 1,
            "content_sha256": "0" * 64,
            "duration_ticks": T,
        }
    )
    assert old.color_transfer is None and old.color_space is None, old
    assert detect_space(old)[1]["reason"] == "no_color_tags", detect_space(old)[1]
    print(
        "PASS receipts: an untagged request still hashes to 1.150's receipt, a tag makes it a "
        "different delivery, and an older probe record says nothing"
    )


def main() -> None:
    assert FFMPEG.is_file(), f"needs the bundled FFmpeg at {FFMPEG}"
    capability_suite()
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        compile_suite(folder)
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        master = pixels_suite(folder)
        roundtrip_suite(folder, master)
    for suite in (refusal_suite, http_suite, receipt_suite):
        with tempfile.TemporaryDirectory() as tmp:
            suite(Path(tmp))


if __name__ == "__main__":
    main()
