"""Plant result contracts (Phase 7).

Frozen dataclasses. Durations stay in the output basis (hours or days)
with no assumed conversion between them. Operating cost is Optional:
absent means explicitly not estimated, never zero.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple


@dataclass(frozen=True)
class ResolvedPlant:
    """One machine resolved to usable output and rates."""
    equipment_key: str
    work_unit: str
    output_per_unit: Decimal
    output_basis: str
    rate: Decimal
    rate_unit: str
    hire_basis: str
    operating_cost_per_hour: Optional[Decimal]
    master_version: str = ""
    overrides_used: bool = False
    overridden_fields: Tuple[str, ...] = ()


@dataclass(frozen=True)
class PlantRequirement:
    """Machine duty: duration, hire cost, operating cost, total."""
    element: str
    work_quantity: Decimal
    work_unit: str
    duration_value: Decimal
    duration_basis: str
    hire_cost: Decimal
    operating_hours: Optional[Decimal]
    operating_cost: Optional[Decimal]
    total_cost: Decimal
    hours_per_day: Optional[Decimal]
    resolved_plant: ResolvedPlant
