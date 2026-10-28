"""Stubbed MuseAutoLab backend for the browser smoke test.

This server runs the actual product FastAPI app and domain logic from
``app.api`` / ``app.domain`` locally, but replaces the Meta model client
(``app.api.generate_turn``) with a deterministic async fake and the layout
model call (``app.design_agent.propose_layout``) with an explicit offline
fixture. No Meta request is made and no API key is needed.
"""

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.api  # noqa: E402
import app.design_agent  # noqa: E402


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
    """Deterministic replacement for ``app.model_client.generate_turn``."""

    if user_message == "Hello.":
        return _FakeTurn("What would you like to automate?", {}), {}

    general_turns = {
        "I spend hours transferring capped vials between racks and an inspection station.": (
            "Let's map the transfer workflow. Which racks and inspection equipment do you use?",
            {
                "workflow_kind": "general",
                "brief_objective": "transferring capped vials between racks "
                "and an inspection station",
                "brief_process": "transferring capped vials between racks "
                "and an inspection station",
            },
        ),
        "I have a microscope and two racks; I need to inspect the labels.": (
            "How are the vials presented to the microscope?",
            {
                "workflow_kind": "general",
                "brief_equipment": "a microscope and two racks",
                "brief_process": "inspect the labels",
            },
        ),
        "The available space is 450 mm wide.": (
            "Recorded the available space for the inspection concept.",
            {"workspace_width_mm": 450, "brief_constraints": "450 mm wide"},
        ),
        "I keep making dilutions manually and want to automate pipetting.": (
            "Which equipment would you like to keep using?",
            {
                "workflow_kind": "liquid_preparation",
                "brief_objective": "automate pipetting",
                "brief_process": "making dilutions manually",
            },
        ),
        "I have a pipette and microcentrifuge tubes.": (
            "What volumes will the liquid preparation need to handle?",
            {"brief_equipment": "a pipette and microcentrifuge tubes"},
        ),
        "Actually, switch this project to inspecting vial labels with a microscope.": (
            "Let's plan the label inspection workflow. How are the vials held?",
            {
                "workflow_kind": "general",
                "brief_objective": "inspecting vial labels",
                "brief_equipment": "a microscope",
            },
        ),
    }
    if user_message in general_turns:
        text, patch = general_turns[user_message]
        return _FakeTurn(text, patch), {}

    lowered = user_message.casefold()
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    if user_message == "Add refrigerated storage at 4 C.":
        return _FakeTurn(
            "Recorded a 4 C refrigerated storage request.",
            {"cooling_enabled": True, "cooling_target_c": 4},
        ), usage

    if "20 mg/ml" in lowered:
        return _FakeTurn(
            "Recorded an impossible target concentration for this test.",
            {"target_concentrations": "20 mg/mL"},
        ), usage

    if (
        ("10 mg/ml" in lowered or "10mg/ml" in lowered)
        and "pipette" in lowered
        and "microcentrifuge" in lowered
    ):
        turn = _FakeTurn(
            "Recorded synthetic parameters for the stubbed smoke test: "
            "10 mg/mL stock, 1 mg/mL target, 1 mL final volume, "
            "pipette and microcentrifuge tubes.",
            {
                "stock_concentration": "10mg/ml",
                "target_concentrations": "1mg/ml",
                "final_volume": "1ml",
                "equipment": "pipette and microcentrifuge tubes",
            },
        )
        return turn, usage

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


WIDE_IDS = ("source-rack", "sample-rack", "tip-rack", "tip-waste", "controller")
# Fixed actual component envelopes are retained by the compiler; positions use
# the default rack layout with the controller clamped clear of the rear strip
# (z >= -depth/2 + 85 + size_z/2).
_WIDE_POSITIONS = {
    "source-rack": (-160.0, 55.0),
    "sample-rack": (-45.0, 55.0),
    "tip-rack": (70.0, 55.0),
    "tip-waste": (200.0, 65.0),
    "controller": (195.0, -50.0),
}
_COMPACT_POSITIONS = {
    "source-rack": (-112.0, -45.0),
    "sample-rack": (0.0, -45.0),
    "tip-rack": (112.0, -45.0),
    "tip-waste": (-120.0, 120.0),
    "controller": (120.0, 120.0),
}


def _fixture_layout(project: dict) -> dict:
    """Explicit offline layout fixture respecting the feasible width."""
    summary = project.get("summary") or {}
    width = summary.get("workspace_width_mm")
    compact = (
        isinstance(width, (int, float))
        and not isinstance(width, bool)
        and width < 600
        and width >= 400
    )
    if compact:
        deck = (400.0, 470.0)
        positions = _COMPACT_POSITIONS
    else:
        deck = (600.0, 370.0)
        positions = _WIDE_POSITIONS
    return {
        "schema_version": "1",
        "deck_width_mm": deck[0],
        "deck_depth_mm": deck[1],
        "placements": [
            {"component_id": cid, "x_mm": positions[cid][0], "z_mm": positions[cid][1]}
            for cid in WIDE_IDS
        ],
        "rationale": "Offline fixture: valid synthetic operating-deck layout; "
        "no provider request or hardware test.",
        "assumptions": ["Synthetic offline fixture for gated browser tests."],
    }


async def _fake_propose_layout(project, instruction, feedback, **kwargs):
    """Explicit offline model fixture for ``app.design_agent.propose_layout``."""
    return deepcopy(_fixture_layout(project)), {
        "model": "offline-layout-fixture",
        "input_tokens": 0,
        "output_tokens": 0,
    }


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

    # Only stub the model callables; domain, compiler and geometry stay real.
    app.api.generate_turn = _fake_generate_turn  # type: ignore[method-assign]
    app.design_agent.propose_layout = _fake_propose_layout  # type: ignore[method-assign]

    import uvicorn

    print(
        f"[stub-server] Starting stubbed MuseAutoLab API on http://{args.host}:{args.port} "
        "(AI provider and layout model are stubbed; no Meta request will be made).",
        flush=True,
    )
    uvicorn.run(app.api.app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
