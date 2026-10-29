"""Local API for the general laboratory automation platform."""

import asyncio
import json
import math
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.chat_actions import execute_chat_actions, extension_only_patch
from app.design_agent import develop_design
from app.design_sources import project_source_basis, reference_library, resolve_reference
from app.domain import apply_update, configure_project, confirm_project, new_project
from app.engineering import EngineeringUpdate, apply_engineering_update, state_for
from app.inspection import clear_extension, develop_inspection
from app.model_client import ChatAction, ModelClientError, generate_turn
from app.project_exports import (
    ExportError,
    export_archive,
    export_file,
    export_status,
    media_type_for,
    start_export,
)
from app.project_storage import MAX_SNAPSHOT_BYTES, decode_snapshot, make_snapshot, restore_snapshot
from app.simulation_jobs import (
    SimulationError,
    simulation_file,
    simulation_result,
    simulation_status,
    start_simulation,
)
from app.vision import Box
from app.vision_jobs import (
    InspectionError,
    inspection_archive,
    inspection_image,
    inspection_status,
    review_inspection,
    start_inspection,
)
from app.workflows import describe_workflow

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


@app.get("/api/references")
async def get_reference_library() -> dict:
    return reference_library()


@app.get("/api/projects/{project_id}/sources")
async def get_project_sources(project_id: str, revision: int) -> Response:
    session = session_for(project_id)
    async with session.lock:
        if revision != session.project["revision"]:
            raise HTTPException(status_code=409,
                                detail="Download sources for the current revision.")
        payload = {"project_id": project_id, "revision": revision,
                   "source_basis": project_source_basis(session.project)}
    return Response(content=json.dumps(payload, indent=2), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="design-sources.json"',
                             "Cache-Control": "no-store"})


@app.get("/api/projects/{project_id}/snapshot")
async def save_project(project_id: str, revision: int) -> Response:
    session = session_for(project_id)
    async with session.lock:
        if revision != session.project["revision"]:
            raise HTTPException(status_code=409, detail="Save the current project revision.")
        try:
            snapshot = make_snapshot(session.project, session.history)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    content = json.dumps(snapshot, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
    filename = f"museautolab-{snapshot['project_id'][:8]}-r{revision}.json"
    return Response(content=content, media_type="application/json", headers={
        "Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store",
    })


@app.post("/api/projects/open", status_code=201)
async def open_project(request: Request) -> dict:
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_SNAPSHOT_BYTES:
            raise HTTPException(status_code=413,
                                detail="The project file exceeds the 256 KB limit.")
    try:
        project, history = restore_snapshot(decode_snapshot(bytes(content)))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    _sessions[project["id"]] = ProjectSession(project=project, history=history)
    return {"project": deepcopy(project), "conversation": deepcopy(history),
            "assistant_message": "Project reopened. Geometry was rebuilt from saved inputs."}


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
            actions = list(turn.actions)
            patch = extension_only_patch(turn.patch(), actions)
            updated = apply_update(current, patch)
            engineering = getattr(turn, "engineering", EngineeringUpdate())
            updated = apply_engineering_update(
                updated, engineering, request.message,
                bump=updated["revision"] == current["revision"]
            )
            new_choice = state_for(updated)["selected_platform_id"]
            preserve_layout = any(phrase in request.message.casefold() for phrase in (
                "keep the machine layout unchanged", "keep the layout unchanged",
                "do not change the layout", "lascia invariata la disposizione",
            ))
            if (preserve_layout and current.get("engineering_design")
                    and not engineering.platform_choice
                    and all(current["summary"].get(k) == updated["summary"].get(k) for k in (
                        "workspace_width_mm", "cooling_enabled", "cooling_target_c"))):
                actions = [action for action in actions if action.kind != "develop_layout"]
            if (engineering.platform_choice and new_choice and not actions
                    and updated["workflow"]["kind"] == "liquid_preparation"
                    and (updated["summary"].get("equipment") or updated["brief"].get("equipment"))):
                actions = [ChatAction(kind="develop_layout", source=engineering.choice_source)]
            if (not actions and current.get("engineering_design") and set(patch).intersection({
                "workspace_width_mm", "cooling_enabled", "cooling_target_c",
            })):
                actions = [ChatAction(kind="develop_layout", source=request.message[:1000])]
            action_runs = []
            if actions:
                updated, action_runs = await execute_chat_actions(updated, actions, request.message)
                if any(run["status"] in ("failed", "rejected") for run in action_runs):
                    updated = deepcopy(current)
        except ModelClientError as exc:
            return JSONResponse(status_code=502, content={
                "detail": str(exc),
                "failure_kind": getattr(exc, "failure_kind", "model_request"),
                "usage": getattr(exc, "usage", {}),
            })
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"{exc} The project was not changed.",
            ) from None

        reply = turn.assistant_message
        from app.platform_profiles import engineering_guidance

        if state_for(updated)["selected_platform_id"] or any(
            run["kind"] == "show_build_plan" for run in action_runs
        ):
            updated["engineering_guidance"] = engineering_guidance(updated)
        if action_runs:
            reply += "\n\n" + "\n".join(run["message"] for run in action_runs)
            if any(run["kind"] == "develop_layout" and run["status"] == "accepted"
                   for run in action_runs):
                proposal = updated.get("engineering_design", {}).get("proposal", {})
                rationale = proposal.get("rationale")
                if rationale:
                    reply += "\n\nDesign reasoning: " + rationale[:600]
        recommendations = []
        for recommendation in turn.recommendations:
            ref = resolve_reference(recommendation.reference_id)
            recommendations.append({"reference": ref, "reason": recommendation.reason})
        workflow = describe_workflow(updated)
        design_available = bool(workflow.get("design_available"))
        if design_available:
            plan = updated.get("plan")
            previous_plan = current.get("plan")
            if plan is not None and plan != previous_plan:
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
            if "workspace_width_mm" in patch and not action_runs:
                width = updated["summary"]["workspace_width_mm"]
                if updated["design"]["constraint_status"] == "infeasible":
                    reply += (
                        f"\n\nA {width:g} mm width is below this concept's supported minimum. "
                        "The previous geometry is retained; "
                        "revise the constraint before confirming."
                    )
                else:
                    reply += (
                        f"\n\nRecorded a {width:g} mm maximum width. "
                        "Develop a fresh layout with Meta to check the arrangement; "
                        "this message has not generated a new machine."
                    )
            reply += _cooling_feedback(patch, updated)

        display_reply = reply
        if recommendations:
            reply += "\n\nReviewed references:\n" + "\n".join(
                f"{r['reference']['title']} [{r['reference']['id']}]: {r['reason']}"
                for r in recommendations
            )
        # Publish state only after model and domain validation both succeed.
        session.project = updated
        session.history.extend(
            [{"role": "user", "content": request.message}, {"role": "assistant", "content": reply}]
        )
        session.history = session.history[-8:]
        return {"project": deepcopy(updated), "assistant_message": display_reply, "usage": usage,
                "recommendations": recommendations, "action_runs": action_runs}


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


@app.get("/api/projects/{project_id}/brief")
async def get_brief(project_id: str, revision: int) -> Response:
    session = session_for(project_id)
    async with session.lock:
        current = deepcopy(session.project)
    current_revision = current.get("revision")
    if revision != current_revision:
        raise HTTPException(
            status_code=409,
            detail=f"Revision {revision} is not current (expected {current_revision}).",
        )
    payload = {
        "project_id": current.get("id", project_id),
        "project_revision": current_revision,
        "status": current.get("status"),
        "brief": deepcopy(current.get("brief", {})),
        "workflow": describe_workflow(current),
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="project-brief.json"',
            "Cache-Control": "no-store",
        },
    )


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


class DesignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_revision: Annotated[int, Field(strict=True, ge=0)]
    instruction: Annotated[str, Field(min_length=1, max_length=2000)]

    @field_validator("instruction")
    @classmethod
    def trim_instruction(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Enter a design instruction before sending.")
        if len(value) > 2000:
            raise ValueError("Design instruction must contain at most 2000 characters.")
        return value


@app.post("/api/projects/{project_id}/design")
async def develop_layout(project_id: str, request: DesignRequest) -> dict:
    session = session_for(project_id)
    # Serialize design runs like chat turns; a slow model call cannot overwrite a newer revision.
    async with session.lock:
        current = session.project
        if request.project_revision != current.get("revision"):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Revision {request.project_revision} is not current "
                    f"(expected {current.get('revision')})."
                ),
            )
        workflow = describe_workflow(current)
        if not isinstance(workflow, dict) or not workflow.get("design_available"):
            raise HTTPException(
                status_code=409,
                detail="Layout design is not available for this workflow.",
            )
        equipment = (
            current.get("summary", {}).get("equipment")
            or current.get("brief", {}).get("equipment")
        )
        if not isinstance(equipment, str) or not equipment.strip():
            raise HTTPException(
                status_code=409,
                detail="Describe the equipment in chat before developing a workstation layout.",
            )
        design = current.get("design", {}) if isinstance(current, dict) else {}
        if design.get("constraint_status") == "infeasible":
            raise HTTPException(
                status_code=409,
                detail="Layout design is not available for an infeasible width.",
            )
        try:
            updated, run = await develop_design(deepcopy(current), request.instruction)
        except ModelClientError as exc:
            if hasattr(exc, "design_run"):
                return JSONResponse(status_code=502, content={
                    "detail": str(exc), "design_run": exc.design_run,
                })
            raise HTTPException(status_code=502, detail=str(exc)) from None
        # Commit only accepted runs; rejected runs leave the stored project unchanged.
        if run.get("status") == "accepted":
            session.project = updated
            return {
                "project": deepcopy(updated),
                "design_run": deepcopy(run),
                "assistant_message": run.get("message", ""),
            }
        return {
            "project": deepcopy(current),
            "design_run": deepcopy(run),
            "assistant_message": run.get("message", ""),
        }


@app.post("/api/projects/{project_id}/inspection-extension")
async def add_inspection_extension(project_id: str, request: DesignRequest) -> dict:
    session = session_for(project_id)
    async with session.lock:
        current = session.project
        if request.project_revision != current["revision"]:
            raise HTTPException(status_code=409,
                                detail="The project changed. Use its current revision.")
        if not current.get("engineering_design"):
            raise HTTPException(status_code=409, detail="Develop a workstation layout first.")
        try:
            updated, run = await develop_inspection(deepcopy(current), request.instruction)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except ModelClientError as exc:
            return JSONResponse(status_code=502, content={
                "detail": str(exc), "design_run": getattr(exc, "design_run", None),
            })
        if run["status"] == "accepted":
            session.project = updated
        return {"project": deepcopy(session.project), "design_run": run,
                "assistant_message": run["message"]}


class RevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_revision: Annotated[int, Field(strict=True, ge=0)]


@app.post("/api/projects/{project_id}/inspection-extension/remove")
async def remove_inspection_extension(project_id: str, request: RevisionRequest) -> dict:
    session = session_for(project_id)
    async with session.lock:
        current = session.project
        if request.project_revision != current["revision"]:
            raise HTTPException(status_code=409,
                                detail="The project changed. Use its current revision.")
        if current.get("inspection_extension"):
            updated = clear_extension(current)
            updated["revision"] += 1
            updated["status"] = "draft"
            session.project = updated
        return {"project": deepcopy(session.project),
                "assistant_message": "Inspection module removed. Workstation layout preserved."}


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


def _inspection_error_response(exc: InspectionError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


class InspectionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    project_revision: Annotated[int, Field(strict=True)]
    image_data_url: Annotated[str, Field(min_length=1, max_length=5_592_472)]


class ReviewDecisionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    action: str
    kind: str | None = None
    label: str | None = None
    box: Box | None = None
    component_id: str | None = None
    tip_rack_contents: str | None = None


class ReviewAdditionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    label: str
    box: Box
    component_id: str | None = None
    tip_rack_contents: str | None = None


class InspectionReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_version: Annotated[int, Field(strict=True)]
    scene_reviewed: Annotated[bool, Field(strict=True)]
    decisions: list[ReviewDecisionModel] = Field(default_factory=list)
    additions: list[ReviewAdditionModel] = Field(default_factory=list)


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


@app.post("/api/projects/{project_id}/inspections", status_code=202)
async def create_inspection(project_id: str, request: InspectionCreateRequest) -> dict:
    session = session_for(project_id)
    async with session.lock:
        current = deepcopy(session.project)
        try:
            return await start_inspection(
                current,
                project_revision=request.project_revision,
                image_data_url=request.image_data_url,
            )
        except InspectionError as exc:
            raise _inspection_error_response(exc) from None


@app.get("/api/projects/{project_id}/inspections/{job_id}")
async def get_inspection(project_id: str, job_id: str) -> dict:
    session = session_for(project_id)
    async with session.lock:
        current = deepcopy(session.project)
    try:
        return await inspection_status(current, job_id)
    except InspectionError as exc:
        raise _inspection_error_response(exc) from None


@app.get("/api/projects/{project_id}/inspections/{job_id}/image")
async def get_inspection_image(project_id: str, job_id: str) -> Response:
    session = session_for(project_id)
    async with session.lock:
        current = deepcopy(session.project)
    try:
        payload, _, _ = await inspection_image(current, job_id)
    except InspectionError as exc:
        raise _inspection_error_response(exc) from None
    return Response(
        content=payload,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/projects/{project_id}/inspections/{job_id}/review")
async def review_inspection_job(
    project_id: str, job_id: str, request: InspectionReviewRequest
) -> dict:
    session = session_for(project_id)
    async with session.lock:
        current = deepcopy(session.project)
    try:
        return await review_inspection(current, job_id, request.model_dump(exclude_unset=True))
    except InspectionError as exc:
        raise _inspection_error_response(exc) from None


@app.get("/api/projects/{project_id}/inspections/{job_id}/archive")
async def download_inspection_archive(
    project_id: str, job_id: str, observation_version: int | None = None
) -> Response:
    session = session_for(project_id)
    async with session.lock:
        current = deepcopy(session.project)
    try:
        payload, filename = await inspection_archive(current, job_id, observation_version)
    except InspectionError as exc:
        raise _inspection_error_response(exc) from None
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
