"""Two real compiler routes after a chat choice; Meta alone is an offline fixture."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import browser_smoke as harness  # noqa: E402


def run(url):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            for route in ("open-source buildable", "prebuilt"):
                page.goto(url)
                expect(page.get_by_text("Workspace ready")).to_be_visible()
                page.get_by_role("button", name="New project", exact=True).click()
                harness.send_chat(
                    page,
                    "I keep making dilutions manually and want to automate pipetting.",
                    "Which equipment",
                )
                harness.send_chat(
                    page, "I have a pipette and microcentrifuge tubes.", "What volumes"
                )
                harness.send_chat(
                    page, "Help me compare the platform options.", "assembled platform"
                )
                expect(page.locator("canvas,.cost-block")).to_have_count(0)
                expect(page.locator("textarea:visible")).to_have_count(1)
                harness.send_chat(page, "Develop the machine now.", "Before developing")
                expect(page.locator("canvas")).to_have_count(0)
                with page.expect_response(lambda r: r.url.endswith("/messages")) as choice:
                    harness.send_chat(page, f"I prefer the {route} one.", "Developing")
                selected = choice.value.json()["project"]
                expect(page.locator("canvas")).to_have_count(1)
                if route == "prebuilt":
                    assert selected["design"]["platform"]["id"] == "opentrons-ot2"
                    assert "foundation" not in selected["design"]
                    expect(page.get_by_text("OT-2 · schematic setup", exact=False)).to_be_visible()
                else:
                    assert selected["design"]["foundation"]["id"].startswith("jubilee")
                harness.send_chat(
                    page, "The stock concentration is 10 mg/mL.", "Recorded the stock"
                )
                message = (
                    "Use target concentrations of 1, 0.5 and 0.1 mg/mL, with a final volume "
                    "of 1 mL per tube. Keep the machine layout unchanged."
                )
                with page.expect_response(lambda r: r.url.endswith("/messages")) as quantities:
                    harness.send_chat(page, message, "Updated the preparation")
                updated = quantities.value.json()["project"]
                assert updated["engineering_design"] == selected["engineering_design"]
                assert [s["stock_volume_ul"] for s in updated["plan"]["steps"]] == [100, 50, 10]
                page.locator("details.prep-plan > summary").click()
                expect(page.locator(".plan-card")).to_contain_text("Ready")
                expect(page.locator(".plan-card")).not_to_contain_text("unsupported unit")
                harness.send_chat(
                    page, "How do I buy the pieces and assemble this?", "Purchase and assembly"
                )
                expect(page.locator("details.project-details")).to_have_attribute("open", "")
                expect(page.get_by_text("Purchase and assembly plan", exact=True)).to_be_visible()
                if route == "prebuilt":
                    expect(page.locator("details.project-details")).to_contain_text(
                        "Specify and quote"
                    )
                with page.expect_download() as download:
                    page.get_by_role("button", name="Save project", exact=True).click()
                saved = download.value.path()
                snapshot = json.loads(Path(saved).read_text(encoding="utf8"))
                assert snapshot["compiler_version"] == "4"
                page.get_by_label("Open saved project").set_input_files(saved)
                expect(page.locator(".storage-notice")).to_contain_text("rebuilt")
                expect(page.locator("canvas")).to_have_count(1)
            assert not errors, errors
            print(
                "[browser-engineering] Requirements, compared options, explicit choice, "
                "two architectures, per-tube arithmetic, layout preservation, guidance "
                "and save/reopen passed."
            )
        finally:
            browser.close()


if __name__ == "__main__":
    harness.STUB_SERVER = Path(__file__).with_name("browser_foundation_server.py")
    harness.run_smoke = run
    raise SystemExit(harness.main())
