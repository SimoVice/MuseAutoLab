"""Independent additive housing geometry, supports, motion reservations and guards."""

from copy import deepcopy

import pytest
from test_custom_project_routes import proposal

from app.concept_design import assembly_review_issues, compile_concept
from app.concept_enclosure import (
    EnclosureRequest,
    add_parametric_enclosure,
    supported_enclosure_clearance,
)


def request(**updates):
    return {
        **{
            "key": "protective_shell",
            "name": "Proposed removable housing",
            "role": "Proposed access cover around the existing mechanism.",
            "assembly": "Seat the housing on the stationary base and review access.",
            "check": "Review physical clearance, attachment and materials before use.",
            "target_keys": ["sample_tray"],
            "clearance_mm": 5,
            "wall_mm": 3,
            "finish": "dark",
            "color": "#121820",
            "open_face": None,
            "open_bottom": True,
        },
        **updates,
    }


def test_closed_housing_reserves_travel_and_preserves_every_existing_component_and_protocol():
    previous = compile_concept(proposal(), 600)
    untouched = deepcopy(previous)
    compiled = add_parametric_enclosure(previous, request())
    assert previous == untouched
    assert compiled["proposal"]["components"][:-1] == previous["proposal"]["components"]
    assert compiled["components"][:-1] == previous["components"]
    for field in ("steps", "software", "supplies", "work_interfaces", "open_questions"):
        assert compiled["proposal"][field] == previous["proposal"][field]
    shell = compiled["components"][-1]
    assert shell["parent_key"] == "rail_base"
    assert shell["placement_mm"] == [0, 10, 0]
    assert shell["source_id"] is None
    assert len(shell["primitives"]) == 5
    assert not assembly_review_issues(compiled, per_component=False)
    tray = next(part for part in previous["components"] if part["key"] == "sample_tray")
    roof = shell["primitives"][-1]
    top_y = shell["position_mm"][1] + roof["center_mm"][1] - roof["size_mm"][1] / 2
    assert top_y == tray["swept_bounds_mm"]["max"][1] + 5
    assert roof["size_mm"][0] == (
        tray["swept_bounds_mm"]["max"][0] - tray["swept_bounds_mm"]["min"][0] + 16
    )


@pytest.mark.parametrize("face", ["front", "back", "left", "right"])
def test_explicit_open_face_removes_one_wall_but_retains_supported_roof(face):
    compiled = add_parametric_enclosure(compile_concept(proposal()), request(open_face=face))
    assert len(compiled["components"][-1]["primitives"]) == 4
    assert not assembly_review_issues(compiled, per_component=False)


def test_housing_includes_descendants_of_target():
    raw = proposal()
    raw["components"].append(
        {
            "key": "sample_lid",
            "name": "Sample lid",
            "role": "Representative lid geometry.",
            "parent_key": "sample_tray",
            "placement_mm": [0, 8, 0],
            "source_id": None,
            "assembly": "Rest the lid on the tray.",
            "check": "Review fit.",
            "primitives": [
                {
                    "shape": "box",
                    "size_mm": [10, 4, 10],
                    "center_mm": [0, 2, 0],
                    "finish": "polymer",
                }
            ],
        }
    )
    previous = compile_concept(raw)
    compiled = add_parametric_enclosure(previous, request())
    shell, lid = compiled["components"][-1], previous["components"][-1]
    roof = shell["primitives"][-1]
    assert (
        shell["position_mm"][1] + roof["center_mm"][1] - roof["size_mm"][1] / 2
        == lid["swept_bounds_mm"]["max"][1] + 5
    )


def test_wall_expands_around_encountered_fixed_support_without_changing_it():
    raw = proposal()
    raw["components"].append(
        {
            "key": "rear_post",
            "name": "Rear support post",
            "role": "Proposed support.",
            "parent_key": "rail_base",
            "placement_mm": [-28, 10, -30],
            "source_id": None,
            "assembly": "Stand the post on the base.",
            "check": "Review its mount.",
            "primitives": [
                {"shape": "box", "size_mm": [8, 20, 6], "center_mm": [0, 10, 0], "finish": "frame"}
            ],
        }
    )
    previous = compile_concept(raw)
    compiled = add_parametric_enclosure(previous, request())
    assert compiled["components"][:-1] == previous["components"]
    roof = compiled["components"][-1]["primitives"][-1]
    assert roof["size_mm"][0] == 113
    assert roof["size_mm"][2] == 74
    assert not assembly_review_issues(compiled, per_component=False)


def test_full_wall_coverage_uses_actual_base_faces_rather_than_its_filled_envelope():
    raw = proposal()
    raw["components"][0]["primitives"] = [
        {"shape": "box", "size_mm": [20, 10, 100], "center_mm": [x, 5, 0], "finish": "frame"}
        for x in (-80, 80)
    ]
    raw["components"][1]["placement_mm"] = [-75, 10, 0]
    raw["components"][1]["primitives"][0]["size_mm"] = [4, 8, 10]
    raw["steps"][0].update(moving_key=None, translation_mm=[0, 0, 0])
    previous = compile_concept(raw)
    assert not assembly_review_issues(previous, per_component=False)
    with pytest.raises(ValueError, match="walls do not fit"):
        add_parametric_enclosure(previous, request(clearance_mm=6))


@pytest.mark.parametrize(
    "change",
    [
        {"clearance_mm": float("nan")},
        {"wall_mm": True},
        {"wall_mm": 0.1},
        {"color": "black"},
        {"open_bottom": False},
        {"open_bottom": 1},
        {"target_keys": ["sample_tray", "sample_tray"]},
        {"source_id": "invented"},
    ],
)
def test_typed_operation_rejects_invalid_or_unsupported_parameters(change):
    with pytest.raises(ValueError):
        EnclosureRequest.model_validate(request(**change))


@pytest.mark.parametrize(
    "change,match",
    [
        ({"key": "sample_tray"}, "new, distinct"),
        ({"target_keys": ["missing"]}, "existing modeled"),
        ({"target_keys": ["rail_base"]}, "rather than the base"),
        ({"clearance_mm": 50}, "walls do not fit"),
    ],
)
def test_infeasible_operations_preserve_accepted_geometry(change, match):
    previous = compile_concept(proposal())
    untouched = deepcopy(previous)
    with pytest.raises(ValueError, match=match):
        add_parametric_enclosure(previous, request(**change))
    assert previous == untouched


def test_moving_base_and_multiple_base_requests_are_rejected():
    raw = proposal()
    raw["steps"][0].update(component_keys=["rail_base"], moving_key="rail_base")
    with pytest.raises(ValueError, match="base moves"):
        add_parametric_enclosure(compile_concept(raw), request())
    raw = proposal()
    other = deepcopy(raw["components"][1])
    other.update(key="other_tray", parent_key=None, placement_mm=None)
    raw["components"].append(other)
    with pytest.raises(ValueError, match="one stationary base"):
        add_parametric_enclosure(
            compile_concept(raw), request(target_keys=["sample_tray", "other_tray"])
        )


def test_normal_work_interface_validation_cannot_be_bypassed(monkeypatch):
    previous = compile_concept(proposal())
    monkeypatch.setattr(
        "app.concept_design.work_interface_issues",
        lambda design: (
            ["Proposed optical path is blocked."] if len(design["components"]) > 2 else []
        ),
    )
    with pytest.raises(ValueError, match="optical path"):
        add_parametric_enclosure(previous, request())


def test_feedback_returns_largest_grid_fit_without_adopting_or_mutating_request():
    previous = compile_concept(proposal())
    operation = request(clearance_mm=25)
    saved = deepcopy((previous, operation))
    assert supported_enclosure_clearance(previous, operation) == 22
    assert (previous, operation) == saved
    assert len(previous["components"]) == 2
    assert supported_enclosure_clearance(previous, request(clearance_mm=5.3)) == 5.3


def test_feedback_returns_none_when_other_constraints_cannot_be_resolved_by_clearance():
    previous = compile_concept(proposal())
    assert supported_enclosure_clearance(previous, request(clearance_mm=1), 100) is None


def test_infeasible_mounting_reports_requested_numeric_dimensions():
    previous = compile_concept(proposal())
    with pytest.raises(ValueError, match=r"196 x 156 mm at 50 mm clearance"):
        add_parametric_enclosure(previous, request(clearance_mm=50))
