"""Server-owned model choices and cached, read-only account catalog discovery."""

import asyncio
import hashlib
import time
from copy import deepcopy

import httpx

from app.model_client import DEFAULT_BASE_URL, ModelClientError, ModelSettings, configured_model

VOICE_MODEL = "muse-voice-transcribe-1.0"
IMAGE_MODEL = "muse-image-1.0"
AGENT_MODELS = {
    "muse-spark-1.3-contributor": {
        "label": "Muse Spark 1.3 Contributor",
        "data_policy": (
            "Contributor: content may be used to train Meta models. Use shareable input."
        ),
        "description": "Spark in Contributor mode; the project's original default.",
    },
    "muse-spark-1.3": {
        "label": "Muse Spark 1.3",
        "data_policy": "Standard: Meta states content is not used to train its models.",
        "description": "Spark in Standard mode; separate Model API usage applies.",
    },
    "muse-wonder-1.0": {
        "label": "Muse Wonder 1.0",
        "data_policy": "Standard: Meta states content is not used to train its models.",
        "description": "Higher-capability reasoning model; separate Model API usage applies.",
    },
}
_cache: dict[str, tuple[float, dict]] = {}
_catalog_lock = asyncio.Lock()
CATALOG_TTL_SECONDS = 60


async def discover_catalog(
    *, settings: ModelSettings | None = None, client: httpx.AsyncClient | None = None
) -> dict:
    """Catalog presence advertises access; it does not prove an inference succeeded."""
    try:
        settings = settings or ModelSettings.load()
    except ModelClientError:
        return {
            "ids": [],
            "reason": "Configure MODEL_API_KEY on the server to check access.",
            "verified": False,
        }
    fingerprint = hashlib.sha256((settings.base_url + "\0" + settings.api_key).encode()).hexdigest()
    async with _catalog_lock:
        cached = _cache.get(fingerprint)
        if cached and time.monotonic() - cached[0] < CATALOG_TTL_SECONDS:
            return deepcopy(cached[1])
        result = {"ids": [], "reason": None, "verified": False}
        try:

            async def fetch(active: httpx.AsyncClient):
                response = await active.get(
                    f"{settings.base_url}/models",
                    headers={"Authorization": f"Bearer {settings.api_key}"},
                    timeout=httpx.Timeout(8, connect=4),
                )
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict) or not isinstance(body.get("data"), list):
                    raise ValueError("Invalid catalog")
                entries = body["data"]
                if len(entries) > 1000 or any(
                    not isinstance(row, dict) or not isinstance(row.get("id"), str)
                    for row in entries
                ):
                    raise ValueError("Invalid catalog")
                return sorted({row["id"] for row in entries})

            async with asyncio.timeout(10):
                if client is None:
                    async with httpx.AsyncClient(follow_redirects=False) as active:
                        result["ids"] = await fetch(active)
                else:
                    result["ids"] = await fetch(client)
            result["verified"] = True
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            result["reason"] = (
                "The server API key cannot list models. Check its account access."
                if code in (401, 403)
                else f"Model access could not be checked (HTTP {code}). Try again shortly."
            )
        except (httpx.RequestError, TimeoutError):
            result["reason"] = "Model access could not be checked. Check the server connection."
        except (ValueError, TypeError):
            result["reason"] = "The provider returned an invalid model catalog. Try again shortly."
        # Keep the cache bounded when operators rotate credentials.
        if len(_cache) >= 8:
            _cache.clear()
        _cache[fingerprint] = (time.monotonic(), deepcopy(result))
        return result


def availability(catalog: dict, model: str) -> dict:
    available = catalog["verified"] and model in catalog["ids"]
    return {
        "available": bool(available),
        "unavailable_reason": None
        if available
        else (catalog["reason"] or "This model is not advertised for the configured account."),
    }


async def model_options(current: str | None = None) -> dict:
    catalog = await discover_catalog()
    default = configured_model()
    voice = {
        "model": VOICE_MODEL,
        **availability(catalog, VOICE_MODEL),
        "max_duration_seconds": 60,
        "max_bytes": 60 * 24000 * 2 + 65536,
        "sample_rates_hz": [16000, 24000],
    }
    image = {
        "model": IMAGE_MODEL,
        **availability(catalog, IMAGE_MODEL),
        "max_reference_bytes": 4 * 1024 * 1024,
        "timeout_seconds": 150,
        "scope": "Optional concept illustration for presentation only.",
    }
    try:
        if ModelSettings.load().base_url != DEFAULT_BASE_URL:
            voice.update(
                available=False,
                unavailable_reason="Voice requires the official Meta Model API endpoint.",
            )
            image.update(
                available=False,
                unavailable_reason="Illustrations require the official Meta Model API endpoint.",
            )
    except ModelClientError:
        pass
    return {
        "models": [
            {"id": model, **details, **availability(catalog, model)}
            for model, details in AGENT_MODELS.items()
        ],
        "default_model": default,
        "active_model": current or default,
        "availability_basis": "Account catalog; successful inference is not guaranteed.",
        "capabilities": {
            "voice": voice,
            "image": image,
        },
    }
