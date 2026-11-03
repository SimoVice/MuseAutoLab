"""Public capability descriptions follow actual workflow scope without model calls."""

import asyncio
from copy import deepcopy

import httpx
import pytest

import app.api as api
from app.bench_station import StationProposal, compile_station
from app.domain import apply_update, new_project
from app.workflows import describe_workflow


def general_project():
    return apply_update(new_project(), {
        'workflow_kind': 'general',
        'brief_objective': 'Track microscopy samples',
        'brief_process': 'Capture an image and associate it with the sample identifier',
    })


def test_general_functional_planning_is_visible_without_claiming_machine_design():
    project = general_project()
    original = deepcopy(project)
    workflow = describe_workflow(project)
    assert project == original
    assert workflow['status'] == 'planning'
    assert 'functional planning' in workflow['capabilities']
    assert workflow['design_available'] is False
    assert 'proposed operations' in workflow['scope']
    assert 'downloadable models' in workflow['scope']


def test_compiled_bench_is_a_supported_concept_without_enabling_liquid_design():
    project = general_project()
    project['bench_station'] = compile_station(StationProposal(operations=['inspect']))
    before = deepcopy(project)
    workflow = describe_workflow(project)
    assert project == before
    assert workflow['kind'] == 'general'
    assert workflow['label'] == 'Human-operated bench station'
    assert workflow['status'] == 'supported_concept'
    assert workflow['design_available'] is False
    assert workflow['parameters_started'] is False
    assert 'schematic 3d' in workflow['capabilities']
    assert 'human-operated workflow' in workflow['scope']
    assert 'no fabrication CAD, physics validation or hardware control' in workflow['scope']
    project.pop('bench_station')
    assert describe_workflow(project)['status'] == 'planning'


@pytest.mark.parametrize('bench', [False, True])
def test_downloaded_brief_derives_current_capabilities_and_keeps_revision_guard(bench):
    project = general_project()
    if bench:
        # Deliberately leave the stored workflow at its earlier planning stage.
        project['bench_station'] = compile_station(StationProposal(operations=['weigh']))
    original = deepcopy(project)
    session = api.ProjectSession(project=project)
    api._sessions[project['id']] = session

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),
                                     base_url='http://offline') as client:
            path = f"/api/projects/{project['id']}/brief"
            response = await client.get(path, params={'revision': project['revision']})
            assert response.status_code == 200
            payload = response.json()
            assert payload['brief'] == project['brief']
            assert payload['workflow'] == describe_workflow(project)
            assert payload['workflow']['status'] == ('supported_concept' if bench else 'planning')
            assert 'bench_station' not in payload
            assert response.headers['cache-control'] == 'no-store'
            stale = await client.get(path, params={'revision': project['revision'] + 1})
            assert stale.status_code == 409

    try:
        asyncio.run(run())
        assert session.project == original
    finally:
        api._sessions.pop(project['id'], None)
