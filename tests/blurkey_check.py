"""1.98 柔焦可以打关键帧：编译出来的是同一条阶梯，两端走的都是它，成片量得出它真的在糊。

以前这一颗旋钮明确不能打关键帧，理由写在 `contracts` 的注释里：`gblur` 的 sigma 不读表达式，只有一个
`enable` 的开/关窗，硬打就是「导出成阶梯、预览平滑插值」——两端各说各话。这一版没有把阶梯藏起来，
而是让它成为唯一的那一份权威：`animation.spatial_schedule` 按序列帧网格把曲线切成至多
`SPATIAL_SCHEDULE_MAX` 段，导出为每一段串一个 `gblur=sigma=…:enable='between(t,…)'`，浏览器把**同样
的段**用 `steps(1, end)` 动画出来。于是两端不是「近似」，是同一个数表。

量什么：

* 阶梯本身：段与段首尾相接、覆盖整段、不超过上限、每段取的就是那段中点的权威 `sample`，值单调；
  短于上限的片段一格一帧（帧级精确），长的自动把步长加宽而不是拒绝。
* 两端同源：`preview_manifest` 交出的点表逐条等于阶梯的偏移与值；编译出的滤镜串里 gblur 段数
  等于非零段数，且每一串的 `between(t,…)` 就是那一段的秒数。
* 成片：一张静止的二值棋盘（高频，且各帧内容相同，于是「同一个 σ 的整段参照」可以直接对照），
  曲线从 0 拉到顶。每个探针时刻读到的细节必须与「整段都用那一段的 σ」的参照对得上，
  而且必须显著低于不糊的参照——阶梯是真的在改变画面，不是字符串上看着变了。
"""

import re
import subprocess
import sys
from pathlib import Path

from fade_check import RATE, SECONDS, asset, build, made_clip, slate
from pydantic import ValidationError

from agentcut.animation import preview_manifest, sample, spatial_schedule
from agentcut.contracts import (
    BLUR_LIMIT,
    SPATIAL_SCHEDULE_MAX,
    Clip,
    Keyframe,
    Project,
    SequenceSettings,
    Track,
    capabilities,
)
from agentcut.contracts import TIMEBASE as T
from agentcut.render import compile_render_plan, focus_radius

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
WIDTH, HEIGHT = 320, 180
FPS = 25
FRAME = T // FPS
FFMPEG = Path(__file__).resolve().parent.parent / "desktop" / "resources" / "bin" / "ffmpeg.exe"


def clip_with(points: list[tuple[int, float, str]], duration: int = SECONDS * T) -> Clip:
    """一条黑底之上的棋盘片段，柔焦曲线就是被测对象。"""
    clip = made_clip("v2", "w", "board", None)
    clip.duration_ticks = duration
    clip.effects.blur = 0.0
    clip.keyframes = [
        Keyframe(property="blur", at_ticks=at, value=value, interpolation=kind)
        for at, value, kind in points
    ]
    return clip


def project_of(clip: Clip, board: dict, black: dict) -> Project:
    return Project(
        id="p",
        name="blurkey",
        settings=SequenceSettings(
            width=WIDTH,
            height=HEIGHT,
            sample_rate=RATE,
            frame_rate={"numerator": FPS, "denominator": 1},
        ),
        tracks=[Track(id="v1", kind="video", name="底"), Track(id="v2", kind="video", name="上")],
        assets={"board": board, "black": black},
        clips={"b": made_clip("v1", "b", "black", None), "w": clip},
    )


def ramp_points(duration: int) -> list[tuple[int, float, str]]:
    return [(0, 0.0, "linear"), (duration, BLUR_LIMIT, "linear")]


def schedule_suite() -> None:
    duration = SECONDS * T
    clip = clip_with(ramp_points(duration))
    plan = spatial_schedule(clip, "blur", FRAME)
    assert plan, "有曲线的柔焦必须排出窗"
    assert plan[0]["from_ticks"] == 0 and plan[-1]["to_ticks"] == duration, plan
    for left, right in zip(plan, plan[1:]):
        assert left["to_ticks"] == right["from_ticks"], "段与段必须首尾相接，不留缝也不重叠"
    assert len(plan) <= SPATIAL_SCHEDULE_MAX, len(plan)
    values = [window["value"] for window in plan]
    assert values == sorted(values), f"从 0 拉到顶的曲线不该回头：{values}"
    # 每段取的是那段中点的权威 sample，不是端点也不是界面自己算的。
    for window in plan:
        middle = (window["from_ticks"] + window["to_ticks"]) // 2
        assert window["value"] == round(sample(clip, "blur", middle), 9), window
    # 4 秒 25 fps 有 100 帧，比上限多，于是步长被加宽而不是拒绝；但仍是整帧的倍数。
    step = plan[1]["from_ticks"] - plan[0]["from_ticks"]
    assert step % FRAME == 0, f"段边界必须落在整帧上：{step}"
    assert step >= FRAME, "加宽后的步长不该比一格帧还细"
    # 短于上限的片段一格一帧：帧级精确，不是「凑够上限」。
    short = clip_with(ramp_points(12 * FRAME), 12 * FRAME)
    fine = spatial_schedule(short, "blur", FRAME)
    assert len(fine) == 12, len(fine)
    assert all(b["from_ticks"] - a["from_ticks"] == FRAME for a, b in zip(fine, fine[1:]))
    # 全程按住的曲线只有一段：值相同的相邻段被合并，窗数不是硬凑出来的。
    # 跳变正好落在片段末尾时也一样——那一值没有任何一帧会看到，所以它不该多出一段窗。
    held = clip_with([(0, 0.06, "hold"), (duration, BLUR_LIMIT, "hold")])
    merged = spatial_schedule(held, "blur", FRAME)
    assert len(merged) == 1, merged
    inside = clip_with([(0, 0.06, "hold"), (3 * T, BLUR_LIMIT, "hold")])
    two = spatial_schedule(inside, "blur", FRAME)
    assert [window["value"] for window in two] == [0.06, BLUR_LIMIT], two
    assert two[0]["to_ticks"] == 3 * T, two
    # 没有曲线的旋钮一段都不排——静态那条路一字不动（blur_check 仍在守着它）。
    assert spatial_schedule(made_clip("v2", "q", "board", None), "blur", FRAME) == []
    print(
        f"   阶梯：{len(plan)} 段覆盖整段、首尾相接、步长 {step / FRAME:g} 帧，"
        "短片段一帧一段、按住的跳变只在末尾就只有一段"
    )


def both_ends_suite() -> None:
    board = {
        "id": "board",
        "kind": "video",
        "label": "b",
        "reference": "r",
        "duration_ticks": SECONDS * T,
    }
    black = {
        "id": "black",
        "kind": "video",
        "label": "k",
        "reference": "r",
        "duration_ticks": SECONDS * T,
    }
    clip = clip_with(ramp_points(SECONDS * T))
    project = project_of(clip, board, black)
    plan = spatial_schedule(clip, "blur", FRAME)
    manifest = preview_manifest(project)["clips"]["w"]
    curve = manifest["spatial"]["blur"]
    assert len(curve) == len(plan), (len(curve), len(plan))
    for point, window in zip(curve, plan):
        assert point["offset"] == window["from_ticks"] / clip.duration_ticks, point
        assert point["value"] == window["value"], (point, window)
        assert point["easing"] == "steps(1, end)", "浏览器必须一格一步，不许自己插值"
    caps = capabilities(True, False, False)
    assert caps["features"]["blur_keyframes"] is True, caps["features"]
    assert caps["limits"]["blur_schedule_segments"] == SPATIAL_SCHEDULE_MAX, caps["limits"]
    # 契约层：blur 现在是可以打关键帧的属性，而 denoise 仍然不是。
    Keyframe(property="blur", at_ticks=0, value=0.1, interpolation="ease")
    for bad in ("denoise", "sharpen"):
        try:
            Keyframe(property=bad, at_ticks=0, value=0.1)
            raise AssertionError(f"{bad} 不该能当关键帧属性")
        except ValidationError:
            pass
    try:
        Keyframe(property="blur", at_ticks=0, value=BLUR_LIMIT + 0.01)
        raise AssertionError("超出旋钮上限的曲线值该在契约层就拒")
    except ValidationError:
        pass
    print(
        f"   两端同源：{len(plan)} 段窗逐条出现在下发给浏览器的点表里（每段一步，不许插值）；"
        "denoise/sharpen 仍进不了关键帧属性"
    )


def detail(video: Path, at: float) -> float:
    """相邻像素差的均值：棋盘不糊时它最大，糊了就掉。整幅灰度逐像素读，不抽样。"""
    raw = subprocess.run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-ss",
            f"{at:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            "format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        timeout=300,
    )
    assert raw.returncode == 0, raw.stderr[-200:]
    data = raw.stdout
    assert len(data) >= WIDTH * HEIGHT, "没读到一整帧"
    total = 0
    for row in range(HEIGHT):
        base = row * WIDTH
        total += sum(abs(data[base + col] - data[base + col + 1]) for col in range(WIDTH - 1))
    return total / (HEIGHT * (WIDTH - 1))


def board_file(folder: Path) -> Path:
    """一张静止的二值棋盘：各帧内容相同，所以「整段同一个 σ」就是可以直接对照的参照。"""
    target = folder / "board.mp4"
    done = subprocess.run(
        [
            str(FFMPEG),
            "-y",
            "-f",
            "lavfi",
            "-i",
            (
                f"nullsrc=s={WIDTH}x{HEIGHT}:r={FPS}:d={SECONDS},"
                "geq=lum='255*mod(floor(X/2)+floor(Y/2)\\,2)':cb=128"
            ),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "gray",
            "-qp",
            "0",
            "-g",
            "1",
            str(target),
        ],
        capture_output=True,
        timeout=600,
    )
    assert done.returncode == 0, done.stderr[-400:]
    return target


def media_suite(folder: Path) -> None:
    board = board_file(folder)
    black = slate(folder, "kb", "0x000000", False)
    board_asset = asset(board, "board", "video", False)
    black_asset = asset(black, "black", "video", False)
    duration = board_asset["verified"]["duration_ticks"]
    clip = clip_with(ramp_points(duration), duration)
    project = project_of(clip, board_asset, black_asset)
    plan = spatial_schedule(clip, "blur", FRAME)
    # 编译串：每一段非零的窗串一个 gblur，`enable` 的那两个秒数就是那一段的边界。
    graph = "\n".join(compile_render_plan(project, "h264-source-quality").filters)
    # `enable` 自己带逗号，所以按逗号切串是切不开的——直接按导出的形状抓三元组。
    stages = re.findall(
        r"gblur=sigma=([\d.]+):steps=6:enable='between\(t,([\d.]+),([\d.]+)\)'", graph
    )
    nonzero = [window for window in plan if window["value"] > 0]
    assert len(stages) == len(nonzero), (len(stages), len(nonzero))
    for (radius, start, stop), window in zip(stages, nonzero):
        assert radius == f"{focus_radius(window['value'], 'blur', HEIGHT):.4f}", (radius, window)
        assert start == f"{window['from_ticks'] / T:.6f}", (start, window)
        assert stop == f"{window['to_ticks'] / T:.6f}", (stop, window)
    rendered, _ = build(project, folder, "blurkey.mp4")
    # 参照走的是同一条编译路与同一个编码器：把曲线换成「整段都用这一个 σ」的静态旋钮再渲一遍。
    # 于是比较里没有近似成分——同一个源、同一个合成、同一套 x264 设置，只差那一个 σ。
    distinct = sorted({window["value"] for window in plan})
    sigma_to_detail = {}
    for value in distinct:
        static = clip_with([], duration)
        static.effects.blur = value
        reference, _ = build(
            project_of(static, board_asset, black_asset), folder, f"static{value:.6f}.mp4"
        )
        sigma_to_detail[value] = detail(reference, 1.0)
    read = []
    for window in plan:
        at = min((window["from_ticks"] + window["to_ticks"]) / 2 / T, duration / T - 0.02)
        read.append((window["value"], detail(rendered, at), sigma_to_detail[window["value"]]))
    # 每一段都必须与「整段都是这一段那个 σ」的渲染同幅同样。容差从编码本身来：同一张静止棋盘
    # 经同一个编码器两次，读数差在这个量级；再大就是模糊算错了。
    for value, got, reference in read:
        assert abs(got - reference) <= max(0.5, reference * 0.1), (value, got, reference)
    steps = [row[1] for row in read]
    # 阶梯要一路在糊：任何一段都不许比前一段更清楚（留 2% 给编码器噪声），并且开头那张棋盘
    # 本身要够高频——不然整条断言只是在比噪声。
    for index in range(1, len(steps)):
        assert steps[index] <= steps[index - 1] + steps[0] * 0.02, steps[index - 1 : index + 1]
    assert steps[0] > 8, f"这张棋盘不够高频，测不出柔焦：{steps[0]}"
    assert steps[0] > steps[2] * 1.5, f"三段之内看不出在糊：{steps[:4]}"
    assert steps[-1] < steps[0] * 0.02, f"拉到底该糊得看不见棋盘：{steps[-1]} 对 {steps[0]}"
    print(
        f"   成片：编译里 {len(stages)} 串 gblur 对应 {len(nonzero)} 段非零窗，"
        f"{len(read)} 段逐段与「整段同一个 σ」的同路渲染对得上，"
        f"细节从 {steps[0]:.1f} 降到 {steps[-1]:.2f}"
    )


def main() -> None:
    schedule_suite()
    both_ends_suite()
    import tempfile

    with tempfile.TemporaryDirectory(prefix="agentcut-blurkey-") as scratch:
        media_suite(Path(scratch))
    print("PASS: 柔焦的曲线编译成一条两端共用的阶梯，成片逐段量得到它真的在糊")


if __name__ == "__main__":
    main()
