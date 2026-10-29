"""Bounded, schematic OT-2 platform and official deck-slot layout.

The exterior envelope and slot coordinates are published references. The frame,
internal deck elevation, pipette and labware are illustrative proxies, not vendor
CAD or a fabrication design. No mounting, travel, collision, compatibility,
control, pipetting performance, price or availability is established here.
"""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PLATFORM_ID = "opentrons-ot2"
ENVELOPE_MM = (630.0, 660.0, 570.0)  # width, height, depth
SLOT_IDS = tuple(str(i) for i in range(1, 12))
ASSIGNABLE_COMPONENTS = ("source-rack", "sample-rack", "tip-rack")
DECK_TOP_MM = 155.0  # illustrative, not a manufacturer dimension
VENTILATION_CLEARANCE_MM = 200.0
OPERATING_WIDTH_MM = ENVELOPE_MM[0] + 2 * VENTILATION_CLEARANCE_MM
DECK_PATH = Path(__file__).resolve().parent / "data" / "ot2" / "deck.json"
PROVENANCE_PATH = DECK_PATH.with_name("provenance.json")
DECK_SHA256 = "f9bde02d43314e42c64d12f1a0d6d4f4aceb448371d37def27de76ff8a308e90"
DECK_REVISION = "95a8a37922cfd5f46ad26c983bcc1659fa13b6e1"
DECK_SOURCE_URL = (
    "https://github.com/Opentrons/opentrons/blob/"
    + DECK_REVISION
    + "/shared-data/deck/definitions/3/ot2_standard.json"
)
DECK_LICENSE_URL = "https://github.com/Opentrons/opentrons/blob/" + DECK_REVISION + "/LICENSE"


def _deck_source() -> tuple[dict, dict, dict]:
    """Load the exact reviewed source and refuse altered data or provenance."""
    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    data = DECK_PATH.read_bytes()
    if (
        provenance.get("sha256") != DECK_SHA256
        or provenance.get("revision") != DECK_REVISION
        or provenance.get("license") != "Apache-2.0"
        or provenance.get("source_url") != DECK_SOURCE_URL
        or provenance.get("license_url") != DECK_LICENSE_URL
        or sha256(data).hexdigest() != DECK_SHA256
    ):
        raise ValueError(
            "Pinned OT-2 deck source or provenance does not match the reviewed revision."
        )
    deck = json.loads(data)
    slots = {slot["id"]: slot for slot in deck["locations"]["orderedSlots"]}
    if set(slots) != {str(i) for i in range(1, 13)}:
        raise ValueError("Pinned OT-2 deck must contain slots 1 through 12.")
    return deck, provenance, slots


def _slot_grid_bounds(slots: dict) -> tuple[float, float, float, float]:
    return (
        min(slot["position"][0] for slot in slots.values()),
        max(slot["position"][0] + slot["boundingBox"]["xDimension"] for slot in slots.values()),
        min(slot["position"][1] for slot in slots.values()),
        max(slot["position"][1] + slot["boundingBox"]["yDimension"] for slot in slots.values()),
    )


def commercial_metadata() -> dict:
    """Return immutable published references and explicit representation limits."""
    _deck, provenance, slots = _deck_source()
    slot_box = slots["1"]["boundingBox"]
    return {
        "id": PLATFORM_ID,
        "label": "Opentrons OT-2",
        "manufacturer": "Opentrons",
        "kind": "prebuilt_platform",
        "envelope_mm": list(ENVELOPE_MM),
        "envelope_order": "width, height, depth",
        "source_url": "https://opentrons.com/products/ot-2-robot",
        "specifications_url": "https://docs.opentrons.com/ot-2/system-description/specs/",
        "deck_slots_url": "https://docs.opentrons.com/python-api/deck-slots/",
        "deck_definition_url": provenance["source_url"],
        "deck_definition_revision": DECK_REVISION,
        "deck_definition_sha256": DECK_SHA256,
        "deck_definition_license": provenance["license"],
        "deck_definition_license_url": provenance["license_url"],
        "slot_size_mm": [slot_box["xDimension"], slot_box["yDimension"]],
        "operating_clearance_mm": VENTILATION_CLEARANCE_MM,
        "minimum_operating_width_mm": OPERATING_WIDTH_MM,
        "operating_clearance_scope": "Allow 200 mm around the device for ventilation; "
        "width includes the body plus both side clearances. Other access needs are unchecked.",
        "envelope_source_scope": "Catalogue specifies width 630, depth 570 and height 660 mm; "
        "specifications page lists the same dimensions without an axis order.",
        "usable_slot_ids": list(SLOT_IDS),
        "fixed_trash_slot_id": "12",
        "pipette_mounts": 2,
        "geometry_scope": "Manufacturer outer envelope and deck slot coordinates; "
        "all represented internal and frame geometry is schematic and unverified.",
        "limitations": [
            "Labware, pipette compatibility, adapter interfaces and travel are unchecked.",
            "OT-2 needs compatible instrument pipettes; manual pipettes are not "
            "assumed compatible.",
            "Cooling and custom inspection modules are unsupported pending integration.",
            "No physical collision, control or laboratory validation is represented.",
        ],
    }


class SlotAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    component_id: Literal["source-rack", "sample-rack", "tip-rack"]
    slot_id: Literal["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"]


class CommercialProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["1"]
    slot_assignments: Annotated[list[SlotAssignment], Field(min_length=3, max_length=3)]
    rationale: Annotated[str, Field(max_length=1200)]
    assumptions: Annotated[list[Annotated[str, Field(max_length=300)]], Field(max_length=6)]

    @model_validator(mode="after")
    def distinct_assignments(self) -> CommercialProposal:
        if {a.component_id for a in self.slot_assignments} != set(ASSIGNABLE_COMPONENTS):
            raise ValueError("Assign each required component exactly once.")
        if len({a.slot_id for a in self.slot_assignments}) != len(ASSIGNABLE_COMPONENTS):
            raise ValueError("Each component must use a distinct slot.")
        return self


def commercial_proposal_schema() -> dict:
    return CommercialProposal.model_json_schema()


def _part(part_id: str, kind: str, label: str, position: list, size: list) -> dict:
    return {"id": part_id, "kind": kind, "label": label, "position": position, "size": size}


def _slot_center(slot_id: str) -> tuple[float, float]:
    """Translate the published x/y grid into app x/z about the grid centre.

    Absolute machine-to-deck pose and the z-axis front/back convention are not
    established by this schematic. The deck definition uses lower-left origins.
    """
    _deck, _provenance, slots = _deck_source()
    xmin, xmax, ymin, ymax = _slot_grid_bounds(slots)
    slot = slots[slot_id]
    position, bounds = slot["position"], slot["boundingBox"]
    return (
        position[0] + bounds["xDimension"] / 2 - (xmin + xmax) / 2,
        position[1] + bounds["yDimension"] / 2 - (ymin + ymax) / 2,
    )


def adopt_commercial(project: dict) -> dict:
    """Select the fixed manufacturer envelope, without accepting a layout."""
    result = deepcopy(project)
    design = result["design"]
    design.pop("foundation", None)
    design["platform"] = commercial_metadata()
    result.pop("engineering_design", None)
    _deck, _provenance, slots = _deck_source()
    xmin, xmax, ymin, ymax = _slot_grid_bounds(slots)
    # Frame rails merely communicate the fixed envelope; they are not vendor CAD.
    parts = [
        _part(
            "base",
            "base",
            "Schematic deck (elevation illustrative)",
            [0, DECK_TOP_MM - 6, 0],
            [xmax - xmin, 12, ymax - ymin],
        ),
        _part(
            "ot2-envelope-left",
            "commercial-proxy",
            "Schematic outer left",
            [-309, 330, -279],
            [12, 660, 12],
        ),
        _part(
            "ot2-envelope-right",
            "commercial-proxy",
            "Schematic outer right",
            [309, 330, -279],
            [12, 660, 12],
        ),
        _part(
            "ot2-envelope-top",
            "commercial-proxy",
            "Schematic outer top",
            [0, 654, -279],
            [630, 12, 12],
        ),
        _part(
            "ot2-envelope-lower",
            "commercial-proxy",
            "Schematic outer base",
            [0, 6, 0],
            [630, 12, 570],
        ),
        _part(
            "carriage",
            "commercial-proxy",
            "Schematic pipette mount (unverified)",
            [0, 390, -140],
            [85, 80, 60],
        ),
        _part(
            "pipette",
            "pipette",
            "Compatible pipette placeholder (not selected)",
            [0, 275, -140],
            [28, 150, 28],
        ),
        _part(
            "source-rack",
            "rack",
            "Source rack placeholder (compatibility unverified)",
            [0, DECK_TOP_MM + 22, 0],
            [95, 44, 70],
        ),
        _part(
            "sample-rack",
            "rack",
            "Sample rack placeholder (compatibility unverified)",
            [0, DECK_TOP_MM + 22, 0],
            [95, 44, 70],
        ),
        _part(
            "tip-rack",
            "tiprack",
            "Tip rack placeholder (compatibility unverified)",
            [0, DECK_TOP_MM + 22, 0],
            [95, 44, 70],
        ),
        _part(
            "tip-waste",
            "waste",
            "Fixed trash placeholder (slot 12)",
            [0, DECK_TOP_MM + 40, 0],
            [55, 80, 55],
        ),
    ]
    # Draft positions are illustrative; accepted assignments are applied at compile time.
    for part, slot in zip(parts[-4:], ("1", "2", "3", "12")):
        part["position"][0], part["position"][2] = _slot_center(slot)
        part["slot_id"] = slot
    design["components"] = parts
    design["footprint"] = {"width_mm": 630.0, "height_mm": 660.0, "depth_mm": 570.0}
    width = result.get("summary", {}).get("workspace_width_mm")
    design["constraint_status"] = (
        "unconstrained"
        if width is None
        else (
            "fits"
            if isinstance(width, (int, float))
            and not isinstance(width, bool)
            and width >= OPERATING_WIDTH_MM
            else "infeasible"
        )
    )
    design["estimated_cost"] = {"amount": None, "currency": "USD"}
    design["assumptions"] = [
        "Only the published external envelope and deck slot grid are sourced; "
        "frame and internal geometry and deck height are schematic.",
        "Rack and pipette proxies are not selected, measured or confirmed compatible.",
        "Deck slot assignment is not a mounting, reach, collision or physical validation.",
        "Cooling and custom inspection are unsupported on this platform pending integration.",
        "Allow 200 mm ventilation clearance around the device; access requirements are unchecked.",
    ]
    design["assembly_bounds"] = {"min_mm": [-315, 0, -285], "max_mm": [315, 660, 285]}
    result["status"] = "draft"
    return result


def _check(check_id: str, label: str, passed: bool, detail: str) -> dict:
    return {"id": check_id, "label": label, "passed": bool(passed), "detail": detail}


def check_commercial_candidate(project: dict, raw: object) -> list[dict]:
    """Validate slot assignment and explicit integration limits, not physical fit."""
    design = project.get("design") or {}
    workflow = project.get("workflow") or {}
    summary = project.get("summary") or {}
    width = summary.get("workspace_width_mm")
    checks = [
        _check(
            "platform",
            "Selected platform",
            design.get("platform", {}).get("id") == PLATFORM_ID,
            "The OT-2 platform must be selected explicitly.",
        ),
        _check(
            "workflow",
            "Supported workflow",
            workflow.get("kind") == "liquid_preparation"
            and workflow.get("design_available") is True,
            "Liquid preparation with design enabled is required.",
        ),
        _check(
            "workspace_width",
            "Workspace width including ventilation",
            width is None
            or (
                isinstance(width, (int, float))
                and not isinstance(width, bool)
                and width >= OPERATING_WIDTH_MM
            ),
            "The 630 mm body plus 200 mm ventilation clearance on each side requires "
            "at least 1030 mm; other access requirements are unchecked.",
        ),
        _check(
            "cooling",
            "Cooling integration",
            not (summary.get("cooling_enabled") or (design.get("cooling") or {}).get("enabled")),
            "Cooling integration on this platform is unsupported.",
        ),
        _check(
            "inspection",
            "Inspection integration",
            not project.get("inspection_extension"),
            "Custom inspection integration on this platform is unsupported.",
        ),
    ]
    try:
        candidate = CommercialProposal.model_validate(raw)
    except ValidationError as exc:
        for index, error in enumerate(exc.errors(include_url=False, include_input=False)):
            location = ".".join(str(part) for part in error["loc"]) or "proposal"
            checks.append(
                _check(f"schema_{index}", "Proposal format", False, f"{location}: {error['msg']}")
            )
        return checks
    checks.append(
        _check(
            "schema",
            "Proposal format",
            True,
            "Three distinct components occupy distinct slots 1–11; trash remains in slot 12.",
        )
    )
    _deck, _provenance, slots = _deck_source()
    slot_fit = all(
        slots[a.slot_id]["boundingBox"]["xDimension"] >= 95
        and slots[a.slot_id]["boundingBox"]["yDimension"] >= 70
        for a in candidate.slot_assignments
    )
    checks.append(
        _check(
            "slot_envelopes",
            "Illustrative rack envelopes",
            slot_fit,
            "The 95 × 70 mm placeholders are compared with the pinned nominal slot rectangles; "
            "actual labware fit and clearances are unchecked.",
        )
    )
    return checks


def compile_commercial_layout(project: dict, raw: object, provenance: dict) -> dict:
    """Compile only a valid assignment into the shared viewer/CAD representation."""
    failures = [c["detail"] for c in check_commercial_candidate(project, raw) if not c["passed"]]
    if failures:
        raise ValueError(" ".join(failures))
    if not isinstance(provenance, dict):
        raise ValueError("Provenance must be an object.")
    proposal = CommercialProposal.model_validate(raw)
    result = adopt_commercial(project)
    components = {part["id"]: part for part in result["design"]["components"]}
    for assignment in proposal.slot_assignments:
        part = components[assignment.component_id]
        part["position"][0], part["position"][2] = _slot_center(assignment.slot_id)
        part["slot_id"] = assignment.slot_id
    result["revision"] += 1
    result["engineering_design"] = {
        "schema_version": "1",
        "proposal": proposal.model_dump(),
        "provenance": deepcopy(provenance),
    }
    from app.geometry import add_geometry

    return add_geometry(result)
