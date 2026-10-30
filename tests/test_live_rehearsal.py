"""The live rehearsal must stay offline by default and bound actual provider calls."""

import asyncio
import json
import subprocess
import sys

import httpx
import pytest

from app.model_client import ModelClientError, ModelSettings
from scripts.rehearse_live_api import ROOT, Rehearsal, assert_quantity_layout, token_totals


def test_default_rehearsal_needs_no_credentials_or_event_loop():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "rehearse_live_api.py"), "--routes", "1"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    payload = json.loads(result.stdout)
    assert payload["mode"] == "dry_run"
    assert len(payload["scenarios"]) == 1
    assert payload["model"] == "muse-spark-1.3-contributor"


def test_usage_includes_failed_responses_and_marks_missing_counts():
    calls = [
        {
            "status": "completed",
            "usage": {"prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40},
        },
        {
            "status": "provider_error",
            "usage": {"prompt_tokens": 20, "completion_tokens": 4, "total_tokens": 24},
        },
        {"status": "transport_error", "usage": None},
    ]
    assert token_totals(calls) == {
        "prompt_tokens": 50,
        "completion_tokens": 14,
        "total_tokens": 64,
        "calls_with_incomplete_usage": 1,
    }


def test_budget_counts_provider_requests_once_and_excludes_local_api(tmp_path):
    rehearsal = Rehearsal(tmp_path, ModelSettings("secret", "https://example.invalid/v1", "m"), 1)
    sent = []

    async def original(client, request, *args, **kwargs):
        sent.append(str(request.url))
        return httpx.Response(
            200,
            request=request,
            json={
                "model": "actual",
                "choices": [],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            },
        )

    async def run():
        instrumented = rehearsal.instrument(original)
        request = httpx.Request(
            "POST",
            "https://example.invalid/v1/chat/completions",
            json={
                "model": "m",
                "response_format": {"json_schema": {"name": "test"}},
            },
            headers={"Authorization": "Bearer secret"},
        )
        await instrumented(None, httpx.Request("GET", "http://local/api/health"))
        await instrumented(None, request)
        with pytest.raises(ModelClientError, match="budget exhausted"):
            await instrumented(None, request)

    asyncio.run(run())
    assert len(sent) == 2
    assert len(rehearsal.calls) == 1
    saved = (tmp_path / "results.json").read_text(encoding="utf-8")
    assert "secret" not in saved
    assert token_totals(rehearsal.calls)["total_tokens"] == 5


def test_quantity_layout_allows_only_canonical_rack_update():
    from copy import deepcopy

    from foundation_fixtures import liquid_project, source_proposal

    from app.design_spec import apply_candidate
    from app.domain import apply_update
    from app.foundation_design import adopt_foundation

    before = apply_candidate(adopt_foundation(liquid_project()), source_proposal(), {})
    after = apply_update(before, {"target_concentrations": "1, 0.5 and 0.1 mg/mL"})
    assert_quantity_layout(before, after)
    sample = next(c for c in after["design"]["components"] if c["id"] == "sample-rack")
    assert sample["rack_slot_count"] == 3
    moved = deepcopy(after)
    moved["design"]["components"][0]["position"][0] += 1
    with pytest.raises(AssertionError):
        assert_quantity_layout(before, moved)
    malformed = deepcopy(after)
    next(c for c in malformed["design"]["components"] if c["id"] == "sample-rack")[
        "rack_slot_count"
    ] = 5
    with pytest.raises(AssertionError):
        assert_quantity_layout(before, malformed)
