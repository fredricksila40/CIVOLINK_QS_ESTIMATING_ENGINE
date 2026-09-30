"""Finishes tests (Phase 6): plaster, screed, tiles, painting.

Geometry fixtures are arbitrary room/element sizes. Rate/wastage/mix
fixtures are ARBITRARY TEST VALUES passed as explicit overrides — never
project data and never to be mistaken for verified values.
"""

import json
from decimal import Decimal

import pytest

from qs_engine.core.assumptions import VerificationStatus
from qs_engine.core.errors import (
    NonPositiveDimensionError,
    UnknownMasterDataKeyError,
    ValidationError,
)
from qs_engine.finishes.resolution import (
    MortarOverride,
    PaintOverride,
    TileConsumablesOverride,
    resolve_mortar_materials,
    resolve_paint_materials,
    resolve_tile_consumables,
)
from qs_engine.finishes.results import Opening, UnresolvedRequirement
from qs_engine.finishes.takeoff import (
    normalize_openings,
    paint_takeoff,
    plaster_takeoff,
    screed_takeoff,
    tile_takeoff,
)
from qs_engine.master_data.repository import MasterDataRepository


def shipped_repo():
    return MasterDataRepository()


# --- openings --------------------------------------------------------------

def test_opening_area_with_count():
    opening = Opening(Decimal("1"), Decimal("2"), count=2)
    assert opening.area_m2 == Decimal("4")


def test_opening_rejects_bad_inputs():
    with pytest.raises(ValidationError):
        Opening(Decimal("1"), Decimal("2"), count=0)
    with pytest.raises(NonPositiveDimensionError):
        Opening(Decimal("0"), Decimal("2"))
    with pytest.raises(ValidationError):
        Opening(Decimal("1"), Decimal("2"), count=2.0)


def test_normalize_mixed_opening_forms():
    total = normalize_openings(
        [Opening(Decimal("1"), Decimal("1"), count=2),
         (Decimal("2"), Decimal("1")),
         (Decimal("1"), Decimal("1"), 3)], unit="m")
    assert total == Decimal("7")


def test_normalize_rejects_bad_shapes():
    with pytest.raises(ValidationError):
        normalize_openings([(Decimal("1"),)], unit="m")
    with pytest.raises(ValidationError):
        normalize_openings([(Decimal("1"), Decimal("1"), 0)], unit="m")


# --- plaster ---------------------------------------------------------------

def test_plaster_areas_openings_faces():
    # 4x3 both faces = 24 gross; two 1x1 openings deducted per face = 4.
    result = plaster_takeoff(length=4, height=3, faces=2,
                             openings=[(Decimal("1"), Decimal("1"), 2)],
                             thickness=Decimal("12"))
    assert result.gross_m2 == Decimal("24")
    assert result.openings_m2 == Decimal("4")
    assert result.net_m2 == Decimal("20")
    assert result.thickness_m == Decimal("0.012")
    assert result.volume_m3 == Decimal("0.24")
    assert result.takeoff.quantity.value == Decimal("20")
    assert result.takeoff.quantity.unit == "m\u00b2"


def test_plaster_single_face_tuple_openings():
    result = plaster_takeoff(length=4, height=3, faces=1,
                             openings=[(Decimal("1"), Decimal("2"))],
                             thickness=Decimal("12"))
    assert result.net_m2 == Decimal("10")


def test_plaster_rejects_bad_inputs():
    with pytest.raises(ValidationError):
        plaster_takeoff(length=4, height=3, faces=3,
                        thickness=Decimal("12"))
    with pytest.raises(NonPositiveDimensionError):
        plaster_takeoff(length=4, height=3, thickness=Decimal("0"))
    with pytest.raises(ValidationError):
        plaster_takeoff(length=1, height=1,
                        openings=[(Decimal("2"), Decimal("2"))],
                        thickness=Decimal("12"))


# --- screed ----------------------------------------------------------------

def test_screed_area_thickness_volume():
    # 5x4 m at 50 mm -> 20 m2, 1.0 m3.
    result = screed_takeoff(length=5, width=4, thickness=Decimal("50"))
    assert result.area_m2 == Decimal("20")
    assert result.thickness_m == Decimal("0.05")
    assert result.volume_m3 == Decimal("1.0")
    assert result.takeoff.quantity.value == Decimal("1.0")
    assert result.takeoff.quantity.unit == "m\u00b3"


def test_screed_rejects_bad_inputs():
    with pytest.raises(NonPositiveDimensionError):
        screed_takeoff(length=5, width=4, thickness=Decimal("0"))
    with pytest.raises(NonPositiveDimensionError):
        screed_takeoff(length=5, width=Decimal("-4"), thickness=Decimal("50"))


# --- tiles -----------------------------------------------------------------

def test_tile_count_exact_and_ceiling():
    # 5x2 m = 10 m2; 500x500 butt-jointed = 0.25 m2 -> 40 exact;
    # 10% waste -> 44 ordered.
    result = tile_takeoff(length=5, width=2, tile_length_mm=Decimal("500"),
                          tile_width_mm=Decimal("500"), joint_mm=Decimal("0"),
                          wastage_pct=Decimal("10"))
    assert result.tile_area_m2 == Decimal("0.25")
    assert result.theoretical_count == Decimal("40")
    assert result.wastage.wastage_quantity == Decimal("4")
    assert result.order_quantity == 44
    assert result.unresolved == ()
    assert result.takeoff.quantity.unit == "piece"


def test_tile_unresolved_wastage_stays_unresolved():
    result = tile_takeoff(length=5, width=2, tile_length_mm=Decimal("500"),
                          tile_width_mm=Decimal("500"), joint_mm=Decimal("5"))
    assert result.theoretical_count == result.takeoff.quantity.value
    assert result.wastage is None
    assert result.order_quantity is None
    assert any("wastage_pct" in note for note in result.unresolved)


def test_tile_openings_and_joints():
    # 6x4 = 24 less 2x2 opening = 20 net; 300x300 + 5 joint.
    result = tile_takeoff(length=6, width=4,
                          openings=[(Decimal("2"), Decimal("2"))],
                          tile_length_mm=Decimal("300"),
                          tile_width_mm=Decimal("300"),
                          joint_mm=Decimal("5"),
                          wastage_pct=Decimal("0"))
    assert result.net_area_m2 == Decimal("20")
    assert result.tile_area_m2 == Decimal("0.093025")
    # 20 / 0.093025 = 214.9959... -> ceiling 215 (0% waste).
    assert result.order_quantity == 215
    assert result.wastage.quantity_after_wastage == result.theoretical_count


def test_tile_rejects_bad_inputs():
    with pytest.raises(NonPositiveDimensionError):
        tile_takeoff(length=5, width=2, tile_length_mm=Decimal("0"),
                     tile_width_mm=Decimal("500"), joint_mm=Decimal("0"))
    with pytest.raises(Exception):
        tile_takeoff(length=5, width=2, tile_length_mm=Decimal("500"),
                     tile_width_mm=Decimal("500"), joint_mm=Decimal("-1"))


# --- paint -----------------------------------------------------------------

def test_paint_areas_coats():
    # 4x3 single face = 12 gross; 1x2 opening = 2; net 10; 3 coats = 30.
    result = paint_takeoff(length=4, height=3, faces=1,
                           openings=[(Decimal("1"), Decimal("2"))], coats=3)
    assert result.gross_m2 == Decimal("12")
    assert result.openings_m2 == Decimal("2")
    assert result.net_m2 == Decimal("10")
    assert result.total_coated_m2 == Decimal("30")
    assert result.takeoff.quantity.value == Decimal("10")


def test_paint_faces_option():
    result = paint_takeoff(length=4, height=3, faces=2,
                           openings=[(Decimal("1"), Decimal("2"))], coats=2)
    assert result.net_m2 == Decimal("20")
    assert result.total_coated_m2 == Decimal("40")


def test_paint_rejects_bad_inputs():
    with pytest.raises(ValidationError):
        paint_takeoff(length=4, height=3, coats=0)
    with pytest.raises(ValidationError):
        paint_takeoff(length=4, height=3, coats="3")
    with pytest.raises(ValidationError):
        paint_takeoff(length=1, height=1,
                      openings=[(Decimal("2"), Decimal("2"))], coats=1)


# --- mortar resolution -----------------------------------------------------

def full_mortar(**changes):
    fields = {"cement_ratio": Decimal("1"), "sand_ratio": Decimal("3"),
              "dry_factor": Decimal("1.5"),
              "cement_density_kg_per_m3": Decimal("1000"),
              "sand_density_kg_per_m3": Decimal("1000"),
              "bag_mass_kg": Decimal("50"), "wastage_pct": Decimal("5")}
    fields.update(changes)
    return MortarOverride(**fields)


def test_mortar_unresolved_without_overrides():
    result = resolve_mortar_materials(
        mortar_volume_m3=Decimal("0.24"), repository=shipped_repo())
    assert isinstance(result, UnresolvedRequirement)
    assert result.requested == "mortar materials (cement, sand)"
    assert set(result.missing) == {
        "cement_ratio", "sand_ratio", "dry_factor",
        "cement_density_kg_per_m3", "sand_density_kg_per_m3",
        "bag_mass_kg", "wastage_pct"}
    assert "MortarOverride" in result.context


def test_mortar_partial_overrides_list_missing():
    result = resolve_mortar_materials(
        mortar_volume_m3=Decimal("0.24"), repository=shipped_repo(),
        overrides=MortarOverride(cement_ratio=Decimal("1")))
    assert isinstance(result, UnresolvedRequirement)
    assert "sand_ratio" in result.missing
    assert "cement_ratio" not in result.missing


def test_mortar_resolved_exact():
    # 0.24 wet x 1.5 = 0.36 dry; 1:3 -> 0.09 / 0.27;
    # 90 / 270 kg; +5% -> 94.5 / 283.5; bags 94.5/50 = 1.89 -> 2.
    result = resolve_mortar_materials(
        mortar_volume_m3=Decimal("0.24"), repository=shipped_repo(),
        overrides=full_mortar())
    assert result.cement.quantity.value == Decimal("94.5")
    assert result.cement.quantity.unit == "kg"
    assert result.cement.material_key == "portland_cement_42_5"
    assert result.sand.quantity.value == Decimal("283.5")
    assert result.sand.material_key == "river_sand"
    assert result.sand_m3 == Decimal("0.27")
    assert result.cement_waste.wastage_quantity == Decimal("4.5")
    assert result.bags.calculated_bags == Decimal("1.89")
    assert result.bags.ordering_bags == 2
    assert result.overrides_used is True


def test_mortar_unknown_material_key_fails_closed(tmp_path):
    from qs_engine.master_data.repository import MasterDataRepository as Repo
    repo = Repo(tmp_path)  # empty tables: no material keys at all
    from qs_engine.core.errors import UnknownMasterDataKeyError as U
    with pytest.raises(U):
        resolve_mortar_materials(
            mortar_volume_m3=Decimal("0.24"), repository=repo,
            overrides=full_mortar())


# --- paint resolution ------------------------------------------------------

def test_paint_unresolved_without_overrides():
    result = resolve_paint_materials(
        area_m2=Decimal("10"), coats=3, repository=shipped_repo(),
        coverage_key="emulsion_paint_per_coat",
        paint_material_key="emulsion_paint")
    assert isinstance(result, UnresolvedRequirement)
    assert any("coverage_m2_per_L" in note for note in result.missing)
    assert any("wastage_pct" in note for note in result.missing)


def test_paint_partial_override_still_unresolved():
    result = resolve_paint_materials(
        area_m2=Decimal("10"), coats=3, repository=shipped_repo(),
        coverage_key="emulsion_paint_per_coat",
        paint_material_key="emulsion_paint",
        overrides=PaintOverride(coverage_m2_per_L=Decimal("10")))
    assert isinstance(result, UnresolvedRequirement)
    assert any("wastage_pct" in note for note in result.missing)


def test_paint_resolved_exact():
    # 10 m2 x 3 coats / 10 m2/L = 3 L; +10% -> 3.3 L.
    result = resolve_paint_materials(
        area_m2=Decimal("10"), coats=3, repository=shipped_repo(),
        coverage_key="emulsion_paint_per_coat",
        paint_material_key="emulsion_paint",
        overrides=PaintOverride(coverage_m2_per_L=Decimal("10"),
                                wastage_pct=Decimal("10")))
    assert result.theoretical_litres == Decimal("3")
    assert result.paint.quantity.value == Decimal("3.3")
    assert result.paint.quantity.unit == "L"
    assert result.paint.material_key == "emulsion_paint"
    assert result.paint_waste.wastage_quantity == Decimal("0.3")
    assert result.overrides_used is True


def test_paint_verified_record_rate_usable(tmp_path):
    record = {
        "key": "paint_t", "activity": "Paint T", "material_key": "emulsion_paint",
        "coverage_per_unit": "12", "coverage_unit": "m2",
        "consumption_unit": "L",
        "source": "TEST FIXTURE ONLY", "version": "t",
        "effective_date": "2026-01-01",
        "verification_status": VerificationStatus.VERIFIED,
    }
    (tmp_path / "coverages.json").write_text(json.dumps({
        "schema_version": "0.1", "table_version": "t",
        "records": [record],
    }), encoding="utf-8")
    (tmp_path / "materials.json").write_text(json.dumps({
        "schema_version": "0.1", "table_version": "t", "records": [{
            "key": "emulsion_paint", "name": "Emulsion", "category": "finishes",
            "unit": "L", "density": None, "density_unit": "kg/m3",
            "default_wastage_pct": None, "source": "t", "version": "t",
            "effective_date": "2026-01-01",
            "verification_status": VerificationStatus.NEEDS_VERIFICATION,
        }],
    }), encoding="utf-8")
    from qs_engine.master_data.repository import MasterDataRepository as Repo
    repo = Repo(tmp_path)
    # Record rate 12 m2/L used; wastage still from explicit override.
    result = resolve_paint_materials(
        area_m2=Decimal("10"), coats=3, repository=repo,
        coverage_key="paint_t", paint_material_key="emulsion_paint",
        overrides=PaintOverride(wastage_pct=Decimal("10")))
    assert result.theoretical_litres == Decimal("2.5")
    assert result.paint.quantity.value == Decimal("2.75")
    assert result.overrides_used is False


def test_paint_unknown_keys_fail_closed():
    with pytest.raises(UnknownMasterDataKeyError):
        resolve_paint_materials(
            area_m2=Decimal("10"), coats=3, repository=shipped_repo(),
            coverage_key="paint_nope", paint_material_key="emulsion_paint",
            overrides=PaintOverride(coverage_m2_per_L=Decimal("10"),
                                    wastage_pct=Decimal("10")))


# --- tile consumables ------------------------------------------------------

def test_tile_consumables_unresolved_without_overrides():
    result = resolve_tile_consumables(
        net_area_m2=Decimal("20"), repository=shipped_repo(),
        adhesive_coverage_key="tile_adhesive_bedding",
        grout_coverage_key="tile_grout_jointing")
    assert isinstance(result, UnresolvedRequirement)
    assert any("adhesive_kg_per_m2" in note for note in result.missing)
    assert any("grout_kg_per_m2" in note for note in result.missing)
    assert any("wastage_pct" in note for note in result.missing)


def test_tile_consumables_resolved_exact():
    # 20 m2 x 3 kg/m2 = 60 -> 66; 20 x 0.5 = 10 -> 11 (10% waste).
    result = resolve_tile_consumables(
        net_area_m2=Decimal("20"), repository=shipped_repo(),
        adhesive_coverage_key="tile_adhesive_bedding",
        grout_coverage_key="tile_grout_jointing",
        overrides=TileConsumablesOverride(
            adhesive_kg_per_m2=Decimal("3"), grout_kg_per_m2=Decimal("0.5"),
            wastage_pct=Decimal("10")))
    assert result.adhesive.quantity.value == Decimal("66")
    assert result.adhesive.material_key == "tile_adhesive"
    assert result.grout.quantity.value == Decimal("11")
    assert result.grout.material_key == "tile_grout"
    assert result.overrides_used is True


# --- separation guarantees -------------------------------------------------

def test_wastage_rounding_separation_tiles():
    result = tile_takeoff(length=5, width=2, tile_length_mm=Decimal("500"),
                          tile_width_mm=Decimal("500"), joint_mm=Decimal("0"),
                          wastage_pct=Decimal("10"))
    assert result.wastage.rounding_applied is False
    assert result.wastage.quantity_after_wastage == Decimal("44")
    assert result.order_quantity == 44
    assert result.theoretical_count == Decimal("40")
