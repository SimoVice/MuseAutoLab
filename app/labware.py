"""User-grounded tube measurements and a bounded rack on the Jubilee insert.

Dimensions supplied by the user are design inputs, not verified measurements or
vendor specifications. A tube's nominal liquid capacity never defines its shape.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

KIND = "rim_supported_tube_rack"
TARGET = "sample-rack"
COMPILER = "rim-rack-v1"
REQUIRED_FIELDS = (
    "body_diameter_max_mm",
    "rim_diameter_min_mm",
    "cap_diameter_max_mm",
    "below_rim_height_mm",
    "count",
    "columns",
)
OPTIONAL_FIELDS = (
    "pitch_mm",
    "radial_clearance_mm",
    "max_width_mm",
    "max_depth_mm",
    "max_height_mm",
)
SPEC_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS
FIELD_LABELS = {
    "body_diameter_max_mm": "maximum tube-body diameter (mm)",
    "rim_diameter_min_mm": "minimum supporting-rim diameter (mm)",
    "cap_diameter_max_mm": "maximum closed-cap envelope including hinge and rim (mm)",
    "below_rim_height_mm": "height from underside of rim to tube tip (mm)",
    "count": "number of tube positions",
    "columns": "number of columns",
}
Number = Annotated[float, Field(strict=True, gt=0, le=300, allow_inf_nan=False)]
DIMENSION_RE = re.compile(
    r"(?<![\w.+-])(\d+(?:[.,]\d+)?)\s*"
    r"(mm|millimet(?:er|re)s?|millimetr[oi]|cm|centimet(?:er|re)s?|centimetr[oi])\b",
    re.IGNORECASE,
)
ALIASES = {
    "body_diameter_max_mm": r"\bbody\b|\bcorpo\b|body_diameter",
    "rim_diameter_min_mm": r"\brim\b|\bbordo\b|\bcollar\w*|\bflangi\w*|rim_diameter",
    "cap_diameter_max_mm": r"\bcap\b|\btapp\w*|closed.envelope|ingombro.chius|cap_diameter",
    "below_rim_height_mm": (
        r"below.rim|under.rim|sotto.{0,20}(?:bordo|collar)|below_rim|"
        r"underside.{0,20}rim.{0,30}tip|rim.{0,20}underside.{0,30}tip|"
        r"intradosso.{0,20}(?:bordo|collar).{0,30}(?:punta|fondo)|"
        r"(?:below|under|beneath|sotto).{0,45}(?:rim|bordo|collar|flange)"
        r".{0,45}(?:tip|punta|height|altezz)"
    ),
    "count": (
        r"\bcount\b|\bpositions?\b|\bholes?\b|\btubes?\b|\bposizioni\b|"
        r"\bfori\b|\bprovette\b|\bposti\b|\bspaces?\b"
    ),
    "columns": r"\bcolumns?\b|\bcolonn[ae]\b",
    "pitch_mm": r"\bpitch\b|\bpasso\b|\binterasse\b",
    "radial_clearance_mm": r"radial.{0,12}clearance|luce.radiale|gioco.radiale|radial_clearance",
    "max_width_mm": r"\bwidth\b|\blarghezza\b|max_width",
    "max_depth_mm": r"\bdepth\b|\bprofondit\w*|max_depth",
    "max_height_mm": r"\bheight\b|\baltezza\b|max_height",
}


def _dimension_roles(text: str) -> set[str]:
    """Identify physical roles, without interpreting a number or a tube volume."""
    diameter = bool(re.search(r"diamet(?:er|r)|[⌀øØ]", text, re.I))
    axial = bool(re.search(ALIASES["below_rim_height_mm"], text, re.I))
    cap = bool(re.search(ALIASES["cap_diameter_max_mm"], text, re.I)) and bool(
        re.search(r"diamet(?:er|r)|envelope|ingombro|closed|chius", text, re.I)
    )
    has_minimum = bool(re.search(r"\bmin(?:imum)?\b|minim\w*|smallest", text, re.I))
    has_maximum = bool(re.search(r"\bmax(?:imum)?\b|massim\w*|largest", text, re.I))
    minimum_only, maximum_only = has_minimum and not has_maximum, has_maximum and not has_minimum
    roles = set()
    if axial:
        roles.add("below_rim_height_mm")
    if cap and not minimum_only:
        roles.add("cap_diameter_max_mm")
    if diameter and not minimum_only and re.search(ALIASES["body_diameter_max_mm"], text, re.I):
        roles.add("body_diameter_max_mm")
    if (
        diameter
        and not axial
        and not maximum_only
        and re.search(ALIASES["rim_diameter_min_mm"], text, re.I)
        and not (cap and re.search(r"including|inclus|hinge|cernier", text, re.I))
    ):
        roles.add("rim_diameter_min_mm")
    for key in OPTIONAL_FIELDS:
        if key == "max_height_mm" and axial:
            continue
        if key.startswith("max_"):
            if minimum_only:
                continue
            limit = bool(
                re.search(
                    r"\bmax(?:imum)?\b|massim\w*|\blimit\w*|at.most|no.more.than|"
                    r"non.oltre|non.superiore|entro\b|[<≤]|max_(?:width|depth|height)",
                    text,
                    re.I,
                )
            )
            tube_only = re.search(
                r"\bbody\b|\bcorpo\b|\bcap\b|\btapp\w*|"
                r"\btubes?\b|\bprovett\w*",
                text,
                re.I,
            ) and not re.search(r"\brack\b|portaprovett\w*", text, re.I)
            if not limit or tube_only:
                continue
        if re.search(ALIASES[key], text, re.I):
            roles.add(key)
    return roles


def _measurement_value(match: re.Match) -> float:
    return float(match[1].replace(",", ".")) * (
        10 if match[2].lower().startswith(("cm", "cent")) else 1
    )


def _dimension_bindings(source: str) -> dict[str, set[float | None]]:
    """Bind each labelled fact to its own adjacent explicit measurement.

    Long citations may contain multiple independently labelled facts. Separators
    split facts, not decimal commas. Within an unseparated list a new label binds
    only the next measurement; a previous number never satisfies a later label.
    A lone measurement can also precede its label ("0.5 mm radial clearance").
    """
    bound: dict[str, set[float | None]] = {}
    assignments: dict[int, set[str]] = {}
    # Keep original offsets so unlabelled alternatives such as "10 mm or 12 mm"
    # can invalidate a supposedly precise value instead of silently choosing one.
    boundaries = [0]
    separators = list(re.finditer(r";|\n|,(?!\d)", source))
    for separator in separators:
        boundaries.extend((separator.start(), separator.end()))
    boundaries.append(len(source))
    segments = [(boundaries[i], boundaries[i + 1]) for i in range(0, len(boundaries), 2)]
    # A parenthetical/appositive comma before the value does not end its label:
    # "closed cap envelope, hinge included: 17 mm" remains one labelled fact.
    merged = []
    pending = None
    for start, end in segments:
        start = pending if pending is not None else start
        if not DIMENSION_RE.search(source[start:end]):
            pending = start
        else:
            merged.append((start, end))
            pending = None
    if pending is not None and merged:
        merged[-1] = (merged[-1][0], len(source))
    clauses = []
    for start, end in merged:
        text = source[start:end]
        cuts = [
            match
            for match in re.finditer(r"\b(?:and|or|e|o)\b", text, re.I)
            if DIMENSION_RE.search(text[: match.start()])
            and DIMENSION_RE.search(text[match.end() :])
        ]
        cursor = start
        for cut in cuts:
            clauses.append((cursor, start + cut.start()))
            cursor = start + cut.end()
        clauses.append((cursor, end))
    for start, end in clauses:
        text = source[start:end]
        measures = list(DIMENSION_RE.finditer(text))
        for index, measure in enumerate(measures):
            if len(measures) == 1:
                label = text[: measure.start()] + " " + text[measure.end() :]
            else:
                prefix = text[measures[index - 1].end() if index else 0 : measure.start()]
                label = prefix
                # Reverse label order is supported when no preceding label exists.
                if not _dimension_roles(label) and index == 0:
                    label += text[measure.end() : measures[index + 1].start()]
            roles = _dimension_roles(label)
            if len(roles) != 1:
                continue
            role = roles.pop()
            bound.setdefault(role, set()).add(_measurement_value(measure))
            assignments[start + measure.start()] = {role}
    all_measures = list(DIMENSION_RE.finditer(source))
    for before, after in zip(all_measures, all_measures[1:]):
        gap = source[before.end() : after.start()]
        if re.fullmatch(r"\s*(?:or|and|to|e|o|a|[-–,])\s*", gap, re.I):
            if after.start() not in assignments:
                for role in assignments.get(before.start(), set()):
                    bound[role].add(None)
    return bound


def _count_bindings(source: str, field: str) -> set[int]:
    label = (
        r"columns?|colonn[ae]"
        if field == "columns"
        else r"count|positions?|holes?|tubes?|posizioni|fori|provette|posti|spaces?"
    )
    number = r"(?<![\w.,+\-])(\d+)(?!\w|[.,]\d)"
    values = set()
    patterns = (
        number + rf"\s*[-–]?\s*(?:{label})\b",
        rf"\b(?:{label})\b\s*(?::|=|of|di|is|sono|è)?\s*" + number,
    )
    for pattern in patterns:
        for match in re.finditer(pattern, source, re.I):
            tail = source[match.end() :]
            if not re.match(r"\s*(?:[µμu]?[mnu]?l|mm|cm|mg|g)\b", tail, re.I):
                values.add(int(match[1]))
    return values


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class LabwarePartialSpec(StrictModel):
    body_diameter_max_mm: Number | None = None
    rim_diameter_min_mm: Number | None = None
    cap_diameter_max_mm: Number | None = None
    below_rim_height_mm: Number | None = None
    count: Annotated[int | None, Field(strict=True, ge=1, le=24)] = None
    columns: Annotated[int | None, Field(strict=True, ge=1, le=8)] = None
    pitch_mm: Number | None = None
    radial_clearance_mm: Annotated[float | None, Field(strict=True, ge=0.4, le=5)] = None
    max_width_mm: Number | None = None
    max_depth_mm: Number | None = None
    max_height_mm: Number | None = None

    def patch(self) -> dict:
        return self.model_dump(exclude_none=True)


class LabwareSpec(LabwarePartialSpec):
    body_diameter_max_mm: Number
    rim_diameter_min_mm: Number
    cap_diameter_max_mm: Number
    below_rim_height_mm: Number
    count: Annotated[int, Field(strict=True, ge=1, le=24)]
    columns: Annotated[int, Field(strict=True, ge=1, le=8)]


class LabwareUpdate(LabwarePartialSpec):
    source_body_diameter_max_mm: Annotated[str | None, Field(max_length=500)] = None
    source_rim_diameter_min_mm: Annotated[str | None, Field(max_length=500)] = None
    source_cap_diameter_max_mm: Annotated[str | None, Field(max_length=500)] = None
    source_below_rim_height_mm: Annotated[str | None, Field(max_length=500)] = None
    source_count: Annotated[str | None, Field(max_length=500)] = None
    source_columns: Annotated[str | None, Field(max_length=500)] = None
    source_pitch_mm: Annotated[str | None, Field(max_length=500)] = None
    source_radial_clearance_mm: Annotated[str | None, Field(max_length=500)] = None
    source_max_width_mm: Annotated[str | None, Field(max_length=500)] = None
    source_max_depth_mm: Annotated[str | None, Field(max_length=500)] = None
    source_max_height_mm: Annotated[str | None, Field(max_length=500)] = None

    def patch(self) -> dict:
        return {key: getattr(self, key) for key in SPEC_FIELDS if getattr(self, key) is not None}

    def verify_sources(self, message: str) -> None:
        for key in SPEC_FIELDS:
            value, source = getattr(self, key), getattr(self, f"source_{key}")
            if value is None:
                if source is not None:
                    raise ValueError("A labware source without a value is not a change.")
                continue
            if not source or source not in message:
                raise ValueError(f"{key} needs its labelled literal source in the latest message.")
            if key in ("count", "columns"):
                quantities = _count_bindings(source, key)
                if quantities != {value}:
                    raise ValueError(f"{key} must match an explicit integer count, not a volume.")
            else:
                values = _dimension_bindings(source).get(key, set())
                if (
                    len(values) != 1
                    or None in values
                    or not math.isclose(value, next(iter(values)), abs_tol=1e-8)
                ):
                    raise ValueError(
                        f"{key} must match its own unambiguous labelled dimension and unit."
                    )


class LabwareFact(StrictModel):
    literal: Annotated[str, Field(min_length=1, max_length=500)]
    value: Annotated[float | int, Field(allow_inf_nan=False)]
    recorded_at_revision: Annotated[int, Field(strict=True, ge=0, le=1000000)]


class SavedLabwareBrief(StrictModel):
    schema_version: Literal[1]
    kind: Literal["rim_supported_tube_rack"]
    target_component_id: Literal["sample-rack"]
    spec: LabwarePartialSpec
    sources: Annotated[dict[str, LabwareFact], Field(max_length=11)]
    missing_fields: Annotated[list[str], Field(max_length=6)]
    status: Literal["needs_dimensions", "ready"]


class OriginalRack(StrictModel):
    kind: Literal["rack"]
    label: Annotated[str, Field(min_length=1, max_length=200)]
    size: Annotated[list[Number], Field(min_length=3, max_length=3)]


class LabwareProvenance(StrictModel):
    basis: Literal["user_dimensions"]
    sources: Annotated[dict[str, LabwareFact], Field(max_length=11)]
    compiler: Literal["rim-rack-v1"]
    source_project_revision: Annotated[int, Field(strict=True, ge=0, le=1000000)]
    previous_size_mm: Annotated[list[Number], Field(min_length=3, max_length=3)]


class SavedLabwareRack(StrictModel):
    schema_version: Literal[1]
    kind: Literal["rim_supported_tube_rack"]
    target_component_id: Literal["sample-rack"]
    spec: LabwareSpec
    provenance: LabwareProvenance
    original_component: OriginalRack


def rack_inputs(module: dict) -> dict:
    return {
        key: deepcopy(module[key])
        for key in (
            "schema_version",
            "kind",
            "target_component_id",
            "spec",
            "provenance",
            "original_component",
        )
    }


def restore_labware(project: dict, brief: object | None, module: object | None) -> dict:
    result = deepcopy(project)
    if brief is not None:
        result["labware_brief"] = validate_saved_brief(brief)
        if any(
            fact["recorded_at_revision"] > project["revision"]
            for fact in result["labware_brief"]["sources"].values()
        ):
            raise ValueError("Saved rack facts cannot come from a future project revision.")
    if module is None:
        return result
    if brief is None:
        raise ValueError("An applied rack requires its saved dimensional brief.")
    saved = SavedLabwareRack.model_validate(module)
    if saved.provenance.source_project_revision > project["revision"]:
        raise ValueError("Saved rack provenance cannot refer to a future project revision.")
    spec = saved.spec.patch()
    sources = {key: fact.model_dump() for key, fact in saved.provenance.sources.items()}
    # Applied module may intentionally precede a later incomplete revision brief.
    validate_saved_brief(_brief(spec, sources))
    if any(fact["recorded_at_revision"] > project["revision"] for fact in sources.values()):
        raise ValueError("Saved rack facts cannot come from a future project revision.")
    original = next(part for part in project["design"]["components"] if part["id"] == TARGET)
    if saved.original_component.model_dump() != {
        key: deepcopy(original[key]) for key in ("kind", "label", "size")
    }:
        raise ValueError("Saved original rack must match the canonical generic component.")
    result["labware_rack"] = saved.model_dump(exclude_none=True)
    return reapply_labware(result)


def _brief(spec: dict, sources: dict) -> dict:
    spec = LabwarePartialSpec.model_validate(spec).patch()
    missing = [field for field in REQUIRED_FIELDS if field not in spec]
    return {
        "schema_version": 1,
        "kind": KIND,
        "target_component_id": TARGET,
        "spec": spec,
        "sources": deepcopy(sources),
        "missing_fields": missing,
        "status": "needs_dimensions" if missing else "ready",
    }


def update_labware_brief(project: dict, update: LabwareUpdate, message: str) -> dict:
    update.verify_sources(message)
    patch = update.patch()
    if not patch:
        return deepcopy(project)
    result = deepcopy(project)
    previous = project.get("labware_brief") or _brief({}, {})
    spec, sources = deepcopy(previous["spec"]), deepcopy(previous["sources"])
    for key, value in patch.items():
        spec[key] = value
        sources[key] = {
            "literal": getattr(update, f"source_{key}"),
            "value": value,
            "recorded_at_revision": project["revision"],
        }
    result["labware_brief"] = _brief(spec, sources)
    if result["labware_brief"] != previous:
        result["revision"] += 1
        result["status"] = "draft"
    return result


def validate_saved_brief(value: object) -> dict:
    saved = SavedLabwareBrief.model_validate(value)
    spec = saved.spec.patch()
    sources = {key: fact.model_dump() for key, fact in saved.sources.items()}
    if set(spec) != set(sources) or set(spec) - set(SPEC_FIELDS):
        raise ValueError("Saved labware dimensions require matching supported source facts.")
    for key, fact in sources.items():
        update = LabwareUpdate.model_validate({key: spec[key], f"source_{key}": fact["literal"]})
        update.verify_sources(fact["literal"])
        if fact["value"] != spec[key]:
            raise ValueError("Saved labware values do not match their supporting facts.")
    result = _brief(spec, sources)
    if result["missing_fields"] != saved.missing_fields or result["status"] != saved.status:
        raise ValueError("Saved labware readiness does not match its dimensions.")
    return result


def _target_count(project: dict) -> int:
    plan = project.get("plan") or {}
    count = len(plan.get("steps") or [])
    targets = project.get("summary", {}).get("target_concentrations")
    if isinstance(targets, str) and targets.strip():
        from app.quantities import normalize_targets

        try:
            normalized = normalize_targets(targets)
            tokens = [value.strip() for value in re.split(r"[;,]", normalized)]
            if all(tokens):
                count = max(count, len(tokens))
        except ValueError:
            pass
    return count


def _platform_guard(project: dict, require_accepted: bool) -> None:
    from app.engineering import state_for
    from app.foundation_design import is_source_based

    if (
        not is_source_based(project)
        or state_for(project)["selected_platform_id"] == "opentrons-ot2"
    ):
        raise ValueError(
            "The measured tube-rack adapter supports the Jubilee insert only. "
            "The current platform is preserved; OT-2 custom labware is unsupported."
        )
    if require_accepted and not project.get("engineering_design"):
        raise ValueError("Develop and accept a Jubilee layout before generating the tube rack.")
    if project["design"].get("constraint_status") == "infeasible":
        raise ValueError("Resolve the infeasible workspace before applying the tube rack.")


def _placement_checks(project: dict, size: list, compiled: dict) -> list[dict]:
    index = {part["id"]: part for part in project["design"]["components"]}
    rack, deck = index[TARGET], index["base"]
    envelope = compiled["derived"].get("closed_cap_envelope_size_mm", [size[0], size[2]])
    width, depth = max(size[0], envelope[0]), max(size[2], envelope[1])
    x, z = rack["position"][0], rack["position"][2]
    dx, dz = deck["position"][0], deck["position"][2]
    inside = (
        abs(x - dx) + width / 2 <= deck["size"][0] / 2 - 10
        and abs(z - dz) + depth / 2 <= deck["size"][2] / 2 - 10
    )
    checks = [
        {
            "id": "rack_deck_fit",
            "label": "Rack and closed-tube deck footprint",
            "passed": inside,
            "detail": "Rack/closed-cap envelope needs 10 mm to deck edges.",
        }
    ]
    for cid in ("source-rack", "tip-rack", "tip-waste", "controller"):
        other = index[cid]
        ox, oz = other["position"][0], other["position"][2]
        clear = (
            abs(x - ox) >= (width + other["size"][0]) / 2 + 5
            or abs(z - oz) >= (depth + other["size"][2]) / 2 + 5
        )
        checks.append(
            {
                "id": f"rack_clearance_{cid}",
                "label": "Neighbor footprint separation",
                "passed": clear,
                "detail": f"Rack and {cid} require 5 mm x/z separation.",
            }
        )
    return checks


def _sourcing(project: dict) -> None:
    from app.foundation_design import foundation_sourcing

    sourcing = foundation_sourcing(project)
    if project.get("inspection_extension"):
        project["sourcing"] = sourcing
        from app.inspection import _extension_sourcing

        _extension_sourcing(project)
        sourcing = project["sourcing"]
    if project.get("labware_rack"):
        for group in sourcing["groups"]:
            if group["id"] == "fixtures":
                group["component_ids"] = [cid for cid in group["component_ids"] if cid != TARGET]
        sourcing["groups"].append(
            {
                "id": "labware-rack",
                "label": "Measured-input printed tube rack",
                "quantity": 1,
                "component_ids": [TARGET],
                "selected_id": COMPILER,
                "options": [
                    {
                        "id": COMPILER,
                        "label": "Custom rim-supported tube rack",
                        "supplier": "Custom fabrication",
                        "sku": None,
                        "unit_price": None,
                        "price_kind": "unpriced",
                        "source_url": None,
                        "checked_on": None,
                        "availability": "Needs fabrication and fit coupon",
                        "compatibility_note": "User dimensions and assumed FDM tolerances; "
                        "material, print process, coupon fit, cleaning and access "
                        "need verification.",
                        "pros": [],
                        "cons": ["No fabrication or laboratory validation"],
                    }
                ],
            }
        )
        sourcing["unpriced_count"] += 1
    project["sourcing"] = sourcing
    if project.get("tip_rack"):
        from app.tip_racks import _sourcing as tip_sourcing

        tip_sourcing(project)


def reapply_labware(project: dict, *, require_accepted: bool = True) -> dict:
    """Recompile the module on the current deck without changing other geometry."""
    if not project.get("labware_rack"):
        return deepcopy(project)
    from app.geometry import add_geometry
    from app.labware_geometry import compile_labware_rack

    _platform_guard(project, require_accepted)
    result = deepcopy(project)
    module = result["labware_rack"]
    spec = LabwareSpec.model_validate(module["spec"]).patch()
    compiled = compile_labware_rack(spec)
    checks = _placement_checks(result, compiled["size_mm"], compiled)
    capacity = spec["count"] >= _target_count(result)
    checks.append(
        {
            "id": "rack_preparation_capacity",
            "label": "Preparation target capacity",
            "passed": capacity,
            "detail": f"{spec['count']} positions for "
            f"{_target_count(result)} currently calculated preparation targets.",
        }
    )
    if any(not check["passed"] for check in checks):
        raise ValueError(" ".join(check["detail"] for check in checks if not check["passed"]))
    module.update({key: deepcopy(compiled[key]) for key in ("size_mm", "geometry", "derived")})
    module["metrics"] = deepcopy(compiled["checks"])
    module["assumptions"] = {
        "radial_clearance_mm": spec.get("radial_clearance_mm", 0.4),
        "bore_diametral_tolerance_plus_minus_mm": 0.3,
        "minimum_rim_bearing_mm": 0.4,
        "top_thickness_mm": 4,
        "end_wall_mm": 3,
        "bottom_clearance_mm": 3,
        "process": "FDM, inverted printing; material and settings unselected",
        "tube_envelope": "Closed cap maximum must include hinge, rim and all protrusions",
        "unverified": [
            "Open-cap interference",
            "Pipette access",
            "Deck attachment",
            "Print fit and strength",
            "Cleaning and chemical compatibility",
        ],
    }
    module["checks"] = [
        {
            "id": "rack_parametric_compile",
            "label": "Parametric geometry",
            "passed": True,
            "detail": "Bore, bearing, web and closed-cap pitch "
            "satisfy the stated input and assumed FDM tolerance limits.",
        },
        *checks,
    ]
    index = {part["id"]: part for part in result["design"]["components"]}
    part, deck = index[TARGET], index["base"]
    part["size"] = deepcopy(compiled["size_mm"])
    part["position"][1] = deck["position"][1] + deck["size"][1] / 2 + part["size"][1] / 2
    part["label"] = "Measured-input rim-supported tube rack"
    part["labware_module_id"] = COMPILER
    if result.get("inspection_extension"):
        from app.inspection import check_extension

        previous = result["inspection_extension"]
        extension = check_extension(result, previous["proposal"])
        extension["provenance"] = deepcopy(previous.get("provenance", {}))
        result["inspection_extension"] = extension
        by_id = {component["id"]: component for component in extension["components"]}
        result["design"]["components"] = [deepcopy(by_id.get(component["id"], component))
                                            for component in result["design"]["components"]]
        result["design"]["assembly_bounds"] = deepcopy(extension["assembly_bounds"])
    _sourcing(result)
    return add_geometry(result)


def develop_labware(project: dict) -> tuple[dict, dict]:
    from app.engineering import state_for

    if project.get("labware_plate"):
        raise ValueError(
            "Switch back to the stored previous tube rack before changing its dimensions."
        )

    if (
        project.get("design", {}).get("platform")
        or state_for(project)["selected_platform_id"] == "opentrons-ot2"
    ):
        _platform_guard(project, False)
    brief = project.get("labware_brief")
    if not brief or brief["missing_fields"]:
        missing = list(REQUIRED_FIELDS) if not brief else brief["missing_fields"]
        result = deepcopy(project)
        if not brief:
            result["labware_brief"] = _brief({}, {})
            result["revision"] += 1
            result["status"] = "draft"
        return result, {
            "kind": "develop_labware",
            "status": "ready",
            "message": "Tube-rack inputs still needed: "
            + "; ".join(FIELD_LABELS[key] for key in missing)
            + ". "
            "Nominal 1.5–2 mL capacity does not establish these dimensions; "
            "the closed-cap maximum must include hinge and rim protrusions.",
        }
    _platform_guard(project, True)
    index = {part["id"]: part for part in project["design"]["components"]}
    original = project.get("labware_rack", {}).get("original_component") or {
        key: deepcopy(index[TARGET][key]) for key in ("kind", "label", "size")
    }
    result = deepcopy(project)
    result["labware_rack"] = {
        "schema_version": 1,
        "kind": KIND,
        "target_component_id": TARGET,
        "spec": deepcopy(brief["spec"]),
        "original_component": deepcopy(original),
        "provenance": {
            "basis": "user_dimensions",
            "sources": deepcopy(brief["sources"]),
            "compiler": COMPILER,
            "source_project_revision": project["revision"],
            "previous_size_mm": deepcopy(index[TARGET]["size"]),
        },
    }
    result = reapply_labware(result)
    result["revision"] += 1
    result["status"] = "draft"
    return result, {
        "kind": "develop_labware",
        "status": "accepted",
        "message": "Applied the rim-supported tube rack from your recorded dimensions. "
        "CAD and footprint checks passed; print a fit coupon before the full part. "
        "Pipette access, retention, material and real print fit remain unverified.",
    }


def remove_labware(project: dict) -> dict:
    if not project.get("labware_rack"):
        return deepcopy(project)
    from app.geometry import add_geometry

    result = deepcopy(project)
    module = result.pop("labware_rack")
    index = {part["id"]: part for part in result["design"]["components"]}
    part, deck = index[TARGET], index["base"]
    part.update(deepcopy(module["original_component"]))
    part.pop("labware_module_id", None)
    part["position"][1] = deck["position"][1] + deck["size"][1] / 2 + part["size"][1] / 2
    if result.get("engineering_design"):
        from app.design_spec import check_candidate

        failures = [
            check["detail"]
            for check in check_candidate(result, result["engineering_design"]["proposal"])
            if not check["passed"]
        ]
        if failures:
            raise ValueError(
                "Restore a layout that fits the original rack before removing "
                "this module. " + " ".join(failures)
            )
    result["revision"] += 1
    result["status"] = "draft"
    _sourcing(result)
    return add_geometry(result)
