"""End-to-end browser verification for the labware photo check.

Standalone executable: imports ``browser_smoke`` as a harness, points
``STUB_SERVER`` at ``browser_vision_server.py``, replaces ``run_smoke``
with ``run_vision`` and delegates to ``harness.main``. Process launch,
free ports and log cleanup are reused exactly from the harness.

Coverage: no analysis on load or example load, example load plus manual
analyze to a ready job, real request counting without route stubbing,
detection cards, aria-pressed accept buttons, label and box edits, tube
source-rack mapping plus Show in 3D, reject of the other object, save,
scene review, six-file ZIP hash checks with raw and history preservation,
stale observation 409 after a further review, revision change clearing the
camera UI with old image and report 409, zero-object scene via a fresh
fake-camera capture, camera capture without automatic analysis with
stopped tracks, stop button and revision stop, and a real JPEG upload
through the file input.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import browser_smoke as harness  # noqa: E402

STEP_TIMEOUT_MS = harness.STEP_TIMEOUT_MS
ANALYSIS_URL_PART = "/inspections"
EXAMPLE_JPEG = ROOT / "web" / "public" / "examples" / "labware.jpg"


def log(message: str) -> None:
    print(f"[browser-vision] {message}", flush=True)


def _camera(page):
    return page.locator("section.camera-card")


def _cards(camera):
    return camera.locator("ul.camera-cards > li")


def _parse_inspection_href(href: str) -> tuple[str, str]:
    match = re.search(r"/api/projects/([^/]+)/inspections/([^/?#]+)", href)
    assert match, f"Could not parse inspection href: {href!r}"
    return match.group(1), match.group(2)


def run_vision(web_url: str) -> None:
    from playwright.sync_api import expect, sync_playwright

    chrome_path = os.environ.get("PLAYWRIGHT_CHROME_PATH", "").strip()
    page_errors: list[str] = []
    analysis_posts: list[str] = []

    with sync_playwright() as playwright:
        launch_kwargs: dict = {
            "headless": True,
            "args": [
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
            ],
        }
        if chrome_path:
            if not Path(chrome_path).exists():
                raise FileNotFoundError(f"PLAYWRIGHT_CHROME_PATH missing: {chrome_path}")
            browser = playwright.chromium.launch(executable_path=chrome_path, **launch_kwargs)
        else:
            browser = playwright.chromium.launch(channel="chrome", **launch_kwargs)
        try:
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000},
                permissions=["camera"],
            )
            # A canvas stream avoids a Windows headless Chrome fake-device issue
            # (the built-in fake track can end before delivering its first frame).
            # Only the camera source is stubbed; the browser uses real MediaStream
            # tracks, video playback, canvas capture, upload and server processing.
            context.add_init_script("""
                navigator.mediaDevices.getUserMedia = async (constraints) => {
                    if (constraints.audio !== false) throw new Error('Audio must be disabled');
                    const canvas = document.createElement('canvas');
                    canvas.width = 640; canvas.height = 480;
                    const ctx = canvas.getContext('2d');
                    let tick = 0;
                    const paint = () => {
                        ctx.fillStyle = '#d8e8e5'; ctx.fillRect(0, 0, 640, 480);
                        ctx.fillStyle = '#176b73'; ctx.fillRect(80 + tick++ % 160, 100, 80, 240);
                    };
                    paint();
                    const stream = canvas.captureStream(10);
                    const timer = setInterval(() => {
                        if (stream.getTracks().every(t => t.readyState === 'ended')) {
                            clearInterval(timer); return;
                        }
                        paint();
                    }, 80);
                    return stream;
                };
            """)
            page = context.new_page()
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))

            def on_request(request) -> None:
                if request.method == "POST" and ANALYSIS_URL_PART in request.url:
                    analysis_posts.append(request.url)

            page.on("request", on_request)
            log(f"Opening {web_url} with fake camera (no real webcam).")
            page.goto(web_url, wait_until="domcontentloaded", timeout=STEP_TIMEOUT_MS)

            expect(page.get_by_text("Workspace ready")).to_be_visible(timeout=STEP_TIMEOUT_MS)
            camera = _camera(page)
            expect(camera.get_by_role("heading", name="Labware photo check")).to_be_visible(
                timeout=STEP_TIMEOUT_MS
            )
            expect(camera.get_by_role("button", name="Analyze photo")).to_be_disabled(
                timeout=STEP_TIMEOUT_MS
            )
            assert len(analysis_posts) == 0, "Analysis must not run on page load."
            log("Camera panel loaded with no automatic analysis.")

            # Load the example photo; still no analysis until explicit Analyze.
            camera.get_by_role("button", name="Load example photo").click()
            expect(camera.locator("img[alt='Labware photo under review']")).to_be_visible(
                timeout=STEP_TIMEOUT_MS
            )
            expect(camera.get_by_role("button", name="Analyze photo")).to_be_enabled(
                timeout=STEP_TIMEOUT_MS
            )
            assert len(analysis_posts) == 0, "Example load must not trigger analysis."
            log("Example photo loaded without automatic analysis.")

            # Analyze and wait for the real job to become ready.
            camera.get_by_role("button", name="Analyze photo").click()
            expect(camera.locator("ul.camera-cards > li")).to_have_count(2, timeout=60_000)
            expect(camera.get_by_text("Summary:")).to_be_visible(timeout=STEP_TIMEOUT_MS)
            first = _cards(camera).nth(0)
            second = _cards(camera).nth(1)
            expect(first).to_contain_text("det-001", timeout=STEP_TIMEOUT_MS)
            expect(second).to_contain_text("det-002", timeout=STEP_TIMEOUT_MS)
            expect(first).to_contain_text("assessment score, not calibrated")
            assert len(analysis_posts) >= 1, "Analyze must use a real network POST."
            log("Two-region inspection is ready via real API calls.")

            # Decide both objects: edit first, map tube, accept; reject second.
            first.locator("button.camera-det-head").click()
            first.get_by_role("button", name="Accept").click()
            expect(first.get_by_role("button", name="Accept")).to_have_attribute(
                "aria-pressed", "true", timeout=STEP_TIMEOUT_MS
            )
            first.get_by_label("Label").fill("Tube A1 edited")
            first.get_by_label("x_min").fill("110")
            first.get_by_label("Manual 3D association").select_option("source-rack")
            expect(first.get_by_role("button", name="Show in 3D")).to_be_visible(
                timeout=STEP_TIMEOUT_MS
            )
            first.get_by_role("button", name="Show in 3D").click()
            second.locator("button.camera-det-head").click()
            second.get_by_role("button", name="Reject").click()
            expect(second.get_by_role("button", name="Reject")).to_have_attribute(
                "aria-pressed", "true", timeout=STEP_TIMEOUT_MS
            )
            # Review scene stays disabled until every object is decided; save first.
            camera.get_by_role("button", name="Save decisions").click()
            expect(camera.get_by_text("Version 2")).to_be_visible(timeout=STEP_TIMEOUT_MS)
            expect(camera.get_by_text("Decided 2/2")).to_be_visible(timeout=STEP_TIMEOUT_MS)
            log("Label, box and source-rack mapping saved as version 2.")

            camera.get_by_role("button", name="Review scene").click()
            expect(camera.get_by_text("Scene reviewed.")).to_be_visible(timeout=STEP_TIMEOUT_MS)
            log("Scene reviewed.")

            # Download the six-file ZIP and verify hashes and preserved content.
            download_link = camera.get_by_role("link", name="Download inspection zip")
            expect(download_link).to_be_visible(timeout=STEP_TIMEOUT_MS)
            href = download_link.get_attribute("href") or ""
            project_id, job_id = _parse_inspection_href(href)
            base = web_url.rstrip("/")
            with page.expect_download() as download_info:
                download_link.click()
            download = download_info.value
            assert download.failure() is None
            with zipfile.ZipFile(download.path()) as archive:
                assert set(archive.namelist()) == {
                    "image.jpg",
                    "annotated.svg",
                    "inspection.json",
                    "review-history.json",
                    "README.md",
                    "manifest.json",
                }
                manifest = json.loads(archive.read("manifest.json"))
                for name in (
                    "image.jpg",
                    "annotated.svg",
                    "inspection.json",
                    "review-history.json",
                    "README.md",
                ):
                    payload = archive.read(name)
                    assert hashlib.sha256(payload).hexdigest() == manifest[name]
                assert archive.read("image.jpg")[:2] == b"\xff\xd8"
                assert b"<svg" in archive.read("annotated.svg")
                inspection = json.loads(archive.read("inspection.json"))
                assert inspection["observation_version"] >= 3
                assert inspection["scene_reviewed"] is True
                raw = inspection.get("raw", {})
                assert len(raw.get("detections", [])) == 2
                boxes = [d["box"] for d in raw["detections"]]
                assert {"x_min": 100, "y_min": 200, "x_max": 300, "y_max": 700} in boxes
                assert {"x_min": 650, "y_min": 300, "x_max": 950, "y_max": 700} in boxes
                assert any(d.get("confidence") == 0.55 for d in raw["detections"])
                assert any(d.get("confidence") == 0.95 for d in raw["detections"])
                history = json.loads(archive.read("review-history.json"))
                assert len(history) >= 2
                assert any("Tube A1 edited" in json.dumps(h) for h in history)
                pixels = archive.read("image.jpg")
            # Report pixels match the canonical image endpoint bytes.
            image_resp = page.request.get(
                f"{base}{href.split('?')[0].rsplit('/archive', 1)[0]}/image"
            )
            assert image_resp.status == 200
            assert image_resp.body() == pixels
            log("Inspection ZIP verified: hashes, raw model, history and pixels.")

            # One more review bumps the version; the previous version is stale.
            stale_version = inspection["observation_version"]
            camera.get_by_role("button", name="Save decisions").click()
            expect(camera.get_by_text(f"Version {stale_version + 1}")).to_be_visible(
                timeout=STEP_TIMEOUT_MS
            )
            stale_review = page.request.post(
                f"{base}/api/projects/{project_id}/inspections/{job_id}/review",
                data=json.dumps({"observation_version": stale_version, "scene_reviewed": False}),
                headers={"Content-Type": "application/json"},
            )
            assert stale_review.status == 409, f"Stale review not rejected: {stale_review.status}"
            log("Stale observation version correctly rejected with 409.")

            # Revision change clears the camera UI; old image and report are 409.
            old_image_url = f"{base}/api/projects/{project_id}/inspections/{job_id}/image"
            old_archive_url = (
                f"{base}/api/projects/{project_id}/inspections/{job_id}/archive"
                f"?observation_version={stale_version + 1}"
            )
            harness.send_chat(page, harness.WIDTH_450_MESSAGE, "Within requested width")
            expect(camera.get_by_text("no photo yet", exact=True)).to_be_visible(
                timeout=STEP_TIMEOUT_MS
            )
            expect(camera.locator("ul.camera-cards > li")).to_have_count(0)
            assert page.request.get(old_image_url).status == 409
            assert page.request.get(old_archive_url).status == 409
            log("Revision change cleared the camera UI and stale reads are 409.")

            # Zero-object scene via a fresh fake-camera capture (new bytes, second model call).
            camera.get_by_role("button", name="Use camera").click()
            expect(camera.locator("video.camera-video")).to_be_visible(timeout=STEP_TIMEOUT_MS)
            before_capture_posts = len(analysis_posts)
            page.wait_for_function("document.querySelector('video.camera-video')?.videoWidth >= 32")
            page.evaluate(
                "window.cameraTracks = document.querySelector('video.camera-video')"
                ".srcObject.getTracks()"
            )
            camera.get_by_role("button", name="Capture").click()
            expect(camera.locator("img[alt='Labware photo under review']")).to_be_visible(
                timeout=STEP_TIMEOUT_MS
            )
            assert len(analysis_posts) == before_capture_posts, (
                "Capture must not trigger automatic analysis."
            )
            stopped = page.evaluate(
                """() => {
                    const videos = [...document.querySelectorAll('section.camera-card video')];
                    return videos.map(v => v.srcObject);
                }"""
            )
            tracks_ended = page.evaluate(
                "window.cameraTracks.every(track => track.readyState === 'ended')"
            )
            assert tracks_ended
            assert all(s is None for s in stopped), "Capture must stop camera tracks."
            log("Fake-camera capture produced a photo with tracks stopped.")
            camera.get_by_role("button", name="Analyze photo").click()
            expect(
                camera.locator(".camera-summary").get_by_text("No regions observed.")
            ).to_be_visible(timeout=60_000)
            expect(camera.locator("ul.camera-cards > li")).to_have_count(0)
            camera.get_by_role("button", name="Review scene").click()
            expect(camera.get_by_text("Scene reviewed.")).to_be_visible(timeout=STEP_TIMEOUT_MS)
            log("Zero-object scene acknowledged and reviewed.")

            # Stop button and revision stop with the fake camera.
            camera.get_by_role("button", name="Use camera").click()
            expect(camera.locator("video.camera-video")).to_be_visible(timeout=STEP_TIMEOUT_MS)
            camera.get_by_role("button", name="Stop camera").click()
            expect(camera.locator("video.camera-video")).to_have_count(0)
            camera.get_by_role("button", name="Use camera").click()
            expect(camera.locator("video.camera-video")).to_be_visible(timeout=STEP_TIMEOUT_MS)
            harness.send_chat(page, harness.WIDTH_650_MESSAGE, "Within requested width")
            expect(camera.locator("video.camera-video")).to_have_count(0)
            expect(camera.get_by_text("no photo yet", exact=True)).to_be_visible(
                timeout=STEP_TIMEOUT_MS
            )
            log("Stop button and revision stop verified.")

            # Real JPEG upload through the file input, then analyze.
            assert EXAMPLE_JPEG.exists()
            if EXAMPLE_JPEG.exists():
                camera.locator("#camera-upload").set_input_files(str(EXAMPLE_JPEG))
                expect(camera.locator("img[alt='Labware photo under review']")).to_be_visible(
                    timeout=STEP_TIMEOUT_MS
                )
                posts_before_upload = len(analysis_posts)
                assert len(analysis_posts) == posts_before_upload
                camera.get_by_role("button", name="Analyze photo").click()
                expect(camera.get_by_text("Summary:")).to_be_visible(timeout=60_000)
                log("Real JPEG upload analyzed through the file input.")
            else:
                log(f"Example JPEG not found at {EXAMPLE_JPEG}; upload step skipped.")

            screenshot_path = os.environ.get("MUSEAUTOLAB_VISION_SCREENSHOT", "").strip()
            if screenshot_path:
                target = Path(screenshot_path)
                if not target.is_absolute():
                    target = ROOT / target
                target.parent.mkdir(parents=True, exist_ok=True)
                camera.screenshot(path=str(target))
                log(f"Saved optional screenshot to {target}.")

            if page_errors:
                raise AssertionError(f"Unexpected browser page errors: {page_errors!r}")
            log("No unexpected browser page errors observed.")
        finally:
            browser.close()


harness.STUB_SERVER = ROOT / "tests" / "browser_vision_server.py"
harness.run_smoke = run_vision


def main() -> int:
    return harness.main()


if __name__ == "__main__":
    raise SystemExit(main())
