"""Decimal policy tests: exactness, float rejection, explicit rounding."""

from decimal import Decimal

import pytest

from qs_engine.core.decimal_policy import (
    MONEY_PLACES,
    apply_percentage,
    quantize,
    quantize_money,
    to_decimal,
)


def test_to_decimal_passthrough():
    assert to_decimal(Decimal("1.23")) == Decimal("1.23")


def test_to_decimal_int():
    assert to_decimal(5) == Decimal("5")


def test_to_decimal_str():
    assert to_decimal(" 2.50 ") == Decimal("2.50")


def test_to_decimal_rejects_float():
    with pytest.raises(TypeError):
        to_decimal(0.1)


def test_to_decimal_rejects_bool_and_empty():
    with pytest.raises(TypeError):
        to_decimal(True)
    with pytest.raises(TypeError):
        to_decimal("   ")
    with pytest.raises(TypeError):
        to_decimal(None)


def test_decimal_preservation_no_binary_error():
    # 0.1 + 0.2 must be exact in Decimal land.
    assert to_decimal("0.1") + to_decimal("0.2") == Decimal("0.3")


def test_quantize_money():
    assert MONEY_PLACES == 2
    assert quantize_money(Decimal("10.245")) == Decimal("10.25")
    assert quantize_money(Decimal("10.244")) == Decimal("10.24")


def test_quantize_custom_places():
    assert quantize(Decimal("1.2345"), 3) == Decimal("1.235")
    with pytest.raises(ValueError):
        quantize(Decimal("1"), -1)


def test_apply_percentage_unrounded():
    # 5% of 100m3 of mortar constituent math stays exact until the caller rounds.
    assert apply_percentage(Decimal("100"), Decimal("5")) == Decimal("5")
    assert apply_percentage(Decimal("3"), Decimal("16")) == Decimal("0.48")
