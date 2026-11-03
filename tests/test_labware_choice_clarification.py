"""Offline choice recovery preserves the full accepted project."""

import asyncio
from copy import deepcopy

import httpx
import pytest
from test_microplates import before
from test_model_client import TEST_SETTINGS, valid_response

from app.labware_choice import choice_clarification
from app.microplates import PROFILE_ID, LabwareSelection
from app.model_client import ChatAction, ExtractedTurn, generate_turn


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


@pytest.mark.parametrize("message", [
    "Maybe i want to use 96 microwells plate instead of eppendorfs",
    "I think I would prefer a 96-well plate for this machine.",
])
def test_tentative_current_preference_uses_reviewed_default(message):
    turn = plate_turn(message)
    assert choice_clarification(turn, message, before()) is None
    turn.verify_sources(message, before())


def test_product_followup_requires_offered_or_selected_reference():
    message = "use the corning one"
    turn = plate_turn(message)
    assert choice_clarification(turn, message, before())
    history = [{"role": "assistant", "content":
                "I can use the Corning 96-well 360 µL flat-bottom reference."}]
    assert choice_clarification(turn, message, before(), history) is None
    turn.verify_sources(message, before())


@pytest.mark.parametrize("message", [
    "Don't use the Corning one", "Do not use Corning", "Use not Corning",
    "Maybe later use the Corning one", "Use a Corning 384-well plate",
    "Use the Corning deep-well plate",
])
def test_named_followup_does_not_bypass_unsupported_or_negative_validation(message):
    with pytest.raises(ValueError):
        LabwareSelection(profile_id=PROFILE_ID, source=message).verify_sources(message)


def test_selected_plate_followup_preserves_revision_and_approval():
    from app.microplates import select_plate

    message = "Use a 96-well plate"
    project, _ = select_plate(before(), LabwareSelection(profile_id=PROFILE_ID,
                                                         source=message), message)
    project["status"] = "confirmed"
    original = deepcopy(project)
    message = "use the corning one"
    selection = LabwareSelection(profile_id=PROFILE_ID, source=message)
    assert choice_clarification(plate_turn(message), message, project) is None
    updated, run = select_plate(project, selection, message)
    assert updated == original
    assert run["status"] == "accepted"
    assert "already selected" in run["message"]


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("has_recipe", [False, True])
def test_http_conversation_selects_offered_reference_and_help_preserves_state(
    monkeypatch, legacy, has_recipe,
):
    from fastapi.testclient import TestClient

    import app.api as api

    project = before()
    if not has_recipe:
        for key in ("stock_concentration", "target_concentrations", "final_volume"):
            project["summary"][key] = None
    session = api.ProjectSession(project=project, history=[])
    if legacy:
        session.history = [{"role": "assistant", "content":
                            "I can use the Corning 96-well 360 µL flat reference."}]
    api._sessions[project["id"]] = session
    responses = []
    if not legacy:
        responses.append(plate_turn(
            "Maybe i want to use 96 microwells plate instead of eppendorfs"))
    responses += [plate_turn("use the corning one"), ExtractedTurn(
        assistant_message="I meant the type of plate. The Corning 96-well plate is already "
                          "shown as a replaceable reference; you can keep exploring the machine.")]
    replies = iter(responses)

    async def normal_model(project, message, history):
        body = valid_response()
        body["choices"][0]["message"]["content"] = next(replies).model_dump_json()
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=body))) as model_client:
            return await generate_turn(project, message, history, client=model_client,
                                       settings=TEST_SETTINGS)

    monkeypatch.setattr(api, "generate_turn", normal_model)
    with TestClient(api.app) as client:
        endpoint = f"/api/projects/{project['id']}/messages"
        if not legacy:
            response = client.post(endpoint, json={"message":
                "Maybe i want to use 96 microwells plate instead of eppendorfs"})
            assert response.status_code == 200, response.text
            body = response.json()
            assert "replaceable design reference" in body["assistant_message"]
            selected = deepcopy(body["project"])
        response = client.post(endpoint, json={"message": "use the corning one"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["project"]["labware_plate"]["profile_id"] == PROFILE_ID
        if not legacy:
            assert body["project"] == selected
            assert len(body["assistant_message"].split()) < 20
            assert "already selected" in body["assistant_message"]
            assert "target(s)" not in body["assistant_message"]
        selected = deepcopy(body["project"])
        response = client.post(endpoint, json={
            "message": "i don’t understand what you are asking for"})
        assert response.status_code == 200, response.text
        assert response.json()["project"] == selected
        assert "type of plate" in response.json()["assistant_message"]
    api._sessions.pop(project["id"], None)


def test_chat_summary_omits_empty_recipe_but_full_report_retains_technical_scope():
    from app.microplates import canonical_labware_reply, labware_chat_reply, select_plate

    original = before()
    for key in ("stock_concentration", "target_concentrations", "final_volume"):
        original["summary"][key] = None
    message = "Use a 96-well plate"
    project, run = select_plate(original, LabwareSelection(profile_id=PROFILE_ID,
                                                           source=message), message)
    visible = labware_chat_reply(original, project, [run], {})
    assert "Replaced the tubes in the sample position" in visible
    assert "Corning 96-well 360 µL flat-bottom" in visible
    assert "replaceable design reference" in visible
    assert "0 existing" not in visible
    assert "preparation" not in visible.lower()
    assert "working volume" not in visible
    report = canonical_labware_reply(project, [run], {})
    assert "0 existing target(s)" in report
    assert "Pipette range, holder fit and access remain unverified" in report
    assert labware_chat_reply(project, project, [], {}) is None


def test_chat_summary_preserves_real_volume_conflict():
    from app.microplates import labware_chat_reply, select_plate

    original = before(volume="2 mL")
    message = "Use a 96-well plate"
    project, run = select_plate(original, LabwareSelection(profile_id=PROFILE_ID,
                                                           source=message), message)
    first = labware_chat_reply(original, project, [run], {})
    repeated = labware_chat_reply(project, project, [run], {})
    for visible in (first, repeated):
        assert "2000" in visible
        assert "360" in visible
    assert "already selected" in repeated


@pytest.mark.parametrize("message", ["use that one", "go with your reference"])
def test_contextual_reference_preserves_literal_and_roundtrips(message):
    from app.microplates import select_plate
    from app.project_storage import make_snapshot, restore_snapshot

    project = before()
    offered = "I can use the Corning 96-well 360 µL flat-bottom reference."
    turn = plate_turn(message)
    assert choice_clarification(turn, message, project, [
        {"role": "assistant", "content": offered}]) is None
    turn.verify_sources(message, project)
    selected, _ = select_plate(project, turn.labware_selection, message)
    assert selected["labware_plate"]["provenance"]["selection_literal"] == message
    assert selected["labware_plate"]["provenance"]["selection_context"] == offered
    restored, _ = restore_snapshot(make_snapshot(selected, []))
    assert restored["labware_plate"] == selected["labware_plate"]


@pytest.mark.parametrize("offer", [None,
    "Use the Corning 96-well reference or a Thermo 384-well plate.",
    "We can choose a Jubilee or OT-2 for your Corning 96-well plate.",
])
def test_ambiguous_pronoun_does_not_change_machine(offer):
    message = "use that one"
    history = [{"role": "assistant", "content": offer}] if offer else []
    assert choice_clarification(plate_turn(message), message, before(), history)


@pytest.mark.parametrize("record_preference", [False, True])
@pytest.mark.parametrize("invalid_echo", [False, True])
def test_http_recovers_omitted_plate_action_on_accepted_legacy_geometry(
    monkeypatch, record_preference, invalid_echo,
):
    from fastapi.testclient import TestClient
    from test_design_workflow import hardware

    import app.api as api
    from app.engineering import state_for

    project = hardware()
    if record_preference:
        project["engineering"] = {"requirements": [], "options": [],
            "selected_platform_id": "jubilee", "selection_source": "Use Jubilee"}
    original_preference = state_for(project)
    project_id = project["id"]
    api._sessions[project_id] = api.ProjectSession(project=project)
    message = "Maybe i want to use 96 microwells plate instead of eppendorfs"

    async def omitted_action(project, message, history):
        body = valid_response()
        proposed = ExtractedTurn(
            assistant_message="We can use a Corning 96-well reference. "
                              "Should we build or buy the platform first?",
        )
        if invalid_echo:
            proposed.equipment = "Historical manual pipette"
            proposed.source_equipment = "copied from the previous interview"
            proposed.engineering.platform_choice = "jubilee"
            proposed.engineering.choice_source = "Let's go with Jubilee"
            proposed.labware_selection = LabwareSelection(
                profile_id=PROFILE_ID, source="a paraphrased plate request")
            proposed.actions = [ChatAction(kind="select_labware", source="bad source")]
            proposed = ExtractedTurn.model_validate(proposed.model_dump())
        body["choices"][0]["message"]["content"] = proposed.model_dump_json()
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=body))) as model_client:
            return await generate_turn(project, message, history, client=model_client,
                                       settings=TEST_SETTINGS)

    monkeypatch.setattr(api, "generate_turn", omitted_action)
    try:
        with TestClient(api.app) as client:
            response = client.post(f"/api/projects/{project_id}/messages",
                                   json={"message": message})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["project"]["labware_plate"]["profile_id"] == PROFILE_ID
        assert state_for(result["project"]) == original_preference
        assert "Replaced the tubes" in result["assistant_message"]
        assert "build or buy" not in result["assistant_message"]
    finally:
        api._sessions.pop(project_id, None)


@pytest.mark.parametrize("message", [
    "Could we use a 96-well plate?", "Don't use a 96-well plate",
    "Use a Thermo 96-well plate", "Use a 96-well plate and add a barcode reader",
    "Use a 96-well plate then return to tubes", "Use a 96-well plate on an OT-2",
    "How does a 96-well plate work?", "I don't understand the 96-well plate question",
    "I might use a 96-well plate", "Use a 96-well plate but keep the tubes",
    "Explain how to use a 96-well plate", "Help me use a 96-well plate",
    "Use a 96-well plate with magnetic stirring",
])
def test_omitted_action_recovery_preserves_ambiguous_and_unsupported_requests(message):
    from test_design_workflow import hardware

    from app.labware_choice import supported_plate_request

    turn = ExtractedTurn(assistant_message="Let's discuss this.")
    original = turn.model_dump()
    assert supported_plate_request(turn, message, hardware()).model_dump() == original


def test_plate_recovery_keeps_independent_explicit_recipe_and_constraint_deltas():
    from test_design_workflow import hardware

    from app.labware_choice import supported_plate_request

    message = "Use a 96-well plate; 200 uL per well; maximum width 600 mm"
    turn = ExtractedTurn(assistant_message="Recorded.", final_volume="200 uL",
                         source_final_volume="200 uL", workspace_width_mm=600,
                         source_workspace_width_mm="maximum width 600 mm")
    recovered = supported_plate_request(turn, message, hardware())
    assert recovered.final_volume == "200 uL"
    assert recovered.workspace_width_mm == 600
    assert recovered.labware_selection.profile_id == PROFILE_ID
    assert recovered.actions[0].kind == "select_labware"



def test_http_help_discards_stale_model_plate_and_unrelated_edits(monkeypatch):
    from fastapi.testclient import TestClient
    from test_design_workflow import hardware

    import app.api as api

    project = hardware()
    project_id = project["id"]
    api._sessions[project_id] = api.ProjectSession(project=project)
    explanation = "I meant the plate type: the Corning reference is one possible starting point."

    async def stale_model(current, message, history):
        proposed = ExtractedTurn(
            assistant_message=explanation,
            labware_selection={"profile_id": PROFILE_ID, "source": "old plate request"},
            actions=[{"kind": "select_labware", "source": "old plate request"}],
            equipment="Old pipette", source_equipment="old source",
        )
        body = valid_response()
        body["choices"][0]["message"]["content"] = proposed.model_dump_json()
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=body))) as model_client:
            return await generate_turn(current, message, history, client=model_client,
                                       settings=TEST_SETTINGS)

    monkeypatch.setattr(api, "generate_turn", stale_model)
    try:
        with TestClient(api.app) as client:
            response = client.post(f"/api/projects/{project_id}/messages", json={
                "message": "I don't understand what you are asking for"})
        assert response.status_code == 200, response.text
        assert response.json()["project"] == project
        assert response.json()["assistant_message"] == explanation
        assert not response.json()["action_runs"]
    finally:
        api._sessions.pop(project_id, None)


def test_unrecognized_request_does_not_discard_invalid_model_sources():
    from test_design_workflow import hardware

    from app.labware_choice import explanation_only_turn, supported_plate_request

    message = "Consider a new proprietary workflow from my description"
    turn = ExtractedTurn(assistant_message="Recorded.", equipment="a guessed device",
                         source_equipment="not present in message")
    result = supported_plate_request(explanation_only_turn(turn, message), message, hardware())
    with pytest.raises(ValueError):
        result.verify_sources(message, hardware())


@pytest.mark.parametrize("message", [
    "Use a 96-well plate and explain this choice",
    "I don't understand. Switch to a 96-well plate",
    "Explain this, then change the plate",
])
def test_combined_change_and_explanation_does_not_erase_model_edits(message):
    from app.labware_choice import explanation_only_turn

    turn = plate_turn(message)
    assert explanation_only_turn(turn, message) is turn
    assert turn.actions
