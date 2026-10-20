"""Transition edits, legacy receipts, transparent picture blends and real sound ramps."""

import hashlib
import json
import math
import subprocess
import tempfile
from array import array
from pathlib import Path

from agentcut.animation import preview_manifest
from agentcut.contracts import (
    SCHEMA_VERSION,
    TIMEBASE,
    EditBatch,
    EditorError,
    Project,
)
from agentcut.projects import ProjectStore
from agentcut.render import compile_render_plan
from agentcut.timeline import apply_commands, validate_timeline

ROOT = Path(__file__).resolve().parent.parent


def edit(commands):
    return EditBatch.model_validate(
        {"request_id": "edit", "expected_revision": 0, "commands": commands}
    )


def transition(duration=TIMEBASE, kind="dissolve"):
    return {
        "op": "transition.set",
        "clip_id": "right",
        "from_clip_id": "left",
        "kind": kind,
        "duration_ticks": duration,
    }


def project():
    return Project.model_validate(
        {
            "schema_version": 3,
            "id": "p",
            "name": "transitions",
            "tracks": [{"id": "v", "kind": "video", "name": "v"}],
            "assets": {
                "a": {
                    "id": "a",
                    "kind": "video",
                    "label": "a",
                    "reference": "test",
                    "duration_ticks": 4 * TIMEBASE,
                }
            },
            "clips": {
                "left": {
                    "id": "left",
                    "asset_id": "a",
                    "track_id": "v",
                    "position_ticks": 0,
                    "duration_ticks": 2 * TIMEBASE,
                },
                "right": {
                    "id": "right",
                    "asset_id": "a",
                    "track_id": "v",
                    "position_ticks": 2 * TIMEBASE,
                    "duration_ticks": 2 * TIMEBASE,
                },
            },
        }
    )


def main():
    original = project()
    dissolved = apply_commands(original, edit([transition()]).commands)
    assert original.clips["right"].position_ticks == 2 * TIMEBASE
    assert dissolved.clips["right"].position_ticks == TIMEBASE
    assert dissolved.clips["right"].source_in_ticks == 0
    assert dissolved.schema_version == SCHEMA_VERSION
    updated = apply_commands(dissolved, edit([transition(TIMEBASE // 2, "dip_black")]).commands)
    assert updated.clips["right"].position_ticks == 3 * TIMEBASE // 2
    removed = apply_commands(
        updated, edit([{"op": "transition.remove", "clip_id": "right"}]).commands
    )
    assert (
        removed.clips["right"].position_ticks == 2 * TIMEBASE
        and removed.clips["right"].transition_in is None
    )
    manifest = preview_manifest(dissolved)
    assert manifest["mixed_track_ids"] == ["v"]
    assert manifest["clips"]["left"]["transition"]["picture"][-1]["value"] == 0
    assert manifest["clips"]["right"]["transition"]["picture"][0]["value"] == 0
    divided = apply_commands(
        dissolved,
        edit(
            [
                {
                    "op": "clip.split",
                    "clip_id": "left",
                    "at_ticks": TIMEBASE // 2,
                    "right_clip_id": "tail",
                }
            ]
        ).commands,
    )
    assert divided.clips["right"].transition_in.from_clip_id == "tail"
    divided = apply_commands(
        dissolved,
        edit(
            [
                {
                    "op": "clip.split",
                    "clip_id": "right",
                    "at_ticks": 2 * TIMEBASE,
                    "right_clip_id": "tail",
                }
            ]
        ).commands,
    )
    assert divided.clips["tail"].transition_in is None
    rippled = apply_commands(
        dissolved, edit([{"op": "clip.ripple_remove", "clip_id": "left"}]).commands
    )
    assert (
        rippled.clips["right"].position_ticks == 0 and rippled.clips["right"].transition_in is None
    )
    reordered = apply_commands(
        dissolved,
        edit(
            [
                {
                    "op": "clip.move",
                    "clip_id": "left",
                    "track_id": "v",
                    "position_ticks": 3 * TIMEBASE,
                }
            ]
        ).commands,
    )
    assert reordered.clips["right"].transition_in is None
    chain = apply_commands(
        original,
        edit(
            [
                {
                    "op": "clip.add",
                    "clip": {
                        **original.clips["right"].model_dump(),
                        "id": "third",
                        "position_ticks": 4 * TIMEBASE,
                    },
                },
                transition(),
                {
                    "op": "transition.set",
                    "clip_id": "third",
                    "from_clip_id": "right",
                    "duration_ticks": TIMEBASE,
                },
            ]
        ).commands,
    )
    assert chain.clips["third"].position_ticks == 2 * TIMEBASE
    middle_removed = apply_commands(
        chain, edit([{"op": "clip.ripple_remove", "clip_id": "right"}]).commands
    )
    assert middle_removed.clips["third"].position_ticks == 2 * TIMEBASE
    assert middle_removed.clips["third"].transition_in is None
    overwritten = apply_commands(
        dissolved,
        edit(
            [
                {
                    "op": "clip.overwrite",
                    "clip": {
                        **original.clips["left"].model_dump(),
                        "id": "new",
                        "position_ticks": TIMEBASE // 5,
                        "duration_ticks": TIMEBASE // 5,
                    },
                }
            ]
        ).commands,
    )
    assert overwritten.clips["right"].transition_in.from_clip_id != "left"
    assert overwritten.clips["right"].transition_in.from_clip_id in overwritten.clips
    locked = original.model_copy(deep=True)
    locked.tracks[0].locked = True
    for state, commands, code in [
        (chain, [transition(3 * TIMEBASE // 2)], "TRANSITION_EDIT_CONFLICT"),
        (locked, [transition()], "TRACK_LOCKED"),
        (original, [transition(2 * TIMEBASE)], "INVALID_TRANSITION"),
        (original, [transition(TIMEBASE + 1)], "TIME_NOT_ALIGNED"),
        (
            dissolved,
            [
                {
                    "op": "clip.split",
                    "clip_id": "left",
                    "at_ticks": 3 * TIMEBASE // 2,
                    "right_clip_id": "tail",
                }
            ],
            "TRANSITION_EDIT_CONFLICT",
        ),
        (
            dissolved,
            [
                {
                    "op": "clip.overwrite",
                    "clip": {
                        **original.clips["left"].model_dump(),
                        "id": "new",
                        "position_ticks": TIMEBASE,
                    },
                }
            ],
            "TRANSITION_EDIT_CONFLICT",
        ),
    ]:
        try:
            apply_commands(state, edit(commands).commands)
        except EditorError as error:
            assert error.code == code, (code, error)
        else:
            raise AssertionError(code)
    malformed = dissolved.model_copy(deep=True)
    malformed.clips["right"].transition_in.from_clip_id = "missing"
    try:
        validate_timeline(malformed)
    except EditorError as error:
        assert error.code == "INVALID_TRANSITION"
    else:
        raise AssertionError("missing transition reference")
    # v3 insert/overwrite fingerprints included expanded Clip defaults. Preserve them exactly.
    for op in ("clip.insert", "clip.overwrite"):
        request = edit([{"op": op, "clip": original.clips["left"].model_dump()}])
        legacy = request.model_dump(exclude={"dry_run", "sequence_id", "sequence_name"})
        del legacy["commands"][0]["clip"]["transition_in"]
        del legacy["commands"][0]["clip"]["color"]["grade"]
        for field in (
            "group_id",
            "link_id",
            "link_source_offset_ticks",
            "embedded_audio",
            "mask",
            "speed_curve",
            "stabilization",  # 1.69: a clip that never mentions one is older
            "fade",  # 1.90: a clip that never mentions a fade window is older
            "mask_shape_keys",  # 1.118: 没提过轮廓帧的载荷就是 1.118 之前写的
            "extra_masks",  # 1.221: 没提过再叠那几块的载荷就是 1.221 之前写的
            "extra_masks_follow",  # 1.237: 没提过「跟着主遮罩平移」的载荷就是 1.237 之前写的
        ):
            del legacy["commands"][0]["clip"][field]
        old_hash = hashlib.sha256(
            json.dumps(["edit", legacy], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        assert ProjectStore._fingerprint("edit", request) == old_hash
    with tempfile.TemporaryDirectory(prefix="agentcut-transitions-") as folder:
        real_render(Path(folder))
    print("PASS: transitions, editing/locks, v3 receipts, premultiplied pixels and sound ramps")


def real_render(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    ffmpeg = ROOT / "desktop/resources/bin/ffmpeg.exe"
    ffprobe = ROOT / "desktop/resources/bin/ffprobe.exe"

    def run(args):
        return subprocess.run(
            [str(ffmpeg), "-v", "error", "-y", *args],
            capture_output=True,
            check=True,
            timeout=90,
            creationflags=0x08000000,
        ).stdout

    for name, color, frequency in (("red", "red", 440), ("blue", "blue", 880)):
        run(
            [
                "-f",
                "lavfi",
                "-i",
                f"color={color}:s=320x180:r=30:d=2",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:sample_rate=48000:duration=2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(folder / f"{name}.mp4"),
            ]
        )
    run(
        [
            "-f",
            "lavfi",
            "-i",
            "color=0x00ff00:s=320x180",
            "-frames:v",
            "1",
            str(folder / "green.png"),
        ]
    )
    p = project()
    p.settings.width, p.settings.height = 320, 180
    assets = {}
    for name in ("red", "blue", "green"):
        path = folder / (name + (".png" if name == "green" else ".mp4"))
        kind = "image" if name == "green" else "video"
        assets[name] = {
            "id": name,
            "kind": kind,
            "label": name,
            "reference": "test",
            "duration_ticks": None if kind == "image" else 2 * TIMEBASE,
            "verified": {
                "probe_id": name,
                "path": str(path),
                "kind": kind,
                "label": name,
                "size_bytes": path.stat().st_size,
                "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "duration_ticks": 0 if kind == "image" else 2 * TIMEBASE,
                "width": 320,
                "height": 180,
                "has_audio": kind == "video",
            },
        }
    doc = p.model_dump()
    doc["assets"] = assets
    doc["tracks"].insert(0, {"id": "bg", "kind": "video", "name": "background"})
    doc["clips"]["left"]["asset_id"] = "red"
    doc["clips"]["right"]["asset_id"] = "blue"
    doc["clips"]["green"] = {
        "id": "green",
        "asset_id": "green",
        "track_id": "bg",
        "position_ticks": 0,
        "duration_ticks": 3 * TIMEBASE,
    }
    p = Project.model_validate(doc)
    for kind, alpha in (("dissolve", 1.0), ("dissolve", 0.5), ("dip_black", 1.0)):
        state = apply_commands(p, edit([transition(kind=kind)]).commands)
        for clip in (state.clips["left"], state.clips["right"]):
            clip.effects.scale = 0.5
            clip.effects.opacity = alpha
        out = folder / f"{kind}-{alpha}.mp4"
        plan = compile_render_plan(state, "h264-source-quality")
        proc = subprocess.run(
            plan.ffmpeg_argv(str(ffmpeg), str(out)),
            capture_output=True,
            timeout=90,
            creationflags=0x08000000,
        )
        assert proc.returncode == 0, proc.stderr.decode(errors="replace")
        rgb = run(
            [
                "-ss",
                "1.5",
                "-i",
                str(out),
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ]
        )
        center = rgb[(90 * 320 + 160) * 3 : (90 * 320 + 160) * 3 + 3]
        corner = rgb[:3]
        expected = (128, 0, 128) if alpha == 1 else (64, 128, 64)
        if kind == "dip_black":
            expected = (0, 0, 0)
        assert all(abs(v - target) < 12 for v, target in zip(center, expected)), (
            kind,
            alpha,
            center,
            expected,
        )
        assert (
            max(corner) < 12
            if kind == "dip_black"
            else corner[1] > 240 and corner[0] < 12 and corner[2] < 12
        ), (kind, corner)
        meta = json.loads(
            subprocess.check_output(
                [
                    str(ffprobe),
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(out),
                ],
                creationflags=0x08000000,
            )
        )
        assert abs(float(meta["format"]["duration"]) - 3) < 0.05
        pcm = array("h", run(["-i", str(out), "-f", "s16le", "-ac", "1", "-ar", "48000", "pipe:1"]))

        def amplitude(at, freq):
            start = round((at - 0.05) * 48000)
            window = pcm[start : start + 4800]
            real = sum(
                value * math.cos(2 * math.pi * freq * i / 48000) for i, value in enumerate(window)
            )
            imag = sum(
                value * math.sin(2 * math.pi * freq * i / 48000) for i, value in enumerate(window)
            )
            return math.hypot(real, imag) / len(window)

        for freq, baseline in ((440, 0.25), (880, 2.5)):
            ratio = amplitude(1.5, freq) / amplitude(baseline, freq)
            assert 0.38 < ratio < 0.62, (kind, freq, ratio)
    return p


if __name__ == "__main__":
    main()
