"""Tests for direct dilution planning."""

import math

import pytest

from app.dilution import create_dilution_plan


def test_basic_multiple_targets():
    plan = create_dilution_plan("10 mM", "1 mM, 2 mM", "1 mL")
    assert plan["status"] == "ready"
    assert plan["stock"] == "10 mM"
    assert plan["final_volume_ul"] == pytest.approx(1000.0)
    assert len(plan["steps"]) == 2
    assert plan["steps"][0]["stock_volume_ul"] == pytest.approx(100.0)
    assert plan["steps"][0]["diluent_volume_ul"] == pytest.approx(900.0)
    assert plan["steps"][0]["total_volume_ul"] == pytest.approx(1000.0)
    assert plan["steps"][1]["stock_volume_ul"] == pytest.approx(200.0)
    assert plan["steps"][1]["diluent_volume_ul"] == pytest.approx(800.0)
    for step in plan["steps"]:
        assert isinstance(step["id"], str)
        assert math.isfinite(step["stock_volume_ul"])
    assert any("hardware" in a.lower() for a in plan["assumptions"])


def test_molar_unit_conversion():
    # 1 M stock, 1 mM target, 1 mL final -> 1 uL stock.
    plan = create_dilution_plan("1 M", "1 mM", "1 mL")
    assert plan["status"] == "ready"
    assert plan["steps"][0]["stock_volume_ul"] == pytest.approx(1.0)
    # uM and nM chain: 1000 uM == 1 mM.
    plan2 = create_dilution_plan("1 mM", "1000 uM", "1000 uL")
    assert plan2["status"] == "ready"
    assert plan2["steps"][0]["stock_volume_ul"] == pytest.approx(1000.0)
    plan3 = create_dilution_plan("1 mM", "1000000 nM", "1 mL")
    assert plan3["status"] == "ready"
    assert plan3["steps"][0]["stock_volume_ul"] == pytest.approx(1000.0)


def test_micro_symbol_normalization():
    a = create_dilution_plan("1 mM", "500 \u00b5M", "1 mL")
    b = create_dilution_plan("1 mM", "500 uM", "1 mL")
    assert a["status"] == "ready" and b["status"] == "ready"
    assert a["steps"][0]["stock_volume_ul"] == pytest.approx(b["steps"][0]["stock_volume_ul"])
    c = create_dilution_plan("1 mM", "500 \u03bcM", "1 mL")
    assert c["status"] == "ready"
    v = create_dilution_plan("10 mM", "1 mM", "100 \u00b5L")
    assert v["status"] == "ready"
    assert v["final_volume_ul"] == pytest.approx(100.0)


def test_mass_units_and_volume_units():
    # 1 g/L equals 1 mg/mL, so target == stock gives full stock volume.
    plan = create_dilution_plan("1 g/L", "1 mg/mL", "1 mL")
    assert plan["status"] == "ready"
    assert plan["steps"][0]["stock_volume_ul"] == pytest.approx(1000.0)
    assert plan["steps"][0]["diluent_volume_ul"] == pytest.approx(0.0)
    # ug/mL conversion: 1000 ug/mL == 1 mg/mL.
    plan2 = create_dilution_plan("1 mg/mL", "1000 ug/mL", "500 uL")
    assert plan2["status"] == "ready"
    assert plan2["steps"][0]["stock_volume_ul"] == pytest.approx(500.0)
    # Volume units: mL, uL, nL.
    assert create_dilution_plan("10 mM", "1 mM", "1 mL")["final_volume_ul"] == pytest.approx(1000.0)
    assert create_dilution_plan("10 mM", "1 mM", "1000 uL")["final_volume_ul"] == pytest.approx(
        1000.0
    )
    assert create_dilution_plan("10 mM", "1 mM", "1000000 nL")["final_volume_ul"] == pytest.approx(
        1000.0
    )


def test_semicolon_separated_targets():
    plan = create_dilution_plan("10 mM", "1 mM; 2 mM", "1 mL")
    assert plan["status"] == "ready"
    assert [s["target"] for s in plan["steps"]] == ["1 mM", "2 mM"]


def test_incompatible_families_are_invalid():
    plan = create_dilution_plan("10 mM", "1 mg/mL", "1 mL")
    assert plan["status"] == "invalid"
    assert plan["steps"] == []
    assert plan["stock"] is None
    assert plan["final_volume_ul"] is None
    plan2 = create_dilution_plan("1 g/L", "1 mM", "1 mL")
    assert plan2["status"] == "invalid"


def test_target_exceeding_stock_is_invalid():
    plan = create_dilution_plan("1 mM", "2 mM", "1 mL")
    assert plan["status"] == "invalid"
    assert plan["steps"] == []
    assert "exceed" in plan["message"].lower()


def test_zero_target_is_valid():
    plan = create_dilution_plan("10 mM", "0 mM", "1 mL")
    assert plan["status"] == "ready"
    assert plan["steps"][0]["stock_volume_ul"] == pytest.approx(0.0)
    assert plan["steps"][0]["diluent_volume_ul"] == pytest.approx(1000.0)


def test_invalid_and_zero_values():
    # Zero or negative stock/volume rejected.
    assert create_dilution_plan("0 mM", "1 mM", "1 mL")["status"] == "invalid"
    assert create_dilution_plan("10 mM", "1 mM", "0 mL")["status"] == "invalid"
    assert create_dilution_plan("-10 mM", "1 mM", "1 mL")["status"] == "invalid"
    assert create_dilution_plan("10 mM", "-1 mM", "1 mL")["status"] == "invalid"
    # Unsupported or ambiguous text rejected.
    assert create_dilution_plan("10 mM", "1 mM", "1 mL")["status"] == "ready"
    assert create_dilution_plan("10 apples", "1 mM", "1 mL")["status"] == "invalid"
    assert create_dilution_plan("10 mM", "1 mM", "1 L")["status"] == "invalid"
    assert create_dilution_plan("10 mM", "1", "1 mL")["status"] == "invalid"
    assert create_dilution_plan("10 mM", "1 mM, ", "1 mL")["status"] == "invalid"
    assert create_dilution_plan("10 mM", "nan mM", "1 mL")["status"] == "invalid"
    assert create_dilution_plan("10 mM", "1 mM", "inf mL")["status"] == "invalid"
    # Case sensitivity: wrong case rejected.
    assert create_dilution_plan("10 MM", "1 mM", "1 mL")["status"] == "invalid"
    assert create_dilution_plan("10 mM", "1 mM", "1 ML")["status"] == "invalid"


def test_missing_data_is_incomplete():
    for args in [
        (None, "1 mM", "1 mL"),
        ("10 mM", None, "1 mL"),
        ("10 mM", "1 mM", None),
        ("", "1 mM", "1 mL"),
        ("10 mM", "   ", "1 mL"),
    ]:
        plan = create_dilution_plan(*args)
        assert plan["status"] == "incomplete"
        assert plan["steps"] == []
        assert plan["stock"] is None
        assert plan["final_volume_ul"] is None
        assert isinstance(plan["message"], str) and plan["message"]


def test_no_partial_results_and_bounds():
    plan = create_dilution_plan("10 mM", "1 mM, 99 mol/L", "1 mL")
    assert plan["status"] == "invalid"
    assert plan["steps"] == []
    long_text = "1 mM " + "x" * 2000
    assert create_dilution_plan("10 mM", long_text, "1 mL")["status"] == "invalid"
    huge = create_dilution_plan("1E30 M", "1 mM", "1 mL")
    assert huge["status"] == "invalid"


def test_tiny_volumes_do_not_silently_underflow():
    plan = create_dilution_plan("1 M", "1e-400 M", "1 uL")
    assert plan["status"] == "invalid"
    assert plan["steps"] == []


def test_too_many_targets_are_rejected():
    plan = create_dilution_plan("10 mM", ", ".join(["1 mM"] * 7), "1 mL")
    assert plan["status"] == "invalid"
