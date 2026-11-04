"""General discovery and task-specific routing through the real app.

Chat responses are deterministic fixtures; the real domain, API and frontend run.
No Meta call, camera or arbitrary CAD generation is tested here. Geometry only
appears after an explicit model-backed design via the shared helper.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import browser_smoke as harness  # noqa: E402


def run_platform(url: str) -> None:
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors, estimate_requests, pricing_requests = [], [], []

        def estimate(route):
            estimate_requests.append(route.request.method)
            route.fulfill(
                json={
                    "state": "current",
                    "estimate": {"status": "failed", "rows": [], "exclusions": []},
                }
            )

        page.route("**/cost-estimate*", estimate)
        page.on("request", lambda request: pricing_requests.append(request.url)
                if "/parts?" in request.url or "/procurement" in request.url else None)

        def no_price_widget():
            design = page.locator("#design-workspace")
            expect(design.get_by_role("region", name="Project cost estimate")).to_have_count(0)
            expect(design.locator(".cost-block,.design-budget-entry,.parts-total")).to_have_count(0)

        def no_pricing_requests():
            assert not estimate_requests, estimate_requests
            assert not pricing_requests, pricing_requests

        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(url)
            expect(page.get_by_text("Workspace ready")).to_be_visible()
            expect(page.locator(".workspace-empty")).to_be_visible()
            no_price_widget()
            no_pricing_requests()
            body = page.locator("body").inner_text().lower()
            assert "dilution" not in body and "concentration" not in body and "stock" not in body
            harness.send_chat(
                page,
                "I spend hours transferring capped vials between racks and an inspection station.",
                "Which racks and inspection equipment",
            )
            expect(page.locator(".planning-panel")).to_be_visible()
            expect(page.locator(".planning-panel")).to_have_count(1)
            expect(page.locator(".conversation-panel .brief-card")).to_have_count(0)
            expect(
                page.locator(
                    ".viewer-canvas canvas,.summary-card,.plan-card,.camera-card"
                )
            ).to_have_count(0)
            harness.send_chat(
                page,
                "I have a microscope and two racks; I need to inspect the labels.",
                "How are the vials presented",
            )
            expect(page.locator(".planning-panel")).to_contain_text("microscope")
            harness.send_chat(
                page, "The available space is 450 mm wide.", "Recorded the available space"
            )
            expect(page.locator(".planning-panel")).to_be_visible()
            expect(page.locator(".viewer-canvas canvas,.footprint")).to_have_count(0)
            with page.expect_download() as download:
                page.get_by_role("link", name="Download brief", exact=True).first.click()
            data = json.loads(Path(download.value.path()).read_text(encoding="utf8"))
            assert data["workflow"]["kind"] == "general"
            assert data["workflow"]["design_available"] is False
            assert data["brief"]["equipment"] == "a microscope and two racks"
            assert "design" not in data and "sourcing" not in data and "summary" not in data
            assert "engineering_design" not in data
            no_price_widget()
            no_pricing_requests()
            project_id, revision = data["project_id"], data["project_revision"]
            rejected = page.request.post(f"{url.rstrip('/')}/api/projects/{project_id}/confirm")
            assert rejected.status == 422
            assert "stock" not in rejected.text().lower()
            assert (
                page.request.get(
                    f"{url.rstrip('/')}/api/projects/{project_id}/brief?revision={revision - 1}"
                ).status
                == 409
            )
            page.get_by_role("button", name="New project", exact=True).click()
            expect(page.locator(".workspace-empty")).to_be_visible()
            expect(page.locator(".brief-card,.planning-panel")).to_have_count(0)
            # Liquid opening without equipment: planning note only, no machine.
            harness.send_chat(
                page,
                "I keep making dilutions manually and want to automate pipetting.",
                "Which equipment would you like to keep",
            )
            expect(page.locator(".planning-panel")).to_be_visible()
            expect(page.locator(".planning-panel")).to_contain_text("equipment")
            expect(page.locator(".viewer-canvas canvas")).to_have_count(0)
            expect(page.locator(".summary-card,.plan-card")).to_have_count(0)
            expect(page.locator(".design-agent-card")).to_have_count(0)
            harness.send_chat(
                page,
                "I have a pipette and microcentrifuge tubes.",
                "What volumes will the liquid preparation",
            )
            expect(page.locator(".planning-panel")).to_contain_text("pipette")
            # Quantities alone cannot expose or approve a machine.
            harness.send_chat(page, harness.COMPLETE_TASK_MESSAGE, "Recorded synthetic parameters")
            expect(page.locator(".summary-card,.plan-card")).to_have_count(0)
            expect(page.locator(".viewer-canvas canvas")).to_have_count(0)
            no_price_widget()
            no_pricing_requests()
            approve = page.get_by_role("button", name="Approve design & open software", exact=True)
            expect(approve).to_have_count(0)
            # Only the explicit model-backed design reveals geometry and starts estimates.
            developed = harness.develop_layout(page)
            expect(page.locator(".viewer-canvas canvas")).to_have_count(1)
            no_price_widget()
            nav = page.get_by_role("navigation", name="Project workspace", exact=True)
            nav.get_by_role("button", name="Parts & prices", exact=True).click()
            expect(page.locator(".parts-total strong")).to_contain_text("$")
            expect(page.locator(".parts-table")).to_be_visible()
            assert estimate_requests, "An accepted design should start its estimate."
            nav.get_by_role("button", name="3D design", exact=True).click()
            assert developed["project"]["engineering_design"]
            assert developed["project"]["engineering"]["selected_platform_id"] == "jubilee"
            expect(page.get_by_role("region", name="Jubilee workstation")).to_be_visible()
            expect(page.locator(".conversation-panel .brief-card")).to_have_count(0)
            approve.click()
            software = page.get_by_role("heading", name="Software & protocols", exact=True)
            expect(software).to_be_visible()
            nav.get_by_role("button", name="3D design", exact=True).click()
            page.get_by_role("button", name="Specifications & files", exact=True).click()
            details = page.locator("details.project-details", has=page.locator(".planning-panel"))
            expect(details).not_to_have_attribute("open", "")
            details.locator("summary").first.click()
            expect(details.locator(".planning-panel")).to_contain_text("pipette")
            page.locator("details.prep-plan > summary").click()
            expect(page.locator(".summary-card")).to_be_visible()
            expect(page.locator(".plan-card")).to_contain_text("100 µL")
            expect(page.locator(".chat-status")).to_contain_text("Confirmed")
            page.wait_for_load_state("networkidle")
            requests_after_design = len(estimate_requests)
            pricing_after_design = len(pricing_requests)
            harness.send_chat(
                page,
                "Actually, switch this project to inspecting vial labels with a microscope.",
                "Let's plan the label inspection",
            )
            expect(page.locator(".planning-panel")).to_be_visible()
            # The chosen source platform can still be inspected without an accepted layout.
            expect(page.locator(".selected-platform-preview canvas")).to_have_count(1)
            expect(
                page.locator(
                    ".presentation-stage canvas,.summary-card,.plan-card,.camera-card"
                )
            ).to_have_count(0)
            expect(page.locator(".chat-status")).to_contain_text("Draft")
            no_price_widget()
            assert len(estimate_requests) == requests_after_design
            assert len(pricing_requests) == pricing_after_design
            assert not errors, errors
            print(
                "[browser-platform] General discovery, brief download, "
                "late liquid parameters, gated design and workflow switching passed."
            )
        finally:
            browser.close()


if __name__ == "__main__":
    harness.run_smoke = run_platform
    raise SystemExit(harness.main())
