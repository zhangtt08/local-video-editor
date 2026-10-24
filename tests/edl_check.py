"""1.285：EDL 剪辑表——一条画面轨的直切列表，时码按整帧写，说不出的东西整条拒绝。

四件只有真引擎才说得准的事：
* 两段画面的源入点与记录入点各自落在正确的帧上（30 fps，00:00:03:00 起的第二段）；
* 8 格卷名由素材标签清洗得到（`solid.mp4` → `SOLID_MP`），事件号从 001 起；
* 读一遍不改工程（revision 不动）；
* 声音轨、变速、分数帧率、空轨各自按名字拒绝，绝不悄悄漏掉一个镜头。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut.contracts import APP_VERSION  # noqa: E402
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


def solid(folder: Path) -> Path:
    target = folder / "solid.mp4"
    run([
        str(FFMPEG), "-v", "error", "-y", "-nostdin",
        "-f", "lavfi", "-i", "color=c=0x334455:s=320x180:r=30:d=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target),
    ])
    return target


def tone(folder: Path) -> Path:
    target = folder / "tone.wav"
    run([
        str(FFMPEG), "-v", "error", "-y", "-nostdin",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3", str(target),
    ])
    return target


def client_for(folder: Path):
    media = MediaService(folder / "e-db.sqlite3", [folder], folder / "e-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "e-api.sqlite3", FFMPEG, folder / "deliverables", [folder / "deliverables"]
    )
    token = "edlcheck" + "c" * 56
    app = create_app(folder / "e-api.sqlite3", token, media=media, jobs=runtime)
    return app, token


def project(client: TestClient, tag: str, rate=None) -> tuple[str, int]:
    settings = {"width": 320, "height": 180}
    if rate is not None:
        settings["frame_rate"] = rate
    made = client.post(
        "/v1/projects",
        json={"request_id": f"e-new-{tag}", "name": f"EDL {tag}", "settings": settings},
    )
    assert made.status_code == 200, made.text
    return made.json()["project"]["id"], made.json()["project"]["revision"]


def create(client: TestClient, pid: str, revision: int, request: str, commands) -> dict:
    done = client.post(
        f"/v1/projects/{pid}/edits",
        json={"request_id": request, "expected_revision": revision, "commands": commands},
    )
    assert done.status_code == 200, done.text
    return done.json()["project"]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-edl-") as raw:
        folder = Path(raw)
        video, audio = solid(folder), tone(folder)
        app, token = client_for(folder)
        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["edl_export"] is True, caps["features"]

            video_probe = client.post(
                "/v1/media/import", json={"path": str(video)}
            ).json()["verified"]
            audio_probe = client.post(
                "/v1/media/import", json={"path": str(audio)}
            ).json()["verified"]

            # ① 两段画面：源入点 0 / 1 秒，记录入点 0 / 3 秒。
            pid, revision = project(client, "main")
            project_row = create(
                client, pid, revision, "e-seed-main",
                [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
                    {"op": "track.add", "track": {"id": "e", "kind": "video", "name": "空"}},
                    {
                        "op": "asset.import", "asset_id": "s", "label": "solid.mp4",
                        "probe_id": video_probe["probe_id"], "verified": video_probe,
                    },
                    {
                        "op": "clip.add",
                        "clip": {"id": "a", "asset_id": "s", "track_id": "v",
                                 "position_ticks": 0, "duration_ticks": 2 * SECOND},
                    },
                    {
                        "op": "clip.add",
                        "clip": {"id": "b", "asset_id": "s", "track_id": "v",
                                 "position_ticks": 3 * SECOND, "duration_ticks": 2 * SECOND,
                                 "source_in_ticks": SECOND},
                    },
                ],
            )
            listed = client.get(f"/v1/projects/{pid}/edl?track_id=v")
            assert listed.status_code == 200, listed.text
            body = listed.json()
            assert body["frame_rate"] == 30, body
            assert body["duration_ticks"] == 5 * SECOND, body["duration_ticks"]
            events = body["events"]
            assert [event["number"] for event in events] == [1, 2], events
            assert [event["reel"] for event in events] == ["SOLID_MP", "SOLID_MP"], events
            assert events[0]["source_in"] == "00:00:00:00", events[0]
            assert events[0]["source_out"] == "00:00:02:00", events[0]
            assert events[0]["record_in"] == "00:00:00:00", events[0]
            assert events[0]["record_out"] == "00:00:02:00", events[0]
            assert events[1]["source_in"] == "00:00:01:00", events[1]
            assert events[1]["source_out"] == "00:00:03:00", events[1]
            assert events[1]["record_in"] == "00:00:03:00", events[1]
            assert events[1]["record_out"] == "00:00:05:00", events[1]
            text = body["text"]
            assert text.startswith("TITLE: EDL main\n"), text[:80]
            assert "FCM: NON-DROP FRAME" in text, text
            first = "001  SOLID_MP V     C        "
            second = "002  SOLID_MP V     C        "
            assert first + "00:00:00:00 00:00:02:00 00:00:00:00 00:00:02:00" in text, text
            assert second + "00:00:01:00 00:00:03:00 00:00:03:00 00:00:05:00" in text, text
            assert text.count("* FROM CLIP NAME: solid.mp4") == 2, text
            assert client.get(f"/v1/projects/{pid}").json()["revision"] == project_row["revision"]
            print(
                f"   30 fps：两段直切 001/002，源入点 "
                f"{events[0]['source_in']} / {events[1]['source_in']}，"
                f"记录 {events[1]['record_in']} → {events[1]['record_out']}，revision 未动"
            )

            # ② 空轨：按名字说没有东西可列。
            empty = client.get(f"/v1/projects/{pid}/edl?track_id=e")
            assert empty.status_code == 422, empty.text
            assert empty.json()["error"]["code"] == "EDL_EMPTY", empty.json()

            # ③ 声音轨与未知轨各自拒绝。
            create(
                client, pid, project_row["revision"], "e-seed-audio",
                [
                    {"op": "track.add", "track": {"id": "snd", "kind": "audio", "name": "声音"}},
                    {
                        "op": "asset.import", "asset_id": "w", "label": "w",
                        "probe_id": audio_probe["probe_id"], "verified": audio_probe,
                    },
                    {
                        "op": "clip.add",
                        "clip": {"id": "w1", "asset_id": "w", "track_id": "snd",
                                 "position_ticks": 0, "duration_ticks": 2 * SECOND},
                    },
                ],
            )
            sound = client.get(f"/v1/projects/{pid}/edl?track_id=snd")
            assert sound.status_code == 422, sound.text
            assert sound.json()["error"]["code"] == "EDL_UNSUPPORTED", sound.json()
            missing = client.get(f"/v1/projects/{pid}/edl?track_id=nope")
            assert missing.status_code == 404, missing.text

            # ④ 变速：整条拒绝并点名是哪一段。
            current = client.get(f"/v1/projects/{pid}").json()["revision"]
            create(
                client, pid, current, "e-seed-speed",
                [{"op": "clip.speed", "clip_id": "b", "speed_percent": 200}],
            )
            speed = client.get(f"/v1/projects/{pid}/edl?track_id=v")
            assert speed.status_code == 422, speed.text
            assert speed.json()["error"]["code"] == "EDL_UNSUPPORTED", speed.json()
            named = speed.json()["error"]["details"]["clips"]
            assert [item["clip_id"] for item in named] == ["b"], named
            assert "speed" in named[0]["reason"], named

            # ⑤ 分数帧率：先定丢帧算法，这一版按名字拒绝。
            frac_pid, frac_revision = project(
                client, "frac", {"numerator": 30000, "denominator": 1001}
            )
            create(
                client, frac_pid, frac_revision, "e-seed-frac",
                [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
                    {
                        "op": "asset.import", "asset_id": "s", "label": "solid.mp4",
                        "probe_id": video_probe["probe_id"], "verified": video_probe,
                    },
                    {
                        "op": "clip.add",
                        "clip": {"id": "a", "asset_id": "s", "track_id": "v",
                                 "position_ticks": 0, "duration_ticks": 2354352 * 30},
                    },
                ],
            )
            frac = client.get(f"/v1/projects/{frac_pid}/edl?track_id=v")
            assert frac.status_code == 422, frac.text
            assert frac.json()["error"]["code"] == "EDL_RATE", frac.json()

    print(
        f"PASS: EDL 剪辑表（{APP_VERSION}）——两段直切按 30 fps 不丢帧写出源/记录时码"
        "与 8 格卷名、读一遍不改 revision；空轨、声音轨、变速与分数帧率各自按名字拒绝并点名"
    )


if __name__ == "__main__":
    main()
