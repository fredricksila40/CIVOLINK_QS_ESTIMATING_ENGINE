"""Phase 14.1 UI patch batch tests: headless, no widgets.

Covers the profile predicate, chrome flag defaults, adaptive label
widths, and status text honesty. Widget layout itself (packing,
scrolling, wrapping) needs a display and is verified visually.
Existing tests are untouched.
"""

import inspect
import pytest

from qs_engine.ui import views
from qs_engine.ui.session import TakeoffSession


def _display():
    """A withdrawn root for geometry checks, or None without a display."""
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


def test_has_profile_requires_non_empty_value():
    session = TakeoffSession()
    assert session.has_profile() is False
    session.set_project(name="  ", reference="")
    assert session.has_profile() is False
    session.set_project(name="Demo")
    assert session.has_profile() is True


def test_status_blank_profile_reports_no_project():
    session = TakeoffSession()
    session.set_project(name="   ", reference="")
    text = views.build_status_text(session)
    assert "○ No Project" in text
    assert "● Project Saved" not in text


def test_status_named_profile_reports_saved():
    session = TakeoffSession()
    session.save_project(name="Demo", reference="D-1")
    text = views.build_status_text(session)
    assert "● Project Saved" in text
    assert "○ No Project" not in text


def test_qspanel_chrome_defaults_on():
    params = inspect.signature(views.QSPanel.__init__).parameters
    assert params["chrome"].default is True
    assert params["action_label"].default == "Calculate"
    assert params["on_result"].default is None


def test_label_column_width_adaptive():
    assert views.label_column_width([("a", "Short")]) == 24
    assert views.label_column_width(
        views.PANEL_SPECS["finishes"][2]) >= len(
            "Kind (plaster/screed/tiles/paint)")
    for _key, (_title, _name, fields) in views.PANEL_SPECS.items():
        assert views.label_column_width(fields) >= max(
            [24] + [len(label) for _, label in fields])


def test_takeoff_page_accepts_layout_options():
    params = inspect.signature(views.build_takeoff_page).parameters
    assert params["add_enabled"].default is True
    assert params["summary_spec"].default is None


def test_scrollable_frame_class_present():
    assert hasattr(views, "ScrollableFrame")
    source = inspect.getsource(views.ScrollableFrame)
    assert ".interior" in source
    assert "yscrollcommand" in source
    assert "MouseWheel" in source


def test_scrollable_frame_precision_touchpad_delta_guard():
    """Regression: <MouseWheel> handler must guard small touchpad deltas
    against truncation to zero (abs(delta) < 120)."""
    source = inspect.getsource(views.ScrollableFrame._scroll)
    assert "abs(delta) < 120" in source
    assert "int(-1 * (delta / 120))" in source


@requires_display
def test_precision_touchpad_small_delta_scrolls():
    """Precision touchpads emit small wheel deltas (<120) that must still
    scroll instead of truncating to zero."""
    from types import SimpleNamespace
    frame = views.ScrollableFrame(ROOT)
    frame.update_idletasks()

    y_calls, x_calls = [], []
    frame.canvas.yview_scroll = (
        lambda lines, unit: y_calls.append((lines, unit)))
    frame.canvas.xview_scroll = (
        lambda lines, unit: x_calls.append((lines, unit)))

    # Small positive delta (touchpad tick) — truncates to 0 without guard
    frame._scroll(SimpleNamespace(delta=60, state=0))
    assert y_calls == [(-1, "units")], \
        f"small positive delta should scroll up (-1 units), got {y_calls}"

    # Small negative delta (opposite direction)
    y_calls.clear()
    frame._scroll(SimpleNamespace(delta=-60, state=0))
    assert y_calls == [(1, "units")], \
        f"small negative delta should scroll down (+1 units), got {y_calls}"

    # Zero delta → no scroll at all
    y_calls.clear()
    frame._scroll(SimpleNamespace(delta=0, state=0))
    assert not y_calls, "zero delta must not trigger any scroll"

    # Shift+wheel + small delta → horizontal pan
    x_calls.clear()
    frame._scroll(SimpleNamespace(delta=60, state=0x1))
    assert x_calls == [(-1, "units")], \
        f"shift+touchpad should scroll horizontally, got {x_calls}"

    frame.destroy()


@requires_display
def test_cursor_inside_terminates_outside_frame():
    """Regression: the ancestor walk must terminate (not loop) for
    widgets outside the frame — the root window's parent resolves to
    itself, which previously froze the app on the first wheel event
    outside the content pane."""
    import tkinter as tk
    frame = views.ScrollableFrame(ROOT)
    frame.update_idletasks()
    outsider = tk.Label(ROOT, text="outside")
    outsider.pack()
    ROOT.update_idletasks()
    try:
        assert frame._is_cursor_inside(outsider) is False
        assert frame._is_cursor_inside(frame.interior) is True
        assert frame._is_cursor_inside(frame.canvas) is True
    finally:
        outsider.destroy()
        frame.destroy()


def test_nav_and_pages_unchanged():
    assert set(views.PAGES) == {
        "overview", "project", "concrete", "masonry", "rebar",
        "earthworks", "finishes", "materials", "labour_plant",
        "logistics", "reconciliation", "rates", "boq", "estimate",
        "excel", "corpdoc", "valuations", "mix_design",
    }
    assert set(views.PANEL_SPECS) == {
        "project", "concrete", "masonry", "earthworks", "finishes",
        "labour", "plant", "logistics", "rates", "boq", "mix_design",
    }


@requires_display
def test_canvas_content_width_matches_parent():
    """Canvas content window width expands to match full workspace width."""
    frame = views.ScrollableFrame(ROOT)
    frame.update_idletasks()
    child = frame.interior
    parent = frame.canvas
    assert child.winfo_width() == parent.winfo_width(), (
        f"Canvas content width {child.winfo_width()} != parent canvas width "
        f"{parent.winfo_width()}")
    frame.destroy()
