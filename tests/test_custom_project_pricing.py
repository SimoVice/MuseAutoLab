"""Offline independent purchase scopes, quantities and safe custom-project pricing."""

import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from test_custom_project_routes import client as client
from test_custom_project_routes import install, project_fixture, proposal
from test_price_estimation import estimate, response_rows

import app.api as api
from app import price_estimation as prices
from app import procurement
from app.concept_design import compile_concept


def modified_project(project, change):
    updated = deepcopy(project)
    raw = deepcopy(updated['concept_design']['proposal'])
    change(raw)
    updated['concept_design'] = compile_concept(raw, 600)
    updated['revision'] += 1
    return updated


def supplier_fixture(monkeypatch):
    calls = []

    async def fetch(product, client):
        calls.append(product.option_id)
        return {
            'product_name': 'Synthetic offline ' + product.option_id,
            'availability': 'InStock', 'source_url': product.url,
            'fetched_at': datetime.now(UTC).isoformat(), 'evidence_sha256': '0' * 64,
            'parser': 'synthetic-test-only',
            'price_breaks': [{'minimum_packs': 1, 'pack_price': '7.50'}],
        }

    monkeypatch.setattr(procurement, 'fetch_product', fetch)
    monkeypatch.setattr(procurement, '_cache', {})
    return calls


def test_generic_parts_have_no_legacy_pipetting_bom_and_correct_supply_quantities():
    project = project_fixture()
    original = deepcopy(project)
    rows = procurement.initial_procurement_rows(project)
    assert project == original
    assert len(rows) == 4
    assert {row['group_id'] for row in rows} == {
        'concept-rail_base', 'concept-sample_tray', 'concept-controller_board',
        'concept-drive_motor'}
    assert all(row['is_candidate'] for row in rows)
    controller = next(r for r in rows if r['group_id'] == 'concept-controller_board')
    motor = next(r for r in rows if r['group_id'] == 'concept-drive_motor')
    assert controller['quantity'] == controller['pack_count'] == 3
    assert controller['catalog_supported'] and motor['catalog_supported']
    assert controller['selected_id'] == 'pico-h' and motor['selected_id'] == 'pololu-1209'
    assert motor['price_source_url'] == procurement.PRODUCTS['pololu-1209'].url


def test_observed_pack_totals_use_declared_quantity_without_second_multiplication(monkeypatch):
    project = project_fixture()
    calls = supplier_fixture(monkeypatch)
    monkeypatch.setitem(procurement.PRODUCTS, 'pico-h',
                        replace(procurement.PRODUCTS['pico-h'], pack_size=2))
    report = asyncio.run(procurement.refresh_procurement(project))
    assert sorted(calls) == ['pico-h', 'pololu-1209']
    controller = next(r for r in report['rows'] if r['group_id'] == 'concept-controller_board')
    assert controller['quantity'] == 3 and controller['pack_count'] == 2
    assert controller['pack_price'] == 7.5 and controller['line_total'] == 15
    assert report['known_partial_subtotal'] == 22.5
    result, requests = estimate(project, report=report)
    assert len(requests) == 1
    provider = json.loads(requests[0]['messages'][1]['content'])
    assert {row['group_id'] for row in provider['rows']} == {
        'concept-rail_base', 'concept-sample_tray'}
    assert result['summary']['project_total_low_usd'] == 42.5
    assert result['summary']['project_total_high_usd'] == 72.5


def test_unobserved_model_ranges_are_entire_group_totals_not_per_board():
    project = project_fixture()
    result, calls = estimate(project)
    assert len(calls) == 1 and result['status'] == 'ready'
    assert result['summary']['project_total_low_usd'] == 40
    assert result['summary']['project_total_high_usd'] == 100
    payload = json.loads(calls[0]['messages'][1]['content'])
    controller = next(r for r in payload['rows'] if r['group_id'] == 'concept-controller_board')
    assert controller['quantity'] == 3
    assert controller['price_basis'] == 'group_total'
    assert all(row['price_source_url'] is None for row in result['rows'])


def test_pose_assembly_prose_and_illustrative_finish_preserve_purchase_scope():
    project = project_fixture()

    def edit(raw):
        raw['components'][1]['assembly'] = 'Improve the descriptive assembly directions.'
        raw['components'][1]['placement_mm'] = [10, 10, 0]
        raw['components'][1]['primitives'][0]['finish'] = 'accent'

    updated = modified_project(project, edit)
    before = {r['group_id']: procurement.purchase_scope(project, r)
              for r in procurement.initial_procurement_rows(project)}
    after = {r['group_id']: procurement.purchase_scope(updated, r)
             for r in procurement.initial_procurement_rows(updated)}
    assert before == after


@pytest.mark.parametrize('change,changed_group', [
    (lambda p: p['supplies'][0].update(quantity=4), 'concept-controller_board'),
    (lambda p: p['supplies'][0].update(source_id='pico'), 'concept-controller_board'),
    (lambda p: p['components'][1]['primitives'][0].update(size_mm=[60, 8, 50]),
     'concept-sample_tray'),
])
def test_revisions_invalidate_only_changed_purchase_scopes(monkeypatch, change, changed_group):
    project = project_fixture()
    supplier_fixture(monkeypatch)
    report = asyncio.run(procurement.refresh_procurement(project))
    ranges, _ = estimate(project, report=report)
    updated = modified_project(project, change)
    rebound = procurement.rebind_report(project, updated, report)
    assert rebound['project_revision'] == updated['revision']
    assert rebound['fetched_at'] == report['fetched_at']
    assert rebound['expires_at'] == report['expires_at']
    assert changed_group not in rebound['revision_binding']['retained_group_ids']
    assert procurement.report_for_project(updated, report) is None
    revised_estimate = prices.rebind_estimate(project, updated, ranges, report, rebound)
    assert revised_estimate['project_revision'] == updated['revision']
    assert changed_group in revised_estimate['pending_scope_group_ids']
    assert revised_estimate['expires_at'] == ranges['expires_at']


def test_estimates_preserve_unchanged_scopes_across_pose_only_revision(monkeypatch):
    project = project_fixture()
    supplier_fixture(monkeypatch)
    report = asyncio.run(procurement.refresh_procurement(project))
    ranges, _ = estimate(project, report=report)
    updated = modified_project(project, lambda p: p['components'][1].update(
        placement_mm=[10, 10, 0], assembly='Fit and check the revised position.'))
    rebound = procurement.rebind_report(project, updated, report)
    retained = prices.rebind_estimate(project, updated, ranges, report, rebound)
    assert retained['pending_scope_group_ids'] == []
    assert retained['summary'] == ranges['summary']
    assert retained['expires_at'] == ranges['expires_at']


def test_provider_failure_retains_unknown_prices_instead_of_free_parts():
    project = project_fixture()
    result, calls = estimate(project, http_status=503)
    assert len(calls) == 1 and result['status'] == 'failed'
    assert result['summary']['project_total_low_usd'] is None
    assert result['summary']['project_total_high_usd'] is None
    assert all(row['low_usd'] is None and row['high_usd'] is None for row in result['rows'])


@pytest.mark.parametrize('edit', [
    lambda rows: rows.append(deepcopy(rows[0])),
    lambda rows: rows.pop(),
    lambda rows: rows[0].update(low_usd=0),
    lambda rows: rows[0].update(low_usd=100, high_usd=10),
    lambda rows: rows[0].update(rationale='See https://invented.invalid/prices'),
])
def test_invalid_or_ambiguous_model_price_rows_fail_safely(edit):
    project = project_fixture()
    rows = response_rows(project)
    edit(rows)
    result, calls = estimate(project, rows=rows)
    assert len(calls) == 1
    assert result['status'] == 'failed'
    assert result['summary']['project_total_low_usd'] is None
    assert result['summary']['project_total_high_usd'] is None


def test_supplier_failure_is_not_a_quote_or_zero_price(monkeypatch):
    project = project_fixture()
    calls = []

    async def failing(product, client):
        calls.append(product.option_id)
        raise procurement.CatalogError('Synthetic inaccessible catalogue.')

    monkeypatch.setattr(procurement, 'fetch_product', failing)
    monkeypatch.setattr(procurement, '_cache', {})
    report = asyncio.run(procurement.refresh_procurement(project))
    assert sorted(calls) == ['pico-h', 'pololu-1209']
    assert report['known_partial_subtotal'] == 0 and report['incomplete']
    assert all(row['line_total'] is None for row in report['rows'])
    assert all(row['unit_price'] is None for row in report['rows'])


def test_sidecar_expiry_does_not_renew_during_generic_read(monkeypatch):
    project = project_fixture()
    supplier_fixture(monkeypatch)
    report = asyncio.run(procurement.refresh_procurement(project))
    original = deepcopy(report)
    now = datetime.fromisoformat(report['fetched_at'].replace('Z', '+00:00'))
    stale = procurement.report_for_project(project, report, now=now + timedelta(minutes=16))
    assert report == original
    assert stale['known_partial_subtotal'] == 0
    assert stale['stale_last_known_subtotal'] == 30
    assert stale['report_id'] == report['report_id']
    assert stale['expires_at'] == report['expires_at']


def test_refresh_api_is_explicit_revision_bound_and_uses_supply_quantities(client, monkeypatch):
    project = project_fixture()
    url = install(project)
    calls = supplier_fixture(monkeypatch)
    revision = project['revision']
    assert client.get(url + '/procurement', params={'revision': revision}).json()['report'] is None
    assert calls == []
    result = client.post(url + '/procurement/refresh', json={'project_revision': revision})
    assert result.status_code == 200, result.text
    report = result.json()['report']
    assert report['known_partial_subtotal'] == 30
    assert sorted(calls) == ['pico-h', 'pololu-1209']
    current = client.get(url + '/procurement', params={'revision': revision}).json()
    assert current['report'] == report
    assert len(calls) == 2
    query = {'revision': revision, 'report_id': report['report_id']}
    assert client.get(url + '/procurement/download', params=query).status_code == 200
    assert client.get(url + '/procurement/download', params={
        **query, 'report_id': 'unknown'}).status_code == 409
    assert client.post(url + '/procurement/refresh', json={
        'project_revision': revision - 1}).status_code == 409
    assert api._sessions[project['id']].project == project


def test_price_get_and_snapshot_never_trigger_estimation(client, monkeypatch):
    project = project_fixture()
    url = install(project)
    calls = []

    async def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError('Read must never invoke price model.')

    monkeypatch.setattr(prices, 'estimate_project_prices', forbidden)
    revision = project['revision']
    first = client.get(url + '/cost-estimate', params={'revision': revision})
    assert first.status_code == 200 and first.json()['state'] == 'not_estimated'
    saved = client.get(url + '/snapshot', params={'revision': revision})
    reopened = client.post('/api/projects/open', content=saved.content)
    assert reopened.status_code == 201
    assert calls == []


def test_generated_proposal_duplicate_supply_keys_are_rejected_before_pricing():
    p = proposal()
    p['supplies'][1]['key'] = p['supplies'][0]['key']
    with pytest.raises(ValueError, match='distinct and unique'):
        compile_concept(p)


def test_explicit_cost_post_is_cached_until_force_and_rejects_untrusted_payload(
        client, monkeypatch):
    project = project_fixture()
    url = install(project)
    ranges, _ = estimate(project)
    calls = []

    async def fake(project_copy, report, **kwargs):
        calls.append(deepcopy(project_copy))
        return deepcopy(ranges)

    monkeypatch.setattr(prices, 'estimate_project_prices', fake)
    revision = project['revision']
    first = client.post(url + '/cost-estimate', json={'project_revision': revision})
    assert first.status_code == 200 and first.json()['estimate']['status'] == 'ready'
    second = client.post(url + '/cost-estimate', json={'project_revision': revision})
    assert second.status_code == 200 and len(calls) == 1
    assert client.get(url + '/cost-estimate', params={
        'revision': revision}).json()['state'] == 'current'
    assert client.post(url + '/cost-estimate', json={
        'project_revision': revision, 'force': True}).status_code == 200
    assert len(calls) == 2
    for invalid in ({'project_revision': revision, 'force': 'true'},
                    {'project_revision': revision, 'model': 'unreviewed-model'},
                    {'project_revision': revision - 1}):
        assert client.post(url + '/cost-estimate', json=invalid).status_code in (409, 422)
    assert len(calls) == 2


def test_mid_estimate_revision_change_does_not_publish_stale_ranges(client, monkeypatch):
    project = project_fixture()
    url = install(project)
    ranges, _ = estimate(project)

    async def slow(project_copy, report, **kwargs):
        api._sessions[project['id']].project['revision'] += 1
        return deepcopy(ranges)

    monkeypatch.setattr(prices, 'estimate_project_prices', slow)
    result = client.post(url + '/cost-estimate', json={'project_revision': project['revision']})
    assert result.status_code == 409
    assert api._sessions[project['id']].cost_estimate is None


def test_same_runtime_reopen_retains_observation_times_without_fetch_or_inference(
        client, monkeypatch):
    project = project_fixture()
    url = install(project)
    calls = supplier_fixture(monkeypatch)
    report = asyncio.run(procurement.refresh_procurement(project))
    ranges, _ = estimate(project, report=report)
    session = api._sessions[project['id']]
    session.procurement_report, session.cost_estimate = report, ranges
    saved = client.get(url + '/snapshot', params={'revision': project['revision']})
    assert 'known_partial_subtotal' not in saved.text
    reopened = client.post('/api/projects/open', content=saved.content)
    assert reopened.status_code == 201
    restored = api._sessions[reopened.json()['project']['id']]
    assert restored.procurement_report['report_id'] == report['report_id']
    assert restored.procurement_report['fetched_at'] == report['fetched_at']
    assert restored.procurement_report['expires_at'] == report['expires_at']
    assert restored.cost_estimate['estimate_id'] == ranges['estimate_id']
    assert restored.cost_estimate['expires_at'] == ranges['expires_at']
    assert len(calls) == 2


def test_modeled_purchase_is_counted_once_and_declared_spares_are_additional():
    from app.concept_design import compile_concept

    raw = proposal()
    raw['components'][1]['source_id'] = 'pololu-1209'
    compiled = compile_concept(raw)
    assert [(part['key'], part['quantity']) for part in compiled['parts']
            if part['source_id'] == 'pololu-1209'] == [('sample_tray', 1)]
    raw['supplies'][1]['quantity'] = 3
    assert sum(part['quantity'] for part in compile_concept(raw)['parts']
               if part['source_id'] == 'pololu-1209') == 3
    raw['supplies'][1]['additional_to_modeled_parts'] = True
    assert sum(part['quantity'] for part in compile_concept(raw)['parts']
               if part['source_id'] == 'pololu-1209') == 4
