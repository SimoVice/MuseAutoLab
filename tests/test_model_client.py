"""Model integration tests use an in-memory HTTP transport and no credentials."""

import asyncio
import json

import httpx
import pytest

from app.domain import new_project
from app.model_client import ModelClientError, ModelSettings, generate_turn

TEST_SETTINGS = ModelSettings(
    api_key="test-only-key",
    base_url="https://example.invalid/v1",
    model="muse-spark-1.3-contributor",
)


def valid_response(**updates):
    result = {
        "assistant_message": "Which pipette are you using?",
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
    result.update(updates)
    return {
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}],
        "usage": {"prompt_tokens": 27, "completion_tokens": 35, "total_tokens": 62},
    }


def run_turn(handler, message="My workspace is 40 cm wide", history=None):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await generate_turn(
                new_project(), message, history or [], client=client, settings=TEST_SETTINGS
            )

    return asyncio.run(run())


def test_request_uses_meta_schema_budget_and_preserves_zero_cost_usage():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json=valid_response(workspace_width_mm=400, source_workspace_width_mm="40 cm")
        )

    history = [{"role": "user", "content": str(index)} for index in range(10)]
    result, usage = run_turn(handler, history=history)
    payload = captured["body"]
    assert captured["url"] == "https://example.invalid/v1/chat/completions"
    assert captured["authorization"] == "Bearer test-only-key"
    assert payload["model"] == "muse-spark-1.3-contributor"
    assert payload["reasoning_effort"] == "minimal"
    assert payload["max_completion_tokens"] == 900
    assert len(payload["messages"]) == 11  # Two instructions, eight history entries, current input.
    schema = payload["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert set(schema["schema"]["required"]) == set(schema["schema"]["properties"])
    assert result.patch() == {"workspace_width_mm": 400.0}
    assert usage == {"prompt_tokens": 27, "completion_tokens": 35, "total_tokens": 62}


@pytest.mark.parametrize(
    "body",
    [
        {"choices": []},
        {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
        {"choices": [{"message": {"content": "not JSON"}}]},
        valid_response(workspace_width_mm=-1),
        valid_response(workspace_width_mm="400"),
        valid_response(workspace_width_mm=True),
        valid_response(equipment=""),
        valid_response(unexpected="field"),
    ],
)
def test_incomplete_or_invalid_model_output_is_rejected(body):
    with pytest.raises(ModelClientError, match="invalid response"):
        run_turn(lambda request: httpx.Response(200, json=body))


def test_provider_failure_is_sanitized():
    with pytest.raises(ModelClientError) as error:
        run_turn(lambda request: httpx.Response(429, text="test-only-key private provider detail"))
    assert "HTTP 429" in str(error.value)
    assert "test-only-key" not in str(error.value)
    assert "private provider detail" not in str(error.value)


def test_network_failure_is_reported_without_secret():
    def handler(request):
        raise httpx.ConnectError("test-only-key", request=request)

    with pytest.raises(ModelClientError) as error:
        run_turn(handler)
    assert "network" in str(error.value).lower()
    assert "test-only-key" not in str(error.value)


@pytest.mark.parametrize(
    ("message", "source", "width"),
    [
        ("Please fit 45 cm width", "45 cm", 450),
        ("The width is 0.45 m", "0.45 m", 450),
        ("Maximum width is 450 mm", "450 mm", 450),
        ("Larghezza massima 45 centimetri", "45 centimetri", 450),
        ("Larghezza massima 1 metro", "1 metro", 1000),
    ],
)
def test_workspace_units_are_checked_against_literal_message(message, source, width):
    reply = valid_response(workspace_width_mm=width, source_workspace_width_mm=source)
    result, _ = run_turn(lambda request: httpx.Response(200, json=reply), message=message)
    assert result.workspace_width_mm == width


def test_unsupported_previous_values_and_wrong_unit_conversion_are_rejected():
    invented = valid_response(stock_concentration="10 mM", source_stock_concentration="10 mM")
    with pytest.raises(ModelClientError):
        run_turn(lambda request: httpx.Response(200, json=invented), message="Use a smaller layout")
    wrong_conversion = valid_response(workspace_width_mm=40, source_workspace_width_mm="40 cm")
    with pytest.raises(ModelClientError):
        run_turn(lambda request: httpx.Response(200, json=wrong_conversion))
