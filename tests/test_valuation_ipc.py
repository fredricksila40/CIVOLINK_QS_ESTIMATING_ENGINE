"""Phase 19 IPC valuation + PDF export tests: headless, no widgets.

Covers the payment-certificate arithmetic (exact Decimal, retention
cap, advance guard, strict validation), both PDF builders (valid
headers, unresolved honesty, file helpers), the new controllers, and
the valuations page wiring. Engine parser/DTO/controller contracts
elsewhere are untouched.
"""

import inspect
import json
from decimal import Decimal

import pytest

from qs_engine.core.errors import ValidationError
from qs_engine.ui import controllers, views
from qs_engine.ui.session import TakeoffSession
from qs_engine.valuation.ipc_engine import IPCCalculator, compute_ipc


def _spec_valuation(**extra):
    params = {
        "contract_sum": "1000000",
        "retention_rate_pct": "10",
        "retention_limit": "50000",
        "previous_valuation": "100000",
        "items": [{"item_no": "1", "description": "Slab",
                   "unit": "m\u00b3", "rate": "100",
                   "completed_qty": "500"}],
        "onsite_materials": "10000",
        "advance_repaid": "20000",
        "advance_balance": "50000",
        "previous_payments": "90000",
        "valuation_no": "IPC-01",
    }
    params.update(extra)
    return compute_ipc(**params)


def _info(**extra):
    base = {"company_name": "Test Corp Ltd", "project_title": "Demo",
            "client": "ACME", "reference": "CTR-1",
            "measurement_standard": "CESMM4", "date": "2026-01-01"}
    base.update(extra)
    return base


def _compiled_fixture(priced=True):
    from qs_engine.boq.compiler import compile_boq
    from qs_engine.boq.models import (
        Boq,
        BoqItem,
        BoqSection,
        BoqSubsection,
        explicit_rate,
        unpriced_item,
    )
    pricing = (explicit_rate(Decimal("100"), "t") if priced
               else unpriced_item())
    boq = Boq(
        project_ref="P19", boq_ref="B19",
        sections=(
            BoqSection(code="C", title="Concrete", subsections=(
                BoqSubsection(code="C.1", title="In-situ", items=(
                    BoqItem(description="Slab", trade="Concrete",
                            unit="m\u00b3", quantity=Decimal("3"),
                            pricing=pricing),
                )),
            )),
        ))
    return compile_boq(boq)


# --- IPC arithmetic ------------------------------------------------------------------

def test_spec_scenario_exact_values():
    valuation = _spec_valuation()
    assert valuation.work_to_date == "150000"  # 100000 + 500x100
    assert valuation.gross_certified == "160000"  # + 10000 on-site
    assert valuation.retention_withheld == "15000"  # 10% uncapped here
    assert valuation.total_deductions == "125000"  # 15k + 20k + 90k
    assert valuation.net_payable == "35000"
    assert valuation.lines[0].line_value == "50000"
    assert valuation.valuation_no == "IPC-01"


def test_retention_cap_binds():
    valuation = _spec_valuation(previous_valuation="900000",
                                items=[{"item_no": "1",
                                        "description": "Slab",
                                        "unit": "m\u00b3", "rate": "100",
                                        "completed_qty": "2000"}])
    # 1,100,000 x 10% = 110,000 -> capped at 50,000.
    assert valuation.work_to_date == "1100000"
    assert valuation.retention_withheld == "50000"


def test_zero_retention_and_empty_lines():
    valuation = _spec_valuation(retention_rate_pct="0", items=[],
                                previous_valuation="0",
                                onsite_materials="0",
                                advance_repaid="0",
                                previous_payments="0")
    assert valuation.current_work == "0"
    assert valuation.retention_withheld == "0"
    assert valuation.net_payable == valuation.gross_certified == "0"
    assert valuation.lines == ()


def test_calculator_holds_contract_terms():
    calc = IPCCalculator("1000000", "10", "50000",
                         advance_balance="50000",
                         previous_payments="90000")
    first = calc.compute(previous_valuation="100000", items=[],
                         valuation_no="A")
    second = calc.compute(previous_valuation="200000", items=[],
                          valuation_no="B")
    assert first.previous_payments == second.previous_payments == "90000"
    assert first.valuation_no == "A" and second.valuation_no == "B"


def test_ipc_rejects_bad_inputs():
    with pytest.raises(ValidationError):
        compute_ipc("-1", "10", "50000")  # negative contract sum
    with pytest.raises(ValidationError):
        compute_ipc("1000", "101", "50000")  # rate above 100%
    with pytest.raises(ValidationError):
        compute_ipc("1000", "abc", "50000")  # non-numeric rate
    with pytest.raises(ValidationError):
        compute_ipc("1000", "10", "50000",
                    advance_repaid="60000",
                    advance_balance="50000")  # over-recovery
    with pytest.raises(ValidationError):
        compute_ipc("1000", "10", "50000", items=[
            {"item_no": "", "description": "x", "unit": "m",
             "rate": "1", "completed_qty": "1"}])
    with pytest.raises(ValidationError):
        compute_ipc("1000", "10", "50000", items=["not-a-mapping"])
    with pytest.raises(ValidationError):
        compute_ipc("1000", "10", "50000", items=[
            {"item_no": "1", "description": "x", "unit": "m",
             "rate": 1.5, "completed_qty": "1"}])  # float rejected


def test_ipc_dto_round_trips_json():
    data = json.loads(json.dumps(_spec_valuation().to_dict()))
    assert data["net_payable"] == "35000"
    assert Decimal(data["gross_certified"]) == Decimal("160000")
    assert data["lines"][0]["line_value"] == "50000"


# --- PDF builders --------------------------------------------------------------------------

def test_boq_summary_pdf_valid_and_honest(tmp_path):
    pytest.importorskip("reportlab")
    from qs_engine.export.pdf_exporter import (
        build_boq_summary_pdf,
        export_boq_summary_pdf,
    )
    payload = build_boq_summary_pdf(_compiled_fixture(), _info())
    assert payload[:5] == b"%PDF-"
    assert len(payload) > 1000
    # Unresolved totals never crash the renderer.
    payload_open = build_boq_summary_pdf(
        _compiled_fixture(priced=False), _info())
    assert payload_open[:5] == b"%PDF-"
    path = export_boq_summary_pdf(_compiled_fixture(), _info(),
                                  tmp_path / "boq.pdf")
    assert path.endswith(".pdf")
    with pytest.raises(ValidationError):
        build_boq_summary_pdf("not-a-boq", _info())


def test_ipc_statement_pdf_valid(tmp_path):
    pytest.importorskip("reportlab")
    from qs_engine.export.pdf_exporter import (
        build_ipc_pdf,
        export_ipc_statement_pdf,
    )
    payload = build_ipc_pdf(_spec_valuation(), _info())
    assert payload[:5] == b"%PDF-"
    assert len(payload) > 1000
    # Plain-dict valuations (API shape) render identically.
    assert build_ipc_pdf(
        _spec_valuation().to_dict(), _info())[:5] == b"%PDF-"
    path = export_ipc_statement_pdf(_spec_valuation(), _info(),
                                    tmp_path / "ipc.pdf")
    assert path.endswith(".pdf")
    with pytest.raises(ValidationError):
        build_ipc_pdf("not-a-valuation", _info())
    with pytest.raises(ValidationError):
        build_ipc_pdf({"valuation_no": "x"}, _info())


# --- controllers -------------------------------------------------------------------------------

def test_ipc_valuation_controller_success_and_failure():
    from qs_engine.valuation.ipc_engine import IPCValuation
    result = controllers.ipc_valuation_controller(
        "1000000", "10", "50000", previous_valuation="100000",
        items=[{"item_no": "1", "description": "Slab", "unit": "m\u00b3",
                "rate": "100", "completed_qty": "500"}],
        onsite_materials="10000", advance_repaid="20000",
        advance_balance="50000", previous_payments="90000",
        valuation_no="IPC-01")
    assert isinstance(result, IPCValuation)
    assert result.net_payable == "35000"
    bad = controllers.ipc_valuation_controller("-1", "10", "50000")
    assert type(bad).__name__ == "ErrorView"


def test_pdf_controllers_success_and_failure(tmp_path):
    from qs_engine.ui.viewmodels import ExportView
    boq_path = controllers.boq_pdf_controller(
        _compiled_fixture(), _info(), str(tmp_path / "boq.pdf"))
    assert isinstance(boq_path, ExportView)
    assert boq_path.path.endswith(".pdf")
    ipc_path = controllers.ipc_pdf_controller(
        _spec_valuation(), _info(), str(tmp_path / "ipc.pdf"))
    assert isinstance(ipc_path, ExportView)
    assert ipc_path.path.endswith(".pdf")
    bad = controllers.boq_pdf_controller(
        "not-a-boq", _info(), str(tmp_path / "x.pdf"))
    assert type(bad).__name__ == "ErrorView"


# --- session + UI wiring ----------------------------------------------------------------------------

def test_session_last_ipc_defaults_to_none():
    assert TakeoffSession().last_ipc is None


def test_valuations_page_wiring():
    assert views.PAGES["valuations"] is views.build_valuations_page
    kinds = {key: kind for _group, items in views.NAV_GROUPS
             for key, _label, kind in items}
    assert kinds["valuations"] == "page"
    source = inspect.getsource(views.build_valuations_page)
    assert "Compute Valuation" in source
    assert "Export BOQ Summary PDF" in source
    assert "Export IPC Statement PDF" in source
    assert "IPC_GRID_COLUMNS" in source
    assert set(dict(views.IPC_GRID_COLUMNS)) == {
        "item_no", "description", "unit", "rate", "completed_qty"}
