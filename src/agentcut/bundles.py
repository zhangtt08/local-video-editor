"""Portable snapshots: streamed files, server probes and one atomic project commit."""

import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from pydantic import ValidationError

from .contracts import BundleImport, EditorError, Project
from .media import ALLOWED_SUFFIXES, MediaService
from .projects import ProjectStore
from .timeline import validate_timeline

MAX_BUNDLE_BYTES = 32 << 30
MAX_UNPACKED_BYTES = 64 << 30
MAX_MANIFEST_BYTES = 128 << 20


def export_bundle(project: Project) -> Path:
    document = project.model_dump()
    files = {}
    packed_bytes = 0
    with tempfile.NamedTemporaryFile(suffix=".agentcut.zip", delete=False) as handle:
        target = Path(handle.name)
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
            for asset in project.assets.values():
                if asset.verified is None:
                    continue
                source = Path(asset.verified.path)
                if not source.is_file():
                    raise EditorError("MEDIA_MISSING", f"source file gone: {asset.id}", 410)
                if source.stat().st_size != asset.verified.size_bytes:
                    raise EditorError("MEDIA_STALE", f"source file changed: {asset.id}", 410)
                packed_bytes += source.stat().st_size
                if packed_bytes > MAX_BUNDLE_BYTES:
                    raise EditorError("BUNDLE_TOO_LARGE", "bundle exceeds 32 GiB", 413)
                name = f"media/{asset.id}{source.suffix.lower()}"
                archive.write(source, name)
                files[asset.id] = name
                document["assets"][asset.id]["verified"]["path"] = ""
            document["_bundle"] = {"schema": 1, "files": files}
            manifest = json.dumps(document, ensure_ascii=False).encode("utf-8")
            if len(manifest) > MAX_MANIFEST_BYTES:
                raise EditorError("BUNDLE_TOO_LARGE", "project manifest exceeds 128 MiB", 413)
            archive.writestr(
                "project.json",
                manifest,
                compress_type=zipfile.ZIP_DEFLATED,
            )
        if target.stat().st_size > MAX_BUNDLE_BYTES:
            raise EditorError("BUNDLE_TOO_LARGE", "bundle exceeds 32 GiB", 413)
        return target
    except OSError:
        target.unlink(missing_ok=True)
        raise EditorError(
            "STORAGE_UNAVAILABLE", "bundle export file operation failed", 503
        ) from None
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def import_bundle(store: ProjectStore, media: MediaService, source, request: BundleImport):
    replay = store.bundle_replay(request)
    if replay:
        return replay
    parent = media.media_root / "bundle-imports"
    folder = None
    keep = False
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(entries) > 10_001 or len(names) != len(set(names)):
                raise EditorError("INVALID_BUNDLE", "too many or duplicate archive entries")
            if any(entry.flag_bits & 1 for entry in entries):
                raise EditorError("INVALID_BUNDLE", "encrypted entries are not supported")
            if sum(entry.file_size for entry in entries) > MAX_UNPACKED_BYTES:
                raise EditorError("BUNDLE_TOO_LARGE", "unpacked bundle exceeds 64 GiB", 413)
            info = archive.getinfo("project.json")
            if info.file_size > MAX_MANIFEST_BYTES:
                raise EditorError("BUNDLE_TOO_LARGE", "project manifest exceeds 128 MiB", 413)
            raw = json.loads(archive.read(info))
            if not isinstance(raw, dict):
                raise EditorError("INVALID_BUNDLE", "project.json must be an object")
            bundle = raw.pop("_bundle", None)
            if (
                not isinstance(bundle, dict)
                or bundle.get("schema") != 1
                or not isinstance(bundle.get("files"), dict)
            ):
                raise EditorError("INVALID_BUNDLE", "unsupported bundle manifest")
            files = bundle["files"]
            # Package paths/probe records are metadata; only this server can verify files.
            assets = raw.get("assets")
            if not isinstance(assets, dict):
                raise EditorError("INVALID_BUNDLE", "project assets must be an object")
            verified_ids = {
                key
                for key, asset in assets.items()
                if isinstance(asset, dict) and asset.get("verified") is not None
            }
            if set(files) != verified_ids:
                raise EditorError("INVALID_BUNDLE", "media entries must match verified assets")
            for asset in assets.values():
                if not isinstance(asset, dict):
                    raise EditorError("INVALID_BUNDLE", "project asset must be an object")
                asset["verified"] = None
            project = Project.model_validate(raw)
            validate_timeline(project)
            for asset_id, name in files.items():
                if (
                    not isinstance(name, str)
                    or "\\" in name
                    or name != f"media/{asset_id}{Path(name).suffix}"
                    or Path(name).suffix.lower() not in ALLOWED_SUFFIXES
                ):
                    raise EditorError("INVALID_BUNDLE", "invalid media entry name")
                archive.getinfo(name)
            if set(names) != {"project.json", *files.values()}:
                raise EditorError("INVALID_BUNDLE", "unexpected archive entries")
            parent.mkdir(parents=True, exist_ok=True)
            if not parent.resolve().is_relative_to(media.media_root):
                raise EditorError(
                    "MEDIA_NOT_ALLOWED", "bundle directory lies outside the media root", 403
                )
            if (
                sum(entry.file_size for entry in entries) + (64 << 20)
                > shutil.disk_usage(parent).free
            ):
                raise EditorError(
                    "INSUFFICIENT_SPACE", "not enough disk space to import the bundle", 507
                )
            folder = Path(tempfile.mkdtemp(prefix="import-", dir=parent))
            probes = []
            for asset_id, name in files.items():
                asset = project.assets[asset_id]
                target = folder / (asset_id + Path(name).suffix.lower())
                with archive.open(name) as incoming, target.open("wb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing, 1 << 20)
                probe = media.import_file(str(target), persist=False)
                if probe.verified.kind != asset.kind:
                    raise EditorError("INVALID_BUNDLE", "media kind does not match the asset")
                probes.append(probe)
                asset.reference = f"probe://{probe.id}"
                asset.verified = probe.verified
                asset.duration_ticks = probe.verified.duration_ticks or None
            result = store.import_bundle(request, project, probes)
            keep = not result.replayed
            return result
    except (
        zipfile.BadZipFile,
        KeyError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValidationError,
        RuntimeError,
        NotImplementedError,
    ):
        raise EditorError("INVALID_BUNDLE", "not a valid AgentCut bundle", 422) from None
    except OSError:
        raise EditorError(
            "STORAGE_UNAVAILABLE",
            "bundle file operation failed; retry with the same request_id",
            503,
        ) from None
    finally:
        if folder is not None and not keep:
            # This path was generated here; never delete a path supplied by the package.
            if folder.resolve().parent != parent.resolve():
                raise RuntimeError("bundle cleanup escaped its import directory")
            shutil.rmtree(folder)
