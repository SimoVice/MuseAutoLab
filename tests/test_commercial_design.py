"""Offline checks of the bounded OT-2 schematic, not hardware validation."""

import json
from copy import deepcopy

import pytest
from evolution_fixtures import layout_project

from app.commercial_design import (
    adopt_commercial,
    check_commercial_candidate,
    commercial_metadata,
    commercial_proposal_schema,
    compile_commercial_layout,
)


def proposal():
    return {
        "schema_version": "1",
        "slot_assignments": [
            {"component_id": "source-rack", "slot_id": "1"},
            {"component_id": "sample-rack", "slot_id": "5"},
            {"component_id": "tip-rack", "slot_id": "11"},
        ],
        "rationale": "Test assignment.",
        "assumptions": [],
    }


def test_fixed_envelope_and_sourced_slot_grid_without_upstream_cad():
    project = adopt_commercial(layout_project())
    before = deepcopy(project)
    result = compile_commercial_layout(project, proposal(), {"model": "offline"})
    assert project == before
    design = result["design"]
    assert design["platform"]["id"] == "opentrons-ot2"
    assert not design.get("foundation")
    assert design["footprint"] == {"width_mm": 630, "height_mm": 660, "depth_mm": 570}
    parts = {p["id"]: p for p in design["components"]}
    assert parts["source-rack"]["position"][::2] == [-132.5, -135.75]
    assert parts["sample-rack"]["position"][::2] == [0, -45.25]
    assert parts["tip-rack"]["position"][::2] == [0, 135.75]
    assert parts["tip-waste"]["slot_id"] == "12"
    assert parts["tip-waste"]["position"][::2] == [132.5, 135.75]
    assert all("geometry" in part for part in parts.values())
    assert result["engineering_design"]["proposal"] == proposal()
    assert result["revision"] == before["revision"] + 1
    assert commercial_metadata()["pipette_mounts"] == 2
    assert (
        commercial_metadata()["deck_definition_revision"]
        == "95a8a37922cfd5f46ad26c983bcc1659fa13b6e1"
    )
    assert commercial_metadata()["deck_definition_license"] == "Apache-2.0"
    assert commercial_proposal_schema()["additionalProperties"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["slot_assignments"][0].update(slot_id="12"),
        lambda p: p["slot_assignments"][0].update(slot_id=1),
        lambda p: p["slot_assignments"][1].update(slot_id="1"),
        lambda p: p["slot_assignments"][1].update(component_id="source-rack"),
        lambda p: p.update(deck_width_mm=400),
    ],
)
def test_invalid_proposals_rejected_without_change(mutation):
    project = adopt_commercial(layout_project())
    bad = proposal()
    mutation(bad)
    original = deepcopy(project)
    assert any(not check["passed"] for check in check_commercial_candidate(project, bad))
    with pytest.raises(ValueError):
        compile_commercial_layout(project, bad, {})
    assert project == original


def test_cooling_inspection_and_insufficient_width_are_rejected():
    project = adopt_commercial(layout_project(cooling=True))
    project["summary"]["workspace_width_mm"] = 629
    project["inspection_extension"] = {"component_ids": ["inspection-camera"]}
    failures = {c["id"] for c in check_commercial_candidate(project, proposal()) if not c["passed"]}
    assert {"cooling", "inspection", "workspace_width"} <= failures
    with pytest.raises(ValueError):
        compile_commercial_layout(project, proposal(), {})


def test_project_without_explicit_ot2_selection_is_rejected():
    checks = check_commercial_candidate(layout_project(), proposal())
    assert not next(c for c in checks if c["id"] == "platform")["passed"]


@pytest.mark.parametrize(
    "width, accepted", [(629, False), (630, False), (1029, False), (1030, True)]
)
def test_ventilation_width_is_included(width, accepted):
    project = layout_project()
    project["summary"]["workspace_width_mm"] = width
    project = adopt_commercial(project)
    check = next(
        c for c in check_commercial_candidate(project, proposal()) if c["id"] == "workspace_width"
    )
    assert check["passed"] is accepted
    assert (project["design"]["constraint_status"] == "fits") is accepted
    assert project["design"]["platform"]["minimum_operating_width_mm"] == 1030


@pytest.mark.parametrize("alter", ["deck", "provenance"])
def test_altered_deck_or_provenance_is_refused(tmp_path, monkeypatch, alter):
    from app import commercial_design

    deck = tmp_path / "deck.json"
    provenance = tmp_path / "provenance.json"
    deck.write_bytes(commercial_design.DECK_PATH.read_bytes())
    provenance.write_bytes(commercial_design.PROVENANCE_PATH.read_bytes())
    if alter == "deck":
        deck.write_bytes(deck.read_bytes() + b" ")
    else:
        data = json.loads(provenance.read_text(encoding="utf-8"))
        data["revision"] = "tampered"
        provenance.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(commercial_design, "DECK_PATH", deck)
    monkeypatch.setattr(commercial_design, "PROVENANCE_PATH", provenance)
    with pytest.raises(ValueError, match="does not match"):
        commercial_metadata()


def test_commercial_cad_export_roundtrip(tmp_path):
    from build123d import import_step

    from app.cad_exports import build_cad_files

    project = compile_commercial_layout(adopt_commercial(layout_project()), proposal(), {})
    files = build_cad_files(project)
    report = json.loads(files["cad/geometry-report.json"])
    path = tmp_path / "commercial.step"
    path.write_bytes(files["cad/workstation.step"])
    shape = import_step(path)
    assert shape.is_valid
    assert len(shape.solids()) == report["solid_count"]
    assert {child.label for child in shape.children} == {
        p["id"] for p in project["design"]["components"]
    }
    assert report["fabrication_ready"] is False
