"""Phase 13B UI wire-up tests: headless, no widgets.

Covers session rate state, the rate-apply helper, summary-card updaters
(via label fakes), the pure status-text builder, and the unchanged
navigation contract. Existing tests are untouched.
"""

import pytest

from qs_engine.core.errors import ValidationError
from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.ui import views
from qs_engine.ui.session import TakeoffLine, TakeoffSession


def repo():
    return MasterDataRepository()


def _line(**extra):
    fields = {"trade": "concrete", "description": "Slab",
              "unit": "m³", "quantity": "3.00", "takeoff_ref": "S1"}
    fields.update(extra)
    return TakeoffLine(**fields)


class _FakeLabel:
    """Stand-in for a ttk.Label (records config calls)."""

    def __init__(self):
        self.settings = {}

    def config(self, **kwargs):
        self.settings.update(kwargs)


# --- session rate state ------------------------------------------------------

def test_last_rate_defaults_to_none():
    assert TakeoffSession().last_rate is None


def test_apply_built_rate_to_line():
    session = TakeoffSession()
    session.add_line(_line())
    updated = views.apply_built_rate_to_line(
        session, 0, "242.00", "rate-builder")
    assert updated.rate == "242.00"
    assert updated.rate_ref == "rate-builder"
    assert session.lines()[0].rate == "242.00"
    with pytest.raises(IndexError):
        views.apply_built_rate_to_line(session, 9, "10", "R")
    with pytest.raises(ValidationError):
        views.apply_built_rate_to_line(session, 0, "not-a-number", "R")


# --- summary card updaters -----------------------------------------------------

def test_labour_card_updater():
    from qs_engine.ui.controllers import labour_controller
    view = labour_controller(
        {"work_quantity": "100", "trade_key": "mason"}, repo(),
        {"output_per_day": "25", "gang_skilled": "2", "gang_unskilled": "4",
         "skilled_rate": "1500", "unskilled_rate": "800"})
    labels = {name: _FakeLabel()
              for name in ("duration", "skilled", "unskilled", "total")}
    views._update_labour_card(labels, view)
    assert labels["duration"].settings == {"text": "4"}
    assert labels["skilled"].settings == {"text": "8"}
    assert labels["unskilled"].settings == {"text": "16"}
    assert labels["total"].settings == {"text": "24800"}


def test_plant_card_updater():
    from qs_engine.ui.controllers import plant_controller
    view = plant_controller(
        {"work_quantity": "100", "equipment_key": "backhoe_excavator"},
        repo(),
        {"output_per_unit": "20", "rate": "24000"},
        hours_per_day="8")
    labels = {name: _FakeLabel()
              for name in ("duration", "hire", "operating", "total")}
    views._update_plant_card(labels, view)
    assert labels["duration"].settings == {"text": "5 hour"}
    assert labels["hire"].settings == {"text": "15000.000"}
    assert labels["total"].settings == {"text": "15000.000"}


# --- status text builder ---------------------------------------------------------

def test_status_empty_session():
    text = views.build_status_text(TakeoffSession())
    assert "Lines: 0" in text
    assert "○ No Project" in text
    assert "○ BOQ: Not Compiled" in text
    assert "Standard: [Not Bound]" in text
    assert "⚠ Measurement Rules Need Verification" in text


def test_status_project_and_clean_boq():
    from qs_engine.boq.compiler import compile_boq
    session = TakeoffSession()
    session.save_project(name="Demo", reference="D-1")
    session.add_line(_line(rate="242.00", rate_ref="R-C1"))
    session.last_compiled = compile_boq(session.to_boq("P", "B"))
    text = views.build_status_text(session)
    assert "● Project Saved" in text
    assert "● BOQ Reconciled: 726.00" in text
    assert "⚠ Measurement Rules Need Verification" in text


def test_status_unresolved_boq():
    from qs_engine.boq.compiler import compile_boq
    session = TakeoffSession()
    session.add_line(_line())
    session.last_compiled = compile_boq(session.to_boq("P", "B"))
    text = views.build_status_text(session)
    assert "⚠ BOQ: 1 unresolved" in text
    assert "● BOQ Reconciled" not in text


# --- navigation contract holds -----------------------------------------------------

def test_nav_pages_still_complete():
    for _group, items in views.NAV_GROUPS:
        for key, _label, kind in items:
            if kind == "page":
                assert key in views.PAGES, key
    assert set(views.PAGES) == {
        "overview", "project", "concrete", "masonry", "rebar",
        "earthworks", "finishes", "materials", "labour_plant",
        "logistics", "reconciliation", "rates", "boq", "estimate",
        "excel", "corpdoc", "valuations", "mix_design",
        "admin_setup", "global_policy_editor", "security_policy",
    }


def test_panel_specs_untouched():
    assert set(views.PANEL_SPECS) == {
        "project", "concrete", "masonry", "earthworks", "finishes",
        "labour", "plant", "logistics", "rates", "boq", "mix_design",
    }
    for _key, (title, name, fields) in views.PANEL_SPECS.items():
        assert callable(getattr(views.controllers, name, None))
