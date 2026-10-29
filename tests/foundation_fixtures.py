"""Explicit offline proposals; these fixtures are not Meta or hardware evidence."""

from app.domain import apply_update, new_project
from app.engineering import EngineeringUpdate, apply_engineering_update


def liquid_project():
    project = apply_update(
        new_project(),
        {
            "workflow_kind": "liquid_preparation",
            "equipment": "pipette and tubes",
            "stock_concentration": "10 mg/mL",
            "target_concentrations": "1 mg/mL",
            "final_volume": "1 mL",
        },
    )
    return apply_engineering_update(project, EngineeringUpdate(
        platform_choice="jubilee", choice_source="Use Jubilee"), "Use Jubilee")


def source_proposal(drop=100):
    positions = {
        "source-rack": (-80, -85),
        "sample-rack": (80, -85),
        "tip-rack": (-80, 0),
        "tip-waste": (0, 100),
        "controller": (80, 5),
    }
    return {
        "schema_version": "1",
        "deck_width_mm": 300,
        "deck_depth_mm": 300,
        "bed_drop_mm": drop,
        "placements": [
            {"component_id": cid, "x_mm": x, "z_mm": z} for cid, (x, z) in positions.items()
        ],
        "rationale": "Offline fixture with two columns and conservative insert gaps.",
        "assumptions": ["No mounting, travel or hardware verification."],
    }
