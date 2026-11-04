"""Two-phase browser acceptance using real API/compiler and offline AI transport.

Run with the repository .venv Python. Chrome and the locked web dependencies
must be installed. Writes ignored screenshots/evidence under .local. No live
model, supplier request or hardware operation is performed.
"""

from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
import browser_smoke as harness  # noqa: E402

OUTPUT = ROOT / ".local/hardware-software-qa"


def serve():
    import browser_foundation_server as foundation
    import uvicorn
    from test_design_workflow import hardware
    from test_microplates import select

    import app.api as api
    from app.design_workflow import refresh_workflow
    from app.model_client import ExtractedTurn

    initial = refresh_workflow(select(hardware()))
    api.new_project = lambda: deepcopy(initial)

    async def offline_chat(project, message, history, **kwargs):
        if message == "Make the next recipe 0.25 mg/mL in 200 uL from the same stock.":
            return ExtractedTurn(
                assistant_message="The next recipe uses 50 uL stock and 150 uL diluent.",
                target_concentrations="0.25 mg/mL",
                source_target_concentrations="0.25 mg/mL",
                final_volume="200 uL",
                source_final_volume="200 uL",
            ), {"model": "offline-software-acceptance"}
        raise ValueError("Only the documented synthetic software request is supported.")

    api.generate_turn = offline_chat
    args = foundation.baseline.parse_args()
    uvicorn.run(api.app, host="127.0.0.1", port=args.port, log_level="warning")


def run(url):
    from playwright.sync_api import expect, sync_playwright

    OUTPUT.mkdir(parents=True, exist_ok=True)
    checks = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(
            viewport={"width": 1600, "height": 1100}, reduced_motion="reduce"
        )
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route(
            "**/cost-estimate*",
            lambda route: route.fulfill(
                json={
                    "state": "not_estimated",
                    "estimate": None,
                }
            ),
        )
        page.route("**/procurement/refresh*", lambda route: route.abort())
        with page.expect_response(
            lambda response: (
                response.url.endswith("/api/projects") and response.request.method == "POST"
            )
        ) as created:
            page.goto(url, wait_until="networkidle")
        try:
            expect(
                page.get_by_role("button", name="Approve design & open software").first
            ).to_be_visible()
            # Canonical source state is inspected through the actual browser/API.
            project = created.value.json()["project"]
            project_id = project["id"]
            baseline = {
                field: deepcopy(project.get(field))
                for field in ("design", "sourcing", "selections", "tip_rack")
            }
            plate_geometry = deepcopy(project["labware_plate"]["geometry"])
            assert project["summary"]["stock_concentration"] is None
            assert project["plan"]["steps"] == []
            page.get_by_role("button", name="Motion preview", exact=True).click()
            preview = page.get_by_role("region", name="Operating preview", exact=True)
            expect(preview).to_contain_text("Example motion")
            expect(preview).to_contain_text("Approve the design to program your own transfers")
            expect(preview).to_contain_text("1 mg/mL")
            expect(preview).to_contain_text("0.5 mg/mL")
            expect(preview).to_contain_text("100 µL")
            preview.get_by_role("button", name="Play", exact=True).click()
            expect(preview.get_by_role("button", name="Pause", exact=True)).to_be_enabled()
            preview.get_by_role("button", name="Reset", exact=True).click()
            expect(preview.get_by_role("button", name="Download motion plan")).to_have_count(0)
            canonical = page.evaluate(
                "async id => (await (await fetch('/api/projects/' + id)).json()).project",
                project_id,
            )
            assert canonical["summary"]["stock_concentration"] is None
            assert canonical["plan"]["steps"] == []
            page.screenshot(path=str(OUTPUT / "hardware-desktop.png"), full_page=True)
            checks.append("hardware-pre-recipe-illustrative-play-reset-without-canonical-recipe")
            page.get_by_role("button", name="Approve design & open software").first.click()
            expect(
                page.get_by_role("heading", name="Software & protocols", exact=True)
            ).to_be_visible()
            expect(page.get_by_label("Stock concentration", exact=True)).to_have_value("")
            expect(page.get_by_role("button", name="Create protocol", exact=True)).to_be_disabled()
            expect(page.get_by_role("link", name="Download Python program")).to_have_count(0)
            expect(
                page.get_by_role("region", name="Operating preview", exact=True)
            ).to_contain_text("Example motion")
            checks.append("explicit-approval-opens-software-with-incomplete-recipe-gated")
            page.get_by_label("Stock concentration", exact=True).fill("1 mg/mL")
            page.get_by_label("Target concentrations", exact=True).fill("0.5 mg/mL")
            page.get_by_label("Final volume per destination", exact=True).fill("2 mL")
            with page.expect_response(
                lambda response: response.url.endswith("/program-recipe")
            ) as response:
                page.get_by_role("button", name="Create protocol", exact=True).click()
            assert response.value.status == 422
            expect(page.get_by_role("alert")).to_be_visible()
            expect(page.get_by_role("button", name="Play", exact=True)).to_be_disabled()
            assert response.value.json()["detail"]
            checks.append("invalid-volume-rejected-and-playback-disabled-for-unapplied-inputs")
            page.get_by_label("Final volume per destination", exact=True).fill("100 uL")
            with page.expect_response(
                lambda response: response.url.endswith("/program-recipe")
            ) as response:
                page.get_by_role("button", name="Create protocol", exact=True).click()
            assert response.value.ok, response.value.text()
            expect(
                page.get_by_role("region", name="Operating preview", exact=True)
            ).to_contain_text("Recipe motion")
            programmed = response.value.json()["project"]
            for field, value in baseline.items():
                assert programmed.get(field) == value, field
            assert programmed["labware_plate"]["geometry"] == plate_geometry
            assert programmed["plan"]["steps"][0]["stock_volume_ul"] == 50
            expect(page.get_by_role("button", name="Python program", exact=True)).to_have_attribute(
                "aria-pressed", "true"
            )
            code = page.get_by_label("Generated Python program")
            expect(code).to_contain_text("50")
            expect(code).to_contain_text("def ")
            expect(page.get_by_role("link", name="Download Python program")).to_be_visible()
            page.screenshot(path=str(OUTPUT / "software-desktop.png"), full_page=True)
            page.get_by_role("button", name="Operations & volumes", exact=True).click()
            expect(page.get_by_role("cell", name="50", exact=True)).to_have_count(2)
            checks.append(
                "real-python-program-and-transfer-table-use-current-recipe-preserve-model-prices-tips"
            )
            page.get_by_label("Target concentrations", exact=True).fill("0.2 mg/mL")
            page.get_by_label("Final volume per destination", exact=True).fill("200 uL")
            with page.expect_response(
                lambda response: response.url.endswith("/program-recipe")
            ) as response:
                page.get_by_role("button", name="Update protocol", exact=True).click()
            second = response.value.json()["project"]
            assert second["plan"]["steps"][0]["stock_volume_ul"] == 40
            assert second["plan"]["steps"][0]["diluent_volume_ul"] == 160
            for field, value in baseline.items():
                assert second.get(field) == value, field
            page.get_by_label("Ask the assistant", exact=True).fill(
                "Make the next recipe 0.25 mg/mL in 200 uL from the same stock."
            )
            with page.expect_response(
                lambda response: response.url.endswith("/messages")
            ) as response:
                page.get_by_role("button", name="Apply request", exact=True).click()
            assert response.value.ok, response.value.text()
            expect(page.get_by_label("Target concentrations", exact=True)).to_have_value(
                "0.25 mg/mL"
            )
            expect(page.get_by_role("cell", name="150", exact=True)).to_be_visible()
            checks.append("typed-next-recipe-and-offline-muse-chat-update-canonical-protocol")
            page.get_by_role("button", name="3D design", exact=True).click()
            expect(page.get_by_role("heading", name="Design assistant", exact=True)).to_be_visible()
            page.get_by_role("button", name="Software & protocols", exact=True).click()
            expect(page.get_by_label("Target concentrations", exact=True)).to_have_value(
                "0.25 mg/mL"
            )
            page.wait_for_timeout(250)
            page.reload(wait_until="networkidle")
            expect(
                page.get_by_role("heading", name="Software & protocols", exact=True)
            ).to_be_visible()
            expect(page.get_by_label("Target concentrations", exact=True)).to_have_value(
                "0.25 mg/mL"
            )
            checks.append("return-to-hardware-reopen-software-and-browser-reload-preserve-recipe")
            page.set_viewport_size({"width": 390, "height": 844})
            expect(page.get_by_label("Stock concentration", exact=True)).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page.screenshot(path=str(OUTPUT / "software-mobile.png"), full_page=True)
            expect(page.get_by_role("button", name="Play", exact=True)).to_be_enabled()
            page.get_by_role("button", name="Play", exact=True).click()
            expect(page.get_by_role("button", name="Pause", exact=True)).to_be_enabled()
            page.get_by_role("button", name="Reset", exact=True).click()
            checks.append("mobile-controls-play-reset-and-no-horizontal-overflow")
            assert not errors, errors
            (OUTPUT / "result.json").write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "checks": checks,
                        "page_errors": errors,
                        "scope": (
                            "Real DOM/API/compiler/WebGL with offline AI fixture; "
                            "stored reference prices retained, no live price/model "
                            "or hardware validation."
                        ),
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
    elif os.environ.get("HARDWARE_SOFTWARE_URL"):
        run(os.environ["HARDWARE_SOFTWARE_URL"])
    else:
        harness.STUB_SERVER = Path(__file__).resolve()
        harness.run_smoke = run
        raise SystemExit(harness.main())
