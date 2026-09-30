"""Wastage pipeline tests: transparent stages, separation from rounding."""

from decimal import Decimal

import pytest

from qs_engine.core.errors import PercentageRangeError
from qs_engine.core.rounding import apply_ceiling
from qs_engine.core.wastage import apply_wastage


def test_conceptual_example():
    # Base 100, 5% -> waste 5, after 105.
    result = apply_wastage(Decimal("100"), Decimal("5"))
    assert result.base_quantity == Decimal("100")
    assert result.wastage_pct == Decimal("5")
    assert result.wastage_quantity == Decimal("5")
    assert result.quantity_after_wastage == Decimal("105")
    assert result.rounding_applied is False


def test_zero_wastage():
    result = apply_wastage("50", "0")
    assert result.wastage_quantity == Decimal("0")
    assert result.quantity_after_wastage == Decimal("50")


def test_zero_base():
    result = apply_wastage("0", "10")
    assert result.quantity_after_wastage == Decimal("0")


def test_wastage_unrounded():
    # 1/3-style fractions stay exact; rounding is a later explicit stage.
    result = apply_wastage(Decimal("10"), Decimal("33.333"))
    assert result.wastage_quantity == Decimal("3.3333")
    assert result.quantity_after_wastage == Decimal("13.3333")


def test_wastage_rejects_out_of_range():
    with pytest.raises(PercentageRangeError):
        apply_wastage("100", "100.01")
    with pytest.raises(PercentageRangeError):
        apply_wastage("100", "-1")


def test_wastage_then_ceiling_are_separate_stages():
    # 100 units + 5% = 105 exact; ceiling stage sees 105, not a hidden 105.x.
    wasted = apply_wastage("100", "5")
    assert wasted.rounding_applied is False
    ordered = apply_ceiling(wasted.quantity_after_wastage, "piece")
    assert ordered.calculated_quantity == Decimal("105")
    assert ordered.ordering_quantity == 105
    # And a fractional case keeps both stages visible.
    wasted2 = apply_wastage("10.24", "0")
    ordered2 = apply_ceiling(wasted2.quantity_after_wastage, "bag")
    assert ordered2.calculated_quantity == Decimal("10.24")
    assert ordered2.ordering_quantity == 11
