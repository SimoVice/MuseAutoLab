"""Generic workflow registry and helpers.

Dilution/aliquoting (liquid_preparation) is one supported adapter, not the
platform identity. General tasks support proposed functional planning; the
bounded bench adapter additionally supplies a schematic and human-operated plan.
Neither general route claims arbitrary machine CAD, physics or hardware control.
"""

from __future__ import annotations

WORKFLOW_KINDS = ("unclassified", "general", "liquid_preparation")

REGISTRY = {
    "unclassified": {
        "label": "Unclassified",
        "status": "discovery",
        "capabilities": ["discovery", "brief planning"],
    },
    "general": {
        "label": "General concept",
        "status": "planning",
        "capabilities": ["discovery", "brief planning", "functional planning"],
    },
    "liquid_preparation": {
        "label": "Liquid preparation",
        "status": "supported_concept",
        "capabilities": ["discovery", "brief planning", "3d", "calculation", "physics", "build"],
    },
}

_BRIEF_FIELDS = ("objective", "process", "materials", "equipment", "constraints")

_LIQUID_QUANTITY_KEYS = ("stock_concentration", "target_concentrations", "final_volume")


def new_brief() -> dict:
    """Return an empty generic brief."""
    return {name: None for name in _BRIEF_FIELDS}


def _stored_kind(project: dict) -> str | None:
    workflow = project.get("workflow")
    if isinstance(workflow, dict):
        kind = workflow.get("kind")
        if kind in WORKFLOW_KINDS:
            return kind
    return None


def _infer_legacy_kind(project: dict) -> str:
    """Fallback for projects stored before the workflow field existed.

    Only old quantitative fields may suggest the liquid adapter; equipment,
    width or cooling alone never select it.
    """
    summary = project.get("summary") or {}
    for key in _LIQUID_QUANTITY_KEYS:
        value = summary.get(key)
        if isinstance(value, str) and value.strip():
            return "liquid_preparation"
    return "unclassified"


def current_kind(project: dict) -> str:
    """Return the stored kind, falling back to legacy inference."""
    kind = _stored_kind(project)
    if kind is not None:
        return kind
    return _infer_legacy_kind(project)


def describe_workflow(project: dict) -> dict:
    """Derive the public workflow shape without mutating the project."""
    kind = current_kind(project)
    entry = REGISTRY[kind]
    design_available = kind == "liquid_preparation"
    parameters_started = False
    if kind == "liquid_preparation":
        summary = project.get("summary") or {}
        for key in _LIQUID_QUANTITY_KEYS:
            value = summary.get(key)
            if isinstance(value, str) and value.strip():
                parameters_started = True
                break
    result = {
        "kind": kind,
        "label": entry["label"],
        "status": entry["status"],
        "design_available": design_available,
        "parameters_started": parameters_started,
    }
    if kind == "general":
        station = project.get("bench_station")
        if station:
            result.update(
                label="Human-operated bench station",
                status="supported_concept",
                capabilities=["brief planning", "schematic 3d", "ordered human operations",
                              "parts planning", "software starter"],
                scope="Schematic planning allocations and a human-operated workflow. "
                      "Candidate equipment and cost allowances require review; no fabrication "
                      "CAD, physics validation or hardware control is provided.",
            )
        else:
            result.update(
                capabilities=["discovery", "brief planning", "functional planning"],
                scope="The recorded brief can be developed on request into proposed operations, "
                      "equipment roles, data handoffs and acceptance checks. Specifications "
                      "require review; arbitrary machine CAD, quotes and control are unavailable.",
            )
    return result


def has_workstation_design_context(project: dict) -> bool:
    """Allow sourced conceptual layout discovery without inventing owned equipment.

    A recorded liquid workflow with an explicitly selected supported base, process
    and materials is enough to propose a workstation. This is not execution,
    labware compatibility, dispensing readiness or physical confirmation.
    Existing declared equipment preserves the legacy design path.
    """
    if current_kind(project) != "liquid_preparation":
        return False
    brief, summary = project.get("brief") or {}, project.get("summary") or {}
    if any(isinstance(value, str) and value.strip() for value in (
        summary.get("equipment"), brief.get("equipment")
    )):
        return True
    selected = (project.get("engineering") or {}).get("selected_platform_id")
    if (_stored_kind(project) != "liquid_preparation"
            or selected not in ("jubilee", "opentrons-ot2")):
        return False
    return all(isinstance(brief.get(key), str) and brief[key].strip()
               for key in ("process", "materials"))


def workstation_context_question(project: dict) -> str:
    """Ask for the first missing conceptual input, without assuming ownership."""
    brief = project.get("brief") or {}
    selected = (project.get("engineering") or {}).get("selected_platform_id")
    if selected not in ("jubilee", "opentrons-ot2"):
        return (
            "Describe the equipment in chat, or record the liquid process and materials "
            "and choose a sourced platform before developing a workstation."
        )
    if not isinstance(brief.get("process"), str) or not brief["process"].strip():
        return "What liquid preparation process should this workstation automate?"
    return "Which materials or containers should this workstation handle?"
