"""Offline extraction only; tip-rack selection, dimensions and storage run normally."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import browser_foundation_server as foundation  # noqa: E402

import app.api as api  # noqa: E402
from app.model_client import ChatAction, ExtractedTurn  # noqa: E402

ALTERNATIVES = "Show me alternative tip rack products."
YES_PRINTER = "Yes, I have access to a 3D printer."
NO_PRINTER = "No, I do not have access to a 3D printer."
PRINTED_DIMENSIONS = (
    "Design the printed tip holder: maximum body diameter 6 mm, "
    "rim diameter minimum 9 mm, rim diameter maximum 10 mm, "
    "below-rim height 35 mm, 24 positions, 6 columns."
)


async def chat(project, message, history, **kwargs):
    values = None
    if message == ALTERNATIVES:
        values = {"actions": [ChatAction(kind="show_tip_rack_options", source=message)]}
    elif message in (YES_PRINTER, NO_PRINTER):
        values = {
            "tip_rack": {
                "printer_available": "yes" if message == YES_PRINTER else "no",
                "printer_source": message,
            }
        }
    elif message == PRINTED_DIMENSIONS:
        fields = {
            "body_diameter_max_mm": (6.0, "maximum body diameter 6 mm"),
            "rim_diameter_min_mm": (9.0, "rim diameter minimum 9 mm"),
            "rim_diameter_max_mm": (10.0, "rim diameter maximum 10 mm"),
            "below_rim_height_mm": (35.0, "below-rim height 35 mm"),
            "count": (24, "24 positions"),
            "columns": (6, "6 columns"),
        }
        values = {
            "tip_rack": {
                "profile_id": "custom_printed_tip_rack",
                "source": message,
                "spec": {key: value for key, (value, _) in fields.items()},
                "spec_sources": {key: source for key, (_, source) in fields.items()},
            },
            "actions": [ChatAction(kind="select_tip_rack", source=message)],
        }
    if values is not None:
        return ExtractedTurn(
            assistant_message="Reviewing the requested tip rack change.", **values
        ), {"model": "offline-tip-options-fixture", "input_tokens": 0, "output_tokens": 0}
    return await foundation.chat(project, message, history, **kwargs)


if __name__ == "__main__":
    import uvicorn

    args = foundation.baseline.parse_args()
    api.generate_turn = chat
    foundation.agent.propose_layout = foundation.layout
    foundation.inspection.propose_inspection = foundation.extension
    uvicorn.run(api.app, host="127.0.0.1", port=args.port, log_level="warning")
