"""Pinned plate selection, reversible replacement and deterministic recipe checks.

The reference maximum well volume is not a validated working volume. A plate
switch never creates more preparation targets or silently changes liquid amounts.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.labware import SavedLabwareRack, rack_inputs

PROFILE_ID = "corning_96_wellplate_360ul_flat"
TARGET = "sample-rack"
COMPILER = "microplate-v1"
Coordinate = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=-5000, le=5000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class LabwareSelection(StrictModel):
    profile_id: Literal["corning_96_wellplate_360ul_flat", "previous_tube_rack"] | None = None
    source: Annotated[str | None, Field(min_length=1, max_length=1000)] = None

    def verify_sources(self, message: str) -> None:
        if self.profile_id is None:
            if self.source is not None:
                raise ValueError("A labware selection source needs a profile choice.")
            return
        if not self.source or self.source not in message:
            raise ValueError("Labware selection needs a literal span from this message.")
        verify_selection(self.profile_id, self.source, message)


def verify_selection(profile_id: str, source: str, message: str) -> None:
    lowered = source.casefold()
    for clause in re.split(r"[,;!?\n]|\.(?!\d)", message):
        if not re.search(r"plate|piastr|rack|labware|provett|tubes?|96", clause, re.I):
            continue
        if re.search(
            r"\b(?:don't|do not|non|never|mai)\s+(?:switch|change|select|use|"
            r"return|restore|passare|cambiare|sostituire|usare|tornare|ripristinare)"
            r".{0,35}(?:plate|piastr|rack|labware|provett|tubes?)|\bnot now\b",
            clause,
            re.I,
        ):
            raise ValueError("A negated labware request cannot select a new container.")
        if re.search(r"\b(?:later|someday|future|eventually|in futuro|più avanti)\b", clause, re.I):
            raise ValueError("A future labware example is not a current selection.")
    if profile_id == "previous_tube_rack":
        if not re.search(r"\btubes?\b|\brack\b|provett|eppendorf|portaprovett", lowered):
            raise ValueError("Switching back needs an explicit request for the previous tube rack.")
        return
    if profile_id != PROFILE_ID:
        raise ValueError("This plate profile is not in the reviewed allowlist.")
    if not re.search(r"\b96\s*[- ]?(?:micro)?(?:well|pozzett)|" + re.escape(PROFILE_ID), lowered):
        raise ValueError("Choose the reviewed 96-well reference explicitly.")
    if re.search(r"\b(?:384|1536|48|24)\s*[- ]?(?:micro)?(?:well|pozzett)", message, re.I):
        raise ValueError(
            "Only the named 96-well reference is supported; no substitute was applied."
        )
    if re.search(r"\bpcr\b|deep[ -]?well|round[ -]?bottom|[uv][ -]?bottom", message, re.I):
        raise ValueError("That plate family differs from the reviewed flat-bottom reference.")
    if re.search(r"https?://|\bsku\b|catalog(?:ue)?\s*(?:number|no\.?|#)|\bcat\s*#", message, re.I):
        raise ValueError(
            "Exact external SKUs/URLs require a reviewed profile; no substitute was applied."
        )
    # A named tube from the old workflow is allowed. A different plate vendor is
    # not silently relabelled as the reviewed Corning software reference.
    for clause in re.split(r"[.;\n]", message):
        if re.search(r"plate|piastr", clause, re.I) and re.search(
            r"bio[ -]?rad|thermo|greiner|falcon|nunc|brandtech|vwr|sarstedt|"
            r"eppendorf\s+(?:96\s*[- ]?well\s+)?(?:microplate|plate|piastr)",
            clause,
            re.I,
        ):
            raise ValueError(
                "That specific plate/vendor has no reviewed adapter; keep the current labware."
            )
    for match in re.finditer(
        r"\b([A-Za-z][A-Za-z0-9]*(?:-[A-Za-z][A-Za-z0-9]*)?)\s+"
        r"(?:96\s*[- ]?(?:micro)?wells?\s+)?(?:microplate|plate|piastra)\b",
        message,
        re.I,
    ):
        if match[1].casefold() not in {
            "corning",
            "well",
            "flat",
            "reference",
            "standard",
            "generic",
            "a",
            "an",
            "the",
            "una",
            "un",
            "la",
            "questa",
            "new",
            "nuova",
            "to",
            "with",
            "into",
            "con",
            "wells",
            "microwell",
            "microwells",
        }:
            raise ValueError("The named destination plate needs its own reviewed profile.")


class PreviousComponent(StrictModel):
    kind: Literal["rack"]
    label: Annotated[str, Field(min_length=1, max_length=200)]
    size: Annotated[
        list[Annotated[float, Field(strict=True, gt=0, le=1000)]], Field(min_length=3, max_length=3)
    ]
    position: Annotated[list[Coordinate], Field(min_length=3, max_length=3)]


class PreviousSample(StrictModel):
    component: PreviousComponent
    rack_inputs: SavedLabwareRack | None = None


class PlateBinding(StrictModel):
    source_revision: Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
    source_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class PlateProvenance(StrictModel):
    compiler: Literal["microplate-v1"]
    selection_literal: Annotated[str, Field(min_length=1, max_length=1000)]
    source_project_revision: Annotated[int, Field(strict=True, ge=0, le=1000000)]


class SavedPlate(StrictModel):
    schema_version: Literal[1]
    kind: Literal["microplate_96"]
    profile_id: Literal["corning_96_wellplate_360ul_flat"]
    target_component_id: Literal["sample-rack"]
    profile_binding: PlateBinding
    provenance: PlateProvenance
    previous_sample: PreviousSample
    position_xz_mm: Annotated[list[Coordinate], Field(min_length=2, max_length=2)]


def _binding(compiled: dict) -> dict:
    source = compiled["profile"]["source"]
    return {"source_revision": source["revision"], "source_sha256": source["sha256"]}


def _index(project: dict) -> dict:
    return {part["id"]: part for part in project["design"]["components"]}


def _placement_checks(project: dict, size: list, x: float, z: float) -> list[dict]:
    parts = _index(project)
    base = parts["base"]
    checks = [
        {
            "id": "plate_deck_fit",
            "label": "Holder deck footprint",
            "passed": (
                abs(x - base["position"][0]) + size[0] / 2 <= base["size"][0] / 2 - 10 + 1e-7
                and abs(z - base["position"][2]) + size[2] / 2 <= base["size"][2] / 2 - 10 + 1e-7
            ),
            "detail": "Plate and holder need 10 mm clearance to each insert edge.",
        }
    ]
    for cid in ("source-rack", "tip-rack", "tip-waste", "controller"):
        other = parts[cid]
        clear = (
            abs(x - other["position"][0]) >= (size[0] + other["size"][0]) / 2 + 5 - 1e-7
            or abs(z - other["position"][2]) >= (size[2] + other["size"][2]) / 2 + 5 - 1e-7
        )
        checks.append(
            {
                "id": f"plate_clearance_{cid}",
                "label": "Neighbor footprint separation",
                "passed": clear,
                "detail": f"Holder and {cid} need 5 mm x/z separation.",
            }
        )
    return checks


def _find_placement(project: dict, size: list) -> tuple[float, float]:
    """Closest feasible center among rectangle-boundary candidates; no other part moves."""
    parts = _index(project)
    base, sample = parts["base"], parts[TARGET]
    x0, z0 = sample["position"][0], sample["position"][2]
    bounds = [
        (
            base["position"][axis] - base["size"][axis] / 2 + 10 + size[axis] / 2,
            base["position"][axis] + base["size"][axis] / 2 - 10 - size[axis] / 2,
        )
        for axis in (0, 2)
    ]
    if any(low > high for low, high in bounds):
        raise ValueError("The plate holder does not fit the accepted insert; no other parts moved.")
    axes = []
    for axis, current, (low, high) in zip((0, 2), (x0, z0), bounds):
        candidates = {low, high, min(high, max(low, current))}
        for cid in ("source-rack", "tip-rack", "tip-waste", "controller"):
            other = parts[cid]
            radius = (size[axis] + other["size"][axis]) / 2 + 5
            for candidate in (other["position"][axis] - radius, other["position"][axis] + radius):
                if low <= candidate <= high:
                    candidates.add(candidate)
        axes.append(candidates)
    candidates = sorted(
        ((x, z) for x in axes[0] for z in axes[1]),
        key=lambda point: ((point[0] - x0) ** 2 + (point[1] - z0) ** 2, *point),
    )
    for x, z in candidates:
        if all(check["passed"] for check in _placement_checks(project, size, x, z)):
            return x, z
    raise ValueError(
        "No sample-only placement fits this plate holder and the current neighbors. "
        "The complete previous project is preserved."
    )


def reconcile_plate_plan(project: dict) -> None:
    from app.dilution import _parse_volume, create_dilution_plan
    from app.quantities import normalize_volume

    module = project["labware_plate"]
    summary = project["summary"]
    plan = create_dilution_plan(
        summary["stock_concentration"], summary["target_concentrations"], summary["final_volume"]
    )
    requested = plan.get("final_volume_ul")
    if requested is None and summary.get("final_volume"):
        try:
            requested = float(_parse_volume(normalize_volume(summary["final_volume"]))[1])
        except ValueError:
            pass
    capacity = module["derived"]["well_capacity_ul"]
    order = module["derived"]["well_ordering"]
    targets = plan.get("steps", [])
    issues = []
    if requested is not None and requested > capacity:
        issues.append(
            f"Requested {requested:g} µL per well exceeds this profile's reference "
            f"maximum of {capacity:g} µL. Choose a smaller volume explicitly; "
            "the recipe has not been scaled. The reference maximum is not a "
            "validated working volume."
        )
    if len(targets) > len(order):
        issues.append("The number of current preparations exceeds the 96-well reference capacity.")
    occupied = order[: len(targets)]
    for step, label in zip(targets, occupied):
        step["well_name"] = label
        step["destination_component_id"] = TARGET
    plan["container_kind"] = "well"
    plan["destination_labels"] = occupied
    plan["assumptions"] = [text.replace("tube", "well") for text in plan.get("assumptions", [])]
    plan["message"] = plan["message"].replace("tube", "well")
    if issues:
        plan["status"] = "invalid"
        plan["message"] = " ".join(issues)
    module["compatibility"] = {
        "status": "volume_conflict"
        if issues
        else "ready"
        if plan["status"] == "ready"
        else "needs_recipe",
        "blocking_issues": issues,
        "well_capacity_ul": capacity,
        "requested_volume_ul": requested,
        "current_target_count": len(targets),
        "occupied_wells": occupied,
        "pipette_range_status": "unverified",
        "pipette_range_note": "Check each calculated stock/diluent transfer against the actual "
        "pipette's range. No pipette range is inferred from tube, plate or brand names.",
    }
    project["plan"] = plan


def canonical_labware_reply(project: dict, action_runs: list[dict], patch: dict) -> str | None:
    """Describe a bounded labware action using only its committed post-action facts.

    Model prose precedes execution and can refer to an earlier revision. Keep it
    out of selection outcomes and plate quantity edits, while leaving ordinary
    advice and unrelated workflows to the conversation model.
    """
    selections = [run for run in action_runs if run.get("kind") == "select_labware"]
    plate = project.get("labware_plate")
    quantity_edit = bool(
        plate
        and set(patch).intersection(
            {
                "stock_concentration",
                "target_concentrations",
                "final_volume",
            }
        )
    )
    if not selections and not quantity_edit:
        return None
    rejected = [run for run in action_runs if run.get("status") in ("rejected", "failed")]
    accepted_selection = any(run.get("status") == "accepted" for run in selections)
    paragraphs = []
    if rejected:
        paragraphs.append(
            "The requested change was not applied. "
            + " ".join(run["message"] for run in rejected if run.get("message"))
        )
    if plate:
        profile = plate["profile"]
        compatibility = plate["compatibility"]
        prefix = "Selected" if accepted_selection else "Current plate:"
        paragraphs.append(
            f"{prefix} {profile['display_name']} software reference and proposed holder. "
            "This is a pinned labware definition, not manufacturer CAD or verified physical fit."
        )
        volume = compatibility.get("requested_volume_ul")
        volume_text = (
            f"{volume:g} µL per well" if volume is not None else "volume not yet specified"
        )
        occupied = compatibility.get("occupied_wells", [])
        count = compatibility["current_target_count"]
        capacity = plate["derived"]["well_count"]
        paragraphs.append(
            f"Current preparation: {volume_text}; {count} existing target(s). "
            f"Assigned wells: {', '.join(occupied) if occupied else 'none yet'} "
            f"({len(occupied)} of {capacity}). Plate capacity does not add preparations."
        )
        if compatibility.get("blocking_issues"):
            paragraphs.append(
                " ".join(compatibility["blocking_issues"]) + " "
                "Confirmation and project-file generation are blocked "
                "until this conflict is resolved."
            )
        elif project["plan"]["status"] != "ready":
            paragraphs.append(
                "The preparation needs attention: " + project["plan"]["message"] + " "
                "Confirmation and project-file generation are blocked until the recipe is ready."
            )
        else:
            maximum = compatibility["well_capacity_ul"]
            status = (
                "The project is confirmed."
                if project["status"] == "confirmed"
                else "Review and confirm this draft before generating project files."
            )
            paragraphs.append(
                f"The current volume passes the profile's {maximum:g} µL reference maximum check; "
                "that maximum is not a validated working volume. " + status
            )
        paragraphs.append(
            "Pipette range, holder fit and access remain unverified. "
            "Plate operation animation is unavailable."
        )
    else:
        paragraphs.append(
            "Restored the previous tube rack and its recorded position."
            if accepted_selection
            else "The current tube setup was preserved."
        )
        plan = project.get("plan") or {}
        volume = plan.get("final_volume_ul")
        if volume is not None:
            paragraphs.append(
                f"Current preparation: {volume:g} µL per tube; "
                f"{len(plan.get('steps', []))} existing target(s)."
            )
        if plan.get("status") != "ready":
            paragraphs.append(
                "The preparation needs attention: " + plan.get("message", "") + " "
                "Confirmation and project-file generation remain blocked."
            )
        else:
            paragraphs.append(
                "Current recipe edits were kept. "
                + (
                    "The project is confirmed."
                    if project["status"] == "confirmed"
                    else "Review and confirm this draft before generating project files."
                )
            )
    return "\n\n".join(paragraphs)


def _sourcing(project: dict) -> None:
    from app.labware import _sourcing as rack_sourcing

    rack_sourcing(project)
    for group in project["sourcing"]["groups"]:
        if group["id"] == "fixtures":
            group["component_ids"] = [cid for cid in group["component_ids"] if cid != TARGET]
    module = project["labware_plate"]
    project["sourcing"]["groups"].append(
        {
            "id": "labware-plate",
            "label": "Reference 96-well plate and custom holder",
            "quantity": 1,
            "component_ids": [TARGET],
            "selected_id": PROFILE_ID,
            "options": [
                {
                    "id": PROFILE_ID,
                    "label": module["profile"]["display_name"] + " + proposed holder",
                    "supplier": "Reference profile / custom fabrication",
                    "sku": None,
                    "unit_price": None,
                    "price_kind": "unpriced",
                    "source_url": module["profile"]["source"]["source_url"],
                    "checked_on": module["profile"]["source"]["checked_on"],
                    "availability": "Exact plate and holder fabrication need verification",
                    "pros": [],
                    "cons": ["Software definition is not manufacturer CAD"],
                    "compatibility_note": "Pinned reference, not a verified exact commercial SKU. "
                    "Plate, printed holder material, fit, access and cleaning remain unverified.",
                }
            ],
        }
    )
    project["sourcing"]["unpriced_count"] += 1


def reapply_plate(project: dict, *, require_accepted: bool = True) -> dict:
    if not project.get("labware_plate"):
        return deepcopy(project)
    if project.get("labware_rack"):
        raise ValueError("Tube rack and plate cannot both be active.")
    from app.geometry import add_geometry
    from app.labware import _platform_guard
    from app.microplate_geometry import compile_microplate

    _platform_guard(project, require_accepted)
    result = deepcopy(project)
    module = result["labware_plate"]
    compiled = compile_microplate(module["profile_id"])
    if module["profile_binding"] != _binding(compiled):
        raise ValueError("Saved plate source binding differs from the pinned reference.")
    parts = _index(result)
    sample, base = parts[TARGET], parts["base"]
    x, z = module["position_xz_mm"]
    checks = _placement_checks(result, compiled["size_mm"], x, z)
    if any(not check["passed"] for check in checks):
        raise ValueError(" ".join(check["detail"] for check in checks if not check["passed"]))
    module.update(
        {key: deepcopy(compiled[key]) for key in ("size_mm", "geometry", "profile", "derived")}
    )
    module["metrics"] = deepcopy(compiled["checks"])
    module["checks"] = checks
    sample["kind"] = "rack"
    sample["label"] = "Corning 96-well software reference + proposed holder"
    sample["size"] = deepcopy(compiled["size_mm"])
    sample["position"] = [x, base["position"][1] + base["size"][1] / 2 + sample["size"][1] / 2, z]
    sample["labware_module_id"] = COMPILER
    if result.get("inspection_extension"):
        from app.inspection import check_extension

        previous = result["inspection_extension"]
        extension = check_extension(result, previous["proposal"])
        extension["provenance"] = deepcopy(previous.get("provenance", {}))
        result["inspection_extension"] = extension
        # Positions are IK consequences of the retained link/mast proposal, not a redesign.
        by_id = {part["id"]: part for part in extension["components"]}
        result["design"]["components"] = [
            deepcopy(by_id.get(part["id"], part)) for part in result["design"]["components"]
        ]
        result["design"]["assembly_bounds"] = deepcopy(extension["assembly_bounds"])
    reconcile_plate_plan(result)
    _sourcing(result)
    return add_geometry(result)


def select_plate(project: dict, selection: LabwareSelection, message: str) -> tuple[dict, dict]:
    selection.verify_sources(message)
    if selection.profile_id == "previous_tube_rack":
        return restore_previous_sample(project), {
            "kind": "select_labware",
            "status": "accepted",
            "message": "Restored the exact previous tube rack and position; "
            "current recipe edits were kept.",
        }
    if selection.profile_id != PROFILE_ID:
        raise ValueError("Choose a supported labware profile in this message.")
    from app.labware import _platform_guard
    from app.microplate_geometry import compile_microplate

    _platform_guard(project, True)
    result = deepcopy(project)
    compiled = compile_microplate(PROFILE_ID)
    parts = _index(result)
    original = parts[TARGET]
    previous = deepcopy(result.get("labware_plate", {}).get("previous_sample")) or {
        "component": {
            key: deepcopy(original[key]) for key in ("kind", "label", "size", "position")
        },
        "rack_inputs": rack_inputs(result["labware_rack"]) if result.get("labware_rack") else None,
    }
    result.pop("labware_rack", None)
    x, z = _find_placement(result, compiled["size_mm"])
    result["labware_plate"] = {
        "schema_version": 1,
        "kind": "microplate_96",
        "profile_id": PROFILE_ID,
        "target_component_id": TARGET,
        "profile_binding": _binding(compiled),
        "provenance": {
            "compiler": COMPILER,
            "selection_literal": selection.source,
            "source_project_revision": project["revision"],
        },
        "previous_sample": previous,
        "position_xz_mm": [x, z],
    }
    result = reapply_plate(result)
    result["revision"] += 1
    result["status"] = "draft"
    compatibility = result["labware_plate"]["compatibility"]
    text = (
        "Selected the named Corning 96-well / 360 µL flat software reference and proposed holder. "
    )
    text += (
        "Only the sample module moved as needed; the source machine and "
        "other deck parts were preserved. "
    )
    text += (
        " ".join(compatibility["blocking_issues"])
        if compatibility["blocking_issues"]
        else f"Mapped {compatibility['current_target_count']} existing target(s) to "
        f"{', '.join(compatibility['occupied_wells']) or 'no assigned wells yet'}; capacity 96 "
        "does not create 96 preparations. Physical fit and pipette access are unverified."
    )
    return result, {"kind": "select_labware", "status": "accepted", "message": text}


def restore_previous_sample(project: dict) -> dict:
    if not project.get("labware_plate"):
        raise ValueError(
            "There is no stored pre-plate sample rack to restore; no dimensions were guessed."
        )
    from app.domain import _plan_for
    from app.geometry import add_geometry
    from app.labware import _sourcing as rack_sourcing
    from app.labware import reapply_labware

    result = deepcopy(project)
    module = result.pop("labware_plate")
    previous = module["previous_sample"]
    parts = _index(result)
    sample, base = parts[TARGET], parts["base"]
    sample.update(deepcopy(previous["component"]))
    sample.pop("labware_module_id", None)
    if previous["rack_inputs"] is not None:
        result["labware_rack"] = deepcopy(previous["rack_inputs"])
        result = reapply_labware(result)
    else:
        checks = _placement_checks(
            result, sample["size"], sample["position"][0], sample["position"][2]
        )
        if any(not check["passed"] for check in checks):
            raise ValueError(
                "The stored original rack no longer fits this layout; current plate preserved."
            )
        sample["position"][1] = base["position"][1] + base["size"][1] / 2 + sample["size"][1] / 2
        if result.get("inspection_extension"):
            from app.inspection import check_extension

            old = result["inspection_extension"]
            new = check_extension(result, old["proposal"])
            new["provenance"] = deepcopy(old.get("provenance", {}))
            result["inspection_extension"] = new
            result["design"]["assembly_bounds"] = deepcopy(new["assembly_bounds"])
            by_id = {part["id"]: part for part in new["components"]}
            result["design"]["components"] = [
                deepcopy(by_id.get(part["id"], part)) for part in result["design"]["components"]
            ]
        rack_sourcing(result)
        result = add_geometry(result)
    result["plan"] = _plan_for(result["summary"])
    result["revision"] += 1
    result["status"] = "draft"
    return result


def plate_inputs(module: dict) -> dict:
    return {
        key: deepcopy(module[key])
        for key in (
            "schema_version",
            "kind",
            "profile_id",
            "target_component_id",
            "profile_binding",
            "provenance",
            "previous_sample",
            "position_xz_mm",
        )
    }


def restore_plate(project: dict, saved: object) -> dict:
    from app.labware import _brief, validate_saved_brief
    from app.microplate_geometry import compile_microplate

    module = SavedPlate.model_validate(saved).model_dump(exclude_none=True)
    previous = module["previous_sample"]
    previous.setdefault("rack_inputs", None)
    compiled = compile_microplate(module["profile_id"])
    if module["profile_binding"] != _binding(compiled):
        raise ValueError("The saved plate source/hash does not match the pinned definition.")
    if module["provenance"]["source_project_revision"] > project["revision"]:
        raise ValueError("Saved plate provenance cannot refer to a future project revision.")
    literal = module["provenance"]["selection_literal"]
    verify_selection(PROFILE_ID, literal, literal)
    if previous["rack_inputs"]:
        rack = previous["rack_inputs"]
        validate_saved_brief(_brief(rack["spec"], rack["provenance"]["sources"]))
        from app.labware_geometry import compile_labware_rack

        dimensions = compile_labware_rack(rack["spec"])["size_mm"]
        if previous["component"]["size"] != dimensions:
            raise ValueError(
                "Stored previous tube rack size differs from its grounded specification."
            )
        from app.domain import new_project

        canonical = _index(new_project())[TARGET]
        if rack["original_component"] != {key: canonical[key] for key in ("kind", "label", "size")}:
            raise ValueError(
                "Stored original tube rack differs from the canonical generic component."
            )
        if previous["component"]["label"] != "Measured-input rim-supported tube rack":
            raise ValueError("Stored prior rack label does not match the measured-rack adapter.")
        if any(
            fact["recorded_at_revision"] > project["revision"]
            for fact in rack["provenance"]["sources"].values()
        ):
            raise ValueError("Archived rack sources cannot refer to future project revisions.")
    else:
        canonical = _index(project)[TARGET]
        if any(previous["component"][key] != canonical[key] for key in ("kind", "label", "size")):
            raise ValueError("Stored previous component is not the canonical generic rack.")
    old = previous["component"]
    if not all(
        check["passed"]
        for check in _placement_checks(project, old["size"], old["position"][0], old["position"][2])
    ):
        raise ValueError("Stored previous sample pose does not fit the accepted deck layout.")
    result = deepcopy(project)
    result["labware_plate"] = module
    return reapply_plate(result)
