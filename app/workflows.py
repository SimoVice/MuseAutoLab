"""Generic workflow registry and helpers.

Dilution/aliquoting (liquid_preparation) is one supported adapter, not the
platform identity. Other work stays in a generic discovery/planning branch
that never claims 3D, cost, simulation or build output.
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
        "capabilities": ["discovery", "brief planning"],
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
    return {
        "kind": kind,
        "label": entry["label"],
        "status": entry["status"],
        "design_available": design_available,
        "parameters_started": parameters_started,
    }
