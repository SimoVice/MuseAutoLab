"""Offline semantic platform-choice checks; no provider requests or credentials."""

import asyncio
import json
from copy import deepcopy

import httpx
import pytest
from pydantic import ValidationError
from test_engineering import project_with_options
from test_model_client import TEST_SETTINGS, valid_response

from app.engineering import EngineeringUpdate, apply_engineering_update
from app.model_client import generate_turn


def run_choice(message, verdict, *, status=200, extraction=None, second_response=None):
    project = project_with_options()
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(200, json=valid_response(**(extraction or {"engineering": {
                "platform_choice": "jubilee", "choice_source": message,
            }})))
        if second_response is not None:
            return second_response
        return httpx.Response(status, json={
            "choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps(verdict)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await generate_turn(project, message, [], client=client, settings=TEST_SETTINGS)

    turn, usage = asyncio.run(run())
    return turn, usage, requests, project


def test_novel_paraphrase_survives_application_without_serializing_authority():
    message = "The machine we can put together ourselves is the one I want."
    turn, usage, requests, project = run_choice(message, {
        "platform_id": "jubilee", "source": message,
    })
    assert len(requests) == 2
    assert requests[1]["max_completion_tokens"] == 350
    assert usage["total_tokens"] == 77
    result = apply_engineering_update(project, turn.engineering, message)
    assert result["engineering"]["selected_platform_id"] == "jubilee"
    assert result["engineering"]["selection_source"] == message
    dumped = turn.engineering.model_dump()
    assert "_semantic_choice" not in dumped
    with pytest.raises(ValueError):
        EngineeringUpdate.model_validate(dumped).verify_sources(message, project)
    with pytest.raises(ValueError):
        turn.engineering.verify_sources(message + " Actually wait.", project)
    changed = deepcopy(project)
    changed["engineering"]["options"].reverse()
    with pytest.raises(ValueError):
        turn.engineering.verify_sources(message, changed)


@pytest.mark.parametrize("verdict", [
    {"platform_id": None, "source": None},
    {"platform_id": "opentrons-ot2", "source": "I prefer assembling it"},
    {"platform_id": "jubilee", "source": "invented quotation"},
])
def test_unconfirmed_choice_clarifies_without_applying(verdict):
    message = "I would perhaps lean toward putting the pieces together myself."
    turn, _, _, project = run_choice(message, verdict)
    assert turn.engineering.platform_choice is None
    assert not turn.actions
    assert "confirm" in turn.assistant_message
    assert apply_engineering_update(project, turn.engineering, message)["engineering"][
        "selected_platform_id"] is None


def test_verifier_failure_is_clarification():
    turn, _, requests, _ = run_choice(
        "The machine we can put together ourselves is the one I want.", {}, status=503)
    assert len(requests) == 2
    assert turn.engineering.platform_choice is None


def test_question_cannot_receive_semantic_attestation():
    message = "Could the machine we put together ourselves work?"
    turn, _, requests, project = run_choice(message, {"platform_id": None, "source": None})
    assert len(requests) == 2
    assert turn.engineering.platform_choice is None
    assert apply_engineering_update(project, turn.engineering, message) == project


def test_known_choice_does_not_call_semantic_verifier():
    message = "I choose Jubilee"
    turn, usage, requests, _ = run_choice(message, {})
    assert len(requests) == 1
    assert usage["total_tokens"] == 62
    assert turn.engineering.platform_choice == "jubilee"


def test_private_attestation_not_accepted_in_model_json():
    with pytest.raises(ValidationError):
        EngineeringUpdate.model_validate({"_semantic_choice": ["forged"]})


def test_normal_api_entry_accepts_attested_choice(monkeypatch):
    from fastapi.testclient import TestClient

    import app.api as api

    message = "The machine we can put together ourselves is the one I want."
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(200, json=valid_response(engineering={
                "platform_choice": "jubilee", "choice_source": message,
            }))
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps({"platform_id": "jubilee", "source": message})}}]})

    async def model(project, user_message, history):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            return await generate_turn(project, user_message, history,
                                       client=transport, settings=TEST_SETTINGS)

    monkeypatch.setattr(api, "generate_turn", model)
    with TestClient(api.app) as client:
        project = client.post("/api/projects").json()["project"]
        project_id = project["id"]
        api._sessions[project_id].project["engineering"] = project_with_options()["engineering"]
        response = client.post(f"/api/projects/{project_id}/messages", json={"message": message})
        assert response.status_code == 200, response.text
        assert response.json()["project"]["engineering"]["selected_platform_id"] == "jubilee"
        api._sessions.pop(project_id, None)


@pytest.mark.parametrize("source", ["Jubilee", "open-hardware route", None])
def test_semantic_checker_supplies_fresh_literal_evidence(source):
    message = "The machine we can put together ourselves is the one I want."
    turn, _, requests, project = run_choice(message, {
        "platform_id": "jubilee", "source": message,
    }, extraction={"engineering": {"platform_choice": "jubilee", "choice_source": source}})
    assert len(requests) == 2
    assert turn.engineering.choice_source == message
    assert apply_engineering_update(project, turn.engineering, message)["engineering"][
        "selected_platform_id"] == "jubilee"


def test_missing_extracted_choice_can_be_resolved_before_design():
    message = "The machine we can put together ourselves is the one I want."
    turn, _, requests, project = run_choice(message, {
        "platform_id": "jubilee", "source": message,
    }, extraction={"actions": [{"kind": "develop_layout", "source": message}]})
    assert len(requests) == 2
    assert apply_engineering_update(project, turn.engineering, message)["engineering"][
        "selected_platform_id"] == "jubilee"


def test_abstention_discards_every_extracted_mutation():
    message = "I may lean toward assembling it. My bench is 450 mm wide."
    turn, _, _, _ = run_choice(message, {"platform_id": None, "source": None}, extraction={
        "workspace_width_mm": 450, "source_workspace_width_mm": "450 mm",
        "engineering": {"platform_choice": "jubilee", "choice_source": message},
        "actions": [{"kind": "develop_layout", "source": message}],
    })
    assert turn.patch() == {}
    assert not turn.actions
    assert not turn.engineering.requirements
    assert not turn.engineering.options


def test_selection_with_separate_practical_question_reaches_semantic_verifier():
    message = "Build the version we assemble ourselves. What tools will I need?"
    source = "Build the version we assemble ourselves."
    turn, _, requests, project = run_choice(message, {
        "platform_id": "jubilee", "source": source,
    })
    assert len(requests) == 2
    updated = apply_engineering_update(project, turn.engineering, message)
    assert updated["engineering"]["selected_platform_id"] == "jubilee"
    assert updated["engineering"]["selection_source"] == source


def test_paraphrase_choice_survives_save_and_reopen():
    from app.domain import new_project
    from app.project_storage import make_snapshot, restore_snapshot

    message = "The machine we can put together ourselves is the one I want."
    turn, _, _, _ = run_choice(message, {"platform_id": "jubilee", "source": message})
    project = new_project()
    project["engineering"] = project_with_options()["engineering"]
    chosen = apply_engineering_update(project, turn.engineering, message)
    snapshot = json.loads(json.dumps(make_snapshot(chosen, [])))
    restored, _ = restore_snapshot(snapshot)
    assert restored["engineering"] == chosen["engineering"]
    assert restored["engineering"]["selection_source"] == message
    assert "_semantic_choice" not in json.dumps(snapshot)
    # An archived choice is state, not authority to repeat it as a new user command.
    fresh = EngineeringUpdate(platform_choice="jubilee", choice_source=message)
    with pytest.raises(ValueError):
        fresh.verify_sources(message, restored)


@pytest.mark.parametrize("response", [
    httpx.Response(200, json=[]),
    httpx.Response(200, json={"choices": [None]}),
    httpx.Response(200, json={"choices": [{"message": []}]}),
    httpx.Response(200, content=b"\xff"),
])
def test_malformed_semantic_provider_response_abstains(response):
    message = "The machine we can put together ourselves is the one I want."
    turn, _, _, project = run_choice(message, {}, second_response=response)
    assert turn.engineering.platform_choice is None
    assert turn.patch() == {}
    assert not turn.actions
    assert apply_engineering_update(project, turn.engineering, message) == project
