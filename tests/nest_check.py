"""Real nested pictures/audio, scope transactions, cycles, locks and portable snapshots."""

import hashlib
import io
import json
import math
import subprocess
import tempfile
from array import array
from pathlib import Path

from blend_check import png
from fastapi.testclient import TestClient

from agentcut.bundles import export_bundle, import_bundle
from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import BundleImport, CreateProject, EditBatch, RestoreProject
from agentcut.http_api import create_app
from agentcut.media import MediaService
from agentcut.projects import ProjectStore
from agentcut.render import compile_render_plan

ROOT = Path(__file__).resolve().parent.parent


def main():
    ffmpeg = ROOT / "desktop/resources/bin/ffmpeg.exe"
    ffprobe = ROOT / "desktop/resources/bin/ffprobe.exe"
    with tempfile.TemporaryDirectory(prefix="agentcut-nest-") as temp:
        folder = Path(temp)

        def run(argv, **kwargs):
            return subprocess.run(
                [str(ffmpeg), "-v", "error", *argv],
                capture_output=True,
                check=True,
                creationflags=0x08000000,
                **kwargs,
            ).stdout

        run(
            [
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000",
                "-t",
                "4",
                str(folder / "tone.wav"),
            ]
        )
        media = MediaService(folder / "db.sqlite3", [folder], folder / "cache", ffmpeg, ffprobe)
        store = ProjectStore(media.db_path, media)
        p = store.create(
            CreateProject(request_id="new", name="nest", settings={"width": 320, "height": 180})
        ).project

        def edit(commands, seq=None, dry=False, request_id=None):
            return store.mutate(
                p.id,
                EditBatch.model_validate(
                    {
                        "request_id": request_id or f"edit-{store.get(p.id).revision}",
                        "expected_revision": store.get(p.id).revision,
                        "sequence_id": seq,
                        "commands": commands,
                        "dry_run": dry,
                    }
                ),
            ).project

        commands = [
            {"op": "track.add", "track": {"id": name, "kind": kind, "name": name}}
            for name, kind in [("base", "video"), ("top", "video"), ("sound", "audio")]
        ]
        for name, rgb in [("base", (80, 40, 160)), ("top", (160, 100, 20))]:
            png(folder / (name + ".png"), rgb)
        for name, suffix in [("base", ".png"), ("top", ".png"), ("sound", ".wav")]:
            probe = media.import_file(
                str(folder / ("tone.wav" if name == "sound" else name + suffix))
            )
            commands += [
                {
                    "op": "asset.import",
                    "asset_id": name,
                    "label": name,
                    "probe_id": probe.id,
                    "verified": probe.verified.model_dump(),
                },
                {
                    "op": "clip.add",
                    "clip": {
                        "id": name,
                        "asset_id": name,
                        "track_id": name,
                        "position_ticks": T,
                        "duration_ticks": 4 * T,
                    },
                },
            ]
        commands += [
            {"op": "clip.patch", "clip_id": "top", "effects": {"opacity": 0.5, "scale": 0.6}},
            {"op": "track.update", "track_id": "sound", "volume": 0.7},
        ]
        before = edit(commands)
        legacy = {
            "request_id": "legacy",
            "expected_revision": 0,
            "commands": [
                {
                    "op": "asset.register",
                    "asset": {
                        "id": "a",
                        "kind": "text",
                        "label": "a",
                        "reference": "generated:text",
                        "duration_ticks": None,
                        "verified": None,
                    },
                }
            ],
        }
        digest = hashlib.sha256(
            json.dumps(["edit", legacy], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        assert store._fingerprint("edit", EditBatch.model_validate(legacy)) == digest

        def nest(ids, name):
            return {
                "op": "sequence.nest",
                "clip_ids": ids,
                "name": name,
                "sequence_id": name,
                "asset_id": "asset-" + name,
                "clip_id": "clip-" + name,
            }

        candidate = edit([nest(["base", "top", "sound"], "s1")], dry=True, request_id="nest")
        assert store.get(p.id) == before and candidate.sequences["s1"].duration_ticks == 4 * T
        nested = edit([nest(["base", "top", "sound"], "s1")], request_id="nest")
        assert nested == candidate
        assert store.mutate(
            p.id,
            EditBatch(
                request_id="nest",
                expected_revision=1,
                commands=[nest(["base", "top", "sound"], "s1")],
            ),
        ).replayed

        def frame(project, at):
            plan = compile_render_plan(project, "h264-source-quality")
            return run(
                [
                    *plan.input_args,
                    "-filter_complex",
                    ";".join([*plan.filters, f"{plan.audio_label}anullsink"]),
                    "-map",
                    plan.video_label,
                    "-ss",
                    str(at),
                    "-frames:v",
                    "1",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "pipe:1",
                ]
            )

        def center(raw):
            return tuple(raw[(90 * 320 + 160) * 3 : (90 * 320 + 160) * 3 + 3])

        for at in [0.5, 1.5, 3, 4.5]:
            a, b = frame(before, at), frame(nested, at)
            assert len(a) == len(b) == 320 * 180 * 3
            assert max(abs(x - y) for x, y in zip(a, b)) <= 3, (at, center(a), center(b))

        def audio(project):
            plan = compile_render_plan(project, "h264-source-quality")
            raw = run(
                [
                    *plan.input_args,
                    "-filter_complex",
                    ";".join([*plan.filters, f"{plan.video_label}nullsink"]),
                    "-map",
                    plan.audio_label,
                    "-t",
                    "5",
                    "-f",
                    "f32le",
                    "pipe:1",
                ]
            )
            samples = array("f", raw)
            return samples, math.sqrt(sum(v * v for v in samples) / len(samples))

        original_sound, a = audio(before)
        nested_sound, b = audio(nested)
        assert len(original_sound) == len(nested_sound) and abs(a - b) < 0.0001, (a, b)
        trimmed = nested.model_copy(deep=True)
        trimmed.clips["clip-s1"].source_in_ticks = T
        trimmed.clips["clip-s1"].duration_ticks = 2 * T
        assert center(frame(trimmed, 1.5)) == center(frame(nested, 2.5))
        faster = nested.model_copy(deep=True)
        faster.clips["clip-s1"].speed_percent = 200
        faster.clips["clip-s1"].duration_ticks = 2 * T
        assert center(frame(faster, 1.5)) == center(frame(nested, 2))
        translucent = nested.model_copy(deep=True)
        translucent.sequences["s1"].clips["base"].effects.opacity = 0.25
        translucent.sequences["s1"].tracks[1].blend_mode = "multiply"
        result = center(frame(translucent, 2))
        expected = [
            0.5 * (0.75 * s + 0.25 * b * s / 255) + 0.25 * b * 0.5
            for b, s in zip((80, 40, 160), (160, 100, 20))
        ]
        assert max(abs(a - b) for a, b in zip(result, expected)) < 4, (result, expected)
        inner = edit([nest(["top"], "s2")], seq="s1")
        assert center(frame(inner, 2)) == center(frame(nested, 2))
        # Transparent child retains its own color even with a non-normal bottom track.
        blend = edit(
            [{"op": "track.update", "track_id": "top", "blend_mode": "multiply"}], seq="s2"
        )
        assert (
            max(abs(x - y) for x, y in zip(center(frame(blend, 2)), center(frame(inner, 2)))) <= 3
        )
        patched = edit(
            [{"op": "clip.patch", "clip_id": "top", "effects": {"opacity": 0.2}}], seq="s2"
        )
        assert center(frame(patched, 2)) != center(frame(blend, 2))
        assert patched.clips == nested.clips
        saved = store.get(p.id)
        for commands, seq, code in [
            (
                [
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "cycle",
                            "asset_id": "asset-s1",
                            "track_id": "top",
                            "position_ticks": 4 * T,
                            "duration_ticks": T,
                        },
                    },
                    {"op": "sequence.update", "sequence_id": "s2", "duration_ticks": 5 * T},
                ],
                "s2",
                "SEQUENCE_CYCLE",
            ),
            ([{"op": "asset.remove", "asset_id": "top"}], None, "ASSET_IN_USE"),
            ([{"op": "sequence.remove", "sequence_id": "s2"}], None, "SEQUENCE_IN_USE"),
            (
                [{"op": "sequence.update", "sequence_id": "s1", "duration_ticks": T}],
                None,
                "SOURCE_OUT_OF_BOUNDS",
            ),
        ]:
            try:
                edit(commands, seq)
            except Exception as e:
                assert getattr(e, "code", None) == code, e
            else:
                raise AssertionError(code)
            assert store.get(p.id) == saved
        with TestClient(
            create_app(store.path, "n" * 48, media),
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer " + "n" * 48},
        ) as client:
            path = f"/v1/projects/{p.id}"
            manifest = client.get(path + "/preview-manifest?sequence_id=s1").json()
            assert manifest["sequence_id"] == "s1" and "top" in manifest["sequences"]["s2"]["clips"]
            frame_response = client.get(path + f"/frame?at_ticks={T}&sequence_id=s2")
            assert frame_response.status_code == 200, frame_response.text
            body = {
                "request_id": "locked",
                "expected_revision": saved.revision,
                "sequence_id": "s2",
                "commands": [{"op": "track.update", "track_id": "top", "locked": True}],
            }
            assert client.post(path + "/edits", json=body).status_code == 200
            body.update(
                request_id="denied",
                expected_revision=saved.revision + 1,
                commands=[{"op": "clip.patch", "clip_id": "top", "effects": {"x": 0.1}}],
            )
            denied = client.post(path + "/edits", json=body)
            assert denied.status_code == 422 and denied.json()["error"]["code"] == "TRACK_LOCKED"
        restored = store.mutate(
            p.id,
            RestoreProject(
                request_id="undo",
                expected_revision=store.get(p.id).revision,
                target_revision=before.revision,
            ),
        ).project
        assert not restored.sequences and restored.clips == before.clips
        bundle = export_bundle(saved)
        data = bundle.read_bytes()
        bundle.unlink()
        imported = import_bundle(
            store,
            media,
            io.BytesIO(data),
            BundleImport(request_id="bundle", content_sha256=hashlib.sha256(data).hexdigest()),
        ).project
        assert imported.sequences == saved.sequences
        assert center(frame(imported, 2)) == center(frame(saved, 2))
        # Rendered streams retain fixed duration and sample clock through two levels.
        plan = compile_render_plan(saved, "h264-source-quality")
        output = folder / "nested.mp4"
        subprocess.run(
            plan.ffmpeg_argv(str(ffmpeg), str(output)),
            capture_output=True,
            check=True,
            creationflags=0x08000000,
        )
        info = json.loads(
            subprocess.run(
                [str(ffprobe), "-v", "error", "-show_streams", "-of", "json", str(output)],
                capture_output=True,
                check=True,
                creationflags=0x08000000,
            ).stdout
        )
        assert all(abs(float(s["duration"]) - 5) < 0.04 for s in info["streams"])
        print(
            "PASS: two-level transparent nesting, audio, source-safe render, scoped HTTP, "
            "atomic rollback, locks, replay, restore, bundles"
        )


if __name__ == "__main__":
    main()
