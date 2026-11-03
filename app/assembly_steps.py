"""User-facing build sequence assembled from the active machine, labware and purchase list."""


def assembly_steps(project: dict, technical_steps: list[dict], proposal: dict) -> list[dict]:
    steps = []
    rows = {row["group_id"]: row for row in proposal["rows"]}
    technical = {step["id"]: step for step in technical_steps}

    def add(title, *instructions, reference=None, group=None):
        links = [{"title": src["title"], "url": src["url"]}
                 for src in technical.get(reference, {}).get("sources", [])[:2]]
        row = rows.get(group, {})
        url = row.get("source_url")
        if url and not any(src["url"] == url for src in links):
            links.append({"title": row.get("selected_product_label") or row["label"], "url": url})
        if row.get("fabrication_url"):
            links.insert(0, {"title": "Download part model (STEP)", "url": row["fabrication_url"]})
        steps.append({"title": title, "instructions": list(instructions), "sources": links})

    if concept := project.get("concept_design"):
        for part in concept.get("components", []):
            if part.get("assembly"):
                add(f"Fit the {part['name']}", part["assembly"], group="concept-" + part["key"])
        return steps
    if station := project.get("bench_station"):
        for module in station.get("modules", []):
            add(f"Set up the {module['label']}", module["guidance"],
                group=f"bench-{module['id']}-equipment")
        return steps
    if not project.get("engineering_design"):
        return []

    if project["design"].get("foundation"):
        add("Assemble the Jubilee frame and motion system",
            "Check the frame, fasteners, rails and motion kits against the Jubilee parts list. "
            "Follow the frame and CoreXY assembly booklets in order.",
            "Before adding the deck, check that the frame is square and the carriage travels "
            "freely by hand with the power off.", reference="upstream-frame")
        add("Fit the deck and check the pipette mount",
            "Compare the mounting holes on your build plate with the proposed insert. "
            "Measure your pipette body, mounting points and tip ejection travel before making "
            "the adapter.",
            "With the machine powered off, dry-fit the pipette with an empty tip. "
            "Check that the tallest rack clears the parked tool.", reference="motion-pipette")
    elif project["design"].get("platform"):
        add("Unpack and set up the OT-2",
            "Use the manufacturer's guide to remove the shipping restraints and install the "
            "configured pipette. Complete the robot and pipette calibration in the Opentrons App.",
            reference="ot2-unboxing", group="platform")
    else:
        add("Check the frame and working surface",
            "Measure the available bench area and compare it with the proposed footprint. "
            "Confirm the mounting pattern and keep cable and service access clear.")

    if plate := project.get("labware_plate"):
        name = plate.get("display_name") or plate.get("profile", {}).get("display_name") or "plate"
        add("Fit the plate and its holder",
            f"Use the selected {name}. Test-fit an empty plate in the holder and secure the "
            "holder against shifting. Orient A1 as shown in the workspace.",
            "Check the first and last well by hand before setting tool offsets.",
            reference="plate-holder", group="labware-plate")
    elif project.get("labware_rack"):
        add("Test-fit the tubes before printing the full rack",
            "Print the small fit coupon first. Try an empty tube of the intended make, check "
            "that its rim supports it and that adjacent caps clear each other, then print the "
            "full rack and secure it on the deck.", group="labware-rack", reference="racks")
    else:
        add("Place the tube racks",
            "Put empty source and sample tubes in their proposed positions. Check the tube rim "
            "and cap clearance, then locate and secure each rack so it returns to the same spot.",
            reference="racks", group="fixtures")
    tip = rows.get("tip-rack-options", {}).get("selected_product_label") or "the proposed tip rack"
    add("Place the tips and tip waste",
        f"Install {tip} beside the waste container. Try an unused tip from your actual box. "
        "Check that the pipette seats it, lifts without moving the rack and ejects it into waste.",
        reference="selected-tip-rack", group="tip-rack-options")
    if project.get("inspection_extension"):
        add("Position the inspection camera",
            "Dry-fit the camera and mount. Move the inspection arm through its full sweep by "
            "hand and leave enough cable slack at both limits. Use an empty plate or rack to "
            "check that the first and last positions remain visible.",
            reference="inspection-extension")
    if project.get("cold_transfer_extension"):
        add("Position the refrigerator and transfer gripper",
            "Measure the chosen refrigerator's opening, shelf and door swing. Compare them "
            "with the proposed cold bay before fixing the transfer rail in place.",
            "With power off, test the jaws and complete transfer path with an empty rigid plate. "
            "Provide door actuation or an operator step and a way to release the plate manually.",
            reference="cold-transfer-extension", group="cold-transfer-motion")
    add("Dry-run the assembled workstation",
        "Check retention, cable routing and travel limits. Calibrate the tool and each working "
        "position on the physical controller, then run an empty cycle one move at a time. "
        "Verify transfers with water before loading samples.")
    return steps
