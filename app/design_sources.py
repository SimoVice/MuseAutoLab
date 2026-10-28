"""Reviewed primary references and explicit bindings to actual concept geometry."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

_PATH = Path(__file__).resolve().parent / "data" / "design-references-2026-10-28.json"
_DATA = json.loads(_PATH.read_text(encoding="utf-8"))
_DATA["sha256"] = sha256(_PATH.read_bytes()).hexdigest()
_REFERENCES = {record["id"]: record for record in _DATA["references"]}
REFERENCE_IDS = tuple(_REFERENCES)


def reference_library() -> dict:
    return deepcopy(_DATA)


def resolve_reference(reference_id: str) -> dict:
    if reference_id not in _REFERENCES:
        raise ValueError("The reference is not in the reviewed source library.")
    return deepcopy(_REFERENCES[reference_id])


def component_geometry_specs(project: dict) -> dict:
    motor_id = project.get("selections", {}).get("motors", "pololu-1209")
    if motor_id not in ("pololu-1209", "pololu-1208"):
        raise ValueError("No reviewed geometry is available for this motor.")
    ref = resolve_reference(motor_id)
    return {
        "carriage": {
            "motor": {
                "reference_id": motor_id,
                "size_mm": ref["body_size_app_mm"],
                "scope": "Manufacturer motor body, excluding shaft",
            }
        }
    }


def camera_geometry_spec() -> dict:
    ref = resolve_reference("rpi-camera-module-3")
    return {
        "reference_id": ref["id"],
        "size_mm": ref["body_size_app_mm"],
        "scope": "Manufacturer overall envelope, standard lens; Y is optical/thickness axis",
    }


def project_source_basis(project: dict) -> dict:
    supported = project.get("workflow", {}).get("kind") == "liquid_preparation"
    parts = project.get("design", {}).get("components", []) if supported else []
    specs = component_geometry_specs(project)
    bindings = []
    for part in parts:
        pid = part["id"]
        if pid == "carriage":
            motor = specs[pid]["motor"]
            bindings.append(
                {
                    "component_id": pid,
                    "primitive_id": "motor",
                    "basis": "manufacturer_envelope",
                    "reference_id": motor["reference_id"],
                    "detail": "Motor body uses supplier dimensions; the carriage is custom.",
                }
            )
        elif pid == "inspection-camera":
            bindings.append(
                {
                    "component_id": pid,
                    "basis": "manufacturer_envelope",
                    "reference_id": "rpi-camera-module-3",
                    "detail": "Camera envelope; board/lens details and mount are custom.",
                }
            )
        elif (
            pid == "cold-storage"
            and project.get("selections", {}).get("cooling") == "opentrons-gen2"
        ):
            bindings.append(
                {
                    "component_id": pid,
                    "basis": "manufacturer_envelope",
                    "reference_id": "opentrons-temp-module-gen2",
                    "detail": "Published outer envelope; displayed details are a custom proxy.",
                }
            )
        else:
            bindings.append(
                {
                    "component_id": pid,
                    "basis": "custom_concept",
                    "reference_id": None,
                    "detail": "Custom concept; dimensions and interfaces remain unverified.",
                }
            )
    return {
        "schema_version": "1",
        "checked_on": _DATA["checked_on"],
        "library_sha256": _DATA["sha256"],
        "architecture": (
            "MuseAutoLab custom XYZ workstation; not an imported Jubilee robot"
            if supported
            else "Workflow discovery; no machine adapter chosen"
        ),
        "bindings": bindings,
        "references": reference_library()["references"],
        "open_hardware_status": "Reviewed reference projects; their CAD has not been imported",
    }


def reference_context(project: dict) -> dict:
    basis = project_source_basis(project)
    return {
        "policy": "Recommend only library entries; never invent URLs, licenses, dimensions or "
        "compatibility. A reviewed source is not tested hardware. Open projects are candidate "
        "foundations, not the current custom robot. Missing evidence must remain explicit.",
        "architecture": basis["architecture"],
        "library_sha256": basis["library_sha256"],
        "geometry_bindings": basis["bindings"],
        "library": basis["references"],
    }
