"""1.193 的引擎账：「叠一层原图」这一条边交给浏览器画，但**画不画得了由引擎说一次**。

`tests/composite_check.py` 已经量过导出那两步落到像素（`(1-mix)·raw + mix·mode(graded, raw)`），
这一档不重跑像素，钉的是清单这一头新立的四件事：

1. 有这条边才交回 `composite` 那一行，`mode`/`mix` 与 `grade.composite_stages` 逐字相同
   ——界面读的就是导出读的那一份，不许有第二次换算；
2. `paintable` 只由素材记录决定：图像且有过一次真的探测为真，视频、悬空引用、没探测过的都假，
   且这个判断只在这一个函数里；
3. 这一级**不进** CSS 滤镜串——它是 DOM 上的一层，混进 `color_filter` 就等于让「已调色」
   那层自己与原图相合两次（导出可没有这一份）；
4. 一条链最多一条这一级（`COMPOSITE_LIMIT`）仍然成立，界面才敢只读一行。
"""

from agentcut.animation import composite_row, preview_manifest
from agentcut.contracts import (
    Asset,
    Clip,
    ClipColor,
    EditorError,
    GradeComposite,
    Project,
    Track,
    capabilities,
)
from agentcut.grade import composite_stages, grade_filter, grade_tables, preview_grade

T = 70_560_000
MODES = ["normal", "multiply", "screen", "overlay", "darken", "lighten", "difference", "exclusion"]


def build(kind: str, edges: list[GradeComposite], probed: bool = True) -> Project:
    media = {"id": "as", "kind": kind, "label": "素材", "reference": "media://x"}
    if kind in ("video", "audio"):
        media["duration_ticks"] = T  # 契约要求：这两类元数据里得有长度
    if probed:
        # 真的探测记录：界面那一头拿到的地址来自这里，所以 `paintable` 问的就是这一条在不在。
        media["verified"] = {
            "probe_id": "pr", "path": "media/x.png", "kind": kind, "label": "素材",
            "size_bytes": 1024, "content_sha256": "0" * 64, "duration_ticks": T,
            "width": 640, "height": 360,
        }
    return Project(
        id="p",
        name="p",
        tracks=[Track(id="v", kind="video", name="画面")],
        assets={"as": Asset(**media)},
        clips={
            "c": Clip(
                id="c",
                asset_id="as",
                track_id="v",
                position_ticks=0,
                duration_ticks=T,
                color=ClipColor(grade=edges),
            )
        },
    )


def main() -> None:
    caps = capabilities()
    assert caps["features"]["composite_preview"] is True, caps["features"]

    # 1) 没有这条边：清单里那一行就是 None，界面那一路一颗像素都不许多画
    plain = build("image", [])
    assert preview_manifest(plain)["clips"]["c"]["composite"] is None
    assert composite_row(plain.clips["c"], plain) is None

    # 2) 八种方式逐条：mode/mix 与 `composite_stages` 逐字相同（一份说法，两个消费者）
    for index, mode in enumerate(MODES):
        mix = 0.125 * (index + 1)
        held = build("image", [GradeComposite(mode=mode, mix=mix)])
        given = preview_manifest(held)["clips"]["c"]["composite"]
        stages = composite_stages(held.clips["c"].color)
        assert given == {"mode": mode, "mix": mix, "paintable": True}, (mode, given)
        assert len(stages) == 1, stages
        assert (given["mode"], given["mix"]) == (stages[0]["mode"], stages[0]["mix"]), stages

    # 3) paintable 只由素材是什么决定：同一条边换到视频素材上就是 False
    moving = build("video", [GradeComposite(mode="multiply", mix=0.5)])
    assert preview_manifest(moving)["clips"]["c"]["composite"] == {
        "mode": "multiply", "mix": 0.5, "paintable": False,
    }, moving
    # 素材引用悬着（老工程里被删掉）也不许猜成真——宁可少画一层，不画一张没根据的画
    broken = build("image", [GradeComposite(mode="screen", mix=0.5)])
    broken.assets = {}
    assert composite_row(broken.clips["c"], broken)["paintable"] is False, broken
    # 图像素材但记录里没有那一次真的探测：界面拿到的是空地址，画出来是两个空 `<img>`
    # 叠在「素材离线或未导入」那句上——那不是第二幅画，所以这一档也是假。
    unprobed = build("image", [GradeComposite(mode="screen", mix=0.5)], probed=False)
    assert unprobed.assets["as"].kind == "image" and unprobed.assets["as"].verified is None
    assert composite_row(unprobed.clips["c"], unprobed)["paintable"] is False, unprobed

    # 4) 这一级不进 CSS 滤镜串：挂着它与不挂时 `color_filter` 逐字节相同；
    #    阶段表里它在（滤镜定义的 id 要盖住这一级），但界面能画的那份阶段表里没有它
    edge = GradeComposite(mode="screen", mix=0.5)
    assert grade_filter(ClipColor(grade=[edge])) == grade_filter(ClipColor(grade=[]))
    tables = grade_tables(ClipColor(grade=[edge]))
    assert [stage["type"] for stage in tables["stages"]] == ["composite"], tables
    assert tables["stages"][0]["preview"] is False, tables
    assert tables["id"] != grade_tables(
        ClipColor(grade=[GradeComposite(mode="multiply", mix=0.5)])
    )["id"], "换了方式，滤镜定义的 id 不能不动"
    drawn = preview_grade(ClipColor(grade=[edge]))
    assert drawn is None or all(
        stage["type"] != "composite" for stage in drawn["stages"]
    ), drawn

    # 5) 一条链最多一条这一级：两条边在契约层就拒，句子点名出路
    try:
        ClipColor(grade=[GradeComposite(mode="screen", mix=0.5), GradeComposite(mode="multiply")])
    except EditorError as refused:
        assert refused.code == "COMPOSITE_LIMIT", refused.code
        assert "嵌套合成" in refused.message or "另一条" in refused.message, refused.message
    else:
        raise AssertionError("两条第二输入边没被点名拒绝")

    print(
        "PASS: 这一条边只在清单里说一次——八种方式与 `composite_stages` 逐字相同、"
        "paintable 只由素材记录决定（视频、悬空引用、没有那次探测都是假）、"
        "不进 CSS 滤镜串、两条边仍按 COMPOSITE_LIMIT 拒"
    )


if __name__ == "__main__":
    main()
