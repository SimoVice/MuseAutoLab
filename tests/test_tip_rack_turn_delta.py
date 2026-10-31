"""Actual rejected model responses and offline fresh-delta contract checks."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from test_microplates import before
from test_model_client import TEST_SETTINGS, valid_response

import app.api as api
from app.model_client import TipRackTurn, _strict_schema, generate_turn
from app.tip_racks import TipRackUpdate, is_tip_only_turn

RECORD = json.loads(
    (Path(__file__).parent / "fixtures" / "tip-rack-source-failures-round2.json").read_text(
        encoding="utf-8"
    )
)


def tip_response(**updates):
    """Synthetic focused-protocol fixture, separate from actual historical responses."""
    body = valid_response()
    body["choices"][0]["message"]["content"] = json.dumps(
        {
            "assistant_message": "Which tip rack would you prefer?",
            "actions": [],
            "tip_rack": {},
            **updates,
        }
    )
    return body


@pytest.mark.parametrize("case", RECORD["cases"], ids=lambda case: case["id"])
def test_recorded_bad_sources_still_reject_without_state_changes(monkeypatch, case):
    project = before()
    if case["printer_available"] == "yes":
        project["fabrication_capabilities"] = {
            "printer_available": "yes",
            "source": "I have a 3D printer",
        }
    original = deepcopy(project)
    api._sessions.clear()
    api._sessions[project["id"]] = api.ProjectSession(project=project)

    async def model(current, message, history):
        def response(request):
            return httpx.Response(200, json=deepcopy(case["response"]))

        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            return await generate_turn(
                current, message, history, client=client, settings=TEST_SETTINGS
            )

    monkeypatch.setattr(api, "generate_turn", model)
    with TestClient(api.app) as client:
        response = client.post(
            f"/api/projects/{project['id']}/messages", json={"message": case["message"]}
        )
    assert response.status_code == 502
    # These actual historical responses used the old broad protocol. The focused
    # protocol now rejects their unrelated namespace keys before source validation.
    assert response.json()["failure_kind"] == "response_format"
    assert api._sessions[project["id"]].project == original
    assert api._sessions[project["id"]].history == []
    api._sessions.clear()


def test_final_developer_contract_and_empty_tip_delta_preserve_recorded_printer(monkeypatch):
    project = before()
    project["fabrication_capabilities"] = {
        "printer_available": "yes",
        "source": "I have a 3D printer",
    }
    original = deepcopy(project)
    api._sessions.clear()
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    captured = {}

    async def model(current, message, history):
        def response(request):
            captured.update(json.loads(request.content))
            return httpx.Response(
                200,
                json=tip_response(
                    assistant_message="Compare the recorded product options.",
                    actions=[{"kind": "show_tip_rack_options", "source": message}],
                    tip_rack={
                        "profile_id": None,
                        "source": None,
                        "printer_available": None,
                        "printer_source": None,
                        "spec": {},
                        "spec_sources": {},
                    },
                ),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            return await generate_turn(
                current, message, history, client=client, settings=TEST_SETTINGS
            )

    monkeypatch.setattr(api, "generate_turn", model)
    with TestClient(api.app) as client:
        response = client.post(
            f"/api/projects/{project['id']}/messages",
            json={"message": "Show alternative tip racks"},
        )
    assert response.status_code == 200
    result = response.json()["project"]
    assert result["fabrication_capabilities"] == original["fabrication_capabilities"]
    assert result["design"] == original["design"]
    assert result["labware_rack"] == original["labware_rack"]
    assert result["summary"] == original["summary"]
    assert result["plan"] == original["plan"]
    assert "tip_rack" not in result
    final_developer = captured["messages"][-2]
    assert final_developer["role"] == "developer"
    assert "tip-rack namespace" in final_developer["content"]
    assert "show_tip_rack_options only" in final_developer["content"]
    assert 'profile_id="custom_printed_tip_rack"' in final_developer["content"]
    assert "Recorded unknown is not a new declaration" in final_developer["content"]
    assert "Optional pitch_mm and radial_clearance_mm MUST be null" in final_developer["content"]
    assert "labware is the separate" in final_developer["content"]
    schema = captured["response_format"]["json_schema"]["schema"]
    assert set(schema["properties"]) == {"assistant_message", "actions", "tip_rack"}
    description = schema["$defs"]["TipRackUpdate"]["properties"]["printer_available"]["description"]
    assert "null when absent" in description
    api._sessions.clear()


@pytest.mark.parametrize(
    "message",
    [
        "Show alternative tip racks",
        "Confronta i portapuntali",
        "Use TipOne 200 uL",
        "Use TipOne 200 uL and do not change the sample plate or recipe.",
        "Usa TipOne 200 uL e non cambiare le provette o la ricetta.",
        "Design a printed holder for purchased tips. Keep the recipe unchanged.",
    ],
)
def test_clear_tip_requests_and_other_module_preservation_choose_focused_protocol(message):
    assert is_tip_only_turn(before(), message)


@pytest.mark.parametrize(
    "message",
    [
        "Use TipOne 200 uL and set final volume to 150 uL.",
        "Usa il portapuntali e cambia la concentrazione stock a 10 mM.",
        "Replace the tip rack and switch the sample tubes to a 96-well plate.",
        "Change the tip rack and choose Jubilee as the platform.",
        "Show tip racks and add a camera.",
    ],
)
def test_mixed_actual_module_changes_keep_broad_protocol(message):
    assert not is_tip_only_turn(before(), message)


def test_pending_printer_and_dimension_answers_are_scoped_but_unrelated_changes_are_not():
    project = before()
    assert not is_tip_only_turn(project, "Yes")
    project["tip_rack_request"] = {"awaiting_printer": True}
    for answer in ("Yes", "No", "Sì", "Non ho una stampante 3D"):
        assert is_tip_only_turn(project, answer)
    assert not is_tip_only_turn(project, "Budget is 5000 EUR")
    project["tip_rack_request"] = {"profile_id": "custom_printed_tip_rack"}
    assert is_tip_only_turn(project, "maximum body diameter 6 mm, 24 positions, 6 columns")
    assert not is_tip_only_turn(project, "Set final volume to 100 uL")


@pytest.mark.parametrize(
    "message",
    [
        "Use TipOne 200 uL; do not change the sample plate or recipe.",
        "Use TipOne 200 uL and do not change the sample plate or recipe.",
        "Usa TipOne 200 uL e non cambiare le provette.",
    ],
)
def test_unrelated_preservation_does_not_negate_explicit_tip_selection(message):
    for source in ("TipOne", message):
        TipRackUpdate(profile_id="tipone_96_tiprack_200ul", source=source).verify_sources(message)


@pytest.mark.parametrize(
    "message",
    [
        "Do not select TipOne 200 uL; keep the recipe unchanged.",
        "Non cambiare TipOne 200 uL; mantieni la ricetta.",
        "Use TipOne 1000 uL",
        "Use 1000 uL TipOne tips",
        "Usa TipOne 1 mL",
        "Use TipOne SKU 1111-0700",
    ],
)
def test_selected_rack_negation_and_conflicting_specific_variant_still_reject(message):
    with pytest.raises(ValueError):
        TipRackUpdate(profile_id="tipone_96_tiprack_200ul", source="TipOne").verify_sources(message)


def test_focused_schema_closes_every_object_and_forbids_unrelated_fields():
    schema = _strict_schema(TipRackTurn)
    assert set(schema["properties"]) == {"assistant_message", "actions", "tip_rack"}
    assert set(schema["required"]) == set(schema["properties"])

    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node.get("properties", {}))
            for item in node.values():
                check(item)
        elif isinstance(node, list):
            for item in node:
                check(item)

    check(schema)
    with pytest.raises(ValueError):
        TipRackTurn.model_validate(
            {
                "assistant_message": "Selected",
                "actions": [],
                "tip_rack": {},
                "labware_selection": {
                    "profile_id": "corning_96_wellplate_360ul_flat",
                    "source": "test",
                },
            }
        )


def test_actual_mixed_turn_payload_retains_broad_schema_and_recipe_field():
    captured = {}

    async def run():
        def response(request):
            captured.update(json.loads(request.content))
            return httpx.Response(
                200,
                json=valid_response(
                    final_volume="150 uL",
                    source_final_volume="150 uL",
                ),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            return await generate_turn(
                before(),
                "Change the tip rack and set final volume to 150 uL",
                [],
                client=client,
                settings=TEST_SETTINGS,
            )

    turn, _ = asyncio.run(run())
    assert turn.final_volume == "150 uL"
    schema = captured["response_format"]["json_schema"]["schema"]
    assert "final_volume" in schema["properties"]
    assert "engineering" in schema["properties"]
    assert "labware_selection" in schema["properties"]


def test_explicit_printed_holder_delta_without_dimensions_asks_specific_inputs(monkeypatch):
    project = before()
    original = deepcopy(project)
    api._sessions.clear()
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    message = "I have a 3D printer. Design a printed holder for purchased tips."

    async def model(current, user_message, history):
        def response(request):
            return httpx.Response(
                200,
                json=tip_response(
                    assistant_message="I will check the holder inputs.",
                    actions=[{"kind": "select_tip_rack", "source": "Design a printed holder"}],
                    tip_rack={
                        "profile_id": "custom_printed_tip_rack",
                        "source": "Design a printed holder for purchased tips",
                        "printer_available": "yes",
                        "printer_source": "I have a 3D printer",
                    },
                ),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            return await generate_turn(
                current, user_message, history, client=client, settings=TEST_SETTINGS
            )

    monkeypatch.setattr(api, "generate_turn", model)
    with TestClient(api.app) as client:
        response = client.post(f"/api/projects/{project['id']}/messages", json={"message": message})
    assert response.status_code == 200
    result = response.json()
    assert result["project"]["tip_rack_request"]["profile_id"] == "custom_printed_tip_rack"
    assert result["project"]["design"] == original["design"]
    for field in (
        "body_diameter_max_mm",
        "rim_diameter_min_mm",
        "rim_diameter_max_mm",
        "below_rim_height_mm",
        "count",
        "columns",
    ):
        assert field in result["assistant_message"]
    assert "tip_rack" not in result["project"]
    api._sessions.clear()
