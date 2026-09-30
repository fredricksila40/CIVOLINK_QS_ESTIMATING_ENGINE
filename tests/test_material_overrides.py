"""Phase 25: material/category override architecture tests (requirements A-R).

Hermetic: every test builds its store/registry against tmp paths. Seed
tables under qs_engine/master_data/tables/ are hash-verified byte-
identical after use — the seed architecture is read-only by design.

Requirements covered here: A (seed unchanged), B (create), C (custom
name), D (custom code), E (generated code override), F (custom
category), G (category persists), H (effective catalogue), I (stable
canonical key), J (resolver path), K (seed resolution unchanged), L
(duplicate codes), M (no seed shadowing), N (fail-closed engineering),
O (restart reload), P (malformed rejected), Q (.clk compatible), R (UI
never modifies seed), plus the acceptance workflow.
"""

import hashlib
import inspect
import json
import zlib
from decimal import Decimal
from pathlib import Path

import pytest

from qs_engine.core.assumptions import VerificationStatus
from qs_engine.core.errors import (
    UnknownMasterDataKeyError,
    UnknownUnitError,
    ValidationError,
)
from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.resources import (
    CategoryRegistry,
    MaterialResolver,
    build_material_stack,
)
from qs_engine.resources.material_store import UserMaterialStore

ROOT = Path(__file__).resolve().parents[1]
TABLES_DIR = ROOT / "qs_engine" / "master_data" / "tables"
SEED_MATERIALS = TABLES_DIR / "materials.json"


def _hashes() -> dict:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(TABLES_DIR.glob("*.json"))}


@pytest.fixture()
def stack(tmp_path):
    """Full Phase 25 stack over the shipped seed, tmp-backed."""
    return build_material_stack(MasterDataRepository(), tmp_path)


def _create(stack, **overrides):
    fields = dict(name="Portland Cement 32.5N", code="CEM-32.5N",
                  category_id="binder", unit="bag")
    fields.update(overrides)
    return stack.store.create_material(**fields)


# --- A: seed data remains unchanged ------------------------------------------

def test_a_seed_tables_untouched_by_full_lifecycle(tmp_path):
    before = _hashes()
    stack = build_material_stack(MasterDataRepository(), tmp_path)
    record = _create(stack)
    stack.store.update_material(record["key"], code="CEMENT-KENYA-01")
    stack.store.deactivate_material(record["key"])
    stack.registry.add_custom_category("Kenya Supplies")
    assert _hashes() == before, "seed table bytes changed"
    assert len(MasterDataRepository().list("materials")) == 23


def test_a_writable_files_live_in_data_dir_not_seed_tree():
    from qs_engine.resources import default_categories_path, default_materials_path
    assert default_materials_path().parent.name == "data"
    assert default_categories_path().parent.name == "data"
    assert "master_data" not in default_materials_path().parts


# --- B / C / D: create, custom name, custom code ------------------------------

def test_b_user_material_can_be_created(stack):
    record = _create(stack)
    assert record["key"].startswith("user:")
    assert record["source"] == "user"
    assert stack.store.get_material(record["key"])["name"] == (
        "Portland Cement 32.5N")


def test_c_custom_material_name_works(stack):
    record = _create(stack, name="Murram Imported Blend",
                     code="MUR-01", unit="m³")
    assert record["name"] == "Murram Imported Blend"
    assert record["key"].startswith("user:")


@pytest.mark.parametrize("code", [
    "CEM-32.5N", "PORTLAND-CEMENT", "CEMENT-A", "MY-CEMENT-001",
])
def test_d_custom_material_codes_accepted(stack, code):
    record = _create(stack, code=code)
    assert record["code"] == code


def test_d_invalid_codes_rejected(stack):
    for bad in ("", "   ", "has space", "bad/slash", "semi;colon"):
        with pytest.raises(ValidationError):
            _create(stack, code=bad)


# --- E: generated code can be overridden --------------------------------------

def test_e_generated_code_is_suggestion_not_lock(stack):
    # Phase 5: suggestions come from the code policy (resolver), and a
    # suggestion is never a lock — the user may pick any valid code.
    suggestion = stack.resolver.suggest_code(
        "Portland Cement 32.5N", category="binder")
    assert suggestion == "BIN-001"
    # suggestion is freely replaceable at creation
    record = _create(stack, code="CEMENT-KENYA-01")
    assert record["code"] == "CEMENT-KENYA-01"
    # and after creation (renaming keeps the canonical key stable)
    renamed = stack.store.update_material(record["key"], code=suggestion)
    assert renamed["code"] == "BIN-001"
    assert renamed["key"] == record["key"]


def test_e_generated_code_skips_taken_sequences(stack):
    _create(stack, code="BIN-001")
    assert stack.resolver.suggest_code(
        "Portland Cement", category="binder") == "BIN-002"


# --- F / G: custom category creation + persistence ----------------------------

def test_f_custom_category_can_be_created(stack):
    record = stack.registry.add_custom_category("Kenya Supplies")
    assert record["category_id"] == "user:kenya-supplies"
    assert record["source"] == "user"
    assert record in stack.registry.list_categories()


def test_g_custom_category_persists(tmp_path):
    stack = build_material_stack(MasterDataRepository(), tmp_path)
    stack.registry.add_custom_category("Kenya Supplies")
    reloaded = CategoryRegistry(
        MasterDataRepository(), tmp_path / "user_categories.json")
    names = [entry["category_name"] for entry in reloaded.list_categories()]
    assert "Kenya Supplies" in names
    assert reloaded.resolve_category("user:kenya-supplies").category_name == (
        "Kenya Supplies")


# --- H: effective catalogue = seed + user -------------------------------------

def test_h_effective_catalogue_contains_seed_and_user(stack):
    seed_keys = [r["key"] for r in MasterDataRepository().list("materials")]
    effective = stack.resolver.list("materials")
    assert [r["key"] for r in effective[:23]] == seed_keys
    record = _create(stack)
    effective = stack.resolver.list("materials")
    assert len(effective) == 24
    assert effective[-1]["key"] == record["key"]
    # non-material domains pass through untouched
    assert stack.resolver.list("soils") == (
        MasterDataRepository().list("soils"))


# --- I: stable canonical key ---------------------------------------------------

def test_i_canonical_key_stable_across_renames(tmp_path):
    stack = build_material_stack(MasterDataRepository(), tmp_path)
    record = _create(stack)
    original = record["key"]
    for code in ("CEMENT-KENYA-01", "MAT-POR-001", "FINAL-CODE"):
        record = stack.store.update_material(original, code=code)
        assert record["key"] == original
    # stability across a simulated restart
    again = build_material_stack(MasterDataRepository(), tmp_path)
    assert again.store.get_material(original)["code"] == "FINAL-CODE"


# --- J: resolution through MaterialResolver ------------------------------------

def test_j_user_material_resolves_through_resolver(stack):
    record = _create(stack)
    by_key = stack.resolver.get("materials", record["key"])
    by_code = stack.resolver.get("materials", "CEM-32.5N")
    assert by_key["name"] == by_code["name"] == "Portland Cement 32.5N"
    effective = stack.resolver.resolve_effective("CEM-32.5N")
    assert effective.source == "user"
    assert effective.is_user
    assert effective.needs_verification
    assert effective.default_unit == "bag"


def test_j_drop_in_engine_path_no_changes_needed(stack):
    """The existing engine consumes the resolver as-is (no if-user logic)."""
    from qs_engine.rates.engine import material_component
    record = _create(stack)
    component = material_component(
        material_key=record["key"], qty_per_unit="2", unit_price="100",
        repository=stack.resolver)
    assert Decimal(component.cost_per_unit) == Decimal("200")
    by_code = material_component(
        material_key="CEM-32.5N", qty_per_unit="1", unit_price="50",
        wastage_pct="10", repository=stack.resolver)
    assert Decimal(by_code.cost_per_unit) == Decimal("55")


# --- K: existing seed resolution unchanged --------------------------------------

def test_k_seed_resolution_unchanged(stack):
    seed = MasterDataRepository()
    for key in ("river_sand", "portland_cement_42_5", "release_agent"):
        assert stack.resolver.get("materials", key) == seed.get(
            "materials", key)
    with pytest.raises(UnknownMasterDataKeyError):
        stack.resolver.get("materials", "unobtainium")
    assert stack.resolver.table_version("materials") == "1.0-catalog"
    # user data never leaks into the seed-only repository
    _create(stack)
    with pytest.raises(UnknownMasterDataKeyError):
        seed.get("materials", "CEM-32.5N")


# --- L: duplicate user codes handled deterministically ---------------------------

def test_l_duplicate_codes_rejected_deterministically(stack):
    _create(stack)
    for duplicate in ("CEM-32.5N", "cem-32.5n", "Cem-32.5N"):
        with pytest.raises(ValidationError):
            _create(stack, code=duplicate)
    assert len(stack.resolver.list("materials")) == 24  # nothing half-added


def test_l_update_cannot_collide_with_other_user_code(stack):
    first = _create(stack)
    second = _create(stack, name="Second", code="OTHER-01")
    with pytest.raises(ValidationError):
        stack.store.update_material(second["key"], code=first["code"])
    assert stack.store.get_material(second["key"])["code"] == "OTHER-01"


def test_l_reserved_seed_identifiers_cannot_be_claimed(stack):
    for reserved in ("portland_cement_42_5", "CEM-10175-PC425",
                     "river_sand"):
        with pytest.raises(ValidationError):
            _create(stack, code=reserved)


# --- M: user category cannot silently replace a seed category ------------------

def test_m_user_category_cannot_shadow_seed(stack):
    for shadow in ("Binder", "binder", "BINDER", "binder!"):
        with pytest.raises(ValidationError):
            stack.registry.add_custom_category(shadow)
    resolved = stack.registry.resolve_category("Binder")
    assert resolved.source == "seed"
    assert resolved.category_id == "binder"


def test_m_duplicate_user_category_rejected_deterministically(stack):
    stack.registry.add_custom_category("Kenya Supplies")
    with pytest.raises(ValidationError):
        stack.registry.add_custom_category("kenya supplies")
    user = [c for c in stack.registry.list_categories()
            if c["source"] == "user"]
    assert len(user) == 1


# --- N: missing engineering properties fail closed ------------------------------

def test_n_user_material_carries_no_engineering_properties(stack):
    record = _create(stack)
    assert record["density"] is None
    assert record["default_wastage_pct"] is None
    assert record["verification_status"] == VerificationStatus.NEEDS_VERIFICATION
    # structural guarantee: no API surface for engineering data at all
    params = inspect.signature(stack.store.create_material).parameters
    forbidden = {"density", "wastage_pct", "strength", "coverage",
                 "mix_ratio", "cement_ratio", "labour_factor"}
    assert not (forbidden & set(params))


def test_n_downstream_calculation_fails_closed_not_fabricated(stack):
    from qs_engine.finishes.resolution import (
        UnresolvedRequirement,
        resolve_mortar_materials,
    )
    record = _create(stack)
    result = resolve_mortar_materials(
        mortar_volume_m3="1", repository=stack.resolver,
        cement_material_key=record["key"])
    assert isinstance(result, UnresolvedRequirement)
    assert result.missing, "unresolved result must name what is missing"
    with pytest.raises(UnknownMasterDataKeyError):
        resolve_mortar_materials(
            mortar_volume_m3="1", repository=stack.resolver,
            cement_material_key="user:doesnotexist")


def test_n_unknown_unit_rejected(stack):
    with pytest.raises(UnknownUnitError):
        _create(stack, unit="furlong")


def test_n_deactivated_material_stops_resolving(stack):
    record = _create(stack)
    stack.store.deactivate_material(record["key"])
    assert stack.store.lookup(record["key"]) is None
    assert stack.store.lookup("CEM-32.5N") is None
    with pytest.raises(UnknownMasterDataKeyError):
        stack.resolver.get("materials", "CEM-32.5N")
    assert stack.store.get_material(record["key"])["active"] is False


# --- O: application restart reloads user preferences ----------------------------

def test_o_restart_reloads_user_materials(tmp_path):
    stack = build_material_stack(MasterDataRepository(), tmp_path)
    record = _create(stack)
    stack.registry.add_custom_category("Kenya Supplies")
    # simulated restart: fresh objects over the same data dir
    restarted = build_material_stack(MasterDataRepository(), tmp_path)
    assert restarted.store.get_material(record["key"])["code"] == "CEM-32.5N"
    assert restarted.resolver.get("materials", "CEM-32.5N")["name"] == (
        "Portland Cement 32.5N")
    assert any(c["category_name"] == "Kenya Supplies"
               for c in restarted.registry.list_categories())


# --- P: malformed preference data rejected safely --------------------------------

def test_p_malformed_material_store_rejected(stack):
    stack.store.path.write_text("{ not json ]", encoding="utf-8")
    with pytest.raises(ValidationError):
        UserMaterialStore(stack.store.path, stack.registry)
    stack.store.path.write_text(
        json.dumps({"schema_version": "9.9", "materials": []}),
        encoding="utf-8")
    with pytest.raises(ValidationError):
        UserMaterialStore(stack.store.path, stack.registry)
    stack.store.path.write_text(
        json.dumps({"schema_version": "1.0", "materials": ["not-a-map"]}),
        encoding="utf-8")
    with pytest.raises(ValidationError):
        UserMaterialStore(stack.store.path, stack.registry)


def test_p_malformed_category_registry_rejected(stack):
    path = stack.registry.path
    path.write_text("garbage", encoding="utf-8")
    with pytest.raises(ValidationError):
        CategoryRegistry(MasterDataRepository(), path)
    path.write_text(json.dumps(
        {"schema_version": "0.1", "categories": []}), encoding="utf-8")
    with pytest.raises(ValidationError):
        CategoryRegistry(MasterDataRepository(), path)
    # a user file may never claim a seed identifier
    path.write_text(json.dumps({
        "schema_version": "1.0",
        "categories": [{"category_id": "binder",
                        "category_name": "Binder",
                        "source": "user"}]}), encoding="utf-8")
    with pytest.raises(ValidationError):
        CategoryRegistry(MasterDataRepository(), path)


# --- Q: existing .clk files remain compatible ----------------------------------

def test_q_clk_schema_unchanged_and_roundtrips():
    from qs_engine.persistence import project_file as pf
    assert pf.SCHEMA_VERSION == "1.0.0"
    state = pf.SessionState(
        project={"name": "P"},
        lines=[{"trade": "Concrete", "description": "Slab", "unit": "m³",
                "quantity": "5", "rate": None, "rate_ref": "CEM-32.5N",
                "takeoff_ref": ""}])
    payload = pf.ProjectFileAdapter.encode(state)
    loaded = pf.ProjectFileAdapter.decode(payload)
    # material references in .clk are plain strings; the schema carries NO
    # material definitions and gains none in Phase 25
    assert "materials" not in state.to_dict()
    assert "material" not in state.to_dict()
    assert loaded.lines[0]["rate_ref"] == "CEM-32.5N"
    with pytest.raises(ValidationError):
        pf.ProjectFileAdapter.decode(
            zlib.compress(json.dumps({"version": "0.9.9"}).encode()))


def test_q_clk_file_still_saves_and_loads(tmp_path):
    from qs_engine.persistence.project_file import (
        ProjectFileAdapter,
        SessionState,
    )
    target = tmp_path / "phase24.clk"
    original = SessionState(project={"name": "Compat"},
                            boq={"project_ref": "PR1", "boq_ref": "B1"})
    ProjectFileAdapter.save_project(target, original)
    restored = ProjectFileAdapter.load_project(target)
    assert restored.project == {"name": "Compat"}
    assert restored.boq == {"project_ref": "PR1", "boq_ref": "B1"}


# --- R: the UI never modifies seed data ------------------------------------------

def _app_or_skip(repository):
    from qs_engine.ui import views
    try:
        return views.QSApp(repository=repository)
    except Exception as exc:  # pragma: no cover - display-dependent
        pytest.skip(f"QSApp needs a display: {exc}")


def test_r_material_dialog_writes_only_the_override_store(tmp_path):
    from qs_engine.ui import views
    before = _hashes()
    stack = build_material_stack(MasterDataRepository(), tmp_path)
    app = _app_or_skip(stack.resolver)
    app.update_idletasks()
    try:
        handle = views.material_editor_dialog(app)
        assert handle is not None
        handle["name"].insert(0, "Portland Cement 32.5N")
        handle["code"].delete(0, "end")
        handle["code"].insert(0, "CEM-32.5N")
        handle["category"].set("binder")
        handle["unit"].set("bag")
        handle["save"].invoke()
        app.update()
        assert handle["result"] is not None
    finally:
        app.destroy()
    assert _hashes() == before, "UI run modified a seed table"
    assert (tmp_path / "user_materials.json").is_file()
    again = build_material_stack(MasterDataRepository(), tmp_path)
    assert again.resolver.get("materials", "CEM-32.5N")["name"] == (
        "Portland Cement 32.5N")


# --- acceptance workflow (spec section 12) -----------------------------------------

def test_acceptance_material_override_workflow(tmp_path):
    """Open catalogue -> create Portland Cement 32.5N / CEM-32.5N ->
    restart -> confirm persistence -> rename to CEMENT-KENYA-01 ->
    confirm stable identity -> use through the normal resolution path ->
    confirm fail-closed engineering."""
    from qs_engine.finishes.resolution import (
        UnresolvedRequirement,
        resolve_mortar_materials,
    )
    from qs_engine.rates.engine import material_component
    from qs_engine.ui import views

    before = _hashes()
    stack = build_material_stack(MasterDataRepository(), tmp_path)

    # 1-4. open the catalogue/material dialog and save the material
    app = _app_or_skip(stack.resolver)
    app.update_idletasks()
    try:
        app.show("materials")
        app.update()
        source = inspect.getsource(views.build_materials_page)
        assert "Add Material" in source
        assert "material_catalogue_rows" in source
        assert "ttk.Entry" not in source
        handle = views.material_editor_dialog(app)
        assert handle is not None
        handle["name"].insert(0, "Portland Cement 32.5N")
        handle["code"].delete(0, "end")
        handle["code"].insert(0, "CEM-32.5N")
        handle["category"].set("binder")
        handle["unit"].set("bag")
        handle["save"].invoke()
        app.update()
        created = handle["result"]
        assert created is not None and created["code"] == "CEM-32.5N"
    finally:
        app.destroy()

    # 5-7. restart over the same data dir: material persists, seed untouched
    restarted = build_material_stack(MasterDataRepository(), tmp_path)
    app2 = _app_or_skip(restarted.resolver)
    app2.update_idletasks()
    try:
        rows = views.material_catalogue_rows(app2.repository)
        assert len(rows) == 24
        assert any(row[0] == "CEM-32.5N" for row in rows)
        assert _hashes() == before
        assert len(MasterDataRepository().list("materials")) == 23

        # 8-10. edit through the dialog: code accepted, identity stable
        record = restarted.resolver.get("materials", "CEM-32.5N")
        edit = views.material_editor_dialog(app2, record=record)
        assert edit is not None
        assert edit["name"].get() == "Portland Cement 32.5N"
        edit["code"].delete(0, "end")
        edit["code"].insert(0, "CEMENT-KENYA-01")
        edit["save"].invoke()
        app2.update()
        renamed = edit["result"]
        assert renamed is not None and renamed["code"] == "CEMENT-KENYA-01"
        assert renamed["key"] == created["key"] == record["key"]

        # 11. normal selection/resolution path
        effective = restarted.resolver.resolve_effective("CEMENT-KENYA-01")
        assert effective.key == created["key"]
        assert effective.source == "user"
        component = material_component(
            material_key="CEMENT-KENYA-01", qty_per_unit="2",
            unit_price="100", repository=restarted.resolver)
        assert Decimal(component.cost_per_unit) == Decimal("200")
        # the earlier reference resolves to the SAME material, never another
        assert restarted.resolver.get(
            "materials", "CEM-32.5N")["key"] == created["key"]

        # 12. missing engineering properties fail closed
        record = restarted.resolver.get("materials", created["key"])
        assert record["density"] is None
        assert record["default_wastage_pct"] is None
        assert record["verification_status"] == (
            VerificationStatus.NEEDS_VERIFICATION)
        mortar = resolve_mortar_materials(
            mortar_volume_m3="1", repository=restarted.resolver,
            cement_material_key=created["key"])
        assert isinstance(mortar, UnresolvedRequirement)

        # grid shows the updated code after refresh; seed still byte-identical
        rows = views.material_catalogue_rows(app2.repository)
        assert any(row[0] == "CEMENT-KENYA-01" for row in rows)
        assert _hashes() == before
    finally:
        app2.destroy()
