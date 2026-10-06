"""Independent RGB formulas, alpha coverage, transition ordering and atomic blend edits."""

import hashlib
import json
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import CreateProject, EditBatch
from agentcut.http_api import create_app
from agentcut.media import MediaService
from agentcut.projects import ProjectStore
from agentcut.render import compile_render_plan

ROOT = Path(__file__).resolve().parent.parent
BASE, TOP, NEXT = (128, 64, 200), (200, 128, 32), (40, 220, 160)


def png(path, rgb):
    def chunk(kind, body):
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    raw = (b"\0" + bytes(rgb) * 64) * 36
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 36, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def formula(mode, top, alpha):
    result = []
    for b, s in zip(BASE, top):
        if mode == "normal":
            color = s
        elif mode == "multiply":
            color = b * s / 255
        elif mode == "screen":
            color = b + s - b * s / 255
        elif mode == "overlay":
            color = 2 * b * s / 255 if b < 127.5 else 255 - 2 * (255 - b) * (255 - s) / 255
        elif mode == "darken":
            color = min(b, s)
        elif mode == "lighten":
            color = max(b, s)
        elif mode == "difference":
            color = abs(b - s)
        else:
            color = b + s - 2 * b * s / 255
        result.append(b * (1 - alpha) + color * alpha)
    return result


def main():
    ffmpeg = ROOT / "desktop/resources/bin/ffmpeg.exe"
    ffprobe = ROOT / "desktop/resources/bin/ffprobe.exe"
    with tempfile.TemporaryDirectory(prefix="agentcut-blend-") as temp:
        folder = Path(temp)
        media = MediaService(folder / "db.sqlite3", [folder], folder / "cache", ffmpeg, ffprobe)
        store = ProjectStore(media.db_path, media)
        p = store.create(
            CreateProject(request_id="new", name="blends", settings={"width": 320, "height": 180})
        ).project
        commands = [
            {"op": "track.add", "track": {"id": "base", "kind": "video", "name": "base"}},
            {"op": "track.add", "track": {"id": "top", "kind": "video", "name": "top"}},
            {"op": "track.add", "track": {"id": "sound", "kind": "audio", "name": "sound"}},
        ]
        for name, rgb in [("base", BASE), ("top", TOP), ("next", NEXT)]:
            path = folder / (name + ".png")
            png(path, rgb)
            probe = media.import_file(str(path))
            commands.append(
                {
                    "op": "asset.import",
                    "asset_id": name,
                    "label": name,
                    "probe_id": probe.id,
                    "verified": probe.verified.model_dump(),
                }
            )
        for name in ["base", "top"]:
            commands.append(
                {
                    "op": "clip.add",
                    "clip": {
                        "id": name,
                        "asset_id": name,
                        "track_id": name,
                        "position_ticks": 0,
                        "duration_ticks": 3 * T,
                    },
                }
            )
        commands += [
            {"op": "clip.effects", "clip_id": "top", "effects": {"opacity": 0.5}},
            {
                "op": "clip.mask",
                "clip_id": "top",
                "mask": {"shape": "rectangle", "width": 0.5, "height": 0.5, "feather": 0.5},
            },
        ]
        p = store.mutate(
            p.id,
            EditBatch.model_validate(
                {"request_id": "seed", "expected_revision": 0, "commands": commands}
            ),
        ).project
        for version in range(1, 7):
            old = p.model_dump()
            old["schema_version"] = version
            for track in old["tracks"]:
                track.pop("blend_mode")
            assert all(t.blend_mode == "normal" for t in type(p).model_validate(old).tracks)
        # Byte-identical v1 expanded track defaults, including track.update nulls.
        legacy = {
            "request_id": "legacy",
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
                    "op": "track.update",
                    "track_id": "v",
                    "name": None,
                    "muted": True,
                    "hidden": None,
                    "volume": None,
                },
            ],
        }
        digest = hashlib.sha256(
            json.dumps(["edit", legacy], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        assert store._fingerprint("edit", EditBatch.model_validate(legacy)) == digest
        with TestClient(
            create_app(store.path, "b" * 48, media),
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer " + "b" * 48},
        ) as client:

            def edit(commands, dry=False):
                current = store.get(p.id)
                body = {
                    "request_id": f"b-{current.revision}",
                    "expected_revision": current.revision,
                    "commands": commands,
                    "dry_run": dry,
                }
                return client.post(f"/v1/projects/{p.id}/edits", json=body), body

            def pixels(at=T):
                revision = store.get(p.id).revision
                frame = client.get(f"/v1/projects/{p.id}/frame?revision={revision}&at_ticks={at}")
                assert frame.status_code == 200, frame.text
                w, h = struct.unpack(">II", frame.content[16:24])
                raw = subprocess.run(
                    [
                        str(ffmpeg),
                        "-v",
                        "error",
                        "-i",
                        "pipe:0",
                        "-f",
                        "rawvideo",
                        "-pix_fmt",
                        "rgb24",
                        "pipe:1",
                    ],
                    input=frame.content,
                    capture_output=True,
                    check=True,
                    creationflags=0x08000000,
                ).stdout
                return lambda x, y: tuple(
                    raw[(int(y * h) * w + int(x * w)) * 3 : (int(y * h) * w + int(x * w)) * 3 + 3]
                )

            for mode in [
                "normal",
                "multiply",
                "screen",
                "overlay",
                "darken",
                "lighten",
                "difference",
                "exclusion",
            ]:
                command = {"op": "track.update", "track_id": "top", "blend_mode": mode}
                before = store.get(p.id).model_dump()
                dry, _ = edit([command], True)
                assert dry.status_code == 200 and not dry.json()["committed"], dry.text
                manifest = client.post("/v1/preview-manifest", json=dry.json()["project"]).json()
                assert manifest["track_blend_modes"]["top"] == mode
                assert store.get(p.id).model_dump() == before
                saved, body = edit([command])
                assert saved.status_code == 200, saved.text
                assert client.post(f"/v1/projects/{p.id}/edits", json=body).json()["replayed"]
                pixel = pixels()
                for xy, alpha in [((0.5, 0.5), 0.5), ((0.6875, 0.5), 0.25), ((0.1, 0.1), 0)]:
                    actual = pixel(*xy)
                    expected = formula(mode, TOP, alpha)
                    assert max(abs(a - b) for a, b in zip(actual, expected)) < 6, (
                        mode,
                        xy,
                        actual,
                        expected,
                    )
            edit([{"op": "track.update", "track_id": "top", "hidden": True}])
            assert max(abs(a - b) for a, b in zip(pixels()(0.5, 0.5), BASE)) < 4
            edit(
                [
                    {
                        "op": "track.update",
                        "track_id": "top",
                        "hidden": False,
                        "blend_mode": "screen",
                    },
                    {"op": "clip.mask", "clip_id": "top", "mask": None},
                    {
                        "op": "clip.trim",
                        "clip_id": "top",
                        "source_in_ticks": 0,
                        "duration_ticks": 2 * T,
                    },
                    {
                        "op": "clip.add",
                        "clip": {
                            "id": "next",
                            "asset_id": "next",
                            "track_id": "top",
                            "position_ticks": 2 * T,
                            "duration_ticks": 2 * T,
                            "effects": {"opacity": 0.5},
                        },
                    },
                    {
                        "op": "transition.set",
                        "clip_id": "next",
                        "from_clip_id": "top",
                        "duration_ticks": T,
                    },
                ]
            )
            actual = pixels(T + T // 2)(0.5, 0.5)
            expected = formula("screen", [(a + b) / 2 for a, b in zip(TOP, NEXT)], 0.5)
            assert max(abs(a - b) for a, b in zip(actual, expected)) < 6, (actual, expected)
            # Nonlinear modes distinguish blending the finished dissolve from blending
            # its two clips separately; difference would otherwise be visibly too bright.
            for mode in ("difference", "darken", "overlay"):
                saved, _ = edit([{"op": "track.update", "track_id": "top", "blend_mode": mode}])
                assert saved.status_code == 200, saved.text
                actual = pixels(T + T // 2)(0.5, 0.5)
                expected = formula(mode, [(a + b) / 2 for a, b in zip(TOP, NEXT)], 0.5)
                assert max(abs(a - b) for a, b in zip(actual, expected)) < 6, (
                    mode,
                    actual,
                    expected,
                )
            # Blend must keep uncovered composition unchanged, including a track's time gaps.
            edit(
                [
                    {"op": "transition.remove", "clip_id": "next"},
                    {"op": "clip.move", "clip_id": "top", "track_id": "top", "position_ticks": T},
                    {"op": "clip.remove", "clip_id": "next"},
                ]
            )
            assert max(abs(a - b) for a, b in zip(pixels(0)(0.5, 0.5), BASE)) < 4
            edit([{"op": "track.update", "track_id": "top", "locked": True}])
            before = store.get(p.id).model_dump()
            rejected, _ = edit(
                [{"op": "track.update", "track_id": "top", "blend_mode": "multiply"}]
            )
            assert (
                rejected.status_code == 422 and rejected.json()["error"]["code"] == "TRACK_LOCKED"
            )
            rejected, _ = edit(
                [
                    {"op": "clip.effects", "clip_id": "base", "effects": {"x": 0.1}},
                    {"op": "track.update", "track_id": "sound", "blend_mode": "screen"},
                ]
            )
            assert (
                rejected.status_code == 422
                and rejected.json()["error"]["code"] == "INVALID_BLEND_MODE"
            )
            assert store.get(p.id).model_dump() == before
            one = store.get(p.id).model_copy(deep=True)
            one.tracks = [track for track in one.tracks if track.id == "top"]
            one.clips = {"top": one.clips["top"]}
            assert compile_render_plan(one, "proxy-540p-fast").mode == "layered"
            one.tracks[0].blend_mode = "screen"
            plan = compile_render_plan(one, "proxy-540p-fast", preview_size=(320, 180))
            image = subprocess.run(
                plan.frame_argv(str(ffmpeg), T + T // 2),
                capture_output=True,
                check=True,
                creationflags=0x08000000,
            ).stdout
            center = subprocess.run(
                [
                    str(ffmpeg),
                    "-v",
                    "error",
                    "-i",
                    "pipe:0",
                    "-vf",
                    "format=rgb24,crop=1:1:160:90",
                    "-f",
                    "rawvideo",
                    "pipe:1",
                ],
                input=image,
                capture_output=True,
                check=True,
                creationflags=0x08000000,
            ).stdout
            assert max(abs(a - b * 0.5) for a, b in zip(center, TOP)) < 5, center
    print(
        "PASS: 8 independent RGB formulas, masked opacity/feather, transitions, gaps, "
        "hidden tracks, "
        "atomic edits/replay/locks/audio, v1-v6 and receipts"
    )


if __name__ == "__main__":
    main()
