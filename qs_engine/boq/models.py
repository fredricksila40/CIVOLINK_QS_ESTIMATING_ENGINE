"""BOQ domain models (Phase 10).

Inputs (Boq/BoqSection/BoqSubsection/BoqItem) are validated structure;
outputs (CompiledBoq/CompiledSection/CompiledItem) are the compiler's
deterministic product. Money is Decimal throughout; amounts are exact
(no compilation rounding — rounding is presentation).

Status vocabulary (compile OUTPUT, never input):
  priced ....... quantity x rate resolved
  provisional .. lump allowance explicitly provided
  unpriced ..... explicitly not priced (amount None — never zero)
  unresolved ... measurement rule required but missing/unverified
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Mapping, Optional, Tuple

from ..contracts.models import Quantity, TakeoffResult
from ..core.decimal_policy import to_decimal
from ..core.errors import ValidationError
from ..core.units import SUPPORTED_UNITS
from ..core.validation import validate_quantity, validate_rate
from ..rates.results import CompositeRate
from .measurement import MeasurementRule

#: Pricing kinds (input-side classification).
PRICING_PRICED = "priced"
PRICING_EXPLICIT = "explicit"
PRICING_PROVISIONAL = "provisional"
PRICING_UNPRICED = "unpriced"

#: Compile-output statuses.
STATUS_PRICED = "priced"
STATUS_PROVISIONAL = "provisional"
STATUS_UNPRICED = "unpriced"
STATUS_UNRESOLVED = "unresolved"

#: The single non-measured unit permitted, and only for provisional sums.
UNIT_SUM = "sum"


@dataclass(frozen=True)
class ItemPricing:
    """How a BOQ item is priced. Exactly one value path is populated;
    use the module constructors — never build ambiguous instances."""
    kind: str
    rate: Optional[Decimal] = None
    amount: Optional[Decimal] = None
    rate_ref: str = ""

    def __post_init__(self):
        if self.kind not in (PRICING_PRICED, PRICING_EXPLICIT,
                             PRICING_PROVISIONAL, PRICING_UNPRICED):
            raise ValidationError(f"Unknown pricing kind {self.kind!r}")


def priced_rate(rate_result: CompositeRate, rate_ref: str = "") -> ItemPricing:
    """Price from a Phase 9 CompositeRate (its gross rate is the source)."""
    if not isinstance(rate_result, CompositeRate):
        raise ValidationError(
            f"priced_rate needs a CompositeRate; "
            f"got {type(rate_result).__name__}")
    return ItemPricing(kind=PRICING_PRICED, rate=rate_result.gross_rate,
                       rate_ref=rate_ref)


def explicit_rate(rate, rate_ref: str = "") -> ItemPricing:
    """Price from an externally established rate with its reference."""
    return ItemPricing(kind=PRICING_EXPLICIT,
                       rate=validate_rate(to_decimal(rate, "rate"), "rate"),
                       rate_ref=rate_ref)


def provisional_sum(amount, rate_ref: str = "") -> ItemPricing:
    """Lump provisional/PC allowance (amount stored directly)."""
    return ItemPricing(kind=PRICING_PROVISIONAL,
                       amount=validate_rate(to_decimal(amount, "amount"),
                                            "amount"),
                       rate_ref=rate_ref)


def unpriced_item() -> ItemPricing:
    """Explicitly not priced — amount will be None, never zero."""
    return ItemPricing(kind=PRICING_UNPRICED)


@dataclass(frozen=True)
class BoqItem:
    """One BOQ line as validated compiler input."""
    description: str
    trade: str
    unit: str
    quantity: Decimal
    pricing: ItemPricing
    measurement: Optional[MeasurementRule] = None
    takeoff: Optional[TakeoffResult] = None
    takeoff_ref: str = ""
    rate_result: Optional[CompositeRate] = None
    item_no: Optional[str] = None
    notes: str = ""

    def __post_init__(self):
        if not self.description or not self.description.strip():
            raise ValidationError("BOQ item description must be non-empty")
        if not self.trade or not self.trade.strip():
            raise ValidationError(
                f"BOQ item {self.description!r} must declare a trade")
        if not isinstance(self.pricing, ItemPricing):
            raise ValidationError("BOQ item pricing must be an ItemPricing")
        if (self.unit == UNIT_SUM
                and self.pricing.kind != PRICING_PROVISIONAL):
            raise ValidationError(
                f"Unit 'sum' is only permitted for provisional sums; "
                f"got pricing kind {self.pricing.kind!r}")
        if self.unit not in SUPPORTED_UNITS and self.unit != UNIT_SUM:
            from ..core.errors import UnknownUnitError
            raise UnknownUnitError(f"Unknown unit: {self.unit!r}")
        object.__setattr__(self, "quantity",
                           validate_quantity(self.quantity, "quantity"))
        if (self.pricing.kind == PRICING_PRICED
                and self.rate_result is None):
            raise ValidationError(
                f"BOQ item {self.description!r} is priced from a build-up "
                f"but carries no rate_result for traceability")


@dataclass(frozen=True)
class BoqSubsection:
    """Ordered item group within a section (at least one item)."""
    code: str
    title: str
    items: Tuple[BoqItem, ...]

    def __post_init__(self):
        if not self.code or not self.code.strip():
            raise ValidationError("Subsection code must be non-empty")
        if not self.items:
            raise ValidationError(
                f"Subsection {self.code!r} must contain at least one item")


@dataclass(frozen=True)
class BoqSection:
    """Ordered subsection group (at least one subsection)."""
    code: str
    title: str
    subsections: Tuple[BoqSubsection, ...]

    def __post_init__(self):
        if not self.code or not self.code.strip():
            raise ValidationError("Section code must be non-empty")
        if not self.subsections:
            raise ValidationError(
                f"Section {self.code!r} must contain at least one subsection")

    @staticmethod
    def single(code: str, title: str,
               items: Tuple[BoqItem, ...]) -> "BoqSection":
        """Convenience: one default subsection for sections needing none."""
        return BoqSection(code=code, title=title, subsections=(
            BoqSubsection(code=f"{code}.1",
                          title=f"{title} (General)", items=tuple(items)),))


@dataclass(frozen=True)
class Boq:
    """A complete priced-document input: ordered sections under refs."""
    project_ref: str
    boq_ref: str
    sections: Tuple[BoqSection, ...]
    notes: str = ""

    def __post_init__(self):
        if not self.project_ref or not self.project_ref.strip():
            raise ValidationError("BOQ project_ref must be non-empty")
        if not self.boq_ref or not self.boq_ref.strip():
            raise ValidationError("BOQ boq_ref must be non-empty")
        if not self.sections:
            raise ValidationError("BOQ must contain at least one section")


@dataclass(frozen=True)
class CompiledItem:
    """One compiled line: number, money, status, and traceability.

    takeoff and rate_result carry the originating engine objects (when
    the input supplied them) so lineage is structural, not just string
    refs. Both default None for hand-built or legacy lines.
    """
    item_no: str
    description: str
    section_code: str
    subsection_code: str
    trade: str
    unit: str
    quantity: Decimal
    rate: Optional[Decimal]
    amount: Optional[Decimal]
    status: str
    pricing_kind: str
    rate_ref: str
    takeoff_ref: str
    measurement_ref: Optional[str]
    provenance: Tuple[str, ...]
    notes: str = ""
    takeoff: Optional[TakeoffResult] = None
    rate_result: Optional[CompositeRate] = None


@dataclass(frozen=True)
class CompiledSubsection:
    """Compiled subsection: title plus its item numbers in order."""
    code: str
    title: str
    item_nos: Tuple[str, ...] = ()


@dataclass(frozen=True)
class CompiledSection:
    """Compiled section: ordered items, totals, and unresolved flags."""
    code: str
    title: str
    items: Tuple[CompiledItem, ...]
    total: Optional[Decimal]
    resolved_subtotal: Decimal
    has_unresolved: bool
    subsections: Tuple[CompiledSubsection, ...] = ()


@dataclass(frozen=True)
class CompiledBoq:
    """Compiled document: ordered sections and honest totals.

    total is None whenever any item is unpriced or unresolved;
    resolved_subtotal always sums what IS priced. unresolved_items
    names every non-priced line for follow-up.
    """
    project_ref: str
    boq_ref: str
    sections: Tuple[CompiledSection, ...]
    total: Optional[Decimal]
    resolved_subtotal: Decimal
    has_unresolved: bool
    unresolved_items: Tuple[str, ...]
