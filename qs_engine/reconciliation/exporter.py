"""Site Material Variance & Store Reconciliation Report export (Phase 6.2).

Domain-facing entry point: validates the summary and delegates the
workbook rendering to the Excel adapter
(``qs_engine/adapters/excel/variance_report.py``) — openpyxl is a
presentation dependency and stays out of the domain layer (enforced by
the import-boundary suite).
"""

from pathlib import Path
from typing import Optional

from ..core.errors import ValidationError
from .models import StoreReconciliationSummary


def export_variance_report(path, summary: StoreReconciliationSummary,
                           title: Optional[str] = None) -> Path:
    """Write the reconciliation summary to a formatted .xlsx workbook.

    Returns the written path. Raises ValidationError when the summary
    has no rows (there is nothing to report) or the path is not .xlsx.
    """
    if not isinstance(summary, StoreReconciliationSummary):
        raise ValidationError(
            "export_variance_report needs a StoreReconciliationSummary; "
            f"got {type(summary).__name__}")
    from ..adapters.excel.variance_report import (REPORT_TITLE,
                                                  write_variance_report)
    return write_variance_report(
        path, summary, title=title or REPORT_TITLE)
