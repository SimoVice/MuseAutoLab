"""Render the real assistant component with legacy/new prose and unsafe inputs, offline."""

import json
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PINNED_URL = "https://github.com/machineagency/jubilee/tree/0123456789abcdef0123456789abcdef01234567"
LEGACY = (
    "Two routes fit your process:\n"
    "1. Build an open-hardware Jubilee platform - source: " + PINNED_URL
    + " - reviewed reference historical base-parts estimate ~$1400 USD "
    "checked 2026-11-03, not a quote."
    " Tradeoff: Custom tools and assembly are additional.\n"
    "2. Buy an assembled OT-2 platform - source: https://opentrons.com/products/categories/robots"
    " - reviewed reference vendor starting price $15,950 USD checked 2026-11-03, not a quote."
    " Tradeoff: Verify the selected instrument pipette and consumables.\n\n"
    "Which route best fits your lab?\n"
)
UNSAFE = """[Unsafe](javascript:alert(1))
![Tracker](https://example.org/tracker.png)
<script>window.injected=true</script>
<img src=x onerror="window.injected=true">
"""


def run(url):
    output = ROOT / ".local/assistant-comparison-20261103"
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/assistant-comparison-test", lambda route: route.fulfill(
            content_type="text/html", body="""<html><head>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>body{margin:0;background:#fff;font:14px Arial;color:#214a52}
            main{max-width:470px;padding:24px;margin:auto;box-sizing:border-box}</style>
            </head><body><main id="root"></main><script type="module">
            import React from '/node_modules/.vite/deps/react.js';
            import ReactDOM from '/node_modules/.vite/deps/react-dom_client.js';
            import RefreshRuntime from '/@react-refresh';
            RefreshRuntime.injectIntoGlobalHook(window);
            window.$RefreshReg$=()=>{};window.$RefreshSig$=()=>type=>type;
            window.__vite_plugin_react_preamble_installed__=true;
            await import('/src/chat-workspace.css');
            const {default: AssistantMessage}=await import('/src/AssistantMessage.tsx');
            const root=ReactDOM.createRoot(document.getElementById('root'));
            window.renderMessage=text=>root.render(React.createElement(AssistantMessage,{text}));
            window.renderMessage(""" + json.dumps(LEGACY) + ");</script></body></html>"))
        page.goto(url.rstrip("/") + "/assistant-comparison-test", wait_until="networkidle")
        expect(page.get_by_role("heading")).to_have_count(2)
        link = page.get_by_role("link", name="machineagency/jubilee project reference")
        expect(link).to_have_attribute("href", PINNED_URL)
        for width in (1440, 390):
            page.set_viewport_size({"width": width, "height": 1000})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert page.locator(".assistant-markdown strong").count() == 6
            assert not any(text.endswith("-") for text in page.locator("h3").all_text_contents())
            assert "0123456789abcdef" not in page.locator(".assistant-markdown").inner_text()
            page.screenshot(path=str(output / f"comparison-{width}.png"), full_page=True)
        page.evaluate("text=>window.renderMessage(text)", UNSAFE)
        expect(page.locator(".assistant-markdown img, .assistant-markdown script")).to_have_count(0)
        expect(page.locator(".assistant-markdown a")).to_have_count(0)
        assert not page.evaluate("Boolean(window.injected)")
        page.evaluate("text=>window.renderMessage(text)", "1. Prepare tubes.\n2. Mix samples.")
        expect(page.locator(".assistant-markdown ol li")).to_have_count(2)
        assert not errors, errors
        browser.close()
    print("Assistant comparison: desktop/mobile, legacy formatting, exact links, "
          "generic instructions and XSS checks passed.")


if __name__ == "__main__":
    run(sys.argv[1])
