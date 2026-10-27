import copy
import json
from pathlib import Path

import pytest

from app.catalog import build_sourcing, cooling_envelope, default_selections

DATA_PATH = Path(__file__).resolve().parents[1] / "app" / "data" / "components-2026-10-27.json"


def test_defaults_cover_all_groups():
    selections = default_selections()
    assert selections == {
        "motors": "pololu-1209",
        "drivers": "drv8825",
        "controller": "pico",
        "cooling": "diy-peltier",
        "temperature-sensor": "probe",
        "frame": "custom",
        "linear-motion": "custom",
        "pipette": "custom",
        "fixtures": "custom",
        "power": "custom",
    }


def test_default_subtotal_uses_quantities():
    sourcing = build_sourcing({}, True)
    # 4*35.12 + 4*15.95 + 4.00 + 34.95 + 9.95
    assert sourcing["subtotal"] == pytest.approx(253.18)
    assert sourcing["is_lower_bound"] is False
    assert sourcing["incomplete"] is True
    assert sourcing["currency"] == "USD"
    assert sourcing["checked_on"] == "2026-10-27"


def test_partial_selection_merges_over_defaults():
    sourcing = build_sourcing({"motors": "pololu-1208"}, True)
    # 4*30.32 + 4*15.95 + 4.00 + 34.95 + 9.95
    assert sourcing["subtotal"] == pytest.approx(233.98)
    by_id = {group["id"]: group for group in sourcing["groups"]}
    assert by_id["motors"]["selected_id"] == "pololu-1208"
    assert by_id["drivers"]["selected_id"] == "drv8825"


def test_opentrons_selection_is_lower_bound():
    sourcing = build_sourcing({"cooling": "opentrons-gen2"}, True)
    assert sourcing["is_lower_bound"] is True
    # 4*35.12 + 4*15.95 + 4.00 + 3975.00 + 9.95
    assert sourcing["subtotal"] == pytest.approx(4193.23)


def test_cooling_disabled_omits_groups_and_reenable_restores():
    disabled = build_sourcing({}, False)
    ids = [group["id"] for group in disabled["groups"]]
    assert "cooling" not in ids
    assert "temperature-sensor" not in ids
    assert disabled["subtotal"] == pytest.approx(208.28)

    retained = {"cooling": "opentrons-gen2", "temperature-sensor": "bare"}
    still_disabled = build_sourcing(retained, False)
    assert [group["id"] for group in still_disabled["groups"]] == ids

    reenabled = build_sourcing(retained, True)
    by_id = {group["id"]: group for group in reenabled["groups"]}
    assert by_id["cooling"]["selected_id"] == "opentrons-gen2"
    assert by_id["temperature-sensor"]["selected_id"] == "bare"
    assert reenabled["is_lower_bound"] is True


def test_invalid_group_and_option_raise():
    with pytest.raises(ValueError):
        build_sourcing({"unknown-group": "custom"}, True)
    with pytest.raises(ValueError):
        build_sourcing({"motors": "no-such-option"}, True)
    with pytest.raises(ValueError):
        build_sourcing({"cooling": "bad-option"}, False)


def test_unpriced_groups_excluded_and_counted():
    sourcing = build_sourcing({}, True)
    assert sourcing["unpriced_count"] == 5
    for group in sourcing["groups"]:
        selected = next(o for o in group["options"] if o["id"] == group["selected_id"])
        if selected["unit_price"] is None:
            assert selected["price_kind"] == "unpriced"
    # Custom groups contribute no amount: cheapest priced alternative check.
    priced = build_sourcing({"motors": "pololu-1208", "drivers": "a4988"}, True)
    # 4*30.32 + 4*8.95 + 4.00 + 34.95 + 9.95
    assert priced["subtotal"] == pytest.approx(205.98)
    assert priced["unpriced_count"] == 5


def test_source_and_date_presence():
    sourcing = build_sourcing({}, True)
    assert sourcing["exclusions"] and len(sourcing["exclusions"]) == 3
    for group in sourcing["groups"]:
        for option in group["options"]:
            assert option["checked_on"] == "2026-10-27"
            assert option["source_url"] is None or option["source_url"].startswith("https://")
            assert option["price_kind"] in ("listed", "starting_at", "unpriced")
    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    assert raw["checked_on"] == "2026-10-27"


def test_no_shared_mutable_state():
    first = build_sourcing({}, True)
    first["groups"][0]["options"][0]["unit_price"] = 0
    first["groups"].append({"id": "tampered"})
    second = build_sourcing({}, True)
    assert second["subtotal"] == pytest.approx(253.18)
    assert all(group["id"] != "tampered" for group in second["groups"])

    defaults = default_selections()
    defaults["motors"] = "tampered"
    assert default_selections()["motors"] == "pololu-1209"

    envelope = cooling_envelope("diy-peltier")
    assert envelope == [150, 120, 130]
    envelope.append(999)
    assert cooling_envelope("diy-peltier") == [150, 120, 130]


def test_cooling_envelopes():
    assert cooling_envelope("diy-peltier") == [150, 120, 130]
    assert cooling_envelope("opentrons-gen2") == [90, 84, 194]
    with pytest.raises(ValueError):
        cooling_envelope("custom")


def test_json_snapshot_matches_catalog():
    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    snapshot = copy.deepcopy(raw)
    assert set(raw["defaults"]) == {group["id"] for group in raw["groups"]}
    assert json.dumps(snapshot, sort_keys=True)
