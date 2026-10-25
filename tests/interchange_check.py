"""1.289：工程格式互操作——OTIO 导出/导入计划、FCPXML 导出。

这一档量的是四件真引擎才说得准的事：
* OTIO 的轨道、空隙与记录时间与工程一致，片段元数据带得回完整记录；
* 导入只交回普通命令（先清空这条轨，再逐段 clip.add），apply 一次一个 revision，
  往返之后每段的轨道、位置、源入点与时长逐项相同；
* 认不出的文件、同名两个素材、轨道数不够，各自按名字拒绝且不写库；
* FCPXML 是合法 XML，说不出的文字层进 omitted，complete 为假。
"""

from __future__ import annotations

import copy
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

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
        "-f", "lavfi", "-i", "color=c=0x334455:s=320x180:r=30:d=6",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target),
    ])
    return target


def tone(folder: Path) -> Path:
    target = folder / "tone.wav"
    run([
        str(FFMPEG), "-v", "error", "-y", "-nostdin",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2", str(target),
    ])
    return target


def client_for(folder: Path):
    media = MediaService(folder / "i-db.sqlite3", [folder], folder / "i-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "i-api.sqlite3", FFMPEG, folder / "deliverables", [folder / "deliverables"]
    )
    token = "interchange" + "c" * 52
    app = create_app(folder / "i-api.sqlite3", token, media=media, jobs=runtime)
    return app, token


def create(client: TestClient, pid: str, revision: int, request: str, commands) -> dict:
    done = client.post(
        f"/v1/projects/{pid}/edits",
        json={"request_id": request, "expected_revision": revision, "commands": commands},
    )
    assert done.status_code == 200, done.text
    return done.json()["project"]


def seed(client: TestClient, video_probe: dict, audio_probe: dict) -> str:
    made = client.post(
        "/v1/projects",
        json={
            "request_id": "i-new",
            "name": "Interchange",
            "settings": {"width": 320, "height": 180, "frame_rate": {"numerator": 30,
                                                                     "denominator": 1}},
        },
    )
    assert made.status_code == 200, made.text
    pid, revision = made.json()["project"]["id"], made.json()["project"]["revision"]
    create(
        client, pid, revision, "i-seed",
        [
            {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
            {"op": "track.add", "track": {"id": "snd", "kind": "audio", "name": "声音"}},
            {
                "op": "asset.import", "asset_id": "s", "label": "solid.mp4",
                "probe_id": video_probe["probe_id"], "verified": video_probe,
            },
            {
                "op": "asset.import", "asset_id": "w", "label": "tone.wav",
                "probe_id": audio_probe["probe_id"], "verified": audio_probe,
            },
            {
                "op": "asset.register",
                "asset": {"id": "title", "kind": "text", "label": "标题",
                          "reference": "generated:text"},
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
            {
                "op": "clip.add",
                "clip": {"id": "t", "asset_id": "title", "track_id": "v",
                         "position_ticks": 5 * SECOND, "duration_ticks": SECOND,
                         "text": {"body": "第一句字幕"}},
            },
            {
                "op": "clip.add",
                "clip": {"id": "m", "asset_id": "w", "track_id": "snd",
                         "position_ticks": 0, "duration_ticks": 2 * SECOND},
            },
        ],
    )
    return pid


def signature(project: dict) -> set:
    return {
        (clip["track_id"], clip["position_ticks"], clip["source_in_ticks"],
         clip["duration_ticks"], clip["asset_id"])
        for clip in project["clips"].values()
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-interchange-") as raw:
        folder = Path(raw)
        video, audio = solid(folder), tone(folder)
        app, token = client_for(folder)
        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["otio_export"] is True, caps["features"]
            assert caps["features"]["otio_import"] is True, caps["features"]
            assert caps["features"]["fcpxml_export"] is True, caps["features"]

            video_probe = client.post(
                "/v1/media/import", json={"path": str(video)}
            ).json()["verified"]
            audio_probe = client.post(
                "/v1/media/import", json={"path": str(audio)}
            ).json()["verified"]
            pid = seed(client, video_probe, audio_probe)
            before = client.get(f"/v1/projects/{pid}").json()
            revision = before["revision"]

            # ① OTIO：两条轨、空隙是真的孩子、记录时间与工程一致。
            exported = client.get(f"/v1/projects/{pid}/otio")
            assert exported.status_code == 200, exported.text
            doc = exported.json()["otio"]
            assert doc["OTIO_SCHEMA"] == "Timeline.1", doc["OTIO_SCHEMA"]
            tracks = doc["tracks"]["children"]
            assert [track["kind"] for track in tracks] == ["Video", "Audio"], tracks
            video_children = tracks[0]["children"]
            kinds = [child["OTIO_SCHEMA"] for child in video_children]
            assert kinds == ["Clip.1", "Gap.1", "Clip.1", "Clip.1"], kinds
            gap = video_children[1]["source_range"]["duration"]
            assert abs(gap["value"] - 30) < 1e-6 and gap["rate"] == 30, gap
            record = video_children[0]["metadata"]["agentcut"]["clip"]
            assert record["id"] == "a" and record["position_ticks"] == 0, record
            text_clip = video_children[3]
            assert text_clip["media_reference"]["OTIO_SCHEMA"] == "MissingReference.1", text_clip
            assert text_clip["metadata"]["agentcut"]["clip"]["text"]["body"] == "第一句字幕"
            assert client.get(f"/v1/projects/{pid}").json()["revision"] == revision
            print("   OTIO：2 轨 / 空隙 1 秒 / 文字层带 MissingReference，读一遍不涨版本")

            # ② FCPXML 是合法 XML，文字层进 omitted。
            fcpxml = client.get(f"/v1/projects/{pid}/fcpxml")
            assert fcpxml.status_code == 200, fcpxml.text
            listed = fcpxml.json()
            root = ET.fromstring(listed["xml"])
            assert root.tag == "fcpxml" and root.attrib["version"] == "1.9", root.tag
            spine = root.find(".//spine")
            assert spine is not None
            tags = [child.tag for child in spine]
            assert tags == ["asset-clip", "gap", "asset-clip", "gap"], tags
            assert listed["complete"] is False, listed
            assert [item["clip_id"] for item in listed["omitted"]] == ["t"], listed["omitted"]
            assert listed["duration_ticks"] == 6 * SECOND, listed["duration_ticks"]
            print("   FCPXML：spine 两段 + 一个空隙，文字层按名字进 omitted")

            # ③ 只读规划：不写库，命令先清空这两条轨，再逐段加回。
            planned = client.post(
                f"/v1/projects/{pid}/otio/import",
                json={"document": doc, "apply": False},
            )
            assert planned.status_code == 200, planned.text
            plan = planned.json()
            assert plan["committed"] is False, plan
            assert plan["clips"] == 4 and plan["text_clips"] == 1, plan
            assert plan["gaps"] == 1, plan
            removes = [c for c in plan["commands"] if c["op"] == "clip.remove"]
            adds = [c for c in plan["commands"] if c["op"] == "clip.add"]
            assert len(removes) == 4 and len(adds) == 4, plan["commands"]
            assert client.get(f"/v1/projects/{pid}").json()["revision"] == revision
            print("   规划：4 条删除 + 4 条添加，revision 未动")

            # ④ 应用：一个 revision，往返之后每段的轨道/位置/源入点/时长都相同。
            applied = client.post(
                f"/v1/projects/{pid}/otio/import",
                json={
                    "document": doc,
                    "apply": True,
                    "request_id": "i-apply",
                    "expected_revision": revision,
                },
            )
            assert applied.status_code == 200, applied.text
            after = applied.json()["project"]
            assert after["revision"] == revision + 1, after["revision"]
            assert signature(after) == signature(before), (signature(after), signature(before))
            bodies = [clip["text"]["body"] for clip in after["clips"].values() if clip.get("text")]
            assert bodies == ["第一句字幕"], bodies
            print("   应用：一个 revision，往返后签名逐项相同，字幕正文还在")

            # ⑤ 三种拒绝各自点名，且都不写库。
            bad = client.post(
                f"/v1/projects/{pid}/otio/import",
                json={"document": {"OTIO_SCHEMA": "Clip.1"}},
            )
            assert bad.status_code == 422 and bad.json()["error"]["code"] == "OTIO_UNSUPPORTED"

            missing = copy.deepcopy(doc)
            missing["tracks"]["children"][0]["children"][0]["media_reference"][
                "target_url"
            ] = "file:///nowhere/missing.mp4"
            missing["tracks"]["children"][0]["children"][0]["metadata"] = {}
            stray = client.post(
                f"/v1/projects/{pid}/otio/import",
                json={"document": missing},
            )
            assert stray.status_code == 422, stray.text
            error = stray.json()["error"]
            assert error["code"] == "OTIO_MEDIA_UNMATCHED", error
            assert error["details"]["unmatched"][0]["target_url"].endswith("missing.mp4"), error

            crowded = copy.deepcopy(doc)
            crowded["tracks"]["children"].append(
                {"OTIO_SCHEMA": "Track.1", "name": "多余", "kind": "Video", "children": []}
            )
            too_many = client.post(
                f"/v1/projects/{pid}/otio/import",
                json={"document": crowded},
            )
            assert too_many.status_code == 422, too_many.text
            assert too_many.json()["error"]["code"] == "OTIO_TRACK_COUNT", too_many.json()

            unreceipted = client.post(
                f"/v1/projects/{pid}/otio/import",
                json={"document": doc, "apply": True},
            )
            assert unreceipted.status_code == 422, unreceipted.text
            assert client.get(f"/v1/projects/{pid}").json()["revision"] == revision + 1
            print("   拒绝：非 OTIO / 找不到素材 / 轨道不够 / 应用缺回执，版本都没动")

        print("interchange_check: all green")


if __name__ == "__main__":
    main()
