"""Portable project bundle: zip round-trip keeps clips, and media is re-probed on import."""

import io
import json
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from agentcut.contracts import TIMEBASE, CreateProject, EditBatch
from agentcut.http_api import create_app
from agentcut.media import MediaService
from agentcut.projects import ProjectStore

ROOT = Path(__file__).resolve().parent.parent
T = TIMEBASE
TOKEN = "bundle-check-token-" + "k" * 40


def main():
    with tempfile.TemporaryDirectory(prefix="agentcut-bundle-") as folder:
        folder = Path(folder)
        media_dir = folder / "media"
        media_dir.mkdir()
        src = media_dir / "clip.mp4"
        ffmpeg = ROOT / "desktop/resources/bin/ffmpeg.exe"
        ffprobe = ROOT / "desktop/resources/bin/ffprobe.exe"
        import subprocess

        subprocess.run(
            [
                str(ffmpeg),
                "-v",
                "error",
                "-y",
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
                str(src),
            ],
            check=True,
            timeout=90,
            creationflags=0x08000000,
        )
        db = folder / "check.sqlite3"
        media = MediaService(db, [media_dir], folder / "cache", ffmpeg, ffprobe)
        store = ProjectStore(db, media)
        created = store.create(CreateProject(request_id="new", name="打包工程"))
        probe = media.import_file(str(src))
        store.mutate(
            created.project.id,
            EditBatch.model_validate(
                {
                    "request_id": "seed",
                    "expected_revision": 0,
                    "commands": [
                        {"op": "track.add", "track": {"id": "v", "kind": "video", "name": "v"}},
                        {"op": "track.add", "track": {"id": "a", "kind": "audio", "name": "a"}},
                        {
                            "op": "asset.import",
                            "asset_id": "m",
                            "label": "clip",
                            "probe_id": probe.id,
                            "verified": probe.verified.model_dump(),
                        },
                        {
                            "op": "asset.register",
                            "asset": {
                                "id": "note",
                                "kind": "text",
                                "label": "字幕",
                                "reference": "generated:text",
                            },
                        },
                        {
                            "op": "clips.add",
                            "clips": [
                                {
                                    "id": "c1",
                                    "asset_id": "m",
                                    "track_id": "v",
                                    "position_ticks": 0,
                                    "duration_ticks": 2 * T,
                                },
                                {
                                    "id": "t1",
                                    "asset_id": "note",
                                    "track_id": "v",
                                    "position_ticks": 2 * T,
                                    "duration_ticks": T,
                                    "text": {
                                        "body": "副标题",
                                        "font_size": 0.08,
                                        "color": "#FFFFFF",
                                    },
                                },
                            ],
                        },
                    ],
                }
            ),
        )
        current = store.get(created.project.id)
        store.mutate(
            current.id,
            EditBatch.model_validate(
                {
                    "request_id": "lock",
                    "expected_revision": current.revision,
                    "commands": [{"op": "track.update", "track_id": "v", "locked": True}],
                }
            ),
        )
        with TestClient(
            create_app(db, TOKEN, media, None, {}),
            base_url="http://127.0.0.1",
            headers={"Authorization": f"Bearer {TOKEN}"},
        ) as client:
            bundle = client.get(f"/v1/projects/{created.project.id}/bundle")
            assert bundle.status_code == 200, bundle.text
            assert "attachment" in bundle.headers.get("content-disposition", "")
            archive = zipfile.ZipFile(io.BytesIO(bundle.content))
            manifest = json.loads(archive.read("project.json"))
            assert manifest["name"] == "打包工程"
            assert manifest["_bundle"]["files"]["m"].startswith("media/m")
            assert manifest["clips"]["c1"]["duration_ticks"] == 2 * T

            restored = client.post(
                "/v1/bundle?request_id=import",
                content=bundle.content,
                headers={"Content-Type": "application/zip"},
            )
            assert restored.status_code == 200, restored.text
            project = restored.json()["project"]
            assert project["id"] != created.project.id
            assert project["name"] == "打包工程"
            assert len(project["clips"]) == 2
            assert project["revision"] == 0
            assert next(t for t in project["tracks"] if t["id"] == "v")["locked"]
            assert project["clips"]["t1"]["text"]["body"] == "副标题"
            imported_asset = project["assets"]["m"]
            assert imported_asset["verified"] and imported_asset["verified"]["path"].endswith(
                ".mp4"
            )
            assert imported_asset["verified"]["content_sha256"] == probe.verified.content_sha256
            assert project["assets"]["note"]["kind"] == "text"
            # the media landed inside a configured media root
            assert media.resolve_path(imported_asset["verified"]["path"])[0].is_file()

            def counts():
                with store.connection() as connection:
                    return {
                        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                        for table in ("projects", "history", "receipts", "media_probes")
                    }

            def upload(body, request="import"):
                return client.post(
                    f"/v1/bundle?request_id={request}",
                    content=body,
                    headers={"Content-Type": "application/zip"},
                )

            def repack(document, extra=None):
                result = io.BytesIO()
                with zipfile.ZipFile(result, "w") as packed:
                    packed.writestr("project.json", json.dumps(document, ensure_ascii=False))
                    for name in archive.namelist():
                        if name != "project.json":
                            packed.writestr(name, archive.read(name))
                    if extra:
                        packed.writestr(extra, b"unexpected")
                return result.getvalue()

            before = counts()
            folders = set((media_dir / "bundle-imports").iterdir())
            retry = upload(bundle.content)
            assert retry.status_code == 200 and retry.json()["replayed"]
            assert retry.json()["project"]["id"] == project["id"]
            assert counts() == before and set((media_dir / "bundle-imports").iterdir()) == folders
            conflict = upload(repack({**manifest, "name": "different bytes"}))
            assert conflict.status_code == 409

            # Final validation after re-probing must roll back even new probe records.
            late = json.loads(json.dumps(manifest))
            late["assets"]["m"]["duration_ticks"] = 5 * T
            late["clips"]["c1"]["duration_ticks"] = 3 * T
            late["clips"]["t1"]["position_ticks"] = 4 * T
            failure = upload(repack(late), "late-failure")
            assert failure.status_code == 422, failure.text
            assert counts() == before and set((media_dir / "bundle-imports").iterdir()) == folders
            assert upload(repack(manifest, "../outside.mp4"), "traversal").status_code == 422
            with patch("agentcut.bundles.MAX_UNPACKED_BYTES", 1):
                assert upload(bundle.content, "large-unpacked").status_code == 413
            with patch("agentcut.http_api.MAX_BUNDLE_BYTES", 1):
                assert upload(bundle.content, "large-upload").status_code == 413
            with patch("agentcut.bundles.MAX_BUNDLE_BYTES", 1):
                assert client.get(f"/v1/projects/{created.project.id}/bundle").status_code == 413
            assert counts() == before

            empty = store.create(CreateProject(request_id="empty", name="empty")).project
            empty_body = client.get(f"/v1/projects/{empty.id}/bundle").content
            empty_result = upload(empty_body, "empty-import")
            assert empty_result.status_code == 200, empty_result.text
            assert not empty_result.json()["project"]["clips"]
            assert client.post("/v1/bundle", content=empty_body).status_code == 422

            before = counts()
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: upload(bundle.content, "parallel"), range(2)))
            assert all(r.status_code == 200 for r in results), [r.text for r in results]
            assert len({r.json()["project"]["id"] for r in results}) == 1
            assert sorted(r.json()["replayed"] for r in results) == [False, True]
            after = counts()
            assert after["projects"] == before["projects"] + 1
            assert after["history"] == before["history"] + 1
            assert after["receipts"] == before["receipts"] + 1
            assert after["media_probes"] == before["media_probes"] + 1

            bad = client.post(
                "/v1/bundle?request_id=invalid",
                content=b"not a zip",
                headers={"Content-Type": "application/zip"},
            )
            assert bad.status_code == 422, bad.text
    print("PASS: bundle export/import round-trip, media re-probed, clips restored")


if __name__ == "__main__":
    main()
