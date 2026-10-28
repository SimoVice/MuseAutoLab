"""Concept-only horizontal inspection arm using the shared geometry primitives.

Coordinates are millimetres in the application's y-up frame. These kinematics
are geometric illustrations, not a motion, collision or hardware validation.
"""

from __future__ import annotations

import math
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from app.design_sources import camera_geometry_spec

INSPECTION_SOURCE_SHA256 = sha256(Path(__file__).read_bytes()).hexdigest()


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number.")
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high} mm.")
    return float(value)


def _proposal(raw):
    keys = {"schema_version", "link_lengths_mm", "mast_height_mm", "rationale", "assumptions"}
    if not isinstance(raw, dict) or set(raw) != keys or raw["schema_version"] != "1":
        raise ValueError("Invalid inspection proposal fields or schema version.")
    lengths = raw["link_lengths_mm"]
    if not isinstance(lengths, list) or len(lengths) != 2:
        raise ValueError("link_lengths_mm must contain exactly two lengths.")
    lengths = [_number(v, "link length", 180, 500) for v in lengths]
    height = _number(raw["mast_height_mm"], "mast height", 400, 550)
    rationale, assumptions = raw["rationale"], raw["assumptions"]
    if not isinstance(rationale, str) or len(rationale) > 1200:
        raise ValueError("rationale must be text of at most 1200 characters.")
    if (
        not isinstance(assumptions, list)
        or len(assumptions) > 6
        or any(not isinstance(s, str) or len(s) > 300 for s in assumptions)
    ):
        raise ValueError("assumptions must contain at most six text entries of 300 characters.")
    return dict(
        schema_version="1",
        link_lengths_mm=lengths,
        mast_height_mm=height,
        rationale=rationale,
        assumptions=list(assumptions),
    )


def _primitive(name, kind, position, size, appearance, **extra):
    return dict(
        id=name, kind=kind, position=list(position), size=list(size), appearance=appearance, **extra
    )


def _component(part_id, kind, label, position, size, primitives):
    return dict(
        id=part_id,
        kind=kind,
        label=label,
        position=list(position),
        size=list(size),
        geometry=dict(schema_version="1", primitives=primitives),
    )


def _joint(part_id, label, x, y, z, diameter=58, height=30):
    return _component(
        part_id,
        "inspection-joint",
        label,
        (x, y, z),
        (diameter, height, diameter),
        [
            _primitive(
                "housing", "cylinder", (0, 0, 0), (diameter, height, diameter), "motor", axis="y"
            )
        ],
    )


def _link(part_id, label, a, b, y, length):
    dx, dz = b[0] - a[0], b[1] - a[1]
    yaw = -math.degrees(math.atan2(dz, dx))
    c, s = abs(math.cos(math.radians(yaw))), abs(math.sin(math.radians(yaw)))
    # World-aligned bounding box of a local rectangular solid rotated about y.
    width, height = 36.0, 26.0
    size = [c * length + s * width, height, s * length + c * width]
    return _component(
        part_id,
        "inspection-link",
        label,
        ((a[0] + b[0]) / 2, y, (a[1] + b[1]) / 2),
        size,
        [
            _primitive(
                "beam", "box", (0, 0, 0), (length, height, width), "frame", rotation_y_deg=yaw
            )
        ],
    )


def _solve(start, target, lengths):
    dx, dz = target[0] - start[0], target[1] - start[1]
    l1, l2 = lengths
    distance = math.hypot(dx, dz)
    if distance < 1e-9 or distance > l1 + l2 + 1e-9 or distance < abs(l1 - l2) - 1e-9:
        raise ValueError("Inspection target is unreachable with the proposed link lengths.")
    cosine = (distance * distance - l1 * l1 - l2 * l2) / (2 * l1 * l2)
    cosine = max(-1.0, min(1.0, cosine))
    # Select the branch with the leftmost elbow for the front-right sidecar.
    solutions = []
    for q2 in (math.acos(cosine), -math.acos(cosine)):
        q1 = math.atan2(dz, dx) - math.atan2(l2 * math.sin(q2), l1 + l2 * math.cos(q2))
        elbow = (start[0] + l1 * math.cos(q1), start[1] + l1 * math.sin(q1))
        solutions.append((elbow, q1, q2))
    return min(solutions, key=lambda v: v[0][0])


def _valid_part(part, part_id):
    try:
        pos, size = part["position"], part["size"]
        if len(pos) != 3 or len(size) != 3:
            raise ValueError
        for n in [*pos, *size]:
            if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n):
                raise ValueError
        if any(n <= 0 for n in size):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"Invalid {part_id} component envelope.") from None
    return pos, size


def _bounds(components):
    return {
        "min_mm": [min(p["position"][i] - p["size"][i] / 2 for p in components) for i in range(3)],
        "max_mm": [max(p["position"][i] + p["size"][i] / 2 for p in components) for i in range(3)],
    }


def compile_inspection(project: dict, proposal: dict) -> dict:
    """Compile an independent inspection module from an existing design snapshot."""
    spec = _proposal(proposal)
    try:
        parts = {p["id"]: p for p in project["design"]["components"]}
        base_pos, base_size = _valid_part(parts["base"], "base")
        rack_pos, rack_size = _valid_part(parts["sample-rack"], "sample-rack")
    except (KeyError, TypeError):
        raise ValueError("The design must contain a base and sample-rack.") from None
    if base_size[0] < 300:
        raise ValueError("The base is too narrow for the sidecar pad.")
    edge = base_pos[2] + base_size[2] / 2
    x, z = base_pos[0] + base_size[0] / 2 - 80, edge + 100
    base_top = base_pos[1] + base_size[1] / 2
    height = spec["mast_height_mm"]
    if base_top >= height - 40:
        raise ValueError("The proposed mast height is below the mounting surface.")
    pad_center_y = base_top - 10
    mount = _component(
        "inspection-mount",
        "inspection-mount",
        "Sidecar pad and edge bracket",
        (x, pad_center_y, edge + 65),
        (140, 24, 210),
        [
            _primitive("pad", "box", (0, 0, 35), (140, 20, 140), "structure"),
            _primitive("edge-bridge", "box", (0, 10, -65), (85, 4, 80), "rail"),
        ],
    )
    mast_bottom = base_top
    mast_top = height - 15
    mast_h = mast_top - mast_bottom
    mast = _component(
        "inspection-mast",
        "inspection-mast",
        "Inspection mast",
        (x, (mast_bottom + mast_top) / 2, z),
        (42, mast_h, 42),
        [_primitive("mast", "box", (0, 0, 0), (42, mast_h, 42), "frame")],
    )
    frames = []
    # Return to the first position so a loop can be played without a jump.
    for time, offset in ((0, 0), (2, -20), (4, 20), (6, 0)):
        target_xz = (rack_pos[0] + offset, rack_pos[2])
        elbow, q1, q2 = _solve((x, z), target_xz, spec["link_lengths_mm"])
        tx, tz = target_xz
        camera_y = height - 55
        camera_spec = camera_geometry_spec()
        camera_size = camera_spec["size_mm"]
        camera = _component(
            "inspection-camera",
            "inspection-camera",
            "Raspberry Pi Camera Module 3 envelope",
            (tx, camera_y, tz),
            camera_size,
            [
                _primitive(
                    "pcb",
                    "box",
                    (0, 4.25, 0),
                    (25, 3, 24),
                    "controller",
                    reference_id=camera_spec["reference_id"],
                    dimension_basis="schematic_within_manufacturer_envelope",
                ),
                _primitive(
                    "lens",
                    "cylinder",
                    (0, -1.5, 0),
                    (11, 8.5, 11),
                    "motor",
                    axis="y",
                    reference_id=camera_spec["reference_id"],
                    dimension_basis="schematic_within_manufacturer_envelope",
                ),
            ],
        )
        camera["reference_geometry"] = deepcopy(camera_spec)
        # Custom conceptual neck connects the wrist to the envelope, not vendor CAD.
        neck_bottom = camera_y + camera_size[1] / 2
        neck_top = height - 15
        neck_height = neck_top - neck_bottom
        camera_mount = _component(
            "inspection-camera-mount",
            "inspection-camera-mount",
            "Custom camera neck concept",
            (tx, (neck_top + neck_bottom) / 2, tz),
            (12, neck_height, 12),
            [_primitive("neck", "box", (0, 0, 0), (12, neck_height, 12), "structure")],
        )
        pieces = [
            deepcopy(mount),
            deepcopy(mast),
            _joint("inspection-shoulder", "Shoulder joint", x, height, z),
            _link(
                "inspection-upper-link",
                "Upper arm link",
                (x, z),
                elbow,
                height,
                spec["link_lengths_mm"][0],
            ),
            _joint("inspection-elbow", "Elbow joint", elbow[0], height, elbow[1]),
            _link(
                "inspection-forearm",
                "Forearm link",
                elbow,
                target_xz,
                height,
                spec["link_lengths_mm"][1],
            ),
            _joint("inspection-wrist", "Camera wrist", tx, height, tz, 40, 30),
            camera_mount,
            camera,
        ]
        frames.append(
            dict(
                time_s=time,
                components=pieces,
                joint_angles_deg=dict(shoulder=math.degrees(q1), elbow=math.degrees(q2)),
                camera_mm=[tx, camera_y, tz],
                target_mm=[tx, rack_pos[1] + rack_size[1] / 2, tz],
            )
        )
    components = deepcopy(frames[0]["components"])
    return dict(
        schema_version="1",
        proposal=spec,
        geometry_source_sha256=INSPECTION_SOURCE_SHA256,
        source_binding=dict(
            camera=deepcopy(camera_geometry_spec()),
            interpretation="Manufacturer envelope; custom mount and arm. Vendor CAD not imported.",
        ),
        attachment=dict(
            parent_component_id="base",
            anchor_mm=[x, base_top, edge],
            concept_only=True,
            fasteners="unverified",
            loads="unverified",
        ),
        component_ids=[p["id"] for p in components],
        components=components,
        pose_frames=frames,
        bounds=_bounds([p for f in frames for p in f["components"]]),
        checks=[
            dict(
                id="planar_reach",
                passed=True,
                detail="All illustrated targets are reachable by planar inverse kinematics.",
            ),
            dict(
                id="sidecar_width",
                passed=True,
                detail="The fixed sidecar pad stays within the base width.",
            ),
        ],
        limitations=[
            "Concept geometry and kinematic poses only; no physical or hardware validation.",
            "Attachment, fasteners, loads, motion clearance, collision avoidance and cabling "
            "are unverified.",
            "The camera uses the manufacturer overall envelope with schematic internal shapes; "
            "mounting and lens details are not supplier CAD.",
            "The downward camera is illustrative; field of view, image quality and inspection "
            "coverage are unverified.",
        ],
    )


def inspection_components(module: dict) -> list[dict]:
    """Return independent initial-pose components for the common design model."""
    return deepcopy(module["components"])
