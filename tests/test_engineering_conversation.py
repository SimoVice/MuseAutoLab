"""The ordinary chat compares routes, waits for choice and designs the selected base."""

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from foundation_fixtures import source_proposal

import app.api as api
import app.design_agent as agent
from app.domain import apply_update, new_project
from app.engineering import EngineeringOption, EngineeringUpdate, state_for
from app.model_client import ChatAction, ExtractedTurn
from app.project_storage import make_snapshot, restore_snapshot


def proposals():
    return [
        EngineeringOption(
            platform_id="jubilee",
            reason="Build and customize the platform.",
            tradeoffs=["Assembly and tool integration are required."],
        ),
        EngineeringOption(
            platform_id="opentrons-ot2",
            reason="Purchase an assembled platform.",
            tradeoffs=["Compatible pipettes and an official quote are required."],
        ),
    ]


def unselected_project(stock="10 mg/mL"):
    return apply_update(
        new_project(),
        {
            "workflow_kind": "liquid_preparation",
            "equipment": "pipette and tubes",
            "stock_concentration": stock,
        },
    )


def configure(monkeypatch, project):
    calls = []

    async def turn(current, message, history):
        if message == "Compare the platform options":
            return ExtractedTurn(
                assistant_message="Would you buy assembled or build it?",
                engineering=EngineeringUpdate(options=proposals()),
            ), {}
        if message in ("I prefer the open-source buildable one", "I prefer the prebuilt one"):
            choice = "jubilee" if "open-source" in message else "opentrons-ot2"
            return ExtractedTurn(
                assistant_message="I will develop the selected platform.",
                engineering=EngineeringUpdate(platform_choice=choice, choice_source=message),
            ), {}
        if message.startswith("Use target concentrations"):
            return ExtractedTurn(
                assistant_message="Updating the preparation quantities only.",
                target_concentrations="1, 0.5 and 0.1 mg/mL",
                source_target_concentrations="1, 0.5 and 0.1 mg/mL",
                final_volume="1 mL per tube",
                source_final_volume="1 mL per tube",
                # Deliberately wrong action: the API must honor the user's explicit preservation.
                actions=[
                    ChatAction(kind="develop_layout", source="Keep the machine layout unchanged")
                ],
            ), {}
        return ExtractedTurn(
            assistant_message="Discussing the design.",
            actions=[ChatAction(kind="develop_layout", source=message)],
        ), {}

    async def propose(current, instruction, feedback, **kwargs):
        calls.append(current["design"].get("platform", {}).get("id", "jubilee"))
        if calls[-1] == "opentrons-ot2":
            return {
                "schema_version": "1",
                "slot_assignments": [
                    {"component_id": "source-rack", "slot_id": "1"},
                    {"component_id": "sample-rack", "slot_id": "2"},
                    {"component_id": "tip-rack", "slot_id": "3"},
                ],
                "rationale": "Offline commercial layout.",
                "assumptions": [],
            }, {"model": "offline"}
        return source_proposal(), {"model": "offline"}

    monkeypatch.setattr(api, "generate_turn", turn)
    monkeypatch.setattr(agent, "propose_layout", propose)
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    return f"/api/projects/{project['id']}/messages", calls


def test_generation_waits_for_choice_and_keeps_requirements(monkeypatch):
    project = unselected_project()
    route, calls = configure(monkeypatch, project)
    with TestClient(api.app) as client:
        data = client.post(route, json={"message": "Develop the machine"}).json()
        assert data["action_runs"][0]["status"] == "ready" and not calls
        assert not data["project"].get("engineering_design")
        assert not data["project"]["design"].get("foundation")
        assert data["project"]["summary"]["equipment"] == "pipette and tubes"


@pytest.mark.parametrize(
    "choice,expected",
    [
        ("I prefer the open-source buildable one", "jubilee"),
        ("I prefer the prebuilt one", "opentrons-ot2"),
    ],
)
def test_choice_develops_distinct_base_and_quantities_preserve_layout(
    monkeypatch, choice, expected
):
    route, calls = configure(monkeypatch, unselected_project())
    with TestClient(api.app) as client:
        offered = client.post(route, json={"message": "Compare the platform options"}).json()
        assert state_for(offered["project"])["selected_platform_id"] is None
        assert not calls
        accepted = client.post(route, json={"message": choice}).json()
        assert accepted["action_runs"][0]["status"] == "accepted"
        before = accepted["project"]
        assert calls == [expected]
        assert state_for(before)["selected_platform_id"] == expected
        if expected == "opentrons-ot2":
            assert before["design"]["platform"]["id"] == expected
            assert not before["design"].get("foundation")
            assert not any(
                g["id"] in ("motors", "drivers", "frame") for g in before["sourcing"]["groups"]
            )
        else:
            assert before["design"]["foundation"]["id"].startswith("jubilee")
        assert before["engineering_guidance"]["steps"]
        message = (
            "Use target concentrations of 1, 0.5 and 0.1 mg/mL, with a final volume "
            "of 1 mL per tube. Keep the machine layout unchanged"
        )
        changed = client.post(route, json={"message": message}).json()["project"]
        assert calls == [expected]
        assert changed["engineering_design"] == before["engineering_design"]
        for old, new in zip(before["design"]["components"], changed["design"]["components"]):
            assert old["id"] == new["id"]
            assert old["position"] == new["position"] and old["size"] == new["size"]
        assert [s["stock_volume_ul"] for s in changed["plan"]["steps"]] == [100, 50, 10]
        saved = make_snapshot(changed, [])
        assert saved["compiler_version"] == "4"
        rebuilt, _ = restore_snapshot(saved)
        assert rebuilt["design"] == changed["design"]
        assert state_for(rebuilt) == state_for(changed)


def test_per_tube_without_stock_asks_for_missing_stock_not_unit(monkeypatch):
    route, _ = configure(monkeypatch, unselected_project(None))
    with TestClient(api.app) as client:
        message = (
            "Use target concentrations of 1, 0.5 and 0.1 mg/mL, with a final volume "
            "of 1 mL per tube. Keep the machine layout unchanged"
        )
        data = client.post(route, json={"message": message}).json()["project"]
        assert data["plan"]["status"] == "incomplete"
        assert "stock" in data["plan"]["message"].lower()
        assert "unsupported unit" not in data["plan"]["message"].lower()


@pytest.mark.parametrize("message", [
    "In the future I want to use Jubilee", "What is Jubilee?", "Should I use Jubilee?",
    "Would you recommend using the prebuilt one?",
])
def test_future_and_information_requests_cannot_select(message):
    update = EngineeringUpdate(platform_choice="jubilee", choice_source=message)
    with pytest.raises(ValueError):
        update.verify_sources(
            message,
            {"engineering": {**state_for({}), "options": [p.model_dump() for p in proposals()]}},
        )


def test_short_route_answer_is_valid_only_after_real_options():
    update = EngineeringUpdate(platform_choice="opentrons-ot2", choice_source="ready-to-use")
    project = {"engineering": {**state_for({}), "options": [p.model_dump() for p in proposals()]}}
    before = deepcopy(project)
    update.verify_sources("ready-to-use", project)
    assert project == before
    with pytest.raises(ValueError):
        update.verify_sources("ready-to-use", {})


def test_commercial_revision_receives_accepted_slot_assignments(monkeypatch):
    from app.commercial_design import adopt_commercial, compile_commercial_layout
    from app.design_agent import _summarize_project
    from app.engineering import apply_engineering_update

    project = apply_engineering_update(unselected_project(), EngineeringUpdate(
        platform_choice="opentrons-ot2", choice_source="Use OT-2"), "Use OT-2")
    proposal = {"schema_version": "1", "rationale": "Accepted prior arrangement.",
                "assumptions": [], "slot_assignments": [
                    {"component_id": "source-rack", "slot_id": "4"},
                    {"component_id": "sample-rack", "slot_id": "5"},
                    {"component_id": "tip-rack", "slot_id": "6"}]}
    project = compile_commercial_layout(adopt_commercial(project), proposal, {})
    route, _ = configure(monkeypatch, project)

    async def revise(current, instruction, feedback, **kwargs):
        assert current["engineering_design"]["proposal"] == proposal
        context = {c["id"]: c for c in _summarize_project(current)["components"]}
        assert context["source-rack"]["slot_id"] == "4"
        changed = deepcopy(proposal)
        changed["slot_assignments"][1]["slot_id"] = "8"
        return changed, {"model": "offline"}

    monkeypatch.setattr(agent, "propose_layout", revise)
    with TestClient(api.app) as client:
        data = client.post(route, json={"message": "Move only the sample rack to slot 8"}).json()
    assert data["action_runs"][0]["status"] == "accepted"
    parts = {c["id"]: c for c in data["project"]["design"]["components"]}
    assert [parts[c]["slot_id"] for c in ("source-rack", "sample-rack", "tip-rack")] == [
        "4", "8", "6"]


def test_failed_platform_switch_preserves_choice_and_actual_design(monkeypatch):
    from foundation_fixtures import liquid_project

    from app.design_spec import apply_candidate
    from app.foundation_design import adopt_foundation

    project = apply_candidate(adopt_foundation(liquid_project()), source_proposal(), {})
    # This module cannot be carried onto the commercial adapter; the whole turn must roll back.
    project["inspection_extension"] = {"component_ids": ["inspection-camera"]}
    state = state_for(project)
    state["options"] = [p.model_dump() for p in proposals()]
    project["engineering"] = state
    before = deepcopy(project)
    route, _ = configure(monkeypatch, project)
    with TestClient(api.app) as client:
        data = client.post(route, json={"message": "I prefer the prebuilt one"}).json()
    assert data["action_runs"][0]["status"] == "rejected"
    assert data["project"]["design"] == before["design"]
    assert state_for(data["project"]) == state_for(before)
