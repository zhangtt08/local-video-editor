"""What the 30→25 fps paste conformer emits is accepted by the reducer, and the raw cut is not.

The conversion itself lives in `desktop/src/rateConform.ts`; `desktop_rateconform_check.ts` pins the
rule (shared cuts rounded once, linked pairs on the picture grid, keys outside the new duration
dropped). This check is the other end of the same seam: the exact geometry that rule produced —
6 + 7 target frames, a 1-frame dissolve, a linked sound pair and an unlinked 15-source-frame
music bed — goes through the real project store, and the untouched 7 + 8 source frames are put in
right beside it as the control that must still be refused by name.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agentcut.contracts import TIMEBASE as T  # noqa: E402
from agentcut.contracts import CreateProject, EditBatch  # noqa: E402
from agentcut.projects import ProjectStore  # noqa: E402

F30 = T // 30
F25 = T // 25
S48 = T // 48_000


def create(store: ProjectStore, name: str) -> str:
    return store.create(
        CreateProject(
            request_id=f"new-{name}", name=name,
            settings={"frame_rate": {"numerator": 25, "denominator": 1}},
        )
    ).project.id


def seed(store: ProjectStore, project_id: str, conformed: bool, request: str) -> dict:
    a_duration = 6 * F25 if conformed else 7 * F30
    b_position = 5 * F25 if conformed else 6 * F30
    b_duration = 7 * F25 if conformed else 8 * F30
    dissolve = F25 if conformed else F30
    commands = [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "V"}},
        {"op": "track.add", "track": {"id": "s", "kind": "audio", "name": "S"}},
        {"op": "track.add", "track": {"id": "m", "kind": "audio", "name": "M"}},
        {
            "op": "asset.register",
            "asset": {"id": "vid", "kind": "video", "label": "vid", "reference": "untrusted",
                      "duration_ticks": 60 * F30},
        },
        {
            "op": "asset.register",
            "asset": {"id": "aud", "kind": "audio", "label": "aud", "reference": "untrusted",
                      "duration_ticks": 60 * F30},
        },
        {
            "op": "clips.add",
            "clips": [
                {
                    "id": "a", "asset_id": "vid", "track_id": "v",
                    "position_ticks": 0, "source_in_ticks": 0, "duration_ticks": a_duration,
                    "keyframes": [{
                        "property": "x", "at_ticks": 6 * F30, "value": 0.2,
                        "interpolation": "linear",
                    }],
                },
                {
                    "id": "b", "asset_id": "vid", "track_id": "v",
                    "position_ticks": b_position, "source_in_ticks": 0,
                    "duration_ticks": b_duration, "link_id": "pair",
                    "transition_in": {"from_clip_id": "a", "kind": "dissolve",
                                      "duration_ticks": dissolve},
                },
                {
                    "id": "voice", "asset_id": "aud", "track_id": "s",
                    "position_ticks": b_position, "source_in_ticks": 0,
                    "duration_ticks": b_duration, "link_id": "pair",
                },
                {
                    "id": "music", "asset_id": "aud", "track_id": "m",
                    "position_ticks": 0, "source_in_ticks": 0, "duration_ticks": 15 * F30,
                },
            ],
        },
    ]
    return store.mutate(
        project_id,
        EditBatch.model_validate(
            {"request_id": request, "expected_revision": 0, "commands": commands}
        ),
    ).project.model_dump(mode="json")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="crossrate-check-") as name:
        store = ProjectStore(Path(name) / "db.sqlite")
        accepted = create(store, "conformed")
        project = seed(store, accepted, True, "seed")
        clips = project["clips"]
        assert clips["a"]["duration_ticks"] == 6 * F25, clips["a"]
        assert clips["b"]["position_ticks"] == 5 * F25, clips["b"]
        assert clips["b"]["duration_ticks"] == 7 * F25, clips["b"]
        assert clips["b"]["transition_in"]["duration_ticks"] == F25, clips["b"]
        overlap = (
            clips["a"]["position_ticks"] + clips["a"]["duration_ticks"]
            - clips["b"]["position_ticks"]
        )
        assert overlap == F25, "转场叠合区不对"
        assert clips["voice"]["position_ticks"] == clips["b"]["position_ticks"], "链接被切点拆散"
        assert clips["voice"]["duration_ticks"] == clips["b"]["duration_ticks"]
        assert clips["music"]["duration_ticks"] == 15 * F30, "未链接的声音被画面的帧格改了时长"
        assert clips["music"]["duration_ticks"] % S48 == 0
        assert clips["a"]["keyframes"][0]["at_ticks"] == 6 * F30
        print(
            "   accepted: 6 + 7 target frames, 1-frame dissolve, linked pair together, "
            "music still 15 source frames"
        )

        refused = create(store, "raw")
        try:
            seed(store, refused, False, "raw-paste")
            outcome = "accepted"
        # The control must be refused by the reducer, not crash somewhere else in the store.
        except Exception as error:
            outcome = getattr(error, "code", type(error).__name__)
        assert outcome == "TIME_NOT_ALIGNED", f"未换算的 7/8 帧应当被点名拒绝：{outcome}"
        print("   control: the untouched 30 fps cut is refused with TIME_NOT_ALIGNED")
    print(
        "PASS: the geometry the paste conformer emits is accepted by the project store, while the "
        "same cut list left on its source grid is refused by name"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
