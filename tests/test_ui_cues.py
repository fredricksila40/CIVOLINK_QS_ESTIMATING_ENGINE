"""Cue-standardisation tests: safe ghost text across every UI form.

Pins the presentation contract of the cue pass (safe placeholder entry,
Rate Builder cleanup, systemic take-off cues). The contract is one rule:
a cue is muted example text that NO reader can ever mistake for input —
not ``get()``, not a panel form getter, not a controller payload, not a
serialized rate line, not a saved project profile.

Engine, parser and controller behaviour stays asserted by the untouched
pre-existing suites; nothing here recalculates. Display tests are guarded
and headless-safe (skipped when Tk cannot open a display).
"""

import inspect

import pytest

from qs_engine.ui import views


# --- helpers -----------------------------------------------------------------

def _display_root():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    return root


def _cue_widget(root, cue="e.g., Test Cue", factory=None, **kwargs):
    """A packed, updated cue widget of the given kind."""
    factory = factory or views.CueEntry
    widget = factory(root, cue=cue, width=24, **kwargs)
    widget.pack()
    root.update_idletasks()
    return widget


def _foreground(widget):
    return str(widget.cget("foreground"))


def _walk(widget, predicate):
    found = []

    def descend(node):
        for child in node.winfo_children():
            try:
                if predicate(child):
                    found.append(child)
            except Exception:
                pass
            descend(child)

    descend(widget)
    return found


def _buttons(widget, label):
    return _walk(widget, lambda c: ("Button" in c.winfo_class()
                                    and str(c.cget("text")) == label))


def _cue_widgets(widget):
    return _walk(widget, lambda c: isinstance(c, views.CueEntry))


# --- approved cue text (source pins, no display needed) ----------------------

def test_cue_colour_is_muted():
    assert views.CUE_TEXT_COLOR == "#888888"


def test_takeoff_field_cues_match_the_approved_table():
    """Every audited take-off/commercial field carries its example cue."""
    assert views.FIELD_CUES == {
        ("concrete", "element"): "e.g., Ground Floor Slab S1",
        ("concrete", "class_key"): "e.g., C20 or C25",
        ("masonry", "element"): "e.g., W1 - 200mm Outer Leaf",
        ("masonry", "unit_key"): "e.g., concrete_block_200mm",
        ("earthworks", "element"): "e.g., Strip Footing Trench Line A-C",
        ("finishes", "element"): "e.g., Internal Wall Plaster (12mm)",
        ("logistics", "element"): "e.g., Site to Quarry (15 km)",
    }
    assert views.PROJECT_FIELD_CUES == {
        "name": "e.g., Proposed Kitise Residence",
    }


def test_cues_are_examples_never_instructions():
    for cue in list(views.FIELD_CUES.values()) \
            + list(views.PROJECT_FIELD_CUES.values()) \
            + list(views.RATE_DESCRIPTION_CUES.values()):
        assert cue.startswith("e.g.,"), cue
        assert "Click" not in cue, cue


def test_cue_data_dictionary_is_real_engine_vocabulary():
    """A cue must never advertise a value the engine would reject."""
    from qs_engine.master_data.repository import MasterDataRepository
    repo = MasterDataRepository()
    grades = views.concrete_grade_choices(repo)
    assert "C20" in grades and "C25" in grades
    masonry_units = {str(rec.get("key", ""))
                     for rec in repo.list("masonry_units")}
    assert "concrete_block_200mm" in masonry_units


def test_rate_description_cue_replaces_the_self_repeating_word():
    """Task 2.1: the Description column no longer echoes its own heading."""
    assert "Description" not in views.RATE_DESCRIPTION_CUES.values()
    assert views.rate_description_cue("material") == "e.g., 20mm Ballast"
    assert views.rate_description_cue("labour") == "e.g., Class 1 Mason"
    assert views.rate_description_cue("subcontract") == "e.g., PC sum"
    # Plant rows are priced by the Plant take-off: their cells stay disabled,
    # so they carry no cue at all (a hint there would lie about what works).
    assert views.rate_description_cue("plant") == ""
    assert views.rate_description_cue("") == ""
    for kind, cue in views.RATE_DESCRIPTION_CUES.items():
        assert len(cue) <= views.RATE_DESCRIPTION_WIDTH, kind


def test_rate_description_cell_width_is_unchanged():
    """The cue fits the pre-existing cell, so no column gets pushed out."""
    assert views.RATE_DESCRIPTION_WIDTH == 20


def test_markups_header_collapsed_to_one_line_in_source():
    source = inspect.getsource(views.build_rates_page)
    assert "Markups \u2014 Label: Pct" in source
    assert "Markups (label: pct per row)" not in source
    assert "Format: Label: Pct" not in source


def test_picker_search_cue_is_wired_to_the_picker_dialog():
    source = inspect.getsource(views.select_resource_dialog)
    assert "PICKER_SEARCH_CUE" in source
    assert views.PICKER_SEARCH_CUE == "Search catalog description..."


def test_panel_forms_build_their_cues_from_the_single_map():
    source = inspect.getsource(views.QSPanel.__init__)
    assert "FIELD_CUES.get" in source
    assert "CueEntry" in source and "CueCombobox" in source


def test_project_page_builds_cue_aware_identity_fields():
    source = inspect.getsource(views.build_project_page)
    assert "PROJECT_FIELD_CUES" in source
    assert "set_value(" in source

# --- CueEntry / CueCombobox contract (display) -------------------------------

def test_cue_entry_starts_muted_and_reads_blank():
    root = _display_root()
    entry = _cue_widget(root, cue="e.g., Ground Floor Slab S1")
    assert entry.display_text() == "e.g., Ground Floor Slab S1"
    assert _foreground(entry) == views.CUE_TEXT_COLOR
    assert entry.get() == ""
    assert entry.get_value() == ""
    assert views._entry_text(entry) == ""
    root.destroy()


def test_focus_in_clears_the_cue_and_restores_colour():
    root = _display_root()
    entry = _cue_widget(root)
    default_colour = entry._placeholder_fg
    entry.event_generate("<FocusIn>")
    root.update()
    assert entry.display_text() == ""
    assert _foreground(entry) != views.CUE_TEXT_COLOR
    assert _foreground(entry) == default_colour
    root.destroy()


def test_focus_out_restores_the_cue_only_while_blank():
    root = _display_root()
    entry = _cue_widget(root)
    entry.event_generate("<FocusIn>")
    root.update()
    entry.event_generate("<FocusOut>")
    root.update()
    assert entry.display_text() == entry._placeholder_text
    assert entry.get() == ""
    assert _foreground(entry) == views.CUE_TEXT_COLOR

    entry.event_generate("<FocusIn>")
    entry.insert(0, "Slab S2")
    entry.event_generate("<FocusOut>")
    root.update()
    assert entry.display_text() == "Slab S2"
    assert entry.get() == "Slab S2"
    assert _foreground(entry) != views.CUE_TEXT_COLOR
    root.destroy()


def test_whitespace_only_input_counts_as_blank():
    root = _display_root()
    entry = _cue_widget(root)
    entry.event_generate("<FocusIn>")
    entry.insert(0, "   ")
    entry.event_generate("<FocusOut>")
    root.update()
    assert entry.display_text() == entry._placeholder_text
    assert entry.get() == ""
    assert views._entry_text(entry) == ""
    root.destroy()


def test_focus_in_never_deletes_user_text():
    root = _display_root()
    entry = _cue_widget(root)
    entry.set_value("W1 - 200mm Outer Leaf")
    for _ in range(3):
        entry.event_generate("<FocusIn>")
        root.update()
        entry.event_generate("<FocusOut>")
        root.update()
    assert entry.display_text() == "W1 - 200mm Outer Leaf"
    assert entry.get() == "W1 - 200mm Outer Leaf"
    root.destroy()


def test_set_value_clears_the_cue_and_blank_re_arms_it():
    root = _display_root()
    entry = _cue_widget(root)
    entry.set_value("C20")
    assert entry.display_text() == "C20"
    assert entry.get() == "C20"
    entry.set_value("")
    assert entry.display_text() == entry._placeholder_text
    assert entry.get() == ""
    root.destroy()


def test_raw_insert_drops_the_cue_first():
    """Programmatic writes must never splice data onto ghost text."""
    root = _display_root()
    entry = _cue_widget(root)
    entry.insert(0, "river_sand")
    assert entry.display_text() == "river_sand"
    assert entry.get() == "river_sand"
    root.destroy()


def test_set_cue_retargets_without_stacking_behaviour():
    root = _display_root()
    entry = _cue_widget(root, cue="e.g., First")
    entry.set_cue("e.g., Second")
    entry.set_cue("e.g., Second")
    assert entry.display_text() == "e.g., Second"
    entry.event_generate("<FocusIn>")
    root.update()
    assert entry.display_text() == ""
    entry.event_generate("<FocusOut>")
    root.update()
    assert entry.display_text() == "e.g., Second"
    entry.set_cue("")
    assert entry.display_text() == ""
    assert entry.get() == ""
    root.destroy()


def test_cues_work_on_a_disabled_cell():
    """A disabled cell keeps the (state-safe) cue contract too."""
    root = _display_root()
    entry = _cue_widget(root, cue="e.g., Stale")
    entry.config(state="disabled")
    entry.set_cue("")
    root.update_idletasks()
    assert entry.display_text() == ""
    assert str(entry.cget("state")) == "disabled"
    root.destroy()

# --- CueCombobox contract (display) ------------------------------------------

def test_cue_combobox_cue_reads_blank_and_pick_becomes_data():
    root = _display_root()
    combo = _cue_widget(root, cue="e.g., C20 or C25",
                        factory=views.CueCombobox,
                        values=["C15", "C20", "C25"])
    assert combo.display_text() == "e.g., C20 or C25"
    assert combo.get() == ""
    assert combo.get_value() == ""
    combo.current(1)                      # a dropdown pick
    combo.event_generate("<<ComboboxSelected>>")
    root.update()
    assert combo.display_text() == "C20"
    assert combo.get() == "C20"
    assert _foreground(combo) != views.CUE_TEXT_COLOR
    combo.set("")
    assert combo.display_text() == "e.g., C20 or C25"
    assert combo.get() == ""
    root.destroy()


def test_on_text_changed_fires_for_programmatic_edits():
    """Search fields re-filter without a mirrored ghost-value StringVar."""
    root = _display_root()
    entry = _cue_widget(root)
    seen = []
    entry.on_text_changed = lambda: seen.append(entry.get())
    entry.delete(0, "end")
    entry.insert(0, "cement")
    assert seen[-1] == "cement"
    entry.set_value("river sand")
    assert seen[-1] == "river sand"
    root.destroy()


# --- form getters / payload extraction (display) -----------------------------

def _panel_payloads(spec_keys, root):
    """(collect() output, captured controller payload) per spec key."""
    from qs_engine.master_data.repository import MasterDataRepository
    repo = MasterDataRepository()
    out = []
    for spec_key in spec_keys:
        seen = []

        def spy(inputs, _repo, _overrides=None, sink=seen):
            sink.append(dict(inputs))
            return None

        panel = views.QSPanel(root, spec_key, spy, repo)
        root.update_idletasks()
        collected = panel.collect()
        panel.run()
        out.append((spec_key, collected, seen[0]))
        panel.destroy()
    return out


def test_every_panel_form_collects_no_cue_text():
    root = _display_root()
    try:
        for spec_key, collected, payload in _panel_payloads(
                tuple(k for k, spec in views.PANEL_SPECS.items() if spec[2]),
                root):
            assert collected, spec_key
            assert set(collected.values()) == {""}, spec_key
            assert set(payload.values()) == {""}, spec_key
    finally:
        root.destroy()


def test_panel_cue_text_is_displayed_but_never_submitted():
    root = _display_root()
    try:
        panel = views.QSPanel(root, "masonry", lambda *a: None, None)
        root.update_idletasks()
        entry = panel._entries["element"]
        assert entry.display_text() == views.FIELD_CUES[("masonry", "element")]
        assert panel.collect()["element"] == ""
        entry.set_value("W1 - 200mm Outer Leaf")
        assert panel.collect()["element"] == "W1 - 200mm Outer Leaf"
        panel.destroy()
    finally:
        root.destroy()


def test_concrete_grade_picker_cue_never_becomes_a_grade_key():
    root = _display_root()
    try:
        from qs_engine.master_data.repository import MasterDataRepository
        panel = views.QSPanel(root, "concrete", lambda *a: None,
                              MasterDataRepository())
        root.update_idletasks()
        grade = panel._entries["class_key"]
        assert grade.display_text() == views.FIELD_CUES[("concrete",
                                                        "class_key")]
        # An untouched panel resolves to "no grade", never to the cue text.
        assert panel.collect()["class_key"] == ""
        assert views.resolve_concrete_class_key("") == ""
        grade.set("C20")
        assert panel.collect()["class_key"] == "class_c20"
        panel.destroy()
    finally:
        root.destroy()


def test_takeoff_pages_show_the_approved_cues():
    """Every audited take-off panel renders its example cue on the page."""
    import tkinter.ttk as ttk
    from types import SimpleNamespace
    from qs_engine.master_data.repository import MasterDataRepository
    from qs_engine.ui.session import TakeoffSession
    root = _display_root()
    try:
        for spec_key in ("concrete", "masonry", "earthworks", "finishes",
                         "logistics"):
            frame = ttk.Frame(root)
            app = SimpleNamespace(session=TakeoffSession(),
                                  repository=MasterDataRepository(),
                                  refresh_status=lambda: None)
            views.build_takeoff_page(frame, app, spec_key, spec_key)
            root.update_idletasks()
            shown = {w.display_text() for w in _cue_widgets(frame)}
            assert views.FIELD_CUES[(spec_key, "element")] in shown, spec_key
            frame.destroy()
    finally:
        root.destroy()


# --- page-level cleanliness (display) ----------------------------------------

def _rates_app(root):
    """The Rate Builder page on a lightweight app stand-in."""
    import tkinter.ttk as ttk
    from types import SimpleNamespace
    from qs_engine.master_data.repository import MasterDataRepository
    from qs_engine.ui.session import TakeoffSession
    body = ttk.Frame(root)
    app = SimpleNamespace(session=TakeoffSession(),
                          repository=MasterDataRepository(),
                          refresh_status=lambda: None)
    views.build_rates_page(body, app)
    root.update_idletasks()
    return body, app


def _kind_selector(body):
    found = _walk(body, lambda c: c.winfo_class() == "TCombobox"
                  and list(c.cget("values"))[:1] == [views.
                                                     RATE_COMPONENT_KINDS[0]])
    assert found, "kind selector row missing"
    return found[0]


def _text_box(body, height):
    found = _walk(body, lambda c: c.winfo_class() == "Text"
                  and str(c.cget("height")) == str(height))
    assert found, f"missing {height}-line text box"
    return found[0]


def test_rate_grid_serializes_no_cue_text_across_kind_switches():
    """Kind switching retargets cell cues without ever serializing one."""
    root = _display_root()
    try:
        body, _app = _rates_app(root)
        for kind in views.RATE_COMPONENT_KINDS:
            _kind_selector(body).set(kind)
            _kind_selector(body).event_generate("<<ComboboxSelected>>")
            root.update_idletasks()
        _buttons(body, "Build Rate")[0].invoke()
        root.update_idletasks()
        serialized = _text_box(body, 6).get("1.0", "end")
        assert "e.g.," not in serialized
        assert "Code / Item ID" not in serialized
        assert views.PICKER_HINT not in serialized
        assert "desc=Description" not in serialized
        # Every component cell still reads blank after the round trip.
        for widget in _cue_widgets(body):
            assert widget.get() == ""
    finally:
        root.destroy()


def test_rate_grid_description_cue_follows_the_component_kind():
    root = _display_root()
    try:
        body, _app = _rates_app(root)
        desc = [w for w in _cue_widgets(body)
                if w.display_text().startswith("e.g., 20mm")]
        assert desc, "material description cue missing"
        for kind, cue in views.RATE_DESCRIPTION_CUES.items():
            _kind_selector(body).set(kind)
            _kind_selector(body).event_generate("<<ComboboxSelected>>")
            root.update_idletasks()
            assert desc[0].display_text() == cue, kind
            assert desc[0].get() == ""
        _kind_selector(body).set("plant")
        _kind_selector(body).event_generate("<<ComboboxSelected>>")
        root.update_idletasks()
        assert desc[0].display_text() == ""
        assert str(desc[0].cget("state")) == "disabled"
    finally:
        root.destroy()


def test_rate_grid_marks_up_header_is_one_line():
    root = _display_root()
    try:
        body, _app = _rates_app(root)
        labels = [str(c.cget("text"))
                  for c in _walk(body, lambda w: w.winfo_class() == "TLabel")]
        headers = [text for text in labels if text.startswith("Markups")]
        assert headers == ["Markups \u2014 Label: Pct (e.g., Overhead: 10, "
                           "Profit: 15)"]
    finally:
        root.destroy()


def test_project_profile_save_never_stores_cue_text():
    import tkinter.ttk as ttk
    from types import SimpleNamespace
    from qs_engine.master_data.repository import MasterDataRepository
    from qs_engine.ui.session import TakeoffSession
    root = _display_root()
    try:
        session = TakeoffSession()
        body = ttk.Frame(root)
        app = SimpleNamespace(session=session,
                              repository=MasterDataRepository(),
                              refresh_status=lambda: None)
        views.build_project_page(body, app)
        root.update_idletasks()
        name = [w for w in _cue_widgets(body)
                if w.display_text() == views.PROJECT_FIELD_CUES["name"]]
        assert name, "project name cue missing"
        # A cue-only form is an empty profile: it must be refused, never
        # silently saved as ghost text.
        _buttons(body, "Save Profile")[0].invoke()
        root.update_idletasks()
        assert session.project == {}
        assert session.project_saved is False
        # A real entry saves verbatim, and the cue is gone with it.
        name[0].set_value("Kitise Residence")
        _buttons(body, "Save Profile")[0].invoke()
        root.update_idletasks()
        assert session.project["name"] == "Kitise Residence"
        assert session.project_saved is True
        assert all(views.CUE_TEXT_COLOR not in str(value)
                   for value in session.project.values())
    finally:
        root.destroy()


def test_picker_dialog_cue_does_not_filter_the_catalogue():
    from qs_engine.master_data.repository import MasterDataRepository
    root = _display_root()
    try:
        dialog = views.select_resource_dialog(root, "materials",
                                             MasterDataRepository())
        assert dialog is not None
        search = _walk(dialog, lambda c: str(c).endswith("resource_search"))[0]
        tree = _walk(dialog, lambda c: c.winfo_class() == "Treeview")[0]
        assert search.display_text() == views.PICKER_SEARCH_CUE
        assert len(tree.get_children()) == 23  # untouched dialog lists all
        search.insert(0, "cement")
        assert 0 < len(tree.get_children()) < 23
        dialog.destroy()
    finally:
        root.destroy()

