"""Vision stub server for the camera browser test.

Runs the actual product FastAPI app and domain code, keeps the chat
``generate_turn`` fake from ``browser_stub_server`` and replaces only
``app.vision.analyze_image`` with a deterministic fake and
``app.design_agent.propose_layout`` with the shared explicit offline layout
fixture. No Meta call occurs.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import browser_stub_server as baseline  # noqa: E402

import app.api  # noqa: E402
import app.design_agent as design_agent  # noqa: E402
import app.vision as vision  # noqa: E402

CALL_COUNT = 0


def _two_region_raw() -> dict:
    return {
        "image_quality": "clear",
        "coverage": "complete",
        "summary": "One tube and one tip rack observed.",
        "warnings": [],
        "detections": [
            {
                "kind": "tube",
                "label": "Tube near left",
                "box": {"x_min": 100, "y_min": 200, "x_max": 300, "y_max": 700},
                "confidence": 0.55,
                "uncertain": True,
                "reason": "Blurry tube edge.",
                "tip_rack_contents": "not_applicable",
            },
            {
                "kind": "tip_rack",
                "label": "Tip rack right",
                "box": {"x_min": 650, "y_min": 300, "x_max": 950, "y_max": 700},
                "confidence": 0.95,
                "uncertain": False,
                "reason": "Rack with visible tips.",
                "tip_rack_contents": "tips_visible",
            },
        ],
    }


def _empty_raw() -> dict:
    return {
        "image_quality": "clear",
        "coverage": "complete",
        "summary": "No regions observed.",
        "warnings": [],
        "detections": [],
    }


async def _fake_analyze_image(image, **kwargs) -> tuple[dict, dict]:
    """Deterministic replacement for ``app.vision.analyze_image``."""
    global CALL_COUNT
    assert hasattr(image, "content") and hasattr(image, "sha256"), (
        "Fake model expected a CanonicalImage."
    )
    assert bytes(image.content)[:2] == b"\xff\xd8", "Canonical image must be JPEG."
    CALL_COUNT += 1
    await asyncio.sleep(1.0)
    if CALL_COUNT == 1:
        raw = _two_region_raw()
    else:
        raw = _empty_raw()
    validated = vision.RawInspection.model_validate(deepcopy(raw)).model_dump()
    usage = {"prompt_tokens": 11, "completion_tokens": 23, "total_tokens": 34}
    return validated, dict(usage)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the stubbed vision MuseAutoLab API for browser testing."
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Loopback host to bind (default 127.0.0.1)."
    )
    parser.add_argument("--port", type=int, default=8000, help="Port to bind.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.host not in ("127.0.0.1", "localhost"):
        raise ValueError("This stub server binds only to loopback (127.0.0.1).")
    # Keep the chat fake and explicit layout fixture; only vision is faked here.
    app.api.generate_turn = baseline._fake_generate_turn  # type: ignore[attr-defined]
    design_agent.propose_layout = baseline._fake_propose_layout  # type: ignore[attr-defined]
    vision.analyze_image = _fake_analyze_image  # type: ignore[method-assign]
    import uvicorn

    print(
        f"[vision-server] Starting vision-stubbed API on http://{args.host}:{args.port} "
        "(chat, layout and vision are stubbed; jobs and images are real).",
        flush=True,
    )
    uvicorn.run(app.api.app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
