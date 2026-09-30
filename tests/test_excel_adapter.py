"""Excel export adapter tests (Phase 11).

The compiled BOQ is the truth; these tests pin the rendering contract:
sheet structure, pricing-kind behaviour, F/G/H reconciliation columns,
metadata completeness, and formatting. openpyxl stores numerics as
IEEE-754 doubles, so value assertions compare against float() of the
compiled Decimal — display exactness comes from number formats.
"""

from decimal import Decimal

import pytest
from openpyxl import load_workbook

from qs_engine.adapters.excel.boq_workbook import (
    GOVERNANCE_BANNER,
    HEADERS,
    export_boq_to_excel,
    sanitize_sheet_name,
)
from qs_engine.boq.compiler import compile_boq
from qs_engine.boq.measurement import MeasurementRule, MeasurementStandard
from qs_engine.boq.models import (
    Boq,
    BoqItem,
    BoqSection,
    BoqSubsection,
    explicit_rate,
    provisional_sum,
    unpriced_item,
)
from qs_engine.core.assumptions import VerificationStatus
from qs_engine.core.errors import ValidationError


def sample_compiled():
    boq = Boq(
        project_ref="TEST-PROJ", boq_ref="TEST-BOQ",
        sections=(
            BoqSection(code="E", title="Earthworks", subsections=(
                BoqSubsection(code="E.1", title="Excavation", items=(
                    BoqItem(description="Bulk excavation", trade="Earthworks",
                            unit="m³", quantity=Decimal("10"),
                            pricing=explicit_rate(Decimal("100"), "test")),
                    BoqItem(description="Dewatering", trade="Earthworks",
                            unit="sum", quantity=Decimal("1"),
                            pricing=provisional_sum(Decimal("500"), "pc")),
                )),
            )),
            BoqSection(code="C", title="Concrete", subsections=(
                BoqSubsection(code="C.1", title="In-situ", items=(
                    BoqItem(description="Blinding", trade="Concrete",
                            unit="m³", quantity=Decimal("5"),
                            pricing=explicit_rate(Decimal("200"), "test"),
                            measurement=MeasurementRule(
                                standard=MeasurementStandard("CESMM", "4"),
                                rule_ref="3.4", source="TEST",
                                verification_status=(
                                    VerificationStatus.VERIFIED))),
                    BoqItem(description="Awaiting rate", trade="Concrete",
                            unit="m³", quantity=Decimal("3"),
                            pricing=unpriced_item()),
                )),
            )),
        ))
    return compile_boq(boq)


def export_sample(tmp_path, **kwargs):
    out = tmp_path / "boq.xlsx"
    params = {"project_name": "Test Project", "exported_on": "2026-09-22"}
    params.update(kwargs)
    return export_boq_to_excel(sample_compiled(), str(out), **params)


def load_sample(tmp_path, **kwargs):
    path = export_sample(tmp_path, **kwargs)
    return load_workbook(path, data_only=False)


# --- structure -------------------------------------------------------------

def test_workbook_sheets_and_headers(tmp_path):
    wb = load_sample(tmp_path)
    assert wb.sheetnames == ["Cover", "Summary", "E", "C"]
    ws = wb["E"]
    assert [ws.cell(row=2, column=c).value for c in range(1, 9)] == list(HEADERS)
    assert ws.freeze_panes == "A3"
    assert ws.column_dimensions["B"].width == 48
    assert ws.sheet_properties.pageSetUpPr.fitToPage is True


def test_sanitize_sheet_name():
    used = set()
    assert sanitize_sheet_name("E", used) == "E"
    assert sanitize_sheet_name("E", used) == "E-2"
    long_name = "A/B:C*D?E[F]G" + "x" * 40
    short = sanitize_sheet_name(long_name, used)
    assert len(short) <= 31
    assert not any(ch in short for ch in "[]:*?/\\")


def test_invalid_input_rejected(tmp_path):
    with pytest.raises(ValidationError):
        export_boq_to_excel("not-a-boq", str(tmp_path / "x.xlsx"))


# --- pricing-kind rendering ------------------------------------------------

def test_priced_row_formula_value_check(tmp_path):
    ws = load_sample(tmp_path)["E"]
    # Row 4: first item (row 3 is the subsection header).
    assert ws.cell(row=4, column=1).value == "1.1.1"
    assert ws.cell(row=4, column=3).value == float(Decimal("10"))
    assert ws.cell(row=4, column=5).value == float(Decimal("100"))
    assert ws.cell(row=4, column=6).value == "=C4*E4"
    assert ws.cell(row=4, column=7).value == float(Decimal("1000"))
    assert ws.cell(row=4, column=8).value == "=F4-G4"


def test_provisional_row_lump_values(tmp_path):
    ws = load_sample(tmp_path)["E"]
    assert ws.cell(row=5, column=2).value == "Dewatering (Provisional Sum)"
    assert ws.cell(row=5, column=6).value == float(Decimal("500"))
    assert ws.cell(row=5, column=7).value == float(Decimal("500"))
    assert ws.cell(row=5, column=8).value == "=F5-G5"


def test_unpriced_row_text_never_zero(tmp_path):
    ws = load_sample(tmp_path)["C"]
    # Row 3 subsection header, rows 4-5 items: unpriced is row 5.
    assert ws.cell(row=5, column=6).value == "UNPRICED"
    assert ws.cell(row=5, column=7).value == "UNPRICED"
    assert ws.cell(row=5, column=8).value is None


def test_section_totals_value_or_unresolved(tmp_path):
    wb = load_sample(tmp_path)
    assert wb["E"].cell(row=6, column=7).value == float(Decimal("1500"))
    assert wb["C"].cell(row=6, column=7).value == "UNRESOLVED"


def test_summary_and_cover(tmp_path):
    wb = load_sample(tmp_path)
    summary = wb["Summary"]
    assert summary.cell(row=3, column=1).value == "E"
    assert summary.cell(row=3, column=4).value == float(Decimal("1500"))
    assert summary.cell(row=4, column=4).value == "UNRESOLVED"
    assert summary.cell(row=5, column=4).value == "UNRESOLVED"
    cover = wb["Cover"]
    texts = [cover.cell(row=r, column=2).value for r in range(1, 20)]
    assert "BILL OF QUANTITIES" in [cover.cell(row=1, column=1).value]
    assert GOVERNANCE_BANNER in [cover.cell(row=2, column=1).value]
    assert "TEST-PROJ" in texts
    assert "TEST-BOQ" in texts
    assert "1 UNRESOLVED ITEM(S)" in texts
    assert "2.1.2" in texts  # unresolved item listed
    assert "CESMM 4: 3.4" in texts  # measurement rules cited
    assert any("CIVOLINK QS Engine" in str(t) for t in texts if t)


# --- formatting & precision ------------------------------------------------

def test_number_formats(tmp_path):
    ws = load_sample(tmp_path)["E"]
    assert ws.cell(row=4, column=3).number_format == "#,##0.000"
    assert ws.cell(row=4, column=5).number_format == "#,##0.00"
    assert ws.cell(row=4, column=6).number_format == "#,##0.00"
    assert ws.cell(row=4, column=7).number_format == "#,##0.00"
    assert ws.cell(row=4, column=8).number_format == "#,##0.00"


def test_money_precision_exact_doubles(tmp_path):
    # 3 x 10.005 = 30.015: stored as the nearest double, displayed exact.
    boq = Boq(project_ref="P", boq_ref="B", sections=(
        BoqSection.single("E", "Earthworks", (
            BoqItem(description="Precise", trade="T", unit="m³",
                    quantity=Decimal("3"),
                    pricing=explicit_rate(Decimal("10.005"), "t")),
        )),
    ))
    out = tmp_path / "precise.xlsx"
    export_boq_to_excel(compile_boq(boq), str(out))
    ws = load_workbook(str(out), data_only=False)["E"]
    assert ws.cell(row=4, column=7).value == float(Decimal("30.015"))
    assert ws.cell(row=4, column=7).number_format == "#,##0.00"
    assert ws.cell(row=4, column=6).value == "=C4*E4"
