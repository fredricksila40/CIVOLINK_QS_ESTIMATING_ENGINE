"""Phase 1 tests: materials catalog identifiers, null-numeric rule, helper."""

import pytest

from qs_engine.contracts.models import master_record_from
from qs_engine.core.assumptions import VerificationStatus
from qs_engine.core.errors import MissingFieldError
from qs_engine.core.units import SUPPORTED_UNITS
from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.master_data.schemas import validate_record

EXPECTED_KEYS = {
    "portland_cement_42_5", "hydrated_lime",
    "river_sand", "quarry_dust", "ballast_20mm", "hardcore", "murram",
    "building_stone", "concrete_block_200mm", "concrete_block_150mm",
    "binding_wire", "wire_nails",
    "formwork_timber", "plywood_18mm",
    "emulsion_paint", "gloss_paint", "tile_adhesive", "tile_grout",
    "gypsum_plaster", "ceiling_board",
    "water", "polythene_sheeting", "release_agent",
}


def test_catalog_loads_with_expected_keys():
    repo = MasterDataRepository()
    keys = {r["key"] for r in repo.list("materials")}
    assert keys == EXPECTED_KEYS
    assert repo.table_version("materials") == "1.0-catalog"


def test_catalog_records_all_unverified_with_null_numerics():
    # Phase 1 gate: identifiers exist, but NO record may carry a usable
    # numeric until engineering verification happens.
    repo = MasterDataRepository()
    for record in repo.list("materials"):
        assert record["verification_status"] == VerificationStatus.NEEDS_VERIFICATION
        assert record["density"] is None, record["key"]
        assert record["default_wastage_pct"] is None, record["key"]


def test_catalog_units_are_core_supported():
    repo = MasterDataRepository()
    for record in repo.list("materials"):
        assert record["unit"] in SUPPORTED_UNITS, record["key"]


def test_get_material_by_key():
    repo = MasterDataRepository()
    cement = repo.get("materials", "portland_cement_42_5")
    assert cement["name"] == "Portland Cement 42.5"
    assert cement["category"] == "binder"
    assert repo.get("materials", "river_sand")["unit"] == "m\u00b3"
    assert repo.get("materials", "water")["unit"] == "L"


def test_null_numerics_accepted_only_when_unverified():
    base = {
        "key": "x", "name": "X", "category": "binder", "unit": "kg",
        "density": None, "density_unit": "kg/m\u00b3", "default_wastage_pct": None,
        "source": "test", "version": "t", "effective_date": "2026-01-01",
    }
    ok = dict(base, verification_status=VerificationStatus.NEEDS_VERIFICATION)
    assert validate_record("materials", ok)["key"] == "x"
    for status in (VerificationStatus.PROVISIONAL, VerificationStatus.VERIFIED):
        bad = dict(base, verification_status=status)
        with pytest.raises(MissingFieldError):
            validate_record("materials", bad)


def test_complete_unverified_record_still_accepted():
    repo_record = dict(repo_record_fixture())
    assert validate_record("materials", repo_record)["key"] == "cement_t"


def repo_record_fixture():
    return {
        "key": "cement_t", "name": "Cement T", "category": "binder",
        "unit": "bag", "density": "1440", "density_unit": "kg/m\u00b3",
        "default_wastage_pct": "5", "source": "test", "version": "t",
        "effective_date": "2026-01-01",
        "verification_status": VerificationStatus.NEEDS_VERIFICATION,
    }


def test_all_domains_populated_phase_8():
    # Phase 8 completes the skeleton set: every domain now carries
    # records (identifiers minimum; numerics verified or null).
    repo = MasterDataRepository()
    for domain in ("materials", "concrete_classes", "masonry_units",
                   "rebar_bars", "coverages", "soils",
                   "labour", "plant", "trucks", "rate_templates"):
        assert repo.list(domain) != [], domain


def test_rebar_nominal_diameters_present_mass_null():
    repo = MasterDataRepository()
    diameters = {r["key"]: r["diameter_mm"]
                 for r in repo.list("rebar_bars")}
    assert diameters == {"Y8": "8", "Y10": "10", "Y12": "12", "Y16": "16",
                         "Y20": "20", "Y25": "25", "Y32": "32"}
    for record in repo.list("rebar_bars"):
        assert record["mass_kg_per_m"] is None
        assert (record["verification_status"]
                == VerificationStatus.NEEDS_VERIFICATION)


def test_release_agent_skeletons_null():
    repo = MasterDataRepository()
    assert (repo.get("coverages", "formwork_release_agent")
            ["coverage_per_unit"] is None)
    assert repo.get("materials", "release_agent")["unit"] == "L"


def test_concrete_skeletons_all_unverified_null():
    repo = MasterDataRepository()
    skeletons = repo.list("concrete_classes")
    assert {r["key"] for r in skeletons} == {
        "class_c15", "class_c20", "class_c25", "class_c30"}
    for record in skeletons:
        assert record["verification_status"] == "NEEDS_VERIFICATION"
        for field in ("cement_ratio", "sand_ratio", "aggregate_ratio",
                      "dry_volume_factor", "wc_ratio",
                      "cement_density_kg_per_m3", "sand_density_kg_per_m3",
                      "aggregate_density_kg_per_m3", "water_density_kg_per_L",
                      "bag_mass_kg", "default_wastage_pct"):
            assert record[field] is None, (record["key"], field)


def test_master_record_from():
    repo = MasterDataRepository()
    record = repo.get("materials", "ballast_20mm")
    wrapped = master_record_from("materials", record)
    assert wrapped.domain == "materials"
    assert wrapped.key == "ballast_20mm"
    assert wrapped.attributes["name"] == "Coarse Aggregate / Ballast 20mm"
    assert wrapped.attributes["unit"] == "m\u00b3"
    assert wrapped.verification_status == VerificationStatus.NEEDS_VERIFICATION
    assert "key" not in wrapped.attributes
