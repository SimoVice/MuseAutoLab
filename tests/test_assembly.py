"""Tests for app.assembly (concept documents only)."""

from __future__ import annotations

import csv
import io
import json
import re
import subprocess
import sys
import tempfile
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree

import pytest

from app.assembly import assembly_steps, build_document_files, build_extensions_md
from app.domain import apply_update, confirm_project, new_project


@pytest.mark.parametrize("route", ["jubilee", "opentrons-ot2", "legacy"])
def test_extension_document_reports_only_the_route_simulation_scope(route):
    from app.commercial_design import adopt_commercial
    from app.foundation_design import adopt_foundation

    project = _confirmed()
    if route == "jubilee":
        project = adopt_foundation(project)
    elif route == "opentrons-ot2":
        project = adopt_commercial(project)
    # A small extension envelope isolates document routing from arm generation.
    project["inspection_extension"] = {"limitations": ["Physical validation remains open."]}
    document = build_extensions_md(project).decode()
    if route == "legacy":
        assert "legacy XYZ MuJoCo adapter covers nominal liquid preparation only" in document
        assert "inspection extension is excluded" in document
    else:
        assert "This platform has no simulation adapter" in document
        assert "Neither the workstation nor the inspection extension" in document
        assert "covers nominal liquid preparation" not in document
    if route == "opentrons-ot2":
        project.pop("inspection_extension")
        exported = build_document_files(project)["extensions.md"].decode()
        assert "This platform has no simulation adapter" in exported
        assert "no MuJoCo validation result is claimed" in exported


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


def test_guide_rounds_display_dimensions_without_mutating_canonical_geometry():
    project = _confirmed()
    project["design"]["components"][0]["position"] = [1.23456789, -0.000001, 89.999999]
    project["design"]["components"][0]["size"] = [483.1234567, 300, 12.5555]
    original = deepcopy(project)
    guide = build_document_files(project)["assembly-guide.html"].decode()
    assert "1.2, 0, 90" in guide and "483.1 × 300 × 12.6" in guide
    assert "1.23456789" not in guide and "483.1234567" not in guide
    assert "not a tolerance claim" in guide
    assert project == original


def test_extended_guide_legend_keeps_every_component_inside_svg_bounds():
    project = _confirmed(cooling=True)
    components = project["design"]["components"]
    while len(components) < 19:
        extra = deepcopy(components[-1])
        extra["id"] = f"inspection-review-{len(components)}"
        components.append(extra)
    guide = build_document_files(project)["assembly-guide.html"].decode()
    for svg_text in re.findall(r"<svg\b.*?</svg>", guide, flags=re.DOTALL):
        svg = ElementTree.fromstring(svg_text)
        width, height = [float(v) for v in svg.attrib["viewBox"].split()[2:]]
        legend = [node for node in svg.iter("text") if ". " in (node.text or "")]
        assert len(legend) == len(components)
        assert all(0 < float(node.attrib["x"]) < width for node in legend)
        assert all(0 < float(node.attrib["y"]) < height - 5 for node in legend)


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
    project = _confirmed()
    files = build_document_files(project)
    assert set(files) == {
        "assembly-guide.html",
        "assembly-guide.md",
        "assembly.json",
        "bill-of-materials.csv",
        "preparation.csv",
        "automation/preview.py",
        "README.md",
        "extension-plan.json",
        "extensions.md",
        "protocol-preview.py",
        "protocol-template.json",
    }
    protocol = json.loads(files["protocol-template.json"])
    assert protocol["execution_enabled"] is False
    assert protocol["binding"]["project_id"] == project["id"]
    assert protocol["binding"]["project_revision"] == project["revision"]
    assert protocol["binding"]["component_ids"] == [
        part["id"] for part in project["design"]["components"]
    ]
    assert protocol["current_preparation"]["target_count"] == len(project["plan"]["steps"])
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
