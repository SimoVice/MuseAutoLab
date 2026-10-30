"""Chat remains the rack editor, with atomic rejection and no real inference."""

import asyncio
import json
from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient
from test_foundation_storage import source_project
from test_labware import FULL_MESSAGE, FULL_UPDATE, rack_project
from test_model_client import TEST_SETTINGS, valid_response

import app.api as api
import app.chat_actions as chat_actions
from app.labware import LabwareUpdate
from app.model_client import ChatAction, ExtractedTurn, ModelClientError, generate_turn
from app.procurement import refresh_procurement
from app.project_exports import ExportError, _check_coherence


@pytest.fixture
def client():
    api._sessions.clear()
    with TestClient(api.app) as client:
        yield client
    api._sessions.clear()


def install(project):
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    return f"/api/projects/{project['id']}"


def reply(monkeypatch, *, labware=None, actions=None, **kwargs):
    async def model(project, message, history):
        return ExtractedTurn(
            assistant_message="I will check the requested rack inputs.",
            labware=LabwareUpdate.model_validate(labware or {}),
            actions=actions or [],
            **kwargs,
        ), {"total_tokens": 1}

    monkeypatch.setattr(api, "generate_turn", model)


def test_chat_partial_then_completed_dimensions_apply_current_sample_rack(client, monkeypatch):
    original = source_project()
    url = install(original)
    reply(
        monkeypatch,
        labware={"count": 6, "source_count": "6 tubes"},
        actions=[ChatAction(kind="develop_labware", source="rack for 6 tubes")],
    )
    partial = client.post(url + "/messages", json={"message": "Make a rack for 6 tubes"})
    assert partial.status_code == 200
    partial = partial.json()
    assert partial["action_runs"][0]["status"] == "ready"
    assert partial["project"]["design"] == original["design"]
    assert "labware_rack" not in partial["project"]
    reply(
        monkeypatch,
        labware=FULL_UPDATE,
        actions=[ChatAction(kind="develop_labware", source="Develop a rim-supported rack")],
    )
    applied = client.post(url + "/messages", json={"message": FULL_MESSAGE})
    assert applied.status_code == 200
    body = applied.json()
    assert body["action_runs"][0]["status"] == "accepted"
    assert body["project"]["labware_rack"]["spec"]["count"] == 6
    assert body["project"]["labware_rack"]["derived"]["bore_diameter_mm"] == pytest.approx(11.9)
    assert body["project"]["engineering_design"] == original["engineering_design"]


def test_invalid_rack_action_rolls_back_every_fact_and_geometry(client, monkeypatch):
    project = rack_project()
    original = deepcopy(project)
    url = install(project)
    reply(
        monkeypatch,
        labware={
            "rim_diameter_min_mm": 11,
            "source_rim_diameter_min_mm": "rim diameter minimum 11 mm",
        },
        actions=[ChatAction(kind="develop_labware", source="Change rack")],
    )
    result = client.post(
        url + "/messages", json={"message": "Change rack to rim diameter minimum 11 mm"}
    )
    assert result.status_code == 200
    assert result.json()["action_runs"][0]["status"] == "rejected"
    assert result.json()["project"] == original
    assert api._sessions[project["id"]].project == original


def test_existing_rack_dimension_edit_applies_without_requiring_repeated_build_words(
    client, monkeypatch
):
    project = rack_project()
    url = install(project)
    reply(
        monkeypatch,
        labware={
            "count": 12,
            "source_count": "12 positions",
            "columns": 4,
            "source_columns": "4 columns",
        },
    )
    result = client.post(url + "/messages", json={"message": "12 positions in 4 columns"})
    assert result.status_code == 200
    assert result.json()["action_runs"][0]["kind"] == "develop_labware"
    rack = next(
        p for p in result.json()["project"]["design"]["components"] if p["id"] == "sample-rack"
    )
    assert rack["rack_slot_count"] == 12


def test_quantity_edit_and_portable_reopen_keep_custom_rack_and_other_geometry(client, monkeypatch):
    project = rack_project(count=12, columns=4)
    url = install(project)
    reply(monkeypatch, final_volume="500 uL", source_final_volume="500 uL")
    updated = client.post(url + "/messages", json={"message": "Use 500 uL per tube"}).json()[
        "project"
    ]
    assert updated["design"] == project["design"]
    assert updated["labware_rack"] == project["labware_rack"]
    saved = client.get(url + "/snapshot", params={"revision": updated["revision"]})
    assert saved.status_code == 200 and saved.json()["compiler_version"] == "5"
    reopened = client.post(
        "/api/projects/open", content=saved.content, headers={"content-type": "application/json"}
    )
    assert reopened.status_code == 201
    assert reopened.json()["project"]["design"] == updated["design"]
    assert reopened.json()["project"]["labware_rack"] == updated["labware_rack"]


def test_relayout_rechecks_applied_rack_and_failure_keeps_current_project(client, monkeypatch):
    project = rack_project(count=12, columns=4)
    url = install(project)
    old = deepcopy(project)

    async def reposition(candidate, instruction):
        proposal = deepcopy(candidate["engineering_design"]["proposal"])
        sample = next(p for p in proposal["placements"] if p["component_id"] == "sample-rack")
        sample["x_mm"] = 115  # The actual rack exceeds the 10 mm edge margin here.
        # A failed candidate must never be published, even if a model claims acceptance.
        changed = deepcopy(candidate)
        part = next(p for p in changed["design"]["components"] if p["id"] == "sample-rack")
        part["position"][0] += 35
        return changed, {"status": "accepted", "message": "Synthetic attempted relocation"}

    monkeypatch.setattr(chat_actions, "develop_design", reposition)
    reply(monkeypatch, actions=[ChatAction(kind="develop_layout", source="Move rack right")])
    result = client.post(url + "/messages", json={"message": "Move rack right"}).json()
    assert result["action_runs"][0]["status"] == "rejected"
    assert result["project"] == old


def test_old_price_report_and_export_are_stale_after_rack_revision(client, monkeypatch):
    project = source_project()
    url = install(project)
    no_rows = deepcopy(project)
    no_rows["sourcing"]["groups"] = []
    report = asyncio.run(refresh_procurement(no_rows))
    api._sessions[project["id"]].procurement_report = report
    reply(
        monkeypatch,
        labware=FULL_UPDATE,
        actions=[ChatAction(kind="develop_labware", source="Develop a rim-supported rack")],
    )
    result = client.post(url + "/messages", json={"message": FULL_MESSAGE}).json()["project"]
    assert client.get(url + "/procurement", params={"revision": result["revision"]}).json() == {
        "state": "stale_revision",
        "report": None,
    }
    with pytest.raises(ExportError) as error:
        _check_coherence(result, {"project_id": project["id"], "revision": project["revision"]})
    assert error.value.status_code == 409


def test_model_schema_and_context_include_stored_rack_without_reextracting_old_facts():
    project = rack_project()
    captured = {}

    def handler(request):
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json=valid_response(
                assistant_message="The rack has six recorded positions.", labware={}
            ),
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await generate_turn(
                project, "How many positions are there?", [], client=client, settings=TEST_SETTINGS
            )

    turn, _ = asyncio.run(run())
    assert turn.labware.patch() == {} and turn.actions == []
    state = json.loads(captured["messages"][1]["content"].split(": ", 1)[1])
    assert state["labware_rack"]["spec"]["count"] == 6
    assert state["labware_brief"]["sources"]["body_diameter_max_mm"]["literal"]
    schema = captured["response_format"]["json_schema"]["schema"]
    assert "labware" in schema["properties"] and "labware" in schema["required"]


def test_real_model_boundary_rejects_dimensions_invented_from_nominal_ml():
    def handler(request):
        return httpx.Response(
            200,
            json=valid_response(
                labware={
                    "body_diameter_max_mm": 10.8,
                    "source_body_diameter_max_mm": "1.5 mL microcentrifuge tubes",
                }
            ),
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ModelClientError) as error:
                await generate_turn(
                    source_project(),
                    "Use 1.5 mL microcentrifuge tubes",
                    [],
                    client=client,
                    settings=TEST_SETTINGS,
                )
            assert error.value.failure_kind == "source_validation"

    asyncio.run(run())
