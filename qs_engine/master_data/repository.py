"""Master-data repository: JSON-table loader with typed lookup errors.

Calculators request records by (domain, key); missing domains or keys
raise typed errors. Nothing is defaulted, substituted, or zero-filled.

Phase 3.1: the shared ``resolve()`` executes the single fail-closed
precedence hierarchy every domain resolver used to re-implement —
explicit user override -> master-table value -> typed error — so the
domain engines keep only their use-time validation and result mapping.
"""

import json
from dataclasses import dataclass, fields as dataclass_fields
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..core.assumptions import VerificationStatus
from ..core.decimal_policy import to_decimal
from ..core.errors import (
    UnknownMasterDataDomainError,
    UnknownMasterDataKeyError,
    UnverifiedMasterDataError,
    ValidationError,
)
from ..core.validation import require_master_key
from .schemas import DOMAINS, PROVENANCE_FIELDS, SCHEMA_VERSION, validate_record

DEFAULT_TABLES_DIR = Path(__file__).parent / "tables"


@dataclass(frozen=True)
class ResolvedValue:
    """One generic resolution: merged values plus full provenance.

    ``values`` maps engine field name -> value (Decimal when coerced;
    None when neither an explicit override nor the master record supplies
    it). ``overridden_fields`` lists fields taken from the override model
    in resolution order; ``missing_fields`` lists required fields that
    resolved to None (always empty when ``strict`` resolution ran).
    """

    domain: str
    key: str
    values: Mapping[str, Any]
    record: Mapping[str, Any]
    verification_status: str
    master_version: str
    overridden_fields: Tuple[str, ...]
    missing_fields: Tuple[str, ...]

    @property
    def overrides_used(self) -> bool:
        """True when at least one field came from the explicit override."""
        return bool(self.overridden_fields)

    @property
    def verified(self) -> bool:
        """True when the record carries verified/provisional status."""
        return self.verification_status in (
            VerificationStatus.VERIFIED, VerificationStatus.PROVISIONAL)

    @property
    def unverified(self) -> bool:
        """True when the record is still NEEDS_VERIFICATION."""
        return self.verification_status == VerificationStatus.NEEDS_VERIFICATION


def resolve(repository, domain: str, key: str,
            override_model: Optional[Any] = None, *,
            fields=None, required=None, record_keys=None,
            coerce: bool = True, strict: bool = True,
            noun: Optional[str] = None) -> ResolvedValue:
    """Unified fail-closed master-data resolution (Phase 3.1).

    Precedence, applied strictly per field:

    1. Explicit user override — a non-None field on ``override_model``
       always wins and is recorded as provenance.
    2. Master-data record value from ``repository.get(domain, key)``.
    3. None — and when a *required* field stays None the call fails
       closed: ``UnverifiedMasterDataError`` for a NEEDS_VERIFICATION
       record (supply complete overrides or verify the record),
       ``ValidationError`` for a verified/provisional record with null
       numerics (incomplete record). Unknown domains/keys surface from
       ``get``/``table_version`` as their typed errors.

    Options (keyword-only):

    * ``fields`` — engine field names to merge, in resolution order.
      Default: the override model's dataclass fields, else the record's
      non-provenance keys.
    * ``required`` — fields that must resolve non-None (default:
      ``fields``). Optional extras (plant operating cost, truck hire/fuel)
      pass a subset so they stay legitimately None.
    * ``record_keys`` — field -> record key mapping for renamed fields
      (identity default).
    * ``coerce`` — Decimal-coerce merged values through the decimal
      policy (labour keeps raw gang counts with ``coerce=False``).
    * ``strict`` — raise on missing required fields. ``False`` returns
      them in ``missing_fields`` for wrappers implementing their own
      fallback (e.g. the rebar nominal-mass formula).
    * ``noun`` — human label for error messages (default: the domain).
    """
    record = repository.get(domain, key)
    status = record.get("verification_status")
    master_version = repository.table_version(domain)

    if fields is None:
        if override_model is not None:
            try:
                field_names = tuple(
                    f.name for f in dataclass_fields(override_model))
            except TypeError:
                field_names = None
        else:
            field_names = None
        if field_names is None:
            field_names = tuple(
                name for name in record if name not in PROVENANCE_FIELDS)
    else:
        field_names = tuple(fields)
    key_map = dict(record_keys) if record_keys else {}

    values: Dict[str, Any] = {}
    overridden: List[str] = []
    for field_name in field_names:
        override_value = (getattr(override_model, field_name, None)
                          if override_model is not None else None)
        record_key = key_map.get(field_name, field_name)
        record_value = record.get(record_key)
        if override_value is not None:
            values[field_name] = (to_decimal(override_value, field_name)
                                  if coerce else override_value)
            overridden.append(field_name)
        elif record_value is None:
            values[field_name] = None
        else:
            values[field_name] = (to_decimal(record_value, record_key)
                                  if coerce else record_value)

    required_names = tuple(required) if required is not None else field_names
    missing = [name for name in required_names if values.get(name) is None]
    if missing and strict:
        label = noun or domain
        if status == VerificationStatus.NEEDS_VERIFICATION:
            raise UnverifiedMasterDataError(
                f"{label} {key!r} is NEEDS_VERIFICATION and lacks verified "
                f"values for {missing}; supply complete explicit overrides "
                f"or verify the master-data record.")
        raise ValidationError(
            f"{label} {key!r} (status {status}) has null values for "
            f"{missing}; record is incomplete.")

    return ResolvedValue(
        domain=domain,
        key=key,
        values=values,
        record=record,
        verification_status=status,
        master_version=master_version,
        overridden_fields=tuple(overridden),
        missing_fields=tuple(missing),
    )


class MasterDataRepository:
    """Loads and serves versioned master-data tables from a directory.

    Expected layout: <tables_dir>/<domain>.json, each shaped::

        {"schema_version": "0.1", "records": [{...}, ...]}

    All records are schema-validated at load time.
    """

    def __init__(self, tables_dir=None):
        self.tables_dir = Path(tables_dir) if tables_dir is not None else DEFAULT_TABLES_DIR
        self._tables: Dict[str, Dict[str, Mapping[str, Any]]] = {}
        self._versions: Dict[str, str] = {}
        self._load_all()

    def _load_all(self) -> None:
        for domain in DOMAINS:
            path = self.tables_dir / f"{domain}.json"
            if not path.exists():
                # A missing table file is an empty table, not an error:
                # domains are populated incrementally across phases.
                self._tables[domain] = {}
                self._versions[domain] = ""
                continue
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in master-data table {path}: {exc}") from exc
            if payload.get("schema_version") != SCHEMA_VERSION:
                raise ValueError(
                    f"Master-data table {path} declares schema_version "
                    f"{payload.get('schema_version')!r}; expected {SCHEMA_VERSION!r}"
                )
            records = payload.get("records", [])
            indexed: Dict[str, Mapping[str, Any]] = {}
            for record in records:
                validate_record(domain, record)
                indexed[record["key"]] = record
            self._tables[domain] = indexed
            self._versions[domain] = payload.get("table_version", "")

    def domains(self) -> List[str]:
        """Return the known domain names."""
        return list(DOMAINS)

    def table_version(self, domain: str) -> str:
        """Return the loaded table version string for a domain."""
        if domain not in DOMAINS:
            raise UnknownMasterDataDomainError(f"Unknown domain {domain!r}")
        return self._versions[domain]

    def list(self, domain: str) -> List[Mapping[str, Any]]:
        """Return all records in a domain (possibly empty)."""
        if domain not in DOMAINS:
            raise UnknownMasterDataDomainError(f"Unknown domain {domain!r}")
        return list(self._tables[domain].values())

    def get(self, domain: str, key: str) -> Mapping[str, Any]:
        """Return one record by key; raise typed errors on miss."""
        if domain not in DOMAINS:
            raise UnknownMasterDataDomainError(f"Unknown domain {domain!r}")
        return require_master_key(self._tables[domain], key, domain)

    def resolve(self, domain: str, key: str,
                override_model: Optional[Any] = None, **options) -> ResolvedValue:
        """Generic fail-closed resolution: ``repo.resolve(domain, key, overrides)``.

        Same contract as the module-level ``resolve()`` (override ->
        master value -> typed error); exists so repository consumers can
        resolve in one call without importing the function separately.
        """
        return resolve(self, domain, key, override_model, **options)
