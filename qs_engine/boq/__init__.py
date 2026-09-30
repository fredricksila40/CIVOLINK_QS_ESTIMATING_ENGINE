"""BOQ compilation layer (Phase 10).

Validated structure in, deterministic compilation out: ordered sections,
stable numbering, exact Decimal amounts, honest totals (None whenever an
unpriced or unresolved line exists), and full traceability to take-off,
rate build-up, and measurement rules. No calculation logic lives here —
the BOQ layer consumes Phase 0-9 results.
"""

from .compiler import compile_boq
from .measurement import (
    KNOWN_STANDARDS,
    MeasurementRule,
    MeasurementStandard,
    Rulebook,
)
from .models import (
    STATUS_PRICED,
    STATUS_PROVISIONAL,
    STATUS_UNPRICED,
    STATUS_UNRESOLVED,
    UNIT_SUM,
    Boq,
    BoqItem,
    BoqSection,
    BoqSubsection,
    CompiledBoq,
    CompiledItem,
    CompiledSection,
    CompiledSubsection,
    ItemPricing,
    explicit_rate,
    priced_rate,
    provisional_sum,
    unpriced_item,
)

__all__ = [
    "compile_boq",
    "KNOWN_STANDARDS", "MeasurementRule", "MeasurementStandard",
    "Rulebook",
    "STATUS_PRICED", "STATUS_PROVISIONAL", "STATUS_UNPRICED",
    "STATUS_UNRESOLVED", "UNIT_SUM",
    "Boq", "BoqItem", "BoqSection", "BoqSubsection",
    "CompiledBoq", "CompiledItem", "CompiledSection", "CompiledSubsection",
    "ItemPricing",
    "explicit_rate", "priced_rate", "provisional_sum", "unpriced_item",
]
