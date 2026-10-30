"""Offline export UI states; real application/compiler, fixture export responses.

No CAD job or Meta request is sent. Checks costly-job reconnection, route scope,
sandboxed HTML guide access and revision reset.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import browser_smoke as harness  # noqa: E402

from app.assembly import build_document_files  # noqa: E402


def run(url):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        try:
            for route_name in ("open-source buildable", "prebuilt"):
                page.goto(url)
                page.wait_for_load_state("networkidle")
                page.get_by_role("button", name="New project", exact=True).click()
                harness.send_chat(
                    page,
                    "I keep making dilutions manually and want to automate pipetting.",
                    "Which equipment",
                )
                harness.send_chat(
                    page, "I have a pipette and microcentrifuge tubes.", "What volumes"
                )
                harness.send_chat(
                    page, "Help me compare the platform options.", "assembled platform"
                )
                harness.send_chat(page, f"I prefer the {route_name} one.", "Developing")
                harness.send_chat(page, harness.COMPLETE_TASK_MESSAGE, harness.EXPECTED_STOCK)
                page.locator("details.prep-plan > summary").click()
                with page.expect_response(lambda r: r.url.endswith("/confirm")) as confirmed:
                    page.get_by_role("button", name="Confirm design").click()
                project = confirmed.value.json()["project"]
                guide_html = build_document_files(project)["assembly-guide.html"].decode()
                if route_name == "prebuilt":
                    assert "assignments of three labware proxies" in guide_html
                    assert "five component positions" not in guide_html
                else:
                    assert "original source frame remains fixed" in guide_html
                guide_html = guide_html.replace(
                    "</body>", "<script>window.parent.guideScriptRan=true</script></body>"
                )
                harness.send_chat(page, "Show project files.", "Checking")
                card = page.locator(".files-card")
                expect(card).to_contain_text("Physics and hardware control are unavailable")
                expect(card).not_to_contain_text("physics report")
                if route_name == "prebuilt":
                    expect(card).to_contain_text("Schematic CAD, setup guide")
                posts, polls = [], []
                job = {
                    "id": "offline-export",
                    "project_id": project["id"],
                    "revision": project["revision"],
                    "status": "running",
                    "stage": "simulation",
                    "completed_stages": 2,
                    "total_stages": 4,
                    "error": None,
                    "files": [],
                    "assembly_steps": [],
                    "download_url": None,
                }

                def exports(request_route):
                    request = request_route.request
                    if request.method == "POST":
                        posts.append(request.url)
                        request_route.fulfill(status=202, json=job)
                    elif request.url.endswith("/files/assembly-guide.html"):
                        request_route.fulfill(
                            content_type="text/html",
                            body=guide_html,
                        )
                    else:
                        polls.append(request.url)
                        if len(polls) == 1:
                            request_route.fulfill(
                                status=503, json={"detail": "Offline status interruption"}
                            )
                        else:
                            request_route.fulfill(
                                json={
                                    **job,
                                    "status": "ready",
                                    "stage": "archive",
                                    "completed_stages": 4,
                                    "files": [{"name": "assembly-guide.html", "size": 200}],
                                }
                            )

                page.route("**/exports**", exports)
                page.get_by_role("button", name="Generate project files", exact=True).click()
                expect(card).to_contain_text("Recording simulation scope")
                expect(card).not_to_contain_text("Running physics")
                page.get_by_role("button", name="Reconnect to generation").click(timeout=10000)
                expect(page.get_by_role("link", name="Download project ZIP")).to_be_visible(
                    timeout=10000
                )
                assert len(posts) == 1, "Reconnection restarted an expensive export"
                assert len(polls) == 2
                assert not page.locator(".files-card iframe").count()
                viewer = page.locator(".viewer-shell")
                expect(viewer).to_have_css("position", "sticky")
                page.get_by_role("button", name="Read project guide").click()
                iframe = page.locator(".files-card iframe")
                expect(iframe).to_have_attribute("sandbox", "")
                expect(viewer).to_have_css("position", "relative")
                for target in (
                    card.get_by_role("heading", name="Project files", exact=True),
                    page.get_by_role("button", name="Close guide", exact=True),
                    iframe,
                ):
                    target.scroll_into_view_if_needed()
                    viewer_box, target_box = viewer.bounding_box(), target.bounding_box()
                    assert viewer_box and target_box
                    assert viewer_box["y"] + viewer_box["height"] <= target_box["y"] + 1
                expect(
                    page.frame_locator(".files-card iframe").get_by_role(
                        "heading",
                        name=(
                            "Instrument purchase and setup guide"
                            if route_name == "prebuilt"
                            else "Concept assembly guide"
                        ),
                    )
                ).to_be_visible()
                expect(
                    page.frame_locator(".files-card iframe").locator("svg").first
                ).to_be_visible()
                assert not page.evaluate("Boolean(window.guideScriptRan)")
                page.set_viewport_size({"width": 390, "height": 844})
                dimensions = (
                    page.frame_locator(".files-card iframe")
                    .locator("html")
                    .evaluate(
                        "element => ({width: element.scrollWidth, viewport: window.innerWidth})"
                    )
                )
                assert dimensions["width"] <= dimensions["viewport"], dimensions
                table = page.frame_locator(".files-card iframe").get_by_role(
                    "region", name="Component dimensions"
                )
                expect(table).to_have_attribute("tabindex", "0")
                assert table.evaluate("el => el.scrollWidth > el.clientWidth")
                page.set_viewport_size({"width": 1440, "height": 1000})
                page.get_by_role("button", name="Close guide").click()
                expect(iframe).to_have_count(0)
                expect(viewer).to_have_css("position", "sticky")
                page.get_by_role("button", name="Read project guide").click()
                expect(iframe).to_have_count(1)
                # A project change must discard both the old guide and old files.
                page.get_by_role("button", name="New project", exact=True).click()
                expect(page.locator(".files-card")).to_have_count(0)
                page.unroute("**/exports**", exports)
            print(
                "[browser-project-files] Both digital routes: truthful scope, one export POST "
                "after reconnect, explicit sandboxed guide and project reset passed "
                "(offline fixtures)."
            )
        finally:
            browser.close()


if __name__ == "__main__":
    harness.run_smoke = run
    raise SystemExit(harness.main())
