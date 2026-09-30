"""Commercial deduction & tax pipeline (Phase 6).

Composes the core IPC engine with configurable retention,
advance-amortization recovery and statutory tax (VAT /
withholding). Every input is coerced through
``decimal_policy``; no float may enter the chain. Money
outputs are rounded to 2dp only at the presentation boundary
via ``quantize_money``.
"""

from dataclasses import dataclass
from decimal import Decimal

from qs_engine.core.decimal_policy import (
    apply_percentage,
    quantize_money,
    to_decimal,
)
from qs_engine.core.errors import ValidationError
from qs_engine.valuation.ipc_engine import IPCCalculator


@dataclass(frozen=True)
class RetentionDetail:
    rate_pct: Decimal
    cap: Decimal
    computed: Decimal
    held: Decimal
    defects_release_pct: Decimal
    defects_release_amount: Decimal


@dataclass(frozen=True)
class AdvanceRecoveryDetail:
    total_advance: Decimal
    amortize_at_pct: Decimal
    certified_to_date_pct: Decimal
    cumulative_recovery: Decimal
    recovered_this_period: Decimal
    remaining: Decimal


@dataclass(frozen=True)
class TaxDetail:
    rate_pct: Decimal
    apply_on: str
    mode: str
    base: Decimal
    amount: Decimal


@dataclass(frozen=True)
class CommercialValuation:
    """Valuation enriched with commercial reconciliation.

    Carries every scalar field of the underlying IPCValuation
    so existing reports stay readable, plus the commercial
    schedule detail and the final net payable.
    """
    valuation_no: str
    contract_sum: str
    previous_valuation: str
    current_work: str
    work_to_date: str
    onsite_materials: str
    gross_certified: str
    retention_rate_pct: str
    retention_limit: str
    retention_withheld: str
    advance_repaid: str
    previous_payments: str
    total_deductions: str
    net_payable: str
    advance_recovery_this_period: str
    defects_release_amount: str
    tax_amount: str
    tax_mode: str
    retention_detail: str
    advance_detail: str
    tax_detail: str


class AdvanceAmortizationSchedule:
    """Amortized advance recovery keyed to certified work."""

    def __init__(self, total_advance: Decimal,
                 amortize_at_pct: Decimal):
        self.total_advance = to_decimal(total_advance,
                                        "total_advance")
        self.amortize_at_pct = to_decimal(amortize_at_pct,
                                           "amortize_at_pct")
        if self.amortize_at_pct < 0 or self.amortize_at_pct > 100:
            raise ValidationError(
                "amortize_at_pct must be within 0..100; "
                f"got {amortize_at_pct!r}")

    def recover(self, certified_to_date: Decimal,
                contract_sum: Decimal) -> Decimal:
        """Cumulative advance recoverable at this certified level.

        Recovery begins once certified work reaches
        ``amortize_at_pct`` of the contract sum and grows in
        proportion to certified work thereafter.
        """
        certified = to_decimal(certified_to_date,
                               "certified_to_date")
        contract = to_decimal(contract_sum, "contract_sum")
        if self.total_advance == 0 or contract == 0:
            return Decimal("0")
        certified_pct = (certified / contract) * 100
        if certified_pct <= self.amortize_at_pct:
            return Decimal("0")
        return min(self.total_advance,
                   self.total_advance * (certified_pct
                                         / self.amortize_at_pct))


class CommercialCalculator:
    """Contract-bound commercial computation.

    Core arithmetic (retention, advance repaid, previous
    payments, net) delegates to ``IPCCalculator``; this class
    layers the amortization schedule, defects-liability split
    and statutory tax on top.
    """

    def __init__(self, contract_sum, retention_rate_pct,
                 retention_limit, advance_balance="0",
                 previous_payments="0", advance_amortize_at_pct="0",
                 defects_release_pct="0",
                 tax_rate_pct="0", tax_apply_on="net",
                 tax_mode="withheld"):
        self.contract_sum = to_decimal(contract_sum,
                                       "contract_sum")
        self.calc = IPCCalculator(
            contract_sum, retention_rate_pct, retention_limit,
            advance_balance=advance_balance,
            previous_payments=previous_payments)
        self.advance_amortize_at_pct = to_decimal(
            advance_amortize_at_pct, "advance_amortize_at_pct")
        self.defects_release_pct = to_decimal(
            defects_release_pct, "defects_release_pct")
        self.tax_rate = to_decimal(tax_rate_pct, "tax_rate_pct")
        if self.tax_rate < 0 or self.tax_rate > 100:
            raise ValidationError(
                "tax_rate_pct must be within 0..100; "
                f"got {tax_rate_pct!r}")
        self.tax_apply_on = tax_apply_on
        self.tax_mode = tax_mode

    def compute(self, previous_valuation="0", items=(),
                onsite_materials="0", advance_repaid="0",
                valuation_no="", period_no=1,
                boq_limits=None, vo_active=False) -> CommercialValuation:
        """Value one commercial period (exact Decimal throughout)."""
        base = self.calc.compute(
            previous_valuation=previous_valuation, items=items,
            onsite_materials=onsite_materials,
            advance_repaid=advance_repaid,
            valuation_no=valuation_no)
        contract = self.contract_sum
        certified_to_date = to_decimal(base.gross_certified,
                                           "gross_certified")
        # ---- advance amortization schedule ----
        sched = AdvanceAmortizationSchedule(
            self.calc.advance_balance,
            self.advance_amortize_at_pct)
        cumulative_recovery = sched.recover(
            certified_to_date, contract)
        recovered_this_period = min(
            cumulative_recovery, self.calc.advance_balance)
        if (to_decimal(advance_repaid, "advance_repaid")
                > cumulative_recovery + Decimal("0.01")):
            raise ValidationError(
                f"advance_repaid ({advance_repaid}) exceeds the "
                f"amortization schedule "
                f"({cumulative_recovery})")
        # ---- retention detail with defects-liability split ----
        held = to_decimal(base.retention_withheld,
                           "retention_withheld")
        defects = min(held * self.defects_release_pct / 100, held)
        retention_detail = RetentionDetail(
            rate_pct=self.calc.retention_rate_pct,
            cap=self.calc.retention_limit,
            computed=min(
                apply_percentage(base.work_to_date,
                                 self.calc.retention_rate_pct),
                self.calc.retention_limit),
            held=held,
            defects_release_pct=self.defects_release_pct,
            defects_release_amount=defects)
        # ---- tax ----
        tax_base = (base.gross_certified if self.tax_apply_on == "gross"
                    else base.net_payable)
        tax = apply_percentage(tax_base, self.tax_rate)
        if self.tax_mode == "withheld":
            net_payable = to_decimal(base.net_payable) - tax
        else:
            net_payable = to_decimal(base.net_payable)
        # ---- assemble ----
        return CommercialValuation(
            valuation_no=base.valuation_no,
            contract_sum=base.contract_sum,
            previous_valuation=base.previous_valuation,
            current_work=base.current_work,
            work_to_date=base.work_to_date,
            onsite_materials=base.onsite_materials,
            gross_certified=base.gross_certified,
            retention_rate_pct=base.retention_rate_pct,
            retention_limit=base.retention_limit,
            retention_withheld=base.retention_withheld,
            advance_repaid=base.advance_repaid,
            previous_payments=base.previous_payments,
            total_deductions=base.total_deductions,
            net_payable=str(net_payable),
            advance_recovery_this_period=str(
                quantize_money(recovered_this_period)),
            defects_release_amount=str(quantize_money(defects)),
            tax_amount=str(quantize_money(tax)),
            tax_mode=self.tax_mode,
            retention_detail=str(retention_detail),
            advance_detail=str(AdvanceRecoveryDetail(
                total_advance=self.calc.advance_balance,
                amortize_at_pct=self.advance_amortize_at_pct,
                certified_to_date_pct=(
                    certified_to_date / contract * 100
                    if contract else Decimal("0")),
                cumulative_recovery=cumulative_recovery,
                recovered_this_period=recovered_this_period,
                remaining=self.calc.advance_balance
                           - cumulative_recovery)),
            tax_detail=str(TaxDetail(
                rate_pct=self.tax_rate, apply_on=self.tax_apply_on,
                mode=self.tax_mode, base=tax_base, amount=tax)),
        )
