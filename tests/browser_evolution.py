"""Reopen, extend, inspect and export one project; no model-provider requests."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import browser_smoke as smoke
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent


def main():
    api_port, web_port = smoke.find_free_port(), smoke.find_free_port()
    api_base, web_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{web_port}"
    logs = [tempfile.TemporaryFile(), tempfile.TemporaryFile()]
    processes = []
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
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(web_url, wait_until="networkidle")
                expect(page.get_by_text("Workspace ready")).to_be_visible()
                smoke.send_chat(page, smoke.COMPLETE_TASK_MESSAGE, smoke.EXPECTED_STOCK)
                with page.expect_response(lambda r: r.url.endswith("/design")) as designed:
                    page.get_by_role("button", name="Develop design with Meta", exact=True).click()
                initial = designed.value.json()["project"]
                expect(page.locator(".viewer-canvas canvas")).to_have_count(1)
                with page.expect_download() as saved:
                    page.get_by_role("button", name="Save project", exact=True).click()
                path = saved.value.path()
                snapshot = json.loads(path.read_bytes())
                assert snapshot["revision"] == initial["revision"]
                page.get_by_role("button", name="New project", exact=True).click()
                expect(page.locator(".workspace-empty")).to_be_visible()
                with page.expect_response(lambda r: r.url.endswith("/projects/open")) as opened:
                    page.get_by_label("Open saved project").set_input_files(path)
                restored = opened.value.json()["project"]
                assert restored["id"] != initial["id"]
                assert restored["lineage_id"] == initial["id"]
                assert restored["design"] == initial["design"]
                expect(page.locator(".viewer-canvas canvas")).to_have_count(1)
                expect(page.get_by_text(smoke.COMPLETE_TASK_MESSAGE, exact=True)).to_be_visible()
                page.wait_for_function("""() => JSON.parse(localStorage.getItem(
                    'museautolab.workspace.v1') || '{}').revision > 0""")
                with page.expect_response(lambda r: r.url.endswith("/projects/open")) as resumed:
                    page.reload(wait_until="networkidle")
                project = resumed.value.json()["project"]
                assert project["lineage_id"] == initial["id"]
                assert project["design"] == initial["design"]
                panel = page.locator(".inspection-panel")
                with page.expect_response(
                    lambda r: r.url.endswith("/inspection-extension")
                ) as expansion:
                    panel.get_by_role(
                        "button", name="Add arm and camera with Meta", exact=True
                    ).click()
                extended = expansion.value.json()["project"]
                assert extended["id"] == project["id"]
                assert extended["revision"] == project["revision"] + 1
                assert (
                    extended["design"]["components"][: len(project["design"]["components"])]
                    == project["design"]["components"]
                )
                expect(
                    panel.get_by_role("heading", name="Inspection arm and camera")
                ).to_be_visible()
                expect(page.locator(".viewer-canvas canvas")).to_have_count(1)
                page.locator(".design-panel").evaluate("el => { el.scrollTop = 0; }")
                page.wait_for_timeout(1200)
                before = page.locator(".viewer-canvas canvas").screenshot()
                slider = panel.get_by_label("Camera sweep", exact=False)
                slider.fill("3")
                slider.dispatch_event("input")
                page.wait_for_timeout(400)
                after = page.locator(".viewer-canvas canvas").screenshot()
                assert hashlib.sha256(before).digest() != hashlib.sha256(after).digest()
                screenshot = os.environ.get("MUSEAUTOLAB_EVOLUTION_SCREENSHOT")
                if screenshot:
                    page.locator(".design-panel").evaluate("el => { el.scrollTop = 0; }")
                    page.screenshot(path=screenshot)
                with page.expect_download() as extended_save:
                    page.get_by_role("button", name="Save project", exact=True).click()
                extended_file = extended_save.value.path()
                with page.expect_response(
                    lambda r: r.url.endswith("/projects/open")
                ) as extended_open:
                    page.get_by_label("Open saved project").set_input_files(extended_file)
                assert (
                    extended_open.value.json()["project"]["inspection_extension"]
                    == extended["inspection_extension"]
                )
                page.get_by_role("button", name="Confirm design", exact=False).click()
                expect(page.get_by_text("Design parameters confirmed")).to_be_visible()
                expect(page.get_by_text("Workstation motion only.", exact=False)).to_be_visible()
                page.get_by_role("button", name="Generate project files", exact=True).click()
                link = page.get_by_role("link", name="Download project ZIP", exact=True)
                expect(link).to_be_visible(timeout=60000)
                with page.expect_download() as archive_download:
                    link.click()
                with zipfile.ZipFile(archive_download.value.path()) as archive:
                    assert len(archive.namelist()) == 24
                    body = json.loads(archive.read("project.json"))["project"]
                    module = json.loads(archive.read("inspection-module.json"))
                    assert module["revision"] == body["revision"]
                    assert module["module"] == body["inspection_extension"]
                    assert b"offline-inspection-fixture" in archive.read("inspection-module.json")
                    physics = json.loads(archive.read("simulation/result.json"))
                    assert physics["status"] == "passed"
                    assert physics["inspection_extension_excluded"] is True
                    report = json.loads(archive.read("cad/geometry-report.json"))
                    assert len(report["components"]) == len(body["design"]["components"])
                    for entry in json.loads(archive.read("manifest.json"))["files"]:
                        assert (
                            hashlib.sha256(archive.read(entry["name"])).hexdigest()
                            == entry["sha256"]
                        )
                panel.get_by_role("button", name="Remove module", exact=True).click()
                expect(panel.get_by_role("heading", name="Expand this workstation")).to_be_visible()
                expect(
                    page.get_by_role("link", name="Download project ZIP", exact=True)
                ).to_have_count(0)
                expect(page.locator(".viewer-canvas canvas")).to_have_count(1)
                # Invalid file never replaces the visible project.
                page.get_by_label("Open saved project").set_input_files(
                    {
                        "name": "wrong.json",
                        "mimeType": "application/json",
                        "buffer": b'{"bad":true}',
                    }
                )
                expect(page.get_by_role("alert")).to_contain_text("invalid MuseAutoLab")
                expect(page.locator(".viewer-canvas canvas")).to_have_count(1)
                page.get_by_role("button", name="New project", exact=True).click()
                expect(page.locator(".workspace-empty")).to_be_visible()
                assert not errors, errors
                print(
                    "PASS: file reopen, browser resume, same-project arm/camera extension, "
                    "kinematic sweep, extended CAD/physics/package, removal and file recovery."
                )
            finally:
                browser.close()
    except Exception:
        for log in logs:
            log.seek(0)
            print(log.read().decode("utf-8", errors="replace")[-2500:], file=sys.stderr)
        raise
    finally:
        for process in reversed(processes):
            smoke.stop_process(process, "project evolution test service")
        for log in logs:
            log.close()


if __name__ == "__main__":
    main()
