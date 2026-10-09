"""Server-issued scalar envelopes for premultiplied picture and linear sound blends.

Three shapes of transition are expressed here, and the exporter only ever consumes what this module
returns:

- a **scalar** picture/sound weight (dissolve, dip to black or white, and the audio of everything);
- a **spatial reveal** (`wipe`): the picture weight stays whole and a ramp across the frame decides
  who is visible, with the outgoing side getting the complement so the two layers still
  sum to one. `{"kind", "curve", "invert"}` per clip, compiled into the layer's alpha by `render`.
- a **size factor** (`scale`): zoom-in grows the incoming shot from `ZOOM_START` to 1 while it
  dissolves, zoom-out shrinks the outgoing one to `ZOOM_END`. Multiplied into the layer's scale.
- a **whole-layer translation** (`motion_x` / `motion_y`): push and slide move the shot across the
  frame. Offset is in fractions of the frame, the same unit the clip's own `x`/`y` use, so the
  exporter adds it straight into its `overlay=` term and the browser into its translate wrapper.
"""

from .contracts import TIMEBASE, Project

WIPE_KINDS = {
    # Named for where the revealing edge starts, because "wipe left" reads differently to different
    # editors: this one starts at the left border and travels right, uncovering the incoming shot.
    "wipe_from_left": ("x", False),
    "wipe_from_right": ("x", True),
    "wipe_from_top": ("y", False),
    "wipe_from_bottom": ("y", True),
}
ZOOM_START = 1.6
ZOOM_END = 0.6
# The reveal edge is not a hard cut: a ramp this wide (as a fraction of the frame) is what makes the
# boundary read as a wipe instead of a one-pixel jump between two opaque shots.
WIPE_FEATHER = 0.02

# A motion transition moves whole layers, so it needs one number per axis: where the incoming shot
# starts (in frame fractions, off-frame) and where the outgoing one ends. Named for the side the
# incoming shot arrives from — the same ruler the wipes use, so 「推移·从左入」 and 「从左擦除」
# travel the same way across the frame. The two sides always move apart, so the layers never overlap
# and the premultiplied sum stays at one; a covering 「滑动」 would need a frame-space complement.
MOTION_KINDS = {
    "push_from_left": ("x", -1.0, 1.0),
    "push_from_right": ("x", 1.0, -1.0),
    "push_from_top": ("y", -1.0, 1.0),
    "push_from_bottom": ("y", 1.0, -1.0),
}
# A wipe and a motion both reveal *space*, not light: the two shots stay fully opaque the whole
# window, so the scalar picture weight must stay whole or the export would double the exposure and
# the preview would show an instant cut. Sound still cross-fades like a dissolve.
WHOLE_WEIGHT_KINDS = {**WIPE_KINDS, **MOTION_KINDS}


def envelopes(project: Project) -> dict:
    outgoing = {
        c.transition_in.from_clip_id: c.transition_in
        for c in project.clips.values()
        if c.transition_in
    }
    result = {}
    for clip in project.clips.values():
        incoming, tail = clip.transition_in, outgoing.get(clip.id)
        times = {0, clip.duration_ticks}
        if incoming:
            times.update((incoming.duration_ticks / 2, incoming.duration_ticks))
        if tail:
            times.update(
                (
                    clip.duration_ticks - tail.duration_ticks,
                    clip.duration_ticks - tail.duration_ticks / 2,
                )
            )

        def progress(at, window, from_start):
            """How far the transition has run, 0 at its first frame and 1 at its last."""
            if from_start:
                return max(0.0, min(1.0, at / window))
            return max(0.0, min(1.0, (at - clip.duration_ticks + window) / window))

        def weight(at, picture):
            value = 1.0
            if incoming:
                p = progress(at, incoming.duration_ticks, True)
                # A wipe reveals space, not light: its scalar picture weight stays whole so the two
                # opaque layers still sum to one, while the audio cross-fades like a dissolve.
                if not (picture and incoming.kind in WHOLE_WEIGHT_KINDS):
                    fade = max(0, 2 * p - 1)
                    value *= fade if picture and incoming.kind in {"dip_black", "dip_white"} else p
            if tail:
                p = progress(at, tail.duration_ticks, False)
                if not (picture and tail.kind in WHOLE_WEIGHT_KINDS):
                    fade = max(0, 1 - 2 * p)
                    value *= fade if picture and tail.kind in {"dip_black", "dip_white"} else 1 - p
            return value

        def scale_at(at):
            if incoming and incoming.kind == "zoom_in":
                return ZOOM_START + (1.0 - ZOOM_START) * progress(at, incoming.duration_ticks, True)
            if tail and tail.kind == "zoom_out":
                return 1.0 + (ZOOM_END - 1.0) * progress(at, tail.duration_ticks, False)
            return 1.0

        def wipe_at(at):
            if incoming and incoming.kind in WIPE_KINDS:
                return incoming.kind, progress(at, incoming.duration_ticks, True), False
            if tail and tail.kind in WIPE_KINDS:
                return tail.kind, progress(at, tail.duration_ticks, False), True
            return None

        def motion_at(at) -> tuple[float, float]:
            """Where this clip's whole layer sits right now, in frame fractions of offset."""
            if incoming and incoming.kind in MOTION_KINDS:
                axis, start, _exit = MOTION_KINDS[incoming.kind]
                value = start * (1.0 - progress(at, incoming.duration_ticks, True))
                return (value, 0.0) if axis == "x" else (0.0, value)
            if tail and tail.kind in MOTION_KINDS:
                axis, _start, exit_to = MOTION_KINDS[tail.kind]
                value = exit_to * progress(at, tail.duration_ticks, False)
                return (value, 0.0) if axis == "x" else (0.0, value)
            return (0.0, 0.0)

        curves = {}
        for name in ("picture", "sound"):
            curves[name] = [
                {
                    "offset": t / clip.duration_ticks,
                    "value": weight(t, name == "picture"),
                    "easing": "linear",
                }
                for t in sorted(times)
            ]
        curves["black"] = [
            {
                "offset": t / clip.duration_ticks,
                "value": max(0, 1 - abs(2 * t / incoming.duration_ticks - 1))
                if incoming and incoming.kind == "dip_black"
                else 0.0,
                "easing": "linear",
            }
            for t in sorted(times)
        ]
        curves["white"] = [
            {
                "offset": t / clip.duration_ticks,
                "value": max(0, 1 - abs(2 * t / incoming.duration_ticks - 1))
                if incoming and incoming.kind == "dip_white"
                else 0.0,
                "easing": "linear",
            }
            for t in sorted(times)
        ]
        curves["scale"] = [
            {"offset": t / clip.duration_ticks, "value": scale_at(t), "easing": "linear"}
            for t in sorted(times)
        ]
        # One point list per axis, because that is the shape both consumers already move in: the
        # exporter adds each into its `overlay=x:`/`y:` term, and the browser animates its two
        # nested translate wrappers with the same numbers.
        for axis in ("x", "y"):
            curves[f"motion_{axis}"] = [
                {
                    "offset": t / clip.duration_ticks,
                    "value": motion_at(t)[0 if axis == "x" else 1],
                    "easing": "linear",
                }
                for t in sorted(times)
            ]
        probe = wipe_at(0)
        curves["wipe"] = (
            None
            if probe is None
            else {
                "kind": probe[0],
                "invert": probe[2],
                # The browser needs the same ramp width the exporter divides by, or its edge would
                # sit half a feather away from the exported one. And it needs the axis and the
                # direction, because a second name→direction table in the shell is two authorities.
                "feather": WIPE_FEATHER,
                "axis": WIPE_KINDS[probe[0]][0],
                "flipped": WIPE_KINDS[probe[0]][1],
                "curve": [
                    {"offset": t / clip.duration_ticks, "value": wipe_at(t)[1], "easing": "linear"}
                    for t in sorted(times)
                ],
            }
        )
        result[clip.id] = curves
    return result


def curve_expression(curve: list[dict], duration_ticks: int, clock: str = "t") -> str:
    result = str(curve[-1]["value"])
    for left, right in reversed(list(zip(curve, curve[1:]))):
        a = left["offset"] * duration_ticks / TIMEBASE
        b = right["offset"] * duration_ticks / TIMEBASE
        value = str(left["value"])
        if right["value"] != left["value"]:
            value = f"({value}+({right['value'] - left['value']})*({clock}-{a:.12f})/{b - a:.12f})"
        result = f"if(lt({clock},{b:.12f}),{value},{result})"
    return f"if(lt({clock},0),{curve[0]['value']},{result})"


def wipe_expression(kind: str, invert: bool, progress: str) -> str:
    """Alpha of one side of a wipe, as a `geq` expression in the frame's own X/Y and the clip clock.

    `progress` is the compiled 0..1 ramp for the transition window. The revealed edge travels along
    one axis over `1 + WIPE_FEATHER` of the frame so it reaches the far border exactly when the
    window ends; the outgoing layer is handed the complement, which keeps the two
    opaque layers summing to one everywhere instead of double-counting the overlap.
    """
    axis, flipped = WIPE_KINDS[kind]
    position = "X/W" if axis == "x" else "Y/H"
    if flipped:
        position = f"(1-({position}))"
    edge = f"({progress})*{1.0 + WIPE_FEATHER:.6f}"
    reveal = f"clip((({edge})-({position}))/{WIPE_FEATHER},0,1)"
    return f"(1-({reveal}))" if invert else reveal
