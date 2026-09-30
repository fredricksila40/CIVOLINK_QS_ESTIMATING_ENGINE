"""Interim Payment Certificate valuation engine (Phase 19).

QS payment logic over caller-supplied period figures, in exact
Decimal throughout (no rounding inside the chain — presentation
formatting belongs to exporters):

- Work Completed to Date = Previous Valuation + Current Period Work
- Gross Certified        = Work Completed to Date + On-site Materials
- Retention Withheld     = min(Work to Date x Rate %, Retention Limit)
- Total Deductions       = Retention + Advance Repaid + Prev. Payments
- Net Amount Payable     = Gross Certified - Total Deductions

Unpriced/open leaves have no place here: every line carries an
explicit rate and completed quantity, and every money input must be
non-negative. Nothing is zero-filled silently — missing inputs raise
instead of defaulting.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Optional, Tuple

from qs_engine.core.decimal_policy import apply_percentage, to_decimal
from qs_engine.core.errors import ValidationError


@dataclass(frozen=True)
class IPCLine:
    """One valued line: rate x completed quantity, exact strings."""
    item_no: str
    description: str
    unit: str
    rate: str
    completed_qty: str
    line_value: str


@dataclass(frozen=True)
class IPCValuation:
    """A complete interim valuation DTO (amounts are exact strings)."""
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
    lines: Tuple[IPCLine, ...] = ()

    def to_dict(self) -> dict:
        """Plain-JSON dict (amounts already exact strings)."""
        import dataclasses

        def convert(value):
            if dataclasses.is_dataclass(value):
                return {f.name: convert(getattr(value, f.name))
                        for f in dataclasses.fields(value)}
            if isinstance(value, (tuple, list)):
                return [convert(v) for v in value]
            return value

        return convert(self)


def _money(value, field: str) -> Decimal:
    """Strict non-negative money parsing (no silent defaults)."""
    try:
        amount = to_decimal(value, field)
    except TypeError as exc:
        raise ValidationError(str(exc)) from exc
    if amount < 0:
        raise ValidationError(f"{field} must be >= 0; got {value!r}")
    return amount


def _text(value, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationError(f"{field} is required")
    return text


class IPCCalculator:
    """Contract-bound interim valuation computer.

    Contract parameters (fixed for the valuation run): contract sum,
    retention rate %, retention cap amount, outstanding advance
    balance, and cumulative previous payments. Period figures arrive
    per compute() call.
    """

    def __init__(self, contract_sum, retention_rate_pct,
                 retention_limit, advance_balance="0",
                 previous_payments="0"):
        self.contract_sum = _money(contract_sum, "contract_sum")
        try:
            rate = to_decimal(retention_rate_pct, "retention_rate_pct")
        except TypeError as exc:
            raise ValidationError(str(exc)) from exc
        if rate < 0 or rate > 100:
            raise ValidationError(
                "retention_rate_pct must be within 0..100; "
                f"got {retention_rate_pct!r}")
        self.retention_rate_pct = rate
        self.retention_limit = _money(retention_limit, "retention_limit")
        self.advance_balance = _money(advance_balance, "advance_balance")
        self.previous_payments = _money(
            previous_payments, "previous_payments")

    def compute(self, previous_valuation="0", items=(),
                onsite_materials="0", advance_repaid="0",
                valuation_no="") -> IPCValuation:
        """Value one interim period (exact Decimal, no rounding)."""
        previous = _money(previous_valuation, "previous_valuation")
        onsite = _money(onsite_materials, "onsite_materials")
        repaid = _money(advance_repaid, "advance_repaid")
        if repaid > self.advance_balance:
            raise ValidationError(
                f"advance_repaid ({repaid}) exceeds the outstanding "
                f"advance balance ({self.advance_balance})")
        lines: list[IPCLine] = []
        current = Decimal("0")
        for index, raw in enumerate(items or ()):
            if not isinstance(raw, Mapping):
                raise ValidationError(
                    f"Valuation line #{index} must be a mapping; "
                    f"got {type(raw).__name__}")
            rate = _money(raw.get("rate"), f"lines[{index}].rate")
            qty = _money(raw.get("completed_qty"),
                         f"lines[{index}].completed_qty")
            value = rate * qty
            current += value
            lines.append(IPCLine(
                item_no=_text(raw.get("item_no"),
                              f"lines[{index}].item_no"),
                description=_text(raw.get("description"),
                                  f"lines[{index}].description"),
                unit=_text(raw.get("unit"), f"lines[{index}].unit"),
                rate=str(rate),
                completed_qty=str(qty),
                line_value=str(value),
            ))
        work_to_date = previous + current
        gross = work_to_date + onsite
        retention = min(apply_percentage(work_to_date,
                                         self.retention_rate_pct),
                        self.retention_limit)
        deductions = retention + repaid + self.previous_payments
        net = gross - deductions
        return IPCValuation(
            valuation_no=str(valuation_no or "").strip(),
            contract_sum=str(self.contract_sum),
            previous_valuation=str(previous),
            current_work=str(current),
            work_to_date=str(work_to_date),
            onsite_materials=str(onsite),
            gross_certified=str(gross),
            retention_rate_pct=str(self.retention_rate_pct),
            retention_limit=str(self.retention_limit),
            retention_withheld=str(retention),
            advance_repaid=str(repaid),
            previous_payments=str(self.previous_payments),
            total_deductions=str(deductions),
            net_payable=str(net),
            lines=tuple(lines),
        )


def compute_ipc(contract_sum, retention_rate_pct, retention_limit,
                previous_valuation="0", items=(), onsite_materials="0",
                advance_repaid="0", advance_balance="0",
                previous_payments="0",
                valuation_no="") -> IPCValuation:
    """One-shot IPC valuation without holding a calculator."""
    return IPCCalculator(
        contract_sum, retention_rate_pct, retention_limit,
        advance_balance=advance_balance,
        previous_payments=previous_payments,
    ).compute(
        previous_valuation=previous_valuation, items=items,
        onsite_materials=onsite_materials, advance_repaid=advance_repaid,
        valuation_no=valuation_no)
