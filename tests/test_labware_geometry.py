"""Geometric rack constraints and actual CAD solid checks with synthetic dimensions."""
import math

import pytest

from app.labware_geometry import compile_labware_rack

SPEC = dict(body_diameter_max_mm=11, rim_diameter_min_mm=14,
            cap_diameter_max_mm=15, below_rim_height_mm=40, count=6, columns=3)


def test_rack_dimensions_and_failures():
    rack = compile_labware_rack(SPEC)
    assert rack["derived"]["bore_diameter_mm"] == pytest.approx(12.1)
    assert rack["checks"]["body_radial_clearance_min_assumed_mm"] == pytest.approx(0.4)
    assert rack["checks"]["rim_land_min_assumed_mm"] == pytest.approx(0.8)
    assert rack["derived"]["tip_clearance_mm"] == 3
    assert len(rack["geometry"]["primitives"][0]["holes"]) == 6
    for changed in (dict(rim_diameter_min_mm=12), dict(pitch_mm=10),
                    dict(max_width_mm=10), dict(count=25), dict(body_diameter_max_mm=math.nan)):
        with pytest.raises(ValueError):
            compile_labware_rack({**SPEC, **changed})


def test_fused_exported_rack_has_clear_bores_and_bearing_material(tmp_path):
    from build123d import Align, Cylinder, Pos, Unit, export_step, import_step

    from app.cad_exports import _build_solid

    rack = compile_labware_rack(SPEC)
    comp = dict(id="sample-rack", position=[0, 0, 0], geometry=rack["geometry"],
                fabrication_shape="rim_supported_tube_rack")
    solid = _build_solid(comp)
    path = tmp_path / "rack.step"
    export_step(solid, str(path), unit=Unit.MM)
    actual = import_step(str(path))
    assert actual.is_valid and len(actual.solids()) == 1
    box = actual.bounding_box().size
    assert [box.X, box.Z, box.Y] == pytest.approx(rack["size_mm"])
    top_center = rack["size_mm"][1] / 2 - 2
    for hole in rack["geometry"]["primitives"][0]["holes"]:
        place = Pos(hole["x_mm"], hole["z_mm"], top_center)
        gauge = place * Cylinder(11 / 2 + 0.4, 4, align=(Align.CENTER,) * 3)
        overlap = actual & gauge
        assert overlap is None or overlap.volume == pytest.approx(0, abs=1e-6)
        ring = place * (Cylinder(14 / 2, 4, align=(Align.CENTER,) * 3)
                        - Cylinder((12.1 + 0.3) / 2, 4, align=(Align.CENTER,) * 3))
        assert (actual & ring).volume == pytest.approx(ring.volume, rel=1e-6)



def test_rack_package_and_self_contained_regeneration(tmp_path):
    import json
    import subprocess
    import sys

    from build123d import import_step

    from app.cad_exports import build_cad_files
    from app.domain import new_project
    from app.geometry import add_geometry

    project = new_project()
    rack = compile_labware_rack(SPEC)
    component = next(c for c in project["design"]["components"] if c["id"] == "sample-rack")
    component["size"] = rack["size_mm"]
    project["labware_rack"] = {"kind": "rim_supported_tube_rack", "spec": SPEC,
                               "target_component_id": "sample-rack"}
    project = add_geometry(project)
    files = build_cad_files(project)
    assert "cad/tube-rack.stl" in files
    assert "cad/tube-rack-fit-coupon.stl" in files
    coupon_path = tmp_path / "tube-rack-fit-coupon.step"
    coupon_path.write_bytes(files["cad/tube-rack-fit-coupon.step"])
    original_coupon = import_step(str(coupon_path))
    assert original_coupon.is_valid and len(original_coupon.solids()) == 1
    report = json.loads(files["cad/geometry-report.json"])
    entry = next(c for c in report["components"] if c["id"] == "sample-rack")
    assert entry["solids"] == 1 and entry["volume_scope"] == "One fused rack solid."
    assert len(report["source"]["labware_geometry_source_sha256"]) == 64
    path = tmp_path / "tube-rack.step"
    path.write_bytes(files["cad/tube-rack.step"])
    original = import_step(str(path))
    assert original.is_valid and len(original.solids()) == 1
    source = tmp_path / "deck-model.py"
    source.write_bytes(files["cad/deck-model.py"])
    subprocess.run([sys.executable, str(source)], check=True, cwd=tmp_path, timeout=90)
    regenerated_coupon = import_step(str(coupon_path))
    assert regenerated_coupon.is_valid and len(regenerated_coupon.solids()) == 1
    assert regenerated_coupon.volume == pytest.approx(original_coupon.volume, rel=1e-7)
    regenerated = import_step(str(path))
    assert regenerated.is_valid and len(regenerated.solids()) == 1
    assert regenerated.volume == pytest.approx(original.volume, rel=1e-7)


def test_fit_coupon_reopened_step_matches_bore_and_bearing(tmp_path):
    from build123d import Align, Cylinder, Pos, Unit, export_step, import_step

    from app.cad_exports import _build_rack_fit_coupon

    rack = compile_labware_rack(SPEC)
    coupon = _build_rack_fit_coupon({"geometry": rack["geometry"]})
    path = tmp_path / "coupon.step"
    export_step(coupon, str(path), unit=Unit.MM)
    actual = import_step(str(path))
    assert actual.is_valid and len(actual.solids()) == 1
    size = actual.bounding_box().size
    assert [size.X, size.Y, size.Z] == pytest.approx([24.1, 24.1, 4])
    align = (Align.CENTER,) * 3
    center = Pos(0, 0, 2)
    clearance = center * Cylinder((11 + 0.8) / 2, 4, align=align)
    overlap = actual & clearance
    assert overlap is None or overlap.volume == pytest.approx(0, abs=1e-6)
    bearing = center * (Cylinder(14 / 2, 4, align=align)
                        - Cylinder(12.4 / 2, 4, align=align))
    assert (actual & bearing).volume == pytest.approx(bearing.volume, rel=1e-6)
    assert actual.volume == pytest.approx((24.1 ** 2 - math.pi * (12.1 / 2) ** 2) * 4)
