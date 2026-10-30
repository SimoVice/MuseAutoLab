"""Offline Meta extraction for the real parametric rack browser journey."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import browser_foundation_server as foundation  # noqa: E402

import app.api as api  # noqa: E402
from app.model_client import ChatAction, ExtractedTurn  # noqa: E402

PARTIAL = (
    "Develop a rim-supported rack for 1.5–2 mL tubes with body diameter maximum 10.8 mm, "
    "6 positions in 3 columns."
)
COMPLETE = (
    "Develop a rim-supported rack with body diameter maximum 10.8 mm, "
    "rim diameter minimum 13.5 mm, closed cap diameter maximum 14 mm, "
    "below-rim height 30 mm, 6 positions in 3 columns."
)
EDIT = "Revise the tube rack to 12 positions in 4 columns."
REJECT = "Revise the tube rack to rim diameter minimum 11 mm."
SIX_TARGETS = (
    "Use target concentrations of 1, 0.8, 0.6, 0.4, 0.2, 0.1 mg/mL, "
    "with a final volume of 100 uL per tube. Keep the machine layout unchanged."
)


async def chat(project, message, history, **kwargs):
    values = None
    if message == PARTIAL:
        values = {
            "body_diameter_max_mm": (10.8, "body diameter maximum 10.8 mm"),
            "count": (6, "6 positions"),
            "columns": (3, "3 columns"),
        }
    elif message == COMPLETE:
        values = {
            "body_diameter_max_mm": (10.8, "body diameter maximum 10.8 mm"),
            "rim_diameter_min_mm": (13.5, "rim diameter minimum 13.5 mm"),
            "cap_diameter_max_mm": (14.0, "closed cap diameter maximum 14 mm"),
            "below_rim_height_mm": (30.0, "below-rim height 30 mm"),
            "count": (6, "6 positions"),
            "columns": (3, "3 columns"),
        }
    elif message == EDIT:
        values = {"count": (12, "12 positions"), "columns": (4, "4 columns")}
    elif message == REJECT:
        values = {"rim_diameter_min_mm": (11.0, "rim diameter minimum 11 mm")}
    if values is not None:
        patch = {key: value for key, (value, _) in values.items()}
        patch.update({f"source_{key}": literal for key, (_, literal) in values.items()})
        return ExtractedTurn(
            assistant_message="Checking the rack against your declared dimensions.",
            labware=patch,
            actions=[ChatAction(kind="develop_labware", source=message)],
        ), {"model": "offline-labware-fixture", "input_tokens": 0, "output_tokens": 0}
    if message == SIX_TARGETS:
        return ExtractedTurn(
            assistant_message="Updated six preparation targets while retaining the rack.",
            target_concentrations="1, 0.8, 0.6, 0.4, 0.2, 0.1 mg/mL",
            source_target_concentrations="1, 0.8, 0.6, 0.4, 0.2, 0.1 mg/mL",
            final_volume="100 uL per tube",
            source_final_volume="100 uL per tube",
        ), {"model": "offline-labware-fixture", "input_tokens": 0, "output_tokens": 0}
    return await foundation.chat(project, message, history, **kwargs)


if __name__ == "__main__":
    import uvicorn

    args = foundation.baseline.parse_args()
    api.generate_turn = chat
    foundation.agent.propose_layout = foundation.layout
    foundation.inspection.propose_inspection = foundation.extension
    uvicorn.run(api.app, host="127.0.0.1", port=args.port, log_level="warning")
