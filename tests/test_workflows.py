"""Domain tests for the general laboratory automation platform."""

from copy import deepcopy

import pytest

from app.domain import apply_update, confirm_project, new_project
from app.workflows import describe_workflow, new_brief


def test_blank_project_is_unclassified_discovery():
    project = new_project()
    assert project["brief"] == {
        "objective": None,
        "process": None,
        "materials": None,
        "equipment": None,
        "constraints": None,
    }
    assert project["workflow"] == describe_workflow(project)
    workflow = describe_workflow(project)
    assert workflow == {
        "kind": "unclassified",
        "label": "Unclassified",
        "status": "discovery",
        "design_available": False,
        "parameters_started": False,
    }


def test_general_patch_stays_generic_without_summary_intrusion():
    project = new_project()
    before_summary = deepcopy(project["summary"])
    updated = apply_update(
        project,
        {"workflow_kind": "general", "brief_objective": "Label tubes neatly"},
    )
    assert updated["workflow"]["kind"] == "general"
    assert updated["brief"]["objective"] == "Label tubes neatly"
    # Generic keys stored under brief without prefix, never under summary.
    assert "brief_objective" not in updated["summary"]
    assert "brief_objective" not in updated["brief"]
    assert updated["summary"]["stock_concentration"] is None
    assert before_summary == project["summary"]
    workflow = describe_workflow(updated)
    assert workflow["kind"] == "general"
    assert workflow["status"] == "planning"
    assert workflow["design_available"] is False
    assert workflow["parameters_started"] is False


def test_labelling_with_microscope_equipment_and_width_not_liquid():
    project = new_project()
    updated = apply_update(
        project,
        {
            "workflow_kind": "general",
            "brief_process": "labelling",
            "brief_equipment": "microscope",
            "workspace_width_mm": 450,
        },
    )
    workflow = describe_workflow(updated)
    assert workflow["kind"] == "general"
    assert workflow["design_available"] is False
    assert updated["brief"]["equipment"] == "microscope"
    # Equipment/width alone must not select the liquid adapter or leak into
    # liquid summary quantities.
    assert updated["summary"]["stock_concentration"] is None
    assert updated["summary"]["target_concentrations"] is None
    assert updated["summary"]["final_volume"] is None


def test_quantitative_legacy_patch_selects_liquid():
    project = new_project()
    updated = apply_update(project, {"stock_concentration": "10 mM"})
    assert updated["workflow"]["kind"] == "liquid_preparation"
    workflow = describe_workflow(updated)
    assert workflow["design_available"] is True
    assert workflow["parameters_started"] is True
    assert workflow["status"] == "supported_concept"


def test_explicit_general_with_quantities_stays_generic():
    project = new_project()
    updated = apply_update(
        project,
        {"workflow_kind": "general", "stock_concentration": "10 mM"},
    )
    assert updated["workflow"]["kind"] == "general"
    assert describe_workflow(updated)["design_available"] is False


def test_liquid_to_general_clears_scoped_fields():
    project = apply_update(
        new_project(),
        {
            "stock_concentration": "10 mM",
            "target_concentrations": "1 mM",
            "final_volume": "1 mL",
            "equipment": "pipette",
            "brief_constraints": "keep sterile",
        },
    )
    assert project["workflow"]["kind"] == "liquid_preparation"
    switched = apply_update(project, {"workflow_kind": "general"})
    assert switched["workflow"]["kind"] == "general"
    assert switched["summary"]["stock_concentration"] is None
    assert switched["summary"]["target_concentrations"] is None
    assert switched["summary"]["final_volume"] is None
    assert switched["summary"]["equipment"] is None
    assert switched["plan"]["status"] == "incomplete"
    # Generic brief and constraints are preserved.
    assert switched["brief"]["constraints"] == "keep sterile"
    assert switched["revision"] == project["revision"] + 1


def test_brief_equipment_mirror_only_in_liquid():
    generic = apply_update(
        new_project(), {"workflow_kind": "general", "brief_equipment": "microscope"}
    )
    assert generic["brief"]["equipment"] == "microscope"
    assert generic["summary"]["equipment"] is None
    liquid = apply_update(
        new_project(), {"workflow_kind": "liquid_preparation", "equipment": "pipette"}
    )
    assert liquid["workflow"]["kind"] == "liquid_preparation"
    assert liquid["brief"]["equipment"] == "pipette"
    assert liquid["summary"]["equipment"] == "pipette"


def test_confirm_guards():
    generic = apply_update(
        new_project(), {"workflow_kind": "general", "brief_objective": "inspect plates"}
    )
    with pytest.raises(ValueError, match="supported workflow"):
        confirm_project(generic)
    # Liquid confirm retains old gates.
    liquid = apply_update(new_project(), {"stock_concentration": "10 mM"})
    with pytest.raises(ValueError, match="Required parameters are missing"):
        confirm_project(liquid)


def test_noop_preserves_revision_and_inputs():
    project = apply_update(
        new_project(), {"workflow_kind": "general", "brief_objective": "transport racks"}
    )
    before = deepcopy(project)
    patch = {"brief_objective": "transport racks", "workflow_kind": "general"}
    patch_copy = deepcopy(patch)
    again = apply_update(project, patch)
    assert again == before
    assert again["revision"] == before["revision"]
    assert patch == patch_copy
    assert project == before


def test_single_increment_for_combined_patch():
    project = new_project()
    updated = apply_update(
        project,
        {"brief_objective": "prepare dilutions", "stock_concentration": "10 mM"},
    )
    assert updated["revision"] == project["revision"] + 1
    assert updated["workflow"]["kind"] == "liquid_preparation"


def test_new_brief_and_describe_purity():
    assert new_brief() == {
        "objective": None,
        "process": None,
        "materials": None,
        "equipment": None,
        "constraints": None,
    }
    project = new_project()
    before = deepcopy(project)
    describe_workflow(project)
    assert project == before
    # Null clears at the domain boundary.
    filled = apply_update(project, {"brief_objective": "automate labelling"})
    cleared = apply_update(filled, {"brief_objective": None})
    assert cleared["brief"]["objective"] is None
    assert cleared["revision"] == filled["revision"] + 1


def test_public_workflow_metadata_matches_routing():
    blank = new_project()
    assert blank["workflow"] == describe_workflow(blank)
    assert blank["workflow"]["design_available"] is False
    liquid = apply_update(blank, {"workflow_kind": "liquid_preparation"})
    assert liquid["workflow"] == describe_workflow(liquid)
    assert liquid["workflow"]["design_available"] is True
    assert liquid["workflow"]["parameters_started"] is False
    liquid = apply_update(liquid, {"final_volume": "1 mL"})
    assert liquid["workflow"]["parameters_started"] is True
    generic = apply_update(liquid, {"workflow_kind": "general"})
    assert generic["workflow"] == describe_workflow(generic)
    assert not generic["workflow"]["design_available"]
    assert not generic["workflow"]["parameters_started"]


def test_non_liquid_volume_can_be_recorded_as_general_context():
    project = apply_update(
        new_project(),
        {
            "workflow_kind": "general",
            "brief_objective": "inspect labels",
            "brief_materials": "tubes containing 1 mL samples",
        },
    )
    assert project["brief"]["materials"] == "tubes containing 1 mL samples"
    assert project["summary"]["final_volume"] is None
    assert project["workflow"]["design_available"] is False


def test_incomplete_liquid_workflow_still_requires_its_parameters():
    project = apply_update(new_project(), {"workflow_kind": "liquid_preparation"})
    with pytest.raises(ValueError, match="Required parameters are missing"):
        confirm_project(project)


def test_grounded_width_is_kept_in_generic_brief_without_machine():
    project = apply_update(
        new_project(),
        {
            "workflow_kind": "general",
            "brief_objective": "inspect labels",
            "workspace_width_mm": 450,
        },
    )
    assert project["brief"]["constraints"] == "Available width: 450 mm"
    assert not project["workflow"]["design_available"]
    revised = apply_update(project, {"workspace_width_mm": 400})
    assert revised["brief"]["constraints"] == "Available width: 400 mm"
    assert revised["revision"] == project["revision"] + 1
