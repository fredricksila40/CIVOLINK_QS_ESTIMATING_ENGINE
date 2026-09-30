"""Central wastage pipeline — a stage distinct from rounding.

Result records base quantity, wastage %, waste quantity, quantity after
wastage, and whether rounding was applied (always False here: rounding is
a separate explicit stage via qs_engine.core.rounding).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Union

from .decimal_policy import apply_percentage, to_decimal
from .validation import validate_percentage, validate_quantity

Numeric = Union[Decimal, int, str]


@dataclass(frozen=True)
class WastageResult:
    """Transparent record of one wastage application."""
    base_quantity: Decimal
    wastage_pct: Decimal
    wastage_quantity: Decimal
    quantity_after_wastage: Decimal
    rounding_applied: bool = False


def apply_wastage(base_quantity: Numeric, wastage_pct: Numeric) -> WastageResult:
    """Apply wastage_pct (0–100) to base_quantity (>= 0), unrounded.

    No hidden multipliers: every component is exposed on the result.
    """
    base = validate_quantity(base_quantity, "base_quantity")
    pct = validate_percentage(wastage_pct, "wastage_pct")
    waste = apply_percentage(base, pct)
    return WastageResult(
        base_quantity=base,
        wastage_pct=pct,
        wastage_quantity=waste,
        quantity_after_wastage=base + waste,
        rounding_applied=False,
    )
