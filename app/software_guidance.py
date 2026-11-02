"""Derived software guidance and a non-executable, revision-bound protocol template."""

from __future__ import annotations

from copy import deepcopy


def _source(sid: str, title: str, url: str, scope: str) -> dict:
    return {"id": sid, "title": title, "url": url, "scope": scope, "checked_on": "2026-10-31"}


def _route_software(route: str) -> tuple[list[dict], list[dict]]:
    if route == "jubilee":
        return (
            [
                {
                    "title": "Science Jubilee: Python protocols for a commissioned Jubilee",
                    "description": "Use Science Jubilee as the upstream programming route for a "
                    "compatible "
                    "Jubilee build. Its Python interfaces describe the machine, tools,"
                    " decks and labware; "
                    "it provides example notebooks. First configure and commission "
                    "the actual controller, tool and labware interfaces. MuseAutoLab "
                    "has not integrated "
                    "or tested a Science Jubilee hardware-control adapter for this "
                    "design. Provisional "
                    "controller entries are not evidence of a compatible commissioned controller.",
                }
            ],
            [
                _source(
                    "science-jubilee-start",
                    "Science Jubilee getting started",
                    "https://science-jubilee.readthedocs.io/en/latest/getting_started/index.html",
                    "Upstream Python machine/tool/deck/labware concepts and tutorials; "
                    "not proof that this custom design is commissioned.",
                ),
                _source(
                    "science-jubilee-install",
                    "Science Jubilee installation",
                    "https://science-jubilee.readthedocs.io/en/latest/getting_started/installation.html",
                    "Configure the upstream software environment for the actual instrument.",
                ),
            ],
        )
    if route == "opentrons-ot2":
        return (
            [
                {
                    "title": "Opentrons Python Protocol API and App",
                    "description": "Author a separate Python protocol using the official "
                    "Protocol API for "
                    "your OT-2, supported instruments and labware. Review it with the "
                    "documented local "
                    "simulation and App workflow, then perform instrument/labware "
                    "setup, calibration and "
                    "position checks. MuseAutoLab's JSON template is a specification, "
                    "not an Opentrons "
                    "protocol. opentrons_simulate protocol.py applies only to a "
                    "separately authored "
                    "Opentrons Python protocol; it does not execute this JSON or the "
                    "local preview.",
                },
                {
                    "title": "Opentrons Protocol Designer",
                    "description": "Consider the official visual protocol-authoring tool when the "
                    "desired "
                    "pipetting steps and selected OT-2 instruments/labware are "
                    "supported. Check the "
                    "resulting protocol with the App and actual setup; a generated "
                    "file is not validated "
                    "liquid-handling performance.",
                },
            ],
            [
                _source(
                    "opentrons-protocol-tutorial",
                    "Opentrons Python protocol tutorial",
                    "https://docs.opentrons.com/python-api/tutorial/",
                    "Authoring and setup workflow for supported Opentrons robots.",
                ),
                _source(
                    "opentrons-simulation",
                    "Opentrons execution and simulation reference",
                    "https://docs.opentrons.com/python-api/reference/execute-simulate/",
                    "Simulation of an authored Opentrons Python protocol, not this JSON template.",
                ),
                _source(
                    "opentrons-designer",
                    "About Opentrons Protocol Designer",
                    "https://docs.opentrons.com/protocol-designer/about/",
                    "Visual protocol authoring; supported steps and instrument choices"
                    " need review.",
                ),
                _source(
                    "opentrons-designer-instruments",
                    "Protocol Designer robot and instruments",
                    "https://docs.opentrons.com/protocol-designer/create-protocol/robot-instruments/",
                    "Choose robot and instrument configuration for a new protocol.",
                ),
            ],
        )
    return (
        [
            {
                "title": "Choose a supported platform before programming hardware",
                "description": "Continue platform and workflow discovery in chat. A general "
                "concept is "
                "not a commissioned pipetting instrument or an executable protocol.",
            }
        ],
        [],
    )


def build_software_guidance(project: dict) -> dict:
    """Separate reusable instrument configuration from one current preparation."""
    design = project.get("design") or {}
    route = (
        "opentrons-ot2"
        if design.get("platform")
        else "jubilee"
        if design.get("foundation")
        else "unselected"
    )
    plan = project.get("plan") or {}
    plate = project.get("labware_plate") or {}
    tip = project.get("tip_rack") or {}
    components = design.get("components") or []
    occupied = set((plate.get("compatibility") or {}).get("occupied_wells", []))
    binding = {
        "project_id": project.get("id"),
        "project_revision": project.get("revision", 0),
        "platform": route,
        "component_ids": [part["id"] for part in components],
        "labware_geometry": [
            {key: deepcopy(part.get(key)) for key in ("id", "size", "position", "slot_id")}
            for part in components
            if part["id"] in {"source-rack", "sample-rack", "tip-rack"}
        ],
        "plate_profile_id": plate.get("profile_id"),
        "plate_source_binding": deepcopy(plate.get("profile_binding")),
        "tip_rack_profile_id": tip.get("profile_id"),
        "tip_rack_source_binding": deepcopy(tip.get("profile_binding")),
        "plate_wells": [
            {
                key: deepcopy(well.get(key))
                for key in ("label", "app_x_mm", "app_y_mm", "app_z_mm", "total_liquid_volume_ul")
            }
            for well in (plate.get("derived") or {}).get("wells", [])
            if well["label"] in occupied
        ],
        "geometry_scope": "Reference/model coordinates only; not calibrated robot positions.",
        "component_slots": {
            part["id"]: part["slot_id"] for part in components if part.get("slot_id")
        },
    }
    transfers = [
        {
            "target": step.get("target"),
            "destination_component_id": step.get("destination_component_id", "sample-rack"),
            "destination_well": step.get("well_name"),
            "stock_volume_ul": step.get("stock_volume_ul"),
            "diluent_volume_ul": step.get("diluent_volume_ul"),
            "total_volume_ul": step.get("total_volume_ul"),
        }
        for step in plan.get("steps", [])
    ]
    scope = (
        "The workstation is a reusable pipetting-platform proposal. Its frame, motion, "
        "tool interfaces and labware arrangement are separate from the current preparation recipe."
    )
    limitations = [
        "MuseAutoLab currently checks the arithmetic of its supported dilution plan; "
        "it does not execute hardware protocols.",
        "Aliquoting, transfers and serial dilutions are possible upstream programming tasks, "
        "not automatically validated MuseAutoLab protocols or verified performance claims.",
        "Recheck tool, labware, deck, reach, transfer range and materials for each new task. "
        "A compatible recipe can reuse hardware; changed interfaces need a"
        " reviewed design revision.",
    ]
    authoring = [
        "Save this hardware project. Describe the next pipetting task, liquids, source and "
        "destination labware, transfer amounts, repeats and constraints in chat.",
        "Compare the task with the accepted platform, pipette, tip rack and labware. "
        "Keep compatible hardware; request a design revision for any changed fit or interface.",
        "Use the declarative template below as a specification. Assign real source positions, "
        "mixing, tip policy and liquid handling parameters explicitly; no "
        "values are inferred here.",
        "Download protocol-template.json and protocol-preview.py together. Run "
        "python protocol-preview.py protocol-template.json locally to check the recorded bindings "
        "and volume arithmetic and print the logical schedule. This does not connect to hardware.",
        "Review the protocol and upstream simulation where available, then commission and "
        "calibrate the actual machine. Perform supervised clearance and "
        "dispensing checks before samples.",
    ]
    route_steps = {
        "jubilee": [
            "In Science Jubilee, configure Machine and the actual calibrated tool, deck and "
            "labware interfaces using the official getting-started documentation and notebooks. "
            "Map each physical stock/diluent source and destination well explicitly.",
            "In a separate reviewed Python notebook or script, parameterize the transfer volumes "
            "and repeat loop for the new pipetting task. Record the configuration, source/well "
            "mapping and protocol results; review tool behavior and error recovery "
            "on the actual build.",
        ],
        "opentrons-ot2": [
            "Choose the actual OT-2 pipette, channels, tip rack and supported labware load names. "
            "Assign their deck slots, source/destination wells and volumes in a separate Protocol "
            "API Python file or a supported Protocol Designer workflow.",
            "For the authored Opentrons Python file, use the documented local simulation. "
            "Then import it into the App, review run setup, calibrate and check labware positions "
            "on the actual robot before a supervised test. "
            "Our JSON template is not that Python file.",
        ],
    }.get(route, [])
    authoring[4:4] = route_steps
    template = {
        "schema_version": 1,
        "kind": "declarative_pipetting_protocol",
        "execution_enabled": False,
        "status": "needs_review" if plan.get("status") == "ready" and transfers else "needs_recipe",
        "binding": binding,
        "units": {"volume": "uL", "geometry": "mm"},
        "current_preparation": {
            "workflow_kind": (project.get("workflow") or {}).get("kind"),
            "stock_concentration": (project.get("summary") or {}).get("stock_concentration"),
            "target_concentrations": (project.get("summary") or {}).get("target_concentrations"),
            "target_count": len(transfers),
            "transfers": transfers,
        },
        "unresolved_parameters": [
            "physical source-stock and diluent positions",
            "pipette model, channels and supported transfer range",
            "calibrated labware/tool offsets and approach depths",
            "liquid properties, aspiration/dispense rates and mixing",
            "tip reuse/change policy and contamination controls",
            "firmware/controller mapping, homing and stop/recovery behavior",
        ],
        "limits": limitations,
    }
    if project.get("cold_transfer_extension"):
        limitations.extend(project["cold_transfer_extension"]["limitations"])
        authoring.append("Treat cold transfer as a separate uncommissioned subsystem: "
                         "select refrigerator, drives and jaws; validate liquid retention, "
                         "clearances, interlocks and thermal performance before control.")
    return {
        "project_id": project.get("id"),
        "project_revision": project.get("revision", 0),
        "platform": route,
        "status": "needs_integration" if route != "unselected" else "planning_only",
        "reusable_hardware": scope,
        "current_preparation": (
            f"This revision contains {len(transfers)} preparation target(s). "
            "They describe one recipe, not the platform's lifetime capacity."
        ),
        "recommendations": _route_software(route)[0],
        "authoring_steps": authoring,
        "limitations": limitations,
        "sources": _route_software(route)[1],
        "protocol_template": template,
    }
