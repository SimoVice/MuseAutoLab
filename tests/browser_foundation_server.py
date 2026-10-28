"""Chat-only source-CAD UI fixture; only the Meta transport is replaced."""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import browser_stub_server as baseline  # noqa: E402
from foundation_fixtures import source_proposal  # noqa: E402

import app.api as api  # noqa: E402
import app.design_agent as agent  # noqa: E402
import app.inspection as inspection  # noqa: E402
from app.model_client import ChatAction, ExtractedTurn  # noqa: E402


async def chat(project, message, history, **kwargs):
    requests = {
        "Develop the workstation from the real CAD base.": "develop_layout",
        "Lower the bed by another 30 mm.": "develop_layout",
        "Add an inspection arm and camera now.": "add_inspection",
        "Remove the inspection module.": "remove_inspection",
        "Show project files.": "show_files",
        "Open photo check.": "show_photo_check",
    }
    if message in requests:
        await asyncio.sleep(0.3)  # Explicit offline response latency.
        return ExtractedTurn(
            assistant_message="Checking the requested change.",
            actions=[ChatAction(kind=requests[message], source=message)],
        ), {}
    if message == "In the future I might want an arm and camera.":
        return ExtractedTurn(assistant_message="You can ask for that expansion in chat later."), {}
    if message == "Increase available width to 700 mm.":
        return ExtractedTurn(
            assistant_message="Recorded a 700 mm maximum width.",
            workspace_width_mm=700,
            source_workspace_width_mm="700 mm",
        ), {}
    return await baseline._fake_generate_turn(project, message, history, **kwargs)


async def layout(project, instruction, feedback, **kwargs):
    return source_proposal(130 if "another 30" in instruction else 100), {
        "model": "offline-source-layout-fixture",
        "input_tokens": 0,
        "output_tokens": 0,
    }


async def extension(project, instruction, feedback, **kwargs):
    return {
        "schema_version": "1",
        "link_lengths_mm": [380, 380],
        "mast_height_mm": 450,
        "rationale": "Offline inspection fixture.",
        "assumptions": [],
    }, {"model": "offline-inspection-fixture"}


if __name__ == "__main__":
    import uvicorn

    args = baseline.parse_args()
    api.generate_turn = chat
    agent.propose_layout = layout
    inspection.propose_inspection = extension
    uvicorn.run(api.app, host="127.0.0.1", port=args.port, log_level="warning")
