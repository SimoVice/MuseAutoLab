"""Versioned concept design for the initial, synthetic aliquoting workstation.

All dimensions are assumed millimetres, not supplier specifications. This model
checks a small set of supported concept layouts; it does not establish travel,
collision clearance, dispensing accuracy, cost, or physical buildability.
"""

from __future__ import annotations

import math
from copy import deepcopy
from uuid import uuid4

from app.catalog import build_sourcing, cooling_envelope, default_selections
from app.dilution import create_dilution_plan
from app.quantities import normalize_concentration, normalize_targets, normalize_volume
from app.workflows import current_kind, describe_workflow, new_brief

TEXT_FIELDS = (
    "stock_concentration",
    "target_concentrations",
    "final_volume",
    "equipment",
)
SUMMARY_FIELDS = frozenset(
    (*TEXT_FIELDS, "workspace_width_mm", "cooling_enabled", "cooling_target_c")
)
PATCH_FIELDS = frozenset((*SUMMARY_FIELDS, "selections"))
BRIEF_FIELDS = ("objective", "process", "materials", "equipment", "constraints")
BRIEF_PATCH_FIELDS = frozenset(
    ("brief_objective", "brief_process", "brief_materials", "brief_equipment", "brief_constraints")
)
WORKFLOW_PATCH_FIELDS = frozenset(("workflow_kind",))
EXTENDED_PATCH_FIELDS = frozenset((*PATCH_FIELDS, *BRIEF_PATCH_FIELDS, *WORKFLOW_PATCH_FIELDS))
WORKFLOW_KINDS = ("unclassified", "general", "liquid_preparation")
LIQUID_QUANTITY_KEYS = ("stock_concentration", "target_concentrations", "final_volume")
WIDE_WIDTH_MM = 600
COMPACT_WIDTH_MM = 400
HEIGHT_MM = 400

COOLING_TARGET_MIN_C = 2.0
COOLING_TARGET_MAX_C = 20.0
COOLING_PROPOSED_TARGET_C = 4.0
OPENTRONS_VARIANT_ID = "opentrons-gen2"


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


def _effective_target(target: float | None) -> tuple[float, str]:
    if target is None:
        return float(COOLING_PROPOSED_TARGET_C), "assumed"
    return float(target), "user"


def _validate_cooling_enabled(value) -> bool:
    if not isinstance(value, bool):
        raise ValueError("cooling_enabled must be a boolean.")
    return value


def _validate_cooling_target(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("cooling_target_c must be a number or null.")
    if not math.isfinite(value):
        raise ValueError("cooling_target_c must be finite.")
    number = float(value)
    if number < COOLING_TARGET_MIN_C or number > COOLING_TARGET_MAX_C:
        raise ValueError("cooling_target_c must be between 2 and 20.")
    return number


def _validate_selections_patch(value) -> dict:
    if not isinstance(value, dict):
        raise ValueError("selections must be an object.")
    for key, option in value.items():
        if not isinstance(key, str) or not isinstance(option, str):
            raise ValueError("selections must map group IDs to option IDs.")
        if not key or not option:
            raise ValueError("selections must map group IDs to option IDs.")
    return dict(value)


def _cooling_info(enabled: bool, target: float | None, selections: dict) -> dict:
    variant_id = str(selections.get("cooling", ""))
    effective, source = _effective_target(target)
    if enabled and variant_id == OPENTRONS_VARIANT_ID and effective < COOLING_PROPOSED_TARGET_C:
        raise ValueError(
            "The Opentrons module cannot target below 4C; "
            "choose a Target of at least 4C or another cooling variant."
        )
    return {
        "enabled": bool(enabled),
        "target_c": float(effective),
        "target_source": source,
        "variant_id": variant_id,
        "transfer_mode": "manual",
        "validation": "unverified",
        "notes": [
            "Refrigerated bay is an attached bay with manual sample transfer.",
            "Operating cycle remains the liquid preparation cycle; no automated cold transfer.",
            "Enclosure size and ventilation clearance are assumed and unverified.",
            "Target is a requested setting, never a measured temperature.",
        ],
    }


def _extend_deck_for_cooling(design: dict, variant_id: str) -> dict:
    """Append the refrigerated bay and extend the custom deck depth."""
    size = [float(v) for v in cooling_envelope(variant_id)]
    original_depth = float(design["footprint"]["depth_mm"])
    added_depth = max(200.0, size[2] + 60.0)
    new_depth = original_depth + added_depth
    design["footprint"]["depth_mm"] = new_depth
    for part in design["components"]:
        if part["id"] == "base":
            part["size"] = [part["size"][0], part["size"][1], new_depth]
            part["position"] = [part["position"][0], part["position"][1], added_depth / 2.0]
            break
    design["components"].append(
        {
            "id": "cold-storage",
            "kind": "cooling",
            "label": "Refrigerated sample bay",
            "position": [0, 20.0 + size[1] / 2.0, original_depth / 2.0 + added_depth / 2.0],
            "size": list(size),
        }
    )
    return design


def _finish_design(
    width, *, cooling_enabled: bool, target, selections: dict
) -> tuple[dict, dict, dict]:
    compact = width is not None and width < WIDE_WIDTH_MM
    design = _layout(compact=compact)
    info = _cooling_info(cooling_enabled, target, selections)
    design["cooling"] = info
    if cooling_enabled:
        _extend_deck_for_cooling(design, info["variant_id"])
    sourcing = build_sourcing(dict(selections), bool(cooling_enabled))
    design["estimated_cost"] = {"amount": sourcing["subtotal"], "currency": "USD"}
    return design, sourcing, info


def new_project() -> dict:
    """Create a draft project with an illustrative wide workstation."""
    summary = {name: None for name in (*TEXT_FIELDS, "workspace_width_mm")}
    summary["cooling_enabled"] = False
    summary["cooling_target_c"] = None
    selections = default_selections()
    sourcing = build_sourcing(dict(selections), False)
    design = _layout(compact=False)
    info = _cooling_info(False, None, selections)
    design["cooling"] = info
    design["estimated_cost"] = {"amount": sourcing["subtotal"], "currency": "USD"}
    project = {
        "id": str(uuid4()),
        "revision": 0,
        "status": "draft",
        "summary": summary,
        "selections": deepcopy(selections),
        "sourcing": deepcopy(sourcing),
        "design": design,
        "plan": _plan_for(summary),
        "brief": new_brief(),
        "workflow": {"kind": "unclassified"},
    }
    project["workflow"] = describe_workflow(project)
    return project


def _plan_for(summary: dict) -> dict:
    return create_dilution_plan(
        summary["stock_concentration"], summary["target_concentrations"], summary["final_volume"]
    )


def _validated_patch(patch: dict) -> dict:
    if not isinstance(patch, dict):
        raise ValueError("The project update must be an object.")
    unknown = set(patch) - EXTENDED_PATCH_FIELDS
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
        elif key in BRIEF_PATCH_FIELDS:
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{key} must be text or null.")
            if isinstance(value, str):
                value = value.strip() or None
                if value is not None and len(value) > 1000:
                    raise ValueError(f"{key} must contain at most 1000 characters.")
        elif key == "workflow_kind":
            if value not in WORKFLOW_KINDS:
                raise ValueError(
                    "workflow_kind must be one of unclassified, general, liquid_preparation."
                )
        elif key == "workspace_width_mm":
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError("workspace_width_mm must be a positive number or null.")
                if not math.isfinite(value) or value <= 0 or value > 5000:
                    raise ValueError(
                        "workspace_width_mm must be greater than 0 and at most 5000 mm."
                    )
                value = float(value)
        elif key == "cooling_enabled":
            value = _validate_cooling_enabled(value)
        elif key == "cooling_target_c":
            value = _validate_cooling_target(value)
        elif key == "selections":
            value = _validate_selections_patch(value)
        validated[key] = value
    return validated


def _project_selections(project: dict) -> dict:
    selections = project.get("selections")
    if selections is None:
        selections = default_selections()
    return deepcopy(dict(selections))


def configure_project(
    project: dict,
    *,
    cooling_enabled: bool | None = None,
    cooling_target_c: float | None = None,
    selections: dict | None = None,
) -> dict:
    """Use the same validated update path for controls and chat."""
    patch = {}
    if cooling_enabled is not None:
        patch["cooling_enabled"] = cooling_enabled
    if cooling_target_c is not None:
        patch["cooling_target_c"] = cooling_target_c
    if selections is not None:
        patch["selections"] = selections
    return apply_update(project, patch)


def _current_brief(project: dict) -> dict:
    brief = new_brief()
    stored = project.get("brief")
    if isinstance(stored, dict):
        for field in BRIEF_FIELDS:
            value = stored.get(field)
            if value is None:
                brief[field] = None
            elif isinstance(value, str):
                brief[field] = value.strip() or None
            else:
                brief[field] = None
    return brief


def _resolve_workflow_kind(project: dict, updates: dict) -> str:
    old_kind = current_kind(project)
    if "workflow_kind" in updates:
        return updates["workflow_kind"]
    if old_kind == "unclassified":
        for key in LIQUID_QUANTITY_KEYS:
            if key in updates and updates[key] is not None:
                value = updates[key]
                if isinstance(value, str) and value.strip():
                    return "liquid_preparation"
                if not isinstance(value, str) and value is not None:
                    return "liquid_preparation"
    return old_kind


def apply_update(project: dict, patch: dict) -> dict:
    """Apply a validated patch without mutating the original project.

    An impossible width is retained as a requirement and marked infeasible; the
    last displayed geometry is preserved so it is not presented as a solution.
    Generic brief fields never intrude into summary; workflow switches refresh.
    """
    updates = _validated_patch(patch)
    current_selections = _project_selections(project)
    old_kind = current_kind(project)
    new_kind = _resolve_workflow_kind(project, updates)

    summary_updates = {k: v for k, v in updates.items() if k in SUMMARY_FIELDS}
    selections_patch = updates.get("selections")
    brief_patch = {}
    for key in BRIEF_PATCH_FIELDS:
        if key in updates:
            brief_patch[key[len("brief_") :]] = updates[key]

    current_brief = _current_brief(project)
    # A width grounded by the model is a project constraint even without a
    # machine adapter. Preserve it in generic planning rather than losing it
    # when only the general brief is sent to the model in later turns.
    if new_kind != "liquid_preparation" and "constraints" not in brief_patch:
        width = summary_updates.get("workspace_width_mm")
        if width is not None:
            old_lines = (current_brief.get("constraints") or "").splitlines()
            kept = [line for line in old_lines if not line.startswith("Available width:")]
            brief_patch["constraints"] = "\n".join([*kept, f"Available width: {width:g} mm"])
    # Resolve equipment mirroring in liquid mode.
    if new_kind == "liquid_preparation":
        liquid_equipment = None
        equipment_touched = False
        if "equipment" in brief_patch:
            liquid_equipment = brief_patch["equipment"]
            equipment_touched = True
        elif "equipment" in summary_updates:
            liquid_equipment = summary_updates["equipment"]
            equipment_touched = True
        if equipment_touched:
            brief_patch["equipment"] = liquid_equipment
            summary_updates["equipment"] = liquid_equipment

    # Fast no-op check including selections, brief and workflow kind.
    summary_noop = all(
        project["summary"].get(key) == value for key, value in summary_updates.items()
    )
    brief_noop = all(current_brief.get(k) == v for k, v in brief_patch.items())
    kind_noop = new_kind == old_kind
    # Switching liquid -> generic always clears scoped fields, so it is effective
    # unless already cleared.
    switching_away = old_kind == "liquid_preparation" and new_kind != "liquid_preparation"
    if selections_patch is not None:
        merged = dict(current_selections)
        merged.update(selections_patch)
        selections_noop = merged == current_selections
    else:
        merged = dict(current_selections)
        selections_noop = True
    if summary_noop and brief_noop and kind_noop and selections_noop:
        result = deepcopy(project)
        result["workflow"] = describe_workflow(result)
        return result

    # Validate selections (even while inactive) before mutating.
    new_enabled_for_check = summary_updates.get(
        "cooling_enabled", project["summary"].get("cooling_enabled", False)
    )
    build_sourcing(dict(merged), bool(new_enabled_for_check))

    # Validate temperature and Opentrons feasibility on the merged state.
    new_target_for_check = summary_updates.get(
        "cooling_target_c", project["summary"].get("cooling_target_c")
    )
    _cooling_info(bool(new_enabled_for_check), new_target_for_check, merged)

    new_width = summary_updates.get(
        "workspace_width_mm", project["summary"].get("workspace_width_mm")
    )
    width_infeasible = new_width is not None and new_width < COMPACT_WIDTH_MM
    cooling_changed = (
        "cooling_enabled" in summary_updates
        or "cooling_target_c" in summary_updates
        or selections_patch is not None
    )
    if width_infeasible and cooling_changed:
        raise ValueError(
            "Width is infeasible; resolve the width before changing cooling configuration."
        )

    result = deepcopy(project)
    if "brief" not in result or not isinstance(result["brief"], dict):
        result["brief"] = new_brief()
    for field in BRIEF_FIELDS:
        if field not in result["brief"]:
            result["brief"][field] = None
    result["brief"].update(brief_patch)
    result["summary"].update(summary_updates)
    if switching_away:
        for key in ("stock_concentration", "target_concentrations", "final_volume", "equipment"):
            result["summary"][key] = None
        result["summary"]["cooling_enabled"] = False
        result["summary"]["cooling_target_c"] = None
    if selections_patch is not None:
        new_full = dict(current_selections)
        new_full.update(selections_patch)
        result["selections"] = new_full
    elif "selections" not in result:
        result["selections"] = deepcopy(current_selections)
    # Brief equipment mirror for liquid consumers.
    if new_kind == "liquid_preparation":
        if (
            result["brief"].get("equipment") is None
            and result["summary"].get("equipment") is not None
        ):
            result["brief"]["equipment"] = result["summary"]["equipment"]
        elif (
            result["summary"].get("equipment") is None
            and result["brief"].get("equipment") is not None
        ):
            result["summary"]["equipment"] = result["brief"]["equipment"]
    result["workflow"] = {"kind": new_kind}
    result["plan"] = _plan_for(result["summary"])

    width = result["summary"]["workspace_width_mm"]
    enabled = bool(result["summary"].get("cooling_enabled", False))
    target = result["summary"].get("cooling_target_c")
    stored_selections = deepcopy(dict(result.get("selections", current_selections)))
    sourcing = build_sourcing(dict(stored_selections), enabled)
    result["selections"] = deepcopy(stored_selections)
    result["sourcing"] = deepcopy(sourcing)

    if width is not None and width < COMPACT_WIDTH_MM:
        result["design"]["constraint_status"] = "infeasible"
        # Preserve last geometry but refresh cooling metadata and partial cost.
        result["design"]["cooling"] = _cooling_info(enabled, target, stored_selections)
        result["design"]["estimated_cost"] = {"amount": sourcing["subtotal"], "currency": "USD"}
    else:
        design, _, _ = _finish_design(
            width, cooling_enabled=enabled, target=target, selections=stored_selections
        )
        design["constraint_status"] = "unconstrained" if width is None else "fits"
        result["design"] = design
    result["revision"] += 1
    result["status"] = "draft"
    result["workflow"] = describe_workflow(result)
    return result


def confirm_project(project: dict) -> dict:
    """Confirm a complete feasible draft; this does not execute a protocol."""
    kind = current_kind(project)
    if kind != "liquid_preparation":
        raise ValueError(
            "Describe the automation workflow first. Concept planning is available; "
            "3D simulation and build packages require a supported workflow."
        )
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
