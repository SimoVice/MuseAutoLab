"""Actual API/compiler with explicit offline model fixtures for project evolution."""

import argparse
import asyncio

import browser_design_server
import browser_stub_server

import app.design_agent
import app.inspection
from app.model_client import ExtractedTurn

SOURCE_MESSAGE = "Which reviewed open-source foundation supports pipette and camera tools?"


async def sourced_turn(project, message, history):
    if message == SOURCE_MESSAGE:
        return ExtractedTurn.model_validate(
            {
                "assistant_message": "Science Jubilee documents pipette and camera workflows. "
                "It is an integration reference; this workstation remains a custom concept.",
                "recommendations": [
                    {
                        "reference_id": "science-jubilee",
                        "reason": "Documented modular pipette/camera starting point.",
                    }
                ],
            }
        ), {"prompt_tokens": 0, "completion_tokens": 0}
    return await browser_stub_server._fake_generate_turn(project, message, history)


async def proposal(project, instruction, feedback):
    await asyncio.sleep(0.2)
    return {
        "schema_version": "1",
        "link_lengths_mm": [400, 400],
        "mast_height_mm": 450,
        "rationale": "Offline browser fixture: inspect the sample rack with a sidecar arm.",
        "assumptions": ["Synthetic proposal, not a live provider response."],
    }, {"model": "offline-inspection-fixture", "input_tokens": 0, "output_tokens": 0}


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    browser_stub_server.app.api.generate_turn = sourced_turn
    app.design_agent.propose_layout = browser_design_server.fake_proposal
    app.inspection.propose_inspection = proposal
    uvicorn.run(browser_stub_server.app.api.app, host="127.0.0.1", port=args.port)
