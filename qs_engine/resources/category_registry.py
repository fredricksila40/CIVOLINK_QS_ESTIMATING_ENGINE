"""Material category registry (Phase 25): seed + user categories, one lookup.

Categories presented to the user come from two sources:

* **seed** — the ``category`` values carried by the shipped materials
  table. Derived at read time; this module NEVER writes seed data.
* **user** — custom categories the operator creates, persisted in the
  writable data directory (``data/user_categories.json``).

Every category has a stable ``category_id``. Seed ids are the plain
strings used by the shipped catalogue (``binder``, ``aggregate``, …);
user ids are namespaced ``user:<slug>`` so they can never collide with
— or silently replace — a seed category. Materials resolve their
category through :meth:`CategoryRegistry.resolve_category` before they
are stored, so arbitrary category strings cannot bypass the registry.

Each category carries configurable formatting parameters (prefix, GL
account binding, format template, sequence padding, separator) that
drive the dynamic code generation engine. Seed categories inherit these
from the seed materials table; user categories may specify custom values
or inherit project defaults (None).
"""

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Mapping, Optional

from ..core.errors import ValidationError

SCHEMA_VERSION = "1.0"
USER_CATEGORY_PREFIX = "user:"
USER_SOURCE = "user"

#: Category names: human text, bounded. No empty/whitespace-only names.
NAME_MAX = 64
_SLUG_RE = re.compile(r"[^a-z0-9]+")

#: Default GL description when no account is bound.
NEEDS_VERIFICATION = "NEEDS_VERIFICATION"

#: Prefix pattern: uppercase alphanumeric only.
PREFIX_RE = re.compile(r"^[A-Z0-9]{1,8}$")

#: Separator pattern: single delimiter character.
SEPARATOR_RE = re.compile(r"^[-/._]?$")


@dataclass(frozen=True)
class CategoryRecord:
    """One category with configurable formatting parameters.

    Formatting fields (``format_template``, ``sequence_padding``,
    ``separator``) are None when the category inherits the project
    default — never hardcoded in the category itself.
    """
    category_id: str
    category_name: str
    prefix: str = ""
    sap_gl_code: str = NEEDS_VERIFICATION
    gl_description: str = NEEDS_VERIFICATION
    format_template: Optional[str] = None
    sequence_padding: Optional[int] = None
    separator: Optional[str] = None
    source: str = "seed"

    def __post_init__(self):
        object.__setattr__(self, "category_id",
                          str(self.category_id or "").strip())
        object.__setattr__(self, "category_name",
                          str(self.category_name or "").strip())
        object.__setattr__(self, "prefix",
                          str(self.prefix or "").strip().upper())
        object.__setattr__(self, "sap_gl_code",
                          str(self.sap_gl_code or "").strip())
        object.__setattr__(self, "gl_description",
                          str(self.gl_description or "").strip())
        if self.format_template is not None:
            object.__setattr__(self, "format_template",
                              str(self.format_template))
        if self.sequence_padding is not None:
            if not isinstance(self.sequence_padding, int) or self.sequence_padding < 1:
                raise ValidationError(
                    f"Category {self.category_id!r}: sequence_padding "
                    f"must be a positive integer")
            object.__setattr__(self, "sequence_padding",
                              self.sequence_padding)
        if self.separator is not None:
            sep = str(self.separator)
            if not SEPARATOR_RE.match(sep):
                raise ValidationError(
                    f"Category {self.category_id!r}: separator "
                    f"{sep!r} must be a single delimiter character "
                    f"(-, /, ., _) or empty")
            object.__setattr__(self, "separator", sep)

    def to_dict(self) -> dict:
        """Serialize to a plain dict for persistence."""
        return {
            "category_id": self.category_id,
            "category_name": self.category_name,
            "prefix": self.prefix,
            "sap_gl_code": self.sap_gl_code,
            "gl_description": self.gl_description,
            "format_template": self.format_template,
            "sequence_padding": self.sequence_padding,
            "separator": self.separator,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> "CategoryRecord":
        """Build from a plain dict (e.g., user_categories.json)."""
        return cls(
            category_id=str(data.get("category_id", "")),
            category_name=str(data.get("category_name", "")),
            prefix=str(data.get("prefix", "")),
            sap_gl_code=str(data.get("sap_gl_code", NEEDS_VERIFICATION)),
            gl_description=str(data.get("gl_description", NEEDS_VERIFICATION)),
            format_template=data.get("format_template"),
            sequence_padding=data.get("sequence_padding"),
            separator=data.get("separator"),
            source=str(data.get("source", USER_SOURCE)),
        )


def default_categories_path() -> Path:
    """Engine-root data/user_categories.json (created on first write)."""
    return (Path(__file__).resolve().parent.parent.parent
            / "data" / "user_categories.json")


def _slugify(name: str) -> str:
    """Stable slug ('Kenya Supplies' -> 'kenya-supplies')."""
    return _SLUG_RE.sub("-", str(name).casefold()).strip("-")


def _validate_name(name) -> str:
    text = str(name or "").strip()
    if not text:
        raise ValidationError("Category name must be non-empty")
    if len(text) > NAME_MAX:
        raise ValidationError(
            f"Category name must be <= {NAME_MAX} characters; "
            f"got {len(text)}")
    if not any(ch.isalnum() for ch in text):
        raise ValidationError(
            f"Category name {text!r} must contain at least one letter "
            f"or digit")
    return text


class CategoryRegistry:
    """Deterministic lookup over seed categories plus persistable user ones.

    Seed categories are derived from the read-only materials table on
    each call (sorted for determinism); user categories are loaded from
    the writable registry file. Lookup order is always seed first, then
    user — a user category can never shadow a seed category.
    """

    def __init__(self, seed_repository, categories_path=None):
        self._seed = seed_repository
        self.path = (Path(categories_path) if categories_path is not None
                     else default_categories_path())
        self._user: Dict[str, dict] = {}
        self._load()

    # -- persistence ---------------------------------------------------------

    def _load(self) -> None:
        """Load user categories; missing file = none (empty, not an error).

        Malformed or version-unknown files fail closed with a typed error
        — never a partial or half-migrated category list.
        """
        self._user = {}
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(
                f"User category registry {self.path} is unreadable: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise ValidationError(
                f"User category registry {self.path} must be a JSON object")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValidationError(
                f"User category registry {self.path} declares "
                f"schema_version {payload.get('schema_version')!r}; "
                f"this build reads {SCHEMA_VERSION!r} only")
        categories = payload.get("categories", [])
        if not isinstance(categories, list):
            raise ValidationError(
                f"User category registry {self.path}: "
                f"'categories' must be a list")
        for record in categories:
            self._user[self._validate_user_record(record)] = dict(record)

    def _validate_user_record(self, record) -> str:
        if not isinstance(record, Mapping):
            raise ValidationError(
                f"User category registry {self.path}: "
                f"category must be a mapping")
        category_id = str(record.get("category_id", "") or "")
        if not category_id.startswith(USER_CATEGORY_PREFIX):
            raise ValidationError(
                f"User category registry {self.path}: category_id "
                f"{category_id!r} must start with {USER_CATEGORY_PREFIX!r} "
                f"(user data may never claim a seed identifier)")
        _validate_name(record.get("category_name"))
        if str(record.get("source", "") or "") != USER_SOURCE:
            raise ValidationError(
                f"User category registry {self.path}: category "
                f"{category_id!r} must carry source {USER_SOURCE!r}")
        prefix = str(record.get("prefix", "") or "").strip().upper()
        if prefix and not PREFIX_RE.match(prefix):
            raise ValidationError(
                f"User category registry {self.path}: category "
                f"{category_id!r} prefix {prefix!r} must be 1-8 uppercase "
                f"alphanumeric characters")
        padding = record.get("sequence_padding")
        if padding is not None:
            if not isinstance(padding, int) or padding < 1:
                raise ValidationError(
                    f"User category registry {self.path}: category "
                    f"{category_id!r} sequence_padding must be a "
                    f"positive integer")
        separator = record.get("separator")
        if separator is not None:
            sep = str(separator)
            if not SEPARATOR_RE.match(sep):
                raise ValidationError(
                    f"User category registry {self.path}: category "
                    f"{category_id!r} separator {sep!r} must be a single "
                    f"delimiter character (-, /, ., _) or empty")
        return category_id

    def _persist(self) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "updated_on": date.today().isoformat(),
            "categories": [dict(self._user[key])
                           for key in sorted(self._user)],
        }
        # Categories now carry formatting parameters; ensure they persist.
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:
            raise ValidationError(
                f"Could not write user category registry "
                f"{self.path}: {exc}") from exc

    def reload(self) -> None:
        """Re-read the persisted registry from disk."""
        self._load()

    # -- seed side (read-only) -------------------------------------------------

    def _seed_categories(self) -> Dict[str, CategoryRecord]:
        """Seed categories derived from the read-only materials table.

        Prefix, GL code, and GL description are inherited from the
        first seed material in each category that carries them.
        """
        derived: Dict[str, CategoryRecord] = {}
        for record in self._seed.list("materials"):
            category = str(record.get("category", "") or "").strip()
            if not category or category in derived:
                continue
            prefix = str(record.get("category_prefix", "") or "").strip()
            gl_code = str(record.get("gl_code", "") or "").strip()
            gl_account = str(record.get("gl_account_name", "") or "").strip()
            gl_desc = (f"Inventory Account - {gl_account}"
                       if gl_account else NEEDS_VERIFICATION)
            derived[category] = CategoryRecord(
                category_id=category,
                category_name=category,
                prefix=prefix,
                sap_gl_code=gl_code or NEEDS_VERIFICATION,
                gl_description=gl_desc,
                source="seed",
            )
        return derived

    # -- public API ------------------------------------------------------------

    def list_categories(self) -> List[dict]:
        """All categories as CategoryRecord dicts, seed then user."""
        seed = self._seed_categories()
        rows = [seed[key].to_dict() for key in sorted(seed)]
        rows.extend(self._user[key] for key in sorted(self._user))
        return rows

    def get_category(self, category_id) -> CategoryRecord:
        """One category by stable id; raises ValidationError on a miss."""
        category_id = str(category_id or "").strip()
        seed = self._seed_categories()
        if category_id in seed:
            return seed[category_id]
        if category_id in self._user:
            return CategoryRecord.from_dict(self._user[category_id])
        raise ValidationError(
            f"Unknown material category {category_id!r}")

    def resolve_category(self, reference) -> CategoryRecord:
        """Resolve an id OR a name to a CategoryRecord.

        Deterministic: exact id match first, then case-insensitive name
        match — seed categories always win a tie, so a user category can
        never shadow (or replace) a seed one.
        """
        ref = str(reference or "").strip()
        if not ref:
            raise ValidationError("Material category must be non-empty")
        seed = self._seed_categories()
        if ref in seed:
            return seed[ref]
        if ref in self._user:
            return CategoryRecord.from_dict(self._user[ref])
        folded = ref.casefold()
        for key in sorted(seed):
            if seed[key].category_name.casefold() == folded:
                return seed[key]
        for key in sorted(self._user):
            if self._user[key].get("category_name", "").casefold() == folded:
                return CategoryRecord.from_dict(self._user[key])
        raise ValidationError(f"Unknown material category {ref!r}")

    def get_category_by_prefix(self, prefix) -> Optional[CategoryRecord]:
        """Look up a category by its uppercase prefix (unique)."""
        text = str(prefix or "").strip().upper()
        if not text:
            return None
        seed = self._seed_categories()
        for key in sorted(seed):
            if seed[key].prefix == text:
                return seed[key]
        for key in sorted(self._user):
            record = CategoryRecord.from_dict(self._user[key])
            if record.prefix == text:
                return record
        return None

    def add_custom_category(self, name, *, prefix="",
                            sap_gl_code="", gl_description="",
                            format_template=None, sequence_padding=None,
                            separator=None) -> dict:
        """Create and persist a user category; returns its record dict.

        Rejects empty names, names that would shadow a seed category
        (same name or same slug), duplicate user categories, and
        duplicate prefixes — deterministically, with a typed error.
        Formatting parameters are optional; None inherits project default.
        """
        text = _validate_name(name)
        seed = self._seed_categories()
        slug = _slugify(text)
        for key in sorted(seed):
            seed_name = seed[key].category_name
            if (text.casefold() == seed_name.casefold()
                    or slug == seed[key].category_id):
                raise ValidationError(
                    f"Category {text!r} would shadow seed category "
                    f"{seed_name!r}; choose a different name (seed "
                    f"categories cannot be replaced by user data)")
        for key in sorted(self._user):
            if (self._user[key].get("category_name", "").casefold()
                    == text.casefold()):
                raise ValidationError(
                    f"Category {text!r} already exists in the user registry")
        prefix_clean = str(prefix or "").strip().upper()
        if prefix_clean:
            if not PREFIX_RE.match(prefix_clean):
                raise ValidationError(
                    f"Category prefix {prefix_clean!r} must be 1-8 "
                    f"uppercase alphanumeric characters")
            existing = self.get_category_by_prefix(prefix_clean)
            if existing is not None:
                raise ValidationError(
                    f"Category prefix {prefix_clean!r} is already used by "
                    f"category {existing.category_id!r}")
        category_id = f"{USER_CATEGORY_PREFIX}{slug}"
        suffix = 2
        while category_id in self._user or category_id in seed:
            category_id = f"{USER_CATEGORY_PREFIX}{slug}-{suffix}"
            suffix += 1
        record = CategoryRecord(
            category_id=category_id,
            category_name=text,
            prefix=prefix_clean,
            sap_gl_code=str(sap_gl_code or "").strip() or NEEDS_VERIFICATION,
            gl_description=(str(gl_description or "").strip()
                            or NEEDS_VERIFICATION),
            format_template=format_template,
            sequence_padding=sequence_padding,
            separator=separator,
            source=USER_SOURCE,
        )
        self._user[category_id] = record.to_dict()
        try:
            self._persist()
        except ValidationError:
            self._user.pop(category_id, None)
            raise
        return record.to_dict()

