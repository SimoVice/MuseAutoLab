"""Meta-proposed, checked inspection-arm extensions for an accepted workstation."""

from __future__ import annotations

import asyncio
import json
import time
from copy import deepcopy
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.catalog import build_sourcing
from app.design_agent import _semaphore, request_design_proposal
from app.design_sources import project_source_basis, reference_context, resolve_reference
from app.inspection_geometry import compile_inspection, inspection_anchor, inspection_components
from app.model_client import ModelClientError

Number = Annotated[float, Field(strict=True, ge=180, le=500, allow_inf_nan=False)]


class InspectionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1"]
    link_lengths_mm: Annotated[list[Number], Field(min_length=2, max_length=2)]
    mast_height_mm: Annotated[float, Field(strict=True, ge=400, le=550, allow_inf_nan=False)]
    rationale: Annotated[str, Field(max_length=1200)]
    assumptions: Annotated[list[Annotated[str, Field(max_length=300)]], Field(max_length=6)]


def _require_layout(project: dict) -> None:
    if project.get("design", {}).get("platform"):
        raise ValueError("Custom inspection-arm integration is not implemented for this "
                         "assembled platform. We can plan its requirements separately.")
    if not project.get("engineering_design") or project["workflow"]["kind"] != "liquid_preparation":
        raise ValueError("Develop a workstation layout with Meta before adding the inspection arm.")
    if project["design"]["constraint_status"] == "infeasible":
        raise ValueError("Resolve the workspace width before adding the inspection arm.")


def clear_extension(project: dict) -> dict:
    result = deepcopy(project)
    previous = result.pop("inspection_extension", None)
    if previous:
        ids = set(previous["component_ids"])
        result["design"]["components"] = [
            p for p in result["design"]["components"] if p["id"] not in ids
        ]
        if result["design"].get("foundation"):
            from app.foundation_design import foundation_sourcing

            result["sourcing"] = foundation_sourcing(result)
        else:
            result["sourcing"] = build_sourcing(
                result["selections"], result["summary"]["cooling_enabled"]
            )
    if result["design"].get("foundation"):
        from app.foundation_design import assembly_bounds

        result["design"]["assembly_bounds"] = assembly_bounds(result)
    else:
        result["design"].pop("assembly_bounds", None)
    result["design_basis"] = project_source_basis(result)
    return result


def check_extension(project: dict, raw: object) -> dict:
    _require_layout(project)
    proposal = InspectionProposal.model_validate(raw).model_dump()
    base = clear_extension(project)
    module = compile_inspection(base, proposal)
    parts = base["design"]["components"]
    lower = [
        min(module["bounds"]["min_mm"][i], min(p["position"][i] - p["size"][i] / 2 for p in parts))
        for i in range(3)
    ]
    upper = [
        max(module["bounds"]["max_mm"][i], max(p["position"][i] + p["size"][i] / 2 for p in parts))
        for i in range(3)
    ]
    limit = project["summary"].get("workspace_width_mm")
    if limit is not None and upper[0] - lower[0] > limit + 1e-6:
        raise ValueError(
            "The inspection poses exceed the workspace width. Propose shorter links "
            "or increase the available width."
        )
    module["assembly_bounds"] = {"min_mm": lower, "max_mm": upper}
    module["checks"].append(
        {
            "id": "workspace_width",
            "passed": True,
            "detail": ("Recorded pose envelopes respect the available width." if limit is not None
                       else "No workspace width limit was specified; pose bounds are recorded."),
        }
    )
    return module


def _extension_sourcing(project: dict) -> None:
    sourcing = project["sourcing"]
    # These are explicitly unselected concept groups, not supplier quotations.
    for group_id, label, ids in (
        (
            "inspection-arm",
            "Inspection arm concept",
            [
                "inspection-mast",
                "inspection-shoulder",
                "inspection-upper-link",
                "inspection-elbow",
                "inspection-forearm",
                "inspection-wrist",
            ],
        ),
        ("inspection-mount", "Inspection sidecar mount", ["inspection-mount"]),
        ("inspection-camera", "Inspection camera and custom bracket",
         ["inspection-camera", "inspection-camera-mount"]),
    ):
        sourcing["groups"] = [g for g in sourcing["groups"] if g["id"] != group_id]
        sourcing["groups"].append(
            {
                "id": group_id,
                "label": label,
                "component_ids": ids,
                "quantity": 1,
                "selected_id": "unselected-concept",
                "options": [
                    {
                        "id": "unselected-concept",
                        "label": "Hardware selection pending",
                        "supplier": "Not selected",
                        "sku": None,
                        "unit_price": None,
                        "price_kind": "unpriced",
                        "source_url": None,
                        "checked_on": "Not researched",
                        "availability": "Unverified",
                        "pros": [],
                        "cons": ["Hardware, fasteners, cabling and power remain to be selected."],
                        "compatibility_note": "Concept geometry only; fit and loads unverified.",
                    }
                ],
            }
        )
        if group_id == "inspection-camera":
            ref = resolve_reference("rpi-camera-module-3")
            option = sourcing["groups"][-1]["options"][0]
            option.update(label="Camera Module 3 + custom mount (integration pending)",
                          supplier="Raspberry Pi / custom bracket", sku="Camera Module 3 standard",
                          source_url=ref["url"], checked_on=ref["checked_on"],
                          compatibility_note=ref["limits"], reference_ids=[ref["id"]])
    sourcing["unpriced_count"] = sum(
        next(o for o in g["options"] if o["id"] == g["selected_id"])["unit_price"] is None
        for g in sourcing["groups"]
    )
    sourcing["incomplete"] = True


def apply_extension(project: dict, raw: object, provenance: dict, *, bump: bool = True) -> dict:
    module = check_extension(project, raw)
    module["provenance"] = deepcopy(provenance)
    result = clear_extension(project)
    result["inspection_extension"] = module
    result["design"]["components"].extend(inspection_components(module))
    result["design"]["assembly_bounds"] = deepcopy(module["assembly_bounds"])
    _extension_sourcing(result)
    result["design_basis"] = project_source_basis(result)
    if bump:
        result["revision"] += 1
        result["status"] = "draft"
    return result


def restore_extension(project: dict, saved: dict) -> dict:
    if set(saved) != {"proposal", "provenance"} or not isinstance(saved["provenance"], dict):
        raise ValueError("Invalid saved inspection extension.")
    return apply_extension(project, saved["proposal"], saved["provenance"], bump=False)


async def propose_inspection(project: dict, instruction: str, feedback: str) -> tuple[dict, dict]:
    parts = [
        {"id": p["id"], "position": p["position"], "size": p["size"]}
        for p in clear_extension(project)["design"]["components"]
    ]
    source_based = bool(project.get("design", {}).get("foundation"))
    anchor = inspection_anchor(project)
    instructions = (
        "Propose a strict JSON inspection-arm extension for this accepted workstation. "
        "One supported concept: two horizontal links, front-right sidecar, downward camera. "
        "Choose link_lengths_mm (exactly two numbers, each 180..500) and mast_height_mm "
        "(400..550), schema_version '1', concise rationale and at most 6 assumptions. "
        + ("For this Jubilee project, mast_height_mm is measured above the custom deck top, "
           "and the arm may extend above the source frame. " if source_based else
           "mast_height_mm is the absolute height above the application ground. ")
        + ("Base joint is at x=foundation.position.x+foundation.size.x/2-80, "
           "z=foundation.position.z+foundation.size.z/2+150. " if source_based else
           "Base joint is at x=base.position.x+base.size.x/2-80, "
           "z=base.position.z+base.size.z/2+100. ")
        + "Reach sample-rack centre and x +/-20 at its z. "
        "For all targets abs(L1-L2) <= distance <= L1+L2. Prefer the shortest practical links. "
        f"Compiler-computed anchor, targets and distances: {json.dumps(anchor)}. "
        "Use these computed distances as authoritative: choose a total link length at least "
        f"{max(anchor['target_distances_mm']) + 10:.2f} mm, including a 10 mm proposal margin. "
        "Compiler selects the leftmost elbow IK branch. All four pose envelopes must fit "
        "the total workspace width if specified, not just the pad. The sidecar increases "
        "depth; no collision, load, camera coverage or hardware control is validated. "
        "Keep existing components unchanged. Hardware is not selected or priced. "
        f"Workspace width limit mm: {project['summary'].get('workspace_width_mm')}. "
        f"Existing components mm: {json.dumps(parts)}"
        f"Reviewed reference context: {json.dumps(reference_context(project))}"
        "The camera envelope is fixed to Camera Module 3 manufacturer dimensions; do not "
        "resize it or imply the custom arm is a copied/validated open-source robot."
    )
    return await request_design_proposal(
        instructions,
        InspectionProposal.model_json_schema(),
        "inspection_proposal",
        instruction,
        feedback,
    )


async def develop_inspection(project: dict, instruction: str) -> tuple[dict, dict]:
    _require_layout(project)
    source = deepcopy(project)
    run_id = f"inspection-{uuid4().hex[:8]}"
    attempts, feedback = [], ""
    deadline = time.monotonic() + 90
    async with _semaphore():
        for number in (1, 2):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                candidate, usage = await asyncio.wait_for(
                    propose_inspection(source, instruction, feedback), timeout=min(45, remaining)
                )
            except (ModelClientError, asyncio.TimeoutError) as exc:
                error = ModelClientError(
                    "The Meta inspection design request failed. "
                    "Your project was not changed; try again."
                )
                error.usage = getattr(exc, "usage", {})
                error.design_run = {
                    "id": run_id,
                    "source_revision": source["revision"],
                    "status": "failed",
                    "model": error.usage.get("model", "not recorded"),
                    "instruction": instruction,
                    "attempts": attempts
                    + [
                        {
                            "number": number,
                            "proposal": None,
                            "checks": [],
                            "usage": error.usage,
                            "error": str(error),
                        }
                    ],
                    "message": str(error),
                }
                raise error from None
            try:
                module = check_extension(source, candidate)
                checks = [{**c, "label": c["id"].replace("_", " ")} for c in module["checks"]]
            except ValueError as exc:
                checks = [
                    {
                        "id": "inspection_geometry",
                        "label": "Inspection geometry",
                        "passed": False,
                        "detail": str(exc),
                    }
                ]
            attempts.append(
                {"number": number, "proposal": candidate, "checks": checks, "usage": usage}
            )
            if all(c["passed"] for c in checks):
                provenance = {
                    "run_id": run_id,
                    "model": usage.get("model", "not recorded"),
                    "source_revision": source["revision"],
                    "instruction": instruction,
                    "attempts": deepcopy(attempts),
                    "checks": checks,
                    "usage": usage,
                    "source_library_sha256": project_source_basis(source)["library_sha256"],
                }
                updated = apply_extension(source, candidate, provenance)
                return updated, {
                    "id": run_id,
                    "source_revision": source["revision"],
                    "status": "accepted",
                    "model": provenance["model"],
                    "instruction": instruction,
                    "attempts": attempts,
                    "message": "Inspection arm and camera added to this "
                    "project. Kinematic concept only; hardware and camera coverage are unverified.",
                }
            feedback = json.dumps({"candidate": candidate, "diagnostics": checks})
    return deepcopy(source), {
        "id": run_id,
        "source_revision": source["revision"],
        "status": "rejected",
        "model": attempts[-1]["usage"].get("model", "not recorded") if attempts else "not recorded",
        "instruction": instruction,
        "attempts": attempts,
        "message": "The inspection proposal did not pass the checks. Your project was not changed.",
    }
