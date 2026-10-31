"""Source-bound plate switching and reversible state; no hardware or live model calls."""

from copy import deepcopy

import pytest
from evolution_fixtures import inspection_proposal, layout_project
from test_commercial_design import proposal as ot2_proposal
from test_foundation_storage import source_project
from test_labware import rack_project

from app.commercial_design import adopt_commercial, compile_commercial_layout
from app.domain import apply_update, confirm_project
from app.inspection import apply_extension
from app.microplate_geometry import SOURCE_SHA256
from app.microplates import (
    PROFILE_ID,
    LabwareSelection,
    reapply_plate,
    restore_previous_sample,
    select_plate,
)
from app.project_exports import ExportError, _ensure_supported
from app.project_storage import make_snapshot, restore_snapshot

MESSAGE = "Sostituisci le provette con una piastra da 96 pozzetti"


def select(project, message=MESSAGE):
    return select_plate(project, LabwareSelection(profile_id=PROFILE_ID, source=message), message)[
        0
    ]


def before(*, arm=False, volume="200 uL"):
    project = rack_project(count=12, columns=4)
    if arm:
        project = apply_extension(project, inspection_proposal(), {})
    return apply_update(project, {"final_volume": volume})


def test_switch_uses_pinned_profile_and_only_moves_sample_and_derived_arm_poses():
    original = before(arm=True)
    baseline = deepcopy(original)
    result = select(original)
    module = result["labware_plate"]
    assert module["profile_id"] == PROFILE_ID and "labware_rack" not in result
    assert module["profile_binding"]["source_sha256"] == SOURCE_SHA256
    assert module["profile"]["source"]["license"] == "Apache-2.0"
    assert module["compatibility"]["occupied_wells"] == ["A1", "B1"]
    assert module["compatibility"]["current_target_count"] == 2
    assert module["derived"]["well_count"] == 96
    assert result["summary"] == original["summary"]
    assert result["engineering_design"] == original["engineering_design"]
    parts = {p["id"]: p for p in result["design"]["components"]}
    for old in original["design"]["components"]:
        if old["id"] != "sample-rack" and not old["id"].startswith("inspection-"):
            assert parts[old["id"]] == old
    assert all(check["passed"] for check in module["checks"])
    assert module["size_mm"] == pytest.approx([135.36, 16.72, 93.08])
    assert module["position_xz_mm"] != baseline["labware_rack"].get("position_xz_mm")
    extension = result["inspection_extension"]
    old_extension = original["inspection_extension"]
    assert extension["proposal"] == old_extension["proposal"]
    assert extension["provenance"] == old_extension["provenance"]
    for cid in ("inspection-mount", "inspection-mast"):
        assert next(p for p in extension["components"] if p["id"] == cid) == next(
            p for p in old_extension["components"] if p["id"] == cid
        )
    for part in extension["components"]:
        assert parts[part["id"]] == part
    assert original == baseline


def test_two_ml_switch_is_applied_as_draft_and_confirmation_export_are_blocked():
    original = before(volume="2 mL")
    result = select(original)
    assert "labware_plate" in result and result["status"] == "draft"
    assert result["plan"]["status"] == "invalid"
    assert result["labware_plate"]["compatibility"]["status"] == "volume_conflict"
    assert result["summary"]["final_volume"] == "2 mL"
    assert result["plan"]["final_volume_ul"] == 2000
    assert "reference maximum" in result["plan"]["message"]
    for old, new in zip(original["plan"]["steps"], result["plan"]["steps"]):
        assert all(new[key] == value for key, value in old.items())
    with pytest.raises(ValueError, match="2000"):
        confirm_project(result)
    with pytest.raises(ExportError):
        _ensure_supported({**result, "status": "confirmed"})
    fixed = apply_update(result, {"final_volume": "200 uL"})
    assert fixed["plan"]["status"] == "ready"
    assert fixed["labware_plate"]["compatibility"]["status"] == "ready"
    assert fixed["design"] == result["design"]
    assert confirm_project(fixed)["status"] == "confirmed"
    assert fixed["labware_plate"]["compatibility"]["pipette_range_status"] == "unverified"


@pytest.mark.parametrize("arm", [False, True])
def test_exact_switchback_restores_rack_spec_pose_components_and_current_recipe(arm):
    original = before(arm=arm)
    plate = select(original)
    plate = apply_update(plate, {"final_volume": "250 uL"})
    result = restore_previous_sample(plate)
    assert result["design"] == original["design"]
    assert result["labware_rack"] == original["labware_rack"]
    assert result["labware_brief"] == original["labware_brief"]
    assert result["summary"]["final_volume"] == "250 uL"
    assert result["plan"]["status"] == "ready" and result["plan"]["final_volume_ul"] == 250
    assert "labware_plate" not in result
    if arm:
        assert result["inspection_extension"] == original["inspection_extension"]
        parts = {p["id"]: p for p in result["design"]["components"]}
        assert all(parts[p["id"]] == p for p in result["inspection_extension"]["components"])


def test_generic_previous_rack_switchback_restores_exact_geometry_and_bounds():
    original = apply_extension(source_project(), inspection_proposal(), {})
    result = restore_previous_sample(select(original))
    assert result["design"] == original["design"]
    assert result["inspection_extension"] == original["inspection_extension"]
    assert "labware_rack" not in result and "labware_plate" not in result


@pytest.mark.parametrize(
    "message",
    [
        "Passa a una piastra da 96 pozzetti",
        "Switch from Eppendorf 1.5 mL tubes to a 96-well microplate",
        "da eppendorf 1.5ml a 96 microwells plates",
        "Use a 96 microwell plate",
        "96 microwells plates",
        "96 microwell plate",
        "96-microwell plate",
        "96-well microplate",
        "Passa da eppendorf 1.5ml a 96 microwells plates.",
        "Switch to a 96-well plate but do not change the volume",
        "Select a 96-well reference plate",
    ],
)
def test_generic_selection_accepts_natural_96_well_aliases(message):
    selection = LabwareSelection(profile_id=PROFILE_ID, source=message)
    selection.verify_sources(message)


@pytest.mark.parametrize(
    "message,source",
    [
        ("Use a 384-well plate", "384-well plate"),
        ("Use a Bio-Rad 96-well PCR plate", "96-well"),
        ("Use a Zeta 96-well plate", "96-well"),
        ("Use a zeta 96-well plate", "96-well"),
        ("Use a 96-well deep-well plate", "96-well"),
        ("Use a 96-well plate SKU ABC-123", "96-well"),
        ("Do not switch to a 96-well plate", "Do not switch to a 96-well plate"),
        ("Maybe switch to a 96-well plate later", "switch to a 96-well plate later"),
        ("Do not switch to a 96-well plate", "96-well plate"),
        ("We may switch to a 96-well plate in future", "96-well plate"),
    ],
)
def test_unknown_profile_family_vendor_and_negated_selection_do_not_substitute(message, source):
    with pytest.raises(ValueError):
        LabwareSelection(profile_id=PROFILE_ID, source=source).verify_sources(message)


def test_no_feasible_sample_only_placement_keeps_all_inputs_unchanged():
    original = before()
    # A synthetic obstruction test, not a real accepted geometric design.
    for part in original["design"]["components"]:
        if part["id"] == "controller":
            part["size"] = [295, 50, 295]
            part["position"][0] = original["design"]["foundation"]["deck_origin_app_mm"][0]
            part["position"][2] = original["design"]["foundation"]["deck_origin_app_mm"][2]
    baseline = deepcopy(original)
    with pytest.raises(ValueError, match="No sample-only placement"):
        select(original)
    assert original == baseline


def test_ot2_custom_plate_switch_is_rejected_atomically():
    project = compile_commercial_layout(adopt_commercial(layout_project()), ot2_proposal(), {})
    baseline = deepcopy(project)
    with pytest.raises(ValueError, match="Jubilee"):
        select(project)
    assert project == baseline


def test_compiler6_roundtrip_rebuilds_profile_and_restores_exact_archived_tube_rack():
    original = before(arm=True)
    selected = select(original)
    snapshot = make_snapshot(selected, [])
    assert snapshot["compiler_version"] == "6"
    assert "geometry" not in snapshot["labware_plate"]
    assert snapshot["labware_rack"] is None
    restored, _ = restore_snapshot(snapshot)
    assert restored["design"] == selected["design"]
    assert restored["labware_plate"] == selected["labware_plate"]
    assert restore_previous_sample(restored)["design"] == original["design"]
    assert make_snapshot(original, [])["compiler_version"] == "5"


def test_compiler6_conflicted_draft_can_reopen_but_cannot_be_forged_confirmed():
    project = select(before(volume="2 mL"))
    snapshot = make_snapshot(project, [])
    restored, _ = restore_snapshot(snapshot)
    assert restored["plan"]["status"] == "invalid"
    invalid = deepcopy(snapshot)
    invalid["status"] = "confirmed"
    with pytest.raises(ValueError):
        restore_snapshot(invalid)


@pytest.mark.parametrize(
    "tamper", ["profile", "hash", "revision", "geometry", "archive", "both", "version"]
)
def test_import_rejects_unreviewed_profiles_geometry_and_archived_rack_tampering(tamper):
    snapshot = make_snapshot(select(before()), [])
    if tamper == "profile":
        snapshot["labware_plate"]["profile_id"] = "generic-384-well"
    elif tamper == "hash":
        snapshot["labware_plate"]["profile_binding"]["source_sha256"] = "0" * 64
    elif tamper == "revision":
        snapshot["labware_plate"]["profile_binding"]["source_revision"] = "0" * 40
    elif tamper == "geometry":
        snapshot["labware_plate"]["geometry"] = {"primitives": []}
    elif tamper == "archive":
        snapshot["labware_plate"]["previous_sample"]["rack_inputs"]["spec"][
            "body_diameter_max_mm"
        ] = 30
    elif tamper == "both":
        snapshot["labware_rack"] = snapshot["labware_plate"]["previous_sample"]["rack_inputs"]
    else:
        snapshot["compiler_version"] = "5"
    with pytest.raises(ValueError):
        restore_snapshot(snapshot)


def test_reapply_same_profile_is_idempotent_and_does_not_add_preparations():
    selected = select(before())
    assert reapply_plate(selected) == selected
    assert len(selected["plan"]["steps"]) == 2
    assert selected["plan"]["steps"][0]["well_name"] == "A1"
    assert selected["plan"]["steps"][1]["well_name"] == "B1"
