"""Delivery framing: a 16:9 timeline exported to 9:16 must really offer contain / cover / stretch,
and the difference must be measurable in the pixels — not just in a filter string."""

import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import Project, render_presets
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService
from agentcut.render import compile_render_plan

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SRC_W, SRC_H = 320, 180
OUT_W, OUT_H = 1080, 1920
SECONDS = 1.0
# A mid-grey field, a white square at the source centre, and a white strip at the very left edge:
# the square proves the aspect, the strip proves a crop actually happened.
SQUARE = (130, 190, 60, 120)
FILTER = (
    f"color=c=0x404040:s={SRC_W}x{SRC_H}:r=30:d={SECONDS},"
    "drawbox=x=130:y=60:w=60:h=60:color=white:t=fill,"
    "drawbox=x=0:y=0:w=3:h=180:color=white:t=fill"
)


def run(args, timeout=420):
    return subprocess.run(
        args, capture_output=True, check=True, timeout=timeout, creationflags=0x08000000
    )


def source(folder: Path) -> Path:
    target = folder / "framing.mp4"
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
            FILTER,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ]
    )
    return target


def project_payload(clip_source: Path) -> Project:
    from agentcut.contracts import VerifiedMedia
    from agentcut.timeline import validate_timeline

    verified = VerifiedMedia.model_validate(
        {
            "probe_id": "a",
            "path": str(clip_source),
            "kind": "video",
            "label": "framing",
            "size_bytes": clip_source.stat().st_size,
            "content_sha256": "0" * 64,
            "duration_ticks": int(SECONDS * T),
            "width": SRC_W,
            "height": SRC_H,
            "has_audio": False,
        }
    )
    project = Project.model_validate(
        {
            "id": "p",
            "name": "framing",
            "settings": {
                "width": SRC_W,
                "height": SRC_H,
                "frame_rate": {"numerator": 30, "denominator": 1},
            },
            "tracks": [{"id": "v", "kind": "video", "name": "v"}],
            "assets": {
                "a": {
                    "id": "a",
                    "kind": "video",
                    "label": "a",
                    "reference": "r",
                    "duration_ticks": int(SECONDS * T),
                    "verified": verified.model_dump(),
                }
            },
            "clips": {
                "c": {
                    "id": "c",
                    "asset_id": "a",
                    "track_id": "v",
                    "position_ticks": 0,
                    "duration_ticks": int(SECONDS * T),
                }
            },
        }
    )
    validate_timeline(project)
    return project


def stage_for(project: Project, fit: str) -> str:
    plan = compile_render_plan(project, "h264-1080x1920-vertical", fit=fit)
    return next(stage for stage in plan.filters if f"scale={OUT_W}:{OUT_H}" in stage)


def plan_suite(folder: Path) -> None:
    project = project_payload(source(folder))
    presets = {item["id"]: item for item in render_presets()}
    assert presets["h264-1080x1920-vertical"]["scale"] == [1080, 1920], presets
    assert presets["h264-1080-square"]["scale"] == [1080, 1080], presets
    assert len(presets) == 7, sorted(presets)

    contain = stage_for(project, "contain")
    cover = stage_for(project, "cover")
    stretch = stage_for(project, "stretch")
    assert "force_original_aspect_ratio=decrease" in contain and "pad=" in contain, contain
    assert "pad=" not in cover and "force_original_aspect_ratio=increase" in cover, cover
    assert f"crop={OUT_W}:{OUT_H}" in cover, cover
    assert "force_original_aspect_ratio" not in stretch and "pad=" not in stretch, stretch
    assert f"scale={OUT_W}:{OUT_H}:flags=bicubic" in stretch, stretch
    for stage in (contain, cover, stretch):
        assert "setsar=1" in stage and "format=yuv420p" in stage, stage
    print(
        "   stages: contain pads, cover scales-increase then crops, stretch scales bare — "
        "all three end at 1080x1920"
    )


def frame(path: Path) -> bytes:
    return run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        timeout=300,
    ).stdout


def geometry(path: Path) -> tuple[int, int]:
    out = run(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(path),
        ]
    ).stdout.decode()
    stream = json.loads(out)["streams"][0]
    return int(stream["width"]), int(stream["height"])


def white_bbox(raw: bytes, width: int, height: int, x_from: int = 0) -> tuple[int, int, int, int]:
    """Bounding box of near-white pixels, scanned without any image library."""
    low_x, low_y, high_x, high_y = width, height, -1, -1
    stride = width * 3
    for y in range(height):
        row = raw[y * stride : (y + 1) * stride]
        if max(row) <= 200:
            continue
        hits = [
            x
            for x in range(x_from, width)
            if row[x * 3] > 200 and row[x * 3 + 1] > 200 and row[x * 3 + 2] > 200
        ]
        if not hits:
            continue
        low_x, high_x = min(low_x, hits[0]), max(high_x, hits[-1])
        low_y, high_y = min(low_y, y), max(high_y, y)
    return low_x, low_y, high_x, high_y


def row_mean(raw: bytes, width: int, y: int) -> float:
    row = raw[y * width * 3 : (y + 1) * width * 3]
    return sum(row) / len(row)


def media_suite(folder: Path) -> None:
    clip = source(folder)
    project = project_payload(clip)
    outputs = {}
    for fit in ("contain", "cover", "stretch"):
        plan = compile_render_plan(project, "h264-1080x1920-vertical", fit=fit)
        job = folder / f"job-{fit}"
        job.mkdir(exist_ok=True)
        for name, body in plan.text_files.items():
            (job / name).write_text(body, encoding="utf-8")
        out = folder / f"{fit}.mp4"
        process = subprocess.run(
            plan.ffmpeg_argv(str(FFMPEG), str(out)),
            cwd=job,
            capture_output=True,
            timeout=600,
            creationflags=0x08000000,
        )
        assert process.returncode == 0, process.stderr.decode(errors="replace")[-800:]
        outputs[fit] = out
        assert geometry(out) == (OUT_W, OUT_H), (fit, geometry(out))

    frames = {fit: frame(path) for fit, path in outputs.items()}
    bars = {fit: row_mean(frames[fit], OUT_W, 6) for fit in frames}
    # Limited-range H.264 lifts "black" to about 16 and keeps 0x40 grey near 64, so the gate
    # separates those two plateaus rather than assuming 0.
    assert bars["contain"] < 30, bars
    assert bars["cover"] > 45 and bars["stretch"] > 45, bars

    aspects = {}
    for fit, raw in frames.items():
        # x_from=100 skips the source's left-edge strip (it lands at x<11 in the two
        # fits that keep it) without touching the square, which starts at x=219 under cover.
        low_x, low_y, high_x, high_y = white_bbox(raw, OUT_W, OUT_H, x_from=100)
        assert high_x > low_x and high_y > low_y, (fit, low_x, low_y, high_x, high_y)
        aspects[fit] = (high_x - low_x + 1) / (high_y - low_y + 1)
    assert abs(aspects["contain"] - 1.0) < 0.05, aspects
    assert abs(aspects["cover"] - 1.0) < 0.05, aspects
    assert 0.25 < aspects["stretch"] < 0.40, aspects
    print(
        "   the same 60x60 square lands as "
        + ", ".join(f"{fit} {value:.3f}:1" for fit, value in aspects.items())
        + " (aspect width/height); top row mean "
        + ", ".join(f"{fit} {bars[fit]:.1f}" for fit in bars)
    )

    edge = {fit: white_bbox(frames[fit], OUT_W, OUT_H, x_from=0)[0] for fit in frames}
    assert edge["contain"] < 40 and edge["stretch"] < 40, edge
    assert edge["cover"] > 150, edge
    print(
        "   the source's left edge strip is found at x="
        + ", ".join(f"{fit} {value}" for fit, value in edge.items())
        + " — cover really cropped it away"
    )


def http_suite(folder: Path) -> None:
    media = MediaService(folder / "fit-db.sqlite3", [folder], folder / "fit-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "fit-api.sqlite3", FFMPEG, folder / "exports", [folder / "exports", folder]
    )
    runtime.ensure_worker()
    token = "fitcheck" + "e" * 56
    app = create_app(folder / "fit-api.sqlite3", token, media=media, jobs=runtime)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        caps = client.get("/v1/capabilities").json()
        assert caps["features"]["output_fit_modes"] is True, caps["features"]
        ids = [item["id"] for item in caps["render_presets"]]
        assert "h264-1080x1920-vertical" in ids and "h264-1080-square" in ids, ids
        clip = source(folder)
        probe = client.post("/v1/media/import", json={"path": str(clip)}).json()
        created = client.post("/v1/projects", json={"request_id": "new", "name": "framing"}).json()[
            "project"
        ]
        path = f"/v1/projects/{created['id']}"
        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "seed",
                "expected_revision": 0,
                "commands": [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                    {
                        "op": "asset.import",
                        "asset_id": "a",
                        "label": "a",
                        "probe_id": probe["id"],
                        "verified": probe["verified"],
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "c",
                            "asset_id": "a",
                            "track_id": "v",
                            "position_ticks": 0,
                            "duration_ticks": int(SECONDS * T),
                        },
                    },
                ],
            },
        )
        assert seeded.status_code == 200, seeded.text

        preview = client.get(
            path + "/render-plan", params={"preset_id": "h264-1080x1920-vertical", "fit": "cover"}
        )
        assert preview.status_code == 200, preview.text
        argv = " ".join(preview.json()["argv_preview"])
        assert "force_original_aspect_ratio=increase" in argv, argv[-400:]
        assert "pad=" not in argv, argv[-400:]
        print("   the plan preview follows the requested fit, not a hardcoded default")

        job = client.post(
            path + "/renders",
            json={
                "request_id": "fit-cover",
                "expected_revision": 1,
                "preset_id": "h264-1080x1920-vertical",
                "filename": "竖屏裁切.mp4",
                "fit": "cover",
            },
        )
        assert job.status_code == 200, job.text
        assert job.json()["job"]["fit"] == "cover", job.json()["job"]
        status = {}
        for _ in range(600):
            status = client.get("/v1/jobs/" + job.json()["job"]["id"]).json()
            if status["job"]["status"] in {"succeeded", "failed", "cancelled"}:
                break
        assert status["job"]["status"] == "succeeded", status
        out = Path(status["job"]["output_path"])
        assert geometry(out) == (OUT_W, OUT_H), geometry(out)
        assert row_mean(frame(out), OUT_W, 6) > 45, (
            "a job must render with the fit it was asked for"
        )

        clash = client.post(
            path + "/renders",
            json={
                "request_id": "fit-cover",
                "expected_revision": 1,
                "preset_id": "h264-1080x1920-vertical",
                "filename": "竖屏裁切.mp4",
                "fit": "contain",
            },
        )
        assert clash.status_code == 409, clash.text
        assert "payload" in clash.json()["error"]["message"].lower(), clash.text
        bad = client.post(
            path + "/renders",
            json={
                "request_id": "fit-bad",
                "expected_revision": 1,
                "preset_id": "h264-1080x1920-vertical",
                "filename": "x.mp4",
                "fit": "smart",
            },
        )
        assert bad.status_code == 422, bad.text
        print("   one request_id cannot be reused for a different fit; an unknown fit is refused")


def main() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="agentcut-fit-") as scratch:
        folder = Path(scratch)
        plan_suite(folder)
        http_suite(folder)
        media_suite(folder)
    print(
        "PASS: contain bars, cover crops and stretch distorts, all three measured on exported "
        "1080x1920 pixels, and the job keeps the fit it was asked for"
    )


if __name__ == "__main__":
    main()
