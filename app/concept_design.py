"""Validated, open-ended conceptual assemblies and deterministic millimetre meshes.

These solids are proposed geometry, not fabrication-ready or imported vendor CAD.
Parent links express proposed rigid attachment; no fastener or control is inferred.
"""

from __future__ import annotations

import math
import re
import struct
from itertools import combinations
from typing import Annotated, Literal
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.bench_station import SOURCES
from app.catalog import build_sourcing
from app.concept_interfaces import WorkInterface, interface_binding_issues, work_interface_issues
from app.design_sources import reference_library
from app.jubilee_procurement import upstream_candidate_groups
from app.supplier_catalogs import PRODUCTS

Vector = Annotated[list[float], Field(min_length=3, max_length=3)]
Text = Annotated[str, Field(min_length=1, max_length=2000)]
GAP_MM = 20.0
EPSILON = 1e-7


def concept_sources() -> dict:
    """Return reviewed candidates without claiming that generated solids use vendor CAD."""
    result = {r['id']: {
                  **r, 'geometry_basis': 'custom_concept_not_vendor_cad',
                  'use': 'Sourcing or design reference only for this concept. No source CAD '
                         'is imported and generated dimensions are not vendor dimensions.',
                  'reference_limits': r['limits'],
                  'limits': 'Generated solids are custom concepts. Verify selected dimensions, '
                            'interfaces and compatibility independently before procurement.',
                  'source_kind': ('open_source_project' if r['kind'] in
                                  ('open_hardware', 'open_source') else 'product'),
                  'purchase_scope': ('Reference project; not a purchasable complete machine.'
                                     if r['kind'] in ('open_hardware', 'open_source') else
                                     'Candidate product; selected configuration requires review.'),
              }
              for r in reference_library()['references']}
    candidate_options = {
        option['id']: option for group in
        build_sourcing()['groups'] + upstream_candidate_groups() for option in group['options']
    }
    candidate_options['camera-module-3'] = {
        'label': 'Raspberry Pi Camera Module 3 Standard (Adafruit 5657)',
        'compatibility_note': 'Requires a compatible CSI host and cable; lens, lighting, '
                              'field of view and mounting must be selected.',
    }
    for key, product in PRODUCTS.items():
        option = candidate_options[key]
        candidate = {
            'id': key, 'title': option['label'], 'url': product.url,
            'publisher': product.supplier, 'supplier': product.supplier, 'sku': product.sku,
            'source_kind': 'product', 'catalog_product_id': key,
            'purchase_url': product.url, 'pack_size': product.pack_size,
            'variant_id': product.variant_id, 'variant_title': product.variant_title,
            'checked_on': option.get('checked_on'),
            'geometry_basis': 'custom_concept_not_vendor_cad',
            'purchase_scope': 'Candidate product or kit; verify exact configuration, '
                              'quantity, stock and compatibility before purchase.',
            'limits': option['compatibility_note'] + ' Generated geometry is a custom concept; '
                      'this link does not establish dimensional agreement or manufacturability.',
        }
        # Historical reference IDs and documentation URLs remain stable. Add purchase
        # identity without replacing their source title, original facts or provenance.
        result[key] = {**candidate, **result.get(key, {}), 'catalog_product_id': key,
                       'purchase_url': product.url, 'supplier': product.supplier,
                       'sku': product.sku}
    for key, (title, url) in SOURCES.items():
        result[f'bench-{key}'] = {
            'id': f'bench-{key}', 'title': title, 'url': url,
            'source_kind': 'product',
            'purchase_scope': 'Candidate product; selected configuration requires review.',
            'geometry_basis': 'custom_concept_not_vendor_cad',
            'limits': 'Sourcing candidate only; generated dimensions and compatibility unverified.',
        }
    return result


def _vector(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 3
            or any(isinstance(n, bool) or not isinstance(n, (int, float))
                   or not math.isfinite(n) for n in value)):
        raise ValueError('Coordinates must be three finite numbers in millimetres.')
    return value


class _Model(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True,
                              revalidate_instances='always')

    @field_validator('*', mode='after')
    @classmethod
    def readable_text(cls, value):
        if isinstance(value, str) and (not value or any(ord(c) < 32 and c not in '\n\t'
                                                       for c in value)):
            raise ValueError('Text must be nonempty and contain no control characters.')
        return value


class ConceptPrimitive(_Model):
    shape: Literal['box', 'cylinder', 'sphere']
    size_mm: Vector
    center_mm: Vector
    finish: Literal['frame', 'steel', 'polymer', 'clear', 'accent', 'dark']
    color: str | None = Field(default=None, pattern=r'^#[0-9a-fA-F]{6}$')

    @field_validator('size_mm', 'center_mm', mode='before')
    @classmethod
    def finite_vectors(cls, value):
        return _vector(value)

    @model_validator(mode='after')
    def bounded_shape(self):
        if any(not 0.5 <= n <= 2500 for n in self.size_mm):
            raise ValueError('Primitive dimensions must be between 0.5 and 2500 mm.')
        if any(abs(n) > 4000 for n in self.center_mm):
            raise ValueError('Primitive centres must be within 4000 mm of the local origin.')
        x, y, z = self.size_mm
        if self.shape == 'cylinder' and not math.isclose(x, z, abs_tol=EPSILON):
            raise ValueError('An upright cylinder needs equal X/Z diameters and Y height.')
        if self.shape == 'sphere' and not (
                math.isclose(x, y, abs_tol=EPSILON) and math.isclose(x, z, abs_tol=EPSILON)):
            raise ValueError('A sphere needs the same diameter on all three axes.')
        return self


class ConceptComponent(_Model):
    key: str = Field(min_length=1, max_length=64, pattern=r'^[a-z][a-z0-9_-]*$')
    name: Annotated[str, Field(min_length=1, max_length=120)]
    role: Text
    primitives: list[ConceptPrimitive] = Field(min_length=1, max_length=64)
    source_id: str | None
    assembly: Text
    check: Text
    parent_key: str | None = None
    placement_mm: Vector | None = None

    @field_validator('placement_mm', mode='before')
    @classmethod
    def finite_placement(cls, value):
        return None if value is None else _vector(value)

    @model_validator(mode='after')
    def local_geometry(self):
        low, high = _bounds(self.primitives)
        if abs(low[1]) > EPSILON:
            raise ValueError('Each component must rest on local Y=0; centre solids accordingly.')
        if any(b - a > 4000 for a, b in zip(low, high)):
            raise ValueError('A component envelope cannot exceed 4000 mm on any axis.')
        if self.placement_mm is not None and any(abs(n) > 4000 for n in self.placement_mm):
            raise ValueError('Attachment positions must be within 4000 mm of the parent.')
        if self.parent_key is None and self.placement_mm is not None:
            raise ValueError('Root components are packed automatically; omit placement_mm.')
        if self.parent_key is not None and self.placement_mm is None:
            raise ValueError('Attached components require placement_mm relative to the parent.')
        if self.source_id is not None and self.source_id not in concept_sources():
            raise ValueError('Unknown source ID; use an approved candidate or null.')
        return self


class ConceptStep(_Model):
    name: Annotated[str, Field(min_length=1, max_length=160)]
    instruction: Text
    component_keys: list[str] = Field(min_length=1, max_length=40)
    moving_key: str | None
    translation_mm: Vector
    rotation_deg: float = 0
    rotation_axis: Literal['x', 'y', 'z'] | None = None
    pivot_mm: Vector | None = None
    stops: list[float] = Field(default_factory=list, max_length=12)
    rotation_reference: Literal['from_rest', 'previous_index'] = 'from_rest'
    index_station: Annotated[str, Field(min_length=1, max_length=120)] | None = None

    @field_validator('stops', mode='before')
    @classmethod
    def bounded_stops(cls, value):
        if (not isinstance(value, list) or any(
                isinstance(n, bool) or not isinstance(n, (int, float))
                or not math.isfinite(n) or not 0 <= n <= 1 for n in value)):
            raise ValueError('Stops must be finite travel fractions from 0 to 1.')
        if any(b <= a for a, b in zip(value, value[1:])):
            raise ValueError('Stops must be strictly increasing without duplicates.')
        return value

    @field_validator('rotation_deg', mode='before')
    @classmethod
    def finite_angle(cls, value):
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not -180 <= value <= 180):
            raise ValueError('Rotation must be a finite number from -180 to 180 degrees.')
        return value

    @field_validator('pivot_mm', mode='before')
    @classmethod
    def finite_pivot(cls, value):
        return None if value is None else _vector(value)

    @field_validator('translation_mm', mode='before')
    @classmethod
    def finite_translation(cls, value):
        return _vector(value)

    @model_validator(mode='after')
    def bounded_translation(self):
        if any(abs(n) > 2000 for n in self.translation_mm):
            raise ValueError('Concept motion is limited to 2000 mm per axis from rest.')
        if self.moving_key is None and any(abs(n) > EPSILON for n in self.translation_mm):
            raise ValueError('A translated step must name its moving component.')
        if self.rotation_deg and (self.moving_key is None or self.rotation_axis is None
                                  or self.pivot_mm is None):
            raise ValueError('Rotation requires a moving component, axis and local pivot.')
        if (self.rotation_axis is None) != (self.pivot_mm is None):
            raise ValueError('Provide both a rotation axis and a local pivot, or neither.')
        if self.pivot_mm is not None and any(abs(n) > 4000 for n in self.pivot_mm):
            raise ValueError('Rotation pivots must be within 4000 mm of the moving origin.')
        if self.stops and self.moving_key is None:
            raise ValueError('Planned travel checkpoints require a moving component.')
        if self.index_station is not None and (
                self.moving_key is None or self.rotation_axis is None
                or self.pivot_mm is None or any(abs(n) > EPSILON for n in self.translation_mm)):
            raise ValueError('An explicit index station requires a rotary component, axis, '
                             'pivot and zero translation.')
        return self


class ConceptSoftware(_Model):
    controller: Text
    interfaces: list[Text] = Field(max_length=30)
    setup: list[Text] = Field(min_length=1, max_length=40)
    checks: list[Text] = Field(min_length=1, max_length=40)


class ConceptSupply(_Model):
    key: str = Field(min_length=1, max_length=64, pattern=r'^[a-z][a-z0-9_-]*$')
    name: Annotated[str, Field(min_length=1, max_length=120)]
    quantity: int = Field(strict=True, ge=1, le=100000)
    unit: Annotated[str, Field(min_length=1, max_length=40)]
    role: Text
    source_id: str | None
    component_keys: list[str] = Field(min_length=1, max_length=40)
    additional_to_modeled_parts: bool = False

    @field_validator('source_id')
    @classmethod
    def known_source(cls, value):
        if value is not None and value not in concept_sources():
            raise ValueError('Unknown supply source ID; use an approved candidate or null.')
        return value


class ConceptProposal(_Model):
    title: Annotated[str, Field(min_length=1, max_length=160)]
    overview: Text
    components: list[ConceptComponent] = Field(min_length=1, max_length=40)
    steps: list[ConceptStep] = Field(min_length=1, max_length=60)
    software: ConceptSoftware
    open_questions: list[Text] = Field(max_length=40)
    supplies: list[ConceptSupply] = Field(default_factory=list, max_length=100)
    work_interfaces: list[WorkInterface] = Field(default_factory=list, max_length=40)

    @model_validator(mode='after')
    def coherent_links(self):
        interface_errors = interface_binding_issues(
            self.work_interfaces, self.components, self.steps)
        if interface_errors:
            raise ValueError('\n'.join(interface_errors))
        keys = [c.key for c in self.components]
        if len(set(keys)) != len(keys):
            raise ValueError('Component keys must be unique.')
        supply_keys = [s.key for s in self.supplies]
        if len(keys) + len(supply_keys) > 64:
            raise ValueError('Components and supplies together may contain at most 64 line items.')
        if len(set(keys + supply_keys)) != len(keys + supply_keys):
            raise ValueError('Supply and component keys must be distinct and unique.')
        link_issues = []
        for supply in self.supplies:
            unknown = [k for k in supply.component_keys if k not in keys]
            duplicated = sorted({k for k in supply.component_keys
                                 if supply.component_keys.count(k) > 1})
            if unknown or duplicated:
                link_issues.append(
                    f'Supply {supply.key!r} ({supply.name}) has invalid component_keys: '
                    f'unknown={unknown}, duplicate={duplicated}. '
                    'Link only modeled mounting components, not other supplies. '
                    f'Existing component keys: {keys[:16]}.')
        if link_issues:
            raise ValueError('\n'.join(link_issues[:8]))
        if sum(len(c.primitives) for c in self.components) > 800:
            raise ValueError('A proposal may contain at most 800 primitives.')
        parents = {c.key: c.parent_key for c in self.components}
        for component in self.components:
            seen, key = set(), component.key
            while key is not None:
                if key in seen or key not in parents:
                    raise ValueError('Parent links must form an acyclic forest '
                                     'of known components.')
                seen.add(key)
                key = parents[key]
        step_names = [step.name.casefold() for step in self.steps]
        if len(set(step_names)) != len(step_names):
            duplicate = next(name for name in step_names if step_names.count(name) > 1)
            raise ValueError(f'Step names must be unique ignoring case; duplicate {duplicate!r}. '
                             'Use distinct operation names for the controller action mapping.')
        for step in self.steps:
            if len(set(step.component_keys)) != len(step.component_keys):
                raise ValueError('Step components must be unique.')
            if any(k not in parents for k in step.component_keys):
                raise ValueError('Every step component must exist.')
            if step.moving_key is not None and step.moving_key not in step.component_keys:
                raise ValueError('The moving component must be listed in the step.')
        _rotation_steps(self.steps)
        return self


def _rotation_steps(steps):
    """Resolve explicit incremental rotary chains while keeping raw proposals unchanged."""
    result, stations = [], {}
    for index, raw in enumerate(steps):
        step = raw.model_dump(mode='json') if isinstance(raw, ConceptStep) else dict(raw)
        reference = step.get('rotation_reference', 'from_rest')
        group = (step['moving_key'], step['rotation_axis'],
                 tuple(step['pivot_mm']) if step['pivot_mm'] is not None else None)
        start = 0.
        if reference == 'previous_index':
            previous = result[-1] if result else None
            previous_group = ((previous['moving_key'], previous['rotation_axis'],
                              tuple(previous['pivot_mm']) if previous['pivot_mm'] is not None
                              else None) if previous else None)
            if (previous is None or group != previous_group or step['moving_key'] is None
                    or step['rotation_axis'] is None or step['pivot_mm'] is None
                    or any(abs(n) > EPSILON for n in step['translation_mm'])
                    or any(abs(n) > EPSILON for n in previous['translation_mm'])):
                raise ValueError(f'Step {index} ({step["name"]}) previous_index requires an '
                                 'immediately preceding rotary step with the same moving '
                                 'component, axis and pivot, and no translation.')
            start = previous['rotation_deg']
            previous['index_chain'] = True
        unwrapped = start + step['rotation_deg']
        wrapped = (unwrapped + 180) % 360 - 180
        if math.isclose(wrapped, -180, abs_tol=EPSILON) and unwrapped > 0:
            wrapped = 180.
        compiled = {**step, 'start_rotation_deg': start,
                    'rotation_delta_deg': step['rotation_deg'], 'rotation_deg': wrapped,
                    'index_chain': reference == 'previous_index'}
        station = step.get('index_station')
        if station is not None:
            for pose, label, name in stations.get(group, []):
                same_pose = abs((wrapped-pose+180) % 360 - 180) <= EPSILON
                if same_pose and label.casefold() != station.casefold():
                    raise ValueError(f'Indexed stations {label!r} ({name}) and {station!r} '
                                     f'({step["name"]}) resolve to the same {wrapped:g} degree '
                                     'pose. Specify actual distinct index travel or correct '
                                     'the station identity; display labels do not move samples.')
            stations.setdefault(group, []).append((wrapped, station, step['name']))
        result.append(compiled)
    return result


def _bounds(primitives):
    lows, highs = [], []
    for p in primitives:
        size = p.size_mm if isinstance(p, ConceptPrimitive) else p['size_mm']
        center = p.center_mm if isinstance(p, ConceptPrimitive) else p['center_mm']
        lows.append([c - s / 2 for c, s in zip(center, size)])
        highs.append([c + s / 2 for c, s in zip(center, size)])
    return ([min(v[i] for v in lows) for i in range(3)],
            [max(v[i] for v in highs) for i in range(3)])


def _add(first, second):
    return [a + b for a, b in zip(first, second)]


def _intersects(first, second):
    return all(min(first[1][i], second[1][i]) - max(first[0][i], second[0][i]) > EPSILON
               for i in range(3))


def _collision_detail(first, second, subject='the second part'):
    depths = [min(first[1][i], second[1][i]) - max(first[0][i], second[0][i])
              for i in range(3)]
    shifts, alternatives = [], []
    for i in range(3):
        positive, negative = first[1][i] - second[0][i], first[0][i] - second[1][i]
        shifts.append(positive if abs(positive) <= abs(negative) else negative)
        alternatives.append(f'{"XYZ"[i]} {negative:+g}/{positive:+g}')
    axis = min(range(3), key=lambda i: abs(shifts[i]))
    overlap = ', '.join(f'{"XYZ"[i]}={depths[i]:g}' for i in range(3))
    return (f'overlap depths mm [{overlap}]; nearest separating face requires '
            f'a {shifts[axis]:+g} mm offset on {"XYZ"[axis]} for {subject} '
            '(add appropriate clearance). Separating offset alternatives mm: '
            + ', '.join(alternatives) + '; check these against every other solid.')


def _motion_sweep(bounds, step, pivot, start_rotation_deg=0):
    """Conservative entire rotation/translation sweep, including angular extrema.

    A rotated solid stays inside its rotated original AABB. Taking exact extrema
    of every AABB corner and independently adding translational ranges also bounds
    simultaneous linear translation and rotation without sampling gaps.
    """
    low, high = bounds
    if not step.rotation_deg and not start_rotation_deg:
        return ([n + min(0, t) for n, t in zip(low, step.translation_mm)],
                [n + max(0, t) for n, t in zip(high, step.translation_mm)])
    axis = 'xyz'.index(step.rotation_axis)
    start_angle = math.radians(start_rotation_deg)
    end_angle = start_angle + math.radians(step.rotation_deg)
    start, end = min(start_angle, end_angle), max(start_angle, end_angle)
    values = [[], [], []]
    for x in (low[0], high[0]):
        for y in (low[1], high[1]):
            for z in (low[2], high[2]):
                q = [n - p for n, p in zip([x, y, z], pivot)]
                cross = ([0, -q[2], q[1]], [q[2], 0, -q[0]], [-q[1], q[0], 0])[axis]
                for i in range(3):
                    a, b, constant = (0, 0, q[i]) if i == axis else (q[i], cross[i], 0)
                    angles = [start, end]
                    extremum = math.atan2(b, a)
                    angles += [extremum + k * math.pi for k in range(-2, 3)
                               if start <= extremum + k * math.pi <= end]
                    values[i].extend(pivot[i] + constant + a * math.cos(theta)
                                     + b * math.sin(theta) for theta in angles)
    return ([min(v) + min(0, t) for v, t in zip(values, step.translation_mm)],
            [max(v) + max(0, t) for v, t in zip(values, step.translation_mm)])


def compile_concept(proposal: ConceptProposal | dict, workspace_width_mm=None,
                    *, _skip_work_interfaces=False) -> dict:
    """Compile immutable proposed geometry; pack assembly roots and reserve motion sweeps.

    Components are rigid primitive collections. Children use parent-relative origins.
    Each operating step describes a separate rigid motion from rest, not a cumulative
    trajectory. Translation and angular interpolation share progress. Primitive AABB
    interference checks are deliberately conservative.
    """
    proposal = ConceptProposal.model_validate(proposal)
    if workspace_width_mm is not None and (
            isinstance(workspace_width_mm, bool)
            or not isinstance(workspace_width_mm, (int, float))
            or not math.isfinite(workspace_width_mm) or not 1 <= workspace_width_mm <= 20000):
        raise ValueError('Workspace width must be a finite number from 1 to 20000 mm.')
    specs = {c.key: c for c in proposal.components}
    origins, roots = {}, {}

    def locate(key):
        if key not in origins:
            c = specs[key]
            if c.parent_key is None:
                origins[key], roots[key] = [0., 0., 0.], key
            else:
                origins[key] = _add(locate(c.parent_key), c.placement_mm)
                roots[key] = roots[c.parent_key]
        return origins[key]

    for key in specs:
        locate(key)
    descendants = {key: [other for other in specs if _descends(other, key, specs)]
                   for key in specs}
    rotation_steps = _rotation_steps(proposal.steps)
    visits = work = 0
    for step in proposal.steps:
        moving = descendants.get(step.moving_key, [])
        visits += sum(len(specs[k].primitives) for k in moving)
        for key in moving:
            fixed_count = sum(len(specs[k].primitives) for k in specs
                              if k not in moving and roots[k] == roots[key])
            work += len(specs[key].primitives) * fixed_count
    if visits > 6000 or work > 1000000:
        raise ValueError('Motion geometry exceeds the bounded validation budget; '
                         'simplify primitives or operating steps.')
    boxes = {key: [tuple(_add(b, origins[key]) for b in _bounds([p]))
                   for p in c.primitives] for key, c in specs.items()}
    issues = []
    for key, solids in boxes.items():
        for index, b in enumerate(solids):
            if b[0][1] < -EPSILON and len(issues) < 8:
                issues.append(f'Component {key!r} ({specs[key].name}) primitive {index} '
                              f'extends below the assembly base to Y={b[0][1]:g} mm. '
                              f'Raise its placement_mm Y by at least {-b[0][1]:g} mm.')
    for first, second in combinations(specs, 2):
        if roots[first] != roots[second]:
            continue
        conflict = next(((i, j, a, b) for i, a in enumerate(boxes[first])
                         for j, b in enumerate(boxes[second]) if _intersects(a, b)), None)
        if conflict is not None and len(issues) < 8:
            i, j, a, b = conflict
            target = second if specs[second].parent_key is not None else first
            fixed, translated = (a, b) if target == second else (b, a)
            issues.append(f'Attached component solids overlap: {first!r} ({specs[first].name}) '
                          f'primitive {i} and {second!r} ({specs[second].name}) primitive {j}; '
                          + _collision_detail(fixed, translated, repr(target))
                          + f' Revise {target!r} placement_mm or conflicting solid dimensions; '
                          'a filled envelope cannot stand in for a frame opening.')
    if issues:
        raise ValueError('\n'.join(issues))
    swept = {key: list(solids) for key, solids in boxes.items()}
    motion_issues = set()
    for step_index, step in enumerate(proposal.steps):
        moving = descendants.get(step.moving_key, [])
        pivot = _add(origins[step.moving_key], step.pivot_mm or [0, 0, 0]) if moving else None
        for key in moving:
            for primitive_index, (low, high) in enumerate(boxes[key]):
                sweep = _motion_sweep((low, high), step, pivot,
                                      rotation_steps[step_index]['start_rotation_deg'])
                if sweep[0][1] < -EPSILON and len(issues) < 8:
                    issues.append(f'Step {step_index} ({step.name}) moves {key!r} '
                                  f'({specs[key].name}) primitive {primitive_index} '
                                  f'below the assembly base: swept Y minimum {sweep[0][1]:g} mm. '
                                  'Raise its mounting position or correct its local pivot; '
                                  'preserve the intended operation.')
                swept[key].append(sweep)
                for other in specs:
                    if other in moving or roots[other] != roots[key]:
                        continue
                    hit = next(((j, fixed) for j, fixed in enumerate(boxes[other])
                                if _intersects(sweep, fixed)), None)
                    identity = (step_index, key, other)
                    if hit is not None and len(issues) < 8 and identity not in motion_issues:
                        motion_issues.add(identity)
                        j, fixed = hit
                        issues.append(
                            f'Step {step_index} ({step.name}) motion intersects fixed part: '
                            f'{key!r} ({specs[key].name}) primitive {primitive_index} swept '
                            f'from {sweep[0]} to {sweep[1]} mm intersects {other!r} '
                            f'({specs[other].name}) primitive {j}; '
                            + _collision_detail(sweep, fixed)
                            + f' Move the fixed {other!r}, add a genuine opening, or revise '
                            'the mounting arrangement while preserving intended travel. '
                            'This is a conservative swept-AABB check, not exact contact.')
    if issues:
        raise ValueError('\n'.join(issues))

    groups = {}
    for root in dict.fromkeys(roots.values()):
        solids = [b for key in specs if roots[key] == root for b in swept[key]]
        low = [min(b[0][i] for b in solids) for i in range(3)]
        high = [max(b[1][i] for b in solids) for i in range(3)]
        if any(b - a > 12000 for a, b in zip(low, high)):
            raise ValueError('Assembly including motion exceeds the 12000 mm concept limit.')
        groups[root] = {'low': low, 'high': high,
                        'width': high[0] - low[0] + 2 * GAP_MM,
                        'depth': high[2] - low[2] + 2 * GAP_MM}
    limit = workspace_width_mm or sum(g['width'] for g in groups.values())
    if any(g['width'] > limit + EPSILON for g in groups.values()):
        raise ValueError('Workspace width cannot fit an assembly '
                         'and its reserved motion clearance.')
    x = z = row_depth = width = 0.
    for group in groups.values():
        if x and x + group['width'] > limit + EPSILON:
            z += row_depth
            x = row_depth = 0.
        group['offset'] = [x + GAP_MM - group['low'][0], 0., z + GAP_MM - group['low'][2]]
        group['surface'] = [x, z, group['width'], group['depth']]
        x += group['width']
        width = max(width, x)
        row_depth = max(row_depth, group['depth'])
    names = {c.key: c.name for c in proposal.components}

    def readable(value):
        pattern = r'(?<![\w-])(' + '|'.join(re.escape(k) for k in
                                         sorted(names, key=len, reverse=True)) + r')(?![\w-])'
        return re.sub(pattern, lambda m: names[m.group()], value)

    sources, components, parts, supplies = concept_sources(), [], [], []
    for c in proposal.components:
        low, high = _bounds(c.primitives)
        source = sources.get(c.source_id)
        component = c.model_dump(mode='json')
        component.update(
            assembly=readable(c.assembly), check=readable(c.check), role=readable(c.role),
            position_mm=_add(origins[c.key], groups[roots[c.key]]['offset']),
            size_mm=[b - a for a, b in zip(low, high)],
            bounds_mm={'min': low, 'max': high}, assembly_root_key=roots[c.key],
            source=source, geometry_basis='custom_concept',
            functional_surface_mm=groups[roots[c.key]]['surface'],
            swept_bounds_mm={
                'min': _add([min(b[0][i] for b in swept[c.key]) for i in range(3)],
                            groups[roots[c.key]]['offset']),
                'max': _add([max(b[1][i] for b in swept[c.key]) for i in range(3)],
                            groups[roots[c.key]]['offset']),
            },
        )
        components.append(component)
        parts.append({'key': c.key, 'label': c.name, 'name': c.name, 'quantity': 1, 'unit': 'item',
                      'source_id': c.source_id, 'source_title': source['title'] if source else None,
                      'source_url': source['url'] if source else None, 'price_usd': None,
                      'basis': 'sourcing_candidate_only' if source else 'custom_concept',
                      'geometry_basis': 'custom_concept', 'assembly': readable(c.assembly)})
    # A procurement line for a device already mounted in the model must not
    # charge for that same unit twice. Explicit spares are additional purchases.
    matched_units = set()
    for supply in proposal.supplies:
        source = sources.get(supply.source_id)
        quantity = supply.quantity
        if (source and source.get('source_kind') == 'product' and
                not supply.additional_to_modeled_parts):
            for key in supply.component_keys:
                if key not in matched_units and specs[key].source_id == supply.source_id:
                    matched_units.add(key)
                    quantity -= 1
                    if not quantity:
                        break
        if not quantity:
            continue
        record = {**supply.model_dump(mode='json'), 'label': supply.name,
                  'quantity': quantity,
                  'role': readable(supply.role),
                  'component_names': [names[k] for k in supply.component_keys],
                  'source': source, 'source_title': source['title'] if source else None,
                  'source_url': source['url'] if source else None,
                  'catalog_search_url': None if source else
                      'https://www.adafruit.com/search?' + urlencode({'q': supply.name}),
                  'price_usd': None, 'geometry_basis': 'not_modeled_supply',
                  'basis': 'sourcing_candidate_only' if source else 'selection_required'}
        supplies.append(record)
        parts.append(record.copy())
    steps = []
    for step, rotation in zip(proposal.steps, rotation_steps):
        steps.append({**rotation, 'name': readable(step.name),
                      'instruction': readable(step.instruction),
                      'component_names': [names[k] for k in step.component_keys],
                      'moving_name': names.get(step.moving_key),
                      'moving_component_keys': descendants.get(step.moving_key, []),
                      'motion_basis': ('indexed_rotation_from_previous' if
                                       step.rotation_reference == 'previous_index' else
                                       'independent_rigid_motion_from_rest')})
    software = proposal.software.model_dump(mode='json')
    software = {k: [readable(v) for v in value] if isinstance(value, list) else readable(value)
                for k, value in software.items()}
    design = {
        'schema_version': '1', 'compiler_version': 'concept-1',
        'proposal': proposal.model_dump(mode='json'), 'workspace_width_mm': workspace_width_mm,
        'title': proposal.title, 'overview': readable(proposal.overview),
        'footprint_mm': [width, z + row_depth], 'components': components, 'parts': parts,
        'supplies': supplies,
        'work_interfaces': [{**interface.model_dump(mode='json'),
                             'label': readable(interface.label)}
                            for interface in proposal.work_interfaces],
        'bounds_mm': {
            'min': [min(c['swept_bounds_mm']['min'][i] for c in components) for i in range(3)],
            'max': [max(c['swept_bounds_mm']['max'][i] for c in components) for i in range(3)],
        },
        'steps': steps, 'software': software,
        'open_questions': [readable(v) for v in proposal.open_questions],
        'limits': [
            'Conceptual primitive solids in millimetres; no imported manufacturer CAD, '
            'fabrication tolerances, fasteners or validated structural design.',
            'Parent links are proposed rigid attachments. Assembly and mounting details '
            'remain unverified. Source links identify candidates, not geometry provenance.',
            'Independent rigid motions from rest are illustrative kinematics. '
            'Conservative solid bounding-box interference checks are not physical simulation '
            'or hardware control. Cables, loads, tools and human access are unverified.',
            'STL and OBJ preserve these solids; intersecting primitives within one component '
            'are separate shells, not a boolean-unioned or print-ready fabrication model.',
        ],
    }
    interface_errors = [] if _skip_work_interfaces else work_interface_issues(design)
    if interface_errors:
        raise ValueError('\n'.join(interface_errors))
    return design


def _descends(key, ancestor, specs):
    while key is not None:
        if key == ancestor:
            return True
        key = specs[key].parent_key
    return False


def assembly_review_issues(design: dict, *, max_issues=8, per_component=True) -> list[str]:
    """Flag apparent unsupported geometry for new proposals, never migrate saved files.

    This illustrative adjacency review uses axis-aligned primitive bounds and a
    documented 1 mm gap tolerance. At least two axes need positive face projection
    overlap. It does not establish load capacity, fastening, exact curved contact,
    mechanical support or safety. Separate roots on the bench are valid; a held or
    suspended payload still needs its proposed support/gripper represented.
    """
    if (isinstance(max_issues, bool) or not isinstance(max_issues, int)
            or not 1 <= max_issues <= 800):
        raise ValueError('Assembly review supports from 1 to 800 reported issues.')
    tolerance = 1.0
    nodes = []
    for component in design['components']:
        for index, primitive in enumerate(component['primitives']):
            low, high = _bounds([primitive])
            nodes.append({'component': component, 'index': index,
                          'low': _add(low, component['position_mm']),
                          'high': _add(high, component['position_mm'])})
    if len(nodes) > 800:
        raise ValueError('Assembly review supports at most 800 conceptual primitives.')
    links = [set() for _ in nodes]

    def gap(a, b):
        return [max(b['low'][i] - a['high'][i], a['low'][i] - b['high'][i], 0)
                for i in range(3)]

    def direction_text(a, b):
        directions = []
        for axis, distance in enumerate(gap(a, b)):
            if distance > EPSILON:
                sign = '+' if b['low'][axis] > a['high'][axis] else '-'
                directions.append(f'{sign}{"XYZ"[axis]} gap {distance:g} mm')
        return ', '.join(directions) or 'edge/point adjacency without a supporting face'

    for i, a in enumerate(nodes):
        for j in range(i + 1, len(nodes)):
            b = nodes[j]
            if a['component']['assembly_root_key'] != b['component']['assembly_root_key']:
                continue
            positive_axes = sum(min(a['high'][axis], b['high'][axis]) -
                                max(a['low'][axis], b['low'][axis]) > EPSILON for axis in range(3))
            if positive_axes >= 2 and sum(v*v for v in gap(a, b)) <= tolerance*tolerance:
                links[i].add(j)
                links[j].add(i)
    grounded = {i for i, node in enumerate(nodes) if node['low'][1] <= tolerance}
    pending = list(grounded)
    while pending:
        for adjacent in links[pending.pop()] - grounded:
            grounded.add(adjacent)
            pending.append(adjacent)
    issues, reported = [], set()
    for i, node in enumerate(nodes):
        component = node['component']
        if i in grounded or (per_component and component['key'] in reported):
            continue
        candidates = [j for j in grounded
                      if nodes[j]['component']['assembly_root_key'] ==
                      component['assembly_root_key']]
        if not candidates:
            continue
        nearest = min(candidates, key=lambda j: sum(v*v for v in gap(node, nodes[j])))
        fixed = nodes[nearest]
        direction = direction_text(node, fixed)
        parent_note = ''
        parent_solids = [n for n in nodes if n['component']['key'] == component['parent_key']]
        if parent_solids:
            parent = min(parent_solids, key=lambda n: sum(v*v for v in gap(node, n)))
            parent_note = (f' Declared parent {parent["component"]["key"]!r} '
                           f'({parent["component"]["name"]}) primitive {parent["index"]}: '
                           f'{direction_text(node, parent)}.')
        issues.append(
            f'Apparent isolated above-base geometry: {component["key"]!r} '
            f'({component["name"]}) primitive {node["index"]}; nearest bench-connected '
            f'solid is {fixed["component"]["key"]!r} ({fixed["component"]["name"]}) '
            f'primitive {fixed["index"]}: {direction}.{parent_note} '
            'Author a bridge, mount, rail or '
            'represented gripper joining the intended support path. Parent links and prose '
            'alone do not create material. This 1 mm illustrative AABB adjacency review '
            'does not certify support or fastening.')
        reported.add(component['key'])
        if len(issues) == max_issues:
            break
    return issues


def _primitive_mesh(p):
    """Return closed, outward-wound triangle shells using the viewer's Y-up dimensions."""
    w, h, d = p['size_mm']
    center = p['center_mm']
    if p['shape'] == 'box':
        vertices = [[x * w / 2, y * h / 2, z * d / 2]
                    for x, y, z in [(-1,-1,-1), (1,-1,-1), (1,1,-1), (-1,1,-1),
                                    (-1,-1,1), (1,-1,1), (1,1,1), (-1,1,1)]]
        faces = [(0,2,1), (0,3,2), (4,5,6), (4,6,7), (0,1,5), (0,5,4),
                 (3,7,6), (3,6,2), (0,4,7), (0,7,3), (1,2,6), (1,6,5)]
    elif p['shape'] == 'cylinder':
        segments = 32
        vertices = [[w / 2 * math.cos(i * 2 * math.pi / segments), y,
                     d / 2 * math.sin(i * 2 * math.pi / segments)]
                    for y in (-h / 2, h / 2) for i in range(segments)]
        vertices += [[0, -h / 2, 0], [0, h / 2, 0]]
        faces = []
        for i in range(segments):
            j = (i + 1) % segments
            faces += [(i, i + segments, j + segments), (i, j + segments, j),
                      (2 * segments, i, j), (2 * segments + 1, j + segments, i + segments)]
    else:
        segments, rings, radius = 32, 16, w / 2
        vertices = [[0, radius, 0]]
        vertices += [[radius * math.sin(j * math.pi / rings) * math.cos(i * 2 * math.pi / segments),
                      radius * math.cos(j * math.pi / rings),
                      radius * math.sin(j * math.pi / rings) * math.sin(i * 2 * math.pi / segments)]
                     for j in range(1, rings) for i in range(segments)]
        vertices.append([0, -radius, 0])
        faces = []
        for i in range(segments):
            j = (i + 1) % segments
            faces.append((0, 1 + j, 1 + i))
            for ring in range(rings - 2):
                a, b = 1 + ring * segments + i, 1 + ring * segments + j
                faces += [(a, b, b + segments), (a, b + segments, a + segments)]
            a, b = 1 + (rings - 2) * segments + i, 1 + (rings - 2) * segments + j
            faces.append((len(vertices) - 1, a, b))
    return [_add(v, center) for v in vertices], faces


def _mesh_parts(design, component_key):
    canonical = compile_concept(design['proposal'], design.get('workspace_width_mm'))
    components = canonical['components']
    if component_key is not None:
        components = [c for c in components if c['key'] == component_key]
        if not components:
            raise ValueError('Unknown component model key.')
    for c in components:
        for index, primitive in enumerate(c['primitives']):
            vertices, faces = _primitive_mesh(primitive)
            if component_key is None:
                vertices = [_add(v, c['position_mm']) for v in vertices]
            yield f'{c["key"]}_{index + 1}', vertices, faces


def concept_obj(design: dict, component_key: str | None = None) -> bytes:
    """Export static complete geometry or one local component, coordinates in mm."""
    lines = ['# MuseAutoLab conceptual geometry; units: mm; Y up; separate solid shells']
    offset = 1
    for name, vertices, faces in _mesh_parts(design, component_key):
        lines.append(f'o {name}')
        lines.extend('v ' + ' '.join(f'{n:.9g}' for n in v) for v in vertices)
        lines.extend('f ' + ' '.join(str(i + offset) for i in face) for face in faces)
        offset += len(vertices)
    return ('\n'.join(lines) + '\n').encode('utf-8')


def concept_stl(design: dict, component_key: str | None = None) -> bytes:
    """Export binary STL in mm (STL has no standard embedded unit metadata)."""
    triangles = []
    for _, vertices, faces in _mesh_parts(design, component_key):
        for face in faces:
            a, b, c = [vertices[i] for i in face]
            u, v = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
            n = [u[1]*v[2] - u[2]*v[1], u[2]*v[0] - u[0]*v[2], u[0]*v[1] - u[1]*v[0]]
            norm = math.sqrt(sum(t * t for t in n))
            n = [t / norm for t in n]
            triangles.append(struct.pack('<12fH', *n, *a, *b, *c, 0))
    header = b'MuseAutoLab concept; units mm; Y up; not fabrication validated'.ljust(80, b' ')
    return header + struct.pack('<I', len(triangles)) + b''.join(triangles)
