"""Portable project inputs; derived geometry and checks are rebuilt on opening."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from app.design_spec import FoundationLayoutProposal, LayoutProposal, apply_candidate
from app.domain import apply_update, confirm_project, new_project
from app.upstream_cad import ASSET_ID

MAX_SNAPSHOT_BYTES = 256 * 1024
Text = Annotated[str, Field(max_length=1000)]
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Summary(StrictModel):
    stock_concentration: Text | None
    target_concentrations: Text | None
    final_volume: Text | None
    equipment: Text | None
    workspace_width_mm: Annotated[Number, Field(gt=0, le=5000)] | None
    cooling_enabled: bool
    cooling_target_c: Annotated[Number, Field(ge=2, le=20)] | None


class Brief(StrictModel):
    objective: Text | None
    process: Text | None
    materials: Text | None
    equipment: Text | None
    constraints: Text | None


class Inputs(StrictModel):
    summary: Summary
    brief: Brief
    workflow_kind: Literal["unclassified", "general", "liquid_preparation"]
    selections: Annotated[dict[Text, Text], Field(max_length=20)]


class SavedDesign(StrictModel):
    schema_version: Literal["1"]
    proposal: LayoutProposal | FoundationLayoutProposal
    provenance: dict[str, JsonValue]


class HistoryEntry(StrictModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=12000)]


class Snapshot(StrictModel):
    format: Literal["museautolab-project"]
    schema_version: Annotated[int, Field(ge=1, le=1)]
    compiler_version: Literal["1", "2", "3"]
    saved_at: Annotated[str, Field(min_length=10, max_length=50)]
    project_id: Annotated[str, Field(min_length=36, max_length=36)]
    revision: Annotated[int, Field(ge=0, le=1000000)]
    status: Literal["draft", "confirmed"]
    inputs: Inputs
    foundation_id: Literal["jubilee-v2.2.2-c877bd2"] | None = None
    foundation_bed_drop_mm: Annotated[Number, Field(ge=0, le=150)] | None = None
    engineering_design: SavedDesign | None
    inspection_extension: dict[str, JsonValue] | None = None
    history: Annotated[list[HistoryEntry], Field(max_length=8)]


def _reject_constant(value: str):
    raise ValueError(f"Non-finite JSON value: {value}.")


def _unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("The project file contains duplicate fields.")
        result[key] = value
    return result


def decode_snapshot(raw: bytes) -> dict:
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise ValueError("The project file exceeds the 256 KB limit.")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Choose a valid MuseAutoLab JSON project file.") from exc
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if depth > 32:
            raise ValueError("The project file is nested too deeply.")
        if isinstance(item, dict):
            stack.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            stack.extend((v, depth + 1) for v in item)
    if not isinstance(value, dict):
        raise ValueError("Choose a MuseAutoLab project file, not a brief or build package.")
    return value


def make_snapshot(project: dict, history: list[dict]) -> dict:
    extension = project.get("inspection_extension")
    payload = {
        "format": "museautolab-project",
        "schema_version": 1,
        "compiler_version": "3",
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "project_id": project.get("lineage_id", project["id"]),
        "revision": project["revision"],
        "status": project["status"],
        "inputs": {
            "summary": deepcopy(project["summary"]),
            "brief": deepcopy(project["brief"]),
            "workflow_kind": project["workflow"]["kind"],
            "selections": deepcopy(project["selections"]),
        },
        "foundation_id": (project.get("design", {}).get("foundation") or {}).get("id"),
        "foundation_bed_drop_mm": (project.get("design", {}).get("foundation") or {}).get(
            "bed_drop_mm"
        ),
        "engineering_design": deepcopy(project.get("engineering_design")),
        "inspection_extension": (
            {
                "proposal": deepcopy(extension["proposal"]),
                "provenance": deepcopy(extension.get("provenance", {})),
            }
            if extension
            else None
        ),
        "history": deepcopy(history[-8:]),
    }
    # Validate our own format before returning a file that cannot be reopened.
    Snapshot.model_validate(payload)
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise ValueError("This project exceeds the 256 KB save limit.")
    return payload


def restore_snapshot(snapshot: object) -> tuple[dict, list[dict]]:
    try:
        saved = Snapshot.model_validate(snapshot)
        UUID(saved.project_id)
        datetime.fromisoformat(saved.saved_at.replace("Z", "+00:00"))
    except (ValidationError, ValueError) as exc:
        raise ValueError("Unsupported or invalid MuseAutoLab project file.") from exc
    inputs = saved.inputs
    if saved.compiler_version != "3" and (
        saved.foundation_id is not None or saved.foundation_bed_drop_mm is not None
    ):
        raise ValueError("Older project files cannot specify a source CAD foundation.")
    proposal = saved.engineering_design.proposal if saved.engineering_design else None
    if (saved.foundation_id is None) != (saved.foundation_bed_drop_mm is None):
        raise ValueError("A saved source CAD foundation requires its bed position.")
    if saved.compiler_version == "3" and proposal is not None:
        source_proposal = isinstance(proposal, FoundationLayoutProposal)
        if source_proposal != (saved.foundation_id == ASSET_ID):
            raise ValueError("The saved layout does not match its CAD foundation.")
        if source_proposal and proposal.bed_drop_mm != saved.foundation_bed_drop_mm:
            raise ValueError("The saved bed position does not match its accepted layout.")
    summary, brief = inputs.summary.model_dump(), inputs.brief.model_dump()
    if inputs.workflow_kind != "liquid_preparation" and any(
        summary[key] is not None
        for key in ("stock_concentration", "target_concentrations", "final_volume", "equipment")
    ):
        raise ValueError("Liquid preparation quantities require the liquid workflow.")
    if inputs.workflow_kind == "liquid_preparation" and summary["equipment"] != brief["equipment"]:
        raise ValueError("The saved equipment fields do not match.")
    width = summary["workspace_width_mm"]
    patch = {
        **summary,
        "workspace_width_mm": None,
        "selections": inputs.selections,
        "workflow_kind": inputs.workflow_kind,
        **{f"brief_{key}": value for key, value in brief.items()},
    }
    project = apply_update(new_project(), patch)
    if width is not None:
        project = apply_update(project, {"workspace_width_mm": width})
    upgraded = saved.compiler_version in ("1", "2")
    if not upgraded and saved.foundation_id:
        from app.foundation_design import adopt_foundation

        project = adopt_foundation(project, bed_drop_mm=saved.foundation_bed_drop_mm)
        if width is not None and width < project["design"]["foundation"]["bbox_mm"][0]:
            project["design"]["constraint_status"] = "infeasible"
        if proposal is None:
            from app.geometry import add_geometry

            project = add_geometry(project)
    if saved.engineering_design and not upgraded:
        if not summary["equipment"] or saved.revision < 1:
            raise ValueError("A saved layout requires equipment and a design revision.")
        project = apply_candidate(
            project,
            saved.engineering_design.proposal.model_dump(),
            saved.engineering_design.provenance,
        )
    if project["summary"] != summary or project["brief"] != brief:
        raise ValueError("The saved inputs are inconsistent with the current project format.")
    if saved.inspection_extension is not None and not upgraded:
        from app.inspection import restore_extension

        project = restore_extension(project, saved.inspection_extension)
    if saved.status == "confirmed" and not upgraded:
        project = confirm_project(project)
    project["revision"] = saved.revision + int(upgraded)
    project["status"] = "draft" if upgraded else saved.status
    project["lineage_id"] = saved.project_id
    project["restored_from"] = {
        "project_id": saved.project_id,
        "revision": saved.revision,
        "saved_at": saved.saved_at,
        "compiler_version": saved.compiler_version,
    }
    if upgraded:
        project["rebuild_notice"] = (
            "This older project retains its inputs and conversation, but its previous design "
            "and inspection extension cannot be carried over to the new CAD foundation. "
            "Ask Meta in chat to develop a new workstation design and confirm it again."
        )
    return project, [entry.model_dump() for entry in saved.history]
