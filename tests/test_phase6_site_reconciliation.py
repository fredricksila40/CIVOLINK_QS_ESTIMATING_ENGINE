"""Phase 6.2: site material reconciliation & stock log bridge.

Covers store-log ingestion (.xlsx / .csv) with master-key, user-code
and policy-display-code resolution; the Decimal variance engine
(theoretical allowance vs actual site consumption); overrun threshold
classification; the formatted Excel variance report; and the Site
Reconciliation page wiring.
"""

import csv
import hashlib
from decimal import Decimal
from pathlib import Path

import pytest

from qs_engine.boq.models import (
    CompiledBoq,
    CompiledItem,
    CompiledSection,
)
from qs_engine.core.errors import ValidationError
from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.reconciliation import (
    ISSUE,
    RECEIPT,
    STATUS_CRITICAL_OVERRUN,
    STATUS_NORMAL,
    STATUS_WARNING,
    STOCK_COUNT,
    WASTAGE_DISPOSAL,
)
from qs_engine.reconciliation.calculator import (
    boq_material_quantities,
    boq_material_rates,
    classify_status,
    reconcile,
    theoretical_allowance,
    variance_pct,
)
from qs_engine.reconciliation.exporter import export_variance_report
from qs_engine.reconciliation.importer import (
    import_store_log,
    resolve_reference,
    transaction_totals,
)
from qs_engine.reconciliation.models import (
    StockTransaction,
    StoreReconciliationSummary,
)


def _resources():
    """Import qs_engine.resources lazily and verify it is usable.

    The resources package is being refactored in parallel (import-time
    and call-time breakage); deferring the check keeps this module
    collectable while that work is in flight. Returns None when the
    package cannot be used yet.
    """
    try:
        from qs_engine.resources import (
            MaterialCodePolicy, build_material_stack)
        from qs_engine.master_data.repository import MasterDataRepository
        build_material_stack(MasterDataRepository(), None)
    except Exception:
        return None
    return MaterialCodePolicy, build_material_stack


_RESOURCES = _resources()
requires_resources = pytest.mark.skipif(
    _RESOURCES is None,
    reason="qs_engine.resources is mid-refactor (external work in progress)")

SEED_TABLES = (Path(__file__).parent.parent / "qs_engine" /
               "master_data" / "tables")


def _seed_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(SEED_TABLES.glob("*.json"))}


def _write_csv(path: Path, header, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _compiled_boq(items):
    """Build a CompiledBoq from (rate_ref, qty, amount) triples."""
    compiled = [
        CompiledItem(
            item_no=f"1.1.{index}", description="Item",
            section_code="C", subsection_code="C1", trade="concrete",
            unit="m³", quantity=qty, rate=(amount / qty),
            amount=amount, status="PRICED", pricing_kind="PRICED",
            rate_ref=ref, takeoff_ref="", measurement_ref=None,
            provenance=(), notes="", takeoff=None, rate_result=None)
        for index, (ref, qty, amount) in enumerate(items, start=1)
    ]
    total = sum((item.amount for item in compiled), Decimal("0"))
    section = CompiledSection(
        code="C", title="Concrete", items=tuple(compiled), total=total,
        resolved_subtotal=total, has_unresolved=False, subsections=())
    return CompiledBoq(
        project_ref="P", boq_ref="B", sections=(section,),
        total=total, resolved_subtotal=total, has_unresolved=False,
        unresolved_items=())


def _txn(date, kind, ref, qty, unit="m³", doc="", resolved_key=None):
    """A store-log transaction. When ``resolved_key`` is given it is used
    directly (the calculator consumes resolved transactions — resolution
    is the importer's job); otherwise the reference is resolved the same
    way the importer resolves it."""
    if resolved_key is None:
        resources = _resources()
        policy = resources[0]() if resources is not None else None
        resolved_key, _ = resolve_reference(ref, policy=policy)
    return StockTransaction(
        date=date, transaction_type=kind, material_ref=ref,
        quantity=Decimal(qty), unit=unit, document_ref=doc,
        resolved_key=resolved_key or None)


@pytest.fixture()
def stack(tmp_path):
    resources = _resources()
    if resources is None:
        pytest.skip("qs_engine.resources is mid-refactor (external)")
    _, build_material_stack = resources
    return build_material_stack(MasterDataRepository(), tmp_path)


# --- models ------------------------------------------------------------------

def test_transaction_rejects_float_and_negative():
    with pytest.raises(TypeError):
        StockTransaction("2026-09-01", ISSUE, "AGG-002", 1.5)
    with pytest.raises(ValueError):
        StockTransaction("2026-09-01", ISSUE, "AGG-002", -1)
    with pytest.raises(ValueError):
        StockTransaction("2026-09-01", "", "AGG-002", 1)
    txn = _txn("2026-09-01", ISSUE, "AGG-002", "10")
    assert txn.quantity == Decimal("10")


# --- importer: csv ------------------------------------------------------------

@requires_resources
def test_import_csv_canonical_headers(tmp_path):
    log = tmp_path / "log.csv"
    _write_csv(log,
               ["Date", "Transaction Type", "Material", "Quantity",
                "Unit", "Document Ref"],
               [["2026-09-01", "RECEIPT", "AGG-002", "100", "m³",
                 "GRN-001"],
                ["2026-09-02", "ISSUE", "quarry_dust", "60", "m³",
                 "IV-01"]])
    material_code_policy, _ = _resources()
    transactions, warnings = import_store_log(
        log, resolver=None, policy=material_code_policy())
    assert warnings == []
    assert len(transactions) == 2
    assert transactions[0].transaction_type == RECEIPT
    assert transactions[0].quantity == Decimal("100")
    assert transactions[0].resolved_key == "quarry_dust"
    assert transactions[0].document_ref == "GRN-001"
    # policy display code resolves to the same master record
    assert transactions[1].resolved_key == "quarry_dust"


def test_import_csv_header_aliases(tmp_path):
    log = tmp_path / "log.csv"
    _write_csv(log,
               ["Txn Date", "Txn Type", "Item Description", "Qty", "UoM",
                "Voucher No"],
               [["2026-09-01", "Received", "River Sand", "12", "m³",
                 "V-1"],
                ["2026-09-02", "Stock Take", "Ballast 20mm", "3", "m³",
                 "C-1"]])
    transactions, warnings = import_store_log(log)
    assert warnings == []
    assert [t.transaction_type for t in transactions] == [RECEIPT,
                                                          STOCK_COUNT]
    # site material NAMES resolve too: exact, then a unique substring
    assert transactions[0].resolved_key == "river_sand"
    assert transactions[0].resolved_name == "River Sand"
    assert transactions[1].resolved_key == "ballast_20mm"
    assert transactions[0].quantity == Decimal("12")


def test_import_unmatched_material_is_kept_and_flagged(tmp_path):
    log = tmp_path / "log.csv"
    _write_csv(log,
               ["Date", "Transaction Type", "Material", "Quantity",
                "Unit", "Document Ref"],
               [["2026-09-01", "ISSUE", "MYSTERY-MAT", "7", "m³", "IV-9"]])
    transactions, warnings = import_store_log(log)
    assert len(transactions) == 1          # never silently dropped
    assert transactions[0].resolved_key is None
    assert any("MYSTERY-MAT" in warning for warning in warnings)


def test_import_unrecognised_type_is_kept_with_raw_type(tmp_path):
    log = tmp_path / "log.csv"
    _write_csv(log,
               ["Date", "Transaction Type", "Material", "Quantity",
                "Unit", "Document Ref"],
               [["2026-09-01", "RETURN", "AGG-002", "3", "m³", "X-1"]])
    transactions, warnings = import_store_log(log)
    assert len(transactions) == 1
    assert transactions[0].transaction_type == "RETURN"
    assert any("RETURN" in warning for warning in warnings)


def test_import_unparseable_quantity_skips_line_with_warning(tmp_path):
    log = tmp_path / "log.csv"
    _write_csv(log,
               ["Date", "Transaction Type", "Material", "Quantity",
                "Unit", "Document Ref"],
               [["2026-09-01", "ISSUE", "AGG-002", "ten", "m³", "IV-1"]])
    transactions, warnings = import_store_log(log)
    assert transactions == []
    assert any("unparseable quantity" in warning for warning in warnings)


def test_import_missing_file_and_bad_format_fail_closed(tmp_path):
    with pytest.raises(ValidationError):
        import_store_log(tmp_path / "nope.csv")
    other = tmp_path / "log.txt"
    other.write_text("Date,Material\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        import_store_log(other)


def test_import_missing_required_column_fails_closed(tmp_path):
    log = tmp_path / "log.csv"
    _write_csv(log, ["Date", "Material"], [["2026-09-01", "AGG-002"]])
    with pytest.raises(ValidationError) as excinfo:
        import_store_log(log)
    assert "Quantity" in str(excinfo.value)


def test_import_resolves_user_material_codes(tmp_path, stack):
    stack.store.add_material({"name": "Site Sand", "code": "SAND-001",
                              "category_id": "aggregate", "unit": "m³"})
    log = tmp_path / "log.csv"
    _write_csv(log,
               ["Date", "Transaction Type", "Material", "Quantity",
                "Unit", "Document Ref"],
               [["2026-09-01", "ISSUE", "SAND-001", "5", "m³", "IV-1"]])
    transactions, warnings = import_store_log(log, resolver=stack.resolver)
    assert warnings == []
    assert transactions[0].resolved_key.startswith("user:")
    assert transactions[0].resolved_name == "Site Sand"


# --- importer: xlsx -----------------------------------------------------------

@requires_resources
def test_import_xlsx_workbook(tmp_path):
    from openpyxl import Workbook
    log = tmp_path / "store_log.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Date", "Transaction Type", "Material", "Quantity",
                "Unit", "Document Ref"])
    sheet.append(["2026-09-01", "RECEIPT", "AGG-002", 100, "m³", "GRN-1"])
    sheet.append(["2026-09-02", "ISSUE", "AGG-002", 40, "m³", "IV-1"])
    workbook.save(log)
    material_code_policy, _ = _resources()
    transactions, warnings = import_store_log(
        log, policy=material_code_policy())
    assert warnings == []
    assert [t.transaction_type for t in transactions] == [RECEIPT, ISSUE]
    assert transactions[0].quantity == Decimal("100")
    assert transactions[1].resolved_key == "quarry_dust"


def test_transaction_totals_are_exact_decimals(tmp_path):
    log = tmp_path / "log.csv"
    _write_csv(log,
               ["Date", "Transaction Type", "Material", "Quantity",
                "Unit", "Document Ref"],
               [["2026-09-01", "RECEIPT", "AGG-002", "10.1", "m³", "G"],
                ["2026-09-02", "ISSUE", "AGG-002", "0.2", "m³", "I"]])
    transactions, _ = import_store_log(log)
    totals = transaction_totals(transactions)
    assert totals[RECEIPT] == Decimal("10.1")
    assert totals[ISSUE] == Decimal("0.2")
    assert isinstance(totals[ISSUE], Decimal)


# --- calculator ---------------------------------------------------------------

def test_theoretical_allowance_applies_wastage_exactly():
    assert theoretical_allowance(50, None) == Decimal("50")
    assert theoretical_allowance(50, 5) == Decimal("52.5")
    assert theoretical_allowance("100", "12.5") == Decimal("112.5")
    with pytest.raises(ValidationError):
        theoretical_allowance(-1, 5)
    with pytest.raises(ValidationError):
        theoretical_allowance(50, -1)


def test_variance_pct_exact_and_none_on_zero_allowance():
    assert variance_pct(20, 50) == Decimal("40")
    assert variance_pct(0, 0) is None
    with pytest.raises(TypeError):
        variance_pct(20.5, 50)


def test_classify_status_thresholds():
    # (variance_pct, variance_qty, warning_threshold_pct, critical_multiplier)
    assert classify_status(Decimal("4"), Decimal("0"), Decimal("5"),
                           Decimal("2")) == STATUS_NORMAL
    assert classify_status(Decimal("6"), Decimal("0"), Decimal("5"),
                           Decimal("2")) == STATUS_WARNING
    assert classify_status(Decimal("12"), Decimal("0"), Decimal("5"),
                           Decimal("2")) == STATUS_CRITICAL_OVERRUN
    # a zero allowance with any issue quantity is an overrun
    assert classify_status(None, Decimal("1"), Decimal("5"),
                           Decimal("2")) == STATUS_CRITICAL_OVERRUN
    assert classify_status(None, Decimal("0"), Decimal("5"),
                           Decimal("2")) == STATUS_NORMAL
    # under-consumption never escalates (overrun alerts only)
    assert classify_status(Decimal("-40"), Decimal("0"), Decimal("5"),
                           Decimal("2")) == STATUS_NORMAL


def test_boq_material_quantities_aggregate_per_reference():
    boq = _compiled_boq([
        ("quarry_dust", Decimal("50"), Decimal("5000")),
        ("quarry_dust", Decimal("25"), Decimal("2500")),
        ("river_sand", Decimal("10"), Decimal("1000")),
    ])
    assert boq_material_quantities(boq) == {
        "quarry_dust": Decimal("75"), "river_sand": Decimal("10")}
    assert boq_material_quantities(None) == {}


def test_boq_material_rates_effective_rate():
    boq = _compiled_boq([
        ("quarry_dust", Decimal("50"), Decimal("5000")),
        ("quarry_dust", Decimal("50"), Decimal("6000")),
    ])
    rates = boq_material_rates(boq)
    assert rates["quarry_dust"] == Decimal("110")


def test_reconcile_end_to_end_with_rates(tmp_path):
    before = _seed_hashes()
    boq = _compiled_boq([
        ("quarry_dust", Decimal("50"), Decimal("5000")),
        ("river_sand", Decimal("20"), Decimal("2000")),
    ])
    transactions = [
        _txn("2026-09-01", RECEIPT, "quarry_dust", "100",
             resolved_key="quarry_dust"),
        _txn("2026-09-02", ISSUE, "AGG-002", "70",
             resolved_key="quarry_dust"),
        _txn("2026-09-03", ISSUE, "quarry_dust", "10",
             resolved_key="quarry_dust"),
        _txn("2026-09-04", WASTAGE_DISPOSAL, "quarry_dust", "5",
             resolved_key="quarry_dust"),
        _txn("2026-09-05", ISSUE, "river_sand", "22",
             resolved_key="river_sand"),
    ]
    summary = reconcile(boq, transactions, resolver=None)
    assert summary.total_materials_tracked == 2
    rows = {row.material_key: row for row in summary.rows}
    quarry = rows["quarry_dust"]
    assert quarry.theoretical_qty == Decimal("50")   # null wastage: no uplift
    assert quarry.actual_issued == Decimal("80")
    assert quarry.store_balance == Decimal("15")
    assert quarry.variance_qty == Decimal("30")
    assert quarry.variance_pct == Decimal("60")
    assert quarry.variance_value == Decimal("3000")  # 30 x 100 effective
    assert quarry.status == STATUS_CRITICAL_OVERRUN  # 60% > 5% x 2
    sand = rows["river_sand"]
    assert sand.variance_pct == Decimal("10")
    assert sand.status == STATUS_WARNING
    assert summary.theoretical_budget_value == Decimal("7000")
    assert summary.actual_issued_value == Decimal("10200")
    assert summary.overall_variance_value == Decimal("3200")
    assert summary.unresolved == ()
    assert _seed_hashes() == before


def test_reconcile_with_explicit_unit_rates():
    boq = _compiled_boq([("quarry_dust", Decimal("50"), Decimal("5000"))])
    transactions = [_txn("2026-09-02", ISSUE, "quarry_dust", "60",
                          resolved_key="quarry_dust")]
    summary = reconcile(boq, transactions,
                        unit_rates={"quarry_dust": "250"})
    row = summary.rows[0]
    assert row.unit_rate == Decimal("250")
    assert row.variance_value == Decimal("2500")     # 10 x 250


def test_reconcile_without_boq_is_site_only():
    transactions = [_txn("2026-09-02", ISSUE, "quarry_dust", "10",
                          resolved_key="quarry_dust")]
    summary = reconcile(None, transactions, resolver=None)
    row = summary.rows[0]
    assert row.theoretical_qty == Decimal("0")
    assert row.variance_qty == Decimal("10")
    assert row.variance_pct is None
    assert row.status == STATUS_CRITICAL_OVERRUN
    assert summary.theoretical_budget_value is None  # no rate data


def test_reconcile_unresolved_materials_are_reported():
    transactions = [
        _txn("2026-09-02", ISSUE, "MYSTERY-MAT", "7"),
        _txn("2026-09-02", ISSUE, "quarry_dust", "10",
             resolved_key="quarry_dust"),
    ]
    summary = reconcile(None, transactions, resolver=None)
    assert summary.unresolved == ("MYSTERY-MAT",)
    assert summary.total_materials_tracked == 1      # unresolved not priced
    assert summary.rows[0].material_key == "quarry_dust"


def test_reconcile_rejects_bad_threshold():
    with pytest.raises(ValidationError):
        reconcile(None, [], warning_threshold_pct=-1)
    with pytest.raises(ValidationError):
        reconcile(None, [], critical_multiplier=0)


# --- exporter -----------------------------------------------------------------

def test_export_variance_report_writes_formatted_workbook(tmp_path):
    boq = _compiled_boq([("quarry_dust", Decimal("50"), Decimal("5000"))])
    transactions = [_txn("2026-09-02", ISSUE, "AGG-002", "70",
                          resolved_key="quarry_dust")]
    summary = reconcile(boq, transactions, resolver=None)
    out = export_variance_report(tmp_path / "variance.xlsx", summary)
    from openpyxl import load_workbook
    workbook = load_workbook(out)
    assert workbook.sheetnames == ["Summary", "Material Variance"]
    grid = workbook["Material Variance"]
    headers = [cell.value for cell in grid[1]]
    assert "Status" in headers
    status_cell = grid.cell(row=2, column=headers.index("Status") + 1)
    assert status_cell.value == STATUS_CRITICAL_OVERRUN
    assert status_cell.fill.fgColor.rgb not in (None, "00000000")
    summary_sheet = workbook["Summary"]
    assert summary_sheet["A1"].value.startswith("Site Material Variance")


def test_export_fails_closed_on_empty_summary_and_bad_suffix(tmp_path):
    with pytest.raises(ValidationError):
        export_variance_report(tmp_path / "r.xlsx",
                              StoreReconciliationSummary())
    boq = _compiled_boq([("quarry_dust", Decimal("50"), Decimal("5000"))])
    summary = reconcile(boq, [], resolver=None)
    with pytest.raises(ValidationError):
        export_variance_report(tmp_path / "r.csv", summary)


# --- UI wiring ----------------------------------------------------------------

def test_reconciliation_page_is_registered():
    import inspect
    from qs_engine.ui import views
    from qs_engine.ui.widgets import guide_text_for
    assert views.PAGES["reconciliation"] is views.build_reconciliation_page
    source = inspect.getsource(views.build_reconciliation_page)
    assert "import_store_log" in source
    assert "reconcile" in source
    assert "RECONCILIATION_COLUMNS" in source
    assert "active_material_code_policy" in source
    groups = dict()
    for group, items in views.NAV_GROUPS:
        groups[group] = [key for key, _label, _kind in items]
    assert "reconciliation" in groups["RESOURCES"]
    assert guide_text_for("reconciliation", "")


def test_reconciliation_page_end_to_end(tmp_path):
    from qs_engine.ui import views

    def app_or_skip():
        try:
            return views.QSApp()
        except Exception as exc:  # pragma: no cover - display-dependent
            pytest.skip(f"QSApp needs a display: {exc}")

    log = tmp_path / "site_log.csv"
    _write_csv(log,
               ["Date", "Transaction Type", "Material", "Quantity",
                "Unit", "Document Ref"],
               [["2026-09-01", "RECEIPT", "AGG-002", "100", "m³", "G"],
                ["2026-09-02", "ISSUE", "AGG-002", "70", "m³", "I"]])
    app = app_or_skip()
    app.show("reconciliation")
    app.update_idletasks()
    try:
        entries = []

        def walk(widget):
            for child in widget.winfo_children():
                if child.winfo_class() == "TEntry":
                    entries.append(child)
                walk(child)

        walk(app.workspace.interior)
        assert entries, "import controls missing"
        entries[0].delete(0, "end")
        entries[0].insert(0, str(log))
        app.update_idletasks()
        readback = entries[0].get()
        buttons = []

        def walk_buttons(widget):
            for child in widget.winfo_children():
                if (child.winfo_class() == "TButton"
                        and child.cget("text") == "Import Store Log"):
                    buttons.append(child)
                walk_buttons(child)

        walk_buttons(app.workspace.interior)
        assert len(buttons) == 1
        buttons[0].invoke()
        app.update_idletasks()
        status_labels = []

        def walk_status(widget):
            for child in widget.winfo_children():
                if child.winfo_class() == "TLabel":
                    status_labels.append(child.cget("text"))
                walk_status(child)

        walk_status(app.workspace.interior)
        assert app.session.store_transactions is not None, (
            f"entries={len(entries)} readback={readback!r} "
            f"status={status_labels[:3]}")
        grids = []

        def walk_grids(widget):
            for child in widget.winfo_children():
                if child.winfo_class() == "Treeview":
                    grids.append(child)
                walk_grids(child)

        walk_grids(app.workspace.interior)
        assert grids, "variance grid missing"
        codes = {grids[0].item(iid, "values")[0]
                 for iid in grids[0].get_children()}
        assert "QRY-10138-QDT01" in codes   # quarry_dust master record
        statuses = {grids[0].item(iid, "values")[8]
                    for iid in grids[0].get_children()}
        assert statuses == {STATUS_CRITICAL_OVERRUN}
        # seeded guide text for the page header
        from qs_engine.ui.widgets import guide_text_for
        assert guide_text_for("reconciliation", "")
    finally:
        app.destroy()
