"""Bounded delegated tip references, real HTTP/domain and portable state, offline model."""

from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient
from test_microplates import before
from test_model_client import TEST_SETTINGS
from test_tip_rack_turn_delta import tip_response
from test_tip_racks import OPENTRONS, TIPONE, selected

import app.api as api
from app.labware_choice import supported_tip_reference_request
from app.model_client import ExtractedTurn, generate_turn
from app.project_storage import make_snapshot, restore_snapshot
from app.tip_racks import TipRackUpdate, delegated_tip_reference


@pytest.mark.parametrize(("message", "profile"), [
    ("I don't know the make. Use a reference tip rack for now", OPENTRONS),
    ("Use a reference 200 µL tip rack for now", TIPONE),
    ("Use a reference 300 uL tip rack for now", OPENTRONS),
])
@pytest.mark.parametrize("starting_profile", [None, OPENTRONS])
def test_delegated_reference_through_ordinary_http_and_portable_restore(
    monkeypatch, message, profile, starting_profile,
):
    project = selected(profile=starting_profile) if starting_profile else before()
    original = deepcopy(project)
    api._sessions[project["id"]] = api.ProjectSession(project=project)

    async def model(current, text, history):
        transport = httpx.MockTransport(lambda request: httpx.Response(
            200, json=tip_response(assistant_message="What make is your tip rack?")))
        async with httpx.AsyncClient(transport=transport) as client:
            return await generate_turn(
                current, text, history, client=client, settings=TEST_SETTINGS)

    monkeypatch.setattr(api, "generate_turn", model)
    try:
        with TestClient(api.app) as client:
            response = client.post(f"/api/projects/{project['id']}/messages",
                                   json={"message": message})
        assert response.status_code == 200, response.text
        data = response.json()
        updated = data["project"]
        assert "replaceable design reference" in data["assistant_message"]
        assert "compatibility" in data["assistant_message"]
        assert "What make" not in data["assistant_message"]
        if not updated.get("tip_rack"):
            assert updated["tip_rack_request"]["profile_id"] == profile
            assert updated["tip_rack_request"]["awaiting_placement"]
            pending, _ = restore_snapshot(make_snapshot(updated, []))
            assert pending["tip_rack_request"]["profile_id"] == profile
            with TestClient(api.app) as client:
                approved = client.post(f"/api/projects/{project['id']}/tip-rack-options", json={
                    "revision": updated["revision"], "profile_id": profile,
                })
            assert approved.status_code == 200, approved.text
            updated = approved.json()["project"]
        assert updated["tip_rack"]["profile_id"] == profile
        assert updated["plan"] == original["plan"]
        assert updated["engineering_design"] == original["engineering_design"]
        restored, _ = restore_snapshot(make_snapshot(updated, []))
        assert restored["tip_rack"]["profile_id"] == profile
        assert restored["tip_rack"]["profile_binding"] == updated["tip_rack"]["profile_binding"]
    finally:
        api._sessions.pop(project["id"], None)


@pytest.mark.parametrize("message", [
    "I don't know the make", "Compare reference tip racks", "Don't use a reference tip rack",
    "Use a reference 1000 uL tip rack", "Use a reference 200 uL or 300 uL tip rack",
    "Use a reference Eppendorf tip rack", "Use a printed reference tip rack",
    "Use a custom reference tip rack", "Maybe use a reference tip rack",
    "Use a reference tip rack if it fits", "Use a reference 200 uL tip rack with wide tips",
    "Use a reference tip rack and add a gripper", "Can I use a reference tip rack?",
])
def test_default_does_not_swallow_constraints_or_ambiguous_intent(message):
    assert delegated_tip_reference(message) is None
    turn = ExtractedTurn(assistant_message="Discussing options.")
    assert supported_tip_reference_request(turn, message, before()) is turn


def test_reference_default_preserves_selected_rack_even_when_model_proposes_another():
    project = selected(profile=TIPONE)
    message = "Use a reference tip rack for now"
    turn = ExtractedTurn(assistant_message="Switching.", tip_rack=TipRackUpdate(
        profile_id=OPENTRONS, source=message))
    result = supported_tip_reference_request(turn, message, project)
    assert result.tip_rack.profile_id is None and result.actions == []
    assert "TipOne" in result.assistant_message and "unchanged" in result.assistant_message


def test_explicit_supported_volume_changes_existing_other_volume_reference():
    project = selected(profile=OPENTRONS)
    message = "Use a 200 µL reference tip rack"
    result = supported_tip_reference_request(ExtractedTurn(assistant_message="Draft."), message,
                                             project)
    assert result.tip_rack.profile_id == TIPONE
    assert [action.kind for action in result.actions] == ["select_tip_rack"]
    assert "200" in result.assistant_message and "not verified" in result.assistant_message
    project["tip_rack"] = None
    result = supported_tip_reference_request(ExtractedTurn(assistant_message="Draft."), message,
                                             project)
    assert result.tip_rack.profile_id == TIPONE
