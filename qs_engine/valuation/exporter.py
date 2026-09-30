"""IPC statement export & commercial reconciliation (Phase 6).

Produces a full contract-reconciliation statement (Excel-compatible
CSV plus the existing PDF) and enforces the BOQ-compilation guard
established in Phase 4 (plus the licensing gate) before any
commercial document leaves the machine.
"""

import csv
from decimal import Decimal
from typing import Mapping

from qs_engine.core.decimal_policy import to_decimal
from qs_engine.core.errors import ValidationError
from qs_engine.valuation.calculator import (
    CommercialValuation,
)
from qs_engine.valuation.ipc_engine import IPCValuation


def build_reconciliation(valuation) -> dict:
    """Full contract reconciliation breakdown from a valuation.

    Accepts either ``IPCValuation`` or ``CommercialValuation``
    (via duck-typing of the scalar fields).
    """
    def money(name: str) -> Decimal:
        return to_decimal(getattr(valuation, name), name)
    gross = money("gross_certified")
    retention = money("retention_withheld")
    advance = money("advance_repaid")
    prev_payments = money("previous_payments")
    net = money("net_payable")
    contract = money("contract_sum")
    return {
        "valuation_no": getattr(valuation, "valuation_no", ""),
        "contract_sum": str(contract),
        "gross_certified": str(gross),
        "retention_withheld": str(retention),
        "advance_repaid": str(advance),
        "previous_payments": str(prev_payments),
        "total_deductions": str(money("total_deductions")),
        "net_payable": str(net),
        "work_to_date": str(money("work_to_date")),
        "onsite_materials": str(money("onsite_materials")),
        "retention_rate_pct": str(money("retention_rate_pct")),
        "retention_limit": str(money("retention_limit")),
        "advance_recovery_this_period": str(
            money("advance_recovery_this_period")),
        "defects_release_amount": str(
            money("defects_release_amount")),
        "tax_amount": str(money("tax_amount")),
        "tax_mode": getattr(valuation, "tax_mode", ""),
        "lines": [
            {"item_no": l.item_no, "description": l.description,
             "unit": l.unit, "rate": l.rate,
             "completed_qty": l.completed_qty,
             "line_value": l.line_value}
            for l in getattr(valuation, "lines", ())],
    }


def ensure_export_allowed(app) -> str | None:
    """Return an error string when commercial export is not allowed.

    Enforces both the BOQ-compilation guard and the licensing gate
    (Phase 4 commercial guard sync). None means entitled.
    """
    compiled = getattr(app.session, "last_compiled", None)
    if compiled is None:
        return ("Compile the BOQ first (BOQ View)")
    from qs_engine.ui.views import _export_entitlement_error
    return _export_entitlement_error(app)


def export_ipc_statement_excel(valuation, info: Mapping,
                               path, app=None) -> str:
    """Write a contract-reconciliation statement as Excel-compatible
    CSV (openpyxl-free, stdlib csv only).
    """
    if app is not None:
        err = ensure_export_allowed(app)
        if err is not None:
            raise ValidationError(err)
    rows = build_reconciliation(valuation)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["field", "value"])
        for key in ("valuation_no", "contract_sum",
                     "gross_certified", "retention_withheld",
                     "advance_repaid", "previous_payments",
                     "total_deductions", "net_payable",
                     "work_to_date", "onsite_materials",
                     "retention_rate_pct", "retention_limit",
                     "advance_recovery_this_period",
                     "defects_release_amount", "tax_amount",
                     "tax_mode"):
            writer.writerow([key, rows.get(key, "")])
        writer.writerow([])
        writer.writerow(["item_no", "description", "unit",
                          "rate", "completed_qty", "line_value"])
        for line in rows.get("lines", []):
            writer.writerow([line["item_no"], line["description"],
                              line["unit"], line["rate"],
                              line["completed_qty"], line["line_value"]])
    return str(path)
