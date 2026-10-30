"""Request-only guidance for empty deltas; ungrounded provider records stay rejected."""

import asyncio
import json
from copy import deepcopy

import httpx
import pytest

from app.domain import new_project
from app.model_client import ModelClientError, ModelSettings, _strict_schema, generate_turn

SETTINGS = ModelSettings("synthetic", "https://example.invalid/v1", "muse-wonder-1.0")
QUESTION = "In one short sentence, remind me which platform is selected. Do not change the project."


def response(requirements):
    return {
        "model": SETTINGS.model,
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {
                            "assistant_message": "Jubilee is the selected platform.",
                            "actions": [],
                            "engineering": {
                                "requirements": requirements,
                                "options": [],
                                "platform_choice": None,
                                "choice_source": None,
                            },
                        }
                    )
                },
            }
        ],
        "usage": {"prompt_tokens": 8759, "completion_tokens": 418, "total_tokens": 9177},
    }


def test_request_explicitly_teaches_empty_arrays_without_weakening_schema():
    captured = {}

    def handler(request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=response([]))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await generate_turn(
                new_project(), QUESTION, [], client=client, settings=SETTINGS
            )

    result, usage = asyncio.run(run())
    assert result.patch() == {}
    assert result.engineering.requirements == []
    assert usage["model"] == SETTINGS.model
    assert captured["messages"][-1] == {"role": "user", "content": QUESTION}
    guidance = captured["messages"][-2]
    assert guidance["role"] == "developer"
    assert '"requirements":[]' in guidance["content"]
    assert "Never pad arrays" in guidance["content"]
    assert '"field":"budget"' in guidance["content"]
    schema = captured["response_format"]["json_schema"]
    assert schema["strict"] is True
    requirements = schema["schema"]["$defs"]["EngineeringUpdate"]["properties"]["requirements"]
    assert requirements["minItems"] == 0
    assert requirements["maxItems"] == 5
    assert "Return []" in requirements["description"]
    requirement = schema["schema"]["$defs"]["EngineeringRequirement"]
    assert requirement["additionalProperties"] is False
    assert requirement["properties"]["source"]["minLength"] == 1
    assert requirement["properties"]["value"]["minLength"] == 1


@pytest.mark.parametrize(
    "placeholder",
    ["\ufffd", "\u00ef\u00bf\u00bd"],
    ids=["replacement-character", "observed-mojibake"],
)
def test_observed_padded_placeholder_records_still_fail_closed(placeholder):
    # The real diagnostic contained five identical procurement records with this mojibake.
    records = [{"field": "procurement", "source": placeholder, "value": placeholder}] * 5
    project = new_project()
    before = deepcopy(project)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response(records))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await generate_turn(project, QUESTION, [], client=client, settings=SETTINGS)

    with pytest.raises(ModelClientError) as caught:
        asyncio.run(run())
    assert caught.value.failure_kind == "source_validation"
    assert caught.value.usage["model"] == SETTINGS.model
    assert project == before
    assert len(calls) == 1


def test_explicit_new_requirement_remains_extractable():
    requirements = [{"field": "budget", "value": "5000 EUR", "source": "5000 EUR"}]

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=response(requirements))
            )
        ) as client:
            return await generate_turn(
                new_project(), "Budget is 5000 EUR.", [], client=client, settings=SETTINGS
            )

    result, _ = asyncio.run(run())
    assert result.engineering.requirements[0].value == "5000 EUR"


def test_all_schema_arrays_keep_their_existing_bounds_and_explicit_empty_branch():
    arrays = []

    def visit(node):
        if isinstance(node, dict):
            if node.get("type") == "array":
                arrays.append(node)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(_strict_schema())
    assert arrays
    assert all(node["minItems"] == 0 for node in arrays)
    assert any(node.get("maxItems") == 5 for node in arrays)
    assert any(node.get("maxItems") == 2 for node in arrays)
