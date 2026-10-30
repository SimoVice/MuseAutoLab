"""Exercise accessible view controls and source loading with offline fixtures."""

import base64
import time
from io import BytesIO
from pathlib import Path

import browser_smoke as harness


def run(url):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("""(() => {
          window.sourceLoadingSeen = false;
          new MutationObserver(() => {
            if (document.querySelector('.scene-loading')) window.sourceLoadingSeen = true;
          }).observe(document, {childList: true, subtree: true});
        })()""")

        def slow_source(route):
            time.sleep(1)
            route.continue_()

        page.route("**/assets/jubilee-*.glb", slow_source)
        page.route("**/api/models?*", lambda route: route.fulfill(json={
            "models": [{
                "id": "muse-spark-1.3-contributor", "label": "Muse Spark", "available": True,
            }],
            "default_model": "muse-spark-1.3-contributor",
            "active_model": "muse-spark-1.3-contributor",
            "capabilities": {
                "voice": {"available": False}, "image": {"available": True, "model": "offline"},
            },
        }))
        captured = []

        def capture_request(route):
            captured.append(base64.b64decode(
                route.request.post_data_json["reference_image_data_url"].split(",", 1)[1]
            ))
            route.fulfill(status=502, json={"detail": "Offline capture test."})

        page.route("**/illustration", capture_request)
        try:
            page.goto(url)
            expect(page.get_by_text("Workspace ready")).to_be_visible()
            harness.send_chat(
                page, "I keep making dilutions manually and want to automate pipetting.",
                "Which equipment",
            )
            harness.send_chat(page, "I have a pipette and microcentrifuge tubes.", "What volumes")
            harness.develop_layout(page)
            page.wait_for_function("window.sourceLoadingSeen", timeout=30000)
            expect(page.locator(".scene-loading")).to_have_count(0, timeout=30000)
            canvas = page.locator("canvas")
            page.wait_for_timeout(2500)
            initial = canvas.screenshot()
            rotate = page.get_by_role("button", name="Rotate left")
            rotate.focus()
            page.keyboard.press("Enter")
            page.wait_for_timeout(300)
            rotated = canvas.screenshot()
            assert rotated != initial, "Keyboard rotation did not change the view"
            page.get_by_role("button", name="Zoom in").focus()
            page.keyboard.press("Space")
            page.wait_for_timeout(300)
            assert canvas.screenshot() != rotated, "Keyboard zoom did not change the view"
            page.get_by_role("button", name="Reset view").click()
            page.wait_for_timeout(700)
            from PIL import Image, ImageChops, ImageStat
            original = Image.open(BytesIO(initial)).convert("RGB")
            reset = Image.open(BytesIO(canvas.screenshot())).convert("RGB")
            difference = ImageStat.Stat(ImageChops.difference(original, reset)).mean
            assert max(difference) < 2, f"Reset did not restore the initial view: {difference}"
            page.locator(".project-details > summary").click()
            page.locator(".illustration-panel > summary").click()
            before_capture = Image.open(BytesIO(canvas.screenshot())).convert("RGB")
            page.get_by_role("button", name="Generate with Muse Image").click()
            expect(page.get_by_text("Offline capture test.")).to_be_visible()
            assert len(captured) == 1
            reference = Image.open(BytesIO(captured[0])).convert("RGB")
            assert max(reference.size) <= 2048, f"Capture exceeded size limit: {reference.size}"
            if reference.size != before_capture.size:
                before_capture = before_capture.resize(reference.size)
            assert max(ImageStat.Stat(reference).stddev) > 5, "Captured image is blank"
            difference = ImageStat.Stat(ImageChops.difference(reference, before_capture)).mean
            assert max(difference) < 3, f"Capture differs from the visible scene: {difference}"
            page.get_by_role("button", name="Custom workflow deck on Jubilee platform").click()
            view = page.get_by_label("Inspect component view")
            view.select_option("part")
            expect(view).to_have_value("part")
            page.get_by_role("button", name="Show full model").click()
            expect(view).to_have_value("")
            page.set_viewport_size({"width": 390, "height": 844})
            controls = page.get_by_role("group", name="3D view controls").bounding_box()
            assert controls and controls["x"] >= 0 and controls["x"] + controls["width"] <= 390
            assert not errors, errors

            failed = browser.new_page(viewport={"width": 1440, "height": 1000})
            failed.route("**/assets/jubilee-*.glb", lambda route: route.abort())
            failed.goto(url)
            expect(failed.get_by_text("Workspace ready")).to_be_visible()
            harness.send_chat(
                failed, "I keep making dilutions manually and want to automate pipetting.",
                "Which equipment",
            )
            harness.send_chat(failed, "I have a pipette and microcentrifuge tubes.", "What volumes")
            harness.develop_layout(failed)
            expect(failed.get_by_text("3D view unavailable.", exact=False)).to_be_visible(
                timeout=30000
            )
            expect(failed.locator(".scene-loading")).to_have_count(0)
            print(
                "[browser-scene-accessibility] Loading and failure, keyboard orbit and zoom, "
                "reset, isolation, mobile controls and nonblank reference capture passed."
            )
        finally:
            browser.close()


if __name__ == "__main__":
    harness.STUB_SERVER = Path(__file__).with_name("browser_foundation_server.py")
    harness.run_smoke = run
    raise SystemExit(harness.main())
