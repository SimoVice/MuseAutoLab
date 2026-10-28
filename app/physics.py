"""Bounded MuJoCo forward dynamics for an ideal XYZ liquid-handling head.

Component envelopes and assumed consumable proxies only. No fluid dynamics,
physical tip detachment, hardware control or validated mechanism is represented.
MuJoCo is imported lazily; errors propagate, with no substitute physics engine.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path

TIMESTEP_S = 0.002
SAMPLE_STRIDE = 25
MAX_SIM_S = 300.0
MAX_FRAMES = 6500
KP = 5000.0
KV = 100.0
FORCE_LIMITS = [15.0, 15.0, 20.0]
TRACK_TOL_MM = 5.0
CONTACT_TOL_N = 0.05
MAX_SPEED_MM_S = 100.0
TIP_LENGTH_MM = 19.0
MODEL_VERSION = 1
_SOURCE_BYTES = Path(__file__).read_bytes()


def _cubic(p0, p1, dur):
    def pos(t):
        s = min(max(t / dur, 0.0), 1.0) if dur > 0 else 1.0
        return [p0[i] + (p1[i] - p0[i]) * (3 * s * s - 2 * s * s * s) for i in range(3)]

    return pos


def _app_to_eng_mm_to_m(car_mm):
    x, y, z = car_mm
    return [x / 1000.0, z / 1000.0, y / 1000.0]


def _eng_to_app_car(eng):
    ex, ey, ez = eng
    return [ex * 1000.0, ez * 1000.0, ey * 1000.0]


def _geom_list(project, info, scenario):
    design = project["design"]
    comps = {c["id"]: c for c in design["components"]}
    fixed = []
    for cid in (
        "base",
        "column-left",
        "column-right",
        "crossbar",
        "source-rack",
        "sample-rack",
        "tip-rack",
        "tip-waste",
        "controller",
        "cold-storage",
    ):
        c = comps.get(cid)
        if c is None:
            continue
        fixed.append(c)
    return fixed


def _model_xml(project, info, scenario, axis_ranges):
    (xr, yr, zr) = axis_ranges
    design = project["design"]
    comps = {c["id"]: c for c in design["components"]}
    car = comps["carriage"]
    pip = comps["pipette"]
    car_size = [float(v) / 1000.0 for v in car["size"]]
    pip_size = [float(v) / 1000.0 for v in pip["size"]]
    tip_r = 0.0035
    tip_l = 0.019
    # relative offsets in metres (engine frame: ex=x, ey=z_app, ez=y_app)
    pc = [
        float(pip["position"][0]) - float(car["position"][0]),
        float(pip["position"][2]) - float(car["position"][2]),
        float(pip["position"][1]) - float(car["position"][1]),
    ]
    pc_m = [pc[0] / 1000.0, pc[1] / 1000.0, pc[2] / 1000.0]
    pip_bottom_rel = pc_m[2] - pip_size[1] / 2.0
    tip_center_rel = [pc_m[0], pc_m[1], pip_bottom_rel - tip_l / 2.0]

    def eng_box(c):
        x, y, z = [float(v) / 1000.0 for v in c["position"]]
        sx, sy, sz = [float(v) / 1000.0 for v in c["size"]]
        return ([x, z, y], [sx / 2.0, sz / 2.0, sy / 2.0])

    root = ET.Element("mujoco", {"model": "aliquot-demo"})
    ET.SubElement(
        root,
        "option",
        {"timestep": str(TIMESTEP_S), "integrator": "implicitfast", "gravity": "0 0 -9.81"},
    )
    default = ET.SubElement(root, "default")
    ET.SubElement(default, "geom", {"contype": "0", "conaffinity": "0"})
    ET.SubElement(default, "joint", {"damping": "5"})
    w = ET.SubElement(root, "worldbody")
    # fixed geoms
    fixed = _geom_list(project, info, scenario)
    for c in fixed:
        pos, half = eng_box(c)
        is_frame = c["id"] == "crossbar"
        ct, ca = ("4", "2") if is_frame else ("8", "3")
        if is_frame:
            ct, ca = "4", "2"
        ET.SubElement(
            w,
            "geom",
            {
                "name": f"g_{c['id']}",
                "type": "box",
                "pos": f"{pos[0]} {pos[1]} {pos[2]}",
                "size": f"{half[0]} {half[1]} {half[2]}",
                "contype": ct,
                "conaffinity": ca,
            },
        )
    # proxies (assumed fixed collision proxies)
    for name, cx, cy, cz, r, h in _proxy_boxes(project, info):
        pos = [cx / 1000.0, cz / 1000.0, cy / 1000.0]
        ET.SubElement(
            w,
            "geom",
            {
                "name": f"g_{name}",
                "type": "cylinder",
                "pos": f"{pos[0]} {pos[1]} {pos[2]}",
                "size": f"{r / 1000.0} {h / 2000.0}",
                "contype": "8",
                "conaffinity": "3",
            },
        )
    if scenario == "blocked_path":
        ob = _obstacle(project, info)
        pos = [
            ob["position_mm"][0] / 1000.0,
            ob["position_mm"][2] / 1000.0,
            ob["position_mm"][1] / 1000.0,
        ]
        half = [s / 2000.0 for s in (ob["size_mm"][0], ob["size_mm"][2], ob["size_mm"][1])]
        ET.SubElement(
            w,
            "geom",
            {
                "name": "g_simulation-obstacle",
                "type": "box",
                "pos": f"{pos[0]} {pos[1]} {pos[2]}",
                "size": f"{half[0]} {half[1]} {half[2]}",
                "contype": "8",
                "conaffinity": "3",
            },
        )
    # head body with slide joints
    home = _app_to_eng_mm_to_m([float(v) for v in car["position"]])
    hb = ET.SubElement(w, "body", {"name": "head", "pos": f"{home[0]} {home[1]} {home[2]}"})
    jx_range = [
        (xr[0] - float(car["position"][0])) / 1000.0,
        (xr[1] - float(car["position"][0])) / 1000.0,
    ]
    jy_range = [
        (zr[0] - float(car["position"][2])) / 1000.0,
        (zr[1] - float(car["position"][2])) / 1000.0,
    ]
    jz_range = [
        (yr[0] - float(car["position"][1])) / 1000.0,
        (yr[1] - float(car["position"][1])) / 1000.0,
    ]
    ET.SubElement(
        hb,
        "joint",
        {
            "name": "jx",
            "type": "slide",
            "axis": "1 0 0",
            "limited": "true",
            "range": f"{jx_range[0]} {jx_range[1]}",
        },
    )
    ET.SubElement(
        hb,
        "joint",
        {
            "name": "jy",
            "type": "slide",
            "axis": "0 1 0",
            "limited": "true",
            "range": f"{jy_range[0]} {jy_range[1]}",
        },
    )
    ET.SubElement(
        hb,
        "joint",
        {
            "name": "jz",
            "type": "slide",
            "axis": "0 0 1",
            "limited": "true",
            "range": f"{jz_range[0]} {jz_range[1]}",
        },
    )
    ET.SubElement(
        hb,
        "geom",
        {
            "name": "g_carriage",
            "type": "box",
            "pos": "0 0 0",
            "size": f"{car_size[0] / 2.0} {car_size[2] / 2.0} {car_size[1] / 2.0}",
            "mass": "0.45",
            "contype": "1",
            "conaffinity": "8",
        },
    )
    ET.SubElement(
        hb,
        "geom",
        {
            "name": "g_pipette",
            "type": "cylinder",
            "pos": f"{pc_m[0]} {pc_m[1]} {pc_m[2]}",
            "size": f"{pip_size[0] / 2.0} {pip_size[1] / 2.0}",
            "mass": "0.15",
            "contype": "2",
            "conaffinity": "12",
        },
    )
    ET.SubElement(
        hb,
        "geom",
        {
            "name": "g_tip",
            "type": "cylinder",
            "pos": f"{tip_center_rel[0]} {tip_center_rel[1]} {tip_center_rel[2]}",
            "size": f"{tip_r} {tip_l / 2.0}",
            "mass": "0.001",
            "contype": "2",
            "conaffinity": "12",
        },
    )
    ET.SubElement(
        hb,
        "site",
        {
            "name": "tip_site",
            "pos": f"{tip_center_rel[0]} {tip_center_rel[1]} {tip_center_rel[2] - tip_l / 2.0}",
        },
    )
    act = ET.SubElement(root, "actuator")
    for nm, jn, fl in (
        ("ax", "jx", FORCE_LIMITS[0]),
        ("ay", "jy", FORCE_LIMITS[1]),
        ("az", "jz", FORCE_LIMITS[2]),
    ):
        ET.SubElement(
            act,
            "position",
            {
                "name": nm,
                "joint": jn,
                "kp": str(KP),
                "kv": str(KV),
                "forcelimited": "true",
                "forcerange": f"{-fl} {fl}",
            },
        )
    sens = ET.SubElement(root, "sensor")
    for c in fixed:
        ET.SubElement(
            sens,
            "contact",
            {
                "name": f"contact_{c['id']}",
                "body1": "head",
                "geom2": f"g_{c['id']}",
                "num": "1",
                "data": "found force",
                "reduce": "maxforce",
            },
        )
    for name, *_ in _proxy_boxes(project, info):
        ET.SubElement(
            sens,
            "contact",
            {
                "name": f"contact_{name}",
                "body1": "head",
                "geom2": f"g_{name}",
                "num": "1",
                "data": "found force",
                "reduce": "maxforce",
            },
        )
    if scenario == "blocked_path":
        ET.SubElement(
            sens,
            "contact",
            {
                "name": "contact_simulation-obstacle",
                "body1": "head",
                "geom2": "g_simulation-obstacle",
                "num": "1",
                "data": "found force",
                "reduce": "maxforce",
            },
        )
    xml_body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0"?>\n' + xml_body


def _obstacle(project, info):
    txs = info.get("tip_xs", [0])
    return {
        "id": "simulation-obstacle",
        "label": "Diagnostic blocked-path obstacle (not a project part)",
        "position_mm": [
            float(txs[0]),
            float(info.get("tip_proxy_top", 60.0)) + 5.0 + 30.0,
            float(info.get("tip_z", 0.0)),
        ],
        "size_mm": [60.0, 100.0, 60.0],
    }


def _validate_details(part: dict) -> int:
    """Check serialized concept geometry against its local envelope, without CAD imports."""
    if "geometry" not in part:
        return 0  # Older snapshots use only the component envelope.
    geometry = part["geometry"]
    label = f"Component {part['id']} geometry"
    if not isinstance(geometry, dict) or geometry.get("schema_version") != "1":
        raise ValueError(f"{label}: unsupported schema version.")
    primitives = geometry.get("primitives")
    if not isinstance(primitives, list) or not 1 <= len(primitives) <= 256:
        raise ValueError(f"{label}: expected 1 to 256 primitives.")

    def number(value, name, positive=False):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{label}: {name} must be a finite number.")
        value = float(value)
        if not math.isfinite(value) or (positive and value <= 0):
            raise ValueError(
                f"{label}: {name} must be finite and positive."
                if positive
                else f"{label}: {name} must be finite."
            )
        return value

    def vector(value, name, positive=False):
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise ValueError(f"{label}: {name} must contain three coordinates.")
        return [number(v, name, positive) for v in value]

    envelope = vector(part["size"], "envelope size", True)
    seen = set()
    for primitive in primitives:
        if not isinstance(primitive, dict):
            raise ValueError(f"{label}: invalid primitive.")
        pid, kind = primitive.get("id"), primitive.get("kind")
        if not isinstance(pid, str) or not pid or pid in seen:
            raise ValueError(f"{label}: primitive IDs must be unique nonempty strings.")
        seen.add(pid)
        if kind not in ("box", "plate", "cylinder", "frustum", "tube"):
            raise ValueError(f"{label}, primitive {pid}: unsupported shape {kind!r}.")
        pos = vector(primitive.get("position"), f"{pid} position")
        size = vector(primitive.get("size"), f"{pid} size", True)
        tolerance = 1e-7
        if kind in ("cylinder", "frustum", "tube"):
            axis = primitive.get("axis", "y")
            if axis not in ("x", "y", "z"):
                raise ValueError(f"{label}, primitive {pid}: invalid axis.")
            transverse = [i for i in range(3) if i != "xyz".index(axis)]
            diameters = [size[i] for i in transverse]
            if not math.isclose(diameters[0], diameters[1], rel_tol=1e-9, abs_tol=tolerance):
                raise ValueError(f"{label}, primitive {pid}: transverse diameters disagree.")
            radius = diameters[0] / 2
            if kind == "frustum":
                radii = [
                    number(primitive.get(key), f"{pid} {key}")
                    for key in ("radius_top_mm", "radius_bottom_mm")
                ]
                if min(radii) < 0 or not math.isclose(
                    max(radii), radius, rel_tol=1e-9, abs_tol=tolerance
                ):
                    raise ValueError(
                        f"{label}, primitive {pid}: radii contradict its bounding size."
                    )
            if kind == "tube":
                inner = number(primitive.get("inner_radius_mm"), f"{pid} inner_radius_mm")
                if not 0 <= inner < radius:
                    raise ValueError(f"{label}, primitive {pid}: invalid inner radius.")
        if any(abs(pos[i]) + size[i] / 2 > envelope[i] / 2 + tolerance for i in range(3)):
            raise ValueError(f"{label}, primitive {pid}: extends outside the component envelope.")
        if kind == "plate":
            holes = primitive.get("holes", [])
            if not isinstance(holes, list) or len(holes) > 256:
                raise ValueError(f"{label}, primitive {pid}: invalid holes list.")
            for hole in holes:
                if not isinstance(hole, dict):
                    raise ValueError(f"{label}, primitive {pid}: invalid hole.")
                x = number(hole.get("x_mm"), f"{pid} hole x")
                z = number(hole.get("z_mm"), f"{pid} hole z")
                radius = number(hole.get("radius_mm"), f"{pid} hole radius", True)
                if (
                    abs(x) + radius > size[0] / 2 + tolerance
                    or abs(z) + radius > size[2] / 2 + tolerance
                ):
                    raise ValueError(f"{label}, primitive {pid}: hole extends outside its plate.")
    return len(primitives)


def _validate(project: dict, scenario: str) -> dict:
    if scenario not in ("nominal", "blocked_path"):
        raise ValueError("Unsupported physics scenario.")
    if project.get("status") != "confirmed" or project.get("plan", {}).get("status") != "ready":
        raise ValueError("Physics requires a confirmed project and ready preparation plan.")
    if project["design"]["constraint_status"] == "infeasible":
        raise ValueError("Resolve the workspace constraint before simulation.")
    components = project["design"]["components"]
    ids = [part["id"] for part in components]
    required = {
        "base",
        "carriage",
        "pipette",
        "source-rack",
        "sample-rack",
        "tip-rack",
        "tip-waste",
    }
    if len(set(ids)) != len(ids) or not required.issubset(ids):
        raise ValueError("Required unique machine component IDs are missing.")
    for part in components:
        for field in ("position", "size"):
            values = part[field]
            if len(values) != 3 or not all(math.isfinite(float(v)) for v in values):
                raise ValueError("Component geometry must contain three finite coordinates.")
        if min(part["size"]) <= 0:
            raise ValueError("Component sizes must be positive.")
    primitive_count = sum(_validate_details(part) for part in components)
    steps = project["plan"]["steps"]
    if not 1 <= len(steps) <= 6:
        raise ValueError("Physics supports one to six preparation targets.")
    for step in steps:
        volumes = [step["stock_volume_ul"], step["diluent_volume_ul"]]
        if not all(math.isfinite(v) and v >= 0 for v in volumes) or sum(volumes) <= 0:
            raise ValueError("Preparation transfers must have finite nonnegative volumes.")
    return {
        "components_with_details": sum(part.get("geometry") is not None for part in components),
        "primitives_validated": primitive_count,
        "collision_model": "component envelopes and consumable proxies",
    }


def _proxy_boxes(project: dict, _info=None) -> list[tuple]:
    """Assumed cylinders follow the same rack arrangement as the browser view."""
    parts = {part["id"]: part for part in project["design"]["components"]}
    proxies = []
    for cid, count, radius, height, center_offset in (
        ("source-rack", 2, 6, 22, 9),
        ("sample-rack", len(project["plan"]["steps"]), 6, 22, 9),
        ("tip-rack", 4, 4.5, 16, 6),
    ):
        part = parts[cid]
        x, y, z = part["position"]
        top = y + part["size"][1] / 2
        spacing = min(20, part["size"][0] / (count + 1))
        for index in range(count):
            proxies.append(
                (
                    f"{cid}-proxy-{index}",
                    x + (index - (count - 1) / 2) * spacing,
                    top + center_offset,
                    z,
                    radius,
                    height,
                )
            )
    return proxies


def _axis_ranges(project: dict) -> tuple:
    parts = {part["id"]: part for part in project["design"]["components"]}
    base, head, pipette = (parts[key] for key in ("base", "carriage", "pipette"))
    offset = [pipette["position"][i] - head["position"][i] for i in range(3)]
    minimum = [-size / 2 for size in head["size"]]
    maximum = [size / 2 for size in head["size"]]
    for axis in range(3):
        extension = TIP_LENGTH_MM if axis == 1 else 0
        minimum[axis] = min(minimum[axis], offset[axis] - pipette["size"][axis] / 2 - extension)
        maximum[axis] = max(maximum[axis], offset[axis] + pipette["size"][axis] / 2)
    ranges = []
    for axis in range(3):
        lower = base["position"][axis] - base["size"][axis] / 2
        upper = base["position"][axis] + base["size"][axis] / 2
        if axis == 1:
            lower = base["position"][1] + base["size"][1] / 2
            upper = project["design"]["footprint"]["height_mm"]
        ranges.append((lower - minimum[axis], upper - maximum[axis]))
    if any(
        not all(math.isfinite(v) for v in limits) or limits[0] >= limits[1] for limits in ranges
    ):
        raise ValueError("Planning envelope leaves no feasible head travel.")
    return tuple(ranges)


def _plan_motion(project: dict) -> tuple:
    parts = {part["id"]: part for part in project["design"]["components"]}
    head, pipette = parts["carriage"], parts["pipette"]
    home = list(head["position"])
    offset = [pipette["position"][i] - home[i] for i in range(3)]
    offset[1] -= pipette["size"][1] / 2 + TIP_LENGTH_MM
    proxies = _proxy_boxes(project)
    tops = [
        p["position"][1] + p["size"][1] / 2
        for p in parts.values()
        if p["id"] not in ("carriage", "pipette", "crossbar", "column-left", "column-right")
    ]
    cruise = max(tops + [p[2] + p[5] / 2 for p in proxies]) + 15
    waypoints = []
    current, clock = home[:], 0.0

    def add(tip, phase, cid=None, transfer=None, volume=None, hold=0):
        nonlocal current, clock
        target = [tip[i] - offset[i] for i in range(3)]
        duration = hold or max(0.3, 1.5 * math.dist(current, target) / MAX_SPEED_MM_S)
        duration = math.ceil(duration / TIMESTEP_S) * TIMESTEP_S
        clock = round(clock + duration, 9)
        waypoints.append(
            {
                "time_s": clock,
                "carriage_mm": target,
                "phase": phase,
                "station_id": cid,
                "transfer_id": transfer,
                "volume_ul": volume,
            }
        )
        current = target

    home_tip = [home[i] + offset[i] for i in range(3)]
    add([home_tip[0], cruise, home_tip[2]], "lift")
    tips = [proxy for proxy in proxies if proxy[0].startswith("tip-rack-")]
    sources = [proxy for proxy in proxies if proxy[0].startswith("source-rack-")]
    samples = [proxy for proxy in proxies if proxy[0].startswith("sample-rack-")]
    transfer_index = 0
    for target_index, step in enumerate(project["plan"]["steps"]):
        for source_index, source_name in enumerate(("stock", "diluent")):
            volume = step[f"{source_name}_volume_ul"]
            if volume <= 0:
                continue
            transfer = f"{step['id']}:{source_name}"
            tip, source, sample = (
                tips[transfer_index % len(tips)],
                sources[source_index],
                samples[target_index],
            )
            waste = parts["tip-waste"]
            stations = [
                ("tip-rack", [tip[1], tip[2] + tip[5] / 2 + 5, tip[3]], "pick-tip"),
                (
                    "source-rack",
                    [source[1], source[2] + source[5] / 2 + 5, source[3]],
                    f"aspirate-{source_name}",
                ),
                ("sample-rack", [sample[1], sample[2] + sample[5] / 2 + 5, sample[3]], "dispense"),
                (
                    "tip-waste",
                    [
                        waste["position"][0],
                        waste["position"][1] + waste["size"][1] / 2 + 5,
                        waste["position"][2],
                    ],
                    "eject-tip",
                ),
            ]
            for cid, point, action in stations:
                hover = [point[0], cruise, point[2]]
                add(hover, "travel", cid, transfer)
                add(point, "approach", cid, transfer)
                add(point, f"{action} (logical hold)", cid, transfer, volume, hold=0.15)
                add(hover, "retract", cid, transfer)
            transfer_index += 1
    add([home_tip[0], cruise, home_tip[2]], "return-above-home")
    add(home_tip, "return-home")
    add(home_tip, "settle", hold=0.3)
    info = {
        "tip_xs": [tip[1] for tip in tips],
        "tip_proxy_top": tips[0][2] + tips[0][5] / 2,
        "tip_z": tips[0][3],
    }
    return waypoints, home, offset, info


def _assumptions() -> list[str]:
    return [
        "Ideal rigid XYZ head on prismatic guides; travel is assumed from the deck/planning "
        "envelope.",
        "Masses: carriage 0.45 kg, pipette 0.15 kg, tip 0.001 kg; not measured hardware masses.",
        "Position gains kp=5000 N/m, kv=100 Ns/m; guide damping 5 Ns/m; gravity is uncompensated.",
        "Assumed actuator limits [15,15,20] N in engine X,Y,Z; not supplier motor capability.",
        "Crossbar/carriage contact omitted as an ideal guide interface; head/post and "
        "tool/frame contacts remain enabled.",
        "Tube/tip cylinders are assumed fixed proxies, matching the displayed rack arrangement.",
        "Collision checks use component envelopes and consumable proxies, not visual details.",
        "Approaches stop 5 mm above proxy tops/rim; cruise is 15 mm above non-frame obstacles.",
        "Tip positions cycle through four logical stations; consumable capacity/replacement "
        "is unverified.",
        "Waypoint tolerance 5 mm, contact threshold 0.05 N, 2 ms implicitfast integration.",
    ]


def _limitations() -> list[str]:
    return [
        "No liquid dynamics, calibrated volumes, mixing, tip detachment or physical tube "
        "insertion.",
        "No rails/transmission, backlash, cable routing, material deformation or hardware control.",
        "No measured motor torque, mount strength, cooling performance or laboratory validation.",
        "Cold storage is an obstacle envelope with manual transfer; no robotic sample transfer.",
        "Fine bores, vents and cutouts are not resolved for contact; full envelopes can "
        "conservatively block visually open spaces.",
        "The diagnostic obstacle is a synthetic test object, not a selected project component.",
    ]


def simulate_project(project: dict, scenario: str = "nominal", on_progress=None) -> dict:
    """Integrate the bounded plan; measured state and declarative sensors determine the result."""
    geometry_scope = _validate(project, scenario)
    import mujoco

    snapshot = deepcopy(project)
    waypoints, home, tip_offset, info = _plan_motion(snapshot)
    ranges = _axis_ranges(snapshot)
    duration = waypoints[-1]["time_s"]
    planned_steps = math.ceil(duration / TIMESTEP_S)
    xml = _model_xml(snapshot, info, scenario, ranges)
    spec = mujoco.MjSpec.from_string(xml)
    model = spec.compile()
    data = mujoco.MjData(model)
    # All joint displacements and position controls start at zero relative to home.
    mujoco.mj_forward(model, data)
    sensors = [(f"contact_{c['id']}", c["id"]) for c in _geom_list(snapshot, info, scenario)]
    sensors += [(f"contact_{p[0]}", p[0]) for p in _proxy_boxes(snapshot)]
    if scenario == "blocked_path":
        sensors.append(("contact_simulation-obstacle", "simulation-obstacle"))
    unsupported = any(
        not ranges[axis][0] <= point[axis] <= ranges[axis][1]
        for point in [home] + [w["carriage_mm"] for w in waypoints]
        for axis in range(3)
    )
    bounded = duration <= MAX_SIM_S and planned_steps // SAMPLE_STRIDE + 2 <= MAX_FRAMES
    frames, contacts = [], []
    peak_force = [0.0, 0.0, 0.0]
    max_error, max_contact, completed = 0.0, 0.0, 0
    status = "passed" if bounded and not unsupported else "failed"
    range_ok, finite = True, True
    parts = {part["id"]: part for part in snapshot["design"]["components"]}
    pipette_offset = [parts["pipette"]["position"][i] - home[i] for i in range(3)]

    def state_frame(target, waypoint):
        carriage = _eng_to_app_car(data.body("head").xpos.copy())
        tip = _eng_to_app_car(data.site("tip_site").xpos.copy())
        return {
            "time_s": round(float(data.time), 9),
            "carriage_mm": carriage,
            "pipette_mm": [carriage[i] + pipette_offset[i] for i in range(3)],
            "tip_mm": tip,
            "target_mm": list(target),
            "phase": waypoint["phase"],
            "station_id": waypoint["station_id"],
            "transfer_id": waypoint["transfer_id"],
        }

    initial = {"phase": "home", "station_id": None, "transfer_id": None}
    frames.append(state_frame(home, initial))
    if on_progress:
        on_progress("integrating", 0, planned_steps)
    tick = 0
    start_time, previous = 0.0, home
    if status == "passed":
        for waypoint in waypoints:
            segment_end = waypoint["time_s"]
            sample = _cubic(previous, waypoint["carriage_mm"], segment_end - start_time)
            while data.time < segment_end - TIMESTEP_S / 2:
                target = sample(min(segment_end, data.time + TIMESTEP_S) - start_time)
                displacement = _app_to_eng_mm_to_m([target[i] - home[i] for i in range(3)])
                for name, value in zip(("ax", "ay", "az"), displacement, strict=True):
                    data.actuator(name).ctrl = value
                mujoco.mj_step(model, data)
                # Refresh derived positions and contact forces at the newly integrated state.
                mujoco.mj_forward(model, data)
                tick += 1
                frame = state_frame(target, waypoint)
                actual = frame["carriage_mm"]
                finite = all(math.isfinite(v) for v in actual + frame["tip_mm"])
                forces = [abs(float(data.actuator(name).force[0])) for name in ("ax", "ay", "az")]
                finite = finite and all(math.isfinite(v) for v in forces)
                if not finite:
                    status = "failed"
                    break
                peak_force = [max(peak_force[i], forces[i]) for i in range(3)]
                error = math.dist(actual, target)
                max_error = max(max_error, error)
                range_ok = range_ok and all(
                    ranges[i][0] - 1 <= actual[i] <= ranges[i][1] + 1 for i in range(3)
                )
                hits = []
                for sensor, cid in sensors:
                    reading = data.sensor(sensor).data
                    force = math.sqrt(sum(float(v) ** 2 for v in reading[1:4]))
                    max_contact = max(max_contact, force)
                    if reading[0] > 0 and force > CONTACT_TOL_N:
                        hits.append(
                            {"time_s": frame["time_s"], "component_id": cid, "force_n": force}
                        )
                if hits:
                    contacts.extend(hits)
                    status = "blocked"
                elif error > TRACK_TOL_MM or not range_ok:
                    status = "failed"
                if tick % SAMPLE_STRIDE == 0 or status != "passed":
                    frames.append(frame)
                if on_progress and tick % 250 == 0:
                    on_progress("integrating", tick, planned_steps)
                if status != "passed":
                    break
            if status != "passed":
                break
            endpoint = state_frame(waypoint["carriage_mm"], waypoint)
            if math.dist(endpoint["carriage_mm"], waypoint["carriage_mm"]) <= TRACK_TOL_MM:
                completed += 1
            else:
                status = "failed"
                break
            start_time, previous = segment_end, waypoint["carriage_mm"]
    last_target = (
        previous
        if completed == len(waypoints)
        else (
            waypoints[completed]["carriage_mm"] if status == "passed" else frames[-1]["target_mm"]
        )
    )
    final_frame = state_frame(last_target, waypoints[min(completed, len(waypoints) - 1)])
    if finite and final_frame["time_s"] > frames[-1]["time_s"]:
        frames.append(final_frame)
    final_error = math.dist(final_frame["carriage_mm"], last_target) if finite else max_error
    checks = [
        {
            "id": "travel",
            "label": "Planned path within assumed travel",
            "passed": not unsupported,
            "observed": str(ranges),
            "limit": "within bounds",
        },
        {
            "id": "bounded",
            "label": "Bounded simulation size",
            "passed": bounded,
            "observed": duration,
            "limit": MAX_SIM_S,
        },
        {
            "id": "tracking",
            "label": "Observed following error",
            "passed": max_error <= TRACK_TOL_MM and finite,
            "observed": max_error,
            "limit": TRACK_TOL_MM,
        },
        {
            "id": "contact",
            "label": "No unexpected contact",
            "passed": max_contact <= CONTACT_TOL_N,
            "observed": max_contact,
            "limit": CONTACT_TOL_N,
        },
        {
            "id": "completed",
            "label": "All waypoints completed",
            "passed": completed == len(waypoints),
            "observed": completed,
            "limit": len(waypoints),
        },
        {
            "id": "finite",
            "label": "Finite engine state and joint limits",
            "passed": finite and range_ok,
            "observed": str(finite and range_ok),
            "limit": "True",
        },
    ]
    result = {
        "schema_version": 1,
        "model_version": MODEL_VERSION,
        "project_id": snapshot["id"],
        "revision": snapshot["revision"],
        "scenario": scenario,
        "engine": "MuJoCo",
        "engine_version": mujoco.__version__,
        "engine_source_sha256": hashlib.sha256(_SOURCE_BYTES).hexdigest(),
        "input_sha256": hashlib.sha256(
            json.dumps(
                {"project": snapshot, "scenario": scenario}, sort_keys=True, allow_nan=False
            ).encode()
        ).hexdigest(),
        "status": status,
        "duration_s": float(data.time),
        "timestep_s": TIMESTEP_S,
        "frames": frames,
        "waypoints": waypoints,
        "metrics": {
            "max_tracking_error_mm": max_error,
            "final_tracking_error_mm": final_error,
            "peak_actuator_force_n": peak_force,
            "max_contact_force_n": max_contact,
            "contact_count": len(contacts),
            "completed_waypoints": completed,
            "total_waypoints": len(waypoints),
        },
        "contacts": contacts,
        "checks": checks,
        "assumptions": _assumptions(),
        "limitations": _limitations(),
        "geometry_scope": geometry_scope,
        "model_xml": spec.to_xml(),
        "obstacles": [_obstacle(snapshot, info)] if scenario == "blocked_path" else [],
        "integration_steps": tick,
        "planned_integration_steps": planned_steps,
    }
    json.dumps(result, allow_nan=False)
    if on_progress:
        on_progress("stopped" if status != "passed" else "completed", tick, planned_steps)
    return result


def build_simulation_files(project: dict, result: dict) -> dict[str, bytes]:
    """Bundle measured results and a standalone copy of the exact runtime source."""
    if result["project_id"] != project["id"] or result["revision"] != project["revision"]:
        raise ValueError("Simulation result belongs to a different project revision.")
    expected_hash = hashlib.sha256(
        json.dumps(
            {"project": project, "scenario": result["scenario"]},
            sort_keys=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()
    if result["input_sha256"] != expected_hash:
        raise ValueError("Simulation input hash does not match the project snapshot.")
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    vector_fields = ("carriage_mm", "pipette_mm", "tip_mm", "target_mm")
    writer.writerow(
        ["time_s"]
        + [f"{field[:-3]}_{axis}_mm" for field in vector_fields for axis in "xyz"]
        + ["phase", "station_id", "transfer_id"]
    )
    for frame in result["frames"]:
        writer.writerow(
            [frame["time_s"]]
            + [v for field in vector_fields for v in frame[field]]
            + [frame["phase"], frame["station_id"], frame["transfer_id"]]
        )
    runner = '''"""Rerun the packaged inputs using the locked MuJoCo environment."""
import json
from pathlib import Path
from engine import simulate_project

folder = Path(__file__).resolve().parent
project = json.loads((folder.parent / "project.json").read_text(encoding="utf-8"))["project"]
scenario = json.loads((folder / "result.json").read_text(encoding="utf-8"))["scenario"]
result = simulate_project(project, scenario=scenario)
(folder / "replay-result.json").write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
print(result["status"], result["metrics"])
'''
    readme = (
        "# MuJoCo simulation bundle\n\n"
        f"Project {project['id']} revision {project['revision']}, scenario "
        f"{result['scenario']}.\n\n"
        "Use the MuseAutoLab README's locked Python .venv with mujoco==3.17.0.\n"
        "Run that interpreter against `simulation/run.py` after extracting the project ZIP.\n"
        "The runner reads project.json and writes simulation/replay-result.json.\n"
        "model.xml is the compiled scene description; result.json retains assumptions,\n"
        "controls/waypoints, checks, metrics and sampled states. trajectory.csv is a flat "
        "trace.\n\n"
        "Coordinates in results are app millimetres (Y up); XML uses metres (Z up):\n"
        "app(x,y,z) maps to engine(x,z,y)/1000. Recorded forces use engine X,Y,Z.\n\n"
        "Real forward dynamics with assumed masses/ideal servos and collision envelopes.\n"
        "Concept primitives are checked against component envelopes when present, but are\n"
        "not used for contacts. Older snapshots without them use the same envelopes.\n"
        "Fine bores, vents and cutouts are unresolved; full envelopes may conservatively\n"
        "block visually open spaces. Tube and tip contacts use separate assumed proxies.\n"
        "Crossbar/carriage guide contact is excluded; head/post and tool/frame contacts "
        "remain enabled.\n"
        "Actions at stations are logical holds above their tops, without insertion,\n"
        "physical tip detachment, liquid dynamics or measured dispensing accuracy.\n"
        "Cooling, materials, mounts, actual motors and laboratory performance are unverified.\n"
    )
    return {
        "simulation/model.xml": result["model_xml"].encode(),
        "simulation/result.json": json.dumps(result, allow_nan=False).encode(),
        "simulation/trajectory.csv": output.getvalue().encode(),
        "simulation/engine.py": _SOURCE_BYTES,
        "simulation/run.py": runner.encode(),
        "simulation/README.md": readme.encode(),
    }
