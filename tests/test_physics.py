"""Real CPU MuJoCo checks, independent of the job/UI stubs."""

import hashlib
import json
import math
import subprocess
import sys
from copy import deepcopy

import pytest

from app import physics
from app.domain import apply_update, confirm_project, new_project


def confirmed(width=600, cooling=False, targets="1, 2 mM"):
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


@pytest.fixture(scope="module")
def nominal_cases():
    cases = []
    for width, cooling in ((600, False), (450, False), (450, True)):
        project = confirmed(width, cooling)
        original = deepcopy(project)
        result = physics.simulate_project(project)
        assert project == original
        cases.append((project, result))
    return cases


def test_real_forward_dynamics_and_supported_layouts(nominal_cases):
    for project, result in nominal_cases:
        assert result["status"] == "passed"
        assert result["engine"] == "MuJoCo" and result["engine_version"] == "3.17.0"
        assert result["project_id"] == project["id"] and result["revision"] == project["revision"]
        metrics = result["metrics"]
        assert 0 < metrics["max_tracking_error_mm"] <= 5
        assert 0.5 < metrics["final_tracking_error_mm"] <= 5  # Uncompensated gravity lag.
        assert metrics["completed_waypoints"] == metrics["total_waypoints"] == 68
        assert all(check["passed"] for check in result["checks"])
        assert metrics["contact_count"] == 0
        assert 1 < metrics["peak_actuator_force_n"][2] <= 20
        assert all(
            0 <= f <= limit + 1e-9
            for f, limit in zip(metrics["peak_actuator_force_n"], [15, 15, 20])
        )
        frames = result["frames"]
        assert 10 < len(frames) <= physics.MAX_FRAMES
        assert all(a["time_s"] < b["time_s"] for a, b in zip(frames, frames[1:]))
        assert frames[-1]["time_s"] == pytest.approx(result["duration_s"])
        assert result["duration_s"] <= physics.MAX_SIM_S
        assert result["integration_steps"] * physics.TIMESTEP_S == pytest.approx(
            result["duration_s"]
        )
        assert any(math.dist(f["carriage_mm"], frames[0]["carriage_mm"]) > 100 for f in frames)
        for frame in frames:
            assert all(
                math.isfinite(v)
                for key in ("carriage_mm", "pipette_mm", "tip_mm")
                for v in frame[key]
            )
            assert frame["pipette_mm"][1] - frame["tip_mm"][1] == pytest.approx(96.5)


def test_contact_obstruction_stops_without_completing_future_actions(nominal_cases):
    project, nominal = nominal_cases[0]
    result = physics.simulate_project(project, "blocked_path")
    assert result["status"] == "blocked"
    assert result["metrics"]["max_contact_force_n"] > physics.CONTACT_TOL_N
    assert result["metrics"]["completed_waypoints"] < result["metrics"]["total_waypoints"]
    assert result["integration_steps"] < result["planned_integration_steps"]
    assert result["duration_s"] < nominal["duration_s"]
    assert result["contacts"][0]["component_id"] == "simulation-obstacle"
    assert result["frames"][-1]["time_s"] == pytest.approx(result["duration_s"])
    assert result["input_sha256"] != nominal["input_sha256"]
    assert result["obstacles"][0]["id"] == "simulation-obstacle"


def test_collision_filters_keep_tool_frame_and_head_deck_collisions(nominal_cases):
    import mujoco

    model = mujoco.MjModel.from_xml_string(nominal_cases[0][1]["model_xml"])

    def collide(first, second):
        a, b = model.geom(first), model.geom(second)
        return bool((a.contype & b.conaffinity) or (b.contype & a.conaffinity))

    assert not collide("g_carriage", "g_crossbar")  # Explicit ideal guide interface.
    assert collide("g_pipette", "g_crossbar")
    assert collide("g_carriage", "g_base")
    assert collide("g_carriage", "g_column-left")
    assert collide("g_tip", "g_tip-rack")
    assert model.nq == model.nv == model.nu == 3


def test_planner_handles_nonzero_transfers_and_matches_sample_spacing():
    project = confirmed(targets="0, 10 mM")
    waypoints, _, _, _ = physics._plan_motion(project)
    holds = [point for point in waypoints if "logical hold" in point["phase"]]
    assert len(holds) == 8  # Two transfers, each with tip/source/destination/waste.
    assert len({point["transfer_id"] for point in holds}) == 2
    samples = [
        proxy
        for proxy in physics._proxy_boxes(confirmed(targets="1, 2, 3, 4, 5, 6 mM"))
        if proxy[0].startswith("sample-rack-")
    ]
    assert samples[1][1] - samples[0][1] == pytest.approx(95 / 7)


def test_no_substitute_result_on_invalid_engine_model(monkeypatch):
    with pytest.raises(ValueError):
        physics.simulate_project(new_project())
    with pytest.raises(ValueError):
        physics.simulate_project(confirmed(), "unsupported")
    monkeypatch.setattr(physics, "_model_xml", lambda *args: "<invalid")
    with pytest.raises(ValueError):
        physics.simulate_project(confirmed())


def test_exported_source_reruns_and_preserves_input_hash(nominal_cases, tmp_path):
    project, result = nominal_cases[0]
    files = physics.build_simulation_files(project, result)
    assert (
        hashlib.sha256(files["simulation/engine.py"]).hexdigest() == result["engine_source_sha256"]
    )
    (tmp_path / "project.json").write_text(json.dumps({"project": project}), encoding="utf-8")
    for name, payload in files.items():
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    done = subprocess.run(
        [sys.executable, str(tmp_path / "simulation/run.py")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert done.returncode == 0, done.stderr
    replay = json.loads((tmp_path / "simulation/replay-result.json").read_text(encoding="utf-8"))
    assert replay["status"] == result["status"] == "passed"
    assert replay["metrics"] == result["metrics"]
    assert replay["input_sha256"] == result["input_sha256"]
    changed = deepcopy(project)
    changed["summary"]["equipment"] = "Different equipment"
    with pytest.raises(ValueError, match="hash"):
        physics.build_simulation_files(changed, result)
