"""Validation tests: every rule fails closed with its typed error."""

from decimal import Decimal

import pytest

from qs_engine.core.errors import (
    MissingFieldError,
    NegativeQuantityError,
    NegativeRateError,
    NonPositiveDensityError,
    NonPositiveDimensionError,
    PercentageRangeError,
    UnknownMasterDataKeyError,
)
from qs_engine.core.validation import (
    require_master_key,
    require_present,
    validate_density,
    validate_dimension,
    validate_percentage,
    validate_quantity,
    validate_rate,
)


def test_dimension_must_be_positive():
    assert validate_dimension(Decimal("0.2")) == Decimal("0.2")
    with pytest.raises(NonPositiveDimensionError):
        validate_dimension(0)
    with pytest.raises(NonPositiveDimensionError):
        validate_dimension("-3")


def test_quantity_allows_zero_rejects_negative():
    assert validate_quantity(0) == Decimal("0")
    with pytest.raises(NegativeQuantityError):
        validate_quantity("-0.01")


def test_density_must_be_positive():
    assert validate_density("1440") == Decimal("1440")
    with pytest.raises(NonPositiveDensityError):
        validate_density(0)


def test_rate_allows_zero_rejects_negative():
    assert validate_rate(0) == Decimal("0")
    with pytest.raises(NegativeRateError):
        validate_rate("-1")


def test_percentage_default_range():
    assert validate_percentage(0) == Decimal("0")
    assert validate_percentage(100) == Decimal("100")
    assert validate_percentage("5.5") == Decimal("5.5")
    with pytest.raises(PercentageRangeError):
        validate_percentage("-0.1")
    with pytest.raises(PercentageRangeError):
        validate_percentage("100.01")


def test_percentage_custom_range():
    assert validate_percentage("50", minimum=10, maximum=90) == Decimal("50")
    with pytest.raises(PercentageRangeError):
        validate_percentage("95", minimum=10, maximum=90)


def test_require_present():
    assert require_present({"a": 1}, "a") == 1
    with pytest.raises(MissingFieldError):
        require_present({}, "a")
    with pytest.raises(MissingFieldError):
        require_present({"a": None}, "a")


def test_require_master_key():
    records = {"cement": {"key": "cement"}}
    assert require_master_key(records, "cement", "materials") == {"key": "cement"}
    with pytest.raises(UnknownMasterDataKeyError):
        require_master_key(records, "unobtainium", "materials")
