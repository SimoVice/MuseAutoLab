"""Execute the actual TypeScript motion compiler against canonical Python projects.

These tests check illustrative timeline bindings and arithmetic, not collisions,
fluid motion, calibration, source robot control or experimental performance.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from test_microplates import before, select
from test_tip_racks import OPENTRONS, TIPONE, selected

ROOT = Path(__file__).resolve().parents[1]
COMPILER = (ROOT / "web/src/motionPlan.ts").as_uri()


def compile_plan(project, mode="preparation"):
    node = shutil.which("node")
    assert node, "The pinned Node 24 toolchain is required"
    script = f"""
import {{ compileMotionPlan, sampleMotionPlan, availableTipSlots, SOURCE_TUBE_MOUTH_ABOVE_RACK_MM,
  PREVIEW_APPROACH_CLEARANCE_MM, SCHEMATIC_TIP_TOP_ABOVE_RACK_MM }}
  from {json.dumps(COMPILER)};
let input = ''; for await (const chunk of process.stdin) input += chunk;
const project = JSON.parse(input), original = JSON.stringify(project);
const plan = compileMotionPlan(project, {json.dumps(mode)});
const samples = [-1, 0, plan.duration_s / 2, plan.duration_s + 1, NaN].map(
  time => sampleMotionPlan(plan, time));
const rack = project.design.components.find(p => p.id === 'tip-rack');
const count = rack?.geometry?.primitives.find(p => p.holes?.length)?.holes.length ?? 0;
const inventory = plan.keyframes.filter(f => ['Pick up tip', 'Manual refill'].includes(f.stage))
  .map(f => ({{frame: f, before: availableTipSlots(plan, f.time_s - 0.001, count),
    after: availableTipSlots(plan, f.time_s, count)}}));
process.stdout.write(JSON.stringify({{plan, samples, inventory, constants: {{
  source_mouth: SOURCE_TUBE_MOUTH_ABOVE_RACK_MM,
  clearance: PREVIEW_APPROACH_CLEARANCE_MM,
  schematic_tip: SCHEMATIC_TIP_TOP_ABOVE_RACK_MM}},
  unchanged: original === JSON.stringify(project)}}));
"""
    result = subprocess.run(
        [node, "--input-type=module", "--eval", script],
        input=json.dumps(project),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["unchanged"], "Compiler/sampler mutated canonical input"
    return output


def parts(project):
    return {part["id"]: part for part in project["design"]["components"]}


def world_hole(part, index=0):
    top = next(p for p in part["geometry"]["primitives"] if p.get("holes"))
    hole = top["holes"][index]
    return [
        part["position"][0] + top["position"][0] + hole["x_mm"],
        part["position"][1] + top["position"][1] + top["size"][1] / 2,
        part["position"][2] + top["position"][2] + hole["z_mm"],
    ]


@pytest.mark.parametrize("plate", [False, True])
@pytest.mark.parametrize("profile", [None, TIPONE, OPENTRONS])
def test_bound_targets_tips_source_arithmetic_and_read_only_revision(plate, profile):
    project = before()
    if plate:
        project = select(project)
    if profile:
        project = selected(project, profile)
    original = deepcopy(project)
    output = compile_plan(project)
    constants = output["constants"]
    assert constants == {"source_mouth": 20, "clearance": 3, "schematic_tip": 14}
    plan = output["plan"]
    assert plan["status"] == "ready", plan["message"]
    assert plan["project_id"] == project["id"] and plan["revision"] == project["revision"]
    binding = plan["binding"]
    assert binding["foundation_source_sha256"] == project["design"]["foundation"]["source_sha256"]
    assert binding["foundation_id"] == project["design"]["foundation"]["id"]
    assert binding["component_ids"] == [part["id"] for part in project["design"]["components"]]
    assert binding["tip_profile_id"] == profile
    assert binding["plate_profile_id"] == (
        project["labware_plate"]["profile_id"] if plate else None
    )
    assert project == original
    frames = plan["keyframes"]
    assert frames[0]["stage"] == "Ready" and frames[-1]["stage"] == "Complete"
    assert all(b["time_s"] > a["time_s"] for a, b in zip(frames, frames[1:]))
    p = parts(project)
    dispense = [f for f in frames if f["stage"] == "Dispense"]
    expected_volumes = [
        volume
        for step in project["plan"]["steps"]
        for volume in (step["stock_volume_ul"], step["diluent_volume_ul"])
        if volume > 0
    ]
    assert [f["volume_ul"] for f in dispense] == expected_volumes
    first = dispense[0]
    if plate:
        label = project["labware_plate"]["compatibility"]["occupied_wells"][0]
        well = next(w for w in project["labware_plate"]["derived"]["wells"] if w["label"] == label)
        expected = [
            p["sample-rack"]["position"][i] + well[key]
            for i, key in enumerate(("app_x_mm", "app_y_mm", "app_z_mm"))
        ]
        assert first["destination_id"] == label
    else:
        expected = world_hole(p["sample-rack"])
        expected[1] = p["sample-rack"]["position"][1] + p["sample-rack"]["size"][1] / 2 + 3
        assert first["destination_id"] == "tube-1"
    assert first["position_mm"] == pytest.approx(expected)
    pickup = next(f for f in frames if f["stage"] == "Pick up tip")
    tip_point = world_hole(p["tip-rack"])
    tip_point[1] = p["tip-rack"]["position"][1] + p["tip-rack"]["size"][1] / 2 + 14 - 22
    assert pickup["position_mm"] == pytest.approx(tip_point)
    assert pickup["tip_attached"]
    aspirate = next(f for f in frames if f["stage"] == "Aspirate")
    source_point = world_hole(p["source-rack"])
    source_point[1] = p["source-rack"]["position"][1] + p["source-rack"]["size"][1] / 2 + 23
    assert aspirate["position_mm"] == pytest.approx(source_point)
    assert not frames[-1]["tip_attached"]
    limits = " ".join(plan["limitations"]).lower()
    assert "must be open" in limits and "caps are not operated" in limits
    assert "no collision" in limits and "physical validation" in limits
    assert output["samples"][0]["position_mm"] == frames[0]["position_mm"]
    assert output["samples"][3]["position_mm"] == frames[-1]["position_mm"]


def test_zero_volume_skips_transfer_and_stations():
    project = before()
    for step in project["plan"]["steps"]:
        step["stock_volume_ul"] = 0
        step["diluent_volume_ul"] = step["total_volume_ul"]
    plan = compile_plan(project)["plan"]
    assert plan["status"] == "ready"
    aspirates = [f for f in plan["keyframes"] if f["stage"] == "Aspirate"]
    assert len(aspirates) == len(project["plan"]["steps"])
    assert all(f["target"] == "Diluent" for f in aspirates)


@pytest.mark.parametrize("plate", [False, True])
def test_hardware_only_preview_keeps_illustrative_recipe_local(plate):
    project = select(before()) if plate else before()
    project["summary"].update(
        stock_concentration=None, target_concentrations=None, final_volume=None
    )
    project["plan"].update(status="incomplete", steps=[])
    original = deepcopy(project)
    plan = compile_plan(project)["plan"]
    assert project == original
    assert plan["status"] == "ready", plan["message"]
    assert plan["scope"] == "illustrative"
    assert "illustrative" in plan["message"].lower()
    assert plan["illustrative_recipe"] == {
        "stock": "1 mg/mL", "target": "0.5 mg/mL", "final_volume_ul": 100,
        "stock_volume_ul": 50, "diluent_volume_ul": 50,
    }
    assert [f["volume_ul"] for f in plan["keyframes"] if f["stage"] == "Dispense"] == [50, 50]
    assert [frame["stage"] for frame in plan["keyframes"]].count("Aspirate") == 2
    assert [frame["stage"] for frame in plan["keyframes"]].count("Dispense") == 2
    assert plan["binding"]["plate_profile_id"] == (
        project["labware_plate"]["profile_id"] if plate else None
    )


@pytest.mark.parametrize("field", ["stock_concentration", "target_concentrations", "final_volume"])
@pytest.mark.parametrize("status", ["incomplete", "invalid"])
def test_started_incomplete_or_invalid_recipe_never_uses_illustrative_fallback(field, status):
    project = before()
    project["summary"].update(
        stock_concentration=None, target_concentrations=None, final_volume=None
    )
    project["summary"][field] = "1 mM"
    project["plan"].update(status=status, steps=[])
    plan = compile_plan(project)["plan"]
    assert plan["scope"] == "recipe"
    assert plan["status"] == "unavailable"
    assert not plan["keyframes"]


def test_ready_recipe_supersedes_illustration_at_next_revision():
    project = before()
    recipe = deepcopy(project)
    project["summary"].update(
        stock_concentration=None, target_concentrations=None, final_volume=None
    )
    project["plan"].update(status="incomplete", steps=[])
    illustrative = compile_plan(project)["plan"]
    recipe["revision"] = project["revision"] + 1
    actual = compile_plan(recipe)["plan"]
    assert illustrative["scope"] == "illustrative"
    assert actual["scope"] == "recipe" and actual["status"] == "ready"
    assert "illustrative_recipe" not in actual
    assert all("example" not in frame["target"] for frame in actual["keyframes"])
    assert actual["revision"] != illustrative["revision"]
    assert [f["volume_ul"] for f in actual["keyframes"] if f["stage"] == "Dispense"] == [
        volume for step in recipe["plan"]["steps"]
        for volume in (step["stock_volume_ul"], step["diluent_volume_ul"]) if volume > 0
    ]


@pytest.mark.parametrize("state", ["ready", "incomplete", "invalid", "missing"])
def test_legacy_project_motion_requires_valid_recipe_or_unstarted_example(state):
    project = before()
    project.pop("design_workflow", None)
    project.pop("machine_approval", None)
    if state != "ready":
        project["summary"].update(
            stock_concentration=None, target_concentrations=None, final_volume=None
        )
        project["plan"] = None if state == "missing" else {"status": state, "steps": []}
    plan = compile_plan(project)["plan"]
    if state == "ready":
        assert plan["status"] == "ready" and plan["scope"] == "recipe"
        assert "illustrative_recipe" not in plan
    elif state == "incomplete":
        assert plan["status"] == "ready" and plan["scope"] == "illustrative"
    else:
        assert plan["status"] == "unavailable" and not plan["keyframes"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.pop("engineering_design"),
        lambda p: p["workflow"].update(kind="general"),
        lambda p: p["plan"].update(status="invalid"),
        lambda p: p["design"].update(foundation=None, platform={"id": "opentrons-ot2"}),
        lambda p: p["design"].update(components=[]),
        lambda p: p["plan"].update(steps=[]),
        lambda p: p["plan"]["steps"][0].update(stock_volume_ul=-1),
        lambda p: p["plan"]["steps"][0].update(total_volume_ul=1),
        lambda p: parts(p)["sample-rack"]["position"].__setitem__(0, 10000),
    ],
)
def test_unsupported_or_invalid_bindings_stay_unavailable(mutation):
    project = before()
    mutation(project)
    plan = compile_plan(project)["plan"]
    assert plan["status"] == "unavailable" and plan["message"]
    assert plan["keyframes"] == []


def test_missing_or_invalid_plate_well_is_unavailable():
    project = select(before())
    project["labware_plate"]["compatibility"]["occupied_wells"][0] = "Z99"
    assert compile_plan(project)["plan"]["status"] == "unavailable"


def test_inspection_uses_canonical_camera_sequence_and_rejects_bad_times():
    project = before(arm=True)
    plan = compile_plan(project, "inspection")["plan"]
    assert plan["status"] == "ready", plan["message"]
    poses = project["inspection_extension"]["pose_frames"]
    assert [f["position_mm"] for f in plan["keyframes"]] == [f["camera_mm"] for f in poses]
    project["inspection_extension"]["pose_frames"][1]["time_s"] = 0
    assert compile_plan(project, "inspection")["plan"]["status"] == "unavailable"


def test_jubilee_reference_pose_127_5_and_fixed_tip_bed_mapping():
    project = selected(before(), OPENTRONS)
    assert project["design"]["foundation"]["bed_drop_mm"] == 127.5
    plan = compile_plan(project)["plan"]
    assert plan["status"] == "ready", plan["message"]
    p = parts(project)
    home_y = p["pipette"]["position"][1] - p["pipette"]["size"][1] / 2 - 22
    for frame in plan["keyframes"]:
        drop = 127.5 + frame["position_mm"][1] - home_y
        assert 0 <= drop <= 150
        # Moving the stations by the opposite amount keeps the virtual tip
        # at one fixed vertical machine height, as required by this platform.
        shifted_station_y = frame["position_mm"][1] - (drop - 127.5)
        assert shifted_station_y == pytest.approx(home_y)


@pytest.mark.parametrize("drop", [-1, 151])
def test_invalid_bed_pose_is_unavailable(drop):
    project = before()
    project["design"]["foundation"]["bed_drop_mm"] = drop
    assert compile_plan(project)["plan"]["status"] == "unavailable"


def test_tall_tip_rack_exceeding_bed_pose_is_unavailable_without_mutation():
    project = selected(before(), OPENTRONS)
    # Deliberately synthetic overheight envelope: no manufacturer dimension claim.
    parts(project)["tip-rack"]["position"][1] += 100
    plan = compile_plan(project)["plan"]
    assert plan["status"] == "unavailable"
    assert "bed-pose envelope" in plan["message"]


@pytest.mark.parametrize("profile", [None, TIPONE, OPENTRONS])
def test_tip_inventory_handoff_refill_and_backward_seek(profile):
    project = before()
    if profile:
        project = selected(project, profile)
    else:
        top = next(
            p for p in parts(project)["tip-rack"]["geometry"]["primitives"] if p.get("holes")
        )
        top["holes"] = top["holes"][:2]
    output = compile_plan(project)
    assert output["plan"]["status"] == "ready"
    inventory = output["inventory"]
    pickups = [event for event in inventory if event["frame"]["stage"] == "Pick up tip"]
    assert pickups
    for event in pickups:
        slot = event["frame"]["tip_slot"]
        assert event["before"][slot] and not event["after"][slot]
        assert sum(event["before"]) - sum(event["after"]) == 1
    refills = [event for event in inventory if event["frame"]["stage"] == "Manual refill"]
    if profile is None:
        assert refills
        assert all(all(event["after"]) and not any(event["before"]) for event in refills)
    # Sampling before the first pickup reconstructs the full inventory, even after a later sample.
    assert all(pickups[0]["before"])


def test_custom_holder_uses_exact_holes_and_manual_refill():
    from test_tip_racks import SPEC

    from app.tip_racks import PRINTED_ID, TipRackUpdate, select_tip_rack

    project = before()
    project["fabrication_capabilities"] = {
        "printer_available": "yes",
        "source": "I have a 3D printer",
    }
    project["tip_rack_request"] = {
        "profile_id": PRINTED_ID,
        "spec": SPEC,
        "spec_sources": {key: "synthetic test fixture" for key in SPEC},
    }
    project, _ = select_tip_rack(
        project, TipRackUpdate(), "Use the printed holder", accept_placement=True
    )
    output = compile_plan(project)
    plan = output["plan"]
    assert plan["status"] == "ready", plan["message"]
    tips = parts(project)["tip-rack"]
    pickup = next(f for f in plan["keyframes"] if f["stage"] == "Pick up tip")
    expected = world_hole(tips)
    expected[1] = tips["position"][1] + tips["size"][1] / 2 + 14 - 22
    assert pickup["position_mm"] == pytest.approx(expected)
    for event in output["inventory"]:
        if event["frame"]["stage"] == "Pick up tip":
            slot = event["frame"]["tip_slot"]
            assert event["before"][slot] and not event["after"][slot]
