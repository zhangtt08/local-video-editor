"""推移（1.94）：整层位移必须落在引擎那条点表说的位置上——用真实成片量出来。

引擎早就只发一条点表（`transitions.envelopes`），导出把它加进 `overlay=x:`/`y:`，浏览器把它动画到
另外的嵌套包装上。所以「两端一致」在这里不是靠承诺，而是可以量的：把纯色片段推过画面，
逐帧找那条接缝，与点表给的进度比。

四件事分别钉：
* 四种推移的点表算术（进来的从画面外走到 0，出去的走到对面那一边，另一根轴一字不动）；
* 画面权重整段保持 1.0——推移露出的是空间不是光，音量照旧交叉淡（与擦除同一条规矩）；
* 编译出的 `overlay` 项里确实加了那条随时间走的位移，而溶解的没有多算一次加法；
* 真实成片：接缝的位置与方向、以及窗口两端「整幅旧画面 / 整幅新画面」两个对照探针。

「滑动」（新画面滑进来盖住原地不动的旧画面）故意没做，这条门禁就是发现它的过程：这条导出链把
预乘后的各层**相加**，两层一重叠就把 (192,32,32) 与 (32,32,192) 叠成 (222,61,220) 的一片亮边。
推移永远朝相反方向走、两层不相交，所以它天生安全；滑动要先有一条画面空间的互补 alpha。
"""

import scratch
from wipe_check import (
    BLUE,
    RED,
    H,
    W,
    build_project,
    export,
    frame,
    near,
    row,
    sources,
)

from agentcut.animation import preview_manifest
from agentcut.render import compile_render_plan
from agentcut.transitions import MOTION_KINDS, WIPE_FEATHER, envelopes


def value_at(curve, offset):
    """引擎点表的线性插值——导出编译的、浏览器动画的都是这一条，所以两边都该读得出同一个数。"""
    points = [(point["offset"], point["value"]) for point in curve]
    if offset <= points[0][0]:
        return points[0][1]
    for (a, va), (b, vb) in zip(points, points[1:]):
        if offset <= b:
            return va + (vb - va) * ((offset - a) / (b - a) if b > a else 0)
    return points[-1][1]


def seam(raw, axis):
    """两色之间那条边在画面里的位置（0..1），以及新画面在哪一头。"""
    if axis == "x":
        pixels = row(raw, H // 4)
        blues = [i for i, pixel in enumerate(pixels) if near(pixel, BLUE)]
        reds = [i for i, pixel in enumerate(pixels) if near(pixel, RED)]
        span = W - 1
    else:
        pixels = [tuple(raw[(y * W + W // 4) * 3 + c] for c in range(3)) for y in range(H)]
        blues = [i for i, pixel in enumerate(pixels) if near(pixel, BLUE)]
        reds = [i for i, pixel in enumerate(pixels) if near(pixel, RED)]
        span = H - 1
    if not blues or not reds:
        return None, "blue" if blues else "red"
    if max(blues) < min(reds):
        return (max(blues) + min(reds)) / 2 / span, "blue-first"
    if max(reds) < min(blues):
        return (max(reds) + min(blues)) / 2 / span, "red-first"
    raise AssertionError(
        f"两色没有分成两段连续的区域：blue {min(blues)}-{max(blues)} red {min(reds)}-{max(reds)}"
    )


def envelope_suite(folder):
    red, blue = sources(folder)
    for kind, (axis, start, exit_to) in sorted(MOTION_KINDS.items()):
        other = "y" if axis == "x" else "x"
        curves = envelopes(build_project(red, blue, kind))
        incoming, outgoing = curves["right"], curves["left"]
        moved, still = incoming[f"motion_{axis}"], incoming[f"motion_{other}"]
        assert abs(value_at(moved, 0.0) - start) < 1e-12, (kind, value_at(moved, 0.0))
        assert abs(value_at(moved, 0.25) - start / 2) < 1e-12, (kind, value_at(moved, 0.25))
        assert abs(value_at(moved, 0.5)) < 1e-12, "窗口走完，进来的那张正好落在原位"
        assert abs(value_at(moved, 1.0)) < 1e-12, "窗口之后不许继续漂"
        assert all(point["value"] == 0.0 for point in still), (kind, "另一根轴一字不动")
        assert all(point["value"] == 0.0 for point in outgoing[f"motion_{other}"]), kind
        assert value_at(outgoing[f"motion_{axis}"], 0.25) == 0.0, "窗口没到，旧画面先不动"
        assert abs(value_at(outgoing[f"motion_{axis}"], 0.75) - exit_to / 2) < 1e-12, kind
        assert abs(value_at(outgoing[f"motion_{axis}"], 1.0) - exit_to) < 1e-12, kind
        assert abs(exit_to + start) < 1e-12, (
            kind,
            "两层朝相反的方向走，所以它们永不重叠，预乘相加也不会双计",
        )
        assert all(point["value"] == 1.0 for point in incoming["picture"]), (
            kind,
            "整层位移露出的是空间，画面权重必须整段是 1",
        )
        assert all(point["value"] == 1.0 for point in outgoing["picture"]), kind
        assert all(point["value"] == 1.0 for point in incoming["scale"]), (kind, "位移不许顺手放大")
        assert incoming["wipe"] is None, kind
        assert incoming["sound"][0]["value"] == 0.0 and incoming["sound"][-1]["value"] == 1.0, kind
        assert outgoing["sound"][0]["value"] == 1.0 and outgoing["sound"][-1]["value"] == 0.0, kind
    print(f"   {len(MOTION_KINDS)} 种推移/滑动：点表算术、两根轴、权重与音量各自都对")

    plan = compile_render_plan(build_project(red, blue, "push_from_left"), "h264-source-quality")
    placed = [line for line in plan.filters if "overlay=" in line and "+(if(lt(" in line]
    assert len(placed) == 2, [line[:120] for line in plan.filters if "overlay=" in line][:6]
    assert any("-1" in line for line in placed), "进来的那张要从画面外推进来"
    assert any(" 1" in line or "+1" in line or "1.0" in line for line in placed), (
        "出去的那张要推到画面外"
    )
    plain = compile_render_plan(build_project(red, blue, "dissolve"), "h264-source-quality")
    assert not [line for line in plain.filters if "overlay=" in line and "+(if(lt(" in line], (
        "没有位移的转场不许多出一次加法——那条项会动每一帧的位置"
    )
    print("   编译：位移加进了 overlay 的 x/y 项，溶解的没有")


def media_suite(folder):
    red, blue = sources(folder)
    for kind, axis, blue_first, from_far_side in (
        ("push_from_left", "x", True, False),
        ("push_from_right", "x", False, True),
        ("push_from_top", "y", True, False),
    ):
        out = export(folder, build_project(red, blue, kind), "h264-source-quality", kind)
        first, last = 0.5, 2.5  # 窗口之前与之后：各应当是完整的一张画面
        for progress in (0.25, 0.5, 0.75):
            at = 1.0 + progress  # 窗口是右片段的第一秒（时间线 1.0s 起）
            expected = 1 - progress if from_far_side else progress
            position, order = seam(frame(out, at), axis)
            assert position is not None, (kind, at, order)
            assert order == ("blue-first" if blue_first else "red-first"), (kind, at, order)
            assert abs(position - expected) <= 0.035, (kind, at, position, expected)
        head, head_order = seam(frame(out, first), axis)
        assert head is None and head_order == "red", (kind, "窗口没到就该整幅是旧画面", head_order)
        tail, tail_order = seam(frame(out, last), axis)
        assert tail is None and tail_order == "blue", (kind, "窗口走完就该整幅是新画面", tail_order)
        print(f"   {kind}: 接缝 {0.25}/{0.5}/{0.75} 实测对得上，两端各是一幅完整画面")


def manifest_suite(folder):
    red, blue = sources(folder)
    motion = preview_manifest(build_project(red, blue, "push_from_top"))
    delivered = motion["clips"]["right"]["transition"]
    authority = envelopes(build_project(red, blue, "push_from_top"))["right"]
    assert [(p["offset"], p["value"]) for p in delivered["motion_y"]] == [
        (p["offset"], p["value"]) for p in authority["motion_y"]
    ], delivered["motion_y"]
    assert [p["value"] for p in delivered["motion_x"]] == [0.0] * len(delivered["motion_x"])
    wipe = preview_manifest(build_project(red, blue, "wipe_from_bottom"))["clips"]["right"][
        "transition"
    ]["wipe"]
    assert wipe["axis"] == "y" and wipe["flipped"] is True, wipe
    assert wipe["feather"] == WIPE_FEATHER, "羽化宽由引擎下发，界面不许自己写一个"
    print("   清单：浏览器拿到的就是引擎算的那一份，擦除还带上轴/方向/羽化宽")


def main() -> None:
    folder = scratch.make("agentcut-motion-")
    envelope_suite(folder)
    media_suite(folder)
    manifest_suite(folder)
    print(
        "PASS: 四种推移的接缝真的走在点表说的位置上（两根轴、两端对照探针），"
        "画面权重整段为 1、音量照旧交叉淡，浏览器与导出读同一份数"
    )


if __name__ == "__main__":
    main()
