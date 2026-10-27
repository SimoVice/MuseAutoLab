"""Async simulation job orchestration (MuJoCo engine runs in worker threads).

Real computation only: progress advances from the engine's on_progress callback
via loop.call_soon_threadsafe; no timer-faked progress. Ready means computation
finished; result["status"] may still be "blocked" (UI must distinguish).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from copy import deepcopy
from uuid import uuid4

from app.physics import build_simulation_files as _physics_build_files
from app.physics import simulate_project as _physics_simulate

VALID_SCENARIOS = ("nominal", "blocked_path")

SIMULATION_FILES = (
    "simulation/model.xml",
    "simulation/result.json",
    "simulation/trajectory.csv",
    "simulation/engine.py",
    "simulation/run.py",
    "simulation/README.md",
)

MAX_RETAINED_PER_PROJECT = 3

_jobs: dict[str, dict] = {}
_cache: dict[tuple[str, int, str], str] = {}
_engine_lock = threading.Lock()
_jobs_lock = threading.Lock()
_background_tasks: set[asyncio.Task] = set()

_log = logging.getLogger(__name__)


class SimulationError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _sanitize_error(exc: BaseException) -> str:
    _log.exception("Simulation job failed: %r", exc)
    return "Physics simulation failed. Retry generation or check the local server log."


def _ensure_scenario(scenario: str) -> str:
    if scenario not in VALID_SCENARIOS:
        raise SimulationError(422, f"Unknown scenario: {scenario!r}.")
    return scenario


def _ensure_supported(project: dict) -> None:
    if not isinstance(project, dict) or project.get("status") != "confirmed":
        raise SimulationError(409, "Physics simulation requires a confirmed project.")
    plan = project.get("plan") or {}
    if plan.get("status") != "ready":
        raise SimulationError(409, "Physics simulation requires a ready preparation plan.")
    design = project.get("design") or {}
    if design.get("constraint_status") == "infeasible":
        raise SimulationError(409, "Physics simulation requires a feasible workspace width.")


def _check_coherence(project: dict, job: dict) -> None:
    if project.get("id") != job["project_id"]:
        raise SimulationError(404, "Simulation job not found for this project.")
    if project.get("revision") != job["revision"]:
        raise SimulationError(409, "Simulation is stale for the current project revision.")
    _ensure_supported(project)


def _public_metadata(job: dict) -> dict:
    return {
        "id": job["id"],
        "project_id": job["project_id"],
        "revision": job["revision"],
        "scenario": job["scenario"],
        "status": job["status"],
        "stage": job["stage"],
        "completed_steps": job["completed_steps"],
        "total_steps": job["total_steps"],
        "error": job["error"],
        "result_url": job["result_url"],
        "summary": deepcopy(job["summary"]) if job.get("summary") is not None else None,
    }


def _prune_project(project_id: str) -> None:
    with _jobs_lock:
        ids = [jid for jid, job in _jobs.items() if job["project_id"] == project_id]
        ids.sort(key=lambda jid: _jobs[jid]["created_seq"])
        remaining = len(ids)
        for jid in ids:
            if remaining <= MAX_RETAINED_PER_PROJECT:
                break
            job = _jobs[jid]
            if job["status"] in ("queued", "running"):
                continue
            del _jobs[jid]
            remaining -= 1
            key = (job["project_id"], job["revision"], job["scenario"])
            if _cache.get(key) == jid:
                _cache.pop(key, None)


_seq = 0


def _simulate_blocking(snapshot: dict, scenario: str, progress_cb) -> dict:
    return _physics_simulate(deepcopy(snapshot), scenario=scenario, on_progress=progress_cb)


def _build_files_blocking(snapshot: dict, result: dict) -> dict[str, bytes]:
    files = _physics_build_files(deepcopy(snapshot), deepcopy(result))
    if set(files) != set(SIMULATION_FILES):
        raise ValueError("Simulation file set mismatch.")
    for name in SIMULATION_FILES:
        if not isinstance(files[name], (bytes, bytearray)):
            raise ValueError(f"Simulation file payload must be bytes: {name}")
    return {name: bytes(files[name]) for name in SIMULATION_FILES}


def _store_result(job: dict, result: dict, files: dict) -> None:
    """Publish all ready fields together while holding _jobs_lock."""
    job["result"] = deepcopy(result)
    job["files"] = dict(files)
    job["summary"] = deepcopy(result["metrics"])
    job["completed_steps"] = result.get("integration_steps", job["completed_steps"])
    job["total_steps"] = result.get("planned_integration_steps", job["total_steps"])
    job["stage"] = "done"
    job["status"] = "ready"
    job["error"] = None
    job["result_url"] = f"/api/projects/{job['project_id']}/simulations/{job['id']}/result"
    _cache[(job["project_id"], job["revision"], job["scenario"])] = job["id"]


async def _run_job(job_id: str) -> None:
    job = _jobs.get(job_id)
    if job is None:
        return
    loop = asyncio.get_running_loop()
    with _jobs_lock:
        job["status"] = "running"
        job["stage"] = "simulate"
    snapshot = job["snapshot"]
    scenario = job["scenario"]

    def _apply(stage: str, completed: int, total: int) -> None:
        with _jobs_lock:
            target = _jobs.get(job_id)
            if target is None or target["status"] not in ("queued", "running"):
                return
            target["stage"] = str(stage)
            target["completed_steps"] = int(completed)
            target["total_steps"] = int(total)

    def _on_progress(stage: str, completed_steps: int, total_steps: int) -> None:
        try:
            loop.call_soon_threadsafe(_apply, str(stage), int(completed_steps), int(total_steps))
        except RuntimeError:
            _apply(str(stage), int(completed_steps), int(total_steps))

    try:

        def _blocking() -> tuple[dict, dict[str, bytes]]:
            with _engine_lock:
                key = (job["project_id"], job["revision"], scenario)
                with _jobs_lock:
                    cached = _jobs.get(_cache.get(key, ""))
                    if cached is not None and cached["status"] == "ready":
                        result, files = deepcopy(cached["result"]), dict(cached["files"])
                    else:
                        result = None
                if result is None:
                    result = _simulate_blocking(snapshot, scenario, _on_progress)
                    files = _build_files_blocking(snapshot, result)
                with _jobs_lock:
                    _store_result(job, result, files)
            return result, files

        await loop.run_in_executor(None, _blocking)
        _prune_project(job["project_id"])
    except Exception as exc:  # noqa: BLE001
        with _jobs_lock:
            job["status"] = "failed"
            job["stage"] = "failed"
            job["error"] = _sanitize_error(exc)
            job["result"] = None
            job["files"] = {}
            job["summary"] = None
            job["result_url"] = None


async def start_simulation(project: dict, scenario: str = "nominal") -> dict:
    global _seq
    _ensure_scenario(scenario)
    _ensure_supported(project)
    project_id = project.get("id")
    revision = project.get("revision")
    with _jobs_lock:
        for job in _jobs.values():
            if job["project_id"] != project_id:
                continue
            if job["status"] in ("queued", "running"):
                if job["revision"] == revision and job["scenario"] == scenario:
                    return _public_metadata(job)
                raise SimulationError(
                    409, "Another simulation is already running for this project."
                )
        key = (project_id, revision, scenario)
        cached_id = _cache.get(key)
        if cached_id is not None:
            cached = _jobs.get(cached_id)
            if cached is not None and cached["status"] == "ready":
                return _public_metadata(cached)
            _cache.pop(key, None)
        # Reuse any ready job with same identity even if cache entry was pruned.
        for job in _jobs.values():
            if (
                job["project_id"] == project_id
                and job["revision"] == revision
                and job["scenario"] == scenario
                and job["status"] == "ready"
            ):
                _cache[key] = job["id"]
                return _public_metadata(job)
    _seq += 1
    job_id = uuid4().hex
    job = {
        "id": job_id,
        "project_id": project_id,
        "revision": revision,
        "scenario": scenario,
        "status": "queued",
        "stage": "queued",
        "completed_steps": 0,
        "total_steps": 0,
        "error": None,
        "result_url": None,
        "summary": None,
        "result": None,
        "files": {},
        "snapshot": deepcopy(project),
        "created_seq": _seq,
    }
    with _jobs_lock:
        _jobs[job_id] = job
    _prune_project(project_id)
    task = asyncio.create_task(_run_job(job_id))
    with _jobs_lock:
        job["task"] = task
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return _public_metadata(job)


async def simulation_status(project: dict, job_id: str) -> dict:
    job = _jobs.get(job_id)
    if job is None:
        raise SimulationError(404, "Simulation job not found.")
    _check_coherence(project, job)
    return _public_metadata(job)


async def simulation_result(project: dict, job_id: str) -> dict:
    job = _jobs.get(job_id)
    if job is None:
        raise SimulationError(404, "Simulation job not found.")
    _check_coherence(project, job)
    if job["status"] != "ready" or job.get("result") is None:
        raise SimulationError(409, "Simulation result is not ready.")
    return deepcopy(job["result"])


async def simulation_file(project: dict, job_id: str, name: str) -> bytes:
    job = _jobs.get(job_id)
    if job is None:
        raise SimulationError(404, "Simulation job not found.")
    _check_coherence(project, job)
    if job["status"] != "ready":
        raise SimulationError(409, "Simulation result is not ready.")
    if name not in SIMULATION_FILES:
        raise SimulationError(404, "File is not part of this simulation.")
    payload = (job.get("files") or {}).get(name)
    if payload is None:
        raise SimulationError(404, "File is not part of this simulation.")
    return bytes(payload)


def simulation_files_for_project(project: dict) -> dict[str, bytes]:
    """Sync NOMINAL simulation files for the main project ZIP (worker thread only)."""
    _ensure_supported(project)
    project_id = project.get("id")
    revision = project.get("revision")
    key = (project_id, revision, "nominal")
    with _jobs_lock:
        cached_id = _cache.get(key)
        if cached_id is not None:
            job = _jobs.get(cached_id)
            if job is not None and job["status"] == "ready" and job.get("files"):
                return {name: bytes(job["files"][name]) for name in SIMULATION_FILES}
    with _engine_lock:
        with _jobs_lock:
            cached_id = _cache.get(key)
            if cached_id is not None:
                job = _jobs.get(cached_id)
                if job is not None and job["status"] == "ready" and job.get("files"):
                    return {name: bytes(job["files"][name]) for name in SIMULATION_FILES}
        snapshot = deepcopy(project)
        result = _simulate_blocking(snapshot, "nominal", lambda *a: None)
        files = _build_files_blocking(snapshot, result)
        metrics = result.get("metrics") if isinstance(result, dict) else None
        # Register a synthetic ready job so async reads stay consistent.
        global _seq
        with _jobs_lock:
            _seq += 1
            job_id = uuid4().hex
            job = {
                "id": job_id,
                "project_id": project_id,
                "revision": revision,
                "scenario": "nominal",
                "status": "ready",
                "stage": "done",
                "completed_steps": result.get("integration_steps", 0),
                "total_steps": result.get("planned_integration_steps", 0),
                "error": None,
                "result_url": (f"/api/projects/{project_id}/simulations/{job_id}/result"),
                "summary": deepcopy(metrics) if isinstance(metrics, dict) else None,
                "result": deepcopy(result),
                "files": dict(files),
                "snapshot": snapshot,
                "created_seq": _seq,
            }
            _jobs[job_id] = job
            _cache[key] = job_id
        _prune_project(project_id)
        return {name: bytes(files[name]) for name in SIMULATION_FILES}
