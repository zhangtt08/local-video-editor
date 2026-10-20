"""1.102 遮罩的坐标是「画面的百分之几」，不是交付帧的——矩形/椭圆与自由路径两条路都量。

1.100 把柔焦的半径、1.101 把字幕的字号与内缩归到画面框之后，同一句「比例量的是画面」
还剩一处没兑现：遮罩。shape 分支的 `geq` 里写的是 `X/W`、`Y/H`，而这个 `geq` 跑在 `head`
之后——那时片段已经被 `scale=…:decrease,pad=out_w:out_h` 垫成整帧；path 分支把轮廓光栅化
到 `raster_size(out_w, out_h)` 的板子上。
于是 16:9 工程交 1:1 或 9:16 时，用户画在画面上的一个遮罩形状会被拉成帧比例、还会滑出画面带。

先量出来再动手（本门禁的 `media_suite` 就是那次测量）：160x90 工程、纯白底、居中 (0.5,0.5)、
尺寸 (0.4,0.4)
的矩形遮罩，预览里应当是 64x36 的亮窗。
  * 交 160x90：行 [27,63]、列 [48,112] —— 36 高 × 64 宽，与预览一致；
  * 交 160x160（contain，画面带 y∈[35,125)）：改前是行 [48,112]（64 高，被拉成正方形且往上偏），
    改后是行 [62,98] —— 与同比例那一路同一尺寸、画面带内居中。
"""

import subprocess
import sys
from pathlib import Path

import scratch

sys.path.insert(0, str(Path(__file__).resolve().parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fade_check import RATE, SECONDS, asset, made_clip  # noqa: E402

from agentcut.contracts import Project, SequenceSettings, ShapeMask, Track  # noqa: E402
from agentcut.masks import alpha_expression  # noqa: E402
from agentcut.render import compile_render_plan  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FFMPEG = REPO / "desktop" / "resources" / "bin" / "ffmpeg.exe"
W, H, FPS = 160, 90, 25
ROOT = scratch.make("agentcut-maskbox-")


def plate(name: str) -> Path:
    target = ROOT / name
    if not target.is_file():
        subprocess.run(
            [
                str(FFMPEG),
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=white:s={W}x{H}:r={FPS}:d={SECONDS}",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-qp",
                "0",
                str(target),
            ],
            check=True,
            capture_output=True,
        )
    return target


def project(mask: ShapeMask) -> Project:
    clip = made_clip("v1", "b", "white")
    clip.mask = mask
    return Project(
        id="p",
        name="maskbox",
        settings=SequenceSettings(
            width=W, height=H, sample_rate=RATE, frame_rate={"numerator": FPS, "denominator": 1}
        ),
        tracks=[Track(id="v1", kind="video", name="画面")],
        assets={"white": asset(plate("white.mp4"), "white", "video", False)},
        clips={"b": clip},
    )


def rect(**override) -> ShapeMask:
    base = {
        "shape": "rectangle",
        "center_x": 0.5,
        "center_y": 0.5,
        "width": 0.4,
        "height": 0.4,
        "feather": 0,
        "inverted": False,
        "vertices": None,
    }
    base.update(override)
    return ShapeMask.model_validate(base)


def path_mask() -> ShapeMask:
    return ShapeMask.model_validate(
        {
            "shape": "path",
            "center_x": 0.5,
            "center_y": 0.5,
            "width": 0.4,
            "height": 0.4,
            "feather": 0,
            "inverted": False,
            "vertices": [
                {"x": 0.35, "y": 0.30, "handle_out": [0, 0], "handle_in": [0, 0]},
                {"x": 0.65, "y": 0.30, "handle_out": [0, 0], "handle_in": [0, 0]},
                {"x": 0.50, "y": 0.70, "handle_out": [0, 0], "handle_in": [0, 0]},
            ],
        }
    )


def expression_suite() -> None:
    taken = "abs((X/W-(0.5))*2/(0.4))"
    plain = alpha_expression(rect())
    assert taken in plain and "(X-0.0000)" not in plain, plain
    # 画面填满帧时不许多出一次减法：`box=None` 与 1.45 以来一字不差。
    box = alpha_expression(rect(), None, (0.0, 35.0, 160.0, 90.0))
    assert "((X-0.0000)/160.0000)" in box and "((Y-35.0000)/90.0000)" in box, box
    assert "abs((((Y-35.0000)/90.0000)-(0.5))" in box, box
    # 居中且画面填满帧时，box 与裸 X/W 折出来必须同值，但不必同串——这里要求串也一致，
    # 好让「同比例交付一字未改」这句话可以拿旧门禁去证。
    assert alpha_expression(rect(), None, None) == plain
    print("   alpha_expression：没有补边时保持 X/W，补边时把 X/Y 折进画面框")


def graph_of(target: Project, size: tuple[int, int]) -> str:
    """argv + filters：板子的尺寸在 lavfi 输入里，pad 在滤镜图里，两处都得看得见。"""
    plan = compile_render_plan(target, "h264-source-quality", preview_size=size)
    argv = " ".join(plan.ffmpeg_argv(str(FFMPEG), "out.mp4"))
    return "\n".join(plan.filters) + "\n" + argv


def graph_suite() -> None:
    native = graph_of(project(rect()), (W, H))
    assert "X/W" in native and "(Y-35" not in native, native[:400]
    square = graph_of(project(rect()), (W, W))
    assert "((Y-35.0000)/90.0000)" in square, square[:400]
    # 自由路径：板子按画面尺寸光栅化，再垫成帧；同比例那条多不出这道 pad。
    path_native = graph_of(project(path_mask()), (W, H))
    assert "color=c=black:s=160x90" in path_native, path_native[-500:]
    assert "pad=160:160:0:35" not in path_native, path_native[:400]
    path_square = graph_of(project(path_mask()), (W, W))
    assert "color=c=black:s=160x90" in path_square, path_square[-500:]
    assert "pad=160:160:0:35:color=black" in path_square, path_square[:600]
    print("   编译串：同比例一字未改，方画幅里板子仍是 160x90、垫成帧时偏移 35")


def render(target: Project, name: str, size: tuple[int, int]) -> Path:
    plan = compile_render_plan(target, "h264-source-quality", preview_size=size, fit="contain")
    out = ROOT / name
    job = ROOT / f"job-{name}"
    job.mkdir(exist_ok=True)
    for file, body in plan.text_files.items():
        (job / file).write_text(body, encoding="utf-8")
    for file, blob in plan.binary_files.items():
        (job / file).write_bytes(blob)
    done = subprocess.run(
        plan.ffmpeg_argv(str(FFMPEG), str(out)),
        cwd=job,
        capture_output=True,
        timeout=420,
        creationflags=0x08000000 if sys.platform == "win32" else 0,
    )
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-700:]
    return out


def bright_box(video: Path, width: int, height: int) -> tuple[int, int, int, int]:
    """中间一列/一行里亮像素的上下左右沿（遮罩留下的是亮的画面，其余被削成透明→黑）。"""
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
            "format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=300,
    ).stdout
    assert len(raw) >= width * height, len(raw)
    column = [raw[row * width + width // 2] for row in range(height)]
    row = [raw[(height // 2) * width + x] for x in range(width)]
    rows = [i for i, value in enumerate(column) if value > 128]
    cols = [i for i, value in enumerate(row) if value > 128]
    assert rows and cols, (len(rows), len(cols))
    return min(rows), max(rows), min(cols), max(cols)


def media_suite() -> None:
    for shape, label in ((rect(), "矩形"), (path_mask(), "路径")):
        native = bright_box(render(project(shape), f"{label}-native.mp4", (W, H)), W, H)
        square = bright_box(render(project(shape), f"{label}-square.mp4", (W, W)), W, W)
        bar = (W - H) / 2
        print(
            f"   {label}遮罩：同比例 行[{native[0]},{native[1]}] 列[{native[2]},{native[3]}]；"
            f"方画幅 行[{square[0]},{square[1]}] 列[{square[2]},{square[3]}]"
        )
        if label == "矩形":
            assert native[1] - native[0] == square[1] - square[0] == 36, (native, square)
            assert square[0] >= bar and square[1] < bar + H, square
            # 画面带内居中：上下余量应当彼此相等（±1 px 的取样误差）。
            assert abs((square[0] - bar) - (bar + H - 1 - square[1])) <= 1, square
        else:
            # 路径的形状不许被帧比例拉高：两路的竖向跨度应当一致（±2 px）。
            assert abs((native[1] - native[0]) - (square[1] - square[0])) <= 2, (native, square)
            assert square[0] >= bar - 1 and square[1] < bar + H + 1, square
    print("   成片：补边交付里的遮罩与同比例那一路同一尺寸、同一落点，都在画面带内")


def main() -> None:
    expression_suite()
    graph_suite()
    media_suite()
    print("PASS: 遮罩（矩形/椭圆与自由路径）的坐标按画面框折算，同比例交付一字未改，成片量得出来")


if __name__ == "__main__":
    main()
