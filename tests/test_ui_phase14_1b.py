"""Phase 14.1B visual-correction tests.

Save-semantics and pure helpers run headless everywhere. Widget
geometry assertions need a display: they run when Tk() constructs and
skip otherwise, so the suite stays green on headless CI.
"""

import pytest

from qs_engine.core.errors import ValidationError
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


# --- save semantics: Saved means a successful save, nothing less ----------

def test_empty_new_session_not_saved():
    session = TakeoffSession()
    assert session.project_saved is False
    assert "○ No Project" in views.build_status_text(session)


def test_empty_profile_not_saved():
    session = TakeoffSession()
    session.set_project(name="   ", reference="")
    assert session.project_saved is False
    assert "○ No Project" in views.build_status_text(session)


def test_populated_unsaved_profile_not_saved():
    session = TakeoffSession()
    session.set_project(name="Demo", reference="D-1")
    assert session.project_saved is False
    assert "○ No Project" in views.build_status_text(session)


def test_successful_populated_save_marks_saved():
    session = TakeoffSession()
    saved = session.save_project(name="Demo", reference="D-1")
    assert saved == {"name": "Demo", "reference": "D-1"}
    assert session.project_saved is True
    assert "● Project Saved" in views.build_status_text(session)


def test_blank_save_raises_and_stays_unsaved():
    session = TakeoffSession()
    with pytest.raises(ValidationError):
        session.save_project(name="   ", reference="")
    assert session.project_saved is False
    assert session.project == {}


def test_clearing_profile_revokes_saved():
    session = TakeoffSession()
    session.save_project(name="Demo")
    assert session.project_saved is True
    session.clear_project()
    assert session.project == {}
    assert session.project_saved is False
    assert "○ No Project" in views.build_status_text(session)


# --- display-guarded geometry proof -----------------------------------------

@requires_display
def test_project_setup_entries_share_label_rows():
    body = __import__("tkinter").Frame(ROOT)
    entries = {}

    import tkinter.ttk as ttk
    for field, label in (("standard", "Measurement Standard"),
                         ("edition", "Edition")):
        row = ttk.Frame(body)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, width=24).pack(side="left")
        entry = ttk.Entry(row)
        entry.pack(side="left", fill="x", expand=True)
        entries[field] = entry
    body.update_idletasks()
    for label_text, widget in (("Measurement Standard", entries["standard"]),
                               ("Edition", entries["edition"])):
        parent = widget.master
        labels = [child.cget("text") for child in parent.winfo_children()
                  if child.winfo_class() == "TLabel"]
        assert label_text in labels
        assert abs(widget.winfo_rooty()
                   - parent.winfo_children()[0].winfo_rooty()) < 30
    body.destroy()


@requires_display
def test_chrome_false_suppresses_panel_header():
    import tkinter.ttk as ttk
    from qs_engine.ui.controllers import concrete_controller
    host = __import__("tkinter").Frame(ROOT)
    panel = views.QSPanel(host, "concrete", concrete_controller,
                          repository=None, chrome=False)
    panel.update_idletasks()

    def walk(widget, found):
        for child in widget.winfo_children():
            cls = child.winfo_class()
            if cls == "TLabelframe":
                found["frames"].append(child.cget("text"))
            if cls == "TLabel":
                try:
                    style = child.cget("style")
                except Exception:
                    style = ""
                if style == "Header.TLabel":
                    found["headers"].append(child.cget("text"))
            walk(child, found)
        return found

    found = walk(panel, {"frames": [], "headers": []})
    assert found["headers"] == []
    assert "ℹ️ Panel Instructions & Input Guide" not in found["frames"]
    panel.destroy()


@requires_display
def test_scrollable_frame_docking():
    frame = views.ScrollableFrame(ROOT)
    frame.update_idletasks()
    assert frame.vbar.pack_info()["side"] == "right"
    assert frame.vbar.pack_info()["fill"] == "y"
    assert frame.canvas.pack_info()["fill"] == "both"
    assert frame.canvas.pack_info()["expand"] in (1, "1")
    assert frame.interior.winfo_parent() == str(frame.canvas)
    frame.destroy()


@requires_display
def test_haulage_summary_renders_after_form():
    import tkinter.ttk as ttk
    from qs_engine.master_data.repository import MasterDataRepository
    from types import SimpleNamespace
    body = ttk.Frame(ROOT)
    app = SimpleNamespace(session=TakeoffSession(),
                          repository=MasterDataRepository(),
                          refresh_status=lambda: None)
    views.build_takeoff_page(
        body, app, "logistics", "logistics", add_enabled=False,
        summary_spec=("Haulage Summary", (("limiting", "Limiting"),)))
    body.update_idletasks()
    children = list(body.winfo_children())
    panels = [w for w in children if type(w).__name__ == "QSPanel"]
    summaries = [w for w in children
                 if w.winfo_class() == "TLabelframe"
                 and w.cget("text") == "Haulage Summary"]
    assert panels, "expected the embedded form panel"
    assert summaries, "expected the summary card"
    assert children.index(panels[0]) < children.index(summaries[0])


@requires_display
def test_status_bar_segments_wrap():
    # Phase 16.2: the single status label became a segmented bar (one
    # cell per status_segments() entry plus separators and watermark).
    import tkinter.ttk as ttk
    from qs_engine.ui.views import QSApp, STATUS_SEGMENTS
    app_holder = {}
    try:
        app_holder["app"] = QSApp()
    except Exception as exc:
        pytest.skip(f"QSApp needs a display: {exc}")
    try:
        app = app_holder["app"]
        app.update_idletasks()
        assert len(app._segments) == len(STATUS_SEGMENTS) == 5
        for label in app._segments:
            assert int(label.cget("wraplength")) > 0
        separators = [child for child in app.status_bar.winfo_children()
                      if child.winfo_class() == "TSeparator"]
        assert len(separators) == len(STATUS_SEGMENTS) - 1
        assert app.watermark.cget("text") == "Powered by CIVOLINK"
        assert app.status_bar.pack_info()["side"] == "bottom"
        assert app.status_bar.pack_info()["fill"] == "x"
    finally:
        app.destroy()


# --- Phase 23.1: ScrollableFrame hover-binding lifecycle fix -----------------

def test_show_calls_refresh_wheel_bindings():
    """Regression: QSApp.show() must rebind <Enter> on dynamically created
    children so _bind_wheel fires on first mouse entry. Without it,
    bind_all(<MouseWheel>) is never registered and scrolling silently
    fails over freshly loaded page content."""
    import inspect
    source = inspect.getsource(views.QSApp.show)
    assert "refresh_wheel_bindings" in source, (
        "QSApp.show() must call self.workspace.refresh_wheel_bindings() "
        "after PAGES[key]() creates new children."
    )


@requires_display
def test_dynamic_children_get_enter_binding_after_refresh():
    """Regression: After refresh_wheel_bindings(), dynamically added children
    must have <Enter> bindings so _on_sub_enter -> _bind_wheel fires on mouse
    entry, registering the global <MouseWheel> handler.
    """
    from qs_engine.ui.views import ScrollableFrame
    import tkinter as tk
    import tkinter.ttk as ttk

    parent = tk.Frame(ROOT)
    parent.pack()
    frame = ScrollableFrame(parent)
    frame.pack(fill="both", expand=True)
    frame.update_idletasks()

    children = []
    for i in range(5):
        lbl = ttk.Label(frame.interior, text="Row %d" % i)
        lbl.pack(anchor="w", pady=2)
        children.append(lbl)
    frame.interior.update_idletasks()

    # Without refresh: new children have NO <Enter> binding
    unbound = [c for c in children if not c.bind("<Enter>")]
    assert len(unbound) == len(children), \
        "Children must lack bindings before refresh"

    # With refresh: all children gain <Enter> binding
    frame.refresh_wheel_bindings()
    bound = [c for c in children if c.bind("<Enter>")]
    assert len(bound) == len(children), \
        "After refresh, all children must have <Enter> — got %d/%d" % (
            len(bound), len(children))

    # _bind_wheel must register bind_all<MouseWheel> on the canvas
    assert frame._hover_keys_active is False
    frame._bind_wheel()
    assert frame._hover_keys_active is True
    binding = frame.canvas.bind_all("<MouseWheel>")
    assert binding, "After _bind_wheel, canvas must have bind_all(MouseWheel)"

    frame.destroy()
    parent.destroy()
