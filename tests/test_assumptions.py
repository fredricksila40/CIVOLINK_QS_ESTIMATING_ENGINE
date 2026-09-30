"""Assumption-register tests: provenance enforced, unverified stays null."""

from decimal import Decimal

import pytest

from qs_engine.core.assumptions import (
    AssumptionRecord,
    VerificationStatus,
    validate_assumption,
)
from qs_engine.core.errors import ValidationError


def make_record(**overrides):
    fields = {
        "key": "cement_bag_mass",
        "name": "Cement bag mass",
        "value": None,
        "unit": "kg/bag",
        "verification_status": VerificationStatus.NEEDS_VERIFICATION,
    }
    fields.update(overrides)
    return AssumptionRecord(**fields)


def test_unverified_null_value_valid():
    record = make_record()
    assert validate_assumption(record) is record
    assert record.value is None


def test_provisional_value_accepted():
    record = make_record(
        verification_status=VerificationStatus.PROVISIONAL,
        value=Decimal("50"),
        source="pending confirmation",
    )
    assert validate_assumption(record).value == Decimal("50")


def test_verified_requires_value_and_source():
    with pytest.raises(ValidationError):
        validate_assumption(make_record(
            verification_status=VerificationStatus.VERIFIED,
            value=Decimal("50"),
            source="",
        ))
    with pytest.raises(ValidationError):
        validate_assumption(make_record(
            verification_status=VerificationStatus.VERIFIED,
            value=None,
            source="Some Standard",
        ))
    ok = make_record(
        verification_status=VerificationStatus.VERIFIED,
        value=Decimal("50"),
        source="Manufacturer datasheet X",
        standard="KEBS",
        version="2024",
        effective_date="2024-01-01",
    )
    assert validate_assumption(ok).value == Decimal("50")


def test_key_name_unit_required():
    with pytest.raises(ValidationError):
        validate_assumption(make_record(key="  "))
    with pytest.raises(ValidationError):
        validate_assumption(make_record(name=""))
    with pytest.raises(ValidationError):
        validate_assumption(make_record(unit=""))


def test_unknown_status_rejected():
    with pytest.raises(ValidationError):
        validate_assumption(make_record(verification_status="TRUST_ME"))


def test_non_record_rejected():
    with pytest.raises(ValidationError):
        validate_assumption({"key": "x"})


def test_str_value_coerced_to_decimal():
    record = make_record(value="1440")
    assert record.value == Decimal("1440")
