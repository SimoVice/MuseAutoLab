"""Cooling API and extraction checks."""

import json

import pytest
from fastapi.testclient import TestClient

import app.api as api
from app.model_client import ExtractedTurn


def _base_turn(**changes):
    value = {
        "assistant_message": "Noted.",
        "stock_concentration": None,
        "target_concentrations": None,
        "final_volume": None,
        "equipment": None,
        "workspace_width_mm": None,
        "source_stock_concentration": None,
        "source_target_concentrations": None,
        "source_final_volume": None,
        "source_equipment": None,
        "source_workspace_width_mm": None,
    }
    value.update(changes)
    return value


def test_cooling_defaults_preserve_old_payloads():
    turn = ExtractedTurn.model_validate(_base_turn())
    assert turn.cooling_enabled is None
    assert turn.cooling_target_c is None
    assert turn.source_cooling_enabled is None
    assert turn.source_cooling_target_c is None
    assert turn.patch() == {}


def test_schema_requires_all_properties():
    import asyncio

    import httpx

    from app.domain import new_project
    from app.model_client import (
        ModelSettings,
        generate_turn,  # noqa: F401
    )

    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        payload = _base_turn()
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(payload)}}],
                "usage": {},
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await generate_turn(
                new_project(),
                "Hello",
                [],
                client=client,
                settings=ModelSettings(
                    api_key="k", base_url="https://example.invalid/v1", model="m"
                ),
            )

    asyncio.run(run())
    schema = captured["body"]["response_format"]["json_schema"]["schema"]
    assert set(schema["required"]) == set(schema["properties"])
    assert "cooling_enabled" in schema["properties"]
    assert "cooling_target_c" in schema["properties"]


def test_cooling_source_requires_explicit_storage_terms():
    turn = ExtractedTurn.model_validate(
        _base_turn(cooling_enabled=True, source_cooling_enabled="keep reagents at 4 C")
    )
    with pytest.raises(ValueError):
        turn.verify_sources("Please keep reagents at 4 C")
    ok = ExtractedTurn.model_validate(
        _base_turn(
            cooling_enabled=True,
            source_cooling_enabled="add refrigerated cold-storage bay",
        )
    )
    ok.verify_sources("Please add refrigerated cold-storage bay")
    it = ExtractedTurn.model_validate(
        _base_turn(cooling_enabled=True, source_cooling_enabled="aggiungi frigo")
    )
    it.verify_sources("Per favore aggiungi frigo")


def test_cooling_target_requires_literal_temperature_and_range():
    with pytest.raises(Exception):
        ExtractedTurn.model_validate(
            _base_turn(cooling_target_c=30, source_cooling_target_c="30 C")
        )
    turn = ExtractedTurn.model_validate(
        _base_turn(cooling_target_c=4.0, source_cooling_target_c="4 C")
    )
    turn.verify_sources("Cooling target 4 C please")
    guessed = ExtractedTurn.model_validate(
        _base_turn(cooling_target_c=4.0, source_cooling_target_c="cold bay")
    )
    with pytest.raises(ValueError):
        guessed.verify_sources("Please add a cold bay")


@pytest.mark.parametrize("source", ["4C", "4°C", "4 Celsius", "4 degrees C", "4 C"])
def test_temperature_notation_accepts_compact_and_spaced_units(source):
    turn = ExtractedTurn.model_validate(
        _base_turn(cooling_target_c=4.0, source_cooling_target_c=source)
    )
    turn.verify_sources(f"Set the cold bay to {source}")


def test_length_unit_cannot_be_used_as_temperature():
    turn = ExtractedTurn.model_validate(
        _base_turn(cooling_target_c=4.0, source_cooling_target_c="4 cm")
    )
    with pytest.raises(ValueError):
        turn.verify_sources("Use 4 cm")


@pytest.fixture
def client():
    api._sessions.clear()
    with TestClient(api.app) as test_client:
        yield test_client
    api._sessions.clear()


def test_configuration_rejects_extra_and_bad_temperature(client):
    project = client.post("/api/projects").json()["project"]
    pid = project["id"]
    before = dict(api._sessions[pid].project)
    assert (
        client.post(f"/api/projects/{pid}/configuration", json={"unknown": True}).status_code == 422
    )
    assert (
        client.post(f"/api/projects/{pid}/configuration", json={"cooling_target_c": 30}).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/projects/{pid}/configuration", json={"cooling_target_c": "4"}
        ).status_code
        == 422
    )
    assert api._sessions[pid].project == before


def test_configuration_noop_preserves_revision(client):
    project = client.post("/api/projects").json()["project"]
    pid = project["id"]
    first = client.post(f"/api/projects/{pid}/configuration", json={}).json()
    assert first["project"]["revision"] == project["revision"]
    assert "$208.28" in first["assistant_message"]
    assert "Unpriced parts" in first["assistant_message"]


def test_configuration_uses_domain_and_reports_cost(client):
    pid = client.post("/api/projects").json()["project"]["id"]
    response = client.post(
        f"/api/projects/{pid}/configuration",
        json={"cooling_enabled": True, "cooling_target_c": 4},
    )
    assert response.status_code == 200
    body = response.json()
    assert "Target" in body["assistant_message"]
    assert "unverified" in body["assistant_message"]
