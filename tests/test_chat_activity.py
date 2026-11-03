import asyncio

import httpx
from fastapi import Depends, FastAPI

from app.chat_activity import (
    _activities,
    _current,
    activity_dependency,
    install_activity,
    report_activity,
)


def test_activity_tracks_real_operation_and_isolates_requests():
    async def run():
        app = FastAPI()
        started = asyncio.Event()
        finish = asyncio.Event()

        @app.post(
            "/api/projects/{project_id}/messages",
            dependencies=[Depends(activity_dependency(lambda project_id: None))],
        )
        async def message(project_id: str):
            report_activity("interpreting")
            started.set()
            await finish.wait()
            return {"project": project_id}

        install_activity(app)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            request_id = "request-unique-12345"
            post = asyncio.create_task(
                client.post("/api/projects/one/messages", headers={"X-Chat-Request-Id": request_id})
            )
            await started.wait()
            url = f"/api/projects/one/activity/{request_id}"
            assert (await client.get(url)).json() == {"active": True, "stage": "interpreting"}
            assert (await client.get(url.replace("/one/", "/two/"))).status_code == 404
            assert (await client.get(url + "-other")).status_code == 404
            duplicate = await client.post(
                "/api/projects/one/messages", headers={"X-Chat-Request-Id": request_id}
            )
            assert duplicate.status_code == 409
            finish.set()
            assert (await post).status_code == 200
            assert (await client.get(url)).json()["active"] is False

    asyncio.run(run())


def test_failed_operation_finishes_activity_and_resets_context():
    async def run():
        app = FastAPI()

        @app.post(
            "/api/projects/{project_id}/concept",
            dependencies=[Depends(activity_dependency(lambda project_id: None))],
        )
        async def concept(project_id: str):
            report_activity("assembling")
            raise ValueError("test failure")

        install_activity(app)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            key = ("error-project", "request-error-12345")
            response = await client.post(
                "/api/projects/error-project/concept", headers={"X-Chat-Request-Id": key[1]}
            )
            assert response.status_code == 500
            assert _activities[key]["active"] is False
            report_activity("interpreting")
            assert _activities[key]["stage"] == "assembling"

    asyncio.run(run())


def test_cancelled_request_clears_active_state():
    async def run():
        app = FastAPI()
        started = asyncio.Event()

        @app.post(
            "/api/projects/{project_id}/messages",
            dependencies=[Depends(activity_dependency(lambda project_id: None))],
        )
        async def message(project_id: str):
            report_activity("interpreting")
            started.set()
            await asyncio.Event().wait()

        install_activity(app)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            key = ("cancel-project", "request-cancel-12345")
            post = asyncio.create_task(
                client.post(
                    "/api/projects/cancel-project/messages", headers={"X-Chat-Request-Id": key[1]}
                )
            )
            await started.wait()
            post.cancel()
            try:
                await post
            except asyncio.CancelledError:
                pass
            assert _activities[key]["active"] is False

    asyncio.run(run())


def test_sourcing_reports_only_uncached_io_and_restores_prior_stage(monkeypatch):
    from app import platform_research

    async def run():
        key = ("source-project", "request-sources-12345")
        _activities[key] = {"stage": "interpreting", "active": True}
        token = _current.set(key)
        monkeypatch.setattr(platform_research, "_cache", {})
        reads = []

        async def read(platform, url, client):
            reads.append(platform)
            assert _activities[key]["stage"] == "sourcing"
            return {"amount": 100, "retrieved_at": "synthetic"}

        monkeypatch.setattr(platform_research, "_read", read)
        try:
            await platform_research.refresh_platform_prices()
            assert reads
            assert _activities[key]["stage"] == "interpreting"
            reads.clear()
            await platform_research.refresh_platform_prices()
            assert not reads
            assert _activities[key]["stage"] == "interpreting"
        finally:
            _current.reset(token)

    asyncio.run(run())


def test_host_auth_precedes_allocation_and_polling(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.host_auth import HostAuth

    app = FastAPI()
    validations = []
    dependency = activity_dependency(lambda project_id: validations.append(project_id))

    @app.post("/api/projects/{project_id}/messages", dependencies=[Depends(dependency)])
    async def message(project_id: str):
        return {"ok": True}

    app.add_middleware(
        HostAuth,
        origin="https://testserver",
        username="test",
        password_hash="unused",
        secret="test-secret",
        session_directory=str(tmp_path),
    )
    install_activity(app)
    key = ("auth-project", "request-auth-test-12345")
    _activities[key] = {
        "stage": "waiting",
        "active": False,
        "updated": __import__("time").monotonic(),
    }
    client = TestClient(app, base_url="https://testserver")
    before = dict(_activities)
    for request_id in (key[1], "request-anonymous-12345"):
        response = client.post(
            "/api/projects/auth-project/messages",
            headers={"X-Chat-Request-Id": request_id, "Origin": "https://testserver"},
        )
        assert response.status_code == 401
    assert client.get(f"/api/projects/{key[0]}/activity/{key[1]}").status_code == 401
    assert not validations
    assert _activities == before


def test_expired_id_can_be_reused_and_polling_avoids_storage(monkeypatch):
    from fastapi.testclient import TestClient

    import app.chat_activity as module

    app = FastAPI()
    validations = []
    dependency = activity_dependency(lambda project_id: validations.append(project_id))

    @app.post("/api/projects/{project_id}/messages", dependencies=[Depends(dependency)])
    async def message(project_id: str):
        return {"ok": True}

    install_activity(app)
    monkeypatch.setattr(module, "_activities", {})
    monkeypatch.setattr(module, "MAX_ACTIVITIES", 2)
    clock = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    client = TestClient(app)
    url = "/api/projects/expiry-project/messages"
    headers = {"X-Chat-Request-Id": "request-expiry-12345"}
    assert client.post(url, headers=headers).status_code == 200
    validations.clear()
    poll = "/api/projects/expiry-project/activity/request-expiry-12345"
    assert client.get(poll).status_code == 200
    assert not validations
    clock[0] += 61
    assert client.get(poll).status_code == 404
    assert client.post(url, headers=headers).status_code == 200
    for number in range(4):
        assert (
            client.post(
                url, headers={"X-Chat-Request-Id": f"request-bounded-{number:05d}"}
            ).status_code
            == 200
        )
        assert len(module._activities) <= 2


def test_other_streaming_routes_are_untouched():
    from fastapi.testclient import TestClient
    from starlette.responses import StreamingResponse

    app = FastAPI()
    chunks = []

    @app.get("/download")
    async def download():
        async def body():
            chunks.append("first")
            yield b"first"
            await asyncio.sleep(0)
            chunks.append("second")
            yield b"second"

        return StreamingResponse(body())

    install_activity(app)
    assert not app.user_middleware
    before = dict(_activities)
    response = TestClient(app).get("/download")
    assert response.content == b"firstsecond"
    assert chunks == ["first", "second"]
    assert _activities == before
