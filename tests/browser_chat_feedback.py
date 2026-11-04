"""Real React/browser UI with explicitly held synthetic chat responses; no model calls."""

import json
from copy import deepcopy

import browser_smoke as harness
from playwright.sync_api import expect, sync_playwright

OUTPUT = harness.ROOT / ".local/chat-feedback-20261031"
MARKDOWN = """## Workstation review

The **selected platform** remains a concept.

- Inspect the rack.
- Check the plate.

1. Review the dimensions.
2. Confirm the draft.

Run `python check.py` only after review.

```python
print('concept only')
```

[Official source](https://example.com/catalog)
Also listed at https://example.com/plain-product.
[Contact](mailto:review@example.com)
[Unsafe](javascript:alert(1))
[Encoded unsafe](jav&#x61;script:alert(1))
![Remote image](https://example.com/tracking.png)
<script>window.markdownExecuted = true</script>
<img src="x" onerror="window.markdownExecuted = true">
"""


def run(url):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        errors, pending, opened = [], [], []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def capture(response):
            if response.url.endswith("/open") and response.ok:
                opened.append(response.json()["project"])

        page.on("response", capture)
        page.route(
            "**/cost-estimate*",
            lambda route: route.fulfill(json={"estimate": None, "state": "not_estimated"}),
        )
        page.route("**/messages", lambda route: pending.append(route))
        page.goto(url, wait_until="networkidle")
        expect(page.get_by_text("Workspace ready")).to_be_visible()
        page.get_by_label("Open saved project").set_input_files(
            str(harness.ROOT / "docs/examples/presentation-flow-project.json")
        )
        expect(page.locator(".viewer-canvas canvas")).to_have_count(1)
        expect(page.get_by_label("Describe your workflow or request a change")).to_be_enabled()
        base = opened[-1]
        expect(page.get_by_role("region", name="Tip rack alternatives")).to_have_count(0)
        page.evaluate("""() => {
          window.feedbackCanvas = document.querySelector('.viewer-canvas canvas');
          window.observedDesignPhases = [];
          new MutationObserver(() => {
            const state = document.querySelector('.design-activity')?.dataset.phase;
            if (state) window.observedDesignPhases.push(state);
          }).observe(document.querySelector('.viewer-canvas'), {
            subtree:true, childList:true, attributes:true, attributeFilter:['data-phase']
          });
        }""")
        composer = page.get_by_label("Describe your workflow or request a change")

        def begin(text):
            expect(composer).to_be_enabled()
            composer.fill(text)
            page.get_by_role("button", name="Send message", exact=True).click()
            expect(page.locator(".design-activity[data-phase=pending]")).to_be_visible()
            expect(page.locator(".design-activity")).to_contain_text("Reviewing your request")
            expect(page.locator(".viewer-canvas")).to_have_attribute("aria-busy", "true")
            assert page.evaluate("window.feedbackCanvas === document.querySelector('canvas')")
            expect(page.locator(".design-activity")).not_to_contain_text("Updating design")
            return pending.pop(0)

        # A software inquiry has rich text but no geometry change or false completion state.
        route = begin("Explain **software** and keep the current design unchanged.")
        page.screenshot(path=str(OUTPUT / "request-pending.png"))
        route.fulfill(json={"project": base, "assistant_message": MARKDOWN, "action_runs": []})
        expect(composer).to_be_enabled()
        expect(page.locator(".design-activity")).to_have_count(0)
        bubble = page.locator(".message-row.assistant .message-bubble").last
        expect(bubble.locator("strong")).to_have_text("selected platform")
        expect(bubble.locator("ul li")).to_have_count(2)
        expect(bubble.locator("ol li")).to_have_count(2)
        expect(bubble.locator("pre code")).to_have_text("print('concept only')\n")
        expect(bubble.get_by_role("link", name="Official source")).to_have_attribute(
            "href", "https://example.com/catalog"
        )
        expect(bubble.get_by_role("link", name="Official source")).to_have_attribute(
            "rel", "noopener noreferrer"
        )
        expect(bubble.get_by_role("link", name="example.com reference")).to_have_attribute(
            "href", "https://example.com/plain-product"
        )
        expect(bubble.get_by_role("link", name="Unsafe", exact=True)).to_have_count(0)
        expect(bubble.get_by_role("link", name="Encoded unsafe")).to_have_count(0)
        expect(bubble.locator("img,script,iframe")).to_have_count(0)
        assert page.evaluate("window.markdownExecuted !== true")
        expect(
            page.locator(".message-row.user .message-bubble").last.locator("strong")
        ).to_have_count(0)
        page.screenshot(path=str(OUTPUT / "markdown-desktop.png"))
        for width in [390, 760]:
            page.set_viewport_size({"width": width, "height": 844})
            page.get_by_role("navigation", name="Workspace view").get_by_role(
                "button", name="Chat", exact=True
            ).click()
            bubble.scroll_into_view_if_needed()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(OUTPUT / f"markdown-mobile-{width}.png"))
        page.set_viewport_size({"width": 1440, "height": 1000})

        # A direct rack choice has a known subject while its request is pending.
        page.get_by_role("button", name="Compare tip racks in Parts & prices").click()
        options = page.get_by_role("region", name="Tip rack alternatives")
        expect(options.get_by_role("article")).to_have_count(2)
        page.route("**/tip-rack-options", lambda route: (
            pending.append(route) if route.request.method == "POST" else route.continue_()
        ))
        options.get_by_role(
            "button", name="Use this rack", exact=True
        ).first.click()
        expect(page.locator(".conversation-scroll [data-phase=pending]")).to_contain_text(
            "Updating tip rack"
        )
        page.screenshot(path=str(OUTPUT / "tip-rack-updating.png"))
        pending.pop(0).fulfill(status=502, json={"detail": "Synthetic rack failure; design kept."})
        expect(page.get_by_role("complementary", name="Design assistant")
               .get_by_role("alert")).to_contain_text("design kept")
        expect(page.locator(".design-activity")).to_have_count(0)
        expect(composer).to_be_enabled()
        page.get_by_role("button", name="3D design", exact=True).click()

        # A changed canonical component position reports updating only after acceptance.
        changed = deepcopy(base)
        changed["revision"] += 1
        changed["design"]["components"][0]["position"][0] += 1
        route = begin("Move the component by one millimeter.")
        route.fulfill(
            json={"project": changed, "assistant_message": "The design changed.", "action_runs": []}
        )
        expect(page.locator(".design-activity[data-phase=ready]")).to_be_visible()
        expect(page.locator(".viewer-canvas")).to_have_attribute("aria-busy", "false")
        assert "updating" in page.evaluate("window.observedDesignPhases")
        assert page.evaluate("window.feedbackCanvas === document.querySelector('canvas')")
        page.screenshot(path=str(OUTPUT / "design-updated.png"))

        # Recipe/cost/provenance metadata alone does not announce a geometry update.
        unchanged = deepcopy(changed)
        unchanged["revision"] += 1
        unchanged["design"]["estimated_cost"]["amount"] = 999
        unchanged["labware_plate"]["provenance"]["source_project_revision"] += 1
        unchanged["labware_plate"]["compatibility"]["requested_volume_ul"] = 150
        route = begin("Update the preparation details without moving any component.")
        route.fulfill(json={"project": unchanged, "assistant_message": "Preparation updated."})
        expect(composer).to_be_enabled()
        expect(page.locator(".design-activity")).to_have_count(0)
        changed = unchanged

        # A subsequent failed request clears the success notice and retains the model/draft.
        route = begin("Request a change that fails safely.")
        route.fulfill(status=502, json={"detail": "Synthetic provider failure; design kept."})
        expect(page.get_by_role("complementary", name="Design assistant")
               .get_by_role("alert")).to_contain_text("design kept")
        expect(page.locator(".design-activity")).to_have_count(0)
        expect(composer).to_have_value("Request a change that fails safely.")
        assert page.evaluate("window.feedbackCanvas === document.querySelector('canvas')")

        # Reduced motion preserves state feedback while disabling the decorative rotation.
        page.emulate_media(reduced_motion="reduce")
        route = begin("Keep the recipe unchanged while reviewing.")
        assert (
            page.locator(".design-activity .activity-indicator > span").evaluate(
                "e => getComputedStyle(e).animationName"
            )
            == "none"
        )
        route.fulfill(
            json={"project": changed, "assistant_message": "Recipe unchanged.", "action_runs": []}
        )
        expect(page.locator(".design-activity")).to_have_count(0)
        expect(composer).to_be_enabled()

        # Keep this request held: synthetic revisions above intentionally differ from
        # backend state. Removing the fixture would produce an immediate stale-revision
        # response instead of exercising navigation during an outstanding request.
        # Navigating away cancels pending presentation work; the new page has no stale notice.
        composer.fill("Show project files.")
        page.get_by_role("button", name="Send message", exact=True).click()
        expect(page.locator(".design-activity[data-phase=pending]")).to_be_visible()
        page.reload(wait_until="networkidle")
        pending.pop().abort()
        page.unroute_all(behavior="ignoreErrors")
        expect(page.get_by_text("Workspace ready")).to_be_visible()
        expect(page.locator(".design-activity")).to_have_count(0)
        expect(composer).to_be_enabled()
        assert not errors, errors
        (OUTPUT / "result.json").write_text(
            json.dumps(
                {
                    "status": "passed",
                    "scope": "Synthetic chat transport; real React/browser; no model calls",
                    "checks": [
                        "CommonMark structure",
                        "safe links",
                        "HTML/media disabled",
                        "literal user text",
                        "mobile no overflow",
                        "truthful phases",
                        "same canvas node",
                        "failure cleanup",
                        "reduced motion",
                        "navigation cancellation",
                    ],
                    "errors": errors,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        context.close()
        browser.close()


if __name__ == "__main__":
    harness.run_smoke = run
    raise SystemExit(harness.main())
