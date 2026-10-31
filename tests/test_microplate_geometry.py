"""Pinned microplate reference, holder geometry and STEP round-trip checks."""

import json
import subprocess
import sys

import pytest

from app.microplate_geometry import PROFILE_ID, SOURCE_SHA256, compile_microplate


def test_pinned_profile_and_orientation():
    plate = compile_microplate(PROFILE_ID)
    assert plate["profile"]["source"]["sha256"] == SOURCE_SHA256
    assert plate["size_mm"] == pytest.approx([135.36, 16.72, 93.08])
    assert plate["derived"]["holder_pocket_mm"] == pytest.approx([129.36, 87.08])
    assert plate["derived"]["well_count"] == 96
    assert plate["derived"]["well_capacity_ul"] == 360
    wells = {w["label"]: w for w in plate["derived"]["wells"]}
    assert wells["A1"]["app_x_mm"] == pytest.approx(-49.5)
    assert wells["A1"]["app_z_mm"] == pytest.approx(31.505)
    assert wells["A1"]["app_y_mm"] == pytest.approx(8.36)
    assert wells["H1"]["app_z_mm"] == pytest.approx(-31.495)
    assert wells["A12"]["app_x_mm"] - wells["A1"]["app_x_mm"] == pytest.approx(99)
    assert all(w["diameter_mm"] == 6.86 and w["depth_mm"] == 10.67 for w in wells.values())
    with pytest.raises(ValueError):
        compile_microplate("unsupported")


def test_rejects_tampered_source_and_provenance(tmp_path, monkeypatch):
    import app.microplate_geometry as module

    source = module.SOURCE_PATH.read_bytes()
    (tmp_path / (PROFILE_ID + ".json")).write_bytes(source)
    provenance = json.loads((module.DATA_DIR / "provenance.json").read_text(encoding="utf-8-sig"))
    provenance["license"] = "unverified"
    (tmp_path / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    monkeypatch.setattr(module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(module, "SOURCE_PATH", tmp_path / (PROFILE_ID + ".json"))
    with pytest.raises(ValueError, match="provenance mismatch"):
        compile_microplate(PROFILE_ID)
    (tmp_path / (PROFILE_ID + ".json")).write_bytes(source + b" ")
    with pytest.raises(ValueError, match="definition hash mismatch"):
        compile_microplate(PROFILE_ID)


def test_reopened_holder_and_schematic_export_regeneration(tmp_path):
    from build123d import Align, Box, Cylinder, Pos, import_step

    from app.cad_exports import build_cad_files
    from app.domain import new_project
    from app.geometry import add_geometry

    plate = compile_microplate(PROFILE_ID)
    project = new_project()
    component = next(c for c in project["design"]["components"] if c["id"] == "sample-rack")
    component["size"] = plate["size_mm"]
    component["position"] = [0, plate["size_mm"][1] / 2, 0]
    project["labware_plate"] = {
        "kind": "microplate_96",
        "profile_id": PROFILE_ID,
        "target_component_id": "sample-rack",
    }
    project = add_geometry(project)
    files = build_cad_files(project)
    assert "cad/tube-rack.step" not in files
    for name in ("plate-holder.step", "plate-holder.stl", "plate-reference.step", "deck-model.py"):
        (tmp_path / name).write_bytes(files["cad/" + name])
    holder = import_step(str(tmp_path / "plate-holder.step"))
    reference = import_step(str(tmp_path / "plate-reference.step"))
    assert holder.is_valid and len(holder.solids()) == 1
    assert reference.is_valid and len(reference.solids()) == 1
    assert [
        holder.bounding_box().size.X,
        holder.bounding_box().size.Y,
        holder.bounding_box().size.Z,
    ] == pytest.approx([135.36, 93.08, 4.5])
    assert holder.volume == pytest.approx(
        135.36 * 93.08 * 2.5 + (135.36 * 93.08 - 129.36 * 87.08) * 2
    )
    # Maximum material condition plus functional allowance fits even with assumed undersize.
    gauge = Pos(0, 0, 3.5) * Box(128.26 + 0.8, 85.98 + 0.8, 2, align=(Align.CENTER,) * 3)
    overlap = holder & gauge
    assert overlap is None or overlap.volume == pytest.approx(0, abs=1e-6)
    floor = Pos(0, 0, 1.25) * Box(128.26, 85.98, 2.5, align=(Align.CENTER,) * 3)
    assert (holder & floor).volume == pytest.approx(floor.volume, rel=1e-7)
    wall = Pos((129.36 + 3) / 2, 0, 3.5) * Box(3, 87.08, 2, align=(Align.CENTER,) * 3)
    assert (holder & wall).volume == pytest.approx(wall.volume, rel=1e-7)
    for w in plate["derived"]["wells"]:
        bore = Pos(w["app_x_mm"], w["app_z_mm"], 2.5 + 3.55 + 10.67 / 2) * Cylinder(
            6.86 / 2, 10.67, align=(Align.CENTER,) * 3
        )
        overlap = reference & bore
        assert overlap is None or overlap.volume == pytest.approx(0, abs=1e-5)
    report = json.loads(files["cad/geometry-report.json"])
    assert len(report["interfaces"]) == 2
    assert report["source"]["microplate_geometry_source_sha256"]
    subprocess.run(
        [sys.executable, "-I", str(tmp_path / "deck-model.py")],
        cwd=tmp_path,
        check=True,
        timeout=180,
    )
    regenerated = import_step(str(tmp_path / "plate-holder.step"))
    assert regenerated.volume == pytest.approx(holder.volume, rel=1e-7)
    assert import_step(str(tmp_path / "plate-reference.step")).volume == pytest.approx(
        reference.volume, rel=1e-7
    )
