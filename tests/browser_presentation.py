"""Repeatable real-browser presentation checks using public portable examples.

No inference, supplier refresh or CAD generation. Browser screenshots and WebGL
draw-call observations describe a digital presentation, not physical validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import browser_smoke as harness  # noqa: E402


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def stable_snapshot(value):
    # Every real save regenerates this timestamp; all engineering fields remain checked.
    return {key: item for key, item in value.items() if key != "saved_at"}


def label_metrics(page):
    """Report actual DOM label spacing; screenshots remain the visual authority."""
    return page.locator(".microplate-axis-label").evaluate_all("""labels => {
      const canvas = document.querySelector('canvas').getBoundingClientRect();
      const rows = labels.map(element => {
        const rect = element.getBoundingClientRect();
        return {text: element.textContent, x: rect.x, y: rect.y, width: rect.width,
          height: rect.height, fontSize: getComputedStyle(element).fontSize};
      });
      const intersections = [];
      for (let a=0; a<rows.length; a++) for (let b=a+1; b<rows.length; b++) {
        const first=rows[a], second=rows[b];
        if (first.x < second.x+second.width && first.x+first.width > second.x &&
          first.y < second.y+second.height && first.y+first.height > second.y) {
            intersections.push([first.text, second.text]);
        }
      }
      const right = rows.length ? Math.max(...rows.map(row=>row.x+row.width)) : 0;
      const left = rows.length ? Math.min(...rows.map(row=>row.x)) : 0;
      const width = right-left;
      return {labels:rows, intersections, labelSpanWidth:width, canvasWidth:canvas.width,
        canvasHeight:canvas.height, labelSpanFraction:width/canvas.width};
    }""")


def run(url, output=None):
    from playwright.sync_api import expect, sync_playwright

    output = output or harness.ROOT / ".local" / "visual-3d-20261031" / "after"
    output.mkdir(parents=True, exist_ok=True)
    evidence = {
        "started_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "url": url,
        "errors": [],
        "requests": [],
        "blocked_requests": [],
        "failed_responses": [],
        "projects": {},
        "scope": "Real API/compiler/Chrome; public portable projects; digital presentation only.",
    }
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
        # Observe browser rendering calls without reading React/Three application state.
        page.add_init_script("""(() => {
          window.presentationDrawCalls = 0;
          for (const type of [WebGLRenderingContext, WebGL2RenderingContext]) {
            const methods = ['drawArrays', 'drawElements',
              'drawArraysInstanced', 'drawElementsInstanced'];
            for (const name of methods) {
              const original = type.prototype[name];
              if (typeof original !== 'function') continue;
              type.prototype[name] = function(...args) {
                window.presentationDrawCalls++;
                return original.apply(this, args);
              };
            }
          }
        })();""")
        page.on("pageerror", lambda error: evidence["errors"].append(str(error)))
        page.on(
            "console",
            lambda message: (
                evidence["errors"].append(message.text) if message.type == "error" else None
            ),
        )
        page.on(
            "request",
            lambda request: evidence["requests"].append(
                {"method": request.method, "url": request.url}
            ),
        )
        page.on(
            "response",
            lambda response: (
                evidence["failed_responses"].append(
                    {"status": response.status, "url": response.url}
                )
                if response.status >= 400
                else None
            ),
        )

        def guard(route):
            request = route.request
            local = urlsplit(request.url).hostname in {"localhost", "127.0.0.1", "::1"}
            allowed = request.method in {"GET", "HEAD", "OPTIONS"} or (
                request.method == "POST"
                and urlsplit(request.url).path in {"/api/projects", "/api/projects/open"}
            )
            if local and allowed:
                route.continue_()
            else:
                evidence["blocked_requests"].append({"method": request.method, "url": request.url})
                route.abort("blockedbyclient")

        page.route("**/*", guard)

        def settle():
            page.wait_for_timeout(700)
            page.evaluate(
                "() => new Promise(resolve => requestAnimationFrame(() => "
                "requestAnimationFrame(resolve)))"
            )

        def motion_frames():
            return page.evaluate("""async () => {
              const samples = [];
              for (let frame=0; frame<12; frame++) {
                await new Promise(resolve => requestAnimationFrame(resolve));
                samples.push(window.presentationDrawCalls);
              }
              return samples;
            }""")

        def snapshot(project):
            response = page.request.get(
                f"{url.rstrip('/')}/api/projects/{project['id']}/snapshot?revision={project['revision']}"
            )
            assert response.ok, response.text()
            return response.json()

        def screenshot(name, locator=None):
            (locator or page).screenshot(path=str(output / name))

        try:
            page.goto(url, wait_until="networkidle")
            expect(page.get_by_text("Workspace ready")).to_be_visible()
            assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
            for kind, filename, label in [
                ("plate", "microplate-project.json", "Confirmed digital r16 plate result"),
                ("rack", "microplate-tube-setup.json", "Synthetic r14 tube setup"),
            ]:
                source = harness.ROOT / "docs/examples" / filename
                with page.expect_response(
                    lambda response: urlsplit(response.url).path == "/api/projects/open"
                ) as opened:
                    page.get_by_label("Open saved project").set_input_files(str(source))
                assert opened.value.ok, opened.value.text()
                project = opened.value.json()["project"]
                expect(page.locator("canvas")).to_have_count(1)
                expect(page.locator(".scene-loading")).to_have_count(0, timeout=60000)
                settle()
                canvas = page.locator("canvas").element_handle()
                page.locator(".design-panel").evaluate("element => element.scrollTop = 0")
                screenshot(f"{kind}-workstation-desktop.png")
                screenshot(f"{kind}-workstation-view.png", page.locator(".viewer-shell"))
                page.set_viewport_size({"width": 390, "height": 844})
                settle()
                page.locator(".viewer-shell").scroll_into_view_if_needed()
                screenshot(f"{kind}-workstation-mobile.png")
                page.set_viewport_size({"width": 1440, "height": 1000})
                settle()
                before = snapshot(project)

                expand = page.get_by_role("button", name="Expand 3D view", exact=True)
                expand.click()
                dialog = page.get_by_role("dialog")
                expect(dialog).to_be_visible()
                expect(dialog).to_have_attribute("aria-modal", "true")
                expect(page.get_by_role("button", name="Exit expanded view")).to_be_focused()
                assert canvas.evaluate("element => element === document.querySelector('canvas')")
                assert page.get_by_label("Describe your workflow or request a change").evaluate(
                    "element => !!element.closest('[inert]')"
                )
                for _ in range(16):
                    page.keyboard.press("Tab")
                    assert dialog.evaluate("element => element.contains(document.activeElement)")
                page.keyboard.press("Shift+Tab")
                assert dialog.evaluate("element => element.contains(document.activeElement)")
                settle()
                screenshot(f"{kind}-expanded-workstation.png")

                select = page.get_by_label("Component in expanded view")
                select.select_option("sample-rack")
                expect(select).to_have_value("sample-rack")
                page.get_by_label("Inspect component view").select_option("part")
                reduced_focus_frames = motion_frames()
                assert len(set(reduced_focus_frames[2:])) == 1, reduced_focus_frames
                settle()
                if kind == "plate":
                    expect(page.locator(".microplate-axis-label")).to_have_count(20)
                    expect(page.locator(".scene-rack-occupancy")).to_contain_text(
                        "3 / 96 wells occupied"
                    )
                else:
                    expect(page.locator(".scene-rack-occupancy")).to_contain_text(
                        "positions occupied"
                    )
                screenshot(f"{kind}-expanded-focused.png")
                screenshot(f"{kind}-expanded-focused-canvas.png", page.locator("canvas"))
                desktop_labels = label_metrics(page)
                assert not desktop_labels["intersections"], desktop_labels["intersections"]
                canvas_before = hashlib.sha256(page.locator("canvas").screenshot()).hexdigest()
                page.get_by_role("button", name="Rotate left", exact=True).click()
                page.get_by_role("button", name="Zoom in", exact=True).click()
                settle()
                canvas_after = hashlib.sha256(page.locator("canvas").screenshot()).hexdigest()
                assert canvas_before != canvas_after, (
                    "Visible camera controls must change rendered pixels."
                )
                screenshot(f"{kind}-camera-control-result.png")

                # Measure whether the static demand loop stops issuing WebGL draw calls.
                settle()
                idle_start = page.evaluate("window.presentationDrawCalls")
                page.wait_for_timeout(600)
                idle_end = page.evaluate("window.presentationDrawCalls")
                assert isinstance(idle_start, int) and idle_start > 0
                assert idle_start == idle_end, (idle_start, idle_end)

                page.set_viewport_size({"width": 390, "height": 844})
                settle()
                expect(dialog).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                assert page.locator("canvas").bounding_box()["height"] > 100
                mobile_labels = label_metrics(page)
                assert not mobile_labels["intersections"], mobile_labels["intersections"]
                occupancy = page.locator(".scene-rack-occupancy").bounding_box()
                inspection = page.get_by_label("Inspect component view").bounding_box()
                assert (
                    occupancy["y"] >= inspection["y"] + inspection["height"]
                    or inspection["y"] >= occupancy["y"] + occupancy["height"]
                ), "Occupancy and inspection controls must not overlap on mobile."
                screenshot(f"{kind}-expanded-mobile.png")
                page.keyboard.press("Escape")
                expect(page.get_by_role("dialog")).to_have_count(0)
                expect(expand).to_be_focused()
                assert not page.get_by_label("Describe your workflow or request a change").evaluate(
                    "element => !!element.closest('[inert]')"
                )
                assert canvas.evaluate("element => element === document.querySelector('canvas')")
                page.locator(".viewer-shell").scroll_into_view_if_needed()
                settle()
                screenshot(f"{kind}-focused-mobile.png")
                page.set_viewport_size({"width": 1440, "height": 1000})
                settle()
                screenshot(f"{kind}-focused-desktop.png")
                screenshot(f"{kind}-focused-view.png", page.locator(".viewer-shell"))
                embedded_labels = label_metrics(page)
                expand.click()
                page.get_by_role("button", name="Exit expanded view", exact=True).click()
                expect(expand).to_be_focused()
                assert canvas.evaluate("element => element === document.querySelector('canvas')")

                # Exercise the actual user Save action, then compare every stable field.
                with (
                    page.expect_download() as download,
                    page.expect_response(lambda response: "/snapshot?" in response.url) as saved,
                ):
                    page.get_by_role("button", name="Save project", exact=True).click()
                assert saved.value.ok
                download.value.save_as(str(output / f"{kind}-saved-after-presentation.json"))
                after = json.loads(
                    (output / f"{kind}-saved-after-presentation.json").read_text(encoding="utf8")
                )
                assert digest(stable_snapshot(before)) == digest(stable_snapshot(after))
                with page.expect_response(
                    lambda response: urlsplit(response.url).path == "/api/projects/open"
                ) as reopened:
                    page.get_by_label("Open saved project").set_input_files(
                        str(output / f"{kind}-saved-after-presentation.json")
                    )
                rebuilt = reopened.value.json()["project"]
                assert digest(project["design"]) == digest(rebuilt["design"])
                normal_focus_frames = None
                if kind == "plate":
                    expect(page.locator(".scene-loading")).to_have_count(0, timeout=60000)
                    settle()
                    page.emulate_media(reduced_motion="no-preference")
                    page.get_by_role("button", name="Show plate in model").click()
                    page.get_by_label("Inspect component view").select_option("part")
                    normal_focus_frames = motion_frames()
                    assert len(set(normal_focus_frames[2:])) > 1, normal_focus_frames
                    settle()
                    normal_idle_start = page.evaluate("window.presentationDrawCalls")
                    page.wait_for_timeout(600)
                    assert page.evaluate("window.presentationDrawCalls") == normal_idle_start
                    page.emulate_media(reduced_motion="reduce")
                evidence["projects"][kind] = {
                    "input": filename,
                    "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "label": label,
                    "revision": project["revision"],
                    "portable_before_raw_sha256": digest(before),
                    "portable_after_raw_sha256": digest(after),
                    "portable_before_stable_sha256": digest(stable_snapshot(before)),
                    "portable_after_stable_sha256": digest(stable_snapshot(after)),
                    "excluded_volatile_field": "saved_at",
                    "design_before_sha256": digest(project["design"]),
                    "design_reopened_sha256": digest(rebuilt["design"]),
                    "canvas_before_camera_sha256": canvas_before,
                    "canvas_after_camera_sha256": canvas_after,
                    "idle_draw_calls_start": idle_start,
                    "idle_draw_calls_end": idle_end,
                    "canvas_identity_preserved": True,
                    "focus_restored": True,
                    "workspace_inert_during_expansion": True,
                    "expanded_desktop_labels": desktop_labels,
                    "expanded_mobile_labels": mobile_labels,
                    "embedded_desktop_labels_after_camera": embedded_labels,
                    "reduced_focus_draw_calls_per_frame": reduced_focus_frames,
                    "normal_focus_draw_calls_per_frame": normal_focus_frames,
                }
            assert not evidence["errors"], evidence["errors"]
            assert not evidence["blocked_requests"], evidence["blocked_requests"]
            assert not evidence["failed_responses"], evidence["failed_responses"]
            evidence["status"] = "passed"
        except Exception as error:
            evidence.update(status="failed", error=f"{type(error).__name__}: {error}")
            screenshot("failure-state.png")
            raise
        finally:
            evidence["finished_at"] = datetime.now(UTC).isoformat()
            evidence["no_external_requests"] = all(
                urlsplit(request["url"]).hostname in {"127.0.0.1", "localhost", "::1"}
                for request in evidence["requests"]
            )
            (output / "browser-presentation-result.json").write_text(
                json.dumps(evidence, indent=2), encoding="utf8"
            )
            browser.close()
    print(
        "[browser-presentation] Passed expanded view, focus, camera, resize, reduced motion, "
        f"idle rendering and unchanged engineering state; {output}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        help="Use an already running local frontend; otherwise start the offline browser harness.",
    )
    parser.add_argument("--output", type=Path, help="Screenshot and metadata output folder.")
    args = parser.parse_args()
    if args.url:
        assert urlsplit(args.url).hostname in {"127.0.0.1", "localhost", "::1"}
        run(args.url, args.output)
    else:
        harness.run_smoke = lambda url: run(url, args.output)
        raise SystemExit(harness.main())
