"""Ephemeral, request-scoped activity; never inferred from elapsed time."""

import re
import time
from contextlib import contextmanager
from contextvars import ContextVar

from fastapi import HTTPException, Request

_current = ContextVar("chat_activity", default=None)
_activities: dict[tuple[str, str], dict] = {}
_valid_id = re.compile(r"^[a-zA-Z0-9_-]{16,80}$")


def report_activity(stage: str) -> None:
    key = _current.get()
    if key in _activities:
        _activities[key]["stage"] = stage


@contextmanager
def activity_scope(stage: str):
    key = _current.get()
    previous = _activities.get(key, {}).get("stage")
    report_activity(stage)
    try:
        yield
    finally:
        if previous is not None:
            report_activity(previous)


MAX_ACTIVITIES = 512
RETENTION_SECONDS = 60


def _prune():
    now = time.monotonic()
    for key, entry in list(_activities.items()):
        if not entry["active"] and now - entry["updated"] >= RETENTION_SECONDS:
            del _activities[key]
    while len(_activities) >= MAX_ACTIVITIES:
        completed = [key for key, entry in _activities.items() if not entry["active"]]
        if not completed:
            break
        del _activities[min(completed, key=lambda key: _activities[key]["updated"])]


def activity_dependency(session_for):
    async def track(request: Request):
        request_id = request.headers.get("x-chat-request-id", "")
        if not _valid_id.fullmatch(request_id):
            yield
            return
        project_id = request.path_params["project_id"]
        session_for(project_id)
        _prune()
        key = (project_id, request_id)
        if key in _activities:
            raise HTTPException(409, "This request identifier has already been used.")
        if len(_activities) >= MAX_ACTIVITIES:
            raise HTTPException(503, "Too many requests are active. Try again shortly.")
        _activities[key] = {"stage": "waiting", "active": True, "updated": time.monotonic()}
        token = _current.set(key)
        try:
            yield
        finally:
            _activities[key].update(active=False, updated=time.monotonic())
            _current.reset(token)

    return track


def install_activity(app) -> None:
    @app.get("/api/projects/{project_id}/activity/{request_id}")
    async def activity(project_id: str, request_id: str):
        _prune()
        entry = _activities.get((project_id, request_id))
        if entry is None:
            raise HTTPException(404, "No active request with this identifier.")
        return {"stage": entry["stage"], "active": entry["active"]}
