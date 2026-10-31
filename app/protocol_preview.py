"""Preview a declarative pipetting specification locally; never control hardware.

Usage: python protocol-preview.py protocol-template.json
This standalone file uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def validate_protocol(configuration: dict) -> list[dict]:
    """Validate revision bindings and volume arithmetic before printing a schedule."""
    if not isinstance(configuration, dict) or (
        type(configuration.get("schema_version")) is not int
        or configuration.get("schema_version") != 1
        or configuration.get("kind") != "declarative_pipetting_protocol"
        or configuration.get("execution_enabled") is not False
    ):
        raise ValueError("Expected a non-executable MuseAutoLab protocol template, schema 1.")
    binding = configuration.get("binding") or {}
    if not isinstance(binding, dict):
        raise ValueError("The hardware binding must be an object.")
    revision = binding.get("project_revision")
    if (
        not isinstance(binding.get("project_id"), str)
        or not binding["project_id"].strip()
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 1
        or binding.get("platform") not in {"jubilee", "opentrons-ot2"}
    ):
        raise ValueError("A selected platform and valid project ID/revision binding are required.")
    components = binding.get("component_ids")
    if (
        not isinstance(components, list)
        or not components
        or not all(isinstance(value, str) and value for value in components)
        or len(set(components)) != len(components)
    ):
        raise ValueError("The hardware binding needs unique component IDs.")
    if configuration.get("units") != {"volume": "uL", "geometry": "mm"}:
        raise ValueError("Volumes must be in uL and geometry in mm.")
    preparation = configuration.get("current_preparation") or {}
    if not isinstance(preparation, dict):
        raise ValueError("The current preparation must be an object.")
    transfers = preparation.get("transfers")
    if (
        configuration.get("status") != "needs_review"
        or not isinstance(transfers, list)
        or not transfers
        or len(transfers) > 10000
        or type(preparation.get("target_count")) is not int
        or preparation.get("target_count") != len(transfers)
    ):
        raise ValueError("A complete current preparation with a matching target count is required.")
    destinations = set()
    wells = binding.get("plate_wells", [])
    if not isinstance(wells, list):
        raise ValueError("Plate well bindings must be a list.")
    well_bindings = {well.get("label"): well for well in wells if isinstance(well, dict)}
    for transfer in transfers:
        if (
            not isinstance(transfer, dict)
            or transfer.get("destination_component_id") not in components
        ):
            raise ValueError("Every transfer destination must belong to the bound hardware.")
        values = [
            transfer.get(key) for key in ("stock_volume_ul", "diluent_volume_ul", "total_volume_ul")
        ]
        if not all(
            isinstance(value, (float, int))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value >= 0
            for value in values
        ):
            raise ValueError("Transfer amounts must be finite, nonnegative numbers.")
        stock, diluent, total = values
        if total <= 0 or not math.isclose(stock + diluent, total, rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError("Stock plus diluent must equal a positive total volume.")
        well = transfer.get("destination_well")
        if binding.get("plate_profile_id"):
            if not isinstance(well, str) or well not in well_bindings:
                raise ValueError("Each destination well must exist in the selected plate binding.")
            capacity = well_bindings[well].get("total_liquid_volume_ul")
            if (
                not isinstance(capacity, (int, float))
                or isinstance(capacity, bool)
                or not math.isfinite(capacity)
                or total > capacity
            ):
                raise ValueError("The target volume exceeds or lacks a bound well capacity.")
            if not all(
                isinstance(well_bindings[well].get(axis), (int, float))
                and not isinstance(well_bindings[well][axis], bool)
                and math.isfinite(well_bindings[well][axis])
                for axis in ("app_x_mm", "app_y_mm", "app_z_mm")
            ):
                raise ValueError("The selected well needs finite reference geometry coordinates.")
            destination = (transfer["destination_component_id"], well)
            if destination in destinations:
                raise ValueError("Current direct-dilution destinations must be unique.")
            destinations.add(destination)
    return transfers


def render_preview(configuration: dict) -> str:
    """Return a logical stock/diluent schedule without actuator instructions."""
    transfers = validate_protocol(configuration)
    binding = configuration["binding"]
    lines = [
        "LOGICAL PREVIEW ONLY — no hardware commands or connection",
        f"Project {binding['project_id']} · revision {binding['project_revision']} "
        f"· platform {binding['platform']}",
        "Physical source positions, tool offsets and dispensing settings remain unresolved.",
    ]
    for index, transfer in enumerate(transfers, 1):
        destination = transfer["destination_component_id"]
        if transfer.get("destination_well"):
            destination += "/" + transfer["destination_well"]
        lines.append(
            f"{index}. {destination}: stock {transfer['stock_volume_ul']:g} uL + "
            f"diluent {transfer['diluent_volume_ul']:g} uL = "
            f"{transfer['total_volume_ul']:g} uL; target {transfer.get('target', 'unspecified')}"
        )
    lines.append(
        "Review, translate into upstream software and validate the actual setup before use."
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template", type=Path, help="Path to protocol-template.json")
    arguments = parser.parse_args()
    try:
        if arguments.template.stat().st_size > 5_000_000:
            raise ValueError("Protocol template exceeds the 5 MB preview limit.")
        configuration = json.loads(arguments.template.read_text(encoding="utf-8-sig"))
        print(render_preview(configuration))
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(2, f"Cannot preview protocol: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
