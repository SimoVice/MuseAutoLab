"""Compile a bounded, human-operated bench station from selected operations.

Envelopes are planning allocations, never manufacturer dimensions or fabrication CAD.
"""

import math
from html import escape
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Operation = Literal['weigh', 'print_label', 'read_barcode', 'inspect']


class StationProposal(BaseModel):
    model_config = ConfigDict(extra='forbid')

    schema_version: Literal['1'] = '1'
    operations: list[Operation] = Field(min_length=1, max_length=4)

    @field_validator('operations')
    @classmethod
    def unique_operations(cls, value):
        if len(value) != len(set(value)):
            raise ValueError('Select each operation only once.')
        return value


# size = width, height, depth; clearance = functional surface around the envelope.
MODULES = {
    'weigh': {
        'label': 'Weighing station', 'size': [240, 180, 300], 'clearance': 60,
        'role': 'Manually load and record mass on a selected balance.',
        'guidance': 'Use a rigid, level, vibration-free surface; establish required capacity '
        'and readability, calibrate and tare the selected balance before use.',
        'step': 'Place the item on the balance, wait for stability, and manually record mass '
        'against its identifier. Remove the item before proceeding.',
        'parts': ['Balance with capacity and readability to be specified',
                  'Compatible check mass and weighing vessel'],
    },
    'print_label': {
        'label': 'Label printing station', 'size': [220, 180, 260], 'clearance': 70,
        'role': 'Print and manually apply an identifier label.',
        'guidance': 'Select label material, adhesive and printer for the actual container '
        'and exposure conditions. Keep the front label exit and rear media access clear.',
        'step': 'Enter or verify the identifier, print one label and manually apply it '
        'without obscuring required markings. Check legibility and adhesion.',
        'parts': ['Desktop label printer with suitable media path',
                  'Application-compatible labels and optional ribbon'],
    },
    'read_barcode': {
        'label': 'Barcode reading station', 'size': [180, 220, 220], 'clearance': 60,
        'role': 'Present the identifier to a reader and verify the decoded value.',
        'guidance': 'Select supported barcode symbologies and an interface; test reading '
        'distance, orientation and representative labels under actual lighting.',
        'step': 'Manually present the barcode to the reader, compare the decoded value '
        'with the expected identifier, and stop on a mismatch or unreadable code.',
        'parts': ['Barcode reader supporting the required symbologies',
                  'Reader stand and compatible data connection'],
    },
    'inspect': {
        'label': 'Visual inspection station', 'size': [280, 360, 300], 'clearance': 60,
        'role': 'Capture a stationary view for human visual review.',
        'guidance': 'Specify the visible feature and acceptance criteria; select camera, '
        'lens and lighting, then verify field of view and focus using representative items.',
        'step': 'Place the item under the camera, capture a focused image, and have a '
        'person review it against predefined visible criteria; record the decision.',
        'parts': ['Camera and lens selected for required field of view',
                  'Compatible host, camera cable, lighting, adjustable stand and sample support'],
    },
}

SOURCES = {
    'weigh': ('OHAUS Scout SPX6201 AM (candidate; verify capacity/readability)',
              'https://us.ohaus.com/en-us/products/balances-scales/portable-balances/'
              'scout-spx/spx6201-am'),
    'print_label': ('Zebra ZD421 (candidate; verify media and configuration)',
                    'https://www.zebra.com/us/en/products/printers/desktop/'
                    'zd400-series/zd421.html'),
    'read_barcode': ('Zebra DS2278 (candidate; verify interface and symbologies)',
                     'https://www.zebra.com/us/en/products/scanners/'
                     'general-purpose-handheld-scanners/ds2200-series/ds2278.html'),
    'inspect': ('Adafruit Raspberry Pi Camera Module 3 Standard '
                '(candidate camera module only; host and stand required)',
                'https://www.adafruit.com/product/5657'),
}


def compile_station(proposal: StationProposal, workspace_width_mm=None) -> dict:
    """Pack functional surfaces in ordered rows, rejecting impossible bench widths."""
    proposal = StationProposal.model_validate(proposal)
    if workspace_width_mm is not None:
        if (isinstance(workspace_width_mm, bool)
                or not isinstance(workspace_width_mm, (int, float))
                or not math.isfinite(workspace_width_mm) or workspace_width_mm <= 0):
            raise ValueError('Workspace width must be a finite positive number in mm.')
    surfaces = [MODULES[op]['size'][0] + 2 * MODULES[op]['clearance']
                for op in proposal.operations]
    width_limit = workspace_width_mm if workspace_width_mm is not None else sum(surfaces)
    if max(surfaces) > width_limit:
        raise ValueError('Workspace width cannot fit a selected module and its functional surface.')
    modules, parts, steps = [], [], [
        'Before use, select equipment and verify bench depth, load capacity, power, '
        'connections and access. This layout contains no automated transport or control.'
    ]
    x = y = row_depth = width = 0
    for index, operation in enumerate(proposal.operations):
        spec = MODULES[operation]
        w, h, d = spec['size']
        margin = spec['clearance']
        surface_w, surface_d = w + 2 * margin, d + 2 * margin
        if x and x + surface_w > width_limit:
            y += row_depth
            x = row_depth = 0
        modules.append({
            'id': operation, 'label': spec['label'], 'size_mm': [w, h, d],
            'position_mm': [x + margin + w / 2, h / 2, y + margin + d / 2],
            'role': spec['role'], 'guidance': spec['guidance'],
            'functional_surface_mm': [x, y, surface_w, surface_d],
        })
        source_title, source_url = SOURCES[operation]
        parts.extend({'operation': operation, 'label': label,
                      'source_title': source_title if part_index == 0 else None,
                      'source_url': source_url if part_index == 0 else None,
                      'price_usd': None} for part_index, label in enumerate(spec['parts']))
        if index:
            steps.append(f'Manually transfer the item to the {spec["label"].lower()}; '
                         'preserve its identity and keep the next work surface clear.')
        steps.append(spec['step'])
        x += surface_w
        width = max(width, x)
        row_depth = max(row_depth, surface_d)
    return {
        'proposal': proposal.model_dump(mode='json'), 'footprint_mm': [width, y + row_depth],
        'modules': modules, 'parts': parts, 'steps': steps,
        'limitations': [
            'Conceptual equipment envelopes and separate functional surfaces only; '
            'dimensions are planning allocations, not vendor specifications or fabrication CAD.',
            'Only allocated rectangles are checked for fit and separation; actual equipment, '
            'cables, open covers, reach, safety and bench depth require verification.',
            'Manual handoffs and human decisions are required. No control integration, '
            'automatic data association, throughput or laboratory performance is validated.',
            'The plan contains sourcing candidates; live prices and model estimates are '
            'shown in the site pricing panel. Parts are selection requirements, not '
            'quotations or a complete procurement BOM; machine compatibility is unverified.',
            'Linked products are planning candidates. Their dimensions are not used in '
            'these conceptual envelopes; verify the selected configuration before procurement.',
        ],
    }


def station_svg(station: dict) -> str:
    """Return a standalone dimensioned top view of the canonical planning allocations."""
    width, depth = station['footprint_mm']
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width + 100}mm" '
           f'height="{depth + 120}mm" viewBox="-50 -60 {width + 100} {depth + 120}">',
           '<title>Conceptual bench station top view, dimensions in mm</title>',
           '<rect x="-50" y="-60" width="100%" height="100%" fill="white"/>',
           f'<path d="M0 -15 V-30 H{width} V-15 M-15 0 H-30 V{depth} H-15" '
           'fill="none" stroke="#334155" stroke-width="1"/>',
           f'<text x="{width / 2}" y="-38" text-anchor="middle" '
           f'font-family="sans-serif" font-size="12">{width:g} mm</text>',
           f'<text x="-38" y="{depth / 2}" transform="rotate(-90 -38 {depth / 2})" '
           f'text-anchor="middle" font-family="sans-serif" font-size="12">{depth:g} mm</text>']
    for module in station['modules']:
        x, _, z = module['position_mm']
        w, _, d = module['size_mm']
        sx, sy, sw, sd = module['functional_surface_mm']
        out.extend([
            f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sd}" '
            'fill="#f1f5f9" stroke="#94a3b8" stroke-dasharray="5 4"/>',
            f'<rect x="{x - w / 2}" y="{z - d / 2}" width="{w}" height="{d}" '
            'fill="#dbeafe" stroke="#2563eb"/>',
            f'<text x="{x}" y="{z}" text-anchor="middle" font-family="sans-serif" '
            f'font-size="12">{escape(module["label"])}</text>',
            f'<text x="{x}" y="{z + 18}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="11">{w} x {d} mm</text>',
        ])
    out.append(f'<text x="0" y="{depth + 35}" font-family="sans-serif" font-size="11">'
               'Concept only; dashed areas reserve working access. '
               'No physical fit verified.</text>')
    out.append('</svg>')
    return '\n'.join(out)
