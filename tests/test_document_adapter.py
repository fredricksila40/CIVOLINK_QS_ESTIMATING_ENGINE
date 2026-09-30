"""Corporate document adapter tests (Phase 12).

Payloads are pure data: exact Decimal strings, verbatim statuses, null
unresolved totals. No rendering, no floats, no invented values.
"""

import json
from decimal import Decimal

import pytest

from qs_engine.adapters.document.payload import (
    OWNERSHIP_HEADER,
    DocumentPayload,
    ItemPayload,
    RateSheetPayload,
    synthesize_boq_payload,
    synthesize_rate_payload,
)
from qs_engine.boq.compiler import compile_boq
from qs_engine.boq.measurement import MeasurementRule, MeasurementStandard
from qs_engine.boq.models import (
    Boq,
    BoqItem,
    BoqSection,
    BoqSubsection,
    explicit_rate,
    provisional_sum,
    unpriced_item,
)
from qs_engine.core.assumptions import VerificationStatus
from qs_engine.core.errors import ValidationError
from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.rates.engine import (
    composite_rate,
    material_component,
    subcontract_component,
)


def repo():
    return MasterDataRepository()


def sample_compiled():
    boq = Boq(
        project_ref="TEST-PROJ", boq_ref="TEST-BOQ",
        sections=(
            BoqSection(code="E", title="Earthworks", subsections=(
                BoqSubsection(code="E.1", title="Excavation", items=(
                    BoqItem(description="Bulk excavation", trade="Earthworks",
                            unit="m³", quantity=Decimal("10"),
                            pricing=explicit_rate(Decimal("100"), "test"),
                            takeoff_ref="trench T1"),
                    BoqItem(description="Dewatering", trade="Earthworks",
                            unit="sum", quantity=Decimal("1"),
                            pricing=provisional_sum(Decimal("500"), "pc")),
                )),
            )),
            BoqSection(code="C", title="Concrete", subsections=(
                BoqSubsection(code="C.1", title="In-situ", items=(
                    BoqItem(description="Blinding", trade="Concrete",
                            unit="m³", quantity=Decimal("5"),
                            pricing=explicit_rate(Decimal("200"), "test"),
                            measurement=MeasurementRule(
                                standard=MeasurementStandard("CESMM", "4"),
                                rule_ref="3.4", source="TEST",
                                verification_status=(
                                    VerificationStatus.VERIFIED))),
                    BoqItem(description="Awaiting rate", trade="Concrete",
                            unit="m³", quantity=Decimal("3"),
                            pricing=unpriced_item()),
                )),
            )),
        ))
    return compile_boq(boq)


def sample_payload(**kwargs):
    params = {"document_title": "Tender BOQ Schedule",
              "purpose": "Tender submission",
              "compilation_id": "CMP-001",
              "document_date": "2026-09-22"}
    params.update(kwargs)
    return synthesize_boq_payload(sample_compiled(), **params)


def sample_rate():
    return composite_rate(
        components=[
            material_component(
                material_key="river_sand", qty_per_unit=Decimal("1"),
                unit_price=Decimal("90"), repository=repo()),
            subcontract_component(amount_per_unit=Decimal("50"),
                                  description="test PC", provisional=True),
        ],
        markups=[("profit", Decimal("10"))],
        element="test rate", work_unit="m³")


# --- BOQ mapping -----------------------------------------------------------

def test_boq_tree_mapping_accuracy():
    payload = sample_payload()
    assert payload.document_title == "Tender BOQ Schedule"
    assert payload.purpose == "Tender submission"
    assert payload.ownership == OWNERSHIP_HEADER
    assert payload.project_ref == "TEST-PROJ"
    assert payload.compilation_id == "CMP-001"
    assert [s.code for s in payload.sections] == ["E", "C"]
    first = payload.sections[0].items[0]
    assert isinstance(first, ItemPayload)
    assert first.item_no == "1.1.1"
    assert first.quantity == "10"
    assert first.rate == "100"
    assert first.amount == "1000"
    assert first.status == "priced"
    assert first.takeoff_ref == "trench T1"


def test_pricing_kind_flags_preserved():
    payload = sample_payload()
    statuses = [i.status for s in payload.sections for i in s.items]
    assert statuses == ["priced", "provisional", "priced", "unpriced"]
    provisional = payload.sections[0].items[1]
    assert provisional.unit == "sum"
    assert provisional.amount == "500"
    assert provisional.rate is None
    unpriced = payload.sections[1].items[1]
    assert unpriced.rate is None
    assert unpriced.amount is None


def test_unresolved_totals_explicit():
    payload = sample_payload()
    assert payload.sections[0].total == "1500"
    assert payload.sections[1].total is None
    assert payload.summary.grand_total is None
    assert payload.summary.resolved_subtotal == "2500"
    assert payload.summary.has_unresolved is True
    assert payload.summary.unresolved_items == ("2.1.2",)
    assert payload.summary.priced_count == 2
    assert payload.summary.provisional_count == 1
    assert payload.summary.unpriced_count == 1
    assert payload.summary.unresolved_count == 0


def test_measurement_standards_collected():
    payload = sample_payload()
    assert payload.measurement_standards == ("CESMM 4: 3.4",)
    assert "QS Engine = Source of Truth" in payload.governance


def test_json_round_trip_exact():
    payload = sample_payload()
    text = payload.to_json()
    data = json.loads(text)  # must serialize without custom encoders
    assert data["sections"][0]["items"][0]["amount"] == "1000"
    assert Decimal(data["sections"][0]["items"][0]["amount"]) == Decimal("1000")
    assert data["sections"][1]["items"][1]["amount"] is None
    assert data["summary"]["grand_total"] is None
    assert data["summary"]["unresolved_items"] == ["2.1.2"]


def test_invalid_inputs_rejected():
    with pytest.raises(ValidationError):
        synthesize_boq_payload("not-a-boq", document_title="T",
                               purpose="P")
    with pytest.raises(ValidationError):
        synthesize_boq_payload(sample_compiled(), document_title="  ",
                               purpose="P")
    with pytest.raises(ValidationError):
        synthesize_boq_payload(sample_compiled(), document_title="T",
                               purpose="")


# --- rate payload ----------------------------------------------------------

def test_rate_payload_mapping():
    # Direct 90 + 50 = 140; +10% -> 154.
    payload = synthesize_rate_payload(
        sample_rate(), document_title="Detailed Rate Build-Up Summary",
        purpose="Tender rate justification")
    assert isinstance(payload, RateSheetPayload)
    assert payload.ownership == OWNERSHIP_HEADER
    assert payload.element == "test rate"
    assert payload.work_unit == "m³"
    assert [c.kind for c in payload.components] == ["material",
                                                   "subcontract"]
    assert payload.components[0].cost_per_unit == "90"
    assert payload.components[1].provisional is True
    assert payload.direct_cost_per_unit == "140"
    assert payload.markups[0].amount == "14"
    assert payload.net_rate == "140"
    assert payload.gross_rate == "154"
    assert payload.markup_policy == "sequential"
    data = json.loads(payload.to_json())
    assert Decimal(data["gross_rate"]) == Decimal("154")


def test_rate_payload_rejects_bad_inputs():
    with pytest.raises(ValidationError):
        synthesize_rate_payload("not-a-rate", document_title="T",
                                purpose="P")
    with pytest.raises(ValidationError):
        synthesize_rate_payload(sample_rate(), document_title="T",
                                purpose=" ")
