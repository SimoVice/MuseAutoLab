"""Real browser/API/compiler tip-rack choices with offline language extraction.

Source labels, actual dimensions, failed request rollback, portable state,
printer conversation, custom holder and mobile view are checked without live calls.
"""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import browser_smoke as harness  # noqa: E402
from browser_tip_options_server import ALTERNATIVES, NO_PRINTER, PRINTED_DIMENSIONS, YES_PRINTER  # noqa: E402


def run(url):
    from playwright.sync_api import expect, sync_playwright

    output = harness.ROOT / ".local" / "tip-options-20261031" / "ui"
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(
            viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", accept_downloads=True
        )
        errors, projects, requests = [], [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda request: requests.append(request.url) if request.method == "POST" else None,
        )

        def record(response):
            if (
                response.request.method == "POST"
                and response.ok
                and response.url.endswith(("/messages", "/open", "/tip-rack-options"))
            ):
                data = response.json()
                if data.get("project"):
                    projects.append(data["project"])

        page.on("response", record)
        composer = page.get_by_label("Describe your workflow or request a change")

        def send(message):
            with page.expect_response(
                lambda response: response.url.endswith("/messages")
            ) as result:
                expect(composer).to_be_enabled()
                composer.fill(message)
                page.get_by_role("button", name="Send message", exact=True).click()
            assert result.value.ok, result.value.text()
            expect(composer).to_be_enabled()
            return result.value.json()["project"]

        def choose(card):
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/tip-rack-options") and response.request.method == "POST"
                )
            ) as result:
                card.get_by_role("button", name="Use this rack", exact=True).click()
            assert result.value.ok, result.value.text()
            expect(composer).to_be_enabled()
            return result.value.json()["project"]

        def screenshot(name):
            page.get_by_role("button", name="Expand 3D view", exact=True).click()
            page.get_by_label("Component in expanded view").select_option("tip-rack")
            page.get_by_label("Inspect component view").select_option("part")
            page.wait_for_timeout(800)
            path = output / name
            page.locator(".viewer-shell").screenshot(path=str(path))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            page.keyboard.press("Escape")
            return digest

        try:
            page.goto(url, wait_until="networkidle")
            expect(page.get_by_text("Workspace ready")).to_be_visible()
            page.get_by_label("Open saved project").set_input_files(
                str(harness.ROOT / "docs/examples/demo-video-project.json")
            )
            expect(page.locator(".storage-notice")).to_contain_text("rebuilt")
            expect(page.get_by_role("region", name="Tip rack alternatives")).to_have_count(0)
            base = send(ALTERNATIVES)
            panel = page.get_by_role("region", name="Tip rack alternatives")
            expect(panel).to_contain_text("3D printer access is not confirmed")
            expect(panel.get_by_role("article")).to_have_count(2)
            expect(panel.get_by_role("article").nth(0)).to_contain_text("repositioning")
            expect(page.locator(".conversation-scroll")).to_contain_text(
                "Do you have access to a 3D printer"
            )
            first = choose(panel.get_by_role("article").nth(0))
            expect(page.locator(".selection-block")).to_contain_text("Pinned product reference")
            page.get_by_label("Inspect component view").select_option("part")
            first_hash = screenshot("commercial-first.png")
            expect(panel.get_by_role("article").nth(0)).to_contain_text("In the model")
            expect(page.get_by_label("Inspect component view")).to_have_value("part")
            for _ in range(3):
                page.get_by_role("button", name="Rotate right").click()
            page.locator(".viewer-shell").screenshot(
                path=str(output / "focus-before-product-change.png")
            )
            second = choose(panel.get_by_role("article").nth(1))
            expect(page.get_by_label("Inspect component view")).to_have_value("part")
            expect(page.locator(".selection-block")).to_contain_text("Opentrons 96 Tip Rack 300")
            page.locator(".viewer-shell").screenshot(
                path=str(output / "focus-after-product-change.png")
            )
            first_part = next(
                part for part in first["design"]["components"] if part["id"] == "tip-rack"
            )
            second_part = next(
                part for part in second["design"]["components"] if part["id"] == "tip-rack"
            )
            assert first_part["size"] != second_part["size"]
            assert first_part["geometry"] != second_part["geometry"]
            assert first["summary"] == second["summary"] == base["summary"]
            assert first["plan"] == second["plan"] == base["plan"]
            assert first["design"]["foundation"] == second["design"]["foundation"]
            assert [part for part in first["design"]["components"] if part["id"] != "tip-rack"] == [
                part for part in second["design"]["components"] if part["id"] != "tip-rack"
            ]
            second_hash = screenshot("commercial-second.png")
            assert first_hash != second_hash
            expect(panel).to_contain_text("Price and availability not verified")
            expect(
                panel.get_by_role("link", name="Product / geometry source").first
            ).to_have_attribute("href", first["tip_rack"]["profile"]["source"]["source_url"])
            page.route(
                "**/tip-rack-options",
                lambda route: (
                    route.fulfill(
                        status=409, json={"detail": "Fixture unavailable: choice was not applied."}
                    )
                    if route.request.method == "POST"
                    else route.continue_()
                ),
            )
            panel.get_by_role("article").nth(0).get_by_role(
                "button", name="Use this rack", exact=True
            ).click()
            expect(page.get_by_role("alert")).to_contain_text("choice was not applied")
            expect(panel.get_by_role("article").nth(1)).to_contain_text("In the model")
            assert projects[-1] == second
            page.unroute("**/tip-rack-options")
            with page.expect_download() as download:
                page.get_by_role("button", name="Save project", exact=True).click()
            saved = download.value.path()
            snapshot = json.loads(Path(saved).read_text(encoding="utf8"))
            page.get_by_label("Open saved project").set_input_files(saved)
            expect(panel.get_by_role("article").nth(1)).to_contain_text("In the model")
            restored = projects[-1]
            assert restored["tip_rack"]["profile_id"] == second["tip_rack"]["profile_id"]
            assert restored["tip_rack"]["geometry"] == second["tip_rack"]["geometry"]
            no_printer = send(NO_PRINTER)
            assert no_printer["fabrication_capabilities"]["printer_available"] == "no"
            expect(panel.get_by_role("article")).to_have_count(2)
            expect(panel).to_contain_text("No 3D printer access")
            yes_printer = send(YES_PRINTER)
            assert yes_printer["fabrication_capabilities"]["printer_available"] == "yes"
            expect(panel.get_by_role("article")).to_have_count(3)
            printed_card = panel.get_by_role("article").nth(2)
            with page.expect_response(
                lambda response: (
                    response.url.endswith("/tip-rack-options") and response.request.method == "POST"
                )
            ):
                printed_card.get_by_role("button", name="Discuss dimensions in chat").click()
            expect(composer).to_be_enabled()
            expect(page.locator(".conversation-scroll")).to_contain_text("provide")
            assert projects[-1]["tip_rack"]["profile_id"] == second["tip_rack"]["profile_id"]
            printed = send(PRINTED_DIMENSIONS)
            assert printed["tip_rack"]["kind"] == "rim_supported_tip_rack"
            assert printed["summary"] == base["summary"]
            page.get_by_role("button", name="Inspect tip rack", exact=True).click()
            expect(page.locator(".selection-block")).to_contain_text("Custom printable geometry")
            screenshot("printed-holder.png")
            with page.expect_response(
                lambda response: "/instructions?" in response.url
            ) as response:
                page.get_by_role("button", name="Build instructions").click()
            guide = response.value.json()
            assert guide["project_revision"] == printed["revision"]
            assert any("tip" in step["id"] for step in guide["steps"])
            with page.expect_download() as download:
                page.get_by_role("button", name="Save project", exact=True).click()
            page.get_by_label("Open saved project").set_input_files(download.value.path())
            expect(panel.get_by_role("article").nth(2)).to_contain_text("In the model")
            restored_printed = projects[-1]
            assert restored_printed["tip_rack"]["geometry"] == printed["tip_rack"]["geometry"]
            assert restored_printed["tip_rack"]["spec"] == printed["tip_rack"]["spec"]
            assert restored_printed["fabrication_capabilities"]["printer_available"] == "yes"
            page.set_viewport_size({"width": 390, "height": 844})
            panel.scroll_into_view_if_needed()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
            page.screenshot(path=str(output / "options-mobile.png"), full_page=True)
            assert not errors, errors
            assert not any(
                path.endswith(("/procurement/refresh", "/exports", "/design")) for path in requests
            )
            evidence = {
                "scope": (
                    "Offline extraction; actual API/compiler/state/browser. "
                    "Unavailable choice is an injected HTTP failure."
                ),
                "commercial_profiles": [
                    first["tip_rack"]["profile_id"],
                    second["tip_rack"]["profile_id"],
                ],
                "sizes_mm": [first_part["size"], second_part["size"]],
                "screenshot_sha256": [first_hash, second_hash],
                "printed_size_mm": printed["tip_rack"]["size_mm"],
                "saved_profile": restored["tip_rack"]["profile_id"],
                "rollback": True,
                "printer_gating": True,
                "printed_save_reopen": True,
                "mobile": True,
                "snapshot_revision": snapshot["revision"],
            }
            (output / "browser-result.json").write_text(
                json.dumps(evidence, indent=2), encoding="utf8"
            )
            print(
                "[browser-tip-options] Commercial geometry, sources, recipe preservation, "
                "rollback, save/reopen, printer conversation, printable holder, instructions "
                "and mobile passed."
            )
        except Exception:
            import traceback

            traceback.print_exc()
            page.screenshot(path=str(output / "failure.png"), full_page=True)
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    harness.STUB_SERVER = Path(__file__).with_name("browser_tip_options_server.py")
    harness.run_smoke = run
    raise SystemExit(harness.main())
