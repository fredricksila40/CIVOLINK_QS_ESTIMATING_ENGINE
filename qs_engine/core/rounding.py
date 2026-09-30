"""Central ceiling/rounding service.

Ceiling is NEVER automatic: the caller must explicitly request it (bags,
pieces, sheets, pairs, sets, tonnes where appropriate). The unrounded
calculated quantity is always preserved — see RoundingResult.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from typing import Union

from .decimal_policy import to_decimal
from .errors import NegativeQuantityError

#: Unit kinds for which ceiling-to-whole-unit ordering is meaningful.
CEILABLE_UNITS = ("bag", "piece", "pair", "set", "sheet", "tonne")


def ceiling_units(value: Union[Decimal, int, str]) -> int:
    """Return CEILING(value) as an int. Negative inputs are rejected."""
    amount = to_decimal(value, "value")
    if amount < 0:
        raise NegativeQuantityError(
            f"Cannot ceiling a negative ordering quantity: {amount}"
        )
    return int(amount.to_integral_value(rounding=ROUND_CEILING))


@dataclass(frozen=True)
class RoundingResult:
    """Keeps the calculated and ordering quantities side by side.

    calculated_quantity: exact (possibly fractional) engineered quantity.
    ordering_quantity: whole units to order after explicit ceiling.
    unit: the count unit (bag/piece/sheet/…).
    ceiling_applied: always True for results produced by apply_ceiling().
    """
    calculated_quantity: Decimal
    ordering_quantity: int
    unit: str
    ceiling_applied: bool = True


def apply_ceiling(
    calculated_quantity: Union[Decimal, int, str], unit: str
) -> RoundingResult:
    """Explicitly ceiling a calculated quantity for ordering.

    Raises for non-ceilable units so callers cannot silently round
    quantities (e.g. m3, kg) that must stay fractional.
    """
    if unit not in CEILABLE_UNITS:
        raise ValueError(
            f"Ceiling is not defined for unit {unit!r}; "
            f"ceilable units are {list(CEILABLE_UNITS)}"
        )
    amount = to_decimal(calculated_quantity, "calculated_quantity")
    if amount < 0:
        raise NegativeQuantityError(
            f"Cannot ceiling a negative ordering quantity: {amount}"
        )
    return RoundingResult(
        calculated_quantity=amount,
        ordering_quantity=ceiling_units(amount),
        unit=unit,
        ceiling_applied=True,
    )
