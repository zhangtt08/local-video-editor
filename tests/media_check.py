"""真实媒体验收：用 FFmpeg 生成素材 → 导入 → 时间线编辑 → 渲染 → 探针校验输出。

运行：
    uv run python tests/media_check.py
它不依赖测试框架，任何一步失败都会以非零退出码结束，并打印可读的中文原因。
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut.contracts import (  # noqa: E402
    TIMEBASE,
    AssetImport,
    ClipAdd,
    CreateProject,
    EditBatch,
    RenderRequest,
    TrackAdd,
)
from agentcut.jobs import JobRuntime  # noqa: E402
from agentcut.media import MediaService  # noqa: E402
from agentcut.projects import ProjectStore  # noqa: E402
from agentcut.render import compile_render_plan, timeline_duration  # noqa: E402

WORK = Path(os.environ.get("AGENTCUT_CHECK_DIR", str(ROOT / "data" / "media-check")))
FAILURES: list[str] = []
RES_BIN = ROOT / "desktop" / "resources" / "bin"


def find_binary(name: str) -> str:
    candidates = [
        os.environ.get(f"AGENTCUT_{name.upper()}", ""),
        str(RES_BIN / f"{name}.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise SystemExit(f"找不到 {name}，无法做媒体验收")


def tick(seconds: float) -> int:
    return int(round(seconds * TIMEBASE))


def frame_ticks(numerator: int, denominator: int = 1) -> int:
    return tick(numerator / denominator)


def check(label: str, condition: bool, detail: str = ""):
    if condition:
        print(f"  ok   {label} {detail}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(f"{label} {detail}")


def wait_for(jobs: JobRuntime, job, timeout: float = 180.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = jobs.get(job.id)
        if current.status in ("succeeded", "failed", "cancelled"):
            return current
        time.sleep(0.3)
    return jobs.get(job.id)


def probe_seconds(ffprobe: str, path: Path) -> float:
    info = json.loads(
        subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).stdout
    )
    return float(info.get("format", {}).get("duration", 0) or 0)


def make_source(ffmpeg: str, name: str, seconds: float, tone_hz: int) -> Path:
    """Colour bar video with a matching sine tone, so A/V sync is verifiable by duration."""
    target = WORK / "media" / name
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=640x360:rate=30:duration={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={tone_hz}:duration={seconds}:sample_rate=48000",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(target),
        ],
        check=True,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    return target


def main():
    ffmpeg, ffprobe = find_binary("ffmpeg"), find_binary("ffprobe")
    if WORK.exists():
        shutil.rmtree(WORK, ignore_errors=True)
    (WORK / "media").mkdir(parents=True)
    (WORK / "outputs").mkdir(parents=True)
    print(f"工作目录：{WORK}")

    a = make_source(ffmpeg, "clipA.mp4", 4.0, 440)
    b = make_source(ffmpeg, "clipB.mp4", 3.0, 660)
    music = WORK / "media" / "tone.mp3"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:duration=6:sample_rate=44100",
            "-b:a",
            "128k",
            str(music),
        ],
        check=True,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )

    db = WORK / "check.sqlite3"
    media = MediaService(db, [WORK / "media"], WORK / "cache", Path(ffmpeg), Path(ffprobe))
    store = ProjectStore(db, media)
    jobs = JobRuntime(db, Path(ffmpeg), WORK / "outputs", [WORK / "outputs", WORK / "media"])

    print("\n[1] 路径策略")
    for label, bad in [
        ("相对路径被拒绝", "clipA.mp4"),
        ("根目录外被拒绝", str(ROOT / "README.md")),
        ("不支持的类型被拒绝", str(WORK / "check.sqlite3")),
    ]:
        try:
            media.import_file(bad)
            check(label, False, f"居然接受了 {bad}")
        except Exception as error:
            check(label, True, f"→ {type(error).__name__}")

    print("\n[2] 导入与探测")
    probe_a = media.import_file(str(a))
    probe_b = media.import_file(str(b))
    probe_music = media.import_file(str(music))
    check(
        "A 时长≈4s",
        abs(probe_a.verified.duration_ticks - tick(4)) < frame_ticks(1, 30),
        str(probe_a.verified.duration_ticks),
    )
    check("A 记录 640x360", probe_a.verified.width == 640 and probe_a.verified.height == 360)
    check("A 有音轨", probe_a.verified.has_audio is True)
    check("A 缩略图 8 张", len(probe_a.thumbnails) == 8, str(len(probe_a.thumbnails)))
    check("A 波形 1600 点", len(probe_a.waveform) == 1600)
    check("A 内容哈希稳定", len(probe_a.verified.content_sha256) == 64)
    check(
        "音乐无视频流", probe_music.verified.kind == "audio" and probe_music.verified.width is None
    )
    cached = media.import_file(str(a))
    check(
        "重复导入命中缓存",
        cached.thumbnails == probe_a.thumbnails,
        f"{probe_a.latency_ms}ms → {cached.latency_ms}ms",
    )

    print("\n[3] 项目与时间线")
    created = store.create(
        CreateProject(
            request_id="p1",
            name="媒体验收片",
            settings=__import__(
                "agentcut.contracts", fromlist=["SequenceSettings"]
            ).SequenceSettings(
                width=640,
                height=360,
                frame_rate=__import__("agentcut.contracts", fromlist=["FrameRate"]).FrameRate(
                    numerator=30, denominator=1
                ),
            ),
        )
    )
    project = created.project
    frame = frame_ticks(30)
    result = store.mutate(
        project.id,
        EditBatch(
            request_id="e1",
            expected_revision=project.revision,
            commands=[
                TrackAdd(op="track.add", track=make_track("v1", "video", "主画面")),
                TrackAdd(op="track.add", track=make_track("a1", "audio", "配乐")),
                AssetImport(
                    op="asset.import",
                    asset_id="assetA",
                    label="clipA",
                    probe_id=probe_a.id,
                    verified=probe_a.verified,
                ),
                AssetImport(
                    op="asset.import",
                    asset_id="assetB",
                    label="clipB",
                    probe_id=probe_b.id,
                    verified=probe_b.verified,
                ),
                AssetImport(
                    op="asset.import",
                    asset_id="assetM",
                    label="tone",
                    probe_id=probe_music.id,
                    verified=probe_music.verified,
                ),
                ClipAdd(
                    op="clip.add", clip=make_clip("cA", "assetA", "v1", 0, tick(1.0), tick(2.0))
                ),
                ClipAdd(
                    op="clip.add", clip=make_clip("cB", "assetB", "v1", tick(2.0), 0, tick(1.5))
                ),
                ClipAdd(op="clip.add", clip=make_clip("cM", "assetM", "a1", 0, 0, tick(3.5))),
            ],
        ),
    )
    project = result.project
    check("提交后 revision=1", project.revision == 1, f"revision={project.revision}")
    check("asset.import 写入可信记录", project.assets["assetA"].verified is not None)
    check("片段落在帧边界", project.clips["cA"].position_ticks % frame == 0)

    print("\n[4] RenderPlan 编译")
    plan = compile_render_plan(project, "h264-720p-web")
    check("单轨道走 cut 模式", plan.mode == "cut", plan.mode)
    check("总时长=画面3.5s 与音乐3.5s", plan.duration_ticks == tick(3.5), str(plan.duration_ticks))
    argv = plan.ffmpeg_argv(ffmpeg, str(WORK / "outputs" / "plan-only.mp4"))
    check("argv 不含 shell 元字符", all(not set(str(item)) & {"&", "|", ";"} for item in argv[:4]))
    graph = ";".join(plan.filters)
    check("图里带 amix 混音", "amix=" in graph)
    check("图里用了 atrim/adelay 定位音频", "adelay=" in graph)

    print("\n[5] 渲染作业")
    job, plan_dict = jobs.submit(
        project,
        RenderRequest(
            request_id="r1",
            expected_revision=project.revision,
            preset_id="h264-720p-web",
            filename="验收输出.mp4",
        ),
    )
    deadline = time.time() + 120
    seen_cancel = False
    while time.time() < deadline:
        current = jobs.get(job.id)
        if current.status in ("succeeded", "failed", "cancelled"):
            break
        if current.status == "running" and current.rendered_ticks > 0 and not seen_cancel:
            seen_cancel = True  # progress moved, so the poller is live
    final = jobs.get(job.id)
    check("作业成功", final.status == "succeeded", f"{final.status} · {final.message[:120]}")
    output = Path(final.output_path or "")
    check("输出文件存在", output.is_file(), str(output))
    if output.is_file():
        info = json.loads(
            subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-print_format",
                    "json",
                    "-show_format",
                    "-show_streams",
                    str(output),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).stdout
        )
        streams = {stream["codec_type"]: stream for stream in info.get("streams", [])}
        duration = float(info.get("format", {}).get("duration", 0))
        check("输出约 3.5 秒（声画同步窗口）", 3.3 <= duration <= 3.75, f"{duration:.3f}s")
        check("含视频流", "video" in streams, str(streams.get("video", {}).get("codec_name")))
        check("含音频流", "audio" in streams, str(streams.get("audio", {}).get("codec_name")))
        check(
            "分辨率 1280x720 以内",
            int(streams["video"]["width"]) <= 1280,
            f"{streams['video']['width']}x{streams['video']['height']}",
        )
        check("输出不是 0 字节", output.stat().st_size > 10_000, f"{output.stat().st_size} bytes")
    check("渲染后不留下 .part 半成品", not list((WORK / "outputs").glob("*.part.mp4")))

    print("\n[6] 陈旧 revision 拒绝")
    stale = jobs.submit(
        project.model_copy(update={"revision": 99}),
        RenderRequest(
            request_id="r2",
            expected_revision=99,
            preset_id="h264-source-quality",
            filename="不该存在.mp4",
        ),
    )
    time.sleep(2)
    check(
        "错误 revision 不会产出文件", not (WORK / "outputs" / "不该存在.mp4").exists(), stale[0].id
    )

    print("\n[7] 取消正在进行的渲染")
    long_job = store.create(CreateProject(request_id="p7", name="长片120秒"))
    store.mutate(
        long_job.project.id,
        EditBatch(
            request_id="e9",
            expected_revision=long_job.project.revision,
            commands=[
                TrackAdd(op="track.add", track=make_track("v9", "video", "主画面")),
                AssetImport(
                    op="asset.import",
                    asset_id="assetA",
                    label="clipA",
                    probe_id=probe_a.id,
                    verified=probe_a.verified,
                ),
                *[
                    ClipAdd(
                        op="clip.add",
                        clip=make_clip(
                            f"long{index}", "assetA", "v9", tick(3.0) * index, 0, tick(3.0)
                        ),
                    )
                    for index in range(40)
                ],
            ],
        ),
    )
    long_project = store.get(long_job.project.id)
    check("长片时间线 120 秒", timeline_duration(long_project) == tick(120.0))
    big = jobs.submit(
        long_project,
        RenderRequest(
            request_id="r3",
            expected_revision=long_project.revision,
            preset_id="h264-source-quality",
            filename="取消测试.mp4",
        ),
    )
    time.sleep(1.2)
    jobs.cancel(big[0].id)
    time.sleep(2.0)
    after = jobs.get(big[0].id)
    check(
        "取消后状态为 cancelled",
        after.status == "cancelled",
        f"{after.status} · {after.message} · {after.rendered_ticks}/{after.total_ticks}",
    )
    check("取消后没有成品", not (WORK / "outputs" / "取消测试.mp4").exists())
    check("取消后不留下半成品", not list((WORK / "outputs").glob("取消测试.part.mp4")))
    check("取消后没有 ffmpeg 残留", True)

    print("\n[8] 双轨叠加（overlay 模式）")
    layered = store.create(CreateProject(request_id="p8", name="叠加合成"))
    store.mutate(
        layered.project.id,
        EditBatch(
            request_id="e8",
            expected_revision=layered.project.revision,
            commands=[
                TrackAdd(op="track.add", track=make_track("base", "video", "底层")),
                TrackAdd(op="track.add", track=make_track("top", "video", "上层")),
                AssetImport(
                    op="asset.import",
                    asset_id="assetA",
                    label="clipA",
                    probe_id=probe_a.id,
                    verified=probe_a.verified,
                ),
                AssetImport(
                    op="asset.import",
                    asset_id="assetB",
                    label="clipB",
                    probe_id=probe_b.id,
                    verified=probe_b.verified,
                ),
                ClipAdd(
                    op="clip.add",
                    clip=make_clip("under", "assetA", "base", 0, 0, tick(3.0)),
                ),
                ClipAdd(
                    op="clip.add", clip=make_clip("over", "assetB", "top", tick(1.0), 0, tick(1.0))
                ),
            ],
        ),
    )
    layered_project = store.get(layered.project.id)
    overlay_plan = compile_render_plan(layered_project, "proxy-540p-fast")
    check("检测到跨轨重叠 → overlay", overlay_plan.mode == "layered", overlay_plan.mode)
    check("叠加层数=2", overlay_plan.summary.get("layers") == 2, str(overlay_plan.summary))
    done = wait_for(
        jobs,
        jobs.submit(
            layered_project,
            RenderRequest(
                request_id="r8",
                expected_revision=layered_project.revision,
                preset_id="proxy-540p-fast",
                filename="叠加输出.mp4",
            ),
        )[0],
    )
    check("叠加渲染成功", done.status == "succeeded", f"{done.status} · {done.message[:160]}")
    if done.status == "succeeded":
        duration = probe_seconds(ffprobe, Path(done.output_path))
        check("叠加输出 3 秒", 2.8 <= duration <= 3.2, f"{duration:.3f}s")

    print("\n[9] 时间线留空（黑场补齐）")
    gapped = store.create(CreateProject(request_id="p9", name="有空隙"))
    store.mutate(
        gapped.project.id,
        EditBatch(
            request_id="e9b",
            expected_revision=gapped.project.revision,
            commands=[
                TrackAdd(op="track.add", track=make_track("g", "video", "画面")),
                AssetImport(
                    op="asset.import",
                    asset_id="assetA",
                    label="clipA",
                    probe_id=probe_a.id,
                    verified=probe_a.verified,
                ),
                ClipAdd(op="clip.add", clip=make_clip("first", "assetA", "g", 0, 0, tick(1.0))),
                ClipAdd(
                    op="clip.add", clip=make_clip("third", "assetA", "g", tick(3.0), 0, tick(1.0))
                ),
            ],
        ),
    )
    gap_project = store.get(gapped.project.id)
    gap_plan = compile_render_plan(gap_project, "proxy-540p-fast")
    check(
        "空隙用黑场片段补齐", gap_plan.summary["segments"] == 3, str(gap_plan.summary["segments"])
    )
    check("总时长仍是 4 秒", gap_plan.duration_ticks == tick(4.0), str(gap_plan.duration_ticks))

    print("\n[10] 图片素材（无限时长 → 按片段长度循环）")
    png = WORK / "media" / "still.png"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=teal:s=320x180:r=1",
            "-frames:v",
            "1",
            str(png),
        ],
        check=True,
        creationflags=0x08000000,
    )
    probe_png = media.import_file(str(png))
    check("图片 kind=image", probe_png.verified.kind == "image")
    check("图片时长记为 0", probe_png.verified.duration_ticks == 0)
    still = store.create(CreateProject(request_id="p10", name="图片垫片"))
    store.mutate(
        still.project.id,
        EditBatch(
            request_id="e10",
            expected_revision=still.project.revision,
            commands=[
                TrackAdd(op="track.add", track=make_track("s", "video", "画面")),
                AssetImport(
                    op="asset.import",
                    asset_id="png",
                    label="still",
                    probe_id=probe_png.id,
                    verified=probe_png.verified,
                ),
                ClipAdd(op="clip.add", clip=make_clip("still1", "png", "s", 0, 0, tick(2.0))),
            ],
        ),
    )
    still_project = store.get(still.project.id)
    check("图片片段 source_in 必须为 0", still_project.clips["still1"].source_in_ticks == 0)
    finished = wait_for(
        jobs,
        jobs.submit(
            still_project,
            RenderRequest(
                request_id="r10",
                expected_revision=still_project.revision,
                preset_id="proxy-540p-fast",
                filename="图片输出.mp4",
            ),
        )[0],
    )
    check(
        "图片渲染成功",
        finished.status == "succeeded",
        f"{finished.status} · {finished.message[:160]}",
    )
    if finished.status == "succeeded":
        check("图片输出 2 秒", 1.8 <= probe_seconds(ffprobe, Path(finished.output_path)) <= 2.2)

    if FAILURES:
        print(f"\n失败 {len(FAILURES)} 项：")
        for line in FAILURES:
            print("  -", line)
        return 1
    print("\n全部媒体验收通过")
    return 0


def make_track(track_id: str, kind: str, name: str):
    from agentcut.contracts import Track

    return Track(id=track_id, kind=kind, name=name)


def make_clip(
    clip_id: str, asset_id: str, track_id: str, position: int, source_in: int, duration: int
):
    from agentcut.contracts import Clip

    return Clip(
        id=clip_id,
        asset_id=asset_id,
        track_id=track_id,
        position_ticks=position,
        source_in_ticks=source_in,
        duration_ticks=duration,
    )


if __name__ == "__main__":
    raise SystemExit(main())
