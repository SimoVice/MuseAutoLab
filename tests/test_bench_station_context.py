"""Accepted station chat uses only canonical operations and matching price records."""
import asyncio
import json
from copy import deepcopy

import httpx
import pytest

from app import api
from app.bench_station import StationProposal, compile_station
from app.domain import apply_update, new_project
from app.model_client import (
    ChatAction,
    ExtractedTurn,
    ModelSettings,
    _bench_station_facts,
    generate_turn,
)


def station_project():
    project = apply_update(new_project(), {'workflow_kind': 'general',
                                              'workspace_width_mm': 800.0})
    project['bench_station'] = compile_station(StationProposal(
        operations=['read_barcode', 'weigh', 'print_label']), workspace_width_mm=800)
    from app.workflows import describe_workflow
    project["workflow"] = describe_workflow(project)
    return project


def test_actual_model_payload_has_steps_candidates_and_only_bound_price_facts():
    project = station_project()
    project['procurement_report'] = {
        'project_id': project['id'], 'project_revision': project['revision'],
        'report_id': 'synthetic-report', 'expires_at': '2026-11-03T00:00:00Z',
        'known_partial_subtotal': 34.5, 'coverage': {'fresh_priced_count': 1},
        'rows': [{'group_id': 'bench-weigh-equipment', 'label': 'Balance',
            'status': 'priced', 'freshness': 'fresh', 'line_total': 34.5,
            'dated_fallback': {'price': 99999}, 'raw_html': 'must not be sent'},
            {'group_id': 'pipette', 'label': 'Legacy liquid', 'line_total': 99999}],
    }
    project['cost_estimate'] = {
        'project_id': project['id'], 'project_revision': project['revision'],
        'status': 'ready', 'model': 'synthetic-model',
        'generated_at': '2026-11-02T12:00:00Z', 'expires_at': '2026-11-03T12:00:00Z',
        'summary': {'estimated_additional_low_usd': 100, 'estimated_additional_high_usd': 300},
        'rows': [{'group_id': 'bench-weigh-equipment', 'source_kind': 'model_estimate',
                  'low_usd': 100, 'high_usd': 300, 'assumptions': ['Candidate only']}],
    }
    original = deepcopy(project)
    captured = {}
    def handler(request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop',
            'message': {'content': '{"assistant_message":"Follow the recorded station steps."}'}}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await generate_turn(
                project, 'What are its cost and operating steps?', [], client=client,
                settings=ModelSettings(api_key='synthetic', base_url='https://synthetic.invalid',
                                       model='synthetic-model'))
    asyncio.run(run())
    state = json.loads(captured['messages'][1]['content'].split(': ', 1)[1])
    facts = state['bench_station']
    assert facts['footprint_mm'] == project['bench_station']['footprint_mm']
    assert facts['steps'] == project['bench_station']['steps']
    assert facts['equipment_candidates'][0]['operation'] == 'read_barcode'
    assert facts['pricing']['supplier']['known_partial_subtotal'] == 34.5
    assert facts['pricing']['model_estimate']['summary']['estimated_additional_low_usd'] == 100
    assert len(facts['pricing']['supplier']['items']) == 1
    encoded = json.dumps(state)
    assert '99999' not in encoded and 'must not be sent' not in encoded
    assert 'dated_fallback' not in encoded
    assert state['reviewed_platforms'] == []
    assert 'non-liquid' in state['reviewed_reference_library']['architecture']
    assert project == original


def test_missing_or_stale_prices_do_not_use_legacy_liquid_fallback():
    project = station_project()
    project['sourcing']['subtotal'] = 99999
    for key in ('procurement_report', 'cost_estimate'):
        project[key] = {'project_id': project['id'], 'project_revision': project['revision'] - 1,
                        'summary': {'project_total_low_usd': 99999}}
    facts = _bench_station_facts(project)
    assert facts['pricing']['supplier_status'] == 'not_checked'
    assert facts['pricing']['model_estimate_status'] == 'not_estimated'
    assert '99999' not in json.dumps(facts)
    project['workflow']['kind'] = 'liquid_preparation'
    assert _bench_station_facts(project) is None


@pytest.mark.parametrize('kind,expected', [
    ('show_build_plan', 'operator steps'), ('show_sources', 'source links'),
    ('show_components', 'equipment and supplies'), ('show_files', 'Download layout'),
])
def test_station_navigation_actions_do_not_enter_liquid_guidance(monkeypatch, kind, expected):
    project = station_project()
    original = deepcopy(project)
    api._sessions[project['id']] = api.ProjectSession(project=project)
    async def inference(*args, **kwargs):
        return ExtractedTurn(assistant_message='Choose a pipetting platform first.',
            actions=[ChatAction(kind=kind, source='Show this station information')]), {}
    monkeypatch.setattr(api, 'generate_turn', inference)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app),
                                    base_url='http://test') as client:
            response = await client.post(f"/api/projects/{project['id']}/messages",
                                         json={'message': 'Show this station information'})
            assert response.status_code == 200, response.text
            body = response.json()
            assert expected in body['assistant_message']
            assert 'pipetting' not in body['assistant_message']
            assert body['action_runs'][0]['status'] == 'ready'
            assert body['project'] == original
            assert 'engineering_guidance' not in body['project']
    try:
        asyncio.run(run())
    finally:
        api._sessions.pop(project['id'], None)
