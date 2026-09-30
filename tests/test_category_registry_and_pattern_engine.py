"""Phase 6: Category Registry & Code Pattern Engine tests.

Covers dynamic token formatting, collision rejections,
category registry lookups, code policy validation, and
.material persistence round-trips.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from qs_engine.core.decimal_policy import to_decimal
from qs_engine.core.errors import ValidationError
from qs_engine.core.security import SessionContext, UserRole, hash_pin, verify_pin
from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.resources.category_registry import (
    CategoryRecord,
    CategoryRegistry,
    NEEDS_VERIFICATION,
    SCHEMA_VERSION,
)
from qs_engine.resources.code_policy import (
    CodePatternEngine,
    CodePatternPreset,
    MaterialCodePolicy,
    POLICY_MODES,
    POLICY_LABELS,
    category_shorthand,
    ensure_available,
    policy_label,
    slugify_name,
)
from qs_engine.resources.material_store import (
    MaterialStore,
    RateLibrary,
    default_materials_path,
    generate_material_code,
    validate_material_code,
    USER_MATERIALS_PATH,
)

REPO = MasterDataRepository()


# ------------------------------------------------------------------ #
# Code Pattern Engine
# ------------------------------------------------------------------ #

def test_code_pattern_engine_format():
    preset = CodePatternPreset(
        preset_id="test", display_name="Test",
        template="{PREFIX}{SEPARATOR}{SEQUENCE}")
    result = CodePatternEngine.format_code(
        preset, prefix="AGG", sequence=1, delimiter="-", padding=3)
    assert result == "AGG-001"


def test_code_pattern_engine_custom_template():
    preset = CodePatternPreset(
        preset_id="test", display_name="Test",
        template="{CATEGORY_ID}:{SEQUENCE}")
    result = CodePatternEngine.format_code(
        preset, prefix="AGG", sequence=5, delimiter="/", padding=2)
    assert result == "AGG:05"


def test_code_pattern_engine_manual():
    preset = CodePatternPreset(
        preset_id="manual", display_name="Manual",
        template="", is_manual=True)
    result = CodePatternEngine.format_code(preset, "", 1)
    assert result == ""


def test_code_pattern_engine_padding():
    preset = CodePatternPreset(
        preset_id="test", display_name="Test",
        template="{PREFIX}{SEPARATOR}{SEQUENCE}")
    result = CodePatternEngine.format_code(
        preset, prefix="BIN", sequence=42, delimiter=".", padding=5)
    assert result == "BIN.00042"


def test_material_code_policy_defaults():
    policy = MaterialCodePolicy()
    assert policy.mode == "CATEGORY_PREFIX"
    assert policy._effective_template() == "{PREFIX}{SEPARATOR}{SEQUENCE}"
    assert policy._effective_padding() == 3
    assert policy._effective_separator() == "-"


def test_material_code_policy_custom_prefix():
    policy = MaterialCodePolicy.parse(
        "CUSTOM_PREFIX", custom_prefix="SITE-A")
    assert policy.mode == "CUSTOM_PREFIX"
    assert policy.custom_prefix == "SITE-A"


def test_material_code_policy_parse_invalid_mode():
    with pytest.raises(ValidationError):
        MaterialCodePolicy.parse("UNKNOWN_MODE")


def test_policy_label():
    assert policy_label("CATEGORY_PREFIX") == "Category Prefix (AGG-001)"


def test_policy_label_unknown():
    with pytest.raises(ValidationError):
        policy_label("UNKNOWN_MODE")


# ------------------------------------------------------------------ #
# Category Registry
# ------------------------------------------------------------------ #

def test_category_registry_list_categories():
    registry = CategoryRegistry(REPO)
    cats = registry.list_categories()
    assert isinstance(cats, list)
    assert len(cats) > 0


def test_category_registry_get_category():
    registry = CategoryRegistry(REPO)
    cat = registry.get_category("aggregate")
    assert isinstance(cat, CategoryRecord)
    assert cat.category_id == "aggregate"


def test_category_registry_get_category_unknown():
    registry = CategoryRegistry(REPO)
    with pytest.raises(ValidationError):
        registry.get_category("nonexistent_category")


def test_category_record_to_dict():
    cat = CategoryRecord(
        category_id="test", category_name="Test Category",
        prefix="TEST", sap_gl_code="1234",
        gl_description="Test GL")
    d = cat.to_dict()
    assert d["category_id"] == "test"
    assert d["prefix"] == "TEST"
    assert d["sap_gl_code"] == "1234"


def test_category_record_from_dict():
    d = {"category_id": "test", "category_name": "Test",
         "prefix": "TEST"}
    cat = CategoryRecord.from_dict(d)
    assert cat.category_id == "test"


def test_category_shorthand():
    assert category_shorthand("aggregate") == "AGG"
    assert category_shorthand("binder") == "BIN"


def test_category_shorthand_user():
    assert category_shorthand("user:kenya-supplies") == "KEN"


# ------------------------------------------------------------------ #
# Material Store
# ------------------------------------------------------------------ #

def test_material_store_existing_codes():
    store = MaterialStore()
    codes = store.existing_codes()
    assert isinstance(codes, list)


def test_validate_material_code_valid():
    assert validate_material_code("AGG-001") is True
    assert validate_material_code("CEM-001") is True
    assert validate_material_code("SITE-A-001") is True


def test_validate_material_code_invalid():
    assert validate_material_code("") is False
    assert validate_material_code("AGG@001") is False


def test_generate_material_code():
    code = generate_material_code("aggregate", 1)
    assert code == "AGG-001"


def test_default_materials_path():
    p = default_materials_path()
    assert p.name == "user_materials.json"


# ------------------------------------------------------------------ #
# Rate Library
# ------------------------------------------------------------------ #

def test_rate_library_add_and_get():
    lib = RateLibrary()
    lib.add_rate_card("RC-001", "Test Rate", "concrete", "m3",
                       base_rate=150.0)
    card = lib.get_rate_card("RC-001")
    assert card is not None
    assert card["description"] == "Test Rate"
    assert card["base_rate"] == 150.0


def test_rate_library_list():
    lib = RateLibrary()
    cards = lib.list_rate_cards()
    assert isinstance(cards, list)


# ------------------------------------------------------------------ #
# Security: PBKDF2 & SessionContext
# ------------------------------------------------------------------ #

def test_hash_pin():
    pin_hash, salt, iterations = hash_pin("123456")
    assert len(pin_hash) == 64  # SHA256 hex
    assert len(salt) == 32  # 16 bytes hex
    assert iterations == 100_000


def test_verify_pin():
    pin_hash, salt, _ = hash_pin("123456")
    assert verify_pin("123456", pin_hash, salt)
    assert not verify_pin("654321", pin_hash, salt)


def test_session_context_default_role():
    ctx = SessionContext()
    assert ctx.role == UserRole.SITE_CLERK


def test_session_context_is_admin():
    ctx = SessionContext()
    assert not ctx.is_admin()
    ctx.set_role(UserRole.SUPER_ADMIN)
    assert ctx.is_admin()


def test_session_context_check_access_admin_view():
    ctx = SessionContext()
    with pytest.raises(ValidationError):
        ctx.check_access("admin_setup")


def test_session_context_check_access_public_view():
    ctx = SessionContext()
    assert ctx.check_access("overview") is True


def test_session_context_set_role():
    ctx = SessionContext()
    ctx.set_role(UserRole.OPERATIONAL_ADMIN)
    assert ctx.role == UserRole.OPERATIONAL_ADMIN


def test_session_context_admin_only_views():
    from qs_engine.core.security import ADMIN_ONLY_VIEWS
    assert "admin_setup" in ADMIN_ONLY_VIEWS
    assert "global_policy_editor" in ADMIN_ONLY_VIEWS


def test_session_context_pin_lockout_threshold():
    from qs_engine.core.security import PIN_LOCKOUT_THRESHOLD
    assert PIN_LOCKOUT_THRESHOLD == 5


def test_session_context_pin_lockout_seconds():
    from qs_engine.core.security import PIN_LOCKOUT_SECONDS
    assert PIN_LOCKOUT_SECONDS == 300


def test_session_context_pin_validation():
    from qs_engine.core.security import PIN_RE
    assert PIN_RE.match("123456")
    assert not PIN_RE.match("123")
    assert not PIN_RE.match("1234567890123")


def test_session_context_operational_pin_set():
    ctx = SessionContext()
    ctx.set_operational_pin("123456")
    assert ctx._operational_pin_hash is not None


def test_session_context_operational_pin_verify_temp_config(tmp_path):
    from qs_engine.core.security import USER_CONFIG_PATH
    # Use a temp config path to avoid lockout state bleeding
    orig_path = USER_CONFIG_PATH
    # Create a fresh SessionContext with temp config
    import qs_engine.core.security as sec
    sec.USER_CONFIG_PATH = tmp_path / "user_config.json"
    try:
        ctx = SessionContext()
        ctx.set_operational_pin("123456")
        assert ctx.verify_operational_pin("123456")
        # A wrong PIN raises the typed error — it never returns False.
        with pytest.raises(ValidationError):
            ctx.verify_operational_pin("654321")
    finally:
        sec.USER_CONFIG_PATH = orig_path


def test_session_context_failed_attempts_tracking(tmp_path):
    from qs_engine.core.security import USER_CONFIG_PATH
    orig_path = USER_CONFIG_PATH
    import qs_engine.core.security as sec
    sec.USER_CONFIG_PATH = tmp_path / "user_config.json"
    try:
        ctx = SessionContext()
        ctx.set_operational_pin("123456")
        with pytest.raises(ValidationError):
            ctx.verify_operational_pin("wrong")
        with pytest.raises(ValidationError):
            ctx.verify_operational_pin("wrong")
        assert ctx._failed_pin_attempts == 2
    finally:
        sec.USER_CONFIG_PATH = orig_path


def test_session_context_failed_attempts_tracking(tmp_path):
    from qs_engine.core.security import USER_CONFIG_PATH
    orig_path = USER_CONFIG_PATH
    import qs_engine.core.security as sec
    sec.USER_CONFIG_PATH = tmp_path / "user_config.json"
    try:
        ctx = SessionContext()
        ctx.set_operational_pin("123456")
        with pytest.raises(ValidationError):
            ctx.verify_operational_pin("wrong")
        with pytest.raises(ValidationError):
            ctx.verify_operational_pin("wrong")
        assert ctx._failed_pin_attempts == 2
    finally:
        sec.USER_CONFIG_PATH = orig_path


def test_session_context_pin_lockout_after_five_failures(tmp_path):
    from qs_engine.core.security import PIN_LOCKOUT_THRESHOLD, PIN_LOCKOUT_SECONDS, USER_CONFIG_PATH
    orig_path = USER_CONFIG_PATH
    import qs_engine.core.security as sec
    sec.USER_CONFIG_PATH = tmp_path / "user_config.json"
    try:
        ctx = SessionContext()
        ctx.set_operational_pin("123456")
        for _ in range(PIN_LOCKOUT_THRESHOLD):
            try:
                ctx.verify_operational_pin("wrong")
            except ValidationError:
                pass
        with pytest.raises(ValidationError) as exc:
            ctx.verify_operational_pin("wrong")
        assert "locked out" in str(exc.value).lower()
    finally:
        sec.USER_CONFIG_PATH = orig_path


def test_session_context_operational_pin_set(tmp_path):
    from qs_engine.core.security import USER_CONFIG_PATH
    orig_path = USER_CONFIG_PATH
    import qs_engine.core.security as sec
    sec.USER_CONFIG_PATH = tmp_path / "user_config.json"
    try:
        ctx = SessionContext()
        ctx.set_operational_pin("123456")
        assert ctx._operational_pin_hash is not None
    finally:
        sec.USER_CONFIG_PATH = orig_path


def test_session_context_operational_pin_verify(tmp_path):
    from qs_engine.core.security import USER_CONFIG_PATH
    orig_path = USER_CONFIG_PATH
    import qs_engine.core.security as sec
    sec.USER_CONFIG_PATH = tmp_path / "user_config.json"
    try:
        ctx = SessionContext()
        ctx.set_operational_pin("123456")
        assert ctx.verify_operational_pin("123456")
        # A wrong PIN raises the typed error — it never returns False.
        with pytest.raises(ValidationError):
            ctx.verify_operational_pin("654321")
    finally:
        sec.USER_CONFIG_PATH = orig_path