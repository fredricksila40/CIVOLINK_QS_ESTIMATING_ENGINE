"""Logistics / haulage tests (Phase 8).

All vehicle, speed, rate, and density fixtures are ARBITRARY TEST VALUES
passed explicitly — never project data and never to be mistaken for
verified payloads, cycle times, speeds, or hire rates.
"""

import json
from decimal import Decimal

import pytest

from qs_engine.core.assumptions import VerificationStatus
from qs_engine.core.errors import (
    UnknownMasterDataKeyError,
    UnverifiedMasterDataError,
    ValidationError,
)
from qs_engine.logistics.engine import (
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
from qs_engine.logistics.results import LIMIT_VOLUME, LIMIT_WEIGHT
from qs_engine.master_data.repository import MasterDataRepository


def full_overrides(**changes):
    fields = {"body_length_m": Decimal("4"), "body_width_m": Decimal("2"),
              "body_height_m": Decimal("1.5"),
              "payload_limit_tonnes": Decimal("12"),
              "payload_tonnes": Decimal("10"),
              "load_time_min": Decimal("10"),
              "unload_time_min": Decimal("5"),
              "speed_loaded_kmh": Decimal("20"),
              "speed_empty_kmh": Decimal("40")}
    fields.update(changes)
    return TruckOverride(**fields)


def shipped_repo():
    return MasterDataRepository()  # includes Phase 8 vehicle skeletons


# --- bin / load ------------------------------------------------------------

def test_bin_volume_struck_and_heaped():
    assert bin_volume(4, 2, Decimal("1.5")) == Decimal("12")
    # 2x2x2 = 8 struck; +25% heap policy -> 10.
    assert bin_volume(2, 2, 2, heap_pct=Decimal("25")) == Decimal("10")
    with pytest.raises(Exception):
        bin_volume(0, 2, Decimal("1.5"))
    with pytest.raises(Exception):
        bin_volume(4, 2, Decimal("1.5"), heap_pct=Decimal("101"))


def test_load_tonnage_loose_density_only():
    assert load_tonnage(Decimal("12"), Decimal("2")) == Decimal("24")
    with pytest.raises(Exception):
        load_tonnage(Decimal("12"), Decimal("0"))


def test_limiting_load_both_constraints():
    # 12 m3 x 2 t/m3 = 24 t > 10 t payload -> weight-limited: 10 t / 5 m3.
    limited = limiting_load(Decimal("12"), Decimal("10"), Decimal("2"))
    assert limited.limiting == LIMIT_WEIGHT
    assert limited.load_tonnes == Decimal("10")
    assert limited.load_m3 == Decimal("5")
    # 12 m3 x 0.5 = 6 t <= 10 t -> volume-limited.
    full = limiting_load(Decimal("12"), Decimal("10"), Decimal("0.5"))
    assert full.limiting == LIMIT_VOLUME
    assert full.load_m3 == Decimal("12")
    assert full.load_tonnes == Decimal("6")


# --- cycle / trips / fleet -------------------------------------------------

def test_cycle_time_round_trip():
    # 10 km @20 = 30 min; @40 = 15 min; +10 load +5 unload = 60.
    assert cycle_time_minutes(
        Decimal("10"), Decimal("20"), Decimal("40"),
        Decimal("10"), Decimal("5")) == Decimal("60")


def test_cycle_zero_distance_allowed_bad_speeds_rejected():
    assert cycle_time_minutes(
        Decimal("0"), Decimal("20"), Decimal("40"),
        Decimal("10"), Decimal("5")) == Decimal("15")
    with pytest.raises(ValidationError):
        cycle_time_minutes(Decimal("10"), Decimal("0"), Decimal("40"),
                           Decimal("10"), Decimal("5"))


def test_trips_and_throughput_and_fleet():
    assert trips_per_day(Decimal("480"), Decimal("60")) == Decimal("8")
    assert daily_throughput(2, Decimal("8"), Decimal("10")) == Decimal("160")
    # 100 t target at 80 t/truck/day -> 2 trucks (ceiling 1.25).
    assert fleet_size(Decimal("100"), Decimal("80")) == 2
    assert fleet_size(Decimal("0"), Decimal("80")) == 0
    with pytest.raises(ValidationError):
        fleet_size(Decimal("100"), Decimal("0"))
    with pytest.raises(ValidationError):
        daily_throughput(2.5, Decimal("8"), Decimal("10"))


# --- costing ---------------------------------------------------------------

def test_hire_cost_modes():
    assert hire_cost_per_trip(Decimal("3750"), "trip") == Decimal("3750")
    assert hire_cost_per_trip(
        Decimal("30000"), "day", trips_per_day=Decimal("8")) == Decimal("3750")
    assert hire_cost_per_trip(
        Decimal("5000"), "hour", cycle_minutes=Decimal("60")) == Decimal("5000")
    with pytest.raises(ValidationError):
        hire_cost_per_trip(Decimal("30000"), "day")
    with pytest.raises(ValidationError):
        hire_cost_per_trip(Decimal("5000"), "hour")
    with pytest.raises(ValidationError):
        hire_cost_per_trip(Decimal("3750"), "trip",
                           trips_per_day=Decimal("8"))
    with pytest.raises(ValidationError):
        hire_cost_per_trip(Decimal("100"), "week")


def test_fuel_and_totals_and_unit_costs():
    # 20 L/h x 60 min = 20 L.
    assert fuel_per_trip(Decimal("20"), Decimal("60")) == Decimal("20")
    assert trip_total_cost(Decimal("3750")) == Decimal("3750")
    assert trip_total_cost(Decimal("3750"), Decimal("4000")) == Decimal("7750")
    per_tonne, per_m3 = unit_costs(Decimal("7750"), Decimal("10"), Decimal("5"))
    assert per_tonne == Decimal("775")
    assert per_m3 == Decimal("1550")
    with pytest.raises(ValidationError):
        unit_costs(Decimal("7750"), Decimal("0"), Decimal("5"))


# --- resolution ------------------------------------------------------------

def test_skeleton_keys_look_up_with_nulls():
    repo = shipped_repo()
    assert {r["key"] for r in repo.list("trucks")} == {
        "tipper_truck", "flatbed_trailer", "site_dumper"}
    for record in repo.list("trucks"):
        assert record["verification_status"] == "NEEDS_VERIFICATION"
        assert record["payload_tonnes"] is None
        assert record["speed_loaded_kmh"] is None


def test_unknown_truck_key_raises():
    with pytest.raises(UnknownMasterDataKeyError):
        resolve_truck("hover_truck", shipped_repo(), full_overrides())


def test_unverified_without_overrides_fails_closed():
    with pytest.raises(UnverifiedMasterDataError):
        resolve_truck("tipper_truck", shipped_repo())


def test_partial_overrides_fail_closed_with_missing_listed():
    partial = TruckOverride(body_length_m=Decimal("4"))
    assert not partial.is_complete()
    assert "speed_loaded_kmh" in partial.missing()
    try:
        resolve_truck("tipper_truck", shipped_repo(), partial)
        raise AssertionError("should have raised")
    except UnverifiedMasterDataError as exc:
        assert "speed_loaded_kmh" in str(exc)


def test_full_overrides_proceed_with_provenance():
    resolved = resolve_truck(
        "tipper_truck", shipped_repo(), full_overrides())
    assert resolved.payload_tonnes == Decimal("10")
    assert resolved.overrides_used is True
    assert "speed_loaded_kmh" in resolved.overridden_fields
    assert resolved.master_version == "8.0-skeleton"
    assert resolved.hire_rate is None
    assert resolved.fuel_burn_L_per_hr is None


def test_payload_above_limit_fails_closed():
    with pytest.raises(ValidationError):
        resolve_truck("tipper_truck", shipped_repo(), full_overrides(
            payload_tonnes=Decimal("15")))


def test_verified_record_needs_no_overrides(tmp_path):
    record = {
        "key": "truck_v", "size_label": "Truck V",
        "body_length_m": "4", "body_width_m": "2", "body_height_m": "1.5",
        "payload_limit_tonnes": "12", "payload_tonnes": "10",
        "load_time_min": "10", "unload_time_min": "5",
        "speed_loaded_kmh": "20", "speed_empty_kmh": "40",
        "hire_rate": "30000", "hire_rate_unit": "day",
        "fuel_burn_L_per_hr": "20",
        "rate_effective_date": "2026-01-01",
        "source": "TEST FIXTURE ONLY", "version": "t",
        "effective_date": "2026-01-01",
        "verification_status": VerificationStatus.VERIFIED,
    }
    (tmp_path / "trucks.json").write_text(json.dumps({
        "schema_version": "0.1", "table_version": "t",
        "records": [record],
    }), encoding="utf-8")
    repo = MasterDataRepository(tmp_path)
    resolved = resolve_truck("truck_v", repo)
    assert resolved.overrides_used is False
    assert resolved.hire_rate == Decimal("30000")
    assert resolved.fuel_burn_L_per_hr == Decimal("20")


# --- end-to-end ------------------------------------------------------------

def test_end_to_end_plan_exact():
    # Bin 4x2x1.5 = 12 m3; density 2 -> 24 t > 10 t payload:
    # weight-limited 10 t / 5 m3. Cycle 60 min; 480 min -> 8 trips.
    # Target 100 t at 80 t/truck -> 2 trucks, 160 t capacity.
    plan = plan_haulage(
        total_loose_m3=Decimal("200"), loose_density_t_per_m3=Decimal("2"),
        truck_key="tipper_truck", repository=shipped_repo(),
        overrides=full_overrides(), distance_km=Decimal("10"),
        available_minutes_per_day=Decimal("480"),
        target_per_day=Decimal("100"), target_unit="tonne",
        element="test haul")
    assert plan.limiting_load.limiting == LIMIT_WEIGHT
    assert plan.limiting_load.load_tonnes == Decimal("10")
    assert plan.limiting_load.load_m3 == Decimal("5")
    assert plan.cycle_minutes == Decimal("60")
    assert plan.trips_exact == Decimal("8")
    assert plan.trips_ordered == 8
    assert plan.daily_capacity_per_truck == Decimal("80")
    assert plan.trucks_required == 2
    assert plan.daily_capacity_total == Decimal("160")
    assert plan.element == "test haul"
    assert plan.resolved_truck.overrides_used is True


def test_end_to_end_price_exact():
    plan = plan_haulage(
        total_loose_m3=Decimal("200"), loose_density_t_per_m3=Decimal("2"),
        truck_key="tipper_truck", repository=shipped_repo(),
        overrides=full_overrides(), distance_km=Decimal("10"),
        available_minutes_per_day=Decimal("480"),
        target_per_day=Decimal("100"), target_unit="tonne")
    # Daily hire 30000 / 8 trips = 3750/trip -> 375/t, 750/m3.
    costs = price_haulage(plan=plan, hire_rate=Decimal("30000"),
                          hire_rate_unit="day")
    assert costs.trips_charged == 8
    assert costs.hire_per_trip == Decimal("3750")
    assert costs.fuel_per_trip is None
    assert costs.cost_per_trip == Decimal("3750")
    assert costs.cost_per_tonne == Decimal("375")
    assert costs.cost_per_m3 == Decimal("750")
    # With fuel: 20 L/h x 1 h x 200 = 4000 -> 7750/trip.
    fuelled = price_haulage(plan=plan, hire_rate=Decimal("30000"),
                            hire_rate_unit="day",
                            fuel_price_per_L=Decimal("200"),
                            fuel_burn_L_per_hr=Decimal("20"))
    assert fuelled.fuel_per_trip == Decimal("4000")
    assert fuelled.cost_per_trip == Decimal("7750")
    assert fuelled.cost_per_tonne == Decimal("775")


def test_price_fuel_half_pairing_rejected():
    plan = plan_haulage(
        total_loose_m3=Decimal("200"), loose_density_t_per_m3=Decimal("2"),
        truck_key="tipper_truck", repository=shipped_repo(),
        overrides=full_overrides(), distance_km=Decimal("10"),
        available_minutes_per_day=Decimal("480"),
        target_per_day=Decimal("100"), target_unit="tonne")
    with pytest.raises(ValidationError):
        price_haulage(plan=plan, hire_rate=Decimal("30000"),
                      hire_rate_unit="day",
                      fuel_price_per_L=Decimal("200"))
    with pytest.raises(ValidationError):
        price_haulage(plan=plan, hire_rate=Decimal("30000"),
                      hire_rate_unit="fortnight")
