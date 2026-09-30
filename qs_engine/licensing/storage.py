"""Local license-artifact storage (no custom crypto, no secrets).

The stored record is an opaque provider-supplied artifact plus cached
display fields — never a provider secret, private key, API token, or
admin credential (there is nothing here worth stealing because the
desktop never holds such material).

Location: per-user application data (Windows %APPDATA%/CIVOLINK,
else ~/.config/civolink), overridable via CIVOLINK_LICENSE_DIR
(which tests use for isolation). This deliberately differs from the
engine-root config/ convention: config/ ships read-mostly defaults
inside the install tree (read-only _MEIPASS when frozen), while
licensing state is per-user, per-machine, and must survive upgrades.

Schema handling: persisted records carry schema_version (v2 current,
v1 legacy without the field). migrate_license_data() upgrades v1 to
v2 (pure, idempotent); newer schemas raise FutureSchemaError and are
never overwritten. Writes are atomic (tmp + fsync + replace) with
the last 5 backups retained under <store-dir>/licensing/backups/.
See docs/LICENSING_MIGRATION.md.
"""

import json
import os
import time
from pathlib import Path
from typing import Dict, Optional

LICENSE_FILENAME = "license.json"
LICENSE_DIR_ENV = "CIVOLINK_LICENSE_DIR"

#: Persisted license schema versions.
CURRENT_SCHEMA_VERSION = 2
MIN_SUPPORTED_SCHEMA_VERSION = 1

#: Backup retention: newest N backups kept per license file.
BACKUP_RETAIN_COUNT = 5


class FutureSchemaError(Exception):
    """Refusal to read or overwrite a newer-than-supported schema."""


def default_license_dir() -> Path:
    """Per-user licensing directory (created on first save)."""
    override = os.environ.get(LICENSE_DIR_ENV, "").strip()
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        return Path(appdata) / "CIVOLINK"
    return Path.home() / ".config" / "civolink"


class LicenseStore:
    """JSON file store for one license record (missing/corrupt → None)."""

    def __init__(self, path=None):
        if path is not None:
            self.path = Path(path)
        else:
            self.path = default_license_dir() / LICENSE_FILENAME

    def load(self) -> Optional[Dict]:
        """Stored record, or None when missing, corrupt, or unshaped."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict):
            return None
        return raw

    def save(self, record: Dict) -> Path:
        """Persist a record; returns the file path."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(dict(record), indent=2) + "\n",
                             encoding="utf-8")
        return self.path

    def clear(self) -> None:
        """Remove the stored record (missing file is not an error)."""
        try:
            self.path.unlink()
        except OSError:
            pass

    def load_state(self):
        """(record|None, status) with migration; raw load() unchanged."""
        return load_state(self.path)

    def save_state(self, record: Dict) -> Path:
        """Migrate, refuse future disk schemas, backup, atomic write."""
        return save_state(self.path, record)


def _schema_version_of(record) -> int:
    """Schema version, treating missing/garbled values as legacy v1."""
    try:
        return int(record.get("schema_version", 1))
    except (TypeError, ValueError):
        return 1


def migrate_license_data(raw_data) -> Dict:
    """Migrate a stored record to the current schema (pure, no I/O).

    Missing/1 -> v2 (schema_version set, updated_at stamped when
    absent; provider values are never rewritten). v2 input returns an
    identical copy (strictly idempotent). Newer schemas raise
    FutureSchemaError; non-mappings raise ValueError.
    """
    if not isinstance(raw_data, dict):
        raise ValueError("license record must be a mapping")
    version = _schema_version_of(raw_data)
    if version > CURRENT_SCHEMA_VERSION:
        raise FutureSchemaError(
            f"license schema v{version} is newer than supported "
            f"v{CURRENT_SCHEMA_VERSION}; upgrade the application "
            f"instead of downgrading the license.")
    record = dict(raw_data)
    if version == CURRENT_SCHEMA_VERSION:
        return record
    record["schema_version"] = CURRENT_SCHEMA_VERSION
    if "updated_at" not in record:
        record["updated_at"] = int(time.time())
    return record


def atomic_write_bytes(target_path, payload: bytes) -> Path:
    """Write bytes atomically: tmp file + flush + fsync + os.replace.

    Single source of truth for atomic file writes in this codebase
    (license records and .clk project files both commit through here).
    The target is either fully replaced or untouched; a failed write
    cleans up its tmp file and re-raises.
    """
    target = Path(target_path)
    tmp = target.parent / (target.name + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except Exception:
        try:
            if tmp.is_file():
                tmp.unlink()
        except OSError:
            pass
        raise
    return target


def atomic_write_json(target_path, data) -> Path:
    """Write JSON atomically via atomic_write_bytes (tmp + fsync + replace).

    The target is either fully replaced or untouched; a failed write
    cleans up its tmp file and re-raises.
    """
    payload = (json.dumps(dict(data), indent=2) + "\n").encode("utf-8")
    return atomic_write_bytes(target_path, payload)


def _backups_dir_for(target: Path) -> Path:
    """Backups directory for a license file.

    <store-dir>/licensing/backups/ — which is exactly
    %APPDATA%/CIVOLINK/licensing/backups/ under the default Windows
    location, and stays test-isolated for override paths.
    """
    return target.parent / "licensing" / "backups"


def create_backup(target_path):
    """Copy the license file into backups/, prune to the newest 5.

    Returns the backup path, or None when there is no file to back
    up. Only parseable-dict files are backed up (corrupt bytes are
    not worth a retention slot).
    """
    target = Path(target_path)
    if not target.is_file():
        return None
    try:
        parsed = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    backups = _backups_dir_for(target)
    backups.mkdir(parents=True, exist_ok=True)
    backup = backups / f"{target.stem}-{time.time_ns()}.json"
    backup.write_bytes(target.read_bytes())
    kept = sorted(backups.glob(f"{target.stem}-*.json"),
                  key=lambda path: path.name)[-BACKUP_RETAIN_COUNT:]
    for stale in backups.glob(f"{target.stem}-*.json"):
        if stale not in kept:
            try:
                stale.unlink()
            except OSError:
                pass
    return backup


def load_state(path):
    """(record|None, status): ok, migrated, missing, corrupt, future.

    Pure read path: migrations are returned in memory and never
    persisted here; callers save explicitly via save_state().
    """
    target = Path(path)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "missing"
    except (OSError, ValueError):
        return None, "corrupt"
    if not isinstance(raw, dict):
        return None, "corrupt"
    try:
        migrated = migrate_license_data(raw)
    except FutureSchemaError:
        return None, "future_schema"
    if _schema_version_of(raw) == CURRENT_SCHEMA_VERSION:
        return migrated, "ok"
    return migrated, "migrated"


def save_state(path, record: Dict) -> Path:
    """Persist a record: migrate, refuse future disk, backup, write.

    Raises FutureSchemaError when the input — or the existing disk
    payload — carries a newer schema (the disk file is left
    untouched). Backs up the prior valid file, then commits the
    migrated record atomically.
    """
    migrated = migrate_license_data(record)
    target = Path(path)
    if target.is_file():
        try:
            disk = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            disk = None
        if isinstance(disk, dict):
            if _schema_version_of(disk) > CURRENT_SCHEMA_VERSION:
                raise FutureSchemaError(
                    "disk holds a newer license schema; refusing "
                    "to overwrite it with an older build.")
            create_backup(target)
    return atomic_write_json(target, migrated)
