"""Earthworks engine tests (Phase 5).

All numeric fixtures below are ARBITRARY TEST VALUES to exercise the math —
they are not project engineering data and must never be mistaken for
verified swell/compaction factors or densities.
"""

import json
from decimal import Decimal

import pytest

from qs_engine.core.assumptions import VerificationStatus
from qs_engine.core.errors import (
    NonPositiveDimensionError,
    UnknownMasterDataKeyError,
    UnverifiedMasterDataError,
    ValidationError,
)
from qs_engine.earthworks.engine import (
    SoilOverride,
    backfill_loose_requirement,
    backfill_volume,
    blinding_volume,
    calculate_foundation_earthworks,
    cartaway_volume,
    clearance_area,
    compacted_yield,
    excavation_volume,
    hardcore_bed_volume,
    layer_volume,
    loose_for_compacted_target,
    membrane_area_with_laps,
    resolve_soil,
    swell_volume,
    topsoil_strip_volume,
)
from qs_engine.master_data.repository import MasterDataRepository

# Arbitrary test-only factors (NOT engineering data).
T_SWELL = Decimal("1.25")
T_COMPACT = Decimal("1.1")
T_DENSITY = Decimal("1000")


def full_overrides(**changes):
    fields = {"swell_factor": T_SWELL, "compact_factor": T_COMPACT,
              "density_kg_per_m3": T_DENSITY}
    fields.update(changes)
    return SoilOverride(**fields)


def shipped_repo():
    return MasterDataRepository()  # includes Phase 5 soil skeletons


# --- clearance / strip -----------------------------------------------------

def test_clearance_area():
    qty = clearance_area(Decimal("20"), Decimal("15"))
    assert qty.value == Decimal("300")
    assert qty.unit == "m\u00b2"


def test_topsoil_strip_volume():
    qty = topsoil_strip_volume(Decimal("300"), Decimal("0.2"))
    assert qty.value == Decimal("60.0")
    assert qty.unit == "m\u00b3"


def test_clearance_rejects_bad_dims():
    with pytest.raises(NonPositiveDimensionError):
        clearance_area(0, 15)


# --- excavation ------------------------------------------------------------

def test_excavation_nominal():
    assert excavation_volume(10, 2, Decimal("1.5")).value == Decimal("30.0")


def test_excavation_working_space_each_side():
    # Allowance added to EACH side: (10+1) x (2+1) x 1.5 = 49.5.
    qty = excavation_volume(10, 2, Decimal("1.5"), working_space_m=Decimal("0.5"))
    assert qty.value == Decimal("49.5")


def test_trench_uses_same_geometry():
    # 20 x 0.6 x 1.2 with 0.3 working space: 20.6 x 1.2 x 1.2 = 29.664.
    qty = excavation_volume(20, Decimal("0.6"), Decimal("1.2"),
                            working_space_m=Decimal("0.3"))
    assert qty.value == Decimal("29.664")


def test_excavation_rejects_bad_inputs():
    with pytest.raises(NonPositiveDimensionError):
        excavation_volume(10, 0, Decimal("1.5"))
    with pytest.raises(Exception):
        excavation_volume(10, 2, Decimal("1.5"), working_space_m=Decimal("-0.1"))


# --- swell / compaction ----------------------------------------------------

def test_swell_volume():
    assert swell_volume(Decimal("15"), T_SWELL) == Decimal("18.75")


def test_factors_below_one_rejected():
    with pytest.raises(ValidationError):
        swell_volume(Decimal("15"), Decimal("0.9"))
    with pytest.raises(ValidationError):
        loose_for_compacted_target(Decimal("10"), Decimal("0.99"))
    with pytest.raises(ValidationError):
        compacted_yield(Decimal("12"), Decimal("0.5"))


def test_compact_directions():
    assert loose_for_compacted_target(Decimal("10"), Decimal("1.2")) == Decimal("12.0")
    assert compacted_yield(Decimal("12"), Decimal("1.2")) == Decimal("10")
    assert swell_volume(Decimal("15"), Decimal("1")) == Decimal("15")


# --- balance ---------------------------------------------------------------

def test_backfill_nominal():
    assert backfill_volume(Decimal("15"), Decimal("3")) == Decimal("12")
    assert backfill_volume(Decimal("15"), Decimal("0")) == Decimal("15")


def test_backfill_excess_displaced_fails_closed():
    with pytest.raises(ValidationError):
        backfill_volume(Decimal("15"), Decimal("15.01"))


def test_dispose_nominal_and_import_signal():
    assert cartaway_volume(Decimal("18.75"), Decimal("13.2")) == Decimal("5.55")
    # Negative dispose is exposed as a net import requirement, not hidden.
    assert cartaway_volume(Decimal("10"), Decimal("12")) == Decimal("-2")


def test_backfill_loose_requirement_modes():
    assert backfill_loose_requirement(Decimal("12"), None) == Decimal("12")
    assert backfill_loose_requirement(Decimal("12"), Decimal("1.1")) == Decimal("13.2")


# --- beds / membranes ------------------------------------------------------

def test_layer_volumes():
    assert hardcore_bed_volume(Decimal("20"), Decimal("0.15")).value == Decimal("3.0")
    assert blinding_volume(Decimal("20"), Decimal("0.05")).value == Decimal("1.0")
    assert layer_volume(Decimal("20"), Decimal("0.15")).value == Decimal("3.0")


def test_membrane_laps():
    assert membrane_area_with_laps(Decimal("100"), Decimal("10")) == Decimal("110.0")
    assert membrane_area_with_laps(Decimal("100"), Decimal("0")) == Decimal("100")
    with pytest.raises(Exception):
        membrane_area_with_laps(Decimal("100"), Decimal("100.01"))


# --- soils lookup + fail-closed --------------------------------------------

def test_skeleton_keys_look_up_with_nulls():
    repo = shipped_repo()
    assert {r["key"] for r in repo.list("soils")} == {
        "topsoil_vegetable", "clay_soil", "gravel_soil", "rock_hard"}
    for record in repo.list("soils"):
        assert record["verification_status"] == "NEEDS_VERIFICATION"
        assert record["swell_factor"] is None


def test_unknown_soil_key_raises():
    with pytest.raises(UnknownMasterDataKeyError):
        resolve_soil("sand_mars", shipped_repo(), full_overrides())


def test_unverified_soil_without_overrides_fails_closed():
    with pytest.raises(UnverifiedMasterDataError):
        resolve_soil("clay_soil", shipped_repo())


def test_partial_overrides_fail_closed_with_missing_listed():
    partial = SoilOverride(swell_factor=T_SWELL)
    assert not partial.is_complete()
    assert "compact_factor" in partial.missing()
    try:
        resolve_soil("clay_soil", shipped_repo(), partial)
        raise AssertionError("should have raised")
    except UnverifiedMasterDataError as exc:
        assert "compact_factor" in str(exc)


def test_full_overrides_proceed_with_provenance():
    soil = resolve_soil("clay_soil", shipped_repo(), full_overrides())
    assert soil.soil_key == "clay_soil"
    assert soil.overrides_used is True
    assert set(soil.overridden_fields) == {
        "swell_factor", "compact_factor", "density_kg_per_m3"}
    assert soil.master_version == "5.0-skeleton"


def test_verified_record_needs_no_overrides(tmp_path):
    record = {
        "key": "soil_t", "name": "Soil T",
        "swell_factor": "1.2", "compact_factor": "1.1",
        "density_kg_per_m3": "1500",
        "source": "TEST FIXTURE ONLY", "version": "t",
        "effective_date": "2026-01-01",
        "verification_status": VerificationStatus.VERIFIED,
    }
    (tmp_path / "soils.json").write_text(json.dumps({
        "schema_version": "0.1", "table_version": "t",
        "records": [record],
    }), encoding="utf-8")
    repo = MasterDataRepository(tmp_path)
    soil = resolve_soil("soil_t", repo)
    assert soil.overrides_used is False
    assert soil.swell_factor == Decimal("1.2")


# --- end-to-end ------------------------------------------------------------

def test_end_to_end_exact():
    # Trench 10x1x1.5 (no working space) -> 15 bank; K_swell 1.25 -> 18.75;
    # displaced 3 -> backfill 12 bank; K_compact 1.1 -> 13.2 loose;
    # dispose 5.55 loose; bank mass 15 x 1000 = 15000 kg.
    result = calculate_foundation_earthworks(
        length=10, width=1, depth=Decimal("1.5"),
        soil_key="clay_soil", repository=shipped_repo(),
        overrides=full_overrides(), displaced_substructure_m3=Decimal("3"),
        element="test trench")
    assert result.excavation_bank_m3 == Decimal("15")
    assert result.loose_dug_m3 == Decimal("18.75")
    assert result.backfill_bank_m3 == Decimal("12")
    assert result.backfill_loose_m3 == Decimal("13.2")
    assert result.dispose_loose_m3 == Decimal("5.55")
    assert result.bank_mass_kg == Decimal("15000")
    assert result.compact_factor_used == T_COMPACT
    assert result.resolved_soil.overrides_used is True
    assert result.element == "test trench"


def test_end_to_end_uncompacted_backfill():
    result = calculate_foundation_earthworks(
        length=10, width=1, depth=Decimal("1.5"),
        soil_key="clay_soil", repository=shipped_repo(),
        overrides=full_overrides(), displaced_substructure_m3=Decimal("3"),
        compact_backfill=False)
    assert result.backfill_loose_m3 == result.backfill_bank_m3 == Decimal("12")
    assert result.compact_factor_used is None
    assert result.dispose_loose_m3 == Decimal("18.75") - Decimal("12")
