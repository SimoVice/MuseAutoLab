"""Offline harness safety and invariant audits; no frozen prompt rehearsals/Meta."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from scripts import evaluate_microplates as harness


@pytest.fixture
def dataset():
    path = harness.ROOT / "docs/examples/microplate-evaluation-cases.json"
    return path, harness.load_dataset(path)


@pytest.fixture
def fixtures():
    return harness.make_fixtures(harness.ROOT / "docs/examples/parametric-tube-rack-project.json")


def restore(value):
    from app.project_storage import restore_snapshot

    return restore_snapshot(value)[0]


def selected_fixture(fixtures, name="rack_200ul"):
    from app.microplates import PROFILE_ID, LabwareSelection, select_plate

    before = restore(fixtures[name])
    literal = "Select a 96-well plate for an offline audit fixture."
    after, _ = select_plate(
        before, LabwareSelection(profile_id=PROFILE_ID, source=literal), literal
    )
    return before, after


def test_exact_predeclared_cases_and_hard_cap(dataset):
    _, data = dataset
    assert len(data["cases"]) == 8
    assert data["max_model_calls"] == harness.MAX_CALLS == 8
    assert data["cases"][0]["prompt"] == "Sostituisci le provette con una piastra da 96 pozzetti."
    assert data["cases"][-1]["prompt"] == "Use a Bio-Rad 96-well PCR plate instead."
    assert data["cases"][5]["prompt"] == "Passa da eppendorf 1.5ml a 96 microwells plates."
    assert [c["expected"]["outcome"] for c in data["cases"]] == [
        "plate_ready",
        "plate_ready",
        "volume_conflict",
        "plate_ready",
        "rack_restored",
        "plate_ready",
        "unchanged",
        "unchanged",
    ]


@pytest.mark.parametrize("change", ["duplicate", "clarification", "cap", "fixture"])
def test_dataset_rejects_unbounded_or_undeclared_input(dataset, tmp_path, change):
    _, data = dataset
    if change == "duplicate":
        data["cases"][1]["id"] = data["cases"][0]["id"]
    elif change == "clarification":
        data["cases"][0]["clarification"] = "An unplanned repair"
    elif change == "cap":
        data["max_model_calls"] = 9
    else:
        data["cases"][0]["fixture"] = "undeclared"
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        harness.load_dataset(path)


def test_default_dry_run_does_not_prepare_fixture_or_load_model(monkeypatch, capsys):
    monkeypatch.setattr(harness, "make_fixtures", lambda *a: pytest.fail("No fixture in dry run"))
    monkeypatch.setattr(harness, "execute", lambda *a: pytest.fail("No product turn in dry run"))
    assert harness.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["evidence_mode"] == "dry_run" and result["physical_provider_calls"] == 0


def test_fixture_derivation_is_repeatable_and_quantity_only(fixtures):
    assert fixtures == harness.make_fixtures(
        harness.ROOT / "docs/examples/parametric-tube-rack-project.json"
    )
    original, smaller = restore(fixtures["rack_2ml"]), restore(fixtures["rack_200ul"])
    assert original["design"] == smaller["design"]
    assert original["labware_rack"] == smaller["labware_rack"]
    assert original["plan"]["final_volume_ul"] == 2000
    assert smaller["plan"]["final_volume_ul"] == 200
    assert restore(fixtures["plate_200ul"])["labware_plate"]["compatibility"]["status"] == "ready"


@pytest.mark.parametrize(
    "name,outcome,volume",
    [("rack_200ul", "plate_ready", 200), ("rack_2ml", "volume_conflict", 2000)],
)
def test_audit_accepts_only_canonical_plate_and_existing_ik(fixtures, name, outcome, volume):
    before, after = selected_fixture(fixtures, name)
    assert "A1_B1_C1_only" in harness.audit_plate(
        before, after, {"volume_ul": volume, "outcome": outcome}
    )


@pytest.mark.parametrize(
    "tamper", ["source", "fixed_part", "target", "arithmetic", "ik", "capacity"]
)
def test_audit_rejects_unrelated_changes(fixtures, tamper):
    before, after = selected_fixture(fixtures)
    if tamper == "source":
        after["design"]["foundation"]["source_sha256"] = "0" * 64
    elif tamper == "fixed_part":
        harness.component_index(after)["source-rack"]["position"][0] += 1
    elif tamper == "target":
        after["plan"]["steps"][0]["target"] = "10 mg/mL"
    elif tamper == "arithmetic":
        after["plan"]["steps"][0]["stock_volume_ul"] += 1
    elif tamper == "ik":
        after["inspection_extension"]["pose_frames"][0]["target_mm"][0] += 1
    else:
        after["labware_plate"]["derived"]["well_count"] = 384
    with pytest.raises(AssertionError):
        harness.audit_plate(before, after, {"volume_ul": 200, "outcome": "plate_ready"})


def test_restore_exact_saved_rack_but_keep_smaller_recipe(fixtures):
    from app.microplates import LabwareSelection, select_plate

    before = restore(fixtures["plate_200ul"])
    literal = "Restore the previous tube rack for an offline audit fixture."
    after, _ = select_plate(
        before, LabwareSelection(profile_id="previous_tube_rack", source=literal), literal
    )
    harness.audit_restoration(before, after, {"volume_ul": 200})
    harness.component_index(after)["sample-rack"]["position"][0] += 1
    with pytest.raises(AssertionError):
        harness.audit_restoration(before, after, {"volume_ul": 200})


def make_run(dataset, tmp_path, *, replay=None, replay_regression=False):
    path, data = dataset
    return harness.Evaluation(
        path, data, tmp_path / "run", 1, replay=replay, replay_regression=replay_regression
    )


def test_changed_harness_helper_aborts_and_retains_evidence(dataset, tmp_path):
    run = make_run(dataset, tmp_path)
    run.own_hashes[str(tmp_path / "synthetic-helper.py")] = "incorrect-hash"
    (tmp_path / "synthetic-helper.py").write_text("changed", encoding="utf-8")
    with pytest.raises(harness.shared.EvaluationAbort, match="harness/helper"):
        run.guard()
    run.save()
    saved = json.loads((run.output / "results.json").read_text())
    assert saved["abort_reason"] and saved["physical_provider_calls"] == 0


def test_each_actual_attempt_retained_and_call_cap_not_retried(dataset, tmp_path):
    run = make_run(dataset, tmp_path)
    run.max_calls = 8  # Per-case cap must stop a retry even with global calls remaining.
    settings = SimpleNamespace(base_url="https://unit.invalid/v1")
    request = httpx.Request(
        "POST", settings.base_url + "/chat/completions", json={"model": harness.MODEL}
    )

    async def provider(*args, **kwargs):
        return httpx.Response(503, json={"error": "unit failure"}, request=request)

    async def go():
        wrapped = run.instrument(provider, settings)
        assert (await wrapped(None, request)).status_code == 503
        with pytest.raises(harness.shared.EvaluationAbort, match="limit"):
            await wrapped(None, request)

    asyncio.run(go())
    assert len(run.calls) == 1 and run.calls[0]["status"] == "provider_error"
    assert (run.output / "provider/001-response.body").exists()


def test_unexpected_model_is_blocked_before_provider_consumption(dataset, tmp_path):
    run = make_run(dataset, tmp_path)
    settings = SimpleNamespace(base_url="https://unit.invalid/v1")
    request = httpx.Request(
        "POST", settings.base_url + "/chat/completions", json={"model": "unapproved-model"}
    )

    async def forbidden(*args, **kwargs):
        pytest.fail("Wrong model was sent to provider")

    async def go():
        with pytest.raises(harness.shared.EvaluationAbort, match="Unexpected provider model"):
            await run.instrument(forbidden, settings)(None, request)

    asyncio.run(go())
    assert run.calls == [] and run.abort_reason


def test_replay_never_sends_network_or_claims_live_consumption(dataset, tmp_path):
    body = {"model": harness.MODEL}
    replay = {
        "provider_calls": [
            {
                "case_id": "unit",
                "turn_index": 0,
                "schema": None,
                "request": body,
                "http_status": 200,
                "response_body": '{"usage":{"total_tokens":9}}',
            }
        ]
    }
    run = make_run(dataset, tmp_path, replay=replay)
    run.case_id, run.turn_index = "unit", 0
    settings = SimpleNamespace(base_url="https://replay.invalid/v1")
    request = httpx.Request("POST", settings.base_url + "/chat/completions", json=body)

    async def forbidden(*a, **kw):
        pytest.fail("Offline replay called provider")

    asyncio.run(run.instrument(forbidden, settings)(None, request))
    saved = json.loads((run.output / "results.json").read_text())
    assert saved["physical_provider_calls"] == 0 and saved["recorded_attempts"] == 1
    assert saved["evidence_mode"] == "recorded_response_replay"


def test_regression_replay_records_changed_requests_without_new_provider(dataset, tmp_path):
    original_body = {"model": harness.MODEL, "messages": [{"content": "old prompt"}]}
    body = {"model": harness.MODEL, "messages": [{"content": "corrected prompt"}]}
    replay = {
        "provider_calls": [
            {
                "case_id": "unit",
                "turn_index": 0,
                "schema": None,
                "request": original_body,
                "http_status": 200,
                "response_body": '{"usage":{"total_tokens":9}}',
            }
        ]
    }
    run = make_run(dataset, tmp_path, replay=replay, replay_regression=True)
    run.case_id, run.turn_index = "unit", 0
    settings = SimpleNamespace(base_url="https://replay.invalid/v1")
    request = httpx.Request("POST", settings.base_url + "/chat/completions", json=body)

    async def forbidden(*a, **kw):
        pytest.fail("Regression replay called external provider")

    asyncio.run(run.instrument(forbidden, settings)(None, request))
    saved = json.loads((run.output / "results.json").read_text())
    assert saved["physical_provider_calls"] == 0
    assert saved["evidence_mode"] == "recorded_response_regression_replay"
    assert saved["replay_request_differences"][0]["recorded_request"] == original_body
    assert saved["replay_request_differences"][0]["current_request"] == body
    assert saved["replay_request_differences"][0]["request_identical_beyond_runtime_ids"] is False
    assert replay["provider_calls"][0]["request"] == original_body


def test_regression_flag_requires_offline_recorded_input():
    with pytest.raises(SystemExit, match="2"):
        harness.main(["--replay-regression"])


@pytest.mark.parametrize(
    "name,outcome,volume",
    [
        ("rack_200ul", "plate_ready", 200),
        ("rack_2ml", "volume_conflict", 2000),
    ],
)
def test_final_reply_has_actual_state_and_gates(fixtures, name, outcome, volume):
    from app.microplates import canonical_labware_reply

    _, project = selected_fixture(fixtures, name)
    runs = [{"kind": "select_labware", "status": "accepted"}]
    visible = canonical_labware_reply(project, runs, {})
    assert harness.audit_visible_reply(visible, project, {"outcome": outcome, "volume_ul": volume})


@pytest.mark.parametrize(
    "tamper",
    [
        "volume",
        "count",
        "addresses",
        "capacity",
        "stale_prose",
        "tube_appendix",
        "false_block",
    ],
)
def test_visible_reply_rejects_contradictions_even_after_correct_appendix(fixtures, tamper):
    from app.microplates import canonical_labware_reply

    _, project = selected_fixture(fixtures)
    visible = canonical_labware_reply(
        project, [{"kind": "select_labware", "status": "accepted"}], {}
    )
    if tamper == "volume":
        visible = visible.replace("200 µL", "400 µL")
    elif tamper == "count":
        visible = visible.replace("3 existing", "96 existing")
    elif tamper == "addresses":
        visible = visible.replace("C1", "D1")
    elif tamper == "capacity":
        visible = visible.replace("96", "384")
    elif tamper == "stale_prose":
        visible = "The 2 mL recipe is blocked; choose a new volume.\n" + visible
    elif tamper == "tube_appendix":
        visible += "\nCalculated preparation per tube: 20 µL stock + 180 µL diluent."
    else:
        visible += "\nThe recipe is blocked; tell me a volume to unblock it."
    with pytest.raises(AssertionError):
        harness.audit_visible_reply(visible, project, {"outcome": "plate_ready", "volume_ul": 200})


def test_rack_restore_reply_retains_current_volume(fixtures):
    from app.microplates import LabwareSelection, canonical_labware_reply, select_plate

    before = restore(fixtures["plate_200ul"])
    literal = "Restore the previous tube rack."
    project, run = select_plate(
        before, LabwareSelection(profile_id="previous_tube_rack", source=literal), literal
    )
    visible = canonical_labware_reply(project, [run], {})
    harness.audit_visible_reply(visible, project, {"outcome": "rack_restored", "volume_ul": 200})


@pytest.mark.parametrize("phrase", ["stays as-is", "remains as is", "will remain as-is"])
def test_unsupported_reply_accepts_explicit_preservation_synonyms(phrase):
    reply = f"That Bio-Rad PCR plate is unsupported. Your measured rack {phrase}."
    harness.audit_visible_reply(reply, {}, {"outcome": "unchanged"})


@pytest.mark.parametrize(
    "reply",
    [
        "That plate is unsupported. Your rack stays as a new holder.",
        "Your rack stays as-is.",
        "That plate is unsupported. Your rack does not remain as is.",
        "That plate is unsupported. Your rack will not stay as-is.",
        "That plate is unsupported. Your rack no longer remains as is.",
        "That plate is unsupported. Selected Bio-Rad PCR plate; your old rack stays as-is.",
    ],
)
def test_preservation_synonyms_do_not_allow_changes_or_silent_substitution(reply):
    with pytest.raises(AssertionError):
        harness.audit_visible_reply(reply, {}, {"outcome": "unchanged"})


def test_deterministic_documents_roundtrip_and_blocking_gates(fixtures, tmp_path, dataset):
    import app.api as api

    run = make_run(dataset, tmp_path)

    async def go():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api.app), base_url="http://evaluation.local"
        ) as client:
            for name, outcome in (("rack_200ul", "plate_ready"), ("rack_2ml", "volume_conflict")):
                before, after = selected_fixture(fixtures, name)
                api._sessions[after["id"]] = api.ProjectSession(project=deepcopy(after), history=[])
                folder = tmp_path / name
                folder.mkdir()
                await run.audit_documents_and_roundtrip(client, after, folder)
                await run.audit_gating(client, api, before, after, outcome)

    asyncio.run(go())
