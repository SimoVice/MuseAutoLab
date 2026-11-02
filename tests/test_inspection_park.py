"""Inspection parking checks against real canonical project geometry (no robot validation)."""

import json
import math
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from evolution_fixtures import inspection_proposal
from test_microplates import before, select

from app.cold_transfer import apply_cold_transfer
from app.inspection import apply_extension

ROOT = Path(__file__).resolve().parents[1]


def project_fixture():
    project = select(before())
    project["summary"]["workspace_width_mm"] = None
    return apply_cold_transfer(apply_extension(project, inspection_proposal(), {}))


def park(project):
    program = r"""import {chooseInspectionPark} from './web/src/inspectionPark.ts';
let input=''; for await (const chunk of process.stdin) input += chunk;
const project=JSON.parse(input), original=JSON.stringify(project);
const pose=chooseInspectionPark(project);
process.stdout.write(JSON.stringify({pose, unchanged: original === JSON.stringify(project)}));"""
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", program],
        cwd=ROOT,
        input=json.dumps(project),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["unchanged"]
    return out["pose"]


def test_park_uses_same_ik_branch_and_clears_transfer_corridor():
    project = project_fixture()
    frame = park(project)
    assert frame is not None
    components = {part["id"]: part for part in frame["components"]}
    shoulder = components["inspection-shoulder"]["position"]
    elbow = components["inspection-elbow"]["position"]
    camera = components["inspection-camera"]["position"]
    lengths = project["inspection_extension"]["proposal"]["link_lengths_mm"]
    assert math.dist([shoulder[0], shoulder[2]], [elbow[0], elbow[2]]) == pytest.approx(lengths[0])
    assert math.dist([elbow[0], elbow[2]], [camera[0], camera[2]]) == pytest.approx(lengths[1])
    assert camera == pytest.approx(frame["camera_mm"])
    angle = math.radians(frame["joint_angles_deg"]["shoulder"])
    assert elbow[0] == pytest.approx(shoulder[0] + lengths[0] * math.cos(angle))
    assert elbow[2] == pytest.approx(shoulder[2] + lengths[0] * math.sin(angle))
    # Compare against the other valid inverse-kinematics branch: canonical
    # selection has the smaller elbow X, including for the new park target.
    dx, dz = camera[0] - shoulder[0], camera[2] - shoulder[2]
    q2 = math.radians(frame["joint_angles_deg"]["elbow"])
    opposite = math.atan2(dz, dx) - math.atan2(
        -lengths[1] * math.sin(q2), lengths[0] + lengths[1] * math.cos(q2)
    )
    assert elbow[0] <= shoulder[0] + lengths[0] * math.cos(opposite) + 1e-7
    cold = project["cold_transfer_extension"]
    gripper = next(p for p in cold["components"] if p["id"] == "cold-transfer-gripper")
    # Every sampled point of the actual link spans and camera/wrist envelopes is
    # outside the XZ gripper sweep, allowing for their half-widths and margin.
    x_min = min(cold["pickup_mm"][0], cold["storage_mm"][0]) - gripper["size"][0] / 2 - 5
    x_max = max(cold["pickup_mm"][0], cold["storage_mm"][0]) + gripper["size"][0] / 2 + 5
    z_min = cold["pickup_mm"][2] - gripper["size"][2] / 2 - 5
    z_max = cold["pickup_mm"][2] + gripper["size"][2] / 2 + 5
    for start, end, name in [
        (shoulder, elbow, "inspection-upper-link"),
        (elbow, camera, "inspection-forearm"),
    ]:
        half_width = components[name]["geometry"]["primitives"][0]["size"][2] / 2
        for i in range(201):
            x = start[0] + (end[0] - start[0]) * i / 200
            z = start[2] + (end[2] - start[2]) * i / 200
            assert not (
                x_min - half_width <= x <= x_max + half_width
                and z_min - half_width <= z <= z_max + half_width
            )
    for name in ("inspection-wrist", "inspection-camera", "inspection-camera-mount"):
        part = components[name]
        r = math.hypot(part["size"][0], part["size"][2]) / 2
        x, z = part["position"][0], part["position"][2]
        assert not (x_min - r <= x <= x_max + r and z_min - r <= z <= z_max + r)


def test_impossible_or_malformed_layout_returns_none():
    original = project_fixture()
    cases = []
    p = deepcopy(original)
    gripper = next(
        p for p in p["cold_transfer_extension"]["components"] if p["id"] == "cold-transfer-gripper"
    )
    gripper["size"] = [10000, 10000, 10000]
    cases.append(p)
    p = deepcopy(original)
    p["inspection_extension"]["proposal"]["link_lengths_mm"] = [1, 1]
    cases.append(p)
    p = deepcopy(original)
    p["inspection_extension"]["pose_frames"][1]["components"][4]["position"][0] += 100
    cases.append(p)
    p = deepcopy(original)
    p["cold_transfer_extension"]["components"] = [
        c for c in p["cold_transfer_extension"]["components"] if c["id"] != "cold-transfer-shaft"
    ]
    cases.append(p)
    p = deepcopy(original)
    p["cold_transfer_extension"]["assembly_bounds"]["max_mm"][2] = (
        p["cold_transfer_extension"]["assembly_bounds"]["min_mm"][2] + 10
    )
    cases.append(p)
    p = deepcopy(original)
    p["summary"]["workspace_width_mm"] = 100
    cases.append(p)
    p = deepcopy(original)
    gripper = next(
        part
        for part in p["cold_transfer_extension"]["components"]
        if part["id"] == "cold-transfer-gripper"
    )
    gripper["size"][0] = 20  # declared envelope no longer contains its jaws
    cases.append(p)
    p = deepcopy(original)
    gripper = next(
        part
        for part in p["cold_transfer_extension"]["components"]
        if part["id"] == "cold-transfer-gripper"
    )
    shoulder = next(
        part
        for part in p["inspection_extension"]["pose_frames"][0]["components"]
        if part["id"] == "inspection-shoulder"
    )
    gripper["position"][1] = shoulder["position"][
        1
    ]  # crosses the starting inspection pose during parking
    cases.append(p)
    assert all(park(p) is None for p in cases)
