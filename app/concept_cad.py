"""Editable STEP exports of the canonical conceptual assembly.

Coordinates are millimetres with Y up, matching the viewer and STL. The model
represents proposed primitive solids; it is not a toleranced fabrication drawing.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock

from app.concept_design import compile_concept

# Boolean operations grow rapidly with solid count. Bound a single request and
# never start an unbounded BRep generation as part of the standard ZIP export.
MAX_STEP_PRIMITIVES = 200
_CAD_LOCK = Lock()


class ConceptCADUnavailable(RuntimeError):
    """The optional CAD dependency is not installed."""


def concept_step(design: dict, component_key: str | None = None) -> bytes:
    """Export a named assembly in world coordinates, or one part in local coordinates."""
    canonical = compile_concept(design['proposal'], design.get('workspace_width_mm'))
    components = canonical['components']
    if component_key is not None:
        components = [component for component in components if component['key'] == component_key]
        if not components:
            raise ValueError('Unknown component model key.')
    count = sum(len(component['primitives']) for component in components)
    if count > MAX_STEP_PRIMITIVES:
        raise ValueError(f'STEP export supports up to {MAX_STEP_PRIMITIVES} primitives per file.')
    # Only geometry and component names affect this output, not user history or prices.
    data = [{'key': c['key'], 'name': c['name'], 'position_mm': c['position_mm'],
             'primitives': c['primitives']} for c in components]
    encoded = json.dumps(data, sort_keys=True, separators=(',', ':'))
    return _render_step(encoded, component_key is None)


@lru_cache(maxsize=4)
def _render_step(encoded: str, world_coordinates: bool) -> bytes:
    # Serialize native CAD operations so concurrent downloads cannot multiply
    # their memory cost or contend in the underlying STEP writer.
    with _CAD_LOCK:
        return _write_step(encoded, world_coordinates)


def _write_step(encoded: str, world_coordinates: bool) -> bytes:
    try:
        from build123d import Align, Box, Compound, Cylinder, Pos, Rot, Sphere, Unit, export_step
    except ImportError as exc:
        raise ConceptCADUnavailable('STEP export requires the optional CAD installation.') from exc

    components = json.loads(encoded)
    groups = []
    for component in components:
        parts = []
        offset = component['position_mm'] if world_coordinates else [0, 0, 0]
        for primitive in component['primitives']:
            sx, sy, sz = primitive['size_mm']
            x, y, z = [a + b for a, b in zip(primitive['center_mm'], offset)]
            if primitive['shape'] == 'box':
                shape = Box(sx, sy, sz, align=(Align.CENTER,) * 3)
            elif primitive['shape'] == 'cylinder':
                shape = Rot(90, 0, 0) * Cylinder(sx / 2, sy, align=(Align.CENTER,) * 3)
            elif primitive['shape'] == 'sphere':
                shape = Sphere(sx / 2)
            else:
                raise ValueError('Unsupported conceptual solid.')
            parts.append(Pos(x, y, z) * shape)
        # Each component remains a named item. Fuse its intersecting/touching
        # solids when possible; leave disconnected shapes together as a compound.
        if len(parts) == 1:
            body = parts[0]
        else:
            try:
                body = parts[0].fuse(*parts[1:])
                if body is None or not body.is_valid or not body.solids():
                    raise ValueError('Invalid boolean result')
            except Exception:
                body = Compound(children=parts)
        body.label = component['name']
        groups.append(body)
    assembly = Compound(children=groups, label='MuseAutoLab concept')
    with TemporaryDirectory(prefix='muse-concept-step-') as temporary:
        path = Path(temporary) / 'concept.step'
        if not export_step(assembly, path, unit=Unit.MM):
            raise RuntimeError('The STEP model could not be exported.')
        return path.read_bytes()
