"""Start timecode: the engine owns the rule, and each container is read where it really puts it.

A master handed to a broadcast or colour suite carries a SMPTE start timecode, and FFmpeg will
happily
accept strings that are not one. Measured here, on this machine's bundled FFmpeg, with no engine
in the
loop: `01:60:00:00` is written back as `02:00:00:00` (the invalid minute is *carried into the
hours*),
`01:02:03.04` comes back as `01:02:03;04` (a dot becomes drop-frame), `1:2:3:4` goes through as
written,
and `01:02:03;04` is accepted at an integer 30 fps where the standard says drop-frame does not
exist.
A delivery that quietly rewrites the number a person typed is worse than a refusal, so `contracts`
validates, and the refusal names which field is wrong.

Then the file itself is the evidence:

1. each container stores the string in a **different place** (measured): mov and mp4 in the video
   **stream** tags, mxf and webm in the **format** tags — and webm upper-cases the key to
   `TIMECODE`.
   Reading one generic "the tag" would pass on a file that lost it and fail on one that kept it.
2. the value that comes back is exactly the value that was asked for, byte for byte.
3. a deliverable with no picture is refused rather than given a timecode it cannot mean, and a
refusal
   costs nothing: no job, no revision.
"""

import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import (
    FrameRate,
    RenderJob,
    checked_timecode,
    render_presets,
    timecode_frames,
)
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.mcp_server import create_mcp
from agentcut.media import MediaService
from agentcut.render import output_args

ROOT = Path(r"C:\Users\Administrator\Desktop\项目\agentcut")
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SRC_W, SRC_H = 320, 180
SECONDS = 2.0
TONE = 440.0
FILTER = f"color=c=0xFF00FF:s={SRC_W}x{SRC_H}:r=30:d={SECONDS}"
# 29.97 的一帧是多少 tick：这条除法在这台机器上是准的（70_560_000 × 1001 ÷ 30000）。
DROP_FRAME = T * 1001 // 30000
TC = "01:02:03:04"
DROP = "01:02:03;04"


def run(args, timeout=900):
    return subprocess.run(
        args, capture_output=True, check=True, timeout=timeout, creationflags=0x08000000
    )


def source(folder: Path, rate: str = "30", seconds: float = SECONDS) -> Path:
    target = folder / f"tc-source-{rate.replace('/', '-')}.mp4"
    run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-y",
            "-nostdin",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0xFF00FF:s={SRC_W}x{SRC_H}:r={rate}:d={seconds},format=yuv444p",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={TONE}:sample_rate=48000:duration={seconds}",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv444p",
            "-crf",
            "10",
            "-c:a",
            "aac",
            "-t",
            str(seconds),
            str(target),
        ]
    )
    return target


def probe(path: Path, entries: str, stream: str | None = None) -> dict:
    argv = [str(FFPROBE), "-v", "error"]
    if stream:
        argv += ["-select_streams", stream]
    argv += ["-show_entries", entries, "-of", "json", str(path)]
    return json.loads(run(argv).stdout.decode())


def tags_of(path: Path) -> dict:
    """Every place a timecode could live in this file, flattened to one lookup."""
    found = {}
    stream = probe(path, "stream=index:stream_tags", "v:0" if path.suffix != ".mp3" else "a:0")
    for tag in stream.get("streams", [{}])[0].get("tags", {}) or {}:
        found[str(tag).lower()] = str(stream["streams"][0]["tags"][tag])
    fmt = probe(path, "format_tags")
    for tag, value in (fmt.get("format", {}).get("tags", {}) or {}).items():
        found[str(tag).lower()] = str(value)
    return found


def wait(client: TestClient, job_id: str) -> dict:
    status: dict = {}
    for _ in range(1200):
        status = client.get("/v1/jobs/" + job_id).json()
        if status["job"]["status"] in {"succeeded", "failed", "cancelled"}:
            break
    return status


def render(client: TestClient, path: str, body: dict) -> dict:
    response = client.post(path + "/renders", json=body)
    assert response.status_code == 200, response.text
    summary = wait(client, response.json()["job"]["id"])["job"]
    assert summary["status"] == "succeeded", summary
    assert summary["output_checked"] is True, summary
    return summary


def contract_suite() -> None:
    r30 = FrameRate(numerator=30, denominator=1)
    r2997 = FrameRate(numerator=30000, denominator=1001)
    r5994 = FrameRate(numerator=60000, denominator=1001)
    r25 = FrameRate(numerator=25, denominator=1)

    assert timecode_frames(r30) == 30 and timecode_frames(r2997) == 30, "帧号上限来自这条率本身"
    assert timecode_frames(r25) == 25
    # 合法的那些原样通过——不是「被改写后差不多」。
    for value, rate in (
        (TC, r30),
        ("23:59:59:29", r30),
        (DROP, r2997),
        (DROP, r5994),
        ("00:00:00:24", r25),
    ):
        assert checked_timecode(value, rate) == value, (value, rate)
    assert checked_timecode(None, r30) is None, "没要就该是没要"

    # 这些是实测 FFmpeg 会收下并**悄悄改写**的写法：引擎必须拒，而不是替它兜。
    refused = {
        "01:60:00:00": "分钟",  # FFmpeg 写成 02:00:00:00
        "24:00:00:00": "小时",
        "01:02:03:30": "帧号",  # 30 fps 上没有第 30 帧
        "01:02:03.04": "两位数字",  # FFmpeg 把点当丢帧，写成 01:02:03;04
        "1:2:3:4": "两位数字",  # 一位数字，FFmpeg 照收
        "01:02:03:04:05": "两位数字",
        "010203": "两位数字",
        "": "两位数字",
        DROP: "丢帧",  # 整数 30 上分号没有定义，FFmpeg 照样写进 mov
    }
    for value, reason in refused.items():
        try:
            checked_timecode(value, r30)
        except Exception as error:  # noqa: BLE001 - the code and the reason are the assertion
            assert error.code == "TIMECODE_INVALID", (value, error.code)
            assert reason in error.message, (value, error.message)
            assert error.status == 422, error.status
        else:
            raise AssertionError(f"{value!r} 被收下了，FFmpeg 会替人改写成别的东西")

    # 能力表把同一组常量下发出去，界面不许自己再认一遍标准。
    from agentcut.contracts import capabilities

    caps = capabilities(media_ready=True)
    assert caps["timecode_shape"] == "HH:MM:SS:FF", caps["timecode_shape"]
    assert [list(item) for item in ((30000, 1001), (60000, 1001))] == caps["timecode_drop_rates"], (
        caps
    )
    example = checked_timecode("01:00:00:00", r30)
    assert example == "01:00:00:00", example

    byid = {item["id"]: item for item in render_presets()}
    plain = output_args(byid["h264-source-quality"], 48_000, 30.0)
    asked = output_args(byid["h264-source-quality"], 48_000, 30.0, timecode=TC)
    assert asked == plain + ["-timecode", TC], (plain[-2:], asked[-4:])
    assert "-timecode" not in plain, "没要的时候参数一个字都不许多"
    for name in ("audio-mp3", "audio-wav", "audio-flac"):
        try:
            output_args(byid[name], 48_000, 30.0, timecode=TC)
        except Exception as error:  # noqa: BLE001
            assert error.code == "TIMECODE_NEEDS_PICTURE", (name, error.code)
        else:
            raise AssertionError(f"{name} 接了一个根本没有画面的时间码")

    # 旧任务文档里没有这一行，读回来必须是 None，而不是报错。
    old_document = {
        "id": "j1",
        "project_id": "p1",
        "revision": 1,
        "preset_id": "h264-1080p",
        "filename": "a.mp4",
        "status": "queued",
    }
    assert RenderJob.model_validate(old_document).timecode is None, "旧任务读不回来"

    # 拒绝这一层不许有第二条实现：HTTP 与 MCP 都只把那串字交给同一处校验。
    api_src = (ROOT / "src/agentcut/http_api.py").read_text(encoding="utf-8")
    block = api_src[api_src.index("def render_plan") : api_src.index("def master_loudness")]
    assert "timecode=timecode" in block, block[:400]
    assert "checked_timecode" not in api_src, "HTTP 层自己判了一遍时间码"
    mcp_src = (ROOT / "src/agentcut/mcp_server.py").read_text(encoding="utf-8")
    tool = mcp_src[mcp_src.index("async def render_plan") : mcp_src.index("async def render_start")]
    assert "quote(timecode" in tool, "分号没被百分号编码，API 收到的就不是那串时间码"
    print(
        "   九种写法被拒（每一种都是实测 FFmpeg 会收下的），三种带画面的 argv 各多 -timecode 一对"
    )


def media_suite(folder: Path) -> None:
    media = MediaService(folder / "tc-db.sqlite3", [folder], folder / "tc-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "tc-api.sqlite3", FFMPEG, folder / "exports", [folder / "exports", folder]
    )
    runtime.ensure_worker()
    token = "tccheck" + "e" * 57
    app = create_app(folder / "tc-api.sqlite3", token, media=media, jobs=runtime)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        clip = source(folder)
        probe_body = client.post("/v1/media/import", json={"path": str(clip)}).json()
        created = client.post(
            "/v1/projects",
            json={
                "request_id": "tc-new",
                "name": "时间码母版",
                "settings": {
                    "width": SRC_W,
                    "height": SRC_H,
                    "frame_rate": {"numerator": 30, "denominator": 1},
                },
            },
        ).json()["project"]
        path = f"/v1/projects/{created['id']}"
        seeded = client.post(
            path + "/edits",
            json={
                "request_id": "tc-seed",
                "expected_revision": 0,
                "commands": [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                    {
                        "op": "asset.import",
                        "asset_id": "a",
                        "label": "a",
                        "probe_id": probe_body["id"],
                        "verified": probe_body["verified"],
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "c",
                            "asset_id": "a",
                            "track_id": "v",
                            "position_ticks": 0,
                            "duration_ticks": int(SECONDS * T),
                        },
                    },
                ],
            },
        )
        assert seeded.status_code == 200, seeded.text
        revision = seeded.json()["project"]["revision"]

        # ---- 干跑先答，再谈落盘
        dry = client.get(path + f"/render-plan?preset_id=prores-422hq&timecode={TC}").json()
        assert dry["plan"]["timecode"] == TC, dry["plan"]
        # argv 最后一项是输出路径，那一对参数在它前面。
        assert dry["argv_preview"][-3:-1] == ["-timecode", TC], dry["argv_preview"][-4:]
        none = client.get(path + "/render-plan?preset_id=prores-422hq").json()
        assert none["plan"]["timecode"] is None, none["plan"]
        assert "-timecode" not in none["argv_preview"], none["argv_preview"][-4:]
        bad = client.get(path + "/render-plan?preset_id=prores-422hq&timecode=01%3A60%3A00%3A00")
        assert bad.status_code == 422, bad.text
        assert bad.json()["error"]["code"] == "TIMECODE_INVALID", bad.text
        assert "分钟" in bad.json()["error"]["message"], bad.text

        # ---- 四个容器，各自把它写在各自的位置
        wanted = {
            "prores-422hq": ("mov", "同一份时间码.mov"),
            "h264-source-quality": ("mp4", "同一份时间码.mp4"),
            "vp9-1080p-web": ("webm", "同一份时间码.webm"),
            "mxf-prores-422hq": ("mxf", "同一份时间码.mxf"),
        }
        read_back: dict[str, str] = {}
        for index, (preset_id, (container, name)) in enumerate(wanted.items()):
            summary = render(
                client,
                path,
                {
                    "request_id": f"tc-ship-{index}",
                    "expected_revision": revision,
                    "preset_id": preset_id,
                    "filename": name,
                    "timecode": TC,
                },
            )
            assert summary["timecode"] == TC, summary
            out = Path(summary["output_path"])
            assert out.suffix == f".{container}", out
            tags = tags_of(out)
            assert "timecode" in tags, (container, tags)
            assert tags["timecode"] == TC, (container, tags["timecode"])
            read_back[container] = tags["timecode"]
        print(
            "   mov/mp4 写在流标签、mxf/webm 写在容器标签（webm 那个键是大写 TIMECODE）——"
            f"四个文件读回来都是 {TC}"
        )

        # ---- 没有画面的那一条：拒，且不写文件、不涨 revision、不排队
        before = client.get(path).json()["revision"]
        jobs_before = client.get(path + "/jobs?limit=50").json()["jobs"]
        refused_audio = client.post(
            path + "/renders",
            json={
                "request_id": "tc-audio",
                "expected_revision": revision,
                "preset_id": "audio-mp3",
                "filename": "口播.mp3",
                "timecode": TC,
            },
        )
        assert refused_audio.status_code == 422, refused_audio.text
        assert refused_audio.json()["error"]["code"] == "TIMECODE_NEEDS_PICTURE", refused_audio.text
        assert client.get(path).json()["revision"] == before, "一次拒绝写了状态"
        assert client.get(path + "/jobs?limit=50").json()["jobs"] == jobs_before, refused_audio.text

        # ---- 整数 30 上的丢帧码：FFmpeg 会照写，引擎必须拒
        control = folder / "ffmpeg-says-yes.mov"
        run(
            [
                str(FFMPEG),
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                FILTER,
                "-c:v",
                "libx264",
                "-crf",
                "20",
                "-timecode",
                DROP,
                str(control),
            ]
        )
        naive = tags_of(control).get("timecode")
        assert naive == DROP, (naive, "这台机器上的 FFmpeg 实测会把整数 30 的丢帧码照写")
        refused_drop = client.post(
            path + "/renders",
            json={
                "request_id": "tc-drop",
                "expected_revision": revision,
                "preset_id": "h264-source-quality",
                "filename": "不该有的丢帧.mp4",
                "timecode": DROP,
            },
        )
        assert refused_drop.status_code == 422, refused_drop.text
        assert refused_drop.json()["error"]["code"] == "TIMECODE_INVALID", refused_drop.text
        assert "丢帧" in refused_drop.json()["error"]["message"], refused_drop.text
        print(
            f"   对照实验：同一个 FFmpeg 直接把 {DROP} 写进了 30fps 的 mov（读回 {naive}），"
            "而引擎把这一条拒了"
        )

        # ---- 29.97 的工程：丢帧码在这儿本来就有定义，必须能写进去并读回来
        clip2997 = source(folder, "30000/1001", 3.0)
        probe2 = client.post("/v1/media/import", json={"path": str(clip2997)}).json()
        second = client.post(
            "/v1/projects",
            json={
                "request_id": "tc-new2",
                "name": "29.97 丢帧",
                "settings": {
                    "width": SRC_W,
                    "height": SRC_H,
                    "frame_rate": {"numerator": 30000, "denominator": 1001},
                },
            },
        ).json()["project"]
        p2 = f"/v1/projects/{second['id']}"
        seeded2 = client.post(
            p2 + "/edits",
            json={
                "request_id": "tc-seed2",
                "expected_revision": 0,
                "commands": [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                    {
                        "op": "asset.import",
                        "asset_id": "a",
                        "label": "a",
                        "probe_id": probe2["id"],
                        "verified": probe2["verified"],
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "c",
                            "asset_id": "a",
                            "track_id": "v",
                            "position_ticks": 0,
                            "duration_ticks": 60 * DROP_FRAME,
                        },
                    },
                ],
            },
        )
        assert seeded2.status_code == 200, seeded2.text
        rev2 = seeded2.json()["project"]["revision"]
        dropped = render(
            client,
            p2,
            {
                "request_id": "tc-ship-drop",
                "expected_revision": rev2,
                "preset_id": "h264-source-quality",
                "filename": "丢帧母版.mp4",
                "timecode": DROP,
            },
        )
        assert tags_of(Path(dropped["output_path"]))["timecode"] == DROP, dropped
        print(f"   29.97 的工程写出并读回 {DROP}，一个字没改")

        # ---- 时间码是请求的一部分，不是装饰
        flipped = client.post(
            p2 + "/renders",
            json={
                "request_id": "tc-ship-drop",
                "expected_revision": rev2,
                "preset_id": "h264-source-quality",
                "filename": "丢帧母版.mp4",
                "timecode": "02:00:00:00",
            },
        )
        assert flipped.status_code == 409, flipped.text
        assert flipped.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT", flipped.text
        replayed = client.post(
            p2 + "/renders",
            json={
                "request_id": "tc-ship-drop",
                "expected_revision": rev2,
                "preset_id": "h264-source-quality",
                "filename": "丢帧母版.mp4",
                "timecode": DROP,
            },
        )
        assert replayed.status_code == 200, replayed.text
        assert replayed.json()["job"]["id"] == dropped["id"], replayed.json()["job"]

        # ---- 批量：每一项自己的时间码，dry_run 先说话
        batch = client.post(
            path + "/renders/batch",
            json={
                "request_id": "tc-batch",
                "expected_revision": revision,
                "dry_run": True,
                "items": [
                    {"preset_id": "prores-422hq", "filename": "a.mov", "timecode": TC},
                    {"preset_id": "prores-422hq", "filename": "b.mov"},
                ],
            },
        )
        assert batch.status_code == 200, batch.text
        flags = [item["timecode"] for item in batch.json()["jobs"]]
        assert flags == [TC, None], flags
        plans = [item["timecode"] for item in batch.json()["plans"]]
        assert plans == [TC, None], plans

        # ---- MCP：拼出去的 query 就是 API 认的那串字（分号必须百分号编码）
        server = create_mcp("http://127.0.0.1:1", token)
        tools = {item.name: item for item in server._tool_manager.list_tools()}
        captured: list[tuple[str, str]] = []

        async def spy(method, api_path, payload=None, timeout=60):
            captured.append((method, api_path))
            return {"ok": True}

        fn = tools["render_plan"].fn
        assert "call" in fn.__code__.co_freevars, fn.__code__.co_freevars
        fn.__closure__[fn.__code__.co_freevars.index("call")].cell_contents = spy
        import asyncio

        asyncio.run(
            fn(project_id=created["id"], preset_id="prores-422hq", revision=revision, timecode=TC)
        )
        plain = captured[-1][1]
        # 整串都百分号编码（冒号也是），API 那边解出来的还是同一串字——下面真的发一次去证明。
        assert "timecode=01%3A02%3A03%3A04" in plain, plain
        answered = client.get(
            f"/v1/projects/{created['id']}/render-plan?" + plain.split("?", 1)[1]
        ).json()
        assert answered["plan"]["timecode"] == TC, answered
        # 分号那一条要百分号编码，且只能在真用得上它的那条时间线上问——29.97 的那个工程。
        asyncio.run(
            fn(
                project_id=second["id"],
                preset_id="h264-source-quality",
                revision=rev2,
                timecode=DROP,
            )
        )
        built = captured[-1][1]
        assert "timecode=01%3A02%3A03%3B04" in built, built
        assert ";" not in built.split("timecode=", 1)[1], built
        dropped_answer = client.get(
            f"/v1/projects/{second['id']}/render-plan?" + built.split("?", 1)[1]
        ).json()
        assert dropped_answer["plan"]["timecode"] == DROP, dropped_answer
        print(f"   MCP 拼出 {built.split('timecode=')[1]}，分号编码过，API 按同一串答")


def main() -> None:
    import tempfile

    contract_suite()
    with tempfile.TemporaryDirectory(prefix="agentcut-tc-") as scratch:
        media_suite(Path(scratch))
    print(
        "PASS: 起始时间码由引擎判规矩（九种实测 FFmpeg 会收下的写法被点名拒掉），"
        "mov／mp4／mxf／webm 四个容器各按自己真正存放的位置读回同一串字，"
        "没有画面的交付拒收时间码且不写状态，29.97 上丢帧码照样落盘"
    )


if __name__ == "__main__":
    main()
