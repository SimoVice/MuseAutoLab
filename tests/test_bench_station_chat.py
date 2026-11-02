"""Synthetic normal-endpoint station journeys; no provider requests."""
import asyncio
from copy import deepcopy

import httpx
import pytest

from app import api
from app.domain import apply_update, new_project
from app.model_client import ChatAction, ExtractedTurn
from app.project_storage import make_snapshot, restore_snapshot


def station_turn(message, operations, **kwargs):
    return ExtractedTurn(assistant_message="Synthetic station proposal", actions=[ChatAction(
        kind="develop_bench_station", source=message, operations=operations,
        operation_sources={op: message for op in operations})], **kwargs)


def test_normal_endpoint_create_reorder_question_width_save_routes(monkeypatch):
    project = new_project()
    api._sessions[project['id']] = api.ProjectSession(project=project)
    turns = []

    async def inference(*args, **kwargs):
        turn = turns.pop(0)
        turn.verify_sources(args[1], args[0])
        return turn, {}
    monkeypatch.setattr(api, 'generate_turn', inference)

    async def journey():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),
                                    base_url='http://test') as client:
            url = f"/api/projects/{project['id']}"
            message = 'Design a station to weigh samples then print labels and read barcodes'
            turns.append(station_turn(message, ['weigh', 'print_label', 'read_barcode'],
                                      workflow_kind='general', source_workflow_kind=message))
            response = await client.post(url + '/messages', json={'message': message})
            assert response.status_code == 200, response.text
            created = response.json()['project']
            assert created['bench_station']['proposal']['operations'] == [
                'weigh', 'print_label', 'read_barcode']
            message = 'Read barcodes first, then weigh samples and print labels'
            turns.append(station_turn(message, ['read_barcode', 'weigh', 'print_label']))
            response = await client.post(url + '/messages', json={'message': message})
            assert response.status_code == 200, response.text
            revised = response.json()['project']
            assert revised['brief']['process'] == ' → '.join(
                module['label'] for module in revised['bench_station']['modules'])
            turns.append(ExtractedTurn(assistant_message='The station is a concept.'))
            response = await client.post(url + '/messages', json={'message': 'How does it work?'})
            assert response.json()['project']['bench_station'] == revised['bench_station']
            assert response.json()['project']['revision'] == revised['revision']
            saved = make_snapshot(revised, [])
            assert saved['bench_station'] == revised['bench_station']['proposal']
            rebuilt, _ = restore_snapshot(saved)
            assert rebuilt['bench_station'] == revised['bench_station']
            for artifact in ('plan.json', 'layout.svg', 'run.py'):
                response = await client.get(url + f'/bench-station/{artifact}',
                                            params={'revision': revised['revision']})
                assert response.status_code == 200, response.text
            response = await client.get(url + '/bench-station/plan.json', params={'revision': 0})
            assert response.status_code == 409
            turns.append(ExtractedTurn(assistant_message='Use a 500 mm bench',
                                      workspace_width_mm=500.0,
                                      source_workspace_width_mm='500 mm'))
            response = await client.post(url + '/messages', json={'message': 'Use 500 mm width'})
            assert response.status_code == 200, response.text
            revised = response.json()['project']
            assert revised['summary']['workspace_width_mm'] == 500.0
            rebuilt, _ = restore_snapshot(make_snapshot(revised, []))
            assert rebuilt['bench_station'] == revised['bench_station']
            turns.append(ExtractedTurn(assistant_message='Reduce width', workspace_width_mm=50.0,
                                      source_workspace_width_mm='50 mm'))
            response = await client.post(url + '/messages', json={'message': 'Use 50 mm width'})
            assert response.status_code == 422
            assert api._sessions[project['id']].project == revised
    try:
        asyncio.run(journey())
    finally:
        api._sessions.pop(project['id'], None)


@pytest.mark.parametrize('message', [
    'Design a station to weigh then sterile filter samples',
    'Design a station to weigh and automatically apply labels',
    'Design a station to pipette and weigh samples',
])
def test_unsupported_scope_never_builds_partial_station(message):
    turn = station_turn(message, ['weigh'], workflow_kind='general',
                        source_workflow_kind=message)
    with pytest.raises(ValueError):
        turn.verify_sources(message, new_project())


def test_liquid_flow_not_rerouted_and_switch_clears_station():
    from app.bench_station import StationProposal, compile_station
    from app.bench_station_chat import update_station
    project = apply_update(new_project(), {'workflow_kind': 'liquid_preparation'})
    message = 'Design a station to weigh samples'
    with pytest.raises(ValueError):
        station_turn(message, ['weigh']).verify_sources(message, project)
    general = apply_update(new_project(), {'workflow_kind': 'general'})
    general['bench_station'] = compile_station(StationProposal(operations=['weigh']))
    switched = apply_update(general, {'workflow_kind': 'liquid_preparation'})
    result, _ = update_station(general, switched, [], 'Switch to pipetting')
    assert 'bench_station' not in result
    assert general['bench_station']
    malicious = make_snapshot(general, [])
    malicious['bench_station']['modules'] = [{'size': [1, 2, 3]}]
    with pytest.raises(ValueError):
        restore_snapshot(malicious)
    assert general == deepcopy(general)


@pytest.mark.parametrize('message', ['What if we design a station to weigh?',
                                      'Can this station weigh samples?',
                                      "Do not build a station to weigh samples"])
def test_questions_and_negative_requests_cannot_generate(message):
    turn = station_turn(message, ['weigh'], workflow_kind='general',
                        source_workflow_kind=message)
    with pytest.raises(ValueError):
        turn.verify_sources(message, new_project())


def test_accepted_liquid_machine_requires_separate_project():
    project = apply_update(new_project(), {'workflow_kind': 'liquid_preparation'})
    project['engineering_design'] = {'proposal': {'source': 'synthetic'}}
    message = 'Design a new station to weigh samples'
    turn = station_turn(message, ['weigh'], workflow_kind='general',
                        source_workflow_kind=message)
    with pytest.raises(ValueError, match='new project'):
        turn.verify_sources(message, project)


def test_process_change_invalidates_station_but_preserves_authored_brief():
    from app.bench_station import StationProposal, compile_station
    from app.bench_station_chat import update_station
    project = apply_update(new_project(), {'workflow_kind': 'general'})
    project['bench_station'] = compile_station(StationProposal(operations=['weigh']))
    updated = apply_update(project, {'brief_process': 'Sterile filtering'})
    updated, run = update_station(project, updated, [], 'I need sterile filtering')
    assert 'bench_station' not in updated
    assert updated['brief']['process'] == 'Sterile filtering'
    assert run['status'] == 'ready'


def test_mixed_laser_request_gets_clarification_without_partial_station(monkeypatch):
    project = new_project()
    api._sessions[project['id']] = api.ProjectSession(project=project)
    message = 'Design a station to weigh my vials and laser-etch serial numbers'
    async def inference(*args, **kwargs):
        return station_turn(message, ['weigh'], workflow_kind='general',
                            source_workflow_kind=message), {}
    monkeypatch.setattr(api, 'generate_turn', inference)
    async def journey():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),
                                    base_url='http://test') as client:
            response = await client.post(f"/api/projects/{project['id']}/messages",
                                         json={'message': message})
            assert response.status_code == 200
            assert response.json()['project'] == project
            assert 'unsupported' in response.json()['assistant_message']
    try:
        asyncio.run(journey())
    finally:
        api._sessions.pop(project['id'], None)


def test_microcentrifuge_tubes_are_materials_not_centrifugation():
    message = 'Design a station to weigh microcentrifuge tubes'
    station_turn(message, ['weigh'], workflow_kind='general',
                 source_workflow_kind=message).verify_sources(message, new_project())


def test_separate_width_restore_preserves_verbatim_general_constraints():
    project = apply_update(new_project(), {
        "workflow_kind": "general", "workspace_width_mm": 800,
        "brief_constraints": "My bench is 800 mm wide.",
    })
    restored, _ = restore_snapshot(make_snapshot(project, []))
    assert restored["brief"] == project["brief"]
    assert restored["summary"] == project["summary"]


def test_uncited_current_classification_does_not_block_a_sourced_reorder():
    from test_model_client import TEST_SETTINGS, valid_response

    from app.bench_station import StationProposal, compile_station
    from app.model_client import generate_turn

    project = apply_update(new_project(), {"workflow_kind": "general"})
    project["bench_station"] = compile_station(StationProposal(operations=["weigh", "inspect"]))
    request = "Change the order to inspect first, then weigh."
    action = station_turn(request, ["inspect", "weigh"]).actions[0]
    body = valid_response(workflow_kind="general", actions=[action.model_dump()])

    async def run():
        transport = httpx.MockTransport(lambda req: httpx.Response(200, json=body))
        async with httpx.AsyncClient(transport=transport) as client:
            turn, _ = await generate_turn(
                project, request, [], settings=TEST_SETTINGS, client=client)
            assert turn.workflow_kind is None
            assert turn.actions[0].operations == ["inspect", "weigh"]

    asyncio.run(run())
