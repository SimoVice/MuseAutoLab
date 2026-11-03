"""Synthetic provider/catalogue latency through the actual chat lifecycle."""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
import browser_foundation_server as fixture  # noqa: E402

import app.api as api  # noqa: E402
import app.platform_research as research  # noqa: E402
from app.model_client import ExtractedTurn, ModelClientError  # noqa: E402


async def read(platform, url, client):
    await asyncio.sleep(1.3)
    return {"amount": 100, "retrieved_at": "synthetic-browser-observation"}


async def chat(project, message, history, **kwargs):
    await asyncio.sleep(1)
    if "fail" in message:
        raise ModelClientError("Synthetic provider timeout", failure_kind="provider_unavailable")
    research._cache.clear()
    await research.refresh_platform_prices()
    await asyncio.sleep(1)
    return ExtractedTurn(assistant_message="Synthetic request completed."), {}


if __name__ == "__main__":
    import uvicorn

    args = fixture.baseline.parse_args()
    api.generate_turn = chat
    research._read = read
    uvicorn.run(api.app, host="127.0.0.1", port=args.port, log_level="warning")
