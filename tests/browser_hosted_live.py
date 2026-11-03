"""Real built hosted app over temporary local HTTPS; no provider traffic or credentials.

Run after ``npm run build --prefix web``. Requires Chrome and OpenSSL (Git for
Windows includes it). Authentication, SQLite storage, Secure cookies, ASGI routes,
process restart and compiled React are real. The isolated server blocks outbound
network access; no model generation or production service is involved.
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def serve(port, certificate, private_key):
    import httpx
    import uvicorn

    async def offline_send(self, request, **kwargs):
        raise httpx.ConnectError(
            "Outbound network disabled by isolated browser test", request=request
        )

    original_connect = socket.socket.connect

    def offline_connect(self, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(self, address)
        raise OSError("Outbound network disabled by isolated browser test")

    httpx.AsyncClient.send = offline_send
    socket.socket.connect = offline_connect
    from app.hosted import create_app

    uvicorn.run(
        create_app(),
        host="127.0.0.1",
        port=port,
        ssl_certfile=certificate,
        ssl_keyfile=private_key,
        log_level="warning",
    )


def free_port():
    with socket.socket() as stream:
        stream.bind(("127.0.0.1", 0))
        return stream.getsockname()[1]


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def run():
    from playwright.sync_api import expect, sync_playwright

    from app.host_auth import COOKIE, hash_password

    if not (ROOT / "web/dist/index.html").is_file():
        raise RuntimeError("Build the website first: npm run build --prefix web")
    openssl = shutil.which("openssl")
    if not openssl:
        candidate = (
            Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/usr/bin/openssl.exe"
        )
        openssl = str(candidate) if candidate.is_file() else None
    if not openssl:
        raise RuntimeError("OpenSSL is required to create an ephemeral local TLS certificate.")
    port = free_port()
    origin = f"https://127.0.0.1:{port}"
    username, password, secret = (secrets.token_urlsafe(32) for _ in range(3))
    with tempfile.TemporaryDirectory(prefix="museautolab-hosted-browser-") as temporary:
        directory = Path(temporary)
        certificate, private_key = directory / "certificate.pem", directory / "private.pem"
        subprocess.run(
            [
                openssl,
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-keyout",
                str(private_key),
                "-out",
                str(certificate),
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=IP:127.0.0.1,DNS:localhost",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        environment = dict(os.environ)
        for name in tuple(environment):
            if name.startswith(("MUSEAUTOLAB_", "MODEL_", "META_API_")):
                environment.pop(name)
        environment.update(
            {
                "PYTHONPATH": str(ROOT),
                "MUSEAUTOLAB_HOSTED": "1",
                "MUSEAUTOLAB_DATABASE_PATH": str(directory / "projects.sqlite3"),
                "MUSEAUTOLAB_AUTH_SESSION_DIRECTORY": str(directory / "sessions"),
                "MUSEAUTOLAB_AUTH_ORIGIN": origin,
                "MUSEAUTOLAB_AUTH_USERNAME": username,
                "MUSEAUTOLAB_AUTH_PASSWORD_HASH": hash_password(password),
                "MUSEAUTOLAB_AUTH_SIGNING_SECRET": secret,
                "MODEL_API_KEY": secrets.token_urlsafe(32),
            }
        )
        process = None
        flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        with tempfile.TemporaryFile() as log:

            def start():
                process = subprocess.Popen(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--serve",
                        "--port",
                        str(port),
                        "--certificate",
                        str(certificate),
                        "--private-key",
                        str(private_key),
                    ],
                    cwd=ROOT,
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    creationflags=flags,
                )
                deadline = time.monotonic() + 40
                context = ssl._create_unverified_context()
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        log.seek(0)
                        detail = log.read().decode("utf-8", errors="replace")[-3000:]
                        raise RuntimeError("The isolated hosted server failed to start:\n" + detail)
                    try:
                        with urllib.request.urlopen(
                            origin + "/healthz", context=context, timeout=1
                        ):
                            return process
                    except OSError:
                        time.sleep(0.1)
                stop(process)
                raise RuntimeError("The isolated hosted server did not become ready.")

            try:
                process = start()
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(channel="chrome", headless=True)
                    context = browser.new_context(
                        ignore_https_errors=True, viewport={"width": 1440, "height": 1000}
                    )
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))

                    def api(path, body=None):
                        return page.evaluate(
                            """async ({path, body}) => {
                          const response = await fetch(path, body === null ? {} : {
                            method:'POST', headers:{'Content-Type':'application/json'},
                            body: JSON.stringify(body)
                          });
                          return {status:response.status, data:await response.json()};
                        }""",
                            {"path": path, "body": body},
                        )

                    def login():
                        page.get_by_label("Username", exact=True).fill(username)
                        page.get_by_label("Password", exact=True).fill(password)
                        page.get_by_role("button", name="Sign in", exact=True).click()
                        expect(page.locator(".connection-dot.connected")).to_be_visible()

                    page.goto(origin, wait_until="networkidle")
                    expect(page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
                    assert api("/api/library")["status"] == 401
                    login()
                    cookie = next(item for item in context.cookies() if item["name"] == COOKIE)
                    assert (
                        cookie["httpOnly"] and cookie["secure"] and cookie["sameSite"] == "Strict"
                    )
                    status = api("/api/auth/status")["data"]
                    project_id = page.evaluate(
                        "key => sessionStorage.getItem(key)",
                        f"museautolab.hosted.{status['account']}",
                    )
                    original = api(f"/api/projects/{project_id}")["data"]["project"]
                    page.get_by_role("button", name="Save project", exact=True).click()
                    page.get_by_label("Project name", exact=True).fill("Synthetic hosted station")
                    page.get_by_role("dialog").get_by_role("button", name="Save project").click()
                    expect(page.locator(".topbar-center")).to_contain_text(
                        "Synthetic hosted station"
                    )
                    edited = api(
                        f"/api/projects/{project_id}/configuration", {"cooling_enabled": True}
                    )
                    assert edited["status"] == 200
                    revision = edited["data"]["project"]["revision"]
                    assert revision > original["revision"]
                    assert edited["data"]["project"]["summary"]["cooling_enabled"] is True
                    page.reload(wait_until="networkidle")
                    expect(page.locator(".topbar-center")).to_contain_text(
                        "Synthetic hosted station"
                    )
                    page.get_by_role("button", name="New project", exact=True).click()
                    expect(page.locator(".topbar-center")).not_to_contain_text(
                        "Synthetic hosted station"
                    )
                    page.get_by_role("button", name="Projects", exact=True).click()
                    expect(page.get_by_role("dialog")).to_contain_text(f"Revision {revision}")
                    page.get_by_role(
                        "button", name="Open Synthetic hosted station", exact=True
                    ).click()
                    expect(page.locator(".topbar-center")).to_contain_text(
                        "Synthetic hosted station"
                    )
                    assert (
                        api(f"/api/projects/{project_id}")["data"]["project"]
                        == edited["data"]["project"]
                    )
                    # Stop the actual writer process; keep Chrome, tab, cookies and tab storage.
                    stop(process)
                    process = start()
                    page.reload(wait_until="networkidle")
                    expect(page.locator(".connection-dot.connected")).to_be_visible()
                    expect(page.locator(".topbar-center")).to_contain_text(
                        "Synthetic hosted station"
                    )
                    resumed = api(f"/api/projects/{project_id}")["data"]
                    assert resumed["project"] == edited["data"]["project"]
                    assert resumed["title"] == "Synthetic hosted station"
                    page.get_by_role("button", name="Projects", exact=True).click()
                    expect(page.get_by_role("dialog")).to_contain_text(f"Revision {revision}")
                    page.keyboard.press("Escape")
                    page.get_by_role("button", name="Sign out", exact=True).click()
                    page.get_by_role("dialog").get_by_role("button", name="Sign out").click()
                    expect(page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
                    assert api("/api/library")["status"] == 401
                    login()
                    expect(page.locator(".topbar-center")).to_contain_text(
                        "Synthetic hosted station"
                    )
                    assert (
                        api(f"/api/projects/{project_id}")["data"]["project"]["revision"]
                        == revision
                    )
                    assert errors == [], errors
                    browser.close()
                print("Hosted HTTPS browser passed: real auth, edit, autosave, restart, logout.")
            finally:
                stop(process)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int)
    parser.add_argument("--certificate")
    parser.add_argument("--private-key")
    args = parser.parse_args()
    if args.serve:
        serve(args.port, args.certificate, args.private_key)
    else:
        run()
