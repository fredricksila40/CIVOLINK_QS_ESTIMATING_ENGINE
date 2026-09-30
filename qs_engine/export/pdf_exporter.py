"""Formal PDF exporter (Phase 19): BOQ summary + IPC statement.

Two print-ready documents from engine DTOs (amounts travel as exact
strings; display formatting via quantize_money happens at this output
boundary only):

- PDF 1: Formal Bill of Quantities Summary (header, client info,
  group breakdown, net total).
- PDF 2: Interim Payment Certificate statement (valuation number,
  executive summary, deductions breakdown, sign-off block).

Unresolved totals render as UNRESOLVED text — a partial figure never
poses as a certified total. Builders return bytes (API streams them);
export_* helpers write the bytes to a file path (UI saves them).
"""

from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm, mm

#: Hairline width in points, written without a float literal to honor
#: the decimal policy (no binary floating-point constants in qs_engine).
_HAIRLINE_PT = 1 / 2
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from qs_engine.boq.models import CompiledBoq
from qs_engine.core.decimal_policy import quantize_money
from qs_engine.core.errors import ValidationError

ACCENT = HexColor("#004F9D")
GREY_DARK = HexColor("#2F3A44")
GREY_LIGHT = HexColor("#EAEAEA")
WHITE = HexColor("#FFFFFF")

GOVERNANCE_LINE = (
    "QS Engine = Source of Truth | Document = Presentation Surface")

#: Collection groups (adapter-local copy — exporters must never import
#: tkinter-bound ui.views; same grouping contract as the dashboard).
PDF_GROUPS = (
    ("Direct Materials", ("C", "M", "R", "E", "F")),
    ("Direct Labour", ("L",)),
    ("Plant & Haulage", ("P", "H")),
    ("Other Sections", ()),
)

MISSING = "\u2014"
UNRESOLVED_TEXT = "UNRESOLVED"


def _text(value) -> str:
    """Paragraph-safe text (reportlab mini-html escaping)."""
    return escape(str(value or ""))


def _money_display(amount) -> str:
    """Exact-string amount -> 2dp display (None stays UNRESOLVED)."""
    if amount is None:
        return UNRESOLVED_TEXT
    return f"{quantize_money(Decimal(str(amount))):,}"


def _doc(buffer: BytesIO, title: str) -> SimpleDocTemplate:
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, title=title,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm)
    return doc


def _styles():
    return getSampleStyleSheet()


def _meta_table(info: dict, pairs) -> Table:
    """Two-column label/value block; blanks become an em-dash."""
    rows = [[_text(label), _text(info.get(key, "") or MISSING)]
            for label, key in pairs]
    table = Table(rows, colWidths=[5 * cm, 11 * cm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _styled_table(header, rows, widths) -> Table:
    """Grid table with a branded header row."""
    table = Table([header] + rows, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), _HAIRLINE_PT, GREY_DARK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, GREY_LIGHT]),
    ]
    table.setStyle(TableStyle(style))
    return table


def _group_rows(compiled: CompiledBoq) -> list:
    """(label, total Decimal|None, partial bool) per collection group."""
    grouped = set()
    for _label, codes in PDF_GROUPS:
        grouped.update(codes)
    out = []
    for label, codes in PDF_GROUPS:
        members = [section for section in compiled.sections
                   if (section.code in codes) or
                   (not codes and section.code not in grouped)]
        if not members:
            out.append((label, None, False, True))
            continue
        if any(section.total is None for section in members):
            total = None
            for section in members:
                if section.total is not None:
                    total = (total or Decimal("0")) + section.total
            out.append((label, total, True, False))
            continue
        total = sum((section.total for section in members),
                    Decimal("0"))
        out.append((label, total, False, False))
    return out


def _require_compiled(compiled) -> CompiledBoq:
    if not isinstance(compiled, CompiledBoq):
        raise ValidationError(
            "BOQ PDF export needs a CompiledBoq; "
            f"got {type(compiled).__name__}")
    return compiled


def build_boq_summary_pdf(compiled: CompiledBoq, info: dict) -> bytes:
    """Formal BOQ summary PDF bytes (header, groups, net total)."""
    _require_compiled(compiled)
    info = dict(info or {})
    styles = _styles()
    story = [
        Paragraph(_text("BILL OF QUANTITIES SUMMARY"),
                  styles["Title"]),
        Spacer(1, 4 * mm),
        _meta_table(info, (
            ("Company", "company_name"),
            ("Project", "project_title"),
            ("Client", "client"),
            ("Reference", "reference"),
            ("Measurement Standard", "measurement_standard"),
            ("Date", "date"),
        )),
        Spacer(1, 5 * mm),
        Paragraph(_text("Group Breakdown"), styles["Heading2"]),
    ]
    rows = []
    for label, total, partial, absent in _group_rows(compiled):
        if absent:
            cell, note = MISSING, "No such sections"
        elif total is None:
            cell, note = UNRESOLVED_TEXT, "Unresolved items present"
        elif partial:
            cell = _money_display(total)
            note = "Partial — unresolved items present"
        else:
            cell, note = _money_display(total), ""
        rows.append([_text(label), _text(cell), _text(note)])
    story.append(_styled_table(
        ["Group", "Amount", "Status"],
        rows, [6 * cm, 5 * cm, 5 * cm]))
    story.append(Spacer(1, 5 * mm))
    story.append(_styled_table(
        ["Total", "Amount"],
        [["Resolved Subtotal",
          _money_display(compiled.resolved_subtotal)],
         ["Net Total",
          _money_display(compiled.total)]],
        [6 * cm, 10 * cm]))
    if compiled.unresolved_items:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(
            _text("Unresolved items: "
                  + ", ".join(compiled.unresolved_items)),
            styles["Normal"]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(_text(GOVERNANCE_LINE), styles["Normal"]))
    buffer = BytesIO()
    _doc(buffer, "BOQ Summary").build(story)
    return buffer.getvalue()


def _valuation_dict(valuation) -> dict:
    if hasattr(valuation, "to_dict"):
        data = valuation.to_dict()
    elif isinstance(valuation, dict):
        data = valuation
    else:
        raise ValidationError(
            "IPC PDF export needs an IPCValuation (or its dict form); "
            f"got {type(valuation).__name__}")
    for field in ("contract_sum", "previous_valuation", "current_work",
                  "work_to_date", "onsite_materials", "gross_certified",
                  "retention_rate_pct", "retention_limit",
                  "retention_withheld", "advance_repaid",
                  "previous_payments", "total_deductions", "net_payable"):
        if field not in data:
            raise ValidationError(
                f"IPC valuation is missing {field!r}")
    data.setdefault("lines", ())
    data.setdefault("valuation_no", "")
    return data


def build_ipc_pdf(valuation, info: dict) -> bytes:
    """Interim Payment Certificate statement PDF bytes."""
    data = _valuation_dict(valuation)
    info = dict(info or {})
    styles = _styles()
    valuation_no = str(data.get("valuation_no", "") or "—")
    story = [
        Paragraph(_text("INTERIM PAYMENT CERTIFICATE"),
                  styles["Title"]),
        Spacer(1, 4 * mm),
        _meta_table({**info, "valuation_no": valuation_no,
                     "date": info.get("date", "")
                     or date.today().isoformat()}, (
            ("Company", "company_name"),
            ("Project", "project_title"),
            ("Client", "client"),
            ("Contract Reference", "reference"),
            ("Valuation No.", "valuation_no"),
            ("Date", "date"),
        )),
        Spacer(1, 5 * mm),
        Paragraph(_text("Executive Summary"), styles["Heading2"]),
        _styled_table(
            ["Item", "Amount"],
            [["Previous Valuation",
              _money_display(data["previous_valuation"])],
             ["Current Period Work",
              _money_display(data["current_work"])],
             ["Work Completed to Date",
              _money_display(data["work_to_date"])],
             ["On-site Materials",
              _money_display(data["onsite_materials"])],
             ["Gross Certified",
              _money_display(data["gross_certified"])]],
            [8 * cm, 8 * cm]),
        Spacer(1, 5 * mm),
    ]
    lines = data.get("lines", ()) or ()
    if lines:
        story.append(Paragraph(_text("Valued Lines"), styles["Heading2"]))
        story.append(_styled_table(
            ["Item", "Description", "Unit", "Rate", "Completed", "Value"],
            [[_text(line.get("item_no", "")),
              _text(line.get("description", "")),
              _text(line.get("unit", "")),
              _text(_money_display(line.get("rate"))),
              _text(str(line.get("completed_qty", ""))),
              _text(_money_display(line.get("line_value")))]
             for line in lines],
            [2 * cm, 5 * cm, 2 * cm, 25 * mm, 25 * mm, 25 * mm]))
        story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(_text("Financial Deductions"),
                           styles["Heading2"]))
    story.append(_styled_table(
        ["Deduction", "Amount"],
        [[f"Retention ({_text(data['retention_rate_pct'])}% "
          f"capped at {_text(_money_display(data['retention_limit']))})",
          _money_display(data["retention_withheld"])],
         ["Advance Payment Recovery",
          _money_display(data["advance_repaid"])],
         ["Less Previous Payments",
          _money_display(data["previous_payments"])],
         ["Total Deductions",
          _money_display(data["total_deductions"])]],
        [8 * cm, 8 * cm]))
    story.append(Spacer(1, 5 * mm))
    net = _styled_table(
        ["Certification", "Amount"],
        [["Net Amount Payable",
          _money_display(data["net_payable"])]],
        [8 * cm, 8 * cm])
    story.append(net)
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(_text("Sign-off"), styles["Heading2"]))
    signoff = Table(
        [["Prepared by", "Checked by", "Approved by"],
         ["", "", ""],
         ["Signature / Date", "Signature / Date", "Signature / Date"]],
        colWidths=[53 * mm, 53 * mm, 54 * mm])
    signoff.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LINEBELOW", (0, 1), (-1, 1), _HAIRLINE_PT, GREY_DARK),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(signoff)
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        _text(f"Contract Sum: {_money_display(data['contract_sum'])} | "
              f"{GOVERNANCE_LINE}"),
        styles["Normal"]))
    buffer = BytesIO()
    _doc(buffer, f"IPC {valuation_no}").build(story)
    return buffer.getvalue()


def export_boq_summary_pdf(compiled: CompiledBoq, info: dict,
                           output_path) -> str:
    """Write the BOQ summary PDF to a file; returns the path."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(build_boq_summary_pdf(compiled, info))
    return str(output)


def export_ipc_statement_pdf(valuation, info: dict,
                             output_path) -> str:
    """Write the IPC statement PDF to a file; returns the path."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(build_ipc_pdf(valuation, info))
    return str(output)
