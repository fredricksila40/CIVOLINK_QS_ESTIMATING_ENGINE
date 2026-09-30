"""User material/category configuration layer (Phase 25).

One coherent stack between configuration and the calculation engine::

    seed master data (read-only)
          + category registry (seed + user categories)
          + user material override store (writable, versioned)
          -> MaterialResolver
          -> EffectiveMaterial
          -> existing calculation engines (unchanged)

Invariants this package exists to keep:

* Seed tables under ``qs_engine/master_data/tables/`` are NEVER written
  by application operation — the seed architecture stays read-only.
* User materials carry identifiers ONLY (name, code, category, default
  unit). They never acquire density, mix ratios, strength, coverage,
  wastage or labour factors: those stay NULL with
  ``verification_status = NEEDS_VERIFICATION`` so every downstream
  calculation fails closed exactly as it does for an unverified seed
  record. No value is ever fabricated.
* The canonical engine key (``user:<stable-id>``) is generated once and
  never changes; the user-editable material code is display/lookup data,
  not identity.
* Writable files live in the application's writable data directory
  (beside the SQLite rate library): ``data/user_materials.json`` and
  ``data/user_categories.json`` — never inside bundled resources.
"""

from dataclasses import dataclass

from ..core.errors import QSEngineError
from ..master_data.repository import MasterDataRepository
from .category_registry import (
    CategoryRecord,
    CategoryRegistry,
    default_categories_path,
    NEEDS_VERIFICATION,
)
from .code_policy import (
    CODE_PATTERN_PRESETS,
    DEFAULT_MODE,
    DEFAULT_PADDING,
    DEFAULT_SEPARATOR,
    DEFAULT_TEMPLATE,
    MATERIAL_CODE_PREFIX_FIELD,
    MATERIAL_CODE_POLICY_FIELD,
    MATERIAL_CODE_TEMPLATE_FIELD,
    MATERIAL_CODE_PADDING_FIELD,
    MATERIAL_CODE_SEPARATOR_FIELD,
    POLICY_LABELS,
    POLICY_LABEL_CHOICES,
    POLICY_MODES,
    PRESET_BY_ID,
    UI_POLICY_MODES,
    CodePatternEngine,
    CodePatternPreset,
    MaterialCodePolicy,
    mode_from_label,
    policy_label,
)
from .material_resolver import EffectiveMaterial, MaterialResolver
from .material_store import (
    RateLibrary,
    UserMaterialStore,
    default_materials_path,
    generate_material_code,
    validate_material_code,
)

__all__ = [
    "CODE_PATTERN_PRESETS",
    "CategoryRegistry",
    "CategoryRecord",
    "CodePatternEngine",
    "CodePatternPreset",
    "DEFAULT_MODE",
    "DEFAULT_PADDING",
    "DEFAULT_SEPARATOR",
    "DEFAULT_TEMPLATE",
    "EffectiveMaterial",
    "MATERIAL_CODE_PREFIX_FIELD",
    "MATERIAL_CODE_POLICY_FIELD",
    "MATERIAL_CODE_TEMPLATE_FIELD",
    "MATERIAL_CODE_PADDING_FIELD",
    "MATERIAL_CODE_SEPARATOR_FIELD",
    "MaterialCodePolicy",
    "MaterialResolver",
    "MaterialStack",
    "NEEDS_VERIFICATION",
    "POLICY_LABELS",
    "POLICY_LABEL_CHOICES",
    "POLICY_MODES",
    "PRESET_BY_ID",
    "UI_POLICY_MODES",
    "RateLibrary",
    "UserMaterialStore",
    "build_material_stack",
    "default_categories_path",
    "default_materials_path",
    "default_repository",
    "generate_material_code",
    "mode_from_label",
    "policy_label",
    "validate_material_code",
]


@dataclass(frozen=True)
class MaterialStack:
    """Fully wired Phase 25 stack: resolver + its collaborators."""
    resolver: MaterialResolver
    store: UserMaterialStore
    registry: CategoryRegistry


def build_material_stack(seed_repository=None, data_dir=None) -> MaterialStack:
    """Wire registry -> store -> resolver over a seed repository.

    ``seed_repository`` defaults to the shipped ``MasterDataRepository``
    (read-only in practice — this package never writes to it).
    ``data_dir`` overrides the writable location (tests use tmp paths);
    by default it is the engine-root ``data/`` directory beside
    ``rate_library.db``.

    Load order matters: the registry owns category persistence, the
    store validates every material's category through the registry, and
    the resolver merges both over seed without mutating either source.
    """
    from pathlib import Path

    seed = seed_repository if seed_repository is not None \
        else MasterDataRepository()
    if data_dir is None:
        base = default_materials_path().parent
    else:
        base = Path(data_dir)
    registry = CategoryRegistry(seed, base / default_categories_path().name)
    store = UserMaterialStore(base / default_materials_path().name, registry)
    resolver = MaterialResolver(seed, store, registry)
    return MaterialStack(resolver=resolver, store=store, registry=registry)


def default_repository(seed_repository=None):
    """Primary material lookup boundary for every consumer.

    One factory behind both the UI shell and the HTTP API so
    ``MaterialResolver`` is THE interface through which user material
    overrides and material record lookup flow — controllers never wire
    the store themselves.

    Returns ``(repository, stack, error)``:

    * ``repository`` — the resolver (a drop-in ``MasterDataRepository``);
      on unreadable user data it falls back to the seed-only catalogue
      (fail closed — never a partial or fabricated view).
    * ``stack`` — the full MaterialStack for UI consumers needing the
      store/registry, or None on fallback.
    * ``error`` — the fail-closed reason (None when healthy), surfaced
      by the UI status path instead of being swallowed.
    """
    seed = seed_repository if seed_repository is not None \
        else MasterDataRepository()
    try:
        stack = build_material_stack(seed)
    except QSEngineError as exc:
        return seed, None, str(exc)
    return stack.resolver, stack, None
