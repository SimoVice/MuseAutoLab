"""Explicit additive, open-bottom housings for a previously accepted concept.

The builder reserves existing swept geometry, adds material only, and requires
the actual modeled base to support each wall. It does not infer a housing from
names or change an accepted mechanism to make a new cover fit.
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.concept_design import (
    EPSILON,
    _bounds,
    _intersects,
    assembly_review_issues,
    compile_concept,
)

Key = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")]
Text = Annotated[str, Field(min_length=1, max_length=2000)]


class EnclosureRequest(BaseModel):
    """A new rectangular housing around selected parts, never a vendor enclosure."""

    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, revalidate_instances="always"
    )

    key: Key
    name: Annotated[str, Field(min_length=1, max_length=120)]
    role: Text
    assembly: Text
    check: Text
    target_keys: list[Key] = Field(min_length=1, max_length=40)
    clearance_mm: float = Field(ge=0.5, le=100)
    wall_mm: float = Field(ge=0.5, le=20)
    finish: Literal["frame", "steel", "polymer", "clear", "accent", "dark"]
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    open_face: Literal["front", "back", "left", "right"] | None = None
    open_bottom: Literal[True] = True

    @field_validator("clearance_mm", "wall_mm", mode="before")
    @classmethod
    def finite_number(cls, value):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("Housing clearance and wall thickness must be finite millimetres.")
        return value

    @field_validator("open_bottom", mode="before")
    @classmethod
    def open_base(cls, value):
        if value is not True:
            raise ValueError("This housing builder supports an open bottom only.")
        return value

    @field_validator("target_keys")
    @classmethod
    def unique_targets(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Select each housing target only once.")
        return value


def _covered(footprint, surfaces):
    """Require complete rectangular foot coverage by the union of actual top faces."""
    x0, x1, z0, z1 = footprint
    clipped = [
        (max(x0, a), min(x1, b), max(z0, c), min(z1, d))
        for a, b, c, d in surfaces
        if min(x1, b) - max(x0, a) > EPSILON and min(z1, d) - max(z0, c) > EPSILON
    ]
    if not clipped:
        return False
    xs = sorted({x0, x1, *(v for r in clipped for v in r[:2])})
    zs = sorted({z0, z1, *(v for r in clipped for v in r[2:])})
    return all(
        any(
            a - EPSILON <= (x + xx) / 2 <= b + EPSILON
            and c - EPSILON <= (z + zz) / 2 <= d + EPSILON
            for a, b, c, d in clipped
        )
        for x, xx in zip(xs, xs[1:])
        for z, zz in zip(zs, zs[1:])
    )


def add_parametric_enclosure(
    previous_design: dict, request: EnclosureRequest | dict, workspace_width_mm=None
) -> dict:
    """Return a compiled additive revision; no input is mutated.

    Targets must belong to one stationary root and cannot include that base.
    Descendants are included automatically. Front is the negative-Z face.
    Clearance expands the complete target motion envelope in X/Z and above it;
    wall bottoms sit on coplanar top faces of actual root box solids.
    Existing proposal geometry, steps, software and work interfaces are retained.
    """
    operation = EnclosureRequest.model_validate(request)
    if not isinstance(previous_design, dict) or not previous_design.get("proposal"):
        raise ValueError("Add a housing only to a previously accepted compiled design.")
    previous = compile_concept(
        previous_design["proposal"], previous_design.get("workspace_width_mm")
    )
    proposal = deepcopy(previous["proposal"])
    index = {part["key"]: part for part in previous["components"]}
    all_keys = set(index) | {part["key"] for part in proposal.get("supplies", [])}
    if operation.key in all_keys:
        raise ValueError("Use a new, distinct name for the housing component key.")
    if any(key not in index for key in operation.target_keys):
        raise ValueError("Select existing modeled parts for the housing.")
    roots = {index[key]["assembly_root_key"] for key in operation.target_keys}
    if len(roots) != 1:
        raise ValueError("One housing can cover parts attached to one stationary base only.")
    root_key = roots.pop()
    if root_key in operation.target_keys:
        raise ValueError("Select parts above the base, rather than the base itself.")
    if any(step["moving_key"] == root_key for step in previous["steps"]):
        raise ValueError("The housing needs a stationary base; this assembly base moves.")
    targets = set(operation.target_keys)
    for _ in index:
        targets.update(key for key, part in index.items() if part["parent_key"] in targets)
    root = index[root_key]
    origin = root["position_mm"]
    gap, wall = operation.clearance_mm, operation.wall_mm
    tops = []
    for primitive in root["primitives"]:
        if primitive["shape"] != "box":
            continue
        x, y, z = primitive["center_mm"]
        w, h, d = primitive["size_mm"]
        tops.append((y + h / 2, (x - w / 2, x + w / 2, z - d / 2, z + d / 2)))

    def box(size, center):
        return {
            "shape": "box",
            "size_mm": size,
            "center_mm": center,
            "finish": operation.finish,
            "color": operation.color,
        }

    def material():
        low = [
            min(index[k]["swept_bounds_mm"]["min"][i] for k in targets) - origin[i]
            for i in range(3)
        ]
        high = [
            max(index[k]["swept_bounds_mm"]["max"][i] for k in targets) - origin[i]
            for i in range(3)
        ]
        left, right, front, back = low[0] - gap, high[0] + gap, low[2] - gap, high[2] + gap
        feet = {
            "left": (left - wall, left, front - wall, back + wall),
            "right": (right, right + wall, front - wall, back + wall),
            "front": (left, right, front - wall, front),
            "back": (left, right, back, back + wall),
        }
        feet = {face: bounds for face, bounds in feet.items() if face != operation.open_face}
        mounting = None
        for y in sorted({top for top, _ in tops if top <= low[1] + EPSILON}, reverse=True):
            surfaces = [surface for top, surface in tops if abs(top - y) <= EPSILON]
            if all(_covered(foot, surfaces) for foot in feet.values()):
                mounting = y
                break
        if mounting is None:
            raise ValueError(
                "The housing walls do not fit on the modeled stationary base. "
                f"Requested outer footprint is {right - left + 2 * wall:g} x "
                f"{back - front + 2 * wall:g} mm at {gap:g} mm clearance and "
                f"{wall:g} mm wall thickness. No actual coplanar base faces cover "
                "all wall feet. Choose a smaller permitted clearance or design "
                "a wider support explicitly; the existing base is unchanged."
            )
        height = high[1] + gap - mounting
        solids = [
            box([x1 - x0, height, z1 - z0], [(x0 + x1) / 2, height / 2, (z0 + z1) / 2])
            for x0, x1, z0, z1 in feet.values()
        ]
        solids.append(
            box(
                [right - left + 2 * wall, wall, back - front + 2 * wall],
                [(left + right) / 2, height + wall / 2, (front + back) / 2],
            )
        )
        return mounting, solids

    moving = {key for step in previous["steps"] for key in step["moving_component_keys"]}
    for _ in range(len(index) + 1):
        mounting, primitives = material()
        shell_bounds = [
            tuple(
                [v + (mounting if i == 1 else 0) for i, v in enumerate(edge)]
                for edge in _bounds([p])
            )
            for p in primitives
        ]
        obstructing = set()
        for key, part in index.items():
            if key in targets or key == root_key or part["assembly_root_key"] != root_key:
                continue
            offset = [a - b for a, b in zip(part["position_mm"], origin)]
            solids = [
                tuple([v + offset[i] for i, v in enumerate(edge)] for edge in _bounds([p]))
                for p in part["primitives"]
            ]
            if key in moving:
                solids.append(
                    tuple(
                        [v - origin[i] for i, v in enumerate(part["swept_bounds_mm"][e])]
                        for e in ("min", "max")
                    )
                )
            if any(_intersects(a, b) for a in shell_bounds for b in solids):
                obstructing.add(key)
        if not obstructing:
            break
        targets.update(obstructing)
        for _ in index:
            targets.update(key for key, part in index.items() if part["parent_key"] in targets)
    else:
        raise ValueError("Housing clearance expansion exceeded the bounded component count.")
    proposal["components"].append(
        {
            "key": operation.key,
            "name": operation.name,
            "role": operation.role,
            "assembly": operation.assembly,
            "check": operation.check,
            "primitives": primitives,
            "source_id": None,
            "parent_key": root_key,
            "placement_mm": [0, mounting, 0],
        }
    )
    width = previous.get("workspace_width_mm") if workspace_width_mm is None else workspace_width_mm
    compiled = compile_concept(proposal, width)
    issues = assembly_review_issues(compiled, per_component=False)
    if issues:
        raise ValueError("\n".join(issues))
    return compiled


def supported_enclosure_clearance(
    previous_design: dict, request: EnclosureRequest | dict, workspace_width_mm=None
) -> float | None:
    """Suggest the largest passing clearance at bounded 0.5 mm resolution.

    Test the authored value first, then descending half-millimetre values down
    to 0.5 mm, at most 200 attempts. Each candidate passes the complete ordinary
    compiler and support/interface checks. This is feedback only: it never
    adopts a revision, changes the request or overrides a user's minimum.
    Other dimensions, materials, openings and existing equipment stay fixed.
    """
    operation = EnclosureRequest.model_validate(request)
    candidates = [operation.clearance_mm]
    candidates.extend(
        value / 2
        for value in range(math.floor(operation.clearance_mm * 2), 0, -1)
        if value / 2 < operation.clearance_mm
    )
    for clearance in candidates:
        candidate = operation.model_copy(update={"clearance_mm": clearance})
        try:
            add_parametric_enclosure(previous_design, candidate, workspace_width_mm)
        except ValueError:
            continue
        return clearance
    return None
