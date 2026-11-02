"""Operator runner records real entered values and rejects inconsistent input."""

import json

import pytest

from app.bench_station import StationProposal, compile_station
from app.bench_station_runner import label_html, main, run_record, validate_plan


def plan(operations):
    return {'project_id': 'synthetic-test', 'revision': 3,
            'station': compile_station(StationProposal(operations=operations))}


def responses(*values):
    iterator = iter(values)
    return lambda _: next(iterator)


def test_complete_assisted_sequence_preserves_provenance_order_and_identity():
    source = plan(['weigh', 'print_label', 'read_barcode', 'inspect'])
    record = run_record(source, responses(
        'test operator', 'SYNTHETIC-001', '2.5', 'yes', 'SYNTHETIC-001', 'yes',
        'yes', 'SYNTHETIC-001', 'yes', 'Readable text', 'pass', 'Synthetic exercise',
    ))
    assert record['project_id'] == 'synthetic-test' and record['revision'] == 3
    assert record['status'] == 'operator_sequence_complete'
    assert record['events'][0]['mass'] == 2.5
    assert record['events'][0]['unit'] == 'g'
    assert [e['sequence'] for e in record['events']] == [1, 2, 3, 4]
    assert all(e['provenance'] == 'operator_entered' for e in record['events'])
    assert len(record['plan_sha256']) == 64


@pytest.mark.parametrize('mass', ['nan', 'inf', '-1', 'unknown'])
def test_invalid_mass_is_never_recorded(mass):
    with pytest.raises(ValueError):
        run_record(plan(['weigh']), responses('operator', 'synthetic', mass))


def test_barcode_mismatch_stops_sequence():
    with pytest.raises(ValueError, match='does not match'):
        run_record(plan(['read_barcode']), responses('operator', 'synthetic', 'other'))


def test_failed_inspection_stops_before_next_operation():
    record = run_record(plan(['inspect', 'weigh']), responses(
        'operator', 'synthetic', 'Visible text', 'fail', 'Unreadable test label'))
    assert record['status'] == 'stopped_on_failed_inspection'
    assert len(record['events']) == 1


def test_handoff_requires_explicit_confirmation():
    with pytest.raises(ValueError, match='handoff'):
        run_record(plan(['weigh', 'inspect']), responses('operator', 'synthetic', '1', 'no'))


@pytest.mark.parametrize('source', [None, [], {}, {'station': []},
                                   {'proposal': {'schema_version': '2'}},
                                   {'proposal': {'schema_version': '1',
                                                 'operations': [['weigh']]}}])
def test_invalid_export_is_rejected(source):
    with pytest.raises(ValueError):
        validate_plan(source)


def test_inconsistent_module_sequence_is_rejected():
    source = plan(['weigh', 'inspect'])
    source['station']['modules'].reverse()
    with pytest.raises(ValueError, match='Modules'):
        validate_plan(source)


def test_cli_never_overwrites_existing_record(tmp_path, monkeypatch):
    existing = tmp_path / 'existing.json'
    existing.write_text('preserved synthetic fixture', encoding='utf-8')
    monkeypatch.setattr('sys.argv', ['run.py', '--plan', str(tmp_path / 'missing.json'),
                                    '--output', str(existing)])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert existing.read_text(encoding='utf-8') == 'preserved synthetic fixture'


def test_cli_dry_run_needs_no_sample_or_terminal_input(tmp_path, monkeypatch):
    source, target = tmp_path / 'plan.json', tmp_path / 'check.json'
    source.write_text(json.dumps(plan(['inspect', 'weigh'])), encoding='utf-8')
    monkeypatch.setattr('sys.argv', ['run.py', '--plan', str(source),
                                    '--output', str(target), '--dry-run'])
    main()
    record = json.loads(target.read_text(encoding='utf-8'))
    assert record['status'] == 'not_executed'
    assert record['events'] == []
    assert [c['operation'] for c in record['pending_human_checkpoints']] == ['inspect', 'weigh']


def test_html_label_escapes_identifier_and_never_claims_barcode():
    html = label_html('<script>alert("bad")</script>')
    assert '<script>' not in html
    assert '&lt;script&gt;' in html
    assert '60mm 30mm' in html
    assert 'contains no barcode' in html


@pytest.mark.parametrize('identifier', ['', 'A' * 81, 'A\nB', 'A\x00B', 'A\x7fB'])
def test_unsafe_or_unbounded_label_identifiers_rejected(identifier):
    with pytest.raises(ValueError):
        label_html(identifier)


def test_label_file_provenance_saved_before_physical_confirmation(tmp_path):
    target = tmp_path / 'label.html'
    snapshots = []
    with pytest.raises(ValueError, match='Label check'):
        run_record(plan(['print_label']), responses('operator', 'SYNTHETIC', 'no'),
                   label_output=target,
                   checkpoint=lambda r: snapshots.append(json.loads(json.dumps(r))))
    assert target.exists()
    artifact = snapshots[-1]['pending_event']['label_artifact']
    assert artifact['path'] == str(target.resolve())
    assert artifact['printed_and_applied'] is False
    assert len(artifact['sha256']) == 64


def test_label_output_never_overwrites_existing_file(tmp_path):
    target = tmp_path / 'label.html'
    target.write_text('preserved', encoding='utf-8')
    with pytest.raises(FileExistsError):
        run_record(plan(['print_label']), responses('operator', 'SYNTHETIC'),
                   label_output=target)
    assert target.read_text(encoding='utf-8') == 'preserved'


def test_cli_rejects_colliding_paths_before_any_artifact(tmp_path, monkeypatch):
    source, target = tmp_path / 'plan.json', tmp_path / 'record.html'
    source.write_text(json.dumps(plan(['print_label'])), encoding='utf-8')
    monkeypatch.setattr('sys.argv', ['run.py', '--plan', str(source), '--output', str(target),
                                    '--label-output', str(target)])
    with pytest.raises(SystemExit):
        main()
    assert not target.exists()


def test_cli_retains_partial_record_and_label_after_aborted_confirmation(tmp_path, monkeypatch):
    source, target = tmp_path / 'plan.json', tmp_path / 'record.json'
    label = tmp_path / 'label.html'
    source.write_text(json.dumps(plan(['print_label'])), encoding='utf-8')
    monkeypatch.setattr('sys.argv', ['run.py', '--plan', str(source), '--output', str(target),
                                    '--label-output', str(label)])
    original = run_record
    monkeypatch.setattr('app.bench_station_runner.run_record', lambda p, **kwargs: original(
        p, ask=responses('operator', 'SYNTHETIC', 'no'), **kwargs))
    with pytest.raises(SystemExit):
        main()
    record = json.loads(target.read_text(encoding='utf-8'))
    assert record['status'] == 'aborted'
    assert record['events'] == []
    assert record['pending_event']['label_artifact']['printed_and_applied'] is False
    assert label.exists()
