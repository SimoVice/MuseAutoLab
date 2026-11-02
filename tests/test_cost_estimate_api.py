"""Revision/race/cache boundaries with mocked estimates; no live provider calls."""

import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from test_price_estimation import estimate, project_fixture, supplier_report

import app.api as api
from app import price_estimation as prices


@pytest.fixture(autouse=True)
def sessions():
    api._sessions.clear()
    yield
    api._sessions.clear()


def seed():
    project = project_fixture()
    api._sessions[project["id"]] = api.ProjectSession(project=deepcopy(project))
    return project, f"/api/projects/{project['id']}"


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://unit")


def test_read_endpoint_never_infers_and_requires_current_revision(monkeypatch):
    project, prefix = seed()

    async def forbidden(*args, **kwargs):
        pytest.fail("A GET must not make an estimation request")

    monkeypatch.setattr(prices, "estimate_project_prices", forbidden)

    async def run():
        async with client() as active:
            response = await active.get(
                prefix + "/cost-estimate", params={"revision": project["revision"]}
            )
            assert response.status_code == 200
            assert response.json()["state"] == "not_estimated"
            assert response.json()["estimate"]["summary"]["project_total_low_usd"] is None
            assert (
                await active.get(prefix + "/cost-estimate", params={"revision": 99})
            ).status_code == 409
            assert (
                await active.post(prefix + "/cost-estimate", json={"project_revision": 99})
            ).status_code == 409

    asyncio.run(run())
    assert api._sessions[project["id"]].project == project


def test_no_design_blocks_provider_before_any_call(monkeypatch):
    project, prefix = seed()
    api._sessions[project["id"]].project.pop("engineering_design")

    async def forbidden(*args, **kwargs):
        pytest.fail("No design must not make a model request")

    monkeypatch.setattr(prices, "estimate_project_prices", forbidden)

    async def run():
        async with client() as active:
            response = await active.post(
                prefix + "/cost-estimate", json={"project_revision": project["revision"]}
            )
            assert response.status_code == 409

    asyncio.run(run())


def test_concurrent_posts_share_one_estimate_and_keep_canonical_state(monkeypatch):
    project, prefix = seed()
    ready, _ = estimate(project)
    calls = []

    async def mock(project_copy, report):
        calls.append(project_copy)
        await asyncio.sleep(0.02)
        return deepcopy(ready)

    monkeypatch.setattr(prices, "estimate_project_prices", mock)

    async def run():
        async with client() as active:
            responses = await asyncio.gather(
                *[
                    active.post(
                        prefix + "/cost-estimate", json={"project_revision": project["revision"]}
                    )
                    for _ in range(2)
                ]
            )
            assert all(r.status_code == 200 for r in responses)
            assert responses[0].json()["estimate"]["estimate_id"] == ready["estimate_id"]
            assert responses[1].json()["estimate"]["estimate_id"] == ready["estimate_id"]
            guide = await active.get(
                prefix + "/instructions", params={"revision": project["revision"]}
            )
            assert guide.json()["cost_estimate"] == ready
            download = await active.get(
                prefix + "/instructions/download",
                params={"revision": project["revision"], "format": "json"},
            )
            assert json.loads(download.content)["cost_estimate"] == ready

    asyncio.run(run())
    assert len(calls) == 1 and api._sessions[project["id"]].project == project
    assert "cost_estimate" not in project


@pytest.mark.parametrize("race", ["revision", "supplier"])
def test_changed_project_or_supplier_discards_delayed_estimate(monkeypatch, race):
    project, prefix = seed()
    ready, _ = estimate(project)

    async def mock(project_copy, report):
        session = api._sessions[project["id"]]
        if race == "revision":
            session.project["revision"] += 1
        else:
            session.procurement_report = supplier_report(project)
        await asyncio.sleep(0)
        return ready

    monkeypatch.setattr(prices, "estimate_project_prices", mock)

    async def run():
        async with client() as active:
            response = await active.post(
                prefix + "/cost-estimate", json={"project_revision": project["revision"]}
            )
            assert response.status_code == 409

    asyncio.run(run())
    assert api._sessions[project["id"]].cost_estimate is None


def test_stale_range_is_explicit_and_post_can_refresh_it(monkeypatch):
    project, prefix = seed()
    ready, _ = estimate(project)
    expired = deepcopy(ready)
    expired["expires_at"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    api._sessions[project["id"]].cost_estimate = expired
    calls = []

    async def mock(candidate, procurement, *, previous=None):
        assert previous["estimate_id"] == expired["estimate_id"]
        assert previous["expires_at"] == expired["expires_at"]
        assert previous["status"] == "stale"
        stale = prices.estimate_for_project(candidate, previous, procurement)
        assert stale["status"] == "stale"
        assert stale["summary"]["project_total_low_usd"] is None
        assert not any(row["source_kind"] == "model_estimate" for row in stale["rows"])
        calls.append(1)
        return ready

    monkeypatch.setattr(prices, "estimate_project_prices", mock)

    async def run():
        async with client() as active:
            read = await active.get(
                prefix + "/cost-estimate", params={"revision": project["revision"]}
            )
            assert read.json()["estimate"]["status"] == "stale"
            assert read.json()["estimate"]["summary"]["project_total_low_usd"] is None
            refreshed = await active.post(
                prefix + "/cost-estimate", json={"project_revision": project["revision"]}
            )
            assert refreshed.json()["estimate"]["status"] == "ready"

    asyncio.run(run())
    assert len(calls) == 1


def test_failed_range_is_visible_and_not_retried_implicitly(monkeypatch):
    project, prefix = seed()
    calls = []

    async def mock(*args):
        calls.append(1)
        failed = prices.unestimated_cost(project)
        failed.update(status="failed", issue="Offline provider failed", estimate_id="failed-call")
        return failed

    monkeypatch.setattr(prices, "estimate_project_prices", mock)

    async def run():
        async with client() as active:
            response = await active.post(
                prefix + "/cost-estimate", json={"project_revision": project["revision"]}
            )
            assert response.status_code == 200 and response.json()["estimate"]["status"] == "failed"
            read = await active.get(
                prefix + "/cost-estimate", params={"revision": project["revision"]}
            )
            assert read.json()["estimate"]["summary"]["project_total_low_usd"] is None

    asyncio.run(run())
    assert calls == [1]


def test_force_explicitly_bypasses_cached_partial_but_default_posts_deduplicate(monkeypatch):
    project, prefix = seed()
    partial = prices.unestimated_cost(project)
    partial.update(estimate_id="partial-first", status="partial")
    api._sessions[project["id"]].cost_estimate = partial
    ready, _ = estimate(project)
    calls = []

    async def mock(*args):
        calls.append(1)
        return ready

    monkeypatch.setattr(prices, "estimate_project_prices", mock)

    async def run():
        async with client() as active:
            payload = {"project_revision": project["revision"]}
            cached = await active.post(prefix + "/cost-estimate", json=payload)
            assert cached.json()["estimate"]["estimate_id"] == "partial-first"
            assert calls == []
            refreshed = await active.post(
                prefix + "/cost-estimate", json={**payload, "force": True}
            )
            assert refreshed.json()["estimate"]["estimate_id"] == ready["estimate_id"]
            assert calls == [1]
            again = await active.post(prefix + "/cost-estimate", json=payload)
            assert again.json()["estimate"]["estimate_id"] == ready["estimate_id"]
            assert calls == [1]

    asyncio.run(run())
