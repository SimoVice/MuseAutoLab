"""Local API for the first interactive design workflow."""

import asyncio
import math
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain import apply_update, configure_project, confirm_project, new_project
from app.model_client import ModelClientError, generate_turn
from app.project_exports import (
    ExportError,
    export_archive,
    export_file,
    export_status,
    media_type_for,
    start_export,
)
from app.simulation_jobs import (
    SimulationError,
    simulation_file,
    simulation_result,
    simulation_status,
    start_simulation,
)

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


class ConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    cooling_enabled: Annotated[bool | None, Field(strict=True)] = None
    cooling_target_c: Annotated[float | None, Field(ge=2, le=20)] = None
    selections: dict[str, str] | None = None

    @field_validator("cooling_target_c", mode="before")
    @classmethod
    def _strict_target(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or isinstance(value, str):
            raise ValueError("cooling_target_c must be a number.")
        return value

    @field_validator("cooling_target_c")
    @classmethod
    def _finite_target(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("cooling_target_c must be a number.")
        if not math.isfinite(float(value)):
            raise ValueError("cooling_target_c must be finite.")
        return float(value)

    @field_validator("selections")
    @classmethod
    def _valid_selections(cls, value: dict | None) -> dict | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("selections must be an object.")
        for key, item in value.items():
            if not isinstance(key, str) or not isinstance(item, str):
                raise ValueError("selections must map strings to strings.")
        return dict(value)


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


def _configuration_message(project: dict) -> str:
    cooling = project["design"]["cooling"]
    sourcing = project["sourcing"]
    if cooling["enabled"]:
        status = (
            f"Refrigerated bay enabled. Target {cooling['target_c']:g} °C; manual sample transfer."
        )
    else:
        status = "Refrigerated bay is off."
    prefix = "from " if sourcing["is_lower_bound"] else ""
    return (
        f"{status} Known parts subtotal: {prefix}${sourcing['subtotal']:.2f} USD. "
        "Unpriced parts, shipping and taxes are excluded. Cooling performance is unverified."
    )


def _cooling_feedback(patch: dict, project: dict) -> str:
    if not {"cooling_enabled", "cooling_target_c"}.intersection(patch):
        return ""
    return "\n\n" + _configuration_message(project)


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
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"{exc} The project was not changed.",
            ) from None

        reply = turn.assistant_message
        plan = updated["plan"]
        if plan != current["plan"]:
            if plan["status"] == "invalid":
                reply += f"\n\nThe preparation plan needs a correction: {plan['message']}"
            elif plan["status"] == "ready":
                recipes = [
                    f"{step['target']}: {step['stock_volume_ul']:g} µL stock + "
                    f"{step['diluent_volume_ul']:g} µL diluent"
                    for step in plan["steps"]
                ]
                reply += "\n\nCalculated preparation per tube:\n" + "\n".join(recipes)
                reply += "\nReview the plan below before confirming."
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
        reply += _cooling_feedback(patch, updated)

        # Publish state only after model and domain validation both succeed.
        session.project = updated
        session.history.extend(
            [{"role": "user", "content": request.message}, {"role": "assistant", "content": reply}]
        )
        session.history = session.history[-8:]
        return {"project": deepcopy(updated), "assistant_message": reply, "usage": usage}


@app.post("/api/projects/{project_id}/configuration")
async def update_configuration(project_id: str, request: ConfigurationRequest) -> dict:
    session = session_for(project_id)
    async with session.lock:
        current = session.project
        try:
            updated = configure_project(current, **request.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"{exc} The project was not changed."
            ) from None
        session.project = updated
        message = _configuration_message(updated)
        return {"project": deepcopy(updated), "assistant_message": message}


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


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: str = "nominal"

    @field_validator("scenario")
    @classmethod
    def _valid_scenario(cls, value: str) -> str:
        if value not in ("nominal", "blocked_path"):
            raise ValueError("scenario must be 'nominal' or 'blocked_path'.")
        return value


def _export_error_response(exc: ExportError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def _simulation_error_response(exc: SimulationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@app.post("/api/projects/{project_id}/exports", status_code=202)
async def create_export(project_id: str) -> dict:
    session = session_for(project_id)
    async with session.lock:
        current = deepcopy(session.project)
    try:
        job = await start_export(current)
    except ExportError as exc:
        raise _export_error_response(exc) from None
    return job


@app.get("/api/projects/{project_id}/exports/{job_id}")
async def get_export(project_id: str, job_id: str) -> dict:
    session = session_for(project_id)
    async with session.lock:
        current = deepcopy(session.project)
    try:
        return await export_status(current, job_id)
    except ExportError as exc:
        raise _export_error_response(exc) from None


@app.get("/api/projects/{project_id}/exports/{job_id}/download")
async def download_export(project_id: str, job_id: str) -> Response:
    session = session_for(project_id)
    async with session.lock:
        current = deepcopy(session.project)
    try:
        payload = await export_archive(current, job_id)
        meta = await export_status(current, job_id)
    except ExportError as exc:
        raise _export_error_response(exc) from None
    filename = f"museautolab-{meta['project_id']}-r{meta['revision']}.zip"
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/projects/{project_id}/simulations", status_code=202)
async def create_simulation(project_id: str, request: SimulationRequest) -> dict:
    session = session_for(project_id)
    async with session.lock:
        current = deepcopy(session.project)
    try:
        return await start_simulation(current, scenario=request.scenario)
    except SimulationError as exc:
        raise _simulation_error_response(exc) from None


@app.get("/api/projects/{project_id}/simulations/{job_id}")
async def get_simulation(project_id: str, job_id: str) -> dict:
    session = session_for(project_id)
    async with session.lock:
        current = deepcopy(session.project)
    try:
        return await simulation_status(current, job_id)
    except SimulationError as exc:
        raise _simulation_error_response(exc) from None


@app.get("/api/projects/{project_id}/simulations/{job_id}/result")
async def get_simulation_result(project_id: str, job_id: str) -> dict:
    session = session_for(project_id)
    async with session.lock:
        current = deepcopy(session.project)
    try:
        return await simulation_result(current, job_id)
    except SimulationError as exc:
        raise _simulation_error_response(exc) from None


@app.get("/api/projects/{project_id}/simulations/{job_id}/files/{name:path}")
async def download_simulation_file(project_id: str, job_id: str, name: str) -> Response:
    session = session_for(project_id)
    async with session.lock:
        current = deepcopy(session.project)
    try:
        payload = await simulation_file(current, job_id, name)
    except SimulationError as exc:
        raise _simulation_error_response(exc) from None
    safe = name.rsplit("/", 1)[-1]
    return Response(
        content=payload,
        media_type=media_type_for(name),
        headers={"Content-Disposition": f'attachment; filename="{safe}"'},
    )


@app.get("/api/projects/{project_id}/exports/{job_id}/files/{name:path}")
async def download_export_file(project_id: str, job_id: str, name: str) -> Response:
    session = session_for(project_id)
    async with session.lock:
        current = deepcopy(session.project)
    try:
        payload = await export_file(current, job_id, name)
    except ExportError as exc:
        raise _export_error_response(exc) from None
    safe = name.rsplit("/", 1)[-1]
    return Response(
        content=payload,
        media_type=media_type_for(name),
        headers={"Content-Disposition": f'attachment; filename="{safe}"'},
    )
