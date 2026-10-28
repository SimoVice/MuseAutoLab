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
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(url)
            expect(page.get_by_text("Workspace ready")).to_be_visible()
            expect(page.locator(".workspace-empty")).to_be_visible()
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
                    ".viewer-canvas canvas,.cost-block,.summary-card,.plan-card,.camera-card"
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
            expect(page.locator(".viewer-canvas canvas,.cost-block,.footprint")).to_have_count(0)
            with page.expect_download() as download:
                page.get_by_role("link", name="Download brief", exact=True).first.click()
            data = json.loads(Path(download.value.path()).read_text(encoding="utf8"))
            assert data["workflow"]["kind"] == "general"
            assert data["workflow"]["design_available"] is False
            assert data["brief"]["equipment"] == "a microscope and two racks"
            assert "design" not in data and "sourcing" not in data and "summary" not in data
            assert "engineering_design" not in data
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
            expect(page.locator(".summary-card,.plan-card,.cost-block")).to_have_count(0)
            expect(page.locator(".design-agent-card")).to_have_count(0)
            harness.send_chat(
                page,
                "I have a pipette and microcentrifuge tubes.",
                "What volumes will the liquid preparation",
            )
            expect(page.locator(".planning-panel")).to_contain_text("pipette")
            # Quantities alone still reveal no geometry; Confirm stays disabled.
            harness.send_chat(page, harness.COMPLETE_TASK_MESSAGE, harness.EXPECTED_STOCK)
            page.locator("details.prep-plan > summary").click()
            expect(page.locator(".summary-card")).to_be_visible()
            expect(page.locator(".plan-card")).to_contain_text("100 µL")
            expect(page.locator(".viewer-canvas canvas")).to_have_count(0)
            expect(page.locator(".cost-block")).to_have_count(0)
            expect(page.get_by_role("button", name="Confirm design")).to_be_disabled()
            # Only the explicit model-backed design reveals geometry and cost.
            harness.develop_layout(page)
            expect(page.locator(".viewer-canvas canvas")).to_have_count(1)
            expect(page.locator(".cost-block")).to_be_visible()
            expect(page.get_by_text("Meta-proposed layout").first).to_be_visible()
            expect(page.locator(".conversation-panel .brief-card")).to_have_count(0)
            details = page.locator("details.project-details")
            expect(details).not_to_have_attribute("open", "")
            details.locator("summary").first.click()
            expect(details.locator(".planning-panel")).to_contain_text("pipette")
            page.get_by_role("button", name="Confirm design").click()
            expect(page.locator(".chat-status")).to_contain_text("Confirmed")
            harness.send_chat(
                page,
                "Actually, switch this project to inspecting vial labels with a microscope.",
                "Let's plan the label inspection",
            )
            expect(page.locator(".planning-panel")).to_be_visible()
            expect(
                page.locator(
                    ".viewer-canvas canvas,.cost-block,.summary-card,.plan-card,.camera-card"
                )
            ).to_have_count(0)
            expect(page.locator(".chat-status")).to_contain_text("Draft")
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
