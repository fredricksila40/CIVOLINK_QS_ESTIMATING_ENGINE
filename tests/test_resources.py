"""Resources subsystem tests (Phase 2 Task 2.2).

Dedicated coverage for the user-material stack: atomic persistence
(no half-written store, no tmp residue), immutable user identity
(canonical key survives renames, identifiers-only records), fail-closed
material resolution through MaterialResolver, and the shared
``default_repository`` factory that makes the resolver the primary
lookup interface behind both the UI shell and the HTTP API.
"""

import json

import pytest

from qs_engine.core.assumptions import VerificationStatus
from qs_engine.core.errors import (
    UnknownMasterDataKeyError,
    ValidationError,
)
from qs_engine.master_data.repository import MasterDataRepository
from qs_engine.master_data.schemas import MATERIALS
from qs_engine.resources import (
    MaterialResolver,
    build_material_stack,
    default_repository,
)
from qs_engine.resources.material_store import USER_KEY_PREFIX


def _create(stack, **overrides):
    fields = dict(name="Portland Cement 32.5N", code="CEM-32.5N",
                  category_id="binder", unit="bag")
    fields.update(overrides)
    return stack.store.create_material(**fields)


@pytest.fixture()
def stack(tmp_path):
    """Full stack over the shipped seed, tmp-backed."""
    return build_material_stack(MasterDataRepository(), tmp_path)


# --- atomic persistence --------------------------------------------------------

def test_create_persists_atomically_without_tmp_residue(stack):
    record = _create(stack)
    path = stack.store.path
    assert path.is_file()
    assert not list(path.parent.glob("*.tmp"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert [row["key"] for row in payload["materials"]] == [record["key"]]
    # Reload (fresh process semantics) sees exactly the same records.
    stack.store.reload()
    assert [row["key"] for row in stack.store.list_materials()] == [
        record["key"]]


def test_failed_replace_preserves_store_and_leaves_no_tmp(
        stack, monkeypatch):
    import qs_engine.resources.material_store as material_store
    _create(stack)
    before = stack.store.path.read_bytes()

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(material_store.os, "replace", boom)
    with pytest.raises(ValidationError) as exc_info:
        _create(stack, name="Second Cement", code="CEM-SECOND")
    assert "Could not write" in str(exc_info.value)
    monkeypatch.undo()
    # Previous store intact on disk, no .tmp residue, memory rolled back.
    assert stack.store.path.read_bytes() == before
    assert not list(stack.store.path.parent.glob("*.tmp"))
    assert len(stack.store.list_materials()) == 1
    again = build_material_stack(MasterDataRepository(),
                                 stack.store.path.parent)
    assert len(again.store.list_materials()) == 1


def test_unreadable_store_fails_closed_on_reload(stack):
    stack.store.path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValidationError) as exc_info:
        stack.store.reload()
    assert "unreadable" in str(exc_info.value)


def test_version_unknown_store_rejected(stack):
    _create(stack)
    payload = json.loads(stack.store.path.read_text(encoding="utf-8"))
    payload["schema_version"] = "99.0"
    stack.store.path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError) as exc_info:
        build_material_stack(MasterDataRepository(),
                             stack.store.path.parent)
    assert "schema_version" in str(exc_info.value)


# --- immutable user identity ---------------------------------------------------

def test_canonical_key_survives_code_rename(stack):
    created = _create(stack)
    key = created["key"]
    assert key.startswith(USER_KEY_PREFIX)
    updated = stack.store.update_material(key, code="CEMENT-KENYA-01")
    assert updated["key"] == key, "canonical key must never move"
    assert created["code"] in updated["aliases"]
    # Every previous reference still resolves to THIS material.
    assert stack.store.lookup(key)["key"] == key
    assert stack.store.lookup("CEM-32.5N")["key"] == key
    assert stack.store.lookup("CEMENT-KENYA-01")["key"] == key


def test_user_materials_are_identifiers_only(stack):
    record = _create(stack)
    for store_record in (record,
                         stack.store.get_material(record["key"])):
        assert store_record["density"] is None
        assert store_record["default_wastage_pct"] is None
        assert store_record["verification_status"] == (
            VerificationStatus.NEEDS_VERIFICATION)
        assert store_record["source"] == "user"
    # No API surface can inject engineering properties: create and
    # update only ever take identifiers.
    with pytest.raises(TypeError):
        stack.store.create_material(
            name="Dense Cement", code="CEM-DENSE",
            category_id="binder", unit="bag", density="1440")


def test_deactivated_user_material_fails_closed(stack):
    record = _create(stack)
    stack.store.deactivate_material(record["key"])
    assert stack.store.lookup(record["key"]) is None
    assert stack.store.list_materials() == []
    with pytest.raises(UnknownMasterDataKeyError):
        stack.resolver.get(MATERIALS, record["key"])


# --- material resolution through the resolver ---------------------------------

def test_resolver_is_drop_in_over_seed(stack):
    record = _create(stack)
    seed = MasterDataRepository()
    resolver = stack.resolver
    assert isinstance(resolver, MaterialResolver)
    assert resolver.domains() == seed.domains()
    assert resolver.table_version(MATERIALS) == seed.table_version(
        MATERIALS)
    seed_rows = seed.list(MATERIALS)
    resolved = resolver.list(MATERIALS)
    # Seed rows first, byte-for-byte the same records.
    assert resolved[:len(seed_rows)] == seed_rows
    assert len(resolved) == len(seed_rows) + 1  # one user material
    assert resolved[-1]["key"] == record["key"]
    # User data never bleeds into other domains.
    for domain in seed.domains():
        if domain == MATERIALS:
            continue
        assert resolver.list(domain) == seed.list(domain)


def test_user_material_resolves_by_key_code_and_alias(stack):
    record = _create(stack)
    resolver = stack.resolver
    assert resolver.get(MATERIALS, record["key"])["name"] == (
        "Portland Cement 32.5N")
    assert resolver.get(MATERIALS, "CEM-32.5N")["key"] == record["key"]
    effective = resolver.resolve_effective("CEM-32.5N")
    assert effective.is_user is True
    assert effective.source == "user"
    assert effective.needs_verification is True
    assert effective.record["density"] is None
    seed_key = MasterDataRepository().list(MATERIALS)[0]["key"]
    from_seed = resolver.resolve_effective(seed_key)
    assert from_seed.is_user is False
    assert from_seed.source == "seed"


def test_unknown_material_miss_is_typed(stack):
    with pytest.raises(UnknownMasterDataKeyError):
        stack.resolver.get(MATERIALS, "definitely_missing_material")
    # Non-material domains bypass the user store entirely.
    with pytest.raises(UnknownMasterDataKeyError):
        stack.resolver.get("concrete_classes", "user:not-a-class")


# --- shared factory: the primary lookup interface -----------------------------

def test_default_repository_returns_resolver_over_seed():
    repository, material_stack, error = default_repository()
    assert isinstance(repository, MaterialResolver)
    assert error is None
    assert material_stack is not None
    assert material_stack.resolver is repository
    assert material_stack.store.path.name == "user_materials.json"
    assert repository.domains() == MasterDataRepository().domains()


def test_default_repository_fails_closed_on_unreadable_user_data(
        monkeypatch, tmp_path):
    import qs_engine.resources as resources
    bad = tmp_path / "user_materials.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(resources, "default_materials_path",
                        lambda: bad)
    monkeypatch.setattr(resources, "default_categories_path",
                        lambda: tmp_path / "user_categories.json")
    repository, material_stack, error = default_repository()
    assert material_stack is None
    assert isinstance(repository, MasterDataRepository)
    assert isinstance(error, str) and "unreadable" in error


def test_ui_and_api_share_the_default_repository_factory():
    import inspect

    from qs_engine.ui import views
    from qs_engine.web import api
    assert "default_repository" in inspect.getsource(views.QSApp.__init__)
    assert "default_repository" in inspect.getsource(api._repository)


def test_factory_surface_is_exported():
    import qs_engine.resources as resources
    assert "default_repository" in resources.__all__
    assert callable(resources.default_repository)
