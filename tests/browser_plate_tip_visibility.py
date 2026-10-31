"""Check plate overlays against the actual visible components in isolated views."""

from pathlib import Path

import browser_smoke as harness
from browser_tip_options_server import ALTERNATIVES


def run(url):
    from playwright.sync_api import expect, sync_playwright

    output = harness.ROOT / ".local" / "tip-options-20261031" / "plate-tip-visibility"
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
        errors = []
        unmount_warnings = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: (
                unmount_warnings.append(message.text)
                if "Attempted to synchronously unmount a root" in message.text
                else None
            ),
        )
        try:
            page.goto(url, wait_until="networkidle")
            expect(page.get_by_text("Workspace ready")).to_be_visible()
            page.get_by_label("Open saved project").set_input_files(
                str(harness.ROOT / "docs/examples/microplate-project.json")
            )
            expect(page.locator(".storage-notice")).to_contain_text("rebuilt")
            expect(page.locator(".scene-rack-occupancy")).to_contain_text("wells occupied")
            composer = page.get_by_label("Describe your workflow or request a change")
            composer.fill(ALTERNATIVES)
            with page.expect_response(lambda response: response.url.endswith("/messages")) as turn:
                page.get_by_role("button", name="Send message", exact=True).click()
            assert turn.value.ok
            panel = page.get_by_role("region", name="Tip rack alternatives")
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/tip-rack-options") and response.request.method == "POST"
                )
            ) as selection:
                panel.get_by_role("article").first.get_by_role(
                    "button", name="Use this rack"
                ).click()
            assert selection.value.ok, selection.value.text()
            project = selection.value.json()["project"]
            assert project["labware_plate"] and project["tip_rack"]
            page.get_by_label("Inspect component view").select_option("part")
            expect(page.locator(".scene-rack-occupancy")).to_have_count(0)
            expect(page.locator(".microplate-axis-label")).to_have_count(0)
            page.locator(".viewer-shell").screenshot(path=str(output / "tip-only.png"))
            page.get_by_role("button", name="Show full model").click()
            expect(page.locator(".scene-rack-occupancy")).to_contain_text("wells occupied")
            page.get_by_label("Inspect component view").select_option("work")
            expect(page.locator(".scene-rack-occupancy")).to_contain_text("wells occupied")
            page.get_by_role("button", name="Show plate in model").click()
            expect(page.get_by_label("Inspect component view")).to_have_value("")
            page.get_by_label("Inspect component view").select_option("part")
            expect(page.locator(".scene-rack-occupancy")).to_contain_text("wells occupied")
            labels = page.locator(".microplate-axis-label")
            expect(labels).to_have_count(20)
            assert sorted(labels.all_text_contents()) == sorted(
                [str(number) for number in range(1, 13)] + list("ABCDEFGH")
            )
            for label in labels.all():
                expect(label).to_be_visible()
            page.locator(".viewer-shell").screenshot(path=str(output / "plate-only.png"))
            before = labels.first.bounding_box()
            assert before
            assert labels.first.evaluate("el => getComputedStyle(el).pointerEvents") == "none"
            page.get_by_role("button", name="Rotate right").click()
            page.wait_for_function(
                "x => Math.abs(document.querySelector('.microplate-axis-label')"
                ".getBoundingClientRect().x - x) > 0.5",
                arg=before["x"],
            )
            expect(labels).to_have_count(20)
            page.locator(".viewer-shell").screenshot(path=str(output / "plate-rotated.png"))
            assert not errors, errors
            assert not unmount_warnings, unmount_warnings
            print(
                "[plate-tip-visibility] Tip-only hides plate overlays; "
                "full, work and plate show them. All 20 axis labels are visible; "
                "no React root unmount warning."
            )
        finally:
            browser.close()


if __name__ == "__main__":
    harness.STUB_SERVER = Path(__file__).with_name("browser_tip_options_server.py")
    harness.run_smoke = run
    raise SystemExit(harness.main())
