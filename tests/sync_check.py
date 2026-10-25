"""1.288：多机位对齐——同一段声音在两条文件里差了 0.8 秒，相关峰把它找回来。

这一档钉四件事：
* 只读计划：偏移 0.8 秒 / 24 帧，工程 revision 不动；
* apply：一个 revision，其它机位移到「基准位置 − 偏移」，基准自己不动；
* 纯音（包络减掉均值后几乎是零）按 `SYNC_WEAK` 拒绝，同一条轨与变速片段按名字拒绝；
* 对齐会落到零之前时 `SYNC_OUT_OF_RANGE`，本来就同拍时 `SYNC_ALIGNED`，两者都不写半个版本。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut.contracts import APP_VERSION, SYNC_MIN_SCORE  # noqa: E402
from agentcut.http_api import create_app  # noqa: E402
from agentcut.jobs import JobRuntime  # noqa: E402
from agentcut.media import MediaService  # noqa: E402

FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SECOND = 70_560_000
FRAME = 2_352_000


def run(args, timeout=300):
    done = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=0x08000000)
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-600:]
    return done.stdout


def burst(folder: Path, name: str, offset_ms: int) -> Path:
    """Five seconds of quiet with the same 0.1 s pink-noise burst at the given offset."""
    target = folder / name
    run([
        str(FFMPEG), "-v", "error", "-y", "-nostdin",
        "-f", "lavfi", "-i", "anoisesrc=d=0.1:c=pink:r=48000:a=0.8:seed=1234",
        "-af", f"adelay={offset_ms}|{offset_ms},apad=whole_dur=5", "-t", "5", str(target),
    ])
    return target


def tone(folder: Path, name: str, hz: float) -> Path:
    target = folder / name
    run([
        str(FFMPEG), "-v", "error", "-y", "-nostdin",
        "-f", "lavfi", "-i", f"sine=frequency={hz}:sample_rate=48000:duration=5", str(target),
    ])
    return target


def client_for(folder: Path):
    media = MediaService(folder / "s-db.sqlite3", [folder], folder / "s-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "s-api.sqlite3", FFMPEG, folder / "deliverables", [folder / "deliverables"]
    )
    token = "synccheck" + "c" * 55
    app = create_app(folder / "s-api.sqlite3", token, media=media, jobs=runtime)
    return app, token


def seed(
    client: TestClient, tag: str, rows: list[tuple[str, Path, int, int, int]]
) -> tuple[str, int]:
    """rows: (clip_id, file, position_seconds_ticks, duration_ticks, speed_percent)."""
    made = client.post(
        "/v1/projects", json={"request_id": f"sy-new-{tag}", "name": f"对齐 {tag}"}
    )
    assert made.status_code == 200, made.text
    pid = made.json()["project"]["id"]
    commands = []
    for index, (clip_id, file, position, duration, speed) in enumerate(rows):
        probe = client.post("/v1/media/import", json={"path": str(file)}).json()["verified"]
        track = f"t{index}"
        commands.append({"op": "track.add", "track": {"id": track, "kind": "audio", "name": track}})
        commands.append(
            {
                "op": "asset.import", "asset_id": f"a{index}", "label": f"{clip_id}.wav",
                "probe_id": probe["probe_id"], "verified": probe,
            }
        )
        clip = {
            "id": clip_id, "asset_id": f"a{index}", "track_id": track,
            "position_ticks": position, "duration_ticks": duration,
        }
        if speed != 100:
            clip["speed_percent"] = speed
        commands.append({"op": "clip.add", "clip": clip})
    done = client.post(
        f"/v1/projects/{pid}/edits",
        json={"request_id": f"sy-seed-{tag}", "expected_revision": 0, "commands": commands},
    )
    assert done.status_code == 200, done.text
    return pid, done.json()["project"]["revision"]


def plan(client: TestClient, pid: str, revision: int, request: str, **body):
    return client.post(
        f"/v1/projects/{pid}/sync",
        json={"request_id": request, "expected_revision": revision, **body},
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-sync-") as raw:
        folder = Path(raw)
        reference_file = burst(folder, "ref.wav", 1000)
        late_file = burst(folder, "late.wav", 1800)
        sine_a, sine_b = tone(folder, "a.wav", 440), tone(folder, "b.wav", 880)
        app, token = client_for(folder)
        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["multicam_sync"] is True, caps["features"]
            assert caps["limits"]["sync_min_score"] == SYNC_MIN_SCORE, caps["limits"]

            # ① 只读计划：0.8 秒 = 24 帧，b 移到 1.2 秒；revision 不动。
            pid, revision = seed(
                client,
                "main",
                [
                    ("a", reference_file, 2 * SECOND, 5 * SECOND, 100),
                    ("b", late_file, 4 * SECOND, 5 * SECOND, 100),
                ],
            )
            planned = plan(client, pid, revision, "sy-plan", clip_ids=["a", "b"])
            assert planned.status_code == 200, planned.text
            body = planned.json()
            assert body["committed"] is False, body
            rows = {item["clip_id"]: item for item in body["sync"]["clips"]}
            assert rows["b"]["offset_ticks"] == 24 * FRAME, rows["b"]
            assert rows["b"]["offset_frames"] == 24, rows["b"]
            assert rows["b"]["score"] >= SYNC_MIN_SCORE, rows["b"]
            assert body["sync"]["commands"] == [
                {
                    "op": "clip.move",
                    "clip_id": "b",
                    "track_id": "t1",
                    "position_ticks": 2 * SECOND - 24 * FRAME,
                }
            ], body["sync"]["commands"]
            assert client.get(f"/v1/projects/{pid}").json()["revision"] == revision
            print(
                f"   只读：偏移 {rows['b']['offset_frames']} 帧（0.8 秒），"
                f"峰 {rows['b']['score']}，revision 未动"
            )

            # ② apply：一个 revision，基准不动，另一路落在「基准 − 偏移」。
            applied = plan(
                client, pid, revision, "sy-apply", clip_ids=["a", "b"], apply=True
            )
            assert applied.status_code == 200, applied.text
            project = applied.json()["project"]
            assert project["revision"] == revision + 1, project["revision"]
            clips = {clip["id"]: clip for clip in project["clips"].values()}
            assert clips["a"]["position_ticks"] == 2 * SECOND, clips["a"]
            assert clips["b"]["position_ticks"] == 2 * SECOND - 24 * FRAME, clips["b"]
            print(
                f"   apply：r{revision} → r{project['revision']}，a 仍在 2 秒、b 到 "
                f"{(2 * SECOND - 24 * FRAME) / SECOND:.2f} 秒"
            )

            # ③ 纯音没有可定位的峰：按名字拒绝，不移动。
            weak_pid, weak_revision = seed(
                client,
                "weak",
                [
                    ("a", sine_a, 0, 5 * SECOND, 100),
                    ("b", sine_b, SECOND, 5 * SECOND, 100),
                ],
            )
            weak = plan(client, weak_pid, weak_revision, "sy-weak", clip_ids=["a", "b"], apply=True)
            assert weak.status_code == 422, weak.text
            assert weak.json()["error"]["code"] == "SYNC_WEAK", weak.json()
            assert client.get(f"/v1/projects/{weak_pid}").json()["revision"] == weak_revision

            # ④ 同一条轨、变速片段各自按名字拒绝。
            same_pid, same_revision = seed(
                client, "same", [("a", reference_file, 0, 5 * SECOND, 100)]
            )
            add = client.post(
                f"/v1/projects/{same_pid}/edits",
                json={
                    "request_id": "sy-same-add",
                    "expected_revision": same_revision,
                    "commands": [
                        {
                            "op": "clip.add",
                            "clip": {"id": "b", "asset_id": "a0", "track_id": "t0",
                                     "position_ticks": 6 * SECOND, "duration_ticks": 5 * SECOND},
                        }
                    ],
                },
            )
            assert add.status_code == 200, add.text
            same = plan(
                client, same_pid, add.json()["project"]["revision"], "sy-same",
                clip_ids=["a", "b"],
            )
            assert same.status_code == 422, same.text
            assert same.json()["error"]["code"] == "INVALID_SYNC_TARGET", same.json()
            speed_pid, speed_revision = seed(
                client,
                "speed",
                [
                    ("a", reference_file, 0, 5 * SECOND, 100),
                    ("b", late_file, 6 * SECOND, 2 * SECOND, 200),
                ],
            )
            speed = plan(client, speed_pid, speed_revision, "sy-speed", clip_ids=["a", "b"])
            assert speed.status_code == 422, speed.text
            assert speed.json()["error"]["code"] == "INVALID_SYNC_TARGET", speed.json()

            # ⑤ 会落到零之前、以及本来就同拍，各自按名字拒绝。
            edge_pid, edge_revision = seed(
                client,
                "edge",
                [
                    ("a", reference_file, 0, 5 * SECOND, 100),
                    ("b", late_file, 4 * SECOND, 5 * SECOND, 100),
                ],
            )
            edge = plan(client, edge_pid, edge_revision, "sy-edge", clip_ids=["a", "b"], apply=True)
            assert edge.status_code == 422, edge.text
            assert edge.json()["error"]["code"] == "SYNC_OUT_OF_RANGE", edge.json()
            same_clock_pid, same_clock_revision = seed(
                client,
                "clock",
                [
                    ("a", reference_file, 2 * SECOND, 5 * SECOND, 100),
                    ("b", reference_file, 2 * SECOND, 5 * SECOND, 100),
                ],
            )
            aligned = plan(
                client, same_clock_pid, same_clock_revision, "sy-aligned",
                clip_ids=["a", "b"], apply=True,
            )
            assert aligned.status_code == 422, aligned.text
            assert aligned.json()["error"]["code"] == "SYNC_ALIGNED", aligned.json()
            unchanged = client.get(f"/v1/projects/{same_clock_pid}").json()
            assert unchanged["revision"] == same_clock_revision

            # ⑥ 少于两段由契约拒绝。
            one = client.post(
                f"/v1/projects/{pid}/sync",
                json={
                    "request_id": "sy-one",
                    "expected_revision": project["revision"],
                    "clip_ids": ["a"],
                },
            )
            assert one.status_code == 422, one.text

    print(
        f"PASS: 多机位对齐（{APP_VERSION}）——0.8 秒的共享声音被量成 24 帧，只读不写；"
        "apply 一个 revision 把另一路移到基准减偏移；"
        "弱峰、同轨、变速、越界与本来就同拍各自按名字拒绝"
    )


if __name__ == "__main__":
    main()
