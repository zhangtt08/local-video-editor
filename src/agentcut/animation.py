"""One animation clock shared by rendering and the browser's native animation plan."""

import hashlib  # preview filter ids are content-addressed, like the caption text files
from math import sqrt

from .contracts import (
    FADE_SHAPE_CURVES,
    LAYER_KEY_LIMITS,
    LAYER_SCHEDULE_MAX,
    MASK_FIELDS,
    MASK_ROTATION_SCHEDULE_MAX,
    MASK_SHAPE_SCHEDULE_MAX,
    PROPERTY_LIMITS,
    SHARPEN_SCHEDULE_MAX,
    SPATIAL_SCHEDULE_MAX,
    TIMEBASE,
    Bezier,
    Clip,
    ClipEffects,
    EditorError,
    Keyframe,
    MaskShapeKeyframe,
    MaskVertex,
    Project,
    Track,
    box_value,
)
from .grade import composite_stages, layer_stages, preview_grade
from .masks import animated_mask_image, cover_svg_image, fit_box, mask_image
from .speed import describe, segments
from .timeline import link_status
from .transitions import envelopes


def sound_enabled(clip: Clip, track: Track) -> bool:
    return not track.muted and (track.kind == "audio" or clip.embedded_audio)


def points(clip: Clip, prop: str):
    return sorted((k for k in clip.keyframes if k.property == prop), key=lambda k: k.at_ticks)


def bezier_value(a: float, b: float, u: float) -> float:
    return u * (3 * a + u * (3 * b - 6 * a + u * (1 + 3 * a - 3 * b)))


def bezier_extrema(a: float, b: float) -> list[float]:
    quadratic, linear, constant = 3 * (1 + 3 * a - 3 * b), 6 * b - 12 * a, 3 * a
    if abs(quadratic) < 1e-14:
        roots = [-constant / linear] if abs(linear) > 1e-14 else []
    else:
        discriminant = linear * linear - 4 * quadratic * constant
        roots = (
            [(-linear + sign * sqrt(max(0, discriminant))) / (2 * quadratic) for sign in (-1, 1)]
            if discriminant >= 0
            else []
        )
    return sorted({u for u in roots if 0 < u < 1})


def bezier_parameter(controls: Bezier, at: float) -> float:
    if at <= 0 or at >= 1:
        return max(0, min(1, at))
    low, high = 0.0, 1.0
    for _ in range(52):
        mid = (low + high) / 2
        value = bezier_value(controls.x1, controls.x2, mid)
        if value == at:
            return mid
        if value < at:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def _cubic_expression(a: float, b: float, u: str) -> str:
    return f"({u}*({3 * a}+{u}*({3 * b - 6 * a}+{u}*({1 + 3 * a - 3 * b}))))"


def _clipped_axis(p1, p2, a, b):
    begin, end = bezier_value(p1, p2, a), bezier_value(p1, p2, b)
    delta = end - begin
    if abs(delta) < 1e-14:
        return 1 / 3, 2 / 3

    def derivative(u):
        return 3 * p1 + u * (6 * p2 - 12 * p1 + u * (3 + 9 * p1 - 9 * p2))

    return (b - a) * derivative(a) / (3 * delta), 1 - (b - a) * derivative(b) / (3 * delta)


def base_value(clip: Clip, prop: str) -> float:
    """Where a property lives: the effects block, or the clip's own mask geometry."""
    field = MASK_FIELDS.get(prop)
    if field is None:
        return float(getattr(clip.effects, prop))
    return float(getattr(clip.mask, field)) if clip.mask else 0.0


FADE_PROPS = ("opacity", "gain")


def fade_windows(clip: Clip, prop: str) -> tuple[int, int]:
    """This clip's fade windows, measured from its own edges and clamped to fit the clip."""
    if clip.fade is None or prop not in FADE_PROPS:
        return 0, 0
    in_ticks, out_ticks = clip.fade.window(prop)
    in_ticks = min(in_ticks, clip.duration_ticks)
    return in_ticks, min(out_ticks, clip.duration_ticks - in_ticks)


def fade_active(clip: Clip, prop: str) -> bool:
    return any(fade_windows(clip, prop))


def _fade_ramp(shape: str, from_head: bool) -> tuple[str, Bezier | None]:
    """这条淡斜坡用哪种插值。形状说的是「从淡的那一头走向静止的那一头」，所以淡出那一段要把控制点
    按时间反演镜像过来——同一个形状在两条边上摸起来才是一样的。linear 与 smoothstep 自己就对称。"""
    curve = FADE_SHAPE_CURVES[shape]
    if curve is None:
        return "linear", None
    if curve == "ease":
        return "ease", None
    x1, y1, x2, y2 = curve  # type: ignore[misc]
    if not from_head:
        x1, y1, x2, y2 = 1 - x2, 1 - y2, 1 - x1, 1 - y1
    return "bezier", Bezier(x1=x1, y1=y1, x2=x2, y2=y2)


def fade_curve(clip: Clip, prop: str) -> list[Keyframe]:
    """The fade as an ordinary piecewise curve on a clock that starts at this clip's head.

    1.0 means "this property is untouched", so the curve multiplies whatever else the property
    carries. The ramps take their shape from `Clip.fade` — the default is the same smoothstep a
    hand-keyed fade used before 1.90, so an old project renders exactly as it did.
    """
    in_ticks, out_ticks = fade_windows(clip, prop)
    if not in_ticks and not out_ticks:
        return []
    shape = clip.fade.shape(prop) if clip.fade else "ease_in_out"
    duration = clip.duration_ticks
    positions = sorted({0, duration, in_ticks or duration, duration - (out_ticks or duration)})
    curve = []
    for index, at in enumerate(positions):
        following = positions[index + 1] if index + 1 < len(positions) else None
        value = 0.0 if (at == 0 and in_ticks) or (at == duration and out_ticks) else 1.0
        ramp = bool(
            following is not None
            and (
                (at == 0 and in_ticks and following == in_ticks)
                or (out_ticks and at == duration - out_ticks and following == duration)
            )
        )
        interpolation, controls = _fade_ramp(shape, at == 0) if ramp else ("linear", None)
        curve.append(
            Keyframe(
                property="opacity",
                at_ticks=at,
                value=value,
                interpolation=interpolation,
                bezier=controls,
            )
        )
    return curve


def _fade_carrier(clip: Clip, prop: str) -> Clip | None:
    """A stand-in clip whose only animation is this property's fade, so the fade is compiled by the
    same `expression`/`property_curve` as every other curve instead of a second implementation."""
    curve = fade_curve(clip, prop)
    if not curve:
        return None
    return clip.model_copy(
        deep=True,
        update={
            "fade": None,
            "animation_offset_ticks": 0,
            "keyframes": curve,
            "effects": ClipEffects(x=0, y=0, scale=1, rotation=0, opacity=1, gain=1),
        },
    )


def fade_factor(clip: Clip, prop: str, at_ticks: int) -> float:
    """Multiply a property value by this, on the same clock `sample` answers on."""
    keys = fade_curve(clip, prop)
    if not keys:
        return 1.0
    return _walk(keys, min(max(at_ticks, 0), clip.duration_ticks))


def sample(clip: Clip, prop: str, at_ticks: int) -> float:
    keys = points(clip, prop)
    value = _walk(keys, at_ticks + clip.animation_offset_ticks) if keys else base_value(clip, prop)
    if prop in FADE_PROPS and clip.fade is not None:
        value = value * fade_factor(clip, prop, at_ticks)
    return value


def _walk(keys: list[Keyframe], at: int) -> float:
    """The one piecewise walk: every curve in the project answers samples through this."""
    if at <= keys[0].at_ticks:
        return keys[0].value
    for left, right in zip(keys, keys[1:]):
        if at < right.at_ticks:
            return _interpolate(left, right, at)
    return keys[-1].value


def sample_values(clip: Clip, at_ticks: int) -> dict[str, float]:
    """Sample saved or candidate clips through the same render clock."""
    if not 0 <= at_ticks <= clip.duration_ticks:
        raise EditorError("INVALID_KEYFRAME", "sample lies outside clip")
    props = list(ClipEffects.model_fields)
    if clip.mask and clip.mask.shape != "path":
        props += list(MASK_FIELDS)
    return {prop: sample(clip, prop, at_ticks) for prop in props}


def _interpolate(left: Keyframe, right: Keyframe, at: int) -> float:
    if left.interpolation == "hold":
        return left.value
    mix = (at - left.at_ticks) / (right.at_ticks - left.at_ticks)
    if left.interpolation == "ease":
        mix = mix * mix * (3 - 2 * mix)
    elif left.interpolation == "bezier":
        controls = left.bezier or Bezier()
        mix = bezier_value(controls.y1, controls.y2, bezier_parameter(controls, mix))
    return left.value + (right.value - left.value) * mix


def expression(clip: Clip, prop: str, clock: str = "t", registers: tuple[int, int] = (8, 9)) -> str:
    """Compile the same piecewise curve to a controlled FFmpeg expression.

    A fade multiplies the curve it rides on, and it happens here rather than at each call site: the
    exporter must not be able to forget it the way the keyframe fades forgot a duck, and `sample`
    above answers on the same product.
    """
    curve = _curve_expression(clip, prop, clock, registers)
    carrier = _fade_carrier(clip, prop) if prop in FADE_PROPS else None
    if carrier is None:
        return curve
    return f"({curve})*({_curve_expression(carrier, 'opacity', clock, registers)})"


def _curve_expression(clip: Clip, prop: str, clock: str, registers: tuple[int, int]) -> str:
    keys = points(clip, prop)
    if not keys:
        return str(base_value(clip, prop))
    t = f"({clock}+{clip.animation_offset_ticks / TIMEBASE:.12f})"
    result = str(keys[-1].value)
    for left, right in reversed(list(zip(keys, keys[1:]))):
        a, b = left.at_ticks / TIMEBASE, right.at_ticks / TIMEBASE
        value = str(left.value)
        if left.interpolation != "hold":
            mix = f"(({t}-{a:.12f})/{b - a:.12f})"
            if left.interpolation == "ease":
                mix = f"({mix}*{mix}*(3-2*{mix}))"
            elif left.interpolation == "bezier":
                controls = left.bezier or Bezier()
                # FFmpeg's native root evaluator inverts the monotone temporal cubic.
                temporal = _cubic_expression(controls.x1, controls.x2, "ld(0)")
                scalar = _cubic_expression(controls.y1, controls.y2, "ld(0)")
                mix = f"(st(0,root({temporal}-{mix},1));{scalar})"
            value = f"({value}+({right.value - left.value})*{mix})"
        result = f"if(lt({t},{b:.12f}),{value},{result})"
    result = f"if(lt({t},{keys[0].at_ticks / TIMEBASE:.12f}),{keys[0].value},{result})"
    if clock == "T" and any(k.interpolation == "bezier" for k in keys):
        # geq evaluates per pixel; cache this scalar once per frame, separately per evaluator.
        value, stamp = registers
        result = f"if(eq(ld({stamp}),T+1),ld({value}),(st({stamp},T+1);st({value},{result})))"
    return result


def property_curve(clip: Clip, prop: str) -> list[dict]:
    times = {0, clip.duration_ticks}
    keys = points(clip, prop)
    times.update(
        k.at_ticks - clip.animation_offset_ticks
        for k in keys
        if 0 < k.at_ticks - clip.animation_offset_ticks < clip.duration_ticks
    )
    for left, right in zip(keys, keys[1:]):
        if left.interpolation == "bezier":
            controls = left.bezier or Bezier()
            for u in sorted(
                set(
                    bezier_extrema(controls.y1, controls.y2)
                    + bezier_extrema(controls.x1, controls.x2)
                )
            ):
                at = (
                    left.at_ticks
                    + (right.at_ticks - left.at_ticks) * bezier_value(controls.x1, controls.x2, u)
                    - clip.animation_offset_ticks
                )
                if 0 < at < clip.duration_ticks:
                    times.add(at)
    # A cropped monotone cubic can have controls outside its cropped time interval.
    # Split exactly with De Casteljau until each native CSS easing has valid x controls.
    cuts = sorted(times)
    key_index = 0
    for begin, end in zip(cuts, cuts[1:]):
        clock = begin + clip.animation_offset_ticks
        while key_index + 1 < len(keys) and keys[key_index + 1].at_ticks <= clock:
            key_index += 1
        if not keys or key_index + 1 >= len(keys):
            continue
        left, right = keys[key_index], keys[key_index + 1]
        if left.interpolation != "bezier" or clock < left.at_ticks:
            continue
        controls = left.bezier or Bezier()
        span = right.at_ticks - left.at_ticks
        a = bezier_parameter(controls, (clock - left.at_ticks) / span)
        b = bezier_parameter(controls, (end + clip.animation_offset_ticks - left.at_ticks) / span)
        pending = [(a, b)]
        while pending:
            a, b = pending.pop()
            x1, x2 = _clipped_axis(controls.x1, controls.x2, a, b)
            if min(x1, x2) < -1e-12 or max(x1, x2) > 1 + 1e-12:
                mid = (a + b) / 2
                times.add(
                    left.at_ticks
                    + span * bezier_value(controls.x1, controls.x2, mid)
                    - clip.animation_offset_ticks
                )
                pending.extend(((a, mid), (mid, b)))
    curve = []
    ordered = sorted(times)
    key_index = -1
    for index, at in enumerate(ordered):
        clock = at + clip.animation_offset_ticks
        while key_index + 1 < len(keys) and keys[key_index + 1].at_ticks <= clock:
            key_index += 1
        left = keys[key_index] if key_index >= 0 else None
        right = keys[key_index + 1] if key_index + 1 < len(keys) else None
        value = (
            _interpolate(left, right, clock)
            if left and right
            else left.value
            if left
            else right.value
            if right
            else base_value(clip, prop)
        )
        easing = "linear"
        if left and left.interpolation == "hold":
            easing = "steps(1, end)"
        elif (
            left and right and left.interpolation in {"ease", "bezier"} and index < len(ordered) - 1
        ):
            span = right.at_ticks - left.at_ticks
            a = (clock - left.at_ticks) / span
            b = (ordered[index + 1] + clip.animation_offset_ticks - left.at_ticks) / span
            controls = left.bezier or Bezier()
            ua, ub = (
                (a, b)
                if left.interpolation == "ease"
                else (bezier_parameter(controls, a), bezier_parameter(controls, b))
            )
            x1, x2 = _clipped_axis(controls.x1, controls.x2, ua, ub)
            y1, y2 = _clipped_axis(controls.y1, controls.y2, ua, ub)
            easing = f"cubic-bezier({max(0, min(1, x1))},{y1},{max(0, min(1, x2))},{y2})"
        curve.append(
            {
                "offset": at / clip.duration_ticks,
                "value": value,
                "easing": easing,
            }
        )
    return curve


SPATIAL_PROPS = ("blur",)


def frame_windows(clip: Clip, quantum: int, limit: int | None, value_at) -> list[dict]:
    """The one frame-aligned staircase compiler: sample at each window's own start frame,
    merge the equal ones.

    取样点定在段起点（1.182）：一枚针在它自己那一帧就必须被执行，否则人敲进去的角度与尺寸
    在预览与导出里谁都不出现，画面上那颗手柄也会在松手后跳回指针之外。两端共用这一份表这件事
    没变——变的只是每窗带哪一个数。

    Two knobs in this app cannot be evaluated continuously by the exporter — `gblur` reads no
    expression for its sigma, and a morphing free-form mask cannot be rasterised per frame — so both
    compile to constant windows and both ends execute that same list. `value_at(clip, at_ticks)`
    returns whatever is comparable and hashable for one step; merging on equality is what keeps a
    curve that happens to be flat at one window boundary from costing two stages at both ends.
    """
    span = clip.duration_ticks
    if span <= 0:
        return []
    ceiling = SPATIAL_SCHEDULE_MAX if limit is None else max(1, limit)
    grid = max(1, int(quantum or 1))
    # Whole frames first, then as many frames per step as the ceiling needs: a step that is not a
    # multiple of the frame grid would put a window boundary between two frames, and the exporter's
    # `enable` window is evaluated per frame anyway — it would silently drop the boundary.
    per_window = max(grid, -(-span // max(1, ceiling)))
    step = ((per_window + grid - 1) // grid) * grid
    windows: list[dict] = []
    start = 0
    while start < span:
        end = min(start + step, span)
        value = value_at(clip, start)
        if windows and windows[-1]["value"] == value:
            windows[-1]["to_ticks"] = end
        else:
            windows.append({"from_ticks": start, "to_ticks": end, "value": value})
        start = end
    return windows


def spatial_schedule(clip: Clip, prop: str, quantum: int, limit: int | None = None) -> list[dict]:
    """The windows a keyframed spatial knob actually executes — the same list at both ends.

    `gblur` has no per-frame sigma: its only time hook is `enable`, an on/off window. Letting the
    export step while the browser interpolates smoothly is exactly why this knob refused keyframes
    before 1.98. The answer is not to hide the staircase but to make it the single authority: the
    curve is sampled here into frame-aligned windows, at most `limit` of them, and the exporter
    chains one `gblur=sigma=…:enable='between(t,…)'` per window while the browser animates those
    same windows with `steps(1, end)`. A clip shorter than `limit` frames is therefore exact at the
    frame level, and a longer one coarsens by a number both ends can be checked against.
    """
    if not points(clip, prop):
        return []

    def value_at(source: Clip, at: int) -> float:
        return round(sample(source, prop, at), 9)

    return frame_windows(clip, quantum, limit, value_at)


SHARPEN_PROPS = ("sharpen", "sharpen_radius")


def sharpen_schedule(clip: Clip, quantum: int, limit: int | None = None) -> list[dict]:
    """One window table carrying both unsharp knobs, so the amount and the radius never step apart.

    The unsharp step is one operation wearing two numbers: `source + amount · (source − gaussian)`
    whose gaussian's sigma is the radius. Compiling each curve on its own would let a radius step
    land in the middle of an amount window, and the exporter would then chain a stage the preview
    has no step for — the two ends would deliver different pictures while both faithfully executing
    "their" table. So one `frame_windows` pass samples the *pair* (its `value_at` may return
    anything hashable) and merges on the pair's equality: a step changes only when at least one of
    the two actually changes, and a clip that animates only the amount still reads its radius from
    the static knob, because `sample` falls back to `base_value`.
    """
    if not any(points(clip, prop) for prop in SHARPEN_PROPS):
        return []

    def value_at(source: Clip, at: int) -> tuple[float, float]:
        return (
            round(sample(source, "sharpen", at), 9),
            round(sample(source, "sharpen_radius", at), 9),
        )

    return frame_windows(clip, quantum, SHARPEN_SCHEDULE_MAX if limit is None else limit, value_at)


LAYER_KEY_PROPS = ("offset_x", "offset_y", "scale", "mix", "rotation")


def layer_nodes(clip: Clip) -> list:
    """有哪几层、按什么顺序——这一族只在这里数一次。

    `grade.layer_stages` 走的是 `grade_stages` 里那条「链尾、启用的才算」的判断，这里问的是
    同一批节点：`render.py` 与 `preview_manifest` 拿同一份顺序去对同一份窗表，不许各数各的。
    """
    return [node for node in clip.color.grade if node.kind == "layer" and node.enabled]


def layer_keys(node, prop: str) -> list:
    return sorted((key for key in node.keys if key.property == prop), key=lambda key: key.at_ticks)


def layer_value_at(node, prop: str, at_ticks: int) -> float:
    """这一层在某一格上到底是几。没有针就读静态那一个数，与 `sample` 回落同一个地方。"""
    keys = layer_keys(node, prop)
    if not keys:
        return round(float(getattr(node, prop)), 9)
    return round(_walk(keys, at_ticks), 9)


def layer_schedule(clip: Clip, quantum: int, limit: int | None = None) -> list[list[dict]]:
    """每一层一份窗表；没有针的那一层交回空表，走静态那一条老路，编译串一字不改。

    五个数（位置两个、大小、淡、转角）在**同一次** `frame_windows` 里换值，所以「挪到哪」「多大
    一块」「转多少」不会各自踩各自的格子——与清晰那两颗旋钮共用一张表是同一个理由
    （`sharpen_schedule`）。导出为每一窗串一路 `crop` + 两段 `blend` + 一次 `overlay:enable`
    （转过的那一窗多一段 `rotate` 与一张 mask），浏览器把同一份窗表画成 `steps(1, end)` 的帧。
    """
    ceiling = LAYER_SCHEDULE_MAX if limit is None else max(1, limit)
    tables: list[list[dict]] = []
    for node in layer_nodes(clip):
        if not node.keys:
            tables.append([])
            continue

        def value_at(source: Clip, at: int, layer=node) -> tuple:
            clock = at + source.animation_offset_ticks
            return tuple(layer_value_at(layer, prop, clock) for prop in LAYER_KEY_PROPS)

        tables.append(frame_windows(clip, quantum, ceiling, value_at))
    return tables


def layer_curve(clip: Clip, table: list[dict]) -> list[dict]:
    """浏览器那份：每窗一个点，五个数一起换，`steps(1, end)` 就是导出那批格子的边界。"""
    span = clip.duration_ticks
    return [
        {
            "offset": window["from_ticks"] / span,
            "easing": "steps(1, end)",
            "offset_x": window["value"][0],
            "offset_y": window["value"][1],
            "scale": window["value"][2],
            "mix": window["value"][3],
            # 1.204：转角也是这一份窗表里的第五个数——上面那份名单的顺序就是这里的下标。
            "rotation": window["value"][4],
        }
        for window in table
    ]


def composite_row(clip: Clip, project: Project) -> dict | None:
    """这条链要不要在监视器里把「叠一层原图」画出来，以及画的是哪一档方式与权重。

    导出那两步是 `(1-mix)·raw + mix·mode(graded, raw)`（`render.py` 里那条边），浏览器用两层
    DOM 就能一次不差地画出来：底层原图，上面一个 `opacity=mix` 的容器，容器内「已调色」作底、
    原图按 `mix-blend-mode` 相合。2026-10-17 逐档量过：八种方式里七种与导出逐通道差 ≤2 级；
    `normal` 要交换容器里那两层的顺序——FFmpeg 的 `normal` 交回**第一个**输入、CSS 的
    `normal` 交回**上面那一层**，与 1.189 为图层量过的那条是同一件事。

    只有**记录里有那一次真的探测**才交回 `paintable: true`，而「什么时候画得成」由同一行里的
    `motion` 说：图像是 `"always"`（两幅都是已经解码好的位图，随时画）；视频是 `"paused"`——
    本轮量过（AGENTS 1.195 那一节）：暂停与逐帧时把主画面那一路用 `drawImage` 拓进一张 canvas，
    与导出逐格 0 差；而播放中再开一路解码会把主线程的动画帧率打掉一半（rAF 181 → 94），
    所以播放中这一级不画。没有探测记录时界面拿到的是空地址，画上去是两个空的图层，
    不是第二幅画，于是 `paintable` 假、`motion` 为 null。这一格由引擎说一次，界面只照着办。
    """
    edges = composite_stages(clip.color)
    if not edges:
        return None
    asset = project.assets.get(clip.asset_id)
    stage = edges[0]
    ready = asset is not None and asset.verified is not None
    motion = (
        "always" if ready and asset is not None and asset.kind == "image"
        else "paused" if ready and asset is not None and asset.kind == "video"
        else None
    )
    return {
        "mode": stage["mode"],
        "mix": stage["mix"],
        "paintable": motion is not None,
        "motion": motion,
    }


def layer_rows(clip: Clip, project: Project, quantum: int) -> list[dict]:
    """有哪几层、各盖在哪一块、现在画不画得成——一次算完，判断只在这一个函数里（1.200）。

    `paintable`/`reason` 问的就是导出那条 `LAYER_ASSET_UNAVAILABLE` 问的三件事：素材不在工程里、
    不是图像、没有引擎验过的媒体记录。1.193 为「叠一层原图」立的规矩是「画不画得了由引擎说一次」，
    当时漏了第二路画面这一头：删掉一张**只有层在用**的素材，清单照旧把那层交出去，浏览器拿不到
    地址就什么也不画，而导出整条拒绝——同一份状态两边说两种话。这一版让清单先说实话，
    界面照着说一句人读得懂的。
    """
    rows = [
        dict(stage, windows=layer_curve(clip, table))
        for stage, table in zip(
            layer_stages(clip.color), layer_schedule(clip, quantum), strict=True
        )
    ]
    for row in rows:
        asset = project.assets.get(row["asset_id"])
        if asset is None:
            row["paintable"], row["reason"] = False, "missing"
        elif asset.kind != "image":
            row["paintable"], row["reason"] = False, "kind"
        elif asset.verified is None:
            row["paintable"], row["reason"] = False, "unverified"
        else:
            row["paintable"], row["reason"] = True, None
    return rows


def outline_keys(clip: Clip) -> list[MaskShapeKeyframe]:
    return sorted(clip.mask_shape_keys, key=lambda key: key.at_ticks)


class _Ease:
    """一枚针穿着 `_interpolate` 认的那身衣服：一个时刻、一种缓动、一个端点。

    轮廓形变是六个数、再叠那块是五个数，而这个项目只有一条分段缓动的走法。与其为每种向量各抄一遍
    三次式和贝塞尔反解，不如把区间两端当成 0 与 1 交给这条走法——回来的就是那一份进度本身。
    """

    __slots__ = ("at_ticks", "value", "interpolation", "bezier")

    def __init__(self, key, value: float):
        self.at_ticks = key.at_ticks
        self.value = value
        self.interpolation = key.interpolation
        self.bezier = key.bezier


def vertices_at(clip: Clip, at_ticks: int) -> list[MaskVertex]:
    """The outline this clip draws at `at_ticks`: the shape as drawn, or the morph at that moment.

    Outside the first and last outline the shape holds, the same way a scalar curve holds its end
    values. Inside an interval every component rides one eased progress, so a vertex and its two
    handles cannot drift apart the way six independent curves would.
    """
    keys = outline_keys(clip)
    if not keys:
        return list(clip.mask.vertices or []) if clip.mask else []
    at = at_ticks + clip.animation_offset_ticks
    if at <= keys[0].at_ticks:
        return list(keys[0].vertices)
    for first, second in zip(keys, keys[1:]):
        if at < second.at_ticks:
            progress = _interpolate(_Ease(first, 0.0), _Ease(second, 1.0), at)
            return [_mix_vertex(a, b, progress) for a, b in zip(first.vertices, second.vertices)]
    return list(keys[-1].vertices)


def _mix_vertex(a: MaskVertex, b: MaskVertex, progress: float) -> MaskVertex:
    def blend(low: float, high: float) -> float:
        return round(low + (high - low) * progress, 9)

    return MaskVertex(
        x=blend(a.x, b.x),
        y=blend(a.y, b.y),
        handle_out=[
            blend(a.handle_out[0], b.handle_out[0]),
            blend(a.handle_out[1], b.handle_out[1]),
        ],
        handle_in=[
            blend(a.handle_in[0], b.handle_in[0]),
            blend(a.handle_in[1], b.handle_in[1]),
        ],
    )


BOX_STEPS = ("mask_rotation", "mask_width", "mask_height", "mask_feather")


def rotated_box(clip: Clip) -> bool:
    """Whether this box is the kind that can only step: a rotated rectangle or ellipse.

    The browser paints a rotated mask from one image the engine baked (a CSS `transform` on the
    masked layer leaves the mask axis-aligned - measured in 1.164), so the angle is a staircase.
    A box that also changes size over time cannot be that one image stretched non-uniformly,
    because the stretch would shear the angle; the honest answer is one image per window, carrying
    that window's own angle *and* edges. An unrotated box keeps the continuous curves it always
    had, byte for byte.
    """
    mask = clip.mask
    return bool(mask and mask.shape != "path" and (mask.rotation or points(clip, "mask_rotation")))


def mask_box_schedule(clip: Clip, quantum: int, limit: int | None = None) -> list[dict]:
    """The windows one turning box actually executes — the same list at both ends.

    A step's `value` is the tuple `(angle, width, height, feather)`, so those numbers swap on the
    *same* frame boundary at both ends: one table, four numbers. `geq` could evaluate an angle
    every frame, but the preview cannot, and a continuous angle on one side and a staircase on the
    other is exactly the split this project refuses. One `frame_windows` pass decides the steps;
    the exporter folds that list into its expressions and the preview ships one isotropic image
    per window. A clip shorter than `limit` frames is therefore exact at the frame level, and a
    longer one coarsens by a number both ends can be checked against.

    1.259: the soft edge joins that tuple. It is not a CSS quantity at all - the ramp lives inside
    the baked plate (`masks.svg_image`'s gradient stops) - so a keyed feather needs the plate
    machinery even for a box that never turns. A box with no feather keys keeps the continuous
    curves it always had, byte for byte.
    """
    if not rotated_box(clip) and not points(clip, "mask_feather"):
        return []
    if not any(points(clip, prop) for prop in BOX_STEPS):
        return []

    def value_at(source: Clip, at: int):
        return tuple(round(sample(source, prop, at), 9) for prop in BOX_STEPS)

    return frame_windows(
        clip, quantum, MASK_ROTATION_SCHEDULE_MAX if limit is None else limit, value_at
    )


MASK_EXTRA_FIELDS = ("center_x", "center_y", "width", "height", "rotation", "feather")


def extra_box_at(extra, at: int) -> tuple[float, ...]:
    """One extra box at a clip-local tick: its own keys interpolated, or the static box.

    The numbers travel together, so a segment's interpolation is one decision for the whole
    box — there is no per-edge easing to get out of step with the others. 1.258: the feather rides
    in this same tuple, so it changes on the very same frame boundaries; a key that does not state
    one answers with the box's own still feather (`box_value` is the only place that question is
    asked).
    """
    keys = extra.keys
    if not keys:
        return tuple(getattr(extra, name) for name in MASK_EXTRA_FIELDS)
    if at <= keys[0].at_ticks:
        return tuple(box_value(extra, keys[0], name) for name in MASK_EXTRA_FIELDS)
    if at >= keys[-1].at_ticks:
        return tuple(box_value(extra, keys[-1], name) for name in MASK_EXTRA_FIELDS)
    for left, right in zip(keys, keys[1:]):
        if left.at_ticks <= at <= right.at_ticks:
            # 1.257：这一串五个数走的缓动与轮廓形变是同一条式子——把区间两端交给 `_interpolate`，
            # 回来的就是那一份进度。这里不再自己写第二遍 hold/ease，贝塞尔因此也不必写第三遍。
            span = right.at_ticks - left.at_ticks
            progress = (
                0.0 if span <= 0 else _interpolate(_Ease(left, 0.0), _Ease(right, 1.0), at)
            )
            return tuple(
                round(
                    (start := box_value(extra, left, name))
                    + (box_value(extra, right, name) - start) * progress,
                    9,
                )
                for name in MASK_EXTRA_FIELDS
            )
    return tuple(box_value(extra, keys[-1], name) for name in MASK_EXTRA_FIELDS)


def extra_box_schedule(clip: Clip, extra, quantum: int, limit: int | None = None) -> list[dict]:
    """The same frame-aligned staircase as the main box, for one extra's own keys."""
    if not extra.keys:
        return []
    return frame_windows(
        clip,
        quantum,
        MASK_ROTATION_SCHEDULE_MAX if limit is None else limit,
        lambda _source, at: tuple(round(value, 9) for value in extra_box_at(extra, at)),
    )


def axis_steps(schedule: list[dict], index: int) -> list[dict]:
    """One number of the shared table as its own scalar schedule - same windows, one edge each."""
    return [{**window, "value": window["value"][index]} for window in schedule]


def rotation_step_expression(schedule: list[dict], frame_ticks: int, clock: str = "T") -> str:
    """The same windows as one FFmpeg expression: `T` is the clip's own seconds, as elsewhere.

    Nested `if(lt(...))` on each window's own end tick, so the boundary a frame reads is the
    boundary the preview swaps its image on — one table, read two ways. The switch sits at the
    **half-frame** inside that boundary: a frame's `T` is that frame's own start, so comparing it
    with the printed boundary decides on the last digits of a float (measured: frame 14 read
    window 13's angle, 6.5° off). Half a frame of margin is what the integer-tick lookup on the
    preview side already implies. The last window needs no test, and a window's value is written
    with enough digits to round-trip the sample.
    """
    if not schedule:
        return "0"
    tail = f"{schedule[-1]['value']:.9f}"
    for window in reversed(schedule[:-1]):
        bound = (window["to_ticks"] - frame_ticks // 2) / TIMEBASE
        tail = f"if(lt({clock},{bound:.12f}),{window['value']:.9f},{tail})"
    return tail


def mask_shape_schedule(clip: Clip, quantum: int, limit: int | None = None) -> list[dict]:
    """The windows one morphing outline actually executes — the same list at both ends.

    A free-form mask's alpha is a rasterised plate, and a plate per frame is neither affordable here
    nor something the browser could cross-fade, so an outline compiles into frame-aligned constant
    windows exactly as soft focus does (`frame_windows`). Each window carries the whole vertex table
    at its midpoint: the exporter bakes that one plate, the preview issues that one outline image,
    and neither end invents a middle. The mask's *box* keeps moving continuously on the
    `mask_x`/`mask_y` curves it already had, so only the shape steps.
    """
    if clip.mask is None or clip.mask.shape != "path" or not clip.mask_shape_keys:
        return []

    def value_at(source: Clip, at: int) -> list[MaskVertex]:
        return vertices_at(source, at)

    return frame_windows(clip, quantum, limit, value_at)


def outline_mask(clip: Clip, vertices: list[MaskVertex]):
    """The mask as stored, with one moment's outline in it.

    `model_copy` deliberately skips revalidation: a morph can pass through two coincident vertices
    on the way between shapes, and the rasteriser already ignores a zero-area edge — refusing to
    render the frame the person animated to would be the defect.
    """
    return clip.mask.model_copy(update={"vertices": vertices})


def spatial_curve(clip: Clip, schedule: list[dict]) -> list[dict]:
    """The browser's copy of the schedule: one point per window, each held with a step easing."""
    span = clip.duration_ticks
    return [
        {
            "offset": window["from_ticks"] / span,
            "value": window["value"],
            "easing": "steps(1, end)",
        }
        for window in schedule
    ]


def sharpen_spec(amount: float, fraction: float, width: int, height: int) -> dict:
    """One unsharp step as the browser draws it: the id, the amount, and the radius in box units.

    The preview filter runs in `objectBoundingBox` units, where a stdDeviation of 1 is the whole box
    — so the y fraction is the radius over the frame height and the x one over the frame width. Both
    come from `contracts.spatial_radius`, which is what the exporter hands `gblur`, so the two ends
    convolve the same Gaussian. The id is content-addressed because the `<filter>` element is shared
    by every clip asking for the same numbers, exactly like the grade tables — a window that repeats
    the static numbers reuses that one def instead of minting a second.
    """
    spec = f"{amount:.6g}|{fraction:.6g}"
    return {
        "id": "sh" + hashlib.sha256(spec.encode()).hexdigest()[:12],
        "amount": amount,
        "bbox": [round(fraction * height / width, 6), round(fraction, 6)],
    }


def sharpen_preview(clip: Clip, width: int, height: int) -> dict | None:
    """The browser's copy of a static unsharp mask: nothing steps, so one filter serves the clip."""
    if clip.effects.sharpen <= 0:
        return None
    return sharpen_spec(clip.effects.sharpen, clip.effects.sharpen_radius, width, height)


def sharpen_windows(
    clip: Clip, width: int, height: int, quantum: int, limit: int | None = None
) -> dict | None:
    """The browser's copy of the unsharp staircase: one `<filter>` per window, steps in between.

    This is the very list the exporter chains (`sharpen_schedule`), with the same `steps(1, end)`
    easing soft focus already uses. CSS cannot animate one term of a shared filter list, so the edge
    layer swaps its whole `filter` between this window's def and `none` — which is also why the
    static `url(#…)` leaves `color_filter` when a curve exists, exactly as it did for an animated
    radius beside an animated blur. A window whose amount is 0 has nothing to composite (the
    exporter skips its stage), so it is named `id: null` and the browser shows `none`.
    """
    schedule = sharpen_schedule(clip, quantum, limit)
    if not schedule:
        return None
    span = clip.duration_ticks
    windows = [
        {
            "from_ticks": window["from_ticks"],
            "to_ticks": window["to_ticks"],
            **sharpen_spec(window["value"][0], window["value"][1], width, height),
        }
        for window in schedule
    ]
    return {
        "windows": windows,
        "curve": [
            {
                "offset": window["from_ticks"] / span,
                "id": window["id"] if window["amount"] > 0 else None,
                "easing": "steps(1, end)",
            }
            for window in windows
        ],
    }


def preview_manifest(
    project: Project,
    sequence_id: str | None = None,
    *,
    clip_ids: list[str] | None = None,
    _include_sequences=True,
) -> dict:
    """Browser uses native linear/steps interpolation of these server-issued scalar curves.

    Each property is independent, so a held opacity curve cannot affect a moving position.
    Translation is relative to the composition, not the fitted source rectangle.

    `clip_ids` narrows the reply to the clips a caller is actually looking at. It is a view, not a
    second compiler: every entry it does return is the same value the full manifest gives, and the
    project-level keys stay whole. An absent list means the whole project, which is what the
    desktop compositor still asks for.
    """
    from .timeline import resolve_sequence, sequence_view

    root = project
    # 1.216：回执里那一个 `sequence_id` 是**解析后的 id**，不是调用方发来的那一行。
    resolved = resolve_sequence(root, sequence_id)
    project = sequence_view(root, resolved)
    clips = {}
    tracks = {track.id: track for track in project.tracks}
    # A narrowed envelope set has to stay the same answer per kept clip, so the skip happens
    # inside `envelopes` (which still indexes every clip's outgoing tail) rather than by editing
    # the project the curves are compiled from.
    wanted = None if clip_ids is None else set(clip_ids)
    transition_curves = envelopes(project, wanted)
    for clip in project.clips.values():
        if wanted is not None and clip.id not in wanted:
            continue
        curves = {}
        for prop in ("x", "y", "scale", "rotation", "opacity", "gain"):
            curves[prop] = property_curve(clip, prop)
        # 1.234：立方表能不能交给画布，只问这一处——画面是视频或图片才谈得上读那一帧；
        # 文字层（DOM 文字）与嵌套合成（一棵子树）都交不出 TexImageSource。
        source_asset = project.assets.get(clip.asset_id)
        drawable = (
            bool(source_asset)
            and source_asset.kind in ("video", "image")
            and not source_asset.sequence_id
        )
        grade = preview_grade(
            clip.color,
            project.settings.working_primaries,
            project.settings.fold_transfer,
            draw_cube=drawable,
        )
        # 1.234：链上有立方表时整条链（含曝光/对比/饱和）由画布上的 WebGL 走一遍，CSS 这一串
        # 里一格都不许再乘——两边都算就是两次调色。`color_basics` 是画布要的那三个数，
        # 与 `color_filter` 里那三项同源：同一条式子在下面只算一次。
        # 判据必须是「格点真的在这条回包里」（`cells_u8`）：文字层、嵌套合成、带第二路画面的
        # 那种链上立方交不出去，画布画不了——那时清空 CSS 就是把整条调色悄悄丢掉。
        webgl = bool(grade) and any(
            stage.get("type") == "lut3d" and stage.get("cells_u8") for stage in grade["stages"]
        )
        basics = [2**clip.color.exposure, clip.color.contrast, clip.color.saturation]
        track = tracks[clip.track_id]
        # The fade travels as its own curve because the browser multiplies nested opacity, not two
        # numbers on one element: a factor curve holding 1.0 through the middle of the clip composes
        # with the property curve the same way `expression` above composes them for FFmpeg.
        fade = {
            prop: property_curve(carrier, "opacity")
            for prop in FADE_PROPS
            if (carrier := _fade_carrier(clip, prop)) is not None
        }
        # Whether this mask is animated is decided below, once the stepped table is in: a clip that
        # only turns its box is animated just the same.
        sharpen = sharpen_preview(clip, project.settings.width, project.settings.height)
        quantum = (
            project.settings.frame_ticks
            if track.kind == "video"
            else project.settings.timebase // project.settings.sample_rate
        )
        # A turning box's angle and two edges are one window table, not three piecewise walks:
        # `frame_windows` steps all three on the same boundary, `spatial_curve` gives the browser
        # one stepped point per window per number, and `cover_svg_image` bakes one plate per window.
        box_schedule = mask_box_schedule(clip, quantum, MASK_ROTATION_SCHEDULE_MAX)
        mask_curves = {
            prop: (
                # `BOX_STEPS.index`, not a loop named `index`: that one means the input pad.
                spatial_curve(clip, axis_steps(box_schedule, BOX_STEPS.index(prop)))
                if box_schedule and prop in BOX_STEPS
                else property_curve(clip, prop)
            )
            for prop in MASK_FIELDS
            if points(clip, prop)
        }
        # 1.98: the staircase is the authority, so the browser animates the very same windows the
        # exporter chains — see `spatial_schedule`.
        spatial = {
            prop: spatial_curve(clip, spatial_schedule(clip, prop, quantum))
            for prop in SPATIAL_PROPS
            if points(clip, prop)
        }
        # 1.123: an animated unsharp mask ships the same window list the exporter chains, so the
        # browser steps where the export steps — including which windows do nothing at all.
        stepped = sharpen_windows(clip, project.settings.width, project.settings.height, quantum)
        # 1.118: a morphing outline ships as the very window list the exporter cuts its plates from
        # — one unit image per window, plus the numbers that put that image where the plate lands.
        # The browser only selects the window the engine named and places it with numbers it was
        # handed, so neither end can invent a shape in between and the guide shows the outline the
        # delivered file will actually cut.
        mask_shape = []
        for window in mask_shape_schedule(clip, quantum, MASK_SHAPE_SCHEDULE_MAX):
            shape = outline_mask(clip, window["value"])
            fitted = fit_box(shape)
            mask_shape.append(
                {
                    "from_ticks": window["from_ticks"],
                    "to_ticks": window["to_ticks"],
                    "image": animated_mask_image(
                        shape, project.settings.width, project.settings.height
                    ),
                    "vertices": [vertex.model_dump() for vertex in window["value"]],
                    # Where this window's plate lands and how wide it is, in the exporter's own
                    # numbers: the patch spans the outline as morphed (`width`), and the box curves
                    # only translate it from the centre the shape was drawn at (`offset`).
                    "width": round(fitted.width, 9),
                    "height": round(fitted.height, 9),
                    "offset_x": round(fitted.center_x - clip.mask.center_x, 9),
                    "offset_y": round(fitted.center_y - clip.mask.center_y, 9),
                }
            )
        rotation_windows = (
            [
                {
                    "from_ticks": window["from_ticks"],
                    "to_ticks": window["to_ticks"],
                    "angle": window["value"][0],
                    "width": window["value"][1],
                    "height": window["value"][2],
                    # 1.259：这一窗执行的那一条软边也写在这一行上——界面画那一框时读的
                    # 就是这一份，不在浏览器里再插一次值。
                    "feather": window["value"][3],
                    # One plate per window: the isotropic canvas already carries that window's own
                    # angle, edges and ramp, so the browser's only job stays translating it.
                    "image": cover_svg_image(
                        clip.mask.model_copy(
                            update={
                                "rotation": window["value"][0],
                                "width": window["value"][1],
                                "height": window["value"][2],
                                "feather": window["value"][3],
                                "center_x": 0.5,
                                "center_y": 0.5,
                            }
                        ),
                        project.settings.width,
                        project.settings.height,
                    ),
                }
                for window in box_schedule
            ]
            if clip.mask is not None
            else []
        )
        mask_unit = None
        animated = bool(mask_curves) and clip.mask is not None
        if animated and not mask_shape:
            # With a turning box the first window's plate is the only honest unit image: the angle
            # inside it is the one the exporter will read at that time, not the static field.
            mask_unit = (
                rotation_windows[0]["image"]
                if rotation_windows
                else animated_mask_image(clip.mask, project.settings.width, project.settings.height)
            )
        # 1.240：跟随时，不转的主遮罩与不转的再叠块共享「中心 + 大小」——预览把形状烘成
        # 一张单位图（填满盒子），用 `--mask-w/--mask-h` 的同两个比例缩放；导出把同一对比例
        # 乘进尺寸表达式。转了的主遮罩、自己带框点或自己转了的那一块不在这条路上。
        # 1.238：自己带框点的那一块按自己的窗表烘图；1.241：跟着一个**转了**的主遮罩时，
        # 按主遮罩的每一窗把这一块的角度与两条边一起烘进去（中心仍由 CSS 跟着平移）。
        extra_windows_list = []
        for extra in clip.extra_masks:
            own = extra_box_schedule(clip, extra, quantum) if extra.keys else []
            rows = []
            if own:
                rows = []
                for window in own:
                    # 1.255：这一窗执行的就是这五个数。界面画那一框、拖那一框都读这一份，
                    # 不在浏览器里再插一次值——两端同一张阶梯，一格一步。
                    box = dict(zip(MASK_EXTRA_FIELDS, window["value"]))
                    rows.append(
                        {
                            "from_ticks": window["from_ticks"],
                            "to_ticks": window["to_ticks"],
                            "follow": False,
                            "box": box,
                            "image": cover_svg_image(
                                extra.model_copy(update=box),
                                project.settings.width,
                                project.settings.height,
                            ),
                        }
                    )
            elif clip.extra_masks_follow and box_schedule and clip.mask is not None:
                for window in box_schedule:
                    # 按位置读那三个数——这一张窗表的元组里还有软边，而那一格是**这一块自己**的洞
                    # 的边，不跟着主遮罩的窗走（主遮罩糊多少，是它自己那一张图的事）。
                    angle, width, height = window["value"][:3]
                    scaled = extra.model_copy(
                        update={
                            "width": extra.width * (width / clip.mask.width),
                            "height": extra.height * (height / clip.mask.height),
                            "rotation": extra.rotation + (angle - clip.mask.rotation),
                        }
                    )
                    rows.append(
                        {
                            "from_ticks": window["from_ticks"],
                            "to_ticks": window["to_ticks"],
                            "follow": True,
                            "image": cover_svg_image(
                                scaled, project.settings.width, project.settings.height
                            ),
                        }
                    )
            extra_windows_list.append(rows or None)
        extra_windows_list = extra_windows_list or None
        extra_units = None
        if clip.extra_masks_follow:
            extra_units = [
                animated_mask_image(
                    extra.model_copy(
                        update={"center_x": 0.5, "center_y": 0.5,
                                "width": 1.0, "height": 1.0}
                    ),
                    project.settings.width,
                    project.settings.height,
                )
                if clip.mask is not None
                and not clip.mask.rotation
                and not points(clip, "mask_rotation")
                and not extra.rotation
                and not extra.keys
                else None
                for extra in clip.extra_masks
            ] or None
        clips[clip.id] = {
            "spatial": spatial or None,
            "mask_image": mask_image(clip.mask, project.settings.width, project.settings.height)
            if clip.mask
            else None,
            # 1.221：主遮罩之外再叠的几块，浏览器用 `mask-composite: intersect` 叠在同一幅画面上，
            # 导出用 `alpha*A*B` 乘在同一条 alpha 上——两端的图出自同一个 `mask_image`。
            "extra_mask_images": [
                mask_image(extra, project.settings.width, project.settings.height)
                for extra in clip.extra_masks
            ] or None,
            # 1.240：跟随时，不转的主遮罩与不转的再叠块共享「中心 + 大小」——预览把形状烘成
            # 一张单位图（填满盒子），用 `--mask-w/--mask-h` 的同两个比例缩放；导出把同一对比例
            # 乘进尺寸表达式。转了的主遮罩或自己带框点/自己转了的那一块不在这条路上。
            "extra_mask_units": extra_units,
            # 1.238：自己带框点的那一块，按窗烘一张整画面图（中心/宽高/角度都烘进去），
            # 浏览器按播放头挑那一窗——与导出那边同一张阶梯，一格一步。
            "extra_mask_windows": extra_windows_list,
            # 1.237：这几块跟不跟主遮罩的中心一起平移——浏览器按同一份曲线平移每一层。
            "extra_masks_follow": clip.extra_masks_follow,
            "mask_curves": mask_curves or None,
            "mask_rotation_windows": rotation_windows or None,
            "mask_shape": mask_shape or None,
            # The unit image is the box-only answer; a clip that animates its outline gets one image
            # per window instead, and the two would be the same bytes for the first of them.
            "mask_unit": mask_unit,
            "sound_enabled": sound_enabled(clip, track),
            "speed": describe(segments(clip, quantum, project.settings.frame_ticks), TIMEBASE)
            if clip.speed_curve
            else None,
            "curves": curves,
            "duration_ms": clip.duration_ticks / TIMEBASE * 1000,
            # One key, two shapes: a clip that does not step gets the single static filter the
            # browser has always drawn, a stepped one gets the window table it animates.
            "sharpen": stepped or sharpen,
            # 画布这一档自己算基础调色与整条链；CSS 这一串只剩柔焦与清晰（它们按顺序留在外层）。
            "webgl": webgl,
            "color_basics": basics if webgl else None,
            "color_filter": (
                ""
                if webgl
                else (
                    f"brightness({basics[0]}) "
                    f"contrast({basics[1]}) saturate({basics[2]})"
                )
                + (f" url(#{grade['id']})" if grade else "")
            )
            # The blur fraction the exporter feeds to `blur_sigma` becomes 1cqh = 1% of the frame's
            # rendered height here, so the preview's radius is the same number of frame-heights.
            # A keyframed radius is NOT baked in: `spatial` carries the windows and the browser
            # animates the same steps on its own wrapper — the same division the exporter makes,
            # where the schedule replaces the static stage rather than stacking on top of it.
            + (
                f" blur({clip.effects.blur * 100:g}cqh)"
                if clip.effects.blur > 0 and not spatial
                else ""
            )
            # Unsharp last, as in the exporter: tonal grade, then radius, then edge enhancement.
            # With a keyframed radius the unsharp step has to leave this string: the animated blur
            # is its own element (CSS cannot animate one term of a shared filter list), and the
            # exporter's order — grade, then blur, then edge — only survives if the edge filter sits
            # on the wrapper *outside* it. Without a curve nothing moves, so the string is what it
            # always was. From 1.123 an animated unsharp mask leaves it the same way, for the same
            # reason: the wrapper animates that window table, so a static `url(#…)` here would apply
            # the first step twice.
            + ("" if (spatial or stepped) else (f" url(#{sharpen['id']})" if sharpen else "")),
            "edge_filter": (
                f" url(#{sharpen['id']})" if sharpen and spatial and not stepped else None
            ),
            # 1.193：「叠一层原图」这条边也交给界面去画——画不画得了由引擎在这一处说一次。
            "composite": composite_row(clip, project),
            # 1.189：第二路画面按链里的顺序交出去，界面只负责把每张图叠在它那一层。
            # 方式与权重不在这里换算——`grade.layer_stages` 就是导出读的那一份。
            # 1.192：每一行还带它自己那份窗表（一枚针都没有就是空表，界面走静态那条老路）。
            # `strict=True` 不是洁癖：层数在两处各数一遍迟早数出不一样的顺序，而编译读的就是
            # 同一批节点（`layer_nodes`），对不齐要当场炸，不是画出一张错图。
            # 1.200：有哪几层、各盖在哪一块、现在画不画得成，全由 `layer_rows` 一处说——
            # 界面不许再问一遍「这个素材还在不在」。
            "layer": layer_rows(clip, project, quantum),
            "grade": grade,
            "transition": transition_curves[clip.id],
            "fade": fade or None,
        }
    return {
        "revision": project.revision,
        "sequence_id": resolved,
        "sequences": {
            key: preview_manifest(root, key, clip_ids=clip_ids, _include_sequences=False)
            for key in root.sequences
        }
        if _include_sequences
        else {},
        "track_blend_modes": {
            track.id: track.blend_mode for track in project.tracks if track.kind == "video"
        },
        "links": link_status(project),
        "clips": clips,
        "mixed_track_ids": sorted({c.track_id for c in project.clips.values() if c.transition_in}),
    }


def path_from(curve: list[dict]) -> str:
    """把一份点表画成 SVG 路径——**唯一那一个画法**：普通曲线与那一层的阶梯共用它。

    `steps(1, end)` 画成「横到边界再竖上去」的直角，正是导出那批 `enable` 格子与浏览器
    `steps(1, end)` 帧的形状；两条腿因此不是各画各的图。
    """
    first = curve[0]
    path = [f"M {first['offset']} {first['value']}"]
    for left, right in zip(curve, curve[1:]):
        x, y = left["offset"], left["value"]
        dx, dy = right["offset"] - x, right["value"] - y
        easing = left["easing"]
        if easing == "steps(1, end)":
            path.append(f"H {right['offset']} V {right['value']}")
        elif easing.startswith("cubic-bezier("):
            x1, y1, x2, y2 = map(float, easing[len("cubic-bezier(") : -1].split(","))
            path.append(
                f"C {x + dx * x1} {y + dy * y1} {x + dx * x2} {y + dy * y2} "
                f"{right['offset']} {right['value']}"
            )
        else:
            path.append(f"L {right['offset']} {right['value']}")
    return " ".join(path)


def graph_curve(clip: Clip, prop: str) -> dict:
    """SVG geometry from the same scalar curve as WAAPI, including clipped ease tangents."""
    curve = property_curve(clip, prop)
    return {
        "property": prop,
        "duration_ticks": clip.duration_ticks,
        "limits": PROPERTY_LIMITS[prop],
        "path": path_from(curve),
        "curve": curve,
        "keys": [
            {**key.model_dump(), "at_ticks": key.at_ticks - clip.animation_offset_ticks}
            for key in points(clip, prop)
            if clip.animation_offset_ticks
            <= key.at_ticks
            <= clip.animation_offset_ticks + clip.duration_ticks
        ],
    }


def layer_curve_points(clip: Clip, node_index: int, prop: str, quantum: int) -> list[dict]:
    """那一层那一个数在片段里到底怎么变——交回的就是**导出执行的那张窗表**。

    有针：每窗一个点，`easing` 就是引擎给的那个 `steps(1, end)`，再补一个 `offset=1` 的收口点
    （它不是一枚针，只是把最后那一级台阶画到头）。没针：整段一级台阶，值就是静态那一个数——
    于是曲线编辑器里看到的平线与检查器里那个框是同一个数，不是在屏幕上另算一遍。
    """
    node = layer_nodes(clip)[node_index]
    table = layer_schedule(clip, quantum)[node_index]
    windows = layer_curve(clip, table)
    if not windows:
        value = round(float(getattr(node, prop)), 9)
        return [
            {"offset": 0.0, "value": value, "easing": "steps(1, end)"},
            {"offset": 1.0, "value": value, "easing": "steps(1, end)"},
        ]
    points = [{"offset": w["offset"], "value": w[prop], "easing": w["easing"]} for w in windows]
    return points + [{"offset": 1.0, "value": points[-1]["value"], "easing": "steps(1, end)"}]


def layer_graph(clip: Clip, node_index: int, prop: str, quantum: int) -> dict:
    """那一层的一条阶梯曲线（读，不写）：与 `graph_curve` 同一份返回形状、同一个画法。

    `limits` 就是契约里那一条带 `LAYER_KEY_LIMITS[prop]`——与检查器里那个框、打点时那句拒绝
    同一条带；界面不许自己写数字。刻度按这一族唯一的折法折过一次（`animation_offset_ticks`），
    与 `graph_curve` 里那些针同一个口径。
    """
    node = layer_nodes(clip)[node_index]
    curve = layer_curve_points(clip, node_index, prop, quantum)
    start, stop = clip.animation_offset_ticks, clip.animation_offset_ticks + clip.duration_ticks
    return {
        "property": prop,
        "layer": node_index,
        "asset_id": node.asset_id,
        "duration_ticks": clip.duration_ticks,
        "limits": list(LAYER_KEY_LIMITS[prop]),
        "path": path_from(curve),
        "curve": curve,
        "keys": [
            {**key.model_dump(), "at_ticks": key.at_ticks - clip.animation_offset_ticks}
            for key in sorted(node.keys, key=lambda item: item.at_ticks)
            if start <= key.at_ticks <= stop
        ],
    }
