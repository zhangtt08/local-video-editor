"""No payload a person or an Agent can put on the wire may come back as an internal error.

The engine publishes 53 command shapes. Every one of them is probed three ways against a real HTTP
server and a project that already holds tracks, clips, a transition, a mask, keyframes, a marker, a
recipe and a nested sequence: the bare discriminator (the contract must refuse it), a payload whose
every required field is filled with a **type-correct value that names nothing real** (that reaches
    the
reducer, which is where an unguarded `KeyError`, a raw pydantic error or an integer overflow would
surface), and the same payload with each integer field pushed to `MAX_TICKS` (the classic
position-plus-duration overflow). Then a table of semantic traps that only bite against real state.

The property asserted is narrow and absolute: **status below 500**, and every refusal carries a code
and a message a person can act on. Accepted probes must actually be accepted too -- a run that
ends up rejecting everything would prove nothing, so the check also fails if fewer than eight
distinct error codes appear, or if a dry-run disagrees with the same command committed for real.
"""

import os
import tempfile
import typing
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import MAX_TICKS, Command
from agentcut.http_api import create_app

# AGENTCUT_MATRIX_REPORT=1 prints what each trap actually answers instead of asserting it. It exists
# for the day the contract moves; the gate itself runs with it unset.
REPORT = os.environ.get("AGENTCUT_MATRIX_REPORT") == "1"

T = 70_560_000
WIDTH, HEIGHT = 320, 180
BANNED = (500, 502, 503, 504)


def command_models() -> list[type]:
    union = typing.get_args(Command)[0]
    return [member for member in typing.get_args(union) if hasattr(member, "model_fields")]


def unwrap(annotation):
    """Strip Annotated[...] so `Ticks` reads as the int it is."""
    while typing.get_origin(annotation) is not None and hasattr(annotation, "__metadata__"):
        annotation = typing.get_args(annotation)[0]
    return annotation


def sample(annotation, depth: int = 0):
    """A value of the right type that refers to nothing in the project."""
    annotation = unwrap(annotation)
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is typing.Literal:
        return args[0]
    if origin in (list, set, tuple):
        return [sample(args[0], depth)] if args else []
    if origin is dict:
        return {}
    if origin is typing.Union or origin is not None:  # unions, including `X | None`
        for candidate in args:
            if candidate is not type(None):
                return sample(candidate, depth)
        return None
    if hasattr(annotation, "model_fields"):
        return minimal(annotation, depth)
    name = getattr(annotation, "__name__", str(annotation))
    if name == "bool":
        return True
    if name == "float":
        return 0.5
    if name == "int":
        return 1_000
    if name == "FrameRate":
        return {"numerator": 30, "denominator": 1}
    return "nope"


def minimal(model, depth: int = 0) -> dict:
    """Fill only what the contract demands, so the payload is legal-shaped but points at nothing."""
    if depth > 3:
        return {}
    payload = {}
    for field_name, field in model.model_fields.items():
        if not field.is_required() or field_name == "op":
            continue
        value = sample(field.annotation, depth + 1)
        if isinstance(value, list) and field_name.endswith("ids"):
            value = ["nope"]
        payload[field_name] = value
    return payload


def integer_fields(model) -> list[str]:
    fields = []
    for name, field in model.model_fields.items():
        if getattr(unwrap(field.annotation), "__name__", "") == "int":
            fields.append(name)
    return fields


def seed_commands() -> list[dict]:
    return [
        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
        {"op": "track.add", "track": {"id": "v2", "kind": "video", "name": "v2"}},
        {"op": "track.add", "track": {"id": "v3", "kind": "video", "name": "v3"}},
        {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "a"}},
        {
            "op": "asset.register",
            "asset": {
                "id": "pic",
                "kind": "video",
                "label": "p",
                "reference": "r",
                "duration_ticks": 4 * T,
            },
        },
        {
            "op": "asset.register",
            "asset": {
                "id": "snd",
                "kind": "audio",
                "label": "s",
                "reference": "r",
                "duration_ticks": 4 * T,
            },
        },
        {
            "op": "asset.register",
            "asset": {
                "id": "txt",
                "kind": "text",
                "label": "t",
                "reference": "r",
                "duration_ticks": T,
            },
        },
        {
            "op": "clip.add",
            "clip": {
                "id": "c1",
                "asset_id": "pic",
                "track_id": "v",
                "position_ticks": 0,
                "duration_ticks": 2 * T,
            },
        },
        {
            "op": "clip.add",
            "clip": {
                "id": "c2",
                "asset_id": "pic",
                "track_id": "v",
                "position_ticks": 2 * T,
                "duration_ticks": 2 * T,
            },
        },
        {
            "op": "clip.add",
            "clip": {
                "id": "c3",
                "asset_id": "pic",
                "track_id": "v2",
                "position_ticks": 0,
                "duration_ticks": T,
            },
        },
        {
            "op": "clip.add",
            "clip": {
                "id": "s1",
                "asset_id": "snd",
                "track_id": "a",
                "position_ticks": 0,
                "duration_ticks": 2 * T,
            },
        },
        {
            "op": "clip.add",
            "clip": {
                "id": "t1",
                "asset_id": "txt",
                "track_id": "v2",
                "position_ticks": T,
                "duration_ticks": T,
                "text": {"body": "标题", "font_size": 0.1, "color": "#ffffff"},
            },
        },
        {
            "op": "clip.add",
            "clip": {
                "id": "c4",
                "asset_id": "pic",
                "track_id": "v3",
                "position_ticks": 0,
                "duration_ticks": T,
            },
        },
        {
            "op": "clip.mask",
            "clip_id": "c1",
            "mask": {
                "shape": "ellipse",
                "center_x": 0.5,
                "center_y": 0.5,
                "width": 0.4,
                "height": 0.4,
                "feather": 0.1,
                "inverted": False,
            },
        },
        {
            "op": "keyframe.set",
            "clip_id": "c1",
            "keyframe": {"property": "x", "at_ticks": T // 2, "value": 0.1},
        },
        {"op": "marker.set", "marker": {"id": "m", "at_ticks": T, "name": "hit"}},
        {
            "op": "transition.set",
            "clip_id": "c2",
            "from_clip_id": "c1",
            "kind": "dissolve",
            "duration_ticks": T // 3,
        },
        {
            "op": "recipe.set",
            "recipe": {
                "id": "r1",
                "name": "交付",
                "items": [{"preset_id": "h264-1080p", "filename": "a.mp4"}],
            },
        },
        {
            "op": "sequence.nest",
            "clip_ids": ["c3", "t1"],
            "name": "n1",
            "sequence_id": "n1",
            "asset_id": "an1",
            "clip_id": "cn1",
        },
        {"op": "track.update", "track_id": "v3", "locked": True},
    ]


def traps(revision: int) -> list[tuple[str, dict, int, str | None]]:
    """(label, command, expected status, expected code) for cases that only bite against real state.

    The codes are pinned because they are the contract a person or an Agent plans against, and two
    of the rows pin the *opposite* of what they look like: nesting a clip that is itself a nested
    picture is legal (depth 2, not a cycle), and `captions.import` creates the track it names rather
    than requiring one to exist. Both were measured, not assumed.
    """
    return [
        # The stabiliser's record (1.69) is a command like any other, so it is probed the same way:
        # a payload that names nothing real must reach the reducer and answer by name, never as a
        # 500, and clearing a record that was never there must be an accepted no-op.
        (
            "stabilize record on a clip that is not there",
            {
                "op": "clip.stabilize_record",
                "clip_id": "nope",
                "record": {
                    "strength": 1.0,
                    "max_crop": 0.1,
                    "points": 12,
                    "translation_correction": 0.02,
                    "roll_correction": 0.0,
                    "zoom_to_hide_borders": 1.04,
                    "analysed_frames": 12,
                },
            },
            404,
            "NOT_FOUND",
        ),
        (
            "stabilize record with no points",
            {
                "op": "clip.stabilize_record",
                "clip_id": "c1",
                "record": {
                    "strength": 1.0,
                    "max_crop": 0.1,
                    "points": 0,
                    "translation_correction": 0.0,
                    "roll_correction": 0.0,
                    "zoom_to_hide_borders": 1.0,
                    "analysed_frames": 0,
                },
            },
            422,
            "INVALID_REQUEST",
        ),
        (
            "clear a record that was never written",
            {"op": "clip.stabilize_record", "clip_id": "c1", "record": None},
            200,
            None,
        ),
        (
            "nest a nested picture again",
            {
                "op": "sequence.nest",
                "clip_ids": ["cn1"],
                "name": "n2",
                "sequence_id": "n2",
                "asset_id": "an2",
                "clip_id": "cn2",
            },
            200,
            None,
        ),
        (
            "mask on an audio clip",
            {
                "op": "clip.mask",
                "clip_id": "s1",
                "mask": {
                    "shape": "ellipse",
                    "center_x": 0.5,
                    "center_y": 0.5,
                    "width": 0.4,
                    "height": 0.4,
                    "feather": 0.0,
                    "inverted": False,
                },
            },
            422,
            "INVALID_MASK",
        ),
        (
            "grade on an audio clip",
            {"op": "clip.grade", "clip_id": "s1", "grade": []},
            422,
            "INVALID_COLOR",
        ),
        (
            "text style on a video clip",
            {
                "op": "clip.text",
                "clip_id": "c1",
                "text": {"body": "hi", "font_size": 0.1, "color": "#ffffff"},
            },
            422,
            "INVALID_TEXT",
        ),
        (
            "transition longer than the clips",
            {
                "op": "transition.set",
                "clip_id": "c2",
                "from_clip_id": "c1",
                "kind": "dissolve",
                "duration_ticks": 4 * T,
            },
            422,
            "INVALID_TRANSITION",
        ),
        (
            "overlap without a transition",
            {
                "op": "clip.add",
                "clip": {
                    "id": "c9",
                    "asset_id": "pic",
                    "track_id": "v",
                    "position_ticks": T,
                    "duration_ticks": T,
                },
            },
            422,
            "CLIP_OVERLAP",
        ),
        (
            "keyframe on a missing clip",
            {
                "op": "keyframe.set",
                "clip_id": "ghost",
                "keyframe": {"property": "x", "at_ticks": T, "value": 0.5},
            },
            404,
            "NOT_FOUND",
        ),
        (
            "marker past the content",
            {"op": "marker.set", "marker": {"id": "m9", "at_ticks": 99 * T, "name": "late"}},
            422,
            "INVALID_MARKER",
        ),
        (
            "remove a missing recipe",
            {"op": "recipe.remove", "recipe_id": "ghost"},
            404,
            "NOT_FOUND",
        ),
        (
            "remove a missing marker",
            {"op": "marker.remove", "marker_id": "ghost"},
            404,
            "NOT_FOUND",
        ),
        (
            "split inside a transition",
            {"op": "clip.split", "clip_id": "c1", "at_ticks": 2 * T, "right_clip_id": "csplit"},
            422,
            "INVALID_SPLIT",
        ),
        (
            "ripple the last clip of a locked track",
            {"op": "clip.ripple_remove", "clip_id": "c4"},
            422,
            "TRACK_LOCKED",
        ),
        (
            "roll across tracks",
            {"op": "clip.roll", "clip_id": "c1", "other_clip_id": "s1", "delta_ticks": T},
            422,
            "INVALID_ROLL",
        ),
        (
            "captions import creates the track it names",
            {
                "op": "captions.import",
                "track_id": "subs",
                "asset_id": "subs",
                "srt": "1\n00:00:00,000 --> 00:00:01,000\n你好\n",
            },
            200,
            None,
        ),
        (
            "mask track on an ellipse",
            {
                "op": "clip.mask_track",
                "clip_id": "c1",
                "points": [{"at_ticks": 0, "center_x": 0.5, "center_y": 0.5}],
            },
            422,
            "INVALID_REQUEST",
        ),
        (
            "clip.add at MAX_TICKS",
            {
                "op": "clip.add",
                "clip": {
                    "id": "cmax",
                    "asset_id": "pic",
                    "track_id": "v",
                    "position_ticks": MAX_TICKS,
                    "duration_ticks": T,
                },
            },
            422,
            "TIME_OVERFLOW",
        ),
        (
            "slip past the source",
            {"op": "clip.slip", "clip_id": "c1", "source_offset_ticks": 9 * T},
            422,
            "SOURCE_OUT_OF_BOUNDS",
        ),
        (
            "detach an unlinked pair",
            {"op": "clip.detach_audio", "clip_id": "c1", "audio_clip_id": "s1", "track_id": "a"},
            422,
            "NO_EMBEDDED_AUDIO",
        ),
        (
            "link two picture clips",
            {"op": "clips.link", "clip_ids": ["c1", "c2"]},
            422,
            "INVALID_REQUEST",
        ),
    ]


def main() -> None:
    models = command_models()
    assert len(models) >= 45, len(models)
    with tempfile.TemporaryDirectory(prefix="agentcut-matrix-") as scratch:
        folder = Path(scratch)
        token = "matrix-" + "f" * 48
        with TestClient(
            create_app(folder / "db.sqlite3", token),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            project = client.post(
                "/v1/projects", json={"request_id": "new", "name": "matrix"}
            ).json()["project"]
            path = f"/v1/projects/{project['id']}"
            revision = 0
            for position, command in enumerate(seed_commands()):
                seeded = client.post(
                    path + "/edits",
                    json={
                        "request_id": f"seed-{position}",
                        "expected_revision": revision,
                        "commands": [command],
                    },
                )
                assert seeded.status_code == 200, (command["op"], seeded.text[:400])
                revision = seeded.json()["project"]["revision"]
            head = revision

            def send(request_id, command, *, revision=None, dry=True):
                return client.post(
                    path + "/edits",
                    json={
                        "request_id": request_id,
                        "expected_revision": revision if revision is not None else head,
                        "commands": [command],
                        "dry_run": dry,
                    },
                )

            codes: set[str] = set()
            accepted: list[str] = []
            probed = 0
            for model in [] if REPORT else models:
                tag = typing.get_args(unwrap(model.model_fields["op"].annotation))[0]
                for label, command in (
                    ("bare", {"op": tag}),
                    ("unknown ids", {"op": tag, **minimal(model)}),
                    *(
                        (f"max {field}", {"op": tag, **minimal(model), field: MAX_TICKS})
                        for field in integer_fields(model)
                    ),
                ):
                    probed += 1
                    answer = send(f"{tag}-{label.replace(' ', '-')}", command)
                    assert answer.status_code not in BANNED, (
                        f"{tag} / {label} -> {answer.status_code}: {answer.text[:400]}"
                    )
                    if answer.status_code >= 400:
                        error = answer.json()["error"]
                        assert error["code"] and error["message"], (tag, label, error)
                        assert "details" in error, (tag, label, error)
                        codes.add(error["code"])
                    else:
                        accepted.append(f"{tag}/{label}")
                    assert client.get(path).json()["revision"] == head, (
                        f"{tag} / {label} wrote state through a dry run"
                    )

            for index, (label, command, expected, expected_code) in enumerate(traps(head)):
                probed += 1
                answer = send(f"trap-{index}", command)
                actual = answer.status_code
                error = answer.json().get("error") or {}
                code = error.get("code") if actual >= 400 else None
                if REPORT:
                    print(
                        f"   trap {label!r}: {actual} {code} (expected {expected} {expected_code})"
                    )
                    continue
                assert actual not in BANNED, f"{label} -> {actual}: {answer.text[:300]}"
                assert (actual, code) == (expected, expected_code), (
                    label,
                    actual,
                    code,
                    answer.text[:300],
                )
                if actual >= 400:
                    assert error["message"], error
                    codes.add(code)

            # A dry run must not be a different engine: the same command, committed, agrees.
            committed = 0
            for index, (label, command, expected, expected_code) in enumerate(
                [] if REPORT else traps(head)
            ):
                if expected != 422:
                    continue
                answer = send(f"commit-{index}", command, dry=False)
                assert answer.status_code == expected, (
                    label,
                    answer.status_code,
                    answer.text[:200],
                )
                assert answer.json()["error"]["code"] == expected_code, (label, answer.json())
                committed += 1
                assert client.get(path).json()["revision"] == head, f"{label} committed a refusal"

            good = send(
                "real-good",
                {"op": "marker.set", "marker": {"id": "m2", "at_ticks": T // 2, "name": "ok"}},
                dry=False,
            )
            assert good.status_code == 200, good.text
            assert good.json()["project"]["revision"] == head + 1

            if REPORT:
                return
            # A probe that the contract itself refuses (INVALID_REQUEST) never reached the reducer.
            # Counting the other codes is what proves this sweep exercises the editing rules at all.
            reducer_codes = codes - {"INVALID_REQUEST"}
            assert len(reducer_codes) >= 10, sorted(reducer_codes)
            print(
                f"   {probed} probes over {len(models)} command shapes: {len(accepted)} legal, "
                f"{len(codes) - len(reducer_codes)} refused by the contract, {len(reducer_codes)} "
                f"refused by the editing rules ({', '.join(sorted(reducer_codes)[:9])}…)"
            )
            print(
                f"   no 5xx anywhere; {committed} refusals behaved identically committed and dry, "
                f"and a legal write still lands (revision {head} -> {head + 1})"
            )
    print(
        "PASS: every command shape answers with a code a person can act on -- never an internal "
        "error, never a silent write, dry run and commit agreeing"
    )


if __name__ == "__main__":
    main()
