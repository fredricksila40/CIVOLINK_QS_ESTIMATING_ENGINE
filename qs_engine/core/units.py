"""Explicit construction units with deterministic Decimal conversions.

Deliberately NOT a generic scientific unit framework: only the conversions
needed by construction take-off are supported. Anything else raises
IncompatibleUnitsError. All factors are exact Decimals.
"""

from decimal import Decimal
from typing import Union

from .decimal_policy import to_decimal
from .errors import IncompatibleUnitsError, UnknownUnitError

# Canonical unit keys
MM = "mm"
CM = "cm"
M = "m"
MM2 = "mm\u00b2"
M2 = "m\u00b2"
MM3 = "mm\u00b3"
M3 = "m\u00b3"
LITRE = "L"
KG = "kg"
TONNE = "tonne"
BAG = "bag"
PIECE = "piece"
PAIR = "pair"
SET = "set"
SHEET = "sheet"
HOUR = "hour"
DAY = "day"

SUPPORTED_UNITS = (
    MM, CM, M, MM2, M2, MM3, M3, LITRE,
    KG, TONNE, BAG, PIECE, PAIR, SET, SHEET, HOUR, DAY,
)

_DIMENSIONS = {
    MM: "length", CM: "length", M: "length",
    MM2: "area", M2: "area",
    MM3: "volume", M3: "volume", LITRE: "volume",
    KG: "mass", TONNE: "mass",
    BAG: "count", PIECE: "count", PAIR: "count", SET: "count", SHEET: "count",
    HOUR: "time", DAY: "time",
}

# (from_unit, to_unit) -> exact multiplicative factor
_CONVERSIONS = {
    (MM, M): Decimal("0.001"),
    (CM, M): Decimal("0.01"),
    (M, MM): Decimal("1000"),
    (M, CM): Decimal("100"),
    (MM2, M2): Decimal("0.000001"),
    (M2, MM2): Decimal("1000000"),
    (MM3, M3): Decimal("0.000000001"),
    (M3, MM3): Decimal("1000000000"),
    (LITRE, M3): Decimal("0.001"),
    (M3, LITRE): Decimal("1000"),
    (KG, TONNE): Decimal("0.001"),
    (TONNE, KG): Decimal("1000"),
}


def dimension_of(unit: str) -> str:
    """Return the dimension family of a supported unit."""
    try:
        return _DIMENSIONS[unit]
    except KeyError:
        raise UnknownUnitError(f"Unknown unit: {unit!r}") from None


def convert(value: Union[Decimal, int, str], from_unit: str, to_unit: str) -> Decimal:
    """Convert value from from_unit to to_unit exactly.

    Identity conversions (same unit) always succeed. Cross-dimension
    conversions raise IncompatibleUnitsError. Unknown units raise
    UnknownUnitError. Float values are rejected by the Decimal policy.
    """
    if from_unit not in _DIMENSIONS:
        raise UnknownUnitError(f"Unknown unit: {from_unit!r}")
    if to_unit not in _DIMENSIONS:
        raise UnknownUnitError(f"Unknown unit: {to_unit!r}")
    amount = to_decimal(value, "value")
    if from_unit == to_unit:
        return amount
    if _DIMENSIONS[from_unit] != _DIMENSIONS[to_unit]:
        raise IncompatibleUnitsError(
            f"Cannot convert {from_unit!r} ({_DIMENSIONS[from_unit]}) "
            f"to {to_unit!r} ({_DIMENSIONS[to_unit]})"
        )
    try:
        factor = _CONVERSIONS[(from_unit, to_unit)]
    except KeyError:
        raise IncompatibleUnitsError(
            f"No defined conversion from {from_unit!r} to {to_unit!r}"
        ) from None
    return amount * factor
