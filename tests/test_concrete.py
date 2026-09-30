"""Concrete engine tests (Phase 2).

All numeric fixtures below are ARBITRARY TEST VALUES to exercise the math —
they are not project engineering data and must never be mistaken for
verified mixes, densities, or factors.
"""

import json
from decimal import Decimal

import pytest

from qs_engine.concrete.engine import (
    ConcreteMixOverride,
    calculate_concrete_requirement,
    cement_bags,
    constituent_masses,
    dry_constituent_volume,
    resolve_mix,
    split_constituents,
    water_requirement,
    wet_concrete_volume,
)
from qs_engine.core.assumptions import VerificationStatus
from qs_engine.core.errors import (
    UnverifiedMasterDataError,
    ValidationError,
    UnknownMasterDataKeyError,
    NonPositiveDimensionError,
)
from qs_engine.master_data.repository import MasterDataRepository

# --- arbitrary test-only fixtures (NOT engineering data) ------------------
T_DRY_FACTOR = Decimal("1.5")
T_RATIOS = (Decimal("1"), Decimal("2"), Decimal("4"))
T_DENSITY = Decimal("1000")
T_BAG = Decimal("50")  # per Phase 2 brief: 50 kg bags under test
T_WC = Decimal("0.5")
T_WATER_DENSITY = Decimal("1")


def full_overrides(**changes):
    fields = {
        "dry_factor": T_DRY_FACTOR,
        "cement_ratio": T_RATIOS[0],
        "sand_ratio": T_RATIOS[1],
        "aggregate_ratio": T_RATIOS[2],
        "wc_ratio": T_WC,
        "cement_density_kg_per_m3": T_DENSITY,
        "sand_density_kg_per_m3": T_DENSITY,
        "aggregate_density_kg_per_m3": T_DENSITY,
        "water_density_kg_per_L": T_WATER_DENSITY,
        "bag_mass_kg": T_BAG,
    }
    fields.update(changes)
    return ConcreteMixOverride(**fields)


def shipped_repo():
    return MasterDataRepository()  # includes Phase 2 skeleton classes


# --- wet volume ------------------------------------------------------------

def test_wet_volume_nominal():
    qty = wet_concrete_volume(Decimal("5"), Decimal("4"), Decimal("0.15"))
    assert qty.value == Decimal("3.0")
    assert qty.unit == "m\u00b3"


def test_wet_volume_mm_inputs():
    qty = wet_concrete_volume(5000, 4000, 150, unit="mm")
    assert qty.value == Decimal("3.0")


def test_wet_volume_rejects_bad_dims():
    with pytest.raises(NonPositiveDimensionError):
        wet_concrete_volume(0, 4, 0.15)
    with pytest.raises(NonPositiveDimensionError):
        wet_concrete_volume(5, -4, 0.15)


def test_wet_volume_rejects_unknown_unit():
    from qs_engine.core.errors import UnknownUnitError
    with pytest.raises(UnknownUnitError):
        wet_concrete_volume(5, 4, 0.15, unit="furlong")


# --- dry factor ------------------------------------------------------------

def test_dry_scaling():
    assert dry_constituent_volume(Decimal("3"), T_DRY_FACTOR) == Decimal("4.5")


def test_dry_factor_one_allowed_below_one_rejected():
    assert dry_constituent_volume(Decimal("3"), Decimal("1")) == Decimal("3")
    with pytest.raises(ValidationError):
        dry_constituent_volume(Decimal("3"), Decimal("0.9"))


# --- ratio split -----------------------------------------------------------

def test_split_1_2_4_sums_to_dry():
    vols = split_constituents(Decimal("7"), *T_RATIOS, T_DRY_FACTOR)
    assert vols.cement_m3 == Decimal("1")
    assert vols.sand_m3 == Decimal("2")
    assert vols.aggregate_m3 == Decimal("4")
    assert vols.cement_m3 + vols.sand_m3 + vols.aggregate_m3 == vols.dry_volume_m3


def test_split_rejects_non_positive_part():
    with pytest.raises(ValidationError):
        split_constituents(Decimal("7"), Decimal("0"), Decimal("2"), Decimal("4"), T_DRY_FACTOR)
    with pytest.raises(ValidationError):
        split_constituents(Decimal("7"), Decimal("1"), Decimal("-2"), Decimal("4"), T_DRY_FACTOR)


# --- masses ----------------------------------------------------------------

def test_masses_volume_times_density():
    vols = split_constituents(Decimal("7"), *T_RATIOS, T_DRY_FACTOR)
    masses = constituent_masses(vols, T_DENSITY, T_DENSITY, T_DENSITY)
    assert masses.cement_kg == Decimal("1000")
    assert masses.sand_kg == Decimal("2000")
    assert masses.aggregate_kg == Decimal("4000")


def test_masses_reject_bad_density():
    vols = split_constituents(Decimal("7"), *T_RATIOS, T_DRY_FACTOR)
    with pytest.raises(Exception):
        constituent_masses(vols, Decimal("0"), T_DENSITY, T_DENSITY)


# --- bags ------------------------------------------------------------------

def test_bags_exact_and_ceiling():
    bags = cement_bags(Decimal("512.4"), T_BAG, round_up=True)
    assert bags.calculated_bags == Decimal("10.248")
    assert bags.ordering_bags == 11
    assert bags.ceiling_applied is True
    assert bags.bag_mass_kg == T_BAG


def test_bags_exact_count_unchanged_by_ceiling():
    bags = cement_bags(Decimal("500"), T_BAG, round_up=True)
    assert bags.calculated_bags == Decimal("10")
    assert bags.ordering_bags == 10


def test_bags_no_rounding_option():
    bags = cement_bags(Decimal("512.4"), T_BAG, round_up=False)
    assert bags.calculated_bags == Decimal("10.248")
    assert bags.ordering_bags is None
    assert bags.ceiling_applied is False


def test_bags_reject_bad_bag_mass():
    with pytest.raises(ValidationError):
        cement_bags(Decimal("100"), Decimal("0"))
    with pytest.raises(ValidationError):
        cement_bags(Decimal("100"), Decimal("-50"))


def test_bag_mass_not_hardcoded():
    # Same cement mass, different bag size -> different count.
    assert cement_bags(Decimal("500"), Decimal("50")).ordering_bags == 10
    assert cement_bags(Decimal("500"), Decimal("25")).ordering_bags == 20


# --- water -----------------------------------------------------------------

def test_water_from_wc_ratio():
    water = water_requirement(Decimal("300"), T_WC, T_WATER_DENSITY)
    assert water.water_litres == Decimal("150")
    assert water.wc_ratio == T_WC


def test_water_rejects_bad_inputs():
    with pytest.raises(ValidationError):
        water_requirement(Decimal("300"), Decimal("0"), T_WATER_DENSITY)
    with pytest.raises(Exception):
        water_requirement(Decimal("300"), T_WC, Decimal("0"))


# --- class lookup + fail-closed --------------------------------------------

def test_skeleton_keys_look_up():
    repo = shipped_repo()
    for key, name in (("class_c15", "C15"), ("class_c20", "C20"),
                      ("class_c25", "C25"), ("class_c30", "C30")):
        assert repo.get("concrete_classes", key)["class_name"] == name


def test_unknown_class_key_raises():
    with pytest.raises(UnknownMasterDataKeyError):
        resolve_mix("class_c99", shipped_repo(), full_overrides())


def test_unverified_class_without_overrides_fails_closed():
    with pytest.raises(UnverifiedMasterDataError):
        resolve_mix("class_c20", shipped_repo())
    with pytest.raises(UnverifiedMasterDataError):
        calculate_concrete_requirement(
            length=2, width=2, thickness=Decimal("0.1"),
            class_key="class_c20", repository=shipped_repo())


def test_partial_overrides_fail_closed_with_missing_listed():
    partial = ConcreteMixOverride(dry_factor=T_DRY_FACTOR)
    assert not partial.is_complete()
    assert "cement_ratio" in partial.missing()
    try:
        resolve_mix("class_c20", shipped_repo(), partial)
        raise AssertionError("should have raised")
    except UnverifiedMasterDataError as exc:
        assert "cement_ratio" in str(exc)


def test_full_overrides_proceed_with_provenance():
    mix = resolve_mix("class_c20", shipped_repo(), full_overrides())
    assert mix.class_key == "class_c20"
    assert mix.overrides_used is True
    assert set(mix.overridden_fields) == {
        "dry_factor", "cement_ratio", "sand_ratio", "aggregate_ratio",
        "wc_ratio", "cement_density_kg_per_m3", "sand_density_kg_per_m3",
        "aggregate_density_kg_per_m3", "water_density_kg_per_L", "bag_mass_kg",
    }
    assert mix.master_version == "2.0-skeleton"


def test_verified_record_needs_no_overrides(tmp_path):
    record = {
        "key": "class_t", "class_name": "CT",
        "cement_ratio": "1", "sand_ratio": "1", "aggregate_ratio": "2",
        "dry_volume_factor": "2", "wc_ratio": "0.5",
        "cement_density_kg_per_m3": "1000", "sand_density_kg_per_m3": "1000",
        "aggregate_density_kg_per_m3": "1000", "water_density_kg_per_L": "1",
        "bag_mass_kg": "50", "default_wastage_pct": "5",
        "source": "TEST FIXTURE ONLY", "version": "t",
        "effective_date": "2026-01-01",
        "verification_status": VerificationStatus.VERIFIED,
    }
    (tmp_path / "concrete_classes.json").write_text(json.dumps({
        "schema_version": "0.1", "table_version": "t",
        "records": [record],
    }), encoding="utf-8")
    repo = MasterDataRepository(tmp_path)
    mix = resolve_mix("class_t", repo)
    assert mix.overrides_used is False
    assert mix.dry_factor == Decimal("2")


# --- end-to-end (exact terminating-decimal case) ----------------------------

def test_end_to_end_exact():
    # 1x1x1 m -> 1 m3 wet; K=2 -> 2 dry; 1:1:2 -> 0.5/0.5/1.0;
    # densities 1000 -> 500/500/1000 kg; 50 kg bags -> 10; water 250 L.
    req = calculate_concrete_requirement(
        length=1, width=1, thickness=1, class_key="class_c20",
        repository=shipped_repo(),
        overrides=full_overrides(dry_factor=Decimal("2"),
                                 cement_ratio=Decimal("1"),
                                 sand_ratio=Decimal("1"),
                                 aggregate_ratio=Decimal("2")),
        element="test slab")
    assert req.wet_volume.value == Decimal("1")
    assert req.constituents.dry_volume_m3 == Decimal("2")
    assert req.constituents.cement_m3 == Decimal("0.5")
    assert req.constituents.sand_m3 == Decimal("0.5")
    assert req.constituents.aggregate_m3 == Decimal("1.0")
    assert req.masses.cement_kg == Decimal("500")
    assert req.masses.sand_kg == Decimal("500")
    assert req.masses.aggregate_kg == Decimal("1000")
    assert req.bags.calculated_bags == Decimal("10")
    assert req.bags.ordering_bags == 10
    assert req.water.water_litres == Decimal("250")
    assert req.element == "test slab"
    assert req.resolved_mix.overrides_used is True
