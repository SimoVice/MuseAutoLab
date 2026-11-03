"""Exact proposed working axes and rigid poses, independent of optical performance."""

import math
from copy import deepcopy

import pytest

from app.concept_design import ConceptProposal, compile_concept
from app.concept_interfaces import WorkInterface, work_interface_issues


def component(key, shape, size, parent=None, placement=None):
    return {'key': key, 'name': key.replace('_', ' ').title(), 'role': 'Proposed test component.',
            'parent_key': parent, 'placement_mm': placement, 'source_id': None,
            'primitives': [{'shape': shape, 'size_mm': size, 'center_mm': [0, size[1]/2, 0],
                            'finish': 'polymer'}],
            'assembly': 'Propose the attachment and check it before commissioning.',
            'check': 'Verify dimensions and intended use physically.'}


def fixture():
    return {
        'title': 'Indexed card reader', 'overview': 'Proposed viewing axis over an indexed card.',
        'components': [component('base', 'box', [120, 10, 120]),
                       component('rotor', 'cylinder', [100, 5, 100], 'base', [0, 10, 0]),
                       component('card', 'box', [10, 2, 10], 'rotor', [30, 5, 0]),
                       component('camera', 'box', [10, 10, 10], 'base', [0, 100, -30])],
        'steps': [{'name': 'Index card', 'instruction': 'Rotate the card into the viewing pose.',
                   'component_keys': ['rotor', 'card'], 'moving_key': 'rotor',
                   'translation_mm': [0, 0, 0], 'rotation_deg': 90, 'rotation_axis': 'y',
                   'pivot_mm': [0, 0, 0]}],
        'software': {'controller': 'Unconnected offline controller.', 'interfaces': [],
                     'setup': ['Verify the index poses.'], 'checks': ['Check stop response.']},
        'open_questions': [],
        'work_interfaces': [{'key': 'card_view', 'label': 'View the indexed card',
                             'tool_key': 'camera', 'tool_primitive': 0,
                             'target_key': 'card', 'target_primitive': 0, 'axis': [0, -1, 0],
                             'step_name': 'Index card', 'phase': 1,
                             'min_distance_mm': 80, 'max_distance_mm': 95}],
    }


def test_rotated_actual_card_alignment_preserves_inputs():
    raw = fixture()
    before = deepcopy(raw)
    design = compile_concept(raw)
    assert work_interface_issues(design) == []
    assert raw == before
    assert design['work_interfaces'][0]['target_key'] == 'card'


@pytest.mark.parametrize('change', [{'phase': 0}, {'axis': [0, 1, 0]}])
def test_wrong_phase_or_backwards_axis_misses_the_actual_sample(change):
    raw = fixture()
    raw['work_interfaces'][0].update(change)
    with pytest.raises(ValueError, match='misses the actual box target'):
        compile_concept(raw)


def test_fractional_phase_and_local_offset_pivot_are_applied_exactly():
    raw = fixture()
    raw['components'][3]['placement_mm'] = [30/math.sqrt(2), 100, -30/math.sqrt(2)]
    raw['work_interfaces'][0]['phase'] = 0.5
    assert compile_concept(raw)
    raw = fixture()
    raw['steps'][0]['pivot_mm'] = [10, 0, 0]
    raw['components'][3]['placement_mm'] = [10, 100, -20]
    assert compile_concept(raw)


def test_moving_tool_and_target_descendants_preserve_relative_axis():
    raw = fixture()
    raw['components'][3].update(parent_key='rotor', placement_mm=[30, 100, 0])
    raw['steps'][0]['translation_mm'] = [20, 0, 10]
    raw['work_interfaces'][0].update(min_distance_mm=90, max_distance_mm=120)
    assert compile_concept(raw)
    raw['work_interfaces'][0]['phase'] = 0.37
    assert compile_concept(raw)


@pytest.mark.parametrize('shape', ['sphere', 'cylinder'])
def test_curved_target_checks_actual_surface_instead_of_enclosing_box(shape):
    raw = fixture()
    raw['components'][2]['primitives'][0].update(shape=shape, size_mm=[10, 10, 10],
                                               center_mm=[0, 5, 0])
    raw['components'][3]['placement_mm'] = [4.9, 100, -25.1]
    raw['work_interfaces'][0].update(min_distance_mm=0, max_distance_mm=None)
    with pytest.raises(ValueError, match=f'misses the actual {shape}'):
        compile_concept(raw)
    raw['components'][3]['placement_mm'] = [4, 100, -30]
    assert compile_concept(raw)


def test_working_distance_and_selected_tool_origin_are_checked():
    raw = fixture()
    raw['work_interfaces'][0]['max_distance_mm'] = 85
    with pytest.raises(ValueError, match='reaches the target at 88 mm'):
        compile_concept(raw)
    raw = fixture()
    raw['work_interfaces'][0]['origin_mm'] = [200, 5, 0]
    with pytest.raises(ValueError, match='lies outside Camera primitive 0'):
        compile_concept(raw)


@pytest.mark.parametrize('change', [
    {'tool_key': 'unknown'}, {'target_primitive': 7}, {'step_name': 'Absent step'},
    {'axis': [0, 0, 0]}, {'axis': [0, -2, 0]}, {'axis': [0, True, 0]},
    {'phase': True}, {'phase': math.nan}, {'phase': 1.1}, {'tool_primitive': True},
    {'min_distance_mm': -1}, {'min_distance_mm': 100, 'max_distance_mm': 20},
])
def test_invalid_bindings_and_ranges_are_rejected(change):
    raw = fixture()
    raw['work_interfaces'][0].update(change)
    with pytest.raises(ValueError):
        compile_concept(raw)


def test_duplicate_interfaces_fail_and_old_proposals_default_to_empty_interfaces():
    raw = fixture()
    raw['work_interfaces'].append(deepcopy(raw['work_interfaces'][0]))
    with pytest.raises(ValueError, match='duplicated'):
        compile_concept(raw)
    raw.pop('work_interfaces')
    assert compile_concept(raw)['work_interfaces'] == []
    assert ConceptProposal.model_validate(raw).work_interfaces == []


def test_interface_model_rejects_self_target_and_unsupported_claims():
    raw = fixture()['work_interfaces'][0]
    with pytest.raises(ValueError):
        WorkInterface.model_validate({**raw, 'target_key': 'camera'})
    with pytest.raises(ValueError):
        WorkInterface.model_validate({**raw, 'verified_optics': True})


def test_rotating_tool_rotates_its_direction_about_the_local_pivot():
    raw = fixture()
    raw['components'][2].update(parent_key='base', placement_mm=[0, 100, -40])
    raw['components'][2]['primitives'][0].update(size_mm=[10, 10, 10], center_mm=[0, 5, 0])
    raw['components'][3]['placement_mm'] = [0, 100, 0]
    raw['steps'][0].update(component_keys=['camera'], moving_key='camera',
                           rotation_axis='x', pivot_mm=[0, 5, 0])
    raw['work_interfaces'][0].update(min_distance_mm=30, max_distance_mm=40)
    assert compile_concept(raw)


def test_interface_feedback_includes_expected_target_and_lateral_correction():
    raw = fixture()
    raw['components'][3]['placement_mm'][2] = -20
    with pytest.raises(ValueError) as error:
        compile_concept(raw)
    assert 'Expected target centre' in str(error.value)
    assert 'perpendicular mount correction' in str(error.value)


def indexed_fixture():
    raw = fixture()
    raw['steps'][0]['index_station'] = 'First view'
    for index, station in enumerate(('Second view', 'Third view'), 2):
        raw['steps'].append({**deepcopy(raw['steps'][0]), 'name': f'Index {index}',
                             'rotation_reference': 'previous_index', 'index_station': station})
    raw['components'].append(component('camera_second', 'box', [10, 10, 10],
                                        'base', [-30, 100, 0]))
    raw['components'].append(component('camera_third', 'box', [10, 10, 10],
                                        'base', [0, 100, 30]))
    raw['work_interfaces'].append({**deepcopy(raw['work_interfaces'][0]), 'key': 'second_view',
                                   'tool_key': 'camera_second', 'step_name': 'Index 2'})
    raw['work_interfaces'].append({**deepcopy(raw['work_interfaces'][0]), 'key': 'third_view',
                                   'tool_key': 'camera_third', 'step_name': 'Index 3'})
    return raw


def test_indexed_increments_compile_wrapped_targets_and_signed_actual_arcs():
    raw = indexed_fixture()
    original = deepcopy(raw)
    design = compile_concept(raw)
    assert [step['rotation_deg'] for step in design['steps']] == [90, 180, -90]
    assert [step['start_rotation_deg'] for step in design['steps']] == [0, 90, 180]
    assert [step['rotation_delta_deg'] for step in design['steps']] == [90, 90, 90]
    assert all(step['index_chain'] for step in design['steps'])
    assert [step['rotation_deg'] for step in design['proposal']['steps']] == [90, 90, 90]
    assert work_interface_issues(design) == []
    assert raw == original


def test_interface_phase_tracks_previous_index_pose_and_the_incremental_arc():
    raw = indexed_fixture()
    raw['work_interfaces'] = [{**raw['work_interfaces'][0], 'step_name': 'Index 2', 'phase': 0}]
    assert compile_concept(raw)
    raw['components'].append(component('camera_middle', 'box', [10, 10, 10], 'base',
                                        [-30/math.sqrt(2), 100, -30/math.sqrt(2)]))
    raw['work_interfaces'][0].update(tool_key='camera_middle', phase=0.5)
    assert compile_concept(raw)


def test_sweep_checks_actual_180_to_270_arc_instead_of_rest_to_minus90():
    raw = indexed_fixture()
    raw['components'].append(component('obstruction', 'box', [3, 2, 3],
                                        'base', [-21, 15, 21]))
    with pytest.raises(ValueError, match=r'Step 2 \(Index 3\) motion intersects'):
        compile_concept(raw)


@pytest.mark.parametrize('change', [
    {'moving_key': 'card', 'component_keys': ['card']},
    {'rotation_axis': 'x'}, {'pivot_mm': [1, 0, 0]}, {'translation_mm': [1, 0, 0]},
])
def test_incompatible_previous_index_references_are_rejected(change):
    raw = indexed_fixture()
    raw['steps'][1].update(change)
    with pytest.raises(ValueError):
        compile_concept(raw)


def test_stationary_boundary_breaks_incremental_chain_without_inferred_pose_hold():
    raw = indexed_fixture()
    raw['steps'].insert(1, {'name': 'Manual check', 'instruction': 'Inspect the result.',
                            'component_keys': ['card'], 'moving_key': None,
                            'translation_mm': [0, 0, 0]})
    with pytest.raises(ValueError, match='immediately preceding rotary step'):
        compile_concept(raw)


def test_explicit_different_index_stations_cannot_share_a_pose_but_legacy_steps_can():
    raw = indexed_fixture()
    raw['steps'][1].update(rotation_reference='from_rest', rotation_deg=90)
    with pytest.raises(ValueError, match='display labels do not move samples'):
        compile_concept(raw)
    raw['work_interfaces'] = raw['work_interfaces'][:1]
    raw['steps'] = raw['steps'][:2]
    for step in raw['steps']:
        step.pop('index_station')
    design = compile_concept(raw)
    assert [step['rotation_deg'] for step in design['steps']] == [90, 90]
    assert not any(step['index_chain'] for step in design['steps'])


def test_zero_degree_explicit_home_can_start_a_rotary_chain():
    raw = indexed_fixture()
    raw['work_interfaces'] = []
    raw['steps'][0]['rotation_deg'] = 0
    design = compile_concept(raw)
    assert [step['rotation_deg'] for step in design['steps']] == [0, 90, 180]
    assert all(step['index_chain'] for step in design['steps'])
