"""Independent fit cases; no private provider records or per-workflow production rules."""

from copy import deepcopy
from time import perf_counter

import pytest
from test_custom_project_routes import proposal

from app.concept_design import ConceptProposal, assembly_review_issues, compile_concept
from app.concept_fit import fit_concept


def test_valid_original_is_unchanged_and_has_no_adjustments():
    raw = proposal()
    original = deepcopy(raw)
    fitted, changes = fit_concept(raw, 600)
    assert fitted == compile_concept(raw, 600)
    assert changes == []
    assert raw == original


def test_small_attachment_interference_is_resolved_without_changing_device_or_travel():
    raw = proposal()
    raw['components'][1]['placement_mm'][1] = 9
    original = deepcopy(raw)
    fitted, changes = fit_concept(raw, 600)
    assert fitted is not None and changes
    assert assembly_review_issues(fitted) == []
    normalized = ConceptProposal.model_validate(raw).model_dump()
    assert fitted['proposal']['components'][1]['primitives'] == (
        normalized['components'][1]['primitives'])
    assert fitted['proposal']['steps'] == ConceptProposal.model_validate(raw).model_dump()['steps']
    assert fitted['proposal']['supplies'] == normalized['supplies']
    assert raw == original
    assert any('attachment' in change or 'vertical stack' in change for change in changes)


def test_floating_working_center_is_preserved_by_visible_separate_custom_mount():
    raw = proposal()
    raw['components'][1]['placement_mm'][1] = 30
    fitted, changes = fit_concept(raw, 600)
    assert fitted is not None
    assert fitted['proposal']['components'][:2] == (
        ConceptProposal.model_validate(raw).model_dump()['components'])
    assert len(fitted['parts']) > len(raw['components']) + len(raw['supplies'])
    mounts = [c for c in fitted['components'] if c['key'].startswith('fit-mount-')]
    assert mounts and all(c['source_id'] is None for c in mounts)
    assert any('modeled custom mount' in change for change in changes)
    # A bracket belonging to a moving tray must travel with it.
    assert mounts[0]['parent_key'] == 'sample_tray'
    assert mounts[0]['key'] in fitted['steps'][0]['moving_component_keys']
    assert assembly_review_issues(fitted) == []


def test_support_search_avoids_an_obstruction_without_relocating_working_payload():
    raw = proposal()
    raw['components'][0]['primitives'][0].update(size_mm=[200, 10, 200])
    raw['components'][1]['placement_mm'] = [0, 30, 0]
    raw['components'][1]['primitives'][0].update(size_mm=[100, 8, 100])
    raw['components'][0]['primitives'].append({
        'shape': 'box', 'size_mm': [20, 15, 20], 'center_mm': [0, 17.5, 0], 'finish': 'steel'})
    raw['steps'][0].update(moving_key=None, translation_mm=[0, 0, 0])
    fitted, changes = fit_concept(raw, 600)
    assert fitted is not None
    assert fitted['proposal']['components'][1]['placement_mm'] == [0, 30, 0]
    assert assembly_review_issues(fitted) == []
    assert changes


def test_existing_accepted_parts_are_frozen_while_new_cover_moves():
    previous = proposal()
    raw = deepcopy(previous)
    guard = deepcopy(raw['components'][1])
    guard.update(key='guard', name='Travel guard', placement_mm=[45, 10, 0])
    guard['primitives'][0].update(size_mm=[20, 25, 40], center_mm=[0, 12.5, 0])
    raw['components'].append(guard)
    fitted, changes = fit_concept(raw, 600, prior_proposal=previous)
    assert fitted is not None and changes
    assert fitted['proposal']['components'][:2] == (
        ConceptProposal.model_validate(previous).model_dump()['components'])
    normalized = ConceptProposal.model_validate(previous).model_dump()
    assert fitted['proposal']['steps'] == normalized['steps']


def test_non_solution_has_bounded_work_and_publishes_no_partial_geometry():
    raw = proposal()
    raw['components'][1]['placement_mm'] = [0, 400, 0]
    original = deepcopy(raw)
    started = perf_counter()
    result, changes = fit_concept(raw, 600, max_attempts=8)
    assert result is None and 'No partial changes' in changes[0]
    assert perf_counter() - started < 3.5
    assert raw == original


@pytest.mark.parametrize('width', [True, 0, -1, float('nan'), '600', 100])
def test_invalid_or_unfit_workspace_is_not_solved_by_scaling_or_deleting(width):
    raw = proposal()
    original = deepcopy(raw)
    fitted, changes = fit_concept(raw, width)
    assert fitted is None and changes
    assert raw == original


@pytest.mark.parametrize('budget', [True, 0, -1, 257, 2.5])
def test_candidate_budget_is_strictly_bounded(budget):
    with pytest.raises(ValueError, match='Fit attempts'):
        fit_concept(proposal(), 600, max_attempts=budget)


def test_invalid_links_cannot_be_repaired_by_discarding_a_supply():
    raw = proposal()
    raw['supplies'][0]['component_keys'] = ['nonexistent-device']
    fitted, changes = fit_concept(raw, 600)
    assert fitted is None
    assert 'valid declarative proposal' in changes[0]
    assert len(raw['supplies']) == 2


def test_fit_is_repeatable_and_preserves_sources_and_absolute_motion():
    raw = proposal()
    raw['components'][1]['placement_mm'][1] = 30
    first, changes = fit_concept(raw, 600)
    second, repeated = fit_concept(raw, 600)
    assert first == second and changes == repeated
    assert first['parts'][2]['source_id'] is None  # New custom mount, never a vendor item.
    normalized = ConceptProposal.model_validate(raw).model_dump()
    assert first['proposal']['supplies'] == normalized['supplies']
    assert first['steps'][0]['translation_mm'] == raw['steps'][0]['translation_mm']


def test_axis_alignment_moves_compatible_mount_ancestor_without_detaching_camera():
    from test_concept_interfaces import component, fixture

    raw = fixture()
    raw['components'][0]['primitives'][0]['size_mm'][0] = 200
    raw['components'] += [component('post', 'box', [10, 90, 10], 'base', [90, 10, -20]),
                          component('boom', 'box', [90, 10, 10], 'post', [-90, 90, 0])]
    raw['components'][-1]['primitives'][0]['center_mm'][0] = 45
    raw['components'][3].update(parent_key='boom', placement_mm=[0, -10, 0])
    raw['work_interfaces'][0].update(min_distance_mm=70, max_distance_mm=90)
    before = ConceptProposal.model_validate(raw).model_dump()
    fitted, changes = fit_concept(raw, 600)
    assert fitted is not None and any('Aligned' in change for change in changes)
    assert fitted['proposal']['work_interfaces'] == before['work_interfaces']
    assert fitted['proposal']['components'][3]['placement_mm'] == [0, -10, 0]
    assert fitted['proposal']['components'][4]['placement_mm'] == pytest.approx([90, 10, -30])
    assert assembly_review_issues(fitted) == []
    assert compile_concept(fitted['proposal'], 600) == fitted


def stacked_fixture():
    raw = proposal()
    raw['components'][0]['primitives'][0].update(size_mm=[180, 20, 100], center_mm=[0, 10, 0])
    raw['components'][1]['placement_mm'] = [0, 20, 0]
    motor = deepcopy(raw['components'][1])
    motor.update(key='drive_head', name='Drive head', placement_mm=[0, -16, 0])
    motor['primitives'] = [
        {'shape': 'box', 'size_mm': [20, 36, 20], 'center_mm': [0, 18, 0], 'finish': 'steel'},
        {'shape': 'cylinder', 'size_mm': [5, 5, 5], 'center_mm': [0, 38.5, 0], 'finish': 'steel'}]
    raw['components'].append(motor)
    return raw


def test_coupled_stack_lifts_lower_intruding_part_and_upper_platform_atomically():
    raw = stacked_fixture()
    original = deepcopy(raw)
    fitted, changes = fit_concept(raw, 600)
    assert fitted is not None
    poses = {c['key']: c['placement_mm'] for c in fitted['proposal']['components']}
    assert poses['drive_head'] == [0, 20, 0]
    assert poses['sample_tray'] == [0, 61, 0]
    assert any('coupled projected vertical stack' in explanation for explanation in changes)
    assert raw == original
    assert fitted['steps'][0]['translation_mm'] == original['steps'][0]['translation_mm']
    assert assembly_review_issues(fitted) == []


def test_stack_candidate_does_not_move_an_unchanged_frozen_platform():
    from app.concept_fit import _layout, _stack_candidate

    raw = ConceptProposal.model_validate(stacked_fixture()).model_dump()
    original = {c['key']: c for c in raw['components']}
    result = _stack_candidate(raw, _layout(raw), original, {'sample_tray'})
    assert result == []


def test_overhead_member_does_not_lift_a_clear_nested_part_above_the_frame():
    from app.concept_fit import _layout, _stack_candidate

    raw = ConceptProposal.model_validate(proposal()).model_dump()
    raw['components'][0]['primitives'].append({
        'shape': 'box', 'size_mm': [180, 10, 100], 'center_mm': [0, 205, 0],
        'finish': 'frame', 'color': None})
    original = {c['key']: c for c in raw['components']}
    assert _stack_candidate(raw, _layout(raw), original, set()) == []


def test_related_support_models_have_distinct_readable_display_names():
    raw = proposal()
    raw['components'][1]['placement_mm'] = [0, 30, 0]
    first = raw['components'][1]['primitives'][0]
    first.update(size_mm=[10, 8, 20], center_mm=[-30, 4, 0])
    raw['components'][1]['primitives'].append({**deepcopy(first), 'center_mm': [30, 4, 0]})
    fitted, _ = fit_concept(raw, 600)
    assert fitted is not None
    names = [part['name'] for part in fitted['components'] if part['key'].startswith('fit-mount-')]
    assert len(names) >= 2 and len(set(names)) == len(names)
