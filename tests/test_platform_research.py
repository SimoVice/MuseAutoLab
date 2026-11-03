import asyncio

import httpx

from app import platform_research
from app.platform_profiles import platform_profiles


def test_discovery_reads_only_reviewed_urls_and_caches_partial_results(monkeypatch):
    requested = []
    actual_client = httpx.AsyncClient

    def serve(request):
        requested.append(str(request.url))
        assert not request.headers.get("authorization") and not request.content
        if request.url.host == "jubilee3d.com":
            return httpx.Response(403)
        return httpx.Response(
            200, headers={"Content-Type": "text/html"}, text="""
            <h3>Flex Robot</h3>Starting at $24,950
            <script>OT-2 Robot Starting at $1,000</script>
            <h3>OT-2 Robot</h3> Starting at <b>$16,250</b>
            """
        )

    monkeypatch.setattr(platform_research, "_cache", {})
    monkeypatch.setattr(platform_research.httpx, "AsyncClient",
                        lambda **kw: actual_client(transport=httpx.MockTransport(serve), **kw))
    asyncio.run(platform_research.refresh_platform_prices())
    asyncio.run(platform_research.refresh_platform_prices())
    specs, vendor = [p["cost_context"] for p in platform_profiles()]
    assert set(requested) == {specs["source_url"], vendor["source_url"]} and len(requested) == 2
    assert "retrieved_at" not in specs and specs["amount"] == 1400
    assert vendor["retrieved_at"] and vendor["amount"] == 16250


def test_price_requires_an_unambiguous_matching_visible_label():
    assert platform_research._amount("jubilee", "Self-Sourcing parts for Jubilee cost ~$1400 (US)."
                                     " The default extruder costs ~$200.") == 1400
    assert platform_research._amount("opentrons-ot2", "Buy a Flex starting at $24,950") is None
    assert platform_research._amount("opentrons-ot2", "OT-2 Robot Starting at $16,900 / "
                                     "OT-2 Robot Starting at $9,950") is None
