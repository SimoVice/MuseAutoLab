"""Portable state rebuilding, API isolation and stale-output boundaries."""

import json
from copy import deepcopy

import pytest
from evolution_fixtures import inspection_proposal, layout_project
from fastapi.testclient import TestClient

import app.api as api
from app.domain import apply_update, confirm_project, new_project
from app.inspection import apply_extension
from app.project_storage import MAX_SNAPSHOT_BYTES, decode_snapshot, make_snapshot, restore_snapshot


@pytest.mark.parametrize("kind", ["blank", "general", "incomplete", "invalid", "layout", "cooled"])
def test_project_roundtrip_rebuilds_inputs_and_layout(kind):
    project = new_project()
    if kind == "general":
        project = apply_update(
            project,
            {"workflow_kind": "general", "brief_process": "Move vials", "workspace_width_mm": 450},
        )
    elif kind == "incomplete":
        project = apply_update(
            project, {"workflow_kind": "liquid_preparation", "equipment": "pipette and tubes"}
        )
    elif kind == "invalid":
        project = apply_update(project, {"workspace_width_mm": 250})
    elif kind in ("layout", "cooled"):
        project = confirm_project(layout_project(cooling=kind == "cooled"))
    before = deepcopy(project)
    history = [{"role": "user", "content": "Keep my project."}]
    snapshot = make_snapshot(project, history)
    restored, conversation = restore_snapshot(decode_snapshot(json.dumps(snapshot).encode()))
    assert project == before
    assert restored["id"] != project["id"]
    assert restored["lineage_id"] == project["id"]
    for key in (
        "revision",
        "status",
        "summary",
        "brief",
        "selections",
        "sourcing",
        "plan",
        "workflow",
    ):
        assert restored[key] == project[key], key
    if kind in ("layout", "cooled"):
        assert restored["engineering_design"] == project["engineering_design"]
        assert restored["design"] == project["design"]
    assert conversation == history
    reopened, _ = restore_snapshot(make_snapshot(restored, conversation))
    assert reopened["id"] not in (project["id"], restored["id"])
    assert reopened["lineage_id"] == project["id"]


def test_extended_confirmed_project_rebuilds_exact_geometry_and_unpriced_groups():
    project = confirm_project(
        apply_extension(
            layout_project(cooling=True),
            inspection_proposal(),
            {"model": "offline-inspection-fixture"},
        )
    )
    restored, _ = restore_snapshot(make_snapshot(project, []))
    assert restored["design"] == project["design"]
    assert restored["inspection_extension"] == project["inspection_extension"]
    assert restored["sourcing"] == project["sourcing"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s: s.update(schema_version=2),
        lambda s: s.update(schema_version=True),
        lambda s: s.update(compiler_version="future"),
        lambda s: s.update(project_id="x" * 36),
        lambda s: s.update(jobs=[]),
    lambda s: s.update(inspection_extension={}),
        lambda s: s.update(history=[{"role": "system", "content": "x"}]),
        lambda s: s["inputs"]["summary"].update(workspace_width_mm=True),
        lambda s: s["inputs"]["summary"].update(cooling_target_c=float("inf")),
        lambda s: s["engineering_design"]["proposal"].update(deck_width_mm=12),
        lambda s: s["engineering_design"]["proposal"]["placements"][0].update(x_mm=900),
        lambda s: s["inputs"].update(workflow_kind="general"),
        lambda s: s["inputs"]["brief"].update(equipment="another machine"),
    ],
)
def test_invalid_or_tampered_snapshot_rejected_without_mutation(mutation):
    saved = make_snapshot(layout_project(), [])
    mutation(saved)
    before = deepcopy(saved)
    with pytest.raises(ValueError):
        restore_snapshot(saved)
    assert saved == before


@pytest.mark.parametrize(
    "raw",
    [
        b'{"format":1,"format":2}',
        b'{"value":NaN}',
        b"[]",
        b"no",
        b'{"x":' + b"[" * 34 + b"0" + b"]" * 34 + b"}",
    ],
)
def test_decoder_rejects_ambiguous_json(raw):
    with pytest.raises(ValueError):
        decode_snapshot(raw)


def test_snapshot_api_survives_session_loss_without_reusing_old_jobs(monkeypatch):
    project = confirm_project(layout_project())
    history = [{"role": "user", "content": "Prepare my dilutions."}]
    api._sessions[project["id"]] = api.ProjectSession(project=project, history=history)
    with TestClient(api.app) as client:
        path = f"/api/projects/{project['id']}/snapshot"
        assert client.get(path, params={"revision": project["revision"] - 1}).status_code == 409
        saved = client.get(path, params={"revision": project["revision"]})
        assert saved.status_code == 200
        assert "attachment" in saved.headers["content-disposition"]
        api._sessions.clear()
        response = client.post("/api/projects/open", content=saved.content)
        assert response.status_code == 201, response.text
        reopened = response.json()["project"]
        assert reopened["lineage_id"] == project["id"]
        assert response.json()["conversation"] == history
        assert reopened["id"] != project["id"]
        assert client.get(f"/api/projects/{reopened['id']}/exports/old").status_code == 404
        before = deepcopy(api._sessions)
        assert client.post("/api/projects/open", content=b'{"bad":1}').status_code == 422
        assert list(api._sessions) == list(before)
        assert (
            client.post("/api/projects/open", content=b" " * (MAX_SNAPSHOT_BYTES + 1)).status_code
            == 413
        )
    api._sessions.clear()
