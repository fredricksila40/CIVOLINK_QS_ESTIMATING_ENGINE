"""Licensing storage migration tests (Phase 23.6-11): schema
versioning, idempotent v1->v2 upgrades, atomic writes, backups,
future-schema refusal, and AppData isolation. No network anywhere.
"""

from pathlib import Path
from unittest import mock
import os

from qs_engine.licensing.storage import (
    BACKUP_RETAIN_COUNT,
    CURRENT_SCHEMA_VERSION,
    MIN_SUPPORTED_SCHEMA_VERSION,
    FutureSchemaError,
    LicenseStore,
    atomic_write_json,
    create_backup,
    default_license_dir,
    load_state,
    migrate_license_data,
    save_state,
)


def _v1_record(**kwargs):
    record = {"provider": "fake", "key_hint": "EY-1",
              "state": "ACTIVE", "organization": "Acme",
              "expires": None, "device_activated": True}
    record.update(kwargs)
    return record


def _v2_record(**kwargs):
    record = _v1_record(schema_version=2, updated_at=1700000000)
    record.update(kwargs)
    return record


# --- versions ------------------------------------------------------------------

def test_schema_version_constants():
    assert CURRENT_SCHEMA_VERSION == 2
    assert MIN_SUPPORTED_SCHEMA_VERSION == 1
    assert BACKUP_RETAIN_COUNT == 5


# --- load_state ------------------------------------------------------------------

def test_load_current_schema_v2(tmp_path):
    path = tmp_path / "license.json"
    path.write_text('{"state": "ACTIVE", "schema_version": 2}',
                    encoding="utf-8")
    record, status = load_state(path)
    assert status == "ok"
    assert record == {"state": "ACTIVE", "schema_version": 2}


def test_load_migrates_legacy_v1(tmp_path):
    path = tmp_path / "license.json"
    path.write_text('{"state": "ACTIVE"}', encoding="utf-8")
    record, status = load_state(path)
    assert status == "migrated"
    assert record["schema_version"] == 2
    assert record["state"] == "ACTIVE"
    assert isinstance(record["updated_at"], int)
    # pure read: disk itself is untouched until an explicit save.
    assert "schema_version" not in path.read_text(encoding="utf-8")


def test_load_missing_file(tmp_path):
    assert load_state(tmp_path / "license.json") == (None, "missing")


def test_load_corrupt_file(tmp_path):
    path = tmp_path / "license.json"
    path.write_text("{oops", encoding="utf-8")
    assert load_state(path) == (None, "corrupt")
    path.write_text("[1, 2]", encoding="utf-8")
    assert load_state(path) == (None, "corrupt")


def test_load_future_schema_refused(tmp_path):
    path = tmp_path / "license.json"
    path.write_text('{"state": "ACTIVE", "schema_version": 99}',
                    encoding="utf-8")
    assert load_state(path) == (None, "future_schema")


# --- migrate ---------------------------------------------------------------------

def test_migrate_v1_to_v2_stamps_once():
    first = migrate_license_data(_v1_record())
    assert first["schema_version"] == 2
    assert isinstance(first["updated_at"], int)
    assert first["state"] == "ACTIVE"
    assert first["organization"] == "Acme"
    second = migrate_license_data(first)
    assert second == first  # strictly idempotent


def test_migrate_v2_returns_identical_copy():
    record = _v2_record()
    assert migrate_license_data(record) == record
    assert migrate_license_data(record) is not record


def test_migrate_rejects_future_and_non_mappings():
    try:
        migrate_license_data({"schema_version": 99})
    except FutureSchemaError:
        pass
    else:
        raise AssertionError("future schema must raise")
    for bad in (None, [], "x", 42):
        try:
            migrate_license_data(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"non-mapping must raise: {bad!r}")


# --- atomic writes -----------------------------------------------------------------

def test_atomic_write_round_trip(tmp_path):
    target = tmp_path / "license.json"
    assert atomic_write_json(target, {"a": 1}) == target
    record, status = load_state(target)
    assert status == "migrated"
    assert record["a"] == 1
    assert record["schema_version"] == 2


def test_atomic_failure_preserves_prior_state(tmp_path):
    target = tmp_path / "license.json"
    target.write_text('{"state": "ACTIVE", "schema_version": 2}',
                      encoding="utf-8")
    with mock.patch.object(os, "replace",
                           side_effect=OSError("disk gone")):
        try:
            atomic_write_json(target, {"state": "X"})
        except OSError:
            pass
        else:
            raise AssertionError("replace failure must propagate")
    assert target.read_text(
        encoding="utf-8") == '{"state": "ACTIVE", "schema_version": 2}'
    assert not (tmp_path / "license.json.tmp").exists()


# --- backups -------------------------------------------------------------------------

def test_backup_creation_and_retention(tmp_path):
    target = tmp_path / "license.json"
    for index in range(7):
        save_state(target, _v1_record(state=f"S{index}"))
    backups = sorted(
        (tmp_path / "licensing" / "backups").glob("license-*.json"))
    assert len(backups) == 5
    assert load_state(target)[0]["state"] == "S6"


def test_no_backup_when_nothing_on_disk(tmp_path):
    target = tmp_path / "license.json"
    save_state(target, _v1_record())
    assert not (tmp_path / "licensing").exists()


def test_create_backup_missing_file_returns_none(tmp_path):
    assert create_backup(tmp_path / "license.json") is None


# --- future-schema protection --------------------------------------------------------------

def test_save_refuses_future_disk(tmp_path):
    target = tmp_path / "license.json"
    future = '{"state": "ACTIVE", "schema_version": 99}'
    target.write_text(future, encoding="utf-8")
    try:
        save_state(target, _v1_record())
    except FutureSchemaError:
        pass
    else:
        raise AssertionError("future disk must refuse overwrite")
    assert target.read_text(encoding="utf-8") == future


def test_save_refuses_future_input(tmp_path):
    target = tmp_path / "license.json"
    try:
        save_state(target, {"schema_version": 99})
    except FutureSchemaError:
        pass
    else:
        raise AssertionError("future input must raise")
    assert not target.exists()


def test_save_heals_corrupt_disk(tmp_path):
    target = tmp_path / "license.json"
    target.write_text("{oops", encoding="utf-8")
    save_state(target, _v1_record())
    record, status = load_state(target)
    assert status in ("ok", "migrated")
    assert record["state"] == "ACTIVE"


# --- store method delegation ---------------------------------------------------------------

def test_store_methods_delegate(tmp_path):
    store = LicenseStore(path=tmp_path / "license.json")
    assert store.load_state() == (None, "missing")
    assert store.save_state(_v1_record()) == store.path
    record, status = store.load_state()
    assert status == "ok"  # save_state persists the migrated v2 form
    assert record["schema_version"] == 2


# --- AppData isolation -----------------------------------------------------------------------

def test_appdata_isolation(tmp_path, monkeypatch):
    monkeypatch.delenv("CIVOLINK_LICENSE_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    base = default_license_dir()
    assert base == tmp_path / "CIVOLINK"
    store = LicenseStore()
    assert str(store.path).startswith(str(base))
    assert "Program Files" not in str(store.path)
    save_state(store.path, _v1_record())
    save_state(store.path, _v1_record(state="B"))
    backups = list((base / "licensing" / "backups").glob("*.json"))
    assert len(backups) == 1
    for path in [store.path] + backups:
        assert str(path).startswith(str(base))


# --- no network ----------------------------------------------------------------------------------

def test_storage_modules_import_no_network_stack():
    import ast as _ast
    # Persistence layer only: provider.py legitimately uses urllib
    # for Keygen API transport (Phase 23); storage must not.
    path = (Path(__file__).parent.parent / "qs_engine" / "licensing"
            / "storage.py")
    tree = _ast.parse(path.read_text(encoding="utf-8"),
                      filename=str(path))
    forbidden = {"socket", "urllib", "requests", "http", "ssl",
                 "http.client", "ftplib"}
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            names = {alias.name.split(".")[0]
                     for alias in node.names}
        elif isinstance(node, _ast.ImportFrom) and node.module:
            names = {node.module.split(".")[0]}
        else:
            continue
        assert not (names & forbidden), (
            f"storage.py: network import {names & forbidden}")


def test_storage_calls_survive_blocked_sockets(tmp_path):
    import socket
    target = tmp_path / "license.json"
    with mock.patch.object(socket, "socket",
                           side_effect=AssertionError("no sockets")):
        save_state(target, _v1_record())
        assert load_state(target)[1] == "ok"  # persisted as v2
        assert migrate_license_data(_v1_record())["schema_version"] == 2
        create_backup(target)
