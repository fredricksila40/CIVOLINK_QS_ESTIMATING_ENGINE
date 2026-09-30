"""Masonry engine tests (Phase 3).

All numeric fixtures below are ARBITRARY TEST VALUES to exercise the math —
they are not project engineering data and must never be mistaken for
verified unit sizes, joints, mixes, densities, or factors.
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
from qs_engine.masonry.engine import (
    MasonryUnitOverride,
    calculate_masonry_requirement,
    gross_wall_volume,
    net_unit_volume,
    resolve_masonry_unit,
    split_mortar,
    mortar_constituents,
    unit_takeoff,
    wall_areas,
    wet_mortar_volume,
)
from qs_engine.master_data.repository import MasterDataRepository

# --- arbitrary test-only fixtures (NOT engineering data) ------------------
T_UNIT = {"length_mm": Decimal("390"), "height_mm": Decimal("190"),
          "thickness_mm": Decimal("200")}
T_JOINTS = {"bed": Decimal("10"), "perp": Decimal("10")}
T_WASTE = Decimal("5")
T_RATIOS = (Decimal("1"), Decimal("3"))
T_DRY = Decimal("1.5")
T_DENSITY = Decimal("1000")
T_BAG = Decimal("50")


def full_overrides(**changes):
    fields = {
        "unit_length_mm": T_UNIT["length_mm"],
        "unit_height_mm": T_UNIT["height_mm"],
        "unit_thickness_mm": T_UNIT["thickness_mm"],
        "bed_joint_mm": T_JOINTS["bed"],
        "perp_joint_mm": T_JOINTS["perp"],
        "wastage_pct": T_WASTE,
        "mortar_cement_ratio": T_RATIOS[0],
        "mortar_sand_ratio": T_RATIOS[1],
        "mortar_dry_factor": T_DRY,
        "mortar_sand_density_kg_per_m3": T_DENSITY,
        "cement_density_kg_per_m3": T_DENSITY,
        "bag_mass_kg": T_BAG,
    }
    fields.update(changes)
    return MasonryUnitOverride(**fields)


def shipped_repo():
    return MasterDataRepository()  # includes Phase 3 skeleton units


# --- wall areas ------------------------------------------------------------

def test_wall_areas_gross_and_net():
    wall = wall_areas(Decimal("4"), Decimal("2"))
    assert wall.gross_m2 == Decimal("8")
    assert wall.openings_m2 == Decimal("0")
    assert wall.net_m2 == Decimal("8")


def test_wall_areas_with_openings():
    wall = wall_areas(4, 2, openings=[(Decimal("1"), Decimal("1")),
                                      (Decimal("0.9"), Decimal("2.1"))])
    assert wall.gross_m2 == Decimal("8")
    assert wall.openings_m2 == Decimal("2.89")
    assert wall.net_m2 == Decimal("5.11")


def test_wall_areas_reject_excess_openings():
    with pytest.raises(ValidationError):
        wall_areas(1, 1, openings=[(Decimal("2"), Decimal("2"))])


def test_wall_areas_reject_bad_opening_shape():
    with pytest.raises(ValidationError):
        wall_areas(4, 2, openings=[(Decimal("1"),)])


def test_wall_areas_reject_bad_dims():
    with pytest.raises(NonPositiveDimensionError):
        wall_areas(0, 2)


# --- unit takeoff ----------------------------------------------------------

def test_takeoff_exact_face_math():
    # Face incl. joints: (390+10) x (190+10) = 400 x 200 mm = 0.08 m2.
    # 8 m2 net -> exactly 100 units before waste.
    takeoff = unit_takeoff(Decimal("8"), T_UNIT["length_mm"],
                           T_UNIT["height_mm"], T_JOINTS["bed"],
                           T_JOINTS["perp"], T_WASTE)
    assert takeoff.unit_face_area_m2 == Decimal("0.08")
    assert takeoff.units_exact == Decimal("100")
    assert takeoff.units_with_waste == Decimal("105")
    assert takeoff.units_order == 105
    assert takeoff.wastage.wastage_quantity == Decimal("5")
    assert takeoff.wastage.rounding_applied is False


def test_takeoff_zero_joints_allowed():
    takeoff = unit_takeoff(Decimal("8"), Decimal("400"), Decimal("200"),
                           Decimal("0"), Decimal("0"), T_WASTE)
    assert takeoff.unit_face_area_m2 == Decimal("0.08")
    assert takeoff.units_exact == Decimal("100")


def test_takeoff_rejects_bad_inputs():
    with pytest.raises(NonPositiveDimensionError):
        unit_takeoff(Decimal("8"), Decimal("0"), Decimal("190"),
                     T_JOINTS["bed"], T_JOINTS["perp"], T_WASTE)
    with pytest.raises(Exception):
        unit_takeoff(Decimal("8"), T_UNIT["length_mm"], T_UNIT["height_mm"],
                     Decimal("-1"), T_JOINTS["perp"], T_WASTE)
    with pytest.raises(Exception):
        unit_takeoff(Decimal("-8"), T_UNIT["length_mm"], T_UNIT["height_mm"],
                     T_JOINTS["bed"], T_JOINTS["perp"], T_WASTE)


# --- conservative mortar identity ------------------------------------------

def test_wet_mortar_identity():
    assert wet_mortar_volume(Decimal("1.6"), Decimal("1.5561")) == Decimal("0.0439")


def test_wet_mortar_floored_at_zero_with_inputs_visible():
    # Tiny patch: ceiled whole unit exceeds the gross wall volume.
    assert wet_mortar_volume(Decimal("0.008"), Decimal("0.01482")) == Decimal("0")


def test_gross_and_net_volumes():
    assert gross_wall_volume(Decimal("8"), Decimal("200")) == Decimal("1.6")
    # One unit: 390 x 190 x 200 mm = 0.01482 m3.
    assert net_unit_volume(1, T_UNIT["length_mm"], T_UNIT["height_mm"],
                           T_UNIT["thickness_mm"]) == Decimal("0.01482")
    assert net_unit_volume(105, T_UNIT["length_mm"], T_UNIT["height_mm"],
                           T_UNIT["thickness_mm"]) == Decimal("1.5561")


# --- mortar split + constituents -------------------------------------------

def test_split_sums_to_dry():
    vols = split_mortar(Decimal("0.0439"), Decimal("0.06585"),
                        *T_RATIOS, T_DRY, Decimal("1.6"), Decimal("1.5561"))
    assert vols.cement_m3 == Decimal("0.0164625")
    assert vols.sand_m3 == Decimal("0.0493875")
    assert vols.cement_m3 + vols.sand_m3 == vols.dry_mortar_m3
    assert vols.wet_mortar_m3 == Decimal("0.0439")


def test_split_rejects_bad_ratios():
    with pytest.raises(ValidationError):
        split_mortar(Decimal("0.04"), Decimal("0.06"), Decimal("0"),
                     Decimal("3"), T_DRY, Decimal("1.6"), Decimal("1.55"))


def test_constituents_mass_and_sand_volume():
    vols = split_mortar(Decimal("0.0439"), Decimal("0.06585"),
                        *T_RATIOS, T_DRY, Decimal("1.6"), Decimal("1.5561"))
    const = mortar_constituents(vols, T_DENSITY, T_DENSITY)
    assert const.cement_kg == Decimal("16.4625")
    assert const.sand_kg == Decimal("49.3875")
    assert const.sand_m3 == Decimal("0.0493875")


# --- lookup + fail-closed ---------------------------------------------------

def test_skeleton_keys_look_up_with_nulls():
    repo = shipped_repo()
    keys = {r["key"] for r in repo.list("masonry_units")}
    assert keys == {"machine_cut_stone_200mm", "concrete_block_200mm",
                    "concrete_block_150mm"}
    for record in repo.list("masonry_units"):
        assert record["verification_status"] == "NEEDS_VERIFICATION"
        assert record["length_mm"] is None


def test_unknown_unit_key_raises():
    with pytest.raises(UnknownMasterDataKeyError):
        resolve_masonry_unit("block_xyz", shipped_repo(), full_overrides())


def test_unverified_unit_without_overrides_fails_closed():
    with pytest.raises(UnverifiedMasterDataError):
        resolve_masonry_unit("concrete_block_200mm", shipped_repo())
    with pytest.raises(UnverifiedMasterDataError):
        calculate_masonry_requirement(
            wall_length=4, wall_height=2,
            unit_key="concrete_block_200mm", repository=shipped_repo())


def test_partial_overrides_fail_closed_with_missing_listed():
    partial = MasonryUnitOverride(unit_length_mm=Decimal("390"))
    assert not partial.is_complete()
    assert "mortar_cement_ratio" in partial.missing()
    try:
        resolve_masonry_unit("concrete_block_200mm", shipped_repo(), partial)
        raise AssertionError("should have raised")
    except UnverifiedMasterDataError as exc:
        assert "mortar_cement_ratio" in str(exc)


def test_full_overrides_proceed_with_provenance():
    resolved = resolve_masonry_unit(
        "concrete_block_200mm", shipped_repo(), full_overrides())
    assert resolved.unit_key == "concrete_block_200mm"
    assert resolved.overrides_used is True
    assert "mortar_dry_factor" in resolved.overridden_fields
    assert resolved.master_version == "3.0-skeleton"


def test_verified_record_needs_no_overrides(tmp_path):
    record = {
        "key": "unit_t", "name": "Unit T",
        "length_mm": "390", "height_mm": "190", "thickness_mm": "200",
        "bed_joint_mm": "10", "perp_joint_mm": "10",
        "mortar_cement_ratio": "1", "mortar_sand_ratio": "3",
        "mortar_dry_factor": "1.5",
        "mortar_sand_density_kg_per_m3": "1000",
        "cement_density_kg_per_m3": "1000",
        "bag_mass_kg": "50", "default_wastage_pct": "5",
        "source": "TEST FIXTURE ONLY", "version": "t",
        "effective_date": "2026-01-01",
        "verification_status": VerificationStatus.VERIFIED,
    }
    (tmp_path / "masonry_units.json").write_text(json.dumps({
        "schema_version": "0.1", "table_version": "t",
        "records": [record],
    }), encoding="utf-8")
    repo = MasterDataRepository(tmp_path)
    resolved = resolve_masonry_unit("unit_t", repo)
    assert resolved.overrides_used is False
    assert resolved.unit_length_mm == Decimal("390")


# --- end-to-end (exact terminating-decimal case) ----------------------------

def test_end_to_end_exact():
    # 4x2 m wall, no openings -> 8 m2; 390x190+10 joints -> 0.08 m2 face;
    # 100 exact + 5% -> 105 ordered; gross 1.6, net 1.5561, wet 0.0439;
    # dry 0.06585; 1:3 -> cement 0.0164625 / sand 0.0493875;
    # 16.4625 kg cement -> 0.32925 bags -> order 1.
    req = calculate_masonry_requirement(
        wall_length=4, wall_height=2,
        unit_key="concrete_block_200mm", repository=shipped_repo(),
        overrides=full_overrides(), element="test wall")
    assert req.wall.gross_m2 == Decimal("8")
    assert req.wall.net_m2 == Decimal("8")
    assert req.takeoff.units_exact == Decimal("100")
    assert req.takeoff.units_order == 105
    assert req.mortar_volumes.wet_mortar_m3 == Decimal("0.0439")
    assert req.mortar_volumes.dry_mortar_m3 == Decimal("0.06585")
    assert req.mortar_constituents.cement_kg == Decimal("16.4625")
    assert req.mortar_constituents.sand_kg == Decimal("49.3875")
    assert req.mortar_constituents.sand_m3 == Decimal("0.0493875")
    assert req.bags.calculated_bags == Decimal("0.32925")
    assert req.bags.ordering_bags == 1
    assert req.bags.ceiling_applied is True
    assert req.element == "test wall"
    assert req.resolved_unit.overrides_used is True


def test_end_to_end_with_openings_and_floor():
    # 0.2x0.2 m patch with a 0.1x0.1 opening -> net 0.03 m2; one unit
    # ordered (ceiling) exceeds gross -> wet mortar floors at 0, dry 0.
    req = calculate_masonry_requirement(
        wall_length=Decimal("0.2"), wall_height=Decimal("0.2"),
        openings=[(Decimal("0.1"), Decimal("0.1"))],
        unit_key="concrete_block_200mm", repository=shipped_repo(),
        overrides=full_overrides(), element="patch")
    assert req.wall.net_m2 == Decimal("0.03")
    assert req.takeoff.units_order == 1
    assert req.mortar_volumes.wet_mortar_m3 == Decimal("0")
    assert req.mortar_volumes.dry_mortar_m3 == Decimal("0")
    assert req.bags.ordering_bags == 0
