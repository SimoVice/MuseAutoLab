"""Hardware approval and recipe changes are independent versioned transitions."""

from copy import deepcopy

from fastapi.testclient import TestClient
from test_foundation_storage import source_project
from test_microplates import select

import app.api as api
from app.cold_transfer import apply_cold_transfer
from app.design_workflow import approve_machine, refresh_workflow, workflow_state
from app.domain import apply_update
from app.project_storage import make_snapshot, restore_snapshot


def hardware():
    project = source_project()
    project["generic_sample_capacity"] = 6
    return apply_update(project, dict.fromkeys(
        ("stock_concentration", "target_concentrations", "final_volume")))


def test_plate_and_gripper_before_recipe_then_approval_roundtrip():
    project = apply_cold_transfer(select(hardware()))
    assert project["plan"]["status"] != "ready"
    approved = approve_machine(project)
    assert workflow_state(approved)["machine_approved"]
    assert not workflow_state(approved)["recipe_started"]
    assert approved["status"] == "draft"
    restored, _ = restore_snapshot(make_snapshot(approved, []))
    assert workflow_state(restored)["machine_approved"]
    assert restored["design"] == approved["design"]
    revised = deepcopy(approved)
    revised["design"]["components"][0]["position"][0] += 1
    assert not workflow_state(revised)["machine_approved"]


def test_typed_recipe_is_atomic_and_preserves_approved_hardware():
    original = approve_machine(select(hardware()))
    api._sessions[original["id"]] = api.ProjectSession(project=original)
    client = TestClient(api.app)
    path = f"/api/projects/{original['id']}/program-recipe"
    body = {"project_revision": original["revision"], "stock_concentration": "1 mg/mL",
            "target_concentrations": "0.1 mg/mL, 0.2 mg/mL", "final_volume": "200 uL"}
    invalid = client.post(path, json={**body, "final_volume": "2 mL"})
    assert invalid.status_code == 422
    assert api._sessions[original["id"]].project == original
    response = client.post(path, json=body)
    assert response.status_code == 200, response.text
    updated = response.json()["project"]
    assert updated["plan"]["status"] == "ready"
    assert updated["design"] == original["design"]
    assert updated["design_workflow"]["machine_approved"]
    assert updated["design_workflow"]["recipe_started"]
    assert updated["revision"] > original["revision"]
    assert client.post(path, json=body).status_code == 409


def test_recipe_requires_approval_and_approval_rejects_empty_design():
    project = hardware()
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    client = TestClient(api.app)
    response = client.post(f"/api/projects/{project['id']}/program-recipe", json={
        "project_revision": project["revision"], "stock_concentration": "1 mg/mL",
        "target_concentrations": "0.1 mg/mL", "final_volume": "200 uL"})
    assert response.status_code == 409
    empty = api.new_project()
    api._sessions[empty["id"]] = api.ProjectSession(project=empty)
    response = client.post(f"/api/projects/{empty['id']}/approve-machine",
                           json={"project_revision": empty["revision"]})
    assert response.status_code == 422


def test_general_machine_approval_is_bound_to_hardware():
    project = api.new_project()
    project["concept_design"] = {"proposal": {"name": "Custom mixer"}}
    approved = approve_machine(project)
    assert workflow_state(approved)["machine_approved"]
    revised = deepcopy(approved)
    revised["concept_design"]["proposal"]["name"] = "Changed mixer"
    assert not refresh_workflow(revised)["design_workflow"]["machine_approved"]


def test_chat_approval_then_recipe_does_not_regenerate_machine(monkeypatch):
    from test_api import turn

    project = hardware()
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    replies = iter([
        turn(actions=[{"kind": "confirm", "source": "OK this is the machine I want"}]),
        turn(stock_concentration="1 mg/mL", target_concentrations="0.1 mg/mL",
             final_volume="200 uL", actions=[{"kind": "develop_layout", "source": "recipe"}]),
    ])

    async def fake_model(*args):
        return next(replies)

    monkeypatch.setattr(api, "generate_turn", fake_model)
    client = TestClient(api.app)
    path = f"/api/projects/{project['id']}/messages"
    approved = client.post(path, json={"message": "OK this is the machine I want"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["project"]["design_workflow"]["machine_approved"]
    updated = client.post(path, json={"message": "Use 1 mg/mL stock, 0.1 mg/mL target, 200 uL"})
    assert updated.status_code == 200, updated.text
    result = updated.json()["project"]
    assert result["design"] == project["design"]
    assert result["design_workflow"]["machine_approved"]
    assert result["plan"]["status"] == "ready"


def test_after_approval_invalid_chat_recipe_rolls_back_atomically(monkeypatch):
    from test_api import turn

    project = approve_machine(select(source_project()))
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    baseline = deepcopy(project)

    async def fake_model(*args):
        return turn(final_volume="2 mL")

    monkeypatch.setattr(api, "generate_turn", fake_model)
    response = TestClient(api.app).post(f"/api/projects/{project['id']}/messages",
                                       json={"message": "Use 2 mL per well"})
    assert response.status_code == 422
    assert api._sessions[project["id"]].project == baseline
    assert workflow_state(api._sessions[project["id"]].project)["machine_approved"]


def test_legacy_confirmed_session_reads_preserve_revision():
    project = approve_machine(source_project())
    project.pop("machine_approval")
    project.pop("design_workflow")
    revision = project["revision"]
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    for _ in range(3):
        current = api.session_for(project["id"]).project
        assert current["revision"] == revision
        assert workflow_state(current)["machine_approved"]


def test_general_machine_rejects_liquid_recipe_route_and_price_data_does_not_revoke():
    project = api.new_project()
    project["workflow"]["kind"] = "general"
    project["concept_design"] = {"proposal": {"name": "Mixer"}}
    project = approve_machine(project)
    project["design"]["estimated_cost"] = {"amount": 999, "currency": "USD"}
    project["procurement_report"] = {"rows": []}
    assert workflow_state(project)["machine_approved"]
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    response = TestClient(api.app).post(f"/api/projects/{project['id']}/program-recipe", json={
        "project_revision": project["revision"], "stock_concentration": "1 mg/mL",
        "target_concentrations": "0.1 mg/mL", "final_volume": "200 uL"})
    assert response.status_code == 409
    assert workflow_state(api._sessions[project["id"]].project)["machine_approved"]


def test_confirmed_snapshot_cannot_claim_software_readiness_without_recipe():
    import pytest

    snapshot = make_snapshot(approve_machine(hardware()), [])
    snapshot["status"] = "confirmed"
    with pytest.raises(ValueError, match="ready recipe"):
        restore_snapshot(snapshot)


def test_generic_hardware_recipe_keeps_capacity_and_reopens():
    project = approve_machine(hardware())
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    client = TestClient(api.app)
    reply = client.post(f"/api/projects/{project['id']}/program-recipe", json={
        "project_revision": project["revision"], "stock_concentration": "5 mg/mL",
        "target_concentrations": "0.5 and 0.25 mg/mL", "final_volume": "200 uL"})
    assert reply.status_code == 200, reply.text
    updated = reply.json()["project"]
    assert updated["design"] == project["design"]
    assert workflow_state(updated)["machine_approved"]
    restored, _ = restore_snapshot(make_snapshot(updated, []))
    assert restored["design"] == project["design"]
    assert workflow_state(restored)["machine_approved"]


def test_legacy_hardware_snapshots_keep_original_rack_capacity():
    project = apply_update(source_project(), dict.fromkeys(
        ("stock_concentration", "target_concentrations", "final_volume")))
    assert "generic_sample_capacity" not in project
    restored, _ = restore_snapshot(make_snapshot(project, []))
    assert restored["design"] == project["design"]
    assert "generic_sample_capacity" not in restored


def test_generic_chat_approval_and_modify_question_guards(monkeypatch):
    from test_api import turn

    project = api.new_project()
    project["workflow"]["kind"] = "general"
    project["concept_design"] = {"proposal": {"name": "Mixer"}}
    api._sessions[project["id"]] = api.ProjectSession(project=project)

    async def fake_model(current, message, history):
        return turn(actions=[{"kind": "confirm", "source": message}])

    monkeypatch.setattr(api, "generate_turn", fake_model)
    client = TestClient(api.app)
    path = f"/api/projects/{project['id']}/messages"
    for text in ("Should I approve it?", "OK, add a camera", "Do not approve yet",
                 "Yes, I have a 3D printer", "I never approved this machine"):
        reply = client.post(path, json={"message": text})
        assert reply.status_code == 200, reply.text
        assert not workflow_state(reply.json()["project"])["machine_approved"]
    reply = client.post(path, json={"message": "This is the machine I want. Let's program it."})
    assert reply.status_code == 200, reply.text
    assert workflow_state(reply.json()["project"])["machine_approved"]
