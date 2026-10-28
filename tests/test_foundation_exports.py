"""Pinned foundation export, source identity and independent regeneration checks."""

import copy
import gc
import gzip
import hashlib
import json
import subprocess
import sys

import pytest
from build123d import import_step

from app.cad_exports import _bbox_of, _components, build_cad_files
from app.domain import new_project
from app.foundation_design import adopt_foundation
from app.geometry import add_geometry
from app.upstream_cad import STEP_SHA256, load_foundation_cad


@pytest.fixture(scope="module")
def project():
    return add_geometry(adopt_foundation(new_project(), bed_drop_mm=100))


@pytest.mark.parametrize(
    "mutation", ["id", "asset", "position", "size", "scale", "metadata", "primitive"]
)
def test_reject_source_spoof(project, mutation):
    bad = copy.deepcopy(project)
    comp = next(p for p in bad["design"]["components"] if p["id"] == "foundation-jubilee")
    if mutation == "id":
        comp["id"] = "other"
    elif mutation == "asset":
        comp["foundation_asset_id"] = "other"
    elif mutation == "position":
        comp["position"][0] = 1
    elif mutation == "size":
        comp["size"][0] += 1
    elif mutation == "scale":
        comp["scale"] = [2, 2, 2]
    elif mutation == "metadata":
        bad["design"]["foundation"]["source_sha256"] = "0" * 64
    else:
        comp["geometry"] = {"schema_version": "1", "primitives": [{"kind": "box"}]}
    with pytest.raises(ValueError):
        _components(bad)


def test_source_step_and_independent_rebuild(project, tmp_path):
    files = build_cad_files(project)
    report = json.loads(files["cad/geometry-report.json"])
    foundation = next(c for c in report["components"] if c["id"] == "foundation-jubilee")
    assert foundation["shape"] == "pinned upstream CAD"
    assert foundation["source_sha256"] == STEP_SHA256
    assert foundation["bed_drop_mm"] == 100
    assert foundation["solids"] == 809 and foundation["valid"]
    assert "primitive_manifest" not in foundation
    assert (
        hashlib.sha256(gzip.decompress(files["cad/source/jubilee-original.step.gz"])).hexdigest()
        == STEP_SHA256
    )
    for name, data in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    step = tmp_path / "cad/workstation.step"
    result = import_step(step)
    assert result.is_valid and len(result.solids()) == report["solid_count"]
    source_part = next(c for c in result.children if c.label == "foundation-jubilee")
    expected = load_foundation_cad(100)
    source_bounds = _bbox_of(source_part)
    for key in ("min", "max"):
        assert source_bounds[key] == pytest.approx(foundation["bbox_cad"][key], abs=1e-4)
    bed = source_part.children[1]
    assert bed.label == "build_plate_assembly"
    expected_bed = expected.children[1]
    bed_bounds, expected_bed_bounds = _bbox_of(source_part.location * bed), _bbox_of(expected_bed)
    for key in ("min", "max"):
        assert bed_bounds[key] == pytest.approx(expected_bed_bounds[key], abs=1e-4)
    del result, source_part, bed
    gc.collect()
    subprocess.run([sys.executable, str(tmp_path / "cad/deck-model.py")], check=True, timeout=600)
    rebuilt = import_step(step)
    assert rebuilt.is_valid and len(rebuilt.solids()) == report["solid_count"]
    rebuilt_source = next(c for c in rebuilt.children if c.label == "foundation-jubilee")
    rebuilt_bed = rebuilt_source.children[1]
    assert rebuilt_bed.label == "build_plate_assembly"
    rebuilt_bed_bounds = _bbox_of(rebuilt_source.location * rebuilt_bed)
    for key in ("min", "max"):
        assert rebuilt_bed_bounds[key] == pytest.approx(expected_bed_bounds[key], abs=1e-4)
    (tmp_path / "cad/source/jubilee-original.step.gz").write_bytes(gzip.compress(b"wrong"))
    failed = subprocess.run(
        [sys.executable, str(tmp_path / "cad/deck-model.py")], capture_output=True, timeout=30
    )
    assert failed.returncode != 0 and b"hash mismatch" in failed.stderr
