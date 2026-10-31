"""One-chat labware switching with real UI/compiler/state and offline extraction.

No Meta, supplier request or heavy CAD generation. Conflicting recipe volumes
remain unchanged until the user explicitly changes them through ordinary chat.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import browser_smoke as harness  # noqa: E402
from browser_labware_server import COMPLETE  # noqa: E402
from browser_microplate_server import RESOLVE, RETURN, SWITCH_ONLY, SWITCH_WITH_VOLUME  # noqa: E402


def run(url):
    from playwright.sync_api import expect, sync_playwright

    output = harness.ROOT / ".local" / "microplate-20261030" / "ui"
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

        def send(message):
            with page.expect_response(
                lambda response: response.url.endswith("/messages")
            ) as result:
                field = page.get_by_label("Describe your workflow or request a change")
                expect(field).to_be_enabled()
                field.fill(message)
                page.get_by_role("button", name="Send message", exact=True).click()
            response = result.value
            assert response.ok, response.text()
            expect(field).to_be_enabled()
            return response.json()["project"]

        try:
            page.goto(url, wait_until="networkidle")
            expect(page.get_by_text("Workspace ready")).to_be_visible()
            page.get_by_label("Open saved project").set_input_files(
                str(harness.ROOT / "docs/examples/demo-video-project.json")
            )
            expect(page.locator(".storage-notice")).to_contain_text("rebuilt")
            tubes = send(COMPLETE)
            expect(page.locator(".labware-rack-panel")).to_contain_text("6 tubes")
            assert tubes["summary"]["final_volume"] == "2 mL"
            page.get_by_role("button", name="Show rack in model").click()
            page.get_by_label("Inspect component view").select_option("part")
            plate = send(SWITCH_ONLY)
            card = page.locator(".microplate-panel")
            expect(card).to_contain_text("96 wells")
            expect(card).to_contain_text("Revise recipe volume")
            expect(card).to_contain_text("2000 µL")
            expect(card).to_contain_text("360 µL")
            expect(page.get_by_label("Inspect component view")).to_have_value("part")
            expect(page.locator(".microplate-axis-label")).to_have_count(20)
            preparation = page.locator("details.prep-plan")
            if preparation.get_attribute("open") is None:
                preparation.locator(":scope > summary").click()
            expect(preparation).to_contain_text("one well per target")
            expect(preparation.locator(".plan-table")).to_contain_text("A1")
            expect(preparation.locator(".plan-table")).to_contain_text("B1")
            expect(page.get_by_role("button", name="Confirm design")).to_be_disabled()
            assert plate["summary"]["final_volume"] == "2 mL"
            assert plate["plan"]["status"] == "invalid"
            assert not plate.get("labware_rack")
            assert plate["labware_brief"] == tubes["labware_brief"]
            assert plate["design"]["foundation"] == tubes["design"]["foundation"]
            source_before = next(
                part for part in tubes["design"]["components"] if part["id"] == "source-rack"
            )
            source_after = next(
                part for part in plate["design"]["components"] if part["id"] == "source-rack"
            )
            assert source_before == source_after
            assert len(plate["labware_plate"]["derived"]["wells"]) == 96
            assert plate["labware_plate"]["compatibility"]["occupied_wells"] == ["A1", "B1", "C1"]
            sample = next(
                part for part in plate["design"]["components"] if part["id"] == "sample-rack"
            )
            well_plate = next(
                primitive
                for primitive in sample["geometry"]["primitives"]
                if primitive["id"] == "reference-plate-wells"
            )
            assert len(well_plate["holes"]) == 96
            with page.expect_response(lambda response: "/instructions?" in response.url) as result:
                page.get_by_role("button", name="Build instructions").click()
            guide = result.value.json()
            volume_index = next(
                i for i, step in enumerate(guide["steps"]) if step["id"] == "plate-volume"
            )
            guide_panel = page.locator("#build-instructions-panel")
            guide_panel.get_by_label("Go to step").select_option(str(volume_index))
            expect(guide_panel).to_contain_text("2000 µL")
            expect(guide_panel).to_contain_text("360 µL")
            assert not any(step["id"].startswith("rack-") for step in guide["steps"])
            repaired = send(RESOLVE)
            assert repaired["labware_plate"]["compatibility"]["status"] == "ready"
            assert repaired["plan"]["status"] == "ready"
            assert len(repaired["plan"]["steps"]) == 3
            assert (
                repaired["summary"]["stock_concentration"]
                == tubes["summary"]["stock_concentration"]
            )
            assert (
                repaired["summary"]["target_concentrations"]
                == tubes["summary"]["target_concentrations"]
            )
            expect(card).to_contain_text("3 occupied · 93 free")
            expect(card).to_contain_text("200 µL")
            card.get_by_role("button", name="Show plate in model").click()
            page.get_by_label("Inspect component view").select_option("part")
            expect(page.locator(".microplate-axis-label")).to_have_count(20)
            expect(page.locator(".scene-rack-occupancy")).to_contain_text("3 / 96 wells occupied")
            page.locator(".viewer-shell").scroll_into_view_if_needed()
            page.evaluate(
                "() => new Promise(resolve => requestAnimationFrame(() => "
                "requestAnimationFrame(resolve)))"
            )
            page.locator(".viewer-shell").screenshot(path=str(output / "plate-96-focused.png"))
            with page.expect_download() as download:
                page.get_by_role("button", name="Save project", exact=True).click()
            saved = download.value.path()
            saved_json = json.loads(Path(saved).read_text(encoding="utf8"))
            assert saved_json["labware_plate"]["profile_id"] == plate["labware_plate"]["profile_id"]
            page.get_by_label("Open saved project").set_input_files(saved)
            expect(page.locator(".storage-notice")).to_contain_text("rebuilt")
            expect(card).to_contain_text("3 occupied · 93 free")
            restored_tubes = send(RETURN)
            assert not restored_tubes.get("labware_plate")
            assert restored_tubes["labware_rack"]["spec"] == tubes["labware_rack"]["spec"]
            assert restored_tubes["labware_rack"]["size_mm"] == tubes["labware_rack"]["size_mm"]
            expect(page.locator(".labware-rack-panel")).to_contain_text("6 tubes")
            before_count = sum(path.endswith("/messages") for path in posts)
            final = send(SWITCH_WITH_VOLUME)
            assert sum(path.endswith("/messages") for path in posts) == before_count + 1
            assert final["labware_plate"]["compatibility"]["status"] == "ready"
            assert final["labware_plate"]["compatibility"]["requested_volume_ul"] == 200
            assert len(final["plan"]["steps"]) == 3
            expect(card).to_contain_text("96 wells")
            expect(page.locator(".labware-rack-panel:not(.microplate-panel)")).to_have_count(0)
            with page.expect_response(lambda response: "/instructions?" in response.url) as result:
                page.get_by_role("button", name="Build instructions").click()
            current_guide = result.value.json()
            assert current_guide["project_revision"] == final["revision"]
            assert current_guide["labware_plate"]["compatibility"]["occupied_wells"] == [
                "A1",
                "B1",
                "C1",
            ]
            with page.expect_download() as download:
                page.get_by_role("link", name="Download guide JSON", exact=True).click()
            exported = json.loads(Path(download.value.path()).read_text(encoding="utf8"))
            assert exported == current_guide
            page.set_viewport_size({"width": 390, "height": 844})
            card.scroll_into_view_if_needed()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
            page.screenshot(path=str(output / "plate-mobile.png"), full_page=True)
            assert not errors, errors
            assert not any(
                path.endswith(("/procurement/refresh", "/exports", "/design")) for path in posts
            )
            (output / "browser-result.json").write_text(
                json.dumps(
                    {
                        "revision": final["revision"],
                        "profile": final["labware_plate"]["profile_id"],
                        "wells": 96,
                        "occupied": ["A1", "B1", "C1"],
                        "requested_volume_ul": 200,
                        "single_message_switch": True,
                        "source": "Offline extraction; actual API/compiler/state/browser/guides.",
                    },
                    indent=2,
                ),
                encoding="utf8",
            )
            print(
                "[browser-microplate] One-message switch, 96 wells, volume conflict/resolution, "
                "source orientation, save/reopen, tube return and guide revision passed."
            )
        finally:
            browser.close()


if __name__ == "__main__":
    harness.STUB_SERVER = Path(__file__).with_name("browser_microplate_server.py")
    harness.run_smoke = run
    raise SystemExit(harness.main())
