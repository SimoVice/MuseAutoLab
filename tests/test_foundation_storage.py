"""Portable foundation identity, migration, and geometry reconstruction."""

from copy import deepcopy

import pytest
from evolution_fixtures import inspection_proposal, layout_project

from app.design_spec import apply_candidate
from app.domain import confirm_project
from app.foundation_design import adopt_foundation
from app.geometry import add_geometry
from app.inspection import apply_extension
from app.project_storage import make_snapshot, restore_snapshot
from app.upstream_cad import ASSET_ID


def source_project(drop=100):
    project = adopt_foundation(layout_project())
    coordinates = [(-80, -85), (80, -85), (-80, 0), (0, 100), (80, 5)]
    ids = ("source-rack", "sample-rack", "tip-rack", "tip-waste", "controller")
    proposal = {
        "schema_version": "1", "deck_width_mm": 300, "deck_depth_mm": 300,
        "bed_drop_mm": drop,
        "placements": [{"component_id": name, "x_mm": x, "z_mm": z}
                       for name, (x, z) in zip(ids, coordinates)],
        "rationale": "Synthetic source layout.", "assumptions": [],
    }
    return apply_candidate(project, proposal, {"model": "offline"})


def test_source_layout_and_inspection_roundtrip_without_serialized_geometry():
    project = confirm_project(apply_extension(source_project(), inspection_proposal(), {}))
    history = [{"role": "user", "content": "Keep the source machine."}]
    snapshot = make_snapshot(project, history)
    assert snapshot["compiler_version"] == "4" and snapshot["foundation_id"] == ASSET_ID
    assert "design" not in snapshot
    restored, conversation = restore_snapshot(snapshot)
    assert restored["engineering_design"] == project["engineering_design"]
    assert restored["design"] == project["design"]
    assert restored["inspection_extension"] == project["inspection_extension"]
    assert restored["sourcing"] == project["sourcing"]
    assert restored["design"]["foundation"]["bed_drop_mm"] == 100
    assert restored["status"] == "confirmed" and conversation == history


@pytest.mark.parametrize("compiler", ["1", "2"])
def test_older_designs_preserve_inputs_and_history_but_require_new_design(compiler):
    project = confirm_project(apply_extension(layout_project(), inspection_proposal(), {}))
    history = [{"role": "user", "content": "Keep these requirements."}]
    snapshot = make_snapshot(project, history)
    snapshot["compiler_version"] = compiler
    restored, conversation = restore_snapshot(snapshot)
    assert restored["summary"] == project["summary"]
    assert restored["brief"] == project["brief"]
    assert conversation == history and restored["status"] == "draft"
    assert restored["revision"] == project["revision"] + 1
    assert not restored.get("engineering_design") and not restored.get("inspection_extension")
    assert "chat" in restored["rebuild_notice"]


def test_new_legacy_project_still_roundtrips():
    project = confirm_project(layout_project())
    restored, _ = restore_snapshot(make_snapshot(project, []))
    assert restored["design"] == project["design"]
    assert restored["status"] == "confirmed"


def test_source_draft_rebuilds_canonical_geometry_without_a_layout():
    project = add_geometry(adopt_foundation(layout_project(), bed_drop_mm=75))
    restored, _ = restore_snapshot(make_snapshot(project, []))
    assert restored["design"] == project["design"]
    assert restored["design"]["foundation"]["bed_drop_mm"] == 75
    assert not restored.get("engineering_design")


@pytest.mark.parametrize("mutation", [
    lambda s: s.update(foundation_id="untrusted"),
    lambda s: s.update(foundation_id=None),
    lambda s: s.update(foundation_bed_drop_mm=120),
    lambda s: s.update(foundation_url="https://example.invalid/asset.step"),
    lambda s: s["engineering_design"]["proposal"].update(bed_drop_mm=151),
])
def test_snapshot_rejects_untrusted_or_incompatible_source(mutation):
    snapshot = make_snapshot(source_project(), [])
    mutation(snapshot)
    before = deepcopy(snapshot)
    with pytest.raises(ValueError):
        restore_snapshot(snapshot)
    assert snapshot == before
