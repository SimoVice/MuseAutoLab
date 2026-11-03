"""Browser checks for hosted account UI with synthetic authentication, no provider calls."""

import secrets
from copy import deepcopy
from datetime import datetime, timezone

import browser_smoke as harness
from playwright.sync_api import expect, sync_playwright


def run(url):
    output = harness.ROOT / ".local" / "hosted-ui"
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        state = {"authenticated": False, "entry": None, "project": None, "expire": False}
        username, password = secrets.token_urlsafe(12), secrets.token_urlsafe(24)

        def auth(route):
            endpoint = route.request.url.rsplit("/", 1)[-1]
            if endpoint == "login":
                assert route.request.post_data_json == {"username": username, "password": password}
                state["authenticated"] = True
            elif endpoint == "logout":
                state["authenticated"] = False
            route.fulfill(
                json={
                    "enabled": True,
                    "authenticated": state["authenticated"],
                    "account": "synthetic-account" if state["authenticated"] else None,
                }
            )

        def library(route):
            if state["expire"]:
                route.fulfill(status=401, json={"detail": "Authentication required."})
            elif route.request.url.endswith("/open"):
                route.fulfill(
                    json={
                        "project": state["project"],
                        "conversation": [],
                        "title": state["entry"]["title"],
                    }
                )
            else:
                route.fulfill(
                    json={"enabled": True, "projects": [state["entry"]] if state["entry"] else []}
                )

        def save(route):
            data = route.request.post_data_json
            state["entry"] = {
                "id": state["project"]["id"],
                "title": data["title"],
                "revision": data["revision"],
                "status": "draft",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            route.fulfill(json={"saved_project": state["entry"]})

        def capture(response):
            if response.url.endswith("/api/projects") and response.ok:
                state["project"] = deepcopy(response.json()["project"])

        page.on("response", capture)
        page.route("**/api/auth/*", auth)
        page.route("**/api/library**", library)
        page.route("**/api/projects/*/save", save)
        page.goto(url, wait_until="networkidle")
        expect(page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
        page.get_by_label("Username", exact=True).fill(username)
        page.get_by_label("Password", exact=True).fill(password)
        page.get_by_role("button", name="Sign in", exact=True).click()
        expect(page.locator(".connection-dot.connected")).to_be_visible()
        assert page.evaluate("localStorage.length") == 0
        page.get_by_role("button", name="Projects", exact=True).click()
        expect(page.get_by_text("Your first project starts here", exact=True)).to_be_visible()
        page.get_by_role("button", name="Continue to workspace").click()
        page.get_by_role("button", name="Save project", exact=True).click()
        page.get_by_label("Project name", exact=True).fill("Synthetic sample station")
        page.get_by_role("dialog").get_by_role("button", name="Save project", exact=True).click()
        expect(page.locator(".topbar-center")).to_contain_text("Synthetic sample station")
        saved_project = deepcopy(state["project"])
        page.get_by_role("button", name="New project", exact=True).click()
        expect(page.locator(".topbar-center")).not_to_contain_text("Synthetic sample station")
        state["project"] = saved_project
        page.get_by_role("button", name="Projects", exact=True).click()
        page.get_by_role("button", name="Open Synthetic sample station", exact=True).click()
        expect(page.locator(".topbar-center")).to_contain_text("Synthetic sample station")
        # Keyboard close restores focus to the project-library trigger.
        page.get_by_role("button", name="Projects", exact=True).click()
        expect(
            page.get_by_role("button", name="Open Synthetic sample station", exact=True)
        ).to_be_enabled()
        page.keyboard.press("Escape")
        expect(page.get_by_role("button", name="Projects", exact=True)).to_be_focused()
        page.reload(wait_until="networkidle")
        expect(page.locator(".connection-dot.connected")).to_be_visible()
        assert (
            page.evaluate("sessionStorage.getItem('museautolab.hosted.synthetic-account')")
            == saved_project["id"]
        )
        with page.expect_download() as download:
            page.get_by_role("button", name="Export file", exact=True).click()
        assert download.value.suggested_filename.endswith(".json")
        page.get_by_role("button", name="Sign out", exact=True).click()
        page.get_by_role("dialog").get_by_role("button", name="Sign out", exact=True).click()
        expect(page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(output / "mobile-signin.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.get_by_label("Username", exact=True).fill(username)
        page.get_by_label("Password", exact=True).fill(password)
        page.get_by_role("button", name="Sign in", exact=True).click()
        expect(page.locator(".connection-dot.connected")).to_be_visible()
        page.screenshot(path=str(output / "mobile-workspace.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.get_by_label("Describe your workflow or request a change", exact=True).fill(
            "Synthetic unsent draft"
        )
        state["expire"] = True
        page.get_by_role("button", name="Projects", exact=True).click()
        expect(
            page.get_by_text(
                "Your session ended. Sign in again to continue your workspace.", exact=True
            )
        ).to_be_visible()
        state["expire"] = False
        page.get_by_label("Username", exact=True).fill(username)
        page.get_by_label("Password", exact=True).fill(password)
        page.get_by_role("button", name="Sign in", exact=True).click()
        expect(
            page.get_by_label("Describe your workflow or request a change", exact=True)
        ).to_have_value("Synthetic unsent draft")
        assert errors == [], errors
        # Local mode retains file-based controls and automatic browser restoration.
        local = browser.new_page()
        local.route(
            "**/api/auth/status",
            lambda route: route.fulfill(json={"enabled": False, "authenticated": True}),
        )
        local.goto(url, wait_until="networkidle")
        expect(local.get_by_role("button", name="Open project", exact=True)).to_be_visible()
        expect(local.get_by_role("button", name="Save project", exact=True)).to_be_visible()
        expect(local.get_by_role("button", name="Sign out", exact=True)).to_have_count(0)
        browser.close()


if __name__ == "__main__":
    harness.run_smoke = run
    raise SystemExit(harness.main())
