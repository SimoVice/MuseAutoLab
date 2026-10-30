"""Offline adversarial supplier observations; not current catalog evidence."""

import asyncio
import csv
import io
import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app import procurement
from app.catalog import build_sourcing
from app.domain import new_project
from app.foundation_design import foundation_sourcing
from app.supplier_catalogs import (
    PRODUCTS,
    CatalogError,
    fetch_product,
    parse_product_page,
)


def page(
    product,
    *,
    price="4.00",
    currency="USD",
    sku=None,
    availability="InStock",
    tiers=None,
    metadata="",
    name="Synthetic supplier item",
    url=None,
):
    value = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": name,
        "sku": sku if sku is not None else product.sku,
        "offers": {
            "@type": "Offer",
            "url": url or product.url,
            "price": price,
            "priceCurrency": currency,
            "availability": f"https://schema.org/{availability}",
        },
    }
    table = ""
    if product.supplier == "Pololu":
        tiers = tiers or [(1, price), (5, "3.80")]
        table = "<table class='pricing'><tr><th>Price break</th><th>Unit price (US$)</th></tr>"
        table += "".join(f"<tr><td>{q}</td><td>{p}</td></tr>" for q, p in tiers) + "</table>"
    return f'<script type="application/ld+json">{json.dumps(value)}</script>{table}{metadata}'


@pytest.fixture(autouse=True)
def clear_cache():
    procurement._cache.clear()
    yield
    procurement._cache.clear()


def only_project(option="pico", quantity=1):
    project = new_project()
    sourcing = build_sourcing({}, True)
    group = next(g for g in sourcing["groups"] if any(o["id"] == option for o in g["options"]))
    group["selected_id"] = option
    group["quantity"] = quantity
    project["sourcing"]["groups"] = [group]
    return project


def refresh(project, handler):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await procurement.refresh_procurement(project, client=client)

    return asyncio.run(run())


def response(product, **kwargs):
    return httpx.Response(200, text=page(product, **kwargs), headers={"content-type": "text/html"})


def test_exact_sku_usd_url_and_metadata_are_required():
    product = PRODUCTS["pico"]
    assert parse_product_page(product, page(product))["sku"] == "4864"
    for kwargs in (
        {"sku": "5525"},
        {"currency": "EUR"},
        {"url": "https://www.adafruit.com/product/5525"},
        {"url": "https://localhost/product/4864"},
        {"metadata": '<meta property="product:price:amount" content="9.99">'},
        {"metadata": '<meta property="product:price:currency" content="CHF">'},
        {"name": "Synthetic item 2-Pack"},
    ):
        with pytest.raises(CatalogError):
            parse_product_page(product, page(product, **kwargs))


@pytest.mark.parametrize("price", ["NaN", "Infinity", "-1", "0", True, "4.0001", "1000001"])
def test_invalid_and_zero_hardware_price_never_becomes_a_cost(price):
    with pytest.raises(CatalogError):
        parse_product_page(PRODUCTS["pico"], page(PRODUCTS["pico"], price=price))


def test_inconsistent_base_price_quantity_tiers_and_duplicate_offers_are_rejected():
    product = PRODUCTS["pololu-1209"]
    for tiers in ([(1, "5.00")], [(1, "4.00"), (1, "3.00")], [(1, "4.00"), (5, "5.00")]):
        with pytest.raises(CatalogError):
            parse_product_page(product, page(product, tiers=tiers))
    original = page(PRODUCTS["pico"])
    with pytest.raises(CatalogError):
        parse_product_page(PRODUCTS["pico"], original + original)


def test_quantity_breaks_and_decimal_totals_use_requested_packs():
    project = only_project("pololu-1209", quantity=7)
    result = refresh(project, lambda request: response(PRODUCTS["pololu-1209"]))
    row = result["rows"][0]
    assert row["pack_count"] == 7
    assert row["unit_price"] == 3.8
    assert row["line_total"] == 26.6
    assert result["known_partial_subtotal"] == 26.6
    assert result["coverage"]["fresh_priced_count"] == 1


def test_reviewed_pack_size_rounds_purchase_quantity_up(monkeypatch):
    product = replace(PRODUCTS["pico"], pack_size=2)
    monkeypatch.setitem(PRODUCTS, "pico", product)
    result = refresh(
        only_project(quantity=3), lambda request: response(product, name="Item 2-Pack")
    )
    row = result["rows"][0]
    assert row["quantity"] == 3 and row["pack_size"] == 2 and row["pack_count"] == 2
    assert row["pack_price"] == 4 and row["unit_price"] == 2 and row["line_total"] == 8


def test_blocked_missing_redirect_and_wrong_mime_do_not_follow_or_invent_prices():
    for code, headers in [
        (403, {}),
        (404, {}),
        (302, {"location": "http://127.0.0.1"}),
        (200, {"content-type": "application/json"}),
    ]:
        calls = []

        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(code, headers=headers, text="unavailable")

        report = refresh(only_project(), handler)
        row = report["rows"][0]
        assert len(calls) == 1 and row["status"] == "missing"
        assert row["unit_price"] is None and row["line_total"] is None
        assert row["dated_fallback"]["unit_price"] == 4
        assert report["known_partial_subtotal"] == 0 and report["incomplete"]


def test_malformed_and_wrong_sku_page_stays_missing():
    for html in ("<html>blocked</html>", page(PRODUCTS["pico"], sku="9999")):
        result = refresh(
            only_project(),
            lambda request: httpx.Response(200, text=html, headers={"content-type": "text/html"}),
        )
        assert result["rows"][0]["status"] == "missing"


def test_unavailable_price_is_visible_but_excluded_from_fresh_subtotal():
    result = refresh(
        only_project(), lambda request: response(PRODUCTS["pico"], availability="OutOfStock")
    )
    row = result["rows"][0]
    assert row["status"] == "unavailable" and row["unit_price"] == 4
    assert row["line_total"] is None and result["known_partial_subtotal"] == 0


def test_failed_expired_refresh_keeps_prior_price_separate_from_current(monkeypatch):
    at = datetime(2026, 10, 30, tzinfo=UTC)
    monkeypatch.setattr(procurement, "_now", lambda: at)
    project = only_project(quantity=3)
    first = refresh(project, lambda request: response(PRODUCTS["pico"]))
    at += timedelta(seconds=procurement.CACHE_TTL_SECONDS + 1)
    failed = refresh(project, lambda request: httpx.Response(403))
    row = failed["rows"][0]
    assert first["report_id"] != failed["report_id"]
    assert row["freshness"] == "stale" and row["unit_price"] is None
    assert row["last_known_price"] == 4 and row["last_known_line_total"] == 12
    assert failed["known_partial_subtotal"] == 0 and failed["stale_last_known_subtotal"] == 12
    assert failed["coverage"] == {
        "row_count": 1,
        "fresh_priced_count": 0,
        "stale_priced_count": 1,
        "unpriced_count": 0,
        "supported_catalog_count": 1,
    }
    assert row["last_known_fetched_at"] == first["rows"][0]["fetched_at"]


def test_cache_hit_keeps_original_fetch_time_and_report_read_never_fetches(monkeypatch):
    calls = []
    project = only_project()

    def handler(request):
        calls.append(request)
        return response(PRODUCTS["pico"])

    first = refresh(project, handler)
    second = refresh(project, handler)
    assert len(calls) == 1 and second["rows"][0]["cache_hit"]
    assert first["rows"][0]["fetched_at"] == second["rows"][0]["fetched_at"]
    at = datetime.fromisoformat(first["expires_at"].replace("Z", "+00:00"))
    view = procurement.report_for_project(project, first, now=at)
    assert view["is_expired"] and view["rows"][0]["freshness"] == "stale"
    assert view["known_partial_subtotal"] == 0 and view["stale_last_known_subtotal"] == 4
    assert first["known_partial_subtotal"] == 4  # Stored facts remain detached.
    updated = deepcopy(project)
    updated["revision"] += 1
    assert procurement.report_for_project(updated, first) is None


def test_registry_identity_cannot_be_overridden_by_project_url():
    project = only_project()
    project["sourcing"]["groups"][0]["options"][0]["source_url"] = "http://127.0.0.1/secret"
    result = refresh(project, lambda request: pytest.fail("Unreviewed URL was fetched"))
    assert result["rows"][0]["status"] == "unsupported"
    assert result["known_partial_subtotal"] == 0


def test_nonregistry_product_fetch_is_rejected_before_http():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: pytest.fail("An arbitrary product URL was fetched")
            )
        ) as client:
            with pytest.raises(CatalogError):
                await fetch_product(replace(PRODUCTS["pico"], url="http://localhost"), client)

    asyncio.run(run())


def test_jubilee_digital_cad_not_zero_cost_hardware_or_legacy_motor_bom():
    project = new_project()
    project["sourcing"] = foundation_sourcing(project)
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(403)

    result = refresh(project, handler)
    assert len(calls) == 6
    assert not any("pololu" in url or "adafruit" in url for url in calls)
    assert not {"motors", "drivers", "controller"}.intersection(
        r["group_id"] for r in result["rows"]
    )
    platform = next(row for row in result["rows"] if row["group_id"] == "upstream-platform")
    assert platform["unit_price"] is None and platform["status"] == "missing"
    assert result["coverage"]["unpriced_count"] == len(result["rows"])


def shopify_page(
    product,
    *,
    currency="USD",
    price=400,
    sku=None,
    variant_id=None,
    variant_title=None,
    available=True,
    product_id=None,
    meta_price="4.00",
):
    obj = {
        "id": product_id or product.product_id,
        "handle": product.url.split("/products/", 1)[1].split("?", 1)[0],
        "title": "Synthetic source-linked kit",
        "price": price,
        "variants": [
            {
                "id": variant_id or product.variant_id,
                "sku": sku or product.sku,
                "title": variant_title or product.variant_title,
                "price": price,
                "available": available,
            }
        ],
    }
    payload = json.dumps(obj)
    if product.supplier == "Filastruder":
        script = f"<script>var wsgVersion = 4.82; var wsgProdData = {payload};</script>"
        prefix = "product"
    else:
        script = (
            f'<script type="application/json" id="ProductJson-product-template">{payload}</script>'
        )
        prefix = "og"
    return (
        script
        + f'<meta property="{prefix}:price:currency" content="{currency}">'
        + f'<meta property="{prefix}:price:amount" content="{meta_price}">'
    )


@pytest.mark.parametrize(
    "option_id",
    ["jubilee-motor-kit", "jubilee-hardware-kit", "jubilee-crossbar", "jubilee-xy-mount-set"],
)
def test_source_kit_requires_exact_variant_sku_product_and_usd(option_id):
    product = PRODUCTS[option_id]
    parsed = parse_product_page(product, shopify_page(product))
    assert parsed["variant_id"] == product.variant_id
    assert parsed["price_breaks"] == [{"minimum_packs": 1, "pack_price": "4"}]
    for kwargs in (
        {"sku": "wrong"},
        {"variant_id": "wrong"},
        {"product_id": "wrong"},
        {"currency": "CAD"},
        {"meta_price": "4.01"},
        {"variant_title": "Different option"},
        {"available": "true"},
        {"price": True},
    ):
        with pytest.raises(CatalogError):
            parse_product_page(product, shopify_page(product, **kwargs))


def test_source_kit_pair_is_one_purchase_unit_and_frame_is_explicit_candidate():
    project = new_project()
    project["sourcing"] = foundation_sourcing(project)

    def handler(request):
        product = next(p for p in PRODUCTS.values() if p.url == str(request.url))
        return httpx.Response(
            200, text=shopify_page(product), headers={"content-type": "text/html"}
        )

    result = refresh(project, handler)
    candidates = [row for row in result["rows"] if row["is_candidate"]]
    assert len(candidates) == 6
    assert result["coverage"]["fresh_priced_count"] == 6
    assert result["known_partial_subtotal"] == 24  # Six separate kits, one each.
    pair = next(row for row in candidates if row["selected_id"] == "jubilee-xy-mount-set")
    assert pair["quantity"] == 1 and pair["pack_count"] == 1 and pair["line_total"] == 4
    assert pair["source_bom_row"] == 12 and pair["source_project_revision"]
    frame = next(row for row in candidates if row["selected_id"] == "jubilee-frame-kit-black")
    assert frame["status"] == "priced" and frame["unit_price"] == 4
    assert frame["is_candidate"] and frame["variant_title"] == "Black"


def test_quote_and_custom_rows_never_claim_current_fallback_subtotal():
    project = new_project()
    project["sourcing"] = build_sourcing({"cooling": "opentrons-gen2"}, True)
    project["sourcing"]["groups"] = [
        g for g in project["sourcing"]["groups"] if g["id"] in {"cooling", "frame"}
    ]
    result = refresh(project, lambda request: pytest.fail("Quote checklist triggered HTTP"))
    assert [r["status"] for r in result["rows"]] == ["quote_needed", "missing"]
    assert result["known_partial_subtotal"] == 0


def test_downloads_preserve_report_provenance_null_prices_and_escape_csv():
    result = refresh(only_project(), lambda request: response(PRODUCTS["pico"]))
    result["rows"][0]["label"] = "=untrusted()"
    result["rows"][0]["line_total"] = None
    assert json.loads(procurement.report_json(result))["report_id"] == result["report_id"]
    row = next(csv.DictReader(io.StringIO(procurement.report_csv(result).decode())))
    assert row["report_id"] == result["report_id"] and row["line_total"] == ""
    assert row["label"] == "'=untrusted()"


def test_supplier_timeout_and_oversize_page_become_safe_missing_rows():
    def timeout(request):
        raise httpx.ReadTimeout("Synthetic timeout", request=request)

    report = refresh(only_project(), timeout)
    assert report["rows"][0]["status"] == "missing"
    assert "within the request limit" in report["rows"][0]["issue"]
    report = refresh(
        only_project(),
        lambda request: httpx.Response(
            200, content=b"x" * (2 * 1024 * 1024 + 1), headers={"content-type": "text/html"}
        ),
    )
    assert report["rows"][0]["unit_price"] is None
    assert "safe retrieval size" in report["rows"][0]["issue"]


def test_missing_availability_remains_literal_unknown_not_in_stock():
    product = PRODUCTS["pico"]
    parsed = parse_product_page(product, page(product, availability="unknown"))
    assert parsed["availability"] == "unknown"


def test_jubilee_csv_keeps_exact_kit_and_compatibility_provenance():
    project = new_project()
    project["sourcing"] = foundation_sourcing(project)

    def handler(request):
        product = next(p for p in PRODUCTS.values() if p.url == str(request.url))
        return httpx.Response(
            200, text=shopify_page(product), headers={"content-type": "text/html"}
        )

    result = refresh(project, handler)
    rows = list(csv.DictReader(io.StringIO(procurement.report_csv(result).decode())))
    motor = next(row for row in rows if row["selected_id"] == "jubilee-motor-kit")
    assert motor["is_candidate"] == "True" and motor["sku"] == "LDO-MTR-KIT-JUB"
    assert motor["variant_id"] == "32303923134535" and motor["source_bom_row"] == "22"
    assert "2022 motor substitutions" in motor["compatibility_note"]
    assert motor["source_project_revision"].startswith("c877bd2")
    assert motor["evidence_sha256"] and motor["parser"]
