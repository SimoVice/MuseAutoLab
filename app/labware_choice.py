"""Conversational recovery for unresolved labware choices, before any mutation.

This does not relax profile or dimensional validation. Callers replace the entire
proposed turn with a reply-only turn when a clarification is returned.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.microplates import noncurrent_plate_choice
from app.tip_racks import PROFILES, TipRackUpdate, delegated_tip_reference, tip_profile

if TYPE_CHECKING:
    from app.model_client import ExtractedTurn


def choice_clarification(
    turn: ExtractedTurn, message: str, project: dict, history: list[dict] | None = None,
) -> str | None:
    """Return an English follow-up for a proposed, ungrounded labware choice."""
    from app.conversation_history import MODEL_HISTORY_LIMIT

    history = (history or [])[-MODEL_HISTORY_LIMIT:]
    actions = {action.kind for action in turn.actions}
    plate = turn.labware_selection
    if plate.profile_id is not None or "select_labware" in actions:
        # Product-only follow-ups need a real offered or selected reference. Never
        # treat arbitrary conversation text as authorization for a default plate.
        product_only = bool(re.search(r"\bcorning\b", message, re.I)) and not re.search(
            r"96\s*[- ]?(?:micro)?well|" + re.escape("corning_96_wellplate_360ul_flat"),
            message, re.I,
        )
        offers = [
            item.get("content", "") for item in history or []
            if item.get("role") == "assistant"
            and re.search(r"corning.{0,60}96|96.{0,60}corning", item.get("content", ""), re.I)
        ]
        offered = bool(offers)
        contextual_request = re.fullmatch(
            r"\s*(?:please\s+)?(?:use|choose|select|go with)\s+"
            r"(?:that one|this one|your reference|that reference|the reference)\s*[.!]?\s*",
            message, re.I,
        )
        if contextual_request:
            recent_assistant = next((item.get("content", "") for item in reversed(history or [])
                                     if item.get("role") == "assistant"), "")
            context = recent_assistant if recent_assistant in offers else None
            if context and re.search(
                r"tipone|thermo|greiner|384|1536|\bot-?2\b|\bor\b", context, re.I,
            ):
                context = None
            if not context:
                return ("Your current labware is unchanged. Which reference do you mean? "
                        "The reviewed plate option is the Corning 96-well "
                        "360 µL flat-bottom plate.")
            plate._reference_context = context[:1000]
        if product_only and not (project.get("labware_plate") or offered):
            return ("Your current labware is unchanged. Do you mean the reviewed Corning "
                    "96-well 360 µL flat-bottom design reference?")
        if noncurrent_plate_choice(message, plate.profile_id):
            return (
                "Your current labware is unchanged. For a plate layout, the reviewed "
                "option is the Corning 96-well 360 µL flat-bottom reference."
            )
        try:
            plate.verify_sources(message)
            if plate.profile_id is None:
                raise ValueError("No plate choice supplied.")
        except ValueError:
            return (
                "Your current labware is unchanged. I can model the Corning 96-well "
                "360 µL flat-bottom reference. This replaceable reference supports a generic "
                "96-well layout; "
                "a different plate family needs its own reviewed adapter."
            )
    tip = turn.tip_rack
    if tip.profile_id is not None or "select_tip_rack" in actions:
        try:
            # Deliberately check only the product choice here. Invalid dimensions,
            # printer declarations and engineering proposals retain their full checks.
            choice = TipRackUpdate(profile_id=tip.profile_id, source=tip.source)
            choice.verify_sources(message)
            if tip.profile_id is None and not project.get("tip_rack_request", {}).get("profile_id"):
                raise ValueError("No tip-rack choice supplied.")
        except ValueError:
            names = [tip_profile(profile)["display_name"] for profile in PROFILES]
            return (
                "Your current tip rack is unchanged. Which product should the design "
                "use? The reviewed options are " + " and ".join(names) + "."
            )
    return None


def explanation_only_turn(turn: ExtractedTurn, message: str) -> ExtractedTurn:
    """Keep contextual model prose, dropping stale edits on explanation-only turns."""
    from app.model_client import ExtractedTurn

    help_request = re.search(
        r"^\s*(?:I (?:don't|don’t|do not) understand|help me understand|"
        r"what (?:are you|were you) asking|explain (?:that|this|your question))\b",
        message, re.I,
    )
    combined_edit = re.search(
        r"(?:\b(?:and|also|then|but|please)\s+|[.!?;]\s*)"
        r"(?:use|switch|change|replace|add|remove)\b",
        message, re.I,
    )
    if help_request and not combined_edit:
        return ExtractedTurn(assistant_message=turn.assistant_message)
    return turn


def _pure_plate_change(message: str) -> bool:
    """Recognize a bounded container-only request, never discard other requirements."""
    from app.model_client import _plate_volume_roles

    if any(role != "nominal" for _, role in _plate_volume_roles(message)):
        return False
    rest = re.sub(r"\b96\s*[- ]?(?:micro)?wells?\b|\b96\s*pozzetti\b", " ", message,
                  flags=re.I)
    for literal, _ in _plate_volume_roles(message):
        rest = rest.replace(literal, " ")
    words = re.findall(r"[\w’']+", rest.casefold())
    allowed = set(
        "maybe i we think want would like prefer please can could you to use switch change replace "
        "the a an my our current existing sample samples from into instead of with for "
        "now rather than tubes tube eppendorf eppendorfs plate plates microplate microplates "
        "flat bottom corning reference standard generic microwell microwells "
        "vorrei usa usare passa passare sostituisci provette provetta piastra una da con "
        "le la al posto delle dei".split()
    )
    return bool(words) and all(word in allowed for word in words)


def supported_plate_request(turn: ExtractedTurn, message: str, project: dict) -> ExtractedTurn:
    """Recover an omitted bounded edit against existing supported geometry.

    Accepted geometry supplies adapter capability, never an expressed platform
    preference. Recovery only adds the reviewed plate choice; other validated
    recipe and workspace deltas remain intact.
    """
    from app.labware import _platform_guard
    from app.microplates import PROFILE_ID, LabwareSelection
    from app.model_client import ChatAction, ExtractedTurn

    try:
        _platform_guard(project, True)
    except (ValueError, KeyError):
        return turn
    # A platform change or another module needs its own interpretation and checks.
    # Do not let a plate default swallow a mixed unsupported hardware request.
    if re.search(
        r"\b(?:jubilee|opentrons|ot[- ]?2|platform|robot|build|buy|camera|arm|"
        r"cooling|refrigerat\w*|gripper|heater|centrifug\w*|add|attach|install|"
        r"connect|remove|restore|return)\b", message, re.I,
    ):
        return turn
    if re.match(
        r"\s*(?:explain|help|tell me|show me|give me|how\b|what\b|why\b)", message, re.I,
    ):
        return turn
    clauses = re.split(r"[;!?\n]|\.(?!\d)", message)
    requests = [clause for clause in clauses if re.search(
        r"\b96\s*[- ]?(?:micro)?(?:well|pozzett)", clause, re.I,
    )]
    if not requests or not any(re.search(
        r"\b(?:use|switch|replace|prefer|want|change|passa|sostituisci|usa|vorrei)\b",
        clause, re.I,
    ) for clause in requests):
        return turn
    if any(re.search(
        r"\b(?:not|don't|don’t|never|non|without|avoid|uncertain|unsure|might|if|but)\b|"
        r"\b(?:I could|thinking about|considering)\b", clause, re.I,
    ) for clause in requests):
        return turn
    candidate = LabwareSelection(profile_id=PROFILE_ID, source=message[:1000])
    try:
        candidate.verify_sources(message)
    except ValueError:
        return turn
    if _pure_plate_change(message):
        # All operative evidence comes from this bounded current request and
        # existing adapter. Discard unrelated model echoes rather than validating
        # paraphrased historical facts as new edits.
        return ExtractedTurn(
            assistant_message=turn.assistant_message, labware_selection=candidate,
            actions=[ChatAction(kind="select_labware", source=candidate.source)],
        )
    # Unknown extra requirements must keep the ordinary model/source-validation
    # path. Only explicitly extracted recipe/width deltas justify a combined edit.
    if not any(getattr(turn, key) is not None for key in (
        "stock_concentration", "target_concentrations", "final_volume", "workspace_width_mm",
    )):
        return turn
    if turn.labware_selection.profile_id is not None or any(
        action.kind not in ("develop_layout", "select_labware") for action in turn.actions
    ):
        return turn
    turn.labware_selection = candidate
    turn.actions = [ChatAction(kind="select_labware", source=candidate.source)]
    # An unrelated re-offering of procurement routes does not replace an
    # existing machine, and a preference is never synthesized from its CAD.
    turn.engineering.options = []
    turn.engineering.platform_choice = None
    turn.engineering.choice_source = None
    return turn


def supported_tip_reference_request(
    turn: ExtractedTurn, message: str, project: dict,
) -> ExtractedTurn:
    """Recover an explicit delegated reference without inventing tip compatibility."""
    from app.model_client import ChatAction, ExtractedTurn
    from app.tip_racks import _guard

    profile_id = delegated_tip_reference(message)
    if profile_id is None:
        return turn
    try:
        _guard(project)
    except (ValueError, KeyError):
        return turn
    selected = (project.get("tip_rack") or {}).get("profile_id")
    explicit_volume = bool(re.search(r"\b(?:200|300)\s*[µμu]l\b", message, re.I))
    if selected and (not explicit_volume or selected == profile_id):
        label = (tip_profile(selected)["display_name"] if selected in PROFILES
                 else "the custom tip holder")
        return ExtractedTurn(assistant_message=(
            f"The current {label} is unchanged. It remains a replaceable design reference; "
            "physical fit and pipette compatibility are unverified. "
            "You can request a specific product change when needed."
        ))
    candidate = TipRackUpdate(profile_id=profile_id, source=message[:1000])
    candidate.verify_sources(message)
    label = tip_profile(profile_id)["display_name"]
    return ExtractedTurn(
        assistant_message=(
            f"I propose the {label} as a replaceable design reference for now. "
            "Its pinned software definition supplies schematic geometry, not verified "
            "physical fit or pipette/tip compatibility. You can change this reference later."
        ),
        tip_rack=candidate,
        actions=[ChatAction(kind="select_tip_rack", source=message[:1000])],
    )
