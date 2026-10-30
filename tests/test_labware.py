"""Grounded rack inputs, deterministic application and portable reconstruction."""

from copy import deepcopy

import pytest
from evolution_fixtures import inspection_proposal, layout_project
from test_commercial_design import proposal as ot2_proposal
from test_foundation_storage import source_project

from app.commercial_design import adopt_commercial, compile_commercial_layout
from app.domain import apply_update, confirm_project
from app.inspection import apply_extension
from app.labware import (
    LabwareUpdate,
    develop_labware,
    reapply_labware,
    remove_labware,
    update_labware_brief,
)
from app.project_storage import make_snapshot, restore_snapshot

FULL_MESSAGE = (
    "Develop a rim-supported rack with body diameter maximum 10.8 mm, "
    "rim diameter minimum 13.5 mm, closed cap diameter maximum 14 mm, "
    "below-rim height 30 mm, 6 positions in 3 columns."
)
FULL_UPDATE = {
    "body_diameter_max_mm": 10.8,
    "source_body_diameter_max_mm": "body diameter maximum 10.8 mm",
    "rim_diameter_min_mm": 13.5,
    "source_rim_diameter_min_mm": "rim diameter minimum 13.5 mm",
    "cap_diameter_max_mm": 14,
    "source_cap_diameter_max_mm": "closed cap diameter maximum 14 mm",
    "below_rim_height_mm": 30,
    "source_below_rim_height_mm": "below-rim height 30 mm",
    "count": 6,
    "source_count": "6 positions",
    "columns": 3,
    "source_columns": "3 columns",
}


def rack_project(project=None, *, count=6, columns=3):
    project = source_project() if project is None else project
    values = deepcopy(FULL_UPDATE)
    values.update(
        count=count,
        source_count=f"{count} positions",
        columns=columns,
        source_columns=f"{columns} columns",
    )
    message = FULL_MESSAGE.replace("6 positions", f"{count} positions").replace(
        "3 columns", f"{columns} columns"
    )
    brief = update_labware_brief(project, LabwareUpdate.model_validate(values), message)
    result, run = develop_labware(brief)
    assert run["status"] == "accepted"
    return result


def test_nominal_tube_capacity_does_not_invent_dimensions_or_mutate_geometry():
    project = source_project()
    before = deepcopy(project)
    result, run = develop_labware(project)
    assert "Nominal 1.5–2 mL" in run["message"]
    assert result["design"] == before["design"]
    assert result["engineering_design"] == before["engineering_design"]
    assert result["labware_brief"]["spec"] == {}
    assert len(result["labware_brief"]["missing_fields"]) == 6
    assert "labware_rack" not in result and project == before
    with pytest.raises(ValueError):
        update_labware_brief(
            project,
            LabwareUpdate(
                body_diameter_max_mm=10.8,
                source_body_diameter_max_mm="1.5 mL microcentrifuge tubes",
            ),
            "Use 1.5 mL microcentrifuge tubes",
        )


def test_partial_dimensions_remain_grounded_and_accumulate_without_geometry():
    project = source_project()
    first = update_labware_brief(
        project,
        LabwareUpdate(
            body_diameter_max_mm=10.8, source_body_diameter_max_mm="diametro corpo massimo 1,08 cm"
        ),
        "Il diametro corpo massimo 1,08 cm",
    )
    second = update_labware_brief(
        first,
        LabwareUpdate(count=12, source_count="12 provette", columns=4, source_columns="4 colonne"),
        "Usa 12 provette in 4 colonne",
    )
    result, run = develop_labware(second)
    assert run["status"] == "ready" and result["design"] == project["design"]
    assert result["labware_brief"]["spec"] == {
        "body_diameter_max_mm": 10.8,
        "count": 12,
        "columns": 4,
    }
    assert (
        result["labware_brief"]["sources"]["body_diameter_max_mm"]["literal"]
        == "diametro corpo massimo 1,08 cm"
    )
    assert result["labware_brief"]["missing_fields"] == [
        "rim_diameter_min_mm",
        "cap_diameter_max_mm",
        "below_rim_height_mm",
    ]


@pytest.mark.parametrize(
    "values,message",
    [
        ({"count": 6, "source_count": "6 mL tubes"}, "Use 6 mL tubes"),
        ({"columns": 3, "source_columns": "3 mL"}, "Use 3 mL"),
        ({"body_diameter_max_mm": 10.8, "source_body_diameter_max_mm": "body 11 mm"}, "body 11 mm"),
        ({"cap_diameter_max_mm": 14, "source_cap_diameter_max_mm": "rim 14 mm"}, "rim 14 mm"),
        (
            {"body_diameter_max_mm": 10.8, "source_body_diameter_max_mm": "body 10.8 mm"},
            "Use previous values",
        ),
    ],
)
def test_unsupported_ungrounded_or_liquid_counts_are_rejected(values, message):
    with pytest.raises(ValueError):
        update_labware_brief(source_project(), LabwareUpdate.model_validate(values), message)


def test_applied_rack_changes_only_sample_component_and_keeps_inspection():
    project = apply_extension(source_project(), inspection_proposal(), {})
    before = deepcopy(project)
    result = rack_project(project)
    old_parts = {part["id"]: part for part in project["design"]["components"]}
    parts = {part["id"]: part for part in result["design"]["components"]}
    assert parts.keys() == old_parts.keys()
    for cid in parts.keys() - {"sample-rack"}:
        assert parts[cid] == old_parts[cid]
    rack = parts["sample-rack"]
    assert rack["size"] != old_parts["sample-rack"]["size"]
    assert rack["position"][0::2] == old_parts["sample-rack"]["position"][0::2]
    assert len(rack["geometry"]["primitives"][0]["holes"]) == 6
    assert result["inspection_extension"]["proposal"] == project["inspection_extension"]["proposal"]
    assert (
        result["inspection_extension"]["provenance"]
        == project["inspection_extension"]["provenance"]
    )
    assert {
        key
        for key in project["inspection_extension"]
        if project["inspection_extension"][key] != result["inspection_extension"][key]
    } == {"pose_frames"}
    old_frames = project["inspection_extension"]["pose_frames"]
    new_frames = result["inspection_extension"]["pose_frames"]
    assert old_frames != new_frames  # Only the measured rack's target plane changes.
    for old_frame, new_frame in zip(old_frames, new_frames):
        assert old_frame["target_mm"][0::2] == new_frame["target_mm"][0::2]
        assert new_frame["target_mm"][1] == rack["position"][1] + rack["size"][1] / 2
        assert {key: value for key, value in old_frame.items() if key != "target_mm"} == {
            key: value for key, value in new_frame.items() if key != "target_mm"
        }
    assert result["engineering_design"] == project["engineering_design"]
    assert (
        result["labware_rack"]["provenance"]["previous_size_mm"] == old_parts["sample-rack"]["size"]
    )
    assert all(check["passed"] for check in result["labware_rack"]["checks"])
    groups = result["sourcing"]["groups"]
    assert "sample-rack" not in next(g for g in groups if g["id"] == "fixtures")["component_ids"]
    assert next(g for g in groups if g["id"] == "labware-rack")["options"][0]["unit_price"] is None
    assert project == before


def test_valid_dimension_refinement_rebuilds_real_holes_and_removal_restores_original():
    initial = rack_project()
    revised = update_labware_brief(
        initial,
        LabwareUpdate(count=12, source_count="12 positions", columns=4, source_columns="4 columns"),
        "Change to 12 positions in 4 columns",
    )
    result, run = develop_labware(revised)
    assert run["status"] == "accepted"
    rack = next(p for p in result["design"]["components"] if p["id"] == "sample-rack")
    assert rack["rack_slot_count"] == 12 and len(rack["geometry"]["primitives"][0]["holes"]) == 12
    assert result["labware_rack"]["size_mm"] != initial["labware_rack"]["size_mm"]
    restored = remove_labware(result)
    original = next(p for p in source_project()["design"]["components"] if p["id"] == "sample-rack")
    assert next(p for p in restored["design"]["components"] if p["id"] == "sample-rack") == original
    assert "labware_rack" not in restored and "labware_brief" in restored


def test_impossible_rim_layout_or_target_capacity_preserves_original_input():
    project = rack_project()
    original = deepcopy(project)
    for values, message in [
        (
            {"rim_diameter_min_mm": 11, "source_rim_diameter_min_mm": "rim diameter minimum 11 mm"},
            "rim diameter minimum 11 mm",
        ),
        (
            {
                "count": 24,
                "source_count": "24 positions",
                "columns": 8,
                "source_columns": "8 columns",
            },
            "24 positions in 8 columns",
        ),
    ]:
        changed = update_labware_brief(project, LabwareUpdate.model_validate(values), message)
        with pytest.raises(ValueError):
            develop_labware(changed)
        assert project == original
    small = rack_project(count=2, columns=2)
    with pytest.raises(ValueError, match="positions"):
        apply_update(small, {"target_concentrations": "1 mg/mL, 2 mg/mL, 3 mg/mL"})


def test_quantity_only_update_preserves_module_capacity_geometry_and_inspection():
    project = rack_project(
        apply_extension(source_project(), inspection_proposal(), {}), count=12, columns=4
    )
    revised = apply_update(project, {"final_volume": "500 uL"})
    assert revised["design"] == project["design"]
    assert revised["inspection_extension"] == project["inspection_extension"]
    assert revised["labware_rack"] == project["labware_rack"]
    assert (
        next(p for p in revised["design"]["components"] if p["id"] == "sample-rack")[
            "rack_slot_count"
        ]
        == 12
    )


def test_ot2_fixture_rejected_even_with_missing_dimensions():
    project = compile_commercial_layout(adopt_commercial(layout_project()), ot2_proposal(), {})
    before = deepcopy(project)
    with pytest.raises(ValueError, match="Jubilee"):
        develop_labware(project)
    assert project == before


def test_compiler5_roundtrip_keeps_rack_geometry_sources_and_twelve_slots():
    project = confirm_project(
        rack_project(
            apply_extension(source_project(), inspection_proposal(), {}), count=12, columns=4
        )
    )
    snapshot = make_snapshot(project, [])
    assert snapshot["compiler_version"] == "5"
    assert "geometry" not in snapshot["labware_rack"] and "derived" not in snapshot["labware_rack"]
    restored, _ = restore_snapshot(snapshot)
    assert restored["design"] == project["design"]
    assert restored["labware_rack"] == project["labware_rack"]
    assert restored["labware_brief"] == project["labware_brief"]
    assert restored["inspection_extension"] == project["inspection_extension"]
    assert restored["sourcing"] == project["sourcing"]


def test_partial_compiler5_and_older_compiler4_do_not_generate_rack_on_open():
    original = source_project()
    partial = update_labware_brief(
        original, LabwareUpdate(count=6, source_count="6 tubes"), "Use 6 tubes"
    )
    snapshot = make_snapshot(partial, [])
    assert snapshot["compiler_version"] == "5"
    restored, _ = restore_snapshot(snapshot)
    assert restored["labware_brief"] == partial["labware_brief"]
    assert "labware_rack" not in restored and restored["design"] == original["design"]
    old = make_snapshot(original, [])
    assert old["compiler_version"] == "4"
    restored, _ = restore_snapshot(old)
    assert "labware_brief" not in restored and "labware_rack" not in restored
    assert restored["design"] == original["design"]


def test_reopen_rejects_invented_geometry_sources_and_mismatched_original_component():
    snapshot = make_snapshot(rack_project(), [])
    for change in ("geometry", "fact", "value", "original", "version", "target"):
        invalid = deepcopy(snapshot)
        if change == "geometry":
            invalid["labware_rack"]["geometry"] = {"primitives": []}
        elif change == "fact":
            invalid["labware_rack"]["provenance"]["sources"]["count"]["literal"] = "6 mL tubes"
        elif change == "value":
            invalid["labware_rack"]["spec"]["count"] = 8
        elif change == "original":
            invalid["labware_rack"]["original_component"]["size"][0] = 50
        elif change == "version":
            invalid["compiler_version"] = "4"
        elif change == "target":
            invalid["labware_rack"]["target_component_id"] = "source-rack"
        with pytest.raises(ValueError):
            restore_snapshot(invalid)


def test_reapply_is_idempotent_and_never_uses_user_urls_or_code():
    project = rack_project()
    assert reapply_labware(project) == project
    with pytest.raises(ValueError):
        LabwareUpdate.model_validate({"body_diameter_max_mm": 10, "url": "https://example.com"})


def test_dimension_role_and_one_value_cannot_be_borrowed_from_another_measurement():
    for update, message in [
        (
            LabwareUpdate(
                body_diameter_max_mm=13,
                source_body_diameter_max_mm="body diameter 10 mm, rim diameter 13 mm",
            ),
            "body diameter 10 mm, rim diameter 13 mm",
        ),
        (
            LabwareUpdate(rim_diameter_min_mm=40, source_rim_diameter_min_mm="rim to tip 40 mm"),
            "rim to tip 40 mm",
        ),
        (
            LabwareUpdate(count=3, source_count="6 positions in 3 columns"),
            "6 positions in 3 columns",
        ),
    ]:
        with pytest.raises(ValueError):
            update.verify_sources(message)


@pytest.mark.parametrize(
    "source",
    [
        "underside of the rim to the tip 30 mm",
        "distance from rim underside to tip 30 mm",
        "dall'intradosso del bordo alla punta 30 mm",
    ],
)
def test_user_facing_under_rim_measurement_definitions_are_groundable(source):
    LabwareUpdate(below_rim_height_mm=30, source_below_rim_height_mm=source).verify_sources(source)
