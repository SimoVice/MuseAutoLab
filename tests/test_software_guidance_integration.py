"""Offline end-to-end invariants for reusable hardware and derived recipe software."""

from copy import deepcopy

import httpx
from fastapi.testclient import TestClient
from test_microplates import before, select
from test_model_client import TEST_SETTINGS, valid_response
from test_tip_racks import OPENTRONS, selected

import app.api as api
from app.domain import apply_update
from app.model_client import generate_turn
from app.project_storage import make_snapshot, restore_snapshot
from app.software_guidance import build_software_guidance


def platform_project():
    return selected(select(before()), OPENTRONS)


def template(project):
    return build_software_guidance(project)["protocol_template"]


def assert_current_recipe(project, config):
    assert config["binding"]["project_id"] == project["id"]
    assert config["binding"]["project_revision"] == project["revision"]
    assert config["binding"]["plate_profile_id"] == project["labware_plate"]["profile_id"]
    assert config["binding"]["tip_rack_profile_id"] == OPENTRONS
    assert config["current_preparation"]["workflow_kind"] == "liquid_preparation"
    expected = [
        {
            "target": step["target"],
            "destination_component_id": "sample-rack",
            "destination_well": step["well_name"],
            **{
                key: step[key]
                for key in ("stock_volume_ul", "diluent_volume_ul", "total_volume_ul")
            },
        }
        for step in project["plan"]["steps"]
    ]
    assert config["current_preparation"]["transfers"] == expected
    assert config["execution_enabled"] is False


def test_second_recipe_updates_current_protocol_without_rebuilding_machine_or_suppliers():
    original = platform_project()
    baseline = deepcopy(original)
    changed = apply_update(
        original, {"target_concentrations": "0.25 mg/mL, 0.1 mg/mL", "final_volume": "250 uL"}
    )
    assert changed["plan"] != original["plan"]
    for key in ("design", "engineering_design", "selections", "tip_rack"):
        assert changed[key] == original[key], key
    assert {g["id"]: g for g in changed["sourcing"]["groups"]} == {
        g["id"]: g for g in original["sourcing"]["groups"]
    }
    assert (
        changed["labware_plate"]["profile_binding"] == original["labware_plate"]["profile_binding"]
    )
    assert_current_recipe(changed, template(changed))
    assert template(changed)["current_preparation"] != template(original)["current_preparation"]
    assert original == baseline


def test_save_open_rederives_current_template_with_new_runtime_identity():
    original = apply_update(platform_project(), {"final_volume": "250 uL"})
    saved = make_snapshot(original, [{"role": "user", "content": "Keep this platform."}])
    assert "software_guidance" not in saved and "protocol_template" not in saved
    restored, history = restore_snapshot(saved)
    assert history[0]["content"] == "Keep this platform."
    assert restored["id"] != original["id"]
    assert restored["design"] == original["design"]
    assert_current_recipe(restored, template(restored))
    assert template(restored)["current_preparation"] == template(original)["current_preparation"]


def install_transport(monkeypatch, body):
    async def offline_turn(project, message, history):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
        async with httpx.AsyncClient(transport=transport) as client:
            return await generate_turn(
                project, message, history, client=client, settings=TEST_SETTINGS
            )

    monkeypatch.setattr(api, "generate_turn", offline_turn)


def test_software_inquiry_through_real_extraction_and_api_preserves_current_project(monkeypatch):
    project = platform_project()
    baseline = deepcopy(project)
    message = (
        "How do I program this reusable pipetting platform for another recipe? "
        "Show the software guide."
    )
    install_transport(
        monkeypatch,
        valid_response(
            assistant_message="Review the software guide for your current platform and recipe.",
            actions=[{"kind": "show_build_plan", "source": message}],
        ),
    )
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    try:
        with TestClient(api.app) as client:
            response = client.post(
                f"/api/projects/{project['id']}/messages", json={"message": message}
            )
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["action_runs"][0]["status"] == "ready"
            updated = result["project"]
            for key in (
                "revision",
                "status",
                "summary",
                "plan",
                "design",
                "engineering_design",
                "selections",
                "sourcing",
                "tip_rack",
                "labware_plate",
            ):
                assert updated[key] == baseline[key], key
            assert_current_recipe(updated, template(updated))
    finally:
        api._sessions.pop(project["id"], None)


def test_invented_recipe_change_is_rejected_at_real_model_boundary_without_state_loss(monkeypatch):
    project = platform_project()
    baseline = deepcopy(project)
    history = [{"role": "user", "content": "Keep this hardware."}]
    session = api.ProjectSession(project=project, history=deepcopy(history))
    api._sessions[project["id"]] = session
    message = "Explain how I can program this platform."
    install_transport(
        monkeypatch,
        valid_response(
            assistant_message="Here is the software guide.",
            target_concentrations="9 mg/mL",
            source_target_concentrations="9 mg/mL",
            actions=[{"kind": "show_build_plan", "source": message}],
        ),
    )
    try:
        with TestClient(api.app) as client:
            response = client.post(
                f"/api/projects/{project['id']}/messages", json={"message": message}
            )
        assert response.status_code == 502, response.text
        assert "not changed" in response.json()["detail"]
        assert session.project == baseline
        assert session.history == history
    finally:
        api._sessions.pop(project["id"], None)
