"""Shareable deterministic project inputs, never model-provider responses."""

from app.design_spec import apply_candidate
from app.domain import apply_update, new_project


def layout_project(*, cooling=False):
    project = apply_update(
        new_project(),
        {
            "workflow_kind": "liquid_preparation",
            "brief_process": "Preparing dilutions",
            "stock_concentration": "10 mM",
            "target_concentrations": "1 mM, 2 mM",
            "final_volume": "100 uL",
            "equipment": "pipette and tubes",
            "cooling_enabled": cooling,
        },
    )
    proposal = {
        "schema_version": "1",
        "deck_width_mm": 600,
        "deck_depth_mm": 400,
        "placements": [
            {"component_id": "source-rack", "x_mm": -180, "z_mm": -50},
            {"component_id": "sample-rack", "x_mm": -65, "z_mm": -50},
            {"component_id": "tip-rack", "x_mm": 50, "z_mm": -50},
            {"component_id": "tip-waste", "x_mm": 165, "z_mm": 80},
            {"component_id": "controller", "x_mm": 165, "z_mm": -50},
        ],
        "rationale": "Offline synthetic layout for project continuity checks.",
        "assumptions": [],
    }
    return apply_candidate(project, proposal, {"model": "offline-layout-fixture", "run_id": "test"})


def inspection_proposal():
    return {
        "schema_version": "1",
        "link_lengths_mm": [400, 400],
        "mast_height_mm": 450,
        "rationale": "Offline inspection proposal; no provider request.",
        "assumptions": [],
    }
