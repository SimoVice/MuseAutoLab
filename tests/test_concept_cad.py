"""STEP keeps curved, concave and attached components faithful to the concept."""
import builtins
import math

import pytest

pytest.importorskip('build123d')
from build123d import import_step  # noqa: E402

from app.concept_cad import (  # noqa: E402
    MAX_STEP_PRIMITIVES,
    ConceptCADUnavailable,
    _render_step,
    concept_step,
)
from app.concept_design import compile_concept  # noqa: E402


def proposal():
    return {
        'title': 'Optical assembly', 'overview': 'Inspect a sample.',
        'components': [
            {'key': 'frame', 'name': 'Open frame', 'role': 'Support optics.',
             'source_id': None, 'assembly': 'Place frame.', 'check': 'Inspect frame.',
             'primitives': [
                 {'shape': 'box', 'size_mm': [100, 10, 80], 'center_mm': [0, 5, 0],
                  'finish': 'frame'},
                 {'shape': 'box', 'size_mm': [10, 60, 10], 'center_mm': [-45, 35, -35],
                  'finish': 'frame'},
                 {'shape': 'box', 'size_mm': [10, 60, 10], 'center_mm': [45, 35, -35],
                  'finish': 'frame'}]},
            {'key': 'optic', 'name': 'Round optic', 'role': 'Inspect the sample.',
             'source_id': None, 'assembly': 'Fit optic.', 'check': 'Review alignment.',
             'parent_key': 'frame', 'placement_mm': [0, 30, 0],
             'primitives': [{'shape': 'sphere', 'size_mm': [20, 20, 20],
                             'center_mm': [0, 10, 0], 'finish': 'clear'}]},
            {'key': 'rod', 'name': 'Upright rod', 'role': 'Provide support.', 'source_id': None,
             'assembly': 'Position rod.', 'check': 'Review fit.',
             'primitives': [{'shape': 'cylinder', 'size_mm': [20, 60, 20],
                             'center_mm': [0, 30, 0], 'finish': 'steel'}]},
        ],
        'steps': [{'name': 'Review', 'instruction': 'Review fit.', 'component_keys': ['frame'],
                   'moving_key': None, 'translation_mm': [0, 0, 0]}],
        'software': {'controller': 'Select a controller.', 'interfaces': [],
                     'setup': ['Review the design.'], 'checks': ['Check alignment.']},
        'open_questions': [],
    }


def imported(tmp_path, data, name='model.step'):
    path = tmp_path / name
    path.write_bytes(data)
    shape = import_step(path)
    assert shape.is_valid
    return shape


def xyz(v):
    return (v.X, v.Y, v.Z)


def test_part_local_frame_is_fused_but_open(tmp_path):
    design = compile_concept(proposal())
    shape = imported(tmp_path, concept_step(design, 'frame'))
    bounds = shape.bounding_box()
    assert xyz(bounds.min) == pytest.approx((-50, 0, -40), abs=1e-5)
    assert xyz(bounds.max) == pytest.approx((50, 65, 40), abs=1e-5)
    assert shape.volume == pytest.approx(91000, rel=1e-6)
    assert len(shape.solids()) == 1
    assert shape.volume < bounds.size.X * bounds.size.Y * bounds.size.Z / 2


def test_assembly_has_named_world_placed_components_and_curves(tmp_path):
    design = compile_concept(proposal())
    shape = imported(tmp_path, concept_step(design))
    assert len(shape.solids()) == 3
    names = {item.label for item in shape.children}
    assert {'Open_frame', 'Round_optic', 'Upright_rod'} <= names
    minimum = [min(c['position_mm'][i] + c['bounds_mm']['min'][i]
                   for c in design['components']) for i in range(3)]
    maximum = [max(c['position_mm'][i] + c['bounds_mm']['max'][i]
                   for c in design['components']) for i in range(3)]
    assert xyz(shape.bounding_box().min) == pytest.approx(minimum, abs=1e-5)
    assert xyz(shape.bounding_box().max) == pytest.approx(maximum, abs=1e-5)
    optic = imported(tmp_path, concept_step(design, 'optic'), 'optic.step')
    rod = imported(tmp_path, concept_step(design, 'rod'), 'rod.step')
    assert xyz(optic.bounding_box().size) == pytest.approx((20, 20, 20), abs=1e-5)
    assert optic.volume == pytest.approx(4 / 3 * math.pi * 10 ** 3, rel=1e-6)
    assert xyz(rod.bounding_box().size) == pytest.approx((20, 60, 20), abs=1e-5)
    assert rod.volume == pytest.approx(math.pi * 10 ** 2 * 60, rel=1e-6)


def test_unknown_part_and_oversized_export_are_rejected(monkeypatch):
    design = compile_concept(proposal())
    with pytest.raises(ValueError, match='Unknown component'):
        concept_step(design, 'missing')
    monkeypatch.setattr('app.concept_cad.MAX_STEP_PRIMITIVES', 2)
    with pytest.raises(ValueError, match='STEP export supports'):
        concept_step(design)
    assert MAX_STEP_PRIMITIVES > 2


def test_missing_optional_cad_has_clear_error(monkeypatch):
    design = compile_concept(proposal())
    original_import = builtins.__import__

    def without_cad(name, *args, **kwargs):
        if name == 'build123d':
            raise ImportError('not installed')
        return original_import(name, *args, **kwargs)

    _render_step.cache_clear()
    monkeypatch.setattr(builtins, '__import__', without_cad)
    with pytest.raises(ConceptCADUnavailable, match='optional CAD'):
        concept_step(design)
