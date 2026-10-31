"""Offline price-range boundaries; mocked model outputs are not live estimates."""

import asyncio
import csv
import io
import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from app import price_estimation as prices
from app import procurement
from app.assembly import build_document_files
from app.domain import new_project
from app.foundation_design import foundation_sourcing
from app.instructions import build_instruction_guide


def project_fixture():
    project = new_project()
    project["engineering_design"] = {
        "schema_version": "offline-cost-unit-fixture",
        "proposal": {"rationale": "Synthetic offline cost-test layout."},
        "provenance": {"model": "offline-fixture"},
    }
    project["sourcing"]["groups"] = [
        g for g in project["sourcing"]["groups"] if g["id"] in {"controller", "fixtures"}
    ]
    return project


def response_rows(project, report=None):
    return [
        {
            "group_id": row["group_id"],
            "status": "estimated",
            "low_usd": 10.0,
            "high_usd": 25.0,
            "assumptions": ["Synthetic test assumes one purchase group."],
            "rationale": "Offline model fixture; material cost only, not a supplier quote.",
            "excluded_group_ids": row["excluded_group_ids"],
        }
        for row in prices.price_context(project, report)["rows"]
        if row["source_kind"] == "unknown"
    ]


def supplier_report(project, *, price=12.0):
    rows = procurement.initial_procurement_rows(project)
    now = datetime.now(UTC)
    row = next(row for row in rows if row["group_id"] == "controller")
    row.update(
        status="priced",
        freshness="fresh",
        line_total=price,
        unit_price=price,
        fetched_at=now.isoformat(),
        pack_price=price,
        issue=None,
    )
    return {
        "schema_version": 1,
        "report_id": "offline-supplier-report",
        "project_id": project["id"],
        "project_revision": project["revision"],
        "market": "US",
        "currency": "USD",
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=15)).isoformat(),
        "rows": rows,
        "exclusions": [],
    }


def estimate(project, rows=None, report=None, *, http_status=200, finish="stop", handler=None):
    calls = []
    rows = response_rows(project, report) if rows is None else rows

    def provider(request):
        calls.append(json.loads(request.content))
        if handler:
            return handler(request)
        return httpx.Response(
            http_status,
            json={
                "model": prices.ESTIMATE_MODEL,
                "choices": [
                    {"finish_reason": finish, "message": {"content": json.dumps({"rows": rows})}}
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            return await prices.estimate_project_prices(
                project,
                report,
                client=client,
                settings=SimpleNamespace(
                    api_key="offline-only", base_url="https://unit.invalid/v1"
                ),
            )

    return asyncio.run(run()), calls


def test_one_spark_call_and_revision_bound_group_total_without_mutation():
    project = project_fixture()
    original = deepcopy(project)
    result, calls = estimate(project)
    assert project == original and len(calls) == 1
    assert calls[0]["model"] == prices.ESTIMATE_MODEL
    assert calls[0]["max_completion_tokens"] == 4800
    assert result["status"] == "ready" and result["project_revision"] == project["revision"]
    assert result["summary"]["project_total_low_usd"] == 20
    assert result["summary"]["project_total_high_usd"] == 50
    assert result["usage"]["total_tokens"] == 140
    assert all(
        r["price_basis"] == "group_total" and r["price_source_url"] is None for r in result["rows"]
    )
    assert prices.estimate_for_project(project, result) == result


def test_verified_pack_total_wins_and_is_never_multiplied_again(monkeypatch):
    project = project_fixture()
    project["sourcing"]["groups"][0]["quantity"] = 4
    monkeypatch.setitem(
        procurement.PRODUCTS, "pico", replace(procurement.PRODUCTS["pico"], pack_size=3)
    )
    report = supplier_report(project)
    report["rows"][0].update(pack_size=3, pack_count=2, unit_price=2, pack_price=6, line_total=12)
    original = deepcopy(report)
    result, calls = estimate(project, report=report)
    assert len(calls) == 1 and report == original
    inputs = json.loads(calls[0]["messages"][1]["content"])
    assert [r["group_id"] for r in inputs["rows"]] == ["fixtures"]
    verified = next(r for r in result["rows"] if r["group_id"] == "controller")
    assert verified["low_usd"] == verified["high_usd"] == 12
    assert verified["pack_count"] == 2 and verified["quantity"] == 4
    assert result["summary"]["project_total_low_usd"] == 22


def test_parent_remainder_excludes_all_candidate_kits_and_no_double_count():
    project = project_fixture()
    project["sourcing"] = foundation_sourcing(project)
    context = prices.price_context(project)
    parent = next(r for r in context["rows"] if r["group_id"] == "upstream-platform")
    children = [r for r in context["rows"] if r["parent_group_id"] == "upstream-platform"]
    assert len(children) == 6
    assert {r["group_id"] for r in children} <= set(parent["excluded_group_ids"])
    assert set(parent["excluded_group_ids"]) == {
        r["group_id"] for r in context["rows"] if r["group_id"] != "upstream-platform"
    }
    rows = response_rows(project)
    result, _ = estimate(project, rows)
    assert result["status"] == "ready"
    assert result["summary"]["project_total_low_usd"] == len(rows) * 10
    next(r for r in rows if r["group_id"] == "upstream-platform")["excluded_group_ids"] = []
    failed, calls = estimate(project, rows)
    assert len(calls) == 1 and failed["status"] == "failed"
    assert failed["summary"]["project_total_low_usd"] is None


@pytest.mark.parametrize(
    "mutation",
    [
        "zero",
        "negative",
        "nan",
        "boolean",
        "reversed",
        "equal",
        "missing",
        "extra",
        "duplicate",
        "url",
        "no_assumptions",
        "wrong_units",
        "round_to_zero",
    ],
)
def test_malformed_model_output_is_an_honest_failure_not_zero(mutation):
    project = project_fixture()
    rows = response_rows(project)
    if mutation == "zero":
        rows[0]["low_usd"] = 0
    elif mutation == "negative":
        rows[0]["low_usd"] = -1
    elif mutation == "nan":
        rows[0]["low_usd"] = float("nan")
    elif mutation == "boolean":
        rows[0]["low_usd"] = True
    elif mutation == "reversed":
        rows[0]["low_usd"] = 50
    elif mutation == "equal":
        rows[0]["low_usd"] = 25
    elif mutation == "missing":
        rows.pop()
    elif mutation == "extra":
        rows[0]["group_id"] = "another-supplier-sku"
    elif mutation == "duplicate":
        rows[1] = deepcopy(rows[0])
    elif mutation == "url":
        rows[0]["rationale"] = "Price from https://invented.invalid"
    elif mutation == "no_assumptions":
        rows[0]["assumptions"] = []
    elif mutation == "wrong_units":
        rows[0]["unit_price"] = 10
    else:
        rows[0].update(low_usd=0.001, high_usd=0.002)
    result, calls = estimate(project, rows)
    assert len(calls) == 1 and result["status"] == "failed"
    assert result["summary"]["project_total_low_usd"] is None
    assert all(r["low_usd"] is None and r["source_kind"] == "unknown" for r in result["rows"])


def test_unknown_and_failure_keep_verified_prices_separate():
    project = project_fixture()
    report = supplier_report(project)
    rows = response_rows(project, report)
    rows[0].update(status="unknown", low_usd=None, high_usd=None, assumptions=[])
    result, _ = estimate(project, rows, report)
    assert result["status"] == "partial" and result["summary"]["missing_count"] == 1
    assert "omitted planning allowances" in result["issue"]
    assert result["summary"]["verified_subtotal_usd"] == 12
    assert result["summary"]["project_total_high_usd"] is None
    failure, calls = estimate(project, report=report, http_status=503)
    assert len(calls) == 1 and failure["status"] == "failed"
    assert failure["summary"]["verified_subtotal_usd"] == 12
    assert failure["summary"]["known_plus_estimated_low_usd"] == 12
    assert failure["summary"]["project_total_low_usd"] is None


def test_timeout_and_truncation_never_retry_or_accept_partial_prices():
    project = project_fixture()

    def timeout(request):
        raise httpx.ReadTimeout("offline timeout", request=request)

    for kwargs in ({"handler": timeout}, {"finish": "length"}):
        result, calls = estimate(project, **kwargs)
        assert len(calls) == 1 and result["status"] == "failed"
        assert result["summary"]["project_total_low_usd"] is None


def test_revisions_scopes_and_expiry_are_checked_and_stale_read_is_idempotent():
    project = project_fixture()
    result, _ = estimate(project)
    changed = deepcopy(project)
    changed["revision"] += 1
    assert prices.estimate_for_project(changed, result) is None
    changed = deepcopy(project)
    changed["sourcing"]["groups"][0]["quantity"] += 1
    assert prices.estimate_for_project(changed, result) is None
    at = datetime.now(UTC) + timedelta(days=2)
    stale = prices.estimate_for_project(project, result, now=at)
    assert stale["status"] == "stale"
    assert stale["summary"]["project_total_low_usd"] is None
    assert stale["last_known_summary"]["project_total_low_usd"] == 20
    assert prices.estimate_for_project(project, stale, now=at) == stale
    invalid = deepcopy(result)
    invalid["rows"][0]["low_usd"] = -200
    assert prices.estimate_for_project(project, invalid) is None


def test_new_supplier_observation_overrides_model_range_without_reestimating():
    project = project_fixture()
    result, _ = estimate(project)
    fresh = prices.estimate_for_project(project, result, supplier_report(project, price=7))
    assert fresh["summary"]["verified_subtotal_usd"] == 7
    assert fresh["summary"]["project_total_low_usd"] == 17
    assert fresh["summary"]["estimated_count"] == 1


def test_instruction_downloads_escape_estimates_and_keep_supplier_csv_separate():
    project = project_fixture()
    rows = response_rows(project)
    rows[0]["assumptions"] = ["<script>alert('unsafe')</script> synthetic material"]
    report, _ = estimate(project, rows)
    project["cost_estimate"] = report
    guide = build_instruction_guide(project)
    assert guide["cost_estimate"] == report
    files = build_document_files(project)
    assert json.loads(files["cost-estimate.json"]) == report
    assert b"&lt;script&gt;" in files["assembly-guide.html"]
    assert b"<script>alert" not in files["assembly-guide.html"]
    assert b"Project cost planning range" in files["assembly-guide.md"]
    records = list(csv.DictReader(io.StringIO(files["cost-estimate.csv"].decode())))
    assert (
        records[0]["price_basis"] == "group_total" and records[0]["source_kind"] == "model_estimate"
    )
    assert b"model_estimate" not in files["bill-of-materials.csv"]


def test_prompt_requires_broad_allowances_not_exact_specs_or_printer_ownership():
    project = project_fixture()
    project["sourcing"] = foundation_sourcing(project)
    project["fabrication_capabilities"] = {"printer_access": "unknown"}
    original = deepcopy(project)
    result, calls = estimate(project)
    prompt = calls[0]["messages"][0]["content"]
    assert "For EVERY understood group" in prompt
    assert "NOT reasons for unknown" in prompt
    assert "outsourced fabrication service" in prompt
    assert "NEVER a recorded printer capability" in prompt
    assert "all other separately budgeted groups" in prompt
    assert "never exact catalog evidence" in prompt
    inputs = json.loads(calls[0]["messages"][1]["content"])
    basis = {row["group_id"]: row["allowance_basis"] for row in inputs["rows"]}
    for group_id in ("upstream-platform", "pipette", "fixtures", "power"):
        assert basis[group_id]["understood"] and basis[group_id]["scope_items"]
    assert "not automatic refusal" in " ".join(basis["fixtures"]["planning_assumptions"])
    assert project == original and result["summary"]["coverage_complete"]
