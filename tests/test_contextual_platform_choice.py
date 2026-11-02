"""Offline regressions for an offered platform choice and design in one turn."""

import asyncio
from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient
from foundation_fixtures import source_proposal

import app.api as api
import app.design_agent as design_agent
from app.domain import apply_update, new_project
from app.engineering import EngineeringUpdate, state_for
from app.model_client import ExtractedTurn, ModelClientError, ModelSettings, generate_turn

MESSAGE = (
    "Let's go with the open platform. Design the pipetting workstation for "
    "microcentrifuge tubes, with a source rack, a sample rack, a tip rack and a tip "
    "waste bin. Start with pipetting only."
)
SETTINGS = ModelSettings("offline-key", "https://example.invalid/v1", "offline")


def compared_project(ids=("jubilee", "opentrons-ot2")):
    project = apply_update(new_project(), {
        "workflow_kind": "liquid_preparation", "equipment": "pipette and tubes",
    })
    project["engineering"] = {
        **state_for(project),
        "options": [{"platform_id": pid, "reason": "Offline comparison.",
                     "tradeoffs": ["Integration remains unverified."]} for pid in ids],
    }
    return project


def run_extraction(project, message, turn):
    calls = []

    def handler(request):
        calls.append(request)
        content = (turn.model_dump_json() if len(calls) == 1 else
                   '{"platform_id":null,"source":null}')
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": content,
        }}], "usage": {"total_tokens": 12}})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await generate_turn(project, message, [], client=client, settings=SETTINGS)
    return asyncio.run(run())


@pytest.mark.parametrize("source", ["open platform", "Jubilee"])
def test_offered_open_platform_choice_accepts_literal_or_named_model_citation(source):
    project = compared_project()
    before = deepcopy(project)
    turn = ExtractedTurn(assistant_message="Developing the selected platform.",
                         engineering=EngineeringUpdate(platform_choice="jubilee",
                                                       choice_source=source))
    extracted, usage = run_extraction(project, MESSAGE, turn)
    extracted.engineering.verify_sources(MESSAGE, project)
    assert extracted.engineering.choice_source in MESSAGE
    assert extracted.engineering.platform_choice == "jubilee"
    assert usage["total_tokens"] == 12
    assert project == before


@pytest.mark.parametrize("message,ids,choice,source", [
    (MESSAGE, (), "jubilee", "Jubilee"),
    ("Yes, design it", ("jubilee", "opentrons-ot2"), "jubilee", "Jubilee"),
    ("Maybe later use the open platform", ("jubilee",), "jubilee", "Jubilee"),
    ("Should I choose the open platform?", ("jubilee",), "jubilee", "Jubilee"),
    ("Could we use the open platform?", ("jubilee",), "jubilee", "open platform"),
    ("If we choose the open platform, design a workstation", ("jubilee",),
     "jubilee", "open platform"),
    ("Compare the open platform and decide whether to use it", ("jubilee",),
     "jubilee", "open platform"),
    ("Choose the second option, the open platform", ("jubilee", "opentrons-ot2"),
     "jubilee", "open platform"),
    ("Choose the second option, the open platform", ("jubilee", "opentrons-ot2"),
     "opentrons-ot2", "second option"),
    ("Do not choose the open platform", ("jubilee",), "jubilee", "open platform"),
    ("Choose the open platform or the assembled one", ("jubilee", "opentrons-ot2"),
     "jubilee", "Jubilee"),
    ("Use the assembled platform", ("jubilee", "opentrons-ot2"), "jubilee", "Jubilee"),
    (MESSAGE, ("jubilee", "opentrons-ot2"), "jubilee", "invented user statement"),
])
def test_source_repair_cannot_force_unsupported_or_ambiguous_choices(message, ids, choice, source):
    turn = ExtractedTurn(assistant_message="Offline selection.", engineering=EngineeringUpdate(
        platform_choice=choice, choice_source=source,
    ))
    project = compared_project(ids)
    before = deepcopy(project)
    if source == "invented user statement":
        with pytest.raises(ModelClientError) as caught:
            run_extraction(project, message, turn)
        assert caught.value.failure_kind == "source_validation"
    else:
        extracted, _ = run_extraction(project, message, turn)
        assert extracted.engineering.platform_choice is None
        assert extracted.engineering.choice_source is None
        assert extracted.patch() == {}
        assert not extracted.actions
        from app.engineering import apply_engineering_update

        updated = apply_engineering_update(project, extracted.engineering, message)
        assert state_for(updated) == state_for(before)
        assert updated == before
    assert project == before



def test_safe_choice_source_repair_does_not_repair_invented_other_requirements():
    turn = ExtractedTurn(assistant_message="Offline selection.", engineering=EngineeringUpdate(
        platform_choice="jubilee", choice_source="Jubilee",
        requirements=[{"field": "budget", "value": "$5000", "source": "$5000"}],
    ))
    with pytest.raises(ModelClientError) as caught:
        run_extraction(compared_project(), MESSAGE, turn)
    assert caught.value.failure_kind == "source_validation"


@pytest.mark.parametrize("message", [
    "My bench already has an open platform.",
    "An open platform sounds interesting.",
    "Design a rack for the open platform on my bench.",
])
def test_open_shorthand_equipment_and_interest_mentions_cannot_select(message):
    turn = ExtractedTurn(assistant_message="Offline selection.", engineering=EngineeringUpdate(
        platform_choice="jubilee", choice_source="open platform",
    ))
    project = compared_project()
    before = deepcopy(project)
    extracted, _ = run_extraction(project, message, turn)
    assert extracted.engineering.platform_choice is None
    assert extracted.patch() == {}
    assert not extracted.actions
    assert state_for(project) == state_for(before)


@pytest.mark.parametrize("message", [
    "Open platform", "The open platform, please.", "Yes, the open platform.",
    "Use the open system", "I prefer the open route", "Let's go with the open platform.",
])
def test_open_shorthand_bare_and_affirmative_answers_select(message):
    turn = ExtractedTurn(assistant_message="Offline selection.", engineering=EngineeringUpdate(
        platform_choice="jubilee", choice_source="Jubilee",
    ))
    result, _ = run_extraction(compared_project(), message, turn)
    assert result.engineering.platform_choice == "jubilee"
    assert result.engineering.choice_source in message


@pytest.mark.parametrize("fail_design", [False, True])
def test_choice_and_design_use_real_extraction_and_atomic_normal_generation(
    monkeypatch, fail_design,
):
    project = compared_project()
    before = deepcopy(project)
    instructions = []
    turn = ExtractedTurn(
        assistant_message="Developing the requested workstation.",
        brief_materials="microcentrifuge tubes", source_brief_materials="microcentrifuge tubes",
        brief_constraints="Start with pipetting only",
        source_brief_constraints="Start with pipetting only",
        engineering=EngineeringUpdate(platform_choice="jubilee", choice_source="Jubilee"),
        # The existing normal API choice path requests layout when no action was emitted.
    )

    async def extract(current, message, history):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {
                "content": turn.model_dump_json(),
            }}], "usage": {"total_tokens": 12}},
        ))) as client:
            return await generate_turn(current, message, history, client=client, settings=SETTINGS)

    async def propose(current, instruction, feedback):
        instructions.append(instruction)
        assert state_for(current)["selected_platform_id"] == "jubilee"
        assert current["brief"]["materials"] == "microcentrifuge tubes"
        assert current["brief"]["constraints"] == "Start with pipetting only"
        if fail_design:
            raise ModelClientError("Offline design request failed.")
        return source_proposal(), {"model": "offline", "total_tokens": 10}

    monkeypatch.setattr(api, "generate_turn", extract)
    monkeypatch.setattr(design_agent, "propose_layout", propose)
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    with TestClient(api.app) as client:
        response = client.post(f"/api/projects/{project['id']}/messages", json={"message": MESSAGE})
    assert response.status_code == 200, response.json()
    result = response.json()
    assert instructions == [MESSAGE]
    if fail_design:
        assert result["project"] == before
        assert result["action_runs"][0]["status"] == "failed"
        assert "Offline design request failed" in result["assistant_message"]
    else:
        assert result["action_runs"][0]["status"] == "accepted"
        accepted = result["project"]
        assert state_for(accepted)["selected_platform_id"] == "jubilee"
        assert accepted["engineering_design"]["provenance"]["instruction"] == MESSAGE
        assert not accepted.get("inspection_extension")
        assert not accepted.get("cold_transfer_extension")
        assert accepted["summary"]["stock_concentration"] is None
        assert accepted["brief"]["constraints"] == "Start with pipetting only"
