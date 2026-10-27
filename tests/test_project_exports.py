"""Export boundary checks; CAD bytes are stubbed here, real geometry is tested separately."""

import hashlib
import io
import json
import threading
import time
import zipfile
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

import app.api as api
import app.project_exports as exports
import app.simulation_jobs as simulations
from app.domain import apply_update, configure_project, confirm_project, new_project


@pytest.fixture
def client(monkeypatch):
    api._sessions.clear()
    exports._jobs.clear()
    monkeypatch.setattr(
        exports, "build_cad_files", lambda p: {"cad/workstation.step": b"test-only CAD"}
    )
    monkeypatch.setattr(
        simulations, "simulation_files_for_project", lambda p: {"simulation/result.json": b"{}"}
    )
    with TestClient(api.app) as test_client:
        yield test_client
    api._sessions.clear()
    exports._jobs.clear()


def seed(client, confirmed=True):
    project = apply_update(
        new_project(),
        {
            "stock_concentration": "10 mM",
            "target_concentrations": "1, 2 mM",
            "final_volume": "100 uL",
            "equipment": "Manual pipette",
            "workspace_width_mm": 450,
        },
    )
    if confirmed:
        project = confirm_project(project)
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    return project, f"/api/projects/{project['id']}/exports"


def wait_done(client, url):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = client.get(url)
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] in ("ready", "failed"):
            return job
        time.sleep(0.02)
    pytest.fail("Export did not finish")


def test_confirmation_gate_and_missing_job(client):
    project, base = seed(client, confirmed=False)
    assert client.post(base).status_code == 409
    assert client.get(base + "/missing").status_code == 404
    api._sessions[project["id"]].project = confirm_project(project)
    assert client.post(base).status_code == 202
    job = next(iter(exports._jobs.values()))
    wait_done(client, base + "/" + job["id"])


def test_archive_manifest_hashes_cache_and_attachments(client):
    project, base = seed(client)
    original = deepcopy(project)
    created = client.post(base).json()
    url = base + "/" + created["id"]
    job = wait_done(client, url)
    assert job["status"] == "ready" and job["completed_stages"] == 4
    assert client.post(base).json()["id"] == job["id"]
    response = client.get(job["download_url"])
    assert response.status_code == 200
    assert "attachment;" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        assert {
            "project.json",
            "manifest.json",
            "assembly-guide.html",
            "cad/workstation.step",
        } <= set(names)
        snapshot = json.loads(archive.read("project.json"))["project"]
        assert snapshot == original == project
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["revision"] == project["revision"]
        assert (
            manifest["input_sha256"]
            == hashlib.sha256(
                json.dumps(project, sort_keys=True, allow_nan=False).encode()
            ).hexdigest()
        )
        assert {f["name"] for f in manifest["files"]} == set(names) - {"manifest.json"}
        for file in manifest["files"]:
            payload = archive.read(file["name"])
            assert file["size"] == len(payload)
            assert file["sha256"] == hashlib.sha256(payload).hexdigest()
    guide = client.get(url + "/files/assembly-guide.html")
    assert guide.status_code == 200 and "attachment;" in guide.headers["content-disposition"]
    assert client.get(url + "/files/not-generated.txt").status_code == 404
    other, other_base = seed(client)
    assert other["id"] != project["id"]
    assert client.get(other_base + "/" + job["id"]).status_code == 404


def test_failure_has_no_partial_download_or_internal_error(client, monkeypatch):
    def broken(_):
        raise RuntimeError("private-local-path-and-secret")

    monkeypatch.setattr(exports, "build_cad_files", broken)
    _, base = seed(client)
    created = client.post(base).json()
    url = base + "/" + created["id"]
    job = wait_done(client, url)
    assert job["status"] == "failed" and job["files"] == []
    assert "private-local-path-and-secret" not in json.dumps(job)
    assert client.get(url + "/download").status_code == 409
    monkeypatch.setattr(exports, "build_cad_files", lambda _: {"cad/workstation.step": b"retry"})
    retried = client.post(base).json()
    assert retried["id"] != job["id"]
    assert wait_done(client, base + "/" + retried["id"])["status"] == "ready"


def test_running_revision_change_blocks_stale_and_duplicate_work(client, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def slow(_):
        entered.set()
        if not release.wait(10):
            raise TimeoutError("Test release missing")
        return {"cad/workstation.step": b"blocked-test"}

    monkeypatch.setattr(exports, "build_cad_files", slow)
    project, base = seed(client)
    created = client.post(base).json()
    url = base + "/" + created["id"]
    try:
        assert entered.wait(5)
        assert client.post(base).json()["id"] == created["id"]
        assert client.get(url + "/download").status_code == 409
        changed = configure_project(project, cooling_enabled=True)
        api._sessions[project["id"]].project = changed
        assert client.get(url).status_code == 409
        assert client.get(url + "/download").status_code == 409
        assert client.get(url + "/files/cad/workstation.step").status_code == 409
        current = confirm_project(changed)
        api._sessions[project["id"]].project = current
        assert client.post(base).status_code == 409
    finally:
        release.set()
    deadline = time.monotonic() + 10
    while exports._jobs[created["id"]]["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert exports._jobs[created["id"]]["status"] == "ready"
    assert client.get(url + "/download").status_code == 409
    next_job = client.post(base).json()
    assert next_job["id"] != created["id"]
    assert wait_done(client, base + "/" + next_job["id"])["revision"] == current["revision"]


@pytest.mark.parametrize(
    "name", ["../escape", "/absolute", "cad//empty", "a/./b", "C:/escape", "a\\b", 'a"b', "a\nb"]
)
def test_unsafe_generated_filenames_rejected(name):
    with pytest.raises(ValueError):
        exports._ensure_safe_name(name)
