"""Explicit supported preservation requests constrain actual model candidates."""

import asyncio
from copy import deepcopy

import pytest
from foundation_fixtures import liquid_project, source_proposal

import app.design_agent as agent
from app.design_spec import apply_candidate
from app.foundation_design import adopt_foundation
from app.upstream_cad import foundation_metadata


def accepted_project():
    return apply_candidate(adopt_foundation(liquid_project()), source_proposal(), {})


def test_source_context_contains_exact_relative_current_layout():
    project = accepted_project()
    context = agent._summarize_project(project)["current_insert_layout"]
    for key in ("deck_width_mm", "deck_depth_mm", "bed_drop_mm", "placements"):
        assert context[key] == project["engineering_design"]["proposal"][key]


def test_bed_only_change_keeps_requested_layout():
    checks = agent._preservation_checks(
        accepted_project(), source_proposal(130),
        "Lower the bed another 2.5 mm while preserving the existing component arrangement.",
    )
    assert checks and all(c["passed"] for c in checks)
    assert not any(c["id"] == "preserve_bed_drop_mm" for c in checks)


@pytest.mark.parametrize("instruction", [
    "Redesign the insert freely.",
    "Do not preserve the existing layout.",
    "Don't keep the existing component arrangement.",
    "Never retain the current layout.",
])
def test_unrestricted_or_negated_preservation_does_not_lock(instruction):
    assert agent._preservation_checks(accepted_project(), source_proposal(), instruction) == []


def test_explicit_bed_and_dimension_preservation_rejects_changes():
    candidate = source_proposal(130)
    candidate["deck_width_mm"] = 290
    checks = agent._preservation_checks(
        accepted_project(), candidate, "Keep the bed pose and insert dimensions.",
    )
    assert not next(c for c in checks if c["id"] == "preserve_bed_drop_mm")["passed"]
    assert not next(c for c in checks if c["id"] == "preserve_deck_width_mm")["passed"]


def test_preserve_frame_does_not_lock_separate_layout_change():
    checks = agent._preservation_checks(
        accepted_project(), source_proposal(), "Keep the frame fixed and change the layout.",
    )
    assert checks == []


def test_arrangement_does_not_lock_requested_insert_resize():
    candidate = source_proposal()
    candidate["deck_width_mm"] = 290
    checks = agent._preservation_checks(
        accepted_project(), candidate,
        "Preserve the component arrangement and resize the insert to 290 mm.",
    )
    assert [c["id"] for c in checks] == ["preserve_placements"]
    assert checks[0]["passed"]


def test_malformed_placements_produce_failed_check_without_crashing():
    candidate = source_proposal()
    candidate["placements"][0]["component_id"] = ["source-rack"]
    checks = agent._preservation_checks(
        accepted_project(), candidate, "Preserve the component arrangement.",
    )
    assert not checks[0]["passed"]


def test_shifted_candidate_receives_one_correction_without_silent_rewrite(monkeypatch):
    project = accepted_project()
    original = deepcopy(project)
    bad = source_proposal(130)
    bad["placements"][0]["x_mm"] += 5
    proposals = [bad, source_proposal(130)]
    feedbacks = []

    async def propose(current, instruction, feedback):
        feedbacks.append(feedback)
        return proposals[len(feedbacks) - 1], {"model": "offline", "input_tokens": 1}

    monkeypatch.setattr(agent, "propose_layout", propose)
    changed, run = asyncio.run(agent.develop_design(
        project, "Lower the bed 2.5 mm; keep the existing component arrangement.",
    ))
    assert run["status"] == "accepted" and len(run["attempts"]) == 2
    assert run["attempts"][0]["proposal"] == bad
    assert not next(c for c in run["attempts"][0]["checks"]
                    if c["id"] == "preserve_placements")["passed"]
    assert "The user requested preserving placements" in feedbacks[1]
    assert changed["engineering_design"]["proposal"] == source_proposal(130)
    assert project == original


def test_compiled_bed_change_is_disclosed_and_an_explicit_target_is_rejected(monkeypatch):
    project = accepted_project()
    proposal = source_proposal(100)

    async def propose(current, instruction, feedback):
        return deepcopy(proposal), {"model": "offline", "input_tokens": 1}

    monkeypatch.setattr(agent, "propose_layout", propose)
    changed, run = asyncio.run(agent.develop_design(project, "Develop a workstation layout."))
    assert run["status"] == "accepted"
    assert run["attempts"][0]["proposal"]["bed_drop_mm"] == 100
    assert changed["engineering_design"]["proposal"]["bed_drop_mm"] == 127.5
    assert "100 mm" in run["message"] and "127.5 mm" in run["message"]
    assert "10 mm" in run["message"]
    rejected, run = asyncio.run(agent.develop_design(project, "Set the bed drop to 100 mm."))
    assert run["status"] == "rejected" and rejected == project
    assert "incompatible" in run["message"]
    assert all(not attempt["canonical_checks"][0]["passed"] for attempt in run["attempts"])


def test_preserved_bed_is_checked_again_after_compilation(monkeypatch):
    project = accepted_project()
    design = project["design"]
    # Simulate an old layout where the tool parked too low, before migration.
    design["foundation"] = foundation_metadata(100)
    for part in design["components"]:
        if part["id"] in {
            "base", "source-rack", "sample-rack", "tip-rack", "tip-waste", "controller"
        }:
            part["position"][1] += 27.5
    project["engineering_design"]["proposal"]["bed_drop_mm"] = 100
    original = deepcopy(project)

    async def propose(current, instruction, feedback):
        return source_proposal(100), {"model": "offline", "input_tokens": 1}

    monkeypatch.setattr(agent, "propose_layout", propose)
    result, run = asyncio.run(agent.develop_design(project, "Keep the bed position."))
    assert run["status"] == "rejected" and result == original and project == original
    assert all(attempt["checks"][-1]["passed"] for attempt in run["attempts"])
    assert all(not attempt["canonical_checks"][0]["passed"] for attempt in run["attempts"])
