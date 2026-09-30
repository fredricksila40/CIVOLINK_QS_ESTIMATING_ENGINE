"""Assumption-register schema.

Every engineering constant the QS engine will ever use must be describable
as an AssumptionRecord carrying source/version/effective-date metadata and
a verification status. Unverified values stay NULL — they are never
populated from memory or "common industry knowledge".
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Union

from .decimal_policy import to_decimal
from .errors import ValidationError

Numeric = Union[Decimal, int, str]


class VerificationStatus:
    """Lifecycle of an engineering assumption."""
    NEEDS_VERIFICATION = "NEEDS_VERIFICATION"
    PROVISIONAL = "PROVISIONAL"
    VERIFIED = "VERIFIED"

    ALL = (NEEDS_VERIFICATION, PROVISIONAL, VERIFIED)


@dataclass(frozen=True)
class AssumptionRecord:
    """One engineering assumption with full provenance.

    value may be None (and MUST be None while NEEDS_VERIFICATION unless a
    provisional figure is explicitly supplied with status PROVISIONAL).
    """
    key: str
    name: str
    value: Optional[Decimal]
    unit: str
    description: str = ""
    source: str = ""
    source_type: str = ""
    standard: str = ""
    version: str = ""
    effective_date: str = ""
    verification_status: str = VerificationStatus.NEEDS_VERIFICATION
    notes: str = ""

    def __post_init__(self):
        if self.value is not None and not isinstance(self.value, Decimal):
            object.__setattr__(self, "value", to_decimal(self.value, "value"))


def validate_assumption(record: AssumptionRecord) -> AssumptionRecord:
    """Validate an assumption record; return it unchanged if valid."""
    if not isinstance(record, AssumptionRecord):
        raise ValidationError(
            f"Expected AssumptionRecord; got {type(record).__name__}"
        )
    if not record.key or not record.key.strip():
        raise ValidationError("Assumption key must be non-empty")
    if not record.name or not record.name.strip():
        raise ValidationError(f"Assumption {record.key!r} must have a name")
    if not record.unit or not record.unit.strip():
        raise ValidationError(f"Assumption {record.key!r} must declare a unit")
    if record.verification_status not in VerificationStatus.ALL:
        raise ValidationError(
            f"Assumption {record.key!r} has unknown status "
            f"{record.verification_status!r}; expected one of "
            f"{list(VerificationStatus.ALL)}"
        )
    if record.verification_status == VerificationStatus.VERIFIED:
        if record.value is None:
            raise ValidationError(
                f"Assumption {record.key!r} is VERIFIED but has no value"
            )
        if not record.source or not record.source.strip():
            raise ValidationError(
                f"Assumption {record.key!r} is VERIFIED but cites no source"
            )
    return record
