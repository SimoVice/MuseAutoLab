"""Propose exact registration of repeated solids to an authored linear working axis.

Patterns are candidates for explicit confirmation. This module never changes an
assembly, motion, stopping plan or recipe, and makes no measurement-quality claim.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy

from app.concept_interfaces import WorkInterface, work_interface_issues

TOLERANCE_MM = 1e-5


def _dot(first, second):
    return sum(a*b for a, b in zip(first, second))


def _perpendicular(vector, axis):
    projection = _dot(vector, axis)
    return [value-projection*direction for value, direction in zip(vector, axis)]


def _matching_solid(first, second):
    return first['shape'] == second['shape'] and all(
        math.isclose(a, b, rel_tol=0, abs_tol=TOLERANCE_MM)
        for a, b in zip(first['size_mm'], second['size_mm']))


def sampling_patterns(compiled: dict) -> list[dict]:
    """Find one-to-one, feasible stop fractions for declared repeated-target scans.

    Detection requires an existing step-bound working interface, pure translation,
    2–12 equal target primitives in one component, exactly as many authored stops,
    distinct collinear centres in a plane perpendicular to the ray, and successful
    exact per-primitive working-axis/range checks. Either the tool or target may
    translate; only their relative travel determines registration. No names or
    workflow-specific heuristics are used. Ambiguous or unreachable groups are omitted.
    """
    components = {component['key']: component for component in compiled['components']}
    raw_steps = compiled.get('proposal', {}).get('steps', compiled['steps'])
    steps = {raw['name'].casefold(): step for raw, step in zip(raw_steps, compiled['steps'])}
    patterns, seen = [], set()
    for original in compiled.get('work_interfaces', []):
        interface = WorkInterface.model_validate(original)
        step = steps.get((interface.step_name or '').casefold())
        if step is None or not 2 <= len(step.get('stops', [])) <= 12:
            continue
        if abs(step.get('start_rotation_deg', 0)) > 1e-7 or abs(
                step.get('rotation_delta_deg', step.get('rotation_deg', 0))) > 1e-7:
            continue
        tool, target = components[interface.tool_key], components[interface.target_key]
        moving = set(step['moving_component_keys'])
        travel = step['translation_mm']
        relative = [value*((tool['key'] in moving) - (target['key'] in moving))
                    for value in travel]
        magnitude = math.sqrt(_dot(interface.axis, interface.axis))
        axis = [value/magnitude for value in interface.axis]
        scan = _perpendicular(relative, axis)
        scan_squared = _dot(scan, scan)
        if scan_squared <= TOLERANCE_MM*TOLERANCE_MM:
            continue
        selected = target['primitives'][interface.target_primitive]
        samples = [(index, solid) for index, solid in enumerate(target['primitives'])
                   if _matching_solid(selected, solid)]
        if len(samples) != len(step['stops']):
            continue
        origin = interface.origin_mm or tool['primitives'][interface.tool_primitive]['center_mm']
        origin = [a+b for a, b in zip(origin, tool['position_mm'])]
        centers = [[a+b for a, b in zip(solid['center_mm'], target['position_mm'])]
                   for _, solid in samples]
        first = centers[0]
        phases = []
        compatible = True
        for (index, _), center in zip(samples, centers):
            offset = [a-b for a, b in zip(center, first)]
            if abs(_dot(offset, axis)) > TOLERANCE_MM:
                compatible = False  # Samples do not share a plane perpendicular to the ray.
                break
            lateral = _perpendicular([a-b for a, b in zip(center, origin)], axis)
            phase = _dot(lateral, scan)/scan_squared
            residual = [a-phase*b for a, b in zip(lateral, scan)]
            if (math.sqrt(_dot(residual, residual)) > TOLERANCE_MM
                    or not -1e-10 <= phase <= 1 + 1e-10):
                compatible = False
                break
            phases.append((round(min(1., max(0., phase)), 12), index))
        phases.sort()
        if not compatible or len(phases) != len(samples) or any(
                b[0]-a[0] <= 1e-10 for a, b in zip(phases, phases[1:])):
            continue
        identity = (step['name'], interface.tool_key, interface.tool_primitive,
                    interface.target_key, tuple(interface.axis),
                    tuple(interface.origin_mm or []), interface.min_distance_mm,
                    interface.max_distance_mm, tuple(index for _, index in phases))
        if identity in seen:
            continue
        records = []
        seed = re.sub(r'-sample-\d+$', '', interface.key)[:48]
        for ordinal, (phase, index) in enumerate(phases, 1):
            record = interface.model_dump(mode='json')
            record.update(key=f'{seed}-sample-{index + 1}',
                          label=f'Sampling position {ordinal} on {target["name"][:120]}',
                          target_primitive=index, phase=phase)
            # The ordinary geometric checker, including actual curved surfaces and
            # declared range, is the authority; a projected centre alone is insufficient.
            if work_interface_issues({**compiled, 'work_interfaces': [record]}):
                compatible = False
                break
            records.append(record)
        if not compatible:
            continue
        seen.add(identity)
        patterns.append({
            'kind': 'linear_repeated_solids', 'step_name': step['name'],
            'interface_key': interface.key, 'tool_key': interface.tool_key,
            'tool_name': tool['name'], 'target_key': interface.target_key,
            'target_name': target['name'],
            'sample_primitive_indexes': [index for _, index in phases],
            'fractions': [phase for phase, _ in phases],
            'original_fractions': deepcopy(step['stops']),
            'work_interfaces': records, 'confirmation_required': True,
            'basis': 'Proposed one-to-one registration of authored equal solids. '
                     'Each geometric working-axis/range check passes; '
                     'sample identity, acquisition and measurement quality remain unverified.',
        })
    return patterns
