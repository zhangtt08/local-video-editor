"""One animation clock shared by rendering and the browser's native animation plan."""

import hashlib  # preview filter ids are content-addressed, like the caption text files
from math import sqrt

from .contracts import (
    FADE_SHAPE_CURVES,
    MASK_FIELDS,
    PROPERTY_LIMITS,
    SPATIAL_SCHEDULE_MAX,
    TIMEBASE,
    Bezier,
    Clip,
    ClipEffects,
    EditorError,
    Keyframe,
    Project,
    Track,
)
from .grade import preview_grade
from .masks import animated_mask_image, mask_image
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
    span = clip.duration_ticks
    if span <= 0 or not points(clip, prop):
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
        value = round(sample(clip, prop, (start + end) // 2), 9)
        if windows and windows[-1]["value"] == value:
            windows[-1]["to_ticks"] = end
        else:
            windows.append({"from_ticks": start, "to_ticks": end, "value": value})
        start = end
    return windows


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


def sharpen_preview(clip: Clip, width: int, height: int) -> dict | None:
    """The browser's copy of the unsharp mask: the same amount, a radius expressed in frame units.

    The preview filter runs in `objectBoundingBox` units, where a stdDeviation of 1 is the whole box
    — so the y fraction is the radius over the frame height and the x one over the frame width. Both
    come from `contracts.spatial_radius`, which is what the exporter hands `gblur`, so the two ends
    convolve the same Gaussian. The id is content-addressed because the `<filter>` element is shared
    by every clip asking for the same numbers, exactly like the grade tables.
    """
    if clip.effects.sharpen <= 0:
        return None
    fraction = clip.effects.sharpen_radius
    spec = f"{clip.effects.sharpen:.6g}|{fraction:.6g}"
    return {
        "id": "sh" + hashlib.sha256(spec.encode()).hexdigest()[:12],
        "amount": clip.effects.sharpen,
        "bbox": [round(fraction * height / width, 6), round(fraction, 6)],
    }


def preview_manifest(
    project: Project, sequence_id: str | None = None, *, _include_sequences=True
) -> dict:
    """Browser uses native linear/steps interpolation of these server-issued scalar curves.

    Each property is independent, so a held opacity curve cannot affect a moving position.
    Translation is relative to the composition, not the fitted source rectangle.
    """
    from .timeline import sequence_view

    root = project
    project = sequence_view(project, sequence_id)
    clips = {}
    tracks = {track.id: track for track in project.tracks}
    transition_curves = envelopes(project)
    for clip in project.clips.values():
        curves = {}
        for prop in ("x", "y", "scale", "rotation", "opacity", "gain"):
            curves[prop] = property_curve(clip, prop)
        grade = preview_grade(clip.color)
        track = tracks[clip.track_id]
        # The fade travels as its own curve because the browser multiplies nested opacity, not two
        # numbers on one element: a factor curve holding 1.0 through the middle of the clip composes
        # with the property curve the same way `expression` above composes them for FFmpeg.
        fade = {
            prop: property_curve(carrier, "opacity")
            for prop in FADE_PROPS
            if (carrier := _fade_carrier(clip, prop)) is not None
        }
        mask_curves = {
            prop: property_curve(clip, prop) for prop in MASK_FIELDS if points(clip, prop)
        }
        animated = bool(mask_curves) and clip.mask is not None
        sharpen = sharpen_preview(clip, project.settings.width, project.settings.height)
        quantum = (
            project.settings.frame_ticks
            if track.kind == "video"
            else project.settings.timebase // project.settings.sample_rate
        )
        # 1.98: the staircase is the authority, so the browser animates the very same windows the
        # exporter chains — see `spatial_schedule`.
        spatial = {
            prop: spatial_curve(clip, spatial_schedule(clip, prop, quantum))
            for prop in SPATIAL_PROPS
            if points(clip, prop)
        }
        clips[clip.id] = {
            "spatial": spatial or None,
            "mask_image": mask_image(clip.mask, project.settings.width, project.settings.height)
            if clip.mask
            else None,
            "mask_curves": mask_curves or None,
            "mask_unit": animated_mask_image(
                clip.mask, project.settings.width, project.settings.height
            )
            if animated
            else None,
            "sound_enabled": sound_enabled(clip, track),
            "speed": describe(segments(clip, quantum, project.settings.frame_ticks), TIMEBASE)
            if clip.speed_curve
            else None,
            "curves": curves,
            "duration_ms": clip.duration_ticks / TIMEBASE * 1000,
            "sharpen": sharpen,
            "color_filter": (
                f"brightness({2**clip.color.exposure}) "
                f"contrast({clip.color.contrast}) saturate({clip.color.saturation})"
            )
            + (f" url(#{grade['id']})" if grade else "")
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
            # always was.
            + ("" if spatial else (f" url(#{sharpen['id']})" if sharpen else "")),
            "edge_filter": (f" url(#{sharpen['id']})" if sharpen and spatial else None),
            "grade": grade,
            "transition": transition_curves[clip.id],
            "fade": fade or None,
        }
    return {
        "revision": project.revision,
        "sequence_id": sequence_id,
        "sequences": {
            key: preview_manifest(root, key, _include_sequences=False) for key in root.sequences
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


def graph_curve(clip: Clip, prop: str) -> dict:
    """SVG geometry from the same scalar curve as WAAPI, including clipped ease tangents."""
    curve = property_curve(clip, prop)
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
    return {
        "property": prop,
        "duration_ticks": clip.duration_ticks,
        "limits": PROPERTY_LIMITS[prop],
        "path": " ".join(path),
        "curve": curve,
        "keys": [
            {**key.model_dump(), "at_ticks": key.at_ticks - clip.animation_offset_ticks}
            for key in points(clip, prop)
            if clip.animation_offset_ticks
            <= key.at_ticks
            <= clip.animation_offset_ticks + clip.duration_ticks
        ],
    }
