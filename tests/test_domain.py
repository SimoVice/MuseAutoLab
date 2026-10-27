"""Behavioral checks for the concept design's version and layout constraints."""

from copy import deepcopy

import pytest

from app.domain import apply_update, confirm_project, new_project

COMPLETE = {
    "stock_concentration": "10 mM",
    "target_concentrations": "1 mM, 2 mM",
    "final_volume": "1 mL",
    "equipment": "adjustable micropipette and microcentrifuge tubes",
}


def test_update_confirm_and_edit_keep_original_versions_unchanged():
    original = new_project()
    snapshot = deepcopy(original)
    draft = apply_update(original, COMPLETE)
    assert original == snapshot
    assert draft["revision"] == 1 and draft["status"] == "draft"
    confirmed = confirm_project(draft)
    assert draft["status"] == "draft"
    assert confirmed["status"] == "confirmed" and confirmed["revision"] == 2
    assert confirm_project(confirmed) == confirmed
    assert apply_update(confirmed, {"equipment": COMPLETE["equipment"]}) == confirmed
    revised = apply_update(confirmed, {"final_volume": "2 mL"})
    assert revised["status"] == "draft" and revised["revision"] == 3
    assert confirmed["summary"]["final_volume"] == "1 mL"


def test_compact_layout_repositions_fixed_parts_and_fits_requested_width():
    wide = new_project()
    compact = apply_update(wide, {"workspace_width_mm": 450})
    assert wide["design"]["footprint"]["width_mm"] == 600
    assert compact["design"]["footprint"]["width_mm"] == 400
    assert compact["design"]["constraint_status"] == "fits"
    before = {part["id"]: part for part in wide["design"]["components"]}
    after = {part["id"]: part for part in compact["design"]["components"]}
    assert before.keys() == after.keys()
    for part_id in before.keys() - {"base", "crossbar"}:
        assert before[part_id]["size"] == after[part_id]["size"]
    assert before["sample-rack"]["position"] != after["sample-rack"]["position"]
    assert compact["design"]["estimated_cost"]["amount"] == pytest.approx(208.28)
    assert compact["sourcing"]["incomplete"] is True


def test_infeasible_width_preserves_geometry_and_can_be_revised():
    draft = apply_update(new_project(), COMPLETE)
    compact = apply_update(draft, {"workspace_width_mm": 400})
    rejected = apply_update(compact, {"workspace_width_mm": 350})
    assert rejected["summary"]["workspace_width_mm"] == 350
    assert rejected["design"]["constraint_status"] == "infeasible"
    assert rejected["design"]["components"] == compact["design"]["components"]
    assert rejected["design"]["footprint"] == compact["design"]["footprint"]
    with pytest.raises(ValueError, match="infeasible"):
        confirm_project(rejected)
    recovered = apply_update(rejected, {"workspace_width_mm": 650})
    assert recovered["design"]["constraint_status"] == "fits"
    assert recovered["design"]["footprint"]["width_mm"] == 600
    assert confirm_project(recovered)["status"] == "confirmed"


@pytest.mark.parametrize("width", [0, -1, True, float("nan"), float("inf"), 5001, "400"])
def test_invalid_width_is_rejected_without_mutation(width):
    project = new_project()
    before = deepcopy(project)
    with pytest.raises(ValueError):
        apply_update(project, {"workspace_width_mm": width})
    assert project == before


def test_unknown_field_and_incomplete_confirmation_are_rejected():
    project = new_project()
    with pytest.raises(ValueError, match="Unsupported project fields"):
        apply_update(project, {"discount": 100})
    with pytest.raises(ValueError, match="Required parameters are missing"):
        confirm_project(project)
