"""Real isolated child execution with bounded trusted fixtures, not real source CAD."""

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
import pytest
from test_foundation_storage import source_project

import app.api as api
import app.cad_worker as worker
import app.project_exports as exports
from app.domain import confirm_project

FIXTURE = Path(__file__).with_name("cad_worker_fixture.py")


def use_worker(monkeypatch, mode="normal", marker=None):
    command = [sys.executable, "-I", str(FIXTURE), "--mode", mode]
    if marker is not None:
        command.extend(("--marker", str(marker)))
    monkeypatch.setattr(worker, "_worker_command", lambda: tuple(command))
    processes = []
    original = worker.subprocess.Popen

    def spawn(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append((process, args[0]))
        return process

    monkeypatch.setattr(worker.subprocess, "Popen", spawn)
    return processes


async def wait_marker(path):
    async with asyncio.timeout(5):
        while not path.exists():
            await asyncio.sleep(0.01)


def assert_clean(processes):
    assert not worker._children
    for process, command in processes:
        assert process.poll() is not None
        assert not Path(command[-3]).parent.exists()


def test_actual_child_protocol_copies_only_project_json_and_cleans_up(monkeypatch):
    processes = use_worker(monkeypatch)
    result = asyncio.run(worker.execute_cad({"id": "isolated-synthetic-project"}))
    assert result == {
        "cad/workstation.step": b"offline child CAD fixture: isolated-synthetic-project"
    }
    assert_clean(processes)


@pytest.mark.parametrize("mode", ["error", "bad-zip", "unsafe", "duplicate"])
def test_failed_or_malformed_child_result_never_returns_partial_artifacts(monkeypatch, mode):
    processes = use_worker(monkeypatch, mode)
    with pytest.raises(worker.CadWorkerError):
        asyncio.run(worker.execute_cad({"id": "failed-worker-test"}))
    assert_clean(processes)


def test_timeout_terminates_reaps_and_releases_worker_slot(monkeypatch):
    processes = use_worker(monkeypatch, "hang")
    normal_timeout = worker.CAD_TIMEOUT_SECONDS
    monkeypatch.setattr(worker, "CAD_TIMEOUT_SECONDS", 0.2)
    with pytest.raises(worker.CadWorkerError, match="timed out"):
        asyncio.run(worker.execute_cad({"id": "timeout-test"}))
    assert_clean(processes)
    monkeypatch.setattr(worker, "CAD_TIMEOUT_SECONDS", normal_timeout)
    monkeypatch.setattr(
        worker, "_worker_command", lambda: (sys.executable, "-I", str(FIXTURE), "--mode", "normal")
    )
    assert asyncio.run(worker.execute_cad({"id": "next-job"}))
    assert_clean(processes)


def test_cancellation_stops_gil_holding_child_and_cleans_its_directory(monkeypatch, tmp_path):
    marker = tmp_path / "started.jsonl"
    processes = use_worker(monkeypatch, "hang", marker)

    async def run():
        task = asyncio.create_task(worker.execute_cad({"id": "cancel-test"}))
        await wait_marker(marker)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert_clean(processes)


def test_process_count_is_bounded_to_one_across_concurrent_jobs(monkeypatch, tmp_path):
    marker = tmp_path / "events.jsonl"
    processes = use_worker(monkeypatch, "gil", marker)

    async def run():
        results = await asyncio.gather(
            worker.execute_cad({"id": "job-one"}), worker.execute_cad({"id": "job-two"})
        )
        assert len(results) == 2

    asyncio.run(run())
    events = [json.loads(line) for line in marker.read_text(encoding="utf-8").splitlines()]
    assert [event["phase"] for event in events] == ["start", "end", "start", "end"]
    assert events[2]["time"] >= events[1]["time"]
    assert_clean(processes)


def test_input_and_result_limits_are_enforced_without_unbounded_transfer(monkeypatch):
    processes = use_worker(monkeypatch)
    monkeypatch.setattr(worker, "MAX_INPUT_BYTES", 8)
    with pytest.raises(worker.CadWorkerError, match="input limit"):
        asyncio.run(worker.execute_cad({"id": "too-large"}))
    assert not processes
    monkeypatch.setattr(worker, "MAX_INPUT_BYTES", 1024)
    monkeypatch.setattr(worker, "MAX_RESULT_BYTES", 1)
    with pytest.raises(worker.CadWorkerError):
        asyncio.run(worker.execute_cad({"id": "result-too-large"}))
    assert_clean(processes)


def test_health_project_and_job_status_respond_during_child_c_call_holding_gil(
    monkeypatch, tmp_path
):
    marker = tmp_path / "busy.jsonl"
    processes = use_worker(monkeypatch, "gil", marker)
    project = confirm_project(source_project())
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    latencies = []

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api.app), base_url="http://test"
        ) as client:
            created = await client.post(f"/api/projects/{project['id']}/exports")
            assert created.status_code == 202
            job = created.json()
            await wait_marker(marker)
            # The child is inside a C Sleep/usleep called through PyDLL, which
            # deliberately retains *its* interpreter GIL for 1.25 seconds.
            while exports._jobs[job["id"]]["stage"] == "cad":
                for path in (
                    "/api/health",
                    f"/api/projects/{project['id']}/brief?revision={project['revision']}",
                    f"/api/projects/{project['id']}/exports/{job['id']}",
                ):
                    started = time.monotonic()
                    response = await client.get(path)
                    latencies.append(time.monotonic() - started)
                    assert response.status_code == 200
                await asyncio.sleep(0.02)
            await exports._jobs[job["id"]]["task"]
            assert exports._jobs[job["id"]]["status"] == "ready"
            assert len(latencies) >= 15
            assert max(latencies) < 2

    try:
        asyncio.run(run())
    finally:
        api._sessions.pop(project["id"], None)
        exports._jobs.clear()
    assert_clean(processes)


def test_export_task_cancellation_marks_failed_and_leaves_no_child(monkeypatch, tmp_path):
    marker = tmp_path / "cancel-job.jsonl"
    processes = use_worker(monkeypatch, "hang", marker)

    async def run():
        project = confirm_project(source_project())
        created = await exports.start_export(project)
        await wait_marker(marker)
        job = exports._jobs[created["id"]]
        job["task"].cancel()
        with pytest.raises(asyncio.CancelledError):
            await job["task"]
        assert job["status"] == "failed" and job["files"] == []
        assert "cancelled" in job["error"]
        with pytest.raises(exports.ExportError):
            await exports.export_archive(project, job["id"])

    try:
        asyncio.run(run())
    finally:
        exports._jobs.clear()
    assert_clean(processes)
