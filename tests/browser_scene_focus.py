"""Exercise explicit component isolation with offline model fixtures and real WebGL."""

from pathlib import Path

import browser_smoke as harness


def run(url):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(url)
            expect(page.get_by_text("Workspace ready")).to_be_visible()
            harness.send_chat(
                page, "I keep making dilutions manually and want to automate pipetting.",
                "Which equipment",
            )
            harness.send_chat(page, "I have a pipette and microcentrifuge tubes.", "What volumes")
            harness.develop_layout(page)
            page.locator(".project-details > summary").click()
            page.get_by_role("button", name="Custom workflow deck on Jubilee platform").click()
            view = page.get_by_label("Inspect component view")
            view.select_option("part")
            expect(view).to_have_value("part")
            canvas = page.locator("canvas")
            # Wait for a rendered demand-loop frame before comparing pixels.
            page.wait_for_timeout(1000)
            before = canvas.screenshot()
            box = canvas.bounding_box()
            assert box
            x, y = box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5
            page.mouse.move(x, y)
            page.mouse.down()
            page.mouse.move(x + 100, y + 30, steps=8)
            page.mouse.up()
            page.wait_for_timeout(300)
            assert canvas.screenshot() != before, "Orbiting should change the isolated view"
            view.select_option("work")
            expect(view).to_have_value("work")
            page.wait_for_timeout(1000)
            assert canvas.screenshot() != before, "The working area should show more than one part"
            page.set_viewport_size({"width": 390, "height": 844})
            label_box = view.bounding_box()
            button_box = page.get_by_role("button", name="Show full model").bounding_box()
            assert label_box and button_box
            assert label_box["x"] >= 0 and label_box["x"] + label_box["width"] <= button_box["x"]
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.get_by_role("button", name="Show full model").click()
            expect(view).to_have_value("")
            view.select_option("work")
            harness.send_chat(page, "Lower the bed by another 30 mm.", "Checking")
            expect(view).to_have_value("")
            harness.send_chat(page, "Add an inspection arm and camera now.", "Checking")
            page.get_by_role("button", name="Upper arm link").click()
            view.select_option("arm")
            expect(view).to_have_value("arm")
            page.get_by_role("button", name="Forearm link").click()
            expect(view).to_have_value("")
            expect(page.get_by_role("button", name="Reset view")).to_be_visible()
            assert not errors, errors
            print("[browser-scene-focus] Isolation, manual orbit, full view, "
                  "revision and selection change passed.")
        finally:
            browser.close()


if __name__ == "__main__":
    harness.STUB_SERVER = Path(__file__).with_name("browser_foundation_server.py")
    harness.run_smoke = run
    raise SystemExit(harness.main())
