"""Post-action prose must agree with actual quantities, labware and action outcomes."""

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from test_microplates import MESSAGE, before, select
from test_model_client import TEST_SETTINGS

import app.api as api
from app.domain import apply_update
from app.microplates import PROFILE_ID, LabwareSelection
from app.model_client import ChatAction, ExtractedTurn, generate_turn

RECORDS = json.loads(
    (Path(__file__).parent / "fixtures" / "microplate-recorded-round1.json").read_text(
        encoding="utf-8"
    )
)["records"]


@pytest.fixture
def client():
    api._sessions.clear()
    with TestClient(api.app) as client:
        yield client
    api._sessions.clear()


def install(project):
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    return f"/api/projects/{project['id']}/messages"


@pytest.mark.parametrize("record", RECORDS, ids=[row["case_id"] for row in RECORDS])
def test_recorded_round1_prose_is_replaced_by_post_action_facts(client, monkeypatch, record):
    quantities = {
        key: record["baseline_summary"][key]
        for key in (
            "stock_concentration",
            "target_concentrations",
            "final_volume",
            "equipment",
        )
    }
    project = apply_update(before(), quantities)
    if record["baseline_plate"]:
        project = select(project)
    original = deepcopy(project)
    url = install(project)
    usage = record["usage"]

    async def replay(current, message, history):
        assert message == record["prompt"]
        body = {
            "choices": [
                {"finish_reason": "stop", "message": {"content": json.dumps(record["response"])}}
            ],
            "usage": usage,
        }
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))
        ) as mock:
            return await generate_turn(
                current, message, history, client=mock, settings=TEST_SETTINGS
            )

    monkeypatch.setattr(api, "generate_turn", replay)
    response = client.post(url, json={"message": record["prompt"]})
    assert response.status_code == 200
    body = response.json()
    text = body["assistant_message"]
    current = body["project"]
    assert body["usage"]["total_tokens"] == usage["total_tokens"]
    assert api._sessions[project["id"]].history[-1]["content"].startswith(text)
    if record["case_id"].startswith("N"):
        assert body["assistant_message_origin"] == "model"
        assert current == original
    else:
        assert body["assistant_message_origin"] == "canonical_labware_state"
        assert record["response"]["assistant_message"] not in text
        if record["case_id"] == "S5_restore_rack":
            assert "Restored the previous tube rack" in text
            assert "200 µL per tube" in text and "Calculated preparation per tube:" in text
            assert "Calculated preparation per well" not in text
        elif record["case_id"] == "S3_volume_conflict":
            assert "2000 µL per well" in text
            assert "Confirmation and project-file generation are blocked" in text
            assert current["plan"]["status"] == "invalid"
        else:
            assert "200 µL per well" in text
            assert "Assigned wells: A1, B1, C1 (3 of 96)" in text
            assert "Calculated preparation per well:" in text
            assert all(label + " — " in text for label in ("A1", "B1", "C1"))
            assert "per tube" not in text and "blocked" not in text
            assert "2 mL" not in text and "2000" not in text
            assert current["plan"]["status"] == "ready"


def fake_turn(monkeypatch, turn):
    async def model(project, message, history):
        return turn, {"total_tokens": 37}

    monkeypatch.setattr(api, "generate_turn", model)


def test_confident_pre_action_success_claim_cannot_claim_confirmed_or_running(client, monkeypatch):
    project = before()
    url = install(project)
    false_prose = "The project is already confirmed, exported and transferring liquids now."
    fake_turn(
        monkeypatch,
        ExtractedTurn(
            assistant_message=false_prose,
            labware_selection=LabwareSelection(profile_id=PROFILE_ID, source=MESSAGE),
            actions=[ChatAction(kind="select_labware", source=MESSAGE)],
        ),
    )
    body = client.post(url, json={"message": MESSAGE}).json()
    assert false_prose not in body["assistant_message"]
    assert "Review and confirm this draft" in body["assistant_message"]
    assert body["project"]["status"] == "draft" and body["usage"]["total_tokens"] == 37


def test_plate_volume_resolution_cannot_repeat_historical_blockage(client, monkeypatch):
    project = select(before(volume="2 mL"))
    url = install(project)
    false_prose = "Your old 2 mL preparation is still blocked and the volume did not change."
    fake_turn(
        monkeypatch,
        ExtractedTurn(
            assistant_message=false_prose,
            final_volume="200 uL",
            source_final_volume="200 uL",
        ),
    )
    body = client.post(url, json={"message": "Use 200 uL per well"}).json()
    text = body["assistant_message"]
    assert false_prose not in text and "200 µL per well" in text
    assert "blocked" not in text and "2 mL" not in text
    assert "Calculated preparation per well:" in text and "A1 — " in text
    assert body["project"]["plan"]["status"] == "ready"
    assert body["assistant_message_origin"] == "canonical_labware_state"


def test_new_plate_volume_conflict_cannot_repeat_false_ready_claim(client, monkeypatch):
    url = install(select(before()))
    false_prose = "No conflict exists; your plate is ready for immediate export."
    fake_turn(
        monkeypatch,
        ExtractedTurn(
            assistant_message=false_prose,
            final_volume="1 mL",
            source_final_volume="1 mL",
        ),
    )
    body = client.post(url, json={"message": "Set final volume to 1 mL per well"}).json()
    assert false_prose not in body["assistant_message"]
    assert "1000 µL per well" in body["assistant_message"]
    assert "Confirmation and project-file generation are blocked" in body["assistant_message"]
    assert body["project"]["plan"]["status"] == "invalid"


def test_failed_selection_preserves_truthful_current_state_instead_of_claimed_change(
    client, monkeypatch
):
    original = before()
    url = install(original)
    false_prose = "I changed the machine to the requested Bio-Rad PCR plate."
    message = "Use a Bio-Rad 96-well PCR plate"
    fake_turn(
        monkeypatch,
        ExtractedTurn(
            assistant_message=false_prose,
            labware_selection=LabwareSelection(profile_id=PROFILE_ID, source="96-well"),
            actions=[ChatAction(kind="select_labware", source=message)],
        ),
    )
    body = client.post(url, json={"message": message}).json()
    assert body["project"] == original
    assert body["action_runs"][0]["status"] == "rejected"
    assert false_prose not in body["assistant_message"]
    assert "requested change was not applied" in body["assistant_message"]
    assert "current tube setup was preserved" in body["assistant_message"]


def test_unrelated_plate_advice_remains_model_reply(client, monkeypatch):
    project = select(before())
    url = install(project)
    advice = "Review the proposed holder material against your cleaning process first."
    fake_turn(monkeypatch, ExtractedTurn(assistant_message=advice))
    body = client.post(url, json={"message": "How should I choose the holder material?"}).json()
    assert body["assistant_message"] == advice
    assert body["assistant_message_origin"] == "model"
    assert body["project"] == project
