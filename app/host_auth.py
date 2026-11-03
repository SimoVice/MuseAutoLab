"""Opt-in single-account access boundary for a small hosted deployment.

Use one writer worker. Session digests persist in private server storage.
No account information belongs in product source or public configuration.
"""

import hashlib
import hmac
import json
import os
import secrets
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import JSONResponse

COOKIE = "__Host-museautolab-session"
SESSION_SECONDS = 8 * 3600
MAX_LOGIN_BYTES = 4096


def hash_password(password: str) -> str:
    """Create a salted password verifier; store the result only in server secrets."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def _valid_hash(value: str) -> bool:
    try:
        kind, n, r, p, salt, digest = value.split("$")
        return (kind, n, r, p) == ("scrypt", "16384", "8", "1") and (
            len(bytes.fromhex(salt)) == 16 and len(bytes.fromhex(digest)) == 64
        )
    except (ValueError, TypeError):
        return False


def _verify(password: str, encoded: str) -> bool:
    _, _, _, _, salt, expected = encoded.split("$")
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return hmac.compare_digest(actual.hex(), expected)


class HostAuth:
    def __init__(
        self,
        app,
        *,
        origin: str,
        username: str,
        password_hash: str,
        secret: str,
        session_directory: str,
    ):
        self.app = app
        self.origin = origin
        self.username = username
        self.password_hash = password_hash
        self.secret = secret.encode()
        self.session_directory = Path(session_directory).expanduser().resolve()
        self.session_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.failures: list[float] = []
        self.pending_commit = False

    def _commit(self):
        if self.pending_commit:
            from app.project_library import _commit_volume

            _commit_volume()
            self.pending_commit = False

    def _session_path(self, token):
        return self.session_directory / (hashlib.sha256(token.encode()).hexdigest() + ".session")

    def _sync_directory(self):
        if os.name != "nt":
            descriptor = os.open(self.session_directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def _save_session(self, token):
        # Only a digest is used as a filename; credentials and bearer tokens are never stored.
        path = self._session_path(token)
        temporary = path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            stream.write(token.split(".")[0])
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        self._sync_directory()
        self.pending_commit = True
        self._commit()

    def _revoke_session(self, token):
        self._session_path(token).unlink(missing_ok=True)
        self._sync_directory()
        self.pending_commit = True
        self._commit()

    def _token(self) -> str:
        payload = f"{int(time.time()) + SESSION_SECONDS}.{secrets.token_hex(24)}"
        signature = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()
        return f"{payload}.{signature}"

    def _authenticated(self, token: str) -> bool:
        now = time.time()
        try:
            self._commit()
            expiry, nonce, signature = token.split(".")
            payload = f"{expiry}.{nonce}"
            expected = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()
            return (
                now < int(expiry) <= now + SESSION_SECONDS
                and len(nonce) == 48
                and hmac.compare_digest(signature, expected)
                and self._session_path(token).is_file()
            )
        except (ValueError, TypeError, OSError, RuntimeError):
            return False

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if scope["type"] == "http" and not (path == "/api" or path.startswith("/api/")):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get(b"cookie", b"").decode("latin1"))
            token = cookie[COOKIE].value if COOKIE in cookie else ""
        except Exception:
            token = ""
        authenticated = self._authenticated(token)
        same_origin = headers.get(b"origin", b"").decode("latin1") == self.origin
        if scope["type"] == "websocket":
            if not authenticated or not same_origin:
                return await send({"type": "websocket.close", "code": 1008})
            return await self.app(scope, receive, send)

        async def reply(status, detail):
            response = JSONResponse(
                detail, status_code=status, headers={"Cache-Control": "no-store"}
            )
            await response(scope, receive, send)

        method = scope["method"]
        if method not in {"GET", "HEAD", "OPTIONS"} and not same_origin:
            return await reply(403, {"detail": "A same-origin request is required."})
        if path == "/api/auth/status" and method == "GET":
            account = hmac.new(self.secret, self.username.encode(), hashlib.sha256).hexdigest()
            return await reply(
                200,
                {
                    "enabled": True,
                    "authenticated": authenticated,
                    "account": account if authenticated else None,
                },
            )
        if path == "/api/auth/login" and method == "POST":
            now = time.time()
            self.failures = [stamp for stamp in self.failures if stamp > now - 300]
            if len(self.failures) >= 5:
                return await reply(429, {"detail": "Too many attempts. Try again later."})
            # Reserve before awaiting input so concurrent attempts cannot bypass the limit.
            self.failures.append(now)
            body = bytearray()
            while True:
                event = await receive()
                if event["type"] != "http.request":
                    return await reply(400, {"detail": "Invalid sign-in request."})
                body.extend(event.get("body", b""))
                if len(body) > MAX_LOGIN_BYTES:
                    return await reply(413, {"detail": "Sign-in request is too large."})
                if not event.get("more_body"):
                    break
            try:
                data = json.loads(body)
                username, password = data["username"], data["password"]
                if not isinstance(username, str) or not isinstance(password, str):
                    raise ValueError
                submitted_name = username.encode()
                valid_password = _verify(password, self.password_hash)
            except (ValueError, KeyError, TypeError):
                return await reply(400, {"detail": "Invalid sign-in request."})
            if not (
                hmac.compare_digest(submitted_name, self.username.encode()) and valid_password
            ):
                return await reply(401, {"detail": "Invalid sign-in details."})
            if now in self.failures:
                self.failures.remove(now)
            session_token = self._token()
            try:
                self._save_session(session_token)
            except Exception:
                return await reply(503, {"detail": "Sign-in storage is unavailable."})
            response = JSONResponse({"authenticated": True}, headers={"Cache-Control": "no-store"})
            response.set_cookie(
                COOKIE,
                session_token,
                max_age=SESSION_SECONDS,
                secure=True,
                httponly=True,
                samesite="strict",
                path="/",
            )
            return await response(scope, receive, send)
        if not authenticated:
            return await reply(401, {"detail": "Sign in to continue."})
        if path == "/api/auth/logout" and method == "POST":
            try:
                self._revoke_session(token)
            except Exception:
                return await reply(503, {"detail": "Sign-out storage is unavailable."})
            response = JSONResponse({"authenticated": False}, headers={"Cache-Control": "no-store"})
            response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="strict")
            return await response(scope, receive, send)

        async def private_send(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                message["headers"] = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"cache-control"
                ] + [(b"cache-control", b"no-store")]
            await send(message)

        return await self.app(scope, receive, private_send)


def install_host_auth(app: FastAPI) -> None:
    """Install before serving. Invalid hosted configuration aborts startup."""
    mode = os.environ.get("MUSEAUTOLAB_HOSTED", "0")
    if mode not in {"0", "1"}:
        raise RuntimeError("MUSEAUTOLAB_HOSTED must be 0 or 1.")
    if mode == "0":

        @app.get("/api/auth/status")
        async def local_auth_status():
            return {"enabled": False, "authenticated": True}

        return
    origin = os.environ.get("MUSEAUTOLAB_AUTH_ORIGIN", "")
    username = os.environ.get("MUSEAUTOLAB_AUTH_USERNAME", "")
    verifier = os.environ.get("MUSEAUTOLAB_AUTH_PASSWORD_HASH", "")
    secret = os.environ.get("MUSEAUTOLAB_AUTH_SIGNING_SECRET", "")
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or not username
        or not _valid_hash(verifier)
        or len(secret) < 32
    ):
        raise RuntimeError("Hosted authentication requires valid server-only configuration.")
    session_directory = os.environ.get("MUSEAUTOLAB_AUTH_SESSION_DIRECTORY", "").strip()
    if not session_directory:
        storage = (
            os.environ.get("MUSEAUTOLAB_LIBRARY_DIRECTORY", "").strip()
            or os.environ.get("MUSEAUTOLAB_DATABASE_PATH", "").strip()
        )
        if not storage:
            raise RuntimeError("Hosted authentication requires private persistent session storage.")
        session_directory = str(Path(storage).expanduser().resolve().parent / "auth_sessions")
    app.add_middleware(
        HostAuth,
        origin=origin,
        username=username,
        password_hash=verifier,
        secret=secret,
        session_directory=session_directory,
    )
