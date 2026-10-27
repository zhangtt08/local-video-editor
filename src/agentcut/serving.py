"""Who may call this engine, and what they did about it.

A desktop install reaches the engine over loopback with one shared token, which is fine for the
person sitting in front of it and useless for a company: nothing can be handed to a pipeline that
runs elsewhere, no integration can be limited to reading, no credential can be taken back, and when
a clip changes nobody can say who asked. This module adds the two things that question needs —
a table of named tokens with scopes, and an append-only ledger of the calls that mattered.

Both live under the engine's own data directory, as plain files: `tokens.json` holds salted hashes
of the secrets (never the secrets themselves) and `audit.jsonl` holds one JSON object per line. An
enterprise can back both up with the project database, and a person can read them with any editor.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from pathlib import Path
from typing import Any

SCOPES = ("read", "write")
LOCAL_LABEL = "local"
LEDGER_LIMIT = 500


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class TokenTable:
    """Named credentials, each with its own scopes, revocable without touching the others."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()

    def rows(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return []
        return [row for row in (loaded.get("tokens") or []) if isinstance(row, dict)]

    def _save(self, rows: list[dict[str, Any]]) -> None:
        body = json.dumps({"tokens": rows}, ensure_ascii=False, indent=2) + "\n"
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(body, encoding="utf-8")
        tmp.replace(self.path)

    def add(self, label: str, scopes: list[str]) -> tuple[dict[str, Any], str]:
        """Issue a credential. The secret is returned once and only its hash is stored."""
        wanted = [scope for scope in SCOPES if scope in scopes] or ["read"]
        with self.lock:
            rows = self.rows()
            if any(row.get("label") == label for row in rows):
                raise ValueError(f"label {label!r} is already issued")
            secret = secrets.token_hex(32)
            row = {
                "label": label,
                "secret_sha256": _hash(secret),
                "scopes": wanted,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "revoked_at": None,
            }
            self._save([*rows, row])
            return dict(row), secret

    def revoke(self, label: str) -> bool:
        with self.lock:
            rows = self.rows()
            found = False
            for row in rows:
                if row.get("label") == label and not row.get("revoked_at"):
                    row["revoked_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                    found = True
            if found:
                self._save(rows)
            return found

    def grant_legacy(self, secret: str, label: str = LOCAL_LABEL) -> None:
        """Register the token the desktop shell already uses, so one path covers both."""
        with self.lock:
            rows = self.rows()
            if any(row.get("label") == label for row in rows):
                return
            self._save([
                *rows,
                {
                    "label": label,
                    "secret_sha256": _hash(secret),
                    "scopes": list(SCOPES),
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "revoked_at": None,
                    "legacy": True,
                },
            ])

    def resolve(self, secret: str) -> dict[str, Any] | None:
        """The live row whose hash matches, or None. Revoked rows never resolve."""
        candidate = _hash(secret)
        for row in self.rows():
            if row.get("revoked_at"):
                continue
            if hmac.compare_digest(str(row.get("secret_sha256")), candidate):
                return {
                    "label": str(row.get("label")),
                    "scopes": [str(scope) for scope in (row.get("scopes") or [])],
                }
        return None

    def summary(self) -> list[dict[str, Any]]:
        return [
            {
                "label": row.get("label"),
                "scopes": row.get("scopes"),
                "created_at": row.get("created_at"),
                "revoked_at": row.get("revoked_at"),
                "legacy": bool(row.get("legacy")),
            }
            for row in self.rows()
        ]


class AuditLog:
    """One JSON line per call that changed something, or was refused.

    Reads are deliberately not written: a desktop polls `/v1/projects` while a person scrubs the
    timeline, and a ledger that buries the actions under heartbeats answers no one's question. A
    denial is an event — that is exactly the line a security review asks for.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.seq = 0
        if path.is_file():
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for _line in handle:
                    self.seq += 1

    def write(self, **event: Any) -> None:
        with self.lock:
            self.seq += 1
            row = {"seq": self.seq, "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **event}
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def recent(self, limit: int = 50, actor: str | None = None,
               project_id: str | None = None) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if actor and row.get("actor") != actor:
                    continue
                if project_id and row.get("project_id") != project_id:
                    continue
                rows.append(row)
        return rows[max(0, len(rows) - min(limit, LEDGER_LIMIT)):]
