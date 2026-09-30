"""Site store-log workbook reader (Phase 6.2 adapter).

openpyxl is a presentation dependency and lives ONLY inside
``qs_engine/adapters/`` (enforced by the import-boundary suite). This
adapter reads a site inventory Excel workbook (``.xlsx``) into the same
canonical row dicts the CSV path produces, so the reconciliation importer
stays format-agnostic and dependency-free.

Reading discipline (openpyxl has no formula evaluator): cells are read
with ``data_only=True`` (Excel-saved cached values); unevaluated
formula strings can never be trusted and count as missing — never
guessed.
"""

import csv
from pathlib import Path
from typing import List

from qs_engine.core.errors import ValidationError


def read_store_log_rows(path) -> List[dict]:
    """Read a .xlsx/.xlsm/.csv site store log into canonical row dicts.

    Returns a list of ``{canonical field: raw string value}`` dicts using
    the importer's header mapping (Date, Transaction Type, Material,
    Quantity, Unit, Document Ref and their common aliases). Raises
    ValidationError for an unsupported format or an unreadable file.
    """
    path = Path(path)
    if not path.exists():
        raise ValidationError(f"Store log not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _read_csv(path)
    if suffix in (".xlsx", ".xlsm"):
        return _read_xlsx(path)
    raise ValidationError(
        f"Unsupported store log format {suffix!r}; expected .xlsx or .csv")


def _read_csv(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        raw_rows = [row for row in reader if any(cell.strip()
                                                 for cell in row)]
    if not raw_rows:
        return []
    from qs_engine.reconciliation.importer import _header_map
    mapping = _header_map(raw_rows[0])
    rows = []
    for raw in raw_rows[1:]:
        row = {}
        for canonical, index in mapping.items():
            row[canonical] = raw[index].strip() if index < len(raw) else ""
        rows.append(row)
    return rows


def _read_xlsx(path: Path) -> List[dict]:
    from openpyxl import load_workbook
    workbook = load_workbook(path, data_only=True, read_only=True)
    try:
        sheet = workbook.active
        raw_rows = []
        for row in sheet.iter_rows(values_only=True):
            cells = ["" if cell is None else str(cell).strip()
                     for cell in row]
            if any(cells):
                raw_rows.append(cells)
    finally:
        workbook.close()
    if not raw_rows:
        return []
    from qs_engine.reconciliation.importer import _header_map
    mapping = _header_map(raw_rows[0])
    rows = []
    for raw in raw_rows[1:]:
        row = {}
        for canonical, index in mapping.items():
            row[canonical] = raw[index] if index < len(raw) else ""
        rows.append(row)
    return rows
