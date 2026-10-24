"""1.282：按镜头切分——颜色变化找硬切，计划是普通 clip.split，一个批次一个版本。

这一档钉四件事，每件都有「另一头会给出不同答案」的反证：
* 纯红 `#ff0000` 到纯绿 `#008000` 的切点：FFmpeg 的 luma-only `scene` 分在这台机器的 6.1.1 上
  量到 **0.0**（`scdet` 只报了 4.0 秒那个绿→蓝的切点），这一版的颜色检测量到 **0.50** 并切在 2 秒；
* 只读计划不写库；一次 `apply` 只涨一个 revision，切出来的三段首尾相接、覆盖整段；
* 恒定 50% 速度把源里的 2.0 秒折到时间线的 4.0 秒（速度只折一次）；
* 没有硬切、不是视频片段各自按名字拒绝，且一个字节都不写。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut.contracts import APP_VERSION, SCENE_MAX_CUTS  # noqa: E402
from agentcut.contracts import TIMEBASE as T  # noqa: E402
from agentcut.http_api import create_app  # noqa: E402
from agentcut.jobs import JobRuntime  # noqa: E402
from agentcut.media import MediaService  # noqa: E402

FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SECOND = T


def run(args, timeout=300):
    done = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=0x08000000)
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-600:]
    return done.stdout


def three_shots(folder: Path) -> Path:
    """2 s red, 2 s green, 2 s blue — red and green have (almost) the same luma on purpose."""
    target = folder / "shots.mp4"
    run([
        str(FFMPEG), "-v", "error", "-y", "-nostdin",
        "-f", "lavfi", "-i", "color=c=#ff0000:s=320x180:r=30:d=2",
        "-f", "lavfi", "-i", "color=c=#008000:s=320x180:r=30:d=2",
        "-f", "lavfi", "-i", "color=c=#0000ff:s=320x180:r=30:d=2",
        "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
        "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target),
    ])
    return target


def solid(folder: Path) -> Path:
    target = folder / "solid.mp4"
    run([
        str(FFMPEG), "-v", "error", "-y", "-nostdin",
        "-f", "lavfi", "-i", "color=c=0x334455:s=320x180:r=30:d=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target),
    ])
    return target


def still(folder: Path) -> Path:
    target = folder / "still.png"
    run([
        str(FFMPEG), "-v", "error", "-y", "-nostdin",
        "-f", "lavfi", "-i", "color=c=0x884422:s=320x180", "-frames:v", "1", str(target),
    ])
    return target


def tone(folder: Path) -> Path:
    target = folder / "a.wav"
    run([
        str(FFMPEG), "-v", "error", "-y", "-nostdin",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3", str(target),
    ])
    return target


def client_for(folder: Path):
    media = MediaService(folder / "sc-db.sqlite3", [folder], folder / "sc-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "sc-api.sqlite3", FFMPEG, folder / "deliverables", [folder / "deliverables"]
    )
    token = "scenecheck" + "c" * 53
    app = create_app(folder / "sc-api.sqlite3", token, media=media, jobs=runtime)
    return app, token


def seed(
    client: TestClient, source: Path, *, duration: int, track_kind="video", speed=100
) -> tuple[str, str]:
    # Every seeded project is its own fixture, so the ids must differ or the second seed replays
    # the first one's receipt (IDEMPOTENCY_CONFLICT on a different payload).
    tag = f"{source.stem}-{duration}-{track_kind}-{speed}"
    probe = client.post("/v1/media/import", json={"path": str(source)}).json()["verified"]
    made = client.post(
        "/v1/projects",
        json={
            "request_id": f"sc-new-{tag}",
            "name": f"分镜 {tag}",
            "settings": {"width": 320, "height": 180},
        },
    )
    assert made.status_code == 200, (made.status_code, made.text[:900])
    made = made.json()["project"]
    pid = made["id"]
    track = {"id": "t", "kind": track_kind, "name": "轨"}
    clip = {
        "id": "c", "asset_id": "s", "track_id": "t",
        "position_ticks": 0, "duration_ticks": duration,
    }
    if speed != 100:
        clip["speed_percent"] = speed
    commands = [
        {"op": "track.add", "track": track},
        {
            "op": "asset.import", "asset_id": "s", "label": "s",
            "probe_id": probe["probe_id"], "verified": probe,
        },
        {"op": "clip.add", "clip": clip},
    ]
    done = client.post(
        f"/v1/projects/{pid}/edits",
        json={"request_id": f"sc-seed-{tag}", "expected_revision": 0, "commands": commands},
    )
    assert done.status_code == 200, done.text
    return pid, done.json()["project"]["revision"]


def scan(client: TestClient, pid: str, revision: int, request: str, **body):
    payload = {"request_id": request, "expected_revision": revision, **body}
    return client.post(f"/v1/projects/{pid}/clips/c/scenes", json=payload)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-scenes-") as raw:
        folder = Path(raw)
        shots, solid_source, still_source, tone_source = (
            three_shots(folder), solid(folder), still(folder), tone(folder)
        )
        app, token = client_for(folder)
        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["scene_split"] is True, caps["features"]
            assert caps["limits"]["scene_max_cuts"] == SCENE_MAX_CUTS, caps["limits"]
            assert 0 < caps["limits"]["scene_threshold_default"] < 1, caps["limits"]

            pid, revision = seed(client, shots, duration=6 * SECOND)

            # ① 只读计划：两个切点（红→绿 2.0 s、绿→蓝 4.0 s），不写库。
            planned = scan(client, pid, revision, "sc-plan")
            assert planned.status_code == 200, planned.text
            body = planned.json()
            assert body["committed"] is False, body
            cuts = body["scenes"]["cuts"]
            assert len(cuts) == 2, cuts
            seconds = [round(cut["at_ticks"] / SECOND, 3) for cut in cuts]
            assert abs(seconds[0] - 2.0) <= 0.1, seconds
            assert abs(seconds[1] - 4.0) <= 0.1, seconds
            assert len(body["scenes"]["commands"]) == 2, body["scenes"]["commands"]
            assert client.get(f"/v1/projects/{pid}").json()["revision"] == revision
            print(f"   只读计划：{len(cuts)} 个切点 {seconds}"
                  "（纯红→纯绿那个点 scene 分是 0.0，颜色差是 0.50）")

            # ② 一次 apply：一个 revision、三段、首尾相接覆盖整段。
            applied = scan(
                client, pid, revision, "sc-apply", apply=True,
            )
            assert applied.status_code == 200, applied.text
            project = applied.json()["project"]
            assert project["revision"] == revision + 1, (project["revision"], revision)
            clips = sorted(project["clips"].values(), key=lambda row: row["position_ticks"])
            assert len(clips) == 3, [
                (c["id"], c["position_ticks"], c["duration_ticks"]) for c in clips
            ]
            assert clips[0]["position_ticks"] == 0
            for left, right in zip(clips, clips[1:]):
                assert (
                    left["position_ticks"] + left["duration_ticks"] == right["position_ticks"]
                ), (left, right)
            assert clips[-1]["position_ticks"] + clips[-1]["duration_ticks"] == 6 * SECOND
            print(f"   apply：r{revision} → r{project['revision']}，{len(clips)} 段首尾相接")

            # ③ 恒定 50% 速度：源里的 2.0 s 折到时间线的 4.0 s（只折一次）。
            slow_pid, slow_revision = seed(client, shots, duration=12 * SECOND, speed=50)
            slow = scan(client, slow_pid, slow_revision, "sc-slow")
            assert slow.status_code == 200, slow.text
            slow_cuts = slow.json()["scenes"]["cuts"]
            assert slow_cuts and abs(slow_cuts[0]["at_ticks"] / SECOND - 4.0) <= 0.2, slow_cuts
            assert slow.json()["scenes"]["speed_percent"] == 50, slow.json()["scenes"]

            # ④ 没有硬切：只读回空计划，apply 按名字拒绝。
            quiet_pid, quiet_revision = seed(client, solid_source, duration=3 * SECOND)
            quiet = scan(client, quiet_pid, quiet_revision, "sc-quiet")
            assert quiet.status_code == 200 and quiet.json()["scenes"]["cuts"] == [], quiet.text
            refused = scan(client, quiet_pid, quiet_revision, "sc-quiet-apply", apply=True)
            assert refused.status_code == 422, refused.text
            assert refused.json()["error"]["code"] == "SCENE_NONE", refused.json()
            assert client.get(f"/v1/projects/{quiet_pid}").json()["revision"] == quiet_revision

            # ⑤ 不是视频片段：图片与声音各自拒绝，不写版本。
            for source, kind, name, slug in (
                (still_source, "video", "图片", "still"),
                (tone_source, "audio", "声音", "tone"),
            ):
                bad_pid, bad_revision = seed(client, source, duration=2 * SECOND, track_kind=kind)
                bad = scan(client, bad_pid, bad_revision, f"sc-bad-{slug}", apply=True)
                assert bad.status_code == 422, (name, bad.text)
                assert bad.json()["error"]["code"] == "INVALID_SCENE_TARGET", bad.json()
                assert client.get(f"/v1/projects/{bad_pid}").json()["revision"] == bad_revision

            # ⑥ 门槛越界由契约拒绝。
            out = client.post(
                f"/v1/projects/{pid}/clips/c/scenes",
                json={
                    "request_id": "sc-range",
                    "expected_revision": project["revision"],
                    "threshold": 1.5,
                },
            )
            assert out.status_code == 422, out.text

    print(
        f"PASS: 按镜头切分（{APP_VERSION}）——颜色变化找到 2.0/4.0 s 两个硬切"
        "（FFmpeg luma-only scene 分对红→绿是 0.0）、只读不写、apply 一个版本三段相接、"
        "50% 速度折到 4.0 s、无切点与错类型各按名字拒绝"
    )


if __name__ == "__main__":
    main()
