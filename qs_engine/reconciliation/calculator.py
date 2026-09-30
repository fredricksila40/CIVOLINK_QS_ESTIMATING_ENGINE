"""Material consumption variance engine (Phase 6.2).

Compares theoretical QS allowances (net BOQ quantity grossed up by the
material's wastage factor) against actual site consumption (store issue
vouchers). Every quantity, rate, percentage and monetary value is an
exact ``decimal.Decimal`` — the precision guard in
``core.decimal_policy`` is applied at every boundary and no float
operation exists in this module.

Formulae (unrounded; rounding happens only at presentation)::

    Theoretical Allowance = Net BOQ Quantity x (1 + Wastage Factor)
    Actual Issued         = SUM(store issue vouchers)
    Variance              = Actual Issued - Theoretical Allowance
    Variance %            = Variance / Theoretical Allowance x 100
    Variance Value        = Variance Qty x Material Unit Rate
"""

from decimal import Decimal
from typing import Dict, Mapping, Optional, Tuple

from ..boq.models import CompiledBoq
from ..core.decimal_policy import to_decimal
from ..core.errors import ValidationError
from .models import (
    ISSUE,
    RECEIPT,
    STATUS_CRITICAL_OVERRUN,
    STATUS_NORMAL,
    STATUS_WARNING,
    WASTAGE_DISPOSAL,
    MaterialVarianceRow,
    StockTransaction,
    StoreReconciliationSummary,
)

#: Default overrun alert threshold (percent) and the multiplier that
#: escalates a WARNING into a CRITICAL_OVERRUN.
DEFAULT_WARNING_THRESHOLD_PCT = Decimal("5")
DEFAULT_CRITICAL_MULTIPLIER = Decimal("2")


def theoretical_allowance(net_qty, wastage_pct) -> Decimal:
    """Net BOQ quantity grossed up by the wastage factor, exactly.

    A null wastage factor (unverified master data) contributes nothing:
    the allowance is the net quantity and the caller records the factor
    as None — a wastage uplift is only ever applied from data that
    exists, never invented.
    """
    net = to_decimal(net_qty, "net_qty")
    if net < 0:
        raise ValidationError(
            f"Net BOQ quantity must be >= 0; got {net}")
    if wastage_pct is None:
        return net
    pct = to_decimal(wastage_pct, "wastage_pct")
    if pct < 0:
        raise ValidationError(
            f"Wastage factor must be >= 0; got {pct}")
    return net + (net * pct / Decimal(100))


def variance_pct(variance_qty, theoretical_qty) -> Optional[Decimal]:
    """Variance as an exact percentage of the theoretical allowance.

    None when the allowance is zero (the percentage is undefined); the
    caller decides the status from the absolute quantities instead.
    """
    variance = to_decimal(variance_qty, "variance_qty")
    theoretical = to_decimal(theoretical_qty, "theoretical_qty")
    if theoretical == 0:
        return None
    return (variance / theoretical) * Decimal(100)


def classify_status(variance_pct: Optional[Decimal], variance_qty,
                    warning_threshold_pct, critical_multiplier) -> str:
    """NORMAL / WARNING / CRITICAL_OVERRUN from the variance percentage.

    Only overruns escalate: a negative variance (under-consumption)
    stays NORMAL by design — the alert exists for site consumption
    exceeding the theoretical QS allowance. A zero allowance with any
    issue quantity is an overrun by definition.
    """
    threshold = to_decimal(warning_threshold_pct, "warning_threshold_pct")
    multiplier = to_decimal(critical_multiplier, "critical_multiplier")
    if variance_pct is None:
        return (STATUS_CRITICAL_OVERRUN
                if to_decimal(variance_qty, "variance_qty") > 0
                else STATUS_NORMAL)
    if variance_pct > threshold * multiplier:
        return STATUS_CRITICAL_OVERRUN
    if variance_pct > threshold:
        return STATUS_WARNING
    return STATUS_NORMAL


def boq_material_quantities(compiled_boq: CompiledBoq) -> Dict[str, Decimal]:
    """Aggregate net BOQ quantity per material reference (exact).

    Items carry their material reference as ``rate_ref``; items without
    one are skipped (labour/plant/subcontract lines are not materials).
    """
    totals: Dict[str, Decimal] = {}
    if compiled_boq is None:
        return totals
    for section in compiled_boq.sections:
        for item in section.items:
            ref = str(item.rate_ref or "").strip()
            if not ref:
                continue
            totals[ref] = totals.get(ref, Decimal("0")) + item.quantity
    return totals


def boq_material_rates(compiled_boq: CompiledBoq) -> Dict[str, Decimal]:
    """Effective unit rate per material reference from priced BOQ items.

    Rate = SUM(amount) / SUM(quantity) over priced/provisional items —
    the same money-per-quantity the BOQ actually carries. Materials with
    no priced items have no entry: no rate is ever invented.
    """
    amounts: Dict[str, Decimal] = {}
    quantities: Dict[str, Decimal] = {}
    if compiled_boq is None:
        return {}
    for section in compiled_boq.sections:
        for item in section.items:
            ref = str(item.rate_ref or "").strip()
            if not ref or item.amount is None:
                continue
            amounts[ref] = amounts.get(ref, Decimal("0")) + item.amount
            quantities[ref] = (quantities.get(ref, Decimal("0"))
                               + item.quantity)
    rates: Dict[str, Decimal] = {}
    for ref, amount in amounts.items():
        qty = quantities.get(ref, Decimal("0"))
        if qty > 0:
            rates[ref] = amount / qty
    return rates


def _site_totals(transactions) -> Dict[str, Decimal]:
    """Exact receipt / issue / disposal totals per resolved material."""
    receipts: Dict[str, Decimal] = {}
    issues: Dict[str, Decimal] = {}
    disposals: Dict[str, Decimal] = {}
    for txn in transactions:
        key = txn.resolved_key
        if not key:
            continue
        bucket = {RECEIPT: receipts, ISSUE: issues,
                  WASTAGE_DISPOSAL: disposals}.get(txn.transaction_type)
        if bucket is not None:
            bucket[key] = bucket.get(key, Decimal("0")) + txn.quantity
    return {"receipts": receipts, "issues": issues, "disposals": disposals}


def _record_facts(resolver, key) -> Tuple[str, str, str, Optional[Decimal]]:
    """(code, name, unit, wastage_pct) for one master-data key.

    Falls back to (key, "", "", None) when the key cannot be resolved —
    facts are only ever read, never fabricated.
    """
    if resolver is not None:
        try:
            record = resolver.get("materials", key)
        except Exception:
            record = None
        if record is not None:
            wastage = record.get("default_wastage_pct")
            return (str(record.get("code", "") or key),
                    str(record.get("name", "") or ""),
                    str(record.get("unit", "") or ""),
                    (to_decimal(wastage, "wastage_pct")
                     if wastage is not None else None))
    return (key, "", "", None)


def reconcile(compiled_boq: Optional[CompiledBoq],
              transactions,
              resolver=None,
              unit_rates: Optional[Mapping[str, object]] = None,
              warning_threshold_pct=DEFAULT_WARNING_THRESHOLD_PCT,
              critical_multiplier=DEFAULT_CRITICAL_MULTIPLIER
              ) -> StoreReconciliationSummary:
    """Build the full reconciliation summary (exact Decimal arithmetic).

    ``unit_rates`` maps a material key to a Decimal/int/str rate; when
    omitted the BOQ's effective rate per material is used. Monetary
    totals are None unless every tracked material has a rate — a budget
    value is only stated when it can be stated completely.
    """
    threshold = to_decimal(warning_threshold_pct, "warning_threshold_pct")
    multiplier = to_decimal(critical_multiplier, "critical_multiplier")
    if threshold < 0 or multiplier <= 0:
        raise ValidationError(
            "warning_threshold_pct must be >= 0 and critical_multiplier > 0")

    theoretical = boq_material_quantities(compiled_boq)
    effective_rates = boq_material_rates(compiled_boq)
    site = _site_totals(transactions)
    issues = site["issues"]
    disposals = site["disposals"]
    receipts = site["receipts"]

    # Materials tracked on site: any resolved material with activity.
    tracked = set(issues) | set(receipts) | set(disposals)
    # Materials with a theoretical allowance but no site activity still
    # reconcile (variance = -theoretical) and stay visible.
    tracked |= set(theoretical)

    supplied_rates: Dict[str, Decimal] = {}
    if unit_rates:
        for key, rate in unit_rates.items():
            supplied_rates[str(key)] = to_decimal(rate, f"rate[{key}]")

    rows = []
    for key in sorted(tracked):
        net_qty = theoretical.get(key, Decimal("0"))
        code, name, unit, wastage = _record_facts(resolver, key)
        allowance = theoretical_allowance(net_qty, wastage)
        issued = issues.get(key, Decimal("0"))
        balance = (receipts.get(key, Decimal("0")) - issued
                   - disposals.get(key, Decimal("0")))
        variance = issued - allowance
        pct = variance_pct(variance, allowance)
        rate = supplied_rates.get(key, effective_rates.get(key))
        value = (variance * rate) if rate is not None else None
        rows.append(MaterialVarianceRow(
            material_key=key,
            code=code or key,
            name=name or key,
            unit=unit,
            theoretical_qty=allowance,
            actual_issued=issued,
            store_balance=balance,
            variance_qty=variance,
            variance_pct=pct,
            variance_value=value,
            unit_rate=rate,
            status=classify_status(pct, variance, threshold, multiplier),
            wastage_pct=wastage,
        ))

    unresolved = tuple(sorted({
        txn.material_ref for txn in transactions if not txn.resolved_key}))

    all_rated = all(row.unit_rate is not None for row in rows)
    if rows and all_rated:
        theoretical_value = sum((row.theoretical_qty * row.unit_rate
                                 for row in rows), Decimal("0"))
        actual_value = sum((row.actual_issued * row.unit_rate
                            for row in rows), Decimal("0"))
        overall_variance = sum((row.variance_qty * row.unit_rate
                                for row in rows), Decimal("0"))
    else:
        theoretical_value = actual_value = overall_variance = None

    return StoreReconciliationSummary(
        rows=tuple(rows),
        unresolved=unresolved,
        total_materials_tracked=len(rows),
        theoretical_budget_value=theoretical_value,
        actual_issued_value=actual_value,
        overall_variance_value=overall_variance,
        warning_threshold_pct=threshold,
        critical_multiplier=multiplier,
        transactions=tuple(transactions),
    )
