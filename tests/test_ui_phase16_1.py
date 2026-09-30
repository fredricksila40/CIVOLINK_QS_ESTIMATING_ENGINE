"""Phase 16.1 terminology, data-discipline, and cleanup tests: headless.

Pins the UI-only Quantity Surveying terminology mapping, the
no-invented-values discipline (no hardcoded densities, no nominal mix
inference, no price library), the BOQ document-data estimate source,
and the hooks length-addition contract. Backend contracts (parser
grammars, DTO shapes, controller signatures, master-data keys) are
asserted unchanged by the untouched pre-existing suites.
"""

import inspect

import pytest

from qs_engine.core.errors import ValidationError
from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.ui import views


def repo():
    return MasterDataRepository()


def _compiled_fixture():
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
        project_ref="P16", boq_ref="B16",
        sections=(
            BoqSection(code="C", title="Concrete", subsections=(
                BoqSubsection(code="C.1", title="In-situ", items=(
                    BoqItem(description="Blinding", trade="Concrete",
                            unit="m\u00b3", quantity=Decimal("5"),
                            pricing=explicit_rate(Decimal("200"), "test")),
                )),
            )),
            BoqSection(code="M", title="Masonry", subsections=(
                BoqSubsection(code="M.1", title="Blockwork", items=(
                    BoqItem(description="Awaiting rate", trade="Masonry",
                            unit="piece", quantity=Decimal("8"),
                            pricing=unpriced_item()),
                )),
            )),
        ))
    return compile_boq(boq)


def _stub_repo(records_by_domain):
    from types import SimpleNamespace
    return SimpleNamespace(
        list=lambda domain: list(records_by_domain.get(domain, ())))


# --- terminology mapping (UI labels only) -----------------------------------------

def test_concrete_grade_and_rate_unit_labels():
    concrete = dict(views.PANEL_SPECS["concrete"][2])
    assert concrete["class_key"] == "Concrete Grade"
    assert "class_key" in concrete  # backend field key untouched
    rates = dict(views.PANEL_SPECS["rates"][2])
    assert rates["work_unit"] == "Rate Unit"
    assert "work_unit" in rates  # backend field key untouched


def test_takeoff_reference_heading():
    assert views.SCHEDULE_COLUMNS["ref"][0] == "Take-off Reference"
    assert "ref" in views.SCHEDULE_COLUMNS  # column key untouched


def test_planning_quantities_badge_reframed():
    source = inspect.getsource(views._summary_card)
    assert "Planning Quantities" in source
    assert "are maintained as project " in source
    assert "automatically assigned to " in source
    assert "direct BOQ items" in source
    assert "Planning Context" not in source
    assert "Unmapped" not in source


def test_rate_grid_headers_use_domain_terms():
    source = inspect.getsource(views.build_rates_page)
    for heading in ("Resource Code", "Quantity", "Unit", "Unit Rate",
                    "Wastage %", "Description", "Kind"):
        assert heading in source
    assert "Resource Key / ID" not in source
    assert "Quantity / Hours" not in source
    assert "Unit Rate / Price" not in source


def test_developer_terms_absent_from_views():
    source = inspect.getsource(views)
    assert "Take-off ref" not in source  # superseded by Take-off Reference
    assert "Work unit" not in source  # superseded by Rate Unit
    assert "Raw DSL" not in source  # superseded by Advanced Input
    assert "Advanced / Raw" not in source
    assert "Compile Branded Word Document" not in source
    assert "Document Generator & Template Hub" not in source
    assert "Grade (class key)" not in source


def test_no_hardcoded_density_numbers_in_views():
    source = inspect.getsource(views)
    for invented in ("1440", "1600", "1500"):
        assert invented not in source


# --- concrete data discipline -------------------------------------------------------

def test_master_density_reference_blank_until_verified():
    blank = {field: (None, False)
             for field, _label in views.CONCRETE_DENSITY_FIELDS}
    assert views.master_density_reference(repo()) == blank
    assert views.master_density_reference(None) == blank


def test_master_density_reference_accepts_verified_values():
    stub = _stub_repo({"concrete_classes": [
        {"key": "class_c20", "class_name": "C20",
         "cement_density_kg_per_m3": 1440,
         "sand_density_kg_per_m3": None,
         "aggregate_density_kg_per_m3": 1500,
         "verification_status": "VERIFIED"},
        {"key": "class_x", "class_name": "CX",
         "cement_density_kg_per_m3": 9999,
         "verification_status": "NEEDS_VERIFICATION"},
    ]})
    reference = views.master_density_reference(stub)
    assert reference["cement_density_kg_per_m3"] == ("1440", True)
    assert reference["aggregate_density_kg_per_m3"] == ("1500", True)
    assert reference["sand_density_kg_per_m3"] == (None, False)


def test_density_field_status_provenance_branches():
    stub = _stub_repo({"concrete_classes": [
        {"key": "class_c20", "class_name": "C20",
         "cement_density_kg_per_m3": 1440,
         "verification_status": "VERIFIED"},
    ]})
    assert views.density_field_status(
        "cement_density_kg_per_m3", "1500", stub) == (
        "Project override: 1500")
    assert views.density_field_status(
        "cement_density_kg_per_m3", "", stub) == "Master verified: 1440"
    assert views.density_field_status(
        "sand_density_kg_per_m3", "", stub) == "\u26a0 Needs Verification"
    assert views.density_field_status(
        "cement_density_kg_per_m3", "", repo()) == (
        "\u26a0 Needs Verification")


def test_nominal_mix_reference_not_available_without_data():
    assert views.nominal_mix_reference("class_c20", repo()) is None
    assert views.nominal_mix_reference("C20", repo()) is None
    assert views.nominal_mix_reference("", repo()) is None
    assert views.nominal_mix_reference("class_c20", None) is None


def test_nominal_mix_reference_displayed_reference_only():
    stub = _stub_repo({"concrete_classes": [
        {"key": "class_c20", "class_name": "C20",
         "nominal_mix": "1:2:4",
         "verification_status": "VERIFIED"},
    ]})
    assert views.nominal_mix_reference("class_c20", stub) == (
        "1:2:4", True)
    assert views.nominal_mix_reference("C20", stub) == ("1:2:4", True)


def test_concrete_supplement_lines_honest_on_shipped_data():
    lines = views.concrete_supplement_lines("class_c20", {}, repo())
    assert lines[0] == "Nominal Mix Reference: Not available"
    assert "Needs Verification" in lines[1]
    assert "1440" not in lines[1]


def test_concrete_supplement_lines_track_provenance():
    stub = _stub_repo({"concrete_classes": [
        {"key": "class_c20", "class_name": "C20",
         "nominal_mix": "1:2:4",
         "cement_density_kg_per_m3": 1440,
         "verification_status": "VERIFIED"},
    ]})
    lines = views.concrete_supplement_lines(
        "class_c20", {"cement_density_kg_per_m3": "1500"}, stub)
    assert lines[0] == "Nominal Mix Reference: 1:2:4 (\u26a0 Reference Only)"
    assert "cement 1500 (project override)" in lines[1]


def test_build_concrete_page_wiring():
    assert views.PAGES["concrete"] is views.build_concrete_page
    source = inspect.getsource(views.build_concrete_page)
    assert "Engineering Reference" in source
    assert "concrete_supplement_lines" in source


def test_project_setup_engineering_inputs_pane():
    source = inspect.getsource(views.build_project_page)
    assert "Engineering Inputs (Settings)" in source
    assert "CONCRETE_DENSITY_FIELDS" in source
    assert "density_field_status" in source


# --- hooks contract: length addition, never a count ----------------------------------

def test_hooks_interpreted_as_length_addition_per_bar():
    from qs_engine.ui.controllers import rebar_controller
    result = rebar_controller(
        [{"bar_key": "Y12", "count": "1", "length_per_bar_m": "6",
          "laps_per_bar": "0", "lap_length_m": "0",
          "hook_extra_per_bar_m": "0.5", "mass_kg_per_m": "2"}],
        "0", None, repo())
    assert type(result).__name__ == "RebarView"
    # per_bar = 6 + 0 x 0 + 0.5 -> total 6.5 m.
    assert result.total_length_m == "6.5"


# --- rate grid unit context never corrupts the contract -------------------------------

def test_format_rate_line_ignores_unit_entry():
    base = {"kind": "material", "key": "cement", "qty": "2",
            "price": "100", "waste": "10", "desc": "C"}
    assert views.format_rate_line(dict(base, unit="bag")) == (
        views.format_rate_line(base))
    assert views.parse_rate_lines(
        views.format_rate_line(dict(base, unit="bag")) + "\n")[0][
        "material_key"] == "cement"


# --- estimate from BOQ document data -----------------------------------------------------

def test_estimate_cost_groups_accepts_document_payload():
    from qs_engine.adapters.document.payload import synthesize_boq_payload
    compiled = _compiled_fixture()
    payload = synthesize_boq_payload(
        compiled, document_title="T", purpose="P")
    from_compiled = views.estimate_cost_groups(compiled)
    assert views.estimate_cost_groups(payload) == from_compiled
    assert views.estimate_cost_groups(payload.to_dict()) == from_compiled


def test_estimate_cost_groups_rejects_unsupported_sources():
    with pytest.raises(ValidationError):
        views.estimate_cost_groups("not-a-boq")
    with pytest.raises(ValidationError):
        views.estimate_cost_groups({"no": "sections"})


def test_estimate_dashboard_labels_use_domain_terms():
    assert views.ESTIMATE_GROUP_ORDER[0] == (
        "materials", "Direct Materials")
    source = inspect.getsource(views.build_estimate_page)
    assert "Overheads/Markups" in source
    assert "Tender Value" in source


# --- materials catalogue discipline -------------------------------------------------------

def test_materials_columns_without_price_library():
    assert set(views.MATERIALS_COLUMNS) == {
        "code", "name", "category", "subcategory", "unit", "density",
        "wastage", "status"}
    headings = [heading for _key, (heading, _w)
                in views.MATERIALS_COLUMNS.items()]
    assert "Material Code" in headings
    assert "Default Unit" in headings
    assert "Verification Status" in headings
    assert not any("rice" in heading for heading in headings)


def test_material_rows_show_em_dash_for_nulls():
    rows = views.material_catalogue_rows(repo())
    assert len(rows) == 23
    assert all(len(row) == 8 for row in rows)
    assert all(row[3] == "\u2014" for row in rows)  # no subcategory field
    assert all(row[5] == "\u2014" for row in rows)  # null densities
    assert all(row[6] == "\u2014" for row in rows)  # null wastage defaults
