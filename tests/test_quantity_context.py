"""Tests for per-container volume context such as '1 mL per tube'."""

import pytest

from app.dilution import create_dilution_plan
from app.model_client import ExtractedTurn
from app.quantities import normalize_volume


def test_volume_per_container_context_canonicalizes():
    assert normalize_volume("1 mL per tube") == "1 mL"
    assert normalize_volume("250 \u00b5l in each tube") == "250 uL"
    assert normalize_volume("1 mL for each tube") == "1 mL"
    assert normalize_volume("2 mL per sample") == "2 mL"
    assert normalize_volume("2 mL per well") == "2 mL"
    assert normalize_volume("1 mL per tubes") == "1 mL"
    assert normalize_volume("1 mL per samples") == "1 mL"
    assert normalize_volume("1 mL per wells") == "1 mL"
    assert normalize_volume("1 mL per tube.") == "1 mL"
    assert normalize_volume("0,5 mL per provetta") == "0.5 mL"
    assert normalize_volume("1 mL per ogni provetta") == "1 mL"
    assert normalize_volume("1 mL in ogni provetta") == "1 mL"
    assert normalize_volume("1 mL per provette") == "1 mL"
    assert normalize_volume("1 mL per campione") == "1 mL"
    assert normalize_volume("1 mL per campioni") == "1 mL"
    assert normalize_volume("1 mL per pozzetto") == "1 mL"
    assert normalize_volume("1 mL per pozzetti") == "1 mL"


def test_volume_context_rejects_ambiguous_or_unrelated():
    for bad in [
        "1 mL total for 10 tubes",
        "1 mL/min",
        "1 mL per tube and 2 mL elsewhere",
        "per tube",
        "1 per tube",
        "1 mL",
        "1 mL per tube extra",
        "1 mL per tubes for 10 tubes",
    ]:
        if bad == "1 mL":
            assert normalize_volume(bad) == "1 mL"
            continue
        with pytest.raises(ValueError):
            normalize_volume(bad)
    with pytest.raises(ValueError):
        normalize_volume("2 mL total")
    with pytest.raises(ValueError):
        normalize_volume("")


def test_extracted_turn_canonical_and_contextual_sources_verify():
    user_message = "Prepare targets at 1 mL per tube using the stock."
    turn = ExtractedTurn(
        assistant_message="Plan ready.",
        final_volume="1 mL",
        source_final_volume="1 mL per tube",
    )
    turn.verify_sources(user_message)
    canonical_user = "Prepare targets at 1 mL using the stock."
    canonical_turn = ExtractedTurn(
        assistant_message="Plan ready.",
        final_volume="1 mL",
        source_final_volume="1 mL",
    )
    canonical_turn.verify_sources(canonical_user)


def test_extracted_turn_distinct_volume_still_invalid():
    user_message = "Prepare targets at 1 mL per tube using the stock."
    turn = ExtractedTurn(
        assistant_message="Plan ready.",
        final_volume="2 mL",
        source_final_volume="1 mL per tube",
    )
    with pytest.raises(ValueError):
        turn.verify_sources(user_message)


def test_dilution_plan_with_per_tube_final_volume():
    plan = create_dilution_plan(
        "10 mg/mL",
        "1 mg/mL, 0.5 mg/mL, 0.1 mg/mL",
        "1 mL per tube",
    )
    assert plan["status"] == "ready"
    assert plan["final_volume_ul"] == pytest.approx(1000.0)
    assert [s["stock_volume_ul"] for s in plan["steps"]] == pytest.approx(
        [100.0, 50.0, 10.0]
    )
    assert [s["diluent_volume_ul"] for s in plan["steps"]] == pytest.approx(
        [900.0, 950.0, 990.0]
    )
