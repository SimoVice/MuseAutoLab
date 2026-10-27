"""Exercise the application boundary with synthetic input and a mocked model."""

import pytest
from fastapi.testclient import TestClient

import app.api as api
from app.model_client import ExtractedTurn, ModelClientError


def turn(**changes):
    value = {
        "assistant_message": "I recorded the requested parameters.",
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


def test_health_project_and_unknown_id(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    result = client.post("/api/projects")
    assert result.status_code == 201
    project = result.json()["project"]
    assert project["status"] == "draft"
    assert project["design"]["estimated_cost"]["amount"] == pytest.approx(208.28)
    assert project["sourcing"]["unpriced_count"] > 0
    assert client.post("/api/projects/unknown/messages", json={"message": "Hi"}).status_code == 404


def test_message_updates_design_and_confirmation_requires_complete_inputs(client, monkeypatch):
    replies = iter(
        [
            turn(workspace_width_mm=450),
            turn(
                stock_concentration="10 mM",
                target_concentrations="1 mM, 2 mM",
                final_volume="100 µL",
                equipment="manual pipette and microcentrifuge tubes",
            ),
        ]
    )

    async def fake_model(project, message, history):
        return next(replies)

    monkeypatch.setattr(api, "generate_turn", fake_model)
    project = client.post("/api/projects").json()["project"]
    project_id = project["id"]
    response = client.post(f"/api/projects/{project_id}/messages", json={"message": "45 cm width"})
    assert response.status_code == 200
    resized = response.json()["project"]
    assert resized["summary"]["workspace_width_mm"] == 450
    assert resized["design"]["footprint"]["width_mm"] == 400
    assert resized["revision"] == project["revision"] + 1
    assert client.post(f"/api/projects/{project_id}/confirm").status_code == 422
    response = client.post(
        f"/api/projects/{project_id}/messages", json={"message": "Other details"}
    )
    assert response.status_code == 200
    confirmation = client.post(f"/api/projects/{project_id}/confirm")
    assert confirmation.status_code == 200
    assert confirmation.json()["project"]["status"] == "confirmed"
    assert "does not run" in confirmation.json()["assistant_message"]


def test_infeasible_width_retains_geometry_and_cannot_confirm(client, monkeypatch):
    async def fake_model(project, message, history):
        return turn(workspace_width_mm=300)

    monkeypatch.setattr(api, "generate_turn", fake_model)
    project = client.post("/api/projects").json()["project"]
    result = client.post(f"/api/projects/{project['id']}/messages", json={"message": "30 cm width"})
    body = result.json()
    assert body["project"]["design"]["constraint_status"] == "infeasible"
    assert body["project"]["design"]["footprint"] == project["design"]["footprint"]
    assert "previous geometry is retained" in body["assistant_message"]
    assert client.post(f"/api/projects/{project['id']}/confirm").status_code == 422


def test_model_errors_and_invalid_changes_preserve_project(client, monkeypatch):
    async def failing_model(project, message, history):
        raise ModelClientError("The model failed safely.")

    monkeypatch.setattr(api, "generate_turn", failing_model)
    original = client.post("/api/projects").json()["project"]
    project_id = original["id"]
    response = client.post(f"/api/projects/{project_id}/messages", json={"message": "Change"})
    assert response.status_code == 502
    assert response.json()["detail"] == "The model failed safely."
    assert api._sessions[project_id].project == original
    assert api._sessions[project_id].history == []
    response = client.post(f"/api/projects/{project_id}/messages", json={"message": "   "})
    assert response.status_code == 422


def test_natural_quantity_updates_and_invalid_plan_feedback(client, monkeypatch):
    replies = iter(
        [
            turn(
                stock_concentration="10mg/ml",
                target_concentrations="1, 2 mg/ml",
                final_volume="0,5ml",
                equipment="pipette and tubes",
            ),
            turn(final_volume="250ul"),
            turn(target_concentrations="20mg/ml"),
        ]
    )

    async def fake_model(project, message, history):
        return next(replies)

    monkeypatch.setattr(api, "generate_turn", fake_model)
    project_id = client.post("/api/projects").json()["project"]["id"]
    endpoint = f"/api/projects/{project_id}/messages"
    first = client.post(endpoint, json={"message": "Synthetic task"}).json()
    assert first["project"]["summary"]["stock_concentration"] == "10 mg/mL"
    assert first["project"]["plan"]["status"] == "ready"
    assert "50 µL stock" in first["assistant_message"]
    updated = client.post(endpoint, json={"message": "Make the volume 250ul"}).json()
    assert updated["project"]["plan"]["final_volume_ul"] == 250
    assert updated["project"]["summary"]["stock_concentration"] == "10 mg/mL"
    assert updated["project"]["plan"]["steps"][0]["stock_volume_ul"] == 25
    invalid = client.post(endpoint, json={"message": "Change target to 20mg/ml"}).json()
    assert invalid["project"]["plan"]["status"] == "invalid"
    assert "needs a correction" in invalid["assistant_message"]
    assert "exceeds" in invalid["assistant_message"]
