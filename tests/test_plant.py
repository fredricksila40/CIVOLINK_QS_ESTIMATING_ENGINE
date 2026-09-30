"""Plant engine tests (Phase 7).

All output/rate/operating fixtures are ARBITRARY TEST VALUES passed
explicitly — never project data and never to be mistaken for verified
productivities, hire rates, or operating costs.
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
from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.plant.engine import (
    PlantOverride,
    calculate_plant_requirement,
    plant_duration,
    resolve_plant_equipment,
)


def full_overrides(**changes):
    fields = {"output_per_unit": Decimal("20"), "rate": Decimal("24000"),
              "operating_cost_per_hour": None}
    fields.update(changes)
    return PlantOverride(**fields)


def shipped_repo():
    return MasterDataRepository()  # includes Phase 7 equipment skeletons


# --- duration --------------------------------------------------------------

def test_duration():
    assert plant_duration(Decimal("100"), Decimal("20")) == Decimal("5")
    with pytest.raises(ValidationError):
        plant_duration(Decimal("100"), Decimal("0"))


# --- same-basis hire -------------------------------------------------------

def test_same_basis_hire_exact(tmp_path):
    record = {
        "key": "plant_d", "equipment": "Plant D", "work_unit": "m3",
        "output_per_unit": "50", "output_basis": "day",
        "rate": "20000", "rate_unit": "day", "hire_basis": "wet",
        "operating_cost_per_hour": None,
        "rate_effective_date": "2026-01-01",
        "source": "TEST FIXTURE ONLY", "version": "t",
        "effective_date": "2026-01-01",
        "verification_status": VerificationStatus.VERIFIED,
    }
    (tmp_path / "plant.json").write_text(json.dumps({
        "schema_version": "0.1", "table_version": "t",
        "records": [record],
    }), encoding="utf-8")
    repo = MasterDataRepository(tmp_path)
    # 100 at 50/day = 2 days x 20000 = 40000; no operating estimated.
    req = calculate_plant_requirement(
        work_quantity=Decimal("100"), equipment_key="plant_d",
        repository=repo, element="test dig")
    assert req.duration_value == Decimal("2")
    assert req.duration_basis == "day"
    assert req.hire_cost == Decimal("40000")
    assert req.operating_cost is None
    assert req.operating_hours is None
    assert req.total_cost == Decimal("40000")
    assert req.hours_per_day is None
    assert req.resolved_plant.overrides_used is False


def test_same_basis_rejects_unneeded_hours():
    with pytest.raises(ValidationError):
        calculate_plant_requirement(
            work_quantity=Decimal("100"), equipment_key="mobile_crane",
            repository=shipped_repo(),
            overrides=PlantOverride(output_per_unit=Decimal("10"),
                                    rate=Decimal("20000")),
            hours_per_day=Decimal("8"))


# --- cross-basis conversion ------------------------------------------------

def test_hourly_output_daily_rate_conversion():
    # 100 at 20/hr = 5 h; daily 24000 / 8 h days = 0.625 d -> 15000.
    req = calculate_plant_requirement(
        work_quantity=Decimal("100"), equipment_key="backhoe_excavator",
        repository=shipped_repo(), overrides=full_overrides(),
        hours_per_day=Decimal("8"))
    assert req.duration_value == Decimal("5")
    assert req.duration_basis == "hour"
    assert req.hire_cost == Decimal("15000")
    assert req.hours_per_day == Decimal("8")
    assert req.operating_cost is None


def test_daily_output_hourly_rate_conversion(tmp_path):
    # 100 at 50/day = 2 d x 8 h x 3000/hr = 48000. Needs a day-output /
    # hour-rate record (no skeleton carries that combination).
    record = {
        "key": "plant_dh", "equipment": "Plant DH", "work_unit": "m3",
        "output_per_unit": "50", "output_basis": "day",
        "rate": "3000", "rate_unit": "hour", "hire_basis": "wet",
        "operating_cost_per_hour": None,
        "rate_effective_date": "2026-01-01",
        "source": "TEST FIXTURE ONLY", "version": "t",
        "effective_date": "2026-01-01",
        "verification_status": VerificationStatus.VERIFIED,
    }
    (tmp_path / "plant.json").write_text(json.dumps({
        "schema_version": "0.1", "table_version": "t",
        "records": [record],
    }), encoding="utf-8")
    from qs_engine.master_data.repository import MasterDataRepository as Repo
    req = calculate_plant_requirement(
        work_quantity=Decimal("100"), equipment_key="plant_dh",
        repository=Repo(tmp_path), hours_per_day=Decimal("8"))
    assert req.hire_cost == Decimal("48000")


def test_cross_basis_requires_hours_per_day():
    with pytest.raises(ValidationError):
        calculate_plant_requirement(
            work_quantity=Decimal("100"), equipment_key="backhoe_excavator",
            repository=shipped_repo(), overrides=full_overrides())


# --- operating cost --------------------------------------------------------

def test_operating_cost_hourly_output():
    # 100 at 20/hr = 5 h x 500/hr operating = 2500; hire 5/8 x 24000 = 15000.
    req = calculate_plant_requirement(
        work_quantity=Decimal("100"), equipment_key="backhoe_excavator",
        repository=shipped_repo(),
        overrides=full_overrides(operating_cost_per_hour=Decimal("500")),
        hours_per_day=Decimal("8"))
    assert req.operating_hours == Decimal("5")
    assert req.operating_cost == Decimal("2500")
    assert req.total_cost == Decimal("17500")


def test_operating_cost_day_output_needs_hours():
    # Day-basis output + daily rate + operating: hpd derives op hours.
    req = calculate_plant_requirement(
        work_quantity=Decimal("100"), equipment_key="mobile_crane",
        repository=shipped_repo(),
        overrides=PlantOverride(output_per_unit=Decimal("50"),
                                rate=Decimal("20000"),
                                operating_cost_per_hour=Decimal("500")),
        hours_per_day=Decimal("8"))
    assert req.operating_hours == Decimal("16")
    assert req.operating_cost == Decimal("8000")
    assert req.total_cost == Decimal("48000")


def test_operating_day_output_missing_hours_fails():
    with pytest.raises(ValidationError):
        calculate_plant_requirement(
            work_quantity=Decimal("100"), equipment_key="mobile_crane",
            repository=shipped_repo(),
            overrides=PlantOverride(output_per_unit=Decimal("50"),
                                    rate=Decimal("20000"),
                                    operating_cost_per_hour=Decimal("500")))


# --- lookup + fail-closed --------------------------------------------------

def test_skeleton_keys_look_up_with_nulls():
    repo = shipped_repo()
    assert {r["key"] for r in repo.list("plant")} == {
        "concrete_mixer", "backhoe_excavator", "poker_vibrator",
        "road_roller", "mobile_crane"}
    for record in repo.list("plant"):
        assert record["verification_status"] == "NEEDS_VERIFICATION"
        assert record["output_per_unit"] is None
        assert record["rate"] is None


def test_unknown_equipment_key_raises():
    with pytest.raises(UnknownMasterDataKeyError):
        resolve_plant_equipment("teleporter", shipped_repo(),
                                full_overrides())


def test_unverified_without_overrides_fails_closed():
    with pytest.raises(UnverifiedMasterDataError):
        resolve_plant_equipment("road_roller", shipped_repo())


def test_partial_overrides_fail_closed_with_missing_listed():
    partial = PlantOverride(output_per_unit=Decimal("20"))
    assert not partial.is_complete()
    assert "rate" in partial.missing_required()
    try:
        resolve_plant_equipment("road_roller", shipped_repo(), partial)
        raise AssertionError("should have raised")
    except UnverifiedMasterDataError as exc:
        assert "rate" in str(exc)


def test_verified_record_needs_no_overrides(tmp_path):
    record = {
        "key": "plant_v", "equipment": "Plant V", "work_unit": "m3",
        "output_per_unit": "20", "output_basis": "hour",
        "rate": "5000", "rate_unit": "hour", "hire_basis": "dry",
        "operating_cost_per_hour": None,
        "rate_effective_date": "2026-01-01",
        "source": "TEST FIXTURE ONLY", "version": "t",
        "effective_date": "2026-01-01",
        "verification_status": VerificationStatus.VERIFIED,
    }
    (tmp_path / "plant.json").write_text(json.dumps({
        "schema_version": "0.1", "table_version": "t",
        "records": [record],
    }), encoding="utf-8")
    repo = MasterDataRepository(tmp_path)
    resolved = resolve_plant_equipment("plant_v", repo)
    assert resolved.overrides_used is False
    assert resolved.output_basis == "hour"
    assert resolved.operating_cost_per_hour is None
