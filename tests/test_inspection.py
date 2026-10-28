"""Bounded Meta proposal loop and same-project extension integration."""

import asyncio
from copy import deepcopy

import pytest
from evolution_fixtures import inspection_proposal, layout_project
from fastapi.testclient import TestClient

import app.api as api
import app.inspection as inspection
from app.assembly import assembly_steps, build_document_files
from app.design_spec import apply_candidate
from app.domain import apply_update
from app.model_client import ModelClientError


def test_correction_then_acceptance_preserves_workstation(monkeypatch):
    calls = []

    async def fake(project, instruction, feedback):
        calls.append(feedback)
        proposal = inspection_proposal()
        if not feedback:
            proposal["link_lengths_mm"] = [180, 180]
        return proposal, {"model": "offline-model", "input_tokens": 5, "output_tokens": 8}

    monkeypatch.setattr(inspection, "propose_inspection", fake)
    project = layout_project(cooling=True)
    before = deepcopy(project)
    updated, run = asyncio.run(inspection.develop_inspection(project, "Add camera inspection."))
    assert project == before
    assert run["status"] == "accepted" and len(run["attempts"]) == 2
    assert calls[0] == "" and "unreachable" in calls[1]
    assert updated["id"] == project["id"] and updated["revision"] == project["revision"] + 1
    assert updated["status"] == "draft"
    assert (
        updated["design"]["components"][: len(project["design"]["components"])]
        == project["design"]["components"]
    )
    assert updated["engineering_design"] == project["engineering_design"]
    assert len(updated["inspection_extension"]["pose_frames"]) == 4
    assert updated["sourcing"]["unpriced_count"] == project["sourcing"]["unpriced_count"] + 3
    docs = build_document_files(updated)
    assert b"offline-model" in docs["inspection-module.json"]
    assert len(docs["inspection-poses.csv"].splitlines()) == 5
    assert any(step["id"] == "inspection-extension" for step in assembly_steps(updated))
    assert b"No arm geometry" not in docs["extensions.md"]
    assert b"liquid_preparation_only" in docs["README.md"]
    removed = inspection.clear_extension(updated)
    assert removed["design"]["components"] == project["design"]["components"]
    assert removed["sourcing"] == project["sourcing"]
    changed = apply_update(updated, {"workspace_width_mm": 300})
    assert not changed.get("inspection_extension")
    assert not any(p["id"].startswith("inspection-") for p in changed["design"]["components"])


def test_rejected_and_transport_failures_preserve_original(monkeypatch):
    project = layout_project(cooling=True)

    async def reject(*args):
        return {**inspection_proposal(), "link_lengths_mm": [180, 180]}, {"model": "offline"}

    monkeypatch.setattr(inspection, "propose_inspection", reject)
    updated, run = asyncio.run(inspection.develop_inspection(project, "Add the inspection arm."))
    assert updated == project and run["status"] == "rejected" and len(run["attempts"]) == 2

    async def fail(*args):
        raise ModelClientError("Synthetic network failure")

    monkeypatch.setattr(inspection, "propose_inspection", fail)
    with pytest.raises(ModelClientError) as caught:
        asyncio.run(inspection.develop_inspection(project, "Add the inspection arm."))
    assert caught.value.design_run["status"] == "failed"


def test_stale_extension_api_and_remove_do_not_call_provider(monkeypatch):
    project = layout_project()
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    calls = []

    async def fake(*args):
        calls.append(True)
        return inspection_proposal(), {"model": "offline-fixture"}

    monkeypatch.setattr(inspection, "propose_inspection", fake)
    with TestClient(api.app) as client:
        path = f"/api/projects/{project['id']}/inspection-extension"
        assert (
            client.post(path, json={"project_revision": 0, "instruction": "Add camera"}).status_code
            == 409
        )
        assert not calls
        result = client.post(
            path, json={"project_revision": project["revision"], "instruction": "Add camera"}
        )
        assert result.status_code == 200 and result.json()["design_run"]["status"] == "accepted"
        current = result.json()["project"]
        result = client.post(path + "/remove", json={"project_revision": current["revision"]})
        assert result.status_code == 200
        assert not result.json()["project"].get("inspection_extension")
        assert result.json()["project"]["engineering_design"] == project["engineering_design"]
        assert len(calls) == 1
    api._sessions.clear()


def test_extension_cannot_silently_exceed_recorded_workspace_width():
    project = apply_update(layout_project(), {"workspace_width_mm": 400})
    layout = deepcopy(layout_project()["engineering_design"]["proposal"])
    layout.update(deck_width_mm=400, deck_depth_mm=470)
    positions = [(-112, -45), (0, -45), (112, -45), (-120, 120), (120, 120)]
    for placement, (x, z) in zip(layout["placements"], positions):
        placement.update(x_mm=x, z_mm=z)
    project = apply_candidate(project, layout, {"model": "offline"})
    proposal = {**inspection_proposal(), "link_lengths_mm": [500, 500]}
    before = deepcopy(project)
    with pytest.raises(ValueError, match="exceed the workspace width"):
        inspection.apply_extension(project, proposal, {"model": "offline"})
    assert project == before
