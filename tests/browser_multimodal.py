"""Offline multimodal controls with synthetic sine-wave microphone audio.

Real UI, browser AudioWorklet and backend project lifecycle. Model catalogue,
selection, transcription and chat transport are explicit fixtures: no provider
request or private audio. This checks interaction, PCM format and stale guards;
it does not establish Muse Voice transcription quality.
"""

import base64
import io
import json
import struct
import sys
from pathlib import Path

from PIL import Image

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent.parent)]
import browser_smoke as harness  # noqa: E402

SYNTHETIC_MIC = """
window.syntheticMicCalls = 0;
window.syntheticTrackStops = 0;
window.syntheticMicMode = 'normal';
window.createSyntheticStream = async () => {
  const context = new AudioContext();
  await context.resume();
  const oscillator = context.createOscillator();
  oscillator.frequency.value = 440;
  const destination = context.createMediaStreamDestination();
  oscillator.connect(destination); oscillator.start();
  const stream = destination.stream;
  stream.getTracks().forEach(track => {
    const stop = track.stop.bind(track);
    track.stop = () => { window.syntheticTrackStops++; stop();
      if (context.state !== 'closed') void context.close(); };
  });
  return stream;
};
navigator.mediaDevices.getUserMedia = async () => {
  window.syntheticMicCalls++;
  if (window.syntheticMicMode === 'denied') {
    throw new DOMException('Synthetic denial', 'NotAllowedError');
  }
  if (window.syntheticMicMode === 'pending') return await new Promise(resolve => {
    window.grantSyntheticMic = async () => resolve(await window.createSyntheticStream());
  });
  return await window.createSyntheticStream();
};
"""


def run(url):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
        page.add_init_script(SYNTHETIC_MIC)
        project = {}
        model_calls, transcripts, messages, pending = [], [], [], []
        image_requests, pending_images = [], []
        image_mode = "failure"
        active_model = "muse-spark-1.3-contributor"
        transcription_mode = "success"
        catalogue_available = True
        browser_errors = []
        page.on("pageerror", lambda error: browser_errors.append(str(error)))

        def catalogue(route):
            route.fulfill(
                json={
                    "models": [
                        {
                            "id": "muse-spark-1.3-contributor",
                            "label": "Muse Spark Contributor",
                            "available": catalogue_available,
                        },
                        {
                            "id": "muse-wonder-1.0",
                            "label": "Muse Wonder",
                            "available": catalogue_available,
                        },
                        {
                            "id": "unavailable-model",
                            "label": "Unavailable model",
                            "available": False,
                        },
                    ],
                    "default_model": "muse-spark-1.3-contributor",
                    "active_model": active_model,
                    "capabilities": {
                        "voice": {
                            "available": True,
                            "model": "muse-voice",
                            "max_duration_seconds": 60,
                        },
                        "image": {"available": True, "model": "muse-image"},
                    },
                }
            )

        def choose(route):
            nonlocal active_model
            model_calls.append(route.request.post_data_json)
            if len(model_calls) == 2:
                route.fulfill(
                    status=503, json={"detail": "Synthetic selection failure. Try again."}
                )
                return
            active_model = route.request.post_data_json["model"]
            route.fulfill(json={"project": project, "active_model": active_model})

        def transcribe(route):
            data = route.request.post_data_buffer
            assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"
            assert struct.unpack_from("<HHI", data, 20) == (1, 1, 16000)
            assert struct.unpack_from("<H", data, 34)[0] == 16
            assert 44 < len(data) <= 44 + 60 * 16000 * 2
            assert route.request.headers["content-type"] == "audio/wav"
            transcripts.append(len(data))
            if transcription_mode == "pending":
                pending.append(route)
            elif transcription_mode == "failure":
                route.fulfill(
                    status=502,
                    json={"detail": "Synthetic transcription failure. Record again or type."},
                )
            else:
                route.fulfill(
                    json={
                        "text": "Synthetic editable transcript.",
                        "model": "muse-voice",
                        "request_id": "offline-only",
                    }
                )

        def illustration(route):
            payload = route.request.post_data_json
            raw = base64.b64decode(payload["reference_image_data_url"].split(",", 1)[1])
            with Image.open(io.BytesIO(raw)) as original:
                assert original.format == "PNG"
                assert min(original.size) >= 32 and max(original.size) <= 2048
            assert isinstance(payload["project_revision"], int)
            image_requests.append(payload)
            if image_mode == "failure":
                route.fulfill(
                    status=502, json={"detail": "Synthetic image failure. Files remain available."}
                )
                return
            result = {
                "image_data_url": payload["reference_image_data_url"],
                "model": "offline-image-fixture",
                "project_id": route.request.url.split("/")[-2],
                "project_revision": payload["project_revision"],
                "reference_sha256": "offline-reference",
                "image_sha256": "offline-image",
            }
            if image_mode == "pending":
                pending_images.append((route, result))
            else:
                route.fulfill(json=result)

        def chat(route):
            messages.append(route.request.post_data_json["message"])
            route.fulfill(
                json={"project": project, "assistant_message": "Offline explicit send received."}
            )

        def observe(response):
            if (
                response.ok
                and response.request.method == "POST"
                and response.url.endswith("/api/projects")
            ):
                project.update(response.json()["project"])

        page.on("response", observe)
        page.route("**/api/models?*", catalogue)
        page.route("**/model", choose)
        page.route("**/api/transcribe", transcribe)
        page.route("**/messages", chat)
        page.route("**/illustration", illustration)
        try:
            page.goto(url)
            page.wait_for_load_state("networkidle")
            model = page.get_by_label("Agent model", exact=True)
            voice = page.get_by_role("button", name="Muse Voice", exact=True)
            composer = page.get_by_label("Describe your workflow or request a change")
            send = page.get_by_role("button", name="Send message")
            expect(voice).to_be_enabled()
            assert page.evaluate("window.syntheticMicCalls") == 0
            model.select_option("muse-wonder-1.0")
            expect(model).to_have_value("muse-wonder-1.0")
            expect(page.locator("#model-data-note")).to_contain_text("not used to train")
            model.select_option("muse-spark-1.3-contributor")
            expect(page.get_by_role("alert")).to_contain_text("Synthetic selection failure")
            expect(model).to_have_value("muse-wonder-1.0")
            model.select_option("muse-spark-1.3-contributor")
            expect(model).to_have_value("muse-spark-1.3-contributor")
            expect(page.locator("#model-data-note")).to_be_visible()
            expect(model.locator('option[value="unavailable-model"]')).to_be_disabled()
            composer.fill("Keep this typed draft.")
            voice.click()
            expect(page.get_by_role("button", name="Stop and transcribe")).to_be_visible()
            expect(send).to_be_disabled()
            composer.press("Enter")
            assert not messages
            page.wait_for_timeout(350)  # Capture actual synthetic browser audio.
            page.get_by_role("button", name="Stop and transcribe").click()
            expect(composer).to_have_value("Keep this typed draft.\nSynthetic editable transcript.")
            assert len(transcripts) == 1 and not messages
            assert page.evaluate("window.syntheticTrackStops") >= 1
            composer.fill("Edited synthetic transcript.")
            send.click()
            expect(page.get_by_text("Offline explicit send received.")).to_be_visible()
            assert messages == ["Edited synthetic transcript."]

            composer.fill("D" * 3990)
            voice.click()
            expect(page.get_by_role("button", name="Stop and transcribe")).to_be_visible()
            page.wait_for_timeout(250)
            page.get_by_role("button", name="Stop and transcribe").click()
            expect(page.get_by_label("Transcript to copy")).to_have_value(
                "Synthetic editable transcript."
            )
            expect(composer).to_have_value("D" * 3990)
            page.get_by_role("button", name="Dismiss transcript").click()
            assert len(transcripts) == 2
            composer.fill("Preserve on cancel.")
            voice.click()
            expect(page.get_by_role("button", name="Stop and transcribe")).to_be_visible()
            page.get_by_role("button", name="Cancel", exact=True).click()
            expect(composer).to_have_value("Preserve on cancel.")
            assert len(transcripts) == 2

            page.evaluate("window.syntheticMicMode = 'pending'")
            voice.click()
            expect(page.get_by_text("Allow microphone access…")).to_be_visible()
            page.get_by_role("button", name="Cancel", exact=True).click()
            page.evaluate("window.grantSyntheticMic()")
            expect(voice).to_be_enabled()
            page.wait_for_timeout(100)
            expect(page.get_by_role("button", name="Stop and transcribe")).to_have_count(0)
            assert len(transcripts) == 2

            page.evaluate("window.syntheticMicMode = 'denied'")
            voice.click()
            expect(page.get_by_role("alert")).to_contain_text("Microphone access is blocked")
            expect(composer).to_have_value("Preserve on cancel.")
            page.evaluate("window.syntheticMicMode = 'normal'")
            transcription_mode = "failure"
            voice.click()
            expect(page.get_by_role("button", name="Stop and transcribe")).to_be_visible()
            page.wait_for_timeout(250)
            page.get_by_role("button", name="Stop and transcribe").click()
            expect(page.get_by_role("alert")).to_contain_text("Synthetic transcription failure")
            expect(composer).to_have_value("Preserve on cancel.")

            # New-project failure preserves the current conversation, draft and browser resume.
            snapshot_before = page.evaluate("localStorage.getItem('museautolab.workspace.v1')")
            messages_before = page.locator(".message-row").count()

            def fail_new(route):
                route.fulfill(status=503, json={"detail": "Synthetic replacement failure."})

            page.route("**/api/projects", fail_new)
            page.get_by_role("button", name="New project", exact=True).click()
            expect(page.get_by_role("alert")).to_contain_text("Your workspace and draft are kept")
            expect(composer).to_have_value("Preserve on cancel.")
            assert page.locator(".message-row").count() == messages_before
            assert (
                page.evaluate("localStorage.getItem('museautolab.workspace.v1')") == snapshot_before
            )
            page.unroute("**/api/projects", fail_new)
            page.get_by_role("button", name="New project", exact=True).click()
            expect(composer).to_have_value("")
            page.get_by_role("button", name="Undo new project").click()
            expect(composer).to_have_value("Preserve on cancel.")
            assert page.locator(".message-row").count() == messages_before

            transcription_mode = "pending"
            voice.click()
            expect(page.get_by_role("button", name="Stop and transcribe")).to_be_visible()
            page.wait_for_timeout(250)
            page.get_by_role("button", name="Stop and transcribe").click()
            expect(page.get_by_text("Transcribing with Muse Voice…")).to_be_visible()
            page.get_by_role("button", name="New project", exact=True).click()
            expect(composer).to_have_value("")
            pending.pop().fulfill(json={"text": "Stale discarded transcript."})
            expect(voice).to_be_enabled()
            expect(composer).to_have_value("")
            expect(page.get_by_text("Stale discarded transcript.")).to_have_count(0)

            voice.click()
            expect(page.get_by_role("button", name="Stop and transcribe")).to_be_visible()
            stops = page.evaluate("window.syntheticTrackStops")
            page.get_by_role("button", name="New project", exact=True).click()
            expect(voice).to_be_enabled()
            assert page.evaluate("window.syntheticTrackStops") > stops
            page.set_viewport_size({"width": 390, "height": 844})
            expect(voice).to_be_visible()
            assert composer.bounding_box()["y"] + composer.bounding_box()["height"] < 844
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(
                path=str(harness.ROOT / ".local/multimodal-20261030/frontend-mobile.png"),
                full_page=True,
            )
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.screenshot(
                path=str(harness.ROOT / ".local/multimodal-20261030/frontend-desktop.png"),
                full_page=True,
            )
            # A successful catalogue with no accessible model explains the next action.
            catalogue_available = False
            page.locator(".model-help > summary").click()
            page.locator(".model-help button").click()
            expect(
                page.get_by_text("No agent model is available for this account.", exact=False)
            ).to_be_visible()
            expect(page.locator(".model-help")).to_contain_text("Check account access")
            catalogue_available = True
            page.locator(".model-help button").click()
            expect(
                page.get_by_text("No agent model is available for this account.", exact=False)
            ).to_have_count(0)
            page.locator(".model-help > summary").click()
            # The confirmed-stage shortcut discovers files without starting generation.
            page.unroute("**/messages", chat)
            harness.send_chat(
                page,
                "I keep making dilutions manually and want to automate pipetting.",
                "Which equipment",
            )
            harness.send_chat(page, "I have a pipette and microcentrifuge tubes.", "What volumes")
            harness.send_chat(page, "Help me compare the platform options.", "assembled platform")
            harness.send_chat(page, "I prefer the prebuilt one.", "Developing")
            harness.send_chat(page, harness.COMPLETE_TASK_MESSAGE, harness.EXPECTED_STOCK)
            assert not page.locator("details.prep-plan").evaluate("el => el.open")
            page.get_by_role("button", name="Review preparation plan", exact=True).click()
            expect(page.locator("details.prep-plan")).to_be_focused()
            page.get_by_role("button", name="Confirm design").click()
            shortcut = page.get_by_role("button", name="Project files", exact=True)
            expect(shortcut).to_be_visible()
            assert not page.locator("details.project-details").evaluate("el => el.open")
            exports = []
            page.on(
                "request",
                lambda request: (
                    exports.append(request.url)
                    if request.method == "POST" and "/exports" in request.url
                    else None
                ),
            )
            shortcut.click()
            expect(page.locator(".project-files-section")).to_be_focused()
            expect(
                page.get_by_role("button", name="Generate project files", exact=True)
            ).to_be_visible()
            assert not exports
            page.set_viewport_size({"width": 390, "height": 844})
            expect(shortcut).to_be_visible()
            page.set_viewport_size({"width": 1440, "height": 1000})
            panel = page.locator(".illustration-panel")
            assert not panel.evaluate("el => el.open")
            assert not image_requests
            panel.locator(":scope > summary").click()
            generate = page.get_by_role("button", name="Generate with Muse Image", exact=True)
            generate.click()
            expect(panel.get_by_role("alert")).to_contain_text("Synthetic image failure")
            assert len(image_requests) == 1
            image_mode = "pending"
            generate.click()
            expect(panel.get_by_text("Generating with Muse Image…", exact=True)).to_be_visible()
            page.get_by_role("button", name="Cancel illustration").click()
            pending_route, pending_result = pending_images.pop()
            pending_route.fulfill(json=pending_result)
            expect(panel.locator(".illustration-result")).to_have_count(0)
            expect(generate).to_be_enabled()
            generate.click()
            expect(panel.get_by_text("Generating with Muse Image…", exact=True)).to_be_visible()
            harness.send_chat(page, "Set target to 20 mg/ml.", "Recorded an impossible target")
            pending_route, pending_result = pending_images.pop()
            pending_route.fulfill(json=pending_result)
            expect(panel.locator(".illustration-result")).to_have_count(0)
            harness.send_chat(page, harness.COMPLETE_TASK_MESSAGE, harness.EXPECTED_STOCK)
            page.get_by_role("button", name="Review preparation plan", exact=True).click()
            page.get_by_role("button", name="Confirm design").click()
            expect(page.locator(".chat-status")).to_have_text("Confirmed")
            expect(page.locator(".viewer-shell")).to_have_css("position", "sticky")
            panel.locator(":scope > summary").click()
            expect(page.locator(".viewer-shell")).to_have_css("position", "relative")
            image_mode = "success"
            generate.click()
            expect(
                panel.get_by_text("AI-generated illustration — not a technical drawing", exact=True)
            ).to_be_visible()
            expect(panel.get_by_role("link", name="Download illustration PNG")).to_have_attribute(
                "download", __import__("re").compile(r"museautolab-illustration-r\d+\.png")
            )
            panel.get_by_text("Compare with original model view", exact=True).click()
            expect(panel.locator(".illustration-reference img")).to_be_visible()
            result_image = panel.locator(".illustration-result img")
            result_image.evaluate(
                "async el => { await el.decode(); "
                "el.scrollIntoView({block: 'center', behavior: 'instant'}); }"
            )
            assert result_image.evaluate(
                "el => { const rect = el.getBoundingClientRect(); "
                "return document.elementFromPoint(rect.x + rect.width / 2, "
                "rect.y + rect.height / 2) === el; }"
            )
            panel.locator(":scope > summary").click()
            expect(page.locator(".viewer-shell")).to_have_css("position", "sticky")
            panel.locator(":scope > summary").click()
            expect(page.locator(".viewer-shell")).to_have_css("position", "relative")
            assert len(image_requests) == 4
            assert not exports
            page.screenshot(
                path=str(harness.ROOT / ".local/multimodal-20261030/frontend-illustration.png"),
                full_page=True,
            )
            page.get_by_role("button", name="New project", exact=True).click()
            expect(panel).to_have_count(0)
            # Public portable state may retain a ready plan with parameters_started=False.
            # Reopening must expose the same review/confirmation section as its shortcut.
            for status in ("confirmed", "draft"):
                portable = json.loads(
                    (harness.ROOT / "docs/examples/demo-video-project.json").read_text(
                        encoding="utf-8"
                    )
                )
                portable["status"] = status
                page.get_by_label("Open saved project").set_input_files(
                    {
                        "name": f"explicit-public-{status}-fixture.json",
                        "mimeType": "application/json",
                        "buffer": json.dumps(portable).encode(),
                    }
                )
                shortcut_name = (
                    "Project files" if status == "confirmed" else "Review preparation plan"
                )
                shortcut = page.get_by_role("button", name=shortcut_name, exact=True)
                expect(shortcut).to_be_visible(timeout=20000)
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth") == 390
                assert shortcut.bounding_box()["x"] + shortcut.bounding_box()["width"] <= 390
                if status == "draft":
                    shortcut.click()
                    expect(page.locator(".prep-plan")).to_be_focused()
                    expect(page.get_by_role("button", name="Confirm design")).to_be_visible()
                    expect(page.get_by_role("button", name="Confirm design")).to_be_enabled()
                page.screenshot(
                    path=str(
                        harness.ROOT / f".local/multimodal-20261030/final-mobile-{status}.png"
                    ),
                    full_page=True,
                )
            assert not browser_errors, browser_errors
            print(
                "[browser-multimodal] Passed actual selector, synthetic PCM capture, "
                "editable append, explicit send, cancel, late permission, denial, provider error, "
                "stale reset, track cleanup, 4,000-character recovery, reset failure/undo, "
                "file discovery, actual illustration capture/error/cancel, "
                "stale-edit/preview/download "
                "and mobile viewport checks. No provider calls."
            )
        finally:
            page.screenshot(
                path=str(harness.ROOT / ".local/multimodal-20261030/last-browser-state.png"),
                full_page=True,
            )
            (harness.ROOT / ".local/multimodal-20261030/last-browser-state.txt").write_text(
                page.locator("body").inner_text(), encoding="utf-8"
            )
            browser.close()


if __name__ == "__main__":
    harness.run_smoke = run
    raise SystemExit(harness.main())
