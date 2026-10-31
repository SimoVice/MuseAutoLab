"""Derived reusable-platform guidance stays coherent with the current recipe."""

import json
from copy import deepcopy

from evolution_fixtures import layout_project
from test_commercial_design import proposal as ot2_proposal
from test_microplates import before, select

from app.commercial_design import adopt_commercial, compile_commercial_layout
from app.domain import apply_update, new_project
from app.instructions import build_instruction_files, build_instruction_guide
from app.protocol_preview import render_preview
from app.software_guidance import build_software_guidance


def test_template_is_derived_non_executable_and_includes_current_well_geometry():
    project = select(before())
    original = deepcopy(project)
    software = build_software_guidance(project)
    config = software["protocol_template"]
    assert project == original
    assert config["execution_enabled"] is False
    assert config["binding"]["project_revision"] == project["revision"]
    assert config["binding"]["plate_source_binding"] == project["labware_plate"]["profile_binding"]
    assert [well["label"] for well in config["binding"]["plate_wells"]] == ["A1", "B1"]
    assert len(config["current_preparation"]["transfers"]) == 2
    assert "not the platform's lifetime capacity" in software["current_preparation"]


def test_next_recipe_changes_schedule_while_preserving_platform_geometry():
    project = select(before())
    revised = apply_update(project, {"final_volume": "100 uL"})
    assert revised["design"]["components"] == project["design"]["components"]
    first = render_preview(build_software_guidance(project)["protocol_template"])
    second = render_preview(build_software_guidance(revised)["protocol_template"])
    assert "200 uL" in first and "100 uL" in second


def test_immediate_exports_include_guidance_and_exact_protocol_configuration():
    project = select(before())
    guide = build_instruction_guide(project)
    files = build_instruction_files(project)
    assert (
        json.loads(files["protocol-template.json"])
        == guide["software_guidance"]["protocol_template"]
    )
    assert json.loads(files["assembly.json"])["software_guidance"] == guide["software_guidance"]
    for name in ("assembly-guide.html", "assembly-guide.md"):
        text = files[name].decode("utf-8")
        assert "Software &amp; protocols" in text or "Software & protocols" in text
        assert "protocol-preview.py protocol-template.json" in text
        assert "not executable" in text


def test_no_selected_platform_has_planning_guidance_and_incomplete_template():
    software = build_software_guidance(new_project())
    assert software["status"] == "planning_only"
    assert software["protocol_template"]["status"] == "needs_recipe"


def test_routes_recommend_their_own_software_with_practical_authoring_steps():
    jubilee = build_software_guidance(select(before()))
    ot2_project = compile_commercial_layout(
        adopt_commercial(layout_project()), ot2_proposal(), {}
    )
    ot2 = build_software_guidance(ot2_project)
    assert "Science Jubilee" in jubilee["recommendations"][0]["title"]
    assert "Machine" in " ".join(jubilee["authoring_steps"])
    assert all("science-jubilee" in source["url"] for source in jubilee["sources"])
    assert all("pipette_guide" not in source["url"] for source in jubilee["sources"])
    assert "Opentrons" in ot2["recommendations"][0]["title"]
    assert "load names" in " ".join(ot2["authoring_steps"])
    assert all("docs.opentrons.com" in source["url"] for source in ot2["sources"])
    assert "JSON" in ot2["recommendations"][0]["description"]
