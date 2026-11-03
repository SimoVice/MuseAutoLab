"""Human-readable, revision-bound concept guide and separate controller download."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from urllib.parse import quote

from app.instructions import _safe_url


def concept_controller_source() -> bytes:
    """Return a standalone standard-library Python preview/integration module."""
    return Path(__file__).with_name("concept_controller.py").read_bytes()


def concept_gateway_config(design: dict, project_id: str, revision: int) -> bytes:
    """Return a disabled gateway mapping template, never automatic hardware commands."""
    config = {
        "schema_version": 1,
        "base_url": "http://127.0.0.1:8787",
        "project_id": project_id,
        "revision": revision,
        "device_id": "",
        "timeout_seconds": 5,
        "commissioning_reviewed": False,
        "actions": {
            step["name"]: {"action": "", "parameters": {}} for step in design.get("steps", [])
        },
    }
    return json.dumps(config, indent=2, ensure_ascii=False).encode("utf-8")


def build_concept_guide(design: dict, project_id: str, revision: int) -> bytes:
    """Render the compiled design without regenerating geometry or calling a model.

    Relative sibling links work at the concept API route and in a matching offline
    folder. Exporters must preserve guide.html, project.json, controller.py,
    machine.stl and parts/<key>.stl together for offline downloads.
    """

    def esc(value):
        return escape(str(value), quote=True)

    def asset(path, label):
        return f'<a href="./{path}?revision={int(revision)}" download>{esc(label)}</a>'

    components = design.get("components", [])
    names = {part["key"]: part["name"] for part in components}
    rows, assembly, sources, supplies = [], [], [], []
    for part in components:
        model = asset(f"parts/{quote(part['key'], safe='')}.stl", "Download part model")
        rows.append(
            f'<tr><th scope="row">{esc(part["name"])}</th>'
            f"<td>{esc(part.get('role', ''))}</td><td>{model}</td></tr>"
        )
        assembly.append(
            f"<li><h3>{esc(part['name'])}</h3>"
            f"<p>{esc(part.get('assembly', 'Review its attachment and access.'))}</p>"
            "<p><strong>Check:</strong> "
            f"{esc(part.get('check', 'Verify fit before use.'))}"
            f"</p><p>{model}</p></li>"
        )
        source = part.get("source") or {}
        url = _safe_url(source.get("url"))
        if url:
            sources.append(
                f"<li><strong>{esc(part['name'])}</strong>: "
                f'<a href="{esc(url)}" rel="noreferrer">'
                f"{esc(source.get('title', 'Selected source'))}</a>. "
                "Reference for selection; verify the exact configuration, "
                "dimensions and current documentation before purchase.</li>"
            )
    sequence = []
    for step in design.get("steps", []):
        part_names = [names[key] for key in step.get("component_keys", []) if key in names]
        motion = ""
        if step.get("moving_key"):
            motion = (
                "<p><strong>Preview:</strong> "
                + esc(names.get(step["moving_key"], "Selected component"))
                + (
                    " moves to the next indexed pose and holds that pose."
                    if step.get("index_chain")
                    else " moves out and returns to its resting position."
                )
            )
            if step.get("stops"):
                motion += (
                    f" Includes {len(step['stops'])} planned travel pause(s); "
                    "sensor readings and process outcomes are not simulated."
                )
            motion += "</p>"
        sequence.append(
            f"<li><h3>{esc(step['name'])}</h3>"
            f"<p>{esc(step['instruction'])}</p>"
            "<p><strong>Uses:</strong> "
            f"{esc(', '.join(part_names) or 'Operator review')}"
            "</p>" + motion + "</li>"
        )
    working = []
    for interface in design.get("work_interfaces", []):
        pose = (
            f"{esc(interface['step_name'])} at {interface['phase']:.0%} of travel"
            if interface.get("step_name")
            else "At rest"
        )
        tool = esc(names[interface["tool_key"]])
        target = esc(names[interface["target_key"]])
        working.append(
            f"<li><strong>{esc(interface['label'])}</strong>. {pose}. "
            f"The proposed axis from {tool} intersects {target}.</li>"
        )
    working_section = (
        "<h3>Working positions</h3><ul>"
        + "".join(working)
        + "</ul><p>Only the listed positions have been checked geometrically. "
        "Verify calibration, access and process performance on the machine.</p>"
        if working
        else ""
    )
    software = design.get("software") or {}
    for item in design.get("supplies", []):
        source = item.get("source") or {}
        url = _safe_url(source.get("url"))
        search = _safe_url(item.get("catalog_search_url")) if not source else ""
        link = (
            f'<a href="{esc(url)}">{esc(source.get("title", "Source reference"))}</a>'
            if url
            else f'<a href="{esc(search)}">Search US catalog</a> '
            "(search only; no product or price verified)"
            if search
            else "Select and review an actual product"
        )
        supplies.append(
            f'<tr><th scope="row">{esc(item["name"])}</th>'
            f"<td>{esc(item.get('quantity', 1))} {esc(item.get('unit', ''))}</td>"
            f"<td>{esc(item.get('role', ''))}<br>{link}</td></tr>"
        )

    def items(values):
        return "".join(f"<li>{esc(value)}</li>" for value in values)

    width, depth = design.get("footprint_mm", [0, 0])
    title = esc(design.get("title", "Laboratory automation concept"))
    source_list = "".join(sources) or (
        "<li>No source reference recorded; select and review actual equipment.</li>"
    )
    questions = items(design.get("open_questions", [])) or (
        "<li>Review the proposed equipment and operating requirements with the team.</li>"
    )
    controller = esc(software.get("controller", "Select the actual controller before integration."))
    supply_table = (
        (
            "<h3>Additional equipment, hardware and consumables</h3>"
            "<p>These selection requirements have no part model. Verify quantities "
            "and compatibility; this is not a complete procurement BOM.</p>"
            '<div class="table-wrap"><table><thead><tr><th>Item</th><th>Quantity</th>'
            "<th>Purpose and reference</th></tr></thead><tbody>"
            + "".join(supplies)
            + "</tbody></table></div>"
        )
        if supplies
        else ""
    )
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{title} — revision {int(revision)}</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f2f6f8;color:#203441;
font:16px/1.65 "Segoe UI",Arial,sans-serif}}main{{max-width:1060px;margin:auto;padding:40px 24px}}
h1{{font-size:clamp(30px,5vw,46px);line-height:1.15;max-width:800px}}h2{{margin:36px 0 14px}}
h3{{font-size:18px;margin-bottom:4px}}p{{max-width:78ch}}a{{color:#075f85;text-underline-offset:3px}}
a:focus-visible{{outline:3px solid #075f85;outline-offset:4px}}
nav{{display:flex;gap:20px;flex-wrap:wrap}}
section{{border-top:1px solid #b9cbd4;padding-top:8px}}table{{width:100%;border-collapse:collapse}}
td,th{{padding:14px 10px;text-align:left;vertical-align:top;border-bottom:1px solid #cbd7de}}
ol{{padding-left:24px}}li{{padding-left:6px;margin:10px 0}}.notice{{border-left:4px solid #168099;
background:#e1edf2;padding:12px 20px}}.table-wrap{{overflow:auto}}
code{{background:#e3ebef;padding:3px 6px;overflow-wrap:anywhere}}
@media print{{body{{background:white}}main{{padding:0}}h2,h3{{break-after:avoid}}
li{{break-inside:avoid}}
a::after{{content:" (" attr(href) ")";font-size:11px;overflow-wrap:anywhere}}}}
</style></head><body><main>
<header><p>Project {esc(project_id)} · revision {int(revision)}</p>
<h1>{title}</h1>
<p>{esc(design.get("overview", ""))}</p>
<p>Proposed work area: {esc(width)} × {esc(depth)} mm.</p>
<p class="notice">Engineering concept for review. Part models show proposed geometry;
fit, fabrication, wiring, device integration and laboratory performance require verification.
The local controller simulates the sequence and has no configured hardware driver.</p></header>
<nav aria-label="Guide sections"><a href="#parts">Parts and sources</a>
<a href="#assembly">Assembly</a><a href="#operation">Operating sequence</a>
<a href="#software">Software and commissioning</a></nav>
<section><h2>Inspect the model in MuseAutoLab</h2>
<p>Drag the model to rotate it and scroll to zoom. The arrow buttons rotate the view;
Reset view restores the camera. Select an operation in Assembly and operation to review it.
Play advances the illustrative sequence, Pause holds the current view, Next step selects
the following operation, and Reset returns the sequence to its first step. Preview movement
jumps from a stationary instruction to the first moving step when that shortcut is available.</p>
<p>Independent motion steps travel out and back from the resting assembly. Linked indexed
rotations continue from the preceding indexed pose and hold the next pose. Reset restores
the first operation. Planned pauses are illustrative; timing is not a measured cycle time.
In reduced-motion mode,
use Next step to read the sequence without automatic movement.</p>
<p>To reopen the design in MuseAutoLab, use Save project in the application and then Open
project. The package's project.json is controller data, a different file from that saved project.
Keep this extracted folder together so the guide's model and software links work offline.</p>
</section>
<section id="parts"><h2>Parts and source references</h2>
<p>Keep the guide, part models and project data from the same revision. Check sourced
items against the actual product; a linked candidate does not establish compatibility.</p>
<div class="table-wrap"><table><thead><tr><th>Part</th><th>Purpose</th><th>Model</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
<p>{asset("machine.stl", "Download complete concept model")}</p>
{supply_table}<h3>Source documentation</h3><ul>{source_list}</ul></section>
<section id="assembly"><h2>Assemble and review the setup</h2>
<p>Start with an unpowered layout on a stable bench. Confirm the actual materials,
mounts, fasteners and access before fabrication. Follow manufacturer instructions
for purchased equipment; custom shapes need a reviewed fabrication drawing.</p>
<ol>{"".join(assembly)}</ol></section>
<section id="operation"><h2>Walk through the operating sequence</h2>
<p>Follow this order with representative empty items first. The preview describes intended
actions; it does not establish motion clearance, successful processing or automatic control.</p>
<ol>{"".join(sequence)}</ol>{working_section}</section>
<section id="software"><h2>Software and commissioning</h2>
<p>{controller}</p>
<h3>Connections to specify</h3><ul>{items(software.get("interfaces", []))}</ul>
<h3>Prepare the software</h3><ol>{items(software.get("setup", []))}
<li>Download {asset("project.json", "the project data")} and
{asset("controller.py", "the Python controller")} into one folder.</li>
<li>Install Python 3.12 or newer. Run <code>python controller.py project.json --simulate</code>.
Read the ordered output and compare it with the sequence above. This command uses no devices.</li>
<li>A device engineer can implement the documented DeviceAdapter interface in a separate
reviewed integration. Map logical actions to calibrated device commands and test stop/recovery;
the proposed model coordinates are not machine positions.</li></ol>
<h3>Optional JSON/HTTP device gateway</h3>
<p>The controller includes a real HTTP adapter for a separately implemented device gateway.
It sends commands only after explicit arming. This is an integration protocol, with no
off-the-shelf device driver or commissioned hardware supplied.</p>
<ol><li>Download {asset("gateway-config.json", "the disabled gateway configuration")}.
Specify the actual gateway address, device identity and one explicit action/parameter mapping
for every named step. Empty mappings are rejected;
preview coordinates are never sent as commands.</li>
<li>Implement and test the gateway locally first. It must accept JSON POST requests at
<code>/prepare</code>, <code>/execute</code> and <code>/stop</code>. Requests carry
<code>schema_version</code>, <code>request_id</code>, <code>device_id</code>,
<code>project_id</code> and <code>revision</code>. Execute adds <code>step_name</code>,
<code>action</code> and the explicitly mapped <code>parameters</code>.</li>
<li>Return HTTP 200 with the matching request, device, project and revision; include
<code>accepted: true</code> and <code>status</code> equal to <code>ready</code>,
<code>completed</code> or <code>stopped</code> for the respective endpoint.
Reject unknown actions, stale revisions and repeated commands; acknowledge completion only
after the device action has completed. The client does not retry commands.</li>
<li>After supervised commissioning, set <code>commissioning_reviewed</code> to true.
Run <code>python controller.py project.json --gateway-config gateway-config.json
--arm-hardware</code>
and type the requested project/revision confirmation. The client checks acknowledgements,
uses timeouts and attempts a stop on completion or failure.</li></ol>
<p>A disconnected gateway cannot guarantee a physical stop. Provide device-side limits,
interlocks, a communications watchdog and an independent emergency stop before hardware use.
The HTTP adapter and a successful acknowledgement do not validate laboratory performance.</p>
<h3>Commission before hardware use</h3><ul>{items(software.get("checks", []))}
<li>Record exact equipment, firmware, connections, limits, calibration and stop behavior.</li>
<li>Complete supervised dry runs, clearance checks and process acceptance tests before samples.
No commissioning result is supplied by this guide or by the simulation.</li></ul></section>
<section><h2>Questions to resolve</h2><ul>{questions}</ul></section>
</main></body></html>"""
    return page.encode("utf-8")
