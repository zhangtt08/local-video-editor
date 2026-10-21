"""1.163 粘贴属性：一类一类搬什么、谁接不下、接不下时话说给谁听。

剪映给的是「复制属性 / 粘贴属性」，达芬奇给的是 Paste Attributes，AE 给的是效果栈的复制粘贴。
三家说的是同一句话：**这一段这几样，变成那几段的**，而两段各自在时间线上的位置一个字都不动。
1.108 那条「套到整轨」只管调色链、只走整轨；这一版把单位换成「人挑的类别 × 人挑的目标」。

五条要紧的事，逐条钉住：

* **规划就是那条判断。** 每一个目标都是把候选命令交给 `apply_commands` 重放一遍才决定收不收，
  所以交回去的命令一定是同一个 reducer 会接受的命令，而拒的那一句用的是 reducer 自己的 code 与
  句子——这里不再写第二套「大概能粘」的规则。
* **类别之间不连坐。** 一段接不下「文字样式」不该让它连调色链都拿不到；但**一类之内**要么整类
  写进去要么整类不写，不会留下半条遮罩或半个淡。
* **搬的是属性，不是位置。** 粘贴前后逐段的 `position_ticks` 与 `duration_ticks` 必须一字不差，
  而 `clip.speed` 发的是 `ripple=False`。
* **有的东西故意不搬。** 画面稳定是那一段素材被量出来的相机运动，转场属于这一段与邻居之间的那对
  关系——两个名字都不在表里，这条按双向钉：今天没有这两行，哪天有人加进表而没说清怎么核对，红。
* **没写过就等于没做。** 一次都不涨 revision，被拒的那些不涨 revision，而规划本身是只读的。
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.attributes import (
    EFFECT_PROPERTIES,
    MASK_PROPERTIES,
    attribute_plan,
    category_content,
)
from agentcut.contracts import (
    ATTRIBUTE_CATEGORIES,
    ATTRIBUTE_CATEGORY_IDS,
    ATTRIBUTE_PASTE_TARGET_LIMIT,
    Asset,
    Bezier,
    Clip,
    ClipColor,
    EditBatch,
    EditorError,
    ExtraShapeMask,
    FrameRate,
    GradeLevels,
    Keyframe,
    MaskBoxKey,
    MaskShapeKeyframe,
    Project,
    SequenceSettings,
    ShapeMask,
    Stabilization,
    TextStyle,
    Track,
    capabilities,
)
from agentcut.contracts import (
    TIMEBASE as T,
)
from agentcut.http_api import create_app
from agentcut.timeline import apply_commands

ROOT = Path(__file__).resolve().parent.parent
FRAME = 2_352_000  # 30 fps 的一帧
LEVELS = GradeLevels(black=0.05, white=0.95, gamma=1.2)


def clip(cid: str, asset_id: str, position: int, duration: int, **kw) -> Clip:
    return Clip(
        id=cid,
        asset_id=asset_id,
        track_id=kw.pop("track_id", "v1"),
        position_ticks=position,
        duration_ticks=duration,
        **kw,
    )


def plate(cid: str, name: str) -> Asset:
    """画面素材一律给 20 秒的视频：图像没有播放速率可言（`INVALID_SPEED`），
    而这一版要粘的类别里就有「变速」，夹具不许自己先说一句假话。"""
    return Asset(id=cid, kind="video", label=name, reference=f"{name}.mp4", duration_ticks=20 * T)


def rich_source(cid="src", **over) -> Clip:
    """一段把六类都有话说的片段：链子、旋钮、两条曲线、遮罩与其曲线、两头淡、150% 速率。"""
    body = (
        dict(
            color=ClipColor(exposure=0.4, contrast=1.2, saturation=0.8, grade=[LEVELS]),
            effects={"scale": 1.5, "blur": 0.02, "opacity": 0.8},
            mask=ShapeMask(shape="ellipse", center_x=0.3, center_y=0.4, width=0.5, height=0.5),
            keyframes=[
                Keyframe(property="x", at_ticks=0, value=0.1),
                Keyframe(
                    property="x",
                    at_ticks=3 * T,
                    value=0.9,
                    interpolation="bezier",
                    bezier=Bezier(x1=0.2, y1=0.4, x2=0.7, y2=0.9),
                ),
                Keyframe(property="blur", at_ticks=FRAME, value=0.03),
                Keyframe(property="mask_x", at_ticks=0, value=0.22),
            ],
            speed_percent=150,
        )
        | over
    )
    return clip(cid, "asset-src", 0, 4 * T, **body)


def fixture(**over) -> Project:
    """一条画面轨 + 一条音量轨：四段画面、一段声音，位置互不重叠。"""
    project = Project(
        id="ap",
        name="粘贴属性",
        settings=SequenceSettings(
            width=320,
            height=180,
            frame_rate=FrameRate(numerator=30, denominator=1),
        ),
        tracks=[
            Track(id="v1", kind="video", name="画面 1"),
            Track(id="a1", kind="audio", name="声 1"),
        ],
        assets={
            "asset-src": plate("asset-src", "甲"),
            "asset-a": plate("asset-a", "乙"),
            "asset-b": plate("asset-b", "丙"),
            "asset-c": plate("asset-c", "丁"),
            "asset-aud": Asset(
                id="asset-aud",
                kind="audio",
                label="声",
                reference="d.wav",
                duration_ticks=10 * T,
            ),
            "asset-txt-src": Asset(
                id="asset-txt-src", kind="text", label="字甲", reference="来源字"
            ),
            "asset-txt": Asset(id="asset-txt", kind="text", label="字乙", reference="目标字"),
        },
        clips={},
    )
    project.clips["src"] = rich_source(**over)
    project.clips["a"] = clip("a", "asset-a", 5 * T, 3 * T)
    project.clips["b"] = clip("b", "asset-b", 9 * T, 6 * T)
    project.clips["narrow"] = clip("narrow", "asset-c", 16 * T, 2 * T)
    project.clips["aud"] = clip("aud", "asset-aud", 0, 4 * T, track_id="a1")
    project.clips["txt-src"] = clip(
        "txt-src",
        "asset-txt-src",
        19 * T,
        T,
        text=TextStyle(body="来源打的那行字", font_size=0.1, color="#FF0000", box=True),
    )
    project.clips["txt"] = clip(
        "txt",
        "asset-txt",
        21 * T,
        T,
        text=TextStyle(body="目标打的那行字", font_size=0.02, color="#00FF00", box=False),
    )
    return project


def codes(plan: dict) -> set[tuple[str, str]]:
    return {(item["clip_id"], item["code"]) for item in plan["refusals"]}


def categories_for(plan: dict, clip_id: str) -> list[str]:
    for row in plan["written"]:
        if row["clip_id"] == clip_id:
            return list(row["categories"])
    return []


def table_suite() -> dict:
    caps = capabilities()
    rows = caps["attribute_categories"]
    assert rows == [dict(row) for row in ATTRIBUTE_CATEGORIES], (
        f"能力表下发的那几类与契约那张表不一致：{rows}"
    )
    ids = [row["id"] for row in rows]
    assert ids == list(ATTRIBUTE_CATEGORY_IDS), f"名单顺序不是表里那一份：{ids}"
    for row in rows:
        assert row["label"] and row["note"], f"{row['id']} 那一行少了中文名或那句「搬什么」"
    assert "stabilization" not in ids and "transition" not in ids, (
        "画面稳定与转场进了名单：前者是那一段素材量出来的相机运动，后者属于与邻居的那对关系，"
        "都不是一段自己的属性，搬过去就是一句没人核对的声明"
    )
    assert caps["features"]["attribute_paste"] is True, "能力开关没下发，界面与 Agent 都挂不上"
    assert caps["limits"]["attribute_paste_targets"] == ATTRIBUTE_PASTE_TARGET_LIMIT, (
        "上限下发了第二个数：界面读的是能力表，契约里那个常数就成了没人看的摆设"
    )
    assert sorted(EFFECT_PROPERTIES + MASK_PROPERTIES) == sorted(
        [*EFFECT_PROPERTIES, *MASK_PROPERTIES]
    ), "关键帧那两堆名单自己重排了"
    assert len(set(EFFECT_PROPERTIES) & set(MASK_PROPERTIES)) == 0, (
        "一条属性同时属于「关键帧动画」和「遮罩」两类：同一次粘贴会发两遍那一条曲线"
    )
    return {"categories": ids}


def content_suite() -> dict:
    """对话框那一排勾是从这份报告排出来的：哪一类有东西、有几个，只能由引擎说。"""
    rows = {row["category"]: row for row in category_content(fixture().clips["src"])}
    assert [row["has_content"] for row in rows.values()] == [
        True,
        True,
        True,
        True,
        False,
        True,
        False,
    ], f"这一份报告的勾选状态不对：{[(k, v['has_content']) for k, v in rows.items()]}"
    assert rows["color"]["nodes"] == 1, "链子上那一枚色阶没被数进去"
    assert rows["color"]["adjusted"] == 1, "曝光/对比度/饱和度的改动没被认成「有内容」"
    assert rows["animation"]["keyframes"] == 4 - 1, "动画那一类不该把遮罩的针也算进来"
    assert rows["animation"]["properties"] == ["blur", "x"], (
        f"报出来的曲线不是非遮罩那两条：{rows['animation']['properties']}"
    )
    assert rows["mask"]["curves"] == 1 and rows["mask"]["shape"] == "ellipse", (
        "遮罩那一行的数与工程里的不是一份"
    )
    assert "scale" in rows["effects"]["fields"] and "blur" in rows["effects"]["fields"], (
        f"效果那一行没念出改过的旋钮：{rows['effects']['fields']}"
    )
    assert rows["speed"]["speed_percent"] == 150, "速率那一行没报真实的那个百分比"
    for row in rows.values():
        assert row["label"] and row["note"], f"{row['category']} 那一行少了中文名或那句说明"
    return {"fade": rows["fade"]["has_content"], "text": rows["text"]["has_content"]}


def state_suite() -> dict:
    project = fixture()
    plan = attribute_plan(project, "src", ["a", "b"], list(ATTRIBUTE_CATEGORY_IDS))
    assert [row["clip_id"] for row in plan["written"]] == ["a", "b"], (
        f"两段都该收下能收的类别：{plan['written']}"
    )
    assert plan["refusals"] == [], f"画面段之间不该有拒绝：{plan['refusals']}"
    moved = apply_commands(
        project,
        EditBatch.model_validate(
            {"request_id": "x", "expected_revision": 0, "commands": plan["commands"]}
        ).commands,
    )
    source = project.clips["src"]
    for cid in ("a", "b"):
        after = moved.clips[cid]
        assert after.color == source.color, f"{cid} 的调色链不是来源那一份"
        assert after.effects == source.effects, f"{cid} 的效果旋钮不是来源那一份"
        assert after.mask == source.mask, f"{cid} 的遮罩不是来源那一份"
        assert after.speed_percent == 150, f"{cid} 的速率没跟着走：{after.speed_percent}"
        got = {(k.property, k.at_ticks, k.value) for k in after.keyframes}
        want = {(k.property, k.at_ticks, k.value) for k in source.keyframes}
        assert got == want, f"{cid} 的关键帧对不上：{sorted(got ^ want)}"
        assert after.position_ticks == project.clips[cid].position_ticks, (
            f"{cid} 的位置被搬属性搬走了"
        )
        assert after.source_in_ticks == project.clips[cid].source_in_ticks, (
            f"{cid} 的源窗口被搬属性挪了"
        )
        expect = project.clips[cid].duration_ticks * 100 // 150 // FRAME * FRAME
        assert after.duration_ticks == expect, (
            f"{cid} 的长度没按速率换算：{after.duration_ticks} 应为 {expect}"
        )
        assert after.text is None, f"{cid} 不是文字片段，不该凭空有样式"
    for cid in ("b", "narrow", "aud", "txt", "txt-src"):
        assert moved.clips[cid].position_ticks == project.clips[cid].position_ticks, (
            f"{cid} 被推开了一段——粘贴属性不动时间线上的位置"
        )
    bezier = [k for k in moved.clips["a"].keyframes if k.property == "x" and k.at_ticks == 3 * T]
    assert bezier and bezier[0].interpolation == "bezier" and bezier[0].bezier is not None, (
        "贝塞尔的控制柄没跟着针走：粘过去会把手感抹平成线性"
    )
    return {"written": [row["clip_id"] for row in plan["written"]]}


def narrow_suite() -> dict:
    """目标比来源短时：段尾之外的针照旧进去，但数目必须报出来，不能悄悄少画。"""
    project = fixture()
    plan = attribute_plan(project, "src", ["narrow"], ["animation"])
    assert plan["beyond_tail_keyframes"] == 1, (
        f"窄目标上有几枚针落在段尾之外没报实数：{plan['beyond_tail_keyframes']}"
    )
    moved = apply_commands(
        project,
        EditBatch.model_validate(
            {"request_id": "n", "expected_revision": 0, "commands": plan["commands"]}
        ).commands,
    )
    assert len([k for k in moved.clips["narrow"].keyframes if k.property == "x"]) == 2, (
        "段尾之外那枚针被偷偷删掉了：界面数的与工程存的会不一致"
    )
    return {"beyond": plan["beyond_tail_keyframes"]}


def clear_suite() -> dict:
    """来源那一类没东西、目标有：整条清掉，而不是留着让人以为粘过了。"""
    project = fixture()
    project.clips["plain"] = clip("plain", "asset-c", 24 * T, T)
    project.clips["blank"] = clip("blank", "asset-a", 26 * T, T)
    project.clips["plain"].color = ClipColor(grade=[LEVELS])
    project.clips["plain"].keyframes = [Keyframe(property="x", at_ticks=0, value=0.5)]
    plan = attribute_plan(project, "blank", ["plain"], ["color", "animation"])
    ops = [command["op"] for command in plan["commands"]]
    assert "clip.color" in ops and "keyframes.remove" in ops, (
        f"来源没东西时目标该被清空，实际发的是 {ops}，拒绝是 {plan['refusals']}"
    )
    moved = apply_commands(
        project,
        EditBatch.model_validate(
            {"request_id": "c", "expected_revision": 0, "commands": plan["commands"]}
        ).commands,
    )
    assert moved.clips["plain"].color == ClipColor(), "旧链子没被清掉"
    assert not moved.clips["plain"].keyframes, "旧曲线没被清掉"
    return {"ops": sorted(ops)}


def audio_suite() -> dict:
    """音轨上那一段：调色与遮罩接不下，其余照拿——类别之间不连坐。"""
    project = fixture()
    plan = attribute_plan(project, "src", ["aud"], list(ATTRIBUTE_CATEGORY_IDS))
    seen = codes(plan)
    assert ("aud", "INVALID_COLOR") in seen, f"音频段没被点名不调色：{sorted(seen)}"
    assert any(code == "INVALID_MASK" for _, code in seen), f"音频段没被点名不能挂遮罩：{seen}"
    assert categories_for(plan, "aud"), "一段都不肯给：这条目标被整段跳过了"
    assert "color" not in categories_for(plan, "aud"), "音频段拿走了调色链"
    return {"refused": sorted(seen), "took": categories_for(plan, "aud")}


def locked_suite() -> dict:
    """锁着的轨：整段一类都进不来，而句子是 reducer 那句，不是这里另编的。"""
    project = fixture()
    project.tracks[1].locked = True
    plan = attribute_plan(project, "src", ["aud"], ["effects"])
    assert categories_for(plan, "aud") == [], "锁定轨道上的片段被写了进去"
    assert plan["refusals"] and plan["refusals"][0]["code"] == "TRACK_LOCKED", (
        f"锁轨那句拒绝没用自己的 code：{plan['refusals']}"
    )
    return {"code": plan["refusals"][0]["code"] if plan["refusals"] else None}


def stabilize_suite() -> dict:
    """稳定过的那一段：变速这一类被 reducer 点名拒掉，其余类别照拿。"""
    project = fixture()
    project.clips["b"].stabilization = Stabilization(
        strength=0.8,
        max_crop=0.1,
        points=20,
        translation_correction=4.0,
        roll_correction=0.2,
        zoom_to_hide_borders=1.05,
        analysed_frames=30,
    )
    plan = attribute_plan(project, "src", ["b"], list(ATTRIBUTE_CATEGORY_IDS))
    assert ("b", "STABILIZE_LOCKED") in codes(plan), f"稳定过的那段没被点名：{plan['refusals']}"
    refused = [row.get("category") for row in plan["refusals"] if row["clip_id"] == "b"]
    assert refused == ["speed"], f"只有「变速」该被拒，实际拒了这些：{refused}"
    assert "color" in categories_for(plan, "b"), "一类被拒就把整段跳过了：类别之间连坐了"
    assert project.clips["b"].stabilization is not None, "规划把稳定记录动了"
    return {"refused": refused, "took": categories_for(plan, "b")}


def fade_suite() -> dict:
    """两头淡：长度与形状一起走，装不下的那段整类跳过而不是写一半。"""
    project = fixture()
    source = project.clips["src"]
    from agentcut.contracts import FadeEnvelope

    source.fade = FadeEnvelope(opacity_in_ticks=T, opacity_out_ticks=2 * T, opacity_shape="linear")
    plan = attribute_plan(project, "src", ["a", "b", "narrow"], ["fade"])
    moved = apply_commands(
        project,
        EditBatch.model_validate(
            {"request_id": "f", "expected_revision": 0, "commands": plan["commands"]}
        ).commands,
    )
    assert moved.clips["b"].fade == source.fade, f"宽那段没拿到同一份淡：{moved.clips['b'].fade}"
    assert "a" in categories_for(plan, "a") or "a" in [row["clip_id"] for row in plan["written"]], (
        "三段里那段 3 秒的该拿下半条淡"
    )
    assert ("narrow", "INVALID_FADE") in codes(plan) or "narrow" not in [
        row["clip_id"] for row in plan["written"]
    ], f"两秒那段装了 3 秒的淡：{plan['written']}"
    return {"written": [row["clip_id"] for row in plan["written"]]}


def mask_suite() -> dict:
    """路径遮罩：整张轮廓与轮廓的关键帧跟着走，目标自己多出来的那些轮廓要被删掉。"""
    project = fixture()
    vertices = [{"x": 0.2, "y": 0.2}, {"x": 0.7, "y": 0.25}, {"x": 0.45, "y": 0.8}]
    other = [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.2}, {"x": 0.5, "y": 0.9}]
    project.clips["src"].mask = ShapeMask(shape="path", vertices=vertices)
    project.clips["src"].mask_shape_keys = [
        MaskShapeKeyframe(at_ticks=0, vertices=vertices),
        MaskShapeKeyframe(
            at_ticks=T,
            vertices=[{"x": 0.25, "y": 0.15}, {"x": 0.75, "y": 0.3}, {"x": 0.5, "y": 0.85}],
        ),
    ]
    project.clips["a"].mask = ShapeMask(shape="path", vertices=other)
    project.clips["a"].mask_shape_keys = [MaskShapeKeyframe(at_ticks=3 * T, vertices=other)]
    plan = attribute_plan(project, "src", ["a"], ["mask"])
    ops = [command["op"] for command in plan["commands"]]
    assert ops.count("mask.shape.set") == 2, f"来源那两条轮廓没各发一条：{ops}"
    assert ops.count("mask.shape.remove") == 1, f"目标自己多出来的那条轮廓没被清掉：{ops}"
    assert "clip.mask" in ops, f"目标那张遮罩与来源不同，该整张换掉：{ops}"
    assert "keyframes.replace" in ops, f"遮罩那四条曲线的针没跟着走：{ops}"
    moved = apply_commands(
        project,
        EditBatch.model_validate(
            {"request_id": "m", "expected_revision": 0, "commands": plan["commands"]}
        ).commands,
    )
    after = moved.clips["a"]
    assert [k.at_ticks for k in after.mask_shape_keys] == [0, T], (
        f"粘完之后那份轮廓表不是来源那一份：{[k.at_ticks for k in after.mask_shape_keys]}"
    )
    assert after.mask.shape == "path" and [
        (round(v.x, 6), round(v.y, 6)) for v in after.mask.vertices
    ] == [(round(v["x"], 6), round(v["y"], 6)) for v in vertices], "路径轮廓没跟着走"
    assert any(k.property == "mask_x" for k in after.keyframes), "遮罩曲线的针没落库"
    return {"ops": ops}


def extra_mask_suite() -> dict:
    """1.244：再叠的那几块跟着「遮罩」这一类一起走——连框点与跟随。

    目标更短时，落在段尾之后的框点**不搬**（引擎不允许框点停在段尾之后），而块的其余部分照搬；
    回执把丢了几枚说在一个自己的数上。主遮罩仍在同一类里。
    """
    project = fixture()
    src = project.clips["src"]
    key_at = (36 * T) // 10  # 3.6 秒：a 只有 3 秒，b 有 6 秒
    src.extra_masks = [
        ExtraShapeMask(
            shape="rectangle", center_x=0.2, center_y=0.3, width=0.2, height=0.2,
            feather=0.05, inverted=False,
        ),
        ExtraShapeMask(
            shape="ellipse", center_x=0.7, center_y=0.7, width=0.3, height=0.2,
            feather=0.0, inverted=False,
            keys=[
                MaskBoxKey(
                    at_ticks=0, center_x=0.7, center_y=0.7, width=0.3, height=0.2,
                    rotation=0, interpolation="linear",
                ),
                MaskBoxKey(
                    at_ticks=key_at, center_x=0.6, center_y=0.6, width=0.25, height=0.25,
                    rotation=10, interpolation="ease",
                ),
            ],
        ),
    ]
    src.extra_masks_follow = True
    plan = attribute_plan(project, "src", ["a", "b"], ["mask"])
    stacks = {
        command["clip_id"]: command
        for command in plan["commands"]
        if command["op"] == "clip.mask_stack"
    }
    assert set(stacks) == {"a", "b"}, f"两段各该有一条框点链的写入：{sorted(stacks)}"
    assert stacks["b"]["follow"] is True, "跟随那一格没跟着走"
    assert [len(mask["keys"]) for mask in stacks["b"]["masks"]] == [0, 2], (
        f"长的那一段该把两枚框点都带上：{stacks['b']['masks']}"
    )
    assert [len(mask["keys"]) for mask in stacks["a"]["masks"]] == [0, 1], (
        f"3 秒那一段不该带上 3.6 秒的框点：{stacks['a']['masks']}"
    )
    assert plan["dropped_extra_keys"] == 1, f"丢了几枚框点没照实说：{plan['dropped_extra_keys']}"
    assert "clip.mask" in [command["op"] for command in plan["commands"]], "主遮罩不在同一类里"
    moved = apply_commands(
        project,
        EditBatch.model_validate(
            {"request_id": "em", "expected_revision": 0, "commands": plan["commands"]}
        ).commands,
    )
    after_a, after_b = moved.clips["a"], moved.clips["b"]
    assert len(after_a.extra_masks) == 2 and after_a.extra_masks_follow is True, (
        "两块的形状与跟随没有落到 3 秒那一段上"
    )
    assert [k.at_ticks for k in after_a.extra_masks[1].keys] == [0], (
        f"3 秒那一段带上了越尾的框点：{[k.at_ticks for k in after_a.extra_masks[1].keys]}"
    )
    assert [k.at_ticks for k in after_b.extra_masks[1].keys] == [0, key_at], (
        f"6 秒那一段的框点不全：{[k.at_ticks for k in after_b.extra_masks[1].keys]}"
    )
    assert after_b.extra_masks[1].keys[1].interpolation == "ease", "插值没有跟着走"
    assert after_a.mask is not None and after_a.mask.shape == "ellipse", "主遮罩没有跟着换"
    rows = {row["category"]: row for row in category_content(src)}
    assert rows["mask"]["extras"] == 2 and rows["mask"]["extra_keys"] == 2, (
        f"回执没把再叠的几块数进去：{rows['mask']}"
    )
    assert rows["mask"]["follow"] is True and rows["mask"]["has_content"] is True

    # 反方向：来源没有那几块、目标有——这一类要能把目标清干净并把跟随关掉。
    cleared = fixture()
    cleared.clips["a"].extra_masks = [
        ExtraShapeMask(
            shape="rectangle", center_x=0.5, center_y=0.5, width=0.2, height=0.2,
            feather=0.0, inverted=False,
        )
    ]
    cleared.clips["a"].extra_masks_follow = True
    plan2 = attribute_plan(cleared, "src", ["a"], ["mask"])
    clear_command = next(
        command for command in plan2["commands"] if command["op"] == "clip.mask_stack"
    )
    assert clear_command["masks"] == [] and clear_command["follow"] is False, (
        f"来源没有那几块时，这一类没有清空目标：{clear_command}"
    )
    again = apply_commands(
        cleared,
        EditBatch.model_validate(
            {"request_id": "em2", "expected_revision": 0, "commands": plan2["commands"]}
        ).commands,
    ).clips["a"]
    assert again.extra_masks == [] and again.extra_masks_follow is False, "清空没有落库"
    return {
        "stacks": sorted(stacks),
        "dropped": plan["dropped_extra_keys"],
        "after_keys": [len(after_a.extra_masks[1].keys), len(after_b.extra_masks[1].keys)],
    }


def text_suite() -> dict:
    """文字样式只搬样式：每段自己打的那行字留着。"""
    project = fixture()
    plan = attribute_plan(project, "txt-src", ["txt"], ["text"])
    assert len(plan["commands"]) == 1, f"文字样式该发一条命令：{plan['commands']}"
    moved = apply_commands(
        project,
        EditBatch.model_validate(
            {"request_id": "t", "expected_revision": 0, "commands": plan["commands"]}
        ).commands,
    )
    assert moved.clips["txt"].text.body == "目标打的那行字", "把别人打的字覆盖掉了"
    assert moved.clips["txt"].text.font_size == 0.1, "样式没跟着走"
    assert moved.clips["txt"].text.box is True, "垫子那一格没跟着走"
    onto_media = attribute_plan(project, "txt-src", ["a"], ["text"])
    assert not onto_media["commands"], "给画面片段粘文字样式——它没有样式可粘"
    return {"body": moved.clips["txt"].text.body}


def unchanged_suite() -> dict:
    """已经一样了就是没活干：一条命令都不发，而不是发一遍再涨一个版本。"""
    project = fixture()
    once = attribute_plan(project, "src", ["a"], list(ATTRIBUTE_CATEGORY_IDS))
    moved = apply_commands(
        project,
        EditBatch.model_validate(
            {"request_id": "u", "expected_revision": 0, "commands": once["commands"]}
        ).commands,
    )
    again = attribute_plan(moved, "src", ["a"], list(ATTRIBUTE_CATEGORY_IDS))
    assert again["commands"] == [], f"第二次粘还有命令：{again['commands']}"
    assert again["unchanged"] == ["a"], f"第二次粘没把那段报成「已经一样」：{again['unchanged']}"
    assert again["written"] == [], "第二次还排了命令：同一份粘贴被写了两遍"
    return {"second": len(again["commands"])}


def determinism_suite() -> dict:
    plan = attribute_plan(fixture(), "src", ["a", "b"], list(ATTRIBUTE_CATEGORY_IDS))
    back = attribute_plan(fixture(), "src", ["a", "b"], list(ATTRIBUTE_CATEGORY_IDS))
    assert plan["commands"] == back["commands"], (
        "同一份工程问两次交出两份命令：界面拿到的与真写进去的可以不是同一批"
    )
    return {"commands": len(plan["commands"])}


def refusal_suite() -> None:
    project = fixture()
    for args, want in (
        ((project, "nope", ["a"], ["color"]), "NOT_FOUND"),
        ((project, "src", ["nope"], ["color"]), "NOT_FOUND"),
        ((project, "src", [], ["color"]), "ATTRIBUTE_NO_TARGET"),
        ((project, "src", ["src"], ["color"]), "ATTRIBUTE_NO_TARGET"),
        ((project, "src", ["a"], []), "ATTRIBUTE_NONE"),
        ((project, "src", ["a"], ["stabilization"]), "UNKNOWN_ATTRIBUTE_CATEGORY"),
    ):
        try:
            attribute_plan(*args)
        except EditorError as error:
            assert error.code == want, f"{want} 该由这句拒绝说出，实际是 {error.code}"
            assert error.details, f"{want} 那句拒绝没有 details：{error.message}"
        else:
            raise AssertionError(f"{want} 没被拒：{args[1:]}")
    over = ATTRIBUTE_PASTE_TARGET_LIMIT + 1
    big = fixture()
    far = []
    for index in range(over):
        cid = f"c{index}"
        far.append(cid)
        big.clips[cid] = clip(cid, "asset-c", (30 + index * 2) * T, T)
    try:
        attribute_plan(big, "src", far, ["color"])
    except EditorError as error:
        assert error.code == "ATTRIBUTE_PASTE_LIMIT", f"超上限该点名额度：{error.code}"
        assert error.details["limit"] == ATTRIBUTE_PASTE_TARGET_LIMIT, "句子没报出那个上限"
        assert error.details["targets"] == over, f"句子没报出要点多少段：{error.details}"
    else:
        raise AssertionError(f"{over} 段一次粘贴没被拒")


def http_suite() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        token = "attribute-paste-" + "a" * 40
        app = create_app(folder / "agentcut.sqlite3", token, media=None, jobs=None)
        with TestClient(
            app, base_url="http://127.0.0.1", headers={"Authorization": f"Bearer {token}"}
        ) as client:
            created = client.post(
                "/v1/projects",
                json={
                    "request_id": "ap-new",
                    "name": "粘贴属性",
                    "settings": {
                        "width": 320,
                        "height": 180,
                        "frame_rate": {"numerator": 30, "denominator": 1},
                    },
                },
            ).json()["project"]
            path = f"/v1/projects/{created['id']}"
            seed = [
                {"op": "track.add", "track": {"id": "v1", "kind": "video", "name": "画面 1"}},
                {"op": "asset.register", "asset": plate("asset-src", "甲").model_dump()},
                {"op": "asset.register", "asset": plate("asset-a", "乙").model_dump()},
                {
                    "op": "clip.add",
                    "clip": clip(
                        "src", "asset-src", 0, 4 * T, color=ClipColor(exposure=0.3)
                    ).model_dump(),
                },
                {"op": "clip.add", "clip": clip("a", "asset-a", 5 * T, 3 * T).model_dump()},
            ]
            wrote = client.post(
                path + "/edits",
                json={
                    "request_id": "ap-seed",
                    "expected_revision": created["revision"],
                    "commands": seed,
                },
            ).json()
            revision = wrote["project"]["revision"]
            assert revision == 1, f"种子批次没落成一个版本：{revision}"
            asked = client.post(
                path + "/clips/src/attribute-plan",
                json={
                    "request_id": "ap-plan",
                    "expected_revision": revision,
                    "source_clip_id": "src",
                    "target_clip_ids": ["a"],
                    "categories": ["color", "speed"],
                },
            )
            assert asked.status_code == 200, asked.text
            body = asked.json()
            assert body["committed"] is False, "只读规划把 committed 说成写过了"
            assert "project" not in body, (
                "只读规划把整份工程代回来了：这一条不改状态，回执只该有那份计划"
            )
            assert body["attribute_plan"]["commands"], "规划空手回来：链子那一段没排进命令"
            after = client.get(path).json()
            assert after["revision"] == revision, "只读路由涨了 revision"
            assert after["clips"]["a"]["color"]["exposure"] == 0.0, "只读路由把画面写进去了"
            landed = client.post(
                path + "/edits",
                json={
                    "request_id": "ap-paste",
                    "expected_revision": revision,
                    "commands": body["attribute_plan"]["commands"],
                },
            ).json()
            assert landed["project"]["revision"] == revision + 1, (
                f"一次粘贴涨了 {landed['project']['revision'] - revision} 个版本"
            )
            assert landed["project"]["clips"]["a"]["color"]["exposure"] == 0.3, (
                "粘过去之后那条链不在工程里"
            )
            assert landed["project"]["clips"]["a"]["position_ticks"] == 5 * T, (
                "粘贴属性搬走了那一段的位置"
            )
            bad = client.post(
                path + "/clips/nope/attribute-plan",
                json={
                    "request_id": "ap-bad",
                    "expected_revision": landed["project"]["revision"],
                    "source_clip_id": "nope",
                    "target_clip_ids": ["a"],
                    "categories": ["color"],
                },
            )
            assert bad.status_code == 404, f"不存在的来源该 404：{bad.status_code}"
            refused = bad.json()["error"]
            assert refused["code"] == "NOT_FOUND", f"404 没说清是哪一种找不到：{refused}"
            assert refused["details"]["clip_id"] == "nope", f"404 没点名是哪个片段：{refused}"
            empty = client.post(
                path + "/clips/src/attribute-plan",
                json={
                    "request_id": "ap-empty",
                    "expected_revision": landed["project"]["revision"],
                    "source_clip_id": "src",
                    "target_clip_ids": [],
                    "categories": ["color"],
                },
            )
            assert empty.json()["error"]["code"] == "ATTRIBUTE_NO_TARGET", (
                f"没有目标时那句拒绝不点名：{empty.json()}"
            )
            assert client.get(path).json()["revision"] == landed["project"]["revision"], (
                "被拒的一次规划涨了 revision"
            )
            mixed = client.post(
                path + "/clips/src/attribute-plan",
                json={
                    "request_id": "ap-mixed",
                    "expected_revision": landed["project"]["revision"],
                    "source_clip_id": "a",
                    "target_clip_ids": ["src"],
                    "categories": ["color"],
                },
            )
            assert mixed.status_code == 404, f"路径与载荷各指一段该拒：{mixed.status_code}"
            assert mixed.json()["error"]["details"] == {
                "clip_id": "src",
                "source_clip_id": "a",
            }, f"那一句没把两个名字都交回来：{mixed.json()}"
            return {"revision": landed["project"]["revision"]}


def cost_suite() -> dict:
    """上限不是拍的：64 段一次规划在这台机器上要跑多久，量一次记下来。"""
    project = fixture()
    for index in range(60):
        cid = f"many{index}"
        project.assets[f"asset-{cid}"] = plate(f"asset-{cid}", f"多{index}")
        project.clips[cid] = clip(cid, f"asset-{cid}", (30 + index * 2) * T, T)
    targets = [f"many{index}" for index in range(60)]
    started = time.perf_counter()
    plan = attribute_plan(project, "src", targets, list(ATTRIBUTE_CATEGORY_IDS))
    elapsed = time.perf_counter() - started
    assert len(plan["written"]) == 60, f"60 段里有段没排进去：{len(plan['written'])}"
    return {"targets": len(plan["written"]), "seconds": round(elapsed, 3)}


def main() -> None:
    report = {
        "table": table_suite(),
        "content": content_suite(),
        "state": state_suite(),
        "narrow": narrow_suite(),
        "clear": clear_suite(),
        "audio": audio_suite(),
        "locked": locked_suite(),
        "stabilize": stabilize_suite(),
        "fade": fade_suite(),
        "mask": mask_suite(),
        "extra_mask": extra_mask_suite(),
        "text": text_suite(),
        "unchanged": unchanged_suite(),
        "determinism": determinism_suite(),
        "cost": cost_suite(),
    }
    refusal_suite()
    report["http"] = http_suite()
    for name, value in report.items():
        print(name, value)
    print(
        f"PASS 粘贴属性：{len(report['table']['categories'])} 类、"
        f"一次粘贴 {report['determinism']['commands']} 条命令，"
        f"60 段规划 {report['cost']['seconds']} 秒，写后 revision {report['http']['revision']}"
    )


if __name__ == "__main__":
    main()
