"""Offline browser regression: one persistent model-estimate driver per project."""

from __future__ import annotations

import asyncio
import json
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
import browser_smoke as harness  # noqa: E402

OUTPUT = ROOT / ".local/proposal-release/cost-driver"


def serve():
    import browser_foundation_server as foundation
    import uvicorn
    from fastapi import HTTPException
    from test_design_workflow import hardware
    from test_microplates import select

    import app.api as api
    import app.price_estimation as prices
    from app.design_workflow import refresh_workflow

    initial = refresh_workflow(select(hardware()))
    api.new_project = lambda: deepcopy(initial)
    calls = 0

    async def offline_estimate(project, procurement=None, **kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.3)
        if calls == 2:
            raise HTTPException(503, "Synthetic estimate outage. Retry the model estimate.")
        estimate = prices.unestimated_cost(project, procurement)
        for row in estimate["rows"]:
            if row["source_kind"] == "unknown":
                row.update(
                    source_kind="model_estimate",
                    low_usd=11 * calls,
                    high_usd=22 * calls,
                    rationale="Synthetic model range.",
                    assumptions=["Offline fixture only."],
                    issue=None,
                )
        estimate.update(
            status="ready",
            issue=None,
            estimate_id=f"offline-{calls}",
            generated_at=datetime.now(UTC).isoformat(),
            expires_at=(datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
        )
        prices._summarize(estimate)
        return estimate

    prices.estimate_project_prices = offline_estimate
    args = foundation.baseline.parse_args()
    uvicorn.run(api.app, host="127.0.0.1", port=args.port, log_level="warning")


def run(url):
    from playwright.sync_api import expect, sync_playwright

    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        posts, proposals = [], []
        page.on(
            "response",
            lambda response: (
                proposals.append(response.json())
                if "/parts?revision=" in response.url and response.ok
                else None
            ),
        )
        page.on(
            "request",
            lambda request: (
                posts.append(request.post_data_json)
                if request.url.endswith("/cost-estimate") and request.method == "POST"
                else None
            ),
        )
        pending_estimate = []

        def hold_first_estimate(route):
            if route.request.method == "POST" and not pending_estimate:
                pending_estimate.append(route)
            else:
                route.continue_()

        page.route("**/cost-estimate*", hold_first_estimate)
        page.goto(url, wait_until="domcontentloaded")
        nav = page.get_by_role("navigation", name="Project workspace", exact=True)
        nav.get_by_role("button", name="Parts & prices", exact=True).click()
        expect(page.locator(".parts-table")).to_be_visible()
        assert any(
            any(row["price_kind"] == "planning_allowance" for row in proposal["rows"])
            for proposal in proposals
        ), "Parts must remain usable while the first estimate is pending"
        assert len(pending_estimate) == 1
        pending_estimate[0].continue_()
        expect(page.locator(".parts-table")).to_contain_text("Model estimate")
        expect(page.locator(".parts-table tbody")).to_contain_text("$11 to $22")
        assert len(posts) == 1, posts
        for destination in ("Assembly", "3D design", "Parts & prices"):
            nav.get_by_role("button", name=destination, exact=True).click()
        expect(page.locator(".parts-table")).to_contain_text("Model estimate")
        page.wait_for_load_state("networkidle")
        assert len(posts) == 1, posts
        page.get_by_role("button", name="Refresh model estimate", exact=True).click()
        expect(page.get_by_role("button", name="Retry model estimate", exact=True)).to_be_enabled()
        expect(page.locator(".parts-table")).to_be_visible()
        assert len(posts) == 2
        page.get_by_role("button", name="Retry model estimate", exact=True).click()
        expect(page.locator(".parts-table tbody")).to_contain_text("$33 to $66")
        assert len(posts) == 3
        nav.get_by_role("button", name="3D design", exact=True).click()
        expect(page.locator(".presentation-stage")).to_be_visible()
        expect(page.locator(".design-budget-entry")).to_have_count(0)
        assert len(posts) == 3
        nav.get_by_role("button", name="Parts & prices", exact=True).click()
        expect(page.locator(".parts-total strong")).to_contain_text("$")
        expect(page.locator(".parts-table tbody")).to_contain_text("$33 to $66")
        assert len(posts) == 3
        page.screenshot(path=str(OUTPUT / "model-prices.png"))
        (OUTPUT / "checks.json").write_text(
            json.dumps(
                {
                    "posts": posts,
                    "checks": [
                        "automatic-model-estimate",
                        "same-revision-table-refresh",
                        "no-tab-switch-duplicate-post",
                        "failure-keeps-prices",
                        "explicit-retry",
                        "latest-prices-and-total-in-parts-workspace",
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        browser.close()


if __name__ == "__main__":
    if "--port" in sys.argv:
        serve()
    else:
        harness.STUB_SERVER = Path(__file__).resolve()
        harness.run_smoke = run
        raise SystemExit(harness.main())
