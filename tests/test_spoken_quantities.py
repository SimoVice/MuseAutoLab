"""Strict English dictation quantities preserve literal sources and accepted geometry."""

import json
from copy import deepcopy

import httpx
import pytest
from evolution_fixtures import inspection_proposal
from fastapi.testclient import TestClient
from test_foundation_storage import source_project

import app.api as api
from app.dilution import create_dilution_plan
from app.domain import apply_update, confirm_project
from app.inspection import apply_extension
from app.model_client import DEFAULT_MODEL, ExtractedTurn
from app.quantities import normalize_concentration, normalize_targets, normalize_volume

TRANSCRIPT = (
    "UseUse a stock concentration of five milligrams per milliliter. Prepare targets of "
    "0.5, 0.25, and 0.05 milligrams per milliliter with two milliliters per tube."
)
TARGETS = "0.5, 0.25, and 0.05 milligrams per milliliter"


@pytest.mark.parametrize(
    "source,expected",
    [
        ("zero milliliters", "0 mL"),
        ("two milliliters", "2 mL"),
        ("Twenty-five microlitres", "25 uL"),
        ("nineteen microliters", "19 uL"),
        ("one hundred microliters", "100 uL"),
        ("two hundred fifty microliters", "250 uL"),
        ("nine hundred ninety-nine nanolitres", "999 nL"),
        ("zero point five milliliters", "0.5 mL"),
        ("zero point zero five millilitres per tube", "0.05 mL"),
        ("one point two five microliters", "1.25 uL"),
        ("2 milliliters in each tube", "2 mL"),
        ("two mL", "2 mL"),
    ],
)
def test_supported_spoken_volume_grammar(source, expected):
    assert normalize_volume(source) == expected
    assert normalize_volume(expected) == expected


@pytest.mark.parametrize(
    "source,expected",
    [
        ("five milligrams per milliliter", "5 mg/mL"),
        ("five milligram per millilitre", "5 mg/mL"),
        ("5 milligrams per mL", "5 mg/mL"),
        ("five mg per milliliters", "5 mg/mL"),
        ("twenty micrograms per millilitre", "20 ug/mL"),
        ("one gram per litre", "1 g/L"),
        ("five mM", "5 mM"),
    ],
)
def test_spelled_units_keep_only_supported_combinations(source, expected):
    assert normalize_concentration(source) == expected


def test_exact_live_transcript_quantities_calculate_correctly():
    assert normalize_targets(TARGETS) == "0.5 mg/mL, 0.25 mg/mL, 0.05 mg/mL"
    spoken_targets = (
        "zero point five, zero point two five and zero point zero five milligrams per milliliter"
    )
    assert normalize_targets(spoken_targets) == normalize_targets(TARGETS)
    plan = create_dilution_plan(
        "five milligrams per milliliter", TARGETS, "two milliliters per tube"
    )
    assert plan["status"] == "ready"
    assert plan["final_volume_ul"] == 2000
    assert [row["stock_volume_ul"] for row in plan["steps"]] == [200, 100, 20]
    assert [row["diluent_volume_ul"] for row in plan["steps"]] == [1800, 1900, 1980]


@pytest.mark.parametrize(
    "source",
    [
        "about two milliliters",
        "two to five milliliters",
        "two-five milliliters",
        "two milliliters per minute",
        "two milliliters/min",
        "two milliliters total for ten tubes",
        "two milliliters per batch",
        "two milliliters per tube and three elsewhere",
        "one half milliliter",
        "one thousand microliters",
        "one hundred and five microliters",
        "zero point twenty five milliliters",
        "one two milliliters",
        "zero hundred microliters",
        "twenty--five microliters",
        "two liters",
        "two micrometers",
        "milliliters",
    ],
)
def test_unsupported_or_ambiguous_speech_remains_rejected(source):
    with pytest.raises(ValueError):
        normalize_volume(source)


@pytest.mark.parametrize(
    "source",
    [
        "five milligrams per deciliter",
        "five milligrams per microliter",
        "five grams per milliliter",
        "five milligrams per milliliter per minute",
        "five or ten mg/mL",
        "five",
        "5 MG/mL",
    ],
)
def test_no_new_unit_or_missing_value_inference(source):
    with pytest.raises(ValueError):
        normalize_concentration(source)


def test_ambiguous_number_list_is_not_reinterpreted_as_two_targets():
    with pytest.raises(ValueError, match="ambiguous"):
        normalize_targets("one hundred and five mg/mL")
    assert normalize_targets("one hundred mg/mL and five mg/mL") == "100 mg/mL, 5 mg/mL"


def spoken_turn(*, volume="two milliliters", canonical=False):
    return ExtractedTurn(
        assistant_message="The supplied quantities are recorded for review.",
        stock_concentration="5 mg/mL" if canonical else "five milligrams per milliliter",
        source_stock_concentration="five milligrams per milliliter",
        target_concentrations="0.5 mg/mL, 0.25 mg/mL, 0.05 mg/mL" if canonical else TARGETS,
        source_target_concentrations=TARGETS,
        final_volume="2 mL" if canonical else volume,
        source_final_volume=volume + " per tube",
    )


@pytest.mark.parametrize("canonical", [False, True])
def test_source_equivalence_accepts_spoken_or_canonical_values_without_rewriting_sources(canonical):
    turn = spoken_turn(canonical=canonical)
    before = turn.model_dump()
    turn.verify_sources(TRANSCRIPT)
    assert turn.model_dump() == before


@pytest.mark.parametrize(
    "value,source",
    [
        ("50 mg/mL", "five milligrams per milliliter"),
        ("five milligrams per milliliter", "fifty milligrams per milliliter"),
        ("5 mg/mL", "five"),
    ],
)
def test_spoken_stock_source_cannot_supply_a_different_or_missing_quantity(value, source):
    turn = ExtractedTurn(
        assistant_message="Review.", stock_concentration=value, source_stock_concentration=source
    )
    with pytest.raises(ValueError):
        turn.verify_sources("Use " + source + ".")


@pytest.mark.parametrize(
    "source",
    [
        "two milliliters total for ten tubes",
        "two milliliters per minute",
        "two to five milliliters",
    ],
)
def test_spoken_volume_source_cannot_hide_ambiguous_context(source):
    for value in ("2 mL", "two milliliters"):
        turn = ExtractedTurn(
            assistant_message="Review.", final_volume=value, source_final_volume=source
        )
        with pytest.raises(ValueError):
            turn.verify_sources("Use " + source + ".")


def accepted_project():
    project = apply_update(
        source_project(130),
        {
            "stock_concentration": "5 mg/mL",
            "target_concentrations": "0.5 mg/mL, 0.25 mg/mL, 0.05 mg/mL",
            "final_volume": "2 mL",
        },
    )
    return confirm_project(apply_extension(project, inspection_proposal(), {}))


def test_equivalent_dictation_is_a_true_noop_on_confirmed_source_project():
    project = accepted_project()
    before = deepcopy(project)
    turn = spoken_turn()
    turn.verify_sources(TRANSCRIPT)
    result = apply_update(project, turn.patch())
    assert result == before
    assert result["status"] == "confirmed"
    assert result["design"]["foundation"]["bed_drop_mm"] == 130
    assert result["inspection_extension"] == before["inspection_extension"]


def test_effective_spoken_edit_still_requires_confirmation_and_keeps_geometry():
    project = accepted_project()
    before = deepcopy(project)
    turn = spoken_turn(volume="three milliliters")
    turn.verify_sources(TRANSCRIPT.replace("two milliliters", "three milliliters"))
    result = apply_update(project, turn.patch())
    assert result["revision"] == project["revision"] + 1
    assert result["status"] == "draft"
    assert result["summary"]["final_volume"] == "3 mL"
    assert result["plan"]["status"] == "ready"
    assert result["design"] == before["design"]
    assert result["engineering_design"] == before["engineering_design"]
    assert result["inspection_extension"] == before["inspection_extension"]
    assert project == before


def test_real_chat_boundary_keeps_equivalent_spoken_project_confirmed(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "synthetic-test-key")
    monkeypatch.setenv("META_MODEL", DEFAULT_MODEL)
    requests = []

    def handler(request):
        requests.append(request)
        payload = json.loads(request.content)
        assert payload["messages"][-1]["content"] == TRANSCRIPT
        return httpx.Response(
            200,
            json={
                "model": payload["model"],
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": spoken_turn().model_dump_json()},
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 30, "total_tokens": 50},
            },
        )

    client_type = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return client_type(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    api._sessions.clear()
    project = accepted_project()
    original = deepcopy(project)
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    with TestClient(api.app) as client:
        response = client.post(
            f"/api/projects/{project['id']}/messages", json={"message": TRANSCRIPT}
        )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["project"]["revision"] == original["revision"]
    assert result["project"]["status"] == "confirmed"
    assert result["project"]["summary"] == original["summary"]
    assert result["project"]["design"] == original["design"]
    assert result["project"]["inspection_extension"] == original["inspection_extension"]
    assert result["action_runs"] == []
    assert len(requests) == 1
    assert api._sessions[project["id"]].history[-2]["content"] == TRANSCRIPT
    api._sessions.clear()
