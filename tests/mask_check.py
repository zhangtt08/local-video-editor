"""Real mask pixels, atomic candidate edits and old schema/receipt compatibility."""

import hashlib
import json
import struct
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import CreateProject, EditBatch, ShapeMask
from agentcut.http_api import create_app
from agentcut.media import MediaService
from agentcut.projects import ProjectStore
from agentcut.render import compile_render_plan

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "mask-check-" + "m" * 48


def main():
    for bad in (
        {"width": 0},
        {"height": 3},
        {"center_x": -0.1},
        {"feather": 1.1},
        {"shape": "path"},
    ):
        try:
            ShapeMask.model_validate(bad)
            raise AssertionError(bad)
        except ValidationError:
            pass
    ffmpeg = ROOT / "desktop/resources/bin/ffmpeg.exe"
    ffprobe = ROOT / "desktop/resources/bin/ffprobe.exe"
    with tempfile.TemporaryDirectory(prefix="agentcut-masks-") as temp:
        folder = Path(temp)
        media_dir = folder / "media"
        media_dir.mkdir()
        media = MediaService(folder / "db.sqlite3", [media_dir], folder / "cache", ffmpeg, ffprobe)
        store = ProjectStore(media.db_path, media)
        p = store.create(CreateProject(request_id="new", name="masks")).project
        commands = []
        for name in ("red", "blue"):
            path = media_dir / (name + ".mp4")
            subprocess.run(
                [
                    str(ffmpeg),
                    "-v",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color={name}:s=320x180:r=30:d=2",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=2",
                    "-c:v",
                    "libx264",
                    "-c:a",
                    "aac",
                    str(path),
                ],
                check=True,
                creationflags=0x08000000,
            )
            probe = media.import_file(str(path))
            commands.extend(
                [
                    {"op": "track.add", "track": {"id": name, "kind": "video", "name": name}},
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
                            "position_ticks": 0,
                            "duration_ticks": 2 * T,
                        },
                    },
                ]
            )
        p = store.mutate(
            p.id,
            EditBatch.model_validate(
                {"request_id": "seed", "expected_revision": 0, "commands": commands}
            ),
        ).project
        # Reconstruct the old release's canonical clip.add payload and persisted receipt.
        legacy = {
            "request_id": "old-add",
            "expected_revision": 1,
            "commands": [
                {
                    "op": "clip.add",
                    "clip": {
                        "id": "old",
                        "asset_id": "blue",
                        "track_id": "blue",
                        "position_ticks": 2 * T,
                        "source_in_ticks": 0,
                        "duration_ticks": T,
                    },
                }
            ],
        }
        request = EditBatch.model_validate(legacy)
        fingerprint = hashlib.sha256(
            json.dumps(["edit", legacy], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        assert ProjectStore._fingerprint("edit", request) == fingerprint
        for version in range(1, 6):
            snapshot = p.model_dump()
            snapshot["schema_version"] = version
            for clip in snapshot["clips"].values():
                clip.pop("mask")
            assert type(p).model_validate(snapshot).clips["blue"].mask is None
        with TestClient(
            create_app(store.path, TOKEN, media),
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client:

            def edit(commands, dry=False, request_id=None):
                current = store.get(p.id)
                body = {
                    "request_id": request_id or f"edit-{current.revision}",
                    "expected_revision": current.revision,
                    "commands": commands,
                    "dry_run": dry,
                }
                response = client.post(f"/v1/projects/{p.id}/edits", json=body)
                return response, body

            def frame(revision):
                response = client.get(f"/v1/projects/{p.id}/frame?revision={revision}&at_ticks={T}")
                assert response.status_code == 200, response.text
                w, h = struct.unpack(">II", response.content[16:24])
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
                    input=response.content,
                    capture_output=True,
                    check=True,
                    creationflags=0x08000000,
                ).stdout
                return lambda x, y: tuple(
                    raw[(int(y * h) * w + int(x * w)) * 3 : (int(y * h) * w + int(x * w)) * 3 + 3]
                )

            for shape in ("rectangle", "ellipse"):
                mask = {"shape": shape, "width": 0.5, "height": 0.5, "feather": 0.5}
                command = {"op": "clip.mask", "clip_id": "blue", "mask": mask}
                before = store.get(p.id).model_dump()
                dry, _ = edit([command], True)
                assert dry.status_code == 200 and not dry.json()["committed"], dry.text
                candidate = dry.json()["project"]
                preview = client.post("/v1/preview-manifest", json=candidate)
                assert (
                    preview.status_code == 200
                    and "data:image/svg+xml" in preview.json()["clips"]["blue"]["mask_image"]
                )
                assert store.get(p.id).model_dump() == before
                response, body = edit([command])
                assert response.status_code == 200, response.text
                result = response.json()["project"]
                replay = client.post(f"/v1/projects/{p.id}/edits", json=body)
                assert replay.json()["replayed"] and store.get(p.id).revision == result["revision"]
                pixel = frame(result["revision"])
                assert pixel(0.5, 0.5)[2] > 240 and pixel(0.1, 0.1)[0] > 240
                assert 119 <= pixel(0.6875, 0.5)[2] <= 132, pixel(0.6875, 0.5)
                corner = pixel(0.6875, 0.6875)[2]
                assert 51 <= corner <= 70 if shape == "rectangle" else corner < 10, (shape, corner)
                mask["inverted"] = True
                response, _ = edit([{"op": "clip.mask", "clip_id": "blue", "mask": mask}])
                assert response.status_code == 200, response.text
                pixel = frame(response.json()["project"]["revision"])
                assert pixel(0.5, 0.5)[0] > 240 and pixel(0.1, 0.1)[2] > 240
            response, _ = edit(
                [
                    {
                        "op": "clip.mask",
                        "clip_id": "blue",
                        "mask": {"shape": "ellipse", "width": 0.5, "height": 0.5},
                    },
                    {
                        "op": "clip.effects",
                        "clip_id": "blue",
                        "effects": {"x": 0.1, "scale": 0.5, "rotation": 90},
                    },
                ]
            )
            assert response.status_code == 200, response.text
            pixel = frame(response.json()["project"]["revision"])
            # Masked picture scales/rotates/translates together; its original alpha survives.
            assert pixel(0.6, 0.5)[2] > 240 and pixel(0.6, 0.68)[2] > 240
            assert pixel(0.68, 0.5)[0] > 240 and pixel(0.1, 0.1)[0] > 240
            response, _ = edit(
                [
                    {"op": "track.add", "track": {"id": "sound", "kind": "audio", "name": "sound"}},
                    {
                        "op": "clip.detach_audio",
                        "clip_id": "blue",
                        "audio_clip_id": "voice",
                        "track_id": "sound",
                    },
                ]
            )
            assert response.status_code == 200, response.text
            latest = store.get(p.id)
            assert latest.clips["blue"].mask and latest.clips["voice"].mask is None
            before = latest.model_dump()
            rejected, _ = edit(
                [
                    {"op": "clip.effects", "clip_id": "red", "effects": {"x": 0.1}},
                    {"op": "clip.mask", "clip_id": "voice", "mask": {}},
                ]
            )
            assert (
                rejected.status_code == 422 and rejected.json()["error"]["code"] == "INVALID_MASK"
            )
            assert store.get(p.id).model_dump() == before
            response, _ = edit([{"op": "track.update", "track_id": "blue", "locked": True}])
            rejected, _ = edit([{"op": "clip.mask", "clip_id": "blue", "mask": None}])
            assert (
                rejected.status_code == 422 and rejected.json()["error"]["code"] == "TRACK_LOCKED"
            )
            edit([{"op": "track.update", "track_id": "blue", "locked": False}])
            response, _ = edit(
                [{"op": "clip.split", "clip_id": "blue", "at_ticks": T, "right_clip_id": "right"}]
            )
            latest = store.get(p.id)
            assert latest.clips["right"].mask == latest.clips["blue"].mask
            # A mask alone must use compositing, even with one visible track.
            one = latest.model_copy(deep=True)
            one.tracks = [track for track in one.tracks if track.id == "blue"]
            one.clips = {key: clip for key, clip in one.clips.items() if clip.track_id == "blue"}
            assert compile_render_plan(one, "proxy-540p-fast").mode == "layered"
            response, _ = edit(
                [
                    {"op": "clip.mask", "clip_id": "blue", "mask": None},
                    {"op": "clip.mask", "clip_id": "right", "mask": None},
                ]
            )
            assert response.status_code == 200 and store.get(p.id).clips["blue"].mask is None
    print(
        "PASS: real rectangle/ellipse feather/invert pixels, candidates read-only, replay, locks, "
        "audio rejection/detach, split, v1-v5 and old receipt"
    )


if __name__ == "__main__":
    main()
