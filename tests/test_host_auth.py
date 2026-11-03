import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from app.host_auth import COOKIE, hash_password, install_host_auth


@pytest.fixture
def hosted(monkeypatch, tmp_path):
    monkeypatch.setenv("MUSEAUTOLAB_AUTH_SESSION_DIRECTORY", str(tmp_path / "auth"))
    monkeypatch.setenv("MUSEAUTOLAB_HOSTED", "1")
    monkeypatch.setenv("MUSEAUTOLAB_AUTH_ORIGIN", "https://testserver")
    monkeypatch.setenv("MUSEAUTOLAB_AUTH_USERNAME", "test-account")
    monkeypatch.setenv("MUSEAUTOLAB_AUTH_PASSWORD_HASH", hash_password("test-password"))
    monkeypatch.setenv("MUSEAUTOLAB_AUTH_SIGNING_SECRET", "test-only-signing-material-" * 2)
    app = FastAPI()
    install_host_auth(app)

    @app.get("/api/download")
    @app.post("/api/expensive")
    def protected():
        return {"ok": True}

    @app.websocket("/socket")
    async def socket(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("ok")
        await websocket.close()

    return TestClient(app, base_url="https://testserver")


def login(client):
    return client.post(
        "/api/auth/login",
        json={"username": "test-account", "password": "test-password"},
        headers={"Origin": "https://testserver"},
    )


def test_default_local(monkeypatch):
    monkeypatch.delenv("MUSEAUTOLAB_HOSTED", raising=False)
    app = FastAPI()
    install_host_auth(app)
    assert TestClient(app).get("/api/auth/status").json() == {
        "enabled": False,
        "authenticated": True,
    }


def test_hosted_fails_closed(monkeypatch):
    monkeypatch.setenv("MUSEAUTOLAB_HOSTED", "1")
    monkeypatch.delenv("MUSEAUTOLAB_AUTH_ORIGIN", raising=False)
    with pytest.raises(RuntimeError):
        install_host_auth(FastAPI())


def test_access_cookie_and_logout_revocation(hosted):
    assert hosted.get("/api/download").status_code == 401
    response = login(hosted)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    token = hosted.cookies.get(COOKIE)
    assert hosted.get("/api/download").status_code == 200
    assert hosted.post("/api/expensive").status_code == 403
    assert hosted.post("/api/expensive", headers={"Origin": "https://evil.test"}).status_code == 403
    assert (
        hosted.post("/api/expensive", headers={"Origin": "https://testserver"}).status_code == 200
    )
    assert (
        hosted.post("/api/auth/logout", headers={"Origin": "https://testserver"}).status_code == 200
    )
    hosted.cookies.set(COOKIE, token)
    assert hosted.get("/api/download").status_code == 401


def test_throttles_across_clients_without_trusting_forwarded_ip(hosted):
    for _ in range(5):
        response = hosted.post(
            "/api/auth/login",
            json={"username": "x", "password": "x"},
            headers={"Origin": "https://testserver", "X-Forwarded-For": "different"},
        )
        assert response.status_code == 401
    assert login(hosted).status_code == 429


def test_login_origin_body_and_tampering(hosted):
    assert hosted.post("/api/auth/login", json={}).status_code == 403
    assert (
        hosted.post(
            "/api/auth/login", content="x" * 5000, headers={"Origin": "https://testserver"}
        ).status_code
        == 413
    )
    login(hosted)
    token = hosted.cookies.get(COOKIE)
    hosted.cookies.clear()
    hosted.cookies.set(COOKIE, token + "x")
    assert hosted.get("/api/download").status_code == 401


def test_websocket_boundary(hosted):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with hosted.websocket_connect("/socket"):
            pass
    login(hosted)
    with pytest.raises(WebSocketDisconnect):
        with hosted.websocket_connect("/socket", headers={"Origin": "https://evil.test"}):
            pass
    with hosted.websocket_connect(
        "wss://testserver/socket", headers={"Origin": "https://testserver"}
    ) as socket:
        assert socket.receive_text() == "ok"


def test_expiry_restart_and_hash_salts(tmp_path):
    from unittest.mock import patch

    from app.host_auth import HostAuth

    first_hash = hash_password("same-password")
    assert first_hash != hash_password("same-password")
    kwargs = dict(
        origin="https://testserver",
        username="test-account",
        password_hash=first_hash,
        secret="test-only-material-" * 3,
        session_directory=str(tmp_path),
    )
    first = HostAuth(None, **kwargs)
    token = first._token()
    first._save_session(token)
    assert first._authenticated(token)
    restarted = HostAuth(None, **kwargs)
    assert restarted._authenticated(token)
    with patch("app.host_auth.time.time", return_value=int(token.split(".")[0]) + 1):
        assert not first._authenticated(token)
    restarted._revoke_session(token)
    assert not HostAuth(None, **kwargs)._authenticated(token)


def test_successful_signins_do_not_consume_failed_attempt_budget(hosted):
    for _ in range(7):
        assert login(hosted).status_code == 200


def test_auth_storage_acknowledges_only_committed_changes(hosted, monkeypatch):
    from app import project_library

    calls = []
    monkeypatch.setattr(project_library, "_commit_volume", lambda: calls.append("commit"))
    assert login(hosted).status_code == 200
    assert calls == ["commit"]
    assert hosted.get("/api/download").status_code == 200
    assert calls == ["commit"]
    assert (
        hosted.post("/api/auth/logout", headers={"Origin": "https://testserver"}).status_code == 200
    )
    assert calls == ["commit", "commit"]


def test_login_storage_failure_never_sets_cookie(hosted, monkeypatch):
    from app import project_library

    def fail():
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(project_library, "_commit_volume", fail)
    response = login(hosted)
    assert response.status_code == 503
    assert "set-cookie" not in response.headers
