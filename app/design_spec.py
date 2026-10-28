"""Bounded layout proposals for the illustrative liquid preparation workstation.

Checks are geometric screening only: they do not verify travel, all collisions,
interfaces, fabrication, or laboratory performance. Coordinates are in mm,
with y vertical and the centre of the operating deck as x/z origin.
"""

from __future__ import annotations

import math
from copy import deepcopy
from itertools import combinations
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.geometry import add_geometry

MOVABLE_IDS = ("source-rack", "sample-rack", "tip-rack", "tip-waste", "controller")
ComponentId = Literal["source-rack", "sample-rack", "tip-rack", "tip-waste", "controller"]
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class Placement(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    component_id: ComponentId
    x_mm: Number
    z_mm: Number


class LayoutProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1"]
    deck_width_mm: Annotated[Number, Field(ge=400, le=900)]
    deck_depth_mm: Annotated[Number, Field(ge=320, le=650)]
    placements: Annotated[list[Placement], Field(min_length=5, max_length=5)]
    rationale: Annotated[str, Field(max_length=1200)]
    assumptions: Annotated[list[Annotated[str, Field(max_length=300)]], Field(max_length=6)]

    @model_validator(mode="after")
    def distinct_components(self) -> LayoutProposal:
        ids = [entry.component_id for entry in self.placements]
        if len(set(ids)) != len(MOVABLE_IDS):
            raise ValueError("Placements must include each of the five component IDs exactly once.")
        return self


def proposal_schema() -> dict:
    return LayoutProposal.model_json_schema()


def _check(check_id: str, label: str, passed: bool, detail: str) -> dict:
    return {"id": check_id, "label": label, "passed": bool(passed), "detail": detail}


def check_candidate(project: dict, raw: object) -> list[dict]:
    """Return actionable checks without raising for an invalid proposal."""
    checks = []
    workflow = project.get("workflow") or {}
    supported = (
        workflow.get("kind") == "liquid_preparation" and workflow.get("design_available") is True
    )
    checks.append(_check("workflow", "Supported workflow", supported,
                         "Liquid preparation with design enabled is required."))
    summary = project.get("summary") or {}
    width_limit = summary.get("workspace_width_mm")
    design = project.get("design") or {}
    feasible = design.get("constraint_status") != "infeasible" and (
        width_limit is None or (isinstance(width_limit, (int, float))
                                and not isinstance(width_limit, bool) and width_limit >= 400)
    )
    checks.append(_check("feasible_width", "Feasible workspace", feasible,
                         "Resolve the infeasible workspace width before developing a layout."))
    try:
        proposal = LayoutProposal.model_validate(raw)
    except ValidationError as exc:
        for index, error in enumerate(exc.errors(include_url=False, include_input=False)):
            location = ".".join(str(part) for part in error["loc"]) or "proposal"
            checks.append(_check(f"schema_{index}", "Proposal format", False,
                                 f"{location}: {error['msg']}"))
        return checks

    checks.append(
        _check("schema", "Proposal format", True, "Required fields and values are valid.")
    )
    within_width = width_limit is None or (
        isinstance(width_limit, (int, float)) and not isinstance(width_limit, bool)
        and proposal.deck_width_mm <= width_limit
    )
    checks.append(_check("workspace_width", "Workspace width", within_width,
                         f"Proposed width {proposal.deck_width_mm:g} mm; "
                         + ("no width limit specified." if width_limit is None
                            else f"workspace limit {width_limit} mm.")))
    components = {part.get("id"): part for part in design.get("components", [])
                  if isinstance(part, dict)}
    boxes = {}
    try:
        for placement in proposal.placements:
            size = components[placement.component_id]["size"]
            if len(size) != 3 or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                     or not math.isfinite(v) or v <= 0 for v in size):
                raise ValueError("Invalid component envelope")
            boxes[placement.component_id] = (
                placement.x_mm - size[0] / 2, placement.x_mm + size[0] / 2,
                placement.z_mm - size[2] / 2, placement.z_mm + size[2] / 2,
            )
    except (KeyError, IndexError, TypeError, ValueError):
        checks.append(_check("envelopes", "Component envelopes", False,
                             "The project must contain valid fixed envelopes for all five parts."))
        return checks
    checks.append(_check("envelopes", "Component envelopes", True,
                         "Fixed project component envelopes are retained."))

    for component_id, (xmin, xmax, zmin, zmax) in boxes.items():
        inside = (xmin >= -proposal.deck_width_mm / 2 + 10
                  and xmax <= proposal.deck_width_mm / 2 - 10
                  and zmin >= -proposal.deck_depth_mm / 2 + 10
                  and zmax <= proposal.deck_depth_mm / 2 - 10)
        checks.append(_check(f"edge_{component_id}", "Deck edge clearance", inside,
                             f"{component_id} requires at least 10 mm to each deck edge."))
        rear_clear = zmin >= -proposal.deck_depth_mm / 2 + 85
        checks.append(_check(f"rear_{component_id}", "Rear gantry strip", rear_clear,
                             f"{component_id} must remain clear of the rear 85 mm strip."))
    for a, b in combinations(MOVABLE_IDS, 2):
        ax0, ax1, az0, az1 = boxes[a]
        bx0, bx1, bz0, bz1 = boxes[b]
        clear = ax1 + 5 <= bx0 or bx1 + 5 <= ax0 or az1 + 5 <= bz0 or bz1 + 5 <= az0
        checks.append(_check(f"clearance_{a}_{b}", "Component separation", clear,
                             f"{a} and {b} need at least 5 mm separation in x or z."))
    return checks


def apply_candidate(project: dict, raw: object, provenance: dict) -> dict:
    """Compile an accepted proposal into the shared project geometry."""
    checks = check_candidate(project, raw)
    failures = [check["detail"] for check in checks if not check["passed"]]
    if failures:
        raise ValueError(" ".join(failures))
    if not isinstance(provenance, dict):
        raise ValueError("Provenance must be an object.")
    proposal = LayoutProposal.model_validate(raw)
    from app.domain import _extend_deck_for_cooling

    result = deepcopy(project)
    design = result["design"]
    design["components"] = [part for part in design["components"] if part["id"] != "cold-storage"]
    components = {part["id"]: part for part in design["components"]}
    width, depth = proposal.deck_width_mm, proposal.deck_depth_mm
    back, column_x = -depth / 2 + 34, width / 2 - 22
    base = components["base"]
    base["size"] = [width, base["size"][1], depth]
    base["position"] = [0, base["position"][1], 0]
    for part_id, x in (("column-left", -column_x), ("column-right", column_x)):
        components[part_id]["position"][0] = x
        components[part_id]["position"][2] = back
    crossbar = components["crossbar"]
    crossbar["position"][2] = back
    crossbar["size"][0] = width - 44
    for part_id in ("carriage", "pipette"):
        components[part_id]["position"][2] = back + 35
    for placement in proposal.placements:
        part = components[placement.component_id]
        part["position"][0] = placement.x_mm
        part["position"][2] = placement.z_mm
    design["footprint"]["width_mm"] = width
    design["footprint"]["depth_mm"] = depth
    design["constraint_status"] = (
        "unconstrained" if result["summary"].get("workspace_width_mm") is None else "fits"
    )
    design["assumptions"] = [
        "Concept geometry and dimensions are illustrative and not supplier-verified.",
        "Deck and crossbar are custom parts; other modeled component sizes are fixed.",
        "The operating deck layout has conservative edge, rear strip and footprint checks only.",
        "The displayed dimensions do not establish motion, collision or hardware feasibility.",
    ]
    cooling = design.get("cooling") or {}
    if cooling.get("enabled"):
        _extend_deck_for_cooling(design, cooling.get("variant_id", ""))
    result["revision"] += 1
    result["status"] = "draft"
    result["engineering_design"] = {
        "schema_version": "1", "proposal": proposal.model_dump(), "provenance": deepcopy(provenance)
    }
    return add_geometry(result)
