"""Labour result contracts (Phase 7).

Frozen dataclasses. Gang-days stay fractional (hiring-day rounding is a
procurement decision, not a calculation step). Person-hours exist only on
hourly rate bases; on daily bases they are None, never derived from an
assumed working day.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple


@dataclass(frozen=True)
class ResolvedLabourTrade:
    """One trade resolved to usable productivity and rates."""
    trade_key: str
    work_unit: str
    output_per_day: Decimal
    gang_skilled: int
    gang_unskilled: int
    skilled_rate: Decimal
    unskilled_rate: Decimal
    rate_unit: str
    master_version: str = ""
    overrides_used: bool = False
    overridden_fields: Tuple[str, ...] = ()


@dataclass(frozen=True)
class LabourRequirement:
    """Activity labour: gang duration, person-time split, cost."""
    element: str
    work_quantity: Decimal
    work_unit: str
    duration_gang_days: Decimal
    skilled_person_days: Decimal
    unskilled_person_days: Decimal
    skilled_person_hours: Optional[Decimal]
    unskilled_person_hours: Optional[Decimal]
    gang_cost_per_day: Decimal
    total_cost: Decimal
    hours_per_day: Optional[Decimal]
    resolved_trade: ResolvedLabourTrade
