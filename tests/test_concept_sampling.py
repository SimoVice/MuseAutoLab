"""Independent equal-solid sampling registration; no workflow or private data fixtures."""

from copy import deepcopy

import pytest

from app.concept_design import compile_concept
from app.concept_interfaces import WorkInterface, work_interface_issues
from app.concept_sampling import sampling_patterns


def fixture(shape='box'):
    def component(key, primitives, parent=None, placement=None):
        return {'key': key, 'name': key.title(), 'role': 'Proposed test part.',
                'primitives': primitives, 'parent_key': parent, 'placement_mm': placement,
                'source_id': None, 'assembly': 'Specify mounting and inspect the proposed part.',
                'check': 'Verify dimensions and use before commissioning.'}

    def solid(kind, size, center):
        return {'shape': kind, 'size_mm': size, 'center_mm': center, 'finish': 'polymer'}

    return {
        'title': 'Repeated target scan', 'overview': 'Proposed geometric scan of equal solids.',
        'components': [
            component('base', [solid('box', [300, 10, 120], [0, 5, 0])]),
            component('samples', [solid(shape, [10, 10, 10], [20*i, 5, 0]) for i in range(5)],
                      'base', [0, 10, 0]),
            component('tool', [solid('box', [5, 10, 5], [0, 5, 0])], 'base', [-10, 60, 0])],
        'steps': [{'name': 'Traverse targets',
                   'instruction': 'Pause at the proposed sampling stops.',
                   'component_keys': ['tool', 'samples'], 'moving_key': 'tool',
                   'translation_mm': [100, 0, 0], 'stops': [0, 0.25, 0.5, 0.75, 1]}],
        'software': {'controller': 'Unconnected controller.', 'interfaces': [],
                     'setup': ['Verify the scan geometry.'], 'checks': ['Check limits and stop.']},
        'open_questions': [],
        'work_interfaces': [{'key': 'sample_read', 'label': 'Read a proposed sample',
                             'tool_key': 'tool', 'tool_primitive': 0,
                             'target_key': 'samples', 'target_primitive': 2, 'axis': [0, -1, 0],
                             'step_name': 'Traverse targets', 'phase': 0.5,
                             'min_distance_mm': 40, 'max_distance_mm': 50}],
    }


@pytest.mark.parametrize('shape', ['box', 'sphere', 'cylinder'])
def test_registration_finds_each_actual_solid_without_mutating_travel_or_authored_stops(shape):
    raw = fixture(shape)
    design = compile_concept(raw)
    before = deepcopy(design)
    patterns = sampling_patterns(design)
    assert design == before
    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern['step_name'] == 'Traverse targets'
    assert pattern['target_key'] == 'samples'
    assert pattern['fractions'] == pytest.approx([0.1, 0.3, 0.5, 0.7, 0.9])
    assert pattern['sample_primitive_indexes'] == [0, 1, 2, 3, 4]
    assert pattern['original_fractions'] == [0, 0.25, 0.5, 0.75, 1]
    assert pattern['confirmation_required'] is True
    assert len(pattern['work_interfaces']) == 5
    assert len({record['key'] for record in pattern['work_interfaces']}) == 5
    assert [record['label'] for record in pattern['work_interfaces']] == [
        f'Sampling position {i} on Samples' for i in range(1, 6)]
    for phase, record in zip(pattern['fractions'], pattern['work_interfaces']):
        assert WorkInterface.model_validate(record).phase == phase
        assert work_interface_issues({**design, 'work_interfaces': [record]}) == []
    registered = deepcopy(raw)
    registered['steps'][0]['stops'] = pattern['fractions']
    registered['work_interfaces'] = pattern['work_interfaces']
    assert compile_concept(registered)['steps'][0]['translation_mm'] == [100, 0, 0]


def test_negative_scan_direction_orders_targets_by_travel_instead_of_primitive_index():
    raw = fixture()
    raw['components'][2]['placement_mm'][0] = 90
    raw['steps'][0]['translation_mm'][0] = -100
    pattern = sampling_patterns(compile_concept(raw))[0]
    assert pattern['sample_primitive_indexes'] == [4, 3, 2, 1, 0]
    assert pattern['fractions'] == pytest.approx([0.1, 0.3, 0.5, 0.7, 0.9])


def test_relative_registration_also_handles_moving_samples_under_stationary_tool():
    raw = fixture()
    raw['components'][1]['placement_mm'][0] = 50
    raw['components'][2]['placement_mm'][0] = 40
    raw['steps'][0].update(moving_key='samples', translation_mm=[-100, 0, 0])
    pattern = sampling_patterns(compile_concept(raw))[0]
    assert pattern['fractions'] == pytest.approx([0.1, 0.3, 0.5, 0.7, 0.9])
    assert pattern['sample_primitive_indexes'] == [0, 1, 2, 3, 4]


@pytest.mark.parametrize('edit', [
    lambda p: p['steps'][0].update(stops=[0, 0.3, 0.6, 1]),
    lambda p: p['components'][1]['primitives'][4]['center_mm'].__setitem__(0, 110),
    lambda p: p['components'][1]['primitives'][0]['center_mm'].__setitem__(2, 2),
    lambda p: p['components'][1]['primitives'][0]['center_mm'].__setitem__(1, 6),
    lambda p: p['components'][1]['primitives'][0].update(size_mm=[12, 10, 10]),
])
def test_cardinality_unreachable_noncollinear_or_unequal_groups_are_not_guessed(edit):
    raw = fixture()
    edit(raw)
    assert sampling_patterns(compile_concept(raw)) == []


def test_every_sample_must_pass_actual_working_range_in_diagonal_translation():
    raw = fixture()
    raw['steps'][0]['translation_mm'][1] = 20
    raw['work_interfaces'][0]['max_distance_mm'] = 60
    # The middle authored interface passes at 55 mm; final sample would be 63 mm away.
    design = compile_concept(raw)
    assert work_interface_issues(design) == []
    assert sampling_patterns(design) == []


def test_common_rigid_translation_has_no_relative_scan_to_register():
    raw = fixture()
    raw['components'][2]['placement_mm'][0] = 40
    raw['steps'][0].update(moving_key='base', component_keys=['base', 'tool', 'samples'])
    assert sampling_patterns(compile_concept(raw)) == []


def test_missing_interface_or_missing_authored_stops_does_not_invent_sampling_intent():
    raw = fixture()
    raw['work_interfaces'] = []
    assert sampling_patterns(compile_concept(raw)) == []
    raw = fixture()
    raw['steps'][0]['stops'] = []
    assert sampling_patterns(compile_concept(raw)) == []


def test_equivalent_declared_views_do_not_duplicate_the_same_sampling_candidate():
    raw = fixture()
    raw['work_interfaces'].append({**raw['work_interfaces'][0], 'key': 'another_view',
                                   'target_primitive': 0, 'phase': 0.1})
    assert len(sampling_patterns(compile_concept(raw))) == 1


def test_registration_is_repeatable_and_keeps_existing_axis_origin_and_range():
    raw = fixture()
    design = compile_concept(raw)
    first = sampling_patterns(design)
    assert first == sampling_patterns(design)
    source = design['work_interfaces'][0]
    for record in first[0]['work_interfaces']:
        assert all(record[key] == source[key] for key in (
            'axis', 'origin_mm', 'min_distance_mm', 'max_distance_mm',
            'tool_key', 'tool_primitive', 'target_key', 'step_name'))
