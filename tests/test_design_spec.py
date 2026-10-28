"""Acceptance boundaries for proposed workstation geometry."""

from copy import deepcopy

import pytest

from app.design_spec import apply_candidate, check_candidate, proposal_schema
from app.domain import apply_update, confirm_project, new_project
from app.geometry import add_geometry

COMPLETE = {
    "stock_concentration": "10 mM",
    "target_concentrations": "1 mM, 2 mM",
    "final_volume": "100 uL",
    "equipment": "pipette and tubes",
    "workspace_width_mm": 650,
}


def proposal():
    return {
        "schema_version": "1", "deck_width_mm": 600, "deck_depth_mm": 400,
        "placements": [
            {"component_id": "source-rack", "x_mm": -180, "z_mm": -50},
            {"component_id": "sample-rack", "x_mm": -65, "z_mm": -50},
            {"component_id": "tip-rack", "x_mm": 50, "z_mm": -50},
            {"component_id": "tip-waste", "x_mm": 165, "z_mm": 80},
            {"component_id": "controller", "x_mm": 165, "z_mm": -50},
        ],
        "rationale": "Keep the sample rack accessible.", "assumptions": ["Concept envelopes."],
    }


def project(**changes):
    return apply_update(new_project(), {**COMPLETE, **changes})


def failed(checks):
    return {entry["id"] for entry in checks if not entry["passed"]}


def test_schema_and_continuous_layout_keep_shared_geometry_and_fixed_parts():
    assert proposal_schema()["additionalProperties"] is False
    before = project()
    snapshot = deepcopy(before)
    raw = proposal()
    raw["deck_width_mm"] = 623.5
    raw["deck_depth_mm"] = 411.5
    result = apply_candidate(before, raw, {"model": "test"})
    assert before == snapshot
    assert result["revision"] == before["revision"] + 1 and result["status"] == "draft"
    assert result["engineering_design"]["proposal"]["deck_width_mm"] == 623.5
    assert result["design"]["footprint"] == {"width_mm": 623.5, "depth_mm": 411.5, "height_mm": 400}
    assert result["design"]["constraint_status"] == "fits"
    old = {p["id"]: p for p in before["design"]["components"]}
    new = {p["id"]: p for p in result["design"]["components"]}
    assert old.keys() == new.keys()
    for part_id in old.keys() - {"base", "crossbar"}:
        assert old[part_id]["size"] == new[part_id]["size"]
    assert new["sample-rack"]["position"][::2] == [-65, -50]
    assert new["crossbar"]["size"][0] == 579.5
    assert result["plan"] == before["plan"] and result["sourcing"] == before["sourcing"]
    assert add_geometry(result) == result


@pytest.mark.parametrize("change", [
    lambda p: p.update(deck_width_mm="600"),
    lambda p: p.update(deck_width_mm=True),
    lambda p: p.update(deck_depth_mm=float("nan")),
    lambda p: p.update(deck_width_mm=float("inf")),
    lambda p: p.update(deck_width_mm=399),
    lambda p: p.update(extra="not allowed"),
    lambda p: p.pop("rationale"),
    lambda p: p["placements"][1].update(component_id="source-rack"),
    lambda p: p["placements"][0].update(x_mm="-180"),
    lambda p: p["placements"].append(p["placements"][0]),
    lambda p: p.update(assumptions=["x"] * 7),
])
def test_invalid_schema_returns_failure_and_never_changes_project(change):
    draft, raw = project(), proposal()
    before = deepcopy(draft)
    change(raw)
    checks = check_candidate(draft, raw)
    assert any(c["id"].startswith("schema_") and not c["passed"] for c in checks)
    with pytest.raises(ValueError):
        apply_candidate(draft, raw, {})
    assert draft == before


def test_geometry_checks_reject_without_silent_repair():
    draft = project(workspace_width_mm=500)
    raw = proposal()
    raw["placements"][0].update(x_mm=-295, z_mm=-165)
    raw["placements"][1].update(x_mm=50, z_mm=-50)
    failures = failed(check_candidate(draft, raw))
    assert {"workspace_width", "edge_source-rack", "rear_source-rack",
            "clearance_sample-rack_tip-rack"} <= failures
    with pytest.raises(ValueError):
        apply_candidate(draft, raw, {})


def test_clearance_boundaries_are_inclusive():
    raw = proposal()
    raw["placements"][1]["x_mm"] = -80  # exactly 5 mm from source
    raw["placements"][0]["z_mm"] = -80  # rear edge exactly -115 mm
    raw["placements"][0]["x_mm"] = -242.5  # left edge exactly 10 mm in
    # Restore a separate exact gap test using the source at its original x.
    assert "edge_source-rack" not in failed(check_candidate(project(), raw))
    assert "rear_source-rack" not in failed(check_candidate(project(), raw))
    raw["placements"][0].update(x_mm=-180, z_mm=-50)
    assert "clearance_source-rack_sample-rack" not in failed(check_candidate(project(), raw))
    raw["placements"][1]["x_mm"] = -80.01
    assert "clearance_source-rack_sample-rack" in failed(check_candidate(project(), raw))


def test_workflow_and_infeasible_width_are_rejected():
    assert "workflow" in failed(check_candidate(new_project(), proposal()))
    impossible = apply_update(project(), {"workspace_width_mm": 300})
    assert "feasible_width" in failed(check_candidate(impossible, proposal()))
    assert failed(check_candidate(project(), None))


def test_cooling_is_appended_to_operating_deck_and_provenance_lifecycle():
    draft = project(cooling_enabled=True, cooling_target_c=6)
    selected = deepcopy(draft["selections"])
    accepted = apply_candidate(draft, proposal(), {"run_id": "run-1"})
    assert accepted["design"]["footprint"]["depth_mm"] > 400
    parts = {p["id"]: p for p in accepted["design"]["components"]}
    assert parts["base"]["size"][2] == accepted["design"]["footprint"]["depth_mm"]
    assert parts["cold-storage"]["position"][2] > 200
    assert accepted["summary"]["cooling_target_c"] == 6
    assert accepted["selections"] == selected
    confirmed = confirm_project(accepted)
    assert confirmed["engineering_design"] == accepted["engineering_design"]
    no_op = apply_update(confirmed, {"cooling_target_c": 6})
    assert no_op["engineering_design"] == accepted["engineering_design"]
    revised = apply_update(confirmed, {"final_volume": "200 uL"})
    assert "engineering_design" not in revised
    infeasible = apply_update(confirmed, {"workspace_width_mm": 300})
    assert "engineering_design" not in infeasible
    assert infeasible["design"]["components"] == confirmed["design"]["components"]
