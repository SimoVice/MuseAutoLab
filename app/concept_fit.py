"""Bounded, transparent geometric fitting of newly authored conceptual assemblies.

The fitter keeps authored solids, device identities, sources, supplies and operating
travel. It proposes small attachment translations and explicitly modeled custom
spacing mounts. Every accepted result still passes the ordinary compiler and the
illustrative support review. It is not mechanical synthesis or fabrication approval.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy
from time import monotonic

from app.concept_design import (
    ConceptProposal,
    ConceptStep,
    _add,
    _bounds,
    _intersects,
    _motion_sweep,
    _rotation_steps,
    assembly_review_issues,
    compile_concept,
)
from app.concept_interfaces import _rotate, work_interface_diagnostics, work_interface_issues

MAX_SHIFT_MM = 80.0
MAX_BRIDGE_MM = 80.0
FIT_SECONDS = 3.0
CLEARANCE_MM = 0.5
MAX_ALIGNMENT_SHIFT_MM = 160.0


def _layout(raw):
    specs = {c['key']: c for c in raw['components']}
    origins, roots = {}, {}

    def locate(key):
        if key not in origins:
            c = specs[key]
            if c['parent_key'] is None:
                origins[key], roots[key] = [0., 0., 0.], key
            else:
                origins[key] = _add(locate(c['parent_key']), c['placement_mm'])
                roots[key] = roots[c['parent_key']]
        return origins[key]

    for key in specs:
        locate(key)
    boxes = {key: [tuple(_add(v, origins[key]) for v in _bounds([p]))
                   for p in c['primitives']] for key, c in specs.items()}
    descendants = {}
    for key in specs:
        descendants[key] = {key}
        for other in specs:
            current = specs[other]['parent_key']
            while current is not None:
                if current == key:
                    descendants[key].add(other)
                current = specs[current]['parent_key']
    conflicts, seen = [], set()
    penalty = 0.

    def record(a, b, first, second, kind):
        nonlocal penalty
        identity = (a, b, kind)
        if identity not in seen and len(conflicts) < 32:
            seen.add(identity)
            conflicts.append({'a': a, 'b': b, 'first': first, 'second': second, 'kind': kind})
            penalty += min(min(first[1][i], second[1][i]) -
                           max(first[0][i], second[0][i]) for i in range(3))

    for a, solids in boxes.items():
        for first in solids:
            if first[0][1] < -1e-7:
                record(a, None, first, first, 'below')
        for b in specs:
            if a >= b or roots[a] != roots[b]:
                continue
            hit = next(((first, second) for first in solids for second in boxes[b]
                        if _intersects(first, second)), None)
            if hit:
                record(a, b, *hit, 'static')
    rotation_steps = _rotation_steps(raw['steps'])
    for index, step_raw in enumerate(raw['steps']):
        step = ConceptStep.model_validate(step_raw)
        moving = descendants.get(step.moving_key, set())
        if not moving:
            continue
        pivot = _add(origins[step.moving_key], step.pivot_mm or [0, 0, 0])
        for a in sorted(moving):
            for first in boxes[a]:
                swept = _motion_sweep(first, step, pivot,
                                      rotation_steps[index]['start_rotation_deg'])
                if swept[0][1] < -1e-7:
                    record(step.moving_key, None, swept, swept, 'below')
                for b in specs:
                    if b in moving or roots[a] != roots[b]:
                        continue
                    hit = next((box for box in boxes[b] if _intersects(swept, box)), None)
                    if hit:
                        record(step.moving_key, b, swept, hit, f'motion {index}')
    return specs, origins, boxes, descendants, conflicts, penalty


def _relative_shift(raw, key, delta):
    candidate = deepcopy(raw)
    component = next(c for c in candidate['components'] if c['key'] == key)
    component['placement_mm'] = [round(a + b, 7) for a, b in
                                 zip(component['placement_mm'], delta)]
    return candidate


def _stack_candidate(raw, layout, original, preserved):
    """Solve coupled floor/sibling height constraints without an invalid intermediate state."""
    specs, _, boxes, _, _, _ = layout
    changes, offsets = [], {}

    def projection_overlap(first, second):
        return all(min(first[1][axis], second[1][axis]) -
                   max(first[0][axis], second[0][axis]) > 1e-7 for axis in (0, 2))

    def raised(bounds, amount):
        return ([bounds[0][0], bounds[0][1] + amount, bounds[0][2]],
                [bounds[1][0], bounds[1][1] + amount, bounds[1][2]])

    for root in (key for key, c in specs.items() if c['parent_key'] is None):
        children = sorted((key for key, c in specs.items() if c['parent_key'] == root),
                          key=lambda key: (min(b[0][1] for b in boxes[key]), key))
        completed = []
        for key in children:
            lift = max(0, -min(b[0][1] for b in boxes[key]))
            # Only actual intersections with root solids impose a floor constraint;
            # an overhead frame member must not lift an otherwise clear nested part.
            for _ in range(len(boxes[root]) + 1):
                required = lift
                for part in boxes[key]:
                    placed = raised(part, lift)
                    for anchor in boxes[root]:
                        if projection_overlap(placed, anchor) and _intersects(placed, anchor):
                            required = max(required, anchor[1][1] - part[0][1])
                if required <= lift + 1e-7:
                    break
                lift = required
            for earlier in completed:
                for lower in boxes[earlier]:
                    for upper in boxes[key]:
                        if projection_overlap(lower, upper):
                            lift = max(lift, lower[1][1] + offsets[earlier] - upper[0][1])
            if lift > 1e-7:
                if key in preserved:
                    return []
                start = original.get(key, specs[key])['placement_mm']
                pose = _add(specs[key]['placement_mm'], [0, lift, 0])
                if math.dist(pose, start) > MAX_SHIFT_MM:
                    return []
                changes.append((key, lift))
            offsets[key] = lift
            completed.append(key)
    if not changes:
        return []
    candidate = deepcopy(raw)
    details = []
    for key, lift in changes:
        component = next(c for c in candidate['components'] if c['key'] == key)
        before = list(component['placement_mm'])
        component['placement_mm'][1] += lift
        details.append(f'{component["name"]}: {before} -> {component["placement_mm"]} mm')
    return [(candidate, 'Resolved a coupled projected vertical stack while preserving X/Z, '
                        'authored solids and travel: ' + '; '.join(details) + '. '
                        'Proposed touching faces still require mounting and load review.')]


def _shift_candidates(raw, layout, original, preserved):
    specs, _, _, descendants, conflicts, _ = layout
    choices = []
    for problem in conflicts[:8]:
        a, b = problem['a'], problem['b']
        if b is None:
            options = [(a, [0, -problem['first'][0][1] + CLEARANCE_MM, 0])]
        else:
            options = []
            for key, other, first, second in ((b, a, problem['first'], problem['second']),
                                               (a, b, problem['second'], problem['first'])):
                if other in descendants[key]:
                    continue  # Moving an ancestor would move both colliding parts.
                for axis in range(3):
                    for shift in (first[1][axis] - second[0][axis] + CLEARANCE_MM,
                                  first[0][axis] - second[1][axis] - CLEARANCE_MM):
                        delta = [0., 0., 0.]
                        delta[axis] = shift
                        options.append((key, delta))
        for key, delta in options:
            if specs[key]['parent_key'] is None or key in preserved:
                continue
            start = original.get(key, specs[key])['placement_mm']
            displacement = [p + d - s for p, d, s in
                            zip(specs[key]['placement_mm'], delta, start)]
            if math.dist(displacement, [0, 0, 0]) > MAX_SHIFT_MM:
                continue
            cost = math.dist(delta, [0, 0, 0])
            if b is not None and delta[1] and specs[a]['parent_key'] == specs[b]['parent_key']:
                if abs(specs[a]['placement_mm'][1] - specs[b]['placement_mm'][1]) < 1:
                    cost *= 8  # Prefer preserving repeated features' common working plane.
            choices.append((cost, key, delta, problem['kind']))
    unique = {}
    for choice in sorted(choices, key=lambda value: (value[0], value[1], tuple(value[2]))):
        _, key, delta, why = choice
        unique.setdefault((key, tuple(delta)), (_relative_shift(raw, key, delta),
                          f'Adjusted {specs[key]["name"]} attachment by {delta} mm '
                          f'to resolve {why} geometric interference.'))
    return _stack_candidate(raw, layout, original, preserved) + list(unique.values())


def _alignment_candidates(raw, design, layout, original, preserved):
    specs, _, _, descendants, _, _ = layout
    choices = []
    for diagnostic in work_interface_diagnostics(design):
        delta_world = diagnostic['mount_correction_mm']
        if not diagnostic['needs_correction'] or delta_world is None:
            continue
        key = diagnostic['tool_key']
        while key is not None:
            component = specs[key]
            if (component['parent_key'] is not None and key not in preserved
                    and diagnostic['target_key'] not in descendants[key]):
                delta = list(delta_world)
                step = next((s for s in _rotation_steps(raw['steps']) if s['name'].casefold() ==
                             (diagnostic['step_name'] or '').casefold()), None)
                if step is not None and key in descendants.get(step['moving_key'], set()):
                    if step['moving_key'] not in descendants[key]:
                        effective = (step['start_rotation_deg'] +
                                     step['rotation_delta_deg']*diagnostic['phase'])
                        delta = _rotate(delta, step['rotation_axis'], -math.radians(effective))
                shifted = _relative_shift(raw, key, delta)
                edited = next(c for c in shifted['components'] if c['key'] == key)
                start = original[key]['placement_mm']
                if math.dist(edited['placement_mm'], start) <= MAX_ALIGNMENT_SHIFT_MM:
                    choices.append((shifted,
                                    f'Aligned {component["name"]} mounting by {delta} mm '
                                    f'for working interface {diagnostic["key"]!r}; '
                                    'actual target centre '
                                    f'{diagnostic["world_target_center_mm"]} mm '
                                    f'at {diagnostic["step_name"] or "rest"} '
                                    f'phase {diagnostic["phase"]:g}. '
                                    'Axis, target and travel preserved.'))
            key = component['parent_key']
    return choices


def _support_candidates(raw, layout, issues, preserved, original):
    specs, origins, boxes, descendants, _, _ = layout
    choices = []
    unsupported = set()
    for issue in issues:
        match = re.search(r"geometry: '([^']+)'.*?primitive (\d+)", issue)
        if match:
            unsupported.add((match[1], int(match[2])))
    for issue in issues:
        match = re.search(r"geometry: '([^']+)'.*?primitive (\d+)", issue)
        if match is None:
            continue
        key = match[1]
        component = specs[key]
        parent_key = component['parent_key']
        if parent_key is None:
            continue
        child_box = boxes[key][int(match[2])]
        targets = [(parent_key, p) for p in boxes[parent_key]]
        targets += [(key, p) for i, p in enumerate(boxes[key]) if (key, i) not in unsupported]
        for target_key, parent_box in targets:
            gaps = [max(child_box[0][i] - parent_box[1][i],
                        parent_box[0][i] - child_box[1][i], 0) for i in range(3)]
            separated = [i for i, value in enumerate(gaps) if value > 1e-7]
            if len(separated) != 1:
                continue
            axis = separated[0]
            if not 1 < gaps[axis] <= MAX_BRIDGE_MM:
                continue
            overlap_low = [max(child_box[0][i], parent_box[0][i]) for i in range(3)]
            overlap_high = [min(child_box[1][i], parent_box[1][i]) for i in range(3)]
            if any(overlap_high[i] - overlap_low[i] < 0.5 for i in range(3) if i != axis):
                continue
            delta = [0., 0., 0.]
            delta[axis] = ((-1 if child_box[0][axis] > parent_box[1][axis] else 1)
                           * (gaps[axis] - CLEARANCE_MM))
            if target_key == parent_key and key not in preserved and gaps[axis] <= 8:
                shifted = _relative_shift(raw, key, delta)
                new = next(c for c in shifted['components'] if c['key'] == key)
                start = original.get(key, component)['placement_mm']
                if math.dist(new['placement_mm'], start) <= MAX_SHIFT_MM:
                    choices.append((shifted, f'Anchored {component["name"]} by {delta} mm '
                                    'to close its small proposed mounting gap.'))
            if len(specs) >= 40 or len(specs) + len(raw.get('supplies', [])) >= 64:
                continue
            # A separate custom mount preserves the authored device solids and its
            # functional centre. Its end faces meet the two existing facing surfaces.
            low = list(overlap_low)
            high = list(overlap_high)
            if child_box[0][axis] > parent_box[1][axis]:
                low[axis], high[axis] = parent_box[1][axis], child_box[0][axis]
            else:
                low[axis], high[axis] = child_box[1][axis], parent_box[0][axis]
            sizes = [high[i] - low[i] if i == axis else
                     min(6., high[i] - low[i]) for i in range(3)]
            center = [(low[i] + high[i]) / 2 for i in range(3)]
            attachment_key = target_key
            for step in raw['steps']:
                moving = descendants.get(step['moving_key'], set())
                if key in moving and target_key not in moving:
                    attachment_key = key  # The proposed tool bracket travels with its tool.
                    break
            local_origin = [center[0], center[1] - sizes[1]/2, center[2]]
            placement = [a - b for a, b in zip(local_origin, origins[attachment_key])]
            stem = ('fit-mount-' + key)[:59]
            mount_key, suffix = stem, 1
            supply_keys = {s['key'] for s in raw.get('supplies', [])}
            while mount_key in specs or mount_key in supply_keys:
                mount_key, suffix = f'{stem}-{suffix}', suffix + 1
            mount_number = 1 + sum(k == stem or k.startswith(stem + '-') for k in specs)
            existing_names = {c['name'].casefold() for c in specs.values()}
            mount_name = (f'Proposed mount {mount_number} for ' + component['name'])[:120]
            while mount_name.casefold() in existing_names:
                mount_number += 1
                mount_name = (f'Proposed mount {mount_number} for ' + component['name'])[:120]
            mount = {
                'key': mount_key,
                'name': mount_name,
                'role': 'Unverified custom spacing bracket connecting the proposed '
                        'attachment surfaces; joint strength and fasteners require design.',
                'parent_key': attachment_key, 'placement_mm': placement, 'source_id': None,
                'primitives': [{'shape': 'box', 'size_mm': sizes,
                                'center_mm': [0, sizes[1]/2, 0], 'finish': 'accent'}],
                'assembly': f'Propose this custom bracket from {specs[target_key]["name"]} '
                            f'and {component["name"]}; specify and review fixing hardware.',
                'check': 'Verify material, joints, loads, access and the entire intended '
                         'travel physically before commissioning.',
            }
            candidate = deepcopy(raw)
            candidate['components'].append(mount)
            centers = [center]
            cross_axes = [i for i in range(3) if i != axis]
            for first_side, second_side in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
                variant_center = list(center)
                for i, side in zip(cross_axes, (first_side, second_side)):
                    variant_center[i] = low[i] + sizes[i]/2 if side < 0 else high[i] - sizes[i]/2
                if variant_center not in centers:
                    centers.append(variant_center)
            for location in centers:
                variant = deepcopy(candidate)
                origin = [location[0], location[1] - sizes[1]/2, location[2]]
                pose = [a - b for a, b in zip(origin, origins[attachment_key])]
                variant['components'][-1]['placement_mm'] = pose
                choices.append((variant, f'Added modeled custom mount {mount_key!r} '
                                f'between {specs[target_key]["name"]} and {component["name"]}; '
                                f'box {sizes} mm at parent-relative {pose} mm. '
                                'Proposed geometry only; joints and fabrication unverified.'))
                if len(choices) >= 18:
                    return choices
    return choices


def fit_concept(proposal, workspace_width_mm=None, *, prior_proposal=None, max_attempts=96):
    """Return a fully checked fit plus transparent adjustments, or no partial design.

    Unchanged prior components are frozen. Authored solids, supplies and travel are
    never altered. Attachment movement is limited to 80 mm from the authored pose;
    face-to-face custom supports span at most 80 mm. Search is capped by candidate
    count, scene complexity and three seconds, whichever is reached first.
    """
    if (isinstance(max_attempts, bool) or not isinstance(max_attempts, int)
            or not 1 <= max_attempts <= 256):
        raise ValueError('Fit attempts must be an integer from 1 to 256.')
    deadline = monotonic() + FIT_SECONDS
    try:
        raw = ConceptProposal.model_validate(proposal).model_dump(mode='json')
        if workspace_width_mm is not None and (
                isinstance(workspace_width_mm, bool)
                or not isinstance(workspace_width_mm, (int, float))
                or not math.isfinite(workspace_width_mm) or not 1 <= workspace_width_mm <= 20000):
            raise ValueError('Workspace width must be a finite number from 1 to 20000 mm.')
    except ValueError as exc:
        return None, [f'Automatic fit requires a valid declarative proposal: {str(exc)[:1200]}']
    original = {c['key']: deepcopy(c) for c in raw['components']}
    try:
        prior = (ConceptProposal.model_validate(prior_proposal).model_dump(mode='json')
                 if prior_proposal is not None else {})
    except ValueError as exc:
        return None, ['Prior proposal is invalid; automatic fit was not attempted: '
                      + str(exc)[:500]]
    previous = {c['key']: c for c in prior.get('components', [])}
    preserved = {key for key, spec in original.items() if previous.get(key) == spec}
    last_issue, attempts = '', 0

    def evaluate(candidate):
        nonlocal attempts, last_issue
        attempts += 1
        layout = _layout(candidate)
        conflicts, penalty = layout[-2:]
        if conflicts:
            return (len(conflicts), penalty, 0, 0), layout, None, [], None
        try:
            design = compile_concept(candidate, workspace_width_mm, _skip_work_interfaces=True)
        except ValueError as exc:
            last_issue = str(exc)[:1000]
            return (1000, 0, 0, 0), layout, None, [], None
        interface_issues = work_interface_issues(design)
        issues = assembly_review_issues(design, max_issues=800, per_component=False)
        last_issue = '\n'.join((interface_issues + issues)[:2])[:1200]
        ready = design if not interface_issues and not issues else None
        return (0, 0, len(interface_issues), len(issues)), layout, ready, issues, design

    state, adjustments = raw, []
    try:
        already_compiled = compile_concept(raw, workspace_width_mm)
        if not assembly_review_issues(already_compiled):
            return already_compiled, []
    except ValueError as exc:
        last_issue = str(exc)[:1000]
    if (len(raw['components']) > 24 or sum(len(c['primitives']) for c in raw['components']) > 200
            or sum(len(c['primitives']) for c in raw['components']) * len(raw['steps']) > 1600):
        return None, ['Automatic fit stopped at its scene-complexity bound. '
                      'The original authored design and operating travel were preserved.']
    current_score, layout, ready, review, unchecked = evaluate(state)
    visited = set()
    while attempts < max_attempts and monotonic() < deadline:
        if layout[-2]:
            candidates = _shift_candidates(state, layout, original, preserved)
        elif current_score[2]:
            candidates = _alignment_candidates(state, unchecked, layout, original, preserved)
        else:
            candidates = _support_candidates(state, layout, review, preserved, original)
        best = None
        for candidate, explanation in candidates[:18]:
            identity = repr([(c['key'], c['placement_mm'], c['primitives'])
                             for c in candidate['components']])
            if identity in visited:
                continue
            visited.add(identity)
            if attempts >= max_attempts or monotonic() >= deadline:
                break
            score, candidate_layout, compiled, issues, candidate_unchecked = evaluate(candidate)
            if compiled is not None:
                return compiled, adjustments + [explanation]
            if score < current_score and (best is None or score < best[0]):
                best = (score, candidate, candidate_layout, issues, explanation,
                        candidate_unchecked)
                if not layout[-2] and not current_score[2]:
                    break  # Valid added material monotonically improves the support graph.
        if best is None:
            break
        current_score, state, layout, review, explanation, unchecked = best
        adjustments.append(explanation)
    if not last_issue and layout[-2]:
        issue = layout[-2][0]
        last_issue = (f'{issue["kind"]} interference between {issue["a"]!r} '
                      f'and {issue["b"]!r} remains.')
    return None, [f'No complete fit within {attempts} checked candidates and the bounded '
                  'attachment/support search. No partial changes were accepted. ' + last_issue]
