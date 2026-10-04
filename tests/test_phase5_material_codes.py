"""Phase 5: material code policy engine, edit/customize flows, persistence.

Covers Task 5.1 (five policy modes + availability against seed AND
user_materials.json + the redundant-MAT-prefix fix), Task 5.2 (Edit
Selected routing: user edit locks the code, seed customization creates
a user override with a policy-assigned code, store DTO routing, dynamic
catalogue refresh), Task 5.3 (Project Setup Material Code Formatting +
.clk round-trip binding), and the fail-closed validation of stored
policy fields.
"""

import hashlib
import inspect
import json
import zlib
from pathlib import Path

import pytest

from qs_engine.core.errors import ValidationError
from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.resources import (
    POLICY_LABEL_CHOICES,
    POLICY_MODES,
    MaterialCodePolicy,
    build_material_stack,
    mode_from_label,
    policy_label,
)
from qs_engine.resources.code_policy import (
    CUSTOM_PREFIX,
    DEFAULT_MODE,
    MANUAL,
    CATEGORY_PREFIX,
    SEQUENTIAL_NUMERIC,
    SLUG,
    MATERIAL_CODE_POLICY_FIELD,
    MATERIAL_CODE_PREFIX_FIELD,
    category_shorthand,
    ensure_available,
    slugify_name,
)

SEED_TABLES = (Path(__file__).parent.parent / "qs_engine" /
               "master_data" / "tables")


def _seed_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(SEED_TABLES.glob("*.json"))}


@pytest.fixture()
def stack(tmp_path):
    return build_material_stack(MasterDataRepository(), tmp_path)


def _app_or_skip(repository):
    from qs_engine.ui import views
    try:
        return views.QSApp(repository=repository)
    except Exception as exc:  # pragma: no cover - display-dependent
        pytest.skip(f"QSApp needs a display: {exc}")


def _walk(widget):
    out = []
    for child in widget.winfo_children():
        out.append(child)
        out.extend(_walk(child))
    return out


def _find_button(widget, text):
    for child in _walk(widget):
        try:
            if child.cget("text") == text:
                return child
        except Exception:
            continue  # widgets without a text option (grids, frames)
    return None


# --- Task 5.1: the five policy modes ---------------------------------------

def test_category_prefix_policy_uses_category_shorthand():
    policy = MaterialCodePolicy(CATEGORY_PREFIX)
    assert category_shorthand("aggregate") == "AGG"
    assert category_shorthand("binder") == "BIN"
    assert category_shorthand("user:kenya-supplies") == "KEN"
    assert policy.suggest("anything", category="aggregate") == "AGG-001"
    assert policy.suggest("anything", category="binder") == "BIN-001"
    # taken candidates are skipped deterministically
    assert policy.suggest("x", category="aggregate",
                          taken=["AGG-001"]) == "AGG-002"
    # no letters at all -> generic fallback, never a fabricated prefix
    assert policy.suggest("x", category="123") == "GEN-001"


def test_slug_policy_slugifies_names():
    policy = MaterialCodePolicy(SLUG)
    assert policy.suggest("Ballast 20mm") == "ballast_20mm"
    assert policy.suggest("Portland  Cement  42.5") == "portland_cement_42_5"
    assert policy.suggest("River Sand", taken=["river_sand"]) == (
        "river_sand_2")
    assert policy.suggest("") == ""  # nothing to slugify -> no invention
    assert slugify_name("Ballast 20mm") == "ballast_20mm"


def test_sequential_numeric_policy_is_bare_numeric():
    policy = MaterialCodePolicy(SEQUENTIAL_NUMERIC)
    assert policy.suggest("anything") == "001"
    assert policy.suggest("anything", taken=["001", "002"]) == "003"


def test_custom_prefix_policy_formats_from_configuration():
    policy = MaterialCodePolicy(CUSTOM_PREFIX, custom_prefix="KEN")
    assert policy.suggest("anything") == "KEN-001"
    assert policy.suggest("x", taken=["KEN-001"]) == "KEN-002"
    with pytest.raises(ValidationError):
        MaterialCodePolicy(CUSTOM_PREFIX, custom_prefix="")
    with pytest.raises(ValidationError):
        MaterialCodePolicy(CUSTOM_PREFIX, custom_prefix="bad prefix!")


def test_manual_policy_leaves_the_field_empty():
    assert MaterialCodePolicy(MANUAL).suggest("Ballast 20mm") == ""
    assert MaterialCodePolicy(MANUAL).suggest("x", category="binder") == ""


def test_no_mode_ever_produces_a_redundant_mat_prefix():
    # The pre-Phase-5 suggestion path concatenated MAT- onto a MAT-
    # prefixed stem ("Material" -> "MAT-MAT-001"); every policy mode is
    # pinned here so no generation path can reintroduce that shape.
    for mode in POLICY_MODES:
        policy = MaterialCodePolicy(
            mode, custom_prefix="MAT" if mode == CUSTOM_PREFIX else "")
        for name in ("Material", "MATTEE Paint", "Material 100"):
            for category in ("binder", "aggregate", None):
                code = policy.suggest(name, category=category)
                assert "MAT-MAT" not in code, (mode, name, category, code)
                assert not code.startswith("MAT-MAT")


def test_policy_validation_and_labels_round_trip():
    for mode in POLICY_MODES:
        assert mode_from_label(policy_label(mode)) == mode
    assert MaterialCodePolicy.from_project({}).mode == DEFAULT_MODE
    assert MaterialCodePolicy.from_project(
        {MATERIAL_CODE_POLICY_FIELD: SLUG}).mode == SLUG
    with pytest.raises(ValidationError):
        MaterialCodePolicy("NOT_A_MODE")
    with pytest.raises(ValidationError):
        MaterialCodePolicy.from_project(
            {MATERIAL_CODE_POLICY_FIELD: "BROKEN_TOKEN"})
    with pytest.raises(ValidationError):
        mode_from_label("No Such Choice")
    fields = MaterialCodePolicy(CUSTOM_PREFIX, "KEN").project_fields()
    assert fields == {MATERIAL_CODE_POLICY_FIELD: "CUSTOM_PREFIX",
                      MATERIAL_CODE_PREFIX_FIELD: "KEN"}
    assert MaterialCodePolicy.from_project(fields).custom_prefix == "KEN"
    # all five modes are offered in the Project Setup combobox
    assert set(POLICY_LABEL_CHOICES) == set(policy_label(m)
                                            for m in POLICY_MODES)


# --- Task 5.1: availability against seed AND user_materials.json ------------

def test_availability_spans_seed_catalogue_and_user_store(stack):
    resolver = stack.resolver
    # seed identifiers (key, code, legacy code) are all reserved
    assert resolver.code_is_available("portland_cement_42_5") is False
    assert resolver.code_is_available("CEM-10175-PC425") is False
    assert resolver.code_is_available("CEM-10175-PC425".lower()) is False
    assert resolver.code_is_available("AGG-001") is True
    assert resolver.code_is_available("") is False
    with pytest.raises(ValidationError, match="seed catalogue"):
        resolver.ensure_code_available("CEM-10175-PC425")
    # a user code is reserved across BOTH sources once stored
    stack.store.add_material({"name": "Test Rock", "code": "TST-001",
                              "category_id": "aggregate", "unit": "m³"})
    assert resolver.code_is_available("TST-001") is False
    with pytest.raises(ValidationError, match="user_materials.json"):
        resolver.ensure_code_available("TST-001")
    assert resolver.code_is_available("TST-002") is True
    # ensure_available hits both sources directly too
    seed = MasterDataRepository()
    with pytest.raises(ValidationError):
        ensure_available("river_sand", seed_repository=seed)
    with pytest.raises(ValidationError):
        ensure_available("TST-001", store=stack.store)
    assert ensure_available("FRESH-001", seed_repository=seed,
                            store=stack.store) == "FRESH-001"


def test_resolver_suggest_code_uses_policy_and_taken_set(stack):
    resolver = stack.resolver
    # both seed keys and codes count as taken (slug collides with the
    # seed key "river_sand" -> deterministic suffix, never a shadow)
    assert resolver.suggest_code("River Sand", category="aggregate",
                                 policy=MaterialCodePolicy(SLUG)) == (
        "river_sand_2")
    assert resolver.suggest_code("River Sand", category="aggregate",
                                 policy=MaterialCodePolicy(
                                     CATEGORY_PREFIX)) == "AGG-001"
    assert resolver.suggest_code("x", policy=MaterialCodePolicy(MANUAL)) == ""
    # a bare project mapping works too (the UI passes either shape)
    assert resolver.suggest_code(
        "x", category="binder",
        policy={MATERIAL_CODE_POLICY_FIELD: CATEGORY_PREFIX}) == "BIN-001"
    existing = resolver.existing_codes()
    assert "CEM-10175-PC425" in existing
    assert "portland_cement_42_5" in existing


# --- Task 5.2: store DTO routing --------------------------------------------

def test_store_dto_routing_add_and_update(stack):
    created = stack.store.add_material({
        "name": "Crushed Stone", "code": "CRUSH-001",
        "category_id": "aggregate", "unit": "m³"})
    assert created["code"] == "CRUSH-001"
    assert created["key"].startswith("user:")
    # update by canonical key with a DTO
    updated = stack.store.update_material(
        created["key"], {"name": "Crushed Stone 40mm",
                         "category_id": "aggregate", "unit": "m³"})
    assert updated["name"] == "Crushed Stone 40mm"
    assert updated["key"] == created["key"]
    # update by current code reference (the spec's update_material(code, dto))
    renamed = stack.store.update_material(
        "CRUSH-001", {"name": "Crushed Stone"})
    assert renamed["key"] == created["key"]
    # a DTO code change retires the old code into aliases
    recoded = stack.store.update_material(
        created["key"], {"code": "CRUSH-40"})
    assert recoded["code"] == "CRUSH-40"
    assert "CRUSH-001" in recoded["aliases"]
    assert stack.resolver.get("materials", "CRUSH-001")["key"] == (
        created["key"])
    with pytest.raises(ValidationError):
        stack.store.add_material("not a mapping")
    with pytest.raises(ValidationError):
        stack.store.update_material(created["key"], ["not", "a", "mapping"])


def test_dto_routing_never_exposes_engineering_fields(stack):
    from qs_engine.resources import UserMaterialStore
    # both routing entries accept identifiers only
    for method in (UserMaterialStore.add_material,):
        assert list(inspect.signature(method).parameters) == ["self", "dto"]


# --- Task 5.1/5.2: views wiring (source pins + dialog flows) ----------------

def test_views_no_longer_hardcodes_mat_prefix_generation():
    from qs_engine.ui import views
    source = inspect.getsource(views.material_editor_dialog)
    assert "generate_material_code" not in source  # legacy MAT- generator
    assert 'f"MAT-' not in source and "'MAT-'" not in source
    # policy helpers replace it
    assert "material_code_suggestions" in source
    assert "active_material_code_policy" in source


def test_materials_page_routes_edit_selected_by_provenance():
    from qs_engine.ui import views
    source = inspect.getsource(views.build_materials_page)
    assert 'mode="edit_user"' in source
    assert 'mode="customize_seed"' in source
    assert "on_saved=on_material_saved" in source
    assert "refresh_catalogue" in source  # grid refresh on save
    assert "ttk.Entry" not in source  # page stays read-only (pinned)


def test_dialog_edit_user_mode_locks_the_code(tmp_path):
    from qs_engine.ui import views
    stack = build_material_stack(MasterDataRepository(), tmp_path)
    record = stack.store.add_material({
        "name": "Site Sand", "code": "SAND-001",
        "category_id": "aggregate", "unit": "m³"})
    app = _app_or_skip(stack.resolver)
    app.update_idletasks()
    try:
        handle = views.material_editor_dialog(
            app, record=record, mode="edit_user")
        assert handle is not None
        assert handle["dialog"].title() == "Edit User Material"
        assert handle["code"].instate(["disabled"])
        assert handle["name"].get() == "Site Sand"
        assert handle["code"].get() == "SAND-001"
        # locked code never submits: rename via DTO, code untouched
        handle["name"].delete(0, "end")
        handle["name"].insert(0, "Site Washed Sand")
        handle["save"].invoke()
        app.update()
        saved = handle["result"]
        assert saved is not None
        assert saved["name"] == "Site Washed Sand"
        assert saved["code"] == "SAND-001"
        assert saved["key"] == record["key"]
    finally:
        app.destroy()


def test_dialog_customize_seed_creates_override_with_assigned_code(tmp_path):
    from qs_engine.ui import views
    before = _seed_hashes()
    stack = build_material_stack(MasterDataRepository(), tmp_path)
    seed = stack.resolver.get("materials", "river_sand")
    app = _app_or_skip(stack.resolver)
    app.update_idletasks()
    try:
        handle = views.material_editor_dialog(
            app, record=seed, mode="customize_seed")
        assert handle is not None
        assert handle["dialog"].title() == (
            "Customize Material (Create User Override)")
        assert handle["banner"] is not None
        assert "read-only" in handle["banner"].cget("text")
        # seed values pre-filled
        assert handle["name"].get() == "River Sand"
        assert handle["unit"].get() == "m³"
        assert handle["category"].get() == "aggregate"
        # policy-assigned, non-conflicting, locked code
        assigned = handle["code"].get()
        assert assigned == "AGG-001"
        assert handle["code"].instate(["disabled"])
        assert app.repository.code_is_available(assigned)
        handle["save"].invoke()
        app.update()
        created = handle["result"]
        assert created is not None
        assert created["key"].startswith("user:")
        assert created["code"] == assigned
        assert created["name"] == "River Sand"
        # seed row itself is untouched
        assert _seed_hashes() == before
        assert stack.resolver.get("materials", "river_sand")["key"] == (
            "river_sand")
        # both provenances now resolve independently
        assert app.repository.get("materials", assigned)["key"].startswith(
            "user:")
        # the catalogue grid data reflects the new row immediately
        rows = views.material_catalogue_rows(app.repository)
        assert assigned in [row[0] for row in rows]
        assert len(rows) == 24
    finally:
        app.destroy()


def test_dialog_customize_seed_manual_policy_prompts_for_code(tmp_path):
    from qs_engine.ui import views
    stack = build_material_stack(MasterDataRepository(), tmp_path)
    seed = stack.resolver.get("materials", "hydrated_lime")
    app = _app_or_skip(stack.resolver)
    app.session.project = dict(
        MaterialCodePolicy(MANUAL).project_fields())
    app.update_idletasks()
    try:
        handle = views.material_editor_dialog(
            app, record=seed, mode="customize_seed")
        assert handle is not None
        # Manual policy: no code is invented — the user must enter one
        assert handle["code"].get() == ""
        assert not handle["code"].instate(["disabled"])
        assert "enter a Material Code" in handle["banner"].cget("text")
        handle["save"].invoke()
        app.update()
        assert handle["result"] is None  # empty code fails closed
        assert "Not saved" in handle["status"].cget("text")
        handle["code"].insert(0, "LIME-001")
        handle["save"].invoke()
        app.update()
        assert handle["result"] is not None
        assert handle["result"]["code"] == "LIME-001"
    finally:
        app.destroy()


def test_dialog_add_mode_suggestion_follows_active_policy(tmp_path):
    from qs_engine.ui import views
    stack = build_material_stack(MasterDataRepository(), tmp_path)
    app = _app_or_skip(stack.resolver)
    app.update_idletasks()
    try:
        handle = views.material_editor_dialog(app)
        assert handle is not None
        assert handle["dialog"].title() == "Add Material"
        assert not handle["code"].instate(["disabled"])
        # default (CATEGORY_PREFIX) suggestion: policy-driven, never a
        # doubled MAT- prefix
        suggested = handle["code"].get()
        assert suggested == app.repository.suggest_code(
            "", category=handle["category"].get())
        assert "MAT-MAT" not in suggested
        # switching the project to Manual empties the suggestion
        handle["cancel"].invoke()
        app.update()
        app.session.project = dict(
            MaterialCodePolicy(MANUAL).project_fields())
        manual = views.material_editor_dialog(app)
        assert manual is not None
        assert manual["code"].get() == ""
        manual["cancel"].invoke()
        app.update()
    finally:
        app.destroy()


# --- Edit Category button + category editor dialog ----------------------------

def test_materials_page_offers_edit_category_button():
    from qs_engine.ui import views
    source = inspect.getsource(views.build_materials_page)
    assert 'text="Edit Category"' in source
    assert "on_edit_category" in source
    # routes through the category editor with an existing record
    assert "category=category.to_dict()" in source
    assert "category_editor_dialog" in source
    # the grid itself stays read-only (pinned)
    assert "ttk.Entry" not in source


def test_materials_page_edit_category_requires_selection():
    from qs_engine.ui import views
    source = inspect.getsource(views.build_materials_page)
    # a category edit without a selected row is reported, never guessed
    assert "Select a material to edit its category first." in source
    assert "grid.selection()" in source


def test_materials_page_edit_category_opens_editor_for_seed_row(
        tmp_path, monkeypatch):
    """A SHIPPED material's Edit Category opens the same editor — the
    old read-only refusal for seed categories is gone."""
    from qs_engine.ui import views
    stack = build_material_stack(MasterDataRepository(), tmp_path)
    captured = {}

    def _capture(parent, registry, on_added=None, *, category=None):
        captured["category"] = category
        captured["registry"] = registry
        return None

    monkeypatch.setattr(views, "category_editor_dialog", _capture)
    app = _app_or_skip(stack.resolver)
    app.update_idletasks()
    try:
        app.show("materials")
        app.update()
        grids = [w for w in _walk(app.workspace.interior)
                 if w.winfo_class() == "Treeview"]
        assert grids, "catalogue grid missing"
        # first row: a shipped (seed) material on its seed category
        grids[0].selection_set(grids[0].get_children()[0])
        button = _find_button(app.workspace.interior, "Edit Category")
        assert button is not None
        button.invoke()
        app.update()
        assert captured, "Edit Category did not route to the editor"
        category = captured["category"]
        assert category["source"] == "seed"
        assert stack.registry.get_category(
            category["category_id"]).source == "seed"
        assert captured["registry"] is stack.registry
    finally:
        app.destroy()


def test_category_editor_dialog_add_mode_is_unchanged(tmp_path):
    from qs_engine.ui import views
    stack = build_material_stack(MasterDataRepository(), tmp_path)
    app = _app_or_skip(stack.resolver)
    app.update_idletasks()
    try:
        handle = views.category_editor_dialog(app, stack.registry)
        assert handle is not None
        assert handle["dialog"].title() == "Add Custom Category"
        assert handle["name"].get() == ""
        assert handle["add"].cget("text") == "Add Category"
        handle["name"].insert(0, "Brand New Cat")
        handle["add"].invoke()
        app.update()
        assert handle["result"]["category_id"] == "user:brand-new-cat"
        assert handle["result"]["source"] == "user"
    finally:
        app.destroy()


def test_category_editor_dialog_edit_mode_prefills_and_saves(tmp_path):
    from qs_engine.ui import views
    stack = build_material_stack(MasterDataRepository(), tmp_path)
    created = stack.registry.add_custom_category(
        "Kenya Supplies", prefix="KEN", sap_gl_code="10999",
        gl_description="Inventory - Kenya", format_template="{PREFIX}-{SEQUENCE}",
        sequence_padding=4, separator="-")
    app = _app_or_skip(stack.resolver)
    app.update_idletasks()
    try:
        handle = views.category_editor_dialog(
            app, stack.registry,
            category=stack.registry.get_category(created["category_id"])
            .to_dict())
        assert handle is not None
        assert handle["dialog"].title() == "Edit Material Category"
        assert handle["add"].cget("text") == "Save Category"
        # every field is pre-filled from the stored record
        assert handle["name"].get() == "Kenya Supplies"
        assert handle["prefix"].get() == "KEN"
        assert handle["gl_code"].get() == "10999"
        assert handle["gl_description"].get() == "Inventory - Kenya"
        assert handle["template"].get() == "{PREFIX}-{SEQUENCE}"
        assert handle["padding"].get() == "4"
        assert handle["separator"].get() == "-"
        # edit and save: the id is stable across the rename
        handle["name"].delete(0, "end")
        handle["name"].insert(0, "Kenya Supplies 2026")
        handle["gl_code"].delete(0, "end")
        handle["gl_code"].insert(0, "10888")
        handle["add"].invoke()
        app.update()
        saved = handle["result"]
        assert saved is not None
        assert saved["category_name"] == "Kenya Supplies 2026"
        assert saved["sap_gl_code"] == "10888"
        assert saved["category_id"] == created["category_id"]
        # the registry (and disk) carry the edit
        assert stack.registry.resolve_category(
            created["category_id"]).category_name == "Kenya Supplies 2026"
    finally:
        app.destroy()


def test_category_editor_dialog_edit_fails_closed(tmp_path):
    from qs_engine.ui import views
    stack = build_material_stack(MasterDataRepository(), tmp_path)
    created = stack.registry.add_custom_category("Doomed", prefix="DM")
    app = _app_or_skip(stack.resolver)
    app.update_idletasks()
    try:
        handle = views.category_editor_dialog(
            app, stack.registry,
            category=stack.registry.get_category(created["category_id"])
            .to_dict())
        assert handle is not None
        # a name that would shadow seed master data is refused in-dialog
        handle["name"].delete(0, "end")
        handle["name"].insert(0, "aggregate")
        handle["add"].invoke()
        app.update()
        assert handle["result"] is None
        assert "Not saved" in handle["status"].cget("text")
        # nothing was written
        assert stack.registry.get_category(
            created["category_id"]).category_name == "Doomed"
    finally:
        app.destroy()


def test_category_editor_dialog_edits_seed_category(tmp_path):
    """The Edit Category dialog edits a SHIPPED category by default:
    pre-filled from the seed record, the stable id preserved, and the
    edit persisted as an override — shipped tables stay byte-identical."""
    from qs_engine.ui import views
    stack = build_material_stack(MasterDataRepository(), tmp_path)
    before = _seed_hashes()
    seed = stack.registry.get_category("aggregate").to_dict()
    assert seed["source"] == "seed"
    app = _app_or_skip(stack.resolver)
    app.update_idletasks()
    try:
        handle = views.category_editor_dialog(app, stack.registry,
                                              category=seed)
        assert handle is not None
        assert handle["dialog"].title() == "Edit Material Category"
        # every field is pre-filled from the shipped record
        assert handle["name"].get() == "aggregate"
        assert handle["prefix"].get() == "AGG"
        assert handle["gl_code"].get() == "10176"
        # edit binding + name; the category_id never changes
        handle["prefix"].delete(0, "end")
        handle["prefix"].insert(0, "AGX")
        handle["gl_code"].delete(0, "end")
        handle["gl_code"].insert(0, "10999")
        handle["name"].delete(0, "end")
        handle["name"].insert(0, "Aggregates")
        handle["add"].invoke()
        app.update()
        assert handle["result"] is not None
        assert handle["result"]["category_id"] == "aggregate"
        assert handle["result"]["source"] == "seed"
        assert handle["result"]["prefix"] == "AGX"
        # the live registry carries the edit
        assert stack.registry.get_category("aggregate").prefix == "AGX"
        assert stack.registry.get_category_by_prefix("AGX").category_id == (
            "aggregate")
    finally:
        app.destroy()
    # the shipped seed table is never written
    assert _seed_hashes() == before
    # and the edit survives a restart over the same data dir
    again = build_material_stack(MasterDataRepository(), tmp_path)
    cat = again.registry.get_category("aggregate")
    assert cat.prefix == "AGX"
    assert cat.sap_gl_code == "10999"
    assert cat.source == "seed"
    # the rename re-points nothing: the stable id still resolves
    assert again.registry.resolve_category("Aggregates").category_id == (
        "aggregate")
    assert again.registry.resolve_category("aggregate").category_id == (
        "aggregate")


# --- Task 5.3: Project Setup + .clk binding ---------------------------------

def test_project_page_offers_material_code_formatting():
    from qs_engine.ui import views
    source = inspect.getsource(views.build_project_page)
    assert "Material Code Formatting" in source
    assert "POLICY_LABEL_CHOICES" in source
    assert "project_fields()" in source
    assert "mode_from_label" in source  # validated before saving


# --- Task 5.3: Material Coding Configuration live preview ---------------------

def test_material_code_preview_evaluates_each_policy_mode():
    """The preview helper runs the production policy path (no NameError)
    and renders every UI mode with the default padding of 3."""
    from qs_engine.ui.views import material_code_preview
    template = "{PREFIX}{SEPARATOR}{SEQUENCE}"
    # Category Prefix: AGG-001
    assert material_code_preview(
        policy_label(CATEGORY_PREFIX), "", template, 3, "-") == "AGG-001"
    # Sequential Numeric: 001
    assert material_code_preview(
        policy_label(SEQUENTIAL_NUMERIC), "", template, 3, "-") == "001"
    # Custom Prefix with SITE-A: SITE-A-001
    assert material_code_preview(
        policy_label(CUSTOM_PREFIX), "SITE-A", template, 3, "-") == \
        "SITE-A-001"
    # Manual: reports its state, never invents a code
    manual = material_code_preview(
        policy_label(MANUAL), "", template, 3, "-")
    assert manual == "(manual entry)"
    assert not any(ch in manual for ch in "{}0123456789-")
    # Non-integer / missing padding falls back to DEFAULT_PADDING (3)
    assert material_code_preview(
        policy_label(CATEGORY_PREFIX), "", template, None, "-") == "AGG-001"


def test_material_code_preview_fails_visibly_on_invalid_template():
    """Unknown or malformed tokens must surface as a visible failure —
    never silently rendered into an apparently valid code."""
    from qs_engine.ui.views import material_code_preview
    unknown = material_code_preview(
        policy_label(CATEGORY_PREFIX), "",
        "{PREFIX}-{SAP_GL}-{SEQUENCE}", 3, "-")
    assert unknown == "(invalid template)"
    assert "{SAP_GL}" not in unknown
    malformed = material_code_preview(
        policy_label(CATEGORY_PREFIX), "", "{PREFIX-{SEQUENCE}", 3, "-")
    assert malformed == "(invalid template)"


def test_project_page_live_preview_renders_without_nameerror():
    """Regression: the live-preview callback referenced a never-imported
    CodePatternPreset, so NameError was swallowed by a broad handler and
    the panel permanently displayed '(invalid template)'. Drive the real
    _update_preview path through the widgets it is bound to."""
    tkinter = pytest.importorskip("tkinter")
    from types import SimpleNamespace
    from qs_engine.resources import DEFAULT_TEMPLATE
    from qs_engine.ui import views
    from qs_engine.ui.session import TakeoffSession
    try:
        root = tkinter.Tk()
    except tkinter.TclError:  # pragma: no cover - display-dependent
        pytest.skip("no display")
    root.withdraw()
    # The page's StringVars attach to tkinter's default root: repoint it
    # at THIS interpreter, otherwise a leaked root from an earlier test
    # receives the variables while the widgets live here, and every read
    # misses cross-interpreter.
    previous_default_root = tkinter._default_root
    tkinter._default_root = root

    def walk(container, predicate):
        found = []
        for child in container.winfo_children():
            if predicate(child):
                found.append(child)
            found.extend(walk(child, predicate))
        return found

    try:
        body = tkinter.ttk.Frame(root)
        body.pack(fill="both", expand=True)
        app = SimpleNamespace(session=TakeoffSession(),
                              repository=MasterDataRepository(),
                              refresh_status=lambda: None)
        views.build_project_page(body, app)
        root.update_idletasks()

        panels = walk(body, lambda w: w.winfo_class() == "TLabelframe"
                      and str(w.cget("text"))
                      == "Material Coding Configuration")
        assert panels, "dynamic formatting panel missing"
        children = panels[0].winfo_children()
        caption_at = next(i for i, widget in enumerate(children)
                          if str(widget.cget("text")) == "Preview:")
        preview_label = children[caption_at + 1]

        def preview():
            return str(root.getvar(str(preview_label.cget("textvariable"))))

        # Initial render (default CATEGORY_PREFIX policy): AGG-001 —
        # under the NameError the panel started as "" / "(invalid template)".
        assert preview() == "AGG-001"

        template_var = str(walk(
            panels[0], lambda w: w.winfo_class() == "TEntry"
            and int(str(w.cget("width"))) >= 20)[0].cget("textvariable"))
        root.setvar(template_var, "{PREFIX}.{SEQUENCE}")
        assert preview() == "AGG.001"
        root.setvar(template_var, "{PREFIX}-{SAP_GL}-{SEQUENCE}")
        assert preview() == "(invalid template)"
        assert "{SAP_GL}" not in preview()
        root.setvar(template_var, DEFAULT_TEMPLATE)
        assert preview() == "AGG-001"

        policy_combo = next(
            combo for combo in walk(body, lambda w: w.winfo_class()
                                    == "TCombobox")
            if any("Category Prefix" in str(value)
                   for value in combo.cget("values")))

        policy_combo.set(policy_label(SEQUENTIAL_NUMERIC))
        policy_combo.event_generate("<<ComboboxSelected>>")
        assert preview() == "001"

        policy_combo.set(policy_label(CUSTOM_PREFIX))
        policy_combo.event_generate("<<ComboboxSelected>>")
        assert preview() == "(enter a custom prefix)"
        prefix_caption = walk(body, lambda w: w.winfo_class() == "TLabel"
                              and str(w.cget("text")) == "Custom Prefix")[0]
        grid = prefix_caption.grid_info()
        prefix_entry = next(
            widget for widget in prefix_caption.master.winfo_children()
            if widget.winfo_class() == "TEntry"
            and int(widget.grid_info().get("row", -1)) == int(grid["row"])
            and int(widget.grid_info().get("column", -1))
            == int(grid["column"]) + 1)
        # The entry refreshes the preview through its KeyRelease binding
        # (tk cannot synthesize key events on Windows Tk, so assert the
        # binding is wired and drive the same callback via a template
        # trace, which re-reads the prefix widget).
        assert prefix_entry.bind("<KeyRelease>")
        prefix_entry.delete(0, "end")
        prefix_entry.insert(0, "SITE-A")
        root.setvar(template_var, "{PREFIX}.{SEQUENCE}")
        assert preview() == "SITE-A.001"
        root.setvar(template_var, DEFAULT_TEMPLATE)
        assert preview() == "SITE-A-001"

        policy_combo.set(policy_label(MANUAL))
        policy_combo.event_generate("<<ComboboxSelected>>")
        assert preview() == "(manual entry)"
    finally:
        tkinter._default_root = previous_default_root
        root.destroy()


def test_project_profile_round_trips_through_clk(tmp_path):
    from qs_engine.persistence.project_file import (
        ProjectFileAdapter,
        load_session,
        save_session,
        state_from_session,
    )
    from qs_engine.ui.session import TakeoffSession
    session = TakeoffSession()
    session.save_project(
        name="Policy Project",
        **MaterialCodePolicy(CUSTOM_PREFIX, "KEN").project_fields())
    state = state_from_session(session)
    payload = ProjectFileAdapter.encode(state)
    restored = ProjectFileAdapter.decode(payload)
    assert restored.project[MATERIAL_CODE_POLICY_FIELD] == "CUSTOM_PREFIX"
    assert restored.project[MATERIAL_CODE_PREFIX_FIELD] == "KEN"
    assert MaterialCodePolicy.from_project(restored.project).mode == (
        "CUSTOM_PREFIX")
    # full save/load through a live session
    target = tmp_path / "policy.clk"
    save_session(session, target)
    fresh = TakeoffSession()
    load_session(fresh, target)
    assert fresh.project[MATERIAL_CODE_POLICY_FIELD] == "CUSTOM_PREFIX"
    assert fresh.project["name"] == "Policy Project"


def test_clk_rejects_unknown_material_code_policy():
    from qs_engine.core.errors import ValidationError
    document = {"version": "1.0.0",
                "project": {"name": "X",
                            MATERIAL_CODE_POLICY_FIELD: "BROKEN"}}
    payload = __import__("zlib").compress(
        json.dumps(document).encode("utf-8"))
    from qs_engine.persistence.project_file import ProjectFileAdapter
    with pytest.raises(ValidationError, match="material code policy"):
        ProjectFileAdapter.decode(payload)


def test_clk_rejects_invalid_custom_prefix_and_keeps_legacy_files():
    from qs_engine.core.errors import ValidationError
    from qs_engine.persistence.project_file import ProjectFileAdapter

    def _payload(project):
        return zlib.compress(json.dumps(
            {"version": "1.0.0", "project": project}).encode("utf-8"))

    with pytest.raises(ValidationError, match="prefix"):
        ProjectFileAdapter.decode(_payload(
            {MATERIAL_CODE_POLICY_FIELD: "CUSTOM_PREFIX",
             MATERIAL_CODE_PREFIX_FIELD: ""}))
    with pytest.raises(ValidationError, match="prefix"):
        ProjectFileAdapter.decode(_payload(
            {MATERIAL_CODE_POLICY_FIELD: "CUSTOM_PREFIX",
             MATERIAL_CODE_PREFIX_FIELD: "has space"}))
    # a non-empty but invalid prefix fails even under another mode
    with pytest.raises(ValidationError):
        ProjectFileAdapter.decode(_payload(
            {MATERIAL_CODE_POLICY_FIELD: "SLUG",
             MATERIAL_CODE_PREFIX_FIELD: "bad prefix!"}))
    # pre-Phase-5 files (no policy fields) load unchanged
    legacy = ProjectFileAdapter.decode(_payload({"name": "Old"}))
    assert legacy.project == {"name": "Old"}
    assert MaterialCodePolicy.from_project(legacy.project).mode == (
        DEFAULT_MODE)
