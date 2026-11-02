"""Canonical non-liquid planning checks, independent of model inference."""

from copy import deepcopy
from itertools import combinations, permutations
from xml.etree import ElementTree

import pytest
from pydantic import ValidationError

from app.bench_station import StationProposal, compile_station, station_svg

OPERATIONS = ['weigh', 'print_label', 'read_barcode', 'inspect']


@pytest.mark.parametrize('operations', [[], ['weigh', 'weigh'], ['pipette'],
                                       OPERATIONS + ['weigh']])
def test_invalid_selection(operations):
    with pytest.raises(ValidationError):
        StationProposal(operations=operations)


@pytest.mark.parametrize('width', [0, -10, float('nan'), float('inf'), True, '400', 299])
def test_invalid_or_insufficient_width_rejected(width):
    with pytest.raises(ValueError):
        compile_station(StationProposal(operations=['weigh']), width)


def test_schema_rejects_unrecognized_fields_and_versions():
    with pytest.raises(ValidationError):
        StationProposal(operations=['weigh'], schema_version='2')
    with pytest.raises(ValidationError):
        StationProposal(operations=['weigh'], automatic=True)


@pytest.mark.parametrize('operations', list(permutations(OPERATIONS)))
def test_ordered_packing_has_nonoverlapping_functional_surfaces(operations):
    proposal = StationProposal(operations=list(operations))
    original = deepcopy(proposal.model_dump())
    station = compile_station(proposal, 760)
    assert station['proposal'] == original == proposal.model_dump()
    assert [m['id'] for m in station['modules']] == list(operations)
    assert station['footprint_mm'][0] <= 760
    for first, second in combinations(station['modules'], 2):
        ax, ay, aw, ad = first['functional_surface_mm']
        bx, by, bw, bd = second['functional_surface_mm']
        assert ax + aw <= bx or bx + bw <= ax or ay + ad <= by or by + bd <= ay
    for module in station['modules']:
        x, h, z = module['position_mm']
        w, height, d = module['size_mm']
        sx, sy, sw, sd = module['functional_surface_mm']
        assert sx < x - w / 2 < x + w / 2 < sx + sw
        assert sy < z - d / 2 < z + d / 2 < sy + sd
        assert h == height / 2
    assert station == compile_station(proposal, 760)
    assert sum('Manually transfer' in step for step in station['steps']) == 3


def test_revision_recompiles_workflow_and_parts_without_stale_operations():
    old = compile_station(StationProposal(operations=OPERATIONS))
    snapshot = deepcopy(old)
    new = compile_station(StationProposal(operations=['inspect', 'read_barcode']), 400)
    assert old == snapshot
    assert new['footprint_mm'] == [400, 760]
    assert {p['operation'] for p in new['parts']} == {'inspect', 'read_barcode'}
    assert not any('balance' in step or 'print one' in step for step in new['steps'])
    assert all(p['price_usd'] is None for p in new['parts'])
    assert all(m['guidance'] and m['role'] for m in new['modules'])
    assert all(p['source_url'].startswith('https://')
               for p in new['parts'] if p['source_url'])


def test_dimensioned_svg_is_standalone_and_matches_compiled_geometry():
    station = compile_station(StationProposal(operations=['read_barcode', 'weigh']))
    root = ElementTree.fromstring(station_svg(station))
    text = ' '.join(root.itertext())
    width, depth = station['footprint_mm']
    assert f'{width:g} mm' in text and f'{depth:g} mm' in text
    assert all(m['label'] in text for m in station['modules'])
    assert 'Concept only' in text
    assert root.attrib['width'].endswith('mm')
