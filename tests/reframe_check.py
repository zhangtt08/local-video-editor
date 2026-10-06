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


def tracked_clip(**mask_overrides) -> Clip:
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
    clip.keyframes = [
        Keyframe(property="mask_x", at_ticks=at, value=value, interpolation="linear")
        for at, value in SWEEP
    ] + [
        Keyframe(property="mask_y", at_ticks=at, value=0.5, interpolation="linear")
        for at, _ in SWEEP
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
    assert notes["followed_points"] == 3 and notes["max_offset"] > 1.1, notes
    print(
        "   reframe: a 0.15→0.85 sweep becomes x=∓0.35 with just enough zoom"
        f" ({scales[0]:.3f}x) to still cover the frame"
    )

    _, tight = reframe_plan(project, clip_id="c", max_scale=1.5)
    assert tight["clamped_points"] > 0 and "warning" in tight, tight
    assert tight["max_scale"] == 1.5, tight
    print(f"   reframe: a 1.5x ceiling says so — {tight['warning']}")

    no_curves = tracked_clip()
    no_curves.keyframes = []
    only_x = tracked_clip()
    only_x.keyframes = [k for k in only_x.keyframes if k.property == "mask_x"]
    disagree = tracked_clip()
    disagree.keyframes[0] = Keyframe(
        property="mask_x", at_ticks=0, value=0.15, interpolation="hold"
    )
    cases = {
        "no mask": refused(project_with(tracked_clip_with_no_mask()), max_scale=2.0),
        "path mask": refused(project_with(tracked_clip(shape="path")), max_scale=2.0),
        "inverted mask": refused(project_with(tracked_clip(inverted=True)), max_scale=2.0),
        "no centre curves": refused(project_with(no_curves), max_scale=2.0),
        "one axis only": refused(project_with(only_x), max_scale=2.0),
        "curves disagree": refused(project_with(disagree), max_scale=2.0),
        "impossible ceiling": refused(project_with(tracked_clip()), max_scale=9.0),
    }
    assert all(value == "INVALID_REFRAME" for value in cases.values()), cases
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
        "   reframe: no mask, a path mask, an inverted one, missing or disagreeing curves and an"
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
        assert all(len(points) == 3 for points in curves.values()), {
            k: len(v) for k, v in curves.items()
        }
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
        # At the tracked ticks the follow is exact; between them it is the mask path's own linear
        # approximation, so the claim under test is "it holds the middle", not "it is perfect".
        held = [centroid_x(moved, at) for at in (0.1, 1.0, 1.9)]
        assert max(held) - min(held) < 0.2, held
        assert sum(abs(value - 0.5) for value in held) / 3 < 0.06, held
        assert sum(abs(value - 0.5) for value in drift) / 3 > 0.2, drift
        edges = [corner(moved, at) for at in (0.1, 1.9)]
        assert all(value > 30 for value in edges), edges
        assert abs(duration(moved) - 2.0) <= 0.05, duration(moved)
        print(
            f" and holds {held[0]:.2f}→{held[2]:.2f} with it,"
            f" corners {edges[0]}/{edges[1]} (no black edge)"
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


def main() -> None:
    folder = Path(tempfile.mkdtemp(prefix="agentcut-reframe-"))
    plan_suite()
    http_suite(folder)
    print("PASS: a tracked subject path becomes pan-and-zoom the pixels confirm holds it centred")


if __name__ == "__main__":
    main()
