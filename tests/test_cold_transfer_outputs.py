"""Canonical cold-transfer guidance and lightweight STEP serialization checks."""
import json
from copy import deepcopy
from html import escape

import pytest
from build123d import export_step, import_step
from evolution_fixtures import inspection_proposal
from test_cold_transfer import plate_project

from app.assembly import build_document_files, build_extension_plan
from app.cad_exports import _bbox_of, _build_solid, _components
from app.cold_transfer import apply_cold_transfer
from app.inspection import apply_extension
from app.instructions import build_instruction_guide


def test_instruction_downloads_include_canonical_hardware_and_separate_manual_bay():
    project = apply_cold_transfer(plate_project())
    guide = build_instruction_guide(project)
    step = next(s for s in guide['steps'] if s['id']=='cold-transfer-extension')
    assert step['component_ids'] == project['cold_transfer_extension']['component_ids']
    assert step['requires_design']
    guidance = ' '.join(step['instructions'])
    assert 'Parts & prices lists candidate hardware' in guidance
    assert 'obtain a supplier quote' in guidance
    files = build_document_files(project)
    component_names = {part['id']: part['label'] for part in project['design']['components']}
    for filename in ('assembly-guide.html','assembly-guide.md','assembly.json'):
        text = files[filename].decode('utf-8')
        for component in ('cold-transfer-fridge', 'cold-transfer-gripper'):
            if filename.endswith('.html'):
                assert escape(component_names[component]) in text
                assert component not in text
            else:
                assert component in text
        assert 'separate' in text
        assert 'manual-access' in text
    assert json.loads(files['assembly.json'])['project_revision'] == project['revision']


def test_mixed_extension_plan_preserves_inspection_and_cooling_contract():
    project = apply_cold_transfer(apply_extension(plate_project(), inspection_proposal(), {}))
    plan = json.loads(build_extension_plan(project))
    assert plan['inspection_extension'] == project['inspection_extension']
    assert plan['cold_transfer_extension'] == project['cold_transfer_extension']
    assert plan['cooling_transfer_mode'] == 'digital_cold_transfer_concept'
    assert plan['on_deck_cold_bay_transfer_mode'] == 'manual'
    assert not plan['installed']


def test_actual_cold_part_step_reimports_preserve_geometry(tmp_path):
    project = apply_cold_transfer(plate_project())
    parts = _components(project)
    ids = project['cold_transfer_extension']['component_ids']
    cold = [part for part in parts if part['id'] in ids]
    assert len(cold) == len(ids)
    for part in cold:
        solid = _build_solid(part)
        assert solid.is_valid and solid.volume > 0
        path = tmp_path / (part['id']+'.step')
        export_step(solid, path)
        restored = import_step(path)
        assert restored.is_valid
        assert restored.volume == pytest.approx(solid.volume, rel=1e-8)
        assert _bbox_of(restored)['size'] == pytest.approx(_bbox_of(solid)['size'], abs=1e-6)


def test_cad_rejects_cold_primitive_tampering_before_building():
    project = apply_cold_transfer(plate_project())
    bad = deepcopy(project)
    part = next(p for p in bad['design']['components'] if p['id']=='cold-transfer-fridge')
    part['geometry']['primitives'][0]['size'][0] -= 1
    with pytest.raises(ValueError, match='canonical compiler'):
        _components(bad)


def test_actual_instruction_api_and_downloads_use_same_revision():
    from app import api
    project = apply_cold_transfer(plate_project())
    api._sessions[project['id']] = api.ProjectSession(project=project)
    def resolve(coroutine):
        try:
            coroutine.send(None)
        except StopIteration as result:
            return result.value
        raise AssertionError('Unexpected blocking operation in deterministic instructions')
    guide = resolve(api.get_instructions(project['id'],project['revision']))
    step = next(s for s in guide['steps'] if s['id']=='cold-transfer-extension')
    assert step['component_ids'] == project['cold_transfer_extension']['component_ids']
    component_names = {part['id']: part['label'] for part in project['design']['components']}
    for kind in ('html','md','json'):
        response = resolve(api.download_instructions(project['id'],project['revision'],kind))
        assert response.status_code == 200
        for component in ('cold-transfer-shaft', 'cold-transfer-fridge', 'cold-transfer-gripper'):
            if kind == 'html':
                assert escape(component_names[component]).encode() in response.body
                assert component.encode() not in response.body
            else:
                assert component.encode() in response.body
        if kind == 'json':
            exported = json.loads(response.body)
            assert exported['project_revision'] == project['revision']
            exported_step = next(s for s in exported['steps'] if s['id'] == step['id'])
            assert exported_step['component_ids'] == step['component_ids']
