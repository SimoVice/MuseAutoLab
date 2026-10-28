"""Shared inspection geometry survives exact CAD export and regeneration."""

import json
import math
from copy import deepcopy

import pytest
from build123d import import_step

from app.cad_exports import _bbox_of, _build_solid, build_cad_files
from app.domain import new_project
from app.geometry import add_geometry
from app.inspection_geometry import compile_inspection


def with_inspection():
    project = new_project()
    extension = compile_inspection(
        project,
        {
            "schema_version": "1",
            "link_lengths_mm": [400, 400],
            "mast_height_mm": 450,
            "rationale": "Concept",
            "assumptions": [],
        },
    )
    project["inspection_extension"] = extension
    project["design"]["components"].extend(deepcopy(extension["components"]))
    return project


def test_geometry_regenerates_only_known_compiled_components():
    project = with_inspection()
    expected = project["inspection_extension"]["components"]
    result = add_geometry(project)
    by_id = {part["id"]: part for part in result["design"]["components"]}
    for part in expected:
        assert by_id[part["id"]]["geometry"] == part["geometry"]
    # Arbitrary stored geometry does not become authoritative, even with a known ID.
    known = next(p for p in project["design"]["components"] if p["id"] == "inspection-upper-link")
    known["geometry"]["primitives"][0]["rotation_y_deg"] = 999
    regenerated = add_geometry(project)
    fixed = next(p for p in regenerated["design"]["components"] if p["id"] == known["id"])
    assert fixed["geometry"] == next(p for p in expected if p["id"] == known["id"])["geometry"]
    project["design"]["components"].append(
        {
            "id": "inspection-arbitrary",
            "kind": "inspection-link",
            "label": "Unknown",
            "position": [0, 0, 0],
            "size": [10, 10, 10],
            "geometry": {"schema_version": "1", "primitives": [{"id": "untrusted"}]},
        }
    )
    unknown = add_geometry(project)["design"]["components"][-1]
    assert unknown["geometry"]["primitives"][0]["id"] == "envelope"


def test_cad_step_and_regenerated_builder_preserve_yaw(tmp_path):
    project = with_inspection()
    files = build_cad_files(project)
    step = tmp_path / "workstation.step"
    step.write_bytes(files["cad/workstation.step"])
    assert import_step(step).is_valid
    report = json.loads(files["cad/geometry-report.json"])
    entries = {part["id"]: part for part in report["components"]}
    source = files["cad/deck-model.py"].decode()
    assert 'Rot(0, 0, -primitive.get("rotation_y_deg", 0))' in source
    namespace = {"__name__": "inspection_regenerated"}
    exec(compile(source, "deck-model.py", "exec"), namespace)
    assert namespace["build"]().is_valid
    for part in project["inspection_extension"]["components"]:
        if part["kind"] != "inspection-link":
            continue
        primitive = part["geometry"]["primitives"][0]
        yaw = math.radians(primitive["rotation_y_deg"])
        x, y, z = primitive["size"]
        expected = [
            abs(x * math.cos(yaw)) + abs(z * math.sin(yaw)),
            abs(x * math.sin(yaw)) + abs(z * math.cos(yaw)),
            y,
        ]
        assert entries[part["id"]]["bbox_cad"]["size"] == pytest.approx(expected, abs=1e-6)
        regenerated = next(c for c in namespace["COMPONENTS_MM"] if c["id"] == part["id"])
        assert _bbox_of(namespace["_build_solid"](regenerated))["size"] == pytest.approx(
            _bbox_of(_build_solid(part))["size"], abs=1e-6
        )


def test_invalid_yaw_or_rotated_extent_is_rejected():
    project = with_inspection()
    link = next(p for p in project["design"]["components"] if p["id"] == "inspection-upper-link")
    link["geometry"]["primitives"][0]["rotation_y_deg"] = float("nan")
    with pytest.raises(ValueError, match="primitive"):
        build_cad_files(project)
    link["geometry"]["primitives"][0]["rotation_y_deg"] = 90
    link["size"] = [5, 5, 5]
    with pytest.raises(ValueError, match="primitive"):
        build_cad_files(project)
