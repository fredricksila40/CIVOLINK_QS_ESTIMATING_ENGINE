"""Contract model tests: distinct qty/rate/total, source tracking."""

from decimal import Decimal

import pytest

from qs_engine.contracts.models import (
    BOQ_SOURCE_CALCULATED,
    BOQItem,
    CostLine,
    MasterRecord,
    MaterialRequirement,
    Quantity,
    TakeoffResult,
)
from qs_engine.core.errors import UnknownUnitError, ValidationError
from qs_engine.core.rounding import apply_ceiling
from qs_engine.core.wastage import apply_wastage


def test_quantity_binds_value_to_supported_unit():
    q = Quantity(Decimal("2.5"), "m\u00b3")
    assert q.value == Decimal("2.5")
    with pytest.raises(UnknownUnitError):
        Quantity(Decimal("1"), "furlong")


def test_takeoff_result_is_geometry_only():
    r = TakeoffResult(element="slab", quantity=Quantity("12", "m\u00b3"),
                      method="LxWxT", assumptions=("dims-verified",))
    assert r.quantity.value == Decimal("12")
    # Geometry only: no cost/rate/material fields may exist on take-off output.
    assert not hasattr(r, "rate") and not hasattr(r, "material_key")


def test_material_requirement_stages():
    wasted = apply_wastage("100", "5")
    ordered = apply_ceiling(wasted.quantity_after_wastage, "piece")
    req = MaterialRequirement(material_key="block_9in", quantity=Quantity("105", "piece"),
                              wastage=wasted, ordering=ordered, master_version="t1")
    assert req.wastage.quantity_after_wastage == Decimal("105")
    assert req.ordering.ordering_quantity == 105
    assert req.ordering.calculated_quantity == Decimal("105")


def test_cost_line_keeps_components_distinct():
    line = CostLine(description="Test", quantity=Decimal("10"), unit="m\u00b2",
                    material_cost_per_unit=Decimal("100"),
                    labour_cost_per_unit=Decimal("40"),
                    plant_cost_per_unit=Decimal("10"),
                    overhead_per_unit=Decimal("15"),
                    profit_per_unit=Decimal("15"))
    assert line.direct_cost_per_unit == Decimal("150")
    assert line.selling_rate_per_unit == Decimal("180")
    assert line.total_amount == Decimal("1800")


def test_cost_line_rejects_negative_rate():
    with pytest.raises(Exception):
        CostLine(description="Bad", quantity=Decimal("1"), unit="m",
                 material_cost_per_unit=Decimal("-5"))


def test_boq_item_source_tracking():
    item = BOQItem(description="X", unit="m", quantity=Decimal("5"),
                   rate=Decimal("100"), amount=Decimal("500"))
    assert item.source == BOQ_SOURCE_CALCULATED
    manual = BOQItem(description="Y", unit="lot", quantity=Decimal("1"),
                     rate=Decimal("50"), amount=Decimal("50"), source="manual")
    assert manual.source == "manual"
    with pytest.raises(ValidationError):
        BOQItem(description="Z", unit="m", quantity=Decimal("1"),
                rate=Decimal("1"), amount=Decimal("1"), source="guess")


def test_master_record_carries_provenance():
    rec = MasterRecord(domain="materials", key="sand", source="QS-LEAD",
                       version="1", effective_date="2026-01-01",
                       verification_status="NEEDS_VERIFICATION")
    assert rec.verification_status == "NEEDS_VERIFICATION"
