"""Unit-rate build-up tests (Phase 9).

Component prices/rates are ARBITRARY TEST VALUES passed explicitly —
never project data. No verified price library exists; the engine takes
prices per call and validates keys/ranges only.
"""

from decimal import Decimal

import pytest

from qs_engine.core.errors import (
    UnknownMasterDataKeyError,
    UnknownUnitError,
    ValidationError,
)
from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.rates.engine import (
    POLICY_PARALLEL,
    POLICY_SEQUENTIAL,
    composite_rate,
    get_rate_template,
    labour_component_direct,
    labour_component_from_requirement,
    logistics_component,
    material_component,
    other_component,
    plant_component_from_requirement,
    subcontract_component,
    template_is_priced,
)


def shipped_repo():
    return MasterDataRepository()


def full_buildup():
    """Direct 745.5/unit across all five cost families (test figures)."""
    repo = shipped_repo()
    material = material_component(
        material_key="portland_cement_42_5", qty_per_unit=Decimal("2"),
        unit_price=Decimal("100"), wastage_pct=Decimal("10"),
        repository=repo)
    assert material.cost_per_unit == Decimal("220")

    from qs_engine.labour.engine import (
        LabourTradeOverride,
        calculate_labour_requirement,
    )
    labour_req = calculate_labour_requirement(
        work_quantity=Decimal("100"), trade_key="mason", repository=repo,
        overrides=LabourTradeOverride(
            output_per_day=Decimal("25"), gang_skilled=2, gang_unskilled=4,
            skilled_rate=Decimal("1500"), unskilled_rate=Decimal("800")))
    labour = labour_component_from_requirement(labour_req, Decimal("100"))
    assert labour.cost_per_unit == Decimal("248")

    from qs_engine.plant.engine import (
        PlantOverride,
        calculate_plant_requirement,
    )
    plant_req = calculate_plant_requirement(
        work_quantity=Decimal("100"), equipment_key="backhoe_excavator",
        repository=repo,
        overrides=PlantOverride(output_per_unit=Decimal("20"),
                                rate=Decimal("24000")),
        hours_per_day=Decimal("8"))
    plant = plant_component_from_requirement(plant_req, Decimal("100"))
    assert plant.cost_per_unit == Decimal("150")

    logistics = logistics_component(
        total_haulage_cost=Decimal("7750"), work_quantity=Decimal("100"))
    assert logistics.cost_per_unit == Decimal("77.5")

    sub = subcontract_component(amount_per_unit=Decimal("50"),
                                description="test PC sum", provisional=True)
    assert sub.provisional is True
    return [material, labour, plant, logistics, sub]


# --- components ------------------------------------------------------------

def test_material_unknown_key_fails_closed():
    with pytest.raises(UnknownMasterDataKeyError):
        material_component(material_key="unobtainium",
                           qty_per_unit=Decimal("1"),
                           unit_price=Decimal("10"),
                           repository=shipped_repo())


def test_material_rejects_bad_inputs():
    repo = shipped_repo()
    with pytest.raises(ValidationError):
        material_component(material_key="river_sand",
                           qty_per_unit=Decimal("-1"),
                           unit_price=Decimal("10"), repository=repo)
    with pytest.raises(ValidationError):
        material_component(material_key="river_sand",
                           qty_per_unit=Decimal("1"),
                           unit_price=Decimal("-10"), repository=repo)
    with pytest.raises(Exception):
        material_component(material_key="river_sand",
                           qty_per_unit=Decimal("1"),
                           unit_price=Decimal("10"),
                           wastage_pct=Decimal("101"), repository=repo)


def test_labour_direct():
    line = labour_component_direct(hours_per_unit=Decimal("2"),
                                   rate_per_hour=Decimal("500"))
    assert line.cost_per_unit == Decimal("1000")
    assert line.kind == "labour"


def test_allocation_rejects_zero_quantity():
    from qs_engine.labour.engine import LabourTradeOverride
    from qs_engine.labour.engine import (
        calculate_labour_requirement as calc_labour)
    req = calc_labour(work_quantity=Decimal("100"), trade_key="mason",
                      repository=shipped_repo(),
                      overrides=LabourTradeOverride(
                          output_per_day=Decimal("25"), gang_skilled=2,
                          gang_unskilled=4, skilled_rate=Decimal("1500"),
                          unskilled_rate=Decimal("800")))
    with pytest.raises(ValidationError):
        labour_component_from_requirement(req, Decimal("0"))
    with pytest.raises(ValidationError):
        logistics_component(total_haulage_cost=Decimal("100"),
                            work_quantity=Decimal("0"))


def test_subcontract_requires_label():
    with pytest.raises(ValidationError):
        subcontract_component(amount_per_unit=Decimal("50"), description="  ")
    plain = other_component(amount_per_unit=Decimal("7"))
    assert plain.kind == "other"
    assert plain.provisional is False


# --- composite -------------------------------------------------------------

def test_composite_sequential_exact():
    # Direct 745.5; +10% -> 820.05 (+74.55); +5% -> 861.0525 (+41.0025).
    rate = composite_rate(
        components=full_buildup(),
        markups=[("site_overhead", Decimal("10")),
                 ("profit", Decimal("5"))],
        markup_policy=POLICY_SEQUENTIAL,
        element="test rate", work_unit="m²")
    assert rate.direct_cost_per_unit == Decimal("745.5")
    assert rate.net_rate == Decimal("745.5")
    assert rate.gross_rate == Decimal("861.0525")
    assert rate.markup_policy == POLICY_SEQUENTIAL
    assert rate.markups[0].amount == Decimal("74.55")
    assert rate.markups[0].running_total == Decimal("820.05")
    assert rate.markups[1].amount == Decimal("41.0025")
    assert rate.markups[1].running_total == Decimal("861.0525")
    assert rate.total_for(Decimal("10")) == Decimal("8610.525")


def test_composite_parallel_exact():
    # Both markups on direct: 745.5 x 0.15 = 111.825 -> 857.325.
    rate = composite_rate(
        components=full_buildup(),
        markups=[("site_overhead", Decimal("10")),
                 ("profit", Decimal("5"))],
        markup_policy=POLICY_PARALLEL, work_unit="m²")
    assert rate.gross_rate == Decimal("857.325")
    assert rate.markups[0].running_total == Decimal("820.05")
    assert rate.markups[1].running_total == Decimal("857.325")
    assert rate.net_rate == Decimal("745.5")


def test_composite_rejects_bad_inputs():
    with pytest.raises(ValidationError):
        composite_rate(components=[], markups=[], work_unit="m²")
    with pytest.raises(ValidationError):
        composite_rate(components=full_buildup(), markups=[],
                       markup_policy="compound", work_unit="m²")
    with pytest.raises(UnknownUnitError):
        composite_rate(components=full_buildup(), markups=[],
                       work_unit="furlong")
    with pytest.raises(ValidationError):
        composite_rate(components=full_buildup(),
                       markups=[("profit", Decimal("1500"))], work_unit="m²")
    with pytest.raises(ValidationError):
        composite_rate(components=full_buildup(), markups=[("x",)],
                       work_unit="m²")
    with pytest.raises(ValidationError):
        composite_rate(components=full_buildup(), markups=[("", Decimal("5"))],
                       work_unit="m²")
    with pytest.raises(ValidationError):
        composite_rate(components=["not-a-component"], markups=[],
                       work_unit="m²")


# --- templates -------------------------------------------------------------

def test_template_skeletons_structural_only():
    repo = shipped_repo()
    template = get_rate_template("concrete_placed_per_m3", repo)
    assert template.work_unit == "m3"
    assert len(template.components) == 4
    assert all(line.qty_per_unit is None for line in template.components)
    assert all(markup.pct is None for markup in template.markups)
    assert template.master_version == "9.0-skeleton"
    assert template_is_priced(template) is False
    blockwork = get_rate_template("blockwork_per_m2", repo)
    assert blockwork.work_unit == "m2"
    assert template_is_priced(blockwork) is False


def test_template_unknown_key_fails_closed():
    with pytest.raises(UnknownMasterDataKeyError):
        get_rate_template("paint_gold_leaf_per_m2", shipped_repo())
