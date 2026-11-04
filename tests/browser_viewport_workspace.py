"""Offline regression for viewport ownership, pinned navigation and reachable controls.

Uses the shared browser runner and synthetic hardware fixture. No model or supplier
request, deployment or physical hardware operation is performed.
"""

import browser_smoke as harness
from playwright.sync_api import expect, sync_playwright


def assert_viewport(page):
    bounds = page.evaluate("""() => ({
        height: innerHeight,
        width: innerWidth,
        documentHeight: document.documentElement.scrollHeight,
        documentWidth: document.documentElement.scrollWidth,
        headerTop: document.querySelector('.topbar').getBoundingClientRect().top,
        navigationTop: document.querySelector('.software-route-nav').getBoundingClientRect().top,
    })""")
    assert bounds["documentHeight"] <= bounds["height"] + 1, bounds
    assert bounds["documentWidth"] <= bounds["width"] + 1, bounds
    assert bounds["headerTop"] == 0, bounds
    assert bounds["navigationTop"] >= 0, bounds


def run(url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page(reduced_motion="reduce")
            page.route(
                "**/cost-estimate*",
                lambda route: route.fulfill(json={"state": "not_estimated", "estimate": None}),
            )
            page.route("**/procurement/refresh*", lambda route: route.abort())
            page.goto(url, wait_until="networkidle")
            expect(
                page.get_by_role("button", name="Approve design & open software")
            ).to_be_visible()
            for width, height in [
                (1440, 900), (1280, 720), (1366, 768), (1280, 600), (390, 844), (390, 600),
            ]:
                page.set_viewport_size({"width": width, "height": height})
                for destination in ["3D design", "Parts & prices", "Assembly"]:
                    page.get_by_role("button", name=destination, exact=True).click()
                    if width < 1000:
                        page.get_by_role("button", name="Design", exact=True).click()
                    if destination == "3D design":
                        stage = page.locator(".presentation-stage")
                        canvas = stage.locator("canvas")
                        expect(canvas).to_be_visible()
                        expect(page.locator(".design-budget-entry:visible")).to_have_count(0)
                        expect(page.locator(".parts-component-browser:visible")).to_have_count(0)
                        if width >= 1000 or height >= 700:
                            design = page.locator("#design-workspace").bounding_box()
                            model = canvas.bounding_box()
                            assert design and model
                            assert model["height"] >= design["height"] / 2, (design, model)
                        stage.get_by_role("button", name="Rotate left", exact=True).click()
                        stage.get_by_role("button", name="Reset view", exact=True).click()
                        motion = stage.get_by_role("button", name="Motion preview", exact=True)
                        motion.click()
                        page.get_by_role("button", name="Play", exact=True).first.click()
                        page.get_by_role("button", name="Reset", exact=True).first.click()
                        motion.click()
                    else:
                        page.locator(".project-resource-anchor").evaluate(
                            "element => { element.scrollTop = element.scrollHeight; }"
                        )
                    assert_viewport(page)
                if width < 1000:
                    page.get_by_role("button", name="Chat", exact=True).click()
                composer = page.get_by_label("Describe your workflow or request a change")
                composer.click()
                bounds = composer.bounding_box()
                assert bounds and 0 <= bounds["y"] < bounds["y"] + bounds["height"] <= height
                assert_viewport(page)

            page.get_by_role("button", name="Approve design & open software").click()
            expect(
                page.get_by_role("heading", name="Software & protocols", exact=True)
            ).to_be_visible()
            for width, height in [(1366, 768), (1280, 600), (390, 844)]:
                page.set_viewport_size({"width": width, "height": height})
                panels = page.get_by_role("navigation", name="Software workspace panel")
                if panels.is_visible():
                    panels.get_by_role("button", name="Generated program", exact=True).click()
                    expect(page.get_by_role("heading", name="Protocol preview")).to_be_visible()
                    panels.get_by_role("button", name="3D preview", exact=True).click()
                page.get_by_role("button", name="Play", exact=True).first.click()
                page.get_by_role("button", name="Reset", exact=True).first.click()
                assert_viewport(page)
        finally:
            browser.close()


if __name__ == "__main__":
    harness.STUB_SERVER = harness.ROOT / "tests/browser_hardware_software.py"
    harness.run_smoke = run
    raise SystemExit(harness.main())
