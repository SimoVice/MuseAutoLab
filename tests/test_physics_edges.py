"""Edge tests for the bounded MuJoCo physics runtime (real dynamics only)."""

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from copy import deepcopy

from app import physics
from app.domain import apply_update, confirm_project, new_project


def _confirmed(targets="1, 2 mM", width=600, cooling=False):
    return confirm_project(
        apply_update(
            new_project(),
            {
                "stock_concentration": "10 mM",
                "target_concentrations": targets,
                "final_volume": "100 uL",
                "equipment": "Manual pipette and tubes",
                "workspace_width_mm": width,
                "cooling_enabled": cooling,
            },
        )
    )


def test_six_target_run_within_bounds():
    project = _confirmed(targets="1, 2, 3, 4, 5, 6 mM")
    result = physics.simulate_project(project)
    assert result["status"] == "passed"
    assert result["duration_s"] <= physics.MAX_SIM_S <= 300.0
    assert len(result["frames"]) <= physics.MAX_FRAMES <= 6500
    assert result["planned_integration_steps"] // physics.SAMPLE_STRIDE + 2 <= 6500
    assert result["metrics"]["completed_waypoints"] == result["metrics"]["total_waypoints"]
    assert all(math.isfinite(v) for v in result["frames"][0]["carriage_mm"])


def test_insufficient_height_rejects_without_false_completion():
    project = _confirmed()
    broken = deepcopy(project)
    broken["design"]["footprint"]["height_mm"] = 20.0
    try:
        result = physics.simulate_project(broken)
    except ValueError:
        return
    assert result["status"] == "failed"
    assert result["metrics"]["completed_waypoints"] < result["metrics"]["total_waypoints"]
    assert not all(check["passed"] for check in result["checks"])


def test_zero_volume_transfers_never_logged():
    project = _confirmed(targets="0, 10 mM")
    waypoints, _, _, _ = physics._plan_motion(project)
    holds = [w for w in waypoints if "logical hold" in w["phase"]]
    assert holds, "expected logical holds for the nonzero transfer"
    assert all(h["volume_ul"] is not None and h["volume_ul"] > 0 for h in holds)
    assert all(h["transfer_id"] and h["volume_ul"] for h in holds)
    expected = sum(
        1
        for s in project["plan"]["steps"]
        for k in ("stock_volume_ul", "diluent_volume_ul")
        if s[k] > 0
    )
    assert len({h["transfer_id"] for h in holds}) == expected


def test_xml_finite_engine_identity_and_frozen_input():
    import mujoco

    project = _confirmed()
    snapshot = deepcopy(project)
    result = physics.simulate_project(project)
    assert project == snapshot
    assert result["engine"] == "MuJoCo" and result["engine_version"] == "3.17.0"
    assert result["model_version"] == physics.MODEL_VERSION
    root = ET.fromstring(result["model_xml"])
    assert root.find("option").get("integrator") == "implicitfast"
    # MuJoCo omits attributes equal to defaults when serializing the model.
    model = mujoco.MjModel.from_xml_string(result["model_xml"])
    assert model.opt.timestep == physics.TIMESTEP_S
    for frame in result["frames"]:
        for key in ("carriage_mm", "pipette_mm", "tip_mm", "target_mm"):
            assert all(math.isfinite(v) for v in frame[key])
    assert all(
        math.isfinite(result["metrics"][k])
        for k in ("max_tracking_error_mm", "final_tracking_error_mm", "max_contact_force_n")
    )
    assert all(math.isfinite(v) for v in result["metrics"]["peak_actuator_force_n"])
    expected = hashlib.sha256(
        json.dumps(
            {"project": snapshot, "scenario": "nominal"}, sort_keys=True, allow_nan=False
        ).encode()
    ).hexdigest()
    assert result["input_sha256"] == expected
    json.dumps(result, allow_nan=False)
