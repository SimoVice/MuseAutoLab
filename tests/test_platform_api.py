"""General platform API tests with a stubbed model and the real domain."""

import pytest
from fastapi.testclient import TestClient

import app.api as api
from app.model_client import ExtractedTurn


def turn(**changes):
    value = {
        "assistant_message": "Noted. What process should the system handle next?",
        "stock_concentration": None,
        "target_concentrations": None,
        "final_volume": None,
        "equipment": None,
        "workspace_width_mm": None,
        "source_stock_concentration": None,
        "source_target_concentrations": None,
        "source_final_volume": None,
        "source_equipment": None,
        "source_workspace_width_mm": None,
    }
    value.update(changes)
    return ExtractedTurn.model_validate(value), {"total_tokens": 5}


@pytest.fixture
def client():
    api._sessions.clear()
    with TestClient(api.app) as test_client:
        yield test_client
    api._sessions.clear()


def test_general_vial_transport_planning_has_no_stock_request(client, monkeypatch):
    async def fake_model(project, message, history):
        return turn(
            workflow_kind="general",
            brief_objective="move vials between racks",
            brief_process="move vials between racks",
        )

    monkeypatch.setattr(api, "generate_turn", fake_model)
    project_id = client.post("/api/projects").json()["project"]["id"]
    response = client.post(
        f"/api/projects/{project_id}/messages",
        json={"message": "I want to move vials between racks"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "stock" not in body["assistant_message"].lower()
    assert "µL stock" not in body["assistant_message"]
    assert "Calculated preparation" not in body["assistant_message"]


def test_bare_equipment_does_not_enable_liquid_capability(client, monkeypatch):
    async def fake_model(project, message, history):
        return turn(brief_equipment="microscope")

    monkeypatch.setattr(api, "generate_turn", fake_model)
    project_id = client.post("/api/projects").json()["project"]["id"]
    body = client.post(
        f"/api/projects/{project_id}/messages", json={"message": "We use a microscope"}
    ).json()
    workflow = body["project"].get("workflow", {})
    assert workflow.get("design_available") is False
    assert "Calculated preparation" not in body["assistant_message"]
    assert "previous geometry" not in body["assistant_message"].lower()


def test_general_confirm_rejects_and_brief_download_uses_revision_guard(client, monkeypatch):
    async def fake_model(project, message, history):
        return turn(
            workflow_kind="general",
            brief_objective="move vials between racks",
        )

    monkeypatch.setattr(api, "generate_turn", fake_model)
    project_id = client.post("/api/projects").json()["project"]["id"]
    updated = client.post(
        f"/api/projects/{project_id}/messages",
        json={"message": "I want to move vials between racks"},
    ).json()["project"]
    revision = updated["revision"]
    confirm = client.post(f"/api/projects/{project_id}/confirm")
    assert confirm.status_code == 422
    good = client.get(f"/api/projects/{project_id}/brief", params={"revision": revision})
    assert good.status_code == 200
    assert good.headers["content-disposition"] == 'attachment; filename="project-brief.json"'
    assert good.headers["cache-control"] == "no-store"
    payload = good.json()
    assert payload["project_id"] == project_id
    assert payload["project_revision"] == revision
    assert payload["brief"]["objective"] == "move vials between racks"
    assert payload["workflow"]["kind"] == "general"
    bad = client.get(f"/api/projects/{project_id}/brief", params={"revision": revision + 1})
    assert bad.status_code == 409


def test_liquid_route_calculation_still_works(client, monkeypatch):
    replies = iter(
        [
            turn(
                workflow_kind="liquid_preparation",
                stock_concentration="10mg/ml",
                target_concentrations="1, 2 mg/ml",
                final_volume="0,5ml",
                equipment="pipette and tubes",
            ),
        ]
    )

    async def fake_model(project, message, history):
        return next(replies)

    monkeypatch.setattr(api, "generate_turn", fake_model)
    project_id = client.post("/api/projects").json()["project"]["id"]
    body = client.post(
        f"/api/projects/{project_id}/messages",
        json={
            "message": "Prepare 1, 2 mg/ml from 10mg/ml stock, "
            "0,5ml with pipette and tubes for dilution"
        },
    ).json()
    assert body["project"]["plan"]["status"] == "ready"
    assert "Calculated preparation" in body["assistant_message"]
