"""Bounded optional image generation with synthetic pixels and mocked Meta transport."""

import asyncio
import base64
import hashlib
import importlib
import io
import json
from copy import deepcopy

import httpx
import pytest
from evolution_fixtures import layout_project
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin

import app.api as api
import app.illustration as illustration
import app.model_catalog as catalog
from app.model_client import DEFAULT_MODEL, ModelSettings

SETTINGS = ModelSettings("synthetic-test-key", "https://api.meta.ai/v1", DEFAULT_MODEL)


def pixels(*, size=(96, 64), fmt="PNG", metadata=False):
    output = io.BytesIO()
    image = Image.new("RGB", size, (20, 120, 100))
    kwargs = {}
    if metadata and fmt == "PNG":
        info = PngImagePlugin.PngInfo()
        info.add_text("Private", "never send this metadata")
        kwargs["pnginfo"] = info
    image.save(output, format=fmt, **kwargs)
    return output.getvalue()


def data_url(raw=None, mime="image/png"):
    return "data:" + mime + ";base64," + base64.b64encode(raw or pixels()).decode("ascii")


def provider_body(raw=None):
    return {
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": [{"text": "never expose provider narration"}]},
            {
                "type": "image_generation_call",
                "status": "completed",
                "result": base64.b64encode(raw or pixels()).decode("ascii"),
            },
        ],
        "usage": {
            "input_tokens": 4,
            "output_tokens": 6,
            "total_tokens": 10,
            "secret": "never expose private provider data",
        },
    }


@pytest.fixture(autouse=True)
def local_configuration(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "synthetic-test-key")
    monkeypatch.setenv("META_API_BASE_URL", "https://api.meta.ai/v1")
    monkeypatch.setenv("META_MODEL", DEFAULT_MODEL)

    async def discover(**kwargs):
        return {
            "ids": [*catalog.AGENT_MODELS, catalog.IMAGE_MODEL],
            "reason": None,
            "verified": True,
        }

    monkeypatch.setattr(api, "discover_catalog", discover)
    monkeypatch.setattr(catalog, "discover_catalog", discover)
    api._sessions.clear()
    yield
    api._sessions.clear()
    assert illustration._active_generations == 0


@pytest.mark.parametrize(
    "value",
    [
        "https://example.test/reference.png",
        "",
        "data:image/png;base64,@@",
        data_url(b"not png"),
        data_url(pixels(fmt="JPEG")),
        data_url(pixels(size=(4097, 32))),
        data_url(pixels(size=(10, 10))),
        data_url(pixels()[:-10]),
    ],
    ids=[
        "remote-url",
        "empty",
        "base64",
        "magic",
        "mime-mismatch",
        "huge-dimensions",
        "tiny",
        "truncated",
    ],
)
def test_invalid_reference_is_rejected(value):
    with pytest.raises(illustration.IllustrationError) as caught:
        illustration.prepare_reference(value)
    assert caught.value.status_code == 422


def test_reference_caps_metadata_and_normalization(monkeypatch):
    raw = pixels(metadata=True)
    image = illustration.prepare_reference(data_url(raw))
    assert b"never send" not in image.content
    assert image.sha256 == hashlib.sha256(image.content).hexdigest()
    assert image.data_url.startswith("data:image/png;base64,")
    resized = illustration.prepare_reference(data_url(pixels(size=(2400, 1200))))
    assert (resized.width, resized.height) == (2048, 1024)
    jpeg = illustration.prepare_reference(data_url(pixels(fmt="JPEG"), "image/jpeg"))
    assert jpeg.content.startswith(b"\x89PNG")
    monkeypatch.setattr(illustration, "MAX_REFERENCE_DATA_URL", 32)
    with pytest.raises(illustration.IllustrationError) as caught:
        illustration.prepare_reference(data_url())
    assert caught.value.status_code == 413


def test_animated_image_is_rejected():
    output = io.BytesIO()
    frames = [Image.new("RGB", (64, 64), color) for color in ("red", "blue")]
    frames[0].save(output, format="PNG", save_all=True, append_images=frames[1:])
    with pytest.raises(illustration.IllustrationError):
        illustration.prepare_reference(data_url(output.getvalue()))


def test_fixed_official_payload_and_safe_output_metadata(caplog):
    project = layout_project()
    original = deepcopy(project)
    reference = illustration.prepare_reference(data_url(pixels(metadata=True)))
    requests = []

    async def handler(request):
        requests.append(request)
        payload = json.loads(await request.aread())
        assert request.url == "https://api.meta.ai/v1/responses"
        assert request.headers["Authorization"] == "Bearer synthetic-test-key"
        assert payload["model"] == catalog.IMAGE_MODEL
        assert payload["store"] is False
        assert payload["tools"] == [illustration.TOOL]
        assert all(
            payload["tools"][0][key] is False
            for key in ("enable_image_search", "enable_web_search", "enable_shell")
        )
        assert payload["input"][0]["content"][1]["image_url"] == reference.data_url
        assert "never send" not in str(payload)
        return httpx.Response(200, json=provider_body(pixels(metadata=True)))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await illustration.generate_illustration(
                project, reference, settings=SETTINGS, client=client
            )

    result = asyncio.run(run())
    returned = base64.b64decode(result["image_data_url"].split(",", 1)[1])
    assert hashlib.sha256(returned).hexdigest() == result["image_sha256"]
    assert result["reference_sha256"] == reference.sha256
    assert result["project_id"] == project["id"]
    assert result["project_revision"] == project["revision"]
    assert result["usage"] == {
        "model": catalog.IMAGE_MODEL,
        "images": 1,
        "input_tokens": 4,
        "output_tokens": 6,
        "total_tokens": 10,
    }
    assert "presentation only" in result["scope"]
    assert "Meta Muse Image" in result["attribution"]
    assert b"never send" not in returned
    assert "provider narration" not in str(result)
    assert "private provider" not in str(result)
    assert "synthetic-test-key" not in caplog.text
    assert project == original
    assert len(requests) == 1


@pytest.mark.parametrize("status,expected", [(403, 503), (404, 503), (429, 429), (500, 502)])
def test_provider_failures_do_not_retry_or_expose_errors(status, expected):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "private provider message"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(illustration.IllustrationError) as caught:
                await illustration.generate_illustration(
                    layout_project(),
                    illustration.prepare_reference(data_url()),
                    settings=SETTINGS,
                    client=client,
                )
        assert caught.value.status_code == expected
        assert "private provider message" not in str(caught.value)

    asyncio.run(run())
    assert len(calls) == 1


@pytest.mark.parametrize(
    "kind", ["incomplete", "multiple", "url", "jpeg", "truncated", "dimensions"]
)
def test_invalid_provider_images_are_rejected(kind):
    body = provider_body()
    if kind == "incomplete":
        body["status"] = "incomplete"
    elif kind == "multiple":
        body["output"].append(deepcopy(body["output"][-1]))
    elif kind == "url":
        body["output"][-1]["result"] = "https://example.test/image.png"
    elif kind == "jpeg":
        body = provider_body(pixels(fmt="JPEG"))
    elif kind == "truncated":
        body = provider_body(pixels()[:-10])
    else:
        body = provider_body(pixels(size=(4097, 32)))
    with pytest.raises(illustration.IllustrationError) as caught:
        illustration._extract_image(body)
    assert caught.value.status_code == 502


def test_response_is_capped_before_json_or_base64_decode(monkeypatch):
    monkeypatch.setattr(illustration, "MAX_RESPONSE_BYTES", 100)

    def handler(request):
        return httpx.Response(200, content=b"x" * 101)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(illustration.IllustrationError, match="oversized"):
                await illustration.generate_illustration(
                    layout_project(),
                    illustration.prepare_reference(data_url()),
                    settings=SETTINGS,
                    client=client,
                )

    asyncio.run(run())


def test_timeout_cancellation_and_global_busy_release_capacity(monkeypatch):
    async def run():
        entered = asyncio.Event()

        async def handler(request):
            entered.set()
            await asyncio.Event().wait()

        reference = illustration.prepare_reference(data_url())
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            task = asyncio.create_task(
                illustration.generate_illustration(
                    layout_project(), reference, settings=SETTINGS, client=client
                )
            )
            await entered.wait()
            with pytest.raises(illustration.IllustrationError) as caught:
                await illustration.generate_illustration(
                    layout_project(), reference, settings=SETTINGS, client=client
                )
            assert caught.value.status_code == 429
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert illustration._active_generations == 0
            monkeypatch.setattr(illustration, "GENERATION_TIMEOUT_SECONDS", 0.01)
            with pytest.raises(illustration.IllustrationError) as timed_out:
                await illustration.generate_illustration(
                    layout_project(), reference, settings=SETTINGS, client=client
                )
            assert timed_out.value.status_code == 504

    asyncio.run(run())


def test_nonofficial_endpoint_never_sends():
    async def run():
        with pytest.raises(illustration.IllustrationError) as caught:
            await illustration.generate_illustration(
                layout_project(),
                illustration.prepare_reference(data_url()),
                settings=ModelSettings("test", "https://example.test/v1", DEFAULT_MODEL),
            )
        assert caught.value.status_code == 503

    asyncio.run(run())


def seed(project=None):
    project = project or layout_project()
    api._sessions[project["id"]] = api.ProjectSession(project=project)
    return project, f"/api/projects/{project['id']}/illustration"


def test_api_missing_stale_unaccepted_and_invalid_project_never_generate(monkeypatch):
    calls = []

    async def generate(*args):
        calls.append(True)
        raise AssertionError("No generation expected")

    monkeypatch.setattr(api, "generate_illustration", generate)
    with TestClient(api.app) as client:
        assert client.post("/api/projects/missing/illustration", json={}).status_code == 404
        project, path = seed()
        body = {"project_revision": project["revision"] - 1, "reference_image_data_url": data_url()}
        assert client.post(path, json=body).status_code == 409
        body["project_revision"] = project["revision"]
        body["reference_image_data_url"] = "https://example.test/private.png"
        assert client.post(path, json=body).status_code == 422
        body["reference_image_data_url"] = data_url()
        api._sessions[project["id"]].project.pop("engineering_design")
        assert client.post(path, json=body).status_code == 409
        assert client.post(path, json={**body, "prompt": "arbitrary prompt"}).status_code == 422
    assert calls == []


def test_api_success_preserves_state_and_snapshot(monkeypatch):
    async def generate(project, reference):
        return {
            "project_id": project["id"],
            "project_revision": project["revision"],
            "reference_sha256": reference.sha256,
            "image_data_url": data_url(),
            "image_sha256": hashlib.sha256(pixels()).hexdigest(),
            "model": catalog.IMAGE_MODEL,
            "scope": illustration.SCOPE,
            "attribution": illustration.ATTRIBUTION,
            "usage": {},
        }

    monkeypatch.setattr(api, "generate_illustration", generate)
    with TestClient(api.app) as client:
        project, path = seed()
        session = api._sessions[project["id"]]
        before = deepcopy(session.project), deepcopy(session.history)
        result = client.post(
            path,
            json={"project_revision": project["revision"], "reference_image_data_url": data_url()},
        )
        assert result.status_code == 200, result.text
        assert result.json()["project_revision"] == project["revision"]
        assert (session.project, session.history) == before
        snapshot = client.get(
            f"/api/projects/{project['id']}/snapshot", params={"revision": project["revision"]}
        )
        assert "image_data_url" not in snapshot.text


def test_revision_changed_during_generation_returns_409_without_overwrite(monkeypatch):
    async def generate(project, reference):
        api._sessions[project["id"]].project["revision"] += 1
        return {"image_data_url": data_url()}

    monkeypatch.setattr(api, "generate_illustration", generate)
    with TestClient(api.app) as client:
        project, path = seed()
        revision = project["revision"]
        result = client.post(
            path, json={"project_revision": revision, "reference_image_data_url": data_url()}
        )
        assert result.status_code == 409
        assert api._sessions[project["id"]].project["revision"] == revision + 1
        assert "image_data_url" not in api._sessions[project["id"]].project


def test_api_provider_failure_preserves_project(monkeypatch):
    async def generate(project, reference):
        raise illustration.IllustrationError(504, "Synthetic timeout")

    monkeypatch.setattr(api, "generate_illustration", generate)
    with TestClient(api.app) as client:
        project, path = seed()
        before = deepcopy(project)
        result = client.post(
            path,
            json={"project_revision": project["revision"], "reference_image_data_url": data_url()},
        )
        assert result.status_code == 504
        assert api._sessions[project["id"]].project == before


def test_request_body_cap_is_checked_before_json_parse(monkeypatch):
    monkeypatch.setattr(api, "MAX_REQUEST_BYTES", 100)
    with TestClient(api.app) as client:
        project, path = seed()
        result = client.post(path, content=b"x" * 101, headers={"Content-Type": "application/json"})
        assert result.status_code == 413
        assert api._sessions[project["id"]].project == project


def test_account_and_endpoint_gates_disable_image(monkeypatch):
    monkeypatch.setenv("META_API_BASE_URL", "https://example.test/v1")
    models = asyncio.run(catalog.model_options())
    assert models["capabilities"]["image"]["available"] is False
    assert "official" in models["capabilities"]["image"]["unavailable_reason"]


def test_disconnect_cancels_generation_task(monkeypatch):
    observed = []

    async def generate(project, reference):
        try:
            await asyncio.Event().wait()
        finally:
            observed.append("cancelled")

    class Disconnected:
        async def is_disconnected(self):
            await asyncio.sleep(0)
            return True

    monkeypatch.setattr(api, "generate_illustration", generate)

    async def run():
        with pytest.raises(api.HTTPException) as caught:
            await api._illustrate_connected(
                Disconnected(), layout_project(), illustration.prepare_reference(data_url())
            )
        assert caught.value.status_code == 499

    asyncio.run(run())
    assert observed == ["cancelled"]


def test_shared_browser_catalog_never_calls_live_provider(monkeypatch):
    # The browser module patches on import; record its targets so this unit test restores them.
    monkeypatch.setattr(api, "discover_catalog", api.discover_catalog)
    monkeypatch.setattr(catalog, "discover_catalog", catalog.discover_catalog)

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline browser fixtures must not call the provider")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    import browser_stub_server

    importlib.reload(browser_stub_server)
    models = asyncio.run(catalog.model_options())
    assert all(option["available"] is True for option in models["models"])
    assert models["capabilities"]["image"]["available"] is False
    assert models["capabilities"]["voice"]["available"] is False
