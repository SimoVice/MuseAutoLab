"""Chat evidence completeness without network or inference."""

from copy import deepcopy

import pytest

from app.chat_sourcing import cold_component_reply, complete_platform_comparison
from app.domain import new_project


def test_incidental_pipetting_discovery_has_links_prices_without_repetition():
    current = new_project()
    updated = deepcopy(current)
    updated["workflow"]["kind"] = "liquid_preparation"
    reply = complete_platform_comparison(current, updated, "I dilute samples", "Which tubes?")
    assert "https://jubilee3d.com" in reply and "$1,400" in reply
    assert "https://opentrons.com" in reply and "$15,950" in reply
    assert complete_platform_comparison(current, updated, "I dilute samples", reply) == reply


def test_unrelated_generic_comparison_does_not_force_pipetting_platforms():
    current = new_project()
    reply = complete_platform_comparison(current, current, "Compare optical filters", "Filters")
    assert reply == "Filters"


def test_cold_candidates_available_before_hardware_without_geometry_mutation():
    project = new_project()
    before = deepcopy(project)
    reply = cold_component_reply(project)
    assert "accucold.com" in reply and "$900" in reply and "$2,200" in reply
    assert "servocity.com" in reply and "$300" in reply and "$1,200" in reply
    assert "hudsonrobotics.com" in reply
    assert project == before


def test_selected_route_asks_equipment_once_and_preserves_recorded_details():
    from app.chat_sourcing import complete_equipment_question
    from app.engineering import state_for

    current = new_project()
    updated = deepcopy(current)
    updated["engineering"] = state_for(current)
    updated["engineering"]["selected_platform_id"] = "jubilee"
    updated["engineering"]["selection_source"] = "Jubilee"
    updated["engineering_design"] = {"id": "layout"}
    reply = complete_equipment_question(current, updated, "Layout updated.")
    assert "make/model or part number" in reply
    assert complete_equipment_question(current, updated, reply) == reply
    updated["brief"]["equipment"] = "Eppendorf Research plus with epT.I.P.S. 200 uL tips"
    reply = complete_equipment_question(current, updated, "Recorded equipment.")
    assert reply == "Recorded equipment."


def test_ordinary_api_adds_sources_even_when_model_omits_them(monkeypatch):
    from fastapi.testclient import TestClient

    from app import api
    from app.model_client import ExtractedTurn

    project = new_project()
    api._sessions[project["id"]] = api.ProjectSession(project=project)

    async def model(current, message, history):
        return ExtractedTurn(
            assistant_message="Which tubes do you use?",
            workflow_kind="liquid_preparation", source_workflow_kind=message,
            brief_process=message, source_brief_process=message,
        ), {"total_tokens": 0}

    monkeypatch.setattr(api, "generate_turn", model)
    try:
        with TestClient(api.app) as client:
            response = client.post(f"/api/projects/{project['id']}/messages",
                                   json={"message": "I manually pipette dilutions."})
        assert response.status_code == 200, response.text
        reply = response.json()["assistant_message"]
        assert "https://jubilee3d.com" in reply and "$1,400" in reply
        assert "https://opentrons.com" in reply and "$15,950" in reply
    finally:
        api._sessions.pop(project["id"], None)


@pytest.mark.parametrize("message", [
    "Compare tip racks", "What fridge alternatives are there?",
    "Compare Jubilee tip rack suppliers", "What are the camera options?",
    "Change the supplier of my pipette tips", "Compare robot arm alternatives",
])
def test_component_shopping_does_not_repeat_platform_comparison(message):
    current = new_project()
    current["workflow"]["kind"] = "liquid_preparation"
    assert complete_platform_comparison(current, current, message, "Component advice.") == (
        "Component advice.")


def test_fallback_uses_current_profile_amount_and_per_source_date(monkeypatch):
    from app import chat_sourcing
    from app.platform_profiles import platform_profiles

    profiles = platform_profiles()
    profiles[1]["cost_context"].update(amount=17250, retrieved_at="2026-11-04T12:00:00Z")
    profiles[0]["cost_context"]["checked_on"] = "2026-11-02"
    monkeypatch.setattr(chat_sourcing, "platform_profiles", lambda: profiles)
    current = new_project()
    reply = complete_platform_comparison(current, current, "Compare Jubilee and OT-2", "Routes")
    assert "$17,250" in reply and "$15,950" not in reply
    assert "page retrieved 2026-11-04T12:00:00Z" in reply
    assert "reference reviewed 2026-11-02" in reply


@pytest.mark.parametrize("machine_key", ["engineering_design", "concept_design", "bench_station"])
def test_added_and_changed_components_get_concise_proposals(monkeypatch, machine_key):
    from app import chat_sourcing

    current = {machine_key: {"title": "Existing machine"}, "rows": []}
    row = {"group_id": "camera", "selected_id": "camera-a", "label": "Inspection camera",
           "selected_product_label": "Camera Module 3", "source_url": "https://www.adafruit.com/product/5657",
           "line_total_low_usd": 30, "line_total_high_usd": 100,
           "price_kind": "planning_allowance", "component_ids": ["camera-body"]}
    updated = {**current, "rows": [row]}
    monkeypatch.setattr(chat_sourcing, "build_parts_proposal", lambda p: {"rows": p["rows"]})
    reply = chat_sourcing.complete_component_changes(current, updated, "Camera added.")
    assert "$30–$100" in reply and "https://www.adafruit.com/product/5657" in reply
    assert "Parts & prices" in reply
    assert chat_sourcing.complete_component_changes(current, updated, reply) == reply
    replacement = {**row, "selected_id": "camera-b", "selected_product_label": "New camera"}
    assert "New camera" in chat_sourcing.complete_component_changes(
        updated, {**updated, "rows": [replacement]}, "Product changed.")
    # Price refreshes and recipe-only state changes do not constitute new hardware.
    repriced = {**row, "line_total_low_usd": 40}
    assert chat_sourcing.complete_component_changes(
        updated, {**updated, "rows": [repriced]}, "Recipe updated.") == "Recipe updated."


def test_initial_layout_cold_scopes_and_unchanged_parts_are_not_dumped(monkeypatch):
    from app import chat_sourcing

    row = {"group_id": "cold-transfer-fridge", "selected_id": "fridge",
           "label": "Fridge", "source_url": "https://www.accucold.com/",
           "line_total_low_usd": 900, "line_total_high_usd": 2200,
           "price_kind": "planning_allowance", "component_ids": []}
    monkeypatch.setattr(chat_sourcing, "build_parts_proposal", lambda p: {"rows": p["rows"]})
    assert chat_sourcing.complete_component_changes(
        {"rows": []}, {"engineering_design": {}, "rows": [row]}, "First layout.") == "First layout."
    assert chat_sourcing.complete_component_changes(
        {"engineering_design": {"id": "machine"}, "rows": []},
        {"rows": [row]}, "Cold options already given.") == "Cold options already given."


def test_component_supplement_limits_visible_proposals_and_links_all_parts(monkeypatch):
    from app import chat_sourcing

    rows = [{"group_id": f"part-{i}", "label": f"Part {i}",
             "source_url": f"https://example.org/part-{i}",
             "line_total_low_usd": 20, "line_total_high_usd": 20,
             "price_kind": "verified_supplier", "component_ids": []} for i in range(5)]
    monkeypatch.setattr(chat_sourcing, "build_parts_proposal", lambda p: {"rows": p["rows"]})
    reply = chat_sourcing.complete_component_changes(
        {"bench_station": {"id": "station"}, "rows": []}, {"rows": rows}, "Updated.")
    assert reply.count("for this purchase scope") == 3
    assert "Parts & prices" in reply


def test_equipment_question_waits_for_layout_and_generic_manual_pipette_is_incomplete():
    from app.chat_sourcing import complete_equipment_question
    from app.engineering import state_for

    current = new_project()
    updated = deepcopy(current)
    updated["engineering"] = {**state_for(current), "selected_platform_id": "jubilee"}
    updated["brief"]["equipment"] = "manual pipette"
    reply = "What materials should the machine hold?"
    assert complete_equipment_question(current, updated, reply) == reply
    updated["engineering_design"] = {"id": "developed-layout"}
    reply = complete_equipment_question(current, updated, "Layout updated.")
    assert "make/model or part number" in reply and reply.endswith("?")
    assert complete_equipment_question(updated, updated, "Equipment recorded.") == (
        "Equipment recorded.")
