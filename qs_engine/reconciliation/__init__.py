"""Site material reconciliation & stock log bridge (Phase 6.2).

One coherent layer between site store logs and the QS engine::

    site store log (.xlsx / .csv)
          + StockTransaction log (importer)
          + compiled BOQ theoretical allowances
          -> Material consumption variance (calculator, exact Decimal)
          -> formatted variance report (exporter)

Invariants this package exists to keep:

* Seed master data is never written — site logs are read-only inputs.
* Every quantity, rate, percentage and monetary value is an exact
  ``decimal.Decimal``; floats are rejected at the boundary.
* Unrecognized site material keys are never silently dropped: the line
  is retained unresolved and reported, so reconciliation fails closed.
* Monetary values are only computed from rates that actually exist —
  no rate is ever invented, so a total is withheld (None) rather than
  understated when any tracked material is unpriced.
"""

from .calculator import (
    DEFAULT_CRITICAL_MULTIPLIER,
    DEFAULT_WARNING_THRESHOLD_PCT,
    boq_material_quantities,
    boq_material_rates,
    classify_status,
    reconcile,
    theoretical_allowance,
    variance_pct,
)
from .exporter import export_variance_report
from .importer import import_store_log, resolve_reference, transaction_totals
from .models import (
    ISSUE,
    RECEIPT,
    STATUS_CRITICAL_OVERRUN,
    STATUS_NORMAL,
    STATUS_WARNING,
    STOCK_COUNT,
    TRANSACTION_TYPES,
    WASTAGE_DISPOSAL,
    MaterialVarianceRow,
    StockTransaction,
    StoreReconciliationSummary,
    VARIANCE_STATUSES,
)

__all__ = [
    "boq_material_quantities",
    "boq_material_rates",
    "classify_status",
    "DEFAULT_CRITICAL_MULTIPLIER",
    "DEFAULT_WARNING_THRESHOLD_PCT",
    "export_variance_report",
    "import_store_log",
    "ISSUE",
    "MaterialVarianceRow",
    "RECEIPT",
    "reconcile",
    "resolve_reference",
    "STATUS_CRITICAL_OVERRUN",
    "STATUS_NORMAL",
    "STATUS_WARNING",
    "StockTransaction",
    "StoreReconciliationSummary",
    "STOCK_COUNT",
    "theoretical_allowance",
    "transaction_totals",
    "TRANSACTION_TYPES",
    "variance_pct",
    "VARIANCE_STATUSES",
    "WASTAGE_DISPOSAL",
]
