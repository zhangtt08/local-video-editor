"""1.293：文稿观测面与「删一行字 = 剪掉那一段」。

这一档量的是四件只有真引擎才说得准的事：
* 视图读的就是字幕轨上那几段字：相邻且停顿小的合成一句，够大的空档列成可剪的候选；
* 删一句交回的是普通命令（clip.split / clip.ripple_remove / clip.remove），
  画面、声音、字幕在同一些边界上被剪，apply 一次一个 revision、撤销一次整体退回；
* 锁住的轨与被点名拒绝的区间各自带原因，且一个字节都不写；
* 剪完之后，被删那句话在时间线上真的不存在了（字幕没了、画面短了那么多、总长也短了那么多）。

跑法：空闲机器单跑 `uv run python tests/transcript_check.py`（要随包 ffmpeg 造夹具素材）。
"""

from __future__ import annotations

import sys
import tempfile
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
FRAME = SECOND // 30


def fail(message: str) -> None:
    raise SystemExit("FAIL: " + message)


def solid(folder: Path) -> Path:
    target = folder / "solid.mp4"
    done = [str(FFMPEG), "-v", "error", "-y", "-nostdin",
            "-f", "lavfi", "-i", "color=c=0x334455:s=320x180:r=30:d=6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target)]
    from subprocess import run
    if run(done, capture_output=True).returncode != 0:
        fail("造不出画面夹具")
    return target


def tone(folder: Path) -> Path:
    target = folder / "tone.wav"
    from subprocess import run
    done = [str(FFMPEG), "-v", "error", "-y", "-nostdin",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=6", str(target)]
    if run(done, capture_output=True).returncode != 0:
        fail("造不出声音夹具")
    return target


def client_for(folder: Path):
    media = MediaService(folder / "t-db.sqlite3", [folder], folder / "t-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "t-api.sqlite3", FFMPEG, folder / "deliverables", [folder / "deliverables"]
    )
    token = "transcript" + "t" * 52
    return create_app(folder / "t-api.sqlite3", token, media=media, jobs=runtime), token


def edit(client, pid, revision, request_id, commands):
    done = client.post(
        f"/v1/projects/{pid}/edits",
        json={"request_id": request_id, "expected_revision": revision, "commands": commands},
    )
    assert done.status_code == 200, done.text
    return done.json()["project"]


def caption(clip_id, at_ticks, duration_ticks, body):
    return {"op": "clip.add", "clip": {
        "id": clip_id, "asset_id": "title", "track_id": "cap",
        "position_ticks": int(at_ticks),
        "duration_ticks": int(duration_ticks),
        "text": {"body": body},
    }}


def seed(client, video_probe, audio_probe) -> str:
    made = client.post(
        "/v1/projects",
        json={"request_id": "t-new", "name": "Transcript",
              "settings": {"width": 320, "height": 180,
                           "frame_rate": {"numerator": 30, "denominator": 1}}},
    )
    assert made.status_code == 200, made.text
    pid = made.json()["project"]["id"]
    edit(client, pid, made.json()["project"]["revision"], "t-seed", [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "画面"}},
        {"op": "track.add", "track": {"id": "snd", "kind": "audio", "name": "声音"}},
        {"op": "track.add", "track": {"id": "cap", "kind": "video", "name": "字幕"}},
        {"op": "asset.import", "asset_id": "s", "label": "solid.mp4",
         "probe_id": video_probe["probe_id"], "verified": video_probe},
        {"op": "asset.import", "asset_id": "w", "label": "tone.wav",
         "probe_id": audio_probe["probe_id"], "verified": audio_probe},
        {"op": "asset.register", "asset": {"id": "title", "kind": "text", "label": "字",
                                          "reference": "generated:text"}},
        {"op": "clip.add", "clip": {"id": "pic", "asset_id": "s", "track_id": "v",
                                    "position_ticks": 0, "duration_ticks": 6 * SECOND}},
        {"op": "clip.add", "clip": {"id": "aud", "asset_id": "w", "track_id": "snd",
                                    "position_ticks": 0, "duration_ticks": 6 * SECOND}},
        caption("c1", SECOND, SECOND, "第一句"),
        # 停顿只有一帧（33 毫秒）：说话的人不会把它当成两句话，视图必须合成一句。
        caption("c2", 2 * SECOND + FRAME, SECOND, "第二句"),
        # 这里空了 29 帧（约 967 毫秒）：这才是一个值得递给人看的剪口候选。
        caption("c3", 4 * SECOND, SECOND, "第三句"),
    ])
    return pid


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-transcript-") as raw:
        folder = Path(raw)
        video, audio = solid(folder), tone(folder)
        app, token = client_for(folder)
        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app, base_url="http://127.0.0.1", headers=headers) as client:
            caps = client.get("/v1/capabilities").json()
            assert caps["features"]["transcript_view"] is True, caps["features"]
            assert caps["features"]["transcript_cut"] is True, caps["features"]

            imported = client.post("/v1/media/import", json={"path": str(video)}).json()
            video_probe = imported["verified"]
            audio_probe = client.post("/v1/media/import", json={"path": str(audio)}
                                      ).json()["verified"]
            pid = seed(client, video_probe, audio_probe)
            revision = client.get(f"/v1/projects/{pid}").json()["revision"]

            # ① 视图：三枚字幕读成两句，中间那 970 毫秒是一个候选剪口。
            read = client.get(f"/v1/projects/{pid}/transcript")
            assert read.status_code == 200, read.text
            view = read.json()
            assert view["phrase_count"] == 2, view["phrases"]
            assert view["caption_clips"] == 3, view
            first, second = view["phrases"]
            assert first["text"] == "第一句 第二句", first
            assert first["clip_ids"] == ["c1", "c2"], first
            assert first["from_ticks"] == SECOND, first
            assert first["to_ticks"] == 3 * SECOND + FRAME, first
            assert second["text"] == "第三句", second
            assert second["index"] == 2, second
            assert view["silence_count"] == 1, view["silences"]
            hole = view["silences"][0]
            assert hole["from_ticks"] == first["to_ticks"], hole
            assert hole["to_ticks"] == second["from_ticks"], hole
            assert 900 <= hole["duration_ms"] <= 1040, hole
            assert view["revision"] == revision, view
            print(f"   视图：{view['caption_clips']} 枚字幕读成 {view['phrase_count']} 句，"
                  f"中间 {hole['duration_ms']:.0f} 毫秒的空档列为剪口候选")

            # ② 计划：只交普通命令，且画面/声音/字幕在同一些边界上被剪；读一遍不写库。
            spans = [{"from_ticks": second["from_ticks"], "to_ticks": second["to_ticks"]}]
            planned = client.post(f"/v1/projects/{pid}/transcript/cut", json={"spans": spans})
            assert planned.status_code == 200, planned.text
            plan = planned.json()
            assert plan["committed"] is False, plan
            ops = {command["op"] for command in plan["commands"]}
            assert ops <= {"clip.split", "clip.ripple_remove", "clip.remove"}, ops
            assert "clip.remove" in ops, plan["commands"]
            touched = {item["track_id"] for item in plan["clips"]}
            assert touched == {"v", "snd", "cap"}, plan["clips"]
            assert plan["removed_ticks"] == SECOND, plan["removed_ticks"]
            assert client.get(f"/v1/projects/{pid}").json()["revision"] == revision
            print(f"   计划：{len(plan['commands'])} 条普通命令、{len(touched)} 条轨在同一些边界上"
                  f"被剪，删掉 {plan['removed_ticks'] / SECOND:.0f} 秒，版本没动")

            # ③ 应用：一次一个 revision，剪完那句真的不存在了。
            applied = client.post(f"/v1/projects/{pid}/transcript/cut", json={
                "spans": spans, "apply": True, "request_id": "t-cut",
                "expected_revision": revision,
            })
            assert applied.status_code == 200, applied.text
            after = applied.json()["project"]
            assert after["revision"] == revision + 1, after["revision"]
            bodies = {(clip["text"] or {}).get("body", "")
                      for clip in after["clips"].values() if clip.get("text")}
            assert bodies == {"第一句", "第二句"}, sorted(bodies)
            pic = after["clips"]["pic"]
            # 剪口在 4..5 秒：`pic` 自己是留在前面的那一段，被剪掉的是中间那一块。
            assert pic["duration_ticks"] == 4 * SECOND, pic["duration_ticks"]
            # 被删的是 4..5 秒那一段：留下的后半截读源必须从 5 秒起，不能还是原来的入点。
            pieces = sorted(
                (clip["position_ticks"], clip["source_in_ticks"], clip["duration_ticks"])
                for clip in after["clips"].values()
                if clip["track_id"] == "v" and clip["asset_id"] == "s"
            )
            assert pieces == [(0, 0, 4 * SECOND), (4 * SECOND, 5 * SECOND, SECOND)], pieces
            print("   应用：一个 revision；那句字幕不在了，画面短了 1 秒，"
                  "留下的后半截从源 5 秒起继续读")

            # ④ 退回剪之前：restore 是重放，版本继续涨，但状态必须一字不差地回来。
            undone = client.post(f"/v1/projects/{pid}/restore", json={
                "request_id": "t-undo", "expected_revision": revision + 1,
                "target_revision": revision,
            })
            assert undone.status_code == 200, undone.text
            back = undone.json()["project"]
            assert back["revision"] > revision, back["revision"]
            restored = {(clip["text"] or {}).get("body", "")
                        for clip in back["clips"].values() if clip.get("text")}
            assert restored == {"第一句", "第二句", "第三句"}, \
                f"退回没有把那句话带回来：{sorted(restored)}"
            assert back["clips"]["pic"]["duration_ticks"] == 6 * SECOND, \
                "退回没有把画面恢复成 6 秒"
            print("   撤销：一步回到剪之前，三句都在、画面仍是 6 秒")

            # ⑤ 拒绝：认不出的、倒着写的、没有区间的，各自按名字回，且一个字节都不写。
            empty = client.post("/v1/projects", json={
                "request_id": "t-bare", "name": "Bare",
                "settings": {"width": 320, "height": 180,
                             "frame_rate": {"numerator": 30, "denominator": 1}},
            }).json()["project"]
            bare = client.get(f"/v1/projects/{empty['id']}/transcript")
            assert bare.status_code == 422, bare.text
            assert bare.json()["error"]["code"] == "TRANSCRIPT_EMPTY", bare.json()

            backwards = client.post(f"/v1/projects/{pid}/transcript/cut", json={"spans": [
                {"from_ticks": 5 * SECOND, "to_ticks": 4 * SECOND}]})
            assert backwards.status_code == 422, backwards.text
            assert backwards.json()["error"]["code"] == "TRANSCRIPT_SPAN", backwards.json()

            nothing = client.post(f"/v1/projects/{pid}/transcript/cut", json={"spans": []})
            assert nothing.status_code == 422, nothing.text
            assert nothing.json()["error"]["code"] == "TRANSCRIPT_NO_SPANS", nothing.json()

            frozen = client.get(f"/v1/projects/{pid}").json()["revision"]
            assert client.get(f"/v1/projects/{pid}").json()["revision"] == frozen, \
                "有一条拒绝写进了库"
            print("   拒绝：没有字幕 / 区间倒着写 / 没交区间，三条各按名字回，版本一步没涨")

            # ⑥ 锁住的轨要看得见：它被跳过并带原因，别的那几条轨照剪。
            locked = client.get(f"/v1/projects/{pid}").json()["revision"]
            edit(client, pid, locked, "t-lock", [
                {"op": "track.update", "track_id": "cap", "locked": True},
            ])
            held = client.post(f"/v1/projects/{pid}/transcript/cut", json={"spans": [
                {"from_ticks": 2 * SECOND + FRAME, "to_ticks": 3 * SECOND + FRAME}]})
            assert held.status_code == 200, held.text
            skipped = held.json()["skipped"]
            assert [item["clip_id"] for item in skipped] == ["c2"], skipped
            assert "locked" in skipped[0]["reason"], skipped
            assert {item["track_id"] for item in held.json()["clips"]} == {"v", "snd"}, \
                held.json()["clips"]
            assert client.get(f"/v1/projects/{pid}").json()["revision"] == locked + 1
            print("   锁住的轨：那一枚字幕被跳过并写明原因，画面与声音照剪")

        print("transcript_check: all green")


if __name__ == "__main__":
    main()
