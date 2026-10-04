"""Catalogue table editability: Remove Selected / Restore Removed….

Covers the reversible removal overlay on the Materials Catalogue page:

* shipped (seed) materials leave the *view* through
  ``UserMaterialStore.hide_seed_material`` — the seed table is never
  written and the resolver keeps resolving the key for existing
  estimates;
* user materials leave through the soft-delete
  (``deactivate_material``) and come back with ``reactivate_material``;
* ``restore_removed_dialog`` puts either kind back;
* the overlay persists in ``user_materials.json`` and fails closed on
  malformed payloads.

Adding materials and editing categories are covered by
``test_phase5_material_codes.py``.
"""

import hashlib
import inspect
import json
from pathlib import Path

import pytest

from qs_engine.core.errors import ValidationError
from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.resources import build_material_stack
from qs_engine.resources.material_store import UserMaterialStore
from qs_engine.ui import views

SEED_TABLES = (Path(__file__).parent.parent / "qs_engine" /
               "master_data" / "tables")


def _seed_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(SEED_TABLES.glob("*.json"))}


@pytest.fixture()
def stack(tmp_path):
    return build_material_stack(MasterDataRepository(), tmp_path)


def _app_or_skip(repository):
    try:
        return views.QSApp(repository=repository)
    except Exception as exc:  # pragma: no cover - display-dependent
        pytest.skip(f"QSApp needs a display: {exc}")


def _walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


def _find_button(widget, text):
    for child in widget.winfo_children():
        if ("Button" in child.winfo_class()
                and child.cget("text") == text):
            return child
        found = _find_button(child, text)
        if found is not None:
            return found
    return None


def _grid(app):
    grids = [w for w in _walk(app.workspace.interior)
             if w.winfo_class() == "Treeview"]
    assert grids, "catalogue grid missing"
    return grids[0]


def _status_texts(app):
    return [str(w.cget("text")) for w in _walk(app.workspace.interior)
            if w.winfo_class() == "TLabel"
            and str(w.cget("style")) == "Status.TLabel"]


def _find_row(app, key):
    """iid of the catalogue row resolving to ``key`` (policy-agnostic)."""
    grid = _grid(app)
    for iid in grid.get_children():
        values = grid.item(iid, "values")
        record = views.resolve_material_reference(app, str(values[0]))
        if record is not None and str(record.get("key", "")) == key:
            return iid
    return None


def _find_toplevel(app, title):
    for child in app.winfo_children():
        if child.winfo_class() == "Toplevel" and child.title() == title:
            return child
    return None

def _diag(app, stack):
    """Failure context for dialog assertions (order-dependent runs)."""
    material_stack = getattr(app, "material_stack", None)
    return (f"status={_status_texts(app)} "
            f"hidden={stack.store.hidden_seed_keys()} "
            f"inactive={stack.store.inactive_materials()} "
            f"material_stack={'ok' if material_stack is not None else 'None'} "
            f"store={'ok' if getattr(material_stack, 'store', None) is not None else 'None'}")


def _find_in(widget, klass, predicate=lambda w: True):
    for w in _walk(widget):
        if w.winfo_class() == klass and predicate(w):
            return w
    return None


# --- wiring ----------------------------------------------------------------

def test_materials_page_wiring_remove_and_restore():
    source = inspect.getsource(views.build_materials_page)
    assert 'text="Remove Selected"' in source
    assert "on_remove_selected" in source
    assert 'text="Restore Removed…"' in source
    assert "on_restore_removed" in source
    assert "hide_seed_material" in source
    assert "deactivate_material" in source
    assert "catalogue_hidden_keys" in source
    # the page itself stays free of inline editors (pinned contract)
    assert "ttk.Entry" not in source
    signature = inspect.signature(views.material_catalogue_rows)
    assert "hidden" in signature.parameters
    assert callable(views.restore_removed_dialog)


# --- store: seed-hide overlay ---------------------------------------------

def test_hide_unhide_seed_material_overlay_roundtrip(tmp_path, stack):
    store = stack.store
    assert store.hidden_seed_keys() == []
    # hide is idempotent and stays a VIEW overlay: the resolver is intact
    assert store.hide_seed_material("river_sand") == ["river_sand"]
    assert store.hide_seed_material("river_sand") == ["river_sand"]
    assert store.hidden_seed_keys() == ["river_sand"]
    assert stack.resolver.get("materials", "river_sand")["name"] == (
        "River Sand")
    assert "river_sand" in [record["key"]
                            for record in stack.resolver.list("materials")]
    rows = views.material_catalogue_rows(
        stack.resolver, hidden=store.hidden_seed_keys())
    assert len(rows) == 22
    assert len(views.material_catalogue_rows(stack.resolver)) == 23
    # unhide restores the view
    assert store.unhide_seed_material("river_sand") == []
    assert store.hidden_seed_keys() == []
    with pytest.raises(ValidationError):
        store.unhide_seed_material("river_sand")
    # user keys and empty keys fail closed — never the seed overlay
    with pytest.raises(ValidationError, match="deactivate"):
        store.hide_seed_material("user:whatever")
    with pytest.raises(ValidationError):
        store.hide_seed_material("   ")
    # persistence: a restart over the same data dir keeps the overlay
    store.hide_seed_material("river_sand")
    again = build_material_stack(MasterDataRepository(), tmp_path)
    assert again.store.hidden_seed_keys() == ["river_sand"]
    # shipped master data untouched throughout
    assert len(MasterDataRepository().list("materials")) == 23


def test_material_catalogue_rows_hidden_is_view_only(tmp_path, stack):
    everything = views.material_catalogue_rows(stack.resolver)
    assert len(everything) == 23
    hidden = views.material_catalogue_rows(
        stack.resolver, hidden={"river_sand"})
    assert len(hidden) == 22
    # the resolver itself still lists the hidden material
    assert "river_sand" in [record["key"]
                            for record in stack.resolver.list("materials")]


def test_hidden_seed_keys_fail_closed_on_bad_payload(tmp_path):
    path = tmp_path / "user_materials.json"
    for payload in (
            {"schema_version": "1.0", "materials": [],
             "hidden_seed_keys": "nope"},
            {"schema_version": "1.0", "materials": [],
             "hidden_seed_keys": [123]},
            {"schema_version": "1.0", "materials": [],
             "hidden_seed_keys": ["user:oops"]}):
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValidationError, match="hidden_seed_keys"):
            UserMaterialStore(path=path, registry=None)
    # a legacy payload without the key loads cleanly (defaults to none)
    path.write_text(json.dumps({"schema_version": "1.0",
                                "materials": []}), encoding="utf-8")
    store = UserMaterialStore(path=path, registry=None)
    assert store.hidden_seed_keys() == []


# --- store: user-material soft delete / restore ---------------------------

def test_reactivate_material_roundtrip(tmp_path, stack):
    store = stack.store
    record = store.add_material({"name": "Site Sand", "code": "SITE-001",
                                 "category_id": "aggregate", "unit": "m³"})
    key = record["key"]
    assert key in [r["key"] for r in stack.resolver.list("materials")]
    store.deactivate_material(key)
    assert key not in [r["key"] for r in stack.resolver.list("materials")]
    assert [m["key"] for m in store.inactive_materials()] == [key]
    # deactivated = fail closed for lookups
    with pytest.raises(ValidationError):
        stack.resolver.get("materials", key)
    # restore brings it back under the same canonical key
    restored = store.reactivate_material(key)
    assert restored["active"] is True and restored["key"] == key
    assert key in [r["key"] for r in stack.resolver.list("materials")]
    assert store.inactive_materials() == []
    # idempotent on an already-active material
    assert store.reactivate_material(key)["key"] == key
    with pytest.raises(ValidationError):
        store.reactivate_material("user:never-created")


# --- page behaviour --------------------------------------------------------

def test_remove_selected_requires_selection(tmp_path, stack):
    app = _app_or_skip(stack.resolver)
    app.update_idletasks()
    try:
        app.show("materials")
        app.update()
        before = len(_grid(app).get_children())
        button = _find_button(app.workspace.interior, "Remove Selected")
        assert button is not None
        button.invoke()
        app.update()
        assert any("Select a material to remove first." in text
                   for text in _status_texts(app))
        assert stack.store.hidden_seed_keys() == []
        assert stack.store.inactive_materials() == []
        assert len(_grid(app).get_children()) == before
    finally:
        app.destroy()


def test_remove_and_restore_seed_material_end_to_end(tmp_path, stack):
    before = _seed_hashes()
    app = _app_or_skip(stack.resolver)
    app.update_idletasks()
    try:
        app.show("materials")
        app.update()
        grid = _grid(app)
        assert len(grid.get_children()) == 23
        iid = _find_row(app, "river_sand")
        assert iid is not None, "river_sand row missing from the catalogue"
        grid.selection_set(iid)
        app.update()
        _find_button(app.workspace.interior, "Remove Selected").invoke()
        app.update()
        # hidden from the VIEW only: store overlay set, grid row gone
        assert stack.store.hidden_seed_keys() == ["river_sand"]
        assert _find_row(app, "river_sand") is None
        assert len(grid.get_children()) == 22
        assert any(text == "22 of 22 resources"
                   for text in _status_texts(app)), _status_texts(app)
        assert any("'Restore Removed…' brings it back" in text
                   for text in _status_texts(app)), _status_texts(app)
        # existing estimates keep resolving the hidden seed key
        assert stack.resolver.get("materials", "river_sand")["name"] == (
            "River Sand")
        assert _seed_hashes() == before
        # restore through the page button + dialog
        _find_button(app.workspace.interior, "Restore Removed…").invoke()
        app.update()
        dialog = _find_toplevel(app, "Restore Removed Materials")
        assert dialog is not None, _diag(app, stack)
        picker = _find_in(dialog, "Listbox")
        assert picker is not None and picker.size() == 1
        picker.selection_set(0)
        _find_button(dialog, "Restore Selected").invoke()
        app.update()
        assert stack.store.hidden_seed_keys() == []
        assert _find_row(app, "river_sand") is not None
        assert len(grid.get_children()) == 23
        assert any("Restored 1 material(s)" in text
                   for text in _status_texts(app)), _status_texts(app)
        assert _seed_hashes() == before
    finally:
        app.destroy()


def test_remove_selected_soft_deletes_user_material(tmp_path, stack):
    before = _seed_hashes()
    record = stack.store.add_material({"name": "Site Sand",
                                       "code": "SITE-001",
                                       "category_id": "aggregate",
                                       "unit": "m³"})
    app = _app_or_skip(stack.resolver)
    app.update_idletasks()
    try:
        app.show("materials")
        app.update()
        grid = _grid(app)
        assert len(grid.get_children()) == 24
        row = next(iid for iid in grid.get_children()
                   if str(grid.item(iid, "values")[0]) == "SITE-001")
        grid.selection_set(row)
        app.update()
        _find_button(app.workspace.interior, "Remove Selected").invoke()
        app.update()
        key = record["key"]
        # soft delete: gone from the effective catalogue, nothing else
        assert [m["key"] for m in stack.store.inactive_materials()] == [key]
        assert key not in [r["key"] for r in stack.resolver.list("materials")]
        assert len(grid.get_children()) == 23
        assert _find_row(app, key) is None
        with pytest.raises(ValidationError):
            stack.resolver.get("materials", key)
        # shipped data untouched
        assert _seed_hashes() == before
        # restore through the dialog
        _find_button(app.workspace.interior, "Restore Removed…").invoke()
        app.update()
        dialog = _find_toplevel(app, "Restore Removed Materials")
        assert dialog is not None, _diag(app, stack)
        picker = _find_in(dialog, "Listbox")
        assert picker is not None and picker.size() == 1
        picker.selection_set(0)
        _find_button(dialog, "Restore Selected").invoke()
        app.update()
        assert stack.store.inactive_materials() == []
        assert len(grid.get_children()) == 24
        assert key in [r["key"] for r in stack.resolver.list("materials")]
    finally:
        app.destroy()


def test_restore_removed_button_reports_nothing_to_restore(tmp_path, stack):
    app = _app_or_skip(stack.resolver)
    app.update_idletasks()
    try:
        app.show("materials")
        app.update()
        _find_button(app.workspace.interior, "Restore Removed…").invoke()
        app.update()
        assert any("Nothing to restore" in text
                   for text in _status_texts(app)), _status_texts(app)
        assert _find_toplevel(app, "Restore Removed Materials") is None
    finally:
        app.destroy()


def test_restore_removed_button_opens_dialog_and_cancels(tmp_path, stack):
    stack.store.hide_seed_material("river_sand")
    app = _app_or_skip(stack.resolver)
    app.update_idletasks()
    try:
        app.show("materials")
        app.update()
        _find_button(app.workspace.interior, "Restore Removed…").invoke()
        app.update()
        dialog = _find_toplevel(app, "Restore Removed Materials")
        assert dialog is not None, _diag(app, stack)
        _find_button(dialog, "Cancel").invoke()
        app.update()
        assert _find_toplevel(app, "Restore Removed Materials") is None
        # cancelling changes nothing
        assert stack.store.hidden_seed_keys() == ["river_sand"]
    finally:
        app.destroy()


# --- restore dialog --------------------------------------------------------

def test_restore_dialog_roundtrip_and_empty_state(tmp_path, stack):
    store = stack.store
    store.hide_seed_material("river_sand")
    record = store.add_material({"name": "Site Sand", "code": "SITE-001",
                                 "category_id": "aggregate", "unit": "m³"})
    store.deactivate_material(record["key"])
    app = _app_or_skip(stack.resolver)
    app.update_idletasks()
    try:
        counts = []
        handle = views.restore_removed_dialog(
            app, store, on_restored=counts.append)
        assert handle is not None
        assert handle["dialog"].title() == "Restore Removed Materials"
        assert handle["listbox"].size() == 2
        labels = [handle["listbox"].get(i) for i in range(2)]
        assert any("River Sand (default material)" in label
                   for label in labels)
        assert any("Site Sand (user material)" in label
                   for label in labels)
        # Restore Selected without a selection: hint, dialog stays open
        handle["restore"].invoke()
        app.update()
        assert "Select at least one material" in handle["status"].cget(
            "text")
        assert handle["dialog"].winfo_exists()
        # restore ONLY the user material
        handle["listbox"].selection_clear(0, "end")
        handle["listbox"].selection_set(1)
        handle["restore"].invoke()
        app.update()
        assert counts == [1]
        assert handle["result"] == 1
        assert store.hidden_seed_keys() == ["river_sand"]
        assert store.inactive_materials() == []
        # reopen: Restore All takes the remaining seed hide
        again = views.restore_removed_dialog(app, store,
                                             on_restored=counts.append)
        assert again["listbox"].size() == 1
        again["restore_all"].invoke()
        app.update()
        assert counts == [1, 1]
        assert store.hidden_seed_keys() == []
        # empty state: buttons disabled, honest status
        empty = views.restore_removed_dialog(app, store)
        assert empty is not None
        assert empty["listbox"].size() == 0
        assert empty["restore"].instate(["disabled"])
        assert empty["restore_all"].instate(["disabled"])
        assert "Nothing to restore" in empty["status"].cget("text")
        empty["cancel"].invoke()
        app.update()
    finally:
        app.destroy()
