"""Bounded, read-only adapters for reviewed US supplier product pages.

Only server-owned registry URLs are fetched. No redirects, browser fallback,
logins, searches, model calls, or purchases occur here.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx

MAX_PAGE_BYTES = 2 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 12


@dataclass(frozen=True)
class CatalogProduct:
    option_id: str
    supplier: str
    sku: str
    url: str
    pack_size: int = 1
    adapter: str = "jsonld"
    product_id: str | None = None
    variant_id: str | None = None
    variant_title: str | None = None


PRODUCTS = {
    item.option_id: item
    for item in (
        CatalogProduct("pololu-1209", "Pololu", "1209", "https://www.pololu.com/product/1209"),
        CatalogProduct("pololu-1208", "Pololu", "1208", "https://www.pololu.com/product/1208"),
        CatalogProduct("drv8825", "Pololu", "2133", "https://www.pololu.com/product/2133"),
        CatalogProduct("a4988", "Pololu", "1182", "https://www.pololu.com/product/1182"),
        CatalogProduct("pico", "Adafruit", "4864", "https://www.adafruit.com/product/4864"),
        CatalogProduct("pico-h", "Adafruit", "5525", "https://www.adafruit.com/product/5525"),
        CatalogProduct("diy-peltier", "Adafruit", "1335", "https://www.adafruit.com/product/1335"),
        CatalogProduct("probe", "Adafruit", "381", "https://www.adafruit.com/product/381"),
        CatalogProduct("bare", "Adafruit", "374", "https://www.adafruit.com/product/374"),
        CatalogProduct(
            "jubilee-motor-kit",
            "Filastruder",
            "LDO-MTR-KIT-JUB",
            "https://www.filastruder.com/products/ldo-stepper-motor-set-for-jubilee",
            adapter="shopify",
            product_id="4665174130759",
            variant_id="32303923134535",
            variant_title="Full set with cables",
        ),
        CatalogProduct(
            "jubilee-motion-kit",
            "Filastruder",
            "JubileeMotionSet",
            "https://www.filastruder.com/products/gates-motion-set-for-jubilee-printers",
            adapter="shopify",
            product_id="4640549175367",
            variant_id="32245286371399",
            variant_title="Standard",
        ),
        CatalogProduct(
            "jubilee-hardware-kit",
            "Filastruder",
            "JubHWKit",
            "https://www.filastruder.com/products/jubilee-hardware-kit?variant=32712442904647",
            adapter="shopify",
            product_id="4925904289863",
            variant_id="32712442904647",
            variant_title="Full Set",
        ),
        CatalogProduct(
            "jubilee-frame-kit-black",
            "Filastruder",
            "JubFrameKitBlack",
            "https://www.filastruder.com/products/jubilee-frame-kit-by-ldo-motors"
            "?variant=32712440021063",
            adapter="shopify",
            product_id="4925902782535",
            variant_id="32712440021063",
            variant_title="Black",
        ),
        CatalogProduct(
            "jubilee-crossbar",
            "Mandala Rose Works",
            "JBXBAR",
            "https://mandalaroseworks.com/products/jubilee-crossbar",
            adapter="shopify",
            product_id="7446311371005",
            variant_id="42044330115325",
            variant_title="Default Title",
        ),
        CatalogProduct(
            "jubilee-xy-mount-set",
            "Mandala Rose Works",
            "JBSM",
            "https://mandalaroseworks.com/products/jubilee-aluminum-stepper-mounts",
            adapter="shopify",
            product_id="7446311403773",
            variant_id="42044330148093",
            variant_title="Default Title",
        ),
    )
}


class CatalogError(Exception):
    """A safe, user-readable supplier retrieval or interpretation failure."""


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[str] = []
        self.metadata: dict[str, list[str]] = {}
        self.tables: list[list[list[str]]] = []
        self._script: list[str] | None = None
        self._script_attributes: dict = {}
        self.shopify_products: list[dict] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attributes = dict(attrs)
        if tag == "script" and not attributes.get("src"):
            self._script = []
            self._script_attributes = attributes
        if tag == "meta":
            key = attributes.get("property") or attributes.get("itemprop")
            if key and attributes.get("content"):
                self.metadata.setdefault(key, []).append(attributes["content"])
        if tag == "table" and "pricing" in attributes.get("class", "").split():
            self._table = []
        if self._table is not None and tag == "tr":
            self._row = []
        if self._row is not None and tag in ("td", "th"):
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script is not None:
            value = "".join(self._script)
            kind = self._script_attributes.get("type", "").lower()
            if kind == "application/ld+json":
                self.scripts.append(value)
            try:
                if kind == "application/json" and self._script_attributes.get("id") == (
                    "ProductJson-product-template"
                ):
                    self.shopify_products.append(json.loads(value))
                elif kind in ("", "text/javascript"):
                    # Read one reviewed JSON literal; never evaluate storefront JavaScript.
                    marker = re.search(r"\bvar\s+wsgProdData\s*=\s*", value)
                    if marker:
                        product, _ = json.JSONDecoder().raw_decode(value[marker.end() :])
                        self.shopify_products.append(product)
            except (ValueError, TypeError):
                pass
            self._script = None
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        if tag == "tr" and self._row is not None:
            self._table.append(self._row)
            self._row = None
        if tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None

    def handle_data(self, value: str) -> None:
        if self._script is not None:
            self._script.append(value)
        if self._cell is not None:
            self._cell.append(value)


def _money(value: object) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise CatalogError("The supplier did not provide a valid positive price.")
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise CatalogError("The supplier did not provide a valid positive price.") from None
    if not amount.is_finite() or amount <= 0 or amount > 1_000_000:
        raise CatalogError("The supplier did not provide a valid positive price.")
    if amount != amount.quantize(Decimal("0.01")):
        raise CatalogError("The supplier price precision needs manual review.")
    return amount


def _nodes(value: object):
    if isinstance(value, list):
        for item in value:
            yield from _nodes(item)
    elif isinstance(value, dict):
        yield value
        if "@graph" in value:
            yield from _nodes(value["@graph"])


def _identity_url(value: object, product: CatalogProduct) -> bool:
    if not isinstance(value, str):
        return False
    try:
        url = urlsplit(value)
        expected = urlsplit(product.url)
        port = url.port
    except ValueError:
        return False
    return (
        url.scheme == "https"
        and url.hostname in {expected.hostname, expected.hostname[4:]}
        and url.path.rstrip("/") == expected.path
        and not url.query
        and not url.fragment
        and url.username is None
        and url.password is None
        and port in (None, 443)
    )


def _shopify_product(product: CatalogProduct, page: _Page, html: str) -> dict:
    matches = [
        node
        for node in page.shopify_products
        if isinstance(node, dict) and str(node.get("id")) == product.product_id
    ]
    if (
        len(matches) != 1
        or matches[0].get("handle") != urlsplit(product.url).path.rsplit("/", 1)[-1]
    ):
        raise CatalogError("The supplier page does not identify the registered product.")
    node = matches[0]
    variants = node.get("variants", [])
    if not isinstance(variants, list):
        raise CatalogError("The supplier variants need manual review.")
    matches = [
        v
        for v in variants
        if isinstance(v, dict)
        and str(v.get("id")) == product.variant_id
        and v.get("sku") == product.sku
        and v.get("title") == product.variant_title
    ]
    if len(matches) != 1:
        raise CatalogError("The supplier variant ID, SKU or option differs from the reviewed kit.")
    variant = matches[0]
    cents = variant.get("price")
    if isinstance(cents, bool) or not isinstance(cents, int):
        raise CatalogError("The supplier variant price is not an integer number of cents.")
    price = _money(Decimal(cents) / 100)
    currencies = page.metadata.get("product:price:currency", []) + page.metadata.get(
        "og:price:currency", []
    )
    amounts = page.metadata.get("product:price:amount", []) + page.metadata.get(
        "og:price:amount", []
    )
    if not currencies or any(value != "USD" for value in currencies):
        raise CatalogError("The supplier variant is not explicitly priced in USD.")
    if not amounts or any(_money(value) != price for value in amounts):
        raise CatalogError("The supplier page and exact variant publish inconsistent prices.")
    if not isinstance(variant.get("available"), bool):
        raise CatalogError("The supplier variant availability is unverified.")
    name = node.get("title")
    if not isinstance(name, str) or not name.strip():
        raise CatalogError("The supplier product name is missing.")
    return {
        "product_name": name[:300],
        "sku": product.sku,
        "currency": "USD",
        "pack_size": product.pack_size,
        "price_breaks": [{"minimum_packs": 1, "pack_price": str(price)}],
        "availability": "InStock" if variant["available"] else "OutOfStock",
        "source_url": product.url,
        "variant_id": product.variant_id,
        "variant_title": product.variant_title,
        "evidence_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
        "parser": "supplier-shopify-exact-variant-us-v1",
    }


def parse_product_page(product: CatalogProduct, html: str) -> dict:
    """Require exact Product SKU, USD Offer and matching primary product URL.

    Preserve all reviewed quantity breaks: the JSON-LD price normally describes
    one pack, whereas Pololu's visible US$ table supplies bulk pack prices.
    """
    page = _Page()
    page.feed(html)
    if product.adapter == "shopify":
        return _shopify_product(product, page, html)
    products = []
    for script in page.scripts:
        try:
            nodes = _nodes(json.loads(script))
            products.extend(node for node in nodes if node.get("@type") == "Product")
        except (ValueError, TypeError):
            continue
    matches = [node for node in products if str(node.get("sku")) == product.sku]
    if len(matches) != 1:
        raise CatalogError("The page does not identify exactly the registered supplier SKU.")
    node = matches[0]
    name = node.get("name")
    if not isinstance(name, str) or not name.strip():
        raise CatalogError("The supplier product identity is incomplete.")
    # Pack size belongs to the reviewed registry, not a guessed product description.
    pack_match = re.search(r"\b(\d+)\s*[- ]?pack\b", name, re.IGNORECASE)
    if pack_match and int(pack_match[1]) != product.pack_size:
        raise CatalogError("The supplier pack size differs from the registered item.")
    offers = node.get("offers")
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list) or not offers:
        raise CatalogError("The supplier has no listed offer; request a quotation.")
    prices: set[Decimal] = set()
    availability: set[str] = set()
    for offer in offers:
        if not isinstance(offer, dict) or offer.get("@type") != "Offer":
            raise CatalogError("The supplier offer format needs manual review.")
        if str(offer.get("priceCurrency", "")).upper() != "USD":
            raise CatalogError("The supplier offer is not explicitly priced in USD.")
        if not _identity_url(offer.get("url") or offer.get("URL"), product):
            raise CatalogError("The supplier offer URL does not match the registered SKU.")
        prices.add(_money(offer.get("price")))
        raw = str(offer.get("availability", "unknown")).rsplit("/", 1)[-1]
        availability.add(raw)
    if len(prices) != 1 or len(availability) != 1:
        raise CatalogError("The supplier publishes inconsistent prices or availability.")
    price = prices.pop()
    for key in ("product:price:currency", "priceCurrency"):
        if any(value.upper() != "USD" for value in page.metadata.get(key, [])):
            raise CatalogError("The page contains conflicting price currencies.")
    for key in ("product:price:amount", "price"):
        if any(_money(value) != price for value in page.metadata.get(key, [])):
            raise CatalogError("The page contains conflicting product prices.")
    tiers = [(1, price)]
    if product.supplier == "Pololu":
        if len(page.tables) != 1:
            raise CatalogError("The supplier quantity-price table is missing or ambiguous.")
        table = page.tables[0]
        if not table or table[0] != ["Price break", "Unit price (US$)"]:
            raise CatalogError("The supplier table is not explicitly a US dollar price list.")
        tiers = []
        for cells in table[1:]:
            if len(cells) != 2 or not cells[0].isdigit() or int(cells[0]) < 1:
                raise CatalogError("The supplier quantity-price breaks need manual review.")
            tiers.append((int(cells[0]), _money(cells[1])))
        if not tiers or tiers[0] != (1, price):
            raise CatalogError("The supplier table disagrees with the listed base price.")
        if any(b[0] <= a[0] or b[1] > a[1] for a, b in zip(tiers, tiers[1:])):
            raise CatalogError("The supplier quantity-price breaks are inconsistent.")
    return {
        "product_name": name.strip()[:300],
        "sku": product.sku,
        "currency": "USD",
        "pack_size": product.pack_size,
        "price_breaks": [{"minimum_packs": q, "pack_price": str(p)} for q, p in tiers],
        "availability": availability.pop(),
        "source_url": product.url,
        "evidence_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
        "parser": "supplier-jsonld-us-v1",
    }


async def fetch_product(product: CatalogProduct, client: httpx.AsyncClient) -> dict:
    if PRODUCTS.get(product.option_id) != product:
        raise CatalogError("This product is not in the reviewed supplier registry.")
    try:
        async with asyncio.timeout(FETCH_TIMEOUT_SECONDS):
            async with client.stream("GET", product.url, follow_redirects=False) as response:
                if response.status_code != 200:
                    raise CatalogError(
                        f"The supplier page was unavailable (HTTP {response.status_code})."
                    )
                if "text/html" not in response.headers.get("content-type", "").lower():
                    raise CatalogError("The supplier did not return a product HTML page.")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_PAGE_BYTES:
                        raise CatalogError("The supplier page exceeds the safe retrieval size.")
                    body.extend(chunk)
                return parse_product_page(product, body.decode("utf-8", errors="replace"))
    except (httpx.HTTPError, TimeoutError):
        raise CatalogError("The supplier could not be reached within the request limit.") from None
