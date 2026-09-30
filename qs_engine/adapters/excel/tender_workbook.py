"""Tender-schedule Excel exporter (Phase 17).

Single-sheet tender layout for compiled BOQs: a header block (company,
project, client, reference, measurement standard, date), one priced
table (Item No | Bill Description | Unit | Quantity | Rate | Amount |
Status / Notes), collection group summaries, and a Net Tender Total.

Formula honesty rules (same doctrine as boq_workbook):
- Priced measured rows carry a live Amount formula (=D{row}*E{row}).
- Section totals carry =SUM over their Amount cells ONLY when the
  section is fully priced; otherwise UNRESOLVED text (a partial sum
  must never pose as a total — Excel SUM silently skips text).
- Group rows reference section-total cells with =SUM ONLY when every
  section in the group is priced; otherwise UNRESOLVED text.
- Net Tender Total is a =SUM over section totals ONLY when the whole
  BOQ is priced; otherwise UNRESOLVED text.
- Overheads have no BOQ-DTO layer and always render an em-dash.
- Unpriced/unresolved rows leave Rate and Amount blank with an
  explicit status — never zero, never a formula over blanks.

PRECISION NOTE: .xlsx numerics are IEEE-754 doubles — openpyxl coerces
Decimal values to float on write. Display stays exact for money via
#,##0.00 formatting; the compiled Decimal truth lives in qs_engine,
not in this file. Styling stays in-house neutral: EDMOLT brand
assets/colours are frozen in another product and must never leak in
here (two neutral template styles only).
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from qs_engine import __version__ as QS_ENGINE_VERSION
from qs_engine.boq.models import CompiledBoq
from qs_engine.core.errors import ValidationError

TENDER_GOVERNANCE = (
    "QS Engine = Source of Truth | Excel = Tender / Review Surface"
)

TENDER_HEADERS = ("Item No", "Bill Description", "Unit", "Quantity",
                  "Rate", "Amount", "Status / Notes")

#: Template styles: key -> (label, table-header fill). Both neutral.
TENDER_STYLES = {
    "standard": ("CIVOLINK Standard", "004F9D"),
    "plain": ("Plain Tender (Print)", "BFBFBF"),
}

#: Section-code groups for the collection summary (mirrors the
#: estimate dashboard grouping; adapter-local copy — adapters must
#: never import tkinter-bound ui.views).
TENDER_GROUPS = (
    ("materials", "Direct Materials", ("C", "M", "R", "E", "F")),
    ("labour", "Direct Labour", ("L",)),
    ("plant", "Plant & Haulage", ("P", "H")),
    ("other", "Other Sections", ()),
)

QTY_FORMAT = "#,##0.000"
MONEY_FORMAT = "#,##0.00"

TITLE_FONT = Font(bold=True, size=14)
HEADER_TEXT = Font(bold=True, size=11, color="FFFFFF")
BOLD_FONT = Font(bold=True)
LABEL_FONT = Font(bold=True, size=10)
ITALIC_GREY = Font(italic=True, size=9, color="595959")

BANNER_FILL = PatternFill("solid", start_color="F2F2F2")
SECTION_FILL = PatternFill("solid", start_color="EAEAEA")
TOTAL_FILL = PatternFill("solid", start_color="D9D9D9")

THIN_BORDER = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"), bottom=Side(style="thin"))

TENDER_WIDTHS = {"A": 12, "B": 48, "C": 10, "D": 14,
                 "E": 16, "F": 18, "G": 22}

UNPRICED_STATUS = "Unpriced Item"
UNRESOLVED_TEXT = "UNRESOLVED"
MISSING = "\u2014"

STATUS_NOTES = {
    "priced": "",
    "provisional": "Provisional Sum",
    "unpriced": UNPRICED_STATUS,
    "unresolved": "Unresolved",
}


def _money(cell, value: Decimal) -> None:
    cell.value = value
    cell.number_format = MONEY_FORMAT
    cell.border = THIN_BORDER


def _qty(cell, value: Decimal) -> None:
    cell.value = value
    cell.number_format = QTY_FORMAT
    cell.border = THIN_BORDER


def _blank(cell) -> None:
    cell.value = None
    cell.border = THIN_BORDER


def _header_block(ws, info: dict) -> int:
    """Write title, governance, and header-block rows. Returns the next
    free row (the table header row)."""
    for letter, width in TENDER_WIDTHS.items():
        ws.column_dimensions[letter].width = width
    ws["A1"] = "TENDER SCHEDULE \u2014 BILL OF QUANTITIES"
    ws["A1"].font = TITLE_FONT
    ws.merge_cells("A1:G1")
    ws["A2"] = TENDER_GOVERNANCE
    ws["A2"].font = ITALIC_GREY
    ws["A2"].fill = BANNER_FILL
    ws.merge_cells("A2:G2")
    row = 3
    for label in ("Company Name", "Project Title", "Client", "Reference",
                  "Measurement Standard", "Date"):
        ws.cell(row=row, column=1, value=label).font = LABEL_FONT
        value_cell = ws.cell(row=row, column=2,
                             value=info.get(label, "") or MISSING)
        ws.merge_cells(start_row=row, start_column=2,
                       end_row=row, end_column=7)
        for col in range(1, 8):
            ws.cell(row=row, column=col).border = THIN_BORDER
        row += 1
    return row + 1  # one blank row before the table


def _table_header(ws, row: int, fill: PatternFill) -> None:
    for index, header in enumerate(TENDER_HEADERS, start=1):
        cell = ws.cell(row=row, column=index, value=header)
        cell.font = HEADER_TEXT
        cell.fill = fill
        cell.border = THIN_BORDER
        cell.alignment = Alignment(horizontal="center",
                                   vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 30
    ws.freeze_panes = f"A{row + 1}"
    ws.print_title_rows = f"{row}:{row}"


def _tender_item_row(ws, row: int, item) -> None:
    """One compiled item: live formula when priced, blanks + status
    otherwise (unpriced amounts never become zero or formulas)."""
    ws.cell(row=row, column=1, value=item.item_no).border = THIN_BORDER
    desc = ws.cell(row=row, column=2, value=item.description)
    desc.border = THIN_BORDER
    desc.alignment = Alignment(vertical="center", wrap_text=True)
    # Tender layout: Unit in C, Quantity in D (TENDER_HEADERS) — the
    # live Amount formula below reads =D{row}*E{row}, so Quantity MUST
    # land in D. (boq_workbook uses the opposite C/D order; do not
    # copy its column positions here.)
    unit = ws.cell(row=row, column=3, value=item.unit)
    unit.border = THIN_BORDER
    unit.alignment = Alignment(horizontal="center")
    _qty(ws.cell(row=row, column=4), item.quantity)
    rate_cell = ws.cell(row=row, column=5)
    amount_cell = ws.cell(row=row, column=6)
    status_cell = ws.cell(row=row, column=7,
                          value=STATUS_NOTES.get(item.status, ""))
    status_cell.border = THIN_BORDER
    if item.status in ("unpriced", "unresolved") or item.amount is None:
        _blank(rate_cell)
        if item.rate is not None:
            _money(rate_cell, item.rate)
        _blank(amount_cell)
        return
    if item.pricing_kind == "provisional":
        _blank(rate_cell)  # lump sum carries no rate
        _money(amount_cell, item.amount)
        return
    _money(rate_cell, item.rate)
    amount_cell.value = f"=D{row}*E{row}"
    amount_cell.number_format = MONEY_FORMAT
    amount_cell.border = THIN_BORDER


def export_tender_to_excel(compiled: CompiledBoq, output_path,
                           *, company_name: str = "",
                           project_title: str = "",
                           client: str = "",
                           reference: str = "",
                           measurement_standard: str = "",
                           exported_on: str = "",
                           template_style: str = "standard",
                           engine_version: str = None) -> str:
    """Export a compiled BOQ as a single-sheet tender schedule.

    Header block, priced table with live Amount formulas, section
    =SUM totals (fully priced sections only), group collection rows,
    and a Net Tender Total (fully priced BOQs only). Returns the
    output path as a string.
    """
    if not isinstance(compiled, CompiledBoq):
        raise ValidationError(
            "export_tender_to_excel needs a CompiledBoq; "
            f"got {type(compiled).__name__}")
    if template_style not in TENDER_STYLES:
        raise ValidationError(
            f"Unknown tender template style {template_style!r}; "
            f"expected one of {sorted(TENDER_STYLES)}")
    if engine_version is None:
        engine_version = QS_ENGINE_VERSION
    wb = Workbook()
    ws = wb.active
    ws.title = "Tender Schedule"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    header_fill = PatternFill(
        "solid", start_color=TENDER_STYLES[template_style][1])
    row = _header_block(ws, {
        "Company Name": company_name,
        "Project Title": project_title or compiled.project_ref,
        "Client": client,
        "Reference": reference or compiled.boq_ref,
        "Measurement Standard": measurement_standard,
        "Date": exported_on or date.today().isoformat(),
    })
    _table_header(ws, row, header_fill)
    row += 1
    section_total_cells = {}  # section code -> Amount-column cell ref
    for section in compiled.sections:
        ws.merge_cells(start_row=row, start_column=1, end_row=row,
                       end_column=7)
        head = ws.cell(row=row, column=1,
                       value=f"{section.code} \u2014 {section.title}")
        head.font = BOLD_FONT
        head.fill = SECTION_FILL
        for col in range(1, 8):
            ws.cell(row=row, column=col).border = THIN_BORDER
            ws.cell(row=row, column=col).fill = SECTION_FILL
        row += 1
        first_amount = row
        for item in section.items:
            _tender_item_row(ws, row, item)
            row += 1
        last_amount = row - 1
        ws.merge_cells(start_row=row, start_column=1, end_row=row,
                       end_column=5)
        label = ws.cell(row=row, column=1, value="SECTION TOTAL")
        label.font = BOLD_FONT
        label.fill = TOTAL_FILL
        label.alignment = Alignment(horizontal="right")
        total_cell = ws.cell(row=row, column=6)
        if section.total is None:
            total_cell.value = UNRESOLVED_TEXT
        else:
            total_cell.value = f"=SUM(F{first_amount}:F{last_amount})"
            total_cell.number_format = MONEY_FORMAT
        total_cell.font = BOLD_FONT
        total_cell.fill = TOTAL_FILL
        for col in range(1, 8):
            ws.cell(row=row, column=col).border = THIN_BORDER
            ws.cell(row=row, column=col).fill = TOTAL_FILL
        section_total_cells[section.code] = f"F{row}"
        row += 1
    row += 1  # blank before the collection summary
    ws.cell(row=row, column=1, value="COLLECTION SUMMARY").font = TITLE_FONT
    ws.merge_cells(start_row=row, start_column=1, end_row=row,
                   end_column=7)
    row += 1
    grouped = _all_grouped_codes()
    for _key, label, codes in TENDER_GROUPS:
        ws.merge_cells(start_row=row, start_column=1, end_row=row,
                       end_column=5)
        group_label = ws.cell(row=row, column=1, value=label)
        group_label.font = BOLD_FONT
        group_label.alignment = Alignment(horizontal="right")
        members = [section for section in compiled.sections
                   if (section.code in codes) or
                   (not codes and section.code not in grouped)]
        refs = [section_total_cells[section.code] for section in members
                if section.code in section_total_cells]
        value_cell = ws.cell(row=row, column=6)
        if not members:
            value_cell.value = MISSING  # no such sections at all
        elif any(section.total is None for section in members):
            value_cell.value = UNRESOLVED_TEXT
        elif refs:
            value_cell.value = "=SUM(" + ",".join(refs) + ")"
            value_cell.number_format = MONEY_FORMAT
        else:
            value_cell.value = MISSING
        value_cell.font = BOLD_FONT
        for col in range(1, 8):
            ws.cell(row=row, column=col).border = THIN_BORDER
        row += 1
    ws.merge_cells(start_row=row, start_column=1, end_row=row,
                   end_column=5)
    overheads = ws.cell(row=row, column=1, value="Overheads")
    overheads.font = BOLD_FONT
    overheads.alignment = Alignment(horizontal="right")
    overhead_cell = ws.cell(row=row, column=6, value=MISSING)
    overhead_cell.font = BOLD_FONT
    for col in range(1, 8):
        ws.cell(row=row, column=col).border = THIN_BORDER
    row += 1
    ws.merge_cells(start_row=row, start_column=1, end_row=row,
                   end_column=5)
    net_label = ws.cell(row=row, column=1, value="NET TENDER TOTAL")
    net_label.font = BOLD_FONT
    net_label.fill = TOTAL_FILL
    net_label.alignment = Alignment(horizontal="right")
    net_cell = ws.cell(row=row, column=6)
    if compiled.total is None:
        net_cell.value = UNRESOLVED_TEXT
    else:
        net_cell.value = "=SUM(" + ",".join(
            section_total_cells.values()) + ")"
        net_cell.number_format = MONEY_FORMAT
    net_cell.font = BOLD_FONT
    net_cell.fill = TOTAL_FILL
    for col in range(1, 8):
        ws.cell(row=row, column=col).border = THIN_BORDER
        ws.cell(row=row, column=col).fill = TOTAL_FILL
    row += 1
    note = ws.cell(
        row=row, column=1,
        value=("Overheads: no markup layer exists in the BOQ document "
               "data — price via Rate Builder markups. "
               f"Engine: CIVOLINK QS Engine {engine_version}."))
    note.font = ITALIC_GREY
    ws.merge_cells(start_row=row, start_column=1, end_row=row,
                   end_column=7)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(output))
    return str(output)


def _all_grouped_codes() -> set:
    grouped = set()
    for _key, _label, codes in TENDER_GROUPS:
        grouped.update(code for code in codes if code)
    return grouped
