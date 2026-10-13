"""交付帧率是一张闭表：同一条时间线可以交成另一档率，表外一律拒，规矩只有一处实现。

要交出去的东西常常不是给自己看的：PAL 机房要 25、NTSC 交 29.97、胶片感要 24／23.976、
高帧率要 50／59.94／60。时间线的时钟是 TIMEBASE，交付率与它不同才有意义——`fps=` 那一级
负责重采样，GOP 的秒数按交付率算，而片段位置、标记区间与遮罩仍按时间线自己的 tick 走。

这里钉住的是四件事，每件都读实际产物：

1. 表是一张闭表。`30000/1000`（数值上就是 30）、`23976/1000`（数值上就是 23.976）这种
   「差不多」的写法必须拒：它们与表里那两条不是同一个有理数，落地的文件也就不是同一个率。
2. 计划里两个率各说各的：`frame_rate` 是交付的率，`project_frame_rate` 是时间线自己的率。
   只留空（不选）时计划与 1.138 之前逐字相同——新字段不许改动没用它的人。
3. 真实导出的文件读回来就是这个率：`avg_frame_rate` 等于选的那一档，帧数等于「时长 × 率」
   （容差一帧），而时长本身不因为重采样被拉长或剪短。
4. 排队时选的率跟着任务走：worker 到点重编计划写的还是同一个率；不同率的两次请求是两份任务
   （幂等指纹带着它），一次拒绝不写状态、不涨 revision、不排队。
"""

import asyncio
import json
import subprocess
import time
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import (
    OUTPUT_FRAME_RATES,
    EditorError,
    FrameRate,
    Project,
    RenderJob,
    capabilities,
    checked_output_rate,
    parse_frame_rate,
    render_presets,
)
from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app
from agentcut.jobs import JobRuntime
from agentcut.mcp_server import create_mcp
from agentcut.media import MediaService
from agentcut.render import compile_render_plan, output_args

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
SRC_W, SRC_H = 320, 180
SECONDS = 2.0
PRESET = "h264-1080p"
FRAME30 = T // 30


def run(args, timeout=900):
    return subprocess.run(
        args, capture_output=True, check=True, timeout=timeout, creationflags=0x08000000
    )


def source(folder: Path) -> Path:
    """30 fps 的彩条源：两秒整，60 帧，读回来没有含糊。"""
    target = folder / "or-source.mp4"
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
            f"color=c=0x336699:s={SRC_W}x{SRC_H}:r=30:d={SECONDS}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=48000:duration={SECONDS}",
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-t",
            str(SECONDS),
            str(target),
        ]
    )
    return target


def stream_stats(path: Path) -> dict:
    payload = json.loads(
        run(
            [
                str(FFPROBE),
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=avg_frame_rate,nb_frames,duration:stream_tags=timecode",
                "-of",
                "json",
                str(path),
            ]
        ).stdout.decode()
    )
    return payload["streams"][0]


def wait(client: TestClient, job_id: str) -> dict:
    deadline = time.time() + 600
    while time.time() < deadline:
        job = client.get(f"/v1/jobs/{job_id}").json()["job"]
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.4)
    raise AssertionError(f"任务 {job_id} 没有到点")


def render(client: TestClient, path: str, body: dict) -> dict:
    response = client.post(path + "/renders", json=body)
    assert response.status_code == 200, response.text
    job = wait(client, response.json()["job"]["id"])
    assert job["status"] == "succeeded", job
    assert job["output_checked"] is True, job
    return job


def refused_rate(numerator: int, denominator: int) -> str:
    try:
        checked_output_rate(FrameRate(numerator=numerator, denominator=denominator))
    except EditorError as error:
        assert error.code == "UNKNOWN_OUTPUT_RATE", (numerator, denominator, error.code)
        assert error.status == 422, error.status
        return error.message
    raise AssertionError(f"{numerator}/{denominator} 被收下了，它不在这张表上")


def contract_suite() -> None:
    # 表内每一档都原样通过，不是「差不多」。
    assert checked_output_rate(None) is None, "留空就是跟时间线一致"
    for numerator, denominator, label in OUTPUT_FRAME_RATES:
        rate = checked_output_rate(FrameRate(numerator=numerator, denominator=denominator))
        assert rate is not None and (rate.numerator, rate.denominator) == (numerator, denominator)
        assert str(numerator / denominator).startswith(label[:2]), (label, numerator, denominator)

    # 数值相等而有理数不同的写法：表外。这些是最容易被「我以为一样」骗过去的一批。
    near = {
        (30_000, 1_000): "30000/1000",
        (23_976, 1_000): "23976/1000",
        (29_970, 1_000): "29970/1000",
        (59_940, 1_000): "59940/1000",
        (48, 1): "48",
        (25, 2): "25/2",
        (1, 1): "1",
        (120, 1): "120",
    }
    for pair, name in near.items():
        message = refused_rate(*pair)
        assert "23.976" in message and "59.94" in message, message
    print(f"   八档表内原样通过，{len(near)} 档表外被点名拒掉（含数值相同而有理数不同的四种）")

    # 文本形状：query 与文本框只能带字符串。
    assert parse_frame_rate(None) is None and parse_frame_rate("") is None
    assert parse_frame_rate("   ") is None
    assert parse_frame_rate(" 25 ") == FrameRate(numerator=25, denominator=1)
    assert parse_frame_rate("25/1") == FrameRate(numerator=25, denominator=1)
    assert parse_frame_rate("30000/1001") == FrameRate(numerator=30_000, denominator=1_001)
    shapes = {
        "25.000": "形状",
        "abc": "形状",
        "1/2/3": "形状",
        "25/0": "表",
        "0/1": "表",
        "300000/1": "表",
        "48": "表",
        "-25": "形状",
    }
    for text, reason in shapes.items():
        try:
            parse_frame_rate(text)
        except EditorError as error:
            assert error.code == "UNKNOWN_OUTPUT_RATE", (text, error.code)
            if reason == "形状":
                assert "分子/分母" in error.message, (text, error.message)
        else:
            raise AssertionError(f"{text!r} 被收下了")
    print(f"   文本形状 {len(shapes)} 种写法全部拒掉，空值等于「跟时间线一致」")

    # 能力表下发的是同一张表，界面不许再列一份。
    caps = capabilities(media_ready=True)
    assert caps["output_frame_rates"] == [
        {"numerator": n, "denominator": d, "label": label} for n, d, label in OUTPUT_FRAME_RATES
    ], caps["output_frame_rates"]

    # 编码参数这一层：换了率只动「一秒几帧」派生出来的那两条，别的一个字不动。
    byid = {item["id"]: item for item in render_presets()}
    plain = output_args(byid[PRESET], 48_000, 30.0)
    at25 = output_args(byid[PRESET], 48_000, 25.0, delivery_rate=FrameRate(numerator=25))
    assert plain[plain.index("-g") + 1] == "60", plain[-8:]
    assert at25[at25.index("-g") + 1] == "50", at25[-8:]
    assert at25[at25.index("-keyint_min") + 1] == "25", at25[-8:]
    assert len(plain) == len(at25), "换率多写或少写了参数"

    # 一条纯音频交付：帧率无处生效，必须像时间码那样拒，而不是收下后什么也不改。
    for name in ("audio-mp3", "audio-wav", "audio-flac"):
        try:
            output_args(byid[name], 48_000, 30.0, delivery_rate=FrameRate(numerator=25))
        except EditorError as error:
            assert error.code == "OUTPUT_RATE_NEEDS_PICTURE", (name, error.code)
            assert "画面" in error.message, (name, error.message)
        else:
            raise AssertionError(f"{name} 收下了一个根本没有画面的帧率")
        assert "-vn" in output_args(byid[name], 48_000, 30.0), "不选的时候那条还是原样"
    print("   纯音频那三条照样拒（-vn 那条不选时一字不变），带画面的 GOP 从 60 变 50")

    # 旧任务文档里没有这一行，读回来必须是 None，而不是报错。
    old = {
        "id": "j1",
        "project_id": "p1",
        "revision": 1,
        "preset_id": PRESET,
        "filename": "a.mp4",
        "status": "queued",
    }
    assert RenderJob.model_validate(old).output_frame_rate is None, "旧任务读不回来"
    assert RenderJob.model_validate(
        {**old, "output_frame_rate": {"numerator": 25, "denominator": 1}}
    ).output_frame_rate == FrameRate(numerator=25, denominator=1)

    # 拒绝这一层不许有第二条实现：HTTP 与 MCP 只把字符串交给同一处校验。
    api_src = (ROOT / "src/agentcut/http_api.py").read_text(encoding="utf-8")
    assert "parse_frame_rate(output_fps)" in api_src, "HTTP 层没把率交给那一处校验"
    assert "OUTPUT_FRAME_RATES" not in api_src, "HTTP 层自己又列了一份表"
    assert "29.97" not in api_src and "23.976" not in api_src, "HTTP 层写死了某一档"
    mcp_src = (ROOT / "src/agentcut/mcp_server.py").read_text(encoding="utf-8")
    tool = mcp_src[mcp_src.index("async def render_plan") : mcp_src.index("async def render_start")]
    assert "quote(output_fps" in tool, "query 里的分子/分母没编码"
    assert "OUTPUT_FRAME_RATES" not in mcp_src, "MCP 层自己又列了一份表"


def media_suite(folder: Path) -> None:
    media = MediaService(folder / "or-db.sqlite3", [folder], folder / "or-cache", FFMPEG, FFPROBE)
    runtime = JobRuntime(
        folder / "or-api.sqlite3", FFMPEG, folder / "exports", [folder / "exports", folder]
    )
    runtime.ensure_worker()
    token = "orcheck" + "e" * 57
    app = create_app(folder / "or-api.sqlite3", token, media=media, jobs=runtime)
    with TestClient(
        app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
    ) as client:
        clip = source(folder)
        probe_body = client.post("/v1/media/import", json={"path": str(clip)}).json()
        created = client.post(
            "/v1/projects",
            json={
                "request_id": "or-new",
                "name": "交付帧率",
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
                "request_id": "or-seed",
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
                            "duration_ticks": 60 * FRAME30,
                        },
                    },
                ],
            },
        )
        assert seeded.status_code == 200, seeded.text
        revision = seeded.json()["project"]["revision"]

        # ---- 计划层：两个率各说各的，且留空时逐字不变
        base = client.get(f"{path}/render-plan?preset_id={PRESET}&revision={revision}").json()
        assert base["plan"]["frame_rate"] == "30/1", base["plan"]
        assert base["plan"]["project_frame_rate"] == "30/1", base["plan"]
        assert base["argv_preview"][base["argv_preview"].index("-g") + 1] == "60", base[
            "argv_preview"
        ][-12:]

        asked = client.get(
            f"{path}/render-plan?preset_id={PRESET}&revision={revision}&output_fps=25"
        ).json()
        assert asked["plan"]["frame_rate"] == "25/1", asked["plan"]
        assert asked["plan"]["project_frame_rate"] == "30/1", "把时间线自己的率也改了"
        assert asked["argv_preview"][asked["argv_preview"].index("-g") + 1] == "50", asked[
            "argv_preview"
        ][-12:]
        slow = client.get(
            f"{path}/render-plan?preset_id={PRESET}&revision={revision}&output_fps=30000%2F1001"
        ).json()
        assert slow["plan"]["frame_rate"] == "30000/1001", slow["plan"]

        bad = client.get(f"{path}/render-plan?preset_id={PRESET}&output_fps=48")
        assert bad.status_code == 422, bad.text
        assert bad.json()["error"]["code"] == "UNKNOWN_OUTPUT_RATE", bad.text
        assert "29.97" in bad.json()["error"]["message"], bad.text

        # 计划文档只带摘要，滤镜链在编译产物里：直接编一次同一处编译，读它真正交出去的那几条链。
        project = Project.model_validate(client.get(path).json())
        plain = compile_render_plan(project, PRESET)
        at25 = compile_render_plan(project, PRESET, output_frame_rate=FrameRate(numerator=25))
        assert [line for line in plain.filters if "fps=30/1" in line], plain.filters[:2]
        assert not [line for line in at25.filters if "fps=30/1" in line], at25.filters[:2]
        assert [line for line in at25.filters if "fps=25/1" in line], at25.filters[:2]
        assert len(plain.filters) == len(at25.filters), "换率改的不只是重采样那一级"
        assert plain.input_args == at25.input_args, "换率动了输入"
        print(
            f"   {len(plain.filters)} 条滤镜链从 fps=30/1 换成 fps=25/1，"
            f"节点数与输入参数一字不差（{len(plain.input_args)} 项输入）"
        )

        # ---- 真实导出：文件读回来就是选的那一档
        wanted = {None: ("30/1", 60), "25": ("25/1", 50), "24000/1001": ("24000/1001", 48)}
        measured: dict[str, tuple[str, int, float]] = {}
        shipped: dict[str, str] = {}
        for index, (fps, (expect_rate, expect_frames)) in enumerate(wanted.items()):
            body = {
                "request_id": f"or-ship-{index}",
                "expected_revision": revision,
                "preset_id": PRESET,
                "filename": f"交付-{(fps or '30').replace('/', '-')}.mp4",
            }
            if fps:
                numerator, _, denominator = fps.partition("/")
                body["output_frame_rate"] = {
                    "numerator": int(numerator),
                    "denominator": int(denominator or 1),
                }
            job = render(client, path, body)
            stats = stream_stats(Path(job["output_path"]))
            frames = int(stats["nb_frames"])
            duration = float(stats["duration"])
            assert stats["avg_frame_rate"] == expect_rate, (fps, stats)
            assert abs(frames - expect_frames) <= 1, (fps, frames, expect_frames)
            assert abs(duration - SECONDS) <= 1.0 / 24.0, (fps, duration)
            measured[fps or "none"] = (stats["avg_frame_rate"], frames, duration)
            shipped[fps or "none"] = job["id"]
            # 任务带着它，worker 重编的计划的也是它。
            assert job["output_frame_rate"] == body.get("output_frame_rate"), job
        print(
            "   同一条两秒时间线交三版，读回来 "
            + "、".join(
                f"{key}→{value[0]} {value[1]}帧 {value[2]:.3f}s" for key, value in measured.items()
            )
        )

        # ---- 幂等指纹带着这个率：同一个 request_id 换一个率必须冲突
        again = render(
            client,
            path,
            {
                "request_id": "or-ship-1",
                "expected_revision": revision,
                "preset_id": PRESET,
                "filename": "交付-25.mp4",
                "output_frame_rate": {"numerator": 25, "denominator": 1},
            },
        )
        assert again["id"] == shipped["25"], (again["id"], shipped)
        assert again["output_frame_rate"] == {"numerator": 25, "denominator": 1}, again
        queued = client.post(
            path + "/renders",
            json={
                "request_id": "or-50",
                "expected_revision": revision,
                "preset_id": PRESET,
                "filename": "交付-50.mp4",
                "output_frame_rate": {"numerator": 50, "denominator": 1},
            },
        ).json()["job"]
        waited = wait(client, queued["id"])
        assert waited["status"] == "succeeded", waited
        assert stream_stats(Path(waited["output_path"]))["avg_frame_rate"] == "50/1", waited
        clash = client.post(
            path + "/renders",
            json={
                "request_id": "or-50",
                "expected_revision": revision,
                "preset_id": PRESET,
                "filename": "交付-50.mp4",
                "output_frame_rate": {"numerator": 25, "denominator": 1},
            },
        )
        assert clash.status_code == 409, clash.text
        assert clash.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT", clash.text
        print("   同一 request_id 重放拿回同一份任务；把率从 50 改成 25 得到 409，不是悄悄重放")

        # ---- 批量：两条各留各的答案（界面「附带竖屏」与方案走的正是这条路）
        batch = client.post(
            path + "/renders/batch",
            json={
                "request_id": "or-batch",
                "expected_revision": revision,
                "items": [
                    {
                        "preset_id": PRESET,
                        "filename": "批量-25.mp4",
                        "fit": "contain",
                        "output_frame_rate": {"numerator": 25, "denominator": 1},
                    },
                    {"preset_id": PRESET, "filename": "批量-30.mp4", "fit": "contain"},
                ],
            },
        )
        assert batch.status_code == 200, batch.text
        rates = [item.get("output_frame_rate") for item in batch.json()["jobs"]]
        assert rates == [{"numerator": 25, "denominator": 1}, None], rates
        planned = [item.get("frame_rate") for item in batch.json()["plans"]]
        assert planned == ["25/1", "30/1"], planned
        landed = []
        for item in batch.json()["jobs"]:
            done = wait(client, item["id"])
            assert done["status"] == "succeeded", done
            landed.append(
                (
                    Path(done["output_path"]).name,
                    stream_stats(Path(done["output_path"]))["avg_frame_rate"],
                )
            )
        assert sorted(landed) == [("批量-25.mp4", "25/1"), ("批量-30.mp4", "30/1")], landed
        print(
            f"   一次批量两份文件：{landed[0][0]} 读回 {landed[0][1]}、"
            f"{landed[1][0]} 读回 {landed[1][1]}"
        )

        # ---- MCP：拼出去的 query 就是 API 认的那串字（分子/分母那道斜杠必须编码）
        server = create_mcp("http://127.0.0.1:1", token)
        tools = {item.name: item for item in server._tool_manager.list_tools()}
        captured: list[tuple[str, str]] = []

        async def spy(method, api_path, payload=None, timeout=60):
            captured.append((method, api_path))
            return {"ok": True}

        fn = tools["render_plan"].fn
        assert "call" in fn.__code__.co_freevars, fn.__code__.co_freevars
        fn.__closure__[fn.__code__.co_freevars.index("call")].cell_contents = spy
        asyncio.run(
            fn(
                project_id=created["id"],
                preset_id=PRESET,
                revision=revision,
                output_fps="30000/1001",
            )
        )
        built = captured[-1][1]
        assert "output_fps=30000%2F1001" in built, built
        answered = client.get(f"{path}/render-plan?" + built.split("?", 1)[1]).json()
        assert answered["plan"]["frame_rate"] == "30000/1001", answered
        print(f"   MCP 拼出 {built.split('output_fps=')[1]}，斜杠编码过，API 按同一个率答")

        # ---- 表外的率：拒，且不写状态、不涨 revision、不排队
        before = client.get(path).json()["revision"]
        jobs_before = client.get(path + "/jobs?limit=50").json()["jobs"]
        refused = client.post(
            path + "/renders",
            json={
                "request_id": "or-bad",
                "expected_revision": revision,
                "preset_id": PRESET,
                "filename": "交不出的.mp4",
                "output_frame_rate": {"numerator": 48, "denominator": 1},
            },
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["error"]["code"] == "UNKNOWN_OUTPUT_RATE", refused.text
        assert client.get(path).json()["revision"] == before, "一次拒绝写了状态"
        assert client.get(path + "/jobs?limit=50").json()["jobs"] == jobs_before, refused.text
        audio = client.post(
            path + "/renders",
            json={
                "request_id": "or-audio",
                "expected_revision": revision,
                "preset_id": "audio-mp3",
                "filename": "口播.mp3",
                "output_frame_rate": {"numerator": 25, "denominator": 1},
            },
        )
        assert audio.status_code == 422, audio.text
        assert audio.json()["error"]["code"] == "OUTPUT_RATE_NEEDS_PICTURE", audio.text
        assert client.get(path).json()["revision"] == before, "一次拒绝写了状态"
        assert client.get(path + "/jobs?limit=50").json()["jobs"] == jobs_before, audio.text
        print("   48 这一档被拒：没有任务、没有新 revision、文件也没写")
        print("   纯音频那条选 25 也被拒（帧率无处生效，不许收下再什么都不改）")


def main() -> None:
    import tempfile

    contract_suite()
    with tempfile.TemporaryDirectory(prefix="agentcut-or-") as scratch:
        media_suite(Path(scratch))
    print(
        "PASS: 交付帧率是一张八档闭表（30000/1000 这种数值相同而有理数不同的写法照样拒），"
        "计划里交付率与时间线率分开写、留空时与 1.138 之前逐字相同，"
        "同一条两秒时间线交 30／25／23.976 三版都读回自己那一档且时长不变，"
        "率进幂等指纹、进任务文档、表外的拒绝不写状态"
    )


if __name__ == "__main__":
    main()
