"""Tests for quantity normalization helpers."""

from decimal import Decimal

import pytest

from app.dilution import create_dilution_plan
from app.quantities import normalize_concentration, normalize_targets, normalize_volume


def assert_same_value(canonical: str, expected_number: str):
    number = canonical.split(" ")[0]
    assert Decimal(number) == Decimal(expected_number)
    assert "," not in canonical


def test_concentration_lowercase_liter_and_spacing():
    assert normalize_concentration("10 mg/ml") == "10 mg/mL"
    assert normalize_concentration("1 g/l") == "1 g/L"
    assert normalize_concentration("100 ug/ml") == "100 ug/mL"
    assert normalize_concentration("1mg/mL") == "1 mg/mL"
    assert normalize_concentration("1 mg / mL") == "1 mg/mL"
    assert normalize_concentration("1  mM") == "1 mM"
    assert normalize_concentration("1mM") == "1 mM"


def test_concentration_mol_aliases():
    assert normalize_concentration("1 mol/L") == "1 M"
    assert normalize_concentration("2 mmol/l") == "2 mM"
    assert normalize_concentration("500 umol/L") == "500 uM"
    assert normalize_concentration("7 nmol/L") == "7 nM"
    assert normalize_concentration("1 mol / l") == "1 M"
    assert normalize_concentration("10 mg per ml") == "10 mg/mL"
    assert normalize_concentration("10 mg per mL") == "10 mg/mL"


def test_concentration_preserves_value():
    out = normalize_concentration("0,5 mM")
    assert out == "0.5 mM"
    assert_same_value(normalize_concentration("1.00 mM"), "1.00")
    assert_same_value(normalize_concentration("1e3 uM"), "1000")
    # Huge exponents keep exponent form and do not expand.
    out = normalize_concentration("1e-300 M")
    assert "E" in out or "e" in out
    assert Decimal(out.split(" ")[0]) == Decimal("1e-300")
    assert len(out) < 100


def test_volume_basics():
    assert normalize_volume("0,5 ml") == "0.5 mL"
    assert normalize_volume("100ul") == "100 uL"
    assert normalize_volume("1 nL") == "1 nL"
    assert normalize_volume("1 ml") == "1 mL"
    assert normalize_volume("2 nl") == "2 nL"


def test_unicode_micro():
    assert normalize_concentration("500 \u00b5M") == "500 uM"
    assert normalize_concentration("500 \u03bcM") == "500 uM"
    assert normalize_volume("100 \u00b5L") == "100 uL"
    assert normalize_volume("100 \u03bcL") == "100 uL"
    assert normalize_concentration("100 \u00b5g/mL") == "100 ug/mL"


def test_uppercase_prefix_rejections():
    for bad in ["10 MM", "10 ML", "10 Mg/ml", "10 mm", "10 G/L", "10 MG/mL"]:
        with pytest.raises(ValueError):
            normalize_concentration(bad)
    for bad in ["1 ML", "1 MM", "1 mm", "1 L", "1 UL"]:
        with pytest.raises(ValueError):
            normalize_volume(bad)


def test_unsupported_strings():
    with pytest.raises(ValueError):
        normalize_concentration("10 apples")
    with pytest.raises(ValueError):
        normalize_concentration("10")
    with pytest.raises(ValueError):
        normalize_concentration("")
    with pytest.raises(ValueError):
        normalize_volume("10 apples")
    with pytest.raises(ValueError):
        normalize_volume("1 L")
    with pytest.raises(ValueError):
        normalize_targets("bananas")


def test_shared_trailing_unit_lists():
    assert normalize_targets("1, 2 and 3 mg/ml") == "1 mg/mL, 2 mg/mL, 3 mg/mL"
    assert normalize_targets("1, 2, and 3 mg/ml") == "1 mg/mL, 2 mg/mL, 3 mg/mL"
    assert normalize_targets("1, 2, 3 mg/mL") == "1 mg/mL, 2 mg/mL, 3 mg/mL"
    assert normalize_targets("1 e 2 mM") == "1 mM, 2 mM"
    assert normalize_targets("1 mM and 2 mM") == "1 mM, 2 mM"
    assert normalize_targets("1 mM; 2 mM") == "1 mM, 2 mM"
    assert normalize_targets("1mg/ml,2mg/ml") == "1 mg/mL, 2 mg/mL"


def test_decimal_comma_lists():
    assert normalize_targets("1,5 mg/ml") == "1.5 mg/mL"
    assert normalize_targets("1, 5 mg/ml") == "1 mg/mL, 5 mg/mL"
    assert normalize_concentration("0,5 mg/ml") == "0.5 mg/mL"


def test_mixed_compatible_unit_lists():
    assert normalize_targets("1 mM, 500 uM") == "1 mM, 500 uM"
    out = normalize_targets("1 g/L, 1 mg/mL")
    assert out == "1 g/L, 1 mg/mL"
    # Numerical equivalence through dilution calculator.
    plan = create_dilution_plan("1 mM", normalize_targets("1000 uM"), "1 mL")
    assert plan["status"] == "ready"
    plan2 = create_dilution_plan("1 mM", "1 mM", "1 mL")
    assert plan["steps"][0]["stock_volume_ul"] == pytest.approx(
        plan2["steps"][0]["stock_volume_ul"]
    )


def test_normalized_values_match_dilution():
    stock = normalize_concentration("10 mg/ml")
    target = normalize_targets("1 mg/mL")
    volume = normalize_volume("1 ml")
    plan = create_dilution_plan(stock, target, volume)
    assert plan["status"] == "ready"
    assert plan["steps"][0]["stock_volume_ul"] == pytest.approx(100.0)


def test_ambiguous_and_empty_rejected():
    with pytest.raises(ValueError, match="ambiguous"):
        normalize_targets("1,2,3 mg/ml")
    with pytest.raises(ValueError, match="ambiguous"):
        normalize_targets("1 mM, 2, 3 uM")
    with pytest.raises(ValueError, match="[Ee]mpty"):
        normalize_targets("1 mM, ")
    with pytest.raises(ValueError, match="[Ee]mpty"):
        normalize_targets("1 mM;; 2 mM")
    with pytest.raises(ValueError, match="[Ee]mpty"):
        normalize_targets(", 1 mM")


def test_too_many_targets():
    with pytest.raises(ValueError, match="maximum 6"):
        normalize_targets(", ".join(["1 mM"] * 7))


def test_bounds():
    with pytest.raises(ValueError):
        normalize_concentration("x" * 1001)
    with pytest.raises(ValueError):
        normalize_concentration("1" * 101 + " mM")
    with pytest.raises(ValueError):
        normalize_concentration("1E1001 mM")
    with pytest.raises(ValueError):
        normalize_concentration("1E-1001 mM")
    with pytest.raises(ValueError):
        normalize_concentration("nan mM")
    with pytest.raises(ValueError):
        normalize_concentration("inf mM")
    with pytest.raises(ValueError):
        normalize_volume("1E1005 mL")
    with pytest.raises(ValueError):
        normalize_targets("x" * 1001)


def test_error_messages_use_human_labels():
    try:
        normalize_concentration("10 apples")
    except ValueError as exc:
        assert "_" not in str(exc)
        assert "Concentration" in str(exc)
    try:
        normalize_volume("10 apples")
    except ValueError as exc:
        assert "_" not in str(exc)
        assert "Volume" in str(exc)
    try:
        normalize_targets("1 mM, ")
    except ValueError as exc:
        assert "_" not in str(exc)
        assert "Targets" in str(exc) or "Target" in str(exc)


def test_equivalent_numeric_spelling_is_canonical_and_idempotent():
    assert normalize_concentration("1.00mg/ml") == normalize_concentration("1mg/mL")
    assert normalize_volume("5e2ul") == normalize_volume("500.0uL")
    assert normalize_targets("1.0, 2.00 mg/ml") == "1 mg/mL, 2 mg/mL"
