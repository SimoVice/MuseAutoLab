"""Deterministic illustrative component geometry in application coordinates, mm.

Interfaces, process, material, clearances and loads are unverified. This is not
a fabrication design. Physics retains conservative component envelopes.
"""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from app.design_sources import component_geometry_specs

# Capture provenance when this module is loaded, not when an export is requested.
GEOMETRY_SOURCE_SHA256 = sha256(Path(__file__).read_bytes()).hexdigest()


def geometry_for_component(comp: dict) -> dict:
    """Return local, centred primitives contained by the component envelope."""
    sx, sy, sz = map(float, comp["size"])
    kind = comp["kind"]
    p = []

    def add(name, shape, pos, size, appearance, **extra):
        p.append(
            dict(
                id=name,
                kind=shape,
                position=list(pos),
                size=list(size),
                appearance=appearance,
                **extra,
            )
        )

    def box(name, pos, size, appearance="structure"):
        add(name, "box", pos, size, appearance)

    def round_part(name, shape, y, h, diameter, appearance, **extra):
        add(name, shape, (0, y, 0), (diameter, h, diameter), appearance, axis="y", **extra)

    if kind == "base":
        box("blank", (0, 0, 0), (sx, sy, sz), "deck")
    elif kind in ("column", "rail"):
        # Extrusion-like cross section, rendered as an arrangement of rails.
        if kind == "column":
            box("core", (0, 0, 0), (sx * 0.56, sy, sz * 0.56), "frame")
            for sign in (-1, 1):
                box(f"side-{sign}", (sign * sx * 0.39, 0, 0), (sx * 0.22, sy, sz), "frame")
                box(f"face-{sign}", (0, 0, sign * sz * 0.39), (sx * 0.56, sy, sz * 0.22), "rail")
        else:
            box("core", (0, 0, 0), (sx, sy * 0.56, sz * 0.56), "frame")
            for sign in (-1, 1):
                box(f"edge-{sign}", (0, sign * sy * 0.39, 0), (sx, sy * 0.22, sz), "frame")
                box(f"guide-{sign}", (0, 0, sign * sz * 0.39), (sx, sy * 0.56, sz * 0.22), "rail")
    elif kind == "carriage":
        box("backplate", (0, 0, -sz * 0.38), (sx, sy, sz * 0.24), "structure")
        motor = comp.get("reference_geometry", {}).get("motor")
        if motor:
            add(
                "motor", "box", (-sx / 2 + motor["size_mm"][0] / 2, sy * 0.12, -sz * 0.07),
                motor["size_mm"], "motor", reference_id=motor["reference_id"],
                dimension_basis="manufacturer_envelope", scope=motor["scope"],
            )
        else:
            box(
                "motor", (-sx * 0.22, sy * 0.12, -sz * 0.07),
                (sx * 0.38, sy * 0.58, sz * 0.38), "motor"
            )
        box("drive", (sx * 0.21, sy * 0.08, -sz * 0.06), (sx * 0.28, sy * 0.65, sz * 0.40), "rail")
        box("holder-upper", (0, sy * 0.30, sz * 0.29), (sx * 0.68, sy * 0.20, sz * 0.42), "holder")
        box("holder-lower", (0, -sy * 0.30, sz * 0.29), (sx * 0.68, sy * 0.20, sz * 0.42), "holder")
    elif kind == "pipette":
        d = min(sx, sz)
        round_part("body", "cylinder", sy * 0.16, sy * 0.68, d, "pipette")
        round_part(
            "shoulder",
            "frustum",
            -sy * 0.24,
            sy * 0.12,
            d,
            "pipette",
            radius_top_mm=d / 2,
            radius_bottom_mm=d * 0.24,
        )
        round_part("shaft", "cylinder", -sy * 0.37, sy * 0.14, d * 0.48, "pipette")
        round_part(
            "nozzle",
            "frustum",
            -sy * 0.47,
            sy * 0.06,
            d * 0.48,
            "pipette",
            radius_top_mm=d * 0.24,
            radius_bottom_mm=d * 0.12,
        )
    elif kind in ("rack", "tiprack"):
        box("floor", (0, -sy * 0.44, 0), (sx, sy * 0.12, sz), "rack")
        for sign in (-1, 1):
            box(
                f"side-{sign}",
                (sign * sx * 0.465, -sy * 0.06, 0),
                (sx * 0.07, sy * 0.76, sz),
                "rack",
            )
        count = (
            4
            if kind == "tiprack"
            else (2 if comp["id"] == "source-rack" else comp.get("rack_slot_count", 1))
        )
        spacing = min(20, sx / (count + 1))
        centers = [(i - (count - 1) / 2) * spacing for i in range(count)]
        holes = [{"x_mm": x, "z_mm": 0, "radius_mm": 6.3 if kind == "rack" else 5} for x in centers]
        add(
            "perforated-top",
            "plate",
            (0, sy * 0.41, 0),
            (sx, sy * 0.18, sz),
            "rack-top",
            holes=holes,
        )
    elif kind == "waste":
        box("floor", (0, -sy * 0.45, 0), (sx, sy * 0.10, sz), "waste")
        for sign in (-1, 1):
            box(
                f"side-x-{sign}",
                (sign * sx * 0.45, sy * 0.05, 0),
                (sx * 0.10, sy * 0.90, sz),
                "waste",
            )
            box(
                f"side-z-{sign}",
                (0, sy * 0.05, sign * sz * 0.45),
                (sx * 0.80, sy * 0.90, sz * 0.10),
                "waste",
            )
    elif kind == "controller":
        box("case", (0, -sy * 0.04, 0), (sx, sy * 0.92, sz), "controller")
        box("panel", (0, sy * 0.47, 0), (sx * 0.78, sy * 0.06, sz * 0.68), "panel")
        for i in range(3):
            box(
                f"vent-{i}",
                ((i - 1) * sx * 0.16, sy * 0.495, sz * 0.18),
                (sx * 0.09, sy * 0.01, sz * 0.10),
                "vent",
            )
    elif kind == "cooling":
        # Sized proportionally to either supported cooling envelope; no vendor fit is implied.
        box("floor", (0, -sy * 0.45, 0), (sx, sy * 0.10, sz), "cooling")
        for sign in (-1, 1):
            box(
                f"wall-x-{sign}",
                (sign * sx * 0.45, -sy * 0.0125, 0),
                (sx * 0.10, sy * 0.875, sz),
                "cooling",
            )
            box(
                f"wall-z-{sign}",
                (0, -sy * 0.0125, sign * sz * 0.45),
                (sx * 0.80, sy * 0.875, sz * 0.10),
                "cooling",
            )
        box("insert", (0, -sy * 0.30, 0), (sx * 0.66, sy * 0.12, sz * 0.64), "insert")
        box("lid", (0, sy * 0.46, 0), (sx, sy * 0.08, sz), "lid")
        for i in range(4):
            box(
                f"vent-{i}",
                ((i - 1.5) * sx * 0.14, sy * 0.505 - sy * 0.01, sz * 0.27),
                (sx * 0.08, sy * 0.01, sz * 0.08),
                "vent",
            )
    else:
        box("envelope", (0, 0, 0), (sx, sy, sz), "structure")
    return {"schema_version": "1", "primitives": p}


def add_geometry(project: dict) -> dict:
    """Return an independent snapshot with a single deterministic geometry model."""
    result = deepcopy(project)
    # Rebuild recognized inspection geometry from the bounded proposal. Never
    # treat arbitrary stored primitives or a matching prefix as authoritative.
    inspection = {}
    extension = result.get("inspection_extension")
    if isinstance(extension, dict):
        try:
            from app.inspection_geometry import compile_inspection

            compiled = compile_inspection(result, extension.get("proposal"))
            inspection = {part["id"]: part for part in compiled["components"]}
        except (ValueError, TypeError, KeyError):
            pass
    rack_geometry = None
    labware = result.get("labware_rack")
    if isinstance(labware, dict) and labware.get("kind") == "rim_supported_tube_rack":
        from app.labware_geometry import compile_labware_rack

        rack_geometry = compile_labware_rack(labware.get("spec"))
    reference_specs = component_geometry_specs(result)
    for comp in result["design"]["components"]:
        if comp.get("kind") == "upstream-cad":
            comp.pop("geometry", None)
            continue
        if comp["id"] in reference_specs:
            comp["reference_geometry"] = deepcopy(reference_specs[comp["id"]])
        else:
            comp.pop("reference_geometry", None)
        if comp["id"] == "sample-rack":
            comp["rack_slot_count"] = (
                labware["spec"]["count"] if rack_geometry else
                max(1, min(6, len(result.get("plan", {}).get("steps", []))))
            )
        canonical = inspection.get(comp["id"])
        if rack_geometry and comp["id"] == labware.get("target_component_id"):
            if comp["kind"] != "rack" or any(
                abs(float(a) - b) > 1e-7
                for a, b in zip(comp["size"], rack_geometry["size_mm"])
            ):
                raise ValueError("Labware rack component does not match its compiled dimensions.")
            comp["geometry"] = deepcopy(rack_geometry["geometry"])
        elif canonical and comp.get("kind") == canonical["kind"]:
            comp["geometry"] = deepcopy(canonical["geometry"])
            if "reference_geometry" in canonical:
                comp["reference_geometry"] = deepcopy(canonical["reference_geometry"])
        else:
            comp["geometry"] = geometry_for_component(comp)
    result["design"]["geometry_model"] = {
        "schema_version": "1",
        "source": "app.geometry.geometry_for_component",
        "assumptions": [
            "Concept details only; interfaces, materials, process and loads are unchecked.",
            "Consumables remain separate assumed visual and physics proxies; "
            "the conceptual sample insert pattern follows the number of targets.",
        ],
        "collision_scope": "Conservative component envelopes and consumable proxies; "
        "no detailed contacts.",
    }
    from app.design_sources import project_source_basis

    result["design_basis"] = project_source_basis(result)
    return result
