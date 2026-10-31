"""The downloadable preview validates a specification and never controls hardware."""

import json
import subprocess
import sys
from copy import deepcopy

import pytest
from test_microplates import before, select

from app.instructions import build_instruction_files
from app.protocol_preview import render_preview, validate_protocol
from app.software_guidance import build_software_guidance


def configuration():
    return build_software_guidance(select(before()))["protocol_template"]


def test_prints_bound_wells_and_actual_transfer_arithmetic():
    config = configuration()
    text = render_preview(config)
    assert "sample-rack/A1" in text and "sample-rack/B1" in text
    assert "200 uL" in text and "no hardware commands" in text
    assert f"revision {config['binding']['project_revision']}" in text
    assert validate_protocol(config) == config["current_preparation"]["transfers"]


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c.update(execution_enabled=True),
        lambda c: c["binding"].update(project_revision=True),
        lambda c: c["binding"].update(component_ids=["unrelated-part"]),
        lambda c: c["current_preparation"].update(target_count=96),
        lambda c: c["current_preparation"]["transfers"][0].update(total_volume_ul=float("nan")),
        lambda c: c["current_preparation"]["transfers"][0].update(stock_volume_ul=True),
        lambda c: c["current_preparation"]["transfers"][0].update(total_volume_ul=199),
        lambda c: c["current_preparation"]["transfers"][0].update(destination_well="Z99"),
        lambda c: c["binding"]["plate_wells"][0].update(total_liquid_volume_ul=10),
        lambda c: c["binding"]["plate_wells"][0].update(app_x_mm=float("inf")),
    ],
)
def test_rejects_invalid_or_unbound_preview_without_modifying_input(change):
    config = configuration()
    change(config)
    original = deepcopy(config)
    with pytest.raises(ValueError):
        validate_protocol(config)
    # NaN is not equal to itself; stable JSON also compares those invalid test values.
    assert json.dumps(config, sort_keys=True) == json.dumps(original, sort_keys=True)


def test_exported_preview_runs_standalone_with_only_its_template(tmp_path):
    files = build_instruction_files(select(before()))
    for name in ("protocol-preview.py", "protocol-template.json"):
        (tmp_path / name).write_bytes(files[name])
    completed = subprocess.run(
        [sys.executable, "protocol-preview.py", "protocol-template.json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "sample-rack/A1" in completed.stdout
    assert "no hardware commands or connection" in completed.stdout
