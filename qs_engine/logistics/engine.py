"""Logistics, haulage, and truck/tonnage pipeline (Phase 8).

    bin volume (struck, or heaped by explicit %) -> load tonnage
      -> limiting load (bin fill vs rated payload, binding named)
      -> round-trip cycle (loaded + empty + load + unload)
      -> trips (exact, then ceiled) -> fleet for a daily target
      -> pricing per trip / tonne / m3 (hire + fuel kept distinct)

Loose volumes arrive from earthworks take-off (documented handoff — no
code coupling). Densities here are LOOSE-state and caller-supplied;
bank densities from materials are never reused silently. All arithmetic
Decimal, unrounded until explicit ceiling/quantize boundaries.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Union

from ..core.decimal_policy import to_decimal
from ..core.errors import ValidationError
from ..core.rounding import ceiling_units
from ..core.units import M3, TONNE, convert
from ..core.validation import (
    validate_density,
    validate_dimension,
    validate_percentage,
    validate_quantity,
    validate_rate,
)
from ..master_data import resolve as resolve_master
from .results import (
    LIMIT_VOLUME,
    LIMIT_WEIGHT,
    HaulageCosts,
    HaulagePlan,
    LimitingLoad,
    ResolvedTruck,
)

Numeric = Union[Decimal, int, str]

#: Truck numerics required for planning (hire/fuel stay optional extras).
TRUCK_FIELDS = (
    "body_length_m",
    "body_width_m",
    "body_height_m",
    "payload_limit_tonnes",
    "payload_tonnes",
    "load_time_min",
    "unload_time_min",
    "speed_loaded_kmh",
    "speed_empty_kmh",
)

#: Record keys backing each truck field (1:1 in this domain).
RECORD_KEYS = {field: field for field in TRUCK_FIELDS}

HIRE_UNIT_TRIP = "trip"
HIRE_UNIT_DAY = "day"
HIRE_UNIT_HOUR = "hour"
TARGET_TONNE = "tonne"
TARGET_M3 = "m3"


@dataclass(frozen=True)
class TruckOverride:
    """Complete-or-nothing explicit overrides, except hire/fuel extras.

    hire_rate and fuel_burn_L_per_hr are OPTIONAL extras (None = that
    cost component explicitly unavailable); the nine planning fields
    must be complete for unverified records.
    """
    body_length_m: Optional[Decimal] = None
    body_width_m: Optional[Decimal] = None
    body_height_m: Optional[Decimal] = None
    payload_limit_tonnes: Optional[Decimal] = None
    payload_tonnes: Optional[Decimal] = None
    load_time_min: Optional[Decimal] = None
    unload_time_min: Optional[Decimal] = None
    speed_loaded_kmh: Optional[Decimal] = None
    speed_empty_kmh: Optional[Decimal] = None
    hire_rate: Optional[Decimal] = None
    fuel_burn_L_per_hr: Optional[Decimal] = None

    def __post_init__(self):
        for field_name in (TRUCK_FIELDS + ("hire_rate", "fuel_burn_L_per_hr")):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, Decimal):
                object.__setattr__(
                    self, field_name, to_decimal(value, field_name))

    def missing(self) -> tuple:
        """Required planning fields still None (hire/fuel excluded)."""
        return tuple(f for f in TRUCK_FIELDS if getattr(self, f) is None)

    def is_complete(self) -> bool:
        """True when every required planning field is supplied."""
        return not self.missing()


def bin_volume(body_length_m: Numeric, body_width_m: Numeric,
               body_height_m: Numeric, unit: str = "m",
               heap_pct: Numeric = 0) -> Decimal:
    """Bin capacity in m3. heap_pct defaults to 0 = STRUCK basis unless
    a heaped policy is explicitly stated (0-100)."""
    length_m = convert(validate_dimension(body_length_m, "body_length_m"),
                       unit, "m")
    width_m = convert(validate_dimension(body_width_m, "body_width_m"),
                      unit, "m")
    height_m = convert(validate_dimension(body_height_m, "body_height_m"),
                       unit, "m")
    heap = validate_percentage(heap_pct, "heap_pct")
    return length_m * width_m * height_m * (Decimal("1") + heap / Decimal("100"))


def load_tonnage(volume_m3: Numeric,
                 loose_density_t_per_m3: Numeric) -> Decimal:
    """Load mass in tonnes. Density MUST be loose-state and explicit —
    bank densities are never substituted here."""
    volume = validate_quantity(volume_m3, "volume_m3")
    density = validate_density(loose_density_t_per_m3, "loose_density")
    return volume * density


def limiting_load(bin_volume_m3: Numeric, payload_tonnes: Numeric,
                  loose_density_t_per_m3: Numeric) -> LimitingLoad:
    """One laden trip honouring BOTH constraints, binding one named."""
    bin_vol = validate_quantity(bin_volume_m3, "bin_volume_m3")
    payload = validate_quantity(payload_tonnes, "payload_tonnes")
    density = validate_density(loose_density_t_per_m3, "loose_density")
    weight_at_full_bin = bin_vol * density
    if weight_at_full_bin <= payload:
        return LimitingLoad(load_m3=bin_vol, load_tonnes=weight_at_full_bin,
                            limiting=LIMIT_VOLUME)
    return LimitingLoad(load_m3=payload / density, load_tonnes=payload,
                        limiting=LIMIT_WEIGHT)


def cycle_time_minutes(distance_km: Numeric, speed_loaded_kmh: Numeric,
                       speed_empty_kmh: Numeric, load_time_min: Numeric,
                       unload_time_min: Numeric) -> Decimal:
    """Round-trip minutes: loaded leg + empty return + load + unload."""
    distance = validate_quantity(distance_km, "distance_km")
    speed_l = to_decimal(speed_loaded_kmh, "speed_loaded_kmh")
    speed_e = to_decimal(speed_empty_kmh, "speed_empty_kmh")
    if speed_l <= 0 or speed_e <= 0:
        raise ValidationError(
            f"haul speeds must be > 0; got loaded={speed_l}, "
            f"empty={speed_e}")
    load = validate_quantity(load_time_min, "load_time_min")
    unload = validate_quantity(unload_time_min, "unload_time_min")
    return (distance / speed_l * Decimal("60")
            + distance / speed_e * Decimal("60") + load + unload)


def trips_per_day(available_minutes: Numeric,
                  cycle_minutes: Numeric) -> Decimal:
    """Exact trips per unit per day (fractional kept; caller ceilings)."""
    available = validate_quantity(available_minutes, "available_minutes")
    cycle = to_decimal(cycle_minutes, "cycle_minutes")
    if cycle <= 0:
        raise ValidationError(f"cycle_minutes must be > 0; got {cycle}")
    return available / cycle


def daily_throughput(truck_count: int, trips_each: Numeric,
                     load_per_trip: Numeric) -> Decimal:
    """Daily throughput in the load's unit (tonnes or m3, caller-kept)."""
    if isinstance(truck_count, bool) or not isinstance(truck_count, int):
        raise ValidationError(
            f"truck_count must be an integer; got {truck_count!r}")
    if truck_count < 0:
        raise ValidationError(f"truck_count must be >= 0; got {truck_count}")
    trips = validate_quantity(trips_each, "trips_each")
    load = validate_quantity(load_per_trip, "load_per_trip")
    return truck_count * trips * load


def fleet_size(target_per_day: Numeric, per_truck_per_day: Numeric) -> int:
    """Trucks required for a daily target (same unit both sides)."""
    target = validate_quantity(target_per_day, "target_per_day")
    capacity = validate_quantity(per_truck_per_day, "per_truck_per_day")
    if capacity == 0:
        if target == 0:
            return 0
        raise ValidationError(
            "per_truck_per_day is 0 with a non-zero target: fleet undefined")
    return ceiling_units(target / capacity)


def fuel_per_trip(burn_L_per_hr: Numeric,
                  cycle_minutes: Numeric) -> Decimal:
    """Fuel litres per trip from burn rate and cycle time."""
    burn = validate_quantity(burn_L_per_hr, "burn_L_per_hr")
    cycle = to_decimal(cycle_minutes, "cycle_minutes")
    if cycle <= 0:
        raise ValidationError(f"cycle_minutes must be > 0; got {cycle}")
    return burn * cycle / Decimal("60")


def hire_cost_per_trip(hire_rate: Numeric, hire_rate_unit: str,
                       trips_per_day: Numeric = None,
                       cycle_minutes: Numeric = None) -> Decimal:
    """Hire portion per trip. Daily rates need trips/day; hourly rates
    need cycle minutes; trip rates stand alone. Unneeded companions with
    trip rates fail closed as contradictory."""
    rate = validate_rate(hire_rate, "hire_rate")
    if hire_rate_unit == HIRE_UNIT_TRIP:
        if trips_per_day is not None or cycle_minutes is not None:
            raise ValidationError(
                "trips_per_day/cycle_minutes contradict per-trip hire; "
                "omit them")
        return rate
    if hire_rate_unit == HIRE_UNIT_DAY:
        if trips_per_day is None:
            raise ValidationError(
                "trips_per_day is required with daily hire rates")
        trips = validate_quantity(trips_per_day, "trips_per_day")
        if trips <= 0:
            raise ValidationError(f"trips_per_day must be > 0; got {trips}")
        return rate / trips
    if hire_rate_unit == HIRE_UNIT_HOUR:
        if cycle_minutes is None:
            raise ValidationError(
                "cycle_minutes is required with hourly hire rates")
        cycle = to_decimal(cycle_minutes, "cycle_minutes")
        if cycle <= 0:
            raise ValidationError(
                f"cycle_minutes must be > 0; got {cycle}")
        return rate * cycle / Decimal("60")
    raise ValidationError(
        f"hire_rate_unit must be one of 'trip', 'day', 'hour'; "
        f"got {hire_rate_unit!r}")


def trip_total_cost(hire_portion: Numeric,
                    fuel_cost: Numeric = None) -> Decimal:
    """Trip total = hire portion + fuel portion (fuel None = hire only)."""
    hire = validate_rate(hire_portion, "hire_portion")
    if fuel_cost is None:
        return hire
    return hire + validate_rate(fuel_cost, "fuel_cost")


def unit_costs(cost_per_trip: Numeric, load_tonnes: Numeric,
               load_m3: Numeric) -> tuple:
    """(cost per tonne, cost per m3) for one laden trip."""
    cost = validate_rate(cost_per_trip, "cost_per_trip")
    tonnes = validate_quantity(load_tonnes, "load_tonnes")
    cubic = validate_quantity(load_m3, "load_m3")
    if tonnes <= 0 or cubic <= 0:
        raise ValidationError(
            "load_tonnes and load_m3 must both be > 0 for unit costing")
    return (cost / tonnes, cost / cubic)


def resolve_truck(truck_key: str, repository,
                  overrides: TruckOverride = None) -> ResolvedTruck:
    """Resolve a vehicle to usable planning numerics, fail-closed.

    NEEDS_VERIFICATION records require complete explicit overrides for
    the nine planning fields; anything less raises
    UnverifiedMasterDataError. hire_rate/fuel stay optional extras
    (None = that cost component unavailable). Rated payload above the
    legal limit fails closed. The nine planning fields merge through the
    unified master-data resolver (Phase 3.1); hire/fuel stay wrapper-
    owned optional extras.
    """
    resolved = resolve_master(
        repository, "trucks", truck_key, overrides,
        fields=TRUCK_FIELDS, record_keys=RECORD_KEYS, noun="Truck")
    values = resolved.values
    record = resolved.record
    master_version = resolved.master_version
    overridden = list(resolved.overridden_fields)
    overrides = overrides or TruckOverride()

    validate_dimension(values["body_length_m"], "body_length_m")
    validate_dimension(values["body_width_m"], "body_width_m")
    validate_dimension(values["body_height_m"], "body_height_m")
    validate_quantity(values["payload_limit_tonnes"], "payload_limit_tonnes")
    validate_quantity(values["payload_tonnes"], "payload_tonnes")
    if values["payload_tonnes"] > values["payload_limit_tonnes"]:
        raise ValidationError(
            f"Rated payload {values['payload_tonnes']} t exceeds legal "
            f"limit {values['payload_limit_tonnes']} t for {truck_key!r}")
    validate_quantity(values["load_time_min"], "load_time_min")
    validate_quantity(values["unload_time_min"], "unload_time_min")
    for speed_name in ("speed_loaded_kmh", "speed_empty_kmh"):
        if values[speed_name] <= 0:
            raise ValidationError(
                f"{speed_name} must be > 0; got {values[speed_name]}")

    hire_rate = overrides.hire_rate
    if hire_rate is not None:
        hire_rate = validate_rate(hire_rate, "hire_rate")
        overridden.append("hire_rate")
    elif record.get("hire_rate") is not None:
        hire_rate = validate_rate(record["hire_rate"], "hire_rate")
    fuel = overrides.fuel_burn_L_per_hr
    if fuel is not None:
        fuel = validate_quantity(fuel, "fuel_burn_L_per_hr")
        overridden.append("fuel_burn_L_per_hr")
    elif record.get("fuel_burn_L_per_hr") is not None:
        fuel = validate_quantity(
            record["fuel_burn_L_per_hr"], "fuel_burn_L_per_hr")
    hire_unit = record.get("hire_rate_unit")
    if hire_unit not in (HIRE_UNIT_TRIP, HIRE_UNIT_DAY, HIRE_UNIT_HOUR):
        raise ValidationError(
            f"Truck {truck_key!r} has unknown hire_rate_unit {hire_unit!r}")

    return ResolvedTruck(
        truck_key=truck_key,
        master_version=master_version,
        overrides_used=bool(overridden),
        overridden_fields=tuple(overridden),
        hire_rate=hire_rate,
        hire_rate_unit=hire_unit,
        fuel_burn_L_per_hr=fuel,
        **{f: values[f] for f in TRUCK_FIELDS},
    )


def plan_haulage(
    *,
    element: str = "",
    total_loose_m3: Numeric,
    loose_density_t_per_m3: Numeric,
    truck_key: str,
    repository,
    overrides: TruckOverride = None,
    heap_pct: Numeric = 0,
    distance_km: Numeric,
    available_minutes_per_day: Numeric,
    target_per_day: Numeric,
    target_unit: str,
) -> HaulagePlan:
    """Trip/fleet plan for a loose volume (keyword-only; costing separate).

    target_unit is "tonne" or "m3" (per-truck capacity compared in kind).
    """
    if target_unit not in (TARGET_TONNE, TARGET_M3):
        raise ValidationError(
            f"target_unit must be 'tonne' or 'm3'; got {target_unit!r}")
    resolved = resolve_truck(truck_key, repository, overrides)
    total = validate_quantity(total_loose_m3, "total_loose_m3")
    density = validate_density(loose_density_t_per_m3, "loose_density")
    bin_vol = bin_volume(
        resolved.body_length_m, resolved.body_width_m,
        resolved.body_height_m, "m", heap_pct)
    load = limiting_load(bin_vol, resolved.payload_tonnes, density)
    cycle = cycle_time_minutes(
        distance_km, resolved.speed_loaded_kmh, resolved.speed_empty_kmh,
        resolved.load_time_min, resolved.unload_time_min)
    trips = trips_per_day(available_minutes_per_day, cycle)
    ordered = ceiling_units(trips)
    per_truck = (ordered * load.load_tonnes if target_unit == TARGET_TONNE
                 else ordered * load.load_m3)
    target = validate_quantity(target_per_day, "target_per_day")
    fleet = fleet_size(target, per_truck)
    return HaulagePlan(
        element=element,
        total_loose_m3=total,
        limiting_load=load,
        cycle_minutes=cycle,
        trips_exact=trips,
        trips_ordered=ordered,
        target_per_day=target,
        target_unit=target_unit,
        daily_capacity_per_truck=per_truck,
        trucks_required=fleet,
        daily_capacity_total=fleet * per_truck,
        resolved_truck=resolved,
    )


def price_haulage(
    *,
    plan: HaulagePlan,
    hire_rate: Numeric,
    hire_rate_unit: str,
    fuel_price_per_L: Numeric = None,
    fuel_burn_L_per_hr: Numeric = None,
) -> HaulageCosts:
    """Price a haulage plan. Hire rate basis explicit; fuel needs BOTH
    burn and price (one without the other fails closed)."""
    if ((fuel_price_per_L is None) != (fuel_burn_L_per_hr is None)):
        raise ValidationError(
            "fuel_price_per_L and fuel_burn_L_per_hr must be supplied "
            "together or not at all")
    hire = hire_cost_per_trip(
        hire_rate, hire_rate_unit,
        trips_per_day=(plan.trips_ordered
                       if hire_rate_unit == HIRE_UNIT_DAY else None),
        cycle_minutes=(plan.cycle_minutes
                       if hire_rate_unit == HIRE_UNIT_HOUR else None))
    fuel = None
    if fuel_price_per_L is not None:
        fuel = (fuel_per_trip(fuel_burn_L_per_hr, plan.cycle_minutes)
                * validate_rate(fuel_price_per_L, "fuel_price_per_L"))
    total = trip_total_cost(hire, fuel)
    per_tonne, per_m3 = unit_costs(
        total, plan.limiting_load.load_tonnes, plan.limiting_load.load_m3)
    return HaulageCosts(
        trips_charged=plan.trips_ordered,
        hire_per_trip=hire,
        fuel_per_trip=fuel,
        cost_per_trip=total,
        cost_per_tonne=per_tonne,
        cost_per_m3=per_m3,
    )
