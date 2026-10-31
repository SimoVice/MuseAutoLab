"""Tip-rack references and measured-input bridge rack, millimetres, Y up.

Commercial references use pinned software definitions, not vendor CAD. The
printable bridge is a concept for FDM with an unselected material: print inverted
with the top on the bed. All tip dimensions are user-declared maxima/minima;
their tolerances, fit, retention, sterilisation and deck attachment are unchecked.
The printed item is a holder for purchased tips, never the disposable tips.
"""

from __future__ import annotations

import math
from hashlib import sha256
from pathlib import Path

TIPRACK_GEOMETRY_SOURCE_SHA256 = sha256(Path(__file__).read_bytes()).hexdigest()
RADIAL_CLEARANCE_MM = 0.4
BORE_TOLERANCE_MM = 0.3
MIN_RIM_LAND_MM = 0.4
TOP_THICKNESS_MM = 4.0
END_WALL_MM = 3.0
MIN_WEB_MM = 3.0
TIP_CLEARANCE_MM = 3.0
RIM_GAP_MM = 0.8
REFERENCE_RECESS_MM = 3.0  # Illustrative top marking; software well depth is not molded geometry.


def _number(spec, key, lower, upper, default=None):
    value = spec.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{key} must be a finite number.")
    if not lower <= value <= upper:
        raise ValueError(f"{key} must be between {lower} and {upper} mm.")
    return float(value)


def _printed(spec):
    if not isinstance(spec, dict):
        raise ValueError("Tip rack specification must be an object.")
    body = _number(spec, "body_diameter_max_mm", 1, 100)
    rim_min = _number(spec, "rim_diameter_min_mm", 1, 120)
    rim_max = _number(spec, "rim_diameter_max_mm", rim_min, 150)
    below = _number(spec, "below_rim_height_mm", 1.1, 250)
    clearance = _number(spec, "radial_clearance_mm", 0.4, 5, RADIAL_CLEARANCE_MM)
    count, columns = spec.get("count"), spec.get("columns")
    if type(count) is not int or not 1 <= count <= 96:
        raise ValueError("count must be an integer between 1 and 96.")
    if type(columns) is not int or not 1 <= columns <= min(count, 12):
        raise ValueError("columns must be an integer between 1 and min(count, 12).")
    bore = body + 2 * clearance + BORE_TOLERANCE_MM
    bore_max = bore + BORE_TOLERANCE_MM
    land = (rim_min - bore_max) / 2
    if land + 1e-9 < MIN_RIM_LAND_MM:
        raise ValueError("Tip rim is too narrow for the bore and minimum bearing land.")
    min_pitch = max(rim_max + RIM_GAP_MM, bore_max + MIN_WEB_MM)
    pitch = _number(spec, "pitch_mm", min_pitch, 200, min_pitch)
    rows = (count + columns - 1) // columns
    width = (columns - 1) * pitch + bore + 2 * (END_WALL_MM + MIN_WEB_MM)
    depth = (rows - 1) * pitch + bore + 2 * MIN_WEB_MM
    height = below + TIP_CLEARANCE_MM
    if height <= TOP_THICKNESS_MM:
        raise ValueError("Tip height leaves no room for rack legs.")
    for key, dimension in (("max_width_mm", width), ("max_depth_mm", depth),
                           ("max_height_mm", height)):
        if spec.get(key) is not None and dimension > _number(spec, key, 1, 1000) + 1e-9:
            raise ValueError(f"Tip rack exceeds {key}.")
    holes = [
        {"x_mm": (i % columns - (columns - 1) / 2) * pitch,
         "z_mm": (i // columns - (rows - 1) / 2) * pitch, "radius_mm": bore / 2}
        for i in range(count)
    ]
    primitives = [{"id": "perforated-top", "kind": "plate",
                   "position": [0, height / 2 - TOP_THICKNESS_MM / 2, 0],
                   "size": [width, TOP_THICKNESS_MM, depth], "appearance": "rack-top",
                   "holes": holes}]
    for sign, name in ((-1, "left"), (1, "right")):
        primitives.append({"id": "leg-" + name, "kind": "box",
                           "position": [sign * (width - END_WALL_MM) / 2,
                                        -TOP_THICKNESS_MM / 2, 0],
                           "size": [END_WALL_MM, height - TOP_THICKNESS_MM, depth],
                           "appearance": "rack"})
    return {"size_mm": [width, height, depth],
            "geometry": {"schema_version": "1", "primitives": primitives},
            "derived": {"rows": rows, "columns": columns, "count": count,
                        "pitch_mm": pitch, "bore_diameter_mm": bore,
                        "bore_max_assumed_mm": bore_max, "rim_land_min_assumed_mm": land,
                        "tip_clearance_mm": TIP_CLEARANCE_MM,
                        "top_thickness_mm": TOP_THICKNESS_MM, "end_wall_mm": END_WALL_MM},
            "checks": {"body_radial_clearance_min_assumed_mm":
                       (bore - BORE_TOLERANCE_MM - body) / 2,
                       "rim_land_min_assumed_mm": land, "rim_gap_mm": pitch - rim_max,
                       "hole_web_min_assumed_mm": pitch - bore_max,
                       "physical_fit_verified": False,
                       "interfaces": [],
                       "scope": "Numerical concept; tip, printer, material, attachment, "
                                "sterilisation and pipette compatibility are unchecked."}}


def _commercial(profile):
    """Make a schematic from software coordinates; do not claim vendor CAD."""
    length, height, width = profile["dimensions_mm"]
    depth = REFERENCE_RECESS_MM
    if not 0 < depth < height:
        raise ValueError("Reference envelope is too short for its schematic top.")
    holes = [{"x_mm": well["x_mm"], "z_mm": well["z_mm"],
              "radius_mm": well["diameter_mm"] / 2} for well in profile["wells"]]
    if not holes:
        raise ValueError("Reference rack requires its software well pattern.")
    primitives = [
        {"id": "reference-bottom", "kind": "box", "position": [0, -depth / 2, 0],
         "size": [length, height - depth, width], "appearance": "rack"},
        {"id": "reference-wells", "kind": "plate", "position": [0, (height - depth) / 2, 0],
         "size": [length, depth, width], "appearance": "rack-top", "holes": holes},
    ]
    return {"size_mm": [length, height, width],
            "geometry": {"schema_version": "1", "primitives": primitives},
            "profile": profile,
            "derived": {"well_count": len(holes), "schematic_recess_mm": depth,
                        "software_well_depth_mm": profile["well_depth_mm"]},
            "checks": {"physical_fit_verified": False, "interfaces": [],
                       "scope": "Software-derived envelope and well pattern with a schematic "
                                "3 mm recess, not vendor CAD or molded internal geometry; "
                                "tip and pipette compatibility and attachment are unverified."}}


def compile_tiprack(record: dict) -> dict:
    if not isinstance(record, dict) or record.get("target_component_id") != "tip-rack":
        raise ValueError("Tip rack must target tip-rack.")
    if record.get("kind") == "rim_supported_tip_rack":
        return _printed(record.get("spec"))
    if record.get("kind") == "commercial_reference":
        from app.tip_racks import tip_profile

        profile = tip_profile(record.get("profile_id"))
        if (record.get("profile_binding") is not None
                and record["profile_binding"] != profile["source"]):
            raise ValueError("Tip rack source binding differs from the pinned profile.")
        return _commercial(profile)
    raise ValueError("Unsupported tip rack kind.")
