"""Concept assembly sequence and document exports (concept only, no hardware validation)."""

from __future__ import annotations

import csv
import html
import io
import json
from pprint import pformat

CHECKED_LABEL = "not recorded"

def _project_id(project: dict) -> str:
    return str(project.get("id", "unknown"))


def _revision(project: dict) -> int:
    try:
        return int(project.get("revision", 0))
    except (TypeError, ValueError):
        return 0


def _components(project: dict) -> list[dict]:
    design = project.get("design") or {}
    comps = design.get("components") or []
    return [c for c in comps if isinstance(c, dict) and c.get("id")]


def _comp_index(project: dict) -> dict[str, dict]:
    return {c["id"]: c for c in _components(project)}


def _cooling(project: dict) -> dict:
    design = project.get("design") or {}
    info = design.get("cooling") or {}
    summary = project.get("summary") or {}
    enabled = bool(info.get("enabled", summary.get("cooling_enabled", False)))
    target = info.get("target_c", summary.get("cooling_target_c"))
    return {
        "enabled": enabled,
        "target_c": target,
        "target_source": info.get("target_source", "assumed"),
        "variant_id": str(info.get("variant_id", "")),
        "transfer_mode": "manual",
    }


def _footprint(project: dict) -> dict:
    design = project.get("design") or {}
    bounds = design.get("assembly_bounds")
    if bounds:
        sizes = [b - a for a, b in zip(bounds["min_mm"], bounds["max_mm"])]
        return {"width_mm": sizes[0], "depth_mm": sizes[2], "height_mm": sizes[1]}
    fp = design.get("footprint") or {}
    return {
        "width_mm": fp.get("width_mm"),
        "depth_mm": fp.get("depth_mm"),
        "height_mm": fp.get("height_mm"),
    }


def _sourcing_groups(project: dict) -> list[dict]:
    sourcing = project.get("sourcing") or {}
    groups = sourcing.get("groups") or []
    return [g for g in groups if isinstance(g, dict)]


def _selected_option(group: dict) -> dict | None:
    selected_id = group.get("selected_id")
    for opt in group.get("options") or []:
        if opt.get("id") == selected_id:
            return opt
    return None


def _money(value) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return ""


def _display_mm(value) -> str:
    """Round document dimensions only; canonical geometry retains full precision."""
    if value is None:
        return "undecided"
    try:
        number = round(float(value), 1)
        return f"{0 if number == 0 else number:.1f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def _display_vector(value, separator: str) -> str:
    if isinstance(value, (list, tuple)):
        return separator.join(_display_mm(item) for item in value)
    return str(value)


def assembly_steps(project: dict, procurement: dict | None = None) -> list[dict]:
    """Return the same revision-bound sequence used by immediate previews and exports."""
    from app.instructions import build_instruction_guide

    return build_instruction_guide(project, procurement)["steps"]


def _csv_cell(value: str) -> str:
    if value and (value.lstrip()[:1] in ("=", "+", "-", "@") or value[:1] in ("\t", "\r", "\n")):
        return "'" + value
    return value


def _bom_rows(project: dict) -> list[list[str]]:
    currency = str((project.get("sourcing") or {}).get("currency", "USD"))
    rows: list[list[str]] = []
    for group in _sourcing_groups(project):
        opt = _selected_option(group)
        if opt is None:
            continue
        qty = group.get("quantity", 1)
        unit = opt.get("unit_price")
        try:
            line = float(unit) * int(qty) if unit is not None else None
        except (TypeError, ValueError):
            line = None
        rows.append(
            [
                str(group.get("id", "")),
                str(group.get("label", "")),
                str(opt.get("label", "")),
                str(opt.get("supplier", "")),
                str(qty),
                _money(unit),
                _money(line),
                currency,
                str(opt.get("price_kind", "")),
                str(opt.get("source_url") or ""),
                str(opt.get("checked_on") or ""),
                str(opt.get("compatibility_note") or ""),
            ]
        )
    return rows


def build_bom_csv(project: dict) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    writer.writerow(
        [
            "group",
            "group_label",
            "option",
            "supplier",
            "quantity",
            "unit_price",
            "line_total",
            "currency",
            "price_kind",
            "source",
            "checked_on",
            "compatibility",
        ]
    )
    for row in _bom_rows(project):
        writer.writerow([_csv_cell(c) for c in row])
    return buf.getvalue().encode("utf-8")


def build_preparation_csv(project: dict) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    writer.writerow(["target", "stock_volume_ul", "diluent_volume_ul", "total_volume_ul"])
    plan = project.get("plan") or {}
    for step in plan.get("steps") or []:
        if not isinstance(step, dict):
            continue
        writer.writerow(
            [
                _csv_cell(str(step.get("target", ""))),
                _csv_cell(str(step.get("stock_volume_ul", ""))),
                _csv_cell(str(step.get("diluent_volume_ul", ""))),
                _csv_cell(str(step.get("total_volume_ul", ""))),
            ]
        )
    return buf.getvalue().encode("utf-8")


def _svg_rects(components: list[dict], highlight: set[str]) -> str:
    """True-scale top view, with a numbered legend outside the geometry."""
    if not components:
        return '<p class="empty">No component geometry in this snapshot.</p>'
    xs = [c["position"][0] + sign * c["size"][0] / 2 for c in components for sign in (-1, 1)]
    zs = [c["position"][2] + sign * c["size"][2] / 2 for c in components for sign in (-1, 1)]
    min_x, max_x, min_z, max_z = min(xs) - 20, max(xs) + 20, min(zs) - 20, max(zs) + 20
    view_height = max(420, 60 + len(components) * 27)
    scale = min(500 / (max_x - min_x), view_height / (max_z - min_z))
    offset_x = (500 - (max_x - min_x) * scale) / 2
    offset_y = (view_height - (max_z - min_z) * scale) / 2
    parts = [
        f'<svg viewBox="0 0 760 {view_height}" role="img" '
        'aria-label="Numbered top view of deck envelopes">'
    ]
    markers = []
    for number, comp in enumerate(components, 1):
        px, _, pz = comp["position"]
        sx, _, sz = comp["size"]
        x = offset_x + (px - sx / 2 - min_x) * scale
        y = offset_y + (max_z - pz - sz / 2) * scale
        width, height = sx * scale, sz * scale
        cid = str(comp["id"])
        active = cid in highlight
        fill = "#0f766e" if active else "#d7e8e4"
        stroke = "#0b4f4a" if active else "#75958e"
        label = html.escape(str(comp.get("label", cid)))
        parts.append(
            f"<g><title>{label}</title>"
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" '
            f'fill="{fill}" fill-opacity="0.75" stroke="{stroke}" stroke-width="1.5"/></g>'
        )
        cx, cy = x + width / 2, y + height / 2
        anchor_x, anchor_y = cx, cy
        if cid == "base":
            cx, cy = x + 14, y + 15
        elif cid == "pipette":
            cx += 20
        elif cid == "crossbar":
            cx -= 36
            cy -= 14
        if cid in ("pipette", "crossbar"):
            markers.append(
                f'<line x1="{anchor_x:.1f}" y1="{anchor_y:.1f}" x2="{cx:.1f}" '
                f'y2="{cy:.1f}" stroke="{stroke}" stroke-width="1"/>'
            )
        markers.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="9" fill="white" stroke="{stroke}"/>'
            f'<text x="{cx:.1f}" y="{cy + 3.5:.1f}" text-anchor="middle" '
            f'font-size="10" fill="#123331">{number}</text>'
            f'<rect x="530" y="{24 + number * 27}" width="12" height="12" fill="{fill}"/>'
            f'<text x="551" y="{35 + number * 27}" font-size="13" '
            f'fill="#123331">{number}. {html.escape(cid)}</text>'
        )
    parts.extend(markers)
    parts.append("</svg>")
    return "".join(parts)


def _overview_svg(project: dict) -> str:
    return _svg_rects(_components(project), set())


def _step_svg(project: dict, component_ids: list[str]) -> str:
    return _svg_rects(_components(project), set(component_ids))


def _design_provenance_html(project: dict) -> str:
    engineering = project.get("engineering_design")
    if not engineering:
        return ""
    provenance = engineering["provenance"]
    proposal = engineering["proposal"]
    model = html.escape(str(provenance.get("model", "not recorded")))
    rationale = html.escape(proposal["rationale"])
    checks = provenance.get("checks", [])
    passed = sum(check.get("passed") is True for check in checks)
    if project.get("design", {}).get("platform"):
        model_choices = "Meta proposed assignments of three labware proxies to deck slots. "
    elif project.get("design", {}).get("foundation"):
        model_choices = (
            "Meta proposed custom-insert dimensions, component positions and a digital bed pose. "
            "The original source frame remains fixed. "
        )
    else:
        model_choices = "Meta proposed the operating-deck dimensions and five component positions. "
    return (
        '<div class="card"><h2>Meta layout decision</h2>'
        f"<p>Model: {model}. {passed}/{len(checks)} recorded geometry checks passed.</p>"
        f"<p>{rationale}</p>"
        "<p>" + model_choices +
        "The application checked and compiled the proposal; these checks do not establish "
        "hardware feasibility. The full accepted proposal and provenance are in "
        "project.json under engineering_design.</p></div>"
    )


def _source_basis_html(project: dict) -> str:
    basis = project.get("design_basis")
    if not basis:
        return ""
    rows = []
    bindings = "".join(
        f'<tr><td>{html.escape(item["component_id"])}</td>'
        f'<td>{html.escape(item["basis"])}</td>'
        f'<td>{html.escape(item["reference_id"] or "Custom concept")}</td>'
        f'<td>{html.escape(item["detail"])}</td></tr>' for item in basis["bindings"]
    )
    for ref in basis["references"]:
        rows.append(
            f'<tr><td><a href="{html.escape(ref["url"], quote=True)}">'
            f'{html.escape(ref["title"])}</a></td><td>{html.escape(ref["license"])}</td>'
            f'<td>{html.escape(ref["use"])}</td><td>{html.escape(ref["limits"])}</td></tr>'
        )
    return ('<section class="card"><h2>Design sources and geometry basis</h2>'
            '<p>' + html.escape(basis["architecture"]) + '. '
            'Manufacturer envelopes and proposed custom interfaces have distinct bindings. '
            'Imported CAD does not establish a validated adapter.</p>'
            '<div class="table-scroll" role="region" aria-label="Component source bindings" '
            'tabindex="0"><table><thead><tr><th>Part</th><th>Basis</th><th>Reference</th><th>Scope</th>'
            '</tr></thead><tbody>' + bindings + '</tbody></table></div>'
            '<div class="table-scroll" role="region" aria-label="Primary sources" tabindex="0">'
            '<table><thead><tr><th>Primary reference</th><th>License / rights</th>'
            '<th>Use</th><th>Scope</th></tr></thead><tbody>' + "".join(rows) +
            '</tbody></table></div><p>Revision-pinned source records and component bindings are '
            'in project.json and cad/geometry-report.json under design_basis.</p></section>')


def build_guide_html(project: dict, steps: list[dict], *, guide: dict | None = None) -> bytes:
    from app.instructions import procurement_html, step_details_html
    pid = html.escape(_project_id(project))
    rev = _revision(project)
    fp = _footprint(project)
    cooling = _cooling(project)
    sourcing = project.get("sourcing") or {}
    checked = html.escape(str(sourcing.get("checked_on", CHECKED_LABEL)))
    if guide is not None:
        dates = [source.get("checked_on", "") for source in guide.get("sources", [])]
        checked = (
            f"historical component snapshot {checked}; instruction references "
            + html.escape(max(dates, default=CHECKED_LABEL))
        )
    limitations = [
        "Concept sequence only; mechanical, thermal, and electronic interfaces are unverified.",
        "Custom deck is a solid blank for review, not fabrication-ready; no drill patterns "
        "or mounts are specified.",
        "No fastener sizes, torque values, wiring pinouts, or calibration steps are given.",
        "Cold target is a requested setting with manual transfer, never a measured temperature.",
    ]
    if project.get("design", {}).get("platform"):
        limitations = [
            "Assembled instrument setup; no manufacturer machine CAD or fabrication design.",
            "Published enclosure dimensions and software slots only; internal shapes, deck "
            "height and rack proxies are illustrative.",
            "Confirm compatible instrument pipettes, labware, tips and calibration with "
            "the manufacturer before purchasing or running a protocol.",
            "No control driver, dynamics validation or laboratory test is implemented.",
        ]
    comp_rows = []
    for comp in _components(project):
        comp_rows.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                html.escape(str(comp.get("id", ""))),
                html.escape(str(comp.get("label", ""))),
                html.escape(_display_vector(comp.get("position", ""), ", ")),
                html.escape(_display_vector(comp.get("size", ""), " × ")),
            )
        )
    step_sections = []
    for number, step in enumerate(steps, start=1):
        comp_list = ", ".join(html.escape(str(c)) for c in step.get("component_ids", [])) or "none"
        instructions = "".join(
            f"<li>{html.escape(str(t))}</li>" for t in step.get("instructions", [])
        )
        checks = "".join(f"<li>{html.escape(str(t))}</li>" for t in step.get("checks", []))
        gate = str(step.get("status", "needs_design")).replace("_", " ")
        step_sections.append(
            '<section class="step"><h3>{}. {}</h3>'
            '<p class="meta">Components: {} &middot; {}</p>{}<ul>{}</ul>'
            '<h4>Checks</h4><ul class="checks">{}</ul></section>'.format(
                number,
                html.escape(str(step.get("title", step.get("id", "")))),
                comp_list,
                html.escape(gate),
                _step_svg(project, list(step.get("component_ids", []))),
                instructions,
                checks,
            ).replace("</section>", step_details_html(step) + "</section>")
        )
    target_text = html.escape(str(cooling["target_c"]))
    page = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Assembly guide — PROJECT_ID rREV</title>
<style>
*{box-sizing:border-box}body{font-family:Segoe UI,Arial,sans-serif;background:#f4f8f7;color:#1d3330;
margin:0;line-height:1.65}
header{background:#103f45;color:#fff;padding:40px max(24px,calc((100vw - 900px)/2))}
h1{font-family:Georgia,serif;font-size:38px;font-weight:400;line-height:1.15;margin:0 0 12px}
header p{margin:0;font-size:12px;color:#c1dcd6;overflow-wrap:anywhere}
h2{font-size:21px;letter-spacing:-.02em}h3{font-size:20px;color:#115d60}
h4{font-size:12px;text-transform:uppercase;letter-spacing:.08em}
main{max-width:948px;margin:0 auto;padding:20px 24px}
.card,.step{background:#fff;border:1px solid #d3e3df;border-radius:12px;padding:20px;margin:16px 0;
overflow-wrap:anywhere}
.step{break-inside:avoid}.meta{font-size:12px;color:#5b7775}
svg{display:block;max-width:740px;width:100%;height:auto;margin:20px auto;
background:#f2f8f6;border:1px solid #d8e7e1;border-radius:8px}
li+li{margin-top:6px}.checks{border-left:3px solid #71b4a6;padding-left:28px}
table{border-collapse:collapse;width:100%;font-size:13px}
.table-scroll{overflow-x:auto;margin:16px 0;overscroll-behavior-x:contain}
.table-scroll table{min-width:600px}.table-scroll:focus-visible{outline:2px solid #0f766e}
th,td{border:1px solid #bcd8d3;padding:6px;text-align:left}
th{background:#d7e8e4}
.procurement-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
.procurement-item{border:1px solid #c9ded8;border-radius:8px;padding:18px;min-width:0;
font-size:14px;line-height:1.55;break-inside:avoid}
.procurement-item h3{font-size:18px;line-height:1.3;margin:8px 0;overflow-wrap:normal}
.procurement-item h4{margin:16px 0 6px}.procurement-item p{margin:8px 0}
.procurement-role{display:inline-block;background:#edf5f2;border-radius:4px;padding:3px 7px;
font-size:12px;color:#305b52}
.procurement-facts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;
border-block:1px solid #d8e7e1;padding:14px 0;margin:16px 0}
.procurement-facts dt{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:#58716c}
.procurement-facts dd{margin:3px 0 0;font-size:14px;font-weight:600}
.procurement-source{font-size:12px;line-height:1.7}
@media(max-width:600px){header{padding:26px 18px}h1{font-size:30px}
main{padding:8px 12px}.card,.step{padding:16px;margin:12px 0}h2{font-size:19px}
.procurement-grid{grid-template-columns:minmax(0,1fr)}.procurement-item{padding:14px}}
@media print{body{background:white;font-size:10pt}
header{color:#103f45;background:white;border-bottom:2px solid #0f766e;padding:12px}
header p{color:#44635f}main{padding:0}.step{break-before:page;border:none}
svg{max-width:640px}table{font-size:9pt}th,td{overflow-wrap:anywhere}
.table-scroll{overflow:visible}.table-scroll table{min-width:0}
.procurement-grid{display:block}.procurement-item{margin:12px 0;border-radius:0;font-size:10pt}
.procurement-item h3{font-size:13pt}.procurement-facts dd{font-size:10pt}
.procurement-source a::after{content:" (" attr(href) ")";overflow-wrap:anywhere}}
</style>
</head>
<body>
<header><h1>Concept assembly guide</h1>
<p>Project PROJECT_ID &middot; revision REV &middot; concept only</p></header>
<main>
<div class="card"><h2>Revision overview</h2>
<p>Concept assembly sequence. Mounts, wiring and hardware performance remain to be engineered.</p>
<p>Assembly envelope FP &middot; cooling COOLING &middot; target TARGET<br>
Sources checked CHECKED.</p>
<p class="meta">Dimensions below are rounded to 0.1 mm for readability, not a tolerance claim.
The diagrams show component envelopes, not source-CAD renders or physical assembly evidence.</p>
<div>OVERVIEW_SVG</div></div>
<div class="card"><h2>Shared concept geometry</h2>
<p>The interactive model and workstation STEP use the same component primitive geometry.
The custom sample insert follows the target count without changing its outside dimensions.
Tube and tip consumables remain separate assumed proxies. The numbered plan below is a
simplified position guide; mechanical fits, materials and fabrication remain unverified.</p>
<p>Physics uses conservative component envelopes. Fine openings and visual details do not
establish insertion clearance, material mass or collision-safe hardware.</p></div>
<div class="card"><h2>Components (mm, y up)</h2>
<div class="table-scroll" role="region" aria-label="Component dimensions" tabindex="0">
<table><tr><th>id</th><th>label</th><th>position (x, y, z)</th><th>size (x × y × z)</th></tr>
ROWS</table></div></div>
STEPS
<div class="card"><h2>Open engineering items</h2>
<ul><li>LIMITATIONS</li></ul></div>
</main>
</body>
</html>"""
    page = page.replace("PROJECT_ID", pid).replace("rREV", f"r{rev}").replace("REV", str(rev))
    page = page.replace("</main>", _design_provenance_html(project) + _source_basis_html(project)
                        + "</main>")
    page = page.replace("LIMITATIONS", "</li><li>".join(html.escape(s) for s in limitations))
    page = page.replace(
        "FP", html.escape(" × ".join(_display_mm(fp.get(axis)) for axis in
                                     ("width_mm", "depth_mm", "height_mm")) + " mm")
    )
    cooling_text = f"{cooling['variant_id']}, manual transfer" if cooling["enabled"] else "disabled"
    page = page.replace("COOLING", html.escape(cooling_text))
    page = page.replace(
        "TARGET", target_text + " °C (requested)" if cooling["enabled"] else "not applicable"
    )
    page = page.replace("CHECKED", checked)
    page = page.replace("OVERVIEW_SVG", _overview_svg(project))
    page = page.replace("ROWS", "".join(comp_rows))
    page = page.replace("STEPS", "".join(step_sections))
    if project.get("design", {}).get("foundation"):
        page = page.replace(
            "The interactive model and workstation STEP use the same component primitive geometry.",
            "The interactive model uses simplified meshes of the pinned Jubilee STEP plus custom "
            "primitives. The exported workstation STEP retains the original source assembly "
            "and the same bed pose and custom parts.")
        page = page.replace("Physics uses conservative component envelopes.",
                            "Jubilee physical simulation is not implemented.")
    if project.get("design", {}).get("platform"):
        page = page.replace("Concept assembly guide", "Instrument purchase and setup guide")
        page = page.replace(
            "Concept assembly sequence. Mounts, wiring and hardware performance remain "
            "to be engineered.",
            "Configure and install an assembled instrument using the manufacturer's instructions.")
        page = page.replace(
            "The custom sample insert follows the target count without changing its "
            "outside dimensions.",
            "Rack proxies mark the chosen software slots; exact labware fit is unverified.")
        page = page.replace("Physics uses conservative component envelopes.",
                            "OT-2 physical simulation is not implemented.")
    if project.get("labware_rack"):
        page = page.replace(
            "The custom sample insert follows the target count without changing its "
            "outside dimensions.",
            "The custom sample rack uses its declared tube envelopes, count and columns. "
            "Its capacity is independent of the number of preparation targets; unused holes "
            "remain free. The other labware fixtures and imported source frame are unchanged.")
        page = page.replace(
            "Tube and tip consumables remain separate assumed proxies.",
            "Occupied sample positions show declared body envelopes and closed-cap outlines; "
            "tip and source consumables remain separate assumed proxies.")
    if guide is not None:
        page = page.replace("</main>", procurement_html(guide) + "</main>")
    return page.encode("utf-8")


def build_preview_source(project: dict) -> bytes:
    plan = project.get("plan") or {}
    raw_steps = [s for s in (plan.get("steps") or []) if isinstance(s, dict)]
    safe_steps = [
        {
            "target": str(s.get("target", "")),
            "stock_volume_ul": s.get("stock_volume_ul"),
            "diluent_volume_ul": s.get("diluent_volume_ul"),
            "total_volume_ul": s.get("total_volume_ul"),
        }
        for s in raw_steps
    ]
    payload = {
        "project_id": _project_id(project),
        "revision": _revision(project),
        "steps": safe_steps,
    }
    literal = pformat(payload, width=88, sort_dicts=False)
    code = (
        '"""Logical liquid-handling preview (no hardware control, stdlib only)."""\n'
        "PLAN = " + literal + "\n"
        "def main():\n"
        "    print('Project %s revision %s logical preview' % (PLAN['project_id'], "
        "PLAN['revision']))\n"
        "    if not PLAN['steps']:\n"
        "        print('No preparation steps in this snapshot.')\n"
        "        return\n"
        "    for item in PLAN['steps']:\n"
        "        print('Target %(target)s: pipette %(stock)s uL stock + %(diluent)s uL "
        "diluent = %(total)s uL'\n"
        "              % {'target': item['target'], 'stock': item['stock_volume_ul'],\n"
        "                 'diluent': item['diluent_volume_ul'], 'total': "
        "item['total_volume_ul']})\n"
        "        print('  tip: pick up tip; waste: eject tip to waste container (logical "
        "event only)')\n"
        "    print('Manual cold transfer only; no mixing or pipetting validation claimed.')\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )
    return code.encode("utf-8")


def build_readme(project: dict) -> bytes:
    if project.get("design", {}).get("platform"):
        return (
            "# Assembled-platform setup proposal\n\n"
            f"Project {_project_id(project)} revision {_revision(project)}.\n\n"
            "The OT-2 is purchased assembled. This package proposes labware slot assignments "
            "and purchase/setup guidance; it is not a fabrication-ready robot. The STEP, "
            "STL and editable script represent schematic reference geometry, not vendor CAD. "
            "Do not fabricate the purchased frame or deck from these proxies.\n\n"
            "Open assembly-guide.html, purchase-and-assembly.md and engineering-guidance.json. "
            "bill-of-materials.csv is an unpriced quotation checklist, not a custom motor BOM. "
            "Verify compatible pipettes, labware and tips, installation space, actual quote, "
            "stock/delivery and manufacturer calibration.\n\n"
            "simulation/result.json records not_run: no OT-2 control/dynamics adapter "
            "is installed. "
            "The logical preview is not an executable laboratory protocol.\n\n"
            "The pinned Apache-2.0 software deck definition and its license/provenance are "
            "in references/. Coordinates are deck-relative; absolute deck height and "
            "internal shapes are illustrative. No physical validation is claimed.\n"
        ).encode("utf8")
    text = (
        "# Concept project files\n\n"
        f"Project {_project_id(project)} revision {_revision(project)} — concept only.\n\n"
        "## How to open\n\n"
        "- Open assembly-guide.html in a browser and print it to PDF if needed.\n"
        "- assembly.json lists the assembly steps; bill-of-materials.csv holds selected options\n"
        "  (blank prices are unknown, never zero); preparation.csv holds per-target volumes.\n"
        "- extensions.md and extension-plan.json describe this revision's extension status.\n\n"
        "- Open cad/workstation.step in a STEP-compatible CAD viewer (millimetres, Z up).\n"
        "  cad/deck.step and cad/deck.stl contain a solid blank, without mounts or holes.\n"
        "- cad/geometry-report.json records shared primitive geometry, measured bounds, validity\n"
        "  and open interfaces. Primitive-sum volumes are not material mass estimates.\n"
        "  cad/workstation.svg is a standalone top-view drawing.\n"
        "- project.json preserves the confirmed input snapshot; manifest.json records its hash\n"
        "  and the SHA-256 of each other file. Use Save project in the app for a portable "
        "file accepted by Open project; this package snapshot is for inspection.\n"
        "- To regenerate CAD, use the MuseAutoLab README's locked Python .venv\n"
        "  (build123d==0.13.0) and run `python cad/deck-model.py`. Outputs are written "
        "beside it.\n\n"
        "## Physical motion model\n\n"
        "- simulation/result.json contains the nominal MuJoCo result for this revision.\n"
        "  A blocked/failed result does not establish a successful operating cycle.\n"
        "- Read simulation/README.md and run `python simulation/run.py` with the locked\n"
        "  .venv (mujoco==3.17.0) to rerun the packaged inputs. No hardware is operated.\n"
        "- Detailed concept shapes are checked inside their declared envelopes; contact tests\n"
        "  still use envelopes, without resolving fine bores, vents or cutouts.\n"
        "- The model assumes rigid guides, masses, force limits and contact proxies;\n"
        "  station actions are logical holds above containers, without liquid simulation.\n\n"
        "## Logical preview\n\n"
        "- Run `python automation/preview.py` with a standard Python 3 interpreter (no "
        "dependencies).\n"
        "- The script prints stock, diluent, tip, and waste logical events only; it does not\n"
        "  operate hardware and does not claim mixing or pipetting validation.\n\n"
        "## Limitations\n\n"
        "- Custom deck is a solid blank for review, not fabrication-ready.\n"
        "- Rack holes and clamp details are concept assumptions, not verified labware fits.\n"
        "  The sample insert pattern follows the number of targets; validate before fabrication.\n"
        "- Rails, mounts, pipette actuation, power, wiring, and firmware are unverified.\n"
        "- Cold target is a requested setting with manual transfer, never a measured result.\n"
    )
    engineering = project.get("engineering_design")
    if engineering:
        provenance = engineering["provenance"]
        proposal = engineering["proposal"]
        text += (
            "\n## Meta layout provenance\n\n"
            f"Model: {provenance.get('model', 'not recorded')}.\n\n"
            f"{proposal['rationale']}\n\n"
            "The operating-deck dimensions and five component positions were proposed by "
            "the model, screened by deterministic geometry checks, and compiled into this "
            "revision. Read project.json -> project.engineering_design for the accepted "
            "proposal, model identity and recorded checks. These checks do not establish "
            "mechanical, thermal or liquid-handling performance.\n"
        )
    if project.get("inspection_extension"):
        text += (
            "\n## Inspection extension\n\n"
            "The actual CAD includes the digital arm/camera concept and sidecar mount. "
            "inspection-module.json preserves its accepted proposal, source revision, "
            "model record, checks, attachment and four kinematic poses; "
            "inspection-poses.csv lists those poses. All added hardware remains unpriced. "
            "The MuJoCo result covers liquid_preparation_only and excludes arm/camera dynamics, "
            "collisions and coverage. No physical mounting, calibration or control is claimed.\n"
        )
    basis = project.get("design_basis")
    if basis:
        text += (
            "\n## Reviewed design foundations\n\n"
            "Component bindings, primary URLs, dates, pinned project revisions and licenses "
            "are in project.json and cad/geometry-report.json under design_basis. "
            "Manufacturer envelopes cover only explicitly bound shapes; the frame, racks, "
            "pipette mechanism, arm and mounts remain custom concepts. Jubilee and Science "
            "Jubilee are documented alternative foundations, not this machine's imported CAD.\n"
        )
    if project.get("design", {}).get("foundation"):
        start = text.index("## Physical motion model")
        end = text.index("\n## ", start + 4)
        text = text[:start] + (
            "## Physical motion model\n\n"
            "simulation/result.json records not_run: the imported Jubilee platform has no "
            "physical simulation adapter. The legacy XYZ result cannot validate this assembly.\n"
        ) + text[end:]
        text += (
            "\n## Imported Jubilee CAD\n\n"
            "The original pinned STEP is included losslessly in cad/source with its license "
            "and provenance. The workstation STEP retains this assembly, lowers only its "
            "build_plate_assembly by the accepted proposal, and adds custom parts. "
            "The frame is not rescaled. The viewer mesh is approximate; original STEP is "
            "the authority. cad/workstation.svg shows custom parts only. Mounting, connections, "
            "travel and all source/custom collisions remain unverified.\n"
        )
        text = text.replace(
            "Manufacturer envelopes cover only explicitly bound shapes; the frame, racks, "
            "pipette mechanism, arm and mounts remain custom concepts. Jubilee and Science "
            "Jubilee are documented alternative foundations, not this machine's imported CAD.",
            "Jubilee is the imported source platform. The insert, pipette, racks, arm and mounts "
            "are custom concepts; Science Jubilee controls are not installed.")
    if project.get("labware_rack"):
        rack = project["labware_rack"]
        text = text.replace(
            "- Rack holes and clamp details are concept assumptions, not verified labware fits.\n"
            "  The sample insert pattern follows the number of targets; "
            "validate before fabrication.\n",
            "- The sample rack is parametrically compiled from declared tube dimensions and "
            "assumed FDM tolerances.\n"
            "  Its capacity and hole pattern follow the rack count/columns, independently of "
            "preparation target count.\n"
            "  Physical fit, strength and deck retention remain unverified; the original "
            "source rack and imported frame are unchanged.\n")
        text += (
            "\n## Parametric tube rack\n\n"
            f"One custom rim-supported rack, {rack['derived']['count']} positions in "
            f"{rack['derived']['rows']} rows and {rack['derived']['columns']} columns. "
            "Tube measurements are user-declared, not manufacturer specifications or "
            "recorded physical fit results.\n\n"
            "Rack-only files: cad/tube-rack.step and cad/tube-rack.stl. Rotate the rack "
            "top-plate-down in the slicer; the engineering export is upright. "
            "Print cad/tube-rack-fit-coupon.stl before the complete rack using the same "
            "material and settings. The flat coupon shares the bore and plate thickness; "
            "cad/tube-rack-fit-coupon.step is also included.\n\n"
            "Follow the rack input, print, first-article and placement steps in "
            "assembly-guide.html. Material, printing and rework are unpriced. One rack "
            "requires no assembly fasteners; deck location and retention remain open. "
            "The custom-rack operating animation is unavailable until tool access, "
            "pipette approach and calibration are implemented and verified.\n"
        )
    return text.encode("utf-8")


def build_extension_plan(project: dict) -> bytes:
    cooling = _cooling(project)
    if project.get("inspection_extension"):
        return json.dumps({
            "project_id": _project_id(project), "revision": _revision(project),
            "status": "digital_concept", "installed": False,
            "inspection_extension": project["inspection_extension"],
            "physics_scope": ("not_run_imported_foundation" if project["design"].get("foundation")
                              else "liquid_preparation_only"),
            "cooling_transfer_mode": cooling["transfer_mode"],
        }, indent=2, sort_keys=True).encode("utf-8")
    plan = {
        "project_id": _project_id(project),
        "revision": _revision(project),
        "status": "proposed_only",
        "robot_arm": {
            "installed": False,
            "proposed_mount": "external sidecar region (to be determined)",
            "control_adapter": "proposed standalone motion service with explicit start/stop "
            "interlocks",
            "data_adapter": "proposed job file exchange; no shared state with the "
            "preparation workflow",
            "unchecked": [
                "mount loads",
                "reach",
                "keep-out volumes",
                "power",
                "collision safety",
                "compatibility",
            ],
        },
        "camera": {
            "installed": False,
            "proposed_mount": "upper frame region (to be determined)",
            "control_adapter": "browser still-frame capture/photo upload implemented; "
            "no hardware adapter",
            "data_adapter": "revision-specific inspection jobs and separate image/audit "
            "ZIP implemented",
            "unchecked": [
                "field of view",
                "lighting",
                "mount loads",
                "keep-out volumes",
                "power",
                "compatibility",
            ],
        },
        "cooling_transfer_mode": cooling["transfer_mode"],
        "note": "Not installed features or guaranteed reserved space; all mounts and "
        "interfaces are TBD.",
    }
    return json.dumps(plan, indent=2, sort_keys=True).encode("utf-8")


def build_extensions_md(project: dict) -> bytes:
    cooling = _cooling(project)
    extension = project.get("inspection_extension")
    if extension:
        text = (
            "# Inspection extension — digital concept\n\n"
            f"Project {_project_id(project)} revision {_revision(project)}.\n\n"
            "The accepted two-link arm, front-right sidecar and downward camera are included "
            "in this revision's CAD. No physical installation or control is implemented.\n\n"
            "## Geometry and provenance\n\n"
            "Read inspection-module.json for dimensions, attachment, model proposal and checks; "
            "inspection-poses.csv lists the four kinematic targets. The underlying workstation "
            "components retain their original IDs and geometry.\n\n"
            "## Image evidence and simulation\n\n"
            "The sweep is a geometric illustration, not a camera acquisition. Browser photo "
            "capture/upload, Meta analysis and human review are separate actions. MuJoCo "
            "covers liquid_preparation_only; the extension is excluded.\n\n"
            "## Open design items\n\n"
            + "\n".join(f"- {v}" for v in extension["limitations"]) + "\n"
        )
        return text.encode("utf-8")
    text = (
        "# Future extensions (proposed, not installed)\n\n"
        f"Project {_project_id(project)} revision {_revision(project)}.\n\n"
        "The robot arm and camera are **not installed** and no physical space is reserved.\n"
        "Proposed mount regions only: arm as an external sidecar; camera on the upper frame.\n\n"
        "## Proposed software boundaries\n\n"
        "- Arm: standalone motion service with explicit start/stop interlocks; job files "
        "exchanged\n"
        "  with the preparation workflow, no shared mutable state.\n"
        "- Camera: browser capture/upload and human-reviewed image inspection are implemented.\n"
        "  Inspection images/audits are downloaded separately, not included in this CAD package.\n"
        "  Step-linked capture, metric calibration and hardware mounting remain proposed.\n\n"
        "## Unchecked mechanical and electrical requirements\n\n"
        "- Mount loads, reach, keep-out volumes, field of view, lighting, power, collision "
        "safety,\n"
        "  and compatibility are all to be determined.\n"
        "- No arm geometry, load ratings, or wiring is claimed here.\n\n"
        f"Current cold workflow remains manual transfer (cooling enabled: {cooling['enabled']}).\n"
    )
    return text.encode("utf-8")


def build_document_files(project: dict, procurement: dict | None = None) -> dict[str, bytes]:
    """Build all standalone document bytes for the snapshot."""
    from app.instructions import build_instruction_files

    files: dict[str, bytes] = {
        **build_instruction_files(project, procurement),
        "bill-of-materials.csv": build_bom_csv(project),
        "preparation.csv": build_preparation_csv(project),
        "automation/preview.py": build_preview_source(project),
        "README.md": build_readme(project),
        "extension-plan.json": build_extension_plan(project),
        "extensions.md": build_extensions_md(project),
    }
    report = procurement if procurement is not None else project.get("procurement_report")
    if report:
        from app.procurement import report_csv, report_json

        files["bill-of-materials.csv"] = report_csv(report)
        files["procurement-report.json"] = report_json(report)
        files["README.md"] = files["README.md"].replace(
            b"bill-of-materials.csv is an unpriced quotation checklist, not a custom motor BOM.",
            b"bill-of-materials.csv is the bound US procurement snapshot, not a custom motor BOM.")
        files["README.md"] += (
            "\n## Bound procurement report\n\n"
            f"Report {report['report_id']} belongs to this project revision. "
            "bill-of-materials.csv and procurement-report.json preserve its current prices, "
            "quantities, source URLs, dates, gaps and stale/unavailable statuses. "
            "The known subtotal is partial, excludes unresolved items, and is not a "
            "complete machine quotation. Commercial offers do not replace accepted geometry.\n"
        ).encode("utf-8")
    extension = project.get("inspection_extension")
    if extension:
        files["inspection-module.json"] = json.dumps({
            "project_id": _project_id(project), "revision": _revision(project),
            "module": extension,
        }, indent=2, sort_keys=True).encode("utf-8")
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(["time_s", "shoulder_deg", "elbow_deg", "camera_x_mm", "camera_y_mm",
                         "camera_z_mm", "target_x_mm", "target_y_mm", "target_z_mm"])
        for frame in extension["pose_frames"]:
            angles = frame["joint_angles_deg"]
            writer.writerow([frame["time_s"], angles["shoulder"], angles["elbow"],
                             *frame["camera_mm"], *frame["target_mm"]])
        files["inspection-poses.csv"] = buffer.getvalue().encode("utf-8")
    from app.platform_profiles import engineering_guidance

    guidance = engineering_guidance(project)
    if guidance["steps"]:
        files["engineering-guidance.json"] = json.dumps(guidance, indent=2).encode("utf8")
        lines = ["# Purchase and assembly plan", "", guidance["message"], ""]
        for step in guidance["steps"]:
            lines.extend([f"## {step['title']}", "", step["detail"], "", step["url"], ""])
        files["purchase-and-assembly.md"] = "\n".join(lines).encode("utf8")
    if project.get("design", {}).get("platform"):
        from pathlib import Path

        directory = Path(__file__).parent / "data" / "ot2"
        for filename in ("deck.json", "LICENSE.txt", "provenance.json"):
            files[f"references/ot2-{filename}"] = (directory / filename).read_bytes()
        files["extensions.md"] = (b"# Integration scope\n\nCustom inspection/cooling "
            b"integration on the assembled platform is not implemented. Discuss requirements "
            b"in chat; no compatible mount or hardware control is claimed.\n")
    return files
