"""Independent proposal compilation, assembly fit, motion and mesh contracts."""

import math
import struct
from collections import Counter
from copy import deepcopy
from itertools import combinations

import pytest
from pydantic import ValidationError

from app.concept_design import (
    ConceptProposal,
    assembly_review_issues,
    compile_concept,
    concept_obj,
    concept_sources,
    concept_stl,
)
from app.design_sources import reference_library
from app.supplier_catalogs import PRODUCTS


def proposal():
    return {
        'title': 'Optical sample carousel', 'overview': 'Rotate samples for optical review.',
        'components': [
            {'key': 'turntable', 'name': 'Sample turntable', 'role': 'Support sample positions.',
             'primitives': [{'shape': 'cylinder', 'size_mm': [120, 20, 120],
                             'center_mm': [0, 10, 0], 'finish': 'steel'}],
             'source_id': None, 'assembly': 'Level turntable before fitting optics.',
             'check': 'Confirm turntable is stable.'},
            {'key': 'optic_head', 'name': 'Optical head', 'role': 'Inspect an illuminated sample.',
             'primitives': [{'shape': 'sphere', 'size_mm': [40, 40, 40],
                             'center_mm': [-5, 20, 10], 'finish': 'clear'}],
             'source_id': 'rpi-camera-module-3', 'assembly': 'Position optic_head.',
             'check': 'Check optic_head focus.'},
        ],
        'steps': [{'name': 'Review an item', 'instruction': 'Move optic_head beside turntable.',
                   'component_keys': ['turntable', 'optic_head'], 'moving_key': 'optic_head',
                   'translation_mm': [0, 30, -50]}],
        'software': {'controller': 'Host controller to be selected.',
                     'interfaces': ['Camera interface must be selected.'],
                     'setup': ['Calibrate optic_head against a representative sample.'],
                     'checks': ['Confirm image review and stop behavior.']},
        'open_questions': ['What sample size and image resolution are required?'],
    }


def test_open_proposal_is_not_a_station_template_and_preserves_inputs():
    original = proposal()
    snapshot = deepcopy(original)
    design = compile_concept(original, 200)
    assert original == snapshot
    assert design == compile_concept(original, 200)
    assert design['proposal'] == ConceptProposal.model_validate(original).model_dump(mode='json')
    assert [c['key'] for c in design['components']] == ['turntable', 'optic_head']
    assert [c['primitives'][0]['shape'] for c in design['components']] == ['cylinder', 'sphere']
    assert all(p['quantity'] == 1 and p['unit'] == 'item' for p in design['parts'])
    assert design['components'][1]['source']['title'].startswith('Raspberry')
    assert all(p['price_usd'] is None for p in design['parts'])
    assert design['steps'][0]['component_names'] == ['Sample turntable', 'Optical head']
    assert 'optic_head' not in design['steps'][0]['instruction']
    assert 'turntable' not in design['components'][0]['assembly'].replace('Sample turntable', '')
    assert 'optic_head' not in design['software']['setup'][0]


def test_explicit_primitive_color_is_preserved_without_changing_geometry():
    original = proposal()
    before = compile_concept(original, 200)
    original['components'][0]['primitives'][0]['color'] = '#19aBcD'
    after = compile_concept(original, 200)
    assert after['components'][0]['primitives'][0]['color'] == '#19aBcD'
    assert after['proposal']['components'][0]['primitives'][0]['color'] == '#19aBcD'
    assert [c['position_mm'] for c in after['components']] == [
        c['position_mm'] for c in before['components']]
    assert after['components'][1]['primitives'][0]['color'] is None


@pytest.mark.parametrize('color', ['red', '#123', '#gggggg', '#00000000', '', 7, True])
def test_invalid_primitive_colors_are_rejected(color):
    original = proposal()
    original['components'][0]['primitives'][0]['color'] = color
    with pytest.raises(ValidationError):
        compile_concept(original, 200)


def test_reserves_motion_and_negative_local_coordinates_without_clipping():
    design = compile_concept(proposal(), 200)
    width, depth = design['footprint_mm']
    assert width <= 200
    surfaces = {tuple(c['functional_surface_mm']) for c in design['components']}
    for a, b in combinations(surfaces, 2):
        assert a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or (
            a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1])
    for component in design['components']:
        offsets = [[0, 0, 0]]
        offsets += [s['translation_mm'] for s in design['steps']
                    if component['key'] in s['moving_component_keys']]
        for offset in offsets:
            for primitive in component['primitives']:
                center = [a + b + c for a, b, c in zip(
                    primitive['center_mm'], component['position_mm'], offset)]
                assert center[0] - primitive['size_mm'][0] / 2 >= 20 - 1e-6
                assert center[0] + primitive['size_mm'][0] / 2 <= width - 20 + 1e-6
                assert center[2] - primitive['size_mm'][2] / 2 >= 20 - 1e-6
                assert center[2] + primitive['size_mm'][2] / 2 <= depth - 20 + 1e-6


@pytest.mark.parametrize('value', [False, True, '200', 0, -1, math.nan, math.inf, 20001, 159])
def test_invalid_or_too_narrow_width(value):
    with pytest.raises(ValueError):
        compile_concept(proposal(), value)


@pytest.mark.parametrize('edit', [
    lambda p: p.update(components=[]),
    lambda p: p.update(surprise=True),
    lambda p: p['components'][1].update(key='turntable'),
    lambda p: p['components'][1].update(source_id='invented-vendor'),
    lambda p: p['components'][1].update(parent_key='unknown', placement_mm=[0, 0, 0]),
    lambda p: p['components'][1].update(parent_key='optic_head', placement_mm=[0, 0, 0]),
    lambda p: p['components'][1].update(parent_key='turntable'),
    lambda p: p['components'][1].update(placement_mm=[0, 0, 0]),
    lambda p: p['components'][0]['primitives'][0].update(size_mm=[120, 20, 100]),
    lambda p: p['components'][1]['primitives'][0].update(size_mm=[40, 30, 40]),
    lambda p: p['components'][1]['primitives'][0].update(size_mm=[0, 0, 0]),
    lambda p: p['components'][1]['primitives'][0].update(center_mm=[0, math.nan, 0]),
    lambda p: p['components'][1]['primitives'][0].update(center_mm=[0, True, 0]),
    lambda p: p['components'][1]['primitives'][0].update(center_mm=[0, 5, 0]),
    lambda p: p['steps'][0].update(component_keys=['missing']),
    lambda p: p['steps'][0].update(component_keys=['turntable', 'turntable']),
    lambda p: p['steps'][0].update(moving_key='missing'),
    lambda p: p['steps'][0].update(moving_key=None),
    lambda p: p['steps'][0].update(translation_mm=[0, 2001, 0]),
    lambda p: p['software'].update(controller='   '),
])
def test_malformed_proposals_rejected(edit):
    value = proposal()
    edit(value)
    with pytest.raises(ValidationError):
        compile_concept(value)


def integrated_proposal():
    p = proposal()
    p['components'][0]['primitives'] = [
        {'shape': 'box', 'size_mm': [160, 10, 160], 'center_mm': [0, 5, 0], 'finish': 'frame'},
        {'shape': 'box', 'size_mm': [10, 150, 10], 'center_mm': [-75, 85, -75],
         'finish': 'frame'},
    ]
    p['components'][1].update(parent_key='turntable', placement_mm=[0, 30, 0])
    p['steps'][0]['translation_mm'] = [20, 10, 0]
    return p


def test_integrated_frame_can_enclose_a_child_without_solid_overlap():
    p = integrated_proposal()
    design = compile_concept(p)
    parent, child = design['components']
    assert child['position_mm'][1] == 30
    assert child['position_mm'][0] == parent['position_mm'][0]
    assert child['assembly_root_key'] == parent['key']
    assert child['functional_surface_mm'] == parent['functional_surface_mm']
    p['steps'][0]['moving_key'] = 'turntable'
    design = compile_concept(p)
    assert design['steps'][0]['moving_component_keys'] == ['turntable', 'optic_head']


def test_collision_and_swept_collision_are_rejected_for_attached_parts():
    p = integrated_proposal()
    p['components'][1]['placement_mm'] = [0, 0, 0]
    with pytest.raises(ValueError, match='overlap'):
        compile_concept(p)
    p['components'][1]['placement_mm'] = [0, 30, 0]
    p['steps'][0]['translation_mm'] = [0, -30, 0]
    with pytest.raises(ValueError, match='intersects'):
        compile_concept(p)
    p['steps'][0]['translation_mm'] = [0, -100, 0]
    with pytest.raises(ValueError, match='below'):
        compile_concept(p)


def test_distinct_workflow_and_shape_produce_distinct_geometry_and_parts():
    first = compile_concept(proposal())
    p = proposal()
    p['title'] = 'Heating block for enzyme tubes'
    p['components'] = [p['components'][0]]
    p['components'][0].update(key='heater', name='Temperature block', source_id=None)
    p['components'][0]['primitives'] = [
        {'shape': 'box', 'size_mm': [80, 40, 90], 'center_mm': [0, 20, 0], 'finish': 'steel'}]
    p['steps'] = [{'name': 'Hold a batch', 'instruction': 'Inspect the temperature block.',
                   'component_keys': ['heater'], 'moving_key': None, 'translation_mm': [0, 0, 0]}]
    second = compile_concept(p)
    assert first['footprint_mm'] != second['footprint_mm']
    assert first['parts'] != second['parts']
    assert concept_obj(first) != concept_obj(second)
    assert second['title'] == p['title']


def stl_triangles(content):
    count, = struct.unpack_from('<I', content, 80)
    assert len(content) == 84 + count * 50
    for index in range(count):
        values = struct.unpack_from('<12fH', content, 84 + index * 50)
        yield values[:3], [values[3:6], values[6:9], values[9:12]]


@pytest.mark.parametrize('shape,size', [('box', [36, 20, 28]),
                                      ('cylinder', [32, 20, 32]), ('sphere', [32, 32, 32])])
def test_meshes_are_closed_outward_and_preserve_mm_dimensions(shape, size):
    p = proposal()
    p['components'] = [p['components'][0]]
    p['components'][0]['primitives'] = [
        {'shape': shape, 'size_mm': size, 'center_mm': [0, size[1]/2, 0], 'finish': 'polymer'}]
    p['steps'][0].update(component_keys=['turntable'], moving_key=None, translation_mm=[0, 0, 0])
    design = compile_concept(p)
    content = concept_stl(design, 'turntable')
    edges, all_points, volume = Counter(), [], 0
    for normal, points in stl_triangles(content):
        assert math.isclose(sum(n*n for n in normal), 1, abs_tol=1e-5)
        all_points.extend(points)
        a, b, c = points
        volume += (a[0]*(b[1]*c[2]-b[2]*c[1]) +
                   a[1]*(b[2]*c[0]-b[0]*c[2]) + a[2]*(b[0]*c[1]-b[1]*c[0]))/6
        for first, second in zip(points, points[1:] + points[:1]):
            edges[tuple(sorted((first, second)))] += 1
    assert set(edges.values()) == {2}
    assert volume > 0
    assert min(v[1] for v in all_points) == pytest.approx(0)
    for axis in range(3):
        assert max(v[axis] for v in all_points) - min(v[axis] for v in all_points) == (
            pytest.approx(size[axis]))
    assert content == concept_stl(design, 'turntable')
    assert b'units: mm' in concept_obj(design)


def test_export_rebuilds_canonical_geometry_and_rejects_unknown_component():
    design = compile_concept(proposal())
    original = concept_obj(design)
    design['components'][0]['position_mm'] = [999999, 0, 0]
    assert concept_obj(design) == original
    with pytest.raises(ValueError):
        concept_stl(design, 'unknown')
    assert 'pololu-1209' in concept_sources()
    assert all(v['url'].startswith('https://') for v in concept_sources().values())


def test_supply_bom_keeps_quantities_source_and_component_links_without_geometry():
    p = proposal()
    p['supplies'] = [{'key': 'mount_screw', 'name': 'Mounting screws', 'quantity': 8,
                      'unit': 'screw', 'role': 'Attach optic_head after selecting its mount.',
                      'source_id': None, 'component_keys': ['optic_head']}]
    design = compile_concept(p)
    assert len(design['components']) == 2
    assert len(design['parts']) == 3
    assert design['supplies'][0]['quantity'] == 8
    assert design['supplies'][0]['component_names'] == ['Optical head']
    assert design['supplies'][0]['geometry_basis'] == 'not_modeled_supply'
    assert 'optic_head' not in design['supplies'][0]['role']
    assert concept_obj(design) == concept_obj(compile_concept(proposal()))


@pytest.mark.parametrize('change', [
    {'quantity': 0}, {'quantity': 100001}, {'quantity': True}, {'quantity': 1.5},
    {'key': 'turntable'}, {'component_keys': ['unknown']},
    {'component_keys': ['turntable', 'turntable']}, {'source_id': 'imaginary-catalogue'},
])
def test_invalid_supply_bom_is_rejected(change):
    p = proposal()
    p['supplies'] = [{'key': 'cable', 'name': 'Camera cable', 'quantity': 1, 'unit': 'item',
                      'role': 'Connect the camera.', 'source_id': None,
                      'component_keys': ['optic_head'], **change}]
    with pytest.raises(ValidationError):
        compile_concept(p)


def test_rotational_sweep_reserves_between_endpoint_extrema_and_descendants():
    p = integrated_proposal()
    p['steps'][0].update(moving_key='turntable', translation_mm=[0, 0, 0],
                         rotation_deg=180, rotation_axis='y', pivot_mm=[0, 0, 0])
    design = compile_concept(p)
    # The 160 mm square reaches a larger AABB at 45 degrees than at either endpoint.
    assert design['footprint_mm'][0] == pytest.approx(160 * math.sqrt(2) + 40)
    assert design['footprint_mm'][1] == pytest.approx(160 * math.sqrt(2) + 40)
    assert design['steps'][0]['moving_component_keys'] == ['turntable', 'optic_head']
    assert design['bounds_mm']['max'][1] == 160
    p['steps'][0]['rotation_deg'] = -180
    negative = compile_concept(p)
    assert negative['footprint_mm'] == pytest.approx(design['footprint_mm'])


def test_rotational_sweep_finds_collision_between_clear_endpoints():
    p = integrated_proposal()
    p['components'][0]['primitives'] = [
        {'shape': 'box', 'size_mm': [5, 60, 5], 'center_mm': [0, 30, 50], 'finish': 'frame'}]
    p['components'][1].update(placement_mm=[50, 10, 0])
    p['components'][1]['primitives'] = [
        {'shape': 'box', 'size_mm': [10, 10, 10], 'center_mm': [0, 5, 0], 'finish': 'accent'}]
    p['steps'][0].update(translation_mm=[0, 0, 0], rotation_deg=-180,
                         rotation_axis='y', pivot_mm=[-50, 0, 0])
    with pytest.raises(ValueError, match='intersects'):
        compile_concept(p)


@pytest.mark.parametrize('change', [
    {'rotation_deg': 181}, {'rotation_deg': math.inf}, {'rotation_deg': True},
    {'rotation_deg': 90}, {'rotation_axis': 'y'}, {'pivot_mm': [0, 0, 0]},
    {'rotation_deg': 90, 'rotation_axis': 'q', 'pivot_mm': [0, 0, 0]},
    {'rotation_deg': 90, 'rotation_axis': 'y', 'pivot_mm': [0, math.nan, 0]},
    {'moving_key': None, 'translation_mm': [0, 0, 0], 'rotation_deg': 45,
     'rotation_axis': 'y', 'pivot_mm': [0, 0, 0]},
])
def test_invalid_rotational_steps_rejected(change):
    p = proposal()
    p['steps'][0].update(change)
    with pytest.raises(ValidationError):
        compile_concept(p)


def test_rotation_about_horizontal_axis_below_base_is_rejected():
    p = proposal()
    p['steps'][0].update(translation_mm=[0, 0, 0], rotation_deg=180,
                         rotation_axis='x', pivot_mm=[0, 0, 0])
    with pytest.raises(ValueError, match='below'):
        compile_concept(p)


def test_mutated_model_is_revalidated():
    model = ConceptProposal.model_validate(proposal())
    model.components[0].primitives[0].size_mm[0] = math.inf
    with pytest.raises(ValidationError):
        compile_concept(model)


def test_total_price_line_budget_and_motion_complexity_are_bounded():
    p = proposal()
    p['supplies'] = [{'key': f'supply_{index}', 'name': 'Mounting supply', 'quantity': 1,
                      'unit': 'item', 'role': 'Select mounting supplies.', 'source_id': None,
                      'component_keys': ['turntable']} for index in range(63)]
    with pytest.raises(ValueError, match='64 line'):
        compile_concept(p)
    p = integrated_proposal()
    p['components'][0]['primitives'] *= 64 // 2
    p['components'][1]['primitives'] *= 64
    p['steps'][0]['moving_key'] = 'turntable'
    p['steps'] = [{**deepcopy(p['steps'][0]), 'name': f'Move {i}'} for i in range(60)]
    with pytest.raises(ValueError, match='validation budget'):
        compile_concept(p)


def test_full_reviewed_catalogue_coverage_preserves_historical_sources_and_scope():
    sources = concept_sources()
    assert set(PRODUCTS) <= sources.keys()
    for key, product in PRODUCTS.items():
        source = sources[key]
        assert source['source_kind'] == 'product'
        assert source['catalog_product_id'] == key
        assert source['purchase_url'] == product.url
        assert source['supplier'] == product.supplier
        assert source['sku'] == product.sku
        assert source['geometry_basis'] == 'custom_concept_not_vendor_cad'
        assert source['title'] != key
    for historical in reference_library()['references']:
        assert sources[historical['id']]['title'] == historical['title']
        assert sources[historical['id']]['url'] == historical['url']
    assert sources['jubilee-hardware']['source_kind'] == 'open_source_project'
    assert 'not a purchasable' in sources['jubilee-hardware']['purchase_scope']
    assert sources['pico-h']['title'].startswith('Raspberry Pi Pico')
    assert sources['jubilee-hardware-kit']['variant_title'] == 'Full Set'
    sources['pico']['title'] = 'Tampered title'
    assert concept_sources()['pico']['title'] != 'Tampered title'


@pytest.mark.parametrize('key', list(PRODUCTS))
def test_every_registered_product_can_be_a_component_and_supply_candidate(key):
    p = proposal()
    p['components'][1]['source_id'] = key
    p['supplies'] = [{'key': 'candidate_supply', 'name': 'Candidate accessory', 'quantity': 2,
                      'unit': 'item', 'role': 'Select an appropriate accessory.',
                      'source_id': key, 'component_keys': ['optic_head'],
                      'additional_to_modeled_parts': True}]
    design = compile_concept(p)
    assert design['components'][1]['source']['catalog_product_id'] == key
    assert design['supplies'][0]['source']['catalog_product_id'] == key
    assert design['parts'][-1]['quantity'] == 2


@pytest.mark.parametrize('axis', ['x', 'y', 'z'])
@pytest.mark.parametrize('angle', [-137, 83])
def test_rigid_motion_bounds_contain_dense_independent_corner_samples(axis, angle):
    p = proposal()
    p['components'] = [p['components'][0]]
    p['steps'][0].update(component_keys=['turntable'], moving_key='turntable',
                         translation_mm=[100, 150, -35], rotation_deg=angle,
                         rotation_axis=axis, pivot_mm=[0, -100, 0] if axis == 'y'
                         else [0, 100, 0])
    # Raising the component via a root frame allows a horizontal angular sweep.
    moving = deepcopy(p['components'][0])
    moving.update(key='moving_disc', parent_key='turntable', placement_mm=[0, 300, 0])
    p['components'][0]['primitives'] = [
        {'shape': 'box', 'size_mm': [10, 5, 10], 'center_mm': [0, 2.5, 0], 'finish': 'frame'}]
    p['components'].append(moving)
    p['steps'][0].update(component_keys=['moving_disc'], moving_key='moving_disc',
                         pivot_mm=[0, 0, 0])
    design = compile_concept(p)
    component = design['components'][1]
    low, high = component['bounds_mm']['min'], component['bounds_mm']['max']
    axis_index = 'xyz'.index(axis)
    sweep = component['swept_bounds_mm']
    for fraction in [i / 200 for i in range(201)]:
        theta = math.radians(angle) * fraction
        for x in (low[0], high[0]):
            for y in (low[1], high[1]):
                for z in (low[2], high[2]):
                    q = [x, y, z]
                    cross = ([0, -z, y], [z, 0, -x], [-y, x, 0])[axis_index]
                    rotated = [q[i] if i == axis_index else
                               q[i]*math.cos(theta) + cross[i]*math.sin(theta)
                               for i in range(3)]
                    world = [rotated[i] + component['position_mm'][i]
                             + p['steps'][0]['translation_mm'][i]*fraction for i in range(3)]
                    for i in range(3):
                        assert sweep['min'][i] - 1e-6 <= world[i] <= sweep['max'][i] + 1e-6


def test_precise_geometry_diagnostic_identifies_parts_axes_and_signed_resolution():
    p = integrated_proposal()
    p['components'][1]['placement_mm'] = [0, 0, 0]
    with pytest.raises(ValueError) as problem:
        compile_concept(p)
    message = str(problem.value)
    assert "'turntable' (Sample turntable) primitive 0" in message
    assert "'optic_head' (Optical head) primitive 0" in message
    assert 'X=40' in message and 'Y=10' in message and 'Z=40' in message
    assert '+10 mm offset on Y' in message
    assert 'placement_mm' in message


def test_motion_diagnostic_names_step_mover_and_fixed_component():
    p = integrated_proposal()
    p['steps'][0]['translation_mm'] = [0, -30, 0]
    with pytest.raises(ValueError) as problem:
        compile_concept(p)
    message = str(problem.value)
    assert 'Step 0 (Review an item)' in message
    assert "'optic_head' (Optical head) primitive 0 swept" in message
    assert "'turntable' (Sample turntable) primitive 0" in message
    assert 'preserving intended travel' in message


def test_supply_link_diagnostic_distinguishes_unmodeled_supply_from_part():
    p = proposal()
    p['supplies'] = [{'key': 'cable_set', 'name': 'Cable set', 'quantity': 1, 'unit': 'set',
                      'role': 'Connect proposed electronics.', 'source_id': None,
                      'component_keys': ['controller_board']}]
    with pytest.raises(ValueError) as problem:
        compile_concept(p)
    message = str(problem.value)
    assert "Supply 'cable_set' (Cable set)" in message
    assert "unknown=['controller_board']" in message
    assert 'not other supplies' in message
    assert 'turntable' in message


def test_step_names_are_unique_case_insensitively_for_gateway_identity():
    p = proposal()
    p['steps'].append({**p['steps'][0], 'name': p['steps'][0]['name'].upper()})
    with pytest.raises(ValueError, match='unique ignoring case'):
        compile_concept(p)


def test_floating_optical_head_is_reviewed_without_breaking_legacy_compilation():
    design = compile_concept(integrated_proposal())
    issues = assembly_review_issues(design)
    assert len(issues) == 1
    assert "'optic_head' (Optical head) primitive 0" in issues[0]
    assert 'gap 20 mm' in issues[0]
    assert 'bridge, mount, rail' in issues[0]
    # Merely naming a parent does not add a structural member.
    assert design['components'][1]['parent_key'] == 'turntable'


def test_review_accepts_material_bridge_and_independent_bench_resting_modules():
    p = integrated_proposal()
    p['components'][1]['placement_mm'] = [0, 10, 0]
    assert assembly_review_issues(compile_concept(p)) == []
    p = proposal()
    assert assembly_review_issues(compile_concept(p)) == []


@pytest.mark.parametrize('gap,expected', [(0, False), (0.9, False), (1, False), (1.1, True)])
def test_review_tolerance_is_documented_and_bounded(gap, expected):
    p = integrated_proposal()
    p['components'][1]['placement_mm'] = [0, 10 + gap, 0]
    assert bool(assembly_review_issues(compile_concept(p))) is expected


def test_review_finds_disconnected_feature_inside_one_component():
    p = proposal()
    p['components'] = p['components'][:1]
    p['components'][0]['primitives'].append({
        'shape': 'box', 'size_mm': [10, 10, 10], 'center_mm': [0, 200, 0], 'finish': 'steel'})
    p['steps'][0].update(component_keys=['turntable'], moving_key=None, translation_mm=[0, 0, 0])
    issues = assembly_review_issues(compile_concept(p))
    assert len(issues) == 1
    assert 'primitive 1' in issues[0] and '-Y gap 175 mm' in issues[0]


def test_checkpoints_retain_same_motion_bounds_and_compiled_fractions():
    p = proposal()
    before = compile_concept(p)
    p['steps'][0]['stops'] = [0, 0.25, 0.5, 1]
    after = compile_concept(p)
    assert after['steps'][0]['stops'] == [0, 0.25, 0.5, 1]
    assert before['bounds_mm'] == after['bounds_mm']
    assert before['footprint_mm'] == after['footprint_mm']


@pytest.mark.parametrize('stops', [[-0.1], [1.1], [True], [math.nan], ['0.5'],
                                  [0.5, 0.5], [0.8, 0.4], list(range(13))])
def test_invalid_checkpoint_fractions_rejected(stops):
    p = proposal()
    p['steps'][0]['stops'] = stops
    with pytest.raises(ValueError):
        compile_concept(p)
