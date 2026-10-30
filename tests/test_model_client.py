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
    assert payload["max_completion_tokens"] == 2400
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


@pytest.mark.parametrize(
    ("key", "source", "value"),
    [
        ("stock_concentration", "10mg/ml", "10 mg/mL"),
        ("final_volume", "0,5ml", "0.5 mL"),
        ("target_concentrations", "1, 2 and 3 mg/ml", "1 mg/mL, 2 mg/mL, 3 mg/mL"),
    ],
)
def test_equivalent_quantity_notation_keeps_literal_evidence(key, source, value):
    body = valid_response(**{key: value, f"source_{key}": source})
    result, _ = run_turn(lambda request: httpx.Response(200, json=body), message=source)
    assert result.patch()[key] == value


def test_brief_fields_are_grounded_in_literal_message():
    body = valid_response(
        brief_objective="move vials across the bench",
        source_brief_objective="move vials across the bench",
        brief_constraints="avoid shaking",
        source_brief_constraints="avoid shaking",
    )
    message = "I want to move vials across the bench and avoid shaking"
    result, _ = run_turn(lambda request: httpx.Response(200, json=body), message=message)
    assert result.patch()["brief_objective"] == "move vials across the bench"
    invented = valid_response(brief_objective="move vials", source_brief_objective="move vials")
    with pytest.raises(ModelClientError):
        run_turn(lambda request: httpx.Response(200, json=invented), message="Do something else")
    mismatched = valid_response(brief_process="transport vials", source_brief_process="other words")
    with pytest.raises(ModelClientError):
        run_turn(
            lambda request: httpx.Response(200, json=mismatched),
            message="We will transport vials daily",
        )


def test_workflow_kind_source_is_literal_but_classification_is_inference():
    body = valid_response(workflow_kind="general", source_workflow_kind="move vials between racks")
    result, _ = run_turn(
        lambda request: httpx.Response(200, json=body),
        message="Please help move vials between racks",
    )
    assert result.patch()["workflow_kind"] == "general"
    with pytest.raises(ModelClientError):
        run_turn(lambda request: httpx.Response(200, json=body), message="Unrelated request")
    bad_kind = valid_response(workflow_kind="robot", source_workflow_kind="robot work")
    with pytest.raises(ModelClientError):
        run_turn(lambda request: httpx.Response(200, json=bad_kind), message="robot work please")


def test_general_workflow_rejects_legacy_quantities():
    body = valid_response(
        workflow_kind="general",
        source_workflow_kind="move vials",
        stock_concentration="10 mM",
        source_stock_concentration="10 mM",
    )
    with pytest.raises(ModelClientError):
        run_turn(
            lambda request: httpx.Response(200, json=body),
            message="move vials with stock 10 mM",
        )


def test_general_context_hides_liquid_template_and_catalogue():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=valid_response())

    run_turn(handler, message="I want to move vials between racks")
    state_text = captured["body"]["messages"][1]["content"]
    assert "move vials between racks" not in state_text or "brief" in state_text
    state = json.loads(state_text.removeprefix("Current recorded project state: "))
    for key in ("summary", "catalogue", "current_plan", "current_footprint_mm"):
        assert key not in state
    references = state["reviewed_reference_library"]
    assert references["geometry_bindings"] == []
    assert references["architecture"] == "Workflow discovery; no accepted machine design"


def test_canonicalization_cannot_change_concentration_or_capitalized_prefix():
    body = valid_response(stock_concentration="1 mM", source_stock_concentration="1 M")
    with pytest.raises(ModelClientError):
        run_turn(lambda request: httpx.Response(200, json=body), message="Stock is 1 M")
    body = valid_response(stock_concentration="1 mM", source_stock_concentration="1 mM")
    with pytest.raises(ModelClientError):
        run_turn(lambda request: httpx.Response(200, json=body), message="Stock is 1 MM")
    body = valid_response(stock_concentration="1 M", source_stock_concentration="11 M")
    with pytest.raises(ModelClientError):
        run_turn(lambda request: httpx.Response(200, json=body), message="Stock is 11 M")


def test_generic_workflow_cannot_receive_liquid_parameters_without_routing():
    from app.domain import apply_update

    project = apply_update(
        new_project(),
        {
            "workflow_kind": "general",
            "brief_objective": "inspect vial labels",
        },
    )

    async def run():
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json=valid_response(final_volume="1 mL", source_final_volume="1 mL"),
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            return await generate_turn(
                project,
                "The inspected tubes contain 1 mL.",
                [],
                client=client,
                settings=TEST_SETTINGS,
            )

    with pytest.raises(ModelClientError, match="invalid response"):
        asyncio.run(run())
    assert project["summary"]["final_volume"] is None
    assert project["workflow"]["kind"] == "general"


def test_undecided_preparation_keeps_quantities_empty_while_assistant_guides():
    body = valid_response(assistant_message=(
        "What concentration range would you like to compare? We can choose the targets "
        "and final volume after that."
    ))
    turn, _ = run_turn(
        lambda request: httpx.Response(200, json=body),
        message="I prepare aliquots manually and have not chosen concentrations yet.",
    )
    assert turn.patch() == {}
    assert "range" in turn.assistant_message


def test_incomplete_response_reports_kind_and_usage_without_raw_output():
    body = {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 2400}}
    with pytest.raises(ModelClientError) as caught:
        run_turn(lambda request: httpx.Response(200, json=body))
    assert caught.value.failure_kind == "token_limit"
    assert caught.value.usage == {"prompt_tokens": 42, "completion_tokens": 2400}
    assert not hasattr(caught.value, "response")


@pytest.mark.parametrize(
    "selected,reply_choice,expect_success,stored_source",
    [
        ("jubilee", "jubilee", True, "I choose Jubilee"),
        ("jubilee", "opentrons-ot2", False, "I choose Jubilee"),
        (None, "jubilee", False, "I choose Jubilee"),
        ("jubilee", "jubilee", False, None),
    ],
)
def test_only_exact_recorded_selection_echo_is_inert(
    selected, reply_choice, expect_success, stored_source
):
    from app.engineering import EngineeringUpdate, apply_engineering_update

    project = new_project()
    prior_choice = "I choose Jubilee"
    if selected:
        project = apply_engineering_update(
            project,
            EngineeringUpdate(platform_choice=selected, choice_source=prior_choice),
            prior_choice,
        )
        project["engineering"]["selection_source"] = stored_source
    body = valid_response(
        assistant_message="Proposing the requested inspection extension.",
        actions=[{"kind": "add_inspection", "source": "add an inspection arm and camera"}],
        engineering={"platform_choice": reply_choice, "choice_source": stored_source},
    )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))
        ) as client:
            return await generate_turn(
                project,
                "Now add an inspection arm and camera",
                [],
                client=client,
                settings=TEST_SETTINGS,
            )

    if expect_success:
        turn, usage = asyncio.run(run())
        assert turn.engineering.platform_choice is None
        assert turn.engineering.choice_source is None
        assert turn.actions[0].kind == "add_inspection"
        assert usage["total_tokens"] == 62
    else:
        with pytest.raises(ModelClientError):
            asyncio.run(run())


@pytest.mark.parametrize("literal_value,expect_success", [
    ("making dilutions with a manual pipette", True),
    ("making automated dilutions with a manual pipette", False),
])
def test_undersized_brief_source_repairs_only_exact_current_literal(literal_value, expect_success):
    body = valid_response(brief_process=literal_value, source_brief_process="a manual pipette")
    def handler(request):
        return httpx.Response(200, json=body)
    message = "My process is making dilutions with a manual pipette"
    if expect_success:
        turn, _ = run_turn(handler, message=message)
        assert turn.brief_process == literal_value
        assert turn.source_brief_process == literal_value
    else:
        with pytest.raises(ModelClientError):
            run_turn(handler, message=message)


def test_brief_source_repair_does_not_use_historical_only_value():
    literal = "making dilutions with a manual pipette"
    body = valid_response(brief_process=literal, source_brief_process="a manual pipette")
    with pytest.raises(ModelClientError):
        run_turn(
            lambda request: httpx.Response(200, json=body),
            message="I still use a manual pipette", history=[{"role": "user", "content": literal}],
        )
