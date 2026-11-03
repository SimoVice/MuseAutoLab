"""Real POST/poll lifecycle with offline provider and catalogue transport."""

import json
from pathlib import Path

import browser_smoke as harness
from playwright.sync_api import expect, sync_playwright

OUTPUT = harness.ROOT / ".local/chat-activity-20261103"


def run(url):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(reduced_motion="reduce", viewport={"width": 1440, "height": 1000})
        errors, polls = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda request: polls.append(request.url) if "/activity/" in request.url else None,
        )
        page.goto(url, wait_until="networkidle")
        expect(page.get_by_text("Workspace ready")).to_be_visible()
        composer = page.get_by_label("Describe your workflow or request a change")
        composer.fill("Synthetic source check")
        page.get_by_role("button", name="Send message", exact=True).click()
        activity = page.locator(".agent-activity")
        expect(activity).to_contain_text("Interpreting your request")
        expect(activity).to_have_attribute("role", "status")
        expect(activity).to_contain_text("Sourcing components")
        page.screenshot(path=str(OUTPUT / "sourcing.png"))
        assert (
            activity.locator(".activity-indicator > span").evaluate(
                "el => getComputedStyle(el).animationName"
            )
            == "none"
        )
        expect(activity).to_contain_text("Interpreting your request")
        expect(page.get_by_text("Synthetic request completed.", exact=True)).to_be_visible()
        expect(activity).to_have_count(0)
        count = len(polls)
        page.wait_for_timeout(1400)
        assert len(polls) == count, "Polling continued after POST completion"
        composer.fill("Synthetic fail")
        page.get_by_role("button", name="Send message", exact=True).click()
        expect(activity).to_contain_text("Interpreting your request")
        expect(page.get_by_role("alert")).to_contain_text("Synthetic provider timeout")
        expect(activity).to_have_count(0)
        expect(composer).to_be_enabled()
        count = len(polls)
        page.wait_for_timeout(1400)
        assert len(polls) == count
        composer.fill("Synthetic navigation cancellation")
        page.get_by_role("button", name="Send message", exact=True).click()
        expect(activity).to_contain_text("Interpreting your request")
        page.reload(wait_until="networkidle")
        expect(activity).to_have_count(0)
        assert not errors, errors
        (OUTPUT / "result.json").write_text(
            json.dumps(
                {
                    "status": "passed",
                    "checks": [
                        "real POST/poll lifecycle",
                        "interpret/sourcing/resume",
                        "no polling after response",
                        "error cleanup",
                        "navigation cancellation",
                        "aria live",
                        "reduced motion",
                    ],
                    "errors": errors,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        browser.close()


if __name__ == "__main__":
    harness.STUB_SERVER = Path(__file__).with_name("browser_activity_server.py")
    harness.run_smoke = run
    raise SystemExit(harness.main())
