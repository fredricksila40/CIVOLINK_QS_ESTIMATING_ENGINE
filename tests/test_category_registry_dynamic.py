"""Dynamic Category Registry & Pattern Engine tests.

Covers:
- Dynamic template evaluation with custom separators, padding, and tokens
- CodePatternEngine token resolution
- MaterialCodePolicy with dynamic formatting parameters
- .clk persistence for custom templates, separators, and sequence padding
- Category Registry prefix uniqueness and SAP/GL account binding
- CategoryRecord formatting parameter validation
"""

import json
import zlib
from pathlib import Path

import pytest

from qs_engine.core.errors import ValidationError
from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.resources import (
    CODE_PATTERN_PRESETS,
    DEFAULT_PADDING,
    DEFAULT_SEPARATOR,
    DEFAULT_TEMPLATE,
    MATERIAL_CODE_PADDING_FIELD,
    MATERIAL_CODE_SEPARATOR_FIELD,
    MATERIAL_CODE_TEMPLATE_FIELD,
    NEEDS_VERIFICATION,
    PRESET_BY_ID,
    UI_POLICY_MODES,
    CodePatternEngine,
    CodePatternPreset,
    MaterialCodePolicy,
    build_material_stack,
)
from qs_engine.resources.category_registry import (
    CategoryRecord,
    CategoryRegistry,
    PREFIX_RE,
    SEPARATOR_RE,
)
from qs_engine.resources.code_policy import (
    CATEGORY_PREFIX,
    CUSTOM_PREFIX,
    MANUAL,
    SEQUENTIAL_NUMERIC,
    SLUG,
)


@pytest.fixture()
def stack(tmp_path):
    return build_material_stack(MasterDataRepository(), tmp_path)


# --- CodePatternEngine: dynamic template evaluation ---------------------------

def test_engine_default_template():
    preset = CodePatternPreset("TEST", "Test", "{PREFIX}{SEPARATOR}{SEQUENCE}")
    result = CodePatternEngine.format_code(
        preset, prefix="AGG", sequence=1)
    assert result == "AGG-001"


def test_engine_custom_separator_slash():
    preset = CodePatternPreset("TEST", "Test", "{PREFIX}{SEPARATOR}{SEQUENCE}")
    result = CodePatternEngine.format_code(
        preset, prefix="AGG", sequence=1, delimiter="/")
    assert result == "AGG/001"


def test_engine_custom_separator_dot():
    preset = CodePatternPreset("TEST", "Test", "{PREFIX}{SEPARATOR}{SEQUENCE}")
    result = CodePatternEngine.format_code(
        preset, prefix="CEM", sequence=1, delimiter=".")
    assert result == "CEM.001"


def test_engine_custom_separator_empty():
    preset = CodePatternPreset("TEST", "Test", "{PREFIX}{SEPARATOR}{SEQUENCE}")
    result = CodePatternEngine.format_code(
        preset, prefix="AGG", sequence=1, delimiter="")
    assert result == "AGG001"


def test_engine_custom_padding_4():
    preset = CodePatternPreset("TEST", "Test", "{PREFIX}{SEPARATOR}{SEQUENCE}")
    result = CodePatternEngine.format_code(
        preset, prefix="AGG", sequence=1, padding=4)
    assert result == "AGG-0001"


def test_engine_custom_padding_5():
    preset = CodePatternPreset("TEST", "Test", "{PREFIX}{SEPARATOR}{SEQUENCE}")
    result = CodePatternEngine.format_code(
        preset, prefix="AGG", sequence=42, padding=5)
    assert result == "AGG-00042"


def test_engine_custom_token_template():
    preset = CodePatternPreset(
        "TEST", "Test", "{CATEGORY_ID}/{SEQUENCE}")
    result = CodePatternEngine.format_code(
        preset, prefix="AGG", sequence=7, delimiter="/", padding=4)
    assert result == "AGG/0007"


def test_engine_manual_preset_returns_empty():
    preset = CodePatternPreset("MANUAL", "Manual", "", is_manual=True)
    result = CodePatternEngine.format_code(
        preset, prefix="AGG", sequence=1)
    assert result == ""


def test_engine_custom_prefix_override():
    preset = CodePatternPreset(
        "CUSTOM", "Custom", "{PREFIX}{SEPARATOR}{SEQUENCE}",
        requires_custom_prefix=True)
    result = CodePatternEngine.format_code(
        preset, prefix="AGG", sequence=1, custom_prefix="KEN")
    assert result == "KEN-001"


def test_engine_padding_uses_zfill():
    preset = CodePatternPreset("TEST", "Test", "{SEQUENCE}")
    result = CodePatternEngine.format_code(
        preset, prefix="", sequence=5, padding=6)
    assert result == "000005"


def test_engine_all_tokens():
    preset = CodePatternPreset(
        "TEST", "Test", "{PREFIX}{SEPARATOR}{CATEGORY_ID}{SEQUENCE}")
    result = CodePatternEngine.format_code(
        preset, prefix="TST", sequence=3, delimiter="_", padding=2)
    assert result == "TST_TST03"


# --- CodePatternPreset registry -----------------------------------------------

def test_builtin_presets_exist():
    assert "CATEGORY_SEQUENCE" in PRESET_BY_ID
    assert "CUSTOM_SEQUENCE" in PRESET_BY_ID
    assert "SEQUENTIAL_NUMERIC" in PRESET_BY_ID
    assert "MANUAL" in PRESET_BY_ID


def test_preset_ids_unique():
    ids = [p.preset_id for p in CODE_PATTERN_PRESETS]
    assert len(ids) == len(set(ids))


def test_manual_preset_is_manual():
    assert PRESET_BY_ID["MANUAL"].is_manual is True


def test_custom_sequence_requires_prefix():
    assert PRESET_BY_ID["CUSTOM_SEQUENCE"].requires_custom_prefix is True


def test_sequential_numeric_template():
    assert PRESET_BY_ID["SEQUENTIAL_NUMERIC"].template == "{SEQUENCE}"


# --- MaterialCodePolicy with dynamic formatting -------------------------------

def test_policy_default_formatting():
    policy = MaterialCodePolicy(CATEGORY_PREFIX)
    assert policy.suggest("x", category="aggregate") == "AGG-001"


def test_policy_custom_separator():
    policy = MaterialCodePolicy(CATEGORY_PREFIX, separator="/")
    assert policy.suggest("x", category="aggregate") == "AGG/001"


def test_policy_custom_padding():
    policy = MaterialCodePolicy(CATEGORY_PREFIX, sequence_padding=4)
    assert policy.suggest("x", category="aggregate") == "AGG-0001"


def test_policy_custom_template():
    policy = MaterialCodePolicy(
        CATEGORY_PREFIX, format_template="{PREFIX}/{SEQUENCE}")
    assert policy.suggest("x", category="aggregate") == "AGG/001"


def test_policy_custom_template_with_padding():
    policy = MaterialCodePolicy(
        CATEGORY_PREFIX,
        format_template="{PREFIX}/{SEQUENCE}",
        sequence_padding=5)
    assert policy.suggest("x", category="aggregate") == "AGG/00001"


def test_policy_custom_prefix_with_template():
    policy = MaterialCodePolicy(
        CUSTOM_PREFIX, custom_prefix="KEN",
        format_template="{PREFIX}.{SEQUENCE}",
        separator=".")
    assert policy.suggest("x") == "KEN.001"


def test_policy_sequential_numeric_with_padding():
    policy = MaterialCodePolicy(SEQUENTIAL_NUMERIC, sequence_padding=5)
    assert policy.suggest("x") == "00001"


def test_policy_manual_returns_empty():
    policy = MaterialCodePolicy(MANUAL)
    assert policy.suggest("x", category="aggregate") == ""


def test_policy_invalid_padding_rejected():
    with pytest.raises(ValidationError):
        MaterialCodePolicy(CATEGORY_PREFIX, sequence_padding=0)
    with pytest.raises(ValidationError):
        MaterialCodePolicy(CATEGORY_PREFIX, sequence_padding=-1)


def test_policy_invalid_separator_rejected():
    with pytest.raises(ValidationError):
        MaterialCodePolicy(CATEGORY_PREFIX, separator="--")


def test_policy_none_values_inherit_defaults():
    policy = MaterialCodePolicy(
        CATEGORY_PREFIX, format_template=None,
        sequence_padding=None, separator=None)
    assert policy.suggest("x", category="aggregate") == "AGG-001"


def test_policy_display_code_with_custom_formatting():
    policy = MaterialCodePolicy(
        CATEGORY_PREFIX, separator="/", sequence_padding=4)
    seed = MasterDataRepository().get("materials", "river_sand")
    assert policy.resolve_display_code(seed) == "AGG/0001"


def test_policy_display_code_sequential_with_padding():
    policy = MaterialCodePolicy(SEQUENTIAL_NUMERIC, sequence_padding=5)
    seed = MasterDataRepository().get("materials", "river_sand")
    assert policy.resolve_display_code(seed) == "00003"


# --- .clk persistence for dynamic formatting ---------------------------------

def test_clk_persists_custom_template(tmp_path):
    from qs_engine.persistence.project_file import (
        ProjectFileAdapter,
        state_from_session,
    )
    from qs_engine.ui.session import TakeoffSession
    session = TakeoffSession()
    session.save_project(
        name="Fmt Project",
        **MaterialCodePolicy(
            CATEGORY_PREFIX,
            format_template="{PREFIX}/{SEQUENCE}",
            sequence_padding=4,
            separator="/",
        ).project_fields())
    state = state_from_session(session)
    payload = ProjectFileAdapter.encode(state)
    restored = ProjectFileAdapter.decode(payload)
    assert restored.project[MATERIAL_CODE_TEMPLATE_FIELD] == "{PREFIX}/{SEQUENCE}"
    assert restored.project[MATERIAL_CODE_PADDING_FIELD] == "4"
    assert restored.project[MATERIAL_CODE_SEPARATOR_FIELD] == "/"
    policy = MaterialCodePolicy.from_project(restored.project)
    assert policy.format_template == "{PREFIX}/{SEQUENCE}"
    assert policy.sequence_padding == 4
    assert policy.separator == "/"


def test_clk_persists_custom_separator_only(tmp_path):
    from qs_engine.persistence.project_file import ProjectFileAdapter
    document = {
        "version": "1.0.0",
        "project": {
            "name": "X",
            "material_code_policy": "CATEGORY_PREFIX",
            "material_code_separator": ".",
        },
    }
    payload = zlib.compress(json.dumps(document).encode("utf-8"))
    restored = ProjectFileAdapter.decode(payload)
    assert restored.project[MATERIAL_CODE_SEPARATOR_FIELD] == "."
    policy = MaterialCodePolicy.from_project(restored.project)
    assert policy.separator == "."


def test_clk_persists_custom_padding_only(tmp_path):
    from qs_engine.persistence.project_file import ProjectFileAdapter
    document = {
        "version": "1.0.0",
        "project": {
            "name": "X",
            "material_code_policy": "CATEGORY_PREFIX",
            "material_code_sequence_padding": "5",
        },
    }
    payload = zlib.compress(json.dumps(document).encode("utf-8"))
    restored = ProjectFileAdapter.decode(payload)
    assert restored.project[MATERIAL_CODE_PADDING_FIELD] == "5"
    policy = MaterialCodePolicy.from_project(restored.project)
    assert policy.sequence_padding == 5


def test_clk_rejects_invalid_padding(tmp_path):
    from qs_engine.persistence.project_file import ProjectFileAdapter
    document = {
        "version": "1.0.0",
        "project": {
            "name": "X",
            "material_code_policy": "CATEGORY_PREFIX",
            "material_code_sequence_padding": "abc",
        },
    }
    payload = zlib.compress(json.dumps(document).encode("utf-8"))
    restored = ProjectFileAdapter.decode(payload)
    with pytest.raises(ValidationError, match="padding"):
        MaterialCodePolicy.from_project(restored.project)


def test_clk_rejects_invalid_separator(tmp_path):
    from qs_engine.persistence.project_file import ProjectFileAdapter
    document = {
        "version": "1.0.0",
        "project": {
            "name": "X",
            "material_code_policy": "CATEGORY_PREFIX",
            "material_code_separator": "!!",
        },
    }
    payload = zlib.compress(json.dumps(document).encode("utf-8"))
    restored = ProjectFileAdapter.decode(payload)
    with pytest.raises(ValidationError, match="Separator"):
        MaterialCodePolicy.from_project(restored.project)


def test_clk_legacy_file_without_formatting_loads(tmp_path):
    from qs_engine.persistence.project_file import ProjectFileAdapter
    document = {"version": "1.0.0", "project": {"name": "Legacy"}}
    payload = zlib.compress(json.dumps(document).encode("utf-8"))
    restored = ProjectFileAdapter.decode(payload)
    policy = MaterialCodePolicy.from_project(restored.project)
    assert policy.format_template is None
    assert policy.sequence_padding is None
    assert policy.separator is None


def test_policy_project_fields_include_formatting():
    policy = MaterialCodePolicy(
        CATEGORY_PREFIX,
        format_template="{PREFIX}.{SEQUENCE}",
        sequence_padding=4,
        separator=".",
    )
    fields = policy.project_fields()
    assert fields[MATERIAL_CODE_TEMPLATE_FIELD] == "{PREFIX}.{SEQUENCE}"
    assert fields[MATERIAL_CODE_PADDING_FIELD] == "4"
    assert fields[MATERIAL_CODE_SEPARATOR_FIELD] == "."


def test_policy_project_fields_omit_none():
    policy = MaterialCodePolicy(CATEGORY_PREFIX)
    fields = policy.project_fields()
    assert MATERIAL_CODE_TEMPLATE_FIELD not in fields
    assert MATERIAL_CODE_PADDING_FIELD not in fields
    assert MATERIAL_CODE_SEPARATOR_FIELD not in fields


# --- CategoryRecord formatting parameters -------------------------------------

def test_category_record_defaults():
    record = CategoryRecord(
        category_id="test", category_name="Test")
    assert record.prefix == ""
    assert record.sap_gl_code == NEEDS_VERIFICATION
    assert record.gl_description == NEEDS_VERIFICATION
    assert record.format_template is None
    assert record.sequence_padding is None
    assert record.separator is None


def test_category_record_with_formatting():
    record = CategoryRecord(
        category_id="test", category_name="Test",
        prefix="TST", sap_gl_code="10001",
        gl_description="Inventory Account - Test",
        format_template="{PREFIX}/{SEQUENCE}",
        sequence_padding=4, separator="/")
    assert record.prefix == "TST"
    assert record.sap_gl_code == "10001"
    assert record.gl_description == "Inventory Account - Test"
    assert record.format_template == "{PREFIX}/{SEQUENCE}"
    assert record.sequence_padding == 4
    assert record.separator == "/"


def test_category_record_to_dict_round_trip():
    record = CategoryRecord(
        category_id="test", category_name="Test",
        prefix="TST", sap_gl_code="10001",
        gl_description="Test Desc",
        format_template="{PREFIX}-{SEQUENCE}",
        sequence_padding=3, separator="-")
    data = record.to_dict()
    restored = CategoryRecord.from_dict(data)
    assert restored.category_id == record.category_id
    assert restored.prefix == record.prefix
    assert restored.sap_gl_code == record.sap_gl_code
    assert restored.format_template == record.format_template
    assert restored.sequence_padding == record.sequence_padding
    assert restored.separator == record.separator


def test_category_record_invalid_padding():
    with pytest.raises(ValidationError):
        CategoryRecord(category_id="t", category_name="T", sequence_padding=0)
    with pytest.raises(ValidationError):
        CategoryRecord(category_id="t", category_name="T", sequence_padding=-1)


def test_category_record_invalid_separator():
    with pytest.raises(ValidationError):
        CategoryRecord(category_id="t", category_name="T", separator="--")


def test_category_record_prefix_uppercased():
    record = CategoryRecord(category_id="t", category_name="T", prefix="abc")
    assert record.prefix == "ABC"


# --- Category Registry prefix uniqueness & GL binding ------------------------

def test_registry_seed_categories_have_prefixes(stack):
    cat = stack.registry.get_category("aggregate")
    assert cat.prefix == "AGG"
    assert cat.sap_gl_code == "10176"
    assert "Aggregates" in cat.gl_description


def test_registry_seed_binder_category(stack):
    cat = stack.registry.get_category("binder")
    assert cat.prefix == "CEM"
    assert cat.sap_gl_code == "10175"


def test_registry_prefix_uniqueness_enforced(stack):
    with pytest.raises(ValidationError, match="prefix"):
        stack.registry.add_custom_category("Test Cat", prefix="AGG")


def test_registry_custom_category_with_prefix(stack):
    record = stack.registry.add_custom_category(
        "Kenya Supplies", prefix="KEN",
        sap_gl_code="10999", gl_description="Inventory - Kenya")
    assert record["prefix"] == "KEN"
    assert record["sap_gl_code"] == "10999"
    assert record["gl_description"] == "Inventory - Kenya"


def test_registry_custom_category_without_prefix(stack):
    record = stack.registry.add_custom_category("No Prefix Cat")
    assert record["prefix"] == ""
    assert record["sap_gl_code"] == NEEDS_VERIFICATION


def test_registry_get_category_by_prefix(stack):
    cat = stack.registry.get_category_by_prefix("AGG")
    assert cat is not None
    assert cat.category_id == "aggregate"


def test_registry_get_category_by_prefix_miss(stack):
    assert stack.registry.get_category_by_prefix("ZZZ") is None


def test_registry_custom_category_with_formatting(stack):
    record = stack.registry.add_custom_category(
        "Custom Fmt", prefix="CUS",
        format_template="{PREFIX}.{SEQUENCE}",
        sequence_padding=4, separator=".")
    assert record["format_template"] == "{PREFIX}.{SEQUENCE}"
    assert record["sequence_padding"] == 4
    assert record["separator"] == "."


def test_registry_custom_category_persists_formatting(stack, tmp_path):
    stack.registry.add_custom_category(
        "Persist Fmt", prefix="PRF",
        format_template="{PREFIX}/{SEQUENCE}",
        sequence_padding=5, separator="/")
    reloaded = CategoryRegistry(
        MasterDataRepository(), tmp_path / "user_categories.json")
    cat = reloaded.get_category("user:persist-fmt")
    assert cat.format_template == "{PREFIX}/{SEQUENCE}"
    assert cat.sequence_padding == 5
    assert cat.separator == "/"


def test_registry_invalid_prefix_rejected(stack):
    with pytest.raises(ValidationError, match="prefix"):
        stack.registry.add_custom_category("Bad Prefix", prefix="lowercase")


def test_registry_list_categories_includes_formatting(stack):
    rows = stack.registry.list_categories()
    by_id = {r["category_id"]: r for r in rows}
    assert by_id["aggregate"]["prefix"] == "AGG"
    assert by_id["aggregate"]["sap_gl_code"] == "10176"


# --- category editing (update_category) ----------------------------------------

def test_registry_user_category_can_be_edited(stack):
    created = stack.registry.add_custom_category("Kenya Supplies",
                                                 prefix="KEN")
    updated = stack.registry.update_category(
        created["category_id"], name="Kenya Supplies (2026)",
        prefix="KEN2", sap_gl_code="10999",
        gl_description="Inventory - Kenya")
    assert updated["category_name"] == "Kenya Supplies (2026)"
    assert updated["prefix"] == "KEN2"
    assert updated["sap_gl_code"] == "10999"
    # the stable id never changes on a rename
    assert updated["category_id"] == created["category_id"]


def test_registry_category_edit_persists(tmp_path):
    stack = build_material_stack(MasterDataRepository(), tmp_path)
    created = stack.registry.add_custom_category("Persist Me", prefix="PER")
    stack.registry.update_category(
        created["category_id"], name="Persist Me Renamed",
        format_template="{PREFIX}/{SEQUENCE}", sequence_padding=5,
        separator="/")
    reloaded = CategoryRegistry(
        MasterDataRepository(), tmp_path / "user_categories.json")
    cat = reloaded.get_category(created["category_id"])
    assert cat.category_name == "Persist Me Renamed"
    assert cat.format_template == "{PREFIX}/{SEQUENCE}"
    assert cat.sequence_padding == 5
    assert cat.separator == "/"


def test_registry_category_edit_omitted_fields_are_unchanged(stack):
    created = stack.registry.add_custom_category(
        "Keep Mine", prefix="KPM", sap_gl_code="10100",
        gl_description="Original", sequence_padding=3)
    updated = stack.registry.update_category(created["category_id"],
                                              name="Keep Mine Renamed")
    assert updated["category_name"] == "Keep Mine Renamed"
    assert updated["prefix"] == "KPM"
    assert updated["sap_gl_code"] == "10100"
    assert updated["gl_description"] == "Original"
    assert updated["sequence_padding"] == 3


def test_registry_category_edit_can_clear_optional_formatting(stack):
    created = stack.registry.add_custom_category(
        "Clear Me", prefix="CLR", format_template="{PREFIX}.{SEQUENCE}",
        sequence_padding=4, separator=".")
    updated = stack.registry.update_category(
        created["category_id"], format_template=None,
        sequence_padding=None, separator=None)
    # explicit None clears back to the project default (never hardcoded)
    assert updated["format_template"] is None
    assert updated["sequence_padding"] is None
    assert updated["separator"] is None


def test_registry_seed_category_is_editable_by_default(stack):
    # preexisting (seed) categories are editable by default: the edit
    # lands on the category itself, keeping its id and seed provenance.
    updated = stack.registry.update_category(
        "aggregate", prefix="AGX", sap_gl_code="10999",
        gl_description="Inventory Account - Aggregates")
    assert updated["category_id"] == "aggregate"
    assert updated["source"] == "seed"
    cat = stack.registry.get_category("aggregate")
    assert cat.prefix == "AGX"
    assert cat.sap_gl_code == "10999"
    assert cat.gl_description == "Inventory Account - Aggregates"
    # every lookup follows the edited binding
    assert stack.registry.get_category_by_prefix("AGX").category_id == (
        "aggregate")
    assert stack.registry.get_category_by_prefix("AGG") is None
    by_name = stack.registry.resolve_category("aggregate")
    assert by_name.prefix == "AGX"


def test_registry_seed_category_edit_keeps_omitted_fields(stack):
    stack.registry.update_category("binder", sap_gl_code="10199")
    cat = stack.registry.get_category("binder")
    assert cat.prefix == "CEM"            # untouched
    assert cat.sap_gl_code == "10199"     # edited
    assert cat.category_name == "binder"  # untouched


def test_registry_seed_category_edit_persists(tmp_path):
    stack = build_material_stack(MasterDataRepository(), tmp_path)
    stack.registry.update_category(
        "aggregate", name="Aggregates (Bulk)", prefix="AGB",
        format_template="{PREFIX}/{SEQUENCE}", sequence_padding=4,
        separator="/")
    reloaded = CategoryRegistry(
        MasterDataRepository(), tmp_path / "user_categories.json")
    cat = reloaded.get_category("aggregate")
    assert cat.category_name == "Aggregates (Bulk)"
    assert cat.prefix == "AGB"
    assert cat.format_template == "{PREFIX}/{SEQUENCE}"
    assert cat.sequence_padding == 4
    assert cat.separator == "/"
    assert cat.source == "seed"
    # the stable id still resolves after the rename
    assert reloaded.resolve_category("aggregate").category_id == "aggregate"


def test_registry_seed_category_edit_does_not_touch_seed_tables(stack):
    seed_file = (Path(__file__).parent.parent / "qs_engine" /
                 "master_data" / "tables" / "materials.json")
    before = seed_file.read_bytes()
    stack.registry.update_category(
        "aggregate", name="Renamed Seed", prefix="AGX",
        sap_gl_code="10999", gl_description="Inventory Account - Renamed")
    assert seed_file.read_bytes() == before, "seed table bytes changed"


def test_registry_seed_category_edit_validation(stack):
    with pytest.raises(ValidationError, match="prefix"):
        stack.registry.update_category("aggregate", prefix="lowercase")
    # a prefix another category already holds is refused
    with pytest.raises(ValidationError, match="already used by"):
        stack.registry.update_category("aggregate", prefix="CEM")
    # renaming onto another seed category is refused
    with pytest.raises(ValidationError, match="shadow seed category"):
        stack.registry.update_category("aggregate", name="binder")
    with pytest.raises(ValidationError, match="non-empty"):
        stack.registry.update_category("aggregate", name="   ")


def test_registry_seed_edit_cannot_take_user_category_name(stack):
    stack.registry.add_custom_category("Kenya Supplies", prefix="KEN")
    with pytest.raises(ValidationError, match="already exists"):
        stack.registry.update_category("aggregate", name="Kenya Supplies")


def test_registry_unknown_category_edit_refused(stack):
    with pytest.raises(ValidationError, match="Unknown material category"):
        stack.registry.update_category("never-made", name="Ghost")
    with pytest.raises(ValidationError, match="Unknown user material category"):
        stack.registry.update_category("user:never-made", name="Ghost")


def test_registry_malformed_override_rejected(stack):
    path = stack.registry.path

    def _write(overrides):
        path.write_text(json.dumps({
            "schema_version": "1.0", "categories": [],
            "overrides": overrides}), encoding="utf-8")

    # an override may never claim a user category id
    _write([{"category_id": "user:kenya-supplies", "prefix": "KEN"}])
    with pytest.raises(ValidationError, match="may not target a user"):
        CategoryRegistry(MasterDataRepository(), path)
    # an override must carry at least one editable field
    _write([{"category_id": "aggregate"}])
    with pytest.raises(ValidationError, match="no editable fields"):
        CategoryRegistry(MasterDataRepository(), path)
    # overrides must be a list
    path.write_text(json.dumps({
        "schema_version": "1.0", "categories": [],
        "overrides": {}}), encoding="utf-8")
    with pytest.raises(ValidationError, match="must be a list"):
        CategoryRegistry(MasterDataRepository(), path)
    # malformed binding values fail closed (prefix length/charset,
    # padded like CategoryRecord normalisation: uppercased first)
    _write([{"category_id": "aggregate", "prefix": "waytoolongprefix"}])
    with pytest.raises(ValidationError, match="prefix"):
        CategoryRegistry(MasterDataRepository(), path)
    _write([{"category_id": "aggregate", "prefix": "LO-W"}])
    with pytest.raises(ValidationError, match="prefix"):
        CategoryRegistry(MasterDataRepository(), path)
    _write([{"category_id": "aggregate", "sequence_padding": 0}])
    with pytest.raises(ValidationError, match="sequence_padding"):
        CategoryRegistry(MasterDataRepository(), path)
    _write([{"category_id": "aggregate", "separator": "--"}])
    with pytest.raises(ValidationError, match="separator"):
        CategoryRegistry(MasterDataRepository(), path)


def test_registry_file_without_overrides_key_still_loads(stack):
    # files written before seed editing existed keep loading unchanged
    path = stack.registry.path
    path.write_text(json.dumps(
        {"schema_version": "1.0", "categories": []}), encoding="utf-8")
    reloaded = CategoryRegistry(MasterDataRepository(), path)
    assert reloaded.get_category("aggregate").prefix == "AGG"


def test_registry_category_edit_cannot_shadow_seed(stack):
    created = stack.registry.add_custom_category("Mine", prefix="MIN")
    with pytest.raises(ValidationError, match="shadow seed category"):
        stack.registry.update_category(created["category_id"],
                                       name="aggregate")


def test_registry_category_edit_cannot_duplicate_user(stack):
    first = stack.registry.add_custom_category("Alpha", prefix="ALP")
    stack.registry.add_custom_category("Beta", prefix="BET")
    with pytest.raises(ValidationError, match="already exists"):
        stack.registry.update_category(first["category_id"], name="Beta")


def test_registry_category_edit_keeps_own_name_and_prefix(stack):
    # Re-saving a category unchanged must not trip the duplicate checks.
    created = stack.registry.add_custom_category("Same Name", prefix="SMN")
    updated = stack.registry.update_category(created["category_id"])
    assert updated["category_name"] == "Same Name"
    assert updated["prefix"] == "SMN"


def test_registry_category_edit_prefix_collision_refused(stack):
    first = stack.registry.add_custom_category("Mine", prefix="MIN")
    stack.registry.add_custom_category("Other", prefix="OTH")
    with pytest.raises(ValidationError, match="already used by"):
        stack.registry.update_category(first["category_id"], prefix="OTH")


def test_registry_category_edit_rejects_bad_values(stack):
    created = stack.registry.add_custom_category("Validate Me",
                                                 prefix="VAL")
    with pytest.raises(ValidationError, match="prefix"):
        stack.registry.update_category(created["category_id"],
                                       prefix="lowercase")
    with pytest.raises(ValidationError, match="non-empty"):
        stack.registry.update_category(created["category_id"], name="  ")
    with pytest.raises(ValidationError, match="sequence_padding"):
        stack.registry.update_category(created["category_id"],
                                       sequence_padding=0)


def test_registry_category_edit_leaves_no_partial_state(stack):
    created = stack.registry.add_custom_category("Atomic", prefix="AT")
    with pytest.raises(ValidationError):
        stack.registry.update_category(created["category_id"],
                                       prefix="lowercase")
    # the failed edit left the stored record exactly as it was
    stored = stack.registry.get_category(created["category_id"])
    assert stored.prefix == "AT"
    assert stored.category_name == "Atomic"


def test_registry_category_edit_does_not_touch_seed_tables(stack):
    seed_file = (Path(__file__).parent.parent / "qs_engine" /
                 "master_data" / "tables" / "materials.json")
    before = seed_file.read_bytes()
    created = stack.registry.add_custom_category("Safe Edit", prefix="SEF")
    stack.registry.update_category(created["category_id"], name="Safe Edit 2")
    assert seed_file.read_bytes() == before


# --- UI policy modes (SLUG removed) -------------------------------------------

def test_slug_not_in_ui_policy_modes():
    assert SLUG not in UI_POLICY_MODES


def test_ui_policy_modes_present():
    assert CATEGORY_PREFIX in UI_POLICY_MODES
    assert SEQUENTIAL_NUMERIC in UI_POLICY_MODES
    assert CUSTOM_PREFIX in UI_POLICY_MODES
    assert MANUAL in UI_POLICY_MODES


# --- Integration: policy + registry ------------------------------------------

def test_policy_suggest_with_registry_prefix(stack):
    policy = MaterialCodePolicy(CATEGORY_PREFIX)
    cat = stack.registry.get_category("aggregate")
    assert policy.suggest("x", category=cat.category_id) == "AGG-001"


def test_policy_suggest_with_custom_formatting_and_registry(stack):
    policy = MaterialCodePolicy(
        CATEGORY_PREFIX,
        format_template="{PREFIX}/{SEQUENCE}",
        sequence_padding=4, separator="/")
    assert policy.suggest("x", category="aggregate") == "AGG/0001"


def test_resolver_suggest_with_dynamic_policy(stack):
    policy = MaterialCodePolicy(
        CATEGORY_PREFIX, separator=".", sequence_padding=4)
    result = stack.resolver.suggest_code(
        "x", category="aggregate", policy=policy)
    assert result == "AGG.0001"


def test_resolver_suggest_custom_template(stack):
    policy = MaterialCodePolicy(
        CATEGORY_PREFIX, format_template="{PREFIX}-{CATEGORY_ID}-{SEQUENCE}")
    result = stack.resolver.suggest_code(
        "x", category="aggregate", policy=policy)
    assert result == "AGG-AGG-001"
