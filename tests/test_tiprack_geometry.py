"""Synthetic dimensions test the geometry, not the fit of real disposable tips."""
import math

import pytest

from app.tiprack_geometry import compile_tiprack

SPEC = {"body_diameter_max_mm": 5, "rim_diameter_min_mm": 8,
        "rim_diameter_max_mm": 8.5, "below_rim_height_mm": 45,
        "count": 6, "columns": 3}
RECORD = {"kind": "rim_supported_tip_rack", "target_component_id": "tip-rack",
          "profile_id": "custom_printed_tip_rack", "spec": SPEC}


def test_commercial_profiles_keep_pinned_pattern_and_schematic_scope():
    def reference(profile_id):
        return compile_tiprack({"kind": "commercial_reference", "target_component_id": "tip-rack",
                                "profile_id": profile_id})

    tipone = reference("tipone_96_tiprack_200ul")
    opentrons = reference("opentrons_96_tiprack_300ul")
    assert tipone["size_mm"] == [127.76, 63.9, 85.48]
    assert opentrons["size_mm"] == [127.76, 64.49, 85.48]
    for value in (tipone, opentrons):
        assert len(value["geometry"]["primitives"][1]["holes"]) == 96
        assert value["derived"]["schematic_recess_mm"] == 3
        assert "not vendor CAD" in value["checks"]["scope"]
        assert len(value["profile"]["source"]["sha256"]) == 64
    a, b = (value["geometry"]["primitives"][1]["holes"][0]
            for value in (tipone, opentrons))
    assert (a["x_mm"], a["z_mm"], a["radius_mm"]) == pytest.approx((-50.19, 29.51, 3.2))
    assert (b["x_mm"], b["z_mm"], b["radius_mm"]) == pytest.approx((-49.5, 31.5, 2.615))
    assert tipone["derived"]["software_well_depth_mm"] == 10.54
    assert opentrons["derived"]["software_well_depth_mm"] == 59.3
    with pytest.raises(ValueError, match="source binding"):
        compile_tiprack({"kind": "commercial_reference", "target_component_id": "tip-rack",
                         "profile_id": "tipone_96_tiprack_200ul",
                         "profile_binding": {"sha256": "incorrect"}})


def test_bounded_tip_rack_and_invalid_inputs():
    rack = compile_tiprack(RECORD)
    assert rack["derived"]["bore_diameter_mm"] == pytest.approx(6.1)
    assert rack["checks"]["body_radial_clearance_min_assumed_mm"] == pytest.approx(0.4)
    assert rack["checks"]["rim_land_min_assumed_mm"] == pytest.approx(0.8)
    assert rack["checks"]["rim_gap_mm"] == pytest.approx(0.9)
    assert len(rack["geometry"]["primitives"][0]["holes"]) == 6
    for changed in ({"rim_diameter_min_mm": 6}, {"rim_diameter_max_mm": 7},
                    {"pitch_mm": 4}, {"count": 97}, {"max_width_mm": 10},
                    {"body_diameter_max_mm": math.nan}):
        with pytest.raises(ValueError):
            compile_tiprack({**RECORD, "spec": {**SPEC, **changed}})


def test_exported_solid_clearance_bearing_and_coupon(tmp_path):
    from build123d import Align, Cylinder, Pos, Unit, export_step, import_step

    from app.cad_exports import _build_rack_fit_coupon, _build_solid

    rack = compile_tiprack(RECORD)
    component = {"id": "tip-rack", "position": [0, 0, 0], "geometry": rack["geometry"],
                 "fabrication_shape": "rim_supported_tip_rack"}
    solid = _build_solid(component)
    path = tmp_path / "tip-rack.step"
    export_step(solid, str(path), unit=Unit.MM)
    actual = import_step(str(path))
    assert actual.is_valid and len(actual.solids()) == 1
    box = actual.bounding_box().size
    assert [box.X, box.Z, box.Y] == pytest.approx(rack["size_mm"])
    top_center = rack["size_mm"][1] / 2 - 2
    align = (Align.CENTER,) * 3
    for hole in rack["geometry"]["primitives"][0]["holes"]:
        place = Pos(hole["x_mm"], hole["z_mm"], top_center)
        gauge = place * Cylinder(2.9, 4, align=align)
        overlap = actual & gauge
        assert overlap is None or overlap.volume == pytest.approx(0, abs=1e-6)
        bearing = place * (Cylinder(4, 4, align=align) - Cylinder(3.2, 4, align=align))
        assert (actual & bearing).volume == pytest.approx(bearing.volume, rel=1e-6)
    coupon = _build_rack_fit_coupon(component)
    assert coupon.is_valid and len(coupon.solids()) == 1
    assert coupon.volume == pytest.approx((18.1 ** 2 - math.pi * 3.05 ** 2) * 4)


def test_tip_rack_package_rebuild_and_mismatch_rejection(tmp_path, monkeypatch):
    import subprocess
    import sys
    import tempfile

    from build123d import import_step

    from app.cad_exports import build_cad_files
    from app.domain import new_project
    from app.geometry import add_geometry

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    project = new_project()
    rack = compile_tiprack(RECORD)
    component = next(c for c in project["design"]["components"] if c["id"] == "tip-rack")
    component["size"] = rack["size_mm"]
    project["tip_rack"] = RECORD
    project = add_geometry(project)
    files = build_cad_files(project)
    for name in ("tip-rack.step", "tip-rack.stl", "tip-rack-fit-coupon.step",
                 "tip-rack-fit-coupon.stl"):
        assert files["cad/" + name]
    path = tmp_path / "tip-rack.step"
    path.write_bytes(files["cad/tip-rack.step"])
    original = import_step(str(path))
    source = tmp_path / "deck-model.py"
    source.write_bytes(files["cad/deck-model.py"])
    subprocess.run([sys.executable, str(source)], check=True, cwd=tmp_path, timeout=90)
    regenerated = import_step(str(path))
    assert regenerated.is_valid and len(regenerated.solids()) == 1
    assert regenerated.volume == pytest.approx(original.volume, rel=1e-7)
    component = next(c for c in project["design"]["components"] if c["id"] == "tip-rack")
    component["geometry"]["primitives"][0]["holes"][0]["radius_mm"] = 1
    with pytest.raises(ValueError, match="Tip rack geometry"):
        build_cad_files(project)


def test_commercial_package_contains_selected_pinned_source_and_license(tmp_path, monkeypatch):
    import hashlib
    import json
    import tempfile

    from app.cad_exports import build_cad_files
    from app.domain import new_project
    from app.geometry import add_geometry

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    profile_id = "tipone_96_tiprack_200ul"
    record = {"kind": "commercial_reference", "target_component_id": "tip-rack",
              "profile_id": profile_id}
    rack = compile_tiprack(record)
    record["profile"] = rack["profile"]
    project = new_project()
    component = next(c for c in project["design"]["components"] if c["id"] == "tip-rack")
    component["size"] = rack["size_mm"]
    project["tip_rack"] = record
    files = build_cad_files(add_geometry(project))
    raw = files[f"cad/source/tiprack-{profile_id}.json"]
    assert hashlib.sha256(raw).hexdigest() == rack["profile"]["source"]["sha256"]
    provenance = json.loads(files["cad/source/tiprack-provenance.json"])
    assert rack["profile"]["source"]["revision"] in json.dumps(provenance)
    assert rack["profile"]["source"]["sha256"] in json.dumps(provenance)
    assert b"Apache License" in files["cad/source/tiprack-LICENSE.txt"]
    assert "cad/tip-rack.stl" not in files
