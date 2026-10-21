"""1.182：阶梯点表每一窗带的是「它自己起点那一格」的值——针在它那一帧必须被执行。

为什么要有这一档：`frame_windows` 是这应用里唯一的阶梯编译器（遮罩那三数与柔焦共用它），它原先取
**段中点**。实测的后果：针在 0/4/8/12 帧、值 0/10/20/30°，第一窗 `[0,2帧)` 却带着 2.5°——也就是人敲
进工程的那一格角度，预览与导出谁都不演；画面上那颗旋转手柄松手后跳回指针之外也是这一处（写 65°，
显示 28.8°）。改成段起点之后两端仍然共用同一份表，只是每窗带哪个数变了。

钉四件事，逐条可反证：
* **每窗 == 该窗起点的采样**：四数（角度、宽、高、软边）逐窗对 `sample(clip, from_ticks)`。
* **针帧被执行**：每一枚针在它自己那一帧上，点表给的就是它自己的值（这是这一档的全部动机）。
* **合并没丢**：曲线前半段摊平成常值时，窗数要掉下来而不是照样一格一窗。
* **柔焦共用同一条规矩**：`spatial_schedule` 也按段起点取值——一把尺量两个消费者。

上限与窗数不在这里钉（`maskbox_check` 与 `maskrot_check`、`planinput_check` 已经在钉），只钉取样点。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agentcut.animation import BOX_STEPS, mask_box_schedule, sample, spatial_schedule
from agentcut.contracts import TIMEBASE, Clip, Keyframe, ShapeMask

F = TIMEBASE // 30
# 1.259：那条窗表从三个数长成四个（软边进来了）。这一档量的就是「每窗带自己起点那一格」，
# 所以轴名单直接取产品那一处的主人——但它的**内容**仍要钉住：少一格就是少一个被量的数。
PROPS = BOX_STEPS


def box_clip() -> Clip:
    """一条 16 帧的片段：三数各自在 0/4/8/12 帧上敲了四枚针，值互不相同。"""
    keys = []
    for index, tick in enumerate((0, 4, 8, 12)):
        keys.append(Keyframe(property="mask_rotation", at_ticks=tick * F, value=10.0 * index))
        keys.append(Keyframe(property="mask_width", at_ticks=tick * F, value=0.30 + 0.05 * index))
        keys.append(Keyframe(property="mask_height", at_ticks=tick * F, value=0.20 + 0.03 * index))
        keys.append(Keyframe(property="mask_feather", at_ticks=tick * F, value=0.02 + 0.04 * index))
    return Clip(
        id="c",
        asset_id="a",
        track_id="v",
        position_ticks=0,
        duration_ticks=16 * F,
        mask=ShapeMask(
            shape="ellipse", center_x=0.5, center_y=0.5, width=0.4, height=0.3, rotation=0.0
        ),
        keyframes=keys,
    )


def executing(schedule: list[dict], at_ticks: int) -> tuple | None:
    for window in schedule:
        if window["from_ticks"] <= at_ticks < window["to_ticks"]:
            return window["value"]
    return None


def window_at(schedule: list[dict], at_ticks: int) -> dict | None:
    for window in schedule:
        if window["from_ticks"] <= at_ticks < window["to_ticks"]:
            return window
    return None


def start_sampled(schedule: list[dict], clip: Clip, props: tuple[str, ...], label: str) -> None:
    bad = []
    for window in schedule:
        want = tuple(round(sample(clip, prop, window["from_ticks"]), 9) for prop in props)
        if tuple(window["value"]) != want:
            bad.append((window["from_ticks"], window["value"], want))
    assert not bad, f"{label}：这些窗带的不是它自己起点那一格的值（起点取样被改了？）：{bad[:3]}"


def needles_execute(clip: Clip, schedule: list[dict], label: str) -> None:
    """每一枚针在它自己那一帧上给的就是它自己的值——四个数都按这一条判。"""
    bad = []
    for key in clip.keyframes:
        got = executing(schedule, key.at_ticks)
        axis = PROPS.index(key.property)
        if got is None or abs(got[axis] - key.value) > 1e-9:
            bad.append((key.property, key.at_ticks // F, key.value, got[axis] if got else None))
    assert not bad, f"{label}：这些针在它自己那一帧没被执行（执行的是别格的数）：{bad}"


def flat_curve_merges() -> int:
    """前半段不动：合并必须把两窗并成一窗，不然「段起点取样」会白付一倍阶段。"""
    clip = box_clip()
    clip.keyframes = [
        Keyframe(property="mask_rotation", at_ticks=0, value=5.0),
        Keyframe(property="mask_rotation", at_ticks=4 * F, value=5.0),
        Keyframe(property="mask_rotation", at_ticks=8 * F, value=40.0),
        Keyframe(property="mask_rotation", at_ticks=12 * F, value=70.0),
    ]
    schedule = mask_box_schedule(clip, F)
    start_sampled(schedule, clip, PROPS, "摊平那一路")
    first = schedule[0]
    assert first["value"][0] == 5.0, f"前两窗没并成一窗：{schedule[:2]}"
    assert first["to_ticks"] > 4 * F, f"常值那一段该合并，实际停在 {first['to_ticks'] // F} 帧"
    return len(schedule)


def blur_shares_the_rule() -> int:
    """柔焦走的是同一个编译器：它的每一窗也必须带自己起点那一格的值。"""
    clip = box_clip()
    clip.keyframes = [
        Keyframe(property="blur", at_ticks=tick * F, value=0.01 * index)
        for index, tick in enumerate((0, 4, 8, 12))
    ]
    schedule = spatial_schedule(clip, "blur", F)
    bad = [
        (
            window["from_ticks"],
            window["value"],
            round(sample(clip, "blur", window["from_ticks"]), 9),
        )
        for window in schedule
        if abs(window["value"] - sample(clip, "blur", window["from_ticks"])) > 1e-9
    ]
    assert not bad, f"柔焦那一档没有按段起点取值，两端与遮罩那一路分家了：{bad[:3]}"
    assert abs(executing(schedule, 0) - 0.0) < 1e-9, "0 帧那枚针在 0 帧上没被执行"
    return len(schedule)


def both_ends_one_table() -> None:
    """同一条表：某一窗的中点与起点给的是两个不同的数时，窗里处处演的必须是起点那个。"""
    clip = box_clip()
    schedule = mask_box_schedule(clip, F)
    window = window_at(schedule, 4 * F)
    assert window is not None
    middle = (window["from_ticks"] + window["to_ticks"]) // 2
    if abs(sample(clip, "mask_rotation", middle) - window["value"][0]) > 1e-9:
        assert abs(sample(clip, "mask_rotation", window["from_ticks"]) - window["value"][0]) < 1e-9
        assert middle != window["from_ticks"], "这份夹具恰好每窗一格，量不出取样点"
    else:
        assert window["to_ticks"] - window["from_ticks"] <= F, "窗宽超过一帧却与中点相同，可疑"


def main() -> None:
    assert PROPS == ("mask_rotation", "mask_width", "mask_height", "mask_feather"), PROPS
    clip = box_clip()
    schedule = mask_box_schedule(clip, F)
    start_sampled(schedule, clip, PROPS, "转过的那一路")
    needles_execute(clip, schedule, "转过的那一路")
    merged = flat_curve_merges()
    blur_windows = blur_shares_the_rule()
    both_ends_one_table()
    print(f"   针帧被执行：{len(schedule)} 窗，逐窗等于段起点采样")
    print("   0/4/8/12 帧上拿到的就是 0/10/20/30°")
    print(f"   常值那一段仍会合并（摊平夹具 {merged} 窗），柔焦同一条规矩（{blur_windows} 窗）")
    print("PASS: 阶梯每窗带自己起点那一格的值——针在它那一帧被执行，两端仍共用同一份表")


if __name__ == "__main__":
    main()
