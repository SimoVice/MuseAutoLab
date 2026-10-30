"""Exercise real HTTP payload builders under selected project model scopes."""

import asyncio
import json
from copy import deepcopy

import httpx
import pytest
from evolution_fixtures import inspection_proposal, layout_project
from fastapi.testclient import TestClient
from test_vision_jobs import _make_data_url, _raw_single, _wait_job

import app.api as api
import app.vision_jobs as jobs
from app.model_client import DEFAULT_MODEL, ChatAction, ExtractedTurn, ModelSettings, using_model


@pytest.fixture(autouse=True)
def local_configuration(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "synthetic-test-key")
    monkeypatch.setenv("META_API_BASE_URL", "https://api.meta.ai/v1")
    monkeypatch.setenv("META_MODEL", DEFAULT_MODEL)
    api._sessions.clear()
    jobs._jobs.clear()
    jobs._cache.clear()
    yield
    api._sessions.clear()
    jobs._jobs.clear()
    jobs._cache.clear()


def install_transport(monkeypatch, handler):
    client_type = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return client_type(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def response(content, model):
    return httpx.Response(
        200,
        json={
            "model": model,
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(content)}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10},
        },
    )


def test_real_chat_design_and_extension_payloads_share_session_selection(monkeypatch):
    project = layout_project()
    original = deepcopy(project)
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        name = payload["response_format"]["json_schema"]["name"]
        calls.append((name, payload["model"]))
        if name == "layout_proposal":
            content = project["engineering_design"]["proposal"]
        elif name == "requirement_turn":
            content = ExtractedTurn(
                assistant_message="I will propose the requested inspection extension.",
                actions=[ChatAction(kind="add_inspection", source="Add inspection camera.")],
            ).model_dump()
        else:
            assert name == "inspection_proposal"
            content = inspection_proposal()
        return response(content, payload["model"])

    install_transport(monkeypatch, handler)
    session = api.ProjectSession(project=project, model="muse-wonder-1.0")
    api._sessions[project["id"]] = session
    with TestClient(api.app) as client:
        path = f"/api/projects/{project['id']}"
        designed = client.post(
            path + "/design",
            json={
                "instruction": "Reconsider this layout.",
                "project_revision": project["revision"],
            },
        )
        assert designed.status_code == 200, designed.text
        assert designed.json()["design_run"]["model"] == "muse-wonder-1.0"
        chat = client.post(path + "/messages", json={"message": "Add inspection camera."})
        assert chat.status_code == 200, chat.text
        result = chat.json()
        assert result["usage"]["model"] == "muse-wonder-1.0"
        assert result["action_runs"][0]["model"] == "muse-wonder-1.0"
        assert result["project"]["inspection_extension"]["provenance"]["model"] == "muse-wonder-1.0"
    assert calls == [
        ("layout_proposal", "muse-wonder-1.0"),
        ("requirement_turn", "muse-wonder-1.0"),
        ("inspection_proposal", "muse-wonder-1.0"),
    ]
    assert project == original
    assert ModelSettings.load().model == DEFAULT_MODEL


def test_background_vision_captures_model_and_deduplicates_per_model(monkeypatch):
    observed = []

    def handler(request):
        payload = json.loads(request.content)
        observed.append(payload["model"])
        return response(_raw_single(), payload["model"])

    install_transport(monkeypatch, handler)
    project = layout_project()
    session = api.ProjectSession(project=project, model="muse-wonder-1.0")
    api._sessions[project["id"]] = session
    with TestClient(api.app) as client:
        base = f"/api/projects/{project['id']}/inspections"
        body = {"project_revision": project["revision"], "image_data_url": _make_data_url()}
        first = client.post(base, json=body).json()
        one = _wait_job(client, base + "/" + first["id"])
        assert one["result"]["model"] == "muse-wonder-1.0"
        assert one["result"]["usage"]["model"] == "muse-wonder-1.0"
        repeated = client.post(base, json=body).json()
        assert repeated["id"] == first["id"]
        session.model = "muse-spark-1.3"
        second = client.post(base, json=body).json()
        two = _wait_job(client, base + "/" + second["id"])
        assert second["id"] != first["id"]
        assert two["result"]["model"] == "muse-spark-1.3"
    assert observed == ["muse-wonder-1.0", "muse-spark-1.3"]


def test_child_task_retains_selection_after_parent_scope_ends():
    async def run():
        gate = asyncio.Event()

        async def child():
            await gate.wait()
            return ModelSettings.load().model

        with using_model("muse-wonder-1.0"):
            task = asyncio.create_task(child())
        gate.set()
        assert await task == "muse-wonder-1.0"
        assert ModelSettings.load().model == DEFAULT_MODEL

    asyncio.run(run())
