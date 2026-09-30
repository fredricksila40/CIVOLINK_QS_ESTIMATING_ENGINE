"""Ceiling tests: explicit ordering rounding, calculated quantity preserved."""

from decimal import Decimal

import pytest

from qs_engine.core.errors import NegativeQuantityError
from qs_engine.core.rounding import CEILABLE_UNITS, apply_ceiling, ceiling_units


def test_ceiling_fractional():
    # The canonical cement example: 10.24 calculated -> 11 ordered.
    assert ceiling_units(Decimal("10.24")) == 11


def test_ceiling_exact_integer_unchanged():
    assert ceiling_units(Decimal("11")) == 11


def test_ceiling_small_fraction():
    assert ceiling_units(Decimal("0.01")) == 1


def test_ceiling_zero():
    assert ceiling_units(Decimal("0")) == 0


def test_ceiling_rejects_negative():
    with pytest.raises(NegativeQuantityError):
        ceiling_units(Decimal("-1"))


def test_apply_ceiling_preserves_calculated():
    result = apply_ceiling(Decimal("10.24"), "bag")
    assert result.calculated_quantity == Decimal("10.24")
    assert result.ordering_quantity == 11
    assert result.unit == "bag"
    assert result.ceiling_applied is True


def test_apply_ceiling_each_count_unit():
    for unit in ("bag", "piece", "pair", "set", "sheet"):
        result = apply_ceiling("2.1", unit)
        assert result.ordering_quantity == 3
        assert result.unit == unit


def test_apply_ceiling_rejects_fractional_units():
    for unit in ("m", "m\u00b3", "kg", "L"):
        with pytest.raises(ValueError):
            apply_ceiling("2.1", unit)


def test_apply_ceiling_rejects_negative():
    with pytest.raises(NegativeQuantityError):
        apply_ceiling("-2.1", "bag")


def test_ceiling_is_never_implicit():
    # RoundingResult only exists when the caller asked for it.
    result = apply_ceiling(10, "piece")
    assert result.calculated_quantity == Decimal("10")
    assert result.ordering_quantity == 10
    assert set(CEILABLE_UNITS) == {"bag", "piece", "pair", "set", "sheet", "tonne"}
