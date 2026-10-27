"""Local API for the first interactive design workflow."""

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.domain import apply_update, confirm_project, new_project
from app.model_client import ModelClientError, generate_turn

app = FastAPI(title="MuseAutoLab", version="0.1.0")


class MessageRequest(BaseModel):
    message: Annotated[str, Field(min_length=1, max_length=4000)]

    @field_validator("message")
    @classmethod
    def trim_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Enter a message before sending.")
        return value


@dataclass
class ProjectSession:
    project: dict
    history: list[dict[str, str]] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# Deliberately process-local for this first milestone; restart starts a fresh session.
_sessions: dict[str, ProjectSession] = {}


def session_for(project_id: str) -> ProjectSession:
    session = _sessions.get(project_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Project not found. Start a new project.")
    return session


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/projects", status_code=201)
async def create_project() -> dict:
    project = new_project()
    _sessions[project["id"]] = ProjectSession(project=project)
    return {"project": deepcopy(project)}


@app.post("/api/projects/{project_id}/messages")
async def send_message(project_id: str, request: MessageRequest) -> dict:
    session = session_for(project_id)
    # Serialize each project's turns: a slow model call cannot overwrite a newer revision.
    async with session.lock:
        current = session.project
        try:
            turn, usage = await generate_turn(
                deepcopy(current), request.message, list(session.history)
            )
            patch = turn.patch()
            updated = apply_update(current, patch)
        except ModelClientError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="The requested change is invalid. The project was not changed.",
            ) from None

        reply = turn.assistant_message
        if "workspace_width_mm" in patch:
            width = updated["summary"]["workspace_width_mm"]
            footprint = updated["design"]["footprint"]
            if updated["design"]["constraint_status"] == "infeasible":
                reply += (
                    f"\n\nA {width:g} mm width is below this concept's supported minimum. "
                    "The previous geometry is retained; revise the constraint before confirming."
                )
            else:
                reply += (
                    f"\n\nThe modeled footprint is {footprint['width_mm']:g} mm wide "
                    f"for your {width:g} mm limit. Fixed component dimensions are unchanged; "
                    "custom frame parts adjust. Motion and physical fit remain unverified."
                )

        # Publish state only after model and domain validation both succeed.
        session.project = updated
        session.history.extend(
            [{"role": "user", "content": request.message}, {"role": "assistant", "content": reply}]
        )
        session.history = session.history[-8:]
        return {"project": deepcopy(updated), "assistant_message": reply, "usage": usage}


@app.post("/api/projects/{project_id}/confirm")
async def confirm(project_id: str) -> dict:
    session = session_for(project_id)
    async with session.lock:
        try:
            updated = confirm_project(session.project)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        session.project = updated
        return {
            "project": deepcopy(updated),
            "assistant_message": (
                "Parameters confirmed for this concept. This does not run a laboratory protocol."
            ),
        }
