"""1.304：剪映 / CapCut 明文草稿的出口——写得出、读得回、落库签名相同。

三层判据：
* **形状**：`tracks[].type` 只有 video / audio，`segments[]` 带 `material_id` 与
  `target_timerange` / `source_timerange`（微秒），素材进 `materials.videos|audios|texts`；
* **算术**：时间与长度按 `TIMEBASE` 换成微秒（70,560,000 tick = 1 秒，不是 1000 tick = 1 秒）；
* **回读**：把这份草稿喂给同一台引擎的进口、落到第二个工程上，落库签名要和源工程一致——
  变速那一段被**点名省略**（照写会交回「位置对、内容错」的一段），所以比对时它不在。

这一档**不**声称「剪映一定能打开」：这台机器上没有剪映，能证的是「本工程写得出、本工程读得回」。

跑法：空闲机器单跑 `uv run python tests/jianyingexport_check.py`（要随包 ffmpeg 造夹具）。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut.contracts import TIMEBASE  # noqa: E402
from agentcut.http_api import create_app  # noqa: E402
from agentcut.jobs import JobRuntime  # noqa: E402
from agentcut.media import MediaService  # noqa: E402

FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SECOND = TIMEBASE
FRAME = SECOND // 30


def fail(message: str) -> None:
    raise SystemExit("FAIL: " + message)


def micros(ticks: int) -> int:
    return round(ticks * 1_000_000 / TIMEBASE)


def media(folder: Path) -> tuple[Path, Path]:
    from subprocess import run

    picture, sound = folder / "solid.mp4", folder / "tone.wav"
    if run([str(FFMPEG), "-v", "error", "-y", "-nostdin", "-f", "lavfi", "-i",
            "color=c=0x334455:s=320x180:r=30:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(picture)], capture_output=True).returncode != 0:
        fail("造不出画面夹具")
    if run([str(FFMPEG), "-v", "error", "-y", "-nostdin", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=6", str(sound)], capture_output=True).returncode != 0:
        fail("造不出声音夹具")
    return picture, sound


def client_for(folder: Path):
    service = MediaService(folder / "j-db.sqlite3", [folder], folder / "j-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "j-api.sqlite3", FFMPEG, folder / "deliverables", [folder / "deliverables"]
    )
    token = "jianying" + "j" * 52
    return create_app(folder / "j-api.sqlite3", token, media=service, jobs=runtime), token


def edit(client, pid, revision, request_id, commands):
    done = client.post(
        f"/v1/projects/{pid}/edits",
        json={"request_id": request_id, "expected_revision": revision, "commands": commands},
    )
    assert done.status_code == 200, done.text
    return done.json()["project"]


def new_project(client, request_id: str) -> dict:
    made = client.post(
        "/v1/projects",
        json={"request_id": request_id, "name": "Draft",
              "settings": {"width": 320, "height": 180,
                           "frame_rate": {"numerator": 30, "denominator": 1}}},
    )
    assert made.status_code == 200, made.text
    return made.json()["project"]


def skeleton(picture: dict, sound: dict, tag: str) -> list[dict]:
    """两边的工程骨架一模一样：三条轨（画面 / 声音 / 字幕）与两份素材。"""
    return [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
        {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "声音"}},
        {"op": "track.add", "track": {"id": "c", "kind": "video", "name": "字幕"}},
        {"op": "asset.import", "asset_id": "pic", "label": "solid.mp4",
         "probe_id": picture["probe_id"], "verified": picture},
        {"op": "asset.import", "asset_id": "snd", "label": "tone.wav",
         "probe_id": sound["probe_id"], "verified": sound},
        {"op": "asset.register", "asset": {"id": "title", "kind": "text", "label": "字",
                                          "reference": f"generated:text:{tag}"}},
    ]


def signature(project: dict, skip: set[str] | None = None) -> set:
    """Every clip's (track, position, source in, duration, name) — ids left out of the compare.

    `skip` drops the clips the draft could not carry: they are in the source project and are
    not in the draft, so the round trip can only match on the rest.
    """
    dropped = skip or set()
    return {
        (clip["track_id"], clip["position_ticks"], clip["source_in_ticks"],
         clip["duration_ticks"], (clip.get("text") or {}).get("body") or clip["asset_id"])
        for clip in project["clips"].values()
        if clip["id"] not in dropped
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-jianying-") as raw:
        folder = Path(raw)
        picture_path, sound_path = media(folder)
        app, token = client_for(folder)
        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["jianying_export"] is True, caps["features"]

            video = client.post(
                "/v1/media/import", json={"path": str(picture_path)}
            ).json()["verified"]
            audio = client.post(
                "/v1/media/import", json={"path": str(sound_path)}
            ).json()["verified"]

            source = new_project(client, "j-a")
            seed = skeleton(video, audio, "a")
            edit(client, source["id"], source["revision"], "j-a-seed", seed + [
                {"op": "clip.add", "clip": {"id": "pic", "asset_id": "pic", "track_id": "v",
                                            "position_ticks": 0, "duration_ticks": 3 * SECOND}},
                # 200% 变速：草稿里说不准（写出来位置对、内容错），必须被点名省略
                {"op": "clip.add", "clip": {"id": "fast", "asset_id": "pic", "track_id": "v",
                                            "position_ticks": 3 * SECOND,
                                            "duration_ticks": 3 * SECOND,
                                            "speed_percent": 200}},
                {"op": "clip.add", "clip": {"id": "cap", "asset_id": "title", "track_id": "c",
                                            "position_ticks": SECOND, "duration_ticks": SECOND,
                                            "text": {"body": "第一句"}}},
                {"op": "clip.add", "clip": {"id": "aud", "asset_id": "snd", "track_id": "a",
                                            "position_ticks": 0, "duration_ticks": 6 * SECOND}},
            ])
            before = client.get(f"/v1/projects/{source['id']}").json()

            # ① 出口的形状与算术
            listed = client.get(f"/v1/projects/{source['id']}/jianying")
            assert listed.status_code == 200, listed.text
            out = listed.json()
            draft = out["draft"]
            assert out["complete"] is False, out
            assert [item["clip_id"] for item in out["omitted"]] == ["fast"], out["omitted"]
            assert "speed" in out["omitted"][0]["reason"], out["omitted"]
            assert out["tracks"] == 3, out
            assert out["clips"] == 3, out
            assert out["text_clips"] == 1, out
            canvas = draft["canvas_config"]
            assert canvas == {"width": 320, "height": 180, "ratio": "original"}, draft
            assert draft["duration"] == micros(6 * SECOND), draft["duration"]
            kinds = [track["type"] for track in draft["tracks"]]
            assert kinds == ["video", "audio", "video"], kinds
            segments = [segment for track in draft["tracks"] for segment in track["segments"]]
            assert len(segments) == 3, segments
            # 每一段的长度落回 tick 之后仍在整帧上：微秒是四舍五入来的，判的是**回读之后**对不对齐，
            # 不是「微秒能被每帧的微秒数整除」（33333.3 µs/帧，整除这条本来就不成立）。
            for segment in segments:
                length = segment["target_timerange"]["duration"]
                ticks = round(length * TIMEBASE / 1_000_000)
                assert ticks % FRAME == 0, (segment, ticks, ticks % FRAME)
            first = draft["tracks"][0]["segments"][0]
            span = {"start": 0, "duration": micros(3 * SECOND)}
            assert first["target_timerange"] == span, first
            assert first["source_timerange"] == span, first
            assert first["source_timerange"] == {"start": 0, "duration": micros(3 * SECOND)}, first
            counts = [len(draft["materials"][group]) for group in ("videos", "audios", "texts")]
            assert counts == [1, 1, 1], draft["materials"]
            print(f"   出口：3 轨 3 段（文字 1 段）、"
                  f"{len(draft['materials']['videos'])} 份画面素材；200% 变速那一段被点名省略")

            # ② 回读：同一份草稿喂给同一台引擎的进口，落到第二个工程上
            target = new_project(client, "j-b")
            edit(client, target["id"], target["revision"], "j-b-seed", skeleton(video, audio, "b"))
            revision = client.get(f"/v1/projects/{target['id']}").json()["revision"]
            imported = client.post(f"/v1/projects/{target['id']}/import", json={
                "document": out["json"], "format": "jianying",
                "apply": True, "request_id": "j-b-import", "expected_revision": revision,
            })
            assert imported.status_code == 200, imported.text
            landed = client.get(f"/v1/projects/{target['id']}").json()

            broke = signature(landed) ^ signature(before, {"fast"})
            assert not broke, f"两边落库签名不一样：{sorted(broke)}"
            assert len(signature(landed)) == 3, signature(landed)
            bodies = {(clip.get("text") or {}).get("body") for clip in landed["clips"].values()}
            assert "第一句" in bodies, bodies
            print("   回读：3 段位置/源入点/时长/文字逐项相同（变速那一段不在两边）")

            # ③ 一份没有变速的干净工程：complete 为真，草稿与原时间线等长
            clean = new_project(client, "j-c")
            edit(client, clean["id"], clean["revision"], "j-c-seed", skeleton(video, audio, "c") + [
                {"op": "clip.add", "clip": {"id": "one", "asset_id": "pic", "track_id": "v",
                                            "position_ticks": 0, "duration_ticks": 2 * SECOND}},
            ])
            tidy = client.get(f"/v1/projects/{clean['id']}/jianying").json()
            assert tidy["complete"] is True, tidy["omitted"]
            assert tidy["duration_ticks"] == 2 * SECOND, tidy
            print("   干净工程：complete=true，草稿长度与时间线一致")
        print("jianyingexport_check: all green")


if __name__ == "__main__":
    main()
