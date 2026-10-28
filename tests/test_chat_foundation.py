"""Chat operations, source-derived revisions and transactional failure behavior."""

import asyncio
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from foundation_fixtures import liquid_project, source_proposal

import app.api as api
import app.chat_actions as actions
import app.design_agent as design_agent
import app.inspection as inspection
from app.design_sources import project_source_basis
from app.design_spec import apply_candidate, check_candidate
from app.domain import apply_update
from app.foundation_design import adopt_foundation
from app.model_client import ChatAction, ExtractedTurn
from app.upstream_cad import STEP_SHA256


def source_project():
    return apply_candidate(
        adopt_foundation(liquid_project()), source_proposal(), {"model": "offline"}
    )


def test_source_revisions_keep_original_frame_and_move_real_bed_pose():
    before = source_project()
    after = apply_candidate(before, source_proposal(130), {})
    assert after["design"]["foundation"]["source_sha256"] == STEP_SHA256
    assert after["design"]["foundation"]["bed_drop_mm"] == 130
    a = {p["id"]: p for p in before["design"]["components"]}
    b = {p["id"]: p for p in after["design"]["components"]}
    assert a["foundation-jubilee"] == b["foundation-jubilee"]
    assert "geometry" not in b["foundation-jubilee"]
    assert b["base"]["position"][1] == a["base"]["position"][1] - 30
    assert b["sample-rack"]["position"][1] == a["sample-rack"]["position"][1] - 30
    assert project_source_basis(after)["bindings"][0]["basis"] == "imported_open_hardware_cad"


def test_quantities_preserve_layout_and_cooling_updates_keep_actual_source():
    project = source_project()
    changed = apply_update(project, {"target_concentrations": "2 mg/mL"})
    assert changed["engineering_design"] == project["engineering_design"]
    assert changed["design"] == project["design"]
    assert changed["plan"]["steps"][0]["stock_volume_ul"] == 200
    cold = apply_update(project, {"cooling_enabled": True, "cooling_target_c": 4})
    assert cold["design"]["cooling"]["enabled"]
    cold = apply_candidate(cold, source_proposal(), {})
    sidecar = next(p for p in cold["design"]["components"] if p["id"] == "cold-storage")
    assert sidecar["position"][2] - sidecar["size"][2] / 2 > 306.4
    warm = apply_candidate(apply_update(cold, {"cooling_enabled": False}), source_proposal(), {})
    assert all(p["id"] != "cold-storage" for p in warm["design"]["components"])


def test_real_frame_and_proposed_head_envelope_cannot_be_shrunk():
    project = source_project()
    narrow = apply_update(project, {"workspace_width_mm": 450})
    assert narrow["design"]["constraint_status"] == "infeasible"
    assert any(not c["passed"] for c in check_candidate(narrow, source_proposal()))
    invalid = source_proposal(60)
    assert any(not c["passed"] for c in check_candidate(project, invalid))


def test_failed_second_action_rolls_back_and_cancels_prior_success(monkeypatch):
    async def develop(project, instruction):
        return apply_candidate(project, source_proposal(), {}), {
            "status": "accepted",
            "message": "Proposed layout accepted.",
        }

    monkeypatch.setattr(actions, "develop_design", develop)
    project = apply_update(liquid_project(), {"target_concentrations": "20 mg/mL"})
    original = deepcopy(project)
    result, runs = asyncio.run(
        actions.execute_chat_actions(
            project,
            [
                ChatAction(kind="develop_layout", source="design"),
                ChatAction(kind="confirm", source="confirm"),
            ],
            "design and confirm",
        )
    )
    assert result == original
    assert all(run["status"] == "rejected" for run in runs)
    assert "cancelled" in runs[0]["message"]


def test_actions_need_literal_latest_message_grounding():
    turn = ExtractedTurn(
        assistant_message="I can propose it.",
        actions=[ChatAction(kind="develop_layout", source="Develop the design")],
    )
    with pytest.raises(ValueError, match="literally"):
        turn.verify_sources("Maybe later.")


def test_revisions_use_last_accepted_layout_instead_of_resetting_to_starter(monkeypatch):
    proposal = source_proposal()
    proposal["placements"][0]["x_mm"] = -75
    current = apply_candidate(adopt_foundation(liquid_project()), proposal, {})
    captured = {}

    async def develop(project, instruction):
        captured["design"] = deepcopy(project["design"])
        revised = deepcopy(proposal)
        revised["bed_drop_mm"] = 130
        return apply_candidate(project, revised, {}), {"status": "accepted", "message": "Accepted"}

    monkeypatch.setattr(actions, "develop_design", develop)
    asyncio.run(actions.execute_chat_actions(current, [
        ChatAction(kind="develop_layout", source="Lower the bed")], "Lower the bed"))
    assert captured["design"] == current["design"]
    patched = apply_update(current, {"workspace_width_mm": 650})
    assert patched["design"]["components"] == current["design"]["components"]
    assert patched["design"]["foundation"] == current["design"]["foundation"]


def test_source_inspection_prompt_uses_external_foundation_anchor(monkeypatch):
    captured = {}

    async def request(instructions, *args, **kwargs):
        captured["instructions"] = instructions
        return {}, {}

    monkeypatch.setattr(inspection, "request_design_proposal", request)
    asyncio.run(inspection.propose_inspection(source_project(), "Add a camera arm", ""))
    assert "foundation.position.z+foundation.size.z/2+150" in captured["instructions"]
    assert "above the custom deck top" in captured["instructions"]


def test_normal_chat_runs_real_compiler_and_rejection_preserves_whole_project(monkeypatch):
    async def fake_turn(project, message, history):
        if message == "Develop the design":
            return ExtractedTurn(
                assistant_message="Proposing a source-based layout.",
                actions=[ChatAction(kind="develop_layout", source=message)],
            ), {}
        return ExtractedTurn(
            assistant_message="Checking the width.",
            workspace_width_mm=450,
            source_workspace_width_mm="450 mm",
        ), {}

    async def fake_layout(project, instruction, feedback, **kwargs):
        return source_proposal(), {"model": "offline-layout-fixture"}

    monkeypatch.setattr(api, "generate_turn", fake_turn)
    monkeypatch.setattr(design_agent, "propose_layout", fake_layout)
    project = liquid_project()
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    with TestClient(api.app) as client:
        route = f"/api/projects/{project['id']}/messages"
        accepted = client.post(route, json={"message": "Develop the design"}).json()
        assert accepted["action_runs"][0]["status"] == "accepted"
        assert accepted["project"]["design"]["foundation"]["source_sha256"] == STEP_SHA256
        rejected = client.post(route, json={"message": "Limit width to 450 mm"}).json()
        assert rejected["action_runs"][0]["status"] == "rejected"
        assert rejected["project"] == accepted["project"]
