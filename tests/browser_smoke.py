"""Reusable local browser harness; default flow is browser_foundation.

The Meta transports are offline fixtures. Backend, compiler, source meshes,
portable state and Chrome are real. No physical validation is implied.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STUB_SERVER = ROOT / "tests" / "browser_foundation_server.py"
WEB_DIR = ROOT / "web"
VITE_BIN = WEB_DIR / "node_modules" / "vite" / "bin" / "vite.js"

# Synthetic English inputs. These exact strings are the only messages the
# stub server understands (matched on the distinctive "10 mg/mL" content and
# on "450/300/650 mm" width numbers).
COMPLETE_TASK_MESSAGE = (
    "I need to prepare aliquots from a 10mg/ml stock to a 1mg/ml target, "
    "with 1ml in each tube. I have a pipette and microcentrifuge tubes."
)
WIDTH_450_MESSAGE = "Please limit the workspace width to 450 mm for this synthetic concept."
WIDTH_300_MESSAGE = "Please limit the workspace width to 300 mm for this synthetic concept."
WIDTH_650_MESSAGE = "Please limit the workspace width to 650 mm for this synthetic concept."

EXPECTED_STOCK = "10 mg/mL"
EXPECTED_TARGET = "1 mg/mL"
EXPECTED_VOLUME = "1 mL"
EXPECTED_EQUIPMENT = "pipette and microcentrifuge tubes"

BACKEND_TIMEOUT_S = 60.0
FRONTEND_TIMEOUT_S = 90.0
STEP_TIMEOUT_MS = 20_000


def log(message: str) -> None:
    print(f"[browser-smoke] {message}", flush=True)


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def creation_flags() -> int:
    # Keep Windows test runs quiet; absent on POSIX.
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def wait_for_http(url: str, timeout_s: float, label: str) -> None:
    deadline = time.monotonic() + timeout_s
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310
                if 200 <= response.status < 500:
                    return
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for {label} at {url}: {last_error}")


def wait_for_backend_health(api_base: str) -> None:
    deadline = time.monotonic() + BACKEND_TIMEOUT_S
    last_error = ""
    url = f"{api_base}/api/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310
                body = json.loads(response.read().decode("utf-8"))
                if body.get("status") == "ok":
                    return
                last_error = f"unexpected body {body!r}"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        time.sleep(0.25)
    raise TimeoutError(f"Backend did not become ready at {url}: {last_error}")


def stop_process(proc: subprocess.Popen | None, label: str) -> None:
    if proc is None or proc.poll() is not None:
        return
    log(f"Stopping {label} (pid {proc.pid})...")
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        log(f"{label} did not exit; killing.")
        proc.kill()
        proc.wait(timeout=10)
    except Exception as exc:  # noqa: BLE001
        log(f"Error while stopping {label}: {exc}")


def send_chat(page, message: str, expect_text: str) -> None:
    """Fill the composer, send, and wait for the expected assistant text."""
    from playwright.sync_api import expect

    composer = page.get_by_label("Describe your workflow or request a change")
    send_button = page.get_by_role("button", name="Send message")
    expect(composer).to_be_enabled(timeout=STEP_TIMEOUT_MS)
    composer.fill(message)
    expect(send_button).to_be_enabled(timeout=STEP_TIMEOUT_MS)
    send_button.click()
    expect(page.get_by_text(expect_text).first).to_be_visible(timeout=STEP_TIMEOUT_MS)
    expect(composer).to_be_enabled(timeout=STEP_TIMEOUT_MS)


def develop_layout(page) -> dict:
    """Request source-CAD development in the ordinary chat and await publication."""
    from playwright.sync_api import expect

    with page.expect_response(lambda response: response.url.endswith("/messages")) as result:
        send_chat(page, "Develop the workstation from the real CAD base.", "Checking")
    expect(page.locator(".viewer-canvas canvas")).to_have_count(1, timeout=STEP_TIMEOUT_MS)
    return result.value.json()


def run_smoke(web_url: str) -> None:
    from browser_foundation import run
    run(web_url)


def main() -> int:
    if not STUB_SERVER.exists():
        print(f"[browser-smoke] Missing stub server: {STUB_SERVER}", file=sys.stderr)
        return 1
    if not VITE_BIN.exists():
        print(f"[browser-smoke] Missing Vite binary: {VITE_BIN}", file=sys.stderr)
        return 1
    node_bin = shutil.which("node")
    if not node_bin:
        print("[browser-smoke] Node.js was not found on PATH.", file=sys.stderr)
        return 1

    api_port = find_free_port()
    web_port = find_free_port()
    # Avoid the unlikely collision from two sequential binds.
    while web_port == api_port:
        web_port = find_free_port()
    api_base = f"http://127.0.0.1:{api_port}"
    web_url = f"http://127.0.0.1:{web_port}/"

    backend_proc: subprocess.Popen | None = None
    frontend_proc: subprocess.Popen | None = None
    # Undrained PIPE logs can fill their Windows buffer and block the server loop.
    backend_log = tempfile.TemporaryFile()
    frontend_log = tempfile.TemporaryFile()
    try:
        log(f"Starting stubbed backend: {sys.executable} {STUB_SERVER} --port {api_port}")
        backend_proc = subprocess.Popen(
            [sys.executable, str(STUB_SERVER), "--host", "127.0.0.1", "--port", str(api_port)],
            cwd=str(ROOT),
            stdout=backend_log,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=creation_flags(),
        )
        wait_for_backend_health(api_base)
        log(f"Backend ready at {api_base} (AI provider stubbed).")

        env = dict(os.environ)
        env["MUSEAUTOLAB_API_TARGET"] = api_base
        log(f"Starting Vite frontend on {web_url} with MUSEAUTOLAB_API_TARGET={api_base}")
        frontend_proc = subprocess.Popen(
            [
                node_bin,
                str(VITE_BIN),
                "--host",
                "127.0.0.1",
                "--port",
                str(web_port),
                "--strictPort",
            ],
            cwd=str(WEB_DIR),
            env=env,
            stdout=frontend_log,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=creation_flags(),
        )
        wait_for_http(web_url, FRONTEND_TIMEOUT_S, "Vite frontend")
        log("Frontend is serving.")

        run_smoke(web_url)
        log("Browser smoke test passed (stubbed AI; no physical/WebGL-visual validation implied).")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[browser-smoke] FAILED: {exc}", file=sys.stderr)
        for label, output in (("backend", backend_log), ("frontend", frontend_log)):
            output.seek(0)
            tail = output.read().decode("utf-8", errors="replace")[-4000:]
            print(f"[browser-smoke] {label} log tail:\n{tail}", file=sys.stderr)
        return 1
    finally:
        stop_process(frontend_proc, "Vite frontend")
        stop_process(backend_proc, "stubbed backend")
        backend_log.close()
        frontend_log.close()


if __name__ == "__main__":
    raise SystemExit(main())
