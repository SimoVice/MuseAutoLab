"""Tests for app.assembly (concept documents only)."""

from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

from app.assembly import assembly_steps, build_document_files
from app.domain import apply_update, confirm_project, new_project


def _confirmed(cooling: bool = False) -> dict:
    project = new_project()
    project = apply_update(
        project,
        {
            "stock_concentration": "10 mM",
            "target_concentrations": "1, 2 uM",
            "final_volume": "100 uL",
            "equipment": "Pipette concept",
            "workspace_width_mm": 600.0,
        },
    )
    if cooling:
        project = apply_update(project, {"cooling_enabled": True})
    return confirm_project(project)


def test_steps_shape_and_stable_ids():
    project = _confirmed()
    steps = assembly_steps(project)
    component_ids = {component["id"] for component in project["design"]["components"]}
    ids = [s["id"] for s in steps]
    assert ids[0] == "design-review" and ids[-1] == "checks"
    assert "cold-bay" not in ids
    for step in steps:
        assert {"id", "title", "component_ids", "instructions", "checks", "requires_design"} <= set(
            step
        )
        assert step["instructions"] and step["checks"]
        assert isinstance(step["requires_design"], bool)
        assert set(step["component_ids"]) <= component_ids


def test_conditional_cold_step():
    assert "cold-bay" in [s["id"] for s in assembly_steps(_confirmed(cooling=True))]


def test_revision_and_unknown_prices():
    project = _confirmed()
    files = build_document_files(project)
    payload = json.loads(files["assembly.json"].decode())
    assert payload["project_id"] == project["id"] and payload["revision"] == project["revision"]
    rows = list(csv.DictReader(io.StringIO(files["bill-of-materials.csv"].decode())))
    assert rows, "BOM must list selected options"
    custom = [r for r in rows if r["price_kind"] == "unpriced"]
    assert custom and all(r["unit_price"] == "" and r["line_total"] == "" for r in custom)
    assert "0" not in [r["unit_price"] for r in custom]


def test_escaping_and_preparation_and_preview_runs():
    project = _confirmed()
    evil = '<script>alert("x")</script>,=cmd'
    project["summary"]["equipment"] = evil
    project["design"]["components"][0]["label"] = evil
    files = build_document_files(project)
    guide = files["assembly-guide.html"].decode()
    assert "<script>" not in guide and "&lt;script&gt;" in guide
    prep = files["preparation.csv"].decode()
    assert prep.splitlines()[0] == "target,stock_volume_ul,diluent_volume_ul,total_volume_ul"
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "preview.py"
        target.write_bytes(files["automation/preview.py"])
        done = subprocess.run(
            [sys.executable, str(target)], capture_output=True, text=True, timeout=15
        )
    assert done.returncode == 0 and "logical" in done.stdout.lower()


def test_expected_file_set_and_extension_plan():
    files = build_document_files(_confirmed())
    assert set(files) == {
        "assembly-guide.html",
        "assembly.json",
        "bill-of-materials.csv",
        "preparation.csv",
        "automation/preview.py",
        "README.md",
        "extension-plan.json",
        "extensions.md",
    }
    plan = json.loads(files["extension-plan.json"].decode())
    assert plan["robot_arm"]["installed"] is False and plan["camera"]["installed"] is False
    assert (
        "TBD" in files["extensions.md"].decode()
        or "to be determined" in files["extensions.md"].decode().lower()
    )
    assert b"<svg" in files["assembly-guide.html"]
    assert all(isinstance(v, bytes) and v for v in files.values())
    assert "revision" in files["extension-plan.json"].decode()
    rows = list(csv.DictReader(io.StringIO(files["bill-of-materials.csv"].decode())))
    assert sum(Decimal(row["line_total"]) for row in rows if row["line_total"]) == Decimal("208.28")
