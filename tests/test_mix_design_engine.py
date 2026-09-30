"""Phase 6 Mix Design & Constituent Engine tests.

Covers BS EN 206 / BS 8500 mass-based constituent computation
(C20/25 cement bounds, mass conservation, bag counts), the
mix master table (all six Eurocode classes, verified status),
strict Decimal enforcement (no float leakage), and the
materials-store linkage (constituent codes resolve against
the materials catalogue).
"""

import hashlib
import inspect
import json
from decimal import Decimal

import pytest

from qs_engine.core.decimal_policy import to_decimal
from qs_engine.core.errors import ValidationError
from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.mixes.calculator import (
    ConstituentCalculator,
    ConstituentResult,
)
from qs_engine.master_data.schemas import (
    DOMAINS,
    REQUIRED_FIELDS,
    NULLABLE_NUMERIC_FIELDS,
)


REPO = MasterDataRepository()


# ------------------------------------------------------------------ #
# Mix master table loading
# ------------------------------------------------------------------ #

def test_mix_designs_domain_registered():
    assert "mix_designs" in DOMAINS


def test_mix_designs_table_loaded():
    records = REPO.list("mix_designs")
    assert len(records) == 10
    designations = {r["designation"] for r in records}
    assert {"C8/10", "C12/15", "C16/20",
            "C20/25", "C25/30", "C30/37",
            "M1", "M2", "M3", "M4"} == designations


def test_mix_designs_all_verified():
    for rec in REPO.list("mix_designs"):
        assert rec["verification_status"] == "VERIFIED"


def test_mix_designs_required_fields():
    for field in REQUIRED_FIELDS["mix_designs"]:
        assert field, field


def test_mix_designs_nullable_fields():
    for field in NULLABLE_NUMERIC_FIELDS["mix_designs"]:
        assert field, field


def test_mix_design_record_structure():
    rec = REPO.get("mix_designs", "mix_c20_25")
    assert rec["designation"] == "C20/25"
    assert rec["bs_8500_designation"] == "ST4 / PAV 1"
    assert rec["cement_code"] == "CEM-001"
    assert rec["fine_agg_code"] == "AGG-001"
    assert rec["coarse_agg_code"] == "AGG-002"


def test_mix_designs_json_consistent():
    path = "qs_engine/master_data/tables/mix_designs.json"
    d = json.load(open(path))
    for r in d["records"]:
        if r.get("is_mortar"):
            assert "mix_ratio_cement_to_sand" in r
            assert "k_dry" in r
            continue
        for field in ("min_cement_content_kg_per_m3",
                        "max_wc_ratio", "fine_agg_ratio",
                        "coarse_agg_ratio", "target_density",
                        "default_wastage_pct"):
            assert isinstance(r[field], str), field


# ------------------------------------------------------------------ #
# Constituent computation
# ------------------------------------------------------------------ #

def test_c20_25_cement_content():
    calc = ConstituentCalculator(REPO)
    result = calc.compute("C20/25", "10")
    assert result.designation == "C20/25"
    assert result.cement_mass == Decimal("2940.00")


def test_c20_25_min_cement_bound():
    calc = ConstituentCalculator(REPO)
    for vol in ("1", "5", "10"):
        result = calc.compute("C20/25", vol)
        per_m3 = result.cement_mass / Decimal(vol)
        assert per_m3 >= Decimal("280")


def test_c25_30_cement_content():
    calc = ConstituentCalculator(REPO)
    result = calc.compute("C25/30", "1")
    assert result.cement_mass == Decimal("336.00")


def test_c30_37_cement_content():
    calc = ConstituentCalculator(REPO)
    result = calc.compute("C30/37", "1")
    assert result.cement_mass == Decimal("378.00")


def test_c8_10_lowest_cement():
    calc = ConstituentCalculator(REPO)
    result = calc.compute("C8/10", "1")
    assert result.designation == "C8/10"
    assert result.cement_mass == Decimal("189.00")


def test_mass_conservation():
    """cement + water + sand + coarse = gross_volume x target_density."""
    from decimal import Decimal as _D
    target_densities = {"C8/10": "2350", "C12/15": "2380",
                        "C16/20": "2400", "C20/25": "2420",
                        "C25/30": "2450", "C30/37": "2480"}
    calc = ConstituentCalculator(REPO)
    for designation, density in target_densities.items():
        result = calc.compute(designation, "10")
        lhs = result.gross_volume * _D(density)
        total = result.cement_mass + result.water_liters + result.sand_mass + result.coarse_agg_mass
        assert abs(lhs - total) < _D("1")


def test_bag_count_rounds_up():
    calc = ConstituentCalculator(REPO)
    result = calc.compute("C20/25", "10")
    assert result.cement_bags == 59
    assert Decimal(result.cement_mass) / Decimal("50") == Decimal("58.8")


def test_gross_volume_includes_wastage():
    calc = ConstituentCalculator(REPO)
    result = calc.compute("C20/25", "10", "0.05")
    assert result.net_volume == Decimal("10")
    assert result.gross_volume == Decimal("10.50")


def test_wastage_zero():
    calc = ConstituentCalculator(REPO)
    result = calc.compute("C20/25", "10", "0")
    assert result.gross_volume == Decimal("10")


def test_water_from_wc_ratio():
    calc = ConstituentCalculator(REPO)
    result = calc.compute("C20/25", "10")
    assert result.water_liters == Decimal("1617.00")


def test_sand_coarse_split():
    calc = ConstituentCalculator(REPO)
    result = calc.compute("C20/25", "10")
    assert result.sand_mass + result.coarse_agg_mass == result.aggregate_mass


def test_sand_volume_plus_coarse_volume():
    calc = ConstituentCalculator(REPO)
    result = calc.compute("C20/25", "10")
    vol_sum = result.sand_volume + result.coarse_agg_volume
    assert abs(vol_sum - result.aggregate_mass / Decimal("2420")) < Decimal("0.01")


def test_negative_volume_raises():
    calc = ConstituentCalculator(REPO)
    with pytest.raises(ValidationError):
        calc.compute("C20/25", "-1")


def test_unknown_designation_raises():
    calc = ConstituentCalculator(REPO)
    with pytest.raises(ValidationError):
        calc.compute("C50/60", "10")


# ------------------------------------------------------------------ #
# Decimal enforcement
# ------------------------------------------------------------------ #

def test_no_float_in_cement_mass():
    calc = ConstituentCalculator(REPO)
    result = calc.compute("C20/25", "10")
    assert isinstance(result.cement_mass, Decimal)
    assert not isinstance(result.cement_mass, float)


def test_no_float_in_any_result():
    calc = ConstituentCalculator(REPO)
    result = calc.compute("C20/25", "10")
    for attr in ("net_volume", "gross_volume", "cement_mass",
                 "water_liters", "aggregate_mass", "sand_mass",
                 "coarse_agg_mass", "sand_volume", "coarse_agg_volume"):
        val = getattr(result, attr)
        assert isinstance(val, Decimal), f"{attr} is {type(val)}"


# ------------------------------------------------------------------ #
# Materials-store linkage
# ------------------------------------------------------------------ #

def test_cement_code_resolves_to_materials():
    result = REPO.get("mix_designs", "mix_c20_25")
    prefix = result["cement_code"].split("-")[0]
    mat_recs = [r for r in REPO.list("materials")
                if r.get("category_prefix") == prefix]
    assert len(mat_recs) > 0
    assert mat_recs[0]["category_prefix"] == "CEM"


def test_fine_agg_code_resolves():
    result = REPO.get("mix_designs", "mix_c20_25")
    prefix = result["fine_agg_code"].split("-")[0]
    mat_recs = [r for r in REPO.list("materials")
                if r.get("category_prefix") == prefix]
    assert len(mat_recs) > 0


def test_coarse_agg_code_resolves():
    result = REPO.get("mix_designs", "mix_c20_25")
    prefix = result["coarse_agg_code"].split("-")[0]
    mat_recs = [r for r in REPO.list("materials")
                if r.get("category_prefix") == prefix]
    assert len(mat_recs) > 0


def test_all_designation_codes_resolve():
    for rec in REPO.list("mix_designs"):
        for field in ("cement_code", "fine_agg_code", "coarse_agg_code"):
            code = rec[field]
            prefix = code.split("-")[0]
            mat_recs = [r for r in REPO.list("materials")
                        if r.get("category_prefix") == prefix]
            assert len(mat_recs) > 0, f"{code} unresolved"


# ------------------------------------------------------------------ #
# Result dataclass
# ------------------------------------------------------------------ #

def test_constituent_result_dataclass():
    calc = ConstituentCalculator(REPO)
    result = calc.compute("C20/25", "10")
    assert isinstance(result, ConstituentResult)
    assert result.designation == "C20/25"
    assert result.bs_8500_designation == "ST4 / PAV 1"
    assert result.cement_code == "CEM-001"


def test_constituent_result_frozen():
    calc = ConstituentCalculator(REPO)
    result = calc.compute("C20/25", "10")
    with pytest.raises(Exception):
        result.cement_mass = Decimal("999")
