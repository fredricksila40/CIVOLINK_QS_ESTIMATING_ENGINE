"""Material resolver (Phase 25): the single resolution boundary.

Configuration (seed master data + user override store + category
registry) meets the calculation engine here::

    SeedRepository
          + UserMaterialRepository
          + MaterialResolver
          -> EffectiveMaterial

``MaterialResolver`` is a DROP-IN for ``MasterDataRepository``: it
implements the same ``domains() / table_version() / list() / get()``
protocol, so every existing engine function that receives a
``repository`` argument keeps working unchanged — no scattered
``if user_material:`` logic anywhere in the calculation code.

Resolution rules (fail closed, never substitute):

* Seed first, exactly as before — existing seed materials resolve
  identically whether or not a user store is attached.
* Then the user store (canonical key, current code, or retired alias).
* A miss raises the same ``UnknownMasterDataKeyError`` the seed
  repository raises — the engine cannot tell the difference, and will
  never silently price a different material.
"""

from dataclasses import dataclass
from typing import List, Mapping, Optional

from ..core.assumptions import VerificationStatus
from ..core.errors import UnknownMasterDataKeyError
from ..master_data.schemas import MATERIALS
from .material_store import USER_KEY_PREFIX, UserMaterialStore


@dataclass(frozen=True)
class EffectiveMaterial:
    """One resolved material with its provenance, ready for consumers.

    ``record`` is the plain mapping the calculation engines already
    consume (via ``repository.get``); the typed fields are the stable
    view configuration/UI code uses. ``source`` is the provenance class
    ("seed" / "user") — distinct from the record's free-text ``source``
    string, which is preserved untouched on seed records.
    """

    key: str
    code: str
    name: str
    category_id: str
    default_unit: str
    source: str
    record: Mapping

    @property
    def is_user(self) -> bool:
        return self.source == "user"

    @property
    def needs_verification(self) -> bool:
        return str(self.record.get("verification_status", "")) == (
            VerificationStatus.NEEDS_VERIFICATION)


class MaterialResolver:
    """Drop-in repository: seed (read-only) + user overrides, one lookup.

    Attach this wherever a ``repository`` is consumed (UI shell, rate
    builder, finishes resolvers). Seed behaviour is byte-for-byte the
    same as passing the seed repository directly; user materials appear
    only through this boundary.
    """

    def __init__(self, seed_repository, user_store: Optional[UserMaterialStore] = None,
                 category_registry=None):
        self._seed = seed_repository
        self._store = user_store
        self._registry = category_registry

    # -- collaborators (for UI/config consumers) -------------------------------

    @property
    def seed(self):
        return self._seed

    @property
    def store(self) -> Optional[UserMaterialStore]:
        return self._store

    @property
    def registry(self):
        return self._registry

    # -- MasterDataRepository protocol (drop-in) --------------------------------

    def domains(self) -> List[str]:
        return self._seed.domains()

    def table_version(self, domain: str) -> str:
        """Seed table version — unchanged by user data (provenance pin)."""
        return self._seed.table_version(domain)

    def list(self, domain: str) -> List[Mapping]:
        rows = list(self._seed.list(domain))
        if domain == MATERIALS and self._store is not None:
            rows.extend(self._store.list_materials())
        return rows

    def get(self, domain: str, key: str) -> Mapping:
        """Resolve one record; seed first, then user store, else typed miss."""
        if domain != MATERIALS:
            return self._seed.get(domain, key)
        try:
            return self._seed.get(domain, key)
        except UnknownMasterDataKeyError:
            pass
        if self._store is not None:
            record = self._store.lookup(key)
            if record is not None:
                return record
        raise UnknownMasterDataKeyError(
            f"Unknown material {key!r} (not in the seed catalogue and "
            f"not in the user override store)")

    # -- typed boundary ----------------------------------------------------------

    def resolve_effective(self, key) -> EffectiveMaterial:
        """Resolve a material reference to the typed EffectiveMaterial view."""
        record = self.get(MATERIALS, key)
        canonical = str(record.get("key", "") or "")
        is_user = canonical.startswith(USER_KEY_PREFIX)
        return EffectiveMaterial(
            key=canonical,
            code=str(record.get("code", "") or canonical),
            name=str(record.get("name", "") or canonical),
            category_id=str(record.get("category", "") or ""),
            default_unit=str(record.get("unit", "") or ""),
            source="user" if is_user else "seed",
            record=record,
        )

    # -- material code policy boundary (Phase 5) --------------------------------

    def existing_codes(self) -> List[str]:
        """Every material identifier in play, seed and user.

        Seed keys, codes and legacy codes plus the user store's codes
        and retired aliases — the one taken-set the code policy needs
        so a suggestion can never collide with either source.
        """
        codes: List[str] = []
        for record in self._seed.list(MATERIALS):
            for field in ("key", "code", "legacy_code"):
                value = str(record.get(field, "") or "").strip()
                if value:
                    codes.append(value)
        if self._store is not None:
            codes.extend(self._store.existing_codes())
        return codes

    def code_is_available(self, code) -> bool:
        """True when the code is free against seed AND user sources."""
        text = str(code or "").strip()
        if not text:
            return False
        folded = text.casefold()
        return not any(folded == str(other).strip().casefold()
                       for other in self.existing_codes())

    def ensure_code_available(self, code) -> str:
        """Validate format + availability against both sources (typed)."""
        from .code_policy import ensure_available
        return ensure_available(code, seed_repository=self._seed,
                                store=self._store)

    def suggest_code(self, name, category=None, policy=None) -> str:
        """Free code under the active policy against both sources.

        ``policy`` is a MaterialCodePolicy, a project-profile mapping,
        or None (default policy). Empty only for the MANUAL policy or
        an input that cannot seed a candidate — never fabricated.
        """
        from .code_policy import MaterialCodePolicy
        if policy is None:
            active = MaterialCodePolicy()
        elif isinstance(policy, MaterialCodePolicy):
            active = policy
        else:
            active = MaterialCodePolicy.from_project(policy or {})
        return active.suggest(name, category=category,
                              taken=self.existing_codes())
