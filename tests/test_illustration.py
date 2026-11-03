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


# These endpoints use synthetic geometry and mocked transport, never paid calls.
def test_step_illustration_binds_current_step_and_rejects_client_prompts(monkeypatch):
    calls = []

    async def generate(project, reference, *, prompt):
        calls.append(prompt)
        assert reference.width == 1024
        return {"project_id": project["id"], "project_revision": project["revision"],
                "reference_sha256": reference.sha256, "image_data_url": data_url()}

    monkeypatch.setattr(api, "generate_illustration", generate)
    with TestClient(api.app) as client:
        project, _ = seed()
        path = f"/api/projects/{project['id']}/instructions/illustration"
        from app.instructions import build_instruction_guide
        guide = build_instruction_guide(project)
        step = next(s for s in guide["assembly_steps"] if s["component_ids"])
        body = {"project_revision": project["revision"], "step_id": step["id"]}
        before = deepcopy(project)
        result = client.post(path, json=body)
        assert result.status_code == 200, result.text
        assert result.json()["component_ids"] == step["component_ids"]
        assert result.json()["step_id"] == step["id"]
        assert "schematic" in result.json()["scope"]
        assert project == before
        assert client.post(path, json={**body, "prompt": "add parts"}).status_code == 422
        injected = {**body, "reference_image_data_url": data_url()}
        assert client.post(path, json=injected).status_code == 422
        assert client.post(path, json={**body, "step_id": "assembly-999"}).status_code == 404
        stale = {**body, "project_revision": project["revision"] - 1}
        assert client.post(path, json=stale).status_code == 409
    assert len(calls) == 1
    assert "untrusted reference data" in calls[0]


def test_concept_step_context_excludes_unrelated_components():
    from app.step_illustration import schematic_reference, step_context, step_prompt
    project = {"concept_design": {"components": [
        {"key": key, "name": key, "assembly": "Fit this component.",
         "position_mm": [0, 20, 0], "size_mm": [20, 40, 20]}
        for key in ("sensor", "unrelated")],
        "steps": [{"name": "Read sample", "instruction": "Read the sensor.",
                   "component_keys": ["sensor"]}]}}
    for sid in ("concept-sensor", "concept-step-1", "assembly-1"):
        context = step_context(project, sid)
        assert context["component_ids"] == ["sensor"]
        assert "unrelated" not in step_prompt(context)
        assert schematic_reference(context).width == 1024
    for sid in ("concept-unknown", "concept-step-0", "concept-step-01", "concept-step-99"):
        with pytest.raises(illustration.IllustrationError) as caught:
            step_context(project, sid)
        assert caught.value.status_code == 404


def test_step_illustration_rejects_revision_change_and_keeps_project(monkeypatch):
    async def generate(project, reference, *, prompt):
        api._sessions[project["id"]].project["revision"] += 1
        return {"image_data_url": data_url()}

    monkeypatch.setattr(api, "generate_illustration", generate)
    with TestClient(api.app) as client:
        project, _ = seed()
        from app.instructions import build_instruction_guide
        step = next(s for s in build_instruction_guide(project)["assembly_steps"]
                    if s["component_ids"])
        response = client.post(f"/api/projects/{project['id']}/instructions/illustration",
                               json={"project_revision": project["revision"],
                                     "step_id": step["id"]})
        assert response.status_code == 409
        assert "image_data_url" not in project


def test_step_illustration_offline_and_provider_failure(monkeypatch):
    async def unavailable(**kwargs):
        return {"ids": [], "reason": "Offline synthetic test", "verified": False}

    async def fail(*args, **kwargs):
        raise illustration.IllustrationError(504, "Synthetic timeout")

    monkeypatch.setattr(api, "generate_illustration", fail)
    with TestClient(api.app) as client:
        project, _ = seed()
        from app.instructions import build_instruction_guide
        step = next(s for s in build_instruction_guide(project)["assembly_steps"]
                    if s["component_ids"])
        path = f"/api/projects/{project['id']}/instructions/illustration"
        body = {"project_revision": project["revision"], "step_id": step["id"]}
        before = deepcopy(project)
        assert client.post(path, json=body).status_code == 504
        monkeypatch.setattr(api, "discover_catalog", unavailable)
        assert client.post(path, json=body).status_code == 503
        assert project == before



def test_step_prompt_uses_existing_official_transport_and_pins():
    from app.step_illustration import schematic_reference, step_prompt
    context = {"step_id": "assembly-1", "step_title": "Fit sensor", "instructions": ["Fit sensor"],
               "parts": [{"component_id": "sensor", "position_mm": [0, 10, 0],
                          "size_mm": [20, 20, 20]}], "sources": [], "component_ids": ["sensor"]}
    reference = schematic_reference(context)
    prompt = step_prompt(context)

    async def handler(request):
        payload = json.loads(await request.aread())
        assert str(request.url) == "https://api.meta.ai/v1/responses"
        assert payload["model"] == catalog.IMAGE_MODEL
        assert payload["input"][0]["content"][0]["text"] == prompt
        assert payload["tools"] == [illustration.TOOL]
        assert payload["store"] is False
        return httpx.Response(200, json=provider_body())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await illustration.generate_illustration(
                layout_project(), reference, prompt=prompt, settings=SETTINGS, client=client)

    assert asyncio.run(run())["model"] == catalog.IMAGE_MODEL



def test_instruction_only_step_generates_grounded_checklist(monkeypatch):
    import app.instructions as instructions
    from app.step_illustration import schematic_reference, step_context, step_prompt

    title, action = "Review supplier guide", "Read the linked setup guide before powering on."
    source = {"title": "Original setup guide", "url": "https://example.test/original-guide"}
    guide = {"parts": [], "assembly_steps": [
        {"id": "assembly-1", "title": title, "instructions": [action],
         "component_ids": [], "sources": [source]}]}
    monkeypatch.setattr(instructions, "build_instruction_guide", lambda project: guide)
    project, _ = seed()
    context = step_context(project, "assembly-1")
    assert context["input_kind"] == "instruction_checklist"
    assert context["parts"] == []
    assert schematic_reference(context).width == 1200
    prompt = step_prompt(context)
    assert title in prompt and action in prompt and "text-only" in prompt
    assert source["url"] in prompt
    calls = []

    async def generate(project, reference, *, prompt):
        calls.append(prompt)
        return {"project_id": project["id"], "project_revision": project["revision"],
                "image_data_url": data_url()}

    monkeypatch.setattr(api, "generate_illustration", generate)
    path = f"/api/projects/{project['id']}/instructions/illustration"
    body = {"project_revision": project["revision"], "step_id": "assembly-1"}
    with TestClient(api.app) as client:
        response = client.post(path, json=body)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["input_kind"] == "instruction_checklist"
        assert result["sources"] == [source]
        assert result["component_ids"] == []
        assert "no equipment geometry" in result["reference_scope"]
        project["revision"] += 1
        assert client.post(path, json=body).status_code == 409
        another, _ = seed()
        other_path = f"/api/projects/{another['id']}/instructions/illustration"
        monkeypatch.setattr(instructions, "build_instruction_guide",
                            lambda project: {"parts": [], "assembly_steps": []})
        assert client.post(other_path, json={**body, "project_revision": another["revision"]}
                           ).status_code == 404
    assert len(calls) == 1


def test_step_with_unavailable_geometry_uses_text_only_without_inventing_parts():
    from app.step_illustration import schematic_reference, step_context, step_prompt
    project = {"concept_design": {"components": [
        {"key": "control", "name": "Controller", "assembly": "Review controller setup.",
         "position_mm": [0, 0, 0], "size_mm": [0, 0, 0]}]}}
    context = step_context(project, "concept-control")
    assert context["input_kind"] == "instruction_checklist"
    assert schematic_reference(context).width == 1200
    assert '"parts"' not in step_prompt(context)
    assert "Do not add procedures" in step_prompt(context)



def test_plate_step_reference_preserves_wells_holder_and_a1():
    from test_microplates import before, select

    from app.instructions import build_instruction_guide
    from app.step_illustration import (
        reference_shapes,
        schematic_reference,
        step_context,
        step_prompt,
    )

    project = select(before())
    step = next(s for s in build_instruction_guide(project)["assembly_steps"]
                if s["title"] == "Fit the plate and its holder")
    context = step_context(project, step["id"])
    assert context["component_ids"] == [project["labware_plate"]["target_component_id"]]
    assert context["input_kind"] == "canonical_primitives"
    shapes = reference_shapes(context)
    assert len([shape for shape in shapes if shape["kind"] == "hole"]) == 96
    assert {shape["id"] for shape in shapes if shape["id"].startswith("holder-")} == {
        "holder-floor", "holder-left", "holder-right", "holder-front", "holder-back"}
    assert any(shape["id"] == "reference-plate-bottom" for shape in shapes)
    assert any(shape["id"] == "A1" and shape["kind"] == "marker" for shape in shapes)
    actual = schematic_reference(context)
    envelope_context = deepcopy(context)
    envelope_context["parts"][0]["primitives"] = []
    envelope_context["parts"][0]["orientation_markers"] = []
    assert actual.sha256 != schematic_reference(envelope_context).sha256
    assert "never merge holder and plate into one box" in step_prompt(context)
    assert "reference-plate-wells" in step_prompt(context)
