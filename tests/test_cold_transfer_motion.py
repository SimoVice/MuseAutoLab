"""Cold-transfer animation follows the accepted plate without changing the holder."""

import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from test_microplates import before, select

from app.cold_transfer import apply_cold_transfer

MODULE = (Path(__file__).resolve().parents[1] / "web/src/coldTransferMotion.ts").as_uri()


def run_motion(project):
    script = f"""
import {{ coldJawOffsetsMm, compileColdTransferMotion, sampleColdTransfer }}
  from {json.dumps(MODULE)};
let input = ''; for await (const chunk of process.stdin) input += chunk;
const project = JSON.parse(input), original = JSON.stringify(project);
const base = {{schema_version: 1, project_id: project.id, revision: project.revision,
  mode: 'cold-transfer', binding: {{}}, status: 'unavailable', message: '',
  duration_s: 0, keyframes: [], limitations: []}};
const plan = compileColdTransferMotion(project, project.cold_transfer_extension, base);
const samples = Array.from({{length: 165}}, (_, i) => sampleColdTransfer(plan, i / 10));
const gripper = project.cold_transfer_extension.components.find(
  p => p.id === 'cold-transfer-gripper');
const length = project.labware_plate.profile.source_dimensions_mm[0];
const jaws = [coldJawOffsetsMm(gripper, length, 0), coldJawOffsetsMm(gripper, length, 1)];
process.stdout.write(JSON.stringify({{plan, samples, jaws,
  unchanged: original === JSON.stringify(project)}}));
"""
    result = subprocess.run(
        [shutil.which("node"), "--input-type=module", "--eval", script],
        input=json.dumps(project),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    result = json.loads(result.stdout)
    assert result["unchanged"]
    return result


def test_pickup_transfer_release_is_continuous_and_seekable():
    project = select(before())
    project["summary"]["workspace_width_mm"] = None
    project = apply_cold_transfer(project)
    result = run_motion(project)
    plan, samples = result["plan"], result["samples"]
    assert plan["status"] == "ready", plan["message"]
    extension = project["cold_transfer_extension"]
    assert samples[0]["payload_position_mm"] == pytest.approx(extension["pickup_mm"])
    assert samples[-1]["payload_position_mm"] == pytest.approx(extension["storage_mm"])
    assert samples[47]["jaw_open"] == pytest.approx(0)
    assert samples[104]["jaw_open"] == pytest.approx(1)
    assert samples[25]["lid_open"] == pytest.approx(1)
    assert samples[-1]["lid_open"] == pytest.approx(0)
    assert samples[0]["jubilee_park_mm"] == [0, 0]
    assert abs(samples[15]["jubilee_park_mm"][1]) == 140
    assert samples[139]["jubilee_park_mm"] == samples[15]["jubilee_park_mm"]
    assert samples[-1]["jubilee_park_mm"] == [0, 0]
    for sample in samples[47:105]:
        assert sample["payload_position_mm"] == pytest.approx(sample["position_mm"])
    for a, b in zip(samples, samples[1:]):
        assert (
            max(abs(x - y) for x, y in zip(a["payload_position_mm"], b["payload_position_mm"]))
            < 100
        )
    for sample in samples[105:]:
        assert sample["payload_position_mm"] == pytest.approx(extension["storage_mm"])


def test_preview_rejects_invalid_binding_or_failed_check():
    project = select(before())
    project["summary"]["workspace_width_mm"] = None
    project = apply_cold_transfer(project)
    bad = deepcopy(project)
    bad["cold_transfer_extension"]["pickup_mm"][0] += 20
    assert run_motion(bad)["plan"]["status"] == "unavailable"
    bad = deepcopy(project)
    bad["cold_transfer_extension"]["checks"][0]["passed"] = False
    assert run_motion(bad)["plan"]["status"] == "unavailable"
    bad = deepcopy(project)
    bad["labware_plate"]["compatibility"]["status"] = "volume_conflict"
    assert run_motion(bad)["plan"]["status"] == "unavailable"
    bad = deepcopy(project)
    shelf = next(
        p for p in bad["cold_transfer_extension"]["components"] if p["id"] == "cold-transfer-shelf"
    )
    shelf["position"][1] -= 30
    assert run_motion(bad)["plan"]["status"] == "unavailable"


def test_gripper_jaws_reach_plate_without_crossing_holder_lip():
    project = select(before())
    project["summary"]["workspace_width_mm"] = None
    project = apply_cold_transfer(project)
    extension = project["cold_transfer_extension"]
    sample = next(p for p in project["design"]["components"] if p["id"] == "sample-rack")
    gripper = next(p for p in extension["components"] if p["id"] == "cold-transfer-gripper")
    primitives = {p["id"]: p for p in gripper["geometry"]["primitives"]}
    shaft = next(p for p in extension["components"] if p["id"] == "cold-transfer-shaft")
    carriage = next(p for p in extension["components"] if p["id"] == "cold-transfer-carriage")
    assert shaft["position"][1] + shaft["size"][1] / 2 == pytest.approx(
        carriage["position"][1] - carriage["size"][1] / 2
    )
    assert shaft["position"][1] - shaft["size"][1] / 2 == pytest.approx(
        gripper["position"][1] + primitives["gripper-bridge"]["size"][1] / 2
    )
    closed, opened = run_motion(project)["jaws"]
    plate_half = project["labware_plate"]["profile"]["source_dimensions_mm"][0] / 2
    assert primitives["gripper-jaw-left"]["position"][0] + primitives["gripper-jaw-left"]["size"][
        0
    ] / 2 + closed[0] == pytest.approx(-plate_half)
    assert primitives["gripper-jaw-right"]["position"][0] - primitives["gripper-jaw-right"]["size"][
        0
    ] / 2 + closed[1] == pytest.approx(plate_half)
    assert opened[0] == pytest.approx(closed[0] - 10)
    assert opened[1] == pytest.approx(closed[1] + 10)
    holder = [
        p
        for p in sample["geometry"]["primitives"]
        if p["id"].startswith("holder-") and p["id"] != "holder-floor"
    ]
    holder_top = max(p["position"][1] + p["size"][1] / 2 for p in holder)
    bridge_bottom = (
        gripper["position"][1]
        + primitives["gripper-bridge"]["position"][1]
        - primitives["gripper-bridge"]["size"][1] / 2
    )
    pickup_delta = extension["pickup_mm"][1] - extension["transfer_height_mm"]
    for name in ("gripper-jaw-left", "gripper-jaw-right"):
        jaw = primitives[name]
        bottom = gripper["position"][1] + jaw["position"][1] - jaw["size"][1] / 2
        top = gripper["position"][1] + jaw["position"][1] + jaw["size"][1] / 2
        assert bottom + pickup_delta >= sample["position"][1] + holder_top
        assert top == pytest.approx(bridge_bottom)


def test_inspection_arm_parks_during_transfer_and_returns():
    project = select(before(arm=True))
    project["summary"]["workspace_width_mm"] = None
    project = apply_cold_transfer(project)
    result = run_motion(project)
    assert result["plan"]["status"] == "ready", result["plan"]["message"]
    parked = result["plan"]["inspection_park_frame"]
    assert parked
    initial = project["inspection_extension"]["pose_frames"][0]["camera_mm"]
    assert parked["camera_mm"] != initial
    assert result["samples"][0]["inspection_park_ratio"] == 0
    assert result["samples"][15]["inspection_park_ratio"] == 1
    assert result["samples"][139]["inspection_park_ratio"] == 1
    assert result["samples"][-1]["inspection_park_ratio"] == 0


def test_inspection_without_valid_poses_gates_transfer():
    project = select(before(arm=True))
    project["summary"]["workspace_width_mm"] = None
    project = apply_cold_transfer(project)
    project["inspection_extension"]["pose_frames"] = []
    plan = run_motion(project)["plan"]
    assert plan["status"] == "unavailable"
    assert "parking pose" in plan["message"]
