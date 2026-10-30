"""Semantic number/label binding, including previously failed recorded outputs.

Recorded examples are regression material, not independent held-out validation.
All model response replay below is offline and makes zero provider requests.
"""

import json
from copy import deepcopy
from itertools import groupby
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from test_foundation_storage import source_project
from test_model_client import TEST_SETTINGS

import app.api as api
from app.labware import LabwareUpdate
from app.model_client import ExtractedTurn, generate_turn

RECORDS = json.loads(
    (Path(__file__).parent / "fixtures" / "labware-recorded-round1.json").read_text(
        encoding="utf-8"
    )
)["records"]


def check(field, value, source):
    LabwareUpdate.model_validate({field: value, f"source_{field}": source}).verify_sources(source)


@pytest.mark.parametrize(
    "field,value,source",
    [
        (
            "body_diameter_max_mm",
            11.2,
            "body diameter 11.2 mm, rim diameter 14.4 mm, closed cap envelope 17 mm",
        ),
        (
            "rim_diameter_min_mm",
            14.4,
            "body diameter 11.2 mm, rim diameter 14.4 mm, closed cap envelope 17 mm",
        ),
        (
            "cap_diameter_max_mm",
            17,
            "body diameter 11.2 mm, rim diameter 14.4 mm, closed cap envelope 17 mm",
        ),
        (
            "body_diameter_max_mm",
            9,
            "body diameter 9 mm rim diameter 12 mm closed cap envelope 15 mm",
        ),
        (
            "cap_diameter_max_mm",
            15,
            "body diameter 9 mm rim diameter 12 mm closed cap envelope 15 mm",
        ),
        ("body_diameter_max_mm", 11, "11 mm body diameter and 14 mm rim diameter"),
        ("rim_diameter_min_mm", 14, "11 mm body diameter and 14 mm rim diameter"),
        ("cap_diameter_max_mm", 17, "ingombro del tappo chiuso, cerniera inclusa: 1,7 cm"),
        ("cap_diameter_max_mm", 17, "closed cap envelope including hinge and rim: 17 mm"),
        ("below_rim_height_mm", 36, "length beneath the supporting flange to the tube tip: 3.6 cm"),
        (
            "below_rim_height_mm",
            36,
            "distance from the underside of the supporting rim to the tube tip 36 mm",
        ),
        ("below_rim_height_mm", 36, "distanza sotto il bordo fino alla punta 36 mm"),
        ("radial_clearance_mm", 0.6, "0.6 mm radial clearance"),
        ("max_width_mm", 55, "maximum rack width 55 mm and closed cap envelope 17 mm"),
        ("max_depth_mm", 85, "maximum depth: 85 mm"),
        ("max_height_mm", 45, "rack height limit: 45 mm"),
        ("max_height_mm", 45, "altezza massima portaprovette 45 mm"),
        ("max_width_mm", 55, "rack width at most 55 mm"),
    ],
)
def test_novel_labelled_dimension_paraphrases_and_mixed_lists(field, value, source):
    check(field, value, source)


@pytest.mark.parametrize(
    "field,value,source",
    [
        ("body_diameter_max_mm", 14.4, "body diameter 11.2 mm, rim diameter 14.4 mm"),
        ("rim_diameter_min_mm", 11.2, "body diameter 11.2 mm, rim diameter 14.4 mm"),
        (
            "cap_diameter_max_mm",
            14.4,
            "body diameter 11.2 mm, rim diameter 14.4 mm, closed cap envelope 17 mm",
        ),
        ("body_diameter_max_mm", 11, "body diameter 11 mm or 12 mm"),
        ("body_diameter_max_mm", 11, "body diameter 11 mm; body diameter 12 mm"),
        ("body_diameter_max_mm", 14, "body and rim diameters 14 mm"),
        ("rim_diameter_min_mm", 36, "rim underside to tip 36 mm"),
        ("rim_diameter_min_mm", 36, "rim-to-tip height 36 mm"),
        ("cap_diameter_max_mm", 17, "cap height 17 mm"),
        ("body_diameter_max_mm", 11, "1.5 mL tubes, typical body diameter eleven"),
        ("max_height_mm", 36, "below-rim height 36 mm"),
        ("max_height_mm", 36, "maximum tube height 36 mm"),
        ("max_width_mm", 11, "maximum tube body width 11 mm"),
        ("max_depth_mm", 17, "cap maximum depth 17 mm"),
        ("max_width_mm", 55, "rack width 55 mm"),
        ("max_height_mm", 45, "rack height 45 mm"),
        ("max_width_mm", 17, "maximum rack width 55 mm and closed cap envelope 17 mm"),
        ("body_diameter_max_mm", 11, "minimum body diameter 11 mm"),
        ("rim_diameter_min_mm", 14, "maximum rim diameter 14 mm"),
        ("cap_diameter_max_mm", 17, "minimum closed cap envelope 17 mm"),
        ("max_height_mm", 45, "minimum rack height limit 45 mm"),
    ],
)
def test_swapped_ambiguous_missing_unit_and_tube_to_rack_bindings_rejected(field, value, source):
    with pytest.raises(ValueError):
        check(field, value, source)


@pytest.mark.parametrize(
    "field,value,source",
    [
        ("count", 9, "9 tubes in 3 columns"),
        ("columns", 3, "9 tubes in 3 columns"),
        ("count", 12, "12 posti in 4 colonne"),
        ("columns", 4, "12 posti in 4 colonne"),
        ("count", 10, "10 spaces, columns: 5"),
        ("columns", 5, "10 spaces, columns: 5"),
        ("count", 6, "6-position rack, 3 columns"),
        ("count", 6, "count: 6, columns: 3"),
    ],
)
def test_count_and_columns_bind_adjacent_integer_to_their_own_label(field, value, source):
    check(field, value, source)


@pytest.mark.parametrize(
    "field,value,source",
    [
        ("count", 3, "9 tubes in 3 columns"),
        ("columns", 9, "9 tubes in 3 columns"),
        ("count", 6, "6 mL tubes in 3 columns"),
        ("count", 3, "6 mL tubes in 3 columns"),
        ("count", 6, "count: 6 mL"),
        ("count", 6, "6 tubes or 8 tubes"),
        ("columns", 3, "3 columns or 4 columns"),
        ("columns", 3, "3 mL tubes"),
    ],
)
def test_counts_do_not_borrow_column_counts_volumes_or_ambiguous_alternatives(field, value, source):
    with pytest.raises(ValueError):
        check(field, value, source)


@pytest.mark.parametrize(
    "record",
    RECORDS,
    ids=[f"{record['case_id']}-turn-{record['turn_index']}" for record in RECORDS],
)
def test_previously_recorded_response_envelope_verifies_all_sources(record):
    turn = ExtractedTurn.model_validate(record["response"])
    turn.verify_sources(record["prompt"])
    turn.engineering.verify_sources(record["prompt"], source_project())


@pytest.mark.parametrize(
    "case_id,records",
    [(case_id, list(records)) for case_id, records in groupby(RECORDS, lambda row: row["case_id"])],
)
def test_recorded_outputs_replay_through_actual_model_and_api_pipeline_offline(
    case_id, records, monkeypatch
):
    project = source_project()
    original = deepcopy(project)
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    try:
        with TestClient(api.app) as client:
            for record in records:

                async def replay(current, message, history):
                    assert message == record["prompt"]
                    body = {
                        "choices": [
                            {
                                "finish_reason": "stop",
                                "message": {"content": json.dumps(record["response"])},
                            }
                        ],
                        "usage": {},
                    }
                    async with httpx.AsyncClient(
                        transport=httpx.MockTransport(
                            lambda request: httpx.Response(200, json=body)
                        )
                    ) as mock:
                        return await generate_turn(
                            current, message, history, client=mock, settings=TEST_SETTINGS
                        )

                monkeypatch.setattr(api, "generate_turn", replay)
                response = client.post(
                    f"/api/projects/{project['id']}/messages", json={"message": record["prompt"]}
                )
                assert response.status_code == 200
                payload = response.json()
                if case_id.startswith("S") and record == records[-1]:
                    assert payload["action_runs"][-1]["status"] == "accepted"
                    assert payload["project"]["labware_rack"]["spec"]
                elif case_id.startswith("S"):
                    assert payload["project"]["design"] == original["design"]
                    assert "labware_rack" not in payload["project"]
            if case_id == "N1_impossible_rim_support":
                assert payload["action_runs"][0]["status"] == "rejected"
                assert "Rim is too narrow" in payload["action_runs"][0]["message"]
                assert payload["project"] == original
            if case_id == "N2_unsupported_capacity":
                assert payload["action_runs"] == [] and payload["project"] == original
    finally:
        api._sessions.pop(project["id"], None)
