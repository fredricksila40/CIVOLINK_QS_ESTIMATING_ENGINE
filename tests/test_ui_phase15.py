"""Phase 15 Corporate Document & Template Manager tests: headless.

Covers the company-profile JSON handlers, the template selection hub
constants, the branded Word/PDF export pipeline (DTO + profile into
scripts/document_base.py, scripts/quotation_word.py,
scripts/invoice_word.py), the corpdoc navigation promotion, and the
Phase 14.2 geometry retention. Widget construction itself needs a
display and stays display-guarded; everything else runs on headless CI.
Existing tests are updated only where the nav contract intentionally
changed (corpdoc placeholder -> working page).
"""

import inspect
import json

import pytest

from qs_engine.adapters.document.company_profile import (
    COMPANY_PROFILE_FIELDS,
    DEFAULT_COMPANY_PROFILE,
    load_company_profile,
    resolve_profile_path,
    save_company_profile,
    validate_company_profile,
)
from qs_engine.adapters.document.word_export import (
    CORPORATE_TEMPLATES,
    DOCUMENT_KINDS,
    TEMPLATE_DESCRIPTIONS,
    export_branded_document,
    resolve_output_dir,
    template_label,
)
from qs_engine.core.errors import ValidationError
from qs_engine.ui import controllers, views


def _profile(**overrides):
    base = {
        "business_name": "Test Corp Ltd",
        "registration_tax_id": "TAX-001",
        "contact_phone": "+254 700 000 000",
        "email": "info@testcorp.example",
        "physical_address": "Nairobi",
        "legal_disclaimers": "Test disclaimers.",
        "logo_path": "",
        "brand_accent_color": "#123ABC",
    }
    base.update(overrides)
    return base


def _compiled_boq():
    from decimal import Decimal
    from qs_engine.boq.compiler import compile_boq
    from qs_engine.boq.models import (
        Boq,
        BoqItem,
        BoqSection,
        BoqSubsection,
        explicit_rate,
        unpriced_item,
    )
    boq = Boq(
        project_ref="P15", boq_ref="B15",
        sections=(
            BoqSection(code="C", title="Concrete", subsections=(
                BoqSubsection(code="C.1", title="In-situ", items=(
                    BoqItem(description="Blinding", trade="Concrete",
                            unit="m\u00b3", quantity=Decimal("5"),
                            pricing=explicit_rate(Decimal("200"), "test")),
                    BoqItem(description="Awaiting rate", trade="Concrete",
                            unit="m\u00b3", quantity=Decimal("3"),
                            pricing=unpriced_item()),
                )),
            )),
        ))
    return compile_boq(boq)


def _docx_texts(path):
    docx = pytest.importorskip("docx")
    doc = docx.Document(str(path))
    texts = [paragraph.text for paragraph in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                texts.append(cell.text)
    return "\n".join(texts)


# --- company profile handlers -------------------------------------------------

def test_profile_fields_cover_identity_requirements():
    assert set(COMPANY_PROFILE_FIELDS) == {
        "business_name", "registration_tax_id", "contact_phone", "email",
        "physical_address", "legal_disclaimers", "logo_path",
        "brand_accent_color",
    }


def test_profile_editor_labels_cover_identity_fields():
    assert set(views.PROFILE_FIELD_LABELS) >= (
        set(COMPANY_PROFILE_FIELDS) - {"legal_disclaimers"})
    assert views.PROFILE_FIELD_LABELS["business_name"] == "Business Name"
    assert "Tax ID" in views.PROFILE_FIELD_LABELS["registration_tax_id"]
    assert ".png" in views.PROFILE_FIELD_LABELS["logo_path"]


def test_load_missing_file_returns_defaults(tmp_path):
    loaded = load_company_profile(tmp_path / "no-such-file.json")
    assert loaded == DEFAULT_COMPANY_PROFILE


def test_save_and_load_round_trip(tmp_path):
    target = tmp_path / "config" / "company_profile.json"
    saved = save_company_profile(_profile(), target)
    assert saved == str(target)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["business_name"] == "Test Corp Ltd"
    assert data["brand_accent_color"] == "#123ABC"
    assert load_company_profile(target)["email"] == "info@testcorp.example"


def test_save_validates_colour_and_logo():
    with pytest.raises(ValidationError):
        save_company_profile(_profile(brand_accent_color="blue"))
    with pytest.raises(ValidationError):
        save_company_profile(_profile(logo_path="logo.svg"))
    with pytest.raises(ValidationError):
        validate_company_profile("not-a-mapping")


def test_colour_normalised_and_unknown_keys_dropped(tmp_path):
    cleaned = validate_company_profile(
        _profile(brand_accent_color="#abcdef", future_field="kept-out"))
    assert cleaned["brand_accent_color"] == "#ABCDEF"
    assert "future_field" not in cleaned


def test_default_profile_path_points_at_engine_config():
    resolved = resolve_profile_path()
    assert resolved.name == "company_profile.json"
    assert resolved.parent.name == "config"
    assert load_company_profile()["business_name"]  # real file readable


# --- template selection hub ----------------------------------------------------

def test_corporate_templates_exact():
    assert CORPORATE_TEMPLATES == (
        ("edmolt", "EDMOLT Construction Template"),
        ("civolink", "CIVOLINK Standard BOQ Template"),
        ("custom", "Custom Corporate Template"),
    )
    assert set(TEMPLATE_DESCRIPTIONS) == {"edmolt", "civolink", "custom"}
    assert DOCUMENT_KINDS == (("quotation", "Quotation"),
                              ("invoice", "Invoice"))
    assert template_label("edmolt") == "EDMOLT Construction Template"
    with pytest.raises(ValidationError):
        template_label("no-such-template")


def test_output_dir_defaults_to_engine_output():
    assert resolve_output_dir().name == "output"


# --- export pipeline ------------------------------------------------------------

def test_quotation_export_branded_docx(tmp_path):
    pytest.importorskip("docx")
    result = export_branded_document(
        _compiled_boq(), profile=_profile(), template="civolink",
        document_kind="quotation", output_dir=tmp_path)
    assert result["pdf_path"] is None
    texts = _docx_texts(result["docx_path"])
    assert "Test Corp Ltd" in texts
    assert "Blinding" in texts
    assert "\u2014" in texts  # unpriced amount: explicit, never zero
    assert "UNRESOLVED" in texts
    assert "QS Engine = Source of Truth" in texts


def test_edmolt_template_and_invoice_kind(tmp_path):
    pytest.importorskip("docx")
    result = export_branded_document(
        _compiled_boq(), profile=_profile(), template="edmolt",
        document_kind="invoice", output_dir=tmp_path)
    texts = _docx_texts(result["docx_path"])
    assert "Test Corp Ltd" in texts
    assert "Invoice No.:" in texts


def test_export_to_pdf_toggle_writes_pdf_alongside_docx(tmp_path):
    pytest.importorskip("docx")
    result = export_branded_document(
        _compiled_boq(), profile=_profile(), template="civolink",
        document_kind="quotation", output_dir=tmp_path, export_pdf=True)
    assert result["pdf_path"] is not None
    pdf = open(result["pdf_path"], "rb").read()
    assert pdf.startswith(b"%PDF")
    assert "Blinding" in pdf.decode("latin-1", errors="replace")


def test_custom_template_merge_tags(tmp_path):
    docx = pytest.importorskip("docx")
    template_path = tmp_path / "custom.docx"
    doc = docx.Document()
    doc.add_paragraph("{{business_name}} :: {{document_title}} :: "
                      "{{grand_total}} :: {{project_ref}}")
    doc.save(str(template_path))
    result = export_branded_document(
        _compiled_boq(), profile=_profile(), template="custom",
        document_kind="quotation", output_dir=tmp_path,
        custom_template_path=str(template_path))
    texts = _docx_texts(result["docx_path"])
    assert "Test Corp Ltd" in texts
    assert "{{business_name}}" not in texts
    assert "{{grand_total}}" not in texts
    assert "Item No." in texts  # BOQ table appended after the tags


def test_custom_template_missing_file_rejected(tmp_path):
    pytest.importorskip("docx")
    with pytest.raises(ValidationError):
        export_branded_document(
            _compiled_boq(), profile=_profile(), template="custom",
            output_dir=tmp_path,
            custom_template_path=str(tmp_path / "missing.docx"))


def test_export_rejects_bad_inputs(tmp_path):
    with pytest.raises(ValidationError):
        export_branded_document(template="civolink",
                                output_dir=tmp_path)  # no BOQ, no payload
    with pytest.raises(ValidationError):
        export_branded_document(_compiled_boq(), template="nope",
                                output_dir=tmp_path)
    with pytest.raises(ValidationError):
        export_branded_document(_compiled_boq(), document_kind="receipt",
                                output_dir=tmp_path)


def test_rate_appendix_travels_into_document(tmp_path):
    pytest.importorskip("docx")
    from qs_engine.adapters.document.payload import synthesize_rate_payload
    from qs_engine.master_data.repository import MasterDataRepository
    from qs_engine.rates.engine import (
        composite_rate,
        material_component,
    )
    from decimal import Decimal
    rate = composite_rate(
        components=[material_component(
            material_key="river_sand", qty_per_unit=Decimal("1"),
            unit_price=Decimal("90"),
            repository=MasterDataRepository())],
        markups=[("profit", Decimal("10"))],
        element="test rate", work_unit="m\u00b3")
    rate_payload = synthesize_rate_payload(
        rate, document_title="Rate sheet", purpose="Test")
    result = export_branded_document(
        _compiled_boq(), profile=_profile(), rate=rate_payload,
        output_dir=tmp_path)
    assert "Rate Build-Up Appendix" in _docx_texts(result["docx_path"])


def test_branded_document_controller_success_and_failure(tmp_path):
    pytest.importorskip("docx")
    from qs_engine.ui.viewmodels import ExportView
    ok_result = controllers.branded_document_controller(
        _compiled_boq(), profile=_profile(), template="civolink",
        output_dir=str(tmp_path))
    assert isinstance(ok_result, ExportView)
    assert ok_result.path.endswith(".docx")
    assert "civolink" in ok_result.detail
    bad_result = controllers.branded_document_controller(
        template="civolink", output_dir=str(tmp_path))
    assert type(bad_result).__name__ == "ErrorView"
    assert "compiled BOQ" in bad_result.message


# --- navigation promotion + geometry retention -----------------------------------

def test_corpdoc_promoted_to_working_page():
    kinds = {key: kind for _group, items in views.NAV_GROUPS
             for key, _label, kind in items}
    assert kinds["corpdoc"] == "page"
    assert views.PAGES["corpdoc"] is views.build_corpdoc_page
    assert "corpdoc" not in views.PLACEHOLDER_COPY
    assert views.CORPDOC_GUIDANCE.strip()


def test_scrollable_frame_geometry_retained():
    source = inspect.getsource(views.ScrollableFrame)
    assert 'pack(side="right"' in source  # far-right scrollbar docking
    assert 'fill="both"' in source  # full workspace container expansion
    assert "expand=True" in source


def test_corpdoc_page_uses_dual_pane_expansion():
    source = inspect.getsource(views.build_corpdoc_page)
    assert "Company Profile Editor" in source
    # Phase 16.1: implementation terms cleaned to domain language.
    assert "Document Output" in source
    assert "Document Generator & Template Hub" not in source
    assert "Generate Branded Document" in source
    assert "Compile Branded Word Document" not in source
    assert "Export to PDF" in source
    assert "fill=\"both\", expand=True" in source
