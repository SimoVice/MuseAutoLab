"""Offline browser regression for illustrative motion, never hardware validation.

Runs real compiler/API/WebGL against public synthetic projects. Only model
extraction is replaced; supplier retrieval and cost inference are blocked.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import browser_smoke as harness

OUTPUT = harness.ROOT / ".local/operating-preview-20261102/qa"


def serve():
    import browser_microplate_server as plate
    import browser_tip_options_server as tips
    import uvicorn

    import app.api as api

    async def chat(project, message, history, **kwargs):
        if message in (tips.ALTERNATIVES, tips.YES_PRINTER, tips.NO_PRINTER):
            return await tips.chat(project, message, history, **kwargs)
        return await plate.chat(project, message, history, **kwargs)

    args = plate.rack_fixture.foundation.baseline.parse_args()
    api.generate_turn = chat
    plate.rack_fixture.foundation.agent.propose_layout = plate.rack_fixture.foundation.layout
    plate.rack_fixture.foundation.inspection.propose_inspection = (
        plate.rack_fixture.foundation.extension
    )
    uvicorn.run(api.app, host="127.0.0.1", port=args.port, log_level="warning")


def run(url):
    from browser_microplate_server import SWITCH_WITH_VOLUME
    from browser_tip_options_server import ALTERNATIVES
    from playwright.sync_api import expect, sync_playwright

    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100}, reduced_motion="reduce")
        errors, posts, checks = [], [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda request: posts.append(request.url) if request.method == "POST" else None,
        )
        page.route(
            "**/cost-estimate*",
            lambda route: route.fulfill(
                json={
                    "state": "current",
                    "estimate": {
                        "status": "failed",
                        "rows": [],
                        "exclusions": [],
                    },
                }
            ),
        )
        page.route("**/procurement/refresh*", lambda route: route.abort())

        def send(message):
            with page.expect_response(
                lambda response: response.url.endswith("/messages")
            ) as response:
                field = page.get_by_label("Describe your workflow or request a change")
                expect(field).to_be_enabled()
                field.fill(message)
                page.get_by_role("button", name="Send message", exact=True).click()
            assert response.value.ok, response.value.text()
            expect(field).to_be_enabled()
            return response.value.json()["project"]

        def save():
            with page.expect_download() as download:
                page.get_by_role("button", name="Save project", exact=True).click()
            data = json.loads(download.value.path().read_text(encoding="utf-8"))
            data.pop("saved_at", None)
            return data

        def canvas(name):
            page.wait_for_timeout(150)
            value = page.locator("canvas").first.screenshot()
            (OUTPUT / f"{name}.png").write_bytes(value)
            return hashlib.sha256(value).hexdigest()

        def verify_motion(label):
            panel = page.get_by_role("region", name="Operating preview", exact=True)
            play = panel.get_by_role("button", name="Play", exact=True)
            pause = panel.get_by_role("button", name="Pause", exact=True)
            reset = panel.get_by_role("button", name="Reset", exact=True)
            timeline = page.get_by_role("slider", name=re.compile("preview|timeline", re.I))
            expect(play).to_be_enabled()
            expect(pause).to_be_disabled()
            details = panel.locator("details", has=page.locator("#operation-time"))
            if details.count() and details.get_attribute("open") is None:
                details.locator(":scope > summary").click()
            timeline.wait_for()
            assert float(timeline.input_value()) == 0
            before = save()
            initial_posts = len(posts)
            first = canvas(f"{label}-idle")
            play.click()
            page.wait_for_timeout(1100)
            pause.click()
            progress = float(timeline.input_value())
            assert progress > 0, "Explicit play did not advance reduced-motion context"
            moved = canvas(f"{label}-moving")
            assert moved != first, "Playback advanced text but canvas did not change"
            assert canvas(f"{label}-paused") == moved, "Paused canvas continues moving"
            assert float(timeline.input_value()) == progress
            maximum = float(timeline.get_attribute("max"))
            timeline.focus()
            timeline.press("Home")
            timeline.press("ArrowRight")
            timeline.press("ArrowRight")
            assert canvas(f"{label}-scrub") != moved
            reset.click()
            assert float(timeline.input_value()) == 0
            panel.get_by_label("Playback speed").select_option("4")
            timeline.press("End")
            for _ in range(10):
                timeline.press("ArrowLeft")
            play.click()
            expect(pause).to_be_disabled(timeout=5000)
            assert abs(float(timeline.input_value()) - maximum) < 0.001
            expect(panel.locator(".operation-now")).to_contain_text("Complete")
            reset.click()
            assert len(posts) == initial_posts, posts[initial_posts:]
            assert save() == before, "Playback changed persisted project/BOM/cost inputs"
            with page.expect_download() as download:
                panel.get_by_role("button", name="Download motion plan", exact=True).click()
            motion = json.loads(download.value.path().read_text(encoding="utf-8"))
            assert motion["execution_enabled"] is False
            assert motion["revision"] == before["revision"]
            assert motion["status"] == "ready" and motion["keyframes"]
            (OUTPUT / f"{label}-motion-plan.json").write_text(
                json.dumps(motion, indent=2), encoding="utf-8"
            )
            checks.append(label)

        try:
            page.goto(url, wait_until="networkidle")
            expect(page.get_by_text("Workspace ready")).to_be_visible()
            initial_preview = page.get_by_role("region", name="Operating preview", exact=True)
            expect(initial_preview).to_have_count(0)
            expect(page.get_by_role("button", name="Play", exact=True)).to_have_count(0)
            checks.append("unaccepted-general-project-unavailable")
            with page.expect_response(lambda response: response.url.endswith("/open")) as opened:
                page.get_by_label("Open saved project").set_input_files(
                    str(harness.ROOT / "docs/examples/parametric-tube-rack-project.json")
                )
            assert opened.value.ok, opened.value.text()
            expect(page.locator(".prep-plan")).to_be_visible()
            expect(page.locator(".scene-loading")).to_have_count(0, timeout=60000)
            page.set_viewport_size({"width": 1440, "height": 900})
            page.wait_for_timeout(300)
            page.evaluate("window.scrollTo(0, 0)")
            layout = page.evaluate("""() => Object.fromEntries(
                ['.cost-summary', '.viewer-shell', '.operating-preview'].map(selector => {
                  const r = document.querySelector(selector).getBoundingClientRect();
                  return [selector, {top:r.top,bottom:r.bottom,height:r.height}];
                }))""")
            layout["cost_without_player_current_styles"] = page.evaluate("""() => {
                const player = document.querySelector('.operating-preview');
                const display = player.style.display; player.style.display = 'none';
                const r = document.querySelector('.cost-summary').getBoundingClientRect();
                const result = {top:r.top,bottom:r.bottom,height:r.height};
                player.style.display = display; return result;
            }""")
            (OUTPUT / "desktop-1440x900-layout.json").write_text(
                json.dumps(layout, indent=2), encoding="utf-8"
            )
            page.screenshot(path=str(OUTPUT / "desktop-1440x900.png"), full_page=True)
            page.set_viewport_size({"width": 1440, "height": 1100})
            verify_motion("tubes")
            desktop = page.get_by_role("region", name="Operating preview", exact=True)
            desktop.get_by_label("Playback speed").select_option("1")
            desktop.get_by_role("button", name="Play", exact=True).click()
            timing = page.evaluate("""() => new Promise(resolve => {
              const times = []; let previous = performance.now(); const start = previous;
              function frame(now) { times.push(now - previous); previous = now;
                if(now-start < 10000) requestAnimationFrame(frame);
                else { times.shift(); times.sort((a,b)=>a-b); resolve({
                  frames:times.length, median_ms:times[Math.floor(times.length*.5)],
                  p95_ms:times[Math.floor(times.length*.95)],
                  over_50ms:times.filter(x=>x>50).length, duration_ms:now-start,
                  scope:'Headless Chrome on this test host; no physical/mobile FPS claim'
                }); }
              } requestAnimationFrame(frame);
            })""")
            desktop.get_by_role("button", name="Pause", exact=True).click()
            assert float(page.get_by_label("Operating timeline").input_value()) > 5
            (OUTPUT / "desktop-playback-timing.json").write_text(
                json.dumps(timing, indent=2), encoding="utf-8"
            )
            desktop.get_by_role("button", name="Reset", exact=True).click()
            desktop.get_by_label("Operating sequence").select_option("inspection")
            inspect_before = save()
            first_inspection = canvas("inspection-idle")
            desktop.get_by_role("button", name="Play", exact=True).click()
            page.wait_for_timeout(1000)
            desktop.get_by_role("button", name="Pause", exact=True).click()
            inspect_moved = canvas("inspection-paused")
            assert inspect_moved != first_inspection
            assert canvas("inspection-still") == inspect_moved
            inspect_timeline = desktop.get_by_label("Operating timeline")
            inspect_timeline.press("End")
            assert canvas("inspection-manual-end") != inspect_moved
            inspect_timeline.press("Home")
            assert canvas("inspection-manual-home") == first_inspection
            page.get_by_role("button", name="Expand 3D view", exact=True).click()
            expect(page.locator("canvas")).to_have_count(1)
            expect(desktop.get_by_role("button", name="Play", exact=True)).to_be_visible()
            desktop.get_by_role("button", name="Play", exact=True).focus()
            page.keyboard.press("Enter")
            page.wait_for_timeout(500)
            desktop.get_by_role("button", name="Pause", exact=True).focus()
            page.keyboard.press("Space")
            expect(desktop.get_by_role("button", name="Pause", exact=True)).to_be_disabled()
            page.locator(".viewer-shell").screenshot(path=str(OUTPUT / "expanded-controls.png"))
            page.keyboard.press("Escape")
            desktop.get_by_role("button", name="Reset", exact=True).click()
            assert save() == inspect_before
            desktop.get_by_label("Operating sequence").select_option("preparation")
            checks.append("inspection-play-pause-manual-seek-expanded-keyboard")
            send(SWITCH_WITH_VOLUME)
            verify_motion("plate")
            send(ALTERNATIVES)
            panel = page.get_by_role("region", name="Tip rack alternatives")
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/tip-rack-options") and response.request.method == "POST"
                )
            ) as response:
                panel.get_by_role("article").nth(1).get_by_role(
                    "button", name="Use this rack", exact=True
                ).click()
            assert response.value.ok, response.value.text()
            verify_motion("plate-supplier")
            with page.expect_download() as download:
                page.get_by_role("button", name="Save project", exact=True).click()
            saved_path = OUTPUT / "reopen-project.json"
            download.value.save_as(saved_path)
            with page.expect_response(lambda response: response.url.endswith("/open")) as opened:
                page.get_by_label("Open saved project").set_input_files(str(saved_path))
            assert opened.value.ok, opened.value.text()
            playback_details = page.locator(
                ".operating-preview details", has=page.locator("#operation-time")
            )
            if playback_details.get_attribute("open") is None:
                playback_details.locator(":scope > summary").click()
            expect(page.get_by_role("slider", name="Operating timeline")).to_have_value("0")
            expect(page.get_by_role("button", name="Pause", exact=True)).to_be_disabled()
            checks.append("save-open-reset")
            page.set_viewport_size({"width": 390, "height": 844})
            page.get_by_role("navigation", name="Workspace view").get_by_role(
                "button", name="Design", exact=True
            ).click()
            mobile_panel = page.get_by_role("region", name="Operating preview", exact=True)
            mobile_panel.get_by_role("button", name="Play", exact=True).click()
            page.wait_for_timeout(400)
            page.get_by_role("navigation", name="Workspace view").get_by_role(
                "button", name="Chat", exact=True
            ).click()
            page.wait_for_timeout(150)
            hidden_time = page.locator("#operation-time").input_value()
            page.wait_for_timeout(350)
            assert page.locator("#operation-time").input_value() == hidden_time
            page.get_by_role("navigation", name="Workspace view").get_by_role(
                "button", name="Design", exact=True
            ).click()
            expect(mobile_panel.get_by_role("button", name="Pause", exact=True)).to_be_disabled()
            checks.append("mobile-hidden-preview-pauses")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page.get_by_role("region", name="Operating preview").screenshot(
                path=str(OUTPUT / "controls-mobile.png")
            )
            checks.append("mobile-controls-no-overflow")
            assert not errors, errors
            (OUTPUT / "result.json").write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "checks": checks,
                        "page_errors": errors,
                        "scope": "Illustrative WebGL/browser regression; no hardware validation",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        finally:
            page.screenshot(path=str(OUTPUT / "final.png"), full_page=True)
            (OUTPUT / "final.html").write_text(page.content(), encoding="utf-8")
            browser.close()


if __name__ == "__main__":
    if "--port" in sys.argv:
        serve()
    elif os.environ.get("OPERATING_PREVIEW_URL"):
        run(os.environ["OPERATING_PREVIEW_URL"])
    else:
        harness.STUB_SERVER = Path(__file__).resolve()
        harness.run_smoke = run
        raise SystemExit(harness.main())
