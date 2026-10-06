"""Server-issued scalar envelopes for premultiplied picture and linear sound blends."""

from .contracts import TIMEBASE, Project


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

        def weight(at, picture):
            value = 1.0
            if incoming:
                p = max(0, min(1, at / incoming.duration_ticks))
                fade = max(0, 2 * p - 1)
                value *= fade if picture and incoming.kind in {"dip_black", "dip_white"} else p
            if tail:
                p = max(
                    0,
                    min(1, (at - clip.duration_ticks + tail.duration_ticks) / tail.duration_ticks),
                )
                fade = max(0, 1 - 2 * p)
                value *= fade if picture and tail.kind in {"dip_black", "dip_white"} else 1 - p
            return value

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
