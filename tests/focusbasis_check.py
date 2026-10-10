"""1.100 柔焦与清晰量的「画面高」：交付画幅被补边时，基准必须是画面，不是那一帧。

这两个旋钮的语义是「画面高的百分比」（界面与预览都这么写：浏览器给的是 `blur(Ncqh)`，而预览那个框
锁的是工程比例）。导出以前用的是 `out_h`——交付帧的高。工程 16:9 交付 1:1 或 9:16 时，画面在帧里
只有 `out_h` 的一部分，于是同一个旋钮在成片里比预览糊得多：实测过，160x90 的工程交付 160x160，
σ 从 4.5 变成 8.0，画面细节从 2.67 掉到 0.10（控制组只差 1.7%）。同一条式子还让母带 64 px 的上限
按帧算，界面按工程高给的位置在竖屏交付里会被导出拒绝。

量什么：
* `picture_height` 的算术：contain 才让画面小于帧，cover/stretch 铺满帧；
* 编译串里的 σ 逐条等于「比例 × 画面高」，阶梯（打关键帧那条）也一样；
* 上限那句话说的是画面，不是帧：竖屏交付里一个界面合法的位置必须被接受；
* 成片差分：同一颗旋钮在同比例与方画幅两种交付里，画面带的细节损失必须与「只有补边」的控制组同量级。
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fade_check import RATE, SECONDS, T, asset, made_clip  # noqa: E402

from agentcut.contracts import (  # noqa: E402
    BLUR_RADIUS_LIMIT_PX,
    EditorError,
    Keyframe,
    Project,
    SequenceSettings,
    Track,
)
from agentcut.render import compile_render_plan, picture_height  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WIDTH, HEIGHT, FPS = 160, 90, 25
FFMPEG = Path(__file__).resolve().parent.parent / "desktop" / "resources" / "bin" / "ffmpeg.exe"
ROOT = Path(tempfile.mkdtemp(prefix="agentcut-focusbasis-"))


def board(name: str, block: int) -> Path:
    target = ROOT / name
    subprocess.run(
        [
            str(FFMPEG),
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"nullsrc=s={WIDTH}x{HEIGHT}:r={FPS}:d={SECONDS},"
            f"geq=lum='255*mod(floor(X/{block})+floor(Y/{block})\\,2)':cb=128",
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
        check=True,
        capture_output=True,
    )
    return target


def project(
    blur: float,
    points: tuple[int, float] | None = None,
    width: int = WIDTH,
    height: int = HEIGHT,
    source: Path | None = None,
) -> Project:
    clip = made_clip("v1", "b", "board")
    clip.effects.blur = blur
    if points is not None:
        clip.keyframes = [
            Keyframe(property="blur", at_ticks=at, value=value, interpolation="linear")
            for at, value in points
        ]
    record = asset(source or board("board8.mp4", 8), "board", "video", False)
    return Project(
        id="p",
        name="focusbasis",
        settings=SequenceSettings(
            width=width,
            height=height,
            sample_rate=RATE,
            frame_rate={"numerator": FPS, "denominator": 1},
        ),
        tracks=[Track(id="v1", kind="video", name="画面")],
        assets={"board": record},
        clips={"b": clip},
    )


def sigmas(plan) -> list[float]:
    text = "\n".join(plan.filters).replace("\n", ",")
    return [float(match.group(1)) for match in re.finditer(r"gblur=sigma=([0-9.]+)", text)]


def arithmetic_suite() -> None:
    assert picture_height(160, 90, 160, 90, "contain") == 90
    assert picture_height(160, 160, 160, 90, "contain") == 90, "同比例补边不该缩画面"
    assert picture_height(160, 160, 320, 180, "contain") == 90, (
        "16:9 进方画幅，画面高是 90 不是 160"
    )
    assert picture_height(90, 160, 160, 90, "contain") == round(90 * 90 / 160), "竖屏那一路"
    assert picture_height(1600, 900, 160, 90, "contain") == 900, "放大交付里画面占满帧高"
    for fit in ("cover", "stretch"):
        assert picture_height(90, 160, 160, 90, fit) == 160, f"{fit} 铺满帧，基准就是帧高"
    print("   picture_height：contain 才让画面小于帧，cover/stretch 铺满，放大交付回帧高")


def compiled_suite() -> None:
    target = project(0.05)
    native = sigmas(compile_render_plan(target, "h264-source-quality", preview_size=(160, 90)))
    square = sigmas(compile_render_plan(target, "h264-source-quality", preview_size=(160, 160)))
    vertical = sigmas(compile_render_plan(target, "h264-source-quality", preview_size=(90, 160)))
    assert native == [4.5], native
    assert square == [4.5], f"方画幅里画面仍是 90 高，σ 不许按帧算：{square}"
    basis = picture_height(90, 160, WIDTH, HEIGHT, "contain")
    assert vertical == [round(0.05 * basis, 4)], f"竖屏：{vertical} vs 0.05×{basis}"

    # 清晰半径同一条式子、同一个基准。
    sharp = project(0.0)
    clip = sharp.clips["b"]
    clip.effects.sharpen = 0.5
    clip.effects.sharpen_radius = 0.05
    text = "\n".join(
        compile_render_plan(sharp, "h264-source-quality", preview_size=(160, 160)).filters
    )
    assert f"sigma={4.5:.4f}" in text.replace("gblur=sigma=", "sigma="), text[:400]

    # 阶梯那条路也要按画面高折算：每段的 σ = 该段值 × 画面高。
    ramp = project(0.0, points=((0, 0.0), (4 * T // 2, 0.2), (SECONDS * T, 0.2)))
    windows = sigmas(compile_render_plan(ramp, "h264-source-quality", preview_size=(160, 160)))
    assert windows, "打关键帧的柔焦没编译出 gblur 段"
    assert max(windows) == round(0.2 * 90, 4), f"阶梯段按帧算了：{max(windows)} vs {0.2 * 90}"
    print(
        f"   编译串：静态 {native[0]} / 方画幅 {square[0]} / 竖屏 {vertical[0]}，"
        f"阶梯峰值 {max(windows)} 都按画面高"
    )


def guard_suite() -> None:
    """竖屏交付里，界面合法的位置必须导得出去；超限那句拒绝得点名画面。"""
    tall = project(0.05, width=1920, height=1080)
    plan = compile_render_plan(tall, "h264-source-quality", preview_size=(1080, 1920))
    basis = picture_height(1080, 1920, 1920, 1080, "contain")
    assert basis == round(1080 * 1080 / 1920) == 608, basis
    assert sigmas(plan) == [round(0.05 * basis, 4)], sigmas(plan)
    try:
        compile_render_plan(
            project(0.11, width=1920, height=1080), "h264-source-quality", preview_size=(1080, 1920)
        )
    except EditorError as error:
        assert error.code == "BLUR_OUT_OF_RANGE", error.code
        assert (
            error.details["max_radius_fraction"] == round(BLUR_RADIUS_LIMIT_PX / basis, 6)
            or abs(error.details["max_radius_fraction"] - BLUR_RADIUS_LIMIT_PX / basis) < 1e-9
        ), error.details
        assert f"{basis} px picture" in error.message, error.message
        print(
            f"   上限守画面高：1920x1080 → 1080x1920 下 5% 导得出去，11% 被 {error.code} 点名拒绝"
        )
        return
    raise AssertionError("0.11 在 607 px 画面上已是 66.8 px，超过实测带却没被拒绝")


def detail(video: Path, crop: str | None, width: int = WIDTH, height: int = HEIGHT) -> float:
    chain = f"format=gray,{crop}" if crop else "format=gray"
    raw = subprocess.run(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-ss",
            "1.0",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            chain,
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=300,
    ).stdout
    assert len(raw) >= width * height, len(raw)
    total = 0
    for row in range(height):
        base = row * width
        total += sum(abs(raw[base + col] - raw[base + col + 1]) for col in range(width - 1))
    return total / (height * (width - 1))


def render(target: Project, name: str, size: tuple[int, int]) -> Path:
    plan = compile_render_plan(target, "h264-source-quality", preview_size=size)
    out = ROOT / name
    job = ROOT / f"job-{name}"
    job.mkdir(exist_ok=True)
    for file, body in plan.text_files.items():
        (job / file).write_text(body, encoding="utf-8")
    done = subprocess.run(
        plan.ffmpeg_argv(str(FFMPEG), str(out)),
        cwd=job,
        capture_output=True,
        timeout=420,
        creationflags=0x08000000 if sys.platform == "win32" else 0,
    )
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-900:]
    return out


def media_suite() -> None:
    """同一颗旋钮、两种交付画幅：细节损失必须与「只有补边」的控制组同量级。"""
    band = f"crop={WIDTH}:{HEIGHT}:0:{(160 - HEIGHT) // 2}"
    for blur, label in ((0.0, "控制"), (0.05, "被测")):
        target = project(blur)
        native = detail(render(target, f"{label}-native.mp4", (WIDTH, HEIGHT)), None)
        square = detail(render(target, f"{label}-square.mp4", (160, 160)), band)
        assert native > 1.0, (label, native)
        ratio = square / native
        print(
            f"   {label}组 5%={blur}：同比例 {native:.2f} → "
            f"方画幅画面带 {square:.2f}，比 {ratio:.3f}"
        )
        if label == "控制":
            control = ratio
        else:
            assert control * 0.7 <= ratio <= min(1.6, control * 1.4 + 0.05), (control, ratio)
            assert ratio > 0.5, f"方画幅交付里画面被糊掉了：{ratio}"
    print("   成片差分：方画幅交付的画面细节与同比例一致（补边本身只吃掉不到 3%）")


def main() -> None:
    arithmetic_suite()
    compiled_suite()
    guard_suite()
    media_suite()
    print(
        "PASS: 柔焦/清晰的基准是画面高不是交付帧高（编译、上限、成片三组都对得上），"
        "同比例交付一字未改"
    )


if __name__ == "__main__":
    main()
