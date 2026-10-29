"""Reviewed platform capabilities and procurement facts, separate from Meta advice."""

from copy import deepcopy

from app.commercial_design import commercial_metadata
from app.design_sources import resolve_reference


def platform_profiles() -> list[dict]:
    return [
        {
            "id": "jubilee",
            "label": "Build an open-hardware Jubilee platform",
            "procurement": "open_hardware",
            "reference_ids": ["jubilee-hardware", "science-jubilee"],
            "source_url": resolve_reference("jubilee-hardware")["url"],
            "acquisition": "Source the pinned project BOM and fabricate its specified parts; "
            "tools, electronics integration and liquid fixtures require review.",
            "geometry": "Original pinned STEP with bounded custom insert and bed pose",
            "supports_inspection_concept": True,
            "price": None,
            "availability": "Parts, kits and regional suppliers need verification",
            "limits": "Not a ready liquid handler. Pipette actuation/mounts, travel, controls, "
            "calibration and assembly labor are not validated or fully priced.",
        },
        {
            "id": "opentrons-ot2",
            "label": "Buy an assembled Opentrons OT-2 platform",
            "procurement": "prebuilt",
            "reference_ids": ["opentrons-ot2"],
            "source_url": resolve_reference("opentrons-ot2")["url"],
            "acquisition": "Request an official configuration/quote for the robot, compatible "
            "pipettes, tips and supported labware, then follow manufacturer setup.",
            "geometry": "Schematic manufacturer envelope with official software deck-slot layout; "
            "no manufacturer machine CAD is imported",
            "manufacturer": commercial_metadata(),
            "supports_inspection_concept": False,
            "price": None,
            "availability": "Configuration, price, stock and delivery require a quote",
            "limits": "Requires compatible instrument pipettes; the user's manual pipette is "
            "not assumed reusable. Custom arms/cooling integration and hardware "
            "control are not implemented. Calibration and labware checks remain necessary.",
        },
    ]


def selected_profile(project: dict) -> dict | None:
    from app.engineering import state_for

    selected = state_for(project)["selected_platform_id"]
    return next((deepcopy(p) for p in platform_profiles() if p["id"] == selected), None)


def commercial_sourcing() -> dict:
    """A quote checklist for an assembled platform, never the custom-frame BOM."""
    ref = resolve_reference("opentrons-ot2")
    groups = []
    for cid, label, component_ids, note in [
        (
            "platform",
            "Assembled OT-2 robot",
            ["ot2-envelope-left", "ot2-envelope-right"],
            "Request a robot configuration and regional quotation; price/stock not verified.",
        ),
        (
            "pipettes",
            "Compatible instrument pipettes",
            ["pipette", "carriage"],
            "Select ranges/channels for the transfers; manual pipettes are not assumed compatible.",
        ),
        (
            "labware",
            "Supported tube racks, tubes and tip racks",
            ["source-rack", "sample-rack", "tip-rack"],
            "Check definitions, capacities, tips and calibration; bodies are placeholders.",
        ),
    ]:
        groups.append(
            {
                "id": cid,
                "label": label,
                "quantity": 1,
                "component_ids": component_ids,
                "selected_id": "quote-required",
                "options": [
                    {
                        "id": "quote-required",
                        "label": label,
                        "supplier": "Opentrons / compatible labware supplier",
                        "sku": None,
                        "unit_price": None,
                        "price_kind": "unpriced",
                        "source_url": ref["url"],
                        "checked_on": ref["checked_on"],
                        "availability": "Quote required",
                        "pros": [],
                        "cons": [note],
                        "compatibility_note": note,
                    }
                ],
            }
        )
    return {
        "checked_on": ref["checked_on"],
        "currency": "USD",
        "subtotal": 0,
        "is_lower_bound": False,
        "incomplete": True,
        "unpriced_count": len(groups),
        "groups": groups,
        "exclusions": [
            "Official quotation, shipping, taxes, "
            "installation, training, validation and ongoing consumables are not included"
        ],
    }


def engineering_guidance(project: dict) -> dict:
    """Revision-specific purchase/build steps with official links and unresolved items."""
    profile = selected_profile(project)
    if profile is None:
        return {
            "status": "choose_platform",
            "steps": [],
            "message": "Discuss the requirements and choose a proposed platform in chat first.",
        }
    if profile["id"] == "opentrons-ot2":
        steps = [
            {
                "title": "Specify and quote the configuration",
                "url": profile["source_url"],
                "detail": "Choose compatible pipette ranges/channels, racks and consumables "
                "from the transfer requirements. Obtain an actual regional quote.",
            },
            {
                "title": "Prepare the installation space",
                "url": profile["manufacturer"]["specifications_url"],
                "detail": "Allow the published envelope plus 200 mm around the instrument "
                "for ventilation; verify full bench access and installation requirements.",
            },
            {
                "title": "Unbox and install the instruments",
                "url": "https://docs.opentrons.com/ot-2/installation/unboxing/",
                "detail": "Follow the manufacturer instructions. The robot is purchased assembled; "
                "this project does not supply a custom robot-frame build sequence.",
            },
            {
                "title": "Calibrate and verify the labware",
                "url": "https://docs.opentrons.com/ot-2/installation/instruments/",
                "detail": "Install supported pipettes and perform required calibration and labware "
                "checks before any physical protocol. No control connection is implemented here.",
            },
        ]
    else:
        steps = [
            {
                "title": "Review the pinned project and BOM",
                "url": profile["source_url"],
                "detail": "Use the upstream assembly guide/BOM at the recorded revision, "
                "then obtain dated supplier quotations. The full platform is unpriced.",
            },
            {
                "title": "Source and fabricate the specified parts",
                "url": profile["source_url"],
                "detail": "Separate purchased, printed/machined and already-owned parts. "
                "Follow upstream drawings and check fit before ordering quantities.",
            },
            {
                "title": "Review the liquid-handling tool interface",
                "url": resolve_reference("science-jubilee")["url"],
                "detail": "Compare documented tools against the actual pipette. The custom insert, "
                "adapter and actuation shown here are engineering proposals requiring review.",
            },
            {
                "title": "Assemble, calibrate and verify",
                "url": profile["source_url"],
                "detail": "Follow upstream assembly/calibration guides and verify connections, "
                "travel and collision clearances. No hardware performance is established here.",
            },
        ]
    return {
        "status": "planning",
        "platform_id": profile["id"],
        "steps": steps,
        "message": "Purchase and assembly guidance for the chosen route; "
        "quotations, compatibility and physical verification remain open.",
    }
