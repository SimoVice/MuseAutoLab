"""Accepted layout decisions and provenance must reach the actual CAD/documents."""

import json

import pytest
from build123d import import_step

from app.assembly import build_document_files
from app.cad_exports import build_cad_files
from app.design_spec import apply_candidate
from app.domain import apply_update, confirm_project, new_project


def test_continuous_layout_export_retains_actual_dimensions_and_decision(tmp_path):
    project = apply_update(new_project(), {
        "stock_concentration": "10 mM", "target_concentrations": "1 mM",
        "final_volume": "100 uL", "equipment": "pipette and tubes",
        "workspace_width_mm": 650,
    })
    proposal = {
        "schema_version": "1", "deck_width_mm": 623.5, "deck_depth_mm": 411.5,
        "placements": [
            {"component_id": "source-rack", "x_mm": -180, "z_mm": -50},
            {"component_id": "sample-rack", "x_mm": -65, "z_mm": -50},
            {"component_id": "tip-rack", "x_mm": 50, "z_mm": -50},
            {"component_id": "tip-waste", "x_mm": 165, "z_mm": 80},
            {"component_id": "controller", "x_mm": 165, "z_mm": -50},
        ],
        "rationale": "Synthetic accepted layout for export consistency.",
        "assumptions": ["Concept envelopes."],
    }
    accepted = confirm_project(apply_candidate(project, proposal, {"model": "offline-fixture"}))
    files = build_cad_files(accepted)
    report = json.loads(files["cad/geometry-report.json"])
    deck = next(c for c in report["components"] if c["id"] == "base")
    assert deck["bbox_cad"]["size"] == pytest.approx([623.5, 411.5, 20])
    target = tmp_path / "deck.step"
    target.write_bytes(files["cad/deck.step"])
    solid = import_step(target)
    assert solid.is_valid
    assert tuple(solid.bounding_box().size) == pytest.approx((623.5, 411.5, 20))
    assert accepted["engineering_design"]["proposal"] == proposal
    assert accepted["engineering_design"]["provenance"]["model"] == "offline-fixture"
    assert report["engineering_design"] == accepted["engineering_design"]
    documents = build_document_files(accepted)
    assert b"Meta layout provenance" in documents["README.md"]
    assert b"offline-fixture" in documents["assembly-guide.html"]
    assert b"Synthetic accepted layout" in documents["assembly-guide.html"]
