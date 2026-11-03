"""The opt-in account library preserves trusted project state across restarts."""

import asyncio
import json
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.api as api
from app import project_library


@pytest.fixture(params=["sqlite", "json"])
def client(tmp_path, monkeypatch, request):
    monkeypatch.delenv("MUSEAUTOLAB_DATABASE_PATH", raising=False)
    monkeypatch.delenv("MUSEAUTOLAB_LIBRARY_DIRECTORY", raising=False)
    monkeypatch.delenv("MUSEAUTOLAB_MODAL_VOLUME_NAME", raising=False)
    if request.param == "sqlite":
        monkeypatch.setenv("MUSEAUTOLAB_DATABASE_PATH", str(tmp_path / "projects.sqlite3"))
    else:
        monkeypatch.setenv("MUSEAUTOLAB_LIBRARY_DIRECTORY", str(tmp_path / "projects"))
    api._sessions.clear()
    with TestClient(api.app) as client:
        yield client
    api._sessions.clear()


def test_named_project_restores_same_identity_revision_conversation_and_prices(client):
    project = client.post("/api/projects").json()["project"]
    project_id = project["id"]
    session = api._sessions[project_id]
    # These observations represent trusted server sidecars, never portable-file input.
    session.history = [{"role": "user", "content": "Build a sample station."}]
    session.procurement_report = {"checked_at": "2026-11-03T10:00:00Z", "items": []}
    session.cost_estimate = {"generated_at": "2026-11-03T09:00:00Z", "amount": 400}
    result = client.post(f"/api/projects/{project_id}/save", json={
        "title": "Sample receiving station", "revision": project["revision"],
    })
    assert result.status_code == 200
    expected = deepcopy(session)
    api._sessions.clear()
    opened = client.post(f"/api/library/{project_id}/open")
    assert opened.status_code == 200
    assert opened.json()["project"] == project
    assert opened.json()["conversation"] == expected.history
    assert opened.json()["title"] == "Sample receiving station"
    restored = api._sessions[project_id]
    assert restored.procurement_report == expected.procurement_report
    assert restored.cost_estimate == expected.cost_estimate
    listing = client.get("/api/library").json()
    assert listing["enabled"] is True
    assert listing["projects"][0]["id"] == project_id


def test_unnamed_project_resumes_but_does_not_enter_named_library(client):
    project = client.post("/api/projects").json()["project"]
    assert client.get("/api/library").json()["projects"] == []
    api._sessions.clear()
    assert client.get(f"/api/projects/{project['id']}").json()["project"] == project
    assert client.post(f"/api/library/{project['id']}/open").status_code == 404


def test_locked_update_survives_restart_without_another_named_save(client):
    project = client.post("/api/projects").json()["project"]
    project_id = project["id"]
    client.post(f"/api/projects/{project_id}/save", json={"title": "Station", "revision": 0})
    session = api._sessions[project_id]

    async def change():
        async with session.model_lock():
            updated = api.apply_update(session.project, {"workspace_width_mm": 900})
            api._accept_project(session, updated)
            session.history.append({"role": "user", "content": "Use a 900 mm bench."})

    asyncio.run(change())
    expected = deepcopy(session.project)
    api._sessions.clear()
    opened = client.post(f"/api/library/{project_id}/open").json()
    assert opened["project"] == expected
    assert opened["project"]["revision"] > 0
    assert opened["conversation"][-1]["content"] == "Use a 900 mm bench."


def test_save_requires_current_revision_and_valid_name(client):
    project = client.post("/api/projects").json()["project"]
    url = f"/api/projects/{project['id']}/save"
    assert client.post(url, json={"title": "New project", "revision": 999}).status_code == 409
    assert client.post(url, json={"title": "  ", "revision": 0}).status_code == 422
    assert client.get("/api/library").json()["projects"] == []


def test_autosave_preserves_named_entry_and_rejects_stale_disk_write(client):
    project = client.post("/api/projects").json()["project"]
    project_id = project["id"]
    client.post(f"/api/projects/{project_id}/save", json={"title": "Station", "revision": 0})
    saved = project_library.load(project_id)
    newer = deepcopy(saved)
    newer["project"]["revision"] = 2
    project_library.persist(newer)
    project_library.persist(saved, title="Outdated")
    assert project_library.load(project_id)["project"]["revision"] == 2
    assert project_library.entry(project_id)["title"] == "Station"


def test_local_mode_preserves_portable_download_and_disables_library(client, monkeypatch):
    monkeypatch.delenv("MUSEAUTOLAB_DATABASE_PATH", raising=False)
    monkeypatch.delenv("MUSEAUTOLAB_LIBRARY_DIRECTORY", raising=False)
    project = client.post("/api/projects").json()["project"]
    assert client.get("/api/library").json() == {"enabled": False, "projects": []}
    assert client.post(f"/api/projects/{project['id']}/save", json={
        "title": "Station", "revision": 0,
    }).status_code == 503
    snapshot = client.get(f"/api/projects/{project['id']}/snapshot?revision=0")
    assert snapshot.status_code == 200
    assert client.post("/api/projects/open", content=snapshot.content).status_code == 201


@pytest.fixture
def volume_storage(tmp_path, monkeypatch):
    monkeypatch.delenv("MUSEAUTOLAB_DATABASE_PATH", raising=False)
    monkeypatch.setenv("MUSEAUTOLAB_LIBRARY_DIRECTORY", str(tmp_path / "projects"))
    monkeypatch.setenv("MUSEAUTOLAB_MODAL_VOLUME_NAME", "test-volume")
    return tmp_path / "projects"


def test_volume_commit_is_immediate_after_atomic_replace(volume_storage, monkeypatch):
    payload = {"project": {"id": "project-1", "revision": 0, "status": "draft"}, "history": []}
    commits = []

    def commit():
        files = list(volume_storage.glob("*.json"))
        assert len(files) == 1
        # Commit sees the complete replacement; no temporary file is held open.
        with files[0].open(encoding="utf-8") as source:
            assert json.load(source)["payload"] == payload
        assert not list(volume_storage.glob(".project-*"))
        commits.append(True)

    monkeypatch.setattr(project_library, "_commit_volume", commit)
    first = project_library.persist(payload, title="Sample station")
    assert commits == [True]
    assert project_library.persist(payload) == first
    assert commits == [True]  # Reads and unchanged lock exits do not commit again.
    assert project_library.load("../../outside") is None
    assert len(list(volume_storage.glob("*.json"))) == 1


def test_failed_commit_is_reported_and_retried(volume_storage, monkeypatch):
    payload = {"project": {"id": "project-1", "revision": 0, "status": "draft"}}
    calls = []

    def commit():
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("Cloud commit unavailable")

    monkeypatch.setattr(project_library, "_commit_volume", commit)
    with pytest.raises(RuntimeError, match="Cloud commit unavailable"):
        project_library.persist(payload)
    assert project_library.persist(payload)["revision"] == 0
    assert len(calls) == 2


def test_failed_replace_preserves_previous_snapshot(volume_storage, monkeypatch):
    monkeypatch.setattr(project_library, "_commit_volume", lambda: None)
    payload = {"project": {"id": "project-1", "revision": 0, "status": "draft"}}
    project_library.persist(payload)
    newer = deepcopy(payload)
    newer["project"]["revision"] = 1

    def fail(*args):
        raise OSError("Replace unavailable")

    monkeypatch.setattr(project_library.os, "replace", fail)
    with pytest.raises(OSError, match="Replace unavailable"):
        project_library.persist(newer)
    assert project_library.load("project-1") == payload
    assert not list(volume_storage.glob(".project-*"))


def test_storage_configuration_rejects_ambiguous_backends(volume_storage, monkeypatch):
    monkeypatch.setenv("MUSEAUTOLAB_DATABASE_PATH", "do-not-create.sqlite3")
    with pytest.raises(RuntimeError, match="either SQLite"):
        project_library.configured()
    monkeypatch.delenv("MUSEAUTOLAB_DATABASE_PATH")
    monkeypatch.delenv("MUSEAUTOLAB_LIBRARY_DIRECTORY")
    with pytest.raises(RuntimeError, match="requires MUSEAUTOLAB_LIBRARY_DIRECTORY"):
        project_library.configured()


def test_modal_commit_looks_up_existing_named_volume(volume_storage, monkeypatch):
    calls = []
    volume = SimpleNamespace(commit=lambda: calls.append("commit"))

    def lookup(name):
        calls.append(name)
        return volume

    monkeypatch.setitem(sys.modules, "modal", SimpleNamespace(
        Volume=SimpleNamespace(from_name=lookup),
    ))
    project_library._modal_volume.cache_clear()
    try:
        project_library._commit_volume()
        assert calls == ["test-volume", "commit"]
    finally:
        project_library._modal_volume.cache_clear()
