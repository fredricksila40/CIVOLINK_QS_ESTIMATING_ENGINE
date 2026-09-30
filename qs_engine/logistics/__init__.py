"""Logistics, haulage, and truck/tonnage engine (Phase 8).

Bin capacity (struck, or explicitly heaped), volume-vs-weight limiting
loads, round-trip cycles, trip/fleet planning against daily targets, and
per-trip/tonne/m3 pricing with hire and fuel kept distinct. Fail-closed
on unverified master data unless complete explicit overrides supplied.
"""

from .engine import (
    HIRE_UNIT_DAY,
    HIRE_UNIT_HOUR,
    HIRE_UNIT_TRIP,
    RECORD_KEYS,
    TARGET_M3,
    TARGET_TONNE,
    TRUCK_FIELDS,
    TruckOverride,
    bin_volume,
    cycle_time_minutes,
    daily_throughput,
    fleet_size,
    fuel_per_trip,
    hire_cost_per_trip,
    limiting_load,
    load_tonnage,
    plan_haulage,
    price_haulage,
    resolve_truck,
    trip_total_cost,
    trips_per_day,
    unit_costs,
)
from .results import (
    LIMIT_VOLUME,
    LIMIT_WEIGHT,
    HaulageCosts,
    HaulagePlan,
    LimitingLoad,
    ResolvedTruck,
)

__all__ = [
    "HIRE_UNIT_DAY", "HIRE_UNIT_HOUR", "HIRE_UNIT_TRIP",
    "RECORD_KEYS", "TARGET_M3", "TARGET_TONNE", "TRUCK_FIELDS",
    "TruckOverride", "bin_volume", "cycle_time_minutes",
    "daily_throughput", "fleet_size", "fuel_per_trip",
    "hire_cost_per_trip", "limiting_load", "load_tonnage",
    "plan_haulage", "price_haulage", "resolve_truck",
    "trip_total_cost", "trips_per_day", "unit_costs",
    "LIMIT_VOLUME", "LIMIT_WEIGHT", "HaulageCosts", "HaulagePlan",
    "LimitingLoad", "ResolvedTruck",
]
