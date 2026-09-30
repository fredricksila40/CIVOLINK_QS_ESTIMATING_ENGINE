"""Phase 5.1/5.2: the Materials Catalogue Treeview renders policy codes.

Covers the grid display fix: user rows show the user's editable code,
un-customized seed rows show the structured code from the active
MaterialCodePolicy (``quarry_dust`` -> ``AGG-002``), the modal save &
refresh loop, and the resolution of a displayed code back to the record
it names.
"""

import hashlib
import inspect
from pathlib import Path

import pytest

from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.resources import (
    MaterialCodePolicy,
    build_material_stack,
)
from qs_engine.resources.code_policy import (
    CATEGORY_PREFIX,
    CUSTOM_PREFIX,
    MANUAL,
    SEQUENTIAL_NUMERIC,
    SLUG,
)

SEED_TABLES = (Path(__file__).parent.parent / "qs_engine" /
               "master_data" / "tables")


def _seed_hashes():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(SEED_TABLES.glob("*.json"))}


def _seed(key):
    return MasterDataRepository().get("materials", key)


def _app_or_skip(repository):
    from qs_engine.ui import views
    try:
        return views.QSApp(repository=repository)
    except Exception as exc:  # pragma: no cover - display-dependent
        pytest.skip(f"QSApp needs a display: {exc}")


@pytest.fixture()
def stack(tmp_path):
    return build_material_stack(MasterDataRepository(), tmp_path)


def _page_grids(app):
    grids = []

    def walk(widget):
        for child in widget.winfo_children():
            if child.winfo_class() == "Treeview":
                grids.append(child)
            walk(child)

    walk(app.workspace.interior)
    return grids


def _grid_codes(app):
    grids = _page_grids(app)
    assert grids, "catalogue grid missing"
    return {grids[0].item(iid, "values")[0]
            for iid in grids[0].get_children()}


# --- Task 5.1: policy display codes -----------------------------------------

def test_category_prefix_display_code_uses_category_ordinal():
    policy = MaterialCodePolicy(CATEGORY_PREFIX)
    assert policy.resolve_display_code(_seed("river_sand")) == "AGG-001"
    assert policy.resolve_display_code(_seed("quarry_dust")) == "AGG-002"
    assert policy.resolve_display_code(_seed("ballast_20mm")) == "AGG-003"
    assert policy.resolve_display_code(
        _seed("portland_cement_42_5")) == "BIN-001"


def test_slug_display_code_slugifies_the_name():
    policy = MaterialCodePolicy(SLUG)
    assert policy.resolve_display_code(_seed("quarry_dust")) == "quarry_dust"
    assert policy.resolve_display_code(
        _seed("portland_cement_42_5")) == "portland_cement_42_5"
    # punctuation and case fold into the slug, never dropped
    assert policy.resolve_display_code(
        _seed("ballast_20mm")) == "coarse_aggregate_ballast_20mm"


def test_sequential_numeric_display_code_spans_the_catalogue():
    policy = MaterialCodePolicy(SEQUENTIAL_NUMERIC)
    assert policy.resolve_display_code(
        _seed("portland_cement_42_5")) == "001"
    assert policy.resolve_display_code(_seed("quarry_dust")) == "004"


def test_custom_prefix_display_code_uses_the_configured_prefix():
    policy = MaterialCodePolicy(CUSTOM_PREFIX, custom_prefix="KEN")
    assert policy.resolve_display_code(_seed("river_sand")) == "KEN-001"
    assert policy.resolve_display_code(_seed("quarry_dust")) == "KEN-002"


def test_manual_display_code_returns_the_seed_key():
    policy = MaterialCodePolicy(MANUAL)
    assert policy.resolve_display_code(_seed("quarry_dust")) == "quarry_dust"


def test_display_code_unknown_record_falls_back_to_its_key():
    policy = MaterialCodePolicy(CATEGORY_PREFIX)
    mystery = {"key": "mystery_material", "category": "aggregate",
               "name": "Mystery"}
    assert policy.resolve_display_code(mystery) == "mystery_material"


# --- Task 5.2: grid population ----------------------------------------------

def test_catalogue_rows_render_policy_codes_for_seed_materials():
    from qs_engine.ui import views
    policy = MaterialCodePolicy(CATEGORY_PREFIX)
    rows = views.material_catalogue_rows(MasterDataRepository(), policy=policy)
    by_code = {row[0]: row for row in rows}
    assert by_code["AGG-001"][1] == "River Sand"
    assert by_code["AGG-002"][1] == "Quarry Dust"
    assert by_code["BIN-001"][1] == "Portland Cement 42.5"
    assert "quarry_dust" not in by_code  # raw slug never rendered


def test_catalogue_rows_without_policy_keep_legacy_keys():
    from qs_engine.ui import views
    rows = views.material_catalogue_rows(MasterDataRepository())
    by_code = {row[0]: row for row in rows}
    assert by_code["quarry_dust"][1] == "Quarry Dust"
    assert by_code["portland_cement_42_5"][1] == "Portland Cement 42.5"


def test_catalogue_rows_render_the_user_override_code(tmp_path):
    from qs_engine.ui import views
    stack = build_material_stack(MasterDataRepository(), tmp_path)
    stack.store.add_material({"name": "Site Sand", "code": "SAND-001",
                              "category_id": "aggregate", "unit": "m³"})
    policy = MaterialCodePolicy(CATEGORY_PREFIX)
    rows = views.material_catalogue_rows(stack.resolver, policy=policy)
    codes = [row[0] for row in rows]
    assert "SAND-001" in codes       # user row: the user's editable code
    assert "AGG-002" in codes        # seed row: the policy display code
    assert "quarry_dust" not in codes


def test_materials_page_grid_displays_policy_codes(tmp_path):
    stack = build_material_stack(MasterDataRepository(), tmp_path)
    app = _app_or_skip(stack.resolver)
    app.show("materials")
    app.update_idletasks()
    try:
        codes = _grid_codes(app)
        assert "AGG-002" in codes   # quarry_dust under the default policy
        assert "BIN-001" in codes   # portland_cement_42_5
        assert "quarry_dust" not in codes
    finally:
        app.destroy()


def test_materials_page_refresh_alias_is_wired():
    from qs_engine.ui import views
    source = inspect.getsource(views.build_materials_page)
    assert "refresh_materials_grid" in source
    assert "material_catalogue_rows" in source
    assert "active_material_code_policy" in source


def test_customize_seed_save_refreshes_grid_with_assigned_code(tmp_path):
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
        assigned = handle["code"].get()
        assert assigned == "AGG-001"
        handle["save"].invoke()
        app.update()
        saved = handle["result"]
        assert saved is not None
        assert saved["key"].startswith("user:")
        assert saved["code"] == "AGG-001"
        # the seed catalogue stays byte-identical
        assert _seed_hashes() == before
        # the grid data reflects the new row immediately
        rows = views.material_catalogue_rows(app.repository)
        assert "AGG-001" in [row[0] for row in rows]
        # and the live grid shows it too
        app.show("materials")
        app.update_idletasks()
        assert "AGG-001" in _grid_codes(app)
    finally:
        app.destroy()


# --- displayed codes resolve back to the record they name -------------------

def test_resolve_material_reference_falls_back_to_display_code(tmp_path):
    from qs_engine.ui import views
    stack = build_material_stack(MasterDataRepository(), tmp_path)
    app = _app_or_skip(stack.resolver)
    try:
        assert views.active_material_code_policy(app).mode == CATEGORY_PREFIX
        # identity still wins
        assert views.resolve_material_reference(
            app, "river_sand")["key"] == "river_sand"
        # the display code resolves to the same record
        record = views.resolve_material_reference(app, "AGG-002")
        assert record is not None
        assert record["key"] == "quarry_dust"
        # unknown references stay unknown
        assert views.resolve_material_reference(app, "NO-SUCH-CODE") is None
    finally:
        app.destroy()


def test_resource_display_name_resolves_display_code(tmp_path):
    from qs_engine.ui import views
    stack = build_material_stack(MasterDataRepository(), tmp_path)
    app = _app_or_skip(stack.resolver)
    try:
        policy = views.active_material_code_policy(app)
        name, unit = views.resource_display_name(
            "materials", "AGG-002", app.repository, policy=policy)
        assert name == "Quarry Dust"
        assert unit == _seed("quarry_dust")["unit"]
        # unknown keys still fail closed
        assert views.resource_display_name(
            "materials", "NO-SUCH-CODE", app.repository,
            policy=policy)[0] == "⚠ unknown key"
    finally:
        app.destroy()


def test_rate_line_material_keys_translate_display_codes(tmp_path):
    from qs_engine.ui import views
    stack = build_material_stack(MasterDataRepository(), tmp_path)
    app = _app_or_skip(stack.resolver)
    try:
        lines = [{"kind": "material", "material_key": "AGG-002",
                  "qty_per_unit": "1", "unit_price": "2",
                  "wastage_pct": "", "description": ""}]
        resolved = views.resolve_rate_line_material_keys(app, lines)
        assert resolved[0]["material_key"] == "quarry_dust"
        # an explicit identity is never rewritten
        lines = [{"kind": "material", "material_key": "river_sand",
                  "qty_per_unit": "1", "unit_price": "2",
                  "wastage_pct": "", "description": ""}]
        resolved = views.resolve_rate_line_material_keys(app, lines)
        assert resolved[0]["material_key"] == "river_sand"
    finally:
        app.destroy()
