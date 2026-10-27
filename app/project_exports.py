"""Project file export orchestration (concept only).

Three real stages: CAD, documents, archive. No timer-faked progress:
``completed_stages`` advances only after actual work completes.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import re
import threading
import zipfile
from copy import deepcopy
from uuid import uuid4

from app.assembly import assembly_steps, build_document_files
from app.cad_exports import build_cad_files

TOTAL_STAGES = 3
MAX_PACKAGE_BYTES = 50 * 1024 * 1024
MAX_RETAINED_JOBS_PER_PROJECT = 3

_cad_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_background_tasks: set[asyncio.Task] = set()


class ExportError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _sanitize_error(exc: BaseException) -> str:
    return "Project file generation failed. Retry generation or check the local server log."


def _input_sha256(project: dict) -> str:
    canonical = json.dumps(project, sort_keys=True, allow_nan=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _ensure_supported(project: dict) -> None:
    if not isinstance(project, dict) or project.get("status") != "confirmed":
        raise ExportError(409, "Project files require a confirmed project.")
    plan = project.get("plan") or {}
    if plan.get("status") != "ready":
        raise ExportError(409, "Project files require a ready preparation plan.")
    design = project.get("design") or {}
    if design.get("constraint_status") == "infeasible":
        raise ExportError(409, "Project files require a feasible workspace width.")


def _check_coherence(project: dict, job: dict) -> None:
    if project.get("id") != job["project_id"]:
        raise ExportError(404, "Export job not found for this project.")
    if project.get("revision") != job["revision"]:
        raise ExportError(409, "Export is stale for the current project revision.")
    _ensure_supported(project)


def _media_type(name: str) -> str:
    lower = name.lower()
    if lower.endswith(".json"):
        return "application/json"
    if lower.endswith(".html"):
        return "text/html"
    if lower.endswith(".csv"):
        return "text/csv"
    if lower.endswith(".py"):
        return "text/x-python"
    if lower.endswith(".md"):
        return "text/markdown"
    if lower.endswith(".step"):
        return "model/step"
    if lower.endswith(".stl"):
        return "model/stl"
    if lower.endswith(".svg"):
        return "image/svg+xml"
    if lower.endswith(".zip"):
        return "application/zip"
    return "application/octet-stream"


def _ensure_safe_name(name: str) -> None:
    if not isinstance(name, str) or not name or len(name) > 256:
        raise ValueError(f"Unsafe file name: {name!r}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]*", name):
        raise ValueError(f"Unsafe file name: {name!r}")
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"Unsafe file name: {name!r}")


def _ensure_safe_files(files: dict[str, bytes]) -> None:
    total = 0
    for name, payload in files.items():
        _ensure_safe_name(name)
        if not isinstance(payload, (bytes, bytearray)):
            raise ValueError(f"File payload must be bytes: {name}")
        total += len(payload)
    if total > MAX_PACKAGE_BYTES:
        raise ValueError("Generated package exceeds the 50 MB limit.")


def _public_metadata(job: dict) -> dict:
    return {
        "id": job["id"],
        "project_id": job["project_id"],
        "revision": job["revision"],
        "status": job["status"],
        "stage": job["stage"],
        "completed_stages": job["completed_stages"],
        "total_stages": TOTAL_STAGES,
        "error": job["error"],
        "files": deepcopy(job["files"]),
        "assembly_steps": deepcopy(job["assembly_steps"]),
        "download_url": job["download_url"],
    }


def _prune_project_jobs(project_id: str) -> None:
    ids = [jid for jid, job in _jobs.items() if job["project_id"] == project_id]
    if len(ids) <= MAX_RETAINED_JOBS_PER_PROJECT:
        return
    # Keep active jobs and the newest ready jobs.
    ids.sort(key=lambda jid: _jobs[jid]["created_seq"])
    while len(ids) > MAX_RETAINED_JOBS_PER_PROJECT:
        candidate = None
        for jid in ids:
            if _jobs[jid]["status"] in ("queued", "running"):
                continue
            candidate = jid
            break
        if candidate is None:
            return
        ids.remove(candidate)
        del _jobs[candidate]


_seq = 0


def _build_archive_bytes(payload_files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(payload_files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, bytes(payload_files[name]))
    return buffer.getvalue()


async def _run_job(job_id: str) -> None:
    job = _jobs.get(job_id)
    if job is None:
        return
    try:
        job["status"] = "running"
        job["stage"] = "cad"
        snapshot = job["snapshot"]
        loop = asyncio.get_running_loop()

        def _cad() -> dict:
            with _cad_lock:
                return build_cad_files(deepcopy(snapshot))

        cad_files = await loop.run_in_executor(None, _cad)
        job["completed_stages"] = 1
        job["stage"] = "documents"

        def _docs() -> tuple[dict, list]:
            docs = build_document_files(deepcopy(snapshot))
            steps = assembly_steps(deepcopy(snapshot))
            return docs, steps

        doc_files, steps = await loop.run_in_executor(None, _docs)
        job["completed_stages"] = 2
        job["stage"] = "archive"

        def _archive() -> tuple[dict[str, bytes], bytes]:
            if not isinstance(cad_files, dict) or not isinstance(doc_files, dict):
                raise ValueError("Generators must return filename to bytes mappings.")
            project_payload = json.dumps(
                {"schema_version": 1, "project": snapshot}, sort_keys=True
            ).encode("utf-8")
            interim: dict[str, bytes] = dict(cad_files)
            if set(cad_files).intersection(doc_files) or {
                "project.json",
                "manifest.json",
            }.intersection(set(cad_files) | set(doc_files)):
                raise ValueError("Generated filenames overlap.")
            interim.update(doc_files)
            interim["project.json"] = project_payload
            _ensure_safe_files(interim)
            manifest = {
                "schema_version": 1,
                "project_id": snapshot.get("id"),
                "revision": snapshot.get("revision"),
                "input_sha256": _input_sha256(snapshot),
                "files": [
                    {
                        "name": name,
                        "size": len(interim[name]),
                        "sha256": hashlib.sha256(interim[name]).hexdigest(),
                    }
                    for name in sorted(interim)
                ],
                "status": "concept",
                "limitations": [
                    "Concept geometry only; not fabrication-ready.",
                    "Interfaces and mounts are unverified.",
                ],
            }
            manifest_payload = json.dumps(manifest, sort_keys=True).encode("utf-8")
            all_files = dict(interim)
            all_files["manifest.json"] = manifest_payload
            _ensure_safe_files(all_files)
            archive = _build_archive_bytes(all_files)
            if len(archive) > MAX_PACKAGE_BYTES:
                raise ValueError("Generated package exceeds the 50 MB limit.")
            return all_files, archive

        all_files, archive = await loop.run_in_executor(None, _archive)
        # Stale outputs must never become downloadable: re-check revision coherence
        # against the latest known project is done on access; here just store.
        job["file_bytes"] = {name: bytes(payload) for name, payload in all_files.items()}
        job["archive_bytes"] = archive
        job["files"] = [
            {
                "name": name,
                "size": len(all_files[name]),
                "media_type": _media_type(name),
                "sha256": hashlib.sha256(all_files[name]).hexdigest(),
            }
            for name in sorted(all_files)
        ]
        job["completed_stages"] = 3
        job["stage"] = "done"
        job["status"] = "ready"
        job["download_url"] = f"/api/projects/{job['project_id']}/exports/{job['id']}/download"
    except Exception as exc:  # noqa: BLE001 - sanitized into job state
        logging.getLogger(__name__).exception("Export generation failed for job %s", job_id)
        job["status"] = "failed"
        job["stage"] = "failed"
        job["error"] = _sanitize_error(exc)
        job["file_bytes"] = {}
        job["archive_bytes"] = b""
        job["files"] = []
        job["download_url"] = None


async def start_export(project: dict) -> dict:
    global _seq
    _ensure_supported(project)
    project_id = project.get("id")
    revision = project.get("revision")
    # Duplicate active job guard and same-revision cache.
    for job in _jobs.values():
        if job["project_id"] != project_id:
            continue
        if job["status"] in ("queued", "running"):
            if job["revision"] == revision:
                return _public_metadata(job)
            raise ExportError(409, "Another export is already running for this project.")
    for job in _jobs.values():
        if (
            job["project_id"] == project_id
            and job["revision"] == revision
            and job["status"] == "ready"
        ):
            return _public_metadata(job)
    try:
        initial_steps = assembly_steps(deepcopy(project))
        initial_steps = [dict(s) if isinstance(s, dict) else s for s in initial_steps]
    except Exception as exc:  # noqa: BLE001
        raise ExportError(409, _sanitize_error(exc)) from None
    job_id = uuid4().hex
    _seq += 1
    job = {
        "id": job_id,
        "project_id": project_id,
        "revision": revision,
        "status": "queued",
        "stage": "queued",
        "completed_stages": 0,
        "total_stages": TOTAL_STAGES,
        "error": None,
        "files": [],
        "file_bytes": {},
        "archive_bytes": b"",
        "assembly_steps": initial_steps,
        "download_url": None,
        "snapshot": deepcopy(project),
        "created_seq": _seq,
    }
    _jobs[job_id] = job
    _prune_project_jobs(project_id)
    task = asyncio.create_task(_run_job(job_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    job["task"] = task
    return _public_metadata(job)


async def export_status(project: dict, job_id: str) -> dict:
    job = _jobs.get(job_id)
    if job is None:
        raise ExportError(404, "Export job not found.")
    _check_coherence(project, job)
    return _public_metadata(job)


async def export_archive(project: dict, job_id: str) -> bytes:
    job = _jobs.get(job_id)
    if job is None:
        raise ExportError(404, "Export job not found.")
    _check_coherence(project, job)
    if job["status"] != "ready":
        raise ExportError(409, "Export is not ready for download.")
    return bytes(job["archive_bytes"])


async def export_file(project: dict, job_id: str, name: str) -> bytes:
    job = _jobs.get(job_id)
    if job is None:
        raise ExportError(404, "Export job not found.")
    _check_coherence(project, job)
    if job["status"] != "ready":
        raise ExportError(409, "Export is not ready for download.")
    payload = job["file_bytes"].get(name)
    if payload is None:
        raise ExportError(404, "File is not part of this export.")
    return bytes(payload)


def media_type_for(name: str) -> str:
    return _media_type(name)
