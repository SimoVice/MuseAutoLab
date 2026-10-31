"""Source-bound tip-rack choices and user-declared fabrication capability.

The printed alternative is a holder for bought tips, never printed disposable tips.
No geometry, fit or supplier price is inferred from nominal tip volume.
"""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

TARGET = "tip-rack"
PRINTED_ID = "custom_printed_tip_rack"
PREVIOUS_ID = "previous_tip_rack"
REQUIRED_FIELDS = (
    "body_diameter_max_mm",
    "rim_diameter_min_mm",
    "rim_diameter_max_mm",
    "below_rim_height_mm",
    "count",
    "columns",
)
SOURCE_REVISION = "95a8a37922cfd5f46ad26c983bcc1659fa13b6e1"
PROFILE_HASHES = {
    "tipone_96_tiprack_200ul": "c077e81c6539d40a7c936ea8729aa0e4442240e8980551fc6ae82c662312b31a",
    "opentrons_96_tiprack_300ul": (
        "b2f4fc74c370dfd31d0de6f320ac5c09d6098d02feef51f58091db24718c402c"
    ),
}
PROFILES: dict[str, dict] = {key: {} for key in PROFILE_HASHES}
Number = Annotated[float, Field(strict=True, gt=0, le=300, allow_inf_nan=False)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TipRackSpec(StrictModel):
    """Only fresh tip-holder inputs; absent fields are null, never copied defaults."""

    body_diameter_max_mm: Number | None = None
    rim_diameter_min_mm: Number | None = None
    rim_diameter_max_mm: Number | None = None
    below_rim_height_mm: Number | None = None
    count: Annotated[int, Field(strict=True, ge=1, le=96)] | None = None
    columns: Annotated[int, Field(strict=True, ge=1, le=12)] | None = None
    pitch_mm: Number | None = None
    radial_clearance_mm: Annotated[Number, Field(le=3)] | None = None


class SavedCapabilities(StrictModel):
    printer_available: Literal["unknown", "yes", "no"]
    source: Annotated[str, Field(min_length=1, max_length=1000)] | None = None


class SavedTipRequest(StrictModel):
    profile_id: Annotated[str, Field(max_length=100)] | None = None
    source: Annotated[str, Field(max_length=1000)] | None = None
    alternatives_requested: bool = False
    awaiting_printer: bool = False
    awaiting_placement: bool = False
    spec: TipRackSpec = Field(default_factory=TipRackSpec)
    spec_sources: dict[str, Annotated[str, Field(min_length=1, max_length=1000)]] = Field(
        default_factory=dict
    )


class SavedTipRack(StrictModel):
    schema_version: Literal[1]
    kind: Literal["commercial_reference", "rim_supported_tip_rack"]
    target_component_id: Literal["tip-rack"]
    profile_id: Annotated[str, Field(min_length=1, max_length=100)]
    profile_binding: dict[str, JsonValue] | None = None
    spec: TipRackSpec | None = None
    previous_component: dict[str, JsonValue]
    provenance: dict[str, JsonValue]
    placement_proposal: dict[str, JsonValue] | None = None
    position_xz_mm: Annotated[
        list[Annotated[float, Field(strict=True, ge=-5000, le=5000)]],
        Field(min_length=2, max_length=2),
    ]


class TipRackSources(StrictModel):
    """Literal latest-message sources for fresh dimensions; every unused field is null."""

    body_diameter_max_mm: Annotated[str | None, Field(min_length=1, max_length=1000)] = None
    rim_diameter_min_mm: Annotated[str | None, Field(min_length=1, max_length=1000)] = None
    rim_diameter_max_mm: Annotated[str | None, Field(min_length=1, max_length=1000)] = None
    below_rim_height_mm: Annotated[str | None, Field(min_length=1, max_length=1000)] = None
    count: Annotated[str | None, Field(min_length=1, max_length=1000)] = None
    columns: Annotated[str | None, Field(min_length=1, max_length=1000)] = None
    pitch_mm: Annotated[str | None, Field(min_length=1, max_length=1000)] = None
    radial_clearance_mm: Annotated[str | None, Field(min_length=1, max_length=1000)] = None

    def supplied(self) -> dict[str, str]:
        return self.model_dump(exclude_none=True)


class TipRackUpdate(StrictModel):
    """Fresh tip-rack changes only; comparisons never select profiles or dimensions."""

    profile_id: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=100,
                description="Current product choice only; null for comparisons or unchanged state.",
            ),
        ]
        | None
    ) = None
    source: Annotated[str, Field(min_length=1, max_length=1000)] | None = None
    printer_available: Annotated[
        Literal["unknown", "yes", "no"] | None,
        Field(
            description="New literal present printer declaration only; null when absent, including "
            "recorded yes/no/unknown. A printed-holder request is not a printer declaration."
        ),
    ] = None
    printer_source: Annotated[str, Field(min_length=1, max_length=1000)] | None = None
    spec: TipRackSpec = Field(default_factory=TipRackSpec)
    spec_sources: TipRackSources = Field(default_factory=TipRackSources)

    def verify_sources(self, message: str, *, printer_context: bool = False) -> None:
        if self.profile_id is not None:
            if not self.source or self.source not in message:
                raise ValueError("Tip-rack selection needs a literal span from this message.")
            if self.profile_id not in {*PROFILES, PRINTED_ID, PREVIOUS_ID}:
                raise ValueError("That tip-rack profile has no reviewed geometry adapter.")
            if self.profile_id in PROFILES:
                profile = tip_profile(self.profile_id)
                aliases = profile.get("selection_aliases", [self.profile_id])
                if not any(alias.casefold() in self.source.casefold() for alias in aliases):
                    raise ValueError(
                        "Choose an exact reviewed tip-rack product before changing geometry."
                    )
                related = [
                    clause
                    for clause in intent_clauses(message)
                    if any(alias.casefold() in clause.casefold() for alias in aliases)
                ]
                if any(_noncurrent_choice(clause) for clause in related):
                    raise ValueError(
                        "The full user statement does not authorize this tip-rack choice."
                    )
                _verify_product_variant(profile, related)
            elif any(
                _noncurrent_choice(clause)
                for clause in intent_clauses(message)
                if re.search(r"tips?|rack|holder|puntal|punte|supporto", clause, re.I)
            ):
                raise ValueError("The full user statement does not authorize this tip-rack choice.")
        elif self.source is not None:
            raise ValueError("A tip-rack source needs a profile choice.")
        if self.printer_available is not None:
            if not self.printer_source or self.printer_source not in message:
                raise ValueError("Printer availability needs a literal user declaration.")
            value = declared_printer(self.printer_source, contextual=printer_context)
            full_value = declared_printer(message, contextual=printer_context)
            if value != self.printer_available or full_value != value:
                raise ValueError("Printer availability does not match the user's declaration.")
        elif self.printer_source is not None:
            raise ValueError("A printer source needs an availability declaration.")
        values = self.spec.model_dump(exclude_none=True)
        sources = self.spec_sources.supplied()
        if set(sources) != set(values):
            raise ValueError("Every tip-rack dimension needs its own literal user source.")
        for key, value in values.items():
            literal = sources[key]
            if literal not in message:
                raise ValueError("Tip-rack dimension source must occur in this message.")
            related = [clause for clause in intent_clauses(message) if literal in clause]
            if any(_noncurrent_choice(clause) for clause in related):
                raise ValueError("A negated or hypothetical dimension is not a design input.")
            number = re.search(r"(?<![\w.])([0-9]+(?:[.,][0-9]+)?)\s*(mm|cm)?\b", literal, re.I)
            if not number:
                raise ValueError("Tip-rack dimensions need explicit numbers.")
            expected = float(number[1].replace(",", ".")) * (10 if number[2] == "cm" else 1)
            if expected != value or (key.endswith("_mm") and not number[2]):
                raise ValueError("Tip-rack input must match the stated dimension and unit.")
            role = {
                "body_diameter_max_mm": r"body|corpo|body_diameter",
                "rim_diameter_min_mm": (
                    r"(?:rim|bordo|collar|flang).{0,25}(?:min|minimum|minim)|"
                    r"(?:min|minimum|minim).{0,25}(?:rim|bordo|collar|flang)|rim_diameter_min"
                ),
                "rim_diameter_max_mm": (
                    r"(?:rim|bordo|collar|flang).{0,25}(?:max|maximum|massim)|"
                    r"(?:max|maximum|massim).{0,25}(?:rim|bordo|collar|flang)|rim_diameter_max"
                ),
                "below_rim_height_mm": r"below|under|sotto|below_rim",
                "count": r"count|positions?|holes?|posizion|fori|posti",
                "columns": r"columns?|colonn",
                "pitch_mm": r"pitch|passo|interasse",
                "radial_clearance_mm": r"radial|radiale",
            }[key]
            if not re.search(role, literal, re.I):
                raise ValueError(
                    "The tip-rack dimension source does not identify its physical role."
                )


def intent_clauses(message: str) -> list[str]:
    """Separate requested edits from explicit preservation of unrelated modules."""
    clauses = re.split(
        r"[,;!?\n]|\.(?!\d)|\b(?:and|e|but|ma)\b(?=\s+(?:do not|don't|non|keep|"
        r"preserve|leave|maintain|mantieni|lascia|conserva))",
        message,
        flags=re.I,
    )
    return [
        clause.strip()
        for clause in clauses
        if clause.strip()
        and not re.search(
            r"^\s*(?:keep|preserve|leave|maintain|mantieni|lascia|conserva|do not change|"
            r"don't change|non cambiar\w*)\s+(?:(?:the|all|every|any|my|current|existing|"
            r"il|la|le|i|tutte|tutti|ogni)\s+){0,3}(?:recipe|ricetta|sample|tube|provett|"
            r"plate|piastr|other component|altr\w* component|position|posizione|layout|"
            r"disposizione|"
            r"tip[ -]?rack position)",
            clause,
            re.I,
        )
    ]


def is_tip_only_turn(project: dict, message: str) -> bool:
    """Choose a narrow response protocol only when no other module is being edited."""
    clauses = intent_clauses(message)
    active = " ".join(clauses)
    explicit = bool(
        re.search(
            r"\btip[ _-]*(?:racks?|holders?)\b|porta[ _-]?(?:puntali|punte)|"
            r"(?:holder|rack|supporto).{0,30}(?:tips?|puntali)|"
            r"\bTipOne\b|opentrons_96_tiprack|tipone_96_tiprack",
            active,
            re.I,
        )
    )
    pending = project.get("tip_rack_request", {})
    pending_context = bool(
        pending.get("awaiting_printer")
        or pending.get("awaiting_placement")
        or pending.get("profile_id")
    )
    contextual = pending_context and bool(
        declared_printer(message, contextual=bool(pending.get("awaiting_printer"))) is not None
        or re.search(
            r"body|rim|diamet|bordo|collar|height|altezza|positions?|posizion|"
            r"columns?|colonn|pitch|clearance|dimensions?|misur|print|stampa|"
            r"^\s*(?:yes|sì|si|confirm|confermo|accept|accetto|proceed|procedi)[.! ]*$",
            active,
            re.I,
        )
    )
    if not (explicit or contextual):
        return False
    if re.search(
        r"stock|concentrat|dilut|final.{0,15}volum|volum.{0,15}final|"
        r"\brecipe\b|\bricetta\b|\b(?:sample|tube|tubes|provett\w*|microplate|plate|piastr\w*)\b|"
        r"\b(?:platform|piattaforma|Jubilee|OT-2|OT2|deck|layout|cooling|camera|inspection|"
        r"budget|throughput|assembly|workspace|bench)\b",
        active,
        re.I,
    ):
        return False
    return True


def _verify_product_variant(profile: dict, clauses: list[str]) -> None:
    expected_volume = float(re.search(r"_(\d+)ul$", profile["id"])[1])
    brand = "TipOne" if profile["id"].startswith("tipone") else "Opentrons"
    for clause in clauses:
        after_brand = re.search(re.escape(brand) + r"(.*)", clause, re.I)
        quantity = re.search(
            r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(?:[µμu]l|ml)\b",
            after_brand[1] if after_brand else clause,
            re.I,
        )
        if quantity is None and after_brand:
            quantity = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(?:[µμu]l|ml)\b", clause, re.I)
        if quantity:
            volume = float(quantity[1].replace(",", "."))
            if re.search(r"ml\b", quantity[0], re.I):
                volume *= 1000
            if volume != expected_volume:
                raise ValueError("The requested tip volume has no matching reviewed rack profile.")
        skus = re.findall(r"\b\d{4}-\d{4}\b", clause)
        if any(sku != profile.get("sku") for sku in skus):
            raise ValueError("The requested tip-rack SKU needs a separate reviewed profile.")


def _noncurrent_choice(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:don't|do not|never|non|mai)\s+(?:use|select|switch|change|print|want|"
            r"usa\w*|scegl\w*|selezion\w*|cambia\w*|stampa\w*|voglio)|"
            r"\b(?:later|someday|eventually|future|in futuro|più avanti|if|se|"
            r"hypothetic\w*|ipotetic\w*|would|compare|comparison|recommend\w*|"
            r"confront\w*|consigl\w*|alternativ\w*|compatib\w*)\b",
            text,
            re.I,
        )
    )


def tip_profile(profile_id: str) -> dict:
    if profile_id not in PROFILES:
        raise ValueError("This tip-rack profile has no reviewed geometry adapter.")
    path = Path(__file__).parent / "data" / "tipracks" / (profile_id + ".json")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != PROFILE_HASHES[profile_id]:
        raise ValueError("Pinned tip-rack definition hash mismatch.")
    data = json.loads(raw)
    dims = data["dimensions"]
    length, height, width = dims["xDimension"], dims["zDimension"], dims["yDimension"]
    tipone = profile_id == "tipone_96_tiprack_200ul"
    source_url = (
        "https://github.com/Opentrons/opentrons/blob/"
        + SOURCE_REVISION
        + "/shared-data/labware/definitions/2/"
        + profile_id
        + "/1.json"
    )
    return {
        "id": profile_id,
        "display_name": data["metadata"]["displayName"],
        "supplier": "USA Scientific / TipOne" if tipone else "Opentrons",
        "sku": "1111-0200" if tipone else None,
        "product_url": "https://www.usascientific.com/act"
        if tipone
        else "https://docs.opentrons.com/ot-2/labware/types/",
        "selection_aliases": [profile_id, "TipOne", "1111-0200"]
        if tipone
        else [profile_id, "Opentrons 300", "Opentrons 96 Tip Rack 300"],
        "dimensions_mm": [length, height, width],
        "well_depth_mm": data["wells"]["A1"]["depth"],
        "wells": [
            {
                "label": label,
                "x_mm": data["wells"][label]["x"] - length / 2,
                "z_mm": data["wells"][label]["y"] - width / 2,
                "diameter_mm": data["wells"][label]["diameter"],
            }
            for column in data["ordering"]
            for label in column
        ],
        "source": {
            "source_url": source_url,
            "revision": SOURCE_REVISION,
            "sha256": PROFILE_HASHES[profile_id],
            "checked_on": "2026-10-31",
            "license": "Apache-2.0",
            "license_url": "https://github.com/Opentrons/opentrons/blob/"
            + SOURCE_REVISION
            + "/LICENSE",
            "scope": "Pinned labware software reference rendered schematically; not "
            "manufacturer CAD, fabrication dimensions or verified drop-in fit. "
            "Well depths and coordinates are software parameters.",
        },
    }


def declared_printer(message: str, *, contextual: bool = False) -> str | None:
    text = message.strip().casefold()
    if re.search(
        r"\b(?:future|later|someday|eventually|in futuro|più avanti|comprerò|will buy|will get)\b",
        text,
    ):
        return None
    if re.search(r"\b(?:if|se|would|could|ipotetic|hypothetic)\b|\?", text):
        return None
    has_printer = bool(re.search(r"\bprinter\b|stampante", text))
    if not has_printer:
        if contextual and re.fullmatch(r"(?:no|nope|non ce l'ho|non ancora)[.! ]*", text):
            return "no"
        if contextual and re.fullmatch(
            r"(?:yes|yep|sì|si|certo|sì,? ne ho una|yes,? I have one)[.! ]*", text, re.I
        ):
            return "yes"
        return None
    if re.search(
        r"(?:don't|do not|no longer|non|not)\s+(?:have|own|access|ho|abbiamo|possiedo)|"
        r"senza\s+stampante|no\s+(?:3d\s+)?printer",
        text,
    ):
        return "no"
    if re.search(
        r"(?:have|own|access to|ho|abbiamo|possiedo).{0,35}(?:3d\s+printer|stampante\s*3d)", text
    ):
        return "yes"
    return "unknown" if re.search(r"don't know|do not know|non so|not sure", text) else None


def capability(project: dict) -> str:
    return project.get("fabrication_capabilities", {}).get("printer_available", "unknown")


def option(profile: dict) -> dict:
    return {
        "id": profile["id"],
        "label": profile["display_name"],
        "supplier": profile.get("supplier", "Reviewed catalogue reference"),
        "sku": profile.get("sku"),
        "unit_price": None,
        "price_kind": "unpriced",
        "source_url": profile["source"]["source_url"],
        "checked_on": profile["source"].get("checked_on"),
        "availability": "Supplier availability and exact purchase SKU require confirmation",
        "pros": ["Distinct reviewed geometry profile"],
        "cons": ["Physical fit and pipette compatibility unverified"],
        "compatibility_note": profile["source"].get("scope", "Digital reference only"),
        "geometry": {
            "profile_id": profile["id"],
            "effect": "product_geometry",
            "size_mm": deepcopy(profile["dimensions_mm"]),
            "basis": "Pinned primary-source reference",
            "source": profile["source"],
            "details": {
                "positions": len(profile["wells"]),
                "bore_diameter_mm": profile["wells"][0]["diameter_mm"],
                "first_center_xz_mm": [profile["wells"][0]["x_mm"], profile["wells"][0]["z_mm"]],
            },
        },
    }


def tip_rack_options(project: dict) -> dict:
    from app.foundation_design import is_source_based

    choices = [option(tip_profile(profile_id)) for profile_id in PROFILES]
    if is_source_based(project) and project.get("engineering_design"):
        for choice in choices:
            choice["geometry"]["placement"] = placement_proposal(
                project, choice["geometry"]["size_mm"]
            )
    if capability(project) == "yes":
        choices.append(
            {
                "id": PRINTED_ID,
                "label": "Printed holder for purchased tips",
                "supplier": "Custom fabrication",
                "sku": None,
                "unit_price": None,
                "price_kind": "unpriced",
                "source_url": None,
                "checked_on": None,
                "availability": "Printer availability and mating dimensions required",
                "pros": ["Parametric holder from declared dimensions"],
                "cons": ["Fit coupon and material/process checks required"],
                "compatibility_note": "Disposable tips must be purchased; no printed tips.",
                "geometry": {
                    "profile_id": PRINTED_ID,
                    "effect": "requires_dimensions",
                    "basis": "User-declared physical dimensions; no assumed fit",
                },
            }
        )
    return {
        "revision": project["revision"],
        "component_id": TARGET,
        "selected_profile_id": project.get("tip_rack", {}).get("profile_id"),
        "printer_available": capability(project),
        "supported": is_source_based(project) and bool(project.get("engineering_design")),
        "options": choices,
    }


def update_tip_request(project: dict, update: TipRackUpdate, message: str) -> dict:
    update.verify_sources(
        message, printer_context=bool(project.get("tip_rack_request", {}).get("awaiting_printer"))
    )
    result = deepcopy(project)
    pending = deepcopy(result.get("tip_rack_request", {}))
    contextual = bool(pending.get("awaiting_printer"))
    available = update.printer_available or declared_printer(message, contextual=contextual)
    if available is not None:
        result["fabrication_capabilities"] = {
            "printer_available": available,
            "source": update.printer_source or message[:1000],
        }
        pending.pop("awaiting_printer", None)
    values = update.spec.model_dump(exclude_none=True)
    if values:
        pending["spec"] = {**pending.get("spec", {}), **values}
        pending["spec_sources"] = {
            **pending.get("spec_sources", {}),
            **update.spec_sources.supplied(),
        }
    if update.profile_id:
        pending.update(profile_id=update.profile_id, source=update.source)
    if pending:
        result["tip_rack_request"] = pending
    if result.get("fabrication_capabilities") != project.get(
        "fabrication_capabilities"
    ) or pending != project.get("tip_rack_request", {}):
        result["revision"] += 1
        result["status"] = "draft"
    return result


def show_tip_options(project: dict) -> tuple[dict, dict]:
    result = deepcopy(project)
    result.setdefault("tip_rack_request", {})["alternatives_requested"] = True
    if capability(result) == "unknown":
        result["tip_rack_request"]["awaiting_printer"] = True
    return result, {
        "kind": "show_tip_rack_options",
        "status": "ready",
        "message": "Compare the reviewed tip racks and their actual dimensions below "
        "in this conversation. Exact purchase SKU, pipette fit and prices require checking. "
        + (
            "Do you have access to a 3D printer for a holder for purchased tips?"
            if capability(result) == "unknown"
            else "A printed holder can be developed from your tip dimensions."
            if capability(result) == "yes"
            else "You reported no printer access; choose a commercial rack."
        ),
    }


def _guard(project: dict) -> None:
    from app.engineering import state_for
    from app.foundation_design import is_source_based

    if (
        not is_source_based(project)
        or state_for(project)["selected_platform_id"] == "opentrons-ot2"
    ):
        raise ValueError(
            "Tip-rack alternatives currently support the Jubilee insert only; "
            "this platform has no integrated placement adapter."
        )
    if not project.get("engineering_design"):
        raise ValueError("Accept a Jubilee layout before choosing its tip rack.")


def _checks(project: dict, size: list, x: float, z: float) -> list[dict]:
    index = {p["id"]: p for p in project["design"]["components"]}
    deck = index["base"]
    inside = all(
        abs(value - deck["position"][axis]) + size[axis] / 2 <= deck["size"][axis] / 2 - 10
        for value, axis in ((x, 0), (z, 2))
    )
    checks = [
        {
            "id": "tip_rack_deck_fit",
            "label": "Tip rack deck footprint",
            "passed": inside,
            "detail": "Tip rack needs 10 mm to deck edges.",
        }
    ]
    for cid in ("source-rack", "sample-rack", "tip-waste", "controller", "cold-storage"):
        if cid not in index:
            continue
        other = index[cid]
        clear = (
            abs(x - other["position"][0]) >= (size[0] + other["size"][0]) / 2 + 5
            or abs(z - other["position"][2]) >= (size[2] + other["size"][2]) / 2 + 5
        )
        checks.append(
            {
                "id": f"tip_rack_clearance_{cid}",
                "label": "Tip rack separation",
                "passed": clear,
                "detail": f"Tip rack and {cid} need 5 mm separation.",
            }
        )
    return checks


def placement_proposal(project: dict, size: list) -> dict:
    """Find the closest safe AABB translation, keeping every other part fixed."""
    index = {p["id"]: p for p in project["design"]["components"]}
    part, deck = index[TARGET], index["base"]
    original = [part["position"][0], part["position"][2]]
    xmin = deck["position"][0] - deck["size"][0] / 2 + 10 + size[0] / 2
    xmax = deck["position"][0] + deck["size"][0] / 2 - 10 - size[0] / 2
    zmin = deck["position"][2] - deck["size"][2] / 2 + 10 + size[2] / 2
    zmax = deck["position"][2] + deck["size"][2] / 2 - 10 - size[2] / 2
    xs, zs = {original[0], xmin, xmax}, {original[1], zmin, zmax}
    for cid in ("source-rack", "sample-rack", "tip-waste", "controller", "cold-storage"):
        if cid not in index:
            continue
        other = index[cid]
        xs.update(
            other["position"][0] + sign * ((size[0] + other["size"][0]) / 2 + 5) for sign in (-1, 1)
        )
        zs.update(
            other["position"][2] + sign * ((size[2] + other["size"][2]) / 2 + 5) for sign in (-1, 1)
        )
    candidates = [
        [x, z]
        for x in xs
        for z in zs
        if xmin <= x <= xmax
        and zmin <= z <= zmax
        and all(check["passed"] for check in _checks(project, size, x, z))
    ]
    if not candidates:
        return {
            "status": "unavailable",
            "message": "No safe placement on the current insert; "
            "request a layout revision or choose another rack.",
        }
    selected = min(candidates, key=lambda pos: (math.dist(pos, original), pos[0], pos[1]))
    shift = [selected[i] - original[i] for i in range(2)]
    distance = math.dist(selected, original)
    return {
        "status": "fits" if distance < 1e-8 else "requires_shift",
        "position_xz_mm": selected,
        "shift_xz_mm": shift,
        "shift_mm": distance,
        "message": "Fits at the current tip-rack position."
        if distance < 1e-8
        else f"Requires {distance:.2f} mm tip-rack shift "
        f"(X {shift[0]:+.2f}, Z {shift[1]:+.2f} mm); "
        "all other components stay fixed. Choosing applies this placement proposal as a draft.",
    }


def _sourcing(project: dict) -> None:
    module = project["tip_rack"]
    sourcing = project["sourcing"]
    sourcing["groups"] = [
        group for group in sourcing["groups"] if group["id"] != "tip-rack-options"
    ]
    for group in sourcing["groups"]:
        if TARGET in group["component_ids"]:
            group["component_ids"].remove(TARGET)
    options = tip_rack_options(project)["options"]
    if module["kind"] == "rim_supported_tip_rack":
        if not any(item["id"] == PRINTED_ID for item in options):
            archived = tip_rack_options(
                {**project, "fabrication_capabilities": {"printer_available": "yes"}}
            )["options"][-1]
            archived["availability"] = "Existing holder; printer access currently unavailable"
            options.append(archived)
        for item in options:
            if item["id"] == PRINTED_ID:
                item["geometry"].update(effect="printable_geometry", size_mm=module["size_mm"])
    sourcing["groups"].append(
        {
            "id": "tip-rack-options",
            "label": "Selected tip rack",
            "quantity": 1,
            "component_ids": [TARGET],
            "selected_id": module["profile_id"],
            "options": options,
        }
    )
    sourcing["unpriced_count"] = sum(
        next(o for o in g["options"] if o["id"] == g["selected_id"])["unit_price"] is None
        for g in sourcing["groups"]
    )


def reapply_tip_rack(project: dict, *, require_accepted: bool = True) -> dict:
    if not project.get("tip_rack"):
        return deepcopy(project)
    from app.geometry import add_geometry
    from app.tiprack_geometry import compile_tiprack

    _guard(project)
    result = deepcopy(project)
    module = result["tip_rack"]
    compiled = compile_tiprack(module)
    index = {part["id"]: part for part in result["design"]["components"]}
    part, deck = index[TARGET], index["base"]
    x, z = module["position_xz_mm"]
    checks = _checks(result, compiled["size_mm"], x, z)
    if any(not check["passed"] for check in checks):
        raise ValueError(" ".join(check["detail"] for check in checks if not check["passed"]))
    for key in ("size_mm", "geometry", "derived", "profile"):
        if key in compiled:
            module[key] = deepcopy(compiled[key])
    module["metrics"] = deepcopy(compiled.get("checks", {}))
    module["checks"] = checks
    part.update(
        size=deepcopy(module["size_mm"]),
        label=module.get("profile", {}).get("display_name", "Printed holder for purchased tips"),
        tip_rack_module_id=module["profile_id"],
    )
    part["position"] = [x, deck["position"][1] + deck["size"][1] / 2 + part["size"][1] / 2, z]
    _sourcing(result)
    return add_geometry(result)


def select_tip_rack(
    project: dict, update: TipRackUpdate, message: str, *, accept_placement: bool = False
) -> tuple[dict, dict]:
    from app.tiprack_geometry import compile_tiprack

    _guard(project)
    pending = project.get("tip_rack_request", {})
    profile_id = update.profile_id or pending.get("profile_id")
    if profile_id is None:
        raise ValueError("Choose an exact reviewed tip-rack profile or the printed holder.")
    result = deepcopy(project)
    if profile_id == PREVIOUS_ID:
        module = result.pop("tip_rack", None)
        if not module:
            raise ValueError("There is no earlier tip rack to restore.")
        part = next(p for p in result["design"]["components"] if p["id"] == TARGET)
        part.clear()
        part.update(deepcopy(module["previous_component"]))
        result.pop("tip_rack_request", None)
        from app.geometry import add_geometry
        from app.labware import _sourcing as refresh_sourcing

        refresh_sourcing(result)
        result = add_geometry(result)
    else:
        if profile_id == PRINTED_ID:
            available = capability(result)
            if available != "yes":
                result.setdefault("tip_rack_request", {}).update(profile_id=PRINTED_ID)
                if available == "unknown":
                    result["tip_rack_request"]["awaiting_printer"] = True
                return result, {
                    "kind": "select_tip_rack",
                    "status": "ready",
                    "message": "Do you have access to a 3D printer? We can design a holder for "
                    "purchased tips after you provide its mating dimensions; disposable tips "
                    "will not be printed."
                    if available == "unknown"
                    else "You reported no access to a 3D printer. Choose a commercial tip rack; "
                    "the current rack is preserved.",
                }
            spec = deepcopy(pending.get("spec", {}))
            missing = [key for key in REQUIRED_FIELDS if key not in spec]
            if missing:
                return result, {
                    "kind": "select_tip_rack",
                    "status": "ready",
                    "message": "For the printed holder, provide: " + ", ".join(missing) + ". "
                    "Measure the actual purchased tip's support interface; nominal tip volume "
                    "does not determine fit. A small fit coupon precedes the complete holder.",
                }
            record = {"kind": "rim_supported_tip_rack", "spec": spec}
        else:
            profile = tip_profile(profile_id)
            record = {
                "kind": "commercial_reference",
                "profile_id": profile_id,
                "profile_binding": deepcopy(profile["source"]),
            }
        part = next(p for p in result["design"]["components"] if p["id"] == TARGET)
        previous = result.get("tip_rack", {}).get("previous_component", part)
        old_position = deepcopy(part["position"])
        record.update(
            schema_version=1,
            profile_id=profile_id,
            target_component_id=TARGET,
            previous_component=deepcopy(previous),
            provenance={
                "selection_literal": update.source or pending.get("source", message[:1000]),
                "sources": deepcopy(pending.get("spec_sources", {})),
            },
            position_xz_mm=[old_position[0], old_position[2]],
        )
        size = compile_tiprack(record)["size_mm"]
        placement = placement_proposal(result, size)
        if placement["status"] == "unavailable":
            raise ValueError(
                "The selected tip rack cannot fit with 10 mm deck edges and 5 mm "
                "neighbor clearance on the current insert. Request an explicit "
                "layout revision; the previous project is preserved."
            )
        preserve = bool(
            re.search(
                r"keep.{0,30}(?:rack|position).{0,25}(?:fixed|unchanged)|"
                r"do not move|don't move|non spostare|lascia.{0,30}posizione.{0,20}invariat",
                message,
                re.I,
            )
        )
        if placement["status"] == "requires_shift":
            if preserve:
                raise ValueError(
                    "This profile does not fit at the preserved tip-rack position. "
                    "Allow the stated shift or choose a smaller rack."
                )
            contextual_accept = pending.get("awaiting_placement") and bool(
                re.fullmatch(
                    r"(?:yes|sì|si|confirm|confermo|accept|accetto|proceed|procedi)[.! ]*",
                    message.strip(),
                    re.I,
                )
            )
            if not (accept_placement or pending.get("alternatives_requested") or contextual_accept):
                result.setdefault("tip_rack_request", {}).update(
                    profile_id=profile_id,
                    source=update.source or pending.get("source"),
                    awaiting_placement=True,
                )
                return result, {
                    "kind": "select_tip_rack",
                    "status": "ready",
                    "message": placement["message"]
                    + " Confirm this tip-rack movement to apply the product choice.",
                }
        record["position_xz_mm"] = placement["position_xz_mm"]
        record["placement_proposal"] = placement
        result["tip_rack"] = record
        result = reapply_tip_rack(result)
        result["tip_rack_request"] = {"alternatives_requested": True}
    result["revision"] += 1
    result["status"] = "draft"
    movement = result.get("tip_rack", {}).get("placement_proposal", {}).get("message", "")
    return result, {
        "kind": "select_tip_rack",
        "status": "accepted",
        "message": "Updated tip-rack geometry, component choice and instructions in this draft. "
        "The preparation recipe and other components are preserved. Physical fit, deck "
        "attachment and pipette compatibility still require checking. " + movement,
    }


def tip_rack_inputs(project: dict) -> dict | None:
    if not project.get("tip_rack"):
        return None
    return {
        key: deepcopy(value)
        for key, value in project["tip_rack"].items()
        if key not in {"geometry", "size_mm", "profile", "derived", "checks", "metrics"}
    }


def restore_tip_rack(project: dict, saved: dict) -> dict:
    result = deepcopy(project)
    saved = SavedTipRack.model_validate(saved).model_dump(exclude_none=True)
    previous = saved["previous_component"]
    current = next(p for p in result["design"]["components"] if p["id"] == TARGET)
    if (
        set(previous) != set(current)
        or previous.get("id") != TARGET
        or previous.get("kind") != "tiprack"
        or previous.get("size") != current["size"]
    ):
        raise ValueError("The archived tip rack does not match the supported original component.")
    if saved["kind"] == "commercial_reference" and saved["profile_id"] == PRINTED_ID:
        raise ValueError("The saved tip-rack kind and profile do not match.")
    if saved["kind"] == "rim_supported_tip_rack" and saved["profile_id"] != PRINTED_ID:
        raise ValueError("The saved printed holder has an unsupported profile.")
    if saved.get("profile_id") != PRINTED_ID:
        profile = tip_profile(saved.get("profile_id"))
        if saved.get("profile_binding") != profile["source"]:
            raise ValueError("The saved tip-rack source binding differs from the pinned profile.")
    else:
        TipRackSpec.model_validate(saved.get("spec"))
    result["tip_rack"] = deepcopy(saved)
    return reapply_tip_rack(result)
