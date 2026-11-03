"""Canonical, offline purchase proposal for every supported project route.

Amounts describe mutually exclusive purchase groups, never repeated viewer meshes.
Reviewed references are candidates, not replacements for accepted source geometry.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlencode

REVIEWED_ON = "2026-11-03"
FRIDGE_URL = "https://www.accucold.com/product/ARS1MLDL2B"
CAMERA_URL = "https://www.adafruit.com/product/5657"
GRIPPER_URL = "https://www.servocity.com/servo-driven-parallel-gripper-kit-servo-included/"
GRIPPER_GUIDE = (
    "https://www.servocity.com/content/user_manuals/3219-0001-0002_assembly_instructions.min.pdf"
)
SCICLOPS_URL = (
    "https://hudsonrobotics.com/wp-content/uploads/2023/02/HUD-0020.19.1-BR-SCICLOPS-23-1.pdf"
)
FABRICATION_URL = "https://www.protolabs.com/services/3d-printing/"
TIPS_URL = "https://opentrons.com/products/opentrons-300ul-tips-1000-refills"
PLATE_URL = (
    "https://ecatalog.corning.com/life-sciences/b2c/US/en/Microplates/Assay-Microplates/"
    "96-Well-Microplates/Corning%C2%AE-96-well-Clear-Polystyrene-Microplates/p/3596"
)
PIPETTE_URL = "https://science-jubilee.readthedocs.io/en/latest/building/pipette_tool.html"


def _fabrication_targets(project):
    kinds = {
        "labware_rack": "rim_supported_tube_rack",
        "labware_plate": "microplate_96",
        "tip_rack": "rim_supported_tip_rack",
    }
    return {
        module["target_component_id"]
        for key, kind in kinds.items()
        if isinstance(module := project.get(key), dict)
        and module.get("kind") == kind
        and module.get("target_component_id")
    }


def _source_candidate(row, project):
    gid = row["group_id"]
    if gid == "pipette":
        return (
            PIPETTE_URL,
            "Science Jubilee Opentrons pipette tool reference",
            "open_design_reference",
        )
    if gid == "power":
        return (
            "https://www.adafruit.com/category/137",
            "Adafruit power supply catalogue",
            "supplier_category",
        )
    if gid == "labware-plate":
        return PLATE_URL, "Corning 3596 plate and separate custom holder", "product_candidate"
    if gid == "tip-rack-options":
        module = project.get("tip_rack") or {}
        if module.get("kind") == "rim_supported_tip_rack":
            return (
                FABRICATION_URL,
                "Custom printed holder for separately purchased tips",
                "fabrication_service",
            )
        if module.get("profile_id") == "tipone_96_tiprack_200ul":
            return (
                "https://www.usascientific.com/act",
                "USA Scientific TipOne 200 µL stack racks — 1111-0200",
                "product_candidate",
            )
        return (
            TIPS_URL,
            "Opentrons OT-2 300 µL tips; check chosen volume profile",
            "product_candidate",
        )
    if any(key in gid for key in ("fixtures", "labware-rack", "inspection-mount", "frame")):
        return (
            FABRICATION_URL,
            "Custom parts — Protolabs fabrication quotation route",
            "fabrication_service",
        )
    return (
        "https://www.adafruit.com/search?" + urlencode({"q": row["label"]}),
        "Supplier search for " + row["label"],
        "supplier_search",
    )


def _money(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _allowance(row):
    """Explicit engineering budget scenarios; none of these are supplier facts."""
    gid = row["group_id"]
    text = (gid + " " + row["label"]).lower()
    if gid == "cold-transfer-fridge":
        return 900, 2200, "One compact laboratory refrigerator; custom door actuation excluded."
    if gid == "cold-transfer-motion":
        return (
            300,
            1200,
            (
                "One custom Cartesian transfer assembly: rails, drives, gripper, bracket, "
                "local controls and wiring; excludes refrigerator and main workstation."
            ),
        )
    if "upstream-platform:" in gid:
        return 50, 400, "One labelled kit only; no kit constituents charged separately."
    if gid == "upstream-platform":
        return 350, 1000, "Remaining base hardware only; excludes every separately listed kit."
    if gid == "platform":
        from app.platform_profiles import platform_profiles

        context = next(p for p in platform_profiles() if p["id"] == "opentrons-ot2")["cost_context"]
        amount = context["amount"]
        return (
            amount,
            _money(amount * 1.4),
            (
                f"OT-2 starts at ${amount:,.0f}; upper bound adds a proposed 40% allowance, "
                "not a quote. One pipette included in this scenario."
            ),
        )
    if gid == "labware-plate":
        return (
            292.99,
            432.99,
            (
                "One Corning 3596 case of 50 at the dated manufacturer listing of $282.99 "
                "plus a proposed $10–150 custom-holder fabrication allowance. "
                "This scenario purchases the full case, not a fictitious single-plate vendor unit."
            ),
        )
    if any(word in text for word in ("camera", "inspection-camera")):
        return 30, 100, "Camera, local holder and cable only; host and arm excluded."
    if any(word in text for word in ("arm", "gantry", "motion", "robot")):
        return 100, 900, "Custom mechanism fabrication and basic drives; commissioning excluded."
    if any(word in text for word in ("printer", "balance", "scale", "scanner", "reader")):
        return (
            100,
            1000,
            ("Equipment class allowance; exact capacity, accessories and SKU unresolved."),
        )
    if any(word in text for word in ("motor", "driver", "controller", "sensor", "probe")):
        return 10, 80, "One basic electronics/drive item; ratings and connections need selection."
    if any(word in text for word in ("cool", "peltier", "refrig")):
        return 40, 180, "One cooling subassembly; thermal performance remains unverified."
    if "pipette" in text:
        return 100, 450, "One basic pipetting mechanism and custom mount; calibration excluded."
    if any(word in text for word in ("frame", "power")):
        return 60, 300, "One labelled structural or electrical scope, excluding other rows."
    return (
        10,
        150,
        (
            "One labelled item/set, simple polymer print or cut stock plus local fixing hardware; "
            "outsourced fabrication at the upper bound. Material/process remain proposals."
        ),
    )


def _references(row, group):
    alternatives = [
        {
            "label": o["label"],
            "url": o["source_url"],
            "note": o.get("compatibility_note") or "Review fit, ratings and included accessories.",
        }
        for o in group.get("options", [])
        if o.get("id") != group.get("selected_id") and o.get("source_url")
    ]
    source = row.get("price_source_url")
    instruction = (
        "Review the selected source's dimensions and interfaces before fabrication or purchase."
    )
    if row["group_id"] == "cold-transfer-fridge":
        source = FRIDGE_URL
        instruction = (
            "Candidate ARS1MLDL2B is 17.5 × 19.75 × 21.5 inches, 115 V/60 Hz, "
            "2–10 °C. Compare its cabinet, door sweep and shelf access with the project's "
            "custom bay; its envelope has NOT replaced the displayed geometry. Plan a "
            "separate door interface, cold-chain check and manual recovery before automation."
        )
        alternatives.append(
            {
                "label": "Keep manual cold storage transfer",
                "url": FRIDGE_URL,
                "note": "Same refrigerator candidate; retain manual door/transfer.",
            }
        )
    elif row["group_id"] == "cold-transfer-motion":
        source = GRIPPER_URL
        instruction = (
            "Build the proposed gantry from its project dimensions; select rail travel, "
            "payload, drives and end stops. The linked servo gripper is a mechanism "
            "reference only: opening, plate retention, jaw design and full transfer reach "
            "are NOT established. Fit custom fingers to a dummy plate and test manual "
            "release and unpowered recovery before any powered commissioning."
        )
        alternatives.append(
            {
                "label": "Hudson SciClops commercial plate handler",
                "url": SCICLOPS_URL,
                "note": (
                    "Separate architecture requiring a vendor quote and reach/door "
                    "integration review; not fitted to this custom bay."
                ),
            }
        )
    return source, alternatives, instruction


def build_parts_proposal(
    project: dict, report: dict | None = None, estimate: dict | None = None
) -> dict:
    """Pure revision-bound view; never fetch sources, mutate state or call a model."""
    from app.price_estimation import estimate_for_project
    from app.procurement import initial_procurement_rows, procurement_groups, report_for_project

    # Document previews may carry a legacy partial report. It is not a valid
    # current observation without expiry/fetch metadata; keep it out of prices.
    current = (
        report_for_project(project, report)
        if (
            isinstance(report, dict)
            and report.get("expires_at")
            and isinstance(report.get("rows"), list)
        )
        else None
    )
    cost = estimate_for_project(project, estimate, current)
    priced = {r["group_id"]: r for r in (cost or {}).get("rows", [])}
    observed = {r["group_id"]: r for r in (current or {}).get("rows", [])}
    groups = {g["id"]: g for g in procurement_groups(project)}
    concepts = {
        "concept-" + p["key"]: p for p in (project.get("concept_design") or {}).get("parts", [])
    }
    rows = []
    for purchase in initial_procurement_rows(project):
        gid, quantity = purchase["group_id"], purchase["quantity"]
        low, high, note = _allowance(purchase)
        if gid == "tip-rack-options":
            tips = project.get("tip_rack") or {}
            if tips.get("kind") == "rim_supported_tip_rack":
                low, high, note = (
                    30,
                    200,
                    (
                        "Proposed $10–150 holder fabrication plus $20–50 for a separate pack "
                        "of purchased tips. Exact tip SKU, pack size and fit need review; "
                        "the printed part is only a reusable holder, never disposable tips."
                    ),
                )
            elif tips.get("profile_id") == "tipone_96_tiprack_200ul":
                low, high, note = (
                    30,
                    120,
                    (
                        "Planning allowance for one supplier pack of TipOne 200 µL stack racks "
                        "(1111-0200); current pack size and price require a supplier quote. "
                        "No printed holder is charged."
                    ),
                )
            else:
                low, high, note = (
                    40,
                    160,
                    (
                        "Planning allowance for one supplier pack of Opentrons OT-2 300 µL "
                        "tips/racks; select rack/refill packaging and obtain its current price. "
                        "No printed holder is charged."
                    ),
                )
        low, high = low * quantity, high * quantity
        kind, date, price_url = "planning_allowance", REVIEWED_ON, None
        item = priced.get(gid, {})
        observation = observed.get(gid, {})
        if item.get("low_usd") is not None and item.get("high_usd") is not None:
            low, high = item["low_usd"], item["high_usd"]
            kind = item["source_kind"]
            note = " ".join([item.get("rationale", ""), *item.get("assumptions", [])])
            date = item.get("fetched_at") or (cost or {}).get("generated_at")
            price_url = item.get("price_source_url")
        elif observation.get("freshness") == "fresh" and observation.get("line_total") is not None:
            low = high = observation["line_total"]
            kind, date = "verified_supplier", observation["fetched_at"]
            price_url = observation.get("price_source_url")
            note = "Observed purchase total including required whole packs."
        source, alternatives, assembly = _references(purchase, groups[gid])
        source_label, source_kind = purchase["label"], "selected_project_reference"
        if not source or gid in ("labware-plate", "tip-rack-options"):
            prior = source
            source, source_label, source_kind = _source_candidate(purchase, project)
            if gid in concepts and concepts[gid].get("basis") == "custom_concept":
                source, source_label, source_kind = (
                    FABRICATION_URL,
                    "Custom design — Protolabs fabrication quote route",
                    "fabrication_service",
                )
            if prior:
                alternatives.append(
                    {
                        "label": "Pinned software geometry reference",
                        "url": prior,
                        "note": "Dimension reference only; not a purchasable physical item.",
                    }
                )
        if gid == "upstream-platform":
            source_label = "Jubilee base remainder — excludes listed kits and custom groups"
        if gid == "cold-transfer-fridge":
            source_label = "Accucold ARS1MLDL2B refrigerator candidate"
        if gid == "cold-transfer-motion":
            source_label = "ServoCity 3219-0001-0002 reference + custom Cartesian gantry"
        if (
            gid == "tip-rack-options"
            and (project.get("tip_rack") or {}).get("kind") == "rim_supported_tip_rack"
        ):
            alternatives.append(
                {
                    "label": "Purchase disposable tips separately — USA Scientific catalogue",
                    "url": "https://www.usascientific.com/act",
                    "note": (
                        "Select tips from measured dimensions and pipette interface; "
                        "holder does not imply compatibility."
                    ),
                }
            )
        if source_kind in ("supplier_category", "supplier_search", "fabrication_service"):
            assembly += (
                " This is a sourcing/quotation route; SKU and fabrication process need selection."
            )
        if project.get("design", {}).get("platform") and gid == "platform":
            source = "https://opentrons.com/products/ot-2-robot"
            # Keep current supplier/model facts if present. The offline scenario
            # otherwise uses the manufacturer's advertised entry configuration.
            if kind == "planning_allowance":
                price_url = "https://opentrons.com/products/categories/robots"
        if project.get("design", {}).get("platform") and gid == "pipettes":
            low = high = 0
            kind, date, price_url = "included_in_base", REVIEWED_ON, None
            note = (
                "One pipette is included in the OT-2 base scenario; do not charge it twice. "
                "Additional channels/ranges require a separate quote."
            )
        part = concepts.get(gid, {})
        if part.get("assembly"):
            assembly = part["assembly"] + " " + assembly
        if project.get("bench_station"):
            assembly = " ".join(project["bench_station"].get("steps", [])) + " " + assembly
        row = {
            "group_id": gid,
            "selected_id": purchase["selected_id"],
            "label": groups[gid].get("label") or purchase["label"],
            "selected_product_label": source_label,
            "source_kind": source_kind,
            "quantity": quantity,
            "unit": part.get("unit") or "item/set",
            "component_ids": purchase["component_ids"],
            "unit_price_low_usd": _money(low / quantity),
            "unit_price_high_usd": _money(high / quantity),
            "line_total_low_usd": _money(low),
            "line_total_high_usd": _money(high),
            "price_kind": kind,
            "price_note": note,
            "source_url": source,
            "unit_price_basis": (
                "Derived allocation of the entire purchase-group budget, not a quoted unit price; "
                "whole packs and scoped accessories are included in the line total."
            ),
            "evidence": {
                "kind": kind,
                "observed_at": date,
                "url": price_url,
                "reference_reviewed_on": REVIEWED_ON
                if source in (FRIDGE_URL, GRIPPER_URL)
                else None,
            },
            "alternatives": alternatives,
            "assembly_steps": [
                {
                    "title": "Select and integrate " + purchase["label"],
                    "instruction": assembly,
                    "url": GRIPPER_GUIDE if gid == "cold-transfer-motion" else source,
                }
            ],
        }
        if gid == "upstream-platform":
            row["label"] = "Jubilee base remainder (listed kits excluded)"
        for cid in purchase["component_ids"]:
            if cid in _fabrication_targets(project):
                row["fabrication_url"] = (
                    f"/api/projects/{project['id']}/parts/{cid}/model.step"
                    f"?revision={project['revision']}"
                )
                row["fabrication_stl_url"] = row["fabrication_url"].replace(
                    "model.step?", "model.stl?"
                )
                alternatives.append(
                    {
                        "label": "Current custom holder/rack STEP model",
                        "url": row["fabrication_url"],
                        "note": "Revision-bound proposal; verify fit before manufacture.",
                    }
                )
                alternatives.append(
                    {
                        "label": "Current custom holder/rack STL model",
                        "url": row["fabrication_stl_url"],
                        "note": "Print only the holder; purchase disposable tips separately."
                        if gid == "tip-rack-options"
                        else "Check fit before manufacture.",
                    }
                )
        if gid in concepts and part["key"] in {
            c["key"] for c in project["concept_design"]["components"]
        }:
            row["fabrication_url"] = (
                f"/api/projects/{project['id']}/concept/parts/{part['key']}.step"
                f"?revision={project['revision']}"
            )
        if source in (CAMERA_URL, GRIPPER_URL):
            row["reference_observation"] = {
                "unit_price_usd": 29.25 if source == CAMERA_URL else 34.99,
                "observed_on": REVIEWED_ON,
                "url": source,
                "scope": "Camera board only, excluding host, holder and cables."
                if source == CAMERA_URL
                else (
                    "Gripper kit with servo only; no separate charge above the gantry allowance."
                ),
                "included_in_total": False,
            }
        rows.append(row)
    return {
        "schema_version": 1,
        "project_id": project["id"],
        "project_revision": project["revision"],
        "currency": "USD",
        "rows": rows,
        "summary": {
            "total_low_usd": _money(sum(r["line_total_low_usd"] for r in rows)),
            "total_high_usd": _money(sum(r["line_total_high_usd"] for r in rows)),
            "priced_count": len(rows),
            "unpriced_count": 0,
            "row_count": len(rows),
            "supplier_priced_count": sum(r["price_kind"] == "verified_supplier" for r in rows),
            "exclusions": [
                "Shipping, sales tax, duties, engineering, assembly labor, validation and support."
            ],
        },
        "limitations": [
            "Planning allowances are proposed budgets, not vendor quotes or price observations.",
            "Reference products do not change accepted geometry or establish compatibility.",
            "Each row is one purchase scope; alternatives are excluded from the total.",
            "The listed-scope total is not a complete commissioned-machine quotation.",
        ],
    }


def cold_transfer_candidate_rows(project: dict) -> list[dict]:
    """Discuss sourced options without adding hardware or altering project state."""
    scenario = {
        "id": project["id"],
        "revision": project["revision"],
        "sourcing": {
            "groups": [
                {
                    "id": gid,
                    "quantity": 1,
                    "component_ids": [],
                    "selected_id": "proposal",
                    "options": [{"id": "proposal", "label": label, "source_url": None}],
                }
                for gid, label in (
                    ("cold-transfer-fridge", "Dedicated laboratory refrigerator candidate"),
                    ("cold-transfer-motion", "Custom plate transfer gantry and gripper proposal"),
                )
            ]
        },
    }
    return build_parts_proposal(scenario)["rows"]


def render_part_model(project: dict, component_id: str, format: str) -> bytes:
    """Export only a canonical rack/holder; never load or rebuild the upstream machine."""
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from build123d import Unit, export_step, export_stl

    from app.cad_exports import _build_plate_part, _build_solid, _components

    if format not in ("step", "stl"):
        raise ValueError("Only STEP or STL is supported.")
    if component_id not in _fabrication_targets(project):
        raise ValueError("This component is not a custom fabrication model.")
    component = next((c for c in _components(project) if c["id"] == component_id), None)
    if not component or component.get("fabrication_shape") not in (
        "rim_supported_tube_rack",
        "rim_supported_tip_rack",
        "microplate_holder",
    ):
        raise ValueError("No standalone fabrication model is available for this component.")
    solid = (
        _build_plate_part(component, "holder-")
        if component["fabrication_shape"] == "microplate_holder"
        else _build_solid(component)
    )
    if solid is None or not solid.is_valid or solid.volume <= 0:
        raise ValueError("The proposed fabrication solid is invalid.")
    with TemporaryDirectory() as directory:
        path = Path(directory) / ("part." + format)
        if format == "step":
            export_step(solid, path, unit=Unit.MM)
        else:
            export_stl(solid, path)
        return path.read_bytes()
