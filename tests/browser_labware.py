"""Chat-only rack generation with real API, geometry, portable state and guides.

Meta extraction is an explicit synthetic fixture; no supplier, model or CAD export
job is called. This is digital coherence evidence, not a printed fit result.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import browser_smoke as harness  # noqa: E402
from browser_labware_server import COMPLETE, EDIT, PARTIAL, REJECT, SIX_TARGETS  # noqa: E402


def run(url):
    from playwright.sync_api import expect, sync_playwright

    output = harness.ROOT / ".local" / "parametric-rack-20261030" / "ui"
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
        errors, posts = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda request: posts.append(request.url) if request.method == "POST" else None,
        )
        try:
            page.goto(url)
            page.wait_for_load_state("networkidle")
            expect(page.get_by_text("Workspace ready")).to_be_visible()
            with page.expect_response(lambda response: response.url.endswith("/open")) as opened:
                page.get_by_label("Open saved project").set_input_files(
                    str(harness.ROOT / "docs/examples/demo-video-project.json")
                )
            original = opened.value.json()["project"]
            expect(page.locator("canvas")).to_have_count(1)
            expect(page.locator(".scene-loading")).to_have_count(0, timeout=60000)
            with page.expect_response(
                lambda response: response.url.endswith("/messages")
            ) as result:
                harness.send_chat(page, PARTIAL, "inputs still needed")
            partial = result.value.json()["project"]
            panel = page.locator(".labware-rack-panel")
            expect(panel).to_contain_text("Dimensions needed")
            expect(panel).to_contain_text("Minimum support rim diameter")
            expect(panel).to_contain_text("does not define fit")
            assert partial["design"]["components"] == original["design"]["components"]
            assert not partial.get("labware_rack")
            with page.expect_response(
                lambda response: response.url.endswith("/messages")
            ) as result:
                harness.send_chat(page, COMPLETE, "Applied the rim-supported tube rack")
            accepted = result.value.json()["project"]
            expect(panel).to_contain_text("6 tubes")
            expect(panel).to_contain_text("11.9 mm")
            expect(panel).to_contain_text("15.2 mm")
            expect(panel).to_contain_text("One-piece bridge rack")
            assert accepted["design"]["foundation"] == original["design"]["foundation"]
            for key in ("proposal", "components", "provenance", "attachment"):
                assert (
                    accepted["inspection_extension"][key] == original["inspection_extension"][key]
                )
            before = {part["id"]: part for part in original["design"]["components"]}
            after = {part["id"]: part for part in accepted["design"]["components"]}
            assert after["source-rack"] == before["source-rack"]
            assert after["sample-rack"]["size"] != before["sample-rack"]["size"]
            groups = accepted["sourcing"]["groups"]
            printed = next(group for group in groups if group["id"] == "labware-rack")
            fixtures = next(group for group in groups if group["id"] == "fixtures")
            assert printed["quantity"] == 1 and printed["component_ids"] == ["sample-rack"]
            assert "sample-rack" not in fixtures["component_ids"]
            old_guide_url = (
                f"{url}api/projects/{accepted['id']}/instructions/download"
                f"?revision={accepted['revision']}&format=json"
            )
            panel.get_by_role("button", name="Show rack in model").click()
            expect(page.locator(".selection-block")).to_contain_text("rim-supported tube rack")
            page.get_by_label("Inspect component view").select_option("part")
            page.locator(".viewer-shell").scroll_into_view_if_needed()
            page.evaluate(
                "() => new Promise(resolve => requestAnimationFrame(() => "
                "requestAnimationFrame(resolve)))"
            )
            page.screenshot(path=str(output / "six-position-rack.png"))
            page.locator(".viewer-shell").screenshot(path=str(output / "six-position-detail.png"))
            page.get_by_role("button", name="Show full model", exact=True).click()
            with page.expect_response(
                lambda response: response.url.endswith("/messages")
            ) as result:
                harness.send_chat(page, SIX_TARGETS, "six preparation targets")
            six = result.value.json()["project"]
            assert len(six["plan"]["steps"]) == 6
            with page.expect_response(
                lambda response: response.url.endswith("/messages")
            ) as result:
                harness.send_chat(page, EDIT, "Applied the rim-supported tube rack")
            edited = result.value.json()["project"]
            expect(panel).to_contain_text("12 tubes")
            expect(panel).to_contain_text("3 rows × 4 columns")
            expect(panel).to_contain_text(
                "6 preparation targets use this rack; 6 positions remain free"
            )
            expect(page.locator(".scene-rack-occupancy")).to_have_text(
                "6 / 12 positions occupied · tube envelopes"
            )
            plate = edited["labware_rack"]["geometry"]["primitives"][0]
            assert len(plate["holes"]) == 12
            assert len({hole["z_mm"] for hole in plate["holes"]}) == 3
            assert page.request.get(old_guide_url).status == 409
            with page.expect_response(
                lambda response: response.url.endswith("/messages")
            ) as result:
                harness.send_chat(page, REJECT, "Rim is too narrow")
            assert result.value.json()["project"] == edited
            expect(panel).to_contain_text("12 tubes")
            expect(page.locator("canvas")).to_have_count(1)
            with page.expect_response(
                lambda response: "/instructions?" in response.url
            ) as guide_result:
                harness.send_chat(
                    page, "How do I buy the pieces and assemble this?", "Build instructions"
                )
            guide_panel = page.locator("#build-instructions-panel")
            expect(guide_panel.locator(".instruction-step")).to_be_visible()
            guide_steps = guide_result.value.json()["steps"]
            print_index = next(
                i for i, step in enumerate(guide_steps) if step["id"] == "rack-print"
            )
            guide_panel.get_by_label("Go to step").select_option(str(print_index))
            expect(guide_panel).to_contain_text("end legs pointing upward")
            expect(guide_panel).to_contain_text("PETG is a proposed")
            with page.expect_download() as download:
                guide_panel.get_by_role("link", name="Download guide JSON").click()
            guide = json.loads(Path(download.value.path()).read_text(encoding="utf8"))
            assert guide["project_revision"] == edited["revision"]
            assert guide["labware_rack"]["spec"]["count"] == 12
            assert guide["labware_rack"]["size_mm"] == edited["labware_rack"]["size_mm"]
            guide_url = guide_panel.get_by_role("link", name="Download guide JSON").get_attribute(
                "href"
            )
            with page.expect_download() as download:
                page.get_by_role("button", name="Save project", exact=True).click()
            saved = download.value.path()
            saved_data = json.loads(Path(saved).read_text(encoding="utf8"))
            assert saved_data["labware_brief"]["spec"]["count"] == 12
            page.get_by_label("Open saved project").set_input_files(saved)
            expect(page.locator(".storage-notice")).to_contain_text("rebuilt")
            expect(panel).to_contain_text("12 tubes")
            expect(panel).to_contain_text(
                "6 preparation targets use this rack; 6 positions remain free"
            )
            page.get_by_role("button", name="Show rack in model").click()
            page.get_by_label("Inspect component view").select_option("part")
            page.locator(".viewer-shell").scroll_into_view_if_needed()
            page.evaluate(
                "() => new Promise(resolve => requestAnimationFrame(() => "
                "requestAnimationFrame(resolve)))"
            )
            page.screenshot(path=str(output / "twelve-position-rack.png"))
            page.locator(".viewer-shell").screenshot(
                path=str(output / "twelve-position-detail.png")
            )
            page.set_viewport_size({"width": 390, "height": 844})
            panel.scroll_into_view_if_needed()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
            page.screenshot(path=str(output / "rack-mobile.png"), full_page=True)
            preparation = page.locator("details.prep-plan")
            if preparation.get_attribute("open") is None:
                preparation.locator(":scope > summary").click()
            page.get_by_role("button", name="Confirm design").click()
            expect(page.locator(".chat-status")).to_have_text("Confirmed")
            details = page.locator("details.project-details")
            if details.get_attribute("open") is None:
                details.locator(":scope > summary").click()
            expect(page.get_by_role("button", name="Play preview", exact=True)).to_have_count(0)
            expect(details).to_contain_text("operating preview is unavailable for this custom rack")
            assert not errors, errors
            assert not any(
                path.endswith(("/procurement/refresh", "/exports", "/design")) for path in posts
            )
            (output / "browser-result.json").write_text(
                json.dumps(
                    {
                        "project_revision": edited["revision"],
                        "rack_count": 12,
                        "occupied_positions": 6,
                        "unused_positions": 6,
                        "size_mm": edited["labware_rack"]["size_mm"],
                        "guide_url": guide_url,
                        "scope": "Offline extraction; real API/compiler/viewer/state/instructions. "
                        "No physical fit evidence.",
                    },
                    indent=2,
                ),
                encoding="utf8",
            )
            print(
                "[browser-labware] Partial measurements, rack generation/edit/rejection, "
                "scoped BOM, "
                "12-hole capacity, save/reopen, instruction downloads and mobile passed."
            )
        finally:
            browser.close()


if __name__ == "__main__":
    harness.STUB_SERVER = Path(__file__).with_name("browser_labware_server.py")
    harness.run_smoke = run
    raise SystemExit(harness.main())
