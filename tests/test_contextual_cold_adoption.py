"""Proposal adoption repairs model misclassification without approving hardware."""

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from test_cold_transfer import plate_project
from test_foundation_storage import source_project

from app import api
from app.cold_transfer import apply_cold_transfer, contextual_cold_transfer_intent
from app.design_workflow import workflow_state
from app.model_client import ChatAction, ExtractedTurn

PROPOSAL = ("I propose a dedicated refrigerator and transfer gripper for the selected "
            "Corning plate. Use the reference components to develop this cold-transfer design.")


def misclassified(message):
    return ExtractedTurn(assistant_message="Please explicitly approve the current machine.",
                         actions=[ChatAction(kind="confirm", source=message)])


@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("message", [
    "go with the plate and cold-transfer design that you proposed",
    "go with the reference components",
])
def test_normal_message_adopts_and_persists_without_approval(
        monkeypatch, tmp_path, active, message):
    monkeypatch.delenv("MUSEAUTOLAB_DATABASE_PATH", raising=False)
    monkeypatch.setenv("MUSEAUTOLAB_LIBRARY_DIRECTORY", str(tmp_path / "library"))
    project = plate_project()
    if active:
        project = apply_cold_transfer(project)
    original = deepcopy(project)
    session = api.ProjectSession(project=project, history=[
        {"role": "user", "content": "Propose plate cold storage."},
        {"role": "assistant", "content": PROPOSAL},
    ])
    api._sessions[project["id"]] = session
    calls = []

    async def model(current, latest, history):
        calls.append((latest, history))
        return misclassified(latest), {"total_tokens": 12}

    monkeypatch.setattr(api, "generate_turn", model)
    with TestClient(api.app) as client:
        path = f"/api/projects/{project['id']}"
        response = client.post(path + "/messages", json={"message": message})
        assert response.status_code == 200, response.text
        body = response.json()
        updated = body["project"]
        assert updated["cold_transfer_extension"]
        assert not workflow_state(updated)["machine_approved"]
        assert updated["revision"] == original["revision"] + (0 if active else 1)
        assert body["action_runs"][0]["status"] == ("ready" if active else "accepted")
        assert "explicitly approve" not in body["assistant_message"]
        assert body["usage"] == {"total_tokens": 12}
        assert calls[0][1][-1]["content"] == PROPOSAL
        assert updated["engineering_design"] == original["engineering_design"]
        api._sessions.pop(project["id"])
        restored = client.get(path)
        assert restored.status_code == 200
        assert restored.json()["project"] == updated
        assert api._sessions[project["id"]].history[-2]["content"] == message
        assert api._sessions[project["id"]].history[-1]["content"] == body["assistant_message"]
    api._sessions.pop(project["id"], None)


@pytest.mark.parametrize("message", [
    "Do not go with the reference components",
    "Should we go with the reference components?",
    "Compare the reference components with alternatives",
    "Go with the reference components if compatible",
    "Go with the reference components and add a camera",
    "Go with the cold-transfer design for tubes",
    "Go with the cold-transfer design at 4 C",
])
def test_contextual_guard_does_not_adopt_extra_or_nonoperative_requests(message):
    assert contextual_cold_transfer_intent(
        misclassified(message), message, plate_project(),
        [{"role": "assistant", "content": PROPOSAL}]) is None


@pytest.mark.parametrize("history", [[], [
    {"role": "assistant", "content": PROPOSAL},
    {"role": "user", "content": "What about the pipette?"},
    {"role": "assistant", "content": "Use these pipette reference components."},
], [{"role": "assistant", "content": "Compare cold-transfer alternatives or manual storage."}],
    [{"role": "assistant", "content": "Cold-transfer is not supported for this request. "
      "Use these reference components for manual storage."}]])
def test_reference_adoption_requires_the_current_unambiguous_proposal(history):
    message = "go with the reference components"
    assert contextual_cold_transfer_intent(
        misclassified(message), message, plate_project(), history) is None


def test_missing_plate_preserves_machine_and_does_not_approve(monkeypatch):
    project = source_project()
    original = deepcopy(project)
    api._sessions[project["id"]] = api.ProjectSession(project=project, history=[
        {"role": "assistant", "content": PROPOSAL}])

    async def model(current, message, history):
        return misclassified(message), {}

    monkeypatch.setattr(api, "generate_turn", model)
    with TestClient(api.app) as client:
        response = client.post(f"/api/projects/{project['id']}/messages", json={
            "message": "go with the reference components"})
    assert response.status_code == 200
    assert response.json()["action_runs"][0]["status"] == "rejected"
    assert response.json()["project"] == original
    assert "96-well" in response.json()["assistant_message"]
    api._sessions.pop(project["id"], None)


def test_explicit_approval_after_old_erroneous_prompt_still_works(monkeypatch):
    project = apply_cold_transfer(plate_project())
    api._sessions[project["id"]] = api.ProjectSession(project=project, history=[
        {"role": "assistant", "content": "Please explicitly approve the current machine."}])

    async def model(current, message, history):
        return misclassified(message), {}

    monkeypatch.setattr(api, "generate_turn", model)
    with TestClient(api.app) as client:
        response = client.post(f"/api/projects/{project['id']}/messages", json={
            "message": "i approve"})
    assert response.status_code == 200, response.text
    assert workflow_state(response.json()["project"])["machine_approved"]
    updated = response.json()["project"]
    assert updated["cold_transfer_extension"] == project["cold_transfer_extension"]
    api._sessions.pop(project["id"], None)


@pytest.mark.parametrize("prior_kind", ["discuss_cold_transfer", "add_cold_transfer"])
def test_actual_canonical_sourcing_reply_allows_reference_adoption(monkeypatch, prior_kind):
    from app.model_client import ColdTransferGrounding

    project = plate_project()
    api._sessions[project["id"]] = api.ProjectSession(project=project)

    async def model(current, message, history):
        if message == "go with the reference components":
            return misclassified(message), {}
        return ExtractedTurn(assistant_message="Model response", actions=[ChatAction(
            kind=prior_kind, source=message,
            cold_transfer=ColdTransferGrounding(
                payload="selected_rigid_plate", destination="dedicated_refrigerated",
                payload_source="prepared plate", destination_source="its own fridge"),
        )]), {}

    monkeypatch.setattr(api, "generate_turn", model)
    with TestClient(api.app) as client:
        path = f"/api/projects/{project['id']}/messages"
        proposal = client.post(path, json={"message": "Give the prepared plate its own fridge."})
        assert proposal.status_code == 200, proposal.text
        assert "Reviewed component candidates" in proposal.json()["assistant_message"]
        revision = proposal.json()["project"]["revision"]
        adopted = client.post(path, json={"message": "go with the reference components"})
        assert adopted.status_code == 200, adopted.text
        body = adopted.json()
        assert body["project"]["cold_transfer_extension"]
        assert not workflow_state(body["project"])["machine_approved"]
        assert body["project"]["revision"] == revision + (prior_kind == "discuss_cold_transfer")
        assert "Preview plate transfer" in body["assistant_message"]
        if prior_kind == "add_cold_transfer":
            assert "Reviewed component candidates" not in body["assistant_message"]
    api._sessions.pop(project["id"], None)


@pytest.mark.parametrize("competing_topic", [False, True])
def test_active_module_recovers_old_failed_approval_only_without_competing_topic(
        monkeypatch, competing_topic):
    project = apply_cold_transfer(plate_project())
    history = [{"role": "assistant", "content": PROPOSAL},
               {"role": "user", "content": "go with the proposed design"},
               {"role": "assistant", "content":
                "Please explicitly approve the current machine after reviewing it. "
                "Questions and hardware changes do not approve a design."}]
    if competing_topic:
        history += [{"role": "user", "content": "What about camera sourcing?"},
                    {"role": "assistant", "content": "Should I add camera or refrigerator?"}]
    message = "go with the reference components"
    intent = contextual_cold_transfer_intent(misclassified(message), message, project, history)
    assert intent == (None if competing_topic else "add")
    api._sessions[project["id"]] = api.ProjectSession(project=project, history=history)

    async def model(current, latest, history):
        return misclassified(latest), {}

    monkeypatch.setattr(api, "generate_turn", model)
    with TestClient(api.app) as client:
        response = client.post(f"/api/projects/{project['id']}/messages", json={"message": message})
    assert response.status_code == 200, response.text
    body = response.json()
    for key in ("revision", "design", "engineering_design", "cold_transfer_extension"):
        assert body["project"][key] == project[key]
    assert not workflow_state(body["project"])["machine_approved"]
    assert body["action_runs"][0]["status"] == ("rejected" if competing_topic else "ready")
    if not competing_topic:
        assert "Preview plate transfer" in body["assistant_message"]
        assert "explicitly approve" not in body["assistant_message"]
    api._sessions.pop(project["id"], None)
