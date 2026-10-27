"""Simulation HTTP/job boundary checks; engine functions are stubbed in place."""

import threading
import time
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

import app.api as api
import app.simulation_jobs as simjobs
from app.domain import apply_update, configure_project, confirm_project, new_project


@pytest.fixture
def client(monkeypatch):
    api._sessions.clear()
    simjobs._jobs.clear()
    simjobs._cache.clear()
    simjobs._background_tasks.clear()
    _stub_engine(monkeypatch)
    with TestClient(api.app) as test_client:
        yield test_client
    _wait_all_done(timeout=15)
    api._sessions.clear()
    simjobs._jobs.clear()
    simjobs._cache.clear()
    simjobs._background_tasks.clear()


def _synthetic_result(project, scenario, status="passed"):
    blocked = status == "blocked"
    return {
        "schema_version": 1,
        "project_id": project["id"],
        "revision": project["revision"],
        "scenario": scenario,
        "engine": "MuJoCo",
        "engine_version": "3.17.0",
        "input_sha256": "stub",
        "status": status,
        "duration_s": 1.0,
        "timestep_s": 0.002,
        "frames": [],
        "waypoints": [],
        "metrics": {"max_tracking_error_mm": 1.0, "completed_waypoints": 1},
        "contacts": [],
        "checks": [],
        "assumptions": [],
        "limitations": [],
        "model_xml": "<mujoco/>",
        "obstacles": [],
        "integration_steps": 3 if blocked else 10,
        "planned_integration_steps": 10,
    }


def _stubbed_files():
    return {name: f"# {name}\n".encode() for name in simjobs.SIMULATION_FILES}


def _stub_engine(monkeypatch, status_for=None):
    def fake_simulate(project, scenario="nominal", on_progress=None):
        if on_progress is not None:
            on_progress("simulate", 1, 10)
        status = status_for(scenario) if status_for else "passed"
        return _synthetic_result(project, scenario, status=status)

    def fake_build(project, result):
        return dict(_stubbed_files())

    monkeypatch.setattr(simjobs, "_physics_simulate", fake_simulate)
    monkeypatch.setattr(simjobs, "_physics_build_files", fake_build)


def _wait_all_done(timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pending = [j for j in list(simjobs._jobs.values()) if j["status"] in ("queued", "running")]
        if not pending:
            return
        time.sleep(0.02)
    raise AssertionError("A simulation worker did not finish")


def _wait_job(client, url, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(url)
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] in ("ready", "failed"):
            return job
        time.sleep(0.02)
    pytest.fail("Simulation job did not finish")


def _seed(confirmed=True):
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
    return project, f"/api/projects/{project['id']}/simulations"


def test_confirmation_and_malformed_scenario_gates(client):
    project, base = _seed(confirmed=False)
    assert client.post(base, json={"scenario": "nominal"}).status_code == 409
    api._sessions[project["id"]].project = confirm_project(project)
    assert client.post(base, json={"scenario": "nope"}).status_code == 422
    created = client.post(base, json={"scenario": "nominal"})
    assert created.status_code == 202
    job = _wait_job(client, base + "/" + created.json()["id"])
    assert job["status"] == "ready"


def test_duplicate_and_cache_reuse_with_sync_files(client):
    project, base = _seed()
    first = client.post(base, json={"scenario": "nominal"}).json()
    duplicate = client.post(base, json={"scenario": "nominal"}).json()
    assert duplicate["id"] == first["id"]
    url = base + "/" + first["id"]
    job = _wait_job(client, url)
    assert job["status"] == "ready"
    assert job["summary"]["max_tracking_error_mm"] == 1.0
    assert job["result_url"].endswith("/result")
    reused = client.post(base, json={"scenario": "nominal"}).json()
    assert reused["id"] == first["id"]
    result = client.get(url + "/result")
    assert result.status_code == 200
    assert result.json()["status"] == "passed"
    payload = client.get(url + "/files/simulation/model.xml")
    assert payload.status_code == 200
    assert payload.content == _stubbed_files()["simulation/model.xml"]
    files = simjobs.simulation_files_for_project(deepcopy(project))
    assert set(files) == set(simjobs.SIMULATION_FILES)


def test_wrong_project_unknown_file_draft_stale_reject(client):
    project, base = _seed()
    other, other_base = _seed()
    assert other["id"] != project["id"]
    created = client.post(base, json={"scenario": "nominal"}).json()
    url = base + "/" + created["id"]
    job = _wait_job(client, url)
    assert job["status"] == "ready"
    assert client.get(other_base + "/" + created["id"]).status_code == 404
    assert client.get(other_base + "/" + created["id"] + "/result").status_code == 404
    assert client.get(url + "/files/simulation/nope").status_code == 404
    assert client.get(url + "/files/outside.txt").status_code == 404
    draft = new_project()
    api._sessions[draft["id"]] = api.ProjectSession(project=draft)
    draft_base = f"/api/projects/{draft['id']}/simulations"
    assert client.post(draft_base, json={"scenario": "nominal"}).status_code == 409
    stale = configure_project(project, cooling_enabled=True)
    api._sessions[project["id"]].project = stale
    assert client.get(url).status_code == 409
    assert client.get(url + "/result").status_code == 409
    assert client.get(url + "/files/simulation/model.xml").status_code == 409


def test_blocked_ready_result_keeps_blocked_status(client, monkeypatch):
    _stub_engine(monkeypatch, status_for=lambda scenario: "blocked")
    project, base = _seed()
    created = client.post(base, json={"scenario": "blocked_path"}).json()
    assert created["scenario"] == "blocked_path"
    url = base + "/" + created["id"]
    job = _wait_job(client, url)
    assert job["status"] == "ready"
    assert job["completed_steps"] < job["total_steps"]
    result = client.get(url + "/result")
    assert result.status_code == 200
    assert result.json()["status"] == "blocked"
    assert result.json()["scenario"] == "blocked_path"


def test_failure_sanitized_without_partial_files_then_retry(client, monkeypatch):
    def broken(project, scenario="nominal", on_progress=None):
        raise RuntimeError("secret-path-should-not-leak")

    monkeypatch.setattr(simjobs, "_physics_simulate", broken)
    monkeypatch.setattr(simjobs, "_physics_build_files", lambda p, r: dict(_stubbed_files()))
    _, base = _seed()
    created = client.post(base, json={"scenario": "nominal"}).json()
    url = base + "/" + created["id"]
    job = _wait_job(client, url)
    assert job["status"] == "failed"
    assert "secret-path-should-not-leak" not in (job["error"] or "")
    assert client.get(url + "/result").status_code == 409
    assert client.get(url + "/files/simulation/model.xml").status_code == 409
    _stub_engine(monkeypatch)
    retried = client.post(base, json={"scenario": "nominal"}).json()
    assert retried["id"] != created["id"]
    assert _wait_job(client, base + "/" + retried["id"])["status"] == "ready"


def test_active_job_and_stale_revision_guard(client, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def slow(project, scenario="nominal", on_progress=None):
        entered.set()
        if not release.wait(10):
            raise TimeoutError("Test release missing")
        return _synthetic_result(project, scenario)

    monkeypatch.setattr(simjobs, "_physics_simulate", slow)
    monkeypatch.setattr(simjobs, "_physics_build_files", lambda p, r: dict(_stubbed_files()))
    project, base = _seed()
    created = client.post(base, json={"scenario": "nominal"}).json()
    url = base + "/" + created["id"]
    try:
        assert entered.wait(5)
        assert client.post(base, json={"scenario": "nominal"}).json()["id"] == created["id"]
        assert client.post(base, json={"scenario": "blocked_path"}).status_code == 409
        assert client.get(url + "/result").status_code == 409
        changed = configure_project(project, cooling_enabled=True)
        api._sessions[project["id"]].project = changed
        assert client.get(url).status_code == 409
        current = confirm_project(changed)
        api._sessions[project["id"]].project = current
        assert client.post(base, json={"scenario": "nominal"}).status_code == 409
    finally:
        release.set()
    _wait_all_done()
    # Inspect completion internally: the old revision must remain inaccessible via HTTP.
    assert simjobs._jobs[created["id"]]["status"] == "ready"
    assert client.get(url).status_code == 409
    fresh = client.post(base, json={"scenario": "nominal"}).json()
    assert fresh["id"] != created["id"]
    assert _wait_job(client, base + "/" + fresh["id"])["revision"] == current["revision"]
