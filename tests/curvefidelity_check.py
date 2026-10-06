"""Curve fidelity: the animation the engine computes and the pixels FFmpeg draws have to agree at
points the keyframes did not choose.

Every animated property has one authority (`animation.sample`) and one compile target
(`animation.expression`, fed to FFmpeg). Both were written to agree, and the comment inside
`expression()` records a real trap: FFmpeg's root evaluator inverts the monotone temporal cubic.
Feature checks then measure the export at the timestamps that happen to carry a keyframe — where any
piecewise curve is exact by construction, so a compile error in the middle of a segment passes
unnoticed. This check probes densely *between* the keyframes for the four properties a compositor
moves: position, scale, opacity, and the mask centre.
"""

import subprocess
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentcut.animation import sample
from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import (
    Bezier,
    Clip,
    Keyframe,
    Project,
    SequenceSettings,
    Track,
    VerifiedMedia,
)
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
FRAME = 2_352_000  # one frame at 30 fps
END = 2 * T - FRAME
WIDTH, HEIGHT = 320, 180
GREY = 0x40
# Probes chosen so several of them fall strictly inside a segment rather than on its endpoints.
PROBES = (0.08, 0.21, 0.34, 0.47, 0.62, 0.79, 0.94, 1.11, 1.29, 1.44, 1.61, 1.78, 1.93)
# Keyframed motion: an ease in, a bezier out, and a scale that peaks mid-segment.
X_KEYS = [
    Keyframe(property="x", at_ticks=0, value=0.0, interpolation="ease"),
    Keyframe(
        property="x",
        at_ticks=T,
        value=0.28,
        interpolation="bezier",
        bezier=Bezier(x1=0.1, y1=0.9, x2=0.4, y2=0.2),
    ),
    Keyframe(property="x", at_ticks=END, value=-0.2, interpolation="linear"),
]
SCALE_KEYS = [
    Keyframe(property="scale", at_ticks=0, value=1.0, interpolation="linear"),
    Keyframe(property="scale", at_ticks=int(0.7 * T), value=1.45, interpolation="ease"),
    Keyframe(property="scale", at_ticks=END, value=0.8, interpolation="linear"),
]
OPACITY_KEYS = [
    Keyframe(property="opacity", at_ticks=0, value=1.0, interpolation="ease"),
    Keyframe(property="opacity", at_ticks=int(1.3 * T), value=0.62, interpolation="bezier"),
    Keyframe(property="opacity", at_ticks=END, value=1.0, interpolation="linear"),
]


def run(args, timeout=420):
    done = subprocess.run(
        args, capture_output=True, check=True, timeout=timeout, creationflags=0x08000000
    )
    return done.stdout


def source(folder: Path) -> Path:
    """A static white square on a grey field: any movement in the export is the clip's own."""
    target = folder / "box.mp4"
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
            f"color=c=0x404040:s={WIDTH}x{HEIGHT}:r=30:d=2",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=60x60:r=30:d=2",
            "-filter_complex",
            "[0:v][1:v]overlay=x=130:y=60:eof_action=pass[v]",
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


def field(folder: Path) -> Path:
    """A flat grey field: the picture under the animated layer must not compete with it."""
    target = folder / "field.mp4"
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
            f"color=c=0x404040:s={WIDTH}x{HEIGHT}:r=30:d=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ]
    )
    return target


def clip_with_keys() -> Clip:
    clip = Clip.model_validate(
        {
            "id": "c",
            "asset_id": "a",
            "track_id": "v",
            "position_ticks": 0,
            "duration_ticks": 2 * T,
        }
    )
    clip.keyframes = X_KEYS + SCALE_KEYS + OPACITY_KEYS
    return clip


def video_asset() -> dict:
    verified = VerifiedMedia.model_validate(
        {
            "probe_id": "a",
            "path": "C:/nowhere/box.mp4",
            "kind": "video",
            "label": "box",
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
        "label": "box",
        "reference": "r",
        "duration_ticks": 2 * T,
        "verified": verified.model_dump(),
    }


def project() -> Project:
    return Project(
        id="p",
        name="curve fidelity",
        settings=SequenceSettings(width=WIDTH, height=HEIGHT),
        tracks=[Track(id="v", kind="video", name="v")],
        assets={"a": video_asset()},
        clips={"c": clip_with_keys()},
    )


def frame_rows(path: Path, at: float) -> list:
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
            "scale=160:90:flags=area",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "pipe:1",
        ]
    )
    return [list(raw[row * 160 : (row + 1) * 160]) for row in range(90)]


def measure(path: Path, at: float) -> dict:
    """Centroid, lit area and the level of the box's flat interior — position, scale and opacity.

    The interior, not the mean of everything above a threshold: a per-frame resample softens the
    edges, and averaging those pixels would blame the compositor for my own measurement.
    """
    rows = frame_rows(path, at)
    total = 0
    weight = 0
    column_weight = 0
    row_weight = 0
    for y, row in enumerate(rows):
        for x, value in enumerate(row):
            if value <= GREY + 40:
                continue
            total += 1
            weight += value
            column_weight += x * value
            row_weight += y * value
    assert total > 0, f"nothing bright in {path} at {at}"
    cx = round(column_weight / weight)
    cy = round(row_weight / weight)
    interior = [
        rows[y][x]
        for y in range(max(0, cy - 3), min(90, cy + 4))
        for x in range(max(0, cx - 3), min(160, cx + 4))
    ]
    return {
        "x": column_weight / weight / 159,
        "y": row_weight / weight / 89,
        "area": total / (160 * 90),
        "level": sum(interior) / len(interior),
    }


def expected(at_ticks: int) -> dict:
    clip = clip_with_keys()
    x = sample(clip, "x", at_ticks)
    scale = sample(clip, "scale", at_ticks)
    opacity = sample(clip, "opacity", at_ticks)
    # The source square is centred at 0.5, so the layer law `0.5 + scale*(c-0.5) + x` reduces to
    # `0.5 + x`; its area scales with scale^2, and a white square over 0x40 grey reads as a blend.
    side = (60 / WIDTH) * scale
    return {
        "x": 0.5 + x,
        "y": 0.5,
        "area": side * ((60 / HEIGHT) * scale),
        "level": GREY + (255 - GREY) * opacity,
    }


def rgb_rows(path: Path, at: float) -> list:
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
            "scale=160:90:flags=area",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )
    return [
        [tuple(raw[(y * 160 + x) * 3 : (y * 160 + x) * 3 + 3]) for x in range(160)]
        for y in range(90)
    ]


def composite_suite(client: TestClient, folder: Path, verified_box: dict) -> Path:
    """A faded layer must reveal the track under it, blended by the curve it was given.

    This is also the combination that used to crash the render: a clip whose size and opacity are
    both animated, sitting above another track. So the check proves the export survives and that the
    blend is the one the fade curve asked for, not merely that some picture came out.
    """
    red = folder / "red.mp4"
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
            f"color=c=0xC00000:s={WIDTH}x{HEIGHT}:r=30:d=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(red),
        ]
    )
    probe = client.post("/v1/media/import", json={"path": str(red)}).json()
    created = client.post(
        "/v1/projects", json={"request_id": "comp-new", "name": "composite"}
    ).json()["project"]
    path = f"/v1/projects/{created['id']}"
    commands = [
        {"op": "track.add", "track": {"id": "under", "kind": "video", "name": "下"}},
        {"op": "track.add", "track": {"id": "over", "kind": "video", "name": "上"}},
        {
            "op": "asset.import",
            "asset_id": "red",
            "label": "red",
            "probe_id": probe["verified"]["probe_id"],
            "verified": probe["verified"],
        },
        {
            "op": "asset.import",
            "asset_id": "a",
            "label": "box",
            "probe_id": verified_box["probe_id"],
            "verified": verified_box,
        },
        {
            "op": "clip.add",
            "clip": {
                "id": "bottom",
                "asset_id": "red",
                "track_id": "under",
                "position_ticks": 0,
                "duration_ticks": 2 * T,
            },
        },
        {
            "op": "clip.add",
            "clip": {
                "id": "top",
                "asset_id": "a",
                "track_id": "over",
                "position_ticks": 0,
                "duration_ticks": 2 * T,
            },
        },
        {"op": "clip.effects", "clip_id": "top", "effects": {"opacity": 0.5}},
        {
            "op": "keyframes.replace",
            "clip_id": "top",
            "property": "scale",
            "keyframes": [key.model_dump() for key in SCALE_KEYS],
        },
        {
            "op": "keyframes.replace",
            "clip_id": "top",
            "property": "opacity",
            "keyframes": [key.model_dump() for key in OPACITY_KEYS],
        },
    ]
    seeded = client.post(
        path + "/edits",
        json={"request_id": "comp-seed", "expected_revision": 0, "commands": commands},
    )
    assert seeded.status_code == 200, seeded.text
    revision = seeded.json()["project"]["revision"]
    queued = client.post(
        path + "/renders",
        json={
            "request_id": "comp-render",
            "expected_revision": revision,
            "preset_id": "h264-source-quality",
            "filename": "composite.mp4",
        },
    )
    assert "job" in queued.json(), queued.text
    job = queued.json()["job"]
    status = {}
    for _ in range(600):
        status = client.get("/v1/jobs/" + job["id"]).json()["job"]
        if status["status"] in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.5)
    assert status["status"] == "succeeded", status
    out = Path(status["output_path"])
    reference = clip_with_keys()
    reference.keyframes = OPACITY_KEYS
    for at in (0.2, 0.9, 1.29, 1.9):
        # What the fade curve says the pixel should be: the red track under the layer's grey field
        # and under its white box, blended by the alpha the same sampler the render uses.
        # Both samples sit inside the layer even at its smallest scale (0.8), where the frame's own
        # corners would legitimately show the track below.
        alpha = sample(reference, "opacity", round(at * T))
        rows = rgb_rows(out, at)
        for pixel, over in ((rows[20][35], GREY), (rows[45][80], 255)):
            want = (192 * (1 - alpha) + over * alpha, over * alpha, over * alpha)
            drift = max(abs(pixel[i] - want[i]) for i in range(3))
            assert drift < 26, (
                f"t={at}: above the red track the export reads {pixel}, the fade curve asks for "
                f"({want[0]:.0f},{want[1]:.0f},{want[2]:.0f}) — off by {drift:.0f}"
            )
    return out


def pixel_suite(folder: Path) -> list:
    service = MediaService(folder / "cf-db.sqlite3", [folder], folder / "cf-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "cf-api.sqlite3",
        FFMPEG,
        folder / "deliverables",
        [folder / "deliverables"],
    )
    runtime.ensure_worker()
    token = "curvefidelity" + "d" * 51
    app = create_app(folder / "cf-api.sqlite3", token, media=service, jobs=runtime)
    clip = source(folder)
    errors: list[str] = []
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        probe = client.post("/v1/media/import", json={"path": str(clip)}).json()
        verified = probe["verified"]
        under = client.post("/v1/media/import", json={"path": str(field(folder))}).json()
        created = client.post(
            "/v1/projects", json={"request_id": "new", "name": "curve fidelity"}
        ).json()["project"]
        path = f"/v1/projects/{created['id']}"
        commands = [
            {"op": "track.add", "track": {"id": "under", "kind": "video", "name": "底"}},
            {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
            {
                "op": "asset.import",
                "asset_id": "field",
                "label": "field",
                "probe_id": under["verified"]["probe_id"],
                "verified": under["verified"],
            },
            {
                "op": "clip.add",
                "clip": {
                    "id": "base",
                    "asset_id": "field",
                    "track_id": "under",
                    "position_ticks": 0,
                    "duration_ticks": 2 * T,
                },
            },
            {
                "op": "asset.import",
                "asset_id": "a",
                "label": "box",
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
        ]
        for name, keys in (("x", X_KEYS), ("scale", SCALE_KEYS), ("opacity", OPACITY_KEYS)):
            commands.append(
                {
                    "op": "keyframes.replace",
                    "clip_id": "c",
                    "property": name,
                    "keyframes": [key.model_dump() for key in keys],
                }
            )
        seeded = client.post(
            path + "/edits",
            json={"request_id": "seed", "expected_revision": 0, "commands": commands},
        )
        assert seeded.status_code == 200, seeded.text
        revision = seeded.json()["project"]["revision"]
        queued = client.post(
            path + "/renders",
            json={
                "request_id": "r",
                "expected_revision": revision,
                "preset_id": "h264-source-quality",
                "filename": "curves.mp4",
            },
        )
        job = queued.json()["job"]
        status = {}
        for _ in range(600):
            status = client.get("/v1/jobs/" + job["id"]).json()["job"]
            if status["status"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.5)
        assert status["status"] == "succeeded", status
        out = Path(status["output_path"])
        composite_suite(client, folder, verified)
        for at in PROBES:
            at_ticks = round(at * T)
            got = measure(out, at)
            want = expected(at_ticks)
            for name in ("x", "y", "area", "level"):
                tolerance = {"x": 0.02, "y": 0.03, "area": 0.18, "level": 16.0}[name]
                drift = abs(got[name] - want[name])
                if name == "area":
                    drift = drift / max(want[name], 1e-9)
                if drift > tolerance:
                    errors.append(
                        f"t={at:.2f}s {name}: pixels {got[name]:.4f} vs authority "
                        f"{want[name]:.4f} (drift {drift:.4f} > {tolerance})"
                    )
    return errors


def guard_suite() -> None:
    """The check has to be able to fail: a curve the authority disagrees with must be caught."""
    clip = clip_with_keys()
    middle = round(0.34 * T)
    authority = sample(clip, "x", middle)
    assert authority != 0.0, "an ease segment must already have moved by a third of a second"
    assert abs(sample(clip, "scale", int(0.35 * T)) - 1.0) > 0.05, "scale must be mid-segment too"
    try:
        Keyframe(property="x", at_ticks=0, value=0.0, interpolation="bezier", bezier=None)
    except ValidationError:
        pass
    print(
        f"   curves: authority values mid-segment x={authority:.4f} (probed, not asserted at keys)"
    )


def main() -> None:
    folder = Path(tempfile.mkdtemp(prefix="agentcut-curves-"))
    guard_suite()
    errors = pixel_suite(folder)
    assert not errors, "the export disagrees with the animation authority:\n" + "\n".join(errors)
    print(
        f"PASS: {len(PROBES)} probe times between the keyframes agree with the engine's own sampler"
        " on position, scale and opacity"
    )


if __name__ == "__main__":
    main()
