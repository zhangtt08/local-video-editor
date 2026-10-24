"""1.283：按镜头粗剪——每个镜头只留前 N 秒，留下的头接在一起，一批普通命令一个版本。

这一档钉四件事，每件都有「另一头会给出不同答案」的反证：
* 6 秒三段（红/绿/蓝）只留 1 秒：三个切点折成三段 1 秒、首尾相接、总长 3 秒；
* 没有硬切的一段（3 秒纯色）只留 1 秒：一条 `clip.trim` 就把头留下，不凭空切一刀；
* 每镜留得比镜头还长（2 秒）时计划里只有切点，画面一字不动；
* 50% 速度把源里的切点折到时间线的 4/8 秒，收尾那段读的源仍是 2/4 秒；
* 图片与声音各自按名字拒绝，镜头都比留长时 apply 回 `ROUGH_NONE`，两者都不写半个版本。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut.contracts import (  # noqa: E402
    APP_VERSION,
    ROUGH_KEEP_MS_DEFAULT,
    ROUGH_KEEP_MS_MAX,
    ROUGH_KEEP_MS_MIN,
)
from agentcut.http_api import create_app  # noqa: E402
from agentcut.jobs import JobRuntime  # noqa: E402
from agentcut.media import MediaService  # noqa: E402

FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SECOND = 70_560_000


def run(args, timeout=300):
    done = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=0x08000000)
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-600:]
    return done.stdout


def three_shots(folder: Path) -> Path:
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
    media = MediaService(folder / "rc-db.sqlite3", [folder], folder / "rc-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "rc-api.sqlite3", FFMPEG, folder / "deliverables", [folder / "deliverables"]
    )
    token = "roughcheck" + "c" * 54
    app = create_app(folder / "rc-api.sqlite3", token, media=media, jobs=runtime)
    return app, token


SEEDS = {"n": 0}


def seed(
    client: TestClient, source: Path, *, duration: int, track_kind="video", speed=100
) -> tuple[str, str]:
    SEEDS["n"] += 1
    tag = f"{source.stem}-{duration}-{track_kind}-{speed}-{SEEDS['n']}"
    probe = client.post("/v1/media/import", json={"path": str(source)}).json()["verified"]
    made = client.post(
        "/v1/projects",
        json={
            "request_id": f"rc-new-{tag}",
            "name": f"粗剪 {tag}",
            "settings": {"width": 320, "height": 180},
        },
    )
    assert made.status_code == 200, (made.status_code, made.text[:900])
    project = made.json()["project"]
    pid = project["id"]
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
        json={"request_id": f"rc-seed-{tag}", "expected_revision": 0, "commands": commands},
    )
    assert done.status_code == 200, done.text
    return pid, done.json()["project"]["revision"]


def seed_track(client: TestClient, source: Path, still_source: Path) -> tuple[str, str]:
    """Two 3 s video clips (0 s and 5 s) plus one still on the same track."""
    SEEDS["n"] += 1
    tag = f"track-{SEEDS['n']}"
    video = client.post("/v1/media/import", json={"path": str(source)}).json()["verified"]
    still = client.post("/v1/media/import", json={"path": str(still_source)}).json()["verified"]
    made = client.post(
        "/v1/projects",
        json={
            "request_id": f"rc-track-new-{tag}",
            "name": f"整轨粗剪 {tag}",
            "settings": {"width": 320, "height": 180},
        },
    )
    assert made.status_code == 200, (made.status_code, made.text[:900])
    project = made.json()["project"]
    pid = project["id"]
    commands = [
        {"op": "track.add", "track": {"id": "t", "kind": "video", "name": "画面"}},
        {
            "op": "asset.import", "asset_id": "v", "label": "v",
            "probe_id": video["probe_id"], "verified": video,
        },
        {
            "op": "asset.import", "asset_id": "i", "label": "i",
            "probe_id": still["probe_id"], "verified": still,
        },
        {
            "op": "clip.add",
            "clip": {"id": "a", "asset_id": "v", "track_id": "t",
                     "position_ticks": 0, "duration_ticks": 3 * SECOND},
        },
        {
            "op": "clip.add",
            "clip": {"id": "b", "asset_id": "v", "track_id": "t",
                     "position_ticks": 5 * SECOND, "duration_ticks": 3 * SECOND},
        },
        {
            "op": "clip.add",
            "clip": {"id": "s", "asset_id": "i", "track_id": "t",
                     "position_ticks": 9 * SECOND, "duration_ticks": 2 * SECOND},
        },
    ]
    done = client.post(
        f"/v1/projects/{pid}/edits",
        json={"request_id": f"rc-track-seed-{tag}", "expected_revision": 0, "commands": commands},
    )
    assert done.status_code == 200, done.text
    return pid, done.json()["project"]["revision"]


def cut(client: TestClient, pid: str, revision: int, request: str, **body):
    payload = {"request_id": request, "expected_revision": revision, **body}
    return client.post(f"/v1/projects/{pid}/clips/c/rough-cut", json=payload)


def clips_of(project) -> list:
    return sorted(project["clips"].values(), key=lambda row: row["position_ticks"])


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-rough-") as raw:
        folder = Path(raw)
        shots, solid_source, still_source, tone_source = (
            three_shots(folder), solid(folder), still(folder), tone(folder)
        )
        app, token = client_for(folder)
        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["rough_cut"] is True, caps["features"]
            assert caps["limits"]["rough_keep_ms_default"] == ROUGH_KEEP_MS_DEFAULT, caps["limits"]
            assert caps["limits"]["rough_keep_ms_min"] == ROUGH_KEEP_MS_MIN, caps["limits"]
            assert caps["limits"]["rough_keep_ms_max"] == ROUGH_KEEP_MS_MAX, caps["limits"]

            # ① 三段各留 1 秒：一个 revision、三段、首尾相接、总长 3 秒。
            pid, revision = seed(client, shots, duration=6 * SECOND)
            planned = cut(client, pid, revision, "rc-plan", keep_ms=1000)
            assert planned.status_code == 200, planned.text
            body = planned.json()
            assert body["committed"] is False, body
            assert len(body["rough"]["cuts"]) == 2, body["rough"]["cuts"]
            assert body["rough"]["keep_ticks"] == SECOND, body["rough"]["keep_ticks"]
            assert client.get(f"/v1/projects/{pid}").json()["revision"] == revision
            applied = cut(client, pid, revision, "rc-apply", keep_ms=1000, apply=True)
            assert applied.status_code == 200, applied.text
            project = applied.json()["project"]
            assert project["revision"] == revision + 1, (project["revision"], revision)
            clips = clips_of(project)
            assert len(clips) == 3, [
                (c["id"], c["position_ticks"], c["duration_ticks"]) for c in clips
            ]
            assert clips[0]["position_ticks"] == 0, clips
            for left, right in zip(clips, clips[1:]):
                assert (
                    left["position_ticks"] + left["duration_ticks"] == right["position_ticks"]
                ), clips
            assert [c["duration_ticks"] for c in clips] == [SECOND] * 3, clips
            print(f"   r{revision} → r{project['revision']}：三段各留 1 秒，总长 3 秒、首尾相接")

            # ② 一段 3 秒的纯色只留 1 秒：一条 trim，不凭空加切点。
            one_pid, one_revision = seed(client, solid_source, duration=3 * SECOND)
            one = cut(client, one_pid, one_revision, "rc-one", keep_ms=1000, apply=True)
            assert one.status_code == 200, one.text
            one_clips = clips_of(one.json()["project"])
            assert len(one_clips) == 1, one_clips
            assert one_clips[0]["duration_ticks"] == SECOND, one_clips
            print("   一镜到底：只留头 1 秒，没有多余的刀")

            # ③ 每镜留 2 秒（等于镜头长度）：计划里只有切点，三段仍是 2 秒。
            keep_pid, keep_revision = seed(client, shots, duration=6 * SECOND)
            kept = cut(client, keep_pid, keep_revision, "rc-keep", keep_ms=2000, apply=True)
            assert kept.status_code == 200, kept.text
            kept_clips = clips_of(kept.json()["project"])
            assert [c["duration_ticks"] for c in kept_clips] == [2 * SECOND] * 3, (
                kept_clips
            )
            print("   每镜留 2 秒：与镜头同长，三段一字不动")

            # ④ 50% 速度：切点在时间线 4/8 秒，收尾那两段读的源仍是 2/4 秒。
            slow_pid, slow_revision = seed(client, shots, duration=12 * SECOND, speed=50)
            slow = cut(client, slow_pid, slow_revision, "rc-slow", keep_ms=1000, apply=True)
            assert slow.status_code == 200, slow.text
            slow_clips = clips_of(slow.json()["project"])
            assert len(slow_clips) == 3, slow_clips
            assert [c["position_ticks"] for c in slow_clips] == [0, SECOND, 2 * SECOND], slow_clips
            assert [c["source_in_ticks"] for c in slow_clips] == [
                0, 2 * SECOND, 4 * SECOND
            ], slow_clips
            print(
                "   50% 速度：切点折到 4/8 秒，留下的头读源 "
                f"{[round(c['source_in_ticks'] / SECOND, 2) for c in slow_clips]} 秒"
            )

            # ⑤ 图片与声音按名字拒绝，不写版本。
            for source, kind, slug in (
                (still_source, "video", "still"),
                (tone_source, "audio", "tone"),
            ):
                bad_pid, bad_revision = seed(
                    client, source, duration=2 * SECOND, track_kind=kind
                )
                bad = cut(client, bad_pid, bad_revision, f"rc-bad-{slug}", keep_ms=500, apply=True)
                assert bad.status_code == 422, (kind, bad.text)
                assert bad.json()["error"]["code"] == "INVALID_ROUGH_TARGET", bad.json()
                assert client.get(f"/v1/projects/{bad_pid}").json()["revision"] == bad_revision

            # ⑥ 每镜留得比唯一的镜头还长：没有可切的，apply 按名字拒绝。
            short_pid, short_revision = seed(client, solid_source, duration=3 * SECOND)
            none = cut(client, short_pid, short_revision, "rc-none", keep_ms=3000, apply=True)
            assert none.status_code == 422, none.text
            assert none.json()["error"]["code"] == "ROUGH_NONE", none.json()
            assert client.get(f"/v1/projects/{short_pid}").json()["revision"] == short_revision

            # ⑦ 带越界的「每镜留」由契约拒绝。
            out = client.post(
                f"/v1/projects/{pid}/clips/c/rough-cut",
                json={
                    "request_id": "rc-range",
                    "expected_revision": project["revision"],
                    "keep_ms": ROUGH_KEEP_MS_MAX + 1,
                },
            )
            assert out.status_code == 422, out.text

            # ⑧ 整轨：两段画面从右往左各取一份计划；图片那一段带原因跳过，一个版本写完整条轨。
            track_pid, track_revision = seed_track(client, solid_source, still_source)
            plan = client.post(
                f"/v1/projects/{track_pid}/tracks/t/rough-cut",
                json={"request_id": "rc-track-plan", "expected_revision": track_revision,
                      "keep_ms": 1000},
            )
            assert plan.status_code == 200, plan.text
            report = plan.json()
            assert report["committed"] is False, report
            skipped = [item for item in report["rough"]["clips"] if item.get("skipped")]
            assert [item["clip_id"] for item in skipped] == ["s"], report["rough"]["clips"]
            assert len(report["rough"]["commands"]) > 0, report["rough"]
            assert client.get(f"/v1/projects/{track_pid}").json()["revision"] == track_revision
            done = client.post(
                f"/v1/projects/{track_pid}/tracks/t/rough-cut",
                json={"request_id": "rc-track-apply", "expected_revision": track_revision,
                      "keep_ms": 1000, "apply": True},
            )
            assert done.status_code == 200, done.text
            track_project = done.json()["project"]
            assert track_project["revision"] == track_revision + 1, track_project["revision"]
            moved = {clip["id"]: clip for clip in track_project["clips"].values()}
            assert set(moved) == {"a", "b", "s"}, moved
            assert moved["a"]["position_ticks"] == 0, moved["a"]
            assert moved["a"]["duration_ticks"] == SECOND, moved["a"]
            assert moved["b"]["duration_ticks"] == SECOND, moved["b"]
            # b 先收尾（5..6，图片随之 9→7），a 收尾再把 b 3..4、图片 7→5；图片自己没被扫。
            assert moved["b"]["position_ticks"] == 3 * SECOND, moved["b"]
            assert moved["s"]["position_ticks"] == 5 * SECOND, moved["s"]
            assert moved["s"]["duration_ticks"] == 2 * SECOND, moved["s"]
            print(
                "   整轨：a 0..1、b 3..4、图片跳过并被两次 ripple 带到 5 秒，一个 revision"
            )

    print(
        f"PASS: 按镜头粗剪（{APP_VERSION}）——三段各留 1 秒并首尾相接、一镜到底只留头、"
        "留得比镜头长时画面一字不动、50% 速度折到时间线且源入点仍对、图片与声音按名字拒绝、"
        "没可切的按 ROUGH_NONE 拒绝且不写半个版本"
    )


if __name__ == "__main__":
    main()
