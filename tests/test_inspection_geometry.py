"""Inspection arm geometric and serialization contract checks."""

import json
import math
from copy import deepcopy

import pytest

from app.domain import apply_update, new_project
from app.inspection_geometry import compile_inspection, inspection_components


def proposal(**patch):
    result = {
        "schema_version": "1",
        "link_lengths_mm": [400, 400],
        "mast_height_mm": 450,
        "rationale": "Concept",
        "assumptions": [],
    }
    result.update(patch)
    return result


def part_map(parts):
    return {part["id"]: part for part in parts}


def test_deterministic_independent_components_and_json():
    project = new_project()
    original = deepcopy(project)
    spec = proposal()
    original_spec = deepcopy(spec)
    module = compile_inspection(project, spec)
    assert project == original and spec == original_spec
    assert module == compile_inspection(project, spec)
    json.dumps(module, allow_nan=False)
    copied = inspection_components(module)
    assert copied == module["components"] and copied is not module["components"]
    copied[0]["position"][0] += 1
    assert copied != module["components"]
    assert module["attachment"]["parent_component_id"] == "base"
    assert [frame["time_s"] for frame in module["pose_frames"]] == [0, 2, 4, 6]


@pytest.mark.parametrize(
    "patch",
    [
        {"link_lengths_mm": [float("nan"), 400]},
        {"link_lengths_mm": [float("inf"), 400]},
        {"link_lengths_mm": [True, 400]},
        {"link_lengths_mm": [179, 400]},
        {"link_lengths_mm": [400, 501]},
        {"link_lengths_mm": [400]},
        {"mast_height_mm": float("inf")},
        {"mast_height_mm": 399},
        {"mast_height_mm": 551},
        {"mast_height_mm": False},
        {"schema_version": 1},
        {"extra": "unexpected"},
        {"assumptions": [4]},
    ],
)
def test_strict_proposal_validation(patch):
    with pytest.raises(ValueError):
        compile_inspection(new_project(), proposal(**patch))


def test_pose_endpoints_and_rack_scan():
    project = new_project()
    module = compile_inspection(project, proposal())
    rack = part_map(project["design"]["components"])["sample-rack"]
    for frame, dx in zip(module["pose_frames"], [0, -20, 20, 0]):
        parts = part_map(frame["components"])
        shoulder = parts["inspection-shoulder"]["position"]
        elbow = parts["inspection-elbow"]["position"]
        wrist = parts["inspection-wrist"]["position"]
        angles = frame["joint_angles_deg"]
        q1, q2 = map(math.radians, (angles["shoulder"], angles["elbow"]))
        assert elbow[0] == pytest.approx(shoulder[0] + 400 * math.cos(q1))
        assert elbow[2] == pytest.approx(shoulder[2] + 400 * math.sin(q1))
        assert wrist[0] == pytest.approx(elbow[0] + 400 * math.cos(q1 + q2))
        assert wrist[2] == pytest.approx(elbow[2] + 400 * math.sin(q1 + q2))
        assert wrist[0] == pytest.approx(rack["position"][0] + dx)
        assert wrist[2] == pytest.approx(rack["position"][2])
        assert frame["camera_mm"] == parts["inspection-camera"]["position"]
        assert frame["target_mm"][0] == pytest.approx(wrist[0])
        assert frame["target_mm"][2] == pytest.approx(wrist[2])


def test_rotated_primitives_are_inside_component_and_overall_bounds():
    module = compile_inspection(new_project(), proposal())
    for frame in module["pose_frames"]:
        for part in frame["components"]:
            for primitive in part["geometry"]["primitives"]:
                angle = math.radians(primitive.get("rotation_y_deg", 0))
                x, y, z = primitive["size"]
                rotated = [
                    abs(x * math.cos(angle)) + abs(z * math.sin(angle)),
                    y,
                    abs(x * math.sin(angle)) + abs(z * math.cos(angle)),
                ]
                for i in range(3):
                    assert (
                        abs(primitive["position"][i]) + rotated[i] / 2 <= part["size"][i] / 2 + 1e-8
                    )
                    assert (
                        part["position"][i] - part["size"][i] / 2
                        >= module["bounds"]["min_mm"][i] - 1e-8
                    )
                    assert (
                        part["position"][i] + part["size"][i] / 2
                        <= module["bounds"]["max_mm"][i] + 1e-8
                    )


def test_camera_mount_and_lens_meet_in_each_pose():
    module = compile_inspection(new_project(), proposal())
    for frame in module["pose_frames"]:
        parts = part_map(frame["components"])
        camera = parts["inspection-camera"]
        wrist = parts["inspection-wrist"]
        shapes = {p["id"]: p for p in camera["geometry"]["primitives"]}

        def top(shape):
            return camera["position"][1] + shape["position"][1] + shape["size"][1] / 2

        def bottom(shape):
            return camera["position"][1] + shape["position"][1] - shape["size"][1] / 2

        assert top(shapes["mounting-neck"]) == pytest.approx(
            wrist["position"][1] - wrist["size"][1] / 2
        )
        assert bottom(shapes["mounting-neck"]) == pytest.approx(top(shapes["body"]))
        assert top(shapes["lens"]) == pytest.approx(bottom(shapes["body"]))
        assert frame["camera_mm"] == camera["position"]


def test_sidecar_beyond_cooling_extension_and_stable_ids():
    wide = new_project()
    compact_cold = apply_update(wide, {"workspace_width_mm": 450, "cooling_enabled": True})
    modules = [compile_inspection(project, proposal()) for project in (wide, compact_cold)]
    assert modules[0]["component_ids"] == modules[1]["component_ids"]
    assert len(set(modules[0]["component_ids"])) == 8
    for project, module in zip((wide, compact_cold), modules):
        base = part_map(project["design"]["components"])["base"]
        mount = part_map(module["components"])["inspection-mount"]
        pad = next(p for p in mount["geometry"]["primitives"] if p["id"] == "pad")
        front = base["position"][2] + base["size"][2] / 2
        assert mount["position"][2] + pad["position"][2] - pad["size"][2] / 2 > front
        assert (
            abs(mount["position"][0] - base["position"][0]) + pad["size"][0] / 2
            <= base["size"][0] / 2
        )
        assert module["attachment"]["anchor_mm"][2] == front


def test_unreachable_targets_are_rejected():
    project = apply_update(new_project(), {"workspace_width_mm": 450, "cooling_enabled": True})
    with pytest.raises(ValueError, match="unreachable"):
        compile_inspection(project, proposal(link_lengths_mm=[180, 180]))
