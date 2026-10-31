"""Offline extraction only; actual plate selection, geometry and storage run."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import browser_labware_server as rack_fixture  # noqa: E402

import app.api as api  # noqa: E402
from app.microplates import PROFILE_ID  # noqa: E402
from app.model_client import ChatAction, ExtractedTurn  # noqa: E402

SWITCH_ONLY = "Passa a una piastra da 96 pozzetti."
SWITCH_WITH_VOLUME = "Passa a una piastra da 96 pozzetti, con 200 µL per pozzetto."
RESOLVE = "Imposta un volume finale di 200 µL per pozzetto."
RETURN = "Torna al portaprovette precedente."


async def chat(project, message, history, **kwargs):
    if message in (SWITCH_ONLY, SWITCH_WITH_VOLUME, RETURN):
        selection = "previous_tube_rack" if message == RETURN else PROFILE_ID
        values = {
            "assistant_message": "Applying your explicit labware selection.",
            "labware_selection": {"profile_id": selection, "source": message},
            "actions": [ChatAction(kind="select_labware", source=message)],
        }
        if message == SWITCH_WITH_VOLUME:
            values.update(
                final_volume="200 µL per pozzetto", source_final_volume="200 µL per pozzetto"
            )
        return ExtractedTurn(**values), {"model": "offline-microplate-fixture"}
    if message == RESOLVE:
        return ExtractedTurn(
            assistant_message="Updating only the requested final volume.",
            final_volume="200 µL per pozzetto",
            source_final_volume="200 µL per pozzetto",
        ), {"model": "offline-microplate-fixture"}
    return await rack_fixture.chat(project, message, history, **kwargs)


if __name__ == "__main__":
    import uvicorn

    args = rack_fixture.foundation.baseline.parse_args()
    api.generate_turn = chat
    rack_fixture.foundation.agent.propose_layout = rack_fixture.foundation.layout
    rack_fixture.foundation.inspection.propose_inspection = rack_fixture.foundation.extension
    uvicorn.run(api.app, host="127.0.0.1", port=args.port, log_level="warning")
