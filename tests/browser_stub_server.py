"""Stubbed MuseAutoLab backend for the browser smoke test.

This server runs the actual product FastAPI app and domain logic from
``app.api`` / ``app.domain`` locally, but replaces the Meta model client
(``app.api.generate_turn``) with a deterministic async fake.

No Meta request is made and no API key is needed. The fake only
understands the four known synthetic English messages sent by
``tests/browser_smoke.py``:

* a complete task filling stock concentration, target, final volume and
  equipment,
* a 450 mm workspace-width request,
* a 300 mm workspace-width request,
* a 650 mm workspace-width request.

Any other message raises ``ValueError`` (surfaced by the API as HTTP 422)
so the smoke test cannot silently pass with unexpected input.

The backend domain still performs the actual layout changes
(600x370 mm wide vs 400x470 mm compact), the infeasible-width handling,
and the confirmation checks. No physical or WebGL-visual validation is
implied.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.api  # noqa: E402


class _FakeTurn:
    """Minimal stand-in for ``ExtractedTurn`` used by ``app.api``."""

    def __init__(self, assistant_message: str, patch_data: dict) -> None:
        self.assistant_message = assistant_message
        self._patch_data = dict(patch_data)

    def patch(self) -> dict:
        return dict(self._patch_data)


async def _fake_generate_turn(
    project: dict, user_message: str, history: list[dict[str, str]], **kwargs
) -> tuple[_FakeTurn, dict[str, int]]:
    """Deterministic replacement for ``app.model_client.generate_turn``.

    NOTE: the AI provider is stubbed here. This fake performs no model
    call and only matches the synthetic messages used by the smoke test.
    """
    lowered = user_message.casefold()
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    # Complete synthetic task: fills the four required text fields.
    # Expected to contain "10 mg/mL" plus pipette/microcentrifuge wording.
    if "10 mg/ml" in lowered and "pipette" in lowered and "microcentrifuge" in lowered:
        turn = _FakeTurn(
            "Recorded synthetic parameters for the stubbed smoke test: "
            "10 mg/mL stock, 1 mg/mL target, 1 mL final volume, "
            "pipette and microcentrifuge tubes.",
            {
                "stock_concentration": "10 mg/mL",
                "target_concentrations": "1 mg/mL",
                "final_volume": "1 mL",
                "equipment": "pipette and microcentrifuge tubes",
            },
        )
        return turn, usage

    # Width requests are matched on the requested number plus a mm unit.
    # Each branch is checked after the complete-task branch so that the
    # "1 mL" volume message cannot be mistaken for a width.
    if "450" in user_message and "mm" in lowered:
        turn = _FakeTurn(
            "Noted a 450 mm width limit for this synthetic concept (stubbed AI provider).",
            {"workspace_width_mm": 450.0},
        )
        return turn, usage

    if "300" in user_message and "mm" in lowered:
        turn = _FakeTurn(
            "Noted a 300 mm width limit for this synthetic concept (stubbed AI provider).",
            {"workspace_width_mm": 300.0},
        )
        return turn, usage

    if "650" in user_message and "mm" in lowered:
        turn = _FakeTurn(
            "Noted a 650 mm width limit for this synthetic concept (stubbed AI provider).",
            {"workspace_width_mm": 650.0},
        )
        return turn, usage

    raise ValueError(
        "Stubbed AI provider received an unexpected synthetic message. "
        "Only the four known smoke-test messages are supported."
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the stubbed MuseAutoLab API for browser smoke testing."
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

    # Replace only the model-callable used by the API module. Domain logic
    # (apply_update / confirm_project) remains the actual product code.
    app.api.generate_turn = _fake_generate_turn  # type: ignore[method-assign]

    import uvicorn

    print(
        f"[stub-server] Starting stubbed MuseAutoLab API on http://{args.host}:{args.port} "
        "(AI provider is stubbed; no Meta request will be made).",
        flush=True,
    )
    uvicorn.run(app.api.app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
