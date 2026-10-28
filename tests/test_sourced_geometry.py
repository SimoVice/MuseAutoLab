"""Manufacturer envelopes remain visible in the shared geometry and CAD."""

import json
from copy import deepcopy

import pytest

from app.cad_exports import _bbox_of, _build_solid, build_cad_files
from app.domain import apply_update, new_project
from app.geometry import add_geometry, geometry_for_component
from app.inspection_geometry import compile_inspection


def parts(components):
    return {component["id"]: component for component in components}


def test_motor_selection_changes_real_geometry_without_mutating_project():
    initial = new_project()
    initial_copy = deepcopy(initial)
    smaller = apply_update(initial, {"selections": {"motors": "pololu-1208"}})
    assert initial == initial_copy
    for project, reference, expected in (
        (initial, "pololu-1209", [35, 36, 35]),
        (smaller, "pololu-1208", [35, 28, 35]),
    ):
        snapshot = deepcopy(project)
        carriage = parts(add_geometry(project)["design"]["components"])["carriage"]
        assert project == snapshot
        assert carriage["size"] == [75, 70, 65]
        motor = next(p for p in carriage["geometry"]["primitives"] if p["id"] == "motor")
        assert motor["size"] == expected
        assert motor["reference_id"] == reference
        assert motor["dimension_basis"] == "manufacturer_envelope"
        assert "excluding shaft" in motor["scope"].lower()
        assert all(
            abs(p) + s / 2 <= b / 2
            for p, s, b in zip(motor["position"], motor["size"], carriage["size"])
        )
        assert carriage["reference_geometry"]["motor"]["reference_id"] == reference
        # The same primitive is used by the real CAD builder, in x/z/y order.
        motor_only = {**carriage, "geometry": {"primitives": [motor]}}
        assert _bbox_of(_build_solid(motor_only))["size"] == pytest.approx(
            [expected[0], expected[2], expected[1]]
        )
    old = {"id": "legacy", "kind": "carriage", "size": [75, 70, 65]}
    assert next(p for p in geometry_for_component(old)["primitives"] if p["id"] == "motor")[
        "size"
    ] != [35, 36, 35]


def test_camera_envelope_and_custom_neck_are_connected_in_every_pose():
    project = new_project()
    before = deepcopy(project)
    proposal = {
        "schema_version": "1",
        "link_lengths_mm": [400, 400],
        "mast_height_mm": 450,
        "rationale": "Offline concept",
        "assumptions": [],
    }
    proposal_before = deepcopy(proposal)
    module = compile_inspection(project, proposal)
    assert project == before and proposal == proposal_before
    assert len(module["component_ids"]) == 9
    assert module["source_binding"]["camera"]["reference_id"] == "rpi-camera-module-3"
    assert module["geometry_source_sha256"]
    for frame in module["pose_frames"]:
        components = parts(frame["components"])
        camera = components["inspection-camera"]
        neck = components["inspection-camera-mount"]
        wrist = components["inspection-wrist"]
        assert camera["size"] == [25, 11.5, 24]
        assert frame["camera_mm"] == camera["position"]
        assert camera["position"][1] == 395
        assert camera["reference_geometry"]["reference_id"] == "rpi-camera-module-3"
        assert all(
            p["reference_id"] == "rpi-camera-module-3" for p in camera["geometry"]["primitives"]
        )
        assert neck["position"][1] - neck["size"][1] / 2 == pytest.approx(
            camera["position"][1] + camera["size"][1] / 2
        )
        assert neck["position"][1] + neck["size"][1] / 2 == pytest.approx(
            wrist["position"][1] - wrist["size"][1] / 2
        )
        assert _bbox_of(_build_solid(camera))["size"] == pytest.approx([25, 24, 11.5])
        assert _build_solid(neck).is_valid


def test_export_pipeline_preserves_source_bound_camera_and_motor():
    project = new_project()
    module = compile_inspection(
        project,
        {
            "schema_version": "1",
            "link_lengths_mm": [400, 400],
            "mast_height_mm": 450,
            "rationale": "Offline concept",
            "assumptions": [],
        },
    )
    project["inspection_extension"] = module
    project["design"]["components"].extend(deepcopy(module["components"]))
    report = json.loads(build_cad_files(add_geometry(project))["cad/geometry-report.json"])
    components = parts(report["components"])
    camera = components["inspection-camera"]
    motor = next(p for p in components["carriage"]["primitive_manifest"] if p["id"] == "motor")
    assert camera["bbox_cad"]["size"] == pytest.approx([25, 24, 11.5])
    assert all(p["reference_id"] == "rpi-camera-module-3" for p in camera["primitive_manifest"])
    assert motor["reference_id"] == "pololu-1209"
    assert motor["size"] == [35, 36, 35]
