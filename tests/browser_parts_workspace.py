"""Offline browser acceptance for visible parts, totals and assembly navigation."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
import browser_smoke as harness  # noqa: E402

OUTPUT = ROOT / ".local/proposal-release"


def serve():
    import browser_foundation_server as foundation
    import uvicorn
    from test_design_workflow import hardware
    from test_microplates import select

    import app.api as api
    from app.cold_transfer import apply_cold_transfer
    from app.design_workflow import refresh_workflow

    initial = refresh_workflow(apply_cold_transfer(select(hardware())))
    api.new_project = lambda: deepcopy(initial)
    args = foundation.baseline.parse_args()
    uvicorn.run(api.app, host="127.0.0.1", port=args.port, log_level="warning")


def run(url):
    from playwright.sync_api import expect, sync_playwright

    OUTPUT.mkdir(parents=True, exist_ok=True)
    checks = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
        errors, proposals = [], []
        page.on(
            "response",
            lambda response: (
                proposals.append(response.json())
                if "/parts?revision=" in response.url and response.ok
                else None
            ),
        )
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route(
            "**/procurement/refresh*",
            lambda route: route.fulfill(
                status=503, json={"detail": "Offline acceptance fixture. Retry refresh."}
            ),
        )
        page.route(
            "**/cost-estimate*",
            lambda route: route.fulfill(json={"state": "not_estimated", "estimate": None}),
        )
        page.goto(url, wait_until="networkidle")
        nav = page.get_by_role("navigation", name="Project workspace", exact=True)
        expect(nav).to_be_visible()
        expect(nav.get_by_role("button", name="Parts & prices", exact=True)).to_be_visible()
        expect(nav.get_by_role("button", name="Assembly", exact=True)).to_be_visible()
        nav.get_by_role("button", name="Parts & prices", exact=True).click()
        table = page.locator(".parts-table")
        expect(table).to_be_visible()
        expect(nav.get_by_role("button", name="Parts & prices", exact=True)).to_have_attribute(
            "aria-current", "page"
        )
        expect(page.locator(".presentation-stage")).not_to_be_visible()
        assert page.locator(".project-resource-anchor").evaluate(
            "(e) => document.activeElement === e"
        )
        find = page.get_by_role("searchbox", name="Find a part")
        total = page.locator(".parts-total strong").inner_text()
        for term in ("refrigerator", "gripper", "plate"):
            find.fill(term)
            expect(table.locator("tbody")).to_contain_text(term, ignore_case=True)
            expect(page.locator(".parts-total strong")).to_have_text(total)
        find.fill("no such laboratory component")
        expect(table).to_contain_text("No matching parts")
        table.get_by_role("button", name="Clear search").click()
        labels = []
        links = set()
        next_page = page.get_by_role("button", name="Next parts page")
        while True:
            labels.extend(table.locator("tbody th > strong").all_inner_texts())
            links.update(table.get_by_role("link").all_inner_texts())
            if next_page.is_disabled():
                break
            next_page.click()
        assert labels == [row["label"] for row in proposals[-1]["rows"]]
        assert {"Purchase / product page", "Source project & files"} <= links
        find.fill("plate")
        page.screenshot(path=str(OUTPUT / "parts-desktop.png"), full_page=False)
        checks.append("direct-visible-parts-plate-fridge-gripper-source-links-focus")
        table.get_by_role("button", name="Show in 3D", exact=True).first.click()
        expect(page.locator(".presentation-stage")).to_be_visible()
        expect(table).to_have_count(0)
        nav.get_by_role("button", name="Parts & prices", exact=True).click()
        expect(table).to_be_visible()
        component_browser = page.get_by_role("region", name="Browse model components")
        component = component_browser.get_by_role("combobox", name="Component", exact=True)
        component.select_option("sample-rack")
        component_browser.get_by_role("button", name="Show in 3D", exact=True).click()
        expect(nav.get_by_role("button", name="3D design", exact=True)).to_have_attribute(
            "aria-current", "page"
        )
        expect(page.get_by_label("Inspect component view")).to_be_visible()
        expect(component_browser).to_have_count(0)
        page.get_by_role("button", name="Expand 3D view", exact=True).click()
        expect(page.get_by_label("Component in expanded view")).to_have_value("sample-rack")
        page.keyboard.press("Escape")
        nav.get_by_role("button", name="Parts & prices", exact=True).click()
        expect(page.locator(".parts-total strong")).to_have_text(total)
        checks.append("select-component-in-parts-and-inspect-same-part-in-3d")
        # Reconcile rendered totals with the actual endpoint, not fixture arithmetic.
        proposal = proposals[-1]
        assert proposal["summary"]["total_low_usd"] == round(
            sum(row["line_total_low_usd"] for row in proposal["rows"]), 2
        )
        assert proposal["summary"]["total_high_usd"] == round(
            sum(row["line_total_high_usd"] for row in proposal["rows"]), 2
        )
        expect(table.locator("tbody tr")).to_have_count(3)
        nav.get_by_role("button", name="Assembly", exact=True).click()
        expect(page.get_by_role("heading", name="Assembly", exact=True)).to_be_visible()
        expect(page.get_by_label("Assembly step", exact=True)).to_be_visible()
        page.screenshot(path=str(OUTPUT / "assembly-desktop.png"), full_page=False)
        checks.append("assembly-direct-numbered-guide-and-downloads")
        nav.get_by_role("button", name="Parts & prices", exact=True).click()
        page.get_by_role("button", name="Refresh US prices", exact=True).click()
        expect(page.get_by_role("alert")).to_contain_text("Offline acceptance fixture")
        expect(table).to_be_visible()
        checks.append("supplier-failure-keeps-planning-table")
        page.get_by_role("button", name="Approve design & open software", exact=True).first.click()
        expect(page.get_by_role("heading", name="Software & protocols", exact=True)).to_be_visible()
        nav.get_by_role("button", name="Parts & prices", exact=True).click()
        expect(table).to_be_visible()
        checks.append("approved-software-return-directly-to-parts")
        page.set_viewport_size({"width": 390, "height": 844})
        nav.get_by_role("button", name="Assembly", exact=True).click()
        expect(page.get_by_label("Assembly step", exact=True)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(OUTPUT / "assembly-mobile.png"), full_page=False)
        nav.get_by_role("button", name="Parts & prices", exact=True).click()
        expect(table).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(OUTPUT / "parts-mobile.png"), full_page=False)
        checks.append("mobile-parts-assembly-direct-navigation-without-page-overflow")
        assert not errors, errors
        (OUTPUT / "checks.json").write_text(
            json.dumps(
                {
                    "checks": checks,
                    "page_errors": errors,
                    "scope": (
                        "Real API/compiler and browser; offline fixtures. No hardware validation."
                    ),
                },
                indent=2,
            )
        )
        browser.close()


if __name__ == "__main__":
    if "--port" in sys.argv:
        serve()
    else:
        harness.STUB_SERVER = Path(__file__).resolve()
        harness.run_smoke = run
        raise SystemExit(harness.main())
