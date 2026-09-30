"""Decimal policy: exact decimal arithmetic everywhere precision matters.

Binary floating-point MUST NOT be used for quantities, densities, rates,
costs, percentages, conversion factors, or monetary amounts. Float inputs
are rejected outright so imprecision can never enter silently.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Union

MONEY_PLACES = 2

DecimalLike = Union[Decimal, int, str]


def to_decimal(value: DecimalLike, name: str = "value") -> Decimal:
    """Coerce int/str/Decimal to Decimal. Rejects float (and anything else)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError(f"{name}: bool is not an accepted numeric type")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise TypeError(f"{name}: empty string is not numeric")
        try:
            return Decimal(text)
        except Exception as exc:
            raise TypeError(f"{name}: cannot parse {value!r} as Decimal") from exc
    raise TypeError(
        f"{name}: expected Decimal, int or numeric str; got {type(value).__name__} "
        "(float is rejected to protect precision)"
    )


def quantize(value: DecimalLike, places: int, rounding=ROUND_HALF_UP) -> Decimal:
    """Round explicitly to a fixed number of decimal places.

    Use only at presentation/output boundaries — never silently inside a chain.
    """
    if places < 0:
        raise ValueError("places must be >= 0")
    quantum = Decimal(1).scaleb(-places)
    return to_decimal(value).quantize(quantum, rounding=rounding)


def quantize_money(value: DecimalLike) -> Decimal:
    """Round a monetary amount to 2dp (KES). Output boundary only."""
    return quantize(value, MONEY_PLACES)


def apply_percentage(base: DecimalLike, percent: DecimalLike) -> Decimal:
    """Return base * percent / 100 exactly (unrounded — caller decides rounding)."""
    b = to_decimal(base, "base")
    p = to_decimal(percent, "percent")
    return (b * p) / Decimal(100)
