"""Copy one clip's chosen aspects onto other clips as ordinary commands the reducer itself accepts.

剪映 gives 「复制属性 / 粘贴属性」, 达芬奇 gives Paste Attributes, AE gives copy/paste of an effect
stack; all three make the same promise — these aspects of that clip become this clip's, while where
each one sits on the timeline does not move.

This module keeps no second copy of the rules. It builds the same ordinary commands a human click or
an Agent batch would write, then replays them through `apply_commands` target by target, so a target
the reducer would refuse is reported with the reducer's own code and sentence rather than a guess
made here. The list that survives is the list the write submits — which is why plan and commit
cannot disagree.

Two aspects are deliberately absent. `Clip.stabilization` is the record of one camera move measured
in *this* footage, and `Clip.transition_in` belongs to the pair a clip forms with its neighbour;
copying either would write a claim no number in the project could check.
"""

import json
from typing import Any, get_args

from pydantic import TypeAdapter

from .contracts import (
    ATTRIBUTE_CATEGORIES,
    ATTRIBUTE_CATEGORY_IDS,
    ATTRIBUTE_PASTE_TARGET_LIMIT,
    MAX_COMMANDS_PER_BATCH,
    ClipEffects,
    Command,
    EditorError,
    EffectProperty,
    MaskProperty,
    SpatialProperty,
    TextStyle,
)
from .timeline import FADE_PROPERTIES, apply_commands, sequence_view

# 关键帧分两堆：遮罩那四条跟着「遮罩」这一类走，其余跟着「关键帧动画」这一类走。名单不写第二份，
# 从契约那三条 Literal 现算，引擎多一条属性这里就自动认得它。
EFFECT_PROPERTIES = [*get_args(EffectProperty), *get_args(SpatialProperty)]
MASK_PROPERTIES = list(get_args(MaskProperty))
MASK_PROPERTY_SET = set(MASK_PROPERTIES)
ATTRIBUTE_IDS = ATTRIBUTE_CATEGORY_IDS
ATTRIBUTE_LABELS = {row["id"]: row["label"] for row in ATTRIBUTE_CATEGORIES}

_COMMANDS = TypeAdapter(list[Command])
_EFFECT_DEFAULTS = ClipEffects()


def _dump(model: Any) -> Any:
    """The same JSON the reducer would read, so a command never carries a Python-only value.

    `None` and lists pass through: a clip may carry no mask at all, and a speed curve is a list of
    points, and both are values a command legitimately holds.
    """
    if model is None:
        return None
    if isinstance(model, list):
        return [_dump(item) for item in model]
    return json.loads(model.model_dump_json())


def _curve(clip: Any, prop: str) -> list[Any]:
    return [item for item in clip.keyframes if item.property == prop]


def _fade_window(clip: Any, prop: str) -> tuple[int, int, str | None]:
    """This clip's `(in, out, shape)` for one fade property, with no window read as zero.

    The shape is `None` when the clip carries no fade at all: a cleared window has no shape to
    claim, and inventing one here would write a number the source never had.
    """
    if clip.fade is None:
        return (0, 0, None)
    window = clip.fade.window(prop)
    return (window[0], window[1], clip.fade.shape(prop))


def _keyframe_commands(source: Any, target: Any, props: list[str]) -> tuple[list[dict], int]:
    """One command per curve the source has, one bulk clear per curve only the target has.

    `keyframes.replace` is the whole curve for one property, so pasting cannot leave a stray point
    behind — which is the difference between 「替换这一条曲线」 and a pile of `keyframe.set`.
    """
    commands: list[dict] = []
    beyond = 0
    for prop in props:
        mine = _curve(source, prop)
        theirs = _curve(target, prop)
        if mine:
            # 已经是同一份曲线就不再发第二遍：粘两次与粘一次必须落进同一个状态，
            # 而「已经一样」那一段报告靠的就是这条判断。
            if [_dump(item) for item in mine] == [_dump(item) for item in theirs]:
                continue
            commands.append(
                {
                    "op": "keyframes.replace",
                    "clip_id": target.id,
                    "property": prop,
                    "keyframes": [_dump(item) for item in mine],
                }
            )
            beyond += sum(1 for item in mine if item.at_ticks > target.duration_ticks)
        elif theirs:
            commands.append(
                {
                    "op": "keyframes.remove",
                    "clip_id": target.id,
                    "keyframes": [{"property": prop, "at_ticks": item.at_ticks} for item in theirs],
                }
            )
    return commands, beyond


def _category_commands(category: str, source: Any, target: Any) -> tuple[list[dict], int]:
    """What this category writes into one target, and how many pasted points sit past its tail."""
    if category == "color":
        if _dump(source.color) == _dump(target.color):
            return [], 0
        return [{"op": "clip.color", "clip_id": target.id, "color": _dump(source.color)}], 0
    if category == "effects":
        if _dump(source.effects) == _dump(target.effects):
            return [], 0
        return [{"op": "clip.effects", "clip_id": target.id, "effects": _dump(source.effects)}], 0
    if category == "animation":
        return _keyframe_commands(source, target, EFFECT_PROPERTIES)
    if category == "mask":
        commands: list[dict] = []
        if _dump(source.mask) != _dump(target.mask):
            commands.append(
                {
                    "op": "clip.mask",
                    "clip_id": target.id,
                    "mask": _dump(source.mask) if source.mask else None,
                }
            )
        curves, beyond = _keyframe_commands(source, target, MASK_PROPERTIES)
        commands += curves
        mine = {item.at_ticks: item for item in source.mask_shape_keys}
        for key in source.mask_shape_keys:
            commands.append({"op": "mask.shape.set", "clip_id": target.id, "keyframe": _dump(key)})
        for key in target.mask_shape_keys:
            if key.at_ticks not in mine:
                commands.append(
                    {"op": "mask.shape.remove", "clip_id": target.id, "at_ticks": key.at_ticks}
                )
        return commands, beyond
    if category == "fade":
        commands = []
        for prop in FADE_PROPERTIES:
            in_ticks, out_ticks, shape = _fade_window(source, prop)
            for mode, value in (("in", in_ticks), ("out", out_ticks)):
                their_window = _fade_window(target, prop)
                theirs = their_window[0] if mode == "in" else their_window[1]
                if value == theirs and (shape is None or their_window[2] == shape):
                    continue
                command: dict = {
                    "op": "clip.fade",
                    "clip_id": target.id,
                    "property": prop,
                    "mode": mode,
                    "duration_ticks": value,
                }
                if shape is not None:
                    command["shape"] = shape
                commands.append(command)
        return commands, 0
    if category == "speed":
        commands = []
        if source.speed_percent != target.speed_percent:
            # `ripple=False`：粘贴属性改的是这一段怎么播，不是时间线上谁在什么时候出现。
            # 让它顶开后面的片段就不是「属性」了，那是「移动」，而移动有自己的命令。
            commands.append(
                {
                    "op": "clip.speed",
                    "clip_id": target.id,
                    "speed_percent": source.speed_percent,
                    "ripple": False,
                }
            )
        if source.speed_curve is not None:
            commands.append(
                {
                    "op": "clip.speed_curve",
                    "clip_id": target.id,
                    "points": _dump(source.speed_curve),
                }
            )
        elif target.speed_curve is not None:
            commands.append({"op": "clip.speed_curve", "clip_id": target.id, "points": None})
        return commands, 0
    if category == "text":
        if source.text is None or target.text is None:
            return [], 0
        # 「文字样式」搬的是这一行长什么样，不搬它写了什么字：覆盖别人打的字不是样式，那是内容，
        # 而内容有自己的命令（`clip.text` 的 `body`）。所以来源的 body 在这里被目标自己的顶回去。
        style = {**_dump(source.text), "body": target.text.body}
        if style == _dump(target.text):
            return [], 0
        return [{"op": "clip.text", "clip_id": target.id, "text": style}], 0
    raise EditorError(
        "UNKNOWN_ATTRIBUTE_CATEGORY",
        f"这一类属性不在这张表里；可选的是 {'、'.join(ATTRIBUTE_IDS)}"
        "（名单在 contracts 的 ATTRIBUTE_CATEGORIES，别处不另写一份）",
        422,
        category=category,
        known=list(ATTRIBUTE_IDS),
    )


def category_content(clip: Any) -> list[dict]:
    """What this clip actually holds in each category — the dialog ticks from these numbers.

    `has_content` is the honest gate: a category with nothing in the source would *clear* the
    target rather than copy anything, and the report says which of the two is happening.
    """
    animated = {item.property for item in clip.keyframes}
    rows: list[dict] = []
    for row in ATTRIBUTE_CATEGORIES:
        category = row["id"]
        counts: dict[str, Any] = {
            "category": category,
            "label": row["label"],
            "note": row["note"],
        }
        if category == "color":
            counts["nodes"] = len(clip.color.grade)
            counts["adjusted"] = int(
                clip.color.exposure != 0 or clip.color.contrast != 1 or clip.color.saturation != 1
            )
            counts["has_content"] = bool(counts["nodes"] or counts["adjusted"])
        elif category == "effects":
            counts["fields"] = [
                name
                for name in ClipEffects.model_fields
                if getattr(clip.effects, name) != getattr(_EFFECT_DEFAULTS, name)
            ]
            counts["has_content"] = bool(counts["fields"])
        elif category == "animation":
            props = sorted(name for name in animated if name not in MASK_PROPERTY_SET)
            counts["curves"] = len(props)
            counts["keyframes"] = sum(len(_curve(clip, name)) for name in props)
            counts["properties"] = props
            counts["has_content"] = bool(props)
        elif category == "mask":
            props = sorted(name for name in animated if name in MASK_PROPERTY_SET)
            counts["shape"] = clip.mask.shape if clip.mask else None
            counts["curves"] = len(props)
            counts["outlines"] = len(clip.mask_shape_keys)
            counts["has_content"] = bool(clip.mask or props or clip.mask_shape_keys)
        elif category == "fade":
            windows = {prop: _fade_window(clip, prop)[:2] for prop in FADE_PROPERTIES}
            counts["windows"] = [list(pair) for pair in windows.values()]
            counts["has_content"] = any(any(pair) for pair in windows.values())
        elif category == "speed":
            counts["speed_percent"] = clip.speed_percent
            counts["curve_points"] = len(clip.speed_curve or [])
            counts["has_content"] = bool(
                clip.speed_percent != 100 or clip.speed_curve or clip.animation_offset_ticks
            )
        else:
            counts["has_text"] = clip.text is not None
            counts["adjusted"] = (
                0
                if clip.text is None
                else sum(
                    1
                    for name in TextStyle.model_fields
                    if name != "body"
                    and getattr(clip.text, name) != TextStyle.model_fields[name].default
                )
            )
            counts["has_content"] = clip.text is not None
        rows.append(counts)
    return rows


def attribute_plan(
    project: Any,
    source_id: str,
    target_ids: list[str],
    categories: list[str],
    sequence_id: str | None = None,
) -> dict:
    """One clip's chosen aspects, written onto these clips, as one ordinary batch.

    The per-target decision is `apply_commands` itself: a target is kept only when the reducer
    accepts the whole accumulated list with its commands appended, so what comes back here is a
    command list that commits at one revision and a refusal that names the clip, the engine's own
    code and the numbers behind it.
    """
    source = project.clips.get(source_id)
    if source is None:
        raise EditorError(
            "NOT_FOUND",
            "source clip is not in this project",
            404,
            clip_id=source_id,
        )
    wanted = [name for name in categories if name in ATTRIBUTE_IDS]
    unknown = [name for name in categories if name not in ATTRIBUTE_IDS]
    if unknown:
        raise EditorError(
            "UNKNOWN_ATTRIBUTE_CATEGORY",
            f"这些类别不在这张表里：{'、'.join(unknown)}；可选的是 {'、'.join(ATTRIBUTE_IDS)}",
            422,
            unknown=unknown,
            known=list(ATTRIBUTE_IDS),
        )
    if not wanted:
        raise EditorError(
            "ATTRIBUTE_NONE",
            "一个类别都没选：粘贴属性至少要挑一样要搬过去的东西",
            422,
            known=list(ATTRIBUTE_IDS),
        )
    if not target_ids:
        raise EditorError(
            "ATTRIBUTE_NO_TARGET",
            "没有要粘的目标片段：先在时间线上选中一段或多段，再来问这一份计划",
            422,
            source_clip_id=source_id,
        )
    requested = list(dict.fromkeys(target_ids))
    missing = [clip_id for clip_id in requested if clip_id not in project.clips]
    if missing:
        raise EditorError(
            "NOT_FOUND",
            f"这一版工程里没有这些片段：{'、'.join(missing)}",
            422,
            clip_ids=missing,
        )
    targets = [clip_id for clip_id in requested if clip_id != source_id]
    if not targets:
        raise EditorError(
            "ATTRIBUTE_NO_TARGET",
            "来源自己不算目标：粘贴属性要把这一类搬到别的片段上去",
            422,
            source_clip_id=source_id,
        )
    if len(targets) > ATTRIBUTE_PASTE_TARGET_LIMIT:
        raise EditorError(
            "ATTRIBUTE_PASTE_LIMIT",
            f"一次最多粘 {ATTRIBUTE_PASTE_TARGET_LIMIT} 段（现在要点 {len(targets)} 段）："
            "把选择缩到这么多以内，或分两批粘",
            422,
            targets=len(targets),
            limit=ATTRIBUTE_PASTE_TARGET_LIMIT,
        )
    if sequence_id is not None:
        sequence_view(project, sequence_id)
    root = project
    accepted: list[dict] = []
    written: list[dict] = []
    unchanged: list[str] = []
    refusals: list[dict] = []
    beyond_tail = 0

    def commit(commands: list[dict]) -> dict | None:
        """None when the reducer accepts everything chosen so far, with these commands appended.

        A rejection comes back as the engine's own `code` / `message` / `details`, which is what
        makes this plan a report instead of a second opinion.
        """
        nonlocal accepted
        try:
            apply_commands(root, _COMMANDS.validate_python(accepted + commands), sequence_id)
        except EditorError as error:
            return {"code": error.code, "message": error.message, "details": error.details}
        accepted += commands
        return None

    for clip_id in sorted(targets, key=lambda item: root.clips[item].position_ticks):
        groups: list[tuple[str, list[dict], int]] = []
        for category in wanted:
            commands, beyond = _category_commands(category, source, root.clips[clip_id])
            if commands:
                groups.append((category, commands, beyond))
        if not groups:
            unchanged.append(clip_id)
            continue
        whole = [command for _, commands, _ in groups for command in commands]
        if len(accepted) + len(whole) > MAX_COMMANDS_PER_BATCH:
            refusals.append(
                {
                    "clip_id": clip_id,
                    "category": None,
                    "code": "ATTRIBUTE_PASTE_LIMIT",
                    "message": f"这批命令会超过一次编辑的 {MAX_COMMANDS_PER_BATCH} 条上限",
                    "details": {
                        "commands": len(accepted) + len(whole),
                        "limit": MAX_COMMANDS_PER_BATCH,
                        "this_clip": len(whole),
                    },
                }
            )
            continue
        error = commit(whole)
        if error is None:
            beyond_tail += sum(beyond for _, _, beyond in groups)
            written.append({"clip_id": clip_id, "categories": [name for name, _, _ in groups]})
            continue
        # 整段粘不进去时拆开重问：人要知道是哪一类过不去，而不是看见整段被跳过。
        # 每一类仍然按它在表里的顺序单独过一遍同一个 reducer，写进去的那几类就是最终那一批命令，
        # 所以「计划」和「提交」仍然对得上——只是类别之间不再互相连坐。
        landed: list[str] = []
        for category, commands, beyond in groups:
            error = commit(commands)
            if error is None:
                landed.append(category)
                beyond_tail += beyond
            else:
                refusals.append({**error, "clip_id": clip_id, "category": category})
        if landed:
            written.append({"clip_id": clip_id, "categories": landed})
    return {
        "source_clip_id": source_id,
        "sequence_id": sequence_id,
        "categories": [row for row in category_content(source) if row["category"] in wanted],
        "all_categories": category_content(source),
        "requested": len(requested),
        "targets": len(targets),
        "commands": accepted,
        "written": written,
        "unchanged": unchanged,
        "refusals": refusals,
        "beyond_tail_keyframes": beyond_tail,
        "target_limit": ATTRIBUTE_PASTE_TARGET_LIMIT,
        "command_limit": MAX_COMMANDS_PER_BATCH,
    }
