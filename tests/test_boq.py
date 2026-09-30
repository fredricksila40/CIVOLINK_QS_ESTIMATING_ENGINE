"""BOQ compilation tests (Phase 10).

All quantities, rates, and sums are ARBITRARY TEST VALUES — never
project data. Money assertions are exact Decimal throughout.
"""

from decimal import Decimal

import pytest

from qs_engine.boq.compiler import compile_boq
from qs_engine.boq.measurement import (
    KNOWN_STANDARDS,
    MeasurementRule,
    MeasurementStandard,
    Rulebook,
)
from qs_engine.boq.models import (
    Boq,
    BoqItem,
    BoqSection,
    BoqSubsection,
    explicit_rate,
    priced_rate,
    provisional_sum,
    unpriced_item,
)
from qs_engine.contracts.models import Quantity, TakeoffResult
from qs_engine.core.assumptions import VerificationStatus
from qs_engine.core.errors import (
    UnknownMasterDataKeyError,
    UnknownUnitError,
    ValidationError,
)
from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.rates.engine import composite_rate, material_component


def repo():
    return MasterDataRepository()


def priced(description, qty, rate, **kwargs):
    fields = {"description": description, "trade": "Test Trade",
              "unit": "m³", "quantity": Decimal(str(qty)),
              "pricing": explicit_rate(Decimal(str(rate)), "test-ref")}
    fields.update(kwargs)
    return BoqItem(**fields)


def verified_rule():
    return MeasurementRule(
        standard=MeasurementStandard("CESMM", "4"), rule_ref="3.4",
        source="TEST FIXTURE ONLY",
        verification_status=VerificationStatus.VERIFIED)


def sample_boq():
    return Boq(
        project_ref="TEST-PROJ", boq_ref="TEST-BOQ",
        sections=(
            BoqSection(code="E", title="Earthworks", subsections=(
                BoqSubsection(code="E.1", title="Excavation", items=(
                    priced("Bulk excavation", 10, 100),
                    BoqItem(description="Provisional dewatering", trade="Test",
                            unit="sum", quantity=Decimal("1"),
                            pricing=provisional_sum(Decimal("500"), "pc-ref")),
                )),
            )),
            BoqSection(code="C", title="Concrete", subsections=(
                BoqSubsection(code="C.1", title="In-situ", items=(
                    priced("Blinding", 5, 200),
                    BoqItem(description="Awaiting rate", trade="Test",
                            unit="m³", quantity=Decimal("3"),
                            pricing=unpriced_item()),
                )),
            )),
        ))


# --- valid compilation -----------------------------------------------------

def test_valid_compilation_numbers_totals():
    compiled = compile_boq(sample_boq())
    assert [s.code for s in compiled.sections] == ["E", "C"]
    numbers = [i.item_no for s in compiled.sections for i in s.items]
    assert numbers == ["1.1.1", "1.1.2", "2.1.1", "2.1.2"]
    assert compiled.sections[0].items[0].amount == Decimal("1000")
    assert compiled.sections[0].items[1].amount == Decimal("500")
    assert compiled.sections[0].items[1].status == "provisional"
    assert compiled.sections[0].total == Decimal("1500")
    assert compiled.sections[1].items[1].status == "unpriced"
    assert compiled.sections[1].items[1].amount is None
    assert compiled.sections[1].total is None
    assert compiled.sections[1].resolved_subtotal == Decimal("1000")
    assert compiled.total is None
    assert compiled.resolved_subtotal == Decimal("2500")
    assert compiled.has_unresolved is True
    assert compiled.unresolved_items == ("2.1.2",)
    assert compiled.project_ref == "TEST-PROJ"


def test_fully_priced_grand_total():
    boq = Boq(project_ref="P", boq_ref="B", sections=(
        BoqSection.single("E", "Earthworks", (
            priced("Dig", 10, 100),
            priced("Fill", 5, 200),
        )),
    ))
    compiled = compile_boq(boq)
    assert compiled.total == Decimal("2000")
    assert compiled.has_unresolved is False
    assert compiled.unresolved_items == ()
    assert compiled.sections[0].items[0].item_no == "1.1.1"


def test_deterministic_input_order_preserved():
    boq = Boq(project_ref="P", boq_ref="B", sections=(
        BoqSection.single("Z", "Last trade", (priced("Z item", 1, 1),)),
        BoqSection.single("A", "First trade", (priced("A item", 1, 1),)),
    ))
    compiled = compile_boq(boq)
    assert [s.code for s in compiled.sections] == ["Z", "A"]
    assert compiled.sections[0].items[0].item_no == "1.1.1"


def test_explicit_numbering_and_duplicates():
    boq = Boq(project_ref="P", boq_ref="B", sections=(
        BoqSection.single("E", "Earthworks", (
            priced("Custom", 1, 1, item_no="E-001"),
            priced("Auto", 1, 1),
        )),
    ))
    compiled = compile_boq(boq)
    assert compiled.sections[0].items[0].item_no == "E-001"
    assert compiled.sections[0].items[1].item_no == "1.1.2"
    dup = Boq(project_ref="P", boq_ref="B", sections=(
        BoqSection.single("E", "Earthworks", (
            priced("One", 1, 1, item_no="E-001"),
            priced("Two", 1, 1, item_no="E-001"),
        )),
    ))
    with pytest.raises(ValidationError):
        compile_boq(dup)


# --- input validation ------------------------------------------------------

def test_missing_description_trade_unit_rejected():
    with pytest.raises(ValidationError):
        priced("", 1, 1)
    with pytest.raises(ValidationError):
        BoqItem(description="X", trade="  ", unit="m³",
                quantity=Decimal("1"), pricing=explicit_rate(Decimal("1")))
    with pytest.raises(UnknownUnitError):
        priced("X", 1, 1, unit="furlong")


def test_sum_unit_restricted_to_provisional():
    with pytest.raises(ValidationError):
        priced("X", 1, 1, unit="sum")


def test_negative_quantity_and_rate_rejected():
    with pytest.raises(ValidationError):
        priced("X", -1, 1)
    with pytest.raises(ValidationError):
        priced("X", 1, -1)


def test_zero_quantity_vs_zero_rate_vs_unpriced():
    boq = Boq(project_ref="P", boq_ref="B", sections=(
        BoqSection.single("E", "Earthworks", (
            priced("Zero qty", 0, 100),
            priced("Zero rate", 5, 0),
            BoqItem(description="No rate", trade="Test", unit="m³",
                    quantity=Decimal("3"), pricing=unpriced_item()),
        )),
    ))
    compiled = compile_boq(boq)
    zero_qty, zero_rate, no_rate = compiled.sections[0].items
    assert (zero_qty.amount, zero_qty.status) == (Decimal("0"), "priced")
    assert (zero_rate.amount, zero_rate.status) == (Decimal("0"), "priced")
    assert (no_rate.amount, no_rate.status) == (None, "unpriced")
    # "Priced at zero" and "not priced" stay formally distinct.
    assert zero_rate.amount == Decimal("0") and no_rate.amount is None


def test_decimal_exactness_no_rounding():
    boq = Boq(project_ref="P", boq_ref="B", sections=(
        BoqSection.single("E", "Earthworks", (
            priced("Exact", 3, Decimal("10.005")),
        )),
    ))
    compiled = compile_boq(boq)
    assert compiled.sections[0].items[0].amount == Decimal("30.015")
    assert compiled.total == Decimal("30.015")


def test_structure_validation():
    with pytest.raises(ValidationError):
        Boq(project_ref="", boq_ref="B", sections=(
            BoqSection.single("E", "E", (priced("X", 1, 1),)),))
    with pytest.raises(ValidationError):
        Boq(project_ref="P", boq_ref="B", sections=())
    with pytest.raises(ValidationError):
        BoqSection(code="E", title="E", subsections=())
    with pytest.raises(ValidationError):
        BoqSubsection(code="E.1", title="E", items=())
    with pytest.raises(ValidationError):
        compile_boq("not-a-boq")


# --- traceability ----------------------------------------------------------

def test_takeoff_and_rate_traceability():
    takeoff = TakeoffResult(
        element="slab S1", quantity=Quantity(Decimal("12"), "m³"),
        method="LxWxT", assumptions=("dims verified",))
    build = composite_rate(
        components=[material_component(
            material_key="river_sand", qty_per_unit=Decimal("1"),
            unit_price=Decimal("90"), repository=repo())],
        markups=[("profit", Decimal("10"))], work_unit="m³")
    assert build.gross_rate == Decimal("99")
    item = BoqItem(
        description="Concrete", trade="Concrete", unit="m³",
        quantity=Decimal("10"), pricing=priced_rate(build, "build-up-7"),
        takeoff=takeoff, takeoff_ref="slab S1 take-off",
        rate_result=build,
        measurement=verified_rule())
    compiled = compile_boq(Boq(
        project_ref="P", boq_ref="B",
        sections=(BoqSection.single("C", "Concrete", (item,)),)))
    line = compiled.sections[0].items[0]
    assert line.amount == Decimal("990")  # gross rate used, not direct
    assert line.takeoff_ref == "slab S1 take-off"
    assert line.rate_ref == "build-up-7"
    assert line.measurement_ref == "CESMM 4: 3.4"
    assert ("slab S1 take-off" in line.provenance
            and "build-up-7" in line.provenance
            and "CESMM 4: 3.4" in line.provenance)


def test_priced_item_requires_rate_result():
    build = composite_rate(
        components=[material_component(
            material_key="river_sand", qty_per_unit=Decimal("1"),
            unit_price=Decimal("90"), repository=repo())],
        work_unit="m³")
    with pytest.raises(ValidationError):
        BoqItem(description="X", trade="T", unit="m³",
                quantity=Decimal("1"),
                pricing=priced_rate(build))


# --- measurement -----------------------------------------------------------

def test_measurement_metadata_and_known_flag():
    assert MeasurementStandard("SMM").is_known is True
    assert MeasurementStandard("cesmm").is_known is True
    assert MeasurementStandard("POMI").is_known is False
    with pytest.raises(ValidationError):
        MeasurementStandard("  ")
    rule = verified_rule()
    assert rule.is_verified is True
    assert rule.citation == "CESMM 4: 3.4"
    bare = MeasurementRule(standard=MeasurementStandard("SMM"),
                           rule_ref="E.2.1")
    assert bare.is_verified is False
    with pytest.raises(ValidationError):
        MeasurementRule(standard=MeasurementStandard("SMM"), rule_ref="  ")
    with pytest.raises(ValidationError):
        MeasurementRule(standard="SMM", rule_ref="E.1")


def test_unresolved_rules_gating():
    item = priced("Measured work", 10, 100,
                  measurement=MeasurementRule(
                      standard=MeasurementStandard("CESMM"),
                      rule_ref="3.4"))  # NEEDS_VERIFICATION default
    boq = Boq(project_ref="P", boq_ref="B", sections=(
        BoqSection.single("E", "Earthworks", (item,)),))
    loose = compile_boq(boq, require_measurement_rules=False)
    assert loose.sections[0].items[0].status == "priced"
    assert loose.total == Decimal("1000")
    strict = compile_boq(boq, require_measurement_rules=True)
    line = strict.sections[0].items[0]
    assert line.status == "unresolved"
    assert line.amount == Decimal("1000")  # arithmetic stands...
    assert strict.total is None  # ...but totals exclude it
    assert strict.resolved_subtotal == Decimal("0")
    assert strict.unresolved_items == ("1.1.1",)
    verified = compile_boq(Boq(
        project_ref="P", boq_ref="B", sections=(
            BoqSection.single(
                "E", "Earthworks",
                (priced("Measured work", 10, 100,
                        measurement=verified_rule()),)),)),
        require_measurement_rules=True)
    assert verified.total == Decimal("1000")
    assert verified.has_unresolved is False


def test_rulebook_add_get_duplicates_missing():
    book = Rulebook()
    rule = verified_rule()
    assert book.add(rule) is rule
    assert book.get("CESMM 4: 3.4") is rule
    assert book.citations() == ["CESMM 4: 3.4"]
    with pytest.raises(ValidationError):
        book.add(rule)
    with pytest.raises(UnknownMasterDataKeyError):
        book.get("CESMM4: 9.9")
    with pytest.raises(ValidationError):
        book.add("not-a-rule")
