"""Reviewed references, source-backed recommendations and actual supplier envelopes."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import browser_smoke as smoke
from browser_evolution_server import SOURCE_MESSAGE
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent


def main():
    api_port, web_port = smoke.find_free_port(), smoke.find_free_port()
    api_base, web_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{web_port}"
    processes = []
    logs = [tempfile.TemporaryFile(), tempfile.TemporaryFile()]
    try:
        processes.append(
            subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "tests/browser_evolution_server.py"),
                    "--port",
                    str(api_port),
                ],
                cwd=ROOT,
                stdout=logs[0],
                stderr=subprocess.STDOUT,
                creationflags=smoke.creation_flags(),
            )
        )
        smoke.wait_for_backend_health(api_base)
        processes.append(
            subprocess.Popen(
                [
                    shutil.which("node") or "node",
                    str(smoke.VITE_BIN),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(web_port),
                    "--strictPort",
                ],
                cwd=smoke.WEB_DIR,
                env=dict(os.environ, MUSEAUTOLAB_API_TARGET=api_base),
                stdout=logs[1],
                stderr=subprocess.STDOUT,
                creationflags=smoke.creation_flags(),
            )
        )
        smoke.wait_for_http(web_url, 45, "Vite")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1050})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(web_url, wait_until="networkidle")
                expect(page.get_by_text("Workspace ready")).to_be_visible()
                expect(page.locator(".viewer-canvas canvas")).to_have_count(0)
                smoke.send_chat(page, smoke.COMPLETE_TASK_MESSAGE, smoke.EXPECTED_STOCK)
                sources = page.locator(".design-sources")
                expect(sources).to_be_visible()
                expect(sources.locator(".source-bindings")).to_have_count(0)
                sources.get_by_text("Browse references and technical scope", exact=True).click()
                link = sources.get_by_role(
                    "link", name="Science Jubilee laboratory tools", exact=False
                )
                expect(link).to_have_attribute(
                    "href",
                    "https://github.com/machineagency/science-jubilee/tree/bb918fa78f300f57cc379a80731cfca7bdb55c66",
                )
                science_url = link.get_attribute("href")
                sources.get_by_text("Browse references and technical scope", exact=True).click()
                with page.expect_response(lambda r: r.url.endswith("/design")) as first:
                    page.get_by_role("button", name="Develop design with Meta", exact=True).click()
                initial = first.value.json()["project"]
                expect(sources.locator(".source-bindings")).to_be_visible()
                with page.expect_response(lambda r: r.url.endswith("/messages")) as advice:
                    smoke.send_chat(page, SOURCE_MESSAGE, "integration reference")
                advised = advice.value.json()
                assert advised["project"] == initial
                expect(page.locator(".message-references a")).to_have_count(1)
                expect(page.locator(".message-references a")).to_have_attribute(
                    "href", science_url
                )
                with page.expect_response(lambda r: r.url.endswith("/configuration")) as configured:
                    page.get_by_label("Choose Motors", exact=True).select_option("pololu-1208")
                motor_project = configured.value.json()["project"]
                motor = next(
                    p for p in motor_project["design"]["components"] if p["id"] == "carriage"
                )
                shape = next(p for p in motor["geometry"]["primitives"] if p["id"] == "motor")
                assert shape["size"] == [35, 28, 35] and shape["reference_id"] == "pololu-1208"
                expect(page.locator(".viewer-canvas canvas")).to_have_count(0)
                page.get_by_role("button", name="Develop design with Meta", exact=True).click()
                expect(page.locator(".viewer-canvas canvas")).to_have_count(1)
                with page.expect_response(
                    lambda r: r.url.endswith("/inspection-extension")
                ) as expansion:
                    page.get_by_role(
                        "button", name="Add arm and camera with Meta", exact=True
                    ).click()
                project = expansion.value.json()["project"]
                camera = next(
                    p for p in project["design"]["components"] if p["id"] == "inspection-camera"
                )
                assert camera["size"] == [25, 11.5, 24]
                expect(
                    page.locator(".inspection-panel").get_by_role(
                        "heading", name="Inspection arm and camera"
                    )
                ).to_be_visible()
                expect(
                    sources.get_by_role("button", name="Raspberry Pi Camera Module 3 envelope")
                ).to_be_visible()
                with page.expect_download() as download:
                    sources.get_by_role("link", name="Download design sources").click()
                payload = json.loads(download.value.path().read_bytes())
                assert payload["revision"] == project["revision"]
                assert payload["source_basis"] == project["design_basis"]
                screenshot = os.environ.get("MUSEAUTOLAB_SOURCES_SCREENSHOT")
                if screenshot:
                    sources.screenshot(path=screenshot)
                with page.expect_download() as saved:
                    page.get_by_role("button", name="Save project", exact=True).click()
                with page.expect_response(lambda r: r.url.endswith("/projects/open")) as reopened:
                    page.get_by_label("Open saved project").set_input_files(saved.value.path())
                assert reopened.value.json()["project"]["design_basis"] == project["design_basis"]
                expect(page.locator(".message-references a")).to_have_count(1)
                assert not errors, errors
                print(
                    "PASS: pinned references, resolved advice, motor geometry, "
                    "camera envelope, source download and reopen."
                )
            finally:
                browser.close()
    except Exception:
        for log in logs:
            log.seek(0)
            print(log.read().decode("utf-8", errors="replace")[-2400:], file=sys.stderr)
        raise
    finally:
        for process in reversed(processes):
            smoke.stop_process(process, "source browser service")
        for log in logs:
            log.close()


if __name__ == "__main__":
    main()
