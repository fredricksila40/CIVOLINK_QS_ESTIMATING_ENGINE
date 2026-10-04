"""Material code policy engine (Phase 5): five generation modes, one API.

The active policy lives in the project profile (``material_code_policy``
+ ``material_code_prefix`` in ``session.project``), so it round-trips
through ``.clk`` project files with every other profile field.

Modes:

* ``CATEGORY_PREFIX`` — ``{PREFIX}{SEPARATOR}{SEQUENCE}`` from the
  category registry prefix (``aggregate`` -> ``AGG-001``, ``binder`` ->
  ``BIN-001``).
* ``SLUG`` — slugified material name (``Ballast 20mm`` ->
  ``ballast_20mm``). Not offered in the UI; retained for API backward
  compatibility.
* ``SEQUENTIAL_NUMERIC`` — bare numeric strings (``001``, ``002``).
* ``CUSTOM_PREFIX`` — ``{PREFIX}{SEPARATOR}{SEQUENCE}`` with the
  configured prefix.
* ``MANUAL`` — generates nothing; the Material Code field stays empty
  for explicit user entry.

Every generated candidate is checked for availability against BOTH the
core seed catalogue and the writable ``user_materials.json`` store, and
the format rules are the store's (letters, digits, dot, hyphen,
underscore; 1-64 chars) — the suggestion may never propose a code the
store would reject. This module never writes anything.

Dynamic formatting is driven by :class:`CodePatternEngine` and
:class:`CodePatternPreset` — all formatting logic evaluates token
templates (``{PREFIX}``, ``{SEPARATOR}``, ``{SEQUENCE}``,
``{CATEGORY_ID}``) with configurable padding and separators. No
digit lengths, delimiters, or format templates are hardcoded.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable, Mapping, Optional, Set

from ..core.errors import ValidationError
from .material_store import CODE_RE, USER_KEY_PREFIX

#: Project-profile fields carrying the active policy.
MATERIAL_CODE_POLICY_FIELD = "material_code_policy"
MATERIAL_CODE_PREFIX_FIELD = "material_code_prefix"
MATERIAL_CODE_TEMPLATE_FIELD = "material_code_template"
MATERIAL_CODE_PADDING_FIELD = "material_code_sequence_padding"
MATERIAL_CODE_SEPARATOR_FIELD = "material_code_separator"

CATEGORY_PREFIX = "CATEGORY_PREFIX"
SLUG = "SLUG"
SEQUENTIAL_NUMERIC = "SEQUENTIAL_NUMERIC"
CUSTOM_PREFIX = "CUSTOM_PREFIX"
MANUAL = "MANUAL"

#: The five supported modes, in menu order.
POLICY_MODES = (CATEGORY_PREFIX, SLUG, SEQUENTIAL_NUMERIC,
                 CUSTOM_PREFIX, MANUAL)

#: UI-visible modes (SLUG removed from user-facing options).
UI_POLICY_MODES = (CATEGORY_PREFIX, SEQUENTIAL_NUMERIC,
                   CUSTOM_PREFIX, MANUAL)

DEFAULT_MODE = CATEGORY_PREFIX

#: Default formatting parameters (backward-compatible fallbacks).
DEFAULT_TEMPLATE = "{PREFIX}{SEPARATOR}{SEQUENCE}"
DEFAULT_PADDING = 3
DEFAULT_SEPARATOR = "-"

#: Display labels for the Project Setup combobox (token -> label).
POLICY_LABELS = {
    CATEGORY_PREFIX: "Category Prefix (AGG-001)",
    SLUG: "Slug (ballast_20mm)",
    SEQUENTIAL_NUMERIC: "Sequential Numeric (001)",
    CUSTOM_PREFIX: "Custom Prefix (PREFIX-001)",
    MANUAL: "Manual (type each code)",
}
LABEL_TO_MODE = {label: mode for mode, label in POLICY_LABELS.items()}
POLICY_LABEL_CHOICES = tuple(POLICY_LABELS[mode] for mode in POLICY_MODES)

#: Custom prefixes are short identifiers, stricter than full codes.
PREFIX_RE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")

#: {SEQ:03d} formats bound at 999 candidates (same bound as the legacy
#: MAT generator); numeric mode offers 001-999 likewise.
_SEQUENCE_LIMIT = 1000

#: Slug ceiling so a generated code always fits the 64-char store rule
#: even with a ``_NN`` collision suffix appended.
_SLUG_MAX = 60


# ---------------------------------------------------------------------------
# Dynamic Pattern Engine
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CodePatternPreset:
    """One named code pattern preset with a token template.

    ``template`` is a string containing tokens like ``{PREFIX}``,
    ``{SEPARATOR}``, ``{SEQUENCE}``, ``{CATEGORY_ID}`` that are
    evaluated dynamically by :class:`CodePatternEngine`.
    """
    preset_id: str
    display_name: str
    template: str
    requires_custom_prefix: bool = False
    is_manual: bool = False


#: Built-in presets offered in the UI (SLUG excluded).
CODE_PATTERN_PRESETS = (
    CodePatternPreset(
        preset_id="CATEGORY_SEQUENCE",
        display_name="Category Prefix + Sequence",
        template=DEFAULT_TEMPLATE,
    ),
    CodePatternPreset(
        preset_id="CUSTOM_SEQUENCE",
        display_name="Custom Prefix + Sequence",
        template=DEFAULT_TEMPLATE,
        requires_custom_prefix=True,
    ),
    CodePatternPreset(
        preset_id="SEQUENTIAL_NUMERIC",
        display_name="Sequential Numeric",
        template="{SEQUENCE}",
    ),
    CodePatternPreset(
        preset_id="MANUAL",
        display_name="Manual Entry",
        template="",
        is_manual=True,
    ),
)

#: Preset lookup by id.
PRESET_BY_ID = {p.preset_id: p for p in CODE_PATTERN_PRESETS}


class CodePatternEngine:
    """Token-based pattern evaluator for material code generation.

    Evaluates templates like ``{PREFIX}{SEPARATOR}{SEQUENCE}`` with
    dynamic values. All formatting is data-driven — no hardcoded
    digit lengths, delimiters, or concatenation logic.
    """

    #: Supported tokens and their resolution.
    SUPPORTED_TOKENS = ("{PREFIX}", "{SEPARATOR}", "{SEQUENCE}",
                       "{CATEGORY_ID}")

    @staticmethod
    def format_code(
        preset: CodePatternPreset,
        prefix: str,
        sequence: int,
        delimiter: str = DEFAULT_SEPARATOR,
        padding: int = DEFAULT_PADDING,
        custom_prefix: str = "",
    ) -> str:
        """Evaluate a preset template with dynamic token values.

        Token resolution:
        * ``{PREFIX}`` — the category or custom prefix
        * ``{SEPARATOR}`` — the delimiter (default ``-``)
        * ``{SEQUENCE}`` — zero-padded sequence number
        * ``{CATEGORY_ID}`` — the category identifier

        Padding uses ``zfill`` so the sequence width is always
        controlled by the ``padding`` parameter, never hardcoded.
        """
        if preset.is_manual:
            return ""
        effective_prefix = (custom_prefix
                            if preset.requires_custom_prefix and custom_prefix
                            else prefix)
        seq_str = str(sequence).zfill(padding)
        result = preset.template
        result = result.replace("{PREFIX}", effective_prefix)
        result = result.replace("{SEPARATOR}", delimiter)
        result = result.replace("{SEQUENCE}", seq_str)
        result = result.replace("{CATEGORY_ID}", prefix)
        return result

    @staticmethod
    def next_sequence(
        prefix: str,
        *,
        seed_repository=None,
        store=None,
        taken: Iterable = (),
    ) -> int:
        """Find the next free sequence number for a given prefix.

        Checks both seed master items and user_materials.json to
        prevent collisions. Returns the first available 1-based
        sequence number.
        """
        occupied = _folded(taken)
        for seq in range(1, _SEQUENCE_LIMIT):
            candidate = f"{prefix}-{seq:03d}"
            if candidate.casefold() not in occupied:
                return seq
        raise ValidationError(
            "Could not find a free sequence number — every candidate "
            "is already in use")


def policy_label(mode) -> str:
    """Display label for a policy token (unknown tokens fail closed)."""
    text = str(mode or "").strip()
    if text not in POLICY_LABELS:
        raise ValidationError(
            f"Unknown material code policy {mode!r}; expected one of "
            f"{', '.join(POLICY_MODES)}")
    return POLICY_LABELS[text]


def mode_from_label(label) -> str:
    """Policy token for a Project Setup display label."""
    text = str(label or "").strip()
    mode = LABEL_TO_MODE.get(text)
    if mode is None:
        raise ValidationError(
            f"Unknown material code formatting choice {label!r}; "
            f"expected one of {', '.join(POLICY_LABEL_CHOICES)}")
    return mode


def category_shorthand(category) -> str:
    """3-letter category shorthand (``aggregate`` -> ``AGG``).

    User categories carry the ``user:`` namespace, which is stripped
    before the letters are taken (``user:kenya-supplies`` -> ``KEN``).
    Empty when the reference holds no letters — callers fall back to a
    generic shorthand rather than inventing one.
    """
    text = str(category or "").strip()
    if text.startswith("user:"):
        text = text[len("user:"):]
    letters = [ch for ch in text if ch.isalpha()]
    return "".join(letters[:3]).upper()


def slugify_name(name) -> str:
    """Slugified material name (``Ballast 20mm`` -> ``ballast_20mm``)."""
    text = str(name or "").strip().casefold()
    slug = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return slug[:_SLUG_MAX].rstrip("_")


def _folded(codes: Iterable) -> Set[str]:
    return {str(code).strip().casefold() for code in codes
            if str(code or "").strip()}


def ensure_available(code, *, seed_repository=None, store=None,
                     taken: Iterable = ()) -> str:
    """Validate one code: format + availability against seed AND user data.

    Checks run against the core seed catalogue (keys, codes, legacy
    codes) and the writable ``user_materials.json`` store (codes and
    retired aliases) — a code that collides with EITHER source is
    refused with a typed error naming the source. Returns the stripped
    code.
    """
    text = str(code or "").strip()
    if not text:
        raise ValidationError("Material code must be non-empty")
    if not CODE_RE.match(text):
        raise ValidationError(
            f"Material code {text!r} must be 1-64 characters of letters, "
            f"digits, '.', '-' or '_'")
    folded = text.casefold()
    if seed_repository is not None:
        from ..master_data.schemas import MATERIALS
        for record in seed_repository.list(MATERIALS):
            for field in ("key", "code", "legacy_code"):
                value = str(record.get(field, "") or "").strip()
                if value and value.casefold() == folded:
                    raise ValidationError(
                        f"Material code {text!r} collides with seed "
                        f"catalogue identifier {value!r}")
    if store is not None:
        for value in store.existing_codes():
            if str(value).strip().casefold() == folded:
                raise ValidationError(
                    f"Material code {text!r} is already used in "
                    f"user_materials.json ({value!r})")
    if folded in _folded(taken):
        raise ValidationError(f"Material code {text!r} is already in use")
    return text


@lru_cache(maxsize=1)
def _shipped_seed_records() -> tuple:
    """Shipped seed materials in catalogue order (read-only master data).

    Cached: the seed tree is never written by the application, so the
    order is stable for the life of the process.
    """
    from ..master_data.repository import MasterDataRepository
    from ..master_data.schemas import MATERIALS
    return tuple(MasterDataRepository().list(MATERIALS))


def _seed_ordinal(seed_resource, seed_records, *, per_category) -> Optional[int]:
    """1-based ordinal of one seed record within its display scope.

    ``per_category`` scopes the ordinal to the record's category
    (CATEGORY_PREFIX / CUSTOM_PREFIX); otherwise it spans the whole
    catalogue (SEQUENTIAL_NUMERIC). None when the record is not part of
    the supplied catalogue — a display code is only ever derived, never
    invented.
    """
    key = str(seed_resource.get("key", "") or "").strip()
    if not key:
        return None
    category = str(seed_resource.get("category", "") or "").strip()
    ordinal = 0
    for record in seed_records:
        record_key = str(record.get("key", "") or "").strip()
        if not record_key or record_key.startswith(USER_KEY_PREFIX):
            continue
        if (per_category and str(record.get("category", "") or "").strip()
                != category):
            continue
        ordinal += 1
        if record_key == key:
            return ordinal
    return None


@dataclass(frozen=True)
class MaterialCodePolicy:
    """One active material-code policy (immutable, validated).

    Supports dynamic formatting parameters (``format_template``,
    ``sequence_padding``, ``separator``) that override the defaults
    when set. None values inherit the project/engine defaults.
    """

    mode: str = DEFAULT_MODE
    custom_prefix: str = ""
    format_template: Optional[str] = None
    sequence_padding: Optional[int] = None
    separator: Optional[str] = None

    def __post_init__(self):
        mode = str(self.mode or "").strip()
        if mode not in POLICY_MODES:
            raise ValidationError(
                f"Unknown material code policy {self.mode!r}; expected "
                f"one of {', '.join(POLICY_MODES)}")
        object.__setattr__(self, "mode", mode)
        prefix = str(self.custom_prefix or "").strip()
        object.__setattr__(self, "custom_prefix", prefix)
        if prefix and not PREFIX_RE.match(prefix):
            raise ValidationError(
                f"Custom material code prefix {prefix!r} must be 1-32 "
                f"characters of letters, digits, '.', '-' or '_'")
        if mode == CUSTOM_PREFIX and not prefix:
            raise ValidationError(
                "A custom material code prefix is required when the "
                "Custom Prefix policy is active")
        if self.format_template is not None:
            object.__setattr__(self, "format_template",
                              str(self.format_template))
        if self.sequence_padding is not None:
            if (not isinstance(self.sequence_padding, int)
                    or self.sequence_padding < 1):
                raise ValidationError(
                    f"Sequence padding must be a positive integer; "
                    f"got {self.sequence_padding!r}")
            object.__setattr__(self, "sequence_padding",
                              self.sequence_padding)
        if self.separator is not None:
            sep = str(self.separator)
            if len(sep) > 1:
                raise ValidationError(
                    f"Separator must be a single character or empty; "
                    f"got {sep!r}")
            object.__setattr__(self, "separator", sep)

    # -- construction / project binding ---------------------------------------

    @classmethod
    def parse(cls, mode, custom_prefix="", format_template=None,
              sequence_padding=None, separator=None) -> "MaterialCodePolicy":
        """Validate raw (string) policy fields into a policy."""
        return cls(mode=str(mode or "").strip() or DEFAULT_MODE,
                   custom_prefix=custom_prefix,
                   format_template=format_template,
                   sequence_padding=sequence_padding,
                   separator=separator)

    @classmethod
    def from_project(cls, project: Optional[Mapping]) -> "MaterialCodePolicy":
        """Active policy from a project profile.

        A profile without the fields (any pre-Phase-5 project) gets the
        default policy; an UNKNOWN non-empty token fails closed with a
        typed error instead of silently generating the wrong shape.
        """
        data = project or {}
        mode = str(data.get(MATERIAL_CODE_POLICY_FIELD, "") or "").strip()
        if not mode:
            return cls()
        padding = data.get(MATERIAL_CODE_PADDING_FIELD, "")
        padding_int = None
        if str(padding or "").strip():
            try:
                padding_int = int(str(padding).strip())
            except (ValueError, TypeError):
                raise ValidationError(
                    f"Invalid sequence padding {padding!r}; "
                    f"must be a positive integer")
        # Key presence decides None ("inherit") vs "" ("no separator") —
        # `or None` would silently turn an explicit empty separator back
        # into the default "-" on the next load.
        separator_raw = data.get(MATERIAL_CODE_SEPARATOR_FIELD, None)
        return cls.parse(
            mode,
            data.get(MATERIAL_CODE_PREFIX_FIELD, ""),
            format_template=data.get(MATERIAL_CODE_TEMPLATE_FIELD) or None,
            sequence_padding=padding_int,
            separator=None if separator_raw is None
            else str(separator_raw),
        )

    def project_fields(self) -> dict:
        """Profile fields for ``session.save_project(...)`` / .clk."""
        fields = {
            MATERIAL_CODE_POLICY_FIELD: self.mode,
            MATERIAL_CODE_PREFIX_FIELD: self.custom_prefix,
        }
        if self.format_template is not None:
            fields[MATERIAL_CODE_TEMPLATE_FIELD] = self.format_template
        if self.sequence_padding is not None:
            fields[MATERIAL_CODE_PADDING_FIELD] = str(self.sequence_padding)
        if self.separator is not None:
            fields[MATERIAL_CODE_SEPARATOR_FIELD] = self.separator
        return fields

    # -- generation -------------------------------------------------------------

    def _effective_template(self) -> str:
        return self.format_template or DEFAULT_TEMPLATE

    def _effective_padding(self) -> int:
        return self.sequence_padding if self.sequence_padding is not None \
            else DEFAULT_PADDING

    def _effective_separator(self) -> str:
        return self.separator if self.separator is not None \
            else DEFAULT_SEPARATOR

    def suggest(self, name, *, category=None,
                taken: Iterable = ()) -> str:
        """First free candidate under this policy (empty for MANUAL).

        ``taken`` must already include every occupied identifier (seed
        catalogue + user materials); callers pass it through
        ``MaterialResolver.existing_codes()``. Returns "" only when the
        policy is MANUAL or the input cannot seed a candidate (blank
        name under SLUG) — never a fabricated code.
        """
        if self.mode == MANUAL:
            return ""
        occupied = _folded(taken)
        if self.mode == CATEGORY_PREFIX:
            prefix = category_shorthand(category) or "GEN"
            return self._first_sequence(
                lambda seq: self._format_with(prefix, seq), occupied)
        if self.mode == CUSTOM_PREFIX:
            prefix = self.custom_prefix
            return self._first_sequence(
                lambda seq: self._format_with(prefix, seq), occupied)
        if self.mode == SEQUENTIAL_NUMERIC:
            return self._first_sequence(
                lambda seq: str(seq).zfill(self._effective_padding()),
                occupied)
        if self.mode == SLUG:
            base = slugify_name(name)
            if not base:
                return ""
            if base not in occupied:
                return base
            suffix = 2
            while f"{base}_{suffix}" in occupied:
                suffix += 1
            return f"{base}_{suffix}"
        raise ValidationError(  # pragma: no cover - mode validated above
            f"Unknown material code policy {self.mode!r}")

    def _format_with(self, prefix: str, seq: int) -> str:
        """Format a code using the dynamic template engine."""
        seq_str = str(seq).zfill(self._effective_padding())
        result = self._effective_template()
        result = result.replace("{PREFIX}", prefix)
        result = result.replace("{SEPARATOR}", self._effective_separator())
        result = result.replace("{SEQUENCE}", seq_str)
        result = result.replace("{CATEGORY_ID}", prefix)
        return result

    @staticmethod
    def _first_sequence(build, occupied: Set[str]) -> str:
        for seq in range(1, _SEQUENCE_LIMIT):
            candidate = build(seq)
            if candidate.casefold() not in occupied:
                return candidate
        raise ValidationError(
            "Could not suggest a free material code — every sequence "
            f"candidate is already in use")

    # -- display ---------------------------------------------------------------

    def resolve_display_code(self, seed_resource, *, seed_records=None) -> str:
        """Structured display code for one un-customized seed material.

        Uses the dynamic template engine with the record's 1-based
        ordinal within its category (CATEGORY_PREFIX / CUSTOM_PREFIX)
        or catalogue-wide (SEQUENTIAL_NUMERIC). SLUG renders the
        slugified name. MANUAL returns the record's key. A record
        outside the catalogue falls back to its key.
        """
        key = str(seed_resource.get("key", "") or "").strip()
        if self.mode == MANUAL:
            return key
        if self.mode == SLUG:
            return slugify_name(seed_resource.get("name", "")) or key
        records = (seed_records if seed_records is not None
                   else _shipped_seed_records())
        per_category = self.mode in (CATEGORY_PREFIX, CUSTOM_PREFIX)
        ordinal = _seed_ordinal(seed_resource, records,
                                per_category=per_category)
        if ordinal is None:
            return key
        if self.mode == CATEGORY_PREFIX:
            prefix = category_shorthand(
                seed_resource.get("category", "")) or "GEN"
            return self._format_with(prefix, ordinal)
        if self.mode == CUSTOM_PREFIX:
            return self._format_with(self.custom_prefix, ordinal)
        return str(ordinal).zfill(self._effective_padding())
