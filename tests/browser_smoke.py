"""Repeatable end-to-end browser smoke test for the MuseAutoLab baseline.

What this test does:
* Starts the actual backend API locally via ``tests/browser_stub_server.py``
  (actual FastAPI + domain code; only the Meta model call is stubbed).
* Starts the actual frontend locally via Node + ``web/node_modules/vite/bin/vite.js``.
* Drives the UI with Playwright using a locally installed Chrome browser.
* Verifies dilution volumes, an impossible concentration and recovery, the
  initial 600x370 mm concept, width revisions and confirmation.
* Inspects one component through the accessible component list.
* Checks playback controls and that canvas pixels change during animation.
* Captures browser page errors and fails on unexpected errors.

What this test does NOT do:
* The AI provider is STUBBED (see ``browser_stub_server.py``). No Meta
  request or key is used; assistant replies are deterministic fakes.
* No physical, collision, dispensing, cost, or quantitative motion validation
  is implied by a change in rendered canvas pixels.
* No fixed screenshot or artifact files are created, except an optional
  screenshot saved only to the path supplied by MUSEAUTOLAB_BROWSER_SCREENSHOT.

Run (integrator machine, after copying both test files back):
    python tests/browser_smoke.py

Environment:
* PLAYWRIGHT_CHROME_PATH (optional): full path to a Chrome executable.
  When unset, Playwright uses channel="chrome".
* MUSEAUTOLAB_BROWSER_SCREENSHOT (optional): path for a final screenshot.
* The test binds only 127.0.0.1 and chooses free localhost ports.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STUB_SERVER = ROOT / "tests" / "browser_stub_server.py"
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
    # The API appends deterministic text (including backend domain suffixes
    # for width changes); wait for the key expected substring.
    expect(page.get_by_text(expect_text).first).to_be_visible(timeout=STEP_TIMEOUT_MS)
    # Wait until the composer is usable again before the next step.
    expect(composer).to_be_enabled(timeout=STEP_TIMEOUT_MS)


def run_smoke(web_url: str) -> None:
    from playwright.sync_api import expect, sync_playwright

    chrome_path = os.environ.get("PLAYWRIGHT_CHROME_PATH", "").strip()
    page_errors: list[str] = []

    with sync_playwright() as playwright:
        if chrome_path:
            if not Path(chrome_path).exists():
                raise FileNotFoundError(f"PLAYWRIGHT_CHROME_PATH does not exist: {chrome_path}")
            log(f"Launching browser from PLAYWRIGHT_CHROME_PATH={chrome_path}")
            browser = playwright.chromium.launch(headless=True, executable_path=chrome_path)
        else:
            log('Launching browser with channel="chrome" (set PLAYWRIGHT_CHROME_PATH to override).')
            browser = playwright.chromium.launch(headless=True, channel="chrome")
        try:
            page = browser.new_page()
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            log(f"Opening {web_url} (AI provider is stubbed; no Meta call occurs).")
            page.goto(web_url, wait_until="domcontentloaded", timeout=STEP_TIMEOUT_MS)

            # Initial state: project created, wide concept visible, canvas present.
            expect(page.get_by_text("Workspace ready")).to_be_visible(timeout=STEP_TIMEOUT_MS)
            footprint = page.locator(".footprint strong")
            expect(footprint).to_contain_text("600", timeout=STEP_TIMEOUT_MS)
            expect(footprint).to_contain_text("370", timeout=STEP_TIMEOUT_MS)
            expect(page.get_by_text("No width constraint yet")).to_be_visible(
                timeout=STEP_TIMEOUT_MS
            )
            # Presence only: this does not validate WebGL pixels or physical fit.
            expect(page.locator(".viewer-canvas canvas")).to_have_count(1, timeout=STEP_TIMEOUT_MS)
            log("Initial 600 x 370 mm concept and canvas are visible.")

            # Complete synthetic task: summary fields must be displayed.
            send_chat(page, COMPLETE_TASK_MESSAGE, EXPECTED_STOCK)
            summary = page.locator(".summary-card")
            expect(summary).to_contain_text(EXPECTED_STOCK, timeout=STEP_TIMEOUT_MS)
            expect(summary).to_contain_text(EXPECTED_TARGET, timeout=STEP_TIMEOUT_MS)
            expect(summary).to_contain_text(EXPECTED_VOLUME, timeout=STEP_TIMEOUT_MS)
            expect(summary).to_contain_text(EXPECTED_EQUIPMENT, timeout=STEP_TIMEOUT_MS)
            plan = page.locator(".plan-card")
            expect(plan).to_contain_text("100 µL", timeout=STEP_TIMEOUT_MS)
            expect(plan).to_contain_text("900 µL", timeout=STEP_TIMEOUT_MS)
            log("Complete synthetic task is reflected in the displayed summary.")

            send_chat(page, "Change the target to 20 mg/mL", "impossible target")
            expect(plan).to_contain_text("Needs attention", timeout=STEP_TIMEOUT_MS)
            page.get_by_role("button", name="Confirm design").click()
            expect(page.get_by_role("alert")).to_be_visible(timeout=STEP_TIMEOUT_MS)
            expect(page.locator(".chat-status")).to_contain_text("Draft")
            send_chat(page, COMPLETE_TASK_MESSAGE, EXPECTED_STOCK)
            expect(plan).to_contain_text("100 µL", timeout=STEP_TIMEOUT_MS)
            log("Impossible target is rejected; restoring the original target restores the plan.")

            # Feasible narrower width: compact 400 x 470 mm layout.
            send_chat(page, WIDTH_450_MESSAGE, "Within requested width")
            expect(footprint).to_contain_text("400", timeout=STEP_TIMEOUT_MS)
            expect(footprint).to_contain_text("470", timeout=STEP_TIMEOUT_MS)
            expect(page.get_by_text("Within requested width")).to_be_visible(
                timeout=STEP_TIMEOUT_MS
            )
            expect(page.get_by_text("400 mm wide").first).to_be_visible(timeout=STEP_TIMEOUT_MS)
            log("450 mm request shows compact 400 x 470 mm geometry and 'Within requested width'.")

            # Infeasible width: message shown and previous geometry preserved.
            send_chat(page, WIDTH_300_MESSAGE, "below this concept's supported minimum")
            expect(page.get_by_text("Requested width cannot fit this concept")).to_be_visible(
                timeout=STEP_TIMEOUT_MS
            )
            expect(footprint).to_contain_text("400", timeout=STEP_TIMEOUT_MS)
            expect(footprint).to_contain_text("470", timeout=STEP_TIMEOUT_MS)
            log("300 mm request shows the infeasible message and preserves 400 x 470 mm geometry.")

            # Wider feasible width then confirm.
            send_chat(page, WIDTH_650_MESSAGE, "Within requested width")
            expect(footprint).to_contain_text("600", timeout=STEP_TIMEOUT_MS)
            expect(footprint).to_contain_text("370", timeout=STEP_TIMEOUT_MS)
            log("650 mm request restores the wide 600 x 370 mm geometry.")

            confirm_button = page.get_by_role("button", name="Confirm design")
            expect(confirm_button).to_be_enabled(timeout=STEP_TIMEOUT_MS)
            confirm_button.click()
            expect(page.get_by_text("Design parameters confirmed")).to_be_visible(
                timeout=STEP_TIMEOUT_MS
            )
            expect(page.locator(".chat-status")).to_contain_text(
                "Confirmed", timeout=STEP_TIMEOUT_MS
            )
            log("Design confirmed; confirmed state is asserted.")

            play = page.get_by_role("button", name="Play preview")
            pause = page.get_by_role("button", name="Pause preview")
            expect(play).to_be_visible(timeout=STEP_TIMEOUT_MS)
            before = page.locator(".viewer-canvas canvas").screenshot()
            play.click()
            expect(pause).to_be_enabled(timeout=STEP_TIMEOUT_MS)
            page.wait_for_timeout(900)
            during = page.locator(".viewer-canvas canvas").screenshot()
            assert hashlib.sha256(before).digest() != hashlib.sha256(during).digest(), (
                "The schematic canvas did not change after starting the preview."
            )
            pause.click()
            expect(play).to_be_enabled(timeout=STEP_TIMEOUT_MS)
            page.get_by_role("button", name="Reset preview").click()
            expect(pause).to_be_disabled(timeout=STEP_TIMEOUT_MS)
            log("Illustrative preview can be played, paused and reset.")

            # Inspect one component through the accessible component list.
            component_list = page.get_by_label("Workstation components")
            tip_rack = component_list.get_by_role("button", name="Tip rack")
            expect(tip_rack).to_be_visible(timeout=STEP_TIMEOUT_MS)
            tip_rack.click()
            expect(page.get_by_text("Selected component")).to_be_visible(timeout=STEP_TIMEOUT_MS)
            expect(page.locator(".selection-block")).to_contain_text(
                "Tip rack", timeout=STEP_TIMEOUT_MS
            )
            log("Component inspection via the accessible list shows 'Tip rack'.")

            screenshot_path = os.environ.get("MUSEAUTOLAB_BROWSER_SCREENSHOT", "").strip()
            if screenshot_path:
                # Optional only; no fixed files are created otherwise.
                target = Path(screenshot_path)
                if not target.is_absolute():
                    target = ROOT / target
                target.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(target))
                log(f"Saved optional screenshot to {target}.")

            if page_errors:
                raise AssertionError(f"Unexpected browser page errors: {page_errors!r}")
            log("No unexpected browser page errors observed.")
        finally:
            browser.close()


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
    try:
        log(f"Starting stubbed backend: {sys.executable} {STUB_SERVER} --port {api_port}")
        backend_proc = subprocess.Popen(
            [sys.executable, str(STUB_SERVER), "--host", "127.0.0.1", "--port", str(api_port)],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
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
            stdout=subprocess.PIPE,
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
        return 1
    finally:
        stop_process(frontend_proc, "Vite frontend")
        stop_process(backend_proc, "stubbed backend")


if __name__ == "__main__":
    raise SystemExit(main())
