"""Versioned concept design for the initial, synthetic aliquoting workstation.

All dimensions are assumed millimetres, not supplier specifications. This model
checks a small set of supported concept layouts; it does not establish travel,
collision clearance, dispensing accuracy, cost, or physical buildability.
"""

from __future__ import annotations

import math
from copy import deepcopy
from uuid import uuid4

from app.dilution import create_dilution_plan
from app.quantities import normalize_concentration, normalize_targets, normalize_volume

TEXT_FIELDS = (
    "stock_concentration",
    "target_concentrations",
    "final_volume",
    "equipment",
)
SUMMARY_FIELDS = frozenset((*TEXT_FIELDS, "workspace_width_mm"))
WIDE_WIDTH_MM = 600
COMPACT_WIDTH_MM = 400
HEIGHT_MM = 400


def _component(
    component_id: str,
    kind: str,
    label: str,
    position: tuple[float, float, float],
    size: tuple[float, float, float],
) -> dict:
    """A component is a centred box in x/y/z; y is the vertical axis."""
    return {
        "id": component_id,
        "kind": kind,
        "label": label,
        "position": list(position),
        "size": list(size),
    }


def _layout(compact: bool) -> dict:
    """Generate one of two proposed arrangements with stable component IDs.

    The base and crossbar are custom, dimensioned to the chosen arrangement;
    every other component retains its assumed dimensions between arrangements.
    """
    width = COMPACT_WIDTH_MM if compact else WIDE_WIDTH_MM
    depth = 470 if compact else 370
    back = -depth / 2 + 34
    column_x = width / 2 - 22
    if compact:
        source, destination, tips = (-112, -45), (0, -45), (112, -45)
        waste, controller = (-120, 120), (120, 120)
    else:
        source, destination, tips = (-160, 55), (-45, 55), (70, 55)
        waste, controller = (200, 65), (195, -90)

    components = [
        _component("base", "base", "Custom deck", (0, 10, 0), (width, 20, depth)),
        _component(
            "column-left", "column", "Left frame post", (-column_x, 160, back), (22, 300, 22)
        ),
        _component(
            "column-right", "column", "Right frame post", (column_x, 160, back), (22, 300, 22)
        ),
        _component(
            "crossbar", "rail", "Custom frame crossbar", (0, 304, back), (width - 44, 18, 18)
        ),
        _component(
            "carriage", "carriage", "Pipette carriage concept", (0, 264, back + 35), (75, 70, 65)
        ),
        _component("pipette", "pipette", "Pipette concept", (0, 155, back + 35), (28, 155, 28)),
        _component(
            "source-rack", "rack", "Source tube rack", (source[0], 42, source[1]), (95, 44, 70)
        ),
        _component(
            "sample-rack",
            "rack",
            "Sample tube rack",
            (destination[0], 42, destination[1]),
            (95, 44, 70),
        ),
        _component("tip-rack", "tiprack", "Tip rack", (tips[0], 42, tips[1]), (95, 44, 70)),
        _component(
            "tip-waste", "waste", "Tip waste container", (waste[0], 60, waste[1]), (55, 80, 55)
        ),
        _component(
            "controller",
            "controller",
            "Controller enclosure concept",
            (controller[0], 45, controller[1]),
            (90, 50, 80),
        ),
    ]
    return {
        "footprint": {"width_mm": width, "depth_mm": depth, "height_mm": HEIGHT_MM},
        "components": components,
        "constraint_status": "unconstrained",
        "estimated_cost": {"amount": None, "currency": "USD"},
        "assumptions": [
            "Concept geometry and dimensions are illustrative and not supplier-verified.",
            "Deck and crossbar are custom parts; other modeled component sizes are fixed.",
            "Only the wide and compact arrangements are supported in this preview.",
            "The displayed dimensions do not establish motion, collision or hardware feasibility.",
        ],
    }


def new_project() -> dict:
    """Create a draft project with an illustrative wide workstation."""
    summary = {name: None for name in (*TEXT_FIELDS, "workspace_width_mm")}
    return {
        "id": str(uuid4()),
        "revision": 0,
        "status": "draft",
        "summary": summary,
        "design": _layout(compact=False),
        "plan": _plan_for(summary),
    }


def _plan_for(summary: dict) -> dict:
    return create_dilution_plan(
        summary["stock_concentration"], summary["target_concentrations"], summary["final_volume"]
    )


def _validated_patch(patch: dict) -> dict:
    if not isinstance(patch, dict):
        raise ValueError("The project update must be an object.")
    unknown = set(patch) - SUMMARY_FIELDS
    if unknown:
        raise ValueError(f"Unsupported project fields: {', '.join(sorted(unknown))}.")
    validated = {}
    for key, value in patch.items():
        if key in TEXT_FIELDS:
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{key} must be text or null.")
            if isinstance(value, str):
                value = value.strip() or None
                if value is not None and len(value) > 1000:
                    raise ValueError(f"{key} must contain at most 1000 characters.")
                normalizer = {
                    "stock_concentration": normalize_concentration,
                    "target_concentrations": normalize_targets,
                    "final_volume": normalize_volume,
                }.get(key)
                if value is not None and normalizer:
                    try:
                        value = normalizer(value)
                    except ValueError:
                        # Keep the user's requirement so the plan can explain what needs correcting.
                        pass
        elif value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("workspace_width_mm must be a positive number or null.")
            if not math.isfinite(value) or value <= 0 or value > 5000:
                raise ValueError("workspace_width_mm must be greater than 0 and at most 5000 mm.")
            value = float(value)
        validated[key] = value
    return validated


def apply_update(project: dict, patch: dict) -> dict:
    """Apply a validated patch without mutating the original project.

    An impossible width is retained as a requirement and marked infeasible; the
    last displayed geometry is preserved so it is not presented as a solution.
    """
    updates = _validated_patch(patch)
    result = deepcopy(project)
    if all(result["summary"][key] == value for key, value in updates.items()):
        return result
    result["summary"].update(updates)
    result["plan"] = _plan_for(result["summary"])
    width = result["summary"]["workspace_width_mm"]
    if width is not None and width < COMPACT_WIDTH_MM:
        result["design"]["constraint_status"] = "infeasible"
    else:
        result["design"] = _layout(compact=width is not None and width < WIDE_WIDTH_MM)
        result["design"]["constraint_status"] = "unconstrained" if width is None else "fits"
    result["revision"] += 1
    result["status"] = "draft"
    return result


def confirm_project(project: dict) -> dict:
    """Confirm a complete feasible draft; this does not execute a protocol."""
    missing = [name for name in TEXT_FIELDS if not project["summary"].get(name)]
    if missing:
        raise ValueError(f"Required parameters are missing: {', '.join(missing)}.")
    if project["design"]["constraint_status"] == "infeasible":
        raise ValueError("The requested workspace width is infeasible for the supported layouts.")
    if project["plan"]["status"] != "ready":
        raise ValueError(f"Dilution plan needs attention: {project['plan']['message']}")
    result = deepcopy(project)
    if result["status"] != "confirmed":
        result["status"] = "confirmed"
        result["revision"] += 1
    return result
