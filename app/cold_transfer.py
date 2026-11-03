"""Bounded digital cold transfer for a prepared rigid 96-well plate."""

import re
from copy import deepcopy

LIMITATIONS = [
    "Digital concept only: no hardware control, collision simulation or physical validation.",
    "Only the selected rigid 96-well plate moves; its custom holder stays on the deck.",
    "Gripping, liquid retention, lid handling, condensation and "
    "thermal performance are unverified.",
    "Dedicated refrigerator and transfer hardware are custom, unselected and unpriced.",
    "Static envelopes exclude open-lid and jaw swept volumes; bench clearance remains unverified.",
]


def offline_cold_transfer_intent(message: str) -> str | None:
    """Canonical convenience commands, exclusively during provider unavailability."""
    text = message.casefold().strip()
    if re.fullmatch(
        r"(?:please )?add a (?:manipulator|gripper) to transfer the "
        r"(?:prepared |rigid |prepared rigid )?plate to a dedicated refrigerator[.!]?", text
    ):
        return "add"
    if re.fullmatch(
        r"(?:please )?remove the (?:refrigerator transfer manipulator|"
        r"cold-transfer module|cold transfer module)[.!]?", text
    ):
        return "remove"
    return None


COLD_ACTIONS = {
    "add_cold_transfer": "add", "remove_cold_transfer": "remove",
    "discuss_cold_transfer": "discuss", "clarify_cold_transfer": "clarify",
}


def semantic_cold_transfer_intent(turn, message: str, project: dict | None = None) -> str | None:
    """Validate model interpretation against this turn, never against prior wishes."""
    actions = [a for a in turn.actions if a.kind in COLD_ACTIONS]
    if not actions:
        return None
    action = actions[0]
    # A cold operation is atomic: unrelated updates must not disappear silently.
    from app.model_client import EngineeringUpdate, LabwareSelection, TipRackUpdate
    if (len(turn.actions) != 1 or turn.patch() or turn.labware.patch()
            or turn.engineering != EngineeringUpdate()
            or turn.labware_selection != LabwareSelection()
            or turn.tip_rack != TipRackUpdate()):
        return "clarify"
    if action.source not in message:
        return "clarify"
    intent = COLD_ACTIONS[action.kind]
    if intent in ("discuss", "clarify"):
        return intent
    text = message.casefold()
    if re.search(r"(?:[;.]\s*|\band\s+(?:then\s+|also\s+)?)(?:switch|replace|"
                 r"change|buy|reduce|increase|add|remove|set|give|install|design)\b", text):
        return "clarify"
    # A polite request remains operative when only the arm implementation is tentative.
    polite_add = bool(re.search(
        r"^\s*(?:please\s+)?(?:can|could|would)\s+you\s+(?:please\s+)?add\b", text
    ))
    tentative_arm = polite_add and bool(re.search(
        r"\bmaybe\s+(?:(?:a|an|the)\s+)?(?:arm|gripper|manipulator)\b", text
    ))
    guard_text = re.sub(r"\bmaybe\b", "", text) if tentative_arm else text
    # Independent guard against an unsafe model classification of an information
    # request, prohibition, hypothetical or extra engineering requirement.
    if re.search(r"^\s*(?:what|why|how|when\s+(?:will|would|can|could|does|is)|"
                 r"where|is|are|does|do we|can we|could we|would it)\b",
                 text) or re.search(r"\b(?:don't|do not|not|never|without|instead|if|maybe|later|"
                                    r"eventually|unless|only if)\b", guard_text):
        return "discuss"
    if re.search(r"\b(?:mm|cm|degrees?|celsius|fahrenheit|minutes?|seconds?|litres?|liters?)\b|"
                 r"\b\d+\s*\u00b0?[cf]\b", text):
        return "clarify"
    if intent == "remove":
        if re.search(r"\b(?:just|only|lid|door|shelf|jaw|motor|carriage|gantry|mast|"
                     r"gripper|refrigerator alone|fridge alone)\b", text):
            return "clarify"
        if (not re.search(r"cold[ -]transfer|refriger|fridge|cold[ -]storage", text)
                and not (project or {}).get("cold_transfer_extension")):
            return "clarify"
        if re.search(r"\b(?:keep|retain|preserve)\b", text):
            return "clarify"
        if re.search(r"camera|inspection|cooling", text):
            return "clarify"
        return intent
    grounding = action.cold_transfer
    if (grounding is None or grounding.payload != "selected_rigid_plate"
            or grounding.destination != "dedicated_refrigerated"):
        return "clarify"
    payload = grounding.payload_source
    destination = grounding.destination_source
    if (not payload or not destination or payload not in action.source
            or destination not in action.source):
        return "clarify"
    if re.search(r"shared|existing|communal|freezer|incubator", destination.casefold()):
        return "clarify"
    # A quoted cold cabinet can be the departure location. The adapter supports
    # incoming storage only; a model role label cannot reverse the user's route.
    if re.search(r"\b(?:from|out of)\s+(?:(?:the|a|an|its|own|dedicated|new)\s+)*"
                 r"(?:fridge|refriger\w*|chilled\s+cabinet|cold\s+storage)", text):
        return "clarify"
    try:
        require_supported_payload_request(message)
    except ValueError:
        return "clarify"
    return intent


def require_supported_payload_request(message: str) -> None:
    """Do not silently reinterpret a request for an incompatible transported object."""
    text = message.casefold()
    # Mentioning an existing camera is expected. Reject it only as a payload.
    camera_payload = re.search(r"\b(?:carry|move|transfer|store|place|put|pick up|give|send|"
                               r"take|sposta)\s+"
                               r"(?:(?:my|the|our|a|la|inspection)\s+)?camera\b", text)
    holder_payload = re.search(r"\b(?:carry|move|transfer|store|place|put|pick up|give|"
                               r"send|take)\s+"
                               r"(?:(?:my|the|our|a)\s+)?(?:plate\s+)?(?:holder|rack|lid)\b",
                               text)
    if camera_payload or holder_payload or re.search(
                                    r"\b(tubes?|provett\w*|vials?|bottles?|flasks?|centrifug\w*|"
                                    r"microscope|microscopio)\b", text):
        raise ValueError("This cold-transfer adapter moves only the selected rigid 96-well "
                         "plate. The requested object has no supported transfer adapter; "
                         "the existing project is preserved.")


def clear_cold_transfer(project: dict) -> dict:
    result = deepcopy(project)
    old = result.pop("cold_transfer_extension", None)
    if old:
        ids = set(old["component_ids"])
        result["design"]["components"] = [
            p for p in result["design"]["components"] if p["id"] not in ids
        ]
        result["sourcing"]["groups"] = [
            g for g in result["sourcing"]["groups"] if not g["id"].startswith("cold-transfer-")
        ]
        from app.foundation_design import assembly_bounds

        result["design"]["assembly_bounds"] = assembly_bounds(result)
        result["sourcing"]["unpriced_count"] = sum(
            next(o for o in g["options"] if o["id"] == g["selected_id"])["unit_price"] is None
            for g in result["sourcing"]["groups"]
        )
    return result


def compile_cold_transfer(project: dict) -> dict:
    base = clear_cold_transfer(project)
    if not base.get("design", {}).get("foundation") or not base.get("engineering_design"):
        raise ValueError(
            "Cold transfer requires an accepted Jubilee layout; other platforms are unsupported."
        )
    if not base.get("labware_plate"):
        raise ValueError(
            "Cold transfer currently supports the selected rigid 96-well "
            "plate only. Select that plate first; loose tubes and tube racks are unsupported."
        )
    if base["labware_plate"].get("compatibility", {}).get("status") == "volume_conflict":
        raise ValueError("Resolve the plate volume conflict before adding cold transfer.")
    if base["design"].get("constraint_status") == "infeasible":
        raise ValueError("Resolve the workspace constraint before adding cold transfer.")
    parts = base["design"]["components"]
    sample = next(p for p in parts if p["id"] == "sample-rack")
    pickup = list(sample["position"])
    left = min(p["position"][0] - p["size"][0] / 2 for p in parts)
    x = left - 130
    from app.microplate_geometry import compile_microplate

    plate = compile_microplate(base["labware_plate"]["profile_id"])
    plate_parts = [
        p for p in plate["geometry"]["primitives"] if p["id"].startswith("reference-plate-")
    ]
    bottom_offset = min(p["position"][1] - p["size"][1] / 2 for p in plate_parts)
    storage = [x, 227.0 - bottom_offset, pickup[2]]
    height = max(p["position"][1] + p["size"][1] / 2 for p in parts) + 100
    components = []

    def part(cid, label, pos, size, appearance="structure"):
        components.append(
            {
                "id": cid,
                "kind": "cold-transfer",
                "label": label,
                "position": pos,
                "size": size,
                "geometry": {
                    "schema_version": "1",
                    "primitives": [
                        {
                            "id": "envelope",
                            "kind": "box",
                            "position": [0, 0, 0],
                            "size": size,
                            "appearance": appearance,
                        }
                    ],
                },
            }
        )

    part(
        "cold-transfer-fridge",
        "Dedicated refrigerated plate cabinet concept",
        [x, 190, pickup[2]],
        [220, 380, 260],
        "cooling",
    )
    part(
        "cold-transfer-shelf",
        "Internal plate landing shelf concept",
        [x, 223, pickup[2]],
        [160, 8, 110],
        "rack",
    )
    part(
        "cold-transfer-lid",
        "Hinged refrigerator lid concept",
        [x, 385, pickup[2]],
        [220, 10, 260],
        "lid",
    )
    part(
        "cold-transfer-gantry",
        "External Cartesian transfer gantry concept",
        [(x + pickup[0] - 90) / 2, height + 100, pickup[2]],
        [pickup[0] - x + 270, 30, 40],
        "rail",
    )
    part(
        "cold-transfer-mast",
        "Transfer gantry support concept",
        [x - 165, (height + 100) / 2, pickup[2]],
        [35, height + 100, 35],
    )
    part(
        "cold-transfer-carriage",
        "Plate transfer carriage concept",
        [pickup[0], height + 70, pickup[2]],
        [65, 30, 65],
        "motor",
    )
    part(
        "cold-transfer-shaft",
        "Telescoping gripper shaft concept",
        [pickup[0], height + 42.5, pickup[2]],
        [11, 25, 11],
        "rail",
    )
    components[-1]["geometry"]["primitives"][0]["kind"] = "cylinder"
    part(
        "cold-transfer-gripper",
        "Vertical plate gripper concept",
        [pickup[0], height + 25, pickup[2]],
        [160, 65, 95],
        "holder",
    )
    cabinet = components[0]
    cabinet["geometry"]["primitives"] = [
        {"id": name, "kind": "box", "position": pos, "size": size, "appearance": finish}
        for name, pos, size, finish in (
            ("service-base", [0, -144, 2], [220, 92, 256], "cooling"),
            ("front-fascia", [0, -144, -126], [216, 84, 4], "controller"),
            ("control-panel", [56, -140, -128.5], [54, 24, 1], "panel"),
            ("control-window", [56, -139, -129.5], [33, 8, 1], "insert"),
            ("wall-left", [-100, 46, 0], [20, 288, 260], "lid"),
            ("wall-right", [100, 46, 0], [20, 288, 260], "lid"),
            ("wall-front", [0, 46, -120], [180, 288, 20], "lid"),
            ("insulated-back", [0, 46, 120], [180, 288, 20], "cooling"),
            *((f"grille-{i}", [-49, -165 + i * 8, -129], [78, 3, 2], "vent")
              for i in range(6)),
        )
    ]
    lid = next(component for component in components if component["id"] == "cold-transfer-lid")
    lid["geometry"]["primitives"] = [
        {"id": name, "kind": "box", "position": pos, "size": size, "appearance": finish}
        for name, pos, size, finish in (
            ("window", [0, 0, 0], [200, 5, 240], "lid"),
            ("left-edge", [-105, 0, 0], [10, 10, 260], "frame"),
            ("right-edge", [105, 0, 0], [10, 10, 260], "frame"),
            ("front-edge", [0, 0, -125], [200, 10, 10], "holder"),
            ("hinge-edge", [0, 0, 125], [200, 10, 10], "frame"),
        )
    ]
    gripper = components[-1]
    open_jaw_x = plate["profile"]["source_dimensions_mm"][0] / 2 + 3 + 10
    gripper["geometry"]["primitives"] = [
        {"id": name, "kind": "box", "position": pos, "size": size, "appearance": "holder"}
        for name, pos, size in (
            ("gripper-bridge", [0, 0, 0], [150, 10, 95]),
            ("gripper-jaw-left", [-open_jaw_x, -15, 0], [6, 20, 65]),
            ("gripper-jaw-right", [open_jaw_x, -15, 0], [6, 20, 65]),
        )
    ]
    all_parts = parts + components
    bounds = {
        "min_mm": [min(p["position"][i] - p["size"][i] / 2 for p in all_parts) for i in range(3)],
        "max_mm": [max(p["position"][i] + p["size"][i] / 2 for p in all_parts) for i in range(3)],
    }
    width = project["summary"].get("workspace_width_mm")
    if width is not None and bounds["max_mm"][0] - bounds["min_mm"][0] > width:
        raise ValueError(
            "The dedicated refrigerator and transfer gantry exceed the "
            "recorded workspace width. Increase the allowed width before adding this concept."
        )
    return {
        "schema_version": "1",
        "kind": "prepared_plate_cold_transfer",
        "compiler": "cold-transfer-v1",
        "payload_component_id": "sample-rack",
        "payload_primitive_prefix": "reference-plate-",
        "pickup_mm": pickup,
        "storage_mm": storage,
        "transfer_height_mm": height,
        "shelf_top_mm": 227.0,
        "lid_open_angle_deg": 105.0,
        "components": components,
        "component_ids": [p["id"] for p in components],
        "assembly_bounds": bounds,
        "checks": [
            {
                "id": "workspace_width",
                "passed": True,
                "detail": "Static component envelopes only; motion clearance unverified.",
            }
        ],
        "limitations": list(LIMITATIONS),
        "provenance": {"kind": "deterministic_compiler", "compiler": "cold-transfer-v1"},
    }


def apply_cold_transfer(project: dict, *, bump: bool = True) -> dict:
    module = compile_cold_transfer(project)
    result = clear_cold_transfer(project)
    result["cold_transfer_extension"] = module
    result["design"]["components"].extend(deepcopy(module["components"]))
    result["design"]["assembly_bounds"] = deepcopy(module["assembly_bounds"])
    for cid, label in (
        ("cold-transfer-fridge", "Dedicated refrigerator concept"),
        ("cold-transfer-motion", "Plate transfer gantry and gripper concept"),
    ):
        result["sourcing"]["groups"].append(
            {
                "id": cid,
                "label": label,
                "quantity": 1,
                "component_ids": [cid] if cid.endswith("fridge") else module["component_ids"][1:],
                "selected_id": "unselected-concept",
                "options": [
                    {
                        "id": "unselected-concept",
                        "label": "Custom integration pending",
                        "supplier": "Not selected",
                        "sku": None,
                        "unit_price": None,
                        "price_kind": "unpriced",
                        "source_url": None,
                        "checked_on": "Not researched",
                        "availability": "Unverified",
                        "pros": [],
                        "cons": list(LIMITATIONS),
                        "compatibility_note": "Concept envelopes; no sourced product or "
                        "physical fit established.",
                    }
                ],
            }
        )
    result["sourcing"]["unpriced_count"] = sum(
        next(o for o in g["options"] if o["id"] == g["selected_id"])["unit_price"] is None
        for g in result["sourcing"]["groups"]
    )
    result["sourcing"]["incomplete"] = True
    if bump:
        result["revision"] += 1
        result["status"] = "draft"
    return result
