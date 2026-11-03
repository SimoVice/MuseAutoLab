"""Opt-in durable storage for trusted server-created project sessions."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from threading import RLock

_file_lock = RLock()
_pending_commits: set[str] = set()


def library_directory() -> str | None:
    return os.environ.get("MUSEAUTOLAB_LIBRARY_DIRECTORY", "").strip() or None


def configured() -> bool:
    if database_path() and library_directory():
        raise RuntimeError("Choose either SQLite or a JSON project directory, not both.")
    if os.environ.get("MUSEAUTOLAB_MODAL_VOLUME_NAME", "").strip() and not library_directory():
        raise RuntimeError("Modal storage requires MUSEAUTOLAB_LIBRARY_DIRECTORY.")
    return bool(database_path() or library_directory())


@lru_cache
def _modal_volume(name: str):
    import modal

    return modal.Volume.from_name(name)


def _commit_volume() -> None:
    name = os.environ.get("MUSEAUTOLAB_MODAL_VOLUME_NAME", "").strip()
    if name:
        _modal_volume(name).commit()


def _directory() -> Path:
    path = Path(library_directory()).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _project_file(project_id: str) -> Path:
    # An identifier from a URL must never become a path supplied by the client.
    return _directory() / (sha256(project_id.encode("utf-8")).hexdigest() + ".json")


def _read_record(path: Path) -> dict | None:
    try:
        with path.open(encoding="utf-8") as source:
            record = json.load(source)
    except FileNotFoundError:
        return None
    if record.get("schema_version") != 1:
        raise RuntimeError("The stored project format is unsupported.")
    return record


def _metadata(record: dict) -> dict:
    return {key: record[key] for key in ("id", "title", "revision", "status", "updated_at")}


def _commit_directory(directory: str) -> None:
    if directory in _pending_commits:
        # The file is closed before committing; don't rely on shutdown commits.
        _commit_volume()
        _pending_commits.discard(directory)


def _persist_file(payload: dict, title: str | None) -> dict:
    """Single-writer storage: never use overlapping containers or rolling writers.

    The mounted Volume is current when a container starts. No reload is performed
    while it runs: another writer could invalidate the process-local sessions.
    Commit failures propagate to the caller; an unacknowledged write may persist.
    """
    project = payload["project"]
    # Round-trip also rejects non-finite data before touching the existing file.
    payload = json.loads(json.dumps(payload, allow_nan=False))
    with _file_lock:
        path = _project_file(project["id"])
        previous = _read_record(path)
        if previous and previous["revision"] > project["revision"]:
            _commit_directory(str(path.parent))
            return _metadata(previous)
        record = {
            "schema_version": 1, "id": project["id"],
            "title": title if title is not None else previous["title"] if previous else None,
            "revision": project["revision"], "status": project["status"],
            "updated_at": previous["updated_at"] if previous else "",
            "payload": payload,
        }
        if record != previous:
            record["updated_at"] = datetime.now(timezone.utc).isoformat()
            descriptor, temporary = tempfile.mkstemp(prefix=".project-", dir=path.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
                    json.dump(record, destination, ensure_ascii=False, allow_nan=False)
                    destination.flush()
                    os.fsync(destination.fileno())
                os.replace(temporary, path)
                _pending_commits.add(str(path.parent))
            finally:
                Path(temporary).unlink(missing_ok=True)
        _commit_directory(str(path.parent))
        return _metadata(record)


def database_path() -> str | None:
    return os.environ.get("MUSEAUTOLAB_DATABASE_PATH", "").strip() or None


@contextmanager
def _connect():
    path = database_path()
    if not path:
        raise RuntimeError("The project library is not configured.")
    Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(Path(path).expanduser()), timeout=15)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("""CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY, title TEXT, revision INTEGER NOT NULL,
            status TEXT NOT NULL, updated_at TEXT NOT NULL, payload TEXT NOT NULL
        )""")
        with connection:
            yield connection
    finally:
        connection.close()


def persist(payload: dict, *, title: str | None = None) -> dict | None:
    """Store a session under its live ID; callers hold its mutation lock."""
    if not configured():
        return None
    if library_directory():
        return _persist_file(payload, title)
    project = payload["project"]
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True)
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        connection.execute("""INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              title=COALESCE(excluded.title, projects.title),
              revision=excluded.revision, status=excluded.status,
              updated_at=CASE WHEN projects.payload != excluded.payload
                OR (excluded.title IS NOT NULL AND projects.title IS NOT excluded.title)
                THEN excluded.updated_at ELSE projects.updated_at END,
              payload=excluded.payload
            WHERE excluded.revision >= projects.revision""",
            (project["id"], title, project["revision"], project["status"], now, encoded))
        row = connection.execute(
            "SELECT id,title,revision,status,updated_at FROM projects WHERE id=?",
            (project["id"],),
        ).fetchone()
    return dict(row)


def load(project_id: str) -> dict | None:
    if not configured():
        return None
    if library_directory():
        with _file_lock:
            record = _read_record(_project_file(project_id))
            return record["payload"] if record and record["id"] == project_id else None
    with _connect() as connection:
        row = connection.execute(
            "SELECT payload FROM projects WHERE id=?", (project_id,)
        ).fetchone()
    return json.loads(row["payload"]) if row else None


def entries() -> list[dict]:
    if not configured():
        return []
    if library_directory():
        with _file_lock:
            records = [_read_record(path) for path in _directory().glob("*.json")]
            result = [_metadata(record) for record in records if record and record["title"]]
        return sorted(result, key=lambda item: (item["updated_at"], item["id"]), reverse=True)
    with _connect() as connection:
        rows = connection.execute("""SELECT id,title,revision,status,updated_at FROM projects
            WHERE title IS NOT NULL ORDER BY updated_at DESC, id""").fetchall()
    return [dict(row) for row in rows]


def entry(project_id: str) -> dict | None:
    return next((item for item in entries() if item["id"] == project_id), None)
