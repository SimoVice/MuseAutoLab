"""Independent reconciliation checks for the reusable parts proposal."""

from copy import deepcopy

from test_bench_station_procurement import station_project
from test_custom_project_routes import client as client
from test_custom_project_routes import project_fixture
from test_foundation_storage import source_project
from test_price_estimation import estimate

import app.api as api
from app.parts_proposal import build_parts_proposal, cold_transfer_candidate_rows
from app.platform_profiles import commercial_sourcing
from app.procurement import project_with_report


def test_generic_quantities_unit_allocation_and_sum_are_canonical():
    project = project_fixture()
    before = deepcopy(project)
    result = build_parts_proposal(project)
    assert project == before
    assert len(result["rows"]) == 4
    boards = next(r for r in result["rows"] if r["group_id"] == "concept-controller_board")
    assert boards["quantity"] == 3 and boards["unit"] == "board"
    assert boards["line_total_low_usd"] == 3 * boards["unit_price_low_usd"]
    assert boards["evidence"]["url"] is None
    assert boards["price_kind"] == "planning_allowance"
    assert boards["source_url"].startswith("https://www.adafruit.com/")
    assert result["summary"]["total_low_usd"] == sum(
        r["line_total_low_usd"] for r in result["rows"]
    )
    assert all(r["assembly_steps"] for r in result["rows"])
    assert "Level the rail base" in result["rows"][0]["assembly_steps"][0]["instruction"]


def test_model_group_totals_are_not_multiplied_by_quantity_again():
    project = project_fixture()
    cost, _ = estimate(project)
    result = build_parts_proposal(project, estimate=cost)
    assert result["summary"]["total_low_usd"] == 40
    assert result["summary"]["total_high_usd"] == 100
    assert all(r["price_kind"] == "model_estimate" for r in result["rows"])
    assert project_with_report(project, None, cost)["parts_proposal"] == result
    revised = deepcopy(project)
    revised["revision"] += 1
    assert all(
        r["price_kind"] == "planning_allowance"
        for r in build_parts_proposal(revised, estimate=cost)["rows"]
    )


def test_bench_and_source_cad_use_their_own_groups():
    bench = build_parts_proposal(station_project(["weigh", "inspect"]))
    assert len(bench["rows"]) == 4
    assert all(r["group_id"].startswith("bench-") for r in bench["rows"])
    foundation = build_parts_proposal(source_project())
    ids = {r["group_id"] for r in foundation["rows"]}
    assert "upstream-platform" in ids
    assert "motors" not in ids
    assert len(ids) == len(foundation["rows"])
    assert foundation["summary"]["total_high_usd"] > foundation["summary"]["total_low_usd"] > 0


def test_cold_candidates_are_reviewed_options_not_silent_hardware_additions():
    project = source_project()
    before = deepcopy(project)
    rows = cold_transfer_candidate_rows(project)
    assert project == before
    assert [r["group_id"] for r in rows] == ["cold-transfer-fridge", "cold-transfer-motion"]
    assert rows[0]["line_total_low_usd"] == 900
    assert rows[1]["line_total_high_usd"] == 1200
    assert all(
        r["evidence"]["kind"] == "planning_allowance" and r["evidence"]["url"] is None for r in rows
    )
    assert "NOT replaced" in rows[0]["assembly_steps"][0]["instruction"]
    assert "NOT established" in rows[1]["assembly_steps"][0]["instruction"]
    assert rows[1]["alternatives"][0]["label"].startswith("Hudson")


def test_parts_endpoint_enforces_revision_and_never_changes_project(client):
    project = project_fixture()
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    before = deepcopy(project)
    url = f"/api/projects/{project['id']}/parts"
    response = client.get(url, params={"revision": project["revision"]})
    assert response.status_code == 200
    assert response.json() == build_parts_proposal(project)
    assert api._sessions[project["id"]].project == before
    assert client.get(url, params={"revision": project["revision"] + 1}).status_code == 409


def test_commercial_base_includes_one_pipette_without_double_counting():
    project = source_project()
    project["design"] = {"platform": {"id": "opentrons-ot2"}}
    project["sourcing"] = commercial_sourcing()
    result = build_parts_proposal(project)
    rows = {r["group_id"]: r for r in result["rows"]}
    assert rows["platform"]["line_total_low_usd"] == 15950
    assert rows["pipettes"]["price_kind"] == "included_in_base"
    assert rows["pipettes"]["line_total_high_usd"] == 0
    assert result["summary"]["total_low_usd"] == (15950 + rows["labware"]["line_total_low_usd"])


def test_all_routes_have_actionable_sources_and_honest_unit_basis():
    for project in (source_project(), project_fixture(), station_project()):
        result = build_parts_proposal(project)
        for row in result["rows"]:
            assert row["source_url"].startswith("https://")
            assert row["selected_product_label"]
            assert row["source_kind"]
            assert "not a quoted unit price" in row["unit_price_basis"]
            assert row["line_total_high_usd"] >= row["line_total_low_usd"]


def test_real_rack_and_holder_standalone_downloads_are_revision_bound(client):
    from test_labware import rack_project
    from test_microplates import select

    for project in (rack_project(), select(rack_project())):
        api._sessions[project["id"]] = api.ProjectSession(project=project)
        proposal = build_parts_proposal(project)
        row = next(
            r for r in proposal["rows"] if r["group_id"] in ("labware-rack", "labware-plate")
        )
        assert row["fabrication_url"].startswith(f"/api/projects/{project['id']}/parts/")
        response = client.get(row["fabrication_url"])
        assert response.status_code == 200, response.text[:200]
        assert b"ISO-10303-21" in response.content[:100]
        assert len(response.content) > 1000
        assert (
            client.get(
                row["fabrication_url"].replace(
                    f"revision={project['revision']}", f"revision={project['revision'] + 1}"
                )
            ).status_code
            == 409
        )


def test_incomplete_legacy_report_is_not_promoted_to_supplier_price():
    project = project_fixture()
    report = {
        "project_id": project["id"],
        "project_revision": project["revision"],
        "report_id": "legacy-document-only",
        "rows": [],
    }
    assert all(
        r["price_kind"] == "planning_allowance"
        for r in build_parts_proposal(project, report)["rows"]
    )


def test_tip_profiles_keep_supplier_price_scope_and_only_printed_model_download(client):
    from test_microplates import before
    from test_tip_racks import OPENTRONS, PRINTED_ID, SPEC, TIPONE, selected

    from app.tip_racks import TipRackUpdate, select_tip_rack

    printed = before()
    printed["fabrication_capabilities"] = {"printer_available": "yes", "source": "Test printer"}
    printed["tip_rack_request"] = {
        "profile_id": PRINTED_ID,
        "spec": SPEC,
        "spec_sources": {k: "Synthetic fixture" for k in SPEC},
    }
    printed, _ = select_tip_rack(
        printed, TipRackUpdate(), "Use the printed holder", accept_placement=True
    )
    cases = (
        (selected(profile=TIPONE), "USA Scientific TipOne 200", "usascientific.com", 30, 120),
        (selected(profile=OPENTRONS), "Opentrons OT-2 300", "opentrons.com", 40, 160),
        (printed, "Custom printed holder", "protolabs.com", 30, 200),
    )
    for project, label, domain, low, high in cases:
        api._sessions[project["id"]] = api.ProjectSession(project=project)
        response = client.get(f"/api/projects/{project['id']}/parts?revision={project['revision']}")
        assert response.status_code == 200
        row = next(r for r in response.json()["rows"] if r["group_id"] == "tip-rack-options")
        assert row["selected_product_label"].startswith(label)
        assert domain in row["source_url"]
        assert (row["line_total_low_usd"], row["line_total_high_usd"]) == (low, high)
        assert row["price_kind"] == "planning_allowance"
        if project["tip_rack"]["kind"] == "rim_supported_tip_rack":
            assert client.get(row["fabrication_url"]).status_code == 200
            assert client.get(row["fabrication_stl_url"]).status_code == 200
            assert "separate pack" in row["price_note"]
            assert any("disposable tips separately" in a["label"] for a in row["alternatives"])
        else:
            assert "fabrication_url" not in row
            assert (
                client.get(
                    f"/api/projects/{project['id']}/parts/tip-rack/model.step?revision={project['revision']}"
                ).status_code
                == 404
            )
