"""Offline normal-app assembly reader and step-image regressions; no provider calls."""

import base64
import io
import sys
from pathlib import Path

from PIL import Image

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent.parent)]
import browser_smoke as harness  # noqa: E402

buffer = io.BytesIO()
Image.new("RGB", (64, 64), "#d9ede9").save(buffer, format="PNG")
PNG = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def run(url):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        requests, errors, pending = [], [], []
        state = {"mode": "failure"}
        page.on("pageerror", lambda error: errors.append(str(error)))

        def models(route):
            route.fulfill(
                json={
                    "models": [
                        {
                            "id": "muse-spark-1.3-contributor",
                            "label": "Muse Spark",
                            "available": True,
                        }
                    ],
                    "active_model": "muse-spark-1.3-contributor",
                    "default_model": "muse-spark-1.3-contributor",
                    "capabilities": {
                        "image": {"available": True, "model": "offline-image-fixture"},
                        "voice": {"available": False, "model": "", "max_duration_seconds": 60},
                    },
                }
            )

        def image(route):
            data = route.request.post_data_json
            requests.append(data)
            if state["mode"] == "failure":
                route.fulfill(
                    status=503, json={"detail": "Synthetic provider unavailable. Try again."}
                )
                return
            result = {
                "project_id": route.request.url.split("/projects/")[1].split("/")[0],
                "project_revision": data["project_revision"],
                "step_id": data["step_id"],
                "model": "offline-image-fixture",
                "image_data_url": PNG,
            }
            if state["mode"] == "stale":
                result["project_revision"] -= 1
            if state["mode"] == "missing":
                del result["image_data_url"]
            if state["mode"] == "render-failure":
                result["image_data_url"] = "data:image/png;base64,aW52YWxpZA=="
            if state["mode"] == "pending":
                pending.append((route, result))
                return
            route.fulfill(json=result)

        page.route("**/api/models?*", models)
        page.route("**/instructions/illustration", image)
        try:
            page.goto(url)
            page.wait_for_load_state("networkidle")
            harness.send_chat(
                page,
                "I keep making dilutions manually and want to automate pipetting.",
                "Which equipment",
            )
            harness.send_chat(page, "I have a pipette and microcentrifuge tubes.", "What volumes")
            project = harness.develop_layout(page)["project"]
            page.get_by_role("navigation", name="Project workspace").get_by_role(
                "button", name="Assembly", exact=True
            ).click()
            reader = page.get_by_role("region", name="Assembly steps")
            expect(reader).to_be_visible()
            assert requests == [], "Reading a step must never generate an image"
            reader.get_by_role("button", name="Next assembly step").click()
            reader.get_by_role("button", name="Illustrate this step", exact=True).click()
            expect(reader.get_by_role("alert")).to_contain_text("Synthetic provider unavailable")
            assert requests[-1]["step_id"] == "assembly-2"
            state["mode"] = "stale"
            reader.get_by_role("button", name="Try illustration again").click()
            expect(reader.get_by_role("alert")).to_contain_text("another step or revision")
            state["mode"] = "missing"
            reader.get_by_role("button", name="Try illustration again").click()
            expect(reader.get_by_role("alert")).to_contain_text("image is missing")
            state["mode"] = "render-failure"
            reader.get_by_role("button", name="Try illustration again").click()
            expect(reader.get_by_role("alert")).to_contain_text("could not be displayed")
            state["mode"] = "success"
            reader.get_by_role("button", name="Try illustration again").click()
            enlarge = reader.get_by_role("button", name="Enlarge illustration:", exact=False)
            expect(enlarge).to_be_visible()
            enlarge.click()
            expect(page.get_by_role("dialog")).to_be_visible()
            page.keyboard.press("Escape")
            expect(page.get_by_role("dialog")).not_to_be_visible()
            expect(enlarge).to_be_focused()
            reader.get_by_role("button", name="Previous assembly step").click()
            expect(
                reader.get_by_role("button", name="Illustrate this step", exact=True)
            ).to_be_visible()
            expect(reader.locator("img")).to_have_count(0)
            reader.get_by_role("button", name="Next assembly step").click()
            expect(
                reader.get_by_role("button", name="Enlarge illustration:", exact=False)
            ).to_be_visible()
            assert len(requests) == 5, "Returning to a step must reuse the image"
            nav = page.get_by_role("navigation", name="Project workspace")
            nav.get_by_role("button", name="3D design", exact=True).click()
            nav.get_by_role("button", name="Assembly", exact=True).click()
            reader.get_by_role("button", name="Next assembly step").click()
            expect(
                reader.get_by_role("button", name="Enlarge illustration:", exact=False)
            ).to_be_visible()
            assert len(requests) == 5, "Tab navigation must preserve the active revision image"
            reader.get_by_role("button", name="Next assembly step").click()
            state["mode"] = "pending"
            reader.get_by_role("button", name="Illustrate this step", exact=True).click()
            expect(reader.get_by_role("status")).to_contain_text("Generating an illustration")
            reader.get_by_role("button", name="Previous assembly step").click()
            reader.get_by_role("button", name="Next assembly step").click()
            expect(reader.get_by_role("status")).to_contain_text("Generating an illustration")
            assert len(requests) == 6, "Step navigation must preserve the in-flight request"
            route, result = pending.pop()
            route.fulfill(json=result)
            expect(
                reader.get_by_role("button", name="Enlarge illustration:", exact=False)
            ).to_be_visible()
            # Switch to a separate synthetic general-equipment revision in the same app.
            from test_concept_design import proposal

            from app.concept_design import compile_concept

            project["concept_design"] = compile_concept(proposal(), 200)
            project["revision"] += 1
            page.route(
                "**/messages",
                lambda route: route.fulfill(
                    json={
                        "project": project,
                        "assistant_message": "Synthetic general equipment ready.",
                    }
                ),
            )
            harness.send_chat(
                page, "Open the synthetic optical carousel.", "Synthetic general equipment ready."
            )
            nav.get_by_role("button", name="3D design", exact=True).click()
            step = page.locator(".concept-steps li").first
            expect(step.locator("img")).to_have_count(0)
            state["mode"] = "success"
            step.get_by_role("button", name="Illustrate this step", exact=True).click()
            expect(
                step.get_by_role("button", name="Enlarge illustration:", exact=False)
            ).to_be_visible()
            assert requests[-1]["step_id"] == "concept-step-1"
            assert requests[-1]["project_revision"] == project["revision"]
            component = page.locator(".concept-parts li").first
            component.get_by_role("button", name="Illustrate this step", exact=True).click()
            expect(
                component.get_by_role("button", name="Enlarge illustration:", exact=False)
            ).to_be_visible()
            assert requests[-1]["step_id"] == "concept-turntable"
            assert not errors, errors
            print(
                "[browser-assembly-images] Step selection, explicit calls, failure/retry, "
                "stale/missing image guards and accessible zoom passed."
            )
        finally:
            browser.close()


if __name__ == "__main__":
    harness.run_smoke = run
    raise SystemExit(harness.main())
