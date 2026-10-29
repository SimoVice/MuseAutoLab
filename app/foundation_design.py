"""Adapt the pinned real platform with a custom, bounded liquid-preparation insert."""

from copy import deepcopy

from app.catalog import build_sourcing
from app.upstream_cad import ASSET_ID, foundation_metadata

REMOVED_TEMPLATE_IDS = {"column-left", "column-right", "crossbar", "cold-storage"}


def is_source_based(project: dict) -> bool:
    return project.get("design", {}).get("foundation", {}).get("id") == ASSET_ID


def foundation_sourcing(project: dict) -> dict:
    sourcing = build_sourcing(project["selections"], project["summary"]["cooling_enabled"])
    # The imported platform's native motors/electronics are not the old four-axis BOM.
    excluded = {"motors", "drivers", "controller", "frame", "linear-motion"}
    sourcing["groups"] = [g for g in sourcing["groups"] if g["id"] not in excluded]
    sourcing["groups"].insert(
        0,
        {
            "id": "upstream-platform",
            "label": "Jubilee open hardware platform",
            "quantity": 1,
            "component_ids": ["foundation-jubilee"],
            "selected_id": "source-cad",
            "options": [
                {
                    "id": "source-cad",
                    "label": "Pinned Jubilee V2.2.2 CAD / BOM",
                    "supplier": "Joshua Vasquez / Machine Agency",
                    "sku": None,
                    "unit_price": None,
                    "price_kind": "unpriced",
                    "source_url": foundation_metadata()["source_url"],
                    "checked_on": "2026-10-28",
                    "availability": "Source design; hardware not procured",
                    "pros": ["Original assembly geometry and source revision retained"],
                    "cons": ["Full upstream hardware BOM has not been priced or built"],
                    "compatibility_note": "CC BY 4.0 source CAD with a proposed bed pose and "
                    "custom liquid insert. Mounting, tools and controls remain unverified.",
                }
            ],
        },
    )
    selected = [
        next(o for o in g["options"] if o["id"] == g["selected_id"]) for g in sourcing["groups"]
    ]
    sourcing["subtotal"] = round(
        sum(g["quantity"] * (o["unit_price"] or 0) for g, o in zip(sourcing["groups"], selected)), 2
    )
    sourcing["unpriced_count"] = sum(o["unit_price"] is None for o in selected)
    sourcing["is_lower_bound"] = any(o["price_kind"] == "starting_at" for o in selected)
    return sourcing


def assembly_bounds(project: dict) -> dict:
    parts = project["design"]["components"]
    return {
        "min_mm": [min(p["position"][i] - p["size"][i] / 2 for p in parts) for i in range(3)],
        "max_mm": [max(p["position"][i] + p["size"][i] / 2 for p in parts) for i in range(3)],
    }


def adopt_foundation(project: dict, *, bed_drop_mm: float = 100) -> dict:
    """Prepare source geometry without claiming that a Meta proposal was accepted."""
    metadata = foundation_metadata(bed_drop_mm)
    result = deepcopy(project)
    design = result["design"]
    if design.pop("platform", None):
        from app.domain import _layout

        design["components"] = deepcopy(_layout(False)["components"])
    design["foundation"] = metadata
    result.pop("engineering_design", None)
    extension = result.pop("inspection_extension", None)
    old_ids = set(extension["component_ids"]) if extension else set()
    design["components"] = [
        p
        for p in design["components"]
        if p["id"] not in REMOVED_TEMPLATE_IDS | old_ids | {"foundation-jubilee"}
    ]
    index = {p["id"]: p for p in design["components"]}
    origin = metadata["deck_origin_app_mm"]
    sx, sy, sz = metadata["bbox_mm"]
    design["components"].insert(
        0,
        {
            "id": "foundation-jubilee",
            "kind": "upstream-cad",
            "label": "Jubilee source CAD platform",
            "position": [0, sy / 2, 0],
            "size": [sx, sy, sz],
            "foundation_asset_id": ASSET_ID,
        },
    )
    index["base"]["label"] = "Custom workflow deck on Jubilee platform"
    index["base"]["size"] = [300, 12, 300]
    index["base"]["position"] = [origin[0], origin[1] + 6, origin[2]]
    deck_top = origin[1] + 12
    positions = {
        "source-rack": (-70, -65),
        "sample-rack": (70, -65),
        "tip-rack": (-70, 35),
        "controller": (70, 50),
        "tip-waste": (-70, 110),
    }
    for cid, (x, z) in positions.items():
        part = index[cid]
        part["position"] = [origin[0] + x, deck_top + part["size"][1] / 2, origin[2] + z]
    index["controller"]["label"] = "Custom pipette interface enclosure"
    index["pipette"]["position"] = [origin[0], deck_top + 140, origin[2]]
    index["carriage"]["position"] = [origin[0], deck_top + 235, origin[2]]
    index["carriage"]["label"] = "Custom pipette adapter concept"
    width = result["summary"].get("workspace_width_mm")
    design["constraint_status"] = (
        "unconstrained" if width is None else "fits" if width >= sx else "infeasible"
    )
    design["assumptions"] = [
        "The fixed platform is original, pinned Jubilee CAD; its frame is not rescaled.",
        "The insert, pipette adapter, racks and interfaces are proposed custom geometry.",
        "Bed drop is a proposed pose; travel, connections and collisions are unchecked.",
        "Placement checks do not establish mounting, fabrication or laboratory performance.",
    ]
    design["footprint"] = {"width_mm": sx, "height_mm": sy, "depth_mm": sz}
    design.pop("assembly_bounds", None)
    design["assembly_bounds"] = assembly_bounds(result)
    result["sourcing"] = foundation_sourcing(result)
    design["estimated_cost"] = {"amount": result["sourcing"]["subtotal"], "currency": "USD"}
    return result


def compile_source_layout(project: dict, proposal: dict, provenance: dict) -> dict:
    result = adopt_foundation(project, bed_drop_mm=proposal["bed_drop_mm"])
    design = result["design"]
    origin = design["foundation"]["deck_origin_app_mm"]
    index = {p["id"]: p for p in design["components"]}
    index["base"]["size"][0] = proposal["deck_width_mm"]
    index["base"]["size"][2] = proposal["deck_depth_mm"]
    for placement in proposal["placements"]:
        part = index[placement["component_id"]]
        part["position"][0] = origin[0] + placement["x_mm"]
        part["position"][2] = origin[2] + placement["z_mm"]
    cooling = design["cooling"]
    if cooling["enabled"]:
        from app.catalog import cooling_envelope

        size = cooling_envelope(cooling["variant_id"])
        front = design["foundation"]["bbox_mm"][2] / 2
        design["components"].append(
            {
                "id": "cold-storage",
                "kind": "cooling",
                "label": "Proposed external cold sidecar",
                "position": [0, size[1] / 2 + 20, front + 40 + size[2] / 2],
                "size": size,
            }
        )
    design["assembly_bounds"] = assembly_bounds(result)
    width_limit = result["summary"].get("workspace_width_mm")
    design["constraint_status"] = "unconstrained" if width_limit is None else "fits"
    result["revision"] += 1
    result["status"] = "draft"
    result["engineering_design"] = {
        "schema_version": "1",
        "proposal": deepcopy(proposal),
        "provenance": deepcopy(provenance),
    }
    from app.geometry import add_geometry

    return add_geometry(result)
