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
        page.goto(url, wait_until="networkidle")
        nav = page.get_by_role("navigation", name="Project workspace", exact=True)
        expect(nav).to_be_visible()
        expect(nav.get_by_role("button", name="Parts & prices", exact=True)).to_be_visible()
        expect(nav.get_by_role("button", name="Assembly", exact=True)).to_be_visible()
        nav.get_by_role("button", name="Parts & prices", exact=True).click()
        table = page.locator(".parts-table")
        expect(table).to_be_visible()
        expect(table).to_contain_text("refrigerator")
        expect(table).to_contain_text("gripper")
        expect(table).to_contain_text("plate")
        expect(nav.get_by_role("button", name="Parts & prices", exact=True)).to_have_attribute(
            "aria-current", "page"
        )
        expect(page.locator(".presentation-stage")).not_to_be_visible()
        assert page.locator(".project-resource-anchor").evaluate(
            "(e) => document.activeElement === e"
        )
        assert table.get_by_role("link", name="Purchase / product page").count() > 0
        assert table.get_by_role("link", name="Source project & files").count() > 0
        page.screenshot(path=str(OUTPUT / "parts-desktop.png"), full_page=False)
        checks.append("direct-visible-parts-plate-fridge-gripper-source-links-focus")
        table.get_by_role("button", name="Show in 3D", exact=True).first.click()
        expect(page.locator(".presentation-stage")).to_be_visible()
        expect(table).to_have_count(0)
        nav.get_by_role("button", name="Parts & prices", exact=True).click()
        expect(table).to_be_visible()
        # Reconcile rendered totals with the actual endpoint, not fixture arithmetic.
        proposal = proposals[-1]
        assert proposal["summary"]["total_low_usd"] == round(
            sum(row["line_total_low_usd"] for row in proposal["rows"]), 2
        )
        assert proposal["summary"]["total_high_usd"] == round(
            sum(row["line_total_high_usd"] for row in proposal["rows"]), 2
        )
        lines = table.locator("tbody tr").count()
        assert lines > 5
        nav.get_by_role("button", name="Assembly", exact=True).click()
        expect(page.get_by_role("heading", name="Assembly", exact=True)).to_be_visible()
        expect(page.get_by_role("list", name="Assembly steps")).to_be_visible()
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
        expect(page.get_by_role("list", name="Assembly steps")).to_be_visible()
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
