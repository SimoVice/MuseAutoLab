"""Revision-bound, source-grounded instruction previews without CAD or model calls.

Ready means ready to review the document. Upstream instructions are linked rather
than reproduced; unresolved custom interfaces become concrete engineering tasks.
"""

from __future__ import annotations

import html
import json
from copy import deepcopy
from urllib.parse import quote, urlsplit

from app.design_sources import project_source_basis, resolve_reference

CHECKED_ON = "2026-10-30"
JUBILEE_DOCS = "https://jubilee3d.github.io/machines/jubilee_2/"
OT2_DOCS = "https://docs.opentrons.com/ot-2/"


def _source(sid: str, title: str, url: str, scope: str, revision: str | None = None) -> dict:
    return {
        "id": sid,
        "title": title,
        "url": url,
        "checked_on": CHECKED_ON,
        "scope": scope,
        "revision": revision,
    }


def _reference(rid: str) -> dict:
    ref = resolve_reference(rid)
    return {
        "id": ref["id"],
        "title": ref["title"],
        "url": ref["url"],
        "checked_on": ref["checked_on"],
        "scope": ref["limits"],
        "revision": ref.get("revision"),
        "publisher": ref.get("publisher"),
        "license": ref.get("license"),
        "license_url": ref.get("license_url"),
    }


def _safe_url(url: object) -> str:
    value = str(url or "")
    if any(ord(char) < 32 for char in value):
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    return (
        quote(value, safe=":/?#[]@!$&'()*+,;=%")
        if parsed.scheme in ("https", "http") and parsed.netloc
        else ""
    )


def _procurement(project: dict, procurement: dict | None) -> dict | None:
    report = procurement if procurement is not None else project.get("procurement_report")
    if report is None:
        return None
    if (
        report.get("project_id") != project.get("id")
        or report.get("project_revision") != project.get("revision")
        or not report.get("report_id")
    ):
        raise ValueError("Procurement report does not match this project revision.")
    return deepcopy(report)


def _parts(project: dict) -> list[dict]:
    bindings = {b["component_id"]: b for b in project_source_basis(project).get("bindings", [])}
    groups = (project.get("sourcing") or {}).get("groups", [])
    parts = []
    for part in (project.get("design") or {}).get("components", []):
        if not isinstance(part, dict) or not part.get("id"):
            continue
        variants = []
        for group in groups:
            if part["id"] not in group.get("component_ids", []):
                continue
            selected = next(
                (o for o in group.get("options", []) if o.get("id") == group.get("selected_id")),
                None,
            )
            if selected:
                variants.append(
                    {
                        "group_id": group["id"],
                        "variant_id": selected["id"],
                        "label": selected.get("label", selected["id"]),
                        "quantity": group.get("quantity", 1),
                        "quantity_scope": "Procurement group quantity, not repeated per proxy part",
                        "source_url": _safe_url(selected.get("source_url")),
                    }
                )
        binding = bindings.get(part["id"], {})
        parts.append(
            {
                "component_id": part["id"],
                "label": part.get("label", part["id"]),
                "quantity": 1,
                "quantity_scope": "One canonical geometry instance",
                "position_mm": deepcopy(part.get("position")),
                "size_mm": deepcopy(part.get("size")),
                "slot_id": part.get("slot_id"),
                "selected_variants": variants,
                "geometry_basis": binding.get("basis", "custom_concept"),
                "reference_id": binding.get("reference_id"),
            }
        )
    return parts


def _vector_text(value) -> str:
    if not isinstance(value, (list, tuple)):
        return str(value)

    def number(item):
        rounded = round(float(item), 1)
        return f"{0 if rounded == 0 else rounded:.1f}".rstrip("0").rstrip(".")

    return "[" + ", ".join(number(item) for item in value) + "]"


def build_instruction_guide(project: dict, procurement: dict | None = None) -> dict:
    """Build a deterministic preview from canonical accepted/draft geometry and selections."""
    design = project.get("design") or {}
    parts = _parts(project)
    index = {p["component_id"]: p for p in parts}
    route = (
        "opentrons-ot2"
        if design.get("platform")
        else "jubilee"
        if design.get("foundation")
        else "legacy-concept"
    )
    report = _procurement(project, procurement)
    steps = []

    def add(
        sid,
        title,
        ids,
        actions,
        checks,
        *,
        status="needs_design",
        prerequisites=(),
        sources=(),
        tasks=(),
        tools=(),
        materials=(),
    ):
        ids = [cid for cid in ids if cid in index]
        placements = []
        for cid in ids:
            p = index[cid]
            placement = (
                f"{cid}: center {_vector_text(p['position_mm'])} mm; "
                f"envelope {_vector_text(p['size_mm'])} mm"
            )
            if p["slot_id"] is not None:
                placement += f"; assigned software deck slot {p['slot_id']}"
            placements.append(placement + ".")
        steps.append(
            {
                "id": sid,
                "title": title,
                "status": status,
                "requires_design": status == "needs_design",
                "component_ids": ids,
                "parts": [deepcopy(index[cid]) for cid in ids],
                "instructions": list(actions) + placements,
                "checks": list(checks),
                "prerequisites": list(prerequisites),
                "sources": list(sources),
                "engineering_tasks": [
                    {"id": f"{sid}-{i}", "action": action, "acceptance_criteria": criteria}
                    for i, (action, criteria) in enumerate(tasks, 1)
                ],
                "required_tools": list(tools),
                "required_materials": list(materials),
            }
        )

    add(
        "design-review",
        "Review this revision and selected configuration",
        [],
        [
            f"Use project {project.get('id', 'unknown')} revision {project.get('revision', 0)}; "
            "compare part IDs, selected variants and quantities below with the project model.",
            "Review the proposed layout before buying or fabricating. Geometry instances and "
            "procurement group quantities are different counts; an "
            "imported platform is one assembly.",
            (
                f"US procurement report {report['report_id']} is attached to this revision. "
                "Catalogue offers do not silently replace selected geometry or prove compatibility."
                if report
                else "No current US procurement report is attached; historical sourcing "
                "prices are not a current complete machine quotation."
            ),
        ],
        [
            "Project ID and revision match the model and downloaded files.",
            "Ready labels mean document review readiness, never completed assembly.",
        ],
        status="ready",
    )

    if not parts:
        add(
            "define-design",
            "Choose a platform and accept a layout",
            [],
            [
                "Describe the process, equipment and workspace in chat, choose a sourced platform, "
                "then request and review a layout."
            ],
            ["A canonical design with component IDs exists."],
            prerequisites=["design-review"],
            tasks=[
                (
                    "Accept a supported platform layout in chat.",
                    "A saved revision contains the accepted geometry.",
                )
            ],
        )
    elif route == "jubilee":
        upstream = _reference("jubilee-hardware")
        assembly = _source(
            "jubilee2-assembly",
            "Jubilee 2 hardware assembly index",
            JUBILEE_DOCS + "hardware_assembly.html",
            "Live documentation navigation and linked booklets; not pinned to the CAD revision. "
            "Electronics and tools sections remain TODO.",
        )
        bom = _source(
            "jubilee2-bom",
            "Jubilee 2 upstream BOM navigation",
            JUBILEE_DOCS + "bom.html",
            "Links the upstream sheet; not a complete price or compatibility verification.",
        )
        add(
            "source-parts",
            "Inventory the original Jubilee platform",
            ["foundation-jubilee"],
            [
                "Keep the source platform at the pinned revision and retain "
                "its CC-BY-4.0 attribution.",
                "Open the upstream BOM and assembly booklets. Separate purchased, fabricated and "
                "already-owned upstream parts before ordering; confirm the "
                "booklet revision matches the parts.",
            ],
            [
                "Pinned source and upstream inventory are recorded; no "
                "custom insert included as upstream hardware."
            ],
            status="reference_only",
            prerequisites=["design-review"],
            sources=[upstream, assembly, bom],
        )
        outer = _source(
            "jubilee2-outer-frame",
            "Jubilee 2 outer frame booklet",
            JUBILEE_DOCS + "instructions/outer_frame.html",
            "Official page links the illustrated frame PDF; check revision before building.",
        )
        corexy = _source(
            "jubilee2-corexy",
            "Jubilee 2 CoreXY booklet",
            JUBILEE_DOCS + "instructions/corexy_frame.html",
            "Official page links the illustrated CoreXY PDF; not a custom pipette adapter.",
        )
        add(
            "upstream-frame",
            "Follow the upstream mechanical build sequence",
            ["foundation-jubilee"],
            [
                "Use the upstream frame booklets for original subassemblies: outer frame, aluminum "
                "motor plates, pulley corners, crossbar, toolchanger "
                "lock/carriage, lower frame, CoreXY and Z axis.",
                "Follow the original instructions and their inventory for each subassembly; do not "
                "derive screws, tolerances or tightening values from the "
                "simplified envelope diagram.",
            ],
            [
                "Original frame and bed subassemblies are identified against "
                "the matching upstream booklets."
            ],
            status="reference_only",
            prerequisites=["source-parts"],
            sources=[assembly, outer, corexy, upstream],
        )
        foundation = design["foundation"]
        add(
            "frame",
            "Review the proposed bed pose and custom insert",
            ["foundation-jubilee", "base"],
            [
                f"Proposed bed drop: {foundation.get('bed_drop_mm')} mm from the pinned STEP pose; "
                f"deck origin: {_vector_text(foundation.get('deck_origin_app_mm'))} mm "
                "in application coordinates.",
                "Retain the unscaled source frame. Use the insert's "
                "canonical dimensions and position "
                "below to prepare an interface drawing, not a drill pattern "
                "inferred from the preview.",
            ],
            ["Insert drawing references the source bed and leaves source geometry unchanged."],
            prerequisites=["upstream-frame"],
            sources=[upstream],
            tasks=[
                (
                    "Specify insert material, attachment datums, fasteners and removable access.",
                    "A reviewed drawing/BOM defines the bed-to-insert joint and "
                    "fabrication tolerances.",
                ),
                (
                    "Check the proposed bed pose over required travel with tooling and cables.",
                    "Record physical clearance and attachment checks before moving hardware.",
                ),
            ],
        )
    elif route == "opentrons-ot2":
        manufacturer = _reference("opentrons-ot2")
        unbox = _source(
            "ot2-unboxing",
            "OT-2 unboxing and supplied toolkit",
            OT2_DOCS + "installation/unboxing/",
            "Manufacturer installation sequence and box contents; verify "
            "actual delivered configuration.",
        )
        add(
            "ot2-configuration",
            "Specify the assembled robot and compatible instruments",
            [cid for cid in index if cid.startswith("ot2-envelope-")] + ["pipette"],
            [
                "Use the schematic envelope to plan space; order an "
                "assembled robot through an official "
                "configuration and US quotation. Frame proxies are not "
                "individual fabricated parts.",
                "Specify the actual instrument pipette model, channels, tips "
                "and labware definitions "
                "against the preparation transfers. A manual pipette is not assumed compatible.",
            ],
            [
                "Robot, pipettes, tips, labware and installation space are "
                "confirmed for the actual order."
            ],
            prerequisites=["design-review"],
            sources=[manufacturer],
            tasks=[
                (
                    "Resolve exact robot/pipette/tip/labware configuration with the supplier.",
                    "Record actual SKUs, quantities, compatibility and a dated US quotation.",
                )
            ],
        )
        add(
            "ot2-unboxing",
            "Follow manufacturer unboxing and installation",
            [cid for cid in index if cid.startswith("ot2-envelope-")] + ["base", "tip-waste"],
            [
                "Open the official illustrated unboxing sequence for the "
                "supplied robot; have another "
                "person assist with lifting and place it on a stable bench.",
                "Use the manufacturer sequence to remove shipping restraints "
                "and install the supplied "
                "covers. Complete its post-assembly checklist before power is connected.",
            ],
            [
                "Shipping brackets removed and manufacturer post-assembly "
                "checks completed before power-up."
            ],
            status="reference_only",
            prerequisites=["ot2-configuration"],
            sources=[unbox],
            tools=[
                {
                    "label": "3 mm hex driver for shipping brackets (verify supplied toolkit)",
                    "source_id": "ot2-unboxing",
                },
                {
                    "label": "2.5 mm hex driver for the top window (verify supplied toolkit)",
                    "source_id": "ot2-unboxing",
                },
            ],
        )
        first = _source(
            "ot2-first-run",
            "OT-2 first run",
            OT2_DOCS + "installation/first-run/",
            "Official app, power supply and connection instructions; "
            "MuseAutoLab does not control the robot.",
        )
        add(
            "ot2-first-run",
            "Connect through the official OT-2 App",
            ["base"],
            [
                "Follow the official First Run page to install the app, "
                "connect the supplied external "
                "power supply/network equipment and identify the robot. "
                "Follow the page's power-on order.",
            ],
            ["The correct robot is identified in the official app and initial setup is recorded."],
            status="reference_only",
            prerequisites=["ot2-unboxing"],
            sources=[first],
        )
        instruments = _source(
            "ot2-instruments",
            "OT-2 pipette installation",
            OT2_DOCS + "installation/instruments/",
            "Official app-assisted attachment and calibration of supported instruments.",
        )
        calibration = _source(
            "ot2-calibration",
            "OT-2 robot calibration",
            OT2_DOCS + "calibration/robot-calibration/",
            "Official deck, tip-length and pipette-offset calibration guidance.",
        )
        add(
            "ot2-calibration",
            "Install and calibrate the actual pipettes",
            ["carriage", "pipette"],
            [
                "Clear the deck and use the official app's Attach pipette "
                "workflow for the selected "
                "mount. Follow its illustrated connection and fastening instructions.",
                "Complete the required deck, tip-length and pipette-offset "
                "calibration for the actual "
                "pipette/tip combination; retain the app results before protocol verification.",
            ],
            ["Official app calibration results belong to the installed pipettes and tips."],
            status="reference_only",
            prerequisites=["ot2-first-run"],
            sources=[instruments, calibration],
        )
    else:
        add(
            "frame",
            "Resolve the legacy custom frame design",
            ["base", "column-left", "column-right", "crossbar"],
            [
                "Use the shown dimensions for concept review. This saved "
                "legacy custom frame has no "
                "verified platform assembly guide; choose a sourced platform "
                "in chat for a new design.",
            ],
            ["The chosen frame architecture and load path have reviewed drawings."],
            prerequisites=["design-review"],
            tasks=[
                (
                    "Specify structure, joints and fabrication drawings.",
                    "A reviewed frame BOM and drawing set defines every physical joint.",
                )
            ],
        )

    if parts and route != "opentrons-ot2":
        add(
            "motion-pipette",
            "Resolve the pipette mount and actuation",
            ["carriage", "pipette"],
            [
                "Use the selected pipette/adapter envelopes and exact positions below. Compare the "
                "actual pipette with the documented Science Jubilee tools; "
                "reference availability does "
                "not make this custom mount compatible.",
            ],
            [
                "Pipette retention, plunger/tip actuation and full travel "
                "are checked against actual parts."
            ],
            prerequisites=["frame"],
            sources=[_reference("science-jubilee")],
            tasks=[
                (
                    "Measure the actual pipette and design its retention, "
                    "actuation and tool interface.",
                    "Review dimensioned adapter drawings, actuator selection and "
                    "collision/force checks.",
                )
            ],
        )

    if parts:
        plate = project.get("labware_plate")
        plate_component = plate.get("target_component_id") if plate else None
        has_microplate = bool(plate and plate_component in index and route == "jubilee")
        if has_microplate:
            profile, derived, compatibility = (
                plate["profile"],
                plate["derived"],
                plate["compatibility"],
            )
            facts = profile["source"]
            plate_source = _source(
                "microplate-profile",
                profile["display_name"],
                facts["source_url"],
                profile["scope"],
                facts["revision"],
            )
            plate_source.update(
                {key: facts[key] for key in ("checked_on", "license", "license_url")}
            )
            plate_source["publisher"] = "Opentrons"
            labels = ", ".join(compatibility["occupied_wells"]) or "none assigned"
            requested = compatibility["requested_volume_ul"]
            add(
                "plate-profile",
                "Review the selected 96-well profile and orientation",
                [plate_component],
                [
                    f"Selected profile: {profile['display_name']} ({plate['profile_id']}). "
                    "This is a pinned official Opentrons software definition, not manufacturer CAD "
                    "or proof that a specific purchased plate fits the holder.",
                    f"The definition provides {derived['well_count']} wells in 8 rows and 12 "
                    f"columns, with {derived['well_capacity_ul']:g} µL maximum definition capacity "
                    "per well. Working volume, headspace and mixing must be checked separately.",
                    f"Current preparation targets use {len(compatibility['occupied_wells'])} "
                    f"wells: {labels}. The switch does not add targets or scale recipe volumes.",
                    "Locate A1 on the actual plate and compare its mark with the amber model "
                    "marker. In model coordinates A1 is at positive Z, columns increase along X, "
                    "and rows A–H run toward negative Z. The definition orders A1, B1 through H1 "
                    "before A2; retain the displayed well assignments.",
                    "Colored well markers show assigned targets only, not a liquid level or "
                    "evidence that liquid was dispensed. The source fixture remains separate.",
                ],
                ["The plate identity and A1 orientation match the selected software profile."],
                status="ready",
                prerequisites=["design-review"],
                sources=[plate_source],
            )
            add(
                "plate-volume",
                "Check per-well volume before confirming the recipe",
                [plate_component],
                [
                    (
                        f"The current recipe requests {requested:g} µL per target. "
                        if requested is not None
                        else "The current recipe has no complete per-target volume. "
                    )
                    + f"Selected definition capacity: {derived['well_capacity_ul']:g} µL per well.",
                    *(
                        compatibility["blocking_issues"]
                        or [
                            "The requested volume is within the definition limit. This arithmetic "
                            "check does not validate practical working volume or pipette access."
                        ]
                    ),
                    "If the requested volume is too large, revise final volume explicitly in "
                    "chat or return to the previous tube rack. Do not split or dilute the "
                    "recipe automatically; retain stock and target concentrations unless changed.",
                ],
                ["Volume per target is explicit, below the limit and reviewed for headspace."],
                status="ready" if compatibility["status"] == "ready" else "needs_design",
                prerequisites=["plate-profile"],
                sources=[plate_source],
                tasks=[]
                if compatibility["status"] == "ready"
                else [
                    (
                        "Resolve the plate-volume conflict in the design chat before confirmation.",
                        "A revision records an explicit compatible volume or different labware "
                        "selection; the recipe has not been silently scaled.",
                    )
                ],
            )
            add(
                "plate-holder",
                "Print and dry fit the custom plate holder",
                [plate_component],
                [
                    "After resolving recipe conflicts, confirm the revision and generate project "
                    "files. cad/plate-holder.step and cad/plate-holder.stl describe the custom "
                    "holder only. cad/plate-reference.step is schematic source-reference geometry; "
                    "do not print it as a laboratory plate.",
                    f"Proposed holder pocket: {_vector_text(derived['holder_pocket_mm'])} mm, "
                    f"with a {derived['holder_floor_mm']:g} mm floor, "
                    f"{derived['holder_wall_mm']:g} mm walls, {derived['holder_lip_mm']:g} mm lip. "
                    "Review the actual plate base, skirt and protrusions against this shallow "
                    "pocket before fabrication.",
                    "Print the holder with its broad bottom face on the print bed and pocket "
                    "facing upward. FDM clearances and material are proposals, not measured "
                    "printer results. Inspect the slicer preview; do not scale the plate.",
                    "Measure the printed pocket, then dry fit the empty plate. It must seat "
                    "flat, remain removable without forcing, expose A1 and the grid, and leave "
                    "lid, gripper and pipette access clear. Record plate identity, material, "
                    "printer settings, dimensions and fit observations before accepting it.",
                    "The purchased plate, holder material, print process, attachment and fit are "
                    "unpriced or unverified unless separately recorded. No successful print or "
                    "physical fit is recorded by this digital guide.",
                ],
                ["A first-article record shows pocket dimensions and actual plate seating."],
                prerequisites=["plate-volume", "frame"],
                sources=[plate_source],
                tasks=[
                    (
                        "Record the actual plate and printed-holder fit before installation.",
                        "Verify base/skirt compatibility, flat seating, removal and tool access "
                        "on the actual manufactured parts.",
                    )
                ],
            )
            add(
                "plate-placement",
                "Locate the plate and commission its well coordinates",
                [plate_component],
                [
                    "Use the canonical sample position below while preserving the source Jubilee "
                    "frame and other fixtures. Define deck locating and retention for the holder; "
                    "the software position is not a calibrated instrument coordinate.",
                    "Verify A1 orientation and every assigned well using the actual pipette, tips, "
                    "plate and holder. Check approach, depth, lid and travel clearances before "
                    "powered operation. Plate operation, calibration and hardware control are "
                    "not implemented by this adapter.",
                ],
                ["Reviewed holder retention and recorded well/tool-clearance checks exist."],
                prerequisites=["plate-holder"],
                sources=[plate_source],
                tasks=[
                    (
                        "Resolve holder retention and calibrate well positions before operation.",
                        "Retain mounting details, A1 orientation, measured pipette approach and "
                        "depth records for all assigned wells.",
                    )
                ],
            )
        rack = project.get("labware_rack")
        rack_component = rack.get("target_component_id") if rack else None
        has_parametric_rack = bool(rack and rack_component in index and route == "jubilee")
        if has_parametric_rack:
            spec, derived, measured_checks = rack["spec"], rack["derived"], rack["metrics"]
            bore = derived["bore_diameter_mm"]
            pitch = derived["pitch_mm"]
            radial = spec.get("radial_clearance_mm", 0.4)
            add(
                "rack-inputs",
                "Review the tube envelope and custom rack geometry",
                [rack_component],
                [
                    "Use the actual tube intended for this dry fit. A 1.5–2 mL label is not a "
                    "dimensional specification and no supplier SKU is inferred.",
                    f"Declared maximum body diameter: {spec['body_diameter_max_mm']:g} mm; "
                    f"minimum support rim diameter: {spec['rim_diameter_min_mm']:g} mm; "
                    f"maximum closed cap envelope: {spec['cap_diameter_max_mm']:g} mm; "
                    f"underside-of-rim to tip height: {spec['below_rim_height_mm']:g} mm.",
                    "Check body diameter over every section that passes through the hole; "
                    "measure the minimum underside bearing rim, and the maximum closed cap "
                    "including rim and closed hinge protrusions. Open-cap motion is not modeled.",
                    f"The rack has {derived['count']} positions in {derived['rows']} rows and "
                    f"{derived['columns']} columns; envelope {_vector_text(rack['size_mm'])} mm "
                    f"(width, height, depth), CAD bore {bore:g} mm and pitch {pitch:g} mm.",
                    "The rack is one custom printed bridge with a perforated top and two end "
                    "legs, no floor and no fasteners. The original Jubilee source geometry "
                    "and separate source rack are unchanged.",
                    f"The bore includes {radial:g} mm radial clearance plus a 0.3 mm diameter "
                    "allowance for an assumed FDM bore deviation of ±0.3 mm. These process "
                    "assumptions have not been measured on your printer.",
                ],
                [
                    "The declared measurements match the intended tube and recorded input sources.",
                    f"Calculated worst-case rim land is "
                    f"{measured_checks['rim_land_min_assumed_mm']:g} mm, at least 0.4 mm; "
                    "this is a geometric calculation, not a physical fit result.",
                ],
                status="ready",
                prerequisites=["design-review"],
            )
            add(
                "rack-print",
                "Prepare the fit coupon and print the one-piece rack",
                [rack_component],
                [
                    "Confirm this revision and generate its project files. Use the rack-only "
                    "cad/tube-rack.step or cad/tube-rack.stl; they retain the upright "
                    "engineering orientation.",
                    "In the slicer rotate the rack so the broad top plate lies flat on the print "
                    "bed, with both end legs pointing upward. Do not scale the part "
                    "to correct fit.",
                    f"Before a full rack, print cad/tube-rack-fit-coupon.stl with the same "
                    f"{bore:g} mm bore and {derived['top_thickness_mm']:g} mm plate thickness, "
                    "using the intended printer and settings. The supplied coupon is flat; "
                    "place its broad face on the print bed. The STEP counterpart is "
                    "cad/tube-rack-fit-coupon.step.",
                    "PETG is a proposed material for a dry fit prototype only. Choose printer "
                    "settings and material suitability separately; no sterilization, chemical "
                    "resistance or laboratory temperature performance is established.",
                    "Inspect the slicer preview for continuous walls and an unobstructed bore. "
                    "After the coupon is accepted, print one complete rack, cool it before "
                    "removal and remove loose strings without enlarging its support holes.",
                ],
                [
                    "The slicer uses the correct revision, millimetres and "
                    "top-plate-down orientation.",
                    "One rack is required; material, printing and rework costs remain unpriced.",
                ],
                status="ready",
                prerequisites=["rack-inputs"],
            )
            add(
                "rack-fit",
                "Measure the first article and dry fit the actual tubes",
                [rack_component],
                [
                    "Record printer, material, settings, part revision and actual tube identity. "
                    "Use a suitable dimensional gauge or caliper; record bore and body variation "
                    "instead of relying on the rendered model.",
                    f"Measure bores in perpendicular directions through the support zone. The "
                    f"proposed bore band is {bore - 0.3:g}–{bore + 0.3:g} mm. For the largest "
                    f"tube body, actual minimum radial clearance must be at least {radial:g} mm; "
                    "use (smallest measured bore − largest body diameter) / 2.",
                    "Use (smallest measured rim − largest measured bore) / 2 to verify at least "
                    "0.4 mm radial bearing land. The rim must seat evenly and retain the tube "
                    "without the body being forced through or the rim falling through.",
                    f"Dry fit one empty, closed tube first; then all {derived['count']} positions. "
                    f"The nominal tube-tip clearance above the bench is "
                    f"{derived['tip_clearance_mm']:g} mm. Verify every tip stays clear, the rack "
                    "stands flat, closed caps do not interfere, and tubes can be removed by hand.",
                    "Reject or revise through chat if the coupon or first article misses the "
                    "criteria. No successful print, fit or laboratory operation is recorded by "
                    "generating this guide.",
                ],
                [
                    "First-article records show bore band, minimum radial clearance "
                    "and rim land met.",
                    "All positions retain the intended empty tubes and leave tips "
                    "clear of the bench.",
                    "Open hinge motion, loaded-rack strength and liquid handling remain unchecked.",
                ],
                prerequisites=["rack-print"],
                tasks=[
                    (
                        "Record coupon and first-article measurements before accepting "
                        "the printed rack.",
                        "Retain tube identity, dimensions, bore/rim clearance measurements and "
                        "an all-position dry-fit record; any failure triggers a revised rack.",
                    )
                ],
            )
            add(
                "rack-placement",
                "Place the accepted rack and resolve its deck retention",
                [rack_component],
                [
                    "After the physical dry fit, place the rack at the canonical sample-rack "
                    "position below. The one-piece rack has no integrated deck fasteners.",
                    "Define how the rack is located and retained on the custom insert, without "
                    "altering the imported Jubilee frame. Check access and travel using the "
                    "actual tool, loaded tubes and cables before powered operation.",
                    "Tube centers and rack geometry are a placement proposal. The current system "
                    "does not calibrate pipette approach, tip reach or liquid-handling accuracy.",
                ],
                [
                    "A reviewed locating/retention method and measured tool clearances exist.",
                    "Rack fabrication fit is tracked separately from machine commissioning.",
                ],
                prerequisites=["rack-fit", "frame"],
                tasks=[
                    (
                        "Design and verify the insert-to-rack locating and retention interface.",
                        "Record actual deck datum, retention details, tool access "
                        "and clearance checks "
                        "before moving the machine with the rack installed.",
                    )
                ],
            )
        tip_rack = project.get("tip_rack")
        if tip_rack:
            profile = tip_rack.get("profile")
            if profile:
                facts = profile["source"]
                add(
                    "selected-tip-rack", "Verify and place the selected commercial tip rack",
                    ["tip-rack"],
                    [f"Selected product reference: {profile['display_name']}. Keep this profile "
                     "identity when checking the supplier's exact package/SKU; a seller change "
                     "for the same product does not change geometry.",
                     "Compare the actual rack to the stated envelope and 96-position software "
                     "pattern. The schematic recesses do not describe molded internal geometry.",
                     "Place at the canonical tip-rack center below. Design its locating and "
                     "retention interface on the custom Jubilee insert. Dry-check pipette pickup "
                     "access and clearance with purchased tips before powered operation."],
                    ["Actual product identity, package quantity and dimensions recorded.",
                     "Attachment and pipette compatibility checked against real parts."],
                    prerequisites=["frame"],
                    sources=[_source("selected-tip-rack-profile", profile["display_name"],
                                     facts["source_url"], facts["scope"], facts["revision"])],
                    tasks=[(
                        "Confirm the exact purchased tip/rack and engineer deck retention.",
                        "Retain product identity, measured envelope and pickup/clearance records."
                    )],
                )
            else:
                spec, derived = tip_rack["spec"], tip_rack["derived"]
                add(
                    "tip-rack-coupon", "Print and measure a tip-holder fit coupon first",
                    ["tip-rack"],
                    ["This part is a holder for purchased disposable tips. Never print disposable "
                     "tips from these files. Printer access was declared by the user; printer "
                     "model, build envelope, material, settings and cleaning need review.",
                     "Use tip-rack-fit-coupon.stl from this revision's CAD package before the full "
                     "holder. Print the top face on the bed and inspect the slicer preview.",
                     f"Declared body maximum {spec['body_diameter_max_mm']:g} mm; supporting rim "
                     f"minimum {spec['rim_diameter_min_mm']:g} mm and maximum "
                     f"{spec['rim_diameter_max_mm']:g} mm; below-rim height "
                     f"{spec['below_rim_height_mm']:g} mm. Nominal volume was not used for fit.",
                     f"Assumed bore {derived['bore_diameter_mm']:g} mm, pitch "
                     f"{derived['pitch_mm']:g} mm. Verify coupon retention, clearance and bearing "
                     "with the actual tip. Revise dimensions if it binds, falls through or rocks."],
                    ["Coupon dimensions and tip fit recorded before printing the full holder.",
                     "Printer/material/settings and cleaning requirements reviewed."],
                    prerequisites=["design-review"],
                    tasks=[("Check the coupon and record actual fit on the intended printer.",
                            "A measured coupon, tip identity and fit record exist.")],
                )
                add(
                    "printed-tip-rack", "Fabricate and dry-check the full tip holder", ["tip-rack"],
                    ["After coupon acceptance, print tip-rack.stl with the same validated setup. "
                     "Inspect all holes/supports; dry-fit bought tips in all positions.",
                     "Use the canonical tip-rack placement below. Design locating/retention on "
                     "the Jubilee insert; check actual pipette pickup, strength and clearances. "
                     "This design does not verify sterility, fit or laboratory suitability."],
                    ["All-position retention, deck attachment and tool access physically checked."],
                    prerequisites=["tip-rack-coupon", "frame"],
                    tasks=[(
                        "Verify the printed holder/deck interface with actual tips and pipette.",
                        "Retain all-position dry-fit, attachment and pickup/clearance checks."
                    )],
                )
        rack_ids = [
            cid
            for cid in ("source-rack", "sample-rack", "tip-rack", "tip-waste")
            if cid in index
            and (not has_parametric_rack or cid != rack_component)
            and (not has_microplate or cid != plate_component)
            and (not tip_rack or cid != "tip-rack")
        ]
        rack_prerequisite = "ot2-calibration" if route == "opentrons-ot2" else "frame"
        add(
            "racks",
            "Match the remaining labware to the layout"
            if has_parametric_rack or has_microplate
            else "Match the layout to actual labware",
            rack_ids,
            [
                "Compare the numbered layout and positions below with actual rack, tube, tip and "
                "waste dimensions. Keep each component ID attached to its source/destination role.",
                "On OT-2 use the assigned software slots with supported labware definitions; on a "
                "custom insert specify locating features and removable access before fabrication.",
                *(
                    [
                        "The custom sample rack has its own input, print, first-article "
                        "and placement steps above; this step covers the remaining source, "
                        "tip and waste fixtures."
                    ]
                    if has_parametric_rack
                    else []
                ),
                *(
                    [
                        "The selected microplate and custom holder have their own profile, volume, "
                        "print/fit and placement steps above; this covers other source fixtures."
                    ]
                    if has_microplate
                    else []
                ),
            ],
            ["Actual labware, capacity, access and locating method match the accepted placements."],
            prerequisites=[rack_prerequisite],
            sources=[_reference("opentrons-ot2")] if route == "opentrons-ot2" else [],
            tasks=[
                (
                    "Record exact labware/tip definitions and verify fit at "
                    "every assigned position.",
                    "Approved labware IDs and a recorded fit/position check "
                    "replace the proxy assumptions.",
                )
            ],
        )
        if route != "opentrons-ot2" and "controller" in index:
            add(
                "controller",
                "Specify the custom control and power interfaces",
                ["controller"],
                [
                    "The shown enclosure is a placement proposal. Select the actual controller, "
                    "actuators, supply and protection before preparing a schematic.",
                    "Use the upstream controller-specific wiring/configuration "
                    "for the original platform. "
                    "Do not treat legacy motor/driver selections as a "
                    "replacement Jubilee controller BOM.",
                ],
                ["A reviewed schematic and I/O/interface list exist for the actual hardware."],
                prerequisites=["motion-pipette"],
                sources=[_reference("jubilee-hardware")] if route == "jubilee" else [],
                tasks=[
                    (
                        "Define controller/driver interfaces, power sizing, wiring "
                        "and stop behavior.",
                        "Reviewed schematics identify actual parts, connectors, "
                        "protection and firmware boundaries.",
                    )
                ],
            )
        cooling = design.get("cooling") or {}
        if cooling.get("enabled") and "cold-storage" in index:
            variant = cooling.get("variant_id") or (project.get("selections") or {}).get(
                "cooling", "unresolved"
            )
            refs = [_reference("opentrons-temp-module-gen2")] if variant == "opentrons-gen2" else []
            add(
                "cold-bay",
                "Resolve the selected cooling module interface",
                ["cold-storage"],
                [
                    f"Selected cooling variant: {variant}; "
                    f"requested target: {cooling.get('target_c')} C. "
                    "Use the recorded envelope and manual transfer workflow; the "
                    "target is not a measured sample temperature.",
                ],
                ["Module, sample holder and manual access fit the proposed layout."],
                prerequisites=["racks"],
                sources=refs,
                tasks=[
                    (
                        "Specify thermal block/sample holder, mounting, supply and "
                        "condensation management.",
                        "Record reviewed interfaces and a sample-temperature "
                        "verification plan for the selected configuration.",
                    )
                ],
            )
        extension = project.get("inspection_extension")
        if extension and route != "opentrons-ot2":
            add(
                "inspection-extension",
                "Resolve the accepted inspection sidecar",
                extension.get("component_ids", []),
                [
                    "Keep the accepted sidecar, mast, two links and camera at "
                    "the canonical placements. "
                    "Use inspection-module.json for the digital poses and dimensions.",
                    "Kinematic reach screening does not verify load, collision "
                    "clearance, cable routing or image coverage.",
                ],
                [
                    "The arm does not change the accepted base platform; "
                    "measured image calibration is separate."
                ],
                prerequisites=["frame", "racks"],
                sources=[_reference("rpi-camera-module-3")],
                tasks=[
                    (
                        "Design the sidecar attachment, joint hardware, actuators "
                        "and camera/host cable route.",
                        "Reviewed load/interface drawings and actual "
                        "clearance/image-coverage checks exist.",
                    )
                ],
            )

    add(
        "checks",
        "Complete the handover checks before physical operation",
        [],
        [
            "Review every engineering task and retain the upstream "
            "build/setup records for the actual configuration.",
            "Review preparation.csv and automation/preview.py as a "
            "logical liquid-transfer trace only. "
            "MuseAutoLab has no control/physics adapter for the selected Jubilee or OT-2 route.",
            "Physical operation needs an approved hardware integration "
            "and process verification record.",
        ],
        [
            "All custom engineering tasks have named deliverables and verification records.",
            "Actual liquid handling has been checked before using valuable samples.",
        ],
        prerequisites=[step["id"] for step in steps if step["id"] != "design-review"],
        tasks=[
            (
                "Prepare a hardware commissioning and liquid-transfer verification procedure.",
                "Record actual calibration, dry-run/clearance and dispensing "
                "checks before release.",
            )
        ],
    )
    sources = {source["id"]: source for step in steps for source in step["sources"]}
    counts = {
        status: sum(step["status"] == status for step in steps)
        for status in ("ready", "reference_only", "needs_design")
    }
    return {
        "schema_version": 1,
        "project_id": project.get("id", "unknown"),
        "project_revision": project.get("revision", 0),
        "revision": project.get("revision", 0),
        "platform": route,
        "status": "needs_design" if counts["needs_design"] else "review_ready",
        "coordinate_system": "mm; X right, Y up, Z depth; canonical component centers",
        "labware_brief": deepcopy(project.get("labware_brief")),
        "labware_rack": deepcopy(project.get("labware_rack")),
        "labware_plate": deepcopy(project.get("labware_plate")),
        "tip_rack": deepcopy(project.get("tip_rack")),
        "fabrication_capabilities": deepcopy(project.get("fabrication_capabilities")),
        "preparation": deepcopy(project.get("plan")) if project.get("labware_plate") else None,
        "readiness_scope": "Review-ready document; not an assembly completion or "
        "physical validation record",
        "procurement_report_id": report["report_id"] if report else None,
        "procurement": report,
        "parts": parts,
        "steps": steps,
        "sources": list(sources.values()),
        "bed_pose": deepcopy(design.get("foundation")),
        "summary": {
            "ready_steps": counts["ready"],
            "reference_steps": counts["reference_only"],
            "needs_design_steps": counts["needs_design"],
            "total_steps": len(steps),
        },
    }


def step_details_html(step: dict) -> str:
    """Render escaped extra fields shared by immediate and packaged guides."""

    def esc(value):
        return html.escape(str(value), quote=True)

    def attribution(source):
        if source.get("publisher"):
            return " — " + esc(source["publisher"]) + "; " + esc(source.get("license", ""))
        return ""

    sections = []
    if step.get("parts"):
        rows = []
        for part in step["parts"]:
            variants = []
            for variant in part["selected_variants"]:
                label = esc(
                    f"{variant['group_id']}: {variant['variant_id']} ({variant['label']}); "
                    f"group quantity {variant['quantity']}"
                )
                url = _safe_url(variant.get("source_url"))
                variants.append(f'<a href="{esc(url)}">{label}</a>' if url else label)
            selected = "; ".join(variants) or "No specific catalogue variant selected"
            rows.append(
                f"<li><strong>{esc(part['component_id'])}</strong>: "
                f"1 geometry instance; {selected}</li>"
            )
        sections.append("<h4>Parts and selected variants</h4><ul>" + "".join(rows) + "</ul>")
    if step.get("prerequisites"):
        sections.append(
            "<h4>Prerequisites</h4><p>" + esc(", ".join(step["prerequisites"])) + "</p>"
        )
    if step.get("engineering_tasks"):
        sections.append(
            "<h4>Required engineering deliverables</h4><ul>"
            + "".join(
                f"<li>{esc(task['action'])}<br><strong>Complete when:</strong> "
                f"{esc(task['acceptance_criteria'])}</li>"
                for task in step["engineering_tasks"]
            )
            + "</ul>"
        )
    for key, title in (
        ("required_tools", "Sourced tools"),
        ("required_materials", "Sourced materials"),
    ):
        if step.get(key):
            sections.append(
                f"<h4>{title}</h4><ul>"
                + "".join(
                    f"<li>{esc(item['label'])} (source: {esc(item['source_id'])})</li>"
                    for item in step[key]
                )
                + "</ul>"
            )
    if step.get("sources"):
        sections.append(
            "<h4>Primary instructions and references</h4><ul>"
            + "".join(
                f'<li><a href="{esc(_safe_url(source["url"]))}" rel="noreferrer">'
                f"{esc(source['title'])}</a>{attribution(source)}"
                f" — checked {esc(source['checked_on'])}. {esc(source['scope'])}</li>"
                for source in step["sources"]
            )
            + "</ul>"
        )
    return "".join(sections)


def procurement_html(guide: dict) -> str:
    """Display only the bound report's current prices, with gaps and dates visible."""
    report = guide.get("procurement")
    if not report:
        return (
            '<section class="card"><h2>US procurement</h2><p>No current '
            "report is attached. Refresh prices for this "
            "revision.</p></section>"
        )

    def esc(value):
        return html.escape(str(value if value is not None else "Unknown"), quote=True)

    rows = []
    for row in report.get("rows", []):
        url = _safe_url(row.get("price_source_url"))
        label = esc(row.get("label", row.get("group_id", "")))
        source = f'<a href="{esc(url)}">Supplier source</a>' if url else "No verified price source"
        bom_url = _safe_url(row.get("source_bom_url"))
        if bom_url:
            source += (
                f'<br><a href="{esc(bom_url)}">'
                f"Upstream BOM row {esc(row.get('source_bom_row'))}</a>"
            )
            source += "<br>Source revision: " + esc(row.get("source_project_revision"))
        role = (
            "Candidate offer; not adopted" if row.get("is_candidate") else "Current selected item"
        )
        facts = "".join(
            f"<div><dt>{name}</dt><dd>{esc(value)}</dd></div>"
            for name, value in (
                ("Quantity", row.get("quantity")),
                ("Unit price", row.get("unit_price")),
                ("Line total", row.get("line_total")),
                ("Status", row.get("status")),
                ("Freshness", row.get("freshness")),
                ("Availability", row.get("availability")),
            )
        )
        rows.append(
            '<article class="procurement-item">'
            f'<p class="procurement-role">{role}</p><h3>{label}</h3>'
            f'<p class="meta">Variant: {esc(row.get("selected_id"))}</p>'
            f'<dl class="procurement-facts">{facts}</dl>'
            "<h4>Compatibility / next action</h4><p>"
            + esc(row.get("compatibility_note") or row.get("issue"))
            + f'</p><p class="procurement-source">{source}</p>'
            + f'<p class="meta">Fetched: {esc(row.get("fetched_at"))}</p></article>'
        )
    return (
        '<section class="card"><h2>Bound US procurement snapshot</h2><p>Report '
        + esc(report.get("report_id"))
        + " · fetched "
        + esc(report.get("fetched_at"))
        + " · currency "
        + esc(report.get("currency"))
        + "</p><p>Known partial subtotal: "
        + esc(report.get("known_partial_subtotal"))
        + " "
        + esc(report.get("currency"))
        + ". Unpriced, unavailable and stale items do not become zero-cost hardware. "
        "Candidate catalogue offers do not change selected geometry "
        "or establish compatibility.</p><p>"
        + esc(
            report.get(
                "scope", "Selected items and explicit procurement candidates for this revision."
            )
        )
        + "</p>"
        '<div class="procurement-grid">'
        + "".join(rows)
        + "</div><p>Exclusions: "
        + esc("; ".join(str(item) for item in report.get("exclusions", [])))
        + "</p></section>"
    )


def build_guide_markdown(guide: dict) -> bytes:
    """Readable text counterpart of the exact structured preview."""

    # Escape raw HTML and Markdown link metacharacters in project-supplied text.
    def plain(value):
        return (
            html.escape(str(value), quote=False)
            .replace("\\", "\\\\")
            .replace("[", "\\[")
            .replace("]", "\\]")
            .replace("|", "\\|")
        )

    lines = [
        "# Build and setup instructions",
        "",
        f"Project {plain(guide['project_id'])} · revision {guide['project_revision']} "
        f"· {guide['platform']}",
        "",
        guide["readiness_scope"],
        "",
        guide["coordinate_system"],
        "",
    ]
    if guide.get("labware_plate") and guide.get("preparation"):
        plan = guide["preparation"]
        wells = guide["labware_plate"]["compatibility"]["occupied_wells"]
        lines.extend(
            [
                "## Well assignments and preparation volumes",
                "",
                plain(plan.get("message", "")),
                "",
                "| Well | Target | Stock (µL) | Diluent (µL) | Total (µL) |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for index, step in enumerate(plan.get("steps") or []):
            cells = [
                wells[index] if index < len(wells) else "Unassigned",
                step.get("target", ""),
                step.get("stock_volume_ul", ""),
                step.get("diluent_volume_ul", ""),
                step.get("total_volume_ul", ""),
            ]
            lines.append("| " + " | ".join(plain(value) for value in cells) + " |")
        lines.append("")
    for step in guide["steps"]:
        lines.extend(
            [
                f"## {plain(step['title'])}",
                "",
                f"Status: {step['status']}",
                "",
                "Prerequisites: " + (", ".join(step["prerequisites"]) or "None"),
                "",
            ]
        )
        lines.extend(f"- {plain(action)}" for action in step["instructions"])
        lines.extend(["", "Checks:", ""])
        lines.extend(f"- {plain(check)}" for check in step["checks"])
        for part in step["parts"]:
            lines.extend(
                ["", f"Part {plain(part['component_id'])}: {part['quantity']} geometry instance."]
            )
            for variant in part["selected_variants"]:
                line = (
                    f"- Selected {plain(variant['group_id'])}: {plain(variant['variant_id'])} "
                    f"({plain(variant['label'])}); "
                )
                line += f"procurement group quantity {variant['quantity']}."
                if _safe_url(variant.get("source_url")):
                    line += f" [Catalogue/source](<{_safe_url(variant['source_url'])}>)"
                lines.append(line)
        for task in step["engineering_tasks"]:
            lines.extend(
                [
                    "",
                    "Required deliverable: " + plain(task["action"]),
                    "Complete when: " + plain(task["acceptance_criteria"]),
                ]
            )
        for key in ("required_tools", "required_materials"):
            lines.extend(
                f"- {plain(item['label'])} (source: {plain(item['source_id'])})"
                for item in step[key]
            )
        for source in step["sources"]:
            url = _safe_url(source["url"])
            lines.extend(
                [
                    "",
                    f"Source: [{plain(source['title'])}](<{url}>) · checked {source['checked_on']}",
                    plain(source["scope"]),
                    (
                        f"Attribution: {plain(source['publisher'])}; "
                        f"{plain(source.get('license', ''))}."
                        if source.get("publisher")
                        else ""
                    ),
                ]
            )
        lines.append("")
    if guide["procurement"]:
        report = guide["procurement"]
        lines.extend(
            [
                "## Bound US procurement snapshot",
                "",
                f"Report {plain(report['report_id'])}; fetched {plain(report.get('fetched_at'))}; "
                f"currency {plain(report.get('currency'))}.",
                "",
                f"Known partial subtotal: {plain(report.get('known_partial_subtotal'))} "
                f"{plain(report.get('currency'))}. "
                "Unavailable, stale and unpriced items remain outside the current subtotal.",
                "",
                plain(
                    report.get(
                        "scope",
                        "Candidate offers do not replace selected geometry or "
                        "establish compatibility.",
                    )
                ),
                "",
                "| Group | Variant | Role | Quantity | Unit price | Line "
                "total | Status | Freshness | Source/date | Compatibility / "
                "next action |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for row in report.get("rows", []):
            source_text = (
                f"{_safe_url(row.get('price_source_url'))} / {row.get('fetched_at', 'not fetched')}"
            )
            if row.get("source_bom_url"):
                source_text += (
                    f"; upstream BOM row {row.get('source_bom_row')}: "
                    f"{_safe_url(row['source_bom_url'])}; "
                    f"source revision {row.get('source_project_revision')}"
                )
            cells = [
                row.get("label", row.get("group_id")),
                row.get("selected_id"),
                "Candidate; not adopted" if row.get("is_candidate") else "Current selected item",
                row.get("quantity"),
                row.get("unit_price"),
                row.get("line_total"),
                row.get("status"),
                row.get("freshness"),
                source_text,
                row.get("compatibility_note") or row.get("issue"),
            ]
            lines.append(
                "| "
                + " | ".join(
                    plain(cell if cell is not None else "Unknown").replace("\n", " ")
                    for cell in cells
                )
                + " |"
            )
        lines.extend(
            [
                "",
                "Exclusions: "
                + plain("; ".join(str(item) for item in report.get("exclusions", []))),
                "",
            ]
        )
    return "\n".join(lines).encode("utf-8")


def build_instruction_files(project: dict, procurement: dict | None = None) -> dict[str, bytes]:
    """Generate HTML/Markdown/JSON immediately; never generate geometry or call a provider."""
    from app.assembly import build_guide_html

    guide = build_instruction_guide(project, procurement)
    return {
        "assembly-guide.html": build_guide_html(project, guide["steps"], guide=guide),
        "assembly-guide.md": build_guide_markdown(guide),
        "assembly.json": json.dumps(guide, indent=2, sort_keys=True).encode("utf-8"),
    }
