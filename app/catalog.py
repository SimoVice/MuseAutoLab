"""Curated sourcing snapshot for the workstation concept.

Prices are a dated curated snapshot, not live feeds. No network calls.
Dimensions are millimetres: a proposed DIY enclosure or the sourced commercial module body.
"""

from __future__ import annotations

import json
from copy import deepcopy
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parent / "data" / "components-2026-10-27.json"

_DISABLED_GROUPS = ("cooling", "temperature-sensor")


def _load_data() -> dict:
    with open(_DATA_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _group_index(data: dict) -> dict[str, dict]:
    return {group["id"]: group for group in data["groups"]}


def default_selections() -> dict[str, str]:
    """Return a detached copy of the default option per group."""
    data = _load_data()
    return deepcopy(data["defaults"])


def cooling_envelope(option_id: str) -> list[float]:
    """Return the assumed outer enclosure size for a cooling option."""
    data = _load_data()
    envelopes = data["envelopes"]
    if option_id not in envelopes:
        raise ValueError(f"Unknown cooling option: {option_id}.")
    return [float(value) for value in envelopes[option_id]]


def build_sourcing(selections: dict[str, str] | None = None, cooling_enabled: bool = True) -> dict:
    """Build a detached sourcing snapshot for the given selections."""
    if selections is None:
        selections = {}
    if not isinstance(selections, dict):
        raise ValueError("Selections must be an object.")
    if not isinstance(cooling_enabled, bool):
        raise ValueError("cooling_enabled must be a boolean.")

    data = _load_data()
    defaults: dict[str, str] = data["defaults"]
    index = _group_index(data)

    for group_id, option_id in selections.items():
        if group_id not in index:
            raise ValueError(f"Unknown group: {group_id}.")
        if not isinstance(option_id, str):
            raise ValueError(f"Invalid option for group {group_id}: {option_id}.")
        valid_ids = {option["id"] for option in index[group_id]["options"]}
        if option_id not in valid_ids:
            raise ValueError(f"Unknown option {option_id} for group {group_id}.")

    effective: dict[str, str] = dict(defaults)
    effective.update(selections)

    for group_id, option_id in effective.items():
        if group_id not in index:
            raise ValueError(f"Unknown group: {group_id}.")
        valid_ids = {option["id"] for option in index[group_id]["options"]}
        if option_id not in valid_ids:
            raise ValueError(f"Unknown option {option_id} for group {group_id}.")

    groups: list[dict] = []
    total = Decimal("0")
    unpriced_count = 0
    is_lower_bound = False

    for group in data["groups"]:
        group_id = group["id"]
        if not cooling_enabled and group_id in _DISABLED_GROUPS:
            continue
        selected_id = effective[group_id]
        selected = next(o for o in group["options"] if o["id"] == selected_id)
        price = selected["unit_price"]
        if price is None:
            unpriced_count += 1
        else:
            total += Decimal(str(price)) * group["quantity"]
        if selected["price_kind"] == "starting_at":
            is_lower_bound = True
        groups.append(
            {
                "id": group["id"],
                "label": group["label"],
                "component_ids": list(group["component_ids"]),
                "quantity": group["quantity"],
                "selected_id": selected_id,
                "options": deepcopy(group["options"]),
            }
        )

    subtotal = float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    return {
        "checked_on": data["checked_on"],
        "currency": data["currency"],
        "subtotal": subtotal,
        "is_lower_bound": is_lower_bound,
        "incomplete": True,
        "unpriced_count": unpriced_count,
        "groups": groups,
        "exclusions": list(data["exclusions"]),
    }
