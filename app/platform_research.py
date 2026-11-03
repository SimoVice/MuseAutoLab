"""Read the two reviewed public platform price sources without sending chat or project data."""

import asyncio
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from time import monotonic

import httpx


class _PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.chunks = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "template"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "template"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.chunks.append(data)


_PRICE = r"\$\s*([1-9]\d{0,2}(?:,\d{3})+|[1-9]\d{0,6})(?:\.00)?(?![\d.,])"
_LABELS = {
    "jubilee": r"Self-sourcing parts for Jubilee cost\s*~?\s*" + _PRICE + r"\s*\(US\)",
    "opentrons-ot2": r"\bOT-2 Robot\s+Starting at\s+" + _PRICE,
}
# Cache only a number and retrieval time, or a short cooldown on a failed read.
_cache: dict[str, tuple[float, dict | None]] = {}


def _amount(platform: str, html: str) -> int | None:
    parser = _PageText()
    parser.feed(html)
    text = " ".join(" ".join(parser.chunks).split())
    values = {int(value.replace(",", "")) for value in re.findall(_LABELS[platform], text, re.I)}
    return values.pop() if len(values) == 1 else None


async def _read(platform: str, url: str, client: httpx.AsyncClient):
    try:
        async with asyncio.timeout(3):
            async with client.stream("GET", url, follow_redirects=False) as response:
                if response.status_code != 200 or "text/html" not in response.headers.get(
                    "content-type", "").lower():
                    return None
                body = bytearray()
                async for chunk in response.aiter_bytes(65536):
                    if len(body) + len(chunk) > 2 * 1024 * 1024:
                        return None
                    body.extend(chunk)
        amount = _amount(platform, body.decode("utf-8", errors="replace"))
        if amount:
            return {"amount": amount,
                    "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds")}
    except (httpx.HTTPError, TimeoutError, ValueError):
        pass
    return None


def apply_recent_prices(profiles: list[dict]) -> list[dict]:
    for item in profiles:
        expires, observation = _cache.get(item["id"], (0, None))
        if observation and expires > monotonic():
            cost = item["cost_context"]
            cost.update(observation)
            cost["detail"] = (
                "The Jubilee project gives this historical estimate for self-sourcing the base."
                if item["id"] == "jubilee"
                else "Starting price from the US robot catalogue; configuration changes the cost."
            )
    return profiles


async def refresh_platform_prices() -> None:
    # The registry is created on the server; no caller-supplied URLs are accepted.
    from app.platform_profiles import platform_profiles

    profiles = [item for item in platform_profiles() if item["id"] in _LABELS
                and _cache.get(item["id"], (0, None))[0] <= monotonic()]
    if not profiles:
        return
    async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
        observations = await asyncio.gather(*(
            _read(item["id"], item["cost_context"]["source_url"], client) for item in profiles
        ))
    for item, observation in zip(profiles, observations, strict=True):
        key = item["id"]
        expires, cached = _cache.get(key, (0, None))
        if observation or not cached or expires <= monotonic():
            _cache[key] = (monotonic() + (21600 if observation else 300), observation)
