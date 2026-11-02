"""Source concept discovery does not invent pre-existing laboratory equipment."""

import json
from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient
from foundation_fixtures import source_proposal
from test_model_client import TEST_SETTINGS, valid_response

import app.api as api
import app.design_agent as design_agent
from app.domain import apply_update, new_project
from app.engineering import state_for
from app.project_storage import make_snapshot, restore_snapshot
from app.workflows import has_workstation_design_context

FIRST = (
    "I prepare dilutions and aliquots by hand using 1.5 mL microcentrifuge tubes. "
    "My bench is 800 mm wide."
)
SECOND = (
    "Build the version we assemble ourselves. Design the pipetting workstation "
    "with a source rack, a sample rack, a tip rack and a tip waste bin."
)


def interview_turn():
    return valid_response(
        assistant_message="Compare the buildable Jubilee and assembled OT-2 platforms.",
        workflow_kind="liquid_preparation", source_workflow_kind="prepare dilutions and aliquots",
        brief_process="prepare dilutions and aliquots by hand",
        source_brief_process="prepare dilutions and aliquots by hand",
        brief_materials="1.5 mL microcentrifuge tubes",
        source_brief_materials="1.5 mL microcentrifuge tubes",
        workspace_width_mm=800, source_workspace_width_mm="800 mm",
        engineering={"options": [
            {"platform_id": pid, "reason": "Offline sourced alternative.",
             "tradeoffs": ["Compatibility and setup remain unverified."]}
            for pid in ("jubilee", "opentrons-ot2")
        ]},
    )


def install_offline_models(monkeypatch, *, action=True, compound=False):
    from app.model_client import generate_turn

    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if payload["response_format"]["json_schema"]["name"] == "semantic_platform_choice":
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps({"platform_id": "jubilee",
                                       "source": "Build the version we assemble ourselves."})}}]})
        message = payload["messages"][-1]["content"]
        if message == FIRST:
            return httpx.Response(200, json=interview_turn())
        return httpx.Response(200, json=valid_response(
            assistant_message="Got it, building the workstation now.",
            engineering={"platform_choice": "jubilee", "choice_source": "Jubilee"},
            actions=(([{"kind": "develop_layout", "source": SECOND}] if action else [])
                     + ([{"kind": "confirm", "source": SECOND}] if compound else [])),
        ))

    async def extract(project, message, history):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            return await generate_turn(project, message, history, client=transport,
                                       settings=TEST_SETTINGS)

    async def propose(project, instruction, feedback):
        assert project["summary"]["equipment"] is None
        assert project["brief"]["equipment"] is None
        assert state_for(project)["selected_platform_id"] == "jubilee"
        return source_proposal(), {"model": "offline", "total_tokens": 10}

    monkeypatch.setattr(api, "generate_turn", extract)
    monkeypatch.setattr(design_agent, "propose_layout", propose)
    return requests


@pytest.mark.parametrize("explicit_action", [True, False])
def test_two_turn_source_layout_without_equipment_renders_and_reopens(monkeypatch, explicit_action):
    requests = install_offline_models(monkeypatch, action=explicit_action)
    with TestClient(api.app) as client:
        project = client.post("/api/projects").json()["project"]
        endpoint = f"/api/projects/{project['id']}/messages"
        first = client.post(endpoint, json={"message": FIRST})
        assert first.status_code == 200, first.text
        recorded = first.json()["project"]
        assert recorded["summary"]["equipment"] is None
        assert not recorded.get("engineering_design")
        response = client.post(endpoint, json={"message": SECOND})
        assert response.status_code == 200, response.text
        body = response.json()
        selected = body["project"]
        assert body["action_runs"][0]["status"] == "accepted"
        assert selected["design"]["foundation"]["id"].startswith("jubilee")
        assert selected["engineering_design"]["provenance"]["instruction"] == SECOND
        assert selected["design"]["components"]
        assert any(component.get("geometry") for component in selected["design"]["components"])
        assert selected["summary"]["equipment"] is None
        assert selected["brief"]["equipment"] is None
        assert selected["summary"]["stock_concentration"] is None
        assert selected["plan"]["status"] != "ready"
        assert client.post(f"/api/projects/{project['id']}/confirm").status_code == 422
        reopened, _ = restore_snapshot(json.loads(json.dumps(make_snapshot(selected, []))))
        assert reopened["design"]["components"] == selected["design"]["components"]
        assert reopened["engineering"] == selected["engineering"]
        assert reopened["brief"] == selected["brief"]
        assert reopened["summary"]["equipment"] is None
        assert len(requests) == 3
        api._sessions.pop(project["id"], None)


@pytest.mark.parametrize("missing", ["process", "materials"])
def test_missing_detail_preserves_choice_and_asks_without_success_prose(monkeypatch, missing):
    install_offline_models(monkeypatch)
    with TestClient(api.app) as client:
        project = client.post("/api/projects").json()["project"]
        project_id = project["id"]
        endpoint = f"/api/projects/{project_id}/messages"
        client.post(endpoint, json={"message": FIRST})
        api._sessions[project_id].project["brief"][missing] = None
        response = client.post(endpoint, json={"message": SECOND})
        assert response.status_code == 200, response.text
        body = response.json()
        assert state_for(body["project"])["selected_platform_id"] == "jubilee"
        assert not body["project"].get("engineering_design")
        assert body["action_runs"][0]["needs_context"] is True
        assert body["assistant_message"].endswith("?")
        assert "building" not in body["assistant_message"].lower()
        assert body["assistant_message_origin"] == "canonical_action_state"
        api._sessions.pop(project_id, None)


@pytest.mark.parametrize("change", ["empty", "general", "legacy", "no_choice", "no_materials"])
def test_concept_context_does_not_bypass_unrelated_workflow_or_discovery(change):
    project = apply_update(new_project(), {
        "workflow_kind": "liquid_preparation", "brief_process": "prepare dilutions",
        "brief_materials": "microcentrifuge tubes",
    })
    project["engineering"] = {**state_for(project), "selected_platform_id": "jubilee"}
    if change == "empty":
        project = new_project()
    elif change == "general":
        project["workflow"]["kind"] = "general"
    elif change == "legacy":
        project.pop("workflow")
        project["summary"]["stock_concentration"] = "10 mM"
    elif change == "no_choice":
        project["engineering"]["selected_platform_id"] = None
    else:
        project["brief"]["materials"] = None
    before = deepcopy(project)
    assert not has_workstation_design_context(project)
    assert project == before


def test_direct_endpoint_adopts_chosen_source_without_equipment(monkeypatch):
    install_offline_models(monkeypatch)
    with TestClient(api.app) as client:
        project = client.post("/api/projects").json()["project"]
        project_id = project["id"]
        client.post(f"/api/projects/{project_id}/messages", json={"message": FIRST})
        stored = api._sessions[project_id].project
        stored["engineering"]["selected_platform_id"] = "jubilee"
        stored["engineering"]["selection_source"] = "Build the version we assemble ourselves."
        response = client.post(f"/api/projects/{project_id}/design", json={
            "project_revision": stored["revision"], "instruction": SECOND,
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["design_run"]["status"] == "accepted"
        assert body["project"]["design"]["foundation"]
        assert body["project"]["summary"]["equipment"] is None
        api._sessions.pop(project_id, None)


def test_rejected_compound_action_uses_only_canonical_outcomes(monkeypatch):
    install_offline_models(monkeypatch, compound=True)
    with TestClient(api.app) as client:
        project = client.post("/api/projects").json()["project"]
        project_id = project["id"]
        endpoint = f"/api/projects/{project_id}/messages"
        before = client.post(endpoint, json={"message": FIRST}).json()["project"]
        response = client.post(endpoint, json={"message": SECOND})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["project"] == before
        assert all(run["status"] == "rejected" for run in body["action_runs"])
        assert body["assistant_message"] == "\n\n".join(
            run["message"] for run in body["action_runs"])
        assert "building" not in body["assistant_message"].casefold()
        assert body["assistant_message_origin"] == "canonical_action_state"
        api._sessions.pop(project_id, None)


def test_legacy_layout_restore_still_requires_equipment():
    from evolution_fixtures import layout_project

    project = layout_project()
    project["summary"]["equipment"] = None
    project["brief"]["equipment"] = None
    project["brief"]["materials"] = "microcentrifuge tubes"
    project["engineering"] = {**state_for(project), "selected_platform_id": "jubilee",
                              "selection_source": "Use Jubilee"}
    assert has_workstation_design_context(project)
    with pytest.raises(ValueError, match="recorded design context"):
        restore_snapshot(make_snapshot(project, []))
