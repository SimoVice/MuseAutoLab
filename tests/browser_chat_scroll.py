"""Offline regression: long replies open at the start; status updates preserve reading."""

import browser_smoke as harness
from playwright.sync_api import expect, sync_playwright


def run(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 768}, reduced_motion="reduce")
        pending = []
        opened = []
        def record_open(response):
            if response.url.endswith("/open") and response.ok:
                opened.append(response.json()["project"])

        page.on("response", record_open)
        page.route(
            "**/cost-estimate*",
            lambda r: r.fulfill(json={"state": "not_estimated", "estimate": None}),
        )
        page.route("**/messages", lambda r: pending.append(r))
        page.goto(url, wait_until="networkidle")
        page.get_by_label("Open saved project").set_input_files(
            str(harness.ROOT / "docs/examples/microplate-project.json")
        )
        composer = page.get_by_label("Describe your workflow or request a change")
        expect(composer).to_be_enabled()
        metrics = """() => {
            const s = document.querySelector('.conversation-scroll');
            const m = [...s.querySelectorAll('.message-row')].at(-1);
            return {
                top: m.getBoundingClientRect().top - s.getBoundingClientRect().top,
                bottom: m.getBoundingClientRect().bottom - s.getBoundingClientRect().bottom,
                height: m.offsetHeight,
                viewport: s.clientHeight,
            };
        }"""
        initial = page.evaluate(metrics)
        assert initial["height"] > initial["viewport"] and 0 <= initial["top"] <= 20, initial
        for text in [
            "Review complete.",
            "## Review\n\n" + "Check this specification before proceeding.\n\n" * 30,
        ]:
            composer.fill("Review this synthetic fixture.")
            page.get_by_role("button", name="Send message", exact=True).click()
            expect(page.locator(".agent-activity")).to_be_visible()
            pending.pop().fulfill(json={"project": opened[-1], "assistant_message": text})
            expect(composer).to_be_enabled()
            result = page.evaluate(metrics)
            if result["height"] > result["viewport"]:
                assert 0 <= result["top"] <= 20, result
            else:
                assert result["bottom"] <= 0, result
        composer.fill("Review a request that fails safely.")
        page.get_by_role("button", name="Send message", exact=True).click()
        expect(page.locator(".agent-activity")).to_be_visible()
        page.locator(".conversation-scroll").evaluate("e => {e.scrollTop = 0;}")
        pending.pop().fulfill(status=502, json={"detail": "Synthetic request failure."})
        expect(page.get_by_role("alert")).to_contain_text("Synthetic request failure")
        assert page.locator(".conversation-scroll").evaluate("e => e.scrollTop") == 0
        browser.close()


if __name__ == "__main__":
    harness.run_smoke = run
    raise SystemExit(harness.main())
