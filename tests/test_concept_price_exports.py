"""Dated supplier/model records in downloads, never trusted imported quotations."""

import asyncio
import csv
import io
import json
import zipfile
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from test_custom_project_pricing import supplier_fixture
from test_custom_project_routes import client as client
from test_custom_project_routes import install, project_fixture
from test_price_estimation import estimate

import app.api as api
from app import price_estimation as prices
from app import procurement
from app.concept_files import render_asset


def rows(content):
    return list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))


def by_name(content):
    return {row["Part"]: row for row in rows(content)}


def downloaded(client, project, *, asset="parts.csv"):
    result = client.get(
        f"/api/projects/{project['id']}/concept/{asset}", params={"revision": project["revision"]}
    )
    assert result.status_code == 200, result.text
    return result.content


def current_sidecars(monkeypatch, project):
    supplier_fixture(monkeypatch)
    monkeypatch.setitem(
        procurement.PRODUCTS, "pico-h", replace(procurement.PRODUCTS["pico-h"], pack_size=2)
    )
    report = asyncio.run(procurement.refresh_procurement(project))
    ranges, _ = estimate(project, report=report)
    session = api._sessions[project["id"]]
    session.procurement_report, session.cost_estimate = report, ranges
    return report, ranges


def forbid_external_calls(monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("Downloading a package must not fetch prices or call a model.")

    monkeypatch.setattr(procurement, "fetch_product", forbidden)
    monkeypatch.setattr(prices, "estimate_project_prices", forbidden)
    monkeypatch.setattr(api, "refresh_procurement", forbidden)


def test_standalone_and_zip_export_supplier_packs_and_model_ranges_separately(client, monkeypatch):
    project = project_fixture()
    install(project)
    report, ranges = current_sidecars(monkeypatch, project)
    original = deepcopy((project, report, ranges))
    forbid_external_calls(monkeypatch)
    content = downloaded(client, project)
    records = by_name(content)
    board = records["Pico H controller boards"]
    assert board["Supplier item USD"] == "3.75"
    assert board["Supplier pack USD"] == "7.50"
    assert board["Pack size"] == board["Packs to buy"] == "2"
    assert board["Supplier line USD"] == "15.00"
    assert board["Supplier checked at"] == report["rows"][2]["fetched_at"]
    assert board["Supplier price URL"] == procurement.PRODUCTS["pico-h"].url
    assert board["Supplier valid until"] == report["expires_at"]
    assert board["Model low USD"] == board["Model high USD"] == ""
    assert "not a quote" in board["Supplier price status"]
    rail = records["Rail base"]
    assert rail["Supplier item USD"] == rail["Supplier line USD"] == ""
    assert rail["Model low USD"] == "10.00" and rail["Model high USD"] == "25.00"
    assert rail["Model generated at"] == ranges["generated_at"]
    assert rail["Model valid until"] == ranges["expires_at"]
    assert rail["Model source"] == ranges["model"]
    assert "entire listed quantity" in rail["Price scope and exclusions"]
    with zipfile.ZipFile(io.BytesIO(downloaded(client, project, asset="package.zip"))) as archive:
        archived = by_name(archive.read("parts.csv"))
        for name, row in records.items():
            assert {
                key: value for key, value in row.items() if key != "Price record exported at"
            } == {
                key: value
                for key, value in archived[name].items()
                if key != "Price record exported at"
            }
        state = json.loads(archive.read("project.json"))
        assert state == {
            "project_id": project["id"],
            "revision": project["revision"],
            "design": project["concept_design"],
        }
        assert "estimate_id" not in archive.read("project.json").decode()
    assert (project, report, ranges) == original


def test_model_group_totals_are_not_multiplied_by_supply_quantity(client, monkeypatch):
    project = project_fixture()
    install(project)
    ranges, _ = estimate(project)
    api._sessions[project["id"]].cost_estimate = ranges
    forbid_external_calls(monkeypatch)
    board = by_name(downloaded(client, project))["Pico H controller boards"]
    assert board["Quantity"] == "3"
    assert board["Model low USD"] == "10.00" and board["Model high USD"] == "25.00"
    assert board["Supplier price status"] == "Unchecked supplier listing"


@pytest.mark.parametrize("stale", ["revision", "expiry", "scope"])
def test_stale_or_expired_records_cannot_supply_price_figures(client, monkeypatch, stale):
    project = project_fixture()
    install(project)
    report, ranges = current_sidecars(monkeypatch, project)
    if stale == "revision":
        report["project_revision"] -= 1
        ranges["project_revision"] -= 1
    elif stale == "expiry":
        old = (datetime.now(UTC) - timedelta(days=3)).isoformat()
        report["expires_at"] = ranges["expires_at"] = old
        for row in report["rows"]:
            row["fetched_at"] = old
    else:
        report["rows"][2]["quantity"] = 99
        ranges["input_scope_sha256"] = "different purchase scope"
    forbid_external_calls(monkeypatch)
    records = by_name(downloaded(client, project))
    board = records["Pico H controller boards"]
    assert board["Supplier item USD"] == board["Supplier line USD"] == ""
    assert all(row["Model low USD"] == row["Model high USD"] == "" for row in records.values())


def test_unchecked_missing_and_failed_ranges_remain_explicit_and_empty(client, monkeypatch):
    project = project_fixture()
    install(project)
    failed, _ = estimate(project)
    failed["status"] = "failed"
    forbid_external_calls(monkeypatch)
    records = by_name(downloaded(client, project))
    assert (
        records["Pico H controller boards"]["Supplier price status"] == "Unchecked supplier listing"
    )
    assert "Missing price" in records["Rail base"]["Supplier price status"]
    assert all(row["Model estimate status"] == "Not estimated" for row in records.values())
    assert all(row["Supplier line USD"] == row["Model low USD"] == "" for row in records.values())
    api._sessions[project["id"]].cost_estimate = failed
    records = by_name(downloaded(client, project))
    assert all(row["Model low USD"] == row["Model high USD"] == "" for row in records.values())
    assert all("unavailable" in row["Model estimate status"] for row in records.values())


def test_foreign_project_payload_prices_do_not_become_verified_sidecars(client, monkeypatch):
    project = project_fixture()
    install(project)
    report, ranges = current_sidecars(monkeypatch, project)
    project["procurement_report"], project["cost_estimate"] = report, ranges
    api._sessions[project["id"]].procurement_report = None
    api._sessions[project["id"]].cost_estimate = None
    forbid_external_calls(monkeypatch)
    records = by_name(downloaded(client, project))
    assert all(row["Supplier line USD"] == row["Model low USD"] == "" for row in records.values())
    saved = client.get(
        f"/api/projects/{project['id']}/snapshot", params={"revision": project["revision"]}
    )
    api._sessions.clear()
    reopened = client.post("/api/projects/open", content=saved.content)
    assert reopened.status_code == 201, reopened.text
    records = by_name(downloaded(client, reopened.json()["project"]))
    assert all(row["Supplier line USD"] == row["Model low USD"] == "" for row in records.values())


def test_renderer_without_sidecars_preserves_its_original_unpriced_contract():
    project = project_fixture()
    content, _ = render_asset(
        project["concept_design"], project["id"], project["revision"], "parts.csv"
    )
    assert list(rows(content)[0]) == [
        "Part",
        "Quantity",
        "Unit",
        "Source",
        "Reference URL",
        "Local model",
        "US catalog search",
    ]
