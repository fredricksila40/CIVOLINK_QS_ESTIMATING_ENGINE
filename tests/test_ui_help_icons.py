"""HelpIconButton / guide-registry contract (runs headless, no display).

The shared header widget (qs_engine/ui/widgets.py) keeps its behaviour
inspectable without a Tk display: guide lookup, tooltip summary
derivation, icon choice, and the graceful headless fallback.  The
legacy "[?] Panel Guide" text buttons must never come back.
"""

import ast
from pathlib import Path

from qs_engine.ui import widgets
from qs_engine.ui.widgets import (HELP_ICON_INFO, HELP_ICON_QUESTION,
                                  HelpIconButton, close_all_popovers,
                                  close_all_tooltips, guide_text_for,
                                  register_guide, set_guide_resolver,
                                  summary_of)

VIEWS_SOURCE = (Path(__file__).parent.parent / "qs_engine" / "ui"
                / "views.py")


class _NoDisplayParent:
    """Parent stand-in that cannot host widgets: forces the headless path."""


def _headless_button(**kwargs):
    """A HelpIconButton built without a display (attributes still set)."""
    button = HelpIconButton(_NoDisplayParent(), **kwargs)
    assert button._headless is True
    return button


# --- tooltip summary derivation ------------------------------------

def test_summary_is_first_sentence_clipped():
    text = ("Enter the pour split and Check. Details, notes, and totals "
            "follow on many lines.")
    assert summary_of(text) == "Enter the pour split and Check."


def test_summary_long_text_gets_clip_marker():
    summary = summary_of("word " * 100)
    assert summary.endswith("\u2026")
    assert len(summary) <= 160


def test_summary_of_blank_text_is_empty():
    assert summary_of("") == ""
    assert summary_of(None) == ""


def test_bullet_bodies_sweep_into_one_line():
    body = ("\u2022 First step and stop.\n"
            "  \u2022 Second step, then Calculate.\n")
    assert summary_of(body) == "\u2022 First step and stop."


# --- guide registry ------------------------------------------------

def test_registered_text_is_served_and_missing_keys_fall_back():
    register_guide("widget-test-key", "Registry body text.")
    assert guide_text_for("widget-test-key") == "Registry body text."
    assert guide_text_for("widget-missing-key", "fallback") == "fallback"
    assert guide_text_for(None, "fallback") == "fallback"


def test_resolver_serves_unregistered_keys_and_errors_are_safe():
    served = []
    previous = widgets._RESOLVER      # restore views.py's resolver after

    def _resolver(key):
        served.append(key)
        if key == "boom":
            raise RuntimeError("resolver failure")
        return "served:" + key

    set_guide_resolver(_resolver)
    try:
        assert guide_text_for("anything") == "served:anything"
        assert "anything" in served
        # A failing resolver must not surface: the caller keeps its default.
        assert guide_text_for("boom", "unchanged") == "unchanged"
    finally:
        set_guide_resolver(previous)
    assert guide_text_for("anything", "gone") == "gone"


def test_views_registers_every_navigation_page():
    """PAGES keys must all resolve once views.py is imported."""
    from qs_engine.ui import views
    for page in views.PAGES:
        assert guide_text_for(page, ""), "no guide text for page %s" % page
    # The verification key reuses the modal text verbatim.
    assert guide_text_for("verification") == views.VERIFICATION_GUIDE_TEXT


# --- the widget itself ---------------------------------------------

def test_button_reads_guide_text_from_its_key():
    register_guide("widget-page-key", "Page body instructions.")
    button = _headless_button(guide_key="widget-page-key")
    assert button.guide_text == "Page body instructions."
    assert button.summary == "Page body instructions."


def test_explicit_text_and_summary_win_over_registry():
    button = _headless_button(guide_key="widget-page-key",
                              guide_text="Explicit guide.",
                              summary="Short tip")
    assert button.guide_text == "Explicit guide."
    assert button.summary == "Short tip"


def test_missing_key_degrades_to_empty_guide():
    button = _headless_button(guide_key="never-registered")
    assert button.guide_text == ""


def test_icon_choice_tracks_severity():
    info = _headless_button(guide_text="Info body.")
    warn = _headless_button(guide_text="Warn body.", severity="warn")
    question = _headless_button(guide_text="Q body.", severity="question")
    assert info._glyph == HELP_ICON_INFO
    assert warn._glyph == HELP_ICON_QUESTION
    assert question._glyph == HELP_ICON_QUESTION


def test_headless_button_state_mirrors_a_live_button():
    clicks = []
    button = _headless_button(guide_text="Body text.",
                              popup_title="Some Guide",
                              command=lambda: clicks.append("click"))
    assert button.tooltip_delay_ms == widgets.HELP_HOVER_DELAY_MS
    assert button.is_open is False
    assert button.guide is None and button.tooltip is None
    # Hover / leave / close must stay inert rather than raise.
    button._on_enter()
    button._on_leave()
    button.close()
    assert button.is_open is False
    # Click with no popover available falls back to the caller command.
    button.toggle()
    assert clicks == ["click"]


def test_headless_close_all_helpers_are_safe():
    close_all_tooltips()
    close_all_popovers()          # must not raise with nothing open
    close_all_popovers(except_guide=_headless_button(guide_text="Body."))


def test_legacy_popover_signature_is_preserved():
    """views.PopoverGuide(button, text) still works and stays headless."""
    from qs_engine.ui import views
    button = _headless_button(guide_text="Legacy body.")
    guide = views.PopoverGuide(button, "Legacy body.")
    assert guide.title == views.INSTRUCTION_TITLE
    assert guide.is_open is False and guide.is_pinned is False
    assert guide.show(pinned=True) is None     # no display: no window
    assert guide.is_open is False
    guide.dismiss_hover()
    guide.hide()


# --- legacy header buttons are gone --------------------------------

def test_legacy_panel_guide_buttons_removed():
    """The legacy "[?] Panel Guide" text button must not come back."""
    source = VIEWS_SOURCE.read_text(encoding="utf-8")
    assert '"[?] Panel Guide"' not in source       # bracket-era label
    assert "command=guide.toggle" in source or "PopoverGuide(button" in source
    # The compat label constant survives only as the widget-failure
    # fallback inside build_page_header - never as a page header control.
    assert source.count("text=GUIDE_BUTTON_TEXT") <= 1
    assert "button = HelpIconButton(" in source    # headers use the icon


def test_every_header_passes_a_guide_key():
    """Page headers resolve copy through the registry, not literals."""
    tree = ast.parse(VIEWS_SOURCE.read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "build_page_header"):
            continue
        keywords = {kw.arg for kw in node.keywords}
        if "guide_key" not in keywords:
            name = node.args[1].value if len(node.args) > 1 else "?"
            offenders.append(name)
    assert offenders == [], ("page header without guide_key: %s" % offenders)
