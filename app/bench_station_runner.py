"""Standalone operator-assisted record runner. Requires Python 3; no hardware commands.

Usage: python run.py --plan plan.json --output record.json
Offline check: python run.py --plan plan.json --output check.json --dry-run
Printable label: add --label-output label.html (example 60 x 30 mm media).
Treat records as operator-entered observations, not validated instrument acquisition.
"""

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from html import escape
from pathlib import Path

OPERATIONS = {'weigh', 'print_label', 'read_barcode', 'inspect'}


def validate_plan(plan):
    """Accept only the versioned, ordered station proposal represented in the export."""
    if not isinstance(plan, dict):
        raise ValueError('Plan must be a JSON object.')
    station = plan.get('station', plan)
    if not isinstance(station, dict):
        raise ValueError('Station must be an object.')
    proposal = station.get('proposal', {})
    if not isinstance(proposal, dict) or proposal.get('schema_version') != '1':
        raise ValueError('Unsupported proposal schema.')
    operations = proposal.get('operations')
    if (not isinstance(operations, list) or not 1 <= len(operations) <= 4
            or any(not isinstance(op, str) or op not in OPERATIONS for op in operations)
            or len(set(operations)) != len(operations)):
        raise ValueError('Invalid operations.')
    modules = station.get('modules')
    if (not isinstance(modules, list)
            or any(not isinstance(module, dict) for module in modules)
            or [module.get('id') for module in modules] != operations):
        raise ValueError('Modules must match the ordered operations.')
    return operations


def nonempty(prompt, ask):
    value = ask(prompt).strip()
    if not value:
        raise ValueError('A nonempty operator response is required.')
    return value


def label_html(identifier):
    """Create escaped plain-text media, not a barcode or a printer command."""
    if (not 1 <= len(identifier) <= 80
            or any(ord(character) < 32 or ord(character) == 127 for character in identifier)):
        raise ValueError('Label identifier must contain 1–80 characters without controls.')
    return ('<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta http-equiv="Content-Security-Policy" '
            'content="default-src \'none\'; style-src \'unsafe-inline\'">'
            '<title>Printable identifier label</title><style>'
            '@page{size:60mm 30mm;margin:0}body{margin:0;font-family:sans-serif}'
            '.label{box-sizing:border-box;width:60mm;height:30mm;padding:3mm;'
            'border:1px solid black;display:flex;align-items:center;'
            'overflow-wrap:anywhere;font-size:9pt}.note{font-size:10pt}'
            '@media print{.note{display:none}}</style><div class="label">'
            + escape(identifier) + '</div><p class="note">'
            'Example 60 x 30 mm plain-text media. Print at 100% scale; verify fit, '
            'readability, adhesive and actual printer media before use. '
            'This file is not evidence of printing or application and contains no barcode.'
            '</p></html>')


def run_record(plan, ask=input, label_output=None, checkpoint=None):
    """Gather explicit human observations without claiming instrument connectivity."""
    operations = validate_plan(plan)
    fingerprint = hashlib.sha256(json.dumps(
        plan, sort_keys=True, separators=(',', ':'), allow_nan=False
    ).encode()).hexdigest()
    record = {
        'schema_version': '1', 'mode': 'operator_assisted_no_hardware_control',
        'plan_sha256': fingerprint, 'project_id': plan.get('project_id'),
        'revision': plan.get('revision'),
        'operator': nonempty('Operator identifier: ', ask),
        'sample_id': nonempty('Item/sample identifier: ', ask), 'events': [],
    }
    label_html(record['sample_id'])  # Validate bounded printable identity before side effects.
    record['status'] = 'in_progress'
    if checkpoint:
        checkpoint(record)
    for index, operation in enumerate(operations):
        event = {'sequence': index + 1, 'operation': operation,
                 'provenance': 'operator_entered'}
        if index:
            if ask('Confirm manual handoff with item identity preserved [yes]: ').strip() != 'yes':
                raise ValueError('Manual handoff was not confirmed.')
        if operation == 'weigh':
            mass = float(nonempty('Stable balance reading in grams (g): ', ask))
            if not math.isfinite(mass) or mass < 0:
                raise ValueError('Mass must be a finite nonnegative value in grams.')
            event.update(mass=mass, unit='g', acquisition='manual transcription')
        elif operation == 'print_label':
            event['label_text'] = record['sample_id']
            if label_output is not None:
                content = label_html(record['sample_id'])
                with Path(label_output).open('x', encoding='utf-8') as label:
                    label.write(content)
                event['label_artifact'] = {
                    'path': str(Path(label_output).resolve()), 'format': 'html_plain_text',
                    'sha256': hashlib.sha256(content.encode()).hexdigest(),
                    'example_media_mm': [60, 30], 'printed_and_applied': False,
                }
                # Persist artifact provenance before requesting any physical confirmation.
                record['pending_event'] = event
                if checkpoint:
                    checkpoint(record)
            else:
                entered = nonempty('Exact text manually printed/applied: ', ask)
                if entered != record['sample_id']:
                    raise ValueError('Label text must match the item/sample identifier.')
            if ask('Confirm label is printed, applied and readable [yes]: ').strip() != 'yes':
                raise ValueError('Label check was not confirmed.')
            if 'label_artifact' in event:
                event['label_artifact']['printed_and_applied'] = True
            record.pop('pending_event', None)
            event['acquisition'] = 'operator confirmation; printing performed separately'
        elif operation == 'read_barcode':
            decoded = nonempty('Scan with keyboard/HID reader or enter decoded barcode: ', ask)
            if decoded != record['sample_id']:
                raise ValueError('Barcode does not match the item/sample identifier; stop.')
            event.update(decoded_value=decoded, acquisition='keyboard/HID or manual input')
        else:
            event['criteria'] = nonempty('Predefined visible inspection criteria: ', ask)
            outcome = nonempty('Human review outcome [pass/fail]: ', ask)
            if outcome not in ('pass', 'fail'):
                raise ValueError('Review outcome must be pass or fail.')
            event.update(outcome=outcome, notes=nonempty('Review notes: ', ask))
        event['recorded_at_utc'] = datetime.now(timezone.utc).isoformat()
        record['events'].append(event)
        if checkpoint:
            checkpoint(record)
        if event.get('outcome') == 'fail':
            record['status'] = 'stopped_on_failed_inspection'
            return record
    record['status'] = 'operator_sequence_complete'
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--label-output', type=Path,
                        help='New printable plain-text HTML file; example 60 x 30 mm media.')
    parser.add_argument('--dry-run', action='store_true',
                        help='Validate plan and write pending human checkpoints; no observations.')
    args = parser.parse_args()
    try:
        # Refuse to replace any existing record or plan before collecting observations.
        if args.output.exists() or args.output.resolve() == args.plan.resolve():
            raise ValueError('Choose a new output filename; existing files are never replaced.')
        plan = json.loads(args.plan.read_text(encoding='utf-8'))
        operations = validate_plan(plan)
        if args.label_output is not None:
            if (args.dry_run or 'print_label' not in operations
                    or args.label_output.suffix.lower() != '.html'):
                raise ValueError('Label output requires print_label, .html and an interactive run.')
            if (args.label_output.exists() or args.label_output.resolve() in
                    (args.output.resolve(), args.plan.resolve())):
                raise ValueError('Label path must be new and distinct from plan and record.')
        if args.dry_run:
            operations = validate_plan(plan)
            record = {
                'schema_version': '1', 'mode': 'dry_run_no_observations',
                'project_id': plan.get('project_id'), 'revision': plan.get('revision'),
                'status': 'not_executed', 'events': [],
                'pending_human_checkpoints': [
                    {'sequence': index + 1, 'operation': operation,
                     'requires_manual_handoff': index > 0}
                    for index, operation in enumerate(operations)
                ],
            }
        else:
            # Reserve record first so a later abort cannot leave an untracked label artifact.
            with args.output.open('x+', encoding='utf-8') as output:
                latest = {'status': 'started_no_observations', 'events': []}

                def save_checkpoint(record):
                    nonlocal latest
                    latest = record
                    output.seek(0)
                    json.dump(record, output, indent=2, allow_nan=False)
                    output.write('\n')
                    output.truncate()
                    output.flush()

                try:
                    save_checkpoint(latest)
                    record = run_record(plan, label_output=args.label_output,
                                        checkpoint=save_checkpoint)
                    save_checkpoint(record)
                except (ValueError, OSError, EOFError, KeyboardInterrupt) as exc:
                    latest['status'] = 'aborted'
                    latest['error'] = str(exc) or 'Operator interrupted the run.'
                    save_checkpoint(latest)
                    parser.exit(1, f'Run stopped; partial record retained at '
                                f'{args.output}: {exc}\n')
            return
        with args.output.open('x', encoding='utf-8') as output:
            json.dump(record, output, indent=2, allow_nan=False)
            output.write('\n')
    except (ValueError, OSError, EOFError) as exc:
        parser.exit(1, f'Record not saved: {exc}\n')


if __name__ == '__main__':
    main()
