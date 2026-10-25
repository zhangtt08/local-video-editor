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

            # ⑤ 1.292：四种别人写的工程，读进同一个项目，应该收敛成**逐字段相同**的时间线。
            # 断言的不是「各自没崩」，而是「四种说法指的是同一刀」——任何一家把源入点、
            # 记录位置或时长折错一格，签名就对不上。
            expected = {
                ("v", 0, 0, 2 * SECOND, "s"),
                ("v", 3 * SECOND, SECOND, 2 * SECOND, "s"),
                ("snd", 0, 0, 2 * SECOND, "w"),
            }
            fcpxml_doc = """<?xml version="1.0" encoding="UTF-8"?>
<fcpxml version="1.9">
  <resources>
    <format id="r0" frameDuration="1/30s" width="320" height="180"/>
    <asset id="r1" name="solid.mp4" src="file:///elsewhere/solid.mp4" start="0s"
           duration="6s" format="r0" hasVideo="1" hasAudio="1"/>
    <asset id="r2" name="tone.wav" src="file:///elsewhere/tone.wav" start="0s"
           duration="6s" format="r0" hasAudio="1"/>
  </resources>
  <library><event><project><sequence id="s0" format="r0" tcFormat="NDF" duration="5s">
    <spine>
      <asset-clip ref="r1" offset="0s" start="0s" duration="2s" format="r0" name="A"/>
      <gap offset="2s" duration="1s"/>
      <asset-clip ref="r1" offset="3s" start="1s" duration="2s" format="r0" name="B"/>
      <transition name="cross dissolve" offset="2s" duration="0.5s"/>
      <lane id="l1" offset="0s" duration="5s">
        <audio-clip ref="r2" offset="0s" start="0s" duration="2s" format="r0" name="T"/>
      </lane>
    </spine>
  </sequence></project></event></library>
</fcpxml>"""
            xmeml_doc = """<?xml version="1.0" encoding="UTF-8"?>
<xmeml version="4"><sequence id="q">
  <rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate>
  <media><video><track format="p2">
    <clipitem id="c1"><name>solid.mp4</name><in>0</in><out>60</out>
      <start>0</start><end>60</end>
      <file id="f1"><pathurl>file:///elsewhere/solid.mp4</pathurl></file></clipitem>
    <clipitem id="c2"><in>30</in><out>90</out><start>90</start><end>150</end>
      <file id="f1"/></clipitem>
  </track></video>
  <audio><track><clipitem id="c3"><in>0</in><out>60</out><start>0</start><end>60</end>
      <file id="f2"><pathurl>file:///elsewhere/tone.wav</pathurl></file></clipitem>
  </track></audio></media>
</sequence></xmeml>"""
            edl_doc = (
                "TITLE: AgentCut\n"
                "FCM: NON-DROP FRAME\n"
                "001  SOLI     V     C        00:00:00:00 00:00:02:00 "
                "00:00:00:00 00:00:02:00\n"
                "* FROM CLIP NAME: solid.mp4\n"
                "002  SOLI     V     C        00:00:01:00 00:00:03:00 "
                "00:00:03:00 00:00:05:00\n"
                "* FROM CLIP NAME: solid.mp4\n"
                "003  TONE     A     C        00:00:00:00 00:00:02:00 "
                "00:00:00:00 00:00:02:00\n"
                "* FROM CLIP NAME: tone.wav\n"
            )
            draft_doc = {
                "tracks": [
                    {"type": "video", "segments": [
                        {"id": "g1", "material_id": "m1",
                         "target_timerange": {"start": 0, "duration": 2_000_000},
                         "source_timerange": {"start": 0, "duration": 2_000_000}},
                        {"id": "g2", "material_id": "m1",
                         "target_timerange": {"start": 3_000_000, "duration": 2_000_000},
                         "source_timerange": {"start": 1_000_000, "duration": 2_000_000}},
                    ]},
                    {"type": "audio", "segments": [
                        {"id": "g3", "material_id": "a1",
                         "target_timerange": {"start": 0, "duration": 2_000_000}},
                    ]},
                ],
                "materials": {
                    "videos": [{"id": "m1", "path": "C:/elsewhere/solid.mp4"}],
                    "audios": [{"id": "a1", "path": "C:/elsewhere/tone.wav"}],
                },
            }
            cases = [
                ("fcpxml", fcpxml_doc),
                ("xmeml", xmeml_doc),
                ("edl", edl_doc),
                ("jianying", draft_doc),
            ]
            here = client.get(f"/v1/projects/{pid}").json()["revision"]
            for name, document in cases:
                planned = client.post(
                    f"/v1/projects/{pid}/import", json={"document": document},
                )
                assert planned.status_code == 200, f"{name}: {planned.text}"
                answer = planned.json()
                assert answer["format"] == name, (name, answer["format"])
                assert answer["committed"] is False, answer
                # 认格式靠文档自己说：不传 format 也要认得。
                assert answer["clips"] == 3, (name, answer["clips"], answer["tracks"])
                if name == "fcpxml":
                    assert answer["complete"] is False, answer
                    assert [item["kind"] for item in answer["omitted"]] == ["transition"], \
                        answer["omitted"]
                applied = client.post(
                    f"/v1/projects/{pid}/import",
                    json={"document": document, "format": name, "apply": True,
                          "request_id": f"imp-{name}", "expected_revision": here},
                )
                assert applied.status_code == 200, f"{name}: {applied.text}"
                here = applied.json()["project"]["revision"]
                got = signature(applied.json()["project"])
                assert got == expected, f"{name} 读进来的不是同一刀：{sorted(got)}"
            assert here == client.get(f"/v1/projects/{pid}").json()["revision"]
            print(f"   四种格式（{', '.join(name for name, _ in cases)}）读进来是同一刀："
                  f"两轨三段、源入点与记录位置逐项相同，一次一个版本")

            # ⑥ 说不准的东西按名字交回，且一个字节都不写。
            refusals = [
                ({"document": "<!DOCTYPE a [<!ENTITY x 'y'>]><fcpxml/>"},
                 "FCPXML_MALFORMED_ENTITIES"),
                ({"document": "hello, not a timeline"}, "INTERCHANGE_UNKNOWN"),
                ({"document": edl_doc.replace("FCM: NON-DROP FRAME", "FCM: DROP-FRAME")},
                 "EDL_DROP_FRAME"),
                ({"document": fcpxml_doc.replace("/elsewhere/solid.mp4", "/nowhere/gone.mp4")},
                 "FCPXML_MEDIA_UNMATCHED"),
                ({}, "INTERCHANGE_NO_DOCUMENT"),
            ]
            frozen = client.get(f"/v1/projects/{pid}").json()["revision"]
            for payload, code in refusals:
                bad = client.post(f"/v1/projects/{pid}/import", json=payload)
                assert bad.status_code == 422, f"{code}: {bad.status_code} {bad.text}"
                assert bad.json()["error"]["code"] == code, (code, bad.json()["error"])
            assert client.get(f"/v1/projects/{pid}").json()["revision"] == frozen, \
                "有一条拒绝写进了库"
            print(f"   拒绝：实体声明 / 认不出的文档 / 丢帧时码 / 素材不在本机 / 没交文档，"
                  f"{len(refusals)} 条各自按名字回，版本一步没涨")

            # ⑦ 加密的剪映草稿不猜：点名说清楚，并指出出路。
            sealed = client.post(
                f"/v1/projects/{pid}/import",
                json={"document": "\u0000ÿþ not json at all"},
            )
            assert sealed.status_code == 422, sealed.text
            assert sealed.json()["error"]["code"] == "INTERCHANGE_UNKNOWN", sealed.json()
            declared = client.post(
                f"/v1/projects/{pid}/import",
                json={"document": {"encrypted": 1, "tracks": []}, "format": "jianying"},
            )
            assert declared.status_code == 422, declared.text
            assert declared.json()["error"]["code"] == "JIANYING_ENCRYPTED", declared.json()
            print("   加密草稿：认不出来的 JSON 与自称 encrypted 的草稿各自按名字拒绝，不猜内容")

        print("interchange_check: all green")


if __name__ == "__main__":
    main()
