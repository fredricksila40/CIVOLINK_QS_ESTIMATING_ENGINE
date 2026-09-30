"""Logistics result contracts (Phase 8).

Frozen dataclasses. Volume-limited vs weight-limited loads, exact vs
ordered trips, and hire vs fuel cost components are never merged.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

LIMIT_VOLUME = "volume"
LIMIT_WEIGHT = "weight"


@dataclass(frozen=True)
class ResolvedTruck:
    """One vehicle resolved to usable planning numerics.

    hire_rate and fuel_burn_L_per_hr may be None (costing of that
    component explicitly unavailable); every other numeric is required
    from verified records or complete overrides.
    """
    truck_key: str
    body_length_m: Decimal
    body_width_m: Decimal
    body_height_m: Decimal
    payload_limit_tonnes: Decimal
    payload_tonnes: Decimal
    load_time_min: Decimal
    unload_time_min: Decimal
    speed_loaded_kmh: Decimal
    speed_empty_kmh: Decimal
    hire_rate: Optional[Decimal]
    hire_rate_unit: str
    fuel_burn_L_per_hr: Optional[Decimal]
    master_version: str = ""
    overrides_used: bool = False
    overridden_fields: Tuple[str, ...] = ()


@dataclass(frozen=True)
class LimitingLoad:
    """One laden trip: the binding constraint is named, both states kept."""
    load_m3: Decimal
    load_tonnes: Decimal
    limiting: str  # LIMIT_VOLUME or LIMIT_WEIGHT


@dataclass(frozen=True)
class HaulagePlan:
    """Trip/fleet plan for a loose volume (costing is a separate step)."""
    element: str
    total_loose_m3: Decimal
    limiting_load: LimitingLoad
    cycle_minutes: Decimal
    trips_exact: Decimal
    trips_ordered: int
    target_per_day: Decimal
    target_unit: str
    daily_capacity_per_truck: Decimal
    trucks_required: int
    daily_capacity_total: Decimal
    resolved_truck: ResolvedTruck


@dataclass(frozen=True)
class HaulageCosts:
    """Priced trips: hire + fuel components kept distinct with unit rates."""
    trips_charged: int
    hire_per_trip: Decimal
    fuel_per_trip: Optional[Decimal]
    cost_per_trip: Decimal
    cost_per_tonne: Decimal
    cost_per_m3: Decimal
