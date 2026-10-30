"""Pricing and instruction UX with offline catalog fixtures and real saved projects.

No supplier, Meta, purchase or heavy CAD calls are made. The normal project API,
canonical instruction builder, revision changes and browser rendering are real.
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import browser_smoke as harness  # noqa: E402

from app.instructions import build_instruction_guide  # noqa: E402


def run(url):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        errors, projects, refreshes, cache_reads = [], [], [], []
        state = {
            "report": None,
            "fail": False,
            "bad_guide": False,
            "bad_report": False,
            "short_ttl": False,
            "fail_cache": False,
        }
        page.on("pageerror", lambda error: errors.append(str(error)))

        def record(response):
            if response.url.endswith(("/messages", "/open")) and response.ok:
                projects.append(response.json()["project"])

        page.on("response", record)

        def catalog(route):
            request = route.request
            query = parse_qs(urlsplit(request.url).query)
            report = state["report"]
            if "/download" in request.url:
                assert report and query["revision"] == [str(report["project_revision"])]
                assert query["report_id"] == [report["report_id"]]
                route.fulfill(
                    body=json.dumps(report),
                    content_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="pricing.json"'},
                )
                return
            if request.method == "POST":
                refreshes.append(request.post_data_json)
                if state["fail"]:
                    route.fulfill(
                        status=503,
                        json={"detail": "Supplier connection unavailable. Retry refresh."},
                    )
                    return
                project = projects[-1]
                row = {
                    "group_id": "camera",
                    "component_ids": ["controller"],
                    "selected_id": "fixture-camera",
                    "label": "Fixture catalog camera",
                    "sku": "FIXTURE-001",
                    "quantity": 2,
                    "pack_size": 1,
                    "pack_count": 2,
                    "unit_price": 25.0,
                    "line_total": 50.0,
                    "currency": "USD",
                    "status": "priced",
                    "freshness": "fresh",
                    "availability": "Listed; physical compatibility unverified",
                    "price_source_url": "https://www.raspberrypi.com/products/camera-module-3/",
                    "availability_source_url": None,
                    "fetched_at": "2026-10-30T10:00:00Z",
                    "last_known_price": None,
                    "last_known_fetched_at": None,
                    "issue": None,
                    "is_candidate": True,
                    "compatibility_note": "Catalog candidate; validate interface before purchase.",
                    "source_bom_url": "https://github.com/machineagency/jubilee",
                    "source_bom_row": "Camera fixture row",
                }
                report = {
                    "report_id": "offline-report",
                    "project_id": project["id"],
                    "project_revision": project["revision"],
                    "market": "US",
                    "currency": "USD",
                    "fetched_at": "2026-10-30T10:00:00Z",
                    "expires_at": (datetime.now(UTC) + timedelta(seconds=0.7)).isoformat()
                    if state["short_ttl"]
                    else "2099-10-31T10:00:00Z",
                    "rows": [
                        row,
                        {
                            **row,
                            "group_id": "motor",
                            "label": "Fixture last-known motor",
                            "status": "missing",
                            "freshness": "stale",
                            "unit_price": None,
                            "line_total": None,
                            "last_known_price": 15,
                            "last_known_line_total": 30,
                            "last_known_fetched_at": "2026-10-28T10:00:00Z",
                            "issue": "Current page could not be checked.",
                        },
                        {
                            **row,
                            "group_id": "custom",
                            "label": "Custom mount fabrication",
                            "sku": None,
                            "status": "quote_needed",
                            "freshness": "unverified",
                            "unit_price": None,
                            "line_total": None,
                            "issue": "Specify material and mounting before requesting a quote.",
                        },
                    ],
                    "coverage": {
                        "row_count": 3,
                        "fresh_priced_count": 1,
                        "stale_priced_count": 1,
                        "unpriced_count": 2,
                    },
                    "known_partial_subtotal": 50,
                    "stale_last_known_subtotal": 30,
                    "exclusions": [
                        "Shipping and taxes",
                        "Custom fabrication",
                        "Complete platform hardware",
                    ],
                }
                state["report"] = report
            else:
                cache_reads.append(request.url)
                if state["fail_cache"]:
                    route.fulfill(
                        status=503, json={"detail": "Saved report temporarily unavailable."}
                    )
                    return
            revision = int(query.get("revision", [projects[-1]["revision"] if projects else 0])[0])
            current = (
                report
                and report["project_id"] == request.url.split("/projects/")[1].split("/")[0]
                and report["project_revision"] == revision
            )
            route.fulfill(
                json={
                    "report": report,
                    "state": "current"
                    if current
                    else "stale_revision"
                    if report
                    else "not_refreshed",
                }
            )

        def instructions(route):
            project = projects[-1]
            report = state["report"]
            if report and (
                report["project_id"] != project["id"]
                or report["project_revision"] != project["revision"]
            ):
                report = None
            guide = build_instruction_guide(project, report)
            if state["bad_guide"]:
                guide["project_revision"] -= 1
            if state["bad_report"]:
                guide["procurement_report_id"] = "external-refresh-report"
            if "/download" in route.request.url:
                route.fulfill(
                    body=json.dumps(guide),
                    content_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="guide.json"'},
                )
            else:
                route.fulfill(json=guide)

        page.route("**/procurement**", catalog)
        page.route("**/instructions**", instructions)
        try:
            page.goto(url)
            page.wait_for_load_state("networkidle")
            harness.send_chat(
                page,
                "I keep making dilutions manually and want to automate pipetting.",
                "Which equipment",
            )
            harness.send_chat(page, "I have a pipette and microcentrifuge tubes.", "What volumes")
            harness.develop_layout(page)
            resources = page.locator(".project-resources")
            expect(resources).to_be_visible()
            expect(page.locator(".cost-block")).to_contain_text("Not refreshed")
            parts_button = resources.get_by_role("button", name="Parts & pricing")
            parts_button.focus()
            page.keyboard.press("Enter")
            expect(resources).to_contain_text("No prices checked for this revision")
            assert not refreshes, "Opening the panel must never fetch supplier pages"
            page.get_by_role("button", name="Refresh US prices", exact=True).click()
            expect(resources.locator(".pricing-summary")).to_contain_text("$50.00")
            expect(resources).to_contain_text("1 of 3 groups freshly priced")
            expect(resources).to_contain_text("Last-known prices, excluded")
            expect(resources).to_contain_text("$30.00")
            expect(resources).to_contain_text("Quote needed")
            expect(resources).to_contain_text("FIXTURE-001")
            expect(resources).to_contain_text("Sourcing candidate for review")
            expect(page.locator(".cost-block")).to_contain_text("Complete machine cost unknown")
            with page.expect_download() as download:
                page.get_by_role("link", name="Download pricing JSON").click()
            assert download.value.suggested_filename
            assert "report_id=offline-report" in download.value.url
            state["fail"] = True
            page.get_by_role("button", name="Refresh US prices", exact=True).click()
            expect(resources.get_by_role("alert")).to_contain_text("previous report is retained")
            expect(resources.locator(".pricing-summary")).to_contain_text("$50.00")
            page.get_by_role("button", name="Build instructions").click()
            expect(resources.locator(".instruction-step")).to_be_visible()
            expect(resources).to_contain_text("require design work")
            expect(resources.get_by_role("link", name="Download guide HTML")).to_be_visible()
            page.get_by_role("button", name="Next step").click()
            expect(resources).to_contain_text("Step 2 of")
            if resources.get_by_role("button", name="Show", exact=False).count():
                resources.get_by_role("button", name="Show", exact=False).first.click()
                expect(page.locator(".selection-block")).not_to_contain_text("Select a component")
            state["bad_report"] = True
            page.get_by_role("button", name="Build instructions").click()
            page.get_by_role("button", name="Build instructions").click()
            expect(resources.get_by_role("alert")).to_contain_text("pricing report changed")
            expect(resources.get_by_role("link", name="Download guide HTML")).to_have_count(0)
            state["bad_report"] = False
            page.get_by_role("button", name="Try instructions again").click()
            expect(resources.locator(".instruction-step")).to_be_visible()
            with page.expect_download() as saved:
                page.get_by_role("button", name="Save project", exact=True).click()
            page.get_by_label("Open saved project").set_input_files(saved.value.path())
            expect(page.locator(".storage-notice")).to_contain_text("rebuilt")
            expect(page.locator(".cost-block")).to_contain_text("Not refreshed")
            page.get_by_role("button", name="Parts & pricing").click()
            expect(resources).to_contain_text("downloads are disabled")
            expect(resources.get_by_role("link", name="Download pricing JSON")).to_have_count(0)
            state["bad_guide"] = True
            page.get_by_role("button", name="Build instructions").click()
            expect(resources.get_by_role("alert")).to_contain_text("earlier revision")
            expect(resources.get_by_role("link", name="Download guide HTML")).to_have_count(0)
            state["bad_guide"] = False
            page.get_by_role("button", name="Try instructions again").click()
            expect(resources.locator(".instruction-step")).to_be_visible()
            state["fail"] = False
            page.get_by_role("button", name="Parts & pricing").click()
            page.get_by_role("button", name="Refresh US prices", exact=True).click()
            expect(resources.locator(".pricing-summary")).to_contain_text("$50.00")
            harness.send_chat(page, "Lower the bed by another 30 mm.", "Checking")
            expect(page.locator(".cost-block")).to_contain_text("Not refreshed")
            page.get_by_role("button", name="Parts & pricing").click()
            expect(resources).to_contain_text("downloads are disabled")
            expect(resources.get_by_role("link", name="Download pricing JSON")).to_have_count(0)
            page.set_viewport_size({"width": 390, "height": 844})
            page.get_by_role("button", name="Build instructions").click()
            expect(resources.locator(".instruction-step")).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
            page.unroute("**/instructions**", instructions)
            state["report"] = None
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            page.get_by_role("button", name="Build instructions").click()
            page.get_by_role("button", name="Build instructions").click()
            expect(resources.locator(".instruction-step")).to_be_visible()
            with page.expect_download() as guide_download:
                resources.get_by_role("link", name="Download guide HTML").click()
            html = Path(guide_download.value.path()).read_text(encoding="utf8")
            current = projects[-1]
            assert current["id"] in html and str(current["revision"]) in html
            stale = page.request.get(
                f"{url}api/projects/{current['id']}/instructions/download"
                f"?revision={current['revision'] - 1}&format=html"
            )
            assert stale.status == 409
            page.route("**/instructions**", instructions)
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.screenshot(
                path=str(harness.ROOT / ".local" / "resources-desktop.png"), full_page=True
            )
            page.set_viewport_size({"width": 390, "height": 844})
            state["short_ttl"] = True
            state["fail_cache"] = True
            page.get_by_role("button", name="Parts & pricing").click()
            reads_before_expiry = len(cache_reads)
            page.get_by_role("button", name="Refresh US prices", exact=True).click()
            expect(resources.locator(".pricing-summary")).to_contain_text(
                "No fresh prices", timeout=5000
            )
            expect(page.locator(".cost-block")).to_contain_text("No fresh prices")
            expect(resources.get_by_role("alert")).to_contain_text(
                "Saved report temporarily unavailable"
            )
            assert len(cache_reads) > reads_before_expiry, (
                "Expiry must reread the saved report without supplier access"
            )
            reads_before_focus = len(cache_reads)
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            expect(
                resources.get_by_role("button", name="Refresh US prices", exact=True)
            ).to_be_enabled()
            assert len(cache_reads) > reads_before_focus
            expect(page.locator(".cost-block")).to_contain_text("No fresh prices")
            state["fail_cache"] = False
            page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            expect(
                resources.get_by_role("button", name="Refresh US prices", exact=True)
            ).to_be_enabled()
            assert len(refreshes) == 4, (
                "Expiry, focus and visibility must never trigger supplier refresh"
            )
            harness.send_chat(
                page, "How do I buy the pieces and assemble this?", "Build instructions"
            )
            expect(resources.locator("#build-instructions-panel")).to_be_visible()
            expect(resources.locator("#build-instructions-panel")).to_be_focused()
            assert len(refreshes) == 4
            page.get_by_role("button", name="Parts & pricing").click()
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.screenshot(
                path=str(harness.ROOT / ".local" / "resources-pricing-desktop.png"), full_page=True
            )
            resources.locator("#parts-pricing-panel").screenshot(
                path=str(harness.ROOT / ".local" / "resources-pricing-panel.png")
            )
            page.set_viewport_size({"width": 390, "height": 844})
            assert not errors, errors
            page.screenshot(
                path=str(harness.ROOT / ".local" / "resources-mobile.png"), full_page=True
            )
            print(
                "[browser-resources] Partial pricing, failed refresh, expiry, guides, "
                "downloads, saved reopen, revision/report guards, keyboard and mobile passed."
            )
        except Exception:
            import traceback

            traceback.print_exc()
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    harness.run_smoke = run
    raise SystemExit(harness.main())
