"""Concept CAD geometry built parametrically from the project snapshot.

Application coordinates use y as UP (mm). CAD export uses Z as UP with the
mapping app(x, y, z) -> CAD(x, z, y). Components use shared primitives.
The deck (component id ``base``) is a solid blank for concept review only.
"""

from __future__ import annotations

import hashlib
import html
import inspect
import json
import math
from importlib import metadata
from pathlib import Path
from pprint import pformat
from tempfile import TemporaryDirectory

from app.geometry import GEOMETRY_SOURCE_SHA256, geometry_for_component
from app.upstream_cad import (
    ASSET_ID,
    STEP_PATH,
    STEP_SHA256,
    foundation_metadata,
    load_foundation_cad,
    original_step_bytes,
)

_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
COORDINATE_MAPPING = "app(x,y,z)->CAD(x,z,y); CAD Z is UP"
UNITS = "mm"
DECK_ID = "base"
PIPETTE_KIND = "pipette"


def _components(project: dict) -> list[dict]:
    try:
        components = project["design"]["components"]
    except (KeyError, TypeError) as exc:
        raise ValueError("project.design.components is missing.") from exc
    if not isinstance(components, list) or not components:
        raise ValueError("project.design.components must be a non-empty list.")
    out: list[dict] = []
    foundation = project["design"].get("foundation")
    if foundation is not None:
        if not isinstance(foundation, dict):
            raise ValueError("Invalid foundation metadata.")
        expected = foundation_metadata(foundation.get("bed_drop_mm"))
        if any(foundation.get(k) != v for k, v in expected.items()):
            raise ValueError("Foundation metadata does not match the pinned source.")
    for comp in components:
        if not isinstance(comp, dict):
            raise ValueError("Each component must be an object.")
        for key in ("id", "kind", "label", "position", "size"):
            if key not in comp:
                raise ValueError(f"Component is missing '{key}'.")
        pos = [float(v) for v in comp["position"]]
        size = [float(v) for v in comp["size"]]
        if len(pos) != 3 or len(size) != 3:
            raise ValueError("Component position/size must have 3 numbers.")
        if not all(math.isfinite(value) for value in pos + size):
            raise ValueError("Component coordinates must be finite.")
        if any(s <= 0 for s in size):
            raise ValueError(f"Component '{comp['id']}' has non-positive size.")
        if (
            comp["kind"] == "upstream-cad"
            or comp.get("foundation_asset_id") is not None
            or comp["id"] == "foundation-jubilee"
        ):
            if (
                foundation is None
                or comp["kind"] != "upstream-cad"
                or comp["id"] != "foundation-jubilee"
                or comp.get("foundation_asset_id") != ASSET_ID
                or pos != [0.0, expected["bbox_mm"][1] / 2, 0.0]
                or size != expected["bbox_mm"]
                or comp.get("geometry")
                or set(comp)
                - {"id", "kind", "label", "position", "size", "foundation_asset_id", "geometry"}
            ):
                raise ValueError("Invalid pinned foundation identity, position, size or geometry.")
            out.append(
                {
                    "id": comp["id"],
                    "kind": comp["kind"],
                    "label": comp["label"],
                    "position": pos,
                    "size": size,
                    "foundation_asset_id": ASSET_ID,
                    "bed_drop_mm": expected["bed_drop_mm"],
                }
            )
            continue
        geometry = comp.get("geometry") or geometry_for_component(comp)
        rack = project.get("labware_rack")
        is_parametric_rack = (
            isinstance(rack, dict)
            and rack.get("kind") == "rim_supported_tube_rack"
            and rack.get("target_component_id") == comp["id"]
        )
        if is_parametric_rack:
            from app.labware_geometry import compile_labware_rack

            compiled = compile_labware_rack(rack.get("spec"))
            if geometry != compiled["geometry"] or any(
                abs(a - b) > 1e-7 for a, b in zip(size, compiled["size_mm"])
            ):
                raise ValueError("Rack geometry does not match its compiled specification.")
        plate = project.get("labware_plate")
        is_microplate = (
            isinstance(plate, dict) and plate.get("kind") == "microplate_96"
            and plate.get("target_component_id") == comp["id"]
        )
        if is_microplate:
            from app.microplate_geometry import compile_microplate

            compiled = compile_microplate(plate.get("profile_id"))
            if is_parametric_rack or geometry != compiled["geometry"] or any(
                abs(a - b) > 1e-7 for a, b in zip(size, compiled["size_mm"])
            ):
                raise ValueError("Microplate geometry does not match its pinned profile.")
        tips = project.get("tip_rack")
        is_tip_rack = isinstance(tips, dict) and tips.get("target_component_id") == comp["id"]
        if is_tip_rack:
            from app.tiprack_geometry import compile_tiprack

            tip_compiled = compile_tiprack(tips)
            if (comp["kind"] != "tiprack" or geometry != tip_compiled["geometry"] or any(
                abs(a - b) > 1e-7 for a, b in zip(size, tip_compiled["size_mm"])
            )):
                raise ValueError("Tip rack geometry does not match its specification.")
        if geometry.get("schema_version") != "1" or not geometry.get("primitives"):
            raise ValueError(f"Invalid geometry for {comp['id']}.")
        for primitive in geometry["primitives"]:
            try:
                primitive_pos = primitive["position"]
                primitive_size = primitive["size"]
                yaw = primitive.get("rotation_y_deg", 0)
                if (
                    isinstance(yaw, bool)
                    or not isinstance(yaw, (int, float))
                    or not math.isfinite(yaw)
                ):
                    raise ValueError
                values = [*primitive_pos, *primitive_size]
                if (
                    len(primitive_pos) != 3
                    or len(primitive_size) != 3
                    or any(
                        isinstance(v, bool)
                        or not isinstance(v, (int, float))
                        or not math.isfinite(v)
                        for v in values
                    )
                    or any(v <= 0 for v in primitive_size)
                ):
                    raise ValueError
                c, s = abs(math.cos(math.radians(yaw))), abs(math.sin(math.radians(yaw)))
                sx, sy, sz = primitive_size
                extents = (c * sx + s * sz, sy, s * sx + c * sz)
                if any(
                    abs(p) + extent / 2 > bound / 2 + 1e-7
                    for p, extent, bound in zip(primitive_pos, extents, size)
                ):
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise ValueError(f"Invalid or out-of-bounds primitive for {comp['id']}.") from None
        out.append(
            {
                "id": str(comp["id"]),
                "kind": str(comp["kind"]),
                "label": str(comp["label"]),
                "position": pos,
                "size": size,
                "geometry": geometry,
                **({"fabrication_shape": "rim_supported_tube_rack"} if is_parametric_rack else {}),
                **({"fabrication_shape": "microplate_holder"} if is_microplate else {}),
                **({"fabrication_shape": "rim_supported_tip_rack"}
                   if is_tip_rack and tips.get("kind") == "rim_supported_tip_rack" else {}),
                **({"plate_interfaces": compiled["checks"]["interfaces"]} if is_microplate else {}),
                **(
                    {"reference_geometry": comp["reference_geometry"]}
                    if "reference_geometry" in comp
                    else {}
                ),
                **(
                    {"rack_slot_count": comp["rack_slot_count"]}
                    if "rack_slot_count" in comp
                    else {}
                ),
            }
        )
    ids = [c["id"] for c in out]
    if len(set(ids)) != len(ids):
        raise ValueError("Component ids must be unique.")
    if foundation is not None and ids.count("foundation-jubilee") != 1:
        raise ValueError("Pinned foundation component is missing.")
    return out


def _cad_center(comp: dict) -> tuple[float, float, float]:
    x, y, z = comp["position"]
    return (x, z, y)


def _cad_box_size(comp: dict) -> tuple[float, float, float]:
    sx, sy, sz = comp["size"]
    return (sx, sz, sy)


def _primitive_solid(comp, primitive):
    """Create one primitive in CAD coordinates from the serialized geometry."""
    from build123d import Align, Box, Cone, Cylinder, Pos, Rot

    x, y, z = primitive["position"]
    sx, sy, sz = primitive["size"]
    shape = primitive["kind"]
    align = (Align.CENTER,) * 3
    if shape in ("box", "plate"):
        solid = Box(sx, sz, sy, align=align)
        if shape == "plate":
            for hole in primitive.get("holes", []):
                cutter = Pos(hole["x_mm"], hole["z_mm"], 0) * Cylinder(
                    hole["radius_mm"], sy + 2, align=align
                )
                solid = solid - cutter
    elif shape in ("cylinder", "frustum", "tube"):
        axis = primitive.get("axis", "y")
        dims = {"x": (sx, sy), "y": (sy, sx), "z": (sz, sx)}
        height, diameter = dims[axis]
        if shape == "frustum":
            solid = Cone(
                primitive["radius_bottom_mm"], primitive["radius_top_mm"], height, align=align
            )
        else:
            solid = Cylinder(diameter / 2, height, align=align)
            if shape == "tube":
                solid = solid - Cylinder(primitive["inner_radius_mm"], height + 2, align=align)
        if axis == "x":
            solid = Rot(0, 90, 0) * solid
        elif axis == "z":
            solid = Rot(-90, 0, 0) * solid
    else:
        raise ValueError(f"Unsupported geometry primitive: {shape}")
    # The app-to-CAD coordinate mapping reflects orientation about the up axis.
    solid = Rot(0, 0, -primitive.get("rotation_y_deg", 0)) * solid
    cx, cy, cz = comp["position"]
    solid = Pos(cx + x, cz + z, cy + y) * solid
    solid.label = primitive["id"]
    return solid


def _build_plate_part(comp, prefix):
    """Fuse only the holder or only the schematic reference plate."""
    parts = [_primitive_solid(comp, p) for p in comp["geometry"]["primitives"]
             if p["id"].startswith(prefix)]
    if not parts:
        raise ValueError("Microplate part is missing its primitives.")
    solid = parts[0]
    for part in parts[1:]:
        solid = solid.fuse(part)
    if not solid.is_valid or len(solid.solids()) != 1:
        raise ValueError("Microplate part must form one valid solid.")
    solid.label = "plate-holder" if prefix == "holder-" else "plate-reference-schematic"
    return solid


def _build_solid(comp):
    """Group the exact shared primitives, retaining component and primitive IDs."""
    from build123d import Compound

    if comp.get("fabrication_shape") == "microplate_holder":
        return Compound(children=[_build_plate_part(comp, "holder-"),
                                  _build_plate_part(comp, "reference-")], label=comp["id"])
    parts = [_primitive_solid(comp, p) for p in comp["geometry"]["primitives"]]
    if comp.get("fabrication_shape") in ("rim_supported_tube_rack", "rim_supported_tip_rack"):
        solid = parts[0]
        for part in parts[1:]:
            solid = solid.fuse(part)
        if not solid.is_valid or len(solid.solids()) != 1:
            raise ValueError("Rack must form one valid fused solid.")
        solid.label = comp["id"]
        return solid
    return Compound(children=parts, label=comp["id"])


def _build_rack_fit_coupon(comp):
    """Build a flat one-hole coupon using the rack's canonical top and bore."""
    plate = next(p for p in comp["geometry"]["primitives"] if p["id"] == "perforated-top")
    radius = plate["holes"][0]["radius_mm"]
    thickness = plate["size"][1]
    side = 2 * radius + 12.0  # 6 mm nominal material from bore to each edge.
    primitive = {
        "id": "fit-coupon", "kind": "plate", "position": [0, 0, 0],
        "size": [side, thickness, side], "holes": [{"x_mm": 0, "z_mm": 0, "radius_mm": radius}],
    }
    coupon = _primitive_solid({"position": [0, thickness / 2, 0]}, primitive)
    if not coupon.is_valid or len(coupon.solids()) != 1:
        raise ValueError("Rack fit coupon must form one valid solid.")
    coupon.label = ("tip-rack-fit-coupon" if comp.get("id") == "tip-rack"
                    else "tube-rack-fit-coupon")
    return coupon


# Freeze the imported builder for self-contained exports throughout this process.
_PRIMITIVE_BUILDER_SOURCE = inspect.getsource(_primitive_solid)
_PLATE_BUILDER_SOURCE = inspect.getsource(_build_plate_part)
_COMPONENT_BUILDER_SOURCE = inspect.getsource(_build_solid)
_COUPON_BUILDER_SOURCE = inspect.getsource(_build_rack_fit_coupon)


def _bbox_of(solid) -> dict:
    bb = solid.bounding_box()
    return {
        "min": [float(bb.min.X), float(bb.min.Y), float(bb.min.Z)],
        "max": [float(bb.max.X), float(bb.max.Y), float(bb.max.Z)],
        "size": [float(bb.size.X), float(bb.size.Y), float(bb.size.Z)],
    }


def _build123d_version() -> str:
    try:
        return metadata.version("build123d")
    except Exception:
        return "unknown"


def _deck_model_source(components: list[dict], project_id, revision) -> str:
    plate_interfaces = next(
        (c.get("plate_interfaces", []) for c in components
         if c.get("fabrication_shape") == "microplate_holder"), []
    )
    return (
        '"""Shared concept primitives, mm. Requires build123d==0.13.0.\n'
        "Process, material and all interfaces unchecked; not fabrication-ready.\n"
        'Application Y-up maps to CAD Z-up; deck is a solid blank.\n"""\n'
        "from pathlib import Path\n"
        "from build123d import Compound, Unit, export_step, export_stl\n"
        f"PROJECT_ID = {project_id!r}\nREVISION = {revision!r}\n"
        f"COMPONENTS_MM = {pformat(components, width=88, sort_dicts=False)}\n\n"
        + _PRIMITIVE_BUILDER_SOURCE
        + "\n\n"
        + _PLATE_BUILDER_SOURCE
        + "\n\n"
        + _COMPONENT_BUILDER_SOURCE
        + "\n\n"
        + _COUPON_BUILDER_SOURCE
        + "\n\n"
        + "def _standalone_solid(c):\n"
        + "    if c['kind'] != 'upstream-cad': return _build_solid(c)\n"
        + "    import gzip, hashlib, tempfile\n"
        + "    from build123d import import_step, Pos, Rot\n"
        + "    path = Path(__file__).resolve().parent / 'source/jubilee-original.step.gz'\n"
        + "    raw = gzip.decompress(path.read_bytes())\n"
        + f"    if hashlib.sha256(raw).hexdigest() != {STEP_SHA256!r}:\n"
        + "        raise ValueError('Pinned source hash mismatch')\n"
        + "    with tempfile.TemporaryDirectory() as tmp:\n"
        + "        source = Path(tmp) / 'original.step'; source.write_bytes(raw)\n"
        + "        original = import_step(source)\n"
        + "    beds = [p for p in original.children if p.label == 'build_plate_assembly']\n"
        + "    if len(beds) != 1: raise ValueError('Expected one bed assembly')\n"
        + "    transform = Pos(-274.855945675, 425.743280356, -272.216535584) * Rot(90, 0, 0)\n"
        + "    fixed = Compound([p for p in original.children "
        + "if p.label != 'build_plate_assembly'])\n"
        + "    bed = Pos(0, 0, -c['bed_drop_mm']) * transform * beds[0]\n"
        + "    bed.label = 'build_plate_assembly'\n"
        + "    return Compound(children=[transform * fixed, bed], label=c['id'])\n\n"
        + "def interfaces():\n"
        + f"    return {pformat(plate_interfaces, width=88)}\n\n"
        + "def build():\n    return Compound(children=[_standalone_solid(c) "
        + "for c in COMPONENTS_MM], "
        + 'label="MuseAutoLab concept")\n\n'
        + "def build_deck():\n    return _build_solid(next(c for c in COMPONENTS_MM "
        + 'if c["id"] == "base"))\n\n'
        + 'if __name__ == "__main__":\n'
        + "    output = Path(__file__).resolve().parent\n"
        + "    workstation, deck = build(), build_deck()\n"
        + "    if not deck.is_valid:\n"
        + '        raise ValueError("Invalid deck geometry")\n'
        + '    export_step(workstation, output / "workstation.step", unit=Unit.MM)\n'
        + '    export_step(deck, output / "deck.step", unit=Unit.MM)\n'
        + '    export_stl(deck, output / "deck.stl")\n'
        + '    rack = next((c for c in COMPONENTS_MM if c.get("fabrication_shape") '
        + '== "rim_supported_tube_rack"), None)\n'
        + '    if rack:\n'
        + '        rack_solid = _build_solid(rack)\n'
        + '        export_step(rack_solid, output / "tube-rack.step", unit=Unit.MM)\n'
        + '        export_stl(rack_solid, output / "tube-rack.stl")\n'
        + '        coupon = _build_rack_fit_coupon(rack)\n'
        + '        export_step(coupon, output / "tube-rack-fit-coupon.step", unit=Unit.MM)\n'
        + '        export_stl(coupon, output / "tube-rack-fit-coupon.stl")\n'
        + '    tip_rack = next((c for c in COMPONENTS_MM if c.get("fabrication_shape") '
        + '== "rim_supported_tip_rack"), None)\n'
        + '    if tip_rack:\n'
        + '        tip_solid = _build_solid(tip_rack)\n'
        + '        export_step(tip_solid, output / "tip-rack.step", unit=Unit.MM)\n'
        + '        export_stl(tip_solid, output / "tip-rack.stl")\n'
        + '        tip_coupon = _build_rack_fit_coupon(tip_rack)\n'
        + '        export_step(tip_coupon, output / "tip-rack-fit-coupon.step", unit=Unit.MM)\n'
        + '        export_stl(tip_coupon, output / "tip-rack-fit-coupon.stl")\n'
        + '    plate = next((c for c in COMPONENTS_MM if c.get("fabrication_shape") '
        + '== "microplate_holder"), None)\n'
        + '    if plate:\n'
        + '        holder = _build_plate_part(plate, "holder-")\n'
        + '        reference = _build_plate_part(plate, "reference-")\n'
        + '        export_step(holder, output / "plate-holder.step", unit=Unit.MM)\n'
        + '        export_stl(holder, output / "plate-holder.stl")\n'
        + '        export_step(reference, output / "plate-reference.step", unit=Unit.MM)\n'
    )


def _workstation_svg(components: list[dict], project_id, revision) -> bytes:
    margin = 30.0
    xs: list[float] = []
    ys: list[float] = []
    for comp in components:
        x, _y, z = comp["position"]
        sx, _sy, sz = comp["size"]
        xs += [x - sx / 2.0, x + sx / 2.0]
        ys += [z - sz / 2.0, z + sz / 2.0]
    lo_x, hi_x = min(xs), max(xs)
    lo_y, hi_y = min(ys), max(ys)
    span_x = max(hi_x - lo_x, 1.0)
    span_y = max(hi_y - lo_y, 1.0)
    scale = min(560.0 / span_x, 360.0 / span_y)
    width = span_x * scale + 2 * margin
    height = span_y * scale + 2 * margin

    def px(x: float) -> float:
        return margin + (x - lo_x) * scale

    def py(z: float) -> float:
        return margin + (hi_y - z) * scale

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width:.1f}" height="{height:.1f}" role="img">',
        f"<title>{html.escape('Concept geometry ' + str(project_id))}</title>",
        f"<desc>{html.escape('Top view app X right, app Z up; revision ' + str(revision))}</desc>",
    ]
    palette = {
        "deck": "#e2e8f0",
        "rack": "#8db9c9",
        "rack-top": "#c9e2e8",
        "frame": "#8a9aa6",
        "rail": "#d4dce2",
        "cooling": "#aecddd",
        "lid": "#d6e9ee",
        "vent": "#57717e",
        "pipette": "#e1e6e9",
    }
    for comp in components:
        x, _y, z = comp["position"]
        for primitive in comp.get("geometry", {}).get("primitives", []):
            dx, _dy, dz = primitive["position"]
            sx, _sy, sz = primitive["size"]
            rx, ry = px(x + dx - sx / 2), py(z + dz + sz / 2)
            fill = palette.get(primitive["appearance"], "#b8c4ca")
            yaw = primitive.get("rotation_y_deg", 0)
            transform = f' transform="rotate({yaw:.6f} {px(x + dx):.2f} {py(z + dz):.2f})"'
            parts.append(
                f'<rect x="{rx:.2f}" y="{ry:.2f}" width="{sx * scale:.2f}" '
                f'height="{sz * scale:.2f}" '
                f'fill="{fill}" stroke="#526772" stroke-width="0.5"{transform}>'
                f"<title>{html.escape(comp['id'] + '/' + primitive['id'])}</title></rect>"
            )
            if primitive["kind"] == "plate":
                for hole in primitive.get("holes", []):
                    parts.append(
                        f'<circle cx="{px(x + dx + hole["x_mm"]):.2f}" '
                        f'cy="{py(z + dz + hole["z_mm"]):.2f}" '
                        f'r="{hole["radius_mm"] * scale:.2f}" fill="#f8fafc" '
                        f'stroke="#526772"{transform}/>'
                    )
        parts.append(
            f'<text x="{px(x):.2f}" y="{py(z):.2f}" font-size="9" '
            f'font-family="sans-serif" fill="#0f172a">{html.escape(comp["id"])}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts).encode("utf-8")


def build_cad_files(project: dict) -> dict[str, bytes]:
    """Build concept CAD files from the live project snapshot."""
    from build123d import Compound, Unit, export_step, export_stl

    if not isinstance(project, dict) or "design" not in project:
        raise ValueError("project.design is missing.")
    project_id = project.get("id")
    revision = project.get("revision")
    components = _components(project)

    solids: list = []
    entries: list[dict] = []
    for comp in components:
        imported = comp["kind"] == "upstream-cad"
        solid = load_foundation_cad(comp["bed_drop_mm"]) if imported else _build_solid(comp)
        solid.label = comp["id"]
        if imported:
            solid.children[1].label = "build_plate_assembly"
        if solid is None or not solid.is_valid:
            raise ValueError(f"CAD solid for '{comp['id']}' is invalid.")
        try:
            volume = float(solid.volume)
        except Exception as exc:
            raise ValueError(f"Could not measure '{comp['id']}': {exc}.") from exc
        if not volume > 0:
            raise ValueError(f"CAD solid for '{comp['id']}' has no volume.")
        bbox = _bbox_of(solid)
        solids.append(solid)
        entries.append(
            {
                "id": comp["id"],
                "kind": comp["kind"],
                "label": comp["label"],
                "app_position": list(comp["position"]),
                "app_size": list(comp["size"]),
                "cad_center": list(_cad_center(comp)),
                "cad_size": list(_cad_box_size(comp)),
                "shape": "pinned upstream CAD" if imported else "shared primitives",
                **(
                    {
                        "foundation_asset_id": ASSET_ID,
                        "bed_drop_mm": comp["bed_drop_mm"],
                        "source_sha256": STEP_SHA256,
                        "source_revision": "c877bd2e889560c83da2a68479641a4f7f0d9b83",
                        "source_license": "CC-BY-4.0",
                        "source_transform": "(X-274.855945675, 425.743280356-Z, Y-272.216535584)",
                        "pose": "Only build_plate_assembly translated down by bed_drop_mm.",
                    }
                    if imported
                    else {"primitive_manifest": comp["geometry"]["primitives"]}
                ),
                **(
                    {"rack_slot_count": comp["rack_slot_count"]}
                    if "rack_slot_count" in comp
                    else {}
                ),
                "valid": True,
                "volume_mm3": volume,
                "volume_scope": (
                    "Sum of imported solid volumes; overlaps may be counted more than once."
                    if imported
                    else (
                        "One fused rack solid."
                        if comp.get("fabrication_shape") in (
                            "rim_supported_tube_rack", "rim_supported_tip_rack"
                        )
                        else "Separate fused holder and schematic reference plate."
                        if comp.get("fabrication_shape") == "microplate_holder"
                        else "Sum of primitive solid volumes; overlaps may be counted "
                        "more than once."
                    )
                ),
                "bbox_cad": bbox,
                "solids": len(solid.solids()),
                "provenance": "Pinned upstream STEP"
                if imported
                else "project.design.components geometry primitives",
            }
        )

    deck = next((c for c in components if c["id"] == DECK_ID), None)
    if deck is None:
        raise ValueError("Deck component 'base' is missing.")
    # Export a separate root shape: a child attached to an assembly cannot be
    # exported alone by build123d's XDE writer without its parent hierarchy.
    deck_solid = _build_solid(deck)
    workstation = Compound(children=solids, label="MuseAutoLab concept")
    if project["design"].get("foundation") is None and not workstation.is_valid:
        raise ValueError("Workstation compound is invalid.")

    with TemporaryDirectory() as tmp:
        import os

        ws_path = os.path.join(tmp, "workstation.step")
        deck_step_path = os.path.join(tmp, "deck.step")
        deck_stl_path = os.path.join(tmp, "deck.stl")
        export_step(workstation, ws_path, unit=Unit.MM)
        export_step(deck_solid, deck_step_path, unit=Unit.MM)
        export_stl(deck_solid, deck_stl_path)
        rack_comp = next(
            (c for c in components if c.get("fabrication_shape") == "rim_supported_tube_rack"),
            None,
        )
        rack_files = {}
        if rack_comp:
            rack_solid = _build_solid(rack_comp)
            rack_step_path = os.path.join(tmp, "tube-rack.step")
            rack_stl_path = os.path.join(tmp, "tube-rack.stl")
            export_step(rack_solid, rack_step_path, unit=Unit.MM)
            export_stl(rack_solid, rack_stl_path)
            coupon = _build_rack_fit_coupon(rack_comp)
            coupon_step_path = os.path.join(tmp, "tube-rack-fit-coupon.step")
            coupon_stl_path = os.path.join(tmp, "tube-rack-fit-coupon.stl")
            export_step(coupon, coupon_step_path, unit=Unit.MM)
            export_stl(coupon, coupon_stl_path)
            with open(coupon_step_path, "rb") as fh:
                rack_files["cad/tube-rack-fit-coupon.step"] = fh.read()
            with open(coupon_stl_path, "rb") as fh:
                rack_files["cad/tube-rack-fit-coupon.stl"] = fh.read()
            with open(rack_step_path, "rb") as fh:
                rack_files["cad/tube-rack.step"] = fh.read()
            with open(rack_stl_path, "rb") as fh:
                rack_files["cad/tube-rack.stl"] = fh.read()
        tip_comp = next(
            (c for c in components if c.get("fabrication_shape") == "rim_supported_tip_rack"),
            None,
        )
        if tip_comp:
            for filename, solid, exporter in (
                ("tip-rack.step", _build_solid(tip_comp),
                 lambda s, p: export_step(s, p, unit=Unit.MM)),
                ("tip-rack.stl", _build_solid(tip_comp), export_stl),
                ("tip-rack-fit-coupon.step", _build_rack_fit_coupon(tip_comp),
                 lambda s, p: export_step(s, p, unit=Unit.MM)),
                ("tip-rack-fit-coupon.stl", _build_rack_fit_coupon(tip_comp), export_stl),
            ):
                path = os.path.join(tmp, filename)
                exporter(solid, path)
                with open(path, "rb") as fh:
                    rack_files["cad/" + filename] = fh.read()
        plate_comp = next(
            (c for c in components if c.get("fabrication_shape") == "microplate_holder"), None
        )
        if plate_comp:
            holder = _build_plate_part(plate_comp, "holder-")
            reference = _build_plate_part(plate_comp, "reference-")
            for filename, solid, exporter in (
                ("plate-holder.step", holder, lambda s, p: export_step(s, p, unit=Unit.MM)),
                ("plate-holder.stl", holder, export_stl),
                ("plate-reference.step", reference, lambda s, p: export_step(s, p, unit=Unit.MM)),
            ):
                path = os.path.join(tmp, filename)
                exporter(solid, path)
                with open(path, "rb") as fh:
                    rack_files["cad/" + filename] = fh.read()
        with open(ws_path, "rb") as fh:
            workstation_step = fh.read()
        with open(deck_step_path, "rb") as fh:
            deck_step = fh.read()
        with open(deck_stl_path, "rb") as fh:
            deck_stl = fh.read()
    if not workstation_step or not deck_step or not deck_stl:
        raise ValueError("CAD export produced empty geometry.")

    labware_source = None
    if project.get("labware_rack"):
        from app.labware_geometry import LABWARE_GEOMETRY_SOURCE_SHA256

        labware_source = LABWARE_GEOMETRY_SOURCE_SHA256
    microplate_source = None
    if project.get("labware_plate"):
        from app.microplate_geometry import MICROPLATE_GEOMETRY_SOURCE_SHA256, compile_microplate

        microplate_source = MICROPLATE_GEOMETRY_SOURCE_SHA256
        plate_details = compile_microplate(project["labware_plate"]["profile_id"])
    tip_source = None
    if project.get("tip_rack"):
        from app.tiprack_geometry import TIPRACK_GEOMETRY_SOURCE_SHA256, compile_tiprack

        tip_source = TIPRACK_GEOMETRY_SOURCE_SHA256
        tip_details = compile_tiprack(project["tip_rack"])
    report = {
        "project_id": project_id,
        "revision": revision,
        "units": UNITS,
        "coordinate_mapping": COORDINATE_MAPPING,
        "interfaces": plate_details["checks"]["interfaces"] if microplate_source else [],
        "unchecked_interfaces": [
            "Frame fixation, rails and transmission: vendor drawings and loads not selected.",
            "Pipette actuation and tip handling: mounting dimensions not measured.",
            "Labware fixtures: tube and tip rack vendor dimensions and tolerances not measured.",
            "Cooling attachment, ventilation and insulation: not engineered.",
            "Camera and arm attachment, loads, motion clearances and cabling: not engineered.",
        ],
        "fabrication_ready": False,
        "assembly_validity_scope": (
            "Component shapes checked individually; STEP assembly not separately checked."
            if project["design"].get("foundation")
            else "Compound and component shapes checked."
        ),
        "layout_origin": (
            "Meta-proposed, geometrically screened layout"
            if project.get("engineering_design")
            else "Built-in concept layout"
        ),
        "engineering_design": project.get("engineering_design"),
        "design_basis": project.get("design_basis"),
        **({"tip_rack_reference": tip_details.get("profile"),
            "tip_rack_checks": tip_details["checks"]} if tip_source else {}),
        "process": "not selected; concept only",
        "material": "not selected; concept only",
        "notes": [
            "Custom concept details and dimensions are illustrative; not fabrication-ready.",
            "The top-view SVG omits imported source geometry; "
            "use the STEP for the complete assembly."
            if project["design"].get("foundation")
            else "Top view depicts concept primitives.",
            "Custom deck is a solid blank for concept review.",
            "Consumables remain separate visual and physics proxies; "
            "sample insert pattern follows the target count.",
            "Details and openings do not establish fit, process, or performance.",
            "Reported volumes sum separate primitive solids and may count overlaps; "
            "they are not material volume or mass.",
            *(["Plate reference is schematic, not manufacturer CAD or a fabrication part; "
               "holder base profile, retention, tool access, mounting, material and print fit "
               "are unchecked."]
              if microplate_source else []),
        ],
        "components": entries,
        "deck_component_id": DECK_ID,
        "component_count": len(solids),
        "solid_count": sum(len(s.solids()) for s in solids),
        "source": {
            "generator": "app.cad_exports.build_cad_files",
            "source_sha256": _SOURCE_SHA256,
            "geometry_source_sha256": GEOMETRY_SOURCE_SHA256,
            **({"labware_geometry_source_sha256": labware_source} if labware_source else {}),
            **({"microplate_geometry_source_sha256": microplate_source}
               if microplate_source else {}),
            **({"tiprack_geometry_source_sha256": tip_source} if tip_source else {}),
            "build123d_version": _build123d_version(),
            "input": (
                "Pinned source STEP and project.design.components primitives (mm, y is UP)"
                if project["design"].get("foundation") is not None
                else "project.design.components geometry primitives (mm, y is UP)"
            ),
        },
    }
    report_bytes = json.dumps(report, indent=2).encode("utf-8")
    files: dict[str, bytes] = {
        **rack_files,
        "cad/workstation.step": workstation_step,
        "cad/deck.step": deck_step,
        "cad/deck.stl": deck_stl,
        "cad/geometry-report.json": report_bytes,
        "cad/deck-model.py": _deck_model_source(components, project_id, revision).encode("utf-8"),
        "cad/workstation.svg": _workstation_svg(components, project_id, revision),
    }
    if project["design"].get("foundation") is not None:
        original_step_bytes()  # Verify the raw upstream source before packaging it.
        files["cad/source/jubilee-original.step.gz"] = STEP_PATH.read_bytes()
        for suffix in ("LICENSE.txt", "provenance.json"):
            files[f"cad/source/jubilee-c877bd2.{suffix}"] = STEP_PATH.with_name(
                f"jubilee-c877bd2.{suffix}"
            ).read_bytes()
    if microplate_source:
        from app.microplate_geometry import DATA_DIR, PROFILE_ID

        for name in (PROFILE_ID + ".json", "provenance.json", "LICENSE.txt"):
            files["cad/source/microplate-" + name] = (DATA_DIR / name).read_bytes()
    if tip_source and project["tip_rack"].get("kind") == "commercial_reference":
        tip_data_dir = Path(__file__).parent / "data" / "tipracks"
        profile_id = project["tip_rack"]["profile_id"]
        for name in (profile_id + ".json", "provenance.json", "LICENSE.txt"):
            files["cad/source/tiprack-" + name] = (tip_data_dir / name).read_bytes()
    return files
