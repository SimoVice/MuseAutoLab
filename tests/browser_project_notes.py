"""Full local workspace checks for project notes and sourced chat; model transport is stubbed."""

import json

import browser_smoke as harness
from playwright.sync_api import expect, sync_playwright

OUTPUT = harness.ROOT / ".local/assistant-comparison-20261103"
NOTE = "Synthetic fixture: prefer printable one-piece holders. We own a manual pipette."


def run(url):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors, notes_requests = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: notes_requests.append(request.post_data_json)
                if request.url.endswith("/notes") and request.method == "PUT" else None)
        page.route("**/cost-estimate*", lambda route: route.fulfill(
            json={"estimate": None, "state": "not_estimated"}))
        page.goto(url, wait_until="networkidle")
        expect(page.get_by_text("Workspace ready")).to_be_visible()
        page.get_by_role("button", name="Project notes", exact=True).click()
        dialog = page.get_by_role("dialog", name="Project notes")
        field = dialog.get_by_role("textbox")
        field.fill(NOTE)
        dialog.get_by_role("button", name="Save notes", exact=True).click()
        expect(dialog).not_to_be_visible()
        assert notes_requests[-1] == {"previous": "", "notes": NOTE}
        page.get_by_role("button", name="Project notes", exact=True).click()
        expect(field).to_have_value(NOTE)
        field.fill("Cancelled synthetic draft")
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        page.get_by_role("button", name="Project notes", exact=True).click()
        expect(field).to_have_value(NOTE)
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        assert len(notes_requests) == 1
        with page.expect_download() as saved:
            page.get_by_role("button", name="Save project", exact=True).click()
        saved_path = OUTPUT / "notes-portable.json"
        saved.value.save_as(saved_path)
        assert json.loads(saved_path.read_text(encoding="utf-8"))["inputs"]["project_notes"] == NOTE
        page.reload(wait_until="networkidle")
        expect(page.get_by_text("Workspace ready")).to_be_visible()
        page.get_by_role("button", name="Project notes", exact=True).click()
        expect(page.get_by_role("dialog", name="Project notes").get_by_role("textbox"))\
            .to_have_value(NOTE)
        dialog.get_by_role("button", name="Cancel").click()
        harness.send_chat(page, "Help me compare the platform options.", "historical upstream")
        expect(page.locator(".assistant-markdown h3")).to_have_count(2)
        page.screenshot(path=str(OUTPUT / "full-chat-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.get_by_role("button", name="Project notes", exact=True).click()
        expect(page.get_by_role("dialog", name="Project notes")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(OUTPUT / "notes-mobile.png"), full_page=True)
        dialog.get_by_role("button", name="Cancel").click()
        page.screenshot(path=str(OUTPUT / "full-chat-mobile.png"), full_page=True)
        assert not errors, errors
        browser.close()
    print("Project notes: save, cancel, portable export, reload and mobile width passed.")


if __name__ == "__main__":
    harness.run_smoke = run
    raise SystemExit(harness.main())
