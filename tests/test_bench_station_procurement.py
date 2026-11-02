"""Offline bench purchase scopes and model allowances, never supplier evidence."""

import asyncio
import json
from copy import deepcopy
from itertools import combinations

import pytest
from test_price_estimation import estimate

from app import price_estimation as prices
from app import procurement
from app.bench_station import StationProposal, compile_station
from app.domain import new_project

OPERATIONS = ['weigh', 'print_label', 'read_barcode', 'inspect']


def station_project(operations=OPERATIONS):
    project = new_project()
    project['bench_station'] = compile_station(StationProposal(operations=operations))
    project.pop('engineering_design', None)
    return project


@pytest.mark.parametrize('operations', [list(c) for n in range(1, 5)
                                         for c in combinations(OPERATIONS, n)])
def test_purchase_groups_follow_only_current_station_operations(operations):
    project = station_project(operations)
    original = deepcopy(project)
    rows = procurement.initial_procurement_rows(project)
    assert project == original
    assert len(rows) == 2 * len(operations)
    assert len({row['group_id'] for row in rows}) == len(rows)
    assert {cid for row in rows for cid in row['component_ids']} == set(operations)
    assert all(row['group_id'].startswith('bench-') and row['is_candidate'] for row in rows)
    assert all(row['quantity'] == 1 and row['line_total'] is None for row in rows)
    assert not ({'pipette', 'controller', 'upstream-platform'} &
                {row['group_id'] for row in rows})


def test_only_reviewed_camera_candidate_can_fetch_catalog(monkeypatch):
    project = station_project()
    original = deepcopy(project)
    calls = []

    async def unavailable(product, client):
        calls.append(product.option_id)
        raise procurement.CatalogError('Offline synthetic unavailable catalog')

    monkeypatch.setattr(procurement, 'fetch_product', unavailable)
    monkeypatch.setattr(procurement, '_cache', {})
    report = asyncio.run(procurement.refresh_procurement(project))
    assert calls == ['camera-module-3']
    assert project == original
    assert report['incomplete'] and report['known_partial_subtotal'] == 0
    assert report['coverage']['supported_catalog_count'] == 1
    assert all(row['line_total'] is None for row in report['rows'])
    for row in report['rows']:
        if row['group_id'] in {'bench-weigh-equipment', 'bench-print_label-equipment',
                               'bench-read_barcode-equipment'}:
            assert row['status'] == 'quote_needed'
            assert row['freshness'] == 'unverified'


def test_station_allowances_use_one_bounded_call_and_exclude_legacy_bom():
    project = station_project(['weigh', 'print_label'])
    original = deepcopy(project)
    result, calls = estimate(project)
    assert project == original and len(calls) == 1
    inputs = json.loads(calls[0]['messages'][1]['content'])
    assert {r['group_id'] for r in inputs['rows']} == {
        'bench-weigh-equipment', 'bench-weigh-supplies',
        'bench-print_label-equipment', 'bench-print_label-supplies',
    }
    assert all(row['allowance_basis']['understood'] for row in inputs['rows'])
    assert all(row['is_candidate'] for row in inputs['rows'])
    assert result['status'] == 'ready'
    assert result['summary']['project_total_low_usd'] == 40
    assert result['summary']['project_total_high_usd'] == 100
    assert all(row['price_source_url'] is None for row in result['rows'])
    assert prices.estimate_for_project(project, result) == result
    revised = deepcopy(project)
    revised['revision'] += 1
    revised['bench_station'] = compile_station(StationProposal(operations=['inspect']))
    assert prices.estimate_for_project(revised, result) is None


def test_station_provider_failure_never_becomes_a_zero_cost_quote():
    project = station_project(['read_barcode'])
    result, calls = estimate(project, http_status=503)
    assert len(calls) == 1 and result['status'] == 'failed'
    assert result['summary']['project_total_low_usd'] is None
    assert result['summary']['project_total_high_usd'] is None
    assert all(row['low_usd'] is None and row['high_usd'] is None for row in result['rows'])
