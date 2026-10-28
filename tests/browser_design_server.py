"""Offline browser fixture: real design loop/compiler, deterministic model proposals."""

import argparse
from copy import deepcopy

import browser_stub_server

import app.design_agent


def candidate():
    return {
        "schema_version": "1",
        "deck_width_mm": 500,
        "deck_depth_mm": 480,
        "placements": [
            {"component_id": "source-rack", "x_mm": -160, "z_mm": 55},
            {"component_id": "sample-rack", "x_mm": -45, "z_mm": 55},
            {"component_id": "tip-rack", "x_mm": 70, "z_mm": 55},
            {"component_id": "tip-waste", "x_mm": 200, "z_mm": 65},
            {"component_id": "controller", "x_mm": 195, "z_mm": -90},
        ],
        "rationale": "Offline fixture: keep the sample rack at the front of the deck.",
        "assumptions": ["Synthetic model response; no provider request or hardware test."],
    }


async def fake_proposal(project, instruction, feedback, **kwargs):
    limit = project.get("summary", {}).get("workspace_width_mm")
    raw = deepcopy(
        browser_stub_server._fixture_layout(project) if limit and limit < 500 else candidate()
    )
    if "reject" in instruction.lower() or ("correction" in instruction.lower() and not feedback):
        first = raw["placements"][0]
        raw["placements"][1].update(x_mm=first["x_mm"], z_mm=first["z_mm"])
    return raw, {"model": "offline-model-fixture", "input_tokens": 0, "output_tokens": 0}


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    browser_stub_server.app.api.generate_turn = browser_stub_server._fake_generate_turn
    app.design_agent.propose_layout = fake_proposal
    uvicorn.run(browser_stub_server.app.api.app, host="127.0.0.1", port=args.port)
