"""Subject-follow reframe: the tracked mask path has to become pan-and-zoom curves that keep the
subject in the middle of the frame — and the pixels have to prove it, including that the zoom really
covers the picture instead of sliding a black edge in."""

import subprocess
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import (
    Clip,
    Keyframe,
    Project,
    ReframeRequest,
    SequenceSettings,
    ShapeMask,
    Track,
    VerifiedMedia,
)
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService
from agentcut.reframe import plan as reframe_plan

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
FRAME = 2_352_000
WIDTH, HEIGHT = 320, 180
END = 2 * T - FRAME
# The subject walks from 15% to 85% of the width; the mask centre follows it.
SWEEP = [(0, 0.15), (T, 0.5), (END, 0.85)]


def run(args, timeout=420):
    done = subprocess.run(
        args, capture_output=True, check=True, timeout=timeout, creationflags=0x08000000
    )
    return done.stdout


def source(folder: Path) -> Path:
    """A bright box sliding left to right across a mid-grey field, two seconds at 30 fps."""
    target = folder / "slider.mp4"
    run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-y",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x404040:s=320x180:r=30:d=2",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=60x60:r=30:d=2",
            "-filter_complex",
            "[0:v][1:v]overlay=x='18+112*t':y=60:eof_action=pass:eval=frame[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ]
    )
    return target


def centroid_x(path: Path, at: float) -> float:
    """Where the bright mass sits, as a fraction of the width."""
    raw = run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-ss",
            f"{at:.6f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "scale=64:36:flags=area",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "pipe:1",
        ]
    )
    # Only the subject is bright; averaging the whole frame would let the grey field drag the
    # answer to the middle and hide exactly the drift this test is about.
    columns = [
        sum(max(0, raw[row * 64 + column] - 150) for row in range(36)) for column in range(64)
    ]
    total = sum(columns)
    assert total > 0, f"nothing bright in {path} at {at}"
    return sum(index * value for index, value in enumerate(columns)) / total / 63


def corner(path: Path, at: float) -> int:
    raw = run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-ss",
            f"{at:.6f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "crop=16:16:0:0,scale=1:1:flags=area",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "pipe:1",
        ]
    )
    return raw[0]


def duration(path: Path) -> float:
    out = run(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ]
    )
    return float(out.decode().strip())


def tracked_clip(points: list[tuple[int, float]] | None = None, **mask_overrides) -> Clip:
    """A clip carrying the mask path a track would have written."""
    clip = Clip.model_validate(
        {
            "id": "c",
            "asset_id": "a",
            "track_id": "v",
            "position_ticks": 0,
            "duration_ticks": 2 * T,
        }
    )
    mask = {"shape": "rectangle", "center_x": 0.15, "center_y": 0.5, "width": 2.0, "height": 2.0}
    mask.update(mask_overrides)
    if mask.get("shape") == "path":
        mask["vertices"] = [{"x": 0.1, "y": 0.1}, {"x": 0.6, "y": 0.1}, {"x": 0.6, "y": 0.6}]
    clip.mask = ShapeMask.model_validate(mask)
    sweep = SWEEP if points is None else points
    clip.keyframes = [
        Keyframe(property="mask_x", at_ticks=at, value=value, interpolation="linear")
        for at, value in sweep
    ] + [
        Keyframe(property="mask_y", at_ticks=at, value=0.5, interpolation="linear")
        for at, _ in sweep
    ]
    return clip


def video_asset() -> dict:
    """The plan only asks whether the asset is a picture, so a server-shaped record is enough."""
    verified = VerifiedMedia.model_validate(
        {
            "probe_id": "a",
            "path": "C:/nowhere/slider.mp4",
            "kind": "video",
            "label": "slider",
            "size_bytes": 1024,
            "content_sha256": "0" * 64,
            "duration_ticks": 2 * T,
            "width": WIDTH,
            "height": HEIGHT,
            "has_audio": False,
        }
    )
    return {
        "id": "a",
        "kind": "video",
        "label": "slider",
        "reference": "r",
        "duration_ticks": 2 * T,
        "verified": verified.model_dump(),
    }


def project_with(clip: Clip) -> Project:
    return Project(
        id="p",
        name="reframe",
        settings=SequenceSettings(width=WIDTH, height=HEIGHT),
        tracks=[Track(id="v", kind="video", name="v")],
        assets={"a": video_asset()},
        clips={clip.id: clip},
    )


def refused(project: Project, *, max_scale: float = 2.0) -> str:
    try:
        reframe_plan(project, clip_id="c", max_scale=max_scale)
    except Exception as error:  # EditorError
        return getattr(error, "code", type(error).__name__)
    return "accepted"


def plan_suite() -> None:
    project = project_with(tracked_clip())
    commands, notes = reframe_plan(project, clip_id="c", max_scale=4.0)
    assert [command["property"] for command in commands] == ["x", "y", "scale"], commands
    assert all(command["op"] == "keyframes.replace" for command in commands), commands
    xs = {point["at_ticks"]: point["value"] for point in commands[0]["keyframes"]}
    assert abs(xs[0] - 0.35 * (1 / 0.3)) < 1e-3 and abs(xs[END] + 0.35 / 0.3) < 1e-3, xs
    scales = {point["at_ticks"]: point["value"] for point in commands[2]["keyframes"]}
    assert abs(scales[T] - 1.0) < 1e-6, scales
    assert abs(scales[0] - 1 / (1 - 2 * 0.35)) < 1e-3, scales
    assert notes["clamped_points"] == 0 and "warning" not in notes, notes
    assert notes["max_offset"] > 1.1, notes
    # Two of the mask's own keyframes joined by a straight line leave a 0.1-wide hole in the middle,
    # because the zoom a centre offset demands is hyperbolic. The follow has to be sampled denser.
    assert notes["followed_points"] > 3 and notes["keyframes_added"] > 0, notes
    assert notes["worst_offset"] < notes["tolerance"] * 1.5, notes
    print(
        "   reframe: a 0.15→0.85 sweep becomes x=∓0.35 with just enough zoom"
        f" ({scales[0]:.3f}x) to still cover the frame, refined to"
        f" {notes['followed_points']} keyframes holding {notes['worst_offset']:.4f} wide"
    )

    # The knob is a real trade, not decoration: asking loosely has to cost fewer keyframes and give
    # back a looser hold on the subject.
    _, loose = reframe_plan(project, clip_id="c", max_scale=4.0, tolerance=0.2)
    assert loose["followed_points"] < notes["followed_points"], (loose, notes)
    assert loose["worst_offset"] > notes["worst_offset"], (loose, notes)
    assert loose["tolerance"] == 0.2, loose
    for bad in (0.0, -0.1, 0.5):
        try:
            ReframeRequest(request_id="req-1", expected_revision=1, tolerance=bad)
        except ValidationError:
            pass
        else:
            raise AssertionError(f"the contract accepted tolerance {bad}")
    print(
        f"   reframe: asking for 0.2 instead of {notes['tolerance']} drops"
        f" {notes['followed_points']} keyframes to {loose['followed_points']} and holds"
        f" {loose['worst_offset']:.3f} instead of {notes['worst_offset']:.4f}"
    )

    # A clip can carry an animation clock offset: stored keyframes are absolute (timeline), while
    # `keyframes.replace` adds the offset back when it writes. Reading one clock and writing the
    # other without converting lands the whole follow one offset late.
    offset = T // 3
    absolute = [(at + offset, value) for at, value in SWEEP]
    shifted = tracked_clip(absolute)
    shifted.animation_offset_ticks = offset
    commands, notes = reframe_plan(project_with(shifted), clip_id="c", max_scale=4.0)
    written = {command["property"]: command["keyframes"] for command in commands}
    local_ticks = [point["at_ticks"] for point in written["x"]]
    assert all(right > left for left, right in zip(local_ticks, local_ticks[1:])), local_ticks
    assert local_ticks[0] == SWEEP[0][0] and local_ticks[-1] == SWEEP[-1][0], local_ticks
    assert {at for at, _ in SWEEP} <= set(local_ticks), local_ticks
    plain_values = {
        point["at_ticks"]: point["value"]
        for point in reframe_plan(project, clip_id="c", max_scale=4.0)[0][0]["keyframes"]
    }
    assert all(
        abs(plain_values[point["at_ticks"]] - point["value"]) < 1e-9 for point in written["x"]
    ), "the offset moved the clock, not the framing"
    print(
        "   reframe: a clip offset by one third of a second still writes clip-local ticks"
        f" ({local_ticks[0]}…{local_ticks[-1]}) identical to the unshifted framing"
    )

    # A split leaves the head's keyframes on the tail, so a tail's window can begin mid-segment. The
    # follow then has to carry the framing the path already had at the cut, on the tail's own clock.
    tail = tracked_clip()
    tail.animation_offset_ticks = T // 2
    tail.duration_ticks = 2 * T - T // 2
    commands, notes = reframe_plan(project_with(tail), clip_id="c", max_scale=4.0)
    points = commands[0]["keyframes"]
    times = [point["at_ticks"] for point in points]
    assert times[0] == 0, times
    assert {0, T // 2, END - T // 2} <= set(times), times
    assert all(right > left for left, right in zip(times, times[1:])), "duplicate clip-local ticks"
    scales = {point["at_ticks"]: point["value"] for point in commands[2]["keyframes"]}
    assert abs(scales[0] - 1 / (1 - 2 * 0.175)) < 1e-4, scales
    assert abs(points[0]["value"] - scales[0] * 0.175) < 1e-4, points
    assert notes["ticks"] == [times[0], times[-1]], notes
    assert notes["first_centre"] == [0.325, 0.5], notes
    print(
        "   reframe: a tail cut mid-segment carries the framing at the cut"
        f" (head x={points[0]['value']:.3f} at {scales[0]:.3f}x) on clip-local ticks"
    )

    # A clip placed after the tracked path holds the path's last centre; that is followable too,
    # and inventing negative clip-local ticks is not.
    after = tracked_clip()
    after.animation_offset_ticks = 3 * T
    commands, notes = reframe_plan(project_with(after), clip_id="c", max_scale=4.0)
    assert notes["followed_points"] == 1 and commands[0]["keyframes"][0]["at_ticks"] == 0, notes
    assert abs(commands[0]["keyframes"][0]["value"] + 1.166667) < 1e-4, commands[0]["keyframes"]
    print("   reframe: a clip beyond the end of the path follows the last centre it holds")

    # A real track writes one mask keyframe per frame. Three follow curves of the same length would
    # not fit the clip's keyframe budget, and the write would be refused after the plan promised it,
    # so the path is sampled to the room the contract actually leaves.
    def dense(frames: int, tick: int) -> Clip:
        clip = tracked_clip()
        clip.duration_ticks = frames * tick
        clip.keyframes = [
            Keyframe(
                property=name,
                at_ticks=index * tick,
                value=0.2 + 0.6 * index / frames,
                interpolation="linear",
            )
            for name in ("mask_x", "mask_y")
            for index in range(frames)
        ]
        return clip

    for frames in (600, 950):
        crowded = dense(frames, FRAME)
        commands, notes = reframe_plan(project_with(crowded), clip_id="c", max_scale=4.0)
        written = [
            Keyframe.model_validate(item) for command in commands for item in command["keyframes"]
        ]
        assert len(crowded.keyframes) == 2 * frames, crowded.keyframes
        assert notes["keyframes_dropped"] > 0, notes
        assert len(commands[0]["keyframes"]) == notes["followed_points"] <= notes["keyframe_budget"]
        assert notes["keyframe_budget"] <= min(48, (2000 - 2 * frames) // 3), notes
        Clip.model_validate(
            {
                **crowded.model_dump(),
                "keyframes": [k.model_dump() for k in crowded.keyframes + written],
            }
        )
        print(
            f"   reframe: a {frames}-frame track becomes {notes['followed_points']} follow"
            f" keyframes inside the clip's budget of {notes['keyframe_budget']},"
            f" holding {notes['worst_offset']:.4f} wide"
        )

    _, tight = reframe_plan(project, clip_id="c", max_scale=1.5)
    assert tight["clamped_points"] > 0 and "warning" in tight, tight
    assert tight["max_scale"] == 1.5, tight
    print(f"   reframe: a 1.5x ceiling says so — {tight['warning']}")

    no_curves = tracked_clip()
    no_curves.keyframes = []
    only_x = tracked_clip()
    only_x.keyframes = [k for k in only_x.keyframes if k.property == "mask_x"]
    stepped = tracked_clip()
    stepped.keyframes = [
        Keyframe(property=k.property, at_ticks=k.at_ticks, value=k.value, interpolation="hold")
        for k in stepped.keyframes
    ]
    cases = {
        "no mask": refused(project_with(tracked_clip_with_no_mask()), max_scale=2.0),
        "path mask": refused(project_with(tracked_clip(shape="path")), max_scale=2.0),
        "inverted mask": refused(project_with(tracked_clip(inverted=True)), max_scale=2.0),
        "no centre curves": refused(project_with(no_curves), max_scale=2.0),
        "impossible ceiling": refused(project_with(tracked_clip()), max_scale=9.0),
    }
    assert all(value == "INVALID_REFRAME" for value in cases.values()), cases
    # Each axis is read through the render's own sampler, so one curve and a stepped curve are both
    # followable; they used to be refused because the planner paired keyframes by hand.
    half, notes = reframe_plan(project_with(only_x), clip_id="c", max_scale=4.0)
    assert notes["worst_offset"] < 0.02, notes
    assert all(point["value"] == 0.0 for point in half[1]["keyframes"]), half[1]
    held, notes = reframe_plan(project_with(stepped), clip_id="c", max_scale=4.0)
    assert notes["keyframes_added"] == 0, notes
    assert all(point["interpolation"] == "hold" for point in held[0]["keyframes"]), held[0]
    print(
        "   reframe: one animated axis follows with the other held still, and a stepped path stays"
        " stepped without inventing keyframes"
    )
    missing = Project(
        id="q",
        name="empty",
        settings=SequenceSettings(),
        tracks=[Track(id="v", kind="video", name="v")],
    )
    try:
        reframe_plan(missing, clip_id="c")
    except Exception as error:
        assert getattr(error, "code", "") == "NOT_FOUND", error
    else:
        raise AssertionError("reframe invented a clip")
    try:
        ReframeRequest(request_id="req-1", expected_revision=1, max_scale=0.5)
    except ValidationError:
        pass
    else:
        raise AssertionError("the contract accepted a sub-1x ceiling")
    print(
        "   reframe: no mask, a path mask, an inverted one, an unanimated mask and an"
        " impossible ceiling are each refused by name"
    )


def tracked_clip_with_no_mask() -> Clip:
    clip = tracked_clip()
    clip.mask = None
    return clip


def render(client: TestClient, path: str, revision: int, request_id: str, name: str) -> Path:
    queued = client.post(
        path + "/renders",
        json={
            "request_id": request_id,
            "expected_revision": revision,
            "preset_id": "h264-720p-web",
            "filename": name,
        },
    )
    assert queued.status_code == 200, queued.text
    job = queued.json()["job"]
    status = {}
    for _ in range(600):
        status = client.get("/v1/jobs/" + job["id"]).json()["job"]
        if status["status"] in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.5)
    assert status["status"] == "succeeded", status
    return Path(status["output_path"])


def seed_commands(verified: dict) -> list[dict]:
    return [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
        {
            "op": "asset.import",
            "asset_id": "a",
            "label": "slider",
            "probe_id": verified["probe_id"],
            "verified": verified,
        },
        {
            "op": "clip.add",
            "clip": {
                "id": "c",
                "asset_id": "a",
                "track_id": "v",
                "position_ticks": 0,
                "duration_ticks": 2 * T,
            },
        },
        {
            "op": "clip.mask",
            "clip_id": "c",
            "mask": {
                "shape": "rectangle",
                "center_x": 0.15,
                "center_y": 0.5,
                "width": 2.0,
                "height": 2.0,
            },
        },
        {
            "op": "keyframes.replace",
            "clip_id": "c",
            "property": "mask_x",
            "keyframes": [
                {"property": "mask_x", "at_ticks": at, "value": value, "interpolation": "linear"}
                for at, value in SWEEP
            ],
        },
        {
            "op": "keyframes.replace",
            "clip_id": "c",
            "property": "mask_y",
            "keyframes": [
                {"property": "mask_y", "at_ticks": at, "value": 0.5, "interpolation": "linear"}
                for at, _ in SWEEP
            ],
        },
    ]


def http_suite(folder: Path) -> None:
    media = MediaService(folder / "rf-db.sqlite3", [folder], folder / "rf-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "rf-api.sqlite3", FFMPEG, folder / "deliverables", [folder / "deliverables"]
    )
    runtime.ensure_worker()
    token = "reframechk" + "f" * 52
    app = create_app(folder / "rf-api.sqlite3", token, media=media, jobs=runtime)
    clip = source(folder)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        caps = client.get("/v1/capabilities").json()
        assert caps["features"]["subject_reframe"] is True, caps["features"]
        probe = client.post("/v1/media/import", json={"path": str(clip)}).json()
        created = client.post("/v1/projects", json={"request_id": "new", "name": "reframe"}).json()[
            "project"
        ]
        path = f"/v1/projects/{created['id']}"
        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "seed",
                "expected_revision": 0,
                "commands": seed_commands(probe["verified"]),
            },
        )
        assert seeded.status_code == 200, seeded.text
        revision = seeded.json()["project"]["revision"]
        # Renders lock to the current revision, so the "before" file has to be made first.
        plain = render(client, path, revision, "r-before", "before.mp4")
        drift = [centroid_x(plain, at) for at in (0.1, 1.0, 1.9)]
        assert drift[0] < 0.32 and drift[2] > 0.68, drift

        endpoint = path + "/clips/c/reframe"

        def request(request_id, **extra):
            return client.post(
                endpoint,
                json={
                    "request_id": request_id,
                    "expected_revision": extra.pop("revision", revision),
                    "max_scale": 4.0,
                    **extra,
                },
            )

        preview = request("p")
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["committed"] is False and len(body["commands"]) == 3, body
        assert body["reframe"]["clamped_points"] == 0, body["reframe"]
        assert body["reframe"]["tolerance"] == 0.01, body["reframe"]
        loose = request("pl", tolerance=0.2)
        assert loose.json()["reframe"]["tolerance"] == 0.2, loose.text
        assert len(loose.json()["commands"][0]["keyframes"]) < len(
            body["commands"][0]["keyframes"]
        ), (len(loose.json()["commands"][0]["keyframes"]), len(body["commands"][0]["keyframes"]))
        assert len(body["commands"][0]["keyframes"]) > 3, len(body["commands"][0]["keyframes"])
        assert client.get(path).json()["revision"] == revision, "planning wrote"
        dry = request("d", apply=True, dry_run=True)
        assert dry.json()["committed"] is False, dry.text
        assert client.get(path).json()["revision"] == revision, "a dry run wrote"
        applied = request("a", apply=True)
        assert applied.status_code == 200, applied.text
        after = applied.json()["project"]
        assert after["revision"] == revision + 1, after["revision"]
        curves = {
            name: [k for k in after["clips"]["c"]["keyframes"] if k["property"] == name]
            for name in ("x", "y", "scale")
        }
        # The mask's own ticks are all there, plus the ones the planner added to hold the middle.
        assert all(len(points) > 3 for points in curves.values()), {
            k: len(v) for k, v in curves.items()
        }
        assert len({len(v) for v in curves.values()}) == 1, {k: len(v) for k, v in curves.items()}
        assert {at for at, _ in SWEEP} <= {k["at_ticks"] for k in curves["x"]}, curves["x"]
        replay = request("a", apply=True)
        assert replay.json()["replayed"] is True, replay.text
        assert client.get(path).json()["revision"] == revision + 1, "a replay added a revision"
        stale = request("s", revision=revision, apply=True)
        assert stale.status_code == 409, stale.text
        print(
            "   reframe: plan and dry-run write nothing, one apply is one revision, a replay"
            " returns its receipt, a stale revision is refused"
        )

        moved = render(client, path, revision + 1, "r-after", "after.mp4")
        # Probed across the whole clip, not just at the tracked ticks: keyframes alone overshot by
        # a fifth of a frame width between them, and that is the defect this closes.
        probes = (0.05, 0.3, 0.55, 0.8, 1.05, 1.3, 1.55, 1.8, 1.95)
        held = [centroid_x(moved, at) for at in probes]
        worst = max(abs(value - 0.5) for value in held)
        assert worst < 0.08, held
        assert sum(abs(value - 0.5) for value in held) / len(held) < 0.04, held
        # The number the engine claimed and the pixels agree.
        assert worst < body["reframe"]["worst_offset"] + 0.06, (worst, body["reframe"])
        assert sum(abs(value - 0.5) for value in drift) / 3 > 0.2, drift
        edges = [corner(moved, at) for at in (0.05, 1.95)]
        assert all(value > 30 for value in edges), edges
        assert abs(duration(moved) - 2.0) <= 0.05, duration(moved)
        print(
            f" and holds {[f'{value:.2f}' for value in held[:4]]}…{held[-1]:.2f} across"
            f" {len(probes)} probes (worst {worst:.3f}), corners"
            f" {edges[0]}/{edges[1]} (no black edge)"
        )

        undone = client.post(
            path + "/restore",
            json={
                "request_id": "undo",
                "expected_revision": revision + 1,
                "target_revision": revision,
            },
        )
        back = undone.json()["project"]
        assert back["revision"] == revision + 2, back["revision"]
        assert not [
            k for k in back["clips"]["c"]["keyframes"] if k["property"] in {"x", "y", "scale"}
        ], "the reframe curves survived the restore"
        print("   reframe: restoring to before it leaves no pan or zoom curves behind")

        # A split is how a real clip acquires an animation clock offset, and it is exactly where the
        # two clocks can disagree. This is the same defect the plan suite asserts on ticks; here the
        # pixels have to say it too.
        split = client.post(
            path + "/edits",
            json={
                "request_id": "split",
                "expected_revision": revision + 2,
                "commands": [
                    {"op": "clip.split", "clip_id": "c", "at_ticks": T, "right_clip_id": "c2"}
                ],
            },
        )
        assert split.status_code == 200, split.text
        parts = split.json()["project"]["clips"]
        tail = parts["c2"]
        assert tail["animation_offset_ticks"] == T, tail["animation_offset_ticks"]
        tail_path = path + "/clips/c2/reframe"
        reframed = client.post(
            tail_path,
            json={
                "request_id": "tail",
                "expected_revision": revision + 3,
                "max_scale": 4.0,
                "apply": True,
            },
        )
        assert reframed.status_code == 200, reframed.text
        keys = reframed.json()["project"]["clips"]["c2"]["keyframes"]
        mask_ticks = sorted({k["at_ticks"] for k in keys if k["property"] == "mask_x"})
        start = tail["animation_offset_ticks"]
        assert mask_ticks[0] < start, f"the split carried no head keyframe: {mask_ticks}"
        window = [at for at in mask_ticks if start <= at <= start + tail["duration_ticks"]]
        follow_ticks = sorted({k["at_ticks"] for k in keys if k["property"] == "x"})
        assert window and set(window) <= set(follow_ticks), (follow_ticks, window)
        assert min(follow_ticks) == start, follow_ticks
        assert max(follow_ticks) <= start + tail["duration_ticks"], follow_ticks
        tail_out = render(client, path, revision + 4, "r-tail", "tail.mp4")
        # The tail is followed on its own clock, so what matters is that the subject stays centred
        # across the whole tail rather than only where the tracker happened to leave a keyframe.
        probes = (1.0, 1.2, 1.45, 1.7, 1.9, 1.96)
        held = [centroid_x(tail_out, at) for at in probes]
        left = [centroid_x(plain, at) for at in probes]
        assert max(abs(value - 0.5) for value in held) < 0.08, held
        claimed = sum(abs(v - 0.5) for v in held) / len(held)
        unfollowed = sum(abs(v - 0.5) for v in left) / len(left)
        assert unfollowed > 4 * claimed, (held, left)
        assert all(corner(tail_out, at) > 30 for at in (1.0, 1.9)), tail_out
        print(
            f"   reframe: a split tail keyed on the shared clock (offset {T}) holds"
            f" {[f'{v:.2f}' for v in held]} where the unfollowed render sits at"
            f" {[f'{v:.2f}' for v in left]}"
        )


def main() -> None:
    folder = Path(tempfile.mkdtemp(prefix="agentcut-reframe-"))
    plan_suite()
    http_suite(folder)
    print("PASS: a tracked subject path becomes pan-and-zoom the pixels confirm holds it centred")


if __name__ == "__main__":
    main()
