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
import tempfile
import time
import urllib.request
import zipfile
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
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            log(f"Opening {web_url} (AI provider is stubbed; no Meta call occurs).")
            page.goto(web_url, wait_until="domcontentloaded", timeout=STEP_TIMEOUT_MS)

            # Start with no preset concept or pricing; the user types the first request.
            expect(page.get_by_text("Workspace ready")).to_be_visible(timeout=STEP_TIMEOUT_MS)
            expect(page.locator(".workspace-empty")).to_be_visible(timeout=STEP_TIMEOUT_MS)
            expect(page.locator(".viewer-canvas canvas")).to_have_count(0)
            expect(
                page.locator(".cost-block, .summary-card, .plan-card, .camera-card")
            ).to_have_count(0)
            expect(page.get_by_role("button", name="Try an example")).to_have_count(0)
            send_chat(page, "Hello.", "What would you like to automate?")
            expect(page.locator(".workspace-empty")).to_be_visible()
            expect(page.locator(".viewer-canvas canvas")).to_have_count(0)
            log("Blank workspace remains blank until an actual requirement is recorded.")

            send_chat(page, COMPLETE_TASK_MESSAGE, EXPECTED_STOCK)
            expect(page.locator(".workspace-empty")).to_have_count(0)
            footprint = page.locator(".footprint strong")
            expect(footprint).to_contain_text("600", timeout=STEP_TIMEOUT_MS)
            expect(footprint).to_contain_text("370", timeout=STEP_TIMEOUT_MS)
            expect(page.locator(".viewer-canvas canvas")).to_have_count(1, timeout=STEP_TIMEOUT_MS)
            log("Typed task reveals the supported 600 x 370 mm concept and pricing.")

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

            physics_card = page.locator(".physics-card")

            def frame_physics_panel():
                page.locator(".design-panel").evaluate("""panel => {
                    const card = panel.querySelector('.physics-card');
                    const viewer = panel.querySelector('.viewer-shell');
                    const top = card.getBoundingClientRect().top
                        - panel.getBoundingClientRect().top;
                    panel.scrollTop += top - viewer.offsetHeight - 24;
                }""")

            expect(physics_card).to_be_visible(timeout=STEP_TIMEOUT_MS)
            run_physics_button = physics_card.get_by_role("button", name="Run physics")
            expect(run_physics_button).to_be_visible(timeout=STEP_TIMEOUT_MS)
            scenario_select = physics_card.get_by_label("Test case")
            expect(scenario_select).to_be_visible(timeout=STEP_TIMEOUT_MS)
            expect(scenario_select.locator("option[value='nominal']")).to_have_count(1)
            expect(scenario_select.locator("option[value='blocked_path']")).to_have_count(1)

            def run_physics_case(scenario_value: str, expected_status: str) -> str:
                scenario_select.select_option(scenario_value)
                with page.expect_response(
                    lambda response: (
                        response.request.method == "POST"
                        and "/api/projects/" in response.url
                        and response.url.endswith("/simulations")
                    )
                ) as response_info:
                    run_physics_button.click()
                start_response = response_info.value
                assert start_response.ok, f"Physics start failed: {start_response.status}"
                job_payload = start_response.json()
                job_id = str(job_payload.get("id", ""))
                assert job_id, f"Physics start response missing job id: {job_payload!r}"
                status_badge = physics_card.locator(".physics-status")
                expect(status_badge).to_have_text(expected_status, timeout=45_000)
                return job_id

            canvas = page.locator(".viewer-canvas canvas")
            nominal_job_id = run_physics_case("nominal", "passed")
            physics_metrics = physics_card.locator(".physics-metrics")
            expect(physics_metrics).to_contain_text("Waypoints", timeout=STEP_TIMEOUT_MS)
            # Real playback: canvas pixels must change while the measured states replay.
            phys_play = physics_card.get_by_role("button", name="Play", exact=True)
            phys_pause = physics_card.get_by_role("button", name="Pause", exact=True)
            phys_reset = physics_card.get_by_role("button", name="Reset", exact=True)
            expect(phys_play).to_be_enabled(timeout=STEP_TIMEOUT_MS)
            viewer_before = canvas.screenshot()
            phys_play.click()
            expect(phys_pause).to_be_enabled(timeout=STEP_TIMEOUT_MS)
            page.wait_for_timeout(1200)
            viewer_during = canvas.screenshot()
            assert (
                hashlib.sha256(viewer_before).digest() != hashlib.sha256(viewer_during).digest()
            ), "The viewer canvas did not change during physics replay."
            # Speed options switch replay rate.
            for speed_label in ("2x", "4x", "1x"):
                physics_card.get_by_role("button", name=speed_label, exact=True).click()
            expect(physics_card.get_by_role("button", name="1x", exact=True)).to_have_attribute(
                "aria-pressed", "true", timeout=STEP_TIMEOUT_MS
            )
            phys_pause.click()
            expect(phys_play).to_be_enabled(timeout=STEP_TIMEOUT_MS)
            phys_reset.click()
            expect(phys_play).to_be_enabled(timeout=STEP_TIMEOUT_MS)
            # Seek part-way through the measured replay; canvas must differ from start.
            seek = physics_card.locator("#physics-seek")
            expect(seek).to_be_visible(timeout=STEP_TIMEOUT_MS)
            seek_max = float(seek.get_attribute("max") or "0")
            assert seek_max > 0, "Physics replay duration must be positive."
            seek.evaluate(
                "(el, half) => { const proto = HTMLInputElement.prototype;"
                " const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');"
                " const setter = descriptor.set;"
                " setter.call(el, String(half));"
                " el.dispatchEvent(new Event('input', { bubbles: true }));"
                " el.dispatchEvent(new Event('change', { bubbles: true })); }",
                seek_max / 2,
            )
            page.wait_for_timeout(600)
            expect(physics_card.locator(".physics-seek-label")).to_contain_text(
                f"Replay time {int(seek_max / 2)}"
            )
            viewer_seeked = canvas.screenshot()
            assert (
                hashlib.sha256(viewer_before).digest() != hashlib.sha256(viewer_seeked).digest()
            ), "Seeking the physics replay did not change the viewer canvas."
            phys_reset.click()
            log("Nominal physics passed; playback, pause, reset, seek and speed verified.")
            phys_play.click()
            page.get_by_role("button", name="Play preview", exact=True).click()
            expect(phys_pause).to_be_disabled(timeout=STEP_TIMEOUT_MS)
            page.get_by_role("button", name="Pause preview", exact=True).click()
            log("Switching to the illustrative preview stops physical replay.")
            blocked_job_id = run_physics_case("blocked_path", "blocked")
            expect(
                physics_card.locator(".physics-note").filter(has_text="Blocked:")
            ).to_contain_text("Blocked", timeout=STEP_TIMEOUT_MS)
            metrics_text = physics_metrics.inner_text()
            import re as _re

            waypoint_match = _re.search(r"(\d+)\s*/\s*(\d+)", metrics_text)
            assert waypoint_match, f"Could not read Waypoints from metrics: {metrics_text!r}"
            assert int(waypoint_match.group(1)) < int(waypoint_match.group(2)), (
                f"Blocked run should complete fewer than total waypoints: {metrics_text!r}"
            )
            log("Blocked-path physics shows diagnostic note with partial waypoints.")
            screenshot_path = os.environ.get("MUSEAUTOLAB_BROWSER_SCREENSHOT", "").strip()
            if screenshot_path:
                blocked_image = Path(screenshot_path)
                blocked_image = blocked_image.with_name(blocked_image.stem + "-blocked.png")
                blocked_image.parent.mkdir(parents=True, exist_ok=True)
                physics_card.locator("#physics-seek").focus()
                physics_card.locator("#physics-seek").press("End")
                frame_physics_panel()
                page.screenshot(path=str(blocked_image))
            # Re-run nominal so the exported package carries a nominal/passed result.
            nominal_job_id = run_physics_case("nominal", "passed")
            physics_job_ids = [nominal_job_id, blocked_job_id]

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

            def download_package():
                page.get_by_role("button", name="Generate project files").click()
                link = page.get_by_role("link", name="Download project ZIP", exact=True)
                expect(link).to_be_visible(timeout=45000)
                href = link.get_attribute("href")
                with page.expect_download() as download_info:
                    link.click()
                download = download_info.value
                assert download.failure() is None
                with zipfile.ZipFile(download.path()) as archive:
                    manifest = json.loads(archive.read("manifest.json"))
                    snapshot = json.loads(archive.read("project.json"))["project"]
                    geometry = json.loads(archive.read("cad/geometry-report.json"))
                    assert snapshot["revision"] == manifest["revision"] == geometry["revision"]
                    assert geometry["project_id"] == snapshot["id"]
                    assert {c["id"] for c in geometry["components"]} == {
                        c["id"] for c in snapshot["design"]["components"]
                    }
                    for file in manifest["files"]:
                        content = archive.read(file["name"])
                        assert len(content) == file["size"]
                        assert hashlib.sha256(content).hexdigest() == file["sha256"]
                    assert b"ISO-10303-21" in archive.read("cad/workstation.step")
                    assert b"<svg" in archive.read("assembly-guide.html")
                    assert b"not fabrication-ready" in archive.read("README.md")
                    assert len(archive.namelist()) == 22
                    for sim_name in (
                        "simulation/model.xml",
                        "simulation/result.json",
                        "simulation/trajectory.csv",
                        "simulation/engine.py",
                        "simulation/run.py",
                        "simulation/README.md",
                    ):
                        assert sim_name in archive.namelist(), f"Missing {sim_name}"
                    sim_result = json.loads(archive.read("simulation/result.json"))
                    assert sim_result["project_id"] == snapshot["id"]
                    assert sim_result["revision"] == snapshot["revision"]
                    assert sim_result["scenario"] == "nominal"
                    assert sim_result["status"] == "passed"
                    assert (
                        hashlib.sha256(archive.read("simulation/engine.py")).hexdigest()
                        == sim_result["engine_source_sha256"]
                    )
                return href, snapshot, geometry

            def physics_result_url(project_id: str, job_id: str) -> str:
                return f"/api/projects/{project_id}/simulations/{job_id}/result"

            baseline_download, baseline_snapshot, _ = download_package()
            page.get_by_role("button", name="Next step", exact=True).click()
            expect(page.locator(".files-step-title")).to_have_text("Frame and custom deck")
            expect(page.locator(".selection-block")).to_contain_text("Custom deck")
            log("Real ZIP download, revision, hashes, CAD and assembly selection verified.")

            send_chat(page, "Add refrigerated storage at 4 C.", "Recorded a 4 C")
            expect(
                component_list.get_by_role("button", name="Refrigerated sample bay")
            ).to_be_visible()
            expect(footprint).to_contain_text("570")
            expect(page.locator(".cost-block")).to_contain_text("253.18")
            expect(page.locator(".chat-status")).to_contain_text("Draft")

            page.get_by_label("Choose Motor drivers", exact=True).select_option("a4988")
            expect(page.locator(".cost-block")).to_contain_text("225.18")
            expect(page.get_by_label("Describe your workflow or request a change")).to_be_enabled()
            try:
                with page.expect_response(
                    lambda response: (
                        response.request.method == "POST"
                        and response.url.endswith("/configuration")
                    ),
                    timeout=10000,
                ) as configured:
                    page.get_by_label("Choose Cooling", exact=True).select_option("opentrons-gen2")
            except Exception:
                choice = page.get_by_label("Choose Cooling", exact=True)
                log(f"Cooling choice: value={choice.input_value()}, enabled={choice.is_enabled()}")
                alerts = page.get_by_role("alert").all_text_contents()
                log(f"Alerts: {alerts}, page errors: {page_errors}")
                raise
            assert configured.value.status == 200, configured.value.text()
            expect(page.locator(".cost-block")).to_contain_text("4,165.23")
            expect(page.locator(".cost-block")).to_contain_text("from")
            expect(footprint).to_contain_text("624")
            page.get_by_label("Target temperature (°C)", exact=True).fill("2")
            page.get_by_role("button", name="Apply cooling settings").click()
            expect(page.get_by_role("alert")).to_contain_text("4")
            expect(page.locator(".cost-block")).to_contain_text("4,165.23")
            page.get_by_label("Target temperature (°C)", exact=True).fill("4")
            page.get_by_label("Refrigerated sample bay", exact=True).uncheck()
            page.get_by_role("button", name="Apply cooling settings").click()
            expect(footprint).to_contain_text("370")
            expect(
                component_list.get_by_role("button", name="Refrigerated sample bay")
            ).to_have_count(0)
            expect(page.locator(".cost-block")).to_contain_text("180.28")
            page.get_by_label("Refrigerated sample bay", exact=True).check()
            page.get_by_role("button", name="Apply cooling settings").click()
            expect(page.get_by_label("Choose Cooling", exact=True)).to_have_value("opentrons-gen2")
            expect(footprint).to_contain_text("624")
            expect(page.locator(".cost-block")).to_contain_text("4,165.23")
            log("Cooling, prices, alternatives, rejection and re-enable are coherent.")
            expect(page.get_by_role("link", name="Download project ZIP", exact=True)).to_have_count(
                0
            )
            assert page.request.get(web_url.rstrip("/") + baseline_download).status == 409
            baseline_project_id = str(baseline_snapshot["id"])
            for stale_job_id in physics_job_ids:
                stale = page.request.get(
                    web_url.rstrip("/") + physics_result_url(baseline_project_id, stale_job_id)
                )
                assert stale.status == 409, f"Stale physics result not rejected: {stale.status}"
                stale_file = page.request.get(
                    web_url.rstrip("/")
                    + f"/api/projects/{baseline_project_id}/simulations/{stale_job_id}"
                    + "/files/simulation/model.xml"
                )
                assert stale_file.status == 409
            expect(physics_card).to_have_count(0)
            page.get_by_role("button", name="Confirm design").click()
            _, cold_snapshot, cold_geometry = download_package()
            assert cold_snapshot["revision"] > baseline_snapshot["revision"]
            assert cold_snapshot["summary"]["cooling_enabled"] is True
            assert cold_snapshot["selections"]["cooling"] == "opentrons-gen2"
            deck = next(c for c in cold_geometry["components"] if c["id"] == "base")
            assert deck["bbox_cad"]["size"] == [600.0, 624.0, 20.0]
            expect(
                page.get_by_role("link", name="Download assembly-guide.html", exact=True)
            ).to_be_visible()
            log("Old downloads blocked; regenerated cold-bay package matches selection.")
            run_physics_case("nominal", "passed")
            physics_card.locator("#physics-seek").evaluate("""el => {
                const proto = HTMLInputElement.prototype;
                const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
                setter.call(el, String(Number(el.max) / 2));
                el.dispatchEvent(new Event('input', { bubbles: true }));
            }""")

            screenshot_path = os.environ.get("MUSEAUTOLAB_BROWSER_SCREENSHOT", "").strip()
            if screenshot_path:
                # Optional only; no fixed files are created otherwise.
                target = Path(screenshot_path)
                if not target.is_absolute():
                    target = ROOT / target
                target.parent.mkdir(parents=True, exist_ok=True)
                frame_physics_panel()
                page.screenshot(path=str(target))
                log(f"Saved optional screenshot to {target}.")

            page.get_by_role("button", name="New project", exact=True).click()
            expect(page.get_by_text("Workspace ready")).to_be_visible(timeout=STEP_TIMEOUT_MS)
            expect(page.locator(".workspace-empty")).to_be_visible(timeout=STEP_TIMEOUT_MS)
            expect(page.locator(".viewer-canvas canvas, .summary-card, .cost-block")).to_have_count(
                0
            )
            expect(page.locator(".message-row.user")).to_have_count(0)
            expect(page.locator("textarea")).to_have_value("")
            log("New project clears the design, conversation, plan, costs and generated panels.")

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
