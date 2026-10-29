"""Canonical quantity normalization for chat inputs.

Converts equivalent notations (lowercase liter, micro signs, whitespace,
decimal comma, mol/L aliases, per-phrasing) into canonical texts that the
dilution planner accepts. No positivity or domain checks here.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, localcontext

MAX_INPUT_CHARS = 1000
MAX_NUMERIC_CHARS = 100
MAX_TARGETS = 6

_MICRO_SIGNS = ("\u00b5", "\u03bc")

CONC_ALIASES = {
    "M": "M",
    "mM": "mM",
    "uM": "uM",
    "nM": "nM",
    "mol/L": "M",
    "mol/l": "M",
    "mmol/L": "mM",
    "mmol/l": "mM",
    "umol/L": "uM",
    "umol/l": "uM",
    "nmol/L": "nM",
    "nmol/l": "nM",
    "g/L": "g/L",
    "g/l": "g/L",
    "mg/mL": "mg/mL",
    "mg/ml": "mg/mL",
    "ug/mL": "ug/mL",
    "ug/ml": "ug/mL",
}

VOLUME_ALIASES = {
    "mL": "mL",
    "ml": "mL",
    "uL": "uL",
    "ul": "uL",
    "nL": "nL",
    "nl": "nL",
}

CONC_SUPPORTED = "M, mM, uM, nM, g/L, mg/mL, ug/mL"
VOLUME_SUPPORTED = "mL, uL, nL"

_NUMBER_START = r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?"
_BARE_NUMBER = re.compile(rf"^{_NUMBER_START}$")
_NUMBER_AT_START = re.compile(_NUMBER_START)
_AND_SPLIT = re.compile(r"(?:,\s*|\s+)(?:and|e)\s+", re.IGNORECASE)
_PER_SLASH = re.compile(r"\s+per\s+", re.IGNORECASE)
_SLASH_SPACES = re.compile(r"\s*/\s*")
# Trailing per-container quantity context for volumes. The app plans one
# independent tube per target, so an explicit trailing phrase such as
# "per tube" describes the same single-container volume.
_VOLUME_CONTEXT = re.compile(
    r"\s+(?:"
    r"per\s+tubes?"
    r"|in\s+each\s+tubes?"
    r"|for\s+each\s+tubes?"
    r"|per\s+samples?"
    r"|in\s+each\s+samples?"
    r"|for\s+each\s+samples?"
    r"|per\s+wells?"
    r"|in\s+each\s+wells?"
    r"|for\s+each\s+wells?"
    r"|per\s+provett[ae]"
    r"|per\s+ogni\s+provett[ae]"
    r"|in\s+ogni\s+provett[ae]"
    r"|per\s+campion[ei]"
    r"|per\s+pozzett[oi]"
    r")\s*\.?\s*$",
    re.IGNORECASE,
)


def _strip_volume_context(working: str) -> str:
    """Remove one trailing per-container phrase from a volume input."""
    return _VOLUME_CONTEXT.sub("", working)


def _replace_micro(text: str) -> str:
    for ch in _MICRO_SIGNS:
        text = text.replace(ch, "u")
    return text


def _parse_decimal(num_raw: str, label: str) -> Decimal:
    if len(num_raw) > MAX_NUMERIC_CHARS:
        raise ValueError(f"{label} numeric text is too long.")
    num_dot = num_raw.replace(",", ".")
    lowered = num_dot.strip().lower()
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
        raise ValueError(f"{label} must be a finite number.")
    try:
        value = Decimal(num_dot)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label} has an unsupported numeric value {num_raw!r}.")
    if not value.is_finite():
        raise ValueError(f"{label} must be a finite number.")
    tup = value.as_tuple()
    if tup.exponent < -1000 or tup.exponent > 1000:
        raise ValueError(f"{label} magnitude is out of the supported range.")
    return value


def _number_text(value: Decimal) -> str:
    """Keep equivalent spellings identical without expanding extreme exponents."""
    if value == 0:
        return "0"
    with localcontext() as ctx:
        ctx.prec = MAX_NUMERIC_CHARS + 1
        value = value.normalize()
    return format(value, "f") if -6 <= value.adjusted() <= 12 else str(value)


def _split_unit(unit_raw: str, label: str, supported: str) -> str:
    if unit_raw == "":
        raise ValueError(
            f"{label} is missing a unit; use a number followed by a supported unit ({supported})."
        )
    if "," in unit_raw or ";" in unit_raw or _AND_SPLIT.search(unit_raw):
        raise ValueError(f"{label} needs a single value. Enter multiple values in Targets.")
    unit_norm = _SLASH_SPACES.sub("/", unit_raw)
    if re.search(r"\s", unit_norm):
        raise ValueError(f"{label} has an unsupported unit {unit_raw!r}. Supported: {supported}.")
    return unit_norm


def _normalize_single(text: str, label: str, aliases: dict, supported: str, allow_per: bool) -> str:
    if not isinstance(text, str):
        raise ValueError(f"{label} must be text such as '10 mM'.")
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError(f"{label} exceeds the 1000 character limit.")
    stripped = text.strip()
    if stripped == "":
        raise ValueError(f"{label} must be a number followed by a supported unit ({supported}).")
    working = _replace_micro(stripped)
    if allow_per:
        working = _PER_SLASH.sub("/", working)
    match = _NUMBER_AT_START.match(working)
    if not match:
        raise ValueError(
            f"{label} must be a number followed by a supported unit ({supported}); "
            f"got {stripped!r}."
        )
    num_raw = match.group(0)
    unit_raw = working[match.end() :].strip()
    unit_norm = _split_unit(unit_raw, label, supported)
    if unit_norm not in aliases:
        raise ValueError(f"{label} has an unsupported unit {unit_raw!r}. Supported: {supported}.")
    value = _parse_decimal(num_raw, label)
    canonical_number = _number_text(value)
    return f"{canonical_number} {aliases[unit_norm]}"


def normalize_concentration(text: str) -> str:
    """Return canonical concentration text such as '10 mg/mL'."""
    return _normalize_single(text, "Concentration", CONC_ALIASES, CONC_SUPPORTED, True)


def normalize_volume(text: str) -> str:
    """Return canonical volume text such as '0.5 mL'.

    A single trailing per-container phrase ("per tube", "in each tube",
    "per sample", "per well" and listed Italian equivalents, with a
    trailing full stop and clear plural variants) is quantity context for
    the app's one-tube-per-target plan and is removed before parsing.
    """
    if not isinstance(text, str):
        raise ValueError("Volume must be text such as '0.5 mL'.")
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError("Volume exceeds the 1000 character limit.")
    stripped = _strip_volume_context(_replace_micro(text.strip()))
    return _normalize_single(stripped, "Volume", VOLUME_ALIASES, VOLUME_SUPPORTED, False)


def _split_targets_commas(piece: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    for i, ch in enumerate(piece):
        if ch == ",":
            prev = piece[i - 1] if i > 0 else ""
            nxt = piece[i + 1] if i + 1 < len(piece) else ""
            if prev.isdigit() and nxt.isdigit():
                current.append(ch)
            else:
                parts.append("".join(current))
                current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


def _parse_target_entry(entry: str) -> tuple[str, str | None]:
    """Return (canonical_number, canonical_unit or None for bare numbers)."""
    s = _replace_micro(entry.strip())
    s = _PER_SLASH.sub("/", s)
    if _BARE_NUMBER.match(s):
        return (_number_text(_parse_decimal(s, "Target")), None)
    canonical = normalize_concentration(s)
    number, unit = canonical.rsplit(" ", 1)
    return number, unit


def normalize_targets(text: str) -> str:
    """Return canonical target list such as '1 mg/mL, 2 mg/mL'."""
    label = "Targets"
    if not isinstance(text, str):
        raise ValueError(f"{label} must be text such as '1 mM, 2 mM'.")
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError(f"{label} exceeds the 1000 character limit.")
    stripped = text.strip()
    if stripped == "":
        raise ValueError(f"{label} must contain at least one value such as '1 mM'.")
    working = _replace_micro(stripped)
    working = _PER_SLASH.sub("/", working)
    if re.search(r"\d,\d+,\d", working):
        raise ValueError(
            "Targets are ambiguous. Use dot decimals (1.5 mM), "
            "or separate values with comma and space (1, 2 mM)."
        )
    entries: list[str] = []
    for semi_part in working.split(";"):
        for and_part in _AND_SPLIT.split(semi_part):
            for comma_part in _split_targets_commas(and_part):
                entries.append(comma_part.strip())
    # Detect empty entries from leading/trailing/double delimiters.
    for token in entries:
        if token == "":
            raise ValueError("Targets contain an empty entry; use values such as '1 mM, 2 mM'.")
    if len(entries) > MAX_TARGETS:
        raise ValueError(f"Too many targets (maximum {MAX_TARGETS}).")
    if not entries:
        raise ValueError(f"{label} must contain at least one value such as '1 mM'.")
    parsed = [_parse_target_entry(e) for e in entries]
    fully = [p[1] is not None for p in parsed]
    if all(fully):
        return ", ".join(f"{num} {unit}" for num, unit in parsed)
    # Shared trailing unit: bare numbers followed by one fully specified entry.
    if parsed[-1][1] is not None and all(p[1] is None for p in parsed[:-1]):
        shared_unit = parsed[-1][1]
        assert shared_unit is not None
        out = [f"{num} {shared_unit}" for num, _ in parsed]
        return ", ".join(out)
    # Mixed bare and specified units, or missing trailing unit.
    raise ValueError(
        "Targets are ambiguous. Give every value its own unit "
        "or use a shared trailing unit, such as '1, 2 and 3 mg/mL'."
    )
