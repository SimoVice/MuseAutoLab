"""Tests for app.cad_exports (concept envelopes, parametric from snapshot)."""

from __future__ import annotations

import json


def _synthetic_project(width=400.0, depth=470.0, extra_depth=0.0):
    depth_total = depth + extra_depth
    base_z = extra_depth / 2.0
    components = [
        {
            "id": "base",
            "kind": "base",
            "label": "Custom deck",
            "position": [0, 10, base_z],
            "size": [width, 20, depth_total],
        },
        {
            "id": "pipette",
            "kind": "pipette",
            "label": "Pipette concept",
            "position": [0, 155, -100],
            "size": [28, 155, 28],
        },
        {
            "id": "source-rack",
            "kind": "rack",
            "label": "Source tube rack",
            "position": [-112, 42, -45],
            "size": [95, 44, 70],
        },
    ]
    if extra_depth:
        components.append(
            {
                "id": "cold-storage",
                "kind": "cooling",
                "label": "Refrigerated sample bay",
                "position": [0, 40, depth / 2.0 + extra_depth / 2.0],
                "size": [200, 40, 150],
            }
        )
    return {"id": "proj-test", "revision": 3, "design": {"components": components}}


def test_keys_and_report_provenance():
    from app.cad_exports import build_cad_files

    files = build_cad_files(_synthetic_project())
    assert set(
        ["cad/workstation.step", "cad/deck.step", "cad/deck.stl", "cad/geometry-report.json"]
    ) <= set(files)
    report = json.loads(files["cad/geometry-report.json"].decode())
    assert report["project_id"] == "proj-test" and report["revision"] == 3
    assert report["coordinate_mapping"].startswith("app(x,y,z)->CAD")
    assert report["units"] == "mm" and report["interfaces"] == []
    assert "concept only" in report["process"]
    assert report["source"]["build123d_version"] not in ("", "unknown")
    assert len(report["source"]["source_sha256"]) == 64
    assert {c["id"] for c in report["components"]} == {"base", "pipette", "source-rack"}
    assert all(
        c["valid"] and c["volume_mm3"] > 0 and c["solids"] == 1 for c in report["components"]
    )


def test_axis_mapping_bbox_volumes_and_nonempty():
    import pytest

    from app.cad_exports import build_cad_files

    files = build_cad_files(_synthetic_project())
    assert len(files["cad/workstation.step"]) > 1000
    assert len(files["cad/deck.step"]) > 500
    assert len(files["cad/deck.stl"]) > 500
    report = json.loads(files["cad/geometry-report.json"].decode())
    by_id = {c["id"]: c for c in report["components"]}
    # Box envelope: CAD size is (sx, sz, sy); bbox size must match exactly.
    rack = by_id["source-rack"]
    assert rack["cad_center"] == [-112, -45, 42]
    assert rack["cad_size"] == [95, 70, 44]
    assert rack["bbox_cad"]["size"] == pytest.approx([95, 70, 44])
    assert rack["volume_mm3"] == pytest.approx(95 * 44 * 70)
    # Pipette cylinder: axis along CAD Z, volume pi*r^2*h.
    import math

    pip = by_id["pipette"]
    assert pip["shape"] == "cylinder"
    assert pip["cad_center"] == [0, -100, 155]
    assert pip["volume_mm3"] == pytest.approx(math.pi * 14.0**2 * 155.0)
    # Deck bbox matches its envelope centred at mapped position.
    deck = by_id["base"]
    assert deck["bbox_cad"]["min"] == pytest.approx([-200.0, -235.0, 0.0])
    assert deck["bbox_cad"]["max"] == pytest.approx([200.0, 235.0, 20.0])


def test_compact_cold_deck_bounds_and_step_roundtrip(tmp_path):
    import pytest

    from app.cad_exports import build_cad_files

    compact = build_cad_files(_synthetic_project(width=400.0, depth=470.0))
    cold = build_cad_files(_synthetic_project(width=400.0, depth=470.0, extra_depth=260.0))
    rc = {c["id"]: c for c in json.loads(compact["cad/geometry-report.json"])["components"]}
    rh = {c["id"]: c for c in json.loads(cold["cad/geometry-report.json"])["components"]}
    # Cold variant extends the deck; width unchanged, depth grown parametrically.
    assert rh["base"]["bbox_cad"]["size"][0] == pytest.approx(400.0)
    assert rh["base"]["bbox_cad"]["size"][1] == pytest.approx(
        rc["base"]["bbox_cad"]["size"][1] + 260.0
    )
    assert "cold-storage" in rh and "cold-storage" not in rc
    # Validate exported STEP by reopening: solid count equals component count.
    from build123d import import_step

    for name in ("cad/workstation.step", "cad/deck.step"):
        path = tmp_path / name.replace("/", "_")
        path.write_bytes(cold[name])
        shape = import_step(str(path))
        assert shape.is_valid
        if name.endswith("workstation.step"):
            assert len(shape.solids()) == len(rh)
        else:
            assert len(shape.solids()) == 1


def test_domain_fixture():
    from app.cad_exports import build_cad_files
    from app.domain import apply_update, new_project

    project = apply_update(new_project(), {"workspace_width_mm": 450, "cooling_enabled": True})
    files = build_cad_files(project)
    report = json.loads(files["cad/geometry-report.json"].decode())
    assert report["project_id"] == project["id"]
    assert {c["id"] for c in report["components"]} == {
        c["id"] for c in project["design"]["components"]
    }
