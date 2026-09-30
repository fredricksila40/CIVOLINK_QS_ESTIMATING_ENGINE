"""Rate build-up result contracts (Phase 9).

Frozen dataclasses. Direct cost, each markup amount, net rate, and gross
rate are carried separately — compounding policy is recorded, never
implied.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

KIND_MATERIAL = "material"
KIND_LABOUR = "labour"
KIND_PLANT = "plant"
KIND_LOGISTICS = "logistics"
KIND_SUBCONTRACT = "subcontract"
KIND_OTHER = "other"

COMPONENT_KINDS = (
    KIND_MATERIAL, KIND_LABOUR, KIND_PLANT,
    KIND_LOGISTICS, KIND_SUBCONTRACT, KIND_OTHER,
)

POLICY_SEQUENTIAL = "sequential"
POLICY_PARALLEL = "parallel"


@dataclass(frozen=True)
class RateComponent:
    """One cost line of a build-up, per work unit."""
    kind: str
    description: str
    cost_per_unit: Decimal
    provisional: bool = False


@dataclass(frozen=True)
class MarkupSpec:
    """One named markup with its percentage (validated 0-1000)."""
    label: str
    pct: Decimal


@dataclass(frozen=True)
class MarkupApplied:
    """One markup with its computed amount and running total."""
    label: str
    pct: Decimal
    amount: Decimal
    running_total: Decimal


@dataclass(frozen=True)
class CompositeRate:
    """Built-up unit rate: net (direct) vs gross (with markups)."""
    element: str
    work_unit: str
    components: Tuple[RateComponent, ...]
    direct_cost_per_unit: Decimal
    markups: Tuple[MarkupApplied, ...]
    markup_policy: str
    net_rate: Decimal
    gross_rate: Decimal

    def total_for(self, quantity) -> Decimal:
        """Gross amount for a work quantity (validated on call)."""
        from ..core.validation import validate_quantity
        return self.gross_rate * validate_quantity(quantity, "quantity")


@dataclass(frozen=True)
class TemplateLine:
    """One structural line of a rate template (values may be null)."""
    kind: str
    ref: str
    qty_per_unit: Optional[Decimal]
    note: str = ""


@dataclass(frozen=True)
class RateTemplate:
    """A build-up structure awaiting prices (BOQ phase binds them)."""
    template_key: str
    name: str
    work_unit: str
    components: Tuple[TemplateLine, ...]
    markups: Tuple[MarkupSpec, ...]
    master_version: str = ""
