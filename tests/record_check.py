"""The stabilisation record has to stay a true statement, whatever command touches the clip.

1.69 gave a stabilised clip a record, and 1.70/1.71/1.73 made that record load-bearing: it is what
lets a re-press replace instead of stack, what refuses a speed change and a reframe, and what the
Inspector prints as 「已稳定 · 强度 …」. A claim that can go stale is worse than no claim, so this
check walks the contract's clip commands over one fixture and asserts three things every time: the
command answers with a named outcome (never an escaping validation error), the record survives only
while the curves it describes exist, and the refusals fire wherever those curves live -- including
inside a nested composition, where the clip is reached through a sequence view.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcut import reframe as reframe_plan  # noqa: E402
from agentcut.animation import sample  # noqa: E402
from agentcut.contracts import (  # noqa: E402
    TIMEBASE,
    Asset,
    Clip,
    EditBatch,
    Project,
    SequenceSettings,
    Stabilization,
    Track,
)
from agentcut.projects import EditorError  # noqa: E402
from agentcut.timeline import apply_commands, validate_timeline  # noqa: E402

T = TIMEBASE
FRAME = T // 30


def record() -> Stabilization:
    return Stabilization(
        strength=1.0,
        max_crop=0.1,
        points=2,
        translation_correction=0.02,
        roll_correction=0.0,
        zoom_to_hide_borders=1.04,
        analysed_frames=60,
    )


def base() -> Project:
    """One clip carrying a stabiliser's curves and the record that describes them."""
    clip = Clip(
        id="c",
        asset_id="a",
        track_id="v",
        position_ticks=0,
        duration_ticks=60 * FRAME,
        keyframes=[
            {"property": "x", "at_ticks": 0, "value": 0.01, "interpolation": "linear"},
            {"property": "x", "at_ticks": 30 * FRAME, "value": -0.01, "interpolation": "linear"},
            {"property": "y", "at_ticks": 0, "value": 0.02, "interpolation": "linear"},
            {"property": "y", "at_ticks": 30 * FRAME, "value": -0.02, "interpolation": "linear"},
            {"property": "scale", "at_ticks": 0, "value": 1.04, "interpolation": "linear"},
            {"property": "scale", "at_ticks": 59 * FRAME, "value": 1.04, "interpolation": "linear"},
        ],
        stabilization=record(),
        mask={
            "shape": "ellipse",
            "center_x": 0.5,
            "center_y": 0.5,
            "width": 0.2,
            "height": 0.3,
            "feather": 0.0,
            "inverted": False,
        },
    )
    project = Project(
        id="p",
        name="record",
        revision=0,
        settings=SequenceSettings(
            width=640, height=360, frame_rate={"numerator": 30, "denominator": 1}
        ),
        tracks=[Track(id="v", kind="video", name="v")],
        assets={
            "a": Asset(id="a", kind="video", label="a", reference="x", duration_ticks=120 * FRAME)
        },
        clips={"c": clip},
        sequences={},
    )
    validate_timeline(project)
    return project


def run(project: Project, commands: list, sequence_id: str | None = None) -> Project:
    """Apply a batch and return the result, or raise the EditorError the reducer chose."""
    batch = EditBatch(
        request_id="case",
        expected_revision=project.revision,
        commands=commands,
        sequence_id=sequence_id,
    )
    after = apply_commands(project, batch.commands, batch.sequence_id)
    validate_timeline(after)
    return after


def transform_curves(clip: Clip) -> set[str]:
    return {key.property for key in clip.keyframes} & {"x", "y", "rotation", "scale"}


def survives() -> None:
    """Ordinary edits keep both the curves and the claim about them."""
    cases = {
        "move": [
            {"op": "clip.move", "clip_id": "c", "track_id": "v", "position_ticks": 10 * FRAME}
        ],
        "slip": [{"op": "clip.slip", "clip_id": "c", "source_offset_ticks": 2 * FRAME}],
        "trim head": [
            {
                "op": "clip.trim",
                "clip_id": "c",
                "source_in_ticks": 10 * FRAME,
                "duration_ticks": 40 * FRAME,
            }
        ],
        "effects": [{"op": "clip.effects", "clip_id": "c", "effects": {"opacity": 0.9}}],
        "patch": [{"op": "clip.patch", "clip_id": "c", "effects": {"opacity": 0.8}}],
        "fade": [
            {"op": "clip.fade", "clip_id": "c", "property": "opacity", "duration_ticks": FRAME}
        ],
        "hand key": [
            {
                "op": "keyframe.set",
                "clip_id": "c",
                "keyframe": {"property": "x", "at_ticks": 10 * FRAME, "value": 0.3},
            }
        ],
        "mask curve": [
            {
                "op": "keyframe.set",
                "clip_id": "c",
                "keyframe": {"property": "mask_x", "at_ticks": 5 * FRAME, "value": 0.4},
            }
        ],
    }
    for label, commands in cases.items():
        after = run(base(), commands)
        clip = after.clips["c"]
        assert clip.stabilization is not None, f"{label} dropped a record that still stands"
        assert transform_curves(clip), f"{label} deleted the curves without dropping the record"
    print(f"   survives: {len(cases)} clip commands keep both the curves and the record")


def refused() -> None:
    """The things a correction cannot survive are refused by name, head untouched."""
    for label, commands in {
        "clip.speed 200": [{"op": "clip.speed", "clip_id": "c", "speed_percent": 200}],
        "clip.speed 50": [{"op": "clip.speed", "clip_id": "c", "speed_percent": 50}],
        "clip.speed_curve": [
            {
                "op": "clip.speed_curve",
                "clip_id": "c",
                "points": [
                    {"at_ticks": 0, "percent": 100},
                    {"at_ticks": 30 * FRAME, "percent": 150},
                ],
            }
        ],
    }.items():
        try:
            run(base(), commands)
        except EditorError as error:
            assert error.code == "STABILIZE_LOCKED", f"{label} refused as {error.code}"
            continue
        raise AssertionError(f"{label} was accepted over a stabilisation record")
    # 主体跟随重构图 writes the same three curves the correction lives in, and it is a planner, so
    # the lock has to fire before it returns any commands at all -- a plan that got as far as
    # `keyframes.replace` would be applied by whoever asked for it.
    try:
        reframe_plan.plan(base(), clip_id="c", max_scale=1.5)
    except EditorError as error:
        assert error.code == "STABILIZE_LOCKED", f"clip.reframe refused as {error.code}"
    else:
        raise AssertionError("a reframe plan was written over a stabilisation record")
    # 100% is not a change, and refusing it would lock the speed field for no reason.
    same = run(base(), [{"op": "clip.speed", "clip_id": "c", "speed_percent": 100}])
    assert same.clips["c"].stabilization is not None
    print(
        "   refused: a rate change, a ramp and a reframe plan all answer STABILIZE_LOCKED; 100% "
        "passes"
    )


def dies_with_its_curves() -> None:
    """Wipe the four curves and the claim has to go; wipe something else and it must not."""
    project = base()
    wiped = run(
        project,
        [
            {
                "op": "keyframes.remove",
                "clip_id": "c",
                "keyframes": [
                    {"property": "x", "at_ticks": 0},
                    {"property": "x", "at_ticks": 30 * FRAME},
                    {"property": "y", "at_ticks": 0},
                    {"property": "y", "at_ticks": 30 * FRAME},
                    {"property": "scale", "at_ticks": 0},
                    {"property": "scale", "at_ticks": 59 * FRAME},
                ],
            }
        ],
    ).clips["c"]
    assert wiped.keyframes == [], wiped.keyframes
    assert wiped.stabilization is None, "the record outlived every curve it described"
    # With nothing left to steady, the locks have to be gone too.
    quiet = base()
    quiet.clips["c"] = wiped
    sped = run(
        quiet,
        [{"op": "clip.speed", "clip_id": "c", "speed_percent": 200, "ripple": False}],
    )
    assert sped.clips["c"].speed_percent == 200, "a dead record still locked the speed"
    # The reframe lock has to lift with it. It now refuses for its own reason (no animated mask
    # centre in this fixture) rather than on behalf of a correction that is no longer there.
    try:
        reframe_plan.plan(quiet, clip_id="c", max_scale=1.5)
    except EditorError as error:
        assert error.code == "INVALID_REFRAME", f"the dead record still refused as {error.code}"
    else:
        raise AssertionError("a reframe was planned with no mask path to follow")
    partial = run(
        project,
        [
            {
                "op": "keyframes.remove",
                "clip_id": "c",
                "keyframes": [{"property": "x", "at_ticks": 0}],
            }
        ],
    ).clips["c"]
    assert partial.stabilization is not None, "removing one point dropped a standing claim"
    cleared = run(project, [{"op": "clip.stabilize_record", "clip_id": "c", "record": None}]).clips[
        "c"
    ]
    assert cleared.stabilization is None, "the explicit clear did not clear"
    assert transform_curves(cleared), "clearing the record deleted the curves as well"
    print(
        "   dies with its curves: wiping all four drops the record and both locks, one point does "
        "not, and an explicit clear leaves the curves alone"
    )


def travels() -> None:
    """Split halves and nested compositions reach the same guard as the clip it started as."""
    project = base()
    halves = run(
        project,
        [{"op": "clip.split", "clip_id": "c", "at_ticks": 30 * FRAME, "right_clip_id": "r"}],
    )
    for clip_id in ("c", "r"):
        clip = halves.clips[clip_id]
        assert clip.stabilization is not None, f"{clip_id} lost the record at the cut"
        assert transform_curves(clip), f"{clip_id} has no correction left to claim"
    # The right half reads the tail of the same animation clock, so its local frame 0 is the point
    # that used to sit at 30 frames: the cut advances the offset and leaves the curve in place, and
    # a stabiliser's correction has to stay in phase with the media it was measured against.
    whole = project.clips["c"]
    left, right = halves.clips["c"], halves.clips["r"]
    assert right.animation_offset_ticks == whole.animation_offset_ticks + 30 * FRAME
    assert left.animation_offset_ticks == whole.animation_offset_ticks
    for local in range(0, 30 * FRAME + 1, 6 * FRAME):
        for prop in ("x", "y", "scale"):
            after = sample(right, prop, local)
            before = sample(whole, prop, local + 30 * FRAME)
            assert abs(after - before) < 1e-9, (prop, local, before, after)
            assert abs(sample(left, prop, local) - sample(whole, prop, local)) < 1e-9
    nested = run(
        project,
        [
            {
                "op": "sequence.nest",
                "clip_ids": ["c"],
                "name": "竖屏",
                "sequence_id": "s1",
                "asset_id": "seq",
                "clip_id": "cn",
            }
        ],
    )
    inside = nested.sequences["s1"].clips["c"]
    assert inside.stabilization is not None, "nesting dropped the record"
    try:
        run(nested, [{"op": "clip.speed", "clip_id": "c", "speed_percent": 200}], sequence_id="s1")
    except EditorError as error:
        assert error.code == "STABILIZE_LOCKED", f"inside a comp it refused as {error.code}"
    else:
        raise AssertionError("a clip inside a composition escaped the speed lock")
    print(
        "   travels: both split halves keep the record and sample the same correction the whole "
        "clip had at that frame, and a clip inside a nested composition answers the same refusal"
    )


def main() -> None:
    survives()
    refused()
    dies_with_its_curves()
    travels()
    print(
        "PASS: the stabilisation record is a true statement under every command probed -- it "
        "survives ordinary edits, refuses rate changes, ramps and reframes by name, dies together "
        "with its curves and lifts their locks, survives a cut in phase with the media, and the "
        "same guard reaches a clip inside a nested composition"
    )


if __name__ == "__main__":
    main()
