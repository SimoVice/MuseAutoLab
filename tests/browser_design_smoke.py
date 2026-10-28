"""Offline UI/geometry/export checks; model proposals are explicitly synthetic fixtures.

Run with the locked environment: python tests/browser_design_smoke.py.
MUSEAUTOLAB_DESIGN_SCREENSHOT optionally saves the actual accepted-layout UI.
"""

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
    while web_port == api_port:
        web_port = smoke.find_free_port()
    api_base = f"http://127.0.0.1:{api_port}"
    web_url = f"http://127.0.0.1:{web_port}"
    processes = []
    logs = [tempfile.TemporaryFile(), tempfile.TemporaryFile()]
    try:
        processes.append(subprocess.Popen([
            sys.executable, str(ROOT / "tests/browser_design_server.py"), "--port", str(api_port),
        ], cwd=ROOT, stdout=logs[0], stderr=subprocess.STDOUT,
            creationflags=smoke.creation_flags()))
        smoke.wait_for_backend_health(api_base)
        env = dict(os.environ, MUSEAUTOLAB_API_TARGET=api_base)
        processes.append(subprocess.Popen([
            shutil.which("node") or "node", str(smoke.VITE_BIN), "--host", "127.0.0.1",
            "--port", str(web_port), "--strictPort",
        ], cwd=smoke.WEB_DIR, env=env, stdout=logs[1], stderr=subprocess.STDOUT,
            creationflags=smoke.creation_flags()))
        smoke.wait_for_http(web_url, 45, "Vite")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(web_url, wait_until="networkidle")
                expect(page.get_by_text("Workspace ready")).to_be_visible()
                expect(page.locator(".design-agent-card")).to_have_count(0)
                smoke.send_chat(page, smoke.COMPLETE_TASK_MESSAGE, smoke.EXPECTED_STOCK)
                panel = page.locator(".design-agent-card")
                expect(panel).to_be_visible()

                def design(instruction, status):
                    panel.get_by_label("Layout request").fill(instruction)
                    with page.expect_response(
                        lambda response: response.url.endswith("/design")
                    ) as info:
                        panel.get_by_role("button", name="design with Meta", exact=False).click()
                    body = info.value.json()
                    assert info.value.status == 200, body
                    assert body["design_run"]["status"] == status, body
                    expect(panel.locator(".design-agent-status")).to_have_text(status.capitalize())
                    expect(page.get_by_role("button", name="Send message")).to_be_disabled()
                    # Empty chat is disabled by content, not by a stuck busy flag.
                    expect(page.get_by_label(
                        "Describe your workflow or request a change"
                    )).to_be_enabled()
                    return body

                before = page.locator(".viewer-canvas canvas").screenshot()
                accepted = design("Exercise a correction with the offline fixture.", "accepted")
                assert len(accepted["design_run"]["attempts"]) == 2
                assert not all(c["passed"] for c in accepted["design_run"]["attempts"][0]["checks"])
                assert all(c["passed"] for c in accepted["design_run"]["attempts"][1]["checks"])
                expect(page.locator(".footprint strong")).to_contain_text("500")
                expect(page.locator(".footprint strong")).to_contain_text("480")
                after = page.locator(".viewer-canvas canvas").screenshot()
                assert hashlib.sha256(before).digest() != hashlib.sha256(after).digest()
                rejected = design("Reject both proposals for this diagnostic.", "rejected")
                assert rejected["project"] == accepted["project"]
                assert len(rejected["design_run"]["attempts"]) == 2
                expect(page.locator(".footprint strong")).to_contain_text("500")
                design("Keep clear access to the sample rack.", "accepted")
                screenshot = os.environ.get("MUSEAUTOLAB_DESIGN_SCREENSHOT")
                if screenshot:
                    page.locator(".design-panel").evaluate("el => {el.scrollTop = 0}")
                    page.screenshot(path=screenshot)

                page.get_by_role("button", name="Confirm design").click()
                expect(page.get_by_text("Design parameters confirmed")).to_be_visible()
                page.get_by_role("button", name="Generate project files", exact=True).click()
                link = page.get_by_role("link", name="Download project ZIP", exact=True)
                expect(link).to_be_visible(timeout=60000)
                with page.expect_download() as download_info:
                    link.click()
                download = download_info.value
                assert download.failure() is None
                with zipfile.ZipFile(download.path()) as archive:
                    project = json.loads(archive.read("project.json"))["project"]
                    report = json.loads(archive.read("cad/geometry-report.json"))
                    assert project["engineering_design"] == report["engineering_design"]
                    assert project["design"]["footprint"]["width_mm"] == 500
                    assert b"offline-model-fixture" in archive.read("assembly-guide.html")
                    assert b"Meta layout provenance" in archive.read("README.md")
                    manifest = json.loads(archive.read("manifest.json"))
                    for entry in manifest["files"]:
                        digest = hashlib.sha256(archive.read(entry["name"])).hexdigest()
                        assert digest == entry["sha256"]
                    physics = json.loads(archive.read("simulation/result.json"))
                    assert physics["status"] == "passed"
                    assert len(archive.namelist()) == 22

                smoke.send_chat(page, smoke.WIDTH_450_MESSAGE, "Within requested width")
                expect(panel.locator(".design-agent-status")).to_have_count(0)
                expect(page.get_by_role(
                    "link", name="Download project ZIP", exact=True
                )).to_have_count(0)
                expect(page.locator(".footprint strong")).to_contain_text("400")
                page.get_by_role("button", name="New project", exact=True).click()
                expect(page.locator(".workspace-empty")).to_be_visible()
                expect(page.locator(".design-agent-card")).to_have_count(0)
                assert errors == [], errors
                print("PASS: correction, rejection, geometry/CAD/simulation ZIP, stale UI "
                      "and reset; model stubbed.")
            finally:
                browser.close()
        return 0
    except Exception:
        for logfile in logs:
            logfile.seek(0)
            print(logfile.read().decode("utf-8", errors="replace")[-2500:], file=sys.stderr)
        raise
    finally:
        for process in reversed(processes):
            smoke.stop_process(process, "design smoke service")
        for logfile in logs:
            logfile.close()


if __name__ == "__main__":
    raise SystemExit(main())
