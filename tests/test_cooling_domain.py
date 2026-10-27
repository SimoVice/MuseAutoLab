"""Cooling domain checks using the real app.catalog snapshot."""

from copy import deepcopy

import pytest

from app.catalog import build_sourcing, cooling_envelope, default_selections
from app.domain import apply_update, configure_project, confirm_project, new_project


def test_defaults_use_catalog():
    project = new_project()
    assert project["summary"]["cooling_enabled"] is False
    assert project["summary"]["cooling_target_c"] is None
    assert project["selections"] == default_selections()
    expected = build_sourcing(dict(project["selections"]), False)
    assert project["sourcing"] == expected
    assert project["sourcing"]["currency"] == "USD"
    assert project["design"]["estimated_cost"] == {
        "amount": expected["subtotal"],
        "currency": "USD",
    }
    cooling = project["design"]["cooling"]
    assert cooling["enabled"] is False
    assert cooling["target_c"] == 4.0
    assert cooling["target_source"] == "assumed"
    assert cooling["transfer_mode"] == "manual"
    assert cooling["validation"] == "unverified"
    assert not any(c["id"] == "cold-storage" for c in project["design"]["components"])


def test_cooling_envelope_values():
    assert cooling_envelope("diy-peltier") == [150, 120, 130]
    assert cooling_envelope("opentrons-gen2") == [90, 84, 194]


def test_enable_cooling_appends_bay_and_extends_depth():
    project = new_project()
    original_depth = project["design"]["footprint"]["depth_mm"]
    enabled = configure_project(project, cooling_enabled=True)
    assert enabled["summary"]["cooling_enabled"] is True
    assert enabled["revision"] == project["revision"] + 1
    size = cooling_envelope(enabled["selections"]["cooling"])
    added = max(200, size[2] + 60)
    assert enabled["design"]["footprint"]["depth_mm"] == original_depth + added
    parts = {c["id"]: c for c in enabled["design"]["components"]}
    bay = parts["cold-storage"]
    assert bay["kind"] == "cooling"
    assert bay["size"] == list(size)
    assert bay["position"] == [0, 20 + size[1] / 2, original_depth / 2 + added / 2]
    base = parts["base"]
    assert base["size"][2] == original_depth + added
    assert base["position"][2] == added / 2
    # Existing purchased/concept parts keep dimensions and positions.
    before = {c["id"]: c for c in project["design"]["components"]}
    for part_id, part in before.items():
        if part_id == "base":
            continue
        assert parts[part_id]["size"] == part["size"]
        assert parts[part_id]["position"] == part["position"]
    cooling = enabled["design"]["cooling"]
    assert cooling["enabled"] is True
    assert cooling["variant_id"] == enabled["selections"]["cooling"]
    expected = build_sourcing(dict(enabled["selections"]), True)
    assert enabled["sourcing"] == expected
    assert enabled["design"]["estimated_cost"]["amount"] == expected["subtotal"]


def test_user_target_and_toggle_retains_selections():
    project = new_project()
    updated = configure_project(project, cooling_enabled=True, cooling_target_c=8)
    assert updated["design"]["cooling"]["target_c"] == 8.0
    assert updated["design"]["cooling"]["target_source"] == "user"
    variant = configure_project(updated, selections={"cooling": "opentrons-gen2"})
    assert variant["selections"]["cooling"] == "opentrons-gen2"
    assert variant["design"]["cooling"]["variant_id"] == "opentrons-gen2"
    disabled = configure_project(variant, cooling_enabled=False)
    assert disabled["selections"]["cooling"] == "opentrons-gen2"
    assert disabled["design"]["cooling"]["enabled"] is False
    assert not any(c["id"] == "cold-storage" for c in disabled["design"]["components"])
    reenabled = configure_project(disabled, cooling_enabled=True)
    assert reenabled["selections"]["cooling"] == "opentrons-gen2"


def test_opentrons_below_4_rejected():
    project = new_project()
    with pytest.raises(ValueError):
        configure_project(
            project,
            cooling_enabled=True,
            cooling_target_c=3,
            selections={"cooling": "opentrons-gen2"},
        )
    enabled = configure_project(
        project, cooling_enabled=True, selections={"cooling": "opentrons-gen2"}
    )
    assert enabled["design"]["cooling"]["target_c"] == 4.0
    with pytest.raises(ValueError):
        configure_project(enabled, cooling_target_c=3)
    assert enabled["summary"]["cooling_target_c"] is None


def test_invalid_inputs_preserve_state():
    project = new_project()
    before = deepcopy(project)
    for kwargs in (
        {"cooling_enabled": "yes"},
        {"cooling_enabled": 1},
        {"cooling_target_c": float("nan")},
        {"cooling_target_c": float("inf")},
        {"cooling_target_c": 1.9},
        {"cooling_target_c": 20.1},
        {"selections": {"no-such-group": "x"}},
    ):
        with pytest.raises(ValueError):
            configure_project(project, **kwargs)
    assert project == before
    with pytest.raises(ValueError):
        apply_update(project, {"cooling_enabled": "yes"})
    with pytest.raises(ValueError):
        apply_update(project, {"cooling_target_c": 99})
    with pytest.raises(ValueError):
        apply_update(project, {"selections": {"cooling": "no-such-option"}})
    assert project == before


def test_noop_preserves_revision_and_single_revision_per_update():
    project = new_project()
    same = configure_project(project, cooling_enabled=False)
    assert same == project
    assert same["revision"] == project["revision"]
    one = configure_project(project, cooling_enabled=True)
    assert one["revision"] == project["revision"] + 1
    again = apply_update(one, {"cooling_enabled": True})
    assert again == one
    changed = apply_update(one, {"cooling_target_c": 10})
    assert changed["revision"] == one["revision"] + 1
    assert changed["status"] == "draft"


def test_apply_update_accepts_cooling_fields_and_width_retains_selections():
    project = new_project()
    updated = apply_update(
        project, {"cooling_enabled": True, "selections": {"cooling": "diy-peltier"}}
    )
    assert updated["summary"]["cooling_enabled"] is True
    assert any(c["id"] == "cold-storage" for c in updated["design"]["components"])
    resized = apply_update(updated, {"workspace_width_mm": 450})
    assert resized["selections"] == updated["selections"]
    assert resized["summary"]["cooling_enabled"] is True
    assert any(c["id"] == "cold-storage" for c in resized["design"]["components"])


def test_infeasible_width_preserves_geometry_and_rejects_simultaneous_cooling():
    project = new_project()
    compact = apply_update(project, {"workspace_width_mm": 400})
    rejected = apply_update(compact, {"workspace_width_mm": 350})
    assert rejected["design"]["constraint_status"] == "infeasible"
    assert rejected["design"]["components"] == compact["design"]["components"]
    with pytest.raises(ValueError):
        apply_update(compact, {"workspace_width_mm": 350, "cooling_enabled": True})
    with pytest.raises(ValueError):
        configure_project(rejected, cooling_enabled=True)
    assert rejected["summary"]["workspace_width_mm"] == 350


def test_confirmation_preserves_cooling_and_cost_partial():
    project = new_project()
    complete = {
        "stock_concentration": "10 mM",
        "target_concentrations": "1 mM, 2 mM",
        "final_volume": "1 mL",
        "equipment": "pipette and tubes",
    }
    draft = apply_update(project, complete)
    cooled = configure_project(draft, cooling_enabled=True)
    confirmed = confirm_project(cooled)
    assert confirmed["status"] == "confirmed"
    assert confirmed["selections"] == cooled["selections"]
    assert confirmed["sourcing"] == cooled["sourcing"]
    assert confirmed["design"]["estimated_cost"]["amount"] == cooled["sourcing"]["subtotal"]
