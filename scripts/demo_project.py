"""Stand up a real engine with real media and one project that actually fills the workbench.

Why this exists: every screenshot this project has taken so far came from a *test fixture* —
clips with no media behind them, so every clip draws the same "未导入" placeholder and the asset
library is empty. Judging "does the layout look right" on that is judging the wrong picture.

This prints one JSON line: base_url, token, project_id, clip_id, media, folder. The engine keeps
running in the background until the caller kills it (the pid is printed too).

    python scripts/demo_project.py [folder]
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop" / "resources" / "bin" / "ffmpeg.exe"
FFPROBE = ROOT / "desktop" / "resources" / "bin" / "ffprobe.exe"
SECOND = 70_560_000
FRAME = SECOND // 30
TOKEN = "demo" + "d" * 55


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def make_media(folder: Path) -> dict[str, Path]:
    """Four files whose pictures are unmistakably different from each other."""
    made: dict[str, Path] = {}

    def run(name: str, args: list[str]) -> Path:
        target = folder / name
        done = subprocess.run(
            [str(FFMPEG), "-v", "error", "-y", "-nostdin", *args, str(target)],
            capture_output=True,
        )
        if done.returncode != 0:
            raise SystemExit(f"ffmpeg could not build {name}: {done.stderr[-200:]!r}")
        made[name] = target
        return target

    run("harbour.mp4", ["-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p"])
    run("train.mp4", ["-f", "lavfi", "-i", "smptebars=s=640x360:r=30:d=6",
                      "-c:v", "libx264", "-pix_fmt", "yuv420p"])
    run("still.png", ["-f", "lavfi", "-i", "color=c=0x2a2438:s=640x360:d=1", "-frames:v", "1"])
    run("theme.wav", ["-f", "lavfi", "-i", "sine=frequency=392:duration=14", "-ar", "48000"])
    return made


def call(base: str, path: str, body: dict | None = None, method: str | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        base + path,
        data=data,
        method=method or ("POST" if body is not None else "GET"),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as reply:
            return json.loads(reply.read().decode())
    except urllib.error.HTTPError as refused:
        raise SystemExit(f"{path} refused {refused.code}: {refused.read().decode()[:400]}")


def main() -> None:
    folder = (
        Path(sys.argv[1]) if len(sys.argv) > 1
        else Path(tempfile.mkdtemp(prefix="agentcut-demo-"))
    )
    media_dir = folder / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    media = make_media(media_dir)

    port = free_port()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    env["AGENTCUT_TOKEN"] = TOKEN
    engine = subprocess.Popen(
        [sys.executable, "-m", "agentcut", "api", "--port", str(port), "--json",
         "--data-dir", str(folder / "engine"), "--cache-dir", str(folder / "cache"),
         "--output-dir", str(folder / "out"), "--media-root", str(media_dir),
         "--ffmpeg", str(FFMPEG), "--ffprobe", str(FFPROBE)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", env=env, cwd=str(ROOT),
    )
    ready = None
    deadline = time.time() + 120
    while time.time() < deadline and ready is None:
        line = engine.stdout.readline() if engine.stdout else ""
        if line.strip().startswith("{"):
            ready = json.loads(line)
        elif not line and engine.poll() is not None:
            raise SystemExit(f"engine died: {line!r}")
    if ready is None:
        raise SystemExit("engine never printed its ready line")
    base = ready["base_url"]

    probes = {}
    for name, path in media.items():
        probes[name] = call(base, "/v1/media/import", {"path": str(path)})["verified"]

    made = call(base, "/v1/projects", {
        "request_id": "demo-new", "name": "日系校园 · 30s 广告",
        "settings": {"width": 640, "height": 360,
                     "frame_rate": {"numerator": 30, "denominator": 1}},
    })
    project = made["project"]
    pid = project["id"]
    commands = [
        {"op": "track.add", "track": {"id": "v1", "kind": "video", "name": "视频 1"}},
        {"op": "track.add", "track": {"id": "v2", "kind": "video", "name": "画中画"}},
        {"op": "track.add", "track": {"id": "a1", "kind": "audio", "name": "背景音乐"}},
        {"op": "track.add", "track": {"id": "c1", "kind": "video", "name": "字幕"}},
        {"op": "asset.import", "asset_id": "harbour", "label": "harbour.mp4",
         "probe_id": probes["harbour.mp4"]["probe_id"], "verified": probes["harbour.mp4"]},
        {"op": "asset.import", "asset_id": "train", "label": "train.mp4",
         "probe_id": probes["train.mp4"]["probe_id"], "verified": probes["train.mp4"]},
        {"op": "asset.import", "asset_id": "still", "label": "still.png",
         "probe_id": probes["still.png"]["probe_id"], "verified": probes["still.png"]},
        {"op": "asset.import", "asset_id": "theme", "label": "theme.wav",
         "probe_id": probes["theme.wav"]["probe_id"], "verified": probes["theme.wav"]},
        {"op": "asset.register", "asset": {"id": "title", "kind": "text", "label": "字幕",
                                          "reference": "generated:text"}},
        {"op": "clip.add", "clip": {"id": "k1", "asset_id": "harbour", "track_id": "v1",
                                    "position_ticks": 0, "duration_ticks": 3 * SECOND}},
        {"op": "clip.add", "clip": {"id": "k2", "asset_id": "train", "track_id": "v1",
                                    "position_ticks": 3 * SECOND,
                                    "duration_ticks": 3 * SECOND}},
        {"op": "clip.add", "clip": {"id": "k3", "asset_id": "still", "track_id": "v1",
                                    "position_ticks": 6 * SECOND,
                                    "duration_ticks": 2 * SECOND}},
        # 密起来才看得出排版：一条满轨 + 一条画中画 + 一条配乐 + 四条字幕。
        {"op": "clip.add", "clip": {"id": "k6", "asset_id": "train", "track_id": "v1",
                                    "position_ticks": 8 * SECOND, "duration_ticks": 3 * SECOND}},
        {"op": "clip.add", "clip": {"id": "k7", "asset_id": "harbour", "track_id": "v1",
                                    "position_ticks": 11 * SECOND, "duration_ticks": 3 * SECOND}},
        {"op": "clip.add", "clip": {"id": "k8", "asset_id": "still", "track_id": "v2",
                                    "position_ticks": 5 * SECOND, "duration_ticks": 3 * SECOND,
                                    "effects": {"scale": 0.28, "x": -0.3, "y": 0.3}}},
        {"op": "clip.add", "clip": {"id": "t4", "asset_id": "title", "track_id": "c1",
                                    "position_ticks": 9 * SECOND, "duration_ticks": 2 * SECOND,
                                    "text": {"body": "开往春天的列车"}}},
        {"op": "clip.add", "clip": {"id": "k4", "asset_id": "harbour", "track_id": "v2",
                                    "position_ticks": SECOND + FRAME * 15,
                                    "duration_ticks": 2 * SECOND,
                                    "effects": {"scale": 0.32, "x": 0.26, "y": 0.22}}},
        {"op": "clip.add", "clip": {"id": "k5", "asset_id": "theme", "track_id": "a1",
                                    "position_ticks": 0, "duration_ticks": 14 * SECOND,
                                    "effects": {"gain": 0.7}}},
        {"op": "clip.add", "clip": {"id": "t1", "asset_id": "title", "track_id": "c1",
                                    "position_ticks": SECOND, "duration_ticks": 2 * SECOND,
                                    "text": {"body": "春天的第一口轻轨"}}},
        {"op": "clip.add", "clip": {"id": "t2", "asset_id": "title", "track_id": "c1",
                                    "position_ticks": 4 * SECOND,
                                    "duration_ticks": 2 * SECOND + FRAME * 12,
                                    "text": {"body": "遇见更好的自己"}}},
        {"op": "clip.add", "clip": {"id": "t3", "asset_id": "title", "track_id": "c1",
                                    "position_ticks": 7 * SECOND, "duration_ticks": SECOND,
                                    "text": {"body": "下一站，见"}}},
    ]
    edited = call(base, f"/v1/projects/{pid}/edits", {
        "request_id": "demo-seed", "expected_revision": project["revision"], "commands": commands,
    })
    print(json.dumps({
        "base_url": base, "token": TOKEN, "project_id": pid,
        "clip_id": "k2", "revision": edited["project"]["revision"],
        "media": str(media_dir), "folder": str(folder), "pid": engine.pid,
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
