"""Screen the fixed-frame parked tool and preserve the pose in portable projects."""

from copy import deepcopy

import pytest
from test_microplates import before
from test_tip_racks import OPENTRONS, selected

from app.design_spec import apply_candidate
from app.domain import confirm_project
from app.foundation_design import adopt_foundation, ensure_park_clearance
from app.project_storage import make_snapshot, restore_snapshot
from app.tip_racks import PRINTED_ID, TipRackUpdate, select_tip_rack


def parts(project):
    return {part["id"]: part for part in project["design"]["components"]}


def test_fixed_head_and_lowered_bed_have_real_world_clearance():
    original = before()
    a = adopt_foundation(original, bed_drop_mm=100)
    b = adopt_foundation(original, bed_drop_mm=150)
    assert parts(a)["pipette"]["position"] == parts(b)["pipette"]["position"]
    assert parts(a)["base"]["position"][1] - parts(b)["base"]["position"][1] == 50
    project = selected(original, OPENTRONS)
    index = parts(project)
    bottom = index["pipette"]["position"][1] - index["pipette"]["size"][1] / 2
    for cid in ("source-rack", "sample-rack", "tip-rack", "tip-waste", "controller"):
        top = index[cid]["position"][1] + index[cid]["size"][1] / 2
        assert bottom - top >= 10 - 1e-7
    assert project["design"]["foundation"]["bed_drop_mm"] == pytest.approx(127.5)
    snapshot = make_snapshot(project, [])
    restored, _ = restore_snapshot(snapshot)
    assert restored["design"] == project["design"]
    assert restored["engineering_design"] == project["engineering_design"]


def test_older_source_project_rebuilds_as_reviewable_draft():
    project = confirm_project(before())
    snapshot = make_snapshot(project, [])
    snapshot["compiler_version"] = "7"
    snapshot["foundation_bed_drop_mm"] = 100
    snapshot["engineering_design"]["proposal"]["bed_drop_mm"] = 100
    original = deepcopy(snapshot)
    restored, _ = restore_snapshot(snapshot)
    assert snapshot == original
    assert restored["status"] == "draft"
    assert restored["revision"] == snapshot["revision"] + 1
    assert restored["design"]["foundation"]["bed_drop_mm"] == pytest.approx(127.5)
    assert "Review and confirm" in restored["rebuild_notice"]
    again, _ = restore_snapshot(make_snapshot(restored, []))
    assert again["design"] == restored["design"]


def test_current_snapshot_cannot_hide_an_unsafe_bed_position():
    snapshot = make_snapshot(confirm_project(before()), [])
    snapshot["foundation_bed_drop_mm"] = 100
    snapshot["engineering_design"]["proposal"]["bed_drop_mm"] = 100
    with pytest.raises(ValueError, match="parked-tool clearance"):
        restore_snapshot(snapshot)


def test_tall_component_is_rejected_before_mutating_the_source_project():
    project = before()
    candidate = deepcopy(project)
    index = parts(candidate)
    deck_top = index["base"]["position"][1] + index["base"]["size"][1] / 2
    index["tip-rack"]["size"][1] = 120
    index["tip-rack"]["position"][1] = deck_top + 60
    before_call = deepcopy(project)
    with pytest.raises(ValueError, match="150 mm bed-drop limit"):
        ensure_park_clearance(candidate)
    assert project == before_call


def test_layout_cannot_claim_excessive_component_height_fits_at_limit():
    project = before()
    index = parts(project)
    index["tip-rack"]["size"][1] = 120
    with pytest.raises(ValueError, match="parked tool"):
        apply_candidate(project, project["engineering_design"]["proposal"], {})


def test_taller_holder_updates_bed_and_inspection_then_roundtrips():
    original = before(arm=True)
    original["fabrication_capabilities"] = {"printer_available": "yes", "source": "test"}
    original["tip_rack_request"] = {"profile_id": PRINTED_ID, "spec": {
        "body_diameter_max_mm": 6, "rim_diameter_min_mm": 9,
        "rim_diameter_max_mm": 10, "below_rim_height_mm": 90,
        "count": 12, "columns": 4,
    }}
    updated, run = select_tip_rack(
        original, TipRackUpdate(), "Use printed holder", accept_placement=True
    )
    assert updated["design"]["foundation"]["bed_drop_mm"] == pytest.approx(140.5)
    assert "Lowered the bed 13.00 mm" in run["message"]
    old_y = original["inspection_extension"]["pose_frames"][0]["camera_mm"][1]
    new_y = updated["inspection_extension"]["pose_frames"][0]["camera_mm"][1]
    assert old_y - new_y == pytest.approx(13)
    restored, _ = restore_snapshot(make_snapshot(updated, []))
    assert restored["design"] == updated["design"]
    assert restored["inspection_extension"] == updated["inspection_extension"]


@pytest.mark.parametrize("instruction", ["Keep the bed position.", "Do not move the bed."])
def test_tall_holder_does_not_move_explicitly_preserved_bed(instruction):
    project = before()
    project["fabrication_capabilities"] = {"printer_available": "yes", "source": "test"}
    project["tip_rack_request"] = {"profile_id": PRINTED_ID, "spec": {
        "body_diameter_max_mm": 6, "rim_diameter_min_mm": 9,
        "rim_diameter_max_mm": 10, "below_rim_height_mm": 90,
        "count": 12, "columns": 4,
    }}
    original = deepcopy(project)
    with pytest.raises(ValueError, match="bed position"):
        select_tip_rack(project, TipRackUpdate(), instruction, accept_placement=True)
    assert project == original


def test_placement_confirmation_preserves_bed_lock_across_save_and_open():
    project = before()
    project["fabrication_capabilities"] = {"printer_available": "yes", "source": "test"}
    project["tip_rack_request"] = {"profile_id": PRINTED_ID, "spec": {
        "body_diameter_max_mm": 6, "rim_diameter_min_mm": 9,
        "rim_diameter_max_mm": 10, "below_rim_height_mm": 90,
        "count": 12, "columns": 12,
    }}
    pending, run = select_tip_rack(project, TipRackUpdate(), "Keep the bed position.")
    assert run["status"] == "ready" and "Confirm" in run["message"]
    assert pending["tip_rack_request"]["bed_position_locked"] is True
    reopened, _ = restore_snapshot(make_snapshot(pending, []))
    assert reopened["tip_rack_request"]["bed_position_locked"] is True
    before_reply = deepcopy(reopened)
    with pytest.raises(ValueError, match="bed position"):
        select_tip_rack(reopened, TipRackUpdate(), "yes")
    assert reopened == before_reply
