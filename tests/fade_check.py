"""淡入淡出是片段两条边上的窗口，不是曲线上的点——1.90 改掉的是三件能量出来的错事。

1.89 及以前，`clip.fade` 把淡写成该属性的关键帧，写之前先把这条曲线整个清掉。于是：

* 点了「淡入」再点「淡出」，淡入没了（实测：先 1 秒淡入得到 `0s=0, 1s=1`，再点淡出只剩
  `5s=1, 6s=0`，前两头一个点都不剩）；
* 在自动闪避过的配乐上点一次淡，闪避写下的六个音量点被清成两个（实测 6→2）；
* 把 6 秒的片段剪到 5 秒，淡出的两个点仍停在 5.0/6.0 秒——片段已经在 5 秒结束，那条淡出落在
  了画面之外（实测 trim 之后 5 秒处的采样是 1.0，也就是根本没淡）。

现在淡存在片段自己身上（`Clip.fade`，两条边各一个窗口），渲染时乘进那条曲线：三条都变成结构
上不可能，而且修剪、分割、挪动都带着淡一起走。这里既测算术（reducer、`sample` 权威、编译出的
表达式、浏览器下发的包络曲线），也测真实成片：音量按 0.1 秒窗取 RMS 与权威逐窗比（差分：除以
同一条时间线不淡的那一遍），画面按像素与「上层全亮 / 只有下层」两遍的实测区间比。
"""

import array
import os
import subprocess
import tempfile
from math import sqrt
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.animation import (
    bezier_parameter,
    bezier_value,
    expression,
    fade_windows,
    preview_manifest,
    sample,
)
from agentcut.contracts import (
    SCHEMA_VERSION,
    Bezier,
    Clip,
    CreateProject,
    EditBatch,
    EditorError,
    FadeEnvelope,
    Keyframe,
    Project,
    SequenceSettings,
    Track,
    VerifiedMedia,
    capabilities,
)
from agentcut.contracts import TIMEBASE as T
from agentcut.http_api import create_app
from agentcut.projects import ProjectStore
from agentcut.render import compile_render_plan
from agentcut.timeline import apply_commands

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
RATE = 48_000
SECONDS = 4
WINDOW = 0.1
# 两头各 1 秒的淡，中间 2 秒平段；窗口边界不落在测点上，测到的就是斜坡本身。
FADE = T
INTERIOR = int(2 * T)
INTERIOR_VALUE = 0.25
TOKEN = "fade-check-" + "a" * 40


def run(args: list[str], timeout: int = 420) -> bytes:
    done = subprocess.run(
        args, capture_output=True, check=True, timeout=timeout, creationflags=0x08000000
    )
    return done.stdout


def slate(folder: Path, name: str, colour: str, tone: bool) -> Path:
    """A solid-colour clip, optionally with a steady 440 Hz tone.

    Level changes in the delivered file are then the curve's, and nothing else.
    """
    target = folder / f"{name}.mp4"
    inputs = ["-f", "lavfi", "-i", f"color=c={colour}:s=160x90:r=30:d={SECONDS}"]
    if tone:
        inputs += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate={RATE}:duration={SECONDS}"]
    run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-y",
            "-nostdin",
            *inputs,
            "-t",
            str(SECONDS),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            *(["-c:a", "aac", "-b:a", "192k"] if tone else ["-an"]),
            str(target),
        ]
    )
    measured = float(
        run(
            [
                str(FFPROBE),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(target),
            ]
        )
        .decode()
        .strip()
    )
    assert abs(measured - SECONDS) < 0.15, f"{name} is {measured}s, not {SECONDS}s"
    return target


def asset(path: Path, asset_id: str, kind: str, tone: bool) -> dict:
    verified = VerifiedMedia.model_validate(
        {
            "probe_id": f"probe-{asset_id}",
            "path": str(path),
            "kind": kind,
            "label": path.stem,
            "size_bytes": path.stat().st_size,
            "content_sha256": "0" * 64,
            "duration_ticks": SECONDS * T,
            "width": 160,
            "height": 90,
            "has_audio": tone,
        }
    )
    return {
        "id": asset_id,
        "kind": kind,
        "label": path.stem,
        "reference": str(path),
        "duration_ticks": SECONDS * T,
        "verified": verified.model_dump(),
    }


def made_clip(track_id: str, clip_id: str, asset_id: str, fade: dict | None = None) -> Clip:
    built = Clip.model_validate(
        {
            "id": clip_id,
            "asset_id": asset_id,
            "track_id": track_id,
            "position_ticks": 0,
            "duration_ticks": SECONDS * T,
        }
    )
    built.fade = FadeEnvelope.model_validate(fade) if fade else None
    return built


def opacity_project(white: dict, black: dict, fade: dict | None, top: bool = True) -> Project:
    """黑底 + 上层白色：落到成片像素里的就是上层的 alpha。"""
    clips = {"b": made_clip("v1", "b", "black", None)}
    if top:
        clips["w"] = made_clip("v2", "w", "white", fade)
    return Project(
        id="p",
        name="fade opacity",
        settings=SequenceSettings(width=160, height=90, sample_rate=RATE),
        tracks=[Track(id="v1", kind="video", name="底"), Track(id="v2", kind="video", name="上")],
        assets={"black": black, "white": white},
        clips=clips,
    )


def audio_project(tone: dict, picture: dict, keys: list[Keyframe], fade: dict | None) -> Project:
    """声音在被测试的音轨上；画面轨静音，否则它自己那份不淡的音调会混进来抬高地板。"""
    subject = made_clip("a1", "c", "tone", fade)
    subject.keyframes = keys
    return Project(
        id="p",
        name="fade audio",
        settings=SequenceSettings(width=160, height=90, sample_rate=RATE),
        tracks=[
            Track(id="v", kind="video", name="画面", muted=True),
            Track(id="a1", kind="audio", name="床"),
        ],
        assets={"tone": tone, "picture": picture},
        clips={"c": subject, "cv": made_clip("v", "cv", "picture", None)},
    )


def build(target: Project, folder: Path, name: str) -> tuple[Path, object]:
    plan = compile_render_plan(target, "h264-source-quality")
    out = folder / name
    job = folder / f"job-{name}"
    job.mkdir(exist_ok=True)
    for file, body in plan.text_files.items():
        (job / file).write_text(body, encoding="utf-8")
    done = subprocess.run(
        plan.ffmpeg_argv(str(FFMPEG), str(out)),
        cwd=job,
        capture_output=True,
        timeout=420,
        creationflags=0x08000000,
    )
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-900:]
    return out, plan


def pixel(video: Path, at: float) -> int:
    raw = run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-ss",
            f"{at:.6f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            "scale=1:1:flags=area,format=rgb24",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )
    return (raw[0] + raw[1] + raw[2]) // 3


def rms_windows(video: Path) -> list[float]:
    raw = run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-i",
            str(video),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(RATE),
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "pipe:1",
        ]
    )
    samples = array.array("f")
    samples.frombytes(raw[: len(raw) - len(raw) % 4])
    size = int(RATE * WINDOW)
    return [
        sqrt(sum(value * value for value in samples[start : start + size]) / size)
        for start in range(0, len(samples) - size, size)
    ]


def clip_payload(
    track_id: str = "v", clip_id: str = "c", asset_id: str = "a", length: int = 6
) -> dict:
    return {
        "id": clip_id,
        "asset_id": asset_id,
        "track_id": track_id,
        "position_ticks": 0,
        "duration_ticks": length * T,
        "source_in_ticks": 0,
    }


def document(clips: dict) -> Project:
    return Project(
        id="p",
        name="fade",
        settings=SequenceSettings(width=320, height=180),
        tracks=[Track(id="v", kind="video", name="v"), Track(id="a", kind="audio", name="a")],
        assets={
            "a": {
                "id": "a",
                "kind": "video",
                "label": "a",
                "reference": "r",
                "duration_ticks": 10 * T,
            },
            "note": {
                "id": "note",
                "kind": "audio",
                "label": "note",
                "reference": "r",
                "duration_ticks": 10 * T,
            },
        },
        clips=clips,
    )


def commands(*items: dict) -> list:
    return EditBatch(request_id="probe", expected_revision=0, commands=list(items)).commands


def fade_at(ticks: int, mode: str = "both", property: str = "gain", clip: str = "c") -> dict:
    return {
        "op": "clip.fade",
        "clip_id": clip,
        "property": property,
        "duration_ticks": ticks,
        "mode": mode,
    }


def duck_curve() -> list[dict]:
    """自动闪避写下来的就是这个形状：中间一堆音量点，两头不动。"""
    return [
        {
            "property": "gain",
            "at_ticks": int(at * T),
            "value": value,
            "interpolation": "linear",
        }
        for at, value in [
            (0.0, 1.0),
            (1.0, 0.25),
            (2.5, 1.0),
            (3.5, 0.25),
            (4.5, 1.0),
            (6.0, 1.0),
        ]
    ]


def one_clip(length: int = 6) -> Project:
    return document({"c": Clip.model_validate(clip_payload(length=length))})


def reducer_suite() -> None:
    # 1. 淡入与淡出同时存在。1.89：第二次点击清掉整条 gain 曲线，前两头一个不剩。
    stepped = apply_commands(one_clip(), commands(fade_at(T, "in")))
    both = apply_commands(stepped, commands(fade_at(2 * T, "out")))
    assert fade_windows(both.clips["c"], "gain") == (T, 2 * T), both.clips["c"].fade
    assert both.clips["c"].keyframes == [], "a fade must not write keyframes any more"
    assert sample(both.clips["c"], "gain", 0) == 0.0, "the head fades in"
    assert sample(both.clips["c"], "gain", 6 * T) == 0.0, "the tail fades out"
    assert abs(sample(both.clips["c"], "gain", 5 * T) - 0.5) < 1e-9, "the 2 s ramp is halfway"
    print("   淡入 + 淡出共存：两头各是自己的窗口，一条关键帧都不写")

    # 2. 淡不再抹掉音量关键帧（1.89 实测：六个点被清成两个）。
    ducked = apply_commands(
        one_clip(),
        commands(
            {
                "op": "keyframes.replace",
                "clip_id": "c",
                "property": "gain",
                "keyframes": duck_curve(),
            }
        ),
    )
    kept = len([key for key in ducked.clips["c"].keyframes if key.property == "gain"])
    faded = apply_commands(ducked, commands(fade_at(T, "out")))
    after = len([key for key in faded.clips["c"].keyframes if key.property == "gain"])
    assert kept == after == 6, f"a fade must leave the duck alone: {kept} -> {after}"
    valley = sample(faded.clips["c"], "gain", int(3.5 * T))
    assert abs(valley - 0.25) < 1e-9, f"the duck's own valley, times no fade there: {valley}"
    assert sample(faded.clips["c"], "gain", 6 * T) == 0.0, "the edge still reaches silence"
    print(f"   与闪避曲线相乘：六个点原样保住（3.5 秒处 {valley:.3f}），6 秒处仍乘到 0.0")

    # 3. 修剪：淡跟着新的边走（1.89：淡出的点停在 5.0/6.0 秒，片段已经在 5 秒结束）。
    trimmed = apply_commands(
        both,
        commands(
            {"op": "clip.trim", "clip_id": "c", "source_in_ticks": 0, "duration_ticks": 5 * T}
        ),
    )
    edge = trimmed.clips["c"]
    assert fade_windows(edge, "gain") == (T, 2 * T), "the windows are the clip's own"
    assert sample(edge, "gain", edge.duration_ticks) == 0.0, "the tail fades at the new end"
    assert sample(edge, "gain", 4 * T) > 0.4, "the ramp sits inside the trimmed clip"
    print(f"   剪到 5 秒：新边上仍是 0.0，4 秒处还有 {sample(edge, 'gain', 4 * T):.2f}——淡跟着边走")

    # 4. 分割：切口不算一条边，外边各保住自己的淡。
    split = apply_commands(
        both,
        commands({"op": "clip.split", "clip_id": "c", "at_ticks": 3 * T, "right_clip_id": "r"}),
    )
    left, right = split.clips["c"], split.clips["r"]
    assert fade_windows(left, "gain") == (T, 0), left.fade
    assert fade_windows(right, "gain") == (0, 2 * T), right.fade
    assert sample(left, "gain", left.duration_ticks) == 1.0, "the cut must not dip"
    assert sample(right, "gain", 0) == 1.0, "nor dip on the far side"
    assert sample(right, "gain", right.duration_ticks) == 0.0, "the outer edge still fades"
    print("   分割：左半保住淡入、右半保住淡出，切口两头都是 1.0（不凭空淡一下）")

    # 5. 拒绝要点名，清零就是取消。
    try:
        apply_commands(one_clip(), commands(fade_at(4 * T, "both")))
        raise AssertionError("a fade longer than the clip must be refused")
    except EditorError as error:
        assert error.code == "INVALID_FADE" and error.status == 422, (error.code, error.status)
        assert error.details["clip_id"] == "c", error.details
        assert error.details["clip_duration_ticks"] == 6 * T, error.details
        assert error.details["fade_in_ticks"] == error.details["fade_out_ticks"] == 4 * T
        assert error.details["room_ticks"] == 2 * T, error.details
        assert "too short" in error.message, error.message
        print("   放不下时点名：INVALID_FADE + 片段长度、两头各多长、这一头还能要 2 秒")
    assert apply_commands(both, commands(fade_at(0, "both"))).clips["c"].fade is None, (
        "0 clears both"
    )
    half = apply_commands(both, commands(fade_at(0, "in")))
    assert fade_windows(half.clips["c"], "gain") == (0, 2 * T), half.clips["c"].fade
    print("   0 就是取消：both 清两头、in 只清淡入")

    # 6. 音频素材没有透明度可淡。
    audio = document({"c": Clip.model_validate(clip_payload("a", "c", "note"))})
    try:
        apply_commands(audio, commands(fade_at(T, "both", "opacity")))
        raise AssertionError("opacity on audio must be refused")
    except EditorError as error:
        assert error.code == "INVALID_FADE" and error.details["clip_id"] == "c", error.details
        assert error.details["asset_kind"] == "audio", error.details
        print("   音频素材点透明度：拒绝点名片段与素材种类")

    # 7. 没有淡的片段，编译出来必须与 1.89 一字不差。
    plain = one_clip().clips["c"]
    assert expression(plain, "gain") == "1.0", expression(plain, "gain")
    assert expression(plain, "opacity", "T") == "1.0"
    sent = preview_manifest(one_clip())["clips"]["c"]
    assert sent["fade"] is None, sent["fade"]
    assert all(point["value"] == 1.0 for point in sent["curves"]["opacity"]), (
        "the raw curve stays raw"
    )
    print("   没淡的片段：表达式仍是 `1.0`，浏览器下发的 fade 是 null")

    # 8. 老写法（淡写在曲线上）照旧渲染。
    legacy = apply_commands(
        one_clip(),
        commands(
            {
                "op": "keyframes.replace",
                "clip_id": "c",
                "property": "gain",
                "keyframes": [
                    {"property": "gain", "at_ticks": 0, "value": 0.0, "interpolation": "ease"},
                    {"property": "gain", "at_ticks": T, "value": 1.0, "interpolation": "linear"},
                    {
                        "property": "gain",
                        "at_ticks": 6 * T,
                        "value": 1.0,
                        "interpolation": "linear",
                    },
                ],
            }
        ),
    )
    assert sample(legacy.clips["c"], "gain", 0) == 0.0, "a pre-1.90 fade still fades"
    assert sample(legacy.clips["c"], "gain", 3 * T) == 1.0
    print("   旧工程写在曲线里的淡：一个点都不用改，0 秒处仍是 0.0")

    caps = capabilities(True, False, [])
    assert caps["features"]["clip_fade_envelopes"] is True, caps["features"]
    assert caps["project_schema_version"] == SCHEMA_VERSION, caps["project_schema_version"]
    v15 = Project.model_validate({**one_clip().model_dump(), "schema_version": 15})
    assert v15.clips["c"].mask_shape_keys == [], "v15 的工程读进来没有轮廓帧"
    old = one_clip().model_dump()
    old["schema_version"] = 13
    assert Project.model_validate(old).clips["c"].fade is None, "a v13 row reads as 'no envelope'"
    print("   v13 的工程读进来 fade 为空；能力接口把这条新语义报出去")


def envelope_suite() -> None:
    """导出乘的那条包络，必须就是浏览器动画的那一条曲线。"""
    subject = Clip.model_validate(clip_payload())
    subject.fade = FadeEnvelope(opacity_in_ticks=T, opacity_out_ticks=T)
    compiled = expression(subject, "opacity", "T")
    assert compiled.startswith("(1.0)*("), compiled[:80]
    assert "3-2*" in compiled, f"the ramp must be the smoothstep: {compiled[:120]}"
    curve = preview_manifest(document({"c": subject}))["clips"]["c"]["fade"]["opacity"]
    points = [(point["offset"], point["value"]) for point in curve]
    assert points[0] == (0.0, 0.0) and points[-1] == (1.0, 0.0), points
    # 中间那段平的是 linear；每个点的 easing 说的是「从这里走到下一个点」，所以第二个内点已经
    # 站在淡出的斜坡头上了，它的 easing 必须是那条斜坡的贝塞尔。
    assert curve[1]["value"] == curve[2]["value"] == 1.0, curve
    assert curve[1]["easing"] == "linear", curve
    assert curve[2]["easing"].startswith("cubic-bezier("), curve
    assert curve[2]["offset"] - curve[1]["offset"] > 0.6, "两条斜坡之间必须有一段真正的平段"
    # 斜坡那一段浏览器用的是 cubic-bezier（WAAPI 说不不出 smoothstep），所以要比的是这条贝塞尔在
    # 时间中点上的取值，而不是某个下发点的值——下发点全在斜坡的两端。
    ramp = curve[0]
    assert ramp["easing"].startswith("cubic-bezier("), curve
    x1, y1, x2, y2 = (float(item) for item in ramp["easing"][13:-1].split(","))
    at_half = bezier_value(y1, y2, bezier_parameter(Bezier(x1=x1, x2=x2), 0.5))
    assert abs(at_half - 0.5) < 0.02, f"the browser's ramp midpoint: {at_half}"
    print(
        f"   浏览器那条包络：{[f'{offset:.3f}={value:.1f}' for offset, value in points]}"
        f"，斜坡中点 {at_half:.3f} 对权威 0.5，"
        f"平段跨 {curve[1]['offset']:.2f}→{curve[2]['offset']:.2f}"
    )
    only_in = Clip.model_validate(clip_payload())
    only_in.fade = FadeEnvelope(gain_in_ticks=2 * T)
    assert fade_windows(only_in, "gain") == (2 * T, 0)
    assert sample(only_in, "gain", 4 * T) == 1.0 and sample(only_in, "gain", 6 * T) == 1.0
    short = Clip.model_validate(clip_payload(length=1))
    short.fade = FadeEnvelope(gain_in_ticks=3 * T, gain_out_ticks=3 * T)
    assert fade_windows(short, "gain") == (T, 0), fade_windows(short, "gain")
    assert sample(short, "gain", T) == 1.0
    print("   片段比淡还短：窗口被夹到片段自己的长度，不会倒着淡")


def http_suite() -> None:
    """HTTP 一路：一次提交一个版本、同 request_id 重放同一笔、撤销把淡取回去。"""
    with tempfile.TemporaryDirectory(prefix="agentcut-fade-") as folder:
        store = ProjectStore(Path(folder) / "test.sqlite")
        project = store.create(CreateProject(request_id="create", name="fade")).project
        seeded = store.mutate(
            project.id,
            EditBatch(
                request_id="seed",
                expected_revision=project.revision,
                commands=[
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                    {
                        "op": "asset.register",
                        "asset": {
                            "id": "a",
                            "kind": "video",
                            "label": "a",
                            "reference": "r",
                            "duration_ticks": 10 * T,
                        },
                    },
                    {"op": "clip.add", "clip": clip_payload()},
                ],
            ),
        ).project
        request = {
            "request_id": "fade-1",
            "expected_revision": seeded.revision,
            "commands": [fade_at(T, "both")],
        }
        with TestClient(
            create_app(store.path, TOKEN),
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client:
            dry = client.post(f"/v1/projects/{project.id}/edits", json={**request, "dry_run": True})
            assert dry.status_code == 200, dry.text
            assert dry.json()["project"]["clips"]["c"]["fade"]["gain_in_ticks"] == T
            assert ProjectStore(store.path).get(project.id).revision == seeded.revision, (
                "a dry run writes nothing"
            )
            saved = client.post(f"/v1/projects/{project.id}/edits", json=request)
            assert saved.status_code == 200, saved.text
            assert saved.json()["project"]["revision"] == seeded.revision + 1
            again = client.post(f"/v1/projects/{project.id}/edits", json=request)
            assert again.json()["replayed"], "the same request must be the same write"
            assert again.json()["project"]["revision"] == saved.json()["project"]["revision"]
            stored = ProjectStore(store.path).get(project.id)
            assert fade_windows(stored.clips["c"], "gain") == (T, T), stored.clips["c"].fade
            undone = client.post(
                f"/v1/projects/{project.id}/restore",
                json={
                    "request_id": "undo",
                    "expected_revision": saved.json()["project"]["revision"],
                    "target_revision": seeded.revision,
                },
            )
            assert undone.status_code == 200, undone.text
            assert not undone.json()["project"]["clips"]["c"].get("fade"), undone.text
            refusal = client.post(
                f"/v1/projects/{project.id}/edits",
                json={
                    "request_id": "too-long",
                    "expected_revision": undone.json()["project"]["revision"],
                    "commands": [fade_at(9 * T, "both")],
                },
            )
            assert refusal.status_code == 422, refusal.text
            error = refusal.json()["error"]
            assert error["code"] == "INVALID_FADE" and error["details"]["room_ticks"], error
            assert error["details"]["clip_id"] == "c", error
            stored = client.get(f"/v1/projects/{project.id}").json()
            assert stored["revision"] == undone.json()["project"]["revision"], "拒绝不涨版本"
            assert not stored["clips"]["c"].get("fade"), stored["clips"]["c"]
            print(
                "   HTTP：预演不落库、一次提交一个版本、同 request_id 重放同一笔、撤销把淡取回去、"
                "拒绝带 details 且不涨版本"
            )


def media_suite(folder: Path) -> None:
    white = slate(folder, "white", "0xffffff", tone=False)
    black = slate(folder, "black", "0x000000", tone=False)
    tone = slate(folder, "tone", "0x404040", tone=True)
    white_asset = asset(white, "white", "video", False)
    black_asset = asset(black, "black", "video", False)
    tone_asset = asset(tone, "tone", "audio", True)
    picture_asset = asset(white, "picture", "video", False)

    subject = {"opacity_in_ticks": FADE, "opacity_out_ticks": FADE}
    bright, _ = build(opacity_project(white_asset, black_asset, None), folder, "full.mp4")
    dark, _ = build(opacity_project(white_asset, black_asset, None, top=False), folder, "floor.mp4")
    faded, plan = build(opacity_project(white_asset, black_asset, subject), folder, "fade.mp4")
    assert plan.mode == "layered", f"a two-track timeline composites: {plan.mode}"

    # 只有一层、没有别的 alpha 的片段：只有淡也得走合成，否则 1.90 之前那条「直通」路径会把淡吃掉。
    lone = Project(
        id="p",
        name="fade lone",
        settings=SequenceSettings(width=160, height=90, sample_rate=RATE),
        tracks=[Track(id="v1", kind="video", name="底")],
        assets={"white": white_asset},
        clips={"w": made_clip("v1", "w", "white", subject)},
    )
    _, single = build(lone, folder, "lone.mp4")
    assert single.mode == "layered", (
        f"one clip with a fade must not take the straight-cut path: {single.mode}"
    )
    assert any("geq=" in line for line in single.filters), single.filters[:3]

    high, low = pixel(bright, 2.0), pixel(dark, 2.0)
    assert high > 220 and low < 12, (high, low)
    probe = made_clip("v1", "w", "white", subject)
    misses: list[str] = []
    for at in (0.033, 0.25, 0.5, 1.0, 2.0, 3.0, 3.5, 3.9):
        want = sample(probe, "opacity", round(at * T))
        expect = low + (high - low) * want
        got = pixel(faded, at)
        allowance = 6.0 if 0.05 < at < 3.95 else 14.0
        if abs(got - expect) > allowance:
            misses.append(f"{at}s: pixel {got} vs {expect:.1f} (alpha {want:.3f})")
        print(
            f"   opacity {at:>5.3f}s：权威 {want:.3f} → 期望 {expect:6.1f}，实测 {got:3d}"
            f"（差 {abs(got - expect):.1f}，允许 {allowance:.0f}）"
        )
    assert not misses, "成片像素不是权威要的淡：\n" + "\n".join(misses)
    print(f"   首尾两帧回到下层（{pixel(faded, 0.033)} / {pixel(faded, 3.9)}，地板 {low}）")

    keys = [
        Keyframe(property="gain", at_ticks=0, value=1.0, interpolation="linear"),
        Keyframe(property="gain", at_ticks=INTERIOR, value=INTERIOR_VALUE, interpolation="linear"),
        Keyframe(property="gain", at_ticks=SECONDS * T, value=1.0, interpolation="linear"),
    ]
    flat_path, _ = build(audio_project(tone_asset, picture_asset, [], None), folder, "flat.mp4")
    bed = audio_project(
        tone_asset,
        picture_asset,
        keys,
        {"gain_in_ticks": FADE, "gain_out_ticks": FADE},
    )
    bedded, _ = build(bed, folder, "bed.mp4")
    curves, flat = rms_windows(bedded), rms_windows(flat_path)
    assert len(curves) == len(flat) >= 30, (len(curves), len(flat))
    authority = bed.clips["c"]
    misses = []
    worst = (0.0, "")
    windows = int(SECONDS / WINDOW) - 1
    for index in range(windows):
        at = index * WINDOW + WINDOW / 2
        if flat[index] <= 1e-6:
            continue
        ratio = curves[index] / flat[index]
        at_ticks = round(at * T)
        want = sample(authority, "gain", at_ticks)
        # 一个窗 0.1 秒，斜坡在窗内还会动，所以诚实的余量是半个窗的局部斜率，再加一点给编码器。
        slope = abs(
            sample(authority, "gain", at_ticks + round(WINDOW * T))
            - sample(authority, "gain", max(0, at_ticks - round(WINDOW * T)))
        ) / (2 * WINDOW)
        allowance = 0.02 + 0.5 * WINDOW * slope
        drift = abs(ratio - want)
        if drift / allowance > worst[0]:
            worst = (drift / allowance, f"{at:.2f}s 比 {ratio:.3f} 对权威 {want:.3f}")
        if drift > allowance:
            misses.append(f"{at:.2f}s: {ratio:.3f} vs {want:.3f} (allowance {allowance:.3f})")
    assert not misses, "成片音量不是淡 × 曲线的权威：\n" + "\n".join(misses[:12])
    valley = min(range(windows), key=lambda index: abs(index * WINDOW + WINDOW / 2 - 2.0))
    valley_ratio = curves[valley] / flat[valley]
    assert abs(valley_ratio - INTERIOR_VALUE) < 0.03, (
        f"中间那个音量点必须在淡之后还在：{valley_ratio:.3f} vs {INTERIOR_VALUE}"
    )
    assert curves[0] / flat[0] < 0.12, f"第一窗就该淡下去：{curves[0] / flat[0]:.3f}"
    disagree = sum(1 for index in range(windows) if abs(curves[index] / flat[index] - 1.0) > 0.03)
    assert disagree > 10, f"只有 {disagree} 个窗与不淡的对照不同"
    print(
        f"   音量：{windows} 个 {WINDOW}s 窗与权威逐窗比，最差只用掉允许量的 {worst[0]:.2f} 倍"
        f"（{worst[1]}）；2 秒处仍是 {valley_ratio:.3f}（乘在曲线上，不是替换）"
    )


def main() -> None:
    os.environ.setdefault("AGENTCUT_TOKEN", TOKEN)
    reducer_suite()
    envelope_suite()
    http_suite()
    folder = Path(tempfile.mkdtemp(prefix="agentcut-fade-media-"))
    media_suite(folder)
    print(
        "PASS: 淡在片段的两条边上——两头共存、与曲线相乘、跟着修剪与分割走，成片逐窗逐像素对得住权威"
    )


if __name__ == "__main__":
    main()
