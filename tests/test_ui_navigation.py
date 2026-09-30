"""UI navigation/session tests (refactor): headless, no widgets.

Pins the sidebar contract (groups, placeholders, controller backing),
the pure session store, the rate-line parsers, and BOQ assembly — all
without instantiating tkinter. Existing tests are untouched.
"""

import pytest

from decimal import Decimal

from qs_engine.core.errors import ValidationError
from qs_engine.ui import controllers, views
from qs_engine.ui.session import (
    TRADE_SECTIONS,
    TakeoffLine,
    TakeoffSession,
)


def _line(trade="concrete", quantity="3.00", rate=None, **extra):
    fields = {"trade": trade, "description": f"{trade} line",
              "unit": "m³", "quantity": quantity, "takeoff_ref": "T1"}
    fields.update(extra)
    if rate is not None:
        fields["rate"] = rate
    return TakeoffLine(**fields)


# --- navigation contract ---------------------------------------------------

def test_nav_groups_exact():
    groups = [(group, tuple(key for key, _label, _kind in items))
              for group, items in views.NAV_GROUPS]
    assert groups == [
        ("PROJECT", ("overview", "project")),
        ("TAKE-OFF", ("concrete", "masonry", "rebar", "earthworks",
                      "finishes")),
        ("RESOURCES", ("materials", "labour_plant", "logistics",
                       "reconciliation")),
        ("COMMERCIAL", ("rates", "boq", "estimate")),
        ("OUTPUT & EXPORT", ("excel", "corpdoc", "valuations")),
        ("CONSTITUENTS", ("mix_design",)),
        ("ADMINISTRATION", ("admin_setup", "global_policy_editor",
                            "security_policy")),
    ]


def test_placeholders_flagged_not_exposed():
    kinds = {key: kind for _g, items in views.NAV_GROUPS
             for key, _label, kind in items}
    # Phase 16: materials catalogue and estimate dashboard promoted to
    # working pages (read-only master-data table + BOQ-derived cost
    # summary); no placeholder modules remain in this build.
    assert kinds["materials"] == "page"
    assert kinds["estimate"] == "page"
    # Phase 15: Corporate Document Integration promoted to a working
    # page (Company Profile Editor + Template Hub + export pipeline).
    assert kinds["corpdoc"] == "page"
    assert set(views.PLACEHOLDER_COPY) == set()
    for _title, message in views.PLACEHOLDER_COPY.values():
        assert "future work" in message


def test_actionable_pages_backed_by_controllers():
    backing = {
        "overview": (),
        "project": ("project_setup_controller",),
        "concrete": ("concrete_controller",),
        "masonry": ("masonry_controller",),
        "rebar": ("rebar_controller",),
        "earthworks": ("earthworks_controller",),
        "finishes": ("finishes_controller",),
        "labour_plant": ("labour_controller", "plant_controller"),
        "logistics": ("logistics_plan_controller",),
        "rates": ("rate_builder_controller",),
        "boq": ("boq_view_controller",),
        "estimate": (),
        "materials": (),
        "excel": ("excel_export_controller", "tender_export_controller",
                  "tender_reconciliation_controller"),
        "corpdoc": ("branded_document_controller",
                    "document_payload_controller",),
        "valuations": ("ipc_valuation_controller", "boq_pdf_controller",
                       "ipc_pdf_controller",),
    }
    for key, names in backing.items():
        assert key in views.PAGES, key
        for name in names:
            assert callable(getattr(controllers, name, None)), (key, name)


def test_no_nav_key_missing_page():
    for _group, items in views.NAV_GROUPS:
        for key, _label, kind in items:
            if kind == "page":
                assert key in views.PAGES, key


def test_entry_point_intact():
    assert callable(views.launch)
    import run_app  # noqa: F401  (repo-root launcher still importable)


# --- verification/status helpers --------------------------------------------

def test_format_verification_never_claims_verified():
    assert "Needs Verification" in views.format_verification(True)
    assert "Needs Verification" in views.format_verification(False)
    assert "Recognized" in views.format_verification(True)
    assert "Custom" in views.format_verification(False)


def test_status_badge_known_and_unknown():
    text, _colour = views.status_badge("priced")
    assert text.startswith("●")
    flagged, _colour = views.status_badge("no-such-status")
    assert flagged.startswith("⚠")


# --- session store ------------------------------------------------------------

def test_session_add_remove_clear():
    session = TakeoffSession()
    first = session.add_line(_line())
    second = session.add_line(_line(trade="masonry", quantity="8"))
    assert (first, second) == (0, 1)
    assert session.summary_counts() == {"lines": 2,
                                        "by_trade": {"concrete": 1,
                                                     "masonry": 1}}
    assert session.lines_by_trade("masonry")[0].quantity == "8"
    removed = session.remove_line(0)
    assert removed.trade == "concrete"
    assert session.summary_counts()["lines"] == 1
    session.clear_lines()
    assert session.lines() == ()
    with pytest.raises(IndexError):
        session.remove_line(0)


def test_session_rejects_bad_lines():
    session = TakeoffSession()
    with pytest.raises(ValidationError):
        session.add_line("not-a-line")
    with pytest.raises(ValidationError):
        session.add_line(_line(trade="  "))
    with pytest.raises(ValidationError):
        session.add_line(_line(quantity="abc"))


def test_session_set_line_rate():
    session = TakeoffSession()
    session.add_line(_line())
    updated = session.set_line_rate(0, "242.00", "R-C1")
    assert updated.rate == "242.00"
    assert updated.rate_ref == "R-C1"
    with pytest.raises(ValidationError):
        session.set_line_rate(0, "not-a-number")
    with pytest.raises(IndexError):
        session.set_line_rate(9, "10")


def test_session_project_profile():
    session = TakeoffSession()
    profile = session.set_project(name="  Demo  ", reference="D-1")
    assert profile == {"name": "Demo", "reference": "D-1"}


def test_session_to_boq_grouping_and_pricing():
    session = TakeoffSession()
    session.add_line(_line(trade="concrete", quantity="3.00"))
    session.add_line(_line(trade="masonry", quantity="8",
                           rate="500.0", rate_ref="R-M1"))
    session.add_line(_line(trade="concrete", quantity="1.5"))
    boq = session.to_boq("P", "B")
    assert [s.code for s in boq.sections] == ["C", "M"]
    assert [i.quantity for i in boq.sections[0].subsections[0].items] == [
        Decimal("3.00"), Decimal("1.5")]
    assert boq.sections[0].subsections[0].items[0].pricing.kind == "unpriced"
    priced = boq.sections[1].subsections[0].items[0]
    assert priced.pricing.kind == "explicit"
    assert priced.pricing.rate == Decimal("500.0")


def test_session_to_boq_requires_lines_and_refs():
    session = TakeoffSession()
    with pytest.raises(ValidationError):
        session.to_boq("P", "B")
    session.add_line(_line())
    with pytest.raises(ValidationError):
        session.to_boq("  ", "B")
    with pytest.raises(ValidationError):
        session.to_boq("P", "")


def test_trade_sections_cover_known_trades():
    for trade in ("concrete", "masonry", "rebar", "earthworks",
                  "finishes", "labour", "plant", "logistics"):
        assert trade in TRADE_SECTIONS


# --- parsers ------------------------------------------------------------------

def test_parse_rate_lines_valid():
    text = ("# comment\n\n"
            "material | key=cement | qty=2 | price=100 | waste=10 | desc=C\n"
            "labour | hours=2 | rate=500 | desc=Fix\n"
            "logistics | total=7750 | qty=100 | desc=Haul\n"
            "subcontract | amount=50 | desc=PC | provisional=yes\n"
            "other | amount=7 | desc=Sundries\n")
    lines = views.parse_rate_lines(text)
    assert [line["kind"] for line in lines] == [
        "material", "labour", "logistics", "subcontract", "other"]
    assert lines[0]["material_key"] == "cement"
    assert lines[3]["provisional"] == "yes"


def test_parse_rate_lines_invalid():
    with pytest.raises(ValidationError):
        views.parse_rate_lines("material | key-only-no-equals\n")
    with pytest.raises(ValidationError):
        views.parse_rate_lines("teleport | amount=5\n")
    assert views.parse_rate_lines("  \n# only comments\n") == []


def test_parse_markup_lines():
    assert views.parse_markup_lines("profit: 10\nOH: 5\n") == [
        ("profit", "10"), ("OH", "5")]
    with pytest.raises(ValidationError):
        views.parse_markup_lines("no-colon-here\n")


def test_parse_rebar_lines():
    lines = views.parse_rebar_lines("Y12 | count=10 | len=6 | mass=2\n")
    assert lines == [{"bar_key": "Y12", "count": "10",
                      "length_per_bar_m": "6", "mass_kg_per_m": "2"}]
    with pytest.raises(ValidationError):
        views.parse_rebar_lines(" | count=2\n")
    with pytest.raises(ValidationError):
        views.parse_rebar_lines("Y12 | bogus=1\n")


# --- BOQ assembly through the compiler ------------------------------------------

def test_session_boq_compiles_with_honest_totals():
    from qs_engine.boq.compiler import compile_boq
    session = TakeoffSession()
    session.add_line(_line(trade="concrete", quantity="3.00",
                           rate="242.00", rate_ref="R-C1"))
    session.add_line(_line(trade="masonry", quantity="8"))
    compiled = compile_boq(session.to_boq("P", "B"))
    assert compiled.total is None  # unpriced line present
    assert compiled.resolved_subtotal == Decimal("726.00")
    assert compiled.unresolved_items == ("2.1.1",)
    priced = views.find_compiled_item(compiled, "1.1.1")
    assert priced is not None and priced.amount == Decimal("726.00")
    assert views.find_compiled_item(compiled, "9.9.9") is None
    assert views.find_compiled_item(None, "1.1.1") is None


def _display():
    """A withdrawn root for display checks, or None without a display."""
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        return root
    except Exception:
        return None


ROOT = _display()
requires_display = pytest.mark.skipif(
    ROOT is None, reason="no graphical display available")


# --- active-route highlight sync (display-guarded) -----------------------------------

@requires_display
def test_sidebar_click_moves_highlight_with_panel():
    """Clicking a sidebar item must move the highlight with the panel.

    Regression test: a builder crash once left the highlight stuck on
    the previous item (workspace destroyed, highlight never updated),
    so every route is clicked and exactly one button may carry the
    active styling afterwards.
    """
    from qs_engine.ui.views import CIVOLINK_BLUE, QSApp
    app_holder = {}
    try:
        app_holder["app"] = QSApp()
    except Exception as exc:
        pytest.skip(f"QSApp needs a display: {exc}")
    try:
        app = app_holder["app"]
        all_keys = [key for _group, items in views.NAV_GROUPS
                    for key, _label, _kind in items]
        assert set(all_keys) == set(app._nav_buttons)
        # ADMINISTRATION is hidden for a clerk, so it is not clicked here.
        keys = [key for key in all_keys
                if key not in views.ADMIN_VIEW_KEYS]
        for key in keys:
            app._nav_buttons[key].invoke()
            app.update_idletasks()
            lit = [name for name, button in app._nav_buttons.items()
                   if str(button.cget("bg")).lower()
                   == CIVOLINK_BLUE.lower()]
            assert lit == [key], (key, lit)
            assert app._current == key
            assert app.active_route_key == key
    finally:
        app.destroy()


@requires_display
def test_sidebar_all_routes_mapped_at_short_height():
    """Every nav button stays mapped (clickable) at 720p heights.

    Regression test: the fixed sidebar used to squeeze late routes
    to zero height, leaving five pages unreachable by mouse.
    """
    from qs_engine.ui.views import QSApp
    try:
        app = QSApp()
    except Exception as exc:
        pytest.skip(f"QSApp needs a display: {exc}")
    try:
        app.geometry("1280x720")
        app.update_idletasks()
        app.update()
        unmapped = [key for key, button in app._nav_buttons.items()
                    if not button.winfo_ismapped()]
        # Only the restricted ADMINISTRATION routes stay unmapped: they
        # are hidden until the session unlocks (least privilege).
        assert sorted(unmapped) == sorted(views.ADMIN_VIEW_KEYS)
        app._nav_buttons["valuations"].invoke()
        app.update_idletasks()
        assert app.active_route_key == "valuations"
    finally:
        app.destroy()


def test_administration_group_hidden_until_unlock():
    """Least privilege: the admin surface is invisible until Tier 1/2."""
    from qs_engine.core.security import SessionContext, UserRole
    from qs_engine.ui.views import QSApp, admin_nav_visible
    try:
        app = QSApp()
    except Exception as exc:
        pytest.skip(f"QSApp needs a display: {exc}")
    try:
        app.security = SessionContext()          # SITE_CLERK
        app._sync_admin_nav()
        assert admin_nav_visible(app.security) is False
        assert not app._nav_buttons["admin_setup"].winfo_ismapped()
        # Blocked navigation surfaces an explicit, non-blocking refusal.
        app.show("security_policy")
        app.update_idletasks()
        assert "SUPER_ADMIN" in getattr(app, "_toast_text", "")
        assert app._current != "security_policy"
        # Owner tier reveals the group and the Tier 2 route opens.
        app.security.set_role(UserRole.SUPER_ADMIN)
        app._sync_admin_nav()
        app.update_idletasks()
        assert admin_nav_visible(app.security) is True
        assert app._nav_buttons["admin_setup"].winfo_ismapped()
        app.show("admin_setup")
        app.update_idletasks()
        assert app._current == "admin_setup"
    finally:
        app.destroy()
