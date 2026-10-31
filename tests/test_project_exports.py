"""Export boundary checks; CAD bytes are stubbed here, real geometry is tested separately."""

import asyncio
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
    async def fixture_cad(_):
        return {"cad/workstation.step": b"test-only CAD"}

    monkeypatch.setattr(exports, "_execute_cad", fixture_cad)
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


def test_commercial_package_keeps_setup_sources_and_no_legacy_physics(client):
    from test_commercial_design import proposal
    from test_engineering_conversation import unselected_project

    from app.commercial_design import adopt_commercial, compile_commercial_layout
    from app.engineering import EngineeringUpdate, apply_engineering_update
    from app.platform_profiles import commercial_sourcing

    project = apply_update(unselected_project(), {
        "target_concentrations": "1 mg/mL", "final_volume": "1 mL per tube"})
    project = apply_engineering_update(project, EngineeringUpdate(
        platform_choice="opentrons-ot2", choice_source="Use OT-2"), "Use OT-2")
    project = compile_commercial_layout(adopt_commercial(project), proposal(), {})
    project["sourcing"] = commercial_sourcing()
    project = confirm_project(project)
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    base = f"/api/projects/{project['id']}/exports"
    created = client.post(base).json()
    job = wait_done(client, base + "/" + created["id"])
    assert job["status"] == "ready"
    with zipfile.ZipFile(io.BytesIO(client.get(job["download_url"]).content)) as archive:
        result = json.loads(archive.read("simulation/result.json"))
        assert result["status"] == "not_run"
        assert "selected platform" in result["reason"]
        assert "references/ot2-deck.json" in archive.namelist()
        guide = archive.read("assembly-guide.html").decode()
        assert "Instrument purchase and setup guide" in guide
        assert "custom sample insert follows" not in guide
        assert "no compatible mount or hardware control" in archive.read("extensions.md").decode()
        assert "quote" in archive.read("purchase-and-assembly.md").decode().lower()


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
    async def broken(_):
        raise RuntimeError("private-local-path-and-secret")

    monkeypatch.setattr(exports, "_execute_cad", broken)
    _, base = seed(client)
    created = client.post(base).json()
    url = base + "/" + created["id"]
    job = wait_done(client, url)
    assert job["status"] == "failed" and job["files"] == []
    assert "private-local-path-and-secret" not in json.dumps(job)
    assert client.get(url + "/download").status_code == 409
    async def retry_cad(_):
        return {"cad/workstation.step": b"retry"}

    monkeypatch.setattr(exports, "_execute_cad", retry_cad)
    retried = client.post(base).json()
    assert retried["id"] != job["id"]
    assert wait_done(client, base + "/" + retried["id"])["status"] == "ready"


def test_running_revision_change_blocks_stale_and_duplicate_work(client, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    async def slow(_):
        entered.set()
        if not await asyncio.to_thread(release.wait, 10):
            raise TimeoutError("Test release missing")
        return {"cad/workstation.step": b"blocked-test"}

    monkeypatch.setattr(exports, "_execute_cad", slow)
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
