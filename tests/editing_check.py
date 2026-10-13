"""Editing acceptance: shared semantics, old receipts, animation continuity and real pixels."""

import hashlib
import json
import subprocess
import tempfile
from array import array
from pathlib import Path

from pydantic import ValidationError

from agentcut.animation import preview_manifest, sample
from agentcut.contracts import (
    MAX_COMMANDS_PER_BATCH,
    TIMEBASE,
    CreateProject,
    EditBatch,
    EditorError,
    Project,
    RenderJob,
    SequenceSettings,
    capabilities,
)
from agentcut.jobs import JobRuntime
from agentcut.projects import ProjectStore
from agentcut.render import compile_render_plan
from agentcut.subtitles import export_srt, parse_srt
from agentcut.timeline import apply_commands

ROOT = Path(__file__).resolve().parent.parent


def batch(commands):
    return EditBatch.model_validate(
        {"request_id": "edit", "expected_revision": 0, "commands": commands}
    ).commands


def batch_cap_suite() -> None:
    """一批能装多少条命令：契约、能力表与界面读的是同一个数，而那个数是量出来的。

    1.126 之前这个数在三处各写了一遍字面量 100（契约的 `max_length`、能力表、界面那句
    「新素材与轨道过多」）——界面挡得不等于引擎挡的，就是那份「怎么填都不行」的来历。
    量过的曲线：250 条 0.05s、1000 条 0.21s、2500 条 0.57s、5000 条 1.32s（写一次并读回整份工程）。
    """
    published = capabilities()["max_commands_per_batch"]
    assert published == MAX_COMMANDS_PER_BATCH, (published, MAX_COMMANDS_PER_BATCH)
    one = {"op": "track.add", "track": {"id": "t", "kind": "audio", "name": "声"}}
    exact = [{**one, "track": {**one["track"], "id": f"t{index}"}} for index in range(published)]
    assert len(batch(exact)) == published, "整批到上限必须收"
    try:
        batch([*exact, one])
    except ValidationError as error:
        located = [item for item in error.errors() if item["loc"] == ("commands",)]
        assert located and str(published) in str(located), (published, located)
    else:
        raise AssertionError("多一条就该被契约拒掉")
    print(f"   批上限：{published} 条，契约与能力表同一个数，到上限收、多一条点名拒")


def main():
    batch_cap_suite()
    project = Project.model_validate(
        {
            "schema_version": 2,
            "id": "p",
            "name": "legacy",
            "tracks": [{"id": "v", "name": "Video", "kind": "video"}],
            "assets": {
                "a": {
                    "id": "a",
                    "kind": "video",
                    "label": "a",
                    "reference": "test",
                    "duration_ticks": 10 * TIMEBASE,
                }
            },
            "clips": {
                "c": {
                    "id": "c",
                    "asset_id": "a",
                    "track_id": "v",
                    "position_ticks": 0,
                    "source_in_ticks": TIMEBASE,
                    "duration_ticks": 4 * TIMEBASE,
                }
            },
        }
    )
    assert project.clips["c"].effects.opacity == 1 and not project.tracks[0].locked
    srt = (
        "1\n00:00:00,000 --> 00:00:01,500\n第一句\n\n"
        "2\n00:00:01,500 --> 00:00:03,000\n<b>第二句</b>\n"
    )
    captions = apply_commands(
        project,
        batch([{"op": "captions.import", "track_id": "subs", "asset_id": "subs", "srt": srt}]),
    )
    assert len([c for c in captions.clips.values() if c.text]) == 2
    assert parse_srt(export_srt(captions, "subs"), project.settings.frame_ticks) == parse_srt(
        srt, project.settings.frame_ticks
    )
    for invalid in (
        srt.replace("第一句", "\x00"),
        srt.replace("00:00:00,000", "9" * 5000 + ":00:00,000"),
        srt.replace("00:00:01,500", "999999:00:00,000"),
    ):
        try:
            parse_srt(invalid, project.settings.frame_ticks)
        except EditorError as error:
            assert error.code in {"INVALID_SUBTITLE", "TIME_OVERFLOW"}
        else:
            raise AssertionError("invalid subtitle escaped boundary validation")
    try:
        apply_commands(
            project,
            batch(
                [
                    {
                        "op": "captions.import",
                        "track_id": "subs",
                        "asset_id": "subs",
                        "srt": srt.replace("00:00:01,500 -->", "00:00:01,000 -->"),
                    }
                ]
            ),
        )
    except EditorError as error:
        assert error.code == "CLIP_OVERLAP" and "subs" not in project.assets
    else:
        raise AssertionError("overlapping subtitle import must roll back")
    fast = apply_commands(
        project, batch([{"op": "clip.speed", "clip_id": "c", "speed_percent": 200}])
    )
    assert fast.clips["c"].duration_ticks == 2 * TIMEBASE
    faded = apply_commands(
        project,
        batch(
            [
                {
                    "op": "clip.fade",
                    "clip_id": "c",
                    "property": "gain",
                    "duration_ticks": TIMEBASE,
                    "mode": "both",
                }
            ]
        ),
    )
    assert sample(faded.clips["c"], "gain", 0) == 0
    assert sample(faded.clips["c"], "gain", TIMEBASE // 2) == 0.5
    assert sample(faded.clips["c"], "gain", 2 * TIMEBASE) == 1
    assert sample(faded.clips["c"], "gain", 4 * TIMEBASE) == 0
    divided = apply_commands(
        fast,
        batch(
            [{"op": "clip.split", "clip_id": "c", "at_ticks": TIMEBASE, "right_clip_id": "right"}]
        ),
    )
    assert divided.clips["right"].source_in_ticks == 3 * TIMEBASE
    animated = apply_commands(
        project,
        batch(
            [
                {
                    "op": "keyframe.set",
                    "clip_id": "c",
                    "keyframe": {"property": "x", "at_ticks": 0, "value": 0.0},
                },
                {
                    "op": "keyframe.set",
                    "clip_id": "c",
                    "keyframe": {"property": "x", "at_ticks": 4 * TIMEBASE, "value": 1.0},
                },
            ]
        ),
    )
    assert sample(animated.clips["c"], "x", 2 * TIMEBASE) == 0.5
    eased = apply_commands(
        animated,
        batch(
            [
                {
                    "op": "keyframe.set",
                    "clip_id": "c",
                    "keyframe": {
                        "property": "x",
                        "at_ticks": 0,
                        "value": 0.0,
                        "interpolation": "ease",
                    },
                }
            ]
        ),
    )
    assert abs(sample(eased.clips["c"], "x", TIMEBASE) - 0.15625) < 1e-12
    assert "cubic-bezier" in preview_manifest(eased)["clips"]["c"]["curves"]["x"][0]["easing"]
    split = apply_commands(
        animated,
        batch(
            [
                {
                    "op": "clip.split",
                    "clip_id": "c",
                    "at_ticks": 2 * TIMEBASE,
                    "right_clip_id": "right",
                }
            ]
        ),
    )
    assert sample(split.clips["right"], "x", TIMEBASE) == sample(
        animated.clips["c"], "x", 3 * TIMEBASE
    )
    trim = apply_commands(
        animated,
        batch(
            [
                {
                    "op": "clip.trim",
                    "clip_id": "c",
                    "position_ticks": TIMEBASE,
                    "source_in_ticks": 2 * TIMEBASE,
                    "duration_ticks": 3 * TIMEBASE,
                }
            ]
        ),
    )
    assert sample(trim.clips["c"], "x", 0) == 0.25 and trim.clips["c"].position_ticks == TIMEBASE
    assert preview_manifest(trim)["clips"]["c"]["curves"]["x"][0]["value"] == 0.25
    locked = apply_commands(
        project, batch([{"op": "track.update", "track_id": "v", "locked": True}])
    )
    for op in (
        {"op": "clip.remove", "clip_id": "c"},
        {"op": "clip.effects", "clip_id": "c", "effects": {"scale": 0.5}},
    ):
        try:
            apply_commands(locked, batch([op]))
        except EditorError as error:
            assert error.code == "TRACK_LOCKED"
        else:
            raise AssertionError("locked track accepted an edit")
    added = apply_commands(
        project,
        batch(
            [
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "tail",
                        "asset_id": "a",
                        "track_id": "v",
                        "position_ticks": 4 * TIMEBASE,
                        "duration_ticks": TIMEBASE,
                    },
                }
            ]
        ),
    )
    ripple = apply_commands(added, batch([{"op": "clip.ripple_remove", "clip_id": "c"}]))
    assert ripple.clips["tail"].position_ticks == 0 and "c" not in ripple.clips
    # Literal old fully-expanded payload, independent of the new model defaults.
    old = {
        "request_id": "old",
        "expected_revision": 0,
        "commands": [
            {
                "op": "track.add",
                "track": {
                    "id": "v",
                    "kind": "video",
                    "name": "v",
                    "muted": False,
                    "hidden": False,
                    "volume": 1.0,
                },
                "index": None,
            },
            {
                "op": "clip.add",
                "clip": {
                    "id": "c",
                    "asset_id": "a",
                    "track_id": "v",
                    "position_ticks": 0,
                    "source_in_ticks": 0,
                    "duration_ticks": TIMEBASE,
                },
            },
            {"op": "clip.trim", "clip_id": "c", "source_in_ticks": 0, "duration_ticks": TIMEBASE},
            {
                "op": "track.update",
                "track_id": "v",
                "name": None,
                "muted": True,
                "hidden": None,
                "volume": None,
            },
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(["edit", old], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert ProjectStore._fingerprint("edit", EditBatch.model_validate(old)) == fingerprint
    with tempfile.TemporaryDirectory(prefix="agentcut-editing-") as folder:
        store = ProjectStore(Path(folder) / "test.sqlite")
        created = store.create(CreateProject(request_id="create", name="test"))
        request = EditBatch.model_validate(
            {
                "request_id": "keys",
                "expected_revision": 0,
                "commands": [
                    {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                    {"op": "asset.register", "asset": project.assets["a"].model_dump()},
                    {"op": "clip.add", "clip": animated.clips["c"].model_dump()},
                ],
            }
        )
        store.mutate(created.project.id, request)
        assert store.mutate(created.project.id, request).replayed
        assert store.get(created.project.id, 0).clips == {}
        real_render(Path(folder))
    print(
        "PASS: animation, split/trim, locks, ripple, old fingerprints, persistence, rendered pixels"
    )


def real_render(folder):
    ffmpeg = ROOT / "desktop/resources/bin/ffmpeg.exe"
    assert ffmpeg.is_file(), "bundled ffmpeg is missing: desktop/resources/bin/ffmpeg.exe"

    def run(args):
        return subprocess.run(
            [str(ffmpeg), "-v", "error", "-y", *args],
            capture_output=True,
            check=True,
            timeout=90,
            creationflags=0x08000000,
        ).stdout

    blue, red = folder / "blue.mp4", folder / "red.png"
    run(
        [
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=320x180:r=30:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(blue),
        ]
    )
    run(["-f", "lavfi", "-i", "color=red:s=320x180", "-frames:v", "1", str(red)])

    def asset(id, path, kind):
        return {
            "id": id,
            "kind": kind,
            "label": id,
            "reference": "test",
            "duration_ticks": None if kind == "image" else 2 * TIMEBASE,
            "verified": {
                "probe_id": id,
                "path": str(path),
                "kind": kind,
                "label": id,
                "size_bytes": path.stat().st_size,
                "content_sha256": "0" * 64,
                "duration_ticks": 0 if kind == "image" else 2 * TIMEBASE,
                "width": 320,
                "height": 180,
                "has_audio": kind == "video",
            },
        }

    project = Project.model_validate(
        {
            "id": "render",
            "name": "render",
            "settings": {"width": 320, "height": 180},
            "tracks": [
                {"id": "base", "kind": "video", "name": "base"},
                {"id": "top", "kind": "video", "name": "top"},
            ],
            "assets": {"blue": asset("blue", blue, "video"), "red": asset("red", red, "image")},
            "clips": {
                "blue": {
                    "id": "blue",
                    "asset_id": "blue",
                    "track_id": "base",
                    "position_ticks": 0,
                    "duration_ticks": 2 * TIMEBASE,
                },
                "red": {
                    "id": "red",
                    "asset_id": "red",
                    "track_id": "top",
                    "position_ticks": 0,
                    "duration_ticks": 2 * TIMEBASE,
                    "effects": {"x": 0.25, "scale": 0.4, "rotation": 12.0},
                    "keyframes": [
                        {"property": "opacity", "at_ticks": 0, "value": 0.0},
                        {"property": "opacity", "at_ticks": 2 * TIMEBASE, "value": 1.0},
                        {"property": "scale", "at_ticks": 0, "value": 0.2},
                        {"property": "scale", "at_ticks": 2 * TIMEBASE, "value": 0.5},
                    ],
                },
            },
        }
    )
    out = folder / "result.mp4"
    base = project.model_copy(
        deep=True, update={"tracks": project.tracks[:1], "clips": {"blue": project.clips["blue"]}}
    )
    for op, expected_duration, last in (("clip.insert", 3, 2.75), ("clip.overwrite", 2, 1.75)):
        placed = apply_commands(
            base,
            batch(
                [
                    {
                        "op": op,
                        "clip": {
                            "id": "replacement",
                            "asset_id": "red",
                            "track_id": "base",
                            "position_ticks": TIMEBASE // 2,
                            "duration_ticks": TIMEBASE,
                        },
                    }
                ]
            ),
        )
        placed_out = folder / f"{op}.mp4"
        placement_plan = compile_render_plan(placed, "h264-source-quality")
        placement_proc = subprocess.run(
            placement_plan.ffmpeg_argv(str(ffmpeg), str(placed_out)),
            capture_output=True,
            timeout=90,
            creationflags=0x08000000,
        )
        assert placement_proc.returncode == 0, placement_proc.stderr.decode(errors="replace")
        for at, color in ((0.25, 2), (0.75, 0), (last, 2)):
            rgb = run(
                [
                    "-ss",
                    str(at),
                    "-i",
                    str(placed_out),
                    "-frames:v",
                    "1",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "pipe:1",
                ]
            )
            pixel = rgb[(90 * 320 + 160) * 3 : (90 * 320 + 160) * 3 + 3]
            assert pixel[color] > 240 and pixel[(color + 1) % 3] < 15, (op, at, pixel)
        probe = ROOT / "desktop/resources/bin/ffprobe.exe"
        meta = json.loads(
            subprocess.check_output(
                [str(probe), "-v", "error", "-show_format", "-of", "json", str(placed_out)],
                creationflags=0x08000000,
            )
        )
        assert abs(float(meta["format"]["duration"]) - expected_duration) < 0.05
    plan = compile_render_plan(project, "h264-source-quality")
    proc = subprocess.run(
        plan.ffmpeg_argv(str(ffmpeg), str(out)),
        capture_output=True,
        timeout=90,
        creationflags=0x08000000,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    for at, expected in ((0.5, 63), (1.5, 191)):
        frame = run(
            [
                "-ss",
                str(at),
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
        index = (90 * 320 + 240) * 3
        pixel = frame[index : index + 3]
        assert len(pixel) == 3 and abs(pixel[0] - expected) < 22, (at, list(pixel), expected)
        untouched = frame[(90 * 320 + 40) * 3 : (90 * 320 + 40) * 3 + 3]
        assert untouched[2] > 220 and untouched[0] < 20, list(untouched)

    enhanced = apply_commands(
        project,
        batch(
            [
                {"op": "clip.remove", "clip_id": "red"},
                {"op": "clip.speed", "clip_id": "blue", "speed_percent": 200},
                {"op": "clip.color", "clip_id": "blue", "color": {"saturation": 0.0}},
                {
                    "op": "asset.register",
                    "asset": {
                        "id": "title",
                        "kind": "text",
                        "label": "title",
                        "reference": "generated:text",
                    },
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "title",
                        "asset_id": "title",
                        "track_id": "top",
                        "position_ticks": 0,
                        "duration_ticks": TIMEBASE,
                        "text": {"body": "中文 Agent %{n}; [x], '安全'", "font_size": 0.1},
                    },
                },
            ]
        ),
    )
    plan = compile_render_plan(enhanced, "h264-source-quality")
    for name, body in plan.text_files.items():
        (folder / name).write_text(body, encoding="utf-8")
    out = folder / "enhanced.mp4"
    proc = subprocess.run(
        plan.ffmpeg_argv(str(ffmpeg), str(out)),
        cwd=folder,
        capture_output=True,
        timeout=90,
        creationflags=0x08000000,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    frame = run(
        [
            "-ss",
            "0.5",
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
    corner = frame[(10 * 320 + 10) * 3 : (10 * 320 + 10) * 3 + 3]
    assert max(corner) - min(corner) < 5, list(corner)
    assert sum(min(frame[i : i + 3]) > 180 for i in range(0, len(frame), 3)) > 100, (
        "title not rendered"
    )
    ffprobe = ROOT / "desktop/resources/bin/ffprobe.exe"
    metadata = json.loads(
        subprocess.check_output(
            [str(ffprobe), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(out)],
            creationflags=0x08000000,
        )
    )
    assert abs(float(metadata["format"]["duration"]) - 1) < 0.08
    assert {s["codec_type"] for s in metadata["streams"]} == {"video", "audio"}
    samples = array(
        "h", run(["-i", str(out), "-vn", "-ac", "1", "-ar", "48000", "-f", "s16le", "pipe:1"])
    )[4800:38400]
    hz = sum(a <= 0 < b for a, b in zip(samples, samples[1:])) * 48000 / len(samples)
    assert abs(hz - 440) < 8, f"speed changed pitch to {hz}Hz"

    store = ProjectStore(folder / "queued.sqlite")
    created = store.create(
        CreateProject(
            request_id="create", name="queued", settings=SequenceSettings(width=320, height=180)
        )
    )
    request = EditBatch(
        request_id="before",
        expected_revision=0,
        commands=batch(
            [
                {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                {
                    "op": "asset.register",
                    "asset": {
                        "id": "text",
                        "kind": "text",
                        "label": "text",
                        "reference": "generated:text",
                    },
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "c",
                        "asset_id": "text",
                        "track_id": "v",
                        "position_ticks": 0,
                        "duration_ticks": TIMEBASE,
                        "text": {"body": "BEFORE", "font_size": 0.15},
                    },
                },
            ]
        ),
    )
    before = store.mutate(created.project.id, request).project
    jobs = JobRuntime(store.path, ffmpeg, folder / "exports", [folder])
    job = jobs._save(
        RenderJob(
            id="snapshot",
            project_id=before.id,
            revision=1,
            preset_id="h264-source-quality",
            filename="snapshot.mp4",
            status="queued",
            output_path=str(folder / "exports/snapshot.mp4"),
        )
    )
    store.mutate(
        before.id,
        EditBatch(
            request_id="after",
            expected_revision=1,
            commands=batch([{"op": "clip.effects", "clip_id": "c", "effects": {"opacity": 0.0}}]),
        ),
    )
    jobs._run_one(job.id)
    finished = jobs.get(job.id)
    assert finished.status == "succeeded", finished.message
    frame = run(
        [
            "-i",
            finished.output_path,
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
    )
    assert sum(min(frame[i : i + 3]) > 180 for i in range(0, len(frame), 3)) > 100, (
        "queued render used current state instead of its snapshot"
    )
    try:
        store.mutate(
            before.id,
            EditBatch(
                request_id="forged",
                expected_revision=2,
                commands=batch(
                    [{"op": "asset.register", "asset": project.assets["blue"].model_dump()}]
                ),
            ),
        )
    except EditorError as error:
        assert error.code == "INVALID_PROBE" and store.get(before.id).revision == 2
    else:
        raise AssertionError("metadata registration bypassed verified import")


if __name__ == "__main__":
    main()
