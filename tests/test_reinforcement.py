"""Reinforcement engine tests (Phase 4).

All numeric fixtures below are ARBITRARY TEST VALUES to exercise the math —
they are not project engineering data. In particular, no steel density is
endorsed: tests pass densities explicitly, and the engine holds none.
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
from qs_engine.reinforcement.engine import (
    MASS_SOURCE_FORMULA,
    MASS_SOURCE_OVERRIDE,
    MASS_SOURCE_TABLE,
    BarLineInput,
    RebarBarOverride,
    calculate_bar_line,
    calculate_rebar_schedule,
    nominal_bar_mass,
    resolve_rebar_bar,
)

# Arbitrary test-only density (NOT a project value).
T_DENSITY = Decimal("1000")
T_MASS = Decimal("2")


def shipped_repo():
    return MasterDataRepository()  # includes Phase 4 bar skeletons


# --- nominal-mass formula --------------------------------------------------

def test_formula_scales_with_diameter_squared():
    # Area (hence mass) scales with d^2: 20 mm bar is 4x a 10 mm bar.
    # Compared at 12dp: the two 28-digit intermediate roundings leave
    # sub-1e-20 residue that exact Decimal equality would trip on.
    from qs_engine.core.decimal_policy import quantize
    ratio = (nominal_bar_mass(Decimal("20"), T_DENSITY)
             / nominal_bar_mass(Decimal("10"), T_DENSITY))
    assert quantize(ratio, 12) == Decimal("4")


def test_formula_first_principles_shape():
    from qs_engine.reinforcement.engine import PI
    assert (nominal_bar_mass(Decimal("12"), T_DENSITY)
            == PI * Decimal("0.012") * Decimal("0.012")
            / Decimal("4") * T_DENSITY)


def test_formula_rejects_bad_inputs():
    with pytest.raises(ValidationError):
        nominal_bar_mass(Decimal("0"), T_DENSITY)
    with pytest.raises(ValidationError):
        nominal_bar_mass(Decimal("-12"), T_DENSITY)
    with pytest.raises(Exception):
        nominal_bar_mass(Decimal("12"), Decimal("0"))


def test_no_baked_in_steel_constant():
    # Same diameter, different densities -> proportionally different mass.
    assert (nominal_bar_mass(Decimal("12"), Decimal("2000"))
            == 2 * nominal_bar_mass(Decimal("12"), T_DENSITY))


# --- resolution ------------------------------------------------------------

def test_skeleton_keys_look_up_with_null_mass():
    repo = shipped_repo()
    assert {r["key"] for r in repo.list("rebar_bars")} == {
        "Y8", "Y10", "Y12", "Y16", "Y20", "Y25", "Y32"}
    assert repo.get("rebar_bars", "Y12")["diameter_mm"] == "12"
    assert repo.get("rebar_bars", "Y12")["mass_kg_per_m"] is None


def test_unknown_bar_key_raises():
    with pytest.raises(UnknownMasterDataKeyError):
        resolve_rebar_bar("Y99", shipped_repo(), RebarBarOverride(
            mass_kg_per_m=T_MASS))


def test_unverified_without_overrides_fails_closed():
    with pytest.raises(UnverifiedMasterDataError):
        resolve_rebar_bar("Y12", shipped_repo())


def test_explicit_mass_override_resolves_override_path():
    # Estimator-specified unit mass must be provenance "override" —
    # never reported as a table value the master data never provided.
    resolved = resolve_rebar_bar(
        "Y12", shipped_repo(), RebarBarOverride(mass_kg_per_m=T_MASS))
    assert resolved.mass_kg_per_m == T_MASS
    assert resolved.mass_source == MASS_SOURCE_OVERRIDE
    assert resolved.diameter_mm == Decimal("12")
    assert resolved.overrides_used is True
    assert "mass_kg_per_m" in resolved.overridden_fields


def test_formula_path_with_explicit_density():
    resolved = resolve_rebar_bar(
        "Y12", shipped_repo(), RebarBarOverride(
            diameter_mm=Decimal("12"), steel_density_kg_per_m3=T_DENSITY))
    assert resolved.mass_source == MASS_SOURCE_FORMULA
    assert resolved.mass_kg_per_m == nominal_bar_mass(Decimal("12"), T_DENSITY)
    assert resolved.overrides_used is True


def test_formula_path_uses_record_diameter_with_override_density():
    # The skeleton's nominal diameter is designation nomenclature (Y12
    # means 12 mm), so density-only overrides resolve via the formula.
    resolved = resolve_rebar_bar(
        "Y12", shipped_repo(),
        RebarBarOverride(steel_density_kg_per_m3=T_DENSITY))
    assert resolved.mass_source == MASS_SOURCE_FORMULA
    assert (resolved.mass_kg_per_m
            == nominal_bar_mass(Decimal("12"), T_DENSITY))
    assert resolved.diameter_mm == Decimal("12")


def test_wastage_override_carried():
    resolved = resolve_rebar_bar(
        "Y12", shipped_repo(), RebarBarOverride(
            mass_kg_per_m=T_MASS, wastage_pct=Decimal("7")))
    assert resolved.wastage_pct == Decimal("7")


def test_verified_record_needs_no_overrides(tmp_path):
    record = {
        "key": "YB", "diameter_mm": "12", "mass_kg_per_m": "0.888",
        "default_wastage_pct": "5",
        "source": "TEST FIXTURE ONLY", "version": "t",
        "effective_date": "2026-01-01",
        "verification_status": VerificationStatus.VERIFIED,
    }
    (tmp_path / "rebar_bars.json").write_text(json.dumps({
        "schema_version": "0.1", "table_version": "t",
        "records": [record],
    }), encoding="utf-8")
    repo = MasterDataRepository(tmp_path)
    resolved = resolve_rebar_bar("YB", repo)
    assert resolved.mass_kg_per_m == Decimal("0.888")
    assert resolved.mass_source == MASS_SOURCE_TABLE
    assert resolved.overrides_used is False
    assert resolved.wastage_pct == Decimal("5")


# --- bar lines -------------------------------------------------------------

def make_resolved(mass=T_MASS):
    return resolve_rebar_bar(
        "Y12", shipped_repo(), RebarBarOverride(mass_kg_per_m=mass))


def test_bar_line_exact_totals():
    # 10 bars x (6 + 2x1.0 laps + 0.3 hooks) = 83 m; x 2 kg/m = 166 kg.
    line = BarLineInput(bar_key="Y12", count=10, length_per_bar_m=Decimal("6"),
                        laps_per_bar=2, lap_length_m=Decimal("1.0"),
                        hook_extra_per_bar_m=Decimal("0.3"))
    result = calculate_bar_line(line, make_resolved())
    assert result.total_length_m == Decimal("83.0")
    assert result.total_mass_kg == Decimal("166.0")
    assert result.mass_kg_per_m == T_MASS


def test_bar_line_key_mismatch_rejected():
    line = BarLineInput(bar_key="Y16", count=2, length_per_bar_m=Decimal("6"))
    with pytest.raises(ValidationError):
        calculate_bar_line(line, make_resolved())


def test_bar_line_bad_inputs_rejected():
    with pytest.raises(ValidationError):
        BarLineInput(bar_key="Y12", count=0, length_per_bar_m=Decimal("6"))
    with pytest.raises(ValidationError):
        BarLineInput(bar_key="Y12", count=2.5, length_per_bar_m=Decimal("6"))
    with pytest.raises(ValidationError):
        BarLineInput(bar_key="Y12", count=2, length_per_bar_m=Decimal("6"),
                     laps_per_bar=-1)


# --- schedule --------------------------------------------------------------

def test_schedule_totals_wastage_wire():
    line = BarLineInput(bar_key="Y12", count=10, length_per_bar_m=Decimal("6"),
                        laps_per_bar=2, lap_length_m=Decimal("1.0"),
                        hook_extra_per_bar_m=Decimal("0.3"))
    result = calculate_bar_line(line, make_resolved())
    schedule = calculate_rebar_schedule(
        [result], wastage_pct=Decimal("5"), tying_wire_kg_per_tonne=Decimal("2"))
    assert schedule.total_length_m == Decimal("83.0")
    assert schedule.total_mass_kg == Decimal("166.0")
    assert schedule.total_mass_tonnes == Decimal("0.166")
    assert schedule.wastage.wastage_quantity == Decimal("8.30")
    assert schedule.wastage.quantity_after_wastage == Decimal("174.30")
    assert schedule.wastage.rounding_applied is False
    assert schedule.tying_wire_kg == Decimal("0.332")


def test_schedule_wire_optional_and_wastage_required():
    line = BarLineInput(bar_key="Y12", count=2, length_per_bar_m=Decimal("6"))
    result = calculate_bar_line(line, make_resolved())
    schedule = calculate_rebar_schedule([result], wastage_pct=Decimal("0"))
    assert schedule.tying_wire_kg is None
    assert schedule.wastage.quantity_after_wastage == schedule.total_mass_kg


def test_schedule_rejects_empty_and_bad_wastage():
    with pytest.raises(ValidationError):
        calculate_rebar_schedule([], wastage_pct=Decimal("5"))
    line = BarLineInput(bar_key="Y12", count=2, length_per_bar_m=Decimal("6"))
    result = calculate_bar_line(line, make_resolved())
    with pytest.raises(Exception):
        calculate_rebar_schedule([result], wastage_pct=Decimal("101"))
