"""Source CAD, chat-only revisions/modules, clean UI and portable state in Chrome.

Uses the real application, source meshes and compiler with offline Meta fixtures.
STEP reopening/regeneration is covered separately by test_foundation_exports.py.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import browser_smoke as harness  # noqa: E402


def run(url):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors, snapshots = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def record(response):
            if response.url.endswith("/messages") and response.ok:
                snapshots.append(response.json())

        page.on("response", record)
        try:
            page.goto(url)
            expect(page.get_by_text("Workspace ready")).to_be_visible()
            assert "stock" not in page.locator("body").inner_text().lower()
            expect(page.locator("textarea")).to_have_count(1)
            harness.send_chat(
                page,
                "I keep making dilutions manually and want to automate pipetting.",
                "Which equipment",
            )
            harness.send_chat(page, "I have a pipette and microcentrifuge tubes.", "What volumes")
            expect(page.locator("canvas,.cost-block,.camera-card")).to_have_count(0)
            expect(page.locator(".planning-panel")).to_have_count(1)
            harness.send_chat(page, "In the future I might want an arm and camera.", "expansion")
            assert not snapshots[-1]["project"].get("inspection_extension")
            field = page.get_by_label("Describe your workflow or request a change")
            field.fill("Develop the workstation from the real CAD base.")
            page.get_by_role("button", name="Send message").click()
            expect(page.get_by_role("progressbar")).to_be_visible()
            expect(page.locator("canvas")).to_have_count(0)
            expect(page.locator("canvas")).to_have_count(1, timeout=20000)
            expect(page.get_by_role("progressbar")).to_have_count(0)
            expect(page.locator(".project-details")).not_to_have_attribute("open", "")
            expect(page.locator("textarea:visible")).to_have_count(1)
            assert not page.get_by_label("Expansion request", exact=True).count()
            first = snapshots[-1]["project"]
            assert first["design"]["foundation"]["bed_drop_mm"] == 100
            assert not first.get("inspection_extension")
            assert first["summary"]["target_concentrations"] is None
            # Mesh URLs are fixed, locally served derivatives of the original source CAD.
            for kind in ("static", "bed"):
                response = page.request.get(url + f"assets/jubilee-c877bd2-{kind}.glb")
                assert response.ok and response.body()[:4] == b"glTF"
            harness.send_chat(page, "Lower the bed by another 30 mm.", "Checking")
            second = snapshots[-1]["project"]
            assert second["design"]["foundation"]["bed_drop_mm"] == 130
            harness.send_chat(page, harness.WIDTH_450_MESSAGE, "cannot fit")
            assert snapshots[-1]["project"] == second
            harness.send_chat(page, "Add an inspection arm and camera now.", "Checking")
            expanded = snapshots[-1]["project"]
            assert (
                expanded["inspection_extension"]["provenance"]["model"]
                == "offline-inspection-fixture"
            )
            assert expanded["design"]["foundation"] == second["design"]["foundation"]
            expect(page.locator("textarea:visible")).to_have_count(1)
            harness.send_chat(page, harness.COMPLETE_TASK_MESSAGE, harness.EXPECTED_STOCK)
            plan = page.locator("details.prep-plan")
            plan.locator("summary").click()
            expect(plan).to_contain_text("100 µL")
            page.get_by_role("button", name="Confirm design").click()
            expect(page.locator(".chat-status")).to_have_text("Confirmed")
            harness.send_chat(page, "Show project files.", "Checking")
            expect(page.locator(".project-details")).to_have_attribute("open", "")
            expect(
                page.get_by_role("button", name="Generate project files", exact=True)
            ).to_be_visible()
            expect(page.get_by_role("button", name="Run physics", exact=True)).to_have_count(0)
            with page.expect_download() as downloaded:
                page.get_by_role("button", name="Save project", exact=True).click()
            saved = downloaded.value.path()
            data = json.loads(Path(saved).read_text(encoding="utf8"))
            assert data["compiler_version"] == "3"
            assert data["foundation_id"] == "jubilee-v2.2.2-c877bd2"
            page.get_by_label("Open saved project").set_input_files(saved)
            expect(page.locator(".storage-notice")).to_contain_text("rebuilt")
            expect(page.locator("canvas")).to_have_count(1)
            if os.environ.get("MUSEAUTOLAB_BROWSER_SCREENSHOT"):
                page.locator(".project-details > summary").click()
                page.screenshot(path=os.environ["MUSEAUTOLAB_BROWSER_SCREENSHOT"])
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page.get_by_role("button", name="New project", exact=True).click()
            expect(page.locator("canvas,.cost-block,.camera-card")).to_have_count(0)
            expect(page.locator("textarea:visible")).to_have_count(1)
            assert not errors, errors
            print(
                "[browser-foundation] Chat design/revision/expansion, real source meshes, "
                "progress, width rollback, clean UI, plans, save/open and mobile passed."
            )
        finally:
            browser.close()


if __name__ == "__main__":
    harness.STUB_SERVER = Path(__file__).with_name("browser_foundation_server.py")
    harness.run_smoke = run
    raise SystemExit(harness.main())
