"""Direct dilution planning with strict unit handling.

This module computes one separate tube per target (no serial dilutions).
All arithmetic uses Decimal; results are returned as JSON-compatible floats.
Volumes are calculated values only and require hardware validation.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation, localcontext

MAX_INPUT_CHARS = 1000
MAX_TARGETS = 6
MAX_RAW_MAGNITUDE = Decimal("1E12")
MAX_VOLUME_UL = Decimal("1E12")
MAX_BASE_CONC = Decimal("1E12")

# Conversion to common base units using Decimal for exact arithmetic.
MOLAR_TO_M = {
    "M": Decimal("1"),
    "mM": Decimal("0.001"),
    "uM": Decimal("0.000001"),
    "nM": Decimal("0.000000001"),
}
MASS_TO_G_PER_L = {
    "g/L": Decimal("1"),
    "mg/mL": Decimal("1"),
    "ug/mL": Decimal("0.001"),
}
VOLUME_TO_UL = {
    "mL": Decimal("1000"),
    "uL": Decimal("1"),
    "nL": Decimal("0.001"),
}

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_CONC_PATTERN = re.compile(rf"^(?P<number>{_NUMBER})\s*(?P<unit>[^\s]+)\s*$")
_VOLUME_PATTERN = re.compile(rf"^(?P<number>{_NUMBER})\s*(?P<unit>[^\s]+)\s*$")

_MICRO_SIGNS = ("\u00b5", "\u03bc")


def _normalize_micro(text: str) -> str:
    for ch in _MICRO_SIGNS:
        text = text.replace(ch, "u")
    return text


def _empty_result(status: str, message: str) -> dict:
    return {
        "status": status,
        "message": message,
        "stock": None,
        "final_volume_ul": None,
        "steps": [],
        "assumptions": [],
    }


def _parse_decimal_number(num_str: str, what: str) -> Decimal:
    lowered = num_str.strip().lower()
    if lowered in (
        "nan",
        "+nan",
        "-nan",
        "inf",
        "+inf",
        "-inf",
        "infinity",
        "+infinity",
        "-infinity",
    ):
        raise ValueError(f"{what} must be a finite number.")
    if len(num_str) > 100:
        raise ValueError(f"{what} numeric text is too long.")
    try:
        value = Decimal(num_str)
    except (InvalidOperation, ValueError, ArithmeticError):
        raise ValueError(f"{what} has an unsupported numeric value: {num_str!r}.")
    if not value.is_finite():
        raise ValueError(f"{what} must be a finite number.")
    if abs(value) > MAX_RAW_MAGNITUDE:
        raise ValueError(f"{what} magnitude is out of the supported range.")
    tup = value.as_tuple()
    # Bound exponent to avoid resource exhaustion from extreme scientific notation.
    if tup.exponent < -1000 or tup.exponent > 1000:
        raise ValueError(f"{what} magnitude is out of the supported range.")
    # Bound significant digits to avoid resource exhaustion.
    if len(tup.digits) > 50:
        raise ValueError(f"{what} has too many significant digits.")
    return value


def _parse_concentration(text: str, what: str) -> tuple[Decimal, str, str, Decimal]:
    """Return (raw value, unit, family, base value)."""
    normalized = _normalize_micro(text.strip())
    match = _CONC_PATTERN.match(normalized)
    if not match:
        raise ValueError(
            f"{what} must be a number followed by a supported unit "
            "(M, mM, uM, nM, g/L, mg/mL, ug/mL); got {text.strip()!r}."
        )
    num_str = match.group("number")
    unit = match.group("unit")
    # Full-string match already enforced; unit must be an exact supported token.
    if unit in MOLAR_TO_M:
        family = "molar"
        factor = MOLAR_TO_M[unit]
    elif unit in MASS_TO_G_PER_L:
        family = "mass"
        factor = MASS_TO_G_PER_L[unit]
    else:
        raise ValueError(
            f"{what} has an unsupported unit {unit!r}. Supported: M, mM, uM, nM, g/L, mg/mL, ug/mL."
        )
    value = _parse_decimal_number(num_str, what)
    with localcontext() as ctx:
        ctx.prec = 80
        base = value * factor
    if abs(base) > MAX_BASE_CONC:
        raise ValueError(f"{what} magnitude is out of the supported range.")
    return value, unit, family, base


def _parse_volume(text: str) -> tuple[Decimal, Decimal]:
    """Return (raw value, volume in uL)."""
    normalized = _normalize_micro(text.strip())
    match = _VOLUME_PATTERN.match(normalized)
    if not match:
        raise ValueError(
            f"final_volume must be a number followed by a supported unit "
            f"(mL, uL, nL); got {text.strip()!r}."
        )
    num_str = match.group("number")
    unit = match.group("unit")
    if unit not in VOLUME_TO_UL:
        raise ValueError(f"final_volume has an unsupported unit {unit!r}. Supported: mL, uL, nL.")
    value = _parse_decimal_number(num_str, "final_volume")
    with localcontext() as ctx:
        ctx.prec = 80
        volume_ul = value * VOLUME_TO_UL[unit]
    if abs(volume_ul) > MAX_VOLUME_UL:
        raise ValueError("final_volume magnitude is out of the supported range.")
    return value, volume_ul


def create_dilution_plan(
    stock_concentration: str | None,
    target_concentrations: str | None,
    final_volume: str | None,
) -> dict:
    """Create a direct-dilution plan with one tube per target.

    Returns a dict with keys status, message, stock, final_volume_ul,
    steps and assumptions following the shared contract.
    """
    missing: list[str] = []
    for name, val in (
        ("stock_concentration", stock_concentration),
        ("target_concentrations", target_concentrations),
        ("final_volume", final_volume),
    ):
        if val is None:
            missing.append(name)
        elif isinstance(val, str) and val.strip() == "":
            missing.append(name)
    if missing:
        return _empty_result(
            "incomplete",
            "Missing required parameters: "
            + ", ".join(missing)
            + ". Provide stock_concentration (e.g. '10 mM'), "
            "target_concentrations (e.g. '1 mM, 2 mM') and "
            "final_volume (e.g. '1 mL').",
        )

    # Type check: all present values must be text.
    for name, val in (
        ("stock_concentration", stock_concentration),
        ("target_concentrations", target_concentrations),
        ("final_volume", final_volume),
    ):
        if not isinstance(val, str):
            return _empty_result(
                "invalid",
                f"{name} must be text such as '10 mM' or '1 mL'.",
            )
        if len(val) > MAX_INPUT_CHARS:
            return _empty_result(
                "invalid",
                f"{name} exceeds the {MAX_INPUT_CHARS} character limit.",
            )

    assert isinstance(stock_concentration, str)
    assert isinstance(target_concentrations, str)
    assert isinstance(final_volume, str)

    stock_text = stock_concentration.strip()
    targets_text = target_concentrations.strip()
    volume_text = final_volume.strip()

    try:
        _, _, stock_family, stock_base = _parse_concentration(stock_text, "stock_concentration")
    except ValueError as exc:
        return _empty_result("invalid", str(exc))

    # Stock must be positive.
    if stock_base <= 0:
        return _empty_result(
            "invalid",
            "stock_concentration must be greater than zero.",
        )

    try:
        _, volume_ul = _parse_volume(volume_text)
    except ValueError as exc:
        return _empty_result("invalid", str(exc))

    if volume_ul <= 0:
        return _empty_result(
            "invalid",
            "final_volume must be greater than zero.",
        )

    # Split targets on comma or semicolon; every entry must be fully specified.
    raw_parts = re.split(r"[;,]", targets_text)
    target_tokens: list[str] = [p.strip() for p in raw_parts]
    if len(target_tokens) > MAX_TARGETS:
        return _empty_result(
            "invalid",
            f"Too many targets (maximum {MAX_TARGETS}).",
        )
    # Detect empty entries from leading/trailing/double delimiters.
    for token in target_tokens:
        if token == "":
            return _empty_result(
                "invalid",
                "target_concentrations contains an empty entry; "
                "use comma or semicolon separated values such as '1 mM, 2 mM'.",
            )

    parsed_targets: list[tuple[str, Decimal]] = []
    try:
        for token in target_tokens:
            _, _, family, base = _parse_concentration(token, f"target {token!r}")
            if family != stock_family:
                return _empty_result(
                    "invalid",
                    f"Incompatible units: stock is {stock_family} family but "
                    f"target {token!r} is {family} family. "
                    "Molar (M, mM, uM, nM) and mass (g/L, mg/mL, ug/mL) "
                    "concentrations cannot be mixed.",
                )
            if base < 0:
                return _empty_result(
                    "invalid",
                    f"Target {token!r} must not be negative.",
                )
            if base > stock_base:
                return _empty_result(
                    "invalid",
                    f"Target {token!r} exceeds stock_concentration "
                    f"{stock_text!r}; direct dilution requires target <= stock.",
                )
            parsed_targets.append((token, base))
    except ValueError as exc:
        return _empty_result("invalid", str(exc))

    if not parsed_targets:
        return _empty_result(
            "invalid",
            "target_concentrations must contain at least one value such as '1 mM'.",
        )

    steps: list[dict] = []
    for index, (token, base) in enumerate(parsed_targets):
        with localcontext() as ctx:
            ctx.prec = 80
            stock_vol = base / stock_base * volume_ul
            diluent_vol = volume_ul - stock_vol
        try:
            stock_f = float(stock_vol)
            diluent_f = float(diluent_vol)
            total_f = float(volume_ul)
        except (OverflowError, ValueError):
            return _empty_result(
                "invalid",
                "Computed volumes are out of the supported range.",
            )
        if not (math.isfinite(stock_f) and math.isfinite(diluent_f) and math.isfinite(total_f)):
            return _empty_result(
                "invalid",
                "Computed volumes are nonfinite and cannot be represented.",
            )
        if any(
            original != 0 and converted == 0
            for original, converted in (
                (stock_vol, stock_f),
                (diluent_vol, diluent_f),
                (volume_ul, total_f),
            )
        ):
            return _empty_result("invalid", "Computed volumes are too small to represent.")
        # Guard against negative zero artefacts and tiny negative drift.
        if stock_f < 0 and stock_f > -1e-18:
            stock_f = 0.0
        if diluent_f < 0 and diluent_f > -1e-18:
            diluent_f = 0.0
        if stock_f < 0 or diluent_f < 0:
            return _empty_result(
                "invalid",
                f"Computed volumes for target {token!r} are invalid.",
            )
        steps.append(
            {
                "id": str(index + 1),
                "target": token,
                "stock_volume_ul": stock_f,
                "diluent_volume_ul": diluent_f,
                "total_volume_ul": total_f,
            }
        )

    try:
        final_volume_float = float(volume_ul)
    except (OverflowError, ValueError):
        return _empty_result(
            "invalid",
            "final_volume is out of the supported range.",
        )
    if not math.isfinite(final_volume_float):
        return _empty_result(
            "invalid",
            "final_volume is nonfinite and cannot be represented.",
        )

    assumptions = [
        "Direct dilution: each target is prepared in a separate tube from stock; "
        "no serial dilutions are used.",
        "Stock volume = target / stock × final volume; diluent = final volume − stock volume.",
        "Concentrations are converted to common units and volumes to µL.",
        "Verify tube capacity, pipette range, mixing and hardware before use; "
        "the preparation is not laboratory validated.",
    ]

    return {
        "status": "ready",
        "message": (
            f"Dilution plan ready for {len(steps)} target(s) at "
            f"{final_volume_float} uL final volume per tube."
        ),
        "stock": stock_text,
        "final_volume_ul": final_volume_float,
        "steps": steps,
        "assumptions": assumptions,
    }
