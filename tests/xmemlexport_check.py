"""1.306：xmeml（FCP7 / Premiere «Export XML»）的出口——写得出、读得回、签名相同。

四层判据：

* **形状**：根是 `<xmeml version="4">`，一条 `<track>` 对一条轨，`clipitem` 带
  `start`/`end`/`in`/`out`，`<file>` 带 `pathurl`；**clipitem 里不许有 `<rate>`**——
  那一个位置在进口读法是「这一段被变速了」，而这里写的是直切；
* **算术**：帧号是整数，序列长度与时间线末尾一致（1461 行那一支的 `_xmeml_frames`）；
* **点名**：文字层（要生成器）与加速段（要 `<rate>` 时基映射）逐条进 `omitted`；
* **回读**：同一份 XML 喂给同一台引擎的进口、落到第二个工程上，落库签名与源工程一致
  （被点名省掉的那两段不在两边）。

分数帧率另外钉一条：出口**拒绝**而不是写一个四舍五入的 29.97。

跑法：空闲机器单跑 `uv run python tests/xmemlexport_check.py`（要随包 ffmpeg 造夹具）。
"""

from __future__ import annotations

import sys
import tempfile
import xml.etree.ElementTree as ElementTree
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
FRAMES_6S = 180


def fail(message: str) -> None:
    raise SystemExit("FAIL: " + message)


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
    service = MediaService(folder / "x-db.sqlite3", [folder], folder / "x-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "x-api.sqlite3", FFMPEG, folder / "deliverables", [folder / "deliverables"]
    )
    token = "xmeml" + "x" * 55
    return create_app(folder / "x-api.sqlite3", token, media=service, jobs=runtime), token


def edit(client, pid, revision, request_id, commands):
    done = client.post(
        f"/v1/projects/{pid}/edits",
        json={"request_id": request_id, "expected_revision": revision, "commands": commands},
    )
    assert done.status_code == 200, done.text
    return done.json()["project"]


def new_project(client, request_id: str, name: str = "出口 & 回读",
                rate: tuple[int, int] = (30, 1)) -> dict:
    made = client.post(
        "/v1/projects",
        json={"request_id": request_id, "name": name,
              "settings": {"width": 320, "height": 180,
                           "frame_rate": {"numerator": rate[0], "denominator": rate[1]}}},
    )
    assert made.status_code == 200, made.text
    return made.json()["project"]


def skeleton(picture: dict, sound: dict, tag: str) -> list[dict]:
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
    dropped = skip or set()
    return {
        (clip["track_id"], clip["position_ticks"], clip["source_in_ticks"],
         clip["duration_ticks"], (clip.get("text") or {}).get("body") or clip["asset_id"])
        for clip in project["clips"].values()
        if clip["id"] not in dropped
    }


def strip(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child(node, name: str):
    return next((item for item in node if strip(item.tag) == name), None)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-xmeml-") as raw:
        folder = Path(raw)
        picture_path, sound_path = media(folder)
        app, token = client_for(folder)
        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["xmeml_export"] is True, caps["features"]

            video = client.post(
                "/v1/media/import", json={"path": str(picture_path)}
            ).json()["verified"]
            audio = client.post(
                "/v1/media/import", json={"path": str(sound_path)}
            ).json()["verified"]

            source = new_project(client, "x-a")
            seed = skeleton(video, audio, "a")
            edit(client, source["id"], source["revision"], "x-a-seed", seed + [
                {"op": "clip.add", "clip": {"id": "pic", "asset_id": "pic", "track_id": "v",
                                            "position_ticks": 0, "duration_ticks": 3 * SECOND}},
                {"op": "clip.add", "clip": {"id": "fast", "asset_id": "pic", "track_id": "v",
                                            "position_ticks": 3 * SECOND,
                                            "duration_ticks": 3 * SECOND,
                                            "speed_percent": 200}},
                {"op": "clip.add", "clip": {"id": "aud", "asset_id": "snd", "track_id": "a",
                                            "position_ticks": 0, "duration_ticks": 6 * SECOND}},
                {"op": "clip.add", "clip": {"id": "cap", "asset_id": "title", "track_id": "c",
                                            "position_ticks": SECOND, "duration_ticks": SECOND,
                                            "text": {"body": "第一句"}}},
            ])
            before = client.get(f"/v1/projects/{source['id']}").json()

            # ① 形状与点名
            listed = client.get(f"/v1/projects/{source['id']}/xmeml")
            assert listed.status_code == 200, listed.text
            out = listed.json()
            assert out["complete"] is False, out
            assert sorted(item["clip_id"] for item in out["omitted"]) == ["cap", "fast"], \
                out["omitted"]
            assert out["tracks"] == {"video": 2, "audio": 1}, out
            assert out["clips"] == 2, out
            assert out["duration_ticks"] == 6 * SECOND, out
            assert out["frame_rate"] == "30", out
            root = ElementTree.fromstring(out["xml"])
            assert strip(root.tag) == "xmeml", root.tag
            sequence = next(node for node in root.iter() if strip(node.tag) == "sequence")
            assert sequence.findtext("name") == "出口 & 回读", sequence.findtext("name")
            assert sequence.findtext("duration") == str(FRAMES_6S), sequence.findtext("duration")
            rate = child(sequence, "rate")
            assert rate is not None and rate.findtext("timebase") == "30", rate
            items = [node for node in root.iter() if strip(node.tag) == "clipitem"]
            assert len(items) == 2, [node.get("id") for node in items]
            for item in items:
                assert child(item, "rate") is None, "clipitem 里的 <rate> 会被读成变速"
                for name in ("start", "end", "in", "out"):
                    value = item.findtext(name)
                    assert value is not None and int(value) >= 0, (name, value)
                name = item.findtext("name")
                assert name in {"solid.mp4", "tone.wav"}, name
                file_node = child(item, "file")
                assert file_node is not None, item.attrib
                url = file_node.findtext("pathurl") or ""
                assert url.endswith(name.replace(" ", "%20")) or url.endswith(name), url
            first = items[0]
            assert [first.findtext(key) for key in ("start", "end", "in", "out")] == \
                ["0", "90", "0", "90"], [first.findtext(k) for k in ("start", "end", "in", "out")]
            assert child(first, "sourcetrack") is None, "画面那一段不该带 sourcetrack"
            audio_item = next(item for item in items if item.findtext("name") == "tone.wav")
            assert child(audio_item, "sourcetrack") is not None, audio_item.attrib
            empty_track = next(
                node for node in sequence.iter()
                if strip(node.tag) == "track" and len(list(node)) == 0
            )
            assert empty_track is not None, "字幕轨全被点名省掉，空轨仍要在（轨道数是结构）"
            print("   出口：3 轨 2 段（文字 1 段、加速 1 段被点名省略）；空轨保留，帧号是整数")

            # ② 回读：同一份 XML 喂给同一台引擎的进口，落到第二个工程上
            target = new_project(client, "x-b")
            edit(client, target["id"], target["revision"], "x-b-seed", skeleton(video, audio, "b"))
            revision = client.get(f"/v1/projects/{target['id']}").json()["revision"]
            imported = client.post(f"/v1/projects/{target['id']}/import", json={
                "document": out["xml"], "format": "xmeml",
                "apply": True, "request_id": "x-b-import", "expected_revision": revision,
            })
            assert imported.status_code == 200, imported.text
            landed = client.get(f"/v1/projects/{target['id']}").json()
            broke = signature(landed) ^ signature(before, {"fast", "cap"})
            assert not broke, f"两边落库签名不一样：{sorted(broke)}"
            assert len(signature(landed)) == 2, signature(landed)
            print("   回读：2 段位置/源入点/时长逐项相同（文字与加速那两段不在两边）")

            # ③ 干净工程：complete 为真，长度与时间线一致
            clean = new_project(client, "x-c")
            edit(client, clean["id"], clean["revision"], "x-c-seed", skeleton(video, audio, "c") + [
                {"op": "clip.add", "clip": {"id": "one", "asset_id": "pic", "track_id": "v",
                                            "position_ticks": 0, "duration_ticks": 2 * SECOND}},
            ])
            tidy = client.get(f"/v1/projects/{clean['id']}/xmeml").json()
            assert tidy["complete"] is True, tidy["omitted"]
            assert tidy["duration_ticks"] == 2 * SECOND, tidy
            print("   干净工程：complete=true，序列长度与时间线一致")

            # ④ 分数帧率：拒绝，不写四舍五入的 29.97
            odd = new_project(client, "x-d", name="分数帧", rate=(30000, 1001))
            refused = client.get(f"/v1/projects/{odd['id']}/xmeml")
            assert refused.status_code == 422, refused.text
            body = refused.json()["error"]
            assert body["code"] == "XMEML_EXPORT_RATE", body
            print("   分数帧率：422 XMEML_EXPORT_RATE（整帧写不出来就不写）")
        print("xmemlexport_check: all green")


if __name__ == "__main__":
    main()
