"""1.157 量的两把尺：为什么「遮罩跟踪估计旋转」还不能交，以及哪条路交得出来。

`AGENTS` 里那条「可复用的是 stabilize.py 的四锚点 Arun 刚体拟合」不成立，这一档把它量死：
画面稳定的四个锚点铺在整幅画面上（~300 px 基线），一个像素 0.19°；遮罩盒的锚点只能铺在盒子上
（这里 38 px 基线），一个像素就是 ~3°。而实测比「分辨率不够」更糟——盒子转起来时四个角彼此长得
一样，锚点会滑到隔壁那个角上，逐帧角增量的中位是 **15.5°**，作者写进去的是每帧 1.15°：那不是低
分辨率的量，那是噪声；30 帧累加得到 445°，真相 33°。

反过来，把第 0 帧的模板按候选角转过去、在已定下的中心上打分（绝对角，不累加），在 30 帧、
±20° 的窗口内误差中位 3.5°。

**1.218 给这一档补了它当时没有的那把尺**：上面那个 3.5° 是「拿第 0 帧当参照、候选角对整段一次性
搜」——最好情况，真正的跟踪器看不到整段。补的这条按跟踪器真能做的事搜（每帧只在**上一帧那个角**
两侧 ±20° 里搜、中心跟着已定下的中心走），30 帧的夹具上中位 4.73°、末帧差 8.77°。所以「下一轮建在
绝对角搜索上」那句要改成：建在它，但先让因果链的末帧也进窗口——这一档现在钉的就是这个末帧。

数字都是这一趟当场量的，不是抄的；两条判据各能红（见文件末尾那句 PASS 之前的突变说明）。
"""

import math
import subprocess
import sys
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut.contracts import TIMEBASE as T  # noqa: E402
from agentcut.contracts import FrameRate  # noqa: E402
from agentcut.stabilize import _rigid_angle  # noqa: E402
from agentcut.tracking import (  # noqa: E402
    _crop,
    _match,
    _ncc,
    _search,
    _zeroed,
    analyse_window,
    track_box,
)

FFMPEG = ROOT / "desktop/resources/bin/ffmpeg.exe"
FFPROBE = ROOT / "desktop/resources/bin/ffprobe.exe"
W, H, FPS = 320, 180, 30
FRAMES = 30
RATE = 0.6  # rad/s，夹具里真转的速度
MARK, PAD = 48, 16
CX, CY = 160, 90
SIDE = 34  # 跟踪器给这个盒子用的模板边长
ANCHOR_PATCH = 6
CANDIDATE_STEP = 4.0
CANDIDATE_SPAN = 20.0
# 钉住的判据：绝对角搜索在中位上收进这个误差内；四锚点拟合的逐帧增量小于这个角就等于量不出来。
SEARCH_MEDIAN_DEGREES = 6.0
ANCHOR_NOISE_FACTOR = 5.0


def plate(path: Path) -> None:
    """一块 48×48 的白板、左上角挖一个黑缺口，按 `RATE` 转：缺口让旋转有方向。"""
    marker = (
        f"color=c=white:s={MARK}x{MARK}:r={FPS},format=rgba,"
        f"drawbox=x=0:y=0:w=14:h=14:color=black@1:t=fill,"
        f"pad={MARK + PAD}:{MARK + PAD}:(ow-{MARK})/2:(oh-{MARK})/2:color=black@0"
    )
    argv = [
        str(FFMPEG),
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x181818:s={W}x{H}:r={FPS}",
        "-f",
        "lavfi",
        "-i",
        marker,
        "-filter_complex",
        f"[1:v]rotate=a='{RATE}*t':ow={MARK + PAD}:oh={MARK + PAD}:c=black@0[b];"
        f"[0:v][b]overlay=x={CX - (MARK + PAD) // 2}:y={CY - (MARK + PAD) // 2},format=yuv420p[v]",
        "-map",
        "[v]",
        "-t",
        str(FRAMES / FPS),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        str(path),
    ]
    done = subprocess.run(argv, capture_output=True, check=False)
    assert done.returncode == 0, done.stderr[-400:].decode(errors="replace")


def principal_axis(frame: bytes, width: int) -> float:
    """亮区的主轴角：夹具自证用——它要说「画面真的在转」，否则后面量的都是空气。"""
    height = len(frame) // width
    pts = [(x, y) for y in range(height) for x in range(width) if frame[y * width + x] > 128]
    assert len(pts) > 200, f"the plate has only {len(pts)} bright pixels"
    mx = sum(p[0] for p in pts) / len(pts)
    my = sum(p[1] for p in pts) / len(pts)
    sxx = sum((p[0] - mx) ** 2 for p in pts) / len(pts)
    syy = sum((p[1] - my) ** 2 for p in pts) / len(pts)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts) / len(pts)
    return 0.5 * math.degrees(math.atan2(2 * sxy, sxx - syy))


def rotate_template(anchor: bytes, side: int, degrees: float) -> bytes:
    angle = math.radians(-degrees)
    cosine, sine = math.cos(angle), math.sin(angle)
    centre = (side - 1) / 2
    out = bytearray(side * side)
    for y in range(side):
        for x in range(side):
            dx, dy = x - centre, y - centre
            sx = centre + dx * cosine - dy * sine
            sy = centre + dx * sine + dy * cosine
            x0, y0 = math.floor(sx), math.floor(sy)
            fx, fy = sx - x0, sy - y0

            def sample(px: int, py: int) -> float:
                return anchor[py * side + px] if 0 <= px < side and 0 <= py < side else 0.0

            value = (
                sample(x0, y0) * (1 - fx) * (1 - fy)
                + sample(x0 + 1, y0) * fx * (1 - fy)
                + sample(x0, y0 + 1) * (1 - fx) * fy
                + sample(x0 + 1, y0 + 1) * fx * fy
            )
            out[y * side + x] = max(0, min(255, int(round(value))))
    return bytes(out)


def fixture_says_it_rotates(decoded: list[bytes], width: int) -> float:
    axes = [principal_axis(frame, width) for frame in decoded]
    first = axes[0]
    swept = [((axis - first + 45) % 90) - 45 for axis in axes[1:]]
    want = math.degrees(RATE * (len(decoded) - 1) / FPS)
    got = max(swept, key=abs)
    assert abs(got) > 5.0, f"the plate did not turn: principal axis moved {got:.2f}°"
    print(
        f"   夹具自证：{len(decoded)} 帧里亮区主轴转了 {got:.2f}°，作者写进去的是 "
        f"{want:.2f}°（方板主轴按 90° 折叠，所以取带符号的最大那一格）"
    )
    return got


def anchor_fit_measured(decoded: list[bytes], width: int) -> tuple[float, float]:
    """四锚点刚体拟合：逐帧角增量的中位数，和累到最后的总角。"""
    height = len(decoded[0]) // width
    scale = width / W
    cx, cy = CX * scale, CY * scale
    half = MARK * scale / 2
    corners = [
        (cx - half, cy - half),
        (cx + half, cy - half),
        (cx + half, cy + half),
        (cx - half, cy + half),
    ]
    anchors = []
    for ax, ay in corners:
        x0 = max(0, min(width - ANCHOR_PATCH, round(ax) - ANCHOR_PATCH // 2))
        y0 = max(0, min(height - ANCHOR_PATCH, round(ay) - ANCHOR_PATCH // 2))
        crop_x, crop_y, block = _crop(
            decoded[0], width, x0 + ANCHOR_PATCH // 2, y0 + ANCHOR_PATCH // 2, ANCHOR_PATCH
        )
        zero, energy = _zeroed(block)
        anchors.append((crop_x + ANCHOR_PATCH / 2, crop_y + ANCHOR_PATCH / 2, zero, energy))
    current = [(a[0], a[1]) for a in anchors]
    steps = []
    total = 0.0
    for frame in decoded[1:]:
        after = []
        for slot, (_ax, _ay, zero, energy) in enumerate(anchors):
            px, py = current[slot]
            _score, x0, y0 = _match(frame, width, height, zero, ANCHOR_PATCH, energy, px, py, 4)
            here = (x0 + ANCHOR_PATCH / 2, y0 + ANCHOR_PATCH / 2)
            current[slot] = here
            after.append(here)
        step = _rigid_angle([(a[0], a[1]) for a in anchors], after)
        steps.append(abs(step))
        total += step
    return median(steps), total


def absolute_search_measured(decoded: list[bytes], width: int) -> float:
    """把第 0 帧的模板按候选角转过去打分：回的角度与作者写进去的差多少（中位）。"""
    scale = width / W
    cx, cy = CX * scale, CY * scale
    _, _, anchor = _crop(decoded[0], width, round(cx), round(cy), SIDE)
    origin_x, origin_y = round(cx) - SIDE // 2, round(cy) - SIDE // 2
    errors = []
    for index, frame in enumerate(decoded):
        want = math.degrees(RATE * index / FPS)
        best, best_angle = -2.0, 0.0
        angle = -CANDIDATE_SPAN
        while angle <= CANDIDATE_SPAN + 1e-9:
            zero, energy = _zeroed(rotate_template(anchor, SIDE, angle))
            score = _ncc(frame, width, origin_x, origin_y, zero, SIDE, energy)
            if score > best:
                best, best_angle = score, angle
            angle += CANDIDATE_SPAN / 5.0
        # 候选角是相对第 0 帧那一档搜的：转得比窗口还快时，能收进窗口内就算量到了。
        errors.append(abs(best_angle - min(want, CANDIDATE_SPAN)))
    return median(errors)


CAUSAL_STEP = 2.0
TAIL_DRIFT_DEGREES = 4.0


def causal_chain_measured(
    decoded: list[bytes], width: int
) -> tuple[float, float, float]:
    """因果链上的绝对角搜索：每帧只在**上一帧那个角**两侧 ±SPAN 里搜，中心跟着跟踪器走。

    `absolute_search_measured` 量的是「拿第 0 帧当参照、候选角对整段一次性搜」——那是最好情况，
    真正的跟踪器没有整段可看。1.218 把这一条补上，因为只有它说得出「能不能交」：
    交回的是（中位误差、最大误差、末帧误差）。
    """
    scale = width / W
    cx, cy = CX * scale, CY * scale
    height = len(decoded[0]) // width
    _, _, anchor = _crop(decoded[0], width, round(cx), round(cy), SIDE)
    boxes = track_box(
        decoded,
        width,
        (CX / W, CY / H, (MARK + PAD) / W, (MARK + PAD) / H),
        search=6,
        scale=False,
    )["boxes"]
    errors: list[float] = []
    angle = 0.0
    for index, frame in enumerate(decoded):
        if index >= len(boxes):
            break
        centre_x = boxes[index][0] * width
        centre_y = boxes[index][1] * height
        best, best_angle = -2.0, angle
        probe = angle - CANDIDATE_SPAN
        while probe <= angle + CANDIDATE_SPAN + 1e-9:
            zero, energy = _zeroed(rotate_template(anchor, SIDE, probe))
            score, _, _ = _search(
                frame, width, height, zero, SIDE, energy, centre_x, centre_y, 1, 1
            )
            if score > best:
                best, best_angle = score, probe
            probe += CAUSAL_STEP
        truth = math.degrees(RATE * index / FPS)
        errors.append(abs(best_angle - truth))
        angle = best_angle
    return median(errors), max(errors), errors[-1]


def main() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="agentcut-rotation-") as name:
        path = Path(name) / "spin.mp4"
        plate(path)
        width, decoded = analyse_window(FFMPEG, path, W, H, FrameRate(), 0, T // FPS, FRAMES)
        fixture_says_it_rotates(decoded, width)
        step_median, accumulated = anchor_fit_measured(decoded, width)
        search_median = absolute_search_measured(decoded, width)
        causal_median, causal_max, causal_tail = causal_chain_measured(decoded, width)

    per_pixel = math.degrees(2 * math.atan(0.5 / (MARK * (width / W) / 2)))
    print(
        f"   四锚点拟合：逐帧角增量中位 {step_median:.3f}°、{FRAMES} 帧累计 {accumulated:.2f}°"
        f"（作者写进去的是 {math.degrees(RATE * (FRAMES - 1) / FPS):.2f}°）；"
        f"这条 {SIDE} px 基线上一个像素就是 {per_pixel:.2f}°"
    )
    print(f"   模板转角搜索：角度误差中位 {search_median:.2f}°")
    print(
        f"   因果链上的同一件事（每帧只在上一帧那个角两侧 ±{CANDIDATE_SPAN:.0f}° 里搜、"
        f"步长 {CAUSAL_STEP:.0f}°）：中位 {causal_median:.2f}°、最大 {causal_max:.2f}°、"
        f"末帧差 {causal_tail:.2f}°——这一条才是「交出去会长什么样」"
    )

    authored_step = math.degrees(RATE / FPS)
    truth = math.degrees(RATE * (FRAMES - 1) / FPS)
    assert step_median > ANCHOR_NOISE_FACTOR * authored_step, (
        f"四锚点拟合的逐帧角增量中位 {step_median:.2f}°，作者写进去的是每帧 {authored_step:.2f}°——"
        f"这一档钉的是「它是噪声，不是低分辨率的量」（差 {step_median / authored_step:.0f} 倍）。"
        "哪天这个中位落回 5 帧以内，说明锚点真的跟住了，那句『不能交』就要重写、下一轮走这条路"
    )
    assert abs(accumulated) > ANCHOR_NOISE_FACTOR * truth, (
        f"累到 {FRAMES} 帧得到 {accumulated:.1f}°，真相是 {truth:.1f}°："
        "累加不回来这一条不再成立时，这一档的判据要重量"
    )
    assert search_median <= SEARCH_MEDIAN_DEGREES, (
        f"模板转角搜索的误差中位涨到 {search_median:.2f}°（钉的是 "
        f"{SEARCH_MEDIAN_DEGREES}°）——那条能交的路也不稳了，别照着它建"
    )
    assert causal_tail > TAIL_DRIFT_DEGREES, (
        f"因果链的末帧误差只有 {causal_tail:.2f}°"
        f"（钉的是超过 {TAIL_DRIFT_DEGREES:.0f}° 就不许交）——"
        "这条链子稳住了，『遮罩不跟旋转』那句该改写、下一轮就建在这条上；"
        "改的时候记得同时改 README 那一行与 AGENTS 的入口清单"
    )
    print(
        "PASS: 当场量出『四锚点拟合在盒子这条基线上是噪声』（逐帧中位 "
        f"{step_median:.2f}° 对作者每帧 {authored_step:.2f}°、累计 {accumulated:.1f}° 对真相 "
        f"{truth:.1f}°）、『一次性对整段搜能把角收进 {search_median:.2f}°』，"
        f"以及『真跟踪器只能因果地搜：末帧差 {causal_tail:.2f}°』——"
        "旋转那一档不交的理由是这三个数，不是感觉；要交就得让因果链的末帧也进窗口"
    )


if __name__ == "__main__":
    main()
