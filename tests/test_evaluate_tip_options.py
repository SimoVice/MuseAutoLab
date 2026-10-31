"""Offline evaluator bounds, audits and full-message adversarial sources."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from scripts import evaluate_tip_options as harness


@pytest.fixture
def dataset():
    path = harness.ROOT / "docs/examples/tip-options-evaluation-cases.json"
    return path, harness.load_dataset(path)


def test_declared_budget_and_dry_run_are_network_free(dataset, monkeypatch, capsys):
    path, data = dataset
    assert len(data["cases"]) == data["max_model_calls"] == harness.MAX_CALLS == 8
    monkeypatch.setattr(harness, "execute", lambda *a: pytest.fail("Dry run executed product"))
    assert harness.main(["--dataset", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["physical_provider_calls"] == 0


def test_provider_schema_guard_rejects_open_nested_dictionary_before_transport():
    harness.assert_closed_provider_schema(
        {"type": "object", "additionalProperties": False, "properties": {}}
    )
    with pytest.raises(ValueError, match="spec_sources"):
        harness.assert_closed_provider_schema(
            {
                "$defs": {
                    "TipRackUpdate": {
                        "properties": {
                            "spec_sources": {
                                "type": "object",
                                "additionalProperties": {"type": "string"},
                            }
                        }
                    }
                }
            }
        )


def test_both_real_provider_schemas_pass_guard_and_tip_schema_has_no_sample_selection():
    from app.model_client import TipRackTurn, _strict_schema

    harness.assert_closed_provider_schema(_strict_schema())
    focused = _strict_schema(TipRackTurn)
    harness.assert_closed_provider_schema(focused)
    assert set(focused["properties"]) == {"assistant_message", "actions", "tip_rack"}


def test_portable_request_defaults_are_semantically_equal_but_real_pending_change_is_not():
    before = {"alternatives_requested": True}
    restored = {
        **before,
        "awaiting_printer": False,
        "awaiting_placement": False,
        "spec": {},
        "spec_sources": {},
    }
    assert harness.normalized_tip_request(before) == harness.normalized_tip_request(restored)
    restored["awaiting_printer"] = True
    assert harness.normalized_tip_request(before) != harness.normalized_tip_request(restored)


def test_generic_printing_offer_is_not_a_specific_missing_dimension_request():
    with pytest.raises(AssertionError, match="Printed request not retained"):
        harness.audit_dimension_request(
            {"alternatives_requested": True},
            "a printed holder can be developed from your tip dimensions.",
        )
    harness.audit_dimension_request(
        {"profile_id": "custom_printed_tip_rack"},
        "provide maximum body diameter, minimum and maximum rim diameters, "
        "below-rim height, position count and columns.",
    )


@pytest.mark.parametrize("change", ["cap", "duplicate", "fixture", "clarification"])
def test_reject_unbounded_or_undeclared_cases(dataset, tmp_path, change):
    _, data = dataset
    if change == "cap":
        data["max_model_calls"] = 9
    elif change == "duplicate":
        data["cases"][1]["id"] = data["cases"][0]["id"]
    elif change == "fixture":
        data["cases"][0]["fixture"] = "unknown"
    else:
        data["cases"][0]["clarification"] = "Repair my prompt"
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        harness.load_dataset(path)


def test_fixtures_are_reopenable_and_audits_reject_unrelated_changes():
    from app.project_storage import restore_snapshot

    fixtures = harness.make_fixtures(
        harness.ROOT / "docs/examples/parametric-tube-rack-project.json"
    )
    assert set(fixtures) == harness.FIXTURES
    original = restore_snapshot(fixtures["original"])[0]
    selected = restore_snapshot(fixtures["selected_tipone"])[0]
    harness.audit_selected(
        original,
        selected,
        {"profile_id": "tipone_96_tiprack_200ul", "size_mm": [127.76, 63.9, 85.48]},
    )
    mutated = deepcopy(selected)
    mutated["plan"]["final_volume_ul"] += 1
    with pytest.raises(AssertionError, match="plan"):
        harness.audit_selected(original, mutated, {"profile_id": "tipone_96_tiprack_200ul"})


def test_provider_retries_blocked_before_send(dataset, tmp_path):
    path, data = dataset
    run = harness.Evaluation(path, data, tmp_path / "records", 8)
    run.case_id = data["cases"][0]["id"]
    sent = []

    async def fake_send(client, request, *args, **kwargs):
        sent.append(request)
        return httpx.Response(200, json={"usage": {}}, request=request)

    async def exercise():
        settings = SimpleNamespace(base_url="https://meta.invalid/v1")
        send = run.instrument(fake_send, settings)
        request = httpx.Request(
            "POST",
            settings.base_url + "/chat/completions",
            json={
                "model": harness.MODEL,
                "response_format": {
                    "json_schema": {
                        "schema": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {},
                        }
                    }
                },
            },
        )
        await send(None, request)
        with pytest.raises(harness.shared.EvaluationAbort, match="retry blocked"):
            await send(None, request)

    asyncio.run(exercise())
    assert len(sent) == len(run.calls) == 1


def test_actual_outbound_open_schema_is_blocked_before_any_provider_send(dataset, tmp_path):
    path, data = dataset
    run = harness.Evaluation(path, data, tmp_path / "blocked-schema", 8)

    async def forbidden_send(*args, **kwargs):
        pytest.fail("Invalid outbound schema reached the provider transport")

    async def exercise():
        settings = SimpleNamespace(base_url="https://meta.invalid/v1")
        request = httpx.Request(
            "POST",
            settings.base_url + "/chat/completions",
            json={
                "model": harness.MODEL,
                "response_format": {
                    "json_schema": {
                        "schema": {"type": "object", "additionalProperties": {"type": "string"}}
                    }
                },
            },
        )
        with pytest.raises(harness.shared.EvaluationAbort, match="open objects"):
            await run.instrument(forbidden_send, settings)(None, request)

    asyncio.run(exercise())
    assert not run.calls and run.abort_reason


@pytest.mark.parametrize(
    "message,source",
    [
        ("Do not use TipOne.", "TipOne"),
        ("Never select TipOne for this workstation.", "TipOne"),
        ("If I had TipOne, would it fit?", "TipOne"),
        ("Compare TipOne with Opentrons, keep the current rack.", "TipOne"),
        ("Use TipOne later; keep the current rack now.", "TipOne"),
        ("Non usare TipOne.", "TipOne"),
        ("Se avessi TipOne, sarebbe compatibile?", "TipOne"),
    ],
)
def test_positive_extracted_span_never_overrides_full_message(message, source):
    from app.tip_racks import TipRackUpdate

    with pytest.raises(ValueError):
        TipRackUpdate(profile_id="tipone_96_tiprack_200ul", source=source).verify_sources(message)


@pytest.mark.parametrize(
    "message",
    [
        "I do not have access to a 3D printer, but I have access to a 3D printer "
        "in a hypothetical example.",
        "If I have access to a 3D printer, could I print a holder?",
    ],
)
def test_positive_printer_span_does_not_override_negation_or_hypothesis(message):
    from app.tip_racks import TipRackUpdate

    source = "have access to a 3D printer"
    with pytest.raises(ValueError):
        TipRackUpdate(printer_available="yes", printer_source=source).verify_sources(message)
