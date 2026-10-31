"""Offline browser checks for conversational workspace hierarchy and cost states."""

import json

import browser_smoke as harness
from playwright.sync_api import expect, sync_playwright

OUTPUT = harness.ROOT / ".local/usability-20261031"


def run(url):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        calls = []

        def cost(route):
            calls.append(route.request.method)
            # Deliberately synthetic UI fixture: no real model request or pricing claim.
            project_id = route.request.url.split("/projects/")[1].split("/")[0]
            revision = (
                int(route.request.url.split("revision=")[1])
                if route.request.method == "GET"
                else route.request.post_data_json["project_revision"]
            )
            estimate = {
                "project_id": project_id,
                "project_revision": revision,
                "status": "partial",
                "summary": {
                    "verified_subtotal_usd": 45,
                    "estimated_additional_low_usd": 120,
                    "estimated_additional_high_usd": 180,
                    "project_total_low_usd": None,
                    "project_total_high_usd": None,
                    "missing_count": 2,
                    "estimated_count": 1,
                    "verified_count": 1,
                    "coverage_complete": False,
                },
                "rows": [],
                "exclusions": ["shipping", "taxes"],
            }
            if route.request.method == "GET":
                route.fulfill(json={"estimate": None, "state": "not_requested"})
            else:
                route.fulfill(json={"estimate": estimate, "state": "current"})

        page.route("**/cost-estimate*", cost)
        page.goto(url, wait_until="networkidle")
        expect(page.get_by_text("Workspace ready")).to_be_visible()
        title_size = page.locator("#design-title").evaluate(
            "e => parseFloat(getComputedStyle(e).fontSize)"
        )
        assert 23 <= title_size <= 28, title_size
        expect(page.get_by_text("Estimate appears with your design")).to_be_visible()
        page.set_viewport_size({"width": 390, "height": 844})
        chat_view = page.get_by_role("navigation", name="Workspace view")
        expect(chat_view.get_by_role("button", name="Chat", exact=True)).to_have_attribute(
            "aria-pressed", "true"
        )
        expect(chat_view.get_by_role("button", name="Design", exact=True)).to_be_disabled()
        composer = page.get_by_label("Describe your workflow or request a change")
        expect(composer).to_be_visible()
        composer_bounds = composer.bounding_box()
        assert composer_bounds and composer_bounds["y"] + composer_bounds["height"] <= 844, (
            composer_bounds
        )
        page.screenshot(path=str(OUTPUT / "blank-project-mobile.png"))
        harness.send_chat(
            page,
            "I keep making dilutions manually and want to automate pipetting.",
            "Which equipment",
        )
        expect(composer).to_be_enabled()
        expect(composer).to_be_visible()
        expect(chat_view.get_by_role("button", name="Chat", exact=True)).to_have_attribute(
            "aria-pressed", "true"
        )
        expect(page.locator(".conversation-scroll")).to_contain_text(
            "I keep making dilutions manually and want to automate pipetting."
        )
        page.screenshot(path=str(OUTPUT / "first-request-mobile.png"))
        page.set_viewport_size({"width": 1440, "height": 1000})
        fixture = json.loads((harness.ROOT / "docs/examples/microplate-project.json").read_text())
        fixture["history"] = [
            {
                "role": "user",
                "content": (
                    "Use a 96-well plate for the same three targets. "
                    "Keep the preparation volumes and the rest of the workstation unchanged."
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "The plate reference and custom holder are ready for review. "
                    "Your three targets and 200 µL final volume are preserved. "
                    "Review the preparation plan beside the cost estimate on the left. "
                    "Physical fit and pipette access still need verification."
                ),
            },
        ]
        page.get_by_label("Open saved project").set_input_files(
            {
                "name": "synthetic-usability-project.json",
                "mimeType": "application/json",
                "buffer": json.dumps(fixture).encode(),
            }
        )
        expect(page.locator(".cost-summary strong").first).to_have_text("Partial cost estimate")
        expect(page.locator(".conversation-panel .prep-plan")).to_have_count(0)
        expect(page.locator(".design-panel .prep-plan")).to_have_count(1)
        expect(page.locator(".model-settings")).not_to_have_attribute("open", "")
        expect(page.locator(".model-data-note")).to_be_visible()
        page.locator(".model-settings > summary").click()
        expect(page.get_by_label("Agent model")).to_be_visible()
        page.locator(".model-settings > summary").click()
        plan = page.locator(".prep-plan")
        plan.locator(":scope > summary").click()
        expect(plan.locator(".plan-table")).to_be_visible()
        expect(page.locator(".cost-summary")).to_contain_text("$120–$180")
        expect(page.locator(".cost-summary")).to_contain_text("2 groups")
        plan.scroll_into_view_if_needed()
        page.screenshot(path=str(OUTPUT / "workspace-plan-desktop.png"))
        plan.locator(":scope > summary").click()
        for height in [900, 1000]:
            page.set_viewport_size({"width": 1440, "height": height})
            page.wait_for_timeout(450)
            page.locator(".design-panel").evaluate("element => element.scrollTop = 0")
            for locator in [plan.locator(":scope > summary"), page.locator(".cost-breakdown")]:
                bounds = locator.bounding_box()
                assert bounds and bounds["y"] + bounds["height"] <= height, bounds
            page.screenshot(path=str(OUTPUT / f"workspace-desktop-{height}.png"))
        page.screenshot(path=str(OUTPUT / "workspace-desktop.png"))
        page.get_by_role("button", name="Expand 3D view", exact=True).click()
        expect(page.get_by_role("dialog")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog")).to_have_count(0)
        plan.locator(":scope > summary").click()
        for width in [390, 760]:
            page.set_viewport_size({"width": width, "height": 844})
            chat_view.get_by_role("button", name="Design", exact=True).click()
            page.locator(".prep-plan").scroll_into_view_if_needed()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
                "Horizontal page overflow"
            )
            page.screenshot(path=str(OUTPUT / f"workspace-mobile-{width}.png"))
            chat_view.get_by_role("button", name="Chat", exact=True).click()
            expect(composer).to_be_visible()
            composer.fill("Keep this unsent revision while I inspect the design.")
            history = page.locator(".message-row").all_text_contents()
            chat_view.get_by_role("button", name="Design", exact=True).click()
            expect(composer).not_to_be_visible()
            chat_view.get_by_role("button", name="Chat", exact=True).click()
            expect(composer).to_have_value("Keep this unsent revision while I inspect the design.")
            assert page.locator(".message-row").all_text_contents() == history
            chat_view.get_by_role("button", name="Design", exact=True).click()
        assert calls == ["GET", "POST"], calls
        assert not errors, errors
        (OUTPUT / "usability-result.json").write_text(
            json.dumps(
                {
                    "status": "passed",
                    "cost_requests": calls,
                    "scope": (
                        "Offline synthetic cost fixture; real browser/compiler; "
                        "no inference or physical validation"
                    ),
                },
                indent=2,
            )
        )
        # Isolated component fixture exercises freshness without inference or changing a project.
        freshness = browser.new_page()
        freshness.on("pageerror", lambda error: print("Lifecycle fixture:", error))
        freshness.on(
            "response",
            lambda response: (
                print("Lifecycle HTTP", response.status, response.url)
                if response.status >= 400
                else None
            ),
        )
        freshness.clock.install()
        refresh_calls = []
        expired = False

        def lifecycle(route):
            nonlocal expired
            method = route.request.method
            refresh_calls.append(
                (method, route.request.post_data_json if method == "POST" else None)
            )
            value = {
                "project_id": "fixture",
                "project_revision": 1,
                "status": "failed" if expired else "partial",
                "expires_at": freshness.evaluate("new Date(Date.now()+60000).toISOString()"),
                "summary": {
                    "verified_subtotal_usd": 45,
                    "verified_count": 1,
                    "estimated_additional_low_usd": 120,
                    "estimated_additional_high_usd": 180,
                    "missing_count": 2,
                    "coverage_complete": False,
                },
                "rows": [],
                "exclusions": [],
            }
            route.fulfill(
                json={
                    "estimate": value,
                    "state": "stale" if expired and method == "GET" else "current",
                }
            )

        freshness.route("**/cost-estimate*", lifecycle)
        freshness.route(
            "**/cost-summary-test",
            lambda route: route.fulfill(
                content_type="text/html",
                body="""<div id="root"></div><script type="module">
            import React from '/node_modules/.vite/deps/react.js';
            import ReactDOM from '/node_modules/.vite/deps/react-dom_client.js';
            const {createRoot}=ReactDOM;
            import RefreshRuntime from '/@react-refresh';
            RefreshRuntime.injectIntoGlobalHook(window);
            window.$RefreshReg$=()=>{}; window.$RefreshSig$=()=>type=>type;
            window.__vite_plugin_react_preamble_installed__=true;
            const {default: CostSummary}=await import('/src/CostSummary.tsx');
            function Test() {
              const [report,setReport]=React.useState(null); window.updateReport=setReport;
              return React.createElement(CostSummary,{project:{id:'fixture',revision:1,
                engineering_design:{}},report});
            }
            createRoot(document.getElementById('root')).render(React.createElement(Test));
            </script>""",
            ),
        )
        freshness.goto(url.rstrip("/") + "/cost-summary-test", wait_until="networkidle")
        expect(freshness.locator(".cost-summary")).to_contain_text("$120–$180")
        freshness.locator(".cost-estimate-details > summary").click()
        with freshness.expect_response(
            lambda response: "/cost-estimate" in response.url and response.request.method == "POST"
        ):
            freshness.get_by_role("button", name="Refresh cost estimate").click()
        expect(freshness.locator(".cost-summary")).to_have_attribute("aria-busy", "false")
        assert refresh_calls[-1] == ("POST", {"project_revision": 1, "force": True}), refresh_calls
        report = {
            "report_id": "same-id",
            "expires_at": "2099-01-01T00:00:00Z",
            "coverage": {"fresh_priced_count": 1},
            "known_partial_subtotal": 99,
        }
        freshness.evaluate("report => window.updateReport(report)", report)
        expect(freshness.locator(".cost-breakdown")).to_contain_text("$99")
        expect(freshness.locator(".cost-summary")).to_have_attribute("aria-busy", "false")
        report["coverage"]["fresh_priced_count"] = 0
        report["known_partial_subtotal"] = 0
        freshness.evaluate("report => window.updateReport(report)", report)
        expect(freshness.locator(".cost-breakdown")).not_to_contain_text("$99")
        expect(freshness.locator(".cost-summary")).to_have_attribute("aria-busy", "false")
        assert refresh_calls[-1][0] == "GET", refresh_calls
        expired = True
        freshness.clock.fast_forward(61000)
        expect(freshness.locator(".cost-summary > strong")).to_have_text("Estimate unavailable")
        expect(freshness.locator(".cost-breakdown")).not_to_contain_text("$120")
        assert refresh_calls[-1] == ("POST", {"project_revision": 1, "force": False}), refresh_calls
        count = len(refresh_calls)
        freshness.clock.fast_forward(120000)
        assert len(refresh_calls) == count, refresh_calls
        freshness.close()
        browser.close()


if __name__ == "__main__":
    harness.run_smoke = run
    raise SystemExit(harness.main())
