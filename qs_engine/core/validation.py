"""Input validation. Every check fails closed with a typed error."""

from decimal import Decimal
from typing import Mapping, Union

from .decimal_policy import to_decimal
from .errors import (
    MissingFieldError,
    NegativeQuantityError,
    NegativeRateError,
    NonPositiveDensityError,
    NonPositiveDimensionError,
    PercentageRangeError,
    UnknownMasterDataKeyError,
)

Numeric = Union[Decimal, int, str]


def require_present(mapping: Mapping, field: str):
    """Return mapping[field]; raise MissingFieldError if absent or None."""
    if field not in mapping or mapping[field] is None:
        raise MissingFieldError(f"Required field missing: {field!r}")
    return mapping[field]


def validate_dimension(value: Numeric, name: str = "dimension") -> Decimal:
    """Dimensions (length/width/thickness/height) must be > 0."""
    amount = to_decimal(value, name)
    if amount <= 0:
        raise NonPositiveDimensionError(f"{name} must be > 0; got {amount}")
    return amount


def validate_quantity(value: Numeric, name: str = "quantity") -> Decimal:
    """Quantities must be >= 0."""
    amount = to_decimal(value, name)
    if amount < 0:
        raise NegativeQuantityError(f"{name} must be >= 0; got {amount}")
    return amount


def validate_density(value: Numeric, name: str = "density") -> Decimal:
    """Densities must be > 0."""
    amount = to_decimal(value, name)
    if amount <= 0:
        raise NonPositiveDensityError(f"{name} must be > 0; got {amount}")
    return amount


def validate_rate(value: Numeric, name: str = "rate") -> Decimal:
    """Rates/costs must be >= 0."""
    amount = to_decimal(value, name)
    if amount < 0:
        raise NegativeRateError(f"{name} must be >= 0; got {amount}")
    return amount


def validate_percentage(
    value: Numeric,
    name: str = "percentage",
    minimum: Numeric = 0,
    maximum: Numeric = 100,
) -> Decimal:
    """Percentages must lie within [minimum, maximum] (default 0–100)."""
    amount = to_decimal(value, name)
    lo = to_decimal(minimum, "minimum")
    hi = to_decimal(maximum, "maximum")
    if amount < lo or amount > hi:
        raise PercentageRangeError(
            f"{name} must be within [{lo}, {hi}]; got {amount}"
        )
    return amount


def require_master_key(records: Mapping, key: str, domain: str):
    """Return records[key]; raise UnknownMasterDataKeyError if absent."""
    try:
        return records[key]
    except KeyError:
        raise UnknownMasterDataKeyError(
            f"Unknown key {key!r} in master-data domain {domain!r}"
        ) from None
