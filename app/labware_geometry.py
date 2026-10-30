"""Parametric rim-supported tube rack, millimetres in the application's y-up frame.

Process assumption: FDM, unselected material; print inverted with the top plate
on the bed. Tube envelopes are user-supplied and remain physically unchecked.
Only a closed circular cap envelope is represented; hinges are not checked.
"""
from __future__ import annotations

import math
from hashlib import sha256
from pathlib import Path

LABWARE_GEOMETRY_SOURCE_SHA256 = sha256(Path(__file__).read_bytes()).hexdigest()

RADIAL_CLEARANCE_MM = 0.4
BORE_TOLERANCE_MM = 0.3  # Assumed diameter deviation, either direction.
MIN_RIM_LAND_MM = 0.4
TOP_THICKNESS_MM = 4.0
END_WALL_MM = 3.0
MIN_WEB_MM = 3.0
TIP_CLEARANCE_MM = 3.0
CAP_GAP_MM = 0.8


def _number(spec, key, lower, upper, default=None):
    value = spec.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{key} must be a finite number.")
    if not lower <= value <= upper:
        raise ValueError(f"{key} must be between {lower} and {upper} mm.")
    return float(value)


def compile_labware_rack(spec: dict) -> dict:
    """Compile a bounded one-piece bridge rack from measured tube envelopes.

    Assumed FDM bore deviation is applied to diameter, not to each radius.
    The closed cap and rim are treated as circular envelopes. A real tube,
    printer, material, loading, deck attachment and open cap remain unchecked.
    """
    if not isinstance(spec, dict):
        raise ValueError("Rack specification must be an object.")
    body = _number(spec, "body_diameter_max_mm", 1, 100)
    rim = _number(spec, "rim_diameter_min_mm", 1, 120)
    cap = _number(spec, "cap_diameter_max_mm", 1, 150)
    below = _number(spec, "below_rim_height_mm", 1.1, 250)
    clearance = _number(spec, "radial_clearance_mm", 0.4, 5, RADIAL_CLEARANCE_MM)
    count, columns = spec.get("count"), spec.get("columns")
    if type(count) is not int or not 1 <= count <= 24:
        raise ValueError("count must be an integer between 1 and 24.")
    if type(columns) is not int or not 1 <= columns <= 8 or columns > count:
        raise ValueError("columns must be an integer between 1 and min(count, 8).")
    if cap < rim:
        raise ValueError("cap_diameter_max_mm must cover the stated minimum rim diameter.")
    bore = body + 2 * clearance + BORE_TOLERANCE_MM
    max_bore = bore + BORE_TOLERANCE_MM
    land = (rim - max_bore) / 2
    if land + 1e-9 < MIN_RIM_LAND_MM:
        raise ValueError("Rim is too narrow for the bore and minimum bearing land.")
    min_pitch = max(cap + CAP_GAP_MM, max_bore + MIN_WEB_MM)
    pitch = _number(spec, "pitch_mm", min_pitch, 200, min_pitch)
    rows = (count + columns - 1) // columns
    width = (columns - 1) * pitch + bore + 2 * (END_WALL_MM + MIN_WEB_MM)
    depth = (rows - 1) * pitch + bore + 2 * MIN_WEB_MM
    height = below + TIP_CLEARANCE_MM
    if height <= TOP_THICKNESS_MM:
        raise ValueError("Tube height leaves no room for rack legs.")
    for key, dimension in (("max_width_mm", width), ("max_depth_mm", depth),
                           ("max_height_mm", height)):
        if spec.get(key) is not None:
            limit = _number(spec, key, 1, 1000)
            if dimension > limit + 1e-9:
                raise ValueError(f"Rack exceeds {key}.")
    holes = [
        {"x_mm": (i % columns - (columns - 1) / 2) * pitch,
         "z_mm": (i // columns - (rows - 1) / 2) * pitch,
         "radius_mm": bore / 2}
        for i in range(count)
    ]
    leg_height = height - TOP_THICKNESS_MM
    primitives = [
        {"id": "perforated-top", "kind": "plate",
         "position": [0, height / 2 - TOP_THICKNESS_MM / 2, 0],
         "size": [width, TOP_THICKNESS_MM, depth], "appearance": "rack-top", "holes": holes},
    ]
    for sign, side in ((-1, "left"), (1, "right")):
        primitives.append({
            "id": f"leg-{side}", "kind": "box",
            "position": [sign * (width - END_WALL_MM) / 2, -TOP_THICKNESS_MM / 2, 0],
            "size": [END_WALL_MM, leg_height, depth], "appearance": "rack",
        })
    return {
        "size_mm": [width, height, depth],
        "geometry": {"schema_version": "1", "primitives": primitives},
        "derived": {"rows": rows, "columns": columns, "count": count,
                    "pitch_mm": pitch, "closed_cap_envelope_size_mm": [
                        (columns - 1) * pitch + cap, (rows - 1) * pitch + cap],
                    "bore_diameter_mm": bore,
                    "bore_max_assumed_mm": max_bore, "rim_land_min_assumed_mm": land,
                    "tip_clearance_mm": TIP_CLEARANCE_MM,
                    "top_thickness_mm": TOP_THICKNESS_MM, "end_wall_mm": END_WALL_MM},
        "checks": {"body_radial_clearance_min_assumed_mm": (bore - BORE_TOLERANCE_MM - body) / 2,
                   "rim_land_min_assumed_mm": land, "closed_cap_gap_mm": pitch - cap,
                   "hole_web_min_assumed_mm": pitch - max_bore},
    }
