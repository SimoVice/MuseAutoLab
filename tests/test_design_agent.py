"""Tests for the bounded Meta layout-design loop and its API endpoint."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import app.api as api
import app.design_agent as design_agent
from app.design_agent import develop_design, propose_layout
from app.model_client import ModelClientError, ModelSettings

TEST_SETTINGS = ModelSettings(
    api_key="test-only-key",
    base_url="https://example.invalid/v1",
    model="muse-spark-1.3-contributor",
)

CANDIDATE = {
    "schema_version": "1",
    "deck_width_mm": 600,
    "deck_depth_mm": 400,
    "placements": [
        {"component_id": "source-rack", "x_mm": -100.0, "z_mm": 0.0},
        {"component_id": "sample-rack", "x_mm": 0.0, "z_mm": 0.0},
        {"component_id": "tip-rack", "x_mm": 100.0, "z_mm": 0.0},
        {"component_id": "tip-waste", "x_mm": -100.0, "z_mm": 100.0},
        {"component_id": "controller", "x_mm": 100.0, "z_mm": 100.0},
    ],
    "rationale": "Keep the sample rack clear.",
    "assumptions": ["Conservative gaps only."],
}

PASSED_CHECKS = [
    {"id": "schema", "label": "Schema", "passed": True, "detail": "Valid."},
    {"id": "gaps", "label": "Gaps", "passed": True, "detail": "Clear."},
]

FAILED_CHECKS = [
    {"id": "schema", "label": "Schema", "passed": True, "detail": "Valid."},
    {"id": "gaps", "label": "Gaps", "passed": False, "detail": "Tip rack overlaps."},
]


def _project(revision=3):
    return {
        "id": "project-1",
        "revision": revision,
        "summary": {"workspace_width_mm": 600},
        "design": {
            "constraint_status": "fits",
            "footprint": {"width_mm": 600, "depth_mm": 370, "height_mm": 400},
            "cooling": {"enabled": False},
            "components": [],
        },
        "workflow": {"kind": "liquid_preparation"},
    }


def _design_response(candidate, *, model="muse-spark-1.3-contributor"):
    return {
        "model": model,
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(candidate)}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


def _run_propose(handler, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await propose_layout(
                _project(), "Arrange the deck.", "", client=client, settings=TEST_SETTINGS
            )

    return asyncio.run(run())


def test_propose_layout_payload_and_usage():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers["authorization"]
        return httpx.Response(200, json=_design_response(CANDIDATE))

    candidate, usage = _run_propose(handler)
    assert candidate == CANDIDATE
    assert usage["model"] == "muse-spark-1.3-contributor"
    assert usage["input_tokens"] == 10
    assert usage["output_tokens"] == 20
    payload = captured["body"]
    assert payload["model"] == "muse-spark-1.3-contributor"
    assert payload["max_completion_tokens"] == 2400
    assert payload["reasoning_effort"] in {"minimal", "low"}
    schema = payload["response_format"]["json_schema"]["schema"]
    assert isinstance(schema, dict)
    assert captured["auth"] == "Bearer test-only-key"


def test_propose_layout_uses_actual_response_model():
    candidate, usage = _run_propose(
        lambda request: httpx.Response(200, json=_design_response(CANDIDATE, model="actual-model"))
    )
    assert candidate == CANDIDATE
    assert usage["model"] == "actual-model"


@pytest.mark.parametrize(
    "body",
    [
        {"choices": []},
        {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
        {"choices": [{"finish_reason": "content_filter", "message": {"content": "{}"}}]},
        {"choices": [{"message": {"content": "not JSON"}}]},
        {"choices": [{"message": {"content": "[1,2]"}}]},
        {"choices": [{"message": {}}]},
        {"unexpected": "envelope"},
    ],
)
def test_propose_layout_rejects_bad_envelopes(body):
    with pytest.raises(ModelClientError, match="incomplete or invalid"):
        _run_propose(lambda request: httpx.Response(200, json=body))


def test_propose_layout_http_error_is_sanitized():
    def handler(request):
        return httpx.Response(429, text="test-only-key secret detail")

    with pytest.raises(ModelClientError) as error:
        _run_propose(handler)
    assert "HTTP 429" in str(error.value)
    assert "test-only-key" not in str(error.value)
    assert "secret detail" not in str(error.value)


def test_propose_layout_network_error_hides_auth():
    def handler(request):
        raise httpx.ConnectError("test-only-key boom", request=request)

    with pytest.raises(ModelClientError) as error:
        _run_propose(handler)
    assert "test-only-key" not in str(error.value)


def test_propose_layout_timeout_reports_sanitized_error(monkeypatch):
    async def slow_send(client):
        await asyncio.sleep(60)
        raise AssertionError("should time out")

    monkeypatch.setattr(design_agent.asyncio, "wait_for", _fast_timeout)
    with pytest.raises(ModelClientError):
        asyncio.run(propose_layout(_project(), "Arrange.", "", settings=TEST_SETTINGS))


async def _fast_timeout(awaitable, timeout):
    awaitable.close()
    raise asyncio.TimeoutError()


def test_develop_design_accepts_first_valid_candidate(monkeypatch):
    async def fake_propose(project, instruction, feedback, **kwargs):
        return dict(CANDIDATE), {"model": "m1", "input_tokens": 1, "output_tokens": 2}

    monkeypatch.setattr(design_agent, "propose_layout", fake_propose)
    monkeypatch.setattr(design_agent, "check_candidate", lambda project, raw: list(PASSED_CHECKS))
    seen = {}

    def fake_apply(project, raw, provenance):
        seen["provenance"] = provenance
        updated = dict(project)
        updated["revision"] = project["revision"] + 1
        return updated

    monkeypatch.setattr(design_agent, "apply_candidate", fake_apply)
    original = _project()
    updated, run = asyncio.run(develop_design(original, "Arrange the deck."))
    assert run["status"] == "accepted"
    assert run["model"] == "m1"
    assert len(run["attempts"]) == 1
    assert updated["revision"] == original["revision"] + 1
    assert original["revision"] == 3
    assert seen["provenance"]["run_id"] == run["id"]
    assert seen["provenance"]["source_revision"] == 3


def test_develop_design_corrects_once_then_accepts(monkeypatch):
    calls = {"count": 0}

    async def fake_propose(project, instruction, feedback, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            assert "overlaps" in feedback
        return dict(CANDIDATE), {"model": "m1"}

    monkeypatch.setattr(design_agent, "propose_layout", fake_propose)
    monkeypatch.setattr(
        design_agent,
        "check_candidate",
        lambda project, raw: list(FAILED_CHECKS) if calls["count"] == 1 else list(PASSED_CHECKS),
    )
    monkeypatch.setattr(
        design_agent, "apply_candidate", lambda project, raw, provenance: dict(project)
    )
    _, run = asyncio.run(develop_design(_project(), "Arrange the deck."))
    assert run["status"] == "accepted"
    assert len(run["attempts"]) == 2
    assert calls["count"] == 2


def test_develop_design_rejects_after_two_attempts_and_preserves_input(monkeypatch):
    calls = {"count": 0}

    async def fake_propose(project, instruction, feedback, **kwargs):
        calls["count"] += 1
        return dict(CANDIDATE), {"model": "m1"}

    monkeypatch.setattr(design_agent, "propose_layout", fake_propose)
    monkeypatch.setattr(design_agent, "check_candidate", lambda project, raw: list(FAILED_CHECKS))

    def forbidden_apply(project, raw, provenance):
        raise AssertionError("must not compile an invalid candidate")

    monkeypatch.setattr(design_agent, "apply_candidate", forbidden_apply)
    original = _project()
    snapshot = json.loads(json.dumps(original))
    updated, run = asyncio.run(develop_design(original, "Arrange the deck."))
    assert run["status"] == "rejected"
    assert len(run["attempts"]) == 2
    assert calls["count"] == 2
    assert updated == snapshot
    assert updated is not original
    assert original == snapshot


def test_develop_design_transport_error_aborts_without_retry(monkeypatch):
    calls = {"count": 0}

    async def failing_propose(project, instruction, feedback, **kwargs):
        calls["count"] += 1
        raise ModelClientError("Could not reach Meta for the design request. Try again.")

    monkeypatch.setattr(design_agent, "propose_layout", failing_propose)
    with pytest.raises(ModelClientError):
        asyncio.run(develop_design(_project(), "Arrange the deck."))
    assert calls["count"] == 1


@pytest.fixture
def client():
    api._sessions.clear()
    with TestClient(api.app) as test_client:
        yield test_client
    api._sessions.clear()


def _seed_session(project):
    api._sessions[project["id"]] = api.ProjectSession(project=dict(project))


def test_design_endpoint_posts_exact_path_and_body(client, monkeypatch):
    captured = {}
    project = _project(revision=4)
    _seed_session(project)

    async def fake_develop(current, instruction):
        captured["instruction"] = instruction
        captured["revision"] = current["revision"]
        run = {
            "id": "design-1",
            "source_revision": 4,
            "status": "accepted",
            "model": "m1",
            "instruction": instruction,
            "attempts": [],
            "message": "Accepted.",
        }
        updated = dict(current)
        updated["revision"] = 5
        return updated, run

    monkeypatch.setattr(api, "develop_design", fake_develop)
    monkeypatch.setattr(api, "describe_workflow", lambda p: {"design_available": True})
    response = client.post(
        f"/api/projects/{project['id']}/design",
        json={"project_revision": 4, "instruction": "  Arrange the deck.  "},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"project", "design_run", "assistant_message"}
    assert body["project"]["revision"] == 5
    assert body["design_run"]["status"] == "accepted"
    assert body["assistant_message"] == "Accepted."
    assert captured == {"instruction": "Arrange the deck.", "revision": 4}
    assert api._sessions[project["id"]].project["revision"] == 5


def test_design_endpoint_rejected_run_preserves_project(client, monkeypatch):
    project = _project(revision=4)
    _seed_session(project)

    async def fake_develop(current, instruction):
        run = {
            "id": "design-2",
            "source_revision": 4,
            "status": "rejected",
            "model": "m1",
            "instruction": instruction,
            "attempts": [{"number": 1, "proposal": {}, "checks": [], "usage": {}}],
            "message": "Rejected.",
        }
        return dict(current), run

    monkeypatch.setattr(api, "develop_design", fake_develop)
    monkeypatch.setattr(api, "describe_workflow", lambda p: {"design_available": True})
    response = client.post(
        f"/api/projects/{project['id']}/design",
        json={"project_revision": 4, "instruction": "Arrange the deck."},
    )
    assert response.status_code == 200
    assert response.json()["project"]["revision"] == 4
    assert api._sessions[project["id"]].project["revision"] == 4


def test_design_endpoint_rejects_stale_revision_before_model(client, monkeypatch):
    _seed_session(_project(revision=4))

    async def forbidden_develop(current, instruction):
        raise AssertionError("must not call the model on stale revision")

    monkeypatch.setattr(api, "develop_design", forbidden_develop)
    response = client.post(
        "/api/projects/project-1/design",
        json={"project_revision": 3, "instruction": "Arrange the deck."},
    )
    assert response.status_code == 409


def test_design_endpoint_rejects_unsupported_workflow_before_model(client, monkeypatch):
    _seed_session(_project(revision=4))

    async def forbidden_develop(current, instruction):
        raise AssertionError("must not call the model when unsupported")

    monkeypatch.setattr(api, "develop_design", forbidden_develop)
    monkeypatch.setattr(api, "describe_workflow", lambda p: {"design_available": False})
    response = client.post(
        "/api/projects/project-1/design",
        json={"project_revision": 4, "instruction": "Arrange the deck."},
    )
    assert response.status_code == 409


def test_design_endpoint_rejects_infeasible_width_before_model(client, monkeypatch):
    stored = _project(revision=4)
    stored["design"]["constraint_status"] = "infeasible"
    _seed_session(stored)

    async def forbidden_develop(current, instruction):
        raise AssertionError("must not call the model on infeasible width")

    monkeypatch.setattr(api, "develop_design", forbidden_develop)
    monkeypatch.setattr(api, "describe_workflow", lambda p: {"design_available": True})
    response = client.post(
        "/api/projects/project-1/design",
        json={"project_revision": 4, "instruction": "Arrange the deck."},
    )
    assert response.status_code == 409


def test_design_endpoint_validates_instruction_bounds(client):
    _seed_session(_project(revision=4))
    assert (
        client.post(
            "/api/projects/project-1/design",
            json={"project_revision": 4, "instruction": "   "},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/projects/project-1/design",
            json={"project_revision": 4, "instruction": "x" * 2001},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/projects/project-1/design",
            json={"project_revision": 4, "instruction": "ok", "extra": 1},
        ).status_code
        == 422
    )


def test_design_endpoint_model_error_is_502_without_history(client, monkeypatch):
    _seed_session(_project(revision=4))

    async def failing_develop(current, instruction):
        raise ModelClientError("Could not reach Meta for the design request. Try again.")

    monkeypatch.setattr(api, "develop_design", failing_develop)
    monkeypatch.setattr(api, "describe_workflow", lambda p: {"design_available": True})
    response = client.post(
        "/api/projects/project-1/design",
        json={"project_revision": 4, "instruction": "Arrange the deck."},
    )
    assert response.status_code == 502
    assert api._sessions["project-1"].project["revision"] == 4
    assert api._sessions["project-1"].history == []


def test_failed_correction_retains_previous_usage_and_does_not_change_input(monkeypatch):
    from copy import deepcopy

    source = _project()
    before = deepcopy(source)
    calls = []

    async def fake_propose(project, instruction, feedback):
        calls.append(feedback)
        if len(calls) == 1:
            return CANDIDATE, {"model": "test-meta", "input_tokens": 12, "output_tokens": 7}
        error = ModelClientError("Meta returned an incomplete design response.")
        error.usage = {"model": "test-meta", "input_tokens": 15, "output_tokens": 9}
        raise error

    monkeypatch.setattr(design_agent, "propose_layout", fake_propose)
    monkeypatch.setattr(design_agent, "check_candidate", lambda p, c: [
        {"id": "overlap", "label": "Separation", "passed": False, "detail": "Overlap."},
    ])
    with pytest.raises(ModelClientError) as caught:
        asyncio.run(develop_design(source, "Keep a clear work area."))
    run = caught.value.design_run
    assert run["status"] == "failed" and len(run["attempts"]) == 2
    assert run["attempts"][0]["usage"]["input_tokens"] == 12
    assert run["attempts"][1]["usage"]["output_tokens"] == 9
    assert run["attempts"][1]["proposal"] is None
    assert run["attempts"][1]["checks"] == []
    assert source == before and calls[1]
