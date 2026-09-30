"""Labour engine tests (Phase 7).

All rate/output/gang fixtures are ARBITRARY TEST VALUES passed explicitly —
never project data and never to be mistaken for verified productivities,
gangs, or rates.
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
from qs_engine.labour.engine import (
    LabourTradeOverride,
    calculate_labour_requirement,
    gang_cost_per_rate_unit,
    labour_duration_days,
    resolve_labour_trade,
)
from qs_engine.master_data.repository import MasterDataRepository


def full_overrides(**changes):
    fields = {"output_per_day": Decimal("25"), "gang_skilled": 2,
              "gang_unskilled": 4, "skilled_rate": Decimal("1500"),
              "unskilled_rate": Decimal("800")}
    fields.update(changes)
    return LabourTradeOverride(**fields)


def shipped_repo():
    return MasterDataRepository()  # includes Phase 7 trade skeletons


# --- gang cost / duration --------------------------------------------------

def test_gang_daily_cost():
    # 2 x 1500 + 4 x 800 = 6200.
    assert gang_cost_per_rate_unit(2, 4, Decimal("1500"),
                                   Decimal("800")) == Decimal("6200")


def test_gang_rejects_empty_or_bad_counts():
    with pytest.raises(ValidationError):
        gang_cost_per_rate_unit(0, 0, Decimal("1500"), Decimal("800"))
    with pytest.raises(ValidationError):
        gang_cost_per_rate_unit(2.0, 4, Decimal("1500"), Decimal("800"))
    with pytest.raises(ValidationError):
        gang_cost_per_rate_unit(-1, 4, Decimal("1500"), Decimal("800"))


def test_duration_days():
    assert labour_duration_days(Decimal("100"), Decimal("25")) == Decimal("4")
    with pytest.raises(ValidationError):
        labour_duration_days(Decimal("100"), Decimal("0"))


# --- daily-rate requirement ------------------------------------------------

def test_daily_requirement_exact():
    # 100 m2 at 25/day = 4 gang-days; gang 2+4 at 1500/800 = 6200/day.
    req = calculate_labour_requirement(
        work_quantity=Decimal("100"), trade_key="mason",
        repository=shipped_repo(), overrides=full_overrides(),
        element="test wall")
    assert req.duration_gang_days == Decimal("4")
    assert req.skilled_person_days == Decimal("8")
    assert req.unskilled_person_days == Decimal("16")
    assert req.skilled_person_hours is None
    assert req.unskilled_person_hours is None
    assert req.gang_cost_per_day == Decimal("6200")
    assert req.total_cost == Decimal("24800")
    assert req.hours_per_day is None
    assert req.work_unit == "m2"
    assert req.element == "test wall"
    assert req.resolved_trade.overrides_used is True


def test_daily_rates_reject_hours_per_day():
    with pytest.raises(ValidationError):
        calculate_labour_requirement(
            work_quantity=Decimal("100"), trade_key="mason",
            repository=shipped_repo(), overrides=full_overrides(),
            hours_per_day=Decimal("8"))


# --- hourly-rate requirement -----------------------------------------------

def hourly_overrides(**changes):
    fields = {"output_per_day": Decimal("25"), "gang_skilled": 1,
              "gang_unskilled": 2, "skilled_rate": Decimal("200"),
              "unskilled_rate": Decimal("100")}
    fields.update(changes)
    return LabourTradeOverride(**fields)


def test_hourly_requirement_exact(tmp_path):
    record = {
        "key": "trade_h", "trade": "Trade H", "work_unit": "m2",
        "output_per_day": "25", "gang_skilled": 1, "gang_unskilled": 2,
        "skilled_rate": "200", "unskilled_rate": "100",
        "rate_unit": "hour", "rate_effective_date": "2026-01-01",
        "source": "TEST FIXTURE ONLY", "version": "t",
        "effective_date": "2026-01-01",
        "verification_status": VerificationStatus.VERIFIED,
    }
    (tmp_path / "labour.json").write_text(json.dumps({
        "schema_version": "0.1", "table_version": "t",
        "records": [record],
    }), encoding="utf-8")
    repo = MasterDataRepository(tmp_path)
    # 100 at 25/day = 4 days; gang 1+2 at 200/100 = 400/hr x 8 h = 3200/day.
    req = calculate_labour_requirement(
        work_quantity=Decimal("100"), trade_key="trade_h", repository=repo,
        hours_per_day=Decimal("8"))
    assert req.duration_gang_days == Decimal("4")
    assert req.gang_cost_per_day == Decimal("3200")
    assert req.total_cost == Decimal("12800")
    assert req.skilled_person_hours == Decimal("32")
    assert req.unskilled_person_hours == Decimal("64")
    assert req.hours_per_day == Decimal("8")
    assert req.resolved_trade.overrides_used is False


def _hourly_repo(tmp_path):
    # Day-basis skeletons can't exercise the hourly path; use a verified
    # hourly record (test fixture only).
    from qs_engine.master_data.repository import MasterDataRepository as Repo
    record = {
        "key": "trade_h", "trade": "Trade H", "work_unit": "m2",
        "output_per_day": "25", "gang_skilled": 1, "gang_unskilled": 2,
        "skilled_rate": "200", "unskilled_rate": "100",
        "rate_unit": "hour", "rate_effective_date": "2026-01-01",
        "source": "TEST FIXTURE ONLY", "version": "t",
        "effective_date": "2026-01-01",
        "verification_status": VerificationStatus.VERIFIED,
    }
    (tmp_path / "labour.json").write_text(json.dumps({
        "schema_version": "0.1", "table_version": "t",
        "records": [record],
    }), encoding="utf-8")
    return Repo(tmp_path)


def test_hourly_rates_require_hours_per_day(tmp_path):
    with pytest.raises(ValidationError):
        calculate_labour_requirement(
            work_quantity=Decimal("100"), trade_key="trade_h",
            repository=_hourly_repo(tmp_path))


def test_hourly_rejects_bad_hours():
    with pytest.raises(ValidationError):
        calculate_labour_requirement(
            work_quantity=Decimal("100"), trade_key="painter",
            repository=shipped_repo(), overrides=hourly_overrides(),
            hours_per_day=Decimal("0"))


# --- lookup + fail-closed --------------------------------------------------

def test_skeleton_keys_look_up_with_nulls():
    repo = shipped_repo()
    assert {r["key"] for r in repo.list("labour")} == {
        "mason", "carpenter", "steel_fixer", "painter",
        "excavator_operator", "general_labourer"}
    for record in repo.list("labour"):
        assert record["verification_status"] == "NEEDS_VERIFICATION"
        assert record["output_per_day"] is None
        assert record["skilled_rate"] is None


def test_unknown_trade_key_raises():
    with pytest.raises(UnknownMasterDataKeyError):
        resolve_labour_trade("bricklayer_mars", shipped_repo(),
                             full_overrides())


def test_unverified_without_overrides_fails_closed():
    with pytest.raises(UnverifiedMasterDataError):
        resolve_labour_trade("mason", shipped_repo())


def test_partial_overrides_fail_closed_with_missing_listed():
    partial = LabourTradeOverride(output_per_day=Decimal("25"))
    assert not partial.is_complete()
    assert "skilled_rate" in partial.missing()
    try:
        resolve_labour_trade("mason", shipped_repo(), partial)
        raise AssertionError("should have raised")
    except UnverifiedMasterDataError as exc:
        assert "skilled_rate" in str(exc)


def test_verified_record_needs_no_overrides(tmp_path):
    record = {
        "key": "trade_v", "trade": "Trade V", "work_unit": "m2",
        "output_per_day": "25", "gang_skilled": 2, "gang_unskilled": 4,
        "skilled_rate": "1500", "unskilled_rate": "800",
        "rate_unit": "day", "rate_effective_date": "2026-01-01",
        "source": "TEST FIXTURE ONLY", "version": "t",
        "effective_date": "2026-01-01",
        "verification_status": VerificationStatus.VERIFIED,
    }
    (tmp_path / "labour.json").write_text(json.dumps({
        "schema_version": "0.1", "table_version": "t",
        "records": [record],
    }), encoding="utf-8")
    repo = MasterDataRepository(tmp_path)
    resolved = resolve_labour_trade("trade_v", repo)
    assert resolved.overrides_used is False
    assert resolved.gang_skilled == 2
    assert resolved.rate_unit == "day"
