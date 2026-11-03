"""Conversational recovery for unresolved labware choices, before any mutation.

This does not relax profile or dimensional validation. Callers replace the entire
proposed turn with a reply-only turn when a clarification is returned.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.microplates import noncurrent_plate_choice
from app.tip_racks import PROFILES, TipRackUpdate, tip_profile

if TYPE_CHECKING:
    from app.model_client import ExtractedTurn


def choice_clarification(
    turn: ExtractedTurn, message: str, project: dict, history: list[dict] | None = None,
) -> str | None:
    """Return an English follow-up for a proposed, ungrounded labware choice."""
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
