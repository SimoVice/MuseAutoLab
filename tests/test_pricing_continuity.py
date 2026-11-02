"""Offline pricing continuity: observations retain their original time and scope."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from test_price_estimation import estimate, project_fixture, supplier_report

import app.api as api
from app import price_estimation as prices
from app import procurement
from app.project_storage import make_snapshot, restore_snapshot


def revision(project):
    result = deepcopy(project)
    result["revision"] += 1
    result["summary"]["target_concentrations"] = "1 mg/mL, 0.2 mg/mL, 0.1 mg/mL"
    result["brief"]["objective"] = "Rephrased recipe request, unchanged machine"
    return result


def test_recipe_rebind_retains_observations_ranges_and_expiry():
    old = project_fixture()
    report = supplier_report(old)
    original, _ = estimate(old, report=report)
    new = revision(old)
    rebound = procurement.rebind_report(old, new, report)
    cost = prices.rebind_estimate(old, new, original, report, rebound)
    assert procurement.report_for_project(new, report) is None  # strict guard unchanged
    assert prices.estimate_for_project(new, original, rebound) is None
    for key in ["report_id", "fetched_at", "expires_at"]:
        assert rebound[key] == report[key]
    for key in ["estimate_id", "generated_at", "expires_at", "model", "usage", "summary"]:
        assert cost[key] == original[key]
    assert not cost["pending_scope_group_ids"]
    assert cost["revision_binding"]["source_revision"] == old["revision"]
    assert cost["project_revision"] == new["revision"]


@pytest.mark.parametrize("change", ["sku", "supplier", "url", "quantity", "size", "geometry"])
def test_changed_purchase_basis_drops_only_affected_observation(change):
    old = project_fixture()
    report = supplier_report(old)
    new = revision(old)
    group = next(g for g in new["sourcing"]["groups"] if g["id"] == "controller")
    selected = next(o for o in group["options"] if o["id"] == group["selected_id"])
    if change == "quantity":
        group["quantity"] += 1
    elif change in ["sku", "supplier"]:
        selected[change] = "different"
    elif change == "url":
        selected["source_url"] += "?different=1"
    else:
        part = next(p for p in new["design"]["components"] if p["id"] in group["component_ids"])
        if change == "size":
            part["size"][0] += 1
        else:
            part["geometry"] = {"kind": "custom", "hole_count": 20}
    rebound = procurement.rebind_report(old, new, report)
    row = next(r for r in rebound["rows"] if r["group_id"] == "controller")
    assert row["line_total"] is None and row["freshness"] == "unverified"


def test_expiry_is_not_revived_and_mismatched_sidecar_cannot_rebind(monkeypatch):
    old = project_fixture()
    report = supplier_report(old)
    expiry = datetime.fromisoformat(report["expires_at"])
    monkeypatch.setattr(procurement, "_now", lambda: expiry + timedelta(seconds=1))
    rebound = procurement.rebind_report(old, revision(old), report)
    row = next(r for r in rebound["rows"] if r["group_id"] == "controller")
    assert row["line_total"] is None and row["last_known_line_total"] == 12
    assert row["freshness"] == "stale" and rebound["expires_at"] == report["expires_at"]
    report["project_revision"] += 99
    assert procurement.rebind_report(old, revision(old), report) is None


def test_expired_allowance_not_rebound(monkeypatch):
    old = project_fixture()
    original, _ = estimate(old)
    after = datetime.fromisoformat(original["expires_at"].replace("Z", "+00:00")) + timedelta(
        seconds=1
    )
    monkeypatch.setattr(prices, "_now", lambda: after)
    assert prices.rebind_estimate(old, revision(old), original, None, None) is None


def test_capability_change_invalidates_allowance_and_internal_rack_spec_is_scope():
    old = project_fixture()
    original, _ = estimate(old)
    new = revision(old)
    new["fabrication_capabilities"] = {"printer_available": "yes"}
    rebound = prices.rebind_estimate(old, new, original, None, None)
    assert set(rebound["pending_scope_group_ids"]) == {"controller", "fixtures"}
    old["labware_rack"] = {"spec": {"count": 12}, "geometry": {"holes": 12}}
    row = {"component_ids": ["sample-rack"]}
    newer = deepcopy(old)
    newer["labware_rack"]["spec"]["count"] = 24
    assert procurement.purchase_scope(old, row) != procurement.purchase_scope(newer, row)


def test_added_scope_get_post_contract_estimates_only_new_group(monkeypatch):
    old = project_fixture()
    original, _ = estimate(old)
    new = revision(old)
    added = deepcopy(new["sourcing"]["groups"][0])
    added["id"] = "inspection-support"
    new["sourcing"]["groups"].append(added)
    session = api.ProjectSession(project=old, cost_estimate=original)
    api._accept_project(session, new)
    seen = []
    actual_estimate = prices.estimate_project_prices

    async def infer(project, procurement_report, *, previous=None):
        assert previous is not None

        def provider(request):
            payload = json.loads(request.content)
            rows = json.loads(payload["messages"][1]["content"])["rows"]
            seen.extend(r["group_id"] for r in rows)
            return httpx.Response(
                200,
                json={
                    "model": prices.ESTIMATE_MODEL,
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": json.dumps(
                                    {
                                        "rows": [
                                            {
                                                "group_id": row["group_id"],
                                                "status": "estimated",
                                                "low_usd": 30,
                                                "high_usd": 90,
                                                "assumptions": ["Synthetic added scope"],
                                                "rationale": "Offline fixture",
                                                "excluded_group_ids": row["excluded_group_ids"],
                                            }
                                            for row in rows
                                        ]
                                    }
                                )
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            return await actual_estimate(
                project,
                procurement_report,
                previous=previous,
                client=client,
                settings=SimpleNamespace(api_key="offline", base_url="https://unit.invalid"),
            )

    monkeypatch.setattr(prices, "estimate_project_prices", infer)
    api._sessions[new["id"]] = session
    try:
        with TestClient(api.app) as client:
            route = f"/api/projects/{new['id']}/cost-estimate"
            read = client.get(route, params={"revision": new["revision"]}).json()
            assert read["state"] == "needs_estimate"
            response = client.post(route, json={"project_revision": new["revision"]})
            assert response.status_code == 200, response.text
            cost = response.json()["estimate"]
            assert cost["status"] == "ready"
            assert cost["expires_at"] == original["expires_at"]
            assert seen == ["inspection-support"]
            for row in cost["rows"]:
                if row["group_id"] != "inspection-support":
                    assert row["low_usd"] == 10 and row["high_usd"] == 25
            assert client.post(route, json={"project_revision": new["revision"]}).status_code == 200
            assert seen == ["inspection-support"]
    finally:
        api._sessions.pop(new["id"], None)


def test_recipe_api_cache_avoids_price_inference(monkeypatch):
    old = project_fixture()
    report = supplier_report(old)
    original, _ = estimate(old, report=report)
    session = api.ProjectSession(project=old, procurement_report=report, cost_estimate=original)
    new = revision(old)
    api._accept_project(session, new)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Unchanged recipe purchase scope must not infer prices again")

    monkeypatch.setattr(prices, "estimate_project_prices", forbidden)
    api._sessions[new["id"]] = session
    try:
        with TestClient(api.app) as client:
            route = f"/api/projects/{new['id']}/cost-estimate"
            assert (
                client.get(route, params={"revision": new["revision"]}).json()["state"] == "current"
            )
            response = client.post(route, json={"project_revision": new["revision"]})
            assert response.status_code == 200
            assert response.json()["estimate"]["summary"] == original["summary"]
    finally:
        api._sessions.pop(new["id"], None)


def test_saved_project_reuses_only_known_matching_runtime_scope(monkeypatch):
    payload = json.loads(Path("docs/examples/presentation-flow-project.json").read_text())
    old, history = restore_snapshot(payload)
    original, _ = estimate(old)
    snapshot = make_snapshot(old, history)
    api._sessions.clear()
    api._sessions[old["id"]] = api.ProjectSession(
        project=old, history=history, cost_estimate=original
    )
    # A newer matching empty copy must not mask the original sidecar.
    empty = deepcopy(old)
    empty["id"] = "00000000-0000-4000-8000-000000000009"
    api._sessions[empty["id"]] = api.ProjectSession(project=empty)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Known saved scope must use cached allowance")

    monkeypatch.setattr(prices, "estimate_project_prices", forbidden)
    try:
        with TestClient(api.app) as client:
            opened = client.post("/api/projects/open", json=snapshot)
            assert opened.status_code == 201, opened.text
            project = opened.json()["project"]
            route = f"/api/projects/{project['id']}/cost-estimate"
            read = client.get(route, params={"revision": project["revision"]}).json()
            assert read["state"] == "current"
            assert read["estimate"]["estimate_id"] == original["estimate_id"]
            assert (
                client.post(route, json={"project_revision": project["revision"]}).status_code
                == 200
            )
            api._sessions.clear()
            unknown = client.post("/api/projects/open", json=snapshot).json()["project"]
            read = client.get(
                f"/api/projects/{unknown['id']}/cost-estimate",
                params={"revision": unknown["revision"]},
            ).json()
            assert read["state"] == "not_estimated" and read["estimate"]["estimate_id"] is None
    finally:
        api._sessions.clear()


def test_actual_jubilee_extension_retains_supplier_facts_and_invalidates_remainder_only():
    from evolution_fixtures import inspection_proposal

    from app.inspection import apply_extension

    payload = json.loads(Path("docs/examples/presentation-flow-project.json").read_text())
    old, _ = restore_snapshot(payload)
    rows = procurement.initial_procurement_rows(old)
    now = datetime.now(UTC)
    for row in rows:
        if row["catalog_supported"]:
            row.update(
                status="priced",
                freshness="fresh",
                line_total=10,
                unit_price=10,
                fetched_at=now.isoformat(),
                issue=None,
            )
    report = {
        "schema_version": 1,
        "report_id": "offline-jubilee-observations",
        "project_id": old["id"],
        "project_revision": old["revision"],
        "market": "US",
        "currency": "USD",
        "rows": rows,
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=15)).isoformat(),
    }
    original, _ = estimate(old, report=report)
    new = apply_extension(old, inspection_proposal(), {"model": "offline-fixture"})
    rebound = procurement.rebind_report(old, new, report)
    cost = prices.rebind_estimate(old, new, original, report, rebound)
    added = {row["group_id"] for row in cost["rows"]} - {
        row["group_id"] for row in original["rows"]
    }
    assert len(added) == 3
    assert set(cost["pending_scope_group_ids"]) == added | {"upstream-platform"}
    assert cost["summary"]["verified_subtotal_usd"] == original["summary"]["verified_subtotal_usd"]
    assert rebound["report_id"] == report["report_id"]
    for row in rebound["rows"]:
        previous = next((r for r in report["rows"] if r["group_id"] == row["group_id"]), None)
        if previous and previous["freshness"] == "fresh":
            assert row == previous


def test_new_scope_provider_failure_preserves_reused_ranges(monkeypatch):
    old = project_fixture()
    original, _ = estimate(old)
    new = revision(old)
    added = deepcopy(new["sourcing"]["groups"][0])
    added["id"] = "inspection-support"
    new["sourcing"]["groups"].append(added)
    seed = prices.rebind_estimate(old, new, original, None, None)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(503, json={"error": "offline-failure"})
            )
        ) as client:
            return await prices.estimate_project_prices(
                new,
                previous=seed,
                client=client,
                settings=SimpleNamespace(api_key="offline", base_url="https://unit.invalid"),
            )

    import asyncio

    result = asyncio.run(run())
    assert result["status"] == "partial" and result["retry_required"]
    for row in result["rows"]:
        if row["group_id"] != "inspection-support":
            assert row["source_kind"] == "model_estimate"
            assert row["low_usd"] == 10 and row["high_usd"] == 25
    assert result["expires_at"] == original["expires_at"]

    # An explicit retry after the failed added-scope request must not reprice
    # accepted old groups, including after another recipe-only transition.
    newer = revision(new)
    carried = prices.rebind_estimate(new, newer, result, None, None)
    assert carried["status"] == "partial" and carried["retry_required"]
    seen = []

    def recovered(request):
        payload = json.loads(request.content)
        rows = json.loads(payload["messages"][1]["content"])["rows"]
        seen.extend(row["group_id"] for row in rows)
        return httpx.Response(
            200,
            json={
                "model": prices.ESTIMATE_MODEL,
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "rows": [
                                        {
                                            "group_id": row["group_id"],
                                            "status": "estimated",
                                            "low_usd": 30,
                                            "high_usd": 90,
                                            "assumptions": ["Synthetic retry"],
                                            "rationale": "Offline fixture",
                                            "excluded_group_ids": row["excluded_group_ids"],
                                        }
                                        for row in rows
                                    ]
                                }
                            )
                        },
                    }
                ],
                "usage": {"total_tokens": 5},
            },
        )

    actual_estimate = prices.estimate_project_prices

    async def retry(project, report, *, previous=None):
        async with httpx.AsyncClient(transport=httpx.MockTransport(recovered)) as client:
            return await actual_estimate(
                project,
                report,
                previous=previous,
                client=client,
                settings=SimpleNamespace(api_key="offline", base_url="https://unit.invalid"),
            )

    monkeypatch.setattr(prices, "estimate_project_prices", retry)
    api._sessions[newer["id"]] = api.ProjectSession(project=newer, cost_estimate=carried)
    try:
        with TestClient(api.app) as client:
            route = f"/api/projects/{newer['id']}/cost-estimate"
            read = client.get(route, params={"revision": newer["revision"]}).json()
            assert read["state"] == "current"  # do not automatically retry on mount
            assert read["estimate"]["status"] == "partial"  # retained range stays visible
            assert read["estimate"]["summary"]["known_plus_estimated_low_usd"] == 20
            response = client.post(
                route, json={"project_revision": newer["revision"], "force": True}
            )
            assert response.status_code == 200, response.text
            recovered_result = response.json()["estimate"]
    finally:
        api._sessions.pop(newer["id"], None)
    assert seen == ["inspection-support"]
    assert recovered_result["status"] == "ready"
    assert recovered_result["expires_at"] == original["expires_at"]
    for row in recovered_result["rows"]:
        if row["group_id"] != "inspection-support":
            assert row["low_usd"] == 10 and row["high_usd"] == 25


def test_accepted_inspection_reply_and_guide_share_derived_footprint(monkeypatch):
    import asyncio

    from evolution_fixtures import inspection_proposal

    import app.inspection as inspection
    from app.instructions import build_instruction_guide

    payload = json.loads(Path("docs/examples/presentation-flow-project.json").read_text())
    project, _ = restore_snapshot(payload)

    async def proposal(*args):
        return inspection_proposal(), {"model": "offline-fixture"}

    monkeypatch.setattr(inspection, "propose_inspection", proposal)
    updated, run = asyncio.run(inspection.develop_inspection(project, "Add camera inspection."))
    assert run["status"] == "accepted"
    bounds = updated["inspection_extension"]["assembly_bounds"]
    width = bounds["max_mm"][0] - bounds["min_mm"][0]
    depth = bounds["max_mm"][2] - bounds["min_mm"][2]
    dimensions = f"{width:.1f} × {depth:.1f} mm"
    notice = inspection.footprint_notice(updated)
    assert dimensions in run["message"]
    assert "Bench depth and collision clearance have not been validated." in run["message"]
    guide = build_instruction_guide(updated)
    assert notice in json.dumps(guide, ensure_ascii=False)


def test_recipe_echoing_unchanged_width_never_develops_a_new_layout(monkeypatch):
    import app.chat_actions as actions
    from app.model_client import ExtractedTurn

    payload = json.loads(Path("docs/examples/presentation-flow-project.json").read_text())
    project, _ = restore_snapshot(payload)
    project["summary"]["workspace_width_mm"] = 800
    original = deepcopy(project["engineering_design"])

    async def extracted(*args):
        return ExtractedTurn.model_validate(
            {
                "assistant_message": "Updated the recipe; same workstation.",
                "stock_concentration": "5 mg/mL",
                "target_concentrations": "1 mg/mL, 0.2 mg/mL, 0.1 mg/mL",
                "final_volume": "150 uL",
                "workspace_width_mm": 800,
            }
        ), {"total_tokens": 5}

    async def forbidden(*args, **kwargs):
        raise AssertionError("An echoed unchanged width must not regenerate geometry")

    monkeypatch.setattr(api, "generate_turn", extracted)
    monkeypatch.setattr(actions, "develop_design", forbidden)
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    try:
        with TestClient(api.app) as client:
            response = client.post(
                f"/api/projects/{project['id']}/messages",
                json={
                    "message": (
                        "Keep the machine layout unchanged. "
                        "Use 150 uL per well; width stays 800 mm."
                    )
                },
            )
            assert response.status_code == 200, response.text
            updated = response.json()["project"]
            assert updated["engineering_design"] == original
            assert updated["summary"]["final_volume"] == "150 uL"
            assert not [
                run for run in response.json()["action_runs"] if run["kind"] == "develop_layout"
            ]
    finally:
        api._sessions.pop(project["id"], None)


def test_observed_constraint_source_failure_stays_strict_and_literal_pair_retains_depth():
    from app.model_client import ExtractedTurn

    message = "My bench remains 800 mm wide and 800 mm deep; keep the design."
    # Synthetic reproduction of provider24's rejected source/value pair.
    failed = ExtractedTurn.model_validate(
        {
            "assistant_message": "Constraints recorded.",
            "brief_constraints": "bench 800 mm wide and 800 mm deep",
            "source_brief_constraints": "800 mm wide and 800 mm deep",
        }
    )
    with pytest.raises(ValueError, match="Brief value must occur in its supporting source"):
        failed.verify_sources(message)
    literal = failed.model_copy(
        update={
            "brief_constraints": "800 mm wide and 800 mm deep",
        }
    )
    literal.verify_sources(message)
    assert "wide" in literal.brief_constraints and "deep" in literal.brief_constraints
