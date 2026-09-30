"""Master-data layer: versioned engineering tables loaded from JSON, never hardcoded."""

from .schemas import (
    SCHEMA_VERSION, DOMAINS, REQUIRED_FIELDS, NULLABLE_NUMERIC_FIELDS,
    COMPONENT_KIND_DOMAINS, CROSS_DOMAIN_FIELDS, validate_record,
)
from .models import CrossDomainReference
from .repository import (
    DEFAULT_TABLES_DIR,
    MasterDataRepository,
    ResolvedValue,
    resolve,
)

__all__ = [
    "SCHEMA_VERSION", "DOMAINS", "REQUIRED_FIELDS", "NULLABLE_NUMERIC_FIELDS",
    "COMPONENT_KIND_DOMAINS", "CROSS_DOMAIN_FIELDS", "validate_record",
    "CrossDomainReference",
    "MasterDataRepository", "DEFAULT_TABLES_DIR",
    "ResolvedValue", "resolve",
]
