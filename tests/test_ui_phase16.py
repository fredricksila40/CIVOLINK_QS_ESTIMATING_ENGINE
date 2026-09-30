"""Phase 16 UI/UX modernization tests: headless, no widgets.

Covers the concrete grade dropdown (master-data key mapping), Project
Setup density defaults with live override plumbing, the rebar/rate grid
serializers and their parser round-trips, the materials catalogue rows,
the estimate cost-group roll-up, and the materials/estimate navigation
promotion. Widget construction needs a display and stays
display-guarded; parser and adapter boundaries are untouched.
"""

import inspect
from types import SimpleNamespace

import pytest

from qs_engine.core.errors import ValidationError
from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.ui import controllers, views
from qs_engine.ui.session import TakeoffSession


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


# --- concrete grade dropdown ----------------------------------------------------

def test_standard_grades_lists_spec_display_set():
    assert views.STANDARD_CONCRETE_GRADES == (
        "C15", "C20", "C25", "C30", "C35", "C40")


def test_grade_choices_map_directly_to_master_keys():
    choices = views.concrete_grade_choices(repo())
    assert choices, "dropdown must offer the verified table grades"
    for grade in choices:
        key = views.resolve_concrete_class_key(grade, repo())
        assert repo().get("concrete_classes", key)["class_name"] == grade
    # C35/C40 have no verified table records, so the dropdown honestly
    # omits them instead of offering choices the engine must reject.
    assert "C35" not in choices and "C40" not in choices


def test_grade_choices_fall_back_without_repository():
    assert views.concrete_grade_choices(None) == (
        views.STANDARD_CONCRETE_GRADES)


def test_resolve_passes_keys_through_verbatim():
    assert views.resolve_concrete_class_key("class_c20", repo()) == (
        "class_c20")
    assert views.resolve_concrete_class_key("C99", repo()) == "C99"
    assert views.resolve_concrete_class_key("", repo()) == ""


def test_field_choices_only_for_grade_selector():
    assert (views.field_choices("concrete", "class_key", repo())
            == views.concrete_grade_choices(repo()))
    assert views.field_choices("concrete", "length", repo()) is None
    assert views.field_choices("masonry", "unit_key", repo()) is None
    assert (views.translate_field_value(
        "concrete", "class_key", "C20", repo()) == "class_c20")
    assert (views.translate_field_value(
        "concrete", "length", "C20", repo()) == "C20")


def test_concrete_spec_labels_carry_units():
    fields = dict(views.PANEL_SPECS["concrete"][2])
    assert "(m)" in fields["length"]
    assert "(m)" in fields["width"]
    assert "(m)" in fields["thickness"]
    assert "Concrete Grade" in fields["class_key"]


# --- engineering inputs (no hardcoded defaults) --------------------------------------
#
# Phase 16.1 data discipline: the UI bakes in no universal density
# numbers. Entries stay blank (engine/master default) unless the
# estimator sets a project-level override with provenance.

def test_density_fields_cover_dry_constituents_without_defaults():
    assert views.CONCRETE_DENSITY_FIELDS == (
        ("cement_density_kg_per_m3", "Cement Density (kg/m\u00b3)"),
        ("sand_density_kg_per_m3", "Sand Density (kg/m\u00b3)"),
        ("aggregate_density_kg_per_m3", "Aggregates Density (kg/m\u00b3)"),
    )
    assert not hasattr(views, "CONCRETE_DENSITY_DEFAULTS")


def test_session_density_overrides_mapping():
    assert views.session_density_overrides({}) == {}
    assert views.session_density_overrides(None) == {}
    project = {"name": "Demo",
               "cement_density_kg_per_m3": "1440",
               "sand_density_kg_per_m3": "  ",
               "aggregate_density_kg_per_m3": "1500"}
    assert views.session_density_overrides(project) == {
        "cement_density_kg_per_m3": "1440",
        "aggregate_density_kg_per_m3": "1500"}


def test_density_keys_drive_engineering_output():
    base = {"length": "1", "width": "1", "thickness": "1",
            "class_key": "class_c20"}
    full = {"dry_factor": "2", "cement_ratio": "1", "sand_ratio": "1",
            "aggregate_ratio": "2", "wc_ratio": "0.5",
            "water_density_kg_per_L": "1", "bag_mass_kg": "50"}
    light = dict(full, cement_density_kg_per_m3="1000",
                 sand_density_kg_per_m3="1000",
                 aggregate_density_kg_per_m3="1000")
    heavy = dict(full, cement_density_kg_per_m3="1440",
                 sand_density_kg_per_m3="1600",
                 aggregate_density_kg_per_m3="1500")
    assert (controllers.concrete_controller(base, repo(), light).bags_exact
            != controllers.concrete_controller(
                base, repo(), heavy).bags_exact)


def test_session_densities_flow_into_concrete_binding():
    session = TakeoffSession()
    session.save_project(name="Demo",
                         cement_density_kg_per_m3="1440",
                         sand_density_kg_per_m3="1600",
                         aggregate_density_kg_per_m3="1500")
    app = SimpleNamespace(session=session)
    bound = views.concrete_controller_with_session_densities(app)
    result = bound({"length": "1", "width": "1", "thickness": "1",
                    "class_key": "class_c20"}, repo())
    # Densities alone cannot satisfy the null-ratio skeleton table, so
    # the engine fails closed on ratios — never on the density inputs.
    assert type(result).__name__ == "ErrorView"
    assert "cement_density" not in result.message


def test_takeoff_page_accepts_controller_override():
    params = inspect.signature(views.build_takeoff_page).parameters
    assert params["controller"].default is None
    assert params["add_enabled"].default is True
    assert params["summary_spec"].default is None


# --- rebar grid serializer ---------------------------------------------------------

def test_format_rebar_line_exact_dsl_and_round_trip():
    line = views.format_rebar_line({
        "bar": "Y12", "count": "10", "length": "6", "laps": "2",
        "lap": "1.0", "hooks": "0.3", "mass": "2"})
    assert line == "Y12 | count=10 | len=6 | laps=2 | lap=1.0 | hooks=0.3 | mass=2"
    parsed = views.parse_rebar_lines(line + "\n")
    assert parsed == [{"bar_key": "Y12", "count": "10",
                       "length_per_bar_m": "6", "laps_per_bar": "2",
                       "lap_length_m": "1.0", "hook_extra_per_bar_m": "0.3",
                       "mass_kg_per_m": "2"}]


def test_format_rebar_line_skips_blanks_and_validates():
    assert views.format_rebar_line({"bar": "Y16", "count": "4", "length": "",
                                    "laps": "", "lap": "", "hooks": "",
                                    "mass": ""}) == "Y16 | count=4"
    with pytest.raises(ValidationError):
        views.format_rebar_line("not-a-mapping")


def test_rebar_bar_sizes_match_master_table():
    assert views.rebar_bar_sizes(repo()) == (
        "Y8", "Y10", "Y12", "Y16", "Y20", "Y25", "Y32")
    assert views.rebar_bar_sizes(None) == views.STANDARD_REBAR_BARS


def test_rebar_grid_columns_carry_explicit_units():
    headings = dict(views.REBAR_GRID_COLUMNS)
    assert headings["length"] == "Cut Length (m)"
    assert headings["mass"] == "Unit Mass (kg/m)"
    assert headings["bar"] == "Designation"
    assert headings["size"] == "Diameter (mm)"
    assert headings["members"] == "No. of Members"
    assert headings["extra"] == "Lap/Bend Extra (m)"
    assert headings["weight"] == "Weight (kg)"
    # BBS grid folds laps into a length addition; the full laps/lap/
    # hooks/count grammar stays available through Advanced Input.
    assert "laps" not in headings
    assert "lap" not in headings
    assert "hooks" not in headings
    assert "count" not in headings


def test_rebar_page_uses_grid_and_raw_expander():
    source = inspect.getsource(views.build_rebar_page)
    assert "REBAR_GRID_COLUMNS" in source
    # Phase 16.1: developer terms cleaned to "Advanced Input".
    assert "Advanced Input" in source
    assert "Advanced / Raw DSL Input" not in source
    assert "rebar_row_inputs_to_dsl" in source
    # "Designation" heading is sourced from REBAR_GRID_COLUMNS (rendered
    # as a grid heading label via ttk.Label(grid_host, text=heading)),
    # not a literal in the function body — so verify it through the
    # constant.
    assert "Designation" in dict(views.REBAR_GRID_COLUMNS).values()


def test_rebar_designation_compose():
    assert views.rebar_designation("H (500 MPa)", "12") == "H12"
    assert views.rebar_designation("Y (460 MPa)", "10") == "Y10"
    assert views.rebar_designation("R (250 MPa)", "8") == "R8"
    assert views.rebar_designation("B (Mesh)", "16") == "B16"
    assert views.rebar_designation("Custom", "12") == ""
    assert views.rebar_designation("", "12") == ""
    assert views.rebar_designation("Y (460 MPa)", "") == ""


def test_rebar_unit_mass_never_auto_generated():
    # E-01 fix: the D^2/162 auto-fill is gone. Unit Mass is an
    # estimator entry; the engine resolves blank mass fail-closed
    # (explicit input, verified table value, or density formula).
    assert not hasattr(views, "rebar_unit_mass_for_diameter")
    page_source = inspect.getsource(views.build_rebar_page)
    assert "rebar_unit_mass_for_diameter" not in page_source
    assert "D\u00b2/162" not in inspect.getsource(views)


def test_rebar_row_totals_display_only():
    assert views.rebar_row_totals("2", "10", "6", "0.5", "0.889") == (
        "20", "6.5", "115.57")
    assert views.rebar_row_totals("", "10", "6", "", "0.889")[0] == "10"
    assert views.rebar_row_totals("", "", "", "", "") == ("", "", "")
    assert views.rebar_row_totals("2", "x", "6", "", "0.889") == (
        "", "", "")


def test_rebar_row_inputs_to_dsl_with_comments():
    lines = views.rebar_row_inputs_to_dsl({
        "member": "Slab S1", "mark": "01", "bar": "Y12",
        "members": "2", "bars": "10", "length": "6", "extra": "0.5",
        "mass": "0.889"})
    assert lines == ["# Slab S1 / 01",
                     "Y12 | count=20 | len=6.5 | mass=0.889"]
    assert views.rebar_row_inputs_to_dsl({
        "member": "", "mark": "", "bar": "",
        "members": "1", "bars": "", "length": "", "extra": "",
        "mass": ""}) == []
    assert views.rebar_row_inputs_to_dsl({
        "member": "Slab S1", "mark": "", "bar": "",
        "members": "1", "bars": "", "length": "", "extra": "",
        "mass": ""}) == []


def _display_root():
    tk = pytest.importorskip("tkinter")
    try:
        return tk.Tk()
    except tk.TclError:
        pytest.skip("no display")


def _find_button(widget, text):
    for child in widget.winfo_children():
        if ("Button" in child.winfo_class()
                and child.cget("text") == text):
            return child
        found = _find_button(child, text)
        if found is not None:
            return found
    return None


def test_rebar_bbs_row_end_to_end():
    root = _display_root()
    from qs_engine.ui.views import QSApp
    app = QSApp()
    app.show("rebar")
    app.update_idletasks()
    body = app.workspace.interior

    def grid_host():
        found = []

        def walk(widget):
            for child in widget.winfo_children():
                try:
                    texts = [c.cget("text")
                             for c in child.winfo_children()
                             if c.winfo_class() == "TLabel"]
                except Exception:
                    texts = []
                if "Designation" in texts:
                    found.append(child)
                walk(child)

        walk(body)
        return found[0]

    def row_cells(host, row_index):
        out = {}
        for child in host.winfo_children():
            info = child.grid_info()
            if info and int(info["row"]) == row_index:
                out[int(info["column"])] = child
        return out

    host = grid_host()
    row = row_cells(host, 1)
    # Columns: 0 member, 1 mark, 2 grade, 3 size, 4 bar, 5 members,
    # 6 bars, 7 length, 8 extra, 9 mass, 10 weight readout.
    assert row[4].get() == "Y12"
    # E-01: Unit Mass starts blank — no D^2/162 value is ever written.
    assert row[9].get() == ""
    assert row[5].get() == "1"
    row[2].set("H (500 MPa)")
    row[2].event_generate("<<ComboboxSelected>>")
    app.update_idletasks()
    assert row[4].get() == "H12"
    assert row[9].get() == ""   # grade change never touches Unit Mass
    row[3].set("16")
    row[3].event_generate("<<ComboboxSelected>>")
    app.update_idletasks()
    assert row[4].get() == "H16"
    assert row[9].get() == ""   # diameter change never touches Unit Mass
    row[0].insert(0, "Slab S1")
    row[1].insert(0, "01")
    row[5].delete(0, "end")
    row[5].insert(0, "2")
    row[6].insert(0, "10")
    row[7].insert(0, "6")
    row[8].insert(0, "0.5")
    # The estimator enters Unit Mass explicitly (no auto-fill to rely on).
    row[9].insert(0, "0.889")
    row[3].set("12")
    row[3].event_generate("<<ComboboxSelected>>")
    app.update_idletasks()
    assert row[10].cget("text") == "115.57"
    waste_entry = None
    for child in body.winfo_children():
        if child.winfo_class() != "TFrame":
            continue
        labels = [c.cget("text") for c in child.winfo_children()
                  if c.winfo_class() == "TLabel"]
        if "Wastage %:" in labels:
            entries = [c for c in child.winfo_children()
                       if c.winfo_class() == "TEntry"]
            waste_entry = entries[0]
    assert waste_entry is not None
    waste_entry.insert(0, "0")
    row[2].set("Y (460 MPa)")
    row[2].event_generate("<<ComboboxSelected>>")
    app.update_idletasks()
    assert row[4].get() == "Y12"
    _find_button(body, "Calculate Schedule").invoke()
    app.update_idletasks()
    outputs = [c for c in body.winfo_children()
               if c.winfo_class() == "Text"
               and str(c.cget("height")) == "8"]
    assert outputs, "result output missing"
    assert "115.57" in outputs[0].get("1.0", "end")
    row[2].set("H (500 MPa)")
    row[2].event_generate("<<ComboboxSelected>>")
    app.update_idletasks()
    _find_button(body, "Calculate Schedule").invoke()
    app.update_idletasks()
    messages = [c.cget("text") for c in body.winfo_children()
                if c.winfo_class() == "TLabel"
                and "H12" in str(c.cget("text"))]
    assert any("Unknown key" in text for text in messages), (
        "unknown designation must fail closed with an honest message")
    app.destroy()
    root.destroy()


# --- rate grid serializer ------------------------------------------------------------

def test_rate_component_kinds_per_spec():
    assert views.RATE_COMPONENT_KINDS == (
        "material", "labour", "plant", "subcontract")


def test_format_rate_line_material_round_trip():
    line = views.format_rate_line({
        "kind": "material", "key": "cement", "qty": "2", "price": "100",
        "waste": "10", "desc": "C"})
    assert line == ("material | key=cement | qty=2 | price=100 | "
                    "waste=10 | desc=C")
    assert views.parse_rate_lines(line + "\n") == [{
        "kind": "material", "material_key": "cement", "qty_per_unit": "2",
        "unit_price": "100", "wastage_pct": "10", "description": "C"}]


def test_format_rate_line_labour_and_subcontract_round_trip():
    labour = views.format_rate_line({
        "kind": "labour", "key": "", "qty": "2", "price": "500",
        "waste": "", "desc": "Fix"})
    assert labour == "labour | hours=2 | rate=500 | desc=Fix"
    assert views.parse_rate_lines(labour + "\n")[0]["kind"] == "labour"
    sub = views.format_rate_line({
        "kind": "subcontract", "key": "", "qty": "", "price": "50",
        "waste": "", "desc": "PC"})
    assert sub == "subcontract | amount=50 | desc=PC"
    parsed = views.parse_rate_lines(sub + "\n")[0]
    assert parsed["provisional"] == "no"


def test_format_rate_line_plant_rejected_honestly_by_parser():
    line = views.format_rate_line({
        "kind": "plant", "key": "excavator", "qty": "2", "price": "500",
        "waste": "", "desc": "Dig"})
    assert line.startswith("plant | key=excavator")
    with pytest.raises(ValidationError) as exc_info:
        views.parse_rate_lines(line + "\n")
    assert "unknown kind" in str(exc_info.value)


def test_format_rate_line_rejects_bad_rows():
    with pytest.raises(ValidationError):
        views.format_rate_line({"kind": "teleport", "price": "5"})
    with pytest.raises(ValidationError):
        views.format_rate_line({"kind": "", "price": "5"})
    with pytest.raises(ValidationError):
        views.format_rate_line(["material"])


def test_rates_page_uses_grid_and_raw_toggle():
    source = inspect.getsource(views.build_rates_page)
    # Phase 16.1: developer terms cleaned to "Advanced Input".
    assert "Advanced Input" in source
    assert "Advanced / Raw DSL" not in source
    assert "Show Advanced / Raw DSL" not in source
    assert "format_rate_line" in source
    assert "Add Component Row" in source
    assert "RATE_COMPONENT_KINDS" in source
    assert "Resource Code" in source


# --- materials catalogue ---------------------------------------------------------------

def test_material_catalogue_rows_from_master_data():
    rows = views.material_catalogue_rows(repo())
    assert len(rows) == 23
    assert set(views.MATERIALS_COLUMNS) == {
        "code", "name", "category", "subcategory", "unit", "density",
        "wastage", "status"}
    # Phase 16.1: no static price column exists by design.
    assert "price" not in views.MATERIALS_COLUMNS
    by_key = {row[0]: row for row in rows}
    cement = by_key["portland_cement_42_5"]
    assert cement[1] == "Portland Cement 42.5"
    assert cement[2] == "binder"
    assert cement[4] == "bag"
    assert cement[5] == "\u2014"  # null density: em-dash, never invented
    assert cement[6] == "\u2014"  # null wastage default likewise
    assert cement[7].strip()  # verification status always shown


def test_materials_page_wiring_and_read_only_grid():
    assert views.PAGES["materials"] is views.build_materials_page
    source = inspect.getsource(views.build_materials_page)
    assert "MATERIALS_COLUMNS" in source
    assert "material_catalogue_rows" in source
    assert "ttk.Entry" not in source  # read-only: grid only, no inputs


# --- estimate dashboard ------------------------------------------------------------------

def test_estimate_cost_groups_honest_roll_up():
    summary = views.estimate_cost_groups(_compiled_fixture())
    assert [key for key, _label, _t, _p in summary["groups"]] == [
        "materials", "labour", "plant", "other"]
    groups = {key: (total, partial)
              for key, _label, total, partial in summary["groups"]}
    # Priced concrete 5x200=1000; unpriced masonry flags partial.
    assert groups["materials"] == ("1000", True)
    assert groups["labour"] == (None, False)
    assert summary["resolved_subtotal"] == "1000"
    assert summary["grand_total"] is None
    assert summary["unresolved_items"] == ("2.1.1",)


def test_estimate_cost_groups_rejects_missing_compilation():
    with pytest.raises(ValidationError):
        views.estimate_cost_groups(None)


def test_estimate_page_wiring():
    assert views.PAGES["estimate"] is views.build_estimate_page
    source = inspect.getsource(views.build_estimate_page)
    assert "estimate_cost_groups" in source
    # Phase 16.1: domain label for the final value.
    assert "Tender Value" in source
    assert "Final Project Tender Value" not in source


# --- navigation promotion ------------------------------------------------------------------

def test_materials_and_estimate_promoted_to_pages():
    kinds = {key: kind for _group, items in views.NAV_GROUPS
             for key, _label, kind in items}
    assert kinds["materials"] == "page"
    assert kinds["estimate"] == "page"
    assert set(views.PLACEHOLDER_COPY) == set()
