"""Concept assembly sequence and document exports (concept only, no hardware validation)."""

from __future__ import annotations

import csv
import html
import io
import json
from pprint import pformat

CHECKED_LABEL = "not recorded"

STEP_DEFS = [
    {
        "id": "design-review",
        "title": "Stage 1 — Design review and concept gate",
        "component_ids": [],
        "requires_design": False,
    },
    {
        "id": "frame",
        "title": "Stage 2 — Frame and custom deck",
        "component_ids": ["base", "column-left", "column-right", "crossbar"],
        "requires_design": True,
    },
    {
        "id": "motion-pipette",
        "title": "Stage 3 — Motion axes and pipette mount",
        "component_ids": ["carriage", "crossbar", "pipette"],
        "requires_design": True,
    },
    {
        "id": "racks",
        "title": "Stage 4 — Racks and waste containers",
        "component_ids": ["source-rack", "sample-rack", "tip-rack", "tip-waste"],
        "requires_design": True,
    },
    {
        "id": "controller",
        "title": "Stage 5 — Controller integration",
        "component_ids": ["controller"],
        "requires_design": True,
    },
    {
        "id": "cold-bay",
        "title": "Stage 6 — Optional refrigerated bay (only when cooling is enabled)",
        "component_ids": ["cold-storage"],
        "requires_design": True,
        "conditional": True,
    },
    {
        "id": "checks",
        "title": "Stage 7 — Checks before operation",
        "component_ids": [],
        "requires_design": False,
    },
]


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


def assembly_steps(project: dict) -> list[dict]:
    """Return the proposed concept assembly sequence for the snapshot."""
    index = _comp_index(project)
    cooling = _cooling(project)
    fp = _footprint(project)
    sourcing = project.get("sourcing") or {}
    checked = str(sourcing.get("checked_on", CHECKED_LABEL))
    currency = str(sourcing.get("currency", "USD"))
    subtotal = sourcing.get("subtotal")
    subtotal_text = f"{float(subtotal):.2f} {currency}" if subtotal is not None else "unknown"
    width_text = str(fp.get("width_mm")) if fp.get("width_mm") is not None else "undecided"
    variant = cooling["variant_id"] or "none selected"
    target = cooling["target_c"]
    target_text = (
        f"{target} C ({cooling['target_source']})" if target is not None else "no target set"
    )

    def existing(ids: list[str]) -> list[str]:
        return [i for i in ids if i in index]

    steps: list[dict] = []
    for spec in STEP_DEFS:
        if spec.get("conditional") and not cooling["enabled"]:
            continue
        sid = spec["id"]
        comp_ids = existing(list(spec["component_ids"]))
        # Cold bay: only keep when the component exists; otherwise keep empty list
        # so the conditional step is still visible when cooling is enabled.
        if sid == "design-review":
            steps.append(
                {
                    "id": sid,
                    "title": spec["title"],
                    "component_ids": [],
                    "instructions": [
                        f"Confirm project {_project_id(project)} revision "
                        f"{_revision(project)} before handling parts.",
                        "Cross-check selected variants and quantities in bill-of-materials.csv.",
                        f"Known subtotal {subtotal_text}; unpriced groups remain excluded. "
                        f"Sources checked {checked}.",
                        f"Footprint {fp.get('width_mm')} x {fp.get('depth_mm')} x "
                        f"{fp.get('height_mm')} mm; width requirement {width_text} mm.",
                        "Treat rails, mounts, pipette actuation, and electronics as open "
                        "design items; do not proceed past this gate with assumed interfaces.",
                    ],
                    "checks": [
                        "Dilution plan status and workspace width requirement reviewed.",
                        "Open mechanical and electronic interfaces acknowledged.",
                    ],
                    "requires_design": False,
                }
            )
        elif sid == "frame":
            steps.append(
                {
                    "id": sid,
                    "title": spec["title"],
                    "component_ids": comp_ids,
                    "instructions": [
                        "Place the custom deck blank on a level surface and position the "
                        "frame posts and crossbar per the concept envelopes.",
                        "Design gate: rail spans, post mounts, and deck fixation are not "
                        "specified; no bolt sizes or torque values are given.",
                    ],
                    "checks": [
                        "Frame parts match the concept envelopes.",
                        "Custom mounts flagged as still to design.",
                    ],
                    "requires_design": True,
                }
            )
        elif sid == "motion-pipette":
            steps.append(
                {
                    "id": sid,
                    "title": spec["title"],
                    "component_ids": comp_ids,
                    "instructions": [
                        "Offer up the carriage and pipette concept to the crossbar region to "
                        "review clearances.",
                        "Design gate: linear rails, transmission, pipette mounts, and tip "
                        "handling are custom and unverified; travel and collisions are not "
                        "established.",
                    ],
                    "checks": [
                        "Carriage and pipette envelopes reviewed.",
                        "Motion design left open; nothing is claimed as validated.",
                    ],
                    "requires_design": True,
                }
            )
        elif sid == "racks":
            steps.append(
                {
                    "id": sid,
                    "title": spec["title"],
                    "component_ids": comp_ids,
                    "instructions": [
                        "Place source, sample, and tip racks and the waste container on the "
                        "deck in the concept positions.",
                        "Printed fixtures and labware are custom; positions are illustrative only.",
                    ],
                    "checks": [
                        "Rack envelopes sit within the deck area.",
                        "Labware fit still to verify.",
                    ],
                    "requires_design": True,
                }
            )
        elif sid == "controller":
            steps.append(
                {
                    "id": sid,
                    "title": spec["title"],
                    "component_ids": comp_ids,
                    "instructions": [
                        "Place the controller enclosure concept in its shown position and "
                        "plan cable routing at concept level.",
                        "Design gate: carrier board, firmware, power, and wiring protection "
                        "are not specified; no pinouts are given.",
                    ],
                    "checks": [
                        "Controller envelope reviewed.",
                        "Electronics integration left open.",
                    ],
                    "requires_design": True,
                }
            )
        elif sid == "cold-bay":
            steps.append(
                {
                    "id": sid,
                    "title": spec["title"],
                    "component_ids": comp_ids,
                    "instructions": [
                        f"Attach the refrigerated bay concept (variant {variant}); requested "
                        f"target {target_text} with manual sample transfer.",
                        "Design gate: enclosure, insulation, power, condensation, and "
                        "ventilation are assumed and unverified; target is a requested "
                        "setting, never a measured temperature.",
                    ],
                    "checks": [
                        "Cold bay envelope reviewed.",
                        "Manual transfer workflow acknowledged.",
                    ],
                    "requires_design": True,
                }
            )
        elif sid == "checks":
            steps.append(
                {
                    "id": sid,
                    "title": spec["title"],
                    "component_ids": [],
                    "instructions": [
                        "Re-check the full concept: footprint, rack layout, manual cold "
                        "transfer, and cost scope with unknowns.",
                        "Run automation/preview.py to review the logical liquid-handling "
                        "trace (no hardware control).",
                        "Do not operate hardware from this concept sequence; mechanical and "
                        "electronic interfaces are unverified.",
                    ],
                    "checks": ["All open interfaces listed.", "Preview trace reviewed."],
                    "requires_design": False,
                }
            )
    for step in steps:
        step["title"] = step["title"].split(" — ", 1)[-1]
    return steps


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
    scale = min(500 / (max_x - min_x), 420 / (max_z - min_z))
    offset_x = (500 - (max_x - min_x) * scale) / 2
    offset_y = (420 - (max_z - min_z) * scale) / 2
    parts = [
        '<svg viewBox="0 0 760 420" role="img" aria-label="Numbered top view of deck envelopes">'
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


def build_guide_html(project: dict, steps: list[dict]) -> bytes:
    pid = html.escape(_project_id(project))
    rev = _revision(project)
    fp = _footprint(project)
    cooling = _cooling(project)
    sourcing = project.get("sourcing") or {}
    checked = html.escape(str(sourcing.get("checked_on", CHECKED_LABEL)))
    limitations = [
        "Concept sequence only; mechanical, thermal, and electronic interfaces are unverified.",
        "Custom deck is a solid blank for review, not fabrication-ready; no drill patterns "
        "or mounts are specified.",
        "No fastener sizes, torque values, wiring pinouts, or calibration steps are given.",
        "Cold target is a requested setting with manual transfer, never a measured temperature.",
    ]
    comp_rows = []
    for comp in _components(project):
        comp_rows.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                html.escape(str(comp.get("id", ""))),
                html.escape(str(comp.get("label", ""))),
                html.escape(str(comp.get("position", ""))),
                html.escape(str(comp.get("size", ""))),
            )
        )
    step_sections = []
    for number, step in enumerate(steps, start=1):
        comp_list = ", ".join(html.escape(str(c)) for c in step.get("component_ids", [])) or "none"
        instructions = "".join(
            f"<li>{html.escape(str(t))}</li>" for t in step.get("instructions", [])
        )
        checks = "".join(f"<li>{html.escape(str(t))}</li>" for t in step.get("checks", []))
        gate = "Open design items remain." if step.get("requires_design") else "Review gate."
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
            )
        )
    target_text = html.escape(str(cooling["target_c"]))
    page = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Assembly guide — PROJECT_ID rREV</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;background:#f4f8f7;color:#1d3330;
margin:0;line-height:1.65}
header{background:#103f45;color:#fff;padding:40px max(24px,calc((100vw - 900px)/2))}
h1{font-family:Georgia,serif;font-size:38px;font-weight:400;line-height:1.15;margin:0 0 12px}
header p{margin:0;font-size:12px;color:#c1dcd6;overflow-wrap:anywhere}
h2{font-size:21px;letter-spacing:-.02em}h3{font-size:20px;color:#115d60}
h4{font-size:12px;text-transform:uppercase;letter-spacing:.08em}
main{max-width:900px;margin:0 auto;padding:24px}
.card,.step{background:#fff;border:1px solid #d3e3df;border-radius:12px;padding:24px;margin:20px 0}
.step{break-inside:avoid}.meta{font-size:12px;color:#5b7775}
svg{display:block;max-width:740px;width:100%;height:auto;margin:20px auto;
background:#f2f8f6;border:1px solid #d8e7e1;border-radius:8px}
li+li{margin-top:6px}.checks{border-left:3px solid #71b4a6;padding-left:28px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border:1px solid #bcd8d3;padding:6px;text-align:left}
th{background:#d7e8e4}
@media print{body{background:white;font-size:10pt}
header{color:#103f45;background:white;border-bottom:2px solid #0f766e;padding:12px}
header p{color:#44635f}main{padding:0}.step{break-before:page;border:none}
svg{max-width:640px}table{font-size:9pt}th,td{overflow-wrap:anywhere}}
</style>
</head>
<body>
<header><h1>Concept assembly guide</h1>
<p>Project PROJECT_ID &middot; revision REV &middot; concept only</p></header>
<main>
<div class="card"><h2>Revision overview</h2>
<p>Concept assembly sequence. Mounts, wiring and hardware performance remain to be engineered.</p>
<p>Footprint FP &middot; cooling COOLING &middot; target TARGET<br>Sources checked CHECKED.</p>
<div>OVERVIEW_SVG</div></div>
<div class="card"><h2>Components (mm, y up)</h2>
<table><tr><th>id</th><th>label</th><th>position</th><th>size</th></tr>ROWS</table></div>
STEPS
<div class="card"><h2>Open engineering items</h2>
<ul><li>LIMITATIONS</li></ul></div>
</main>
</body>
</html>"""
    page = page.replace("PROJECT_ID", pid).replace("rREV", f"r{rev}").replace("REV", str(rev))
    page = page.replace("LIMITATIONS", "</li><li>".join(html.escape(s) for s in limitations))
    page = page.replace(
        "FP", html.escape(f"{fp.get('width_mm')} x {fp.get('depth_mm')} x {fp.get('height_mm')} mm")
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
    text = (
        "# Concept project files\n\n"
        f"Project {_project_id(project)} revision {_revision(project)} — concept only.\n\n"
        "## How to open\n\n"
        "- Open assembly-guide.html in a browser and print it to PDF if needed.\n"
        "- assembly.json lists the assembly steps; bill-of-materials.csv holds selected options\n"
        "  (blank prices are unknown, never zero); preparation.csv holds per-target volumes.\n"
        "- extensions.md and extension-plan.json describe possible future robot arm and "
        "camera work.\n\n"
        "- Open cad/workstation.step in a STEP-compatible CAD viewer (millimetres, Z up).\n"
        "  cad/deck.step and cad/deck.stl contain a solid blank, without mounts or holes.\n"
        "- cad/geometry-report.json records measured envelopes, validity and open interfaces.\n"
        "  cad/workstation.svg is a standalone top-view drawing.\n"
        "- project.json preserves the confirmed input snapshot; manifest.json records its hash\n"
        "  and the SHA-256 of each other file. In-app reopening is not implemented yet.\n"
        "- To regenerate CAD, use the MuseAutoLab README's locked Python .venv\n"
        "  (build123d==0.13.0) and run `python cad/deck-model.py`. Outputs are written "
        "beside it.\n\n"
        "## Physical motion model\n\n"
        "- simulation/result.json contains the nominal MuJoCo result for this revision.\n"
        "  A blocked/failed result does not establish a successful operating cycle.\n"
        "- Read simulation/README.md and run `python simulation/run.py` with the locked\n"
        "  .venv (mujoco==3.17.0) to rerun the packaged inputs. No hardware is operated.\n"
        "- The model assumes rigid guides, masses, force limits and contact proxies;\n"
        "  station actions are logical holds above containers, without liquid simulation.\n\n"
        "## Logical preview\n\n"
        "- Run `python automation/preview.py` with a standard Python 3 interpreter (no "
        "dependencies).\n"
        "- The script prints stock, diluent, tip, and waste logical events only; it does not\n"
        "  operate hardware and does not claim mixing or pipetting validation.\n\n"
        "## Limitations\n\n"
        "- Custom deck is a solid blank for review, not fabrication-ready.\n"
        "- Rails, mounts, pipette actuation, power, wiring, and firmware are unverified.\n"
        "- Cold target is a requested setting with manual transfer, never a measured result.\n"
    )
    return text.encode("utf-8")


def build_extension_plan(project: dict) -> bytes:
    cooling = _cooling(project)
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


def build_document_files(project: dict) -> dict[str, bytes]:
    """Build all standalone document bytes for the snapshot."""
    steps = assembly_steps(project)
    files: dict[str, bytes] = {
        "assembly-guide.html": build_guide_html(project, steps),
        "assembly.json": json.dumps(
            {"project_id": _project_id(project), "revision": _revision(project), "steps": steps},
            indent=2,
            sort_keys=True,
        ).encode("utf-8"),
        "bill-of-materials.csv": build_bom_csv(project),
        "preparation.csv": build_preparation_csv(project),
        "automation/preview.py": build_preview_source(project),
        "README.md": build_readme(project),
        "extension-plan.json": build_extension_plan(project),
        "extensions.md": build_extensions_md(project),
    }
    return files
