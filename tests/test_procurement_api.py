"""Revision and cancellation boundaries for explicit supplier refreshes."""

import asyncio
from copy import deepcopy

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_foundation_storage import source_project

import app.api as api
from app.procurement import refresh_procurement


@pytest.fixture
def client(monkeypatch):
    api._sessions.clear()

    async def offline(project):
        project = deepcopy(project)
        project["sourcing"]["groups"] = []
        return await refresh_procurement(project)

    monkeypatch.setattr(api, "refresh_procurement", offline)
    with TestClient(api.app) as client:
        yield client
    api._sessions.clear()


def machine(client):
    project = source_project()
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    return project


def test_get_does_not_fetch_and_refresh_is_explicit_design_bound(client, monkeypatch):
    project = client.post("/api/projects").json()["project"]
    url = f"/api/projects/{project['id']}/procurement"
    assert client.get(url, params={"revision": project["revision"]}).json() == {
        "report": None,
        "state": "not_refreshed",
    }
    result = client.post(url + "/refresh", json={"project_revision": project["revision"]})
    assert result.status_code == 409
    assert client.get(url, params={"revision": project["revision"] + 1}).status_code == 409


def test_refresh_report_download_and_saved_design_remain_separate(client):
    project = machine(client)
    before = deepcopy(project)
    url = f"/api/projects/{project['id']}/procurement"
    result = client.post(url + "/refresh", json={"project_revision": project["revision"]})
    assert result.status_code == 200
    report = result.json()["report"]
    assert (
        report["project_id"] == project["id"] and report["project_revision"] == project["revision"]
    )
    assert api._sessions[project["id"]].project == before
    assert "procurement_report" not in project
    assert (
        client.get(url, params={"revision": project["revision"]}).json()["report"]["report_id"]
        == report["report_id"]
    )
    query = {"revision": project["revision"], "report_id": report["report_id"]}
    assert client.get(url + "/download", params=query).json()["report_id"] == report["report_id"]
    assert (
        client.get(url + "/download", params={**query, "format": "csv"})
        .headers["content-type"]
        .startswith("text/csv")
    )
    assert client.get(url + "/download", params={**query, "report_id": "other"}).status_code == 409
    assert client.get(url + "/download", params={**query, "format": "exe"}).status_code == 422
    project["revision"] += 1
    assert client.get(url, params={"revision": project["revision"]}).json() == {
        "state": "stale_revision",
        "report": None,
    }
    assert client.get(url + "/download", params=query).status_code == 409


def test_revision_change_during_network_does_not_publish_old_report(client, monkeypatch):
    project = machine(client)
    revision = project["revision"]
    original = api.refresh_procurement

    async def slow(project_copy):
        report = await original(project_copy)
        api._sessions[project_copy["id"]].project["revision"] += 1
        return report

    monkeypatch.setattr(api, "refresh_procurement", slow)
    result = client.post(
        f"/api/projects/{project['id']}/procurement/refresh", json={"project_revision": revision}
    )
    assert result.status_code == 409
    assert api._sessions[project["id"]].procurement_report is None


def test_refresh_payload_has_no_caller_supplied_supplier_url(client):
    project = machine(client)
    url = f"/api/projects/{project['id']}/procurement/refresh"
    for payload in (
        {"project_revision": True},
        {"project_revision": "1"},
        {"project_revision": project["revision"], "url": "http://localhost"},
    ):
        assert client.post(url, json=payload).status_code == 422


def test_disconnect_cancels_inflight_supplier_work():
    cancelled = []

    class Request:
        async def is_disconnected(self):
            await asyncio.sleep(0)
            return True

    async def network():
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.append(True)

    async def run():
        with pytest.raises(HTTPException) as error:
            await api._refresh_procurement_connected(Request(), network())
        assert error.value.status_code == 499

    asyncio.run(run())
    assert cancelled == [True]


def test_export_uses_detached_current_report_without_network_or_design_mutation(
    client, monkeypatch
):
    project = machine(client)
    url = f"/api/projects/{project['id']}"
    report = client.post(
        url + "/procurement/refresh", json={"project_revision": project["revision"]}
    ).json()["report"]
    captured = []

    async def start(snapshot):
        captured.append(snapshot)
        return {
            "status": "queued",
            "procurement_report_id": snapshot["procurement_report"]["report_id"],
        }

    monkeypatch.setattr(api, "start_export", start)
    response = client.post(url + "/exports")
    assert response.status_code == 202
    assert captured[0]["procurement_report"]["report_id"] == report["report_id"]
    assert "procurement_report" not in project


def test_instruction_preview_downloads_bind_current_revision_and_report(client):
    project = machine(client)
    url = f"/api/projects/{project['id']}"
    revision = project["revision"]
    fallback = client.get(url + "/instructions", params={"revision": revision})
    assert fallback.status_code == 200
    assert fallback.json()["procurement_report_id"] is None
    report = client.post(url + "/procurement/refresh", json={"project_revision": revision}).json()[
        "report"
    ]
    guide = client.get(url + "/instructions", params={"revision": revision}).json()
    assert guide["procurement_report_id"] == report["report_id"]
    assert "procurement_report" not in project
    for format in ("html", "md", "json"):
        result = client.get(
            url + "/instructions/download",
            params={
                "revision": revision,
                "report_id": report["report_id"],
                "format": format,
            },
        )
        assert result.status_code == 200
        assert report["report_id"] in result.text
    assert (
        client.get(
            url + "/instructions/download", params={"revision": revision, "report_id": "wrong"}
        ).status_code
        == 409
    )
    assert client.get(url + "/instructions", params={"revision": revision + 1}).status_code == 409
