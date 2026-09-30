"""Phase 16.2 dropdown + segmented footer tests: headless, no widgets.

Pins the measurement-standard registry derivation, the edition
cascade, the honest custom-standard binding, the five footer segments,
and the frozen legacy status-text contract. Widget construction needs
a display and stays display-guarded; controller and session contracts
are asserted untouched.
"""

import inspect

from qs_engine.ui import controllers, views
from qs_engine.ui.session import TakeoffLine, TakeoffSession


def _line(**extra):
    fields = {"trade": "concrete", "description": "Slab", "unit": "m\u00b3",
              "quantity": "3.00", "takeoff_ref": "S1"}
    fields.update(extra)
    return TakeoffLine(**fields)


def _compiled_session(**lines):
    from qs_engine.boq.compiler import compile_boq
    session = TakeoffSession()
    session.add_line(_line(**lines))
    session.last_compiled = compile_boq(session.to_boq("P", "B"))
    return session


# --- standard / edition dropdown data ---------------------------------------------

def test_standard_choices_derive_from_registry():
    from qs_engine.boq.measurement import KNOWN_STANDARDS
    choices = views.measurement_standard_choices()
    assert choices == ("CESMM", "SMM", "NRM")
    for registered in KNOWN_STANDARDS:
        assert registered in choices


def test_edition_cascade_per_standard():
    assert views.measurement_edition_choices("CESMM") == ("CESMM4", "CESMM3")
    assert views.measurement_edition_choices("smm") == ("SMM7",)
    assert views.measurement_edition_choices("NRM") == ("NRM2",)
    assert views.measurement_edition_choices("POMI") == ()
    assert views.measurement_edition_choices("") == ()


def test_unregistered_standard_binds_honestly_as_custom():
    setup = controllers.project_setup_controller(
        standard="NRM", edition="NRM2")
    assert setup.standard == "NRM"
    assert setup.edition == "NRM2"
    assert setup.known is False
    assert "Needs Verification" in views.format_verification(setup.known)


def test_project_setup_controller_contract_untouched():
    params = inspect.signature(
        controllers.project_setup_controller).parameters
    assert list(params) == ["standard", "edition"]
    assert params["edition"].default == ""


def test_project_page_uses_cascading_comboboxes():
    source = inspect.getsource(views.build_project_page)
    assert "ttk.Combobox" in source
    assert "measurement_standard_choices" in source
    assert "measurement_edition_choices" in source
    assert "<<ComboboxSelected>>" in source
    assert "entries_std" in source  # getter/setter contracts preserved


# --- segmented footer -----------------------------------------------------------------

def test_status_segments_keys_in_order():
    assert views.STATUS_SEGMENTS == (
        "lines", "project", "boq", "standard", "rules")


def test_status_segments_empty_session():
    assert views.status_segments(TakeoffSession()) == (
        "Lines: 0",
        "\U0001f4c1 No Active Project",
        "\u26aa BOQ: Uncompiled",
        "\u26aa Standard: [Not Bound]",
        "\u26a0 Measurement Rules Need Verification",
    )


def test_status_segments_project_indicator():
    session = TakeoffSession()
    session.save_project(name="Demo")
    assert views.status_segments(session)[1] == "\U0001f7e2 Project: Demo"
    unnamed = TakeoffSession()
    unnamed.save_project(client="ACME")
    assert views.status_segments(unnamed)[1] == (
        "\U0001f7e2 Project: Unnamed Project")


def test_status_segments_boq_states():
    priced = _compiled_session(rate="242.00", rate_ref="R-C1")
    assert views.status_segments(priced)[2] == "\U0001f7e2 BOQ: Compiled"
    segments = views.status_segments(_compiled_session())
    assert segments[0] == "Lines: 1"
    assert segments[2] == "\u26a0 BOQ: 1 Unresolved"


def test_status_segments_standard_edition():
    session = TakeoffSession()
    session.standard = controllers.project_setup_controller(
        standard="CESMM", edition="CESMM4")
    assert views.status_segments(session)[3] == "\U0001f4d0 Standard: CESMM4"
    session.standard = controllers.project_setup_controller(standard="SMM")
    assert views.status_segments(session)[3] == "\U0001f4d0 Standard: SMM"


def test_legacy_status_text_contract_frozen():
    assert views.build_status_text(TakeoffSession()) == (
        "Lines: 0 | \u25cb No Project | \u25cb BOQ: Not Compiled | "
        "Standard: [Not Bound] | "
        "\u26a0 Measurement Rules Need Verification")


def test_qsapp_footer_uses_segmented_bar():
    source = inspect.getsource(views.QSApp.__init__)
    assert "STATUS_SEGMENTS" in source
    assert "ttk.Separator" in source
    assert "status_bar" in source
    assert "watermark" in source
    assert "FOOTER_BADGE" in source
    refresh = inspect.getsource(views.QSApp.refresh_status)
    assert "status_segments" in refresh
    assert "build_status_text" in refresh


def test_status_bar_theme_tokens_present():
    assert views.STATUSBAR_BG.startswith("#")
    source = inspect.getsource(views._apply_civolink_theme)
    assert "StatusBar.TFrame" in source
    assert "Segment.TLabel" in source
