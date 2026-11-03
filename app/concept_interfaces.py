"""Generic axis-to-solid working interfaces for conceptual assemblies.

The checks establish proposed geometric alignment and axis clearance only. They
do not validate optics, focus, field of view, measurement quality or physical fit.
"""

from __future__ import annotations

import math
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Vector = Annotated[list[float], Field(min_length=3, max_length=3)]


class WorkInterface(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True,
                              revalidate_instances='always')
    key: str = Field(min_length=1, max_length=64, pattern=r'^[a-z][a-z0-9_-]*$')
    label: str = Field(min_length=1, max_length=160)
    tool_key: str = Field(min_length=1, max_length=64)
    tool_primitive: int = Field(strict=True, ge=0, le=63)
    target_key: str = Field(min_length=1, max_length=64)
    target_primitive: int = Field(strict=True, ge=0, le=63)
    axis: Vector
    origin_mm: Vector | None = None
    step_name: str | None = Field(default=None, min_length=1, max_length=160)
    phase: float = Field(default=0, ge=0, le=1)
    min_distance_mm: float = Field(default=0, ge=0, le=20000)
    max_distance_mm: float | None = Field(default=None, gt=0, le=20000)

    @field_validator('axis', 'origin_mm', mode='before')
    @classmethod
    def finite_vector(cls, value, info):
        if value is None and info.field_name == 'origin_mm':
            return value
        if (not isinstance(value, (list, tuple)) or len(value) != 3 or any(
                isinstance(n, bool) or not isinstance(n, (int, float))
                or not math.isfinite(n) or abs(n) > 20000 for n in value)):
            raise ValueError('Interface coordinates must be three finite bounded numbers.')
        return value

    @field_validator('phase', 'min_distance_mm', 'max_distance_mm', mode='before')
    @classmethod
    def finite_number(cls, value, info):
        if value is None and info.field_name == 'max_distance_mm':
            return value
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value)):
            raise ValueError('Interface phase and distances must be finite numbers.')
        return value

    @model_validator(mode='after')
    def coherent_interface(self):
        if not math.isclose(sum(v*v for v in self.axis), 1, abs_tol=1e-6):
            raise ValueError('Interface axis must be a unit direction vector.')
        if self.max_distance_mm is not None and self.max_distance_mm < self.min_distance_mm:
            raise ValueError('Interface maximum distance cannot be below its minimum.')
        if self.step_name is None and self.phase:
            raise ValueError('A nonzero interface phase requires a named operating step.')
        if self.tool_key == self.target_key and self.tool_primitive == self.target_primitive:
            raise ValueError('An interface cannot target its own tool primitive.')
        return self


def interface_binding_issues(interfaces, components, steps):
    """Check declared primitive and step links before any geometric transform."""
    specs = {c.key: c for c in components}
    names = {step.name.casefold() for step in steps}
    keys, issues = set(), []
    for interface in interfaces:
        if interface.key in keys:
            issues.append(f'Work interface key {interface.key!r} is duplicated.')
        keys.add(interface.key)
        for role in ('tool', 'target'):
            key = getattr(interface, role + '_key')
            index = getattr(interface, role + '_primitive')
            if key not in specs:
                issues.append(f'Interface {interface.key!r} ({interface.label}) has unknown '
                              f'{role} component {key!r}.')
            elif index >= len(specs[key].primitives):
                issues.append(f'Interface {interface.key!r} ({interface.label}) references '
                              f'{role} {key!r} primitive {index}, but it has only '
                              f'{len(specs[key].primitives)} primitives (zero-based indexes).')
        if interface.step_name is not None and interface.step_name.casefold() not in names:
            issues.append(f'Interface {interface.key!r} has unknown step {interface.step_name!r}.')
    return issues[:12]


def _rotate(vector, axis, angle):
    if axis is None or not angle:
        return list(vector)
    index = 'xyz'.index(axis)
    x, y, z = vector
    cross = ([0, -z, y], [z, 0, -x], [-y, x, 0])[index]
    return [vector[i] if i == index else vector[i]*math.cos(angle) + cross[i]*math.sin(angle)
            for i in range(3)]


def _ray_hit(origin, direction, primitive):
    """First positive ray entry into the actual local box, sphere or Y cylinder."""
    size = primitive['size_mm']
    if primitive['shape'] == 'box':
        near, far = -math.inf, math.inf
        for i in range(3):
            if abs(direction[i]) < 1e-12:
                if abs(origin[i]) > size[i]/2 + 1e-7:
                    return None
            else:
                a, b = ((-size[i]/2-origin[i])/direction[i],
                        (size[i]/2-origin[i])/direction[i])
                near, far = max(near, min(a, b)), min(far, max(a, b))
        return max(near, 0) if far >= max(near, 0) - 1e-7 else None
    if primitive['shape'] == 'sphere':
        b = 2 * sum(a*d for a, d in zip(origin, direction))
        c = sum(a*a for a in origin) - (size[0]/2)**2
        discriminant = b*b - 4*c
        if discriminant < -1e-7:
            return None
        roots = [(-b - math.sqrt(max(0, discriminant)))/2,
                 (-b + math.sqrt(max(0, discriminant)))/2]
        return max(0, roots[0]) if roots[1] >= -1e-7 else None
    radius, height = size[0]/2, size[1]/2
    if origin[0]**2 + origin[2]**2 <= radius*radius and abs(origin[1]) <= height:
        return 0.
    hits = []
    a = direction[0]**2 + direction[2]**2
    b = 2 * (origin[0]*direction[0] + origin[2]*direction[2])
    c = origin[0]**2 + origin[2]**2 - radius*radius
    discriminant = b*b - 4*a*c
    if a > 1e-12 and discriminant >= -1e-7:
        for t in ((-b-math.sqrt(max(0, discriminant)))/(2*a),
                  (-b+math.sqrt(max(0, discriminant)))/(2*a)):
            if t >= -1e-7 and abs(origin[1] + t*direction[1]) <= height + 1e-7:
                hits.append(max(0, t))
    if abs(direction[1]) > 1e-12:
        for cap in (-height, height):
            t = (cap-origin[1])/direction[1]
            if t >= -1e-7 and ((origin[0]+t*direction[0])**2 +
                              (origin[2]+t*direction[2])**2 <= radius*radius + 1e-7):
                hits.append(max(0, t))
    return min(hits) if hits else None


def work_interface_issues(design: dict, *, diagnostics=None) -> list[str]:
    """Evaluate declared working axes at exact proposed poses; never infer a target."""
    specs = {c['key']: c for c in design['components']}
    raw_steps = design.get('proposal', {}).get('steps', design['steps'])
    steps = {raw['name'].casefold(): compiled
             for raw, compiled in zip(raw_steps, design['steps'])}
    issues = []
    for raw in design.get('work_interfaces', []):
        interface = WorkInterface.model_validate(raw)
        tool, target = specs[interface.tool_key], specs[interface.target_key]
        tool_solid = tool['primitives'][interface.tool_primitive]
        target_solid = target['primitives'][interface.target_primitive]
        local_origin = interface.origin_mm or tool_solid['center_mm']
        if any(abs(a-c) > size/2 + 1e-7 for a, c, size in
               zip(local_origin, tool_solid['center_mm'], tool_solid['size_mm'])):
            issues.append(f'Interface {interface.key!r}: origin_mm {local_origin} lies outside '
                          f'{tool["name"]} primitive {interface.tool_primitive}. '
                          'Place the axis origin within the selected tool envelope.')
            continue
        origin = [a + b for a, b in zip(local_origin, tool['position_mm'])]
        magnitude = math.sqrt(sum(value*value for value in interface.axis))
        direction = [value/magnitude for value in interface.axis]
        step = steps.get((interface.step_name or '').casefold())
        moving, angle, pivot, translation, axis = set(), 0., [0, 0, 0], [0, 0, 0], None
        if step is not None:
            moving = set(step['moving_component_keys'])
            increment = step.get('rotation_delta_deg', step['rotation_deg'])
            angle = math.radians(step.get('start_rotation_deg', 0) + increment*interface.phase)
            axis = step['rotation_axis']
            translation = [value * interface.phase for value in step['translation_mm']]
            if step['moving_key'] is not None:
                pivot = [a + b for a, b in zip(specs[step['moving_key']]['position_mm'],
                                              step['pivot_mm'] or [0, 0, 0])]
        if tool['key'] in moving:
            offset = _rotate([a-b for a, b in zip(origin, pivot)], axis, angle)
            origin = [a+b+c for a, b, c in zip(offset, pivot, translation)]
            direction = _rotate(direction, axis, angle)
        target_origin, target_direction = list(origin), list(direction)
        if target['key'] in moving:
            target_origin = _rotate([a-b-c for a, b, c in zip(origin, pivot, translation)],
                                    axis, -angle)
            target_origin = [a+b for a, b in zip(target_origin, pivot)]
            target_direction = _rotate(direction, axis, -angle)
        target_origin = [a-b-c for a, b, c in zip(target_origin, target['position_mm'],
                                                target_solid['center_mm'])]
        distance = _ray_hit(target_origin, target_direction, target_solid)
        target_center = [a+b for a, b in zip(target['position_mm'], target_solid['center_mm'])]
        if target['key'] in moving:
            offset = _rotate([a-b for a, b in zip(target_center, pivot)], axis, angle)
            target_center = [a+b+c for a, b, c in zip(offset, pivot, translation)]
        toward = [a-b for a, b in zip(target_center, origin)]
        projection = sum(a*b for a, b in zip(toward, direction))
        lateral = [a-projection*b for a, b in zip(toward, direction)]
        target_lateral = _rotate(lateral, axis, -angle) if target['key'] in moving else lateral
        aligned_hit = _ray_hit([a+b for a, b in zip(target_origin, target_lateral)],
                               target_direction, target_solid)
        correction = None
        if aligned_hit is not None:
            desired = max(interface.min_distance_mm, aligned_hit)
            if interface.max_distance_mm is not None:
                desired = min(desired, interface.max_distance_mm)
            correction = [a+b*(aligned_hit-desired) for a, b in zip(lateral, direction)]
        invalid = distance is None or distance < interface.min_distance_mm - 1e-7 or (
            interface.max_distance_mm is not None and distance > interface.max_distance_mm + 1e-7)
        if diagnostics is not None:
            diagnostics.append({'key': interface.key, 'tool_key': interface.tool_key,
                                'target_key': interface.target_key,
                                'step_name': interface.step_name,
                                'phase': interface.phase, 'world_origin_mm': origin,
                                'world_direction': direction,
                                'world_target_center_mm': target_center,
                                'miss_vector_mm': lateral, 'mount_correction_mm': correction,
                                'distance_mm': distance, 'needs_correction': invalid})
        context = (f'Interface {interface.key!r} ({interface.label}): {tool["name"]} '
                   f'primitive {interface.tool_primitive} axis toward {target["name"]} '
                   f'primitive {interface.target_primitive} at '
                   f'{interface.step_name or "rest"}, phase {interface.phase:g}')
        if distance is None:
            issues.append(context + f' misses the actual {target_solid["shape"]} target. '
                          f'World ray origin {origin}, unit direction {direction}. '
                          f'Expected target centre {target_center} mm; perpendicular '
                          f'mount correction {lateral} mm; range-aware correction {correction} mm. '
                          'Revise the tool mounting position/axis or the intended target/phase; '
                          'do not substitute a nearby hub or an envelope for the sample.')
        elif distance < interface.min_distance_mm - 1e-7 or (
                interface.max_distance_mm is not None
                and distance > interface.max_distance_mm + 1e-7):
            issues.append(context + f' reaches the target at {distance:g} mm, outside '
                          f'the declared clearance/range [{interface.min_distance_mm:g}, '
                          f'{interface.max_distance_mm}] mm. Revise mounting distance or '
                          'declare the supported working range with evidence.')
    return issues[:12]


def work_interface_diagnostics(design: dict) -> list[dict]:
    """Return pose-specific, explicit mounting corrections without changing axis metadata."""
    result = []
    work_interface_issues(design, diagnostics=result)
    return result
