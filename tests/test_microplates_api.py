"""One-message switches using the real state pipeline and offline model envelopes."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from test_microplates import MESSAGE, before
from test_model_client import TEST_SETTINGS, valid_response

import app.api as api
from app.domain import apply_update
from app.microplates import PROFILE_ID, LabwareSelection
from app.model_client import ChatAction, ExtractedTurn, generate_turn
from app.procurement import refresh_procurement
from app.project_storage import restore_snapshot


@pytest.fixture
def client():
    api._sessions.clear()
    with TestClient(api.app) as client:
        yield client
    api._sessions.clear()


def install(project):
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    return f"/api/projects/{project['id']}"


def model_turn(
    monkeypatch,
    message,
    *,
    volume=None,
    volume_source=None,
    profile=PROFILE_ID,
    source=None,
    with_action=True,
):
    async def model(project, user_message, history):
        assert user_message == message
        selection = LabwareSelection(profile_id=profile, source=source or message)
        return ExtractedTurn(
            assistant_message="I will select the named reference and check the current recipe.",
            labware_selection=selection,
            final_volume=volume,
            source_final_volume=volume_source,
            actions=[ChatAction(kind="select_labware", source=source or message)]
            if with_action
            else [],
        ), {"total_tokens": 1}

    monkeypatch.setattr(api, "generate_turn", model)


def test_one_italian_message_switches_current_200_ul_recipe_without_changing_it(
    client, monkeypatch
):
    project = before(arm=True)
    original = deepcopy(project)
    url = install(project)
    model_turn(monkeypatch, MESSAGE)
    result = client.post(url + "/messages", json={"message": MESSAGE})
    assert result.status_code == 200
    data = result.json()
    assert data["action_runs"][0]["status"] == "accepted"
    assert data["project"]["labware_plate"]["compatibility"]["status"] == "ready"
    assert data["project"]["summary"] == original["summary"]
    assert data["project"]["labware_plate"]["compatibility"]["occupied_wells"] == ["A1", "B1"]
    assert "labware_rack" not in data["project"]


def test_switch_and_explicit_per_well_volume_change_are_one_coherent_turn(client, monkeypatch):
    project = before(volume="2 mL")
    url = install(project)
    message = "Passa a una piastra da 96 pozzetti, con 200 µL per pozzetto"
    model_turn(
        monkeypatch,
        message,
        source="piastra da 96 pozzetti",
        volume="200 µL",
        volume_source="200 µL per pozzetto",
    )
    response = client.post(url + "/messages", json={"message": message})
    assert response.status_code == 200
    result = response.json()["project"]
    assert result["plan"]["status"] == "ready"
    assert result["plan"]["final_volume_ul"] == 200
    assert result["labware_plate"]["compatibility"]["status"] == "ready"
    assert len(result["plan"]["steps"]) == len(project["plan"]["steps"])


@pytest.mark.parametrize(
    "message,capacity",
    [
        ("Switch from Eppendorf 1.5 mL tubes to a 96-well microplate", "1.5 mL"),
        ("Passa da eppendorf 1.5ml a 96 microwells plates.", "1.5ml"),
    ],
)
def test_old_tube_capacity_is_not_a_recipe_delta_even_if_model_mis_scopes_it(
    client, monkeypatch, message, capacity
):
    project = before()
    url = install(project)
    model_turn(monkeypatch, message, volume=capacity, volume_source=capacity)
    result = client.post(url + "/messages", json={"message": message})
    assert result.status_code == 200
    result = result.json()["project"]
    assert result["summary"]["final_volume"] == project["summary"]["final_volume"]
    assert result["plan"]["final_volume_ul"] == 200
    assert result["labware_plate"]["compatibility"]["status"] == "ready"


def test_plate_only_conflict_is_visible_and_volume_only_edit_resolves_it(client, monkeypatch):
    url = install(before(volume="2 mL"))
    model_turn(monkeypatch, MESSAGE)
    selected = client.post(url + "/messages", json={"message": MESSAGE}).json()["project"]
    assert selected["plan"]["status"] == "invalid" and selected["status"] == "draft"
    assert client.post(url + "/confirm").status_code == 422

    async def volume_model(project, message, history):
        return ExtractedTurn(
            assistant_message="I recorded the explicit per-well volume.",
            final_volume="200 uL",
            source_final_volume="200 uL",
        ), {}

    monkeypatch.setattr(api, "generate_turn", volume_model)
    updated = client.post(url + "/messages", json={"message": "Use 200 uL per well"}).json()[
        "project"
    ]
    assert updated["plan"]["status"] == "ready"
    assert updated["labware_plate"]["compatibility"]["status"] == "ready"
    assert updated["design"] == selected["design"]
    assert client.post(url + "/confirm").status_code == 200


def test_source_bound_choice_itself_can_trigger_the_single_bounded_action(client, monkeypatch):
    url = install(before())
    model_turn(monkeypatch, MESSAGE, with_action=False)
    result = client.post(url + "/messages", json={"message": MESSAGE})
    assert result.status_code == 200
    assert [run["kind"] for run in result.json()["action_runs"]] == ["select_labware"]


def test_return_message_and_save_reopen_restore_exact_before_state(client, monkeypatch):
    original = before(arm=True)
    url = install(original)
    model_turn(monkeypatch, MESSAGE)
    selected = client.post(url + "/messages", json={"message": MESSAGE}).json()["project"]
    saved = client.get(url + "/snapshot", params={"revision": selected["revision"]})
    assert saved.status_code == 200 and saved.json()["compiler_version"] == "6"
    reopened = client.post(
        "/api/projects/open", content=saved.content, headers={"content-type": "application/json"}
    )
    assert reopened.status_code == 201
    project = reopened.json()["project"]
    url = f"/api/projects/{project['id']}"
    message = "Torna al precedente rack di provette"
    model_turn(monkeypatch, message, profile="previous_tube_rack")
    returned = client.post(url + "/messages", json={"message": message})
    assert returned.status_code == 200
    assert returned.json()["project"]["design"] == original["design"]
    assert returned.json()["project"]["labware_rack"] == original["labware_rack"]


def test_unsupported_destination_does_not_replace_any_state(client, monkeypatch):
    project = before()
    original = deepcopy(project)
    url = install(project)
    message = "Use a Bio-Rad 96-well PCR plate"
    model_turn(monkeypatch, message, source="96-well")
    response = client.post(url + "/messages", json={"message": message})
    assert response.status_code == 200
    assert response.json()["action_runs"][0]["status"] == "rejected"
    assert response.json()["project"] == original


def test_previous_pricing_report_becomes_stale_for_changed_labware(client, monkeypatch):
    project = before()
    no_rows = deepcopy(project)
    no_rows["sourcing"]["groups"] = []
    report = asyncio.run(refresh_procurement(no_rows))
    url = install(project)
    api._sessions[project["id"]].procurement_report = report
    model_turn(monkeypatch, MESSAGE)
    result = client.post(url + "/messages", json={"message": MESSAGE}).json()["project"]
    assert client.get(url + "/procurement", params={"revision": result["revision"]}).json() == {
        "state": "stale_revision",
        "report": None,
    }


def test_published_two_ml_rack_switches_reversibly_and_quantity_example_keeps_geometry():
    path = Path(__file__).parents[1] / "docs" / "examples" / "parametric-tube-rack-project.json"
    project, _ = restore_snapshot(json.loads(path.read_text(encoding="utf-8")))
    before_200 = apply_update(project, {"final_volume": "200 uL"})
    assert before_200["design"] == project["design"]
    from app.microplates import restore_previous_sample, select_plate

    selected, _ = select_plate(
        before_200, LabwareSelection(profile_id=PROFILE_ID, source=MESSAGE), MESSAGE
    )
    assert selected["plan"]["status"] == "ready"
    assert restore_previous_sample(selected)["design"] == project["design"]


def test_actual_model_boundary_contains_plate_source_and_preserves_capacity_scope():
    message = "Switch from Eppendorf 1.5 mL tubes to a 96-well microplate"
    captured = {}

    def handler(request):
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json=valid_response(
                final_volume="1.5 mL",
                source_final_volume="1.5 mL",
                labware_selection={"profile_id": PROFILE_ID, "source": "96-well microplate"},
                actions=[{"kind": "select_labware", "source": message}],
            ),
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await generate_turn(before(), message, [], client=client, settings=TEST_SETTINGS)

    turn, _ = asyncio.run(run())
    assert turn.final_volume is None and turn.source_final_volume is None
    schema = captured["response_format"]["json_schema"]["schema"]
    assert "labware_selection" in schema["properties"]
