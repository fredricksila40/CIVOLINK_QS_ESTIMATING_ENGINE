"""Site material reconciliation domain models (Phase 6.2).

Pure data structures — no I/O, no widgets, no arithmetic beyond the
Decimal coercions the precision guard requires. Every quantity is an
exact ``decimal.Decimal``; floats are rejected at the boundary by
``core.decimal_policy.to_decimal``.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Tuple

from ..core.decimal_policy import to_decimal

#: Transaction types a site store log can carry.
RECEIPT = "RECEIPT"
ISSUE = "ISSUE"
WASTAGE_DISPOSAL = "WASTAGE_DISPOSAL"
STOCK_COUNT = "STOCK_COUNT"

#: The transaction types, in display order.
TRANSACTION_TYPES = (RECEIPT, ISSUE, WASTAGE_DISPOSAL, STOCK_COUNT)

#: Variance statuses, in escalating severity order.
STATUS_NORMAL = "NORMAL"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL_OVERRUN = "CRITICAL_OVERRUN"

#: Statuses, in display order.
VARIANCE_STATUSES = (STATUS_NORMAL, STATUS_WARNING, STATUS_CRITICAL_OVERRUN)


@dataclass(frozen=True)
class StockTransaction:
    """One site store-log line.

    ``material_ref`` is the material name/code exactly as written in the
    site log; ``resolved_key`` is the master-data key the importer mapped
    it to (None when unresolved — the line is kept and flagged, never
    silently dropped). ``quantity`` is an exact Decimal; ``unit`` and
    ``document_ref`` are free text as recorded on the voucher.
    """

    date: str
    transaction_type: str
    material_ref: str
    quantity: Decimal
    unit: str = ""
    document_ref: str = ""
    resolved_key: Optional[str] = None
    resolved_name: str = ""

    def __post_init__(self):
        object.__setattr__(self, "date", str(self.date or "").strip())
        object.__setattr__(self, "transaction_type",
                           str(self.transaction_type or "").strip().upper())
        object.__setattr__(self, "material_ref",
                           str(self.material_ref or "").strip())
        object.__setattr__(self, "quantity",
                           to_decimal(self.quantity, "quantity"))
        object.__setattr__(self, "unit", str(self.unit or "").strip())
        object.__setattr__(self, "document_ref",
                           str(self.document_ref or "").strip())
        if not self.transaction_type:
            raise ValueError("StockTransaction requires a transaction type")
        if not self.material_ref:
            raise ValueError("StockTransaction requires a material reference")
        if self.quantity < 0:
            raise ValueError(
                f"StockTransaction quantity must be >= 0; got {self.quantity}")


@dataclass(frozen=True)
class MaterialVarianceRow:
    """One material's theoretical-vs-actual reconciliation line.

    All quantities are exact Decimals. ``variance_value`` is None when no
    unit rate is available for the material — a monetary value is only
    ever computed from a rate that actually exists, never invented.
    ``unit_rate`` is the rate used (None when unavailable).
    """

    material_key: str
    code: str
    name: str
    unit: str
    theoretical_qty: Decimal
    actual_issued: Decimal
    store_balance: Decimal
    variance_qty: Decimal
    variance_pct: Optional[Decimal]
    variance_value: Optional[Decimal]
    unit_rate: Optional[Decimal]
    status: str
    wastage_pct: Optional[Decimal] = None
    unresolved: Tuple[str, ...] = ()


@dataclass(frozen=True)
class StoreReconciliationSummary:
    """Whole-project reconciliation result.

    ``rows`` holds one entry per material tracked on site (issued or
    counted); ``unresolved`` names every site-log reference that could
    not be mapped to master data (fail-closed auditability — the lines
    are retained on the transactions, never dropped). Monetary totals are
    exact Decimals, None when no rate data exists to price them.
    """

    rows: Tuple[MaterialVarianceRow, ...] = ()
    unresolved: Tuple[str, ...] = ()
    total_materials_tracked: int = 0
    theoretical_budget_value: Optional[Decimal] = None
    actual_issued_value: Optional[Decimal] = None
    overall_variance_value: Optional[Decimal] = None
    warning_threshold_pct: Decimal = field(
        default_factory=lambda: to_decimal(5, "warning_threshold_pct"))
    critical_multiplier: Decimal = field(
        default_factory=lambda: to_decimal(2, "critical_multiplier"))
    transactions: Tuple[StockTransaction, ...] = ()
