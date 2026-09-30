"""Site store-log ingestion (Phase 6.2).

Parses site inventory Excel workbooks (``.xlsx``) and ``.csv`` store
logs into ``StockTransaction`` records, mapping each site material
name/code to the active ``MaterialResolver`` — master keys, user
material codes, and the project's policy display codes all resolve.

Fail-closed auditability: a site reference that maps to nothing is
NEVER silently dropped. The transaction is retained with
``resolved_key=None`` and its raw reference is reported in the
warnings tuple so the reconciliation can flag it explicitly.
"""

from decimal import Decimal
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from ..core.decimal_policy import to_decimal
from ..core.errors import ValidationError
from .models import (
    ISSUE,
    RECEIPT,
    STOCK_COUNT,
    TRANSACTION_TYPES,
    WASTAGE_DISPOSAL,
    StockTransaction,
)

#: Header aliases (folded, lower-cased) -> canonical field. Site logs
#: arrive from many stores; the importer recognises the common spellings
#: and never guesses beyond them.
_HEADER_ALIASES = {
    "date": "date",
    "transaction date": "date",
    "txn date": "date",
    "transaction type": "transaction_type",
    "type": "transaction_type",
    "txn type": "transaction_type",
    "transaction": "transaction_type",
    "material": "material_ref",
    "material key": "material_ref",
    "material code": "material_ref",
    "material name": "material_ref",
    "description": "material_ref",
    "item": "material_ref",
    "item description": "material_ref",
    "quantity": "quantity",
    "qty": "quantity",
    "quantity issued": "quantity",
    "quantity received": "quantity",
    "unit": "unit",
    "uom": "unit",
    "unit of measure": "unit",
    "document ref": "document_ref",
    "document reference": "document_ref",
    "doc ref": "document_ref",
    "voucher": "document_ref",
    "voucher no": "document_ref",
    "issue voucher": "document_ref",
    "issue voucher no": "document_ref",
    "receipt no": "document_ref",
    "store ref": "document_ref",
}

#: Transaction-type spellings found on site logs -> canonical type.
#: Keys are lower-cased; lookups fold the raw header value the same way.
_TYPE_ALIASES = {
    "receipt": RECEIPT,
    "received": RECEIPT,
    "in": RECEIPT,
    "grn": RECEIPT,
    "goods received": RECEIPT,
    "issue": ISSUE,
    "issued": ISSUE,
    "out": ISSUE,
    "wastage_disposal": WASTAGE_DISPOSAL,
    "wastage": WASTAGE_DISPOSAL,
    "disposal": WASTAGE_DISPOSAL,
    "waste disposal": WASTAGE_DISPOSAL,
    "stock_count": STOCK_COUNT,
    "stock count": STOCK_COUNT,
    "count": STOCK_COUNT,
    "stocktake": STOCK_COUNT,
    "stock take": STOCK_COUNT,
}


def _fold(text) -> str:
    return " ".join(str(text or "").split()).strip().lower()


def _header_map(headers: Sequence[str]) -> dict:
    """Map canonical field -> column index for one header row."""
    mapping = {}
    for index, header in enumerate(headers):
        canonical = _HEADER_ALIASES.get(_fold(header))
        if canonical is not None and canonical not in mapping:
            mapping[canonical] = index
    return mapping


def _read_rows(path: Path) -> List[dict]:
    """Read a .xlsx or .csv store log into {canonical field: raw value}.

    The workbook parsing itself lives in the Excel adapter
    (``qs_engine/adapters/excel/store_log.py``) — openpyxl is a
    presentation dependency and stays out of the domain layer.
    """
    from ..adapters.excel.store_log import read_store_log_rows
    return read_store_log_rows(path)


def _seed_records(resolver) -> list:
    """Seed material records: the resolver's, or the shipped catalogue.

    The shipped master data is always available, so policy display-code
    resolution works even when no resolver was injected.
    """
    if resolver is not None:
        try:
            records = resolver.list("materials")
        except Exception:
            records = []
    else:
        from ..master_data.repository import MasterDataRepository
        try:
            records = MasterDataRepository().list("materials")
        except Exception:
            records = []
    return [record for record in records
            if not str(record.get("key", "")).startswith("user:")]


def resolve_reference(reference: str, resolver=None,
                      policy=None) -> Tuple[Optional[str], str]:
    """Public: map one site material reference to (master key, name).

    Resolution order: identity through the resolver (master key, user
    code or alias), then seed identity (key, legacy code, recorded code
    or material name — exact, else a UNIQUE name substring), then the
    project policy's display code. Returns ("", "") when nothing matches
    or when a substring match is ambiguous — callers keep the line and
    flag it.
    """
    text = str(reference or "").strip()
    if not text:
        return ("", "")
    if resolver is not None:
        try:
            record = resolver.get("materials", text)
        except Exception:
            record = None
        if record is not None:
            return (str(record.get("key", "")), str(record.get("name", "")))
    seed_records = _seed_records(resolver)
    needle = _fold(text)
    for record in seed_records:
        if needle in (_fold(record.get("key", "")),
                      _fold(record.get("legacy_code", "")),
                      _fold(record.get("code", "")),
                      _fold(record.get("name", ""))):
            return (str(record.get("key", "")),
                    str(record.get("name", "")))
    # Site logs often carry a short name ("Ballast 20mm") for a longer
    # master name ("Coarse Aggregate / Ballast 20mm"): a unique substring
    # match resolves, an ambiguous one fails closed.
    if len(needle) >= 4:
        name_matches = [record for record in seed_records
                        if needle in _fold(record.get("name", ""))]
        if len(name_matches) == 1:
            record = name_matches[0]
            return (str(record.get("key", "")),
                    str(record.get("name", "")))
    if policy is not None:
        for record in seed_records:
            if _fold(policy.resolve_display_code(
                    record, seed_records=seed_records)) == needle:
                return (str(record.get("key", "")),
                        str(record.get("name", "")))
    return ("", "")


def _resolve_reference(reference: str, resolver, policy) -> Tuple[
        Optional[str], str]:
    """Internal alias for :func:`resolve_reference`."""
    return resolve_reference(reference, resolver=resolver, policy=policy)


def import_store_log(path, resolver=None, policy=None) -> Tuple[
        List[StockTransaction], List[str]]:
    """Ingest one site store log.

    Returns ``(transactions, warnings)``. Every data row becomes a
    transaction — including rows whose material reference does not
    resolve; those are kept with ``resolved_key=None`` and named in
    ``warnings`` so reconciliation fails closed instead of dropping
    site lines. Raises ValidationError for an unreadable file, a missing
    header, or a row without a parseable quantity.
    """
    path = Path(path)
    if not path.exists():
        raise ValidationError(f"Store log not found: {path}")
    rows = _read_rows(path)
    if not rows:
        return ([], [f"{path.name}: no data rows found"])
    required = {"date", "transaction_type", "material_ref", "quantity"}
    missing = required - set(rows[0].keys())
    if missing:
        raise ValidationError(
            f"{path.name}: store log is missing column(s) "
            f"{sorted(missing)} — expected headers such as Date, "
            f"Transaction Type, Material, Quantity, Unit, Document Ref")

    transactions: List[StockTransaction] = []
    warnings: List[str] = []
    for number, row in enumerate(rows, start=2):
        ref = str(row.get("material_ref", "") or "").strip()
        raw_type = str(row.get("transaction_type", "") or "").strip()
        txn_type = _TYPE_ALIASES.get(_fold(raw_type))
        if txn_type is None:
            # Fail closed: the line is retained with its raw type (it
            # simply never matches a canonical flow bucket) and the
            # warning names it — nothing is silently dropped.
            warnings.append(
                f"{path.name} row {number}: unrecognised transaction type "
                f"{raw_type!r} — line kept with the raw type recorded")
            txn_type = raw_type.upper()
        try:
            quantity = to_decimal(row.get("quantity", ""), "quantity")
        except (TypeError, ValueError):
            warnings.append(
                f"{path.name} row {number}: unparseable quantity "
                f"{row.get('quantity', '')!r} for {ref!r} — line skipped")
            continue
        resolved_key, resolved_name = _resolve_reference(ref, resolver,
                                                         policy)
        if ref and not resolved_key:
            warnings.append(
                f"{path.name} row {number}: site material {ref!r} does not "
                f"match any master key, user code, or policy display code "
                f"— line kept UNRESOLVED")
        try:
            transactions.append(StockTransaction(
                date=str(row.get("date", "") or ""),
                transaction_type=txn_type,
                material_ref=ref,
                quantity=quantity,
                unit=str(row.get("unit", "") or ""),
                document_ref=str(row.get("document_ref", "") or ""),
                resolved_key=resolved_key or None,
                resolved_name=resolved_name,
            ))
        except ValueError as exc:
            warnings.append(f"{path.name} row {number}: {exc} — line skipped")
    return (transactions, warnings)


def transaction_totals(transactions: Sequence[StockTransaction]) -> dict:
    """Exact Decimal totals per transaction type (unresolved included)."""
    totals = {kind: Decimal("0") for kind in TRANSACTION_TYPES}
    for txn in transactions:
        if txn.transaction_type in totals:
            totals[txn.transaction_type] += txn.quantity
    return totals
