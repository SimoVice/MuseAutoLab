"""Revision-bound procurement snapshots, separate from accepted project designs.

Catalog access is explicit. Opening, rendering, saving and exporting a project
never cause supplier requests. Prices exclude shipping, tax and engineering work.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import math
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

import httpx

from app.supplier_catalogs import PRODUCTS, CatalogError, fetch_product

CACHE_TTL_SECONDS = 900
MAX_PARALLEL_SUPPLIERS = 3
_cache: dict[str, dict] = {}


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _amount(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _sum(rows: list[dict], key: str) -> float:
    return _amount(sum((Decimal(str(r[key])) for r in rows if r.get(key) is not None), Decimal(0)))


def _recount(report: dict) -> None:
    rows = report["rows"]
    fresh = sum(row["line_total"] is not None and row["freshness"] == "fresh" for row in rows)
    stale = sum(row.get("last_known_line_total") is not None for row in rows)
    report["coverage"] = {
        "row_count": len(rows),
        "fresh_priced_count": fresh,
        "stale_priced_count": stale,
        "unpriced_count": len(rows) - fresh - stale,
        "supported_catalog_count": sum(row.get("catalog_supported", False) for row in rows),
    }
    report["known_partial_subtotal"] = _sum(rows, "line_total")
    report["stale_last_known_subtotal"] = _sum(rows, "last_known_line_total")
    report["incomplete"] = True


def report_for_project(project: dict, report: dict | None, *, now: datetime | None = None):
    """Return a detached, time-aware view, or None for another revision.

    report_id identifies the fetched facts; freshness is evaluated at read time.
    Expired observations remain explicitly last-known, never a fresh subtotal.
    """
    if not report or (report["project_id"], report["project_revision"]) != (
        project["id"],
        project["revision"],
    ):
        return None
    result = deepcopy(report)
    at = now or _now()
    result["is_expired"] = at >= _date(result["expires_at"])
    for row in result["rows"]:
        if row["freshness"] != "fresh" or not row.get("fetched_at"):
            continue
        if at < _date(row["fetched_at"]) + timedelta(seconds=CACHE_TTL_SECONDS):
            continue
        row["freshness"] = "stale"
        row["last_known_price"] = row["unit_price"]
        row["last_known_fetched_at"] = row["fetched_at"]
        row["last_known_line_total"] = row["line_total"]
        row["unit_price"] = None
        row["line_total"] = None
        row["issue"] = (
            "The supplier observation expired; refresh before using it as a current price."
        )
    _recount(result)
    return result


def project_with_report(project: dict, report: dict | None) -> dict:
    result = deepcopy(project)
    bound = report_for_project(project, report)
    if bound is not None:
        result["procurement_report"] = bound
    return result


def procurement_groups(project: dict) -> list[dict]:
    """Use the accepted route's selected groups, never the legacy template BOM."""
    groups = deepcopy(project.get("sourcing", {}).get("groups", []))
    if any(
        group["id"] == "upstream-platform" and group["selected_id"] == "source-cad"
        for group in groups
    ):
        from app.jubilee_procurement import upstream_candidate_groups

        groups.extend(upstream_candidate_groups())
    return groups


def _row(group: dict) -> dict:
    selected = next(o for o in group["options"] if o["id"] == group["selected_id"])
    quantity = group["quantity"]
    if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 100_000:
        raise ValueError("Procurement requires a positive bounded integer quantity.")
    product = PRODUCTS.get(selected["id"])
    # A matching option id alone does not authorize a URL or different SKU/supplier.
    supported = bool(
        product
        and selected.get("sku") == product.sku
        and selected.get("source_url") == product.url
        and selected.get("supplier") == product.supplier
    )
    status = "missing"
    issue = "Specify the exact hardware, fabrication/materials and supplier before pricing."
    if selected["id"] == "quote-required" or selected.get("price_kind") in {
        "starting_at",
        "configuration_needed",
    }:
        status = "quote_needed"
        issue = (
            "Request an official US configuration and quotation; a starting price is not a quote."
        )
    elif selected["id"] == "source-cad":
        status = "missing"
        issue = (
            "Digital CAD is not hardware. Remaining upstream parts beyond the candidate "
            "kits below are unpriced; this group is not a second whole-platform purchase."
        )
    elif selected.get("sku") and not supported:
        status = "unsupported"
        issue = "This exact supplier item has no reviewed live catalog adapter."
    fallback = None
    if selected.get("unit_price") is not None:
        fallback = {
            "unit_price": selected["unit_price"],
            "currency": "USD",
            "checked_on": selected.get("checked_on"),
            "source_url": selected.get("source_url"),
            "status": "dated_curated_fallback",
            "excluded_from_subtotal": True,
        }
    return {
        "group_id": group["id"],
        "label": selected["label"],
        "component_ids": list(group.get("component_ids", [])),
        "selected_id": selected["id"],
        "supplier": selected.get("supplier"),
        "sku": selected.get("sku"),
        "quantity": quantity,
        "currency": "USD",
        "pack_size": product.pack_size if supported else 1,
        "pack_count": math.ceil(quantity / product.pack_size) if supported else quantity,
        "unit_price": None,
        "pack_price": None,
        "line_total": None,
        "status": status,
        "freshness": "unverified",
        "availability": "unknown",
        "price_source_url": selected.get("source_url"),
        "availability_source_url": None,
        "fetched_at": None,
        "last_known_price": None,
        "last_known_fetched_at": None,
        "last_known_line_total": None,
        "issue": issue,
        "dated_fallback": fallback,
        "catalog_supported": supported,
        "compatibility_note": selected.get("compatibility_note"),
        "parent_group_id": group.get("parent_group_id"),
        "is_candidate": group.get("is_candidate", False),
        "source_bom_url": group.get("source_bom_url"),
        "source_bom_row": group.get("source_bom_row"),
        "source_project_revision": group.get("source_project_revision"),
    }


def _apply_observation(row: dict, observation: dict, *, stale: bool, issue: str | None) -> None:
    packs = row["pack_count"]
    eligible = [tier for tier in observation["price_breaks"] if tier["minimum_packs"] <= packs]
    pack_price = Decimal(eligible[-1]["pack_price"])
    unit_price = pack_price / row["pack_size"]
    unavailable = observation["availability"] in {"OutOfStock", "SoldOut", "Discontinued"}
    line_total = None if unavailable else _amount(pack_price * packs)
    row.update(
        product_name=observation["product_name"],
        availability=observation["availability"],
        price_source_url=observation["source_url"],
        availability_source_url=observation["source_url"],
        fetched_at=observation["fetched_at"],
        evidence_sha256=observation["evidence_sha256"],
        parser=observation["parser"],
        price_breaks=deepcopy(observation["price_breaks"]),
        status="unavailable" if unavailable else "priced",
        freshness="stale" if stale else "fresh",
        issue=issue,
        pack_price=_amount(pack_price),
    )
    if unavailable and issue is None:
        row["issue"] = "Supplier lists this item as unavailable; its listed price is excluded."
    if stale:
        row.update(
            last_known_price=_amount(unit_price),
            last_known_fetched_at=observation["fetched_at"],
            last_known_line_total=line_total,
        )
        row["pack_price"] = None
    else:
        row.update(unit_price=_amount(unit_price), line_total=line_total)
    if observation.get("variant_id"):
        row["variant_id"] = observation["variant_id"]
        row["variant_title"] = observation["variant_title"]


async def refresh_procurement(project: dict, *, client: httpx.AsyncClient | None = None) -> dict:
    """Refresh selected registered products; failed pages retain stale prior facts.

    The short process-local cache avoids hammering suppliers on repeated clicks.
    Cache entries record original fetch time; cache hits never pretend a new fetch.
    """
    now = _now()
    rows = [_row(group) for group in procurement_groups(project)]
    semaphore = asyncio.Semaphore(MAX_PARALLEL_SUPPLIERS)

    async def retrieve(row: dict, active_client: httpx.AsyncClient):
        if not row["catalog_supported"]:
            return
        key = row["selected_id"]
        prior = _cache.get(key)
        if prior and now < _date(prior["fetched_at"]) + timedelta(seconds=CACHE_TTL_SECONDS):
            _apply_observation(row, prior, stale=False, issue=None)
            row["cache_hit"] = True
            return
        async with semaphore:
            try:
                observation = await fetch_product(PRODUCTS[key], active_client)
            except CatalogError as exc:
                row["status"] = "missing"
                row["issue"] = str(exc)
                if prior:
                    _apply_observation(row, prior, stale=True, issue=str(exc))
                return
            observation["fetched_at"] = _iso(_now())
            _cache[key] = deepcopy(observation)
            _apply_observation(row, observation, stale=False, issue=None)
            row["cache_hit"] = False

    async def run(active_client: httpx.AsyncClient):
        await asyncio.gather(*(retrieve(row, active_client) for row in rows))

    if client is not None:
        await run(client)
    else:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10, connect=5),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=MAX_PARALLEL_SUPPLIERS),
            headers={
                "User-Agent": "MuseAutoLab/0.1 (read-only US product price check)",
                "Accept": "text/html",
            },
        ) as active_client:
            await run(active_client)
    fresh_expiry = [
        _date(row["fetched_at"]) + timedelta(seconds=CACHE_TTL_SECONDS)
        for row in rows
        if row["freshness"] == "fresh"
    ]
    report = {
        "schema_version": 1,
        "report_id": str(uuid4()),
        "project_id": project["id"],
        "project_revision": project["revision"],
        "market": "US",
        "currency": "USD",
        "fetched_at": _iso(now),
        "expires_at": _iso(min(fresh_expiry, default=now)),
        "is_expired": not bool(fresh_expiry),
        "rows": rows,
        "scope": "Selected project procurement groups and a partial, non-overlapping set of "
        "source-linked Jubilee candidate kits. Candidate fit and remaining BOM require review.",
        "exclusions": [
            "Shipping, sales tax, duties and delivery times are not included.",
            "Custom fabrication, assembly, validation, support and unspecified parts are unpriced.",
            "Dated curated fallback prices and stale observations are excluded "
            "from the fresh subtotal.",
            "Unavailable items are excluded; a listed price does not guarantee "
            "stock or compatibility.",
            "Coverage counts procurement groups, not every upstream physical part "
            "or a complete machine BOM.",
        ],
    }
    _recount(report)
    return report


def report_json(report: dict) -> bytes:
    return json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8")


def report_csv(report: dict) -> bytes:
    buffer = io.StringIO(newline="")
    columns = [
        "report_id",
        "project_id",
        "project_revision",
        "market",
        "currency",
        "group_id",
        "component_ids",
        "selected_id",
        "label",
        "supplier",
        "sku",
        "quantity",
        "pack_size",
        "pack_count",
        "pack_price",
        "unit_price",
        "line_total",
        "status",
        "freshness",
        "availability",
        "price_source_url",
        "availability_source_url",
        "fetched_at",
        "last_known_price",
        "last_known_line_total",
        "last_known_fetched_at",
        "issue",
        "is_candidate",
        "compatibility_note",
        "parent_group_id",
        "source_bom_url",
        "source_bom_row",
        "source_project_revision",
        "variant_id",
        "variant_title",
        "evidence_sha256",
        "parser",
    ]
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in report["rows"]:
        record = {key: report[key] for key in columns[:5]}
        record.update(row)
        record["component_ids"] = ";".join(row["component_ids"])
        # Avoid treating any supplier-controlled field as a spreadsheet formula.
        record = {
            key: (
                "'" + value
                if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r"))
                else value
            )
            for key, value in record.items()
        }
        writer.writerow(record)
    return buffer.getvalue().encode("utf-8")
