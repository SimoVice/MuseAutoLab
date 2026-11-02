"""Fresh natural platform choice through real UI/compiler with offline AI fixtures.

These exact English inputs are synthetic browser regressions. No live model,
supplier lookup, user browser storage or physical validation is involved.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import browser_smoke as harness

FIRST = (
    "I prepare dilutions and aliquots by hand in 1.5 mL microcentrifuge tubes. "
    "I’d like a workstation I can reuse for different pipetting protocols. "
    "I have 800 mm of bench width and I’m comfortable assembling open hardware. "
    "Please compare a buildable option with an assembled one. Use US suppliers and USD."
)
SECOND = (
    "Let's go with the open platform. Design the pipetting workstation for "
    "microcentrifuge tubes, with a source rack, a sample rack, a tip rack and "
    "a tip waste bin. Start with pipetting only."
)
OUTPUT = Path(os.environ.get(
    "FRESH_PLATFORM_BROWSER_OUTPUT", str(harness.ROOT / ".local/fresh-platform-20261102/browser")
))


def serve():
    import browser_foundation_server as foundation
    import uvicorn

    import app.api as api
    from app.engineering import EngineeringOption, EngineeringRequirement, EngineeringUpdate
    from app.model_client import ChatAction, ExtractedTurn

    async def chat(project, message, history, **kwargs):
        if message == FIRST:
            return ExtractedTurn(
                assistant_message=(
                    "Compare Jubilee, a buildable open platform requiring assembly and "
                    "pipette integration, with the assembled OT-2, requiring compatible "
                    "instruments and an official quote. Which platform would you prefer?"
                ),
                workflow_kind="liquid_preparation",
                source_workflow_kind="prepare dilutions and aliquots by hand",
                equipment="1.5 mL microcentrifuge tubes",
                source_equipment="1.5 mL microcentrifuge tubes",
                workspace_width_mm=800.0,
                source_workspace_width_mm="800 mm of bench width",
                brief_constraints="Use US suppliers and USD.",
                source_brief_constraints="Use US suppliers and USD.",
                engineering=EngineeringUpdate(
                    requirements=[EngineeringRequirement(
                        field="assembly", value="comfortable assembling open hardware",
                        source="comfortable assembling open hardware",
                    )],
                    options=[
                        EngineeringOption(platform_id="jubilee", reason="Build and customize.",
                                          tradeoffs=["Assembly and tool integration required."]),
                        EngineeringOption(platform_id="opentrons-ot2", reason="Buy assembled.",
                                          tradeoffs=["Compatible instruments and quote required."]),
                    ],
                ),
            ), {}
        if message == SECOND:
            # Reproduce the extractor's field-format error: its platform is
            # correct, but the brand is not a literal span in the latest message.
            turn = ExtractedTurn(
                assistant_message="Developing the selected open platform for pipetting only.",
                engineering=EngineeringUpdate(
                    platform_choice="jubilee", choice_source="Jubilee",
                ),
                actions=[ChatAction(
                    kind="develop_layout", source="Design the pipetting workstation"
                )],
            )
            # The real generate_turn performs this boundary repair after parsing.
            turn.engineering.normalize_choice_source(message, project)
            return turn, {}
        raise ValueError("Only the two exact fresh-platform browser inputs are supported.")

    args = foundation.baseline.parse_args()
    api.generate_turn = chat
    foundation.agent.propose_layout = foundation.layout
    uvicorn.run(api.app, host="127.0.0.1", port=args.port, log_level="warning")


def run(url):
    from playwright.sync_api import expect, sync_playwright

    OUTPUT.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            for recover in (False, True):
                context = browser.new_context(
                    viewport={"width": 1440, "height": 1000}, reduced_motion="reduce"
                )
                assert context.storage_state() == {"cookies": [], "origins": []}
                page = context.new_page()
                errors, external, assets = [], [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("response", lambda response: assets.append(response.url)
                        if response.ok and ".glb" in response.url else None)

                def route_network(route):
                    if urlparse(route.request.url).hostname not in ("127.0.0.1", "localhost"):
                        external.append(route.request.url)
                        route.abort()
                    else:
                        route.continue_()

                context.route("**/*", route_network)
                page.route("**/cost-estimate*", lambda route: route.fulfill(
                    json={"estimate": None, "state": "not_estimated"}
                ))
                page.route("**/procurement/refresh*", lambda route: route.abort())
                page.goto(url, wait_until="networkidle")
                expect(page.get_by_text("Workspace ready")).to_be_visible()
                expect(page.locator("canvas")).to_have_count(0)
                composer = page.get_by_label("Describe your workflow or request a change")

                def send(message):
                    expect(composer).to_be_enabled()
                    composer.fill(message)
                    with page.expect_response(
                        lambda response: response.url.endswith("/messages")
                    ) as response:
                        page.get_by_role("button", name="Send message", exact=True).click()
                    expect(composer).to_be_enabled()
                    return response.value

                compared = send(FIRST)
                assert compared.ok, compared.text()
                proposed = compared.json()["project"]
                assert proposed["summary"]["workspace_width_mm"] == 800
                assert proposed["engineering"]["selected_platform_id"] is None
                assert {item["platform_id"] for item in proposed["engineering"]["options"]} == {
                    "jubilee", "opentrons-ot2"
                }
                expect(page.locator("canvas")).to_have_count(0)
                expect(page.get_by_text(
                    "Which platform would you prefer?", exact=False
                )).to_be_visible()
                if recover:
                    page.route("**/messages", lambda route: route.fulfill(
                        status=502, json={"detail": "Synthetic provider failure; project kept."}
                    ), times=1)
                    failed = send(SECOND)
                    assert failed.status == 502
                    expect(page.get_by_role("alert")).to_contain_text("project kept")
                    expect(composer).to_have_value(SECOND)
                    expect(page.locator("canvas")).to_have_count(0)
                    retained_response = page.request.get(
                        url + "api/projects/" + proposed["id"] + "/snapshot",
                        params={"revision": proposed["revision"]},
                    )
                    assert retained_response.ok, retained_response.text()
                    retained = retained_response.json()
                    assert retained["engineering"] == proposed["engineering"]

                selected = send(SECOND)
                assert selected.ok, selected.text()
                data = selected.json()
                project = data["project"]
                assert project["engineering"]["selected_platform_id"] == "jubilee"
                assert project["engineering"]["selection_source"] == (
                    "Let's go with the open platform"
                )
                assert project["summary"]["workspace_width_mm"] == 800
                assert project["summary"]["stock_concentration"] is None
                assert project["summary"]["final_volume"] is None
                assert data["action_runs"][0]["status"] == "accepted"
                assert project["design"]["foundation"]["id"] == "jubilee-v2.2.2-c877bd2"
                assert project["design"]["constraint_status"] == "fits"
                assert project["design"]["footprint"]["width_mm"] <= 800
                components = {item["id"] for item in project["design"]["components"]}
                assert {"foundation-jubilee", "source-rack", "sample-rack", "tip-rack",
                        "tip-waste"} <= components
                assert not project.get("inspection_extension")
                assert not project.get("cold_transfer")
                assert not any("inspection" in item or "cold-transfer" in item
                               for item in components)
                expect(page.locator("canvas")).to_have_count(1, timeout=20000)
                expect(page.locator(".scene-loading")).to_have_count(0, timeout=20000)
                expect(page.get_by_role("alert")).to_have_count(0)
                assert any("jubilee-c877bd2-motion-fixed.glb" in asset for asset in assets)
                page.screenshot(path=str(OUTPUT / ("recovered.png" if recover else "fresh.png")))
                assert not external, external
                assert not errors, errors
                results.append({"recovery": recover, "project_id": project["id"],
                                "revision": project["revision"], "components": sorted(components)})
                context.close()
        finally:
            browser.close()
    (OUTPUT / "result.json").write_text(json.dumps({
        "status": "passed", "model_transport": "offline synthetic fixtures", "cases": results,
    }, indent=2) + "\n", encoding="utf-8")
    print("[browser-fresh-platform] Exact fresh English prompts, explicit open choice, "
          "800 mm, source frame/layout, pipetting-only scope and retry recovery passed.")


if __name__ == "__main__":
    if "--port" in sys.argv:
        serve()
    else:
        harness.STUB_SERVER = Path(__file__)
        harness.run_smoke = run
        raise SystemExit(harness.main())
