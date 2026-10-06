"""Real composite frames include layers, animation and text, with exact snapshot clocks."""

import struct
import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE as T
from agentcut.contracts import CreateProject, EditBatch
from agentcut.http_api import create_app
from agentcut.media import MediaService
from agentcut.projects import ProjectStore

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "frame-check-token-" + "x" * 40


def main():
    ffmpeg = ROOT / "desktop/resources/bin/ffmpeg.exe"
    ffprobe = ROOT / "desktop/resources/bin/ffprobe.exe"
    with tempfile.TemporaryDirectory(prefix="agentcut-frames-") as temp:
        folder = Path(temp)
        media_dir = folder / "media"
        media_dir.mkdir()
        media = MediaService(
            folder / "test.sqlite3", [media_dir], folder / "cache", ffmpeg, ffprobe
        )
        store = ProjectStore(media.db_path, media)
        p = store.create(CreateProject(request_id="new", name="frames")).project
        commands = []
        for name in ("red", "blue"):
            path = media_dir / (name + ".mp4")
            subprocess.run(
                [
                    str(ffmpeg),
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color={name}:s=320x180:r=30:d=2",
                    "-c:v",
                    "libx264",
                    "-y",
                    str(path),
                ],
                check=True,
                creationflags=0x08000000,
            )
            probe = media.import_file(str(path))
            commands += [
                {"op": "track.add", "track": {"id": name, "kind": "video", "name": name}},
                {
                    "op": "asset.import",
                    "asset_id": name,
                    "probe_id": probe.id,
                    "label": name,
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
        p = store.mutate(
            p.id,
            EditBatch.model_validate(
                {"request_id": "seed", "expected_revision": 0, "commands": commands}
            ),
        ).project
        with TestClient(
            create_app(store.path, TOKEN, media),
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer " + TOKEN, "Origin": "http://127.0.0.1:5179"},
        ) as client:

            def frame(revision, at=T):
                response = client.get(
                    f"/v1/projects/{p.id}/frame?revision={revision}&at_ticks={at}"
                )
                assert response.status_code == 200, response.text
                assert response.headers["x-frame-ticks"] == str(
                    at // p.settings.frame_ticks * p.settings.frame_ticks
                )
                assert "X-Frame-Ticks" in response.headers["access-control-expose-headers"]
                width, height = struct.unpack(">II", response.content[16:24])
                raw = subprocess.run(
                    [
                        str(ffmpeg),
                        "-v",
                        "error",
                        "-i",
                        "pipe:0",
                        "-frames:v",
                        "1",
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
                return raw, width, height

            def pixel(result, x=0.5, y=0.5):
                raw, width, height = result
                offset = (
                    min(height - 1, int(height * y)) * width + min(width - 1, int(width * x))
                ) * 3
                return tuple(raw[offset : offset + 3])

            blue = pixel(frame(1, T + p.settings.frame_ticks // 2))
            assert blue[2] > 240 and blue[0] < 10, blue
            p = store.mutate(
                p.id,
                EditBatch.model_validate(
                    {
                        "request_id": "animate",
                        "expected_revision": 1,
                        "commands": [
                            {
                                "op": "keyframe.set",
                                "clip_id": "blue",
                                "keyframe": {"property": "opacity", "at_ticks": 0, "value": 0.0},
                            },
                            {
                                "op": "keyframe.set",
                                "clip_id": "blue",
                                "keyframe": {
                                    "property": "opacity",
                                    "at_ticks": 2 * T,
                                    "value": 1.0,
                                },
                            },
                        ],
                    }
                ),
            ).project
            mixed = pixel(frame(2))
            assert 110 < mixed[0] < 145 and 110 < mixed[2] < 145, mixed
            assert pixel(frame(1))[2] > 240  # old revision remains blue
            p = store.mutate(
                p.id,
                EditBatch.model_validate(
                    {
                        "request_id": "title",
                        "expected_revision": 2,
                        "commands": [
                            {
                                "op": "track.add",
                                "track": {"id": "title", "kind": "video", "name": "title"},
                            },
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
                                    "id": "title",
                                    "asset_id": "text",
                                    "track_id": "title",
                                    "position_ticks": 0,
                                    "duration_ticks": 2 * T,
                                    "text": {
                                        "body": "标题",
                                        "align": "bottom",
                                        "box": True,
                                        "font_size": 0.12,
                                    },
                                },
                            },
                        ],
                    }
                ),
            ).project
            titled = frame(3)
            plate = pixel(titled, 0.03, 0.86)
            assert plate[0] < mixed[0] - 30 and plate[2] < mixed[2] - 30, (plate, mixed)
            assert pixel(frame(3, 2 * T)) == (0, 0, 0)
            assert (
                client.get(
                    f"/v1/projects/{p.id}/frame?at_ticks=0",
                    headers={"Authorization": "Bearer wrong"},
                ).status_code
                == 401
            )
    print(
        "PASS: real composite frame, layers, opacity animation, subtitle plate, "
        "CORS, snapshot and end frame"
    )


if __name__ == "__main__":
    main()
