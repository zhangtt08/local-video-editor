"""Durable application facade. SQLite owns snapshots, audit, and retry receipts."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .contracts import (
    MAX_TICKS,
    PATH_BOX_SCHEMA_VERSION,
    SCHEMA_VERSION,
    BundleImport,
    CreateProject,
    EditBatch,
    EditorError,
    MediaProbe,
    MutationResult,
    Project,
    ProjectUpdate,
    RestoreProject,
)
from .masks import fit_box
from .timeline import apply_commands, validate_timeline


def _fitted(project: Project) -> Project:
    """Give a path mask drawn before v13 the box it was actually drawn in.

    Rows written earlier stored the shape's default box, which meant nothing to a free-form mask.
    Fitting the box to the outline's bounds is the identity for how those rows rendered, and it is
    what lets the box be animated from here on.

    The cut-off is the schema that introduced the box, not the current one: every later field (v14's
    fade windows) reads from its own default, so re-fitting a row that was already fitted would just
    be wasted work pretending to be a migration.
    """
    if project.schema_version >= PATH_BOX_SCHEMA_VERSION:
        return project
    groups = [project.clips] + [sequence.clips for sequence in project.sequences.values()]
    for clips in groups:
        for clip in clips.values():
            if clip.mask is not None and clip.mask.shape == "path":
                clip.mask = fit_box(clip.mask)
    return project


class ProjectStore:
    def __init__(self, path: Path, media=None):
        self.path = path
        self.media = media
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise RuntimeError(f"Unsupported database version: {version}")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, document TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS history (
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    revision INTEGER NOT NULL, document TEXT NOT NULL,
                    request_id TEXT NOT NULL, operation TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(project_id, revision)
                );
                CREATE TABLE IF NOT EXISTS receipts (
                    scope TEXT NOT NULL, request_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, response TEXT NOT NULL,
                    PRIMARY KEY(scope, request_id)
                );
                PRAGMA user_version=2;
            """)

    @contextmanager
    def connection(self, write: bool = False):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            # ponytail: one SQLite writer; move to a server DB if multi-user write load demands it.
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _load(db, project_id: str, revision: int | None = None) -> Project:
        if revision is None:
            row = db.execute("SELECT document FROM projects WHERE id=?", (project_id,)).fetchone()
        else:
            row = db.execute(
                "SELECT document FROM history WHERE project_id=? AND revision=?",
                (project_id, revision),
            ).fetchone()
        if row is None:
            raise EditorError(
                "NOT_FOUND",
                "project or revision does not exist",
                404,
                project_id=project_id,
                revision=revision,
            )
        return _fitted(Project.model_validate_json(row["document"]))

    @staticmethod
    def _replay(
        db, scope: str, request_id: str, fingerprint: str, compatible=()
    ) -> MutationResult | None:
        row = db.execute(
            "SELECT fingerprint,response FROM receipts WHERE scope=? AND request_id=?",
            (scope, request_id),
        ).fetchone()
        if row is None:
            return None
        if row["fingerprint"] != fingerprint and row["fingerprint"] not in compatible:
            raise EditorError(
                "IDEMPOTENCY_CONFLICT", "request_id was used with a different payload", 409
            )
        return MutationResult.model_validate_json(row["response"]).model_copy(
            update={"replayed": True}
        )

    @staticmethod
    def _fingerprint(operation: str, request, normalize_text: bool = True) -> str:
        payload = request.model_dump(exclude={"dry_run"})

        def strip_bezier_defaults(node):
            if isinstance(node, dict):
                if "interpolation" in node and "at_ticks" in node and node.get("bezier") is None:
                    node.pop("bezier", None)
                if "exposure" in node and not node.get("grade"):
                    node.pop("grade", None)
                if "kind" in node and node.get("mix") == 1.0:
                    node.pop("mix", None)
                if "center_x" in node and node.get("vertices") is None:
                    node.pop("vertices", None)
                # 1.69 gave a clip a stabilisation record. A payload that never mentions one must
                # hash as the pre-1.69 payload it was, or every receipt for a `clip.add` written
                # before this release splits in two on retry.
                if "asset_id" in node and node.get("stabilization") is None:
                    node.pop("stabilization", None)
                # 1.90 gave a clip its fade windows. A payload that never mentions one must hash as
                # the pre-1.90 payload it was, for the same reason as the record above: otherwise
                # every receipt written before this release splits in two when it is retried.
                if "asset_id" in node and node.get("fade") is None:
                    node.pop("fade", None)
                # 1.118 gave a clip its outline keyframes, and an empty table is exactly the state a
                # pre-1.118 payload had: dropping it keeps those receipts replaying.
                if "asset_id" in node and not node.get("mask_shape_keys"):
                    node.pop("mask_shape_keys", None)
                for value in node.values():
                    strip_bezier_defaults(value)
            elif isinstance(node, list):
                for value in node:
                    strip_bezier_defaults(value)

        strip_bezier_defaults(payload)
        if payload.get("sequence_id") is None:
            payload.pop("sequence_id", None)
        # v3 additive defaults must not change fingerprints of v1/v2 receipts.
        from .contracts import TextStyle

        # Derived from the model, so the next style field a text layer grows cannot silently split
        # an old receipt in two. A field that arrived after a payload's era was not asked for, so it
        # must not enter the hash: `normalize_text=True` is the current form (only
        # body/font_size/color were ever sent at first), and the `False` form is the 1.7 comparison,
        # which did send align/box and must keep them.
        text_era = {"body", "font_size", "color"} | (set() if normalize_text else {"align", "box"})
        text_dropped = {name for name in TextStyle.model_fields if name not in text_era}
        # Only a field sitting at its default is "not part of what was asked for"; a payload that
        # deliberately set the same value as another field's default still hashes as it was sent.
        text_defaults = tuple(
            (name, TextStyle.model_fields[name].default) for name in sorted(text_dropped)
        )
        # Same era treatment for the six effect keys that existed before 1.64 added `blur`.
        from .contracts import ClipEffects

        spatial_keys = {"x", "y", "scale", "rotation", "opacity", "gain"}
        effects_added = tuple(
            (name, field.default)
            for name, field in sorted(ClipEffects.model_fields.items(), key=lambda e: e[0])
            if name not in spatial_keys
        )
        effects_defaults = {
            name: field.default
            for name, field in ClipEffects.model_fields.items()
            if name in spatial_keys
        }
        for command in payload.get("commands", []):
            if (
                command.get("op") == "asset.register"
                and command["asset"].get("sequence_id") is None
            ):
                command["asset"].pop("sequence_id", None)
            clips = (
                command.get("clips", [])
                if command.get("op") == "clips.add"
                else [command["clip"]]
                if "clip" in command
                else []
            )
            for clip in clips:
                text = clip.get("text")
                if text:
                    for field, default in text_defaults:
                        if text.get(field) == default:
                            text.pop(field, None)
                for field, default in (
                    ("group_id", None),
                    ("link_id", None),
                    ("link_source_offset_ticks", 0),
                    ("embedded_audio", True),
                    ("mask", None),
                    ("speed_curve", None),
                ):
                    if clip.get(field) == default:
                        clip.pop(field, None)
            if command.get("op") == "clip.text":
                for field, default in text_defaults:
                    if command["text"].get(field) == default:
                        command["text"].pop(field, None)
            if command.get("op") in {"clip.add", "clip.insert", "clip.overwrite"}:
                if command["clip"].get("transition_in") is None:
                    command["clip"].pop("transition_in", None)
            if command.get("op") == "clip.add":
                clip = command["clip"]
                if clip.get("speed_percent") == 100:
                    clip.pop("speed_percent", None)
                if clip.get("text") is None:
                    clip.pop("text", None)
                if not clip.get("keyframes"):
                    clip.pop("keyframes", None)
                if not clip.get("animation_offset_ticks"):
                    clip.pop("animation_offset_ticks", None)
                from .contracts import ClipColor, ClipEffects

                # `blur` arrived in 1.64, and by this point the payload has already been re-dumped
                # through the model, so a receipt written before the field existed would pick up a
                # seventh key and split in two. Same era rule as the text style above: a key the
                # caller's version could not have named is not part of what was asked for as long as
                # it sits at its default — and it has to be dropped even when another effect *was*
                # asked for, which is the case an all-or-nothing comparison misses.
                effects = clip.get("effects")
                if effects is not None:
                    for name, default in effects_added:
                        if effects.get(name) == default:
                            effects.pop(name, None)
                    if not effects or effects == effects_defaults:
                        clip.pop("effects", None)
                if clip.get("color") == {
                    key: value for key, value in ClipColor().model_dump().items() if key != "grade"
                }:
                    clip.pop("color", None)
            if command.get("op") == "clip.trim" and command.get("position_ticks") is None:
                command.pop("position_ticks", None)
            if (
                command.get("op") in {"clip.trim", "clip.trim_linked"}
                and command.get("ripple") is False
            ):
                command.pop("ripple", None)
            if command.get("op") == "track.add" and not command["track"].get("locked"):
                command["track"].pop("locked", None)
            if command.get("op") == "track.update" and command.get("locked") is None:
                command.pop("locked", None)
            if command.get("op") == "track.add" and command["track"].get("blend_mode") == "normal":
                command["track"].pop("blend_mode", None)
            if command.get("op") == "track.update" and command.get("blend_mode") is None:
                command.pop("blend_mode", None)
        canonical = json.dumps([operation, payload], sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def bundle_replay(self, request: BundleImport) -> MutationResult | None:
        with self.connection() as db:
            return self._replay(
                db, "bundle-import", request.request_id, self._fingerprint("bundle.import", request)
            )

    def import_bundle(
        self, request: BundleImport, project: Project, probes: list[MediaProbe]
    ) -> MutationResult:
        """Commit a prepared snapshot, probe records, history and receipt together."""
        fingerprint = self._fingerprint("bundle.import", request)
        with self.connection(write=True) as db:
            replay = self._replay(db, "bundle-import", request.request_id, fingerprint)
            if replay:
                return replay
            candidate = Project.model_validate(
                {
                    **project.model_dump(),
                    "id": uuid4().hex,
                    "revision": 0,
                    "schema_version": SCHEMA_VERSION,
                }
            )
            validate_timeline(candidate)
            prepared = {probe.id: probe for probe in probes}
            for asset in candidate.assets.values():
                if asset.verified is not None:
                    probe = prepared.get(asset.verified.probe_id)
                    if probe is None or probe.verified != asset.verified:
                        raise EditorError("INVALID_PROBE", "bundle needs server-probed media")
            if probes and (self.media is None or self.media.db_path != self.path):
                raise EditorError(
                    "MEDIA_UNAVAILABLE", "bundle media must use the project database", 503
                )
            for probe in probes:
                db.execute(
                    "INSERT INTO media_probes(id,path,document) VALUES(?,?,?)",
                    (probe.id, probe.verified.path, probe.model_dump_json()),
                )
            result = MutationResult(project=candidate, committed=True)
            self._persist(
                db, candidate, result, "bundle.import", request, "bundle-import", fingerprint
            )
            return result

    @staticmethod
    def _persist(
        db,
        project: Project,
        result: MutationResult,
        operation: str,
        request,
        scope: str,
        fingerprint: str,
    ):
        document = project.model_dump_json()
        db.execute(
            "INSERT INTO projects(id,document) VALUES(?,?) "
            "ON CONFLICT(id) DO UPDATE SET document=excluded.document",
            (project.id, document),
        )
        db.execute(
            "INSERT INTO history(project_id,revision,document,request_id,operation,payload) "
            "VALUES(?,?,?,?,?,?)",
            (
                project.id,
                project.revision,
                document,
                request.request_id,
                operation,
                request.model_dump_json(),
            ),
        )
        db.execute(
            "INSERT INTO receipts(scope,request_id,fingerprint,response) VALUES(?,?,?,?)",
            (scope, request.request_id, fingerprint, result.model_dump_json()),
        )

    def create(self, request: CreateProject) -> MutationResult:
        fingerprint = self._fingerprint("create", request)
        with self.connection(write=True) as db:
            replay = self._replay(db, "create", request.request_id, fingerprint)
            if replay:
                return replay
            project = Project(id=uuid4().hex, name=request.name, settings=request.settings)
            result = MutationResult(project=project, committed=True)
            self._persist(db, project, result, "create", request, "create", fingerprint)
            return result

    def get(self, project_id: str, revision: int | None = None) -> Project:
        with self.connection() as db:
            return self._load(db, project_id, revision)

    def list_projects(self, limit: int = 100, offset: int = 0) -> list[dict]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT id,json_extract(document,'$.name') AS name,"
                "json_extract(document,'$.revision') AS revision "
                "FROM projects ORDER BY id LIMIT ? OFFSET ?",
                (limit, offset),
            )
            return [dict(row) for row in rows]

    def history(self, project_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
        with self.connection() as db:
            self._load(db, project_id)
            rows = db.execute(
                "SELECT revision,request_id,operation,created_at FROM history "
                "WHERE project_id=? ORDER BY revision DESC LIMIT ? OFFSET ?",
                (project_id, limit, offset),
            )
            return [dict(row) for row in rows]

    def _authorize_probes(self, commands) -> None:
        """asset.import may only attach a probe this server issued and recorded."""
        for command in commands:
            if command.op == "asset.register" and command.asset.verified is not None:
                raise EditorError(
                    "INVALID_PROBE",
                    "asset.register accepts metadata only; use asset.import for verified media",
                )
        if self.media is None:
            for command in commands:
                if command.op == "asset.import":
                    raise EditorError(
                        "MEDIA_UNAVAILABLE",
                        "media engine is disabled, so asset.import is unavailable",
                        503,
                    )
            return
        for command in commands:
            if command.op != "asset.import":
                continue
            # The client echo is untrusted: whatever fields it claims, persist the
            # server-recorded probe so kind/duration/codec cannot be forged.
            command.verified = self.media.get_probe(command.probe_id).verified

    def update_project(self, project_id: str, request: ProjectUpdate) -> MutationResult:
        fingerprint = self._fingerprint("update", request)
        with self.connection(write=True) as db:
            replay = self._replay(db, project_id, request.request_id, fingerprint)
            if replay:
                return replay
            current = self._load(db, project_id)
            if current.revision != request.expected_revision:
                raise EditorError(
                    "REVISION_CONFLICT",
                    "read the latest project before editing",
                    409,
                    expected_revision=request.expected_revision,
                    actual_revision=current.revision,
                )
            updates = request.model_dump(
                exclude={"request_id", "expected_revision"}, exclude_none=True, mode="json"
            )
            # Validate the merged document rather than copying typed fields with raw dicts in
            # them: a `model_copy` leaves `settings` a dict for one step, which makes Pydantic
            # warn while serializing the half-built project.
            candidate = Project.model_validate(
                {**current.model_dump(), **updates, "revision": current.revision + 1}
            )
            validate_timeline(candidate)
            result = MutationResult(
                project=candidate, committed=True, base_revision=current.revision
            )
            self._persist(db, candidate, result, "update", request, project_id, fingerprint)
            return result

    def mutate(self, project_id: str, request: EditBatch | RestoreProject) -> MutationResult:
        operation = "edit" if isinstance(request, EditBatch) else "restore"
        fingerprint = self._fingerprint(operation, request)
        dry_run = isinstance(request, EditBatch) and request.dry_run
        with self.connection(write=True) as db:
            # 1.7 receipts included additive text defaults; earlier receipts did not.
            compatible = (
                (self._fingerprint(operation, request, normalize_text=False),)
                if isinstance(request, EditBatch)
                else ()
            )
            replay = self._replay(db, project_id, request.request_id, fingerprint, compatible)
            if replay:
                if dry_run:
                    raise EditorError(
                        "REQUEST_ALREADY_COMMITTED", "use a fresh id for a new preview", 409
                    )
                return replay
            current = self._load(db, project_id)
            if current.revision != request.expected_revision:
                raise EditorError(
                    "REVISION_CONFLICT",
                    "read the latest project before editing",
                    409,
                    expected_revision=request.expected_revision,
                    actual_revision=current.revision,
                )
            if current.revision == MAX_TICKS:
                raise EditorError("REVISION_OVERFLOW", "revision limit reached", 409)
            if operation == "edit":
                self._authorize_probes(request.commands)
            candidate = (
                apply_commands(current, request.commands, request.sequence_id)
                if operation == "edit"
                else self._load(db, project_id, request.target_revision)
            )
            candidate = candidate.model_copy(
                update={"revision": current.revision + 1, "schema_version": SCHEMA_VERSION}
            )
            validate_timeline(candidate)
            result = MutationResult(
                project=candidate, committed=not dry_run, base_revision=current.revision
            )
            if not dry_run:
                self._persist(db, candidate, result, operation, request, project_id, fingerprint)
            return result

    def ping(self):
        with self.connection() as db:
            db.execute("SELECT 1 FROM projects LIMIT 1").fetchone()
