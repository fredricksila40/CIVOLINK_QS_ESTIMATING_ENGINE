"""Foundational typed data models (Phase 0: contracts only, no BOQ system yet).

All precision-sensitive fields are Decimal. All models are frozen
dataclasses. Quantity, unit, rate, and total are kept distinct by
construction — see CostLine and BOQItem.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Mapping, Optional, Tuple

from ..core.decimal_policy import to_decimal
from ..core.errors import ValidationError
from ..core.rounding import RoundingResult
from ..core.units import SUPPORTED_UNITS
from ..core.validation import validate_quantity, validate_rate
from ..core.wastage import WastageResult

# BOQ line provenance: generated, hand-entered, or generated-then-edited.
BOQ_SOURCE_CALCULATED = "calculated"
BOQ_SOURCE_MANUAL = "manual"
BOQ_SOURCE_OVERRIDDEN = "overridden"
BOQ_SOURCES = (BOQ_SOURCE_CALCULATED, BOQ_SOURCE_MANUAL, BOQ_SOURCE_OVERRIDDEN)


@dataclass(frozen=True)
class MasterRecord:
    """One row of a master-data table with its provenance."""
    domain: str
    key: str
    attributes: Dict[str, object] = field(default_factory=dict)
    source: str = ""
    version: str = ""
    effective_date: str = ""
    verification_status: str = "NEEDS_VERIFICATION"


@dataclass(frozen=True)
class Quantity:
    """A numeric amount bound to an explicit supported unit."""
    value: Decimal
    unit: str

    def __post_init__(self):
        object.__setattr__(self, "value", to_decimal(self.value, "value"))
        if self.unit not in SUPPORTED_UNITS:
            from ..core.errors import UnknownUnitError
            raise UnknownUnitError(f"Unknown unit: {self.unit!r}")


@dataclass(frozen=True)
class TakeoffResult:
    """Geometry-only take-off output (no materials, no costs)."""
    element: str
    quantity: Quantity
    method: str = ""
    assumptions: Tuple[str, ...] = ()


@dataclass(frozen=True)
class MaterialRequirement:
    """A material quantity derived from take-off, pre-costing.

    wastage holds the (unrounded) wastage stage; ordering holds the
    explicit ceiling stage (or None when the quantity stays fractional).
    master_version pins the table version the requirement was resolved with.
    """
    material_key: str
    quantity: Quantity
    wastage: Optional[WastageResult] = None
    ordering: Optional[RoundingResult] = None
    master_version: str = ""


@dataclass(frozen=True)
class CostLine:
    """Unit-rate build-up kept as separate, auditable components.

    quantity/unit describe WHAT is measured; the *_cost fields describe
    the rate build-up PER UNIT; direct_cost and selling_amount are the
    derived totals. Nothing is merged or hidden.
    """
    description: str
    quantity: Decimal
    unit: str
    material_cost_per_unit: Decimal = Decimal("0")
    labour_cost_per_unit: Decimal = Decimal("0")
    plant_cost_per_unit: Decimal = Decimal("0")
    other_cost_per_unit: Decimal = Decimal("0")
    overhead_per_unit: Decimal = Decimal("0")
    profit_per_unit: Decimal = Decimal("0")

    def __post_init__(self):
        validate_quantity(self.quantity, "quantity")
        for fname in ("material_cost_per_unit", "labour_cost_per_unit",
                      "plant_cost_per_unit", "other_cost_per_unit",
                      "overhead_per_unit", "profit_per_unit"):
            validate_rate(getattr(self, fname), fname)

    @property
    def direct_cost_per_unit(self) -> Decimal:
        return (self.material_cost_per_unit + self.labour_cost_per_unit
                + self.plant_cost_per_unit + self.other_cost_per_unit)

    @property
    def selling_rate_per_unit(self) -> Decimal:
        return self.direct_cost_per_unit + self.overhead_per_unit + self.profit_per_unit

    @property
    def total_amount(self) -> Decimal:
        return self.quantity * self.selling_rate_per_unit


_PROVENANCE_KEYS = ("key", "source", "version", "effective_date",
                    "verification_status")


def master_record_from(domain: str, record: Mapping) -> MasterRecord:
    """Wrap a validated master-data record dict as a typed MasterRecord.

    Provenance fields map onto MasterRecord; everything else becomes
    attributes. Use with MasterDataRepository.get().
    """
    attributes = {k: v for k, v in record.items() if k not in _PROVENANCE_KEYS}
    return MasterRecord(
        domain=domain,
        key=str(record["key"]),
        attributes=attributes,
        source=str(record.get("source", "")),
        version=str(record.get("version", "")),
        effective_date=str(record.get("effective_date", "")),
        verification_status=str(record.get("verification_status", "")),
    )


@dataclass(frozen=True)
class BOQItem:
    """One priced BOQ line. Source tracks generated vs manual vs overridden."""
    description: str
    unit: str
    quantity: Decimal
    rate: Decimal
    amount: Decimal
    source: str = BOQ_SOURCE_CALCULATED
    origin_ref: str = ""
    master_versions: Tuple[str, ...] = ()

    def __post_init__(self):
        validate_quantity(self.quantity, "quantity")
        validate_rate(self.rate, "rate")
        validate_rate(self.amount, "amount")
        if self.source not in BOQ_SOURCES:
            raise ValidationError(
                f"BOQItem source must be one of {list(BOQ_SOURCES)}; "
                f"got {self.source!r}"
            )
