"""1.123 清晰（unsharp）那两个旋钮可以打关键帧：一条两端共用的窗表，成片量得到它真的在锐化。

1.98 给柔焦排窗的理由在这里同样成立，只是多付一份代价：`gblur` 与 `blend` 的时间钩子都只有 `enable`
那个开/关窗，所以一条清晰曲线编译出来的是一串窗，而每一窗是 `gblur` + `blend` 一对，比柔焦那一段贵。
量过的数写在 `contracts.SHARPEN_SCHEDULE_MAX` 的注释里（八段封顶）。真正要紧的是另一半：强度与半径是
同一个算式的两个数，必须**共用一张窗表**——两条曲线各排各的窗，导出就会串出预览根本没有的那一段。

量什么：

* 窗本身：两段曲线共用一组断点（任一个变了才换窗）、首尾相接、覆盖整段、不越过上限、每段读的是那段
  起点的权威 `sample`；只动强度时半径原样跟着静态旋钮走；一段曲线都没有时一段窗都不排。
* 两端同源：`preview_manifest` 交出的 windows 逐条等于阶梯，id 由那一份内容地址算出；强度为 0
  的那一段在浏览器里是 `none`，因为导出压根不为它串阶段。
* 编译串：N 段非零窗就是 N 对带 `enable` 的 `gblur` 与 `blend`，`split` 只有一处且扇出 N+1；
  没有曲线时静态那三元组一字不变。
* 成片：一张 128/192 的二值棋盘（纯黑纯白没有过冲的余量，量不出锐化），逐窗中点读相邻像素差的均值，
  必须与「整段都用这一窗那两个数」的同路渲染一致，并且沿斜坡一路更锐。
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

from blurkey_check import FRAME, HEIGHT, WIDTH, detail, project_of
from fade_check import SECONDS, asset, build, made_clip, slate
from pydantic import ValidationError

from agentcut.animation import preview_manifest, sample, sharpen_schedule, sharpen_spec
from agentcut.contracts import (
    BLUR_LIMIT,
    PROPERTY_LIMITS,
    SHARPEN_LIMIT,
    SHARPEN_RADIUS_DEFAULT,
    SHARPEN_SCHEDULE_MAX,
    SPATIAL_SCHEDULE_MAX,
    Clip,
    Keyframe,
    capabilities,
)
from agentcut.contracts import TIMEBASE as T
from agentcut.render import compile_render_plan, focus_radius

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
FFMPEG = Path(__file__).resolve().parent.parent / "desktop" / "resources" / "bin" / "ffmpeg.exe"
DURATION = SECONDS * T
# 半径按画面高折算，所以这两个数是「画面高的百分之几」：一格一像素与三格多一像素的两种模糊。
THIN = SHARPEN_RADIUS_DEFAULT
THICK = 0.02


def sharp_clip(
    points: list[tuple[str, int, float, str]] = (),
    duration: int = DURATION,
    amount: float = 0.0,
    radius: float = THIN,
) -> Clip:
    """一张棋盘上的被测片段：曲线是要测的东西，静态旋钮是它的对照。"""
    clip = made_clip("v2", "w", "board", None)
    clip.duration_ticks = duration
    clip.effects.blur = 0.0
    clip.effects.sharpen = amount
    clip.effects.sharpen_radius = radius
    clip.keyframes = [
        Keyframe(property=prop, at_ticks=at, value=value, interpolation=kind)
        for prop, at, value, kind in points
    ]
    return clip


def ramp(duration: int = DURATION) -> list[tuple[str, int, float, str]]:
    return [("sharpen", 0, 0.0, "linear"), ("sharpen", duration, SHARPEN_LIMIT, "linear")]


def hold_pair() -> list[tuple[str, int, float, str]]:
    """三条窗：按住不动的 0，只换半径的 0，最后才是真的锐。断点必须两段曲线共用。"""
    return [
        ("sharpen", 0, 0.0, "hold"),
        ("sharpen", 2 * T, SHARPEN_LIMIT, "hold"),
        ("sharpen_radius", 0, THIN, "hold"),
        ("sharpen_radius", 1 * T, THICK, "hold"),
    ]


def pairs(plan: list[dict]) -> list[tuple[float, float]]:
    return [window["value"] for window in plan]


def schedule_suite() -> None:
    clip = sharp_clip(ramp())
    plan = sharpen_schedule(clip, FRAME)
    assert plan, "有曲线的清晰旋钮必须排出窗"
    assert plan[0]["from_ticks"] == 0 and plan[-1]["to_ticks"] == DURATION, plan
    assert len(plan) <= SHARPEN_SCHEDULE_MAX, f"[sk-cap] 段数越过下发的上限：{len(plan)}"
    for left, right in zip(plan, plan[1:]):
        assert left["to_ticks"] == right["from_ticks"], (
            "[sk-contiguous] 段与段必须首尾相接，不留缝也不重叠"
        )
    amounts = [value[0] for value in pairs(plan)]
    assert amounts == sorted(amounts), f"从 0 拉到顶的强度不该回头：{amounts}"
    # 只动强度时，半径就是那颗静态旋钮，每一窗都读同一个数。
    assert {value[1] for value in pairs(plan)} == {THIN}, "[sk-radius-static] pairs(plan)"
    for window in plan:
        start = window["from_ticks"]
        assert window["value"] == (
            round(sample(clip, "sharpen", start), 9),
            round(sample(clip, "sharpen_radius", start), 9),
        ), f"[sk-start] 这段没取它起点那一格的数：{window}"
    step = plan[1]["from_ticks"] - plan[0]["from_ticks"]
    assert step % FRAME == 0 and step >= FRAME, f"段边界必须落在整帧上：{step}"
    # 八段的上限是真的在收：12 帧的片段这里两帧一窗，而柔焦（24 段）一帧一窗。
    short = sharp_clip(ramp(12 * FRAME), 12 * FRAME)
    fine = sharpen_schedule(short, FRAME)
    assert len(fine) == 6, f"[sk-grid] 12 帧片段八段封顶该是 6 窗两帧一跳：{len(fine)}"
    assert all(
        b - a == 2 * FRAME
        for a, b in zip([w["from_ticks"] for w in fine], [w["from_ticks"] for w in fine[1:]])
    )
    blur_fine = preview_of(short)["spatial"]
    assert blur_fine is None, "这张片段没有柔焦曲线"
    # 共用断点：半径先换、强度后换，于是三窗，而各自单独排都会少一段。
    both = sharp_clip(hold_pair())
    union = sharpen_schedule(both, FRAME)
    assert pairs(union) == [(0.0, THIN), (0.0, THICK), (SHARPEN_LIMIT, THICK)], (
        "[sk-union] 两段曲线没共用断点"
    )
    edges = [window["to_ticks"] for window in union]
    assert edges[-1] == DURATION and all(edge % FRAME == 0 for edge in edges), union
    assert edges == sorted(edges) and edges[0] < edges[1], union
    # 两个数都没变的那些窗被合并：全程一个数就只有一段。
    flat = sharpen_schedule(sharp_clip(hold_pair()[:2], amount=1.0, radius=THIN), FRAME)
    assert len(flat) >= 2, "强度有曲线就该分段"
    still = sharpen_schedule(sharp_clip([], amount=1.0, radius=THIN), FRAME)
    assert still == [], "[sk-none] 没有曲线也排出了窗"
    print(
        f"   阶梯：{len(plan)} 段覆盖整段、首尾相接、步长 {step / FRAME:g} 帧；12 帧片段两帧一段"
        f"（柔焦上限 {SPATIAL_SCHEDULE_MAX} 段时是一帧一段），共用断点排出 {len(union)} 段"
    )


def preview_of(clip: Clip) -> dict:
    board = {
        "id": "board",
        "kind": "video",
        "label": "b",
        "reference": "r",
        "duration_ticks": DURATION,
    }
    black = {
        "id": "black",
        "kind": "video",
        "label": "k",
        "reference": "r",
        "duration_ticks": DURATION,
    }
    return preview_manifest(project_of(clip, board, black))["clips"]["w"]


def both_ends_suite() -> None:
    clip = sharp_clip(ramp())
    plan = sharpen_schedule(clip, FRAME)
    manifest = preview_of(clip)
    issued = manifest["sharpen"]
    assert "windows" in issued and "curve" in issued, issued
    assert len(issued["windows"]) == len(plan), "[sk-manifest] 下发的窗数与阶梯不等"
    for entry, window in zip(issued["windows"], plan, strict=True):
        amount, radius = window["value"]
        assert (entry["from_ticks"], entry["to_ticks"]) == (
            window["from_ticks"],
            window["to_ticks"],
        ), entry
        assert entry["amount"] == amount and entry["bbox"][1] == round(radius, 6), entry
        # id 只由那一份内容地址算出：同一个数的另一窗必须复用同一个 def。
        assert entry["id"] == sharpen_spec(amount, radius, WIDTH, HEIGHT)["id"], entry
    for point, window in zip(issued["curve"], plan, strict=True):
        assert point["offset"] == window["from_ticks"] / clip.duration_ticks, point
        assert point["easing"] == "steps(1, end)", "浏览器必须一格一步，不许自己插值"
        assert point["id"] == window_id(issued, window), point
    # 强度为 0 的那一段：导出不为它串阶段，界面也必须显示 `none`。
    stepped = preview_of(sharp_clip(hold_pair()))
    zero = [entry for entry in stepped["sharpen"]["windows"] if entry["amount"] == 0]
    assert len(zero) == 2, zero
    assert [point["id"] for point in stepped["sharpen"]["curve"][:2]] == [None, None], (
        "[sk-zero] 零强度的那窗在浏览器里还挂着一个 def"
    )
    assert all(entry["id"] for entry in stepped["sharpen"]["windows"][2:]), stepped
    # 有曲线时静态那份 url 必须从 `color_filter` 里离开，否则第一窗被算两遍。
    assert "url(" not in stepped["color_filter"], "[sk-url] 有曲线时静态那份 url 还留在串里"
    assert stepped["edge_filter"] is None, stepped["edge_filter"]
    plain = preview_of(sharp_clip([], amount=1.0))
    assert "windows" not in plain["sharpen"] and "url(" in plain["color_filter"], (
        "[sk-static-shape] 没曲线那片被换成了窗表"
    )
    # 静态旋钮开着、同时又有一条曲线：那一份静态 url 也必须离开串——不然第一窗被算两遍。
    both_preview = preview_of(sharp_clip(hold_pair(), amount=0.5))
    assert "url(" not in both_preview["color_filter"], "[sk-double] 静态 url 与窗表同时在串里"
    assert both_preview["edge_filter"] is None, "[sk-double] 窗表与静态那份 def 各画了一遍"

    caps = capabilities(True, False, False)
    assert caps["features"]["sharpen_keyframes"] is True, "[sk-feature] 能力位没随字段下发"
    assert caps["limits"]["sharpen_schedule_segments"] == SHARPEN_SCHEDULE_MAX, (
        "[sk-limit-field] 段数上限没下发"
    )
    assert SHARPEN_SCHEDULE_MAX < SPATIAL_SCHEDULE_MAX, "一窗一对阶段，上限必须比柔焦小"
    # 契约层：两颗旋钮进来了，降噪仍然进不来；曲线的带与静态字段的带是同一份。
    Keyframe(property="sharpen", at_ticks=0, value=1.0, interpolation="ease")
    Keyframe(property="sharpen_radius", at_ticks=0, value=THICK, interpolation="ease")
    assert PROPERTY_LIMITS["sharpen"] == (0.0, SHARPEN_LIMIT), (
        "[sk-limits] 强度的带不是那颗旋钮的带"
    )
    assert PROPERTY_LIMITS["sharpen_radius"] == (0.0, BLUR_LIMIT), (
        "[sk-limits] 半径的带不是柔焦那条带"
    )
    for bad, value in (("sharpen", SHARPEN_LIMIT + 0.01), ("sharpen_radius", BLUR_LIMIT + 0.01)):
        try:
            Keyframe(property=bad, at_ticks=0, value=value)
            raise AssertionError(f"[sk-band] {bad} 越过旋钮上限的曲线值被收下了")
        except ValidationError:
            pass
    try:
        Keyframe(property="denoise", at_ticks=0, value=1.0)
        raise AssertionError("[sk-denoise] 降噪没有浏览器那一端，仍不该能当关键帧属性")
    except ValidationError:
        pass
    print(
        f"   两端同源：{len(plan)} 段窗逐条出现在下发的点表里，两段零强度的窗在浏览器是 none，"
        "有曲线时静态 url 不再留在 color_filter 里"
    )


def window_id(issued: dict, window: dict) -> str | None:
    """那一段在浏览器里该用哪个 def：按 from_ticks 找，而不是按序号——曲线与窗必须靠时刻对齐。"""
    for entry in issued["windows"]:
        if entry["from_ticks"] == window["from_ticks"]:
            return entry["id"] if entry["amount"] > 0 else None
    raise AssertionError(f"曲线里出现了一段窗表没有的时刻：{window}")


def chain_suite(folder: Path) -> list[Path]:
    """编译串的形状：一次 split、每窗一对带 enable 的阶段；没有曲线时那三元组一字不变。"""
    board, black = board_file(folder), slate(folder, "sk", "0x000000", False)
    board_asset, black_asset = (
        asset(board, "board", "video", False),
        asset(black, "black", "video", False),
    )
    clip = sharp_clip(ramp(), board_asset["verified"]["duration_ticks"])
    project = project_of(clip, board_asset, black_asset)
    plan = sharpen_schedule(clip, FRAME)
    graph = "\n".join(compile_render_plan(project, "h264-source-quality").filters)
    nonzero = [window for window in plan if window["value"][0] > 0]
    gates = re.findall(
        r"gblur=sigma=([\d.]+):steps=6:planes=7:enable='between\(t,([\d.]+),([\d.]+)\)'", graph
    )
    # 抓三元组的那一条式子按导出自己的写法拼出来：三个通道各一份同一条 expr。alpha 那一份单独数，
    # 否则「把 alpha 也锐了」这一条与「阶段数」这一条会挤在同一条正则上，谁红都说不清。
    step = r"clip\(A\+([\d.]+)\*\(A-B\),0,255\)"
    blends = re.findall(
        "blend="
        + ":".join(f"c{plane}_expr='{step}'" for plane in (0, 1, 2))
        + r":c3_expr='[^']*':enable='between\(t,([\d.]+),([\d.]+)\)'",
        graph,
    )
    assert len(gates) == len(nonzero), "[sk-stages] 模糊的阶段数不是非零窗数"
    assert len(blends) == len(nonzero), "[sk-blend-stages] 相加的阶段数不是非零窗数"
    assert graph.count(":c3_expr='A'") == len(nonzero), "[sk-alpha] 锐化碰到了遮罩的透明度"
    assert graph.count("split=") == 1 and f"split={len(nonzero) + 1}" in graph, (
        "[sk-split] 扇出不对"
    )
    # 零强度的那两窗不为它们串阶段：三窗只串一对，扇出也只多两个头。
    held_clip = sharp_clip(hold_pair(), board_asset["verified"]["duration_ticks"])
    held_graph = "\n".join(
        compile_render_plan(
            project_of(held_clip, board_asset, black_asset), "h264-source-quality"
        ).filters
    )
    assert len(sharpen_schedule(held_clip, FRAME)) == 3, "[sk-zerostage] 那三窗的排法变了"
    assert held_graph.count("blend=c0_expr=") == 1, (
        f"[sk-zerostage] 零强度那窗也串了阶段：{held_graph.count('blend=c0_expr=')}"
    )
    # 半径随窗走的证据只能在**半径真的变过**的那条片段上看：斜坡那片半径一直是静态旋钮，
    # 把它换成静态值是一个看不出来的空突变（1.123 突变跑出来的教训）。
    held_sigmas = re.findall(r"gblur=sigma=([\d.]+)", held_graph)
    held_pairs = [
        window["value"] for window in sharpen_schedule(held_clip, FRAME) if window["value"][0] > 0
    ]
    assert held_sigmas == [
        f"{focus_radius(pair[1], 'sharpen_radius', HEIGHT):.4f}" for pair in held_pairs
    ], f"[sk-sigma] 每一窗的半径没走到 sigma：{held_sigmas} 对 {held_pairs}"
    for (radius, start, stop), (a0, a1, a2, blend_start, blend_stop), window in zip(
        gates, blends, nonzero, strict=True
    ):
        amount, fraction = window["value"]
        assert radius == f"{focus_radius(fraction, 'sharpen_radius', HEIGHT):.4f}", (
            f"[sk-sigma] 第 {window['from_ticks']} 窗的半径没进 sigma"
        )
        assert {a0, a1, a2} == {f"{amount}"}, f"[sk-amount] 这一窗的强度没进表达式：{a0}"
        for text, ticks in ((start, window["from_ticks"]), (stop, window["to_ticks"])):
            assert text == f"{ticks / T:.6f}", f"[sk-time] 窗边界不是那一段的秒数：{text}"
        assert (blend_start, blend_stop) == (start, stop), (
            "[sk-samewindow] 模糊与相加不在同一个窗里"
        )
    static = project_of(sharp_clip([], amount=1.0), board_asset, black_asset)
    plain = "\n".join(compile_render_plan(static, "h264-source-quality").filters)
    assert plain.count("gblur=sigma=") == 1, "[sk-static-string] 静态那片不止一个模糊"
    segment = plain.split("gblur=sigma=")[1].split("[")[0]
    assert ":enable" not in segment, f"[sk-static-string] 静态那一段带了窗：{segment}"
    assert plain.count("blend=c0_expr") == 1, "[sk-static-string] 静态那片不止一次相加"
    assert "blend=c0_expr='clip(A+1.0*(A-B),0,255)'" in plain, "[sk-static-string] 静态式子被改写"
    return [board, black]


def board_file(folder: Path) -> Path:
    """一张静止的 128/192 棋盘：锐化要在两边都留得下过冲，纯黑纯白一夹就顶满。"""
    target = folder / "board123.mp4"
    done = subprocess.run(
        [
            str(FFMPEG),
            "-y",
            "-f",
            "lavfi",
            "-i",
            (
                f"nullsrc=s={WIDTH}x{HEIGHT}:r=25:d={SECONDS},"
                "geq=lum='128+64*mod(floor(X/2)+floor(Y/2)\\,2)':cb=128"
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
    board, black = board_file(folder), slate(folder, "sm", "0x000000", False)
    board_asset, black_asset = (
        asset(board, "board", "video", False),
        asset(black, "black", "video", False),
    )
    duration = board_asset["verified"]["duration_ticks"]

    def render(clip: Clip, name: str) -> Path:
        built, _ = build(project_of(clip, board_asset, black_asset), folder, name)
        return built

    def reference(amount: float, radius: float) -> float:
        """整段都用这一对数、且**没有曲线**的同路渲染：与阶梯比的就是它。"""
        return detail(render(sharp_clip([], duration, amount, radius), f"ref{amount:.3f}.mp4"), 1.0)

    clip = sharp_clip(ramp(duration), duration)
    plan = sharpen_schedule(clip, FRAME)
    delivered = render(clip, "sharpenkey.mp4")
    picked = [plan[0], plan[len(plan) // 2], plan[-1]]
    read = []
    for window in picked:
        amount, radius = window["value"]
        at = min((window["from_ticks"] + window["to_ticks"]) / 2 / T, duration / T - 0.02)
        read.append((amount, detail(delivered, at), reference(amount, radius)))
    for amount, got, want in read:
        assert abs(got - want) <= max(0.5, want * 0.1), (
            f"[sk-media] {amount} 那窗读到的不是同路渲染：{got}"
        )
    steps = [row[1] for row in read]
    assert steps[0] < steps[1] < steps[2], f"[sk-rise] 沿斜坡没有一路更锐：{steps}"
    assert steps[2] > steps[0] * 1.05, (
        f"从第一段到最后一段看不出在锐化：{steps[0]:.2f} 对 {steps[2]:.2f}"
    )

    # 零强度的那两窗必须与完全不锐化的原片同幅同样：导出根本不为它串阶段。
    held = sharp_clip(hold_pair(), duration)
    held_windows = sharpen_schedule(held, FRAME)
    flat = render(held, "sharpenhold.mp4")
    plain = reference(0.0, THIN)
    for window in held_windows[:2]:
        at = (window["from_ticks"] + window["to_ticks"]) / 2 / T
        got = detail(flat, at)
        assert abs(got - plain) <= max(0.5, plain * 0.1), f"[sk-zerowin] 零强度那窗不是原片：{got}"
    last = held_windows[-1]
    at = (last["from_ticks"] + last["to_ticks"]) / 2 / T
    sharp_last = reference(SHARPEN_LIMIT, THICK)
    assert abs(detail(flat, at) - sharp_last) <= max(0.5, sharp_last * 0.1), (
        "[sk-hold] 最后那窗读的不是那一对数",
        detail(flat, at),
    )
    print(
        f"   成片：{len(plan)} 段窗里逐点取了 3 段，与「整段同一对数」的同路渲染分别差 "
        f"{max(abs(got - want) for _, got, want in read):.2f} 以内，"
        f"细节从 {steps[0]:.2f} 涨到 {steps[2]:.2f}；零强度的两窗读到的就是原片 {plain:.2f}"
    )


def main() -> None:
    schedule_suite()
    both_ends_suite()
    with tempfile.TemporaryDirectory(prefix="agentcut-sharpenkey-") as scratch:
        chain_suite(Path(scratch))
        media_suite(Path(scratch))
    print("PASS: 清晰的强度与半径共用一张窗表，编译、预览与成片读的都是它，零窗不串阶段")


if __name__ == "__main__":
    main()
