"""A real 4K multi-track export: three picture layers, one audio bed, and a budget.

The source is a 3840x2160 test pattern with sound; two small solid-colour clips are scaled and
placed over it, so the delivered frame itself proves the three layers composited (green and blue
at known picture fractions). The render plan and the preview manifest are measured for size, and
the export is given a wall-clock ceiling. Everything runs through the shipped engine over HTTP,
the same path a person and an Agent use.
"""

import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
ENGINE = ROOT / "desktop/resources/bin/agentcut/agentcut.exe"
T = 70_560_000
FPS = 30
SECONDS = 8
WIDTH, HEIGHT = 3840, 2160
# Measured on this machine at 54.4 s; the ceiling leaves room for a loaded suite but still fails a
# regression that doubles the export.
RENDER_BUDGET_S = 240.0
PLAN_BUDGET_BYTES = 64 * 1024
MANIFEST_BUDGET_BYTES = 64 * 1024


def call(method: str, url: str, token: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=600) as answer:
        return json.loads(answer.read().decode("utf-8"))


def build(folder: Path) -> tuple[Path, Path, Path]:
    base = folder / "base4k.mp4"
    if not base.is_file():
        subprocess.run(
            [
                str(FFMPEG), "-y", "-v", "error",
                "-f", "lavfi", "-i", f"testsrc2=s={WIDTH}x{HEIGHT}:r={FPS}:d={SECONDS}",
                "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={SECONDS}",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k", "-shortest", str(base),
            ],
            check=True,
            timeout=600,
        )
    green = folder / "green.mp4"
    blue = folder / "blue.mp4"
    for target, colour in ((green, "0x00FF00"), (blue, "0x0000FF")):
        if not target.is_file():
            subprocess.run(
                [
                    str(FFMPEG), "-y", "-v", "error",
                    "-f", "lavfi", "-i", f"color=c={colour}:s=960x540:d={SECONDS}:r={FPS}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-pix_fmt", "yuv420p",
                    str(target),
                ],
                check=True,
                timeout=300,
            )
    return base, green, blue


def probe(path: Path) -> dict:
    done = subprocess.run(
        [
            str(FFPROBE), "-v", "error",
            "-show_entries",
            "format=duration,size:stream=codec_type,codec_name,width,height,avg_frame_rate,"
            "sample_rate,channels",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(done.stdout)


def sample(path: Path, seconds: float, spots: dict[str, tuple[float, float]]) -> dict[str, tuple]:
    raw = subprocess.run(
        [
            str(FFMPEG), "-v", "error", "-ss", f"{seconds:.3f}", "-i", str(path),
            "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
        ],
        check=True,
        capture_output=True,
        timeout=120,
    ).stdout
    stride = WIDTH * 3
    found = {}
    for name, (fx, fy) in spots.items():
        x, y = int(fx * WIDTH), int(fy * HEIGHT)
        offset = y * stride + x * 3
        found[name] = tuple(raw[offset : offset + 3])
    return found


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    with tempfile.TemporaryDirectory(prefix="fourk-check-") as name:
        folder = Path(name)
        media = folder / "media"
        media.mkdir()
        base, green, blue = build(media)
        data = folder / "data"
        data.mkdir()
        out = folder / "out"
        token_file = data / "agentcut.token"
        child = subprocess.Popen(
            [
                str(ENGINE), "desktop", "--port", "0", "--data-dir", str(data),
                "--token-file", str(token_file), "--ffmpeg", str(FFMPEG),
                "--ffprobe", str(FFPROBE), "--media-root", str(media), "--output-dir", str(out),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )
        try:
            assert child.stdout is not None
            ready = None
            deadline = time.time() + 60
            while time.time() < deadline and ready is None:
                line = child.stdout.readline()
                if line.strip().startswith("{"):
                    ready = json.loads(line)
            assert ready, "engine did not report ready"
            base_url = ready["base_url"]
            token = token_file.read_text(encoding="utf-8").strip()
            project = call(
                "POST", base_url + "/v1/projects", token,
                {
                    "request_id": "4k-create", "name": "4K three layers",
                    "settings": {
                        "width": WIDTH, "height": HEIGHT,
                        "frame_rate": {"numerator": FPS, "denominator": 1},
                        "sample_rate": 48000,
                    },
                },
            )["project"]
            pid = project["id"]
            probes = {}
            for key, path in (("base", base), ("green", green), ("blue", blue)):
                probes[key] = call(
                    "POST", base_url + "/v1/media/import", token, {"path": str(path)}
                )
            commands = [
                {"op": "track.add", "track": {"id": "v1", "kind": "video", "name": "base"}},
                {"op": "track.add", "track": {"id": "v2", "kind": "video", "name": "pip"}},
                {"op": "track.add", "track": {"id": "v3", "kind": "video", "name": "third"}},
                {"op": "track.add", "track": {"id": "a1", "kind": "audio", "name": "bed"}},
            ]
            commands += [
                {
                    "op": "asset.import",
                    "asset_id": key,
                    "label": key,
                    "probe_id": probe["id"],
                    "verified": probe["verified"],
                }
                for key, probe in probes.items()
            ]
            commands += [
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "base", "asset_id": "base", "track_id": "v1",
                        "position_ticks": 0, "duration_ticks": SECONDS * T,
                        "speed_percent": 100,
                    },
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "pip", "asset_id": "green", "track_id": "v2",
                        "position_ticks": T, "duration_ticks": 4 * T,
                        "speed_percent": 100,
                        "effects": {"x": 0.2, "y": -0.2, "scale": 0.45, "opacity": 1.0},
                    },
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "third", "asset_id": "blue", "track_id": "v3",
                        "position_ticks": 2 * T, "duration_ticks": 4 * T,
                        "speed_percent": 100,
                        "effects": {"x": -0.25, "y": 0.2, "scale": 0.35, "opacity": 1.0},
                    },
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "bed", "asset_id": "base", "track_id": "a1",
                        "position_ticks": 0, "duration_ticks": SECONDS * T,
                        "speed_percent": 100,
                    },
                },
            ]
            seeded = call(
                "POST", f"{base_url}/v1/projects/{pid}/edits", token,
                {"request_id": "4k-seed", "expected_revision": 0, "commands": commands},
            )
            revision = seeded["project"]["revision"]
            plan = call(
                "GET",
                f"{base_url}/v1/projects/{pid}/render-plan?preset_id=h264-2160p&fit=cover",
                token,
            )
            manifest = call(
                "GET",
                f"{base_url}/v1/projects/{pid}/preview-manifest?revision={revision}",
                token,
            )
            plan_bytes = len(json.dumps(plan))
            manifest_bytes = len(json.dumps(manifest))
            assert plan_bytes < PLAN_BUDGET_BYTES, plan_bytes
            assert manifest_bytes < MANIFEST_BUDGET_BYTES, manifest_bytes
            assert len(manifest.get("clips", {})) == 4, manifest.get("clips", {}).keys()

            started = time.perf_counter()
            job = call(
                "POST", f"{base_url}/v1/projects/{pid}/renders", token,
                {
                    "request_id": "4k-render", "expected_revision": revision,
                    "preset_id": "h264-2160p", "filename": "4k-three-layers.mp4",
                    "fit": "cover",
                },
            )
            job_id = job["job"]["id"]
            state = {}
            for _ in range(300):
                state = call("GET", f"{base_url}/v1/jobs/{job_id}", token)["job"]
                if state["status"] in ("succeeded", "failed"):
                    break
                time.sleep(2)
            elapsed = time.perf_counter() - started
            assert state["status"] == "succeeded", state
            assert state.get("output_checked") is True, state
            assert elapsed < RENDER_BUDGET_S, f"4K export took {elapsed:.1f}s"
            output = Path(state["output_path"])
            info = probe(output)
            streams = {row["codec_type"]: row for row in info["streams"]}
            assert streams["video"]["width"] == WIDTH and streams["video"]["height"] == HEIGHT, info
            assert streams["video"]["avg_frame_rate"] == "30/1", info
            assert streams["audio"]["sample_rate"] == "48000", info
            assert float(info["format"]["duration"]) == SECONDS, info
            spots = sample(
                output, 3.0,
                {"pip": (0.70, 0.30), "third": (0.25, 0.70), "base": (0.05, 0.05)},
            )
            assert spots["pip"][1] > spots["pip"][0] + 40, spots
            assert spots["pip"][1] > spots["pip"][2] + 40, spots
            assert spots["third"][2] > spots["third"][0] + 40, spots
            assert spots["third"][2] > spots["third"][1] + 40, spots
            print(
                f"   4K export {elapsed:.1f}s, {info['format']['size']} B, "
                f"plan {plan_bytes} B, manifest {manifest_bytes} B, "
                f"pip {spots['pip']}, third {spots['third']}"
            )
        finally:
            child.terminate()
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.kill()
    print(
        "PASS: a 4K project with three picture layers exports inside the budget, the delivered "
        "frame shows green and blue where they were placed, and the plan/manifest stay small"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
