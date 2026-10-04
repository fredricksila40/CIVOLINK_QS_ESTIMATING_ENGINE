"""Format Pattern Template panel: modern layout + accuracy notes.

Covers the reworked Material Coding Configuration panel (token
chips, accuracy hint line, monospace preview) and the empty-separator
choice now honoured end to end (preview helper, policy round trip,
save path). The pinned behaviour in test_phase5_material_codes.py
(preview strings, "Preview:" adjacency, live-preview regressions)
must stay intact alongside these.
"""

import inspect

import pytest

from qs_engine.resources import (
    DEFAULT_TEMPLATE,
    CodePatternEngine,
    MaterialCodePolicy,
    policy_label,
)
from qs_engine.resources.code_policy import (
    CATEGORY_PREFIX,
    MATERIAL_CODE_SEPARATOR_FIELD,
    SEQUENTIAL_NUMERIC,
)
from qs_engine.ui.views import material_code_preview, preview_hint

DOUBLED_TEMPLATE = "{PREFIX}{SEPARATOR}{CATEGORY_ID}{SEPARATOR}{SEQUENCE}"


# --- accuracy notes (preview_hint) -------------------------------------------

def test_doubled_token_case_from_screenshot_is_flagged():
    """{PREFIX} + {CATEGORY_ID} both expand to the category prefix, so
    the pattern renders AGG_AGG_001 — the preview keeps that pinned
    output while the hint names the redundancy."""
    code = material_code_preview(
        policy_label(CATEGORY_PREFIX), "", DOUBLED_TEMPLATE, 3, "_")
    assert code == "AGG_AGG_001"
    hint = preview_hint(
        code, policy_label(CATEGORY_PREFIX), DOUBLED_TEMPLATE, "_")
    assert "{CATEGORY_ID}" in hint
    assert "{PREFIX}" in hint
    assert "AGG_AGG_001" in hint


def test_clean_template_has_no_hint():
    hint = preview_hint(
        "AGG-001", policy_label(CATEGORY_PREFIX), DEFAULT_TEMPLATE, "-")
    assert hint == ""


def test_numeric_mode_notes_ignored_pattern():
    code = material_code_preview(
        policy_label(SEQUENTIAL_NUMERIC), "", DEFAULT_TEMPLATE, 3, "-")
    assert code == "001"
    hint = preview_hint(
        code, policy_label(SEQUENTIAL_NUMERIC), DEFAULT_TEMPLATE, "-")
    assert "not applied" in hint


def test_manual_mode_notes_hand_entry():
    code = material_code_preview(policy_label("MANUAL"), "", "", 3, "-")
    assert code == "(manual entry)"
    hint = preview_hint(
        code, policy_label("MANUAL"), DEFAULT_TEMPLATE, "-")
    assert "typed by hand" in hint


def test_invalid_template_hint_never_leaks_tokens():
    hint = preview_hint(
        "(invalid template)", policy_label(CATEGORY_PREFIX),
        "{PREFIX}-{SAP_GL}-{SEQUENCE}", "-")
    assert "SAP_GL" not in hint
    assert "tokens" in hint


def test_blank_template_notes_default_fallback():
    code = material_code_preview(
        policy_label(CATEGORY_PREFIX), "", "", 3, "-")
    assert code == "AGG-001"  # default template applies silently
    hint = preview_hint(code, policy_label(CATEGORY_PREFIX), "", "-")
    assert "default" in hint


def test_empty_separator_renders_joined_and_is_noted():
    code = material_code_preview(
        policy_label(CATEGORY_PREFIX), "", DEFAULT_TEMPLATE, 3, "")
    assert code == "AGG001"
    hint = preview_hint(
        code, policy_label(CATEGORY_PREFIX), DEFAULT_TEMPLATE, "")
    assert "No separator" in hint
    assert "AGG001" in hint


# --- empty separator round trip ----------------------------------------------

def test_empty_separator_survives_profile_round_trip():
    """An explicit empty separator is a real choice: it must reach the
    profile as "" and come back as "" — never silently rebound to the
    default "-"."""
    policy = MaterialCodePolicy(CATEGORY_PREFIX, separator="")
    fields = policy.project_fields()
    assert fields[MATERIAL_CODE_SEPARATOR_FIELD] == ""
    restored = MaterialCodePolicy.from_project(
        {"material_code_policy": CATEGORY_PREFIX,
         MATERIAL_CODE_SEPARATOR_FIELD: fields[
             MATERIAL_CODE_SEPARATOR_FIELD]})
    assert restored.separator == ""
    assert restored.suggest("x", category="aggregate") == "AGG001"


def test_absent_separator_key_still_inherits_default():
    restored = MaterialCodePolicy.from_project(
        {"material_code_policy": CATEGORY_PREFIX})
    assert restored.separator is None
    assert restored.suggest("x", category="aggregate") == "AGG-001"


def test_save_path_does_not_coerce_empty_separator():
    from qs_engine.ui import views
    source = inspect.getsource(views.build_project_page)
    assert "separator=separator_var.get()," in source
    assert "separator_var.get() or None" not in source


# --- panel structure -------------------------------------------------------------

def test_panel_exposes_chips_hint_and_preview():
    from qs_engine.ui import views
    source = inspect.getsource(views.build_project_page)
    assert 'text="Material Coding Configuration"' in source
    assert 'text="Insert Token"' in source
    assert "CodePatternEngine.SUPPORTED_TOKENS" in source
    assert "preview_hint(" in source
    # preview strings stay the engine's, never a local reimplementation
    assert "material_code_preview(" in source


def test_preview_hint_is_wired_to_the_live_update():
    from qs_engine.ui import views
    source = inspect.getsource(views.build_project_page)
    assert "hint_var.set(preview_hint(" in source


# --- live panel behaviour --------------------------------------------------------

def _build_project_page():
    """Build the Project Setup page on a fresh root; returns teardown info.

    StringVars must attach to THIS root (repoint the default root), or
    a leaked root from an earlier test receives the variables while the
    widgets live here.
    """
    tkinter = pytest.importorskip("tkinter")
    from types import SimpleNamespace
    from qs_engine.master_data.repository import MasterDataRepository
    from qs_engine.ui import views
    from qs_engine.ui.session import TakeoffSession
    try:
        root = tkinter.Tk()
    except tkinter.TclError:  # pragma: no cover - display-dependent
        pytest.skip("no display")
    root.withdraw()
    previous_default_root = tkinter._default_root
    tkinter._default_root = root
    body = tkinter.ttk.Frame(root)
    body.pack(fill="both", expand=True)
    app = SimpleNamespace(session=TakeoffSession(),
                          repository=MasterDataRepository(),
                          refresh_status=lambda: None)
    try:
        views.build_project_page(body, app)
        root.update_idletasks()
    except Exception:
        tkinter._default_root = previous_default_root
        root.destroy()
        raise
    return root, body, previous_default_root


def _walk(container, predicate):
    found = []
    for child in container.winfo_children():
        if predicate(child):
            found.append(child)
        found.extend(_walk(child, predicate))
    return found


@pytest.fixture()
def panel_env():
    tkinter = pytest.importorskip("tkinter")
    root, body, previous = _build_project_page()
    try:
        yield tkinter, root, body
    finally:
        tkinter._default_root = previous
        root.destroy()


def _panel(body):
    panels = _walk(body, lambda w: w.winfo_class() == "TLabelframe"
                   and str(w.cget("text")) == "Material Coding Configuration")
    assert panels, "dynamic formatting panel missing"
    return panels[0]


def test_chips_offer_exactly_the_engine_tokens(panel_env):
    tkinter, root, body = panel_env
    panel = _panel(body)
    chip_groups = [child for child in panel.winfo_children()
                   if child.winfo_class() == "TLabelframe"
                   and str(child.cget("text")) == "Insert Token"]
    assert chip_groups, "token chip group missing"
    texts = [str(button.cget("text"))
             for button in _walk(chip_groups[0],
                                 lambda w: w.winfo_class() == "TButton")]
    assert tuple(texts) == CodePatternEngine.SUPPORTED_TOKENS


def test_chip_click_inserts_token_and_updates_preview(panel_env):
    tkinter, root, body = panel_env
    panel = _panel(body)
    chip_groups = [child for child in panel.winfo_children()
                   if child.winfo_class() == "TLabelframe"
                   and str(child.cget("text")) == "Insert Token"]
    buttons = {str(button.cget("text")): button
               for button in _walk(chip_groups[0],
                                   lambda w: w.winfo_class() == "TButton")}
    entries = _walk(panel, lambda w: w.winfo_class() == "TEntry"
                    and int(str(w.cget("width"))) >= 20)
    template_entry = entries[0]
    template_var = str(template_entry.cget("textvariable"))
    original = str(root.getvar(template_var))
    buttons["{SEQUENCE}"].invoke()
    updated = str(root.getvar(template_var))
    assert updated == original + "{SEQUENCE}"
    root.setvar(template_var, original)  # leave the page as found


def test_doubled_template_shows_flagged_preview_and_hint(panel_env):
    tkinter, root, body = panel_env
    panel = _panel(body)
    children = panel.winfo_children()
    caption_at = next(i for i, widget in enumerate(children)
                      if str(widget.cget("text")) == "Preview:")
    preview_label = children[caption_at + 1]
    hint_label = children[-1]
    template_var = str(_walk(
        panel, lambda w: w.winfo_class() == "TEntry"
        and int(str(w.cget("width"))) >= 20)[0].cget("textvariable"))
    root.setvar(template_var, DOUBLED_TEMPLATE)
    root.update_idletasks()
    assert str(root.getvar(str(preview_label.cget("textvariable")))) \
        == "AGG-AGG-001"
    hint = str(root.getvar(str(hint_label.cget("textvariable"))))
    assert "CATEGORY_ID" in hint
    assert "AGG-AGG-001" in hint


def test_clearing_separator_updates_preview_live(panel_env):
    tkinter, root, body = panel_env
    panel = _panel(body)
    children = panel.winfo_children()
    caption_at = next(i for i, widget in enumerate(children)
                      if str(widget.cget("text")) == "Preview:")
    preview_label = children[caption_at + 1]
    separator_entries = [
        child for child in children
        if child.winfo_class() == "TEntry"
        and int(str(child.cget("width"))) <= 8]
    assert separator_entries, "separator entry missing"
    sep_var = str(separator_entries[0].cget("textvariable"))
    root.setvar(sep_var, "")
    root.update_idletasks()
    assert str(root.getvar(str(preview_label.cget("textvariable")))) \
        == "AGG001"
