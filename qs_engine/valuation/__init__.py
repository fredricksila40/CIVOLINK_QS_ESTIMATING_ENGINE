"""Valuation domain package (Phase 19 + Phase 6): Interim Payment
Certificates.

Phase 6 adds a multi-period model (ValuationManager), a commercial
deduction & tax calculator (CommercialCalculator) and statement
export (build_reconciliation, ensure_export_allowed).
The core IPC arithmetic remains pure and caller-supplied.
"""

from qs_engine.valuation.calculator import (
    CommercialCalculator,
    CommercialValuation,
)
from qs_engine.valuation.exporter import (
    build_reconciliation,
    ensure_export_allowed,
    export_ipc_statement_excel,
)
from qs_engine.valuation.ipc_engine import (
    IPCCalculator,
    IPCLine,
    IPCValuation,
    compute_ipc,
)
from qs_engine.valuation.models import (
    ValuationManager,
    ValuationPeriod,
    VALID_TRANSITIONS,
    VALUATION_STATES,
)

__all__ = [
    "CommercialCalculator", "CommercialValuation",
    "IPCCalculator", "IPCLine", "IPCValuation",
    "ValuationManager", "ValuationPeriod",
    "VALID_TRANSITIONS", "VALUATION_STATES",
    "build_reconciliation", "compute_ipc",
    "ensure_export_allowed", "export_ipc_statement_excel",
]