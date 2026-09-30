"""Rate-builder UX tests (Phase 23): resource search, kind-conditional
rows, picker selection, provisional sums, and catalogue usability.

All engine/parser contracts are asserted unchanged by the untouched
pre-existing suites; these tests cover only the new presentation and
workflow layer. Display tests are guarded and headless-safe.
"""

import inspect

import pytest

from qs_engine.ui import views


def _repo():
    from qs_engine.master_data.repository import MasterDataRepository
    return MasterDataRepository()


def _materials():
    return _repo().list("materials")


# --- search ------------------------------------------------------------------

def test_search_by_name_case_insensitive():
    matches = views.search_records(
        _materials(), "cement", ("key", "name", "category"))
    names = {row.get("name", "") for row in matches}
    assert "Portland Cement 42.5" in names
    assert matches, "cement should match catalogue entries"


def test_search_by_code_with_underscores():
    matches = views.search_records(
        _materials(), "portland_cement_42_5", ("key", "name", "category"))
    keys = {row.get("key", "") for row in matches}
    assert "portland_cement_42_5" in keys


def test_search_by_category_and_empty_query():
    assert views.search_records(_materials(), "", ("key",)) == _materials()
    matches = views.search_records(
        _materials(), "binder", ("key", "name", "category"))
    assert matches
    assert all("binder" in str(row.get("category", "")).lower()
               for row in matches)
    assert views.search_records(
        _materials(), "no-such-resource-xyz",
        ("key", "name", "category")) == []


def test_filter_catalogue_scope_and_status():
    records = _materials()
    codes = views.filter_catalogue(records, "ballast", scope="Code")
    assert {row.get("key", "") for row in codes} == {"ballast_20mm"}
    names = views.filter_catalogue(records, "Ballast", scope="Name")
    assert any("Ballast" in str(row.get("name", "")) for row in names)
    verified = views.filter_catalogue(records, status="VERIFIED")
    assert all(str(row.get("verification_status", "")) == "VERIFIED"
               for row in verified)
    everything = views.filter_catalogue(records)
    assert len(everything) == len(records) == 23


# --- kind-conditional fields ---------------------------------------------------

def test_rate_row_field_states_per_kind():
    material = views.rate_row_field_states("material")
    assert set(material["enabled"]) == {
        "key", "qty", "unit", "price", "waste", "desc"}
    assert material["picker"] == "materials"
    labour = views.rate_row_field_states("labour")
    assert "key" not in labour["enabled"]
    assert "waste" not in labour["enabled"]  # engine ignores it
    assert {"qty", "price", "desc"} <= set(labour["enabled"])
    assert labour["picker"] == "labour"
    plant = views.rate_row_field_states("plant")
    assert plant["enabled"] == ()
    assert plant["picker"] is None
    subcontract = views.rate_row_field_states("subcontract")
    assert set(subcontract["enabled"]) == {"price", "desc", "prov"}
    assert subcontract["picker"] is None


def test_resource_name_lookup_full_and_honest():
    name, _unit = views.resource_display_name(
        "materials", "portland_cement_42_5", _repo())
    assert name == "Portland Cement 42.5"  # full text, never truncated
    building = "Machine-Cut Building Stone"
    name, _unit = views.resource_display_name(
        "materials", "building_stone", _repo())
    assert name == building
    assert views.resource_display_name(
        "materials", "", _repo())[0] == "—"
    assert views.resource_display_name(
        "materials", "no-such-key", _repo())[0] == "⚠ unknown key"
    trade, _unit = views.resource_display_name(
        "labour", "mason", _repo())
    assert trade == "Mason"


def test_material_details_text_marks_nulls():
    record = {"key": "portland_cement_42_5",
              "name": "Portland Cement 42.5",
              "category": "binder", "unit": "bag",
              "density": None, "default_wastage_pct": None,
              "verification_status": "NEEDS_VERIFICATION"}
    text = views.material_details_text(record)
    assert "Portland Cement 42.5" in text
    assert "portland_cement_42_5" in text
    assert "— (unverified)" in text
    assert "NEEDS_VERIFICATION" in text


def test_provisional_serializes_opt_in_only():
    line = views.format_rate_line({
        "kind": "subcontract", "key": "", "qty": "", "price": "50",
        "waste": "", "desc": "PC", "provisional": True})
    assert line == "subcontract | amount=50 | desc=PC | provisional=yes"
    assert views.parse_rate_lines(line + "\n")[0]["provisional"] == "yes"
    legacy = views.format_rate_line({
        "kind": "subcontract", "key": "", "qty": "", "price": "50",
        "waste": "", "desc": "PC"})
    assert legacy == "subcontract | amount=50 | desc=PC"
    material = views.format_rate_line({
        "kind": "material", "key": "river_sand", "qty": "2",
        "price": "100", "waste": "5", "desc": "M",
        "provisional": True})
    assert "provisional" not in material  # material has no such field


def test_pending_material_key_defaults_none():
    from qs_engine.ui.session import TakeoffSession
    assert TakeoffSession().pending_material_key is None


def test_build_up_summary_uses_qs_terms():
    source = inspect.getsource(views.build_rates_page)
    assert "Composite Unit Rate" in source
    assert "Direct Cost" in source
    assert "Resource Code" in source  # retained technical heading


# --- display-guarded -----------------------------------------------------------

def _display_root():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    return root


def test_picker_dialog_lists_filter_and_select():
    root = _display_root()
    picked = []
    dialog = views.select_resource_dialog(
        root, "materials", _repo(), on_select=picked.append)
    assert dialog is not None
    trees = []

    def walk(widget):
        for child in widget.winfo_children():
            if child.winfo_class() == "Treeview":
                trees.append(child)
            walk(child)

    walk(dialog)
    assert len(trees) == 1
    assert len(trees[0].get_children()) == 23
    entries = []

    def walk_entries(widget):
        for child in widget.winfo_children():
            if (child.winfo_class() == "TEntry"
                    and str(child).endswith("resource_search")):
                entries.append(child)
            walk_entries(child)

    walk_entries(dialog)
    assert len(entries) == 1
    entries[0].focus_set()
    dialog.update_idletasks()
    entries[0].insert(0, "cement")
    entries[0].event_generate("<KeyRelease>")
    dialog.update_idletasks()
    narrowed = list(trees[0].get_children())
    assert 0 < len(narrowed) < 23
    trees[0].selection_set(narrowed[0])
    trees[0].event_generate("<<TreeviewSelect>>")
    dialog.update_idletasks()
    buttons = []

    def walk_buttons(widget):
        for child in widget.winfo_children():
            if ("Button" in child.winfo_class()
                    and child.cget("text") == "Select"):
                buttons.append(child)
            walk_buttons(child)

    walk_buttons(dialog)
    buttons[0].invoke()
    dialog.update_idletasks()
    assert len(picked) == 1
    assert picked[0].get("key")
    dialog.destroy()
    root.destroy()


def test_kind_switching_disables_irrelevant_fields():
    root = _display_root()
    from qs_engine.ui.views import QSApp
    app = QSApp()
    app.show("rates")
    app.update_idletasks()
    body = app.workspace.interior
    combos = []

    def walk(widget):
        for child in widget.winfo_children():
            if (child.winfo_class() == "TCombobox"
                    and list(child.cget("values"))[:1] == ["material"]):
                combos.append(child)
            walk(child)

    walk(body)
    assert combos, "kind selector row missing"
    kind_box = combos[0]
    parent = kind_box.master
    by_column = {}
    for child in parent.winfo_children():
        info = child.grid_info()
        if child.winfo_class() in ("TEntry", "TCombobox") and info:
            by_column[int(info["column"])] = child
    # Columns: 1 key, 2 qty, 3 unit, 4 price, 5 waste, 6 desc, 9 prov.
    assert set(by_column) >= {1, 2, 3, 4, 5, 6, 9}
    kind_box.set("labour")
    kind_box.event_generate("<<ComboboxSelected>>")
    app.update_idletasks()
    assert str(by_column[1].cget("state")) == "disabled"  # no trade key
    assert str(by_column[5].cget("state")) == "disabled"  # no wastage
    assert str(by_column[4].cget("state")) == "normal"  # rate/hr
    assert str(by_column[2].cget("state")) == "normal"  # hours
    kind_box.set("subcontract")
    kind_box.event_generate("<<ComboboxSelected>>")
    app.update_idletasks()
    assert str(by_column[4].cget("state")) == "normal"  # amount
    assert str(by_column[9].cget("state")) == "normal"  # provisional
    assert str(by_column[1].cget("state")) == "disabled"
    assert str(by_column[5].cget("state")) == "disabled"
    kind_box.set("plant")
    kind_box.event_generate("<<ComboboxSelected>>")
    app.update_idletasks()
    for column in (1, 2, 3, 4, 5, 6, 9):
        assert str(by_column[column].cget("state")) == "disabled"
    app.destroy()
    root.destroy()


def test_catalogue_search_filters_grid_and_handoff():
    root = _display_root()
    from qs_engine.master_data.repository import MasterDataRepository
    from qs_engine.ui.views import QSApp
    # Pin the fixture to the seed-only catalogue: the default app now
    # serves seed + user override materials (Phase 25), and this test's
    # assertion is about the shipped 23-row catalogue regardless of any
    # user materials stored on the machine.
    app = QSApp(repository=MasterDataRepository())
    app.show("materials")
    app.update_idletasks()
    body = app.workspace.interior
    search_boxes = []

    def walk(widget):
        for child in widget.winfo_children():
            if (child.winfo_class() == "TEntry"
                    and str(child).endswith("catalogue_search")):
                search_boxes.append(child)
            walk(child)

    walk(body)
    assert len(search_boxes) == 1
    grids = []

    def walk_grids(widget):
        for child in widget.winfo_children():
            if child.winfo_class() == "Treeview":
                grids.append(child)
            walk_grids(child)

    walk_grids(body)
    assert grids
    full = len(grids[0].get_children())
    assert full == 23
    search_boxes[0].focus_set()
    app.update_idletasks()
    search_boxes[0].insert(0, "cement")
    search_boxes[0].event_generate("<KeyRelease>")
    app.update_idletasks()
    narrowed = len(grids[0].get_children())
    assert 0 < narrowed < full
    grids[0].selection_set(grids[0].get_children()[0])
    grids[0].event_generate("<<TreeviewSelect>>")
    app.update_idletasks()
    picked_code = grids[0].item(
        grids[0].get_children()[0], "values")[0]
    assert picked_code, "selection unreadable"
    use_buttons = []

    def walk_buttons(widget):
        for child in widget.winfo_children():
            if ("Button" in child.winfo_class()
                    and child.cget("text") == "Use in Rate Builder"):
                use_buttons.append(child)
            walk_buttons(child)

    walk_buttons(body)
    assert len(use_buttons) == 1
    use_buttons[0].invoke()
    app.update_idletasks()
    assert app._current == "rates"
    rate_entries = []

    def walk_rates(widget):
        for child in widget.winfo_children():
            if child.winfo_class() == "TEntry":
                rate_entries.append(child)
            walk_rates(child)

    walk_rates(app.workspace.interior)
    key_texts = [entry.get() for entry in rate_entries]
    assert picked_code in key_texts, "pending key not consumed into row"
    assert app.session.pending_material_key is None
    app.destroy()
    root.destroy()


def test_project_badge_wraps_long_warnings():
    root = _display_root()
    from qs_engine.ui.views import QSApp
    app = QSApp()
    app.session.project["cement_density_kg_per_m3"] = (
        "Site laboratory batch record ref LAB-2026-0847 verified density")
    app.show("project")
    app.update_idletasks()
    badges = []

    def walk(widget):
        for child in widget.winfo_children():
            try:
                if ("Project override" in child.cget("text")
                        and child.winfo_class() == "TLabel"):
                    badges.append(child)
            except Exception:
                pass
            walk(child)

    walk(app.workspace.interior)
    assert badges, "override badge missing"
    assert int(badges[0].cget("wraplength")) > 0
    app.destroy()
    root.destroy()


def _rates_widgets(app):
    """(meta combos, first-row widget map) for the live Rate Builder."""
    from qs_engine.ui import views as _views

    body = app.workspace.interior
    combos = {}

    def walk_combos(widget):
        for child in widget.winfo_children():
            if child.winfo_class() == "TCombobox":
                try:
                    values = list(child.cget("values"))
                except Exception:
                    values = []
                if values == ["sequential", "parallel"]:
                    combos["Policy"] = child
                elif values == list(_views.RATE_WORK_UNITS):
                    combos["Rate Unit"] = child
            walk_combos(child)

    walk_combos(body)
    assert set(combos) == {"Rate Unit", "Policy"}
    host = None

    def walk_host(widget):
        nonlocal host
        for child in widget.winfo_children():
            try:
                texts = [c.cget("text")
                         for c in child.winfo_children()
                         if c.winfo_class() == "TLabel"]
            except Exception:
                texts = []
            if "Resource Code" in texts:
                host = child
                return
            walk_host(child)

    walk_host(body)
    assert host is not None
    first = {}
    for child in host.winfo_children():
        info = child.grid_info()
        if info and int(info["row"]) == 1:
            first[int(info["column"])] = child
    return combos, first, _views


def test_policy_combobox_limited_to_engine_policies():
    root = _display_root()
    from qs_engine.ui.views import QSApp
    app = QSApp()
    app.show("rates")
    app.update_idletasks()
    combos, _first, _views = _rates_widgets(app)
    policy = combos["Policy"]
    assert list(policy.cget("values")) == ["sequential", "parallel"]
    assert "flat" not in list(policy.cget("values"))
    assert "compound" not in list(policy.cget("values"))
    assert str(policy.cget("state")) == "readonly"
    assert policy.get() == "sequential"
    app.destroy()
    root.destroy()


def test_rate_unit_options_are_engine_supported():
    root = _display_root()
    from qs_engine.core.units import SUPPORTED_UNITS
    from qs_engine.ui.views import QSApp
    app = QSApp()
    app.show("rates")
    app.update_idletasks()
    combos, _first, _views = _rates_widgets(app)
    unit = combos["Rate Unit"]
    assert unit.get() == "m²"
    assert set(unit.cget("values")) <= set(SUPPORTED_UNITS)
    for unsupported in ("nr", "sum", "item", "t"):
        assert unsupported not in list(unit.cget("values"))
    assert str(unit.cget("state")) == "readonly"  # hardened: no free text
    app.destroy()
    root.destroy()


def test_component_unit_and_provisional_combos():
    root = _display_root()
    from qs_engine.ui.views import QSApp
    app = QSApp()
    app.show("rates")
    app.update_idletasks()
    _combos, first, views = _rates_widgets(app)
    unit_box = first[3]
    assert list(unit_box.cget("values")) == list(views.COMPONENT_UNITS)
    assert "readonly" not in str(unit_box.cget("state"))
    prov_box = first[9]
    assert list(prov_box.cget("values")) == ["No", "Yes"]
    assert prov_box.get() == "No"
    assert str(prov_box.cget("state")) == "readonly"
    app.destroy()
    root.destroy()


def test_placeholders_never_serialize():
    """A fresh row displays its cues; every cue still reads as a blank value
    through the widget API, the shared helper and the serialized payload."""
    root = _display_root()
    from qs_engine.ui import views
    from qs_engine.ui.views import QSApp
    app = QSApp()
    app.show("rates")
    app.update_idletasks()
    _combos, first, _views = _rates_widgets(app)
    key_entry = first[1]
    assert key_entry.display_text() == views.RATE_CODE_CUE
    assert key_entry.get() == ""
    assert key_entry.get_value() == ""
    assert views._entry_text(key_entry) == ""
    for column in (1, 2, 4, 5, 6):
        assert views._entry_text(first[column]) == ""
    views._set_entry_value(key_entry, "river_sand")
    assert views._entry_text(key_entry) == "river_sand"
    assert key_entry.get() == "river_sand"
    app.destroy()
    root.destroy()


def test_key_entry_stays_editable_for_expert_input():
    root = _display_root()
    from qs_engine.ui.views import QSApp
    app = QSApp()
    app.show("rates")
    app.update_idletasks()
    _combos, first, _views = _rates_widgets(app)
    assert str(first[1].cget("state")) == "normal"
    app.destroy()
    root.destroy()


def test_markups_helper_text_is_one_clean_line():
    """Task 2.3: the two stacked instruction lines collapsed into one."""
    root = _display_root()
    from qs_engine.ui.views import QSApp
    app = QSApp()
    app.show("rates")
    app.update_idletasks()
    texts = []

    def walk(widget):
        for child in widget.winfo_children():
            try:
                if child.winfo_class() == "TLabel":
                    texts.append(child.cget("text"))
            except Exception:
                pass
            walk(child)

    walk(app.workspace.interior)
    assert any(text.startswith("Markups") and "Label: Pct" in text
               for text in texts)
    assert not any(text == "Markups (label: pct per row):" for text in texts)
    assert not any("Format: Label: Pct" in text for text in texts)
    app.destroy()
    root.destroy()


def test_provisional_yes_flows_end_to_end():
    root = _display_root()
    from qs_engine.ui.views import QSApp
    app = QSApp()
    app.show("rates")
    app.update_idletasks()
    _combos, first, views = _rates_widgets(app)
    first[0].set("subcontract")
    first[0].event_generate("<<ComboboxSelected>>")
    views._set_entry_value(first[4], "200")
    views._set_entry_value(first[6], "PC Sum")
    first[9].set("Yes")
    app.update_idletasks()

    def find_text(widget, height):
        for child in widget.winfo_children():
            if (child.winfo_class() == "Text"
                    and str(child.cget("height")) == str(height)):
                return child
            found = find_text(child, height)
            if found is not None:
                return found
        return None

    body = app.workspace.interior
    buttons = []

    def walk_buttons(widget):
        for child in widget.winfo_children():
            if ("Button" in child.winfo_class()
                    and child.cget("text") == "Build Rate"):
                buttons.append(child)
            walk_buttons(child)

    walk_buttons(body)
    buttons[0].invoke()
    app.update_idletasks()
    lines_text = find_text(body, 6)
    assert lines_text is not None
    assert "provisional=yes" in lines_text.get("1.0", "end")
    app.destroy()
    root.destroy()


def test_default_no_provisional_matches_legacy_output():
    root = _display_root()
    from qs_engine.ui.views import QSApp
    app = QSApp()
    app.show("rates")
    app.update_idletasks()
    _combos, first, views = _rates_widgets(app)
    first[0].set("subcontract")
    first[0].event_generate("<<ComboboxSelected>>")
    views._set_entry_value(first[4], "200")
    views._set_entry_value(first[6], "PC Sum")
    app.update_idletasks()

    def find_text(widget, height):
        for child in widget.winfo_children():
            if (child.winfo_class() == "Text"
                    and str(child.cget("height")) == str(height)):
                return child
            found = find_text(child, height)
            if found is not None:
                return found
        return None

    body = app.workspace.interior
    buttons = []

    def walk_buttons(widget):
        for child in widget.winfo_children():
            if ("Button" in child.winfo_class()
                    and child.cget("text") == "Build Rate"):
                buttons.append(child)
            walk_buttons(child)

    walk_buttons(body)
    buttons[0].invoke()
    app.update_idletasks()
    lines_text = find_text(body, 6)
    assert "provisional" not in lines_text.get("1.0", "end")
    assert "subcontract | amount=200 | desc=PC Sum" in lines_text.get(
        "1.0", "end")
    app.destroy()
    root.destroy()
