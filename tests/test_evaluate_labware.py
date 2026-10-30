"""Harness safety/accounting checks; no Meta calls or frozen-case rehearsals."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from scripts import evaluate_labware as harness


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    (tmp_path / "app").mkdir()
    (tmp_path / "web" / "src").mkdir(parents=True)
    (tmp_path / "app" / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "web" / "src" / "example.ts").write_text(
        "export const value = 1;\n", encoding="utf-8"
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{}", encoding="utf-8")
    dataset = {
        "schema_version": 1,
        "baseline": "baseline.json",
        "max_model_calls": 1,
        "cases": [
            {
                "id": "unit_case",
                "prompt": "Synthetic harness unit input.",
                "expected": {"outcome": "unchanged"},
            }
        ],
    }
    dataset_path = tmp_path / "cases.json"
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
    return tmp_path, dataset_path, dataset


def test_fingerprint_covers_owned_assets_and_ignores_generated_dependencies(workspace):
    root, _, _ = workspace
    before = harness.source_fingerprint()
    dependency = root / "web" / "node_modules" / "dependency.js"
    dependency.parent.mkdir()
    dependency.write_text("ignored", encoding="utf-8")
    (root / "app" / ".env").write_text("not-recorded", encoding="utf-8")
    assert harness.source_fingerprint() == before
    (root / "app" / "example.py").write_text("VALUE = 2\n", encoding="utf-8")
    after = harness.source_fingerprint()
    assert after["sha256"] != before["sha256"]
    assert "app/.env" not in after["files"]


def test_dataset_requires_unique_ids_and_one_predeclared_clarification(workspace):
    _, path, data = workspace
    assert harness.load_dataset(path) == data
    data["cases"].append(data["cases"][0])
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        harness.load_dataset(path)
    data["cases"] = data["cases"][:1]
    data["cases"][0]["clarification"] = ["repair one", "repair two"]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="one predeclared"):
        harness.load_dataset(path)


def test_json_pointer_and_exact_numeric_comparison():
    assert harness.pointer({"a/b": {"~": [1.25]}}, "/a~1b/~0/0") == 1.25
    harness.assert_equal([1.25, 2], [1.25, 2.0])
    with pytest.raises(AssertionError):
        harness.assert_equal(True, 1)


def inspection_fixture():
    before = {
        "inspection_extension": {
            "proposal": {"link_lengths_mm": [200, 250], "mast_height_mm": 450},
            "provenance": {"model": "synthetic-unit-fixture"},
            "components": [{"id": "unit-camera", "position": [1, 55, 3]}],
            "pose_frames": [
                {"time_s": 0, "target_mm": [1, 10, 3], "camera_mm": [1, 55, 3]},
                {"time_s": 2, "target_mm": [-19, 10, 3], "camera_mm": [-19, 55, 3]},
            ],
        }
    }
    after = deepcopy(before)
    rack_part = {"position": [1, 35, 3], "size": [4, 20, 5]}
    for frame in after["inspection_extension"]["pose_frames"]:
        frame["target_mm"][1] = 45
    return before, after, rack_part


def test_inspection_allows_only_correct_derived_target_height():
    before, after, rack_part = inspection_fixture()
    harness.audit_inspection_targets(before, after, rack_part)
    after["inspection_extension"]["pose_frames"][0]["target_mm"][1] = 46
    with pytest.raises(AssertionError, match="follows rack top"):
        harness.audit_inspection_targets(before, after, rack_part)


@pytest.mark.parametrize("axis", [0, 2])
def test_inspection_rejects_target_xz_changes(axis):
    before, after, rack_part = inspection_fixture()
    after["inspection_extension"]["pose_frames"][0]["target_mm"][axis] += 1
    with pytest.raises(AssertionError, match="target x/z changed"):
        harness.audit_inspection_targets(before, after, rack_part)


def test_inspection_rejects_proposal_or_pose_geometry_changes():
    before, after, rack_part = inspection_fixture()
    after["inspection_extension"]["proposal"]["link_lengths_mm"][0] += 1
    with pytest.raises(AssertionError, match="beyond target height"):
        harness.audit_inspection_targets(before, after, rack_part)
    before, after, rack_part = inspection_fixture()
    after["inspection_extension"]["pose_frames"][0]["camera_mm"][1] += 1
    with pytest.raises(AssertionError, match="beyond target height"):
        harness.audit_inspection_targets(before, after, rack_part)


def test_source_and_dataset_changes_abort_without_losing_metadata(workspace):
    root, path, data = workspace
    run = harness.Evaluation(path, data, root / ".local" / "unit-run", 1)
    (root / "web" / "src" / "example.ts").write_text("changed", encoding="utf-8")
    with pytest.raises(harness.EvaluationAbort, match="source changed"):
        run.guard()
    run.save()
    saved = json.loads((run.output / "results.json").read_text())
    assert saved["source_before"] != saved["source_after"]
    assert saved["physical_provider_calls"] == 0
    assert saved["abort_reason"]


def test_transport_retains_raw_attempt_and_usage_and_enforces_physical_cap(workspace):
    root, path, data = workspace
    run = harness.Evaluation(path, data, root / ".local" / "unit-run", 1)
    run.case_id, run.turn_index = "unit_case", 0
    settings = SimpleNamespace(base_url="https://provider.invalid/v1")
    body = {
        "model": harness.MODEL,
        "messages": [{"role": "user", "content": "unit input"}],
        "response_format": {"json_schema": {"name": "unit_schema"}},
    }
    request = httpx.Request(
        "POST",
        settings.base_url + "/chat/completions",
        json=body,
        headers={"Authorization": "Bearer unit-only-not-a-secret"},
    )

    async def provider(client, request, **kwargs):
        return httpx.Response(
            200,
            request=request,
            json={
                "model": harness.MODEL,
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "invalid product JSON"}}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
            },
        )

    async def execute():
        wrapped = run.instrument(provider, settings)
        await wrapped(None, request)
        with pytest.raises(harness.EvaluationAbort, match="limit reached"):
            await wrapped(None, request)

    asyncio.run(execute())
    run.save()
    assert len(run.calls) == 1
    assert harness.token_totals(run.calls)["total_tokens"] == 12
    assert "invalid product JSON" in run.calls[0]["response_body"]
    assert "Authorization" not in (run.output / "results.json").read_text()
    assert (run.output / "provider" / "001-request.json").exists()
    assert (run.output / "provider" / "001-response.body").exists()


def test_failed_transport_is_still_counted_and_retained(workspace):
    root, path, data = workspace
    run = harness.Evaluation(path, data, root / ".local" / "unit-run", 1)
    settings = SimpleNamespace(base_url="https://provider.invalid/v1")
    request = httpx.Request("POST", settings.base_url + "/chat/completions", json={})

    async def provider(client, request, **kwargs):
        raise httpx.ConnectError("unit transport failure", request=request)

    async def execute():
        with pytest.raises(httpx.ConnectError):
            await run.instrument(provider, settings)(None, request)

    asyncio.run(execute())
    saved = json.loads((run.output / "results.json").read_text())
    assert saved["physical_provider_calls"] == 1
    assert saved["provider_calls"][0]["error_type"] == "ConnectError"
    assert saved["token_totals"]["calls_with_incomplete_usage"] == 1


def test_replay_never_calls_provider_and_is_not_reported_as_live(workspace):
    root, path, data = workspace
    body = {
        "messages": [{"role": "user", "content": "unit input"}],
        "response_format": {"json_schema": {"name": "unit_schema"}},
    }
    replay = {
        "provider_calls": [
            {
                "case_id": "unit_case",
                "turn_index": 0,
                "schema": "unit_schema",
                "request": body,
                "http_status": 200,
                "response_body": '{"usage":{"total_tokens":7}}',
            }
        ]
    }
    run = harness.Evaluation(path, data, root / ".local" / "unit-run", 1, replay=replay)
    run.case_id, run.turn_index = "unit_case", 0
    settings = SimpleNamespace(base_url="https://replay.invalid/v1")
    request = httpx.Request("POST", settings.base_url + "/chat/completions", json=body)

    async def provider(*args, **kwargs):
        pytest.fail("Replay must not call the provider")

    asyncio.run(run.instrument(provider, settings)(None, request))
    saved = json.loads((run.output / "results.json").read_text())
    assert saved["evidence_mode"] == "recorded_response_replay"
    assert saved["physical_provider_calls"] == 0
    assert saved["token_totals"]["total_tokens"] == 7


def test_dry_run_does_not_execute_cases_or_load_credentials(workspace, monkeypatch, capsys):
    _, path, _ = workspace

    async def unexpected(*args):
        pytest.fail("Dry run must not invoke product or provider execution")

    monkeypatch.setattr(harness, "execute", unexpected)
    assert harness.main(["--dataset", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["evidence_mode"] == "dry_run" and result["physical_provider_calls"] == 0
