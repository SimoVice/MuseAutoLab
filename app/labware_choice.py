"""Conversational recovery for unresolved labware choices, before any mutation.

This does not relax profile or dimensional validation. Callers replace the entire
proposed turn with a reply-only turn when a clarification is returned.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.microplates import noncurrent_plate_choice
from app.tip_racks import PROFILES, TipRackUpdate, tip_profile

if TYPE_CHECKING:
    from app.model_client import ExtractedTurn


def choice_clarification(turn: ExtractedTurn, message: str, project: dict) -> str | None:
    """Return an English follow-up for a proposed, ungrounded labware choice."""
    actions = {action.kind for action in turn.actions}
    plate = turn.labware_selection
    if plate.profile_id is not None or "select_labware" in actions:
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
                "360 µL flat-bottom reference. Which plate format and product should "
                "the design use?"
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
