"""Reproducible canonical cold-transfer checks, without live model requests."""
from copy import deepcopy

import pytest
from test_foundation_storage import source_project
from test_microplates import select

from app import api
from app.cold_transfer import apply_cold_transfer, clear_cold_transfer, cold_transfer_intent
from app.geometry import add_geometry
from app.project_storage import make_snapshot, restore_snapshot


def plate_project():
    project = source_project()
    project['summary']['workspace_width_mm'] = None
    return select(project)


@pytest.mark.parametrize('message,intent', [
    ('Add a manipulator to transfer the prepared plate to a dedicated refrigerator', 'add'),
    ('Remove the refrigerator transfer manipulator', 'remove'),
    ('Do not add a robot arm to transfer to the fridge', 'discuss'),
    ('What if we add a robot arm to transfer to a fridge?', 'discuss'),
    ('Estimate the cost of a robot arm and refrigerator transfer', 'discuss'),
    ('Add a camera', None), ('Add cooling', None),
    ('Could you add a gripper to move the plate to a dedicated refrigerator?', 'add'),
    ('I want to know whether a refrigerator gripper would work', 'discuss'),
    ('What would it cost to remove the refrigerator transfer module?', 'discuss'),
    ('Show me the design without the cold-transfer gripper', 'discuss'),
    ('I would like a gripper to move a plate into the fridge', 'add'),
    ('Add a gripper to transfer the plate to a fridge and replace my rack', 'clarify'),
    ('Alongside the inspection camera, add a gripper to transfer the plate to a fridge', 'add'),
])
def test_explicit_intent(message, intent):
    assert cold_transfer_intent(message) == intent


def test_canonical_roundtrip_geometry_and_independent_equipment():
    original = plate_project()
    baseline = deepcopy(original)
    project = add_geometry(apply_cold_transfer(original))
    assert original == baseline
    module = project['cold_transfer_extension']
    assert module['payload_primitive_prefix'] == 'reference-plate-'
    assert len(module['component_ids']) == 8
    old = {p['id']:p for p in original['design']['components']}
    assert all(p == old[p['id']] for p in project['design']['components'] if p['id'] in old)
    restored, _ = restore_snapshot(make_snapshot(project, []))
    assert restored['cold_transfer_extension'] == project['cold_transfer_extension']
    assert restored['sourcing'] == project['sourcing']
    assert not clear_cold_transfer(project).get('cold_transfer_extension')


def test_loose_tubes_rejected():
    with pytest.raises(ValueError, match='96-well'):
        apply_cold_transfer(source_project())


def test_chat_is_normal_entry_point_and_does_not_call_model(monkeypatch):
    project = plate_project()
    api._sessions[project['id']] = api.ProjectSession(project=project)
    async def forbidden(*args, **kwargs):
        raise AssertionError('No model call expected')
    monkeypatch.setattr(api, 'generate_turn', forbidden)
    async def journey():
        response = await api.send_message(project['id'], api.MessageRequest(
            message='Add a manipulator to transfer the prepared plate to a dedicated refrigerator'))
        assert response['action_runs'][0]['status'] == 'accepted'
        assert response['project']['summary']['equipment'] == project['summary']['equipment']
        response = await api.send_message(project['id'], api.MessageRequest(
            message='Remove the refrigerator transfer manipulator'))
        assert not response['project'].get('cold_transfer_extension')
    coroutine = journey()
    with pytest.raises(StopIteration):
        coroutine.send(None)


def test_independent_inspection_and_export_guidance():
    import json

    from evolution_fixtures import inspection_proposal

    from app.assembly import build_extension_plan, build_extensions_md
    from app.inspection import apply_extension
    from app.software_guidance import build_software_guidance
    project = apply_extension(plate_project(), inspection_proposal(), {})
    inspection = deepcopy(project['inspection_extension'])
    project = apply_cold_transfer(project)
    assert project['inspection_extension'] == inspection
    plan = json.loads(build_extension_plan(project))
    assert plan['cold_transfer_extension'] == project['cold_transfer_extension']
    assert plan['inspection_extension'] == inspection
    assert b'liquid retention' in build_extensions_md(project)
    assert 'thermal performance' in ' '.join(build_software_guidance(project)['authoring_steps'])
    removed = clear_cold_transfer(project)
    assert removed['inspection_extension'] == inspection


@pytest.mark.parametrize('message', [
    'Do not remove the refrigerator transfer manipulator',
    'What if we remove the refrigerator transfer manipulator?',
])
def test_negative_hypothetical_removal_is_not_an_action(message):
    assert cold_transfer_intent(message) == 'discuss'


def test_all_project_acceptance_rebinds_and_rejects_unsupported_transition():
    from fastapi import HTTPException
    original = apply_cold_transfer(plate_project())
    session = api.ProjectSession(project=original)
    changed = deepcopy(original)
    next(p for p in changed['design']['components'] if p['id']=='sample-rack')['position'][0] += 5
    api._accept_project(session, changed)
    assert changed['cold_transfer_extension']['pickup_mm'][0] == (
        original['cold_transfer_extension']['pickup_mm'][0]+5)
    bad = deepcopy(changed)
    bad.pop('labware_plate')
    before = deepcopy(session.project)
    with pytest.raises(HTTPException, match='96-well'):
        api._accept_project(session, bad)
    assert session.project == before


def test_compact_cell_fits_800_mm_constraint():
    project = plate_project()
    project['summary']['workspace_width_mm'] = 800.0
    project = apply_cold_transfer(project)
    bounds = project['design']['assembly_bounds']
    assert bounds['max_mm'][0]-bounds['min_mm'][0] <= 800.0
    assert project['summary']['workspace_width_mm'] == 800.0
