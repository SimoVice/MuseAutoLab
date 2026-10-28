"""The inspection concept is validated geometrically but excluded from MuJoCo."""

import json
import subprocess
import sys
from copy import deepcopy

import pytest

from app.design_spec import apply_candidate
from app.domain import apply_update, confirm_project, new_project
from app.inspection import apply_extension
from app.physics import _validate, build_simulation_files, simulate_project


def extended_project():
    draft = apply_update(
        new_project(),
        {
            "stock_concentration": "10 mM",
            "target_concentrations": "1 mM, 2 mM",
            "final_volume": "100 uL",
            "equipment": "pipette and tubes",
        },
    )
    layout = {
        "schema_version": "1",
        "deck_width_mm": 600,
        "deck_depth_mm": 400,
        "placements": [
            {"component_id": "source-rack", "x_mm": -180, "z_mm": -50},
            {"component_id": "sample-rack", "x_mm": -65, "z_mm": -50},
            {"component_id": "tip-rack", "x_mm": 50, "z_mm": -50},
            {"component_id": "tip-waste", "x_mm": 165, "z_mm": 80},
            {"component_id": "controller", "x_mm": 165, "z_mm": -50},
        ],
        "rationale": "Concept layout",
        "assumptions": [],
    }
    draft = apply_candidate(draft, layout, {"model": "synthetic test"})
    proposal = {
        "schema_version": "1",
        "link_lengths_mm": [400, 400],
        "mast_height_mm": 450,
        "rationale": "Concept",
        "assumptions": [],
    }
    return confirm_project(apply_extension(draft, proposal, {"model": "synthetic test"}))


def test_extended_project_runs_workstation_only_and_replays_scope(tmp_path):
    project = extended_project()
    before = deepcopy(project)
    scope = _validate(project, "nominal")
    assert scope["components_with_details"] == len(project["design"]["components"])
    result = simulate_project(project)
    assert project == before
    assert result["status"] == "passed"
    assert result["scope"] == "liquid_preparation_only"
    assert result["inspection_extension_excluded"] is True
    assert any("Inspection arm and camera are excluded" in text for text in result["limitations"])
    assert "inspection-" not in result["model_xml"]
    files = build_simulation_files(project, result)
    assert b"liquid_preparation_only" in files["simulation/README.md"]
    assert b"liquid_preparation_only" in files["simulation/engine.py"]
    (tmp_path / "project.json").write_text(json.dumps({"project": project}), encoding="utf-8")
    for name, content in files.items():
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    run = subprocess.run(
        [sys.executable, str(tmp_path / "simulation/run.py")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, run.stderr
    replay = json.loads((tmp_path / "simulation/replay-result.json").read_text(encoding="utf-8"))
    assert replay["scope"] == result["scope"]
    assert replay["inspection_extension_excluded"] is True
    assert replay["metrics"] == result["metrics"]


@pytest.mark.parametrize("rotation", [float("nan"), float("inf"), True, "45"])
def test_rotation_must_be_finite_number(rotation):
    project = extended_project()
    link = next(p for p in project["design"]["components"] if p["id"] == "inspection-upper-link")
    link["geometry"]["primitives"][0]["rotation_y_deg"] = rotation
    with pytest.raises(ValueError, match="rotation_y_deg"):
        _validate(project, "nominal")


def test_rotated_beam_outside_envelope_is_rejected():
    project = extended_project()
    link = next(p for p in project["design"]["components"] if p["id"] == "inspection-upper-link")
    link["geometry"]["primitives"][0]["rotation_y_deg"] = 90
    with pytest.raises(ValueError, match="outside the component envelope"):
        _validate(project, "nominal")
