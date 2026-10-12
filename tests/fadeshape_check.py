"""淡的形状（1.95）：一条边上的淡不再只有缓入缓出那一种走法。

1.90 把淡搬到片段的边上，1.91/1.92 让人在时间线上拖它，
但那条斜坡一直是唯一的一种走法（smoothstep）。
剪映与达芬奇都能选形状，这一版给每条属性的两头一个形状：线性 / 缓入 / 缓出 / 缓入缓出。

它不是新算术。淡本来就是一条普通分段曲线（`fade_curve`），导出编译它、预览动画它，两端读同一份点表；
「形状」就是那条斜坡用哪种插值。默认 `ease_in_out` 就是原来的 smoothstep，所以 1.95 之前写的淡
一字不差地照旧。淡出那一段按时间反演镜像控制点——同一个形状在两条边上摸起来才是一样的。

钉的东西：
* 契约：`FadeShape` 与 `FADE_SHAPES` 必须点名同一组 id（与转场种类同一条规矩），界面读的是
  `capabilities.fade_shapes`，默认必须是 `ease_in_out`；
* reducer：只带形状不带长度的请求保留原窗口；形状与长度可以一次带；两头都空但形状非默认时记录
  不许被丢掉；非法形状与「什么都不带」在契约层就被拒（HTTP 把它翻成 422）；
* 算术：四种形状在 1/4、1/2、3/4 处的因子，`ease_out` 必须是 `1 - ease_in(1-p)`，
  淡出从尾部量回来必须与淡入逐点相同（镜像恒等式）；
* 两端一致：把浏览器要动画的那条下发曲线按它自己声明的 cubic-bezier 段求值，与权威 `fade_factor`
  在几十个点上比——这是「预览等于导出」在这条功能上的说法；
* 成片：黑底上层白块，四种形状各渲一遍，0.25/0.5/0.75 秒的像素对得上 `255 × 因子`（容差 6 阶）。
"""

import tempfile
import typing
from pathlib import Path

from fade_check import (
    SECONDS,
    asset,
    build,
    commands,
    fade_at,
    one_clip,
    opacity_project,
    pixel,
    slate,
)
from pydantic import ValidationError

from agentcut.animation import (
    bezier_parameter,
    bezier_value,
    fade_curve,
    fade_factor,
    preview_manifest,
)
from agentcut.contracts import FADE_SHAPES, SCHEMA_VERSION, FadeEnvelope, FadeShape, capabilities
from agentcut.contracts import TIMEBASE as T
from agentcut.timeline import apply_commands

SHAPES = tuple(item["id"] for item in FADE_SHAPES)
# 权威值：线性与 smoothstep 可以直接写死；ease_out 由镜像恒等式单独验。
QUARTERS = {
    "linear": (0.25, 0.5, 0.75),
    "ease_in_out": (0.15625, 0.5, 0.84375),
}


def contract_suite() -> None:
    literal = sorted(typing.get_args(FadeShape))
    assert literal == sorted(SHAPES), (literal, SHAPES)
    assert all(item["label"] for item in FADE_SHAPES), FADE_SHAPES
    caps = capabilities()
    assert caps["features"]["clip_fade_shapes"] is True, caps["features"]
    assert [item["id"] for item in caps["fade_shapes"]] == list(SHAPES), caps["fade_shapes"]
    assert all(item["label"] for item in caps["fade_shapes"]), caps["fade_shapes"]
    assert FadeEnvelope().opacity_shape == "ease_in_out", "默认必须是 1.95 之前唯一的形状"
    assert FadeEnvelope().gain_shape == "ease_in_out"
    # 淡的形状进的是 v15，轮廓帧进的是 v16：这条断言说的是那段历史，不是今天的当前值——
    # schema 现在等于几由 `contracts.SCHEMA_VERSION` 一处说，README 那一行由 docs_facts_check 钉住。
    assert SCHEMA_VERSION >= 16, SCHEMA_VERSION
    print(f"   契约：{len(SHAPES)} 个形状，Literal 与表点名同一组 id，默认是缓入缓出")


def fade_payload(**fields) -> dict:
    base = {
        "opacity_in_ticks": T,
        "opacity_out_ticks": 0,
        "gain_in_ticks": 0,
        "gain_out_ticks": 0,
    }
    base.update(fields)
    return base


def shape_command(shape=None, duration=None, property="gain", mode="in", clip="c") -> dict:
    payload: dict = {"op": "clip.fade", "clip_id": clip, "property": property, "mode": mode}
    if duration is not None:
        payload["duration_ticks"] = duration
    if shape is not None:
        payload["shape"] = shape
    return payload


def reducer_suite() -> None:
    shaped = apply_commands(one_clip(6), commands(fade_at(T, "in", "gain")))
    assert shaped.clips["c"].fade.gain_shape == "ease_in_out", shaped.clips["c"].fade
    # revision 是 store 的事（`apply_commands` 是纯 reducer），这里只断片段上的状态。
    only_shape = apply_commands(shaped, commands(shape_command("linear")))
    assert only_shape.clips["c"].fade.gain_in_ticks == T, "只改形状不许动窗口"
    assert only_shape.clips["c"].fade.gain_shape == "linear", only_shape.clips["c"].fade

    # 两头都空、只留一个非默认形状：记录不许被丢掉，否则用户下次淡会掉回默认。
    bare = apply_commands(
        one_clip(6), commands(shape_command("ease_out", property="opacity", mode="both"))
    )
    assert bare.clips["c"].fade is not None, "形状是一个选择，不是长度 0"
    assert bare.clips["c"].fade.opacity_shape == "ease_out"
    assert bare.clips["c"].fade.opacity_in_ticks == 0

    # 形状与长度可以一次带（时间线拖角柄与检查器下拉都走这一条命令）。
    both = apply_commands(one_clip(6), commands(shape_command("ease_in", duration=T, mode="out")))
    assert (both.clips["c"].fade.gain_out_ticks, both.clips["c"].fade.gain_shape) == (T, "ease_in")

    # 两个属性互不占用：画面的形状不许顶掉音量的形状。
    mixed = apply_commands(both, commands(shape_command("linear", property="opacity")))
    assert (mixed.clips["c"].fade.opacity_shape, mixed.clips["c"].fade.gain_shape) == (
        "linear",
        "ease_in",
    )

    # 非法形状与「既不给长度也不给形状」都在契约层就被拒，片段上不留痕迹。
    refused = 0
    for bad in ("bounce", "smooth", "", None):
        try:
            commands(shape_command(bad))
            raise AssertionError(f"{bad!r} 不该被当成一次合法的淡写入")
        except ValidationError:
            refused += 1
    assert refused == 4, refused
    assert both.clips["c"].fade.gain_shape == "ease_in", "被拒的请求不许在片段上留下任何痕迹"
    print("   reducer：只带形状保留窗口、一次可带两个字段、空窗口也留得住记录、非法形状契约层就拒")


def shaped_clip(shape: str, **window):
    clip = one_clip(4).clips["c"]
    clip.duration_ticks = SECONDS * T
    clip.fade = FadeEnvelope.model_validate(fade_payload(opacity_shape=shape, **window))
    return clip


def curve_suite() -> None:
    for shape in SHAPES:
        clip = shaped_clip(shape)
        got = tuple(round(fade_factor(clip, "opacity", int(T * p)), 4) for p in (0.25, 0.5, 0.75))
        if shape in QUARTERS:
            assert got == tuple(round(v, 4) for v in QUARTERS[shape]), (shape, got)
        if shape == "ease_out":
            mirror = shaped_clip("ease_in")
            assert got == tuple(
                round(1 - fade_factor(mirror, "opacity", int(T * (1 - p))), 4)
                for p in (0.25, 0.5, 0.75)
            ), (shape, got)
        # 从尾部量回来的淡出，与从头部量过去的淡入必须逐点相同（形状说的是「离边多远」）。
        out = shaped_clip(shape, opacity_in_ticks=0, opacity_out_ticks=T)
        from_tail = tuple(
            round(fade_factor(out, "opacity", int(SECONDS * T - T * p)), 4)
            for p in (0.25, 0.5, 0.75)
        )
        assert from_tail == got, (shape, from_tail, got)
        kinds = {key.interpolation for key in fade_curve(clip, "opacity")}
        expected = (
            {"linear"}
            if shape == "linear"
            else {"linear", "ease"}
            if shape == "ease_in_out"
            else {"linear", "bezier"}
        )
        assert kinds == expected, (shape, kinds)
    print("   算术：四种形状在 1/4、1/2、3/4 处各自对得上，缓出是缓入的时间反演，两头镜像恒等")


class _Axis:
    """`bezier_parameter` 只要一个带 x1/x2 的对象；下发的那段 easing 就是四个数。"""

    def __init__(self, x1: float, x2: float) -> None:
        self.x1, self.x2 = x1, x2


def browser_curve(clip):
    """把下发给浏览器的那条淡曲线按它自己声明的分段求值——浏览器跑的就是这套插值。"""
    project = one_clip(4)
    project.clips["c"] = clip
    points = preview_manifest(project)["clips"]["c"]["fade"]["opacity"]
    ordered = sorted(points, key=lambda item: item["offset"])

    def at(offset: float) -> float:
        left = max(
            (item for item in ordered if item["offset"] <= offset), key=lambda item: item["offset"]
        )
        right = min(
            (item for item in ordered if item["offset"] >= offset), key=lambda item: item["offset"]
        )
        if right["offset"] == left["offset"]:
            return left["value"]
        span = (offset - left["offset"]) / (right["offset"] - left["offset"])
        easing = left["easing"]
        if easing.startswith("cubic-bezier("):
            x1, y1, x2, y2 = map(float, easing[len("cubic-bezier(") : -1].split(","))
            span = bezier_value(y1, y2, bezier_parameter(_Axis(x1, x2), span))
        return left["value"] + (right["value"] - left["value"]) * span

    return ordered, at


def preview_suite() -> None:
    worst = 0.0
    probes = 0
    for shape in SHAPES:
        clip = shaped_clip(shape)
        ordered, at = browser_curve(clip)
        assert len(ordered) >= 3, (shape, ordered)
        for index in range(1, len(ordered) - 1):
            for fraction in (0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875):
                offset = ordered[index - 1]["offset"] + fraction * (
                    ordered[index]["offset"] - ordered[index - 1]["offset"]
                )
                gap = abs(
                    at(offset) - fade_factor(clip, "opacity", int(offset * clip.duration_ticks))
                )
                worst = max(worst, gap)
                probes += 1
                assert gap < 2e-3, (
                    shape,
                    offset,
                    at(offset),
                    fade_factor(clip, "opacity", int(offset * clip.duration_ticks)),
                )
    print(f"   两端一致：浏览器那条分段三次曲线与权威因子在 {probes} 个点上最差差 {worst:.2e}")


def media_suite(folder: Path) -> None:
    white = slate(folder, "w", "0xFFFFFF", False)
    black = slate(folder, "b", "0x000000", False)
    white_asset = asset(white, "white", "video", False)
    black_asset = asset(black, "black", "video", False)
    for shape in SHAPES:
        target = opacity_project(white_asset, black_asset, fade_payload(opacity_shape=shape))
        video, _plan = build(target, folder, f"shape-{shape}.mp4")
        line = []
        for at in (0.25, 0.5, 0.75):
            authority = fade_factor(target.clips["w"], "opacity", int(at * T))
            measured = pixel(video, at)
            assert abs(measured - 255 * authority) <= 6.0, (
                shape,
                at,
                measured,
                round(255 * authority, 1),
            )
            line.append(f"{at}s {measured} 对 {round(255 * authority, 1)}")
        assert pixel(video, 0.0) <= 8, (shape, "开头该是地板")
        assert pixel(video, float(SECONDS) - 0.05) >= 245, (shape, "淡完之后要回到全亮")
        print("   成片", shape, "；".join(line))


def main() -> None:
    contract_suite()
    reducer_suite()
    curve_suite()
    preview_suite()
    with tempfile.TemporaryDirectory(prefix="agentcut-fadeshape-") as scratch:
        media_suite(Path(scratch))
    print(
        "PASS: 淡有四种形状了——契约只有一张表、reducer 允许只改形状、两端读同一条曲线，"
        "四种形状各自渲出对得上传染因子的成片"
    )


if __name__ == "__main__":
    main()
