"""Render immutable, offline-friendly files from one compiled mechanical assembly."""

import csv
import io
import json
import math
import zipfile
from datetime import UTC, datetime

from app.concept_design import concept_obj, concept_stl
from app.concept_guide import build_concept_guide, concept_controller_source, concept_gateway_config

PRICE_COLUMNS = [
    "Supplier price status",
    "Supplier item USD",
    "Supplier pack USD",
    "Pack size",
    "Packs to buy",
    "Supplier line USD",
    "Supplier checked at",
    "Supplier valid until",
    "Supplier price URL",
    "Model estimate status",
    "Model low USD",
    "Model high USD",
    "Model generated at",
    "Model valid until",
    "Model source",
    "Price scope and exclusions",
    "Price record exported at",
]


def _future(value, now):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.tzinfo is not None and parsed > now
    except (AttributeError, TypeError, ValueError):
        return False


def _money(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        return ""
    return f"{value:.2f}"


def price_record_for_project(
    project: dict, procurement: dict | None = None, estimate: dict | None = None
) -> dict:
    """Read trusted runtime sidecars only; never fetch or read imported project prices.

    Values are dated records, not renewable quotes. Invalid, expired and unmatched
    values are omitted; missing prices are explicit and never written as zero.
    """
    from app.instructions import _safe_url
    from app.price_estimation import estimate_for_project
    from app.procurement import initial_procurement_rows, report_for_project

    now = datetime.now(UTC)
    try:
        report = report_for_project(project, procurement, now=now)
    except (ArithmeticError, KeyError, TypeError, ValueError):
        report = None
    report_current = bool(
        report
        and report.get("currency") == "USD"
        and report.get("market") == "US"
        and _future(report.get("expires_at"), now)
    )
    observed = {row["group_id"]: row for row in report["rows"]} if report else {}
    try:
        ranges = estimate_for_project(project, estimate, report, now=now)
    except (ArithmeticError, KeyError, TypeError, ValueError):
        ranges = None
    ranges_current = bool(
        ranges
        and ranges.get("estimate_id")
        and ranges.get("generated_at")
        and ranges.get("status") not in ("stale", "failed")
        and _future(ranges.get("expires_at"), now)
    )
    modeled = {row["group_id"]: row for row in ranges["rows"]} if ranges else {}
    rows = {}
    identity = (
        "selected_id",
        "supplier",
        "sku",
        "quantity",
        "pack_size",
        "pack_count",
        "price_source_url",
        "component_ids",
    )
    for expected in initial_procurement_rows(project):
        key = expected["group_id"]
        observation = observed.get(key, {})
        value = modeled.get(key, {})
        status = (
            "Unchecked supplier listing"
            if expected.get("catalog_supported")
            else "Missing price; supplier or quotation required"
        )
        if procurement and not report:
            status = "Supplier record does not match this revision; omitted"
        elif observation.get("freshness") == "stale" or (report and not report_current):
            status = "Expired supplier observation omitted"
        elif observation.get("status") == "unavailable":
            status = "Supplier item unavailable; price omitted"
        supplier = ["", "", "", "", "", "", "", ""]
        if (
            report_current
            and observation.get("status") == "priced"
            and observation.get("freshness") == "fresh"
            and observation.get("fetched_at")
            and expected.get("catalog_supported")
            and all(observation.get(field) == expected.get(field) for field in identity)
            and _money(observation.get("line_total"))
            and observation.get("line_total", 0) > 0
        ):
            status = "Dated supplier observation; not a quote"
            supplier = [
                _money(observation.get("unit_price")),
                _money(observation.get("pack_price")),
                observation.get("pack_size"),
                observation.get("pack_count"),
                _money(observation.get("line_total")),
                observation["fetched_at"],
                report["expires_at"],
                _safe_url(observation.get("price_source_url")),
            ]
        model_status = (
            "Expired model estimate omitted"
            if ranges and ranges.get("status") == "stale"
            else "Model estimate unavailable; no valid range"
            if ranges and not ranges_current
            else "Model estimate unavailable for this revision"
            if estimate and not ranges
            else "Not estimated"
        )
        model = ["", "", "", "", ""]
        if ranges_current and value.get("source_kind") == "model_estimate":
            model_status = "Model planning range; not a supplier price"
            model = [
                _money(value.get("low_usd")),
                _money(value.get("high_usd")),
                ranges["generated_at"],
                ranges["expires_at"],
                ranges.get("model") or "Model",
            ]
        rows[key] = [
            status,
            *supplier,
            model_status,
            *model,
            "Line totals and model ranges cover the entire listed quantity. "
            "Excludes shipping, tax, assembly, engineering and validation. "
            "Dated record only; refresh in the application before budgeting.",
            now.isoformat(),
        ]
    return {"project_id": project["id"], "revision": project["revision"], "rows": rows}


def _safe_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def render_asset(
    design: dict, project_id: str, revision: int, asset: str, *, price_record: dict | None = None
) -> tuple[bytes, str]:
    if asset == "project.json":
        data = {"project_id": project_id, "revision": revision, "design": design}
        return json.dumps(data, ensure_ascii=False, indent=2).encode(), "application/json"
    if asset == "parts.csv":
        buf = io.StringIO(newline="")
        writer = csv.writer(buf)
        priced = bool(
            price_record
            and price_record.get("project_id") == project_id
            and price_record.get("revision") == revision
        )
        writer.writerow(
            [
                "Part",
                "Quantity",
                "Unit",
                "Source",
                "Reference URL",
                "Local model",
                "US catalog search",
                *(PRICE_COLUMNS if priced else []),
            ]
        )
        keys = {c["key"] for c in design["components"]}
        for row in design["parts"]:
            writer.writerow(
                [
                    _safe_cell(v)
                    for v in (
                        row["name"],
                        row["quantity"],
                        row["unit"],
                        row.get("source_title"),
                        row.get("source_url"),
                        f"parts/{row['key']}.stl" if row["key"] in keys else "",
                        row.get("catalog_search_url"),
                        *(
                            price_record["rows"].get(
                                "concept-" + row["key"], [""] * len(PRICE_COLUMNS)
                            )
                            if priced
                            else []
                        ),
                    )
                ]
            )
        return buf.getvalue().encode("utf-8-sig"), "text/csv"
    if asset == "guide.html":
        return build_concept_guide(design, project_id, revision), "text/html"
    if asset == "controller.py":
        return concept_controller_source(), "text/x-python"
    if asset == "gateway-config.json":
        return concept_gateway_config(design, project_id, revision), "application/json"
    if asset == "machine.stl":
        return concept_stl(design), "model/stl"
    if asset == "machine.obj":
        return concept_obj(design), "model/obj"
    if asset == "machine.step":
        from app.concept_cad import concept_step

        return concept_step(design), "model/step"
    parts = {f"parts/{part['key']}.stl": part["key"] for part in design["components"]}
    if asset in parts:
        return concept_stl(design, parts[asset]), "model/stl"
    step_parts = {f"parts/{part['key']}.step": part["key"] for part in design["components"]}
    if asset in step_parts:
        from app.concept_cad import concept_step

        return concept_step(design, step_parts[asset]), "model/step"
    if asset == "package.zip":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in (
                "guide.html",
                "project.json",
                "machine.stl",
                "controller.py",
                "gateway-config.json",
                "parts.csv",
                *parts,
            ):
                content, _ = render_asset(
                    design, project_id, revision, name, price_record=price_record
                )
                archive.writestr(name, content)
        return buf.getvalue(), "application/zip"
    raise KeyError(asset)
