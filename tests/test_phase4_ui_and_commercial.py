"""Phase 4 UI/UX polish, help-icon, navigation and commercial tests.

Covers the unified HelpIconButton / PopoverGuide / ToolTip adoption
across page headers (hover cue -> quick tooltip, click -> pinned
popover, auto-dismiss on view switch), navigation and Project Setup
label normalization, the Formwork take-off -> BOQ -> Rate Builder ->
Estimate commercial flow (section code ``T``, unit m²), and the export
action guards driven by ``session.boq_compiled``.
"""

import inspect
from decimal import Decimal
from types import SimpleNamespace

import pytest

from qs_engine.ui import views
from qs_engine.ui.session import TakeoffLine, TakeoffSession, TRADE_SECTIONS
from qs_engine.ui.widgets import (
    HELP_HOVER_DELAY_MS,
    HELP_ICON_INFO,
    HELP_ICON_QUESTION,
    HelpIconButton,
    close_all_popovers,
    summary_of,
)


def _display_root():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    return root


def _walk(widget, predicate, found=None):
    if found is None:
        found = []
    for child in widget.winfo_children():
        if predicate(child):
            found.append(child)
        _walk(child, predicate, found)
    return found


def _buttons(container):
    return _walk(container, lambda w: w.winfo_class() == "TButton")


def _labels(container):
    return _walk(container, lambda w: w.winfo_class() == "TLabel")


def _find_button(container, text):
    for button in _buttons(container):
        if str(button.cget("text")) == text:
            return button
    return None


def _formwork_session(rate=None, rate_ref=""):
    session = TakeoffSession()
    session.add_line(TakeoffLine(
        trade="formwork",
        description="GF Slab Soffit (slab_soffit)",
        unit="m²", quantity="40",
        rate=rate, rate_ref=rate_ref,
        takeoff_ref="GF Slab S1"))
    return session


# --- Task 4.1: HelpIconButton & popover system --------------------------------

def test_help_icon_widget_contract():
    root = _display_root()
    button = HelpIconButton(root, guide_text="Panel guide body.")
    assert isinstance(button, HelpIconButton)
    assert str(button.cget("text")) == HELP_ICON_INFO == "\u24d8"
    assert int(button.cget("width")) == 2          # compact square
    assert button.tooltip.delay_ms == HELP_HOVER_DELAY_MS == 250
    assert button.guide_text == "Panel guide body."
    assert button.guide.text == "Panel guide body."
    button.destroy()
    root.destroy()


def test_help_icon_question_glyph_for_verification_severity():
    root = _display_root()
    button = HelpIconButton(root, guide_text="Verify this input.",
                            severity="question")
    assert str(button.cget("text")) == HELP_ICON_QUESTION == "?"
    assert button.severity == "question"
    button.destroy()
    root.destroy()


def test_help_icon_resolves_guide_key_from_registry():
    from qs_engine.ui.widgets import register_guide
    root = _display_root()
    register_guide("p4-state-test", "Registered guide body.")
    button = HelpIconButton(root, guide_key="p4-state-test")
    assert button.guide_key == "p4-state-test"
    assert button.guide_text == "Registered guide body."
    assert button.summary == "Registered guide body."
    button.destroy()
    root.destroy()


def test_hover_schedules_tooltip_and_leave_cancels():
    root = _display_root()
    button = HelpIconButton(
        root, guide_text="Panel guide. Extra detail behind the cue.")
    assert button.tooltip.text == summary_of(button.guide_text)
    button._on_enter()
    assert button.tooltip._after is not None      # 250ms show scheduled
    button._on_leave()
    assert button.tooltip._after is None          # cancelled on exit
    assert not button.tooltip.is_visible
    button.destroy()
    root.destroy()


def test_click_toggles_pinned_popover_and_suppresses_hover():
    root = _display_root()
    button = HelpIconButton(root, guide_text="Click for the full guide.")
    button.toggle()
    assert button.is_open and button.guide.is_pinned
    button._on_enter()                            # hover while pinned
    assert button.tooltip._after is None          # tooltip suppressed
    button.toggle()                               # second click closes
    assert not button.is_open
    button.destroy()
    root.destroy()


def test_close_all_popovers_dismisses_open_guides():
    root = _display_root()
    button = HelpIconButton(root, guide_text="Guide body for closing.")
    button.toggle()
    assert button.is_open
    close_all_popovers()
    assert not button.is_open
    button.destroy()
    root.destroy()


def test_help_icon_without_guide_text_runs_fallback_command():
    root = _display_root()
    calls = []
    button = HelpIconButton(root, command=lambda: calls.append(1))
    button.toggle()
    assert calls == [1]
    assert not button.is_open
    button.destroy()
    root.destroy()


def test_build_page_header_renders_help_icon_button():
    from tkinter import ttk
    root = _display_root()
    body = ttk.Frame(root)
    body.pack()
    views.build_page_header(body, "Any Panel",
                            "Full guide text for the header icon.")
    icons = _walk(body, lambda w: isinstance(w, HelpIconButton))
    assert icons, "header did not render a HelpIconButton"
    assert icons[0].guide_text == "Full guide text for the header icon."
    legacy = [b for b in _buttons(body)
              if str(b.cget("text")).strip("ℹ ").endswith("Panel Guide")]
    assert not legacy, "legacy text guide button still present"
    root.destroy()


def test_headers_adopted_across_all_pages_in_source():
    source = inspect.getsource(views)
    assert "HelpIconButton(header" in source
    # no legacy text buttons remain (docstring mentions are fine)
    assert 'text="[?] Verification Help"' not in source
    assert '("[?] Verification Help"' not in source
    assert source.count("guide_key=") >= 12


def test_guide_registry_covers_every_navigation_page():
    required = {
        "overview", "project", "concrete", "masonry", "rebar",
        "earthworks", "finishes", "materials", "labour", "plant",
        "logistics", "rates", "boq", "estimate", "excel", "corpdoc",
        "valuations", "verification",
    }
    content = views._GUIDE_CONTENT
    assert required <= set(content)
    assert all(str(content[key]).strip() for key in required)


def test_view_switch_closes_popovers_and_tooltips():
    root = _display_root()
    from qs_engine.ui.views import QSApp
    app = QSApp()
    app.show("overview")
    app.update_idletasks()
    icons = _walk(app.workspace.interior,
                  lambda w: isinstance(w, HelpIconButton))
    assert icons
    icon = icons[0]
    icon._on_enter()                              # pending hover tooltip
    assert icon.tooltip._after is not None
    icon.toggle()                                 # pin the popover open
    assert icon.is_open
    app.show("rates")                             # tab change
    app.update_idletasks()
    assert not icon.is_open                       # popover auto-dismissed
    assert icon.tooltip._after is None
    assert not icon.tooltip.is_visible
    app.destroy()
    root.destroy()


# --- Task 4.2: navigation & label normalization --------------------------------

def test_navigation_labels_normalized():
    labels = [label for _group, items in views.NAV_GROUPS
              for _key, label, _kind in items]
    assert "Masonry" in labels
    assert "Haulage Plan" in labels
    assert not any("Masority" in label for label in labels)
    assert not any("Hauluge" in label for label in labels)
    sections = dict((key, value[1]) for key, value in TRADE_SECTIONS.items())
    assert sections["masonry"] == "Masonry"
    assert sections["logistics"] == "Haulage"


def test_project_setup_density_labels_clean():
    fields = dict(views.CONCRETE_DENSITY_FIELDS)
    assert fields["cement_density_kg_per_m3"] == "Cement Density (kg/m³)"
    assert fields["sand_density_kg_per_m3"] == "Sand Density (kg/m³)"
    assert fields["aggregate_density_kg_per_m3"] == (
        "Aggregates Density (kg/m³)")
    for label in fields.values():
        assert "kg/m²" not in label      # never a squared-unit typo
        assert "( (" not in label        # never a doubled paren
        assert "r(" not in label         # never raw LaTeX remnants
        assert label.endswith("(kg/m³)")


# --- Task 4.3: formwork commercial binding & BOQ flow ---------------------------

def test_formwork_section_flows_through_boq_compiler():
    from qs_engine.boq.compiler import compile_boq
    from qs_engine.boq.models import STATUS_UNPRICED
    session = _formwork_session()
    boq = session.to_boq("PRJ", "B1")
    section = next(s for s in boq.sections if s.code == "T")
    assert section.title == "Formwork"
    assert section.subsections[0].code == "T.1"
    assert TRADE_SECTIONS["formwork"] == (
        "T", "Formwork", "Temporary works")

    compiled = compile_boq(boq)
    compiled_section = next(s for s in compiled.sections if s.code == "T")
    item = compiled_section.items[0]
    assert item.unit == "m²"
    assert item.quantity == Decimal("40")
    assert item.status == STATUS_UNPRICED
    assert item.amount is None
    assert compiled_section.resolved_subtotal == Decimal("0")
    assert compiled.resolved_subtotal == Decimal("0")
    assert compiled.has_unresolved


def test_formwork_priced_line_populates_estimate_table():
    from qs_engine.boq.compiler import compile_boq
    from qs_engine.boq.models import STATUS_PRICED
    session = _formwork_session(rate="37.5", rate_ref="RB-formwork")
    compiled = compile_boq(session.to_boq("PRJ", "B1"))
    item = compiled.sections[0].items[0]
    expected_amount = Decimal("40") * Decimal("37.5")
    assert item.status == STATUS_PRICED
    assert item.rate == Decimal("37.5")
    assert item.amount == expected_amount
    assert item.rate_ref == "RB-formwork"

    summary = views.estimate_cost_groups(compiled)
    groups = {key: (label, total, partial)
              for key, label, total, partial in summary["groups"]}
    label, total, partial = groups["other"]
    assert label == "Other Sections"        # section T lands here today
    assert Decimal(total) == expected_amount
    assert partial is False
    assert Decimal(summary["resolved_subtotal"]) == expected_amount
    assert summary["unresolved_items"] == ()


def test_formwork_line_takes_rate_from_rate_builder():
    from qs_engine.boq.compiler import compile_boq
    session = _formwork_session()
    views.apply_built_rate_to_line(session, 0, "37.5", "RB-formwork")
    line = session.lines()[0]
    assert line.rate == "37.5"
    assert line.rate_ref == "RB-formwork"
    compiled = compile_boq(session.to_boq("PRJ", "B1"))
    item = compiled.sections[0].items[0]
    assert item.status == "priced"
    assert item.rate == Decimal("37.5")
    assert "RB-formwork" in item.provenance


def test_formwork_boq_view_renders_section_t_with_m2():
    from qs_engine.ui.controllers import boq_view_controller
    from qs_engine.ui.viewmodels import ErrorView
    view = boq_view_controller(_formwork_session().to_boq("PRJ", "B1"))
    assert not isinstance(view, ErrorView), view
    section = view.sections[0]
    assert section.code == "T"
    assert section.title == "Formwork"
    assert section.items[0].unit == "m²"
    assert section.items[0].quantity == "40"


def test_schedule_grid_rows_include_formwork_trade():
    session = _formwork_session()
    session.add_line(TakeoffLine(
        trade="rebar", description="Slab steel", unit="kg",
        quantity="120"))
    rows = views._trade_grid_rows(session)
    assert [row[1] for row in rows] == ["formwork", "rebar"]
    only_formwork = views._trade_grid_rows(session, "formwork")
    assert len(only_formwork) == 1
    assert only_formwork[0][3] == "m²"


def test_rate_builder_schedule_lists_formwork_line():
    root = _display_root()
    from qs_engine.ui.views import QSApp
    app = QSApp()
    app.session.add_line(TakeoffLine(
        trade="formwork",
        description="GF Slab Soffit (slab_soffit)",
        unit="m²", quantity="40", takeoff_ref="GF Slab S1"))
    app.show("rates")
    app.update_idletasks()
    trees = _walk(app.workspace.interior,
                  lambda w: w.winfo_class() == "Treeview")
    rows = [values for tree in trees for iid in tree.get_children()
            for values in (tree.item(iid, "values"),)]
    assert any(str(row[0]) == "formwork" and str(row[2]) == "m²"
               for row in rows), "formwork line missing from schedule"
    app.destroy()
    root.destroy()


# --- Task 4.4: export & commercial view action guards ---------------------------

def test_session_boq_compiled_flag_tracks_snapshot():
    from qs_engine.boq.compiler import compile_boq
    session = TakeoffSession()
    assert session.boq_compiled is False
    session.add_line(TakeoffLine(
        trade="formwork", description="Soffit", unit="m²",
        quantity="40"))
    assert session.boq_compiled is False
    session.last_compiled = compile_boq(session.to_boq("P", "B"))
    assert session.boq_compiled is True
    session.last_compiled = None
    assert session.boq_compiled is False


def test_export_guard_banner_text_standardized():
    assert views.EXPORT_GUARD_BANNER == (
        "Action Required: Compile BOQ in Bill of Quantities view "
        "prior to exporting."
    )


def test_register_export_guard_applies_state_immediately():
    from tkinter import ttk
    root = _display_root()
    button = ttk.Button(root, text="Export")
    banner = ttk.Label(root, text="stale")
    app = SimpleNamespace(session=TakeoffSession(), _export_guards=[])
    views.register_export_guard(app, button, banner)
    assert str(button.cget("state")) == "disabled"
    assert str(banner.cget("text")) == views.EXPORT_GUARD_BANNER
    app.session.last_compiled = object()          # compiled snapshot
    assert views.sync_export_guards(app) == 1
    assert str(button.cget("state")) == "normal"
    assert str(banner.cget("text")) == ""
    root.destroy()


def test_sync_export_guards_prunes_destroyed_pages():
    from tkinter import ttk
    root = _display_root()
    button = ttk.Button(root, text="Export")
    banner = ttk.Label(root, text="")
    button.destroy()
    app = SimpleNamespace(session=TakeoffSession(),
                          _export_guards=[(button, banner)])
    assert views.sync_export_guards(app) == 0
    assert app._export_guards == []
    root.destroy()


def test_export_guards_toggle_with_boq_compilation():
    from qs_engine.boq.compiler import compile_boq
    root = _display_root()
    from qs_engine.ui.views import QSApp
    app = QSApp()
    targets = (
        ("excel", "Export BOQ"),
        ("valuations", "Export IPC Statement PDF"),
        ("corpdoc", "Generate Branded Document"),
    )
    # Uncompiled: every primary action is disabled with the banner.
    for page, label in targets:
        app.show(page)
        app.update_idletasks()
        button = _find_button(app.workspace.interior, label)
        assert button is not None, f"{label} missing on {page}"
        assert str(button.cget("state")) == "disabled", label
        banners = [w for w in _labels(app.workspace.interior)
                   if str(w.cget("text")) == views.EXPORT_GUARD_BANNER]
        assert banners, f"guard banner missing on {page}"
    # Compile a formwork-only BOQ: guards flip live on refresh.
    session = app.session
    session.add_line(TakeoffLine(
        trade="formwork",
        description="GF Slab Soffit (slab_soffit)",
        unit="m²", quantity="40"))
    session.last_compiled = compile_boq(session.to_boq("PRJ", "B1"))
    app.refresh_status()
    for page, label in targets:
        app.show(page)
        app.update_idletasks()
        button = _find_button(app.workspace.interior, label)
        assert button is not None, f"{label} missing on {page}"
        assert str(button.cget("state")) == "normal", label
        banners = [w for w in _labels(app.workspace.interior)
                   if str(w.cget("text")) == views.EXPORT_GUARD_BANNER]
        assert not banners, f"stale banner on {page}"
    app.destroy()
    root.destroy()
