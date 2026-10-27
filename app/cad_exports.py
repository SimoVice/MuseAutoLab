"""Concept CAD envelopes built parametrically from the project snapshot.

Application coordinates use y as UP (mm). CAD export uses Z as UP with the
mapping app(x, y, z) -> CAD(x, z, y). The pipette is a schematic cylinder;
every other component is a schematic centred box matching its envelope.
The deck (component id ``base``) is a solid blank for concept review only.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
from importlib import metadata
from pprint import pformat
from tempfile import TemporaryDirectory

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
        out.append(
            {
                "id": str(comp["id"]),
                "kind": str(comp["kind"]),
                "label": str(comp["label"]),
                "position": pos,
                "size": size,
            }
        )
    ids = [c["id"] for c in out]
    if len(set(ids)) != len(ids):
        raise ValueError("Component ids must be unique.")
    return out


def _cad_center(comp: dict) -> tuple[float, float, float]:
    x, y, z = comp["position"]
    return (x, z, y)


def _cad_box_size(comp: dict) -> tuple[float, float, float]:
    sx, sy, sz = comp["size"]
    return (sx, sz, sy)


def _build_solid(comp: dict):
    """Build one centred solid in CAD (Z-up) coordinates."""
    from build123d import Align, Box, Cylinder, Location

    cx, cy, cz = _cad_center(comp)
    if comp["kind"] == PIPETTE_KIND:
        sx, sy, sz = comp["size"]
        radius = min(float(sx), float(sz)) / 2.0
        height = float(sy)
        solid = Cylinder(radius, height, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    else:
        lx, ly, lz = _cad_box_size(comp)
        solid = Box(lx, ly, lz, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    solid = solid.located(Location((cx, cy, cz)))
    solid.label = comp["id"]
    return solid


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


def _source_sha256() -> str:
    try:
        with open(__file__, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return "unknown"


def _deck_model_source(components: list[dict], project_id, revision) -> str:
    return (
        '"""Parametric concept envelopes. Requires build123d==0.13.0.\n'
        "Process and material: not selected. Deck is a solid blank, not fabrication-ready.\n"
        "Interfaces: labware, rails, pipette, cooling and mounts remain unchecked.\n"
        'Dimensions in mm; application y-up maps to CAD Z-up.\n"""\n'
        "from pathlib import Path\n"
        "from build123d import Align, Box, Compound, Cylinder, Location, Unit, export_step, "
        "export_stl\n"
        f"PROJECT_ID = {project_id!r}\nREVISION = {revision!r}\n"
        "# INTERFACE: none specified against a standard or vendor drawing.\n"
        "# DESIGN: component position/size arrays are editable millimetre parameters.\n"
        f"COMPONENTS_MM = {pformat(components, width=88, sort_dicts=False)}\n\n"
        "def interfaces():\n    return []\n\n"
        "def component_solid(comp):\n"
        "    x, y, z = comp['position']\n    sx, sy, sz = comp['size']\n"
        "    if comp['kind'] == 'pipette':\n"
        "        solid = Cylinder(min(sx, sz) / 2, sy, align=(Align.CENTER,) * 3)\n"
        "    else:\n        solid = Box(sx, sz, sy, align=(Align.CENTER,) * 3)\n"
        "    solid = solid.located(Location((x, z, y)))\n"
        "    solid.label = comp['id']\n    return solid\n\n"
        "def build():\n"
        "    return Compound(children=[component_solid(c) for c in COMPONENTS_MM], "
        "label='MuseAutoLab concept')\n\n"
        "def build_deck():\n"
        "    return component_solid(next(c for c in COMPONENTS_MM if c['id'] == 'base'))\n\n"
        "if __name__ == '__main__':\n"
        "    output = Path(__file__).resolve().parent\n    workstation = build()\n    deck = "
        "build_deck()\n"
        "    if not workstation.is_valid or not deck.is_valid:\n"
        "        raise ValueError('Invalid concept geometry')\n"
        "    export_step(workstation, output / 'workstation.step', unit=Unit.MM)\n"
        "    export_step(deck, output / 'deck.step', unit=Unit.MM)\n"
        "    export_stl(deck, output / 'deck.stl')\n"
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
        f"<title>{html.escape('Concept envelopes ' + str(project_id))}</title>",
        f"<desc>{html.escape('Top view app X right, app Z up; revision ' + str(revision))}</desc>",
    ]
    palette = ["#dbeafe", "#e0e7ff", "#ede9fe", "#fce7f3", "#fef3c7", "#dcfce7"]
    for i, comp in enumerate(components):
        x, _y, z = comp["position"]
        sx, _sy, sz = comp["size"]
        rx, ry = px(x - sx / 2.0), py(z + sz / 2.0)
        rw, rh = sx * scale, sz * scale
        fill = palette[i % len(palette)]
        stroke = "#1e3a8a" if comp["id"] == DECK_ID else "#334155"
        parts.append(
            f'<rect x="{rx:.2f}" y="{ry:.2f}" width="{rw:.2f}" height="{rh:.2f}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.5">'
            f"<title>{html.escape(comp['id'] + ' ' + comp['label'])}</title></rect>"
        )
        parts.append(
            f'<text x="{rx + 3:.2f}" y="{ry + 13:.2f}" font-size="10" '
            f'font-family="sans-serif" fill="#0f172a">'
            f"{html.escape(comp['id'])}</text>"
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
        solid = _build_solid(comp)
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
                "shape": "cylinder" if comp["kind"] == PIPETTE_KIND else "box",
                "valid": True,
                "volume_mm3": volume,
                "bbox_cad": bbox,
                "solids": len(solid.solids()),
                "provenance": "parametric from project.design.components envelope",
            }
        )

    deck = next((c for c in components if c["id"] == DECK_ID), None)
    if deck is None:
        raise ValueError("Deck component 'base' is missing.")
    # Export a separate root shape: a child attached to an assembly cannot be
    # exported alone by build123d's XDE writer without its parent hierarchy.
    deck_solid = _build_solid(deck)
    workstation = Compound(children=solids, label="MuseAutoLab concept")
    if not workstation.is_valid:
        raise ValueError("Workstation compound is invalid.")

    with TemporaryDirectory() as tmp:
        import os

        ws_path = os.path.join(tmp, "workstation.step")
        deck_step_path = os.path.join(tmp, "deck.step")
        deck_stl_path = os.path.join(tmp, "deck.stl")
        export_step(workstation, ws_path, unit=Unit.MM)
        export_step(deck_solid, deck_step_path, unit=Unit.MM)
        export_stl(deck_solid, deck_stl_path)
        with open(ws_path, "rb") as fh:
            workstation_step = fh.read()
        with open(deck_step_path, "rb") as fh:
            deck_step = fh.read()
        with open(deck_stl_path, "rb") as fh:
            deck_stl = fh.read()
    if not workstation_step or not deck_step or not deck_stl:
        raise ValueError("CAD export produced empty geometry.")

    report = {
        "project_id": project_id,
        "revision": revision,
        "units": UNITS,
        "coordinate_mapping": COORDINATE_MAPPING,
        "interfaces": [],
        "unchecked_interfaces": [
            "Frame fixation, rails and transmission: vendor drawings and loads not selected.",
            "Pipette actuation and tip handling: mounting dimensions not measured.",
            "Labware fixtures: tube and tip rack vendor dimensions and tolerances not measured.",
            "Cooling attachment, ventilation and insulation: not engineered.",
            "Camera and arm mounts, loads, reach and keep-out volumes: future design.",
        ],
        "fabrication_ready": False,
        "process": "not selected; concept only",
        "material": "not selected; concept only",
        "notes": [
            "Concept envelopes only; not fabrication-ready.",
            "Custom deck is a solid blank for concept review.",
            "Decorative scene tubes/vents are not engineering CAD.",
            "Pipette is a schematic cylinder; others are schematic boxes.",
        ],
        "components": entries,
        "deck_component_id": DECK_ID,
        "solid_count": len(solids),
        "source": {
            "generator": "app.cad_exports.build_cad_files",
            "source_sha256": _source_sha256(),
            "build123d_version": _build123d_version(),
            "input": "project.design.components (position/size in mm, y is UP)",
        },
    }
    report_bytes = json.dumps(report, indent=2).encode("utf-8")
    files: dict[str, bytes] = {
        "cad/workstation.step": workstation_step,
        "cad/deck.step": deck_step,
        "cad/deck.stl": deck_stl,
        "cad/geometry-report.json": report_bytes,
        "cad/deck-model.py": _deck_model_source(components, project_id, revision).encode("utf-8"),
        "cad/workstation.svg": _workstation_svg(components, project_id, revision),
    }
    return files
