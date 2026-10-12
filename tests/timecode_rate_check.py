"""时间码的那把尺跟着**交付**率走——1.137 的规矩遇上 1.138 的交付率留下的第二条接缝。

1.137 立规矩的理由是「FFmpeg 会收下并悄悄改写人打的数字」；1.138 让一秒里有几帧变成两件不同的事
（时间线自己的率 vs 交付的率），而 `checked_timecode` 还在按**时间线**那一档判。量出来的后果就是
1.137 想拦的那件事从另一头又回来了：

* 30 的线、按 25 交、写 `00:00:00:29`——**收下**，然后 muxer 把这串按 25 重数，落盘读回来是
  `00:00:01:04`（这一条是本门禁实测的，不是推测）；
* 25 的线、按 30 交、写 `00:00:00:29`——文件里明明有第 29 帧，却被**拒**；
* 丢帧码（分号）同构：29.97 的线按 25 交时原来会被收下，可 25 fps 的流上 SMPTE 根本没有丢帧这回事。

修法是校验交给「这一条交付画面的帧率」：选了交付率就是那一档，没选就跟时间线一致。
这里断四件事：① 上面三格各自的答案（含改写的实测证据）；② 该收下的那些原样落盘、读回来
逐字相同；③ 一次拒绝不写状态、不排队；④ 界面那句提示与那颗「分号可用」的判断也按同一把尺算
（`tests/desktop_timecode_rate_check.ts`）。
"""

import json
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import FrameRate, checked_timecode, timecode_frames
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.media import MediaService

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SRC_W, SRC_H = 320, 180
PRESET = "h264-1080p"


def run(args, timeout=900):
    return subprocess.run(
        [str(a) for a in args],
        capture_output=True,
        check=True,
        timeout=timeout,
        creationflags=0x08000000,
    )


def source(folder: Path, rate: int = 30) -> Path:
    target = folder / f"tcrt-source-{rate}.mp4"
    run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x336699:s={SRC_W}x{SRC_H}:r={rate}:d=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ]
    )
    return target


def stream_tag(path: Path) -> dict:
    payload = json.loads(
        run(
            [
                FFPROBE,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=avg_frame_rate:stream_tags=timecode",
                "-of",
                "json",
                str(path),
            ]
        ).stdout.decode()
    )
    return payload["streams"][0]


def ffmpeg_rewrite_evidence(folder: Path) -> str:
    """让 FFmpeg 自己作证：它收下 25 fps 的 `00:00:00:29`，落盘却写成别的。"""
    clip = source(folder, 25)
    target = folder / "tcrt-rewrite.mp4"
    run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-i",
            str(clip),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "25",
            "-timecode",
            "00:00:00:29",
            str(target),
        ]
    )
    said = stream_tag(target)
    return f"{said.get('avg_frame_rate')}|{(said.get('tags') or {}).get('timecode')}"


def rewrite_evidence_line(said: str) -> str:
    return (
        f"   FFmpeg 自己作证：25 fps 上写 00:00:00:29，落盘读回来是 {said.split('|')[1]}"
        "（数字被改了）"
    )


def wait(client: TestClient, job_id: str) -> dict:
    deadline = time.time() + 600
    while time.time() < deadline:
        job = client.get(f"/v1/jobs/{job_id}").json()["job"]
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.4)
    raise AssertionError(f"任务 {job_id} 没有到点")


def make_project(
    client: TestClient, folder: Path, key: str, name: str, rate: tuple[int, int], duration: int
) -> tuple[str, int, dict]:
    clip = source(folder, rate[0] if rate[1] == 1 else 30)
    probe = client.post("/v1/media/import", json={"path": str(clip)}).json()
    settings = {
        "width": SRC_W,
        "height": SRC_H,
        "frame_rate": {"numerator": rate[0], "denominator": rate[1]},
    }
    project = client.post(
        "/v1/projects", json={"request_id": f"tcrt-new-{key}", "name": name, "settings": settings}
    ).json()["project"]
    path = f"/v1/projects/{project['id']}"
    answer = client.post(
        path + "/edits",
        json={
            "request_id": f"tcrt-seed-{key}",
            "expected_revision": 0,
            "commands": [
                {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                {
                    "op": "asset.import",
                    "asset_id": "a",
                    "label": "a",
                    "probe_id": probe["id"],
                    "verified": probe["verified"],
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "c",
                        "asset_id": "a",
                        "track_id": "v",
                        "position_ticks": 0,
                        "duration_ticks": duration,
                    },
                },
            ],
        },
    )
    assert answer.status_code == 200, answer.text
    return path, answer.json()["project"]["revision"], settings


def unit_suite(folder: Path) -> None:
    r30 = FrameRate(numerator=30, denominator=1)
    r25 = FrameRate(numerator=25, denominator=1)
    # 规矩本身没变：判它的是哪条率才变。这一条把「25 的画面上第 29 帧不存在」写死。
    assert checked_timecode("00:00:00:24", r25) == "00:00:00:24"
    assert timecode_frames(r25) == 25 and timecode_frames(r30) == 30
    try:
        checked_timecode("00:00:00:29", r25)
    except Exception as error:  # noqa: BLE001 - 要看的就是这一句
        assert error.code == "TIMECODE_INVALID" and "00–24" in error.message, error.message
    else:
        raise AssertionError("25 的画面收下了第 29 帧")
    said = ffmpeg_rewrite_evidence(folder)
    assert said.startswith("25/1|") and said.split("|")[1] != "00:00:00:29", said
    print(rewrite_evidence_line(said))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentcut-tcrt-") as scratch:
        folder = Path(scratch)
        unit_suite(folder)
        media = MediaService(
            folder / "tcrt-db.sqlite3", [folder], folder / "tcrt-cache", FFMPEG, FFPROBE
        )
        runtime = JobRuntime(
            folder / "tcrt-api.sqlite3", FFMPEG, folder / "exports", [folder / "exports", folder]
        )
        runtime.ensure_worker()
        token = "tcrtcheck" + "e" * 56
        app = create_app(folder / "tcrt-api.sqlite3", token, media=media, jobs=runtime)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            frame30 = T // 30
            frame25 = T // 25
            frame2997 = T * 1001 // 30000
            p30, r30, _ = make_project(client, folder, "a", "三十格", (30, 1), 60 * frame30)
            p25, r25, _ = make_project(client, folder, "b", "二十五格", (25, 1), 50 * frame25)
            p2997, r2997, _ = make_project(
                client, folder, "c", "二十九点九七", (30000, 1001), 55 * frame2997
            )

            def plan(path: str, revision: int, tc: str, fps: str | None):
                suffix = f"&output_fps={fps}" if fps else ""
                return client.get(
                    f"{path}/render-plan?preset_id={PRESET}&revision={revision}&timecode={tc}{suffix}"
                )

            # ① 三格各自的答案
            wrong = plan(p30, r30, "00:00:00:29", "25")
            assert wrong.status_code == 422, wrong.text
            assert wrong.json()["error"]["code"] == "TIMECODE_INVALID", wrong.text
            assert "25/1" in wrong.json()["error"]["message"], wrong.json()
            assert "00–24" in wrong.json()["error"]["message"], wrong.json()
            # 句子必须点名「这一条画面的帧率」——它说的是交付那一档，不是时间线。
            assert "这一条画面的帧率是" in wrong.json()["error"]["message"], wrong.json()
            ok_same = plan(p30, r30, "00:00:00:29", None)
            assert ok_same.status_code == 200, ok_same.text
            assert ok_same.json()["plan"]["timecode"] == "00:00:00:29", ok_same.json()["plan"]
            ok_low = plan(p30, r30, "00:00:00:24", "25")
            assert ok_low.status_code == 200, ok_low.text
            assert ok_low.json()["plan"]["frame_rate"] == "25/1", ok_low.json()["plan"]
            wider = plan(p25, r25, "00:00:00:29", "30")
            assert wider.status_code == 200, wider.text
            assert wider.json()["plan"]["timecode"] == "00:00:00:29", wider.json()["plan"]
            print(
                "   30 的线交 25：第 29 帧被拒（句子点名 25/1 与 00–24），第 24 帧照收；"
                "25 的线交 30：第 29 帧收下——过去是反着的"
            )

            drop_ok = plan(p2997, r2997, "00:00:00;15", None)
            assert drop_ok.status_code == 200, drop_ok.text
            drop_bad = plan(p2997, r2997, "00:00:00;15", "25")
            assert drop_bad.status_code == 422, drop_bad.text
            assert "丢帧" in drop_bad.json()["error"]["message"], drop_bad.json()
            to_drop = plan(p30, r30, "00:00:00;15", "30000%2F1001")
            assert to_drop.status_code == 200, to_drop.text
            print("   丢帧码也跟着交付率：29.97 的线交 25 被拒，30 的线交 29.97 收下")

            # ② 一次拒绝不写状态、不排队
            before = client.get(p30).json()["revision"]
            jobs_before = client.get(p30 + "/jobs?limit=50").json()["jobs"]
            refused = client.post(
                p30 + "/renders",
                json={
                    "request_id": "tcrt-refuse",
                    "expected_revision": before,
                    "preset_id": PRESET,
                    "filename": "交不出的.mp4",
                    "timecode": "00:00:00:29",
                    "output_frame_rate": {"numerator": 25, "denominator": 1},
                },
            )
            assert refused.status_code == 422, refused.text
            assert client.get(p30).json()["revision"] == before, "一次拒绝写了状态"
            assert client.get(p30 + "/jobs?limit=50").json()["jobs"] == jobs_before, refused.text

            # ③ 该收下的原样落盘：读回来逐字相同
            job = client.post(
                p30 + "/renders",
                json={
                    "request_id": "tcrt-ship",
                    "expected_revision": before,
                    "preset_id": PRESET,
                    "filename": "第二十四帧.mp4",
                    "timecode": "00:00:00:24",
                    "output_frame_rate": {"numerator": 25, "denominator": 1},
                },
            ).json()["job"]
            done = wait(client, job["id"])
            assert done["status"] == "succeeded", done
            said = stream_tag(Path(done["output_path"]))
            assert (said.get("tags") or {}).get("timecode") == "00:00:00:24", said
            assert said["avg_frame_rate"] == "25/1", said
            print(f"   按 25 交、写 00:00:00:24：文件读回来 {said['tags']['timecode']}，一字没改")

            # ④ 只有一处实现：HTTP、MCP、worker 共用 `compile_render_plan` 里那一次判断
            api_src = (ROOT / "src/agentcut/http_api.py").read_text(encoding="utf-8")
            assert "checked_timecode" not in api_src, "HTTP 层自己又判了一遍"
            render_src = (ROOT / "src/agentcut/render.py").read_text(encoding="utf-8")
            assert (
                "checked_timecode(timecode, delivery_rate or settings.frame_rate)" in render_src
            ), "校验没有交给交付率"


if __name__ == "__main__":
    main()
    print(
        "PASS: 时间码的帧号与丢帧码都按这一条交付画面的帧率判（实测 FFmpeg 会把 25 fps 上的 "
        "00:00:00:29 改写成 00:00:01:04），该收下的落盘读回来一字没改，一次拒绝不写状态也不排队"
    )
