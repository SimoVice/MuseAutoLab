"""Offline choice recovery preserves the full accepted project."""

import asyncio
from copy import deepcopy

import httpx
import pytest
from test_microplates import before
from test_model_client import TEST_SETTINGS, valid_response

from app.labware_choice import choice_clarification
from app.microplates import PROFILE_ID, LabwareSelection
from app.model_client import ExtractedTurn, generate_turn


def plate_turn(message):
    return ExtractedTurn(
        assistant_message="I changed the plate and redesigned the layout.",
        labware_selection={"profile_id": PROFILE_ID, "source": message},
        actions=[{"kind": "select_labware", "source": message},
                 {"kind": "develop_layout", "source": message}],
    )


@pytest.mark.parametrize("message", [
    "Could we use a 96-well plate?",
    "How tall would the 96-well plate be?",
    "Never mind the 96-well plate. Please leave the tubes in place.",
    "Suppose we used a 96-well plate.",
    "Use a 384-well plate instead of the 96-well plate.",
    "Use a Thermo 96-well plate.",
    "Use a 96-well deep-well plate.",
])
def test_unresolved_plate_choices_return_a_reply_only_turn(message):
    project = {"revision": 7, "design": {"accepted": True}}
    original = deepcopy(project)
    proposed = plate_turn(message)
    reply = choice_clarification(proposed, message, project)
    assert reply and "unchanged" in reply and "Corning" in reply
    recovered = ExtractedTurn(assistant_message=reply)
    recovered.verify_sources(message, project)
    assert not recovered.actions
    assert recovered.labware_selection.profile_id is None
    assert recovered.engineering == ExtractedTurn(assistant_message="Unchanged.").engineering
    assert project == original


@pytest.mark.parametrize("message", [
    "Could you please switch to a 96-well plate?",
    "Would you please use a 96-well plate?",
    "Please replace the tubes with a 96-well plate.",
])
def test_polite_plate_requests_keep_the_original_validation(message):
    turn = plate_turn(message)
    assert choice_clarification(turn, message, {}) is None
    turn.labware_selection.verify_sources(message)


@pytest.mark.parametrize("message", [
    "Could we use a 96-well plate?",
    "How tall would the 96-well plate be?",
    "Never mind the 96-well plate. Please leave the tubes in place.",
])
def test_low_level_plate_validator_still_rejects_noncurrent_choices(message):
    with pytest.raises(ValueError):
        LabwareSelection(profile_id=PROFILE_ID, source="96-well plate").verify_sources(message)


@pytest.mark.parametrize(("message", "profile"), [
    ("Use the other rack.", "tipone_96_tiprack_200ul"),
    ("Use TipOne 1000 uL tips.", "tipone_96_tiprack_200ul"),
    ("Use TipOne SKU 1111-1000.", "tipone_96_tiprack_200ul"),
    ("Use my custom rack.", "unreviewed_rack"),
])
def test_ambiguous_tip_choices_name_actual_reviewed_products(message, profile):
    turn = ExtractedTurn(
        assistant_message="I selected it.",
        tip_rack={"profile_id": profile, "source": message},
        actions=[{"kind": "select_tip_rack", "source": message}],
    )
    reply = choice_clarification(turn, message, {})
    assert reply and "TipOne" in reply and "Opentrons" in reply and "unchanged" in reply


def test_valid_tip_choice_does_not_bypass_dimensional_validation():
    message = "Use TipOne. The body diameter is 12 mm."
    turn = ExtractedTurn(
        assistant_message="I selected it.",
        tip_rack={"profile_id": "tipone_96_tiprack_200ul", "source": "TipOne",
                  "spec": {"body_diameter_max_mm": 10.0},
                  "spec_sources": {"body_diameter_max_mm": "body diameter is 12 mm"}},
    )
    assert choice_clarification(turn, message, {}) is None
    with pytest.raises(ValueError, match="stated dimension"):
        turn.verify_sources(message, {})


@pytest.mark.parametrize("message", [
    "What is the price difference if we use a 384-well plate?",
    "How tall would the 96-well plate be?",
    "Could we use a 96-well plate?",
])
def test_normal_advice_is_left_to_the_model(message):
    turn = ExtractedTurn(assistant_message="Here is the requested comparison.")
    assert choice_clarification(turn, message, {}) is None


def test_withdrawing_plate_and_explicitly_restoring_tubes_is_a_real_return_request():
    message = "Never mind the 96-well plate. Please return to the tubes."
    turn = ExtractedTurn(
        assistant_message="Returning to the tubes.",
        labware_selection={"profile_id": "previous_tube_rack", "source": "return to the tubes"},
        actions=[{"kind": "select_labware", "source": message}],
    )
    assert choice_clarification(turn, message, {}) is None
    turn.labware_selection.verify_sources(message)


@pytest.mark.parametrize("pending", ["awaiting_printer", "awaiting_placement"])
def test_pending_printed_holder_reply_is_not_replaced(pending):
    turn = ExtractedTurn(
        assistant_message="Thanks.",
        actions=[{"kind": "select_tip_rack", "source": "yes"}],
    )
    project = {"tip_rack_request": {"profile_id": "custom_printed_tip_rack", pending: True}}
    assert choice_clarification(turn, "yes", project) is None


@pytest.mark.parametrize("message", [
    "Could we use a 96-well plate?",
    "How tall would the 96-well plate be?",
    "Never mind the 96-well plate. Please leave the tubes in place.",
    "Use a Thermo 96-well plate.",
])
def test_model_pipeline_recovers_without_leaking_a_hidden_layout(message):
    project = before()
    original = deepcopy(project)
    body = valid_response()
    body["choices"][0]["message"]["content"] = plate_turn(message).model_dump_json()

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=body)
        )) as client:
            return await generate_turn(project, message, [], client=client, settings=TEST_SETTINGS)

    result, _ = asyncio.run(run())
    assert not result.actions
    assert result.labware_selection.profile_id is None
    assert "unchanged" in result.assistant_message
    assert project == original
