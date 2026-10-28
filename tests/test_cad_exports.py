"""Round-trip and regeneration checks for shared concept CAD."""

import json
import math
import subprocess
import sys

import pytest
from build123d import import_step

from app.cad_exports import build_cad_files
from app.domain import apply_update, new_project


@pytest.fixture(scope="module")
def exported():
    project = apply_update(new_project(), {"workspace_width_mm": 450, "cooling_enabled": True})
    return project, build_cad_files(project)


def test_report_and_exact_primitive_manifest(exported):
    project, files = exported
    assert len(files) == 6
    report = json.loads(files["cad/geometry-report.json"])
    assert report["project_id"] == project["id"] and report["revision"] == project["revision"]
    assert report["units"] == "mm" and report["interfaces"] == []
    assert report["fabrication_ready"] is False and "not selected" in report["material"]
    assert (
        len(report["source"]["source_sha256"])
        == len(report["source"]["geometry_source_sha256"])
        == 64
    )
    entries = {c["id"]: c for c in report["components"]}
    assert report["component_count"] == len(project["design"]["components"])
    assert (
        report["solid_count"]
        == sum(c["solids"] for c in entries.values())
        > report["component_count"]
    )
    for c in project["design"]["components"]:
        entry = entries[c["id"]]
        assert entry["primitive_manifest"] == c["geometry"]["primitives"]
        assert entry["valid"] and entry["volume_mm3"] > 0
        assert "overlaps" in entry["volume_scope"]
        assert all(
            b <= expected + 1e-6
            for b, expected in zip(
                entry["bbox_cad"]["size"], [c["size"][0], c["size"][2], c["size"][1]]
            )
        )
    deck = entries["base"]
    assert deck["bbox_cad"]["size"] == pytest.approx([400, 670, 20])
    assert deck["volume_mm3"] == pytest.approx(400 * 670 * 20)
    assert b"source-rack/perforated-top" in files["cad/workstation.svg"]
    assert b"<circle" in files["cad/workstation.svg"]


def test_perforated_plate_has_actual_through_holes():
    from build123d import Align, Cylinder, Pos

    from app.cad_exports import _primitive_solid

    rack = next(c for c in new_project()["design"]["components"] if c["id"] == "source-rack")
    plate = next(p for p in rack["geometry"]["primitives"] if p["kind"] == "plate")
    solid = _primitive_solid(rack, plate)
    sx, sy, sz = plate["size"]
    removed = sum(math.pi * h["radius_mm"] ** 2 * sy for h in plate["holes"])
    assert solid.volume == pytest.approx(sx * sy * sz - removed)
    hole = plate["holes"][1]
    x, y, z = rack["position"]
    dx, dy, dz = plate["position"]
    probe = Pos(x + dx + hole["x_mm"], z + dz + hole["z_mm"], y + dy) * Cylinder(
        hole["radius_mm"] * 0.8, sy, align=(Align.CENTER,) * 3
    )
    intersection = solid & probe
    assert intersection is None or intersection.volume == pytest.approx(0, abs=1e-7)


def test_reopen_step_and_regenerate_source(exported, tmp_path):
    _, files = exported
    report = json.loads(files["cad/geometry-report.json"])
    for name in ("workstation.step", "deck.step"):
        path = tmp_path / name
        path.write_bytes(files["cad/" + name])
        shape = import_step(str(path))
        assert shape.is_valid
        assert len(shape.solids()) == (report["solid_count"] if name == "workstation.step" else 1)
        if name == "workstation.step":
            assert {child.label for child in shape.children} == {
                c["id"] for c in report["components"]
            }
        else:
            assert [
                shape.bounding_box().size.X,
                shape.bounding_box().size.Y,
                shape.bounding_box().size.Z,
            ] == pytest.approx([400, 670, 20])
    source = tmp_path / "deck-model.py"
    source.write_bytes(files["cad/deck-model.py"])
    subprocess.run([sys.executable, str(source)], check=True, cwd=tmp_path, timeout=90)
    regenerated = import_step(str(tmp_path / "workstation.step"))
    assert regenerated.is_valid and len(regenerated.solids()) == report["solid_count"]
    assert regenerated.volume == pytest.approx(
        sum(c["volume_mm3"] for c in report["components"]), rel=1e-6
    )
    assert {child.label for child in regenerated.children} == {
        c["id"] for c in report["components"]
    }


@pytest.mark.parametrize("axis", ["x", "z"])
@pytest.mark.parametrize("kind", ["cylinder", "frustum"])
def test_horizontal_round_primitives_preserve_axis_and_position(axis, kind):
    from build123d import Align, Box, Pos

    from app.cad_exports import _primitive_solid

    dimensions = {"x": [20, 8, 8], "z": [8, 8, 20]}[axis]
    primitive = {
        "id": "horizontal",
        "kind": kind,
        "position": [5, 6, 7],
        "size": dimensions,
        "axis": axis,
        "radius_top_mm": 4,
        "radius_bottom_mm": 2,
    }
    solid = _primitive_solid({"position": [11, 12, 13]}, primitive)
    bounds = solid.bounding_box()
    assert [bounds.size.X, bounds.size.Y, bounds.size.Z] == pytest.approx(
        [dimensions[0], dimensions[2], dimensions[1]]
    )
    assert [bounds.center().X, bounds.center().Y, bounds.center().Z] == pytest.approx([16, 20, 18])
    if kind == "frustum":
        # The larger, top radius is on the positive application axis.
        cx, cy, cz = 16, 20, 18
        slice_size = (1, 10, 10) if axis == "x" else (10, 1, 10)
        offset = (9, 0, 0) if axis == "x" else (0, 9, 0)
        small = solid & (
            Pos(cx - offset[0], cy - offset[1], cz) * Box(*slice_size, align=(Align.CENTER,) * 3)
        )
        large = solid & (
            Pos(cx + offset[0], cy + offset[1], cz) * Box(*slice_size, align=(Align.CENTER,) * 3)
        )
        assert large.volume > small.volume


def test_frame_sections_form_connected_shapes():
    from app.cad_exports import _primitive_solid
    from app.geometry import geometry_for_component

    for kind, size in (("column", [22, 300, 22]), ("rail", [356, 18, 18])):
        comp = {"id": kind, "kind": kind, "position": [0, 0, 0], "size": size}
        primitives = geometry_for_component(comp)["primitives"]
        solids = [_primitive_solid(comp, primitive) for primitive in primitives]
        joined = solids[0].fuse(*solids[1:])
        assert joined.is_valid and len(joined.solids()) == 1


@pytest.mark.parametrize("selection", [None, "opentrons-gen2"])
def test_cold_enclosure_floor_walls_and_lid_are_connected(selection):
    from app.cad_exports import _primitive_solid

    patch = {"cooling_enabled": True}
    if selection:
        patch["selections"] = {"cooling": selection}
    project = apply_update(new_project(), patch)
    bay = next(c for c in project["design"]["components"] if c["id"] == "cold-storage")
    parts = [
        p
        for p in bay["geometry"]["primitives"]
        if p["id"] in {"floor", "lid"} or p["id"].startswith("wall-")
    ]
    assert len(parts) == 6
    shapes = [_primitive_solid(bay, p) for p in parts]
    shell = shapes[0].fuse(*shapes[1:])
    assert shell.is_valid and len(shell.solids()) == 1


def test_export_uses_loaded_source_when_files_or_inspection_change(exported, monkeypatch):
    import inspect
    from pathlib import Path

    from app import cad_exports, geometry

    project, original = exported
    report_before = json.loads(original["cad/geometry-report.json"])
    source_before = original["cad/deck-model.py"]
    real_read_bytes = Path.read_bytes

    def changed_source(path):
        if path.resolve() in (
            Path(cad_exports.__file__).resolve(),
            Path(geometry.__file__).resolve(),
        ):
            return b"changed after import"
        return real_read_bytes(path)

    def unavailable(*args, **kwargs):
        raise RuntimeError("source no longer available")

    monkeypatch.setattr(Path, "read_bytes", changed_source)
    monkeypatch.setattr(inspect, "getsource", unavailable)
    after = cad_exports.build_cad_files(project)
    report_after = json.loads(after["cad/geometry-report.json"])
    assert after["cad/deck-model.py"] == source_before
    assert report_after["source"]["source_sha256"] == report_before["source"]["source_sha256"]
    assert (
        report_after["source"]["geometry_source_sha256"]
        == report_before["source"]["geometry_source_sha256"]
    )
