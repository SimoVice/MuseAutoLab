"""Offline real-app software guidance, read-only access and protocol downloads."""

import json

import browser_smoke as harness
from playwright.sync_api import expect, sync_playwright

OUTPUT = harness.ROOT / ".local/software-guidance-20261031/browser"


def run(url):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        # Cost is unrelated to this check; prevent any estimate-provider request.
        page.route(
            "**/cost-estimate*",
            lambda route: route.fulfill(
                json={
                    "state": "current",
                    "estimate": {"status": "failed", "rows": [], "exclusions": []},
                }
            ),
        )
        page.goto(url, wait_until="networkidle")
        expect(page.get_by_text("Workspace ready")).to_be_visible()
        page.get_by_label("Open saved project").set_input_files(
            str(harness.ROOT / "docs/examples/microplate-project.json")
        )
        expect(page.locator(".prep-plan")).to_be_visible()

        def snapshot():
            with page.expect_download() as captured:
                page.get_by_role("button", name="Save project", exact=True).click()
            value = json.loads(captured.value.path().read_text(encoding="utf-8"))
            value.pop("saved_at", None)
            return value

        original = snapshot()
        with page.expect_response(lambda response: "/instructions?" in response.url) as response:
            page.get_by_role("button", name="Software & protocols", exact=False).click()
        guide = response.value.json()
        panel = page.locator("#software-protocols-panel")
        expect(
            panel.get_by_role("heading", name="Software & protocols", exact=True)
        ).to_be_visible()
        expect(panel).to_contain_text("Science Jubilee")
        expect(panel).to_contain_text("protocol-preview.py protocol-template.json")
        expect(panel.get_by_role("link", name="Download protocol template")).to_be_visible()
        panel.locator("summary", has_text="Scope and source documentation").click()
        expect(panel.get_by_role("link", name="Science Jubilee getting started")).to_have_attribute(
            "href", "https://science-jubilee.readthedocs.io/en/latest/getting_started/index.html"
        )
        for name, filename in [
            ("Download protocol template", "protocol-template.json"),
            ("Download local preview", "protocol-preview.py"),
        ]:
            with page.expect_download() as captured:
                panel.get_by_role("link", name=name, exact=True).click()
            captured.value.save_as(OUTPUT / filename)
        configuration = json.loads((OUTPUT / "protocol-template.json").read_text())
        assert configuration == guide["software_guidance"]["protocol_template"]
        assert configuration["execution_enabled"] is False
        assert configuration["current_preparation"]["target_count"] == 3
        assert all(
            t["total_volume_ul"] == 200 for t in configuration["current_preparation"]["transfers"]
        )
        panel.screenshot(path=str(OUTPUT / "software-desktop.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        page.get_by_role("navigation", name="Workspace view").get_by_role(
            "button", name="Design", exact=True
        ).click()
        panel.scroll_into_view_if_needed()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
        panel.screenshot(path=str(OUTPUT / "software-mobile.png"))
        page.get_by_role("button", name="Build instructions", exact=False).click()
        page.get_by_role("button", name="Open software & protocols", exact=True).click()
        expect(panel).to_be_visible()
        assert snapshot() == original
        assert not errors, errors
        (OUTPUT / "result.json").write_text(
            json.dumps(
                {
                    "status": "passed",
                    "scope": "Offline real browser/API/compiler; no inference",
                    "read_only_project_preserved": True,
                    "download_matches_guide": True,
                    "mobile_no_document_overflow": True,
                    "page_errors": errors,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        browser.close()


if __name__ == "__main__":
    harness.run_smoke = run
    raise SystemExit(harness.main())
