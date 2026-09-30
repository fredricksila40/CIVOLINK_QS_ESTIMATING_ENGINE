"""Phase 6 Option 1: IPC & Commercial Valuations Engine — tests.

Covers the multi-period model (ValuationManager / ValuationPeriod
state machine), the commercial deduction & tax calculator
(CommercialCalculator) and the export reconciliation / guard.
All arithmetic stays inside decimal.Decimal throughout.
"""

from decimal import Decimal

import pytest

from qs_engine.core.errors import ValidationError
from qs_engine.valuation.calculator import (
    AdvanceAmortizationSchedule,
    AdvanceRecoveryDetail,
    CommercialCalculator,
    CommercialValuation,
    RetentionDetail,
    TaxDetail,
)
from qs_engine.valuation.exporter import (
    build_reconciliation,
    ensure_export_allowed,
)
from qs_engine.valuation.models import (
    VALID_TRANSITIONS,
    ValuationManager,
    ValuationPeriod,
)


def _eval_detail(s):
    return eval(s, {"AdvanceRecoveryDetail": AdvanceRecoveryDetail,
                       "RetentionDetail": RetentionDetail,
                       "TaxDetail": TaxDetail,
                       "Decimal": Decimal})


# ------------------------------------------------------------------ #
# ValuationPeriod state machine
# ------------------------------------------------------------------ #

def test_valuation_period_create_and_cumulatives():
    p = ValuationPeriod.create(
        "V-001", "BOQ-01", 1,
        previous_qty="0", present_qty="100",
        previous_amount="0", present_amount="5000",
        onsite_materials="200")
    assert p.to_date_qty == Decimal("100")
    assert p.to_date_amount == Decimal("5000")
    assert p.previous_qty == Decimal("0")
    assert p.previous_amount == Decimal("0")
    assert p.onsite_materials == Decimal("200")
    assert p.state == "DRAFT"
    assert p.period_no == 1


def test_valuation_period_transition_approved():
    p = ValuationPeriod.create(
        "V-001", "BOQ-01", 1,
        previous_qty="0", present_qty="100",
        previous_amount="0", present_amount="5000")
    ap = p.transition_to("APPROVED")
    assert ap.state == "APPROVED"


def test_valuation_period_transition_draft_after_approved():
    p = ValuationPeriod.create(
        "V-001", "BOQ-01", 1,
        previous_qty="0", present_qty="100",
        previous_amount="0", present_amount="5000")
    ap = p.transition_to("APPROVED")
    back = ap.transition_to("DRAFT")
    assert back.state == "DRAFT"


def test_valuation_period_issued_locked():
    p = ValuationPeriod.create(
        "V-001", "BOQ-01", 1,
        previous_qty="0", present_qty="100",
        previous_amount="0", present_amount="5000")
    ap = p.transition_to("APPROVED")
    issued = ap.transition_to("ISSUED")
    assert issued.state == "ISSUED"
    with pytest.raises(ValidationError):
        issued.transition_to("DRAFT")
    with pytest.raises(ValidationError):
        issued.transition_to("APPROVED")


def test_valuation_period_invalid_transition_raises():
    p = ValuationPeriod.create(
        "V-001", "BOQ-01", 1,
        previous_qty="0", present_qty="100",
        previous_amount="0", present_amount="5000")
    with pytest.raises(ValidationError):
        p.transition_to("ISSUED")


def test_valuation_period_unknown_state_raises():
    with pytest.raises(ValidationError):
        ValuationPeriod.create(
            "V-001", "BOQ-01", 1,
            previous_qty="0", present_qty="100",
            previous_amount="0", present_amount="5000",
            state="UNKNOWN")


# ------------------------------------------------------------------ #
# ValuationManager
# ------------------------------------------------------------------ #

def test_valuation_manager_add_period_basic():
    m = ValuationManager()
    p1 = ValuationPeriod.create(
        "V-001", "BOQ-01", 1,
        previous_qty="0", present_qty="100",
        previous_amount="0", present_amount="5000")
    m.add_period(p1)
    cum = m.cumulative("BOQ-01")
    assert cum["to_date_qty"] == Decimal("100")
    assert cum["state"] == "DRAFT"
    assert cum["period_no"] == 1


def test_valuation_manager_previous_is_prior_cumulative():
    m = ValuationManager()
    p1 = ValuationPeriod.create(
        "V-001", "BOQ-01", 1,
        previous_qty="0", present_qty="100",
        previous_amount="0", present_amount="5000")
    m.add_period(p1)
    p2 = ValuationPeriod.create(
        "V-001", "BOQ-01", 2,
        previous_qty="100", present_qty="50",
        previous_amount="5000", present_amount="2500")
    added = m.add_period(p2)
    assert added.previous_qty == Decimal("100")
    assert added.previous_amount == Decimal("5000")
    assert m.cumulative("BOQ-01")["to_date_qty"] == Decimal("150")


def test_valuation_manager_previous_mismatch_raises():
    m = ValuationManager()
    p1 = ValuationPeriod.create(
        "V-001", "BOQ-01", 1,
        previous_qty="0", present_qty="100",
        previous_amount="0", present_amount="5000")
    m.add_period(p1)
    p2 = ValuationPeriod.create(
        "V-001", "BOQ-01", 2,
        previous_qty="0", present_qty="50",
        previous_amount="0", present_amount="2500")
    with pytest.raises(ValidationError):
        m.add_period(p2)


def test_valuation_manager_issued_locked():
    """Once a period is ISSUED, no further period may be added."""
    m = ValuationManager()
    p1 = ValuationPeriod.create(
        "V-001", "BOQ-01", 1,
        previous_qty="0", present_qty="100",
        previous_amount="0", present_amount="5000")
    m.add_period(p1)
    approved = p1.transition_to("APPROVED")
    m.add_period(approved)
    issued = approved.transition_to("ISSUED")
    m.add_period(issued)
    p2 = ValuationPeriod.create(
        "V-001", "BOQ-01", 2,
        previous_qty="100", present_qty="50",
        previous_amount="5000", present_amount="2500")
    with pytest.raises(ValidationError):
        m.add_period(p2)


def test_valuation_manager_cannot_add_after_issued():
    m = ValuationManager()
    p1 = ValuationPeriod.create(
        "V-001", "BOQ-01", 1,
        previous_qty="0", present_qty="100",
        previous_amount="0", present_amount="5000",
        state="ISSUED")
    m.add_period(p1)
    p2 = ValuationPeriod.create(
        "V-001", "BOQ-01", 2,
        previous_qty="100", present_qty="50",
        previous_amount="5000", present_amount="2500")
    with pytest.raises(ValidationError):
        m.add_period(p2)


def test_valuation_manager_approval_gate():
    m = ValuationManager()
    p1 = ValuationPeriod.create(
        "V-001", "BOQ-01", 1,
        previous_qty="0", present_qty="100",
        previous_amount="0", present_amount="5000")
    m.add_period(p1.transition_to("APPROVED"))
    p2 = ValuationPeriod.create(
        "V-001", "BOQ-01", 2,
        previous_qty="100", present_qty="50",
        previous_amount="5000", present_amount="2500")
    m.add_period(p2)
    assert m.cumulative("BOQ-01")["period_no"] == 2


def test_valuation_manager_boq_limit_guard():
    m = ValuationManager(boq_limits={"BOQ-01": Decimal("120")})
    p1 = ValuationPeriod.create(
        "V-001", "BOQ-01", 1,
        previous_qty="0", present_qty="100",
        previous_amount="0", present_amount="5000")
    m.add_period(p1)
    p2 = ValuationPeriod.create(
        "V-001", "BOQ-01", 2,
        previous_qty="100", present_qty="50",
        previous_amount="5000", present_amount="2500")
    with pytest.raises(ValidationError):
        m.add_period(p2)


def test_valuation_manager_vo_waiver():
    m = ValuationManager(boq_limits={"BOQ-01": Decimal("120")})
    p1 = ValuationPeriod.create(
        "V-001", "BOQ-01", 1,
        previous_qty="0", present_qty="100",
        previous_amount="0", present_amount="5000")
    m.add_period(p1)
    p2 = ValuationPeriod.create(
        "V-001", "BOQ-01", 2,
        previous_qty="100", present_qty="50",
        previous_amount="5000", present_amount="2500",
        vo_active=True)
    added = m.add_period(p2)
    assert added.vo_active is True
    assert m.cumulative("BOQ-01")["to_date_qty"] == Decimal("150")


def test_valuation_manager_all_cumulative():
    m = ValuationManager()
    p1 = ValuationPeriod.create(
        "V-001", "BOQ-01", 1,
        previous_qty="0", present_qty="100",
        previous_amount="0", present_amount="5000")
    m.add_period(p1)
    p2 = ValuationPeriod.create(
        "V-002", "BOQ-02", 1,
        previous_qty="0", present_qty="200",
        previous_amount="0", present_amount="8000")
    m.add_period(p2)
    all_c = m.all_cumulative()
    assert len(all_c) == 2
    assert all_c["BOQ-01"]["to_date_qty"] == Decimal("100")
    assert all_c["BOQ-02"]["to_date_qty"] == Decimal("200")


def test_valuation_manager_periods_list():
    m = ValuationManager()
    p1 = ValuationPeriod.create(
        "V-001", "BOQ-01", 1,
        previous_qty="0", present_qty="100",
        previous_amount="0", present_amount="5000")
    m.add_period(p1)
    assert len(m.periods("BOQ-01")) == 1
    assert m.periods("BOQ-99") == []


# ------------------------------------------------------------------ #
# CommercialCalculator
# ------------------------------------------------------------------ #

def test_commercial_calculator_retention_capped():
    # 5% of (1,000,000 work + 5,000 onsite) = 50,250 > 30,000 cap
    calc = CommercialCalculator(
        contract_sum="1000000", retention_rate_pct="5",
        retention_limit="30000")
    v = calc.compute(
        previous_valuation="0",
        items=[{"item_no": "1", "description": "Work",
                "unit": "m3", "rate": "100",
                "completed_qty": "10000"}],
        onsite_materials="5000", advance_repaid="0",
        valuation_no="V-001", period_no=1)
    assert v.retention_withheld == "30000"
    assert v.gross_certified == "1005000"


def test_commercial_calculator_net_payable():
    calc = CommercialCalculator(
        contract_sum="500000", retention_rate_pct="5",
        retention_limit="20000")
    v = calc.compute(
        previous_valuation="0",
        items=[{"item_no": "1", "description": "Work",
                "unit": "m3", "rate": "50",
                "completed_qty": "500"}],
        onsite_materials="0", advance_repaid="0",
        valuation_no="V-001", period_no=1)
    assert Decimal(v.net_payable) < Decimal(v.gross_certified)


def test_commercial_calculator_tax_withheld_reduces_net():
    calc = CommercialCalculator(
        contract_sum="500000", retention_rate_pct="5",
        retention_limit="20000", tax_rate_pct="10",
        tax_apply_on="net", tax_mode="withheld")
    v = calc.compute(
        previous_valuation="0",
        items=[{"item_no": "1", "description": "Work",
                "unit": "m3", "rate": "50",
                "completed_qty": "500"}],
        onsite_materials="0", advance_repaid="0",
        valuation_no="V-001", period_no=1)
    assert Decimal(v.tax_amount) > 0
    base_net = calc.calc.compute(
        previous_valuation="0",
        items=[{"item_no": "1", "description": "Work",
                "unit": "m3", "rate": "50",
                "completed_qty": "500"}],
        onsite_materials="0", advance_repaid="0",
        valuation_no="V-001").net_payable
    assert Decimal(v.net_payable) < Decimal(base_net)


def test_commercial_calculator_tax_added_not_deducted():
    calc = CommercialCalculator(
        contract_sum="500000", retention_rate_pct="5",
        retention_limit="20000", tax_rate_pct="10",
        tax_apply_on="net", tax_mode="added")
    v = calc.compute(
        previous_valuation="0",
        items=[{"item_no": "1", "description": "Work",
                "unit": "m3", "rate": "50",
                "completed_qty": "500"}],
        onsite_materials="0", advance_repaid="0",
        valuation_no="V-001", period_no=1)
    assert Decimal(v.tax_amount) > 0
    base_net = calc.calc.compute(
        previous_valuation="0",
        items=[{"item_no": "1", "description": "Work",
                "unit": "m3", "rate": "50",
                "completed_qty": "500"}],
        onsite_materials="0", advance_repaid="0",
        valuation_no="V-001").net_payable
    assert Decimal(v.net_payable) == Decimal(base_net)


def test_commercial_valuation_has_all_fields():
    calc = CommercialCalculator(
        contract_sum="500000", retention_rate_pct="5",
        retention_limit="20000", tax_rate_pct="12",
        tax_apply_on="gross", tax_mode="withheld")
    v = calc.compute(
        previous_valuation="0",
        items=[{"item_no": "1", "description": "Work",
                "unit": "m3", "rate": "50",
                "completed_qty": "500"}],
        onsite_materials="1000", advance_repaid="0",
        valuation_no="V-001", period_no=1)
    assert isinstance(v, CommercialValuation)
    for field in ("valuation_no", "contract_sum",
                  "work_to_date", "gross_certified",
                  "retention_withheld", "net_payable",
                  "advance_recovery_this_period",
                  "defects_release_amount", "tax_amount",
                  "tax_mode", "retention_detail",
                  "advance_detail", "tax_detail"):
        assert hasattr(v, field)
        assert getattr(v, field) != ""


def test_commercial_calculator_retention_detail():
    calc = CommercialCalculator(
        contract_sum="1000000", retention_rate_pct="5",
        retention_limit="40000", defects_release_pct="50")
    v = calc.compute(
        previous_valuation="0",
        items=[{"item_no": "1", "description": "Work",
                "unit": "m3", "rate": "100",
                "completed_qty": "1000"}],
        onsite_materials="0", advance_repaid="0",
        valuation_no="V-001", period_no=1)
    detail = _eval_detail(v.retention_detail)
    assert isinstance(detail, RetentionDetail)
    assert detail.rate_pct == Decimal("5")
    assert detail.held == detail.computed


def test_commercial_calculator_advance_amortization():
    # 3000 m3 at 100 = 300,000 = 30% of contract (> 20% threshold)
    calc = CommercialCalculator(
        contract_sum="1000000", retention_rate_pct="5",
        retention_limit="40000", advance_balance="100000",
        advance_amortize_at_pct="20")
    v = calc.compute(
        previous_valuation="0",
        items=[{"item_no": "1", "description": "Work",
                "unit": "m3", "rate": "100",
                "completed_qty": "3000"}],
        onsite_materials="0", advance_repaid="0",
        valuation_no="V-001", period_no=1)
    detail = _eval_detail(v.advance_detail)
    assert isinstance(detail, AdvanceRecoveryDetail)
    assert detail.cumulative_recovery == Decimal("100000")


def test_commercial_calculator_advance_repaid_exceeds_schedule():
    # certified (100000 = 10% of contract) is below the
    # 20% amortization threshold, so cumulative recovery is 0
    calc = CommercialCalculator(
        contract_sum="1000000", retention_rate_pct="5",
        retention_limit="40000", advance_balance="100000",
        advance_amortize_at_pct="20")
    with pytest.raises(ValidationError):
        calc.compute(
            previous_valuation="0",
            items=[{"item_no": "1", "description": "Work",
                    "unit": "m3", "rate": "100",
                    "completed_qty": "1000"}],
            onsite_materials="0", advance_repaid="50000",
            valuation_no="V-001", period_no=1)


def test_commercial_calculator_advance_recovery_after_threshold():
    calc = CommercialCalculator(
        contract_sum="1000000", retention_rate_pct="5",
        retention_limit="40000", advance_balance="100000",
        advance_amortize_at_pct="20")
    # certified to date = 30% of contract (> 20% threshold)
    v = calc.compute(
        previous_valuation="0",
        items=[{"item_no": "1", "description": "Work",
                "unit": "m3", "rate": "100",
                "completed_qty": "300000"}],
        onsite_materials="0", advance_repaid="0",
        valuation_no="V-001", period_no=1)
    detail = _eval_detail(v.advance_detail)
    # 30% certified > 20% threshold -> recovery = 100000 * 30/20 = 150000
    # capped at total_advance 100000
    assert detail.cumulative_recovery == Decimal("100000")


# ------------------------------------------------------------------ #
# AdvanceAmortizationSchedule (unit)
# ------------------------------------------------------------------ #

def test_advance_schedule_zero_advance():
    sched = AdvanceAmortizationSchedule(Decimal("0"), Decimal("20"))
    assert sched.recover(Decimal("50000"), Decimal("1000000")) == Decimal("0")


def test_advance_schedule_below_threshold():
    sched = AdvanceAmortizationSchedule(Decimal("100000"), Decimal("20"))
    assert sched.recover(Decimal("10000"), Decimal("100000")) == Decimal("0")


def test_advance_schedule_above_threshold():
    sched = AdvanceAmortizationSchedule(Decimal("100000"), Decimal("20"))
    result = sched.recover(Decimal("30000"), Decimal("100000"))
    # 30% certified > 20% threshold -> uncapped 150,000
    # but capped at the total advance of 100,000
    assert result == Decimal("100000")


# ------------------------------------------------------------------ #
# Export reconciliation + guard
# ------------------------------------------------------------------ #

def test_build_reconciliation_keys():
    calc = CommercialCalculator(
        contract_sum="500000", retention_rate_pct="5",
        retention_limit="20000", tax_rate_pct="12",
        tax_apply_on="gross", tax_mode="withheld")
    v = calc.compute(
        previous_valuation="0",
        items=[{"item_no": "1", "description": "Work",
                "unit": "m3", "rate": "50",
                "completed_qty": "500"}],
        onsite_materials="1000", advance_repaid="0",
        valuation_no="V-001", period_no=1)
    recon = build_reconciliation(v)
    for key in ("valuation_no", "contract_sum",
                "gross_certified", "retention_withheld",
                "net_payable", "work_to_date"):
        assert key in recon
    assert recon["valuation_no"] == "V-001"


def test_build_reconciliation_includes_lines():
    calc = CommercialCalculator(
        contract_sum="500000", retention_rate_pct="5",
        retention_limit="20000")
    v = calc.compute(
        previous_valuation="0",
        items=[{"item_no": "1", "description": "Work",
                "unit": "m3", "rate": "50",
                "completed_qty": "500"}],
        onsite_materials="0", advance_repaid="0",
        valuation_no="V-001", period_no=1)
    recon = build_reconciliation(v)
    assert recon["lines"] == []


def test_ensure_export_allowed_without_compile():
    class FakeSession:
        last_compiled = None
        boq_compiled = False
    class FakeApp:
        session = FakeSession()
    err = ensure_export_allowed(FakeApp())
    assert err is not None
    assert "BOQ" in err


def test_export_ipc_statement_excel_skips_guard_without_app():
    import csv, os, tempfile
    from qs_engine.valuation.calculator import (
        CommercialCalculator,
    )
    from qs_engine.valuation.exporter import (
        export_ipc_statement_excel)
    calc = CommercialCalculator(
        contract_sum="500000", retention_rate_pct="5",
        retention_limit="20000")
    v = calc.compute(
        previous_valuation="0",
        items=[{"item_no": "1", "description": "Work",
                "unit": "m3", "rate": "50",
                "completed_qty": "500"}],
        onsite_materials="0", advance_repaid="0",
        valuation_no="V-001", period_no=1)
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    try:
        # app=None skips the guard entirely
        export_ipc_statement_excel(v, {}, path, app=None)
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        assert any("valuation_no" in r for r in rows)
    finally:
        os.unlink(path)


def test_commercial_calculator_invalid_tax_rate():
    with pytest.raises(ValidationError):
        CommercialCalculator(
            contract_sum="500000", retention_rate_pct="5",
            retention_limit="20000", tax_rate_pct="200")


def test_commercial_calculator_invalid_amortize_pct():
    with pytest.raises(ValidationError):
        AdvanceAmortizationSchedule(Decimal("100000"), Decimal("150"))
