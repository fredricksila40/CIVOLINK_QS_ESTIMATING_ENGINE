"""UI input-hardening tests: compact picker fields + clean icon buttons.

Pins the presentation contract from the systemic input-hardening pass:
lookup-driven fields stay compact (no long instructional sentences telling
the user to click the icon), the resource-picker trigger is one standardized
square icon button, fixed-parameter controls are read-only comboboxes, and
combobox selection bindings keep driving the underlying take-off state.

Engine and parser behaviour is asserted by the untouched pre-existing
suites; nothing here recalculates. Display tests are guarded and
headless-safe.
"""

import inspect

import pytest

from qs_engine.ui import views


def _display_root():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    return root


def _walk(widget, winfo_class):
    """Every descendant whose ttk class matches (best-effort)."""
    found = []

    def descend(node):
        for child in node.winfo_children():
            try:
                if child.winfo_class() == winfo_class:
                    found.append(child)
            except Exception:
                pass
            descend(child)

    descend(widget)
    return found


def _text(widget):
    try:
        return str(widget.cget("text"))
    except Exception:
        return ""


def _rates_body(app):
    app.show("rates")
    app.update_idletasks()
    return app.workspace.interior


def _picker_buttons(body):
    return [b for b in _walk(body, "TButton")
            if _text(b) == views.PICKER_ICON]


def _combo_with_values(body, values):
    for combo in _walk(body, "TCombobox"):
        try:
            if list(combo.cget("values")) == list(values):
                return combo
        except Exception:
            continue
    return None


def _readout_entries(body):
    """Disabled entries are programmatic readouts (never typed into)."""
    out = []
    for entry in _walk(body, "TEntry"):
        try:
            if str(entry.cget("state")) == "disabled":
                out.append(entry)
        except Exception:
            continue
    return out


# --- source-level contract (no display required) -----------------------------

def test_no_long_instructional_hint_left_in_source():
    """Fixed-parameter fields must not carry click-the-icon sentences."""
    source = inspect.getsource(views)
    for banned in ("(Click", "to select)", "type code or use"):
        assert banned not in source, f"banned hint text {banned!r} remains"


def test_picker_hint_is_compact():
    assert views.PICKER_HINT == "Select..."
    assert len(views.PICKER_HINT) <= 12


def test_picker_icon_is_a_single_unicode_glyph():
    """The UI layer is stdlib tkinter/ttk only (no image asset loader),
    so the standardized trigger is a unicode glyph, not a PNG/SVG."""
    assert views.PICKER_ICON == "\U0001F50D"


def test_rate_rows_use_the_standard_picker_factory():
    assert "make_picker_button" in inspect.getsource(views.build_rates_page)


def test_resource_code_cue_disambiguates_from_the_resource_readout():
    """Cue standardisation: the Resource Code cell no longer shows the same
    ghost text as the Resource cell beside it (the audit's ambiguity)."""
    assert views.RATE_CODE_CUE == "Code / Item ID..."
    assert views.RATE_ROW_PLACEHOLDERS["key"] == views.RATE_CODE_CUE
    assert views.RATE_CODE_CUE != views.PICKER_HINT
    assert len(views.RATE_CODE_CUE) <= 20
    assert "Click" not in views.RATE_CODE_CUE


# --- display-guarded ---------------------------------------------------------

def test_picker_button_is_a_clean_square_icon_button():
    root = _display_root()
    app = views.QSApp()
    buttons = _picker_buttons(_rates_body(app))
    assert len(buttons) == 1, "exactly one standardized picker per row"
    button = buttons[0]
    assert str(button.cget("style")) == views.PICKER_BUTTON_STYLE
    assert int(button.cget("width")) == 2
    app.destroy()
    root.destroy()


def test_picker_button_is_narrower_than_a_text_button():
    """Icon trigger stays compact — no stretched or clipped grid cell."""
    root = _display_root()
    app = views.QSApp()
    body = _rates_body(app)
    app.update_idletasks()
    picker = _picker_buttons(body)[0]
    text_buttons = [b for b in _walk(body, "TButton")
                    if _text(b) == "Add Component Row"]
    assert text_buttons, "reference text button must exist"
    assert picker.winfo_reqwidth() < text_buttons[0].winfo_reqwidth()
    app.destroy()
    root.destroy()


def test_resource_readout_starts_as_compact_hint():
    root = _display_root()
    app = views.QSApp()
    body = _rates_body(app)
    texts = [entry.get() for entry in _readout_entries(body)]
    assert views.PICKER_HINT in texts
    assert not any("Click" in text for text in texts)
    app.destroy()
    root.destroy()


def test_fixed_parameter_comboboxes_are_readonly():
    """Typo-prone fixed parameters are locked read-only dropdowns."""
    root = _display_root()
    app = views.QSApp()
    body = _rates_body(app)
    for values in (views.RATE_POLICIES, views.RATE_COMPONENT_KINDS,
                   views.PROVISIONAL_CHOICES, views.RATE_WORK_UNITS):
        combo = _combo_with_values(body, values)
        assert combo is not None, f"missing dropdown for {values}"
        assert str(combo.cget("state")) == "readonly"
    app.destroy()
    root.destroy()


def test_fixed_parameter_combobox_defaults_match_spec():
    root = _display_root()
    app = views.QSApp()
    body = _rates_body(app)
    assert _combo_with_values(
        body, views.RATE_POLICIES).get() == "sequential"
    assert _combo_with_values(
        body, views.RATE_COMPONENT_KINDS).get() == "material"
    assert _combo_with_values(
        body, views.PROVISIONAL_CHOICES).get() == "No"
    app.destroy()
    root.destroy()


def test_kind_combobox_binding_updates_resource_readout():
    """A combobox selection must flow straight into panel state."""
    root = _display_root()
    app = views.QSApp()
    body = _rates_body(app)
    kind = _combo_with_values(body, views.RATE_COMPONENT_KINDS)
    assert kind is not None
    readouts = _readout_entries(body)
    assert readouts, "resource readout must exist"
    readout = readouts[0]

    kind.set("plant")
    kind.event_generate("<<ComboboxSelected>>")
    app.update_idletasks()
    assert readout.get() == "Price via Plant take-off"

    kind.set("material")
    kind.event_generate("<<ComboboxSelected>>")
    app.update_idletasks()
    assert readout.get() != "Price via Plant take-off"
    app.destroy()
    root.destroy()


def test_every_page_builds_without_layout_error():
    """Switching tabs must build each panel cleanly (no clipping/raise)."""
    root = _display_root()
    app = views.QSApp()
    for key in views.PAGES:
        app.show(key)
        app.update_idletasks()
        assert app.workspace.interior.winfo_children(), key
    app.destroy()
    root.destroy()


# --- rate-unit vocabulary (what makes read-only safe) ------------------------

def test_rate_unit_choices_cover_every_supported_unit():
    """Read-only is only safe because the list is the FULL vocabulary —
    otherwise a supported unit would become unreachable from the UI."""
    from qs_engine.core.units import SUPPORTED_UNITS
    assert set(views.RATE_WORK_UNITS) == set(SUPPORTED_UNITS)


def test_rate_unit_choices_exclude_engine_invalid_shorthand():
    """Canonical spellings only; shorthand the engine must reject is out."""
    for shorthand in ("t", "hr", "nr", "sum", "item"):
        assert shorthand not in views.RATE_WORK_UNITS


def test_rate_unit_default_is_a_supported_unit():
    assert views.RATE_WORK_UNITS[1] == "m²"
    assert "m²" in views.RATE_WORK_UNITS


# --- placeholder hygiene -----------------------------------------------------

def test_placeholders_are_compact_and_never_instructional():
    """Hints must fit their entry width (no clipping) and never instruct
    the user to click the picker icon."""
    for field, hint in views.RATE_ROW_PLACEHOLDERS.items():
        assert len(hint) <= 20, f"{field} hint too long: {hint!r}"
        assert "Click" not in hint
    assert len(views.ELEMENT_HINT) <= 24  # element entry is width=24
    assert "Click" not in views.ELEMENT_HINT


def test_rate_row_defaults_stay_readonly_and_correct():
    root = _display_root()
    app = views.QSApp()
    body = _rates_body(app)
    unit = _combo_with_values(body, views.RATE_WORK_UNITS)
    assert unit is not None
    assert unit.get() == "m²"
    assert str(unit.cget("state")) == "readonly"
    app.destroy()
    root.destroy()
