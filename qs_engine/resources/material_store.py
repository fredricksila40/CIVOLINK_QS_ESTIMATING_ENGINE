"""Writable material store for user materials and rate lines.

Two persistence surfaces:

* ``user_materials.json`` — user-created material overrides persisted
  as a JSON object (``schema_version`` / ``updated_on`` /
  ``materials``) in the engine data directory. Loading is fail-closed:
  malformed, version-unknown, or non-record content raises a typed
  error instead of being silently ignored. Writes are atomic (tmp file
  + ``os.replace``) and roll back in memory when they fail.
* ``rate_library.db`` — SQLite store for assembly rates and rate cards
  managed on the Rate Builder page.

Both are created on first write. Neither is part of the shipped
seed master data.

A user material carries identifiers ONLY: name, material code,
category (resolved through the category registry), default unit. It
never receives engineering properties — those stay NULL with
``verification_status = NEEDS_VERIFICATION`` so downstream
calculations fail closed exactly like an unverified seed record.

Identity rules: ``key`` = ``user:<stable-id>`` is generated once and
never changes; ``code`` is user-editable, and renaming keeps the
previous code in ``aliases`` so earlier references keep resolving to
THIS material — never to a different one.
"""

import json
import os
import sqlite3
import threading
import uuid
from datetime import date
from pathlib import Path
from typing import Dict, List, Mapping, Optional

from ..core.assumptions import VerificationStatus
from ..core.errors import (
    UnknownMasterDataKeyError,
    UnknownUnitError,
    ValidationError,
)
from ..core.units import SUPPORTED_UNITS
from ..master_data.schemas import MATERIALS, validate_record
from .category_registry import USER_SOURCE

#: User-materials file format version (one format for this build).
SCHEMA_VERSION = "1.0"
#: Canonical key prefix: engines resolve ``user:<stable-id>``.
USER_KEY_PREFIX = "user:"
#: Acceptable characters in a user material code (1-64 of [A-Za-z0-9._-]).
CODE_RE = __import__("re").compile(r"^[A-Za-z0-9._-]{1,64}$")

#: Maximum length of a user material name.
NAME_MAX = 200
#: Engineering values stay NULL until verified; the unit the density
#: column will use once verification provides a value.
_DENSITY_UNIT = "kg/m³"
#: Per-record format version stamped on every user material.
_RECORD_VERSION = "1.0"

#: Engine-root data/user_materials.json (created on first write).
USER_MATERIALS_PATH = (Path(__file__).resolve().parent.parent.parent
                       / "data" / "user_materials.json")

#: Engine-root data/rate_library.db (created on first write).
RATE_LIBRARY_PATH = (Path(__file__).resolve().parent.parent.parent
                     / "data" / "rate_library.db")


def _ensure_data_dir() -> None:
    """Create the data directory if it does not exist."""
    USER_MATERIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RATE_LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------ #
# User materials store
# ------------------------------------------------------------------ #

#: User-material records are plain dicts validated against the shared
#: materials schema (MaterialStore.validate_material) — no dataclass.



class MaterialStore:
    """User material override store: writable, versioned, fail-closed.

    Binds one JSON file (default: the engine data directory's
    ``user_materials.json``) to the category registry that validates
    categories. Construction reads the file; malformed or
    version-unknown content fails closed with a typed error.
    """

    def __init__(self, path=None, registry=None):
        """Open the store at ``path`` (default data dir) with its registry."""
        self.path = Path(path) if path is not None else default_materials_path()
        self._registry = registry
        self._records: List[dict] = []
        #: Shipped (seed) keys the operator removed from the catalogue
        #: view — a user-side overlay; the seed table is never written.
        self._hidden_seed: List[str] = []
        self._load()

    def _load(self) -> None:
        """Load user materials; missing file = none (empty, not an error).

        Malformed or version-unknown files fail closed with a typed
        error (requirement: malformed preference data is rejected
        safely, never partially applied).
        """
        self._records = []
        self._hidden_seed = []
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(
                f"User material store {self.path} is unreadable: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise ValidationError(
                f"User material store {self.path} must be a JSON object")
        version = str(payload.get("schema_version", "") or "")
        if version != SCHEMA_VERSION:
            raise ValidationError(
                f"User material store {self.path} declares schema_version "
                f"{version!r}; this build reads {SCHEMA_VERSION!r} only")
        materials = payload.get("materials") or []
        if not isinstance(materials, list):
            raise ValidationError(
                f"User material store {self.path}: 'materials' must be a list")
        records: List[dict] = []
        for record in materials:
            if not isinstance(record, dict):
                raise ValidationError(
                    f"User material must be a mapping; "
                    f"got {type(record).__name__}")
            records.append(self.validate_material(record))
        self._records = records
        hidden = payload.get("hidden_seed_keys", [])
        if not isinstance(hidden, list):
            raise ValidationError(
                f"User material store {self.path}: 'hidden_seed_keys' "
                f"must be a list")
        cleaned: List[str] = []
        for key in hidden:
            if not isinstance(key, str) or not key.strip():
                raise ValidationError(
                    f"User material store {self.path}: 'hidden_seed_keys' "
                    f"entries must be non-empty strings")
            text = key.strip()
            if text.startswith(USER_KEY_PREFIX):
                raise ValidationError(
                    f"User material store {self.path}: 'hidden_seed_keys' "
                    f"entry {text!r} may not be a user key (user materials "
                    f"are deactivated, never hidden as seed)")
            if text not in cleaned:
                cleaned.append(text)
        self._hidden_seed = cleaned

    def _persist(self) -> None:
        """Atomically write the in-memory records to disk."""
        payload = {
            "schema_version": SCHEMA_VERSION,
            "updated_on": date.today().isoformat(),
            "materials": [dict(record) for record in self._records],
            "hidden_seed_keys": list(self._hidden_seed),
        }
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:
            try:
                tmp.unlink()
            except OSError:
                pass  # never leave a partial .tmp behind
            raise ValidationError(
                f"Could not write user material store {self.path}: {exc}"
            ) from exc

    def persist(self) -> None:
        """Write the current in-memory records to disk (atomic)."""
        self._persist()

    def reload(self) -> None:
        """Re-read the persisted store from disk (application restart)."""
        self._load()

    def validate_material(self, record) -> dict:
        """Validate one record against the shared materials schema.

        Returns a plain dict copy. Raises typed errors otherwise —
        nothing is coerced, defaulted, or zero-filled.
        """
        try:
            validated = validate_record(MATERIALS, dict(record))
        except ValidationError as exc:
            raise ValidationError(
                f"User material store {self.path}: {exc}") from exc
        return dict(validated)

    @staticmethod
    def _new_key() -> str:
        """Stable canonical key: generated ONCE, never derived from code."""
        return f"{USER_KEY_PREFIX}{uuid.uuid4().hex[:12]}"

    def _reserved_codes(self) -> Dict[str, str]:
        """Seed keys/legacy codes/codes — reserved canonical identifiers."""
        from ..master_data.repository import MasterDataRepository
        reserved: Dict[str, str] = {}
        for record in MasterDataRepository().list(MATERIALS):
            for field in ("key", "code", "legacy_code"):
                value = str(record.get(field, "") or "").strip()
                if value:
                    reserved.setdefault(value.casefold(), value)
        return reserved

    def _find_by_key(self, key):
        """Exact canonical-key match (any state); None when unknown."""
        wanted = str(key or "")
        for record in self._records:
            if str(record.get("key", "")) == wanted:
                return record
        return None

    def _code_index(self, active_only: bool = True) -> Dict[str, dict]:
        """casefold(code or alias) -> record.

        Deterministic by construction: codes/aliases are unique
        (case-insensitive) at write time, so a match is always
        unambiguous; an ambiguous index is refused, never guessed.
        """
        index: Dict[str, dict] = {}
        for record in self._records:
            if active_only and not record.get("active", True):
                continue
            references = [record.get("code", "")] + list(
                record.get("aliases") or [])
            for reference in references:
                text = str(reference or "").strip().casefold()
                if not text:
                    continue
                prior = index.get(text)
                if prior is not None and prior is not record:
                    raise ValidationError(
                        f"User material store {self.path}: code/alias "
                        f"{text!r} maps to more than one material — "
                        f"refusing ambiguous lookup")
                index[text] = record
        return index

    def _check_code(self, code, *, exclude_key=None) -> str:
        """Validate a code: format, reserved seed identifiers, uniqueness."""
        text = str(code or "").strip()
        _validate_material_code_format(text)
        folded = text.casefold()
        reserved = self._reserved_codes()
        if folded in reserved:
            raise ValidationError(
                f"Material code {text!r} collides with reserved seed "
                f"identifier {reserved[folded]!r}")
        other = self._code_index(active_only=False).get(folded)
        if other is not None and other.get("key") != exclude_key:
            raise ValidationError(
                f"Material code {text!r} is already used by user material "
                f"{other.get('key')!r}")
        return text

    def existing_codes(self) -> List[str]:
        """All codes and retired aliases (for code suggestions)."""
        codes: List[str] = []
        seen = set()
        for record in self._records:
            references = [record.get("code", "")] + list(
                record.get("aliases") or [])
            for reference in references:
                text = str(reference or "").strip()
                if text and text not in seen:
                    seen.add(text)
                    codes.append(text)
        return codes

    def get_material(self, key) -> dict:
        """Retrieve one user material by canonical key (any state)."""
        return dict(self._resolve_reference(key))

    def _resolve_reference(self, reference) -> dict:
        """Canonical key or code/alias match (any state), else typed miss."""
        ref = str(reference or "").strip()
        record = self._find_by_key(ref) if ref else None
        if record is None and ref:
            record = self._code_index(active_only=False).get(ref.casefold())
        if record is None:
            raise UnknownMasterDataKeyError(
                f"Unknown user material key {reference!r}")
        return record

    def lookup(self, reference) -> Optional[dict]:
        """Resolve canonical key, current code, or retired code.

        Returns None when unknown/inactive — callers (the resolver)
        raise the domain-typed miss. Never returns a different material
        than the reference identifies.
        """
        ref = str(reference or "").strip()
        if not ref:
            return None
        record = self._find_by_key(ref)
        if record is None:
            record = self._code_index(active_only=True).get(ref.casefold())
        elif not record.get("active", True):
            record = None
        return dict(record) if record is not None else None

    def list_materials(self, active_only: bool = True) -> List[dict]:
        """Materials in file order (seed order lives in the seed table)."""
        return [dict(record) for record in self._records
                if not active_only or record.get("active", True)]

    def _build_record(self, *, name, code, category_id, unit,
                      existing=None, exclude_key=None) -> dict:
        """Validate identifiers and assemble a schema-valid record.

        Engineering properties are written as NULL here BY CONSTRUCTION —
        there is no parameter for them, so a user material can never
        acquire density/wastage/mix data from this path.
        """
        text_name = str(name or "").strip()
        if not text_name:
            raise ValidationError("Material name must be non-empty")
        if len(text_name) > NAME_MAX:
            raise ValidationError(
                f"Material name must be <= {NAME_MAX} characters; "
                f"got {len(text_name)}")
        if self._registry is None:
            raise ValidationError(
                "UserMaterialStore requires a CategoryRegistry — material "
                "categories may never bypass the registry")
        text_unit = str(unit or "").strip()
        if text_unit not in SUPPORTED_UNITS:
            raise UnknownUnitError(f"Unknown unit: {text_unit!r}")
        current = dict(existing) if existing else {}
        text_code = self._check_code(
            code, exclude_key=exclude_key or current.get("key"))
        resolved = self._registry.resolve_category(category_id)
        record = {
            "key": current.get("key") or self._new_key(),
            "code": text_code,
            "name": text_name,
            "category": str(resolved.category_id),
            "unit": text_unit,
            "density": current.get("density"),
            "density_unit": current.get("density_unit", _DENSITY_UNIT),
            "default_wastage_pct": current.get("default_wastage_pct"),
            "source": current.get("source", USER_SOURCE),
            "version": current.get("version", _RECORD_VERSION),
            "effective_date": (current.get("effective_date")
                               or date.today().isoformat()),
            "verification_status": current.get(
                "verification_status",
                VerificationStatus.NEEDS_VERIFICATION),
            "active": current.get("active", True),
            "aliases": list(current.get("aliases") or []),
        }
        previous_code = str(current.get("code", "") or "")
        if previous_code and previous_code != text_code:
            # Renaming retires the old code so earlier references keep
            # resolving to THIS material; round-tripping a rename back
            # keeps both entries listed (never a different material).
            record["aliases"].append(previous_code)
        return self.validate_material(record)

    def create_material(self, *, name, code, category_id, unit) -> dict:
        """Create and persist a user material; returns its record."""
        record = self._build_record(
            name=name, code=code, category_id=category_id, unit=unit)
        self._records.append(record)
        try:
            self._persist()
        except Exception:
            self._records.pop()
            raise
        return dict(record)

    def add_material(self, dto) -> dict:
        """Create a user material from a plain DTO mapping (Phase 5).

        The routing target for every new material: the Add Material
        dialog and seed-customization ("Create User Override") flow
        both land here. The DTO carries identifiers only (``name``,
        ``code``, ``category_id``, ``unit``) — there is deliberately no
        engineering-property key, mirroring :meth:`create_material`.
        """
        if not isinstance(dto, Mapping):
            raise ValidationError(
                "User material DTO must be a mapping of identifier fields")
        return self.create_material(
            name=dto.get("name"),
            code=dto.get("code"),
            category_id=(dto.get("category_id") or dto.get("category")),
            unit=dto.get("unit"))

    def update_material(self, key, updated_dto=None, *, name=None,
                        code=None, category_id=None, unit=None) -> dict:
        """Update identifying fields; the canonical key never changes.

        Accepts the material reference as canonical key OR current code
        and an optional plain DTO mapping (``name`` / ``code`` /
        ``category_id`` / ``unit``); explicit keyword arguments win
        over DTO values, and an omitted/None value keeps the current
        field. A code change keeps the previous code as an alias so
        earlier references (saved rates, .clk line refs) keep resolving
        to THIS material — never to a different one.
        """
        if updated_dto is not None and not isinstance(updated_dto, Mapping):
            raise ValidationError(
                "User material update DTO must be a mapping of identifier "
                "fields")
        current = dict(self._resolve_reference(key))
        dto = dict(updated_dto) if updated_dto else {}

        def pick(keyword_value, *dto_keys, current_value):
            if keyword_value is not None:
                return keyword_value
            for dto_key in dto_keys:
                if dto_key in dto:
                    value = dto[dto_key]
                    if value is not None:
                        return value
                    break  # explicit None keeps the current value
            return current_value

        record = self._build_record(
            name=pick(name, "name", current_value=current["name"]),
            code=pick(code, "code", current_value=current["code"]),
            category_id=pick(category_id, "category_id", "category",
                             current_value=current["category"]),
            unit=pick(unit, "unit", current_value=current["unit"]),
            existing=current, exclude_key=current["key"])
        position = next(i for i, stored in enumerate(self._records)
                        if str(stored.get("key")) == current["key"])
        snapshot = list(self._records)
        self._records[position] = record
        try:
            self._persist()
        except Exception:
            self._records = snapshot
            raise
        return dict(record)

    def deactivate_material(self, key) -> dict:
        """Soft-delete: the material leaves the effective catalogue.

        Hard deletes are deliberately not offered — a deactivated
        material simply stops resolving (fail closed); references to it
        never silently resolve to a different material.
        """
        current = dict(self._resolve_reference(key))
        updated = dict(current)
        updated["active"] = False
        position = next(i for i, stored in enumerate(self._records)
                        if str(stored.get("key")) == current["key"])
        snapshot = list(self._records)
        self._records[position] = updated
        try:
            self._persist()
        except Exception:
            self._records = snapshot
            raise
        return dict(updated)

    def reactivate_material(self, key) -> dict:
        """Undo :meth:`deactivate_material`: the material rejoins the
        catalogue and starts resolving again.

        An already-active material is returned unchanged (idempotent —
        no redundant write). The canonical key never changes.
        """
        current = dict(self._resolve_reference(key))
        if current.get("active", True):
            return current
        updated = dict(current)
        updated["active"] = True
        position = next(i for i, stored in enumerate(self._records)
                        if str(stored.get("key")) == current["key"])
        snapshot = list(self._records)
        self._records[position] = updated
        try:
            self._persist()
        except Exception:
            self._records = snapshot
            raise
        return dict(updated)

    def inactive_materials(self) -> List[dict]:
        """Soft-deleted user materials (removed catalogue rows, restorable)."""
        return [dict(record) for record in self._records
                if not record.get("active", True)]

    def hidden_seed_keys(self) -> List[str]:
        """Shipped keys the operator removed from the catalogue view."""
        return list(self._hidden_seed)

    def hide_seed_material(self, key) -> List[str]:
        """Remove a SHIPPED material from the catalogue view (reversible).

        A user-side overlay only: the seed table is never written and
        the resolver keeps resolving the key for existing estimates —
        only the catalogue listing (and its counts) drop the row.
        User materials leave the catalogue through
        :meth:`deactivate_material` instead, so a ``user:`` key here
        fails closed. Re-hiding an already-hidden key is a no-op.
        """
        text = str(key or "").strip()
        if not text:
            raise ValidationError("Hidden material key must be non-empty")
        if text.startswith(USER_KEY_PREFIX):
            raise ValidationError(
                f"Material {text!r} is a user material; remove it with "
                f"deactivate_material, not the seed-catalogue overlay")
        if text in self._hidden_seed:
            return list(self._hidden_seed)
        self._hidden_seed.append(text)
        try:
            self._persist()
        except Exception:
            self._hidden_seed.remove(text)
            raise
        return list(self._hidden_seed)

    def unhide_seed_material(self, key) -> List[str]:
        """Put a hidden shipped material back into the catalogue view."""
        text = str(key or "").strip()
        if text not in self._hidden_seed:
            raise ValidationError(
                f"Material {text!r} is not hidden from the catalogue")
        snapshot = list(self._hidden_seed)
        self._hidden_seed.remove(text)
        try:
            self._persist()
        except Exception:
            self._hidden_seed = snapshot
            raise
        return list(self._hidden_seed)


# ------------------------------------------------------------------ #
# Rate library (SQLite)
# ------------------------------------------------------------------ #

_RATE_LOCK = threading.Lock()


def _init_rate_library() -> None:
    """Create the rate_library.db tables if they do not exist."""
    with _RATE_LOCK:
        conn = sqlite3.connect(str(RATE_LIBRARY_PATH))
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rate_cards (
                    id TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    category TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    base_rate REAL NOT NULL DEFAULT 0.0,
                    markup_percent REAL NOT NULL DEFAULT 0.0,
                    effective_date TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'user'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rate_components (
                    id TEXT PRIMARY KEY,
                    rate_card_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    ref TEXT NOT NULL,
                    quantity REAL NOT NULL DEFAULT 1.0,
                    FOREIGN KEY (rate_card_id) REFERENCES rate_cards(id)
                )
            """)
            conn.commit()
        finally:
            conn.close()


class RateLibrary:
    """SQLite-backed rate card store for assembly rates."""

    def __init__(self):
        _ensure_data_dir()
        _init_rate_library()

    def add_rate_card(self, card_id: str, description: str,
                       category: str, unit: str,
                       base_rate: float, markup_percent: float = 0,
                       effective_date: str = "",
                       source: str = "user") -> dict:
        """Create a new rate card."""
        with _RATE_LOCK:
            conn = sqlite3.connect(str(RATE_LIBRARY_PATH))
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO rate_cards "
                    "(id, description, category, unit, base_rate, "
                    "markup_percent, effective_date, source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (card_id, description, category, unit, base_rate,
                     markup_percent, effective_date or date.today().isoformat(), source))
                conn.commit()
            finally:
                conn.close()
        return {"id": card_id, "description": description,
                "category": category, "unit": unit,
                "base_rate": base_rate, "markup_percent": markup_percent,
                "effective_date": effective_date, "source": source}

    def get_rate_card(self, card_id: str) -> Optional[dict]:
        """Retrieve one rate card by id."""
        with _RATE_LOCK:
            conn = sqlite3.connect(str(RATE_LIBRARY_PATH))
            try:
                row = conn.execute(
                    "SELECT id, description, category, unit, base_rate, "
                    "markup_percent, effective_date, source FROM rate_cards "
                    "WHERE id = ?", (card_id,)).fetchone()
            finally:
                conn.close()
        if row is None:
            return None
        return {"id": row[0], "description": row[1], "category": row[2],
                "unit": row[3], "base_rate": row[4],
                "markup_percent": row[5], "effective_date": row[6],
                "source": row[7]}

    def list_rate_cards(self) -> List[dict]:
        """All rate cards."""
        with _RATE_LOCK:
            conn = sqlite3.connect(str(RATE_LIBRARY_PATH))
            try:
                rows = conn.execute(
                    "SELECT id, description, category, unit, base_rate, "
                    "markup_percent, effective_date, source FROM rate_cards "
                    "ORDER BY category, id"
                ).fetchall()
            finally:
                conn.close()
        return [{"id": r[0], "description": r[1], "category": r[2],
                 "unit": r[3], "base_rate": r[4],
                 "markup_percent": r[5], "effective_date": r[6],
                 "source": r[7]} for r in rows]


# ------------------------------------------------------------------ #
# Backward-compatible aliases for existing resource stack
# ------------------------------------------------------------------ #

UserMaterialStore = MaterialStore


def default_materials_path() -> Path:
    """Engine-root data/user_materials.json path."""
    return USER_MATERIALS_PATH


_CODE_PATTERN_RE = __import__("re").compile(r"^[A-Za-z0-9._-]{1,64}$")


def generate_material_code(category: str, sequence: int,
                           prefix: str = "",
                           separator: str = "-") -> str:
    """Generate a material code from category + sequence.

    Uses the configured prefix and separator when available;
    falls back to category shorthand + zero-padded sequence.
    """
    if prefix:
        return f"{prefix}{separator}{str(sequence).zfill(3)}"
    shorthand = ""
    for ch in category:
        if ch.isalpha():
            shorthand += ch.upper()
    shorthand = shorthand[:3] or "GEN"
    return f"{shorthand}{separator}{str(sequence).zfill(3)}"


def validate_material_code(code: str) -> bool:
    """Validate a material code format. Returns True if valid."""
    return bool(_CODE_PATTERN_RE.match(code))


def _validate_material_code_format(code: str) -> None:
    """Validate material code format; raises ValidationError if invalid."""
    if not _CODE_PATTERN_RE.match(code):
        raise ValidationError(
            f"Material code {code!r} must be 1-64 characters "
            f"of letters, digits, '.', '-' or '_'")
