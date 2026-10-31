"""An explicit requested volume must not be erased by an equal old tube capacity."""

import pytest
from fastapi.testclient import TestClient
from test_microplates import before

import app.api as api
from app.microplates import PROFILE_ID, LabwareSelection
from app.model_client import ChatAction, ExtractedTurn

BASE = "Switch from Eppendorf 1.5 mL tubes to a 96-well plate"


def turn(message, source="1.5 mL", value="1.5 mL"):
    return ExtractedTurn(
        assistant_message="The application will check the selected profile and recipe.",
        final_volume=value,
        source_final_volume=source,
        labware_selection=LabwareSelection(profile_id=PROFILE_ID, source="96-well plate"),
        actions=[ChatAction(kind="select_labware", source="96-well plate")],
    )


@pytest.mark.parametrize(
    "volume_request",
    [
        "set the volume to 1.5 mL",
        "use 1.5 mL",
        "prepare 1.5 mL",
        "with a volume of 1.5 mL",
        "final volume 1.5 mL",
        "1.5 mL per well",
        "imposta il volume a 1,5 mL",
        "usa 1.5 mL",
        "prepara 1.5 mL",
        "con un volume di 1.5 mL",
        "volume finale 1.5 mL",
        "1.5 mL per pozzetto",
    ],
)
def test_equal_requested_volume_survives_old_capacity_and_rebinds_its_literal_source(
    volume_request,
):
    message = BASE + "; " + volume_request + "."
    result = turn(message)
    result.normalize_container_volume_scope(message)
    assert result.final_volume == "1.5 mL"
    assert result.source_final_volume == ("1,5 mL" if "1,5" in volume_request else "1.5 mL")
    result.verify_sources(message)


@pytest.mark.parametrize(
    "message",
    [
        BASE + ".",
        "Passa da eppendorf 1.5ml a 96-well plate.",
        "Use 1.5 mL Eppendorf tubes, then switch to a 96-well plate.",
        "Usa 1.5 mL provette, poi passa a una 96-well plate.",
        BASE + "; do not set the volume to 1.5 mL.",
        BASE + "; don't use 1.5 mL per well.",
        BASE + "; non impostare il volume a 1.5 mL per pozzetto.",
        BASE + "; later prepare 1.5 mL.",
        BASE + "; in futuro usa 1.5 mL.",
        "Switch to a 96-well plate; later prepare 1.5 mL.",
    ],
)
def test_nominal_capacity_and_negated_or_future_volume_are_not_current_recipe_changes(message):
    source = "1.5ml" if "1.5ml" in message else "1.5 mL"
    result = turn(message, source=source)
    result.normalize_container_volume_scope(message)
    assert result.final_volume is None and result.source_final_volume is None
    result.verify_sources(message)


def test_missing_or_nonliteral_citation_is_not_repaired_by_searching_for_a_number():
    message = BASE + "; set the volume to 1.5 mL."
    for source in (None, "from another conversation"):
        result = turn(message, source=source)
        result.normalize_container_volume_scope(message)
        with pytest.raises(ValueError):
            result.verify_sources(message)


def test_guard_does_not_invent_a_delta_when_model_returns_none():
    message = BASE + "; use 1.5 mL."
    result = turn(message, source=None, value=None)
    result.normalize_container_volume_scope(message)
    assert result.final_volume is None and result.source_final_volume is None


def test_guard_leaves_non_plate_operations_unchanged():
    result = ExtractedTurn(
        assistant_message="Recorded.", final_volume="1.5 mL", source_final_volume="1.5 mL"
    )
    result.normalize_container_volume_scope("Use 1.5 mL tubes")
    assert result.final_volume == "1.5 mL"


@pytest.mark.parametrize(
    "volume_request", ["set the volume to 1.5 mL", "imposta il volume a 1.5 mL"]
)
def test_one_message_api_exposes_real_1500_ul_conflict_instead_of_ready_200_ul(
    monkeypatch, volume_request
):
    project = before()
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    message = BASE + "; " + volume_request + "."

    async def model(current, user_message, history):
        return turn(message), {"total_tokens": 1}

    monkeypatch.setattr(api, "generate_turn", model)
    try:
        with TestClient(api.app) as client:
            response = client.post(
                f"/api/projects/{project['id']}/messages", json={"message": message}
            )
        assert response.status_code == 200
        body = response.json()
        assert body["project"]["plan"]["final_volume_ul"] == 1500
        assert body["project"]["labware_plate"]["compatibility"]["status"] == "volume_conflict"
        assert "1500 µL per well" in body["assistant_message"]
        assert "Confirmation and project-file generation are blocked" in body["assistant_message"]
    finally:
        api._sessions.pop(project["id"], None)
