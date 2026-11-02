"""Synthetic functional-specification API and provider-contract checks."""
import asyncio
import json
from copy import deepcopy

import httpx
import pytest

from app import api
from app.domain import apply_update, new_project
from app.functional_plan import propose_plan
from app.model_client import ModelClientError, ModelSettings

PLAN = {
    'objective': 'Record vial mass and identifier',
    'steps': [{'task': 'Weigh the vial', 'equipment_role': 'Balance',
               'handoff': 'Vial identifier and mass',
               'acceptance_check': 'Compare a check mass with its reference value'}],
    'open_questions': ['What balance readability is required?'],
}
GENERATED = {'status': 'proposed_specification', 'model': 'synthetic-model',
             'usage': {'total_tokens': 42}, 'plan': PLAN}


@pytest.fixture
def general_session():
    project = apply_update(new_project(), {'workflow_kind': 'general',
        'brief_objective': 'Record vial mass', 'brief_process': 'Weigh and identify vials'})
    session = api.ProjectSession(project=project)
    api._sessions[project['id']] = session
    try:
        yield session
    finally:
        api._sessions.pop(project['id'], None)


async def post_plan(client, session, revision=None):
    return await client.post(f"/api/projects/{session.project['id']}/functional-plan",
        json={'project_revision': session.project['revision'] if revision is None else revision})


def test_normal_endpoint_cache_revision_model_and_project_preservation(
        monkeypatch, general_session):
    from app import functional_plan
    session = general_session
    calls = []
    async def generate(brief):
        calls.append(deepcopy(brief))
        return deepcopy(GENERATED)
    monkeypatch.setattr(functional_plan, 'propose_plan', generate)
    initial = deepcopy(session.project)

    async def journey():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),
                                    base_url='http://test') as client:
            response = await post_plan(client, session)
            assert response.status_code == 200
            result = response.json()
            assert result['plan'] == PLAN
            assert result['project_revision'] == initial['revision']
            assert result['brief'] == initial['brief']
            assert result['project_id'] == initial['id']
            assert session.project == initial
            assert (await post_plan(client, session)).json() == result
            assert len(calls) == 1
            # Mutating a returned value must not corrupt the server cache.
            result['plan']['steps'].clear()
            assert (await post_plan(client, session)).json()['plan'] == PLAN
            response = await post_plan(client, session, revision=0)
            assert response.status_code == 409
            assert len(calls) == 1
            session.project = apply_update(session.project, {'brief_process': 'Weigh sealed vials'})
            response = await post_plan(client, session)
            assert response.status_code == 200
            assert len(calls) == 2
            assert calls[-1]['process'] == 'Weigh sealed vials'
            session.model = 'muse-wonder-1.0'
            assert (await post_plan(client, session)).status_code == 200
            assert len(calls) == 3
    asyncio.run(journey())


@pytest.mark.parametrize('kind,brief,station', [
    ('liquid_preparation', 'Pipette samples', False),
    ('unclassified', 'Inspect samples', False),
    ('general', None, False),
    ('general', 'Weigh samples', True),
])
def test_adapter_guards_never_call_provider(monkeypatch, general_session, kind, brief, station):
    from app import functional_plan
    session = general_session
    session.project = apply_update(new_project(), {'workflow_kind': kind,
        'brief_objective': brief, 'brief_process': brief})
    # Keep the existing session key while replacing the synthetic project contents.
    key = next(key for key, value in api._sessions.items() if value is session)
    session.project['id'] = key
    if station:
        session.project['bench_station'] = {'proposal': {'operations': ['weigh']}}
    original = deepcopy(session.project)
    async def forbidden(*args, **kwargs):
        pytest.fail('Guarded workflow must never call the model')
    monkeypatch.setattr(functional_plan, 'propose_plan', forbidden)
    async def journey():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),
                                    base_url='http://test') as client:
            assert (await post_plan(client, session)).status_code == 409
    asyncio.run(journey())
    assert session.project == original
    assert session.functional_plan is None


def test_provider_failure_does_not_cache_or_mutate(monkeypatch, general_session):
    from app import functional_plan
    session = general_session
    original = deepcopy(session.project)
    async def failure(*args, **kwargs):
        raise ModelClientError('Synthetic provider failure')
    monkeypatch.setattr(functional_plan, 'propose_plan', failure)
    async def journey():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),
                                    base_url='http://test') as client:
            response = await post_plan(client, session)
            assert response.status_code == 502
            assert response.json()['detail'] == 'Synthetic provider failure'
    asyncio.run(journey())
    assert session.project == original
    assert session.functional_plan is None


def provider_response(plan=PLAN, finish='stop'):
    return {'model': 'synthetic-reported', 'usage': {'total_tokens': 42},
            'choices': [{'finish_reason': finish,
                         'message': {'content': json.dumps(plan)}}]}


def run_provider(handler):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await propose_plan({'objective': 'Weigh vials'}, client=client,
                settings=ModelSettings(api_key='synthetic-key',
                    base_url='https://synthetic.invalid/v1', model='synthetic-requested'))
    return asyncio.run(run())


def test_provider_parses_plan_and_uses_bounded_strict_schema():
    captured = {}
    def handler(request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=provider_response())
    result = run_provider(handler)
    assert result['plan'] == PLAN
    assert result['model'] == 'synthetic-reported'
    assert result['usage'] == {'total_tokens': 42}
    assert captured['max_completion_tokens'] == 1600
    assert captured['reasoning_effort'] == 'minimal'
    assert json.loads(captured['messages'][1]['content']) == {'objective': 'Weigh vials'}
    def strict(node):
        if isinstance(node, dict):
            if node.get('type') == 'object':
                assert node['additionalProperties'] is False
                assert set(node['required']) == set(node['properties'])
            for child in node.values():
                strict(child)
        elif isinstance(node, list):
            for child in node:
                strict(child)
    strict(captured['response_format']['json_schema']['schema'])


@pytest.mark.parametrize('body', [
    {}, {'choices': []}, provider_response(finish='length'),
    provider_response(plan={'objective': 'Missing steps'}),
    provider_response(plan={**PLAN, 'steps': []}),
    provider_response(plan={**PLAN, 'steps': [{**PLAN['steps'][0], 'price': 12}]}),
    provider_response(plan={**PLAN, 'open_questions': []}),
    provider_response(plan={**PLAN, 'objective': ' '}),
])
def test_invalid_or_incomplete_provider_responses_are_sanitized(body):
    with pytest.raises(ModelClientError, match='functional plan could not be generated'):
        run_provider(lambda request: httpx.Response(200, json=body))


@pytest.mark.parametrize('status', [400, 401, 429, 500])
def test_provider_http_failures_are_sanitized(status):
    with pytest.raises(ModelClientError, match='functional plan could not be generated'):
        run_provider(lambda request: httpx.Response(status, text='secret provider detail'))


def test_provider_network_failure_is_sanitized():
    def failure(request):
        raise httpx.ConnectError('secret transport detail', request=request)
    with pytest.raises(ModelClientError, match='functional plan could not be generated'):
        run_provider(failure)
