"""Natural answers must stay scoped to the pending printer question."""

import json
from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient
from test_microplates import before
from test_model_client import TEST_SETTINGS, valid_response

import app.api as api
from app.model_client import generate_turn
from app.tip_racks import declared_printer, is_tip_only_turn, show_tip_options


@pytest.mark.parametrize(
    "message,expected",
    [
        ("Yes I do", "yes"),
        ("Yes, I do.", "yes"),
        ("I do", "yes"),
        ("Yes, we do", "yes"),
        ("Yes, I have access", "yes"),
        ("No I don't", "no"),
        ("No, I do not.", "no"),
        ("I don't", "no"),
    ],
)
def test_short_answer_requires_pending_question(message, expected):
    assert declared_printer(message) is None
    assert declared_printer(message, contextual=True) == expected


@pytest.mark.parametrize(
    "message",
    [
        "Yes if I buy one",
        "Yes, I will buy one later",
        "Do I need one?",
        "I could borrow one",
        "Yes, but not yet",
        "Yes I do not",
    ],
)
def test_conditional_or_ambiguous_answer_never_becomes_access(message):
    assert declared_printer(message, contextual=True) is None


def test_yes_i_do_roundtrip_records_only_printer_and_preserves_design(monkeypatch):
    project, _ = show_tip_options(before())
    original = deepcopy(project)
    captured = {}

    async def model(current, message, history):
        def handler(request):
            captured.update(json.loads(request.content))
            body = valid_response()
            body["choices"][0]["message"]["content"] = json.dumps(
                {
                    "assistant_message": "You can make a holder for purchased tips.",
                    "actions": [],
                    "tip_rack": {"printer_available": "yes", "printer_source": message},
                }
            )
            return httpx.Response(200, json=body)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await generate_turn(
                current, message, history, client=client, settings=TEST_SETTINGS
            )

    assert is_tip_only_turn(project, "Yes I do")
    monkeypatch.setattr(api, "generate_turn", model)
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    try:
        with TestClient(api.app) as client:
            response = client.post(
                f"/api/projects/{project['id']}/messages", json={"message": "Yes I do"}
            )
        assert response.status_code == 200, response.text
        result = response.json()["project"]
        assert result["fabrication_capabilities"]["printer_available"] == "yes"
        assert not result["tip_rack_request"].get("awaiting_printer")
        assert result["plan"] == original["plan"]
        assert result["design"] == original["design"]
        assert set(captured["response_format"]["json_schema"]["schema"]["properties"]) == {
            "assistant_message",
            "actions",
            "tip_rack",
        }
    finally:
        api._sessions.pop(project["id"], None)
