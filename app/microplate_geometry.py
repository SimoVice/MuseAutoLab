"""Schematic 96-well reference and shallow microplate holder, in millimetres.

The Opentrons software definition is not manufacturer CAD. Pocket dimensions
use ANSI/SLAS 1-2004 nominal footprint and overall +/-0.50 mm tolerance.
Proposed process: FDM, material not selected; 0.40 mm functional clearance
per side plus 0.30 mm assumed total pocket undersize. Neither process nor fit
is validated. The shallow lip assumes a suitable base profile; verify the actual
plate, mounting, handling, material and printer before fabrication.
"""

import json
from hashlib import sha256
from pathlib import Path

PROFILE_ID = "corning_96_wellplate_360ul_flat"
DATA_DIR = Path(__file__).parent / "data" / "labware"
SOURCE_PATH = DATA_DIR / (PROFILE_ID + ".json")
SOURCE_SHA256 = "c13f112e52893e781c59ced9e6418ff10a5e2cc4b4877fd9559045f2f475558d"
SOURCE_REVISION = "95a8a37922cfd5f46ad26c983bcc1659fa13b6e1"
SOURCE_URL = (
    "https://github.com/Opentrons/opentrons/blob/"
    + SOURCE_REVISION
    + "/shared-data/labware/definitions/2/corning_96_wellplate_360ul_flat/1.json"
)
LICENSE_URL = "https://github.com/Opentrons/opentrons/blob/" + SOURCE_REVISION + "/LICENSE"
MICROPLATE_GEOMETRY_SOURCE_SHA256 = sha256(Path(__file__).read_bytes()).hexdigest()
SLAS_LENGTH_MM = 127.76
SLAS_WIDTH_MM = 85.48
SLAS_OVERALL_PLUS_TOLERANCE_MM = 0.50
FUNCTIONAL_CLEARANCE_PER_SIDE_MM = 0.40
ASSUMED_FDM_UNDERSIZE_MM = 0.30
WALL_THICKNESS_MM = 3.0
FLOOR_THICKNESS_MM = 2.5
LIP_HEIGHT_MM = 2.0


def compile_microplate(profile_id: str) -> dict:
    """Compile a fixed, pinned software reference into shared app primitives."""
    if profile_id != PROFILE_ID:
        raise ValueError("Unsupported microplate profile.")
    raw = SOURCE_PATH.read_bytes()
    if sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("Pinned microplate definition hash mismatch.")
    data = json.loads(raw)
    provenance = json.loads((DATA_DIR / "provenance.json").read_text(encoding="utf-8-sig"))
    expected_provenance = {
        "source_url": SOURCE_URL,
        "revision": SOURCE_REVISION,
        "sha256": SOURCE_SHA256,
        "license": "Apache-2.0",
        "license_url": LICENSE_URL,
    }
    if any(provenance.get(key) != value for key, value in expected_provenance.items()):
        raise ValueError("Pinned microplate provenance mismatch.")
    dims = data["dimensions"]
    length, width, height = (dims["xDimension"], dims["yDimension"], dims["zDimension"])
    pocket_l = (
        SLAS_LENGTH_MM
        + SLAS_OVERALL_PLUS_TOLERANCE_MM
        + 2 * FUNCTIONAL_CLEARANCE_PER_SIDE_MM
        + ASSUMED_FDM_UNDERSIZE_MM
    )
    pocket_w = (
        SLAS_WIDTH_MM
        + SLAS_OVERALL_PLUS_TOLERANCE_MM
        + 2 * FUNCTIONAL_CLEARANCE_PER_SIDE_MM
        + ASSUMED_FDM_UNDERSIZE_MM
    )
    outer_l = pocket_l + 2 * WALL_THICKNESS_MM
    outer_w = pocket_w + 2 * WALL_THICKNESS_MM
    total_h = FLOOR_THICKNESS_MM + height
    floor_center = -total_h / 2 + FLOOR_THICKNESS_MM / 2
    plate_bottom = -total_h / 2 + FLOOR_THICKNESS_MM
    order = [label for column in data["ordering"] for label in column]
    wells = []
    holes = []
    for label in order:
        w = data["wells"][label]
        wells.append(
            {
                "label": label,
                "x_mm": w["x"],
                "y_mm": w["y"],
                "z_mm": w["z"],
                "app_x_mm": w["x"] - length / 2,
                "app_y_mm": plate_bottom + w["z"] + w["depth"],
                "app_z_mm": w["y"] - width / 2,
                "diameter_mm": w["diameter"],
                "depth_mm": w["depth"],
                "total_liquid_volume_ul": w["totalLiquidVolume"],
            }
        )
        holes.append(
            {
                "x_mm": w["x"] - length / 2,
                "z_mm": w["y"] - width / 2,
                "radius_mm": w["diameter"] / 2,
            }
        )
    well = data["wells"]["A1"]
    bottom_h = height - well["depth"]
    primitives = [
        {
            "id": "holder-floor",
            "kind": "box",
            "position": [0, floor_center, 0],
            "size": [outer_l, FLOOR_THICKNESS_MM, outer_w],
            "appearance": "rack",
        },
    ]
    for sign, name in ((-1, "left"), (1, "right")):
        primitives.append(
            {
                "id": "holder-" + name,
                "kind": "box",
                "position": [
                    sign * (pocket_l + WALL_THICKNESS_MM) / 2,
                    plate_bottom + LIP_HEIGHT_MM / 2,
                    0,
                ],
                "size": [WALL_THICKNESS_MM, LIP_HEIGHT_MM, outer_w],
                "appearance": "rack",
            }
        )
    for sign, name in ((-1, "front"), (1, "back")):
        primitives.append(
            {
                "id": "holder-" + name,
                "kind": "box",
                "position": [
                    0,
                    plate_bottom + LIP_HEIGHT_MM / 2,
                    sign * (pocket_w + WALL_THICKNESS_MM) / 2,
                ],
                "size": [pocket_l, LIP_HEIGHT_MM, WALL_THICKNESS_MM],
                "appearance": "rack",
            }
        )
    primitives.extend(
        [
            {
                "id": "reference-plate-bottom",
                "kind": "box",
                "position": [0, plate_bottom + bottom_h / 2, 0],
                "size": [length, bottom_h, width],
                "appearance": "rack-top",
            },
            {
                "id": "reference-plate-wells",
                "kind": "plate",
                "position": [0, plate_bottom + bottom_h + well["depth"] / 2, 0],
                "size": [length, well["depth"], width],
                "appearance": "rack-top",
                "holes": holes,
            },
        ]
    )
    interfaces = [
        {
            "feature": "plate pocket length",
            "standard": "slas-microplate-footprint",
            "dimension": "footprint_length",
            "value": pocket_l,
            "intent": "envelope",
            "clearance": 2 * FUNCTIONAL_CLEARANCE_PER_SIDE_MM,
        },
        {
            "feature": "plate pocket width",
            "standard": "slas-microplate-footprint",
            "dimension": "footprint_width",
            "value": pocket_w,
            "intent": "envelope",
            "clearance": 2 * FUNCTIONAL_CLEARANCE_PER_SIDE_MM,
        },
    ]
    return {
        "size_mm": [outer_l, total_h, outer_w],
        "geometry": {"schema_version": "1", "primitives": primitives},
        "profile": {
            "id": profile_id,
            "display_name": data["metadata"]["displayName"],
            "source_dimensions_mm": [length, width, height],
            "source": provenance,
            "scope": "Pinned Opentrons software definition; schematic, not vendor CAD.",
        },
        "derived": {
            "well_count": len(wells),
            "well_capacity_ul": well["totalLiquidVolume"],
            "well_ordering": order,
            "wells": wells,
            "source_to_app": "app x = source x - length/2; app z = source y - width/2; "
            "source z is height from plate bottom; A1 is at positive app z",
            "holder_pocket_mm": [pocket_l, pocket_w],
            "holder_wall_mm": WALL_THICKNESS_MM,
            "holder_floor_mm": FLOOR_THICKNESS_MM,
            "holder_lip_mm": LIP_HEIGHT_MM,
        },
        "checks": {
            "interfaces": interfaces,
            "functional_clearance_per_side_mm": FUNCTIONAL_CLEARANCE_PER_SIDE_MM,
            "assumed_fdm_pocket_undersize_mm": ASSUMED_FDM_UNDERSIZE_MM,
            "physical_fit_verified": False,
            "material_selected": False,
            "scope": "Numerical design only; plate base profile, retention, tool access, "
            "print and mounting unverified.",
        },
    }
